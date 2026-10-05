"""worker.py -- the detached batch process. NO Qt imports, ever.

    python -m src.ai.Taguchi_Analysis_UI.worker --job <output>/_job [--retry-failed]

Started by procs.spawn_detached() (or jobctl), it runs every pending run of the
job in order and records everything in the job folder (see jobstate.py). It
survives the UI closing; if it dies, a new worker resumes from state.json.

Per run (the same chain batch_runs.py runs, through pipeline_spec's builders):
    1. process_capture.process_capture(...)   extract, background, inference, measure
    2. process_capture._run(classical_cmd)    classical_liquid.py, output STREAMED
    3. pipeline_spec checks                   folder name returned, artefacts present
A failed run is recorded and the batch moves on (as batch_runs does). A CONTRACT
VIOLATION halts the batch: if the pipeline no longer produces what the contract
promises, every later run would be wrong in the same way.

Exit codes: 0 all done, 1 finished with failed runs, 2 halted (contract), 3 another
worker owns the job, 4 stopped on request, 5 bad job folder.
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import eta, jobstate, procs, progress
from . import pipeline_spec as spec


class HaltBatch(Exception):
    pass


def _own_group() -> int | None:
    """Our process-group id if we lead it, else None (never someone else's group)."""
    if not hasattr(os, "getpgid"):
        return None
    pg = os.getpgid(0)
    return pg if pg == os.getpid() else None


# ---- the pipeline implementation (real, or the stub for tests) -----------------------

class RealPipeline:
    def __init__(self):
        pc = spec.rdc_module("process_capture")
        self.process_capture = pc.process_capture
        self.run = pc._run        # the canonical streaming runner (see pipeline_spec.HELPERS)


def make_pipeline(args) -> object:
    if args.impl == "real":
        return RealPipeline()
    from .stub_pipeline import Stub
    omit: dict = {}
    for item in args.stub_omit or []:
        oid, name = item.split("@", 1)
        omit.setdefault(name, set()).add(oid)
    return Stub(frames=args.stub_frames, stage_s=args.stub_stage_s, fail=set(args.stub_fail or []),
                hang=set(args.stub_hang or []), hang_s=args.stub_hang_s, omit=omit,
                child=set(args.stub_child or []),
                child_pid_file=Path(args.job) / "stub_child.pid")


def check_sandbox_env(run_dir: Path) -> None:
    """If TAGUCHI_UI_SANDBOX_ROOT is set, refuse any run outside it (real or stub).
    Tests set it so that nothing they do can reach a real run folder."""
    root = os.environ.get("TAGUCHI_UI_SANDBOX_ROOT")
    if root:
        r, rd = Path(root).resolve(), Path(run_dir).resolve()
        if r != rd and r not in rd.parents:
            raise RuntimeError(f"{run_dir} is outside the sandbox {root}; refusing")


# ---- the worker -------------------------------------------------------------------------

class Worker:
    def __init__(self, jd: Path, pipeline, retry_failed: bool = False,
                 heartbeat_s: float = jobstate.HEARTBEAT_S):
        self.jd = Path(jd)
        self.pipeline = pipeline
        self.retry_failed = retry_failed
        self.heartbeat_s = heartbeat_s
        self.token = uuid.uuid4().hex
        self.events = jobstate.EventLog(self.jd)
        self.job = jobstate.load_job(self.jd)
        self.state = None
        self.calib = eta.Calibration.load()
        self.host = eta.host_id()
        self._hb_stop = threading.Event()
        self._last_save = 0.0
        self._job_handle = None

    # -- persistence ---------------------------------------------------------------
    def save(self, force: bool = True) -> None:
        now = time.monotonic()
        if force or now - self._last_save >= 2.0:          # progress saves are throttled
            self.state["eta"] = self._eta_snapshot()
            jobstate.save_state(self.jd, self.state)
            self._last_save = now

    def _eta_snapshot(self) -> dict | None:
        try:
            est = eta.estimate(self.state, self.state.get("images"), host=self.host, calib=self.calib)
            return {"batch_remaining_s": est.batch_remaining_s, "low_s": est.low_s,
                    "high_s": est.high_s, "measured": est.measured, "note": est.note,
                    "computed": time.time()}
        except Exception:
            return None

    def emit(self, kind: str, **fields) -> None:
        self.events.append(kind, **fields)

    # -- heartbeat ---------------------------------------------------------------
    def _heartbeat(self) -> None:
        seq = 0
        while not self._hb_stop.is_set():
            seq += 1
            cur = next((r for r in self.state["runs"] if r["status"] == "running"), None) \
                if self.state else None
            try:
                jobstate.write_heartbeat(self.jd, os.getpid(), self.token, seq,
                                         {"run": cur and cur["name"], "stage": cur and cur.get("stage")})
            except OSError:
                pass
            self._hb_stop.wait(self.heartbeat_s)

    # -- main --------------------------------------------------------------------
    def run(self) -> int:
        if not self.job:
            print(f"no job.json in {self.jd}", flush=True)
            return 5
        ok, why = jobstate.acquire_lock(self.jd, os.getpid(), self.token)
        if not ok:
            print(f"refusing to start: {why}", flush=True)
            return 3
        hb = None
        code = 0
        try:
            self.state = jobstate.load_state(self.jd) or jobstate.initial_state(self.job)
            prev = self.state.get("worker")
            killed = procs.reap_orphans(prev, log=lambda m: self.emit("warn", detail=m))
            notes = jobstate.plan_resume(self.state, self.retry_failed)
            self.state["status"] = "running"
            self.state["worker"] = {
                # Only recorded if this worker LEADS its group (spawn_detached's setsid);
                # kill_tree never signals a group it does not lead. See procs.kill_tree.
                "pid": os.getpid(), "pgid": _own_group(),
                "token": self.token, "create_time": procs.create_time(os.getpid()),
                "started": jobstate.now_iso(), "started_epoch": time.time(),
                "host": platform.node(), "python": sys.executable,
                "impl": type(self.pipeline).__name__,
            }
            self.save()
            hb = threading.Thread(target=self._heartbeat, name="heartbeat", daemon=True)
            hb.start()
            awake = procs.keep_awake()
            try:
                self._job_handle = procs.windows_job()
            except Exception as exc:                 # never fatal: costs only orphan protection
                self.emit("warn", detail=f"could not create the Windows job object ({exc}); "
                                         f"if this worker is killed, stop its pipeline stage by hand")
            self.emit("job_start", job_id=self.job["job_id"], pid=os.getpid(),
                      runs=len(self.state["runs"]), resumed=bool(prev), notes=notes,
                      orphans_stopped=killed, keep_awake=awake, impl=self.state["worker"]["impl"])
            for note in notes:
                self.emit("log", line=note)

            settings = jobstate.settings_from(self.job["settings"])
            options = self.job["options"]
            for r in self.state["runs"]:
                if r["status"] != "pending":
                    continue
                if jobstate.stop_requested(self.jd):
                    self.state["status"] = "stopped"
                    self.emit("log", line="stop requested: stopping before the next run")
                    code = 4
                    break
                self.process_run(r, settings, options)
            else:
                c = jobstate.counts(self.state)
                failed = c.get("failed", 0) + c.get("contract_violation", 0)
                self.state["status"] = "finished_with_failures" if failed else "finished"
                code = 1 if failed else 0
        except HaltBatch as exc:
            self.state["status"] = "halted"
            self.emit("error", detail=f"BATCH HALTED: {exc}")
            code = 2
        except Exception as exc:                           # a worker bug: record it, never vanish
            if self.state is not None:
                self.state["status"] = "halted"
            self.emit("error", detail=f"worker crashed: {type(exc).__name__}: {exc}",
                      traceback=traceback.format_exc())
            code = 2
        finally:
            self._hb_stop.set()
            if self.state is not None:
                self.save()
                jobstate.write_timings(self.jd, self.state)
                c = jobstate.counts(self.state)
                self.emit("job_end", status=self.state["status"], exit_code=code, counts=c)
            jobstate.release_lock(self.jd, self.token)
            if isinstance(self.pipeline, RealPipeline):
                self.calib.save()
        return code

    # -- one run -------------------------------------------------------------------
    def process_run(self, r: dict, settings: spec.RunSettings, options: dict) -> None:
        run_dir = Path(r["path"])
        t_started = time.time()
        r.update(status="running", stage=None, error=None, started=jobstate.now_iso(),
                 progress=None, seconds={}, timings={})
        r["attempts"] = r.get("attempts", 0) + 1
        tracker = progress.Tracker()
        logf = open(self.jd / "logs" / f"{r['index']:02d}_{r['name']}.log", "a", encoding="utf-8")
        t_run = time.time()
        self.save()
        self.emit("run_start", i=r["index"], name=r["name"], attempt=r["attempts"])

        def log(line) -> None:
            text = str(line)
            logf.write(text + ("" if text.endswith("\n") else "\n"))
            logf.flush()
            for ev in tracker.feed(text):
                k = ev.pop("k")
                if k == "stage_start":
                    r["stage"], r["stage_started"] = ev["stage"], time.time()
                    r["progress"] = {"done": 0, "total": ev.get("total")}
                    self.emit("stage_start", i=r["index"], **ev)
                    self.save()
                elif k == "progress":
                    r["progress"] = {"done": ev["done"], "total": ev["total"]}
                    r["frame_interval_s"] = tracker.interval_s
                    self.emit("progress", i=r["index"], **ev)
                    self.save(force=False)
                elif k == "stage_end":
                    self.emit("stage_end", i=r["index"], **ev)
                else:
                    self.emit("log", i=r["index"], line=ev["line"])
            if tracker.frames:
                r["frames"] = tracker.frames
            if tracker.device:
                r["device"] = tracker.device

        try:
            check_sandbox_env(run_dir)
            # An interrupted run is redone WITH reuse: process_capture's can_reuse()
            # keeps finished extraction + inference (and refuses anything partial or
            # older than the model), so a crash in measurement costs minutes, not 25.
            reuse = settings.reuse or r["attempts"] > 1
            run_settings = spec.RunSettings(**{**settings.__dict__, "reuse": reuse})
            s = spec.effective(run_settings)

            kwargs = spec.process_capture_kwargs(run_dir, run_settings, options, log)
            t0 = time.time()
            summary = self.pipeline.process_capture(**kwargs)
            pc_s = round(time.time() - t0, 1)

            stage_seconds = summary.get("_stage_seconds") or {}
            r["seconds"] = {progress.TIMING_TO_STAGE.get(k, k): v for k, v in stage_seconds.items()}
            r["frames"] = summary.get("_frames") or r.get("frames")
            r["reused"] = bool(summary.get("_reused_analysis"))
            r["timings"] = {"process_capture_s": pc_s, "reused_analysis": r["reused"],
                            "frames": r["frames"], "d32_um": summary.get("d32_in_focus_um"),
                            "d32_ci95": summary.get("d32_ci95"),
                            "model_atomised_pct": summary.get("atomised_pct"),
                            **{f"{k.replace(' ', '_')}_s": round(v, 1) for k, v in stage_seconds.items()}}
            for v in spec.check_stage_seconds(summary):
                self.emit("warn", i=r["index"], detail=f"{v.where}: {v.message}")
            self._halt_on(spec.check_measurement_dir(summary, run_dir, s.score_thresh), r)

            # ---- classical, streamed through the canonical runner ----
            ev = tracker.begin("classical", r.get("frames"))
            r["stage"], r["stage_started"] = "classical", time.time()
            r["progress"] = {"done": 0, "total": ev.get("total")}
            self.emit("stage_start", i=r["index"], stage="classical", total=ev.get("total"))
            self.save()
            t1 = time.time()
            self.pipeline.run(spec.classical_cmd(run_dir, run_settings, options), log)
            r["seconds"]["classical"] = round(time.time() - t1, 3)
            r["timings"]["classical_s"] = round(time.time() - t1, 1)
            self.emit("stage_end", i=r["index"], stage="classical",
                      took=eta.fmt(r["seconds"]["classical"]))
            cs = jobstate.read_json(spec.clas_dir(run_dir, s.score_thresh) / "classical_summary.json", {}) or {}
            r["timings"]["classical_atomised_pct"] = cs.get("atomised_pct_pooled")

            # since=: judge measurement/classical outputs on what THIS run wrote, so files
            # left by an earlier analysis of the same folder cannot cause a false halt
            self._halt_on(spec.verify_run_outputs(run_dir, run_settings, options,
                                                  n_frames=r.get("frames"), since=t_started), r)

            r["status"], r["stage"] = "done", None
            r["finished"] = jobstate.now_iso()
            r["timings"]["total_s"] = round(time.time() - t_run, 1)
            if isinstance(self.pipeline, RealPipeline):
                # only REAL timings teach this machine's ETA: a stub run's are fake by design, and
                # would make every future estimate on this PC absurdly short
                for key, rate in eta.observations_from_run(r, self.host, options.get("images")).items():
                    self.calib.add(key, rate)
                self.calib.save()        # after EVERY run: a later crash must not lose these timings
            self.emit("run_end", i=r["index"], name=r["name"], status="done",
                      total_s=r["timings"]["total_s"], d32=summary.get("d32_in_focus_um"),
                      atomised=cs.get("atomised_pct_pooled"))
        except HaltBatch:
            raise
        except Exception as exc:
            r["status"], r["error"] = "failed", f"{type(exc).__name__}: {exc}"
            r["timings"]["total_s"] = round(time.time() - t_run, 1)
            logf.write(traceback.format_exc())
            self.emit("run_end", i=r["index"], name=r["name"], status="failed", error=r["error"])
            self.emit("error", i=r["index"], detail=f"{r['name']} FAILED: {r['error']}",
                      traceback=traceback.format_exc())
        finally:
            logf.close()
            self.save()
            jobstate.write_timings(self.jd, self.state)

    def _halt_on(self, violations, r: dict) -> None:
        errors = [v for v in violations if v.level == "error"]
        if not errors:
            return
        r["status"] = "contract_violation"
        r["error"] = "; ".join(f"{v.where}: {v.message}" for v in errors)
        self.emit("run_end", i=r["index"], name=r["name"], status="contract_violation",
                  error=r["error"])
        for v in errors:
            self.emit("error", i=r["index"], detail=f"CONTRACT: {v.where}: {v.message}",
                      fix=v.fix)
        raise HaltBatch(f"{r['name']}: the pipeline output does not match pipeline_spec.py "
                        f"({len(errors)} problem(s)); later runs would be wrong the same way")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.ai.Taguchi_Analysis_UI.worker")
    ap.add_argument("--job", required=True, help="the _job folder")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--impl", choices=["real", "stub"], default="real")
    ap.add_argument("--heartbeat-s", type=float, default=jobstate.HEARTBEAT_S)
    # stub-only test hooks
    ap.add_argument("--stub-frames", type=int, default=6)
    ap.add_argument("--stub-stage-s", type=float, default=0.01)
    ap.add_argument("--stub-fail", action="append")
    ap.add_argument("--stub-hang", action="append")
    ap.add_argument("--stub-hang-s", type=float, default=60.0)
    ap.add_argument("--stub-omit", action="append", help="OUTPUT_ID@RUN_NAME")
    ap.add_argument("--stub-child", action="append")
    args = ap.parse_args(argv)

    jd = Path(args.job)
    if not (jd / "job.json").is_file():
        print(f"not a job folder (no job.json): {jd}", flush=True)
        return 5
    print(f"[{jobstate.now_iso()}] worker pid {os.getpid()} starting on {jd} "
          f"(impl {args.impl}, python {sys.executable})", flush=True)
    worker = Worker(jd, make_pipeline(args), retry_failed=args.retry_failed,
                    heartbeat_s=args.heartbeat_s)
    code = worker.run()
    print(f"[{jobstate.now_iso()}] worker exiting with code {code}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
