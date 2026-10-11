"""Phase 4: the response-surface statistics, against known answers and independent calculations.

Planted quadratics on CCF layouts; the fit checked against a separate QR / scipy computation, PRESS
against explicit leave-one-out refits, lack of fit against the CCD plan's own formula, prediction
intervals by simulation, backward elimination's hierarchy rule, and the desirability optimum against
planted optima, constraints and settable levels."""
from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from scipy import stats as sps

from src.ai.Taguchi_Analysis_UI import rsm_stats as rs


def ccf(k: int, centres: int = 5) -> np.ndarray:
    pts = list(itertools.product((-1, 1), repeat=k))
    pts += [tuple(s if j == i else 0 for j in range(k)) for i in range(k) for s in (-1, 1)]
    pts += [(0,) * k] * centres
    return np.array(pts, float)


KEYS = ["a", "b", "c"]
TRUE = {"1": 10.0, "a": 2.0, "b": -1.0, "c": 0.5, "a*b": 0.8, "a*c": 0.0, "b*c": -0.3,
        "a^2": -1.5, "b^2": 0.4, "c^2": 0.0}


def planted(P: np.ndarray, coef=TRUE, noise=0.0, seed=0):
    x = {k: P[:, i] for i, k in enumerate(KEYS)}
    terms = list(coef)
    y = rs.model_matrix(x, terms) @ np.array([coef[t] for t in terms])
    y = y + np.random.default_rng(seed).normal(0, noise, len(y)) if noise else y
    return x, y, terms


def groups_of(P):
    return [tuple(r) for r in P]


def test_quadratic_terms_and_model_matrix():
    t = rs.quadratic_terms(["g", "f"], {"rpm": "quadratic"}, time_term=True)
    assert t == ["1", "g", "f", "g*f", "g^2", "f^2", "rpm", "rpm^2", "time"]
    X = rs.model_matrix({"g": np.array([1., -1]), "f": np.array([2., 3])}, ["1", "g", "g*f", "f^2"])
    assert X.tolist() == [[1, 1, 2, 4], [1, -1, -3, 9]]


def test_a_noise_free_quadratic_is_recovered_exactly():
    P = ccf(3)
    x, y, terms = planted(P)
    f = rs.fit(y, x, rs.quadratic_terms(KEYS))
    for t, b in f.coef().items():
        assert b == pytest.approx(TRUE[t], abs=1e-9), t
    assert f.r2 == pytest.approx(1.0)


def test_coefficients_se_and_p_match_an_independent_calculation():
    P = ccf(3)
    x, y, _ = planted(P, noise=0.3, seed=4)
    terms = rs.quadratic_terms(KEYS)
    f = rs.fit(y, x, terms, groups_of(P))
    X = rs.model_matrix(x, terms)
    Q, R = np.linalg.qr(X)
    beta = np.linalg.solve(R, Q.T @ y)
    resid = y - X @ beta
    df = len(y) - X.shape[1]
    s2 = resid @ resid / df
    Rinv = np.linalg.inv(R)
    se = np.sqrt(s2 * np.sum(Rinv ** 2, axis=1))
    p = 2 * sps.t.sf(np.abs(beta / se), df)
    assert np.allclose(f.beta, beta, atol=1e-9) and np.allclose(f.se, se, rtol=1e-7)
    assert np.allclose(f.p, p, rtol=1e-6, atol=1e-12)
    sst = ((y - y.mean()) ** 2).sum()
    assert f.r2 == pytest.approx(1 - resid @ resid / sst)
    assert f.r2_adj == pytest.approx(1 - (resid @ resid / df) / (sst / (len(y) - 1)))


def test_predicted_r2_is_leave_one_out():
    P = ccf(3)
    x, y, _ = planted(P, noise=0.3, seed=5)
    terms = rs.quadratic_terms(KEYS)
    f = rs.fit(y, x, terms)
    press = 0.0
    for i in range(len(y)):
        keep = np.arange(len(y)) != i
        g = rs.fit(y[keep], {k: v[keep] for k, v in x.items()}, terms)
        press += (y[i] - g.predict({k: v[i] for k, v in x.items()})["mean"][0]) ** 2
    assert f.r2_pred == pytest.approx(1 - press / ((y - y.mean()) ** 2).sum(), rel=1e-6)


