"""
Convert LabelMe polygon annotations → binary PNG masks for U-Net training.

LabelMe saves one JSON per image. Each JSON contains a list of "shapes" with
type="polygon" and a "label" field. We fill the polygon labelled "liquid" (or
any label in LIQUID_LABELS) to produce a binary mask (255=liquid, 0=gas).

Usage:
    python -m src.ai.lamella.labelme_to_masks <json_dir> <output_mask_dir>

    json_dir:         directory of LabelMe JSON files
    output_mask_dir:  where to write binary PNG masks (created if absent)

Options:
    --labels   Comma-separated polygon labels to treat as liquid (default: liquid)
    --crop     x,y,w,h — if set, crop mask to this region after generation
"""
from __future__ import annotations
import argparse
import json
import os
import glob
import numpy as np
import cv2

LIQUID_LABELS = {"liquid"}


def convert_json_to_mask(
    json_path: str,
    output_dir: str,
    liquid_labels: set[str] = LIQUID_LABELS,
    crop: tuple | None = None,
) -> str:
    """
    Convert one LabelMe JSON file to a binary PNG mask.

    Args:
        json_path:      Path to LabelMe JSON.
        output_dir:     Directory to write the mask PNG.
        liquid_labels:  Set of label names to fill as liquid (255).
        crop:           Optional (x, y, w, h) to crop the mask after generation.

    Returns:
        Path to the written mask PNG.
    """
    with open(json_path) as f:
        data = json.load(f)

    img_h = data.get("imageHeight")
    img_w = data.get("imageWidth")
    if img_h is None or img_w is None:
        raise ValueError(f"imageHeight/imageWidth missing in {json_path}")

    mask = np.zeros((img_h, img_w), dtype=np.uint8)

    for shape in data.get("shapes", []):
        if shape.get("shape_type") != "polygon":
            continue
        if shape.get("label", "").lower() not in liquid_labels:
            continue
        pts = np.array(shape["points"], dtype=np.int32)
        cv2.fillPoly(mask, [pts], color=255)

    if crop is not None:
        x, y, w, h = crop
        mask = mask[y:y+h, x:x+w]

    stem = os.path.splitext(os.path.basename(json_path))[0]
    out_path = os.path.join(output_dir, stem + ".png")
    cv2.imwrite(out_path, mask)
    return out_path


def convert_directory(
    json_dir: str,
    output_dir: str,
    liquid_labels: set[str] = LIQUID_LABELS,
    crop: tuple | None = None,
) -> list[str]:
    """Convert all LabelMe JSONs in json_dir. Returns list of written mask paths."""
    os.makedirs(output_dir, exist_ok=True)
    json_files = sorted(glob.glob(os.path.join(json_dir, "*.json")))
    if not json_files:
        raise FileNotFoundError(f"No JSON files found in: {json_dir}")

    written = []
    for jf in json_files:
        try:
            out = convert_json_to_mask(jf, output_dir, liquid_labels, crop)
            written.append(out)
            print(f"  {os.path.basename(jf)} → {os.path.basename(out)}")
        except Exception as e:
            print(f"  SKIP {os.path.basename(jf)}: {e}")

    return written


def _main():
    parser = argparse.ArgumentParser(
        description="Convert LabelMe JSON annotations to binary PNG masks."
    )
    parser.add_argument("json_dir",    help="Directory of LabelMe JSON files.")
    parser.add_argument("output_dir",  help="Output directory for binary mask PNGs.")
    parser.add_argument("--labels",    default="liquid",
                        help="Comma-separated polygon labels to treat as liquid.")
    parser.add_argument("--crop",      default=None,
                        help="Crop masks to x,y,w,h after generation.")
    args = parser.parse_args()

    labels = {lbl.strip().lower() for lbl in args.labels.split(",")}
    crop = None
    if args.crop:
        crop = tuple(int(v) for v in args.crop.split(","))

    written = convert_directory(args.json_dir, args.output_dir, labels, crop)
    print(f"\nDone. {len(written)} masks written to: {args.output_dir}")


if __name__ == "__main__":
    _main()
