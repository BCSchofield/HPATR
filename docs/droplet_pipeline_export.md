# HPATR Droplet Detection Pipeline — Code Export

Exported for planning discussion in a separate chat. Raw contents / trimmed
excerpts as requested — see cut-notes inline for anything over ~400 lines.

---

## 1. Inference script

`AI/Training_Analysis/inference_detectron2.py` (canonical — most recently
touched, commit "Anchors" 2026-04-11). A near-identical unmerged copy also
exists at repo root `inference_detectron2.py`, pointing at a different
`MODEL_PATH` (`Claudia.pth`) — same logic otherwise.

```python
"""
Detectron2 Inference Script
Run inference on new images and export masks (visual + numerical data)
"""

import os
import json
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

import torch
from detectron2.engine import DefaultPredictor
from detectron2.config import get_cfg
from detectron2.utils.visualizer import Visualizer, ColorMode
from detectron2.data import MetadataCatalog
from detectron2 import model_zoo
import matplotlib.pyplot as plt

# ============================================================================
# CONFIGURATION
# ============================================================================

# Model path (update after training)
# Use the final model from your latest training run
MODEL_PATH = r"D:\Experiments\AI\training_2025_12_25_15_43_57\model_final.pth"

# Detection threshold (0.0 to 1.0)
# Lower = more detections (but more false positives)
# Higher = fewer detections (but more accurate)
SCORE_THRESHOLD = 0.5

# Output directories
OUTPUT_DIR = Path("./inference_results")
VISUALIZATIONS_DIR = OUTPUT_DIR / "visualizations"
MASKS_DIR = OUTPUT_DIR / "masks"
DATA_DIR = OUTPUT_DIR / "data"

# ============================================================================
# SETUP
# ============================================================================

def setup_predictor(model_path: str, score_threshold: float = 0.5, nms_threshold: float = 0.3):
    """Load trained model and create predictor"""
    print(f"\n{'='*60}")
    print("Loading Model")
    print(f"{'='*60}")

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found: {model_path}")

    cfg = get_cfg()

    # IMPORTANT: Use the same config as training!
    # Load the same config file that was used during training
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )

    # Set model weights
    cfg.MODEL.WEIGHTS = model_path
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2  # droplet and ligament
    cfg.MODEL.ANCHOR_GENERATOR.SIZES = [[8, 16, 32, 64]]  # Match Dennis training anchors
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = score_threshold

    # Non-Maximum Suppression (NMS) settings to reduce duplicate detections
    # Lower values = more aggressive (removes more overlapping boxes)
    # Default is usually 0.5, but we'll make it more aggressive
    cfg.MODEL.ROI_HEADS.NMS_THRESH_TEST = nms_threshold

    # Set device
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cfg.MODEL.DEVICE = device

    # Register metadata for visualization
    MetadataCatalog.get("spray_train").set(thing_classes=["droplet", "ligament"])

    predictor = DefaultPredictor(cfg)

    print(f"[OK] Model loaded from: {model_path}")
    print(f"[OK] Device: {device}")
    print(f"[OK] Score threshold: {score_threshold}")
    print(f"[OK] NMS threshold: {nms_threshold} (lower = more aggressive)")
    print(f"[OK] Config: Mask R-CNN R50 FPN 3x")

    return predictor, cfg

def fit_ellipse_to_mask(mask: np.ndarray) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
    """
    Fit an ellipse to a binary mask.

    Returns:
        ((center_x, center_y), (major_axis, minor_axis), angle)
    """
    # Find contours
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if len(contours) == 0:
        return None

    # Use largest contour
    largest_contour = max(contours, key=cv2.contourArea)

    if len(largest_contour) < 5:  # Need at least 5 points for ellipse
        return None

    # Fit ellipse
    ellipse = cv2.fitEllipse(largest_contour)
    center = ellipse[0]  # (x, y)
    axes = ellipse[1]  # (major_axis, minor_axis)
    angle = ellipse[2]  # rotation angle in degrees

    return (center, axes, angle)

def calculate_droplet_properties(mask: np.ndarray, pixels_per_mm: float = None) -> Dict:
    """
    Calculate droplet properties from mask.

    Args:
        mask: Binary mask
        pixels_per_mm: Calibration factor (optional)

    Returns:
        Dictionary with droplet properties
    """
    # Basic properties
    area_pixels = np.sum(mask > 0)
    equivalent_diameter_pixels = 2 * np.sqrt(area_pixels / np.pi)

    # Fit ellipse
    ellipse_data = fit_ellipse_to_mask(mask)

    properties = {
        'area_pixels': float(area_pixels),
        'equivalent_diameter_pixels': float(equivalent_diameter_pixels),
    }

    if ellipse_data:
        center, axes, angle = ellipse_data
        properties['ellipse'] = {
            'center': {'x': float(center[0]), 'y': float(center[1])},
            'major_axis_pixels': float(axes[0]),
            'minor_axis_pixels': float(axes[1]),
            'angle_degrees': float(angle)
        }

        # Calculate equivalent diameter from ellipse
        ellipse_area = np.pi * (axes[0] / 2) * (axes[1] / 2)
        properties['ellipse_equivalent_diameter_pixels'] = 2 * np.sqrt(ellipse_area / np.pi)
    else:
        properties['ellipse'] = None

    # Convert to physical units if calibration provided
    if pixels_per_mm:
        properties['area_mm2'] = properties['area_pixels'] / (pixels_per_mm ** 2)
        properties['equivalent_diameter_mm'] = properties['equivalent_diameter_pixels'] / pixels_per_mm

        if ellipse_data:
            properties['ellipse']['major_axis_mm'] = axes[0] / pixels_per_mm
            properties['ellipse']['minor_axis_mm'] = axes[1] / pixels_per_mm
            properties['ellipse_equivalent_diameter_mm'] = properties['ellipse_equivalent_diameter_pixels'] / pixels_per_mm

    return properties

# ============================================================================
# INFERENCE
# ============================================================================

def run_inference(
    predictor,
    image_path: str,
    output_dir: Path,
    pixels_per_mm: float = None,
    save_visualization: bool = True,
    save_masks: bool = True,
    save_data: bool = True
) -> Dict:
    """
    Run inference on a single image.

    Returns:
        Dictionary with detection results
    """
    print(f"\nProcessing: {image_path}")

    # Load image
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Could not load image: {image_path}")

    # Run inference
    outputs = predictor(image)
    instances = outputs["instances"].to("cpu")

    # Extract detections
    num_detections = len(instances)
    print(f"  Detected {num_detections} objects")

    # Process each detection
    detections = []
    for i in range(num_detections):
        # Get mask
        mask = instances.pred_masks[i].numpy().astype(np.uint8) * 255
        score = float(instances.scores[i])
        class_id = int(instances.pred_classes[i])
        class_name = ["droplet", "ligament"][class_id]

        # Calculate properties
        properties = calculate_droplet_properties(mask, pixels_per_mm)
        properties['score'] = score
        properties['class_id'] = class_id
        properties['class_name'] = class_name

        detections.append(properties)

        print(f"    {i+1}. {class_name} (score: {score:.3f}, area: {properties['area_pixels']:.1f} px²)")

    # Save visualization
    if save_visualization:
        vis_path = output_dir / "visualizations" / f"{Path(image_path).stem}_result.png"
        vis_path.parent.mkdir(parents=True, exist_ok=True)

        v = Visualizer(
            image[:, :, ::-1],  # BGR to RGB
            MetadataCatalog.get("spray_train"),
            scale=1.0,
            instance_mode=ColorMode.IMAGE_BW  # Colored masks on grayscale image
        )
        vis_output = v.draw_instance_predictions(instances)
        cv2.imwrite(str(vis_path), vis_output.get_image()[:, :, ::-1])
        print(f"  [OK] Visualization saved: {vis_path}")

    # Save individual masks
    if save_masks:
        masks_subdir = output_dir / "masks" / Path(image_path).stem
        masks_subdir.mkdir(parents=True, exist_ok=True)

        for i, detection in enumerate(detections):
            # Reconstruct mask from properties (we need to get it from instances)
            mask = instances.pred_masks[i].numpy().astype(np.uint8) * 255
            mask_path = masks_subdir / f"{detection['class_name']}_{i+1}_mask.png"
            cv2.imwrite(str(mask_path), mask)

        print(f"  [OK] Masks saved to: {masks_subdir}")

    # Save numerical data
    if save_data:
        data_path = output_dir / "data" / f"{Path(image_path).stem}_results.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)

        results = {
            'image_path': str(image_path),
            'timestamp': datetime.now().isoformat(),
            'num_detections': num_detections,
            'pixels_per_mm': pixels_per_mm,
            'detections': detections
        }

        with open(data_path, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"  [OK] Data saved: {data_path}")

    return {
        'image_path': str(image_path),
        'num_detections': num_detections,
        'detections': detections
    }

def process_images(
    image_paths: List[str],
    model_path: str,
    output_dir: Path,
    score_threshold: float = 0.5,
    nms_threshold: float = 0.3,
    pixels_per_mm: float = None
):
    """Process multiple images"""

    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "visualizations").mkdir(exist_ok=True)
    (output_dir / "masks").mkdir(exist_ok=True)
    (output_dir / "data").mkdir(exist_ok=True)

    # Setup predictor
    predictor, cfg = setup_predictor(model_path, score_threshold, nms_threshold)

    # Process each image
    all_results = []
    for image_path in image_paths:
        try:
            result = run_inference(
                predictor,
                image_path,
                output_dir,
                pixels_per_mm=pixels_per_mm
            )
            all_results.append(result)
        except Exception as e:
            print(f"  ERROR processing {image_path}: {e}")

    # Save summary
    summary_path = output_dir / "summary.json"
    summary = {
        'timestamp': datetime.now().isoformat(),
        'model_path': model_path,
        'score_threshold': score_threshold,
        'nms_threshold': nms_threshold,
        'pixels_per_mm': pixels_per_mm,
        'total_images': len(image_paths),
        'processed_images': len(all_results),
        'results': all_results
    }

    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print("Inference Complete!")
    print(f"{'='*60}")
    print(f"Processed {len(all_results)}/{len(image_paths)} images")
    print(f"Results saved to: {output_dir}")
    print(f"Summary: {summary_path}")
    print(f"{'='*60}\n")

# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run Detectron2 inference on images")
    parser.add_argument("--model", type=str, default=MODEL_PATH,
                       help="Path to trained model (.pth file)")
    parser.add_argument("--images", type=str, nargs="+", required=True,
                       help="Path(s) to image file(s) or directory")
    parser.add_argument("--output", type=str, default=str(OUTPUT_DIR),
                       help="Output directory")
    parser.add_argument("--threshold", type=float, default=SCORE_THRESHOLD,
                       help="Detection score threshold (0.0-1.0)")
    parser.add_argument("--nms-threshold", type=float, default=0.3,
                       help="NMS threshold for removing overlapping detections (0.0-1.0, lower=more aggressive)")
    parser.add_argument("--pixels-per-mm", type=float, default=None,
                       help="Calibration: pixels per millimeter (for size calculation)")

    args = parser.parse_args()

    # Collect image paths and determine input folder name
    image_paths = []
    input_folder_name = None

    for path_str in args.images:
        path = Path(path_str)
        if path.is_file():
            image_paths.append(str(path))
            # Extract folder name from file path
            if input_folder_name is None:
                input_folder_name = path.parent.name
        elif path.is_dir():
            # Add all images from directory
            image_paths.extend([str(p) for p in path.glob("*.png")])
            image_paths.extend([str(p) for p in path.glob("*.jpg")])
            image_paths.extend([str(p) for p in path.glob("*.jpeg")])
            # Extract folder name from directory path
            if input_folder_name is None:
                input_folder_name = path.name
        else:
            print(f"Warning: {path_str} not found, skipping")

    if len(image_paths) == 0:
        print("ERROR: No images found!")
        return

    print(f"Found {len(image_paths)} image(s) to process")

    # Create timestamped output directory
    if args.output == str(OUTPUT_DIR):  # Using default output
        # Create timestamped folder based on input folder name
        if input_folder_name:
            timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
            output_base = Path(r"D:\Experiments\AI\InferenceTests")
            output_dir = output_base / f"{input_folder_name}_{timestamp}"
        else:
            output_dir = Path(args.output)
    else:
        output_dir = Path(args.output)

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")

    # Process images
    process_images(
        image_paths,
        args.model,
        output_dir,
        args.threshold,
        args.nms_threshold,
        args.pixels_per_mm
    )

if __name__ == "__main__":
    main()
```

