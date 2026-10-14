"""Phase 7: the Response surface tab, headless, on a measured fake CCD day (the 33-run sheet captured as
fake runs) and the fake 9x3: the detected design and its edits, the model defaults, the builder, the
built-sheet comparison, a real Analyse, and the guide."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ai.Taguchi_Analysis_UI import rsm_design as rb
from src.ai.Taguchi_Analysis_UI import rsm_detect as rdet
from src.ai.Taguchi_Analysis_UI import theme
from src.ai.Taguchi_Analysis_UI.app import BatchTab, MainWindow
from src.ai.Taguchi_Analysis_UI.tab_rsm import ROLE_PATH, RsmTab, goal_for_fit
from src.ai.Taguchi_Analysis_UI.tests import fakes
from src.ai.Taguchi_Analysis_UI.tests.test_rsm_design import ben_plan


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_fusion_style(a)
    return a


def pump(app, cond=lambda: True, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            app.processEvents()
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


@pytest.fixture(scope="module")
def ccd_day():
    """The measured fake 33-run CCD day, made once (the widgets are made per test: a module-scoped
    top-level widget is destroyed between tests)."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        fakes.make_measured_ccd_day(root / "runs", rb.build_sheet(ben_plan()), seed=3)
        (root / "out").mkdir()
        yield root


@pytest.fixture
def ccd(app, ccd_day):
    """The tab over the CCD day, with an output folder (shared across the module's tests)."""
    root = ccd_day
    bt = BatchTab()
    tab = RsmTab(bt.runs_pane)
    tab.messages = []
    tab.log = lambda text, level="info": tab.messages.append((level, text))
    tab.ask_yes = lambda text: True
    bt.runs_pane.add_paths([root / "runs" / "2026"])
    pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.list.count() == 33)
    bt.runs_pane.set_output_folder(root / "out", remember=False)
    pump(app)
    tab.bt, tab.root = bt, root
    yield tab


def _col(tab, text):
    return next(i for i in range(tab.table.columnCount()) if tab.table.horizontalHeaderItem(i).text() == text)


def test_the_window_has_the_tab_and_its_new_title(app):
    w = MainWindow()
    titles = [w.centralWidget().tabText(i).strip() for i in range(w.centralWidget().count())]
    assert w.windowTitle() == "Experiment Analysis" and "Response surface" in titles


def test_the_ccd_day_is_detected_and_shown(ccd):
    assert ccd.table.rowCount() == 33
    assert "face-centred central composite" in ccd.banner.text()
    kinds = [ccd.table.item(i, 2).text() for i in range(33)]
    assert sum(k.startswith("centre") for k in kinds) == 5 and any("check point" in k for k in kinds)
    assert ccd.block_combo.currentData() == "auto"


def test_the_model_defaults_for_a_ccd(ccd):
    m = ccd.read_model()
    assert set(m["roles"].values()) == {"surface"} and not m["compare"]
    assert m["discrete"] == {"orifice": "0.5, 0.8, 1.2, 1.8"}
    models, opts = ccd.models_and_options()
    assert len(models) == 1 and opts["discrete"] == {"orifice": [0.5, 0.8, 1.2, 1.8]}
    # throughput (2026-10-14): in-band droplets per second x3, atomised fraction x1
    assert {g["key"]: g["importance"] for g in opts["goals"]} == {"rate_band": 3.0, "atom": 1.0}
    # 2026-10-13: orifice on a log scale and pressure-limited runs left out, by default
    assert m["log"] == ["orifice"] and opts["log_scale"] == ["orifice"] and opts["limited"] == "exclude"
    row = next(i for i in range(ccd.roles_table.rowCount()) if ccd.roles_table.item(i, 0).text().startswith("Orifice"))
    ccd.roles_table.cellWidget(row, 3).setChecked(False)
    assert ccd.models_and_options()[1]["log_scale"] == []
    ccd.roles_table.cellWidget(row, 3).setChecked(True)
    ccd.limited_combo.setCurrentIndex(ccd.limited_combo.findData("delivered"))
    assert ccd.models_and_options()[1]["limited"] == "delivered"
    ccd.limited_combo.setCurrentIndex(ccd.limited_combo.findData("exclude"))


def test_a_validation_tick_leaves_the_fit_and_is_saved(app, ccd):
    i = next(i for i in range(33) if ccd.table.item(i, 2).text().startswith("centre"))
    path = ccd.table.item(i, 0).data(Qt.ItemDataRole.UserRole)
    ccd.table.item(i, _col(ccd, "Validation")).setCheckState(Qt.CheckState.Checked)
    pump(app, lambda: not ccd._pending)
    assert any(str(p) == path for p in ccd.design.validation)
    saved = json.loads((ccd.root / "out" / rdet.DESIGN_FILENAME).read_text())
    assert path in saved["validation"]
    i = next(i for i in range(33) if ccd.table.item(i, 0).data(Qt.ItemDataRole.UserRole) == path)
    ccd.table.item(i, _col(ccd, "Validation")).setCheckState(Qt.CheckState.Unchecked)
    pump(app, lambda: not ccd._pending)
    assert not ccd.design.validation


def test_the_builder_exports_the_example_and_the_design_compares_with_it(app, ccd):
    ccd.load_example()
    assert ccd.build_sheet() and ccd.preview.rowCount() == 33
    files = ccd.export_sheet()
    assert {p.name for p in files} == {"run_sheet.csv", "run_sheet.xlsx", "run_sheet.md"}
    assert (ccd.root / "out" / rb.SHEET_FILENAME).is_file()
    sheet_col = _col(ccd, "Sheet")
    statuses = [ccd.table.item(i, sheet_col).text() for i in range(33)]
    assert all(s.endswith(rb.PLANNED) for s in statuses)              # the fake day WAS that sheet


