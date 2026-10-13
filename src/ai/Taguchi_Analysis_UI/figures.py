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
    fig_gas_flux              each response against the gas mass flux at the orifice (log x, power-law fit),
                              coloured by orifice, hollow where the run did not get its set gas
    fig_film_thickness        the same against the silicone film thickness at the exit (orifice.py)
    fig_orifice_model         the diagram behind both: the orifice cut along and across, and the equations

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
from .tables import cond_order

DPI = 300
HEADLINE = ("d32", "d_mean", "atom")            # the responses every figure leads with (mean diameter: Ben,
                                                # 2026-10-11, on a level with D32 and atomised fraction)
# the deck template's accents ("Atomisation Ink": orange, teal, purple, yellow, then greys), so the
# figures match the slides they sit on
FACTOR_COLOURS = ("#E07A3F", "#2A9D8F", "#7B6CB0", "#F2C14E", "#22313F", "#9AA5AD", "#C9D3D9")
GREY = "#8e8e93"
# conditions need MORE distinct colours than factors do (an L9 has 9): matplotlib's tab10.
CONDITION_COLOURS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2",
                     "#7f7f7f", "#bcbd22", "#17becf")
# the orifice inserts, as in the phase 12 evidence figure (docs/notes/2026-10-13_phase12_physical_variables/)
ORIFICE_COLOURS = {0.5: "#d62728", 0.8: "#9467bd", 1.2: "#1f77b4", 1.8: "#2ca02c"}


def _save(fig: Figure, out_dir: Path, name: str, formats=("png", "svg")) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    FigureCanvasAgg(fig)
    written = []
    for ext, kw in (("png", {"dpi": DPI}), ("svg", {})):
        if ext not in formats:
            continue
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
    order = sorted(results.runs, key=lambda r: (cond_order(r.condition), r.replicate or 0, r.name))
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

def _trend_title(t) -> str:
    bits = [f"r = {t.r:+.2f}"]
    if t.p is not None:
        bits.append(f"p = {t.p:.2g}")
    if t.exponent is not None:
        ci = (f" [{t.exponent_ci95[0]:+.2f}, {t.exponent_ci95[1]:+.2f}]" if t.exponent_ci95 else "")
        bits.append(f"exponent {t.exponent:+.2f}{ci}")
    return "  ·  ".join(bits)


def _power_line(ax, t, log: bool = False) -> None:
    """The fitted power law over the FITTED points' range (no-spray runs are not in it)."""
    xs = np.array([p[0] for p in t.points])
    ys = np.array([p[1] for p in t.points])
    if t.exponent is not None and xs.size and np.all(xs > 0) and np.all(ys > 0):
        b, a = t.exponent, np.mean(np.log(ys)) - t.exponent * np.mean(np.log(xs))
        grid = np.geomspace(xs.min(), xs.max(), 60) if log else np.linspace(xs.min(), xs.max(), 60)
        ax.plot(grid, np.exp(a) * grid ** b, color="black", linewidth=1.2, zorder=2)


NO_SPRAY_LABEL = "no spray, not fitted"


def fig_glr(results, out_dir: Path, covariate: str = "glr") -> list[Path]:
    from matplotlib.lines import Line2D
    keys = [k for k in HEADLINE if (k, covariate) in results.trends
            and results.trends[(k, covariate)].r is not None]
    if not keys:
        return []
    fig = Figure(figsize=(4.4 * len(keys), 3.8))
    axes = fig.subplots(1, len(keys), squeeze=False)
    conds = list(dict.fromkeys(r.condition for r in results.runs))
    cmap = {c: CONDITION_COLOURS[i % len(CONDITION_COLOURS)] for i, c in enumerate(conds)}
    dribbles = False
    for ax, key in zip(axes[0], keys):
        t = results.trends[(key, covariate)]
        for xv, yv, c in t.points:
            ax.scatter(xv, yv, s=26, color=cmap.get(c, GREY), zorder=3, edgecolor="white", linewidth=0.4)
        for xv, yv, _c in t.excluded:
            ax.scatter(xv, yv, s=30, marker="x", color=GREY, linewidth=1.2, zorder=3)
            dribbles = True
        _power_line(ax, t)
        _axes_style(ax)
        ax.set_xlabel("GLR" if covariate == "glr" else "GLR (achieved gas flow)")
        ax.set_ylabel(_label(results, key))
        ax.set_title(_trend_title(t), fontsize=8, loc="left")
    if dribbles:
        fig.legend(handles=[Line2D([], [], linestyle="none", marker="x", color=GREY, label=NO_SPRAY_LABEL)],
                   fontsize=7, frameon=False, loc="center left", bbox_to_anchor=(1.0, 0.5))
    fig.text(0.0, -0.03, "A trend, not a factor: GLR is made from the gas and liquid flows, so it cannot be "
             "separated from them.", fontsize=7, color=GREY)
    fig.tight_layout()
    return _save(fig, out_dir, "fig_glr" if covariate == "glr" else f"fig_{covariate}")


