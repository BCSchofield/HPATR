#!/usr/bin/env python3
"""
run_stats.py -- measurement statistics for an UNLABELLED set of frames.

This is the production-path counterpart to score_v2.py. score_v2 needs hand
labels and reports ACCURACY. A real experimental run has no labels, so the only
questions that can be asked are about the measurement itself:

  - what does the model measure, pooled over the run?
  - how much does it scatter frame to frame?
  - how many frames are needed before the number stops moving?
  - how far apart do two runs have to be before the difference is real?

That last one is what decides whether this instrument can rank a Taguchi array.
Accuracy (bias) cancels when comparing two runs measured the same way;
PRECISION does not.

D32 is POOLED, never averaged per frame -- it is a ratio of sums, so every
droplet in the set goes into one sum. Averaging per-frame D32 values weights a
3-droplet frame the same as a 300-droplet one and is simply wrong.

Usage:
    python run_stats.py --pred <...>/v3_predictions.json \\
        --val-dir 09_experiments/20_new_frames --score-thresh 0.30
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    from pycocotools import mask as mask_util
except ImportError:
    sys.exit("pycocotools is required:  pip install pycocotools")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402

UM_PER_PX = 10.0
CAT = {1: "droplet", 2: "filament", 3: "blob"}


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def equiv_um(area):
    return 2.0 * np.sqrt(np.asarray(area, dtype=float) / np.pi) * UM_PER_PX


def d32(areas):
    if len(areas) == 0:
        return float("nan")
    d = equiv_um(areas)
    return float((d ** 3).sum() / (d ** 2).sum())


def class_area_union(dets):
    """Union within (frame, class), summed across frames -- never the sum of
    instances. One long filament is emitted as several overlapping
    sub-segments; summing double-counts the overlap."""
    by = defaultdict(lambda: defaultdict(list))
    for d in dets:
        by[d["image_id"]][d["category_id"]].append(d["segmentation"])
    tot = defaultdict(float)
    for _img, per_class in by.items():
        for c, rles in per_class.items():
            tot[c] += float(mask_util.area(mask_util.merge(rles)))
    return tot


def atomised_pct(dets):
    u = class_area_union(dets)
    total = sum(u.values())
    return (u.get(1, 0.0) / total * 100) if total else float("nan")


def bootstrap(per_frame_dets, stat_fn, n_boot=2000, seed=0):
    """Resample FRAMES (not droplets) with replacement.

    Frames are the independent unit here: droplets within a frame share an
    illumination field, a focal plane and a moment of the spray, so resampling
    droplets would treat correlated samples as independent and give a
    falsely tight interval.
    """
    rng = np.random.default_rng(seed)
    keys = list(per_frame_dets)
    vals = []
    for _ in range(n_boot):
        pick = rng.choice(len(keys), size=len(keys), replace=True)
        pooled = []
        for i in pick:
            pooled.extend(per_frame_dets[keys[i]])
        vals.append(stat_fn(pooled))
    v = np.array([x for x in vals if np.isfinite(x)])
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)), float(v.std())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--val-dir", default="06_validation")
    ap.add_argument("--score-thresh", type=float, default=0.30,
                    help="measurement operating point (default 0.30)")
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args()

    root = args.root or real_data_root()
    val = root / args.val_dir
    manifest = json.loads((val / "instances.json").read_text(encoding="utf-8"))
    name_by_id = {im["id"]: im["file_name"] for im in manifest["images"]}

    preds = json.loads(args.pred.read_text(encoding="utf-8"))
    kept = [d for d in preds
            if d["score"] >= args.score_thresh and not d.get("truncated", False)]

    per_frame = {i: [] for i in name_by_id}
    for d in kept:
        per_frame.setdefault(d["image_id"], []).append(d)

    print(f"frames: {len(name_by_id)}   detections >= {args.score_thresh:.2f} "
          f"and not truncated: {len(kept)}  (of {len(preds)} raw)\n")

    print(f"{'frame':>22} {'drop':>6} {'fil':>5} {'blob':>5} {'D32 um':>8} {'atom %':>8}")
    d32s, atoms, counts = [], [], []
    for img_id in sorted(per_frame):
        dets = per_frame[img_id]
        dro = [d["area"] for d in dets if d["category_id"] == 1]
        nf = sum(1 for d in dets if d["category_id"] == 2)
        nb = sum(1 for d in dets if d["category_id"] == 3)
        v, a = d32(dro), atomised_pct(dets)
        d32s.append(v); atoms.append(a); counts.append(len(dro))
        print(f"{Path(name_by_id[img_id]).stem:>22} {len(dro):6d} {nf:5d} {nb:5d} "
              f"{v:8.1f} {a:8.2f}")

    all_dets = [d for dets in per_frame.values() for d in dets]
    all_dro = [d["area"] for d in all_dets if d["category_id"] == 1]
    pooled_d32 = d32(all_dro)
    pooled_atom = atomised_pct(all_dets)

    print("\n" + "=" * 72)
    print("POOLED OVER THE RUN  (the number to report)")
    print("=" * 72)
    print(f"  droplets            : {len(all_dro)}")
    print(f"  D32                 : {pooled_d32:.1f} um")
    print(f"  atomised fraction   : {pooled_atom:.2f} %")

    lo, hi, sd = bootstrap(per_frame, lambda ds: d32([d["area"] for d in ds
                                                      if d["category_id"] == 1]),
                           args.n_boot)
    alo, ahi, asd = bootstrap(per_frame, atomised_pct, args.n_boot)

    print("\n" + "=" * 72)
    print(f"PRECISION -- bootstrap over frames, {args.n_boot} resamples")
    print("=" * 72)
    print(f"  D32               {pooled_d32:6.1f} um   95% CI [{lo:.1f}, {hi:.1f}]"
          f"   +/- {(hi - lo) / 2:.1f}  ({100 * (hi - lo) / 2 / pooled_d32:.1f}%)")
    print(f"  atomised          {pooled_atom:6.2f} %    95% CI [{alo:.2f}, {ahi:.2f}]"
          f"   +/- {(ahi - alo) / 2:.2f}  ({100 * (ahi - alo) / 2 / pooled_atom:.1f}%)")
    print(f"\n  Two runs measured this way are distinguishable only if they differ")
    print(f"  by more than roughly {1.4 * (hi - lo) / 2:.1f} um D32 "
          f"/ {1.4 * (ahi - alo) / 2:.2f} pp atomised.")
    print(f"  (1.4x a half-width, the rough threshold for two CIs not to overlap.)")

    print("\n" + "=" * 72)
    print("CONVERGENCE -- pooled D32 as frames are added, in file order")
    print("=" * 72)
    keys = sorted(per_frame)
    run_dro = []
    for k, img_id in enumerate(keys, start=1):
        run_dro.extend(d["area"] for d in per_frame[img_id] if d["category_id"] == 1)
        if k % 2 == 0 or k == len(keys):
            print(f"  after {k:3d} frames ({len(run_dro):5d} droplets): "
                  f"D32 {d32(run_dro):6.1f} um")

    fd = np.array([x for x in d32s if np.isfinite(x)])
    print(f"\n  per-frame D32 spread: median {np.median(fd):.1f}  "
          f"p10 {np.percentile(fd, 10):.1f}  p90 {np.percentile(fd, 90):.1f}  "
          f"(pooled {pooled_d32:.1f})")
    print(f"  droplets per frame:  median {int(np.median(counts))}  "
          f"min {min(counts)}  max {max(counts)}")

    # ---- extreme frames, for eyeballing ----
    print("\n" + "=" * 72)
    print("EXTREME FRAMES -- go and look at these")
    print("=" * 72)
    rows = []
    for img_id in sorted(per_frame):
        dets = per_frame[img_id]
        dro = [d["area"] for d in dets if d["category_id"] == 1]
        if dro:
            rows.append((d32(dro), len(dro), atomised_pct(dets),
                         Path(name_by_id[img_id]).stem))
    rows.sort()

    # A frame with a handful of droplets has a meaningless per-frame D32, so
    # report the extremes among frames carrying a reasonable sample as well as
    # the raw extremes -- if they differ, the raw one is a sparse-frame artifact.
    floor = max(50, int(np.median(counts) * 0.5))
    solid = [r for r in rows if r[1] >= floor]

    def show(tag, r):
        print(f"  {tag:34s} {r[3]:>22}  D32 {r[0]:6.1f} um   "
              f"{r[1]:4d} droplets   atomised {r[2]:6.2f}%")

    show("LOWEST D32 (finest)", rows[0])
    show("HIGHEST D32 (coarsest)", rows[-1])
    if solid and (solid[0][3] != rows[0][3] or solid[-1][3] != rows[-1][3]):
        print(f"\n  among frames with >= {floor} droplets only:")
        show("LOWEST D32", solid[0])
        show("HIGHEST D32", solid[-1])
        print("  (differs from the raw extremes above -> those were sparse-frame"
              "\n   artifacts, not genuinely fine/coarse spray)")
    else:
        print(f"\n  (unchanged when restricted to frames with >= {floor} droplets,"
              "\n   so these are real, not sparse-frame artifacts)")
    print(f"\n  ratio highest/lowest: {rows[-1][0] / rows[0][0]:.2f}x  -- this is the"
          f"\n  frame-to-frame swing the pooled number is averaging over.")

    # ---- what a whole run would buy ----
    print("\n" + "=" * 72)
    print("PROJECTED PRECISION AT RUN SCALE  (noise ~ 1/sqrt(n_independent))")
    print("=" * 72)
    n_now = len(per_frame)
    print(f"  measured here at n={n_now} INDEPENDENT frames.")
    print(f"  {'n frames':>10} {'D32 +/-':>12} {'atomised +/-':>16}")
    for n in (50, 100, 250, 500, 1000):
        f = np.sqrt(n_now / n)
        dh, ah = (hi - lo) / 2 * f, (ahi - alo) / 2 * f
        print(f"  {n:>10} {dh:>8.2f} um {100 * dh / pooled_d32:>5.1f}%"
              f"   {ah:>7.2f} pp {100 * ah / pooled_atom:>5.1f}%")
    print("\n  CAUTION: n is INDEPENDENT frames, not raw frames. Decorrelation is")
    print("  ~20 ms, so at 500 fps only every 10th frame counts. 1,000 independent")
    print("  frames = a 10,000-frame capture = the full 20 s post-trigger window.")


if __name__ == "__main__":
    main()
