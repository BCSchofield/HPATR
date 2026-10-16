#!/usr/bin/env python3
"""
size_limit.py -- the smallest droplet this optics can size with confidence (sizer 3.0.0 plan, Phase 2, 2026-10-16;
docs/notes/2026-10-15_sizer_3.0.0_plan.md).

There are no certified beads below 37.36 um (no smaller ones until a 3x lens), and over half the spray's in-focus
droplets read below that. So the limit comes from a MODEL of our optics, checked against the beads where they exist:

  * a droplet = an opaque disc (darkness tau from the beads' core at focus) convolved with Blaisot & Yon's Gaussian
    PSF exp(-2 r^2 / chi^2), on an 8x sub-pixel grid, area-averaged into 10 um pixels at a random sub-pixel
    position, plus the single-frame noise of a real spray frame;
  * measured with exactly the code the beads were measured with (bead_calibration.measure_at): the blur width chi,
    the half-max diameter on native pixels (what the current sizer does) and on a 4x upsample, and Blaisot's
    contrast-corrected diameter;
  * the optical blur at best focus is set so that a 76 um disc reads the chi the real 76 um beads read at focus;
    the edge offset the real beads show (the model has none) is added as one constant; then the model is checked
    against the real beads, static through focus and falling, at 37 / 56 / 76 / 98 um;
  * droplets of each size are scattered evenly through depth (even in |z| is even in optical blur, chi = chi0 +
    k|z|), found if their T < 0.95 piece has >= 4 px, and passed if their measured chi <= chi_max.

"Confident" (Ben, 2026-10-15): the median size of the droplets passed within +-10 % of the true size after the edge
correction, and >= 90 % of the droplets truly inside the measurement volume found and passed. The AI's own
detection is flat at 92-96 % from ~20 to 150 um on the 20 hand-labelled frames (2026-10-02), so it sets no size
limit and is reported, not modelled.

    python size_limit.py --beads "<LaCie>/Calibration/Imaging Work/analysis/2026-10-15" \\
        --noise-run "<LaCie>/Experiments/2026/10/12/125754_..." --out "<LaCie>/Calibration/Imaging Work/analysis/size_limit_2026-10-16"

Writes report.md, size_limit.json, model_grid.csv and fig_size_limit.png into --out; nothing else.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bead_calibration as bc  # noqa: E402
import measure_run as mr  # noqa: E402

VERSION = "1.0.0"
UP = 8                                   # sub-pixel grid for rendering
SIZES_UM = (10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 50.0, 60.0, 80.0, 100.0, 150.0)
BEAD_SIZES = (37.36, 56.28, 76.39, 98.1)
CHI_MAX_TRIED = (15.0, 20.0, 25.0)
BIAS_OK = 0.10                           # "confident": median within +-10 % ...
FOUND_OK = 0.90                          # ... and >= 90 % of the droplets inside the volume found and passed
MIN_AREA_PX = 4                          # the candidate floor (extract_candidates / bead_calibration)
NOISE_T_DEFAULT = 0.022                  # single-frame T noise of a real spray frame (CCD 125754, 2026-10-16)
AI_RECALL = "92-96 % at every size from ~20 to 150 um (IoU >= 0.25; 20 hand-labelled frames, 2026-10-02)"
METHODS = {"halfmax_native": "half-max on native pixels (the current sizer)",
           "halfmax_up4": "half-max on a 4x upsample (bead_calibration d_l0.50)",
           "blaisot": "Blaisot's contrast-corrected size at l = 0.61"}


# ---- the model -------------------------------------------------------------------------------------------

def render(d_um: float, chi_um: float, tau: float, rng, noise: float, um_per_px: float = 10.0):
    """One droplet image: T (float32), its centre (x, y) in px. Pixel i covers [i - 0.5, i + 0.5)."""
    half = int(max(d_um / um_per_px / 2 + 3 * max(chi_um, 4.0) / um_per_px + 8,      # the blurred disc, and the
                   1.5 * max(d_um, 20.0) / um_per_px + 12 + bc.RECENTRE_PX + 4))   # window measure_at needs
    n = 2 * half + 1
    cx, cy = half + rng.uniform(-0.5, 0.5), half + rng.uniform(-0.5, 0.5)
    g = (np.arange(n * UP) + 0.5) / UP - 0.5                    # sub-cell centres in px
    xx, yy = np.meshgrid(g, g)
    disc = ((xx - cx) ** 2 + (yy - cy) ** 2 <= (d_um / um_per_px / 2) ** 2).astype(np.float32)
    t = 1.0 - (1.0 - tau) * disc
    sigma = chi_um / 2.0 / um_per_px * UP                       # exp(-2 r^2/chi^2) is a Gaussian of sigma chi/2
    if sigma > 0.3:
        t = cv2.GaussianBlur(t, (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)
    T = cv2.resize(t, (n, n), interpolation=cv2.INTER_AREA)
    if noise > 0:
        T = T + rng.normal(0.0, noise, T.shape).astype(np.float32)
    return T.astype(np.float32), cx, cy


def found_area(T: np.ndarray, cx: float, cy: float) -> int:
    """Pixels in the T < 0.95 piece (lightly smoothed, as the candidate finder) at the droplet's centre."""
    Ts = cv2.GaussianBlur(T, (0, 0), 0.5)
    n, lab = cv2.connectedComponents((Ts < bc.DETECT_T).astype(np.uint8), connectivity=8)
    if n < 2:
        return 0
    y, x = int(round(cy)), int(round(cx))
    k = lab[y, x]
    if k == 0:
        ys, xs = np.nonzero(lab)
        j = int(np.argmin((ys - y) ** 2 + (xs - x) ** 2))
        if (ys[j] - y) ** 2 + (xs[j] - x) ** 2 > 4:
            return 0
        k = lab[ys[j], xs[j]]
    return int((lab == k).sum())


