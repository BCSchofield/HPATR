#!/usr/bin/env python3
"""
prelabel_frame.py -- Step 6 helper: PROPOSE LabelMe shapes for a validation
frame, for a human to correct.

WHAT THIS IS, AND WHAT IT IS NOT
---------------------------------
This writes a PROPOSAL, not ground truth.

It runs the same detector that built the training data (extract_candidates.py's
loose net -> per-object half-maximum edge -> shape heuristic). So anything it
gets systematically wrong, the model was also trained to get wrong -- most
importantly the small-object focus bias documented in the handoff, where tiny
objects physically cannot reach the same peak darkness as large ones.

Scoring a model against un-reviewed output from this script would measure
"does the model reproduce the extractor", not "does the model find real
objects", and would hide exactly the bias the validation set exists to expose.

Every shape written here must be reviewed by hand in LabelMe before the frame
counts as ground truth. This saves drawing time; it does not make the call.

WHAT IT DOES
------------
1. Loose net at --detect-threshold finds candidate regions (not object edges).
2. Each region's darkest pixel sets its own half-maximum edge, (t_min + 1) / 2
   -- the same rule used everywhere else in this pipeline.
3. Regions whose darkest pixel never reaches --focus-max are REJECTED as
   out-of-focus, and drawn in red on the review image so the cutoff itself can
   be judged by eye rather than taken on trust.
4. Surviving pieces are classified with extract_candidates.guess_class
   (true_aspect for filaments, equivalent-diameter ceiling for droplet/blob)
   and written as LabelMe shapes -- circles for round droplets (equivalent-area
   radius, so D32 stays correct), polygons otherwise.

KNOWN LIMITATION, STATED LOUDLY
--------------------------------
A region whose refined mask breaks into several pieces is emitted as several
separate shapes, never silently merged across a gap. For filaments this is
usually WRONG: brightness varies along a filament's length, so its faint
sections can drop below its own half-max edge and one real object arrives as
three. Merging those back together in LabelMe is part of the review.

Usage:
    python prelabel_frame.py --frame frame_0072_n719
    python prelabel_frame.py --frame frame_0072_n719 --focus-max 0.75
"""

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from extract_candidates import measure_region, guess_class  # noqa: E402
from refine_labels import mask_to_points  # noqa: E402

DETECT_THRESHOLD = 0.95   # loose net, matches extract_candidates.py
BLUR_SIGMA = 0.5
MIN_AREA = 4
FOCUS_MAX = 0.70          # out-of-focus cutoff, matches the rest of the pipeline

COLOURS = {                       # BGR
    "droplet": (0, 200, 0),
    "filament": (255, 130, 0),
    "blob": (0, 180, 255),
    "rejected": (0, 0, 255),
}


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def find_background(root: Path, run: str = None) -> Path:
    """
    The run's cached temporal median.

    `run` is REQUIRED once more than one run exists. The old behaviour -- take
    the first 01_candidates/* directory that has one -- silently picked by
    alphabetical order, so adding run 101947 would have had it used against
    run 125917's frames, making every transmission value wrong. Refuses to
    guess rather than pick the wrong illumination field.
    """
    if run:
        cand = root / "01_candidates" / run / "background_median.tiff"
        if not cand.exists():
            sys.exit(f"No cached background_median.tiff for run '{run}' at {cand}")
        return cand
    runs = sorted(d.name for d in (root / "01_candidates").iterdir()
                  if (d / "background_median.tiff").exists() and not d.name.endswith("backup"))
    if len(runs) == 1:
        return root / "01_candidates" / runs[0] / "background_median.tiff"
    sys.exit(f"More than one run has a cached background "
             f"({', '.join(runs)}). Pass --run explicitly -- using the wrong "
             f"run's median makes every transmission value wrong.")


