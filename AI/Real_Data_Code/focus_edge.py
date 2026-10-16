#!/usr/bin/env python3
"""
focus_edge.py -- how sharp an edge is: the focus meter (sizer 3.0.0 plan, Phase 1, 2026-10-16;
docs/notes/2026-10-15_sizer_3.0.0_plan.md).

The spray-day focus target is a 300 um precision pinhole held on the orifice axis (a bright disc on a dark
frame). Any disc works the same way (a chrome dot: dark on bright), and so does a straight edge (a reticle square,
a razor blade). The meter fits the edge-spread function of our Gaussian point-spread function to the edge:

    I(r) = lo + (hi - lo) * Phi((r - R) / sigma)        Phi = the standard normal CDF

over every pixel near the edge (a disc: r = distance from its centre, so the profile is averaged all the way
round; a straight edge: the signed distance from the fitted line). The blur width in Blaisot & Yon's terms,
exp(-2 r^2 / chi^2), has sigma = chi / 2, so

    chi = 2 * sqrt(sigma^2 - 1/12) * um_per_px

(the 1/12 px^2 is the pixel's own width, so chi is the optics' blur, comparable across set-ups). On the beads
(2026-10-15) chi was ~13 um at best focus and grew ~8 um per mm, so |z| from best focus ~ (chi - chi_best) / 8 um.
chi does not say which side of focus: step one way and watch it. The fitted disc's diameter, against the target's
certificate, is a scale check.

numpy only (no scipy: the lab PC's GUI runs it). Used live by GUI_Clean's Focus check panel, and on a 'FOCUS
CHECK' capture (averaged frames) from the command line:

    python focus_edge.py "<LaCie>/Experiments/2026/10/20" --certified-um 300 --out "<folder for focus_check.json>"
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import optics  # noqa: E402

VERSION = "1.0.0"
PINHOLE_UM = 300.0          # the spray-day target (Ben, 2026-10-16)
K_UM_PER_MM = 8.0           # blur growth per mm off focus (beads, 2026-10-15)
GREEN_TOL_UM = 2.0          # "in focus": within this of the best chi seen (~0.25 mm)
ROTATION_TOL_MM = 0.2       # the 0 / 180 degree readings may differ by this much before re-seating
NOTE_PREFIX = "FOCUS CHECK"


class FocusError(ValueError):
    pass


# ---- the edge-spread fit (numpy only) ----------------------------------------------------------------------

def _erf(x):
    """Abramowitz & Stegun 7.1.26 (|error| < 1.5e-7): numpy, no scipy."""
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t \
        * np.exp(-a * a)
    return s * y


def _Phi(u):
    return 0.5 * (1.0 + _erf(u / math.sqrt(2.0)))


def fit_esf(r: np.ndarray, v: np.ndarray, r0: float, sigma0: float = 1.0, iters: int = 60) -> dict:
    """Least-squares fit of v = lo + (hi - lo) Phi((r - R)/sigma) by Levenberg-Marquardt. r in px."""
    r = np.asarray(r, float)
    v = np.asarray(v, float)
    inner, outer = v[r < r0 - 2], v[r > r0 + 2]
    lo = float(np.median(inner)) if inner.size else float(v.min())
    hi = float(np.median(outer)) if outer.size else float(v.max())
    p = np.array([lo, hi, float(r0), max(float(sigma0), 0.3)])
    lam = 1e-3

    def model(q):
        u = (r - q[2]) / q[3]
        return q[0] + (q[1] - q[0]) * _Phi(u), u

    m, u = model(p)
    cost = float(((v - m) ** 2).sum())
    for _ in range(iters):
        phi = np.exp(-0.5 * u * u) / math.sqrt(2 * math.pi)
        P = _Phi(u)
        amp = p[1] - p[0]
        J = np.column_stack([1.0 - P, P, -amp * phi / p[3], -amp * phi * u / p[3]])
        g = J.T @ (v - m)
        H = J.T @ J
        step = np.linalg.solve(H + lam * np.diag(np.diag(H) + 1e-12), g)
        q = p + step
        q[3] = max(q[3], 0.05)
        m2, u2 = model(q)
        c2 = float(((v - m2) ** 2).sum())
        if c2 < cost:
            p, m, u, cost, lam = q, m2, u2, c2, lam * 0.3
            if np.abs(step).max() < 1e-6:
                break
        else:
            lam *= 10.0
            if lam > 1e8:
                break
    amp = p[1] - p[0]
    return {"lo": float(p[0]), "hi": float(p[1]), "R": float(p[2]), "sigma_px": float(p[3]),
            "rms_rel": float(math.sqrt(cost / max(len(v), 1)) / abs(amp)) if amp else float("inf")}


def _chi_um(sigma_px: float, um_per_px: float) -> tuple[float, float]:
    """(chi of the optics, chi as measured): the pixel's own 1/12 px^2 taken out of the first."""
    raw = 2.0 * sigma_px * um_per_px
    opt = 2.0 * math.sqrt(max(sigma_px ** 2 - 1.0 / 12.0, 0.0)) * um_per_px
    return opt, raw


