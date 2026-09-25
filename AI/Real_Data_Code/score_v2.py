#!/usr/bin/env python3
"""
score_v2.py -- Step 8: score tiled predictions against the hand-labelled benchmark.

SCORE ONCE. The checkpoint was selected on composite validation; picking a
different checkpoint or threshold because it scores better here would turn the
benchmark into a tuning set, and there is no third set held in reserve.

FILTERING RULES (from the Step 6 ground rules -- both sides must use the same
convention or the comparison is meaningless):

- Detection is scored against ALL annotations. Every one is a real object.
- Size statistics use `measurable == true` only. Out-of-focus and
  border-touching objects are real but their sizes are not trustworthy.
- Unmeasurable objects are marked IGNORE for the measurable-only evaluation,
  never deleted. Deleting them would turn a correct detection of a real
  out-of-focus droplet into a false positive.
- Size bands are PHYSICAL (um), not COCO small/medium/large -- COCO "small" is
  under 32^2 px, which is nearly every droplet in this data.

Usage:
    python score_v2.py --pred 06_validation/v2_predictions.json
"""

import argparse
import copy
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
    from pycocotools import mask as mask_util
except ImportError:
    sys.exit("pycocotools is required:  pip install pycocotools")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402

UM_PER_PX = 10.0
CLASS_NAMES = {1: "droplet", 2: "filament", 3: "blob"}
SIZE_BANDS_UM = [(0, 50), (50, 100), (100, 200), (200, 500), (500, 1e9)]


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def equiv_um(area_px):
    return 2.0 * np.sqrt(np.asarray(area_px, dtype=float) / np.pi) * UM_PER_PX


def run_eval(coco_gt, preds, iou_type, quiet=True):
    if not preds:
        return None
    coco_dt = coco_gt.loadRes(copy.deepcopy(preds))
    e = COCOeval(coco_gt, coco_dt, iou_type)
    e.evaluate(); e.accumulate()
    if quiet:
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            e.summarize()
    else:
        e.summarize()
    return e


def ap_per_class(coco_gt, preds, iou_type):
    out = {}
    for cid, name in CLASS_NAMES.items():
        e = run_eval(coco_gt, preds, iou_type)
        if e is None:
            continue
        e.params.catIds = [cid]
        e.evaluate(); e.accumulate()
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            e.summarize()
        out[name] = e.stats[0] * 100
    return out


def greedy_match(gt_anns, preds, score_thresh, iou_thresh=0.5):
    """
    Per-class greedy IoU matching at one operating point, so precision/recall
    mean what a person expects rather than an integral over thresholds.
    Returns (tp, fp, fn) counts and the matched GT ids.
    """
    tp = fp = 0
    matched_gt = set()
    by_img_cls = {}
    for a in gt_anns:
        by_img_cls.setdefault((a["image_id"], a["category_id"]), []).append(a)

    dets = sorted([d for d in preds if d["score"] >= score_thresh],
                  key=lambda d: -d["score"])
    for d in dets:
        cands = by_img_cls.get((d["image_id"], d["category_id"]), [])
        best, best_iou = None, 0.0
        for g in cands:
            if g["id"] in matched_gt:
                continue
            i = mask_util.iou([d["segmentation"]], [g["segmentation"]], [0])[0][0]
            if i > best_iou:
                best, best_iou = g, i
        if best is not None and best_iou >= iou_thresh:
            matched_gt.add(best["id"]); tp += 1
        else:
            fp += 1
    fn = len(gt_anns) - len(matched_gt)
    return tp, fp, fn, matched_gt


