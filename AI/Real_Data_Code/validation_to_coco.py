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


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


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
    n_border = 0
    unknown_labels = Counter()

    for i, fp in enumerate(frames, start=1):
        img = cv2.imread(str(fp), cv2.IMREAD_UNCHANGED)
        h, w = img.shape[:2]
        images.append({"id": i, "file_name": fp.name, "width": w, "height": h})

        jp = jsons.get(fp.stem)
        if jp is None:
            per_frame[fp.stem] = 0
            continue
        data = json.loads(jp.read_text(encoding="utf-8"))

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

            rle = mask_util.encode(np.asfortranarray(m.astype(np.uint8)))
            rle["counts"] = rle["counts"].decode("ascii")
            annotations.append({
                "id": ann_id, "image_id": i,
                "category_id": CLASS_TO_ID[label],
                "segmentation": rle, "area": float(area),
                "bbox": [x0, y0, bw, bh], "iscrowd": 0,
                "touches_border": touches,
            })
            ann_id += 1
            per_class[label] += 1
            areas_by_class[label].append(area)
            count += 1
        per_frame[fp.stem] = count

    coco = {
        "info": {
            "description": "HPATR hand-masked validation ground truth",
            "run_name": args.run_name,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": "LabelMe, per docs/VALIDATION_LABELLING_PROTOCOL.md",
            "um_per_px": UM_PER_PX,
            "note": "NEVER trained on. touches_border objects have unreliable size "
                    "-- keep them for detection scoring, drop them from size stats.",
        },
        "images": images, "annotations": annotations, "categories": CATEGORIES,
    }
    out = val_dir / "instances.json"
    out.write_text(json.dumps(coco), encoding="utf-8")

    # ---- checks ----
    print(f"frames: {len(images)}   labelled: {sum(1 for v in per_frame.values() if v)}"
          f"   annotations: {len(annotations)}\n")
    print(f"{'class':10s} {'count':>6}  {'median px':>10} {'median um':>10}")
    for c in CATEGORIES:
        n = per_class[c["name"]]
        a = areas_by_class[c["name"]]
        if a:
            med = float(np.median(a))
            dia = 2 * np.sqrt(med / np.pi) * UM_PER_PX
            print(f"{c['name']:10s} {n:6d}  {med:10.0f} {dia:10.0f}")
        else:
            print(f"{c['name']:10s} {n:6d}  {'-':>10} {'-':>10}")
    print(f"\nborder-touching: {n_border}")

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