---

## 2. Training script — canonical (root) `train_detectron2.py`

`TRAINING_SETUP.md` confirms this is the one actually run (`python
train_detectron2.py`); the `AI/Training_Analysis/` copy is an older,
near-duplicate. File is 1289 lines total — cut the `ProgressTracker` class
(plotting/logging, ~466 lines), `ProgressTrainer`'s custom eval/viz methods
(~220 lines), `plot_learning_rate_schedule()`, the `retry_file_io` decorator
utility, and `main()` CLI glue (~70 lines): none of that touches image
size/scaling/augmentation/file-format writing beyond matplotlib PNG plots and
Detectron2's own `.pth`/`.json` checkpoint writes via `DefaultTrainer` hooks.
Kept: imports, all config constants, `setup_dataset()`, `setup_config()`
(anchors + INPUT sizing lives here — all inherited from the base config,
never overridden), and the full `RLEDatasetMapper` (the only place image
transforms/masks are actually applied).

### Imports + constants

```python
import csv
import os
import json
import time
from datetime import datetime
from pathlib import Path
from functools import wraps

import numpy as np
import torch
from detectron2.engine import DefaultTrainer
from detectron2.config import get_cfg
from detectron2 import model_zoo
from detectron2.data import MetadataCatalog, DatasetCatalog
from detectron2.data.datasets import register_coco_instances
from detectron2.data import DatasetMapper
from detectron2.data import detection_utils as utils
from detectron2.data.transforms import apply_transform_gens
from detectron2.structures import BitMasks, Instances, Boxes
from detectron2.utils.logger import setup_logger
from detectron2.evaluation import COCOEvaluator, inference_on_dataset
from detectron2.data import build_detection_test_loader, get_detection_dataset_dicts
from detectron2.utils.visualizer import Visualizer
from PIL import Image
from pycocotools import mask as coco_mask
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from tqdm import tqdm

# --- Final training options (from hyperparameter sweep) ---
BATCH_SIZE = 2
BASE_LEARNING_RATE = 0.0025
ANCHOR_SIZES = [[8, 16, 32, 64]]  # FPN anchor sizes (one list per level; same for all here)
WARMUP_ITERS = 1000
LR_DECAY_TYPE = "cosine"  # "cosine" | "step" (drops at 60%/80%) | "none"

# --- Dataset paths ---
DATASET_NAME = "spray_train"
ANNOTATIONS_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\blur_annotations.json"
IMAGES_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\images"

# --- Training length and output ---
NUM_EPOCHS = 1
MAX_ITER = 78000  # ~80k full run; None = derived from NUM_EPOCHS
QUICK_TEST_ITERATIONS = None
OUTPUT_BASE_DIR = r"D:\Experiments\AI"
CHECKPOINT_INTERVAL = 10000

# --- Validation ---
VALIDATION_SPLIT = 0.1
VALIDATION_INTERVAL = 500
VALIDATION_SIZE = 20
NUM_VIZ_IMAGES = 5
VIZ_SCORE_THRESHOLD = 0.5

# --- Resume ---
RESUME_FROM_MODEL = None
```

### `setup_dataset()` and `setup_config()`

