"""rsm_figures.py -- the response-surface figures. No Qt, no pyplot (figures.py's rules: PNG 300 dpi
+ SVG, nothing drawn when there is nothing honest to draw).

THE MAP LAYOUT (MapLayout, map_layout()): which two factors are the map's axes, which factor gets one
PANEL per level, which gets one FIGURE per level, and where everything else is held. Default, as the
CCD plan draws it ("one contour map of gas against feed per orifice, at RPM 100, 500 and 900"): the
pair is the first two of gas, feed, RPM, orifice, height that are surface factors and not the block
factor; panels = the block factor (or a nuisance factor, or the next surface factor); figures = the
next one; any further factor is held at the best setting. Any of it can be given explicitly.

    fig_rsm_contour_<resp>[_<factor><level>]   filled contour map of the pair, one panel per panel level,
                                               the runs at that setting filled, the best setting starred
    fig_rsm_surface_<resp>                     the same as 3D surfaces (figure factor at its centre)
    fig_rsm_pairs_<resp>                       every pair of surface factors, the others at the best
                                               setting (3+ surface factors)
    fig_rsm_desirability[_<factor><level>]     overall desirability, the sweet spot hatched
    fig_rsm_profiler                           each response swept along each factor through the optimum
    fig_rsm_drift                              centre runs against time, and block repeat pairs
    fig_rsm_fit_checks                         observed vs predicted, standardised effects, residuals vs time
    fig_rsm_model_compare                      each term under every model fitted
    fig_rsm_validation                         runs outside the fit against their 95% prediction intervals
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from . import rsm_detect as rdet
from . import rsm_stats as rs
from .figures import FACTOR_COLOURS, GREY, _axes_style, _save
from .stats import t_quantile

N_GRID = 60
MAP_CMAP = "viridis"
HEADLINE = ("atom", "d32", "af_flow", "cv_droplets")
PAIR_PREFERENCE = ("sccm", "sps", "rpm", "orifice", "bh")


def _num(v) -> str:
    v = float(v)
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.4g}"


def _short(label: str) -> str:
    return label.split(" (")[0]


def _f(R, k):
    return next(f for f in R.loaded.detected.factors if f.key == k)


def _real_axis(R, k, coded):
    return np.array([R.decode(k, c) for c in np.atleast_1d(coded)])


def _x_for(R, grid: dict, fixed_real: dict) -> dict:
    """Coded model inputs: the grid (coded) + fixed factors (REAL values, surface or nuisance) + time 0."""
    n = len(next(iter(grid.values())))
    x = dict(grid)
    for k, v in fixed_real.items():
        x[k] = np.full(n, _f(R, k).real_code(v))
    if "time" in R.terms:
        x["time"] = np.zeros(n)
    return x


def _hold_sets(R) -> list[dict]:
    """Every combination of the nuisance factors' levels (one empty set when there is none)."""
    sets = [{}]
    for k in R.nuisance:
        sets = [dict(s, **{k: v}) for s in sets for v in _f(R, k).levels]
    return sets


def _optimum_at(R, fixed_real: dict, model_key: str = "reduced"):
    """The desirability optimum over the surface factors NOT in fixed_real (the rest held there)."""
    free = [k for k in R.axis if k not in fixed_real]
    if not free:
        return None
    fixed = {k: _f(R, k).real_code(v) for k, v in fixed_real.items()}
    for k in R.nuisance:
        fixed.setdefault(k, R.hold.get(k, 0.0))
    if "time" in R.terms:
        fixed["time"] = 0.0
    live = {k: getattr(f, model_key) for k, f in R.fits.items() if getattr(f, model_key) is not None
            and (k in {g.key for g in R.goals} or k in {c.key for c in R.constraints})}
    if not live or not R.goals:
        return None
    return rs.optimise(live, R.goals, {k: (-1.0, 1.0) for k in free}, fixed, R.constraints)


@dataclass
class MapLayout:
    pair: tuple                                   # (x factor, y factor)
    panel: str | None = None                      # one panel per level
    figure: str | None = None                     # one figure per level
    held: dict = field(default_factory=dict)      # factor -> REAL value for everything else

    def describe(self, R) -> str:
        bits = [f"{_short(_f(R, self.pair[0]).label)} × {_short(_f(R, self.pair[1]).label)}"]
        if self.panel:
            bits.append(f"one panel per {_short(_f(R, self.panel).label).lower()}")
        if self.figure:
            bits.append(f"one figure per {_short(_f(R, self.figure).label).lower()}")
        if self.held:
            bits.append("held: " + ", ".join(f"{_short(_f(R, k).label)} {v:g}" for k, v in self.held.items()))
        return "; ".join(bits)


