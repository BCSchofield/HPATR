#!/usr/bin/env python3
"""
skeleton_prototype.py -- look at classical segmentation + skeletonisation
beside the model's own masks, on real frames, before building anything on it.

WHY THIS EXISTS
---------------
Mask R-CNN's mask head is a fixed 28x28 grid per detection. A filament with a
100:1 aspect ratio cannot be represented in it. On Trial_1, 566 of 4,364
filament detections are longer than 150 px AND fill under 25% of their own
bounding box; the worst is 626 px long at 0.33% fill, detected at score 1.00 --
the model is certain the object is there and still returns an almost-empty mask.

Blobs have the opposite problem. Their shape is fine (50-78% bbox fill) but they
get cut at tile seams: 96 of 483 blob detections have an edge within 5 px of a
tile boundary, and frame_0074_n739 holds one blob reported as two fragments
split exactly at y=800.

This script renders both alongside a classical whole-frame pass so the two can
be judged by eye. It MEASURES NOTHING and decides nothing.

WHY HYSTERESIS AND NOT A PLAIN THRESHOLD
----------------------------------------
`extract_candidates.py` uses T < 0.95 to find candidates, but that is a
deliberately permissive generator feeding a curation step -- as a segmentation
rule it is unusable: 36,695 components per frame, 89% of the mask area sitting
at transmission 0.90-0.95, which is sensor and illumination noise rather than
liquid.

Seed on dark cores (T<0.70) and grow each seed to ITS OWN half-maximum edge,
(t_min + 1) / 2 -- the edge definition the hand labels, extract_candidates.py
and the model's own training targets all already use. Noise speckle never earns
a seed and is dropped whole. See classical_liquid.hysteresis(), which this
imports rather than duplicating.

A FIXED grow threshold was tried first and was wrong twice over: it inflated a
t_min=0.06 thread (true edge 0.53) by ~1.5x, and it grew droplets past their
half-max so the leftover rim scored as un-atomised liquid -- 85.5% of all
"un-atomised" area on frame_0099_n989.

NOTE ON THE SEED THRESHOLD
--------------------------
Out-of-focus is DEFINED as t_min > 0.70, so a 0.70 seed cannot seed an
out-of-focus object by construction. That is intentional -- it makes this pass
measure the same in-focus population D32 already uses -- but it does mean the
classical mask is not directly comparable to an atomised fraction computed over
all liquid.

Usage:
    python skeleton_prototype.py                      # default Trial_1 frames
    python skeleton_prototype.py --seed 0.7 --ceiling 0.95
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pycocotools import mask as mask_util  # noqa: E402

# Reuse the model-side helpers and the exact colours measure_run draws with, so
# the AI panel here is pixel-comparable to the images already in the run folder.
from measure_run import (  # noqa: E402
    det_crop, GREEN, MAGENTA, ORANGE, BLUE, DROPLET, FILAMENT, UM_PER_PX,
)

# One implementation, shared with the measurement, so the pictures in this
# folder and the numbers beside them can never drift apart.
from classical_liquid import hysteresis, drop_droplet_components  # noqa: E402

try:
    from skimage.morphology import skeletonize
except ImportError:
    sys.exit("scikit-image is required:  pip install scikit-image")

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
CYAN = (255, 255, 0)      # BGR -- classical mask, kept
GREY = (150, 150, 150)    # BGR -- classical mask, dropped as already-detected droplet
RED = (0, 0, 255)         # BGR -- skeleton

DEFAULT_RUN = Path("/Volumes/LaCie/Experiments/2026/09/28/Trial_1")

# Chosen to exercise each known failure mode rather than to look good.
DEFAULT_FRAMES = [
    ("frame_0055_n549",  "worst thread-in-a-box: 626 px filament, 0.33% fill, score 1.00"),
    ("frame_0026_n259",  "long filament: 777 px, 0.60% fill"),
    ("frame_0074_n739",  "blob split at the y=800 tile seam, reported as two"),
    ("frame_0162_n1619", "sparsest frame in the run (43 detections)"),
    ("frame_0185_n1849", "densest frame in the run (495 detections)"),
]


def panel_label(img, lines, scale=1.0):
    """Caption block, top-left, on a white plate so it reads over any frame."""
    fs, th = 1.5 * scale, max(2, int(round(3 * scale)))
    pad = int(18 * scale)
    sizes = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, fs, th)[0] for t in lines]
    bw = max(w for w, _ in sizes) + pad * 2
    lh = int(max(h for _, h in sizes) * 1.9)
    bh = lh * len(lines) + pad
    cv2.rectangle(img, (0, 0), (bw, bh), WHITE, -1)
    for i, t in enumerate(lines):
        cv2.putText(img, t, (pad, int(lh * (i + 0.85))),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, BLACK, th, cv2.LINE_AA)


def draw_ai(canvas, dets, T, focus_max):
    """The model's own masks, drawn exactly as measure_run draws them."""
    for d in dets:
        mb, bx, by, bh, bw = det_crop(d)
        if not mb.any():
            continue
        cid = d["category_id"]
        if cid == DROPLET:
            sharp = bool(T[by:by + bh, bx:bx + bw][mb].min() <= focus_max)
            colour = GREEN if sharp else MAGENTA
        elif cid == FILAMENT:
            colour = ORANGE
        else:
            colour = BLUE
        full = np.zeros(canvas.shape[:2], np.uint8)
        full[by:by + bh, bx:bx + bw] = mb
        cnts, _ = cv2.findContours(full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, cnts, -1, colour, 2)