def main():
    ap = argparse.ArgumentParser(description="Score v2 against the hand-labelled benchmark")
    ap.add_argument("--pred", type=Path, default=None)
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    val = root / "06_validation"
    gt_path = val / "instances.json"
    pred_path = args.pred or (val / "v2_predictions.json")

    gt_raw = json.loads(gt_path.read_text(encoding="utf-8"))
    preds = json.loads(pred_path.read_text(encoding="utf-8"))
    print(f"ground truth: {len(gt_raw['annotations'])} annotations, "
          f"{len(gt_raw['images'])} frames")
    print(f"predictions:  {len(preds)} detections\n")

    # Predictions carry image_ids assigned when they were generated. Those ids
    # come from the GT file's image order, so ADDING A FRAME to the benchmark
    # renumbers everything and silently invalidates an older predictions file.
    # It happened on 2026-09-25 (15 -> 20 frames) and surfaced as AP 0.0, which
    # was luck: had the count stayed the same and only the order changed, the
    # score would have been quietly wrong instead. Fail loudly.
    gt_ids = {im["id"] for im in gt_raw["images"]}
    pred_ids = {d["image_id"] for d in preds}
    stray = pred_ids - gt_ids
    if stray:
        sys.exit(f"{len(stray)} prediction image_id(s) are not in the ground truth "
                 f"({sorted(stray)[:6]}...). The predictions were generated against "
                 f"a different version of the benchmark -- regenerate them.")
    unmatched = gt_ids - pred_ids
    if len(unmatched) > len(gt_ids) // 2:
        print(f"  WARNING: {len(unmatched)} of {len(gt_ids)} frames have no "
              f"detections at all. Stale predictions?\n")

    coco_gt = COCO(gt_path) if False else None  # avoid COCO's stdout noise
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        coco_gt = COCO(str(gt_path))

    # ---------- 1. detection, ALL annotations ----------
    print("=" * 72)
    print(f"1. DETECTION -- all {len(gt_raw['annotations'])} annotations "
          f"(every one is a real object)")
    print("=" * 72)
    for iou_type in ("bbox", "segm"):
        e = run_eval(coco_gt, preds, iou_type)
        print(f"  {iou_type:5s}  AP {e.stats[0]*100:5.1f}   AP50 {e.stats[1]*100:5.1f}   "
              f"AP75 {e.stats[2]*100:5.1f}   AR100 {e.stats[8]*100:5.1f}")
    print("\n  per class (bbox AP / segm AP):")
    ab, as_ = ap_per_class(coco_gt, preds, "bbox"), ap_per_class(coco_gt, preds, "segm")
    for name in ("droplet", "filament", "blob"):
        print(f"    {name:9s} {ab.get(name, float('nan')):5.1f} / {as_.get(name, float('nan')):5.1f}")

    # ---------- 2. measurable only ----------
    print()
    print("=" * 72)
    print("2. MEASURABLE ONLY -- unmeasurable GT set to IGNORE, not deleted")
    print("=" * 72)
    # pycocotools DISCARDS a plain `ignore` flag: COCOeval._prepare sets
    #     gt['ignore'] = gt['ignore'] if 'ignore' in gt else 0
    #     gt['ignore'] = 'iscrowd' in gt and gt['iscrowd']      <-- overwrites it
    # so the second line wins and `ignore` never takes effect. The earlier
    # version of this section set `ignore` and therefore printed numbers
    # IDENTICAL to section 1, which is how the bug was spotted.
    #
    # `iscrowd=1` is the flag that actually reaches the matcher, and its
    # semantics are what we want here: a detection landing on a crowd region is
    # neither a true positive nor a false positive. Unmeasurable objects are
    # real, so a model that finds one must not be punished -- it simply must not
    # be scored on that object's size.
    gt_m = copy.deepcopy(gt_raw)
    n_ign = 0
    for a in gt_m["annotations"]:
        if not a.get("measurable", True):
            a["iscrowd"] = 1
            n_ign += 1
    tmp = val / "_gt_measurable_tmp.json"
    tmp.write_text(json.dumps(gt_m), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        coco_m = COCO(str(tmp))
    print(f"  {n_ign} of {len(gt_m['annotations'])} annotations ignored "
          f"(out of focus or border-touching)")
    for iou_type in ("bbox", "segm"):
        e = run_eval(coco_m, preds, iou_type)
        print(f"  {iou_type:5s}  AP {e.stats[0]*100:5.1f}   AP50 {e.stats[1]*100:5.1f}   "
              f"AR100 {e.stats[8]*100:5.1f}")
    tmp.unlink()

    # ---------- 3. operating point ----------
    print()
    print("=" * 72)
    print("3. OPERATING POINT -- greedy mask-IoU>=0.5 matching, measurable GT only")
    print("=" * 72)
    gt_meas = [a for a in gt_raw["annotations"] if a.get("measurable", True)]
    print(f"{'score':>6} {'TP':>6} {'FP':>6} {'FN':>6} {'precision':>10} {'recall':>8} {'F1':>7}")
    best = None
    for t in (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        tp, fp, fn, _ = greedy_match(gt_meas, preds, t)
        prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)
        print(f"{t:6.2f} {tp:6d} {fp:6d} {fn:6d} {prec:10.3f} {rec:8.3f} {f1:7.3f}")
        if best is None or f1 > best[1]:
            best = (t, f1)
    print(f"\n  best F1 at score >= {best[0]:.2f} (F1 {best[1]:.3f}) "
          f"-- candidate MEASUREMENT operating point")

    # ---------- 4. recall by physical size ----------
    print()
    print("=" * 72)
    print("4. RECALL BY PHYSICAL SIZE -- measurable GT, at the best-F1 threshold")
    print("=" * 72)
    _, _, _, matched = greedy_match(gt_meas, preds, best[0])
    print(f"{'band (um)':>14} {'class':9s} {'n':>5} {'found':>6} {'recall':>8}")
    for lo, hi in SIZE_BANDS_UM:
        for cid, name in CLASS_NAMES.items():
            sel = [a for a in gt_meas if a["category_id"] == cid
                   and lo <= equiv_um(a["area"]) < hi]
            if not sel:
                continue
            found = sum(1 for a in sel if a["id"] in matched)
            label = f"{lo:.0f}-{hi:.0f}" if hi < 1e8 else f">{lo:.0f}"
            print(f"{label:>14} {name:9s} {len(sel):5d} {found:6d} {found/len(sel):8.3f}")

    # ---------- 5. the numbers that matter ----------
    print()
    print("=" * 72)
    print("5. MEASUREMENT -- D32 and atomised fraction, GT vs predicted")
    print("=" * 72)
    t = best[0]
    dets = [d for d in preds if d["score"] >= t and not d.get("truncated", False)]

    def d32(areas):
        if len(areas) == 0:
            return float("nan")

        d = equiv_um(areas)
        return float((d ** 3).sum() / (d ** 2).sum())

    def class_area_union(anns):
        """
        Total area per class as the UNION of masks, not the sum of instances.

        The model emits one long filament as several detections covering
        different stretches of it -- a 28x28 mask head cannot represent a long
        thread, so the RPN proposes sub-segments. Those are NOT duplicates and
        no NMS rule removes them, but summing their areas double-counts the
        overlap. Measured on v2: filament +20.5%, blob +10.6%, droplet 0%.
        Hand labels overlap by ~0%, so this is a prediction-side error only, and
        it biases the atomised fraction DOWN by inflating the denominator.
        Union counts each pixel once; it costs only instance counting, which no
        Taguchi metric uses.
        """
        by = defaultdict(lambda: defaultdict(list))
        for a in anns:
            by[a["image_id"]][a["category_id"]].append(a["segmentation"])
        tot = defaultdict(float)
        for img, cls in by.items():
            for c, rles in cls.items():
                tot[c] += float(mask_util.area(mask_util.merge(rles)))
        return tot

    for label, anns in (("ground truth", gt_meas), ("predicted", dets)):
        dro = [a["area"] for a in anns if a["category_id"] == 1]
        u = class_area_union(anns)
        tot_u = sum(u.values())
        frac_u = u[1] / tot_u * 100 if tot_u else float("nan")
        s_all = [sum(a["area"] for a in anns if a["category_id"] == c) for c in (1, 2, 3)]
        frac_s = s_all[0] / sum(s_all) * 100 if sum(s_all) else float("nan")
        print(f"  {label:13s} droplets {len(dro):5d}  D32 {d32(dro):6.1f} um   "
              f"atomised fraction: UNION {frac_u:5.2f}%   (sum-of-instances {frac_s:5.2f}%)")
    print("\n  NOTE: predicted filament AREA is not trustworthy (28x28 mask head,"
          "\n  ~20 pt box-vs-mask gap). The atomised fraction above inherits that.")


if __name__ == "__main__":
    main()