# ---- a disc (pinhole or dot) -------------------------------------------------------------------------------

def find_disc(img: np.ndarray) -> tuple[float, float, float, str]:
    """The target disc: (cx, cy, radius px, 'bright' | 'dark'). The disc is the smaller of the two tones; its
    largest piece not touching the frame edge."""
    import cv2
    a = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 1.5)
    med, top, bot = float(np.median(a)), float(a.max()), float(a.min())
    if top - bot < 1e-6:
        raise FocusError("a flat image: nothing to focus on")
    # the target is what stands out from the frame's median (the background): a pinhole far brighter, a dot far
    # darker. It may cover a tiny share of the frame (a 300 um pinhole is ~0.03 % of 2048 x 1152).
    noise = float(np.median(np.abs(a - med))) * 1.4826 + 1e-9
    if max(top - med, med - bot) < 8 * noise:
        raise FocusError("nothing stands out from the background (is the target in view and lit?)")
    polarity = "bright" if top - med >= med - bot else "dark"
    mask = a > (med + top) / 2 if polarity == "bright" else a < (med + bot) / 2
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    H, W = a.shape
    best = None
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1 or area < 12:
            continue
        if best is None or area > best[1]:
            best = (i, area)
    if best is None:
        raise FocusError("no whole disc in view (is the target in the field, away from the edges?)")
    i, area = best
    return float(cent[i][0]), float(cent[i][1]), math.sqrt(area / math.pi), polarity


