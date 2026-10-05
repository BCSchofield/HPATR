"""The Batch tab driving real detached workers (stub pipeline), through its buttons."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.ai.Taguchi_Analysis_UI import jobstate, procs, theme
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI.app import BatchTab
from src.ai.Taguchi_Analysis_UI.batch_controller import confirm_text, format_event
from src.ai.Taguchi_Analysis_UI.tests import fakes
from src.ai.Taguchi_Analysis_UI.tests.workerkit import new_job, run_state, stub_args, wait_exit

OK = spec.PreflightReport()                     # no violations = passed


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


def pump(app, cond, timeout=60.0, what="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            app.processEvents()
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def make_tab(app, tmp, n_runs=3, preflight=OK, extra=None):
    tab = BatchTab()
    tab.resize(1300, 800)
    tab.show()
    tab.confirm = lambda *a, **k: True
    tab.controller.extra_args = extra if extra is not None else stub_args()
    for name, _, _ in fakes.REAL_10_05[:n_runs]:
        fakes.make_run(tmp, name)
    tab.runs_pane.add_paths([tmp / "2026" / "10" / "05"])
    pump(app, lambda: not tab.runs_pane._busy and tab.runs_pane.list.count() == n_runs, what="runs")
    if preflight is not None:
        tab.set_preflight(preflight)
    return tab


def console(tab):
    tab.console._flush()             # lines are queued and drained every 100 ms; read them all
    return tab.console.text.toPlainText()


def stop_everything(tab):
    if tab.controller.jd:
        jobstate.kill_worker(tab.controller.jd)


# ---- readiness -----------------------------------------------------------------------

def test_run_is_disabled_until_everything_needed_is_there(app, tmp):
    tab = make_tab(app, tmp, preflight=None)
    rb = tab.runs_pane.run_btn
    assert not rb.isEnabled() and "Checking the pipeline" in rb.toolTip()
    bad = spec.PreflightReport(violations=[spec.Violation("error", "x", "y")])
    tab.set_preflight(bad)
    assert not rb.isEnabled() and "no longer matches" in rb.toolTip()
    tab.set_preflight(OK)
    assert not rb.isEnabled() and "output folder" in rb.toolTip()
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    assert rb.isEnabled() and rb.text() == "Run batch" and "3 runs" in rb.toolTip()
    for i in range(3):
        tab.runs_pane.list.item(i).setCheckState(tab.runs_pane.list.item(i).checkState().Unchecked)
    assert not rb.isEnabled() and "Tick at least one run" in rb.toolTip()


# ---- a whole batch through the buttons ---------------------------------------------------

def test_run_batch_runs_in_the_background_and_reports_in_the_console(app, tmp):
    tab = make_tab(app, tmp)
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.mode == "finished", what="the batch to finish")
    text = console(tab)
    assert "batch started in the background" in text
    assert "can be resumed" not in text            # a brand-new batch is not a "resumable" one
    assert "✔ [1/3]" in text and "✔ [3/3]" in text
    assert "batch finished: 3 done" in text
    assert tab.console.status_label.text() == "batch finished: 3/3 done"
    assert tab.runs_pane.run_btn.text() == "Run batch" and not tab.runs_pane.stop_btn.isVisible()
    for name, _, _ in fakes.REAL_10_05[:3]:
        run = tmp / "2026" / "10" / "05" / name
        assert spec.verify_run_outputs(run, spec.RunSettings(), spec.default_options()) == []


def test_every_frame_tick_reaches_the_batch(app, tmp):
    tab = make_tab(app, tmp, n_runs=1)
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    tab.outputs_pane.set_ticks(tab.outputs_pane.ticks() | {"meas_all", "clas_all"})
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.mode == "finished", what="finish")
    assert jobstate.load_job(tab.controller.jd)["options"]["images"] == "all"
    run = tmp / "2026" / "10" / "05" / fakes.REAL_10_05[0][0]
    assert (run / "shadowgraph" / "analysis" / "liquid_0.30" / "images").is_dir()


def test_buttons_while_running_then_stop_after_this_run_then_resume(app, tmp):
    tab = make_tab(app, tmp, extra=stub_args(stage_s=0.04))
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.mode == "running", what="running")
    rp = tab.runs_pane
    assert rp.run_btn.text() == "Stop after this run" and rp.stop_btn.isVisible()
    rp.run_btn.click()
    assert rp.run_btn.text().startswith("Stopping after this run") and not rp.run_btn.isEnabled()
    pump(app, lambda: tab.controller.mode == "stopped", what="stopped")
    assert rp.run_btn.text().startswith("Resume (") and rp.aux_btn.isVisible()
    assert rp.aux_btn.text() == "New batch"
    rp.run_btn.click()
    pump(app, lambda: tab.controller.mode == "finished", what="resumed batch to finish")
    assert jobstate.counts(jobstate.load_state(tab.controller.jd)) == {"done": 3}


def test_stop_now_then_resume_redoes_only_the_interrupted_run(app, tmp):
    hang = fakes.REAL_10_05[1][0]
    tab = make_tab(app, tmp, extra=stub_args("--stub-hang", hang, "--stub-hang-s", "60"))
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.jd and run_state(tab.controller.jd, 1).get("stage") == "inference",
         what="run 2 in inference")
    tab.runs_pane.stop_btn.click()
    pump(app, lambda: tab.controller.mode == "dead", what="the worker to be stopped")
    assert "batch stopped now" in console(tab)
    assert tab.runs_pane.run_btn.text() == "Resume (1/3 done)"
    tab.controller.extra_args = stub_args()               # no hang this time
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.mode == "finished", what="finish after resume")
    st = jobstate.load_state(tab.controller.jd)
    assert [r["attempts"] for r in st["runs"]] == [1, 2, 1]


def test_failed_runs_offer_retry(app, tmp):
    bad = fakes.REAL_10_05[0][0]
    tab = make_tab(app, tmp, n_runs=2, extra=stub_args("--stub-fail", bad))
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.mode == "finished_with_failures", what="finish with a failure")
    text = console(tab)
    assert f"✖ [1/2] {bad} FAILED" in text
    aux = tab.runs_pane.aux_btn
    assert aux.isVisible() and aux.text() == "Retry failed (1)"
    tab.controller.extra_args = stub_args()
    aux.click()
    pump(app, lambda: tab.controller.mode == "finished", what="retry to finish")
    assert jobstate.counts(jobstate.load_state(tab.controller.jd)) == {"done": 2}


def test_a_failed_preflight_at_start_time_stops_the_batch_from_starting(app, tmp, monkeypatch):
    tab = make_tab(app, tmp, n_runs=1)
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    broken = spec.PreflightReport(violations=[spec.Violation(
        "error", "classical_liquid.py", "no longer accepts --images-mode", "update CLASSICAL")])
    monkeypatch.setattr(spec, "preflight_fresh", lambda: broken)
    tab.runs_pane.run_btn.click()
    pump(app, lambda: "NOT started" in console(tab), what="the refusal")
    assert not (tmp / "out" / "_job").exists()
    assert "no longer accepts --images-mode" in console(tab)


# ---- reattaching ----------------------------------------------------------------------------

def test_reopening_reattaches_to_a_running_batch(app, tmp):
    runs = [fakes.make_run(tmp, n) for n, _, _ in fakes.REAL_10_05[:3]]
    jd, p = jobstate.start_job(tmp / "out", runs, spec.RunSettings(), spec.default_options(),
                               preflight=OK, extra_args=stub_args(stage_s=0.05))
    pump(app, lambda: run_state(jd, 0).get("status") == "running", what="worker running")
    tab = BatchTab()                                    # "reopening the app"
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    pump(app, lambda: tab.controller.mode == "running", timeout=10, what="re-attach")
    assert "found a batch" in console(tab) and "re-attached" in console(tab)
    assert tab.runs_pane.run_btn.text() == "Stop after this run"
    pump(app, lambda: "/3 " in tab.console.status_label.text() or tab.controller.mode == "finished",
         what="live status")
    wait_exit(p)
    pump(app, lambda: tab.controller.mode == "finished", what="finished")
    assert "batch finished" in console(tab)


def test_reopening_after_a_crash_offers_resume(app, tmp):
    runs = [fakes.make_run(tmp, n) for n, _, _ in fakes.REAL_10_05[:2]]
    jd, p = jobstate.start_job(tmp / "out", runs, spec.RunSettings(), spec.default_options(),
                               preflight=OK, extra_args=stub_args("--stub-hang", runs[0].name,
                                                                  "--stub-hang-s", "60"))
    pump(app, lambda: run_state(jd, 0).get("stage") == "inference", what="hang")
    procs.kill_tree(p.pid)
    p.wait()
    tab = BatchTab()
    tab.controller.extra_args = stub_args()
    tab.runs_pane.set_output_folder(tmp / "out", remember=False)
    app.processEvents()
    assert tab.runs_pane.run_btn.text() == "Resume (0/2 done)"
    assert "can be resumed" in console(tab)
    status, level = tab.controller.status()
    assert level == "error" and "click Resume" in status
    tab.runs_pane.run_btn.click()
    pump(app, lambda: tab.controller.mode == "finished", what="resume to finish")


# ---- formatting --------------------------------------------------------------------------------

def test_events_format_for_the_console():
    assert format_event({"k": "progress", "i": 0, "done": 3}, 3) is None
    assert format_event({"k": "run_start", "i": 1, "name": "x", "attempt": 2}, 3) == \
        ("▶ [2/3] x (attempt 2)", "info")
    text, level = format_event({"k": "error", "i": 0, "detail": "CONTRACT: a: missing",
                                "fix": "Output 'a'"}, 3)
    assert level == "error" and "fix: Output 'a'" in text
    ok, lvl = format_event({"k": "run_end", "i": 2, "name": "x", "status": "done", "total_s": 125,
                            "d32": 90.0, "atomised": 8.1}, 3)
    assert lvl == "ok" and ok == "✔ [3/3] x done in 2m 05s · D32 90.0 µm · atomised 8.1%"


def test_errors_are_coloured_in_the_console(app, tmp):
    tab = make_tab(app, tmp, n_runs=1)
    tab.console.log("something broke", "error")
    pump(app, lambda: "something broke" in console(tab), what="log line")
    assert "#ff453a" in tab.console.text.document().toHtml().lower()


def test_confirmation_spells_out_what_will_happen(tmp):
    from src.ai.Taguchi_Analysis_UI import run_discovery as rd
    measured = rd.load_run_info(fakes.make_run(tmp, fakes.REAL_10_05[0][0], analysis="current"))
    fresh = rd.load_run_info(fakes.make_run(tmp, fakes.REAL_10_05[1][0]))
    text = confirm_text([measured, fresh], dict(spec.default_options(), images="all"),
                        spec.RunSettings(), tmp / "out")
    assert "2 run(s)" in text and "EVERY frame" in text
    assert "1 of these already have results" in text
    assert "keeps going if you close this window" in text
    import sys
    if sys.platform == "darwin":
        assert "CPU" in text


def test_tests_never_write_the_users_preferences():
    from src.ai.Taguchi_Analysis_UI.pane_runs import app_settings
    assert app_settings() is None
