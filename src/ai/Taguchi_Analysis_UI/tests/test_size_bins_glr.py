"""Droplet size spread (% by count and by volume) and GLR."""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import covariates as cv
from src.ai.Taguchi_Analysis_UI import design as dz
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI import size_bins as sb
from src.ai.Taguchi_Analysis_UI import stats
from src.ai.Taguchi_Analysis_UI.tests import fakes

REAL_DAY = Path("/Volumes/LaCie/Experiments/2026/10/05")
REAL_01 = Path("/Volumes/LaCie/Experiments/2026/10/01")
needs_lacie = pytest.mark.skipif(not REAL_DAY.is_dir(), reason="LaCie not mounted")


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ---- bins --------------------------------------------------------------------------------

def test_default_bins_are_25um_to_200um_plus_an_open_bin():
    e = sb.make_edges()
    assert e[:-1] == [0, 25, 50, 75, 100, 125, 150, 175, 200] and math.isinf(e[-1])
    assert sb.make_labels(e) == ["<25", "25–50", "50–75", "75–100", "100–125",
                                 "125–150", "150–175", "175–200", ">200"]


def test_custom_and_uneven_widths():
    assert sb.make_edges(50, 200)[:-1] == [0, 50, 100, 150, 200]
    assert sb.make_edges(30, 100)[:-1] == [0, 30, 60, 90, 100]            # last bin closes at the max
    for bad in ((0, 200), (-5, 200), (50, 20)):
        with pytest.raises(ValueError):
            sb.make_edges(*bad)


def test_count_and_volume_shares_by_hand():
    s = sb.spread("r", [10, 20, 30, 210], sb.make_edges())
    assert s.counts == [2, 1, 0, 0, 0, 0, 0, 0, 1] and s.n == 4
    assert s.pct_count[0] == pytest.approx(50) and s.pct_count[-1] == pytest.approx(25)
    total = 10 ** 3 + 20 ** 3 + 30 ** 3 + 210 ** 3
    assert s.pct_volume[0] == pytest.approx(100 * (10 ** 3 + 20 ** 3) / total)
    assert s.pct_volume[-1] == pytest.approx(100 * 210 ** 3 / total)       # one big drop dominates volume
    assert sum(s.pct_count) == pytest.approx(100) and sum(s.pct_volume) == pytest.approx(100)


def test_an_edge_value_goes_in_the_bin_it_opens():
    s = sb.spread("r", [25.0, 50.0, 200.0], sb.make_edges())
    assert s.counts[1] == 1 and s.counts[2] == 1 and s.counts[-1] == 1


def test_an_empty_run_is_all_zeros_not_a_crash():
    s = sb.spread("r", [], sb.make_edges())
    assert s.n == 0 and sum(s.pct_count) == 0 and sum(s.pct_volume) == 0


def test_conditions_are_pooled_droplets_not_averaged_percentages():
    bins = sb.size_bins([("a", "T1", [10] * 9 + [60]), ("b", "T1", [60])])
    pooled = bins.conditions[0]
    assert pooled.n == 11 and pooled.pct_count[0] == pytest.approx(100 * 9 / 11)
    averaged = (bins.runs[0].pct_count[0] + bins.runs[1].pct_count[0]) / 2
    assert pooled.pct_count[0] != pytest.approx(averaged)                # 81.8% vs 45%


def test_tidy_tables_for_the_workbook():
    bins = sb.size_bins([("a", "T1", [10, 30]), ("b", "T2", [80])])
    rows = bins.table("volume", "run")
    assert rows[0]["run"] == "a" and rows[0]["condition"] == "T1" and rows[0]["droplets"] == 2
    assert set(bins.labels) <= set(rows[0]) and "50" in bins.caveat
    assert bins.table("count", "condition")[1]["condition"] == "T2"


def test_size_bins_from_an_analysed_campaign(tmp, monkeypatch):
    monkeypatch.setattr(spec.rdc_module("taguchi_analysis"), "N_BOOT", 50)
    fakes.make_measured_l9x3(tmp)
    d = dz.detect(rd.load_runs(rd.find_runs([tmp / "2026"]).runs, check_reuse=False))
    res = stats.analyse(d)
    bins = sb.from_results(res)
    assert len(bins.runs) == 27 and len(bins.conditions) == 9
    for s in bins.runs + bins.conditions:
        assert sum(s.pct_count) == pytest.approx(100) and sum(s.pct_volume) == pytest.approx(100)
    # bigger droplets at higher gas flow (built in) -> less of the volume in the small bins
    t1 = next(c for c in bins.conditions if c.name == "T1")              # 3000 sccm
    t3 = next(c for c in bins.conditions if c.name == "T3")              # 9000 sccm
    assert sum(t1.pct_volume[:3]) > sum(t3.pct_volume[:3])


@needs_lacie
@pytest.mark.skipif(not REAL_01.is_dir(), reason="10/01 not present")
def test_real_run_droplet_count_matches_its_own_summary():
    run = REAL_01 / "104852_3000sccm_300rpm_4000sps_or1.2_bh1"
    rec = stats.load_run_responses(run, 0.30, do_bootstrap=False)
    dia = np.concatenate([np.asarray(v) for v in rec["dia"].values()])
    s = sb.spread(run.name, dia, sb.make_edges())
    summ = json.loads((run / "shadowgraph/analysis/measurement_0.30/summary.json").read_text())
    assert s.n == summ["droplets_in_focus"]                               # 17480 in-focus droplets
    assert sum(s.pct_count) == pytest.approx(100) and sum(s.pct_volume) == pytest.approx(100)


