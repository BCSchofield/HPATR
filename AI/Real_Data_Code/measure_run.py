#!/usr/bin/env python3
"""
measure_run.py -- production measurement for a whole experimental run.

No ground truth required. This is what an actual Taguchi condition gets put
through, and the intended entry point for the GUI.

WHAT IT MEASURES, AND WHY EACH RULE IS THERE
---------------------------------------------
Every predicted droplet is split by its OWN transmission minimum, using the
same focus test the hand labels use (t_min <= FOCUS_MAX):

  IN FOCUS  (green)   -> size is trustworthy
  OUT OF FOCUS (magenta) -> real object, size is not trustworthy

  D32                = IN-FOCUS droplets only.
  atomised fraction  = ALL droplets (in + out of focus) against all liquid.

Those two use different populations ON PURPOSE. D32 is a SIZE statistic, so it
must only see objects whose size means something. The atomised fraction is an
AREA SHARE -- an out-of-focus droplet is still liquid that has atomised, and
dropping it would understate the numerator while its filaments stayed in the
denominator.

WHAT THE D32 NUMBER IS, AND IS NOT
-----------------------------------
It is "D32 of the droplets this model detected and could size confidently".
It is NOT an unbiased estimate of the spray's true D32: small in-focus droplets
are under-detected (~75% recall at 0-50 um on the benchmark), and missing small
droplets inflates a Sauter mean. Measured against the benchmark's hand labels
the in-focus number reads about +23%.

That bias is fine for RANKING runs -- it applies to every run measured the same
way -- and must never be quoted as an absolute droplet size.

POOLED, NEVER AVERAGED
-----------------------
D32 is a ratio of sums, so every droplet in the run goes into one
Sum(d^3)/Sum(d^2). Averaging per-frame D32 values weights a 3-droplet frame the
same as a 300-droplet one and is simply wrong. Per-frame values are reported for
diagnostics only.

Usage:
    python measure_run.py --pred <...>/v3_predictions.json \\
        --val-dir 09_experiments/20_new_frames \\
        --background <...>/01_candidates/<run>/background_median.tiff \\
        --sixteen-bit-dir <...>/00_frames/<run>/16bit \\
        --images
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import optics  # noqa: E402  (one profile per optical set-up: config/optics/)
import blur  # noqa: E402  (sizer 3.0.0: the blur width and the size, measured as the beads were)

# The scale. main() sets it from the run's own optics profile; this default is the newest profile (the rig's
# set-up now) for callers that measure without a run.
UM_PER_PX = float(optics.current()["um_per_px"])
DROPLET, FILAMENT, BLOB = 1, 2, 3

# BGR. Must match preview_predictions.py so the two tools never disagree.
GREEN = (0, 200, 0)
MAGENTA = (200, 0, 200)
ORANGE = (0, 165, 255)
BLUE = (255, 120, 0)
BLACK = (0, 0, 0)
DROPLET_RING_PX = 10         # droplet outline offset (--droplet-ring)


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


def det_crop(d):
    """(mask_crop, x, y, h, w) for one detection, without ever building a
    frame-sized array if it can be avoided.

    tiled_inference writes `segmentation_crop` -- the mask encoded over its own
    bounding box -- alongside the frame-sized `segmentation` COCO requires.
    Decoding the frame-sized one costs 4.1 M pixels whatever the object's size,
    and the median detection is a 16 px box.

    Predictions written before that field existed still work: they fall back to
    decoding the frame and slicing, which is what this did previously. Slower,
    identical answer.
    """
    sc = d.get("segmentation_crop")
    if sc is not None:
        h, w = sc["size"]
        x, y = (int(v) for v in d["crop_xy"])
        return mask_util.decode(sc).astype(bool), x, y, h, w
    x, y, w, h = mask_util.toBbox(d["segmentation"])
    x, y = int(x), int(y)
    w, h = int(np.ceil(w)), int(np.ceil(h))
    full = mask_util.decode(d["segmentation"])
    return full[y:y + h, x:x + w].astype(bool), x, y, h, w


# ============================================================================
# THE ONE PLACE A DROPLET'S FOCUS VERDICT AND ITS SIZE ARE DECIDED
#
# This test used to be written out three times -- here, and twice in
# classical_liquid.py -- and the copies had already drifted: the two scripts
# reported 85.58 and 85.57 um for the same run. Adding the classical sizer to
# three places would have turned that into real divergence, so everything now
# goes through `measure_droplet` and classical_liquid imports it.
# ============================================================================

# Bump on ANY change that moves a reported number. compare_runs.py and
# taguchi_analysis.py refuse to mix versions, which is the whole point.
#
#   2.0.0  classical half-max sizing at/above the split; interior-pixel core
#          estimator replacing the single darkest pixel.
#   2.1.0  the atomised fraction's NUMERATOR now uses the half-max droplet mask
#          where one exists, instead of the model's raw mask. Both sides of the
#          ratio finally use the same edge; before this, droplets were measured
#          generously against classically-measured un-atomised liquid, which
#          inflated the fraction (MAX TEST: 17.598% -> 17.019%, -3.3% relative).
#          Also: tile-truncated detections excluded from classical's D32, to
#          match measure_run -- they stay in the area union, where a union
#          correctly reassembles an object split across a tile seam.
#   2.2.0  2.1.0 plus the SHARPNESS RULE (the DEFAULT since 2026-10-08, Ben's
#          decision: "using 2.2 for good now"; `--no-sharpness-rule` for 2.1.0): an in-focus
#          droplet >= 50 um is reclassified OUT OF FOCUS when its half-max mask
#          is not round (fill_ratio < 0.85) or its extinction leaks past its own
#          edge (extinction_conc < 0.60). Fitted on Ben's sharp/fuzzy eye labels
#          (2026-10-02). It is a reclassification, never a deletion: counts, the
#          sized area and the atomised numerator are untouched; only D32
#          membership moves. Off, a run is 2.1.0 and bit-identical to before.
#   3.0.0  (sizer 3.0.0 plan, Phase 4, 2026-10-16; opt-in with --sizer 3.0.0 until Ben's Phase 6 go) ONE focus
#          rule and ONE edge for every size, calibrated on certified glass beads (sizer_calibration.py, the optics
#          profile's calibration block): each droplet's blur width chi and Blaisot's contrast-corrected size are
#          measured around its AI mask exactly as the beads were (blur.py). In the measurement volume if chi <=
#          chi_max and its window fits in the frame; sized directly up to chi_sharp, through the look-up table up
#          to chi_max; counted but not sized below d_min. No 40 um split, no sharpness rule, no 0.70 core test for
#          droplets. droplet_sizes.csv gains chi_um, in_volume and size_method.
SIZER_VERSION = "2.1.0"
SIZER_VERSION_SHARPNESS = "2.2.0"
SIZER_VERSION_3 = "3.0.0"
SIZER3 = None                 # sizer 3.0.0's settings (blur.sizer3): main() sets them from the run's own profile
IN_VOLUME = ("direct", "table", "table_extrapolated")
CROWD_PX = 3                  # sizer 3.0.0: another detection this close to a droplet's mask = crowded (not measured);
                              # further off, its mask grown by this much is blanked out before the droplet is measured
SPLIT_UM = 40.0              # classical sizing acts at/above this diameter
DILATE_PX = 5                # search region beyond the model mask
CORE_MIN_PX = 3              # floor for the robust core, see droplet_core
CORE_FRAC = 0.05


def droplet_core(T_crop, mask, estimator="robust"):
    """The droplet's core transmission -- what `t_min` used to be.

    `estimator="min"` is the historical single darkest pixel. That is the
    noisiest statistic available AND it is biased one way: noise can drag a
    minimum down, never up. Measured over 233 droplets it sits 0.010 below the
    mean of the darkest few, and that bias propagates twice --

      * `edge = (core + 1)/2`, so a dark-biased core gives a darker threshold,
        keeps fewer pixels, and reads every diameter 1.6-2.6% SMALL;
      * the focus gate becomes permissive: 2.6% of droplets are in-focus on the
        strength of one pixel, all of them sitting at 0.677-0.699 against a
        0.70 cut.

    `estimator="robust"` averages the darkest max(CORE_MIN_PX, 5%) of the mask's
    INTERIOR pixels -- the mask eroded by one, i.e. pixels fully covered by the
    droplet.

    THE INTERIOR RESTRICTION IS THE WHOLE POINT, and a first attempt without it
    was wrong. Measured on 7,965 Trial_1 droplets, the share with NO interior
    pixel at all is:

        < 25 um   100.0%        40-50 um    0.7%
        25-30     99.9%         50-60       0.0%
        30-40     71.8%         > 80        0.0%

    A 4-6 px mask eroded by one is EMPTY: every pixel straddles the boundary and
    is part droplet, part background. Averaging those is not noise suppression,
    it is partial-volume dilution, and it penalises a droplet for being small --
    exactly backwards. Without the restriction the gate lost 30% of droplets
    under 25 um and 15% of the whole in-focus population; with it, droplets
    under 25 um are completely unaffected (0.00 pp) and the overall change is
    -2.1 pp, falling only where there is a real core to average.

    This also protects the design's central asymmetry: a SMALL out-of-focus
    droplet blurs and loses contrast, so it fails the gate on its own. A small
    droplet that IS dark is therefore in focus, and must be counted.

    With no interior there is nothing to average and the single minimum is the
    only estimate available, so that is what is returned.

    NOTE `focus_max` 0.70 was calibrated against the single-pixel minimum, so
    this makes the gate slightly stricter for droplets that HAVE a core. That is
    a deliberate, recorded change -- see SIZER_VERSION.
    """
    v = np.sort(np.asarray(T_crop[mask], dtype=np.float32), axis=None)
    if v.size == 0:
        return float("nan")
    if estimator == "min":
        return float(v[0])
    inner = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    if not inner.any():
        return float(v[0])
    iv = np.sort(np.asarray(T_crop[inner], dtype=np.float32), axis=None)
    k = max(CORE_MIN_PX, int(round(CORE_FRAC * iv.size)))
    return float(iv[:min(k, iv.size)].mean())


def halfmax_area(T_pad, mask_pad, core_t, dilate_px=DILATE_PX):
    """Half-max area in px for one droplet, and whether anything was measured.

    The edge is the project-wide `(core + 1)/2`, grown inside a DILATED SEARCH
    REGION -- never inside the candidate mask itself. refine_labels.py:322-332
    records that thresholding within the candidate clips every object with
    t_min > 0.40: median true area 1.5x larger, worst case 14x.

    Returns (area_px, degenerate, component_mask). `degenerate` means the half-max component
    came out exactly equal to the model's mask, so the measurement reproduced
    its own input. Such a droplet is still counted and still sized -- only the
    provenance differs, and it carries ~2% of the d^3 weight.
    """
    k = np.ones((2 * dilate_px + 1,) * 2, np.uint8)
    search = cv2.dilate(mask_pad.astype(np.uint8), k).astype(bool)
    grown = search & (T_pad < (core_t + 1.0) / 2.0)
    n, lab = cv2.connectedComponents(grown.astype(np.uint8), 8)
    masked = np.where(mask_pad, T_pad, np.inf)
    cy, cx = np.unravel_index(np.argmin(masked), masked.shape)
    comp_id = lab[cy, cx]
    if comp_id <= 0:
        return 0, False, None
    comp = lab == comp_id
    area = int(comp.sum())
    return area, area == int(mask_pad.sum()), comp


# The sharpness rule, exactly as validated in "Classical Droplet Sizing
# Testing/code/run_all_frames.py" + inspect_droplets.measure (2026-10-02): its
# own split on the MODEL diameter, and its metrics on a half-max component grown
# from the single darkest mask pixel -- NOT the sizer's robust core. The two
# thresholds were fitted on that definition; computing them on the sizer's
# component would quietly move them.
SHARPNESS_SPLIT_UM = 50.0
FILL_RATIO_MIN = 0.85        # below: not round (blobs, merged pairs)
EXTINCTION_CONC_MIN = 0.60   # below: blurred, optical depth leaks past the edge


def sizer_version(sharpness_rule: bool, sizer: str | None = None) -> str:
    """The version a run is measured at: `sizer` when given, else the sharpness switch (2.2.0 / 2.1.0)."""
    return blur.resolve_sizer(sizer, sharpness_rule)


def sizer3_settings() -> dict:
    """Sizer 3.0.0's settings: the ones main() loaded from the run's profile, else the newest profile's."""
    global SIZER3
    if SIZER3 is None:
        SIZER3 = blur.sizer3(optics.current())
    return SIZER3