def overlay(canvas, mask, colour, alpha=0.45):
    canvas[mask] = (np.asarray(colour, np.float32) * alpha
                    + canvas[mask].astype(np.float32) * (1 - alpha)).astype(np.uint8)


def to_bgr(view):
    return cv2.cvtColor(view, cv2.COLOR_GRAY2BGR) if view.ndim == 2 else view.copy()


def build_panels(view8, dets, T, kept, dropped, skel, args, thicken_skel=True):
    """Four views of the same frame, UNCAPTIONED.

    Captions are applied later and only to the overview: baking them into the
    panels put a white plate over whatever the detail crop happened to land on.
    """
    p1 = to_bgr(view8)

    p2 = to_bgr(view8)
    draw_ai(p2, dets, T, args.focus_max)

    # Panel 3 shows BOTH what survived and what was removed, so the removal can
    # be checked by eye rather than taken on trust.
    p3 = to_bgr(view8)
    overlay(p3, dropped, GREY, alpha=0.55)
    overlay(p3, kept, CYAN)

    p4 = to_bgr(view8)
    overlay(p4, kept, CYAN, alpha=0.18)
    # A 1-px skeleton vanishes when the overview is downscaled, so thicken it
    # there. The detail crop is full resolution and must NOT be thickened --
    # the whole point of it is to show the true width.
    s = cv2.dilate(skel.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) \
        if thicken_skel else skel
    p4[s] = RED
    return [p1, p2, p3, p4]


def captions_for(dets, kept, dropped, n_kept, n_drop, skel, args):
    n_fil = sum(1 for d in dets if d["category_id"] == FILAMENT)
    n_drop_det = sum(1 for d in dets if d["category_id"] == DROPLET)
    n_blob = len(dets) - n_fil - n_drop_det
    return [
        ["1. frame as the model sees it (8-bit, pinned window)"],
        ["2. MODEL masks", f"   {n_drop_det} droplet  {n_fil} filament  {n_blob} blob"],
        [f"3. CLASSICAL mask (seed T<{args.seed}, edge = per-component half-max)",
         f"   KEPT {n_kept} comps, {kept.sum():,} px",
         f"   GREY: {n_drop} dropped as already-detected droplets"],
        ["4. SKELETON of the kept mask only",
         f"   {skel.sum():,} skeleton px"],
    ]


