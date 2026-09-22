#!/usr/bin/env python3
"""
extract_candidates.py -- Step 2 of the real-data pipeline.

Threshold + connected components over the training-pool frames, producing
one candidate object per detected region. See
docs/HANDOFF_real_data_pipeline.md.

NOTHING THIS SCRIPT PRODUCES IS TRAINING DATA. These are unreviewed first
drafts. Step 3 is where a human deletes the rubbish, fixes the class, and
corrects the mask edges. Training on raw threshold masks would just teach
the model to imitate the threshold.

Method:
  1. Background is a per-pixel temporal median across frames spread over the
     run, computed once and cached. Spray is transient and medians away;
     illumination, vignette and the fixed top-edge smudge are static and
     survive into the estimate, so those artefacts sit at T ~ 1 and are not
     detected as objects.
  2. Transmission T = I / I_bg. Shadowgraph is I = I_bg x T, so liquid
     absorbs and reads T < 1.
  3. Find candidate regions with a loose threshold, then judge each one
     individually:
       - Focus gate: if the region's darkest pixel never drops below
         --focus-max, it was never in focus. Reject it. Defocus inflates
         apparent size, so measuring such objects is untrustworthy.
       - Edge: per-object half-maximum, (t_min + 1) / 2. Standard
         shadowgraphy/PDIA practice. A global edge level cannot work --
         tried, and it put the boundary of a dark streak out in its diffuse
         halo, giving a mask both oversized and the wrong shape. A dark
         object (t_min 0.45) gets a tight edge at 0.72; a fainter one
         (t_min 0.80) gets 0.90.
  4. Measure each region from its refined mask.
  5. Guess a class from shape alone (no model exists yet -- Step 3 corrects).

Outputs per candidate, into 01_candidates/<run>/:
  transmission/  float32 TIFF crop of T   -- the data, used by the compositor
  masks/         binary PNG mask
  view8/         8-bit PNG crop           -- so LabelMe can display it in Step 3
  candidates.csv one row per candidate, with measurements and provenance

Note on precision: the handoff specifies a "16-bit transmission map". This
writes float32 instead -- same intent (do not quantise to 8-bit), but with
no scale factor to remember and no clipping of T values slightly above 1.
Crops are small, so the size cost is irrelevant.

Usage:
    python extract_candidates.py --run-name 125917_NNA_3000sccm --max-frames 5
    python extract_candidates.py --run-name 125917_NNA_3000sccm --frame-stride 10
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")


# Cross-platform drive resolution. Never hardcode /Volumes/... -- this runs on
# the Mac and the Windows training machine, where the LaCie is a drive letter.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Connect it, or pass --frames-root / "
                 "--output-root / --manifest explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"

UM_PER_PX = 10.0
# 200 um droplet/blob ceiling (Rayleigh-derived, see handoff decision 2).
DROPLET_CEILING_PX = 200.0 / UM_PER_PX   # 20 px equivalent diameter
# A filament is an object that is LONG RELATIVE TO ITS OWN WIDTH, measured
# along itself rather than around it. true_aspect = major_px / thread_width,
# where thread_width comes from the largest inscribed circle. This works for
# any shape -- straight, curved, V-shaped, looped -- because a thread is thin
# everywhere regardless of the path it takes.
#
# Bounding-box elongation (minAreaRect) and solidity were both tried and both
# failed. A crescent, a V and a loop all have near-square bounding boxes:
# measured elongation 1.36 / 1.44 / 1.49, versus 1.39 for a genuine compact
# droplet -- indistinguishable. Their true aspects are 6.5 / 6.3 / 7.6 versus
# 1.5 for the droplet. Solidity half-worked but promoted ragged-edged compact
# objects, and patching it with an elongation floor re-broke the curved shapes
# it existed to catch.
FILAMENT_TRUE_ASPECT = 3.0
# A filament must actually be long. Below this the shape metrics are measuring
# noise, not shape: 67 candidates under 10px area were being called filaments
# with a median major axis of 2.2 px. 20 px = 200 um, matching the droplet
# ceiling -- shorter than that and it is a fragment, whatever shape it is.
FILAMENT_MIN_LENGTH_PX = 20.0

CSV_FIELDS = [
    "candidate_id", "run", "frame_number", "object_index",
    "class_guess", "area_px", "equiv_diameter_px", "equiv_diameter_um",
    "major_px", "minor_px", "elongation", "solidity",
    "thread_width_px", "true_aspect", "extent",
    "bbox_x", "bbox_y", "bbox_w", "bbox_h",
    "centroid_x", "centroid_y",
    "touches_border", "min_transmission", "mean_transmission",
]


def load_excluded_frames(manifest_path: Path) -> set:
    """
    Frame numbers that must never be touched. These frames were also physically
    moved out of 00_frames/, but this check is the authoritative safeguard --
    a future run added to the pipeline may not be isolated the same way.
    """
    if not manifest_path.exists():
        sys.exit(f"Validation manifest not found: {manifest_path}\n"
                 f"Refusing to run without it -- see handoff Step 1.")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    return {int(entry["frame_number"]) for entry in manifest["frames"]}


def build_temporal_background(frame_paths: list, n_sample: int, cache: Path) -> np.ndarray:
    """
    Per-pixel median across frames spread over the run.

    Spray is transient, so it medians away; illumination, vignette and the
    fixed top-edge smudge are static, so they survive into the estimate and
    end up at T ~ 1 rather than being detected as objects.

    Greyscale morphological closing was tried first and rejected: it dilates
    before eroding, so the max over the kernel biases the estimate ~8% bright
    (image median 804 vs estimate 866 on this run). That put ordinary
    background below threshold, merging every real object into one 1.95M-px
    region. The temporal median puts background at exactly 1.0000.
    """
    if cache.exists():
        bg = cv2.imread(str(cache), cv2.IMREAD_UNCHANGED)
        if bg is not None:
            print(f"background: reusing cached {cache.name}")
            return bg.astype(np.float32)

    step = max(1, len(frame_paths) // n_sample)
    sample = frame_paths[::step][:n_sample]
    print(f"background: temporal median over {len(sample)} frames spread across the run")
    stack = np.stack([cv2.imread(str(p), cv2.IMREAD_UNCHANGED) for p in sample])
    bg = np.median(stack.astype(np.float32), axis=0)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(cache), bg.astype(np.float32))
    return bg


def measure_region(mask: np.ndarray, t_crop: np.ndarray) -> dict:
    """Shape and transmission stats for one candidate region."""
    area = float(mask.sum())
    equiv_d = 2.0 * np.sqrt(area / np.pi)

    contours, _ = cv2.findContours(mask.astype(np.uint8),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solidity = 1.0
    if contours:
        largest = max(contours, key=cv2.contourArea)
        # minAreaRect over fitEllipse: fitEllipse needs >=5 points and the
        # smallest real fragments are 3-5 px.
        (_, _), (w, h), _ = cv2.minAreaRect(largest)
        major, minor = max(w, h), min(w, h)
        # Solidity = area / convex hull area. This is what catches CURVED
        # filaments: a U or S shaped thread does not fill its own hull (the
        # space inside the curve is empty), while a droplet does. Elongation
        # alone fails on them -- a U-shaped thread has a near-square
        # minAreaRect, so it reads as compact.
        hull_area = cv2.contourArea(cv2.convexHull(largest))
        if hull_area > 0:
            solidity = float(cv2.contourArea(largest) / hull_area)
    else:
        major = minor = 0.0

    elongation = (major / minor) if minor > 0.5 else (major if major > 0 else 1.0)

    # Largest inscribed circle -> the object's own width at its widest point.
    # For a thread this is the thread width whatever path it takes; for a
    # compact mass it is most of the object.
    dist = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    thread_width = float(dist.max()) * 2.0
    true_aspect = (major / thread_width) if thread_width > 0 else 1.0

    bbox_area = mask.shape[0] * mask.shape[1]
    extent = area / bbox_area if bbox_area else 0.0

    vals = t_crop[mask]
    return {
        "area_px": area,
        "equiv_diameter_px": equiv_d,
        "equiv_diameter_um": equiv_d * UM_PER_PX,
        "major_px": major,
        "minor_px": minor,
        "elongation": elongation,
        "solidity": solidity,
        "thread_width_px": thread_width,
        "true_aspect": true_aspect,
        "extent": extent,
        "min_transmission": float(vals.min()) if vals.size else float("nan"),
        "mean_transmission": float(vals.mean()) if vals.size else float("nan"),
    }


def guess_class(m: dict) -> str:
    """
    Shape-only heuristic standing in for the model that does not exist yet.
    Step 3 exists precisely because this will be wrong a lot.
    """
    # Long enough for shape to mean anything, and thin relative to its own
    # width along its length. One rule, correct for any shape.
    if (m["major_px"] >= FILAMENT_MIN_LENGTH_PX
            and m["true_aspect"] >= FILAMENT_TRUE_ASPECT):
        return "filament"
    return "droplet" if m["equiv_diameter_px"] <= DROPLET_CEILING_PX else "blob"


def main():
    ap = argparse.ArgumentParser(description="Extract candidate objects from training-pool frames")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--detect-threshold", type=float, default=0.95,
                    help="loose net for finding candidate regions (default 0.95). "
                         "Only finds regions -- the mask edge is set per-object "
                         "at half-maximum, so this is not a size-defining value.")
    ap.add_argument("--focus-max", type=float, default=0.70,
                    help="reject an object whose darkest pixel is not below this "
                         "(default 0.80). THIS IS THE OUT-OF-FOCUS CUTOFF: a soft "
                         "blob never reaches it. Handoff Step 6 -- hand-masking "
                         "must apply the same rule or validation and training "
                         "disagree about what counts as an object.")
    ap.add_argument("--blur-sigma", type=float, default=0.5,
                    help="gaussian sigma on T before finding regions, 0 to disable "
                         "(default 0.5). Only affects region finding; saved crops "
                         "and the half-max edge use unblurred T. Do not raise much "
                         "above 0.5: at 1.0 the 3-5px fragment class is wiped out.")
    ap.add_argument("--max-pieces", type=int, default=1,
                    help="reject if the refined mask breaks into more than this many "
                         "pieces (default 1). This is the out-of-focus detector: a "
                         "shallow core puts the half-max edge in noise and the mask "
                         "shatters. Calibrated on hand-labelled examples -- in-focus "
                         "objects stay whole, out-of-focus ones fragment badly.")
    ap.add_argument("--min-area", type=int, default=4,
                    help="drop regions smaller than this many px (default 4)")
    ap.add_argument("--bg-frames", type=int, default=40,
                    help="frames sampled for the temporal median background (default 40)")
    ap.add_argument("--pad", type=int, default=12,
                    help="context margin around each crop (default 12)")
    ap.add_argument("--frame-stride", type=int, default=10,
                    help="process every Nth training frame (default 10)")
    ap.add_argument("--max-frames", type=int, default=None,
                    help="stop after N frames (dry run)")
    ap.add_argument("--max-candidates", type=int, default=20000,
                    help="safety cap on total candidates written")
    ap.add_argument("--frames-root", type=Path, default=None)
    ap.add_argument("--output-root", type=Path, default=None)
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    root = real_data_root()
    if args.frames_root is None:
        args.frames_root = root / "00_frames"
    if args.output_root is None:
        args.output_root = root / "01_candidates"
    if args.manifest is None:
        args.manifest = root / "00_manifest" / "validation_split.json"

    excluded = load_excluded_frames(args.manifest)
    print(f"Validation manifest: {len(excluded)} frame numbers excluded")

    dir_16 = args.frames_root / args.run_name / "16bit"
    dir_8 = args.frames_root / args.run_name / "8bit"
    if not dir_16.is_dir():
        sys.exit(f"No such run folder: {dir_16}")

    out_dir = args.output_root / args.run_name
    d_trans = out_dir / "transmission"
    d_mask = out_dir / "masks"
    d_view = out_dir / "view8"

    existing = list_files(d_trans, "*.tiff")
    if existing and not args.overwrite:
        sys.exit(f"{out_dir} already holds {len(existing)} candidates.\n"
                 f"Re-run with --overwrite, or use a different --run-name.")
    if existing and args.overwrite:
        print(f"--overwrite: clearing {len(existing)} existing candidates")
        for d in (d_trans, d_mask, d_view):
            for p in list_files(d):
                p.unlink()

    for d in (d_trans, d_mask, d_view):
        d.mkdir(parents=True, exist_ok=True)

    # Frame numbers come from the filename, not from position on disk.
    frames = []
    for p in list_files(dir_16, "*.tiff"):
        n = int(p.stem.split("_n")[-1])
        frames.append((n, p))
    frames.sort()

    leaked = [n for n, _ in frames if n in excluded]
    if leaked:
        sys.exit(f"ABORT: validation frames present in training pool: {leaked}\n"
                 f"These must never be processed. Investigate before continuing.")

    selected = frames[::args.frame_stride]
    if args.max_frames:
        selected = selected[:args.max_frames]
    print(f"{len(frames)} training frames available, processing {len(selected)} "
          f"(stride {args.frame_stride})")
    if args.max_frames:
        print(f"  DRY RUN -- limited to {args.max_frames} frames")
    print(f"detect T<{args.detect_threshold}  focus_max T<{args.focus_max}  "
          f"blur={args.blur_sigma}  min_area={args.min_area}px  pad={args.pad}px")
    print("edge: per-object half-maximum, (t_min + 1) / 2")

    # Built from the training pool only -- validation frames are already absent.
    bg = build_temporal_background([p for _, p in frames], args.bg_frames,
                                   out_dir / "background_median.tiff")

    rows = []
    n_written = 0
    capped = False

    for f_i, (frame_n, path16) in enumerate(selected):
        img = cv2.imread(str(path16), cv2.IMREAD_UNCHANGED)
        if img is None:
            print(f"  [WARN] unreadable, skipping: {path16.name}")
            continue

        path8 = dir_8 / (path16.stem + ".png")
        view = cv2.imread(str(path8), cv2.IMREAD_UNCHANGED)

        T = img.astype(np.float32) / np.maximum(bg, 1.0)

        # Cast a loose net to find candidate regions, then decide each one
        # individually. A single global edge level cannot work here: it puts
        # the boundary of a dark streak out in its diffuse halo, producing a
        # mask that is both oversized and the wrong shape.
        Ts = cv2.GaussianBlur(T, (0, 0), args.blur_sigma) if args.blur_sigma > 0 else T
        cand = (Ts < args.detect_threshold).astype(np.uint8)
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(cand, 8)

        H, W = img.shape
        kept = 0
        for lab in range(1, n_labels):           # 0 is background
            x, y, w, h, area = stats[lab]
            if area < args.min_area:
                continue

            region_full = (labels == lab)
            t_min = float(T[region_full].min())

            # Focus gate. An object whose core never gets this dark was never
            # in focus -- defocus inflates apparent size, so measuring it
            # would be untrustworthy. See handoff Step 6 (out-of-focus cutoff).
            if t_min > args.focus_max:
                continue

            # Per-object half-maximum edge: boundary midway between this
            # object's darkest point and background. Standard shadowgraphy /
            # PDIA practice, and it adapts to each object instead of forcing
            # one level on all of them.
            edge = (t_min + 1.0) / 2.0
            region_full = region_full & (T < edge)
            area = int(region_full.sum())
            if area < args.min_area:
                continue

            # Fragmentation gate -- the strongest out-of-focus signal found.
            # When an object's core is shallow, its half-maximum edge lands in
            # noise and the refined mask shatters into disconnected specks.
            # Calibrated against three hand-labelled examples (Ben, 2026-09-20):
            # in-focus filament = 1 piece, borderline = 1 piece, clearly
            # out-of-focus = 40 pieces. Size-independent, unlike a contrast
            # threshold: a small in-focus droplet stays whole, so this does not
            # penalise the fragment class the way lowering --focus-max would.
            n_pieces, _, piece_stats, _ = cv2.connectedComponentsWithStats(
                region_full.astype(np.uint8), 8)
            real_pieces = sum(1 for p in range(1, n_pieces)
                              if piece_stats[p, 4] >= args.min_area)
            if real_pieces > args.max_pieces:
                continue
            ys, xs = np.where(region_full)
            x, y = int(xs.min()), int(ys.min())
            w, h = int(xs.max() - x + 1), int(ys.max() - y + 1)
            if n_written >= args.max_candidates:
                capped = True
                break

            x0, y0 = max(0, x - args.pad), max(0, y - args.pad)
            x1, y1 = min(W, x + w + args.pad), min(H, y + h + args.pad)

            region = region_full[y0:y1, x0:x1]
            t_crop = T[y0:y1, x0:x1]
            m = measure_region(region, t_crop)
            cls = guess_class(m)

            cid = f"n{frame_n}_o{lab:04d}"
            cv2.imwrite(str(d_trans / f"{cid}.tiff"), t_crop.astype(np.float32))
            cv2.imwrite(str(d_mask / f"{cid}.png"), region.astype(np.uint8) * 255)
            if view is not None:
                cv2.imwrite(str(d_view / f"{cid}.png"), view[y0:y1, x0:x1])

            rows.append({
                "candidate_id": cid,
                "run": args.run_name,
                "frame_number": frame_n,
                "object_index": lab,
                "class_guess": cls,
                "bbox_x": x, "bbox_y": y, "bbox_w": w, "bbox_h": h,
                "centroid_x": round(float(centroids[lab][0]), 2),
                "centroid_y": round(float(centroids[lab][1]), 2),
                "touches_border": bool(x == 0 or y == 0 or x + w >= W or y + h >= H),
                **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()},
            })
            n_written += 1
            kept += 1

        print(f"  [{f_i+1}/{len(selected)}] n{frame_n}: {kept} candidates "
              f"({n_labels-1} regions found)")
        if capped:
            print(f"  [STOP] hit --max-candidates ({args.max_candidates})")
            break

    csv_path = out_dir / "candidates.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    by_class = {}
    for r in rows:
        by_class[r["class_guess"]] = by_class.get(r["class_guess"], 0) + 1
    n_border = sum(1 for r in rows if r["touches_border"])

    meta = {
        "run_name": args.run_name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "frames_available": len(frames),
        "frames_processed": len(selected),
        "frame_stride": args.frame_stride,
        "parameters": {
            "detect_threshold": args.detect_threshold,
            "focus_max": args.focus_max,
            "blur_sigma": args.blur_sigma,
            "edge_rule": "per-object half-maximum: (t_min + 1) / 2",
            "max_pieces": args.max_pieces,
            "min_area_px": args.min_area,
            "background": f"temporal median over {args.bg_frames} frames",
            "pad_px": args.pad,
        },
        "validation_frames_excluded": sorted(excluded),
        "candidates_total": len(rows),
        "candidates_by_class_guess": by_class,
        "candidates_touching_border": n_border,
        "um_per_px": UM_PER_PX,
        "droplet_ceiling_px": DROPLET_CEILING_PX,
        "note": ("Unreviewed first-draft candidates. class_guess is a shape-only "
                 "heuristic, not a model output. Nothing here is training data "
                 "until Step 3 review. transmission/ holds float32 T = I/I_bg."),
    }
    (out_dir / "extraction_params.json").write_text(json.dumps(meta, indent=2),
                                                    encoding="utf-8")

    print(f"\nDone. {len(rows)} candidates -> {out_dir}")
    for cls, n in sorted(by_class.items()):
        print(f"  {cls:9s} {n}")
    print(f"  touching border: {n_border}")
    print(f"  index: {csv_path}")


if __name__ == "__main__":
    main()
