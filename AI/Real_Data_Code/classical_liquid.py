#!/usr/bin/env python3
"""
classical_liquid.py -- measure un-atomised liquid classically, whole-frame.

WHY THIS EXISTS
---------------
The model measures droplets well and un-atomised liquid badly, for two separate
structural reasons:

  FILAMENTS   The mask head is a fixed 28x28 grid per detection. A 100:1
              aspect-ratio thread cannot be represented in it. On Trial_1, 566
              of 4,364 filament detections are >150 px long AND fill <25% of
              their own bounding box; the worst is 626 px at 0.33% fill,
              detected at score 1.00 -- certain the object is there, and still
              returning an almost-empty mask.

  BLOBS       Shape is fine (50-78% bbox fill) but they get cut at tile seams:
              96 of 483 blob detections have an edge within 5 px of a tile
              boundary. One blob in frame_0074_n739 is reported as two
              fragments split exactly at y=800.

Measured consequence: classical area is 1.09x the model's on a blob-heavy frame
and 1.53x on a thread-heavy one. The model was under-reading un-atomised liquid,
so the atomised fraction was flattered.

A whole-frame classical pass has neither defect -- no 28x28 bottleneck, no tiles
to be cut by.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
No filament/blob distinction. Real regions are routinely BOTH -- the largest
component in frame_0074_n739 is 560,985 px with a 511 px maximum width and thin
threads trailing off it, one connected piece of liquid. Any single label for it
would be wrong. The atomised fraction only needs droplet vs not-droplet, so the
distinction is not computed. (The model's filament/blob classes still earn their
keep at training time; they just are not a measurement.)

No skeletons, no lengths. A classical mask's pixel count IS its area, exactly.
The skeleton was only ever the route to length, which is not wanted.

ACCOUNTING
----------
    numerator   = union(model droplet masks)
    denominator = union(classical liquid, model droplets,
                        OUT-OF-FOCUS model filaments/blobs)
    un-atomised = denominator - numerator

The denominator is ONE union rather than three per-class unions summed, which
structurally removes the cross-class double-counting bug: a droplet overlapping
a filament used to be counted twice.

Only OUT-OF-FOCUS model filaments/blobs are unioned in. Out-of-focus is DEFINED
as t_min > 0.70, so the 0.70 seed cannot find them by construction, and without
help the ratio would count out-of-focus droplets while dropping out-of-focus
threads.

Unioning ALL model masks was tried and was wrong: a union can only ADD, so the
model's over-wide filament masks became a floor the classical measurement could
never get below -- on frame_0122_n1219, 44% of the reported un-atomised area was
model mask rather than classical measurement. Restricting it to out-of-focus
detections keeps only what the classical pass genuinely cannot reach.

Usage:
    python classical_liquid.py --root <run>            # all frames
    python classical_liquid.py --root <run> --limit 20
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pycocotools import mask as mask_util  # noqa: E402
from measure_run import (  # noqa: E402
    det_crop, px_to_mm2, equiv_um, d32, annotate, ring_contours,
    measure_droplet, sizer_version, SPLIT_UM,
    DROPLET, UM_PER_PX, DROPLET_BIN_UM,
    GREEN, MAGENTA, ORANGE,
    PLOT_GREEN, PLOT_MAGENTA, PLOT_ORANGE,
)

SEED_THR = 0.70      # strict: definitely liquid. Same value as the focus gate.
CEILING_THR = 0.95   # bounds region growing only -- never an edge itself
MIN_AREA = 20        # px; below this nothing can carry a measurement
DROPLET_COVER = 0.50
DROPLET_MAX_EXTENT = 100


def hysteresis(T, seed_thr=SEED_THR, ceiling=CEILING_THR, min_area=MIN_AREA):
    """Liquid mask: seed on dark cores, grow each seed to ITS OWN half-max edge.

    Two thresholds are needed because one cannot work. T<0.95 (what
    extract_candidates.py uses to generate CANDIDATES, before curation) gives
    36,695 components per frame, 89% of the area sitting at transmission
    0.90-0.95 -- sensor and illumination noise. T<0.70 alone loses the faint
    edges of real objects.

    The grow threshold is PER COMPONENT, at that component's own half-maximum
    (t_min + 1) / 2, not a fixed value. This matters and a fixed grow is wrong:

      * It is the edge definition the rest of the project already uses. Hand
        labels, extract_candidates.py and therefore the model's own training
        targets all put an object's edge at its own half-max. Measuring droplets
        at half-max (via the model) and un-atomised liquid at some other
        threshold would mix two edge definitions inside one ratio.

      * A fixed grow over-segments dark objects. A thread with t_min 0.06 has its
        true edge at 0.53; growing it to 0.90 inflated it by ~1.5x, visible as an
        orange halo wider than the thread itself.

      * It was double-counting droplets. Growing a droplet past its half-max left
        a rim outside the model's mask, which then scored as un-atomised liquid.
        On frame_0099_n989 that rim was 85.5% of all "un-atomised" area, dragging
        a genuinely ~97% atomised frame down to 74%. At half-max it is 5.9%.

    Growing from the seed rather than refining an existing mask also keeps
    regions connected: measured on Trial_1, post-hoc refinement of a fixed-grow
    mask SPLIT components (76 -> 81), while growing to the same edge from the
    seed merges them (76 -> 51) for the same final area.

    `ceiling` only bounds the region growing; it is never an edge itself.
    """
    grow = (T < ceiling).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(grow, 8)
    seeded = {i for i in np.unique(lab[T < seed_thr]) if i != 0}
    if not seeded:
        return np.zeros(T.shape, bool), 0

    # Work inside each component's BOUNDING BOX, which
    # connectedComponentsWithStats already gives us. `lab == i` over the whole
    # frame builds a 2.4 M-element boolean per component, and there are hundreds
    # of components per frame -- that one line was 56% of the classical pass
    # (0.30 s/frame). A component lies entirely within its own bbox by
    # definition, so this is the same computation on a smaller array and the
    # result is bit-identical.
    out = np.zeros(T.shape, bool)
    for i in seeded:
        x0 = stats[i, cv2.CC_STAT_LEFT]
        y0 = stats[i, cv2.CC_STAT_TOP]
        sl = (slice(y0, y0 + stats[i, cv2.CC_STAT_HEIGHT]),
              slice(x0, x0 + stats[i, cv2.CC_STAT_WIDTH]))
        comp = lab[sl] == i
        Tc = T[sl]
        out[sl] |= comp & (Tc < (Tc[comp].min() + 1.0) / 2.0)

    n2, lab2, stats2, _ = cv2.connectedComponentsWithStats(out.astype(np.uint8), 8)
    big = [j for j in range(1, n2) if stats2[j, cv2.CC_STAT_AREA] >= min_area]
    return np.isin(lab2, big), len(big)


def drop_droplet_components(liquid, droplet_mask,
                            cover_thr=DROPLET_COVER, max_extent=DROPLET_MAX_EXTENT):
    """Remove whole components that are just an already-detected droplet.

    Per COMPONENT, never per pixel. Subtracting droplet PIXELS was measured to
    take one frame from 199 components to 441 -- a droplet sitting on a filament
    punches a hole and splits it in two. Dropping a whole component cannot
    fragment anything, by construction.

    `max_extent` is a guard, not a tuning knob: measured on Trial_1 the longest
    component this ever drops is 31 px, so it never binds. It is there because
    the model sometimes emits a fragmented filament as a chain of droplets, and
    losing a filament is the one failure this pass must not have.

    Only affects the per-component size distribution. The atomised fraction uses
    the FULL mask, because an isolated droplet is still liquid.
    """
    n, lab, stats, _ = cv2.connectedComponentsWithStats(liquid.astype(np.uint8), 8)
    kept = np.zeros_like(liquid)
    dropped = np.zeros_like(liquid)
    n_kept = n_drop = 0
    # Per bounding box, for the same reason as hysteresis(): `lab == i` and the
    # coverage test over the whole frame cost 84 ms/frame across hundreds of
    # components. A component lies entirely inside its own bbox, so this is the
    # identical computation on a smaller array.
    for i in range(1, n):
        x0 = stats[i, cv2.CC_STAT_LEFT]
        y0 = stats[i, cv2.CC_STAT_TOP]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        sl = (slice(y0, y0 + h), slice(x0, x0 + w))
        comp = lab[sl] == i
        area = stats[i, cv2.CC_STAT_AREA]
        extent = max(w, h)
        if (area and (comp & droplet_mask[sl]).sum() / area >= cover_thr
                and extent <= max_extent):
            dropped[sl] |= comp
            n_drop += 1
        else:
            kept[sl] |= comp
            n_kept += 1
    return kept, dropped, n_kept, n_drop


def model_masks(dets, T, focus_max, args_ref=None):
    """(droplet_union, out_of_focus_unatomised_union).

    The second return is deliberately ONLY out-of-focus non-droplet detections.

    An earlier version unioned ALL model masks in, to close a focus asymmetry:
    the 0.70 seed IS the focus gate, so the classical pass cannot see
    out-of-focus liquid at all, and without help it would count out-of-focus
    droplets (which arrive via the model) while silently dropping out-of-focus
    threads. That asymmetry is worth ~1.6% of un-atomised area.

    But unioning everything was a mistake, and the "union is monotonic so it can
    only add" argument is exactly why: it can only ADD, so it can never tighten.
    The model's over-wide filament masks became a floor the classical
    measurement could not get below. Measured on frame_0122_n1219: classical
    found 27,322 px of liquid, the model's masks covered 48,752, and 44% of the
    reported un-atomised area was model mask rather than classical measurement.
    It was really max(classical, model) wearing a classical label.

    Restricting the union to OUT-OF-FOCUS detections keeps the part the
    classical pass genuinely cannot reach (t_min > focus_max, unseedable by
    construction) and nowhere else -- so where classical has an answer, it wins.
    """
    drop = np.zeros(T.shape, bool)
    oof = np.zeros(T.shape, bool)
    n_half = n_model = 0
    for d in dets:
        mb, bx, by, bh, bw = det_crop(d)
        if not mb.any():
            continue
        if d["category_id"] == DROPLET:
            # SAME EDGE ON BOTH SIDES OF THE RATIO. The denominator is measured
            # classically at each component's half-max; putting the model's raw
            # mask in the numerator gave droplets a more generous edge than
            # filaments and blobs, which inflated the atomised fraction. Half-max
            # droplet areas run ~0.86x the model mask, so the asymmetry was
            # worth several percent of the headline number.
            #
            # Where no half-max measurement exists -- out of focus, below the
            # size split, or no component found -- there is nothing to use but
            # the model's mask, so that still goes in.
            md = measure_droplet(T, d, focus_max,
                                 split_um=getattr(args_ref, "split_um", SPLIT_UM),
                                 core_estimator=getattr(args_ref, "core_estimator", "robust"),
                                 sizer=not getattr(args_ref, "no_sizer", False),
                                 crop=(mb, bx, by, bh, bw), want_mask=True,
                                 sharpness_rule=getattr(args_ref, "sharpness_rule", False))
            hm = md.get("mask") if md else None
            if hm is not None:
                hx, hy = md["mask_xy"]
                drop[hy:hy + hm.shape[0], hx:hx + hm.shape[1]] |= hm
                n_half += 1
            else:
                drop[by:by + bh, bx:bx + bw] |= mb
                n_model += 1
        elif T[by:by + bh, bx:bx + bw][mb].min() > focus_max:
            oof[by:by + bh, bx:bx + bw] |= mb
    model_masks.last_counts = (n_half, n_model)
    return drop, oof


def measure_frame(T, dets, args):
    """One frame -> (row, component_areas_px, focus_d, oof_d, unatom_mask).

    `liquid` is the full classical mask and is what the ratio uses. `kept` has
    already-detected droplets removed and is only for the size distribution --
    an isolated droplet is still liquid and must stay in the denominator.
    """
    liquid, _ = hysteresis(T, args.seed, args.ceiling, args.min_area)
    dmask, oof_unatom = model_masks(dets, T, args.focus_max, args)

    # True union: nothing counted twice, and droplets are a subset of total by
    # construction, so un-atomised can never go negative.
    total = liquid | dmask if args.classical_only else liquid | dmask | oof_unatom
    droplet_px = int(dmask.sum())
    total_px = int(total.sum())
    unatom_px = total_px - droplet_px

    kept, _, n_kept, n_drop = drop_droplet_components(
        liquid, dmask, args.droplet_cover, args.droplet_max_extent)

    n, lab, stats, _ = cv2.connectedComponentsWithStats(kept.astype(np.uint8), 8)
    comp_areas = [int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n)]

    # Droplet focus AND sizing come from measure_run.measure_droplet -- the one
    # shared implementation. This file used to recompute the focus test itself,
    # twice, and the copies drifted: 85.58 um here against 85.57 um there for the
    # same run. Only the un-atomised denominator is re-derived classically.
    focus_a, oof_a = [], []
    for d in dets:
        if d["category_id"] != DROPLET:
            continue
        # Tile-truncated detections are excluded from SIZING only, matching
        # measure_run.py:582. A mask cut by a tile seam has a clipped area and
        # therefore a wrong diameter. They stay in the atomised NUMERATOR
        # (model_masks above), because a union reassembles the two halves of a
        # split object and dropping them would lose real liquid area.
        if d.get("truncated", False):
            continue
        md = measure_droplet(T, d, args.focus_max,
                             split_um=getattr(args, "split_um", SPLIT_UM),
                             core_estimator=getattr(args, "core_estimator", "robust"),
                             sizer=not getattr(args, "no_sizer", False),
                             sharpness_rule=getattr(args, "sharpness_rule", False))
        if md is None:
            continue
        (focus_a if md["in_focus"] else oof_a).append(md["area_px"])

    row = {
        "total_liquid_px": total_px,
        "droplet_px": droplet_px,
        "unatomised_px": unatom_px,
        "atomised_pct": round(100.0 * droplet_px / total_px, 3) if total_px else float("nan"),
        "d32_in_focus_um": round(d32(focus_a), 2) if focus_a else float("nan"),
        "droplets_in_focus": len(focus_a),
        "droplets_out_of_focus": len(oof_a),
        "n_components": n_kept,
        "n_droplet_components_dropped": n_drop,
    }
    return row, comp_areas, focus_a, oof_a, (total & ~dmask)


def draw_frame(view8, dets, T, unatom, row, args):
    """Un-atomised liquid FILLED, droplets outlined on top, one image.

    The fill is the classically-measured un-atomised mask -- literally the
    pixels going into the denominator -- so the picture and the number cannot
    disagree. Droplets keep the green/magenta focus convention from
    measure_run so these read the same way as the existing run images.
    """
    canvas = cv2.cvtColor(view8, cv2.COLOR_GRAY2BGR) if view8.ndim == 2 else view8.copy()
    alpha = 0.45
    canvas[unatom] = (np.asarray(ORANGE, np.float32) * alpha
                      + canvas[unatom].astype(np.float32) * (1 - alpha)).astype(np.uint8)
    for d in dets:
        if d["category_id"] != DROPLET:
            continue
        mb, bx, by, bh, bw = det_crop(d)
        if not mb.any():
            continue
        # same shared decision as the numbers, so the picture cannot contradict
        # the table: a droplet re-sized or re-classified is drawn accordingly
        md = measure_droplet(T, d, args.focus_max,
                             split_um=getattr(args, "split_um", SPLIT_UM),
                             core_estimator=getattr(args, "core_estimator", "robust"),
                             sizer=not getattr(args, "no_sizer", False),
                             crop=(mb, bx, by, bh, bw),
                             sharpness_rule=getattr(args, "sharpness_rule", False))
        sharp = bool(md["in_focus"]) if md else False
        full = np.zeros(canvas.shape[:2], np.uint8)
        full[by:by + bh, bx:bx + bw] = mb
        # Ring, not outline: a 9 px droplet's own contour is invisible at full
        # frame scale. Same convention as measure_run so these images read the
        # same way as the ones already in the run folder.
        if args.droplet_ring > 0:
            cnts = ring_contours(full, d["bbox"], args.droplet_ring, canvas.shape[:2])
        else:
            cnts, _ = cv2.findContours(full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, cnts, -1, GREEN if sharp else MAGENTA, 2)
    annotate(canvas, row["d32_in_focus_um"], row["atomised_pct"])
    return canvas


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path,
                    default=Path("/Volumes/LaCie/Experiments/2026/09/28/Trial_1"))
    ap.add_argument("--pred", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="default: <root>/shadowgraph/analysis/skeletonisation_testing")
    ap.add_argument("--seed", type=float, default=SEED_THR)
    ap.add_argument("--ceiling", type=float, default=CEILING_THR,
                    help="bounds region growing; the EDGE is each component's own "
                         "half-max, not this value")
    ap.add_argument("--min-area", type=int, default=MIN_AREA)
    ap.add_argument("--droplet-cover", type=float, default=DROPLET_COVER)
    ap.add_argument("--droplet-max-extent", type=int, default=DROPLET_MAX_EXTENT)
    ap.add_argument("--score-thresh", type=float, default=0.30)
    ap.add_argument("--classical-only", action="store_true",
                    help="leave out-of-focus filaments/blobs unmeasured too. For "
                         "comparison; biases the fraction up by ~1.6%%.")
    ap.add_argument("--sharpness-rule", action="store_true",
                    help="sizer 2.2.0, as measure_run.py --sharpness-rule: moves D32 "
                         "membership and drawing colour only, never the atomised fraction")
    ap.add_argument("--focus-max", type=float, default=0.70,
                    help="droplet focus gate, as measure_run (default 0.70)")
    ap.add_argument("--droplet-ring", type=int, default=10,
                    help="draw droplets as a ring of this radius, as measure_run")
    ap.add_argument("--images-mode", choices=["extremes", "all"], default=None,
                    help="'extremes' draws only the 4 frames at the atomised "
                         "min/max (chosen from THIS pass's atomised %%, which is "
                         "the real one -- measure_run picks its extremes from the "
                         "model-only figure); 'all' draws every frame. Implies "
                         "--images.")
    ap.add_argument("--images", action="store_true",
                    help="write a marked-up full-res PNG per frame")
    ap.add_argument("--limit", type=int, default=None, help="first N frames only")
    ap.add_argument("--frames", nargs="*", default=None,
                    help="measure only these frame stems")
    args = ap.parse_args()

    root = args.root
    raw = root / "shadowgraph" / "raw"
    pred = args.pred or (root / "shadowgraph" / "analysis" / "predictions_crop.json")
    if not pred.exists():
        pred = root / "shadowgraph" / "analysis" / "predictions.json"
    out_dir = args.out_dir or (root / "shadowgraph" / "analysis" / "skeletonisation_testing")
    out_dir.mkdir(parents=True, exist_ok=True)

    bg = cv2.imread(str(raw / "background_median.tiff"), cv2.IMREAD_UNCHANGED)
    if bg is None:
        sys.exit(f"no background at {raw / 'background_median.tiff'}")
    bg = bg.astype(np.float32)

    preds = json.loads(pred.read_text())
    inst = json.loads((raw / "instances.json").read_text())
    stem_by_id = {im["id"]: im["file_name"].rsplit(".", 1)[0] for im in inst["images"]}

    by_img = {}
    for d in preds:
        if d["score"] >= args.score_thresh:
            by_img.setdefault(d["image_id"], []).append(d)

    ids = sorted(stem_by_id)
    if args.frames:
        want = set(args.frames)
        ids = [i for i in ids if stem_by_id[i] in want]
        missing = want - {stem_by_id[i] for i in ids}
        if missing:
            sys.exit(f"not in instances.json: {sorted(missing)}")
    if args.limit:
        ids = ids[:args.limit]

    t0 = time.time()
    rows, all_comps = [], []
    focus_all, oof_all = [], []
    mode = args.images_mode or ("all" if args.images else None)
    draw_all = mode == "all"
    draw_extremes = mode == "extremes"
    img_dir = out_dir / ("extreme_images" if draw_extremes else "images")
    if mode:
        img_dir.mkdir(exist_ok=True)
    held = {}        # extremes mode: keep what drawing needs, decide afterwards

    for k, img_id in enumerate(ids, 1):
        stem = stem_by_id[img_id]
        raw16 = cv2.imread(str(raw / "frames" / "16bit" / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
        if raw16 is None:
            print(f"  !! {stem}: no 16-bit frame, skipped")
            continue
        T = raw16.astype(np.float32) / np.maximum(bg, 1.0)
        dets = by_img.get(img_id, [])
        row, comps, fa, oa, unatom = measure_frame(T, dets, args)
        row["frame"] = stem
        rows.append(row)
        all_comps.extend((stem, a) for a in comps)
        focus_all.extend(fa)
        oof_all.extend(oa)

        if draw_all:
            view8 = cv2.imread(str(raw / "frames" / "8bit" / f"{stem}.png"),
                               cv2.IMREAD_UNCHANGED)
            if view8 is not None:
                cv2.imwrite(str(img_dir / f"{stem}.png"),
                            draw_frame(view8, dets, T, unatom, row, args))
        elif draw_extremes:
            # which frames are extreme is only known once every frame is
            # measured, so hold the cheap inputs and draw at the end
            held[stem] = (dets, unatom, row)

        if k % 25 == 0 or k == len(ids):
            el = time.time() - t0
            print(f"  {k:4}/{len(ids)}  {el:5.1f}s  ({el / k:.2f} s/frame)")

    if not rows:
        sys.exit("no frames measured")

    # THE ATOMISED EXTREMES BELONG TO THIS PASS. measure_run also records
    # "atomised_extreme_frames", but it picks them from its MODEL-ONLY atomised
    # figure (reference only, never reported), not from the classical fraction
    # that is actually quoted. The two can disagree.
    _val = [(r["frame"], r["atomised_pct"]) for r in rows
            if r.get("atomised_pct") == r.get("atomised_pct")]   # drop NaN
    extremes = None
    if _val:
        _val.sort(key=lambda z: z[1])
        extremes = {"lowest": {"frame": _val[0][0], "atomised_pct": round(_val[0][1], 3)},
                    "highest": {"frame": _val[-1][0], "atomised_pct": round(_val[-1][1], 3)}}
        if draw_extremes:
            for stem in {_val[0][0], _val[-1][0]}:
                if stem not in held:
                    continue
                dets_e, unatom_e, row_e = held[stem]
                view8 = cv2.imread(str(raw / "frames" / "8bit" / f"{stem}.png"),
                                   cv2.IMREAD_UNCHANGED)
                if view8 is None:
                    continue
                raw16 = cv2.imread(str(raw / "frames" / "16bit" / f"{stem}.tiff"),
                                   cv2.IMREAD_UNCHANGED)
                T_e = raw16.astype(np.float32) / np.maximum(bg, 1.0)
                cv2.imwrite(str(img_dir / f"{stem}.png"),
                            draw_frame(view8, dets_e, T_e, unatom_e, row_e, args))
            print(f"  extreme images: {_val[0][0]} (lowest {_val[0][1]:.2f}%), "
                  f"{_val[-1][0]} (highest {_val[-1][1]:.2f}%)")

    # POOLED, not averaged. The atomised fraction is a ratio of areas, so every
    # pixel in the run goes into one sum -- averaging per-frame percentages
    # would weight a near-empty frame the same as a full one.
    tot = sum(r["total_liquid_px"] for r in rows)
    drp = sum(r["droplet_px"] for r in rows)
    pooled = 100.0 * drp / tot if tot else float("nan")
    # D32 is a ratio of moments, so it pools over every droplet in the run --
    # never an average of per-frame values.
    pooled_d32 = d32(focus_all) if focus_all else float("nan")

    fields = ["frame", "total_liquid_px", "droplet_px", "unatomised_px",
              "atomised_pct", "d32_in_focus_um", "droplets_in_focus",
              "droplets_out_of_focus", "n_components",
              "n_droplet_components_dropped"]
    with open(out_dir / "classical_per_frame.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows([{k: r[k] for k in fields} for r in rows])

    with open(out_dir / "classical_components.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "area_px", "area_mm2"])
        for stem, a in all_comps:
            w.writerow([stem, a, round(float(px_to_mm2(a)), 6)])

    areas = np.array([a for _, a in all_comps], float)
    summary = {
        "measured_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.time() - t0, 1),
        "provenance": {
            "predictions": str(pred),
            "seed_thr": args.seed, "ceiling_thr": args.ceiling,
            "edge": "per-component half-max (t_min+1)/2",
            "min_area_px": args.min_area,
            "droplet_cover": args.droplet_cover,
            "droplet_max_extent": args.droplet_max_extent,
            "score_threshold": args.score_thresh,
            # The atomised fraction is this file's output, and 2.1.0 changed how
            # its numerator is measured. Without this field a pre-2.1.0 and a
            # post-2.1.0 atomised % look identical and would be compared
            # silently -- a ~3% difference with nothing to flag it.
            "sizer_version": sizer_version(args.sharpness_rule),
            "sharpness_rule": args.sharpness_rule,
            "atomised_numerator_edge": "half-max where measured, model mask "
                                       "otherwise (out of focus or below split)",
            "classical_only": args.classical_only,
            "um_per_px": UM_PER_PX,
        },
        "definitions": {
            "atomised_pct": "union(model droplets) / union(classical liquid, model droplets, "
                            "OUT-OF-FOCUS model filaments/blobs). "
                            "ONE union, so a droplet overlapping un-atomised liquid is counted "
                            "once -- this is the structural fix for the cross-class "
                            "double-counting bug.",
            "components": "connected regions of classical liquid AFTER whole-component "
                          "removal of already-detected droplets. Un-atomised objects only. "
                          "No filament/blob split: real regions are routinely both.",
            "caveat": "seed T<=0.70 IS the focus gate, so the classical mask is in-focus "
                      "liquid. Out-of-focus droplets enter via the union with the model's "
                      "masks; out-of-focus un-atomised liquid is not measured.",
        },
        "frames": len(rows),
        "atomised_pct_pooled": round(pooled, 3),
        "d32_in_focus_um": round(pooled_d32, 2) if focus_all else None,
        "droplets_in_focus": len(focus_all),
        "droplets_out_of_focus": len(oof_all),
        "total_liquid_px": int(tot),
        "droplet_px": int(drp),
        "unatomised_px": int(tot - drp),
        "atomised_extreme_frames": extremes,
        "n_components": len(areas),
        "component_area_px": {
            "mean": round(float(areas.mean()), 1) if areas.size else None,
            "p50": round(float(np.percentile(areas, 50)), 1) if areas.size else None,
            "p90": round(float(np.percentile(areas, 90)), 1) if areas.size else None,
            "max": int(areas.max()) if areas.size else None,
        },
    }
    (out_dir / "classical_summary.json").write_text(json.dumps(summary, indent=2))

    # Same two-panel layout as measure_run's size_histograms.png, so this can be
    # read beside the existing run images without re-learning the format. Panel 1
    # is unchanged (droplets come from the model either way); panel 2 is the one
    # that differs -- classical whole-frame regions, with no filament/blob split
    # because a real region is routinely both.
    png = None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        focus_d = equiv_um(focus_all) if focus_all else np.array([])
        oof_d = equiv_um(oof_all) if oof_all else np.array([])
        mm2 = px_to_mm2(areas) if areas.size else np.array([])

        fig, axes = plt.subplots(2, 1, figsize=(10, 9))

        ax = axes[0]
        all_d = np.concatenate([d for d in (focus_d, oof_d) if d.size]) \
            if (focus_d.size or oof_d.size) else np.array([])
        if all_d.size:
            top = (np.floor(all_d.max() / DROPLET_BIN_UM) + 1) * DROPLET_BIN_UM
            edges = np.arange(0, top + DROPLET_BIN_UM, DROPLET_BIN_UM)
            ax.hist([focus_d, oof_d], bins=edges, stacked=True,
                    color=[PLOT_GREEN, PLOT_MAGENTA],
                    label=[f"in focus (n={focus_d.size:,})",
                           f"out of focus (n={oof_d.size:,})"],
                    edgecolor="white", linewidth=0.5)
            ax.set_xticks(edges[::2])
            ax.legend()
        ax.set_title(f"Droplet diameter \u2014 {DROPLET_BIN_UM:.0f} \u00b5m bins\n"
                     "D32 uses the in-focus population only (unchanged: from the model)",
                     fontsize=11)
        ax.set_xlabel("equivalent diameter (\u00b5m)")
        ax.set_ylabel("count")

        ax = axes[1]
        if mm2.size and mm2.min() > 0 and mm2.max() > mm2.min():
            edges = np.logspace(np.log10(mm2.min()), np.log10(mm2.max()), 30)
            ax.hist(mm2, bins=edges, color=PLOT_ORANGE,
                    label=f"un-atomised region (n={mm2.size:,})",
                    edgecolor="white", linewidth=0.5)
            ax.set_xscale("log")
            ax.legend()
        ax.set_title(f"Un-atomised liquid \u2014 area, log bins (n={mm2.size:,})\n"
                     "CLASSICAL whole-frame measurement", fontsize=11)
        ax.set_xlabel("area (mm\u00b2)")
        ax.set_ylabel("count")

        ax.text(0.5, -0.22,
                "One region = one connected piece of liquid, measured whole-frame, so it is NOT "
                "cut at tile seams\nand NOT split into sub-segments. No filament/blob split: a "
                "region is routinely both.",
                transform=ax.transAxes, ha="center", va="top",
                fontsize=8, color="#555555")

        fig.tight_layout()
        png = out_dir / "size_histograms.png"
        fig.savefig(png, dpi=130, bbox_inches="tight")
        plt.close(fig)
    except ImportError:
        print("  (matplotlib not installed -- CSVs written, histogram skipped)")

    print("\n" + "=" * 64)
    print(f"  frames                 {len(rows)}")
    print(f"  D32 (in-focus)         {pooled_d32:.1f} um   [from the model, unchanged]")
    print(f"  atomised (pooled)      {pooled:.3f} %   [classical denominator]")
    print(f"  total liquid           {tot:,} px")
    print(f"  un-atomised            {tot - drp:,} px")
    print(f"  un-atomised components {len(areas):,}")
    print("=" * 64)
    if png:
        print(f"  histogram {png.name}")
    print(f"  written to {out_dir}")


if __name__ == "__main__":
    main()
