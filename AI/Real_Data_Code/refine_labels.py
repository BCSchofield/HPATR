#!/usr/bin/env python3
"""
refine_labels.py -- Step 6 helper: snap hand/SAM-drawn shapes to the
physically correct half-maximum edge.

WHY THIS EXISTS
----------------
SAM (via LabelMe's AI-Box/AI-Points) was trained on natural images, where a
soft/blurred edge is usually still part of the object. In shadowgraph data the
soft halo around a liquid object is optical defocus, not liquid -- the real
boundary is much tighter. This script does not re-judge WHAT an object is
(labels are never touched) -- only WHERE its edge sits, using the exact same
rule extract_candidates.py already uses everywhere else in this pipeline:
per-object half-maximum, (t_min + 1) / 2.

WHAT IT DOES, PER SHAPE
------------------------
1. Rasterise the existing shape -> a SEARCH region, not the answer. Dilated a
   few px in case the original undershot the object.
2. Within that region, take the connected component containing the shape's
   own centroid (so a neighbouring object caught in a generous SAM box is
   ignored, not merged in).
3. Find that component's darkest pixel, t_min, in the REAL 16-bit transmission
   data -- not the 8-bit view LabelMe displays.
4. Threshold at (t_min + 1) / 2. This is the new mask. Holes (real background
   enclosed by liquid, e.g. a folded filament) survive naturally -- they are
   not filled in.
5. Trace the result back to polygon points. A shape with a hole is written as
   a single keyhole/bridge polygon (outer boundary -> slit -> inner hole
   boundary -> slit back out), the same technique used by hand on the annular
   objects.

WHAT IT NEVER DOES
-------------------
- Never touches `label` (droplet/filament/blob). Classification is your call.
- Never invents an object. If refinement finds nothing near the focus cutoff,
  the shape is left untouched and flagged for you to look at -- possibly a
  shape that should not have been drawn at all.
- Never guesses across a gap. If the search region contains more than one
  clearly separate dark blob, the shape is flagged, not auto-merged or
  auto-split.

SAFETY
------
The original JSON is copied to <name>.original.json the FIRST time this
script touches a file (never overwritten again), so the pre-refinement labels
are always recoverable. The working file is edited in place, so reopening it
in LabelMe shows the refined result directly.

Usage:
    python refine_labels.py --frame frame_0062_n619
"""

import argparse
import json
import shutil
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

FOCUS_MAX = 0.70          # must match extract_candidates.py
DILATE_PX = 5             # search-region margin beyond the original shape
MIN_SIMPLIFY_EPS = 0.35   # floor for small objects -- 1.2 was crushing a 5px
                          # droplet down to a 3-4 point triangle/square
MAX_SIMPLIFY_EPS = 1.2
CIRCLE_FILL_RATIO = 0.65  # mask_area / its min-enclosing-circle area, above
                          # which a droplet is "round enough" to store as a
                          # circle rather than a polygon
CIRCLE_ASPECT_MAX = 1.6   # bbox w/h (or h/w) must stay under this too


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def shape_to_mask(shape, h, w):
    """Rasterise a LabelMe shape (polygon or circle) to a binary mask."""
    pts = np.array(shape["points"], dtype=np.float64)
    m = np.zeros((h, w), dtype=np.uint8)
    if shape.get("shape_type") == "circle":
        c, e = pts[0], pts[1]
        r = int(round(np.linalg.norm(e - c)))
        cv2.circle(m, (int(c[0]), int(c[1])), max(r, 1), 1, -1)
    else:
        cv2.fillPoly(m, [pts.astype(np.int32)], 1)
    return m.astype(bool), pts.mean(axis=0)


def keep_component_at(mask, point, h, w, drawn=None):
    """
    Pick the one connected component of `mask` that belongs to this shape.

    Preference order:
      1. the component containing the shape's centroid;
      2. otherwise the component OVERLAPPING THE DRAWN SHAPE MOST;
      3. otherwise nothing -- an empty mask, which the caller turns into a flag.

    Step 2 matters because a centroid is not a reliable "inside" test for the
    shapes in this data. A curved, hooked or looped filament encloses empty
    background, so its centroid lands OFF the object -- the same geometric fact
    that made bounding-box elongation useless for classifying them.

    Step 3 matters because the search region is dilated, so a NEIGHBOURING
    object only has to come within DILATE_PX to be picked up. Falling back to
    "the largest component nearby" (the original behaviour) silently measured
    that neighbour and wrote it into this shape: observed on frame_0072_n719
    shape 263, which refined to 0 px inside the drawn circle and 15 px outside
    it, all belonging to a different object. Requiring real overlap with what
    was actually drawn rejects that while keeping curved filaments working.
    """
    n, lab = cv2.connectedComponents(mask.astype(np.uint8), 8)
    if n <= 1:
        return mask
    px, py = int(round(point[0])), int(round(point[1]))
    px, py = min(max(px, 0), w - 1), min(max(py, 0), h - 1)
    cid = int(lab[py, px])
    if cid != 0:
        return lab == cid

    if drawn is None:
        return np.zeros_like(mask, dtype=bool)
    best_id, best_overlap = 0, 0
    for i in range(1, n):
        overlap = int(((lab == i) & drawn).sum())
        if overlap > best_overlap:
            best_id, best_overlap = i, overlap
    if best_overlap == 0:
        return np.zeros_like(mask, dtype=bool)
    return lab == best_id