def _orifice_colour(mm) -> str:
    return next((c for o, c in ORIFICE_COLOURS.items() if mm is not None and abs(mm - o) < 0.01), GREY)


def _plain_log(axis) -> None:
    """20, 50, 100, 200 ... rather than 10^2 alone."""
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
    axis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    axis.set_minor_formatter(NullFormatter())


def _by_orifice(results, out_dir: Path, covariate: str, name: str, xlabel: str, footnote: str,
                logx: bool = False, top=None) -> list[Path]:
    """Each headline response against a run covariate, every run of both regimes on one axis: colour =
    orifice, hollow = did not get its set gas (plotted at the gas it got), grey x = no spray (not fitted).
    `top`: (label, forward, inverse) for a second x scale on top."""
    from matplotlib.lines import Line2D
    keys = [k for k in HEADLINE if (k, covariate) in results.trends
            and results.trends[(k, covariate)].r is not None]
    if not keys:
        return []
    fig = Figure(figsize=(4.6 * len(keys), 4.0))
    axes = fig.subplots(1, len(keys), squeeze=False)
    kinds: set = set()
    dribbles = False
    for ax, key in zip(axes[0], keys):
        t = results.trends[(key, covariate)]
        for r in results.runs:
            x, y = getattr(r.context, covariate, None), r.values.get(key)
            if x is None or y is None or not math.isfinite(y) or (logx and not x > 0):
                continue                                   # a zero has no place on a log axis
            if (r.rec or {}).get("no_spray"):
                ax.scatter(x, y, s=34, marker="x", color=GREY, linewidth=1.2, zorder=3)
                dribbles = True
                continue
            op = (r.rec or {}).get("operating")
            hollow = bool(op is not None and op.not_delivered)
            o = r.context.orifice_mm
            col = _orifice_colour(o)
            kinds.add((o if o is not None else math.inf, hollow))
            ax.scatter(x, y, s=30, zorder=3, facecolor="white" if hollow else col, edgecolor=col,
                       linewidth=1.3 if hollow else 0.5)
        _power_line(ax, t, logx)
        if logx:
            ax.set_xscale("log")
            _plain_log(ax.xaxis)
        _axes_style(ax)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(_label(results, key))
        if top is not None:
            label, fwd, inv = top
            sec = ax.secondary_xaxis("top", functions=(fwd, inv))
            if logx:
                _plain_log(sec.xaxis)
            sec.set_xlabel(label, fontsize=7, color=GREY)
            sec.tick_params(labelsize=7, colors=GREY)
        ax.set_title(_trend_title(t), fontsize=8, loc="left")
    handles = []
    for o, hollow in sorted(kinds):                       # o = inf: no orifice recorded
        col = _orifice_colour(None if o == math.inf else o)
        handles.append(Line2D([], [], linestyle="none", marker="o", markersize=5.5, markeredgecolor=col,
                              markerfacecolor="white" if hollow else col, markeredgewidth=1.3 if hollow else 0.5,
                              label=("orifice not known" if o == math.inf else f"{o:g} mm")
                              + (", did not get its set gas" if hollow else "")))
    if dribbles:
        handles.append(Line2D([], [], linestyle="none", marker="x", color=GREY, label=NO_SPRAY_LABEL))
    fig.legend(handles=handles, fontsize=7, frameon=False, loc="center left", bbox_to_anchor=(1.0, 0.5))
    fig.text(0.0, -0.03, footnote, fontsize=7, color=GREY)
    fig.tight_layout()
    return _save(fig, out_dir, name)


