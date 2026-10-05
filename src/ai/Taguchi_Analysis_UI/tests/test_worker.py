"""The batch worker, end to end, with real detached processes and the stub pipeline.

These reproduce what has actually gone wrong with this batch before: the
handoff records it being killed twice, a monitor that only grepped for 'done'
stayed silent through a kill, and an orphaned stage could race a restart.
POSIX-only where they send signals; the Windows equivalents are in test_procs.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import jobstate, paths, procs
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI.tests import fakes
from src.ai.Taguchi_Analysis_UI.tests.workerkit import (
    kill9, new_job, run_state, run_worker_inline, sandbox, stub_args, wait_exit, wait_for)

posix_only = pytest.mark.skipif(os.name == "nt", reason="uses POSIX signals")


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def events(jd):
    return [json.loads(l) for l in (jd / "events.jsonl").read_text().splitlines() if l.strip()]


# ---- the happy path ------------------------------------------------------------------

def test_a_batch_runs_every_run_and_leaves_a_complete_record(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    p = procs.spawn_detached(jd, stub_args())
    assert wait_exit(p) == 0
    st = jobstate.load_state(jd)
    assert st["status"] == "finished"
    assert [r["status"] for r in st["runs"]] == ["done"] * 3
    for run in runs:
        assert spec.verify_run_outputs(run, spec.RunSettings(), spec.default_options()) == []
    rows = (jd / "timings.csv").read_text().splitlines()
    assert len(rows) == 4 and rows[0].startswith("run,status,")
    kinds = [e["k"] for e in events(jd)]
    assert kinds[0] == "job_start" and kinds[-1] == "job_end"
    assert kinds.count("run_end") == 3 and "progress" in kinds
    assert not (jd / "worker.lock").exists()
    assert jobstate.liveness(jd).state == "finished"
    assert (jd / "logs" / f"00_{runs[0].name}.log").stat().st_size > 0


def test_every_frame_option_reaches_both_stages(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 1)
    opts = dict(spec.default_options(), images="all")
    jd = new_job(out, runs, options=opts)
    assert wait_exit(procs.spawn_detached(jd, stub_args())) == 0
    an = runs[0] / "shadowgraph" / "analysis"
    assert (an / "liquid_0.30" / "images").is_dir() and not (an / "liquid_0.30" / "extreme_images").exists()
    assert spec.verify_run_outputs(runs[0], spec.RunSettings(), opts) == []


@posix_only
def test_the_worker_survives_its_launcher_being_killed_with_its_whole_group(tmp, monkeypatch):
    """'Closing the UI' the hard way: the launcher and EVERYTHING in its process group
    get SIGTERM -- what closing a terminal or a Ctrl-C does. An undetached worker
    would be in that group and die with it; a detached one (its own session) must not.
    (Merely exiting the launcher would prove nothing: children survive a normal exit.)"""
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    launcher = subprocess.run(
        [sys.executable, "-c",
         "import os, signal, sys; from src.ai.Taguchi_Analysis_UI import procs; "
         f"p = procs.spawn_detached(r'{jd}', {stub_args(stage_s=0.03)!r}); "
         "print(p.pid, flush=True); os.killpg(os.getpgrp(), signal.SIGTERM)"],
        cwd=str(paths.REPO_ROOT), capture_output=True, text=True, timeout=60,
        start_new_session=True)
    assert launcher.returncode == -15, f"launcher should die by SIGTERM: {launcher.stderr}"
    worker_pid = int(launcher.stdout.strip().splitlines()[-1])
    assert procs.is_alive(worker_pid), "worker died with its launcher"
    wait_for(lambda: jobstate.liveness(jd).state == "finished", what="the orphaned worker to finish")
    assert jobstate.counts(jobstate.load_state(jd)) == {"done": 3}


# ---- crashes and resume --------------------------------------------------------------------

@posix_only
def test_kill_9_mid_run_is_detected_as_dead_and_resume_finishes_the_job(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    p = procs.spawn_detached(jd, stub_args("--stub-hang", runs[1].name, "--stub-hang-s", "60"))
    wait_for(lambda: run_state(jd, 1).get("stage") == "inference", what="run 2 to reach inference")
    kill9(p.pid)
    p.wait()                                           # the launcher reaps; the record stays "running"
    live = jobstate.liveness(jd)
    assert live.state == "dead" and live.resumable
    assert jobstate.load_state(jd)["status"] == "running"     # what a crash leaves behind

    q = jobstate.resume(jd, extra_args=stub_args())
    assert wait_exit(q) == 0
    st = jobstate.load_state(jd)
    assert [r["status"] for r in st["runs"]] == ["done"] * 3
    assert st["runs"][0]["attempts"] == 1                     # finished runs are NOT redone
    assert st["runs"][1]["attempts"] == 2                     # the interrupted one is
    rows = (jd / "timings.csv").read_text().splitlines()[1:]
    assert len(rows) == 3                                     # one row per run, no duplicates
    starts = [e for e in events(jd) if e["k"] == "job_start"]
    assert [s["resumed"] for s in starts] == [False, True]
    assert any("interrupted" in n for n in starts[1]["notes"])


@posix_only
def test_resume_kills_pipeline_children_orphaned_by_the_crash(tmp, monkeypatch):
    """A crash leaves the running stage subprocess alive; a resumed worker must stop
    it before redoing the run, or both would write the same predictions.json."""
    out, runs = sandbox(tmp, monkeypatch, 2)
    jd = new_job(out, runs)
    p = procs.spawn_detached(jd, stub_args("--stub-child", runs[0].name))
    pid_file = jd / "stub_child.pid"
    wait_for(pid_file.exists, what="the stage child to start")
    child = int(pid_file.read_text())
    kill9(p.pid)
    p.wait()
    time.sleep(0.3)
    assert procs.is_alive(child), "test premise: the child should outlive the killed worker"

    q = jobstate.resume(jd, extra_args=stub_args())
    wait_for(lambda: not procs.is_alive(child), timeout=15, what="the orphan to be stopped")
    assert wait_exit(q) == 0
    warn = [e for e in events(jd) if e["k"] == "warn" and "orphaned" in e.get("detail", "")]
    assert warn, "the orphan cleanup should be logged"
    assert [e for e in events(jd) if e["k"] == "job_start"][-1]["orphans_stopped"] == 1


def test_a_failed_run_is_recorded_and_the_batch_carries_on(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    assert wait_exit(procs.spawn_detached(jd, stub_args("--stub-fail", runs[1].name))) == 1
    st = jobstate.load_state(jd)
    assert [r["status"] for r in st["runs"]] == ["done", "failed", "done"]
    assert "stub measurement failure" in st["runs"][1]["error"]
    assert st["status"] == "finished_with_failures"
    assert "FAILED: RuntimeError" in (jd / "timings.csv").read_text()
    assert any(e["k"] == "error" and runs[1].name in e["detail"] for e in events(jd))


def test_retrying_a_failed_run_reuses_its_finished_inference(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 2)
    jd = new_job(out, runs)
    wait_exit(procs.spawn_detached(jd, stub_args("--stub-fail", runs[0].name)))
    assert run_state(jd, 0)["status"] == "failed"
    q = jobstate.resume(jd, retry_failed=True, extra_args=stub_args())
    assert wait_exit(q) == 0
    st = jobstate.load_state(jd)
    assert [r["status"] for r in st["runs"]] == ["done", "done"]
    assert st["runs"][0]["attempts"] == 2 and st["runs"][0]["reused"] is True
    assert st["runs"][1]["attempts"] == 1                       # the good run was left alone
    log = (jd / "logs" / f"00_{runs[0].name}.log").read_text()
    assert "reusing the existing stride-10 analysis" in log


def test_resume_without_retry_leaves_failed_runs_alone(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 2)
    jd = new_job(out, runs)
    wait_exit(procs.spawn_detached(jd, stub_args("--stub-fail", runs[0].name)))
    jobstate.load_state(jd)
    q = jobstate.resume(jd, extra_args=stub_args())
    assert wait_exit(q) == 1
    assert run_state(jd, 0)["status"] == "failed" and run_state(jd, 0)["attempts"] == 1


def test_a_contract_violation_halts_the_batch(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    code = wait_exit(procs.spawn_detached(jd, stub_args("--stub-omit", f"per_frame@{runs[1].name}")))
    assert code == 2
    st = jobstate.load_state(jd)
    assert [r["status"] for r in st["runs"]] == ["done", "contract_violation", "pending"]
    assert st["status"] == "halted"
    errs = [e for e in events(jd) if e["k"] == "error"]
    assert any("CONTRACT" in e["detail"] and "per_frame.csv" in e["detail"] for e in errs)
    assert any("BATCH HALTED" in e["detail"] for e in errs)


def test_stop_finishes_the_current_run_then_stops_and_can_resume(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 3)
    jd = new_job(out, runs)
    p = procs.spawn_detached(jd, stub_args(stage_s=0.05))
    wait_for(lambda: run_state(jd, 0).get("status") == "running", what="run 1 to start")
    jobstate.request_stop(jd)
    assert wait_exit(p) == 4
    st = jobstate.load_state(jd)
    assert st["status"] == "stopped"
    assert st["runs"][0]["status"] == "done" and st["runs"][2]["status"] == "pending"
    assert jobstate.liveness(jd).resumable
    assert wait_exit(jobstate.resume(jd, extra_args=stub_args())) == 0
    assert jobstate.counts(jobstate.load_state(jd)) == {"done": 3}


# ---- watching a live worker ----------------------------------------------------------------

def test_a_stage_that_goes_silent_reads_as_stalled_not_dead(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 1)
    jd = new_job(out, runs)
    p = procs.spawn_detached(jd, stub_args("--stub-hang", runs[0].name, "--stub-hang-s", "30"))
    try:
        wait_for(lambda: run_state(jd, 0).get("stage") == "inference", what="inference")
        live = wait_for(lambda: (lambda l: l if l.state == "stalled" else None)(
            jobstate.liveness(jd, stall_s=1.0)), timeout=10, what="stalled")
        assert live.heartbeat_age is not None and live.heartbeat_age < 2     # still heartbeating
        assert "inference" in live.detail and "worker alive" in live.detail
    finally:
        procs.kill_tree(p.pid)
        p.wait()
    assert jobstate.liveness(jd).state == "dead"


def test_a_second_worker_on_the_same_job_is_refused(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 1)
    jd = new_job(out, runs)
    p = procs.spawn_detached(jd, stub_args("--stub-hang", runs[0].name, "--stub-hang-s", "30"))
    try:
        wait_for(lambda: (jd / "worker.lock").exists() and run_state(jd, 0).get("status") == "running",
                 what="the first worker")
        second = run_worker_inline(jd, *stub_args())
        assert second.returncode == 3 and "already running" in second.stdout
        with pytest.raises(jobstate.JobBusy):
            jobstate.resume(jd)
        with pytest.raises(jobstate.JobBusy):
            new_job(out, runs)
    finally:
        procs.kill_tree(p.pid)
        p.wait()


def test_the_heartbeat_keeps_beating_through_a_long_stage(tmp, monkeypatch):
    out, runs = sandbox(tmp, monkeypatch, 1)
    jd = new_job(out, runs)
    p = procs.spawn_detached(jd, stub_args("--stub-hang", runs[0].name, "--stub-hang-s", "30"))
    try:
        seq = lambda: (jobstate.read_json(jd / "heartbeat.json", {}) or {}).get("seq", 0)
        wait_for(lambda: seq() >= 1, what="first heartbeat")
        first = seq()
        wait_for(lambda: seq() >= first + 3, timeout=5, what="three more heartbeats")
    finally:
        procs.kill_tree(p.pid)
        p.wait()


# ---- safety -----------------------------------------------------------------------------------

def test_the_stub_refuses_runs_outside_the_sandbox(tmp, monkeypatch):
    with tempfile.TemporaryDirectory() as elsewhere:
        outside = fakes.make_run(Path(elsewhere), fakes.REAL_10_05[0][0])
        out, _ = sandbox(tmp, monkeypatch, 0)
        jd = new_job(out, [outside])
        assert wait_exit(procs.spawn_detached(jd, stub_args())) == 1
        assert "outside the sandbox" in run_state(jd, 0)["error"]
        assert not (outside / "shadowgraph" / "analysis" / "droplets_0.30").exists()


def test_the_stub_refuses_to_run_at_all_without_a_sandbox(tmp, monkeypatch):
    from src.ai.Taguchi_Analysis_UI.stub_pipeline import Stub
    monkeypatch.delenv("TAGUCHI_UI_SANDBOX_ROOT", raising=False)
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    with pytest.raises(RuntimeError, match="only runs inside a sandbox"):
        Stub().process_capture(cine=run / "x.cine", run_dir=run, log=lambda s: None)


def test_the_worker_never_imports_qt():
    code = ("import sys; import src.ai.Taguchi_Analysis_UI.worker, src.ai.Taguchi_Analysis_UI.jobctl; "
            "bad=[m for m in sys.modules if m.startswith('PySide6')]; print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(paths.REPO_ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_missing_job_folder_exits_5(tmp):
    r = run_worker_inline(tmp / "nope")
    assert r.returncode == 5 and "no job.json" in r.stdout


def test_jobctl_status_reports_a_finished_job(tmp, monkeypatch):
    from src.ai.Taguchi_Analysis_UI import jobctl
    out, runs = sandbox(tmp, monkeypatch, 2)
    jd = new_job(out, runs)
    wait_exit(procs.spawn_detached(jd, stub_args("--stub-fail", runs[1].name)))
    text = "\n".join(jobctl.status_lines(out))
    assert "finished_with_failures" in text and "1 done" in text and "1 failed" in text
    assert "FAILED: " + runs[1].name in text


def test_the_real_pipeline_adapter_binds_the_canonical_functions():
    """No compute: just that --impl real calls process_capture.process_capture and the
    canonical streaming runner _run -- the functions preflight verifies."""
    from src.ai.Taguchi_Analysis_UI.worker import RealPipeline
    pc = spec.rdc_module("process_capture")
    rp = RealPipeline()
    assert rp.process_capture is pc.process_capture and rp.run is pc._run


def test_jobctl_suggests_retry_for_failed_runs(tmp, monkeypatch):
    from src.ai.Taguchi_Analysis_UI import jobctl
    out, runs = sandbox(tmp, monkeypatch, 1)
    jd = new_job(out, runs)
    wait_exit(procs.spawn_detached(jd, stub_args("--stub-fail", runs[0].name)))
    assert any("--retry-failed" in l for l in jobctl.status_lines(out))



def test_a_stub_run_never_teaches_the_machine_fake_timings(tmp, monkeypatch):
    """Real timings are remembered per machine for future ETAs; a stub's must never be."""
    out, runs = sandbox(tmp, monkeypatch, 2)
    calib = tmp / "calib.json"
    assert wait_exit(procs.spawn_detached(new_job(out, runs), stub_args())) == 0
    assert not calib.exists()



def test_a_real_run_does_teach_the_machine_its_timings(tmp, monkeypatch):
    """The other half: a REAL pipeline's timings are remembered for this machine's future ETAs
    (that is how the overnight Windows batch calibrates the lab PC). Run in-process with a stub
    that counts as real, so no cine or GPU is needed."""
    import json
    from src.ai.Taguchi_Analysis_UI import eta, worker as wk
    from src.ai.Taguchi_Analysis_UI.stub_pipeline import Stub

    class RealLike(Stub, wk.RealPipeline):
        pass

    monkeypatch.setattr(procs, "keep_awake", lambda: "test")
    out, runs = sandbox(tmp, monkeypatch, 2)
    jd = new_job(out, runs)
    assert wk.Worker(jd, RealLike(frames=6, stage_s=0.01), heartbeat_s=0.3).run() == 0
    rates = json.loads((tmp / "calib.json").read_text())["rates"]
    host = eta.host_id()
    assert any(k.startswith(f"{host}|inference|") for k in rates)
    assert all(len(v) == 2 for k, v in rates.items() if k.startswith(f"{host}|extract"))   # one per run