def test_lack_of_fit_matches_the_ccd_plans_formula_and_catches_a_cubic():
    P = ccf(3)
    x, y, _ = planted(P, noise=0.2, seed=6)
    terms = rs.quadratic_terms(KEYS)
    f = rs.fit(y, x, terms, groups_of(P))
    # the plan's code: ss_pe over identical settings, F = ((ssr - ss_pe)/(df_resid - df_pe)) / (ss_pe/df_pe)
    cells: dict = {}
    for row, v in zip(map(tuple, P), y):
        cells.setdefault(row, []).append(v)
    ss_pe = sum(((np.array(v) - np.mean(v)) ** 2).sum() for v in cells.values())
    df_pe = sum(len(v) - 1 for v in cells.values())
    ssr = (f.resid ** 2).sum()
    F = ((ssr - ss_pe) / (f.df_resid - df_pe)) / (ss_pe / df_pe)
    assert f.lof.df_pe == df_pe == 4 and f.lof.df_lof == f.df_resid - 4
    assert f.lof.F == pytest.approx(F) and f.lof.p == pytest.approx(1 - sps.f.cdf(F, f.df_resid - df_pe, df_pe))
    cubic = y + 3.0 * P[:, 0] ** 3 * P[:, 1] ** 2            # something a quadratic cannot follow
    assert rs.fit(cubic, x, terms, groups_of(P)).lof.p < 0.01


def test_prediction_intervals_cover_95_percent_of_new_runs():
    P = ccf(3)
    rng = np.random.default_rng(7)
    xnew = {"a": 0.4, "b": -0.6, "c": 0.2}
    true_new = rs.model_matrix({k: np.array([v]) for k, v in xnew.items()}, list(TRUE)) @ np.array(list(TRUE.values()))
    hits = 0
    n = 1500
    for i in range(n):
        x, y, _ = planted(P, noise=0.5, seed=1000 + i)
        pr = rs.fit(y, x, rs.quadratic_terms(KEYS)).predict(xnew)
        ynew = true_new[0] + rng.normal(0, 0.5)
        hits += pr["pi"][0][0] <= ynew <= pr["pi"][1][0]
    assert abs(hits / n - 0.95) < 0.02


def test_backward_elimination_keeps_hierarchy_and_drops_noise():
    """A pure a*b interaction with no b main effect, over 100 noise draws: the true terms always stay;
    b always stays because a*b needs it (hierarchy); higher-order terms always leave before linear
    ones; and noise terms survive only as often as testing ~7 null terms at 0.05 makes likely (one
    draw in 4 or so -- seed 8 keeps b^2 at p = 0.019, a genuine chance result)."""
    P = ccf(3)
    coef = {"1": 5.0, "a": 2.0, "b": 0.0, "c": 0.0, "a*b": 1.5, "a*c": 0, "b*c": 0, "a^2": 0, "b^2": 0, "c^2": 0}
    extra = 0
    for seed in range(100):
        x, y, _ = planted(P, coef, noise=0.05, seed=seed)
        f = rs.backward(y, x, rs.quadratic_terms(KEYS), groups_of(P))
        assert {"1", "a", "b", "a*b"} <= set(f.terms)
        for t in f.terms:
            assert all(p in f.terms for p in rs.term_parents(t))
        orders = [rs.term_order(t) for t, _ in f.removed]
        assert orders == sorted(orders, reverse=True)
        extra += set(f.terms) != {"1", "a", "b", "a*b"}
    assert extra < 40


def test_nuisance_terms_are_never_dropped():
    P = ccf(3)
    x, y, _ = planted(P, noise=0.05, seed=9)
    terms = rs.quadratic_terms(["a", "b"], {"c": "quadratic"})
    f = rs.backward(y, x, terms, groups_of(P), keep=("c", "c^2"))
    assert {"c", "c^2"} <= set(f.terms)


def test_vif_and_correlation():
    P = ccf(3)
    x = {k: P[:, i] for i, k in enumerate(KEYS)}
    v = rs.vif(x, rs.quadratic_terms(KEYS))
    assert max(v.values()) < 3 and v["a"] == pytest.approx(1.0)
    # an L9: c is built from a and b, so c correlates with the a*b interaction
    L9 = np.array([(a, b, (a + b) % 3 - 1) for a in (-1, 0, 1) for b in (-1, 0, 1)], float)
    xl = {k: L9[:, i] for i, k in enumerate(KEYS)}
    assert abs(rs.correlation(xl, "c", "a*b")) > 0.3


