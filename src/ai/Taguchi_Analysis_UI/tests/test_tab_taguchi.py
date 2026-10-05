"""The Taguchi tab, headless: real item edits, ticks, saving and restoring."""
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

from src.ai.Taguchi_Analysis_UI import design as dz
from src.ai.Taguchi_Analysis_UI import theme
from src.ai.Taguchi_Analysis_UI.app import BatchTab, MainWindow
from src.ai.Taguchi_Analysis_UI.tab_taguchi import FIXED_COLS, TaguchiTab
from src.ai.Taguchi_Analysis_UI.tests import fakes

REAL_DAY = Path("/Volumes/LaCie/Experiments/2026/10/05")
needs_lacie = pytest.mark.skipif(not REAL_DAY.is_dir(), reason="LaCie not mounted")


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


def make(app, tmp, notes=lambda n, t, r: f"Taguchi ReRun {t} - Repeat {r}", only=None):
    bt = BatchTab()
    tab = TaguchiTab(bt.runs_pane)
    tab.messages = []
    tab.log = lambda text, level="info": tab.messages.append((level, text))
    tab.ask_yes = lambda text: True
    rows = [x for x in fakes.REAL_10_05 if only is None or only(x)]
    for name, t, r in rows:
        fakes.make_run(tmp, name, notes=notes(name, t, r))
    bt.runs_pane.add_paths([tmp / "2026" / "10" / "05"])
    pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.list.count() == len(rows))
    tab.bt = bt
    return tab


def col(tab, text):
    return next(i for i in range(tab.table.columnCount())
                if tab.table.horizontalHeaderItem(i).text() == text)


def row_of(tab, prefix):
    for i in range(tab.table.rowCount()):
        if tab.table.item(i, 1).text().split()[-1].startswith(prefix):
            return i
    raise KeyError(prefix)


def findings(tab):
    return [tab.findings.item(i).text() for i in range(tab.findings.count())]


# ---- rendering --------------------------------------------------------------------------------

def test_a_clean_9x3_is_shown_grouped_by_condition_with_a_green_banner(app, tmp):
    tab = make(app, tmp)
    assert tab.table.rowCount() == 27
    assert "27 runs = 9 conditions × 3 replicates" in tab.banner.text()
    assert "two independent ways" in tab.banner.text() and "#8be9a8" in tab.banner.styleSheet()
    heads = [tab.table.horizontalHeaderItem(i).text() for i in range(tab.table.columnCount())]
    assert heads == ["Use", "Run", "Condition", "Rep", "Gas flow (sccm)", "Bubbler RPM",
                     "Silicone (steps/s)", "Cross-check"]
    conds = [tab.table.item(i, 2).text() for i in range(27)]
    assert conds == sorted(conds, key=lambda c: conds.index(c))       # contiguous groups
    assert [c for c in dict.fromkeys(conds)] == [f"T{i}" for i in range(1, 10)] or len(set(conds)) == 9
    reps = [tab.table.item(i, 3).text() for i in range(27)]
    assert reps[:3] == ["1", "2", "3"]
    assert all(tab.table.item(i, 7).text().startswith("agrees") for i in range(27))
    assert all(tab.table.item(i, 0).checkState() == Qt.CheckState.Checked for i in range(27))
    assert all(f.startswith(("✔")) for f in findings(tab))


def test_the_trap_run_sits_with_its_own_condition_not_in_folder_order(app, tmp):
    tab = make(app, tmp)
    r = row_of(tab, "112253")                       # ReRun 4 Repeat 3, listed after ReRun 5 Repeat 1
    assert tab.table.item(r, 2).text() == "T4" and tab.table.item(r, 3).text() == "3"
    assert tab.table.item(r - 1, 2).text() == "T4"


def test_the_findings_list_has_no_horizontal_scrollbar(app, tmp):
    tab = make(app, tmp)
    assert tab.findings.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


# ---- editing -------------------------------------------------------------------------------------

def test_unticking_a_run_leaves_it_out_and_updates_the_banner(app, tmp):
    tab = make(app, tmp)
    r = row_of(tab, "090432")
    tab.table.item(r, 0).setCheckState(Qt.CheckState.Unchecked)
    pump(app)
    assert "26 runs" in tab.banner.text() and "unbalanced" in tab.banner.text()
    dropped = tab.table.item(row_of(tab, "090432"), 7).text()
    assert dropped.startswith("dropped")
    assert any("not used equally often" in f for f in findings(tab))


def test_typing_a_level_overrides_it_and_the_cross_check_notices(app, tmp):
    tab = make(app, tmp)
    c = col(tab, "Gas flow (sccm)")
    r = row_of(tab, "090432")
    tab.table.item(r, c).setText("6000")
    pump(app)
    r = row_of(tab, "090432")
    item = tab.table.item(r, c)
    assert item.text() == "6000" and item.font().italic() and "EDITED by you" in item.toolTip()
    assert tab.table.item(r, 7).text().startswith("CONFLICT")
    assert "DISAGREE" in tab.banner.text() and "#ff453a" in tab.banner.styleSheet()
    tab.table.item(r, c).setText("3000")             # typing the detected value back
    pump(app)
    assert not tab.design.rows[0].overrides and "two independent ways" in tab.banner.text()


