#!/usr/bin/env python3
"""
process_capture.py -- one .cine in, a measured run folder out.

THE single entry point for turning a capture into numbers. The GUI calls this;
the command line calls this. Nothing else should re-implement the chain.

That is a hard constraint, not a preference. From the handoff:

    "the RAM quick-look and the offline cine path must share the same
     measurement code and the same fixed intensity mapping. If they diverge,
     the lab number won't match the thesis number and the discrepancy will be
     expensive to chase."

STAGES
------
  1. cine_extract.py   .cine -> frames/16bit (measurement) + frames/8bit (what
                       the model is fed) + instances.json manifest, using the
                       PINNED 8-bit window so every run is comparable.
  2. background        per-pixel temporal median over this run's own 16-bit
                       frames. Spray is transient and medians away;
                       illumination, vignette and dust are static and survive,
                       landing at T ~ 1 instead of being detected as objects.
  3. tiled_inference   the model, 800 px tiles at native scale, never resized.
  4. measure_run       D32 (in-focus droplets only) + atomised fraction (all
                       droplets), pooled over the run, with bootstrap CIs.

FOLDER LAYOUT PRODUCED
----------------------
    <run>/shadowgraph/raw/CINE/recording_*.cine      the archival source
    <run>/shadowgraph/raw/CINE/frames/16bit/         native TIFFs
    <run>/shadowgraph/raw/CINE/frames/8bit/          PNGs, pinned window
    <run>/shadowgraph/raw/CINE/instances.json        manifest
    <run>/shadowgraph/raw/CINE/background_median.tiff
    <run>/shadowgraph/analysis/predictions.json
    <run>/shadowgraph/analysis/measurement_<thr>/    csv + summary + images

Usage:
    python process_capture.py <cine> --run-dir <run folder>
    python process_capture.py <cine> --run-dir <run folder> --stride 10 --images
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "src"))

DEFAULT_SCORE_THRESH = 0.30
DEFAULT_STRIDE = 10
BG_FRAMES = 40


def _run(cmd, log):
    """Run a stage as a subprocess, streaming its output through `log`.

    Subprocess rather than import: it keeps detectron2's heavy, CUDA-touching
    import out of the caller's process (the GUI especially), and it means each
    stage's CLI stays the one interface, so a stage cannot behave differently
    depending on who called it.
    """
    log(f"$ {' '.join(str(c) for c in cmd)}")
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in p.stdout:
        log(line.rstrip())
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"stage failed ({p.returncode}): {' '.join(str(c) for c in cmd)}")


def build_background(frames_16bit: Path, out_path: Path, n_sample: int, log):
    """Per-pixel temporal median. Reuses extract_candidates' implementation so
    the production background is bit-identical to the one the library and the
    benchmark were built against."""
    from _fsutil import list_files
    from extract_candidates import build_temporal_background

    if out_path.exists():
        log(f"background: reusing existing {out_path.name}")
        return out_path
    frames = list_files(frames_16bit, "*.tiff")
    if not frames:
        raise RuntimeError(f"no 16-bit frames in {frames_16bit}")
    log(f"background: temporal median over up to {n_sample} of {len(frames)} frames")
    build_temporal_background(frames, n_sample, out_path)
    return out_path


def process_capture(cine: Path, run_dir: Path, *, stride=DEFAULT_STRIDE,
                    score_thresh=DEFAULT_SCORE_THRESH, device=None,
                    model_dir: Path = None, images=True, ci_stride=None,
                    bg_frames=BG_FRAMES, limit=None, log=print) -> dict:
    """
    Run the whole chain. Returns measure_run's summary dict.

    `log` takes one string; the GUI passes something that appends to its log
    panel, the CLI passes print.
    """
    t0 = time.time()
    cine = Path(cine)
    run_dir = Path(run_dir)
    if not cine.exists():
        raise FileNotFoundError(f"no such .cine: {cine}")

    cine_dir = run_dir / "shadowgraph" / "raw" / "CINE"
    analysis = run_dir / "shadowgraph" / "analysis"
    cine_dir.mkdir(parents=True, exist_ok=True)
    analysis.mkdir(parents=True, exist_ok=True)

    # The .cine is the archival source of truth, so it lives inside the run
    # folder. Copy it in if it was picked from elsewhere (the Test Pipeline
    # path); a real capture will already have written it here.
    local_cine = cine_dir / cine.name
    if cine.resolve() != local_cine.resolve():
        log(f"copying {cine.name} into the run folder ...")
        shutil.copy2(cine, local_cine)

    # ---- 1. frames -------------------------------------------------------
    log("\n=== 1/4  extracting frames ===")
    cmd = [sys.executable, HERE / "cine_extract.py", local_cine,
           "--run-name", "CINE", "--output-root", cine_dir.parent,
           "--stride", stride, "--overwrite"]
    if limit:
        cmd += ["--limit", limit]
    _run(cmd, log)

    frames_16 = cine_dir / "frames" / "16bit"
    frames_8 = cine_dir / "frames" / "8bit"
    n_frames = len(list(frames_8.glob("*.png")))
    if n_frames == 0:
        raise RuntimeError(f"extraction produced no frames in {frames_8}")

    # ---- 2. background ---------------------------------------------------
    log("\n=== 2/4  background ===")
    bg_path = build_background(frames_16, cine_dir / "background_median.tiff",
                               bg_frames, log)

    # ---- 3. inference ----------------------------------------------------
    log(f"\n=== 3/4  inference on {n_frames} frames ===")
    preds = analysis / "predictions.json"
    cmd = [sys.executable, HERE / "tiled_inference.py", "--all",
           "--root", run_dir, "--val-dir", "shadowgraph/raw/CINE",
           "--out", preds]
    if device:
        cmd += ["--device", device]
    if model_dir:
        cmd += ["--model-dir", model_dir]
    _run(cmd, log)

    # ---- 4. measurement --------------------------------------------------
    log("\n=== 4/4  measurement ===")
    out_dir = analysis / f"measurement_{score_thresh:.2f}"
    cmd = [sys.executable, HERE / "measure_run.py", "--pred", preds,
           "--root", run_dir, "--val-dir", "shadowgraph/raw/CINE",
           "--background", bg_path,
           "--sixteen-bit-dir", frames_16,
           "--score-thresh", score_thresh,
           "--out-dir", out_dir]
    if images:
        cmd += ["--images"]
    if ci_stride:
        cmd += ["--ci-stride", ci_stride]
    _run(cmd, log)

    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    summary["_elapsed_total_s"] = round(time.time() - t0, 1)
    summary["_run_dir"] = str(run_dir)
    summary["_frames"] = n_frames
    summary["_measurement_dir"] = str(out_dir)

    log(f"\n=== done in {summary['_elapsed_total_s']:.0f} s ===")
    log(f"  D32 (in-focus)    {summary['d32_in_focus_um']} um   "
        f"95% CI {summary['d32_ci95']}")
    log(f"  atomised fraction {summary['atomised_pct']} %   "
        f"95% CI {summary['atomised_ci95']}")
    ext = summary.get("d32_extreme_frames") or {}
    if ext.get("lowest"):
        log(f"  lowest-D32 frame  {ext['lowest']['frame']}  "
            f"({ext['lowest']['d32_um']} um)")
    return summary


def next_trial_dir(base: Path) -> Path:
    """<base>/YYYY/MM/DD/Trial_n, n being the next free number for today."""
    from datetime import datetime
    now = datetime.now()
    day = base / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    day.mkdir(parents=True, exist_ok=True)
    n = 1
    while (day / f"Trial_{n}").exists():
        n += 1
    return day / f"Trial_{n}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cine", type=Path)
    ap.add_argument("--run-dir", type=Path, default=None,
                    help="run folder to build. Default: a new Trial_n under "
                         "<LaCie>/Experiments/YYYY/MM/DD/")
    ap.add_argument("--stride", type=int, default=DEFAULT_STRIDE,
                    help=f"keep every Nth frame from the cine (default {DEFAULT_STRIDE}; "
                         f"at 500 fps that is one decorrelation time apart)")
    ap.add_argument("--score-thresh", type=float, default=DEFAULT_SCORE_THRESH)
    ap.add_argument("--ci-stride", type=int, default=None)
    ap.add_argument("--device", default=None, help="cuda / cpu. Default: auto-detect")
    ap.add_argument("--model-dir", type=Path, default=None)
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N frames -- use for a quick smoke test")
    args = ap.parse_args()

    run_dir = args.run_dir
    if run_dir is None:
        from config_loader import find_lacie_drive
        drive = find_lacie_drive()
        if drive is None:
            sys.exit("LaCie drive not found. Pass --run-dir explicitly.")
        run_dir = next_trial_dir(Path(drive) / "Experiments")
        print(f"run folder: {run_dir}")

    process_capture(args.cine, run_dir, stride=args.stride,
                    score_thresh=args.score_thresh, device=args.device,
                    model_dir=args.model_dir, images=not args.no_images,
                    ci_stride=args.ci_stride, limit=args.limit)


if __name__ == "__main__":
    main()
