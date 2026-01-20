"""
Hyperparameter Sweep for Detectron2 Training
Sweeps over learning rates and anchor sizes, reusing existing training infrastructure

OPTIMIZATIONS FOR FAST SWEEPS:
- Uses 25% of training images (SWEEP_TRAIN_FRACTION = 0.25)
- Trains for 25% of full epochs (SWEEP_EPOCH_FRACTION = 0.25)
- Uses 2% validation split (~400 images instead of 2000)
- Result: ~16x faster than full training while still providing reliable hyperparameter comparisons
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
# CONFIGURATION
# ============================================================================

# Dataset paths (using Detectron_Trial_2 as specified)
DATASET_NAME = "spray_train"
ANNOTATIONS_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\blur_annotations.json"
IMAGES_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\images"

# Training settings
BATCH_SIZE = 2
NUM_EPOCHS = 1  # Base number of epochs (will be reduced for sweep)
SWEEP_EPOCH_FRACTION = 0.25  # Train for 25% of full epochs (20-30% range)
SWEEP_TRAIN_FRACTION = 0.25  # Use 25% of training images for sweeps (20-30% range for faster sweeps)

# Hyperparameter sweep ranges
LEARNING_RATES = [0.005, 0.0025, 0.001, 0.0005]
ANCHOR_SIZES = [
    [[8, 16, 32, 64]],
    [[8, 16, 32, 64, 128]],
    [[16, 32, 64, 128]]
]

# Output directories
OUTPUT_BASE_DIR = r"D:\Experiments\AI\Hyperparameters"
# CSV paths will be set dynamically in main() after creating timestamped sweep folder
SWEEP_RESULTS_CSV = None
SWEEP_SUMMARY_CSV = None

# Validation settings
# For hyperparameter sweeps, use a smaller validation set to speed up evaluation
# With ~20,000 total images:
#   0.1 = 2000 images (TOO SLOW for sweeps! ~2 hours per validation)
#   0.05 = 1000 images (still slow, ~1 hour per validation)
#   0.02 = 400 images (~45 minutes per validation - still slow!)
#   0.01 = 200 images (~20-25 minutes per validation - much better for sweeps)
VALIDATION_SPLIT = 0.01  # 1% = ~200 images (faster validation, still enough for reliable metrics)
# Validation interval: For sweeps, validate less frequently to save time
# Options:
#   - 150 = 3-4 validations per run (12 hours total for all combinations)
#   - 9999 = Only validate at the end (12 validations total = ~3 hours, but less monitoring)
#   - 50 = Frequent validation (33 hours total - TOO SLOW!)
VALIDATION_INTERVAL = 150  # Evaluate every N iterations (reduced frequency for faster sweeps)
# Set to 9999 to only validate at the end of each run (fastest, but no mid-training metrics)

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
    
    # For hyperparameter sweeps, use a subset of training images to speed up training
    # This is fine for hyperparameter comparison - we just need relative performance
    if SWEEP_TRAIN_FRACTION < 1.0:
        original_train_count = len(train_dicts)
        train_subset_size = int(len(train_dicts) * SWEEP_TRAIN_FRACTION)
        # Use first N images from shuffled training set (already randomized)
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
        self.val_aps = []  # Validation AP (segmentation mAP)
        self.val_iterations = []
        self.start_time = time.time()
        
        # Best metrics tracking
        self.best_val_ap = 0.0
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
        
        # Plot 2: Validation AP
        self.ax2.set_xlabel('Iteration')
        self.ax2.set_ylabel('Validation AP')
        self.ax2.set_title('Validation Average Precision (mAP)')
        self.ax2.grid(True, alpha=0.3)
        self.line2, = self.ax2.plot([], [], 'r-o', linewidth=2, markersize=6, label='Validation AP')
        self.ax2.axhline(y=0, color='k', linestyle='--', alpha=0.3)
        self.ax2.legend()
        self.ax2.set_xlim(0, max_iter)  # Initialize x-axis to start at 0
        
        plt.tight_layout()
        
        # Create plots directory FIRST (before trying to save)
        self.plots_dir = self.output_dir / "plots"
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        
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
        
        # Print progress every 25 iterations to show it's working
        if iteration % 25 == 0:
            print(f"\n  [Plot Tracker] Training loss at iter {iteration}: {total_loss:.4f} (total points: {len(self.train_losses)})")
        
        # Update plot
        self.line1.set_data(self.train_iterations, self.train_losses)
        self.ax1.relim()
        
        # Set x-axis limits BEFORE autoscale to ensure it starts at 0
        if len(self.train_iterations) > 0:
            max_iter_val = max(self.max_iter, max(self.train_iterations))
            self.ax1.set_xlim(0, max_iter_val)
        else:
            self.ax1.set_xlim(0, self.max_iter)
        
        # Then autoscale only the y-axis (not x-axis)
        self.ax1.autoscale_view(scalex=False, scaley=True)
        
        # Save plot to file every 25 iterations (so you can always check the file)
        if iteration % 25 == 0 and self.plot_path is not None:
            try:
                self.fig.savefig(str(self.plot_path), dpi=150, bbox_inches='tight')
                if iteration % 50 == 0:  # Print path every 50 iterations
                    print(f"  [Plot] ✓ Saved live plot to: {self.plot_path}")
            except Exception as e:
                if iteration % 50 == 0:
                    print(f"  [Plot] ✗ Could not save live plot: {e}")
                    import traceback
                    traceback.print_exc()
    
    def update_validation(self, iteration: int, val_metrics: Dict):
        """Update validation metrics and refresh plot"""
        if val_metrics is None:
            return
        
        # Extract AP (prefer segm/AP, fallback to bbox/AP)
        ap = None
        if 'segm/AP' in val_metrics:
            ap = float(val_metrics['segm/AP'])
        elif 'bbox/AP' in val_metrics:
            ap = float(val_metrics['bbox/AP'])
        elif 'segm/AP50' in val_metrics:
            ap = float(val_metrics['segm/AP50'])
        elif 'bbox/AP50' in val_metrics:
            ap = float(val_metrics['bbox/AP50'])
        
        if ap is not None:
            self.val_aps.append(ap)
            self.val_iterations.append(iteration)
            
            # Update best AP
            if ap > self.best_val_ap:
                self.best_val_ap = ap
                self.best_val_iter = iteration
            
            # Update plot
            self.line2.set_data(self.val_iterations, self.val_aps)
            self.ax2.relim()
            
            # Set x-axis limits BEFORE autoscale to ensure it starts at 0
            if len(self.val_iterations) > 0:
                max_iter_val = max(self.max_iter, max(self.val_iterations))
                self.ax2.set_xlim(0, max_iter_val)
            else:
                self.ax2.set_xlim(0, self.max_iter)
            
            # Then autoscale only the y-axis (not x-axis)
            self.ax2.autoscale_view(scalex=False, scaley=True)
            
            # Add best AP annotation
            if len(self.val_aps) > 0:
                # Remove old annotation if exists
                for txt in self.ax2.texts:
                    if txt.get_text().startswith('Best'):
                        txt.remove()
                
                # Add new annotation
                self.ax2.text(0.02, 0.98, f'Best AP: {self.best_val_ap:.4f} @ iter {self.best_val_iter}',
                            transform=self.ax2.transAxes, fontsize=10,
                            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.5))
            
            # Refresh display
            print(f"\n  [Plot] Updating validation plot at iter {iteration}...")
            print(f"  [Plot] AP value: {ap:.4f}, Best AP: {self.best_val_ap:.4f}")
            print(f"  [Plot] Total validation points: {len(self.val_aps)}")
            
            # Always save plot to file when validation updates
            if self.plot_path is not None:
                try:
                    self.fig.savefig(str(self.plot_path), dpi=150, bbox_inches='tight')
                    print(f"  [Plot] ✓ Plot saved to: {self.plot_path}")
                except Exception as e:
                    print(f"  [Plot] ✗ Could not save plot: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"  [Plot] ⚠ Plot path not set, skipping save")
    
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
        
        final_val_ap = self.val_aps[-1] if len(self.val_aps) > 0 else 0.0
        
        return {
            'final_val_ap': final_val_ap,
            'best_val_ap': self.best_val_ap,
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
        """Override to capture validation results from Detectron2's built-in validation"""
        val_interval = self.cfg.TEST.EVAL_PERIOD
        
        # Let Detectron2 handle validation automatically via cfg.TEST.EVAL_PERIOD
        # We'll capture results in the test() method override
        try:
            super().after_step()
        except (OSError, IOError) as e:
            if "[Errno 22]" in str(e) or "Invalid argument" in str(e):
                pass
            else:
                raise
        
        # Fallback: If validation should have run but we haven't captured results yet,
        # manually trigger it (this handles cases where test() override isn't called)
        if (self.plot_tracker and 
            self.iter % val_interval == 0 and 
            self.iter > 0 and 
            self.iter != self.last_val_iter):
            
            # Check if validation results were already captured
            if len(self.plot_tracker.val_aps) == 0 or self.plot_tracker.val_iterations[-1] != self.iter:
                print(f"\n  [Plot Tracker] Validation should have run at iter {self.iter}, but results not captured.")
                print(f"  [Plot Tracker] Manually running validation...")
                self.last_val_iter = self.iter
                try:
                    val_results = self._run_validation()
                    if val_results and isinstance(val_results, dict) and len(val_results) > 0:
                        self.plot_tracker.update_validation(self.iter, val_results)
                        print(f"  [Plot Tracker] Manual validation complete and plot updated!")
                    else:
                        print(f"  [WARNING] Manual validation returned empty results!")
                except Exception as e:
                    print(f"  [ERROR] Manual validation failed: {e}")
                    import traceback
                    traceback.print_exc()
    
    def after_train(self):
        """Override to handle Windows file I/O errors at end of training"""
        try:
            super().after_train()
        except (OSError, IOError) as e:
            if "[Errno 22]" in str(e) or "Invalid argument" in str(e):
                # Windows file handle issue - metrics were likely already written
                print(f"  [WARNING] File I/O error during after_train (Windows issue): {e}")
                print(f"  [WARNING] This is usually harmless - metrics were likely already saved")
            else:
                raise
    
    def test(self, cfg=None, model=None, evaluators=None):
        """Override test method to capture validation results"""
        # Use current config/model if not provided
        if cfg is None:
            cfg = self.cfg
        if model is None:
            model = self.model
        
        # Call parent test method - this runs validation automatically
        results = super().test(cfg, model, evaluators)
        
        # Capture results for plot tracker
        if self.plot_tracker and hasattr(self, 'iter') and results:
            print(f"\n  [Plot Tracker] Validation completed at iter {self.iter}")
            print(f"  [Plot Tracker] Results keys: {list(results.keys())}")
            
            # Extract AP value for logging
            ap_value = None
            if 'segm/AP' in results:
                ap_value = results['segm/AP']
                print(f"  [Plot Tracker] Segmentation mAP: {ap_value:.4f}")
            elif 'bbox/AP' in results:
                ap_value = results['bbox/AP']
                print(f"  [Plot Tracker] Bbox mAP: {ap_value:.4f}")
            
            # Update plot tracker with validation results
            self.plot_tracker.update_validation(self.iter, results)
            print(f"  [Plot Tracker] Plot updated successfully!")
        
        return results
    
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
            
            # Print all results for debugging
            print(f"\n    [Validation] Inference complete!")
            print(f"    [Validation] Results dictionary keys: {list(results.keys())}")
            print(f"    [Validation] Full results: {results}")
            
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
    
    # Calculate MAX_ITER (reduced for sweep)
    iterations_per_epoch = num_train_images // BATCH_SIZE
    max_iter_full = NUM_EPOCHS * iterations_per_epoch
    max_iter_sweep = int(max_iter_full * SWEEP_EPOCH_FRACTION)
    
    # Learning rate decay at 60% and 80% of training
    decay_step_1 = int(max_iter_sweep * 0.6)
    decay_step_2 = int(max_iter_sweep * 0.8)
    learning_rate_decay_steps = (decay_step_1, decay_step_2)
    
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
    val_interval = min(VALIDATION_INTERVAL, iterations_per_epoch)
    cfg.TEST.EVAL_PERIOD = val_interval
    
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
    
    training_time = time.time() - start_time
    
    # Run final validation if no validation has been run yet
    if len(plot_tracker.val_aps) == 0:
        print(f"\n  [Final Validation] No validation metrics captured during training.")
        print(f"  [Final Validation] Running final validation now...")
        try:
            val_results = trainer._run_validation()
            if val_results and isinstance(val_results, dict) and len(val_results) > 0:
                plot_tracker.update_validation(trainer.iter, val_results)
                print(f"  [Final Validation] ✓ Validation complete and metrics captured!")
            else:
                print(f"  [WARNING] Final validation returned empty results!")
        except Exception as e:
            print(f"  [ERROR] Final validation failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Get final metrics
    final_metrics = plot_tracker.get_final_metrics()
    plot_tracker.save_plot()
    plot_tracker.close()
    
    # Prepare results dictionary
    results = {
        'run_name': run_name,
        'learning_rate': learning_rate,
        'anchor_sizes': str(anchor_sizes),
        'final_val_ap': final_metrics['final_val_ap'],
        'best_val_ap': final_metrics['best_val_ap'],
        'best_val_iter': final_metrics['best_val_iter'],
        'training_time_seconds': final_metrics['training_time_seconds'],
        'training_time_minutes': final_metrics['training_time_minutes'],
        'max_iter': max_iter,
        'output_dir': str(output_dir)
    }
    
    # Save to CSV immediately (append mode for resume safety)
    save_run_to_csv(results)
    
    print(f"\n{'='*80}")
    print(f"RUN {run_number}/{total_runs} COMPLETE")
    print(f"{'='*80}")
    print(f"Final Validation AP: {final_metrics['final_val_ap']:.4f}")
    print(f"Best Validation AP: {final_metrics['best_val_ap']:.4f} @ iter {final_metrics['best_val_iter']}")
    print(f"Training time: {final_metrics['training_time_minutes']:.1f} minutes")
    print(f"{'='*80}\n")
    
    return results


def save_run_to_csv(results: Dict):
    """Append a single run's results to the CSV file"""
    csv_path = SWEEP_RESULTS_CSV
    
    # Create file with headers if it doesn't exist
    file_exists = csv_path.exists()
    
    with open(csv_path, 'a', newline='') as f:
        fieldnames = [
            'run_name', 'learning_rate', 'anchor_sizes', 'final_val_ap',
            'best_val_ap', 'best_val_iter', 'training_time_seconds',
            'training_time_minutes', 'max_iter', 'output_dir', 'timestamp'
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
    
    # Save summary CSV
    summary_path = SWEEP_SUMMARY_CSV
    with open(summary_path, 'w', newline='') as f:
        fieldnames = [
            'run_name', 'learning_rate', 'anchor_sizes', 'final_val_ap',
            'best_val_ap', 'best_val_iter', 'training_time_minutes'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for results in results_list:
            writer.writerow({
                'run_name': results['run_name'],
                'learning_rate': results['learning_rate'],
                'anchor_sizes': results['anchor_sizes'],
                'final_val_ap': results['final_val_ap'],
                'best_val_ap': results['best_val_ap'],
                'best_val_iter': results['best_val_iter'],
                'training_time_minutes': results['training_time_minutes']
            })
    
    print(f"[OK] Summary CSV saved: {summary_path}")
    
    # Create comparison plots
    create_comparison_plots(results_list)
    
    print(f"\n{'='*80}")
    print("SWEEP SUMMARY COMPLETE")
    print(f"{'='*80}\n")


def create_comparison_plots(results_list: List[Dict]):
    """Create comparison plots for all runs"""
    plots_dir = Path(OUTPUT_BASE_DIR) / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract data
    learning_rates = [r['learning_rate'] for r in results_list]
    anchor_sizes_str = [r['anchor_sizes'] for r in results_list]
    best_aps = [r['best_val_ap'] for r in results_list]
    final_aps = [r['final_val_ap'] for r in results_list]
    
    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Plot 1: AP vs Learning Rate
    ax1.scatter(learning_rates, best_aps, s=100, alpha=0.7, label='Best AP', c='blue')
    ax1.scatter(learning_rates, final_aps, s=100, alpha=0.7, label='Final AP', c='red', marker='x')
    ax1.set_xlabel('Learning Rate', fontsize=12)
    ax1.set_ylabel('Validation AP', fontsize=12)
    ax1.set_title('Validation AP vs Learning Rate', fontsize=14, fontweight='bold')
    ax1.set_xscale('log')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    
    # Add annotations for anchor sizes
    for i, (lr, ap, anchor_str) in enumerate(zip(learning_rates, best_aps, anchor_sizes_str)):
        ax1.annotate(f"Anchors:\n{anchor_str[:30]}", 
                    xy=(lr, ap), xytext=(5, 5), textcoords='offset points',
                    fontsize=8, alpha=0.7)
    
    # Plot 2: AP vs Anchor Configuration (grouped by anchor size)
    # Create unique anchor configurations
    unique_anchors = list(set(anchor_sizes_str))
    anchor_indices = {anchor: i for i, anchor in enumerate(unique_anchors)}
    
    x_positions = [anchor_indices[anchor] for anchor in anchor_sizes_str]
    
    ax2.scatter(x_positions, best_aps, s=100, alpha=0.7, label='Best AP', c='blue')
    ax2.scatter(x_positions, final_aps, s=100, alpha=0.7, label='Final AP', c='red', marker='x')
    ax2.set_xlabel('Anchor Configuration', fontsize=12)
    ax2.set_ylabel('Validation AP', fontsize=12)
    ax2.set_title('Validation AP vs Anchor Configuration', fontsize=14, fontweight='bold')
    ax2.set_xticks(range(len(unique_anchors)))
    ax2.set_xticklabels([f"Config {i+1}" for i in range(len(unique_anchors))], rotation=45, ha='right')
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    
    # Add legend for anchor configurations
    legend_text = "\n".join([f"Config {i+1}: {anchor[:50]}" for i, anchor in enumerate(unique_anchors)])
    ax2.text(1.02, 0.5, legend_text, transform=ax2.transAxes, fontsize=8,
            verticalalignment='center', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    
    # Save plot
    plot_path = plots_dir / "sweep_comparison.png"
    fig.savefig(str(plot_path), dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    print(f"[OK] Comparison plot saved: {plot_path}")


def check_existing_runs() -> List[Dict]:
    """Check for existing runs in CSV to enable resume"""
    if SWEEP_RESULTS_CSV is None or not SWEEP_RESULTS_CSV.exists():
        return []
    
    existing_runs = []
    with open(SWEEP_RESULTS_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_runs.append({
                'learning_rate': float(row['learning_rate']),
                'anchor_sizes': ast.literal_eval(row['anchor_sizes'])  # Safe parsing for list
            })
    
    return existing_runs


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
    
    # Create timestamped sweep folder (always create a new sweep per run)
    base_output_dir = Path(OUTPUT_BASE_DIR)
    sweep_timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    sweep_folder = base_output_dir / f"sweep_{sweep_timestamp}"
    sweep_folder.mkdir(parents=True, exist_ok=True)
    
    # Update global OUTPUT_BASE_DIR and CSV paths to point to this sweep folder
    OUTPUT_BASE_DIR = str(sweep_folder)
    SWEEP_RESULTS_CSV = sweep_folder / "sweep_results.csv"
    SWEEP_SUMMARY_CSV = sweep_folder / "sweep_summary.csv"
    
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Sweep folder: {sweep_folder}")
    print(f"Dataset: {ANNOTATIONS_PATH}")
    print(f"Training fraction: {SWEEP_EPOCH_FRACTION*100:.0f}% of full training")
    print("="*80 + "\n")
    
    # Setup dataset (only once)
    setup_logger()
    train_dicts, val_dicts, num_train_images = setup_dataset()
    
    # Check for existing runs (for resume capability)
    existing_runs = check_existing_runs()
    print(f"Found {len(existing_runs)} existing runs in CSV (will skip if duplicate)\n")
    
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