def map_layout(R, pair=None, panel="auto", figure="auto") -> MapLayout | None:
    if len(R.axis) < 2:
        return None
    block = R.loaded.detected.blocks.block_factor
    order = sorted(R.axis, key=lambda k: PAIR_PREFERENCE.index(k) if k in PAIR_PREFERENCE else 99)
    if pair is None:
        pool = [k for k in order if k != block] if len([k for k in order if k != block]) >= 2 else order
        pair = (pool[0], pool[1])
    rest = [k for k in order if k not in pair] + list(R.nuisance)
    if panel == "auto":
        panel = block if block in rest else (next(iter(R.nuisance), None) or (rest[0] if rest else None))
    rest = [k for k in rest if k != panel]
    if figure == "auto":
        figure = rest[0] if rest else None
    rest = [k for k in rest if k != figure]
    held = {}
    o = R.optimum
    for k in rest:
        held[k] = R.decode(k, o.coded[k]) if o is not None and k in o.coded else float(_f(R, k).centre)
    return MapLayout(tuple(pair), panel, figure, held)


def _levels(R, k) -> list:
    return list(_f(R, k).levels) if k else [None]


def _label_of(R, fixed: dict) -> str:
    return ", ".join(f"{_short(_f(R, k).label)} {v:g}" for k, v in fixed.items() if v is not None) or "all runs"


def _surface_grid(R, fr, a, b, fixed: dict, n=N_GRID):
    ca, cb = np.linspace(-1, 1, n), np.linspace(-1, 1, n)
    A, B = np.meshgrid(ca, cb)
    g = {a: A.ravel(), b: B.ravel()}
    Z = fr.reduced.predict(_x_for(R, g, fixed))["mean"].reshape(A.shape)
    return _real_axis(R, a, ca), _real_axis(R, b, cb), Z


def _runs_on(R, fixed: dict, a: str, b: str):
    """Fitted runs at exactly this setting of the fixed factors (filled), and the rest (hollow)."""
    on, off = [], []
    for r in R.loaded.runs:
        if not r.point.in_fit:
            continue
        hit = all(r.point.values.get(k) == v for k, v in fixed.items() if v is not None)
        (on if hit else off).append((r.point.values[a], r.point.values[b]))
    return on, off


# ---- maps ----------------------------------------------------------------------------------------

def fig_contour(R, key: str, out_dir: Path, layout: MapLayout | None = None) -> list[Path]:
    fr = R.fits.get(key)
    L = layout or map_layout(R)
    if fr is None or fr.reduced is None or L is None:
        return []
    a, b = L.pair
    written = []
    for fv in _levels(R, L.figure):
        panels = _levels(R, L.panel)
        fixeds = []
        for pv in panels:
            fixed = dict(L.held)
            if L.panel:
                fixed[L.panel] = pv
            if L.figure:
                fixed[L.figure] = fv
            fixeds.append(fixed)
        grids = [_surface_grid(R, fr, a, b, fx) for fx in fixeds]
        lo, hi = min(g[2].min() for g in grids), max(g[2].max() for g in grids)
        levels = np.linspace(lo, hi, 14) if hi > lo else np.linspace(lo - 1, hi + 1, 3)
        fig = Figure(figsize=(4.4 * len(panels) + 1.0, 4.3), layout="constrained")
        axes = fig.subplots(1, len(panels), squeeze=False)[0]
        cs = None
        for ax, fx, (xa, xb, Z) in zip(axes, fixeds, grids):
            cs = ax.contourf(xa, xb, Z, levels=levels, cmap=MAP_CMAP)
            cl = ax.contour(xa, xb, Z, levels=levels[::2], colors="white", linewidths=0.5, alpha=0.8)
            ax.clabel(cl, fontsize=6, fmt="%.3g")
            on, off = _runs_on(R, fx, a, b)
            for pts, filled in ((off, False), (on, True)):
                if pts:
                    ax.scatter(*zip(*pts), s=24 if filled else 10, facecolor="white" if filled else "none",
                               edgecolor="black", linewidth=0.6, zorder=3)
            o = _optimum_at(R, {k: v for k, v in fx.items() if k in R.axis and k not in (a, b)})
            if o is not None and a in o.coded and b in o.coded:
                ax.scatter(R.decode(a, o.coded[a]), R.decode(b, o.coded[b]), marker="*", s=160, color="#F2C14E",
                           edgecolor="black", linewidth=0.6, zorder=4)
            ax.set_xlabel(_f(R, a).label, fontsize=8)
            ax.set_ylabel(_f(R, b).label, fontsize=8)
            ax.tick_params(labelsize=7)
            ax.set_title(_label_of(R, {k: v for k, v in fx.items() if k in (L.panel, L.figure)}), fontsize=8, loc="left")
        fig.colorbar(cs, ax=list(axes), shrink=0.85, label=fr.label)
        held = f"; held: {_label_of(R, L.held)}" if L.held else ""
        fig.suptitle(f"{fr.label}: fitted surface ({fr.direction} is better){held}. Filled circles = runs at that "
                     f"setting, hollow = other runs; star = best setting for ALL the goals on this map", fontsize=8)
        stem = f"fig_rsm_contour_{key}" + (f"_{L.figure}{fv:g}" if L.figure else "")
        written += _save(fig, out_dir, stem)
    return written


