"""The "runs that already have results" setting: what Run batch does with them."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.ai.Taguchi_Analysis_UI import jobstate, reanalysis as ra, theme
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI.app import BatchTab
from src.ai.Taguchi_Analysis_UI.tests import fakes
from src.ai.Taguchi_Analysis_UI.tests.workerkit import stub_args

OK = spec.PreflightReport()
NAMES = [n for n, _, _ in fakes.REAL_10_05]


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_fusion_style(a)
    return a


@pytest.fixture
def tmp(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        monkeypatch.setenv("TAGUCHI_UI_SANDBOX_ROOT", str(d))
        monkeypatch.setenv("TAGUCHI_UI_CALIBRATION", str(d / "calib.json"))
        yield d


def info(tmp, i, **kw):
    return rd.load_run_info(fakes.make_run(tmp, NAMES[i], **kw), check_reuse=False)


def pump(app, cond, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            app.processEvents()
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


# ---- planning ------------------------------------------------------------------------------

def test_skip_leaves_measured_runs_alone_and_processes_the_rest(tmp):
    new, done, half = info(tmp, 0), info(tmp, 1, analysis="current"), info(tmp, 2, analysis="current")
    import shutil
    shutil.rmtree(half.path / "shadowgraph/analysis/liquid_0.30")           # droplets only
    half = rd.load_run_info(half.path, check_reuse=False)
    assert half.analysis.droplets_only
    plan = ra.plan_runs([new, done, half], ra.SKIP)
    assert plan.process == [new, half] and plan.skipped == [done] and plan.cannot == []
    assert plan.reuse is True


def test_the_default_mode_is_skip():
    assert ra.DEFAULT_MODE == ra.SKIP == ra.MODES[0][0]


@pytest.mark.parametrize("mode", [ra.REMEASURE, ra.REDO])
def test_remeasure_and_redo_process_every_runnable_run(tmp, mode):
    runs = [info(tmp, 0), info(tmp, 1, analysis="current")]
    plan = ra.plan_runs(runs, mode)
    assert plan.process == runs and plan.skipped == []


def test_measured_runs_without_a_cine_cannot_be_rerun(tmp):
    gone = info(tmp, 0, analysis="current", cines=0)
    assert not gone.runnable and gone.analysable
    assert ra.plan_runs([gone], ra.SKIP).skipped == [gone]                  # fine: used as it is
    plan = ra.plan_runs([gone], ra.REMEASURE)
    assert plan.cannot == [gone] and plan.process == []
    assert any("no .cine here" in l for l in ra.describe(plan))


def test_redo_turns_reuse_off_and_the_others_keep_it_on():
    base = spec.RunSettings(stride=10)
    assert ra.settings_for(ra.SKIP, base).reuse and ra.settings_for(ra.REMEASURE, base).reuse
    assert not ra.settings_for(ra.REDO, base).reuse
    assert base.reuse is False                                              # input not mutated


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        ra.plan_runs([], "overwrite-everything")


def _with_reusable(run, value):
    run.analysis.reusable = value
    return run


def test_remeasure_says_which_runs_keep_the_ai_and_which_must_redo_it(tmp):
    keeps = _with_reusable(info(tmp, 0, analysis="current"), True)
    must = _with_reusable(info(tmp, 1, analysis="current"), False)         # frames deleted / stale
    plan = ra.plan_runs([keeps, must], ra.REMEASURE)
    assert plan.keep_ai == [keeps] and plan.redo_ai == [must]
    lines = " ".join(ra.describe(plan))
    assert "frames and AI predictions are reused" in lines and "missing, partial" in lines
    assert "hours on a CPU" in lines


def test_redo_redoes_the_ai_for_everything_even_if_reusable(tmp):
    r = _with_reusable(info(tmp, 0, analysis="current"), True)
    plan = ra.plan_runs([r], ra.REDO)
    assert plan.keep_ai == [] and plan.redo_ai == [r]
    assert "re-extracts the frames" in " ".join(ra.describe(plan))
    assert "you chose to redo everything" in " ".join(ra.describe(plan))


def test_new_runs_are_always_the_full_chain(tmp):
    plan = ra.plan_runs([info(tmp, 0)], ra.SKIP)
    assert plan.new == plan.process and plan.remeasured == [] and plan.redo_ai == []


# ---- the setting in the window -------------------------------------------------------------------

def make_tab(app, tmp, measured=(), fresh=(), cines=1):
    tab = BatchTab()
    tab.resize(1300, 800)
    tab.show()
    tab.confirm = lambda *a, **k: True
    tab.controller.extra_args = stub_args()
    for i in measured:
        fakes.make_run(tmp, NAMES[i], analysis="current", cines=cines)
    for i in fresh:
        fakes.make_run(tmp, NAMES[i])
    n = len(measured) + len(fresh)
    tab.runs_pane.add_paths([tmp / "2026" / "10" / "05"])
    pump(app, lambda: not tab.runs_pane._busy and tab.runs_pane.list.count() == n)
    tab.set_preflight(OK)
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    return tab


def test_the_setting_only_appears_when_some_selected_runs_have_results(app, tmp):
    tab = make_tab(app, tmp, fresh=[0, 1])
    assert not tab.runs_pane.existing_row.isVisibleTo(tab)
    tab = make_tab(app, tmp / "b", measured=[2], fresh=[3])
    assert tab.runs_pane.existing_row.isVisibleTo(tab)
    assert "1 of the 2 selected runs already have results" in tab.runs_pane.existing_label.text()
    assert tab.runs_pane.existing_mode() == ra.SKIP                         # safe default


def test_all_measured_plus_skip_means_there_is_nothing_to_run(app, tmp):
    tab = make_tab(app, tmp, measured=[0, 1])
    rb = tab.runs_pane.run_btn
    assert not rb.isEnabled() and "Nothing to run" in rb.toolTip() and "Re-measure" in rb.toolTip()
    tab.runs_pane.set_existing_mode(ra.REMEASURE)
    assert rb.isEnabled() and "Analyse 2 runs" in rb.toolTip()
    tab.runs_pane.set_existing_mode(ra.SKIP)
    assert not rb.isEnabled()


def test_skip_runs_only_what_still_needs_running(app, tmp):
    tab = make_tab(app, tmp, measured=[0, 1], fresh=[2])
    rb = tab.runs_pane.run_btn
    assert rb.isEnabled() and "Analyse 1 run in the background; 2 left as they are" in rb.toolTip()
    seen = []
    tab.confirm = lambda text, *a: seen.append(text) or True
    rb.click()
    pump(app, lambda: tab.controller.mode == "finished")
    job = jobstate.load_job(tab.controller.jd)
    assert [Path(p).name for p in job["runs"]] == [NAMES[2]]               # the measured two untouched
    assert "2 run(s) already have results and are left as they are" in seen[0]
    assert "(the analysis still uses them)" in seen[0]
    for i in (0, 1):                                                       # their results were not rewritten
        assert not (tmp / "2026/10/05" / NAMES[i] / "shadowgraph/analysis/predictions.json").exists()


def run_remeasure(app, tmp, reusable):
    tab = make_tab(app, tmp, measured=[0], fresh=[1])
    for r in tab.runs_pane.all_runs():
        if r.analysis.measured:
            r.analysis.reusable = reusable           # what can_reuse() would have said
    tab.runs_pane.set_existing_mode(ra.REMEASURE)
    seen = []
    tab.confirm = lambda text, *a: seen.append(text) or True
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.mode == "finished")
    return jobstate.load_job(tab.controller.jd), seen[0]


def test_remeasure_runs_everything_and_keeps_reuse_on(app, tmp):
    job, text = run_remeasure(app, tmp, reusable=True)
    assert sorted(Path(p).name for p in job["runs"]) == sorted(NAMES[:2])
    assert job["settings"]["reuse"] is True
    assert "will be re-measured; their frames and AI predictions are reused" in text
    assert "overwritten in place" in text and "AI will be run again" not in text


def test_remeasure_is_honest_when_the_ai_predictions_cannot_be_reused(app, tmp):
    """A run whose frames/predictions are missing or stale cannot be re-measured cheaply:
    the pipeline silently falls back to the full chain, so the confirmation must say so."""
    job, text = run_remeasure(app, tmp / "b", reusable=False)
    assert job["settings"]["reuse"] is True          # still asks to reuse; can_reuse() refuses
    assert "AI will be run again" in text and "missing, partial" in text
    assert "frames and AI predictions are reused" not in text


def test_redo_everything_turns_reuse_off_in_the_job(app, tmp):
    tab = make_tab(app, tmp, measured=[0])
    tab.runs_pane.set_existing_mode(ra.REDO)
    seen = []
    tab.confirm = lambda text, *a: seen.append(text) or True
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.mode == "finished")
    job = jobstate.load_job(tab.controller.jd)
    assert job["settings"]["reuse"] is False
    assert "AI will be run again" in seen[0] and "you chose to redo everything" in seen[0]
    assert "re-extracts the frames" in seen[0]


def test_cancelling_the_confirmation_starts_nothing(app, tmp):
    tab = make_tab(app, tmp, measured=[0], fresh=[1])
    tab.runs_pane.set_existing_mode(ra.REDO)
    tab.confirm = lambda *a: False
    tab.runs_pane.run_btn.click()
    app.processEvents()
    assert tab.controller.jd is None and not (tmp / "out" / "_job").exists()


def test_selecting_runs_never_starts_anything(app, tmp):
    tab = make_tab(app, tmp, measured=[0, 1], fresh=[2])
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    assert tab.controller.jd is None and tab.controller.mode == "none"
    assert not (tmp / "out").exists()


def test_the_choice_does_not_persist_between_launches(app, tmp):
    tab = make_tab(app, tmp, measured=[0], fresh=[1])
    tab.runs_pane.set_existing_mode(ra.REDO)
    again = make_tab(app, tmp / "second", measured=[0], fresh=[1])
    assert again.runs_pane.existing_mode() == ra.SKIP


def test_measured_runs_without_cines_are_still_analysed_under_skip(app, tmp):
    tab = make_tab(app, tmp, measured=[0, 1], cines=0)
    assert len(tab.runs_pane.included_runs()) == 2                         # still selected for analysis
    plan = tab.plan()
    assert plan.skipped and not plan.process
    tab.runs_pane.set_existing_mode(ra.REMEASURE)
    assert not tab.runs_pane.run_btn.isEnabled()                           # cannot be re-run: no cine
    assert "Nothing to run" in tab.runs_pane.run_btn.toolTip()


def test_the_output_tree_counts_the_runs_the_batch_will_process_not_the_ones_selected(app, tmp):
    tab = make_tab(app, tmp, measured=[0, 1], fresh=[2, 3, 4])
    head = lambda: tab.outputs_pane.tree.topLevelItem(0).text(0)
    assert "each of 3 run folders" in head() and NAMES[2] in head()        # skip: 3 of the 5
    assert "9.3 GB for 3 runs" in tab.outputs_pane.cost_label.text()
    tab.runs_pane.set_existing_mode(ra.REMEASURE)
    assert "each of 5 run folders" in head() and NAMES[0] in head()        # all 5 now
    tab.runs_pane.set_existing_mode(ra.SKIP)
    assert "each of 3 run folders" in head()
