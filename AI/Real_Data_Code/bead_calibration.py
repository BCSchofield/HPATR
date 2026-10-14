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

Each capture is averaged over its frames. The beads do not move, so a temporal median would contain them:
the background is estimated from the averaged frame itself (a large-window median; a bead is at most ~16 px
across) and T = I / background. Beads are found at best focus and each is followed through every depth at
the same place, so its identity (certified size) carries through.

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
Nothing in the capture folders is written; nothing in the pipeline changes (a new sizer is a separate step).

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
import measure_run as mr  # noqa: E402

VERSION = "1.0.0"
UM_PER_PX = mr.UM_PER_PX
LEVELS = tuple(round(float(x), 2) for x in np.arange(0.10, 0.901, 0.05))
BLAISOT_LEVELS = (0.25, 0.61, 0.77)
DETECT_T = 0.95               # as extract_candidates / check_missed: anything darker is a candidate
MIN_AREA_PX = 4
EDGE_PX = 3                   # a bead this close to the frame edge is not measured
BG_DOWNSAMPLE = 4
BG_WINDOW_PX = 101            # >> the largest bead (155.8 um = 16 px), even blurred
RECENTRE_PX = 3               # a bead may shift this much between depths
ISOLATION = 2.0               # centres closer than this many mean diameters (+2 px): both dropped
UPSAMPLE = 4                  # the level curves are measured on a 4x bicubic upsample (less pixel staircase)
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


def find_captures(paths) -> list[Capture]:
    out = []
    for p in paths:
        p = Path(p)
        summaries = [p / "run_summary.xlsx"] if (p / "run_summary.xlsx").is_file() else \
            sorted(q for q in p.rglob("run_summary.xlsx") if not any(s.startswith((".", "_")) for s in q.parts))
        for x in summaries:
            notes = read_meta(x).get("Notes")
            parsed = parse_notes(notes)
            if parsed:
                out.append(Capture(x.parent, str(notes).strip(), *parsed))
    return out


# ---- frames and transmission ------------------------------------------------------------------------------

def average_frames(run: Path, max_frames: int = MAX_FRAMES) -> np.ndarray:
    """The capture averaged over up to max_frames frames, spread through it: from its .cine, else from
    extracted 16-bit TIFFs (shadowgraph/raw/frames/16bit)."""
    cines = sorted((run / "shadowgraph" / "raw" / "CINE").glob("*.cine"))
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


# ---- the Blaisot & Yon model (Gaussian PSF, disc object) --------------------------------------------------

_MODEL: dict | None = None


