"""Headless tests for the right pane: real mouse clicks and real pixels.

Two of these exist because a bug was found only by rendering the window: the one
tickable control was invisible on the dark theme, and the "+" button was blank.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from src.ai.Taguchi_Analysis_UI import output_tree as ot
from src.ai.Taguchi_Analysis_UI import pane_outputs, pane_runs, theme
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI.app import BatchTab
from src.ai.Taguchi_Analysis_UI.tests import fakes


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_fusion_style(a)
    return a


@pytest.fixture
def pane(app):
    p = pane_outputs.OutputsPane()
    p.resize(800, 720)
    p.show()
    app.processEvents()
    p.signals = []
    p.options_changed.connect(p.signals.append)
    return p


def item_for(pane, output_id):
    stack = [pane.tree.topLevelItem(i) for i in range(pane.tree.topLevelItemCount())]
    while stack:
        it = stack.pop()
        if it.data(0, pane_outputs.ROLE_OUTPUT) == output_id:
            return it
        stack += [it.child(i) for i in range(it.childCount())]
    raise KeyError(output_id)


def click_box(app, pane, output_id):
    it = item_for(pane, output_id)
    pane.tree.scrollToItem(it)
    app.processEvents()
    r = pane.tree.visualItemRect(it)
    QTest.mouseClick(pane.tree.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(r.left() + 10, r.center().y()))
    app.processEvents()


def pixels_differing(img, rect, bg: QColor, tol=40):
    n = 0
    for x in range(max(rect.left(), 0), min(rect.right(), img.width())):
        for y in range(max(rect.top(), 0), min(rect.bottom(), img.height())):
            c = QColor(img.pixel(x, y))
            if abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue()) > tol:
                n += 1
    return n


def box_rect(pane, output_id):
    r = pane.tree.visualItemRect(item_for(pane, output_id))
    from PySide6.QtCore import QRect
    return QRect(r.left() + 2, r.center().y() - 8, pane_outputs.BOX + 3, 16)


# ---- structure ------------------------------------------------------------------

def test_default_pane_matches_the_contract_defaults(pane):
    assert pane.options() == spec.default_options()
    st = pane.states()
    assert st["droplet_sizes"] == ot.LOCKED_ON and st["meas_all"] == ot.OFF


def test_locked_rows_are_disabled_checked_and_optional_rows_are_tickable(pane):
    locked = item_for(pane, "droplet_sizes")
    assert not (locked.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert locked.checkState(0) == Qt.CheckState.Checked
    opt = item_for(pane, "meas_all")
    assert opt.flags() & Qt.ItemFlag.ItemIsEnabled and opt.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert opt.checkState(0) == Qt.CheckState.Unchecked


def test_native_check_indicator_is_stripped_so_rows_never_draw_two_boxes(pane):
    d = pane.tree.itemDelegateForColumn(0)
    for oid in ("droplet_sizes", "meas_all"):
        opt = QStyleOptionViewItem()
        d.initStyleOption(opt, pane.tree.indexFromItem(item_for(pane, oid), 0))
        assert not (opt.features & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator), oid


def test_headings_span_the_full_width(pane):
    for i in range(pane.tree.topLevelItemCount()):
        assert pane.tree.topLevelItem(i).isFirstColumnSpanned()


# ---- real clicks --------------------------------------------------------------------

def test_clicking_every_frame_ticks_both_boxes_and_supersedes_the_extremes(app, pane):
    click_box(app, pane, "meas_all")
    assert pane.options()["images"] == "all"
    st = pane.states()
    assert st["meas_all"] == st["clas_all"] == ot.ON
    assert st["meas_extremes"] == st["clas_extremes"] == ot.SUPERSEDED
    assert len(pane.signals) == 1 and pane.signals[0]["images"] == "all"


def test_a_tick_never_destroys_the_item_while_its_handler_is_still_running(app, pane):
    """The bug: the tree was rebuilt synchronously inside itemChanged, i.e. inside the
    delegate's editorEvent, freeing the item the delegate was still using. That is
    undefined behaviour and it segfaulted. The rebuild must wait for the event loop."""
    it = item_for(pane, "meas_all")
    it.setCheckState(0, Qt.CheckState.Checked)            # fires itemChanged synchronously
    assert it.treeWidget() is pane.tree, "item was destroyed inside its own change handler"
    assert pane.signals == []                              # nothing has happened yet ...
    app.processEvents()                                    # ... until the event loop turns
    assert pane.options()["images"] == "all" and len(pane.signals) == 1


def test_rapid_ticks_coalesce_into_one_rebuild_with_the_right_result(app, pane):
    item_for(pane, "flat_csvs").setCheckState(0, Qt.CheckState.Checked)
    item_for(pane, "odd_pack").setCheckState(0, Qt.CheckState.Checked)
    app.processEvents()
    assert pane.options() == dict(spec.default_options(), flat_csvs=True, odd_pack=True)
    assert len(pane.signals) == 1                          # one notification for the burst


def test_clicking_the_other_every_frame_box_unticks_both_again(app, pane):
    click_box(app, pane, "meas_all")
    click_box(app, pane, "clas_all")
    assert pane.options() == spec.default_options()
    assert pane.states()["meas_extremes"] == ot.LOCKED_ON
    assert [s["images"] for s in pane.signals] == ["all", "extremes"]


def test_one_click_toggles_exactly_once(app, pane):
    click_box(app, pane, "flat_csvs")
    assert pane.options()["flat_csvs"] is True and len(pane.signals) == 1


def test_clicking_a_locked_row_does_nothing(app, pane):
    for oid in ("droplet_sizes", "predictions", "meas_extremes", "report_md"):
        click_box(app, pane, oid)
    assert pane.options() == spec.default_options() and pane.signals == []
    assert pane.states()["droplet_sizes"] == ot.LOCKED_ON


def test_clicking_a_superseded_row_does_nothing(app, pane):
    click_box(app, pane, "meas_all")
    pane.signals.clear()
    click_box(app, pane, "meas_extremes")
    assert pane.options()["images"] == "all" and pane.signals == []


def test_optional_campaign_outputs_toggle_independently(app, pane):
    click_box(app, pane, "odd_pack")
    assert pane.options() == dict(spec.default_options(), odd_pack=True)
    click_box(app, pane, "flat_csvs")
    assert pane.options() == dict(spec.default_options(), odd_pack=True, flat_csvs=True)


def test_cost_label_follows_the_ticks(app, pane):
    assert "Every frame" not in pane.cost_label.text()
    click_box(app, pane, "meas_all")
    assert "“Every frame” adds" in pane.cost_label.text()
    click_box(app, pane, "meas_all")
    assert "Extreme frames only" in pane.cost_label.text()


def test_set_ticks_repaints_and_notifies(pane):
    pane.set_ticks(spec.ticks_for(dict(spec.default_options(), images="all")))
    assert pane.states()["clas_all"] == ot.ON and pane.signals[-1]["images"] == "all"


def test_context_changes_the_headings_but_never_the_ticks(app, pane):
    click_box(app, pane, "meas_all")
    pane.set_context(run_name="090432_3000sccm_300rpm_4000sps_or1.2_bh1", thr=0.30, n_runs=27,
                     output_dir="/tmp/out")
    head = [pane.tree.topLevelItem(i).text(0) for i in range(2)]
    assert "090432_3000sccm" in head[0] and "each of 27 run folders" in head[0]
    assert "/tmp/out" in head[1]
    assert pane.options()["images"] == "all"                       # ticks survive a context change
    assert "27 runs" in pane.cost_label.text()


# ---- real pixels ----------------------------------------------------------------------

def test_an_unticked_optional_box_is_actually_visible(app, pane):
    """The bug: Fusion's unchecked box matched the dark field colour, so the only
    clickable control could not be seen."""
    img = pane.tree.viewport().grab().toImage()
    bg = QColor(theme.CLR_INPUT)
    for oid in ("meas_all", "flat_csvs"):
        pane.tree.scrollToItem(item_for(pane, oid))
        app.processEvents()
        img = pane.tree.viewport().grab().toImage()
        assert pixels_differing(img, box_rect(pane, oid), bg) >= 20, f"{oid}: no visible box"


def test_locked_rows_draw_a_grey_box_and_ticked_rows_a_blue_one(app, pane):
    click_box(app, pane, "meas_all")
    bg = QColor(theme.CLR_INPUT)

    def dominant(oid):
        pane.tree.scrollToItem(item_for(pane, oid)); app.processEvents()
        img = pane.tree.viewport().grab().toImage()
        r = box_rect(pane, oid)
        cols = [QColor(img.pixel(x, y)) for x in range(r.left(), r.right())
                for y in range(r.top(), r.bottom())]
        cols = [c for c in cols if abs(c.red() - bg.red()) + abs(c.green() - bg.green())
                + abs(c.blue() - bg.blue()) > 60]
        return cols

    locked = dominant("droplet_sizes")
    assert len(locked) >= 40
    assert all(abs(c.red() - c.blue()) < 40 for c in locked), "locked box should be neutral grey"
    blue = dominant("meas_all")
    assert sum(1 for c in blue if c.blue() > c.red() + 80) >= 40, "ticked box should be accent blue"


def test_exactly_one_box_is_drawn_per_row(app, pane):
    """The bug: Qt's native indicator and ours both drew. The text must start right
    after ONE box width; two boxes pushed it ~2x further."""
    it = item_for(pane, "droplet_sizes")
    r = pane.tree.visualItemRect(it)
    img = pane.tree.viewport().grab().toImage()
    bg = QColor(theme.CLR_INPUT)
    start = r.left() + pane_outputs.BOX + 8                        # where the label starts
    from PySide6.QtCore import QRect
    gap = QRect(r.left() + pane_outputs.BOX + 5, r.top() + 3, 3, r.height() - 6)
    assert pixels_differing(img, gap, bg) == 0, "something (a second box?) sits in the gap"


def test_the_add_runs_button_is_not_blank(app):
    """The bug: the theme's 16px side padding clipped the '+' out of a 32px button."""
    rp = pane_runs.RunsPane()
    rp.show()
    app.processEvents()
    img = rp.add_btn.grab().toImage()
    white = sum(1 for x in range(img.width()) for y in range(img.height())
                if QColor(img.pixel(x, y)).lightness() > 220)
    assert white >= 12, "the '+' glyph is not drawn"


