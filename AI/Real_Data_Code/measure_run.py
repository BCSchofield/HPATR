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

import argparse
import csv
import json
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

UM_PER_PX = 10.0
DROPLET, FILAMENT, BLOB = 1, 2, 3

# BGR. Must match preview_predictions.py so the two tools never disagree.
GREEN = (0, 200, 0)
MAGENTA = (200, 0, 200)
ORANGE = (0, 165, 255)
BLUE = (255, 120, 0)
BLACK = (0, 0, 0)


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

SIZER_VERSION = "2.0.0"      # bump on ANY change to the three functions below
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

    Returns (area_px, degenerate). `degenerate` means the half-max component
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
        return 0, False
    area = int((lab == comp_id).sum())
    return area, area == int(mask_pad.sum())


def measure_droplet(T, d, focus_max, split_um=SPLIT_UM, core_estimator="robust",
                    sizer=True, crop=None):
    """Focus verdict and sized area for ONE droplet detection.

    Returns None for an empty mask, else a dict:
        in_focus  bool   -- drives D32 membership AND the green/magenta colour
        area_px   float  -- what D32 is built from
        method    str    -- halfmax | model_degenerate | model_below_split
                            | model_out_of_focus | model_no_sizer
        core_t    float

    NOTHING IS EVER DROPPED HERE. An out-of-focus droplet keeps its area and
    still counts toward the atomised fraction; only its SIZE is withheld from
    D32. The sizer changes a number, never membership.
    """
    mb, bx, by, bh, bw = crop if crop is not None else det_crop(d)
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
    if not sizer:
        pass
    elif not in_focus:
        method = "model_out_of_focus"
    elif equiv_um(area) < split_um:
        method = "model_below_split"
    else:
        a_half, degenerate = halfmax_area(T_pad, m_pad, core_t)
        if a_half >= 4:
            area = float(a_half)
            method = "model_degenerate" if degenerate else "halfmax"
        else:
            method = "model_no_component"
    return {"in_focus": in_focus, "area_px": area, "method": method,
            "core_t": core_t}


def union_area(rles):
    """Union, not sum. One long filament is emitted as several overlapping
    sub-segments; summing double-counts the overlap (measured: filament 20.5%,
    blob 10.6%, droplet 0%)."""
    return float(mask_util.area(mask_util.merge(rles))) if rles else 0.0


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


DROPLET_BIN_UM = 25.0

# Matplotlib hex equivalents of the BGR constants above, so a histogram bar
# and the outline drawn on the frame are the same colour.
PLOT_GREEN, PLOT_MAGENTA, PLOT_ORANGE, PLOT_BLUE = "#00c800", "#c800c8", "#ffa500", "#0078ff"


def px_to_mm2(area_px):
    return np.asarray(area_px, dtype=float) * (UM_PER_PX ** 2) / 1e6