def grid2x2(panels, caps, max_w):
    """Tile four same-size panels, scaled so the whole grid fits max_w."""
    h, w = panels[0].shape[:2]
    scale = min(1.0, (max_w / 2) / w)
    if scale < 1.0:
        panels = [cv2.resize(p, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA) for p in panels]
    panels = [p.copy() for p in panels]
    for p, c in zip(panels, caps):
        panel_label(p, c, scale=max(0.6, scale * 1.6))
    top = np.hstack([panels[0], panels[1]])
    bot = np.hstack([panels[2], panels[3]])
    sep = np.full((4, top.shape[1], 3), 60, np.uint8)
    return np.vstack([top, sep, bot])


def detail_crop(panels, caps, box, pad=120):
    """Same four panels, full resolution, around one object. No downscaling and
    no skeleton thickening -- a 2 px filament survives here and nowhere else.
    Captions go in a bar UNDER each crop so they cannot cover the subject."""
    x, y, w, h = box
    H, W = panels[0].shape[:2]
    x0, y0 = max(0, int(x) - pad), max(0, int(y) - pad)
    x1, y1 = min(W, int(x + w) + pad), min(H, int(y + h) + pad)
    crops = []
    for p, c in zip(panels, caps):
        sub = p[y0:y1, x0:x1].copy()
        bar = np.full((44, sub.shape[1], 3), 255, np.uint8)
        cv2.putText(bar, c[0], (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, BLACK, 2, cv2.LINE_AA)
        crops.append(np.vstack([sub, bar]))
    sep_v = np.full((crops[0].shape[0], 4, 3), 60, np.uint8)
    row1 = np.hstack([crops[0], sep_v, crops[1]])
    row2 = np.hstack([crops[2], sep_v, crops[3]])
    sep_h = np.full((4, row1.shape[1], 3), 60, np.uint8)
    return np.vstack([row1, sep_h, row2])


def pick_detail_box(dets, liquid):
    """The object most worth looking at closely: the longest, emptiest filament
    box, else the largest classical component."""
    best, best_key = None, None
    for d in dets:
        if d["category_id"] != FILAMENT:
            continue
        x, y, w, h = d["bbox"]
        ba = w * h
        if ba <= 0 or max(w, h) < 150:
            continue
        key = (d["area"] / ba)          # lower fill = more interesting
        if best_key is None or key < best_key:
            best_key, best = key, (x, y, w, h)
    if best:
        return best
    n, lab, stats, _ = cv2.connectedComponentsWithStats(liquid.astype(np.uint8), 8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
            stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=DEFAULT_RUN)
    ap.add_argument("--pred", type=Path, default=None,
                    help="default: <root>/shadowgraph/analysis/predictions_crop.json")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="default: <root>/shadowgraph/analysis/skeletonisation_testing")
    ap.add_argument("--frames", nargs="*", default=None,
                    help="frame stems; default is the five chosen failure cases")
    ap.add_argument("--seed", type=float, default=0.70,
                    help="strict threshold: definitely liquid (default 0.70, the focus gate)")
    ap.add_argument("--ceiling", type=float, default=0.95,
                    help="bounds region growing; the EDGE is each component's own half-max")
    ap.add_argument("--min-area", type=int, default=20)
    ap.add_argument("--droplet-cover", type=float, default=0.50,
                    help="drop a component if this fraction of it is already "
                         "covered by model droplet masks (default 0.50)")
    ap.add_argument("--droplet-max-extent", type=int, default=100,
                    help="never drop a component longer than this, whatever its "
                         "droplet coverage -- guards against losing a filament "
                         "the model emitted as a chain of droplets")
    ap.add_argument("--keep-droplets", action="store_true",
                    help="skip droplet removal entirely (the old behaviour)")
    ap.add_argument("--score-thresh", type=float, default=0.30)
    ap.add_argument("--focus-max", type=float, default=0.70)
    ap.add_argument("--overview-width", type=int, default=3200)
    args = ap.parse_args()

    import json
    root = args.root
    raw = root / "shadowgraph" / "raw"
    pred_path = args.pred or (root / "shadowgraph" / "analysis" / "predictions_crop.json")
    if not pred_path.exists():
        pred_path = root / "shadowgraph" / "analysis" / "predictions.json"
    out_dir = args.out_dir or (root / "shadowgraph" / "analysis" / "skeletonisation_testing")
    out_dir.mkdir(parents=True, exist_ok=True)

    bg = cv2.imread(str(raw / "background_median.tiff"), cv2.IMREAD_UNCHANGED)
    if bg is None:
        sys.exit(f"no background at {raw / 'background_median.tiff'}")
    bg = bg.astype(np.float32)

    preds = json.loads(pred_path.read_text())
    inst = json.loads((raw / "instances.json").read_text())
    id_by_stem = {im["file_name"].rsplit(".", 1)[0]: im["id"] for im in inst["images"]}

    by_img = {}
    for d in preds:
        if d["score"] >= args.score_thresh:
            by_img.setdefault(d["image_id"], []).append(d)

    wanted = args.frames or [f for f, _ in DEFAULT_FRAMES]
    notes = dict(DEFAULT_FRAMES)

    print(f"run        {root}")
    print(f"predictions{pred_path.name}")
    print(f"thresholds seed T<{args.seed}  ceiling T<{args.ceiling}  "
          f"edge=per-component half-max  min_area {args.min_area}")
    print(f"out        {out_dir}\n")

    for stem in wanted:
        img_id = id_by_stem.get(stem)
        if img_id is None:
            print(f"  !! {stem}: not in instances.json, skipped")
            continue
        raw16 = cv2.imread(str(raw / "frames" / "16bit" / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
        view8 = cv2.imread(str(raw / "frames" / "8bit" / f"{stem}.png"), cv2.IMREAD_UNCHANGED)
        if raw16 is None or view8 is None:
            print(f"  !! {stem}: missing 16-bit or 8-bit frame, skipped")
            continue

        T = raw16.astype(np.float32) / np.maximum(bg, 1.0)
        liquid, ncomp = hysteresis(T, args.seed, args.ceiling, args.min_area)
        dets = by_img.get(img_id, [])

        # Already-detected droplets contribute nothing but junk skeleton stubs,
        # so remove them -- by whole component, never by pixel. See
        # drop_droplet_components().
        if args.keep_droplets:
            kept, dropped, n_kept, n_drop = liquid, np.zeros_like(liquid), ncomp, 0
        else:
            dmask = np.zeros(T.shape, bool)
            for d in dets:
                if d["category_id"] == DROPLET:
                    mb, bx, by, bh, bw = det_crop(d)
                    dmask[by:by + bh, bx:bx + bw] |= mb
            kept, dropped, n_kept, n_drop = drop_droplet_components(
                liquid, dmask, args.droplet_cover, args.droplet_max_extent)

        skel = skeletonize(kept)
        caps = captions_for(dets, kept, dropped, n_kept, n_drop, skel, args)

        ov_panels = build_panels(view8, dets, T, kept, dropped, skel, args,
                                 thicken_skel=True)
        cv2.imwrite(str(out_dir / f"{stem}__overview.png"),
                    grid2x2(ov_panels, caps, args.overview_width))

        box = pick_detail_box(dets, kept)
        if box is not None:
            # True 1-px skeleton here: the detail crop exists to show real width.
            dt_panels = build_panels(view8, dets, T, kept, dropped, skel, args,
                                     thicken_skel=False)
            cv2.imwrite(str(out_dir / f"{stem}__detail.png"),
                        detail_crop(dt_panels, caps, box))

        n_fil = sum(1 for d in dets if d["category_id"] == FILAMENT)
        print(f"  {stem:20} model:{len(dets):4} dets ({n_fil:3} filament)   "
              f"classical:{ncomp:4} -> kept {n_kept:4} comps {kept.sum():7,}px   "
              f"(dropped {n_drop:4} droplet comps, {dropped.sum():6,}px)   "
              f"skel {skel.sum():6,}px")
        if stem in notes:
            print(f"  {'':20} ^ {notes[stem]}")

    print(f"\nwritten to {out_dir}")


if __name__ == "__main__":
    main()
