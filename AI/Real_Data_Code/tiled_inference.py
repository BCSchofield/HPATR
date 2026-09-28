#!/usr/bin/env python3
"""
tiled_inference.py -- Step 8: run v2 over full frames by tiling.

WHY TILING IS MANDATORY
------------------------
The model's `config.yaml` pins MIN_SIZE_TEST = MAX_SIZE_TEST = 800, so handing
it a 2048x1152 frame rescales the frame by 800/2048 = 0.39 and a 9 px droplet
arrives as ~3 px. An 800x800 tile passes through at exactly 1.0, which is the
scale the model trained at. So: tile, never resize.

TILE LAYOUT -- evenly distributed, not fixed-stride
----------------------------------------------------
Fixed stride plus a "shift the last tile flush" fix gives UNEVEN overlaps (e.g.
stride 700 on 2048 px gives 100 px at the regular seams and 252 px where the
shifted tile lands). The minimum is what constrains you, so the extra is wasted.
Distributing n tiles evenly across the axis gives a uniform, larger overlap for
the same tile count: 2048 px in 3 tiles -> offsets 0/624/1248, overlap 176 px
everywhere, versus 100 px worst-case for stride 700. Same 6 tiles per frame.

SEAMS -- mark, don't drop
--------------------------
An object crossing a seam appears in two tiles as two partial detections whose
mutual IoU is low, so plain NMS keeps both and one filament is counted twice
with wrong areas in both. Dropping every edge-touching detection is worse: an
object longer than the overlap touches an edge in EVERY tile and vanishes
entirely, punishing the model for our tiling choice.

So each detection is flagged `truncated` when its box meets a tile edge that is
not a frame edge. NMS then prefers untruncated detections, and survivors that
are still truncated stay in the detection count but are excluded from size
statistics -- exactly the `touches_border` convention the hand-labelled ground
truth already uses, so the same rule applies on both sides of the comparison.

Measured on the benchmark, at 176 px overlap: 0% of droplets, 7% of filaments
and 4% of blobs are larger than the overlap and so can still be cut.

Usage:
    python tiled_inference.py --frame frame_0072_n719 --preview
    python tiled_inference.py --all --out predictions.json
"""

import argparse
import json
import sys
import time
from math import ceil
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402

TILE = 800
MIN_OVERLAP = 150          # 176 px actual on a 2048 px axis; see module docstring
EDGE_MARGIN = 2            # px tolerance for "touches the tile edge"
NMS_IOU = 0.5
# A detection this fully inside another, AND this large a fraction of it, is a
# duplicate partial rather than a separate object. Both measured against the
# hand-labelled ground truth -- see _merge.
#
# CONTAIN_FRAC is deliberately low because mask IoU collapses for THIN objects:
# two traces of the same filament offset by 4 px across a 10 px width overlap
# on only 60% of each, giving IoU 0.43 -- under any sane NMS threshold, yet
# plainly the same object. Sweeping it against the ground truth, every value
# from 0.9 down to 0.4 wrongly suppresses the SAME 3 pairs, all
# droplet-inside-droplet (accidental double-labels). So lowering it costs
# nothing real -- genuine small-object-on-large-object pairs are protected by
# CONTAIN_MIN_RATIO, not by this.
CONTAIN_FRAC = 0.5
CONTAIN_MIN_RATIO = 0.2
CLASS_NAMES = ["droplet", "filament", "blob"]   # contiguous id order from training


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


# The named production model. A promoted model lives in its own folder as
# <Name>/<Name>.pth + config.yaml, matching the existing Dennis/Dennis.pth
# convention, so the model in use has a stable name that does not change every
# time something is retrained.
PRODUCTION_MODEL = "Eden"


def find_weights(model_dir: Path) -> Path:
    """
    The .pth inside a model folder.

    Accepts both layouts: a promoted model named after its folder
    (Eden/Eden.pth), and a raw training output (training_*/model_best.pth).
    Checking the folder name first means promoting a model is a copy and a
    rename, with no code change.
    """
    for cand in (model_dir / f"{model_dir.name}.pth", model_dir / "model_best.pth"):
        if cand.exists():
            return cand
    sys.exit(f"no weights in {model_dir} -- expected {model_dir.name}.pth or "
             f"model_best.pth")