```python
def setup_dataset():
    """Register the COCO dataset and split into train/validation"""
    print(f"\n{'='*60}")
    print("Registering Dataset")
    print(f"{'='*60}")

    # Check if images directory exists
    if not os.path.exists(IMAGES_PATH):
        raise FileNotFoundError(f"Images directory not found: {IMAGES_PATH}")

    # Check for annotation file (try specified path first, then alternatives)
    annotations_path = Path(ANNOTATIONS_PATH)
    if not annotations_path.exists():
        # Try common alternative names in the same directory
        alt_names = ["annotations.json", "blur_annotations.json"]
        annotations_dir = annotations_path.parent
        found = False
        for alt_name in alt_names:
            alt_path = annotations_dir / alt_name
            if alt_path.exists():
                print(f"Found alternative annotation file: {alt_path}")
                annotations_path = alt_path
                found = True
                break
        if not found:
            raise FileNotFoundError(f"Annotations file not found: {ANNOTATIONS_PATH} (also tried: {', '.join(alt_names)})")

    # Register full dataset first
    register_coco_instances(
        DATASET_NAME,
        {},
        str(annotations_path),
        IMAGES_PATH
    )

    # Set metadata for visualization
    MetadataCatalog.get(DATASET_NAME).set(thing_classes=["droplet", "ligament"])

    # Get dataset info
    dataset_dicts = DatasetCatalog.get(DATASET_NAME)
    print(f"[OK] Dataset registered: {DATASET_NAME}")
    print(f"[OK] Total number of images: {len(dataset_dicts)}")

    # Split into train and validation sets
    # Use a fixed seed for reproducibility, but shuffle for randomness
    rng = np.random.default_rng(42)  # Fixed seed for reproducibility
    indices = np.arange(len(dataset_dicts))
    rng.shuffle(indices)

    if VALIDATION_SIZE is not None and VALIDATION_SIZE > 0:
        # Exactly VALIDATION_SIZE images for validation, rest for train
        n_val = min(VALIDATION_SIZE, len(indices) - 1)  # keep at least 1 for train
        if n_val < 1:
            n_val = 1
        val_indices = indices[-n_val:]
        train_indices = indices[:-n_val]
        print(f"[OK] Validation: exactly {n_val} images (VALIDATION_SIZE={VALIDATION_SIZE})")
    else:
        split_idx = int(len(dataset_dicts) * (1 - VALIDATION_SPLIT))
        train_indices = indices[:split_idx]
        val_indices = indices[split_idx:]

    # Create train and validation datasets (disjoint: no image in both)
    train_dicts = [dataset_dicts[i] for i in train_indices]
    val_dicts = [dataset_dicts[i] for i in val_indices]

    # Register TRAIN-only dataset (so the model never sees val images during training)
    TRAIN_DATASET_NAME = f"{DATASET_NAME}_train"
    DatasetCatalog.register(TRAIN_DATASET_NAME, lambda t=train_dicts: t)
    MetadataCatalog.get(TRAIN_DATASET_NAME).set(thing_classes=["droplet", "ligament"])

    # Register validation dataset (held out, never used for training)
    VAL_DATASET_NAME = f"{DATASET_NAME}_val"
    DatasetCatalog.register(VAL_DATASET_NAME, lambda v=val_dicts: v)
    MetadataCatalog.get(VAL_DATASET_NAME).set(thing_classes=["droplet", "ligament"])

    print(f"[OK] Training images: {len(train_dicts)} (held out from val, no overlap)")
    print(f"[OK] Validation images: {len(val_dicts)} ({len(val_dicts)/len(dataset_dicts)*100:.1f}%)")

    # Verify a few image files exist (check first few)
    if len(train_dicts) > 0:
        sample_image = train_dicts[0]
        sample_path = os.path.join(IMAGES_PATH, sample_image["file_name"])
        if os.path.exists(sample_path):
            print(f"[OK] Sample image verified: {sample_image['file_name']}")
        else:
            print(f"[WARNING] Sample image not found: {sample_path}")
            print(f"  Make sure image filenames in JSON match actual files")

    return train_dicts, val_dicts, len(train_dicts)

def setup_config(output_dir, num_train_images, resume_from=None):
    """Configure Detectron2"""
    print(f"\n{'='*60}")
    print("Setting up Configuration")
    print(f"{'='*60}")

    # MAX_ITER: 1) QUICK_TEST_ITERATIONS if set, 2) else MAX_ITER if set, 3) else NUM_EPOCHS * (num_train // BATCH_SIZE)
    global MAX_ITER
    iterations_per_epoch = num_train_images // BATCH_SIZE
    if QUICK_TEST_ITERATIONS is not None:
        MAX_ITER = QUICK_TEST_ITERATIONS
        print(f"[OK] Quick test: MAX_ITER = {MAX_ITER}")
    elif MAX_ITER is not None:
        print(f"[OK] MAX_ITER set explicitly: {MAX_ITER}")
    else:
        MAX_ITER = NUM_EPOCHS * iterations_per_epoch

    # Decay steps for "step" LR schedule (60% and 80% of training)
    if LR_DECAY_TYPE == "step":
        decay_step_1 = int(MAX_ITER * 0.6)
        decay_step_2 = int(MAX_ITER * 0.8)

    print(f"[OK] Training dataset size: {num_train_images} images")
    print(f"[OK] Batch size: {BATCH_SIZE} images per iteration")
    print(f"[OK] Iterations per epoch: {iterations_per_epoch} ({num_train_images} images / {BATCH_SIZE})")
    print(f"[OK] Number of epochs: {NUM_EPOCHS}")
    print(f"[OK] Total iterations: {MAX_ITER} ({NUM_EPOCHS} epochs x {iterations_per_epoch} iterations)")
    print(f"[OK] Anchors: {ANCHOR_SIZES}")
    print(f"[OK] Warmup: {WARMUP_ITERS} iterations")
    if LR_DECAY_TYPE == "step":
        print(f"[OK] LR decay: step at {decay_step_1} and {decay_step_2} iterations")
    elif LR_DECAY_TYPE == "cosine":
        print(f"[OK] LR decay: cosine")
    else:
        print(f"[OK] LR decay: none (constant after warmup)")

    cfg = get_cfg()

    # Load pre-trained Mask R-CNN config
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )

    # Dataset configuration (train = only train images; val = held-out, never seen during training)
    cfg.DATASETS.TRAIN = (f"{DATASET_NAME}_train",)
    cfg.DATASETS.TEST = (f"{DATASET_NAME}_val",)

    # Data loading
    cfg.DATALOADER.NUM_WORKERS = 2

    # IMPORTANT: Configure for RLE format (not polygon)
    # Detectron2 will automatically handle RLE when loading COCO annotations
    # But we need to ensure the dataset mapper uses the correct format

    # Model weights
    if resume_from and os.path.exists(resume_from):
        # Continue training from existing model
        cfg.MODEL.WEIGHTS = resume_from
        print(f"[OK] Resuming training from: {resume_from}")
    else:
        # Start from COCO pre-trained weights
        cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(
            "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"
        )
        print(f"[OK] Starting from COCO pre-trained weights")

    # Training settings
    cfg.SOLVER.IMS_PER_BATCH = BATCH_SIZE
    cfg.SOLVER.BASE_LR = BASE_LEARNING_RATE
    cfg.SOLVER.MAX_ITER = MAX_ITER
    cfg.SOLVER.WARMUP_ITERS = WARMUP_ITERS

    # LR schedule: cosine, step (60%/80%), or none
    if LR_DECAY_TYPE == "cosine":
        cfg.SOLVER.LR_SCHEDULER_NAME = "WarmupCosineLR"
        cfg.SOLVER.STEPS = ()
        cfg.SOLVER.GAMMA = 0.1  # ignored by cosine
    elif LR_DECAY_TYPE == "step":
        cfg.SOLVER.STEPS = (decay_step_1, decay_step_2)
        cfg.SOLVER.GAMMA = 0.1
    else:  # "none"
        cfg.SOLVER.STEPS = ()
        cfg.SOLVER.GAMMA = 0.1

    # Checkpoint saving
    cfg.SOLVER.CHECKPOINT_PERIOD = CHECKPOINT_INTERVAL

    # Validation - every N iterations
    val_interval = min(VALIDATION_INTERVAL, iterations_per_epoch)
    cfg.TEST.EVAL_PERIOD = val_interval

    # Anchors and ROI heads
    cfg.MODEL.ANCHOR_GENERATOR.SIZES = ANCHOR_SIZES
    cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 128
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2  # droplet and ligament

    # Output
    cfg.OUTPUT_DIR = output_dir
    os.makedirs(output_dir, exist_ok=True)

    print(f"[OK] Learning rate: {BASE_LEARNING_RATE}")
    print(f"[OK] Max iterations: {MAX_ITER}")
    print(f"[OK] Output directory: {output_dir}")
    print(f"[OK] Checkpoint interval: {CHECKPOINT_INTERVAL} iterations")
    print(f"[OK] Validation interval: {val_interval} iterations")

    return cfg
```

**Important:** `INPUT.MIN_SIZE_TRAIN/MAX_SIZE_TRAIN/MIN_SIZE_TEST/MAX_SIZE_TEST`
and `ResizeShortestEdge` are **never overridden anywhere in this file or its
config setup** — `cfg.merge_from_file(model_zoo.get_config_file(...))` pulls
Detectron2's stock defaults straight through:

```
INPUT.MIN_SIZE_TRAIN = (640, 672, 704, 736, 768, 800)
INPUT.MAX_SIZE_TRAIN = 1333
INPUT.MIN_SIZE_TEST  = 800
INPUT.MAX_SIZE_TEST  = 1333
INPUT.RANDOM_FLIP    = "horizontal"
```

`RLEDatasetMapper` (below) subclasses `DatasetMapper` and never touches
`self.tfm_gens`, so it inherits exactly that default transform (ResizeShortestEdge
choice-sampling + horizontal flip) — there is no `RandomCrop`, no
color/brightness/contrast augmentation anywhere in the Detectron2 pipeline.
All domain-randomization (blur, noise, contrast) happens upstream in the
synthetic data generator (section 3), baked into the images before
Detectron2 ever sees them.

### `RLEDatasetMapper` — the only place per-image transforms/mask decoding run

