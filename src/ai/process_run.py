# Merge term 1
"""
src/ai/process_run.py
Dennis AI inference pipeline for a single shadowgraph capture.

Standalone — call from CLI or import run() from the GUI.

Flow
----
1. find_brightest_frame()  — picks best TIFF from frames_folder, saves
                             flashed_output.tiff into output_folder
2. frames_folder preserved — all raw frames kept for troubleshooting
3. Dennis loaded from LaCie
4. Inference on flashed_output.tiff  (score threshold 0.75)
5. Coloured mask overlay saved as ai_result.png
6. Metrics computed: mean confidence, avg droplet diameter (µm), D/L ratio
7. ai_results.json + ai_summary.xlsx written to output_folder

CLI usage
---------
    python process_run.py <frames_folder> <output_folder> <pixels_per_mm>

    frames_folder  — path to VIDEO_PERSISTENT/frames/ (TIFF sequence)
    output_folder  — path to {run_folder}/shadowgraph/analysis/
    pixels_per_mm  — float from GUI calibration
"""

import sys
import json
import math
import shutil
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np

# ── path setup ────────────────────────────────────────────────────────────────
_SRC  = Path(__file__).parent.parent   # src/
_ROOT = _SRC.parent                    # repo root
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_ROOT))

from config_loader import find_lacie_drive
from imaging.mp4_to_tiff import find_brightest_frame

# ── constants ─────────────────────────────────────────────────────────────────
SCORE_THRESHOLD = 0.75
ANCHOR_SIZES    = [[8, 16, 32, 64]]
CLASS_NAMES     = ["droplet", "ligament"]
# BGR colours for mask overlay: cyan for droplets, orange for ligaments
CLASS_COLOURS   = {0: (255, 200, 0), 1: (0, 120, 255)}
MASK_ALPHA      = 0.45   # transparency of mask overlay (0=invisible, 1=opaque)


# ── internal helpers ──────────────────────────────────────────────────────────

def _dennis_model_path() -> Path:
    lacie = find_lacie_drive()
    if lacie is None:
        raise RuntimeError("LaCie drive not found — cannot locate Dennis model.")
    return Path(lacie) / "Experiments" / "AI" / "Dennis" / "Dennis.pth"


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ── step 1: brightest frame ───────────────────────────────────────────────────

def extract_brightest_tiff(frames_folder: Path, output_folder: Path) -> Path:
    """
    Pick the brightest TIFF from frames_folder, save it as
    output_folder/flashed_output.tiff. frames_folder is preserved so all
    raw data remains available for troubleshooting.

    Returns the path to the saved flashed_output.tiff.
    """
    frames_folder = Path(frames_folder)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    print(f"[process_run] Extracting brightest frame from: {frames_folder}")
    success = find_brightest_frame(str(frames_folder), str(output_folder))
    if not success:
        raise RuntimeError(
            f"Could not extract a brightest frame from {frames_folder}. "
            "Check that TIFF files exist in the frames folder."
        )

    tiff_path = output_folder / "flashed_output.tiff"
    if not tiff_path.exists():
        raise RuntimeError(f"Expected flashed_output.tiff not found at {tiff_path}")

    print(f"[process_run] Brightest frame saved → {tiff_path}")
    # Frames folder is kept — all raw data is preserved for troubleshooting
    return tiff_path


# ── step 2: inference ─────────────────────────────────────────────────────────

