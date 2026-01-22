"""
Hyperparameter Sweep for Detectron2 Training
Sweeps over learning rates and anchor sizes, reusing existing training infrastructure

CURRENT CONFIGURATION (with SWEEP_MAX_ITER set):
- Uses fixed iteration count (SWEEP_MAX_ITER = 7000 iterations)
- Uses exactly 14,000 training images (7000 iterations × batch size 2)
- Uses 2% validation split (~400 images)
- Validates every 500 iterations
- Result: Each hyperparameter combination trains for exactly 7,000 iterations

FALLBACK MODE (if SWEEP_MAX_ITER = None):
- Uses fraction of training images (SWEEP_TRAIN_FRACTION = 0.25)
- Trains for fraction of epochs (SWEEP_EPOCH_FRACTION = 0.25)
"""

import os
import json
import csv
import ast
import time
import signal
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import torch
from detectron2.engine import DefaultTrainer
from detectron2.config import get_cfg
from detectron2 import model_zoo
from functools import wraps
from detectron2.data import MetadataCatalog, DatasetCatalog
from detectron2.data.datasets import register_coco_instances
from detectron2.data import DatasetMapper
from detectron2.data import detection_utils as utils
from detectron2.data.transforms import apply_transform_gens
from detectron2.structures import BitMasks, Instances, Boxes
from detectron2.utils.logger import setup_logger
from detectron2.evaluation import COCOEvaluator, inference_on_dataset
from detectron2.data import build_detection_test_loader
from pycocotools import mask as coco_mask
import matplotlib
# Use non-interactive backend to prevent popup windows
# Plots will be saved to file only - user can open the file to view progress
matplotlib.use('Agg')  # Non-interactive backend - no popup windows
import matplotlib.pyplot as plt
from tqdm import tqdm

# Import reusable components from train_detectron2
# We'll define them here to avoid import issues, but structure matches train_detectron2.py

# ============================================================================
# RETRY UTILITY FOR FILE I/O OPERATIONS
# ============================================================================

