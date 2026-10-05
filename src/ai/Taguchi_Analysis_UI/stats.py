"""stats.py -- the generalised Taguchi statistics. No Qt in here.

taguchi_analysis.py is hard-wired to one design: nine runs, three factors at three
levels, no replicates, error from the L9's unassigned column. This module handles any
number of factors and levels, with or without replicates, balanced or not -- and
collapses to EXACTLY the published L9 numbers when given the published L9 (a regression
test asserts it, to 1e-9, against results_2026-10-01/taguchi_results.json).

ONE METHOD, NOT SEVERAL. Every factor's sum of squares is a Type II SS from least squares
on a sum-to-zero coded main-effects model:  SS_f = RSS(model without f) - RSS(full model).
  * balanced + orthogonal (an L9, with or without replicates): identical to the classic
    Taguchi formula  n_level * sum (level mean - grand mean)^2  (a test pins this);
  * unbalanced (a dropped run, uneven replication): the standard correct answer;
  * aliased (a combination never run): the factor LOSES degrees of freedom
    (rank(full) - rank(without f) < levels - 1). With none left it is not estimable and
    no number is reported -- producing one would be fabrication.

THE ERROR TERM, in order of preference:
  pure error     from replicates: sum over conditions of (y - condition mean)^2,
                 df = N - number of conditions. This is real run-to-run noise.
  residual       no replicates: whatever the main-effects model leaves unexplained,
                 df = N - rank. On a saturated L9 that is the unassigned column, so this is
                 what the old script did -- and it tests factors against INTERACTIONS, not noise.
  none           no degrees of freedom left: effects are shown, no F or p.
With replicates the leftover (lack of fit = residual - pure error) is tested against pure
error: a significant lack of fit means the factors interact, which an unreplicated L9 could
not even see.

S/N RATIOS. Per condition, from its replicates: smaller-is-better -10 log10(mean y^2),
larger-is-better -10 log10(mean 1/y^2). With one run per condition these reduce to the
old single-value form (-/+ 20 log10 y), so the published L9 S/N numbers are reproduced
too. S/N is undefined if a value is <= 0 (e.g. intermittency at its ideal of 0): reported
as undefined, never patched with an epsilon.

Reuses from taguchi_analysis.py (imported through pipeline_spec, never copied): load_run,
bootstrap, the RESPONSES table and its SN_SIGN directions, MIN_DISTINCT. Its
ss_factor / anova / f_sf_2 are NOT reused: they hard-code three runs per level, the three
factor names, and an F distribution with exactly 2 numerator degrees of freedom.
"""
from __future__ import annotations

import contextlib
import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import covariates
from . import design as dz
from . import pipeline_spec as spec

OUTLIER_Z = 3.0                 # standardised residual beyond which a replicate is flagged


# ---- the F distribution -------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Lentz's method)."""
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def f_sf(F: float, d1: float, d2: float) -> float:
    """P(F(d1, d2) > F). scipy when available; otherwise the pure-Python incomplete beta
    (agreement to 1e-10 is asserted in the tests). Exact for any degrees of freedom --
    unlike taguchi_analysis.f_sf_2, which is exact only for d1 = 2."""
    if not math.isfinite(F):
        return 0.0
    if F <= 0:
        return 1.0
    try:
        from scipy.stats import f as fdist
        return float(fdist.sf(F, d1, d2))
    except Exception:
        return _betainc(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * F))


def benjamini_hochberg(p: list[float]) -> list[float]:
    """BH-adjusted p-values (q), same order as the input."""
    n = len(p)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p[i])
    q = [0.0] * n
    running = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * n / rank)
        q[i] = running
    return q


# ---- least squares on a coded main-effects model ---------------------------------------------

def _coded(levels: list, factor_levels: list) -> np.ndarray:
    """Sum-to-zero (effect) coding of one factor: L-1 columns."""
    cols = []
    last = factor_levels[-1]
    for lv in factor_levels[:-1]:
        cols.append([1.0 if x == lv else (-1.0 if x == last else 0.0) for x in levels])
    return np.array(cols, dtype=float).T if cols else np.zeros((len(levels), 0))


def _rss_rank(y: np.ndarray, X: np.ndarray) -> tuple[float, int]:
    if X.shape[1] == 0:
        return float(((y - y.mean()) ** 2).sum()), 0
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return float(resid @ resid), int(np.linalg.matrix_rank(X))


