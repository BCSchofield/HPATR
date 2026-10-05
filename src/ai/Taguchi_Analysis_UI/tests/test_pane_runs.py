"""Headless tests for the left pane (QT_QPA_PLATFORM=offscreen)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from src.ai.Taguchi_Analysis_UI import pane_runs
from src.ai.Taguchi_Analysis_UI.tests import fakes

REAL_DAY = Path("/Volumes/LaCie/Experiments/2026/10/05")
needs_lacie = pytest.mark.skipif(not REAL_DAY.is_dir(), reason="LaCie not mounted")
FIRST = fakes.REAL_10_05[0][0]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def root():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def pane(app):
    p = pane_runs.RunsPane()
    p.messages = []
    p.log = p.messages.append
    return p


def load(app, pane, folders, timeout=60):
    pane.add_paths(folders)
    end = time.monotonic() + timeout
    while pane._busy and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not pane._busy, "discovery did not finish"


def items(pane):
    return [pane.list.item(i) for i in range(pane.list.count())]


def test_empty_pane_shows_the_hint_not_an_empty_list(pane):
    assert pane.summary_label.text() == "0 runs selected"
    assert not pane.hint.isHidden() and pane.list.isHidden()
    assert pane.included_runs() == []


def test_a_clean_9x3_loads_ticked_and_summarised(app, pane, root):
    fakes.make_l9x3(root)
    load(app, pane, [root / "2026" / "10" / "05"])
    assert pane.list.count() == 27
    assert all(i.checkState() == Qt.CheckState.Checked for i in items(pane))
    assert len(pane.included_runs()) == 27
    assert pane.summary_label.text().startswith(
        "27 runs · 9 conditions × 3 replicates · 0 already measured")
    assert pane.hint.isHidden() and not pane.list.isHidden()
    assert not any("ERROR" in m for m in pane.messages)


def test_list_is_chronological_not_in_scan_order(app, pane, root):
    a = fakes.make_run(root, "104852_3000sccm_300rpm_4000sps_or1.2_bh1", day=("2026", "10", "01"))
    b = fakes.make_run(root, "090432_3000sccm_300rpm_4000sps_or1.2_bh1", day=("2026", "10", "05"))
    load(app, pane, [b, a])
    assert [Path(i.data(pane_runs.ROLE_PATH)) for i in items(pane)] == [a, b]
    assert items(pane)[0].text().startswith("2026-10-01")


def test_unticking_a_run_removes_it_from_included_and_the_summary(app, pane, root):
    fakes.make_l9x3(root)
    load(app, pane, [root / "2026" / "10" / "05"])
    items(pane)[0].setCheckState(Qt.CheckState.Unchecked)
    assert len(pane.included_runs()) == 26
    assert "26 runs" in pane.summary_label.text()
    assert "1 of 27 not ticked or unusable" in pane.summary_label.text()
    assert "unbalanced" in pane.summary_label.text()          # one condition now has 2


def test_a_run_with_no_cine_is_unticked_uncheckable_and_red(app, pane, root):
    fakes.make_run(root, FIRST, cines=0)
    fakes.make_run(root, fakes.REAL_10_05[1][0])
    load(app, pane, [root / "2026" / "10" / "05"])
    bad, good = items(pane)[0], items(pane)[1]
    assert not (bad.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert bad.checkState() == Qt.CheckState.Unchecked
    assert "cannot run" in bad.text()
    assert good.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert [r.name for r in pane.included_runs()] == [fakes.REAL_10_05[1][0]]
    assert any("ERROR" in m and ".cine" in m for m in pane.messages)


def test_already_measured_runs_are_labelled(app, pane, root):
    fakes.make_run(root, FIRST, analysis="current")
    fakes.make_run(root, fakes.REAL_10_05[1][0], analysis="legacy", sizer_version=None)
    load(app, pane, [root / "2026" / "10" / "05"])
    texts = [i.text() for i in items(pane)]
    assert "measured v2.1.0" in texts[0] and "measured pre-2.0.0 \u00b7 legacy folders" in texts[1]
    assert "2 already measured" in pane.summary_label.text()


def test_mixed_sizer_versions_raise_a_warning(app, pane, root):
    fakes.make_run(root, FIRST, analysis="current", sizer_version="2.0.0")
    assert pane.warn_label.isHidden()
    fakes.make_run(root, fakes.REAL_10_05[1][0], analysis="current", sizer_version="2.1.0")
    load(app, pane, [root / "2026" / "10" / "05"])
    assert not pane.warn_label.isHidden()
    assert "2.0.0" in pane.warn_label.text() and "2.1.0" in pane.warn_label.text()
    # ticking one of them off clears the conflict
    items(pane)[1].setCheckState(Qt.CheckState.Unchecked)
    assert pane.warn_label.isHidden()


def test_adding_the_same_folders_twice_does_not_duplicate(app, pane, root):
    fakes.make_l9x3(root)
    day = root / "2026" / "10" / "05"
    load(app, pane, [day])
    load(app, pane, [day, day / FIRST])
    assert pane.list.count() == 27
    assert any("already in the list" in m for m in pane.messages)


def test_adding_a_second_day_keeps_existing_tick_state(app, pane, root):
    fakes.make_run(root, FIRST)
    fakes.make_run(root, "104852_3000sccm_300rpm_4000sps_or1.2_bh1", day=("2026", "10", "01"))
    load(app, pane, [root / "2026" / "10" / "05"])
    items(pane)[0].setCheckState(Qt.CheckState.Unchecked)
    load(app, pane, [root / "2026" / "10" / "01"])
    assert pane.list.count() == 2
    states = {i.text()[:10]: i.checkState() for i in items(pane)}
    assert states["2026-10-05"] == Qt.CheckState.Unchecked
    assert states["2026-10-01"] == Qt.CheckState.Checked


def test_a_folder_with_no_runs_says_so_and_how_deep_it_looked(app, pane, root):
    (root / "empty").mkdir()
    load(app, pane, [root / "empty"])
    assert pane.list.count() == 0 and not pane.hint.isHidden()
    assert any("no run folders found" in m and "3 levels" in m for m in pane.messages), pane.messages


def test_picking_the_experiments_folder_explains_why_nothing_was_found(app, pane, root):
    fakes.make_run(root, FIRST)                      # root/2026/10/05/<run>: 4 levels down
    load(app, pane, [root])
    assert pane.list.count() == 0
    assert any("not the Experiments folder itself" in m for m in pane.messages)


def test_old_format_folders_are_logged_as_skipped(app, pane, root):
    fakes.make_run(root, FIRST)
    (root / "2026" / "10" / "05" / "110302_N6_1.0BAR" / "shadowgraph").mkdir(parents=True)
    load(app, pane, [root / "2026" / "10" / "05"])
    assert pane.list.count() == 1
    assert any("skipped 110302_N6_1.0BAR" in m for m in pane.messages)


def test_remove_and_clear(app, pane, root):
    fakes.make_l9x3(root)
    load(app, pane, [root / "2026" / "10" / "05"])
    items(pane)[0].setSelected(True)
    items(pane)[1].setSelected(True)
    pane.remove_selected()
    assert pane.list.count() == 25
    pane.clear()
    assert pane.list.count() == 0 and not pane.hint.isHidden()
    assert pane.summary_label.text() == "0 runs selected"


def test_dropping_folders_adds_them(app, pane, root):
    fakes.make_run(root, FIRST)
    pane.list.dropped.emit([root / "2026" / "10" / "05"])
    end = time.monotonic() + 30
    while (pane._busy or pane.list.count() == 0) and time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
    assert pane.list.count() == 1


def test_a_second_add_while_busy_is_ignored(app, pane, root):
    fakes.make_run(root, FIRST)
    pane._busy = True
    pane.add_paths([root / "2026" / "10" / "05"])
    assert pane.list.count() == 0 and pane.messages == []
    pane._busy = False


def test_multi_select_workaround_switches_the_dialogs_views(app, root):
    dlg = QFileDialog(None, "t", str(root))
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    assert pane_runs.enable_multi_select(dlg) >= 1


def test_output_folder_is_none_until_chosen(pane):
    assert pane.output_folder() is None
    pane.output_label.setText("/tmp/out")
    assert pane.output_folder() == Path("/tmp/out")


def test_selection_changed_fires_on_tick_changes(app, pane, root):
    fakes.make_run(root, FIRST)
    load(app, pane, [root / "2026" / "10" / "05"])
    fired = []
    pane.selection_changed.connect(lambda: fired.append(1))
    items(pane)[0].setCheckState(Qt.CheckState.Unchecked)
    assert fired


@needs_lacie
def test_real_10_05_loads_into_the_pane_as_a_clean_9x3(app, pane):
    load(app, pane, [REAL_DAY])
    assert pane.list.count() == 27 and len(pane.included_runs()) == 27
    assert pane.summary_label.text() == \
        "27 runs · 9 conditions × 3 replicates · 0 already measured"
    assert not any("ERROR" in m or "warn" in m for m in pane.messages), pane.messages