def sharpness_metrics(T_pad, m_pad, dilate_px=DILATE_PX):
    """(fill_ratio, extinction_conc) for one droplet; NaN where undefined.

    fill_ratio      = half-max area / area of its minimum enclosing circle
    extinction_conc = sum(1-T) inside the half-max mask / sum(1-T) over the
                      model mask dilated by `dilate_px` (the search region)
    """
    k = np.ones((2 * dilate_px + 1,) * 2, np.uint8)
    search = cv2.dilate(m_pad.astype(np.uint8), k).astype(bool)
    _, _, comp = halfmax_area(T_pad, m_pad, float(T_pad[m_pad].min()), dilate_px)
    if comp is None:
        return float("nan"), float("nan")
    area = int(comp.sum())
    ext_total = float((1.0 - T_pad)[search].sum())
    conc = float((1.0 - T_pad)[comp].sum()) / ext_total if ext_total > 0 else float("nan")
    fill = float("nan")
    if area >= 4:
        cnts, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            _, r_enc = cv2.minEnclosingCircle(max(cnts, key=cv2.contourArea))
            if r_enc > 0:
                fill = area / (np.pi * r_enc ** 2)
    return fill, conc


def measure_droplet(T, d, focus_max, split_um=SPLIT_UM, core_estimator="robust",
                    sizer=True, crop=None, want_mask=False, sharpness_rule=False, version=None, calib=None,
                    others=None):
    """Focus verdict and sized area for ONE droplet detection.

    Returns None for an empty mask, else a dict:
        in_focus  bool   -- drives D32 membership AND the green/magenta colour
        area_px   float  -- what D32 is built from
        method    str    -- halfmax | model_degenerate | model_below_split
                            | model_out_of_focus | model_no_sizer
        core_t    float
        reclassified bool -- the sharpness rule moved it out of focus (2.2.0)

    NOTHING IS EVER DROPPED HERE. An out-of-focus droplet keeps its area and
    still counts toward the atomised fraction; only its SIZE is withheld from
    D32. The sizer changes a number, never membership.

    `version` "3.0.0" (sizer 3.0.0) answers through measure_droplet_3 instead, with `calib` (blur.sizer3) or the
    run's own; None or "2.2.0" / "2.1.0" is the sharpness switch, exactly as before.
    """
    mb, bx, by, bh, bw = crop if crop is not None else det_crop(d)
    if version == SIZER_VERSION_3:
        return measure_droplet_3(T, d, (mb, bx, by, bh, bw), calib or sizer3_settings(), core_estimator, want_mask,
                                 others)
    if not mb.any():
        return None
    H, W = T.shape
    pad = DILATE_PX + 2
    y0, y1 = max(0, by - pad), min(H, by + bh + pad)
    x0, x1 = max(0, bx - pad), min(W, bx + bw + pad)
    T_pad = T[y0:y1, x0:x1]
    m_pad = np.zeros(T_pad.shape, bool)
    m_pad[by - y0:by - y0 + bh, bx - x0:bx - x0 + bw] = mb
    if not m_pad.any():
        return None

    core_t = droplet_core(T_pad, m_pad, core_estimator)
    in_focus = bool(core_t <= focus_max)
    area = float(d["area"])
    method = "model_no_sizer"
    half_mask = None
    if not sizer:
        pass
    elif not in_focus:
        method = "model_out_of_focus"
    elif equiv_um(area) < split_um:
        method = "model_below_split"
    else:
        a_half, degenerate, comp = halfmax_area(T_pad, m_pad, core_t)
        if a_half >= 4:
            area = float(a_half)
            method = "model_degenerate" if degenerate else "halfmax"
            half_mask = comp
        else:
            method = "model_no_component"

    # The sharpness rule only ever moves a droplet OUT of focus. Its sized area
    # and half-max mask are kept, so the atomised numerator and every count are
    # identical with the rule on or off; only D32 membership changes.
    reclassified = False
    if sharpness_rule and in_focus and equiv_um(float(d["area"])) >= SHARPNESS_SPLIT_UM:
        fill, conc = sharpness_metrics(T_pad, m_pad)
        if (np.isfinite(fill) and fill < FILL_RATIO_MIN) or \
                (np.isfinite(conc) and conc < EXTINCTION_CONC_MIN):
            in_focus, reclassified = False, True
    out = {"in_focus": in_focus, "area_px": area, "method": method,
           "core_t": core_t, "reclassified": reclassified}
    if want_mask:
        # The half-max component, placed back at its frame offset. None when no
        # half-max measurement was made (out of focus, below the split, or no
        # component) -- the caller then has only the model's mask to fall back on.
        out["mask"] = half_mask
        out["mask_xy"] = (x0, y0)
    return out


def occupancy(T_shape, dets):
    """Sizer 3.0.0: (every detection's mask, the same grown by CROWD_PX) for one frame, so each droplet can be
    measured on its own profile (measure_droplet_3's `others`)."""
    occ = np.zeros(T_shape, bool)
    for d in dets:
        mb, bx, by, bh, bw = det_crop(d)
        occ[by:by + bh, bx:bx + bw] |= mb
    k = np.ones((2 * CROWD_PX + 1,) * 2, np.uint8)
    return occ, cv2.dilate(occ.astype(np.uint8), k).astype(bool)


