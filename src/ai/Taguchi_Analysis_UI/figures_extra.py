"""figures_extra.py -- the richer figures, shared by the Taguchi and response-surface analyses.

Same rules as figures.py (object API, no pyplot; PNG 300 dpi + SVG; nothing drawn when there is
nothing honest to draw). The data come from run_metrics (results.runs[i].metrics), the in-focus
diameters load_run already holds, and stats' main-effects fit.

    fig_size_distribution   number and volume distributions per condition (pooled replicates),
                            cumulative volume with Dv10 / Dv50 / Dv90 marked
    fig_size_percentiles    Dv10-Dv90 range and Dv50 per run, grouped by condition
    fig_series              droplets per frame over the capture, with the logged pressure, per run
    fig_series_liquid       liquid area per frame over the capture, per run
    fig_spectra             droplet-count spectra per condition, slow band shaded
    fig_steadiness          count CV, frames below half the mean, lag-1 r, slow share, by condition
    fig_drift               responses against capture time, coloured by condition
    fig_replicates          every analysed response: replicates, condition mean and its 95% CI
    fig_interactions        condition means for each factor pair (aliasing caveat when fractional)
    fig_diagnostics         residuals vs fitted, normal probability, residuals vs capture time
    fig_correlations        correlation matrix of the analysed responses across runs
    fig_pieces              un-atomised liquid pieces: size distribution and count per frame
    fig_quality             sizer and data-quality checks per run, odd runs flagged
    galleries/gallery_<c>   each run's lowest- and highest-atomised classical frames (PNG only)
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
from matplotlib.figure import Figure

from . import fsops, run_metrics, stats, tables
from .figures import CONDITION_COLOURS, FACTOR_COLOURS, GREY, _axes_style, _save

SIZE_BIN_UM = 5.0
SIZE_MAX_UM = 300.0
DRIFT_KEYS = ("d32", "atom", "dv50", "af_flow", "per_frame", "cv_droplets")
DIAG_KEYS = ("d32", "atom", "dv50", "af_flow")
INTERACTION_KEYS = ("d32", "atom")
GALLERY_WIDTH = 760                  # px per thumbnail
GALLERY_DIR = "galleries"


# ---- shared bits -------------------------------------------------------------------------------

def _conditions(results) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in sorted(results.runs, key=lambda r: (tables.cond_order(r.condition), r.replicate or 0, r.name)):
        out.setdefault(r.condition, []).append(r)
    return out


def _cmap(results) -> dict[str, str]:
    return {c: CONDITION_COLOURS[i % len(CONDITION_COLOURS)] for i, c in enumerate(_conditions(results))}


def cond_name(results, c: str, runs=None) -> str:
    """'T1: 3000 / 300 / 4000' -- the condition label with its factor levels."""
    runs = runs or _conditions(results).get(c, [])
    if not runs:
        return c
    lv = " / ".join(tables.level_text(runs[0].levels.get(f.key)) for f in results.factors)
    return f"{c}: {lv}"


def _levels_caption(results) -> str:
    return "levels: " + " / ".join(f.label for f in results.factors)


def _short(label: str) -> str:
    """'D32 in-focus (um)' -> 'D32 in-focus'; used where space is tight."""
    return label.split(" (")[0]


def _legend_conditions(fig, results, cmap, ncol=None) -> None:
    from matplotlib.lines import Line2D
    conds = list(_conditions(results))
    handles = [Line2D([], [], color=cmap[c], marker="o", linewidth=1.5, markersize=4,
                      label=cond_name(results, c)) for c in conds]
    fig.legend(handles=handles, loc="lower center", ncol=ncol or min(len(conds), 5), frameon=False,
               fontsize=7, bbox_to_anchor=(0.5, -0.01), title=_levels_caption(results), title_fontsize=7)


def _strip(ax, results, key_fn, cmap, *, label: str, ci: dict | None = None) -> None:
    """Dot per run at its condition, mean tick, optional (low, high) CI per condition."""
    conds = list(_conditions(results))
    for i, (c, rs) in enumerate(_conditions(results).items()):
        vals = [key_fn(r) for r in rs]
        vals = [v for v in vals if v is not None and math.isfinite(v)]
        if not vals:
            continue
        jitter = np.linspace(-0.12, 0.12, len(vals)) if len(vals) > 1 else [0.0]
        ax.scatter(i + np.asarray(jitter), vals, s=16, color=cmap[c], zorder=3, edgecolor="white",
                   linewidth=0.4)
        ax.hlines(np.mean(vals), i - 0.28, i + 0.28, color="black", linewidth=1.2, zorder=4)
        if ci and ci.get(c) and None not in ci[c]:
            ax.vlines(i, ci[c][0], ci[c][1], color=GREY, linewidth=4, alpha=0.35, zorder=2)
    ax.set_xticks(range(len(conds)), conds, fontsize=7)
    ax.set_xlim(-0.6, len(conds) - 0.4)
    ax.set_title(label, fontsize=8, loc="left")
    _axes_style(ax)


# ---- size --------------------------------------------------------------------------------------------

def fig_size_distribution(results, out_dir: Path) -> list[Path]:
    conds = _conditions(results)
    pooled = {c: np.concatenate([tables.in_focus_diameters(r) for r in rs]) for c, rs in conds.items()}
    pooled = {c: d[np.isfinite(d)] for c, d in pooled.items() if d.size}
    if not pooled:
        return []
    cmap = _cmap(results)
    edges = np.arange(0.0, SIZE_MAX_UM + SIZE_BIN_UM, SIZE_BIN_UM)
    mids = (edges[:-1] + edges[1:]) / 2
    fig = Figure(figsize=(13.0, 4.4))
    ax_n, ax_v, ax_c = fig.subplots(1, 3)
    for c, d in pooled.items():
        n, _ = np.histogram(d, bins=edges)
        v, _ = np.histogram(d, bins=edges, weights=d ** 3)
        ax_n.plot(mids, 100 * n / d.size, color=cmap[c], linewidth=1.2)
        ax_v.plot(mids, 100 * v / (d ** 3).sum(), color=cmap[c], linewidth=1.2)
        s = np.sort(d)
        cum = np.cumsum(s ** 3)
        ax_c.plot(s, 100 * cum / cum[-1], color=cmap[c], linewidth=1.2)
    for p in (10, 50, 90):
        ax_c.axhline(p, color=GREY, linestyle=":", linewidth=0.8)
        ax_c.text(SIZE_MAX_UM, p + 1.5, f"Dv{p}", fontsize=7, color=GREY, ha="right")
    for ax, ylab, title in ((ax_n, f"% of droplets per {SIZE_BIN_UM:g} µm", "By number"),
                            (ax_v, f"% of liquid volume per {SIZE_BIN_UM:g} µm", "By volume (where the liquid is)"),
                            (ax_c, "cumulative % of liquid volume", "Cumulative volume")):
        ax.axvspan(0, run_metrics.SMALL_UM, color="#f2f2f7", zorder=0)
        ax.set_xlim(0, SIZE_MAX_UM)
        ax.set_xlabel("in-focus droplet diameter (µm)")
        ax.set_ylabel(ylab, fontsize=8)
        ax.set_title(title, fontsize=9, loc="left")
        _axes_style(ax)
    ax_c.set_ylim(0, 100)
    _legend_conditions(fig, results, cmap)
    fig.suptitle("Droplet size distributions per condition (replicates pooled; shaded: below 50 µm, "
                 "indicative only)", fontsize=9, y=0.99)
    fig.tight_layout(rect=(0, 0.12, 1, 0.97))
    return _save(fig, out_dir, "fig_size_distribution")


def fig_size_percentiles(results, out_dir: Path) -> list[Path]:
    rows = [(r, run_metrics.volume_percentiles(tables.in_focus_diameters(r))) for r in
            sorted(results.runs, key=lambda r: (tables.cond_order(r.condition), r.replicate or 0, r.name))]
    rows = [(r, p) for r, p in rows if None not in p]
    if not rows:
        return []
    cmap = _cmap(results)
    fig = Figure(figsize=(max(7.0, 0.3 * len(rows) + 2.5), 4.0))
    ax = fig.subplots()
    x = np.arange(len(rows))
    for xi, (r, (d10, d50, d90)) in zip(x, rows):
        ax.vlines(xi, d10, d90, color=cmap[r.condition], linewidth=3, alpha=0.55)
        ax.scatter(xi, d50, color=cmap[r.condition], s=26, zorder=3, edgecolor="black", linewidth=0.5)
    prev = None
    for xi, (r, _) in zip(x, rows):
        if prev is not None and r.condition != prev:
            ax.axvline(xi - 0.5, color="black", linewidth=0.6, alpha=0.4)
        prev = r.condition
    ax.set_xticks(x, [r.name[:6] for r, _ in rows], rotation=90, fontsize=7)
    ax.set_ylabel("diameter (µm)")
    ax.set_title("Volume percentiles per run: bar = Dv10 to Dv90, dot = Dv50 (grouped by condition)",
                 fontsize=9, loc="left")
    _axes_style(ax)
    _legend_conditions(fig, results, cmap)
    fig.tight_layout(rect=(0, 0.14, 1, 1))
    return _save(fig, out_dir, "fig_size_percentiles")


# ---- steadiness --------------------------------------------------------------------------------------

def _grid(results, only=None):
    conds = _conditions(results)
    if only is not None:
        conds = {c: rs for c, rs in conds.items() if c in only}
    ncol = max((len(rs) for rs in conds.values()), default=1)
    return conds, ncol


def fig_series(results, out_dir: Path, only=None, name: str = "fig_series", formats=("png", "svg")) -> list[Path]:
    conds, ncol = _grid(results, only)
    if not conds:
        return []
    if not any((r.metrics.get("steadiness") or {}).get("count_series") for r in results.runs):
        return []
    fig = Figure(figsize=(3.4 * ncol, 1.35 * len(conds) + 0.9))
    axes = fig.subplots(len(conds), ncol, squeeze=False, sharex=True)
    for i, (c, rs) in enumerate(conds.items()):
        for j in range(ncol):
            ax = axes[i][j]
            if j >= len(rs):
                ax.axis("off")
                continue
            r = rs[j]
            st = r.metrics.get("steadiness") or {}
            cs = np.asarray(st.get("count_series") or [], float)
            fs = st.get("fs_hz")
            t = np.arange(cs.size) / fs if fs else np.arange(cs.size)
            ax.plot(t, cs, color="#0a84ff", linewidth=0.6)
            if cs.size:
                ax.axhline(cs.mean(), color="#0a84ff", linestyle="--", linewidth=0.6, alpha=0.7)
            pr = r.metrics.get("pressure") or {}
            if pr.get("t") and fs:
                ax2 = ax.twinx()
                ax2.plot(pr["t"], pr["pressure"], color="#ff453a", linewidth=0.8)
                ax2.tick_params(labelsize=6, colors="#ff453a")
                for side in ("top",):
                    ax2.spines[side].set_visible(False)
            ax.tick_params(labelsize=6)
            _axes_style(ax)
            ax.set_title(f"{c}  {r.name[:6]}" + (f"   r(p, n) = {pr['r_pressure_droplets']:+.2f}"
                                                  if pr.get("r_pressure_droplets") is not None else ""),
                         fontsize=7, loc="left")
            if j == 0:
                ax.set_ylabel("droplets\n/ frame", fontsize=7)
    for ax in axes[-1]:
        ax.set_xlabel("time in capture (s)", fontsize=7)
    fig.suptitle("Droplets per frame (blue; dashed = run mean) and logged upstream pressure (red, barA) "
                 "through each capture", fontsize=9, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.985 if len(conds) > 4 else 0.95))
    return _save(fig, out_dir, name, formats)


def fig_series_liquid(results, out_dir: Path, only=None, name: str = "fig_series_liquid",
                      formats=("png", "svg")) -> list[Path]:
    conds, ncol = _grid(results, only)
    if not conds:
        return []
    if not any((r.metrics.get("steadiness") or {}).get("liquid_series") for r in results.runs):
        return []
    fig = Figure(figsize=(3.4 * ncol, 1.35 * len(conds) + 0.9))
    axes = fig.subplots(len(conds), ncol, squeeze=False, sharex=True)
    for i, (c, rs) in enumerate(conds.items()):
        for j in range(ncol):
            ax = axes[i][j]
            if j >= len(rs):
                ax.axis("off")
                continue
            st = rs[j].metrics.get("steadiness") or {}
            li = np.asarray(st.get("liquid_series") or [], float)
            fs = st.get("fs_hz")
            t = np.arange(li.size) / fs if fs else np.arange(li.size)
            ax.plot(t, li / 1e3, color="#8e5a1e", linewidth=0.6)
            ax.tick_params(labelsize=6)
            _axes_style(ax)
            cv = st.get("liquid_cv")
            ax.set_title(f"{c}  {rs[j].name[:6]}" + (f"   CV {cv:.2f}" if cv is not None else ""),
                         fontsize=7, loc="left")
            if j == 0:
                ax.set_ylabel("liquid\n(kpx)", fontsize=7)
    for ax in axes[-1]:
        ax.set_xlabel("time in capture (s)", fontsize=7)
    fig.suptitle("Total liquid area per frame (classical) through each capture", fontsize=9, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.985 if len(conds) > 4 else 0.95))
    return _save(fig, out_dir, name, formats)


def fig_spectra(results, out_dir: Path) -> list[Path]:
    conds = _conditions(results)
    have = {c: [r for r in rs if any(p > 0 for p in (r.metrics.get("steadiness") or {}).get("spectrum") or [])]
            for c, rs in conds.items()}
    have = {c: rs for c, rs in have.items() if rs}
    if not have:
        return []
    n = len(have)
    ncol = min(3, n)
    nrow = math.ceil(n / ncol)
    fig = Figure(figsize=(3.6 * ncol, 2.5 * nrow + 0.5))
    axes = fig.subplots(nrow, ncol, squeeze=False, sharex=True, sharey=True)
    for k, (c, rs) in enumerate(have.items()):
        ax = axes[k // ncol][k % ncol]
        shares = []
        for r in rs:
            st = r.metrics["steadiness"]
            f, P = np.asarray(st["spectrum_hz"]), np.asarray(st["spectrum"])
            ok = f > 0
            ax.semilogy(f[ok], P[ok], linewidth=0.8, alpha=0.85)
            if st.get("slow_share_pct") is not None:
                shares.append(st["slow_share_pct"])
        ax.axvspan(0, run_metrics.SLOW_HZ, color="#ffd60a", alpha=0.18, zorder=0)
        _axes_style(ax)
        ax.tick_params(labelsize=7)
        title = cond_name(results, c, rs)
        if shares:
            title += f"\nslow share {np.mean(shares):.0f}%"
        ax.set_title(title, fontsize=7, loc="left")
    for k in range(n, nrow * ncol):
        axes[k // ncol][k % ncol].axis("off")
    for ax in axes[-1]:
        ax.set_xlabel("frequency (Hz)", fontsize=8)
    for row in axes:
        row[0].set_ylabel("power", fontsize=8)
    noise = next((r.metrics["steadiness"].get("slow_share_noise_pct") for rs in have.values() for r in rs
                  if r.metrics["steadiness"].get("slow_share_noise_pct") is not None), None)
    fig.suptitle(f"Droplet-count spectra (Welch), one line per replicate; shaded: below {run_metrics.SLOW_HZ:g} Hz"
                 + (f" (white noise would put {noise:.0f}% there)" if noise is not None else ""),
                 fontsize=9, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return _save(fig, out_dir, "fig_spectra")


def fig_steadiness(results, out_dir: Path) -> list[Path]:
    cmap = _cmap(results)
    panels = [("count_cv", "Droplet-count CV", None), ("thin_pct", "Frames below half the mean count (%)", None),
              ("lag1", "Lag-1 correlation of droplet count", None),
              ("slow_share_pct", f"Slow share of count variance, < {run_metrics.SLOW_HZ:g} Hz (%)",
               "slow_share_noise_pct")]
    panels = [p for p in panels if any((r.metrics.get("steadiness") or {}).get(p[0]) is not None
                                       for r in results.runs)]
    if not panels:
        return []
    ncol = 2 if len(panels) > 1 else 1                 # 2 x 2: readable on a slide
    nrow = math.ceil(len(panels) / ncol)
    fig = Figure(figsize=(5.2 * ncol, 3.0 * nrow + 1.1))
    grid = fig.subplots(nrow, ncol, squeeze=False)
    axes = [grid[i // ncol][i % ncol] for i in range(len(panels))]
    for k in range(len(panels), nrow * ncol):
        grid[k // ncol][k % ncol].axis("off")
    for ax, (key, label, ref) in zip(axes, panels):
        _strip(ax, results, lambda r, k=key: (r.metrics.get("steadiness") or {}).get(k), cmap, label=label)
        if ref:
            v = next(((r.metrics.get("steadiness") or {}).get(ref) for r in results.runs
                      if (r.metrics.get("steadiness") or {}).get(ref) is not None), None)
            if v is not None:
                ax.axhline(v, color=GREY, linestyle="--", linewidth=0.8)
                ax.text(ax.get_xlim()[0], v, " white noise", fontsize=6, color=GREY, va="bottom", ha="left")
    _legend_conditions(fig, results, cmap)
    fig.suptitle("Steadiness and pulsing by condition (dots = runs, bar = mean); all droplets, in and out of "
                 "focus, so not affected by the sizer version", fontsize=9, y=0.995)
    fig.tight_layout(rect=(0, 0.11 if nrow > 1 else 0.17, 1, 0.97))
    return _save(fig, out_dir, "fig_steadiness")


# ---- drift, replicates, interactions --------------------------------------------------------------

def fig_drift(results, out_dir: Path) -> list[Path]:
    hours = stats.run_hours(results)
    keys = [k for k in DRIFT_KEYS if k in results.responses and results.responses[k].anova is not None]
    if not keys or len(hours) < 4:
        return []
    cmap = _cmap(results)
    ncol = min(3, len(keys))
    nrow = math.ceil(len(keys) / ncol)
    fig = Figure(figsize=(4.2 * ncol, 2.9 * nrow + 0.9))
    axes = fig.subplots(nrow, ncol, squeeze=False)
    for k, key in enumerate(keys):
        ax = axes[k // ncol][k % ncol]
        for r in results.runs:
            v = r.values.get(key)
            if r.name in hours and v is not None and math.isfinite(v):
                ax.scatter(hours[r.name], v, s=20, color=cmap[r.condition], edgecolor="white", linewidth=0.4,
                           zorder=3)
        d = stats.drift(results, key)
        bits = [_short(results.responses[key].label)]
        if d is not None and d.p is not None:
            bits.append(f"residual drift {d.slope_per_h:+.3g}/h, p = {d.p:.2g}")
        ax.set_title("\n".join(bits), fontsize=8, loc="left")
        ax.set_xlabel("hours from the first run", fontsize=8)
        ax.tick_params(labelsize=7)
        _axes_style(ax)
    for k in range(len(keys), nrow * ncol):
        axes[k // ncol][k % ncol].axis("off")
    _legend_conditions(fig, results, cmap)
    conf = [(f, r) for f, r in stats.order_confounding(results) if abs(r) >= 0.5]
    note = ("Drift is tested on what the factors leave unexplained (main-effects residuals)."
            + (" Confounded with time of day: " + ", ".join(f"{f} (r = {r:+.2f})" for f, r in conf)
               + ", so a drift would show up as that factor's effect, not here." if conf else ""))
    fig.suptitle("Responses against capture time, coloured by condition", fontsize=9, y=0.995)
    fig.text(0.5, 0.965, note, fontsize=7, color=GREY, ha="center", va="top", wrap=True)
    fig.tight_layout(rect=(0, 0.2 if nrow == 1 else 0.13, 1, 0.94))
    return _save(fig, out_dir, "fig_drift")


def _condition_ci(results, key) -> dict:
    out = {}
    for c, rs in _conditions(results).items():
        v = np.array([r.values[key] for r in rs if r.values.get(key) is not None
                      and math.isfinite(r.values[key])], float)
        if v.size >= 2:
            half = stats.t_quantile(0.05, v.size - 1) * v.std(ddof=1) / math.sqrt(v.size)
            out[c] = (v.mean() - half, v.mean() + half)
    return out


def fig_replicates(results, out_dir: Path, keys=None, name: str = "fig_replicates",
                   formats=("png", "svg")) -> list[Path]:
    keys = [k for k in (keys or results.responses) if k in results.responses
            and results.responses[k].anova is not None]
    if not keys:
        return []
    cmap = _cmap(results)
    ncol = 4 if len(keys) > 6 else min(3, len(keys))
    nrow = math.ceil(len(keys) / ncol)
    fig = Figure(figsize=(3.6 * ncol, 2.5 * nrow + 1.0))
    axes = fig.subplots(nrow, ncol, squeeze=False)
    for k, key in enumerate(keys):
        ax = axes[k // ncol][k % ncol]
        _strip(ax, results, lambda r, kk=key: r.values.get(kk), cmap,
               label=_short(results.responses[key].label), ci=_condition_ci(results, key))
        ax.tick_params(labelsize=6)
    for k in range(len(keys), nrow * ncol):
        axes[k // ncol][k % ncol].axis("off")
    _legend_conditions(fig, results, cmap)
    fig.suptitle("Replicates per condition (dots = runs, bar = mean, grey = 95% CI of the mean from the "
                 "replicates)", fontsize=9, y=0.995)
    fig.tight_layout(rect=(0, 0.08 if nrow > 2 else 0.16, 1, 0.98 if nrow > 2 else 0.95))
    return _save(fig, out_dir, name, formats)


def is_full_factorial(results) -> bool:
    n_cells = 1
    for f in results.factors:
        n_cells *= len({r.levels[f.key] for r in results.runs})
    return results.n_conditions >= n_cells


def fig_interactions(results, out_dir: Path) -> list[Path]:
    fs = results.factors
    keys = [k for k in INTERACTION_KEYS if k in results.responses and results.responses[k].anova is not None]
    pairs = [(a, b) for i, a in enumerate(fs) for b in fs[i + 1:]]
    if not keys or not pairs:
        return []
    fig = Figure(figsize=(3.6 * len(pairs), 2.9 * len(keys) + 0.9))
    axes = fig.subplots(len(keys), len(pairs), squeeze=False)
    for i, key in enumerate(keys):
        for j, (fa, fb) in enumerate(pairs):
            ax = axes[i][j]
            la = sorted({r.levels[fa.key] for r in results.runs}, key=lambda x: (str(type(x)), x))
            lb = sorted({r.levels[fb.key] for r in results.runs}, key=lambda x: (str(type(x)), x))
            for m, b in enumerate(lb):
                ys = []
                for a in la:
                    v = [r.values[key] for r in results.runs if r.levels[fa.key] == a and r.levels[fb.key] == b
                         and r.values.get(key) is not None and math.isfinite(r.values[key])]
                    ys.append(np.mean(v) if v else np.nan)
                ax.plot(range(len(la)), ys, "-o", color=FACTOR_COLOURS[m % len(FACTOR_COLOURS)], linewidth=1.4,
                        markersize=4, label=f"{tables.level_text(b)}")
            ax.set_xticks(range(len(la)), [tables.level_text(a) for a in la], fontsize=7)
            ax.tick_params(labelsize=7)
            _axes_style(ax)
            if i == len(keys) - 1:
                ax.set_xlabel(fa.label, fontsize=8)
            if j == 0:
                ax.set_ylabel(_short(results.responses[key].label), fontsize=8)
            if i == 0:
                ax.legend(title=fb.label, fontsize=6, title_fontsize=6, frameon=False, loc="best")
    note = ("Non-parallel lines suggest an interaction." if is_full_factorial(results) else
            "Caution: the design is fractional, so each point here also changes the other factor(s). Non-parallel "
            "lines can be another factor's main effect rather than an interaction (in an L9, every two-factor "
            "interaction is aliased with the third factor).")
    fig.suptitle("Condition means for each pair of factors", fontsize=9, y=0.995)
    fig.text(0.0, 0.0, note, fontsize=7, color=GREY, wrap=True)
    fig.tight_layout(rect=(0, 0.06, 1, 0.97))
    return _save(fig, out_dir, "fig_interactions")


# ---- diagnostics -----------------------------------------------------------------------------------------

def fig_diagnostics(results, out_dir: Path, keys=DIAG_KEYS, name: str = "fig_diagnostics",
                    formats=("png", "svg")) -> list[Path]:
    fits = [(k, stats.main_effects_fit(results, k)) for k in keys if k in results.responses
            and results.responses[k].anova is not None]
    fits = [(k, f) for k, f in fits if f is not None and np.isfinite(f.std_resid).sum() >= 3]
    if not fits:
        return []
    hours = stats.run_hours(results)
    cmap = _cmap(results)
    fig = Figure(figsize=(12.0, 2.8 * len(fits) + 0.9))
    axes = fig.subplots(len(fits), 3, squeeze=False)
    nd = NormalDist()
    for i, (key, fit) in enumerate(fits):
        z = fit.std_resid
        ok = np.isfinite(z)
        colours = [cmap[r.condition] for r in fit.runs]
        a0, a1, a2 = axes[i]
        a0.scatter(fit.fitted[ok], z[ok], c=[c for c, o in zip(colours, ok) if o], s=16, edgecolor="white",
                   linewidth=0.4)
        a0.set_xlabel("fitted (main effects)", fontsize=7)
        zs = np.sort(z[ok])
        q = [nd.inv_cdf((k + 1 - 0.375) / (zs.size + 0.25)) for k in range(zs.size)]      # Blom
        a1.scatter(q, zs, s=14, color="#3a3a3c")
        lim = max(abs(min(q)), abs(max(q)))
        a1.plot([-lim, lim], [-lim, lim], color=GREY, linewidth=0.8)
        a1.set_xlabel("normal quantile", fontsize=7)
        t = np.array([hours.get(r.name, np.nan) for r in fit.runs])
        m = ok & np.isfinite(t)
        a2.scatter(t[m], z[m], c=[c for c, o in zip(colours, m) if o], s=16, edgecolor="white", linewidth=0.4)
        a2.set_xlabel("hours from the first run", fontsize=7)
        for ax in (a0, a2):
            for v in (-2, 2):
                ax.axhline(v, color=GREY, linestyle=":", linewidth=0.8)
            ax.axhline(0, color=GREY, linewidth=0.6)
        for ax in (a0, a1, a2):
            ax.tick_params(labelsize=7)
            _axes_style(ax)
        a0.set_ylabel(f"{_short(results.responses[key].label)}\nstandardised residual", fontsize=7)
        if i == 0:
            a0.set_title("Residuals vs fitted", fontsize=8, loc="left")
            a1.set_title("Normal probability", fontsize=8, loc="left")
            a2.set_title("Residuals vs capture time", fontsize=8, loc="left")
    _legend_conditions(fig, results, cmap)
    fig.suptitle("Model checks on the main-effects fit (dotted: ±2; a straight normal plot and no pattern "
                 "against fitted or time is what a good fit looks like)", fontsize=9, y=0.995)
    fig.tight_layout(rect=(0, 0.08 if len(fits) > 2 else 0.17, 1, 0.98 if len(fits) > 2 else 0.94))
    return _save(fig, out_dir, name, formats)


def fig_correlations(results, out_dir: Path) -> list[Path]:
    rows = tables.response_correlations(results)
    if len(rows) < 2:
        return []
    labels = [r["response"] for r in rows]
    M = np.array([[np.nan if r.get(l) is None else r[l] for l in labels] for r in rows], float)
    n = len(labels)
    fig = Figure(figsize=(0.55 * n + 3.2, 0.5 * n + 2.2))
    ax = fig.subplots()
    im = ax.imshow(M, cmap="RdBu_r", vmin=-1, vmax=1)
    for i in range(n):
        for j in range(n):
            if np.isfinite(M[i, j]):
                ax.text(j, i, f"{M[i, j]:.2f}".replace("0.", ".").replace("-.", "−."), ha="center", va="center",
                        fontsize=6, color="white" if abs(M[i, j]) > 0.6 else "#1c1c1e")
    short = [_short(l) for l in labels]
    ax.set_xticks(range(n), short, rotation=60, ha="right", fontsize=7)
    ax.set_yticks(range(n), short, fontsize=7)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Pearson r across runs")
    ax.set_title("How the responses move together (across all runs: includes the factors' effects)",
                 fontsize=9, loc="left")
    fig.tight_layout()
    return _save(fig, out_dir, "fig_correlations")


# ---- liquid pieces and data quality ------------------------------------------------------------------------

def fig_pieces(results, out_dir: Path) -> list[Path]:
    conds = _conditions(results)
    hist = {}
    for c, rs in conds.items():
        hs = [np.asarray((r.metrics.get("pieces") or {}).get("log10_area_hist") or [], float) for r in rs]
        hs = [h for h in hs if h.size]
        if hs:
            hist[c] = np.sum(hs, axis=0)
    if not hist:
        return []
    cmap = _cmap(results)
    edges = np.arange(1, 7.01, 0.25)
    mids = 10 ** ((edges[:-1] + edges[1:]) / 2) * 1e-4           # px -> mm^2 (10 um/px)
    fig = Figure(figsize=(11.5, 3.9))
    ax_d, ax_n, ax_m = fig.subplots(1, 3)
    for c, h in hist.items():
        if h.sum() > 0:
            ax_d.semilogx(mids, 100 * h / h.sum(), color=cmap[c], linewidth=1.2)
    ax_d.set_xlabel("piece area (mm², log scale)", fontsize=8)
    ax_d.set_ylabel("% of pieces", fontsize=8)
    ax_d.set_title("Size of un-atomised pieces", fontsize=9, loc="left")
    _axes_style(ax_d)
    _strip(ax_n, results, lambda r: (r.metrics.get("pieces") or {}).get("per_frame"), cmap,
           label="Pieces per frame")
    _strip(ax_m, results, lambda r: (r.metrics.get("pieces") or {}).get("largest_mm2"), cmap,
           label="Largest piece (mm²)")
    _legend_conditions(fig, results, cmap)
    fig.suptitle("Un-atomised liquid pieces (classical connected components, replicates pooled in the "
                 "distribution)", fontsize=9, y=0.99)
    fig.tight_layout(rect=(0, 0.16, 1, 0.95))
    return _save(fig, out_dir, "fig_pieces")


def fig_quality(results, out_dir: Path) -> list[Path]:
    rows = tables.data_quality(results)
    cols = [c for c, _ in tables.QUALITY_COLUMNS if any(r.get(c) is not None for r in rows)]
    if not rows or not cols:
        return []
    flags = tables.quality_flags(results)
    cmap = _cmap(results)
    ncol = min(3, len(cols))
    nrow = math.ceil(len(cols) / ncol)
    fig = Figure(figsize=(max(4.4, 0.17 * len(rows) + 1.4) * ncol, 2.5 * nrow + 1.0))
    axes = fig.subplots(nrow, ncol, squeeze=False)
    x = np.arange(len(rows))
    for k, col in enumerate(cols):
        ax = axes[k // ncol][k % ncol]
        for xi, r in zip(x, rows):
            v = r.get(col)
            if v is None:
                continue
            flagged = any(f["column"] == col for f in flags.get(r["run"], []))
            ax.bar(xi, v, color="#ff453a" if flagged else cmap[r["condition"]], width=0.8,
                   edgecolor="black" if flagged else "none", linewidth=0.8)
        ax.set_xticks(x, [r["run"][:6] for r in rows], rotation=90, fontsize=5)
        ax.tick_params(axis="y", labelsize=7)
        ax.set_title(col, fontsize=8, loc="left")
        _axes_style(ax)
    for k in range(len(cols), nrow * ncol):
        axes[k // ncol][k % ncol].axis("off")
    versions = sorted({str(r.get("sizer version")) for r in rows})
    n_flag = sum(1 for v in flags.values() if v)
    fig.suptitle(f"Sizer and data quality per run (sizer {', '.join(versions)}); red = far from the other runs "
                 f"(robust z > {tables.QUALITY_Z:g}): {n_flag} run(s)", fontsize=9, y=0.995)
    _legend_conditions(fig, results, cmap)
    fig.tight_layout(rect=(0, 0.1, 1, 0.97))
    return _save(fig, out_dir, "fig_quality")


# ---- image galleries ---------------------------------------------------------------------------------------

def _extreme_frames(r, thr: float) -> list[tuple[str, Path, float | None]]:
    """(which, image path, atomised %) for the run's classical lowest / highest atomised frames."""
    cl = Path((r.rec or {}).get("cl_dir") or r.path / "shadowgraph" / "analysis" / f"liquid_{thr:.2f}")
    try:
        ext = json.loads((cl / "classical_summary.json").read_text(encoding="utf-8")).get("atomised_extreme_frames") or {}
    except (OSError, ValueError):
        return []
    out = []
    for which in ("lowest", "highest"):
        e = ext.get(which) or {}
        p = cl / "extreme_images" / f"{e.get('frame')}.png"
        if e.get("frame") and p.is_file():
            out.append((which, p, e.get("atomised_pct")))
    return out


