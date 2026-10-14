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

RUNS THAT DID NOT GET THEIR SET GAS (operating.py, 2026-10-13). Once the silicone reaches a small orifice
the pressure can hit the supply ceiling and the gas fall far below its set point (the CCD day's 0.5 mm
block: 33-5,554 sccm against 7,000-11,000). The design's gas factor does not describe such a run, so by
default (limited="exclude") it is kept out of the fit (point.excluded) and reported in its own section, with
a main-effects test of what controlled it there; "delivered" fits it at the gas it got instead; "set" keeps
the old behaviour.

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

import dataclasses

import numpy as np

from . import covariates
from . import operating
from . import pipeline_spec as spec
from . import rsm_detect as rdet
from . import rsm_stats as rs
from . import stats

# (key, direction, importance). The objective is THROUGHPUT (Ben, 2026-10-14): the spray is collected and
# size-filtered, so the goal is as many droplets in the size band per second as possible (mass balance,
# `rate_band`, Settings band default 20-60 um), with atomised fraction as a lighter second goal. A run
# without the rate (measured before liquid stage 2.3.0, or no syringe flow) leaves atomised fraction alone.
DEFAULT_GOALS = (("rate_band", "max", 3.0), ("atom", "max", 1.0))
USABLE_R2_PRED = 0.5                  # below this a surface is not used to choose the best setting
LIMITED_MODES = ("exclude", "delivered", "set")   # what to do with runs that did not get their set gas
LIMITED_RESPONSES = ("delivered", "atom", "per_frame", "af_flow", "d_mean")   # the pressure-limited section
N_BEST_OBSERVED = 5
EXTRAPOLATION_TOL = 0.05              # coded distance beyond the design region still counted as inside


@dataclass
class RunData:
    point: rdet.RunPoint
    values: dict                      # response key -> value
    ci: dict
    hours: float | None
    sizer_version: str | None
    metrics: dict = field(default_factory=dict, repr=False)
    op: object = None                 # operating.OperatingPoint: gas delivered, P0, regime


@dataclass
class Loaded:
    detected: rdet.Detected
    runs: list[RunData]
    skipped: list
    warnings: list
    refused: str | None = None
    thr: float = 0.30
    opts: stats.AnalysisOptions = field(default_factory=stats.AnalysisOptions)


def load(detected: rdet.Detected, runs_info: dict, thr: float | None = None,
         metrics_cache: Path | None = None, progress: Callable[[int, int, str], None] | None = None,
         do_bootstrap: bool = False, opts: stats.AnalysisOptions | None = None) -> Loaded:
    """runs_info: run path -> run_discovery.RunInfo (design.Design.runs)."""
    s = spec.effective(spec.RunSettings(score_thresh=thr))
    ta = spec.rdc_module("taguchi_analysis")
    rng = np.random.default_rng(getattr(ta, "SEED", 0))
    pts = [p for p in detected.points if p.included and p.kind != rdet.MISSING]
    t0 = min((p.when for p in pts if p.when), default=None)
    skipped, warnings, out, recs, contexts = [], [], [], [], []
    for i, p in enumerate(pts, 1):
        if progress:
            progress(i, len(pts), p.name)
        got = stats.load_measured_run(p.row.path, runs_info.get(p.row.path), s.score_thresh, rng, do_bootstrap,
                                      metrics_cache, skipped, warnings, opts)
        if got is None:
            continue
        rec, values, ci, context, metrics = got
        recs.append(rec)
        contexts.append(context)
        hours = (p.when - t0).total_seconds() / 3600 if p.when and t0 else None
        op = rec.get("operating")
        if op is not None and p.values.get("sccm") is not None:
            op = operating.reclassify(op, p.values["sccm"])        # the level in force (it may be corrected)
        out.append(RunData(p, values, ci, hours, rec.get("sizer_version"), metrics, op))
    fw = stats.flow_warning([r.values for r in out])
    if fw:
        warnings.append(fw)
    lw = covariates.orifice_length_warning(contexts)      # a hidden factor: not in the model
    if lw:
        warnings.append(lw)
    L = Loaded(detected, out, skipped, warnings, thr=s.score_thresh, opts=opts or stats.AnalysisOptions())
    versions = {r.sizer_version for r in out}
    liq = stats.mixed_liquid_versions(recs)
    if liq:
        L.refused = liq
    elif len(versions) > 1:
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

    @property
    def used(self) -> rs.Fit | None:
        """The fit that draws the maps and steers the best setting: the simplified model (the full one only
        when there is no simplified one)."""
        return self.reduced if self.reduced is not None else self.full

    @property
    def r2_pred_used(self) -> float | None:
        """Predicted R² of `used`. Judging a surface by the FULL quadratic's instead fails when the design is
        nearly saturated: on the CCD day with the pressure-limited block out (21 runs, 14 terms) every
        leave-one-out prediction is a high-leverage extrapolation, so the full model read -0.28 for
        atomised fraction while the simplified one that is mapped and optimised read 0.89. (The simplified
        model's terms were chosen on the same runs, so its figure is somewhat optimistic.)"""
        f = self.used
        return None if f is None else f.r2_pred


