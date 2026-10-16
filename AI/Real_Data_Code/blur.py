#!/usr/bin/env python3
"""
blur.py -- the blur width chi and the size of one droplet or bead, measured exactly as the beads that calibrated
sizer 3.0.0 were measured, and sizer 3.0.0's rule on top (sizer 3.0.0 plan, Phase 4, 2026-10-16).

Shared by bead_calibration.py (which measured the beads with it), sizer_calibration.py (which built the look-up
table from them) and measure_run.py (which sizes spray droplets with it), so a droplet and a bead go through the same
code. numpy + OpenCV only: the lab PC runs the pipeline and has no scipy.

The measurement (Blaisot & Yon 2005, Exp. Fluids 39:977-994):
  * re-centre on the darkness near the given centre; a window of max(14, 1.5 d + 12) px each way, which must fit
    inside the frame (else None: a droplet that close to the edge is not measured);
  * the object = the T < 0.95 piece at the centre (light 1 px smoothing); its core transmission (the caller's
    estimator: measure_run.droplet_core), contrast C = (1 - core) / (1 + core);
  * the diameter at relative grey levels l (level = core + l (1 - core)) on a 4x bicubic upsample, holes filled;
  * chi = sqrt(2) (r_0.77 - r_0.25) / p_width(C0) and the contrast-corrected size 2 r_0.61 p_0.61(C0), where
    C0 = C / ((1 - tau)(1 + C) - C) and p_* come from Blaisot's Gaussian-PSF disc model.

The rule (the optics profile's calibration block, from sizer_calibration.py):
    chi <= chi_sharp              sized directly: the size read minus the edge offset
    chi_sharp < chi <= chi_max    sized through the look-up table (Delta held beyond its bead sizes: extrapolated)
    beyond chi_max                outside the measurement volume
    below d_min                   counted, not sized
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL_FILE = HERE / "blaisot_model.json"
BLAISOT_LEVELS = (0.25, 0.61, 0.77)
MODEL_LEVELS = (0.25, 0.5, 0.61, 0.77)
UPSAMPLE = 4                  # the level curves are measured on a 4x bicubic upsample (less pixel staircase)
DETECT_T = 0.95               # as extract_candidates: anything darker is part of the object
RECENTRE_PX = 3               # how far the darkness may sit from the centre given
SMOOTH_SIGMA = 1.0            # light smoothing for finding the object and re-centring
SIZERS = ("3.0.0", "2.2.0", "2.1.0")
DEFAULT_SIZER = "3.0.0"       # Ben, 2026-10-16: the default everywhere; 2.2.0 / 2.1.0 only when asked for


# ---- Blaisot's Gaussian-PSF disc model ----------------------------------------------------------------------

# Cephes' Chebyshev coefficients for the exponentially scaled Bessel function I0e (as scipy.special.i0e and
# numpy.i0 use them): agrees with scipy to ~1e-15.
_I0E_A = (-4.41534164647933937950E-18, 3.33079451882223809783E-17, -2.43127984654795469359E-16,
          1.71539128555513303061E-15, -1.16853328779934516808E-14, 7.67618549860493561688E-14,
          -4.85644678311192946090E-13, 2.95505266312963983461E-12, -1.72682629144155570723E-11,
          9.67580903537323691224E-11, -5.18979560163526290666E-10, 2.65982372468238665035E-9,
          -1.30002500998624804212E-8, 6.04699502254191894932E-8, -2.67079385394061173391E-7,
          1.11738753912010371815E-6, -4.41673835845875056359E-6, 1.64484480707288970893E-5,
          -5.75419501008210370398E-5, 1.88502885095841655729E-4, -5.76375574538582365885E-4,
          1.63947561694133579842E-3, -4.32430999505057594430E-3, 1.05464603945949983183E-2,
          -2.37374148058994688156E-2, 4.93052842396707084878E-2, -9.49010970480476444210E-2,
          1.71620901522208775349E-1, -3.04682672343198398683E-1, 6.76795274409476084995E-1)
_I0E_B = (-7.23318048787475395456E-18, -4.83050448594418207126E-18, 4.46562142029675999901E-17,
          3.46122286769746109310E-17, -2.82762398051658348494E-16, -3.42548561967721913462E-16,
          1.77256013305652638360E-15, 3.81168066935262242075E-15, -9.55484669882830764870E-15,
          -4.15056934728722208663E-14, 1.54008621752140982691E-14, 3.85277838274214270114E-13,
          7.18012445138366623367E-13, -1.79417853150680611778E-12, -1.32158118404477131188E-11,
          -3.14991652796324136454E-11, 1.18891471078464383424E-11, 4.94060238822496958910E-10,
          3.39623202570838634515E-9, 2.26666899049817806459E-8, 2.04891858946906374183E-7,
          2.89137052083475648297E-6, 6.88975834691682398426E-5, 3.36911647825569408990E-3,
          8.04490411014108831608E-1)


def _chbevl(x, coef):
    b0 = np.zeros_like(x)
    b1 = np.zeros_like(x)
    b2 = b1
    for c in coef:
        b2, b1 = b1, b0
        b0 = x * b1 - b2 + c
    return 0.5 * (b0 - b2)


def i0e(x) -> np.ndarray:
    """exp(-|x|) I0(x)."""
    x = np.abs(np.asarray(x, float))
    out = np.empty_like(x)
    lo = x <= 8.0
    out[lo] = _chbevl(x[lo] / 2.0 - 2.0, _I0E_A)
    out[~lo] = _chbevl(32.0 / x[~lo] - 2.0, _I0E_B) / np.sqrt(x[~lo])
    return out


def compute_model(levels=MODEL_LEVELS) -> dict:
    """For a grid of a~ = sqrt(2) a / chi (a = geometric radius, chi = PSF half-width, s(r) = exp(-2 r^2/chi^2)): the
    normalised contrast C0 = (1 - e^-a~^2)/(1 + e^-a~^2) and the level radii r~_l of the image profile (Eq. 5 with
    tau = 0; r~_l does not depend on tau, Sect. 2.5). ~8 s: blaisot_model() reads the stored copy."""
    a_grid = np.linspace(0.08, 6.0, 150)
    r = np.linspace(0.0, 12.0, 2401)
    radii = {l: [] for l in levels}
    for a in a_grid:
        rho = np.linspace(0.0, a, 500)
        # e^{-r^2 - rho^2} I0(2 r rho) = e^{-(r - rho)^2} i0e(2 r rho): no overflow
        f = rho[None, :] * np.exp(-(r[:, None] - rho[None, :]) ** 2) * i0e(2.0 * r[:, None] * rho[None, :])
        prof = 1.0 - 2.0 * np.trapezoid(f, rho, axis=1) if hasattr(np, "trapezoid") else \
            1.0 - 2.0 * np.trapz(f, rho, axis=1)
        pmin = prof[0]
        for l in levels:
            thr = pmin + l * (1.0 - pmin)
            j = max(int(np.argmax(prof >= thr)), 1)
            r0, r1, p0, p1 = r[j - 1], r[j], prof[j - 1], prof[j]
            radii[l].append(float(r0 + (thr - p0) * (r1 - r0) / (p1 - p0)) if p1 != p0 else float(r1))
    e = np.exp(-a_grid ** 2)
    return {"a": a_grid.tolist(), "C0": ((1 - e) / (1 + e)).tolist(), "r": {f"{l:.2f}": radii[l] for l in levels}}


_MODEL: dict | None = None


def blaisot_model() -> dict:
    """The model, from the stored copy (written by compute_model; a test checks the two agree), cached."""
    global _MODEL
    if _MODEL is None:
        m = json.loads(MODEL_FILE.read_text(encoding="utf-8")) if MODEL_FILE.is_file() else compute_model()
        _MODEL = {"a": np.asarray(m["a"]), "C0": np.asarray(m["C0"]),
                  "r": {float(l): np.asarray(v) for l, v in m["r"].items()}}
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


# ---- one object -------------------------------------------------------------------------------------------

def fill_holes(mask: np.ndarray) -> np.ndarray:
    """scipy.ndimage.binary_fill_holes with its default (4-connected background), in OpenCV."""
    m = np.pad(mask.astype(np.uint8), 1)
    h, w = m.shape
    cv2.floodFill(m, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 2, flags=4)
    return (m != 2)[1:-1, 1:-1]


def component_at(mask: np.ndarray, y: int, x: int) -> np.ndarray:
    """The 8-connected piece of `mask` at (y, x), or the nearest piece if (y, x) is not in it."""
    n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    if n < 2:
        return np.zeros_like(mask, bool)
    k = lab[y, x]
    if k == 0:
        ys, xs = np.nonzero(lab)
        j = int(np.argmin((ys - y) ** 2 + (xs - x) ** 2))
        k = lab[ys[j], xs[j]]
    return lab == k


def half_window(d_px: float) -> int:
    return int(max(14, 1.5 * d_px + 12))


def border_weight(d_px: float, shape) -> float:
    """A droplet is measured only if its window fits in the frame, i.e. its centre lies at least half_window from
    every edge: of a W x H frame only (W - 2h)(H - 2h) can hold it. Each one measured stands for W H / that many
    (the border correction for a concentration; sizer 3.0.0 plan, Phase 5)."""
    H, W = shape
    h = half_window(d_px)
    return float(W * H) / max(1.0, (W - 2.0 * h) * (H - 2.0 * h))


def locate(T: np.ndarray, cx: float, cy: float, d_px: float, nearest: bool = True,
           blank: np.ndarray | None = None) -> dict | None:
    """Re-centre and cut the window. None if the window does not fit in the frame. Smooths only a crop around the
    object (with a margin wider than the smoothing kernel): the same numbers as smoothing the whole frame.

    For a spray droplet (measure_run, sizer 3.0.0): `blank` (frame-sized bool) marks the OTHER objects, set to
    background (T = 1) before anything is measured, so only the droplet's own profile counts; and `nearest=False`
    takes no other piece when the centre itself is not dark (a bead is isolated, so the nearest piece is the bead;
    in a spray it is a neighbour or the jet)."""
    H, W = T.shape
    half = half_window(d_px)
    x0r, x1r = int(round(cx)) - RECENTRE_PX, int(round(cx)) + RECENTRE_PX + 1
    y0r, y1r = int(round(cy)) - RECENTRE_PX, int(round(cy)) + RECENTRE_PX + 1
    if x0r < 0 or y0r < 0 or x1r > W or y1r > H:
        return None
    reach = half + half // 2 + RECENTRE_PX + 2 + 5
    gx0, gx1 = max(0, int(round(cx)) - reach), min(W, int(round(cx)) + reach + 1)
    gy0, gy1 = max(0, int(round(cy)) - reach), min(H, int(round(cy)) + reach + 1)
    Tg = np.ascontiguousarray(T[gy0:gy1, gx0:gx1])
    if blank is not None:
        Tg = Tg.copy()
        Tg[blank[gy0:gy1, gx0:gx1]] = 1.0
    Ts = cv2.GaussianBlur(Tg, (0, 0), SMOOTH_SIGMA)

    def sm(ya, yb, xa, xb):                      # the smoothed frame's [ya:yb, xa:xb], in frame coordinates
        return Ts[ya - gy0:yb - gy0, xa - gx0:xb - gx0]

    wy0, wy1 = max(0, y0r - half // 2), min(H, y1r + half // 2)
    wx0, wx1 = max(0, x0r - half // 2), min(W, x1r + half // 2)
    win = np.clip(1.0 - sm(wy0, wy1, wx0, wx1), 0, None)
    if win.sum() > 0:
        yy, xx = np.mgrid[0:win.shape[0], 0:win.shape[1]]
        ucx = wx0 + float((xx * win).sum() / win.sum())
        ucy = wy0 + float((yy * win).sum() / win.sum())
        if math.hypot(ucx - cx, ucy - cy) <= RECENTRE_PX + 1:
            cx, cy = ucx, ucy
    xc, yc = int(round(cx)), int(round(cy))
    x0, x1, y0, y1 = xc - half, xc + half + 1, yc - half, yc + half + 1
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
        return None
    Tsc = sm(y0, y1, x0, x1)
    cand = Tsc < DETECT_T
    if not nearest and not cand[half, half]:
        m = np.zeros_like(cand)
    else:
        m = component_at(cand, half, half) if cand.any() else np.zeros_like(cand)
    Tc = Tg[y0 - gy0:y1 - gy0, x0 - gx0:x1 - gx0]
    return {"cx": cx, "cy": cy, "half": half, "x0": x0, "y0": y0, "Tc": Tc, "Tsc": Tsc, "m": m}


def edge_sizes(Tc: np.ndarray, m: np.ndarray, core: float, um_per_px: float, tau: float | None,
               levels=()) -> dict:
    """The level-curve diameters (filled `d_l<l>` and raw `draw_l<l>`) for `levels` plus the Blaisot levels and 0.5,
    and with tau the blur width chi_um, the contrast-corrected size d_blaisot_um and C0."""
    row = {}
    U = cv2.resize(Tc, None, fx=UPSAMPLE, fy=UPSAMPLE, interpolation=cv2.INTER_CUBIC)
    near = cv2.resize(cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)), (U.shape[1], U.shape[0]),
                      interpolation=cv2.INTER_NEAREST).astype(bool)
    for l in sorted(set(levels) | set(BLAISOT_LEVELS) | {0.5}):
        thr = core + l * (1.0 - core)
        reg = (U < thr) & near
        if not reg.any():
            row[f"d_l{l:.2f}"] = row[f"draw_l{l:.2f}"] = float("nan")
            continue
        n, lab, stats, _c = cv2.connectedComponentsWithStats(reg.astype(np.uint8), connectivity=8)
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        comp_l = lab == big
        a_raw = float(comp_l.sum())
        a_fill = float(fill_holes(comp_l).sum())
        row[f"d_l{l:.2f}"] = round(2 * math.sqrt(a_fill / math.pi) / UPSAMPLE * um_per_px, 3)
        row[f"draw_l{l:.2f}"] = round(2 * math.sqrt(a_raw / math.pi) / UPSAMPLE * um_per_px, 3)
    r25, r61, r77 = (row[f"d_l{l:.2f}"] / 2 for l in BLAISOT_LEVELS)
    if tau is not None and all(np.isfinite([r25, r61, r77])):
        C = (1 - core) / (1 + core)
        C0 = c0_from(round(C, 4), tau)
        pw = p_width(C0)
        row["chi_um"] = round(math.sqrt(2.0) * (r77 - r25) / pw, 3) if pw > 0 else float("nan")
        row["d_blaisot_um"] = round(2 * r61 * p_level(0.61, C0), 3)
        row["C0"] = round(C0, 4)
    return row


def measure(T: np.ndarray, cx: float, cy: float, d_px: float, tau: float, core_fn, um_per_px: float,
            nearest: bool = True, blank: np.ndarray | None = None) -> dict | None:
    """One object, as the beads were measured: None if its window does not fit in the frame; else cx, cy, core_t,
    contrast, d_l0.50, chi_um and d_blaisot_um (nan when there is no edge to measure). `nearest` and `blank`: see
    locate (a spray droplet among others)."""
    loc = locate(T, cx, cy, d_px, nearest, blank)
    if loc is None:
        return None
    out = {"cx": round(loc["cx"], 2), "cy": round(loc["cy"], 2), "chi_um": float("nan"),
           "d_blaisot_um": float("nan"), "d_l0.50": float("nan")}
    if not loc["m"].any():
        return out
    core = float(core_fn(loc["Tc"], loc["m"]))
    out.update(core_t=round(core, 4), contrast=round((1 - core) / (1 + core), 4))
    out.update(edge_sizes(loc["Tc"], loc["m"], core, um_per_px, tau))
    return out


def _perimeter(region: np.ndarray) -> float:
    """Outline length of a binary region, its contour smoothed over 5 points so the pixel staircase does not
    lengthen it (a stepped circle reads ~8 % long unsmoothed)."""
    cnts, _ = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    total = 0.0
    for c in cnts:
        p = c[:, 0, :].astype(np.float64)
        if len(p) < 6:
            total += cv2.arcLength(c, True)
            continue
        k = np.ones(5) / 5.0
        q = np.vstack([np.convolve(np.concatenate([p[-2:, i], p[:, i], p[:2, i]]), k, mode="valid")
                       for i in range(2)]).T
        total += float(np.sum(np.hypot(*np.diff(np.vstack([q, q[:1]]), axis=0).T)))
    return total


def object_chi(T: np.ndarray, mask: np.ndarray, x0: int, y0: int, tau: float, core_fn, um_per_px: float,
               others: np.ndarray | None = None, margin: int = 10) -> dict:
    """The blur width of an object of ANY shape (a ligament or a blob; sizer 3.0.0 plan, Phase 5): Blaisot's edge
    width generalised. For a disc, chi = sqrt(2) (r_0.77 - r_0.25) / p_width(C0); here r_0.77 - r_0.25 becomes the
    area between the object's 0.77 and 0.25 level sets over their mean (smoothed) outline length, which for a disc
    is exactly r_0.77 - r_0.25. So it agrees with a droplet's chi on discs, and on a long ligament it is its edge's
    own width. `mask` is the object's mask at (x0, y0) in T; `others` (T-sized) marks every object in the frame:
    all but this one (grown by 3 px) are set to background first. Returns chi_um (nan if there is no edge to
    measure), core_t and the contrast."""
    H, W = T.shape
    mh, mw = mask.shape
    gx0, gy0 = max(0, x0 - margin), max(0, y0 - margin)
    gx1, gy1 = min(W, x0 + mw + margin), min(H, y0 + mh + margin)
    Tc = np.array(T[gy0:gy1, gx0:gx1], dtype=np.float32)
    m = np.zeros(Tc.shape, bool)
    m[y0 - gy0:y0 - gy0 + mh, x0 - gx0:x0 - gx0 + mw] = mask
    if others is not None:
        mine = cv2.dilate(m.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        Tc[others[gy0:gy1, gx0:gx1] & ~mine] = 1.0
    out = {"chi_um": float("nan"), "core_t": float("nan"), "contrast": float("nan")}
    if not m.any():
        return out
    Ts = cv2.GaussianBlur(Tc, (0, 0), SMOOTH_SIGMA)
    n, lab = cv2.connectedComponents((Ts < DETECT_T).astype(np.uint8), connectivity=8)
    own = np.isin(lab, np.unique(lab[m & (lab > 0)]))           # its own T < 0.95 piece(s)
    if not own.any():
        return out
    core = float(core_fn(Tc, own & m if (own & m).any() else own))
    C = (1 - core) / (1 + core)
    out.update(core_t=round(core, 4), contrast=round(C, 4))
    up = UPSAMPLE if max(Tc.shape) <= 160 else 1               # big ligaments: native pixels are fine
    U = cv2.resize(Tc, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC) if up > 1 else Tc
    near = cv2.dilate(own.astype(np.uint8), np.ones((5, 5), np.uint8))
    if up > 1:
        near = cv2.resize(near, (U.shape[1], U.shape[0]), interpolation=cv2.INTER_NEAREST)
    near = near.astype(bool)
    reg = {}
    for l in (0.25, 0.77):
        r = (U < core + l * (1.0 - core)) & near
        reg[l] = fill_holes(r) if r.any() else r
    a25, a77 = float(reg[0.25].sum()), float(reg[0.77].sum())
    if a25 <= 0 or a77 <= a25:
        return out
    width = (a77 - a25) / ((_perimeter(reg[0.25]) + _perimeter(reg[0.77])) / 2.0) / up
    pw = p_width(c0_from(round(C, 4), tau))
    out["chi_um"] = round(math.sqrt(2.0) * width * um_per_px / pw, 3) if pw > 0 else float("nan")
    return out


# ---- the look-up table and the rule ------------------------------------------------------------------------

def table_size(d_read, chi, T: dict):
    """Sizes through the table. d_read: the size read (after the edge offset); chi: the blur width. Returns (size,
    sigma, where), where 'in' = between two bead sizes, 'below' / 'above' = beyond the smallest / largest bead
    (Delta held at its value: extrapolated), 'off' = chi beyond the table's reach (size nan)."""
    d_read = np.atleast_1d(np.asarray(d_read, float))
    chi = np.atleast_1d(np.asarray(chi, float))
    g = np.asarray(T["chi_um"], float)
    s = np.asarray(T["nodes_um"], float)
    D = np.asarray(T["delta_um"], float)
    S = np.asarray(T["sigma_um"], float)
    reach = T.get("chi_reach_um") or float(g.max())
    Di = np.vstack([np.interp(chi, g[np.isfinite(r)], r[np.isfinite(r)]) for r in D])     # nodes x droplets
    Si = np.vstack([np.interp(chi, g, r) for r in S])
    pred = s[:, None] + Di
    size = np.full(d_read.shape, np.nan)
    sig = np.full(d_read.shape, np.nan)
    where = np.full(d_read.shape, "off", dtype=object)
    live = np.isfinite(d_read) & np.isfinite(chi) & (chi <= reach)
    lo = live & (d_read < pred[0])
    size[lo], sig[lo], where[lo] = d_read[lo] - Di[0, lo], Si[0, lo], "below"
    hi = live & (d_read > pred[-1])
    size[hi], sig[hi], where[hi] = d_read[hi] - Di[-1, hi], Si[-1, hi], "above"
    for j in range(len(s) - 1):
        a, b = pred[j], pred[j + 1]
        m = live & (where == "off") & (d_read >= a) & (d_read <= b)
        mono = m & (b > a)
        t = np.zeros(d_read.shape)
        t[mono] = (d_read[mono] - a[mono]) / (b[mono] - a[mono])
        size[mono] = s[j] + t[mono] * (s[j + 1] - s[j])
        sig[mono] = Si[j, mono] + t[mono] * (Si[j + 1, mono] - Si[j, mono])
        where[mono] = "in"
        flat = m & ~(b > a)                     # not ordered at this chi (never seen): the nearer bead's Delta
        size[flat], sig[flat], where[flat] = d_read[flat] - Di[j, flat], Si[j, flat], "in"
    return size, sig, where


