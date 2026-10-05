"""jobstate.py -- everything about a batch job that lives on disk.

The worker and the UI never talk directly. They share a folder:

    <output folder>/_job/
        job.json          what to do (written once, by whoever launches the job)
        state.json        how far it got (worker, atomic rewrite at every stage)
        events.jsonl      what happened, one JSON object per line, append-only
        heartbeat.json    "I am alive" (worker, every few seconds, separate thread)
        worker.lock       one worker per job at a time
        worker.log        the worker's raw stdout/stderr
        logs/NN_<run>.log full pipeline output for each run
        timings.csv/.json batch_runs.py's schema, rewritten after every run
        stop              (UI creates it) "stop after the current run"

Files, not sockets: no ports or permissions, identical on macOS and Windows, a
`kill -9` loses at most one half-written line (the reader discards it), and the
folder is the audit trail.

ATOMICITY. state.json is written to a temp file and os.replace()d into place,
which is atomic on POSIX and NTFS: a reader sees the old file or the new one,
never half of one. exFAT (the LaCie) does not promise atomic rename, so the
reader also tolerates a corrupt read and retries.
"""
from __future__ import annotations

import csv
import json
import os
import platform
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths
from . import pipeline_spec as spec
from . import procs

SCHEMA = 1
JOB_DIRNAME = "_job"
ARCHIVE_DIRNAME = "_job_archive"

HEARTBEAT_S = 5.0
UNRESPONSIVE_S = 30.0        # heartbeat older than this: the worker is not answering
DEAD_S = 120.0               # ... older than this, with the pid gone: it has died
STALL_S = 90.0               # no output for this long while alive: stuck in a stage?

FINISHED = ("finished", "finished_with_failures", "halted", "stopped")


class JobBusy(RuntimeError):
    """A live worker already owns this output folder."""


def job_dir(output_dir: Path) -> Path:
    return Path(output_dir) / JOB_DIRNAME


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---- JSON on disk ---------------------------------------------------------------------

def atomic_write_json(path: Path, obj: Any) -> None:
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(obj, indent=1, default=str)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None, retries: int = 3) -> Any:
    for i in range(retries):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            if i == retries - 1:
                return default
            time.sleep(0.05)
    return default


# ---- creating a job ---------------------------------------------------------------------

def _settings_dict(settings: spec.RunSettings) -> dict:
    return {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(settings).items()}


def settings_from(d: dict) -> spec.RunSettings:
    d = dict(d or {})
    if d.get("model_dir"):
        d["model_dir"] = Path(d["model_dir"])
    return spec.RunSettings(**d)


def initial_state(job: dict) -> dict:
    return {
        "schema": SCHEMA, "job_id": job["job_id"], "status": "pending", "updated": now_iso(),
        "images": job["options"].get("images"),
        "runs": [{"index": i, "path": p, "name": Path(p).name, "status": "pending",
                  "attempts": 0, "stage": None, "seconds": {}, "error": None}
                 for i, p in enumerate(job["runs"])],
        "worker": None, "eta": None,
    }