def _design_matrix(X_levels: dict[str, list], keys: list[str], factor_levels: dict) -> np.ndarray:
    n = len(next(iter(X_levels.values()))) if X_levels else 0
    parts = [np.ones((n, 1))] + [_coded(X_levels[k], factor_levels[k]) for k in keys]
    return np.hstack(parts)


def estimability(levels: dict[str, list]) -> dict[str, tuple[int, int]]:
    """factor -> (estimable degrees of freedom, nominal L-1) for a main-effects model on
    these observations. The ONE definition of aliasing used everywhere (the design tab's
    findings and the ANOVA): a missing combination of levels only makes a design
    non-orthogonal; a factor is aliased only when the model loses rank -- e.g. a level that
    only ever occurs together with one level of another factor."""
    keys = list(levels)
    if not keys:
        return {}
    fl = {k: sorted(set(v), key=lambda x: (str(type(x)), x)) for k, v in levels.items()}
    full_rank = int(np.linalg.matrix_rank(_design_matrix(levels, keys, fl)))
    out = {}
    for k in keys:
        wo = int(np.linalg.matrix_rank(_design_matrix(levels, [o for o in keys if o != k], fl)))
        out[k] = (full_rank - wo, len(fl[k]) - 1)
    return out


@dataclass
class AnovaRow:
    source: str
    ss: float | None
    df: float
    ms: float | None = None
    F: float | None = None
    p: float | None = None
    contribution_pct: float | None = None
    pooled_contribution_pct: float | None = None
    note: str = ""


@dataclass
class Anova:
    rows: dict[str, AnovaRow]          # factor key -> row
    error: AnovaRow | None
    lack_of_fit: AnovaRow | None
    total_ss: float
    total_df: int
    error_source: str                  # "pure error" | "residual" | "none"
    n: int
    n_conditions: int


def anova(y: list[float], levels: dict[str, list], groups: list, factor_levels: dict | None = None
          ) -> Anova:
    """ANOVA of y on the factors in `levels` (factor key -> one level per observation).
    `groups` gives each observation's condition, for the pure-error term."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    keys = list(levels)
    factor_levels = factor_levels or {k: sorted(set(v), key=lambda x: (str(type(x)), x))
                                      for k, v in levels.items()}
    total_ss = float(((y - y.mean()) ** 2).sum())
    full = _design_matrix(levels, keys, factor_levels)
    rss_full, rank_full = _rss_rank(y, full)

    # pure error from replicates
    by_group: dict = {}
    for v, g in zip(y, groups):
        by_group.setdefault(g, []).append(v)
    ss_pe = float(sum(((np.array(v) - np.mean(v)) ** 2).sum() for v in by_group.values()))
    df_pe = n - len(by_group)
    df_res = n - rank_full

    if df_pe > 0:
        error_source, err_ss, err_df = "pure error", ss_pe, df_pe
    elif df_res > 0:
        error_source, err_ss, err_df = "residual", rss_full, df_res
    else:
        error_source, err_ss, err_df = "none", None, 0
    ms_err = err_ss / err_df if err_df > 0 else None

    rows: dict[str, AnovaRow] = {}
    for k in keys:
        others = [o for o in keys if o != k]
        rss_wo, rank_wo = _rss_rank(y, _design_matrix(levels, others, factor_levels))
        df_f = rank_full - rank_wo
        nominal = len(factor_levels[k]) - 1
        if df_f <= 0:
            rows[k] = AnovaRow(k, None, 0, note="not estimable: aliased with other factors "
                                                "(a combination of levels was never run)")
            continue
        ss_f = max(0.0, rss_wo - rss_full)
        row = AnovaRow(k, ss_f, df_f, ms=ss_f / df_f,
                       contribution_pct=100.0 * ss_f / total_ss if total_ss else None)
        if df_f < nominal:
            row.note = (f"partly aliased: {df_f} of {nominal} degrees of freedom estimable")
        if ms_err is not None:
            if ms_err > 0:
                row.F = row.ms / ms_err
                row.p = f_sf(row.F, df_f, err_df)
            else:
                row.F, row.p = math.inf, 0.0
            row.pooled_contribution_pct = (max(0.0, 100.0 * (ss_f - df_f * ms_err) / total_ss)
                                           if total_ss else None)
        rows[k] = row

    error = (AnovaRow("error", err_ss, err_df, ms=ms_err,
                      contribution_pct=100.0 * err_ss / total_ss if total_ss else None,
                      note=error_source) if err_df > 0 else None)
    lof = None
    if df_pe > 0:
        df_lof = df_res - df_pe
        ss_lof = max(0.0, rss_full - ss_pe)
        if df_lof > 0:
            lof = AnovaRow("lack of fit", ss_lof, df_lof, ms=ss_lof / df_lof)
            if ms_err and ms_err > 0:
                lof.F = lof.ms / ms_err
                lof.p = f_sf(lof.F, df_lof, df_pe)
    return Anova(rows, error, lof, total_ss, n - 1, error_source, n, len(by_group))


def classic_ss(y: list[float], levels: list) -> float:
    """The textbook Taguchi factor SS: sum over levels of n_level * (level mean - grand)^2.
    Only valid for balanced designs; kept to prove anova() equals it there."""
    y = np.asarray(y, dtype=float)
    grand = y.mean()
    ss = 0.0
    for lv in set(levels):
        sel = np.array([x == lv for x in levels])
        ss += sel.sum() * (y[sel].mean() - grand) ** 2
    return float(ss)


# ---- S/N --------------------------------------------------------------------------------------------

def sn_ratio(values: list[float], direction: str) -> float | None:
    """Taguchi S/N of one condition's replicates. None if undefined (any value <= 0)."""
    v = np.asarray(values, dtype=float)
    if v.size == 0 or not np.all(np.isfinite(v)) or np.any(v <= 0):
        return None
    if direction == "smaller":
        return float(-10.0 * math.log10(np.mean(v ** 2)))
    return float(-10.0 * math.log10(np.mean(1.0 / v ** 2)))


