"""The generalised Taguchi statistics.

The strongest tests are at the bottom: the engine reproduces the PUBLISHED L9 analysis
(results_2026-10-01/taguchi_results.json) to 1e-9, both from its published values and
from the real run folders on the LaCie."""
from __future__ import annotations

import itertools
import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import design as dz
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI import stats
from src.ai.Taguchi_Analysis_UI.tests import fakes

PUBLISHED = Path("/Volumes/LaCie/Experiments/Taguchi/First Taguchi Trial (RPM, SCCM, Silicone Flow)"
                 "/results_2026-10-01/taguchi_results.json")
REAL_01 = Path("/Volumes/LaCie/Experiments/2026/10/01")
needs_pub = pytest.mark.skipif(not PUBLISHED.is_file(), reason="LaCie not mounted")
FACTORS3 = [dz.Factor(k, k, "attr", k) for k in ("sccm", "rpm", "sps")]
L9 = [(0, 0, 0), (1, 0, 1), (2, 0, 2), (0, 1, 1), (1, 1, 2), (2, 1, 0), (0, 2, 2), (1, 2, 0), (2, 2, 1)]


@pytest.fixture(autouse=True)
def fast_bootstrap(monkeypatch):
    ta = spec.rdc_module("taguchi_analysis")
    monkeypatch.setattr(ta, "N_BOOT", 100)


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def l9(reps=1, effect=(1.0, 0.0, 0.3), interaction=0.0, noise=0.1, seed=0):
    """(y, levels{a,b,c}, groups) for an L9 with `reps` replicates."""
    rng = np.random.default_rng(seed)
    y, lv, g = [], {"a": [], "b": [], "c": []}, []
    for ci, (i, j, k) in enumerate(L9):
        for _ in range(reps):
            y.append(10 + effect[0] * i + effect[1] * j + effect[2] * k
                     + interaction * (i - 1) * (j - 1) + rng.normal(0, noise))
            lv["a"].append(i); lv["b"].append(j); lv["c"].append(k)
            g.append(ci)
    return y, lv, g


# ---- the F distribution and multiple comparisons ---------------------------------------------

@pytest.mark.parametrize("F,d1,d2", [(0.5, 1, 5), (3.2, 2, 18), (8.73, 2, 2), (1.0, 4, 20),
                                     (12.0, 3, 9), (0.01, 2, 6), (40.0, 1, 30), (2.5, 6, 100)])
def test_pure_python_f_tail_agrees_with_scipy(F, d1, d2):
    from scipy.stats import f
    assert stats._betainc(d2 / 2, d1 / 2, d2 / (d2 + d1 * F)) == pytest.approx(f.sf(F, d1, d2), abs=1e-10)
    assert stats.f_sf(F, d1, d2) == pytest.approx(f.sf(F, d1, d2), abs=1e-12)


def test_f_tail_with_2_and_2_dof_is_the_old_scripts_closed_form():
    for F in (0.3, 1.0, 8.730567523480348, 576.6):
        assert stats.f_sf(F, 2, 2) == pytest.approx(1 / (1 + F), abs=1e-12)


def test_f_tail_edges():
    assert stats.f_sf(math.inf, 2, 5) == 0.0 and stats.f_sf(0.0, 2, 5) == 1.0


def test_f_tail_falls_back_without_scipy(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_scipy(name, *a, **k):
        if name.startswith("scipy"):
            raise ImportError("no scipy")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_scipy)
    assert stats.f_sf(3.2, 2, 18) == pytest.approx(0.0645, abs=1e-3)


def test_benjamini_hochberg():
    p = [0.01, 0.04, 0.03, 0.20]
    q = stats.benjamini_hochberg(p)
    # sorted 0.01 0.03 0.04 0.20 -> p*m/rank 0.04 0.06 0.0533 0.20 -> running min from the top
    assert q == pytest.approx([0.04, 0.16 / 3, 0.16 / 3, 0.20], abs=1e-12)
    assert all(qq >= pp for pp, qq in zip(p, q)) and stats.benjamini_hochberg([]) == []


# ---- ANOVA: the classic formula, partitions, error terms ------------------------------------------