def default_model_dir() -> Path:
    """
    The production model if one is promoted, else the newest training run.

    Preferring a NAMED folder over "whatever trained most recently" is
    deliberate: the newest training run is also whatever 500-iteration quick
    test someone ran last, and silently scoring with that produces plausible,
    wrong numbers. The resolved folder and its checkpoint iteration are printed
    before inference either way, and --model-dir remains the explicit override.
    """
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --model-dir explicitly.")
    ai = Path(drive) / "Experiments" / "AI"

    promoted = ai / PRODUCTION_MODEL
    if (promoted / f"{PRODUCTION_MODEL}.pth").exists():
        return promoted

    runs = [d for d in ai.glob("training_*") if (d / "model_best.pth").exists()]
    if not runs:
        sys.exit(f"no {PRODUCTION_MODEL}/ and no training_* run with weights "
                 f"under {ai}. Pass --model-dir explicitly.")
    print(f"  (no {PRODUCTION_MODEL}/ found -- falling back to the newest "
          f"training run)")
    return max(runs, key=lambda d: d.name)


def tile_offsets(size: int, tile: int = TILE, min_overlap: int = MIN_OVERLAP):
    """
    Evenly spaced tile origins covering `size`, with at least `min_overlap`
    between neighbours. Returns [0] when the axis is no longer than one tile.
    """
    if size <= tile:
        return [0]
    n = ceil((size - tile) / (tile - min_overlap)) + 1
    step = (size - tile) / (n - 1)
    return [int(round(i * step)) for i in range(n)]


def auto_device() -> str:
    """
    cuda when a usable CUDA GPU is actually present, else cpu.

    Deliberately tests for the GPU rather than branching on the operating
    system: "Windows" is not the same claim as "a working CUDA install", and
    the failure mode of guessing wrong is a crash three hours into a run or,
    worse, a silent fall back to CPU nobody notices until the timing looks odd.
    MPS is not selected automatically -- detectron2's support for it is patchy
    and a wrong answer is worse than a slow one. Pass --device mps to try it.
    """
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def build_predictor(model_dir: Path, score_thresh: float, device: str):
    from detectron2.config import get_cfg
    from detectron2.engine import DefaultPredictor

    cfg_path = model_dir / "config.yaml"
    if not cfg_path.exists():
        sys.exit(f"no config.yaml in {model_dir}. It must travel with the weights "
                 f"-- it pins the anchor layout and the 800 px input, and "
                 f"rebuilding it by hand silently mismatches the anchors.")
    cfg = get_cfg()
    cfg.merge_from_file(str(cfg_path))
    cfg.MODEL.WEIGHTS = str(find_weights(model_dir))
    cfg.MODEL.DEVICE = device
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = score_thresh
    if cfg.INPUT.MIN_SIZE_TEST != TILE or cfg.INPUT.MAX_SIZE_TEST != TILE:
        sys.exit(f"config.yaml expects {cfg.INPUT.MIN_SIZE_TEST}/{cfg.INPUT.MAX_SIZE_TEST} "
                 f"px input but this tiler emits {TILE} px tiles. Refusing to rescale.")
    return DefaultPredictor(cfg)


