"""The Settings tab, headless: real editor input, validation, reset, and what it changes elsewhere."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import publish, settings_defaults as sd, size_bins, tab_settings, theme
from src.ai.Taguchi_Analysis_UI.app import BatchTab, MainWindow
from src.ai.Taguchi_Analysis_UI.pane_runs import RunsPane
from src.ai.Taguchi_Analysis_UI.tab_settings import SettingsTab
from src.ai.Taguchi_Analysis_UI.tab_taguchi import TaguchiTab
from src.ai.Taguchi_Analysis_UI.tests import fakes


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_fusion_style(a)
    return a


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def pump(app, cond=lambda: True, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            app.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


MODEL = sd.ModelInfo(Path("/models/Eden"), Path("/models/Eden/Eden.pth"), 19000, 66.8, "weights: Eden.pth")
CPU = sd.Default("cpu", "the pipeline's own choice (tiled_inference.auto_device)")


def make(app, tmp=None, runs: bool = False, measured: bool = False, resolver=None):
    pane = RunsPane()
    pane.log = lambda *a, **k: None
    tab = SettingsTab(pane, resolver=resolver or (lambda: (CPU, MODEL)))
    tab.bridge_pairs = []
    pump(app, lambda: tab.device_default is not None)
    if runs:
        (fakes.make_measured_l9x3 if measured else fakes.make_l9x3)(tmp / "runs")
        pane.add_paths([tmp / "runs" / "2026" / "10" / "05"])
        pump(app, lambda: not pane._busy and pane.list.count() == 27)
    tab.pane = pane
    return tab


def type_in(row, text):
    row.editor.setText(text)
    row.editor.editingFinished.emit()


def idle(app, tab):
    pump(app, lambda: not tab.pane._busy)


# ---- opening state -----------------------------------------------------------------------------------------

def test_it_opens_with_the_pipelines_values_and_everything_marked_default(app):
    tab = make(app)
    pc = spec.rdc_module("process_capture")
    assert tab.thr.editor.text() == f"{pc.DEFAULT_SCORE_THRESH:g}" and tab.stride.editor.text() == str(pc.DEFAULT_STRIDE)
    assert tab.ci.editor.text() == "auto" and tab.model.editor.text() == ""
    assert (tab.bin_width, tab.bin_max) == (size_bins.DEFAULT_WIDTH_UM, size_bins.DEFAULT_MAX_UM)
    for row in (tab.thr, tab.stride, tab.ci, tab.device, tab.model, tab.width, tab.maxd):
        assert row.tag.text() == "default" and not row.reset_btn.isEnabled()
    assert tab.status.text() == "all settings are the pipeline's defaults" and not tab.reset_all_btn.isEnabled()
    assert tab.runs_pane.settings == spec.RunSettings()                  # nothing pinned


def test_every_field_says_where_its_value_comes_from(app):
    tab = make(app)
    assert "process_capture.DEFAULT_SCORE_THRESH" in tab.thr.note.text()
    assert "process_capture.DEFAULT_STRIDE" in tab.stride.note.text()
    assert "auto_ci_stride" in tab.ci.note.text()
    assert "auto_device" in tab.device.note.text()
    assert "default_model_dir" in tab.model.note.text() and "iteration 19000" in tab.model.note.text()
    assert "no upstream value" in tab.width.note.text()


def test_device_and_model_are_resolved_off_the_ui_thread_and_shown_when_ready(app):
    gate, seen = threading.Event(), {}

    def slow():
        seen["thread"] = threading.current_thread().name
        gate.wait(5)
        return CPU, MODEL
    pane = RunsPane()
    tab = SettingsTab(pane, resolver=slow)
    assert "asking the pipeline" in tab.device.note.text() and "looking for the model" in tab.model.note.text()
    assert tab.device_default is None
    gate.set()
    pump(app, lambda: tab.device_default is not None)
    assert seen["thread"] == "settings-resolve"
    assert tab.device.editor.itemText(0) == "auto → cpu"
    assert tab.model.editor.placeholderText() == str(MODEL.folder)


def test_a_resolver_that_fails_is_reported_in_the_tab_not_raised(app):
    def broken():
        raise RuntimeError("drive vanished")
    pane = RunsPane()
    tab = SettingsTab(pane, resolver=broken)
    pump(app, lambda: tab.device_default is not None)
    assert not tab.device_default.ok and "drive vanished" in tab.device_default.note
    assert tab.model.editor.placeholderText() == "no model found: choose a folder"


def test_the_cpu_warning_shows_for_the_resolved_device(app):
    tab = make(app)
    assert tab.device.warn.isVisible() or tab.device.warn.text().startswith("⚠")
    assert "CPU" in tab.device.warn.text()


# ---- editing ---------------------------------------------------------------------------------------------------

def test_a_valid_threshold_is_applied_and_marked_edited(app):
    tab = make(app)
    type_in(tab.thr, "0.45")
    assert tab.runs_pane.settings.score_thresh == 0.45
    assert tab.thr.tag.text() == "edited" and tab.thr.reset_btn.isEnabled()
    assert tab.status.text() == "1 setting changed from the defaults" and tab.reset_all_btn.isEnabled()


def test_typing_the_default_back_means_let_the_pipeline_decide(app):
    tab = make(app)
    type_in(tab.thr, "0.45")
    type_in(tab.thr, "0.30")
    assert tab.runs_pane.settings.score_thresh is None and tab.thr.tag.text() == "default"
    type_in(tab.stride, "10")
    assert tab.runs_pane.settings.stride is None and tab.stride.tag.text() == "default"


def test_an_invalid_entry_is_not_applied_and_says_why(app):
    tab = make(app)
    type_in(tab.thr, "0.45")
    type_in(tab.thr, "banana")
    assert tab.runs_pane.settings.score_thresh == 0.45                    # the last valid value stays in force
    assert tab.thr.error.text().startswith("✖") and "a number between 0 and 1" in tab.thr.error.text()
    type_in(tab.thr, "0.5")
    assert tab.thr.error.text() == "" and tab.runs_pane.settings.score_thresh == 0.5
    type_in(tab.stride, "2.5")
    assert "whole number" in tab.stride.error.text() and tab.runs_pane.settings.stride is None


def test_ci_stride_override_and_back_to_auto(app):
    tab = make(app)
    type_in(tab.ci, "4")
    assert tab.runs_pane.settings.ci_stride == 4 and tab.ci.tag.text() == "edited"
    assert "you chose 4" in tab.ci.note.text()
    type_in(tab.ci, "0")
    assert "or 'auto'" in tab.ci.error.text() and tab.runs_pane.settings.ci_stride == 4
    type_in(tab.ci, "auto")
    assert tab.runs_pane.settings.ci_stride is None and tab.ci.tag.text() == "default"


def test_a_stride_shorter_than_decorrelation_warns_for_the_selected_runs(app, tmp):
    tab = make(app, tmp, runs=True)
    assert tab.stride.warn.text() == ""                                   # 390 fps, stride 10: independent
    type_in(tab.stride, "5")
    idle(app, tab)
    assert "closer than the 20.5 ms" in tab.stride.warn.text() and "390 fps" in tab.stride.note.text()
    type_in(tab.stride, "8")
    idle(app, tab)
    assert tab.stride.warn.text() == ""


def test_the_ci_note_follows_the_stride_for_the_selected_runs(app, tmp):
    tab = make(app, tmp, runs=True)
    pc = spec.rdc_module("process_capture")
    type_in(tab.stride, "1")
    idle(app, tab)
    want = pc.auto_ci_stride(390, 1)
    assert want > 1 and f"{want} for 27 runs" in tab.ci.note.text()


def test_choosing_a_device_applies_it_and_warns_about_risky_choices(app):
    tab = make(app)
    combo = tab.device.editor
    combo.setCurrentIndex(3)                                              # mps
    combo.activated.emit(3)
    assert tab.runs_pane.settings.device == "mps" and "experimental" in tab.device.warn.text()
    combo.setCurrentIndex(2)                                              # cuda while the pipeline found none
    combo.activated.emit(2)
    assert tab.runs_pane.settings.device == "cuda" and "probably fail" in tab.device.warn.text()
    assert tab.device.tag.text() == "edited"
    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert tab.runs_pane.settings.device is None and tab.device.tag.text() == "default"


def test_a_model_folder_is_checked_with_the_pipelines_own_find_weights(app, tmp):
    tab = make(app)
    type_in(tab.model, str(tmp / "nowhere"))
    assert "not a folder" in tab.model.error.text() and tab.runs_pane.settings.model_dir is None
    empty = tmp / "empty"
    empty.mkdir()
    type_in(tab.model, str(empty))
    assert "no weights" in tab.model.error.text() and tab.runs_pane.settings.model_dir is None
    good = tmp / "Benedict"
    good.mkdir()
    (good / "Benedict.pth").write_bytes(b"w")
    (good / "Benedict_summary.json").write_text(json.dumps({"iteration": 9000, "segm_AP": 50.0}))
    type_in(tab.model, str(good))
    assert tab.model.error.text() == "" and tab.runs_pane.settings.model_dir == good
    assert "iteration 9000" in tab.model.note.text() and "Not the promoted production model" in tab.model.warn.text()
    assert tab.model.tag.text() == "edited"


def test_choosing_the_models_default_folder_is_stored_as_no_override(app, tmp):
    folder = tmp / "Eden"                                      # a REAL folder, so it passes validation
    folder.mkdir()
    (folder / "Eden.pth").write_bytes(b"w")
    tab = make(app, resolver=lambda: (CPU, sd.ModelInfo(folder, folder / "Eden.pth", 19000, 66.8, "weights: Eden.pth")))
    type_in(tab.model, str(folder))
    assert tab.model.error.text() == ""                          # it was accepted ...
    assert tab.runs_pane.settings.model_dir is None              # ... as "let the pipeline decide"
    assert tab.model.tag.text() == "default" and tab.model.editor.text() == ""


def test_blank_model_field_returns_to_the_pipelines_choice(app, tmp):
    tab = make(app)
    good = tmp / "M"
    good.mkdir()
    (good / "M.pth").write_bytes(b"w")
    type_in(tab.model, str(good))
    assert tab.runs_pane.settings.model_dir == good
    type_in(tab.model, "")
    assert tab.runs_pane.settings.model_dir is None and tab.model.tag.text() == "default"


def test_browse_fills_in_and_applies_the_chosen_folder(app, tmp, monkeypatch):
    tab = make(app)
    good = tmp / "Z"
    good.mkdir()
    (good / "Z.pth").write_bytes(b"w")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(good)))
    tab.model.browse_btn.click()
    assert tab.model.editor.text() == str(good) and tab.runs_pane.settings.model_dir == good
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    tab.model.browse_btn.click()                                           # cancelled: nothing changes
    assert tab.runs_pane.settings.model_dir == good


def test_size_bin_settings_validate_and_announce_the_change(app):
    tab = make(app)
    seen = []
    tab.bins_changed.connect(lambda: seen.append((tab.bin_width, tab.bin_max)))
    tab.width.editor.setText("50")
    tab.width.editor.editingFinished.emit()
    assert seen[-1] == (50.0, 200.0) and tab.width.tag.text() == "edited"
    tab.maxd.editor.setText("30")                                          # less than one bin
    tab.maxd.editor.editingFinished.emit()
    assert "at least one bin width" in tab.width.error.text() and (tab.bin_width, tab.bin_max) == (50.0, 200.0)
    tab.maxd.editor.setText("-1")
    tab.maxd.editor.editingFinished.emit()
    assert "more than 0" in tab.width.error.text()
    tab.maxd.editor.setText("300")
    tab.maxd.editor.editingFinished.emit()
    assert tab.width.error.text() == "" and (tab.bin_width, tab.bin_max) == (50.0, 300.0)


# ---- reset ----------------------------------------------------------------------------------------------------------

def test_each_reset_button_puts_the_default_back_and_clears_its_error(app):
    tab = make(app)
    type_in(tab.thr, "0.6")
    type_in(tab.stride, "x")
    tab.thr.reset_btn.click()
    assert tab.runs_pane.settings.score_thresh is None and tab.thr.editor.text() == "0.3"
    type_in(tab.stride, "20")
    tab.stride.reset_btn.click()
    assert tab.runs_pane.settings.stride is None and tab.stride.editor.text() == "10" and tab.stride.error.text() == ""
    tab.width.editor.setText("40")
    tab.width.editor.editingFinished.emit()
    tab.width.reset_btn.click()
    assert (tab.bin_width, tab.bin_max) == (size_bins.DEFAULT_WIDTH_UM, size_bins.DEFAULT_MAX_UM)
    assert tab.width.editor.text() == "25"


def test_reset_all_restores_every_default_and_leaves_other_run_settings_alone(app, tmp):
    tab = make(app)
    tab.runs_pane.settings = replace(tab.runs_pane.settings, limit=40)       # not a Settings-tab field
    good = tmp / "Benedict"
    good.mkdir()
    (good / "Benedict.pth").write_bytes(b"w")
    type_in(tab.model, str(good))
    assert tab.runs_pane.settings.model_dir == good
    type_in(tab.thr, "0.6")
    type_in(tab.stride, "20")
    type_in(tab.ci, "3")
    tab.device.editor.setCurrentIndex(1)
    tab.device.editor.activated.emit(1)
    tab.width.editor.setText("40")
    tab.width.editor.editingFinished.emit()
    assert tab.n_edited() == 6
    tab.reset_all_btn.click()
    s = tab.runs_pane.settings
    assert (s.score_thresh, s.stride, s.ci_stride, s.device, s.model_dir) == (None,) * 5 and s.limit == 40
    assert tab.n_edited() == 0 and tab.bin_width == 25.0 and tab.ci.editor.text() == "auto" and tab.model.editor.text() == ""
    assert tab.status.text() == "all settings are the pipeline's defaults"


# ---- what a change does elsewhere ------------------------------------------------------------------------------------

def test_changing_the_threshold_rereads_what_each_run_already_has(app, tmp):
    tab = make(app, tmp, runs=True, measured=True)
    pane = tab.pane
    assert all(r.analysis.measured for r in pane._runs.values())
    victim = next(iter(pane._runs))
    pane._included[victim] = False                                          # the user unticked one
    type_in(tab.thr, "0.5")
    idle(app, tab)
    assert pane.settings.score_thresh == 0.5
    assert not any(r.analysis.measured for r in pane._runs.values())        # no droplets_0.50/ folders exist
    assert pane._included[victim] is False and len(pane.included_runs()) == 26   # ticks survive the re-read
    tab.thr.reset_btn.click()
    idle(app, tab)
    assert all(r.analysis.measured for r in pane._runs.values())


def test_changing_the_stride_rereads_runs_but_the_device_does_not(app, tmp, monkeypatch):
    tab = make(app, tmp, runs=True)
    calls = []
    real = tab.pane._reload_runs
    monkeypatch.setattr(tab.pane, "_reload_runs", lambda: (calls.append(1), real())[1])
    tab.device.editor.setCurrentIndex(1)
    tab.device.editor.activated.emit(1)
    tab.ci.editor.setText("3")
    tab.ci.editor.editingFinished.emit()
    assert calls == []                                                      # neither affects what a folder holds
    type_in(tab.stride, "5")
    idle(app, tab)
    assert calls == [1]


def test_a_change_made_while_runs_are_still_loading_is_not_lost(app, tmp):
    pane = RunsPane()
    pane.log = lambda *a, **k: None
    tab = SettingsTab(pane, resolver=lambda: (CPU, MODEL))
    fakes.make_measured_l9x3(tmp / "runs")
    pane.add_paths([tmp / "runs" / "2026" / "10" / "05"])
    assert pane._busy                                                       # the scan is under way
    pane.set_settings(replace(pane.settings, score_thresh=0.5))             # ... and the user changes the threshold
    pump(app, lambda: not pane._busy and pane.list.count() == 27 and not pane._reload_again)
    pump(app, lambda: not any(r.analysis.measured for r in pane._runs.values()), timeout=10)
    assert len(pane._runs) == 27                                            # re-read under the NEW threshold


def test_with_no_runs_loaded_a_change_just_announces_itself(app):
    tab = make(app)
    seen = []
    tab.runs_pane.settings_changed.connect(lambda: seen.append(1))
    type_in(tab.thr, "0.5")
    assert seen == [1] and not tab.runs_pane._busy


def test_the_batch_tab_uses_the_changed_settings_and_the_outputs_pane_follows_the_threshold(app, tmp):
    bt = BatchTab()
    tab = SettingsTab(bt.runs_pane, resolver=lambda: (CPU, MODEL))
    fakes.make_l9x3(tmp / "runs")
    bt.runs_pane.add_paths([tmp / "runs" / "2026" / "10" / "05"])
    pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.list.count() == 27)
    type_in(tab.thr, "0.45")
    type_in(tab.stride, "6")
    type_in(tab.ci, "2")
    tab.device.editor.setCurrentIndex(1)
    tab.device.editor.activated.emit(1)
    pump(app, lambda: not bt.runs_pane._busy)
    s = bt._settings()
    assert (s.score_thresh, s.stride, s.ci_stride, s.device) == (0.45, 6, 2, "cpu")
    assert bt.outputs_pane._ctx["thr"] == 0.45


def test_the_main_window_has_the_tab_and_analyse_gets_its_bin_settings(app, tmp):
    w = MainWindow()
    try:
        st = w.settings_tab
        assert isinstance(st, SettingsTab) and w.centralWidget().tabText(2).strip() == "Settings"
        assert w.taguchi_tab.bins_provider() == (25.0, 200.0)
        st.width.editor.setText("50")
        st.width.editor.editingFinished.emit()
        assert w.taguchi_tab.bins_provider() == (50.0, 200.0)
        # and Analyse really hands them to publish()
        fakes.make_measured_l9x3(tmp / "runs")
        bt, tt = w.batch_tab, w.taguchi_tab
        bt.runs_pane.add_paths([tmp / "runs" / "2026" / "10" / "05"])
        pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.list.count() == 27)
        bt.runs_pane.set_output_folder(tmp / "out", remember=False)
        got = {}

        def fake(design, out, **kw):
            got.update(kw)
            return publish.Deliverables(out)
        tt.analysis.publish_fn = fake
        tt.analyse_btn.click()
        pump(app, lambda: not tt.analysis.busy and tt.analysis.last is not None)
        assert (got["bin_width"], got["bin_max"]) == (50.0, 200.0)
    finally:
        w.close()


def test_settings_chosen_here_are_what_the_detached_worker_is_actually_given(app, tmp, monkeypatch):
    """Tab -> Run batch -> job.json: the file the worker reads. Stub pipeline, sandbox only."""
    from src.ai.Taguchi_Analysis_UI import jobstate
    from src.ai.Taguchi_Analysis_UI.tests.workerkit import stub_args
    monkeypatch.setenv("TAGUCHI_UI_SANDBOX_ROOT", str(tmp))
    monkeypatch.setenv("TAGUCHI_UI_CALIBRATION", str(tmp / "calib.json"))
    bt = BatchTab()
    bt.confirm = lambda *a, **k: True
    bt.controller.extra_args = stub_args()
    st = SettingsTab(bt.runs_pane, resolver=lambda: (CPU, MODEL))
    for name, _, _ in fakes.REAL_10_05[:2]:
        fakes.make_run(tmp, name)
    bt.runs_pane.add_paths([tmp / "2026" / "10" / "05"])
    pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.list.count() == 2)
    bt.set_preflight(spec.PreflightReport())
    bt.runs_pane.set_output_folder(tmp / "out", remember=False)
    good = tmp / "Benedict"
    good.mkdir()
    (good / "Benedict.pth").write_bytes(b"w")
    type_in(st.thr, "0.45")
    type_in(st.stride, "6")
    type_in(st.ci, "2")
    type_in(st.model, str(good))
    st.device.editor.setCurrentIndex(1)
    st.device.editor.activated.emit(1)
    pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.run_btn.isEnabled())
    try:
        bt.runs_pane.run_btn.click()
        pump(app, lambda: (tmp / "out" / "_job" / "job.json").is_file())
        job = jobstate.load_job(tmp / "out" / "_job")
        s = job["settings"]
        assert (s["score_thresh"], s["stride"], s["ci_stride"], s["device"], s["model_dir"]) == \
            (0.45, 6, 2, "cpu", str(good))
        pump(app, lambda: bt.controller.mode in ("finished", "finished_with_failures"), timeout=90)
        assert bt.controller.mode == "finished"
        assert len(list((tmp / "2026/10/05").rglob("droplets_0.45"))) == 2     # both runs wrote under the new threshold
    finally:
        if bt.controller.jd:
            jobstate.kill_worker(bt.controller.jd)