def test_balanced_type_ii_ss_equals_the_classic_taguchi_formula():
    y, lv, g = l9(reps=3, seed=1)
    a = stats.anova(y, lv, g)
    for k in "abc":
        assert a.rows[k].ss == pytest.approx(stats.classic_ss(y, lv[k]), abs=1e-9)
        assert a.rows[k].df == 2


def test_replicated_l9_partitions_into_factors_lack_of_fit_and_pure_error():
    y, lv, g = l9(reps=3, seed=2)
    a = stats.anova(y, lv, g)
    assert a.error_source == "pure error" and a.error.df == 18 and a.lack_of_fit.df == 2
    total = sum(a.rows[k].ss for k in "abc") + a.lack_of_fit.ss + a.error.ss
    assert total == pytest.approx(a.total_ss, abs=1e-9)
    assert a.rows["a"].p < 1e-6 and a.rows["b"].p > 0.01                 # strong vs absent effect


def test_unreplicated_l9_uses_the_residual_the_old_unassigned_column():
    y, lv, g = l9(reps=1, seed=3)
    a = stats.anova(y, lv, g)
    assert a.error_source == "residual" and a.error.df == 2 and a.lack_of_fit is None
    assert a.error.ss == pytest.approx(a.total_ss - sum(a.rows[k].ss for k in "abc"), abs=1e-9)


def test_a_saturated_design_shows_effects_but_no_p_values():
    y, lv, g = l9(reps=1)
    lv["d"] = [(i + 2 * j) % 3 for i, j in zip(lv["a"], lv["b"])]          # the 4th L9 column
    a = stats.anova(y, lv, g)
    assert a.error_source == "none" and a.error is None
    assert all(a.rows[k].ss is not None and a.rows[k].p is None for k in "abcd")


def test_lack_of_fit_detects_an_interaction_only_replicates_can_see():
    y, lv, g = l9(reps=3, interaction=1.5, noise=0.1, seed=4)
    assert stats.anova(y, lv, g).lack_of_fit.p < 0.001
    y, lv, g = l9(reps=3, interaction=0.0, noise=0.1, seed=4)
    assert stats.anova(y, lv, g).lack_of_fit.p > 0.05


def test_unbalanced_type_ii_matches_an_independent_dummy_coded_computation():
    y, lv, g = l9(reps=3, seed=5)
    drop = [0, 1, 9]                                  # uneven replication
    y = [v for i, v in enumerate(y) if i not in drop]
    lv = {k: [v for i, v in enumerate(vals) if i not in drop] for k, vals in lv.items()}
    g = [v for i, v in enumerate(g) if i not in drop]
    a = stats.anova(y, lv, g)

    def rss(keys):                                    # treatment coding: a DIFFERENT basis
        cols = [np.ones(len(y))]
        for k in keys:
            for level in sorted(set(lv[k]))[1:]:
                cols.append(np.array([1.0 if x == level else 0.0 for x in lv[k]]))
        X = np.column_stack(cols)
        beta, *_ = np.linalg.lstsq(X, np.array(y), rcond=None)
        r = np.array(y) - X @ beta
        return float(r @ r)
    for k in "abc":
        others = [o for o in "abc" if o != k]
        assert a.rows[k].ss == pytest.approx(rss(others) - rss(list("abc")), abs=1e-9)
        assert a.rows[k].ss != pytest.approx(stats.classic_ss(y, lv[k]), abs=1e-6)  # really unbalanced


def test_a_factor_that_mirrors_another_is_not_estimable():
    y, lv, g = l9(reps=2)
    lv["copy"] = list(lv["a"])
    a = stats.anova(y, lv, g)
    assert a.rows["copy"].ss is None and a.rows["copy"].p is None and "not estimable" in a.rows["copy"].note
    assert a.rows["a"].ss is None                     # and neither is the one it copies


def test_a_level_seen_with_only_one_other_level_is_partly_aliased():
    y, lv, g = l9(reps=1)
    y.append(20.0); lv["a"].append(3); lv["b"].append(3); lv["c"].append(1); g.append(99)
    est = stats.estimability(lv)
    assert est["a"] == (2, 3) and est["b"] == (2, 3) and est["c"] == (2, 2)
    a = stats.anova(y, lv, g)
    assert a.rows["a"].df == 2 and "partly aliased" in a.rows["a"].note