def create_job(output_dir: Path, run_dirs: list[Path], settings: spec.RunSettings,
               options: dict, *, preflight: spec.PreflightReport | None = None) -> Path:
    """Write a new job into <output_dir>/_job. A previous FINISHED or dead job there
    is archived first; a LIVE one raises JobBusy (never two workers on one folder)."""
    output_dir = Path(output_dir)
    jd = job_dir(output_dir)
    if jd.exists():
        live = liveness(jd)
        if live.state in ("running", "stalled", "unresponsive"):
            raise JobBusy(f"a batch is still running in {jd} ({live.detail})")
        old = read_json(jd / "job.json", {}) or {}
        dest = output_dir / ARCHIVE_DIRNAME / (old.get("job_id") or f"unknown_{int(time.time())}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(jd), str(dest))
    jd.mkdir(parents=True)
    (jd / "logs").mkdir()
    commit, dirty = paths.repo_commit("AI/Real_Data_Code")
    job = {
        "schema": SCHEMA,
        "job_id": datetime.now().strftime("%Y-%m-%dT%H-%M-%S_") + uuid.uuid4().hex[:4],
        "created": now_iso(),
        "output_dir": str(output_dir),
        "runs": [str(Path(p)) for p in run_dirs],
        "settings": _settings_dict(settings),
        "options": dict(options),
        "repo_commit": commit, "pipeline_dirty": dirty,
        "script_hashes": preflight.script_hashes if preflight else spec.script_hashes(),
        "python": sys.executable, "platform": platform.platform(), "host": platform.node(),
    }
    atomic_write_json(jd / "job.json", job)
    atomic_write_json(jd / "state.json", initial_state(job))
    return jd


def load_job(jd: Path) -> dict | None:
    return read_json(Path(jd) / "job.json")


def load_state(jd: Path) -> dict | None:
    return read_json(Path(jd) / "state.json")


def save_state(jd: Path, state: dict) -> None:
    state["updated"] = now_iso()
    atomic_write_json(Path(jd) / "state.json", state)


def plan_resume(state: dict, retry_failed: bool = False) -> list[str]:
    """Prepare a state for a new worker. Returns what changed, for the log.

    `running` -> `pending`: that run was interrupted mid-way; it is redone (with
    reuse, so finished extraction/inference on disk is not repeated).
    `failed` -> `pending` only if asked. `contract_violation` is never retried
    automatically: the pipeline no longer matches the contract, and running it
    again would fail the same way."""
    notes = []
    for r in state["runs"]:
        if r["status"] == "running":
            r["status"], r["stage"] = "pending", None
            notes.append(f"{r['name']}: was interrupted during a run; will be redone")
        elif r["status"] == "failed" and retry_failed:
            r["status"], r["error"], r["stage"] = "pending", None, None
            notes.append(f"{r['name']}: failed last time; retrying")
    state["status"] = "pending"
    return notes


def counts(state: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in state.get("runs", []):
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


# ---- events --------------------------------------------------------------------------------

class EventLog:
    """Append-only JSON lines. One open/append/flush per event: simple, and a kill
    can corrupt at most the line being written."""

    def __init__(self, jd: Path):
        self.path = Path(jd) / "events.jsonl"

    def append(self, kind: str, **fields) -> dict:
        ev = {"t": now_iso(), "k": kind, **fields}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, default=str) + "\n")
            f.flush()
        return ev


class EventTail:
    """Reads new events since the last call, by byte offset. A last line without
    its newline is a write in progress: it is left for next time, not parsed."""

    def __init__(self, jd: Path, from_start: bool = True):
        self.path = Path(jd) / "events.jsonl"
        self.offset = 0 if from_start else (self.path.stat().st_size if self.path.exists() else 0)

    def poll(self) -> list[dict]:
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except FileNotFoundError:
            return []
        if not chunk:
            return []
        end = chunk.rfind(b"\n")
        if end < 0:
            return []
        self.offset += end + 1
        out = []
        for line in chunk[:end].splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue                     # a line torn by a kill: skip it
        return out


# ---- heartbeat + lock ---------------------------------------------------------------------

def write_heartbeat(jd: Path, pid: int, token: str, seq: int, info: dict | None = None) -> None:
    atomic_write_json(Path(jd) / "heartbeat.json",
                      {"pid": pid, "token": token, "seq": seq, "time": time.time(), **(info or {})})


def acquire_lock(jd: Path, pid: int, token: str) -> tuple[bool, str]:
    """One worker per job. A lock left by a dead worker is taken over."""
    lock = Path(jd) / "worker.lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = read_json(lock, {}) or {}
            if held.get("pid") and procs.is_alive(held["pid"], held.get("create_time")):
                return False, f"another worker (pid {held['pid']}) is already running this job"
            try:
                lock.unlink()            # stale: its owner is gone
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "token": token, "create_time": procs.create_time(pid),
                       "started": now_iso()}, f)
        return True, "ok"
    return False, "could not take the worker lock"


def release_lock(jd: Path, token: str) -> None:
    lock = Path(jd) / "worker.lock"
    held = read_json(lock, {}) or {}
    if held.get("token") == token:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def request_stop(jd: Path) -> None:
    (Path(jd) / "stop").write_text(now_iso(), encoding="utf-8")


def stop_requested(jd: Path) -> bool:
    return (Path(jd) / "stop").exists()


def clear_stop(jd: Path) -> None:
    try:
        (Path(jd) / "stop").unlink()
    except FileNotFoundError:
        pass


# ---- liveness --------------------------------------------------------------------------

@dataclass
class Liveness:
    state: str          # none | pending | running | stalled | unresponsive | dead | <FINISHED>
    detail: str
    pid: int | None = None
    heartbeat_age: float | None = None
    output_age: float | None = None
    n_done: int = 0
    n_total: int = 0

    @property
    def resumable(self) -> bool:
        return self.state in ("dead", "pending", "stopped") and self.n_done < self.n_total