def fig_surface(R, key: str, out_dir: Path, layout: MapLayout | None = None) -> list[Path]:
    fr = R.fits.get(key)
    L = layout or map_layout(R)
    if fr is None or fr.reduced is None or L is None:
        return []
    a, b = L.pair
    panels = _levels(R, L.panel)
    fixeds = []
    for pv in panels:
        fixed = dict(L.held)
        if L.panel:
            fixed[L.panel] = pv
        if L.figure:
            fixed[L.figure] = _f(R, L.figure).centre
        fixeds.append(fixed)
    grids = [_surface_grid(R, fr, a, b, fx, 40) for fx in fixeds]
    lo, hi = min(g[2].min() for g in grids), max(g[2].max() for g in grids)
    fig = Figure(figsize=(4.4 * len(panels), 4.2))
    for i, (fx, (xa, xb, Z)) in enumerate(zip(fixeds, grids)):
        ax = fig.add_subplot(1, len(panels), i + 1, projection="3d")
        XA, XB = np.meshgrid(xa, xb)
        ax.plot_surface(XA, XB, Z, cmap=MAP_CMAP, vmin=lo, vmax=hi, linewidth=0, antialiased=True, alpha=0.9)
        for r in R.loaded.runs:
            if r.point.in_fit and r.values.get(key) is not None and \
                    all(r.point.values.get(k) == v for k, v in fx.items()):
                ax.scatter(r.point.values[a], r.point.values[b], r.values[key], color="black", s=10, depthshade=False)
        if hi > lo:
            ax.set_zlim(lo, hi)
        ax.set_xlabel(_short(_f(R, a).label), fontsize=7)
        ax.set_ylabel(_short(_f(R, b).label), fontsize=7)
        ax.set_zlabel(_short(fr.label), fontsize=7)
        ax.tick_params(labelsize=6)
        ax.set_title(_label_of(R, {k: v for k, v in fx.items() if k in (L.panel, L.figure)}), fontsize=8)
        ax.view_init(elev=24, azim=-130)
    fig.suptitle(f"{fr.label}: fitted surface in 3D (black points = the measured runs at that setting)",
                 fontsize=9, y=0.98)
    return _save(fig, out_dir, f"fig_rsm_surface_{key}")


