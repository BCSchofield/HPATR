"""eta.py -- time remaining, learned from the runs that have actually finished.

Pure functions over the job state: the worker calls them after each stage, and
the UI calls them every second, so both show the same number.

THE MODEL. Each stage costs seconds-per-frame. Before anything has run on this
machine the only numbers available are PRIORS from another machine (below,
with sources). As soon as a stage finishes in this job, its measured rate
replaces the prior for that stage -- this is what the user asked for: "update
based on how long the previous runs that session have taken". Rates are also
remembered per machine across sessions (~/.hpatr/eta_calibration.json), so a
second batch on the same computer starts from its own history, not the priors.

Keys matter: inference speed depends on the DEVICE (cuda vs cpu differ by an
order of magnitude), and measurement/classical depend on the IMAGES mode
("every frame" draws ~1,000 PNGs). So rates are keyed (host, stage, device)
for inference and (host, stage, images) for measurement/classical.

Within the current stage, live frame progress is used once it is meaningful
(>= 10% done): remaining = elapsed * (1 - f) / f. That is what makes the number
move smoothly instead of jumping at stage boundaries.

The range shown is the spread of MEASURED rates (min..max), not an invented
confidence interval. With priors only, it is the range recorded on the source
machine, and the estimate says plainly that it is not from this machine.
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import fsops

STAGE_ORDER = ("extract", "background", "inference", "measurement", "classical")
REF_FRAMES = 497

# ---- PRIORS: seconds per 497-frame run, PER OPERATING SYSTEM ---------------------
# Used only until THIS machine has measured a stage (then its own rates take over,
# and are remembered in the calibration file). Keyed by OS so a fresh machine starts
# from the right kind of computer: GPU inference and CPU inference differ ~6x.
# (lo, typical, hi). `background` is a FIXED cost (a median over up to 40 frames,
# however long the run), so its figures are seconds per run, not per 497 frames.
_WINDOWS = {
    # docs/archive/HANDOFF_real_data_pipeline_LEGACY.md timing table: nine L9 runs on the home PC
    # (C:\Users\BenSc, CUDA), --images all. Classical extremes: batch_runs.py:91-95.
    ("extract", None): (190, 215, 226),
    ("background", None): (2, 3, 7),
    ("inference", None): (411, 950, 1559),       # load-dependent: gas + silicone flow
    ("measurement", "all"): (316, 335, 361),
    # NOT measured: derived from the handoff's estimate that drawing all images is
    # ~70-80% of the stage, i.e. 335 s x 0.2-0.3.
    ("measurement", "extremes"): (60, 85, 110),
    ("classical", "all"): (420, 560, 699),
    ("classical", "extremes"): (35, 41, 60),
}
_INFER_SPREAD = (411 / 950, 1559 / 950)          # how much inference varies with load (CUDA)
_DARWIN = {
    # MEASURED 2026-10-05: two real sandbox runs on a MacBook Air, CPU inference, first
    # 40 frames, one condition (3000 sccm / 300 rpm / 4000 sps -- the LIGHTEST spray, so
    # heavier conditions will run slower). s/frame: extract 0.235-0.2375, inference
    # 5.80-5.83, measurement 0.1075-0.115, classical 0.042-0.044; background 1.7-2.6 s.
    ("extract", None): (117, 117, 118),
    ("background", None): (2, 2, 3),
    # one light condition measured: widen by the load spread recorded on CUDA
    ("inference", None): (round(2892 * _INFER_SPREAD[0]), 2892, round(2892 * _INFER_SPREAD[1])),
    ("measurement", "extremes"): (53, 55, 57),
    ("classical", "extremes"): (21, 21, 22),
    # NOT measured on macOS: "every frame" taken from the Windows figures
    ("measurement", "all"): _WINDOWS[("measurement", "all")],
    ("classical", "all"): _WINDOWS[("classical", "all")],
}
PRIORS_BY_OS = {"Windows": _WINDOWS, "Darwin": _DARWIN}
PRIOR_SOURCE_BY_OS = {
    "Windows": "the GPU PC's figures (handoff timings, CUDA)",
    "Darwin": "a MacBook Air's measured figures (CPU, one light condition)",
}
FIXED_STAGES = frozenset({"background"})          # seconds per run, not per frame


def priors_for(os_name: str) -> dict:
    return PRIORS_BY_OS.get(os_name, _WINDOWS)


def prior_source(os_name: str) -> str:
    return PRIOR_SOURCE_BY_OS.get(os_name, PRIOR_SOURCE_BY_OS["Windows"])


def _prior_key(stage: str, images: str | None) -> tuple:
    return (stage, images if stage in ("measurement", "classical") else None)


def host_id() -> str:
    return f"{platform.node() or 'unknown'}|{platform.system()}"


# ---- calibration memory -------------------------------------------------------

def calibration_path() -> Path:
    override = os.environ.get("TAGUCHI_UI_CALIBRATION")
    return Path(override) if override else Path.home() / ".hpatr" / "eta_calibration.json"


def obs_key(host: str, stage: str, device: str | None, images: str | None) -> str:
    if stage in FIXED_STAGES:
        return f"{host}|{stage}_s"          # per-run seconds (the "_s" keeps old per-frame data apart)
    if stage == "inference":
        return f"{host}|inference|{device or 'unknown'}"
    if stage in ("measurement", "classical"):
        return f"{host}|{stage}|{images or 'unknown'}"
    return f"{host}|{stage}"


@dataclass
class Calibration:
    """Per-machine seconds-per-frame observations, last KEEP per key."""
    path: Path = field(default_factory=calibration_path)
    data: dict = field(default_factory=dict)
    KEEP = 30

    @classmethod
    def load(cls, path: Path | None = None) -> "Calibration":
        p = path or calibration_path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")).get("rates", {})
        except (OSError, ValueError, AttributeError):
            data = {}
        return cls(path=p, data=data)

    def add(self, key: str, s_per_frame: float) -> None:
        if s_per_frame > 0:
            self.data.setdefault(key, []).append(round(s_per_frame, 5))
            self.data[key] = self.data[key][-self.KEEP:]

    def rates(self, key: str) -> list[float]:
        return list(self.data.get(key, []))

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "rates": self.data}, indent=1),
                           encoding="utf-8")
            fsops.replace(tmp, self.path)
        except OSError:
            pass                       # a lost calibration file only costs accuracy


def observations_from_run(run: dict, host: str, images: str | None) -> dict[str, float]:
    """{obs_key: rate} for the stages a finished run measured: seconds per frame,
    or seconds per run for the fixed-cost stages."""
    frames = run.get("frames")
    if not frames:
        return {}
    out = {}
    for stage, secs in (run.get("seconds") or {}).items():
        if stage in STAGE_ORDER and secs and secs > 0:
            out[obs_key(host, stage, run.get("device"), images)] = (
                secs if stage in FIXED_STAGES else secs / frames)
    return out


# ---- estimate -------------------------------------------------------------------

@dataclass
class Estimate:
    run_remaining_s: float | None
    batch_remaining_s: float | None
    low_s: float | None
    high_s: float | None
    measured: bool                  # every stage still to come has a rate from THIS machine
    n_measured_runs: int            # finished runs in this job that fed the rates
    note: str = ""


def _rates(stage: str, images: str | None, device: str | None, host: str,
           job_obs: dict[str, list[float]], calib: Calibration | None):
    key = obs_key(host, stage, device, images)
    seen = list(job_obs.get(key, [])) + (calib.rates(key) if calib else [])
    if seen:
        return statistics.median(seen), min(seen), max(seen), True
    lo, typ, hi = priors_for(host.split("|")[-1])[_prior_key(stage, images)]
    if stage in FIXED_STAGES:
        return typ, lo, hi, False
    return typ / REF_FRAMES, lo / REF_FRAMES, hi / REF_FRAMES, False


def estimate(state: dict, images: str | None, *, now: float | None = None,
             host: str | None = None, calib: Calibration | None = None) -> Estimate:
    now = time.time() if now is None else now
    host = host or host_id()
    runs = state.get("runs", [])
    done = [r for r in runs if r.get("status") == "done"]
    current = next((r for r in runs if r.get("status") == "running"), None)
    pending = [r for r in runs if r.get("status") == "pending"]

    job_obs: dict[str, list[float]] = {}
    for r in done:
        for k, v in observations_from_run(r, host, images).items():
            job_obs.setdefault(k, []).append(v)
    device = next((r.get("device") for r in reversed(runs) if r.get("device")), None)
    if device is None and calib is not None:
        # nothing has reported its device yet: if this machine has only ever run
        # inference on ONE device, that is where it will run again
        seen = {k.rsplit("|", 1)[-1] for k in calib.data if k.startswith(f"{host}|inference|")}
        device = seen.pop() if len(seen) == 1 else None
    known_frames = [r["frames"] for r in runs if r.get("frames")]
    typ_frames = statistics.median(known_frames) if known_frames else REF_FRAMES

    rate = {s: _rates(s, images, device, host, job_obs, calib) for s in STAGE_ORDER}
    unmeasured: set[str] = set()             # stages still on priors, named in the note

    def run_cost(frames: float, stages) -> tuple[float, float, float]:
        t = lo = hi = 0.0
        for s in stages:
            r, rlo, rhi, measured = rate[s]
            if not measured:
                unmeasured.add(s)
            n = 1 if s in FIXED_STAGES else frames
            t, lo, hi = t + r * n, lo + rlo * n, hi + rhi * n
        return t, lo, hi

    cur = (0.0, 0.0, 0.0)
    if current is not None:
        frames = current.get("frames") or typ_frames
        stage = current.get("stage")
        later = STAGE_ORDER[STAGE_ORDER.index(stage) + 1:] if stage in STAGE_ORDER else STAGE_ORDER
        t, lo, hi = run_cost(frames, later)
        if stage in STAGE_ORDER:
            r, rlo, rhi, measured = rate[stage]
            if not measured:
                unmeasured.add(stage)
            expected = r * (1 if stage in FIXED_STAGES else frames)
            elapsed = max(0.0, now - (current.get("stage_started") or now))
            prog = current.get("progress") or {}
            f = (prog.get("done", 0) / prog["total"]) if prog.get("total") else 0.0
            rem = elapsed * (1 - f) / f if f >= 0.1 and elapsed > 0 else max(expected - elapsed,
                                                                              0.1 * expected)
            t, lo, hi = t + rem, lo + rem * (rlo / r), hi + rem * (rhi / r)
        cur = (t, lo, hi)

    # each pending run at its OWN frame count where known (e.g. a re-run), else the typical
    batch, low, high = cur
    for r in pending:
        t, lo, hi = run_cost(r.get("frames") or typ_frames, STAGE_ORDER)
        batch, low, high = batch + t, low + lo, high + hi

    if current is None and not pending:
        return Estimate(0.0, 0.0, 0.0, 0.0, True, len(done), "nothing left to run")
    measured_from = (f"{len(done)} finished run{'s' if len(done) != 1 else ''} on this machine"
                     if done else "this machine's earlier batches")
    if not unmeasured:
        note = f"from {measured_from}"
    else:
        named = ", ".join(s for s in STAGE_ORDER if s in unmeasured)
        source = prior_source(host.split("|")[-1])
        if len(unmeasured) == len(STAGE_ORDER):
            note = (f"not yet measured on this machine: using {source}, which can be well "
                    f"off for a different computer or a heavier spray")
        else:
            note = f"from {measured_from}; {named} not yet measured here (using {source})"
    all_measured = not unmeasured
    return Estimate(cur[0] if current is not None else None, batch, low, high,
                    all_measured, len(done), note)


def fmt(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(round(max(0.0, seconds)))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def describe(est: Estimate, now: float | None = None) -> str:
    """One status line, e.g.
    'batch ETA 7h 12m (6h 40m-8h 05m), done ~21:40 -- from 5 finished runs on this machine'"""
    if est.batch_remaining_s is None:
        return "ETA unknown"
    if est.batch_remaining_s == 0:
        return "nothing left to run"
    now = time.time() if now is None else now
    finish = time.strftime("%H:%M", time.localtime(now + est.batch_remaining_s))
    # a range narrower than 30 s (or 5%) is noise, not information
    rng = (f" ({fmt(est.low_s)}–{fmt(est.high_s)})"
           if est.low_s is not None and est.high_s
           and est.high_s - est.low_s >= max(30.0, 0.05 * est.high_s) else "")
    return f"batch ETA {fmt(est.batch_remaining_s)}{rng}, done ~{finish} — {est.note}"
