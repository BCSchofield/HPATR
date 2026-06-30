"""
Batch lamella analysis over a directory of TIFF frames.

Usage (standalone):
    python -m src.ai.lamella.batch_tiff <tiff_dir> [--model path.pt] [--arch smp|tiny]

Output:
    <tiff_dir>/lamella_thickness.csv  — one row per frame, strictly ordered.
"""
from __future__ import annotations
import argparse
import csv
import os
import glob
from typing import Callable, Optional
import numpy as np
import cv2

from .crop import OutletCrop
from .infer import LamellaSegmenter, StubSegmenter, Result


_CSV_FIELDS = ["frame_index", "filename", "thickness_px", "thickness_mm", "ok"]


def _save_mask_image(
    crop: np.ndarray,
    result,
    out_path: str,
) -> None:
    """Save a 2-panel PNG: original crop | masked overlay with probe lines."""
    h, w = crop.shape[:2]

    # Normalise crop to 8-bit for display
    crop8 = crop.astype(np.float32)
    lo, hi = crop8.min(), crop8.max()
    crop8 = ((crop8 - lo) / max(hi - lo, 1.0) * 255).astype(np.uint8)

    left  = cv2.cvtColor(crop8, cv2.COLOR_GRAY2BGR)
    right = left.copy()

    mask = result.mask
    t    = result.thickness

    # Green tint on liquid pixels
    liquid = mask > 0
    right[liquid] = (right[liquid] * 0.4 + np.array([0, 200, 80]) * 0.6).astype(np.uint8)

    # Draw all probe lines in cyan
    for y, x_left, x_right in t.probe_lines:
        cv2.line(right, (0, y), (w - 1, y), (255, 200, 0), 1, cv2.LINE_AA)

    # Highlight the median probe row in yellow (middle index)
    if t.probe_lines:
        mid = t.probe_lines[len(t.probe_lines) // 2]
        cv2.line(right, (0, mid[0]), (w - 1, mid[0]), (0, 220, 255), 2, cv2.LINE_AA)

    # Thickness text bottom-left of right panel
    if t.ok:
        label = f"{t.thickness_px:.1f}px"
        if t.thickness_mm is not None:
            label += f"  {t.thickness_mm:.3f}mm"
        cv2.putText(right, label, (4, h - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

    panel = np.hstack([left, right])
    cv2.imwrite(out_path, panel)


def run_batch(
    tiff_dir: str,
    segmenter,
    crop_box: OutletCrop,
    px_per_mm: float = 0.0,
    output_csv: Optional[str] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
    save_masks: bool = False,
) -> str:
    """
    Iterate over sorted TIFF files in tiff_dir, run segmenter on each, write CSV.

    Args:
        tiff_dir:    Directory containing .tif / .tiff files.
        segmenter:   LamellaSegmenter or StubSegmenter instance.
        crop_box:    OutletCrop defining the outlet channel region.
        px_per_mm:   Calibration scale (0.0 = skip mm conversion).
        output_csv:  Path for the output CSV. Defaults to tiff_dir/lamella_thickness.csv.
        progress_cb: Optional callback(int 0-100) called after each frame for GUI progress.

    Returns:
        Path to the written CSV file.
    """
    # Strictly sorted so frame order is always preserved
    patterns = ("*.tif", "*.tiff", "*.TIF", "*.TIFF")
    files: list[str] = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(tiff_dir, pat)))
    files = sorted(set(files))

    if not files:
        raise FileNotFoundError(f"No TIFF files found in: {tiff_dir}")

    if output_csv is None:
        output_csv = os.path.join(tiff_dir, "lamella_thickness.csv")

    masks_dir = None
    if save_masks:
        masks_dir = os.path.join(tiff_dir, "masks")
        os.makedirs(masks_dir, exist_ok=True)

    total = len(files)

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()

        for idx, fpath in enumerate(files):
            frame = cv2.imread(fpath, cv2.IMREAD_UNCHANGED)
            if frame is None:
                # Skip unreadable files but preserve ordering via empty row
                writer.writerow({
                    "frame_index": idx,
                    "filename": os.path.basename(fpath),
                    "thickness_px": "",
                    "thickness_mm": "",
                    "ok": "error",
                })
            else:
                result: Result = segmenter.analyse_frame(frame, crop_box, px_per_mm)
                t = result.thickness
                writer.writerow({
                    "frame_index": idx,
                    "filename": os.path.basename(fpath),
                    "thickness_px": f"{t.thickness_px:.4f}",
                    "thickness_mm": f"{t.thickness_mm:.4f}" if t.thickness_mm is not None else "",
                    "ok": str(t.ok),
                })
                if masks_dir is not None:
                    crop = crop_box.apply(frame)
                    stem = os.path.splitext(os.path.basename(fpath))[0]
                    _save_mask_image(crop, result, os.path.join(masks_dir, stem + "_mask.png"))
            if progress_cb is not None:
                progress_cb(int((idx + 1) / total * 100))

    return output_csv


# ── CLI entry point ───────────────────────────────────────────────────────────

def _main():
    parser = argparse.ArgumentParser(description="Batch lamella thickness analysis over TIFFs.")
    parser.add_argument("tiff_dir", help="Directory of .tif / .tiff frames.")
    parser.add_argument("--model", default=None,
                        help="Path to trained .pt model. Omit to use stub segmenter.")
    parser.add_argument("--arch", default="smp", choices=["smp", "tiny"],
                        help="Model architecture (only used if --model is set).")
    parser.add_argument("--crop", default="0,0,256,256",
                        help="Crop as x,y,w,h (default: 0,0,256,256).")
    parser.add_argument("--px-per-mm", type=float, default=0.0,
                        help="Pixels per mm for thickness conversion.")
    parser.add_argument("--output", default=None,
                        help="Output CSV path. Default: <tiff_dir>/lamella_thickness.csv.")
    args = parser.parse_args()

    x, y, w, h = (int(v) for v in args.crop.split(","))
    crop_box = OutletCrop(x=x, y=y, w=w, h=h)

    if args.model:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        segmenter = LamellaSegmenter.load(args.model, arch=args.arch, device=device)
        print(f"Loaded model: {args.model} (arch={args.arch}, device={device})")
    else:
        segmenter = StubSegmenter()
        print("No model specified — using StubSegmenter.")

    def _progress(pct):
        print(f"\r  Progress: {pct:3d}%", end="", flush=True)

    out_path = run_batch(
        tiff_dir=args.tiff_dir,
        segmenter=segmenter,
        crop_box=crop_box,
        px_per_mm=args.px_per_mm,
        output_csv=args.output,
        progress_cb=_progress,
    )
    print(f"\nDone. CSV written to: {out_path}")


if __name__ == "__main__":
    _main()
