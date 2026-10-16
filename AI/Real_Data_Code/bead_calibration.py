#!/usr/bin/env python3
"""
bead_calibration.py -- size calibration of the shadowgraph sizer from glass beads of certified size, and
later the PS20 dot reticle (2026-10-14; procedure docs/BEAD_CALIBRATION.md).

Captures are GUI_Clean runs found by their Notes (run_summary.xlsx):

    BEAD mix z-1.25     the mixed sandwich (all sizes), 1.25 mm before best focus   (through focus)
    BEAD mix z0 p3      the mixed sandwich at best focus, third patch                 (at focus)
    BEAD 56.28 z0 p1    a single-size sandwich at its best focus                      (at focus)
    BEAD 56.28 bg       a patch with no beads (a cross-check of the background)
    BEAD fall 56.28     beads poured through the field: read from the AI pipeline's droplet_sizes.csv
    RETICLE z-1.25 / RETICLE array c|tl|tr|bl|br / RETICLE bg     the reticle, when it arrives

    BEAD blank bg.cine  a loose .cine (recorded in PCC) whose FILE NAME reads as Notes: here an empty field,
                        the dust map (anything dark in it is not a bead, wherever it turns up)

Each capture is averaged over its frames. The beads do not move, so a temporal median would contain them:
the background is estimated from the averaged frame itself (a large-window median; a bead is at most ~16 px
across) and T = I / background. Beads are found at best focus and each is followed through every depth at
the same place, so its identity (certified size) carries through.

ONLY THE SPARSE PART OF EACH PHOTO IS USED (1.1.0, 2026-10-15; the real slides: faint specks and fibres
everywhere, the coverslip edge, and crowded streaks of small beads). A bead counts only if it is DARK (its
darkest pixel T < 0.35; specks and debris sit at 0.35-0.9 and are ignored, even as neighbours), ROUND (a touching pair is
not) and ISOLATED (no other dark object within one of its diameters), and only inside the photo's sparse
tiles (128 px; dark objects cover <= 3 % of the area around the tile). The area used is boxed on a PNG written
into the capture's own folder (shadowgraph/analysis/bead_calibration/bead_region.png; Ben, 2026-10-15) and
copied to <out>/regions/. Nothing else is written into the capture folders.

Per bead and depth it records:
  * what THE CURRENT SIZER makes of it (measure_run.measure_droplet: robust core, in focus if core <= 0.70,
    half-max area, the 2.2.0 sharpness rule) -- with a T < 0.95 component standing in for the AI's mask;
    below 40 um the real pipeline keeps the AI mask's area, so there the falling-bead test is the real check;
  * the diameter at every relative grey level l (level = T_min + l (1 - T_min)), holes filled and not;
  * whether the half-max region is a RING (a transparent sphere's bright centre);
  * Blaisot & Yon (2005, Exp. Fluids 39:977-994) quantities: contrast C = (1 - T_min)/(1 + T_min), the
    radii at l = 0.25 / 0.61 / 0.77, the blur width chi = sqrt(2) dr / p_r(C0) and their contrast-corrected
    size 2 r_0.61 p_0.61(C0). p_r and p_l are computed here from their Gaussian-PSF disc model (Eq. 5).

It reports, per size: the current sizer's bias against the certificate at focus, the level l* that gives
the certified size, rings, 2.2.0 rejections, the depth range over which the current rule counts the bead as
in focus (the 1/DOF(d) weight), the range over which its size holds within 5 %, and chi(z) = chi0 + k|z - zf|.
Nothing in the pipeline changes (a new sizer is a separate step).

    python bead_calibration.py "<LaCie>/Calibration/Imaging Work/2026/10/15" --out "<...>/analysis/2026-10-15"
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blur  # noqa: E402  (the measurement itself, shared with measure_run's sizer 3.0.0)
import measure_run as mr  # noqa: E402
import optics  # noqa: E402
from blur import BLAISOT_LEVELS, DETECT_T, RECENTRE_PX, UPSAMPLE, blaisot_model, c0_from, p_level, p_width  # noqa: E402,F401

VERSION = "1.1.0"
UM_PER_PX = mr.UM_PER_PX
LEVELS = tuple(round(float(x), 2) for x in np.arange(0.10, 0.901, 0.05))
MIN_AREA_PX = 4
EDGE_PX = 3                   # a bead this close to the frame edge is not measured
BG_DOWNSAMPLE = 4
BG_WINDOW_PX = 101            # >> the largest bead (155.8 um = 16 px), even blurred
DARK_T = 0.35                 # a bead's darkest pixel at focus (light smoothing): beads 0.1-0.35, debris 0.35-0.9
ROUND_MAX = 1.40              # major / minor axis of the core (half-max part); a touching pair is ~2
GAP = 1.0                     # isolated: no other dark object within GAP x its diameter + 2 px, edge to edge
TILE_PX = 128                 # the sparse region is made of tiles this size (1.28 mm)
SPARSE_MAX = 0.03             # a tile is sparse if dark objects cover <= 3 % around it (random beads: ~60 % isolated)
MIN_TILES = 12                # if fewer tiles are that sparse, the MIN_TILES sparsest are used
MAX_FRAMES = 40                # ~0.5 s a frame from the LaCie; 40 frames cut the noise ~6x
DUST_PX = 4                    # a 'bead' this close to something seen in a bead-free capture is dust
FOCUS_MAX = 0.70              # measure_run's default --focus-max
SIZE_STABLE = 0.05            # "size holds" = within 5 % of its value at focus
MATCH_MARGIN = 0.35           # identity: nearest size by at least this share of the log-gap to the next


# ---- captures --------------------------------------------------------------------------------------------

@dataclass
class Capture:
    run: Path
    notes: str
    target: str               # "bead" | "reticle"
    slide: str                # "mix", "56.28", "reticle"
    kind: str                 # "z" (through focus) | "focus" | "bg" | "fall" | "array"
    z_mm: float | None
    pos: str


NOTE_RE = re.compile(r"^\s*(BEAD|RETICLE)\b\s*(.*)$", re.I)


def parse_notes(notes) -> tuple | None:
    """(target, slide, kind, z_mm, pos) from a capture's Notes, or None if it is not a calibration capture."""
    m = NOTE_RE.match(str(notes or ""))
    if not m:
        return None
    target = "bead" if m.group(1).upper() == "BEAD" else "reticle"
    toks = m.group(2).split()
    if target == "bead":
        if not toks:
            return None
        slide, rest = toks[0].lower(), toks[1:]
        if slide == "fall":
            return ("bead", rest[0] if rest else "", "fall", None, "")
    else:
        slide, rest = "reticle", toks
    kind, z, pos = "focus", None, ""
    for t in rest:
        tl = t.lower()
        if tl == "bg":
            kind = "bg"
        elif tl == "array":
            kind = "array"
        elif tl == "z0":
            z = 0.0
        elif re.fullmatch(r"z[+-]?\d+(\.\d+)?", tl):
            z, kind = float(tl[1:]), "z"
        elif re.fullmatch(r"p\d+", tl) or tl in ("c", "tl", "tr", "bl", "br"):
            pos = tl
    if kind == "focus" and z is None:
        z = 0.0
    return (target, slide, kind, z, pos)