def blaisot_model() -> dict:
    """For a grid of a~ = sqrt(2) a / chi (a = geometric radius, chi = PSF half-width, s(r) = exp(-2 r^2/chi^2)):
    the normalised contrast C0 = (1 - e^-a~^2)/(1 + e^-a~^2) and the level radii r~_l of the image profile
    (Eq. 5 with tau = 0; r~_l does not depend on tau, Sect. 2.5). Cached."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    from scipy.special import i0e
    a_grid = np.linspace(0.08, 6.0, 150)
    r = np.linspace(0.0, 12.0, 2401)
    levels = sorted(set(LEVELS) | set(BLAISOT_LEVELS) | {0.5})
    radii = {l: [] for l in levels}
    for a in a_grid:
        rho = np.linspace(0.0, a, 500)
        # e^{-r^2 - rho^2} I0(2 r rho) = e^{-(r - rho)^2} i0e(2 r rho): no overflow
        f = rho[None, :] * np.exp(-(r[:, None] - rho[None, :]) ** 2) * i0e(2.0 * r[:, None] * rho[None, :])
        prof = 1.0 - 2.0 * np.trapezoid(f, rho, axis=1)
        pmin = prof[0]
        for l in levels:
            thr = pmin + l * (1.0 - pmin)
            j = int(np.argmax(prof >= thr))
            j = max(j, 1)
            r0, r1, p0, p1 = r[j - 1], r[j], prof[j - 1], prof[j]
            radii[l].append(r0 + (thr - p0) * (r1 - r0) / (p1 - p0) if p1 != p0 else r1)
    e = np.exp(-a_grid ** 2)
    _MODEL = {"a": a_grid, "C0": (1 - e) / (1 + e), "r": {l: np.asarray(v) for l, v in radii.items()}}
    return _MODEL


def c0_from(C: float, tau: float) -> float:
    """Blaisot Eq. 11 inverted: the normalised contrast from the measured one."""
    den = (1.0 - tau) * (1.0 + C) - C
    return float(np.clip(C / den, 0.0, 0.999)) if den > 0 else 0.999


def p_level(l: float, C0: float) -> float:
    """a / r_l as a function of C0 (Blaisot Eq. 15), from the model."""
    m = blaisot_model()
    return float(np.interp(C0, m["C0"], m["a"] / m["r"][l]))


def p_width(C0: float) -> float:
    """r~_0.77 - r~_0.25 as a function of C0 (Blaisot Eq. 19-20), from the model."""
    m = blaisot_model()
    return float(np.interp(C0, m["C0"], m["r"][0.77] - m["r"][0.25]))


# ---- detection and measurement ---------------------------------------------------------------------------

def find_beads(T: np.ndarray) -> list[dict]:
    """Isolated dark round-ish objects, as extract_candidates finds candidates (T < 0.95, >= 4 px), not touching
    the frame edge and with no neighbour closer than ISOLATION mean diameters."""
    Ts = cv2.GaussianBlur(T, (0, 0), 0.5)
    n, lab, stats, cent = cv2.connectedComponentsWithStats((Ts < DETECT_T).astype(np.uint8), connectivity=8)
    H, W = T.shape
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in stats[i])
        if a < MIN_AREA_PX or x <= EDGE_PX or y <= EDGE_PX or x + w >= W - EDGE_PX or y + h >= H - EDGE_PX:
            continue
        out.append({"cx": float(cent[i][0]), "cy": float(cent[i][1]), "area": a,
                    "d_px": 2.0 * math.sqrt(a / math.pi)})
    keep = []
    for i, b in enumerate(out):
        ok = True
        for j, c in enumerate(out):
            if i != j and math.hypot(b["cx"] - c["cx"], b["cy"] - c["cy"]) < \
                    ISOLATION * (b["d_px"] + c["d_px"]) / 2 + 2:
                ok = False
                break
        if ok:
            keep.append(b)
    return keep


def _component_at(mask: np.ndarray, y: int, x: int) -> np.ndarray:
    n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    if n < 2:
        return np.zeros_like(mask, bool)
    k = lab[y, x]
    if k == 0:                                    # the seed is not in the mask: take the nearest component
        ys, xs = np.nonzero(lab)
        j = int(np.argmin((ys - y) ** 2 + (xs - x) ** 2))
        k = lab[ys[j], xs[j]]
    return lab == k


def measure_at(T: np.ndarray, cx: float, cy: float, d_px: float, tau: float | None = None) -> dict | None:
    """Everything measured for one bead whose centre is near (cx, cy). None if it is too close to the edge."""
    from scipy import ndimage
    H, W = T.shape
    half = int(max(14, 1.5 * d_px + 12))
    Ts = cv2.GaussianBlur(T, (0, 0), 1.0)
    x0r, x1r = int(round(cx)) - RECENTRE_PX, int(round(cx)) + RECENTRE_PX + 1
    y0r, y1r = int(round(cy)) - RECENTRE_PX, int(round(cy)) + RECENTRE_PX + 1
    if x0r < 0 or y0r < 0 or x1r > W or y1r > H:
        return None
    # re-centre on the darkness: the centroid of (1 - T) in the search window
    win = np.clip(1.0 - Ts[max(0, y0r - half // 2):min(H, y1r + half // 2),
                           max(0, x0r - half // 2):min(W, x1r + half // 2)], 0, None)
    if win.sum() > 0:
        yy, xx = np.mgrid[0:win.shape[0], 0:win.shape[1]]
        ucx = max(0, x0r - half // 2) + float((xx * win).sum() / win.sum())
        ucy = max(0, y0r - half // 2) + float((yy * win).sum() / win.sum())
        if math.hypot(ucx - cx, ucy - cy) <= RECENTRE_PX + 1:
            cx, cy = ucx, ucy
    xc, yc = int(round(cx)), int(round(cy))
    x0, x1, y0, y1 = xc - half, xc + half + 1, yc - half, yc + half + 1
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
        return None
    Tc = T[y0:y1, x0:x1]
    Tsc = Ts[y0:y1, x0:x1]
    row = {"cx": round(cx, 2), "cy": round(cy, 2)}
    cand = Tsc < DETECT_T
    m = _component_at(cand, half, half) if cand.any() else np.zeros_like(cand)
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

    # -- the level curve, on a 4x upsample, inside the bead's neighbourhood --
    U = cv2.resize(Tc, None, fx=UPSAMPLE, fy=UPSAMPLE, interpolation=cv2.INTER_CUBIC)
    near = cv2.resize(cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)), (U.shape[1], U.shape[0]),
                      interpolation=cv2.INTER_NEAREST).astype(bool)
    for l in sorted(set(LEVELS) | set(BLAISOT_LEVELS) | {0.5}):
        thr = core + l * (1.0 - core)
        reg = (U < thr) & near
        if not reg.any():
            row[f"d_l{l:.2f}"] = row[f"draw_l{l:.2f}"] = float("nan")
            continue
        n, lab, stats, _c = cv2.connectedComponentsWithStats(reg.astype(np.uint8), connectivity=8)
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        comp_l = lab == big
        a_raw = float(comp_l.sum())
        a_fill = float(ndimage.binary_fill_holes(comp_l).sum())
        row[f"d_l{l:.2f}"] = round(2 * math.sqrt(a_fill / math.pi) / UPSAMPLE * UM_PER_PX, 3)
        row[f"draw_l{l:.2f}"] = round(2 * math.sqrt(a_raw / math.pi) / UPSAMPLE * UM_PER_PX, 3)

    # -- Blaisot & Yon: blur width and contrast-corrected size --
    r25, r61, r77 = (row[f"d_l{l:.2f}"] / 2 for l in BLAISOT_LEVELS)
    if tau is not None and all(np.isfinite([r25, r61, r77])):
        C0 = c0_from(row["contrast"], tau)
        pw = p_width(C0)
        row["chi_um"] = round(math.sqrt(2.0) * (r77 - r25) / pw, 3) if pw > 0 else float("nan")
        row["d_blaisot_um"] = round(2 * r61 * p_level(0.61, C0), 3)
        row["C0"] = round(C0, 4)
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
    """Everything dark in a bead-free ('bg') capture: specks on the window, the sensor or the slide, which
    stay at the same pixels whatever the beads do (an averaged spray frame shows ~200 of them)."""
    return [(b["cx"], b["cy"]) for b in find_beads(T)]


def _not_dust(b: dict, dust) -> bool:
    return all(math.hypot(b["cx"] - x, b["cy"] - y) > max(DUST_PX, b["d_px"] / 2) for x, y in dust)


def detect_and_identify(T, sizes, tau=None, dust=()) -> tuple[list[dict], float]:
    beads = [b for b in find_beads(T) if _not_dust(b, dust)]
    rows = [measure_at(T, b["cx"], b["cy"], b["d_px"], tau) for b in beads]
    rows = [r for r in rows if r and r.get("detected")]
    if len(sizes) == 1:                                   # a single-size slide: drop clumps and dust
        d = np.asarray([r.get("d_l0.50", np.nan) for r in rows], float)
        med = float(np.nanmedian(d)) if np.isfinite(d).any() else np.nan
        out = []
        for r in rows:
            if np.isfinite(med) and abs(r.get("d_l0.50", np.nan) / med - 1) <= 0.35:
                r["certified_um"] = sizes[0]
                out.append(r)
        return out, (med / sizes[0] if np.isfinite(med) else float("nan"))
    ids, k = assign_sizes([r.get("d_l0.50", np.nan) for r in rows], sizes)
    out = []
    for r, s in zip(rows, ids):
        if s is not None:
            r["certified_um"] = s
            out.append(r)
    return out, k


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


def through_focus(caps: list[Capture], targets: dict, max_frames: int, tau_hint=None, dust=()) -> tuple[list, dict]:
    """The traverse of one slide: beads found in its z = 0 capture, followed through every z."""
    caps = sorted(caps, key=lambda c: c.z_mm)
    ref = min(caps, key=lambda c: abs(c.z_mm))
    sizes = _slide_sizes(ref.slide, ref.target, targets)
    T_ref = transmission(average_frames(ref.run, max_frames))
    beads, k = detect_and_identify(T_ref, sizes, dust=dust)
    tau = tau_hint if tau_hint is not None else _tau(beads)
    rows = []
    for c in caps:
        T = T_ref if c is ref else transmission(average_frames(c.run, max_frames))
        for i, b in enumerate(beads):
            r = measure_at(T, b["cx"], b["cy"], b["certified_um"] / UM_PER_PX, tau)
            if r is None:
                continue
            r.update(bead=i, certified_um=b["certified_um"], z_mm=c.z_mm, run=c.run.name, slide=c.slide)
            rows.append(r)
    return rows, {"slide": ref.slide, "reference_run": ref.run.name, "n_beads": len(beads),
                  "scale_k": round(k, 4) if np.isfinite(k) else None, "tau": tau}


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
        med = _median(d_in)
        out.append({"run": c.run.name, "certified_um": cert, "n_detected": len(rr), "n_in_focus": len(d_in),
                    "in_focus_share": round(len(d_in) / len(rr), 3) if rr else None,
                    "d_in_focus_median_um": round(med, 2),
                    "bias_pct": round(100 * (med / cert - 1), 1) if cert and np.isfinite(med) else None})
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


def analyse(paths, out: Path, targets_path: Path | None = None, max_frames: int = MAX_FRAMES) -> dict:
    caps = find_captures(paths)
    if not caps:
        sys.exit("no calibration captures (Notes starting BEAD or RETICLE) under " + ", ".join(map(str, paths)))
    targets = load_targets(targets_path)
    out.mkdir(parents=True, exist_ok=True)
    result = {"version": VERSION, "made": datetime.now().isoformat(timespec="seconds"),
              "captures": len(caps), "um_per_px_assumed": UM_PER_PX, "focus_max": FOCUS_MAX,
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
    tau = None
    for slide in sorted({c.slide for c in caps if c.kind == "z"}):
        zc = [c for c in caps if c.kind == "z" and c.slide == slide]
        rows, info = through_focus(zc, targets, max_frames, dust=dust)
        tau = info["tau"] if tau is None else tau
        rows_depth += rows
        result["through_focus"][slide] = {"info": info}
        for cert in sorted({r["certified_um"] for r in rows}):
            result["through_focus"][slide][f"{cert:g}"] = depth_summary(
                [r for r in rows if r["certified_um"] == cert], cert)

    # at focus: the traverse's z = 0 plus every 'focus' capture
    rows_focus = [dict(r) for r in rows_depth if r["z_mm"] == 0]
    for c in [c for c in caps if c.kind == "focus"]:
        T = transmission(average_frames(c.run, max_frames))
        sizes = _slide_sizes(c.slide, c.target, targets)
        beads, _k = detect_and_identify(T, sizes, dust=dust)
        t = tau if tau is not None else _tau(beads)
        for r in beads:
            r2 = measure_at(T, r["cx"], r["cy"], r["certified_um"] / UM_PER_PX, t)
            if r2 and r2.get("detected"):
                r2.update(certified_um=r["certified_um"], z_mm=0.0, run=c.run.name, slide=c.slide)
                rows_focus.append(r2)
    tau = tau if tau is not None else _tau(rows_focus)
    for cert in sorted({r["certified_um"] for r in rows_focus}):
        result["at_focus"][f"{cert:g}"] = focus_summary([r for r in rows_focus if r["certified_um"] == cert], cert)
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

    _write_csv(out / "beads_through_focus.csv", rows_depth)
    _write_csv(out / "beads_at_focus.csv", rows_focus)
    depth_for_fig = {k: v for s in result["through_focus"].values() for k, v in s.items() if k != "info"}
    figs = _figures(out, result["at_focus"], depth_for_fig, rows_focus)
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
            L.append(f"| {f['run']} | {f['certified_um']} | {f.get('n_in_focus', '-')} | "
                     f"{f.get('d_in_focus_median_um', f.get('note'))} | {f.get('bias_pct', '-')} |")
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
    a = ap.parse_args()
    targets = a.targets
    if targets is None:
        for p in [a.paths[0]] + list(a.paths[0].resolve().parents)[:5]:
            if (p / "targets.json").is_file():
                targets = p / "targets.json"
                break
    R = analyse(a.paths, a.out, targets, a.max_frames)
    print(f"{R['captures']} captures; targets {targets or '(built-in sizes)'}")
    for s, v in sorted(R["at_focus"].items(), key=lambda kv: float(kv[0])):
        print(f"  {s:>7} um: {v['n_beads']:3d} beads at focus, current sizer {v['d_current_median_um']} um "
              f"({v['bias_current_pct']}%), l* {v['level_star']}, rings {v['ring_share']}")
    print("written:", *R["_files"], sep="\n  ")


if __name__ == "__main__":
    main()