```python
class RLEDatasetMapper(DatasetMapper):
    """Custom dataset mapper that properly handles RLE format annotations"""

    def __init__(self, cfg, is_train=True):
        """Initialize mapper - call parent to set up transforms"""
        super().__init__(cfg, is_train=is_train)

    def __call__(self, dataset_dict):
        """
        Args:
            dataset_dict (dict): Metadata of one image, in Detectron2 Dataset format.
        Returns:
            dict: a format that builtin models in detectron2 accept.
        """
        # Check if image file exists before trying to read
        image_path = dataset_dict["file_name"]
        if not os.path.exists(image_path):
            print(f"[WARNING] Missing image file: {image_path}")
            print(f"  Skipping this image (will be filtered out)")
            # Create a dummy black image so the pipeline doesn't crash
            # This will be filtered out by filter_empty_instances
            dummy_image = np.zeros((dataset_dict.get("height", 800), dataset_dict.get("width", 1280), 3), dtype=np.uint8)
            dataset_dict["image"] = torch.as_tensor(dummy_image.transpose(2, 0, 1).astype("float32"))
            dataset_dict["annotations"] = []
            # Create empty Instances with required fields
            empty_instances = Instances((dataset_dict.get("height", 800), dataset_dict.get("width", 1280)))
            empty_instances.gt_boxes = Boxes(torch.zeros((0, 4), dtype=torch.float32))
            empty_instances.gt_classes = torch.zeros((0,), dtype=torch.int64)
            dataset_dict["instances"] = empty_instances
            return dataset_dict

        # Read image
        try:
            image = utils.read_image(image_path, format=self.image_format)
        except Exception as e:
            print(f"[ERROR] Failed to read image: {image_path}")
            print(f"  Error: {e}")
            # Create dummy image to prevent crash
            dummy_image = np.zeros((dataset_dict.get("height", 800), dataset_dict.get("width", 1280), 3), dtype=np.uint8)
            dataset_dict["image"] = torch.as_tensor(dummy_image.transpose(2, 0, 1).astype("float32"))
            dataset_dict["annotations"] = []
            # Create empty Instances with required fields
            empty_instances = Instances((dataset_dict.get("height", 800), dataset_dict.get("width", 1280)))
            empty_instances.gt_boxes = Boxes(torch.zeros((0, 4), dtype=torch.float32))
            empty_instances.gt_classes = torch.zeros((0,), dtype=torch.int64)
            dataset_dict["instances"] = empty_instances
            return dataset_dict

        utils.check_image_size(dataset_dict, image)

        if "annotations" in dataset_dict:
            # Convert RLE format to numpy arrays (not BitMasks yet)
            annos = []
            for anno in dataset_dict["annotations"]:
                segm = anno.get("segmentation", None)
                if segm is None:
                    continue

                # Check if it's RLE format (dict with "counts" and "size")
                if isinstance(segm, dict) and "counts" in segm and "size" in segm:
                    # Decode RLE to binary mask (numpy array)
                    height, width = segm["size"]
                    rle = {
                        "counts": segm["counts"],
                        "size": [height, width]
                    }
                    mask = coco_mask.decode(rle)
                    if len(mask.shape) == 3:
                        mask = mask.sum(axis=2) > 0
                    # Store as numpy array (HxW) - annotations_to_instances will convert to BitMasks
                    mask = mask.astype(np.uint8)
                    anno["segmentation"] = mask

                annos.append(anno)
            dataset_dict["annotations"] = annos

        # Apply transforms to image
        if hasattr(self, 'tfm_gens') and self.tfm_gens:
            image, transforms = apply_transform_gens(self.tfm_gens, image)
        else:
            transforms = None

        dataset_dict["image"] = torch.as_tensor(image.transpose(2, 0, 1).astype("float32"))

        if "annotations" in dataset_dict:
            # Apply transforms to masks (numpy arrays)
            annos = []
            for anno in dataset_dict["annotations"]:
                segm = anno.get("segmentation", None)
                if isinstance(segm, np.ndarray):
                    # Apply transforms to mask
                    if transforms:
                        mask_transformed = transforms.apply_segmentation(segm)
                    else:
                        mask_transformed = segm
                    anno["segmentation"] = mask_transformed
                annos.append(anno)

            # Create instances with bitmask format
            # annotations_to_instances will convert numpy arrays to BitMasks internally
            instances = utils.annotations_to_instances(
                annos, image.shape[:2], mask_format="bitmask"
            )
            dataset_dict["instances"] = utils.filter_empty_instances(instances)

        return dataset_dict
```

---

## 3. Synthetic data generator — `AI/synthetic_data/conjoined_blur_spray_dataset_generator.py`

Current/most advanced of three variants in that folder (`spray_dataset_generator.py`
is an older, simpler predecessor; `blur_spray_dataset_generator.py` predates
the conjoined-droplet-pair logic). All three share the same core pipeline
below; this is the live one given the "conjoined pairs" experiment showing
up in the config. Trimmed to the image-formation parts as requested — cut:
`_conjoined_pair_center_distance`, `generate_conjoined_droplet_pair_parameters`,
`draw_elliptical_droplet_realistic`, `draw_blurred_background_droplet`,
`draw_straight/curved_ligament_realistic` line-drawing bodies,
`remove_entirely_covered_instances`, `create_instance_mask`,
`extract_contours_from_mask` (occlusion/geometry bookkeeping, not image
formation), and `generate_coco_annotations`, `visualize_instances`,
`create_sidebyside_visualization`, `generate_dataset` (annotation export /
multiprocessing driver / CLI, not pixel formation).

### Output dimensions + relevant constants

```python
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 800
IMAGE_SHAPE = (IMAGE_HEIGHT, IMAGE_WIDTH)

BACKGROUND_INTENSITY_MIN = 240
BACKGROUND_INTENSITY_MAX = 255
LIQUID_INTENSITY_MIN = 20
LIQUID_INTENSITY_MAX = 80

DROPLET_RADIUS_MIN = 2
DROPLET_RADIUS_MAX = 50
DROPLET_POISSON_LAMBDA = 10
DROPLET_SIZE_MU = 2.5      # log-normal mean (log space)
DROPLET_SIZE_SIGMA = 0.8   # log-normal std — heavy tail toward small droplets

LIGAMENT_LENGTH_MIN = 30
LIGAMENT_LENGTH_MAX = 600
LIGAMENT_THICKNESS_MIN = 3
LIGAMENT_THICKNESS_MAX = 50
LIGAMENT_POISSON_LAMBDA = 20

GAUSSIAN_BLUR_SIGMA_MIN = 0.5
GAUSSIAN_BLUR_SIGMA_MAX = 2.0
MOTION_BLUR_LENGTH_MIN = 3
MOTION_BLUR_LENGTH_MAX = 15
NOISE_STD_MIN = 2.0
NOISE_STD_MAX = 8.0
INTENSITY_SCALE_MIN = 0.9
INTENSITY_SCALE_MAX = 1.1
INTENSITY_SHIFT_MIN = -10
INTENSITY_SHIFT_MAX = 10

DROPLET_ABSORPTION_ALPHA_MIN = 80    # max intensity drop at center
DROPLET_ABSORPTION_ALPHA_MAX = 150
DROPLET_ABSORPTION_BETA_MIN = 2.0    # radial falloff rate
DROPLET_ABSORPTION_BETA_MAX = 4.0
DROPLET_EDGE_BLUR_SIGMA_MIN = 0.3
DROPLET_EDGE_BLUR_SIGMA_MAX = 1.5
HALO_INTENSITY_BOOST = 5
HALO_WIDTH_FACTOR = 0.15
BACKGROUND_GRADIENT_STRENGTH = 10
BACKGROUND_NOISE_STD = 3.0

BACKGROUND_DROPLET_POISSON_LAMBDA = 50    # out-of-focus layer, NOT annotated
BACKGROUND_DROPLET_SIZE_MU = 1.44
BACKGROUND_DROPLET_SIZE_SIGMA = 1.2
BACKGROUND_DROPLET_BLUR_SIGMA_MIN = 0.5
BACKGROUND_DROPLET_BLUR_SIGMA_MAX = 8.0
BACKGROUND_DROPLET_OPACITY = 0.6
BACKGROUND_DROPLET_IN_FOCUS_PROB = 0.15
BACKGROUND_DROPLET_IN_FOCUS_BLUR_THRESHOLD = 8.0

DROPLET_CIRCULARITY_THRESHOLD = 0.85
MIN_DROPLET_DIAMETER = 15.0
MIN_DROPLET_VISIBILITY_RATIO = 0.15
MIN_DROPLET_CONTRAST = 2.0

CONJOINED_DROPLET_FROM_LIGAMENT_PROB = 0.50
CONJOINED_DROPLET_TINY_JOIN_FRAC_MIN = 0.02
CONJOINED_DROPLET_TINY_JOIN_FRAC_MAX = 0.06
CONJOINED_DROPLET_STRONG_JOIN_FRAC_MIN = 0.15
CONJOINED_DROPLET_STRONG_JOIN_FRAC_MAX = 0.50
CONJOINED_DROPLET_STRONG_OVERLAP_PROB = 0.8
CONJOINED_DROPLET_MAX_PLACEMENT_TRIES = 50

CATEGORY_DROPLET = 1
CATEGORY_LIGAMENT = 2
```

### Droplet size sampling — `generate_droplet_parameters`

```python
def generate_droplet_parameters(rng, image_shape):
    height, width = image_shape
    margin = 60
    x = rng.integers(margin, width - margin)
    y = rng.integers(margin, height - margin)
    center = (x, y)

    # Log-normal size distribution — many small, few large droplets
    log_radius = rng.normal(DROPLET_SIZE_MU, DROPLET_SIZE_SIGMA)
    radius = np.exp(log_radius)
    radius = np.clip(radius, DROPLET_RADIUS_MIN, DROPLET_RADIUS_MAX)

    if rng.random() < 0.75:
        return {'type': 'circular', 'center': center, 'radius': radius}
    else:
        log_major = rng.normal(DROPLET_SIZE_MU, DROPLET_SIZE_SIGMA)
        major_axis = np.clip(np.exp(log_major), DROPLET_RADIUS_MIN, DROPLET_RADIUS_MAX * 1.5)
        minor_axis = rng.uniform(DROPLET_RADIUS_MIN, major_axis)
        axes = (int(major_axis), int(minor_axis))
        angle = rng.uniform(0, 360)
        return {'type': 'elliptical', 'center': center, 'axes': axes, 'angle': angle}
```

