"""Shared helpers for the batch-worker tests: a sandbox of fake 10/05-format runs,
job creation, and waiting on a detached worker."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from src.ai.Taguchi_Analysis_UI import jobstate, paths, procs
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI.tests import fakes


def sandbox(tmp: Path, monkeypatch, n_runs: int = 3) -> tuple[Path, list[Path]]:
    """Fake runs under tmp, with the sandbox guard and calibration file pointed at tmp."""
    monkeypatch.setenv("TAGUCHI_UI_SANDBOX_ROOT", str(tmp))
    monkeypatch.setenv("TAGUCHI_UI_CALIBRATION", str(tmp / "calib.json"))
    runs = [fakes.make_run(tmp, name) for name, _, _ in fakes.REAL_10_05[:n_runs]]
    return tmp / "output", runs


def new_job(out: Path, runs, options=None, settings=None) -> Path:
    return jobstate.create_job(out, runs, settings or spec.RunSettings(),
                               options or spec.default_options())


def stub_args(*extra, stage_s=0.01, heartbeat=0.3) -> list[str]:
    return ["--impl", "stub", "--stub-stage-s", str(stage_s), "--heartbeat-s", str(heartbeat), *extra]


def wait_for(pred, timeout=60.0, step=0.05, what="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


def wait_exit(p: subprocess.Popen, timeout=60.0) -> int:
    try:
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        procs.kill_tree(p.pid)
        raise AssertionError("worker did not finish in time")


def run_state(jd: Path, i: int) -> dict:
    return (jobstate.load_state(jd) or {"runs": [{}] * (i + 1)})["runs"][i]


def kill9(pid: int) -> None:
    """SIGKILL the worker ONLY -- not its process group -- exactly like a crash or an
    OS kill, which leaves its pipeline children running."""
    import signal
    os.kill(pid, signal.SIGKILL)


def run_worker_inline(jd: Path, *args) -> subprocess.CompletedProcess:
    """A worker in the foreground (for exit-code tests)."""
    return subprocess.run([sys.executable, "-m", procs.WORKER_MODULE, "--job", str(jd), *args],
                          cwd=str(paths.REPO_ROOT), capture_output=True, text=True, timeout=120)