def free_factors(live: dict, axis: list) -> list:
    """Axis factors that appear in no term of any surface steering the best setting (goals and
    constraints): no setting of them changes D. On the CCD day the simplified atomised-fraction surface
    was gas + orifice only, so rpm and silicone feed were free."""
    used = {p for f in live.values() for t in f.terms for p in rs.term_parents(t)}
    return [k for k in axis if k not in used]


def weak_goals(goals: list, fits: dict) -> list:
    """Goals whose surface cannot predict a new run (predicted R² of the model in use below USABLE_R2_PRED,
    or no fit): they must not steer the best setting."""
    return [g for g in goals if g.key not in fits or fits[g.key].r2_pred_used is None
            or fits[g.key].r2_pred_used < USABLE_R2_PRED]


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
    limited_mode: str = "exclude"     # LIMITED_MODES
    limited: list = field(default_factory=list)          # RunData that did not get their set gas
    limited_effects: dict = field(default_factory=dict)  # response key -> rs.Fit, main effects among them
    goal_status: list = field(default_factory=list)      # GoalStatus for every goal that was set
    best_observed: list = field(default_factory=list)    # (D, RunData, {key: d}) best runs as measured
    surface_best: dict = field(default_factory=dict)     # goal key -> its '1 at' taken from the surface (blank)
    free: list = field(default_factory=list)             # axis factors no steering surface depends on:
                                                         # held at the centre in the best setting

    def factor(self, key: str) -> rdet.FactorLevels:
        return next(f for f in self.loaded.detected.factors if f.key == key)

    def decode(self, key: str, coded: float) -> float:
        return self.factor(key).decode(coded)


@dataclass
class GoalStatus:
    key: str
    label: str
    aim: str                          # "max" | "min" | "target"
    importance: float
    used: bool
    why: str                          # "used" or why it was left out of the best-settings search


def _limit_runs(L: Loaded, mode: str) -> tuple[Loaded, list[RunData]]:
    """The runs the analysis uses, and the ones that did not get their set gas. mode "exclude": those keep
    their kind but are kept out of the fit (point.excluded) and out of the predictions; "delivered": their
    gas factor is moved to the gas they got; "set": as they were."""
    if mode not in LIMITED_MODES:
        raise ValueError(f"limited must be one of {LIMITED_MODES}")
    det = L.detected
    gas = next((f for f in det.factors if f.key == "sccm"), None)
    nd = [r for r in L.runs if gas is not None and r.op is not None and r.op.not_delivered]
    if mode == "set" or not nd:
        return L, nd
    runs = []
    for r in L.runs:
        if r not in nd:
            runs.append(r)
            continue
        p = r.point
        if mode == "exclude":
            p = dataclasses.replace(p, excluded=f"{r.op.regime}: {r.op.text()}")
        else:
            got = r.op.delivered_sccm
            p = dataclasses.replace(p, values={**p.values, "sccm": round(got)},
                                    real={**p.real, "sccm": gas.real_code(got)},
                                    coded={**p.coded, "sccm": gas.design_code(got)},
                                    flags=list(p.flags) + [f"fitted at the gas delivered, {got:,.0f} sccm"])
        runs.append(dataclasses.replace(r, point=p))
    return dataclasses.replace(L, runs=runs), nd


