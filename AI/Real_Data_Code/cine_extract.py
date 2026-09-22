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
from datetime import datetime, timezone
from pathlib import Path

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

# Frames sampled to establish the single fixed 8-bit viewing window.
WINDOW_SAMPLE_FRAMES = 20
WINDOW_LOW_PCT = 0.05
WINDOW_HIGH_PCT = 99.95


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
    args = ap.parse_args()

    if args.output_root is None:
        args.output_root = default_output_root()

    if not args.cine.exists():
        sys.exit(f"File not found: {args.cine}")

    run_dir = args.output_root / args.run_name
    dir_16 = run_dir / "16bit"
    dir_8 = run_dir / "8bit"

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

        lo, hi, n_sampled = establish_view_window(cine, first, last)
        print(f"  8-bit viewing window: [{lo:.1f}, {hi:.1f}] "
              f"(p{WINDOW_LOW_PCT}-p{WINDOW_HIGH_PCT} over {n_sampled} frames)")

        nums = frame_numbers(first, last, args.stride, args.limit)
        print(f"  extracting {len(nums)} frames at stride {args.stride} "
              f"({args.stride / fps * 1e3:.2f} ms apart)")
        if args.limit:
            print(f"  DRY RUN -- limited to {args.limit} frames")

        src_dtype = None
        vmin, vmax = None, None

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

            if (i + 1) % 25 == 0 or i == len(nums) - 1:
                print(f"    {i + 1}/{len(nums)}")

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
                "mode": f"p{WINDOW_LOW_PCT}-p{WINDOW_HIGH_PCT} over {n_sampled} frames",
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

    print(f"\nDone. {len(nums)} frames -> {run_dir}")
    print(f"  16bit/  {len(nums)} TIFFs (primary)")
    print(f"  8bit/   {len(nums)} PNGs (viewing)")
    print(f"  observed value range across extracted frames: {vmin}..{vmax}")


if __name__ == "__main__":
    main()