def test_a_bad_plan_says_why(ccd):
    ccd.load_example()
    ccd.build_table.item(0, 4).setText("13000")                         # gas high beyond the rig
    assert not ccd.build_sheet() and "outside what the rig can set" in ccd.build_summary.text()
    ccd.load_example()


def test_analyse_writes_everything_and_lists_what_to_run_next(app, ccd):
    assert ccd.analyse_blocker() is None
    ccd.analyse()
    pump(app, lambda: not ccd.controller.busy and ccd.controller.last is not None, timeout=600)
    d = ccd.controller.last
    assert d.ok, d.problems
    names = {p.name for p in (ccd.root / "out").iterdir()}
    assert {"rsm_report.md", "rsm_deck.pptx", "next_runs.xlsx", "rsm_analysis.xlsx"} <= names
    assert ccd.recs.count() >= 1 and ccd.recs.item(0).text().startswith("Confirm the best setting")
    assert all(b.isEnabled() for b in ccd.open_btns.values())
    assert "Best setting: Gas flow (sccm)" in ccd.analyse_label.text()


def test_the_l9_defaults_to_the_gas_x_feed_trial(app):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        fakes.make_measured_l9x3(root)
        bt = BatchTab()
        tab = RsmTab(bt.runs_pane)
        bt.runs_pane.add_paths([root / "2026" / "10" / "05"])
        pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.list.count() == 27)
        assert "use the Taguchi tab" in tab.banner.text() and "Model page" in tab.banner.text()
        m = tab.read_model()
        assert m["roles"] == {"sccm": "surface", "sps": "surface", "rpm": "nuisance-quadratic"} and m["compare"]
        models, _ = tab.models_and_options()
        assert [mm.name for mm in models] == ["(a) Gas flow × Silicone + Bubbler RPM as nuisance terms",
                                              "(b) Gas flow × Silicone only (nuisance factors pooled into the error)"]


def test_the_guide_is_shown(app):
    bt = BatchTab()
    tab = RsmTab(bt.runs_pane)
    guide = tab.tabs.widget(tab.tabs.count() - 1)
    assert "Step 1: build the run sheet" in guide.toPlainText()


# ---- the goals table: worst scores 0, best scores 1, whatever the aim --------------------------------------------

def _goal_row(tab, key):
    return next(i for i in range(tab.goals_table.rowCount()) if tab.goals_table.item(i, 0).data(ROLE_PATH) == key)


def _scores(g, ys, observed=(0.0, 100.0)):
    from src.ai.Taguchi_Analysis_UI import rsm_stats as rs
    lo = g["low"] if g["low"] is not None else observed[0]
    hi = g["high"] if g["high"] is not None else observed[1]
    return [round(float(v), 3) for v in rs.Goal(g["key"], g["direction"], lo, hi, g.get("target")).d(ys)]


def test_goal_ends_mean_worst_and_best_for_every_aim():
    """Found 2026-10-11: typed ends on a Minimise goal went in unswapped, so the ramp was empty and the
    goal scored 1 everywhere (silently ignored); a target had nowhere to go."""
    mx = goal_for_fit({"key": "atom", "aim": "max", "worst": 10.0, "best": 25.0})
    mn = goal_for_fit({"key": "d32", "aim": "min", "worst": 60.0, "best": 30.0})
    tg = goal_for_fit({"key": "d32", "aim": "target", "worst": 35.0, "best": 40.0})
    assert _scores(mx, [5, 10, 17.5, 25, 40]) == [0, 0, 0.5, 1, 1]
    assert _scores(mn, [70, 60, 45, 30, 20]) == [0, 0, 0.5, 1, 1]
    assert _scores(tg, [30, 35, 37.5, 40, 42.5, 45, 50]) == [0, 0, 0.5, 1, 0.5, 0, 0]
    assert goal_for_fit({"key": "d32", "aim": "min", "worst": None, "best": None})["low"] is None   # observed range
    old = goal_for_fit({"key": "d32", "aim": "min", "low": 60.0, "high": 30.0})     # a file saved before the fix
    assert (old["low"], old["high"]) == (30.0, 60.0)
    for aim, worst, best in (("max", 25.0, 10.0), ("min", 30.0, 60.0)):
        with pytest.raises(ValueError, match="worst"):
            goal_for_fit({"key": "d32", "aim": aim, "worst": worst, "best": best})


def test_the_goals_table_reaches_the_analysis_and_a_backwards_ramp_is_refused(app, ccd):
    i = _goal_row(ccd, "d_mean")
    aim = ccd.goals_table.cellWidget(i, 1)
    was = aim.currentData()                                       # not a default goal since 2026-10-14
    aim.setCurrentIndex(aim.findData("min"))
    ccd.goals_table.item(i, 2).setText("60")
    ccd.goals_table.item(i, 3).setText("30")
    ccd.goals_table.item(i, 4).setText("2")
    g = next(x for x in ccd.models_and_options()[1]["goals"] if x["key"] == "d_mean")
    assert (g["direction"], g["low"], g["high"], g["importance"]) == ("min", 30.0, 60.0, 2.0)
    saved = json.loads((ccd.root / "out" / "rsm_model.json").read_text())
    assert next(x for x in saved["goals"] if x["key"] == "d_mean")["worst"] == 60.0
    ccd.goals_table.item(i, 2).setText("20")                     # worst below best on a Minimise goal
    ccd.analyse()
    assert "must be above best" in ccd.analyse_label.text() and "Mean diameter" in ccd.analyse_label.text()
    ccd.goals_table.item(i, 2).setText("")                        # put it back for the other tests
    ccd.goals_table.item(i, 3).setText("")
    ccd.goals_table.item(i, 4).setText("1")
    aim.setCurrentIndex(aim.findData(was))