def _recode(L: Loaded, log_keys, refit: bool) -> tuple[Loaded, list[str]]:
    """The factors the fit codes against, and every point recoded to them. `log_keys`: factors coded on
    ln(value) (orifice by default: its inserts are a geometric series, and on the CCD day a log scale
    predicted the 0.8 mm check's peak pressure best). `refit`: when runs were left out of the fit, each
    factor's levels become the levels the FITTED runs span, so the surface, its maps and the optimum stay
    inside what was fitted (with the 0.5 mm block out, orifice spans 1.2-1.8, not 0.5-1.8). Returns the
    recoded Loaded and notes for the report."""
    det = L.detected
    log_keys = set(log_keys or ())
    notes = []
    fit_pts = [r.point for r in L.runs if r.point.in_fit]
    new = []
    for f in det.factors:
        g = f
        if refit and f.numeric:
            lv = sorted({p.values.get(f.key) for p in fit_pts if p.values.get(f.key) is not None})
            if len(lv) >= 2 and (lv[0] != f.low or lv[-1] != f.high):
                centre = lv[len(lv) // 2] if len(lv) % 2 else (lv[0] + lv[-1]) / 2
                g = dataclasses.replace(g, levels=lv, centre=centre)
                notes.append(f"{f.label}: the fitted runs span {lv[0]:g} to {lv[-1]:g} (the design ran "
                             f"{f.low:g} to {f.high:g}); the surface, maps and best setting stay inside the fitted span")
        if f.key in log_keys:
            if f.numeric and g.levels and all(float(v) > 0 for v in g.levels):
                g = dataclasses.replace(g, log=True)
            else:
                notes.append(f"{f.label}: not fitted on a log scale (a level is zero or negative)")
        new.append(g)
    if all(a is b for a, b in zip(new, det.factors)):
        return L, notes
    det2 = dataclasses.replace(det, factors=new)
    runs = []
    for r in L.runs:
        p = r.point
        real = {g.key: g.real_code(p.values.get(g.key)) for g in new}
        coded = {g.key: g.design_code(p.values.get(g.key)) for g in new}
        runs.append(dataclasses.replace(r, point=dataclasses.replace(p, real=real, coded=coded)))
    return dataclasses.replace(L, detected=det2, runs=runs), notes


def _limited_effects(nd: list[RunData], det) -> dict:
    """Among the runs that did not get their set gas: a main-effects fit (linear in each design factor that
    varies among them) of the gas they got and of the spray responses. Answers "what controlled the gas
    once the rig was pressure-limited", and whether the set point still mattered."""
    keys = [f.key for f in det.factors if len({r.point.values.get(f.key) for r in nd}) > 1
            and all(r.point.real.get(f.key) is not None for r in nd)]
    out = {}
    if not keys:
        return out
    terms = ["1"] + keys
    for key in LIMITED_RESPONSES:
        rows = [r for r in nd if (r.op.delivered_sccm if key == "delivered" else r.values.get(key)) is not None]
        if len(rows) < len(terms) + 2:
            continue
        y = np.array([r.op.delivered_sccm if key == "delivered" else r.values[key] for r in rows], float)
        if np.ptp(y) == 0:
            continue
        x = {k: np.array([r.point.real[k] for r in rows], float) for k in keys}
        out[key] = rs.fit(y, x, terms, [tuple(r.point.values[k] for k in keys) for r in rows])
    return out


def _best_observed(runs: list[RunData], goals: list[rs.Goal]) -> list[tuple]:
    """The measured runs ranked by the combined score of the goals, on their OBSERVED values (a goal with
    no value for a run scores 0 there). Every run counts, in the fit or not: a reproducible
    pressure-limited run can be the best recipe of the day even though the surface leaves it out."""
    if not goals:
        return []
    out = []
    for r in runs:
        each = {g.key: (float(g.d(r.values[g.key])) if r.values.get(g.key) is not None
                        and math.isfinite(r.values[g.key]) else 0.0) for g in goals}
        w = sum(g.importance for g in goals)
        D = math.exp(sum(g.importance * math.log(max(each[g.key], 1e-300)) for g in goals) / w) \
            if all(v > 0 for v in each.values()) else 0.0
        out.append((D, r, each))
    out.sort(key=lambda t: -t[0])
    return out[:N_BEST_OBSERVED]


def default_goals(L: Loaded) -> list[rs.Goal]:
    out = []
    fit_runs = [r for r in L.runs if r.point.in_fit]
    for key, direction, importance in DEFAULT_GOALS:
        v = [r.values.get(key) for r in fit_runs]
        v = [x for x in v if x is not None and math.isfinite(x)]
        if len(v) >= 3 and max(v) > min(v):
            out.append(rs.Goal(key, direction, float(min(v)), float(max(v)), importance=importance))
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


SURFACE_GRID = 11          # points per factor for the surface's best inside the tested region


def _surface_extreme(f: rs.Fit, axis: list[str], fixed: dict, direction: str) -> float:
    """The highest (max) or lowest (min) value the fitted surface reaches inside the tested region
    (every axis factor over coded -1..+1; nuisance factors and time held as in `fixed`)."""
    pts = np.linspace(-1.0, 1.0, SURFACE_GRID)
    mesh = np.meshgrid(*[pts] * len(axis), indexing="ij")
    x = {k: m.ravel() for k, m in zip(axis, mesh)}
    n = mesh[0].size
    x.update({k: np.full(n, v) for k, v in fixed.items()})
    y = np.asarray(f.predict(x)["mean"], float)
    return float(np.nanmax(y) if direction == "max" else np.nanmin(y))


def reach_surface(goals: list, requested: list, live: dict, axis: list[str], fixed: dict) -> tuple[list, dict]:
    """A goal whose best end ('1 at') was left blank scores 1 at the best its fitted surface reaches in the
    tested region, not at the best run seen (Ben, 2026-10-13). With the best RUN as the end, every setting
    the surface predicts beyond that run scores a flat 1, the desirability cannot tell them apart and the
    optimiser stops at the first one it tries: the CCD day gave '10,740 sccm' for atomised fraction and
    'feed 3,000' when maximising the droplet production rate, which rises with feed. Returns (goals,
    {key: the end used}) for the report."""
    blank = set()
    for g in requested:
        if isinstance(g, dict):
            d = g.get("direction", "max")
            if (d == "max" and g.get("high") is None) or (d == "min" and g.get("low") is None):
                blank.add(g["key"])
    out, used = [], {}
    for g in goals:
        f = live.get(g.key)
        if g.key in blank and f is not None and g.direction in ("max", "min"):
            ext = _surface_extreme(f, axis, fixed, g.direction)
            if g.direction == "max" and math.isfinite(ext) and ext > g.high:
                g = dataclasses.replace(g, high=ext)
                used[g.key] = ext
            elif g.direction == "min" and math.isfinite(ext) and ext < g.low:
                g = dataclasses.replace(g, low=ext)
                used[g.key] = ext
        out.append(g)
    return out, used


def _x(runs: list[RunData], keys: list[str], time_term: bool) -> dict:
    x = {k: np.array([r.point.real[k] for r in runs], float) for k in keys}
    if time_term:
        h = np.array([r.hours if r.hours is not None else np.nan for r in runs], float)
        x["time"] = h - np.nanmean(h)
    return x


def analyse(L: Loaded, axis: list[str] | None = None, nuisance: dict | None = None,
            hold: dict | None = None, time_term: bool = False, goals: list | None = None,
            constraints: list | None = None, discrete: dict | None = None, alpha: float = rs.ALPHA,
            responses: list | None = None, limited: str = "exclude", log: list | None = None) -> RsmResults:
    """axis: factor keys for the surface (default all); nuisance: key -> "linear" | "quadratic";
    hold: nuisance key -> REAL value the maps and the optimum use (default its centre);
    discrete: axis key -> real values that can be set (e.g. orifice inserts);
    limited: what to do with runs that did not get their set gas (LIMITED_MODES);
    log: factor keys fitted on a log scale (None = orifice, if there is one; [] = none)."""
    L, not_delivered = _limit_runs(L, limited)
    if log is None:
        log = [f.key for f in L.detected.factors if f.key == "orifice"]
    L, recode_notes = _recode(L, log, refit=bool(not_delivered) and limited == "exclude")
    det = L.detected
    nuisance = dict(nuisance or {})
    keys_all = [f.key for f in det.factors]
    axis = list(axis or [k for k in keys_all if k not in nuisance])
    warnings = list(L.warnings) + recode_notes
    if not_delivered:
        how = {"exclude": "kept out of the fit (their own section in the report)",
               "delivered": "fitted at the gas they got, not their set point",
               "set": "fitted at their SET gas, which they did not get: the gas factor is wrong for them"}[limited]
        warnings.append(f"{len(not_delivered)} run(s) did not get their set gas ("
                        + ", ".join(sorted({r.op.regime for r in not_delivered})) + f"), {how}: "
                        + ", ".join(r.point.name for r in not_delivered))
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
    requested = list(goals) if goals is not None else [{"key": k, "direction": d, "importance": w}
                                                       for k, d, w in DEFAULT_GOALS]
    goals = resolve_goals(L, requested)
    goals_all = list(goals)
    # a goal whose surface cannot predict a new run must not steer the best setting
    weak = weak_goals(goals, fits)
    status = []
    labels = {k: lab for k, lab, _d, _q in table}
    resolved = {g.key: g for g in goals}
    for g in requested:
        key = g.key if isinstance(g, rs.Goal) else g["key"]
        aim = g.direction if isinstance(g, rs.Goal) else g.get("direction", "max")
        imp = g.importance if isinstance(g, rs.Goal) else float(g.get("importance") or 1.0)
        if key not in resolved:
            why = ("no values to score: atomised liquid flow could not be computed" if key == "af_flow" else
                   "no values to score (fewer than 3 fitted runs with a value, or the same value in every run)")
        elif resolved[key] in weak:
            r2p = fits[key].r2_pred_used if key in fits else None
            why = ("no usable surface: predicted R² " + (f"{r2p:.2f}" if r2p is not None else "not available")
                   + f" (simplified model), below {USABLE_R2_PRED}")
        else:
            why = "used"
        status.append(GoalStatus(key, labels.get(key, key), aim, imp, why == "used", why))
    if weak:
        warnings.append("left out of the best-settings search (surface predicts new runs poorly, predicted R² of "
                        f"the simplified model below {USABLE_R2_PRED}): " + ", ".join(
                            f"{fits[g.key].label if g.key in fits else g.key}"
                            + (f" ({fits[g.key].r2_pred_used:.2f})" if g.key in fits
                               and fits[g.key].r2_pred_used is not None else "") for g in weak))
        goals = [g for g in goals if g not in weak]
    constraints = list(constraints or [])
    live = {k: f.reduced for k, f in fits.items() if f.reduced is not None
            and (k in {g.key for g in goals} or k in {c.key for c in constraints})}
    held = dict(hold_c) | ({"time": 0.0} if time_term else {})
    goals, surface_best = reach_surface(goals, requested, live, axis, held)
    goals_all = reach_surface(goals_all, requested, live, axis, held)[0]
    opt = opt_d = None
    free = free_factors(live, axis)
    if live and goals and len(free) == len(axis):
        warnings.append("no best setting: none of the surfaces it would optimise depends on any factor")
    if live and goals and len(free) < len(axis):
        # a factor in none of the steering surfaces cannot change D: searching it returns the grid's first
        # value (an "edge" that means nothing), so it is held at the design centre and reported as free
        ranges = {k: (-1.0, 1.0) for k in axis if k not in free}
        fixed = dict(hold_c) | {k: 0.0 for k in free}
        if time_term:
            fixed["time"] = 0.0
        opt = rs.optimise(live, goals, ranges, fixed, constraints)
        if opt is not None:
            opt.coded.update({k: 0.0 for k in free})
        if discrete:
            dcoded, outside = {}, []
            for k, vals in discrete.items():
                if k not in axis:
                    continue
                fk = det.factors[keys_all.index(k)]
                ok = [(v, fk.real_code(v)) for v in vals if fk.real_code(v) is not None]
                inside = [c for v, c in ok if abs(c) <= 1 + EXTRAPOLATION_TOL]
                outside += [f"{fk.label} {v:g}" for v, c in ok if abs(c) > 1 + EXTRAPOLATION_TOL]
                dcoded[k] = inside or [c for _v, c in ok]
            if outside:
                warnings.append("settable levels outside the fitted range, not offered as the best setting: "
                                + ", ".join(outside))
            fixed_d = dict(fixed)
            for k in free:                     # a free fixed-size factor: the settable size nearest the centre
                if k in dcoded:
                    fixed_d[k] = min(dcoded.pop(k), key=abs)
            opt_d = rs.optimise(live, goals, ranges, fixed_d, constraints, dcoded)
            if opt_d is not None:
                opt_d.coded.update({k: fixed_d[k] for k in free})
    return RsmResults(L, axis, nuisance, hold_c, terms, dropped, fits, goals, constraints, opt, opt_d, corr, warnings,
                      discrete=dict(discrete) if discrete else None, limited_mode=limited,
                      limited=[r for r in L.runs if r.op is not None and r.op.not_delivered],
                      limited_effects=_limited_effects(not_delivered, det) if not_delivered else {},
                      goal_status=status, best_observed=_best_observed(L.runs, goals_all),
                      free=free if opt is not None else [], surface_best=surface_best)


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
        if ra is None or rb is None or ra is rb or ra.point.excluded or rb.point.excluded:
            continue                        # a repeat that did not get its gas measures that, not drift
        va, vb = ra.values.get(key), rb.values.get(key)
        if va is None or vb is None:
            continue
        diff = vb - va
        out.append((block, ra, rb, diff, diff / (s_pe * math.sqrt(2)) if s_pe else None))
    return out


def _predict(L: Loaded, f: rs.Fit, key: str, model_keys: list[str], nuisance: dict, time_term: bool,
             x_fit: dict) -> list[Prediction]:
    """Every included run NOT in the fit (validation, check, control): predicted with its PI. Runs kept out
    because they did not get their set gas are not predicted: the model cannot speak for them."""
    out = []
    t_mean = float(np.nanmean(x_fit["time"])) if time_term and "time" in x_fit else 0.0
    for r in L.runs:
        if r.point.in_fit or r.point.excluded or any(r.point.real.get(k) is None for k in model_keys):
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
