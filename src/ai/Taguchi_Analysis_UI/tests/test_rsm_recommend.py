"""Phase 6: the next-run recommender, on measured fake 3-factor CCF days (gas x feed x orifice, RPM 500,
orifice blocks, five centres, a 0.8 mm check run) with PLANTED atomised-fraction surfaces chosen so each
recommendation should, or should not, appear."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import rsm_design as rb
from src.ai.Taguchi_Analysis_UI import rsm_detect as rsm
from src.ai.Taguchi_Analysis_UI import rsm_recommend as rec
from src.ai.Taguchi_Analysis_UI import rsm_responses as rr
from src.ai.Taguchi_Analysis_UI import rsm_stats as rs
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI.tests import fakes
from src.ai.Taguchi_Analysis_UI.tests.test_rsm_responses import _ccf_rows, _o_real

INSERTS = {"orifice": [0.5, 0.8, 1.2, 1.8]}


@pytest.fixture(scope="module", autouse=True)
def no_bootstrap():
    ta = spec.rdc_module("taguchi_analysis")
    old = ta.N_BOOT
    ta.N_BOOT = 0
    yield
    ta.N_BOOT = old


def world(truth, *, check_offset=0.0, seed=5):
    """Analyse a measured fake CCF day whose atomised % is truth(g, f, o_real); the 0.8 mm check run
    can be pushed off the surface by check_offset points."""
    d = tempfile.TemporaryDirectory()
    root = Path(d.name)
    rng = np.random.default_rng(seed)
    paths = []
    start = datetime(2026, 10, 12, 8, 0)
    for i, (mm, g, f, kind) in enumerate(_ccf_rows(), 1):
        gas, feed = 9000 + 2000 * g, 4000 + 1000 * f
        t = (start + timedelta(minutes=9 * i)).strftime("%H%M%S")
        run = fakes.make_run(root, f"{t}_{gas:g}sccm_500rpm_{feed:g}sps_or{mm:g}_bh0.5", day=("2026", "10", "12"),
                             notes=f"CCD run {i} {kind}")
        a = truth(g, f, _o_real(mm)) + (check_offset if kind == "Check run" else 0.0)
        fakes.write_results(run, rng, 55 - 2 * g, a / 100, n_frames=60, per_frame=80)
        paths.append(run)
    design = rsm.from_runs(rd.load_runs(paths, check_reuse=False))
    L = rr.load(design.detect(), design.base.runs)
    R = rr.analyse(L, goals=[rs.Goal("atom", "max", 0, 40)], discrete=INSERTS)
    return d, R


@pytest.fixture(scope="module")
def interior():
    d, R = world(lambda g, f, o: 14 + 2 * g - 2 * g * g - 1.5 * f * f + 1.0 * o - 1.2 * o * o)
    yield R
    d.cleanup()


@pytest.fixture(scope="module")
def gas_edge():
    d, R = world(lambda g, f, o: 14 + 4 * g - 0.4 * g * g - 1.5 * f * f + 0.5 * o - 1.0 * o * o)
    yield R
    d.cleanup()


def _kinds(recs):
    return [r.kind for r in recs]


# ---- an optimum inside the region ------------------------------------------------------------------------

def test_an_interior_optimum_gets_confirmation_runs_only(interior):
    recs = rec.recommend(interior, INSERTS)
    assert _kinds(recs) == ["confirm"]
    c = recs[0]
    assert len(c.rows) == 4 and c.rows[-1].label.startswith("Anchor")
    best = c.rows[0].values
    assert best["sccm"] == pytest.approx(10000, abs=400)                 # planted: g = 0.5
    assert best["sps"] == pytest.approx(4000, abs=300)
    assert best["orifice"] in INSERTS["orifice"] and best["sccm"] % 100 == 0
    m, lo, hi = c.rows[0].preds["atom"]
    truth = 14 + 2 * 0.5 - 2 * 0.25 + 1.0 * _o_real(best["orifice"]) - 1.2 * _o_real(best["orifice"]) ** 2
    assert lo < truth < hi and not c.rows[0].extrapolated


def test_snap_keeps_settings_runnable(interior):
    """The rig's limits (gas 12,000 sccm), its setpoint steps, and the levels that exist."""
    assert rec.snap(interior, "sccm", 12345) == 12000 and rec.snap(interior, "sccm", -50) == 0
    assert rec.snap(interior, "rpm", 1700) == 1000 and rec.snap(interior, "sps", 12600) == 12000
    assert rec.snap(interior, "sccm", 10449) == 10400 and rec.snap(interior, "sps", 3951) == 4000
    assert rec.snap(interior, "sps", 400) == 2000                       # the lowest feed that sprays usefully
    assert rec.snap(interior, "orifice", 1.45, INSERTS) == 1.2 and rec.snap(interior, "orifice", 1.6, INSERTS) == 1.8


# ---- an optimum on the gas edge -------------------------------------------------------------------------

def test_an_edge_optimum_gets_a_path_outward_that_stops_at_the_gas_limit(gas_edge):
    recs = {r.kind: r for r in rec.recommend(gas_edge, INSERTS)}
    assert "steepest" in recs and "new_ccd" in recs
    rows = recs["steepest"].rows
    gas = [r.values["sccm"] for r in rows]
    assert gas == sorted(gas) and gas[0] > 11000 and max(gas) <= 12000
    assert rows[-1].values["sccm"] == 12000 and "rig's limit" in rows[-1].label
    assert all(r.extrapolated for r in rows)
    assert all(r.values["orifice"] in INSERTS["orifice"] for r in rows)          # fixed sizes do not walk


