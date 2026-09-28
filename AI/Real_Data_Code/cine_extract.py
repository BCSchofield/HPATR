#!/usr/bin/env python3
"""
cine_extract.py -- Phantom .cine -> per-run folder of frames.

Step 0 of the real-data pipeline (see docs/HANDOFF_real_data_pipeline.md).
Everything downstream reads the folder this produces; nothing else opens a
.cine.

Two outputs per run:

  16bit/  native unscaled values, uncompressed TIFF. THIS IS THE DATA.
          Transmission maps, compositing and all measurement use these.
          The camera is 12-bit in a uint16 container, so values run to
          ~4095, not 65535 (background sits around ~807). Uncompressed
          TIFF reads back ~9x faster than 16-bit PNG, which matters once
          Step 2 is re-reading every frame repeatedly while tuning
          thresholds. Read with
          cv2.IMREAD_UNCHANGED -- plain cv2.imread silently downconverts
          to 8-bit BGR and undoes the point.

  8bit/   viewing only, for the by-eye steps (validation-frame picking,
          contact-sheet review, background selection). One fixed linear
          mapping is computed once and applied identically to every frame,
          so a sparse frame and a dense frame remain visually comparable.
          Never measure off these.

Frame numbering: Phantom pre-trigger frames are NEGATIVE (this run starts
at -1). Always walk first_frame_number..last_frame_number; never
range(total_frames).

Usage:
    python cine_extract.py <cine> --run-name 125917_NNA_3000sccm
    python cine_extract.py <cine> --run-name foo --stride 10
    python cine_extract.py <cine> --run-name foo --limit 3      # dry run
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _fmt_dur(seconds) -> str:
    """Human-readable duration: '45s', '2m 05s', '1h 12m'."""
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

try:
    from cine_reader import Cine
except ImportError:
    sys.exit("cine-handler is required:  pip install cine-handler")


# Cross-platform drive resolution. Never hardcode /Volumes/... -- this runs on
# the Mac and the Windows training machine, where the LaCie is a drive letter.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402


def default_output_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Connect it, or pass --output-root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data" / "00_frames"

# Frames sampled to establish the 8-bit window when it is measured per run.
WINDOW_SAMPLE_FRAMES = 20
WINDOW_LOW_PCT = 0.05
WINDOW_HIGH_PCT = 99.95

# THE PINNED 8-BIT WINDOW -- the default, and what any run destined for
# inference must use.
#
# The model is fed 8-BIT images and was TRAINED on 8-bit composites (verified:
# 05_dataset_v3/images are uint8). The 16-bit TIFFs are never shown to the
# network -- they are only read back afterwards for measurement. So this linear
# rescale IS the information the model learns "droplet" from, and it has to
# mean the same thing at training and inference time.
#
# 05_dataset_v3/annotations/instances.json records the window the composites
# were built with and says so explicitly: "matches real frame extraction;
# inference on real frames must use the same window".
#
# Measuring it per run instead (p0.05-p99.95, the old default) gave a DIFFERENT
# window for every recording -- [27, 876] for 125917_NNA_3000sccm, [66, 901]
# for 101947_NNA_4500sccm, [68, 117] for 103608_NNA_4500sccm. At transmission
# 0.3 (raw ~242) the first two map the identical object to 8-bit 65 vs 54, a
# ~17% contrast difference caused purely by which recording it came from. For
# comparing runs that is a silent, uncontrolled variable.
#
# --window-per-run restores the old behaviour for by-eye work on a recording
# that is not going near the model.
PINNED_WINDOW = (27.0, 876.0)
PINNED_WINDOW_SOURCE = "05_dataset_v3 composites (125917_NNA_3000sccm extraction)"
# Warn if more than this fraction of sampled pixels fall outside the pinned
# window -- the signal that lighting or exposure has drifted far enough that
# the render is clipping, and the model is seeing flattened contrast.
CLIP_WARN_FRACTION = 0.02


def frame_numbers(first, last, stride, limit=None):
    """Frame numbers at the given stride. Handles negative (pre-trigger) starts."""
    nums = list(range(first, last + 1, stride))
    if limit is not None:
        nums = nums[:limit]
    return nums


def establish_view_window(cine, first, last):
    """
    One intensity window for the whole run, for the 8-bit viewing render only.

    Computed across frames spanning the entire recording so it covers both
    sparse and dense conditions. Per-frame auto-contrast would make frames
    visually incomparable and corrupt the by-eye sparse/dense judgement in
    Step 1.
    """
    span = max(1, (last - first) // max(1, WINDOW_SAMPLE_FRAMES - 1))
    sample = list(range(first, last + 1, span))[:WINDOW_SAMPLE_FRAMES]

    vals = []
    for n in sample:
        cine.load_frame(n)
        vals.append(np.asarray(cine.frame).ravel()[::17])  # decimated
    allv = np.concatenate(vals)

    lo = float(np.percentile(allv, WINDOW_LOW_PCT))
    hi = float(np.percentile(allv, WINDOW_HIGH_PCT))
    return lo, hi, len(sample)


def to_8bit(frame, lo, hi):
    f = (frame.astype(np.float64) - lo) / max(hi - lo, 1e-9)
    return np.clip(f * 255.0, 0, 255).astype(np.uint8)


def check_window_fit(cine, first, last, lo, hi):
    """
    How much of this recording falls outside the window it is about to be
    rendered with.

    Clipping is silent and destroys contrast exactly where it matters: a
    droplet darker than `lo` flattens to 0 and becomes indistinguishable from
    any other dark droplet, so its SIZE survives but its depth does not. This
    only reports -- it never changes the window, because auto-adjusting is the
    behaviour that made runs incomparable in the first place.
    """
    span = max(1, (last - first) // max(1, WINDOW_SAMPLE_FRAMES - 1))
    sample = list(range(first, last + 1, span))[:WINDOW_SAMPLE_FRAMES]
    vals = []
    for n in sample:
        cine.load_frame(n)
        vals.append(np.asarray(cine.frame).ravel()[::17])
    allv = np.concatenate(vals)
    below = float((allv < lo).mean())
    above = float((allv > hi).mean())
    return below, above, len(sample)


def main():
    ap = argparse.ArgumentParser(
        description="Extract strided frames from a Phantom .cine (16-bit primary + 8-bit viewing)")
    ap.add_argument("cine", type=Path)
    ap.add_argument("--run-name", required=True,
                    help="run folder name, e.g. 125917_NNA_3000sccm")
    ap.add_argument("--stride", type=int, default=10,
                    help="keep every Nth frame (default 10)")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N frames (dry run)")
    ap.add_argument("--output-root", type=Path, default=None)
    ap.add_argument("--overwrite", action="store_true",
                    help="clear an existing run folder before extracting")
    ap.add_argument("--window-per-run", action="store_true",
                    help="measure the 8-bit window from THIS recording "
                         f"(p{WINDOW_LOW_PCT}-p{WINDOW_HIGH_PCT}) instead of using the "
                         f"pinned {PINNED_WINDOW}. Only for by-eye work on a recording "
                         "that is not going near the model -- a per-run window makes "
                         "runs incomparable to each other and to the training set.")
    ap.add_argument("--flat", action="store_true",
                    help="write 16bit/ and 8bit/ directly in the run folder, the old "
                         "layout, instead of nesting them under frames/. The nested "
                         "layout is what tiled_inference.py and measure_run.py expect.")
    args = ap.parse_args()

    if args.output_root is None:
        args.output_root = default_output_root()

    if not args.cine.exists():
        sys.exit(f"File not found: {args.cine}")

    run_dir = args.output_root / args.run_name
    # frames/16bit + frames/8bit + instances.json is the layout the rest of the
    # toolchain already reads (tiled_inference.py, measure_run.py, score_v2.py
    # all resolve <val-dir>/frames/8bit). Writing it here means a run folder is
    # directly usable as a --val-dir with no intermediate step; previously every
    # new frame set needed a hand-written manifest and a reshuffle first.
    frames_dir = run_dir if args.flat else run_dir / "frames"
    dir_16 = frames_dir / "16bit"
    dir_8 = frames_dir / "8bit"

    # A re-run at a different stride produces different frame numbering, so
    # surviving files from a previous pass would sit alongside the new ones
    # and contradict extraction_metadata.json. Refuse rather than mix.
    existing = list_files(dir_16, "*.tiff") + list_files(dir_8, "*.png")
    if existing and not args.overwrite:
        sys.exit(
            f"Run folder already holds {len(existing)} frames: {run_dir}\n"
            f"Re-run with --overwrite to replace it, or use a different "
            f"--run-name.")
    if existing and args.overwrite:
        print(f"--overwrite: clearing {len(existing)} existing frames in {run_dir}")
        for p in existing:
            p.unlink()

    dir_16.mkdir(parents=True, exist_ok=True)
    dir_8.mkdir(parents=True, exist_ok=True)

    with Cine(args.cine) as cine:
        first = cine.first_frame_number
        last = cine.last_frame_number
        fps = float(cine.frame_rate)

        print(f"Opened {args.cine.name}")
        print(f"  frames {first}..{last} ({cine.total_frames} total) @ {fps} fps")

        if args.window_per_run:
            lo, hi, n_sampled = establish_view_window(cine, first, last)
            window_mode = f"p{WINDOW_LOW_PCT}-p{WINDOW_HIGH_PCT} over {n_sampled} frames"
            print(f"  8-bit window: [{lo:.1f}, {hi:.1f}]  MEASURED PER RUN")
            print("    !! This run is NOT comparable to runs rendered with the "
                  "pinned window,")
            print("       and the model was trained on the pinned one. Do not "
                  "run inference on this.")
        else:
            lo, hi = PINNED_WINDOW
            window_mode = f"pinned -- {PINNED_WINDOW_SOURCE}"
            below, above, n_sampled = check_window_fit(cine, first, last, lo, hi)
            print(f"  8-bit window: [{lo:.1f}, {hi:.1f}]  PINNED "
                  f"({PINNED_WINDOW_SOURCE})")
            print(f"    fit over {n_sampled} sampled frames: "
                  f"{below * 100:.2f}% of pixels below, {above * 100:.2f}% above")
            if below > CLIP_WARN_FRACTION or above > CLIP_WARN_FRACTION:
                print(f"    !! WARNING: more than {CLIP_WARN_FRACTION * 100:.0f}% of "
                      f"pixels fall outside the window and will CLIP.")
                print("       Contrast is being flattened where it matters. Check the "
                      "backlight,")
                print("       exposure and gain against the runs the model was trained "
                      "on before")
                print("       trusting any measurement from this recording.")

        nums = frame_numbers(first, last, args.stride, args.limit)
        print(f"  extracting {len(nums)} frames at stride {args.stride} "
              f"({args.stride / fps * 1e3:.2f} ms apart)")
        if args.limit:
            print(f"  DRY RUN -- limited to {args.limit} frames")

        src_dtype = None
        vmin, vmax = None, None
        _t_extract = time.time()

        for i, n in enumerate(nums):
            cine.load_frame(n)
            frame = np.asarray(cine.frame)
            src_dtype = str(frame.dtype)

            fmin, fmax = int(frame.min()), int(frame.max())
            vmin = fmin if vmin is None else min(vmin, fmin)
            vmax = fmax if vmax is None else max(vmax, fmax)

            stem = f"frame_{i:04d}_n{n}"
            # 16-bit: native values, no scaling of any kind. Uncompressed TIFF --
            # ~9x faster to read back than PNG, which matters because Step 2
            # re-reads every frame repeatedly while tuning thresholds.
            cv2.imwrite(str(dir_16 / f"{stem}.tiff"), frame.astype(np.uint16),
                        [cv2.IMWRITE_TIFF_COMPRESSION, 1])
            # 8-bit: the single fixed mapping, PNG for reliable Preview/QuickLook viewing.
            cv2.imwrite(str(dir_8 / f"{stem}.png"), to_8bit(frame, lo, hi))

            # Progress with a rate and an ETA. Extraction writes an ~8 MB TIFF
            # plus a PNG per frame, so on a long capture this is the stage that
            # looks hung; a bare "25/300" every 25 frames did not say whether
            # it was moving or how much longer it had.
            done = i + 1
            if done % 25 == 0 or done == len(nums):
                el = time.time() - _t_extract
                rate = done / el if el > 0 else 0.0
                eta = (len(nums) - done) / rate if rate > 0 else 0.0
                print(f"    {done}/{len(nums)} ({done * 100 // len(nums)}%)"
                      f"   {rate:.1f} frames/s"
                      + (f"   ETA {_fmt_dur(eta)}" if done < len(nums)
                         else f"   took {_fmt_dur(el)}"),
                      flush=True)

        meta = {
            "run_name": args.run_name,
            "source_cine": str(args.cine.resolve()),
            "extracted_utc": datetime.now(timezone.utc).isoformat(),
            "stride": args.stride,
            "frame_count": len(nums),
            "frame_numbers": nums,
            "first_frame_number": first,
            "last_frame_number": last,
            "total_frames_in_cine": cine.total_frames,
            "frame_rate_fps": fps,
            "stride_ms": args.stride / fps * 1e3,
            "exposure_us": cine.exposure_time_seconds * 1e6,
            "source_dtype": src_dtype,
            "observed_value_range": {"min": vmin, "max": vmax},
            "viewing_window_8bit": {
                "low": lo,
                "high": hi,
                "mode": window_mode,
                "pinned": not args.window_per_run,
            },
            "dry_run_limit": args.limit,
            "note": (
                "16bit/ holds native unscaled camera values as uncompressed "
                "TIFF and is the primary data for all measurement -- read "
                "with cv2.IMREAD_UNCHANGED. 8bit/ is a PNG viewing render "
                "produced with the single fixed linear window above applied "
                "identically to every frame; do not measure off it, and do "
                "not re-normalise frames individually."
            ),
        }
        (run_dir / "extraction_metadata.json").write_text(json.dumps(meta, indent=2),
                                                          encoding="utf-8")

        # Images-only COCO manifest, so this folder is immediately usable as a
        # --val-dir. tiled_inference.py needs it purely to map file_name ->
        # image_id; there are no annotations because these frames are not
        # labelled. Written here because this is the only place that already
        # knows every frame's name and dimensions as it writes them -- doing it
        # later meant a hand-written script per frame set, every time.
        h, w = frame.shape[:2]
        manifest = {
            "info": {
                "description": "Images-only manifest for an UNLABELLED frame set. "
                               "No annotations: these frames have no ground truth. "
                               "score_v2.py CANNOT be run against this; "
                               "measure_run.py can.",
                "run_name": args.run_name,
                "source_cine": str(args.cine.resolve()),
                "created_utc": datetime.now(timezone.utc).isoformat(),
            },
            "images": [
                {"id": i + 1, "file_name": f"frame_{i:04d}_n{n}.png",
                 "width": w, "height": h, "source_run": args.run_name}
                for i, n in enumerate(nums)
            ],
            "annotations": [],
            "categories": [{"id": 1, "name": "droplet"},
                           {"id": 2, "name": "filament"},
                           {"id": 3, "name": "blob"}],
        }
        (run_dir / "instances.json").write_text(json.dumps(manifest, indent=2),
                                                encoding="utf-8")
        (run_dir / "frame_runs.json").write_text(json.dumps({
            "purpose": "Which recording each frame came from. Tools computing "
                       "transmission MUST look the frame up here -- the "
                       "temporal-median background is per-run.",
            "frames": {f"frame_{i:04d}_n{n}": args.run_name
                      for i, n in enumerate(nums)},
        }, indent=2), encoding="utf-8")

    rel = "" if args.flat else "frames/"
    print(f"\nDone. {len(nums)} frames -> {run_dir}")
    print(f"  {rel}16bit/  {len(nums)} TIFFs (primary, for measurement)")
    print(f"  {rel}8bit/   {len(nums)} PNGs (what the model is fed)")
    print(f"  instances.json    images-only manifest -- this folder is now a "
          f"usable --val-dir")
    print(f"  observed value range across extracted frames: {vmin}..{vmax}")


if __name__ == "__main__":
    main()
