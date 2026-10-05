"""figures.py -- every chart of the analysis, as PNG (300 dpi) + SVG. No Qt, no pyplot.

Uses matplotlib's object API (`Figure`, `FigureCanvasAgg`) rather than pyplot, so nothing
touches global state or a GUI backend: safe to call from the analysis thread while the
window is open.

One function per figure; each returns the list of files it wrote (empty if there was nothing
honest to draw -- no empty axes are saved).

    fig_main_effects          level means per factor, per headline response (+/- SE, bootstrap CI)
    fig_contributions         where the variation comes from: factors vs lack of fit vs error
    fig_per_run               each run's value with its frame-bootstrap CI, grouped by condition
    fig_sn                    S/N level means per factor (higher is better, always)
    fig_size_spread_count     stacked bars, runs on X, % of droplets per size bin
    fig_size_spread_volume    stacked bars, runs on X, % of liquid volume per size bin
    fig_glr                   each response against GLR, with the power-law fit

Colour: size bins use ONE sequential ramp ordered small -> large (never a categorical
palette, which would imply the bins are unrelated); factors use a fixed qualitative set.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from . import fsops

DPI = 300
HEADLINE = ("d32", "atom")                      # the two responses every figure leads with
FACTOR_COLOURS = ("#0a84ff", "#ff9f0a", "#30d158", "#bf5af2", "#ff453a", "#64d2ff", "#ffd60a")
GREY = "#8e8e93"
# conditions need MORE distinct colours than factors do (an L9 has 9): matplotlib's tab10.
CONDITION_COLOURS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2",
                     "#7f7f7f", "#bcbd22", "#17becf")


def _save(fig: Figure, out_dir: Path, name: str) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    FigureCanvasAgg(fig)
    written = []
    for ext, kw in (("png", {"dpi": DPI}), ("svg", {})):
        path = out_dir / f"{name}.{ext}"
        tmp = out_dir / f".{name}.{ext}.tmp"
        fig.savefig(tmp, format=ext, bbox_inches="tight", facecolor="white", **kw)
        fsops.replace(tmp, path)
        written.append(path)
    return written


def _axes_style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color="#e5e5ea", linewidth=0.6)
    ax.set_axisbelow(True)


def _label(results, key: str) -> str:
    r = results.responses.get(key)
    return r.label if r else key


def _factor_label(results, key: str) -> str:
    return next((f.label for f in results.factors if f.key == key), key)


def _headline_keys(results) -> list[str]:
    return [k for k in HEADLINE if k in results.responses and results.responses[k].effects]


def _fmt_level(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


# ---- main effects ----------------------------------------------------------------------------------

def fig_main_effects(results, out_dir: Path) -> list[Path]:
    keys, factors = _headline_keys(results), results.factors
    if not keys or not factors:
        return []
    fig = Figure(figsize=(3.3 * len(factors), 2.9 * len(keys) + 0.4))
    axes = fig.subplots(len(keys), len(factors), squeeze=False, sharey="row")
    for i, key in enumerate(keys):
        res = results.responses[key]
        for j, f in enumerate(factors):
            ax = axes[i][j]
            effs = res.effects.get(f.key, [])
            xs = np.arange(len(effs))
            ys = [e.mean for e in effs]
            ax.plot(xs, ys, "-o", color=FACTOR_COLOURS[j % len(FACTOR_COLOURS)], linewidth=1.8, zorder=3)
            for x, e in zip(xs, effs):
                if e.ci95 is not None:
                    ax.vlines(x, e.ci95[0], e.ci95[1], color=GREY, linewidth=4, alpha=0.35, zorder=2)
                if e.se is not None:
                    ax.errorbar(x, e.mean, yerr=e.se, color="black", capsize=3, linewidth=1, zorder=4)
            if ys:
                ax.axhline(float(np.mean([r.values[key] for r in results.runs
                                          if r.values.get(key) is not None])),
                           color=GREY, linestyle="--", linewidth=0.8, zorder=1)
            ax.set_xticks(xs, [_fmt_level(e.level) for e in effs])
            ax.set_xlim(-0.4, max(len(effs) - 1, 0) + 0.4)
            _axes_style(ax)
            row = res.anova.rows.get(f.key) if res.anova else None
            if row is not None and row.p is not None:
                ax.set_title(f"p = {row.p:.3g}", fontsize=8, loc="right", color="#3a3a3c")
            if i == len(keys) - 1:
                ax.set_xlabel(f.label)
            if j == 0:
                ax.set_ylabel(res.label, fontsize=9)
    fig.suptitle("Main effects: level means (dashed = grand mean; black = standard error from the "
                 "ANOVA error; grey band = frame-bootstrap 95% CI)", fontsize=9, y=0.995)
    fig.tight_layout()
    return _save(fig, out_dir, "fig_main_effects")


# ---- contributions ------------------------------------------------------------------------------------

def fig_contributions(results, out_dir: Path) -> list[Path]:
    """Share of each response's total variation, by source. Uses the raw SS shares (they sum
    to 100% with lack of fit and error), so the bars are a true partition."""
    items = [(k, r) for k, r in results.responses.items() if r.anova and r.anova.error]
    if not items:
        return []
    sources = [f.key for f in results.factors]
    has_lof = any(r.anova.lack_of_fit is not None for _, r in items)
    fig = Figure(figsize=(8.5, 0.5 * len(items) + 1.9))
    ax = fig.subplots()
    ypos = np.arange(len(items))[::-1]
    for y, (key, res) in zip(ypos, items):
        left = 0.0
        parts = [(s, res.anova.rows[s].contribution_pct or 0.0) for s in sources if s in res.anova.rows]
        if res.anova.lack_of_fit is not None:
            parts.append(("lack of fit", 100 * res.anova.lack_of_fit.ss / res.anova.total_ss
                          if res.anova.total_ss else 0.0))
        parts.append(("error", res.anova.error.contribution_pct or 0.0))
        for name, v in parts:
            if name == "error":
                colour = "#d1d1d6"
            elif name == "lack of fit":
                colour = "#8e8e93"
            else:
                colour = FACTOR_COLOURS[sources.index(name) % len(FACTOR_COLOURS)]
            ax.barh(y, v, left=left, color=colour, edgecolor="white", linewidth=0.6)
            if v >= 6:
                ax.text(left + v / 2, y, f"{v:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if name not in ("error",) else "#3a3a3c")
            left += v
    ax.set_yticks(ypos, [r.label for _, r in items], fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of total variation (sum of squares)")
    _axes_style(ax)
    ax.grid(axis="x", color="#e5e5ea", linewidth=0.6)
    ax.grid(axis="y", visible=False)
    from matplotlib.patches import Patch
    handles = [Patch(color=FACTOR_COLOURS[i % len(FACTOR_COLOURS)], label=_factor_label(results, s))
               for i, s in enumerate(sources)]
    if has_lof:
        handles.append(Patch(color="#8e8e93", label="lack of fit (interactions)"))
    handles.append(Patch(color="#d1d1d6", label=f"error ({results.error_source})"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=min(len(handles), 5),
              frameon=False, fontsize=8)
    ax.set_title("What drives each response", fontsize=10, loc="left")
    return _save(fig, out_dir, "fig_contributions")


# ---- per run ---------------------------------------------------------------------------------------------

def fig_per_run(results, out_dir: Path) -> list[Path]:
    keys = _headline_keys(results) or [k for k in HEADLINE if k in results.responses]
    if not keys or not results.runs:
        return []
    order = sorted(results.runs, key=lambda r: (r.condition, r.replicate or 0, r.name))
    conds = list(dict.fromkeys(r.condition for r in order))
    cmap = {c: CONDITION_COLOURS[i % len(CONDITION_COLOURS)] for i, c in enumerate(conds)}
    fig = Figure(figsize=(max(7.0, 0.32 * len(order) + 2), 3.0 * len(keys) + 0.6))
    axes = fig.subplots(len(keys), 1, squeeze=False, sharex=True)
    x = np.arange(len(order))
    for i, key in enumerate(keys):
        ax = axes[i][0]
        for xi, r in zip(x, order):
            v = r.values.get(key)
            if v is None or not math.isfinite(v):
                continue
            ax.bar(xi, v, color=cmap[r.condition], width=0.75, zorder=2)
            ci = r.ci95.get(key)
            if ci is not None:
                ax.vlines(xi, ci[0], ci[1], color="black", linewidth=1, zorder=3)
        _axes_style(ax)
        ax.set_ylabel(_label(results, key), fontsize=9)
    ax = axes[-1][0]
    ax.set_xticks(x, [r.name[:6] for r in order], rotation=90, fontsize=7)
    from matplotlib.patches import Patch
    axes[0][0].legend(handles=[Patch(color=cmap[c], label=c) for c in conds], ncol=min(len(conds), 9),
                      frameon=False, fontsize=7, loc="lower center", bbox_to_anchor=(0.5, 1.0),
                      title="condition (replicates share a colour); bars = value, line = bootstrap 95% CI",
                      title_fontsize=7)
    fig.tight_layout()
    return _save(fig, out_dir, "fig_per_run")


# ---- S/N -------------------------------------------------------------------------------------------------------

def fig_sn(results, out_dir: Path) -> list[Path]:
    keys = [k for k in HEADLINE if k in results.responses and results.responses[k].sn_defined]
    if not keys or not results.factors:
        return []
    fig = Figure(figsize=(3.3 * len(results.factors), 2.9 * len(keys) + 0.4))
    axes = fig.subplots(len(keys), len(results.factors), squeeze=False, sharey="row")
    for i, key in enumerate(keys):
        res = results.responses[key]
        for j, f in enumerate(results.factors):
            ax = axes[i][j]
            eff = res.sn_effects.get(f.key, {})
            levels = list(eff)
            ax.plot(range(len(levels)), [eff[l] for l in levels], "-o",
                    color=FACTOR_COLOURS[j % len(FACTOR_COLOURS)], linewidth=1.8)
            ax.set_xticks(range(len(levels)), [_fmt_level(l) for l in levels])
            ax.set_xlim(-0.4, max(len(levels) - 1, 0) + 0.4)
            _axes_style(ax)
            if i == len(keys) - 1:
                ax.set_xlabel(f.label)
            if j == 0:
                ax.set_ylabel(f"S/N, {res.label}\n(dB, higher = better)", fontsize=8)
    fig.suptitle("Signal-to-noise ratio by factor level", fontsize=9, y=0.995)
    fig.tight_layout()
    return _save(fig, out_dir, "fig_sn")


# ---- size spread ---------------------------------------------------------------------------------------------

def _ramp(n: int):
    """Sequential light -> dark, ordered small -> large droplets."""
    from matplotlib import colormaps
    cm = colormaps["viridis_r"]
    return [cm(0.08 + 0.84 * i / max(n - 1, 1)) for i in range(n)]


def _fig_spread(bins, measure: str, out_dir: Path, name: str, title: str) -> list[Path]:
    spreads = bins.runs
    if not spreads:
        return []
    cond_of = bins.run_condition
    order = sorted(spreads, key=lambda s: (cond_of.get(s.name, ""), s.name))
    colours = _ramp(len(bins.labels))
    fig = Figure(figsize=(max(7.5, 0.34 * len(order) + 2.6), 4.6))
    ax = fig.subplots()
    x = np.arange(len(order))
    bottom = np.zeros(len(order))
    for b, label in enumerate(bins.labels):
        vals = np.array([(s.pct_count if measure == "count" else s.pct_volume)[b] for s in order])
        ax.bar(x, vals, bottom=bottom, color=colours[b], width=0.85, label=f"{label} µm",
               edgecolor="white", linewidth=0.3)
        bottom += vals
    ax.set_xticks(x, [s.name[:6] for s in order], rotation=90, fontsize=7)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of droplets" if measure == "count" else "% of liquid volume")
    ax.set_xlabel("run (grouped by condition)")
    _axes_style(ax)
    # condition separators, so replicates read as groups
    prev = None
    for xi, s in zip(x, order):
        c = cond_of.get(s.name, "")
        if prev is not None and c != prev:
            ax.axvline(xi - 0.5, color="black", linewidth=0.6, alpha=0.5)
        prev = c
    ax.legend(title="droplet diameter", loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False,
              fontsize=8, title_fontsize=8, reverse=True)
    ax.set_title(title, fontsize=10, loc="left")
    fig.text(0.0, -0.04, "Bins under 50 µm are indicative only (pixel-lattice floor).",
             fontsize=7, color=GREY)
    return _save(fig, out_dir, name)


def fig_size_spread_count(bins, out_dir: Path) -> list[Path]:
    return _fig_spread(bins, "count", out_dir, "fig_size_spread_count",
                       "Droplet size spread, by count (in-focus droplets)")


def fig_size_spread_volume(bins, out_dir: Path) -> list[Path]:
    return _fig_spread(bins, "volume", out_dir, "fig_size_spread_volume",
                       "Droplet size spread, by volume (where the liquid is)")


# ---- GLR ---------------------------------------------------------------------------------------------------------

def fig_glr(results, out_dir: Path, covariate: str = "glr") -> list[Path]:
    keys = [k for k in HEADLINE if (k, covariate) in results.trends
            and results.trends[(k, covariate)].r is not None]
    if not keys:
        return []
    fig = Figure(figsize=(4.4 * len(keys), 3.8))
    axes = fig.subplots(1, len(keys), squeeze=False)
    conds = list(dict.fromkeys(r.condition for r in results.runs))
    cmap = {c: CONDITION_COLOURS[i % len(CONDITION_COLOURS)] for i, c in enumerate(conds)}
    for ax, key in zip(axes[0], keys):
        t = results.trends[(key, covariate)]
        for xv, yv, c in t.points:
            ax.scatter(xv, yv, s=26, color=cmap.get(c, GREY), zorder=3, edgecolor="white", linewidth=0.4)
        xs = np.array([p[0] for p in t.points])
        ys = np.array([p[1] for p in t.points])
        if t.exponent is not None and np.all(xs > 0) and np.all(ys > 0):
            b, a = t.exponent, np.mean(np.log(ys)) - t.exponent * np.mean(np.log(xs))
            grid = np.linspace(xs.min(), xs.max(), 60)
            ax.plot(grid, np.exp(a) * grid ** b, color="black", linewidth=1.2, zorder=2)
        _axes_style(ax)
        ax.set_xlabel("GLR" if covariate == "glr" else "GLR (achieved gas flow)")
        ax.set_ylabel(_label(results, key))
        bits = [f"r = {t.r:+.2f}"]
        if t.p is not None:
            bits.append(f"p = {t.p:.2g}")
        if t.exponent is not None:
            ci = (f" [{t.exponent_ci95[0]:+.2f}, {t.exponent_ci95[1]:+.2f}]" if t.exponent_ci95 else "")
            bits.append(f"exponent {t.exponent:+.2f}{ci}")
        ax.set_title("  ·  ".join(bits), fontsize=8, loc="left")
    fig.text(0.0, -0.03, "A trend, not a factor: GLR is made from the gas and liquid flows, so it cannot be "
             "separated from them.", fontsize=7, color=GREY)
    fig.tight_layout()
    return _save(fig, out_dir, "fig_glr" if covariate == "glr" else f"fig_{covariate}")


def make_all(results, bins, out_dir: Path) -> list[Path]:
    """Every figure that has something honest to draw."""
    out: list[Path] = []
    if results.responses:
        out += fig_main_effects(results, out_dir)
        out += fig_contributions(results, out_dir)
        out += fig_per_run(results, out_dir)
        out += fig_sn(results, out_dir)
        out += fig_glr(results, out_dir)
    if bins is not None:
        out += fig_size_spread_count(bins, out_dir)
        out += fig_size_spread_volume(bins, out_dir)
    return out