def read_meta(xlsx: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    try:
        if "Metadata" not in wb.sheetnames:
            return {}
        return {str(r[0]).strip(): r[1] for r in wb["Metadata"].iter_rows(min_row=2, values_only=True)
                if r and r[0] is not None}
    finally:
        wb.close()


def _hidden(q: Path, root: Path) -> bool:
    """Below the folder given, a name starting with '.' or '_' (archives, app caches, macOS '._' files)."""
    return any(s.startswith((".", "_")) for s in q.relative_to(root).parts)


def find_captures(paths) -> list[Capture]:
    """Run folders whose Notes read as a capture, then loose .cine files (PCC) whose file name does, unless
    run_ai_where has already made a run folder for that file (then the run folder is the capture)."""
    out = []
    for p in paths:
        p = Path(p)
        is_run = (p / "run_summary.xlsx").is_file()
        summaries = [p / "run_summary.xlsx"] if is_run else \
            sorted(q for q in p.rglob("run_summary.xlsx") if not _hidden(q, p))
        for x in summaries:
            notes = read_meta(x).get("Notes")
            parsed = parse_notes(notes)
            if parsed:
                out.append(Capture(x.parent, str(notes).strip(), *parsed))
        if is_run or not p.is_dir():
            continue
        for c in sorted(p.rglob("*.cine")):
            if "CINE" in c.relative_to(p).parts[:-1] or _hidden(c, p) or \
                    (c.parent / c.stem / "run_summary.xlsx").is_file():
                continue                          # a run's own recording, or one with its run folder already
            notes = c.stem.replace("_", " ").strip()
            parsed = parse_notes(notes)
            if parsed:
                out.append(Capture(c, notes, *parsed))
    return out


# ---- frames and transmission ------------------------------------------------------------------------------

def average_frames(run: Path, max_frames: int = MAX_FRAMES) -> np.ndarray:
    """The capture averaged over up to max_frames frames, spread through it: from its .cine (or `run` IS a
    loose .cine), else from extracted 16-bit TIFFs (shadowgraph/raw/frames/16bit)."""
    run = Path(run)
    cines = [run] if run.suffix.lower() == ".cine" else sorted((run / "shadowgraph" / "raw" / "CINE").glob("*.cine"))
    if cines:
        from cine_reader import Cine
        acc, n = None, 0
        with Cine(cines[0]) as cine:
            nums = list(range(cine.first_frame_number, cine.last_frame_number + 1))
            for k in nums[::max(1, len(nums) // max_frames)][:max_frames]:
                cine.load_frame(k)
                f = np.asarray(cine.frame, dtype=np.float64)
                acc = f if acc is None else acc + f
                n += 1
        return (acc / n).astype(np.float32)
    tiffs = sorted((run / "shadowgraph" / "raw" / "frames" / "16bit").glob("*.tif*"))
    if not tiffs:
        raise FileNotFoundError(f"{run.name}: no .cine and no extracted 16-bit frames")
    tiffs = tiffs[::max(1, len(tiffs) // max_frames)][:max_frames]
    acc = None
    for t in tiffs:
        f = cv2.imread(str(t), cv2.IMREAD_UNCHANGED).astype(np.float64)
        acc = f if acc is None else acc + f
    return (acc / len(tiffs)).astype(np.float32)


BG_SIGMA_PX = 12.0            # the second pass's local average (a backlight gradient biases it < 0.5 %)
BG_MASK_T = 0.97              # pixels darker than this (after the first pass) are bead, not backlight
BG_MASK_GROW_PX = 6


def estimate_background(img: np.ndarray, window_px: int = BG_WINDOW_PX, down: int = BG_DOWNSAMPLE) -> np.ndarray:
    """The backlight without the beads, in two passes. (1) A median over window_px on a down-sampled copy:
    sparse beads, each far smaller than the window, do not move a median, but on a backlight gradient a
    101 px median is ~1-2 % off near the frame edges. (2) The beads found against (1) are masked out and the
    backlight is the local average of what is left (a normalised Gaussian, sigma 12 px), which follows the
    gradient; where too little is left (inside a large blurred bead) pass (1) is kept."""
    from scipy import ndimage
    h, w = img.shape
    small = cv2.resize(img, (max(1, w // down), max(1, h // down)), interpolation=cv2.INTER_AREA)
    k = max(3, int(round(window_px / down)) | 1)
    bg0 = cv2.resize(ndimage.median_filter(small, size=k, mode="reflect"), (w, h),
                     interpolation=cv2.INTER_LINEAR).astype(np.float32)
    bead = (img / np.maximum(bg0, 1.0)) < BG_MASK_T
    g = 2 * BG_MASK_GROW_PX + 1
    keep = (~cv2.dilate(bead.astype(np.uint8), np.ones((g, g), np.uint8)).astype(bool)).astype(np.float32)
    num = cv2.GaussianBlur(img.astype(np.float32) * keep, (0, 0), BG_SIGMA_PX, borderType=cv2.BORDER_REFLECT)
    den = cv2.GaussianBlur(keep, (0, 0), BG_SIGMA_PX, borderType=cv2.BORDER_REFLECT)
    return np.where(den > 0.05, num / np.maximum(den, 1e-6), bg0).astype(np.float32)


def transmission(img: np.ndarray) -> np.ndarray:
    return img / np.maximum(estimate_background(img), 1.0)


# ---- the Blaisot & Yon model: blur.py (blaisot_model, c0_from, p_level, p_width; imported above) ------------


# ---- detection and measurement ---------------------------------------------------------------------------

def _dark_objects(T: np.ndarray):
    """The dark matter of a photo. Components of T < 0.95 (as extract_candidates finds candidates) whose darkest
    pixel is below DARK_T are DARK; faint ones (specks on the slide or the window, dried debris, fibre halos) are
    not beads and do not count as anyone's neighbour. Each dark component's CORE is its half-max part
    (T < T_min + 0.5 (1 - T_min)): the bead itself, without the faint debris its blurred edge may run into; two
    touching beads give two cores, or one long one. Returns (smoothed T, component labels, dark per component,
    core labels, number of cores, core -> its component)."""
    from scipy import ndimage
    Ts = cv2.GaussianBlur(T, (0, 0), 0.5)
    n, lab = cv2.connectedComponents((Ts < DETECT_T).astype(np.uint8), connectivity=8)
    tmin = np.asarray(ndimage.minimum(Ts, lab, np.arange(n)), float)
    area = np.bincount(lab.ravel(), minlength=n)
    dark = (tmin < DARK_T) & (area >= MIN_AREA_PX)
    dark[0] = False
    level = np.where(dark, tmin + 0.5 * (1.0 - tmin), -1.0)
    core = dark[lab] & (Ts < level[lab])
    nc, clab = cv2.connectedComponents(core.astype(np.uint8), connectivity=8)
    parent = np.zeros(nc, int)
    parent[clab.ravel()] = lab.ravel()
    parent[0] = 0
    return Ts, lab, dark, clab, nc, parent


def _axis_ratio(mask: np.ndarray) -> float:
    """Major / minor axis of a region's second moments (plus each pixel's own 1/12 variance, so a 2-px blob is
    not called elongated)."""
    yy, xx = np.nonzero(mask)
    if yy.size == 0:
        return float("inf")
    cxx = xx.var() + 1 / 12
    cyy = yy.var() + 1 / 12
    cxy = ((xx - xx.mean()) * (yy - yy.mean())).mean()
    ev = np.linalg.eigvalsh(np.array([[cxx, cxy], [cxy, cyy]]))
    return float(math.sqrt(ev[1] / max(ev[0], 1e-9)))


CORE_MIN_PX = 3               # a core smaller than this is an obstacle, never a bead


def objects(T: np.ndarray) -> list[dict]:
    """Every dark core, with why it is not a usable bead ('' = usable): 'edge' (at the frame edge), 'not round'
    (a touching pair, a fibre: axis ratio > ROUND_MAX), 'crowded' (other dark matter -- another core, or another
    dark component -- within GAP of its own diameters, edge to edge). Sizes and shapes are the core's."""
    from scipy import ndimage
    Ts, lab, dark, clab, nc, parent = _dark_objects(T)
    H, W = T.shape
    out = []
    if nc < 2:
        return out
    boxes = ndimage.find_objects(clab)
    for k in range(1, nc):
        sl = boxes[k - 1]
        if sl is None:
            continue
        y, x = sl[0].start, sl[1].start
        h, w = sl[0].stop - y, sl[1].stop - x
        own = clab[sl] == k
        a = int(own.sum())
        if a < CORE_MIN_PX:
            continue
        yy, xx = np.nonzero(own)
        d = 2.0 * math.sqrt(a / math.pi)
        o = {"cx": float(x + xx.mean()), "cy": float(y + yy.mean()), "area": a, "d_px": d,
             "t_min": round(float(Ts[sl][own].min()), 4), "why": ""}
        if x <= EDGE_PX or y <= EDGE_PX or x + w >= W - EDGE_PX or y + h >= H - EDGE_PX:
            o["why"] = "edge"
            out.append(o)
            continue
        o["axis_ratio"] = round(_axis_ratio(own), 3)
        need = GAP * d + 2
        m = int(math.ceil(need)) + 1
        x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(W, x + w + m), min(H, y + h + m)
        cw, lw = clab[y0:y1, x0:x1], lab[y0:y1, x0:x1]
        other = ((cw > 0) & (cw != k)) | (dark[lw] & (lw != parent[k]))
        gap = float("inf")
        if other.any():
            dist = cv2.distanceTransform((cw != k).astype(np.uint8), cv2.DIST_L2, 3)   # to its own nearest pixel
            gap = float(dist[other].min()) - 1.0
        o["gap_px"] = round(gap, 2) if np.isfinite(gap) else None
        if o["axis_ratio"] > ROUND_MAX:
            o["why"] = "not round"
        elif gap < need:
            o["why"] = "crowded"
        out.append(o)
    return out


def find_beads(T: np.ndarray) -> list[dict]:
    """The usable beads: dark, round, isolated, not touching the frame edge."""
    return [o for o in objects(T) if not o["why"]]


def sparse_region(T: np.ndarray) -> tuple[np.ndarray, dict]:
    """The part of the photo whose beads can be measured: the TILE_PX tiles where dark cores cover at most
    SPARSE_MAX of the area around the tile (a box twice the tile, so a tile's share is not decided by one or
    two large beads); if fewer than MIN_TILES are that sparse, the MIN_TILES sparsest. Returns the region as a
    boolean mask and a summary."""
    _Ts, _lab, _dark, clab, _nc, _parent = _dark_objects(T)
    foot = (clab > 0).astype(np.float32)                 # the cores: the beads (and dark dirt) themselves
    H, W = T.shape
    ny, nx = -(-H // TILE_PX), -(-W // TILE_PX)
    share = np.zeros((ny, nx))
    for j in range(ny):
        for i in range(nx):
            cy, cx = j * TILE_PX + TILE_PX // 2, i * TILE_PX + TILE_PX // 2
            share[j, i] = foot[max(0, cy - TILE_PX):cy + TILE_PX, max(0, cx - TILE_PX):cx + TILE_PX].mean()
    keep = share <= SPARSE_MAX
    if keep.sum() < min(MIN_TILES, share.size):
        keep = np.zeros_like(keep)
        keep.flat[np.argsort(share, axis=None)[:min(MIN_TILES, share.size)]] = True
    mask = np.kron(keep, np.ones((TILE_PX, TILE_PX), bool))[:H, :W]
    return mask, {"tiles_used": int(keep.sum()), "tiles": int(share.size),
                  "share_of_frame": round(float(mask.mean()), 3),
                  "dark_cover_used": round(float(share[keep].mean()), 4),
                  "dark_cover_all": round(float(foot.mean()), 4),
                  "fallback_sparsest": bool((share <= SPARSE_MAX).sum() < min(MIN_TILES, share.size))}


def _in(region, b) -> bool:
    return region is None or bool(region[min(region.shape[0] - 1, int(round(b["cy"]))),
                                         min(region.shape[1] - 1, int(round(b["cx"])))])


_component_at = blur.component_at


def measure_at(T: np.ndarray, cx: float, cy: float, d_px: float, tau: float | None = None,
               levels=None) -> dict | None:
    """Everything measured for one bead whose centre is near (cx, cy). None if it is too close to the edge.
    `levels` limits the level curve (default: every level in LEVELS; the Blaisot levels and 0.5 always)."""
    from scipy import ndimage
    loc = blur.locate(T, cx, cy, d_px)                 # re-centre on the darkness, cut the window (blur.py)
    if loc is None:
        return None
    Tc, Tsc, m = loc["Tc"], loc["Tsc"], loc["m"]
    row = {"cx": round(loc["cx"], 2), "cy": round(loc["cy"], 2)}
    t_low = float(Tsc.min())
    row["t_min_smoothed"] = round(t_low, 4)
    if not m.any():
        row.update(detected=False, in_focus_current=False)
        return row
    core = float(mr.droplet_core(Tc, m))
    row.update(detected=True, core_t=round(core, 4), contrast=round((1 - core) / (1 + core), 4))

    # -- the current sizer (sizer 2.2.0), a T < 0.95 component standing in for the AI mask --
    ys, xs = np.nonzero(m)
    by, bx = int(ys.min()), int(xs.min())
    bh, bw = int(ys.max()) - by + 1, int(xs.max()) - bx + 1
    md = mr.measure_droplet(Tc, {"area": float(m.sum())}, FOCUS_MAX,
                            crop=(m[by:by + bh, bx:bx + bw], bx, by, bh, bw), sharpness_rule=True)
    fill, conc = mr.sharpness_metrics(Tc, m)
    a_half, _deg, comp = mr.halfmax_area(Tc, m, core)
    ring, centre_t = False, float("nan")
    if comp is not None and comp.any():
        filled = ndimage.binary_fill_holes(comp)
        ring = bool(filled.sum() > comp.sum())
        fy, fx = (int(round(v)) for v in ndimage.center_of_mass(filled))
        centre_t = float(Tc[max(0, fy - 1):fy + 2, max(0, fx - 1):fx + 2].mean())
    row.update(in_focus_current=bool(md["in_focus"]) if md else False,
               d_current_um=round(float(mr.equiv_um(md["area_px"])), 2) if md else float("nan"),
               method=md["method"] if md else "none", reclassified=bool(md["reclassified"]) if md else False,
               fill_ratio=round(float(fill), 4) if np.isfinite(fill) else float("nan"),
               extinction_conc=round(float(conc), 4) if np.isfinite(conc) else float("nan"),
               halfmax_d_um=round(float(mr.equiv_um(a_half)), 2) if a_half else float("nan"),
               ring=ring, centre_t=round(centre_t, 4))

    # -- the level curve on a 4x upsample, the blur width chi and Blaisot's contrast-corrected size (blur.py) --
    row.update(blur.edge_sizes(Tc, m, core, UM_PER_PX, tau, LEVELS if levels is None else levels))
    return row


# ---- identity --------------------------------------------------------------------------------------------

def assign_sizes(measured_um: list[float], sizes: list[float]) -> tuple[list, float]:
    """Each bead's certified size, or None if ambiguous. A common scale k (the edge level's bias) is fitted
    first, so a sizer that reads every bead 20 % small still sorts them correctly."""
    logs = np.log(np.asarray(sizes))
    m = np.log(np.asarray([v for v in measured_um if np.isfinite(v) and v > 0]))
    if not m.size:
        return [None] * len(measured_um), 1.0
    best_k, best_cost = 1.0, np.inf
    for k in np.linspace(0.5, 1.6, 221):
        cost = np.abs(m[:, None] - (logs[None, :] + math.log(k))).min(axis=1).sum()
        if cost < best_cost:
            best_k, best_cost = float(k), cost
    out = []
    for v in measured_um:
        if not (np.isfinite(v) and v > 0):
            out.append(None)
            continue
        dist = np.abs(math.log(v) - (logs + math.log(best_k)))
        order = np.argsort(dist)
        if len(order) > 1:
            gap = abs(logs[order[1]] - logs[order[0]])
            if dist[order[0]] > (0.5 - MATCH_MARGIN / 2) * gap:
                out.append(None)
                continue
        out.append(float(sizes[order[0]]))
    return out, best_k


# ---- analysis --------------------------------------------------------------------------------------------

def load_targets(path: Path | None) -> dict:
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"beads": {"sizes": [{"label": s, "certified_um": float(s)}
                                for s in ("37.36", "56.28", "76.39", "98.1", "155.8")]},
            "reticle": {"dots_um": [39.6, 56.0, 79.2, 112.0, 158.0, 224.0, 317.0],
                        "array": {"dot_um": 250.0, "pitch_um": 500.0}}}


def _slide_sizes(slide: str, target: str, targets: dict) -> list[float]:
    if target == "reticle":
        return [float(v) for v in targets["reticle"]["dots_um"]]
    all_sizes = [float(s["certified_um"]) for s in targets["beads"]["sizes"]]
    if slide == "mix":
        return all_sizes
    v = float(slide)
    return [min(all_sizes, key=lambda s: abs(s - v))]


def dust_positions(T: np.ndarray) -> list[tuple[float, float]]:
    """Every dark object in a bead-free ('bg') capture, crowded or not: specks on the window, the sensor or the
    slide, which stay at the same pixels whatever the beads do (an averaged spray frame shows ~200 of them)."""
    return [(o["cx"], o["cy"]) for o in objects(T)]


def _not_dust(b: dict, dust) -> bool:
    return all(math.hypot(b["cx"] - x, b["cy"] - y) > max(DUST_PX, b["d_px"] / 2) for x, y in dust)


SINGLE_BAND = 0.20            # a single-size slide keeps beads within 20 % of its size's mode (76.39 is 22 % below 98.1)


def _single_size_scale(d: list[float], cert: float) -> float:
    """The measured size the beads of a single-size slide cluster at, as a share of the certified one: the mode
    (the scale with the most beads within 20 %), so dirt that is dark and round does not pull it as a median would."""
    ld = np.log(np.asarray([v for v in d if np.isfinite(v) and v > 0], float))
    if not ld.size:
        return float("nan")
    ks = np.linspace(0.5, 1.6, 221)
    counts = np.array([(np.abs(ld - math.log(k * cert)) <= math.log(1.2)).sum() for k in ks])
    k = float(np.median(ks[counts == counts.max()]))
    near = ld[np.abs(ld - math.log(k * cert)) <= math.log(1.2)]
    return float(np.exp(np.median(near)) / cert) if near.size else k


def detect_and_identify(T, sizes, tau=None, dust=(), region=None) -> tuple[list[dict], float, list[dict]]:
    """The usable beads inside `region` (None = the whole photo), measured, each with its certified size.
    Also returns the dark objects in the region that were NOT used, each with why (for the PNG)."""
    rejected, beads = [], []
    for o in objects(T):
        if not _in(region, o):
            continue
        if not o["why"] and not _not_dust(o, dust):
            o["why"] = "dust"
        (rejected if o["why"] else beads).append(o)
    rows = []
    for b in beads:
        r = measure_at(T, b["cx"], b["cy"], b["d_px"], tau)
        if r and r.get("detected"):
            rows.append(r)
        else:
            rejected.append({**b, "why": "not measured"})
    d = [r.get("d_l0.50", np.nan) for r in rows]
    if len(sizes) == 1:                                   # a single-size slide: drop clumps and dirt
        k = _single_size_scale(d, sizes[0])
        ids = [sizes[0] if np.isfinite(k) and np.isfinite(v) and abs(math.log(v / (k * sizes[0]))) <=
               math.log(1 + SINGLE_BAND) else None for v in d]
    else:
        ids, k = assign_sizes(d, sizes)
    out = []
    for r, s in zip(rows, ids):
        if s is None:
            rejected.append({"cx": r["cx"], "cy": r["cy"], "d_px": r.get("d_l0.50", 0) / UM_PER_PX,
                             "why": "no size match"})
        else:
            r["certified_um"] = s
            out.append(r)
    return out, k, rejected


SIZE_BGR = [(255, 140, 0), (0, 190, 0), (0, 200, 255), (230, 0, 230), (40, 40, 255), (255, 255, 0), (0, 128, 255)]


def region_png(T, region, used, rejected, title: str, sizes: list[float], dest: list[Path]) -> None:
    """The averaged photo with the area used boxed (green), the beads used circled in their size's colour and the
    dark objects in the area that were not used in thin red. Written to every path in `dest`."""
    img = cv2.cvtColor(np.clip(T / 1.1 * 255, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    if region is not None:
        img[~region] = (0.55 * img[~region] + 0.45 * np.array([150, 110, 110])).astype(np.uint8)   # not used: shaded
        cnts, _h = cv2.findContours(region.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, cnts, -1, (0, 200, 0), 3)
    for o in rejected:
        cv2.circle(img, (int(round(o["cx"])), int(round(o["cy"]))), int(o.get("d_px", 4) / 2 + 3), (0, 0, 220), 1)
    order = sorted(sizes)
    for r in used:
        c = SIZE_BGR[order.index(r["certified_um"]) % len(SIZE_BGR)] if r["certified_um"] in order else (255, 255, 255)
        cv2.circle(img, (int(round(r["cx"])), int(round(r["cy"]))), int(r["certified_um"] / UM_PER_PX / 2 + 5), c, 2)
    lines = [(title, (0, 0, 0)),
             (f"area used (inside green, unshaded): {100 * region.mean():.0f}% of the photo" if region is not None else
              "area used: the whole photo", (0, 140, 0)),
             (f"beads used: {len(used)} (circled, colour = size)   not used, in the area: {len(rejected)} (red)",
              (0, 0, 0))]
    font, sc, th = cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
    hgt = 30 * (len(lines) + 1) + 10
    cv2.rectangle(img, (0, 0), (min(img.shape[1], 980), hgt), (255, 255, 255), -1)
    for j, (txt, col) in enumerate(lines):
        cv2.putText(img, txt, (10, 28 + 30 * j), font, sc, col, th, cv2.LINE_AA)
    x = 10
    for s in order:
        if any(r["certified_um"] == s for r in used):
            txt = f"{s:g} um"
            cv2.putText(img, txt, (x, 28 + 30 * len(lines)), font, sc, SIZE_BGR[order.index(s) % len(SIZE_BGR)], th,
                        cv2.LINE_AA)
            x += cv2.getTextSize(txt, font, sc, th)[0][0] + 25
    for p in dest:
        p.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(p), img)


def _png_dest(c: Capture, out: Path | None) -> list[Path]:
    """Where a capture's region PNG goes: its own folder (Ben, 2026-10-15) and the analysis folder."""
    if out is None:
        return []
    notes = re.sub(r"[^\w .+-]", "_", c.notes)
    name = f"{c.run.stem if c.run.is_file() else c.run.name}  {notes}.png"
    dest = [out / "regions" / name]
    if c.run.is_dir():
        dest.insert(0, c.run / "shadowgraph" / "analysis" / "bead_calibration" / "bead_region.png")
    return dest


def _median(v):
    v = np.asarray([x for x in v if x is not None and np.isfinite(x)], float)
    return float(np.median(v)) if v.size else float("nan")


def level_star(rows: list[dict], cert: float) -> float:
    """The relative level l where the median filled diameter equals the certified size (nan if outside)."""
    ls = np.asarray(LEVELS)
    d = np.asarray([_median([r.get(f"d_l{l:.2f}") for r in rows]) for l in LEVELS])
    ok = np.isfinite(d)
    if ok.sum() < 2:
        return float("nan")
    ls, d = ls[ok], d[ok]                                  # d rises with l (a higher level is further out)
    if not (d.min() <= cert <= d.max()):
        return float("nan")
    order = np.argsort(d)
    return float(np.interp(cert, d[order], ls[order]))


def fit_chi(z: np.ndarray, chi: np.ndarray) -> dict:
    """chi = chi0 + k |z - zf| (Blaisot Eq. 39 form), zf searched, chi0 and k by least squares."""
    ok = np.isfinite(z) & np.isfinite(chi)
    z, chi = z[ok], chi[ok]
    if z.size < 3:
        return {}
    best = None
    for zf in np.linspace(z.min(), z.max(), 401):
        A = np.column_stack([np.ones_like(z), np.abs(z - zf)])
        coef, *_ = np.linalg.lstsq(A, chi, rcond=None)
        sse = float(((A @ coef - chi) ** 2).sum())
        if best is None or sse < best[0]:
            best = (sse, float(zf), float(coef[0]), float(coef[1]))
    sse, zf, c0, k = best
    return {"zf_mm": round(zf, 3), "chi0_um": round(c0, 2), "k_um_per_mm": round(k, 2),
            "rms_um": round(math.sqrt(sse / z.size), 2)}


def through_focus(caps: list[Capture], targets: dict, max_frames: int, tau_hint=None, dust=(),
                  out: Path | None = None) -> tuple[list, dict]:
    """The traverse of one slide: beads found in the sparse region of its z = 0 capture, followed through
    every z (same region, same places)."""
    caps = sorted(caps, key=lambda c: c.z_mm)
    ref = min(caps, key=lambda c: abs(c.z_mm))
    sizes = _slide_sizes(ref.slide, ref.target, targets)
    T_ref = transmission(average_frames(ref.run, max_frames))
    region, reg = sparse_region(T_ref)
    beads, k, rejected = detect_and_identify(T_ref, sizes, dust=dust, region=region)
    tau = tau_hint if tau_hint is not None else _tau(beads)
    rows = []
    for c in caps:
        T = T_ref if c is ref else transmission(average_frames(c.run, max_frames))
        rows_c = []
        for i, b in enumerate(beads):
            r = measure_at(T, b["cx"], b["cy"], b["certified_um"] / UM_PER_PX, tau)
            if r is None:
                continue
            r.update(bead=i, certified_um=b["certified_um"], z_mm=c.z_mm, run=c.run.name, slide=c.slide)
            rows_c.append(r)
        rows += rows_c
        region_png(T, region, rows_c, rejected if c is ref else [],
                   f"{c.notes}   ({c.run.name}; beads chosen at {ref.notes})", sizes, _png_dest(c, out))
    return rows, {"slide": ref.slide, "reference_run": ref.run.name, "n_beads": len(beads),
                  "scale_k": round(k, 4) if np.isfinite(k) else None, "tau": tau, "region": reg,
                  "not_used_in_region": _why_counts(rejected)}


def _why_counts(rejected) -> dict:
    out = {}
    for o in rejected:
        out[o["why"]] = out.get(o["why"], 0) + 1
    return out


def _tau(rows) -> float:
    """tau (Blaisot Eq. 8: the contrast of a fully resolved object) from the largest beads' core at focus."""
    if not rows:
        return 0.0
    big = max(r["certified_um"] for r in rows)
    return float(np.clip(_median([r["core_t"] for r in rows if r["certified_um"] == big]), 0.0, 0.9))


def focus_summary(rows: list[dict], cert: float) -> dict:
    d = [r.get("d_current_um") for r in rows]
    med = _median(d)
    q = np.nanpercentile([x for x in d if np.isfinite(x)], [25, 75]) if any(np.isfinite(d)) else [np.nan] * 2
    n = len(rows)
    return {"certified_um": cert, "n_beads": n,
            "d_current_median_um": round(med, 2), "d_current_iqr_um": [round(float(q[0]), 2), round(float(q[1]), 2)],
            "bias_current_pct": round(100 * (med / cert - 1), 1) if np.isfinite(med) else None,
            "in_focus_current_share": round(sum(bool(r.get("in_focus_current")) for r in rows) / n, 3) if n else None,
            "rejected_by_2_2_0_share": round(sum(bool(r.get("reclassified")) for r in rows) / n, 3) if n else None,
            "ring_share": round(sum(bool(r.get("ring")) for r in rows) / n, 3) if n else None,
            "level_star": round(level_star(rows, cert), 3) if np.isfinite(level_star(rows, cert)) else None,
            "d_halfmax_filled_median_um": round(_median([r.get("d_l0.50") for r in rows]), 2),
            "d_blaisot_median_um": round(_median([r.get("d_blaisot_um") for r in rows]), 2),
            "contrast_median": round(_median([r.get("contrast") for r in rows]), 3),
            "chi_median_um": round(_median([r.get("chi_um") for r in rows]), 2)}


def depth_summary(rows: list[dict], cert: float) -> dict:
    """Through focus, for one size: acceptance by the current rule, size stability, chi(z)."""
    zs = sorted({r["z_mm"] for r in rows})
    frac, dmed, chi = [], [], []
    for z in zs:
        rz = [r for r in rows if r["z_mm"] == z]
        frac.append(sum(bool(r.get("in_focus_current")) for r in rz) / len(rz))
        dmed.append(_median([r.get("d_current_um") for r in rz if r.get("in_focus_current")]))
        chi.append(_median([r.get("chi_um") for r in rz]))
    z, frac, dmed, chi = (np.asarray(v, float) for v in (zs, frac, dmed, chi))
    dof_eff = float(np.trapezoid(frac, z)) if z.size > 1 else float("nan")
    above = z[frac >= 0.5]
    dof_50 = float(above.max() - above.min()) if above.size else 0.0
    j0 = int(np.argmin(np.abs(z)))
    stable = z[np.isfinite(dmed) & (np.abs(dmed / dmed[j0] - 1) <= SIZE_STABLE) & (frac >= 0.5)] \
        if np.isfinite(dmed[j0]) else np.array([])
    return {"certified_um": cert, "z_mm": zs, "in_focus_share": [round(float(v), 3) for v in frac],
            "d_current_median_um": [round(float(v), 2) if np.isfinite(v) else None for v in dmed],
            "chi_median_um": [round(float(v), 2) if np.isfinite(v) else None for v in chi],
            "dof_effective_mm": round(dof_eff, 3), "dof_50pct_mm": round(dof_50, 3),
            "size_within_5pct_mm": round(float(stable.max() - stable.min()), 3) if stable.size else 0.0,
            "chi_fit": fit_chi(z, chi)}


def array_scale(T: np.ndarray, pitch_um: float) -> dict:
    """The dot array (reticle): median nearest-neighbour spacing -> um/px, and per quadrant."""
    beads = find_beads(T)
    if len(beads) < 4:
        return {}
    pts = np.asarray([[b["cx"], b["cy"]] for b in beads])
    d = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(d, np.inf)
    nn = d.min(axis=1)
    H, W = T.shape
    quad = {}
    for name, sel in (("tl", (pts[:, 0] < W / 2) & (pts[:, 1] < H / 2)), ("tr", (pts[:, 0] >= W / 2) & (pts[:, 1] < H / 2)),
                      ("bl", (pts[:, 0] < W / 2) & (pts[:, 1] >= H / 2)), ("br", (pts[:, 0] >= W / 2) & (pts[:, 1] >= H / 2))):
        if sel.sum() >= 3:
            quad[name] = round(pitch_um / float(np.median(nn[sel])), 4)
    return {"um_per_px": round(pitch_um / float(np.median(nn)), 4), "n_dots": len(beads), "by_quadrant": quad}


def falling(caps: list[Capture], targets: dict) -> list[dict]:
    out = []
    sizes = [float(s["certified_um"]) for s in targets["beads"]["sizes"]]
    for c in caps:
        cert = min(sizes, key=lambda s: abs(s - float(c.slide))) if c.slide else None
        files = sorted((c.run / "shadowgraph" / "analysis").glob("droplets_*/droplet_sizes.csv"))
        if not files:
            out.append({"run": c.run.name, "certified_um": cert, "note": "not measured yet: run the AI batch"})
            continue
        with open(files[0], newline="") as f:
            rr = list(csv.DictReader(f))
        d_in = [float(r["diameter_um"]) for r in rr if str(r.get("in_focus")).lower() in ("1", "true")]
        out.append(_fall_row(c.run.name, cert, len(rr), d_in))
    # the pours of each size pooled (two per size from 2026-10-15: a hand sprinkle is not a defined plane)
    pooled = {}
    for c in caps:
        files = sorted((c.run / "shadowgraph" / "analysis").glob("droplets_*/droplet_sizes.csv"))
        if not files or not c.slide:
            continue
        cert = min(sizes, key=lambda s: abs(s - float(c.slide)))
        with open(files[0], newline="") as f:
            rr = list(csv.DictReader(f))
        acc = pooled.setdefault(cert, [0, [], 0])
        acc[0] += len(rr)
        acc[1] += [float(r["diameter_um"]) for r in rr if str(r.get("in_focus")).lower() in ("1", "true")]
        acc[2] += 1
    for cert, (n_all, d_in, n_runs) in sorted(pooled.items()):
        if n_runs > 1:
            out.append(_fall_row(f"all {n_runs} pours", cert, n_all, d_in))
    return out


def _fall_row(name: str, cert, n_all: int, d_in: list) -> dict:
    med = _median(d_in)
    q = np.percentile(d_in, [25, 75]) if d_in else [np.nan, np.nan]
    return {"run": name, "certified_um": cert, "n_detected": n_all, "n_in_focus": len(d_in),
            "in_focus_share": round(len(d_in) / n_all, 3) if n_all else None,
            "d_in_focus_median_um": round(med, 2), "d_in_focus_iqr_um": [round(float(v), 2) for v in q],
            "bias_pct": round(100 * (med / cert - 1), 1) if cert and np.isfinite(med) else None}


CHI_MAX_TRIED = (15.0, 20.0, 25.0, 30.0, 40.0)    # blur-width focus rules tried on the falling beads (um)


def falling_detail(run: Path, cert: float | None, tau: float, score_thresh: float = 0.30,
                   frame_step: int = 1) -> tuple[list[dict], dict]:
    """Every AI detection of one pour, re-measured (2026-10-15). Each droplet gets the pipeline's own verdict and
    size, exactly as measure_run made them (measure_droplet, 2.2.0, on T = frame / the run's temporal median),
    next to its blur width chi, contrast and contrast-corrected size (measure_at) and its nearest neighbour. Every
    object in a pour is a sphere, so the AI's class shares and the atomised fraction by area are checked too.
    Needs the AI chain's files in the run: predictions.json, instances.json, background_median.tiff, 16-bit frames.
    Works on any run with those files (a spray run too: cert None); frame_step > 1 measures every Nth frame."""
    from collections import Counter, defaultdict
    sg = run / "shadowgraph"
    pred, man = sg / "analysis" / "predictions.json", sg / "raw" / "instances.json"
    bg_path, frames = sg / "raw" / "background_median.tiff", sg / "raw" / "frames" / "16bit"
    if not (pred.is_file() and man.is_file() and bg_path.is_file() and frames.is_dir()):
        return [], {"note": "no AI files (predictions.json, instances.json, background, 16-bit frames)"}
    names = {im["id"]: Path(im["file_name"]).stem for im in json.loads(man.read_text(encoding="utf-8"))["images"]}
    bg = cv2.imread(str(bg_path), cv2.IMREAD_UNCHANGED).astype(np.float32)
    by_img = defaultdict(list)
    for d in json.loads(pred.read_text(encoding="utf-8")):
        if d["score"] >= score_thresh and not d.get("truncated", False):
            by_img[d["image_id"]].append(d)
    rows, n_class, a_class = [], Counter(), Counter()
    for img_id in sorted(by_img)[::max(1, frame_step)]:
        T = mr.transmission(frames, names.get(img_id, ""), bg)
        if T is None:
            continue
        drops = []
        for d in by_img[img_id]:
            mb, bx, by, bh, bw = mr.det_crop(d)
            if not mb.any():
                continue
            cls = {mr.DROPLET: "droplet", mr.FILAMENT: "filament"}.get(d["category_id"], "blob")
            n_class[cls] += 1
            a_class[cls] += float(d["area"])
            if cls != "droplet":
                continue
            md = mr.measure_droplet(T, d, FOCUS_MAX, crop=(mb, bx, by, bh, bw), sharpness_rule=True)
            if md is None:
                continue
            ys, xs = np.nonzero(mb)
            drops.append((bx + float(xs.mean()), by + float(ys.mean()), 2 * math.sqrt(float(d["area"]) / math.pi), md))
        pts = np.asarray([[x, y] for x, y, _d, _m in drops], float)
        for i, (cx, cy, dpx, md) in enumerate(drops):
            dist = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) if len(drops) > 1 else np.array([np.inf])
            if len(drops) > 1:
                dist[i] = np.inf
            nn = float(dist.min())
            r = measure_at(T, cx, cy, dpx, tau, levels=()) or {}      # chi and size only: 4 levels, not 18
            rows.append({"frame": names[img_id], "cx": round(cx, 1), "cy": round(cy, 1), "certified_um": cert,
                         "ai_mask_d_um": round(dpx * UM_PER_PX, 2),
                         "pipeline_in_focus": bool(md["in_focus"]),
                         "pipeline_d_um": round(float(mr.equiv_um(md["area_px"])), 2), "method": md["method"],
                         "core_t": round(float(md["core_t"]), 4), "nn_px": round(nn, 1) if np.isfinite(nn) else None,
                         "isolated": bool(nn > 2 * dpx + 2),
                         "chi_um": r.get("chi_um", float("nan")), "contrast": r.get("contrast", float("nan")),
                         "d_l0.50": r.get("d_l0.50", float("nan")), "d_blaisot_um": r.get("d_blaisot_um", float("nan"))})
    total = sum(a_class.values())
    return rows, {"classes_n": dict(n_class),
                  "classes_area_share": {k: round(v / total, 4) for k, v in a_class.items()} if total else {},
                  "atomised_pct_by_area": round(100 * a_class["droplet"] / total, 2) if total else None}


def falling_summary(rows: list[dict], cert: float, static_ratio: float | None = None) -> dict:
    """One pour: the pipeline as it is, then what a blur-width focus rule would do (chi <= chi_max, isolated
    droplets, the pipeline's own size), against the certificate and the static beads at focus."""
    def stats(sel):
        d = [r["pipeline_d_um"] for r in sel]
        med = _median(d)
        return {"n": len(sel), "median_um": round(med, 2) if np.isfinite(med) else None,
                "bias_pct": round(100 * (med / cert - 1), 1) if np.isfinite(med) else None}
    inf = [r for r in rows if r["pipeline_in_focus"]]
    chi_in = [r["chi_um"] for r in inf if np.isfinite(r["chi_um"])]
    out = {"certified_um": cert, "detections": len(rows), "pipeline_in_focus": stats(inf),
           "isolated_share": round(sum(r["isolated"] for r in rows) / len(rows), 3) if rows else None,
           "chi_of_pipeline_in_focus_um": [round(float(np.percentile(chi_in, q)), 1) for q in (10, 50, 90)]
           if chi_in else None,
           "static_at_focus_ratio": round(static_ratio, 4) if static_ratio else None, "chi_rule": {}}
    for cmax in CHI_MAX_TRIED:
        sel = [r for r in rows if r["isolated"] and np.isfinite(r["chi_um"]) and r["chi_um"] <= cmax]
        out["chi_rule"][f"{cmax:g}"] = stats(sel)
    return out


def _falling_figure(out: Path, detail: dict, rows_depth: list[dict]) -> Path | None:
    """Per size: measured / certified against blur width, falling beads (pipeline in focus or not) over the static
    through-focus beads (known depth), with the chi rules tried."""
    if not detail:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sizes = sorted(detail, key=float)
    fig, axs = plt.subplots(1, len(sizes), figsize=(4.2 * len(sizes), 4.2), squeeze=False)
    for ax, s in zip(axs[0], sizes):
        rr, cert = detail[s]["rows"], float(s)
        for flag, col, lab in ((False, "#9aa0a6", "falling, pipeline: out of focus"),
                               (True, "#2a7de1", "falling, pipeline: in focus")):
            sel = [r for r in rr if r["pipeline_in_focus"] == flag and np.isfinite(r["chi_um"])]
            ax.scatter([r["chi_um"] for r in sel], [r["pipeline_d_um"] / cert for r in sel], s=2, alpha=0.15,
                       color=col, label=lab, rasterized=True)
        st = [r for r in rows_depth if r["certified_um"] == cert]
        if st:
            zs = sorted({r["z_mm"] for r in st})
            cx = [_median([r.get("chi_um") for r in st if r["z_mm"] == z]) for z in zs]
            cy = [_median([r.get("d_current_um") for r in st if r["z_mm"] == z]) / cert for z in zs]
            ax.plot(cx, cy, "o-", color="#d9822b", ms=3, label="static beads, through focus")
        for cmax in (20.0, 30.0):
            ax.axvline(cmax, color="k", lw=0.6, ls=":")
        ax.axhline(1, color="k", lw=0.8)
        ax.set(xlim=(0, 90), ylim=(0.6, 2.4), xlabel="blur width chi (um)", ylabel="pipeline size / certified",
               title=f"{s} um falling")
    axs[0][0].legend(fontsize=7, markerscale=4, loc="upper left")
    fig.tight_layout()
    p = out / "fig_falling_chi.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def equivalent_defocus(rows_depth: list[dict], fall: list[dict]) -> dict:
    """At what depth do the static beads read as large as the falling ones? For every z of the through-focus
    series, the median in-focus d_current / certified of each size, against each pour's median / certified; the
    z where they agree best over all the sizes both have (mean |log ratio|). A pour is not on the focal plane:
    this says how far off it fell, and so how much of the falling beads' error is defocus that the current
    in-focus rule lets through (2026-10-15: ~2.5-3 mm, which explains the falling beads' fixed ~+20 um)."""
    want = {f["certified_um"]: f["d_in_focus_median_um"] / f["certified_um"] for f in fall
            if not str(f.get("run", "")).startswith("all ") and f.get("d_in_focus_median_um") and f.get("certified_um")
            and np.isfinite(f["d_in_focus_median_um"])}
    sizes = sorted({r["certified_um"] for r in rows_depth} & set(want))
    if not sizes:
        return {}
    by_z = []
    for z in sorted({r["z_mm"] for r in rows_depth}):
        ratio = {}
        for c in sizes:
            d = [r.get("d_current_um") for r in rows_depth
                 if r["z_mm"] == z and r["certified_um"] == c and r.get("in_focus_current")]
            m = _median(d)
            if np.isfinite(m):
                ratio[c] = m / c
        if len(ratio) == len(sizes):
            by_z.append((float(np.mean([abs(math.log(ratio[c] / want[c])) for c in sizes])), z, ratio))
    if not by_z:
        return {}
    misfit, z, ratio = min(by_z, key=lambda t: t[0])
    other = [t for t in by_z if t[1] * z < 0]                   # the best on the other side of focus
    out = {"sizes_um": sizes, "best_z_mm": z, "misfit_pct": round(100 * misfit, 1),
           "static_ratio_at_best_z": {f"{c:g}": round(ratio[c], 3) for c in sizes},
           "falling_ratio": {f"{c:g}": round(want[c], 3) for c in sizes}}
    if other:
        m2, z2, _r2 = min(other, key=lambda t: t[0])
        out.update(other_side_z_mm=z2, other_side_misfit_pct=round(100 * m2, 1))
    return out


def _write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def _figures(out: Path, at_focus: dict, depth: dict, rows_focus: list[dict]):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figs = []
    if at_focus:
        sizes = sorted(at_focus, key=float)
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        c = [float(s) for s in sizes]
        ax[0].plot(c, [at_focus[s]["bias_current_pct"] for s in sizes], "o-", label="current sizer (2.2.0)")
        ax[0].plot(c, [100 * (at_focus[s]["d_blaisot_median_um"] / float(s) - 1) for s in sizes], "s--",
                   label="Blaisot l = 0.61, contrast-corrected")
        ax[0].axhline(0, color="k", lw=0.8)
        ax[0].set(xlabel="certified diameter (um)", ylabel="bias at focus (%)", title="Size bias at best focus")
        ax[0].legend(fontsize=8)
        for s in sizes:
            rr = [r for r in rows_focus if r["certified_um"] == float(s)]
            ax[1].plot(LEVELS, [_median([r.get(f"d_l{l:.2f}") for r in rr]) / float(s) for l in LEVELS], label=s)
        ax[1].axhline(1, color="k", lw=0.8)
        ax[1].set(xlabel="relative level l", ylabel="d(l) / certified", title="Diameter against edge level")
        ax[1].legend(fontsize=8, title="um")
        fig.tight_layout()
        figs.append(out / "fig_at_focus.png")
        fig.savefig(figs[-1], dpi=130)
        plt.close(fig)
    if depth:
        fig, ax = plt.subplots(1, 3, figsize=(15, 4))
        for s, d in sorted(depth.items(), key=lambda kv: float(kv[0])):
            ax[0].plot(d["z_mm"], d["in_focus_share"], "o-", ms=3, label=s)
            ax[1].plot(d["z_mm"], [v / float(s) if v else np.nan for v in d["d_current_median_um"]], "o-", ms=3)
            ax[2].plot(d["z_mm"], [v if v else np.nan for v in d["chi_median_um"]], "o-", ms=3)
        ax[0].set(xlabel="z (mm)", ylabel="share counted in focus", title="Current focus rule through focus")
        ax[0].legend(fontsize=8, title="um")
        ax[1].set(xlabel="z (mm)", ylabel="d_current / certified", title="Size through focus (in-focus beads)")
        ax[2].set(xlabel="z (mm)", ylabel="chi (um)", title="Blur width chi (Blaisot)")
        fig.tight_layout()
        figs.append(out / "fig_through_focus.png")
        fig.savefig(figs[-1], dpi=130)
        plt.close(fig)
    return figs


def analyse(paths, out: Path, targets_path: Path | None = None, max_frames: int = MAX_FRAMES,
            tau_fixed: float | None = None) -> dict:
    """tau_fixed: Blaisot's tau to use instead of measuring it (chi depends on it, so a later series must use the
    first one's to be comparable: 0.1115 for the beads of 2026-10-15)."""
    global UM_PER_PX
    profile = optics.profile_for(paths[0])             # the optics these captures were taken with
    UM_PER_PX = mr.UM_PER_PX = float(profile["um_per_px"])
    caps = find_captures(paths)
    if not caps:
        sys.exit("no calibration captures (Notes starting BEAD or RETICLE) under " + ", ".join(map(str, paths)))
    targets = load_targets(targets_path)
    out.mkdir(parents=True, exist_ok=True)
    result = {"version": VERSION, "made": datetime.now().isoformat(timespec="seconds"),
              "captures": len(caps), "um_per_px_assumed": UM_PER_PX, "optics_profile": profile["name"],
              "focus_max": FOCUS_MAX,
              "note": "The current sizer is run with a T < 0.95 component in place of the AI mask; below 40 um "
                      "the real pipeline sizes from the AI mask, so the falling-bead runs are the check there.",
              "through_focus": {}, "at_focus": {}, "falling": [], "array": [], "background_check": []}

    # dust: whatever a bead-free capture shows is not a bead, wherever it turns up
    dust = []
    for c in [c for c in caps if c.kind == "bg"]:
        dust += dust_positions(transmission(average_frames(c.run, max_frames)))
    result["dust_spots"] = len(dust)

    # through focus, per slide
    rows_depth = []
    tau = tau_fixed
    result["regions"] = []
    for slide in sorted({c.slide for c in caps if c.kind == "z"}):
        zc = [c for c in caps if c.kind == "z" and c.slide == slide]
        rows, info = through_focus(zc, targets, max_frames, tau_hint=tau_fixed, dust=dust, out=out)
        tau = info["tau"] if tau is None else tau
        rows_depth += rows
        result["through_focus"][slide] = {"info": info}
        result["regions"].append({"run": info["reference_run"], "slide": slide, "kind": "through focus",
                                  "beads_used": info["n_beads"], **info["region"],
                                  "not_used_in_region": info["not_used_in_region"]})
        for cert in sorted({r["certified_um"] for r in rows}):
            result["through_focus"][slide][f"{cert:g}"] = depth_summary(
                [r for r in rows if r["certified_um"] == cert], cert)

    # at focus: the traverse's z = 0 plus every 'focus' capture, each in its own sparse region
    rows_focus = [dict(r) for r in rows_depth if r["z_mm"] == 0]
    for c in [c for c in caps if c.kind == "focus"]:
        T = transmission(average_frames(c.run, max_frames))
        sizes = _slide_sizes(c.slide, c.target, targets)
        region, reg = sparse_region(T)
        beads, _k, rejected = detect_and_identify(T, sizes, dust=dust, region=region)
        t = tau if tau is not None else _tau(beads)
        used = []
        for r in beads:
            r2 = measure_at(T, r["cx"], r["cy"], r["certified_um"] / UM_PER_PX, t)
            if r2 and r2.get("detected"):
                r2.update(certified_um=r["certified_um"], z_mm=0.0, run=c.run.name, slide=c.slide)
                used.append(r2)
        rows_focus += used
        region_png(T, region, used, rejected, f"{c.notes}   ({c.run.name})", sizes, _png_dest(c, out))
        result["regions"].append({"run": c.run.name, "slide": c.slide, "kind": "at focus", "beads_used": len(used),
                                  **reg, "not_used_in_region": _why_counts(rejected)})
    tau = tau if tau is not None else _tau(rows_focus)
    for cert in sorted({r["certified_um"] for r in rows_focus}):
        rc = [r for r in rows_focus if r["certified_um"] == cert]
        result["at_focus"][f"{cert:g}"] = focus_summary(rc, cert)
        result["at_focus"][f"{cert:g}"]["by_slide"] = {
            s: focus_summary([r for r in rc if r["slide"] == s], cert) for s in sorted({r["slide"] for r in rc})}
    result["tau"] = round(float(tau), 4) if tau is not None else None

    # background cross-check: a 'bg' capture's own T should be ~1 everywhere
    for c in [c for c in caps if c.kind == "bg"]:
        T = transmission(average_frames(c.run, max_frames))
        result["background_check"].append({"run": c.run.name, "slide": c.slide,
                                           "T_p01": round(float(np.percentile(T, 1)), 4),
                                           "T_p99": round(float(np.percentile(T, 99)), 4)})
    # reticle dot array
    for c in [c for c in caps if c.kind == "array"]:
        T = transmission(average_frames(c.run, max_frames))
        a = array_scale(T, float(targets["reticle"]["array"]["pitch_um"]))
        result["array"].append({"run": c.run.name, "pos": c.pos, **a})
    result["falling"] = falling([c for c in caps if c.kind == "fall"], targets)
    result["falling_equivalent_defocus"] = equivalent_defocus(rows_depth, result["falling"])

    # the pours bead by bead (needs the AI chain's files in each pour's run folder)
    result["falling_detail"] = {}
    detail_rows, detail_fig = [], {}
    sizes = [float(s["certified_um"]) for s in targets["beads"]["sizes"]]
    at_ratio = {float(k): v["d_current_median_um"] / float(k) for k, v in result["at_focus"].items()
                if v.get("d_current_median_um") and np.isfinite(v["d_current_median_um"])}
    for c in [c for c in caps if c.kind == "fall" and c.run.is_dir() and c.slide]:
        cert = min(sizes, key=lambda s: abs(s - float(c.slide)))
        rows, info = falling_detail(c.run, cert, tau if tau is not None else 0.1)
        if rows:
            info = {**falling_summary(rows, cert, at_ratio.get(cert)), **info}
            for r in rows:
                r["run"] = c.run.name
            detail_rows += rows
            detail_fig.setdefault(f"{cert:g}", {"rows": []})["rows"] += rows
        result["falling_detail"][c.run.name] = info

    _write_csv(out / "beads_through_focus.csv", rows_depth)
    _write_csv(out / "beads_at_focus.csv", rows_focus)
    _write_csv(out / "falling_beads.csv", detail_rows)
    depth_for_fig = {k: v for s in result["through_focus"].values() for k, v in s.items() if k != "info"}
    figs = _figures(out, result["at_focus"], depth_for_fig, rows_focus)
    ff = _falling_figure(out, detail_fig, rows_depth)
    figs += [ff] if ff else []
    name = "optics_calibration_v2.json" if any(c.target == "reticle" for c in caps) else "optics_calibration_v1.json"
    (out / name).write_text(json.dumps(result, indent=1), encoding="utf-8")
    (out / "report.md").write_text(report(result, figs), encoding="utf-8")
    result["_files"] = [str(out / name), str(out / "report.md")] + [str(f) for f in figs]
    return result


def report(R: dict, figs) -> str:
    L = [f"# Size calibration ({R['made'][:10]}, bead_calibration {R['version']})\n",
         f"{R['captures']} captures; scale assumed {R['um_per_px_assumed']} um/px; "
         f"tau (largest beads' core at focus) {R.get('tau')}; {R.get('dust_spots', 0)} dust spots (from the "
         f"bead-free captures) excluded. {R['note']}\n"]
    if R["at_focus"]:
        L += ["## At best focus\n",
              "| certified (um) | beads | current sizer (um) | bias | in focus (current rule) | rejected by 2.2.0 "
              "| rings | l* | Blaisot (um) | C | chi (um) |", "|" + "---|" * 11]
        for s, a in sorted(R["at_focus"].items(), key=lambda kv: float(kv[0])):
            L.append(f"| {s} | {a['n_beads']} | {a['d_current_median_um']} | {a['bias_current_pct']}% | "
                     f"{a['in_focus_current_share']} | {a['rejected_by_2_2_0_share']} | {a['ring_share']} | "
                     f"{a['level_star']} | {a['d_blaisot_median_um']} | {a['contrast_median']} | {a['chi_median_um']} |")
        L.append("\nl* = the relative grey level whose (hole-filled) diameter equals the certified size; the "
                 "current sizer uses 0.5 (half-max).\n")
        L += ["### By slide\n", "| certified (um) | slide | beads | current sizer (um) | bias | in focus | l* |",
              "|---|---|---|---|---|---|---|"]
        for s, a in sorted(R["at_focus"].items(), key=lambda kv: float(kv[0])):
            for sl, b in a.get("by_slide", {}).items():
                L.append(f"| {s} | {sl} | {b['n_beads']} | {b['d_current_median_um']} | {b['bias_current_pct']}% | "
                         f"{b['in_focus_current_share']} | {b['level_star']} |")
        L.append("")
    if R.get("regions"):
        L += ["## The part of each photo used\n",
              f"Only dark (T_min < {DARK_T}), round (axis ratio <= {ROUND_MAX}), isolated beads, inside the sparse "
              f"{TILE_PX}-px tiles (dark cover <= {100 * SPARSE_MAX:.0f}% around the tile; else the {MIN_TILES} "
              "sparsest). Each capture's folder holds `shadowgraph/analysis/bead_calibration/bead_region.png` with "
              "the area boxed; copies are in `regions/`.\n",
              "| run | slide | kind | area used | dark cover (used / whole photo) | beads used | not used in the area |",
              "|---|---|---|---|---|---|---|"]
        for g in R["regions"]:
            L.append(f"| {g['run']} | {g['slide']} | {g['kind']} | {100 * g['share_of_frame']:.0f}%"
                     f"{' (sparsest only)' if g['fallback_sparsest'] else ''} | {100 * g['dark_cover_used']:.1f}% / "
                     f"{100 * g['dark_cover_all']:.1f}% | {g['beads_used']} | "
                     f"{', '.join(f'{k} {v}' for k, v in sorted(g['not_used_in_region'].items())) or '-'} |")
        L.append("")
    for slide, d in R["through_focus"].items():
        L += [f"## Through focus: slide '{slide}' (reference {d['info']['reference_run']}, "
              f"{d['info']['n_beads']} beads)\n",
              "| certified (um) | counted in focus over (effective, mm) | >= 50 % in focus (mm) | size within 5 % (mm) "
              "| chi0 (um) | k (um/mm) | zf (mm) |", "|" + "---|" * 7]
        for s, v in sorted(((k, v) for k, v in d.items() if k != "info"), key=lambda kv: float(kv[0])):
            f = v["chi_fit"] or {}
            L.append(f"| {s} | {v['dof_effective_mm']} | {v['dof_50pct_mm']} | {v['size_within_5pct_mm']} | "
                     f"{f.get('chi0_um')} | {f.get('k_um_per_mm')} | {f.get('zf_mm')} |")
        L.append("\nThe effective depth is the integral of the in-focus share over z: the 1/DOF(d) weight a "
                 "count or D32 needs for droplets of that size.\n")
    if R["falling"]:
        L += ["## Falling beads (AI pipeline)\n", "| run | certified (um) | in focus | median (um) | bias |",
              "|---|---|---|---|---|"]
        for f in R["falling"]:
            b = f.get("bias_pct")
            L.append(f"| {f['run']} | {f['certified_um']} | {f.get('n_in_focus', '-')} | "
                     f"{f.get('d_in_focus_median_um', f.get('note'))} | {f'{b:+.1f}%' if b is not None else '-'} |")
        e = R.get("falling_equivalent_defocus") or {}
        if e:
            L += ["", f"**Equivalent defocus:** the static beads read as large as the falling ones at z = "
                      f"{e['best_z_mm']:+.2f} mm from best focus (misfit {e['misfit_pct']}%"
                  + (f"; the other side of focus, {e['other_side_z_mm']:+.2f} mm, misfit {e['other_side_misfit_pct']}%"
                     if "other_side_z_mm" in e else "") + "). d / certified, static at that z against falling: "
                  + ", ".join(f"{c} um {e['static_ratio_at_best_z'][c]} vs {e['falling_ratio'][c]}"
                              for c in e['static_ratio_at_best_z'])
                  + ". The pours did not fall on the focal plane, and the current in-focus rule accepts beads "
                    "that far out, so their error is mostly defocus, not the edge level."]
    fd = {k: v for k, v in (R.get("falling_detail") or {}).items() if "chi_rule" in v}
    if fd:
        rules = list(CHI_MAX_TRIED)
        L += ["", "### Falling beads, bead by bead: what a blur-width focus rule would do\n",
              "Each AI droplet detection re-measured as the pipeline does (2.2.0), plus its blur width chi. Rows: the "
              "pipeline as it is, then only isolated droplets with chi <= chi_max, sized by the pipeline. The static "
              "beads at focus read the 'static' ratio, the floor a focus rule can reach without a new scale.\n",
              "| pour | pipeline in focus: n, median, bias | " + " | ".join(f"chi <= {c:g} um" for c in rules)
              + " | static at focus |", "|" + "---|" * (len(rules) + 3)]
        for run, v in sorted(fd.items(), key=lambda kv: kv[1]["certified_um"]):
            pi = v["pipeline_in_focus"]
            cells = [f"{x['n']}, {x['median_um']}, {x['bias_pct']:+.1f}%" if x["median_um"] else f"{x['n']}, -"
                     for x in (v["chi_rule"][f"{c:g}"] for c in rules)]
            st = v.get("static_at_focus_ratio")
            L.append(f"| {run} | {pi['n']}, {pi['median_um']}, {pi['bias_pct']:+.1f}% | " + " | ".join(cells)
                     + f" | {f'{100 * (st - 1):+.1f}%' if st else '-'} |")
        L += ["", "**The AI on pure spheres** (every object in a pour is a bead): "
              + "; ".join(f"{run}: droplet / filament / blob by count {v['classes_n'].get('droplet', 0)} / "
                          f"{v['classes_n'].get('filament', 0)} / {v['classes_n'].get('blob', 0)}, atomised by area "
                          f"{v['atomised_pct_by_area']}%"
                          for run, v in sorted(fd.items(), key=lambda kv: kv[1]["certified_um"])) + "."]
    if R["array"]:
        L += ["\n## Reticle dot array: scale\n"] + [f"- {a['run']} ({a['pos']}): {a.get('um_per_px')} um/px, "
                                                   f"quadrants {a.get('by_quadrant')}" for a in R["array"]]
    if R["background_check"]:
        L += ["\n## Background check (bead-free captures: T should sit near 1)\n"] + \
             [f"- {b['run']} ({b['slide']}): T 1st-99th percentile {b['T_p01']} - {b['T_p99']}"
              for b in R["background_check"]]
    L += ["\n## Figures\n"] + [f"![{Path(f).stem}]({Path(f).name})" for f in figs]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, help="day folders or run folders holding the captures")
    ap.add_argument("--out", type=Path, required=True, help="a new folder for the results")
    ap.add_argument("--targets", type=Path, default=None,
                    help="targets.json (default: the first found in the given folder or its parents)")
    ap.add_argument("--max-frames", type=int, default=MAX_FRAMES, help="frames averaged per capture")
    ap.add_argument("--tau", type=float, default=None, help="Blaisot's tau to use instead of measuring it (chi "
                    "depends on it: give 0.1115, the 2026-10-15 value, so a new series is comparable)")
    a = ap.parse_args()
    targets = a.targets
    if targets is None:
        for p in [a.paths[0]] + list(a.paths[0].resolve().parents)[:5]:
            if (p / "targets.json").is_file():
                targets = p / "targets.json"
                break
    R = analyse(a.paths, a.out, targets, a.max_frames, a.tau)
    print(f"{R['captures']} captures; targets {targets or '(built-in sizes)'}")
    for s, v in sorted(R["at_focus"].items(), key=lambda kv: float(kv[0])):
        print(f"  {s:>7} um: {v['n_beads']:3d} beads at focus, current sizer {v['d_current_median_um']} um "
              f"({v['bias_current_pct']}%), l* {v['level_star']}, rings {v['ring_share']}")
    print("written:", *R["_files"], sep="\n  ")


if __name__ == "__main__":
    main()
