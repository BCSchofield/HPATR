"""rsm_stats.py -- the response-surface statistics. No Qt, no I/O, numpy only (no statsmodels).

MODEL. A quadratic in coded units (real coding: (v - mid-range) / half-range, so an uneven middle
level is where it really is). The AXIS factors get the full quadratic: linear, every pairwise
interaction, squares. NUISANCE factors are kept in the model but only as linear (or linear +
square) terms, without interactions: they soak up their own effect so it does not bias the axis
terms, and the maps hold them at a chosen value. A time term (hours, centred) can be added for drift.

FIT. Ordinary least squares. Coefficients with SE, t and two-sided p; R^2, adjusted R^2 and
predicted R^2 (from PRESS, the leave-one-out residuals e / (1 - h)); 95% confidence intervals for
the mean and 95% PREDICTION intervals for a new run (the one to check a validation run against).

LACK OF FIT. Pure error from every repeated setting of the model's factors; lack of fit = residual
- pure error, F-tested against pure error. Significant lack of fit means the surface does not
describe the data: narrow the region or add points.

SIMPLIFICATION. Backward elimination with hierarchy, as the CCD plan says: drop non-significant
terms one at a time, highest order first; a linear term stays while a square or interaction
containing it stays. The p-values of a simplified model are optimistic (it was chosen by them); the
full model's are the honest ones, and their Benjamini-Hochberg q across every response is reported.

DESIRABILITY (Derringer-Suich). Per response a ramp: maximise (0 at or below `low`, 1 at or above
`high`), minimise (mirror), or target (1 at the target, 0 at the ends). Overall D = weighted
geometric mean, 0 where any hard constraint fails (a predicted peak pressure over the limit). The
optimum is searched on a grid over the axis factors (continuous, or restricted to the levels that
can actually be set, e.g. the inserts that exist), then refined locally on continuous factors.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from .stats import benjamini_hochberg, f_sf, t_quantile

ALPHA = 0.05
GRID_BUDGET = 200_000                 # grid points for the optimum search


# ---- terms -------------------------------------------------------------------------------------------

def term_parents(term: str) -> tuple:
    if term == "1":
        return ()
    if term.endswith("^2"):
        k = term[:-2]
        return (k, k)
    return tuple(term.split("*"))


def term_order(term: str) -> int:
    return len(term_parents(term))


def quadratic_terms(axis: list[str], nuisance: dict | None = None, time_term: bool = False) -> list[str]:
    """Intercept, axis linear, axis interactions, axis squares, then nuisance terms and time."""
    nuisance = nuisance or {}
    terms = ["1"] + list(axis) + [f"{a}*{b}" for a, b in itertools.combinations(axis, 2)] + [f"{a}^2" for a in axis]
    for k, how in nuisance.items():
        terms.append(k)
        if how == "quadratic":
            terms.append(f"{k}^2")
    if time_term:
        terms.append("time")
    return terms


def model_matrix(x: dict, terms: list[str]) -> np.ndarray:
    """x: name -> array of coded values (same length)."""
    n = len(next(iter(x.values()))) if x else 1
    cols = []
    for t in terms:
        p = term_parents(t)
        if not p:
            cols.append(np.ones(n))
        elif len(p) == 1:
            cols.append(np.asarray(x[p[0]], float))
        else:
            cols.append(np.asarray(x[p[0]], float) * np.asarray(x[p[1]], float))
    return np.column_stack(cols)


# ---- the fit -----------------------------------------------------------------------------------------------

@dataclass
class LackOfFit:
    ss_lof: float
    df_lof: int
    ss_pe: float
    df_pe: int
    F: float | None
    p: float | None


@dataclass
class Fit:
    terms: list[str]
    beta: np.ndarray
    se: np.ndarray
    t: np.ndarray
    p: np.ndarray
    n: int
    df_resid: int
    s: float | None                  # residual standard deviation
    r2: float | None
    r2_adj: float | None
    r2_pred: float | None
    y: np.ndarray
    fitted: np.ndarray
    resid: np.ndarray
    leverage: np.ndarray
    xtx_inv: np.ndarray
    lof: LackOfFit | None = None
    removed: list = field(default_factory=list)     # (term, p when removed), in removal order
    q: dict = field(default_factory=dict)           # term -> BH q (filled by the caller)

    def coef(self) -> dict:
        return dict(zip(self.terms, self.beta))

    @property
    def p_of(self) -> dict:
        return dict(zip(self.terms, self.p))

    @property
    def std_resid(self) -> np.ndarray:
        if not self.s:
            return np.full(self.n, np.nan)
        with np.errstate(all="ignore"):
            return self.resid / (self.s * np.sqrt(np.clip(1 - self.leverage, 1e-12, None)))

    def predict(self, x: dict) -> dict:
        """x: name -> coded value(s). Mean, its 95% CI and the 95% prediction interval for a new run."""
        X = model_matrix({k: np.atleast_1d(np.asarray(v, float)) for k, v in x.items()}, self.terms)
        with np.errstate(all="ignore"):           # Accelerate BLAS false alarms on finite inputs
            yhat = X @ self.beta
        if self.s is None or self.df_resid <= 0:
            nan = np.full(len(yhat), np.nan)
            return {"mean": yhat, "ci": (nan, nan), "pi": (nan, nan), "se_mean": nan}
        with np.errstate(all="ignore"):
            h = np.einsum("ij,jk,ik->i", X, self.xtx_inv, X)
        tq = t_quantile(0.05, self.df_resid)
        se_m = self.s * np.sqrt(np.clip(h, 0, None))
        se_p = self.s * np.sqrt(1 + np.clip(h, 0, None))
        return {"mean": yhat, "se_mean": se_m, "ci": (yhat - tq * se_m, yhat + tq * se_m),
                "pi": (yhat - tq * se_p, yhat + tq * se_p)}


def fit(y, x: dict, terms: list[str], groups: list | None = None) -> Fit:
    """OLS of y on the terms. `groups` (one label per run: the setting of the model's factors) gives
    the pure-error / lack-of-fit split."""
    y = np.asarray(y, float)
    X = model_matrix(x, terms)
    n, p = X.shape
    with np.errstate(all="ignore"):               # Accelerate BLAS false alarms (see run_metrics)
        xtx_inv = np.linalg.pinv(X.T @ X)
        beta = xtx_inv @ X.T @ y
        fitted = X @ beta
        h = np.einsum("ij,jk,ik->i", X, xtx_inv, X)
    resid = y - fitted
    rank = int(np.linalg.matrix_rank(X))
    df = n - rank
    sse = float(resid @ resid)
    sst = float(((y - y.mean()) ** 2).sum())
    s = math.sqrt(sse / df) if df > 0 and sse > 0 else (0.0 if df > 0 else None)
    if s:
        se = s * np.sqrt(np.clip(np.diag(xtx_inv), 0, None))
        with np.errstate(all="ignore"):
            t = np.where(se > 0, beta / se, np.nan)
        p_ = np.array([f_sf(float(tt) ** 2, 1, df) if np.isfinite(tt) else np.nan for tt in t])
    else:
        se = t = p_ = np.full(p, np.nan)
    r2 = 1 - sse / sst if sst > 0 else None
    r2_adj = 1 - (sse / df) / (sst / (n - 1)) if sst > 0 and df > 0 else None
    with np.errstate(all="ignore"):
        press = float(((resid / np.clip(1 - h, 1e-12, None)) ** 2).sum()) if np.all(h < 1 - 1e-9) else None
    r2_pred = 1 - press / sst if press is not None and sst > 0 else None
    f = Fit(list(terms), beta, se, t, p_, n, df, s, r2, r2_adj, r2_pred, y, fitted, resid, h, xtx_inv)
    if groups is not None:
        f.lof = lack_of_fit(y, groups, sse, df)
    return f


def lack_of_fit(y, groups: list, sse: float, df_resid: int) -> LackOfFit | None:
    y = np.asarray(y, float)
    by: dict = {}
    for v, g in zip(y, groups):
        by.setdefault(g, []).append(v)
    ss_pe = float(sum(((np.array(v) - np.mean(v)) ** 2).sum() for v in by.values()))
    df_pe = sum(len(v) - 1 for v in by.values())
    df_lof = df_resid - df_pe
    if df_pe <= 0:
        return None
    ss_lof = max(0.0, sse - ss_pe)
    if df_lof <= 0:
        return LackOfFit(ss_lof, df_lof, ss_pe, df_pe, None, None)
    if ss_pe <= 0:
        return LackOfFit(ss_lof, df_lof, ss_pe, df_pe, math.inf, 0.0 if ss_lof > 0 else 1.0)
    F = (ss_lof / df_lof) / (ss_pe / df_pe)
    return LackOfFit(ss_lof, df_lof, ss_pe, df_pe, F, f_sf(F, df_lof, df_pe))


def backward(y, x: dict, terms: list[str], groups: list | None = None, alpha: float = ALPHA,
             keep: tuple = ()) -> Fit:
    """Backward elimination with hierarchy: at each step, of the terms no kept higher-order term
    needs, take the highest-order ones whose p > alpha and drop the one with the largest p; refit;
    stop when none qualifies. The intercept and `keep` (e.g. nuisance terms) always stay."""
    current = list(terms)
    removed = []
    while True:
        f = fit(y, x, current, groups)
        if f.s is None or f.df_resid <= 0:
            break
        needed = {k for t in current if term_order(t) == 2 for k in term_parents(t) if t not in keep}
        cands = [(term_order(t), f.p_of[t], t) for t in current
                 if t != "1" and t not in keep and not (term_order(t) == 1 and t in needed)
                 and np.isfinite(f.p_of[t]) and f.p_of[t] > alpha]
        if not cands:
            break
        top = max(c[0] for c in cands)
        _, pv, worst = max(c for c in cands if c[0] == top)
        current.remove(worst)
        removed.append((worst, float(pv)))
    f.removed = removed
    return f


def vif(x: dict, terms: list[str]) -> dict:
    """Variance inflation of each non-intercept term (centred columns)."""
    names = [t for t in terms if t != "1"]
    if len(names) < 2:
        return {t: 1.0 for t in names}
    M = model_matrix(x, names)
    M = M - M.mean(axis=0)
    sd = M.std(axis=0)
    out = {}
    live = sd > 1e-12
    if live.sum() >= 2:
        with np.errstate(all="ignore"):
            C = np.corrcoef(M[:, live], rowvar=False)
            v = np.diag(np.linalg.pinv(C))
        for t, val in zip([t for t, ok in zip(names, live) if ok], v):
            out[t] = float(val) if np.isfinite(val) else math.inf
    for t, ok in zip(names, live):
        if not ok:
            out[t] = math.inf
    return out


def correlation(x: dict, a: str, b: str) -> float | None:
    """Correlation between two terms' columns (e.g. a nuisance factor and an axis interaction)."""
    M = model_matrix(x, [a, b])
    if M[:, 0].std() == 0 or M[:, 1].std() == 0:
        return None
    return float(np.corrcoef(M[:, 0], M[:, 1])[0, 1])


def bh_across(fits: dict) -> None:
    """Benjamini-Hochberg q over every non-intercept term test of every fit (fills Fit.q)."""
    tests = [(name, t, f.p_of[t]) for name, f in fits.items() for t in f.terms
             if t != "1" and np.isfinite(f.p_of[t])]
    q = benjamini_hochberg([p for _, _, p in tests])
    for (name, t, _), qq in zip(tests, q):
        fits[name].q[t] = qq


# ---- where a fitted surface peaks (canonical analysis) ----------------------------------------------------

@dataclass
class Stationary:
    coded: dict                       # axis factor -> coded value of the stationary point
    value: float                      # fitted response there
    kind: str                         # "maximum" | "minimum" | "saddle" | "ridge" (a near-zero curvature)
    inside: bool                      # within the coded box [-1, 1] on every axis factor
    eigen: list                       # curvatures along the principal axes
    held: dict = field(default_factory=dict)   # axis factors with no curve, held (coded) while solving


def stationary(f: Fit, axis: list[str], fixed: dict | None = None, ridge_tol: float = 1e-6,
               fallback: dict | None = None) -> Stationary | None:
    """Solve grad = 0 of the fitted quadratic in the axis factors (other model factors held at `fixed`,
    coded). y = b0 + x'b + x'Bx; x_s = -B^-1 b / 2. When B is singular (a factor kept only as a straight
    line, so the surface is a ridge along it), solve along the factors that curve, with the straight-line
    ones held at `fallback` (coded; default 0) and listed in `held`. None if nothing curves."""
    c = f.coef()

    def inter(a, b_):
        return c.get(f"{a}*{b_}", c.get(f"{b_}*{a}", 0.0))

    def build(sub, others):
        k = len(sub)
        b = np.array([c.get(a, 0.0) + sum(inter(a, o) * v for o, v in others.items()) for a in sub])
        B = np.zeros((k, k))
        for i, a in enumerate(sub):
            B[i, i] = c.get(f"{a}^2", 0.0)
            for j in range(i + 1, k):
                B[i, j] = B[j, i] = inter(a, sub[j]) / 2
        return b, B

    held = {}
    sub = list(axis)
    b, B = build(sub, {})
    if np.linalg.matrix_rank(B) < len(sub):
        sub = [a for a in axis if c.get(f"{a}^2", 0.0) != 0.0]
        held = {a: float((fallback or {}).get(a, 0.0)) for a in axis if a not in sub}
        if not sub:
            return None
        b, B = build(sub, held)
        if np.linalg.matrix_rank(B) < len(sub):
            return None
    axis = sub
    k = len(axis)
    xs = -0.5 * np.linalg.solve(B, b)
    ev = np.linalg.eigvalsh(B)
    scale = max(1e-12, float(np.abs(ev).max()))
    if np.all(ev < -ridge_tol * scale):
        kind = "maximum"
    elif np.all(ev > ridge_tol * scale):
        kind = "minimum"
    else:
        kind = "saddle"
    if np.min(np.abs(ev)) < 0.05 * scale:
        kind = f"{kind} (nearly a ridge: one direction is almost flat)"
    x = {a: float(v) for a, v in zip(axis, xs)}
    pt = dict(fixed or {})
    pt.update(held)
    pt.update(x)
    val = float(f.predict({kk: np.array([vv]) for kk, vv in pt.items()})["mean"][0])
    return Stationary(x, val, kind, bool(np.all(np.abs(xs) <= 1 + 1e-9)), ev.tolist(), held)


# ---- drift ----------------------------------------------------------------------------------------------------

@dataclass
class TimeTrend:
    n: int
    slope_per_h: float
    se: float | None
    p: float | None


def time_trend(values, hours) -> TimeTrend | None:
    """Straight line through (hours, value): e.g. the centre runs through the day."""
    v = np.asarray(values, float)
    t = np.asarray(hours, float)
    ok = np.isfinite(v) & np.isfinite(t)
    v, t = v[ok], t[ok]
    if v.size < 3 or t.std() == 0:
        return None
    sxx = float(((t - t.mean()) ** 2).sum())
    slope = float(((t - t.mean()) * (v - v.mean())).sum() / sxx)
    res = v - v.mean() - slope * (t - t.mean())
    df = v.size - 2
    se = math.sqrt(float(res @ res) / df / sxx) if df > 0 else None
    p = f_sf((slope / se) ** 2, 1, df) if se else None
    return TimeTrend(int(v.size), slope, se, p)


# ---- desirability and the optimum ------------------------------------------------------------------------------

@dataclass
class Goal:
    key: str                          # response key
    direction: str                    # "max" | "min" | "target"
    low: float
    high: float
    target: float | None = None
    weight: float = 1.0               # ramp shape: 1 linear, > 1 stricter, < 1 more lenient
    importance: float = 1.0           # weight in the geometric mean

    def d(self, y):
        y = np.asarray(y, float)
        lo, hi = self.low, self.high
        if hi <= lo:
            return np.where(np.isfinite(y), 1.0, 0.0)
        if self.direction == "max":
            r = np.clip((y - lo) / (hi - lo), 0, 1)
        elif self.direction == "min":
            r = np.clip((hi - y) / (hi - lo), 0, 1)
        else:
            tg = self.target if self.target is not None else (lo + hi) / 2
            up = np.clip((y - lo) / max(tg - lo, 1e-12), 0, 1)
            down = np.clip((hi - y) / max(hi - tg, 1e-12), 0, 1)
            r = np.where(y <= tg, up, down)
        return r ** self.weight


@dataclass
class Constraint:
    key: str                          # response key
    low: float | None = None
    high: float | None = None         # e.g. peak pressure limit (barA)

    def ok(self, y):
        y = np.asarray(y, float)
        good = np.isfinite(y)
        if self.low is not None:
            good &= y >= self.low
        if self.high is not None:
            good &= y <= self.high
        return good


def desirability(preds: dict, goals: list[Goal], constraints: list[Constraint] = ()) -> np.ndarray:
    """preds: response key -> predicted values (arrays, same shape). Overall D in [0, 1]."""
    shape = np.shape(next(iter(preds.values())))
    logsum = np.zeros(shape)
    wsum = 0.0
    for g in goals:
        if g.key not in preds:
            continue
        with np.errstate(divide="ignore"):
            logsum = logsum + g.importance * np.log(g.d(preds[g.key]))
        wsum += g.importance
    D = np.exp(logsum / wsum) if wsum else np.ones(shape)
    for c in constraints:
        if c.key in preds:
            D = np.where(c.ok(preds[c.key]), D, 0.0)
    return D


@dataclass
class Optimum:
    coded: dict                       # axis factor -> coded value
    D: float
    preds: dict                       # response key -> predicted mean
    d_each: dict                      # response key -> its desirability
    feasible_share: float             # share of the searched region meeting every constraint
    on_edge: list                     # axis factors at the edge of the searched range


def optimise(fits: dict, goals: list[Goal], axis_ranges: dict, fixed: dict | None = None,
             constraints: list[Constraint] = (), discrete: dict | None = None,
             budget: int = GRID_BUDGET) -> Optimum | None:
    """Maximise D over the axis factors. axis_ranges: factor -> (coded lo, coded hi); discrete:
    factor -> the coded values that can actually be set (only those are searched); fixed: factor ->
    coded value for every model factor not searched (nuisance, time)."""
    fixed = dict(fixed or {})
    discrete = discrete or {}
    keys = list(axis_ranges)
    cont = [k for k in keys if k not in discrete]
    per = max(5, int(budget ** (1 / max(1, len(cont))))) if cont else 1
    axes = {k: (np.array(sorted(discrete[k]), float) if k in discrete
                else np.linspace(axis_ranges[k][0], axis_ranges[k][1], per)) for k in keys}
    mesh = np.meshgrid(*[axes[k] for k in keys], indexing="ij")
    grid = {k: m.ravel() for k, m in zip(keys, mesh)}

    def evaluate(g: dict):
        x = dict(g)
        n = len(next(iter(g.values())))
        for k, v in fixed.items():
            x[k] = np.full(n, v)
        preds = {key: f.predict(x)["mean"] for key, f in fits.items()}
        return preds, desirability(preds, goals, constraints)

    preds, D = evaluate(grid)
    feasible = float(np.mean(np.all([c.ok(preds[c.key]) for c in constraints if c.key in preds], axis=0))) \
        if any(c.key in preds for c in constraints) else 1.0
    i = int(np.argmax(D))
    best = {k: float(grid[k][i]) for k in keys}
    # local refinement on the continuous factors (a finer grid around the best grid point)
    if cont and D[i] > 0:
        step = {k: (axis_ranges[k][1] - axis_ranges[k][0]) / max(per - 1, 1) for k in cont}
        local = {k: (np.linspace(max(axis_ranges[k][0], best[k] - step[k]),
                                 min(axis_ranges[k][1], best[k] + step[k]), 11) if k in cont
                     else np.array([best[k]])) for k in keys}
        m2 = np.meshgrid(*[local[k] for k in keys], indexing="ij")
        g2 = {k: m.ravel() for k, m in zip(keys, m2)}
        p2, D2 = evaluate(g2)
        j = int(np.argmax(D2))
        if D2[j] > D[i]:
            best = {k: float(g2[k][j]) for k in keys}
    pb, Db = evaluate({k: np.array([v]) for k, v in best.items()})
    d_each = {g.key: float(g.d(pb[g.key])[0]) for g in goals if g.key in pb}
    edge = [k for k in cont if min(abs(best[k] - axis_ranges[k][0]), abs(best[k] - axis_ranges[k][1])) < 1e-6]
    return Optimum(best, float(Db[0]), {k: float(v[0]) for k, v in pb.items()}, d_each, feasible, edge)
