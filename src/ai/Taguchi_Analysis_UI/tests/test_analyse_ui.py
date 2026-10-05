"""The Analyse button and the background controller, headless."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.ai.Taguchi_Analysis_UI import analysis_controller as ac
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import publish, tab_taguchi, theme
from src.ai.Taguchi_Analysis_UI.app import BatchTab, MainWindow
from src.ai.Taguchi_Analysis_UI.tab_taguchi import TaguchiTab
from src.ai.Taguchi_Analysis_UI.tests import fakes


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_fusion_style(a)
    return a


@pytest.fixture(scope="module", autouse=True)
def small_bootstrap():
    ta = spec.rdc_module("taguchi_analysis")
    old = ta.N_BOOT
    ta.N_BOOT = 40
    yield
    ta.N_BOOT = old


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def pump(app, cond=lambda: True, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            app.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def make(app, tmp, measured=True, out=True):
    bt = BatchTab()
    tab = TaguchiTab(bt.runs_pane)
    tab.messages = []
    tab.log = lambda text, level="info": tab.messages.append((level, text))
    tab.ask_yes = lambda text: True
    tab.options_provider = bt.outputs_pane.options
    if measured:
        fakes.make_measured_l9x3(tmp / "runs")
    else:
        fakes.make_l9x3(tmp / "runs")
    bt.runs_pane.add_paths([tmp / "runs" / "2026" / "10" / "05"])
    pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.list.count() == 27)
    if out:
        bt.runs_pane.set_output_folder(tmp / "out", remember=False)
        pump(app)
    tab.bt = bt
    return tab


def finish(app, tab):
    pump(app, lambda: not tab.analysis.busy and tab.analysis.last is not None)


# ---- the controller ------------------------------------------------------------------------------------

def test_controller_runs_off_the_ui_thread_and_delivers_on_it(app, tmp):
    seen, gate = {}, threading.Event()

    def fake(design, out, *, thr, options, progress, log, **kw):
        gate.wait(5)
        seen["thread"] = threading.current_thread().name
        progress(1, 2, "a")
        progress(2, 2, "b")
        return publish.Deliverables(out)

    c = ac.AnalysisController(publish_fn=fake)
    lines, got = [], []
    c.log = lambda t, l="info": lines.append(t)
    c.finished.connect(lambda d: got.append((d, threading.current_thread().name)))
    assert c.start(object(), tmp, thr=0.3, options={})
    assert c.busy and "starting" in c.status()
    gate.set()
    pump(app, lambda: bool(got))
    assert seen["thread"] == "taguchi-analysis" and got[0][1] == threading.main_thread().name
    assert not c.busy and c.last is got[0][0] and any("run 2/2  b" in l for l in lines)


def test_controller_refuses_a_second_start_while_busy(app, tmp):
    gate = threading.Event()
    c = ac.AnalysisController(publish_fn=lambda d, o, **k: (gate.wait(5), publish.Deliverables(o))[1])
    assert c.start(object(), tmp, thr=None, options={})
    assert not c.start(object(), tmp, thr=None, options={})
    gate.set()
    pump(app, lambda: not c.busy)


def test_controller_analyses_the_design_as_it_was_at_the_click(app, tmp):
    gate, saw = threading.Event(), {}

    def fake(design, out, **k):
        gate.wait(5)
        saw["n"] = len(design.rows)
        return publish.Deliverables(out)

    class D:
        def __init__(self):
            self.rows = [1, 2, 3]
    design = D()
    c = ac.AnalysisController(publish_fn=fake)
    c.start(design, tmp, thr=None, options={})
    design.rows.append(4)                       # the user keeps editing
    gate.set()
    pump(app, lambda: not c.busy)
    assert saw["n"] == 3


def test_a_crash_in_the_analysis_is_reported_not_swallowed(app, tmp):
    def boom(*a, **k):
        raise ValueError("kaboom")
    c = ac.AnalysisController(publish_fn=boom)
    lines = []
    c.log = lambda t, l="info": lines.append((l, t))
    c.start(object(), tmp, thr=None, options={})
    pump(app, lambda: c.last is not None)
    assert c.last.problems == ["analysis crashed: ValueError: kaboom"] and not c.busy
    assert any(l == "error" and "kaboom" in t for l, t in lines)


# ---- the button ---------------------------------------------------------------------------------------------

def test_analyse_is_disabled_until_there_is_an_output_folder_and_runs(app, tmp):
    tab = make(app, tmp, out=False)
    assert not tab.analyse_btn.isEnabled() and "output folder" in tab.analyse_btn.toolTip()
    assert "output folder" in tab.analyse_label.text() and not tab.report_btn.isEnabled()
    tab.bt.runs_pane.set_output_folder(tmp / "out", remember=False)
    pump(app)
    assert tab.analyse_btn.isEnabled() and tab.folder_btn.isEnabled()


def test_clicking_analyse_writes_the_deliverables_and_reports_them(app, tmp):
    tab = make(app, tmp)
    tab.analyse_btn.click()
    assert tab.analysis.busy and not tab.analyse_btn.isEnabled() and tab.analyse_btn.text() == "Analysing …"
    finish(app, tab)
    out = tmp / "out"
    assert (out / "taguchi_report.md").is_file() and (out / "taguchi_analysis.xlsx").is_file()
    assert (out / "figures" / "fig_size_spread_volume.png").is_file()
    assert tab.analyse_btn.isEnabled() and tab.report_btn.isEnabled()
    assert tab.analyse_label.text().startswith("✔") and "27 runs analysed" in tab.analyse_label.text()
    assert theme.CLR_GREEN in tab.analyse_label.styleSheet()
    levels = [l for l, t in tab.messages]
    assert "ok" in levels and not [t for l, t in tab.messages if l == "error"]
    assert any("analysis done" in t for l, t in tab.messages)


def test_ticked_optional_outputs_flow_through_to_the_analysis(app, tmp):
    tab = make(app, tmp)
    pane = tab.bt.outputs_pane
    pane.set_ticks(pane.ticks() | {"flat_csvs", "odd_pack"})
    tab.analyse_btn.click()
    finish(app, tab)
    assert (tmp / "out" / "csv" / "results.json").is_file() and (tmp / "out" / "odd").is_dir()


def test_the_threshold_comes_from_the_settings_not_a_literal(app, tmp, monkeypatch):
    tab = make(app, tmp)
    got = {}

    def fake(design, out, *, thr, options, progress, log, **kw):
        got.update(thr=thr, options=options)
        return publish.Deliverables(out)
    tab.analysis.publish_fn = fake
    from dataclasses import replace
    tab.runs_pane.settings = replace(tab.runs_pane.settings, score_thresh=0.45)      # not the default
    tab.analyse_btn.click()
    pump(app, lambda: not tab.analysis.busy and tab.analysis.last is not None)
    assert got["thr"] == 0.45 == spec.effective(tab.runs_pane.settings).score_thresh
    assert got["options"] == tab.bt.outputs_pane.options()


def test_a_refused_analysis_is_shown_in_red_and_writes_nothing(app, tmp):
    tab = make(app, tmp)
    summ = next((tmp / "runs").rglob("droplets_0.30/summary.json"))
    s = json.loads(summ.read_text()); s["provenance"]["sizer_version"] = "2.0.0"
    summ.write_text(json.dumps(s))
    tab.analyse_btn.click()
    finish(app, tab)
    assert tab.analyse_label.text().startswith("✖ Refused") and theme.CLR_RED in tab.analyse_label.styleSheet()
    assert any(l == "error" and "REFUSED" in t for l, t in tab.messages)
    assert not (tmp / "out" / "taguchi_report.md").exists() and not tab.report_btn.isEnabled()


def test_unmeasured_runs_are_left_out_and_said_so(app, tmp):
    tab = make(app, tmp, measured=False)
    tab.analyse_btn.click()
    finish(app, tab)
    assert tab.analysis.last.refused and "nothing to analyse" in tab.analysis.last.refused
    assert any("not measured yet" in t for l, t in tab.messages)


def test_analysing_while_a_batch_runs_asks_first(app, tmp):
    tab = make(app, tmp)
    asked = []
    tab.batch_busy = lambda: True
    tab.ask_yes = lambda text: asked.append(text) or False
    tab.analyse_btn.click()
    assert asked and "still running" in asked[0] and not tab.analysis.busy
    tab.ask_yes = lambda text: True
    tab.analyse_btn.click()
    finish(app, tab)
    assert (tmp / "out" / "taguchi_report.md").is_file()


def test_a_result_belongs_to_the_folder_it_was_written_to(app, tmp):
    tab = make(app, tmp)
    tab.analyse_btn.click()
    finish(app, tab)
    assert tab.report_btn.isEnabled()
    tab.bt.runs_pane.set_output_folder(tmp / "elsewhere", remember=False)
    pump(app)
    assert tab.analysis.last is None and not tab.report_btn.isEnabled()
    assert tab.analyse_label.text() == "" and tab.analyse_btn.isEnabled()


def test_open_report_opens_the_report_and_open_folder_the_folder(app, tmp, monkeypatch):
    tab = make(app, tmp)
    tab.analyse_btn.click()
    finish(app, tab)
    opened = []
    monkeypatch.setattr(tab_taguchi.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    tab.report_btn.click()
    tab.folder_btn.click()
    assert opened == [str(tmp / "out" / "taguchi_report.md"), str(tmp / "out")]


def test_the_main_window_wires_the_tab_to_the_outputs_pane_and_the_batch(app, tmp):
    w = MainWindow()
    try:
        t = w.taguchi_tab
        assert t.options_provider == w.batch_tab.outputs_pane.options
        assert t.batch_busy() is False
        assert t.analyse_btn.parent() is not None
    finally:
        w.close()