def write_distributions(out_dir, per_focus, per_oof, per_fil, per_blob):
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
    """
    stems = sorted(per_focus)

    drop_csv = out_dir / "droplet_sizes.csv"
    with open(drop_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "diameter_um", "in_focus"])
        for s in stems:
            for a in per_focus.get(s, []):
                w.writerow([s, round(float(equiv_um(a)), 3), 1])
            for a in per_oof.get(s, []):
                w.writerow([s, round(float(equiv_um(a)), 3), 0])

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

    return drop_csv, obj_csv, plot_distributions(out_dir, focus_d, oof_d,
                                                 fil_mm2, blob_mm2)


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


def plot_distributions(out_dir, focus_d, oof_d, fil_mm2, blob_mm2):
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
                label=[f"in focus (n={focus_d.size:,})",
                       f"out of focus (n={oof_d.size:,})"],
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


def main():
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
    ap.add_argument("--droplet-ring", type=int, default=10)
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
    val = root / args.val_dir
    sb_dir = args.sixteen_bit_dir or (val / "frames" / "16bit")
    out_dir = args.out_dir or (val / f"measurement_{args.score_thresh:.2f}")
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
    per_frame_focus_areas = {}   # for the run-level bootstrap over frames
    per_frame_atom_parts = {}
    per_frame_oof_areas = {}     # size distributions only, never D32
    per_frame_fil_areas = {}
    per_frame_blob_areas = {}
    all_focus_areas = []
    # extremes mode: which frames to draw is only known once every frame is
    # measured, so hold each frame's crops (small) and draw afterwards.
    pending_images = {}

    for img_id in sorted(by_img):
        stem = name_by_id[img_id]
        dets = by_img[img_id]
        raw = cv2.imread(str(sb_dir / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
        if raw is None:
            sys.exit(f"no 16-bit frame for {stem} under {sb_dir}")
        T = raw.astype(np.float32) / np.maximum(bg, 1.0)

        focus_a, oof_a = [], []
        fil_a, blob_a = [], []
        rle_drop, rle_fil, rle_blob = [], [], []
        drawn = []
        for d in dets:
            mb, bx, by, bh, bw = det_crop(d)
            if not mb.any():
                continue
            cid = d["category_id"]
            if cid == DROPLET:
                md = measure_droplet(T, d, args.focus_max, split_um=args.split_um,
                                     core_estimator=args.core_estimator,
                                     sizer=not args.no_sizer,
                                     crop=(mb, bx, by, bh, bw))
                if md is None:
                    continue
                sharp = md["in_focus"]
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
            if args.images:
                drawn.append((d, mb, bx, by, bh, bw, colour))

        a_drop = union_area(rle_drop)
        a_fil = union_area(rle_fil)
        a_blob = union_area(rle_blob)
        total = a_drop + a_fil + a_blob
        atom = (a_drop / total * 100) if total else float("nan")
        f_d32 = d32(focus_a)

        lo, hi = boot_ci(d32, focus_a, args.n_boot)
        rows.append({
            "frame": stem,
            "droplets_in_focus": len(focus_a),
            "droplets_out_of_focus": len(oof_a),
            "filaments": len(rle_fil),
            "blobs": len(rle_blob),
            "d32_in_focus_um": round(f_d32, 2),
            "d32_ci_lo": round(lo, 2), "d32_ci_hi": round(hi, 2),
            "atomised_pct": round(atom, 3),
            "droplet_area_px": round(a_drop, 1),
            "filament_area_px": round(a_fil, 1),
            "blob_area_px": round(a_blob, 1),
        })
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
              f"fil {len(rle_fil):3d}  blob {len(rle_blob):2d}   "
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
            # SIZING METHOD -- compare_runs.py guards on these. A run measured
            # with a different sizer_version is NOT comparable with one measured
            # before it, and without this field that difference is invisible.
            "sizer_version": SIZER_VERSION,
            "sizer_enabled": not args.no_sizer,
            "split_um": args.split_um,
            "core_estimator": args.core_estimator,
            "diameter_method_counts": dict(methods),
            "ci_stride": args.ci_stride,
            "frames_used_for_ci": len(ci_stems),
            "ci_assumes_independence": args.ci_stride == 1,
        },
        "definitions": {
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
    }
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

    drop_csv, obj_csv, png = write_distributions(
        out_dir, per_frame_focus_areas, per_frame_oof_areas,
        per_frame_fil_areas, per_frame_blob_areas)

    print(f"\n  elapsed {elapsed:.1f} s")
    print(f"  written: {csv_path}")
    print(f"           {out_dir / 'summary.json'}")
    print(f"           {drop_csv.name}  (every droplet, one row each)")
    print(f"           {obj_csv.name}  (every filament/blob instance)")
    if png:
        print(f"           {png.name}")
    if args.images:
        print(f"           {n_images} images ({args.images}) in {out_dir}")


if __name__ == "__main__":
    main()
