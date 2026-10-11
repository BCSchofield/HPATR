"""rsm_responses.py -- load a detected response-surface design's runs and analyse every response.
No Qt.

    load()     every included run of an rsm_detect.Detected (fitted runs, validation runs, check
               points, controls), read exactly as the Taguchi analysis reads a run
               (stats.load_measured_run: the nine load_run responses with their self-consistency
               gates, plus run_metrics' five), so the two analyses never disagree about a number.
               Mixed sizer versions refuse, as in the Taguchi analysis.
    analyse()  for every response: the full model (the axis factors' quadratic + nuisance terms,
               or the largest estimable part of it), the simplified model (backward elimination with
               hierarchy), lack of fit, VIFs, R^2 / adjusted / predicted; BH q across every term test
               of every full model; drift (centres against time, block repeat pairs, residual trend);
               every run outside the fit predicted with its 95% prediction interval (pass / fail,
               extrapolation flagged); and the desirability optimum, continuous and at the levels that
               can actually be set.

AXIS AND NUISANCE. The surface is drawn over the AXIS factors (default: every factor). NUISANCE
factors (e.g. RPM in the 9x3 gas x feed trial) stay in the model as linear or linear + square terms,
held at a chosen value in the maps; their correlation with the axis terms is reported (VIF), so
partial confounding is visible rather than hidden.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import pipeline_spec as spec
from . import rsm_detect as rdet
from . import rsm_stats as rs
from . import stats

# the size goal is MEAN diameter, not D32 (Ben, 2026-10-11); one size goal only, as two would double its weight
DEFAULT_GOALS = (("atom", "max"), ("af_flow", "max"), ("cv_droplets", "min"), ("d_mean", "min"))
USABLE_R2_PRED = 0.5                  # below this a surface is not used to choose the best setting
EXTRAPOLATION_TOL = 0.05              # coded distance beyond the design region still counted as inside


@dataclass
class RunData:
    point: rdet.RunPoint
    values: dict                      # response key -> value
    ci: dict
    hours: float | None
    sizer_version: str | None
    metrics: dict = field(default_factory=dict, repr=False)


@dataclass
class Loaded:
    detected: rdet.Detected
    runs: list[RunData]
    skipped: list
    warnings: list
    refused: str | None = None
    thr: float = 0.30


def load(detected: rdet.Detected, runs_info: dict, thr: float | None = None,
         metrics_cache: Path | None = None, progress: Callable[[int, int, str], None] | None = None,
         do_bootstrap: bool = False) -> Loaded:
    """runs_info: run path -> run_discovery.RunInfo (design.Design.runs)."""
    s = spec.effective(spec.RunSettings(score_thresh=thr))
    ta = spec.rdc_module("taguchi_analysis")
    rng = np.random.default_rng(getattr(ta, "SEED", 0))
    pts = [p for p in detected.points if p.included and p.kind != rdet.MISSING]
    t0 = min((p.when for p in pts if p.when), default=None)
    skipped, warnings, out = [], [], []
    for i, p in enumerate(pts, 1):
        if progress:
            progress(i, len(pts), p.name)
        got = stats.load_measured_run(p.row.path, runs_info.get(p.row.path), s.score_thresh, rng, do_bootstrap,
                                      metrics_cache, skipped, warnings)
        if got is None:
            continue
        rec, values, ci, _context, metrics = got
        hours = (p.when - t0).total_seconds() / 3600 if p.when and t0 else None
        out.append(RunData(p, values, ci, hours, rec.get("sizer_version"), metrics))
    L = Loaded(detected, out, skipped, warnings, thr=s.score_thresh)
    versions = {r.sizer_version for r in out}
    if len(versions) > 1:
        L.refused = ("these runs were measured with different sizer versions (" +
                     ", ".join(sorted(str(v) for v in versions)) + "), so their numbers are not comparable; "
                     "re-measure them all with one version")
    elif sum(1 for r in out if r.point.in_fit) < 3:
        L.refused = "fewer than three measured runs in the fit"
    return L


# ---- the analysis -----------------------------------------------------------------------------------------

@dataclass
class Prediction:
    run: RunData
    observed: float | None
    mean: float
    pi: tuple
    inside: bool | None               # observed inside the 95% PI
    extrapolated: bool


@dataclass
class ResponseFit:
    key: str
    label: str
    direction: str
    full: rs.Fit | None
    reduced: rs.Fit | None
    vif: dict
    centre_trend: rs.TimeTrend | None
    residual_trend: rs.TimeTrend | None
    block_pairs: list                 # (block, run a, run b, difference, difference / (s_pe * sqrt 2))
    predictions: list[Prediction]
    note: str = ""


@dataclass
class RsmResults:
    loaded: Loaded
    axis: list[str]
    nuisance: dict
    hold: dict                        # nuisance factor -> coded value the maps use
    terms: list[str]                  # the full model's terms
    dropped_terms: list[str]          # terms of the requested model that are not estimable here
    fits: dict                        # response key -> ResponseFit
    goals: list
    constraints: list
    optimum: rs.Optimum | None
    optimum_discrete: rs.Optimum | None
    correlations: list                # (nuisance term, axis term, r) with |r| >= 0.3
    warnings: list
    discrete: dict | None = None      # factor -> the real levels that can be set (e.g. orifice inserts)

    def factor(self, key: str) -> rdet.FactorLevels:
        return next(f for f in self.loaded.detected.factors if f.key == key)

    def decode(self, key: str, coded: float) -> float:
        f = self.factor(key)
        lo, hi = float(f.low), float(f.high)
        return (lo + hi) / 2 + coded * (hi - lo) / 2


def default_goals(L: Loaded) -> list[rs.Goal]:
    out = []
    fit_runs = [r for r in L.runs if r.point.in_fit]
    for key, direction in DEFAULT_GOALS:
        v = [r.values.get(key) for r in fit_runs]
        v = [x for x in v if x is not None and math.isfinite(x)]
        if len(v) >= 3 and max(v) > min(v):
            out.append(rs.Goal(key, direction, float(min(v)), float(max(v))))
    return out


def resolve_goals(L: Loaded, goals) -> list[rs.Goal]:
    """Goals as the tab gives them: rs.Goal, or dicts {key, direction ("max" | "min" | "target"),
    low, high, target, importance} where a blank (None) ramp end is the range observed in the fitted
    runs. A goal on a response with no usable values is dropped."""
    out = []
    fit_runs = [r for r in L.runs if r.point.in_fit]
    for g in goals:
        if isinstance(g, rs.Goal):
            out.append(g)
            continue
        v = [r.values.get(g["key"]) for r in fit_runs]
        v = [x for x in v if x is not None and math.isfinite(x)]
        if len(v) < 3 or max(v) == min(v):
            continue
        lo = g.get("low") if g.get("low") is not None else float(min(v))
        hi = g.get("high") if g.get("high") is not None else float(max(v))
        out.append(rs.Goal(g["key"], g.get("direction", "max"), float(lo), float(hi), g.get("target"),
                           importance=float(g.get("importance") or 1.0)))
    return out


def _x(runs: list[RunData], keys: list[str], time_term: bool) -> dict:
    x = {k: np.array([r.point.real[k] for r in runs], float) for k in keys}
    if time_term:
        h = np.array([r.hours if r.hours is not None else np.nan for r in runs], float)
        x["time"] = h - np.nanmean(h)
    return x


def analyse(L: Loaded, axis: list[str] | None = None, nuisance: dict | None = None,
            hold: dict | None = None, time_term: bool = False, goals: list | None = None,
            constraints: list | None = None, discrete: dict | None = None, alpha: float = rs.ALPHA,
            responses: list | None = None) -> RsmResults:
    """axis: factor keys for the surface (default all); nuisance: key -> "linear" | "quadratic";
    hold: nuisance key -> REAL value the maps and the optimum use (default its centre);
    discrete: axis key -> real values that can be set (e.g. orifice inserts)."""
    det = L.detected
    nuisance = dict(nuisance or {})
    keys_all = [f.key for f in det.factors]
    axis = list(axis or [k for k in keys_all if k not in nuisance])
    warnings = list(L.warnings)
    unused = [k for k in keys_all if k not in axis and k not in nuisance]
    if unused:
        warnings.append("not in the model (pooled into the error): " + ", ".join(
            det.factors[keys_all.index(k)].label for k in unused))
    fit_runs = [r for r in L.runs if r.point.in_fit]
    model_keys = axis + list(nuisance)
    x = _x(fit_runs, model_keys, time_term)
    groups = [tuple(r.point.values[k] for k in model_keys) for r in fit_runs]
    requested = rs.quadratic_terms(axis, nuisance, time_term)
    # the largest estimable part of the requested model (squares, then interactions, then linear,
    # dropped only when they add nothing), as rsm_detect does for the full quadratic
    terms = list(requested)
    X = rs.model_matrix(x, terms)
    rank = int(np.linalg.matrix_rank(X))
    dropped = []
    if rank < len(terms):
        order = sorted([t for t in terms if t != "1"], key=lambda t: (-rs.term_order(t), t))
        for t in order:
            trial = [u for u in terms if u != t]
            if int(np.linalg.matrix_rank(rs.model_matrix(x, trial))) == int(np.linalg.matrix_rank(
                    rs.model_matrix(x, terms))):
                terms = trial
                dropped.append(t)
        warnings.append("not estimable on these runs, left out of the model: " + ", ".join(dropped))
    vifs = rs.vif(x, terms)
    corr = []
    for n_key in nuisance:
        for t in terms:
            if t == "1" or n_key in rs.term_parents(t) or t == "time":
                continue
            r = rs.correlation(x, n_key, t)
            if r is not None and abs(r) >= 0.3:
                corr.append((n_key, t, r))

    keep = tuple(t for t in terms if any(k in rs.term_parents(t) for k in nuisance) or t == "time")
    table = responses or stats.responses_table()
    hold_c = {k: det.factors[keys_all.index(k)].real_code((hold or {}).get(k, det.factors[keys_all.index(k)].centre))
              for k in nuisance}
    fits = {}
    for key, label, direction, _q in table:
        rows = [r for r in fit_runs if r.values.get(key) is not None and math.isfinite(r.values[key])]
        if len(rows) < len(terms) + 1:
            fits[key] = ResponseFit(key, label, direction, None, None, {}, None, None, [], [],
                                    note="too few runs with a value for this model")
            continue
        idx = [fit_runs.index(r) for r in rows]
        xs = {k: v[idx] for k, v in x.items()}
        gs = [groups[i] for i in idx]
        y = np.array([r.values[key] for r in rows], float)
        if np.ptp(y) == 0:
            fits[key] = ResponseFit(key, label, direction, None, None, {}, None, None, [], [],
                                    note="the same value in every run")
            continue
        full = rs.fit(y, xs, terms, gs)
        red = rs.backward(y, xs, terms, gs, alpha, keep=keep)
        fits[key] = ResponseFit(key, label, direction, full, red, vifs,
                                _centre_trend(fit_runs, key), _resid_trend(rows, red),
                                _block_pairs(det, L.runs, key, full), _predict(L, red, key, model_keys, nuisance,
                                                                               time_term, x))
    rs.bh_across({k: f.full for k, f in fits.items() if f.full is not None})
    goals = resolve_goals(L, goals) if goals is not None else default_goals(L)
    # a goal whose surface cannot predict a new run must not steer the best setting
    weak = [g for g in goals if g.key not in fits or fits[g.key].full is None or fits[g.key].full.r2_pred is None
            or fits[g.key].full.r2_pred < USABLE_R2_PRED]
    if weak:
        warnings.append("left out of the best-settings search (surface predicts new runs poorly, predicted R² below "
                        f"{USABLE_R2_PRED}): " + ", ".join(
                            f"{fits[g.key].label if g.key in fits else g.key}"
                            + (f" ({fits[g.key].full.r2_pred:.2f})" if g.key in fits and fits[g.key].full is not None
                               and fits[g.key].full.r2_pred is not None else "") for g in weak))
        goals = [g for g in goals if g not in weak]
    constraints = list(constraints or [])
    live = {k: f.reduced for k, f in fits.items() if f.reduced is not None
            and (k in {g.key for g in goals} or k in {c.key for c in constraints})}
    opt = opt_d = None
    if live and goals:
        ranges = {k: (-1.0, 1.0) for k in axis}
        fixed = dict(hold_c)
        if time_term:
            fixed["time"] = 0.0
        opt = rs.optimise(live, goals, ranges, fixed, constraints)
        if discrete:
            dcoded = {k: [det.factors[keys_all.index(k)].real_code(v) for v in vals] for k, vals in discrete.items()
                      if k in axis}
            opt_d = rs.optimise(live, goals, ranges, fixed, constraints, dcoded)
    return RsmResults(L, axis, nuisance, hold_c, terms, dropped, fits, goals, constraints, opt, opt_d, corr, warnings,
                      discrete=dict(discrete) if discrete else None)


def _centre_trend(fit_runs: list[RunData], key: str) -> rs.TimeTrend | None:
    c = [r for r in fit_runs if r.point.kind == rdet.CENTRE and r.values.get(key) is not None]
    return rs.time_trend([r.values[key] for r in c], [r.hours for r in c]) if len(c) >= 3 else None


def _resid_trend(rows: list[RunData], f: rs.Fit) -> rs.TimeTrend | None:
    return rs.time_trend(f.resid, [r.hours if r.hours is not None else np.nan for r in rows])


def _block_pairs(det: rdet.Detected, runs: list[RunData], key: str, f: rs.Fit) -> list:
    by_path = {r.point.row.path: r for r in runs}
    s_pe = math.sqrt(f.lof.ss_pe / f.lof.df_pe) if f.lof and f.lof.df_pe > 0 and f.lof.ss_pe > 0 else None
    out = []
    for block, a, b in det.blocks.drift_pairs:
        ra, rb = by_path.get(a.row.path), by_path.get(b.row.path)
        if ra is None or rb is None or ra is rb:
            continue
        va, vb = ra.values.get(key), rb.values.get(key)
        if va is None or vb is None:
            continue
        diff = vb - va
        out.append((block, ra, rb, diff, diff / (s_pe * math.sqrt(2)) if s_pe else None))
    return out


def _predict(L: Loaded, f: rs.Fit, key: str, model_keys: list[str], nuisance: dict, time_term: bool,
             x_fit: dict) -> list[Prediction]:
    """Every included run NOT in the fit (validation, check, control): predicted with its PI."""
    out = []
    t_mean = float(np.nanmean(x_fit["time"])) if time_term and "time" in x_fit else 0.0
    for r in L.runs:
        if r.point.in_fit or any(r.point.real.get(k) is None for k in model_keys):
            continue
        xr = {k: r.point.real[k] for k in model_keys}
        if time_term:
            xr["time"] = (r.hours - t_mean) if r.hours is not None else 0.0
        pr = f.predict(xr)
        obs = r.values.get(key)
        lo, hi = float(pr["pi"][0][0]), float(pr["pi"][1][0])
        ext = any(abs(r.point.coded.get(k) or 0) > 1 + EXTRAPOLATION_TOL for k in model_keys)
        inside = None if obs is None or not math.isfinite(lo) else bool(lo <= obs <= hi)
        out.append(Prediction(r, obs, float(pr["mean"][0]), (lo, hi), inside, ext))
    return out
