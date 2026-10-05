"""Unit tests for the job folder: atomic writes, event tailing, liveness, resume
planning, locking and the timings schema."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import jobstate, procs
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI.tests import fakes


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def jd(tmp):
    runs = [fakes.make_run(tmp, n) for n, _, _ in fakes.REAL_10_05[:3]]
    return jobstate.create_job(tmp / "out", runs, spec.RunSettings(score_thresh=0.45),
                               spec.default_options())


# ---- creation ---------------------------------------------------------------------------

def test_create_job_writes_a_complete_job(jd):
    job, state = jobstate.load_job(jd), jobstate.load_state(jd)
    assert jd.name == "_job" and (jd / "logs").is_dir()
    assert len(job["runs"]) == 3 and job["settings"]["score_thresh"] == 0.45
    assert job["options"] == spec.default_options()
    assert set(job["script_hashes"]) == set(spec.CHAIN_SCRIPTS)
    assert job["python"] and job["repo_commit"]
    assert state["status"] == "pending" and [r["status"] for r in state["runs"]] == ["pending"] * 3
    assert state["images"] == "extremes"


def test_settings_round_trip_through_the_job_file(jd):
    s = jobstate.settings_from(jobstate.load_job(jd)["settings"])
    assert s == spec.RunSettings(score_thresh=0.45)


def test_a_new_job_archives_a_finished_one(jd, tmp):
    st = jobstate.load_state(jd)
    st["status"] = "finished"
    jobstate.save_state(jd, st)
    old_id = jobstate.load_job(jd)["job_id"]
    new = jobstate.create_job(tmp / "out", [], spec.RunSettings(), spec.default_options())
    assert jobstate.load_job(new)["job_id"] != old_id
    assert (tmp / "out" / "_job_archive" / old_id / "job.json").exists()


def test_a_new_job_refuses_while_a_worker_is_live(jd, tmp):
    st = jobstate.load_state(jd)
    st["status"] = "running"
    st["worker"] = {"pid": os.getpid(), "token": "t", "create_time": procs.create_time(os.getpid())}
    jobstate.save_state(jd, st)
    jobstate.write_heartbeat(jd, os.getpid(), "t", 1)
    with pytest.raises(jobstate.JobBusy):
        jobstate.create_job(tmp / "out", [], spec.RunSettings(), spec.default_options())


# ---- atomic writes + tolerant reads ------------------------------------------------------------

def test_atomic_write_leaves_no_temp_files_and_replaces_whole(tmp):
    p = tmp / "s.json"
    for i in range(20):
        jobstate.atomic_write_json(p, {"i": i, "pad": "x" * 1000})
    assert json.loads(p.read_text())["i"] == 19
    assert [x.name for x in tmp.iterdir()] == ["s.json"]


def test_read_json_tolerates_a_torn_or_missing_file(tmp):
    assert jobstate.read_json(tmp / "missing.json", "d") == "d"
    (tmp / "torn.json").write_text('{"a": 1, "b"')
    assert jobstate.read_json(tmp / "torn.json", "d", retries=2) == "d"


# ---- events --------------------------------------------------------------------------------------

def test_event_tail_reads_only_new_events(jd):
    log, tail = jobstate.EventLog(jd), jobstate.EventTail(jd)
    log.append("a", n=1)
    log.append("b", n=2)
    assert [e["k"] for e in tail.poll()] == ["a", "b"]
    assert tail.poll() == []
    log.append("c")
    assert [e["k"] for e in tail.poll()] == ["c"]


def test_event_tail_leaves_a_half_written_line_for_later(jd):
    tail = jobstate.EventTail(jd)
    with open(jd / "events.jsonl", "a") as f:
        f.write('{"k": "a"}\n{"k": "b", "par')
    assert [e["k"] for e in tail.poll()] == ["a"]
    with open(jd / "events.jsonl", "a") as f:
        f.write('tial": 1}\n')
    assert tail.poll() == [{"k": "b", "partial": 1}]


def test_event_tail_skips_a_line_torn_by_a_kill(jd):
    with open(jd / "events.jsonl", "a") as f:
        f.write('{"k": "a"}\n{"k": "torn\n{"k": "c"}\n')
    assert [e["k"] for e in jobstate.EventTail(jd).poll()] == ["a", "c"]


def test_event_tail_from_end_ignores_history(jd):
    jobstate.EventLog(jd).append("old")
    tail = jobstate.EventTail(jd, from_start=False)
    jobstate.EventLog(jd).append("new")
    assert [e["k"] for e in tail.poll()] == ["new"]


# ---- resume planning ----------------------------------------------------------------------------

def _set(jd, *statuses):
    st = jobstate.load_state(jd)
    for r, s in zip(st["runs"], statuses):
        r["status"] = s
    return st


def test_plan_resume_redoes_the_interrupted_run_only(jd):
    st = _set(jd, "done", "running", "pending")
    notes = jobstate.plan_resume(st)
    assert [r["status"] for r in st["runs"]] == ["done", "pending", "pending"]
    assert len(notes) == 1 and "interrupted" in notes[0]


def test_plan_resume_keeps_failures_unless_asked(jd):
    st = _set(jd, "failed", "contract_violation", "done")
    jobstate.plan_resume(st)
    assert [r["status"] for r in st["runs"]] == ["failed", "contract_violation", "done"]
    jobstate.plan_resume(st, retry_failed=True)
    # a contract violation is never retried automatically: it would fail the same way
    assert [r["status"] for r in st["runs"]] == ["pending", "contract_violation", "done"]


# ---- liveness ---------------------------------------------------------------------------------

def _running(jd, pid, created=None, hb_age=0.0, out_age=0.0, frame_interval=None):
    st = jobstate.load_state(jd)
    st["status"] = "running"
    st["worker"] = {"pid": pid, "token": "tok", "create_time": created}
    st["runs"][0].update(status="running", stage="inference", frame_interval_s=frame_interval)
    jobstate.save_state(jd, st)
    jobstate.write_heartbeat(jd, pid, "tok", 1)
    hb = jobstate.read_json(jd / "heartbeat.json")
    hb["time"] = time.time() - hb_age
    jobstate.atomic_write_json(jd / "heartbeat.json", hb)
    (jd / "events.jsonl").write_text('{"k": "x"}\n')
    t = time.time() - out_age
    os.utime(jd / "events.jsonl", (t, t))


ME = os.getpid()
NOT_A_PID = 2 ** 22 - 7


def test_liveness_running(jd):
    _running(jd, ME, procs.create_time(ME))
    assert jobstate.liveness(jd).state == "running"


def test_liveness_dead_when_the_pid_is_gone(jd):
    _running(jd, NOT_A_PID)
    live = jobstate.liveness(jd)
    assert live.state == "dead" and live.resumable


def test_liveness_dead_when_the_pid_was_reused_by_another_process(jd):
    _running(jd, ME, created=12345.0)              # our pid, but a different start time
    assert jobstate.liveness(jd).state == "dead"


def test_liveness_unresponsive_when_the_heartbeat_is_stale(jd):
    _running(jd, ME, procs.create_time(ME), hb_age=60)
    assert jobstate.liveness(jd).state == "unresponsive"


def test_liveness_ignores_a_heartbeat_from_another_worker(jd):
    _running(jd, ME, procs.create_time(ME))
    hb = jobstate.read_json(jd / "heartbeat.json")
    hb["token"] = "someone-else"
    jobstate.atomic_write_json(jd / "heartbeat.json", hb)
    assert jobstate.liveness(jd).state == "unresponsive"


def test_liveness_stalled_when_alive_but_silent(jd):
    _running(jd, ME, procs.create_time(ME), out_age=200)
    live = jobstate.liveness(jd)
    assert live.state == "stalled" and "inference" in live.detail


def test_slow_cpu_frames_do_not_read_as_stalled(jd):
    # 60 s per frame (plausible for CPU inference): 200 s of silence is normal
    _running(jd, ME, procs.create_time(ME), out_age=200, frame_interval=60.0)
    assert jobstate.liveness(jd).state == "running"


def test_liveness_finished_and_none(jd, tmp):
    st = jobstate.load_state(jd)
    st["status"] = "finished_with_failures"
    jobstate.save_state(jd, st)
    assert jobstate.liveness(jd).state == "finished_with_failures"
    assert jobstate.liveness(tmp / "nowhere").state == "none"


# ---- lock ------------------------------------------------------------------------------------

def test_lock_is_exclusive_and_stale_locks_are_taken_over(jd):
    ok, _ = jobstate.acquire_lock(jd, ME, "a")
    assert ok
    ok2, why = jobstate.acquire_lock(jd, ME, "b")
    assert not ok2 and "already running" in why
    jobstate.release_lock(jd, "b")                     # not the owner: no effect
    assert (jd / "worker.lock").exists()
    jobstate.release_lock(jd, "a")
    assert not (jd / "worker.lock").exists()
    (jd / "worker.lock").write_text(json.dumps({"pid": NOT_A_PID, "token": "dead"}))
    ok3, _ = jobstate.acquire_lock(jd, ME, "c")        # owner is dead: taken over
    assert ok3


# ---- timings ------------------------------------------------------------------------------

def test_timings_use_batch_runs_schema(jd):
    st = _set(jd, "done", "failed", "pending")
    st["runs"][0]["timings"] = {"frames": 497, "inference_s": 411.0, "total_s": 1342.3}
    st["runs"][1]["error"] = "RuntimeError: boom"
    jobstate.write_timings(jd, st)
    lines = (jd / "timings.csv").read_text().splitlines()
    assert lines[0].split(",")[:2] == ["run", "status"]          # batch_runs puts these first
    assert len(lines) == 3                                         # pending runs have no row
    assert ",ok," in lines[1] and "FAILED: RuntimeError: boom" in lines[2]
    assert json.loads((jd / "timings.json").read_text())[0]["inference_s"] == 411.0


def test_stop_flag_round_trip(jd):
    assert not jobstate.stop_requested(jd)
    jobstate.request_stop(jd)
    assert jobstate.stop_requested(jd)
    jobstate.clear_stop(jd)
    assert not jobstate.stop_requested(jd)
