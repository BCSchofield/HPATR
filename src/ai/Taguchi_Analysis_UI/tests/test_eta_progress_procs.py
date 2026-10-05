"""ETA model, stdout progress parsing (against a REAL batch log), and the Windows
process flags that cannot be exercised on this Mac."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import eta, procs, progress

REAL_LOG = Path("/Volumes/LaCie/Experiments/2026/10/01/104852_3000sccm_300rpm_4000sps_or1.2_bh1"
                "/shadowgraph/analysis/batch_log.txt")
needs_log = pytest.mark.skipif(not REAL_LOG.is_file(), reason="LaCie not mounted")
HOST = "testhost|Darwin"


# ---- progress parsing --------------------------------------------------------------------

@needs_log
def test_tracker_recovers_the_real_log_exactly():
    t = progress.Tracker()
    evs = [e for ln in REAL_LOG.read_text(errors="replace").splitlines() for e in t.feed(ln)]
    starts = [(e["stage"], e["total"]) for e in evs if e["k"] == "stage_start"]
    ends = [(e["stage"], e["took"]) for e in evs if e["k"] == "stage_end"]
    assert [s for s, _ in starts] == ["extract", "background", "inference", "measurement"]
    assert ends == [("extract", "3m 10s"), ("background", "3s"), ("inference", "6m 51s"),
                    ("measurement", "5m 19s")]
    last = {}
    for e in evs:
        if e["k"] == "progress":
            last[e["stage"]] = (e["done"], e["total"])
    assert last == {"extract": (497, 497), "inference": (497, 497), "measurement": (497, 497)}
    assert t.frames == 497 and t.device == "cuda"
    # per-frame spam is folded into progress, not forwarded to the console
    assert sum(e["k"] == "log" for e in evs) < 150


def test_tracker_on_the_real_line_formats():
    t = progress.Tracker(every=1)
    lines = ["", "=== 1/4  extracting frames ===",
             "  extracting 3 frames at stride 10 (12.50 ms apart)",
             "    1/3 (33%)   13.1 frames/s   ETA 28s", "    3/3 (100%)   13.1 frames/s   ETA 0s",
             "    [extract frames took 3m 10s]", "=== 3/4  inference on 3 frames ===",
             "device: cpu  (auto-detected)",
             "frame_0000_n-1         2560x1600   24 tiles     0.80s  det   97 (>=0.30:  73)  truncated   2   {}",
             "frame_0001_n9          2560x1600   24 tiles     0.80s  det   97 (>=0.30:  73)  truncated   2   {}"]
    evs = [e for ln in lines for e in t.feed(ln)]
    assert [e for e in evs if e["k"] == "progress"][-1] == \
        {"k": "progress", "stage": "inference", "done": 2, "total": 3}
    assert t.device == "cpu" and t.frames == 3
    t.begin("classical", 3)
    assert t.feed("    25/497   12.3s  (0.49 s/frame)")[0]["done"] == 25


def test_tracker_never_raises_on_garbage():
    t = progress.Tracker()
    for junk in ("\x00\x01", "=== 9/4 ???", "frame_xyz", "[ took ]", "12/ (%)", "\n\n"):
        t.feed(junk)


def test_reuse_banner_sets_frames():
    t = progress.Tracker()
    t.feed("=== reusing the existing stride-10 analysis (497 frames): extraction, background "
           "and inference skipped ===")
    assert t.reused and t.frames == 497


# ---- ETA ---------------------------------------------------------------------------------------

def run(status, frames=497, seconds=None, stage=None, started=None, done=None, total=None,
        device="cuda"):
    r = {"status": status, "frames": frames, "seconds": seconds or {}, "device": device,
         "stage": stage, "stage_started": started}
    if done is not None:
        r["progress"] = {"done": done, "total": total}
    return r


def state(*runs):
    return {"runs": list(runs)}


def test_priors_are_used_and_labelled_before_anything_has_run():
    est = eta.estimate(state(run("pending", frames=None), run("pending", frames=None)), "extremes",
                       host=HOST, calib=None, now=0)
    typical = sum(eta.priors_for("Darwin")[eta._prior_key(s, "extremes")][1] for s in eta.STAGE_ORDER)
    assert est.batch_remaining_s == pytest.approx(2 * typical)
    assert not est.measured and "not yet measured on this machine" in est.note
    assert "MacBook Air" in est.note                    # HOST is a Darwin host


def test_priors_follow_the_operating_system():
    pending = state(run("pending", frames=None))
    mac = eta.estimate(pending, "extremes", host="m|Darwin", now=0)
    win = eta.estimate(pending, "extremes", host="w|Windows", now=0)
    assert mac.batch_remaining_s > 2 * win.batch_remaining_s      # CPU vs CUDA inference
    assert "GPU PC" in win.note and "MacBook Air" in mac.note
    other = eta.estimate(pending, "extremes", host="l|Linux", now=0)
    assert other.batch_remaining_s == win.batch_remaining_s       # unknown OS: GPU figures


def test_background_is_a_fixed_cost_not_per_frame():
    secs = {"extract": 40, "background": 2.0, "inference": 400, "measurement": 4, "classical": 2}
    est = eta.estimate(state(run("done", frames=40, seconds=secs), run("pending", frames=497)),
                       "extremes", host=HOST, now=0)
    per_frame = (40 + 400 + 4 + 2) / 40
    # the 497-frame run: per-frame stages scale, background stays 2 s (not 2 x 497/40 = 25 s)
    assert est.batch_remaining_s == pytest.approx(per_frame * 497 + 2.0)


def test_finished_runs_replace_the_priors_with_measured_rates():
    secs = {"extract": 100, "background": 2, "inference": 1000, "measurement": 50, "classical": 30}
    est = eta.estimate(state(run("done", seconds=secs), run("pending")), "extremes",
                       host=HOST, calib=None, now=0)
    assert est.batch_remaining_s == pytest.approx(sum(secs.values()))   # same frame count
    assert est.measured and "1 finished run" in est.note


def test_rates_scale_with_frame_count():
    secs = {s: 100 for s in eta.STAGE_ORDER}
    est = eta.estimate(state(run("done", frames=100, seconds=secs), run("pending", frames=None)),
                       "extremes", host=HOST, now=0)
    # the pending run's frame count is unknown, so the typical (100) is used
    assert est.batch_remaining_s == pytest.approx(500)


def test_live_progress_drives_the_current_stage():
    secs = {s: 100 for s in eta.STAGE_ORDER}
    cur = run("running", stage="inference", started=1000.0, done=250, total=497)
    est = eta.estimate(state(run("done", seconds=secs), cur), "extremes", host=HOST, now=1200.0)
    f = 250 / 497
    expected_now = 200 * (1 - f) / f + 100 + 100                 # inference rest + measure + classical
    assert est.run_remaining_s == pytest.approx(expected_now, rel=1e-6)


def test_the_range_is_the_spread_of_measured_rates():
    a = {s: 100 for s in eta.STAGE_ORDER}
    b = {s: 200 for s in eta.STAGE_ORDER}
    est = eta.estimate(state(run("done", seconds=a), run("done", seconds=b), run("pending")),
                       "extremes", host=HOST, now=0)
    assert est.low_s == pytest.approx(500) and est.high_s == pytest.approx(1000)
    assert est.batch_remaining_s == pytest.approx(750)            # the median


def test_inference_rates_are_kept_apart_by_device():
    secs = {s: 100 for s in eta.STAGE_ORDER}
    est = eta.estimate(state(run("done", seconds=secs, device="cuda"),
                             run("pending", device="cpu")), "extremes", host=HOST, now=0)
    # latest device is cpu, which has no measurement: inference falls back to the prior
    assert not est.measured


def test_images_mode_keeps_measurement_rates_apart():
    secs = {s: 100 for s in eta.STAGE_ORDER}
    ext = eta.estimate(state(run("done", seconds=secs), run("pending")), "extremes", host=HOST, now=0)
    assert ext.measured
    allm = eta.estimate(state(run("done", seconds=secs), run("pending")), "all", host=HOST, now=0)
    assert allm.measured                       # the done run is keyed under the CURRENT mode here
    c = eta.Calibration(path=Path("/nonexistent/x.json"))
    c.add(eta.obs_key(HOST, "measurement", "cuda", "all"), 1.0)
    assert c.rates(eta.obs_key(HOST, "measurement", "cuda", "extremes")) == []


def test_calibration_carries_rates_to_the_next_batch_on_this_machine():
    with tempfile.TemporaryDirectory() as d:
        c = eta.Calibration(path=Path(d) / "c.json")
        for s in eta.STAGE_ORDER:
            c.add(eta.obs_key(HOST, s, "cuda", "extremes"), 0.5)
        c.save()
        c2 = eta.Calibration.load(Path(d) / "c.json")
        est = eta.estimate(state(run("pending", device="cuda")), "extremes", host=HOST, calib=c2, now=0)
        # four per-frame stages x 497 frames, plus background as a fixed 0.5 s
        assert est.measured and est.batch_remaining_s == pytest.approx(0.5 * 4 * 497 + 0.5)
        assert "earlier batches" in est.note
        other = eta.estimate(state(run("pending", device="cuda")), "extremes",
                             host="otherbox|Windows", calib=c2, now=0)
        assert not other.measured                   # another machine's history is not used


def test_calibration_keeps_only_recent_observations():
    c = eta.Calibration(path=Path("/nonexistent/x.json"))
    for i in range(100):
        c.add("k", float(i + 1))
    assert len(c.rates("k")) == eta.Calibration.KEEP and c.rates("k")[-1] == 100.0


def test_describe_and_fmt():
    assert eta.fmt(None) == "?" and eta.fmt(45) == "45s" and eta.fmt(125) == "2m 05s"
    assert eta.fmt(7320) == "2h 02m"
    e = eta.Estimate(None, 3600, 3000, 4000, True, 5, "from 5 finished runs on this machine")
    text = eta.describe(e, now=0)
    assert text.startswith("batch ETA 1h 00m (50m 00s–1h 06m), done ~") and "5 finished" in text
    assert eta.describe(eta.Estimate(0, 0, 0, 0, True, 3)) == "nothing left to run"


def test_nothing_left():
    est = eta.estimate(state(run("done", seconds={"extract": 1}), run("failed")), "extremes", now=0)
    assert est.batch_remaining_s == 0


# ---- Windows process flags (asserted, since they cannot run here) ---------------------------------

class _FakeSI:
    def __init__(self):
        self.dwFlags, self.wShowWindow = 0, 1


def _capture_popen(monkeypatch, fail_breakaway=False):
    calls = []

    class P:
        pid = 4242

    def fake_popen(cmd, **kw):
        calls.append((cmd, kw))
        if fail_breakaway and kw.get("creationflags", 0) & procs.CREATE_BREAKAWAY_FROM_JOB:
            e = OSError("Access is denied")
            e.winerror = procs.ERROR_ACCESS_DENIED
            raise e
        return P()

    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    monkeypatch.setattr(procs.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(procs.subprocess, "STARTUPINFO", _FakeSI, raising=False)
    monkeypatch.setattr(procs.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    return calls


def test_windows_spawn_is_detached_hidden_and_breaks_away(monkeypatch):
    calls = _capture_popen(monkeypatch)
    with tempfile.TemporaryDirectory() as d:
        p = procs.spawn_detached(Path(d), ["--impl", "stub"])
    (cmd, kw), = calls
    flags = kw["creationflags"]
    assert flags & procs.CREATE_NO_WINDOW and flags & procs.CREATE_NEW_PROCESS_GROUP
    # NOT DETACHED_PROCESS: a worker with no console makes every stage it starts open its own
    # visible console window (and CREATE_NO_WINDOW is ignored when combined with it)
    assert not flags & 0x00000008
    assert flags & procs.CREATE_BREAKAWAY_FROM_JOB
    assert not flags & 0x00000010, "must NOT use CREATE_NEW_CONSOLE (the window that killed the batch)"
    assert kw["startupinfo"].wShowWindow == 0 and kw["startupinfo"].dwFlags & 1
    assert "start_new_session" not in kw
    assert cmd[1:4] == ["-u", "-m", procs.WORKER_MODULE] and p.breakaway is True


def test_windows_spawn_falls_back_when_breakaway_is_denied(monkeypatch):
    calls = _capture_popen(monkeypatch, fail_breakaway=True)
    with tempfile.TemporaryDirectory() as d:
        p = procs.spawn_detached(Path(d))
    assert len(calls) == 2
    assert not calls[1][1]["creationflags"] & procs.CREATE_BREAKAWAY_FROM_JOB
    assert calls[1][1]["creationflags"] & procs.CREATE_NO_WINDOW and not calls[1][1]["creationflags"] & 0x8
    assert p.breakaway is False


def test_posix_spawn_uses_a_new_session(monkeypatch):
    calls = []
    monkeypatch.setattr(procs, "IS_WINDOWS", False)
    monkeypatch.setattr(procs.subprocess, "Popen",
                        lambda cmd, **kw: calls.append(kw) or type("P", (), {"pid": 1})())
    with tempfile.TemporaryDirectory() as d:
        procs.spawn_detached(Path(d))
    assert calls[0]["start_new_session"] is True and "creationflags" not in calls[0]
    assert calls[0]["stdin"] is subprocess.DEVNULL


def test_windows_kill_uses_a_tree_kill(monkeypatch):
    calls = []
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    monkeypatch.setattr(procs.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    procs.kill_tree(4242)
    assert calls == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_windows_job_object_is_only_attempted_on_windows():
    assert procs.windows_job() is None


def test_reap_orphans_never_touches_processes_that_are_not_ours(monkeypatch):
    import os
    import sys
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                         start_new_session=True)
    try:
        dead_worker = {"pid": 2 ** 22 - 7, "pgid": os.getpgid(p.pid), "started_epoch": 0}
        assert procs.reap_orphans(dead_worker, log=lambda m: None) == 0
        assert procs.is_alive(p.pid), "an unrelated process in the group was killed"
    finally:
        p.kill()
        p.wait()


def test_is_alive_sees_through_a_zombie():
    import sys
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    import time
    time.sleep(0.5)                      # exited, not yet reaped: a zombie
    assert procs.is_alive(p.pid) is False


# ---- the process-group safety rule (found by a mutation test that killed the test run) ----

def _sleeper():
    import sys
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                            start_new_session=True)


def test_kill_tree_never_signals_a_group_the_worker_does_not_lead():
    worker, bystander = _sleeper(), _sleeper()
    try:
        # pretend the recorded pgid is someone else's group (e.g. the user's shell)
        procs.kill_tree(worker.pid, pgid=bystander.pid, grace=2)
        worker.wait(timeout=5)
        assert procs.is_alive(bystander.pid), "kill_tree took down a process it does not own"
    finally:
        for p in (worker, bystander):
            if p.poll() is None:
                p.kill()
            p.wait()


def test_kill_tree_stops_a_non_leader_worker_and_its_children():
    import sys
    import time
    code = ("import subprocess, sys, time; "
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "print(c.pid, flush=True); time.sleep(30)")
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    child = int(parent.stdout.readline())
    try:
        procs.kill_tree(parent.pid, pgid=None, grace=2)       # parent shares OUR group
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while procs.is_alive(child) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not procs.is_alive(child), "the worker's child survived"
        assert procs.is_alive(__import__("os").getpid())        # and we are still here
    finally:
        if parent.poll() is None:
            parent.kill()


def test_a_worker_run_by_hand_records_no_group(tmp_path):
    import sys
    from src.ai.Taguchi_Analysis_UI import worker
    r = subprocess.run([sys.executable, "-c",
                        "from src.ai.Taguchi_Analysis_UI.worker import _own_group; print(_own_group())"],
                       cwd=str(procs.paths.REPO_ROOT), capture_output=True, text=True)
    assert r.stdout.strip() == "None"                           # shares pytest's group
    r2 = subprocess.run([sys.executable, "-c",
                         "from src.ai.Taguchi_Analysis_UI.worker import _own_group; import os; "
                         "print(_own_group() == os.getpid())"],
                        cwd=str(procs.paths.REPO_ROOT), capture_output=True, text=True,
                        start_new_session=True)
    assert r2.stdout.strip() == "True"                          # detached: leads its own


def test_this_machines_only_inference_device_is_assumed_before_any_run_reports_one():
    c = eta.Calibration(path=Path("/nonexistent/x.json"))
    for s in ("extract", "inference", "measurement", "classical"):
        c.add(eta.obs_key(HOST, s, "cpu", "extremes"), 1.0)
    c.add(eta.obs_key(HOST, "background", None, None), 2.0)
    fresh = state(run("pending", frames=100, device=None))
    est = eta.estimate(fresh, "extremes", host=HOST, calib=c, now=0)
    assert est.measured and est.batch_remaining_s == pytest.approx(4 * 100 + 2)
    c.add(eta.obs_key(HOST, "inference", "mps", "extremes"), 0.2)   # two devices: ambiguous
    assert not eta.estimate(fresh, "extremes", host=HOST, calib=c, now=0).measured



# ---- 64-bit Windows ctypes semantics, simulated ------------------------------------------------------

class _FakeFn:
    """A kernel32 function with LLP64 argument rules: undeclared ints must fit 32 bits."""
    def __init__(self, name, log):
        self.name, self.log, self.argtypes, self.restype = name, log, None, "c_int"

    def __call__(self, *args):
        import ctypes
        if self.argtypes is None:
            for a in args:
                if isinstance(a, int) and not (-2 ** 31 <= a < 2 ** 32):
                    raise ctypes.ArgumentError(f"{self.name}: int too long to convert")
        else:
            assert len(args) == len(self.argtypes), self.name
        self.log.append(self.name)
        handle_typed = self.restype is not None and self.restype != "c_int" and \
            getattr(self.restype, "__name__", "") in ("c_void_p", "HANDLE")
        if self.name == "GetCurrentProcess":
            return 2 ** 64 - 1 if handle_typed else -1          # the pseudo-handle (HANDLE)-1
        if self.name == "CreateJobObjectW":
            return 0x7FFE00001F4 if handle_typed else 0x1F4
        return 1


class _FakeKernel32:
    def __init__(self):
        self.log, self.fns = [], {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self.fns.setdefault(name, _FakeFn(name, self.log))


def test_the_fake_kernel32_reproduces_the_crash_the_old_code_had():
    """Sanity check of the simulation: the pre-fix pattern (restype set, argtypes not) fails."""
    import ctypes
    from ctypes import wintypes
    k = _FakeKernel32()
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.CreateJobObjectW.restype = wintypes.HANDLE
    h = k.CreateJobObjectW(None, None)
    with pytest.raises(ctypes.ArgumentError):
        k.AssignProcessToJobObject(h, k.GetCurrentProcess())


def test_windows_job_declares_its_types_so_64_bit_handles_pass(monkeypatch):
    import ctypes
    fake = _FakeKernel32()
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: fake, raising=False)
    h = procs.windows_job()
    assert h == 0x7FFE00001F4
    assert fake.log == ["CreateJobObjectW", "SetInformationJobObject", "GetCurrentProcess",
                        "AssignProcessToJobObject"]


def test_keep_awake_and_liveness_use_declared_types_on_windows(monkeypatch):
    import ctypes
    fake = _FakeKernel32()
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    monkeypatch.setattr(procs, "_psutil", lambda: None)
    monkeypatch.setattr(procs, "_reap", lambda pid: False)
    monkeypatch.setattr(procs.shutil, "which", lambda name: None)          # not the macOS branch
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: fake, raising=False)
    assert procs.keep_awake().startswith("SetThreadExecutionState")
    procs.is_alive(4242)
    assert {"OpenProcess", "GetExitCodeProcess", "CloseHandle"} <= set(fake.log)
    assert all(fn.argtypes is not None for fn in fake.fns.values())


def test_a_job_object_failure_of_any_kind_does_not_stop_the_worker(monkeypatch, tmp_path):
    """The worker treats the job object as a nicety: any exception is a warning."""
    from src.ai.Taguchi_Analysis_UI import worker
    src = Path(worker.__file__).read_text(encoding="utf-8")
    block = src[src.index("self._job_handle = procs.windows_job()") - 40:][:200]
    assert "except Exception" in block


def test_pythonw_is_swapped_for_the_console_python_beside_it(tmp_path):
    (tmp_path / "python.exe").write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    assert procs.console_python(str(tmp_path / "pythonw.exe")) == str(tmp_path / "python.exe")
    assert procs.console_python(str(tmp_path / "python.exe")) == str(tmp_path / "python.exe")
    assert procs.console_python("/usr/bin/python3") == "/usr/bin/python3"
