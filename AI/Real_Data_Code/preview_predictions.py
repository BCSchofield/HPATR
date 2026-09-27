#!/usr/bin/env python3
"""
preview_predictions.py -- render model predictions at several score thresholds,
colour-coded by whether each detection actually reaches the measurement.

NOT the same as preview_thresholds.py, which tunes the EXTRACTOR (seed/grow/blur
on raw frames). This one draws what a trained model predicted, straight from a
saved predictions JSON -- no inference, no GPU, seconds per threshold.

WHY THE COLOURS ARE WHAT THEY ARE
---------------------------------
`score_v2.py` section 5 computes D32 and the atomised fraction from

    dets = [d for d in preds if d["score"] >= t and not d["truncated"]]

so a detection reaches the measurement only if it clears the score threshold
AND was not cut off at a tile seam. The old preview drew every detection in its
class colour, which showed what the model SAW but not what the numbers were
built from. Here:

    green   droplet, not truncated   -> IS in the D32 number
    red     droplet, truncated       -> detected, EXCLUDED from D32
    orange  filament                 -> not in D32; feeds the atomised fraction
    blue    blob                     -> not in D32; feeds the atomised fraction
    thin red box  any truncated object, any class -- excluded from every
                  measurement, because the truncation filter is class-blind

D32 is area-weighted (sum d^3 / sum d^2), so the green set is what moves it.

Usage:
    python preview_predictions.py --pred <LaCie>/.../06_validation/v3_predictions.json
    python preview_predictions.py --pred ... --thresholds 0.3 0.5 --frames frame_0056_n559
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from pycocotools import mask as mask_util

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402

UM_PER_PX = 10.0
DEFAULT_THRESHOLDS = [0.05, 0.30, 0.50, 0.70, 0.90]

# OpenCV is BGR.
GREEN = (0, 200, 0)
RED = (0, 0, 255)
ORANGE = (0, 165, 255)
BLUE = (255, 120, 0)
MAGENTA = (200, 0, 200)   # in the D32 number, but fails the focus test
GREY = (150, 150, 150)
BLACK = (0, 0, 0)

CAT = {1: "droplet", 2: "filament", 3: "blob"}


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def equiv_um(area_px):
    return 2.0 * np.sqrt(np.asarray(area_px, dtype=float) / np.pi) * UM_PER_PX


def d32(areas):
    """Sauter mean diameter -- area-weighted, so small detections barely move it."""
    if len(areas) == 0:
        return float("nan")
    d = equiv_um(np.asarray(areas))
    return float((d ** 3).sum() / (d ** 2).sum())


def class_area_union(dets):
    """
    Per-class area as the union of masks (see score_v2.py -- sub-segments of one
    filament are not duplicates but must not be double-counted).

    Union WITHIN a frame, then sum across frames. Merging RLEs from frames of
    different sizes is meaningless -- the benchmark mixes 2560x1600 and
    2048x1152, and doing it globally silently produced nan.
    """
    by = defaultdict(lambda: defaultdict(list))
    for d in dets:
        by[d["image_id"]][d["category_id"]].append(d["segmentation"])
    tot = defaultdict(float)
    for _img, per_class in by.items():
        for c, rles in per_class.items():
            tot[c] += float(mask_util.area(mask_util.merge(rles)))
    return tot


def role(det, in_focus=None):
    """
    (colour, is_measured) for one detection, mirroring score_v2 section 5.

    `in_focus` is optional and only supplied when --focus-gate is on. The MODEL
    has no measurable/unmeasurable concept -- it emits droplet/filament/blob and
    every droplet enters D32 unless it was truncated at a tile seam. The focus
    gate applies the SAME t_min test the ground truth uses (t_min <= FOCUS_MAX)
    to the model's own masks, which is the only honest analogue of the hand
    labels' measure/seen split. It is a DIAGNOSTIC overlay: nothing in the
    measurement pipeline currently filters on it.
    """
    trunc = bool(det.get("truncated", False))
    cid = det["category_id"]
    if cid == 1:
        if trunc:
            return RED, False
        if in_focus is False:
            return MAGENTA, True     # still counted in D32 today -- that is the point
        return GREEN, True
    return (ORANGE if cid == 2 else BLUE), (not trunc)


def ring_contours(mask, bbox, offset, shape):
    """
    Contours of the mask grown outward by `offset` px, so the outline sits clear
    of the object instead of on top of it.

    A droplet here is often 3-5 px across, so an outline drawn on its boundary
    covers the very edge you want to judge. Standing the ring off by ~10 px
    leaves the droplet itself untouched.

    Dilation runs on a bbox crop, not the full frame -- morphology on a
    2560x1600 array once per detection is thousands of times more work for an
    identical result.
    """
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


def render_overlay(view, dets, thresh, thickness=1, droplet_ring=0, T=None,
                   focus_max=0.70):
    """Draw the detections at one threshold. No legend -- callers add their own,
    sized for whatever they are composing.

    `droplet_ring` stands droplet outlines off by N px. Filaments and blobs are
    always drawn on their true boundary: they are large enough to see under the
    line, and their exact extent is what the atomised fraction is computed from.
    """
    canvas = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR) if view.ndim == 2 else view.copy()
    keep = [d for d in dets if d["score"] >= thresh]

    counts = {"droplet_used": 0, "droplet_excluded": 0, "filament": 0, "blob": 0,
              "droplet_out_of_focus": 0}
    smd_areas = []
    for d in keep:
        m = mask_util.decode(d["segmentation"])
        in_focus = None
        if T is not None and d["category_id"] == 1:
            mb = m.astype(bool)
            in_focus = bool(T[mb].min() <= focus_max) if mb.any() else None
        colour, measured = role(d, in_focus)
        if in_focus is False:
            counts["droplet_out_of_focus"] += 1
        if d["category_id"] == 1 and droplet_ring > 0:
            cnts = ring_contours(m, d["bbox"], droplet_ring, canvas.shape[:2])
        else:
            cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, cnts, -1, colour, thickness)
        if d.get("truncated", False):
            x, y, w_, h_ = [int(v) for v in d["bbox"]]
            cv2.rectangle(canvas, (x, y), (x + w_, y + h_), RED, thickness)
        if d["category_id"] == 1:
            if measured:
                counts["droplet_used"] += 1
                smd_areas.append(d["area"])
            else:
                counts["droplet_excluded"] += 1
        else:
            counts[CAT[d["category_id"]]] += 1
    return canvas, counts, smd_areas, keep


def draw_frame(view, dets, thresh, out_path, T=None, focus_max=0.70,
               droplet_ring=0):
    """Full-resolution single-threshold image, with the full legend."""
    canvas, counts, smd_areas, keep = render_overlay(
        view, dets, thresh, droplet_ring=droplet_ring, T=T, focus_max=focus_max)
    frame_d32 = d32(smd_areas)
    n_oof = counts.get("droplet_out_of_focus", 0)
    n_sharp = counts["droplet_used"] - n_oof
    if T is None:
        lines = [
            (f"score >= {thresh:.2f}    {len(keep)} detections", BLACK),
            (f"green  droplet IN D32        {counts['droplet_used']}", GREEN),
            (f"red    droplet EXCLUDED      {counts['droplet_excluded']}", RED),
            (f"orange filament              {counts['filament']}", ORANGE),
            (f"blue   blob                  {counts['blob']}", BLUE),
            (f"frame D32 (green only): {frame_d32:.1f} um", BLACK),
            ("red box = truncated at a seam, excluded from all measurements", GREY),
        ]
    else:
        lines = [
            (f"score >= {thresh:.2f}    {len(keep)} detections    "
             f"focus test: t_min <= {focus_max}", BLACK),
            (f"green   droplet in D32, IN FOCUS -- size trustworthy   {n_sharp}", GREEN),
            (f"magenta droplet in D32, OUT OF FOCUS -- size NOT       {n_oof}", MAGENTA),
            (f"red     droplet excluded (truncated at a seam)         "
             f"{counts['droplet_excluded']}", RED),
            (f"orange  filament                                      "
             f"{counts['filament']}", ORANGE),
            (f"blue    blob                                          "
             f"{counts['blob']}", BLUE),
            (f"frame D32 (green + magenta, as measured today): {frame_d32:.1f} um", BLACK),
            ("NOTE: magenta droplets ARE counted in D32 today. The focus gate is a",
             GREY),
            ("diagnostic -- nothing in the measurement filters on it yet.", GREY),
        ]
    y = 34
    for txt, col in lines:
        cv2.putText(canvas, txt, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
        y += 32

    cv2.imwrite(str(out_path), canvas)
    return counts, smd_areas, keep


def label_panel(panel, thresh, counts, d32_um, scale=1.0):
    """
    Small count block, top-left, over a translucent plate.

    Drawn AFTER the panel is resized so the text is sized in final pixels and
    stays crisp -- text drawn before a downscale would blur. `scale` grows it
    with the panel so a native-resolution sheet shows the block at the same
    apparent size once fitted to a screen.
    """
    pad = max(6, int(6 * scale))
    fs = 0.42 * scale
    th = max(1, int(round(scale)))
    lh = max(15, int(15 * scale))
    rows = [
        (f"score >= {thresh:.2f}", BLACK),
        (f"droplet  {counts['droplet_used']}", GREEN),
        (f"filament {counts['filament']}", ORANGE),
        (f"blob     {counts['blob']}", BLUE),
    ]
    if counts["droplet_excluded"]:
        rows.append((f"excluded {counts['droplet_excluded']}", RED))
    if not np.isnan(d32_um):
        rows.append((f"D32 {d32_um:.0f} um", BLACK))

    w = max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, fs, th)[0][0] for t, _ in rows)
    box = (pad * 2 + w, pad * 2 + lh * len(rows))
    plate = panel[0:box[1], 0:box[0]].copy()
    panel[0:box[1], 0:box[0]] = cv2.addWeighted(
        plate, 0.25, np.full_like(plate, 255), 0.75, 0)
    cv2.rectangle(panel, (0, 0), (box[0] - 1, box[1] - 1), (200, 200, 200), 1)

    y = pad + int(11 * scale)
    for txt, col in rows:
        cv2.putText(panel, txt, (pad, y), cv2.FONT_HERSHEY_SIMPLEX, fs, col, th,
                    cv2.LINE_AA)
        y += lh
    return panel


def contact_sheet(view, dets, thresholds, out_path, gt_note="",
                  cols=3, panel_w=1280, gap=8, droplet_ring=0):
    """One frame, every threshold, as a labelled grid.

    panel_w=0 keeps every panel at the frame's native resolution -- nothing is
    resampled, so the sheet is zoomable to the pixel and a 3 px droplet is still
    3 px. Contours then go on 1 px, as in the single-threshold images.

    When the panels ARE downscaled, contours go on 2 px first: a 1 px outline
    around a 3 px droplet disappears completely at half scale.
    """
    h0, w0 = view.shape[:2]
    native = panel_w <= 0
    out_w = w0 if native else panel_w
    scale = out_w / w0
    thickness = 1 if scale >= 0.9 else 2

    panels = []
    for t in thresholds:
        full, counts, areas, _ = render_overlay(view, dets, t, thickness=thickness,
                                                droplet_ring=droplet_ring)
        if native:
            panel = full
        else:
            panel = cv2.resize(full, (out_w, max(1, round(h0 * scale))),
                               interpolation=cv2.INTER_AREA)
        panels.append(label_panel(panel, t, counts, d32(areas), scale=max(1.0, scale)))

    ph = max(p.shape[0] for p in panels)
    rows = (len(panels) + cols - 1) // cols
    head = max(30, int(30 * scale))
    sheet = np.full((head + rows * ph + (rows + 1) * gap,
                     cols * out_w + (cols + 1) * gap, 3), 245, np.uint8)
    cv2.putText(sheet, gt_note, (gap, int(20 * max(1.0, scale))),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5 * max(1.0, scale), BLACK,
                max(1, int(round(scale))), cv2.LINE_AA)
    for i, p in enumerate(panels):
        r, c = divmod(i, cols)
        y0 = head + gap + r * (ph + gap)
        x0 = gap + c * (out_w + gap)
        sheet[y0:y0 + p.shape[0], x0:x0 + out_w] = p
    cv2.imwrite(str(out_path), sheet, [cv2.IMWRITE_PNG_COMPRESSION, 3])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pred", type=Path, required=True, help="predictions JSON")
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--val-dir", default="06_validation",
                    help="which set, relative to the Real_Data root, e.g. "
                         "09_experiments/02_Chosen_Frame.")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="default: 06_validation/<pred stem>_by_threshold/")
    ap.add_argument("--thresholds", type=float, nargs="+", default=DEFAULT_THRESHOLDS)
    ap.add_argument("--frames", nargs="+", default=None, help="frame stems; default all")
    ap.add_argument("--no-sheets", action="store_true",
                    help="skip the per-frame all-thresholds contact sheets")
    ap.add_argument("--only-sheets", action="store_true",
                    help="skip the full-res single-threshold images and build only the "
                         "sheets. The singles are the slow half and rarely change, so "
                         "this is the flag to use when re-running for layout tweaks.")
    ap.add_argument("--sheet-cols", type=int, default=3)
    ap.add_argument("--panel-width", type=int, default=1280,
                    help="panel width on the sheets. 0 = native resolution, nothing "
                         "resampled, zoomable to the pixel (much larger files).")
    ap.add_argument("--droplet-ring", type=int, default=0,
                    help="stand droplet outlines off by N px so the droplet edge stays "
                         "visible underneath. Filaments and blobs are unaffected.")
    ap.add_argument("--sheet-dir", default="sheets",
                    help="subfolder for the sheets (default: sheets)")
    ap.add_argument("--focus-gate", action="store_true",
                    help="colour droplets MAGENTA when their own t_min fails the "
                         "focus test, i.e. the size the model is contributing to D32 "
                         "is not trustworthy. DIAGNOSTIC ONLY -- nothing in the "
                         "measurement filters on this today. Needs --sixteen-bit-dir "
                         "and --background.")
    ap.add_argument("--sixteen-bit-dir", type=Path, default=None,
                    help="16-bit TIFFs for --focus-gate (default: <val-dir>/frames/16bit)")
    ap.add_argument("--background", type=Path, default=None,
                    help="temporal-median background for --focus-gate. MUST be the one "
                         "for this run, or every transmission value is wrong.")
    ap.add_argument("--focus-max", type=float, default=0.70,
                    help="focus cutoff for --focus-gate (must match extract_candidates.py)")
    args = ap.parse_args()

    root = args.root or real_data_root()
    val = root / args.val_dir
    gt = json.loads((val / "instances.json").read_text(encoding="utf-8"))
    name_by_id = {im["id"]: im["file_name"] for im in gt["images"]}

    preds = json.loads(args.pred.read_text(encoding="utf-8"))
    stray = {d["image_id"] for d in preds} - set(name_by_id)
    if stray:
        sys.exit(f"{len(stray)} prediction image_id(s) absent from the ground truth "
                 f"-- these predictions were made against a different benchmark version.")

    by_img = defaultdict(list)
    for d in preds:
        by_img[d["image_id"]].append(d)

    # Hand-labelled counts, for the sheet header -- the number every panel is
    # trying to reproduce. Measurable only, matching what the metrics use.
    gt_counts = defaultdict(lambda: defaultdict(int))
    for a in gt["annotations"]:
        if a.get("measurable", True):
            gt_counts[a["image_id"]][a["category_id"]] += 1

    tag = args.pred.stem.replace("_predictions", "")
    out_root = args.out_dir or (val / f"{tag}_by_threshold")
    out_root.mkdir(parents=True, exist_ok=True)

    wanted = set(args.frames) if args.frames else None
    summary = []

    # Transmission maps for --focus-gate. Cached per frame; the background MUST
    # belong to this run (each recording has its own temporal median, and the
    # wrong one silently corrupts every T value).
    _bg = None
    _T_cache = {}
    if args.focus_gate:
        if args.background is None:
            sys.exit("--focus-gate needs --background (the run's "
                     "background_median.tiff from 01_candidates/<run>/).")
        _bg = cv2.imread(str(args.background), cv2.IMREAD_UNCHANGED)
        if _bg is None:
            sys.exit(f"could not read background: {args.background}")
        _bg = _bg.astype(np.float32)

    def T_of(stem):
        if not args.focus_gate:
            return None
        if stem not in _T_cache:
            sb = args.sixteen_bit_dir or (val / "frames" / "16bit")
            raw = cv2.imread(str(Path(sb) / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
            if raw is None:
                sys.exit(f"--focus-gate: no 16-bit frame for {stem} under {sb}")
            _T_cache[stem] = raw.astype(np.float32) / np.maximum(_bg, 1.0)
        return _T_cache[stem]

    for thresh in args.thresholds:
        tdir = out_root / f"score_{thresh:.2f}"
        if not args.only_sheets:
            tdir.mkdir(parents=True, exist_ok=True)
        tot = {"droplet_used": 0, "droplet_excluded": 0, "filament": 0, "blob": 0}
        all_areas, all_kept = [], []
        for image_id, dets in sorted(by_img.items()):
            stem = Path(name_by_id[image_id]).stem
            if wanted and stem not in wanted:
                continue
            view = cv2.imread(str(val / "frames" / "8bit" / f"{stem}.png"),
                              cv2.IMREAD_UNCHANGED)
            if view is None:
                print(f"  {stem}: no 8-bit frame, skipped")
                continue
            if args.only_sheets:
                # Same tallies, no full-res render or PNG write.
                _, counts, areas, kept = render_overlay(
                    view, dets, thresh, T=T_of(stem), focus_max=args.focus_max)
            else:
                counts, areas, kept = draw_frame(
                    view, dets, thresh, tdir / f"{stem}.png",
                    T=T_of(stem), focus_max=args.focus_max,
                    droplet_ring=args.droplet_ring)
            for k in tot:
                tot[k] += counts[k]
            all_areas.extend(areas)
            all_kept.extend(kept)

        measured = [d for d in all_kept if not d.get("truncated", False)]
        u = class_area_union(measured)
        tot_area = sum(u.values())
        frac = u.get(1, 0.0) / tot_area * 100 if tot_area else float("nan")
        row = dict(threshold=thresh, d32=d32(all_areas),
                   atomised_pct=frac, **tot)
        summary.append(row)
        print(f"score >= {thresh:.2f}  ->  {tdir.name}/   "
              f"droplets in D32 {tot['droplet_used']:5d}  excluded {tot['droplet_excluded']:4d}  "
              f"filament {tot['filament']:4d}  blob {tot['blob']:3d}   "
              f"D32 {row['d32']:6.1f} um   atomised {frac:5.2f}%")

    if not args.no_sheets:
        sheet_dir = out_root / args.sheet_dir
        sheet_dir.mkdir(parents=True, exist_ok=True)
        print()
        for image_id, dets in sorted(by_img.items()):
            stem = Path(name_by_id[image_id]).stem
            if wanted and stem not in wanted:
                continue
            view = cv2.imread(str(val / "frames" / "8bit" / f"{stem}.png"),
                              cv2.IMREAD_UNCHANGED)
            if view is None:
                continue
            g = gt_counts[image_id]
            note = (f"{stem}   {view.shape[1]}x{view.shape[0]}   "
                    f"hand-labelled (measurable): droplet {g[1]}  filament {g[2]}  "
                    f"blob {g[3]}")
            contact_sheet(view, dets, args.thresholds, sheet_dir / f"{stem}.png",
                          gt_note=note, cols=args.sheet_cols,
                          panel_w=args.panel_width, droplet_ring=args.droplet_ring)
            print(f"  sheet: {stem}")

    csv_path = out_root / "summary.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        cols = ["threshold", "droplet_used", "droplet_excluded", "filament", "blob",
                "d32", "atomised_pct"]
        f.write(",".join(cols) + "\n")
        for r in summary:
            f.write(",".join(f"{r[c]:.4g}" if isinstance(r[c], float) else str(r[c])
                             for c in cols) + "\n")
    print(f"\nwritten: {out_root}\n         {csv_path}")


if __name__ == "__main__":
    main()