# ---- wired into the window ---------------------------------------------------------------

@pytest.fixture
def batch(app):
    b = BatchTab()
    b.resize(1400, 800)
    b.show()
    app.processEvents()
    return b


def load(app, runs_pane, folders, timeout=60):
    runs_pane.add_paths(folders)
    end = time.monotonic() + timeout
    while runs_pane._busy and time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
    app.processEvents()


def test_the_tree_describes_the_selected_runs_and_output_folder(app, batch):
    with tempfile.TemporaryDirectory() as tmp:
        fakes.make_l9x3(Path(tmp))
        load(app, batch.runs_pane, [Path(tmp) / "2026" / "10" / "05"])
        head = batch.outputs_pane.tree.topLevelItem(0).text(0)
        assert fakes.REAL_10_05[0][0] in head and "each of 27 run folders" in head
        assert "27 runs" in batch.outputs_pane.cost_label.text()

        batch.runs_pane.set_output_folder(Path(tmp) / "out")
        assert str(Path(tmp) / "out") in batch.outputs_pane.tree.topLevelItem(1).text(0)


def test_unticking_runs_updates_the_count_but_not_the_ticks(app, batch):
    with tempfile.TemporaryDirectory() as tmp:
        fakes.make_l9x3(Path(tmp))
        load(app, batch.runs_pane, [Path(tmp) / "2026" / "10" / "05"])
        click_box(app, batch.outputs_pane, "meas_all")
        batch.runs_pane.list.item(0).setCheckState(Qt.CheckState.Unchecked)
        head = batch.outputs_pane.tree.topLevelItem(0).text(0)
        assert "each of 26 run folders" in head
        assert fakes.REAL_10_05[1][0] in head                    # first INCLUDED run is the example
        assert batch.outputs_pane.options()["images"] == "all"


def test_the_tree_options_are_the_ones_the_pipeline_builders_use(app, batch):
    click_box(app, batch.outputs_pane, "meas_all")
    opts = batch.outputs_pane.options()
    run = Path("/x/090432_3000sccm_300rpm_4000sps_or1.2_bh1")
    cmd = spec.classical_cmd(run, spec.RunSettings(), opts)
    kw = spec.process_capture_kwargs(run, spec.RunSettings(), opts, print, cine=run / "a.cine")
    assert cmd[cmd.index("--images-mode") + 1] == "all" and kw["images"] == "all"