def main():
    ap = argparse.ArgumentParser(description="Propose LabelMe shapes for a validation frame")
    ap.add_argument("--frame", required=True, help="frame stem, e.g. frame_0072_n719")
    ap.add_argument("--detect-threshold", type=float, default=DETECT_THRESHOLD)
    ap.add_argument("--focus-max", type=float, default=FOCUS_MAX,
                    help="out-of-focus cutoff. Raise it to keep fainter objects, "
                         "lower it to keep only hard-edged ones.")
    ap.add_argument("--min-area", type=int, default=MIN_AREA)
    ap.add_argument("--review-band", type=float, default=0.10,
                    help="only draw rejects whose t_min falls within this much of "
                         "the cutoff (default 0.10, i.e. 0.70-0.80). Rejects far "
                         "above the cutoff are noise and haze -- drawing all of them "
                         "buries the handful that are actually arguable. All rejects "
                         "are still counted and reported.")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    val_dir = root / "06_validation"
    json_path = val_dir / "labels" / f"{args.frame}.json"
    tiff_path = val_dir / "frames" / "16bit" / f"{args.frame}.tiff"
    view_path = val_dir / "frames" / "8bit" / f"{args.frame}.png"
    review_dir = val_dir / "review_images"
    review_dir.mkdir(parents=True, exist_ok=True)

    if not tiff_path.exists():
        sys.exit(f"No 16-bit frame: {tiff_path}")

    # Never clobber existing hand-drawn work without a copy of it.
    if json_path.exists():
        existing = json.loads(json_path.read_text(encoding="utf-8"))
        if existing.get("shapes"):
            backup = json_path.with_suffix(".prelabel_backup.json")
            if not backup.exists():
                shutil.copy2(json_path, backup)
                print(f"existing {len(existing['shapes'])} shapes backed up -> {backup.name}")
    else:
        existing = None

    img = cv2.imread(str(tiff_path), cv2.IMREAD_UNCHANGED).astype(np.float32)
    bg = cv2.imread(str(find_background(root)), cv2.IMREAD_UNCHANGED).astype(np.float32)
    T = img / np.maximum(bg, 1.0)
    h, w = T.shape[:2]

    Ts = cv2.GaussianBlur(T, (0, 0), BLUR_SIGMA)
    cand = (Ts < args.detect_threshold).astype(np.uint8)
    n_lab, lab, stats, _ = cv2.connectedComponentsWithStats(cand, 8)

    shapes = []
    rejected = []            # (mask, reason, t_min) for the review image
    n_split = 0
    per_class = Counter()
    reasons = Counter()

    for i in range(1, n_lab):
        if stats[i, cv2.CC_STAT_AREA] < args.min_area:
            continue
        region = lab == i
        t_min = float(T[region].min())

        if t_min > args.focus_max:
            rejected.append((region, "out_of_focus", t_min))
            reasons["out_of_focus"] += 1
            continue

        edge = (t_min + 1.0) / 2.0
        refined = region & (T < edge)
        if refined.sum() < args.min_area:
            rejected.append((region, "too_small_after_refine", t_min))
            reasons["too_small_after_refine"] += 1
            continue

        # Each surviving piece is its own proposal -- never merged across a gap.
        n_p, lab_p, stats_p, _ = cv2.connectedComponentsWithStats(
            refined.astype(np.uint8), 8)
        pieces = [j for j in range(1, n_p) if stats_p[j, cv2.CC_STAT_AREA] >= args.min_area]
        if len(pieces) > 1:
            n_split += 1

        for j in pieces:
            piece = lab_p == j
            x, y, bw, bh = (stats_p[j, cv2.CC_STAT_LEFT], stats_p[j, cv2.CC_STAT_TOP],
                            stats_p[j, cv2.CC_STAT_WIDTH], stats_p[j, cv2.CC_STAT_HEIGHT])
            m = measure_region(piece[y:y + bh, x:x + bw], T[y:y + bh, x:x + bw])
            label = guess_class(m)

            points, shape_type, status = mask_to_points(piece, label)
            if points is None:
                rejected.append((piece, f"trace_{status}", t_min))
                reasons[f"trace_{status}"] += 1
                continue

            shapes.append({
                "label": label,
                "points": points,
                "group_id": None,
                "description": "",
                "shape_type": shape_type,
                "flags": {},
                "mask": None,
            })
            per_class[label] += 1

    template = existing or {
        "version": "6.3.1", "flags": {},
        "imagePath": f"../frames/8bit/{args.frame}.png",
        "imageData": None, "imageHeight": h, "imageWidth": w,
    }
    template["shapes"] = shapes
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(template, indent=2), encoding="utf-8")

    # ---- review image ----
    view = cv2.imread(str(view_path), cv2.IMREAD_UNCHANGED)
    canvas = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR) if view.ndim == 2 else view.copy()

    band_limit = args.focus_max + args.review_band
    drawn_rejects = [r for r in rejected if r[2] < band_limit]
    for mask, reason, t_min in drawn_rejects:
        cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, cnts, -1, COLOURS["rejected"], 1)
        ys, xs = np.where(mask)
        cv2.circle(canvas, (int(xs.mean()), int(ys.mean())), 9,
                   COLOURS["rejected"], 1)

    for sh in shapes:
        pts = np.array(sh["points"], dtype=np.float64)
        col = COLOURS[sh["label"]]
        if sh["shape_type"] == "circle":
            c, e = pts[0], pts[1]
            cv2.circle(canvas, (int(c[0]), int(c[1])),
                       max(int(round(np.linalg.norm(e - c))), 1), col, 1)
        else:
            cv2.polylines(canvas, [pts.astype(np.int32)], True, col, 1)

    y0 = 34
    for text, col in [
        (f"KEPT droplet {per_class['droplet']}", COLOURS["droplet"]),
        (f"KEPT filament {per_class['filament']}", COLOURS["filament"]),
        (f"KEPT blob {per_class['blob']}", COLOURS["blob"]),
        (f"REJECTED shown {len(drawn_rejects)} of {len(rejected)}"
         f"  (t_min {args.focus_max}-{band_limit:.2f}; rest are noise/haze)",
         COLOURS["rejected"]),
    ]:
        cv2.putText(canvas, text, (14, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
        y0 += 32

    review_path = review_dir / f"{args.frame}_prelabel.png"
    cv2.imwrite(str(review_path), canvas)

    # ---- report ----
    print(f"\n{args.frame}  (detect<{args.detect_threshold}, focus-max {args.focus_max})")
    print(f"  candidate regions found: {n_lab - 1}")
    print(f"  proposed shapes:         {len(shapes)}")
    for c in ("droplet", "filament", "blob"):
        print(f"    {c:9s} {per_class[c]}")
    print(f"  rejected:                {len(rejected)}")
    for reason, n in reasons.most_common():
        print(f"    {reason:24s} {n}")

    # How close were the rejects to making the cut? Only the band just above the
    # cutoff is arguable -- the rest are too pale to be liquid at any threshold.
    if rejected:
        t_mins = np.array([r[2] for r in rejected])
        print(f"\n  reject darkness (t_min: 1.0 = background, lower = darker):")
        edges = [args.focus_max, args.focus_max + 0.05, args.focus_max + 0.10,
                 args.focus_max + 0.15, args.focus_max + 0.20, 1.01]
        for lo, hi in zip(edges, edges[1:]):
            n = int(((t_mins >= lo) & (t_mins < hi)).sum())
            if n:
                tag = "  <- arguable, drawn on review image" if hi <= band_limit else ""
                print(f"    {lo:.2f} - {hi:.2f}   {n:5d}{tag}")
    if n_split:
        print(f"\n  {n_split} region(s) split into multiple pieces -- check these for")
        print("  filaments broken into fragments by their own half-max edge.")
    print("\n  THIS IS A PROPOSAL, NOT GROUND TRUTH. Review every shape in LabelMe.")
    print(f"\nwritten: {json_path}")
    print(f"review:  {review_path}")


if __name__ == "__main__":
    main()