### Droplet rendering — absorption/defocus model — `draw_circular_droplet_realistic`

```python
def draw_circular_droplet_realistic(image, center, radius, background_intensity, rng, apply_edge_blur=True):
    height, width = image.shape
    cx, cy = center
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, center, int(radius), 255, -1)

    dist_transform = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    normalized_dist = dist_transform / (radius + 1e-6)
    normalized_dist = np.clip(normalized_dist, 0, 1)

    # Absorption model: I = background - alpha * exp(-beta * normalized_distance)
    alpha = rng.uniform(DROPLET_ABSORPTION_ALPHA_MIN, DROPLET_ABSORPTION_ALPHA_MAX)
    beta = rng.uniform(DROPLET_ABSORPTION_BETA_MIN, DROPLET_ABSORPTION_BETA_MAX)
    intensity_profile = background_intensity - alpha * np.exp(-beta * normalized_dist)
    intensity_profile = np.clip(intensity_profile, 0, 255)

    droplet_region = mask > 0
    image[droplet_region] = intensity_profile[droplet_region].astype(np.uint8)

    if rng.random() < 0.6:  # bright rim/halo
        kernel_size = max(1, int(radius * HALO_WIDTH_FACTOR))
        if kernel_size % 2 == 0: kernel_size += 1
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        dilated = cv2.dilate(mask, kernel, iterations=1)
        edge_mask = dilated - mask
        image[edge_mask > 0] = np.minimum(
            image[edge_mask > 0].astype(np.float32) + HALO_INTENSITY_BOOST * 0.3, 255
        ).astype(np.uint8)

    if apply_edge_blur:  # size-dependent soft-edge blur
        blur_sigma = radius * rng.uniform(0.02, 0.05)
        blur_sigma = np.clip(blur_sigma, 0.1, 0.5)
        ksize = int(6 * blur_sigma + 1)
        if ksize % 2 == 0: ksize += 1
        if ksize >= 3:
            blurred_region = cv2.GaussianBlur(image, (ksize, ksize), blur_sigma)
            image[droplet_region] = blurred_region[droplet_region]
    return image
```

`draw_elliptical_droplet_realistic` and `draw_blurred_background_droplet` use
the same absorption math, applied to an ellipse mask / with heavier defocus
blur for the out-of-focus background layer — cut for length, same pattern.

### Ligament generation — `generate_ligament_parameters`

```python
def generate_ligament_parameters(rng, image_shape):
    height, width = image_shape
    margin = 60
    start_x = rng.integers(margin, width - margin)
    start_y = rng.integers(margin, height - margin)
    start = (start_x, start_y)
    thickness = rng.integers(LIGAMENT_THICKNESS_MIN, LIGAMENT_THICKNESS_MAX + 1)

    if rng.random() < 0.05:  # 5% straight
        length = rng.uniform(LIGAMENT_LENGTH_MIN, LIGAMENT_LENGTH_MAX)
        angle = rng.uniform(0, 2 * np.pi)
        end_x = int(start_x + length * np.cos(angle))
        end_y = int(start_y + length * np.sin(angle))
        end_x = max(margin, min(width - margin, end_x))
        end_y = max(margin, min(height - margin, end_y))
        return {'type': 'straight', 'start': start, 'end': (end_x, end_y), 'thickness': thickness}
    else:  # 95% curved, multi-segment
        num_points = rng.integers(4, 11)
        control_points = [start]
        current_x, current_y = start_x, start_y
        current_angle = rng.uniform(0, 2 * np.pi)
        total_length = rng.uniform(LIGAMENT_LENGTH_MIN, LIGAMENT_LENGTH_MAX)
        avg_segment_length = total_length / (num_points - 1)

        for i in range(num_points - 1):
            segment_length = avg_segment_length * rng.uniform(0.5, 1.5)
            angle_change = rng.normal(0, np.pi / 3)
            angle_change = np.clip(angle_change, -2 * np.pi / 3, 2 * np.pi / 3)
            current_angle += angle_change
            if rng.random() < 0.3:  # 30% chance of sharp turn
                current_angle = rng.uniform(0, 2 * np.pi)
            next_x = int(current_x + segment_length * np.cos(current_angle))
            next_y = int(current_y + segment_length * np.sin(current_angle))
            next_x = max(margin, min(width - margin, next_x))
            next_y = max(margin, min(height - margin, next_y))
            if next_x != current_x or next_y != current_y:
                control_points.append((next_x, next_y))
                current_x, current_y = next_x, next_y

        if len(control_points) < 2:
            angle = rng.uniform(0, 2 * np.pi)
            length = rng.uniform(LIGAMENT_LENGTH_MIN / 2, LIGAMENT_LENGTH_MAX / 2)
            end_x = max(margin, min(width - margin, int(start_x + length * np.cos(angle))))
            end_y = max(margin, min(height - margin, int(start_y + length * np.sin(angle))))
            control_points.append((end_x, end_y))

        return {'type': 'curved', 'control_points': control_points, 'thickness': thickness}
```

### Background — `create_realistic_background`

```python
def create_realistic_background(image_shape, base_intensity, rng):
    height, width = image_shape
    background = np.full((height, width), base_intensity, dtype=np.float32)

    y_coords, x_coords = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')
    gradient_strength = rng.uniform(0.2, 0.6) * BACKGROUND_GRADIENT_STRENGTH
    angle = rng.uniform(0, 2 * np.pi)
    wavelength_x = rng.uniform(width * 0.5, width * 2.0)
    wavelength_y = rng.uniform(height * 0.5, height * 2.0)
    phase = rng.uniform(0, 2 * np.pi)
    gradient = gradient_strength * np.sin(
        2 * np.pi * (x_coords * np.cos(angle) / wavelength_x +
                     y_coords * np.sin(angle) / wavelength_y) + phase
    )
    background += gradient

    noise = rng.normal(0, BACKGROUND_NOISE_STD * 0.7, (height, width))
    background += noise
    background = np.clip(background, BACKGROUND_INTENSITY_MIN, 255)
    return background.astype(np.uint8)
```

### Domain randomization — blur / motion blur / noise / contrast

```python
def apply_gaussian_blur(image, rng):
    sigma = rng.uniform(GAUSSIAN_BLUR_SIGMA_MIN, GAUSSIAN_BLUR_SIGMA_MAX)
    ksize = int(6 * sigma + 1)
    if ksize % 2 == 0: ksize += 1
    return cv2.GaussianBlur(image, (ksize, ksize), sigma)

def apply_motion_blur(image, rng):
    length = rng.integers(MOTION_BLUR_LENGTH_MIN, MOTION_BLUR_LENGTH_MAX + 1)
    angle = rng.uniform(0, 360)
    kernel = np.zeros((length, length), dtype=np.float32)
    kernel[int((length - 1) / 2), :] = np.ones(length, dtype=np.float32)
    kernel = kernel / length
    M = cv2.getRotationMatrix2D((length / 2, length / 2), angle, 1.0)
    kernel = cv2.warpAffine(kernel, M, (length, length))
    return cv2.filter2D(image, -1, kernel)

def add_gaussian_noise(image, rng):
    std = rng.uniform(NOISE_STD_MIN, NOISE_STD_MAX)
    noise = rng.normal(0, std, image.shape).astype(np.float32)
    noisy = image.astype(np.float32) + noise
    return np.clip(noisy, 0, 255).astype(np.uint8)

def apply_intensity_variation(image, rng):
    scale = rng.uniform(INTENSITY_SCALE_MIN, INTENSITY_SCALE_MAX)
    shift = rng.integers(INTENSITY_SHIFT_MIN, INTENSITY_SHIFT_MAX + 1)
    adjusted = image.astype(np.float32) * scale + shift
    return np.clip(adjusted, 0, 255).astype(np.uint8)
```

### Per-image pipeline order — inside `generate_synthetic_image`

```python
bg_intensity = rng.integers(BACKGROUND_INTENSITY_MIN, BACKGROUND_INTENSITY_MAX + 1)
image = create_realistic_background(image_shape, bg_intensity, rng)
image = image.astype(np.float32)
# ... background out-of-focus droplet layer, then foreground droplets/ligaments/
#     conjoined pairs drawn on top, with incremental occlusion-based instance removal ...
image = np.clip(image, 0, 255).astype(np.uint8)

if rng.random() < 0.3: image = apply_gaussian_blur(image, rng)   # 30% extra blur
if rng.random() < 0.2: image = apply_motion_blur(image, rng)    # 20% motion blur
if rng.random() < 0.4: image = add_gaussian_noise(image, rng)   # 40% extra noise
return image, instances
```