def disc_edge(img: np.ndarray, um_per_px: float, certified_um: float | None = None) -> dict:
    """The blur width chi of a disc's edge, its diameter, and the scale check against its certificate."""
    a = img.astype(np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    cx, cy, r_guess, polarity = find_disc(a)
    H, W = a.shape
    band = max(6.0, 0.5 * r_guess)
    y0, y1 = max(0, int(cy - r_guess - band - 2)), min(H, int(cy + r_guess + band + 3))
    x0, x1 = max(0, int(cx - r_guess - band - 2)), min(W, int(cx + r_guess + band + 3))
    sub = a[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    for _ in range(2):                                   # re-centre on the disc's own light / darkness
        r = np.hypot(xx - cx, yy - cy)
        lo_v, hi_v = np.percentile(sub, [2, 98])
        w = (sub - lo_v) / max(hi_v - lo_v, 1e-9)
        w = np.clip(w if polarity == "bright" else 1 - w, 0, 1) * (r < r_guess + 2)
        if w.sum() > 0:
            cx, cy = float((xx * w).sum() / w.sum()), float((yy * w).sum() / w.sum())
    r = np.hypot(xx - cx, yy - cy)
    sel = (r > max(0.4 * r_guess, r_guess - band)) & (r < r_guess + band)
    f = fit_esf(r[sel], sub[sel], r_guess)
    # A blurred disc's half-level edge sits inside its true edge by ~sigma^2 / 2R (the curvature: a straight-edge
    # profile fitted to a circle); 0.01 px at best focus, 0.13 px for a 300 um disc 3.5 mm off.
    f["R"] = f["R"] + f["sigma_px"] ** 2 / (2 * f["R"])
    chi_opt, chi_raw = _chi_um(f["sigma_px"], um_per_px)
    d_um = 2 * f["R"] * um_per_px
    out = {"ok": bool(f["rms_rel"] < 0.25 and 0 < f["sigma_px"] < band), "shape": "disc", "polarity": polarity,
           "cx": round(cx, 2), "cy": round(cy, 2), "radius_px": round(f["R"], 3), "diameter_um": round(d_um, 2),
           "sigma_px": round(f["sigma_px"], 4), "chi_um": round(chi_opt, 2), "chi_raw_um": round(chi_raw, 2),
           "contrast": round(abs(f["hi"] - f["lo"]) / max(abs(f["hi"]), abs(f["lo"]), 1e-9), 3),
           "fit_rms_rel": round(f["rms_rel"], 4), "n_px": int(sel.sum()), "um_per_px": um_per_px}
    if certified_um:
        out["certified_um"] = certified_um
        out["um_per_px_from_target"] = round(certified_um / (2 * f["R"]), 4)
        out["scale_error_pct"] = round(100 * (d_um / certified_um - 1), 2)
    return out


# ---- a straight edge (a reticle square, a razor blade) -----------------------------------------------------

def line_edge(img: np.ndarray, um_per_px: float) -> dict:
    """The blur width of the one straight edge in the image (or a crop of it)."""
    import cv2
    a = img.astype(np.float64)
    if a.ndim == 3:
        a = a.mean(axis=2)
    g = cv2.GaussianBlur(a.astype(np.float32), (0, 0), 1.0)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    thr = np.percentile(mag, 97)
    ys, xs = np.nonzero(mag >= thr)
    if xs.size < 10:
        raise FocusError("no edge in view")
    pts = np.column_stack([xs, ys]).astype(float)
    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c)
    normal = vt[1]                                      # perpendicular to the line
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    d = (xx - c[0]) * normal[0] + (yy - c[1]) * normal[1]
    sel = np.abs(d) < 8
    f = fit_esf(d[sel], a[sel], 0.0)
    chi_opt, chi_raw = _chi_um(f["sigma_px"], um_per_px)
    return {"ok": bool(f["rms_rel"] < 0.25 and 0 < f["sigma_px"] < 8), "shape": "line",
            "sigma_px": round(f["sigma_px"], 4), "chi_um": round(chi_opt, 2), "chi_raw_um": round(chi_raw, 2),
            "contrast": round(abs(f["hi"] - f["lo"]) / max(abs(f["hi"]), abs(f["lo"]), 1e-9), 3),
            "fit_rms_rel": round(f["rms_rel"], 4), "n_px": int(sel.sum()), "um_per_px": um_per_px}


# ---- what the numbers mean ---------------------------------------------------------------------------------

def z_off_mm(chi_um: float, chi_best_um: float, k_um_per_mm: float = K_UM_PER_MM) -> float:
    """Roughly how far from best focus (either side), from the blur's growth ~8 um per mm."""
    return max(chi_um - chi_best_um, 0.0) / k_um_per_mm


def in_focus(chi_um: float, chi_best_um: float, tol_um: float = GREEN_TOL_UM) -> bool:
    return chi_um <= chi_best_um + tol_um


def rotation_midpoint(rail_0_mm: float, rail_180_mm: float) -> dict:
    """The 180-degree check: a thin foil off the axis by e sits at -e once turned round, so the axis plane is
    midway between the two best-focus rail readings."""
    diff = abs(rail_180_mm - rail_0_mm)
    return {"axis_rail_mm": round((rail_0_mm + rail_180_mm) / 2, 3), "difference_mm": round(diff, 3),
            "ok": diff <= ROTATION_TOL_MM}


def summary_text(rec: dict) -> str:
    """One line for run_summary ('Focus check')."""
    bits = [rec.get("when", "?"), f"chi {rec.get('chi_um')} um"]
    if rec.get("diameter_um") is not None:
        bits.append(f"target {rec['diameter_um']} um")
    if rec.get("axis_rail_mm") is not None:
        bits.append(f"axis at rail {rec['axis_rail_mm']} mm (0/180 differ {rec.get('difference_mm')} mm)")
    elif rec.get("rail_mm") is not None:
        bits.append(f"rail {rec['rail_mm']} mm")
    return ", ".join(bits)


# ---- a FOCUS CHECK capture ---------------------------------------------------------------------------------

def focus_runs(paths) -> list[Path]:
    """Run folders whose Notes start with 'FOCUS CHECK'."""
    import bead_calibration as bc
    out = []
    for p in paths:
        p = Path(p)
        xs = [p / "run_summary.xlsx"] if (p / "run_summary.xlsx").is_file() else sorted(p.rglob("run_summary.xlsx"))
        for x in xs:
            if str(bc.read_meta(x).get("Notes") or "").strip().upper().startswith(NOTE_PREFIX):
                out.append(x.parent)
    return out


def analyse_capture(run: Path, certified_um: float = PINHOLE_UM, max_frames: int = 20) -> dict:
    import bead_calibration as bc
    img = bc.average_frames(run, max_frames)
    um = optics.um_per_px(run)
    r = disc_edge(img, um, certified_um)
    r.update(run=run.name, optics_profile=optics.profile_for(run)["name"], frames_averaged=max_frames)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, help="FOCUS CHECK run folders, or day folders holding them")
    ap.add_argument("--certified-um", type=float, default=PINHOLE_UM)
    ap.add_argument("--out", type=Path, required=True, help="where focus_check.json goes (not a capture folder)")
    a = ap.parse_args()
    runs = focus_runs(a.paths)
    if not runs:
        sys.exit(f"no runs with Notes starting '{NOTE_PREFIX}' under " + ", ".join(map(str, a.paths)))
    res = []
    for run in runs:
        try:
            res.append(analyse_capture(run, a.certified_um))
        except FocusError as e:
            res.append({"run": run.name, "ok": False, "why": str(e)})
    best = min((r["chi_um"] for r in res if r.get("ok")), default=None)
    for r in res:
        if r.get("ok") and best is not None:
            r["z_off_mm_vs_best"] = round(z_off_mm(r["chi_um"], best), 3)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "focus_check.json").write_text(json.dumps({"version": VERSION, "made": datetime.now().isoformat(
        timespec="seconds"), "captures": res}, indent=1), encoding="utf-8")
    for r in res:
        print(f"{r['run']}: " + (f"chi {r['chi_um']} um, target {r['diameter_um']} um "
                                 f"(scale {r.get('scale_error_pct')} %)" if r.get("ok") else f"not measured: {r.get('why')}"))
    print("written:", a.out / "focus_check.json")


if __name__ == "__main__":
    main()
