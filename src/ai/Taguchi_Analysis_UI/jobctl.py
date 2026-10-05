"""jobctl.py -- drive a batch job from the command line.

    python -m src.ai.Taguchi_Analysis_UI.jobctl start  <output folder> <day/run folders...>
                                                   [--limit N] [--images all] [--device cpu|mps|cuda]
    python -m src.ai.Taguchi_Analysis_UI.jobctl status <output folder>
    python -m src.ai.Taguchi_Analysis_UI.jobctl watch  <output folder>    live, Ctrl-C to leave
    python -m src.ai.Taguchi_Analysis_UI.jobctl resume <output folder> [--retry-failed]
    python -m src.ai.Taguchi_Analysis_UI.jobctl stop   <output folder>    after the current run
    python -m src.ai.Taguchi_Analysis_UI.jobctl kill   <output folder>    now (run is redone on resume)

`watch` only reads the job folder: leaving it (or closing the terminal) never
affects the worker. The UI (Phase 6) does the same things through the same
functions.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import eta, jobstate
from . import pipeline_spec as spec


def status_lines(output_dir: Path) -> list[str]:
    jd = jobstate.job_dir(output_dir)
    live = jobstate.liveness(jd)
    lines = [f"job: {jd}", f"worker: {live.state} — {live.detail}"]
    state = jobstate.load_state(jd)
    if not state:
        return lines
    c = jobstate.counts(state)
    lines.append("runs: " + ", ".join(f"{v} {k}" for k, v in sorted(c.items())))
    cur = next((r for r in state["runs"] if r["status"] == "running"), None)
    if cur:
        p = cur.get("progress") or {}
        frac = f" {p['done']}/{p['total']}" if p.get("total") else ""
        lines.append(f"now: {cur['index'] + 1}/{len(state['runs'])} {cur['name']} · "
                     f"{cur.get('stage') or 'starting'}{frac}")
    est = eta.estimate(state, state.get("images"), calib=eta.Calibration.load())
    if live.state in ("running", "stalled", "unresponsive"):
        lines.append(eta.describe(est))
    for r in state["runs"]:
        if r["status"] in ("failed", "contract_violation"):
            lines.append(f"  {r['status'].upper()}: {r['name']}: {r.get('error')}")
    if live.resumable:
        lines.append("resume with: jobctl resume <output folder>")
    elif c.get("failed") and live.state in jobstate.FINISHED:
        lines.append("retry the failed runs with: jobctl resume <output folder> --retry-failed")
    return lines


def start(a) -> int:
    from . import run_discovery as rd
    if a.sandbox:
        os.environ["TAGUCHI_UI_SANDBOX_ROOT"] = str(a.sandbox.resolve())
    print("preflight ...")
    report = spec.preflight_fresh()
    print("\n".join(report.render()))
    if not report.ok:
        return 2
    settings = spec.RunSettings(limit=a.limit, device=a.device)
    s = spec.effective(settings)
    found = rd.find_runs(a.folders)
    runs = rd.load_runs(found.runs, thr=s.score_thresh, stride=s.stride, check_reuse=False)
    for p, why in found.skipped:
        print(f"skipped {p.name}: {why}")
    ok = [r for r in runs if r.runnable]
    for r in runs:
        if not r.runnable:
            print(f"not runnable, left out: {r.name}: " + "; ".join(i.message for i in r.errors))
    print(rd.summarise(ok).headline())
    if not ok:
        return 1
    options = dict(spec.default_options(), images=a.images)
    jd, p = jobstate.start_job(a.output_dir, [r.path for r in ok], settings, options, preflight=report)
    print(f"started worker pid {p.pid} on {len(ok)} runs; job folder {jd}")
    print(f"watch with: python -m src.ai.Taguchi_Analysis_UI.jobctl watch {a.output_dir}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.ai.Taguchi_Analysis_UI.jobctl")
    ap.add_argument("command", choices=["start", "status", "watch", "resume", "stop", "kill"])
    ap.add_argument("output_dir", type=Path)
    ap.add_argument("folders", type=Path, nargs="*", help="start: run or day folders")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="start: first N frames only (smoke test)")
    ap.add_argument("--images", choices=["extremes", "all"], default="extremes")
    ap.add_argument("--device", default=None, help="start: cpu / mps / cuda (default: auto)")
    ap.add_argument("--sandbox", type=Path, default=None,
                    help="start: refuse any run outside this folder (testing)")
    a = ap.parse_args(argv)
    if a.command == "start":
        return start(a)
    jd = jobstate.job_dir(a.output_dir)
    if not (jd / "job.json").exists():
        print(f"no job in {a.output_dir}")
        return 1

    if a.command == "status":
        print("\n".join(status_lines(a.output_dir)))
    elif a.command == "watch":
        tail = jobstate.EventTail(jd, from_start=False)
        print("\n".join(status_lines(a.output_dir)))
        try:
            while True:
                for ev in tail.poll():
                    if ev["k"] in ("log", "warn", "error", "run_start", "run_end", "stage_start",
                                   "job_start", "job_end"):
                        body = ev.get("line") or ev.get("detail") or {k: v for k, v in ev.items()
                                                                     if k not in ("t", "k")}
                        print(f"[{ev['t'][11:]}] {ev['k']:>11}  {body}")
                live = jobstate.liveness(jd)
                if live.state not in ("running", "stalled", "unresponsive"):
                    print(f"worker {live.state}: {live.detail}")
                    return 0
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n(left the watch; the worker keeps running)")
    elif a.command == "resume":
        p = jobstate.resume(jd, retry_failed=a.retry_failed)
        print(f"worker started, pid {p.pid}")
    elif a.command == "stop":
        jobstate.request_stop(jd)
        print("stop requested: the worker will stop after the current run")
    elif a.command == "kill":
        print("killed" if jobstate.kill_worker(jd) else "no live worker to kill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