def bridge_hole(outer, hole):
    """Splice a hole contour into an outer contour via the keyhole/slit
    technique: nearest point pair, walk in, trace the hole, walk back out."""
    d = np.linalg.norm(outer[:, None, :] - hole[None, :, :], axis=2)
    i, j = np.unravel_index(np.argmin(d), d.shape)
    return np.vstack([outer[:i + 1], hole[j:], hole[:j + 1], outer[i:]])


def as_circle_if_round(mask, outer_contour, label):
    """
    If `mask` is round enough, return (center, radius) for a LabelMe circle
    shape using the EQUIVALENT-AREA radius -- not the min-enclosing-circle
    radius, which would inflate the area and throw off D32. Only applied to
    droplets: filaments and blobs are never forced round, and a droplet with
    a hole (there shouldn't be one, but be safe) is never forced round either.
    Returns None if the shape doesn't qualify -- caller falls back to polygon.
    """
    if label != "droplet":
        return None
    area = int(mask.sum())
    (cx, cy), r_enclosing = cv2.minEnclosingCircle(outer_contour)
    if r_enclosing <= 0:
        return None
    fill_ratio = area / (np.pi * r_enclosing ** 2)
    x, y, w, h = cv2.boundingRect(outer_contour)
    aspect = max(w, h) / max(1, min(w, h))
    if fill_ratio < CIRCLE_FILL_RATIO or aspect > CIRCLE_ASPECT_MAX:
        return None
    r_equiv = float(np.sqrt(area / np.pi))  # preserves the true area, not the enclosing circle's
    return (float(cx), float(cy)), r_equiv


def mask_to_points(mask, label):
    """
    Binary mask -> LabelMe shape, preserving holes as keyhole bridges when a
    polygon is used. Returns (points, shape_type, status).

    A round droplet becomes a `circle` (center + equivalent-area radius) --
    this is what avoids the blocky-triangle problem AND matches what D32
    actually needs (correct area; exact polygon shape is not required for it).
    Anything else stays a polygon, simplified with a tolerance that SCALES
    with object size so a 5px object isn't crushed by the same 1.2px
    tolerance that's appropriate for a 700px filament.
    """
    cnts, hier = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP,
                                  cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, None, "empty"

    outer_idx = [i for i, h in enumerate(hier[0]) if h[3] == -1]
    if len(outer_idx) > 1:
        return None, None, "fragmented"  # more than one separate blob -- flag, don't guess

    outer_raw = cnts[outer_idx[0]]
    hole_idx = [i for i, h in enumerate(hier[0]) if h[3] == outer_idx[0]]
    if not hole_idx:  # only hole-free shapes are eligible to become a circle
        circle = as_circle_if_round(mask, outer_raw, label)
        if circle is not None:
            (cx, cy), r = circle
            return [[cx, cy], [cx + r, cy]], "circle", "ok"

    eps = float(np.clip(0.12 * np.sqrt(max(cv2.contourArea(outer_raw), 1.0)),
                        MIN_SIMPLIFY_EPS, MAX_SIMPLIFY_EPS))
    outer = cv2.approxPolyDP(outer_raw, eps, True).reshape(-1, 2).astype(np.float64)
    if len(outer) < 3:
        return None, None, "too_small"

    path = outer
    for hi in hole_idx:
        hole = cnts[hi]
        if cv2.contourArea(hole) < 2:
            continue
        hole = cv2.approxPolyDP(hole, eps, True).reshape(-1, 2).astype(np.float64)
        if len(hole) < 3:
            continue
        path = bridge_hole(path, hole)

    return path.tolist(), "polygon", "ok"


