#!/usr/bin/env python3
"""
composite.py -- Step 5: build the training set by compositing real objects
onto real backgrounds.

See docs/HANDOFF_real_data_pipeline.md decisions 4, 5 and 6.

THE PHYSICS, AND WHY IT IS NOT ALPHA BLENDING
---------------------------------------------
Shadowgraph forms an image as  I = I_bg x T,  where T in (0, 1] is the
fraction of light transmitted. Liquid absorbs, so T < 1 inside an object.
Library objects are stored as exactly that ratio, T = I_obj / I_bg_local,
computed at extraction time.

Compositing is therefore a PRODUCT, never a blend:

    I_new = I_bg_new  x  T_1  x  T_2  x  ...

Two consequences that an alpha blend would get wrong, both silently:

  1. Overlaps multiply. Light crossing two objects is attenuated by both, so
     the overlap is darker than either alone -- and by the right amount, for
     free. Alpha blending would average them, making overlaps too bright and
     teaching the model physics that does not hold in its test data.
  2. There is no "occlusion". In a shadowgraph nothing hides anything; a
     nearer object does not replace a farther one. So instance masks are NOT
     subtracted where they overlap -- every object keeps its whole mask, and
     overlapping instance masks are correct ground truth.

T > 1 IS REAL. Specular glints off droplet surfaces exceed the background
(measured up to 1.18 in the library). Do not clip T at 1.0 -- the product
handles brightening correctly and clipping would erase a real phenomenon.

WHAT GETS PASTED, AND THE SEAM PROBLEM
--------------------------------------
A stored crop is a rectangle: the object, plus a 12 px margin of its original
surroundings. Pasting that whole rectangle would import the original frame's
noise -- and sometimes a neighbouring object caught in the margin (measured:
out-of-mask crop medians range 0.971..1.004, so some margins are genuinely
3% dark) -- as a visible rectangular seam.

Pasting only inside the mask instead cuts the object at its half-maximum
boundary, discarding the real soft edge outside it.

So neither: the object's deviation from unity is faded out over a few pixels
beyond the mask,

    T_eff = 1 + (T_crop - 1) * w,     w = 1 inside the mask, -> 0 outside

which keeps the real halo near the boundary, forces the far field to exactly
1.0 (no seam, no imported neighbour), and needs no decision about where the
object "really" ends.

SCALE IS NEVER RANDOMISED. Rotation and flips only. Object pixel size is the
measurement -- rescaling an object would make its diameter a lie.

Usage:
    python composite.py --run-name 125917_NNA_3000sccm --n 2000
    python composite.py --run-name 125917_NNA_3000sccm --preview 6
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
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
from _fsutil import list_files  # noqa: E402

# category_id -> name. Recorded in the COCO json, which is self-describing,
# but keep this stable: Detectron2 maps these to contiguous 0-indexed classes
# in sorted-id order, so changing the numbering changes the model's outputs.
CATEGORIES = [
    {"id": 1, "name": "droplet"},
    {"id": 2, "name": "filament"},
    {"id": 3, "name": "blob"},
]
CLASS_TO_ID = {c["name"]: c["id"] for c in CATEGORIES}

# Per-image class mix. The library is ~68% droplet by count, but the handoff
# asks for deliberate control -- including droplet-rich scenes that do not
# occur in this run's footage.
MIX_REGIMES = {
    "natural":      {"weight": 0.50, "mix": {"droplet": 0.70, "filament": 0.25, "blob": 0.05}},
    "droplet_rich": {"weight": 0.30, "mix": {"droplet": 0.95, "filament": 0.04, "blob": 0.01}},
    "filament_rich":{"weight": 0.20, "mix": {"droplet": 0.30, "filament": 0.65, "blob": 0.05}},
}


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def load_library(lib_dir: Path):
    """Objects grouped by class, each with its transmission map and mask."""
    with open(lib_dir / "library.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_class = defaultdict(list)
    for r in rows:
        cls = r["library_class"]
        cid = r["candidate_id"]
        by_class[cls].append({
            "id": cid,
            "class": cls,
            "weight": float(r.get("library_weight", 1.0) or 1.0),
            "t_path": lib_dir / cls / "transmission" / f"{cid}.tiff",
            "m_path": lib_dir / cls / "masks" / f"{cid}.png",
        })
    return by_class


_OBJ_CACHE = {}


def load_object(obj):
    """Cached -- the whole library is ~50 MB, and lamella crops are ~3 MB each
    re-read thousands of times otherwise."""
    hit = _OBJ_CACHE.get(obj["id"])
    if hit is not None:
        return hit
    T = cv2.imread(str(obj["t_path"]), cv2.IMREAD_UNCHANGED)
    M = cv2.imread(str(obj["m_path"]), cv2.IMREAD_UNCHANGED)
    if T is None or M is None:
        return None, None
    val = (T.astype(np.float32), (M > 0))
    _OBJ_CACHE[obj["id"]] = val
    return val


def transform(T, M, rng):
    """Random flips and a free rotation. No scaling -- scale is the measurement."""
    if rng.random() < 0.5:
        T, M = np.fliplr(T).copy(), np.fliplr(M).copy()
    if rng.random() < 0.5:
        T, M = np.flipud(T).copy(), np.flipud(M).copy()

    angle = float(rng.uniform(0, 360))
    h, w = T.shape
    rot = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    cos, sin = abs(rot[0, 0]), abs(rot[0, 1])
    nw, nh = int(h * sin + w * cos) + 1, int(h * cos + w * sin) + 1
    rot[0, 2] += nw / 2.0 - w / 2.0
    rot[1, 2] += nh / 2.0 - h / 2.0

    # borderValue=1.0 is critical: the border of a transmission map is "no
    # liquid", which is 1.0. Filling with 0.0 -- the OpenCV default -- means
    # "totally opaque" and would paste black corners around every object.
    T_r = cv2.warpAffine(T, rot, (nw, nh), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=1.0)
    M_r = cv2.warpAffine(M.astype(np.uint8), rot, (nw, nh), flags=cv2.INTER_NEAREST,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return T_r, M_r.astype(bool)


def feather(T, M, feather_px):
    """
    Fade the object's deviation from unity to exactly 1.0 outside its mask.
    See the seam discussion in the module docstring.
    """
    if feather_px <= 0:
        out = np.ones_like(T)
        out[M] = T[M]
        return out
    outside = (~M).astype(np.uint8)
    dist = cv2.distanceTransform(outside, cv2.DIST_L2, 5)
    w = np.clip(1.0 - dist / float(feather_px), 0.0, 1.0)
    w[M] = 1.0
    return 1.0 + (T - 1.0) * w


def encode_rle(mask):
    rle = mask_util.encode(np.asfortranarray(mask.astype(np.uint8)))
    rle["counts"] = rle["counts"].decode("ascii")
    return rle


def sample_object(by_class, cls, rng):
    pool = by_class.get(cls)
    if not pool:
        return None
    wts = np.array([o["weight"] for o in pool], dtype=np.float64)
    wts /= wts.sum()
    return pool[int(rng.choice(len(pool), p=wts))]


def build_image(bg_full, by_class, rng, args, next_ann_id, image_id):
    """Composite one training image. Returns (uint8 image, annotations, info)."""
    S = args.size
    H, W = bg_full.shape

    # Random crop of a real background. Random position is also the mitigation
    # for single-run dirt memorisation -- the fixed smudge and vignette land
    # in a different place each time.
    by = int(rng.integers(0, max(1, H - S)))
    bx = int(rng.integers(0, max(1, W - S)))
    bg = bg_full[by:by + S, bx:bx + S].astype(np.float32)
    bg *= float(rng.uniform(1.0 - args.intensity_jitter, 1.0 + args.intensity_jitter))

    regime_names = list(MIX_REGIMES)
    regime_p = np.array([MIX_REGIMES[r]["weight"] for r in regime_names])
    regime_p /= regime_p.sum()
    regime = regime_names[int(rng.choice(len(regime_names), p=regime_p))]
    mix = MIX_REGIMES[regime]["mix"]

    # Log-uniform density so sparse and dense scenes are both well represented
    # (the real process is intermittent -- see established facts).
    k = int(round(np.exp(rng.uniform(np.log(args.min_objects), np.log(args.max_objects)))))

    T_total = np.ones((S, S), dtype=np.float32)
    occupancy = np.zeros((S, S), dtype=bool)
    anns = []
    placed = 0

    classes = list(mix)
    class_p = np.array([mix[c] for c in classes])
    class_p /= class_p.sum()

    for _ in range(k):
        if occupancy.mean() > args.max_coverage:
            break
        cls = classes[int(rng.choice(len(classes), p=class_p))]
        obj = sample_object(by_class, cls, rng)
        if obj is None:
            continue
        T_o, M_o = load_object(obj)
        if T_o is None:
            continue
        T_o, M_o = transform(T_o, M_o, rng)
        if not M_o.any():
            continue
        T_eff = feather(T_o, M_o, args.feather)
        oh, ow = T_eff.shape

        # Placement may hang off the canvas on purpose: tiled inference cuts
        # objects at every tile boundary, so the model must see truncated ones.
        for _attempt in range(args.place_attempts):
            y0 = int(rng.integers(-(oh - args.min_visible_px), S - args.min_visible_px + 1))
            x0 = int(rng.integers(-(ow - args.min_visible_px), S - args.min_visible_px + 1))
            ys, ye = max(0, y0), min(S, y0 + oh)
            xs, xe = max(0, x0), min(S, x0 + ow)
            if ye <= ys or xe <= xs:
                continue
            sub_m = M_o[ys - y0:ye - y0, xs - x0:xe - x0]
            vis = int(sub_m.sum())
            if vis < args.min_visible_px:
                continue
            # Overlap is physically fine (it multiplies correctly); the limit is
            # about LABEL quality -- two heavily overlapped instances are an
            # ambiguous target, not a wrong image.
            if vis and (sub_m & occupancy[ys:ye, xs:xe]).sum() / vis > args.max_overlap:
                continue
            break
        else:
            continue

        sub_t = T_eff[ys - y0:ye - y0, xs - x0:xe - x0]
        T_total[ys:ye, xs:xe] *= sub_t

        inst = np.zeros((S, S), dtype=bool)
        inst[ys:ye, xs:xe] = sub_m
        occupancy |= inst

        ry, rx = np.where(inst)
        bbox = [int(rx.min()), int(ry.min()),
                int(rx.max() - rx.min() + 1), int(ry.max() - ry.min() + 1)]
        anns.append({
            "id": next_ann_id + len(anns),
            "image_id": image_id,
            "category_id": CLASS_TO_ID[obj["class"]],
            "segmentation": encode_rle(inst),
            "area": float(inst.sum()),
            "bbox": bbox,
            "iscrowd": 0,
            "source_object": obj["id"],
        })
        placed += 1

    img = bg * T_total
    img8 = np.clip((img - args.window_lo) / (args.window_hi - args.window_lo) * 255.0,
                   0, 255).astype(np.uint8)
    info = {"regime": regime, "k_requested": k, "k_placed": placed,
            "coverage": float(occupancy.mean())}
    return img8, anns, info


def draw_preview(img8, anns):
    """Annotation outlines over the composite, for eyeballing correctness."""
    colour = {1: (80, 200, 80), 2: (60, 90, 240), 3: (240, 180, 60)}
    canvas = cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR)
    for a in anns:
        m = mask_util.decode({**a["segmentation"],
                              "counts": a["segmentation"]["counts"].encode("ascii")})
        cont, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, cont, -1, colour.get(a["category_id"], (255, 255, 255)), 1)
    return canvas


def main():
    ap = argparse.ArgumentParser(description="Composite real objects onto real backgrounds (Step 5)")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--n", type=int, default=2000, help="images to generate")
    ap.add_argument("--size", type=int, default=800, help="output edge length (handoff decision 6)")
    ap.add_argument("--min-objects", type=int, default=3)
    ap.add_argument("--max-objects", type=int, default=60)
    ap.add_argument("--feather", type=int, default=5,
                    help="px over which an object's deviation fades to 1.0 outside its mask")
    ap.add_argument("--max-overlap", type=float, default=0.30,
                    help="reject a placement overlapping existing instances by more than this "
                         "fraction of its visible area (label clarity, not physics)")
    ap.add_argument("--max-coverage", type=float, default=0.60,
                    help="stop adding objects once this fraction of the canvas is covered")
    ap.add_argument("--min-visible-px", type=int, default=12,
                    help="an object clipped below this is repositioned, never pasted "
                         "unlabelled -- everything visible in the image is annotated")
    ap.add_argument("--place-attempts", type=int, default=12)
    ap.add_argument("--intensity-jitter", type=float, default=0.02,
                    help="per-image background scale jitter; with one run every background "
                         "shares a dirt pattern, and this plus random crops is the mitigation")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--preview", type=int, default=0,
                    help="write N annotated preview images instead of a dataset")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    lib_dir = root / "02_library"
    out_dir = root / "05_dataset"

    # Prefer cleaned backgrounds. The raw ones each carry ~4.7 real in-focus
    # objects that would sit UNLABELLED in every composite built on them --
    # about 20% of the real objects per image, training the model to suppress
    # exactly what it needs to find. See clean_backgrounds.py.
    bg_dir = root / "03_backgrounds" / "16bit_clean"
    if not list_files(bg_dir, "*.tiff"):
        bg_dir = root / "03_backgrounds" / "16bit"
        print("WARNING: using RAW backgrounds -- they contain unlabelled in-focus\n"
              "         objects. Run clean_backgrounds.py first.")

    # The 8-bit mapping MUST match the one real frames were written with, or
    # the model trains on one intensity scale and is tested on another.
    meta_path = root / "00_frames" / args.run_name / "extraction_metadata.json"
    win = json.loads(meta_path.read_text(encoding="utf-8"))["viewing_window_8bit"]
    args.window_lo, args.window_hi = float(win["low"]), float(win["high"])

    by_class = load_library(lib_dir)
    if not by_class:
        sys.exit(f"No library at {lib_dir}. Run build_library.py first.")
    bg_paths = list_files(bg_dir, "*.tiff")
    if not bg_paths:
        sys.exit(f"No backgrounds at {bg_dir}. Run build_backgrounds.py first.")

    print(f"library: " + ", ".join(f"{c} {len(v)}" for c, v in sorted(by_class.items())))
    print(f"backgrounds: {len(bg_paths)} from {bg_dir.name}")
    print(f"8-bit window (matched to real frames): [{args.window_lo}, {args.window_hi}]")
    print(f"canvas {args.size}x{args.size}, {args.min_objects}-{args.max_objects} objects/image")

    backgrounds = [cv2.imread(str(p), cv2.IMREAD_UNCHANGED) for p in bg_paths]
    rng = np.random.default_rng(args.seed)

    if args.preview:
        prev_dir = out_dir / "_preview"
        prev_dir.mkdir(parents=True, exist_ok=True)
        for i in range(args.preview):
            bg = backgrounds[int(rng.integers(len(backgrounds)))]
            img8, anns, info = build_image(bg, by_class, rng, args, 1, i)
            cv2.imwrite(str(prev_dir / f"preview_{i:02d}.png"), img8)
            cv2.imwrite(str(prev_dir / f"preview_{i:02d}_annotated.png"),
                        draw_preview(img8, anns))
            print(f"  preview {i}: {info['regime']:13s} {info['k_placed']:3d} objects "
                  f"(of {info['k_requested']:3d} asked), coverage {info['coverage']*100:4.1f}%")
        print(f"\npreviews -> {prev_dir}")
        print("green=droplet  red=filament  amber=blob")
        return

    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "annotations").mkdir(parents=True, exist_ok=True)

    images, annotations = [], []
    ann_id = 1
    regime_counts = defaultdict(int)
    for i in range(args.n):
        bg = backgrounds[int(rng.integers(len(backgrounds)))]
        img8, anns, info = build_image(bg, by_class, rng, args, ann_id, i + 1)
        fname = f"composite_{i:06d}.png"
        cv2.imwrite(str(img_dir / fname), img8)
        images.append({"id": i + 1, "file_name": fname,
                       "width": args.size, "height": args.size})
        annotations.extend(anns)
        ann_id += len(anns)
        regime_counts[info["regime"]] += 1
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{args.n}  ({len(annotations)} instances so far)")

    coco = {
        "info": {
            "description": "HPATR real-object composited training set",
            "run_name": args.run_name,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "method": "multiplicative transmission compositing of real extracted "
                      "objects onto real clean-field backgrounds",
            "backgrounds": bg_dir.name,
            "intensity_window_8bit": {"low": args.window_lo, "high": args.window_hi,
                                      "note": "matches real frame extraction; inference "
                                              "on real frames must use the same window"},
            "um_per_px": 10.0,
            "scale_randomised": False,
            "seed": args.seed,
            "params": {k: v for k, v in vars(args).items()
                       if k not in ("root", "preview")and not isinstance(v, Path)},
        },
        "images": images,
        "annotations": annotations,
        "categories": CATEGORIES,
    }
    ann_path = out_dir / "annotations" / "instances.json"
    ann_path.write_text(json.dumps(coco), encoding="utf-8")

    per_cat = defaultdict(int)
    for a in annotations:
        per_cat[a["category_id"]] += 1
    print(f"\n{len(images)} images, {len(annotations)} instances -> {out_dir}")
    for c in CATEGORIES:
        print(f"  {c['name']:9s} {per_cat[c['id']]:7d}")
    print(f"  regimes: {dict(regime_counts)}")
    print(f"annotations: {ann_path}")


if __name__ == "__main__":
    main()
