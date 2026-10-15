"""GUI_Clean's real window, offscreen: the Run sheet tab and the top bar's master_log button (2026-10-14).
Run by test_run_sheet.py in its OWN process:
building and then deleting GUI_Clean's main window crashes Qt (the committed GUI too, 2026-10-14), so this
script never deletes it -- it prints PASS / FAIL per check and leaves with os._exit, skipping Qt's teardown.

    QT_QPA_PLATFORM=offscreen HPATR_RUN_SHEET_STATE=/tmp/x.json python gui_window_checks.py
"""
import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
STATE = Path(os.environ.setdefault("HPATR_RUN_SHEET_STATE", "/tmp/hpatr_run_sheet_checks_state.json"))
# A frozen copy of the full 57-row sheet planned for 2026-10-15 (057a0f3): Cd tests, spray runs and bead rows.
# Not the live day sheet, which was cut to the bead rows on the day (b55c142) and may change again.
THURSDAY = Path(__file__).resolve().parent / "data" / "run_sheet_57_rows_2026-10-15.csv"

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import gui.GUI_Clean as G  # noqa: E402
from gui import run_sheet as rs  # noqa: E402

G.AtomisationApp._save_camera_settings = lambda self: None          # never write the rig's settings file
win = G.AtomisationApp()
warned = []
win._warn = lambda title, msg: warned.append((title, msg))


def idx(notes):
    """The sheet row whose Notes are exactly `notes` (the sheet's order may change)."""
    return next(i for i, r in enumerate(win._sheet_rows) if r.notes == notes)


def boxes():
    return {"flow": win._flow_entry.text(), "speed": win._speed_entry.text(), "rpm": win._rpm_entry.text(),
            "distance": win._distance_entry.text(), "orifice": win._orifice_combo.currentText(),
            "notes": win._notes_text.toPlainText()}


def fresh():
    """A new progress file, the 0.5 mm insert in the box, the sheet loaded from the start."""
    if STATE.exists():
        STATE.unlink()
    for name in ("_run_sheet_ask", "_save_to_excel_async"):
        win.__dict__.pop(name, None)
    warned.clear()
    win.pressure_data["experiment_active"] = False
    win._notes_lock = None
    win._orifice_combo.setCurrentIndex(win._orifice_combo.findText("0.5mm"))
    win._run_sheet_load(str(THURSDAY))


def finish(i, choice, extra="", folder="/runs/A", save_ok=True):
    """As at the end of a run: Start recorded the row, the run was saved, then the question."""
    win._run_sheet_fill(i)
    win._sheet_row_at_start = i
    win._run_conditions = win._snapshot_run_conditions()
    win._last_saved_run_folder = folder
    win._run_sheet_ask = lambda row, diffs: (choice, extra)
    saves = []
    win._save_to_excel_async = lambda on_done=None: (saves.append(win._notes_text.toPlainText()),
                                                     on_done(save_ok, None if save_ok else "disk full"))
    win._run_sheet_after_save(True, None)
    return saves


def check_loading_fills_in_the_first_run():
    fresh()
    b = boxes()
    assert (b["flow"], b["speed"], b["rpm"], b["orifice"], b["notes"]) == ("2000", "0", "", "1.2mm",
                                                                          "CD TEST 1.2 mm"), b
    assert win._sheet_table.rowCount() == len(win._sheet_rows) and "Next: #Cd 1.2" in win._sheet_next_lbl.text()
    assert any(t == "Change the insert" and "SETUP" in m and "Cd test" in m for t, m in warned), warned
    warned.clear()
    win._run_sheet_load(str(THURSDAY), fill=False)                 # as after a restart: progress kept, no pop-up
    assert win._sheet_progress.current == 0 and not warned
    n = len(win._sheet_rows)
    assert rs.load_state(n, str(THURSDAY)) is not None


def check_yes_fills_in_the_next_run_and_keeps_the_saved_runs_notes():
    fresh()
    a = idx("S2 #01 anchor centre")
    saves = finish(a, "ok", folder="/runs/A")
    assert saves == []                                             # nothing to add: no second save
    assert win._sheet_progress.status[a] == rs.DONE and win._sheet_progress.current == a + 1
    assert boxes()["notes"] == "S2 #02 confirm" and boxes()["flow"] == "11000"
    assert win._notes_lock == ("/runs/A", "S2 #01 anchor centre")
    assert rs.load_state(len(win._sheet_rows), str(THURSDAY)).status[a] == rs.DONE    # remembered on disk
    win._run_folder = "/runs/A"                                    # a later save of run A keeps its own Notes
    win._last_experiment_snapshot = {"timestamps": [], "pressures": [], "flows": [], "camera_windows": []}
    assert win._collect_save_job()["notes"] == "S2 #01 anchor centre"
    win._run_folder = "/runs/NEW"                                  # the next run's save reads the box again
    assert win._collect_save_job()["notes"] == "S2 #02 confirm"


def check_no_marks_the_saved_run_then_refills_the_same_run():
    fresh()
    a = idx("S2 #02 confirm")
    saves = finish(a, "redo", extra="pulsing", folder="/runs/B")
    assert saves == ["S2 #02 confirm [bad run, redone] pulsing"], saves      # the master_log row first
    assert win._sheet_progress.status[a] == rs.REDO and win._sheet_progress.current == a
    assert boxes()["notes"] == "S2 #02 confirm"                    # the redo gets the clean Notes
    assert win._notes_lock == ("/runs/B", "S2 #02 confirm [bad run, redone] pulsing")