# ---- data in ------------------------------------------------------------------------------------------

class RunLoadError(RuntimeError):
    pass


@contextlib.contextmanager
def _tolerant_level_parsing(ta):
    """load_run() calls parse_levels(), which sys.exits on folder names that are not
    `<n>sccm_<n>rpm_<n>sps` (e.g. the real `..._nobh`, or `?sccm`). This app takes levels
    from the design instead, so during the call parse_levels is made harmless; the result's
    "levels" are overwritten by the caller."""
    original = getattr(ta, "parse_levels", None)
    ta.parse_levels = lambda name: {}
    try:
        yield
    finally:
        if original is not None:
            ta.parse_levels = original


def load_run_responses(run_dir: Path, thr: float, rng=None, do_bootstrap: bool = True) -> dict:
    """taguchi_analysis.load_run(), made safe to call from an app: its self-consistency
    gates still REFUSE (D32 / atomised re-derived from the CSVs must match the summaries),
    but as a RunLoadError instead of killing the process."""
    ta = spec.rdc_module("taguchi_analysis")
    noise = io.StringIO()
    try:
        with contextlib.redirect_stdout(noise), _tolerant_level_parsing(ta):
            rec = ta.load_run(Path(run_dir), f"{thr:.2f}")
            if do_bootstrap:
                ta.bootstrap(rec, rng if rng is not None else np.random.default_rng(ta.SEED))
    except SystemExit as exc:
        raise RunLoadError(str(exc)) from None
    except FileNotFoundError as exc:
        raise RunLoadError(f"results missing: {exc.filename}") from None
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise RunLoadError(f"{type(exc).__name__}: {exc}") from None
    return rec


def responses_table():
    """(key, label, direction, quantised) for every response, from taguchi_analysis."""
    return list(spec.rdc_module("taguchi_analysis").RESPONSES)


# ---- results ----------------------------------------------------------------------------------------------

@dataclass
class LevelEffect:
    level: Any
    n: int
    mean: float
    se: float | None = None              # from the ANOVA error: sqrt(MS_error / n)
    ci95: tuple | None = None            # measurement noise: frame bootstrap


@dataclass
class ResponseResult:
    key: str
    label: str
    direction: str
    n_used: int
    degenerate: bool = False
    n_distinct: int = 0
    quantisation_warning: bool = False
    anova: Anova | None = None
    effects: dict = field(default_factory=dict)          # factor key -> [LevelEffect]
    sn_defined: bool = False
    sn_by_condition: dict = field(default_factory=dict)  # condition label -> eta
    sn_effects: dict = field(default_factory=dict)       # factor key -> {level: mean eta}
    sn_anova: Anova | None = None
    sn_note: str = ""
    outliers: list = field(default_factory=list)


@dataclass
class RunRecord:
    name: str
    path: Path
    condition: str
    replicate: int | None
    levels: dict
    values: dict
    ci95: dict
    sizer_version: str | None
    frames: int
    rec: dict = field(default_factory=dict, repr=False)  # the full load_run record
    context: Any = None                                  # covariates.RunContext: GLR, densities...


