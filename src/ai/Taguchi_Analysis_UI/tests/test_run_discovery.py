"""Tests for run_discovery, on fakes that mirror the real 2026/10/05 format
(see fakes.py and test_fakes_fidelity.py), plus read-only checks against the
real data when the LaCie is mounted."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI.tests import fakes

REAL_DAY = Path("/Volumes/LaCie/Experiments/2026/10/05")
REAL_01 = Path("/Volumes/LaCie/Experiments/2026/10/01")
needs_lacie = pytest.mark.skipif(not REAL_DAY.is_dir(), reason="LaCie not mounted")
FIRST = fakes.REAL_10_05[0][0]


@pytest.fixture
def root():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


# ---- xlsx value coercion ----------------------------------------------------

@pytest.mark.parametrize("raw,number,rng,unit", [
    ("300", 300.0, None, ""),
    (390, 390.0, None, ""),
    (0.2819, 0.2819, None, ""),
    ("1.2mm", 1.2, None, "mm"),
    ("1.145", 1.145, None, ""),
    ("1070", 1070.0, None, ""),
    ("0–3086 sccm", None, (0.0, 3086.0), "sccm"),          # en-dash, as in the real files
    ("1.01–2.38 barA", None, (1.01, 2.38), "barA"),
    ("0-3086 sccm", None, (0.0, 3086.0), "sccm"),               # plain hyphen
    ("0—3086", None, (0.0, 3086.0), ""),                   # em-dash
    ("-5", -5.0, None, ""),                                     # negative is not a range
    ("1e-3", 0.001, None, ""),                                  # exponent is not a range
    ("1070 kg/m3", 1070.0, None, "kg/m3"),
])
def test_coerce_numbers_and_ranges(raw, number, rng, unit):
    v = rd.coerce_value(raw)
    assert (v.number, v.range, v.unit) == (number, rng, unit)
    assert v.missing is None


@pytest.mark.parametrize("raw", [None, "", "  ", "NOT RECORDED", "not set", "N/A", "unknown"])
def test_coerce_unrecorded_values(raw):
    v = rd.coerce_value(raw)
    assert v.missing is not None
    assert v.number is None and v.range is None


def test_coerce_plain_text_keeps_text_and_no_number():
    v = rd.coerce_value("EcoFlex 00-30")
    assert v.text == "EcoFlex 00-30" and v.number is None and v.range is None and not v.missing


def test_pick_takes_max_of_a_range_by_default():
    v = rd.coerce_value("0–3086 sccm")
    assert (v.pick(), v.pick("min"), v.pick("mean")) == (3086.0, 0.0, 1543.0)
    assert rd.coerce_value("300").pick() == 300.0
    assert rd.coerce_value("EcoFlex").pick() is None


# ---- one run ----------------------------------------------------------------

def test_a_fresh_capture_like_10_05(root):
    run = fakes.make_run(root, FIRST, notes="Taguchi ReRun 1 - Repeat 1\nWITH NOZZLE ADAPTER")
    info = rd.load_run_info(run)
    assert info.name_ok and info.runnable and info.usable and not info.analysable
    assert (info.sccm, info.rpm, info.sps, info.orifice_mm, info.bubbler_height) == \
           (3000, 300, 4000, 1.2, 1)
    assert info.sources == {"sccm": "name", "rpm": "workbook", "sps": "workbook",
                            "orifice_mm": "workbook", "bubbler_height": "workbook"}
    assert info.time == "090432" and info.date == "2026-10-05"
    assert info.cine.name == "recording_090506.cine"
    assert info.fps == 390.0 and info.flow_achieved_sccm == 3090.0
    assert info.notes.startswith("Taguchi ReRun 1 - Repeat 1")
    assert info.analysis.label == "new"
    assert info.issues == []                      # a real 10/05 run is clean
    assert info.condition_key == (3000, 300, 4000, 1.2, 1)
    assert info.label == "2026-10-05  090432   3000 sccm · 300 rpm · 4000 sps"


def test_missing_xlsx_warns_but_is_still_runnable(root):
    info = rd.load_run_info(fakes.make_run(root, FIRST, xlsx=False))
    assert info.runnable and info.errors == []
    assert any("run_summary.xlsx" in w.message for w in info.warnings)
    assert info.date == "2026-10-05"              # falls back to the path


def test_unreadable_xlsx_warns_and_does_not_crash(root):
    run = fakes.make_run(root, FIRST)
    (run / "run_summary.xlsx").write_bytes(b"this is not a workbook")
    info = rd.load_run_info(run)
    assert info.runnable and info.errors == []
    assert any("unreadable" in w.message for w in info.warnings)


def test_xlsx_without_metadata_sheet_warns(root):
    import openpyxl
    run = fakes.make_run(root, FIRST)
    wb = openpyxl.Workbook(); wb.active.title = "Other"; wb.save(run / "run_summary.xlsx")
    info = rd.load_run_info(run)
    assert any("Metadata" in w.message for w in info.warnings)


def test_older_runs_missing_glr_fluid_are_fine(root):
    # 10 of the real runs (10/01) lack GLR/Fluid/densities.
    run = fakes.make_run(root, FIRST, omit=("GLR", "Fluid", "Liquid density (kg/m3)",
                                            "Gas", "Gas density (kg/m3)"))
    info = rd.load_run_info(run)
    assert info.issues == [] and "GLR" not in info.meta and info.fps == 390.0


def test_fps_800_is_read(root):
    assert rd.load_run_info(fakes.make_run(root, FIRST, fps=800)).fps == 800.0


def test_no_cine_is_an_error_unless_already_measured(root):
    bare = rd.load_run_info(fakes.make_run(root, FIRST, cines=0))
    assert not bare.runnable and not bare.usable
    assert any(i.level == "error" and ".cine" in i.message for i in bare.issues)

    measured = rd.load_run_info(fakes.make_run(
        root, fakes.REAL_10_05[1][0], cines=0, analysis="current"))
    assert not measured.runnable and measured.analysable and measured.usable
    assert measured.errors == [] and any(".cine" in w.message for w in measured.warnings)


def test_two_cines_is_an_error(root):
    info = rd.load_run_info(fakes.make_run(root, FIRST, cines=2))
    assert not info.runnable and info.n_cines == 2
    assert any("2 .cine" in i.message for i in info.errors)


def test_appledouble_sidecar_cine_is_ignored(root):
    run = fakes.make_run(root, FIRST)
    (run / "shadowgraph" / "raw" / "CINE" / "._recording_090506.cine").touch()
    info = rd.load_run_info(run)
    assert info.n_cines == 1 and info.runnable


def test_bad_folder_name_is_an_error(root):
    run = root / "110302_N6_1.0BAR"
    (run / "shadowgraph").mkdir(parents=True)
    info = rd.load_run_info(run)
    assert not info.name_ok and info.condition_key is None
    assert any("not <HHMMSS>" in i.message for i in info.errors)


def test_nonexistent_folder_is_an_error_not_a_crash(root):
    info = rd.load_run_info(root / "090432_3000sccm_300rpm_4000sps_or1.2_bh1")
    assert any("does not exist" in i.message for i in info.errors)


def test_folder_name_disagreeing_with_xlsx_warns(root):
    run = fakes.make_run(root, FIRST, overrides={"Bubbler RPM": "600"})
    info = rd.load_run_info(run)
    msgs = [w.message for w in info.warnings]
    assert any("rpm 300" in m and "600" in m and "workbook" in m for m in msgs), msgs
    assert info.rpm == 600 and info.sources["rpm"] == "workbook"     # the workbook is authoritative


def test_big_flow_drift_warns_but_normal_drift_does_not(root):
    normal = rd.load_run_info(fakes.make_run(root, FIRST))        # +3%, like the real runs
    assert normal.warnings == []
    off = rd.load_run_info(fakes.make_run(
        root, fakes.REAL_10_05[1][0], overrides={"Flow Range (sccm)": "0–6000 sccm"}))
    assert any("achieved flow" in w.message for w in off.warnings)


# ---- analysis state ---------------------------------------------------------

def test_measured_under_current_names(root):
    s = rd.load_run_info(fakes.make_run(root, FIRST, analysis="current")).analysis
    assert s.measured and not s.legacy_names and s.sizer_version == "2.1.0"
    assert s.label == "measured v2.1.0"


def test_measured_under_legacy_names_like_10_01(root):
    s = rd.load_run_info(fakes.make_run(root, FIRST, analysis="legacy",
                                        sizer_version=None)).analysis
    assert s.measured and s.legacy_names and s.sizer_version is None
    assert s.label == "measured pre-2.0.0 \u00b7 legacy folders"


def test_droplets_only_is_its_own_state_not_new(root):
    # like the real 10/01 ..._nobh run: measurement_0.30 exists, classical_0.30 does not
    run = fakes.make_run(root, FIRST, analysis="legacy")
    import shutil
    shutil.rmtree(run / "shadowgraph" / "analysis" / "classical_0.30")
    s = rd.load_run_info(run).analysis
    assert not s.measured and s.droplets_only
    assert s.label == "droplets measured, no classical stage"
    assert not rd.load_run_info(run).analysable          # the statistics need both


def test_nothing_measured_is_new_not_droplets_only(root):
    s = rd.load_run_info(fakes.make_run(root, FIRST)).analysis
    assert not s.measured and not s.droplets_only and s.label == "new"


def test_half_measured_is_not_measured(root):
    run = fakes.make_run(root, FIRST, analysis="current")
    (run / "shadowgraph" / "analysis" / "liquid_0.30" / "classical_summary.json").unlink()
    assert not rd.load_run_info(run).analysis.measured


def test_other_threshold_is_not_this_threshold(root):
    run = fakes.make_run(root, FIRST, analysis="current", thr=0.30)
    assert rd.load_run_info(run, thr=0.30).analysis.measured
    assert not rd.load_run_info(run, thr=0.45).analysis.measured


# ---- finding runs -----------------------------------------------------------

def test_find_runs_in_a_day_folder_keeps_chronological_order(root):
    fakes.make_l9x3(root)
    res = rd.find_runs([root / "2026" / "10" / "05"])
    assert len(res.runs) == 27 and res.skipped == []
    assert [p.name for p in res.runs] == sorted(p.name for p in res.runs)


def test_a_run_folder_given_directly_is_taken_as_is(root):
    run = fakes.make_run(root, FIRST)
    assert rd.find_runs([run]).runs == [run]


def test_runs_from_different_days_are_all_found_and_sorted_by_date(root):
    a = fakes.make_run(root, "104852_3000sccm_300rpm_4000sps_or1.2_bh1", day=("2026", "10", "01"))
    b = fakes.make_run(root, "090432_3000sccm_300rpm_4000sps_or1.2_bh1", day=("2026", "10", "05"))
    res = rd.find_runs([b, a])
    assert res.runs == [a, b]                      # 10/01 before 10/05 despite 104852 > 090432


def test_scanning_a_month_or_year_finds_everything_below(root):
    fakes.make_run(root, "104852_3000sccm_300rpm_4000sps_or1.2_bh1", day=("2026", "10", "01"))
    fakes.make_run(root, "090432_3000sccm_300rpm_4000sps_or1.2_bh1", day=("2026", "10", "05"))
    assert len(rd.find_runs([root / "2026" / "10"]).runs) == 2
    assert len(rd.find_runs([root / "2026"]).runs) == 2


def test_old_format_folders_are_reported_as_skipped_with_a_reason(root):
    fakes.make_run(root, FIRST)
    old = root / "2026" / "10" / "05" / "110302_N6_1.0BAR"
    (old / "shadowgraph").mkdir(parents=True)
    res = rd.find_runs([root / "2026" / "10" / "05"])
    assert [p.name for p in res.runs] == [FIRST]
    assert [(p.name, "name is not" in why) for p, why in res.skipped] == [("110302_N6_1.0BAR", True)]


def test_unrelated_folders_are_ignored_quietly(root):
    fakes.make_run(root, FIRST)
    (root / "2026" / "10" / "05" / "notes").mkdir()
    assert rd.find_runs([root / "2026" / "10" / "05"]).skipped == []


def test_duplicates_are_collapsed(root):
    run = fakes.make_run(root, FIRST)
    assert rd.find_runs([run, run, run.parent]).runs == [run]


def test_hidden_folders_are_ignored(root):
    fakes.make_run(root, FIRST)
    fakes.make_run(root / "2026" / "10" / "05" / ".Trash", "091303_3000sccm_300rpm_4000sps_or1.2_bh1",
                   flat=True)
    assert len(rd.find_runs([root / "2026" / "10" / "05"]).runs) == 1


def test_does_not_descend_into_run_folders(root, monkeypatch):
    run = fakes.make_run(root, FIRST)
    visited = []
    real = rd._subdirs
    monkeypatch.setattr(rd, "_subdirs", lambda p: (visited.append(p), real(p))[1])
    rd.find_runs([run.parent])
    assert run not in visited and not any(run in p.parents for p in visited)


def test_missing_root_is_reported_not_raised(root):
    res = rd.find_runs([root / "nope"])
    assert res.runs == [] and res.skipped[0][1] == "not a folder"


# ---- summary ----------------------------------------------------------------

def test_scan_depth_reaches_runs_from_a_year_folder_but_not_from_experiments(root):
    # Documented contract: pick a year, month, day or run folder. Experiments/
    # itself is 4 levels above the runs, so a default scan finds nothing there --
    # the UI must say so rather than show an empty list.
    fakes.make_run(root, FIRST)
    assert len(rd.find_runs([root / "2026"]).runs) == 1
    assert rd.find_runs([root]).runs == []
    assert len(rd.find_runs([root], max_depth=4).runs) == 1


def test_summary_of_a_clean_9x3(root):
    fakes.make_l9x3(root)
    runs = rd.load_runs(rd.find_runs([root / "2026"]).runs)
    s = rd.summarise(runs)
    assert (s.n_runs, s.n_conditions, s.n_usable, s.n_errors, s.n_measured, s.n_days) == \
           (27, 9, 27, 0, 0, 1)
    assert set(s.replicates.values()) == {3}
    assert s.headline() == "27 runs · 9 conditions × 3 replicates · 0 already measured"


def test_summary_is_independent_of_folder_order(root):
    # 111625 (ReRun 5) sorts before 112253 (ReRun 4): grouping must use the factors.
    fakes.make_l9x3(root)
    runs = rd.load_runs(rd.find_runs([root / "2026"]).runs)
    assert len(rd.summarise(runs).replicates) == 9


def test_summary_flags_an_unbalanced_design(root):
    for name, _, _ in fakes.REAL_10_05[:-1]:                       # drop the last run
        fakes.make_run(root, name)
    s = rd.summarise(rd.load_runs(rd.find_runs([root / "2026"]).runs))
    assert sorted(set(s.replicates.values())) == [2, 3]
    assert "unbalanced" in s.headline()


def test_summary_counts_measured_and_errors_and_days(root):
    fakes.make_run(root, "104852_3000sccm_300rpm_4000sps_or1.2_bh1", day=("2026", "10", "01"),
                   analysis="legacy")
    fakes.make_run(root, "090432_3000sccm_300rpm_4000sps_or1.2_bh1", cines=0)
    s = rd.summarise(rd.load_runs(rd.find_runs([root / "2026"]).runs))
    assert (s.n_runs, s.n_measured, s.n_errors, s.n_days) == (2, 1, 1, 2)
    assert "2 days" in s.headline() and "1 with errors" in s.headline()


def test_sizer_versions_flags_a_mixed_set(root):
    a = rd.load_run_info(fakes.make_run(root, FIRST, analysis="current", sizer_version="2.0.0"))
    b = rd.load_run_info(fakes.make_run(root, fakes.REAL_10_05[1][0], analysis="current",
                                        sizer_version="2.1.0"))
    c = rd.load_run_info(fakes.make_run(root, fakes.REAL_10_05[2][0]))        # not measured
    assert rd.sizer_versions([a]) == {"2.0.0"}
    assert rd.sizer_versions([a, b, c]) == {"2.0.0", "2.1.0"}               # c is ignored
    assert rd.sizer_versions([c]) == set()


def test_progress_callback_is_called_once_per_run(root):
    fakes.make_l9x3(root)
    seen = []
    rd.load_runs(rd.find_runs([root / "2026"]).runs, progress=lambda i, n, r: seen.append((i, n)))
    assert seen[0] == (1, 27) and seen[-1] == (27, 27) and len(seen) == 27


# ---- the real folder-name grammar (GUI_Clean._run_id) ---------------------------

@pytest.mark.parametrize("name,expected", [
    ("090432_3000sccm_300rpm_4000sps_or1.2_bh1",
     dict(sccm=3000.0, rpm=300.0, sps=4000.0, orifice_mm=1.2, bubbler_height=1.0)),
    ("101035_4500sccm_500rpm_6000sps_or1.2_nobh",                 # the real 10/01 run
     dict(sccm=4500.0, rpm=500.0, sps=6000.0, orifice_mm=1.2, bubbler_height=None)),
    ("101035_4500sccm_norpm_nosps_noor_nobh",
     dict(sccm=4500.0, rpm=None, sps=None, orifice_mm=None, bubbler_height=None)),
    ("101035_?sccm_300rpm_4000sps_or1.2_bh40",
     dict(sccm=None, rpm=300.0, sps=4000.0, orifice_mm=1.2, bubbler_height=40.0)),
    ("101035_unknownsccm_300rpm_4000sps_or1.2_bh1",
     dict(sccm=None, rpm=300.0, sps=4000.0, orifice_mm=1.2, bubbler_height=1.0)),
    ("101035_4500sccm_0.5rpm_6000sps_or0.8_bh2.5",
     dict(sccm=4500.0, rpm=0.5, sps=6000.0, orifice_mm=0.8, bubbler_height=2.5)),
])
def test_parse_run_name_accepts_the_real_grammar(name, expected):
    parsed = rd.parse_run_name(name)
    assert {k: parsed[k] for k in expected} == expected


@pytest.mark.parametrize("name", [
    "110302_N6_1.0BAR", "153116_N2_unknownBAR", "090432_3000sccm_300rpm_4000sps_or1.2",
    "90432_3000sccm_300rpm_4000sps_or1.2_bh1", "T1_104852_3000sccm_300rpm_4000sps",
    "090432_3000sccm_300rpm_4000sps_or1.2_bh1_extra", "notes", "",
])
def test_parse_run_name_rejects_other_names(name):
    assert rd.parse_run_name(name) is None


def test_workbook_fills_a_value_the_folder_name_lost(root):
    # The real 10/01 run 101035_..._nobh: name says nobh, workbook says bh = 1.
    run = fakes.make_run(root, "101035_4500sccm_500rpm_6000sps_or1.2_nobh",
                         day=("2026", "10", "01"), fps=800)
    info = rd.load_run_info(run)
    assert info.name_ok and info.runnable and info.errors == []
    assert info.bubbler_height == 1.0 and info.sources["bubbler_height"] == "workbook"
    assert info.sources["rpm"] == "workbook" and info.rpm == 500.0
    assert not any("bubbler height" in w.message for w in info.warnings)
    # ... so it is a replicate of a bh1 run, not a condition of its own
    twin = rd.load_run_info(fakes.make_run(
        root, "101040_4500sccm_500rpm_6000sps_or1.2_bh1", day=("2026", "10", "01")))
    assert info.condition_key == twin.condition_key


def test_a_value_in_neither_name_nor_workbook_is_warned(root):
    run = fakes.make_run(root, "101035_4500sccm_500rpm_6000sps_or1.2_nobh",
                         xlsx=False)
    msgs = [w.message for w in rd.load_run_info(run).warnings]
    assert any("bubbler height is not in the folder name or run_summary.xlsx" in m for m in msgs)


def test_unknown_flow_setpoint_is_warned_and_shown_as_a_question_mark(root):
    run = fakes.make_run(root, "101035_?sccm_500rpm_6000sps_or1.2_bh1")
    info = rd.load_run_info(run)
    assert info.sccm is None and "? sccm" in info.label
    assert any("no gas-flow setpoint" in w.message for w in info.warnings)


def test_find_runs_now_picks_up_nobh_style_folders(root):
    fakes.make_run(root, "101035_4500sccm_500rpm_6000sps_or1.2_nobh", day=("2026", "10", "01"))
    res = rd.find_runs([root / "2026" / "10" / "01"])
    assert [p.name for p in res.runs] == ["101035_4500sccm_500rpm_6000sps_or1.2_nobh"]
    assert res.skipped == []


# ---- real data, read-only ---------------------------------------------------

@needs_lacie
def test_real_10_05_is_a_clean_9x3():
    runs = rd.load_runs(rd.find_runs([REAL_DAY]).runs, check_reuse=False)
    s = rd.summarise(runs)
    assert (s.n_runs, s.n_conditions, s.n_errors, s.n_measured, s.n_days) == (27, 9, 0, 0, 1)
    assert set(s.replicates.values()) == {3}
    assert all(r.fps == 390.0 and r.runnable and r.issues == [] for r in runs), \
        [(r.name, r.issues) for r in runs if r.issues]


@needs_lacie
def test_real_10_05_discovery_agrees_with_the_fakes_table():
    runs = rd.find_runs([REAL_DAY]).runs
    assert [p.name for p in runs] == [n for n, _, _ in fakes.REAL_10_05]


@needs_lacie
@pytest.mark.skipif(not REAL_01.is_dir(), reason="10/01 not present")
def test_real_10_01_is_measured_under_legacy_names():
    runs = rd.load_runs(rd.find_runs([REAL_01]).runs, check_reuse=False)
    assert len(runs) >= 10
    # all but one are fully measured; the odd one out is the nobh run, which only
    # ever had the droplet stage (verified on disk: no classical_0.30 folder)
    full = [r for r in runs if r.analysis.measured]
    assert len(full) == len(runs) - 1 and all(r.analysis.legacy_names for r in full)
    odd = [r for r in runs if not r.analysis.measured]
    assert [r.name for r in odd] == ["101035_4500sccm_500rpm_6000sps_or1.2_nobh"]
    assert odd[0].analysis.droplets_only and odd[0].analysis.label == \
        "droplets measured, no classical stage"


@needs_lacie
def test_real_scan_across_days_finds_both_and_skips_old_format():
    res = rd.find_runs([REAL_DAY.parent.parent])                   # .../2026/10
    days = {p.parent.name for p in res.runs}
    assert {"01", "05"} <= days


@needs_lacie
def test_discovery_writes_nothing_to_a_real_run():
    run = REAL_DAY / FIRST

    def snapshot():
        return sorted((str(p.relative_to(run)), p.stat().st_mtime_ns, p.stat().st_size)
                      for p in run.rglob("*"))

    before = snapshot()
    rd.load_run_info(run, check_reuse=True)
    assert snapshot() == before


@needs_lacie
@pytest.mark.skipif(not REAL_01.is_dir(), reason="10/01 not present")
def test_real_nobh_run_is_found_and_its_bubbler_height_comes_from_the_workbook():
    res = rd.find_runs([REAL_01])
    nobh = [p for p in res.runs if p.name.endswith("_nobh")]
    assert [p.name for p in nobh] == ["101035_4500sccm_500rpm_6000sps_or1.2_nobh"]
    assert res.skipped == []
    info = rd.load_run_info(nobh[0], check_reuse=False)
    assert info.bubbler_height == 1.0 and info.sources["bubbler_height"] == "workbook"
    assert info.errors == [] and info.fps == 800.0
