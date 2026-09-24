#!/usr/bin/env python3
"""
validation_to_coco.py -- Step 6 second half: LabelMe JSONs -> COCO ground truth.

Converts hand-drawn masks for the 15 validation frames into the SAME COCO/RLE
format and the SAME category IDs as the composited training set, so evaluation
compares like with like.

Reads  06_validation/labels/*.json   (LabelMe output)
Writes 06_validation/instances.json  (COCO)

Also reports the checks worth doing before trusting the ground truth: per-class
counts, size distribution against the training set, border-touching objects,
and -- most importantly -- any frame with zero annotations, which is almost
always a skipped frame rather than an empty one.

Usage:
    python validation_to_coco.py --run-name 125917_NNA_3000sccm
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

try:
    from pycocotools import mask as mask_util
except ImportError:
    sys.exit("pycocotools is required:  pip install pycocotools")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402

# Must match composite.py exactly, or the model's class indices mean one thing
# in training and another in evaluation.
CATEGORIES = [
    {"id": 1, "name": "droplet"},
    {"id": 2, "name": "filament"},
    {"id": 3, "name": "blob"},
]
CLASS_TO_ID = {c["name"]: c["id"] for c in CATEGORIES}
UM_PER_PX = 10.0

# An out-of-focus object is REAL but UNMEASURABLE: defocus spreads its edge, so
# any boundary drawn around it is wrong by an unknown amount. It is therefore
# kept as ground truth for detection (a model that finds it is correct, and must
# not be scored as a false positive) and excluded from size statistics -- exactly
# the treatment already given to border-touching objects.
#
# This is recorded per annotation as a measured number, not a human judgement:
# min_transmission comes from the 16-bit data, so the in-focus cutoff can be
# moved later, or swept, WITHOUT re-labelling anything.
FOCUS_MAX = 0.70


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def find_background(root: Path) -> Path:
    for run_dir in sorted((root / "01_candidates").iterdir()):
        cand = run_dir / "background_median.tiff"
        if cand.exists():
            return cand
    sys.exit("No cached background_median.tiff found under 01_candidates/*/")


def sauter_mean_diameter(areas_px) -> float:
    """D32 = sum(d^3) / sum(d^2), from equivalent-area diameters, in microns."""
    if not areas_px:
        return float("nan")
    d = 2.0 * np.sqrt(np.asarray(areas_px, dtype=np.float64) / np.pi) * UM_PER_PX
    return float((d ** 3).sum() / (d ** 2).sum())


def shape_to_mask(shape, h, w):
    """LabelMe shape -> binary mask. Handles polygon, mask, rectangle, circle."""
    st = shape.get("shape_type", "polygon")
    pts = np.array(shape["points"], dtype=np.float64)
    m = np.zeros((h, w), dtype=np.uint8)

    if st == "mask":
        # LabelMe 6.x AI-Mask: base64 PNG in the shape, placed at its bbox.
        import base64, io
        from PIL import Image
        raw = base64.b64decode(shape["mask"])
        sub = np.array(Image.open(io.BytesIO(raw))) > 0
        (x1, y1), (x2, y2) = pts[0], pts[1]
        x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
        sub = cv2.resize(sub.astype(np.uint8), (x2 - x1 + 1, y2 - y1 + 1),
                         interpolation=cv2.INTER_NEAREST)
        ys, xs = max(0, y1), max(0, x1)
        ye, xe = min(h, y1 + sub.shape[0]), min(w, x1 + sub.shape[1])
        if ye > ys and xe > xs:
            m[ys:ye, xs:xe] = sub[:ye - ys, :xe - xs]
    elif st == "rectangle":
        (x1, y1), (x2, y2) = pts[0], pts[1]
        cv2.rectangle(m, (int(x1), int(y1)), (int(x2), int(y2)), 1, -1)
    elif st == "circle":
        c, edge = pts[0], pts[1]
        r = int(round(np.linalg.norm(edge - c)))
        cv2.circle(m, (int(c[0]), int(c[1])), r, 1, -1)
    else:  # polygon / linestrip
        cv2.fillPoly(m, [pts.astype(np.int32)], 1)
    return m.astype(bool)


def main():
    ap = argparse.ArgumentParser(description="Convert LabelMe validation masks to COCO")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    val_dir = root / "06_validation"
    lab_dir = val_dir / "labels"
    frame_dir = val_dir / "frames" / "8bit"

    if not lab_dir.is_dir():
        sys.exit(f"No LabelMe output at {lab_dir}. See docs/VALIDATION_LABELLING_PROTOCOL.md")

    frames = list_files(frame_dir, "*.png")
    jsons = {p.stem: p for p in list_files(lab_dir, "*.json")}
    if not jsons:
        sys.exit(f"No .json files in {lab_dir} -- nothing labelled yet.")

    # Frames excluded from training must be exactly the frames validated here.
    manifest = json.loads((root / "00_manifest" / "validation_split.json")
                          .read_text(encoding="utf-8"))
    expected = {int(e["frame_number"]) for e in manifest["frames"]}

    images, annotations = [], []
    ann_id = 1
    per_class = Counter()
    per_frame = {}
    areas_by_class = defaultdict(list)
    measurable_by_class = defaultdict(list)
    n_border = 0
    n_out_of_focus = 0
    unknown_labels = Counter()

    bg = cv2.imread(str(find_background(root)), cv2.IMREAD_UNCHANGED).astype(np.float32)

    for i, fp in enumerate(frames, start=1):
        img = cv2.imread(str(fp), cv2.IMREAD_UNCHANGED)
        h, w = img.shape[:2]
        images.append({"id": i, "file_name": fp.name, "width": w, "height": h})

        jp = jsons.get(fp.stem)
        if jp is None:
            per_frame[fp.stem] = 0
            continue
        data = json.loads(jp.read_text(encoding="utf-8"))

        # Focus is measured from the 16-bit transmission data, never from the
        # 8-bit view LabelMe displays.
        raw = cv2.imread(str(val_dir / "frames" / "16bit" / f"{fp.stem}.tiff"),
                         cv2.IMREAD_UNCHANGED)
        if raw is None:
            sys.exit(f"No 16-bit frame for {fp.stem} -- cannot measure focus.")
        T = raw.astype(np.float32) / np.maximum(bg, 1.0)

        count = 0
        for sh in data.get("shapes", []):
            label = sh.get("label", "").strip()
            if label not in CLASS_TO_ID:
                unknown_labels[label] += 1
                continue
            m = shape_to_mask(sh, h, w)
            area = int(m.sum())
            if area < 1:
                continue
            ys, xs = np.where(m)
            x0, y0 = int(xs.min()), int(ys.min())
            bw, bh = int(xs.max() - x0 + 1), int(ys.max() - y0 + 1)
            touches = bool(x0 == 0 or y0 == 0 or x0 + bw >= w or y0 + bh >= h)
            n_border += touches

            t_min = float(T[m].min())
            in_focus = bool(t_min <= FOCUS_MAX)
            # Measurable = the size can be trusted. Real but unmeasurable objects
            # stay in the ground truth so detection is scored honestly.
            measurable = in_focus and not touches
            n_out_of_focus += not in_focus

            rle = mask_util.encode(np.asfortranarray(m.astype(np.uint8)))
            rle["counts"] = rle["counts"].decode("ascii")
            annotations.append({
                "id": ann_id, "image_id": i,
                "category_id": CLASS_TO_ID[label],
                "segmentation": rle, "area": float(area),
                "bbox": [x0, y0, bw, bh], "iscrowd": 0,
                "touches_border": touches,
                "min_transmission": round(t_min, 4),
                "in_focus": in_focus,
                "measurable": measurable,
            })
            ann_id += 1
            per_class[label] += 1
            areas_by_class[label].append(area)
            if measurable:
                measurable_by_class[label].append(area)
            count += 1
        per_frame[fp.stem] = count

    coco = {
        "info": {
            "description": "HPATR hand-masked validation ground truth",
            "run_name": args.run_name,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": "LabelMe, per docs/VALIDATION_LABELLING_PROTOCOL.md",
            "um_per_px": UM_PER_PX,
            "focus_max": FOCUS_MAX,
            "note": "NEVER trained on. Every annotation is a REAL object and counts "
                    "for detection scoring. Size statistics (D32, atomised fraction) "
                    "must use only annotations with measurable=true: "
                    "touches_border objects are cut off by the frame edge, and "
                    "in_focus=false objects are spread by defocus, so both have "
                    "unreliable size. min_transmission is stored per annotation, so "
                    "the focus cutoff can be moved or swept WITHOUT re-labelling.",
            "known_bias": "Focus-gating samples a size-dependent volume: small "
                          "droplets leave focus over a shorter axial distance than "
                          "large ones, so they are under-sampled and D32 is biased "
                          "upward. With fixed optics this largely cancels when "
                          "RANKING runs; it does not cancel in absolute terms.",
        },
        "images": images, "annotations": annotations, "categories": CATEGORIES,
    }
    out = val_dir / "instances.json"
    out.write_text(json.dumps(coco), encoding="utf-8")

    # ---- checks ----
    print(f"frames: {len(images)}   labelled: {sum(1 for v in per_frame.values() if v)}"
          f"   annotations: {len(annotations)}\n")
    print(f"{'class':10s} {'all':>6} {'measurable':>11}  {'D32 um':>8}  {'median um':>10}")
    for c in CATEGORIES:
        name = c["name"]
        n, meas = per_class[name], measurable_by_class[name]
        if meas:
            med = 2 * np.sqrt(float(np.median(meas)) / np.pi) * UM_PER_PX
            print(f"{name:10s} {n:6d} {len(meas):11d}  "
                  f"{sauter_mean_diameter(meas):8.0f}  {med:10.0f}")
        else:
            print(f"{name:10s} {n:6d} {len(meas):11d}  {'-':>8}  {'-':>10}")

    print(f"\nexcluded from size stats (still counted for detection):")
    print(f"  out of focus (t_min > {FOCUS_MAX}): {n_out_of_focus}")
    print(f"  border-touching:                {n_border}")

    # What the focus gate actually costs the number being reported.
    all_d = areas_by_class["droplet"]
    meas_d = measurable_by_class["droplet"]
    if all_d and meas_d and len(all_d) != len(meas_d):
        print(f"\ndroplet D32 using ALL annotations:        "
              f"{sauter_mean_diameter(all_d):.0f} um  (n={len(all_d)})")
        print(f"droplet D32 using measurable only:        "
              f"{sauter_mean_diameter(meas_d):.0f} um  (n={len(meas_d)})")
        print("  The second is the defensible number. The gap is the size-dependent")
        print("  sampling bias -- report it, do not try to remove it by relabelling.")

    empty = [k for k, v in per_frame.items() if v == 0]
    if empty:
        print(f"\n*** {len(empty)} FRAME(S) WITH ZERO ANNOTATIONS ***")
        for e in empty:
            print(f"      {e}")
        print("    The sparsest frame in this run still had 44 detected regions, so a")
        print("    zero here almost certainly means the frame was skipped, not that it")
        print("    is empty. Check before trusting any accuracy number built on this.")
    if unknown_labels:
        print(f"\n*** UNRECOGNISED LABELS (ignored): {dict(unknown_labels)} ***")
        print("    Expected exactly: droplet, filament, blob")

    # Did the labelled frames match the manifest's held-out set?
    labelled_nums = set()
    for stem, n in per_frame.items():
        if n and "_n" in stem:
            try:
                labelled_nums.add(int(stem.split("_n")[-1]))
            except ValueError:
                pass
    missing = expected - labelled_nums
    if missing:
        print(f"\nheld-out frames not yet labelled: {sorted(missing)}")

    counts = [v for v in per_frame.values()]
    print(f"\nobjects per frame: min {min(counts)}  median {int(np.median(counts))}  "
          f"max {max(counts)}   (extractor averaged ~55/frame on training frames)")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