@dataclass
class Results:
    factors: list                                  # design.Factor, analysed ones
    runs: list[RunRecord]
    responses: dict[str, ResponseResult]
    skipped: list[tuple[str, str]]                 # (run name, why)
    warnings: list[str]
    refused: str | None = None
    multiple: list = field(default_factory=list)   # (response, factor, p, q)
    trends: dict = field(default_factory=dict)     # (response, covariate) -> covariates.Trend
    n_boot: int = 0
    seed: int = 0
    thr: float = 0.30

    @property
    def n_conditions(self) -> int:
        return len({r.condition for r in self.runs})

    @property
    def error_source(self) -> str:
        live = [r.anova for r in self.responses.values() if r.anova]
        return live[0].error_source if live else "none"


def analyse_values(runs: list[RunRecord], factors: list, responses=None,
                   with_bootstrap: bool = True) -> dict[str, ResponseResult]:
    """The statistics on already-loaded runs (pure computation; the regression test feeds
    the published L9's values straight into this)."""
    ta_responses = responses or responses_table()
    keys = [f.key for f in factors]
    factor_levels = {k: sorted({r.levels[k] for r in runs}, key=lambda x: (str(type(x)), x))
                     for k in keys}
    out: dict[str, ResponseResult] = {}
    for key, label, direction, _quant in ta_responses:
        used = [r for r in runs if key in r.values and r.values[key] is not None
                and math.isfinite(r.values[key])]
        res = ResponseResult(key, label, direction, len(used))
        out[key] = res
        if len(used) < 2:
            res.degenerate = True
            continue
        y = [r.values[key] for r in used]
        res.n_distinct = len({round(v, 9) for v in y})
        min_distinct = getattr(spec.rdc_module("taguchi_analysis"), "MIN_DISTINCT", 4)
        if res.n_distinct < 2:
            res.degenerate = True
            continue
        res.quantisation_warning = res.n_distinct < min_distinct
        lv = {k: [r.levels[k] for r in used] for k in keys}
        groups = [r.condition for r in used]
        res.anova = anova(y, lv, groups, factor_levels)
        ms_err = res.anova.error.ms if res.anova.error else None

        # main effects: level means, SE from the ANOVA error, CI from the frame bootstrap
        for k in keys:
            effects = []
            for level in factor_levels[k]:
                sel = [r for r in used if r.levels[k] == level]
                if not sel:
                    continue
                vals = [r.values[key] for r in sel]
                eff = LevelEffect(level, len(sel), float(np.mean(vals)))
                if ms_err is not None:
                    eff.se = math.sqrt(ms_err / len(sel))
                boots = [r.rec.get(f"boot_{key}") for r in sel]
                if with_bootstrap and all(b is not None for b in boots):
                    stacked = np.mean(np.vstack(boots), axis=0)
                    eff.ci95 = tuple(float(x) for x in np.percentile(stacked, [2.5, 97.5]))
                effects.append(eff)
            res.effects[k] = effects

        # S/N per condition, then its level means and its own ANOVA (one value per condition)
        by_cond: dict[str, list] = {}
        for r in used:
            by_cond.setdefault(r.condition, []).append(r)
        etas = {c: sn_ratio([r.values[key] for r in rs], direction) for c, rs in by_cond.items()}
        if any(v is None for v in etas.values()):
            res.sn_note = ("not defined: the response reaches 0 or below (for some responses 0 "
                           "is the ideal value), and a log cannot be taken there")
        else:
            res.sn_defined = True
            res.sn_by_condition = etas
            cond_levels = {c: rs[0].levels for c, rs in by_cond.items()}
            for k in keys:
                res.sn_effects[k] = {}
                for level in factor_levels[k]:
                    vals = [etas[c] for c in etas if cond_levels[c][k] == level]
                    if vals:
                        res.sn_effects[k][level] = float(np.mean(vals))
            conds = list(etas)
            res.sn_anova = anova([etas[c] for c in conds],
                                 {k: [cond_levels[c][k] for c in conds] for k in keys},
                                 conds, factor_levels)

        # replicates far from their own condition's mean
        if res.anova.error_source == "pure error" and ms_err and ms_err > 0:
            for c, rs in by_cond.items():
                if len(rs) < 3:
                    continue
                mean = np.mean([r.values[key] for r in rs])
                scale = math.sqrt(ms_err * (1 - 1 / len(rs)))
                for r in rs:
                    z = (r.values[key] - mean) / scale
                    if abs(z) > OUTLIER_Z:
                        res.outliers.append({"run": r.name, "condition": c, "value": r.values[key],
                                             "condition_mean": float(mean), "z": float(z)})
    return out


