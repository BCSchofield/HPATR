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


def test_thursdays_sheet_as_run_is_the_bead_captures():
    """2026-10-15 as run (lab PC, b55c142): no silicone; the Cd tests were run first and dropped from the sheet,
    the spray runs postponed (they are in 057a0f3's sheet). Left: one capture per single-size sandwich at focus,
    then the mixed sandwich through focus, all 1 s captures saved under Calibration/Imaging Work."""
    rows = rs.load(THURSDAY)
    assert len(rows) == 36 and all(r.notes.startswith("BEAD") for r in rows)
    assert [r.notes for r in rows[:5]] == [f"BEAD {s} z0" for s in ("155.8", "98.1", "76.39", "56.28", "37.36")]
    assert rows[5].notes == "BEAD mix z-8.00" and rows[-1].notes == "BEAD mix z+8.00"
    assert all(r.folder_parts() == ["Calibration", "Imaging Work"] and r.post_trigger_s == 1 for r in rows)
    assert all(r.gas == 0 and not r.static and r.travel == 0.5 for r in rows)  # a nudge, so the trigger fires
    assert not any("fall" in r.notes for r in rows) and "PCC" in rows[-1].instructions  # pours: PCC, not here
    assert not any("run " in r.notes.lower() for r in rows)          # "run N" would read as a CCD-day run


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