def liveness(jd: Path, now: float | None = None, stall_s: float = STALL_S) -> Liveness:
    """What is the worker doing? Distinguishes a worker that is DEAD from one that
    is ALIVE BUT SILENT (stalled) -- the heartbeat runs on its own thread, so a hung
    stage still heartbeats but stops producing output."""
    jd = Path(jd)
    now = time.time() if now is None else now
    state = load_state(jd)
    if not state:
        return Liveness("none", "no job here")
    c = counts(state)
    n_total = len(state.get("runs", []))
    n_done = c.get("done", 0)
    base = dict(n_done=n_done, n_total=n_total)
    status = state.get("status", "pending")
    w = state.get("worker") or {}
    if status in FINISHED:
        return Liveness(status, f"{status.replace('_', ' ')}: {n_done}/{n_total} done", w.get("pid"), **base)
    if status != "running":
        return Liveness("pending", f"not started ({n_done}/{n_total} done)", **base)

    hb = read_json(jd / "heartbeat.json", {}) or {}
    hb_age = now - hb["time"] if hb.get("token") == w.get("token") and hb.get("time") else None
    ev = jd / "events.jsonl"
    out_age = now - ev.stat().st_mtime if ev.exists() else None
    alive = procs.is_alive(w.get("pid"), w.get("create_time"))
    extra = dict(pid=w.get("pid"), heartbeat_age=hb_age, output_age=out_age, **base)

    if not alive:
        return Liveness("dead", f"the worker has stopped unexpectedly ({n_done}/{n_total} done)", **extra)
    if hb_age is None or hb_age > UNRESPONSIVE_S:
        age = "never" if hb_age is None else f"{hb_age:.0f}s ago"
        return Liveness("unresponsive", f"worker pid {w.get('pid')} is not answering "
                                        f"(last heartbeat {age})", **extra)
    # A stage that legitimately takes long per frame (CPU inference) must not read
    # as stalled: allow 4x the stage's own observed time between frames.
    cur = next((r for r in state["runs"] if r.get("status") == "running"), {}) or {}
    limit = max(stall_s, 4 * (cur.get("frame_interval_s") or 0))
    if out_age is not None and out_age > limit:
        where = f" in {cur.get('stage')}" if cur.get("stage") else ""
        return Liveness("stalled", f"no output for {out_age:.0f}s{where} (worker alive)", **extra)
    return Liveness("running", f"{n_done}/{n_total} done", **extra)


# ---- timings (batch_runs.py's schema) ---------------------------------------------------------

def timings_row(run: dict) -> dict:
    """One row exactly as batch_runs.py writes it (its lines 72-107), so existing
    tools that read timings.csv keep working."""
    row = {"run": run["name"], "started": run.get("started", "")}
    status = run.get("status")
    row["status"] = "ok" if status == "done" else f"FAILED: {run.get('error')}" if status in (
        "failed", "contract_violation") else status
    for key, val in (run.get("timings") or {}).items():
        row[key] = val
    return row


def write_timings(jd: Path, state: dict) -> None:
    rows = [timings_row(r) for r in state["runs"] if r.get("status") in
            ("done", "failed", "contract_violation")]
    if not rows:
        return
    fields = sorted({f for r in rows for f in r}, key=lambda f: (f not in ("run", "status"), f))
    tmp = Path(jd) / ".timings.csv.tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, Path(jd) / "timings.csv")
    atomic_write_json(Path(jd) / "timings.json", rows)


# ---- controlling a worker -------------------------------------------------------------------

def kill_worker(jd: Path, grace: float = 5.0) -> bool:
    """Stop NOW: the worker and the pipeline stage it is running. Returns True if
    something was killed. The interrupted run is redone on resume."""
    state = load_state(jd) or {}
    w = state.get("worker") or {}
    if not procs.is_alive(w.get("pid"), w.get("create_time")):
        return False
    procs.kill_tree(w["pid"], w.get("pgid"), grace=grace)
    return True


def start_job(output_dir: Path, run_dirs: list[Path], settings: spec.RunSettings, options: dict,
              *, preflight: spec.PreflightReport, extra_args=()):
    """Create a job and start its detached worker. Refuses unless preflight passed:
    the batch must never run against a pipeline whose interface has drifted."""
    if preflight is None or not preflight.ok:
        raise RuntimeError("preflight has not passed; the batch is disabled")
    if not run_dirs:
        raise ValueError("no runnable runs selected")
    jd = create_job(output_dir, run_dirs, settings, options, preflight=preflight)
    return jd, procs.spawn_detached(jd, list(extra_args))


def resume(jd: Path, retry_failed: bool = False, extra_args=()):
    """Start a worker on an existing job (dead, stopped or never started)."""
    live = liveness(jd)
    if live.state in ("running", "stalled", "unresponsive"):
        raise JobBusy(f"the worker is still {live.state}: {live.detail}")
    clear_stop(jd)
    args = list(extra_args) + (["--retry-failed"] if retry_failed else [])
    return procs.spawn_detached(jd, args)
