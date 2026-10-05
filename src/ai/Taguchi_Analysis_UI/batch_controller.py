"""batch_controller.py -- the UI side of a batch: start, watch, stop, resume.

It never runs pipeline code. Batches run in a detached worker process (see
worker.py); this object only creates jobs, signals them, and READS the job
folder: it tails events.jsonl into the console and polls liveness for the status
line and the buttons. Closing the window closes this object, not the batch.

When an output folder is chosen (or remembered from last time), any job already
there is re-attached: recent events are replayed into the console, and a live
worker's progress resumes on screen. A dead one offers "Resume (k/N done)".
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from . import eta, jobstate
from . import pipeline_spec as spec

TAIL_MS = 500
TICK_MS = 1000
REPLAY_EVENTS = 150

LIVE = ("running", "stalled", "unresponsive")


def _short(name: str) -> str:
    return name.split("_or")[0] if name else "?"


def format_event(ev: dict, n_runs: int) -> tuple[str, str] | None:
    """One event -> (console text, level), or None to keep it off the console.
    Progress events are deliberately silent: the status line shows them."""
    k = ev.get("k")
    i = ev.get("i")
    tag = f"[{i + 1}/{n_runs}] " if isinstance(i, int) else ""
    if k == "job_start":
        how = "resumed" if ev.get("resumed") else "started"
        extra = f", stopped {ev['orphans_stopped']} orphaned stage process(es)" if ev.get("orphans_stopped") else ""
        return f"batch {how}: {ev.get('runs')} runs, worker pid {ev.get('pid')}{extra}", "info"
    if k == "run_start":
        again = f" (attempt {ev['attempt']})" if ev.get("attempt", 1) > 1 else ""
        return f"▶ {tag}{ev.get('name')}{again}", "info"
    if k == "stage_start":
        total = f" ({ev['total']} frames)" if ev.get("total") else ""
        return f"   {tag}{ev.get('stage')}{total}", "info"
    if k == "stage_end":
        return f"   {tag}{ev.get('stage')} took {ev.get('took')}", "info"
    if k == "log":
        line = ev.get("line", "")
        return (f"      {line}", "info") if line else None
    if k == "warn":
        return f"⚠ {tag}{ev.get('detail')}", "warn"
    if k == "error":
        text = f"✖ {tag}{ev.get('detail')}"
        if ev.get("fix"):
            text += f"\n      fix: {ev['fix']}"
        return text, "error"
    if k == "run_end":
        if ev.get("status") == "done":
            parts = [f"✔ {tag}{ev.get('name')} done in {eta.fmt(ev.get('total_s'))}"]
            if ev.get("d32") is not None:
                parts.append(f"D32 {ev['d32']} µm")
            if ev.get("atomised") is not None:
                parts.append(f"atomised {ev['atomised']}%")
            return " · ".join(parts), "ok"
        return f"✖ {tag}{ev.get('name')} {ev.get('status', '').upper()}: {ev.get('error')}", "error"
    if k == "job_end":
        c = ev.get("counts") or {}
        summary = ", ".join(f"{v} {s}" for s, v in sorted(c.items()))
        level = "ok" if ev.get("status") == "finished" else "warn"
        return f"batch {ev.get('status', '').replace('_', ' ')}: {summary}", level
    return None


def last_events(jd: Path, n: int = REPLAY_EVENTS) -> list[dict]:
    p = Path(jd) / "events.jsonl"
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 256_000))
            chunk = f.read()
    except FileNotFoundError:
        return []
    out = []
    for line in chunk.splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


class _Bridge(QObject):
    preflight_done = Signal(object, object)       # (report, start-args)


class BatchController(QObject):
    changed = Signal()

    def __init__(self, log, parent=None) -> None:
        super().__init__(parent)
        self.log = log                       # console.log(text, level)
        self.output_dir: Path | None = None
        self.jd: Path | None = None
        self.tail: jobstate.EventTail | None = None
        self.popen = None                    # only for workers THIS window started
        self.live: jobstate.Liveness | None = None
        self.state: dict | None = None
        self.busy = False                    # a start/resume is being prepared
        self.extra_args: list[str] = []      # tests: run the stub pipeline
        self._calib = None
        self._calib_age = 0
        self._last_live_state = None
        self._bridge = _Bridge()
        self._bridge.preflight_done.connect(self._continue_start)
        self._tail_timer = QTimer(self)
        self._tail_timer.setInterval(TAIL_MS)
        self._tail_timer.timeout.connect(self.poll_events)
        self._tail_timer.start()
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(TICK_MS)
        self._tick_timer.timeout.connect(self.tick)
        self._tick_timer.start()

    # ---- what the UI asks -------------------------------------------------------
    @property
    def mode(self) -> str:
        if self.busy:
            return "starting"
        if self.live is None:
            return "none"
        return self.live.state

    @property
    def stop_requested(self) -> bool:
        return bool(self.jd and jobstate.stop_requested(self.jd))

    def n_runs(self) -> int:
        return len((self.state or {}).get("runs", []))

    def counts(self) -> dict:
        return jobstate.counts(self.state) if self.state else {}

    # ---- attaching ---------------------------------------------------------------
    def attach(self, output_dir: Path | None, announce: bool = True) -> None:
        """`announce=False` when attaching to a job this window has just created:
        there is no history to replay, and "can be resumed (0/N done)" would be nonsense."""
        output_dir = Path(output_dir) if output_dir else None
        if output_dir == self.output_dir and self.jd is not None:
            return
        self.output_dir = output_dir
        self.jd = self.tail = None
        self.live = self.state = None
        self._last_live_state = None
        if output_dir is None:
            self.changed.emit()
            return
        jd = jobstate.job_dir(output_dir)
        if (jd / "job.json").exists():
            self.jd = jd
            self.state = jobstate.load_state(jd)
            self.live = jobstate.liveness(jd)
            self._last_live_state = self.live.state
            n = self.n_runs()
            if not announce:
                self.tail = jobstate.EventTail(jd, from_start=True)
                self.changed.emit()
                return
            self.log(f"— found a batch in {output_dir}: {self.live.detail} —", "info")
            for ev in last_events(jd):
                line = format_event(ev, n)
                if line:
                    self.log(*line)
            self.tail = jobstate.EventTail(jd, from_start=False)
            if self.live.state in LIVE:
                self.log("— re-attached: following the running batch —", "ok")
            elif self.live.resumable:
                self.log(f"— this batch can be resumed ({self.live.n_done}/{self.live.n_total} done) —",
                         "warn")
        self.changed.emit()

    # ---- polling -------------------------------------------------------------------
    def poll_events(self) -> None:
        if self.tail is None:
            return
        n = self.n_runs()
        for ev in self.tail.poll():
            line = format_event(ev, n)
            if line:
                self.log(*line)

    def tick(self) -> None:
        if self.popen is not None and self.popen.poll() is not None:
            self.popen = None                # reaped: never a zombie
        if self.jd is None:
            return
        self.state = jobstate.load_state(self.jd)
        self.live = jobstate.liveness(self.jd)
        if self.live.state != self._last_live_state:
            if self.live.state == "dead":
                self.log(f"✖ {self.live.detail}. Nothing is lost: click Resume to carry on.", "error")
            elif self.live.state == "stalled":
                self.log(f"⚠ {self.live.detail}", "warn")
            self._last_live_state = self.live.state
        self.changed.emit()

    def status(self) -> tuple[str, str]:
        """The line under the console title, repainted every second."""
        if self.mode == "starting":
            return "preparing the batch (checking the pipeline) …", "info"
        if self.live is None:
            return "no batch in this output folder", "info"
        st, live = self.state or {}, self.live
        n = len(st.get("runs", []))
        if live.state in LIVE:
            cur = next((r for r in st.get("runs", []) if r.get("status") == "running"), None)
            where = ""
            if cur:
                p = cur.get("progress") or {}
                frac = (f" {p['done']}/{p['total']} ({100 * p['done'] // p['total']}%)"
                        if p.get("total") else "")
                where = f"{cur['index'] + 1}/{n} {_short(cur['name'])} · {cur.get('stage') or 'starting'}{frac}"
            est = eta.estimate(st, st.get("images"), calib=self._calibration())
            text = f"{where} · {eta.describe(est)}"
            if self.stop_requested:
                text = "stopping after this run · " + text
            if live.state == "stalled":
                return f"⚠ {live.detail} · {where}", "warn"
            if live.state == "unresponsive":
                return f"⚠ {live.detail}", "warn"
            return text, "info"
        if live.state == "dead":
            return f"✖ {live.detail} — click Resume", "error"
        if live.state == "stopped":
            return f"stopped: {live.n_done}/{live.n_total} done — click Resume to carry on", "warn"
        if live.state == "halted":
            return "✖ batch halted: the pipeline output did not match the contract (see console)", "error"
        if live.state == "finished_with_failures":
            return f"finished with failures: {live.detail}", "warn"
        if live.state == "finished":
            return f"batch finished: {live.n_done}/{live.n_total} done", "ok"
        return live.detail, "info"

    def _calibration(self):
        self._calib_age += 1
        if self._calib is None or self._calib_age > 30:
            self._calib, self._calib_age = eta.Calibration.load(), 0
        return self._calib

    # ---- actions -------------------------------------------------------------------------
    def start(self, output_dir: Path, run_dirs: list[Path], settings: spec.RunSettings,
              options: dict) -> None:
        """Preflight in a fresh interpreter (off the UI thread), then start the worker."""
        if self.busy:
            return
        self.busy = True
        self.changed.emit()
        self.log(f"preparing a batch of {len(run_dirs)} runs: checking the pipeline …", "info")
        args = (Path(output_dir), list(run_dirs), settings, dict(options))

        def work():
            report = spec.preflight_fresh()
            self._bridge.preflight_done.emit(report, args)

        threading.Thread(target=work, name="batch-preflight", daemon=True).start()

    def _continue_start(self, report, args) -> None:
        self.busy = False
        output_dir, run_dirs, settings, options = args
        if not report.ok:
            for line in report.render():
                self.log(line, "error" if "FAIL" in line else "info")
            self.log("✖ the batch was NOT started: fix the pipeline mismatch above first", "error")
            self.changed.emit()
            return
        try:
            jd, self.popen = jobstate.start_job(output_dir, run_dirs, settings, options,
                                                preflight=report, extra_args=self.extra_args)
        except Exception as exc:
            self.log(f"✖ could not start the batch: {exc}", "error")
            self.changed.emit()
            return
        self.output_dir = None                   # force a fresh attach to the new job
        self.attach(output_dir, announce=False)
        self.log(f"batch started in the background (pid {self.popen.pid}); it keeps running "
                 f"if you close this window", "ok")

    def stop_after_run(self) -> None:
        if self.jd and self.mode in LIVE:
            jobstate.request_stop(self.jd)
            self.log("stop requested: the batch will stop after the current run "
                     "(no work is lost; click Resume later)", "warn")
            self.changed.emit()

    def stop_now(self) -> None:
        if self.jd and jobstate.kill_worker(self.jd):
            self.log("batch stopped now. The interrupted run will be redone on Resume "
                     "(finished frames and inference are reused).", "warn")
        self.tick()

    def resume(self, retry_failed: bool = False) -> None:
        if not self.jd:
            return
        try:
            self.popen = jobstate.resume(self.jd, retry_failed=retry_failed, extra_args=self.extra_args)
        except Exception as exc:
            self.log(f"✖ could not resume: {exc}", "error")
            return
        self.log(("retrying the failed runs" if retry_failed else "resuming the batch")
                 + f" (worker pid {self.popen.pid})", "ok")
        self.tick()


def confirm_text(runs, options: dict, settings: spec.RunSettings, output_dir: Path) -> str:
    """What the user is asked to confirm before a batch starts."""
    from . import output_tree as ot
    measured = sum(1 for r in runs if r.analysis.measured or r.analysis.droplets_only)
    days = len({r.date for r in runs if r.date})
    lines = [f"Run the full analysis on {len(runs)} run(s)"
             + (f" from {days} days" if days > 1 else "") + "?", ""]
    if options.get("images") == "all":
        lines.append("Images: EVERY frame drawn (slow, ~4 GB extra per run).")
    else:
        lines.append("Images: extreme frames only.")
    lines.append(ot.cost_note(options, len(runs)).splitlines()[0])
    if measured:
        lines.append(f"{measured} of these already have results: they will be measured again "
                     "(finished extraction + inference is reused where still valid).")
    if sys.platform == "darwin" and settings.device in (None, "cpu"):
        lines.append("This Mac runs inference on the CPU: expect it to be several times slower "
                     "than the GPU PC. The time estimate becomes real after the first run.")
    lines += ["", f"Reports go to: {output_dir}",
              "The batch runs in the background and keeps going if you close this window."]
    return "\n".join(lines)
