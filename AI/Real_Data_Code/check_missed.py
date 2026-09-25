#!/usr/bin/env python3
"""
check_missed.py -- Step 6 audit: find dark regions in a validation frame that
were NOT labelled.

READ-ONLY. Never modifies the labels file.

A missed object in a validation frame is worse than a missed object anywhere
else in this pipeline: the benchmark says it does not exist, so a model that
correctly detects it is scored as a false positive. That is the one error that
actively pushes the model in the wrong direction.

This finds every region the loose detector sees, subtracts everything already
covered by a hand-drawn shape, and reports what is left -- banded by how dark
it actually gets, because that is what decides whether it matters:

  t_min < 0.70   unambiguously in focus. If this is unlabelled it is a REAL
                 miss and should be fixed before the frame is accepted.
  0.70 - 0.80    borderline. Worth a look; labelling it is cheap and it will
                 be auto-excluded from size stats anyway.
  > 0.80         haze and sensor noise. Ignore -- no threshold makes these
                 objects, and labelling them would add noise to the benchmark.

Usage:
    python check_missed.py --frame frame_0072_n719
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from validation_to_coco import shape_to_mask  # noqa: E402
from _dust import dust_mask, is_dust  # noqa: E402

DETECT_THRESHOLD = 0.95
BLUR_SIGMA = 0.5
MIN_AREA = 4
FOCUS_MAX = 0.70


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
    ap = argparse.ArgumentParser(description="Find unlabelled dark regions in a validation frame")
    ap.add_argument("--frame", required=True)
    ap.add_argument("--min-area", type=int, default=MIN_AREA)
    ap.add_argument("--sliver-gap", type=float, default=15.0,
                    help="an unlabelled region closer than this to an existing "
                         "shape is a SLIVER -- a few px of boundary the trace "
                         "did not quite cover on an object already labelled, not "
                         "a separate object. Not actionable, so it is reported "
                         "but never drawn (default 15 px).")
    ap.add_argument("--show-all", action="store_true",
                    help="also draw borderline and haze regions and your existing "
                         "labels. Off by default: the image is an action list, and "
                         "drawing 500 noise specks buries the few that matter.")
    ap.add_argument("--val-dir", default="06_validation",
                    help="which validation set, e.g. 06_validation_run2")
    ap.add_argument("--run", default="125917_NNA_3000sccm",
                    help="the run these frames came from -- selects the temporal "
                         "median. MUST match, or every transmission value is wrong.")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    val = root / args.val_dir
    json_path = val / "labels" / f"{args.frame}.json"
    if not json_path.exists():
        sys.exit(f"No labels file: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    h, w = data["imageHeight"], data["imageWidth"]

    img = cv2.imread(str(val / "frames" / "16bit" / f"{args.frame}.tiff"),
                     cv2.IMREAD_UNCHANGED).astype(np.float32)
    bg = cv2.imread(str(find_background(root, args.run)), cv2.IMREAD_UNCHANGED).astype(np.float32)
    T = img / np.maximum(bg, 1.0)

    # Everything the human already covered. Dilated slightly so a region that
    # merely sits alongside a drawn shape is not called a miss.
    # Sensor specks are static, so they live in the background and vanish in T.
    # They must never be proposed as objects, and any still labelled is an error
    # worth surfacing -- see _dust.py and strip_dust.py.
    dust = dust_mask(bg)

    labelled = np.zeros((h, w), dtype=np.uint8)
    per_class = {}
    still_dust = 0
    for sh in data.get("shapes", []):
        m = shape_to_mask(sh, h, w)
        if is_dust(m, T, dust):
            still_dust += 1
        labelled |= m.astype(np.uint8)
        per_class[sh["label"]] = per_class.get(sh["label"], 0) + 1
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    covered = cv2.dilate(labelled, k).astype(bool)
    # Distance from every pixel to the nearest labelled pixel, used to tell a
    # separate missed object from a sliver of one already labelled.
    gap_to_label = cv2.distanceTransform(1 - labelled, cv2.DIST_L2, 5)

    Ts = cv2.GaussianBlur(T, (0, 0), BLUR_SIGMA)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(
        (Ts < DETECT_THRESHOLD).astype(np.uint8), 8)

    missed, slivers = [], []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < args.min_area:
            continue
        region = lab == i
        if covered[region].any():
            continue
        t_min = float(T[region].min())
        area = int(stats[i, cv2.CC_STAT_AREA])
        if dust[region].any() and t_min > 0.85:
            continue  # a sensor speck -- never propose it
        if t_min < FOCUS_MAX and float(gap_to_label[region].min()) < args.sliver_gap:
            slivers.append((t_min, area, region))
            continue
        missed.append((t_min, area, region))

    view = cv2.imread(str(val / "frames" / "8bit" / f"{args.frame}.png"), cv2.IMREAD_UNCHANGED)
    canvas = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR) if view.ndim == 2 else view.copy()

    tiers = [(0.00, FOCUS_MAX, (0, 0, 255), 14, "REAL MISS (in focus)"),
             (FOCUS_MAX, 0.80, (0, 140, 255), 9, "borderline"),
             (0.80, 1.01, (190, 190, 190), 4, "haze/noise")]
    counts = {t[4]: 0 for t in tiers}
    for t_min, area, region in missed:
        for lo, hi, col, rad, name in tiers:
            if lo <= t_min < hi:
                counts[name] += 1
                break

    # The image is an ACTION LIST: by default only the regions worth going back
    # for are drawn, numbered so they can be worked through against the printout.
    if args.show_all:
        cnts, _ = cv2.findContours(labelled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, cnts, -1, (0, 190, 0), 1)
        for t_min, area, region in missed:
            for lo, hi, col, rad, name in tiers:
                if lo <= t_min < hi and name != "REAL MISS (in focus)":
                    ys, xs = np.where(region)
                    cv2.circle(canvas, (int(xs.mean()), int(ys.mean())), rad, col, 1)
                    break

    actionable = sorted([m for m in missed if m[0] < FOCUS_MAX], key=lambda r: r[0])
    for num, (t_min, area, region) in enumerate(actionable, start=1):
        ys, xs = np.where(region)
        cx, cy = int(xs.mean()), int(ys.mean())
        cv2.circle(canvas, (cx, cy), 26, (0, 0, 255), 2)
        cv2.putText(canvas, str(num), (cx + 30, cy - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)

    y = 34
    cv2.putText(canvas, f"{len(actionable)} TO ADD (numbered)", (14, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    for num, (t_min, area, region) in enumerate(actionable, start=1):
        ys, xs = np.where(region)
        y += 30
        cv2.putText(canvas, f"{num}. ({xs.mean():.0f},{ys.mean():.0f})  {area} px  t_min {t_min:.2f}",
                    (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    y += 34
    cv2.putText(canvas, f"not shown: {len(slivers)} slivers on labelled objects, "
                        f"{counts['borderline']} borderline, {counts['haze/noise']} haze",
                (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (120, 120, 120), 2)

    out_dir = val / "review_images"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.frame}_missed.png"
    cv2.imwrite(str(out), canvas)

    print(f"\n{args.frame}")
    print(f"  labelled: {sum(per_class.values())} shapes  {per_class}")
    print(f"  unlabelled dark regions: {len(missed)}  (+ {len(slivers)} slivers, not actionable)")
    for lo, hi, col, rad, name in tiers:
        print(f"    {lo:.2f}-{hi:.2f}  {name:22s} {counts[name]}")

    if actionable:
        print(f"\n  *** {len(actionable)} TO ADD -- numbered on the review image ***")
        for num, (t_min, area, region) in enumerate(actionable, start=1):
            ys, xs = np.where(region)
            print(f"    {num:2d}. ({xs.mean():6.0f},{ys.mean():6.0f})  area {area:5d} px  t_min {t_min:.3f}")
    else:
        print("\n  Nothing to add -- no isolated unlabelled region reaches the focus cutoff.")
    if slivers:
        print(f"\n  {len(slivers)} sliver(s) ignored: in focus but within "
              f"{args.sliver_gap:.0f} px of a shape you already drew, i.e. boundary "
              f"your trace did not quite cover, not separate objects.")
    if still_dust:
        print(f"\n  *** {still_dust} labelled shape(s) still sit on sensor dust — "
              f"run strip_dust.py ***")
    print(f"\nreview: {out}")


if __name__ == "__main__":
    main()