def test_clearing_an_override_cell_reverts_it(app, tmp):
    tab = make(app, tmp)
    c, r = col(tab, "Bubbler RPM"), row_of(tab, "090432")
    tab.table.item(r, c).setText("450"); pump(app)
    r = row_of(tab, "090432")
    tab.table.item(r, c).setText(""); pump(app)
    assert not any(row.overrides for row in tab.design.rows)


def test_a_word_in_a_numeric_cell_makes_the_factor_categorical(app, tmp):
    tab = make(app, tmp)
    c, r = col(tab, "Bubbler RPM"), row_of(tab, "090432")
    tab.table.item(r, c).setText("high"); pump(app)
    assert tab.design.factor("rpm").numeric is False
    assert tab.design.rows[0].value("rpm") == "high"


def test_a_cell_edit_never_destroys_the_table_inside_its_own_handler(app, tmp):
    """The same use-after-free that segfaulted the output tree: rebuilding the table from
    inside itemChanged. The rebuild must wait a turn of the event loop."""
    tab = make(app, tmp)
    item = tab.table.item(row_of(tab, "090432"), col(tab, "Bubbler RPM"))
    item.setText("450")                               # fires itemChanged synchronously
    assert item.tableWidget() is tab.table, "the item was destroyed inside its own change handler"
    pump(app)
    assert tab.design.rows[0].overrides == {"rpm": 450}


def test_an_unassigned_run_is_listed_first_and_fixed_by_typing_its_level(app, tmp):
    tab = make(app, tmp)
    tab.design.rows[0].detected["rpm"] = None
    tab.rebuild()
    assert tab.table.item(0, 7).text().startswith("UNASSIGNED")
    assert "cannot be assigned yet" in tab.banner.text()
    assert tab.table.item(0, col(tab, "Bubbler RPM")).text() == ""
    tab.table.item(0, col(tab, "Bubbler RPM")).setText("300"); pump(app)
    assert not any(tab.table.item(i, 7).text().startswith("UNASSIGNED") for i in range(tab.table.rowCount()))
    assert "two independent ways" in tab.banner.text()


def test_rename_a_factor_through_the_header(app, tmp):
    tab = make(app, tmp)
    tab.ask_text = lambda title, label, text="": "Silicone flow (steps/s)"
    tab._header_double_clicked(col(tab, "Silicone (steps/s)"))
    assert tab.table.horizontalHeaderItem(col(tab, "Silicone flow (steps/s)")) is not None
    assert any("Silicone flow" in f for f in findings(tab))
    tab.ask_text = lambda title, label, text="": None                   # cancelled dialog
    tab._header_double_clicked(col(tab, "Silicone flow (steps/s)"))
    assert tab.design.factor("sps").label == "Silicone flow (steps/s)"
    tab.ask_text = lambda title, label, text="": "Gas flow (sccm)"        # a duplicate name
    tab._header_double_clicked(col(tab, "Silicone flow (steps/s)"))
    assert any("already called" in m for _, m in tab.messages)
    assert tab.design.factor("sps").label == "Silicone flow (steps/s)"


def test_add_and_remove_a_factor(app, tmp):
    tab = make(app, tmp)
    assert tab.add_factor("GLR")
    assert col(tab, "GLR") == FIXED_COLS + 3 and tab.table.columnCount() == 9
    glr = tab.table.item(0, col(tab, "GLR")).text()
    assert float(glr) == pytest.approx(0.2819)
    assert not tab.add_factor("GLR")                                    # already there
    assert any("already a factor" in m for _, m in tab.messages)
    tab.remove_factor("wb:GLR")
    assert tab.table.columnCount() == 8
    tab.remove_factor("rpm")
    assert "Bubbler RPM" not in [tab.table.horizontalHeaderItem(i).text() for i in range(7)]


def test_the_add_menu_offers_unused_fields_only(app, tmp):
    tab = make(app, tmp)
    ids = [k for k, _ in tab.design.candidates()]
    assert "sccm" not in ids and "orifice" in ids and "Motor Travel (mm)" in ids and "FPS" in ids
    tab.add_factor("orifice")
    assert "orifice" not in [k for k, _ in tab.design.candidates()]