File write (`generate_single_image_worker`): `cv2.imwrite(str(image_path), image)`
— plain PNG, no resizing (images are written at the native `IMAGE_SHAPE` =
1280×800; all size variation Detectron2 sees comes from its own
`ResizeShortestEdge` at train time, per section 2).

---

## 4. Acquisition/saving code — `src/gui/GUI_Clean.py`

### `PhantomController` — the Phantom SDK wrapper

Connect, configure, arm/trigger, and both save paths (`.cine` via SDK, and
the RAM→TIFF path actually used every trigger):

```python
import pyphantom as _pyph
from pyphantom import Phantom, utils, cine

class PhantomController:
    def __init__(self):
        self.ph = None; self.cam = None; self.current_cine = None
        self.is_connected = False; self.is_recording = False
        self.recording_started = False; self.is_armed = False
        self._fps = 1000.0

    def connect(self, ip_address=None, camera_index=0):
        if not PHANTOM_SDK_AVAILABLE:
            raise RuntimeError("Phantom SDK not installed")
        import pyphantom as _pyph
        self.ph = Phantom()
        real_count = self.ph.camera_count
        self.ph.discover(print_list=False)  # auto-adds simulated camera if none found
        if real_count == 0:
            raise RuntimeError("No Phantom camera found on network")
        cam_index = min(camera_index, self.ph.camera_count - 1)
        try:
            self.cam = self.ph.Camera(cam_index)
        except Exception as e:
            if "requested parameter is missing" in str(e).lower() or "missing" in str(e).lower():
                # Camera.__init__ tries to get the live cine handle, which requires
                # armed/live state — bypass __init__ when the camera isn't live yet.
                cam = object.__new__(_pyph.Camera)
                cam._camera_num = cam_index
                cam._live_cine = None
                self.cam = cam
            else:
                raise
        self.is_connected = True
        return True

    def configure(self, width, height, fps, exposure_us, partition_count=1, post_trigger_frames=0, exp_index=0):
        if not self.is_connected: raise RuntimeError("Camera not connected")
        self.cam.resolution = (int(width), int(height))
        self.cam.partition_count = int(partition_count)
        self.cam.post_trigger_frames = int(post_trigger_frames)
        self.cam.frame_rate = float(fps)
        actual_fps = self.cam.frame_rate
        self._fps = actual_fps
        max_exp = (1.0 / actual_fps) * 1e6
        if exposure_us >= max_exp:
            raise RuntimeError(f"Exposure {exposure_us}μs exceeds max {max_exp:.1f}μs")
        self.cam.exposure = float(exposure_us)
        if exp_index != 0:
            self.cam.exp_index = int(exp_index)
        return {'resolution': self.cam.resolution, 'frame_rate': actual_fps, 'exposure': self.cam.exposure}

    def start_recording(self):
        self.cam.record(); self.is_recording = True; self.is_armed = True
        self.recording_started = False; return True

    def trigger(self):
        self.cam.trigger(); self.recording_started = True; self.is_armed = False; return True

    # A CINE save is abandoned only when progress genuinely stops, never on a fixed
    # ceiling: a large capture can legitimately run far longer while still writing.
    CINE_STALL_TIMEOUT_S = 120.0
    CINE_ABSOLUTE_MAX_S  = 6 * 3600.0

    @staticmethod
    def _eta_seconds(elapsed, done, total):
        if done <= 0 or elapsed <= 0 or total <= 0 or done >= total:
            return None
        return max(0.0, elapsed * (total - done) / done)

    def save_recording(self, output_path, cine_index=1, file_format='cine', frame_range=None, progress_cb=None):
        self.current_cine = self.cam.Cine(cine_index)
        fmt_map = {'cine': 0, 'tiff': -8, 'tif': -8, 'avi': -7}
        self.current_cine.save_type = utils.FileTypeEnum(fmt_map.get(file_format, 0))
        r = self.current_cine.range
        if frame_range is None:
            self.current_cine.save_range = utils.FrameRange(r.first_image, r.last_image)
        else:
            self.current_cine.save_range = utils.FrameRange(
                max(r.first_image, frame_range[0]),
                min(r.last_image,  frame_range[1]))
        self.current_cine.save_name = output_path
        # SDK's blocking save() has a known bug: throws even on success.
        # Use save_non_blocking() and poll save_percentage instead.
        self.current_cine._save_percentage = -1
        self.current_cine.save_non_blocking()
        started = time.time()
        hard_deadline = started + self.CINE_ABSOLUTE_MAX_S
        last_pct, last_change = -1, started
        while time.time() < hard_deadline:
            pct = self.current_cine.save_percentage
            now = time.time()
            if pct >= 100:
                if progress_cb: progress_cb(100, 0.0)
                break
            if pct != last_pct:
                last_change = now; last_pct = pct
                if progress_cb:
                    progress_cb(max(0, pct), self._eta_seconds(now - started, pct, 100))
            elif pct >= 90 and now - last_change > 30.0:
                if progress_cb: progress_cb(100, 0.0)
                break  # stalled near end — assume complete
            elif now - last_change > self.CINE_STALL_TIMEOUT_S:
                raise RuntimeError(f"CINE save stalled at {pct}% — no progress for {self.CINE_STALL_TIMEOUT_S:.0f} s")
            time.sleep(0.25)
        else:
            raise RuntimeError(f"CINE save exceeded {self.CINE_ABSOLUTE_MAX_S / 3600:.0f} h (progress: {self.current_cine.save_percentage}%)")
        return True

    def save_tiffs_from_ram(self, output_dir, tiff_prefix='frame', cine_index=1, frame_range=None, progress_cb=None):
        """Read frames from camera RAM and write TIFFs directly — no SDK save() involved."""
        c = self.cam.Cine(cine_index)
        r = c.range
        if frame_range is not None:
            f_start = max(r.first_image, frame_range[0])
            f_end   = min(r.last_image,  frame_range[1])
        else:
            f_start, f_end = r.first_image, r.last_image
        total = max(1, f_end - f_start + 1)
        started = time.time()
        last_pct = -1
        for i, (_, img) in enumerate(c.get_imagessave(utils.FrameRange(f_start, f_end + 1))):
            cv2.imwrite(os.path.join(output_dir, f"{tiff_prefix}{i:06d}.tif"), img)
            if progress_cb:
                done = i + 1
                pct  = int(done / total * 100)
                if pct != last_pct:  # only emit on % change — avoids flooding Qt event loop
                    last_pct = pct
                    progress_cb(pct, self._eta_seconds(time.time() - started, done, total))
        return True

    def abort(self):
        if self.is_recording:
            self.cam.clear_ram(); self.is_recording = False; self.recording_started = False
        self.is_armed = False
        return True

    def ping(self):
        try: _ = self.cam.frame_rate; return True
        except Exception: self.is_connected = False; return False

    def disconnect(self):
        try:
            if self.cam: self.cam.close(); self.cam = None
            if self.ph: self.ph.close(); self.ph = None
        except Exception: pass
        self.is_connected = False; self.is_recording = False
```

### `_cam_trigger` — GUI method wired to the trigger button

Arms status UI, resolves the run folder, triggers the camera, waits for
settle time, saves `.cine` (optional) then TIFFs from RAM, copies the
brightest frame, and (new this session) auto-kicks the lamella batch:

```python
def _cam_trigger(self):
    """Fire the trigger — freeze the ring buffer and save pre+post window."""
    if not self.phantom: return
    run_pipeline  = self._pipeline_check.isChecked()
    save_video    = self._cam_save_video_chk.isChecked()
    # Derive from the live fields so the values on screen are the ones used,
    # falling back to whatever Apply Config last pushed to the camera.
    pre_frames, post_frames = self._cam_frame_counts()
    if pre_frames  <= 0: pre_frames  = self._cam_pre_frames
    if post_frames <= 0: post_frames = self._cam_post_frames
    run_folder    = self._run_folder
    ts = datetime.now().strftime("%H%M%S")

    # Update UI immediately so the user knows the trigger was received
    self._cam_trigger_btn.setEnabled(False)
    self._cam_arm_btn.setEnabled(False)
    self._cam_arm_status_lbl.setText("Triggered — saving…")
    self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_ORANGE}; font-size:12px;")
    self._set_camera_armed_indicator(CLR_GREEN)

    if run_folder:
        # Mid-experiment: write into the active run folder
        cine_path    = os.path.join(run_folder, "shadowgraph", "raw", "CINE",
                                    f"recording_{ts}.cine")
        tiff_prefix  = os.path.join(run_folder, "shadowgraph", "raw", "TIFFs", "frame")
        tiff_dir     = os.path.join(run_folder, "shadowgraph", "raw", "TIFFs")
        bright_dir   = os.path.join(run_folder, "shadowgraph", "raw", "Brightest_Frame")
        analysis_dir = os.path.join(run_folder, "shadowgraph", "analysis")
    else:
        # Manual trigger — create a new run folder with the same structure
        _now   = datetime.now()
        _lacie = find_lacie_drive()
        _base  = os.path.join(_lacie, "Experiments") if _lacie else os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "experiment_logs", "Experiments")
        _run_folder = os.path.join(
            _base, _now.strftime("%Y"), _now.strftime("%m"),
            _now.strftime("%d"), f"{_now.strftime('%H%M%S')}_Manual")
        for _sub in [os.path.join("shadowgraph", "raw", "CINE"),
                     os.path.join("shadowgraph", "raw", "TIFFs"),
                     os.path.join("shadowgraph", "raw", "Brightest_Frame"),
                     os.path.join("shadowgraph", "analysis"),
                     "cone"]:
            os.makedirs(os.path.join(_run_folder, _sub), exist_ok=True)
        cine_path    = os.path.join(_run_folder, "shadowgraph", "raw", "CINE",
                                    f"recording_{ts}.cine")
        tiff_prefix  = os.path.join(_run_folder, "shadowgraph", "raw", "TIFFs", "frame")
        tiff_dir     = os.path.join(_run_folder, "shadowgraph", "raw", "TIFFs")
        bright_dir   = os.path.join(_run_folder, "shadowgraph", "raw", "Brightest_Frame")
        analysis_dir = os.path.join(_run_folder, "shadowgraph", "analysis")
        # Update the save path label to show where this capture went
        QTimer.singleShot(0, self,
            lambda p=_run_folder: self._cam_save_lbl.setText(f"Saving to: {p}"))

    frame_range = (-pre_frames, post_frames - 1) if pre_frames > 0 else None

    def _brightest_frame(folder):
        import glob, cv2 as _cv2
        tiffs = glob.glob(os.path.join(folder, "*.tif")) + \
                glob.glob(os.path.join(folder, "*.tiff"))
        if not tiffs:
            return None
        best, best_val = None, -1
        for f in tiffs:
            img = _cv2.imread(f, _cv2.IMREAD_UNCHANGED)
            if img is not None:
                val = float(img.mean())
                if val > best_val:
                    best_val, best = val, f
        return best

    def _do_trigger():
        import shutil, glob as _glob
        try:
            QTimer.singleShot(0, self, lambda: self._cam_arm_status_lbl.setText("Triggering…"))
            self.phantom.trigger()
            _trigger_wall = time.time()
            fps_val = float(self._cam_fps.text()) if self._cam_fps.text() else 1000.0
            if self.pressure_data.get('experiment_active') and \
                    self.pressure_data.get('experiment_start_time') is not None:
                _trel = _trigger_wall - self.pressure_data['experiment_start_time']
                self.pressure_data['camera_windows'].append((
                    _trel - pre_frames / fps_val,
                    _trel + post_frames / fps_val,
                ))
            # Fixed settle: post-trigger frames + 2 s for the camera to commit the cine.
            # wait_for_cine() polling was replaced because cam.Cine() can block at the
            # SDK level without raising, leaving the thread stuck indefinitely.
            settle = post_frames / fps_val + 2.0
            QTimer.singleShot(0, self,
                lambda s=settle: self._cam_arm_status_lbl.setText(f"Settling {s:.1f} s…"))
            time.sleep(settle)

            def _progress_reporter(label):
                """Progress callback that also shows a time-remaining estimate."""
                def _cb(pct, eta=None):
                    txt = f"{label} {pct}%"
                    if eta is not None:
                        txt += f" — {self._fmt_eta(eta)} left"
                    QTimer.singleShot(0, self, lambda p=pct, t=txt: (
                        self._cam_save_progress.setValue(p),
                        self._cam_arm_status_lbl.setText(t),
                    ))
                return _cb

            # 1 — save .cine (optional)
            if save_video:
                QTimer.singleShot(0, self, lambda: (
                    self._cam_arm_status_lbl.setText("Saving .cine…"),
                    self._cam_save_progress.setValue(0),
                    self._cam_save_progress.setVisible(True),
                ))
                self.phantom.save_recording(cine_path, file_format='cine',
                                            frame_range=frame_range,
                                            progress_cb=_progress_reporter("Saving .cine"))
                QTimer.singleShot(0, self, lambda: self._cam_save_progress.setValue(0))

            # 2 — read frames from camera RAM and write TIFFs ourselves.
            # This bypasses the SDK's save() which has a known bug that throws
            # an exception even when the save succeeds.
            QTimer.singleShot(0, self, lambda: (
                self._cam_arm_status_lbl.setText("Saving TIFFs…"),
                self._cam_save_progress.setValue(0),
                self._cam_save_progress.setVisible(True),
            ))
            os.makedirs(tiff_dir, exist_ok=True)
            for _old in (_glob.glob(os.path.join(tiff_dir, "*.tif")) +
                         _glob.glob(os.path.join(tiff_dir, "*.tiff"))):
                try: os.remove(_old)
                except OSError: pass
            self.phantom.save_tiffs_from_ram(tiff_dir, tiff_prefix='frame',
                                             frame_range=frame_range,
                                             progress_cb=_progress_reporter("Saving TIFFs"))
            QTimer.singleShot(0, self, lambda: self._cam_save_progress.setVisible(False))

            # 2b — auto-run lamella batch on saved TIFFs if analysis is enabled
            if self._lamella_on:
                _captured_tiff_dir = tiff_dir
                self._last_tiff_dir = _captured_tiff_dir
                QTimer.singleShot(0, self,
                    lambda d=_captured_tiff_dir: self._lamella_run_batch_auto(d))

            # 3 — find brightest frame, copy to Brightest_Frame/
            os.makedirs(bright_dir, exist_ok=True)
            best = _brightest_frame(tiff_dir)
            bright_path = None
            if best:
                bright_path = os.path.join(bright_dir, os.path.basename(best))
                shutil.copy2(best, bright_path)

            QTimer.singleShot(0, self,
                lambda: self._cam_status_lbl.setText("Trigger saved ✓"))

            # 4 — kick off AI in its own thread as soon as brightest frame is known
            if run_pipeline and bright_path:
                QTimer.singleShot(0, self,
                    lambda: self._run_pipeline(bright_dir, analysis_dir))
            elif run_pipeline:
                QTimer.singleShot(0, self,
                    lambda: self._set_status("No frames found for pipeline", CLR_ORANGE))

            # 5 — re-arm automatically so the camera is ready for the next trigger
            QTimer.singleShot(0, self, self._cam_arm)

        except Exception as e:
            err = str(e)
            QTimer.singleShot(0, self, lambda: (
                self._set_status(f"Trigger error: {err}", CLR_RED),
                self._cam_arm_status_lbl.setText("Error — re-arm manually"),
                self._cam_arm_btn.setEnabled(True),
                self._set_camera_armed_indicator("transparent"),
                self._cam_save_progress.setVisible(False),
            ))

    threading.Thread(target=_do_trigger, daemon=True).start()
```

### `src/imaging/mp4_to_tiff.py` — standalone `.cine`/video → TIFF converter (full file, 212 lines)

Used when converting a previously-saved video/cine file rather than going
through the GUI's live RAM path.