def retry_file_io(max_retries=5, delay=1.0, backoff=2.0):
    """
    Decorator to retry file I/O operations on failure.
    Handles temporary drive disconnections and Windows file I/O errors.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries (seconds)
        backoff: Multiplier for delay after each retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (OSError, IOError, PermissionError, FileNotFoundError) as e:
                    last_exception = e
                    error_str = str(e)
                    
                    # Check if it's a retryable error
                    is_retryable = (
                        "[Errno 9]" in error_str or  # Bad file descriptor
                        "[Errno 22]" in error_str or  # Invalid argument
                        "Bad file descriptor" in error_str or
                        "Invalid argument" in error_str or
                        "Permission denied" in error_str or
                        "No such file or directory" in error_str or
                        isinstance(e, FileNotFoundError)  # Temporary file not found
                    )
                    
                    if not is_retryable:
                        # Not a retryable error, raise immediately
                        raise
                    
                    if attempt < max_retries - 1:
                        print(f"  [RETRY] File I/O error (attempt {attempt + 1}/{max_retries}): {error_str}")
                        print(f"  [RETRY] Retrying in {current_delay:.1f} seconds...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        # Last attempt failed
                        print(f"  [ERROR] File I/O failed after {max_retries} attempts: {error_str}")
                        raise
                except Exception as e:
                    # Non-retryable errors (syntax errors, etc.) - raise immediately
                    raise
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


# ============================================================================
# CONFIGURATION
# ============================================================================

# Dataset paths (using Detectron_Trial_2 as specified)
DATASET_NAME = "spray_train"
ANNOTATIONS_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\blur_annotations.json"
IMAGES_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\images"

# Training settings
BATCH_SIZE = 2
NUM_EPOCHS = 1  # Base number of epochs (will be reduced for sweep)
# These are only used if SWEEP_MAX_ITER = None (fallback mode)
SWEEP_EPOCH_FRACTION = 0.25  # Train for 25% of full epochs (only used if SWEEP_MAX_ITER is None)
SWEEP_TRAIN_FRACTION = 0.25  # Use 25% of training images (only used if SWEEP_MAX_ITER is None)

# ============================================================================
# QUICK TEST MODE (for debugging - set to True for fast testing)
# ============================================================================
QUICK_TEST_MODE = True  # Set to False for full sweep

# Fixed iteration count (set based on convergence test results)
# If set to None, will calculate from epochs/fractions (old behavior)
# If set to a number (e.g., 15000), will use that exact iteration count for all sweep runs
# This allows you to use the convergence iteration count directly from convergence_test.py
if QUICK_TEST_MODE:
    SWEEP_MAX_ITER = 100  # Only 100 iterations per run (vs 6000)
    # Hyperparameter sweep ranges (keep all combinations for full workflow test)
    LEARNING_RATES = [0.005, 0.0025, 0.001, 0.0005]  # All 4 learning rates
    ANCHOR_SIZES = [
        [[8, 16, 32, 64]],
        [[8, 16, 32, 64, 128]],
        [[16, 32, 64, 128]]
    ]  # All 3 anchor configs = 12 total combinations
else:
    SWEEP_MAX_ITER = 6000  # Set to 15000 (or whatever your convergence test found) to use fixed iterations
    # Hyperparameter sweep ranges
    LEARNING_RATES = [0.005, 0.0025, 0.001, 0.0005]
    ANCHOR_SIZES = [
        [[8, 16, 32, 64]],
        [[8, 16, 32, 64, 128]],
        [[16, 32, 64, 128]]
    ]

# Output directories
OUTPUT_BASE_DIR = r"D:\Experiments\AI\Hyperparameters"
# Resume from existing sweep folder (set to None to create a new sweep)
# Example: RESUME_SWEEP_FOLDER = r"D:\Experiments\AI\Hyperparameters\sweep_2026_01_21_21_39_37"
RESUME_SWEEP_FOLDER = None  # Set to None to create a new timestamped sweep folder
# CSV paths will be set dynamically in main() after creating timestamped sweep folder
SWEEP_RESULTS_CSV = None
SWEEP_SUMMARY_CSV = None

# Validation settings
# For hyperparameter sweeps, use a smaller validation set to speed up evaluation
# With ~20,000 total images:
#   0.1 = 2000 images (TOO SLOW for sweeps! ~2 hours per validation)
#   0.05 = 1000 images (still slow, ~1 hour per validation)
#   0.02 = 400 images (~45 minutes per validation - good balance for sweeps)
#   0.01 = 200 images (~20-25 minutes per validation - faster but still reliable)
#   0.005 = 100 images (~10-15 minutes per validation - faster but less reliable)
#   0.002 = 40 images (~4-5 minutes per validation - VERY FAST but noisy/inaccurate)
if QUICK_TEST_MODE:
    VALIDATION_SPLIT = 0.002  # Only 40 images for very fast validation (~2-3 min each)
    VALIDATION_INTERVAL = 25  # Validate at 25, 50, 75, 100 (4 validations per run)
else:
    VALIDATION_SPLIT = 0.01  # 1% = ~200 images (good balance: faster but still reliable)
    # Validation interval: More frequent = smoother curves
    #   250 = Validates every 250 iterations (28 validations for 7000 iterations = smooth curves!)
    #   500 = Validates every 500 iterations (14 validations for 7000 iterations = fewer points)
    VALIDATION_INTERVAL = 250  # Evaluate every N iterations (more frequent = smoother curves)

# Resume from pre-trained model (set to None to start from COCO weights)
RESUME_FROM_MODEL = None  # Can be set to a model path if needed

# ============================================================================
# REUSABLE COMPONENTS (from train_detectron2.py)
# ============================================================================

def setup_dataset():
    """Register the COCO dataset and split into train/validation"""
    print(f"\n{'='*60}")
    print("Registering Dataset")
    print(f"{'='*60}")
    
    if not os.path.exists(IMAGES_PATH):
        raise FileNotFoundError(f"Images directory not found: {IMAGES_PATH}")
    
    annotations_path = Path(ANNOTATIONS_PATH)
    if not annotations_path.exists():
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
            raise FileNotFoundError(f"Annotations file not found: {ANNOTATIONS_PATH}")
    
    register_coco_instances(DATASET_NAME, {}, str(annotations_path), IMAGES_PATH)
    MetadataCatalog.get(DATASET_NAME).set(thing_classes=["droplet", "ligament"])
    
    dataset_dicts = DatasetCatalog.get(DATASET_NAME)
    print(f"[OK] Dataset registered: {DATASET_NAME}")
    print(f"[OK] Total number of images: {len(dataset_dicts)}")
    
    # Split into train and validation
    rng = np.random.default_rng(42)  # Fixed seed for reproducibility
    indices = np.arange(len(dataset_dicts))
    rng.shuffle(indices)
    
    split_idx = int(len(dataset_dicts) * (1 - VALIDATION_SPLIT))
    train_indices = indices[:split_idx]
    val_indices = indices[split_idx:]
    
    train_dicts = [dataset_dicts[i] for i in train_indices]
    val_dicts = [dataset_dicts[i] for i in val_indices]
    
    # For hyperparameter sweeps, use enough images for the fixed iteration count
    # With SWEEP_MAX_ITER = 7000 and BATCH_SIZE = 2, we need 14,000 images (7000 * 2)
    # This ensures we use exactly one epoch worth of data for the iteration count
    if SWEEP_MAX_ITER is not None:
        required_images = SWEEP_MAX_ITER * BATCH_SIZE
        original_train_count = len(train_dicts)
        
        if required_images <= original_train_count:
            # Use exactly the number of images needed for the iteration count
            train_dicts = train_dicts[:required_images]
            print(f"[SWEEP] Using {required_images} training images (exactly {SWEEP_MAX_ITER} iterations with batch size {BATCH_SIZE})")
            print(f"[SWEEP] This is {required_images/original_train_count*100:.1f}% of available training images")
        else:
            # Not enough images - use all available (will cycle through dataset)
            print(f"[SWEEP] WARNING: Need {required_images} images but only have {original_train_count}")
            print(f"[SWEEP] Will cycle through dataset {required_images/original_train_count:.2f} times")
            print(f"[SWEEP] Using all {original_train_count} training images")
    elif SWEEP_TRAIN_FRACTION < 1.0:
        # Old behavior: use fraction of images
        original_train_count = len(train_dicts)
        train_subset_size = int(len(train_dicts) * SWEEP_TRAIN_FRACTION)
        train_dicts = train_dicts[:train_subset_size]
        print(f"[SWEEP] Using {SWEEP_TRAIN_FRACTION*100:.0f}% of training images for faster sweeps")
        print(f"[SWEEP] Training images: {len(train_dicts)} (reduced from {original_train_count})")
    else:
        print(f"[OK] Using full training set ({len(train_dicts)} images)")
    
    VAL_DATASET_NAME = f"{DATASET_NAME}_val"
    DatasetCatalog.register(VAL_DATASET_NAME, lambda: val_dicts)
    MetadataCatalog.get(VAL_DATASET_NAME).set(thing_classes=["droplet", "ligament"])
    
    print(f"[OK] Training images: {len(train_dicts)} ({len(train_dicts)/len(dataset_dicts)*100:.1f}% of total)")
    print(f"[OK] Validation images: {len(val_dicts)} ({len(val_dicts)/len(dataset_dicts)*100:.1f}% of total)")
    
    return train_dicts, val_dicts, len(train_dicts)


class RLEDatasetMapper(DatasetMapper):
    """Custom dataset mapper that properly handles RLE format annotations"""
    
    def __init__(self, cfg, is_train=True):
        super().__init__(cfg, is_train=is_train)
    
    def __call__(self, dataset_dict):
        image_path = dataset_dict["file_name"]
        if not os.path.exists(image_path):
            dummy_image = np.zeros((dataset_dict.get("height", 800), dataset_dict.get("width", 1280), 3), dtype=np.uint8)
            dataset_dict["image"] = torch.as_tensor(dummy_image.transpose(2, 0, 1).astype("float32"))
            dataset_dict["annotations"] = []
            empty_instances = Instances((dataset_dict.get("height", 800), dataset_dict.get("width", 1280)))
            empty_instances.gt_boxes = Boxes(torch.zeros((0, 4), dtype=torch.float32))
            empty_instances.gt_classes = torch.zeros((0,), dtype=torch.int64)
            dataset_dict["instances"] = empty_instances
            return dataset_dict
        
        try:
            image = utils.read_image(image_path, format=self.image_format)
        except Exception as e:
            dummy_image = np.zeros((dataset_dict.get("height", 800), dataset_dict.get("width", 1280), 3), dtype=np.uint8)
            dataset_dict["image"] = torch.as_tensor(dummy_image.transpose(2, 0, 1).astype("float32"))
            dataset_dict["annotations"] = []
            empty_instances = Instances((dataset_dict.get("height", 800), dataset_dict.get("width", 1280)))
            empty_instances.gt_boxes = Boxes(torch.zeros((0, 4), dtype=torch.float32))
            empty_instances.gt_classes = torch.zeros((0,), dtype=torch.int64)
            dataset_dict["instances"] = empty_instances
            return dataset_dict
        
        utils.check_image_size(dataset_dict, image)
        
        if "annotations" in dataset_dict:
            annos = []
            for anno in dataset_dict["annotations"]:
                segm = anno.get("segmentation", None)
                if segm is None:
                    continue
                
                if isinstance(segm, dict) and "counts" in segm and "size" in segm:
                    height, width = segm["size"]
                    rle = {"counts": segm["counts"], "size": [height, width]}
                    mask = coco_mask.decode(rle)
                    if len(mask.shape) == 3:
                        mask = mask.sum(axis=2) > 0
                    mask = mask.astype(np.uint8)
                    anno["segmentation"] = mask
                
                annos.append(anno)
            dataset_dict["annotations"] = annos
        
        if hasattr(self, 'tfm_gens') and self.tfm_gens:
            image, transforms = apply_transform_gens(self.tfm_gens, image)
        else:
            transforms = None
        
        dataset_dict["image"] = torch.as_tensor(image.transpose(2, 0, 1).astype("float32"))
        
        if "annotations" in dataset_dict:
            annos = []
            for anno in dataset_dict["annotations"]:
                segm = anno.get("segmentation", None)
                if isinstance(segm, np.ndarray):
                    if transforms:
                        mask_transformed = transforms.apply_segmentation(segm)
                    else:
                        mask_transformed = segm
                    anno["segmentation"] = mask_transformed
                annos.append(anno)
            
            instances = utils.annotations_to_instances(annos, image.shape[:2], mask_format="bitmask")
            dataset_dict["instances"] = utils.filter_empty_instances(instances)
        
        return dataset_dict


# ============================================================================
# LIVE PLOTTING TRACKER
# ============================================================================

class LivePlotTracker:
    """Track metrics and update live matplotlib plot during training"""
    
    def __init__(self, output_dir: Path, run_name: str, max_iter: int):
        self.output_dir = Path(output_dir)
        self.run_name = run_name
        self.max_iter = max_iter
        
        # Metric storage
        self.train_losses = []
        self.train_iterations = []
        self.val_segm_aps = []  # Validation segmentation AP
        self.val_bbox_aps = []  # Validation bbox AP
        self.val_iterations = []
        self.start_time = time.time()
        
        # Best metrics tracking (for both segm and bbox)
        self.best_val_segm_ap = 0.0
        self.best_val_bbox_ap = 0.0
        self.best_val_iter = 0
        
        # Setup matplotlib figure for live plotting
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(12, 8))
        self.fig.suptitle(f'Training Progress: {run_name}', fontsize=14, fontweight='bold')
        
        # Plot 1: Training Loss
        self.ax1.set_xlabel('Iteration')
        self.ax1.set_ylabel('Training Loss')
        self.ax1.set_title('Training Loss')
        self.ax1.grid(True, alpha=0.3)
        self.line1, = self.ax1.plot([], [], 'b-', linewidth=2, label='Training Loss')
        self.ax1.legend()
        self.ax1.set_xlim(0, max_iter)  # Initialize x-axis to start at 0
        
        # Plot 2: Validation AP (both segm and bbox)
        self.ax2.set_xlabel('Iteration')
        self.ax2.set_ylabel('Validation AP')
        self.ax2.set_title('Validation Average Precision (mAP)')
        self.ax2.grid(True, alpha=0.3)
        self.line2_segm, = self.ax2.plot([], [], 'r-o', linewidth=2, markersize=6, label='segm/AP')
        self.line2_bbox, = self.ax2.plot([], [], 'b-s', linewidth=2, markersize=6, label='bbox/AP')
        self.ax2.axhline(y=0, color='k', linestyle='--', alpha=0.3)
        self.ax2.legend()
        self.ax2.set_xlim(0, max_iter)  # Initialize x-axis to start at 0
        
        plt.tight_layout()
        
        # Create plots directory FIRST (before trying to save)
        self.plots_dir = self.output_dir / "plots"
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup CSV file for live updates (matching convergence_test.py)
        self.csv_path = self.output_dir / f"{self.run_name}_live.csv"
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'iteration', 'training_loss', 'validation_segm_ap', 'validation_bbox_ap',
                'best_segm_ap', 'best_bbox_ap', 'best_ap_iter', 'timestamp'
            ])
        print(f"[OK] Live CSV will be saved to: {self.csv_path}")
        print(f"     Open this file in Excel/CSV viewer to watch progress!")
        
        # Save initial empty plot so user knows where to look
        self.plot_path = self.plots_dir / f"{self.run_name}_training_curve_live.png"
        try:
            self.fig.savefig(str(self.plot_path), dpi=150, bbox_inches='tight')
            # Verify file was created
            if self.plot_path.exists():
                file_size = self.plot_path.stat().st_size
                print(f"  [Plot] ✓ Plot file created: {self.plot_path}")
                print(f"  [Plot]   File size: {file_size:,} bytes")
                print(f"  [Plot]   - Updates every 25 iterations (training loss)")
                print(f"  [Plot]   - Updates after each validation (validation AP)")
                print(f"  [Plot]   - Open this file in an image viewer to watch progress!")
            else:
                print(f"  [ERROR] Plot file was not created: {self.plot_path}")
                self.plot_path = None
        except Exception as e:
            print(f"  [ERROR] Could not save initial plot: {e}")
            import traceback
            traceback.print_exc()
            self.plot_path = None
    
    def update_training(self, iteration: int, loss_dict: Dict):
        """Update training loss and refresh plot"""
        if loss_dict is None:
            return
        
        total_loss = float(loss_dict.get('total_loss', 0.0))
        self.train_losses.append(total_loss)
        self.train_iterations.append(iteration)
        
        # Update plot and CSV every 25 iterations (matching convergence_test.py)
        if iteration % 25 == 0:
            self.line1.set_data(self.train_iterations, self.train_losses)
            self.ax1.relim()
            self.ax1.autoscale_view()
            
            if self.plot_path:
                try:
                    self.fig.savefig(str(self.plot_path), dpi=150, bbox_inches='tight')
                except Exception:
                    pass
            
            # Update CSV
            self._update_csv(iteration, total_loss, None, None)
    
    def update_validation(self, iteration: int, val_metrics: Dict):
        """Update validation metrics and refresh plot"""
        if val_metrics is None:
            return
        
        # Extract both segm/AP and bbox/AP
        segm_ap = None
        bbox_ap = None
        
        if 'segm/AP' in val_metrics:
            segm_ap = float(val_metrics['segm/AP'])
        elif 'segm/AP50' in val_metrics:
            segm_ap = float(val_metrics['segm/AP50'])
        
        if 'bbox/AP' in val_metrics:
            bbox_ap = float(val_metrics['bbox/AP'])
        elif 'bbox/AP50' in val_metrics:
            bbox_ap = float(val_metrics['bbox/AP50'])
        
        if segm_ap is None and bbox_ap is None:
            print(f"  [WARNING] Could not extract AP from validation metrics")
            return
        
        # Store both metrics
        if segm_ap is not None:
            self.val_segm_aps.append(segm_ap)
        else:
            self.val_segm_aps.append(0.0)  # Placeholder if missing
        
        if bbox_ap is not None:
            self.val_bbox_aps.append(bbox_ap)
        else:
            self.val_bbox_aps.append(0.0)  # Placeholder if missing
        
        self.val_iterations.append(iteration)
        
        # Update best APs
        if segm_ap is not None and segm_ap > self.best_val_segm_ap:
            self.best_val_segm_ap = segm_ap
            self.best_val_iter = iteration
        
        if bbox_ap is not None and bbox_ap > self.best_val_bbox_ap:
            self.best_val_bbox_ap = bbox_ap
            if segm_ap is None or bbox_ap > segm_ap:
                self.best_val_iter = iteration
        
        # Update plot (both segm and bbox)
        if len(self.val_segm_aps) > 0:
            self.line2_segm.set_data(self.val_iterations, self.val_segm_aps)
        if len(self.val_bbox_aps) > 0:
            self.line2_bbox.set_data(self.val_iterations, self.val_bbox_aps)
        
        self.ax2.relim()
        self.ax2.autoscale_view()
        
        # Add best AP annotation
        if len(self.val_segm_aps) > 0 or len(self.val_bbox_aps) > 0:
            # Remove old annotation
            for txt in self.ax2.texts:
                if txt.get_text().startswith('Best'):
                    txt.remove()
            
            # Add new annotation with both metrics
            annotation_text = f'Best segm/AP: {self.best_val_segm_ap:.4f}\nBest bbox/AP: {self.best_val_bbox_ap:.4f}\n@ iter {self.best_val_iter}'
            self.ax2.text(0.02, 0.98, annotation_text,
                        transform=self.ax2.transAxes, fontsize=10,
                        verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.5))
        
        # Save plot
        if self.plot_path:
            try:
                self._save_plot_with_retry()
            except Exception as e:
                # Don't let plot errors stop training
                if self.iter % 50 == 0:  # Only print occasionally
                    print(f"  [WARNING] Plot save failed: {e}")
    
    @retry_file_io(max_retries=3, delay=0.5)
    def _save_plot_with_retry(self):
        """Save plot with retry logic"""
        self.fig.savefig(str(self.plot_path), dpi=150, bbox_inches='tight')
        
        # Update CSV after validation
        current_loss = self.train_losses[-1] if self.train_losses else None
        self._update_csv(iteration, current_loss, segm_ap, bbox_ap)
        
        # Also write validation results to Detectron2's metrics.json via EventStorage
        # This ensures they're available in metrics.json for later analysis
        # Use smoothing_hint=False to match Detectron2's evaluation hook behavior
        from detectron2.utils.events import get_event_storage
        storage = get_event_storage()
        if storage is not None:
            if segm_ap is not None:
                storage.put_scalar('segm/AP', segm_ap, smoothing_hint=False)
            if bbox_ap is not None:
                storage.put_scalar('bbox/AP', bbox_ap, smoothing_hint=False)
    
    @retry_file_io(max_retries=5, delay=1.0)
    def _update_csv(self, iteration, training_loss, validation_segm_ap, validation_bbox_ap):
        """Update CSV file with current metrics"""
        try:
            with open(self.csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    iteration,
                    training_loss if training_loss is not None else '',
                    validation_segm_ap if validation_segm_ap is not None else '',
                    validation_bbox_ap if validation_bbox_ap is not None else '',
                    self.best_val_segm_ap,
                    self.best_val_bbox_ap,
                    self.best_val_iter,
                    datetime.now().isoformat()
                ])
        except Exception as e:
            # Don't let CSV errors stop training
            if iteration % 100 == 0:  # Only print occasionally
                print(f"  [WARNING] CSV update failed: {e}")
    
    @retry_file_io(max_retries=3, delay=0.5)
    def save_plot(self):
        """Save final plot to file"""
        try:
            plot_path = self.plots_dir / f"{self.run_name}_training_curve.png"
            self.fig.savefig(str(plot_path), dpi=150, bbox_inches='tight')
            print(f"  [OK] Plot saved: {plot_path}")
        except Exception as e:
            print(f"  [WARNING] Failed to save plot: {e}")
    
    def get_final_metrics(self) -> Dict:
        """Get final metrics for CSV export"""
        elapsed_time = time.time() - self.start_time
        
        final_val_segm_ap = self.val_segm_aps[-1] if len(self.val_segm_aps) > 0 else 0.0
        final_val_bbox_ap = self.val_bbox_aps[-1] if len(self.val_bbox_aps) > 0 else 0.0
        
        return {
            'final_val_segm_ap': final_val_segm_ap,
            'final_val_bbox_ap': final_val_bbox_ap,
            'best_val_segm_ap': self.best_val_segm_ap,
            'best_val_bbox_ap': self.best_val_bbox_ap,
            'best_val_iter': self.best_val_iter,
            'training_time_seconds': elapsed_time,
            'training_time_minutes': elapsed_time / 60.0
        }
    
    def close(self):
        """Close the plot figure"""
        plt.close(self.fig)


# ============================================================================
# CUSTOM TRAINER WITH LIVE TRACKING
# ============================================================================

class SweepTrainer(DefaultTrainer):
    """Custom trainer with live progress tracking for hyperparameter sweep"""
    
    @classmethod
    def build_train_loader(cls, cfg):
        from detectron2.data import build_detection_train_loader
        from detectron2.data import get_detection_dataset_dicts
        
        dataset_dicts = get_detection_dataset_dicts(cfg.DATASETS.TRAIN)
        mapper = RLEDatasetMapper(cfg, is_train=True)
        return build_detection_train_loader(cfg, mapper=mapper)
    
    @classmethod
    def build_test_loader(cls, cfg, dataset_name):
        from detectron2.data import build_detection_test_loader
        from detectron2.data import get_detection_dataset_dicts
        
        dataset_dicts = get_detection_dataset_dicts([dataset_name])
        mapper = RLEDatasetMapper(cfg, is_train=False)
        return build_detection_test_loader(cfg, dataset_name, mapper=mapper)
    
    @classmethod
    def build_evaluator(cls, cfg, dataset_name, output_folder=None):
        from detectron2.evaluation import COCOEvaluator
        
        if output_folder is None:
            output_folder = Path(cfg.OUTPUT_DIR) / "validation_eval"
            output_folder.mkdir(parents=True, exist_ok=True)
        
        return COCOEvaluator(dataset_name, output_dir=str(output_folder))
    
    def __init__(self, cfg, plot_tracker=None):
        super().__init__(cfg)
        self.plot_tracker = plot_tracker
        self.last_val_iter = -1
        if plot_tracker:
            print(f"  [Plot Tracker] Initialized - will update every 5 iterations (training) and every {cfg.TEST.EVAL_PERIOD} iterations (validation)")
        else:
            print(f"  [WARNING] Plot tracker is None - plots will not update!")
    
    def run_step(self):
        """Override to track training progress"""
        loss_dict = super().run_step()
        
        # Update plot every 5 iterations for more frequent visual feedback
        if self.plot_tracker and loss_dict is not None and self.iter % 5 == 0:
            try:
                self.plot_tracker.update_training(self.iter, loss_dict)
            except Exception as e:
                # Don't let plot errors stop training
                if self.iter % 50 == 0:  # Only print occasionally
                    print(f"  [WARNING] Plot update failed at iter {self.iter}: {e}")
        
        return loss_dict
    
    def after_step(self):
        """Override to run validation manually (avoiding double validation)"""
        # Use our custom validation interval (stored in config)
        val_interval = getattr(self.cfg.TEST, 'EVAL_PERIOD_CUSTOM', 500)
        
        # Run validation manually
        if (self.plot_tracker and 
            self.iter % val_interval == 0 and 
            self.iter > 0 and 
            self.iter != self.last_val_iter):
            
            self.last_val_iter = self.iter
            
            try:
                print(f"\n  [Validation] Running at iteration {self.iter}...")
                val_results = self._run_validation()
                print(f"  [Validation] Results keys: {list(val_results.keys()) if val_results else 'None'}")
                if val_results and isinstance(val_results, dict) and len(val_results) > 0:
                    self.plot_tracker.update_validation(self.iter, val_results)
                    print(f"  [Validation] ✓ Validation results captured!")
                else:
                    print(f"  [WARNING] Validation returned empty results!")
            except Exception as e:
                print(f"  [ERROR] Validation failed: {e}")
                import traceback
                traceback.print_exc()
        
        try:
            super().after_step()
        except (OSError, IOError) as e:
            # Catch Windows file I/O errors (Errno 22 and Errno 9 - Bad file descriptor)
            if "[Errno 22]" in str(e) or "[Errno 9]" in str(e) or "Invalid argument" in str(e) or "Bad file descriptor" in str(e):
                # Ignore Windows file handle issues - metrics are usually already saved
                pass
            else:
                raise
    
    def after_train(self):
        """Override to handle Windows file I/O errors at end of training"""
        try:
            super().after_train()
        except (OSError, IOError) as e:
            # Catch Windows file I/O errors (Errno 22 and Errno 9 - Bad file descriptor)
            if "[Errno 22]" in str(e) or "[Errno 9]" in str(e) or "Invalid argument" in str(e) or "Bad file descriptor" in str(e):
                # Windows file handle issue - metrics were likely already written
                print(f"  [WARNING] File I/O error during after_train (Windows issue): {e}")
                print(f"  [WARNING] This is usually harmless - metrics were likely already saved")
            else:
                raise
    
    def test(self, cfg=None, model=None, evaluators=None):
        """Override test method - but we handle validation manually in after_step()"""
        # Since we disabled built-in validation (EVAL_PERIOD = 999999), 
        # this method shouldn't be called during training
        # But if it is called (e.g., manually), just pass through to parent
        return super().test(cfg, model, evaluators)
    
    def _run_validation(self):
        """Run validation evaluation and return metrics"""
        from detectron2.evaluation import COCOEvaluator, inference_on_dataset
        
        val_dataset_name = f"{DATASET_NAME}_val"
        eval_output_dir = Path(self.cfg.OUTPUT_DIR) / "validation_eval"
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        
        results = {}
        try:
            print(f"\n    [Validation] Building test loader for {val_dataset_name}...")
            test_loader = self.build_test_loader(self.cfg, val_dataset_name)
            evaluator = COCOEvaluator(val_dataset_name, output_dir=str(eval_output_dir))
            print(f"    [Validation] Running inference on validation set (this may take a few minutes)...")
            print(f"    [Validation] Progress will be shown by Detectron2...")
            
            # Run inference - this will print progress automatically
            results = inference_on_dataset(self.model, test_loader, evaluator)
            
            # Safety check: ensure results is a dict
            if results is None:
                print(f"    [WARNING] inference_on_dataset returned None")
                return {}
            
            # Results are nested: {'bbox': {'AP': ...}, 'segm': {'AP': ...}}
            # Flatten to match expected format: {'segm/AP': ..., 'bbox/AP': ...}
            flattened_results = {}
            if isinstance(results, dict):
                if 'segm' in results and isinstance(results['segm'], dict):
                    for key, value in results['segm'].items():
                        flattened_results[f'segm/{key}'] = value
                if 'bbox' in results and isinstance(results['bbox'], dict):
                    for key, value in results['bbox'].items():
                        flattened_results[f'bbox/{key}'] = value
                
                # Also check if already flattened (for compatibility)
                if not flattened_results and any('/' in k for k in results.keys()):
                    flattened_results = results
            
            # Use flattened results (or original if flattening didn't work)
            results = flattened_results if flattened_results else results
            
            # Print all results for debugging
            print(f"\n    [Validation] Inference complete!")
            print(f"    [Validation] Results dictionary keys: {list(results.keys())}")
            
            # Extract and print AP metrics
            if 'segm/AP' in results:
                print(f"    [Validation] Segmentation mAP: {results['segm/AP']:.4f}")
            if 'segm/AP50' in results:
                print(f"    [Validation] Segmentation AP50: {results['segm/AP50']:.4f}")
            if 'bbox/AP' in results:
                print(f"    [Validation] Bbox mAP: {results['bbox/AP']:.4f}")
            if 'bbox/AP50' in results:
                print(f"    [Validation] Bbox AP50: {results['bbox/AP50']:.4f}")
            
            # If results is empty, try to read from evaluator
            if not results:
                print(f"    [WARNING] Results dictionary is empty, checking evaluator state...")
                # COCOEvaluator saves results to a file, but we need the dict
                # The results should be in the return value, but let's check
                
        except Exception as e:
            print(f"    [ERROR] COCO evaluation failed: {e}")
            import traceback
            traceback.print_exc()
            results = {}
        
        # Ensure we return a dict even if empty
        if not isinstance(results, dict):
            print(f"    [WARNING] Results is not a dict, type: {type(results)}, value: {results}")
            results = {}
        
        return results


# ============================================================================
# HYPERPARAMETER SWEEP FUNCTIONS
# ============================================================================

def setup_config_for_sweep(
    output_dir: str,
    num_train_images: int,
    learning_rate: float,
    anchor_sizes: List[List[int]],
    resume_from: Optional[str] = None
) -> Tuple:
    """Configure Detectron2 for a specific hyperparameter combination"""
    
    # Calculate MAX_ITER
    if SWEEP_MAX_ITER is not None:
        # Use fixed iteration count from convergence test
        max_iter_sweep = SWEEP_MAX_ITER
        print(f"[SWEEP] Using fixed iteration count: {max_iter_sweep} (from convergence test)")
    else:
        # Calculate from epochs/fractions (old behavior)
        iterations_per_epoch = num_train_images // BATCH_SIZE
        max_iter_full = NUM_EPOCHS * iterations_per_epoch
        max_iter_sweep = int(max_iter_full * SWEEP_EPOCH_FRACTION)
        print(f"[SWEEP] Calculated iteration count: {max_iter_sweep} (from {NUM_EPOCHS} epochs × {SWEEP_EPOCH_FRACTION} fraction)")
    
    # Learning rate decay at 60% and 80% of training
    decay_step_1 = int(max_iter_sweep * 0.6)
    decay_step_2 = int(max_iter_sweep * 0.8)
    learning_rate_decay_steps = (decay_step_1, decay_step_2)
    
    print(f"[SWEEP] Learning rate decay steps: {decay_step_1} (60%) and {decay_step_2} (80%)")
    print(f"[SWEEP] Note: Detectron2's default config includes warm-up (typically 1000 iterations)")
    
    cfg = get_cfg()
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )
    
    # Dataset configuration
    cfg.DATASETS.TRAIN = (DATASET_NAME,)
    cfg.DATASETS.TEST = (f"{DATASET_NAME}_val",)
    
    # Data loading
    cfg.DATALOADER.NUM_WORKERS = 2
    
    # Model weights
    if resume_from and os.path.exists(resume_from):
        cfg.MODEL.WEIGHTS = resume_from
    else:
        cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(
            "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"
        )
    
    # Training settings
    cfg.SOLVER.IMS_PER_BATCH = BATCH_SIZE
    cfg.SOLVER.BASE_LR = learning_rate
    cfg.SOLVER.MAX_ITER = max_iter_sweep
    cfg.SOLVER.STEPS = learning_rate_decay_steps
    cfg.SOLVER.GAMMA = 0.1
    
    # Anchor generator sizes (hyperparameter)
    cfg.MODEL.ANCHOR_GENERATOR.SIZES = anchor_sizes
    
    # Validation evaluation
    # Disable Detectron2's built-in validation (set to very high number so it never triggers)
    # We handle validation manually in our custom after_step() to avoid double validation
    cfg.TEST.EVAL_PERIOD = 999999  # Disable built-in validation
    # Store our desired interval for use in after_step()
    if SWEEP_MAX_ITER is not None:
        # Fixed iteration count - use validation interval directly
        cfg.TEST.EVAL_PERIOD_CUSTOM = VALIDATION_INTERVAL
    else:
        # Calculated iterations - cap by epoch length
        val_interval = min(VALIDATION_INTERVAL, iterations_per_epoch)
        cfg.TEST.EVAL_PERIOD_CUSTOM = val_interval
    
    # ROI heads
    cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 128
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2
    
    # Output
    cfg.OUTPUT_DIR = output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    return cfg, max_iter_sweep


def create_run_name(learning_rate: float, anchor_sizes: List[List[int]], include_timestamp: bool = True) -> str:
    """Create a descriptive name for this hyperparameter combination"""
    lr_str = f"lr{learning_rate:.4f}".replace('.', '_')
    anchor_str = "_".join([str(s) for sizes in anchor_sizes for s in sizes])
    anchor_str = anchor_str.replace('[', '').replace(']', '').replace(',', '')
    base_name = f"{lr_str}_anchors{anchor_str}"
    
    if include_timestamp:
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        return f"{base_name}_{timestamp}"
    return base_name


def run_single_sweep(
    learning_rate: float,
    anchor_sizes: List[List[int]],
    train_dicts: List,
    val_dicts: List,
    num_train_images: int,
    run_number: int,
    total_runs: int
) -> Dict:
    """Run training for a single hyperparameter combination"""
    
    print(f"\n{'='*80}")
    print(f"SWEEP RUN {run_number}/{total_runs}")
    print(f"{'='*80}")
    print(f"Learning Rate: {learning_rate}")
    print(f"Anchor Sizes: {anchor_sizes}")
    print(f"{'='*80}\n")
    
    # Create run name and output directory (with timestamp)
    run_name = create_run_name(learning_rate, anchor_sizes, include_timestamp=True)
    output_dir = Path(OUTPUT_BASE_DIR) / run_name
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup config
    cfg, max_iter = setup_config_for_sweep(
        str(output_dir), num_train_images, learning_rate, anchor_sizes, RESUME_FROM_MODEL
    )
    
    print(f"Output directory: {output_dir}")
    print(f"Max iterations: {max_iter} (reduced from full training)")
    print(f"Validation interval: {cfg.TEST.EVAL_PERIOD} iterations\n")
    
    # Initialize live plot tracker
    print(f"\n  Initializing live plot tracker...")
    plot_tracker = LivePlotTracker(output_dir, run_name, max_iter)
    print(f"  [OK] Plot tracker initialized")
    
    # Show user where to find the plot
    plot_file = output_dir / "plots" / f"{run_name}_training_curve_live.png"
    print(f"\n  {'='*60}")
    print(f"  📊 PLOT LOCATION:")
    print(f"  {'='*60}")
    print(f"  File: {plot_file}")
    print(f"  - Updates every 25 iterations (training loss)")
    print(f"  - Updates after each validation (validation AP)")
    print(f"  - Open this file in an image viewer to watch progress!")
    print(f"  - You can keep it open and refresh to see updates")
    print(f"  {'='*60}\n")
    
    # Create trainer
    print(f"  Creating trainer with plot tracker...")
    trainer = SweepTrainer(cfg, plot_tracker)
    print(f"  [OK] Trainer created")
    trainer.resume_or_load(resume=False)
    
    # Train
    start_time = time.time()
    try:
        trainer.train()
    except KeyboardInterrupt:
        print("\n\nTraining interrupted by user. Saving checkpoint...")
        trainer.checkpointer.save("model_interrupted")
        print("Checkpoint saved!")
    except (OSError, IOError) as e:
        # Catch Windows file I/O errors that might occur during training
        if "[Errno 9]" in str(e) or "Bad file descriptor" in str(e):
            print(f"\n  [WARNING] Windows file I/O error during training: {e}")
            print(f"  [WARNING] Training will continue - this is usually harmless")
            # Training should continue, but if it stopped, we need to handle it
            # The error was likely already caught in after_step/after_train, so this is a safety net
        else:
            raise
    
    training_time = time.time() - start_time
    
    # Always run final validation to ensure CSV has the actual final model performance
    # Check if we need to run final validation (either no validation yet, or last validation wasn't at final iteration)
    final_iter = trainer.iter
    needs_final_validation = False
    
    if len(plot_tracker.val_segm_aps) == 0 and len(plot_tracker.val_bbox_aps) == 0:
        print(f"\n  [Final Validation] No validation metrics captured during training.")
        needs_final_validation = True
    elif len(plot_tracker.val_iterations) > 0 and plot_tracker.val_iterations[-1] != final_iter:
        print(f"\n  [Final Validation] Last validation was at iter {plot_tracker.val_iterations[-1]}, but training ended at iter {final_iter}.")
        needs_final_validation = True
    
    if needs_final_validation:
        print(f"  [Final Validation] Running final validation at iter {final_iter}...")
        try:
            val_results = trainer._run_validation()
            if val_results and isinstance(val_results, dict) and len(val_results) > 0:
                plot_tracker.update_validation(final_iter, val_results)
                print(f"  [Final Validation] ✓ Validation complete and metrics captured!")
            else:
                print(f"  [WARNING] Final validation returned empty results!")
        except Exception as e:
            print(f"  [ERROR] Final validation failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"\n  [Final Validation] Validation already run at final iteration ({final_iter}). Using existing metrics.")
    
    # Get final metrics
    final_metrics = plot_tracker.get_final_metrics()
    
    # Debug: Print what we're about to save (before closing plot tracker)
    print(f"\n  [CSV Debug] Metrics to be saved:")
    num_val_runs = max(len(plot_tracker.val_segm_aps), len(plot_tracker.val_bbox_aps))
    print(f"    Final Val segm/AP: {final_metrics['final_val_segm_ap']:.4f}")
    print(f"    Final Val bbox/AP: {final_metrics['final_val_bbox_ap']:.4f}")
    print(f"    Best Val segm/AP: {final_metrics['best_val_segm_ap']:.4f}")
    print(f"    Best Val bbox/AP: {final_metrics['best_val_bbox_ap']:.4f}")
    print(f"    (from {num_val_runs} validation runs)")
    print(f"    Best AP @ iter: {final_metrics['best_val_iter']}")
    if len(plot_tracker.val_iterations) > 0:
        print(f"    Last validation at iter: {plot_tracker.val_iterations[-1]}")
        print(f"    Training ended at iter: {final_iter}")
    
    plot_tracker.save_plot()
    plot_tracker.close()
    
    # Prepare results dictionary
    results = {
        'run_name': run_name,
        'learning_rate': learning_rate,
        'anchor_sizes': str(anchor_sizes),
        'final_val_segm_ap': final_metrics['final_val_segm_ap'],
        'final_val_bbox_ap': final_metrics['final_val_bbox_ap'],
        'best_val_segm_ap': final_metrics['best_val_segm_ap'],
        'best_val_bbox_ap': final_metrics['best_val_bbox_ap'],
        'best_val_iter': final_metrics['best_val_iter'],
        'training_time_seconds': final_metrics['training_time_seconds'],
        'training_time_minutes': final_metrics['training_time_minutes'],
        'max_iter': max_iter,
        'output_dir': str(output_dir)
    }
    
    # Save to CSV immediately (append mode for resume safety)
    save_run_to_csv(results)
    print(f"  [CSV] ✓ Results saved to: {SWEEP_RESULTS_CSV}")
    
    print(f"\n{'='*80}")
    print(f"RUN {run_number}/{total_runs} COMPLETE")
    print(f"{'='*80}")
    print(f"Final Validation segm/AP: {final_metrics['final_val_segm_ap']:.4f}")
    print(f"Final Validation bbox/AP: {final_metrics['final_val_bbox_ap']:.4f}")
    print(f"Best Validation segm/AP: {final_metrics['best_val_segm_ap']:.4f} @ iter {final_metrics['best_val_iter']}")
    print(f"Best Validation bbox/AP: {final_metrics['best_val_bbox_ap']:.4f} @ iter {final_metrics['best_val_iter']}")
    print(f"Training time: {final_metrics['training_time_minutes']:.1f} minutes")
    print(f"{'='*80}\n")
    
    return results


@retry_file_io(max_retries=5, delay=1.0)
def save_run_to_csv(results: Dict):
    """Append a single run's results to the CSV file"""
    csv_path = SWEEP_RESULTS_CSV
    
    # Create file with headers if it doesn't exist
    file_exists = _path_exists_with_retry(csv_path)
    
    with open(csv_path, 'a', newline='') as f:
        fieldnames = [
            'run_name', 'learning_rate', 'anchor_sizes', 
            'final_val_segm_ap', 'final_val_bbox_ap',
            'best_val_segm_ap', 'best_val_bbox_ap', 'best_val_iter',
            'training_time_seconds', 'training_time_minutes', 'max_iter', 'output_dir', 'timestamp'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        if not file_exists:
            writer.writeheader()
        
        # Add timestamp
        results['timestamp'] = datetime.now().isoformat()
        writer.writerow(results)


def create_summary(results_list: List[Dict]):
    """Create summary CSV and comparison plots"""
    print(f"\n{'='*80}")
    print("CREATING SWEEP SUMMARY")
    print(f"{'='*80}\n")
    
    # Save summary CSV (with retry)
    summary_path = SWEEP_SUMMARY_CSV
    _write_summary_csv_with_retry(summary_path, results_list)
    
    # Create comparison plots
    create_comparison_plots(results_list)
    
    print(f"\n{'='*80}")
    print("SWEEP SUMMARY COMPLETE")
    print(f"{'='*80}\n")


def create_comparison_plots(results_list: List[Dict]):
    """Create comparison plots for all runs - showing both segm/AP and bbox/AP"""
    plots_dir = Path(OUTPUT_BASE_DIR) / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract data (with fallback for old format)
    learning_rates = [r['learning_rate'] for r in results_list]
    anchor_sizes_str = [r['anchor_sizes'] for r in results_list]
    
    # Extract segm and bbox APs (with fallback for old format)
    best_segm_aps = [r.get('best_val_segm_ap', r.get('best_val_ap', 0.0)) for r in results_list]
    best_bbox_aps = [r.get('best_val_bbox_ap', r.get('best_val_ap', 0.0)) for r in results_list]
    final_segm_aps = [r.get('final_val_segm_ap', r.get('final_val_ap', 0.0)) for r in results_list]
    final_bbox_aps = [r.get('final_val_bbox_ap', r.get('final_val_ap', 0.0)) for r in results_list]
    
    # Create figure with subplots (2 rows, 2 columns: segm and bbox for each comparison)
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    ax1_segm, ax1_bbox = axes[0]  # Top row: AP vs Learning Rate
    ax2_segm, ax2_bbox = axes[1]  # Bottom row: AP vs Anchor Configuration
    
    # Plot 1a: segm/AP vs Learning Rate
    ax1_segm.scatter(learning_rates, best_segm_aps, s=100, alpha=0.7, label='Best segm/AP', c='blue', marker='o')
    ax1_segm.scatter(learning_rates, final_segm_aps, s=100, alpha=0.7, label='Final segm/AP', c='red', marker='x')
    ax1_segm.set_xlabel('Learning Rate', fontsize=12)
    ax1_segm.set_ylabel('Validation segm/AP', fontsize=12)
    ax1_segm.set_title('Validation segm/AP vs Learning Rate', fontsize=14, fontweight='bold')
    ax1_segm.set_xscale('log')
    ax1_segm.grid(True, alpha=0.3)
    ax1_segm.legend()
    
    # Plot 1b: bbox/AP vs Learning Rate
    ax1_bbox.scatter(learning_rates, best_bbox_aps, s=100, alpha=0.7, label='Best bbox/AP', c='green', marker='s')
    ax1_bbox.scatter(learning_rates, final_bbox_aps, s=100, alpha=0.7, label='Final bbox/AP', c='orange', marker='x')
    ax1_bbox.set_xlabel('Learning Rate', fontsize=12)
    ax1_bbox.set_ylabel('Validation bbox/AP', fontsize=12)
    ax1_bbox.set_title('Validation bbox/AP vs Learning Rate', fontsize=14, fontweight='bold')
    ax1_bbox.set_xscale('log')
    ax1_bbox.grid(True, alpha=0.3)
    ax1_bbox.legend()
    
    # Plot 2a: segm/AP vs Anchor Configuration
    unique_anchors = list(set(anchor_sizes_str))
    anchor_indices = {anchor: i for i, anchor in enumerate(unique_anchors)}
    x_positions = [anchor_indices[anchor] for anchor in anchor_sizes_str]
    
    ax2_segm.scatter(x_positions, best_segm_aps, s=100, alpha=0.7, label='Best segm/AP', c='blue', marker='o')
    ax2_segm.scatter(x_positions, final_segm_aps, s=100, alpha=0.7, label='Final segm/AP', c='red', marker='x')
    ax2_segm.set_xlabel('Anchor Configuration', fontsize=12)
    ax2_segm.set_ylabel('Validation segm/AP', fontsize=12)
    ax2_segm.set_title('Validation segm/AP vs Anchor Configuration', fontsize=14, fontweight='bold')
    ax2_segm.set_xticks(range(len(unique_anchors)))
    ax2_segm.set_xticklabels([f"Config {i+1}" for i in range(len(unique_anchors))], rotation=45, ha='right')
    ax2_segm.grid(True, alpha=0.3)
    ax2_segm.legend()
    
    # Plot 2b: bbox/AP vs Anchor Configuration
    ax2_bbox.scatter(x_positions, best_bbox_aps, s=100, alpha=0.7, label='Best bbox/AP', c='green', marker='s')
    ax2_bbox.scatter(x_positions, final_bbox_aps, s=100, alpha=0.7, label='Final bbox/AP', c='orange', marker='x')
    ax2_bbox.set_xlabel('Anchor Configuration', fontsize=12)
    ax2_bbox.set_ylabel('Validation bbox/AP', fontsize=12)
    ax2_bbox.set_title('Validation bbox/AP vs Anchor Configuration', fontsize=14, fontweight='bold')
    ax2_bbox.set_xticks(range(len(unique_anchors)))
    ax2_bbox.set_xticklabels([f"Config {i+1}" for i in range(len(unique_anchors))], rotation=45, ha='right')
    ax2_bbox.grid(True, alpha=0.3)
    ax2_bbox.legend()
    
    # Add legend for anchor configurations (on the right side)
    legend_text = "\n".join([f"Config {i+1}: {anchor[:50]}" for i, anchor in enumerate(unique_anchors)])
    ax2_segm.text(1.02, 0.5, legend_text, transform=ax2_segm.transAxes, fontsize=8,
            verticalalignment='center', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    # Save plot with retry
    plot_path = plots_dir / "sweep_comparison.png"
    _save_plot_fig_with_retry(fig, plot_path)
    plt.close(fig)
    
    print(f"[OK] Comparison plot saved: {plot_path}")


@retry_file_io(max_retries=3, delay=0.5)
def _path_exists_with_retry(path: Path) -> bool:
    """Check if path exists with retry logic"""
    return path.exists()

@retry_file_io(max_retries=3, delay=0.5)
def _read_csv_with_retry(csv_path: Path):
    """Read CSV file with retry logic"""
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        return list(reader)

@retry_file_io(max_retries=3, delay=0.5)
def _read_json_with_retry(json_path: Path):
    """Read JSON file with retry logic"""
    import json
    with open(json_path, 'r') as f:
        return json.load(f)

@retry_file_io(max_retries=3, delay=0.5)
def _write_summary_csv_with_retry(summary_path: Path, results_list: List[Dict]):
    """Write summary CSV with retry logic"""
    with open(summary_path, 'w', newline='') as f:
        fieldnames = [
            'run_name', 'learning_rate', 'anchor_sizes', 
            'final_val_segm_ap', 'final_val_bbox_ap',
            'best_val_segm_ap', 'best_val_bbox_ap', 'best_val_iter', 'training_time_minutes'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for results in results_list:
            writer.writerow({
                'run_name': results['run_name'],
                'learning_rate': results['learning_rate'],
                'anchor_sizes': results['anchor_sizes'],
                'final_val_segm_ap': results.get('final_val_segm_ap', 0.0),
                'final_val_bbox_ap': results.get('final_val_bbox_ap', 0.0),
                'best_val_segm_ap': results.get('best_val_segm_ap', 0.0),
                'best_val_bbox_ap': results.get('best_val_bbox_ap', 0.0),
                'best_val_iter': results['best_val_iter'],
                'training_time_minutes': results['training_time_minutes']
            })
    print(f"[OK] Summary CSV saved: {summary_path}")

@retry_file_io(max_retries=3, delay=0.5)
def _save_plot_fig_with_retry(fig, plot_path: Path):
    """Save matplotlib figure with retry logic"""
    fig.savefig(str(plot_path), dpi=150, bbox_inches='tight')

@retry_file_io(max_retries=3, delay=0.5)
def check_existing_runs() -> List[Dict]:
    """Check for existing runs in CSV to enable resume"""
    existing_runs = []
    
    # First, check CSV if it exists
    if SWEEP_RESULTS_CSV is not None and _path_exists_with_retry(SWEEP_RESULTS_CSV):
        with open(SWEEP_RESULTS_CSV, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_runs.append({
                    'learning_rate': float(row['learning_rate']),
                    'anchor_sizes': ast.literal_eval(row['anchor_sizes'])  # Safe parsing for list
                })
    
    return existing_runs


def find_completed_runs_in_folders(sweep_folder: Path) -> List[Dict]:
    """Scan sweep folder for completed run directories and extract their metrics"""
    completed_runs = []
    
    if not sweep_folder.exists():
        return completed_runs
    
    # Pattern: lr0_0050_anchors8_16_32_64_2026_01_22_17_14_52
    import re
    
    for run_dir in sweep_folder.iterdir():
        if not run_dir.is_dir():
            continue
        
        run_name = run_dir.name
        
        # Check if this looks like a run folder (starts with lr)
        if not run_name.startswith('lr'):
            continue
        
        # Check if run completed (has model_final.pth)
        model_final = run_dir / "model_final.pth"
        if not _path_exists_with_retry(model_final):
            continue
        
        # Parse run name to extract learning rate and anchor sizes
        # Pattern: lr0_0050_anchors8_16_32_64_2026_01_22_17_14_52
        match = re.match(r'lr([\d_]+)_anchors([\d_]+)(?:_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})?', run_name)
        if not match:
            continue
        
        # Extract learning rate (convert 0_0050 to 0.0050)
        lr_str = match.group(1).replace('_', '.')
        try:
            learning_rate = float(lr_str)
        except ValueError:
            continue
        
        # Extract anchor sizes (convert "8_16_32_64" to [[8, 16, 32, 64]])
        anchor_str = match.group(2)
        anchor_parts = [int(x) for x in anchor_str.split('_') if x.isdigit()]
        if not anchor_parts:
            continue
        
        # Detectron2 anchor sizes are grouped by aspect ratio, but we store them as a flat list
        # We need to reconstruct the original format - typically it's one list per aspect ratio
        # For simplicity, assume single aspect ratio with these sizes
        anchor_sizes = [anchor_parts]  # Wrap in list to match expected format
        
        # Try to extract metrics from the run folder
        metrics = extract_metrics_from_completed_run(run_dir, run_name)
        
        if metrics:
            completed_runs.append({
                'learning_rate': learning_rate,
                'anchor_sizes': anchor_sizes,
                'run_name': run_name,
                'run_dir': run_dir,
                'metrics': metrics
            })
    
    return completed_runs


def extract_metrics_from_completed_run(run_dir: Path, run_name: str) -> Optional[Dict]:
    """Extract final metrics from a completed run folder"""
    metrics = {}
    
    # Try to load from live CSV first (most accurate)
    live_csv = run_dir / f"{run_name}_live.csv"
    if _path_exists_with_retry(live_csv):
        try:
            # Read CSV manually (no pandas dependency) - with retry
            rows = _read_csv_with_retry(live_csv)
            
            if len(rows) > 0:
                # Find rows with validation data
                val_rows = []
                for row in rows:
                    if (row.get('validation_segm_ap', '').strip() and row['validation_segm_ap'] != '') or \
                       (row.get('validation_bbox_ap', '').strip() and row['validation_bbox_ap'] != ''):
                        val_rows.append(row)
                
                if len(val_rows) > 0:
                    # Get final validation metrics
                    last_val = val_rows[-1]
                    try:
                        metrics['final_val_segm_ap'] = float(last_val.get('validation_segm_ap', 0) or 0)
                    except (ValueError, TypeError):
                        metrics['final_val_segm_ap'] = 0.0
                    
                    try:
                        metrics['final_val_bbox_ap'] = float(last_val.get('validation_bbox_ap', 0) or 0)
                    except (ValueError, TypeError):
                        metrics['final_val_bbox_ap'] = 0.0
                    
                    try:
                        metrics['best_val_iter'] = int(last_val.get('iteration', 0) or 0)
                    except (ValueError, TypeError):
                        metrics['best_val_iter'] = 0
                    
                    # Find best APs
                    segm_aps = []
                    bbox_aps = []
                    for row in val_rows:
                        try:
                            segm_val = float(row.get('validation_segm_ap', 0) or 0)
                            if segm_val > 0:
                                segm_aps.append(segm_val)
                        except (ValueError, TypeError):
                            pass
                        try:
                            bbox_val = float(row.get('validation_bbox_ap', 0) or 0)
                            if bbox_val > 0:
                                bbox_aps.append(bbox_val)
                        except (ValueError, TypeError):
                            pass
                    
                    if segm_aps:
                        metrics['best_val_segm_ap'] = max(segm_aps)
                    if bbox_aps:
                        metrics['best_val_bbox_ap'] = max(bbox_aps)
                    
                    # Get max iteration from all rows
                    max_iter = 0
                    for row in rows:
                        try:
                            iter_val = int(row.get('iteration', 0) or 0)
                            max_iter = max(max_iter, iter_val)
                        except (ValueError, TypeError):
                            pass
                    metrics['max_iter'] = max_iter
                    
                    return metrics
        except Exception as e:
            print(f"  [WARNING] Could not read live CSV for {run_name}: {e}")
    
    # Fallback: try to extract from validation_eval results
    val_results = run_dir / "validation_eval" / "coco_instances_results.json"
    if _path_exists_with_retry(val_results):
        try:
            results = _read_json_with_retry(val_results)
            
            # Extract AP from results (format varies)
            if isinstance(results, list) and len(results) > 0:
                # This is detection results, need to evaluate
                pass  # Would need COCO evaluator to compute AP
            elif isinstance(results, dict):
                # Try to find AP values
                if 'segm' in results and 'AP' in results['segm']:
                    metrics['final_val_segm_ap'] = float(results['segm']['AP'])
                if 'bbox' in results and 'AP' in results['bbox']:
                    metrics['final_val_bbox_ap'] = float(results['bbox']['AP'])
        except Exception as e:
            print(f"  [WARNING] Could not read validation results for {run_name}: {e}")
    
    # If we got at least some metrics, return them
    if metrics:
        # Set defaults for missing values
        metrics.setdefault('final_val_segm_ap', 0.0)
        metrics.setdefault('final_val_bbox_ap', 0.0)
        metrics.setdefault('best_val_segm_ap', metrics.get('final_val_segm_ap', 0.0))
        metrics.setdefault('best_val_bbox_ap', metrics.get('final_val_bbox_ap', 0.0))
        metrics.setdefault('best_val_iter', metrics.get('max_iter', 0))
        metrics.setdefault('training_time_seconds', 0)
        metrics.setdefault('training_time_minutes', 0)
        metrics.setdefault('max_iter', SWEEP_MAX_ITER if SWEEP_MAX_ITER else 0)
        return metrics
    
    return None


# ============================================================================
# MAIN SWEEP FUNCTION
# ============================================================================

def main():
    """Run hyperparameter sweep"""
    # Declare globals first (before any use)
    global OUTPUT_BASE_DIR, SWEEP_RESULTS_CSV, SWEEP_SUMMARY_CSV
    
    print("\n" + "="*80)
    print("HYPERPARAMETER SWEEP FOR DETECTRON2")
    print("="*80)
    
    # Show quick test mode status
    if QUICK_TEST_MODE:
        print("\n" + "="*80)
        print("⚠️  QUICK TEST MODE ENABLED ⚠️")
        print("="*80)
        print(f"  Iterations per run: {SWEEP_MAX_ITER} (vs 6000 in full mode)")
        print(f"  Validation interval: {VALIDATION_INTERVAL} (vs 250 in full mode)")
        print(f"  Validation images: ~{int(20000 * VALIDATION_SPLIT)} (vs ~200 in full mode)")
        print(f"  Total combinations: {len(LEARNING_RATES) * len(ANCHOR_SIZES)}")
        print(f"  Estimated time: ~{len(LEARNING_RATES) * len(ANCHOR_SIZES) * 15} minutes total")
        print("="*80 + "\n")
    
    # Check if resuming from existing sweep folder
    if RESUME_SWEEP_FOLDER is not None:
        sweep_folder = Path(RESUME_SWEEP_FOLDER)
        if not sweep_folder.exists():
            print(f"ERROR: Resume folder does not exist: {sweep_folder}")
            print("Please set RESUME_SWEEP_FOLDER = None to create a new sweep, or fix the path.")
            return
        print(f"[RESUME] Continuing from existing sweep folder: {sweep_folder}")
        print(f"[RESUME] Will skip already completed runs and continue with remaining combinations")
    else:
        # Create timestamped sweep folder (new sweep)
        base_output_dir = Path(OUTPUT_BASE_DIR)
        sweep_timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        sweep_folder = base_output_dir / f"sweep_{sweep_timestamp}"
        sweep_folder.mkdir(parents=True, exist_ok=True)
        print(f"[NEW] Creating new sweep folder: {sweep_folder}")
    
    # Update global OUTPUT_BASE_DIR and CSV paths to point to this sweep folder
    OUTPUT_BASE_DIR = str(sweep_folder)
    SWEEP_RESULTS_CSV = sweep_folder / "sweep_results.csv"
    SWEEP_SUMMARY_CSV = sweep_folder / "sweep_summary.csv"
    
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Sweep folder: {sweep_folder}")
    print(f"Dataset: {ANNOTATIONS_PATH}")
    if SWEEP_MAX_ITER is not None:
        print(f"Iterations per run: {SWEEP_MAX_ITER} (fixed)")
        print(f"Training images per run: {SWEEP_MAX_ITER * BATCH_SIZE} (exactly one epoch)")
    else:
        print(f"Training fraction: {SWEEP_EPOCH_FRACTION*100:.0f}% of full training")
    print("="*80 + "\n")
    
    # Setup dataset (only once)
    setup_logger()
    train_dicts, val_dicts, num_train_images = setup_dataset()
    
    # Check for existing runs (for resume capability)
    existing_runs = check_existing_runs()
    print(f"Found {len(existing_runs)} existing runs in CSV (will skip if duplicate)\n")
    
    # Also check for completed runs in folders that might not be in CSV (e.g., crashed before CSV write)
    print(f"[RESUME] Scanning sweep folder for completed runs...")
    completed_runs_in_folders = find_completed_runs_in_folders(sweep_folder)
    
    if completed_runs_in_folders:
        print(f"[RESUME] Found {len(completed_runs_in_folders)} completed runs in folders")
        
        # Add completed runs to CSV if not already there
        for completed_run in completed_runs_in_folders:
            lr = completed_run['learning_rate']
            anchors = completed_run['anchor_sizes']
            
            # Check if already in CSV
            already_in_csv = False
            for existing in existing_runs:
                if (abs(existing['learning_rate'] - lr) < 1e-6 and 
                    existing['anchor_sizes'] == anchors):
                    already_in_csv = True
                    break
            
            if not already_in_csv:
                print(f"  [RECOVER] Recovering metrics for: LR={lr}, Anchors={anchors}")
                metrics = completed_run['metrics']
                
                # Create results dict in same format as run_single_sweep
                results = {
                    'run_name': completed_run['run_name'],
                    'learning_rate': lr,
                    'anchor_sizes': str(anchors),
                    'final_val_segm_ap': metrics.get('final_val_segm_ap', 0.0),
                    'final_val_bbox_ap': metrics.get('final_val_bbox_ap', 0.0),
                    'best_val_segm_ap': metrics.get('best_val_segm_ap', metrics.get('final_val_segm_ap', 0.0)),
                    'best_val_bbox_ap': metrics.get('best_val_bbox_ap', metrics.get('final_val_bbox_ap', 0.0)),
                    'best_val_iter': metrics.get('best_val_iter', metrics.get('max_iter', 0)),
                    'training_time_seconds': metrics.get('training_time_seconds', 0),
                    'training_time_minutes': metrics.get('training_time_minutes', 0),
                    'max_iter': metrics.get('max_iter', SWEEP_MAX_ITER if SWEEP_MAX_ITER else 0),
                    'output_dir': str(completed_run['run_dir'])
                }
                
                # Add to CSV
                save_run_to_csv(results)
                print(f"    [OK] Added to CSV: segm/AP={results['final_val_segm_ap']:.4f}, bbox/AP={results['final_val_bbox_ap']:.4f}")
                
                # Add to existing_runs so it gets skipped
                existing_runs.append({
                    'learning_rate': lr,
                    'anchor_sizes': anchors
                })
            else:
                print(f"  [SKIP] Already in CSV: LR={lr}, Anchors={anchors}")
        
        print()  # Blank line
    
    # Generate all hyperparameter combinations
    all_combinations = []
    for lr in LEARNING_RATES:
        for anchor_sizes in ANCHOR_SIZES:
            # Check if this combination was already run
            is_duplicate = False
            for existing in existing_runs:
                if (abs(existing['learning_rate'] - lr) < 1e-6 and 
                    existing['anchor_sizes'] == anchor_sizes):
                    print(f"[SKIP] Already run: LR={lr}, Anchors={anchor_sizes}")
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                all_combinations.append((lr, anchor_sizes))
    
    total_runs = len(all_combinations)
    print(f"\nTotal new runs to execute: {total_runs}")
    print(f"Total combinations: {len(LEARNING_RATES) * len(ANCHOR_SIZES)}")
    print(f"Already completed: {len(LEARNING_RATES) * len(ANCHOR_SIZES) - total_runs}\n")
    
    if total_runs == 0:
        print("All combinations already completed! Exiting.")
        return
    
    # Run sweep
    all_results = []
    
    try:
        for run_num, (lr, anchor_sizes) in enumerate(all_combinations, 1):
            results = run_single_sweep(
                lr, anchor_sizes, train_dicts, val_dicts,
                num_train_images, run_num, total_runs
            )
            all_results.append(results)
            
            # Small pause between runs
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\nSweep interrupted by user!")
        print("Completed runs have been saved to CSV.")
        if len(all_results) > 0:
            print("Creating summary for completed runs...")
            create_summary(all_results)
        return
    
    # Create final summary
    create_summary(all_results)
    
    # Find best configuration
    best_run = max(all_results, key=lambda x: x['best_val_ap'])
    
    print(f"\n{'='*80}")
    print("SWEEP COMPLETE!")
    print(f"{'='*80}")
    print(f"Best configuration:")
    print(f"  Learning Rate: {best_run['learning_rate']}")
    print(f"  Anchor Sizes: {best_run['anchor_sizes']}")
    print(f"  Best Validation AP: {best_run['best_val_ap']:.4f}")
    print(f"  Output Directory: {best_run['output_dir']}")
    print(f"\nSummary files:")
    print(f"  Results CSV: {SWEEP_RESULTS_CSV}")
    print(f"  Summary CSV: {SWEEP_SUMMARY_CSV}")
    print(f"  Comparison Plot: {Path(OUTPUT_BASE_DIR) / 'plots' / 'sweep_comparison.png'}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
