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

FOLDER LAYOUT PRODUCED  (changed 2026-09-28 -- see the note in process_capture)
----------------------
    <run>/shadowgraph/raw/CINE/recording_*.cine      the archival source, ALONE
    <run>/shadowgraph/raw/frames/16bit/              native TIFFs
    <run>/shadowgraph/raw/frames/8bit/               PNGs, pinned window
    <run>/shadowgraph/raw/instances.json             manifest (an INPUT)
    <run>/shadowgraph/raw/background_median.tiff
    <run>/shadowgraph/analysis/predictions.json
    <run>/shadowgraph/analysis/measurement_<thr>/    csv + summary + images

`raw/` is what gets passed as --val-dir. Runs made before this date have
frames and instances.json one level deeper, inside CINE/.

Usage:
    python process_capture.py <cine> --run-dir <run folder>
    python process_capture.py <cine> --run-dir <run folder> --stride 10 --images
"""

import argparse
import json
import os
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
# Liquid crosses the 20.5 mm field of view at ~1 m/s, so frames closer than
# this share droplets. Sets the automatic --ci-stride; see auto_ci_stride().
DECORRELATION_S = 0.0205


def _fmt_dur(seconds) -> str:
    """Human-readable duration: '45s', '2m 05s', '1h 12m'."""
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def _run(cmd, log):
    """Run a stage as a subprocess, streaming its output through `log`.

    Subprocess rather than import: it keeps detectron2's heavy, CUDA-touching
    import out of the caller's process (the GUI especially), and it means each
    stage's CLI stays the one interface, so a stage cannot behave differently
    depending on who called it.
    """
    log(f"$ {' '.join(str(c) for c in cmd)}")
    # PYTHONUNBUFFERED is the reason progress appears at all. A child writing to
    # a PIPE block-buffers its stdout in ~8 KB chunks, so a stage that prints a
    # short progress line every 25 frames emits nothing for minutes and then a
    # burst -- indistinguishable from being hung. bufsize=1 below only affects
    # OUR side of the pipe; it cannot unbuffer the child.
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    for line in p.stdout:
        log(line.rstrip())
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"stage failed ({p.returncode}): {' '.join(str(c) for c in cmd)}")


def previous_analysis(run_dir: Path):
    """The extraction metadata of an earlier analysis in this run folder, or
    None. Carries stride, frame_count, total_frames_in_cine, frame_rate_fps
    and extracted_utc."""
    meta = Path(run_dir) / "shadowgraph" / "raw" / "extraction_metadata.json"
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _newest_weights_mtime(model_dir: Path = None):
    """mtime of the newest .pth the inference stage would load, or None. Kept
    import-light (no torch) so the GUI can call it on the main thread."""
    if model_dir is None:
        from config_loader import find_lacie_drive
        drive = find_lacie_drive()
        if drive is None:
            return None
        model_dir = Path(drive) / "Experiments" / "AI" / "Eden"
    times = [p.stat().st_mtime for p in Path(model_dir).glob("*.pth")]
    return max(times) if times else None


def can_reuse(run_dir: Path, stride: int, model_dir: Path = None) -> bool:
    """True when this run folder already holds a complete analysis at `stride`
    that the current model would reproduce, so stages 1-3 can be skipped.

    Every check guards a way reuse could silently give a different answer:
    frames deleted under the backup policy (derived data is disposable),
    a half-finished extraction, or a model promoted after the predictions
    were made.
    """
    run_dir = Path(run_dir)
    raw = run_dir / "shadowgraph" / "raw"
    preds = run_dir / "shadowgraph" / "analysis" / "predictions.json"
    meta = previous_analysis(run_dir)
    if not meta or meta.get("stride") != stride:
        return False
    if meta.get("limited"):
        # A --limit extraction holds only the first N frames while looking
        # complete. Reusing it silently caps a full run at N.
        return False
    n = meta.get("frame_count")
    if not n:
        return False
    if len(list((raw / "frames" / "8bit").glob("*.png"))) != n:
        return False
    if len(list((raw / "frames" / "16bit").glob("*.tiff"))) != n:
        return False
    manifest = raw / "instances.json"
    if not ((raw / "background_median.tiff").exists() and manifest.exists()
            and preds.exists()):
        return False
    t_pred = preds.stat().st_mtime
    if t_pred < manifest.stat().st_mtime:
        return False
    t_model = _newest_weights_mtime(model_dir)
    if t_model is None or t_pred < t_model:
        return False
    return True


def auto_ci_stride(fps, stride) -> int:
    """Frames between CI samples so each is >= one decorrelation time apart.
    10 at 500 fps / stride 1; 1 at 500 fps / stride 10 (already independent)."""
    if not fps:
        return 1
    return max(1, round(DECORRELATION_S * fps / stride))


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
                    model_dir: Path = None, images="extremes", ci_stride=None,
                    bg_frames=BG_FRAMES, limit=None, reuse=False,
                    log=print) -> dict:
    """
    Run the whole chain. Returns measure_run's summary dict.

    `images`: "extremes" (default) draws only the frames the Extremes tab
    shows; "all" draws every frame; None/False draws none. True means "all",
    for older callers. Drawing all of them was ~80% of measurement time on the
    lab PC, and every frame can be regenerated from the .cine later.

    `reuse`: when this run folder already holds a complete analysis at the
    same stride (see can_reuse), skip extraction, background and inference and
    only measure. Measurement is deterministic, so the numbers come out the
    same; this is how Full Analyse Cine draws every image of an existing run.

    `ci_stride=None` picks it from the cine's frame rate (auto_ci_stride).

    `log` takes one string; the GUI passes something that appends to its log
    panel, the CLI passes print.
    """
    if images is True:
        images = "all"
    t0 = time.time()
    cine = Path(cine)
    run_dir = Path(run_dir)
    if not cine.exists():
        raise FileNotFoundError(f"no such .cine: {cine}")

    # Per-stage wall clock. Only a total was reported before, which cannot tell
    # you whether a slow run was the extraction, the model or the measurement --
    # and those have completely different fixes.
    stage_s = {}

    class _Stage:
        def __init__(self, name):
            self.name = name
        def __enter__(self):
            self.t = time.time()
            return self
        def __exit__(self, *exc):
            stage_s[self.name] = round(time.time() - self.t, 1)
            log(f"    [{self.name} took {_fmt_dur(stage_s[self.name])}]")
            return False

    # Layout (changed 2026-09-28):
    #   shadowgraph/raw/CINE/recording_*.cine   the archival source, ALONE
    #   shadowgraph/raw/frames/{8bit,16bit}/    extracted frames
    #   shadowgraph/raw/instances.json          image manifest (INPUT, not a result)
    #   shadowgraph/raw/background_median.tiff
    #   shadowgraph/analysis/                   predictions + measurement output
    #
    # `raw/` is the --val-dir. Every tool resolves <val-dir>/frames/8bit and
    # <val-dir>/instances.json, which is the same contract 06_validation and
    # 09_experiments satisfy -- that is what lets a capture be analysed by
    # exactly the same code as the thesis validation set. Frames used to live
    # inside CINE/ to meet it, which put 30 GB of regenerable data in the same
    # folder as the one irreplaceable file. Moving the boundary up one level
    # keeps the contract and makes the backup rule "sync raw/CINE, skip the
    # rest of raw/".
    raw_dir = run_dir / "shadowgraph" / "raw"
    cine_dir = raw_dir / "CINE"
    analysis = run_dir / "shadowgraph" / "analysis"
    cine_dir.mkdir(parents=True, exist_ok=True)
    analysis.mkdir(parents=True, exist_ok=True)

    frames_16 = raw_dir / "frames" / "16bit"
    frames_8 = raw_dir / "frames" / "8bit"
    bg_path = raw_dir / "background_median.tiff"
    preds = analysis / "predictions.json"

    reusing = reuse and can_reuse(run_dir, stride, model_dir)
    if reuse and not reusing:
        log(f"no complete stride-{stride} analysis to reuse here -- running the full chain")

    if reusing:
        n_frames = len(list(frames_8.glob("*.png")))
        log(f"\n=== reusing the existing stride-{stride} analysis "
            f"({n_frames} frames): extraction, background and inference skipped ===")
    else:
        # The .cine is the archival source of truth, so it lives inside the run
        # folder. Copy it in if it was picked from elsewhere (the Full Analyse
        # path); a real capture will already have written it here.
        local_cine = cine_dir / cine.name
        if cine.resolve() != local_cine.resolve():
            log(f"copying {cine.name} into the run folder ...")
            with _Stage("copy cine"):
                shutil.copy2(cine, local_cine)

        # ---- 1. frames ---------------------------------------------------
        log("\n=== 1/4  extracting frames ===")
        # output_root/run_name is where cine_extract writes, so this lands
        # frames and instances.json directly in raw/ rather than inside CINE/.
        cmd = [sys.executable, HERE / "cine_extract.py", local_cine,
               "--run-name", raw_dir.name, "--output-root", raw_dir.parent,
               "--stride", stride, "--overwrite"]
        if limit:
            cmd += ["--limit", limit]
        with _Stage("extract frames"):
            _run(cmd, log)

        n_frames = len(list(frames_8.glob("*.png")))
        if n_frames == 0:
            raise RuntimeError(f"extraction produced no frames in {frames_8}")

        # ---- 2. background -----------------------------------------------
        log("\n=== 2/4  background ===")
        with _Stage("background"):
            build_background(frames_16, bg_path, bg_frames, log)

        # ---- 3. inference ------------------------------------------------
        log(f"\n=== 3/4  inference on {n_frames} frames ===")
        cmd = [sys.executable, HERE / "tiled_inference.py", "--all",
               "--root", run_dir, "--val-dir", "shadowgraph/raw",
               "--out", preds]
        if device:
            cmd += ["--device", device]
        if model_dir:
            cmd += ["--model-dir", model_dir]
        with _Stage("inference"):
            _run(cmd, log)

    # Consecutive frames closer than one decorrelation time share droplets, and
    # bootstrapping them as independent gives a CI ~3x too narrow at stride 1.
    if ci_stride is None:
        fps = (previous_analysis(run_dir) or {}).get("frame_rate_fps")
        ci_stride = auto_ci_stride(fps, stride)
        log(f"ci-stride {ci_stride} (auto: {fps or '?'} fps, stride {stride})")

    # ---- 4. measurement --------------------------------------------------
    log("\n=== 4/4  measurement ===")
    out_dir = analysis / f"measurement_{score_thresh:.2f}"
    cmd = [sys.executable, HERE / "measure_run.py", "--pred", preds,
           "--root", run_dir, "--val-dir", "shadowgraph/raw",
           "--background", bg_path,
           "--sixteen-bit-dir", frames_16,
           "--score-thresh", score_thresh,
           "--out-dir", out_dir]
    if images:
        cmd += ["--images", images]
    if ci_stride:
        cmd += ["--ci-stride", ci_stride]
    with _Stage("measurement"):
        _run(cmd, log)

    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    # Surface the sizing method in the log and the GUI. A run measured with a
    # different sizer_version is NOT comparable with one measured before it, and
    # compare_runs.py refuses to mix them -- so it must be visible here rather
    # than buried in summary.json.
    _p = summary.get("provenance", {})
    log(f"    sizer {_p.get('sizer_version', 'pre-2.0.0 (model mask area)')}"
        f"  split {_p.get('split_um', '-')} um  core {_p.get('core_estimator', 'min')}")
    _mc = _p.get("diameter_method_counts")
    if _mc:
        log(f"    diameters: " + ", ".join(f"{k} {v:,}" for k, v in sorted(_mc.items())))
    summary["_elapsed_total_s"] = round(time.time() - t0, 1)
    summary["_run_dir"] = str(run_dir)
    summary["_frames"] = n_frames
    summary["_measurement_dir"] = str(out_dir)
    summary["_stage_seconds"] = stage_s
    summary["_stride"] = stride
    summary["_reused_analysis"] = reusing

    total = summary["_elapsed_total_s"]
    log("\n=== stage breakdown ===")
    for name, secs in stage_s.items():
        share = f"{secs / total * 100:4.0f}%" if total else "   ?"
        log(f"  {name:16s}{_fmt_dur(secs):>10}  {share}")
    log(f"  {'TOTAL':16s}{_fmt_dur(total):>10}")
    if n_frames:
        log(f"  ({n_frames} frames at stride {stride} -> "
            f"{total / n_frames:.2f} s/frame end to end)")

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
    ap.add_argument("--images", choices=["extremes", "all"], default="extremes",
                    help="which frames to draw marked-up images for (default extremes)")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--reuse", action="store_true",
                    help="if --run-dir already holds a complete analysis at this "
                         "stride, skip extraction/background/inference and only measure")
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
                    model_dir=args.model_dir,
                    images=None if args.no_images else args.images,
                    ci_stride=args.ci_stride, limit=args.limit, reuse=args.reuse)


if __name__ == "__main__":
    main()
