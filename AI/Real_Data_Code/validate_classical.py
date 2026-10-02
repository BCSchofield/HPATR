#!/usr/bin/env python3
"""
validate_classical.py -- score classical_liquid.py against the hand-labelled
20-frame benchmark (06_validation) BEFORE its atomised fraction is quoted.

classical_liquid.py replaces the atomised fraction's DENOMINATOR (un-atomised
liquid) with a whole-frame classical measurement. The handoff marks it NOT
VALIDATED: every failure mode found pointed the same way, but the magnitude
rests on the seed threshold. This compares, on the same 20 frames:

  GT drawn       union(GT droplets) / union(all GT), as labelled
  GT half-max    the same, but every NON-droplet GT shape trimmed to its own
                 half-max edge, (t_min+1)/2, inside the drawn outline. Hand-drawn
                 filaments/blobs were never refined (handoff rule 5: ~1.6x
                 over-wide), droplets were. This is the edge definition the
                 classical pass uses, so it is the fair comparison.
  model only     union(model droplets) / union(all model masks) -- the old method
  classical      classical_liquid.measure_frame, unchanged

each for measurable-only GT (what the size statistics use) and all GT.
Pooled = sum of pixels over all frames, never an average of per-frame ratios.

Reads only: 06_validation/{instances.json, frame_runs.json, frames/16bit,
v3_predictions.json} and 01_candidates/<run>/background_median.tiff.
Writes nothing unless --out is given.

Usage:
    python validate_classical.py
    python validate_classical.py --pred <...>/v3_predictions.json --out <dir>
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from pycocotools import mask as mask_util

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))

import classical_liquid as cl  # noqa: E402
from measure_run import det_crop, DROPLET  # noqa: E402
from config_loader import find_lacie_drive  # noqa: E402


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def union_masks(anns, shape, halfmax_T=None):
    """(droplet_union, all_union). With halfmax_T, non-droplet shapes are
    trimmed to their own half-max inside the drawn outline."""
    drop = np.zeros(shape, bool)
    allm = np.zeros(shape, bool)
    for a in anns:
        m = mask_util.decode(a["segmentation"]).astype(bool)
        if not m.any():
            continue
        if a["category_id"] == DROPLET:
            drop |= m
        elif halfmax_T is not None:
            tmin = float(halfmax_T[m].min())
            m = m & (halfmax_T < (tmin + 1.0) / 2.0)
        allm |= m
    return drop, allm | drop


def model_union(dets, shape):
    drop = np.zeros(shape, bool)
    allm = np.zeros(shape, bool)
    for d in dets:
        mb, bx, by, bh, bw = det_crop(d)
        if not mb.any():
            continue
        allm[by:by + bh, bx:bx + bw] |= mb
        if d["category_id"] == DROPLET:
            drop[by:by + bh, bx:bx + bw] |= mb
    return drop, allm


def pct(num, den):
    return 100.0 * num / den if den else float("nan")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None, help="Real_Data root")
    ap.add_argument("--pred", type=Path, default=None,
                    help="default: 06_validation/v3_predictions.json")
    ap.add_argument("--score-thresh", type=float, default=0.30)
    ap.add_argument("--out", type=Path, default=None, help="write per-frame CSV + summary here")
    args = ap.parse_args()

    root = args.root or real_data_root()
    val = root / "06_validation"
    pred_path = args.pred or (val / "v3_predictions.json")
    gt = json.loads((val / "instances.json").read_text(encoding="utf-8"))
    runs = json.loads((val / "frame_runs.json").read_text(encoding="utf-8"))["frames"]
    preds = json.loads(pred_path.read_text(encoding="utf-8"))

    gt_ids = {im["id"] for im in gt["images"]}
    stray = {d["image_id"] for d in preds} - gt_ids
    if stray:
        sys.exit(f"{len(stray)} prediction image_ids not in the ground truth -- stale predictions")

    # classical_liquid.measure_frame reads these off its argparse namespace
    cl_args = SimpleNamespace(seed=cl.SEED_THR, ceiling=cl.CEILING_THR, min_area=cl.MIN_AREA,
                              droplet_cover=cl.DROPLET_COVER,
                              droplet_max_extent=cl.DROPLET_MAX_EXTENT,
                              focus_max=0.70, classical_only=False)

    bgs = {}
    gt_by = {}
    for a in gt["annotations"]:
        gt_by.setdefault(a["image_id"], []).append(a)
    det_by = {}
    for d in preds:
        if d["score"] >= args.score_thresh:
            det_by.setdefault(d["image_id"], []).append(d)

    keys = ["gt_drawn_meas", "gt_drawn_all", "gt_hm_meas", "gt_hm_all", "model", "classical"]
    rows = []
    t0 = time.time()
    for im in sorted(gt["images"], key=lambda i: i["id"]):
        stem = im["file_name"].rsplit(".", 1)[0]
        run = runs[stem]
        if run not in bgs:
            b = cv2.imread(str(root / "01_candidates" / run / "background_median.tiff"),
                           cv2.IMREAD_UNCHANGED)
            if b is None:
                sys.exit(f"no background for run {run}")
            bgs[run] = b.astype(np.float32)
        raw16 = cv2.imread(str(val / "frames" / "16bit" / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
        if raw16 is None:
            sys.exit(f"no 16-bit frame for {stem}")
        T = raw16.astype(np.float32) / np.maximum(bgs[run], 1.0)
        shape = T.shape
        anns = gt_by.get(im["id"], [])
        meas = [a for a in anns if a.get("measurable", True)]
        dets = det_by.get(im["id"], [])

        r = {"frame": stem, "run": run}
        for key, sel, hm in (("gt_drawn_meas", meas, None), ("gt_drawn_all", anns, None),
                             ("gt_hm_meas", meas, T), ("gt_hm_all", anns, T)):
            dm, am = union_masks(sel, shape, hm)
            r[key + "_drop"], r[key + "_tot"] = int(dm.sum()), int(am.sum())
        dm, am = model_union(dets, shape)
        r["model_drop"], r["model_tot"] = int(dm.sum()), int(am.sum())
        crow, *_ = cl.measure_frame(T, dets, cl_args)
        r["classical_drop"], r["classical_tot"] = crow["droplet_px"], crow["total_liquid_px"]
        for k in keys:
            r[k + "_pct"] = round(pct(r[k + "_drop"], r[k + "_tot"]), 2)
            r[k + "_unatom"] = r[k + "_tot"] - r[k + "_drop"]
        rows.append(r)
        print(f"  {stem:18s} {run[:6]}  GT(hm,meas) {r['gt_hm_meas_pct']:6.2f}%  "
              f"model {r['model_pct']:6.2f}%  classical {r['classical_pct']:6.2f}%")
    elapsed = time.time() - t0

    def pooled(sel, k):
        d = sum(r[k + "_drop"] for r in sel)
        t = sum(r[k + "_tot"] for r in sel)
        return pct(d, t), t - d

    labels = {"gt_drawn_meas": "GT drawn, measurable", "gt_drawn_all": "GT drawn, all",
              "gt_hm_meas": "GT half-max, measurable", "gt_hm_all": "GT half-max, all",
              "model": "model only (old)", "classical": "classical (new)"}
    summary = {"frames": len(rows), "score_thresh": args.score_thresh,
               "predictions": str(pred_path), "elapsed_s": round(elapsed, 1), "groups": {}}
    groups = [("ALL 20 FRAMES", rows)] + [
        (f"run {r}", [x for x in rows if x["run"] == r]) for r in sorted({x["run"] for x in rows})]
    for name, sel in groups:
        print(f"\n=== {name} ({len(sel)} frames) -- pooled atomised fraction and un-atomised px")
        g = {}
        for k in keys:
            p, u = pooled(sel, k)
            g[k] = {"atomised_pct": round(p, 3), "unatomised_px": int(u)}
            print(f"  {labels[k]:26s} {p:7.3f}%   un-atomised {u:>10,} px")
        for ref in ("gt_hm_meas", "gt_hm_all"):
            for k in ("model", "classical"):
                g[f"{k}_vs_{ref}_rel_pct"] = round(100 * (g[k]["atomised_pct"] /
                                                          g[ref]["atomised_pct"] - 1), 1)
                g[f"{k}_unatom_ratio_vs_{ref}"] = round(
                    g[k]["unatomised_px"] / max(g[ref]["unatomised_px"], 1), 3)
        print(f"  relative to GT half-max (meas / all): "
              f"model {g['model_vs_gt_hm_meas_rel_pct']:+.1f}% / {g['model_vs_gt_hm_all_rel_pct']:+.1f}%,  "
              f"classical {g['classical_vs_gt_hm_meas_rel_pct']:+.1f}% / "
              f"{g['classical_vs_gt_hm_all_rel_pct']:+.1f}%")
        print(f"  un-atomised area / GT half-max (meas / all): "
              f"model {g['model_unatom_ratio_vs_gt_hm_meas']:.2f} / {g['model_unatom_ratio_vs_gt_hm_all']:.2f},  "
              f"classical {g['classical_unatom_ratio_vs_gt_hm_meas']:.2f} / "
              f"{g['classical_unatom_ratio_vs_gt_hm_all']:.2f}")
        summary["groups"][name] = g

    # per-frame agreement: does classical track the truth frame to frame?
    for k in ("model", "classical"):
        a = np.array([r[k + "_pct"] for r in rows])
        b = np.array([r["gt_hm_meas_pct"] for r in rows])
        ok = np.isfinite(a) & np.isfinite(b)
        rho = float(np.corrcoef(np.argsort(np.argsort(a[ok])),
                                np.argsort(np.argsort(b[ok])))[0, 1])
        summary[f"{k}_spearman_vs_gt_hm_meas"] = round(rho, 3)
        print(f"\nper-frame rank correlation with GT half-max (measurable): {k} {rho:.3f}")
    print(f"\n{len(rows)} frames in {elapsed:.0f} s")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        with open(args.out / "validate_classical_per_frame.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        (args.out / "validate_classical_summary.json").write_text(json.dumps(summary, indent=2))
        print(f"written to {args.out}")


if __name__ == "__main__":
    main()