def multiple_comparisons(responses: dict[str, ResponseResult], factors) -> list[tuple]:
    tests = [(rk, f.key, res.anova.rows[f.key].p) for rk, res in responses.items()
             if res.anova for f in factors
             if f.key in res.anova.rows and res.anova.rows[f.key].p is not None]
    q = benjamini_hochberg([t[2] for t in tests])
    return [(rk, fk, p, qq) for (rk, fk, p), qq in zip(tests, q)]


def analyse(design: dz.Design, thr: float | None = None,
            progress: Callable[[int, int, str], None] | None = None,
            do_bootstrap: bool = True) -> Results:
    """Load every analysable run in the design and run the statistics."""
    s = spec.effective(spec.RunSettings(score_thresh=thr))
    ta = spec.rdc_module("taguchi_analysis")
    a = dz.assign(design)
    factors = dz.analysis_factors(design, a)
    warnings: list[str] = []
    skipped: list[tuple[str, str]] = []
    counts = a.counts()
    if counts.get(dz.CONFLICT):
        warnings.append(f"{counts[dz.CONFLICT]} run(s) have Notes that disagree with their factor "
                        f"levels; the analysis groups them by their levels.")
    for row in design.rows:
        st = a.of(row).status
        if st in (dz.UNASSIGNED, dz.DROPPED):
            skipped.append((row.name, "left out" if st == dz.DROPPED else "no complete factor levels"))

    rng = np.random.default_rng(getattr(ta, "SEED", 0))
    runs: list[RunRecord] = []
    todo = [(c, r) for c in a.conditions for r in c.rows]
    for i, (cond, row) in enumerate(todo, 1):
        if progress:
            progress(i, len(todo), row.name)
        info = design.runs.get(row.path)
        if info is not None and not info.analysis.measured:
            skipped.append((row.name, "not measured yet: run the batch on it first"))
            continue
        try:
            rec = load_run_responses(row.path, s.score_thresh, rng, do_bootstrap)
        except RunLoadError as exc:
            skipped.append((row.name, f"cannot be read: {exc}"))
            continue
        levels = {f.key: row.value(f.key) for f in factors}
        rec["levels"] = levels
        values = {k: rec.get(k) for k in getattr(ta, "RESP_KEYS", [])}
        ci = {k: tuple(rec[f"{k}_ci"]) for k in values if f"{k}_ci" in rec}
        runs.append(RunRecord(row.name, row.path, cond.label, a.of(row).replicate, levels, values,
                              ci, rec.get("sizer_version"), len(rec.get("frames", [])), rec,
                              covariates.run_context(info) if info is not None else None))

    results = Results(factors, runs, {}, skipped, warnings,
                      n_boot=getattr(ta, "N_BOOT", 0) if do_bootstrap else 0,
                      seed=getattr(ta, "SEED", 0), thr=s.score_thresh)
    versions = {r.sizer_version for r in runs}
    if len(versions) > 1:
        groups = {}
        for r in runs:
            groups.setdefault(r.sizer_version or "pre-2.0.0", []).append(r.name[:6])
        results.refused = ("these runs were measured with different sizer versions, so their numbers "
                           "are not comparable: " + "; ".join(f"{v}: {', '.join(n)}" for v, n in
                                                              sorted(groups.items())) +
                           ". Re-measure them all with one version (Batch tab, 'Re-measure only').")
        return results
    if len(runs) < 2 or not factors:
        results.refused = ("nothing to analyse: fewer than two measured runs, or no factor with two "
                           "or more levels")
        return results
    results.responses = analyse_values(runs, factors, with_bootstrap=do_bootstrap)
    results.multiple = multiple_comparisons(results.responses, factors)
    results.trends = covariates.trends(runs, responses_table())
    no_glr = [r for r in runs if not (r.context and r.context.glr is not None)]
    if no_glr:
        why = no_glr[0].context.note if no_glr[0].context else "no workbook"
        if len(no_glr) == len(runs):
            results.warnings.append(f"no run has a GLR ({why}), so there is no GLR analysis.")
        else:
            results.warnings.append(f"{len(no_glr)} run(s) have no GLR ({why}), so the GLR trends use "
                                    f"the other {len(runs) - len(no_glr)} run(s).")
    return results