def fig_pairs(R, key: str, out_dir: Path) -> list[Path]:
    """Every pair of surface factors, the others held at the best setting (3+ surface factors)."""
    fr = R.fits.get(key)
    if fr is None or fr.reduced is None or len(R.axis) < 3:
        return []
    o = R.optimum
    best = {k: (R.decode(k, o.coded[k]) if o is not None else float(_f(R, k).centre)) for k in R.axis}
    k = len(R.axis)
    fig = Figure(figsize=(3.0 * (k - 1) + 1.0, 2.8 * (k - 1) + 0.6), layout="constrained")
    axes = fig.subplots(k - 1, k - 1, squeeze=False)
    grids = {}
    for i in range(1, k):
        for j in range(i):
            a, b = R.axis[j], R.axis[i]
            fixed = {kk: v for kk, v in best.items() if kk not in (a, b)}
            grids[(i, j)] = (a, b, _surface_grid(R, fr, a, b, fixed, 40))
    lo = min(g[2][2].min() for g in grids.values())
    hi = max(g[2][2].max() for g in grids.values())
    levels = np.linspace(lo, hi, 12) if hi > lo else np.linspace(lo - 1, hi + 1, 3)
    cs = None
    for i in range(1, k):
        for j in range(k - 1):
            ax = axes[i - 1][j]
            if j >= i:
                ax.axis("off")
                continue
            a, b, (xa, xb, Z) = grids[(i, j)]
            cs = ax.contourf(xa, xb, Z, levels=levels, cmap=MAP_CMAP)
            ax.scatter(best[a], best[b], marker="*", s=90, color="#F2C14E", edgecolor="black", linewidth=0.5, zorder=4)
            ax.tick_params(labelsize=6)
            if i == k - 1:
                ax.set_xlabel(_f(R, a).label, fontsize=7)
            if j == 0:
                ax.set_ylabel(_f(R, b).label, fontsize=7)
    fig.colorbar(cs, ax=axes.ravel().tolist(), shrink=0.7, label=fr.label)
    fig.suptitle(f"{fr.label}: every pair of factors, the others at the best setting ("
                 + ", ".join(f"{_short(_f(R, kk).label)} {_num(v)}" for kk, v in best.items()) + ")", fontsize=8)
    return _save(fig, out_dir, f"fig_rsm_pairs_{key}")


# ---- profiler, desirability, drift ----------------------------------------------------------------------

