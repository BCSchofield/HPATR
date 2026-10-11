"""The overnight batch of 2026-10-06 died twice on a USB drop: one failed log flush (OSError 22) failed
the run and then the worker, and the crash was then shown as a contract violation with no Resume.
These reproduce both, in-process with the stub pipeline: a write that fails never fails a run; a run
that fails while the drive is away waits for it and is redone once; a drive that never returns, or a
worker crash, leaves a job that Resume finishes."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import jobstate, procs
from src.ai.Taguchi_Analysis_UI import worker as wk
from src.ai.Taguchi_Analysis_UI.stub_pipeline import Stub
from src.ai.Taguchi_Analysis_UI.tests.workerkit import new_job, sandbox


@pytest.fixture
def tmp(monkeypatch):
    monkeypatch.setattr(procs, "keep_awake", lambda: "test")
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def events(jd):
    return [json.loads(l) for l in (jd / "events.jsonl").read_text().splitlines() if l.strip()]


def worker(jd, pipeline=None, wait_s=10.0):
    w = wk.Worker(jd, pipeline or Stub(frames=6, stage_s=0.01), heartbeat_s=0.3)
    w.drive_wait_s, w.drive_poll_s = wait_s, 0.05
    return w


class DropsDrive(Stub):
    """Pulls the named run's folder away (as a USB drop does) during its first attempt and fails with
    the error Windows gave on 10-06; puts it back after `back_after` seconds (None: never)."""

    def __init__(self, name, back_after=None, **kw):
        super().__init__(frames=6, stage_s=0.01, **kw)
        self.name, self.back_after, self.dropped = name, back_after, 0

    def process_capture(self, cine, run_dir, **kw):
        run_dir = Path(run_dir)
        if run_dir.name == self.name and not self.dropped:
            self.dropped += 1
            away = run_dir.with_name(run_dir.name + ".away")
            os.rename(run_dir, away)
            if self.back_after is not None:
                threading.Timer(self.back_after, os.rename, (away, run_dir)).start()
            raise OSError(22, "Invalid argument")
        return super().process_capture(cine, run_dir, **kw)


def test_a_log_write_that_fails_does_not_fail_the_run_or_the_worker(tmp, monkeypatch):
    """worker.py:229 on 10-06: logf.flush() raised OSError 22 and the run, then the worker, died."""
    out, runs = sandbox(tmp, monkeypatch, 2)
    jd = new_job(out, runs)
    real_open = open
    failures = [0]

    class Flaky:
        def __init__(self, f):
            self.f = f

        def write(self, text):
            return self.f.write(text)

        def flush(self):
            if failures[0] < 3:
                failures[0] += 1
                raise OSError(22, "Invalid argument")
            self.f.flush()

        def close(self):
            self.f.close()

    def flaky_open(path, *a, **kw):
        f = real_open(path, *a, **kw)
        return Flaky(f) if Path(path).parent.name == "logs" else f

    monkeypatch.setattr(wk, "open", flaky_open, raising=False)
    monkeypatch.setattr(wk, "LOG_REOPEN_S", 0.0)
    assert worker(jd).run() == 0
    st = jobstate.load_state(jd)
    assert [r["status"] for r in st["runs"]] == ["done", "done"] and st["status"] == "finished"
    assert failures[0] == 3
    assert any(e["k"] == "warn" and "could not write the run log" in e["detail"] for e in events(jd))
    assert (jd / "logs" / f"00_{runs[0].name}.log").stat().st_size > 0      # writing carried on


def test_a_drive_that_drops_and_comes_back_gets_the_run_redone_once(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    assert worker(jd, DropsDrive(runs[1].name, back_after=0.4)).run() == 0
    st = jobstate.load_state(jd)
    assert [r["status"] for r in st["runs"]] == ["done"] * 3 and st["status"] == "finished"
    assert st["runs"][1]["attempts"] == 2 and st["runs"][1]["drive_retried"] is True
    assert st["runs"][0]["attempts"] == st["runs"][2]["attempts"] == 1
    details = " ".join(e.get("detail", "") + e.get("line", "") for e in events(jd))
    assert "waiting up to" in details and "the drive is back" in details and "redoing it once" in details


def test_a_run_that_fails_again_after_the_drive_returns_is_failed_not_looped(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 2)
    jd = new_job(out, runs)

    class AlwaysOSError(Stub):
        def process_capture(self, cine, run_dir, **kw):
            if Path(run_dir).name == runs[0].name:
                raise OSError(5, "Input/output error")
            return super().process_capture(cine, run_dir, **kw)

    assert worker(jd, AlwaysOSError(frames=6, stage_s=0.01)).run() == 1
    st = jobstate.load_state(jd)
    assert [r["status"] for r in st["runs"]] == ["failed", "done"]
    assert st["runs"][0]["attempts"] == 2                      # one redo, then recorded and moved on


def test_a_drive_that_never_comes_back_pauses_the_batch_and_resume_finishes_it(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    assert worker(jd, DropsDrive(runs[1].name, back_after=None), wait_s=0.3).run() == 6
    st = jobstate.load_state(jd)
    assert st["status"] == "drive_lost"
    assert [r["status"] for r in st["runs"]] == ["done", "pending", "pending"]
    live = jobstate.liveness(jd)
    assert live.state == "drive_lost" and live.resumable
    assert any(e["k"] == "error" and "drive lost" in e["detail"] for e in events(jd))
    os.rename(runs[1].with_name(runs[1].name + ".away"), runs[1])           # reconnected
    jobstate.plan_resume(st)
    assert worker(jd).run() == 0
    assert [r["status"] for r in jobstate.load_state(jd)["runs"]] == ["done"] * 3


def test_a_worker_crash_is_resumable_and_not_called_a_contract_violation(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 2)
    jd = new_job(out, runs)
    real = jobstate.write_timings
    calls = [0]

    def buggy(jd_, state):
        calls[0] += 1
        if calls[0] == 1:
            raise ValueError("a bug in the worker")
        return real(jd_, state)

    monkeypatch.setattr(jobstate, "write_timings", buggy)
    assert worker(jd).run() == 7
    st = jobstate.load_state(jd)
    assert st["status"] == "crashed"
    live = jobstate.liveness(jd)
    assert live.state == "crashed" and live.resumable
    assert worker(jd).run() == 0                               # Resume finishes it


def test_an_old_halted_crash_reads_as_crashed_but_a_contract_halt_stays_halted(tmp, monkeypatch):
    """Workers before this fix wrote "halted" for a crash too (the 10-06 batch)."""
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    st = jobstate.initial_state(jobstate.load_job(jd))
    st["status"] = "halted"
    st["runs"][0]["status"] = "done"
    jobstate.save_state(jd, st)
    live = jobstate.liveness(jd)
    assert live.state == "crashed" and live.resumable
    st["runs"][1]["status"] = "contract_violation"
    jobstate.save_state(jd, st)
    live = jobstate.liveness(jd)
    assert live.state == "halted" and not live.resumable


def test_events_that_cannot_be_written_are_kept_and_written_later(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 1)
    jd = new_job(out, runs)
    w = worker(jd)
    real = w.events.append
    fail = [True]

    def append(kind, **fields):
        if fail[0]:
            raise OSError(22, "Invalid argument")
        return real(kind, **fields)

    w.events.append = append
    w.emit("log", line="first")
    w.emit("log", line="second")
    fail[0] = False
    w.emit("log", line="third")
    lines = [e["line"] for e in events(jd)]
    assert lines == ["first", "second", "third"]
    assert all("written_late_from" in e for e in events(jd)[:2])