def measure(d_um: float, chi_opt: float, tau: float, rng, noise: float) -> dict:
    T, cx, cy = render(d_um, chi_opt, tau, rng, noise)
    area = found_area(T, cx, cy)
    out = {"d_um": d_um, "chi_opt": chi_opt, "found": area >= MIN_AREA_PX}
    r = bc.measure_at(T, cx, cy, max(d_um, 20.0) / bc.UM_PER_PX, tau, levels=()) if out["found"] else None
    if not r or not r.get("detected"):
        out.update(found=False, chi=np.nan, halfmax_native=np.nan, halfmax_up4=np.nan, blaisot=np.nan, core=np.nan)
        return out
    out.update(chi=float(r.get("chi_um", np.nan)), halfmax_native=float(r.get("halfmax_d_um", np.nan)),
               halfmax_up4=float(r.get("d_l0.50", np.nan)), blaisot=float(r.get("d_blaisot_um", np.nan)),
               core=float(r.get("core_t", np.nan)))
    return out


def _med(v):
    v = np.asarray([x for x in v if np.isfinite(x)], float)
    return float(np.median(v)) if v.size else float("nan")


def chi_curve(d_um, chi_opts, tau, noise, n, seed=0) -> list[dict]:
    """Median measurements of n droplets of size d at each optical blur."""
    rng = np.random.default_rng(seed)
    out = []
    for c in chi_opts:
        rows = [measure(d_um, c, tau, rng, noise) for _ in range(n)]
        out.append({"d_um": d_um, "chi_opt": float(c), "found": float(np.mean([r["found"] for r in rows])),
                    **{k: _med([r[k] for r in rows]) for k in ("chi", "core", *METHODS)}})
    return out


def calibrate_chi0(target_chi: float, d_um: float, tau: float, noise: float, n: int = 60) -> float:
    """The optical blur at best focus: the one at which a d-um disc reads the chi the real beads read at focus."""
    grid = np.arange(4.0, 22.01, 1.0)
    curve = chi_curve(d_um, grid, tau, noise, n, seed=1)
    meas = np.asarray([r["chi"] for r in curve])
    ok = np.isfinite(meas)
    return float(np.interp(target_chi, meas[ok], grid[ok]))