def fig_gas_flux(results, out_dir: Path) -> list[Path]:
    """Each headline response against the gas mass flux at the orifice (covariates.py), log x."""
    rhos = {r.context.rho_gas for r in results.runs if r.context and r.context.gas_flux is not None}
    top = None
    if len(rhos) == 1 and None not in rhos:               # one gas density: the velocity equivalent on top
        rho = next(iter(rhos))
        top = (f"exit velocity equivalent at {rho:g} kg/m³ (m/s)", lambda g, rho=rho: g / rho,
               lambda v, rho=rho: v * rho)
    return _by_orifice(results, out_dir, "gas_flux", "fig_gas_flux",
                       "Gas mass flux at the orifice, delivered (kg/m²/s)",
                       "A trend, not a factor: the flux is made from the gas flow and the orifice, so it cannot be "
                       "separated from them. Hollow: the run did not get its set gas (pressure-limited or gas "
                       "short), plotted at the gas it got. No-spray runs are plotted, not fitted.",
                       logx=True, top=top)


def fig_film_thickness(results, out_dir: Path) -> list[Path]:
    """Each headline response against the silicone film thickness at the exit (orifice.py, annular estimate)."""
    cds = {r.context.cd_source for r in results.runs if r.context and r.context.film_um is not None}
    cd = ("Cd = 1 (ideal, not measured)" if cds == {"ideal (not measured)"} else
          "Cd as measured" if "ideal (not measured)" not in cds else "Cd measured for some inserts, 1 for others")
    return _by_orifice(results, out_dir, "film_um", "fig_film_thickness",
                       "Silicone film thickness at the exit, annular estimate (µm)",
                       f"An estimate, not a measurement: h = (d/2)(1 − √α), α = measured gas flux / gas-only "
                       f"capacity at the camera-window P0; {cd}. A covariate made from the gas, the pressure and "
                       f"the orifice, not a factor. No-spray runs are plotted, not fitted.")


# ---- the orifice model diagram ------------------------------------------------------------------------------------

SILICONE_COLOUR = "#E07A3F"      # as the un-atomised liquid in the classical renders
GAS_COLOUR = "#d6eaf8"
GAS_EDGE = "#5b9bd5"
INSERT_COLOUR = "#dfe5e9"