# ---- GLR -------------------------------------------------------------------------------------------

def test_recorded_glr_is_used_when_present(tmp):
    info = rd.load_run_info(fakes.make_run(tmp, fakes.REAL_10_05[0][0]), check_reuse=False)
    c = cv.run_context(info)
    assert c.glr == pytest.approx(0.2819) and c.glr_source == "recorded"
    assert c.liquid_ml_min == pytest.approx(11.389, abs=1e-3)
    assert c.glr_achieved > c.glr                                          # achieved flow is ~3% higher
    assert c.fluid == "EcoFlex 00-30" and (c.rho_liquid, c.rho_gas) == (1070.0, 1.145)


def test_glr_is_computed_with_the_guis_formula_when_not_recorded(tmp):
    info = rd.load_run_info(fakes.make_run(tmp, fakes.REAL_10_05[0][0], omit=("GLR",)), check_reuse=False)
    c = cv.run_context(info)
    assert c.glr_source == "computed" and c.glr == pytest.approx(0.2819, abs=5e-5)


def test_without_densities_glr_is_missing_and_says_why(tmp):
    info = rd.load_run_info(fakes.make_run(tmp, fakes.REAL_10_05[0][0],
                                           omit=("GLR", "Liquid density (kg/m3)", "Gas density (kg/m3)")),
                            check_reuse=False)
    c = cv.run_context(info)
    assert c.glr is None and c.glr_source == "missing" and "no densities" in c.note


def test_the_glr_formula_really_is_the_guis(monkeypatch):
    """If the GUI changes its constants, the analysis must follow."""
    from src.ai.Taguchi_Analysis_UI import paths
    paths.ensure_src_on_path()
    import gui.GUI_Clean as G
    orig = G.AtomisationApp._glr_working
    monkeypatch.setattr(G.AtomisationApp, "_glr_working", lambda self: {"glr": 42.0, "ml_per_min": 1.0})
    assert cv.glr_working(3000, 4000, 1070, 1.145)["glr"] == 42.0
    monkeypatch.setattr(G.AtomisationApp, "_glr_working", orig)
    assert cv.glr_working(3000, 4000, 1070, 1.145)["glr"] == pytest.approx(0.2819, abs=5e-5)


def test_trend_recovers_a_known_power_law_and_correlation():
    x = [0.2, 0.3, 0.4, 0.6, 0.8]
    y = [2 * v ** 0.5 for v in x]
    t = cv.trend("d32", "glr", x, y, ["c"] * 5)
    assert t.exponent == pytest.approx(0.5) and t.r2_power == pytest.approx(1.0)
    from scipy.stats import pearsonr
    noisy = [v * (1 + 0.05 * s) for v, s in zip(y, (1, -1, 0.5, -0.5, 0))]
    t2 = cv.trend("d32", "glr", x, noisy, ["c"] * 5)
    r, p = pearsonr(x, noisy)
    assert t2.r == pytest.approx(r) and t2.p == pytest.approx(p, rel=1e-9)
    assert t2.exponent_ci95[0] < t2.exponent < t2.exponent_ci95[1]


def test_trend_degrades_gracefully():
    assert "fewer than 3" in cv.trend("a", "glr", [1, 2], [1, 2], ["c"] * 2).note
    assert "no spread" in cv.trend("a", "glr", [1, 1, 1], [1, 2, 3], ["c"] * 3).note
    t = cv.trend("intermit_pct", "glr", [0.2, 0.3, 0.4], [0.0, 1.0, 2.0], ["c"] * 3)
    assert t.r is not None and t.exponent is None and "power law not fitted" in t.note


def test_the_analysis_reports_glr_trends_and_warns_about_runs_without_glr(tmp, monkeypatch):
    monkeypatch.setattr(spec.rdc_module("taguchi_analysis"), "N_BOOT", 50)
    runs = fakes.make_measured_l9x3(tmp)
    d = dz.detect(rd.load_runs(rd.find_runs([tmp / "2026"]).runs, check_reuse=False))
    res = stats.analyse(d)
    t = res.trends[("atom", "glr")]
    assert t.n == 27 and t.r > 0.5 and t.p < 0.01 and len(t.points) == 27
    assert ("d32", "glr_achieved") in res.trends
    assert res.warnings == []
    for r in res.runs[:3]:
        r.context.glr = None
    res.trends = cv.trends(res.runs, stats.responses_table())
    assert res.trends[("atom", "glr")].n == 24


@needs_lacie
def test_real_10_05_every_glr_is_recorded_and_the_gui_formula_agrees():
    runs = rd.load_runs(rd.find_runs([REAL_DAY]).runs, check_reuse=False)
    for r in runs:
        c = cv.run_context(r)
        assert c.glr_source == "recorded"
        w = cv.glr_working(r.sccm, r.sps, c.rho_liquid, c.rho_gas)
        assert round(w["glr"], 4) == c.glr


@needs_lacie
@pytest.mark.skipif(not REAL_01.is_dir(), reason="10/01 not present")
def test_real_10_01_runs_have_no_glr_and_say_why():
    runs = rd.load_runs(rd.find_runs([REAL_01]).runs, check_reuse=False)
    ctx = [cv.run_context(r) for r in runs]
    assert all(c.glr is None and "no densities" in c.note for c in ctx)