def test_leave_out_runs_with_no_trial_button(app, tmp):
    names = [x for x in fakes.REAL_10_05 if x[2] == 1]
    tab = make(app, tmp, only=lambda x: x in names,
               notes=lambda n, t, r: f"Taguchi {t}")
    fakes.make_run(tmp, "101035_4500sccm_500rpm_6000sps_or1.2_nobh", notes="")
    fakes.make_run(tmp, "120606_9000sccm_900rpm_8000sps_or1.2_bh1", notes="MAX TEST")
    tab.bt.runs_pane.add_paths([tmp / "2026" / "10" / "05"])
    pump(app, lambda: not tab.bt.runs_pane._busy and tab.bt.runs_pane.list.count() == 11)
    assert tab.stray_btn.isEnabled() and tab.stray_btn.text() == "Leave out 2 runs with no trial"
    assert any("side tests" in f for f in findings(tab))
    tab.stray_btn.click()
    assert not tab.stray_btn.isEnabled()
    assert "9 conditions" in tab.banner.text() and "dropped" in tab.table.item(10, 7).text()
    assert not any("ALIASED" in f for f in findings(tab))
    assert any("left out 2 run(s)" in m for _, m in tab.messages)


def test_reset_asks_first_and_can_be_cancelled(app, tmp):
    tab = make(app, tmp)
    tab.add_factor("GLR")
    tab.ask_yes = lambda text: False
    tab.reset()
    assert tab.design.has("wb:GLR")
    tab.ask_yes = lambda text: True
    tab.reset()
    assert not tab.design.has("wb:GLR") and not tab.design.customised


# ---- following the Batch tab ----------------------------------------------------------------------

def test_edits_survive_a_change_of_selection_on_the_batch_tab(app, tmp):
    tab = make(app, tmp)
    tab.rename_factor("sps", "Silicone flow")
    tab.table.item(row_of(tab, "090432"), col(tab, "Bubbler RPM")).setText("450"); pump(app)
    rp = tab.bt.runs_pane
    rp.list.item(26).setCheckState(Qt.CheckState.Unchecked)             # untick the last run
    pump(app)
    assert tab.table.rowCount() == 26 and tab.design.factor("sps").label == "Silicone flow"
    assert tab.design.rows[0].overrides == {"rpm": 450}


# ---- saving and restoring ----------------------------------------------------------------------------

def test_edits_are_saved_to_the_output_folder_and_restored_next_time(app, tmp):
    tab = make(app, tmp)
    assert "choose an output folder" in tab.save_label.text()
    out = tmp / "out"
    tab.bt.runs_pane.set_output_folder(out, remember=False)
    pump(app)
    tab.rename_factor("sps", "Silicone flow")
    tab.add_factor("Flow Range (sccm)")
    tab.table.item(row_of(tab, "090432"), 0).setCheckState(Qt.CheckState.Unchecked)
    pump(app)
    saved = json.loads((out / "taguchi_design.json").read_text())
    assert saved["customised"] and any(r["included"] is False for r in saved["runs"])
    assert tab.save_label.text() == "saved: taguchi_design.json"

    again = make(app, tmp / "second")                  # "reopening the app": fresh tab, same runs
    for name, t, r in fakes.REAL_10_05[:0]:
        pass
    again.bt.runs_pane.clear()
    again.bt.runs_pane.add_paths([tmp / "2026" / "10" / "05"])
    pump(app, lambda: not again.bt.runs_pane._busy and again.bt.runs_pane.list.count() == 27)
    again.bt.runs_pane.set_output_folder(out, remember=False)
    pump(app)
    assert again.design.factor("sps").label == "Silicone flow"
    assert again.design.has("wb:Flow Range (sccm)")
    assert next(r for r in again.design.rows if r.name.startswith("090432")).included is False
    assert any("restored your edits" in m for _, m in again.messages)


def test_a_save_failure_is_reported_not_raised(app, tmp, monkeypatch):
    tab = make(app, tmp)
    monkeypatch.setattr(dz, "save", lambda d, o: (_ for _ in ()).throw(OSError("disk full")))
    tab.output_dir = tmp / "out"
    tab.rebuild()
    assert "could not save the design: disk full" in tab.save_label.text()
    assert any(level == "error" and "disk full" in m for level, m in tab.messages)


# ---- in the window ------------------------------------------------------------------------------------------

def test_the_main_window_has_the_tab_wired_to_the_console(app, tmp):
    w = MainWindow()
    try:
        names = [w.centralWidget().tabText(i).strip() for i in range(3)]
        assert names == ["Batch", "Taguchi", "Settings"]
        assert isinstance(w.taguchi_tab, TaguchiTab)
        w.taguchi_tab.log("hello from the design tab", "warn")
        w.batch_tab.console._flush()
        assert "hello from the design tab" in w.batch_tab.console.text.toPlainText()
    finally:
        w.close()


@needs_lacie
def test_real_10_05_in_the_tab(app):
    bt = BatchTab()
    tab = TaguchiTab(bt.runs_pane)
    bt.runs_pane.add_paths([REAL_DAY])
    pump(app, lambda: not bt.runs_pane._busy and bt.runs_pane.list.count() == 27)
    assert "27 runs = 9 conditions × 3 replicates" in tab.banner.text()
    assert all(tab.table.item(i, 7).text().startswith("agrees") for i in range(27))