def fig_orifice_model(out_dir: Path, alpha: float = 0.25) -> list[Path]:
    """The model behind the gas flux and the silicone film: the orifice cut along its axis (film on the wall,
    gas core), the exit cross-section (gas core alpha A, silicone annulus), and the equations. Drawn at
    `alpha` (0.25, the CCD day's best runs)."""
    from matplotlib.patches import Circle, FancyArrowPatch, Rectangle, Wedge
    fig = Figure(figsize=(12, 6.9))
    gs = fig.add_gridspec(2, 2, width_ratios=(1.75, 1), height_ratios=(1.55, 1), hspace=0.08, wspace=0.05,
                          left=0.02, right=0.98, top=0.88, bottom=0.02)
    ax, cx, eq = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, :])
    R, L, W = 1.0, 5.0, 2.2                  # bore radius, length, chamber half-height (drawing units)
    h = R * (1 - math.sqrt(alpha))
    rng = np.random.default_rng(3)

    def dim(a, x0, y0, x1, y1, text, tx, ty, **kw):
        a.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="<->", mutation_scale=10, color="#22313F",
                                    linewidth=1.0, shrinkA=0, shrinkB=0, zorder=6))
        a.text(tx, ty, text, fontsize=12, color="#22313F", zorder=7, **kw)

    # -- along the orifice
    ax.add_patch(Rectangle((-3.0, -W), 3.0, 2 * W, facecolor=SILICONE_COLOUR, alpha=0.85, edgecolor="none"))
    for _ in range(22):                       # the two-phase mixture: gas bubbles in silicone
        bx, by, br = rng.uniform(-2.8, -0.3), rng.uniform(-1.9, 1.9), rng.uniform(0.08, 0.32)
        ax.add_patch(Circle((bx, by), br, facecolor=GAS_COLOUR, edgecolor=GAS_EDGE, linewidth=0.6, zorder=2))
    for sgn in (1, -1):
        ax.add_patch(Rectangle((0, sgn * R if sgn > 0 else -W), L, W - R, facecolor=INSERT_COLOUR,
                               edgecolor="#9aa5ad", hatch="////", linewidth=0.8, zorder=1))
        ax.add_patch(Rectangle((0, sgn * R - (h if sgn > 0 else 0)), L, h, facecolor=SILICONE_COLOUR,
                               edgecolor="none", zorder=2))
        ax.plot([-3.0, 0], [sgn * W, sgn * W], color="#9aa5ad", linewidth=1.5)
    ax.add_patch(Rectangle((0, -R + h), L, 2 * (R - h), facecolor=GAS_COLOUR, edgecolor="none", zorder=2))
    ax.add_patch(FancyArrowPatch((0.35, 0), (L - 0.2, 0), arrowstyle="-|>", mutation_scale=16, color=GAS_EDGE,
                                 linewidth=2.2, zorder=4))
    ax.text(L / 2, 0.14, "gas core, choked (≈ sonic)", ha="center", va="bottom", fontsize=10.5, color="#1f4e79",
            zorder=5)
    for sgn in (1, -1):
        ax.add_patch(FancyArrowPatch((0.5, sgn * (R - h / 2)), (3.2, sgn * (R - h / 2)), arrowstyle="-|>",
                                     mutation_scale=10, color="white", linewidth=1.3, zorder=4))
    ax.annotate("silicone film on the wall, speed $u_L$", xy=(1.6, R - h / 2), xytext=(2.7, W + 0.3),
                ha="center", va="bottom", fontsize=10,
                arrowprops={"arrowstyle": "-", "color": "#22313F", "linewidth": 0.8}, zorder=7)
    for _ in range(40):                       # the spray leaving the exit
        sx = rng.uniform(L + 0.3, L + 2.4)
        spread = 0.5 + 0.55 * (sx - L)
        ax.add_patch(Circle((sx, rng.uniform(-spread, spread)), rng.uniform(0.03, 0.09),
                            facecolor=SILICONE_COLOUR, edgecolor="none", zorder=3))
    dim(ax, 0, -W - 0.3, L, -W - 0.3, "$L$", L / 2, -W - 0.75, ha="center")
    dim(ax, L + 0.15, -R, L + 0.15, R, "$d$", L + 0.3, -0.85, ha="left")
    dim(ax, L - 0.6, R - h, L - 0.6, R, "$h$", L - 0.75, R - h / 2, ha="right", va="center")
    ax.text(-1.5, W + 0.3, "two-phase mixture at $P_0$\n(measured upstream)", ha="center", va="bottom",
            fontsize=10)
    ax.text(L + 1.35, W + 0.3, "atmosphere\n$P_a$ = 1.013 barA", ha="center", va="bottom", fontsize=10)
    ax.text(3.7, (R + W) / 2, "exit orifice insert", ha="center", va="center", fontsize=9.5, color="#3a3a3c",
            zorder=7, bbox={"facecolor": INSERT_COLOUR, "edgecolor": "none", "pad": 1.5})
    ax.set_xlim(-3.1, L + 2.6)
    ax.set_ylim(-W - 1.15, W + 1.3)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Along the orifice", fontsize=12, loc="left")

    # -- across the exit
    cx.add_patch(Wedge((0, 0), 1.35, 0, 360, width=0.35, facecolor=INSERT_COLOUR, edgecolor="#9aa5ad",
                       hatch="////", linewidth=0.8))
    cx.add_patch(Circle((0, 0), R, facecolor=SILICONE_COLOUR, edgecolor="none"))
    cx.add_patch(Circle((0, 0), R - h, facecolor=GAS_COLOUR, edgecolor=GAS_EDGE, linewidth=1.0))
    cx.text(0, 0.08, "gas core", ha="center", va="bottom", fontsize=10.5, color="#1f4e79")
    cx.text(0, -0.08, r"area $\alpha A$", ha="center", va="top", fontsize=10.5, color="#1f4e79")
    cx.annotate(r"silicone film, area $(1-\alpha)A$", xy=(-0.62, 0.62), xytext=(-1.6, 1.5), fontsize=10.5,
                va="bottom", arrowprops={"arrowstyle": "-", "color": "#22313F", "linewidth": 0.8})
    dim(cx, R - h, 0, R, 0, "$h$", R - h / 2, 0.08, ha="center", va="bottom")
    for x in (-R, R):
        cx.plot([x, x], [-0.15, -1.6], color="#22313F", linewidth=0.6, linestyle=(0, (2, 2)))
    dim(cx, -R, -1.55, R, -1.55, "$d$", 0, -1.62, ha="center", va="top")
    cx.set_xlim(-1.65, 1.65)
    cx.set_ylim(-2.0, 1.9)
    cx.set_aspect("equal")
    cx.axis("off")
    cx.set_title("Across the exit", fontsize=12, loc="left")

    # -- the equations
    eq.axis("off")
    rows = [
        (r"$G = \dot{m}_g\,/\,A,\quad \dot{m}_g = Q_g\,\rho_g\,/\,6\times10^{7},\quad A = \pi d^2/4$",
         "measured gas mass flux: the gas the run got in the camera window, at its recorded density"),
        (r"$G_{gas}(P_0) = C_d\,P_0\,\sqrt{\gamma/(R\,T)}\,\left(\frac{2}{\gamma+1}\right)^{\frac{\gamma+1}"
         r"{2(\gamma-1)}}$",
         "what gas alone could pass from $P_0$ (choked; the subsonic form below $P_0$ = 1.89 $P_a$), 20 °C"),
        (r"$\alpha = G\,/\,G_{gas}(P_0)$", "the gas share of the orifice area; the rest, $1-\\alpha$, is silicone"),
        (r"$u_L = Q_L\,/\,\left((1-\alpha)\,A\right)$", "silicone speed in the orifice ($Q_L$: the syringe flow)"),
        (r"$h = \frac{d}{2}\,\left(1-\sqrt{\alpha}\right)$", "film thickness for an annular exit (gas core, film "
                                                             "on the wall)"),
    ]
    for i, (math_text, words) in enumerate(rows):
        y = 0.9 - i * 0.2
        eq.text(0.02, y, math_text, fontsize=13, va="center", transform=eq.transAxes)
        eq.text(0.5, y, words, fontsize=10, va="center", color="#3a3a3c", transform=eq.transAxes)
    fig.suptitle(f"How the gas flux and the silicone film are estimated (drawn at α = {alpha:g})", fontsize=13,
                 x=0.02, ha="left")
    return _save(fig, out_dir, "fig_orifice_model")


def covariate_figures(results, out_dir: Path) -> list[Path]:
    """The gas flux and silicone film figures, with the model diagram whenever the flux is drawn."""
    out = fig_gas_flux(results, out_dir)
    if out:
        out += fig_orifice_model(out_dir)
    return out + fig_film_thickness(results, out_dir)


def make_all(results, bins, out_dir: Path) -> list[Path]:
    """Every figure that has something honest to draw."""
    out: list[Path] = []
    if results.responses:
        out += fig_main_effects(results, out_dir)
        out += fig_contributions(results, out_dir)
        out += fig_per_run(results, out_dir)
        out += fig_sn(results, out_dir)
        out += fig_glr(results, out_dir)
        out += covariate_figures(results, out_dir)
    if bins is not None:
        out += fig_size_spread_count(bins, out_dir)
        out += fig_size_spread_volume(bins, out_dir)
    return out
