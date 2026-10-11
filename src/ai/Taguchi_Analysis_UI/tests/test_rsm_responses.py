"""Phase 4: loading a detected response-surface design's runs and analysing every response, end to end
on MEASURED fake runs (fakes.write_results: load_run's self-consistency gates genuinely pass).

A 3-factor CCF day (gas x feed x orifice, RPM 500, orifice blocks, five centres, a 0.8 mm check run)
with a planted atomised-fraction surface; and the 9x3 layout (fakes.make_measured_l9x3) analysed as a
gas x feed surface with RPM as a nuisance term, the set-up of the Phase 4b real-data trial."""
from __future__ import annotations

import itertools
import math
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import rsm_detect as rsm
from src.ai.Taguchi_Analysis_UI import rsm_responses as rr
from src.ai.Taguchi_Analysis_UI import rsm_stats as rs
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI.tests import fakes

REAL_10_05 = Path("/Volumes/LaCie/Experiments/2026/10/05")
ORI = (0.5, 1.2, 1.8)


def atom_pct(g, f, o_real):
    """The planted surface (atomised %), in coded gas / feed and the orifice's REAL coding."""
    return 12 + 4 * g - 2 * f + 2 * g * f - 3 * g * g + 1.0 * o_real


def _o_real(mm):
    return (mm - (ORI[0] + ORI[2]) / 2) / ((ORI[2] - ORI[0]) / 2)


def _ccf_rows():
    corners = list(itertools.product((-1, 1), repeat=2))
    rows = [(0.5, 0, 0, "Block repeat")] + [(0.5, g, f, "Corner") for g, f in corners] + [(0.5, 0, 0, "Block repeat")]
    rows += [(1.2, 0, 0, "Centre"), (1.2, 1, 0, "Gas face"), (1.2, 0, 1, "Feed face"), (1.2, 0, 0, "Centre"),
             (1.2, 0, -1, "Feed face"), (1.2, -1, 0, "Gas face"), (1.2, 0, 0, "Centre"), (1.2, 0, 0, "Centre"),
             (1.2, 0, 0, "Centre")]
    rows += [(1.8, 0, 0, "Block repeat")] + [(1.8, g, f, "Corner") for g, f in corners] + [(1.8, 0, 0, "Block repeat")]
    rows += [(0.8, 0, 0, "Check run")]
    return rows


@pytest.fixture(scope="module", autouse=True)
def no_bootstrap():
    ta = spec.rdc_module("taguchi_analysis")
    old = ta.N_BOOT
    ta.N_BOOT = 20
    yield
    ta.N_BOOT = old


@pytest.fixture(scope="module")
def ccf_world():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        rng = np.random.default_rng(11)
        paths = []
        start = datetime(2026, 10, 12, 8, 0)
        rows = _ccf_rows() + [(1.2, 0, 0, "Validation (bad)")]
        for i, (mm, g, f, kind) in enumerate(rows, 1):
            gas, feed = 9000 + 2000 * g, 4000 + 1000 * f
            t = (start + timedelta(minutes=9 * i)).strftime("%H%M%S")
            run = fakes.make_run(root, f"{t}_{gas:g}sccm_500rpm_{feed:g}sps_or{mm:g}_bh0.5", day=("2026", "10", "12"),
                                 notes=f"CCD run {i} {kind}")
            a = atom_pct(g, f, _o_real(mm)) if kind != "Validation (bad)" else 30.0
            fakes.write_results(run, rng, 55 - 3 * g + 2 * f, a / 100, n_frames=40, per_frame=60)
            paths.append(run)
        runs = rd.load_runs(paths, check_reuse=False)
        design = rsm.from_runs(runs)
        bad = next(r for r in design.base.rows if "Validation" in r.notes)
        design.validation.add(bad.path)
        det = design.detect()
        L = rr.load(det, design.base.runs)
        res = rr.analyse(L, goals=[rs.Goal("atom", "max", 0, 20)],
                         discrete={"orifice": [0.5, 0.8, 1.2, 1.8]})
        yield {"det": det, "L": L, "res": res}


def test_every_run_loads_and_the_design_is_the_ccf(ccf_world):
    det, L = ccf_world["det"], ccf_world["L"]
    assert det.type_key == "ccf" and det.k == 3 and L.refused is None and not L.skipped
    assert len(L.runs) == 23 and sum(r.point.in_fit for r in L.runs) == 21     # 22 planned + 1 validation


def test_the_planted_surface_is_recovered(ccf_world):
    f = ccf_world["res"].fits["atom"].full
    c = f.coef()
    assert c["sccm"] == pytest.approx(4, abs=0.6) and c["sccm^2"] == pytest.approx(-3, abs=0.8)
    assert c["sps"] == pytest.approx(-2, abs=0.6) and c["sccm*sps"] == pytest.approx(2, abs=0.6)
    assert c["orifice"] == pytest.approx(1, abs=0.6)
    assert f.p_of["sccm"] < 0.001 and f.p_of["sccm^2"] < 0.01 and f.r2 > 0.9
    red = ccf_world["res"].fits["atom"].reduced
    assert {"sccm", "sps", "sccm*sps", "sccm^2"} <= set(red.terms)
    assert f.lof is not None and f.lof.df_pe == 4 + 1 + 1
    assert f.q and all(0 <= q <= 1 for q in f.q.values())


