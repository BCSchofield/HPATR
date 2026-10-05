"""fsops: replacing and deleting files survives Windows sharing violations.

Windows refuses to rename over, or delete, a file another process has open (Python's
open() grants no delete-sharing). These tests make os.replace / os.unlink fail the way
Windows does and check that every writer the worker and the analysis use rides it out."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import eta, fsops, jobstate

PKG = Path(fsops.__file__).parent


def flaky(real, failures: int):
    """A stand-in for os.replace / os.unlink that is 'locked' for the first N calls."""
    state = {"n": 0}

    def op(*a, **k):
        state["n"] += 1
        if state["n"] <= failures:
            raise PermissionError(13, "The process cannot access the file because it is being used "
                                      "by another process")
        return real(*a, **k)
    op.state = state
    return op


def test_replace_rides_out_a_brief_lock(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a"
    src.write_text("new")
    dst.write_text("old")
    op = flaky(os.replace, 5)
    monkeypatch.setattr(os, "replace", op)
    fsops.replace(src, dst)
    assert dst.read_text() == "new" and not src.exists() and op.state["n"] == 6


def test_a_lock_that_never_clears_still_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(fsops, "ATTEMPTS", 3)
    monkeypatch.setattr(os, "replace", flaky(os.replace, 99))
    with pytest.raises(PermissionError):
        fsops.replace(tmp_path / "x", tmp_path / "y")


def test_other_errors_are_not_retried(tmp_path, monkeypatch):
    calls = []

    def missing(*a):
        calls.append(1)
        raise FileNotFoundError("gone")
    monkeypatch.setattr(os, "replace", missing)
    with pytest.raises(FileNotFoundError):
        fsops.replace(tmp_path / "x", tmp_path / "y")
    assert calls == [1]


def test_unlink_retries_and_tolerates_a_missing_file(tmp_path, monkeypatch):
    f = tmp_path / "lock"
    f.write_text("x")
    monkeypatch.setattr(os, "unlink", flaky(os.unlink, 3))
    fsops.unlink(f)
    assert not f.exists()
    fsops.unlink(f)                                       # already gone: fine
    with pytest.raises(FileNotFoundError):
        fsops.unlink(f, missing_ok=False)


def test_the_workers_state_heartbeat_and_timings_survive_a_ui_reading_them(tmp_path, monkeypatch):
    jd = tmp_path / "_job"
    jd.mkdir()
    monkeypatch.setattr(os, "replace", flaky(os.replace, 4))
    jobstate.save_state(jd, {"runs": [], "status": "running"})
    monkeypatch.setattr(os, "replace", flaky(os.replace, 4))
    jobstate.write_heartbeat(jd, 1, "t", 1)
    monkeypatch.setattr(os, "replace", flaky(os.replace, 4))
    jobstate.write_timings(jd, {"runs": [{"name": "r", "status": "done", "timings": {"total_s": 1.0}}]})
    assert json.loads((jd / "state.json").read_text())["status"] == "running"
    assert (jd / "heartbeat.json").is_file() and (jd / "timings.csv").is_file()


def test_the_lock_file_is_released_even_while_something_reads_it(tmp_path, monkeypatch):
    jd = tmp_path / "_job"
    jd.mkdir()
    ok, _ = jobstate.acquire_lock(jd, os.getpid(), "tok")
    assert ok
    monkeypatch.setattr(os, "unlink", flaky(os.unlink, 3))
    jobstate.release_lock(jd, "tok")
    assert not (jd / "worker.lock").exists()


def test_eta_calibration_saves_through_a_brief_lock(tmp_path, monkeypatch):
    c = eta.Calibration.load(tmp_path / "calib.json")
    c.add("k", 1.5)
    monkeypatch.setattr(os, "replace", flaky(os.replace, 4))
    c.save()
    assert json.loads((tmp_path / "calib.json").read_text())["rates"]["k"] == [1.5]


def test_no_module_replaces_or_deletes_files_except_through_fsops():
    """Guards the fix: a bare os.replace / Path.replace / unlink reintroduces the Windows crash."""
    offenders = []
    for f in PKG.glob("*.py"):
        if f.name == "fsops.py":
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = node.func.attr
                owner = node.func.value
                if name == "replace" and isinstance(owner, ast.Name) and owner.id == "os":
                    offenders.append(f"{f.name}:{node.lineno} os.replace")
                if name == "replace" and isinstance(owner, ast.Name) and owner.id in ("tmp", "src"):
                    offenders.append(f"{f.name}:{node.lineno} Path.replace")
                if name == "unlink" and f.name in ("jobstate.py", "worker.py") and not (
                        isinstance(owner, ast.Name) and owner.id == "fsops"):
                    offenders.append(f"{f.name}:{node.lineno} unlink")
    assert offenders == []