# ---- the real beads, for the check -----------------------------------------------------------------------

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def bead_curves(beads_dir: Path) -> dict:
    """Real beads, median size / certified against measured chi: static (through focus, per z) and falling (chi
    bands). Same measurement (measure_at) as the model."""
    out = {}
    st = list(csv.DictReader(open(beads_dir / "beads_through_focus.csv")))
    for c in BEAD_SIZES:
        rows = [r for r in st if abs(_num(r["certified_um"]) - c) < 0.01]
        if not rows:
            continue
        zs = sorted({_num(r["z_mm"]) for r in rows})
        pts = []
        for z in zs:
            rz = [r for r in rows if _num(r["z_mm"]) == z]
            pts.append((_med([_num(r["chi_um"]) for r in rz]), _med([_num(r["d_l0.50"]) for r in rz]) / c,
                        _med([_num(r["halfmax_d_um"]) for r in rz]) / c))
        out.setdefault(f"{c:g}", {})["static"] = pts
    fb = beads_dir / "falling_beads.csv"
    if fb.is_file():
        fr = [r for r in csv.DictReader(open(fb)) if r.get("isolated") == "True"]
        for c in BEAD_SIZES:
            rows = [r for r in fr if abs(_num(r["certified_um"]) - c) < 0.01]
            pts = []
            for lo in range(12, 60, 4):
                rz = [r for r in rows if lo <= _num(r["chi_um"]) < lo + 4]
                if len(rz) >= 15:
                    pts.append((lo + 2.0, _med([_num(r["d_l0.50"]) for r in rz]) / c, float("nan")))
            if pts:
                out.setdefault(f"{c:g}", {})["falling"] = pts
    return out


def edge_offset_real(beads_dir: Path) -> dict:
    """The real beads' upsampled half-max at their sharpest (falling, chi 12-16 um), minus the certificate."""
    fb = beads_dir / "falling_beads.csv"
    out = {}
    if not fb.is_file():
        return out
    fr = [r for r in csv.DictReader(open(fb)) if r.get("isolated") == "True"]
    for c in BEAD_SIZES + (155.8,):
        d = [_num(r["d_l0.50"]) for r in fr if abs(_num(r["certified_um"]) - c) < 0.01 and 12 <= _num(r["chi_um"]) < 16]
        if len(d) >= 15:
            out[f"{c:g}"] = round(_med(d) - c, 2)
    return out


# ---- the limit -------------------------------------------------------------------------------------------

def slab_chi_opt(chi_max: float, curve_ref: list[dict]) -> float:
    """The optical blur at which a large reference disc reads chi_max: the edge of the measurement volume."""
    co = np.asarray([r["chi_opt"] for r in curve_ref])
    ch = np.asarray([r["chi"] for r in curve_ref])
    ok = np.isfinite(ch)
    return float(np.interp(chi_max, ch[ok], co[ok]))


def size_table(chi0: float, chi_max: float, chi_slab: float, offsets: dict, tau: float, noise: float, n: int,
               seed: int = 7) -> list[dict]:
    """Per size: droplets spread evenly in optical blur from chi0 to twice the volume's edge (even in |z|), found,
    passed by chi <= chi_max, and sized by each method (edge-corrected by the model's own offset at large sizes)."""
    rng = np.random.default_rng(seed)
    far = chi0 + 2.0 * (chi_slab - chi0)
    out = []
    for d in SIZES_UM:
        rows = [measure(d, float(rng.uniform(chi0, far)), tau, rng, noise) for _ in range(n)]
        inside = [r for r in rows if r["chi_opt"] <= chi_slab]
        passed = [r for r in rows if r["found"] and np.isfinite(r["chi"]) and r["chi"] <= chi_max]
        ok_in = [r for r in inside if r["found"] and np.isfinite(r["chi"]) and r["chi"] <= chi_max]
        row = {"d_um": d, "chi_max": chi_max, "n": n, "inside": len(inside),
               "found_and_passed_inside": round(len(ok_in) / len(inside), 3) if inside else None,
               "found_inside": round(sum(r["found"] for r in inside) / len(inside), 3) if inside else None,
               "passed_from_outside": round(sum(r["chi_opt"] > chi_slab for r in passed) / len(passed), 3)
               if passed else None}
        for m in METHODS:
            v = np.asarray([r[m] - offsets.get(m, 0.0) for r in passed if np.isfinite(r[m])], float)
            row[f"{m}_bias"] = round(float(np.median(v) / d - 1), 4) if v.size else None
            row[f"{m}_rms"] = round(float(np.sqrt(np.mean((v / d - 1) ** 2))), 4) if v.size else None
        out.append(row)
    return out