def test_pooled_contribution_subtracts_the_error_and_never_goes_negative():
    y, lv, g = l9(reps=3, effect=(1.0, 0.0, 0.0), seed=6)
    a = stats.anova(y, lv, g)
    r = a.rows["b"]
    assert r.pooled_contribution_pct >= 0
    assert r.pooled_contribution_pct <= r.contribution_pct
    big = a.rows["a"]
    assert big.pooled_contribution_pct == pytest.approx(
        100 * (big.ss - big.df * a.error.ms) / a.total_ss)


# ---- S/N -----------------------------------------------------------------------------------------------

def test_sn_with_one_value_is_the_old_plus_minus_20_log10():
    assert stats.sn_ratio([90.0], "smaller") == pytest.approx(-20 * math.log10(90.0))
    assert stats.sn_ratio([8.0], "larger") == pytest.approx(20 * math.log10(8.0))


def test_sn_with_replicates_uses_the_taguchi_forms():
    v = [88.0, 90.0, 93.0]
    assert stats.sn_ratio(v, "smaller") == pytest.approx(-10 * math.log10(np.mean(np.square(v))))
    assert stats.sn_ratio(v, "larger") == pytest.approx(-10 * math.log10(np.mean(1 / np.square(v))))


def test_sn_is_undefined_at_or_below_zero():
    assert stats.sn_ratio([0.0, 1.0], "smaller") is None and stats.sn_ratio([-1.0], "larger") is None
    assert stats.sn_ratio([], "smaller") is None


# ---- analyse_values: effects, degenerate responses, outliers ----------------------------------------------

def records(y, lv, g, key="d32"):
    return [stats.RunRecord(f"r{i}", Path(f"r{i}"), f"C{gi}", 1,
                            {k: lv[k][i] for k in lv}, {key: v}, {}, "2.1.0", 10)
            for i, (v, gi) in enumerate(zip(y, g))]


RESP = [("d32", "D32", "smaller", False)]
FAC = [dz.Factor(k, k, "attr", k) for k in "abc"]


def test_main_effects_level_means_and_their_standard_error():
    y, lv, g = l9(reps=3, seed=7)
    res = stats.analyse_values(records(y, lv, g), FAC, RESP, with_bootstrap=False)["d32"]
    for eff in res.effects["a"]:
        vals = [v for v, x in zip(y, lv["a"]) if x == eff.level]
        assert eff.mean == pytest.approx(np.mean(vals)) and eff.n == 9
        assert eff.se == pytest.approx(math.sqrt(res.anova.error.ms / 9))


def test_bootstrap_confidence_intervals_come_from_the_runs_bootstrap_draws():
    y, lv, g = l9(reps=1)
    recs = records(y, lv, g)
    for r, v in zip(recs, y):
        r.rec = {"boot_d32": np.full(50, v) + np.linspace(-1, 1, 50)}
    res = stats.analyse_values(recs, FAC, RESP, with_bootstrap=True)["d32"]
    lo, hi = res.effects["a"][0].ci95
    assert lo < res.effects["a"][0].mean < hi


def test_a_constant_response_is_degenerate_not_significant():
    y, lv, g = l9(reps=1)
    res = stats.analyse_values(records([22.568] * 9, lv, g), FAC, RESP, with_bootstrap=False)["d32"]
    assert res.degenerate and res.anova is None


def test_few_distinct_values_raise_the_quantisation_warning():
    y, lv, g = l9(reps=1)
    vals = [22.6, 22.6, 45.1, 45.1, 45.1, 67.7, 22.6, 45.1, 67.7]
    res = stats.analyse_values(records(vals, lv, g), FAC, RESP, with_bootstrap=False)["d32"]
    assert res.n_distinct == 3 and res.quantisation_warning


def test_non_finite_values_are_left_out_of_that_response_only():
    y, lv, g = l9(reps=3, seed=8)
    y[0] = float("nan")
    res = stats.analyse_values(records(y, lv, g), FAC, RESP, with_bootstrap=False)["d32"]
    assert res.n_used == 26 and res.anova.n == 26


def test_a_wild_replicate_is_flagged_and_clean_data_flags_nothing():
    y, lv, g = l9(reps=3, noise=0.1, seed=9)
    clean = stats.analyse_values(records(y, lv, g), FAC, RESP, with_bootstrap=False)["d32"]
    assert clean.outliers == []
    y[4] += 2.5
    wild = stats.analyse_values(records(y, lv, g), FAC, RESP, with_bootstrap=False)["d32"]
    assert [o["run"] for o in wild.outliers] == ["r4"] and abs(wild.outliers[0]["z"]) > stats.OUTLIER_Z