def check_a_failed_save_never_moves_the_sheet_on():
    fresh()
    before = list(win._sheet_progress.status)
    a = idx("S2 #03 ladder")
    saves = finish(a, "ok", extra="note", folder="/runs/C", save_ok=False)
    assert saves and win._sheet_progress.status == before and win._sheet_progress.current == a
    assert any("could not be saved" in m for _t, m in warned), warned
    win._sheet_row_at_start = a
    win._run_sheet_after_save(False, "LaCie gone")                 # the end-of-run save itself failed
    assert win._sheet_progress.status == before and any("could NOT be saved" in m for _t, m in warned)


def check_a_change_of_insert_is_flagged():
    fresh()
    win._run_sheet_fill(idx("CD TEST 1.2 mm"))                     # 1.2 mm, then the 0.8 mm Cd test
    warned.clear()
    win._run_sheet_fill(idx("CD TEST 0.8 mm"))
    assert any(t == "Change the insert" and "0.8mm" in m and "Cd test" in m for t, m in warned), warned
    assert boxes()["orifice"] == "0.8mm"


def check_nothing_is_filled_in_while_a_run_is_going():
    fresh()
    win._run_sheet_fill(idx("S2 #05 ladder"))
    win.pressure_data["experiment_active"] = True
    try:
        win._run_sheet_fill(idx("S2 #06 confirm"))
        assert boxes()["notes"] == "S2 #05 ladder"
    finally:
        win.pressure_data["experiment_active"] = False


def check_the_top_bar_has_no_afg_light_and_the_master_log_button_follows_lacie():
    assert not hasattr(win, "_hdr_afg_dot") and not hasattr(win, "_hdr_afg_lbl")
    hl = win._hdr_lacie_lbl.parentWidget().layout()
    order = [hl.itemAt(k).widget() for k in range(hl.count())]
    assert order.index(win._hdr_master_btn) == order.index(win._hdr_lacie_lbl) + 1


def check_the_master_log_button_is_green_only_when_safe():
    import tempfile
    fresh()
    win.pressure_data["experiment_data"]["timestamps"] = []
    win._experiment_saved, win._excel_saves_pending, win._pipeline_busy = True, 0, False
    opened = []
    win._open_folder = lambda path: opened.append(path)
    lacie = tempfile.mkdtemp()
    (Path(lacie) / "Experiments" / "Logs").mkdir(parents=True)
    (Path(lacie) / "Experiments" / "Logs" / "master_log.xlsx").write_bytes(b"x")
    G.find_lacie_drive = lambda: lacie

    def state():
        win._update_master_btn()
        return win._hdr_master_btn.isEnabled(), G.CLR_GREEN in win._hdr_master_btn.styleSheet().split(":disabled")[0]
    assert state() == (True, True)                                 # nothing going on: green, clickable
    win.pressure_data["experiment_active"] = True
    assert state() == (False, False)                               # a run is going: red, not clickable
    win._open_master_log()
    assert opened == []
    win.pressure_data["experiment_active"] = False
    win._experiment_saved = False
    win.pressure_data["experiment_data"]["timestamps"] = [0.1, 0.2]
    assert state() == (False, False)                               # ended, not saved yet
    win._excel_saves_pending = 1
    win._experiment_saved = True
    assert state() == (False, False)                               # a save being written
    win._excel_saves_pending = 0
    win._pipeline_busy = True
    assert state() == (False, False)                               # the AI's re-save still to come
    win._pipeline_busy = False
    assert state() == (True, True)
    win._open_master_log()
    assert opened == [str(Path(lacie) / "Experiments" / "Logs" / "master_log.xlsx")]
    assert win._master_log_locked(opened[0]) is False              # (Windows only; never on the Mac)


def check_calibration_rows_route_the_run_folder_and_shorten_the_capture():
    """A bead row: the run goes under Calibration/Imaging Work, the camera's post-trigger is 1 s and the
    standard-capture check does not ask about it. A spray row: Experiments and the 13 s standard again."""
    import tempfile
    fresh()
    lacie = tempfile.mkdtemp()
    G.find_lacie_drive = lambda: lacie
    win._run_sheet_fill(idx("BEAD mix z0 p2"))
    assert win._cam_post_s.text() == "1"
    assert win._run_base(lacie) == os.path.join(lacie, "Calibration", "Imaging Work")
    assert os.path.join("Calibration", "Imaging Work") in win._hdr_next_save_lbl.text()
    asked = []
    G.QMessageBox.exec = lambda self: asked.append(self.text()) or 0
    assert win._check_standard_capture() is True and not asked      # the 1 s is intended: not asked
    win._cam_fps.setText("500")                                    # ... but anything else still is
    win._check_standard_capture()
    assert asked and "Frame rate" in asked[-1] and "Post-trigger" not in asked[-1]
    win._cam_fps.setText("390")
    win._run_sheet_fill(idx("CD TEST 0.5 mm"))
    assert win._run_base(lacie) == os.path.join(lacie, "Calibration", "Orifice Cd")
    win._run_sheet_fill(idx("S2 #09 0.5 feed"))
    assert win._cam_post_s.text() == "13"                          # back to the standard
    assert win._run_base(lacie) == os.path.join(lacie, "Experiments")
    asked.clear()
    assert win._standard_capture_diffs() == []


failed = 0
for name, fn in [(k, v) for k, v in list(globals().items()) if k.startswith("check_")]:
    try:
        fn()
        print(f"PASS {name}", flush=True)
    except Exception:
        failed += 1
        print(f"FAIL {name}\n{traceback.format_exc()}", flush=True)
print("ALL WINDOW CHECKS PASSED" if not failed else f"{failed} CHECK(S) FAILED", flush=True)
sys.stdout.flush()
os._exit(1 if failed else 0)                    # skip Qt's teardown (see the module docstring)
