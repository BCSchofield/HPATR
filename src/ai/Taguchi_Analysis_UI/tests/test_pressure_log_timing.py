"""The pressure / gas log's timing (2026-10-14). On the CCD day GUI_Clean's GUI thread stalled for 1-4 s in
30 of 33 runs (find_lacie_drive() and the serial log both touch the LaCie, which was busy finishing the
previous run's cine), and because each Alicat reading was stamped when the GUI thread handled it, the
readings queued meanwhile were logged in one burst: a gap, then a jump. Fixed in the GUI (stamp at read
time; the serial log and the drive probe off the reader / GUI threads) and repaired in the analysis for
the logs already written (operating.respace_queued)."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import openpyxl
import pytest

from src.ai.Taguchi_Analysis_UI import operating as op
from src.ai.Taguchi_Analysis_UI import paths


# ---- the analysis: logs already written ---------------------------------------------------------------------

def _stalled_log(tmp: Path, stall=(40.0, 43.0), step=0.2):
    """A run's Pressure sheet as the old GUI wrote it: a reading every `step` s, true flow rising through the
    stall (so dropping the queued readings biases the median), and every reading taken during the stall
    logged at the stall's end, 1 ms apart."""
    t_true = np.arange(step, 80.0, step)
    q = np.where(t_true < 41.0, 5000.0, 5600.0)
    p = np.full_like(t_true, 9.2)
    logged = t_true.copy()
    queued = (t_true > stall[0]) & (t_true <= stall[1])
    logged[queued] = stall[1] + 0.001 * np.arange(queued.sum())
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pressure"
    ws.append(["timestamps", "pressures", "flows_sccm", "cam_start_1", "cam_end_1"])
    for i, (ti, pi, qi) in enumerate(zip(logged, p, q)):
        ws.append([float(ti), float(pi), float(qi), 35.0 if i == 0 else None, 48.0 if i == 0 else None])
    x = tmp / "run_summary.xlsx"
    wb.save(x)
    return x, t_true, q, int(queued.sum())


def test_queued_readings_are_spread_back_across_the_stall_not_dropped(tmp_path):
    x, t_true, q, n_queued = _stalled_log(tmp_path)
    assert n_queued == 15
    tr = op.read_trace(x)
    assert tr.t.size == t_true.size                                        # none dropped
    stalled = (tr.t > 40.0) & (tr.t <= 43.02)                             # the burst was logged at 43.000-43.014
    assert stalled.sum() == n_queued and np.allclose(np.diff(tr.t[stalled]), 0.2, atol=0.01)
    true = op.window_stats(op.Trace(t_true, np.full_like(t_true, 9.2), q, (35.0, 48.0)))
    assert op.window_stats(tr)["delivered_sccm"] == true["delivered_sccm"]


def test_a_log_without_stalls_is_left_alone():
    t = np.arange(0.22, 30, 0.22)
    assert np.array_equal(op.respace_queued(t), t)
    t2 = t.copy()
    t2[50:] += 2.0                                                          # a real gap, nothing queued
    assert np.array_equal(op.respace_queued(t2), t2)


# ---- the GUI: new logs --------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def G():
    pytest.importorskip("PySide6")
    paths.ensure_src_on_path()
    import gui.GUI_Clean as G
    return G


class _Label:
    def setText(self, *_a): pass
    def setStyleSheet(self, *_a): pass


def _fake_app(G, start: float):
    return SimpleNamespace(
        _EMA_ALPHA=0.3, _pressure_ema=None, _flow_ema=None, _smooth_enabled=False,
        _hdr_pressure_lbl=_Label(), _hdr_pressure_dot=_Label(),
        pressure_data={"live_buffer": {"timestamps": [], "pressures": [], "flows": []},
                       "live_buffer_start_time": start, "experiment_active": True,
                       "experiment_start_time": start,
                       "experiment_data": {"timestamps": [], "pressures": [], "flows": []}})


def test_a_reading_is_logged_at_the_time_it_was_read_not_when_the_gui_got_to_it(G):
    start = time.time()
    app = _fake_app(G, start)
    stamps = [start - 0.1] + [start + 0.2 * k for k in range(1, 6)]         # one read before Start
    time.sleep(0.05)                                                        # the GUI handles them late, together
    for k, w in enumerate(stamps):
        G.AtomisationApp._record_alicat_sample(app, 9.0 + k / 100, 5000.0 + k, w)
    ed = app.pressure_data["experiment_data"]
    assert ed["timestamps"] == pytest.approx([0.2 * k for k in range(1, 6)])   # read times; the early one left out
    assert ed["flows"] == [5001.0 + k for k in range(5)]


def test_the_alicat_reader_stamps_the_reading_itself(G, monkeypatch):
    got = []
    app = SimpleNamespace(_on_alicat_reading=lambda *a: got.append(a))
    monkeypatch.setattr(G, "QTimer", SimpleNamespace(singleShot=lambda _ms, _ctx, fn: fn()))
    before = time.time()
    G.AtomisationApp._parse_alicat_line(app, f"{G.AlicatMFC.DEVICE_ID} +09.150 +025.0 +00000 +05400 +07000 "
                                             "+0000000 N2")
    (p, _temp, m, s, stamp), = got
    assert (p, m, s) == (9.15, 5400.0, 7000.0) and before <= stamp <= time.time()


def test_serial_log_lines_never_wait_for_a_slow_drive_and_all_arrive_in_order(G, tmp_path, monkeypatch):
    log = tmp_path / "serial.txt"
    real_write = G._write_serial_lines

    def slow(batch):                                                        # the LaCie busy for 0.5 s
        time.sleep(0.5)
        real_write(batch)
    monkeypatch.setattr(G, "_write_serial_lines", slow)
    t0 = time.monotonic()
    for k in range(20):
        G.log_serial(f"Received: DEBUG: Movement progress: {k}%", log_file=str(log))
    assert time.monotonic() - t0 < 0.2                                      # the reader is never held up
    assert G.flush_serial_log(5.0)
    lines = log.read_text().splitlines()
    assert [ln.split("progress: ")[1] for ln in lines] == [f"{k}%" for k in range(20)]


def test_the_lacie_probe_runs_off_the_gui_thread_one_at_a_time(G, monkeypatch):
    shown, started = [], []
    release = threading.Event()

    def slow_find():
        started.append(threading.current_thread().name)
        release.wait(5)
        return "D:\\"
    monkeypatch.setattr(G, "find_lacie_drive", slow_find)

    class _Signal:                                     # the answer comes back as a Qt signal (queued by Qt)
        def __init__(self):
            self.slots = []

        def connect(self, fn):
            self.slots.append(fn)

        def emit(self, v):
            for fn in self.slots:
                fn(v)
    app = SimpleNamespace(_lacie_probe_busy=False, _lacie_probed=_Signal())
    app._show_lacie = lambda ok: (shown.append(ok), setattr(app, "_lacie_probe_busy", False))
    t0 = time.monotonic()
    G.AtomisationApp._poll_lacie(app)
    G.AtomisationApp._poll_lacie(app)                                        # still probing: not a second thread
    assert time.monotonic() - t0 < 0.2 and app._lacie_probe_busy
    release.set()
    for _ in range(100):
        if shown:
            break
        time.sleep(0.01)
    assert shown == [True] and started == ["lacie-probe"] and not app._lacie_probe_busy
    assert len(app._lacie_probed.slots) == 1                                  # connected once, not per poll
