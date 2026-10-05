"""progress.py -- turn the pipeline's stdout into stage + progress events.

BEST-EFFORT by design. stdout text is not part of the pipeline contract
(pipeline_spec.py says so): if a format changes, a line simply stops matching,
progress for that stage degrades to elapsed time only, and the run carries on.
Nothing here can fail a run.

Every pattern below was taken from a REAL log --
2026/10/01/104852_.../shadowgraph/analysis/batch_log.txt -- not from memory:

    === 1/4  extracting frames ===                         process_capture banner
      extracting 497 frames at stride 10 (12.50 ms apart)  cine_extract: the total
        120/497 (24%)   13.1 frames/s   ETA 28s             cine_extract progress
        [extract frames took 3m 10s]                        process_capture stage end
    === 3/4  inference on 497 frames ===
    device: cuda  (auto-detected)                           tiled_inference
    frame_0000_n-1   2560x1600   24 tiles   0.80s  det ...  one line per frame
              frame_0000_n-1  focus   35  oof   20 ...      measure_run, one per frame
      25/497   12.3s  (0.49 s/frame)                        classical_liquid, every 25
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

BANNERS = (
    (re.compile(r"^=== 1/4\s+extracting frames ==="), "extract"),
    (re.compile(r"^=== 2/4\s+background ==="), "background"),
    (re.compile(r"^=== 3/4\s+inference on (\d+) frames ==="), "inference"),
    (re.compile(r"^=== 4/4\s+measurement ==="), "measurement"),
)
REUSE_RE = re.compile(r"^=== reusing the existing stride-\d+ analysis \((\d+) frames\)")
STAGE_END_RE = re.compile(r"^\[(.+?) took (.+)\]$")
TOTAL_RE = re.compile(r"^extracting (\d+) frames at stride")
DEVICE_RE = re.compile(r"^device:\s+(\w+)")
EXTRACT_RE = re.compile(r"^(\d+)/(\d+) \(\d+%\)")
INFER_FRAME_RE = re.compile(r"^frame_\d+_n-?\d+\s+\d+x\d+\s+\d+ tiles")
MEASURE_FRAME_RE = re.compile(r"^frame_\d+_n-?\d+\s+focus\s+\d+")
CLASSICAL_RE = re.compile(r"^(\d+)/(\d+)\s+[\d.]+s\s+\(")

# process_capture's timing names -> our stage ids (pipeline_spec.STAGES)
TIMING_TO_STAGE = {"copy cine": "copy_cine", "extract frames": "extract",
                   "background": "background", "inference": "inference",
                   "measurement": "measurement"}


@dataclass
class Tracker:
    """Feed it every stdout line of one run; it returns events and keeps the
    current stage, frame progress and frame count up to date."""
    every: int = 10                    # progress event every N frames ...
    min_interval_s: float = 2.0        # ... or at least this often while frames arrive
    stage: str | None = None
    done: int = 0
    total: int | None = None
    frames: int | None = None
    device: str | None = None
    reused: bool = False
    _last_emit: float = 0.0
    _last_progress_t: float | None = None
    interval_s: float | None = None    # smoothed seconds between frames (stall detection)
    clock: callable = field(default=time.monotonic, repr=False)

    def begin(self, stage: str, total: int | None = None) -> dict:
        """Start a stage the worker knows about directly (classical)."""
        self.stage, self.done = stage, 0
        self.total = total if total is not None else self.frames
        self._last_progress_t = None
        return {"k": "stage_start", "stage": stage, "total": self.total}

    def feed(self, raw: str) -> list[dict]:
        events: list[dict] = []
        for line in str(raw).splitlines() or [""]:
            events += self._one(line.strip())
        return events

    def _one(self, s: str) -> list[dict]:
        if not s:
            return []
        for rx, stage in BANNERS:
            m = rx.match(s)
            if m:
                if stage == "inference":
                    self.frames = int(m.group(1))
                return [self.begin(stage, self.frames if stage in ("inference", "measurement")
                                   else None), {"k": "log", "line": s}]
        m = REUSE_RE.match(s)
        if m:
            self.reused, self.frames = True, int(m.group(1))
            return [{"k": "log", "line": s}]
        m = STAGE_END_RE.match(s)
        if m:
            stage = TIMING_TO_STAGE.get(m.group(1), m.group(1))
            return [{"k": "stage_end", "stage": stage, "took": m.group(2)}, {"k": "log", "line": s}]
        m = TOTAL_RE.match(s)
        if m:
            self.frames = self.total = int(m.group(1))
            return [{"k": "log", "line": s}]
        m = DEVICE_RE.match(s)
        if m:
            self.device = m.group(1)
            return [{"k": "log", "line": s}]

        # per-frame / counter lines: progress, never forwarded as log (they would
        # bury everything else -- 2 x 497 lines per run)
        if self.stage == "extract":
            m = EXTRACT_RE.match(s)
            if m:
                return self._progress(int(m.group(1)), int(m.group(2)))
        elif self.stage == "inference" and INFER_FRAME_RE.match(s):
            return self._progress(self.done + 1, self.total)
        elif self.stage == "measurement" and MEASURE_FRAME_RE.match(s):
            return self._progress(self.done + 1, self.total)
        elif self.stage == "classical":
            m = CLASSICAL_RE.match(s)
            if m:
                return self._progress(int(m.group(1)), int(m.group(2)))
        return [{"k": "log", "line": s}]

    def _progress(self, done: int, total: int | None) -> list[dict]:
        now = self.clock()
        if self._last_progress_t is not None and done > self.done:
            dt = (now - self._last_progress_t) / max(1, done - self.done)
            self.interval_s = dt if self.interval_s is None else 0.8 * self.interval_s + 0.2 * dt
        self._last_progress_t = now
        self.done, self.total = done, total if total else self.total
        last = self.total is not None and done >= self.total
        if done == 1 or last or done % self.every == 0 or now - self._last_emit >= self.min_interval_s:
            self._last_emit = now
            return [{"k": "progress", "stage": self.stage, "done": done, "total": self.total}]
        return []
