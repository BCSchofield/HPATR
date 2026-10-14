"""GUI_Clean's run sheet (2026-10-14): gui/run_sheet.py reads a sheet (the analysis app's next_runs.csv, or a
hand-made one), keeps progress on the local disk, and the Run sheet tab fills in each run. The question after a
run comes only once the run is saved to master_log, and the next run's Notes never reach the saved run's row."""
from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import paths

paths.ensure_src_on_path()
from gui import run_sheet as rs  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
THURSDAY = REPO / "docs" / "notes" / "2026-10-15_thursday_run_sheet.csv"


def _write(path: Path, head, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)
    return path


# ---- the sheet ----------------------------------------------------------------------------------------------

def test_the_analysis_apps_next_runs_csv_loads_as_it_is(tmp_path):
    head = ["Run", "Recommendation", "Why this run", "Gas flow (sccm)", "Bubbler RPM", "Silicone (steps/s)",
            "Orifice (mm)", "predicted Atomised fraction by area, classical (%)", "extrapolated", "Notes to type"]
    p = _write(tmp_path / "next_runs.csv", head,
               [[1, "Confirm the best setting", "Confirmation 1 of 3", 11000, 100, 5000, 1.2, 20.3, "", "CCD next 1"],
                ["", "", "", "", "", "", "", "", "", ""],                       # a blank line is not a run
                [2, "Steepest ascent", "Step 1", 12000, 0, 5300, 1.2, 22.0, "yes", "CCD next 2"]])
    rows = rs.load(p)
    assert [r.number for r in rows] == ["1", "2"]
    assert rows[0].fields() == {"flow": "11000", "rpm": "100", "speed": "5000", "orifice": "1.2mm",
                                "notes": "CCD next 1"}
    assert rows[1].fields()["rpm"] == "" and rows[1].instructions == "Step 1"     # rpm 0: the box is cleared


def test_thursdays_sheet_is_valid_and_its_cd_tests_are_static_runs():
    rows = rs.load(THURSDAY)
    assert len(rows) == 57 and sum(r.notes.startswith("BEAD") for r in rows) == 43
    assert not any("fall" in r.notes for r in rows)                           # falling beads: in PCC, not here
    assert "PCC" in rows[-1].instructions
    cd = [r for r in rows if r.notes.startswith("CD TEST")]
    assert [r.orifice for r in cd] == [1.2, 0.8, 0.5] and all(r.static and r.rpm is None for r in cd)
    spray = [r for r in rows if r.notes.startswith("S2 #")]
    assert len(spray) == 10 and all(not r.static for r in spray)
    first_bead = next(i for i, r in enumerate(rows) if r.notes.startswith("BEAD"))
    assert all(r.notes.startswith("BEAD") for r in rows[first_bead:])        # all the bead work at the end
    assert not any("run " in r.notes.lower() for r in rows)          # "run N" would read as a CCD-day run
    assert all(r.travel >= 36 * r.feed / 5000 - 0.5 for r in spray if r.feed > 5000)   # >= ~49 s per run


def test_a_sheet_without_gas_or_feed_is_refused_with_a_reason(tmp_path):
    p = _write(tmp_path / "bad.csv", ["Run", "Notes"], [[1, "x"]])
    with pytest.raises(rs.SheetError, match="no column for gas or feed"):
        rs.load(p)


def test_progress_moves_on_redoes_and_wraps(tmp_path):
    p = rs.Progress.new("s.csv", 4)
    assert p.finish(0, True, "runA") == 1 and p.current == 1
    assert p.finish(1, False, "runB") == 1 and p.status[1] == rs.REDO          # stays on the same row
    assert p.finish(1, True, "runC") == 2 and p.folders["1"] == ["runB", "runC"]
    p.status[3] = rs.SKIPPED
    assert p.finish(2, True, "runD") is None and p.counts()["done"] == 3       # nothing open: the sheet is done
    p.status[0] = rs.REDO
    assert p.next_open(2) == 0                                                  # wraps round to an open row
    rs.save_state(p, tmp_path / "state.json")
    back = rs.load_state(4, "s.csv", tmp_path / "state.json")
    assert back.status == p.status and back.folders == p.folders
    assert rs.load_state(5, "s.csv", tmp_path / "state.json") is None          # the sheet changed
    assert rs.load_state(4, "other.csv", tmp_path / "state.json") is None


def test_differences_name_what_was_run_against_the_sheet():
    row = rs.Row("2", 1.2, 11000.0, 100.0, 5000.0, 36.0, None, "S2 #02 confirm")
    cond = {"flow_entry": "11000", "speed_str": "5000", "rpm_str": "100", "orifice": "1.2mm", "distance_str": "36"}
    assert rs.differences(row, cond) == []
    assert rs.differences(row, dict(cond, flow_entry="12000", orifice="0.8mm")) == \
        ["gas 12000 (sheet 11000)", "insert 0.8mm (sheet 1.2mm)"]
    static = rs.Row("Cd", 1.2, 2000.0, None, 0.0, None, None, "CD TEST 1.2 mm")
    assert rs.differences(static, {"flow_entry": "2000", "speed_str": "0", "rpm_str": "", "orifice": "1.2mm",
                                   "distance_str": "0"}) == []


# ---- the tab, in the real window (offscreen, in its own process) -------------------------------------------

def test_the_run_sheet_tab_and_master_log_button_in_the_real_window(tmp_path):
    """The tab's flows and the top bar's master_log button run in GUI_Clean's real window, in a separate Python process
    (tests/gui_window_checks.py). Deleting that window crashes Qt, the committed GUI too (2026-10-14:
    building and deleting it in one process segfaults), so the checks process exits without tearing Qt down."""
    import subprocess
    import sys
    pytest.importorskip("PySide6")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HPATR_RUN_SHEET_STATE=str(tmp_path / "state.json"))
    p = subprocess.run([sys.executable, str(Path(__file__).with_name("gui_window_checks.py"))],
                       capture_output=True, text=True, env=env, cwd=str(REPO), timeout=300)
    out = p.stdout + p.stderr
    assert p.returncode == 0 and "ALL WINDOW CHECKS PASSED" in p.stdout, out[-4000:]
    assert out.count("PASS ") == 9, out[-4000:]
