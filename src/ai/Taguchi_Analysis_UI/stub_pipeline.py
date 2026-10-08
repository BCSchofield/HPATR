"""stub_pipeline.py -- a fake pipeline for testing the batch machinery in seconds.

It stands in for process_capture.process_capture() and process_capture._run()
(worker --impl stub). It prints the REAL log formats (copied from a real
batch_log.txt, see progress.py), writes exactly the artefacts pipeline_spec
promises, and returns the same summary keys. That lets detach / kill -9 /
resume / stall / failure be tested without a 14 GiB cine or a GPU.

SAFETY: it writes fake results INTO run folders, so it refuses to touch any
folder outside $TAGUCHI_UI_SANDBOX_ROOT -- and refuses to run at all if that is
not set. It can never overwrite a real run's analysis.

Test hooks (worker CLI flags, keyed by run folder name):
    --stub-fail NAME     raise during measurement           -> run "failed"
    --stub-hang NAME     go silent for --stub-hang-s seconds during inference (stall)
    --stub-omit ID@NAME  do not write output ID              -> "contract_violation"
    --stub-child NAME    start a long-lived child process during inference and wait
                         on it, as a real stage subprocess would (orphan test)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import pipeline_spec as spec

SANDBOX_ENV = "TAGUCHI_UI_SANDBOX_ROOT"
CHILD_MARKER = "Taguchi_Analysis_UI-stub-child"     # procs.OURS matches this


def check_sandbox(run_dir: Path) -> None:
    root = os.environ.get(SANDBOX_ENV)
    if not root:
        raise RuntimeError(f"the stub pipeline only runs inside a sandbox: set {SANDBOX_ENV}")
    run_dir, root = Path(run_dir).resolve(), Path(root).resolve()
    if root != run_dir and root not in run_dir.parents:
        raise RuntimeError(f"refusing to write fake results into {run_dir}: "
                           f"it is outside the sandbox {root}")


@dataclass
class Stub:
    frames: int = 6
    stage_s: float = 0.01           # sleep per frame (keeps tests fast)
    fail: set = field(default_factory=set)
    hang: set = field(default_factory=set)
    hang_s: float = 60.0
    omit: dict = field(default_factory=dict)      # run name -> {output id}
    child: set = field(default_factory=set)
    child_pid_file: Path | None = None

    # ---- process_capture.process_capture -------------------------------------------
    def process_capture(self, cine, run_dir, *, stride=10, score_thresh=0.30, device=None,
                        model_dir=None, images="extremes", ci_stride=None, bg_frames=40,
                        limit=None, reuse=False, log=print, sharpness_rule=True) -> dict:
        run_dir = Path(run_dir)
        check_sandbox(run_dir)
        name = run_dir.name
        n = min(self.frames, limit) if limit else self.frames
        raw = run_dir / "shadowgraph" / "raw"
        an = run_dir / "shadowgraph" / "analysis"
        stems = [f"frame_{i:04d}_n{i * stride - 1}" for i in range(n)]   # real: n-1, n9, n19 ...
        omit = self.omit.get(name, set())
        stage_s, t0 = {}, time.time()

        # mirror the checks of the real process_capture.can_reuse() that a stub can: same
        # stride, not a --limit extraction, complete frame count, predictions present
        try:
            prev = json.loads((raw / "extraction_metadata.json").read_text())
        except (OSError, ValueError):
            prev = {}
        reusing = bool(reuse and prev.get("stride") == stride and not prev.get("limited")
                       and prev.get("frame_count") == n and (an / "predictions.json").exists())
        if reusing:
            log(f"\n=== reusing the existing stride-{stride} analysis ({n} frames): "
                f"extraction, background and inference skipped ===")
        else:
            # ---- 1/4 extract -------------------------------------------------------
            log("\n=== 1/4  extracting frames ===")
            log(f"  extracting {n} frames at stride {stride} (12.50 ms apart)")
            t = time.time()
            for d in ("8bit", "16bit"):
                (raw / "frames" / d).mkdir(parents=True, exist_ok=True)
                for old_frame in (raw / "frames" / d).glob("frame_*"):
                    old_frame.unlink()          # cine_extract.py --overwrite clears old frames
            for k, s in enumerate(stems, 1):
                self._touch(raw / "frames" / "8bit" / f"{s}.png", "frames_8bit", omit)
                self._touch(raw / "frames" / "16bit" / f"{s}.tiff", "frames_16bit", omit)
                log(f"    {k}/{n} ({k * 100 // n}%)   10.0 frames/s   ETA 0s")
                time.sleep(self.stage_s)
            meta = {"stride": stride, "frame_count": n, "frame_rate_fps": 390.0,
                    "limited": bool(limit), "stub": True}
            if "extraction_metadata" not in omit:
                (raw / "extraction_metadata.json").write_text(json.dumps(meta))
            for f, oid in (("instances.json", "instances_json"), ("frame_runs.json", "frame_runs_json")):
                self._touch(raw / f, oid, omit)
            stage_s["extract frames"] = round(time.time() - t, 3)
            log(f"    [extract frames took {stage_s['extract frames']:.0f}s]")

            # ---- 2/4 background -----------------------------------------------------
            log("\n=== 2/4  background ===")
            t = time.time()
            self._touch(raw / "background_median.tiff", "background", omit)
            stage_s["background"] = round(time.time() - t, 3)
            log(f"    [background took 0s]")

            # ---- 3/4 inference ------------------------------------------------------
            log(f"\n=== 3/4  inference on {n} frames ===")
            log("device: cpu  (auto-detected)")
            t = time.time()
            if name in self.child:
                self._run_child()
            if name in self.hang:
                time.sleep(self.hang_s)                  # silent: no output, as if stuck
            an.mkdir(parents=True, exist_ok=True)
            for s in stems:
                log(f"{s}         2560x1600   24 tiles     0.10s  det   12 (>=0.30:  9)  "
                    f"truncated   0   {{'droplet': 9, 'filament': 2, 'blob': 1}}")
                time.sleep(self.stage_s)
            self._touch(an / "predictions.json", "predictions", omit)
            stage_s["inference"] = round(time.time() - t, 3)
            log(f"    [inference took 0s]")

        # ---- 4/4 measurement ------------------------------------------------------------
        log("\n=== 4/4  measurement ===")
        t = time.time()
        out = spec.meas_dir(run_dir, score_thresh)
        out.mkdir(parents=True, exist_ok=True)
        for s in stems:
            log(f"          {s}  focus   35  oof   20  fil   3  blob  1   D32   90.0   atom  8.0%")
            time.sleep(self.stage_s)
            if name in self.fail:
                raise RuntimeError("stage failed (1): stub measurement failure (requested)")
        for f, oid in (("droplet_sizes.csv", "droplet_sizes"), ("object_areas.csv", "object_areas"),
                       ("per_frame.csv", "per_frame"), ("size_histograms.png", "meas_hist")):
            self._touch(out / f, oid, omit)
        drawn = stems if images == "all" else stems[:3] if images == "extremes" else []
        for s in drawn:
            self._touch(out / f"{s}.png", "meas_all" if images == "all" else "meas_extremes", omit)
        summary = {"d32_in_focus_um": 90.0, "d32_ci95": [88.0, 92.0], "atomised_pct": 8.0,
                   "atomised_ci95": [7.0, 9.0],
                   "provenance": {"sizer_version": "2.2.0" if sharpness_rule else "2.1.0", "stub": True}}
        if "meas_summary" not in omit:
            (out / "summary.json").write_text(json.dumps(summary))
        stage_s["measurement"] = round(time.time() - t, 3)
        log(f"    [measurement took 0s]")

        summary.update({"_elapsed_total_s": round(time.time() - t0, 3), "_run_dir": str(run_dir),
                        "_frames": n, "_measurement_dir": str(out), "_stage_seconds": stage_s,
                        "_stride": stride, "_reused_analysis": reusing})
        return summary

    # ---- process_capture._run (used for classical_liquid) ---------------------------
    def run(self, cmd, log) -> None:
        cmd = [str(c) for c in cmd]
        get = lambda flag: cmd[cmd.index(flag) + 1] if flag in cmd else None
        root, out_dir = Path(get("--root")), Path(get("--out-dir"))
        check_sandbox(root)
        images = get("--images-mode")
        omit = self.omit.get(root.name, set())
        stems = sorted(p.stem for p in (root / "shadowgraph" / "raw" / "frames" / "8bit").glob("frame_*.png"))
        log(f"$ {' '.join(cmd)}")
        out_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        for k, _ in enumerate(stems, 1):
            time.sleep(self.stage_s)
            el = time.time() - t0
            log(f"  {k:4}/{len(stems)}  {el:5.1f}s  ({el / k:.2f} s/frame)")
        for f, oid in (("classical_per_frame.csv", "classical_per_frame"),
                       ("classical_components.csv", "classical_components"),
                       ("size_histograms.png", "clas_hist")):
            self._touch(out_dir / f, oid, omit)
        if images in ("extremes", "all"):
            d = out_dir / ("extreme_images" if images == "extremes" else "images")
            d.mkdir(exist_ok=True)
            for s in (stems[:2] if images == "extremes" else stems):
                self._touch(d / f"{s}.png", "clas_extremes" if images == "extremes" else "clas_all", omit)
        if "classical_summary" not in omit:
            (out_dir / "classical_summary.json").write_text(json.dumps(
                {"atomised_pct_pooled": 8.1, "provenance": {"stub": True}}))

    # ---- helpers ---------------------------------------------------------------------
    @staticmethod
    def _touch(path: Path, output_id: str, omit: set) -> None:
        if output_id not in omit:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"stub")

    def _run_child(self) -> None:
        """Start and WAIT on a long-lived child, as process_capture._run does for a
        real stage. Killing the worker now leaves this child orphaned."""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", CHILD_MARKER])
        if self.child_pid_file:
            Path(self.child_pid_file).write_text(str(p.pid))
        p.wait()