def measure_droplet_3(T, d, crop, calib, core_estimator="robust", want_mask=False, others=None):
    """Sizer 3.0.0 for ONE droplet detection. Returns None for an empty mask, else measure_droplet's dict plus
        chi_um     the blur width (nan where it could not be measured)
        size_um    the 3.0.0 diameter (nan unless sized)
        in_volume  inside the measurement volume: chi <= chi_max and its window fits in the frame
    with in_focus = in the volume AND sized (>= d_min): what D32, the mean and the band are built from, and
    method = direct | table | table_extrapolated (in the volume, sized), below_d_min (in the volume, counted, not
    sized), outside (chi > chi_max), border (too near the frame edge to measure), no_chi (no edge to measure),
    crowded (another detection within CROWD_PX of its mask: its profile is not its own).
    A sized droplet's area_px is its diameter's equivalent area, so equiv_um(area_px) gives the diameter back; any
    other keeps the model's mask area, as an out-of-focus droplet always has.

    `others` = occupancy(T.shape, the frame's detections): the beads were isolated, a spray droplet is not, so every
    OTHER detection's mask (grown by CROWD_PX) is set to background before measuring, and the droplet's own centre
    must be dark (no fallback to a nearby piece: in a spray that is the jet). Without it (a lone object) the
    measurement is exactly the beads'."""
    mb, bx, by, bh, bw = crop
    if not mb.any():
        return None
    H, W = T.shape
    pad = DILATE_PX + 2
    y0, y1 = max(0, by - pad), min(H, by + bh + pad)
    x0, x1 = max(0, bx - pad), min(W, bx + bw + pad)
    T_pad = T[y0:y1, x0:x1]
    m_pad = np.zeros(T_pad.shape, bool)
    m_pad[by - y0:by - y0 + bh, bx - x0:bx - x0 + bw] = mb
    core_t = droplet_core(T_pad, m_pad, core_estimator)
    ys, xs = np.nonzero(mb)
    cx, cy = bx + float(xs.mean()), by + float(ys.mean())
    d_px = 2.0 * math.sqrt(float(d["area"]) / math.pi)
    # a local copy of the frame, wide enough for the whole measurement (or reaching the frame's own edge, so a
    # window that does not fit in the frame does not fit here either)
    half = blur.half_window(d_px)
    reach = half + half // 2 + blur.RECENTRE_PX + 8
    X0, X1 = max(0, int(round(cx)) - reach), min(W, int(round(cx)) + reach + 1)
    Y0, Y1 = max(0, int(round(cy)) - reach), min(H, int(round(cy)) + reach + 1)
    TL = T[Y0:Y1, X0:X1]
    crowded = False
    if others is not None:
        occ, occ_grown = others
        own = np.zeros(TL.shape, bool)
        oy0, ox0 = max(by, Y0), max(bx, X0)
        oy1, ox1 = min(by + bh, Y1), min(bx + bw, X1)
        own[oy0 - Y0:oy1 - Y0, ox0 - X0:ox1 - X0] = mb[oy0 - by:oy1 - by, ox0 - bx:ox1 - bx]
        k = np.ones((2 * CROWD_PX + 1,) * 2, np.uint8)
        own_grown = cv2.dilate(own.astype(np.uint8), k).astype(bool)
        crowded = bool((occ[Y0:Y1, X0:X1] & own_grown & ~own).any())
        blank = occ_grown[Y0:Y1, X0:X1] & ~own_grown
        if blank.any():
            TL = TL.copy()
            TL[blank] = 1.0
    r = None if crowded else blur.measure(TL, cx - X0, cy - Y0, d_px, calib["tau"], droplet_core, UM_PER_PX,
                                          nearest=others is None)
    chi, size, method = float("nan"), float("nan"), "crowded" if crowded else "border"
    if r is not None:
        chi, base = float(r["chi_um"]), float(r.get(calib["column"], float("nan")))
        if not (np.isfinite(chi) and np.isfinite(base)):
            method = "no_chi"
        else:
            sz, mt = blur.size_3([base - calib["edge_offset_um"]], [chi], calib["table"], calib["chi_sharp_um"],
                                 calib["chi_max_um"])
            size, method = float(sz[0]), str(mt[0])
    in_volume = method in IN_VOLUME
    sized = in_volume and bool(np.isfinite(size)) and size >= calib["d_min_um"]
    if in_volume and not sized:
        method = "below_d_min"
    area = math.pi * (size / 2.0 / UM_PER_PX) ** 2 if sized else float(d["area"])
    out = {"in_focus": sized, "area_px": area, "method": method, "core_t": core_t, "reclassified": False,
           "chi_um": chi, "size_um": size if sized else float("nan"), "in_volume": in_volume,
           "weight": blur.border_weight(d_px, T.shape) if in_volume else 0.0}
    if want_mask:
        # the atomised numerator's droplet edge: the half-max component of a sized droplet, as 2.x uses for its
        # in-focus ones (no size split now); anything else falls back to the model's mask
        half = None
        if sized:
            a_half, _deg, comp = halfmax_area(T_pad, m_pad, core_t)
            half = comp if a_half >= 4 else None
        out["mask"] = half
        out["mask_xy"] = (x0, y0)
    return out


def union_area(rles):
    """Union, not sum. One long filament is emitted as several overlapping
    sub-segments; summing double-counts the overlap (measured: filament 20.5%,
    blob 10.6%, droplet 0%)."""
    return float(mask_util.area(mask_util.merge(rles))) if rles else 0.0


def transmission(sb_dir, stem, bg):
    """T = 16-bit frame / background, or None when the frame is missing."""
    raw = cv2.imread(str(Path(sb_dir) / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
    return None if raw is None else raw.astype(np.float32) / np.maximum(bg, 1.0)


def measure_frame(T, dets, focus_max, split_um=SPLIT_UM, core_estimator="robust",
                  sizer=True, sharpness_rule=False, keep_drawn=False, version=None):
    """Every kept detection of ONE frame: droplets focus-split and sized, liquid
    unioned per class. The body of main()'s per-frame loop, lifted out so
    render_more_extremes.py re-measures a frame with exactly this code.

    Returns a dict:
        focus_a / oof_a    sized droplet areas (px), in / out of focus
        fil_a / blob_a     model areas (px) of each filament / blob instance
        a_drop / a_fil / a_blob   per-class union areas (px)
        atom (%), d32 (um, in-focus only)
        methods (Counter of diameter methods), reclassified (int)
        drawn              render_frame items; empty unless keep_drawn
        sizer 3.0.0 only:  rows3 (one (area_px, in_focus, chi_um, in_volume, method, weight) per droplet, for
                           droplet_sizes.csv), in_volume / unsized / border / crowded / outside / no_chi (counts),
                           w_volume / w_sized / w_unsized (border-weighted counts, for the concentration)
    """
    version = version or sizer_version(sharpness_rule)
    calib = sizer3_settings() if version == SIZER_VERSION_3 else None
    others = occupancy(T.shape, dets) if calib is not None else None
    rows3 = []
    n_volume = n_unsized = n_border = n_crowded = n_outside = n_nochi = 0
    w_volume = w_sized = w_unsized = 0.0
    focus_a, oof_a = [], []
    fil_a, blob_a = [], []
    rle_drop, rle_fil, rle_blob = [], [], []
    drawn = []
    methods = Counter()
    n_reclassified = 0
    for d in dets:
        mb, bx, by, bh, bw = det_crop(d)
        if not mb.any():
            continue
        cid = d["category_id"]
        if cid == DROPLET:
            md = measure_droplet(T, d, focus_max, split_um=split_um,
                                 core_estimator=core_estimator, sizer=sizer,
                                 crop=(mb, bx, by, bh, bw),
                                 sharpness_rule=sharpness_rule, version=version, calib=calib, others=others)
            if md is None:
                continue
            sharp = md["in_focus"]
            if calib is not None:
                rows3.append((md["area_px"], sharp, md["chi_um"], md["in_volume"], md["method"], md["weight"]))
                n_volume += md["in_volume"]
                n_unsized += md["in_volume"] and not sharp
                n_border += md["method"] == "border"
                n_crowded += md["method"] == "crowded"
                n_outside += md["method"] == "outside"
                n_nochi += md["method"] == "no_chi"
                w_volume += md["weight"]
                w_sized += md["weight"] if sharp else 0.0
                w_unsized += md["weight"] if md["in_volume"] and not sharp else 0.0
            n_reclassified += md["reclassified"]
            # the SIZED area, not the model's, when the sizer ran
            (focus_a if sharp else oof_a).append(md["area_px"])
            methods[md["method"]] += 1
            # rle_drop is unconditional: an out-of-focus droplet is still
            # atomised liquid, so the atomised fraction never sees focus.
            rle_drop.append(d["segmentation"])
            colour = GREEN if sharp else MAGENTA
        elif cid == FILAMENT:
            rle_fil.append(d["segmentation"])
            fil_a.append(d["area"])
            colour = ORANGE
        else:
            rle_blob.append(d["segmentation"])
            blob_a.append(d["area"])
            colour = BLUE
        # Crop only; render_frame builds the frame-sized mask if it draws.
        if keep_drawn:
            drawn.append((d, mb, bx, by, bh, bw, colour))

    a_drop = union_area(rle_drop)
    a_fil = union_area(rle_fil)
    a_blob = union_area(rle_blob)
    total = a_drop + a_fil + a_blob
    return {"focus_a": focus_a, "oof_a": oof_a, "fil_a": fil_a, "blob_a": blob_a,
            "a_drop": a_drop, "a_fil": a_fil, "a_blob": a_blob,
            "atom": (a_drop / total * 100) if total else float("nan"),
            "d32": d32(focus_a), "methods": methods,
            "reclassified": n_reclassified, "drawn": drawn,
            "rows3": rows3, "in_volume": n_volume, "unsized": n_unsized, "border": n_border,
            "crowded": n_crowded, "outside": n_outside, "no_chi": n_nochi,
            "w_volume": w_volume, "w_sized": w_sized, "w_unsized": w_unsized}


def boot_ci(values_fn, items, n_boot, seed=0):
    """Percentile bootstrap. Returns (lo, hi) at 95%."""
    if len(items) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    out = []
    n = len(items)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        v = values_fn([items[i] for i in idx])
        if np.isfinite(v):
            out.append(v)
    if not out:
        return float("nan"), float("nan")
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def annotate(canvas, d32_um, atom_pct, scale=1.0):
    """Top-left: D32 and atomised fraction. Nothing else, by request."""
    fs, th = 1.1 * scale, max(2, int(round(2 * scale)))
    lines = [f"D32 {d32_um:.1f} um", f"atomised {atom_pct:.2f} %"]
    pad = int(14 * scale)
    widths = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, fs, th)[0] for t in lines]
    bw = max(w for w, _ in widths) + pad * 2
    lh = int(max(h for _, h in widths) * 1.9)
    bh = pad + lh * len(lines)
    plate = canvas[0:bh, 0:bw].copy()
    canvas[0:bh, 0:bw] = cv2.addWeighted(plate, 0.25,
                                         np.full_like(plate, 255), 0.75, 0)
    y = pad + int(lh * 0.62)
    for t in lines:
        cv2.putText(canvas, t, (pad, y), cv2.FONT_HERSHEY_SIMPLEX, fs, BLACK, th,
                    cv2.LINE_AA)
        y += lh
    return canvas