def refine_one(shape, T, h, w):
    label = shape["label"]
    mask0, centroid = shape_to_mask(shape, h, w)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * DILATE_PX + 1,) * 2)
    search = cv2.dilate(mask0.astype(np.uint8), k).astype(bool)

    region_T = np.where(search, T, 1.0)
    t_min = float(region_T.min())
    if t_min > FOCUS_MAX:
        return None, None, "never_reaches_focus_cutoff", t_min

    candidate = search & (T < FOCUS_MAX)
    candidate = keep_component_at(candidate, centroid, h, w, mask0)
    if not candidate.any():
        # Nothing in focus at the shape's own centre. The dark pixels that made
        # t_min low belong to something else nearby -- do not measure them, and
        # report darkness over the DRAWN shape only, so the number describes
        # what was actually drawn rather than a neighbour in the search margin.
        t_own = float(T[mask0].min()) if mask0.any() else t_min
        return None, None, "nothing_in_focus_at_centre", t_own

    t_min_final = float(T[candidate].min())
    edge = (t_min_final + 1.0) / 2.0

    # Threshold within the SEARCH region, not within `candidate`.
    #
    # `candidate` is the set of pixels below FOCUS_MAX, and its only job is to
    # identify WHICH object this shape refers to. Using it as the pixel set for
    # the edge as well silently clipped the mask at FOCUS_MAX whenever the
    # half-maximum edge landed above it -- which is every object with
    # t_min > 0.40, since edge = (t_min + 1) / 2. Those objects were being cut
    # at a FIXED CONTRAST THRESHOLD, exactly what the per-object half-maximum
    # rule exists to avoid. Measured over frames 1-2: 104 refined droplets
    # affected, true area a median 1.5x larger (worst 14x), so their diameters
    # -- and therefore D32 -- were biased low.
    grown = search & (T < edge)
    refined = keep_component_at(grown, centroid, h, w, candidate)
    if refined.sum() < 4:
        return None, None, "too_small_after_refine", t_min_final

    points, shape_type, status = mask_to_points(refined, label)
    if points is None:
        return None, None, status, t_min_final
    return points, shape_type, "ok", t_min_final


