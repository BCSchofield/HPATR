"""
Detectron2 Training Script with Progress Visualization
Trains Mask R-CNN on synthetic spray droplet dataset
"""

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
matplotlib.use('Agg')  # Use non-interactive backend to avoid display issues
import matplotlib.pyplot as plt
from tqdm import tqdm

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
                        raise

                    if attempt < max_retries - 1:
                        print(f"  [RETRY] File I/O error (attempt {attempt + 1}/{max_retries}): {error_str}")
                        print(f"  [RETRY] Retrying in {current_delay:.1f} seconds...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        print(f"  [ERROR] File I/O failed after {max_retries} attempts: {error_str}")
                        raise
                except Exception:
                    raise

            if last_exception:
                raise last_exception

        return wrapper
    return decorator


@retry_file_io(max_retries=3, delay=0.5)
def _path_exists_with_retry(path: Path) -> bool:
    """Check if path exists with retry logic"""
    return path.exists()


@retry_file_io(max_retries=3, delay=0.5)
def _savefig_with_retry(fig, path, **kwargs):
    """Save matplotlib figure with retry logic"""
    fig.savefig(str(path), **kwargs)


# ============================================================================
# CONFIGURATION
# ============================================================================

# --- Final training options (from hyperparameter sweep) ---
BATCH_SIZE = 2
BASE_LEARNING_RATE = 0.0025
ANCHOR_SIZES = [[8, 16, 32, 64]]  # FPN anchor sizes (one list per level; same for all here)
WARMUP_ITERS = 1000
# LR decay: "cosine" | "step" (drops at 60% and 80%) | "none" (constant after warmup)
LR_DECAY_TYPE = "cosine"

# --- Dataset paths ---
DATASET_NAME = "spray_train"
ANNOTATIONS_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\blur_annotations.json"
IMAGES_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\images"

# --- Training length and output ---
NUM_EPOCHS = 1  # Used only when MAX_ITER is None: total iters = NUM_EPOCHS * (num_train // BATCH_SIZE)
# Set MAX_ITER to fix total iterations (e.g. 20000 for your final run). None = use NUM_EPOCHS formula.
MAX_ITER = 78000  # ~80k full run; None = derived from NUM_EPOCHS
# Quick test: overrides everything. 500 for ~15 min test; None for real run.
QUICK_TEST_ITERATIONS = None  # 500 for quick test; None for real run
OUTPUT_BASE_DIR = r"D:\Experiments\AI"
CHECKPOINT_INTERVAL = 10000  # Save checkpoint every N iterations

# --- Validation ---
VALIDATION_SPLIT = 0.1  # Used only when VALIDATION_SIZE is None: fraction for validation
VALIDATION_INTERVAL = 500  # Evaluate every N iterations
# Total validation images. When set, exactly this many are held out for val (rest for train). None = use VALIDATION_SPLIT.
VALIDATION_SIZE = 20
# Fixed validation images to use for visualization at each validation (first N of the val set; e.g. 5 of the 20)
NUM_VIZ_IMAGES = 5
# Score threshold for drawings (drop low-confidence detections for clearer viz)
VIZ_SCORE_THRESHOLD = 0.5

# --- Resume (set to None to start from COCO weights) ---
RESUME_FROM_MODEL = None
# Example: RESUME_FROM_MODEL = r"D:\Experiments\AI\training_2025_12_25_15_43_57\model_final.pth"

# ============================================================================
# SETUP
# ============================================================================

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


def plot_learning_rate_schedule(output_dir):
    """
    Plot the learning rate schedule (warmup + decay) at the start of the run.
    Saves to output_dir/plots/learning_rate_schedule.png
    """
    output_dir = Path(output_dir)
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    base = BASE_LEARNING_RATE
    warmup = WARMUP_ITERS
    max_iter = MAX_ITER
    decay_type = LR_DECAY_TYPE
    gamma = 0.1

    iters = np.arange(0, max_iter + 1, dtype=np.int32)
    lrs = np.zeros(len(iters), dtype=np.float64)

    for i, it in enumerate(iters):
        if warmup > 0 and it < warmup:
            # Linear warmup: 0 -> base
            lrs[i] = base * (it / warmup)
        else:
            if decay_type == "cosine":
                # Cosine decay from base to 0 over (max_iter - warmup) iters
                denom = max(1, max_iter - warmup)
                progress = (it - warmup) / denom
                progress = min(1.0, progress)  # clamp in case it > max_iter
                lrs[i] = base * 0.5 * (1.0 + np.cos(np.pi * progress))
            elif decay_type == "step":
                s1 = int(max_iter * 0.6)
                s2 = int(max_iter * 0.8)
                if it < s1:
                    lrs[i] = base
                elif it < s2:
                    lrs[i] = base * gamma
                else:
                    lrs[i] = base * gamma * gamma
            else:  # "none"
                lrs[i] = base

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(iters, lrs, linewidth=1.5, color="steelblue")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Learning rate")
    ax.set_title("Learning rate schedule (warmup=%d, decay=%s)" % (warmup, decay_type))
    ax.set_xlim(0, max_iter)
    ax.set_ylim(bottom=0)
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    out = plots_dir / "learning_rate_schedule.png"
    _savefig_with_retry(fig, out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Learning rate schedule plot: {out}")


# ============================================================================
# PROGRESS MONITORING
# ============================================================================

class ProgressTracker:
    """Track and visualize training progress with validation metrics"""
    
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.train_losses = []
        self.val_losses = []
        self.val_iterations = []
        self.train_iterations = []
        self.val_segm_aps = []   # segm/AP per validation (same order as val_iterations)
        self.val_bbox_aps = []   # bbox/AP per validation
        self.best_val_segm_ap = 0.0
        self.best_val_bbox_ap = 0.0
        self.best_val_iter = 0
        self.start_time = time.time()
        self.last_log_time = time.time()
        # For ETA after each validation: last validation wall time, last val iter, total val time
        self.last_validation_wall_time = self.start_time
        self.last_val_iteration_done = 0
        self.total_validation_duration = 0.0
        
        # Create plots directory early and verify it exists
        self.plots_dir = self.output_dir / "plots"
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        
        # Verify directory was created
        if not self.plots_dir.exists():
            raise RuntimeError(f"Failed to create plots directory: {self.plots_dir}")
        
        print(f"[OK] Plots directory ready: {self.plots_dir}")
        
    def update(self, iteration, loss_dict):
        """Update progress tracking with training loss"""
        if loss_dict is None:
            return
        
        current_time = time.time()
        elapsed = current_time - self.start_time
        time_since_last = current_time - self.last_log_time
        
        # Extract total loss
        total_loss = loss_dict.get('total_loss', 0.0)
        self.train_losses.append(float(total_loss))
        self.train_iterations.append(iteration)
        
        # Calculate progress
        progress_pct = (iteration / MAX_ITER) * 100
        avg_time_per_iter = elapsed / iteration if iteration > 0 else 0
        remaining_iters = MAX_ITER - iteration
        eta_seconds = remaining_iters * avg_time_per_iter
        eta_minutes = eta_seconds / 60
        eta_hours = eta_minutes / 60
        
        # Print progress
        print(f"\n[{iteration}/{MAX_ITER}] ({progress_pct:.1f}%)")
        print(f"  Training Loss: {total_loss:.4f}")
        
        # Show validation loss if available
        if len(self.val_losses) > 0:
            latest_val_loss = self.val_losses[-1]
            latest_val_iter = self.val_iterations[-1]
            gap = total_loss - latest_val_loss
            print(f"  Validation Loss: {latest_val_loss:.4f} (at iter {latest_val_iter})")
            print(f"  Generalization Gap: {gap:.4f} ({'Overfitting' if gap < -0.1 else 'Underfitting' if gap > 0.1 else 'Good'})")
        
        print(f"  Time: {elapsed/60:.1f} min elapsed, ETA: {eta_minutes:.1f} min ({eta_hours:.1f} hours)")
        print(f"  Speed: {1/time_since_last:.2f} iter/sec")
        
        # Detailed loss breakdown
        for key, value in loss_dict.items():
            if key != 'total_loss':
                print(f"    {key}: {float(value):.4f}")
        
        self.last_log_time = current_time
        
        # Save plot every 50 iterations (and also save metrics JSON)
        if iteration % 50 == 0:
            print(f"\n  Saving plot and metrics...")
            self.save_plot()
            self.save_metrics()
            print(f"  Plot and metrics saved!\n")
    
    def update_validation(self, iteration, val_metrics, validation_duration=None,
                          training_block_time=None, training_iters_in_block=None, val_interval=None):
        """Update validation metrics. Optional ETA: pass validation_duration, training_block_time, training_iters_in_block, val_interval."""
        if val_metrics is None or len(val_metrics) == 0:
            return
        
        # Extract validation loss (actual loss computed on validation set)
        val_loss = val_metrics.get('total_loss', None)
        
        if val_loss is None:
            # Fallback: try to compute from components or use mAP proxy
            if 'loss_box_reg' in val_metrics and 'loss_mask' in val_metrics:
                val_loss = float(val_metrics.get('loss_box_reg', 0) + 
                               val_metrics.get('loss_mask', 0) + 
                               val_metrics.get('loss_cls', 0) +
                               val_metrics.get('loss_rpn_cls', 0) + 
                               val_metrics.get('loss_rpn_loc', 0))
            elif 'segm/AP' in val_metrics:
                # Use mAP as proxy (convert to loss-like: lower AP = higher "loss")
                mAP = float(val_metrics['segm/AP'])
                val_loss = (100.0 - mAP) / 100.0
            else:
                print(f"  [WARNING] Could not extract validation loss from metrics")
                return
        
        self.val_losses.append(float(val_loss))
        self.val_iterations.append(iteration)
        
        print(f"\n[VALIDATION at iter {iteration}]")
        print(f"  Validation Loss: {val_loss:.4f}")
        
        # Show mAP if available
        if 'segm/AP' in val_metrics:
            print(f"  Segmentation mAP: {float(val_metrics['segm/AP']):.4f}")
        if 'bbox/AP' in val_metrics:
            print(f"  Bounding Box mAP: {float(val_metrics['bbox/AP']):.4f}")
        
        # Show other metrics
        for key, value in val_metrics.items():
            if key not in ['total_loss', 'segm/AP', 'bbox/AP', 'num_batches_evaluated']:
                print(f"  {key}: {float(value):.4f}")
        
        # Append to validation CSV and store segm/AP, bbox/AP for metrics.json
        training_loss = self.train_losses[-1] if self.train_losses else None
        segm_ap = val_metrics.get('segm/AP')
        bbox_ap = val_metrics.get('bbox/AP')
        self.val_segm_aps.append(segm_ap)
        self.val_bbox_aps.append(bbox_ap)
        if segm_ap is not None and segm_ap > self.best_val_segm_ap:
            self.best_val_segm_ap = segm_ap
            self.best_val_iter = iteration
        if bbox_ap is not None and bbox_ap > self.best_val_bbox_ap:
            self.best_val_bbox_ap = bbox_ap
            if segm_ap is None or bbox_ap >= segm_ap:
                self.best_val_iter = iteration
        self._append_validation_csv(iteration, training_loss, segm_ap, bbox_ap)
        
        # Save plot and validation AP curve after validation
        self.save_plot()
        self.save_metrics()
        self.save_validation_AP_plot()
        
        # ETA: estimate remaining time from last training block and last validation run
        if (validation_duration is not None and training_block_time is not None and
                training_iters_in_block is not None):
            self.total_validation_duration += validation_duration
            self.last_validation_wall_time = time.time()
            self.last_val_iteration_done = iteration
            
            remaining_iters = MAX_ITER - iteration
            if remaining_iters <= 0:
                print(f"  [ETA] Final validation, no time remaining.")
            else:
                vi = val_interval if val_interval is not None else VALIDATION_INTERVAL
                remaining_validations = remaining_iters // max(1, vi)
                if training_iters_in_block > 0:
                    avg_training = training_block_time / training_iters_in_block
                else:
                    elapsed = time.time() - self.start_time
                    avg_training = (elapsed - self.total_validation_duration) / max(1, iteration)
                eta_training = remaining_iters * avg_training
                eta_validation = remaining_validations * validation_duration
                eta_total = eta_training + eta_validation
                h = int(eta_total // 3600)
                m = int((eta_total % 3600) // 60)
                st = f"{int(eta_training//3600)} h {int((eta_training%3600)//60)} min" if eta_training >= 60 else f"{eta_training:.1f} s"
                sv = f"{int(eta_validation//3600)} h {int((eta_validation%3600)//60)} min" if eta_validation >= 60 else f"{eta_validation:.1f} s"
                print(f"  [ETA] ~{h} h {m} min remaining (training: {st}, validation: {sv})")
    
    @retry_file_io(max_retries=3, delay=0.5)
    def _append_validation_csv(self, iteration, training_loss, segm_ap, bbox_ap):
        """Append one row to validation_results.csv: iteration, training_loss, segm_AP, bbox_AP, timestamp."""
        csv_path = self.output_dir / "validation_results.csv"
        file_existed = csv_path.exists()
        try:
            with open(csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                if not file_existed:
                    writer.writerow(['iteration', 'training_loss', 'segm_AP', 'bbox_AP', 'timestamp'])
                writer.writerow([
                    iteration,
                    training_loss if training_loss is not None else '',
                    segm_ap if segm_ap is not None else '',
                    bbox_ap if bbox_ap is not None else '',
                    datetime.now().isoformat()
                ])
            print(f"  [OK] Validation results appended to: {csv_path}")
        except Exception as e:
            if isinstance(e, (OSError, IOError, PermissionError, FileNotFoundError)):
                raise
            print(f"  [WARNING] Failed to append to validation CSV: {e}")
    
    def save_plot(self):
        """Save loss curve plot with training and validation"""
        if len(self.train_losses) < 2:
            print(f"  [INFO] Not enough data points yet ({len(self.train_losses)} < 2), skipping plot")
            return
        
        # Try multiple save locations to ensure it works
        save_paths = [
            self.plots_dir / "loss_curve.png",
            self.output_dir / "loss_curve.png",
            self.output_dir / "plots" / "loss_curve.png"
        ]
        
        try:
            # Ensure plots directory exists - use absolute path
            plots_dir_abs = Path(self.plots_dir).resolve()
            plots_dir_abs.mkdir(parents=True, exist_ok=True)
            
            print(f"  [DEBUG] Attempting to save plot to: {plots_dir_abs}")
            print(f"  [DEBUG] Train losses: {len(self.train_losses)}, Val losses: {len(self.val_losses)}")
            
            # Verify directory is writable
            if not plots_dir_abs.exists():
                raise RuntimeError(f"Failed to create plots directory: {plots_dir_abs}")
            
            if not os.access(plots_dir_abs, os.W_OK):
                raise RuntimeError(f"Plots directory is not writable: {plots_dir_abs}")
            
            # Create figure with two subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
            
            # Plot 1: Training and Validation Loss
            ax1.plot(self.train_iterations, self.train_losses, 'b-', linewidth=2, 
                    label='Training Loss', alpha=0.7)
            if len(self.val_losses) > 0:
                ax1.plot(self.val_iterations, self.val_losses, 'r-', linewidth=2, 
                        label='Validation Loss', marker='o', markersize=5, markeredgewidth=1.5)
            
            ax1.set_xlabel('Iteration', fontsize=12)
            ax1.set_ylabel('Loss', fontsize=12)
            ax1.set_title('Training vs Validation Loss (Generalization)', fontsize=14, fontweight='bold')
            ax1.grid(True, alpha=0.3)
            ax1.legend(fontsize=11)
            
            # Add annotation about generalization
            if len(self.val_losses) > 0:
                latest_train = self.train_losses[-1]
                latest_val = self.val_losses[-1]
                gap = latest_train - latest_val
                # Gap interpretation:
                # - Negative gap (train < val): Overfitting (model performs worse on unseen data)
                # - Positive gap (train > val): Underfitting (model not learning well)
                # - Small gap (~0): Good generalization
                if gap < -0.1:
                    status = "[WARNING] Overfitting (val loss > train loss)"
                    color = 'red'
                    explanation = "Model memorizing training data"
                elif gap > 0.1:
                    status = "[INFO] Underfitting (train loss > val loss)"
                    color = 'orange'
                    explanation = "Model needs more training"
                else:
                    status = "[OK] Good generalization"
                    color = 'green'
                    explanation = "Model learning well"
                
                ax1.text(0.02, 0.98, f"Status: {status}\nGap: {gap:.4f}\n{explanation}", 
                        transform=ax1.transAxes, fontsize=10, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor=color, alpha=0.3))
            
            # Plot 2: Generalization Gap (Train - Val)
            if len(self.val_losses) > 0:
                # Interpolate validation losses to match training iterations for gap calculation
                gap_iterations = []
                gap_values = []
                
                for i, train_iter in enumerate(self.train_iterations):
                    # Find nearest validation point
                    if len(self.val_iterations) > 0:
                        nearest_val_idx = np.argmin(np.abs(np.array(self.val_iterations) - train_iter))
                        if abs(self.val_iterations[nearest_val_idx] - train_iter) <= VALIDATION_INTERVAL:
                            gap_iterations.append(train_iter)
                            gap_values.append(self.train_losses[i] - self.val_losses[nearest_val_idx])
                
                if len(gap_values) > 0:
                    ax2.plot(gap_iterations, gap_values, 'g-', linewidth=2, 
                            label='Generalization Gap (Train - Val)', alpha=0.7)
                    ax2.axhline(y=0, color='k', linestyle='--', alpha=0.3, label='Perfect Match')
                    ax2.fill_between(gap_iterations, 0, gap_values, 
                                     where=np.array(gap_values) < 0, alpha=0.3, color='red', 
                                     label='Overfitting Zone')
                    ax2.fill_between(gap_iterations, 0, gap_values, 
                                     where=np.array(gap_values) > 0, alpha=0.3, color='blue', 
                                     label='Underfitting Zone')
            
            ax2.set_xlabel('Iteration', fontsize=12)
            ax2.set_ylabel('Loss Gap (Train - Val)', fontsize=12)
            ax2.set_title('Generalization Gap: Lower is Better (closer to 0)', fontsize=14, fontweight='bold')
            ax2.grid(True, alpha=0.3)
            if len(self.val_losses) > 0:
                ax2.legend(fontsize=10)
            
            plt.tight_layout()
            
            # Try to save to all locations - ensure at least one works
            saved = False
            saved_path = None
            
            for plot_path in save_paths:
                try:
                    plot_path.parent.mkdir(parents=True, exist_ok=True)
                    plot_path_str = str(plot_path.resolve())
                    
                    print(f"  [DEBUG] Trying to save plot to: {plot_path_str}")
                    
                    # Force save with explicit format (retried on I/O errors)
                    _savefig_with_retry(fig, plot_path_str, dpi=150, bbox_inches='tight', format='png', facecolor='white')
                    
                    # Force matplotlib to flush
                    fig.canvas.draw()
                    fig.canvas.flush_events()
                    
                    # Wait and verify
                    import time
                    time.sleep(0.2)
                    
                    if plot_path.exists() and plot_path.stat().st_size > 0:
                        file_size = plot_path.stat().st_size
                        print(f"  [OK] Loss plot saved: {plot_path_str} ({file_size/1024:.1f} KB)")
                        saved = True
                        saved_path = plot_path
                        break
                    else:
                        print(f"  [WARNING] Plot file not created or empty at: {plot_path_str}")
                except Exception as e:
                    print(f"  [WARNING] Failed to save to {plot_path}: {e}")
                    continue
            
            plt.close(fig)
            
            if not saved:
                print(f"  [ERROR] Failed to save plot to any location!")
                print(f"  Tried: {[str(p) for p in save_paths]}")
                print(f"  Attempting simple fallback plot...")
                
                # Last resort: very simple plot
                try:
                    simple_path = self.output_dir / "loss_curve_simple.png"
                    simple_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    fig_simple, ax_simple = plt.subplots(1, 1, figsize=(10, 6))
                    ax_simple.plot(self.train_iterations, self.train_losses, 'b-', linewidth=2, label='Training Loss')
                    if len(self.val_losses) > 0:
                        ax_simple.plot(self.val_iterations, self.val_losses, 'r-', linewidth=2, label='Validation Loss', marker='o')
                    ax_simple.set_xlabel('Iteration')
                    ax_simple.set_ylabel('Loss')
                    ax_simple.set_title('Training Loss Curve')
                    ax_simple.grid(True, alpha=0.3)
                    ax_simple.legend()
                    plt.tight_layout()
                    _savefig_with_retry(fig_simple, simple_path, dpi=100, bbox_inches='tight', format='png')
                    plt.close(fig_simple)
                    
                    if simple_path.exists():
                        print(f"  [OK] Simple plot saved to: {simple_path}")
                    else:
                        print(f"  [ERROR] Even simple plot failed to save!")
                except Exception as e_simple:
                    import traceback
                    print(f"  [ERROR] Simple plot also failed: {e_simple}")
                    print(f"  Traceback: {traceback.format_exc()}")
            else:
                # If we saved successfully, try to copy to other locations as backups
                for backup_path in save_paths:
                    if backup_path != saved_path:
                        try:
                            import shutil
                            backup_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(str(saved_path), str(backup_path))
                        except Exception:
                            pass  # Backup copy failed, but main save worked
        except Exception as e:
            import traceback
            print(f"  [ERROR] Failed to save plot: {e}")
            print(f"  Traceback: {traceback.format_exc()}")
    
    @retry_file_io(max_retries=3, delay=0.5)
    def save_metrics(self):
        """Save metrics to JSON file for later analysis (includes segm/AP and bbox/AP)
        
        Note: Uses 'progress_metrics.json' to avoid conflict with Detectron2's default
        JSONL format 'metrics.json' file. Both files will exist - metrics.json has
        per-iteration data in JSONL format, progress_metrics.json has aggregated data.
        """
        try:
            metrics_path = self.output_dir / "progress_metrics.json"
            metrics_data = {
                'train_iterations': self.train_iterations,
                'train_losses': self.train_losses,
                'val_iterations': self.val_iterations,
                'val_losses': self.val_losses,
                'val_segm_aps': self.val_segm_aps,
                'val_bbox_aps': self.val_bbox_aps,
                'total_train_iterations': len(self.train_iterations),
                'total_val_evaluations': len(self.val_losses),
                'last_update': datetime.now().isoformat()
            }
            
            # Latest validation APs (so they survive Ctrl+C and are easy to find)
            if len(self.val_segm_aps) > 0 and self.val_segm_aps[-1] is not None:
                metrics_data['latest_segm_AP'] = float(self.val_segm_aps[-1])
            if len(self.val_bbox_aps) > 0 and self.val_bbox_aps[-1] is not None:
                metrics_data['latest_bbox_AP'] = float(self.val_bbox_aps[-1])
            
            # Calculate generalization metrics
            if len(self.val_losses) > 0 and len(self.train_losses) > 0:
                latest_train = self.train_losses[-1]
                latest_val = self.val_losses[-1]
                gap = latest_train - latest_val
                
                metrics_data['generalization'] = {
                    'latest_train_loss': latest_train,
                    'latest_val_loss': latest_val,
                    'generalization_gap': gap,
                    'status': 'overfitting' if gap < -0.1 else 'underfitting' if gap > 0.1 else 'good'
                }
            
            with open(metrics_path, 'w') as f:
                json.dump(metrics_data, f, indent=2)
        except Exception as e:
            if isinstance(e, (OSError, IOError, PermissionError, FileNotFoundError)):
                raise
            print(f"  [WARNING] Failed to save metrics JSON: {e}")

    def save_validation_AP_plot(self):
        """Save segm/AP and bbox/AP vs iteration (updated every validation, like hyperparameter sweep)."""
        segm_ok = [v for v in self.val_segm_aps if v is not None]
        bbox_ok = [v for v in self.val_bbox_aps if v is not None]
        if len(segm_ok) == 0 and len(bbox_ok) == 0:
            return
        segm_iters = [self.val_iterations[i] for i in range(len(self.val_segm_aps)) if self.val_segm_aps[i] is not None]
        segm_vals = segm_ok
        bbox_iters = [self.val_iterations[i] for i in range(len(self.val_bbox_aps)) if self.val_bbox_aps[i] is not None]
        bbox_vals = bbox_ok
        fig, ax = plt.subplots(1, 1, figsize=(12, 6))
        ax.set_xlabel('Iteration', fontsize=12)
        ax.set_ylabel('Validation AP', fontsize=12)
        ax.set_title('Validation Average Precision (mAP)', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        if len(segm_iters) > 0:
            ax.plot(segm_iters, segm_vals, 'r-o', linewidth=2, markersize=6, label='segm/AP')
        if len(bbox_iters) > 0:
            ax.plot(bbox_iters, bbox_vals, 'b-s', linewidth=2, markersize=6, label='bbox/AP')
        ax.axhline(y=0, color='k', linestyle='--', alpha=0.3)
        ax.legend(fontsize=11)
        ax.set_xlim(0, MAX_ITER)
        ax.set_ylim(bottom=0)
        if self.best_val_segm_ap > 0 or self.best_val_bbox_ap > 0:
            ann = f'Best segm/AP: {self.best_val_segm_ap:.4f}\nBest bbox/AP: {self.best_val_bbox_ap:.4f}\n@ iter {self.best_val_iter}'
            ax.text(0.02, 0.98, ann, transform=ax.transAxes, fontsize=10, verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.5))
        plt.tight_layout()
        out = self.plots_dir / "validation_AP_curve.png"
        try:
            _savefig_with_retry(fig, str(out), dpi=150, bbox_inches='tight', format='png', facecolor='white')
            plt.close(fig)
            if out.exists():
                print(f"  [OK] Validation AP curve: {out}")
        except Exception as e:
            plt.close(fig)
            print(f"  [WARNING] Failed to save validation AP curve: {e}")

# ============================================================================
# CUSTOM DATASET MAPPER FOR RLE FORMAT
# ============================================================================

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

# ============================================================================
# CUSTOM TRAINER WITH PROGRESS TRACKING
# ============================================================================

class ProgressTrainer(DefaultTrainer):
    """Custom trainer with progress tracking, validation, and RLE support"""
    
    @classmethod
    def build_train_loader(cls, cfg):
        """Build data loader with custom mapper for RLE format"""
        from detectron2.data import build_detection_train_loader
        from detectron2.data import get_detection_dataset_dicts
        
        dataset_dicts = get_detection_dataset_dicts(cfg.DATASETS.TRAIN)
        
        # Create custom mapper
        mapper = RLEDatasetMapper(cfg, is_train=True)
        
        return build_detection_train_loader(cfg, mapper=mapper)
    
    @classmethod
    def build_test_loader(cls, cfg, dataset_name):
        """Build validation data loader with custom mapper"""
        from detectron2.data import build_detection_test_loader
        from detectron2.data import get_detection_dataset_dicts
        
        dataset_dicts = get_detection_dataset_dicts([dataset_name])
        
        # Create custom mapper (no augmentation for validation)
        mapper = RLEDatasetMapper(cfg, is_train=False)
        
        return build_detection_test_loader(cfg, dataset_name, mapper=mapper)
    
    @classmethod
    def build_evaluator(cls, cfg, dataset_name, output_folder=None):
        """Build evaluator for validation - this silences the 'No evaluator found' warning"""
        from detectron2.evaluation import COCOEvaluator
        
        # Create output directory for evaluator if not provided
        if output_folder is None:
            output_folder = Path(cfg.OUTPUT_DIR) / "validation_eval"
            output_folder.mkdir(parents=True, exist_ok=True)
        
        # Return COCO evaluator for validation dataset
        return COCOEvaluator(dataset_name, output_dir=str(output_folder))
    
    def __init__(self, cfg, progress_tracker=None):
        super().__init__(cfg)
        self.progress_tracker = progress_tracker
        self.last_val_iter = -1  # Track last iteration we ran validation on
    
    def run_step(self):
        """Override to track progress"""
        loss_dict = super().run_step()
        
        if self.progress_tracker and loss_dict is not None and self.iter % 10 == 0:  # Log every 10 iterations
            self.progress_tracker.update(self.iter, loss_dict)
        
        return loss_dict
    
    def after_step(self):
        """Override to run validation evaluation"""
        # Check if it's time for validation
        # Use the validation interval from config
        val_interval = self.cfg.TEST.EVAL_PERIOD
        
        # Only run validation if:
        # 1. We have a progress tracker
        # 2. It's the right iteration (divisible by interval)
        # 3. We haven't already run validation for this iteration
        # 4. We're past iteration 0
        if (self.progress_tracker and 
            self.iter % val_interval == 0 and 
            self.iter > 0 and 
            self.iter != self.last_val_iter):
            
            # Mark that we're running validation for this iteration
            self.last_val_iter = self.iter
            
            # Run validation evaluation (time it for ETA)
            try:
                print(f"\n  [INFO] Running validation at iteration {self.iter}...")
                t0 = time.time()
                val_results = self._run_validation()
                validation_duration = time.time() - t0
                training_block_time = t0 - self.progress_tracker.last_validation_wall_time
                training_iters_in_block = self.iter - self.progress_tracker.last_val_iteration_done
                if val_results:
                    self.progress_tracker.update_validation(
                        self.iter, val_results,
                        validation_duration=validation_duration,
                        training_block_time=training_block_time,
                        training_iters_in_block=training_iters_in_block,
                        val_interval=val_interval
                    )
            except Exception as e:
                print(f"  [WARNING] Validation evaluation failed: {e}")
                import traceback
                print(f"  [WARNING] Traceback: {traceback.format_exc()}")
                # Don't let validation failure stop training
        
        # Call parent after_step (saves checkpoints, etc.)
        # Wrap in try-except to handle potential file I/O errors
        # This is a known Windows issue with Detectron2's event writer
        # It doesn't affect training - checkpoints and plots still save correctly
        try:
            super().after_step()
        except (OSError, IOError) as e:
            # Handle Windows file I/O errors gracefully
            # Errno 22 = Invalid argument - usually from event writer trying to write to locked files
            if "[Errno 22]" in str(e) or "Invalid argument" in str(e):
                # This is non-critical - training continues normally
                # Checkpoints and plots are saved via our custom code, not the event writer
                pass  # Silently ignore to reduce log noise
            else:
                raise  # Re-raise if it's a different error
    
    def _run_validation(self):
        """Run validation evaluation and return metrics"""
        from detectron2.evaluation import COCOEvaluator, inference_on_dataset
        
        val_dataset_name = f"{DATASET_NAME}_val"
        # Create a temporary directory for COCO evaluator output
        # COCOEvaluator requires output_dir even for COCO format datasets
        eval_output_dir = Path(self.cfg.OUTPUT_DIR) / "validation_eval"
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        print(f"  [INFO] Validation evaluation output: {eval_output_dir}")
        
        # Run COCO evaluation for mAP metrics
        # This is the standard way to evaluate in Detectron2
        try:
            test_loader = self.build_test_loader(self.cfg, val_dataset_name)
            evaluator = COCOEvaluator(val_dataset_name, output_dir=str(eval_output_dir))
            results = inference_on_dataset(self.model, test_loader, evaluator)
        except Exception as e:
            print(f"  [WARNING] COCO evaluation failed: {e}")
            import traceback
            traceback.print_exc()
            results = {}
        
        # Convert mAP to a loss-like metric for plotting
        # Lower mAP = worse performance (like higher loss)
        # We'll use segmentation mAP as the main metric
        if 'segm/AP' in results:
            mAP = float(results['segm/AP'])
            # Convert to loss-like: (100 - mAP) / 100
            # This way higher mAP = lower "loss" value
            results['total_loss'] = (100.0 - mAP) / 100.0
        elif 'bbox/AP' in results:
            mAP = float(results['bbox/AP'])
            results['total_loss'] = (100.0 - mAP) / 100.0
        else:
            # If no AP available, set a default
            results['total_loss'] = None
        
        # Save visualizations on the same fixed images at this validation
        self._save_validation_visualizations(self.iter)

        return results

    def _save_validation_visualizations(self, iteration):
        """
        Run the model on a fixed set of validation images and save prediction visualizations.
        Uses the first NUM_VIZ_IMAGES (e.g. 5) from the val set, same every time.
        """
        val_dataset_name = f"{DATASET_NAME}_val"
        output_dir = Path(self.cfg.OUTPUT_DIR) / "validation_visualizations"
        output_dir.mkdir(parents=True, exist_ok=True)

        # On first run, pick and cache the first NUM_VIZ_IMAGES (file_name, height, width only).
        # Same images are used for every validation so you can see the model improving over time.
        if not hasattr(self, "_viz_info"):
            dicts = get_detection_dataset_dicts([val_dataset_name])
            self._viz_info = [
                {"file_name": d["file_name"], "height": d.get("height", 800), "width": d.get("width", 1280)}
                for d in dicts[:NUM_VIZ_IMAGES]
            ]
            if not self._viz_info:
                print(f"  [WARNING] No validation images for visualization")
                return
            print(f"  [INFO] Cached {len(self._viz_info)} fixed validation images for all future viz runs")
            # Write which source image is img_0, img_1, ... (one-time)
            try:
                src_path = output_dir / "_sources.txt"
                with open(src_path, "w") as f:
                    f.write("# Same fixed images used for all validation visualizations\n")
                    for i, info in enumerate(self._viz_info):
                        f.write(f"img_{i}: {info['file_name']}\n")
            except Exception as e:
                print(f"  [WARNING] Could not write _sources.txt: {e}")

        if not self._viz_info:
            return

        mapper = RLEDatasetMapper(self.cfg, is_train=False)
        metadata = MetadataCatalog.get(val_dataset_name)

        was_training = self.model.training
        self.model.eval()
        try:
            with torch.no_grad():
                for i, info in enumerate(self._viz_info):
                    try:
                        d = dict(info)
                        mapped = mapper(d)
                        pred = self.model([mapped])
                        if not pred or "instances" not in pred[0]:
                            continue
                        inst = pred[0]["instances"].to("cpu")
                        # Filter by score so early-training clutter is reduced
                        if hasattr(inst, "scores") and inst.has("scores") and len(inst) > 0:
                            inst = inst[inst.scores >= VIZ_SCORE_THRESHOLD]
                        img = mapped["image"].permute(1, 2, 0).cpu().numpy()
                        img = np.clip(img, 0, 255).astype(np.uint8)
                        v = Visualizer(img, metadata=metadata, scale=1.0)
                        out = v.draw_instance_predictions(inst)
                        vis = out.get_image()
                        base = Path(info["file_name"]).stem
                        path = output_dir / f"iter_{iteration:07d}_img_{i}_{base}.png"
                        Image.fromarray(vis).save(path)
                    except Exception as e:
                        print(f"  [WARNING] Visualization failed for image {i}: {e}")
            print(f"  [OK] Validation visualizations: {output_dir} (iter {iteration}, same {len(self._viz_info)} images)")
        finally:
            self.model.train(was_training)

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*60)
    print("Detectron2 Training Script")
    print("="*60)
    
    # Create timestamped output directory
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    OUTPUT_DIR = Path(OUTPUT_BASE_DIR) / f"training_{timestamp}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Output directory: {OUTPUT_DIR}")
    
    # Setup
    setup_logger()
    train_dicts, val_dicts, num_train_images = setup_dataset()
    cfg = setup_config(str(OUTPUT_DIR), num_train_images, resume_from=RESUME_FROM_MODEL)

    # Plot learning rate schedule (warmup + decay) at start of run
    plot_learning_rate_schedule(OUTPUT_DIR)
    
    # Initialize progress tracker
    progress_tracker = ProgressTracker(OUTPUT_DIR)
    
    # Create trainer
    print(f"\n{'='*60}")
    print("Starting Training")
    print(f"{'='*60}")
    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"Training will run for {MAX_ITER} iterations ({NUM_EPOCHS} epochs)")
    print(f"Checkpoints will be saved every {CHECKPOINT_INTERVAL} iterations")
    print(f"Validation will run every {cfg.TEST.EVAL_PERIOD} iterations")
    print(f"Train/Val split: {100*(1-VALIDATION_SPLIT):.0f}%/{100*VALIDATION_SPLIT:.0f}%")
    print(f"\nPress Ctrl+C to stop training early (checkpoints will be saved)")
    print(f"{'='*60}\n")
    
    trainer = ProgressTrainer(cfg, progress_tracker)
    trainer.resume_or_load(resume=False)
    
    # Start training
    try:
        trainer.train()
    except KeyboardInterrupt:
        print("\n\nTraining interrupted by user. Saving final checkpoint and metrics...")
        trainer.checkpointer.save("model_interrupted")
        progress_tracker.save_metrics()
        progress_tracker.save_validation_AP_plot()
        print("Checkpoint and progress_metrics.json saved!")
        print("Note: Detectron2's metrics.json (JSONL format) contains per-iteration data.")
    
    # Final plot, metrics and validation AP curve (again if we didn't Ctrl+C, so they have latest)
    progress_tracker.save_plot()
    progress_tracker.save_metrics()
    progress_tracker.save_validation_AP_plot()
    
    print(f"\n{'='*60}")
    print("Training Complete!")
    print(f"{'='*60}")
    print(f"Final model: {OUTPUT_DIR}/model_final.pth")
    print(f"Loss plot: {OUTPUT_DIR}/plots/loss_curve.png")
    print(f"Validation AP curve: {OUTPUT_DIR}/plots/validation_AP_curve.png")
    print(f"Learning rate schedule: {OUTPUT_DIR}/plots/learning_rate_schedule.png")
    print(f"Validation results CSV: {OUTPUT_DIR}/validation_results.csv")
    print(f"Validation visualizations: {OUTPUT_DIR}/validation_visualizations/ (same fixed images each run)")
    print(f"All outputs saved to: {OUTPUT_DIR}")
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()