def to_bgr(view: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(view, cv2.COLOR_GRAY2BGR) if view.ndim == 2 else view


def pad_to_tile(img: np.ndarray, tile: int = TILE):
    """Frames smaller than one tile get a background-matched border, never a rescale."""
    h, w = img.shape[:2]
    if h >= tile and w >= tile:
        return img, (0, 0)
    fill = int(np.median(img))
    out = np.full((max(h, tile), max(w, tile)) + img.shape[2:], fill, dtype=img.dtype)
    out[:h, :w] = img
    return out, (0, 0)


def detect_frame(predictor, view: np.ndarray, retile_truncated: bool = True):
    """
    Run the model over one full frame. Returns a list of dicts in FRAME
    coordinates: {bbox_xyxy, score, category, mask (bool HxW), truncated}.
    """
    import torch

    padded, _ = pad_to_tile(view)
    H, W = padded.shape[:2]
    fh, fw = view.shape[:2]
    bgr = to_bgr(padded)

    dets = []
    n_tiles = 0
    for y0 in tile_offsets(H):
        for x0 in tile_offsets(W):
            tile = bgr[y0:y0 + TILE, x0:x0 + TILE]
            out = predictor(tile)["instances"].to("cpu")
            n_tiles += 1
            dets.extend(_collect(out, x0, y0, fw, fh))

    merged = _merge(dets)

    if retile_truncated:
        extra, n_extra = _rescue_truncated(predictor, bgr, merged, fw, fh)
        n_tiles += n_extra
        if extra:
            merged = _merge(merged + extra)
    return merged, n_tiles


def _full_mask(d) -> np.ndarray:
    """Materialise a detection's frame-sized boolean mask from its stored crop.

    Only call this where a frame-sized array is genuinely required -- RLE
    encoding for the output JSON, and contour drawing for previews. Everything
    else (areas, IoU, boxes) works on the crop directly, which is the whole
    point of storing it that way.
    """
    fh, fw = d["shape"]
    full = np.zeros((fh, fw), dtype=bool)
    mh, mw = d["m"].shape
    full[d["my"]:d["my"] + mh, d["mx"]:d["mx"] + mw] = d["m"]
    return full


def _collect(inst, x0, y0, fw, fh):
    """Tile-local instances -> frame coordinates, flagging tile-edge truncation.

    Each detection's mask is stored as the smallest crop that contains it plus
    the crop's frame offset, NOT as a frame-sized array.

    That used to be a `np.zeros((fh, fw))` per detection -- 4.1 MB for a blob
    40 px across -- and every later step then scanned all 4.1 M pixels to reach
    the few hundred that mattered. Profiled on frame_0056 (391 detections):
    _collect 25.9 s and _merge 31.9 s against 3.9 s for the actual model, with
    1.6 GB of masks resident. The crop carries identical pixels, so areas,
    boxes, IoU and the emitted RLE are all unchanged -- only the storage is.
    """
    out = []
    if len(inst) == 0:
        return out
    boxes = inst.pred_boxes.tensor.numpy()
    scores = inst.scores.numpy()
    classes = inst.pred_classes.numpy()
    masks = inst.pred_masks.numpy()

    for b, s, c, m in zip(boxes, scores, classes, masks):
        x1, y1, x2, y2 = b
        # A tile edge only truncates when it is NOT also the frame edge.
        truncated = (
            (x1 <= EDGE_MARGIN and x0 > 0)
            or (y1 <= EDGE_MARGIN and y0 > 0)
            or (x2 >= TILE - EDGE_MARGIN and x0 + TILE < fw)
            or (y2 >= TILE - EDGE_MARGIN and y0 + TILE < fh)
        )
        mh = min(TILE, fh - y0)
        mw = min(TILE, fw - x0)
        if mh <= 0 or mw <= 0:
            continue
        # Clip to the frame exactly as the old full-frame assignment did.
        sub = m[:mh, :mw]
        if not sub.any():
            continue
        # Tighten to the blob's own bounds. np.where over <=800x800 rather than
        # the whole frame, and the resulting box is identical: the old code took
        # min/max over frame coordinates, which are these plus the tile origin.
        ys, xs = np.where(sub)
        ry0, ry1 = int(ys.min()), int(ys.max()) + 1
        rx0, rx1 = int(xs.min()), int(xs.max()) + 1
        crop = np.ascontiguousarray(sub[ry0:ry1, rx0:rx1])
        out.append({
            "bbox_xyxy": [float(x0 + rx0), float(y0 + ry0),
                          float(x0 + rx1), float(y0 + ry1)],
            "score": float(s),
            "category": int(c),
            "m": crop,
            "mx": x0 + rx0,
            "my": y0 + ry0,
            "shape": (fh, fw),
            "area": int(crop.sum()),
            "truncated": bool(truncated),
        })
    return out


def _crop_iou(a, b, area_a, area_b) -> float:
    """Mask IoU between two crop-backed detections.

    Identical arithmetic to pycocotools' iou() with iscrowd=0 --
    intersection / (area_a + area_b - intersection) -- but the intersection is
    counted only over the rectangle where the two crops actually overlap
    instead of over the whole frame. Both counts are exact integers, so the
    division yields the same double the RLE path produced.
    """
    ah, aw = a["m"].shape
    bh, bw = b["m"].shape
    ix0 = max(a["mx"], b["mx"])
    iy0 = max(a["my"], b["my"])
    ix1 = min(a["mx"] + aw, b["mx"] + bw)
    iy1 = min(a["my"] + ah, b["my"] + bh)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    sa = a["m"][iy0 - a["my"]:iy1 - a["my"], ix0 - a["mx"]:ix1 - a["mx"]]
    sb = b["m"][iy0 - b["my"]:iy1 - b["my"], ix0 - b["mx"]:ix1 - b["mx"]]
    inter = float(np.count_nonzero(sa & sb))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _merge(dets):
    """
    CROSS-CLASS NMS on MASK IoU, preferring untruncated detections.

    Two deliberate departures from the COCO default, both measured as necessary
    on the 15-frame benchmark (88 duplicate pairs at score >= 0.3):

    1. **Cross-class, not per-class.** COCO's class-aware NMS never compares a
       droplet against a filament, so both survive on the same object -- 58 of
       the 88 duplicates were cross-class (droplet+filament 24, blob+filament
       21, blob+droplet 13). A physical object has exactly one class, so the
       lower-scoring label is a false positive and must be suppressed.

    2. **Mask IoU, not box IoU.** A long diagonal filament's box is mostly empty
       space, so box overlap says almost nothing about whether two detections
       are the same object: two detections sharing a box but covering different
       halves of a thread read as duplicates, while genuinely nested detections
       can read as distinct. Mask IoU asks the question directly. It also keeps
       a small droplet lying on top of a large filament, which is a real
       configuration in this data -- their masks barely overlap even though
       their boxes do.

    Untruncated detections get +1.0 on the ordering key (scores are in [0,1]),
    so a whole object always outranks a seam fragment of the same object.
    """
    if not dets:
        return []
    order = sorted(range(len(dets)),
                   key=lambda i: -(dets[i]["score"] + (0.0 if dets[i]["truncated"] else 1.0)))

    areas = np.array([float(d["area"]) for d in dets])
    # Boxes as arrays so the overlap prefilter below is one vectorised test
    # rather than a Python loop over every pair.
    bx = np.array([d["bbox_xyxy"] for d in dets], dtype=np.float64)

    keep = []
    suppressed = set()
    for i in order:
        if i in suppressed:
            continue
        keep.append(i)
        rest = [j for j in order if j not in suppressed and j != i and j not in keep]
        if not rest:
            continue
        # Masks can only overlap where their BOXES overlap, so discard the
        # non-overlapping majority with one cheap vectorised test and compute
        # true mask IoU on the survivors only. Exact, not approximate: a pair
        # whose boxes miss has zero mask intersection by construction.
        rj = np.array(rest)
        bi = bx[i]
        cand = rj[(bx[rj, 0] < bi[2]) & (bx[rj, 2] > bi[0]) &
                  (bx[rj, 1] < bi[3]) & (bx[rj, 3] > bi[1])]
        if cand.size == 0:
            continue
        ious = [_crop_iou(dets[i], dets[j], areas[i], areas[j]) for j in cand]
        for j, iou in zip(cand, ious):
            j = int(j)
            if iou >= NMS_IOU:
                suppressed.add(j)
                continue
            # CONTAINMENT: a partial detection of a big object has LOW IoU with
            # the whole (upper half of a filament vs the filament: IoU ~0.4) so
            # plain NMS keeps both. Containment catches it -- but it must not
            # also kill a small droplet genuinely lying on a large filament,
            # which is a real configuration here.
            #
            # Size ratio separates the two cleanly. In the hand-labelled ground
            # truth only 11 of 2458 annotations are >=0.8 contained in another,
            # and every genuine one is a tiny object on a big one (ratios 1:20
            # to 1:240, i.e. <=0.05). A duplicate partial is a large fraction of
            # its container. So suppress only when both hold.
            if iou <= 0:
                continue
            inter = iou * (areas[i] + areas[j]) / (1.0 + iou)
            contained = inter / max(areas[j], 1.0)
            if contained >= CONTAIN_FRAC and areas[j] / max(areas[i], 1.0) >= CONTAIN_MIN_RATIO:
                suppressed.add(j)
    return [dets[i] for i in sorted(keep)]


def _rescue_truncated(predictor, bgr, merged, fw, fh):
    """
    Second pass: re-tile centred on each still-truncated detection, so an object
    cut by a seam gets one more chance to be seen whole. Cannot help an object
    larger than the tile -- nothing can.
    """
    extra, n = [], 0
    for d in merged:
        if not d["truncated"]:
            continue
        x1, y1, x2, y2 = d["bbox_xyxy"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        x0 = int(np.clip(cx - TILE / 2, 0, max(fw - TILE, 0)))
        y0 = int(np.clip(cy - TILE / 2, 0, max(fh - TILE, 0)))
        tile = bgr[y0:y0 + TILE, x0:x0 + TILE]
        if tile.shape[0] < TILE or tile.shape[1] < TILE:
            continue
        out = predictor(tile)["instances"].to("cpu")
        n += 1
        extra.extend(_collect(out, x0, y0, fw, fh))
    return extra, n


def to_coco(dets, image_id):
    from pycocotools import mask as mask_util
    out = []
    for d in dets:
        # The emitted RLE is frame-sized by definition, so this is the one place
        # the full array is unavoidable -- but it now runs once per SURVIVING
        # detection instead of once per raw tile detection in _merge and again
        # here, which on frame_0056 is 391 encodes rather than 2297.
        rle = mask_util.encode(np.asfortranarray(_full_mask(d).astype(np.uint8)))
        rle["counts"] = rle["counts"].decode("ascii")
        x1, y1, x2, y2 = d["bbox_xyxy"]
        out.append({
            "image_id": image_id,
            "category_id": d["category"] + 1,      # contiguous 0-2 -> COCO 1-3
            "segmentation": rle,
            "bbox": [x1, y1, x2 - x1, y2 - y1],
            "score": d["score"],
            "area": float(d["area"]),
            "truncated": d["truncated"],
        })
    return out


def preview(view, dets, path, score_thresh, show_tiles=True):
    canvas = to_bgr(view).copy()
    colours = {0: (0, 200, 0), 1: (255, 130, 0), 2: (0, 180, 255)}
    h, w = view.shape[:2]

    # Tile boundaries first, so detections draw over them. Every tile edge is
    # drawn, so the overlap bands show up as pairs of close lines -- that band
    # is where an object can be seen whole by the neighbouring tile.
    if show_tiles:
        faint = (205, 205, 205)
        for x0 in tile_offsets(w):
            for x in (x0, min(x0 + TILE, w) - 1):
                cv2.line(canvas, (x, 0), (x, h - 1), faint, 1)
        for y0 in tile_offsets(h):
            for y in (y0, min(y0 + TILE, h) - 1):
                cv2.line(canvas, (0, y), (w - 1, y), faint, 1)

    shown = 0
    for d in dets:
        if d["score"] < score_thresh:
            continue
        shown += 1
        col = colours[d["category"]]
        # Contours in FRAME coordinates: find them on the crop (cheap) and shift
        # by the crop origin, rather than rebuilding a frame-sized array.
        cnts, _ = cv2.findContours(d["m"].astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        cnts = [c + np.array([[d["mx"], d["my"]]], dtype=c.dtype) for c in cnts]
        cv2.drawContours(canvas, cnts, -1, col, 1)
        if d["truncated"]:
            x1, y1, x2, y2 = [int(v) for v in d["bbox_xyxy"]]
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 0, 255), 1)

    nx, ny = len(tile_offsets(w)), len(tile_offsets(h))
    ov = TILE - (tile_offsets(w)[1] - tile_offsets(w)[0]) if nx > 1 else 0
    y = 34
    for txt, col in [(f"shown at score >= {score_thresh}: {shown}", (0, 0, 0)),
                     ("droplet", colours[0]), ("filament", colours[1]),
                     ("blob", colours[2]),
                     ("red box = truncated at a seam", (0, 0, 255)),
                     (f"grey lines = {nx}x{ny} tile grid, {ov} px overlap", (150, 150, 150))]:
        cv2.putText(canvas, txt, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
        y += 32
    cv2.imwrite(str(path), canvas)


def main():
    ap = argparse.ArgumentParser(description="Tiled inference over full frames")
    ap.add_argument("--frame", help="one validation frame stem")
    ap.add_argument("--all", action="store_true", help="every validation frame")
    ap.add_argument("--model-dir", type=Path, default=None)
    ap.add_argument("--score-thresh", type=float, default=0.05,
                    help="model output threshold. Keep LOW (0.05) for AP scoring -- "
                         "AP integrates over recall and needs the low-confidence "
                         "tail. Choose a separate, higher operating point for "
                         "measurement from the PR curve.")
    ap.add_argument("--preview-thresh", type=float, default=0.5,
                    help="score threshold used only for the preview image")
    ap.add_argument("--no-retile", action="store_true",
                    help="skip the second pass over seam-truncated detections")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="write COCO predictions JSON")
    ap.add_argument("--device", default=None,
                    help="cuda / cpu / mps. Default: auto -- cuda when a working "
                         "CUDA GPU is present (the Windows training machine), cpu "
                         "otherwise (the Mac). Pass it explicitly to force one, e.g. "
                         "--device cpu on Windows to benchmark against CPU.")
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--val-dir", default="06_validation",
                    help="which set to run on, relative to the Real_Data root, e.g. "
                         "09_experiments/02_Chosen_Frame. Needs the same layout: "
                         "frames/8bit/ and instances.json.")
    ap.add_argument("--tag", default=None,
                    help="name for preview files, e.g. 'v3' -> <frame>_v3pred.png. "
                         "Defaults to the --out stem ('v3_predictions.json' -> 'v3'), "
                         "else the model directory name.")
    args = ap.parse_args()

    root = args.root or real_data_root()
    val = root / args.val_dir
    model_dir = args.model_dir or default_model_dir()
    device = args.device or auto_device()
    if args.device is None:
        print(f"device: {device}  (auto-detected"
              f"{'; no CUDA GPU found' if device == 'cpu' else ''})")

    # Preview filenames used to be hardcoded to "_v2pred.png", so scoring any
    # other model overwrote v2's previews with someone else's detections under
    # v2's name. The tag makes the file say which model drew it.
    if args.tag:
        tag = args.tag
    elif args.out:
        tag = args.out.stem.replace("_predictions", "")
    else:
        tag = model_dir.name

    gt = json.loads((val / "instances.json").read_text(encoding="utf-8"))
    id_by_name = {im["file_name"]: im["id"] for im in gt["images"]}

    if args.all:
        stems = sorted(p.stem for p in list_files(val / "frames" / "8bit", "*.png"))
    elif args.frame:
        stems = [args.frame]
    else:
        sys.exit("give --frame <stem> or --all")

    # Say which weights these numbers came from, and at what iteration -- a
    # 500-iteration quick test is the newest run too, and would otherwise be
    # indistinguishable from the real one in the output.
    # Promoted models keep this as <Name>_summary.json; raw training outputs as
    # model_best.json. Check both so the provenance line never goes silent.
    best_meta = next((p for p in (model_dir / f"{model_dir.name}_summary.json",
                                  model_dir / "model_best.json") if p.exists()),
                     model_dir / "model_best.json")
    iter_note = ""
    if best_meta.exists():
        try:
            _b = json.loads(best_meta.read_text(encoding="utf-8"))
            iter_note = (f"   (best checkpoint: iter {_b.get('iteration')}, "
                         f"segm AP {_b.get('segm_AP', float('nan')):.1f} on composites)")
        except (ValueError, TypeError):
            pass
    print(f"model:  {model_dir.name}{iter_note}")
    print(f"preview tag: {tag}")
    t0 = time.time()
    predictor = build_predictor(model_dir, args.score_thresh, device)
    print(f"loaded in {time.time() - t0:.1f}s on {device}  "
          f"(once, reused for every tile)\n")

    all_preds = []
    for stem in stems:
        view = cv2.imread(str(val / "frames" / "8bit" / f"{stem}.png"), cv2.IMREAD_UNCHANGED)
        if view is None:
            print(f"{stem}: no 8-bit frame, skipped")
            continue
        h, w = view.shape[:2]
        t0 = time.time()
        dets, n_tiles = detect_frame(predictor, view, retile_truncated=not args.no_retile)
        dt = time.time() - t0

        n_trunc = sum(d["truncated"] for d in dets)
        strong = sum(d["score"] >= args.preview_thresh for d in dets)
        per_class = {CLASS_NAMES[c]: sum(1 for d in dets if d["category"] == c)
                     for c in range(3)}
        print(f"{stem:24s} {w}x{h}  {n_tiles:2d} tiles  {dt:6.1f}s  "
              f"det {len(dets):4d} (>={args.preview_thresh}: {strong:3d})  "
              f"truncated {n_trunc:3d}   {per_class}")

        if args.preview:
            out_dir = val / "review_images"
            out_dir.mkdir(parents=True, exist_ok=True)
            preview(view, dets, out_dir / f"{stem}_{tag}pred.png", args.preview_thresh)

        image_id = id_by_name.get(f"{stem}.png")
        if image_id is not None:
            all_preds.extend(to_coco(dets, image_id))

    if args.out:
        args.out.write_text(json.dumps(all_preds), encoding="utf-8")
        print(f"\nwritten: {args.out}  ({len(all_preds)} detections)")


if __name__ == "__main__":
    main()