def size_3(d_read, chi, T: dict, chi_sharp: float, chi_max: float):
    """The 3.0.0 rule on arrays: direct up to chi_sharp, the table up to chi_max, nan beyond. Returns (size, method)
    with method 'direct' | 'table' | 'table_extrapolated' | 'outside'."""
    d_read = np.atleast_1d(np.asarray(d_read, float))
    chi = np.atleast_1d(np.asarray(chi, float))
    size = np.full(d_read.shape, np.nan)
    method = np.full(d_read.shape, "outside", dtype=object)
    direct = np.isfinite(chi) & (chi <= chi_sharp)
    size[direct], method[direct] = d_read[direct], "direct"
    mid = np.isfinite(chi) & (chi > chi_sharp) & (chi <= chi_max)
    if mid.any():
        t, _s, where = table_size(d_read[mid], chi[mid], T)
        size[mid] = t
        method[mid] = np.where(where == "in", "table", np.where(where == "off", "outside", "table_extrapolated"))
    return size, method


class CalibrationMissing(ValueError):
    pass


def sizer3(profile: dict) -> dict:
    """Sizer 3.0.0's settings from an optics profile's calibration block (sizer_calibration --write-profile), with a
    short hash of the block so a run records exactly which calibration sized it."""
    cal = profile.get("calibration") or {}
    need = ("tau", "edge_base", "edge_offset_um", "chi_sharp_um", "chi_max_um", "d_min_um", "lookup_table")
    missing = [k for k in need if cal.get(k) is None]
    if missing:
        raise CalibrationMissing(f"optics profile {profile.get('name')!r} has no sizer 3.0.0 calibration "
                                 f"({', '.join(missing)} missing): run sizer_calibration.py --write-profile")
    return {"profile": profile.get("name"),
            "hash": hashlib.sha256(json.dumps(cal, sort_keys=True).encode()).hexdigest()[:12],
            "tau": float(cal["tau"]), "edge_base": cal["edge_base"],
            "column": "d_blaisot_um" if cal["edge_base"] == "blaisot" else "d_l0.50",
            "edge_offset_um": float(cal["edge_offset_um"]), "chi_sharp_um": float(cal["chi_sharp_um"]),
            "chi_max_um": float(cal["chi_max_um"]), "d_min_um": float(cal["d_min_um"]),
            "table": cal["lookup_table"], "status": cal.get("status", ""),
            "depth_mm": float((cal.get("depth_mm") or {}).get("chi_max") or "nan")}


def resolve_sizer(sizer: str | None = None, sharpness_rule: bool | None = None) -> str:
    """The sizer version: `sizer` when given; else what the old switch says when it is set (2.2.0 with the
    sharpness rule, 2.1.0 without), so every older command, job and run keeps its version; else (nothing asked
    for) the default, 3.0.0."""
    if sizer:
        if sizer not in SIZERS:
            raise ValueError(f"unknown sizer {sizer!r}: one of {', '.join(SIZERS)}")
        return sizer
    if sharpness_rule is None:
        return DEFAULT_SIZER
    return "2.2.0" if sharpness_rule else "2.1.0"