def ring_contours(mask, bbox, offset, shape):
    """Contours of the mask grown outward, so the outline sits clear of a 3-5 px
    droplet instead of covering the edge you want to judge. Dilation runs on a
    bbox crop -- full-frame morphology per detection is needless work."""
    H, W = shape
    x, y, w_, h_ = [int(v) for v in bbox]
    pad = offset + 2
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w_ + pad), min(H, y + h_ + pad)
    if x1 <= x0 or y1 <= y0:
        return []
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * offset + 1,) * 2)
    sub = cv2.dilate(mask[y0:y1, x0:x1], k)
    cnts, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return [c + np.array([[x0, y0]], dtype=c.dtype) for c in cnts]


def render_frame(view_path, items, f_d32, atom, droplet_ring, out_path):
    """Write one marked-up full-res frame.

    `items` holds (detection, mask_crop, x, y, h, w, colour). The frame-sized
    mask is built here, per detection, only for frames actually being drawn --
    so in extremes mode the other ~270 frames never pay for it.
    """
    view = cv2.imread(str(view_path), cv2.IMREAD_UNCHANGED)
    canvas = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR) if view.ndim == 2 else view.copy()
    for d, mb, bx, by, bh, bw, col in items:
        m = np.zeros(canvas.shape[:2], np.uint8)
        m[by:by + bh, bx:bx + bw] = mb
        if d["category_id"] == DROPLET and droplet_ring > 0:
            cnts = ring_contours(m, d["bbox"], droplet_ring, canvas.shape[:2])
        else:
            cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, cnts, -1, col, 1)
    annotate(canvas, f_d32, atom)
    cv2.imwrite(str(out_path), canvas)


# ============================================================================
# MORE EXTREME FRAMES (2026-10-13)
#
# Beside the D32 / atomised extremes: the frame with the most in-focus
# droplets, the most droplets in total, and the largest / smallest MEAN
# in-focus diameter. Drawn into droplets_<thr>/extreme_frames_more/ with an
# index.json the capture GUI and the Taguchi app read. Chosen here, from the
# per-frame rows, so measure_run and render_more_extremes.py (the back-fill
# for runs measured before this existed) pick the same frames.
# ============================================================================

MORE_EXTREMES_DIR = "extreme_frames_more"
# A frame's mean diameter is only an extreme worth looking at with a sample
# behind it: one speck must not be "the smallest mean". The floor is half the
# run's median in-focus count per frame, never below MIN_DROPLETS_FOR_MEAN
# (Ben, 2026-10-13). With a flat 10, the largest-mean frame was usually a thin
# one that caught a few big drops: on 130918 (median 54 a frame) it was 57.9 um
# from 17 droplets, where a frame's mean swings +/-4 um by chance; at half the
# median it is 55.1 um from 34. The same idea as the D32 extremes' guard.
MIN_DROPLETS_FOR_MEAN = 10
MEAN_FLOOR_SHARE = 0.5
MORE_EXTREMES = (            # key, label, unit -- the GUI reads these as written
    ("most_in_focus", "Most in-focus droplets", "in-focus droplets"),
    ("most_total", "Most droplets in total", "droplets"),
    ("mean_d_highest", "Largest mean diameter", "um mean (in focus)"),
    ("mean_d_lowest", "Smallest mean diameter", "um mean (in focus)"),
)
MORE_INDEX_FIELDS = ("key", "label", "frame", "image", "value", "unit", "droplets_in_focus",
                     "droplets_total", "mean_d_um", "d32_um", "atomised_pct")


def csv_um(area_px):
    """A droplet's diameter exactly as droplet_sizes.csv writes it."""
    return round(float(equiv_um(area_px)), 3)


def frame_mean_d(diameters_um):
    """Mean in-focus diameter of one frame (um) from its droplet_sizes.csv
    diameters; NaN for a frame without one. fsum, so the answer does not
    depend on the order the diameters are read back in."""
    return math.fsum(diameters_um) / len(diameters_um) if len(diameters_um) else float("nan")


def _num(v, nd):
    v = float(v)
    return round(v, nd) if np.isfinite(v) else None


def mean_floor(rows) -> int:
    """In-focus droplets a frame needs for its mean diameter to count as an
    extreme: MEAN_FLOOR_SHARE of the run's median per frame, at least
    MIN_DROPLETS_FOR_MEAN."""
    if not rows:
        return MIN_DROPLETS_FOR_MEAN
    med = float(np.median([int(r["droplets_in_focus"]) for r in rows]))
    return max(MIN_DROPLETS_FOR_MEAN, int(math.ceil(MEAN_FLOOR_SHARE * med)))


def pick_more_extremes(rows, mean_d, floor=None):
    """(frames, note) for the four extra extremes.

    `rows` are per_frame rows in frame order (frame, droplets_in_focus,
    droplets_out_of_focus, d32_in_focus_um, atomised_pct); `mean_d` maps frame
    -> mean in-focus diameter. Ties go to the first frame in frame order
    (max/min keep the first). The two mean entries are left out, and `note`
    says why, when fewer than 2 frames have `floor` in-focus droplets
    (default mean_floor(rows))."""
    if not rows:
        return [], "no frames measured"
    floor = mean_floor(rows) if floor is None else floor
    meta = {k: (label, unit) for k, label, unit in MORE_EXTREMES}

    def entry(key, r, value):
        label, unit = meta[key]
        n_in, n_out = int(r["droplets_in_focus"]), int(r["droplets_out_of_focus"])
        return {"key": key, "label": label, "frame": r["frame"], "image": None,
                "value": value, "unit": unit, "droplets_in_focus": n_in,
                "droplets_total": n_in + n_out,
                "mean_d_um": _num(mean_d.get(r["frame"], float("nan")), 2),
                "d32_um": _num(r["d32_in_focus_um"], 2),
                "atomised_pct": _num(r["atomised_pct"], 3)}

    def total(r):
        return int(r["droplets_in_focus"]) + int(r["droplets_out_of_focus"])

    top_in = max(rows, key=lambda r: int(r["droplets_in_focus"]))
    top_all = max(rows, key=total)
    frames = [entry("most_in_focus", top_in, int(top_in["droplets_in_focus"])),
              entry("most_total", top_all, total(top_all))]
    ok = [r for r in rows if int(r["droplets_in_focus"]) >= floor
          and np.isfinite(mean_d.get(r["frame"], float("nan")))]
    note = ""
    if len(ok) >= 2:
        hi = max(ok, key=lambda r: mean_d[r["frame"]])
        lo = min(ok, key=lambda r: mean_d[r["frame"]])
        frames += [entry("mean_d_highest", hi, _num(mean_d[hi["frame"]], 2)),
                   entry("mean_d_lowest", lo, _num(mean_d[lo["frame"]], 2))]
    else:
        note = (f"mean-diameter extremes left out: {len(ok)} frame(s) have >= "
                f"{floor} in-focus droplets, 2 needed")
    return frames, note


def print_more_extremes(frames, note):
    for e in frames:
        print(f"  {e['label']:26s} {e['frame']:>22}  {e['value']:>7} {e['unit']:<20s}"
              f"  ({e['droplets_in_focus']} in focus of {e['droplets_total']})")
    if note:
        print(f"  ({note})")


