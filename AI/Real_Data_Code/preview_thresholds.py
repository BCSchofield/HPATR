#!/usr/bin/env python3
"""
preview_thresholds.py -- render detection overlays for parameter tuning.

Companion to extract_candidates.py. Runs the same detection logic and draws
the resulting object outlines on the 8-bit view, so threshold and blur
choices can be judged by eye rather than from counts.

Writes two images per parameter combination:
  full_*.png  whole frame  -- is coverage even? do the edges/vignette misbehave?
  zoom_*.png  3x crop      -- are the small detections real objects or noise?

Both are needed. At full-frame scale a 3-5 px fragment is sub-pixel and
invisible; at zoom you cannot see whether a whole region is being missed.
All combos share one zoom region so they are directly comparable.

Usage:
    python preview_thresholds.py --run-name 125917_NNA_3000sccm \\
        --frame 199 --seed 0.85 0.90 --grow 0.97 --blur 0.5
"""

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def detect(T, seed_t, grow_t, sigma, min_area):
    """Same hysteresis as extract_candidates.py -- keep these in step."""
    Ts = cv2.GaussianBlur(T, (0, 0), sigma) if sigma > 0 else T
    seed = (Ts < seed_t).astype(np.uint8)
    grow = (Ts < grow_t).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(grow, 8)
    seeded = set(np.unique(lab[seed > 0])) - {0}
    keep = np.zeros_like(grow)
    areas = []
    for i in range(1, n):
        if i in seeded and stats[i, 4] >= min_area:
            keep[lab == i] = 1
            areas.append(int(stats[i, 4]))
    return keep, areas


def main():
    ap = argparse.ArgumentParser(description="Render detection overlays for threshold tuning")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--frame", type=int, required=True, help="frame number (the n value)")
    ap.add_argument("--seed", type=float, nargs="+", default=[0.90])
    ap.add_argument("--grow", type=float, nargs="+", default=[0.97])
    ap.add_argument("--blur", type=float, nargs="+", default=[0.5])
    ap.add_argument("--min-area", type=int, default=4)
    ap.add_argument("--zoom", type=int, nargs=4, metavar=("X", "Y", "W", "H"),
                    default=[882, 133, 500, 300],
                    help="zoom region, shared by every combo so they compare directly")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    run16 = root / "00_frames" / args.run_name / "16bit"
    run8 = root / "00_frames" / args.run_name / "8bit"
    out = root / "01_candidates" / args.run_name / "_threshold_preview"
    out.mkdir(parents=True, exist_ok=True)

    matches = list_files(run16, f"*_n{args.frame}.tiff")
    if not matches:
        sys.exit(f"No frame n{args.frame} in {run16}")
    stem = matches[0].stem

    img = cv2.imread(str(matches[0]), cv2.IMREAD_UNCHANGED).astype(np.float32)
    view = cv2.imread(str(run8 / f"{stem}.png"), cv2.IMREAD_UNCHANGED)

    bg_path = root / "01_candidates" / args.run_name / "background_median.tiff"
    if not bg_path.exists():
        sys.exit(f"No cached background at {bg_path}. Run extract_candidates.py first.")
    bg = cv2.imread(str(bg_path), cv2.IMREAD_UNCHANGED).astype(np.float32)

    T = img / np.maximum(bg, 1.0)
    x, y, w, h = args.zoom

    print(f"frame n{args.frame}  zoom [{x},{y} {w}x{h}]")
    print(f"{'seed':>6} {'grow':>6} {'blur':>6} {'objects':>8} {'4-10px':>7} "
          f"{'10-25':>7} {'>25':>6}")

    for s in args.seed:
        for g in args.grow:
            for b in args.blur:
                keep, areas = detect(T, s, g, b, args.min_area)
                tiny = sum(1 for a in areas if a < 10)
                small = sum(1 for a in areas if 10 <= a < 25)
                big = sum(1 for a in areas if a >= 25)
                print(f"{s:6.2f} {g:6.2f} {b:6.2f} {len(areas):8d} {tiny:7d} "
                      f"{small:7d} {big:6d}")

                canvas = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)
                cont, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(canvas, cont, -1, (0, 0, 255), 1)

                tag = f"n{args.frame}_s{s}_g{g}_b{b}"
                label = f"seed<{s} grow<{g} blur{b}  {len(areas)} objects ({tiny} tiny)"

                full = canvas.copy()
                cv2.rectangle(full, (x, y), (x + w, y + h), (0, 255, 255), 2)
                cv2.putText(full, label, (10, 40), cv2.FONT_HERSHEY_SIMPLEX,
                            1.2, (0, 255, 255), 3)
                cv2.imwrite(str(out / f"full_{tag}.png"), full)

                z = cv2.resize(canvas[y:y + h, x:x + w], None, fx=3, fy=3,
                               interpolation=cv2.INTER_NEAREST)
                cv2.putText(z, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                            0.9, (0, 255, 255), 2)
                cv2.imwrite(str(out / f"zoom_{tag}.png"), z)

    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
