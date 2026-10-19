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

DROPS ON THE WINDOW (liquid stage 2.3.0, 2026-10-13)
-----------------------------------------------------
A drop of silicone on the glass is not spray, but it was being counted as
un-atomised liquid, by two routes (docs/notes/2026-10-13_area_vs_volume_and_window.md):

  A. A drop that LANDS mid-run is in under half the frames, so it is not in the
     background median and the classical pass counts it in every frame after it
     lands (CCD C9: +7 points of atomised fraction once removed). Fix: a WINDOW
     MASK from a first pass over every frame: a piece of un-atomised liquid that
     sits on the same pixels in >= WINDOW_P of the frames, is compact, and is
     flat-topped in that persistence map (a drop on the glass does not move; a
     jet or stream wobbles and fades at its edges) is masked out of numerator and
     denominator in EVERY frame. The masked area is recorded.
  B. A drop present all run IS in the median and divides out of T (C20: T 0.998
     in its core), but the model, which runs on the un-normalised frame, still
     detects it, and with T ~ 1 it always passes the out-of-focus test, so its
     whole mask went into the denominator (41% of C20's un-atomised liquid). Fix:
     an out-of-focus non-droplet detection whose mean T is >= STATIC_T has nothing
     left after background division and is not liquid in this frame.

VOLUME (secondary, 2.3.0)
-------------------------
Per frame, the droplet and total liquid VOLUME (liquid_volume.py: droplets as
spheres, un-atomised pieces with a round cross-section) for a volume-based
atomised fraction. The AREA fraction stays the headline: volume ranks runs like
area but is ~3x noisier and its absolute scale is good to about +/-40%.

Usage:
    python classical_liquid.py --root <run>            # all frames
    python classical_liquid.py --root <run> --limit 20
"""

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pycocotools import mask as mask_util  # noqa: E402
import liquid_volume  # noqa: E402
import background  # noqa: E402  (sizer 3.1.0: the rolling background)
import measure_run  # noqa: E402
import optics  # noqa: E402
from measure_run import (  # noqa: E402
    det_crop, px_to_mm2, equiv_um, d32, annotate, ring_contours,
    measure_droplet, sizer_version, SPLIT_UM,
    DROPLET, UM_PER_PX, DROPLET_BIN_UM,
    GREEN, MAGENTA, ORANGE,
    PLOT_GREEN, PLOT_MAGENTA, PLOT_ORANGE,
)

# The liquid map (seed T < 0.70, each piece grown to its own half-max) lives in liquid_map.py since sizer 3.1.0:
# measure_run blanks every undetected piece of liquid round a droplet with it, so both stages share one definition.
from liquid_map import SEED_THR, CEILING_THR, MIN_AREA, hysteresis  # noqa: E402,F401
DROPLET_COVER = 0.50
DROPLET_MAX_EXTENT = 100

# ---- liquid stage 2.3.0 (2026-10-13): drops on the window, and volume -----------------
LIQUID_VERSION = "2.3.0"   # 2.2.0 = sizer 2.2.0's liquid stage, before these
STATIC_T = 0.97            # route B: an out-of-focus model piece with mean T >= this is gone
                           # after background division (real out-of-focus liquid: 0.70-0.95)
WINDOW_P = 0.20            # route A: un-atomised in at least this share of frames ...
WINDOW_MAX_EXTENT = 400    # ... compact: at most this many px across (4 mm) ...
WINDOW_ASPECT = 3.0        # ... and not long and thin (a stream is) ...
WINDOW_PLATEAU = 0.60      # ... and flat-topped: this share of it within 70% of its peak persistence
WINDOW_GROW = 3            # px added round a window object (its edge flickers frame to frame)


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


def _others(T, dets, args_ref, liquid=None):
    """Sizer 3.0.0: the frame's occupancy (measure_run.occupancy) from the same detections measure_run measures
    (tile-truncated pieces left out, as there), so a droplet gets the same verdict in both stages. None for 2.x.
    Sizer 3.1.0 adds the frame's liquid map (the same hysteresis measure_run uses, given here as `liquid`)."""
    v = getattr(args_ref, "sizer_version", None)
    if not measure_run.blur.is_sizer3(v):
        return None
    if v == measure_run.SIZER_VERSION_31 and liquid is None:
        liquid, _ = hysteresis(T)
    return measure_run.occupancy(T.shape, [d for d in dets if not d.get("truncated", False)],
                                 liquid if v == measure_run.SIZER_VERSION_31 else None)


def _sizer_liquid(liquid, args_ref):
    """The liquid map measure_run blanks with (sizer 3.1.0) is the plain hysteresis at its default thresholds. This
    stage's own map is that one unless --seed / --ceiling / --min-area changed it; then None (rebuilt at the
    defaults), so a droplet always gets the same verdict in both stages."""
    if liquid is None or args_ref is None:
        return liquid
    same = (getattr(args_ref, "seed", SEED_THR) == SEED_THR and getattr(args_ref, "ceiling", CEILING_THR) == CEILING_THR
            and getattr(args_ref, "min_area", MIN_AREA) == MIN_AREA)
    return liquid if same else None


def model_masks(dets, T, focus_max, args_ref=None, liquid=None):
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

    STATIC PIECES (2.3.0): an out-of-focus non-droplet detection whose mean T is
    >= static_t (args_ref.static_t, default STATIC_T; 0 = off) is a drop on the
    window that the background division has already removed: the model still
    sees it on the raw frame, but there is no liquid left there. Counted in
    model_masks.last_static.
    """
    drop = np.zeros(T.shape, bool)
    oof = np.zeros(T.shape, bool)
    n_half = n_model = n_static = 0
    static_t = getattr(args_ref, "static_t", STATIC_T) if args_ref is not None else STATIC_T
    others = _others(T, dets, args_ref, _sizer_liquid(liquid, args_ref))
    vol3 = others is not None                     # sizer 3.0.0: which droplets are inside the measurement volume
    v31 = getattr(args_ref, "sizer_version", None) == measure_run.SIZER_VERSION_31
    drops = []                                    # 3.1.0: (method, in_volume, sized, size, size_raw, mask_d, bx, by, mb)
    dvol = np.zeros(T.shape, bool) if vol3 else None
    undecided = np.zeros(T.shape, bool) if vol3 else None
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
                                 sharpness_rule=getattr(args_ref, "sharpness_rule", False),
                                 version=getattr(args_ref, "sizer_version", None), others=others)
            if md and md["method"] == "static":
                continue                        # 3.1.0: a speck in the same place every frame is not spray
            if v31 and md:
                drops.append((md["method"], md["in_volume"], md["in_focus"], md["size_um"],
                              md.get("size_raw_um", float("nan")), md.get("mask_d_um", float("nan")), bx, by, mb))
            hm = md.get("mask") if md else None
            if hm is not None:
                hx, hy = md["mask_xy"]
                drop[hy:hy + hm.shape[0], hx:hx + hm.shape[1]] |= hm
                n_half += 1
            else:
                drop[by:by + bh, bx:bx + bw] |= mb
                n_model += 1
            if vol3 and md:
                # in the volume by its own verdict; crowded and frame-edge droplets have none and take their
                # liquid object's (volume_masks); no-chi ones count as outside (Ben, 2026-10-16)
                tgt = dvol if md["in_volume"] else \
                    undecided if md["method"] in measure_run.UNMEASURED + ("border",) else None
                if tgt is not None:
                    if hm is not None:
                        tgt[hy:hy + hm.shape[0], hx:hx + hm.shape[1]] |= hm
                    else:
                        tgt[by:by + bh, bx:bx + bw] |= mb
        else:
            tin = T[by:by + bh, bx:bx + bw][mb]
            if tin.min() > focus_max:
                if static_t and float(tin.mean()) >= static_t:
                    n_static += 1               # nothing there after background division
                else:
                    oof[by:by + bh, bx:bx + bw] |= mb
    model_masks.last_counts = (n_half, n_model)
    model_masks.last_static = n_static
    model_masks.last_vol = (dvol, undecided) if vol3 else None
    model_masks.last_drops = drops
    return drop, oof


def volume_masks(T, liquid, dmask, oof, dvol, undecided, args):
    """Sizer 3.0.0 (plan, Phase 5): (droplets inside the measurement volume, un-atomised liquid inside it).

    Every connected piece of liquid (a ligament, a blob, or a droplet with its rim) is judged by its own blur width,
    blur.object_chi, measured with every other piece blanked; inside if chi <= chi_max. Its un-atomised pixels follow
    that verdict, and so do crowded and frame-edge droplets in it (they have no verdict of their own). A piece that
    is mostly droplet (its un-atomised part a rim) takes its droplets' verdict instead, by area. A piece with no edge
    to measure (too faint) is outside."""
    cal = measure_run.SIZER3
    total = liquid | dmask if args.classical_only else liquid | dmask | oof
    un = total & ~dmask
    dv, uv = dvol.copy(), np.zeros(T.shape, bool)
    n, lab, stats, _c = cv2.connectedComponentsWithStats(total.astype(np.uint8), connectivity=8)
    n_meas = n_in = 0
    for i in range(1, n):
        x, y, w, h = (int(v) for v in stats[i, :4])
        sub = lab[y:y + h, x:x + w] == i
        u_sub = un[y:y + h, x:x + w] & sub
        und = undecided[y:y + h, x:x + w] & sub
        if not u_sub.any() and not und.any():
            continue
        d_sub = dmask[y:y + h, x:x + w] & sub
        if not und.any() and d_sub.any() and u_sub.sum() < d_sub.sum():
            inside = (dvol[y:y + h, x:x + w] & sub).sum() * 2 >= d_sub.sum()
        else:
            r = measure_run.blur.object_chi(T, sub, x, y, cal["tau"], measure_run.droplet_core,
                                            measure_run.UM_PER_PX, others=total)
            n_meas += 1
            inside = bool(np.isfinite(r["chi_um"]) and r["chi_um"] <= cal["chi_max_um"])
        if inside:
            n_in += 1
            uv[y:y + h, x:x + w] |= u_sub
            dv[y:y + h, x:x + w] |= und
    volume_masks.last_counts = (n_meas, n_in)
    return dv, uv


VOLUME_FIELDS = ("vol_sized_in_volume_mm3", "vol_below_d_min_in_volume_mm3", "vol_unmeasured_in_volume_mm3",
                 "vol_unatomised_in_volume_mm3", "vol_droplets_in_volume_mm3", "vol_liquid_in_volume_mm3")


def inside_droplets(drops, dv):
    """Sizer 3.1.0: the droplets of one frame that ended inside the measurement volume, by their own verdict or
    (crowded, attached, frame edge ...) by their liquid object's (most of their mask in `dv`), as
    (method, sized, size, size_raw, mask_d, cx, cy)."""
    out = []
    for meth, inv, sized, size, raw, mask_d, bx, by, mb in drops:
        if not inv:
            if meth not in measure_run.UNMEASURED + ("border",):
                continue
            if float(dv[by:by + mb.shape[0], bx:bx + mb.shape[1]][mb].mean()) < 0.5:
                continue
        ys, xs = np.nonzero(mb)
        out.append((meth, bool(sized), float(size), float(raw), float(mask_d), bx + float(xs.mean()),
                    by + float(ys.mean())))
    return out


def unmeasured_size_factor(drops3):
    """The run's median measured size / mask-equivalent size of its sized droplets inside the volume (~0.65: the AI's
    masks run large), the stand-in for a droplet that could not be sized."""
    r = [d[2] / d[4] for ds in drops3.values() for d in ds if d[1] and d[4] > 0 and math.isfinite(d[2])]
    return round(float(np.median(r)), 4) if r else 0.65


def liquid_volume_in_volume(drops, dv, uv, window, k_mask):
    """Sizer 3.1.0 (plan Phase 3): the liquid volume inside the measurement volume of one frame, mm^3, each piece by
    its best size: sized droplets from their calibrated size, droplets below d_min from their measured size, ones
    that could not be measured from their mask's size x k_mask, and the un-atomised liquid (ligaments, blobs) as
    bodies of revolution (liquid_volume.body_volume_px3, as the all-objects volume). The throughput's denominator
    (rates.py): sizes and liquid in one volume, by one rule."""
    if window is not None:
        drops = [d for d in drops if not window[min(window.shape[0] - 1, int(round(d[6]))),
                                                  min(window.shape[1] - 1, int(round(d[5])))]]
    um3 = math.pi / 6.0 * 1e-9                       # pi/6 d^3, um^3 -> mm^3
    v_s = um3 * sum(d[2] ** 3 for d in drops if d[1])
    v_b = um3 * sum(d[3] ** 3 for d in drops if d[0] == "below_d_min" and math.isfinite(d[3]))
    v_u = um3 * sum((k_mask * d[4]) ** 3 for d in drops if not d[1] and d[0] != "below_d_min"
                    and math.isfinite(d[4]))
    v_un = liquid_volume.body_volume_px3(uv, fill=dv) * (UM_PER_PX * 1e-3) ** 3
    return {"vol_sized_in_volume_mm3": round(v_s, 9), "vol_below_d_min_in_volume_mm3": round(v_b, 9),
            "vol_unmeasured_in_volume_mm3": round(v_u, 9), "vol_unatomised_in_volume_mm3": round(v_un, 9),
            "vol_droplets_in_volume_mm3": round(v_s + v_b + v_u, 9),
            "vol_liquid_in_volume_mm3": round(v_s + v_b + v_u + v_un, 9)}


def frame_masks(T, dets, args):
    """(liquid, droplet mask, out-of-focus un-atomised mask) for one frame."""
    liquid, _ = hysteresis(T, args.seed, args.ceiling, args.min_area)
    dmask, oof_unatom = model_masks(dets, T, args.focus_max, args, liquid=liquid)
    return liquid, dmask, oof_unatom


def area_part(liquid, dmask, oof_unatom, args, exclude=None, volume=False):
    """The area (and optionally volume) half of a frame's row, its un-atomised
    component areas and its un-atomised mask. `exclude`: pixels taken out of
    numerator AND denominator (the window mask), or None."""
    if exclude is not None:
        liquid, dmask, oof_unatom = liquid & ~exclude, dmask & ~exclude, oof_unatom & ~exclude
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
    unatom = total & ~dmask
    part = {
        "total_liquid_px": total_px,
        "droplet_px": droplet_px,
        "unatomised_px": unatom_px,
        "atomised_pct": round(100.0 * droplet_px / total_px, 3) if total_px else float("nan"),
        "n_components": n_kept,
        "n_droplet_components_dropped": n_drop,
    }
    if volume:
        mm3 = (UM_PER_PX * 1e-3) ** 3               # one px^3 in mm^3
        dv = liquid_volume.droplet_volume_px3(dmask) * mm3
        uv = liquid_volume.body_volume_px3(unatom, fill=dmask) * mm3
        part["droplet_vol_mm3"] = round(dv, 9)
        part["total_liquid_vol_mm3"] = round(dv + uv, 9)
        part["atomised_vol_pct"] = round(100.0 * dv / (dv + uv), 3) if dv + uv > 0 else float("nan")
    return part, comp_areas, unatom


def droplet_part(T, dets, args, liquid=None):
    """(in-focus areas, out-of-focus areas) of the frame's droplets, from measure_run's
    shared measure_droplet. Independent of the window mask."""
    # Droplet focus AND sizing come from measure_run.measure_droplet -- the one
    # shared implementation. This file used to recompute the focus test itself,
    # twice, and the copies drifted: 85.58 um here against 85.57 um there for the
    # same run. Only the un-atomised denominator is re-derived classically.
    focus_a, oof_a = [], []
    others = _others(T, dets, args, _sizer_liquid(liquid, args))
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
                             sharpness_rule=getattr(args, "sharpness_rule", False),
                             version=getattr(args, "sizer_version", None), others=others)
        if md is None:
            continue
        (focus_a if md["in_focus"] else oof_a).append(md["area_px"])
    return focus_a, oof_a


def _row(part, focus_a, oof_a):
    return {
        "total_liquid_px": part["total_liquid_px"],
        "droplet_px": part["droplet_px"],
        "unatomised_px": part["unatomised_px"],
        "atomised_pct": part["atomised_pct"],
        "d32_in_focus_um": round(d32(focus_a), 2) if focus_a else float("nan"),
        "droplets_in_focus": len(focus_a),
        "droplets_out_of_focus": len(oof_a),
        "n_components": part["n_components"],
        "n_droplet_components_dropped": part["n_droplet_components_dropped"],
        **{k: part[k] for k in ("droplet_vol_mm3", "total_liquid_vol_mm3", "atomised_vol_pct") if k in part},
    }


def measure_frame(T, dets, args, exclude=None):
    """One frame -> (row, component_areas_px, focus_d, oof_d, unatom_mask).

    `liquid` is the full classical mask and is what the ratio uses. `kept` has
    already-detected droplets removed and is only for the size distribution --
    an isolated droplet is still liquid and must stay in the denominator.
    One pass, no window mask unless one is given (main() makes it from all frames).
    """
    liquid, dmask, oof_unatom = frame_masks(T, dets, args)
    part, comp_areas, unatom = area_part(liquid, dmask, oof_unatom, args, exclude,
                                         volume=getattr(args, "volume", False))
    focus_a, oof_a = droplet_part(T, dets, args, liquid)
    return _row(part, focus_a, oof_a), comp_areas, focus_a, oof_a, unatom


def window_mask(persistence, n_frames, args=None):
    """Route A: drops that landed on the window. `persistence`: per pixel, the number of frames
    in which it was un-atomised liquid. A piece is a window object if its peak persistence
    (95th percentile) is >= WINDOW_P, it is compact (<= WINDOW_MAX_EXTENT px across, aspect
    <= WINDOW_ASPECT) and flat-topped (>= WINDOW_PLATEAU of it within 70% of its peak): a drop
    on the glass sits still; a jet or stream wobbles and fades at its edges. Returns (mask or
    None, [(x, y, w, h, area_px, peak persistence, plateau share)]) of the objects found."""
    if not n_frames:
        return None, []
    p_min = getattr(args, "window_p", WINDOW_P) if args is not None else WINDOW_P
    if not p_min:
        return None, []
    P = persistence.astype(np.float32) / float(n_frames)
    cand = (P >= 0.5 * p_min).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand, 8)
    out = np.zeros(P.shape, bool)
    found = []
    for i in range(1, n):
        x0, y0, w, h, a = (int(stats[i, k]) for k in range(5))
        if a < MIN_AREA or max(w, h) > WINDOW_MAX_EXTENT or max(w, h) > WINDOW_ASPECT * max(1, min(w, h)):
            continue
        comp = lab[y0:y0 + h, x0:x0 + w] == i
        p = P[y0:y0 + h, x0:x0 + w][comp]
        peak = float(np.percentile(p, 95))
        if peak < p_min:
            continue
        plateau = float((p >= 0.7 * peak).mean())
        if plateau < WINDOW_PLATEAU:
            continue
        out[y0:y0 + h, x0:x0 + w] |= comp
        found.append((x0, y0, w, h, a, round(peak, 3), round(plateau, 3)))
    if not found:
        return None, []
    if WINDOW_GROW:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * WINDOW_GROW + 1, 2 * WINDOW_GROW + 1))
        out = cv2.dilate(out.astype(np.uint8), k) > 0
    return out, found


def draw_frame(view8, dets, T, unatom, row, args, window=None):
    """Un-atomised liquid FILLED, droplets outlined on top, one image.

    The fill is the classically-measured un-atomised mask -- literally the
    pixels going into the denominator -- so the picture and the number cannot
    disagree. Droplets keep the green/magenta focus convention from
    measure_run so these read the same way as the existing run images.
    """
    canvas = cv2.cvtColor(view8, cv2.COLOR_GRAY2BGR) if view8.ndim == 2 else view8.copy()
    alpha = 0.6                       # 2026-10-19 (Ben: brighter): the filament outline's orange, stronger
    canvas[unatom] = (np.asarray(measure_run.LIGAMENT_STYLE[0], np.float32) * alpha
                      + canvas[unatom].astype(np.float32) * (1 - alpha)).astype(np.uint8)
    others = _others(T, dets, args)
    from collections import Counter
    counts = Counter()
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
                             sharpness_rule=getattr(args, "sharpness_rule", False),
                             version=getattr(args, "sizer_version", None), others=others)
        sharp = bool(md["in_focus"]) if md else False
        full = np.zeros(canvas.shape[:2], np.uint8)
        full[by:by + bh, bx:bx + bw] = mb
        # Ring, not outline: a 9 px droplet's own contour is invisible at full
        # frame scale. Same convention as measure_run so these images read the
        # same way as the ones already in the run folder.
        v3 = others is not None and md is not None              # sizer 3.x: rings by verdict, with a key
        ring = max(args.droplet_ring, 3) if v3 else args.droplet_ring
        if ring > 0:
            cnts = ring_contours(full, d["bbox"], ring, canvas.shape[:2])
        else:
            cnts, _ = cv2.findContours(full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if v3:
            counts[md["method"]] += 1
            cv2.drawContours(canvas, cnts, -1, measure_run.RING_EDGE, measure_run.RING_EDGE_PX, cv2.LINE_AA)
            cv2.drawContours(canvas, cnts, -1, measure_run.VERDICT_STYLE.get(md["method"], (GREEN, ""))[0],
                             measure_run.RING_PX, cv2.LINE_AA)
        else:
            cv2.drawContours(canvas, cnts, -1, GREEN if sharp else MAGENTA, 2)
    win_any = window is not None and window.any()
    if win_any:
        # the masked window drops, outlined in blue: not counted in either measure
        cnts, _ = cv2.findContours(window.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, cnts, -1, (255, 130, 10), 2)
    annotate(canvas, row["d32_in_focus_um"], row["atomised_pct"])
    if counts:
        measure_run.draw_key(canvas, counts, extra=[(measure_run.LIGAMENT_STYLE[0], "un-atomised liquid (filled)", None)]
                             + ([((255, 130, 10), "drop on the window: masked", None)] if win_any else []))
    return canvas


def main():
    global UM_PER_PX
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path,
                    default=Path("/Volumes/LaCie/Experiments/2026/09/28/Trial_1"))
    ap.add_argument("--pred", type=Path, default=None)
    ap.add_argument("--background-rolling", default="auto",
                    help="sizer 3.1.0: 'auto' (default) = the run's rolling background (shadowgraph/analysis/"
                         "background_rolling/, built if missing), as measure_run uses; a folder to use that one; "
                         "'none' for raw/background_median.tiff only. Ignored before 3.1.0")
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
    ap.add_argument("--sharpness-rule", action=argparse.BooleanOptionalAction, default=None,
                    help="sizer 2.2.0 (DEFAULT since 2026-10-08), as measure_run.py: "
                         "moves D32 membership and drawing colour only, never the atomised "
                         "fraction. --no-sharpness-rule measures at 2.1.0")
    ap.add_argument("--sizer", choices=measure_run.blur.SIZERS, default=None,
                    help="the sizer version, as measure_run.py (3.0.0, the default since 2026-10-16: the blur-width "
                         "rule and calibrated sizes, and the atomised fraction inside the measurement volume beside "
                         "the all-objects one). --sharpness-rule / --no-sharpness-rule still mean 2.2.0 / 2.1.0")
    ap.add_argument("--focus-max", type=float, default=0.70,
                    help="droplet focus gate, as measure_run (default 0.70)")
    ap.add_argument("--droplet-ring", type=int, default=10,
                    help="draw droplets as a ring of this radius, as measure_run")
    ap.add_argument("--images-mode", choices=["extremes", "all"], default=None,
                    help="'extremes' draws only the extreme frames: atomised "
                         "min/max (chosen from THIS pass's atomised %%, which is "
                         "the real one -- measure_run picks its extremes from the "
                         "model-only figure) and D32 min/max, up to 4 PNGs; 'all' "
                         "draws every frame. Implies --images.")
    ap.add_argument("--images", action="store_true",
                    help="write a marked-up full-res PNG per frame")
    ap.add_argument("--static-t", type=float, default=STATIC_T,
                    help="out-of-focus model pieces with mean T at or above this are drops already "
                         "divided out of the frame, not liquid (2.3.0; 0 = off)")
    ap.add_argument("--window-p", type=float, default=WINDOW_P,
                    help="mask still, compact drops on the window that are un-atomised in at least "
                         "this share of frames (2.3.0; 0 = off)")
    ap.add_argument("--volume", action=argparse.BooleanOptionalAction, default=True,
                    help="per-frame droplet and total liquid volume (2.3.0; secondary measure)")
    ap.add_argument("--more-extremes", type=Path, default=None,
                    help="measure_run's extreme_frames_more/index.json (busiest and mean-diameter frames); "
                         "in extremes mode those frames are drawn here too, the classical way. Default: "
                         "<root>/shadowgraph/analysis/droplets_<thr>/extreme_frames_more/index.json")
    ap.add_argument("--limit", type=int, default=None, help="first N frames only")
    ap.add_argument("--frames", nargs="*", default=None,
                    help="measure only these frame stems")
    args = ap.parse_args()

    root = args.root
    profile = optics.profile_for(root)                 # the optics this run was captured with
    UM_PER_PX = measure_run.UM_PER_PX = float(profile["um_per_px"])   # measure_run's helpers read its own
    args.sizer_version = sizer_version(args.sharpness_rule, args.sizer)
    if measure_run.blur.is_sizer3(args.sizer_version):
        try:                                           # the run's own profile's calibration, never another's
            measure_run.SIZER3 = measure_run.blur.sizer3(profile)
        except measure_run.blur.CalibrationMissing as e:
            sys.exit(str(e))
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
    roll = None
    if args.sizer_version == measure_run.SIZER_VERSION_31 and args.background_rolling != "none":
        sb = raw / "frames" / "16bit"
        rdir = background.auto_dir(root, sb) if args.background_rolling == "auto" else Path(args.background_rolling)
        if rdir is not None:
            roll = background.ensure_rolling(sb, rdir)
    bg_for = (lambda stem: roll.for_stem(stem)) if roll is not None else (lambda stem: bg)

    preds = json.loads(pred.read_text())
    inst = json.loads((raw / "instances.json").read_text())
    stem_by_id = {im["id"]: im["file_name"].rsplit(".", 1)[0] for im in inst["images"]}

    by_img = {}
    for d in preds:
        if d["score"] >= args.score_thresh:
            by_img.setdefault(d["image_id"], []).append(d)
    if args.sizer_version == measure_run.SIZER_VERSION_31:
        # the same static specks measure_run leaves out (it never sees tile-truncated pieces, so neither does this)
        n_st = measure_run.mark_static({k: [d for d in v if not d.get("truncated", False)] for k, v in by_img.items()},
                                       sorted(stem_by_id, key=lambda i: stem_by_id[i]))
        print(f"  sizer 3.1.0: {n_st} static droplet detections left out (not spray)")

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

    # PASS 1: every frame's masks (kept bit-packed: ~0.9 MB per frame) and droplet
    # sizes, and the persistence of un-atomised liquid at each pixel. A drop that
    # landed on the window can only be told from spray across the whole run.
    shape = bg.shape
    packed = []          # (stem, img_id, liquid, dmask, oof) packed
    sizes = {}           # stem -> (focus areas, out-of-focus areas)
    persistence = np.zeros(shape, np.uint16)
    n_static = 0
    v31 = args.sizer_version == measure_run.SIZER_VERSION_31
    drops3 = {}          # 3.1.0: stem -> the droplets inside the volume, for the liquid volume there
    for k, img_id in enumerate(ids, 1):
        stem = stem_by_id[img_id]
        raw16 = cv2.imread(str(raw / "frames" / "16bit" / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
        if raw16 is None:
            print(f"  !! {stem}: no 16-bit frame, skipped")
            continue
        T = raw16.astype(np.float32) / np.maximum(bg_for(stem), 1.0)
        dets = by_img.get(img_id, [])
        liquid, dmask, oof = frame_masks(T, dets, args)
        n_static += getattr(model_masks, "last_static", 0)
        vol = getattr(model_masks, "last_vol", None)
        sizes[stem] = droplet_part(T, dets, args, liquid)
        total = liquid | dmask if args.classical_only else liquid | dmask | oof
        persistence += (total & ~dmask)
        extra = ()
        if vol is not None:                                   # sizer 3.0.0: what is inside the volume
            dv, uv = volume_masks(T, liquid, dmask, oof, vol[0], vol[1], args)
            extra = (np.packbits(dv), np.packbits(uv))
            if v31:
                drops3[stem] = inside_droplets(getattr(model_masks, "last_drops", []), dv)
        packed.append((stem, img_id, np.packbits(liquid), np.packbits(dmask), np.packbits(oof)) + extra)
        if k % 25 == 0 or k == len(ids):
            el = time.time() - t0
            print(f"  pass 1  {k:4}/{len(ids)}  {el:5.1f}s  ({el / k:.2f} s/frame)")
    if not packed:
        sys.exit("no frames measured")

    window, window_objects = window_mask(persistence, len(packed), args)
    window_px = int(window.sum()) if window is not None else 0
    if window_objects:
        print(f"  window: {len(window_objects)} still drop(s) on the glass masked, {window_px:,} px "
              f"({100.0 * window_px / window.size:.2f}% of the frame)")
    if n_static:
        print(f"  {n_static} out-of-focus model piece(s) with nothing left after background division "
              f"(mean T >= {args.static_t:g}) not counted as liquid")

    # sizer 3.1.0: a droplet inside the volume that could not be sized (crowded, attached, ...) gets its mask's size
    # times this run's median size/mask ratio of the sized ones (AI masks run ~1.5x the true size)
    k_mask = unmeasured_size_factor(drops3) if v31 else None

    # PASS 2: areas (and volumes) with the window masked out of both measures.
    npx = shape[0] * shape[1]
    unpack = lambda b: np.unpackbits(b)[:npx].reshape(shape).astype(bool)
    t1 = time.time()
    for k, (stem, img_id, lq, dm, of, *inv) in enumerate(packed, 1):
        liquid, dmask, oof = unpack(lq), unpack(dm), unpack(of)
        part, comps, unatom = area_part(liquid, dmask, oof, args, exclude=window, volume=args.volume)
        fa, oa = sizes[stem]
        row = _row(part, fa, oa)
        row["frame"] = stem
        if inv:                                               # sizer 3.0.0: the same measure, inside the volume
            dv, uv = unpack(inv[0]), unpack(inv[1])
            if window is not None:
                dv, uv = dv & ~window, uv & ~window
            tv = int((dv | uv).sum())
            row.update(droplet_px_in_volume=int(dv.sum()), total_liquid_px_in_volume=tv,
                       atomised_pct_in_volume=round(100.0 * int(dv.sum()) / tv, 3) if tv else float("nan"))
            if v31:
                row.update(liquid_volume_in_volume(drops3.get(stem, []), dv, uv, window, k_mask))
        rows.append(row)
        all_comps.extend((stem, a) for a in comps)
        focus_all.extend(fa)
        oof_all.extend(oa)
        if draw_all:
            view8 = cv2.imread(str(raw / "frames" / "8bit" / f"{stem}.png"), cv2.IMREAD_UNCHANGED)
            raw16 = cv2.imread(str(raw / "frames" / "16bit" / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
            if view8 is not None and raw16 is not None:
                T = raw16.astype(np.float32) / np.maximum(bg_for(stem), 1.0)
                cv2.imwrite(str(img_dir / f"{stem}.png"),
                            draw_frame(view8, by_img.get(img_id, []), T, unatom, row, args, window))
        elif draw_extremes:
            # which frames are extreme is only known once every frame is
            # measured, so hold the cheap inputs and draw at the end
            held[stem] = (by_img.get(img_id, []), unatom, row)
        if k % 100 == 0 or k == len(packed):
            el = time.time() - t1
            print(f"  pass 2  {k:4}/{len(packed)}  {el:5.1f}s  ({el / k:.2f} s/frame)")
    del packed

    # THE ATOMISED EXTREMES BELONG TO THIS PASS. measure_run also records
    # "atomised_extreme_frames", but it picks them from its MODEL-ONLY atomised
    # figure (reference only, never reported), not from the classical fraction
    # that is actually quoted. The two can disagree.
    #
    # The D32 extremes are drawn here too (added 2026-10-08), so every extreme
    # frame the GUI shows is rendered the classical way: un-atomised liquid
    # filled orange, droplets ringed. They are picked by the same rule as
    # measure_run (raw lowest / highest per-frame D32 among frames with an
    # in-focus droplet), and this pass's per-frame D32 comes from the same
    # shared measure_droplet, so they are the same frames.
    def _atom_entry(r):
        return {"frame": r["frame"], "atomised_pct": round(r["atomised_pct"], 3),
                "droplets": r["droplets_in_focus"] + r["droplets_out_of_focus"],
                "unatomised_px": r["unatomised_px"], "n_components": r["n_components"]}

    def _d32_entry(r):
        return {"frame": r["frame"], "d32_um": r["d32_in_focus_um"],
                "droplets_in_focus": r["droplets_in_focus"],
                "atomised_pct": round(r["atomised_pct"], 3)}

    by_atom = sorted((r for r in rows if r.get("atomised_pct") == r.get("atomised_pct")),
                     key=lambda r: r["atomised_pct"])                 # drop NaN
    by_d32 = sorted((r for r in rows if r["droplets_in_focus"] > 0
                     and r["d32_in_focus_um"] == r["d32_in_focus_um"]),
                    key=lambda r: r["d32_in_focus_um"])
    extremes = ({"lowest": _atom_entry(by_atom[0]), "highest": _atom_entry(by_atom[-1])}
                if by_atom else None)
    d32_extremes = ({"lowest": _d32_entry(by_d32[0]), "highest": _d32_entry(by_d32[-1])}
                    if len(by_d32) >= 2 else None)
    # measure_run's busiest and mean-diameter frames (extreme_frames_more/) are drawn here as
    # well (2026-10-14, Ben): its own drawings outline filaments thinly, so at slide size the
    # un-atomised liquid is hard to see; filled, it reads like the atomised extremes.
    more = []
    if draw_extremes:
        idx = args.more_extremes or (root / "shadowgraph" / "analysis" / f"droplets_{args.score_thresh:.2f}"
                                     / "extreme_frames_more" / "index.json")
        try:
            more = sorted({f["frame"] for f in json.loads(idx.read_text(encoding="utf-8")).get("frames", [])
                           if f.get("frame") in held})
        except (OSError, ValueError, AttributeError):
            more = []
    if draw_extremes:
        to_draw = {e["frame"] for grp in (extremes, d32_extremes) if grp
                   for e in (grp["lowest"], grp["highest"])} | set(more)
        for stem in sorted(to_draw):
            if stem not in held:
                continue
            dets_e, unatom_e, row_e = held[stem]
            view8 = cv2.imread(str(raw / "frames" / "8bit" / f"{stem}.png"),
                               cv2.IMREAD_UNCHANGED)
            if view8 is None:
                continue
            raw16 = cv2.imread(str(raw / "frames" / "16bit" / f"{stem}.tiff"),
                               cv2.IMREAD_UNCHANGED)
            T_e = raw16.astype(np.float32) / np.maximum(bg_for(stem), 1.0)
            cv2.imwrite(str(img_dir / f"{stem}.png"),
                        draw_frame(view8, dets_e, T_e, unatom_e, row_e, args, window))
        if extremes:
            print(f"  atomised extremes: {extremes['lowest']['frame']} "
                  f"(lowest {extremes['lowest']['atomised_pct']:.2f}%), "
                  f"{extremes['highest']['frame']} (highest {extremes['highest']['atomised_pct']:.2f}%)")
        if d32_extremes:
            print(f"  D32 extremes: {d32_extremes['lowest']['frame']} "
                  f"(lowest {d32_extremes['lowest']['d32_um']} um), "
                  f"{d32_extremes['highest']['frame']} (highest {d32_extremes['highest']['d32_um']} um)")

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
    if args.volume:
        fields += ["droplet_vol_mm3", "total_liquid_vol_mm3", "atomised_vol_pct"]
    vol3 = measure_run.blur.is_sizer3(args.sizer_version)
    if vol3:
        fields += ["droplet_px_in_volume", "total_liquid_px_in_volume", "atomised_pct_in_volume"]
    if v31:
        fields += list(VOLUME_FIELDS)
    tot_iv = sum(r.get("total_liquid_px_in_volume", 0) for r in rows)
    drp_iv = sum(r.get("droplet_px_in_volume", 0) for r in rows)
    tot_v = sum(r.get("total_liquid_vol_mm3", 0.0) for r in rows)
    drp_v = sum(r.get("droplet_vol_mm3", 0.0) for r in rows)
    pooled_v = 100.0 * drp_v / tot_v if tot_v else float("nan")
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
            "sizer_version": args.sizer_version,
            **(roll.provenance() if roll is not None else
               {"background_kind": "static"} if args.sizer_version == measure_run.SIZER_VERSION_31 else {}),
            "sharpness_rule": args.sharpness_rule,
            **(measure_run.sizer3_provenance(measure_run.SIZER3)
               if measure_run.blur.is_sizer3(args.sizer_version) else {}),
            "atomised_numerator_edge": "half-max where measured, model mask "
                                       "otherwise (out of focus or below split)",
            "classical_only": args.classical_only,
            "um_per_px": UM_PER_PX,
            "optics_profile": profile["name"],
            "liquid_version": LIQUID_VERSION,
            "static_t": args.static_t,
            "window_p": args.window_p,
            "window_rule": (f"un-atomised in >= {args.window_p:g} of frames, <= {WINDOW_MAX_EXTENT} px "
                            f"across, aspect <= {WINDOW_ASPECT:g}, plateau >= {WINDOW_PLATEAU:g}, "
                            f"grown {WINDOW_GROW} px") if args.window_p else "off",
            "volume": bool(args.volume),
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
            "window": "2.3.0: drops on the window are not liquid. Still, compact pieces present "
                      "in >= window_p of frames are masked out of both measures in every frame; "
                      "out-of-focus model pieces with mean T >= static_t (gone after background "
                      "division) are not counted.",
            "atomised_pct_in_volume": "sizer 3.0.0: droplet area / liquid area, counting only what is inside the "
                                      "measurement volume (blur width <= chi_max): droplets by their own verdict "
                                      "(crowded and frame-edge ones by their liquid piece's, no-chi ones outside), "
                                      "every other piece of liquid by its own blur width (blur.object_chi). The "
                                      "all-objects atomised_pct is kept alongside.",
            "atomised_vol_pct": "2.3.0, SECONDARY: droplet volume (spheres) / total liquid volume "
                                "(un-atomised pieces with a round cross-section, liquid_volume.py). "
                                "Ranks runs like the area fraction; its absolute scale is good to "
                                "about +/-40%.",
        },
        "frames": len(rows),
        "atomised_pct_pooled": round(pooled, 3),
        # sizer 3.0.0 (plan, Phase 5): the same fraction inside the measurement volume only (Ben, 2026-10-15);
        # the all-objects figure above is kept alongside
        "atomised_pct_in_volume_pooled": (round(100.0 * drp_iv / tot_iv, 3) if tot_iv else None) if vol3 else None,
        **({"liquid_in_volume_mm3": round(sum(r["vol_liquid_in_volume_mm3"] for r in rows), 6),
            "droplets_in_volume_mm3": round(sum(r["vol_droplets_in_volume_mm3"] for r in rows), 6),
            "atomised_vol_pct_in_volume_pooled": (round(100.0 * sum(r["vol_droplets_in_volume_mm3"] for r in rows)
                                                        / sum(r["vol_liquid_in_volume_mm3"] for r in rows), 3)
                                                  if sum(r["vol_liquid_in_volume_mm3"] for r in rows) else None),
            "unmeasured_size_factor": k_mask} if v31 else {}),
        "atomised_vol_pct_pooled": (round(pooled_v, 3) if args.volume and tot_v else None),
        "total_liquid_vol_mm3": round(tot_v, 6) if args.volume else None,
        "droplet_vol_mm3": round(drp_v, 6) if args.volume else None,
        "window": {"objects": [dict(zip(("x", "y", "w", "h", "area_px", "peak_persistence", "plateau"), o))
                               for o in window_objects],
                   "masked_px": window_px,
                   "masked_pct_of_frame": round(100.0 * window_px / (shape[0] * shape[1]), 3)},
        "static_pieces_not_counted": n_static,
        "d32_in_focus_um": round(pooled_d32, 2) if focus_all else None,
        "droplets_in_focus": len(focus_all),
        "droplets_out_of_focus": len(oof_all),
        "total_liquid_px": int(tot),
        "droplet_px": int(drp),
        "unatomised_px": int(tot - drp),
        "atomised_extreme_frames": extremes,
        "d32_extreme_frames": d32_extremes,
        "more_extreme_frames": more,           # measure_run's busiest / mean-diameter frames, drawn here too
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
    if args.volume:
        print(f"  atomised by volume     {pooled_v:.3f} %   [secondary, +/-40% in scale]")
    if vol3 and tot_iv:
        print(f"  atomised in the volume {100.0 * drp_iv / tot_iv:.3f} %   [sizer 3.0.0: inside chi <= "
              f"{measure_run.SIZER3['chi_max_um']:g} um only]")
    print(f"  total liquid           {tot:,} px")
    print(f"  un-atomised            {tot - drp:,} px")
    print(f"  un-atomised components {len(areas):,}")
    print("=" * 64)
    if png:
        print(f"  histogram {png.name}")
    print(f"  written to {out_dir}")


if __name__ == "__main__":
    main()