def write_more_extremes(out_dir, frames, note, draw=None, floor=MIN_DROPLETS_FOR_MEAN):
    """droplets_<thr>/extreme_frames_more/: one PNG per distinct frame whose
    entry names an image (drawn by `draw(stem, path)`), plus index.json and
    index.csv. Built in a .partial folder and renamed, so a folder that exists
    is complete; a previous one is replaced."""
    final = Path(out_dir) / MORE_EXTREMES_DIR
    part = Path(out_dir) / f"{MORE_EXTREMES_DIR}.partial"
    if part.exists():
        shutil.rmtree(part)
    part.mkdir(parents=True)
    if draw is not None:
        for stem in dict.fromkeys(e["frame"] for e in frames if e["image"]):
            draw(stem, part / f"{stem}.png")
    index = {"schema": 1, "min_droplets_for_mean": floor,
             "note": note, "frames": frames}
    (part / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    with open(part / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MORE_INDEX_FIELDS)
        w.writeheader()
        w.writerows({k: e[k] for k in MORE_INDEX_FIELDS} for e in frames)
    if final.exists():
        shutil.rmtree(final)
    part.rename(final)
    return final


DROPLET_BIN_UM = 25.0

# Matplotlib hex equivalents of the BGR constants above, so a histogram bar
# and the outline drawn on the frame are the same colour.
PLOT_GREEN, PLOT_MAGENTA, PLOT_ORANGE, PLOT_BLUE = "#00c800", "#c800c8", "#ffa500", "#0078ff"


def px_to_mm2(area_px):
    return np.asarray(area_px, dtype=float) * (UM_PER_PX ** 2) / 1e6


def write_distributions(out_dir, per_focus, per_oof, per_fil, per_blob, per_rows3=None):
    """Per-object size distributions: CSVs always, plot only if matplotlib is
    importable.

    The CSVs are the durable artefact. per_frame.csv carries only aggregates,
    so before this existed the individual sizes were recoverable solely by
    re-deriving the focus split from predictions.json plus the 16-bit frames.
    Writing them once means any future histogram, fit or percentile is a read
    rather than a re-measurement.

    Plotting is optional ON PURPOSE: this runs inside the production chain, and
    a missing matplotlib on the lab machine must not cost a 20-minute
    measurement. The data is written first, the figure second.

    Sizer 3.0.0 (`per_rows3`): one row per droplet in measuring order, with three more columns: chi_um, in_volume
    and size_method. in_focus = 1 still means "sized, in D32" (in the volume and >= d_min), so every reader of the
    first three columns reads a 3.0.0 run unchanged.
    """
    stems = sorted(per_focus)

    drop_csv = out_dir / "droplet_sizes.csv"
    with open(drop_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if per_rows3 is not None:
            w.writerow(["frame", "diameter_um", "in_focus", "chi_um", "in_volume", "size_method", "weight"])
            for s in stems:
                for a, inf, chi, vol, meth, wt in per_rows3.get(s, []):
                    w.writerow([s, csv_um(a), int(bool(inf)), round(chi, 3) if np.isfinite(chi) else "",
                                int(bool(vol)), meth, round(wt, 5) if vol else ""])
        else:
            w.writerow(["frame", "diameter_um", "in_focus"])
            for s in stems:
                for a in per_focus.get(s, []):
                    w.writerow([s, csv_um(a), 1])
                for a in per_oof.get(s, []):
                    w.writerow([s, csv_um(a), 0])

    obj_csv = out_dir / "object_areas.csv"
    with open(obj_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "class", "area_px", "area_mm2"])
        for s in stems:
            for a in per_fil.get(s, []):
                w.writerow([s, "filament", round(float(a), 1), round(float(px_to_mm2(a)), 6)])
            for a in per_blob.get(s, []):
                w.writerow([s, "blob", round(float(a), 1), round(float(px_to_mm2(a)), 6)])

    focus_d = equiv_um([a for s in stems for a in per_focus.get(s, [])]) \
        if any(per_focus.values()) else np.array([])
    oof_d = equiv_um([a for s in stems for a in per_oof.get(s, [])]) \
        if any(per_oof.values()) else np.array([])
    fil_mm2 = px_to_mm2([a for s in stems for a in per_fil.get(s, [])]) \
        if any(per_fil.values()) else np.array([])
    blob_mm2 = px_to_mm2([a for s in stems for a in per_blob.get(s, [])]) \
        if any(per_blob.values()) else np.array([])

    return drop_csv, obj_csv, plot_distributions(out_dir, focus_d, oof_d, fil_mm2, blob_mm2,
                                                 sizer3=per_rows3 is not None)


def read_distributions(out_dir):
    """Load the arrays back out of the CSVs, so the figure can be redrawn
    without repeating a 7-minute measurement."""
    focus_d, oof_d = [], []
    with open(out_dir / "droplet_sizes.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            (focus_d if r["in_focus"] == "1" else oof_d).append(float(r["diameter_um"]))
    fil, blob = [], []
    with open(out_dir / "object_areas.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            (fil if r["class"] == "filament" else blob).append(float(r["area_mm2"]))
    return (np.array(focus_d), np.array(oof_d), np.array(fil), np.array(blob))


def plot_distributions(out_dir, focus_d, oof_d, fil_mm2, blob_mm2, sizer3=False):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not installed -- CSVs written, histogram skipped)")
        return None

    fig, axes = plt.subplots(2, 1, figsize=(10, 9))

    # --- droplets: linear 25 um bins -------------------------------------
    ax = axes[0]
    all_d = np.concatenate([d for d in (focus_d, oof_d) if d.size]) \
        if (focus_d.size or oof_d.size) else np.array([])
    if all_d.size:
        top = (np.floor(all_d.max() / DROPLET_BIN_UM) + 1) * DROPLET_BIN_UM
        edges = np.arange(0, top + DROPLET_BIN_UM, DROPLET_BIN_UM)
        ax.hist([focus_d, oof_d], bins=edges, stacked=True,
                color=[PLOT_GREEN, PLOT_MAGENTA],
                label=([f"sized, in the volume (n={focus_d.size:,})",
                        f"not sized: outside the volume or below d_min (n={oof_d.size:,})"] if sizer3 else
                       [f"in focus (n={focus_d.size:,})", f"out of focus (n={oof_d.size:,})"]),
                edgecolor="white", linewidth=0.5)
        ax.set_xticks(edges[::2])
        ax.legend()
    ax.set_title(f"Droplet diameter — {DROPLET_BIN_UM:.0f} µm bins\n"
                 "D32 uses the in-focus population only", fontsize=11)
    ax.set_xlabel("equivalent diameter (µm)")
    ax.set_ylabel("count")

    # --- un-atomised liquid (filament + blob): LOG bins -------------------
    # One panel, both classes. Areas span ~5 orders of magnitude (median
    # ~0.04 mm^2, max ~30), so linear bins would put everything in the first.
    # Stacked rather than merged: total bar height IS the combined
    # distribution, and the split costs nothing to keep.
    ax = axes[1]
    both = np.concatenate([v for v in (fil_mm2, blob_mm2) if v.size]) \
        if (fil_mm2.size or blob_mm2.size) else np.array([])
    if both.size and both.min() > 0 and both.max() > both.min():
        edges = np.logspace(np.log10(both.min()), np.log10(both.max()), 30)
        ax.hist([fil_mm2, blob_mm2], bins=edges, stacked=True,
                color=[PLOT_ORANGE, PLOT_BLUE],
                label=[f"filament (n={fil_mm2.size:,})",
                       f"blob (n={blob_mm2.size:,})"],
                edgecolor="white", linewidth=0.5)
        ax.set_xscale("log")
        ax.legend()
    ax.set_title(f"Un-atomised liquid — filament + blob area, log bins "
                 f"(n={both.size:,})", fontsize=11)
    ax.set_xlabel("area (mm²)")
    ax.set_ylabel("count")

    ax.text(0.5, -0.22,
            "Counts are DETECTED INSTANCES, not whole objects: one long filament is emitted as "
            "several\noverlapping sub-segments. Use the atomised fraction, which unions them, "
            "for area share.",
            transform=ax.transAxes, ha="center", va="top",
            fontsize=8, color="#555555")

    fig.tight_layout()
    png = out_dir / "size_histograms.png"
    fig.savefig(png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return png


def sizer3_provenance(calib: dict) -> dict:
    """What a 3.0.0 run records about the calibration that sized it (compare_runs refuses to mix these)."""
    T = calib["table"]
    return {"optics_profile_hash": calib["hash"],
            "sizer_edge": f"{calib['edge_base']} - {calib['edge_offset_um']:g} um",
            "sizer_chi_sharp_um": calib["chi_sharp_um"], "sizer_chi_max_um": calib["chi_max_um"],
            "sizer_d_min_um": calib["d_min_um"], "sizer_tau": calib["tau"],
            "sizer_table_beads_um": list(T["nodes_um"]), "sizer_calibration_status": calib["status"]}


def concentration(rows, parts, shape, calib: dict) -> dict:
    """Sizer 3.0.0's droplet concentration (sizer 3.0.0 plan, Phase 5; decisions Ben, 2026-10-16):
       * the measurement volume = the frame's area x the calibrated depth at chi_max (the same for every size; the
         lens is telecentric, so the area is the same at every depth);
       * each droplet in the volume counts its border weight (blur.border_weight: near the edge it cannot be
         measured);
       * crowded droplets (touching another detection) are added back in proportion: in the volume as often as
         the droplets that could be judged (in the volume, outside it, or with no chi, which counts as outside);
       * per mm3 = weighted count x the crowded factor / (frames x volume)."""
    n_f = len(rows)
    H, W = shape if shape else (1152, 2048)
    area_mm2 = W * H * (UM_PER_PX / 1000.0) ** 2
    depth = calib.get("depth_mm", float("nan"))
    vol = area_mm2 * depth
    n_in = sum(r["droplets_in_volume"] for r in rows)
    judged = n_in + sum(r["droplets_outside"] + r["droplets_no_chi"] for r in rows)
    crowded = sum(r["droplets_crowded"] for r in rows)
    p_in = n_in / judged if judged else 0.0
    factor = 1.0 + (p_in * crowded / n_in if n_in else 0.0)
    wv, ws, wu = (sum(p[i] for p in parts) for i in range(3))
    per = (lambda w: round(w * factor / (n_f * vol), 6) if n_f and vol > 0 and math.isfinite(vol) else None)
    return {"volume_mm3": round(vol, 2), "frame_mm2": round(area_mm2, 3), "depth_mm": depth, "frames": n_f,
            "crowded": crowded, "crowded_in_volume_share": round(p_in, 4), "crowded_factor": round(factor, 5),
            "in_volume_per_mm3": per(wv), "sized_per_mm3": per(ws), "below_d_min_per_mm3": per(wu),
            "definition": "droplets per mm3 of spray in the measurement volume (frame area x depth at chi_max), "
                          "each weighted for the frame border, crowded ones added back in proportion; a snapshot "
                          "concentration, not a flux (slow droplets are over-represented against what flows "
                          "through); only droplets the AI finds"}


def sizer3_definitions(calib: dict) -> dict:
    T = calib["table"]
    lo, hi = min(T["nodes_um"]), max(T["nodes_um"])
    return {
        "d32": f"droplets in the measurement volume (blur width chi <= {calib['chi_max_um']:g} um, measuring window "
               f"inside the frame) and sized (>= d_min {calib['d_min_um']:g} um); pooled Sum(d^3)/Sum(d^2)",
        "diameter": f"sizer 3.0.0: {calib['edge_base']} size measured around the AI mask as the calibration beads "
                    f"were (blur.py), minus the edge offset {calib['edge_offset_um']:g} um; directly up to chi "
                    f"{calib['chi_sharp_um']:g} um, through the bead look-up table up to {calib['chi_max_um']:g} um "
                    f"(beads {lo:g}-{hi:g} um; beyond them extrapolated, size_method table_extrapolated). Optics "
                    f"profile calibration {calib['hash']}.",
        "core_transmission": "the robust core (mean of the darkest max(3, 5%) interior pixels); 3.0.0 does not "
                             "use it for focus",
        "atomised_pct": "ALL droplet area / (droplet + filament + blob) area, per-class union within a frame, summed "
                        "across frames (unchanged in 3.0.0; Phase 5 restricts it to the measurement volume)",
        "caveat": f"Calibrated on certified glass beads {lo:g}-{hi:g} um (provisional: {calib['status']}). Below "
                  f"{lo:g} um the table is extrapolated down to d_min. Droplets the AI misses are not counted.",
    }


def main():
    global UM_PER_PX, SIZER3
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # Not required=True: --replot needs neither, and argparse cannot express
    # "required unless another flag is set". Checked below instead.
    ap.add_argument("--pred", type=Path, default=None)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--val-dir", default="06_validation")
    ap.add_argument("--background", type=Path, default=None,
                    help="temporal-median background for THIS run. The wrong one "
                         "silently corrupts every transmission value.")
    ap.add_argument("--sixteen-bit-dir", type=Path, default=None,
                    help="default: <val-dir>/frames/16bit")
    ap.add_argument("--score-thresh", type=float, default=0.30)
    ap.add_argument("--split-um", type=float, default=SPLIT_UM,
                    help="classical half-max sizing acts at/above this diameter; "
                         "below it the model's mask area is used unchanged")
    ap.add_argument("--core-estimator", choices=["robust", "min"], default="robust",
                    help="'robust' = mean of the darkest max(3, 5%%) mask pixels; "
                         "'min' = the historical single darkest pixel")
    ap.add_argument("--no-sizer", action="store_true",
                    help="skip classical sizing entirely and use the model's mask "
                         "area, as before SIZER_VERSION 2.0.0")
    ap.add_argument("--focus-max", type=float, default=0.70,
                    help="must match extract_candidates.py")
    ap.add_argument("--sharpness-rule", action=argparse.BooleanOptionalAction, default=None,
                    help="sizer 2.2.0 (DEFAULT since 2026-10-08): reclassify in-focus "
                         "droplets >= 50 um as out of focus when not round (fill_ratio "
                         "< 0.85) or blurred (extinction_conc < 0.60). Moves D32 only. "
                         "--no-sharpness-rule measures at 2.1.0, bit-identical to before")
    ap.add_argument("--sizer", choices=blur.SIZERS, default=None,
                    help="the sizer version. 3.0.0 (the DEFAULT since 2026-10-16, Ben): blur-width focus rule and "
                         "calibrated sizing from the optics profile. --sharpness-rule / --no-sharpness-rule without "
                         "--sizer still mean 2.2.0 / 2.1.0")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="default: <val-dir>/measurement_<thresh>")
    ap.add_argument("--images", nargs="?", const="all", default=None,
                    choices=["all", "extremes"],
                    help="write marked-up full-res images. 'all' (the default when "
                         "the flag is given bare) draws every frame; 'extremes' "
                         "draws only the extreme D32 / atomised frames the GUI "
                         "shows. On the lab PC 'all' is ~80%% of measurement time "
                         "(~0.9 s and 7.5 MB per frame), and any frame can be "
                         "regenerated later from the .cine.")
    ap.add_argument("--replot", action="store_true",
                    help="redraw size_histograms.png from the CSVs already in "
                         "--out-dir and exit. Measures nothing, so changing the "
                         "figure costs seconds instead of a full re-measurement.")
    ap.add_argument("--droplet-ring", type=int, default=DROPLET_RING_PX)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--ci-stride", type=int, default=1, metavar="N",
                    help="use every Nth frame for the CONFIDENCE INTERVAL only. The "
                         "point estimate always uses every frame. Set this to one "
                         "decorrelation time in frames when the capture is "
                         "CONSECUTIVE -- 10 at 500 fps, 26 at 1300 fps (~20 ms). "
                         "Default 1, correct only when the frames are already "
                         ">=1 decorrelation time apart.")
    args = ap.parse_args()

    t_start = time.time()
    root = args.root or real_data_root()
    profile = optics.profile_for(root)                 # the optics this run was captured with
    UM_PER_PX = float(profile["um_per_px"])
    version = sizer_version(args.sharpness_rule, args.sizer)
    calib3 = None
    if version == SIZER_VERSION_3:
        if args.no_sizer:
            sys.exit("--no-sizer and --sizer 3.0.0 contradict each other: 3.0.0 always sizes")
        try:
            calib3 = SIZER3 = blur.sizer3(profile)     # the run's own profile's calibration, never another's
        except blur.CalibrationMissing as e:
            sys.exit(str(e))
    val = root / args.val_dir
    sb_dir = args.sixteen_bit_dir or (val / "frames" / "16bit")
    out_dir = args.out_dir or (val / f"droplets_{args.score_thresh:.2f}")
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.replot:
        png = plot_distributions(out_dir, *read_distributions(out_dir))
        print(f"replotted: {png}" if png else "matplotlib missing -- nothing drawn")
        return

    missing = [f for f, v in (("--pred", args.pred), ("--background", args.background))
               if v is None]
    if missing:
        sys.exit(f"{' and '.join(missing)} required (omit only with --replot)")

    manifest = json.loads((val / "instances.json").read_text(encoding="utf-8"))
    name_by_id = {im["id"]: Path(im["file_name"]).stem for im in manifest["images"]}

    bg = cv2.imread(str(args.background), cv2.IMREAD_UNCHANGED)
    if bg is None:
        sys.exit(f"could not read background: {args.background}")
    bg = bg.astype(np.float32)

    preds = json.loads(args.pred.read_text(encoding="utf-8"))
    stray = {d["image_id"] for d in preds} - set(name_by_id)
    if stray:
        sys.exit(f"{len(stray)} prediction image_id(s) absent from the manifest -- "
                 f"these predictions were made against a different frame set.")

    kept = [d for d in preds
            if d["score"] >= args.score_thresh and not d.get("truncated", False)]
    by_img = defaultdict(list)
    for d in kept:
        by_img[d["image_id"]].append(d)

    print(f"frames {len(name_by_id)}   detections >= {args.score_thresh:.2f}, "
          f"not truncated: {len(kept)} of {len(preds)}\n")

    rows = []
    methods = Counter()          # how each in-focus diameter was actually obtained
    n_reclassified = 0           # moved out of focus by the sharpness rule (2.2.0)
    per_frame_focus_areas = {}   # for the run-level bootstrap over frames
    per_frame_atom_parts = {}
    per_frame_oof_areas = {}     # size distributions only, never D32
    per_frame_fil_areas = {}
    per_frame_blob_areas = {}
    all_focus_areas = []
    per_frame_mean_d = {}        # mean in-focus diameter, for the more-extremes pick
    per_frame_rows3 = {} if calib3 is not None else None      # sizer 3.0.0: every droplet's chi and method
    conc_parts = []                                             # sizer 3.0.0: border-weighted counts per frame
    frame_shape = None
    # extremes mode: which frames to draw is only known once every frame is
    # measured, so hold each frame's crops (small) and draw afterwards.
    pending_images = {}

    for img_id in sorted(by_img):
        stem = name_by_id[img_id]
        dets = by_img[img_id]
        T = transmission(sb_dir, stem, bg)
        if T is None:
            sys.exit(f"no 16-bit frame for {stem} under {sb_dir}")
        frame_shape = T.shape

        fr = measure_frame(T, dets, args.focus_max, split_um=args.split_um,
                           core_estimator=args.core_estimator, sizer=not args.no_sizer,
                           sharpness_rule=args.sharpness_rule, keep_drawn=bool(args.images),
                           version=version)
        focus_a, oof_a, fil_a, blob_a = fr["focus_a"], fr["oof_a"], fr["fil_a"], fr["blob_a"]
        a_drop, a_fil, a_blob = fr["a_drop"], fr["a_fil"], fr["a_blob"]
        atom, f_d32, drawn = fr["atom"], fr["d32"], fr["drawn"]
        methods.update(fr["methods"])
        n_reclassified += fr["reclassified"]
        mean_d = frame_mean_d([csv_um(a) for a in focus_a])
        per_frame_mean_d[stem] = mean_d

        lo, hi = boot_ci(d32, focus_a, args.n_boot)
        rows.append({
            "frame": stem,
            "droplets_in_focus": len(focus_a),
            "droplets_out_of_focus": len(oof_a),
            "filaments": len(fil_a),
            "blobs": len(blob_a),
            "d32_in_focus_um": round(f_d32, 2),
            "d32_ci_lo": round(lo, 2), "d32_ci_hi": round(hi, 2),
            "atomised_pct": round(atom, 3),
            "droplet_area_px": round(a_drop, 1),
            "filament_area_px": round(a_fil, 1),
            "blob_area_px": round(a_blob, 1),
            # Appended LAST so a reader by position is unaffected (none reads by
            # position; checked 2026-10-13). From droplet_sizes.csv's diameters.
            "mean_d_in_focus_um": round(mean_d, 2),
        })
        if calib3 is not None:
            # sizer 3.0.0, appended after everything else: in the volume (sized or not), counted but below d_min,
            # too near the frame edge to measure, touching another detection
            rows[-1].update(droplets_in_volume=fr["in_volume"], droplets_unsized_in_volume=fr["unsized"],
                            droplets_border=fr["border"], droplets_crowded=fr["crowded"],
                            droplets_outside=fr["outside"], droplets_no_chi=fr["no_chi"],
                            weighted_in_volume=round(fr["w_volume"], 3), weighted_sized=round(fr["w_sized"], 3))
            conc_parts.append((fr["w_volume"], fr["w_sized"], fr["w_unsized"]))
            per_frame_rows3[stem] = fr["rows3"]
        per_frame_focus_areas[stem] = focus_a
        per_frame_atom_parts[stem] = (a_drop, a_fil, a_blob)
        per_frame_oof_areas[stem] = oof_a
        per_frame_fil_areas[stem] = fil_a
        per_frame_blob_areas[stem] = blob_a
        all_focus_areas.extend(focus_a)

        if args.images == "all":
            render_frame(val / "frames" / "8bit" / f"{stem}.png", drawn,
                         f_d32, atom, args.droplet_ring, out_dir / f"{stem}.png")
        elif args.images == "extremes":
            pending_images[stem] = (drawn, f_d32, atom)

        print(f"  {stem:>24}  focus {len(focus_a):4d}  oof {len(oof_a):4d}  "
              f"fil {len(fil_a):3d}  blob {len(blob_a):2d}   "
              f"D32 {f_d32:6.1f}   atom {atom:6.2f}%")

    # ---- pooled over the run ----
    pooled_d32 = d32(all_focus_areas)
    # Size distribution of every in-focus droplet in the run, pooled.
    all_focus_d = equiv_um(all_focus_areas) if all_focus_areas else np.array([])
    d_mean = float(all_focus_d.mean()) if len(all_focus_d) else float("nan")
    d_std = float(all_focus_d.std(ddof=1)) if len(all_focus_d) > 1 else float("nan")
    d_min = float(all_focus_d.min()) if len(all_focus_d) else float("nan")
    d_max = float(all_focus_d.max()) if len(all_focus_d) else float("nan")
    tot_d = sum(v[0] for v in per_frame_atom_parts.values())
    tot_f = sum(v[1] for v in per_frame_atom_parts.values())
    tot_b = sum(v[2] for v in per_frame_atom_parts.values())
    pooled_atom = tot_d / (tot_d + tot_f + tot_b) * 100 if (tot_d + tot_f + tot_b) else float("nan")

    # Bootstrap over per-frame (Sum d^3, Sum d^2) pairs, not over pooled droplet
    # lists. D32 = Sum(d^3)/Sum(d^2), so the pair is a sufficient statistic per
    # frame and the pooled value is just the ratio of the summed pairs --
    # mathematically identical, and it turns each resample from "concatenate
    # 240,000 areas" into "add up N pairs". At 1,000 frames the naive version
    # does ~500M operations per run; this does ~2M.
    stems = sorted(per_frame_focus_areas)
    _pairs = {}
    for s in stems:
        d = equiv_um(per_frame_focus_areas[s]) if per_frame_focus_areas[s] else np.array([])
        _pairs[s] = ((d ** 3).sum(), (d ** 2).sum()) if d.size else (0.0, 0.0)

    def _d32_of(ss):
        num = sum(_pairs[s][0] for s in ss)
        den = sum(_pairs[s][1] for s in ss)
        return num / den if den else float("nan")

    # POINT ESTIMATE uses every frame; the CI uses a strided subsample.
    #
    # Consecutive frames are not independent -- liquid crosses the field of view
    # in ~20 ms, so at 500 fps frames less than ~10 apart share physical
    # droplets. Bootstrapping them as if independent reports the precision of a
    # sample you do not have: duplicating 20 frames 10x (zero new information)
    # narrows the interval 3.2x. Too-narrow intervals make compare_runs.py
    # declare differences real that are not, which is the dangerous direction.
    #
    # Striding for the CI throws away real precision -- an interval from every
    # 10th frame is wider than a correct block bootstrap over all of them --
    # but it is honest, and it is wrong in the safe direction.
    ci_stems = stems[::max(1, args.ci_stride)]
    if len(ci_stems) < 2:
        print(f"\n  WARNING: --ci-stride {args.ci_stride} leaves {len(ci_stems)} "
              f"frame(s); no interval can be computed. Lower it.")
    d_lo, d_hi = boot_ci(_d32_of, ci_stems, args.n_boot)

    def atom_of(ss):
        d = sum(per_frame_atom_parts[s][0] for s in ss)
        f = sum(per_frame_atom_parts[s][1] for s in ss)
        b = sum(per_frame_atom_parts[s][2] for s in ss)
        return d / (d + f + b) * 100 if (d + f + b) else float("nan")

    a_lo, a_hi = boot_ci(atom_of, ci_stems, args.n_boot)

    n_focus = sum(r["droplets_in_focus"] for r in rows)
    n_oof = sum(r["droplets_out_of_focus"] for r in rows)
    elapsed = time.time() - t_start

    print("\n" + "=" * 74)
    print("RUN MEASUREMENT  (pooled -- never an average of per-frame values)")
    print("=" * 74)
    print(f"  frames                    : {len(rows)}")
    print(f"  droplets IN FOCUS  (green): {n_focus}")
    print(f"  droplets out of focus     : {n_oof}"
          f"   ({100 * n_oof / max(1, n_focus + n_oof):.1f}% of all droplets)")
    if calib3 is not None:
        print(f"  sizer 3.0.0: in the volume {sum(r['droplets_in_volume'] for r in rows)} (chi <= "
              f"{calib3['chi_max_um']:g} um), of which below d_min {calib3['d_min_um']:g} um (counted, not sized) "
              f"{sum(r['droplets_unsized_in_volume'] for r in rows)}; too near the frame edge "
              f"{sum(r['droplets_border'] for r in rows)}; touching another detection "
              f"{sum(r['droplets_crowded'] for r in rows)}")
    print()
    print(f"  D32 (in-focus only)       : {pooled_d32:.1f} um"
          f"   95% CI [{d_lo:.1f}, {d_hi:.1f}]   +/-{(d_hi - d_lo) / 2:.1f}"
          f" ({100 * (d_hi - d_lo) / 2 / pooled_d32:.1f}%)")
    print(f"  atomised fraction (all)   : {pooled_atom:.2f} %"
          f"   95% CI [{a_lo:.2f}, {a_hi:.2f}]   +/-{(a_hi - a_lo) / 2:.2f}"
          f" ({100 * (a_hi - a_lo) / 2 / pooled_atom:.1f}%)")
    print()
    # The SIZE DISTRIBUTION of the in-focus droplets. Distinct from the CI
    # above: the CI says how well D32 is known, this says how varied the
    # droplets themselves are. D32 is a ratio of moments (sum d^3 / sum d^2)
    # and deliberately weights large droplets, so it sits well above the mean
    # -- do not read the spread below as an error bar on it.
    if len(all_focus_d):
        print(f"  droplet diameters         : mean {d_mean:.1f} um"
              f"   SD {d_std:.1f} um"
              f"   min {d_min:.1f}   max {d_max:.1f}")
        print(f"                              (n={len(all_focus_d)} in focus;"
              f" min/max are single detections -- the smallest sits on the"
              f" model's noise floor)")
        print()
    print(f"  Two runs are distinguishable only if they differ by more than")
    print(f"  ~{1.4 * (d_hi - d_lo) / 2:.1f} um D32 / ~{1.4 * (a_hi - a_lo) / 2:.2f} pp atomised.")
    print()
    print(f"  point estimates use all {len(rows)} frames.")
    if args.ci_stride > 1:
        print(f"  CIs use every {args.ci_stride}th frame ({len(ci_stems)} of "
              f"{len(rows)}), so the bootstrap sees independent samples.")
        print("  That interval is honestly wide rather than falsely tight; a block")
        print("  bootstrap over all frames would be tighter and equally valid.")
    else:
        print("  CIs use ALL frames (--ci-stride 1). That is correct ONLY if these")
        print("  frames are already >=1 decorrelation time apart (~20 ms; every")
        print("  10th frame at 500 fps). For a CONSECUTIVE capture this interval")
        print("  is roughly 3x too narrow -- pass --ci-stride 10.")

    # Atomised-fraction extremes, sorted RAW. `filaments` is the field that
    # explains a degenerate reading: zero filaments makes the ratio 1 by
    # construction, which is why a 100% frame is usually an artifact rather
    # than perfect atomisation.
    by_atom = sorted(rows, key=lambda r: r["atomised_pct"])

    def _atom_extreme(r):
        return {
            "frame": r["frame"],
            "atomised_pct": r["atomised_pct"],
            "droplets": r["droplets_in_focus"] + r["droplets_out_of_focus"],
            "filaments": r["filaments"],
        }

    # ---- extreme frames ----
    # A frame with a handful of droplets has a meaningless per-frame D32 (one
    # or two large detections can swing it wildly), so the raw extremes are
    # reported alongside the extremes among frames with a REASONABLE sample --
    # if they differ, the raw one is a sparse-frame artifact, not genuinely
    # fine/coarse spray. Ported from run_stats.py 2026-09-27.
    with_d32 = [r for r in rows if r["droplets_in_focus"] > 0]
    if len(with_d32) >= 2:
        by_d32 = sorted(with_d32, key=lambda r: r["d32_in_focus_um"])
        med_n = np.median([r["droplets_in_focus"] for r in with_d32])
        floor = max(50, int(med_n * 0.5))
        solid = [r for r in by_d32 if r["droplets_in_focus"] >= floor]

        print("\n" + "=" * 74)
        print("EXTREME FRAMES -- go and look at these")
        print("=" * 74)

        def _show(tag, r):
            print(f"  {tag:26s} {r['frame']:>22}  D32 {r['d32_in_focus_um']:7.1f} um"
                  f"   {r['droplets_in_focus']:4d} in-focus droplets"
                  f"   atomised {r['atomised_pct']:6.2f}%")

        _show("LOWEST D32 (finest)", by_d32[0])
        _show("HIGHEST D32 (coarsest)", by_d32[-1])
        if solid and (solid[0]["frame"] != by_d32[0]["frame"]
                      or solid[-1]["frame"] != by_d32[-1]["frame"]):
            print(f"\n  among frames with >= {floor} in-focus droplets only:")
            _show("LOWEST D32", solid[0])
            _show("HIGHEST D32", solid[-1])
            print("  (differs from the raw extremes above -> those were sparse-frame"
                  "\n   artifacts, not genuinely fine/coarse spray)")
        else:
            print(f"\n  (unchanged when restricted to frames with >= {floor} "
                  f"in-focus droplets,\n   so these are real, not sparse-frame artifacts)")
        ratio = by_d32[-1]["d32_in_focus_um"] / by_d32[0]["d32_in_focus_um"] \
            if by_d32[0]["d32_in_focus_um"] else float("nan")
        print(f"\n  ratio highest/lowest: {ratio:.2f}x -- the frame-to-frame swing"
              f"\n  the pooled number is averaging over.")

    # The four more extremes (most in-focus, most in total, largest / smallest
    # mean diameter), chosen by the function render_more_extremes.py shares.
    more_floor = mean_floor(rows)
    more, more_note = pick_more_extremes(rows, per_frame_mean_d, more_floor)
    for e in more:
        e["image"] = f"{e['frame']}.png" if args.images else None
    if len(with_d32) < 2:
        print("\n" + "=" * 74)
        print("EXTREME FRAMES -- go and look at these")
        print("=" * 74)
    print(f"\n  more extremes ({MORE_EXTREMES_DIR}/):")
    print_more_extremes(more, more_note)

    csv_path = out_dir / "per_frame.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "measured_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(elapsed, 1),
        "provenance": {
            "predictions": str(args.pred),
            "val_dir": args.val_dir,
            "background": str(args.background),
            "sixteen_bit_dir": str(sb_dir),
            "score_threshold": args.score_thresh,
            "focus_max": args.focus_max,
            "um_per_px": UM_PER_PX,
            "optics_profile": profile["name"],
            # SIZING METHOD -- compare_runs.py guards on these. A run measured
            # with a different sizer_version is NOT comparable with one measured
            # before it, and without this field that difference is invisible.
            "sizer_version": version,
            "sizer_enabled": not args.no_sizer,
            "sharpness_rule": args.sharpness_rule,
            "sharpness_reclassified": n_reclassified,
            "split_um": args.split_um,
            "core_estimator": args.core_estimator,
            "diameter_method_counts": dict(methods),
            "ci_stride": args.ci_stride,
            "frames_used_for_ci": len(ci_stems),
            "ci_assumes_independence": args.ci_stride == 1,
            **(sizer3_provenance(calib3) if calib3 is not None else {}),
        },
        "definitions": sizer3_definitions(calib3) if calib3 is not None else {
            "d32": "in-focus droplets only (core transmission <= focus_max); "
                   "pooled Sum(d^3)/Sum(d^2)",
            "diameter": "classical half-max area at/above split_um, (core+1)/2 grown "
                        "inside a 5 px dilated search region; the model's mask area "
                        "below it. `diameter_method_counts` says which applied. "
                        "'model_degenerate' = the half-max component equalled the "
                        "mask, so the droplet is counted and sized but its diameter "
                        "is not an independent measurement.",
            "core_transmission": "mean of the darkest max(3, 5%) mask pixels "
                                 "('robust'), or the single darkest pixel ('min'). "
                                 "The single-pixel minimum is biased dark by noise, "
                                 "which reads diameters ~2% small and makes the "
                                 "focus gate permissive.",
            "atomised_pct": "ALL droplet area / (droplet + filament + blob) area, "
                            "per-class union within a frame, summed across frames",
            "caveat": "D32 is 'D32 of confidently-sized droplets', not the spray's "
                      "true D32 -- small in-focus droplets are under-detected "
                      "(~75% recall at 0-50 um), which inflates it. Valid for "
                      "RANKING runs measured identically; never quote as absolute.",
        },
        "frames": len(rows),
        "droplets_in_focus": n_focus,
        "droplets_out_of_focus": n_oof,
        "d32_in_focus_um": round(pooled_d32, 2),
        # Size distribution, NOT a precision statement -- see the note by the
        # printout. Mean sits below D32 because D32 weights large droplets.
        "droplet_d_mean_um": None if np.isnan(d_mean) else round(d_mean, 2),
        "droplet_d_std_um": None if np.isnan(d_std) else round(d_std, 2),
        "droplet_d_min_um": None if np.isnan(d_min) else round(d_min, 2),
        "droplet_d_max_um": None if np.isnan(d_max) else round(d_max, 2),
        "d32_ci95": [round(d_lo, 2), round(d_hi, 2)],
        "atomised_pct": round(pooled_atom, 3),
        "atomised_ci95": [round(a_lo, 3), round(a_hi, 3)],
        "d32_extreme_frames": ({
            "lowest": {"frame": by_d32[0]["frame"],
                      "d32_um": by_d32[0]["d32_in_focus_um"],
                      "droplets_in_focus": by_d32[0]["droplets_in_focus"]},
            "highest": {"frame": by_d32[-1]["frame"],
                       "d32_um": by_d32[-1]["d32_in_focus_um"],
                       "droplets_in_focus": by_d32[-1]["droplets_in_focus"]},
            "ratio": round(by_d32[-1]["d32_in_focus_um"] / by_d32[0]["d32_in_focus_um"], 3)
                if by_d32[0]["d32_in_focus_um"] else None,
        } if len(with_d32) >= 2 else None),
        # Deliberately RAW, with no sparse-frame guard. The atomised fraction
        # is a ratio with an intermittent denominator, so its extremes are
        # frequently degenerate -- a frame with zero filaments reads 100% by
        # construction. Those frames are the interesting ones: they show where
        # and why the measure fails. `droplets`/`filaments` travel with each
        # entry so a degenerate frame is recognisable on sight rather than
        # being mistaken for a real result.
        "atomised_extreme_frames": ({
            "lowest": _atom_extreme(by_atom[0]),
            "highest": _atom_extreme(by_atom[-1]),
        } if len(by_atom) >= 2 else None),
        # Most in-focus / most in total / largest and smallest mean diameter;
        # the same list as extreme_frames_more/index.json's "frames".
        "more_extreme_frames": more,
    }
    if calib3 is not None:
        summary["concentration"] = concentration(rows, conc_parts, frame_shape, calib3)
        summary.update(droplets_in_volume=sum(r["droplets_in_volume"] for r in rows),
                       droplets_unsized_in_volume=sum(r["droplets_unsized_in_volume"] for r in rows),
                       droplets_border=sum(r["droplets_border"] for r in rows),
                       droplets_crowded=sum(r["droplets_crowded"] for r in rows))
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # The four frames the GUI's Extremes tab shows (raw D32 low/high, atomised
    # low/high), plus the sparse-frame-guarded D32 extremes when they differ --
    # those are the ones worth looking at when the raw ones are artifacts.
    n_images = len(rows) if args.images == "all" else 0
    if args.images == "extremes":
        want = []
        if len(with_d32) >= 2:
            want += [by_d32[0]["frame"], by_d32[-1]["frame"]]
            if solid:
                want += [solid[0]["frame"], solid[-1]["frame"]]
        if len(by_atom) >= 2:
            want += [by_atom[0]["frame"], by_atom[-1]["frame"]]
        for stem in dict.fromkeys(want):          # de-duplicate, keep order
            drawn, f_d32, atom = pending_images[stem]
            render_frame(val / "frames" / "8bit" / f"{stem}.png", drawn,
                         f_d32, atom, args.droplet_ring, out_dir / f"{stem}.png")
            n_images += 1

    # extreme_frames_more/ whatever the image mode: index.json always, PNGs
    # when images are drawn. 'all' has drawn every frame flat already, so its
    # PNGs are copies; 'extremes' draws them from the held crops.
    def _draw_more(stem, path):
        if args.images == "all":
            shutil.copyfile(out_dir / f"{stem}.png", path)
            return
        drawn, f_d32, atom = pending_images[stem]
        render_frame(val / "frames" / "8bit" / f"{stem}.png", drawn,
                     f_d32, atom, args.droplet_ring, path)

    more_dir = write_more_extremes(out_dir, more, more_note,
                                   _draw_more if args.images else None, more_floor)

    if calib3 is not None and summary["concentration"]["in_volume_per_mm3"] is not None:
        c = summary["concentration"]
        print(f"  concentration (sizer 3.0.0): {c['in_volume_per_mm3']:.4f} droplets per mm3 in the volume "
              f"({c['sized_per_mm3']:.4f} sized), volume {c['volume_mm3']} mm3 a frame, crowded factor "
              f"{c['crowded_factor']}")
    drop_csv, obj_csv, png = write_distributions(
        out_dir, per_frame_focus_areas, per_frame_oof_areas,
        per_frame_fil_areas, per_frame_blob_areas, per_frame_rows3)

    print(f"\n  elapsed {elapsed:.1f} s")
    print(f"  written: {csv_path}")
    print(f"           {out_dir / 'summary.json'}")
    print(f"           {drop_csv.name}  (every droplet, one row each)")
    print(f"           {obj_csv.name}  (every filament/blob instance)")
    if png:
        print(f"           {png.name}")
    if args.images:
        print(f"           {n_images} images ({args.images}) in {out_dir}")
    print(f"           {more_dir.name}/  ({len({e['frame'] for e in more if e['image']})} "
          f"images + index.json)")


if __name__ == "__main__":
    main()