def test_sn_level_means_and_sn_anova_use_one_value_per_condition():
    y, lv, g = l9(reps=3, seed=10)
    res = stats.analyse_values(records(y, lv, g), FAC, RESP, with_bootstrap=False)["d32"]
    assert res.sn_defined and len(res.sn_by_condition) == 9
    assert res.sn_anova.n == 9 and res.sn_anova.error_source == "residual"


def test_sn_undefined_for_a_response_that_reaches_zero():
    y, lv, g = l9(reps=1)
    y[0] = 0.0
    recs = records(y, lv, g, key="intermit_pct")
    r = stats.analyse_values(recs, FAC, [("intermit_pct", "x", "smaller", False)], with_bootstrap=False)["intermit_pct"]
    assert not r.sn_defined and "not defined" in r.sn_note and r.anova is not None


def test_multiple_comparisons_cover_every_test_and_q_is_at_least_p():
    y, lv, g = l9(reps=3, seed=11)
    resp = {"d32": stats.analyse_values(records(y, lv, g), FAC, RESP, with_bootstrap=False)["d32"]}
    mc = stats.multiple_comparisons(resp, FAC)
    assert len(mc) == 3 and all(q >= p for _, _, p, q in mc)


# ---- analyse(): whole campaigns from run folders ---------------------------------------------------------------

def campaign(tmp, **kw):
    fakes.make_measured_l9x3(tmp, **kw)
    return dz.detect(rd.load_runs(rd.find_runs([tmp / "2026"]).runs, check_reuse=False))


def test_a_replicated_campaign_recovers_the_built_in_effects(tmp):
    res = stats.analyse(campaign(tmp))
    assert res.refused is None and len(res.runs) == 27 and res.skipped == []
    assert res.error_source == "pure error" and res.n_conditions == 9
    d32, atom = res.responses["d32"].anova, res.responses["atom"].anova
    assert d32.error.df == 18
    assert d32.rows["sccm"].p < 1e-4 and atom.rows["sccm"].p < 1e-6     # built in: strong
    assert d32.rows["rpm"].p > 0.05 and atom.rows["rpm"].p > 0.05      # built in: none
    assert d32.lack_of_fit.p > 0.05                                     # built in: no interaction
    assert len(res.multiple) == 3 * sum(1 for r in res.responses.values() if r.anova)


def test_a_built_in_interaction_shows_up_as_lack_of_fit(tmp):
    res = stats.analyse(campaign(tmp, interaction=0.25, replicate_sd=0.01, per_frame=200))
    assert res.responses["d32"].anova.lack_of_fit.p < 0.01


def test_mixed_sizer_versions_are_refused(tmp):
    d = campaign(tmp)
    run = d.rows[0].path
    summ = run / "shadowgraph/analysis/droplets_0.30/summary.json"
    s = json.loads(summ.read_text()); s["provenance"]["sizer_version"] = "2.0.0"
    summ.write_text(json.dumps(s))
    res = stats.analyse(d)
    assert res.refused and "different sizer versions" in res.refused and "2.0.0" in res.refused
    assert res.responses == {}


def test_a_run_failing_load_runs_own_check_is_skipped_with_its_reason(tmp):
    d = campaign(tmp)
    summ = d.rows[0].path / "shadowgraph/analysis/droplets_0.30/summary.json"
    s = json.loads(summ.read_text()); s["d32_in_focus_um"] += 5.0       # disagrees with the CSV
    summ.write_text(json.dumps(s))
    res = stats.analyse(d)
    assert len(res.runs) == 26
    name, why = next((n, w) for n, w in res.skipped if n == d.rows[0].name)
    assert "cannot be read" in why and "D32 re-derived" in why          # load_run's refusal, kept