def test_the_new_ccd_contains_the_best_point_and_respects_the_rig(gas_edge):
    r = next(x for x in rec.recommend(gas_edge, INSERTS) if x.kind == "new_ccd")
    gas = next(f for f in r.plan.factors if f.key == "sccm")
    assert gas.high <= 12000 and gas.low < 11000 < gas.high
    assert r.sheet is not None and r.sheet.estimability.usable
    ori = next(f for f in r.plan.factors if f.key == "orifice")
    assert (ori.low, ori.mid, ori.high) == (0.5, 1.2, 1.8)                     # inserts stay the ones that exist


def test_a_path_towards_low_feed_stops_at_the_feed_floor_not_at_zero():
    """Found 2026-10-11 on the 9x3: goals favouring a high atomised fraction walked feed down to 0 steps/s."""
    d, R = world(lambda g, f, o: 14 + 2 * g - 2 * g * g - 4.0 * f + 0.5 * o - 1.0 * o * o)
    try:
        steep = next(r for r in rec.recommend(R, INSERTS) if r.kind == "steepest")
        feed = [r.values["sps"] for r in steep.rows]
        assert feed == sorted(feed, reverse=True) and feed[-1] == 2000 and min(feed) >= 2000
        assert "rig's limit" in steep.rows[-1].label
        ccd = next(r for r in rec.recommend(R, INSERTS) if r.kind == "new_ccd")
        assert next(f for f in ccd.plan.factors if f.key == "sps").low >= 2000
    finally:
        d.cleanup()


# ---- a new insert ---------------------------------------------------------------------------------------------

def test_a_new_insert_is_proposed_only_when_all_three_conditions_hold():
    rising = lambda g, f, o: 14 + 1.5 * g - 1.5 * g * g - 1.0 * f * f + 3.0 * o       # still rising at 1.8 mm
    d1, good = world(rising)
    d2, bad = world(rising, check_offset=-6.0)                                         # the check run misses
    try:
        nl = [r for r in rec.recommend(good, INSERTS) if r.kind == "new_level"]
        assert len(nl) == 1 and "2.7" in nl[0].title                                 # 1.8 x 1.8 / 1.2
        assert nl[0].rows[0].values["orifice"] == pytest.approx(2.7) and nl[0].rows[0].extrapolated
        assert not [r for r in rec.recommend(bad, INSERTS) if r.kind == "new_level"]
    finally:
        d1.cleanup()
        d2.cleanup()


def test_no_new_insert_when_the_optimum_is_not_at_an_orifice_edge(interior):
    assert not rec.new_level(interior, INSERTS)


# ---- strengthening a weak model --------------------------------------------------------------------------------

def test_a_weak_model_gets_d_optimal_runs_and_the_first_is_the_least_certain_setting():
    cubic = lambda g, f, o: 14 + 3 * g - 1.5 * f * f + 0.5 * o + 4.0 * g ** 3 * f * f   # a quadratic cannot follow
    d, R = world(cubic)
    try:
        lof = R.fits["atom"].full.lof
        assert lof.p < 0.05
        r = rec.augment(R, INSERTS, n=4)
        assert r is not None and len(r.rows) == 4 and "lack of fit" in r.why
        # independently: the first pick maximises x'(X'X)^-1 x over the runnable candidates
        keys = list(R.axis)
        fit = [x for x in R.loaded.runs if x.point.in_fit]
        X = rs.model_matrix({k: np.array([x.point.real[k] for x in fit]) for k in keys}, R.terms)
        cands = rec._candidates(R, INSERTS)
        C = rs.model_matrix({k: np.array([rec._f(R, k).real_code(c[k]) for c in cands]) for k in keys}, R.terms)
        with np.errstate(all="ignore"):                    # Accelerate BLAS false alarms
            lev = np.einsum("ij,jk,ik->i", C, np.linalg.inv(X.T @ X), C)
        assert r.rows[0].values == cands[int(np.argmax(lev))]
        assert all(row.values["orifice"] in INSERTS["orifice"] for row in r.rows)
    finally:
        d.cleanup()


def test_a_failed_check_run_gets_a_run_next_to_it_first():
    d, R = world(lambda g, f, o: 14 + 2 * g - 2 * g * g - 1.5 * f * f + 1.0 * o - 1.2 * o * o, check_offset=-6.0)
    try:
        r = rec.augment(R, INSERTS)
        assert r is not None and "missed its prediction" in r.why
        assert r.rows[0].label.startswith("Next to") and r.rows[0].values["orifice"] == 0.8
    finally:
        d.cleanup()


def test_an_interior_well_fitted_model_needs_no_strengthening(interior):
    assert rec.augment(interior, INSERTS) is None


# ---- the exported run sheet ---------------------------------------------------------------------------------------

def test_the_next_runs_export_and_the_new_ccd_sheet(gas_edge, tmp_path):
    recs = rec.recommend(gas_edge, INSERTS)
    files = {p.relative_to(tmp_path).as_posix() for p in rec.export(gas_edge, recs, tmp_path)}
    assert {"next_runs.csv", "next_runs.xlsx", "next_runs.md", "next CCD/run_sheet.xlsx"} <= files
    rows = rec.table(gas_edge, recs)
    assert [r["Run"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0]["Notes to type"] == "CCD next run 1 confirm"
    assert any("predicted Atomised fraction" in k for k in rows[0])
    assert rb.load(tmp_path / "next CCD") is not None
