"""
Evaluate a trained lamella model against a held-out validation set.
Appends one CSV row per model — the thesis comparison table.

Usage:
    python -m src.ai.lamella.evaluate \\
        --model path/to/lamella_smp.pt --arch smp \\
        --data  path/to/val_data/      \\
        --output lamella_comparison.csv

Metrics reported:
    mean_iou, mean_dice, thickness_mae_px, thickness_mae_mm (if px_per_mm set)
"""
from __future__ import annotations
import argparse
import csv
import datetime
import os
import numpy as np
import cv2

from .crop import OutletCrop
from .infer import LamellaSegmenter, StubSegmenter, thickness_from_mask


_CSV_FIELDS = [
    "timestamp", "model_path", "arch", "n_images",
    "mean_iou", "mean_dice",
    "thickness_mae_px", "thickness_mae_mm",
    "notes",
]


def _iou(pred: np.ndarray, gt: np.ndarray) -> float:
    pred_b = pred > 0
    gt_b   = gt   > 0
    inter  = np.logical_and(pred_b, gt_b).sum()
    union  = np.logical_or(pred_b,  gt_b).sum()
    return inter / (union + 1e-6)


def _dice(pred: np.ndarray, gt: np.ndarray) -> float:
    pred_b = pred > 0
    gt_b   = gt   > 0
    inter  = np.logical_and(pred_b, gt_b).sum()
    return (2 * inter) / (pred_b.sum() + gt_b.sum() + 1e-6)


def evaluate(
    segmenter,
    data_dir: str,
    crop_box: OutletCrop,
    px_per_mm: float = 0.0,
    image_subdir: str = "images",
    mask_subdir: str  = "masks",
) -> dict:
    """Run evaluation over all image/mask pairs. Returns metrics dict."""
    import glob
    img_dir  = os.path.join(data_dir, image_subdir)
    mask_dir = os.path.join(data_dir, mask_subdir)

    img_files = sorted(glob.glob(os.path.join(img_dir, "*.png")) +
                       glob.glob(os.path.join(img_dir, "*.tif")) +
                       glob.glob(os.path.join(img_dir, "*.tiff")))

    ious, dices, thickness_errors_px, thickness_errors_mm = [], [], [], []

    for img_path in img_files:
        stem = os.path.splitext(os.path.basename(img_path))[0]
        mask_path = os.path.join(mask_dir, stem + ".png")
        if not os.path.exists(mask_path):
            continue

        frame = cv2.imread(img_path, cv2.IMREAD_UNCHANGED)
        gt    = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        if frame is None or gt is None:
            continue

        result = segmenter.analyse_frame(frame, crop_box, px_per_mm)
        pred_mask = result.mask

        # Resize GT to pred_mask size if needed (crop may differ)
        if gt.shape != pred_mask.shape:
            gt = cv2.resize(gt, (pred_mask.shape[1], pred_mask.shape[0]),
                            interpolation=cv2.INTER_NEAREST)

        ious.append(_iou(pred_mask, gt))
        dices.append(_dice(pred_mask, gt))

        # Thickness error vs GT mask thickness
        gt_t = thickness_from_mask(gt, px_per_mm)
        if result.thickness.ok and gt_t.ok:
            thickness_errors_px.append(abs(result.thickness.thickness_px - gt_t.thickness_px))
            if result.thickness.thickness_mm is not None and gt_t.thickness_mm is not None:
                thickness_errors_mm.append(
                    abs(result.thickness.thickness_mm - gt_t.thickness_mm))

    n = len(ious)
    return {
        "n_images":          n,
        "mean_iou":          float(np.mean(ious))               if ious else 0.0,
        "mean_dice":         float(np.mean(dices))              if dices else 0.0,
        "thickness_mae_px":  float(np.mean(thickness_errors_px)) if thickness_errors_px else 0.0,
        "thickness_mae_mm":  float(np.mean(thickness_errors_mm)) if thickness_errors_mm else 0.0,
    }


def append_to_csv(metrics: dict, model_path: str, arch: str, output_csv: str, notes: str = ""):
    """Append one result row to the comparison CSV (creates headers if new file)."""
    write_header = not os.path.exists(output_csv)
    with open(output_csv, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "timestamp":        datetime.datetime.now().isoformat(timespec="seconds"),
            "model_path":       model_path,
            "arch":             arch,
            "n_images":         metrics["n_images"],
            "mean_iou":         f"{metrics['mean_iou']:.4f}",
            "mean_dice":        f"{metrics['mean_dice']:.4f}",
            "thickness_mae_px": f"{metrics['thickness_mae_px']:.4f}",
            "thickness_mae_mm": f"{metrics['thickness_mae_mm']:.4f}",
            "notes":            notes,
        })


def _main():
    parser = argparse.ArgumentParser(description="Evaluate lamella segmentation model.")
    parser.add_argument("--model",     default=None,   help="Path to .pt model (omit=stub).")
    parser.add_argument("--arch",      default="smp",  choices=["smp", "tiny"])
    parser.add_argument("--data",      required=True,  help="Val data dir with images/ + masks/.")
    parser.add_argument("--crop",      default="0,0,256,256")
    parser.add_argument("--px-per-mm", type=float,     default=0.0)
    parser.add_argument("--output",    default="lamella_comparison.csv")
    parser.add_argument("--notes",     default="")
    args = parser.parse_args()

    x, y, w, h = (int(v) for v in args.crop.split(","))
    crop_box = OutletCrop(x=x, y=y, w=w, h=h)

    if args.model:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        segmenter = LamellaSegmenter.load(args.model, arch=args.arch, device=device)
        model_label = args.model
    else:
        segmenter = StubSegmenter()
        model_label = "StubSegmenter"

    print(f"Evaluating {model_label} on {args.data} ...")
    metrics = evaluate(segmenter, args.data, crop_box, args.px_per_mm)

    print(f"  n_images:          {metrics['n_images']}")
    print(f"  mean_iou:          {metrics['mean_iou']:.4f}")
    print(f"  mean_dice:         {metrics['mean_dice']:.4f}")
    print(f"  thickness_mae_px:  {metrics['thickness_mae_px']:.4f}")
    print(f"  thickness_mae_mm:  {metrics['thickness_mae_mm']:.4f}")

    append_to_csv(metrics, model_label, args.arch, args.output, args.notes)
    print(f"\nResults appended to: {args.output}")


if __name__ == "__main__":
    _main()