def test_time_trend_by_hand():
    t = rs.time_trend([1.0, 2.0, 2.9, 4.1], [0, 1, 2, 3])
    assert t.slope_per_h == pytest.approx(1.02) and t.n == 4 and t.p < 0.01
    assert rs.time_trend([1, 2], [0, 1]) is None


def test_bh_across_fills_q_for_every_term():
    P = ccf(3)
    x, y, terms = planted(P, noise=0.3, seed=10)
    fits = {"r1": rs.fit(y, x, rs.quadratic_terms(KEYS)), "r2": rs.fit(y[::-1], x, rs.quadratic_terms(KEYS))}
    rs.bh_across(fits)
    assert len(fits["r1"].q) == 9 and all(fits["r1"].q[t] >= fits["r1"].p_of[t] - 1e-12 for t in fits["r1"].q)


# ---- desirability ------------------------------------------------------------------------------------------

def test_desirability_ramps_by_hand():
    g = rs.Goal("y", "max", 10, 20)
    assert g.d([5, 10, 15, 20, 25]).tolist() == [0, 0, 0.5, 1, 1]
    assert rs.Goal("y", "min", 10, 20).d([15]).tolist() == [0.5]
    assert rs.Goal("y", "target", 10, 20, target=12).d([11, 12, 16]).tolist() == pytest.approx([0.5, 1, 0.5])
    D = rs.desirability({"y": np.array([15.0]), "z": np.array([1.0])},
                        [rs.Goal("y", "max", 10, 20), rs.Goal("z", "max", 0, 4)])
    assert D[0] == pytest.approx(math.sqrt(0.5 * 0.25))
    assert rs.desirability({"y": np.array([15.0]), "p": np.array([5.0])}, [rs.Goal("y", "max", 10, 20)],
                           [rs.Constraint("p", high=4)])[0] == 0


def _fits_for(fn, k=2, n_centres=5):
    P = ccf(k, n_centres)
    x = {kk: P[:, i] for i, kk in enumerate(KEYS[:k])}
    return x, rs.fit(fn(P), x, rs.quadratic_terms(KEYS[:k]))


def test_the_optimum_finds_a_planted_peak_respects_a_constraint_and_settable_levels():
    x, fy = _fits_for(lambda P: 10 - (P[:, 0] - 0.3) ** 2 - (P[:, 1] + 0.2) ** 2)
    _, fp = _fits_for(lambda P: 3 + P[:, 0])                     # "pressure" rises with a
    goals = [rs.Goal("y", "max", 8, 10)]
    o = rs.optimise({"y": fy}, goals, {"a": (-1, 1), "b": (-1, 1)})
    assert o.coded["a"] == pytest.approx(0.3, abs=0.01) and o.coded["b"] == pytest.approx(-0.2, abs=0.01)
    assert o.D == pytest.approx(1.0, abs=1e-3) and o.on_edge == []
    o2 = rs.optimise({"y": fy, "p": fp}, goals, {"a": (-1, 1), "b": (-1, 1)}, constraints=[rs.Constraint("p", high=3.0)])
    assert o2.coded["a"] == pytest.approx(0.0, abs=0.02) and o2.preds["p"] <= 3.0 + 1e-9
    assert 0.4 < o2.feasible_share < 0.6
    o3 = rs.optimise({"y": fy}, goals, {"a": (-1, 1), "b": (-1, 1)}, discrete={"a": [-1, -0.4, 0.5, 1]})
    assert o3.coded["a"] == 0.5 and o3.coded["b"] == pytest.approx(-0.2, abs=0.01)


def test_an_optimum_outside_the_region_is_reported_on_the_edge():
    x, fy = _fits_for(lambda P: 5 + 2 * P[:, 0] + 0.5 * P[:, 1])
    o = rs.optimise({"y": fy}, [rs.Goal("y", "max", 2, 8)], {"a": (-1, 1), "b": (-1, 1)})
    assert o.coded == {"a": 1.0, "b": 1.0} and set(o.on_edge) == {"a", "b"}