def main():
    ap = argparse.ArgumentParser(description="Snap LabelMe shapes to the half-maximum edge")
    ap.add_argument("--frame", required=True, help="frame stem, e.g. frame_0062_n619")
    ap.add_argument("--from-original", action="store_true",
                    help="rebuild from <name>.original.json rather than the working "
                         "file. Use this to restore shapes a previous --drop-flagged "
                         "removed: refinement is deterministic, so every shape that "
                         "can be refined still will be, and the rest come back with "
                         "their hand-drawn boundary intact.")
    ap.add_argument("--classes", nargs="+", default=["droplet"],
                    metavar="CLASS",
                    help="which classes to refine (default: droplet only). "
                         "Filaments are EXCLUDED by default because the single "
                         "global half-max threshold truncates them: measured on "
                         "frame_0072_n719, 23 of 51 refined filaments lost more "
                         "than 20%% of their LENGTH (worst kept 12%%), which is "
                         "the refiner overruling the human on extent -- the one "
                         "judgement the human is better at. Width loss alone "
                         "would be legitimate halo removal. Pass "
                         "'--classes droplet filament blob' to refine everything "
                         "once a local/adaptive threshold exists.")
    ap.add_argument("--drop-flagged", action="store_true",
                    help="remove flagged (never-reaches-focus-cutoff / too-small-after-"
                         "refine / fragmented) shapes from the saved JSON instead of "
                         "leaving them in place untouched. Safe either way -- the "
                         ".original.json backup keeps every shape, including dropped "
                         "ones, so nothing is lost if the cutoff turns out too harsh.")
    ap.add_argument("--val-dir", default="06_validation",
                    help="which validation set, e.g. 06_validation_run2")
    ap.add_argument("--run", default="125917_NNA_3000sccm",
                    help="the run these frames came from -- selects the temporal "
                         "median. MUST match the frames or T is wrong everywhere.")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    val_dir = root / args.val_dir
    json_path = val_dir / "labels" / f"{args.frame}.json"
    tiff_path = val_dir / "frames" / "16bit" / f"{args.frame}.tiff"

    # The background MUST come from the run this frame belongs to. Picking the
    # first 01_candidates/* with a median (the old behaviour) selects by
    # alphabetical order, which since run 101947 exists would divide run 125917
    # frames by the wrong illumination field -- every transmission value wrong,
    # silently.
    bg_path = root / "01_candidates" / args.run / "background_median.tiff"

    if not json_path.exists():
        sys.exit(f"No labels file: {json_path}")
    if not tiff_path.exists():
        sys.exit(f"No 16-bit frame: {tiff_path}")
    if not bg_path.exists():
        sys.exit(f"No cached background_median.tiff for run '{args.run}' at {bg_path}")

    backup = json_path.with_suffix(".original.json")
    if not backup.exists():
        shutil.copy2(json_path, backup)
        print(f"backup written (first touch): {backup.name}")

    # Rolling one-step undo, refreshed on EVERY run. `.original.json` is a
    # first-touch snapshot and goes stale as soon as more shapes are drawn, so
    # it cannot be the only safety net -- see the --from-original guard below.
    undo = json_path.with_suffix(".prerefine.json")
    shutil.copy2(json_path, undo)

    source = backup if args.from_original else json_path
    if args.from_original and not backup.exists():
        sys.exit(f"--from-original needs {backup.name}, which does not exist.")
    data = json.loads(source.read_text(encoding="utf-8"))
    if args.from_original:
        # The backup is a snapshot from the FIRST refine of this frame. Any
        # shapes drawn after that exist only in the working file, so rebuilding
        # from the backup would silently delete them -- which is exactly what
        # happened to frame_0201_n2009 on 2026-09-23 (109 shapes -> 107).
        n_working = len(json.loads(json_path.read_text(encoding="utf-8"))["shapes"])
        if n_working > len(data["shapes"]):
            sys.exit(
                f"REFUSING: {json_path.name} has {n_working} shapes but "
                f"{backup.name} has only {len(data['shapes'])}.\n"
                f"The working file contains labelling done AFTER the backup was "
                f"taken; rebuilding from the backup would delete it.\n"
                f"Run without --from-original (refinement is idempotent), or if "
                f"you really do want the older state, move the backup aside first."
            )
        print(f"rebuilding from {backup.name} ({len(data['shapes'])} shapes)")
    h, w = data["imageHeight"], data["imageWidth"]

    img = cv2.imread(str(tiff_path), cv2.IMREAD_UNCHANGED).astype(np.float32)
    bg = cv2.imread(str(bg_path), cv2.IMREAD_UNCHANGED).astype(np.float32)
    T = img / np.maximum(bg, 1.0)

    n_ok, n_flag, n_dropped, n_resized_up, n_resized_down = 0, 0, 0, 0, 0
    n_circle, n_polygon = 0, 0
    flags = []
    n_before = len(data["shapes"])
    new_shapes = []

    n_skipped = 0
    for shape in data["shapes"]:
        if shape["label"] not in args.classes:
            # Left exactly as drawn, and deliberately NOT flagged -- this is a
            # policy choice about which classes the refiner is trusted on, not
            # a failure to refine this particular shape.
            n_skipped += 1
            new_shapes.append(shape)
            continue

        before_mask, _ = shape_to_mask(shape, h, w)
        before_area = int(before_mask.sum())

        points, shape_type, status, t_min = refine_one(shape, T, h, w)
        if points is None:
            n_flag += 1
            flags.append((shape["label"], shape["points"][0], status, round(t_min, 3)))
            if args.drop_flagged:
                n_dropped += 1
            else:
                # Keep the hand-drawn boundary -- for a soft-edged object there is
                # no half-maximum edge to snap to, so the human's outline is the
                # best available. Record why, and how dark it actually got, so the
                # shape can be judged (and filtered at analysis time) on a number
                # rather than on a guess about what the eye saw.
                desc = shape.get("description") or ""
                if not desc or desc.startswith("auto:"):
                    shape["description"] = f"auto: unrefined ({status}), t_min={t_min:.3f}"
                new_shapes.append(shape)
            continue

        temp_shape = {"points": points, "shape_type": shape_type}
        after_mask, _ = shape_to_mask(temp_shape, h, w)
        after_area = int(after_mask.sum())

        shape["points"] = points
        shape["shape_type"] = shape_type
        shape.pop("mask", None)
        n_ok += 1
        n_circle += shape_type == "circle"
        n_polygon += shape_type == "polygon"
        if after_area > before_area * 1.15:
            n_resized_up += 1
        elif after_area < before_area * 0.85:
            n_resized_down += 1
        new_shapes.append(shape)

    data["shapes"] = new_shapes
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    print(f"\n{args.frame}: {n_before} shapes -> {len(new_shapes)} in saved file")
    print(f"  refining classes:   {', '.join(args.classes)}")
    if n_skipped:
        print(f"  left as drawn:      {n_skipped}  (class not in --classes)")
    print(f"  refined:            {n_ok}")
    print(f"    -> circle:        {n_circle}  (round droplets -- equivalent-area radius)")
    print(f"    -> polygon:       {n_polygon}  (size-scaled simplification)")
    print(f"    grew >15%:        {n_resized_up}")
    print(f"    shrank >15%:      {n_resized_down}  (SAM over-mask correction shows up here)")
    print(f"  flagged:            {n_flag}")
    if args.drop_flagged:
        print(f"    -> removed from saved file: {n_dropped}")
        print(f"    -> full originals (including these) still in: {backup.name}")
    else:
        print(f"    -> left in place, untouched (re-run with --drop-flagged to remove)")
    if flags:
        print("\n  flagged shapes -- look at these in LabelMe / the marker image:")
        for label, pt, status, t_min in flags:
            print(f"    {label:10s} near ({pt[0]:.0f},{pt[1]:.0f})  {status:28s}  t_min={t_min}")
    print(f"\nwritten: {json_path}")
    print(f"undo:    {undo.name}  (state before this run -- copy it back if this looks wrong)")


if __name__ == "__main__":
    main()