def fig_profiler(R, out_dir: Path, keys=None) -> list[Path]:
    o = R.optimum
    keys = [k for k in (keys or [g.key for g in R.goals] + ["peak_bar"]) if k in R.fits and R.fits[k].reduced]
    if o is None or not keys:
        return []
    holds = {k: _f(R, k).centre for k in R.nuisance}
    fig = Figure(figsize=(3.0 * len(R.axis) + 0.8, 2.2 * len(keys) + 0.8))
    axes = fig.subplots(len(keys), len(R.axis), squeeze=False, sharex="col")
    sweep = np.linspace(-1, 1, 81)
    for i, key in enumerate(keys):
        f = R.fits[key].reduced
        for j, k in enumerate(R.axis):
            ax = axes[i][j]
            g = {kk: np.full(sweep.size, o.coded[kk]) for kk in R.axis}
            g[k] = sweep
            pr = f.predict(_x_for(R, g, holds))
            xs = _real_axis(R, k, sweep)
            ax.fill_between(xs, pr["pi"][0], pr["pi"][1], color=FACTOR_COLOURS[j % 7], alpha=0.12, linewidth=0)
            ax.fill_between(xs, pr["ci"][0], pr["ci"][1], color=FACTOR_COLOURS[j % 7], alpha=0.3, linewidth=0)
            ax.plot(xs, pr["mean"], color=FACTOR_COLOURS[j % 7], linewidth=1.6)
            ax.axvline(R.decode(k, o.coded[k]), color="black", linestyle=":", linewidth=0.8)
            ax.tick_params(labelsize=7)
            _axes_style(ax)
            if j == 0:
                ax.set_ylabel(_short(R.fits[key].label), fontsize=8)
            if i == len(keys) - 1:
                ax.set_xlabel(_f(R, k).label, fontsize=8)
    held = ", ".join(f"{_short(_f(R, k).label)} {v:g}" for k, v in holds.items())
    fig.suptitle("Prediction profiler through the optimum (dotted): each factor swept with the others at the "
                 f"optimum{'; ' + held if held else ''}. Dark band = 95% CI of the mean, light = 95% prediction "
                 "interval for one new run", fontsize=8, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return _save(fig, out_dir, "fig_rsm_profiler")


def fig_desirability(R, out_dir: Path, layout: MapLayout | None = None) -> list[Path]:
    L = layout or map_layout(R)
    if not R.goals or L is None:
        return []
    live = {k: f.reduced for k, f in R.fits.items() if f.reduced is not None}
    if not all(g.key in live for g in R.goals):
        return []
    a, b = L.pair
    written = []
    ca, cb = np.linspace(-1, 1, N_GRID), np.linspace(-1, 1, N_GRID)
    A, B = np.meshgrid(ca, cb)
    for fv in _levels(R, L.figure):
        panels = _levels(R, L.panel)
        fig = Figure(figsize=(4.4 * len(panels) + 1.0, 4.3), layout="constrained")
        axes = fig.subplots(1, len(panels), squeeze=False)[0]
        cs = None
        for ax, pv in zip(axes, panels):
            fixed = dict(L.held)
            if L.panel:
                fixed[L.panel] = pv
            if L.figure:
                fixed[L.figure] = fv
            x = _x_for(R, {a: A.ravel(), b: B.ravel()}, fixed)
            preds = {k: f.predict(x)["mean"] for k, f in live.items()}
            D = rs.desirability(preds, R.goals, R.constraints).reshape(A.shape)
            sweet = np.all([g_.d(preds[g_.key]) >= 0.5 for g_ in R.goals], axis=0).reshape(A.shape)
            xa, xb = _real_axis(R, a, ca), _real_axis(R, b, cb)
            cs = ax.contourf(xa, xb, D, levels=np.linspace(0, 1, 11), cmap="magma")
            if sweet.any() and not sweet.all():
                ax.contourf(xa, xb, sweet.astype(float), levels=[0.5, 1.5], colors="none", hatches=["///"])
                ax.contour(xa, xb, sweet.astype(float), levels=[0.5], colors="white", linewidths=1.0)
            o = _optimum_at(R, {k: v for k, v in fixed.items() if k in R.axis and k not in (a, b)})
            title = _label_of(R, {k: v for k, v in fixed.items() if k in (L.panel, L.figure)})
            if o is not None and a in o.coded:
                ax.scatter(R.decode(a, o.coded[a]), R.decode(b, o.coded[b]), marker="*", s=160, color="#F2C14E",
                           edgecolor="black", linewidth=0.6, zorder=4)
                title += f"   D max {o.D:.2f}"
            ax.set_title(title, fontsize=8, loc="left")
            ax.set_xlabel(_f(R, a).label, fontsize=8)
            ax.set_ylabel(_f(R, b).label, fontsize=8)
            ax.tick_params(labelsize=7)
        fig.colorbar(cs, ax=list(axes), shrink=0.85, label="overall desirability D")
        goals = "; ".join(f"{_short(R.fits[g_.key].label)} {'up' if g_.direction == 'max' else 'down' if g_.direction == 'min' else 'to target'}"
                          for g_ in R.goals)
        fig.suptitle(f"Where all the goals are met: desirability D ({goals}); hatched = every goal at least half "
                     f"met; star = optimum on this map", fontsize=8)
        written += _save(fig, out_dir, "fig_rsm_desirability" + (f"_{L.figure}{fv:g}" if L.figure else ""))
    return written


def fig_drift(R, out_dir: Path, keys=HEADLINE) -> list[Path]:
    """Centre runs against capture time (with their trend) and repeated settings inside a block (first
    to last): what the day did to the same setting."""
    keys = [k for k in keys if k in R.fits and R.fits[k].full is not None]
    cen = [r for r in R.loaded.runs if r.point.in_fit and r.point.kind == rdet.CENTRE and r.hours is not None]
    have_pairs = any(R.fits[k].block_pairs for k in keys)
    if not keys or (len(cen) < 3 and not have_pairs):
        return []
    fig = Figure(figsize=(3.4 * len(keys), 3.2))
    axes = fig.subplots(1, len(keys), squeeze=False)[0]
    for ax, key in zip(axes, keys):
        fr = R.fits[key]
        if len(cen) >= 3:
            h = np.array([r.hours for r in cen])
            v = np.array([r.values.get(key, np.nan) for r in cen], float)
            ax.scatter(h, v, s=26, color="#22313F", zorder=3, label="centre runs")
            t = fr.centre_trend
            if t is not None:
                ax.plot([h.min(), h.max()], [np.nanmean(v) + t.slope_per_h * (x - h.mean()) for x in (h.min(), h.max())],
                        color="#22313F", linewidth=1)
        for i, (_, ra, rb, _, z) in enumerate(fr.block_pairs):
            if ra.hours is None or rb.hours is None:
                continue
            ax.plot([ra.hours, rb.hours], [ra.values[key], rb.values[key]], "-o", color="#E07A3F", ms=3, linewidth=0.9,
                    alpha=0.8, label="block repeats (first, last)" if i == 0 else None)
        title = _short(fr.label)
        if fr.centre_trend is not None and fr.centre_trend.p is not None:
            title += f"\ncentres {fr.centre_trend.slope_per_h:+.3g}/h, p = {fr.centre_trend.p:.2g}"
        ax.set_title(title, fontsize=8, loc="left")
        ax.set_xlabel("hours from the first run", fontsize=7)
        ax.tick_params(labelsize=7)
        _axes_style(ax)
    axes[0].legend(fontsize=6, frameon=False)
    fig.suptitle("Drift: the same setting repeated through the day (centre runs and block repeats). A slope or a "
                 "step means something changed with time", fontsize=8, y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return _save(fig, out_dir, "fig_rsm_drift")


# ---- fit checks, model comparison, validation ------------------------------------------------------------

def fig_fit_checks(R, out_dir: Path, keys=HEADLINE) -> list[Path]:
    keys = [k for k in keys if k in R.fits and R.fits[k].full is not None]
    if not keys:
        return []
    fig = Figure(figsize=(12.0, 2.7 * len(keys) + 0.8))
    axes = fig.subplots(len(keys), 3, squeeze=False)
    for i, key in enumerate(keys):
        fr = R.fits[key]
        red, full = fr.reduced, fr.full
        a0, a1, a2 = axes[i]
        a0.scatter(red.fitted, red.y, s=14, color="#22313F")
        lim = [min(red.fitted.min(), red.y.min()), max(red.fitted.max(), red.y.max())]
        a0.plot(lim, lim, color=GREY, linewidth=0.8)
        a0.set_xlabel("predicted (simplified model)", fontsize=7)
        a0.set_ylabel(f"{_short(fr.label)}\nobserved", fontsize=7)
        a0.set_title(f"R² {red.r2:.3f}, predicted R² {red.r2_pred:.3f}" if red.r2_pred is not None else "",
                     fontsize=7, loc="left")
        terms = [t for t in full.terms if t != "1"]
        tv = np.array([abs(full.t[full.terms.index(t)]) for t in terms])
        order = np.argsort(tv)
        a1.barh(range(len(terms)), tv[order], color=["#E07A3F" if tv[o] > t_quantile(0.05, full.df_resid) else
                                                     "#C9D3D9" for o in order])
        a1.set_yticks(range(len(terms)), [terms[o] for o in order], fontsize=6)
        a1.axvline(t_quantile(0.05, full.df_resid), color="black", linestyle=":", linewidth=0.8)
        a1.set_xlabel("|t| (full model); dotted = 5% significance", fontsize=7)
        rows = [r for r in R.loaded.runs if r.point.in_fit and r.values.get(key) is not None]
        h = np.array([r.hours if r.hours is not None else np.nan for r in rows])
        a2.scatter(h, red.std_resid, s=14, color="#22313F")
        for v in (-2, 2):
            a2.axhline(v, color=GREY, linestyle=":", linewidth=0.8)
        a2.axhline(0, color=GREY, linewidth=0.6)
        a2.set_xlabel("hours from the first run", fontsize=7)
        a2.set_ylabel("standardised residual", fontsize=7)
        lof = full.lof
        if lof is not None and lof.p is not None:
            a2.set_title(f"lack of fit p = {lof.p:.3g} ({lof.df_lof} vs {lof.df_pe} df)", fontsize=7, loc="left")
        for ax in (a0, a1, a2):
            ax.tick_params(labelsize=6)
            _axes_style(ax)
    fig.suptitle("Fit checks: observed vs predicted (on the line = good), standardised effects (Pareto), residuals "
                 "against time (no pattern = no drift)", fontsize=9, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return _save(fig, out_dir, "fig_rsm_fit_checks")


def fig_model_compare(results: dict, out_dir: Path, keys=HEADLINE) -> list[Path]:
    """results: model name -> RsmResults, all on the same runs."""
    if len(results) < 2:
        return []
    names = list(results)
    first = results[names[0]]
    keys = [k for k in keys if all(k in R.fits and R.fits[k].full is not None for R in results.values())]
    if not keys:
        return []
    terms = [t for t in first.terms if t != "1"]
    fig = Figure(figsize=(3.4 * len(keys) + 0.8, 0.32 * len(terms) + 1.8))
    axes = fig.subplots(1, len(keys), squeeze=False, sharey=True)[0]
    y = np.arange(len(terms))[::-1]
    for ax, key in zip(axes, keys):
        for m, name in enumerate(names):
            f = results[name].fits[key].full
            tq = t_quantile(0.05, f.df_resid)
            for yi, t in zip(y, terms):
                if t not in f.terms:
                    continue
                i = f.terms.index(t)
                off = (m - (len(names) - 1) / 2) * 0.28
                ax.errorbar(f.beta[i], yi + off, xerr=tq * f.se[i], fmt="o", ms=4, color=FACTOR_COLOURS[m % 7],
                            elinewidth=1.2, capsize=2, label=name if yi == y[0] else None)
        ax.axvline(0, color=GREY, linewidth=0.8)
        ax.set_yticks(y, terms, fontsize=7)
        ax.tick_params(labelsize=7)
        _axes_style(ax)
        ax.set_title(_short(first.fits[key].label), fontsize=8, loc="left")
        ax.set_xlabel("coefficient (coded units), 95% CI", fontsize=7)
    axes[0].legend(fontsize=7, frameon=False, loc="lower left")
    fig.suptitle("The same terms under each model: a term whose estimate moves between models is not separated "
                 "from what the models treat differently", fontsize=9, y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return _save(fig, out_dir, "fig_rsm_model_compare")


def fig_validation(R, out_dir: Path, keys=HEADLINE) -> list[Path]:
    keys = [k for k in keys if k in R.fits and R.fits[k].predictions]
    if not keys:
        return []
    fig = Figure(figsize=(3.6 * len(keys), 3.2))
    axes = fig.subplots(1, len(keys), squeeze=False)[0]
    for ax, key in zip(axes, keys):
        preds = R.fits[key].predictions
        for i, p in enumerate(preds):
            ax.vlines(i, p.pi[0], p.pi[1], color="#9AA5AD", linewidth=6, alpha=0.7)
            ax.scatter(i, p.mean, color="black", marker="_", s=120)
            if p.observed is not None:
                ax.scatter(i, p.observed, color="#2A9D8F" if p.inside else "#E07A3F", s=36, zorder=3,
                           edgecolor="black", linewidth=0.5)
        ax.set_xticks(range(len(preds)), [p.run.point.name[:6] for p in preds], rotation=60, fontsize=6)
        ax.set_title(_short(R.fits[key].label), fontsize=8, loc="left")
        _axes_style(ax)
    fig.suptitle("Runs kept out of the fit against their 95% prediction interval (bar); dot = observed: teal "
                 "inside, orange outside", fontsize=9, y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return _save(fig, out_dir, "fig_rsm_validation")


def make_all(models: dict, out_dir: Path, problems: list | None = None, map_keys=None,
             layout: MapLayout | None = None) -> list[Path]:
    """models: name -> RsmResults; the FIRST is the primary model the maps are drawn from."""
    if not models:
        return []
    R = next(iter(models.values()))
    L = layout or map_layout(R)
    map_keys = map_keys or [k for k in list(HEADLINE) + ["lag1", "peak_bar"] if k in R.fits]
    jobs = [(f"contour {k}", lambda k=k: fig_contour(R, k, out_dir, L)) for k in map_keys]
    jobs += [(f"surface {k}", lambda k=k: fig_surface(R, k, out_dir, L)) for k in map_keys]
    jobs += [(f"pairs {k}", lambda k=k: fig_pairs(R, k, out_dir)) for k in map_keys]
    jobs += [("profiler", lambda: fig_profiler(R, out_dir)), ("desirability", lambda: fig_desirability(R, out_dir, L)),
             ("drift", lambda: fig_drift(R, out_dir)),
             ("fit checks", lambda: fig_fit_checks(R, out_dir)),
             ("model comparison", lambda: fig_model_compare(models, out_dir)),
             ("validation", lambda: fig_validation(R, out_dir))]
    out = []
    for label, fn in jobs:
        try:
            out += fn()
        except Exception as exc:                       # noqa: BLE001 -- reported by the caller
            if problems is None:
                raise
            problems.append(f"{label} figure failed: {type(exc).__name__}: {exc}")
    return out