def test_the_check_run_is_predicted_and_a_bad_validation_run_fails(ccf_world):
    """The check run's prediction must match the planted surface; whether this one noisy draw lands
    inside its 95% PI is a 1-in-20 coin (here it lands 0.57 above a 0.55 half-width), so the PI is
    checked for arithmetic here and for coverage by simulation in test_rsm_stats."""
    preds = {p.run.point.row.notes.split(" ", 3)[-1]: p for p in ccf_world["res"].fits["atom"].predictions}
    check = preds["Check run"]
    assert not check.extrapolated
    assert check.mean == pytest.approx(atom_pct(0, 0, _o_real(0.8)), abs=0.3)
    assert check.inside == (check.pi[0] <= check.observed <= check.pi[1])
    assert abs(check.observed - check.mean) < 2 * (check.pi[1] - check.pi[0]) / 2
    bad = preds["Validation (bad)"]
    assert bad.inside is False and bad.observed == pytest.approx(30, abs=1.5)


def test_the_optimum_is_where_the_algebra_puts_it(ccf_world):
    """Max of 12 + 4g - 2f + 2gf - 3g^2 + o: f = -1, then g = 1/3, and the largest orifice."""
    res = ccf_world["res"]
    o = res.optimum
    assert o.coded["sps"] == pytest.approx(-1) and o.coded["sccm"] == pytest.approx(1 / 3, abs=0.15)
    assert o.coded["orifice"] == pytest.approx(1) and "sps" in o.on_edge
    od = res.optimum_discrete
    assert res.decode("orifice", od.coded["orifice"]) == pytest.approx(1.8)


def test_drift_checks_are_computed(ccf_world):
    fr = ccf_world["res"].fits["atom"]
    assert fr.centre_trend is not None and fr.centre_trend.n == 5
    assert len(fr.block_pairs) >= 2 and all(z is None or abs(z) < 5 for *_, z in fr.block_pairs)


# ---- the 9x3 as a gas x feed surface (the Phase 4b set-up) ---------------------------------------------------

@pytest.fixture(scope="module")
def l9_world():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        fakes.make_measured_l9x3(root / "src")
        runs = rd.load_runs(rd.find_runs([root / "src" / "2026"]).runs, check_reuse=False)
        design = rsm.from_runs(runs)
        det = design.detect()
        L = rr.load(det, design.base.runs)
        a = rr.analyse(L, axis=["sccm", "sps"], nuisance={"rpm": "quadratic"})
        b = rr.analyse(L, axis=["sccm", "sps"])
        yield {"det": det, "a": a, "b": b}


def test_the_9x3_gas_x_feed_surface_with_rpm_as_nuisance(l9_world):
    a = l9_world["a"]
    assert l9_world["det"].type_key == "oa"
    assert a.terms == ["1", "sccm", "sps", "sccm*sps", "sccm^2", "sps^2", "rpm", "rpm^2"]
    f = a.fits["d32"].full
    assert f.n == 27 and f.lof.df_pe == 18 and f.lof.df_lof == 1
    corr = {(n, t): r for n, t, r in a.correlations}
    assert ("rpm", "sccm*sps") in corr and abs(corr[("rpm", "sccm*sps")]) > 0.3
    assert "rpm" in a.fits["d32"].reduced.terms and "rpm^2" in a.fits["d32"].reduced.terms


def test_the_9x3_without_rpm_pools_it_into_the_error(l9_world):
    b = l9_world["b"]
    assert b.terms == ["1", "sccm", "sps", "sccm*sps", "sccm^2", "sps^2"]
    assert any("pooled into the error" in w and "RPM" in w for w in b.warnings)
    assert b.fits["d32"].full.lof.df_lof == 27 - 6 - 18


@pytest.mark.skipif(not REAL_10_05.is_dir(), reason="LaCie not mounted")
def test_on_the_real_9x3_rpm_correlates_with_the_gas_x_feed_interaction():
    """The plan's number (checked 2026-10-11 by hand): r = -0.61 between RPM and the coded g*f term."""
    runs = rd.load_runs(sorted(p for p in REAL_10_05.iterdir() if p.is_dir()), check_reuse=False)
    det = rsm.from_runs(runs).detect()
    pts = [p for p in det.points if p.in_fit]
    x = {k: np.array([p.real[k] for p in pts]) for k in ("sccm", "sps", "rpm")}
    assert rs.correlation(x, "rpm", "sccm*sps") == pytest.approx(-0.61, abs=0.01)