def d_min(table: list[dict], method: str) -> float | None:
    """The smallest size from which every larger size meets 'confident'."""
    good = [r["d_um"] for r in table
            if r[f"{method}_bias"] is not None and abs(r[f"{method}_bias"]) <= BIAS_OK
            and (r["found_and_passed_inside"] or 0) >= FOUND_OK]
    sizes = [r["d_um"] for r in table]
    for d in sizes:
        if all(s in good for s in sizes if s >= d):
            return d
    return None


# ---- run -------------------------------------------------------------------------------------------------

def noise_of(run: Path | None) -> float:
    """Single-frame T noise of a real run (robust spread of the backlight away from objects)."""
    if run is None:
        return NOISE_T_DEFAULT
    raw = run / "shadowgraph" / "raw"
    bg = cv2.imread(str(raw / "background_median.tiff"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    s = []
    for f in sorted((raw / "frames" / "16bit").glob("*.tiff"))[::50][:8]:
        T = cv2.imread(str(f), cv2.IMREAD_UNCHANGED).astype(np.float32) / np.maximum(bg, 1)
        obj = cv2.dilate((cv2.GaussianBlur(T, (0, 0), 1.0) < 0.95).astype(np.uint8), np.ones((15, 15), np.uint8))
        v = T[~obj.astype(bool)]
        s.append(float(np.median(np.abs(v - np.median(v))) * 1.4826))
    return float(np.mean(s)) if s else NOISE_T_DEFAULT


def analyse(beads_dir: Path, out: Path, noise: float, n_curve: int = 40, n_table: int = 600) -> dict:
    calib = json.loads((beads_dir / "optics_calibration_v1.json").read_text())
    tau = float(calib.get("tau") or 0.11)
    chi_focus_76 = float(calib["at_focus"]["76.39"]["chi_median_um"])
    chi0 = calibrate_chi0(chi_focus_76, 76.39, tau, noise)
    grid = np.unique(np.concatenate([np.arange(chi0, 30, 2.0), np.arange(30, 91, 5.0)]))
    curves = {f"{d:g}": chi_curve(d, grid, tau, noise, n_curve, seed=11) for d in SIZES_UM + BEAD_SIZES}
    # the model's own edge offset at large sizes and best focus, per method; the real beads' (falling, sharpest)
    big = [r for d in (80.0, 100.0, 150.0) for r in curves[f"{d:g}"] if r["chi_opt"] == grid[0]]
    model_offset = {m: round(_med([r[m] - r["d_um"] for r in big]), 2) for m in METHODS}
    real_offset = edge_offset_real(beads_dir)
    real_mean = _med(list(real_offset.values())) if real_offset else float("nan")
    delta = real_mean - model_offset["halfmax_up4"] if np.isfinite(real_mean) else 0.0
    beads = bead_curves(beads_dir)
    # the check: model (+ the real edge offset, a constant) against the real beads, size / certified vs chi
    check = {}
    for c, b in beads.items():
        mc = curves.get(c) or []
        mch = np.asarray([r["chi"] for r in mc]); mr_ = np.asarray([(r["halfmax_up4"] + delta) / float(c) for r in mc])
        okm = np.isfinite(mch) & np.isfinite(mr_)
        order = np.argsort(mch[okm])
        res = []
        for kind, pts in b.items():
            for ch, ratio, _hn in pts:
                if np.isfinite(ch) and np.isfinite(ratio) and mch[okm].min() <= ch <= mch[okm].max():
                    res.append(ratio - float(np.interp(ch, mch[okm][order], mr_[okm][order])))
        check[c] = {"n_points": len(res), "median_diff": round(_med(res), 4) if res else None,
                    "max_abs_diff": round(float(np.max(np.abs(res))), 4) if res else None}
    ref = curves["150"]
    tables, limits = {}, {}
    for cm in CHI_MAX_TRIED:
        slab = slab_chi_opt(cm, ref)
        t = size_table(chi0, cm, slab, model_offset, tau, noise, n_table)
        tables[f"{cm:g}"] = t
        limits[f"{cm:g}"] = {"chi_opt_slab_um": round(slab, 2), **{m: d_min(t, m) for m in METHODS}}
    R = {"version": VERSION, "made": datetime.now().isoformat(timespec="seconds"),
         "inputs": {"beads": str(beads_dir), "tau": tau, "noise_T": round(noise, 4), "um_per_px": bc.UM_PER_PX},
         "chi0_optical_um": round(chi0, 2), "chi_focus_76_real_um": chi_focus_76,
         "model_edge_offset_um": model_offset, "real_edge_offset_um_sharpest_falling": real_offset,
         "edge_offset_added_um": round(delta, 2), "check_against_beads": check,
         "criterion": {"bias": BIAS_OK, "found_and_passed": FOUND_OK, "ai_recall": AI_RECALL},
         "d_min_um": limits, "tables": tables}
    out.mkdir(parents=True, exist_ok=True)
    (out / "size_limit.json").write_text(json.dumps(R, indent=1), encoding="utf-8")
    with open(out / "model_grid.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["d_um", "chi_opt", "found", "chi", "core", *METHODS])
        w.writeheader()
        for rows in curves.values():
            w.writerows(rows)
    fig = _figure(out, curves, beads, delta, tables)
    (out / "report.md").write_text(report(R, fig), encoding="utf-8")
    R["_files"] = [str(out / "report.md"), str(out / "size_limit.json"), str(fig)]
    return R


def _figure(out: Path, curves, beads, delta, tables) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    cols = {"37.36": "#1f77b4", "56.28": "#ff7f0e", "76.39": "#2ca02c", "98.1": "#d62728"}
    for c, col in cols.items():
        mc = [r for r in curves.get(c, []) if np.isfinite(r["chi"])]
        ax[0].plot([r["chi"] for r in mc], [(r["halfmax_up4"] + delta) / float(c) for r in mc], "-", color=col,
                   label=f"model {c} um")
        for kind, mk in (("static", "o"), ("falling", "x")):
            pts = beads.get(c, {}).get(kind) or []
            ax[0].plot([p[0] for p in pts], [p[1] for p in pts], mk, color=col, ms=4, alpha=0.8)
    ax[0].set(xlim=(10, 70), ylim=(0.9, 2.0), xlabel="measured blur width chi (um)", ylabel="measured / true size",
              title="Model (lines) against real beads (o static, x falling)")
    ax[0].legend(fontsize=7)
    for cm, ls in zip(CHI_MAX_TRIED, ("-", "--", ":")):
        t = tables[f"{cm:g}"]
        for m, col in (("halfmax_native", "#888888"), ("halfmax_up4", "#1f77b4"), ("blaisot", "#2ca02c")):
            ax[1].plot([r["d_um"] for r in t], [100 * (r[f"{m}_bias"] or np.nan) for r in t], ls, color=col,
                       label=f"{METHODS[m].split(' (')[0]}, chi<={cm:g}" if cm == CHI_MAX_TRIED[0] or m == "halfmax_up4" else None)
        ax[2].plot([r["d_um"] for r in t], [100 * (r["found_and_passed_inside"] or 0) for r in t], ls, color="k",
                   label=f"chi <= {cm:g} um")
    for a in (ax[1],):
        a.axhspan(-100 * BIAS_OK, 100 * BIAS_OK, color="#2ca02c", alpha=0.08)
    ax[1].set(xscale="log", ylim=(-40, 60), xlabel="true diameter (um)", ylabel="median bias after edge correction (%)",
              title="Size bias of the droplets passed")
    ax[1].legend(fontsize=6)
    ax[2].axhline(100 * FOUND_OK, color="#2ca02c", lw=0.8)
    ax[2].set(xscale="log", ylim=(0, 105), xlabel="true diameter (um)", ylabel="% of those inside the volume",
              title="Found (>= 4 px) and passed (chi <= chi_max)")
    ax[2].legend(fontsize=7)
    fig.tight_layout()
    p = out / "fig_size_limit.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def report(R: dict, fig: Path) -> str:
    L = [f"# The smallest size we can confidently measure (size_limit {R['version']}, {R['made'][:10]})\n",
         f"Model: opaque disc (tau {R['inputs']['tau']}) * Gaussian PSF, {R['inputs']['um_per_px']} um pixels, "
         f"single-frame noise {R['inputs']['noise_T']} in T. Optical blur at best focus chi0 = "
         f"{R['chi0_optical_um']} um (a 76 um disc then reads the real beads' {R['chi_focus_76_real_um']} um). "
         f"Edge offset added to the model so its large discs read like the sharpest real beads: "
         f"{R['edge_offset_added_um']} um (real, falling, chi 12-16 um: {R['real_edge_offset_um_sharpest_falling']}; "
         f"model alone: {R['model_edge_offset_um']}).\n",
         "## Check against the real beads (size / certified against chi, real minus model)\n",
         "| bead (um) | points | median difference | largest difference |", "|---|---|---|---|"]
    for c, v in R["check_against_beads"].items():
        L.append(f"| {c} | {v['n_points']} | {v['median_diff']} | {v['max_abs_diff']} |")
    L += ["", f"Confident = median bias within +-{100 * BIAS_OK:.0f} % after the edge correction, and >= "
              f"{100 * FOUND_OK:.0f} % of the droplets inside the measurement volume found and passed. AI detection: "
              f"{R['criterion']['ai_recall']} (sets no limit).\n",
          "## d_min (um), by blur-width limit and sizing method\n",
          "| chi_max (um) | volume edge (optical chi, um) | " + " | ".join(METHODS[m] for m in METHODS) + " |",
          "|---|---|" + "---|" * len(METHODS)]
    for cm, v in R["d_min_um"].items():
        L.append(f"| {cm} | {v['chi_opt_slab_um']} | " + " | ".join(str(v[m]) for m in METHODS) + " |")
    for cm, t in R["tables"].items():
        L += ["", f"### chi_max = {cm} um\n",
              "| d (um) | found+passed inside | from outside | " + " | ".join(f"{m} bias / rms" for m in METHODS) + " |",
              "|---|---|---|" + "---|" * len(METHODS)]
        for r in t:
            L.append(f"| {r['d_um']:g} | {r['found_and_passed_inside']} | {r['passed_from_outside']} | " +
                     " | ".join(f"{r[f'{m}_bias']} / {r[f'{m}_rms']}" for m in METHODS) + " |")
    L += ["", f"![size limit]({fig.name})", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--beads", type=Path, required=True, help="the bead analysis folder (optics_calibration_v1.json, "
                    "beads_through_focus.csv, falling_beads.csv)")
    ap.add_argument("--noise-run", type=Path, default=None, help="a real run whose single-frame noise to use")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-curve", type=int, default=40)
    ap.add_argument("--n-table", type=int, default=600)
    a = ap.parse_args()
    noise = noise_of(a.noise_run)
    R = analyse(a.beads, a.out, noise, a.n_curve, a.n_table)
    print(f"chi0 {R['chi0_optical_um']} um, edge offset added {R['edge_offset_added_um']} um, noise {noise:.4f}")
    for cm, v in R["d_min_um"].items():
        print(f"  chi_max {cm}: d_min " + ", ".join(f"{m} {v[m]}" for m in METHODS))
    print("written:", *R["_files"], sep="\n  ")


if __name__ == "__main__":
    main()
