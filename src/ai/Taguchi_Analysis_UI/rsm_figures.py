"""rsm_figures.py -- the response-surface figures. No Qt, no pyplot (figures.py's rules: PNG 300 dpi
+ SVG, nothing drawn when there is nothing honest to draw).

    fig_rsm_contour_<resp>     filled contour map over each pair of axis factors, in real units, one
                               panel per held level of the nuisance factor (or of the remaining axis
                               factors), the runs at that level overlaid, the optimum starred
    fig_rsm_surface_<resp>     the same fit as a 3D surface, with the runs as points
    fig_rsm_profiler           each response swept along each axis factor through the optimum, with
                               the 95% CI of the mean and the 95% prediction interval
    fig_rsm_desirability       overall desirability D, the sweet spot (every goal at least half met)
                               hatched, the optimum starred
    fig_rsm_fit_checks         per headline response: observed vs predicted, standardised effects
                               (Pareto, with the 5% line), residuals vs capture time
    fig_rsm_model_compare      each term's coefficient (95% CI) under every model fitted, so a term
                               that changes with the model (an interaction confounded with a
                               nuisance factor) is visible
    fig_rsm_validation         runs outside the fit (check, control, validation): observed vs the
                               95% prediction interval
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from . import rsm_stats as rs
from .figures import FACTOR_COLOURS, GREY, _axes_style, _save
from .stats import t_quantile

N_GRID = 60
MAP_CMAP = "viridis"
HEADLINE = ("atom", "d32", "af_flow", "cv_droplets")


def _short(label: str) -> str:
    return label.split(" (")[0]


def _unit_label(f) -> str:
    return f.label


def _hold_sets(R) -> list[dict]:
    """The held values the maps are drawn at: every level of each nuisance factor (all combinations);
    a single empty set when there is none."""
    det = R.loaded.detected
    sets = [{}]
    for k in R.nuisance:
        f = next(x for x in det.factors if x.key == k)
        sets = [dict(s, **{k: v}) for s in sets for v in f.levels]
    return sets


def _x_for(R, grid: dict, hold_real: dict, time0: bool = True) -> dict:
    """Coded inputs for a prediction: axis grid (coded) + held factors (real -> coded) + time 0."""
    det = R.loaded.detected
    n = len(next(iter(grid.values())))
    x = dict(grid)
    for k, v in hold_real.items():
        f = next(f_ for f_ in det.factors if f_.key == k)
        x[k] = np.full(n, f.real_code(v))
    if "time" in R.terms:
        x["time"] = np.zeros(n)
    return x


def _optimum_at(R, hold_real: dict, model_key: str = "reduced"):
    det = R.loaded.detected
    fixed = {k: next(f for f in det.factors if f.key == k).real_code(v) for k, v in hold_real.items()}
    if "time" in R.terms:
        fixed["time"] = 0.0
    live = {k: getattr(f, model_key) for k, f in R.fits.items() if getattr(f, model_key) is not None
            and (k in {g.key for g in R.goals} or k in {c.key for c in R.constraints})}
    if not live or not R.goals:
        return None
    return rs.optimise(live, R.goals, {k: (-1.0, 1.0) for k in R.axis}, fixed, R.constraints)


def _pairs(R) -> list[tuple[str, str]]:
    return list(itertools.combinations(R.axis, 2))


def _f(R, k):
    return next(f for f in R.loaded.detected.factors if f.key == k)


def _real_axis(R, k, coded):
    return np.array([R.decode(k, c) for c in np.atleast_1d(coded)])


# ---- maps ----------------------------------------------------------------------------------------

def fig_contour(R, key: str, out_dir: Path, name: str | None = None) -> list[Path]:
    fr = R.fits.get(key)
    if fr is None or fr.reduced is None or len(R.axis) < 2:
        return []
    holds = _hold_sets(R)
    pairs = _pairs(R)
    written = []
    for a, b in pairs:
        others = [k for k in R.axis if k not in (a, b)]
        fig = Figure(figsize=(4.5 * len(holds) + 1.0, 4.3), layout="constrained")
        axes = fig.subplots(1, len(holds), squeeze=False)[0]
        ca, cb = np.linspace(-1, 1, N_GRID), np.linspace(-1, 1, N_GRID)
        A, B = np.meshgrid(ca, cb)
        zs = []
        for hold in holds:
            g = {a: A.ravel(), b: B.ravel()}
            for o in others:
                g[o] = np.zeros(A.size)
            zs.append(fr.reduced.predict(_x_for(R, g, hold))["mean"].reshape(A.shape))
        lo, hi = min(z.min() for z in zs), max(z.max() for z in zs)
        levels = np.linspace(lo, hi, 14)
        for ax, hold, Z in zip(axes, holds, zs):
            cs = ax.contourf(_real_axis(R, a, ca), _real_axis(R, b, cb), Z, levels=levels, cmap=MAP_CMAP)
            cl = ax.contour(_real_axis(R, a, ca), _real_axis(R, b, cb), Z, levels=levels[::2], colors="white",
                            linewidths=0.5, alpha=0.8)
            ax.clabel(cl, fontsize=6, fmt="%.3g")
            runs = R.loaded.runs
            for r in runs:
                if not r.point.in_fit:
                    continue
                at = all(r.point.values.get(k) == v for k, v in hold.items())
                ax.scatter(r.point.values[a], r.point.values[b], s=22 if at else 10,
                           facecolor="white" if at else "none", edgecolor="black", linewidth=0.6, zorder=3)
            o = _optimum_at(R, hold)
            if o is not None:
                ax.scatter(R.decode(a, o.coded[a]), R.decode(b, o.coded[b]), marker="*", s=160, color="#F2C14E",
                           edgecolor="black", linewidth=0.6, zorder=4)
            ax.set_xlabel(_f(R, a).label, fontsize=8)
            ax.set_ylabel(_f(R, b).label, fontsize=8)
            ax.tick_params(labelsize=7)
            ax.set_title(", ".join(f"{_short(_f(R, k).label)} {v:g}" for k, v in hold.items()) or "all runs",
                         fontsize=8, loc="left")
        fig.colorbar(cs, ax=list(axes), shrink=0.85, label=fr.label)
        fig.suptitle(f"{fr.label}: fitted surface ({'larger' if fr.direction == 'larger' else 'smaller'} is better). "
                     f"Filled circles = runs at that setting, hollow = other runs; star = the best setting for ALL "
                     f"the goals together (desirability), not this response's own peak", fontsize=8)
        stem = name or f"fig_rsm_contour_{key}" + (f"_{a}_{b}" if len(pairs) > 1 else "")
        written += _save(fig, out_dir, stem)
    return written


def fig_surface(R, key: str, out_dir: Path) -> list[Path]:
    fr = R.fits.get(key)
    if fr is None or fr.reduced is None or len(R.axis) < 2:
        return []
    a, b = _pairs(R)[0]
    holds = _hold_sets(R)
    fig = Figure(figsize=(4.4 * len(holds), 4.2))
    ca, cb = np.linspace(-1, 1, 40), np.linspace(-1, 1, 40)
    A, B = np.meshgrid(ca, cb)
    zs = []
    for hold in holds:
        g = {a: A.ravel(), b: B.ravel()}
        for o in [k for k in R.axis if k not in (a, b)]:
            g[o] = np.zeros(A.size)
        zs.append(fr.reduced.predict(_x_for(R, g, hold))["mean"].reshape(A.shape))
    lo, hi = min(z.min() for z in zs), max(z.max() for z in zs)
    XA, XB = np.meshgrid(_real_axis(R, a, ca), _real_axis(R, b, cb))
    for i, (hold, Z) in enumerate(zip(holds, zs)):
        ax = fig.add_subplot(1, len(holds), i + 1, projection="3d")
        ax.plot_surface(XA, XB, Z, cmap=MAP_CMAP, vmin=lo, vmax=hi, linewidth=0, antialiased=True, alpha=0.9)
        for r in R.loaded.runs:
            if r.point.in_fit and all(r.point.values.get(k) == v for k, v in hold.items()) \
                    and r.values.get(key) is not None:
                ax.scatter(r.point.values[a], r.point.values[b], r.values[key], color="black", s=10, depthshade=False)
        ax.set_zlim(lo, hi)
        ax.set_xlabel(_short(_f(R, a).label), fontsize=7)
        ax.set_ylabel(_short(_f(R, b).label), fontsize=7)
        ax.set_zlabel(_short(fr.label), fontsize=7)
        ax.tick_params(labelsize=6)
        ax.set_title(", ".join(f"{_short(_f(R, k).label)} {v:g}" for k, v in hold.items()) or "all runs", fontsize=8)
        ax.view_init(elev=24, azim=-130)
    fig.suptitle(f"{fr.label}: fitted surface in 3D (black points = the measured runs at that setting)",
                 fontsize=9, y=0.98)
    return _save(fig, out_dir, f"fig_rsm_surface_{key}")


# ---- profiler and desirability ----------------------------------------------------------------------------

def fig_profiler(R, out_dir: Path, keys=None) -> list[Path]:
    o = R.optimum
    keys = [k for k in (keys or [g.key for g in R.goals] + ["peak_bar"]) if k in R.fits and R.fits[k].reduced]
    if o is None or not keys:
        return []
    holds = {k: _f(R, k).centre for k in R.nuisance}
    fig = Figure(figsize=(3.3 * len(R.axis) + 0.6, 2.2 * len(keys) + 0.8))
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


def fig_desirability(R, out_dir: Path) -> list[Path]:
    if not R.goals or len(R.axis) < 2:
        return []
    live = {k: f.reduced for k, f in R.fits.items() if f.reduced is not None}
    if not all(g.key in live for g in R.goals):
        return []
    a, b = _pairs(R)[0]
    holds = _hold_sets(R)
    fig = Figure(figsize=(4.5 * len(holds) + 1.0, 4.3), layout="constrained")
    axes = fig.subplots(1, len(holds), squeeze=False)[0]
    ca, cb = np.linspace(-1, 1, N_GRID), np.linspace(-1, 1, N_GRID)
    A, B = np.meshgrid(ca, cb)
    for ax, hold in zip(axes, holds):
        g = {a: A.ravel(), b: B.ravel()}
        for o_ in [k for k in R.axis if k not in (a, b)]:
            g[o_] = np.zeros(A.size)
        x = _x_for(R, g, hold)
        preds = {k: f.predict(x)["mean"] for k, f in live.items()}
        D = rs.desirability(preds, R.goals, R.constraints).reshape(A.shape)
        sweet = np.all([g_.d(preds[g_.key]) >= 0.5 for g_ in R.goals], axis=0).reshape(A.shape)
        cs = ax.contourf(_real_axis(R, a, ca), _real_axis(R, b, cb), D, levels=np.linspace(0, 1, 11), cmap="magma")
        if sweet.any():
            ax.contourf(_real_axis(R, a, ca), _real_axis(R, b, cb), sweet.astype(float), levels=[0.5, 1.5],
                        colors="none", hatches=["///"])
            ax.contour(_real_axis(R, a, ca), _real_axis(R, b, cb), sweet.astype(float), levels=[0.5],
                       colors="white", linewidths=1.0)
        o = _optimum_at(R, hold)
        if o is not None:
            ax.scatter(R.decode(a, o.coded[a]), R.decode(b, o.coded[b]), marker="*", s=160, color="#F2C14E",
                       edgecolor="black", linewidth=0.6, zorder=4)
            ax.set_title((", ".join(f"{_short(_f(R, k).label)} {v:g}" for k, v in hold.items()) or "all runs")
                         + f"   D max {o.D:.2f}", fontsize=8, loc="left")
        ax.set_xlabel(_f(R, a).label, fontsize=8)
        ax.set_ylabel(_f(R, b).label, fontsize=8)
        ax.tick_params(labelsize=7)
    fig.colorbar(cs, ax=list(axes), shrink=0.85, label="overall desirability D")
    goals = "; ".join(f"{_short(R.fits[g_.key].label)} {'up' if g_.direction == 'max' else 'down' if g_.direction == 'min' else 'to target'}"
                      for g_ in R.goals)
    fig.suptitle(f"Where all the goals are met: desirability D ({goals}); hatched = every goal at least half met; "
                 f"star = optimum", fontsize=8)
    return _save(fig, out_dir, "fig_rsm_desirability")


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


def make_all(models: dict, out_dir: Path, problems: list | None = None, map_keys=None) -> list[Path]:
    """models: name -> RsmResults; the FIRST is the primary model the maps are drawn from."""
    if not models:
        return []
    R = next(iter(models.values()))
    map_keys = map_keys or [k for k in list(HEADLINE) + ["lag1", "peak_bar"] if k in R.fits]
    jobs = [(f"contour {k}", lambda k=k: fig_contour(R, k, out_dir)) for k in map_keys]
    jobs += [(f"surface {k}", lambda k=k: fig_surface(R, k, out_dir)) for k in map_keys]
    jobs += [("profiler", lambda: fig_profiler(R, out_dir)), ("desirability", lambda: fig_desirability(R, out_dir)),
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