```python
# Merge term 1
"""
HPATR MP4 to TIFF Converter
Converts MP4 videos to TIFF frames and finds the brightest frame.
"""
import cv2
import os
import sys
import numpy as np

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import config loader
from config_loader import get_mp4_config

def video_to_tiff_frames(video_path, output_folder):
    """
    Convert MP4 video to individual TIFF frames

    Args:
        video_path (str): Path to the input MP4 video file
        output_folder (str): Folder to save the TIFF frames
    """
    # Check if video file exists
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        return False

    # Create output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)

    # Open the video file
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return False

    # Get video properties
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0

    print(f"Video info:")
    print(f"  Input: {video_path}")
    print(f"  Total frames: {total_frames}")
    print(f"  FPS: {fps:.2f}")
    print(f"  Duration: {duration:.2f} seconds")
    print(f"  Output folder: {output_folder}")
    print(f"\nConverting frames...")

    frame_count = 0
    success = True

    while success:
        # Read a frame
        success, frame = cap.read()

        if success:
            # Create filename with zero-padded frame number
            frame_filename = f"frame_{frame_count:06d}.tiff"
            frame_path = os.path.join(output_folder, frame_filename)

            # Save frame as TIFF
            cv2.imwrite(frame_path, frame)

            # Print progress every 100 frames
            if frame_count % 100 == 0:
                print(f"  Processed frame {frame_count}/{total_frames}")

            frame_count += 1
        else:
            break

    # Release the video capture object
    cap.release()

    print(f"\nConversion complete!")
    print(f"  Total frames saved: {frame_count}")
    print(f"  Frames saved to: {output_folder}")

    return True

def find_brightest_frame(tiff_folder, output_path):
    """
    Find the brightest TIFF frame and save it as 'flashed_output.tiff'

    Args:
        tiff_folder (str): Folder containing TIFF frames
        output_path (str): Path to save the brightest frame
    """
    print(f"\nFinding brightest frame...")
    print(f"  Input folder: {tiff_folder}")
    print(f"  Output: {output_path}")

    # Check if input folder exists
    if not os.path.exists(tiff_folder):
        print(f"Error: TIFF folder not found at {tiff_folder}")
        return False

    # Create output folder if it doesn't exist
    os.makedirs(output_path, exist_ok=True)

    # Get all TIFF files
    tiff_files = [f for f in os.listdir(tiff_folder) if f.lower().endswith('.tiff') or f.lower().endswith('.tif')]

    if not tiff_files:
        print(f"Error: No TIFF files found in {tiff_folder}")
        return False

    print(f"  Found {len(tiff_files)} TIFF files")
    print(f"  Analyzing brightness...")

    brightest_frame = None
    brightest_value = -1
    brightest_filename = None

    # Analyze each frame
    for i, filename in enumerate(tiff_files):
        file_path = os.path.join(tiff_folder, filename)

        # Read the image
        img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)

        if img is not None:
            # Calculate average brightness
            brightness = np.mean(img)

            # Update if this is the brightest so far
            if brightness > brightest_value:
                brightest_value = brightness
                brightest_frame = img
                brightest_filename = filename

            # Show progress every 50 files
            if (i + 1) % 50 == 0:
                print(f"    Analyzed {i + 1}/{len(tiff_files)} files")

    if brightest_frame is not None:
        # Save the brightest frame
        output_file = os.path.join(output_path, "flashed_output.tiff")
        cv2.imwrite(output_file, brightest_frame)

        print(f"\n✅ Brightest frame found and saved!")
        print(f"  Brightest frame: {brightest_filename}")
        print(f"  Average brightness: {brightest_value:.2f}")
        print(f"  Saved to: {output_file}")

        return True
    else:
        print(f"Error: Could not process any TIFF files")
        return False

def main():
    """Main function to run the video conversion and brightest frame detection"""
    print("HPATR MP4 to TIFF Converter + Brightest Frame Finder")
    print("=" * 60)

    # Load config
    config = get_mp4_config()
    default_video_path = config.get('default_video_path', '/Volumes/LaCie/Phantom/Video/5fps_First_Cine_Trial.mp4')
    default_tiff_folder = config.get('default_tiff_folder', '/Volumes/LaCie/Phantom/TIFF_Output')
    default_flashed_output = config.get('default_flashed_output', '/Volumes/LaCie/Phantom/Flashed_Output')

    # Use command line arguments if provided, otherwise use config defaults
    if len(sys.argv) == 3:
        video_path = sys.argv[1]
        output_folder = sys.argv[2]
        print(f"Using command line arguments:")
        print(f"  Video: {video_path}")
        print(f"  Output: {output_folder}")
        print()

        # Convert video to frames
        success = video_to_tiff_frames(video_path, output_folder)
        if not success:
            return

    elif len(sys.argv) == 1:
        print(f"Using config paths:")
        print(f"  Video: {default_video_path}")
        print(f"  TIFF Output: {default_tiff_folder}")
        print(f"  Flashed Output: {default_flashed_output}")
        print()

        # Check if TIFF files already exist
        if os.path.exists(default_tiff_folder) and os.listdir(default_tiff_folder):
            print("TIFF files already exist. Skipping video conversion.")
        else:
            # Convert video to frames
            success = video_to_tiff_frames(default_video_path, default_tiff_folder)
            if not success:
                return

        # Find brightest frame
        success = find_brightest_frame(default_tiff_folder, default_flashed_output)

    else:
        print("Usage options:")
        print("1. Run with config defaults: python mp4_to_tiff.py")
        print("2. Specify paths: python mp4_to_tiff.py <input_video.mp4> <output_folder>")
        print(f"\nConfig defaults:")
        print(f"  Video: {default_video_path}")
        print(f"  TIFF output: {default_tiff_folder}")
        print(f"  Flashed output: {default_flashed_output}")
        print(f"\nTo change defaults, edit config/paths.yaml")
        return

    print("\n[SUCCESS] All operations completed successfully!")

if __name__ == "__main__":
    main()
```

---

## 5. Repo tree (`-L 3`, data/weights/logs/trials excluded)

```
.
./.claude
./.claude/settings.local.json
./AI
./AI/Training_Analysis
./AI/Training_Analysis/check_image_identity.py
./AI/Training_Analysis/evaluate_model.py
./AI/Training_Analysis/inference_detectron2.py
./AI/Training_Analysis/plot_from_metrics.py
./AI/Training_Analysis/setup_training_dataset.py
./AI/Training_Analysis/test_inference_debug.py
./AI/Training_Analysis/train_detectron2.py
./AI/Training_Analysis/verify_installation.py
./AI/Training_Analysis/visualize_coco_results.py
./AI/Training_Analysis/visualize_model_predictions.py
./AI/Validation_100
./AI/evaluate_model.py
./AI/synthetic_data
./AI/synthetic_data/blur_spray_dataset_generator.py
./AI/synthetic_data/conjoined_blur_spray_dataset_generator.py
./AI/synthetic_data/spray_dataset_generator.py
./INFERENCE_GUIDE.md
./README.md
./TRAINING_SETUP.md
./Trials
./activate_conda.ps1
./check_dataset_overlap.py
./check_image_identity.py
./check_sweep_progress.py
./compare_eval_results.py
./compare_training_metrics.py
./config
./config/context
./config/context/Hyperparameter Context.txt
./config/paths.yaml
./config/paths_example.yaml
./convergence_test.py
./data
./data/sample_input
./data/sample_output
./docs
./docs/AI_PIPELINE_PLAN.md
./docs/CLAUDE_Understanding.md
./docs/CODE_SOP.md
./docs/FILE_STRUCTURE_PLAN.md
./docs/FLOWCHART.md
./docs/Full_Workflow.drawio
./docs/LOOP_CLARIFICATION.md
./docs/OPTIMIZATION_EXPLANATIONS.md
./docs/SYSTEM_ARCHITECTURE.md
./docs/TAGUCHI_DATA_PLAN.md
./docs/gradient_descent_example.py
./docs/lamella_ai_plan.md
./docs/numpy_mask_example.py
./docs/water-drop.png
./evaluate_multiple_models.py
./evaluation_results.xlsx
./experiment_logs
./extract_sweep_metrics.py
./hyperparameter_sweep.py
./inference_detectron2.py
./plot_from_metrics.py
./requirements.txt
./serial_log.txt
./setup_training_dataset.py
./src
./src/__init__.py
./src/ai
./src/ai/__init__.py
./src/ai/lamella
./src/ai/process_run.py
./src/config_loader.py
./src/gui
./src/gui/GUI_Clean.py
./src/gui/Pressure_Motor_Portenta.cpp
./src/gui/Windows_Experiment_GUI.py
./src/gui/__init__.py
./src/gui/camera_settings.json
./src/imaging
./src/imaging/__init__.py
./src/imaging/expansion_detection.py
./src/imaging/mp4_to_tiff.py
./src/imaging/save_and_analyse.py
./test_inference_debug.py
./test_lamella.py
./tests
./tests/blur_image_00002.json
./tests/blur_image_00002.tiff
./tests/mock_arduino.py
./train_detectron2.py
./verify_installation.py
./visualize_coco_results.py
./visualize_dennis_vs_claudia.py
./visualize_model_predictions.py
```

## `requirements.txt` (full)

```
# Merge term 1
# HPATR Requirements
# Python package dependencies for HPATR (High-Performance Aerosol Testing & Research)

# Core image processing
opencv-python>=4.5.0
numpy>=1.20.0,<2.0  # NumPy 2.x incompatible with pyphantom (compiled with NumPy 1.x)
matplotlib>=3.3.0
pandas>=1.2.0

# GUI
customtkinter>=5.0.0
Pillow>=8.0.0
openpyxl>=3.0.0

# Serial communication
pyserial>=3.5

# Optional: Phantom SDK (install separately if needed)
# pyphantom>=3.11.11.806  # Install from vendor or pip if available

# Optional: PyVISA for Tektronix AFG1062
# pyvisa>=1.11.0  # Uncomment if using AFG1062

# Config file handling
PyYAML>=5.4.0

# COCO annotation format
pycocotools>=2.0.0
```

---

## Notes / gaps to flag in the other conversation

- **`requirements.txt` is stale/incomplete.** It lists `customtkinter` (the
  old GUI toolkit) but not `PySide6` (what `GUI_Clean.py` actually uses),
  and has no `torch`, `detectron2`, or `segmentation-models-pytorch` at all
  — these are presumably installed manually on the Windows GPU training box.
- **Two near-duplicate copies each** of `inference_detectron2.py` and
  `train_detectron2.py` exist (repo root vs. `AI/Training_Analysis/`), with
  slightly different `MODEL_PATH`/config-loading defaults. This doc picked
  the ones matching `TRAINING_SETUP.md` and the most recent "Anchors"
  commit — confirm which copy is actually being edited before reconciling.
- Detectron2's `INPUT.MIN_SIZE_*`/`MAX_SIZE_*`/`ResizeShortestEdge` are
  **all stock defaults** — never overridden in `train_detectron2.py`. To
  change resizing/scaling behavior, add `cfg.INPUT.*` lines to
  `setup_config()`; changing the synthetic generator's `IMAGE_WIDTH/HEIGHT`
  only changes the *source* image size, not what Detectron2 resizes it to.