def gallery(results, cond: str, runs, out_dir: Path) -> Path | None:
    from PIL import Image, ImageDraw, ImageFont
    rows = [(r, _extreme_frames(r, results.thr)) for r in runs]
    rows = [(r, ex) for r, ex in rows if ex]
    if not rows:
        return None
    first = Image.open(rows[0][1][0][1])
    w = GALLERY_WIDTH
    h = round(first.height * w / first.width)
    pad, head, cap = 8, 34, 22
    sheet = Image.new("RGB", (2 * w + 3 * pad, head + len(rows) * (h + cap + pad) + pad), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=16)
        big = ImageFont.load_default(size=20)
    except TypeError:                                   # Pillow < 10.1: one fixed size
        font = big = ImageFont.load_default()
    draw.text((pad, 8), f"{cond_name(results, cond, runs)}  ({_levels_caption(results)}):  lowest- and "
                        f"highest-atomised frame of each run", fill="black", font=big)
    for i, (r, ex) in enumerate(rows):
        y = head + i * (h + cap + pad)
        for which, p, pct in ex:
            col = 0 if which == "lowest" else 1
            x = pad + col * (w + pad)
            with Image.open(p) as im:
                sheet.paste(im.convert("RGB").resize((w, h), Image.Resampling.LANCZOS), (x, y + cap))
            label = f"{r.name[:6]}  {which} atomised" + (f": {pct:.1f}%" if pct is not None else "") + f"  ({p.stem})"
            draw.text((x, y + 2), label, fill="black", font=font)
    out = Path(out_dir) / GALLERY_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"gallery_{cond}.png"
    tmp = out / f".gallery_{cond}.png.tmp"
    sheet.save(tmp, format="PNG", optimize=True)
    fsops.replace(tmp, path)
    return path


def galleries(results, out_dir: Path) -> list[Path]:
    out = []
    for c, rs in _conditions(results).items():
        p = gallery(results, c, rs, out_dir)
        if p is not None:
            out.append(p)
    return out


# ---- all of them ---------------------------------------------------------------------------------------

FIGURES = (fig_size_distribution, fig_size_percentiles, fig_series, fig_series_liquid, fig_spectra,
           fig_steadiness, fig_drift, fig_replicates, fig_interactions, fig_diagnostics, fig_correlations,
           fig_pieces, fig_quality, galleries)


def make_all(results, out_dir: Path, problems: list[str] | None = None) -> list[Path]:
    """Every extra figure with something honest to draw. One failing figure is recorded in
    `problems` and the rest still land."""
    out: list[Path] = []
    if not results.runs:
        return out
    for fn in FIGURES:
        try:
            out += fn(results, out_dir)
        except Exception as exc:                       # noqa: BLE001 -- reported by the caller
            if problems is None:
                raise
            problems.append(f"{fn.__name__} failed: {type(exc).__name__}: {exc}")
    return out