def test_unmeasured_dropped_and_unassigned_runs_are_skipped(tmp):
    d = campaign(tmp)
    fresh = fakes.make_run(tmp / "x", "130000_3000sccm_300rpm_4000sps_or1.2_bh1", notes="Taguchi ReRun 1 - Repeat 4")
    d.update_runs(list(d.runs.values()) + [rd.load_run_info(fresh, check_reuse=False)])
    d.rows[1].included = False
    d.rows[2].detected["rpm"] = None
    res = stats.analyse(d)
    why = dict(res.skipped)
    assert "not measured yet" in why[fresh.name]
    assert why[d.rows[1].name] == "left out" and why[d.rows[2].name] == "no complete factor levels"
    assert len(res.runs) == 25


def test_a_nobh_style_folder_name_does_not_stop_load_run(tmp):
    import numpy as np
    run = fakes.make_run(tmp, "101035_4500sccm_500rpm_6000sps_or1.2_nobh", notes="")
    fakes.write_results(run, np.random.default_rng(0), 50, 0.1)
    rec = stats.load_run_responses(run, 0.30, do_bootstrap=False)
    assert rec["d32"] > 0
    ta = spec.rdc_module("taguchi_analysis")
    with pytest.raises(SystemExit):                    # the real parse_levels is back afterwards
        ta.parse_levels("not_a_run")


def test_parse_levels_is_restored_even_when_load_run_fails(tmp):
    ta = spec.rdc_module("taguchi_analysis")
    original = ta.parse_levels
    with pytest.raises(stats.RunLoadError):
        stats.load_run_responses(tmp / "nowhere", 0.30, do_bootstrap=False)
    assert ta.parse_levels is original


def test_too_little_to_analyse_is_refused(tmp):
    d = campaign(tmp)
    for r in d.rows[1:]:
        r.included = False
    assert "nothing to analyse" in stats.analyse(d).refused


# ---- the published L9: exact reproduction -----------------------------------------------------------------

def _published():
    return json.loads(PUBLISHED.read_text())


def _check_against_published(out, pub):
    worst = 0.0
    for key in ("d32", "atom"):
        a = out[key].anova
        assert a.error_source == "residual" and a.error.df == 2
        for f in ("sccm", "rpm", "sps"):
            P, M = pub["results"][key]["anova"][f], a.rows[f]
            for mine, theirs in ((M.ss, P["SS"]), (M.F, P["F"]), (M.p, P["p"]),
                                 (M.contribution_pct, P["contribution_pct"])):
                worst = max(worst, abs(mine - theirs))
            for e, lm in zip(out[key].effects[f], pub["results"][key]["noise_test"][f]["level_means"]):
                worst = max(worst, abs(e.mean - lm))
            for level, sn in pub["results"][key]["sn_level_means"][f].items():
                worst = max(worst, abs(out[key].sn_effects[f][int(level)] - sn))
        PE = pub["results"][key]["anova"]["error"]
        worst = max(worst, abs(a.error.ss - PE["SS"]), abs(a.error.contribution_pct - PE["contribution_pct"]))
    return worst


@needs_pub
def test_published_l9_reproduced_exactly_from_its_values():
    pub = _published()
    runs = [stats.RunRecord(r["run"], Path(r["run"]), r["run"][:6], 1, r["levels"],
                            {"d32": r["d32_um"], "atom": r["atomised_pct_classical"]}, {}, None, 497)
            for r in pub["runs"]]
    out = stats.analyse_values(runs, FACTORS3, [("d32", "", "smaller", False), ("atom", "", "larger", False)],
                               with_bootstrap=False)
    assert _check_against_published(out, pub) < 1e-9


@needs_pub
@pytest.mark.skipif(not REAL_01.is_dir(), reason="10/01 not present")
def test_published_l9_reproduced_exactly_from_the_real_run_folders():
    """End to end: discovery -> design (side runs left out) -> load_run on the real 10/01
    folders (legacy names, pre-2.0.0) -> the ANOVA. Must equal what was published."""
    pub = _published()
    d = dz.detect(rd.load_runs(rd.find_runs([REAL_01]).runs, check_reuse=False))
    for r in dz.outside_design(d):
        r.included = False
    res = stats.analyse(d, do_bootstrap=False)
    assert res.refused is None and len(res.runs) == 9
    by_name = {r["run"]: r for r in pub["runs"]}
    for r in res.runs:
        assert r.values["d32"] == pytest.approx(by_name[r.name]["d32_um"], abs=1e-12)
    assert _check_against_published(res.responses, pub) < 1e-9