def run_inference(tiff_path: Path, output_folder: Path, pixels_per_mm: float) -> dict:
    """
    Run Dennis on a single TIFF frame and write all outputs.

    Parameters
    ----------
    tiff_path     : path to flashed_output.tiff
    output_folder : where to write ai_result.png, ai_results.json, ai_summary.xlsx
    pixels_per_mm : GUI calibration value (always set before capture)

    Returns
    -------
    dict with keys:
        mean_confidence  float   0–100 %
        avg_droplet_um   float | None
        n_droplets       int
        n_ligaments      int
        dl_ratio         str     e.g. "14 : 3"
        result_image     Path    ai_result.png
        json_path        Path    ai_results.json
        xlsx_path        Path | None  ai_summary.xlsx
    """
    tiff_path     = Path(tiff_path)
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    # ── load image ────────────────────────────────────────────────────────────
    img_raw = cv2.imread(str(tiff_path), cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        raise FileNotFoundError(f"Could not read TIFF: {tiff_path}")

    # Ensure BGR — Detectron2 expects 3-channel BGR
    if img_raw.ndim == 2:
        img_bgr = cv2.cvtColor(img_raw, cv2.COLOR_GRAY2BGR)
    elif img_raw.ndim == 3 and img_raw.shape[2] == 4:
        img_bgr = cv2.cvtColor(img_raw, cv2.COLOR_BGRA2BGR)
    else:
        img_bgr = img_raw.copy()

    # ── build Detectron2 config and load Dennis ───────────────────────────────
    from detectron2.config import get_cfg
    from detectron2 import model_zoo
    from detectron2.engine import DefaultPredictor

    model_path = _dennis_model_path()
    if not model_path.exists():
        raise FileNotFoundError(f"Dennis model not found at: {model_path}")

    print(f"[process_run] Loading Dennis: {model_path}")
    cfg = get_cfg()
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )
    cfg.MODEL.ANCHOR_GENERATOR.SIZES  = ANCHOR_SIZES
    cfg.MODEL.WEIGHTS                  = str(model_path)
    cfg.MODEL.ROI_HEADS.NUM_CLASSES    = 2
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = SCORE_THRESHOLD
    cfg.MODEL.DEVICE                   = "cuda" if _cuda_available() else "cpu"
    cfg.DATALOADER.NUM_WORKERS         = 0

    predictor = DefaultPredictor(cfg)

    # ── run inference ─────────────────────────────────────────────────────────
    print(f"[process_run] Running inference (device={cfg.MODEL.DEVICE}, threshold={SCORE_THRESHOLD})...")
    outputs   = predictor(img_bgr)
    instances = outputs["instances"].to("cpu")

    scores  = instances.scores.numpy()        # (N,)
    classes = instances.pred_classes.numpy()  # (N,)  0=droplet 1=ligament
    masks   = instances.pred_masks.numpy()    # (N, H, W) bool
    boxes   = instances.pred_boxes.tensor.numpy()  # (N, 4) x1y1x2y2

    print(f"[process_run] {len(scores)} detection(s) above threshold {SCORE_THRESHOLD}")

    # ── compute metrics ───────────────────────────────────────────────────────
    droplet_mask  = classes == 0
    ligament_mask = classes == 1
    n_droplets    = int(droplet_mask.sum())
    n_ligaments   = int(ligament_mask.sum())

    mean_confidence = float(scores.mean() * 100) if len(scores) > 0 else 0.0

    if n_droplets > 0 and pixels_per_mm > 0:
        areas_px    = masks[droplet_mask].sum(axis=(1, 2)).astype(float)
        diam_px     = 2.0 * np.sqrt(areas_px / np.pi)
        diam_um     = (diam_px / pixels_per_mm) * 1000.0
        avg_droplet_um = float(diam_um.mean())
    else:
        avg_droplet_um = None

    dl_ratio = f"{n_droplets} : {n_ligaments}"

    # ── draw result image ─────────────────────────────────────────────────────
    result_img = img_bgr.copy()
    overlay    = img_bgr.copy()

    for i in range(len(scores)):
        colour = CLASS_COLOURS.get(int(classes[i]), (200, 200, 200))
        overlay[masks[i]] = colour

    cv2.addWeighted(overlay, MASK_ALPHA, result_img, 1.0 - MASK_ALPHA, 0, result_img)

    for i in range(len(scores)):
        x1, y1, x2, y2 = boxes[i].astype(int)
        colour = CLASS_COLOURS.get(int(classes[i]), (200, 200, 200))
        label  = f"{CLASS_NAMES[int(classes[i])]} {scores[i]*100:.0f}%"
        cv2.rectangle(result_img, (x1, y1), (x2, y2), colour, 1)
        cv2.putText(
            result_img, label, (x1, max(y1 - 4, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, colour, 1, cv2.LINE_AA,
        )

    result_image_path = output_folder / "ai_result.png"
    cv2.imwrite(str(result_image_path), result_img)
    print(f"[process_run] Result image → {result_image_path}")

    # ── per-detection records ─────────────────────────────────────────────────
    per_detection = []
    for i in range(len(scores)):
        area_px = int(masks[i].sum())
        diam_px = 2.0 * math.sqrt(area_px / math.pi)
        diam_um = (diam_px / pixels_per_mm) * 1000.0 if pixels_per_mm > 0 else None
        per_detection.append({
            "index":       i,
            "class":       CLASS_NAMES[int(classes[i])],
            "confidence":  round(float(scores[i]) * 100, 2),
            "area_px":     area_px,
            "diameter_px": round(diam_px, 2),
            "diameter_um": round(diam_um, 2) if diam_um is not None else None,
        })

    # ── save ai_results.json ──────────────────────────────────────────────────
    json_data = {
        "timestamp":       datetime.now().isoformat(),
        "model":           str(model_path),
        "score_threshold": SCORE_THRESHOLD,
        "pixels_per_mm":   pixels_per_mm,
        "n_droplets":      n_droplets,
        "n_ligaments":     n_ligaments,
        "mean_confidence": round(mean_confidence, 2),
        "avg_droplet_um":  round(avg_droplet_um, 2) if avg_droplet_um is not None else None,
        "dl_ratio":        dl_ratio,
        "detections":      per_detection,
    }
    json_path = output_folder / "ai_results.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2)
    print(f"[process_run] JSON → {json_path}")

    # ── save ai_summary.xlsx ──────────────────────────────────────────────────
    xlsx_path = None
    try:
        import pandas as pd

        summary_row = {
            "Timestamp":             json_data["timestamp"],
            "Model":                 "Dennis",
            "Score Threshold":       SCORE_THRESHOLD,
            "px/mm":                 pixels_per_mm,
            "N Droplets":            n_droplets,
            "N Ligaments":           n_ligaments,
            "Mean Confidence (%)":   round(mean_confidence, 2),
            "Avg Droplet Size (µm)": round(avg_droplet_um, 2) if avg_droplet_um is not None else "N/A",
            "D/L Ratio":             dl_ratio,
        }
        xlsx_path = output_folder / "ai_summary.xlsx"
        with pd.ExcelWriter(str(xlsx_path), engine="openpyxl") as writer:
            pd.DataFrame([summary_row]).to_excel(writer, sheet_name="Summary", index=False)
            pd.DataFrame(per_detection).to_excel(writer, sheet_name="Per Detection", index=False)
        print(f"[process_run] XLSX → {xlsx_path}")

    except ImportError:
        print("[process_run] pandas/openpyxl not available — XLSX skipped")

    return {
        "mean_confidence": mean_confidence,
        "avg_droplet_um":  avg_droplet_um,
        "n_droplets":      n_droplets,
        "n_ligaments":     n_ligaments,
        "dl_ratio":        dl_ratio,
        "result_image":    result_image_path,
        "json_path":       json_path,
        "xlsx_path":       xlsx_path,
    }


# ── main entry point (called by GUI) ─────────────────────────────────────────

def run(frames_folder: Path, output_folder: Path, pixels_per_mm: float) -> dict:
    """
    Full pipeline: extract brightest frame, delete frames folder, run Dennis.

    Parameters
    ----------
    frames_folder  : Path to VIDEO_PERSISTENT/frames/ (written by Phantom SDK)
    output_folder  : Path to {run_folder}/shadowgraph/analysis/
    pixels_per_mm  : Calibration float from GUI (always set before capture)

    Returns
    -------
    dict — see run_inference() docstring
    """
    tiff_path = extract_brightest_tiff(Path(frames_folder), Path(output_folder))
    return run_inference(tiff_path, Path(output_folder), pixels_per_mm)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Dennis AI inference on a Phantom TIFF frame sequence."
    )
    parser.add_argument("frames_folder", help="Folder containing TIFF frames from Phantom SDK")
    parser.add_argument("output_folder", help="Output folder (e.g. {run_folder}/shadowgraph/analysis/)")
    parser.add_argument("pixels_per_mm", type=float, help="Calibration: pixels per mm from GUI")
    args = parser.parse_args()

    results = run(Path(args.frames_folder), Path(args.output_folder), args.pixels_per_mm)

    print("\n" + "=" * 50)
    print("AI ANALYSIS COMPLETE")
    print("=" * 50)
    print(f"  Droplets detected : {results['n_droplets']}")
    print(f"  Ligaments detected: {results['n_ligaments']}")
    print(f"  Mean confidence   : {results['mean_confidence']:.1f}%")
    if results["avg_droplet_um"] is not None:
        print(f"  Avg droplet size  : {results['avg_droplet_um']:.1f} µm")
    else:
        print(f"  Avg droplet size  : N/A (no droplets detected)")
    print(f"  D/L ratio         : {results['dl_ratio']}")
    print(f"  Result image      : {results['result_image']}")
