"""
Convergence Test for Detectron2 Training
Tests a single learning rate to determine how many iterations are needed for convergence.
Automatically stops when validation AP plateaus.

Based on train_detectron2.py but with convergence detection and early stopping.
"""

import os
import json
import csv
import time
from datetime import datetime
from pathlib import Path

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
matplotlib.use('Agg')  # Use non-interactive backend to avoid display issues
import matplotlib.pyplot as plt

# ============================================================================
# CONFIGURATION
# ============================================================================

# Dataset paths (using same as hyperparameter sweep for consistency)
DATASET_NAME = "spray_train"
ANNOTATIONS_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\blur_annotations.json"
IMAGES_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\images"

# Training settings
BATCH_SIZE = 2
TEST_LEARNING_RATE = 0.0025  # Learning rate to test for convergence
NUM_EPOCHS = 4  # Maximum epochs (will stop early if converged)
MAX_ITER = None  # Will be calculated dynamically

# Output directory for convergence tests
OUTPUT_BASE_DIR = r"D:\Experiments\AI\ConvergenceTests"
CHECKPOINT_INTERVAL = 1000

# Validation settings
VALIDATION_SPLIT = 0.02  # 2% for validation (98% for training) - smaller for faster convergence testing
# Note: For convergence testing, smaller validation set is fine - we just need relative AP trends
# Original: 0.1 (10% = ~2000 images) - too slow for convergence testing!
# Current: 0.02 (2% = ~400 images) - much faster, still reliable for convergence detection
VALIDATION_INTERVAL = 500  # Validate every N iterations
# Note: Validation is slow! Higher values = less frequent validation = faster training
# But we still need enough validations to detect convergence (at least 3-5)
# Recommended: 500-1000 iterations (validates ~2-4 times per epoch for typical datasets)

# Convergence detection settings
CONVERGENCE_PATIENCE = 3  # Number of consecutive validations with no improvement before stopping
CONVERGENCE_THRESHOLD = 0.005  # Minimum improvement in AP to count as "improvement" (0.5%)
# Note: Validation AP has noise (~±0.002-0.005). Too low threshold (e.g., 0.001) may never converge.
# Recommended: 0.005 (0.5%) is standard, 0.01 (1%) is more conservative
MIN_VALIDATIONS = 3  # Minimum number of validations before checking for convergence

# Resume from pre-trained model (set to None to start from COCO weights)
RESUME_FROM_MODEL = None

# ============================================================================
# SETUP
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
    
    VAL_DATASET_NAME = f"{DATASET_NAME}_val"
    DatasetCatalog.register(VAL_DATASET_NAME, lambda: val_dicts)
    MetadataCatalog.get(VAL_DATASET_NAME).set(thing_classes=["droplet", "ligament"])
    
    print(f"[OK] Training images: {len(train_dicts)} ({len(train_dicts)/len(dataset_dicts)*100:.1f}%)")
    print(f"[OK] Validation images: {len(val_dicts)} ({len(val_dicts)/len(dataset_dicts)*100:.1f}%)")
    
    return train_dicts, val_dicts, len(train_dicts)

def setup_config(output_dir, num_train_images, resume_from=None):
    """Configure Detectron2"""
    global MAX_ITER
    
    iterations_per_epoch = num_train_images // BATCH_SIZE
    MAX_ITER = NUM_EPOCHS * iterations_per_epoch
    
    # Learning rate decay at 60% and 80% of training
    decay_step_1 = int(MAX_ITER * 0.6)
    decay_step_2 = int(MAX_ITER * 0.8)
    learning_rate_decay_steps = (decay_step_1, decay_step_2)
    
    print(f"\n{'='*60}")
    print("Configuration")
    print(f"{'='*60}")
    print(f"[OK] Training dataset size: {num_train_images} images")
    print(f"[OK] Batch size: {BATCH_SIZE}")
    print(f"[OK] Iterations per epoch: {iterations_per_epoch}")
    print(f"[OK] Number of epochs: {NUM_EPOCHS}")
    print(f"[OK] Maximum iterations: {MAX_ITER} (will stop early if converged)")
    print(f"[OK] Learning rate: {TEST_LEARNING_RATE}")
    print(f"[OK] Learning rate decay at: {decay_step_1} and {decay_step_2} iterations")
    print(f"[OK] Validation interval: {VALIDATION_INTERVAL} iterations")
    print(f"[OK] Convergence patience: {CONVERGENCE_PATIENCE} validations")
    print(f"[OK] Convergence threshold: {CONVERGENCE_THRESHOLD:.4f} AP improvement")
    
    cfg = get_cfg()
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )
    
    cfg.DATASETS.TRAIN = (DATASET_NAME,)
    cfg.DATASETS.TEST = (f"{DATASET_NAME}_val",)
    cfg.DATALOADER.NUM_WORKERS = 2
    
    if resume_from and os.path.exists(resume_from):
        cfg.MODEL.WEIGHTS = resume_from
        print(f"[OK] Resuming from: {resume_from}")
    else:
        cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(
            "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"
        )
        print(f"[OK] Starting from COCO pre-trained weights")
    
    cfg.SOLVER.IMS_PER_BATCH = BATCH_SIZE
    cfg.SOLVER.BASE_LR = TEST_LEARNING_RATE
    cfg.SOLVER.MAX_ITER = MAX_ITER
    cfg.SOLVER.STEPS = learning_rate_decay_steps
    cfg.SOLVER.GAMMA = 0.1
    cfg.SOLVER.CHECKPOINT_PERIOD = CHECKPOINT_INTERVAL
    
    val_interval = min(VALIDATION_INTERVAL, iterations_per_epoch)
    # Disable Detectron2's built-in validation (set to very high number so it never triggers)
    # We handle validation manually in our custom after_step() to avoid double validation
    cfg.TEST.EVAL_PERIOD = 999999  # Disable built-in validation
    # Store our desired interval for use in after_step()
    cfg.TEST.EVAL_PERIOD_CUSTOM = val_interval
    
    cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 128
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2
    cfg.OUTPUT_DIR = output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    return cfg

# ============================================================================
# CONVERGENCE TRACKER
# ============================================================================

class ConvergenceTracker:
    """Track training progress and detect convergence"""
    
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.train_losses = []
        self.train_iterations = []
        self.val_aps = []  # Validation AP values
        self.val_iterations = []
        self.start_time = time.time()
        
        # Convergence tracking
        self.best_ap = 0.0
        self.best_ap_iter = 0
        self.no_improvement_count = 0
        self.converged = False
        self.convergence_iter = None
        
        # Create plots directory
        self.plots_dir = self.output_dir / "plots"
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup live plot
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(12, 8))
        self.fig.suptitle(f'Convergence Test: LR={TEST_LEARNING_RATE}', fontsize=14, fontweight='bold')
        
        # Plot 1: Training Loss
        self.ax1.set_xlabel('Iteration')
        self.ax1.set_ylabel('Training Loss')
        self.ax1.set_title('Training Loss')
        self.ax1.grid(True, alpha=0.3)
        self.line1, = self.ax1.plot([], [], 'b-', linewidth=2, label='Training Loss')
        self.ax1.legend()
        
        # Plot 2: Validation AP
        self.ax2.set_xlabel('Iteration')
        self.ax2.set_ylabel('Validation AP (mAP)')
        self.ax2.set_title('Validation Average Precision - Convergence Detection')
        self.ax2.grid(True, alpha=0.3)
        self.line2, = self.ax2.plot([], [], 'r-o', linewidth=2, markersize=6, label='Validation AP')
        self.ax2.legend()
        
        plt.tight_layout()
        
        # Save initial plot
        self.plot_path = self.plots_dir / "convergence_test_live.png"
        self.fig.savefig(str(self.plot_path), dpi=150, bbox_inches='tight')
        print(f"[OK] Live plot will be saved to: {self.plot_path}")
        print(f"     Open this file in an image viewer to watch progress!")
        
        # Setup CSV file for live updates
        self.csv_path = self.output_dir / "convergence_live.csv"
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'iteration', 'training_loss', 'validation_ap', 
                'best_ap', 'best_ap_iter', 'no_improvement_count', 
                'converged', 'timestamp'
            ])
        print(f"[OK] Live CSV will be saved to: {self.csv_path}")
        print(f"     Open this file in Excel/CSV viewer to watch progress!")
    
    def update_training(self, iteration, loss_dict):
        """Update training loss"""
        if loss_dict is None:
            return
        
        total_loss = float(loss_dict.get('total_loss', 0.0))
        self.train_losses.append(total_loss)
        self.train_iterations.append(iteration)
        
        # Update plot and CSV every 25 iterations
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
            self._update_csv(iteration, total_loss, None)
    
    def update_validation(self, iteration, val_metrics):
        """Update validation metrics and check for convergence"""
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
        
        if ap is None:
            print(f"  [WARNING] Could not extract AP from validation metrics")
            return
        
        self.val_aps.append(ap)
        self.val_iterations.append(iteration)
        
        # Check for improvement
        improvement = ap - self.best_ap
        
        if improvement > CONVERGENCE_THRESHOLD:
            # Significant improvement - reset counter and update best
            self.best_ap = ap
            self.best_ap_iter = iteration
            self.no_improvement_count = 0
            print(f"\n  [CONVERGENCE] ✓ Improvement! AP: {ap:.4f} (best: {self.best_ap:.4f} @ iter {self.best_ap_iter})")
        elif ap > self.best_ap:
            # Small improvement (above best but below threshold) - update best but don't reset counter
            # This handles cases where AP starts very low and improves gradually
            self.best_ap = ap
            self.best_ap_iter = iteration
            # Don't reset no_improvement_count - we want to see if it plateaus
            print(f"\n  [CONVERGENCE] Small improvement! AP: {ap:.4f} (best: {self.best_ap:.4f} @ iter {self.best_ap_iter})")
            print(f"               Improvement: {improvement:.4f} < threshold: {CONVERGENCE_THRESHOLD:.4f}")
            print(f"               No improvement count: {self.no_improvement_count}/{CONVERGENCE_PATIENCE}")
        else:
            # No improvement (AP <= best_ap) - increment counter
            self.no_improvement_count += 1
            print(f"\n  [CONVERGENCE] No improvement ({self.no_improvement_count}/{CONVERGENCE_PATIENCE})")
            print(f"               Current AP: {ap:.4f}, Best AP: {self.best_ap:.4f} @ iter {self.best_ap_iter}")
            print(f"               Improvement needed: {CONVERGENCE_THRESHOLD:.4f}, Got: {improvement:.4f}")
        
        # Update plot
        self.line2.set_data(self.val_iterations, self.val_aps)
        self.ax2.relim()
        self.ax2.autoscale_view()
        
        # Add best AP annotation
        if len(self.val_aps) > 0:
            # Remove old annotation
            for txt in self.ax2.texts:
                if txt.get_text().startswith('Best'):
                    txt.remove()
            
            # Add new annotation
            self.ax2.text(0.02, 0.98, 
                         f'Best AP: {self.best_ap:.4f} @ iter {self.best_ap_iter}\n'
                         f'No improvement: {self.no_improvement_count}/{CONVERGENCE_PATIENCE}',
                         transform=self.ax2.transAxes, fontsize=10,
                         verticalalignment='top',
                         bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.5))
        
        # Save plot
        if self.plot_path:
            try:
                self.fig.savefig(str(self.plot_path), dpi=150, bbox_inches='tight')
            except Exception:
                pass
        
        # Update CSV after validation
        current_loss = self.train_losses[-1] if self.train_losses else None
        self._update_csv(iteration, current_loss, ap)
        
        # Check for convergence
        if (len(self.val_aps) >= MIN_VALIDATIONS and 
            self.no_improvement_count >= CONVERGENCE_PATIENCE):
            self.converged = True
            self.convergence_iter = iteration
            print(f"\n  {'='*60}")
            print(f"  🎯 CONVERGENCE DETECTED!")
            print(f"  {'='*60}")
            print(f"  Best AP: {self.best_ap:.4f} @ iteration {self.best_ap_iter}")
            print(f"  Converged at: iteration {self.convergence_iter}")
            print(f"  Total validations: {len(self.val_aps)}")
            print(f"  No improvement for {self.no_improvement_count} consecutive validations")
            print(f"  {'='*60}\n")
    
    def _update_csv(self, iteration, training_loss, validation_ap):
        """Update CSV file with current metrics"""
        try:
            with open(self.csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    iteration,
                    training_loss if training_loss is not None else '',
                    validation_ap if validation_ap is not None else '',
                    self.best_ap,
                    self.best_ap_iter,
                    self.no_improvement_count,
                    self.converged,
                    datetime.now().isoformat()
                ])
        except Exception as e:
            # Don't let CSV errors stop training
            if iteration % 100 == 0:  # Only print occasionally
                print(f"  [WARNING] CSV update failed: {e}")
    
    def save_final_plot(self):
        """Save final plot"""
        try:
            plot_path = self.plots_dir / "convergence_test_final.png"
            self.fig.savefig(str(plot_path), dpi=150, bbox_inches='tight')
            print(f"[OK] Final plot saved: {plot_path}")
        except Exception as e:
            print(f"[WARNING] Failed to save final plot: {e}")
    
    def save_results(self):
        """Save convergence results to JSON"""
        elapsed_time = time.time() - self.start_time
        
        results = {
            'learning_rate': TEST_LEARNING_RATE,
            'converged': self.converged,
            'convergence_iteration': self.convergence_iter,
            'best_ap': self.best_ap,
            'best_ap_iteration': self.best_ap_iter,
            'total_iterations': self.train_iterations[-1] if self.train_iterations else 0,
            'total_validations': len(self.val_aps),
            'training_time_seconds': elapsed_time,
            'training_time_minutes': elapsed_time / 60.0,
            'training_time_hours': elapsed_time / 3600.0,
            'val_aps': self.val_aps,
            'val_iterations': self.val_iterations,
            'final_val_ap': self.val_aps[-1] if self.val_aps else 0.0
        }
        
        results_path = self.output_dir / "convergence_results.json"
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"[OK] Results saved: {results_path}")
        return results

# ============================================================================
# DATASET MAPPER
# ============================================================================

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
# CUSTOM TRAINER WITH CONVERGENCE DETECTION
# ============================================================================

class ConvergenceTrainer(DefaultTrainer):
    """Custom trainer with convergence detection and early stopping"""
    
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
    
    def __init__(self, cfg, convergence_tracker=None):
        super().__init__(cfg)
        self.convergence_tracker = convergence_tracker
        self.last_val_iter = -1
    
    def run_step(self):
        """Override to track training progress"""
        # Check if converged before running step (for immediate stopping)
        if self.convergence_tracker and self.convergence_tracker.converged:
            # Skip training step if converged
            self.iter = self.cfg.SOLVER.MAX_ITER
            # Return empty dict instead of None to avoid potential issues
            return {}
        
        loss_dict = super().run_step()
        
        if self.convergence_tracker and loss_dict is not None and self.iter % 5 == 0:
            self.convergence_tracker.update_training(self.iter, loss_dict)
        
        return loss_dict
    
    def after_step(self):
        """Override to run validation and check for convergence"""
        # Use our custom validation interval (stored in config)
        val_interval = getattr(self.cfg.TEST, 'EVAL_PERIOD_CUSTOM', 500)
        
        # Run validation
        if (self.convergence_tracker and 
            self.iter % val_interval == 0 and 
            self.iter > 0 and 
            self.iter != self.last_val_iter):
            
            self.last_val_iter = self.iter
            
            try:
                print(f"\n  [Validation] Running at iteration {self.iter}...")
                val_results = self._run_validation()
                print(f"  [Validation] Results keys: {list(val_results.keys()) if val_results else 'None'}")
                if val_results:
                    self.convergence_tracker.update_validation(self.iter, val_results)
                    print(f"  [Validation] ✓ Validation results captured!")
                    
                    # Check if converged - stop training
                    if self.convergence_tracker.converged:
                        print(f"\n  {'='*60}")
                        print(f"  🛑 STOPPING TRAINING - Convergence detected!")
                        print(f"  {'='*60}")
                        # Stop training by setting iter to max_iter
                        self.iter = self.cfg.SOLVER.MAX_ITER
                else:
                    print(f"  [WARNING] Validation returned empty results!")
            except Exception as e:
                print(f"  [ERROR] Validation failed: {e}")
                import traceback
                traceback.print_exc()
        
        try:
            super().after_step()
        except (OSError, IOError) as e:
            if "[Errno 22]" in str(e) or "Invalid argument" in str(e):
                pass
            else:
                raise
    
    def _run_validation(self):
        """Run validation evaluation and return metrics"""
        from detectron2.evaluation import COCOEvaluator, inference_on_dataset
        
        val_dataset_name = f"{DATASET_NAME}_val"
        eval_output_dir = Path(self.cfg.OUTPUT_DIR) / "validation_eval"
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        
        results = {}
        try:
            test_loader = self.build_test_loader(self.cfg, val_dataset_name)
            evaluator = COCOEvaluator(val_dataset_name, output_dir=str(eval_output_dir))
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
            
            if 'segm/AP' in results:
                print(f"    Segmentation mAP: {results['segm/AP']:.4f}")
            if 'bbox/AP' in results:
                print(f"    Bbox mAP: {results['bbox/AP']:.4f}")
        except Exception as e:
            print(f"    [ERROR] Validation failed: {e}")
            import traceback
            traceback.print_exc()
            results = {}
        
        return results

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*80)
    print("CONVERGENCE TEST FOR DETECTRON2")
    print("="*80)
    print(f"Testing learning rate: {TEST_LEARNING_RATE}")
    print(f"Will stop automatically when validation AP plateaus")
    print("="*80)
    
    # Create timestamped output directory
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    output_dir = Path(OUTPUT_BASE_DIR) / f"convergence_lr{TEST_LEARNING_RATE}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nStart time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Output directory: {output_dir}")
    
    # Setup
    setup_logger()
    train_dicts, val_dicts, num_train_images = setup_dataset()
    cfg = setup_config(str(output_dir), num_train_images, resume_from=RESUME_FROM_MODEL)
    
    # Initialize convergence tracker
    convergence_tracker = ConvergenceTracker(output_dir)
    
    # Create trainer
    print(f"\n{'='*60}")
    print("Starting Training")
    print(f"{'='*60}")
    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"Maximum iterations: {MAX_ITER} (will stop early if converged)")
    print(f"Validation every: {getattr(cfg.TEST, 'EVAL_PERIOD_CUSTOM', 500)} iterations")
    print(f"Convergence patience: {CONVERGENCE_PATIENCE} validations")
    print(f"Convergence threshold: {CONVERGENCE_THRESHOLD:.4f} AP improvement")
    print(f"\nPress Ctrl+C to stop training manually")
    print(f"{'='*60}\n")
    
    trainer = ConvergenceTrainer(cfg, convergence_tracker)
    trainer.resume_or_load(resume=False)
    
    # Start training
    try:
        trainer.train()
    except KeyboardInterrupt:
        print("\n\nTraining interrupted by user. Saving checkpoint...")
        trainer.checkpointer.save("model_interrupted")
        print("Checkpoint saved!")
    
    # Get final iteration from trainer (more reliable than train_iterations list)
    final_iter = trainer.iter if hasattr(trainer, 'iter') else 0
    if convergence_tracker.train_iterations:
        final_iter = max(final_iter, convergence_tracker.train_iterations[-1])
    
    # Save final results
    convergence_tracker.save_final_plot()
    results = convergence_tracker.save_results()
    
    # Fix total_iterations if it's wrong
    if results['total_iterations'] == 0 and final_iter > 0:
        results['total_iterations'] = final_iter
        print(f"[INFO] Fixed total_iterations: {final_iter}")
    
    # Debug: Print what we captured
    print(f"\n[DEBUG] Validation tracking:")
    print(f"  Total validations captured: {len(convergence_tracker.val_aps)}")
    print(f"  Best AP: {convergence_tracker.best_ap:.4f}")
    print(f"  Final iteration from trainer: {final_iter}")
    print(f"  Train iterations tracked: {len(convergence_tracker.train_iterations)}")
    if convergence_tracker.val_aps:
        print(f"  Validation APs captured: {convergence_tracker.val_aps}")
    
    # Print summary
    print(f"\n{'='*80}")
    print("CONVERGENCE TEST COMPLETE")
    print(f"{'='*80}")
    print(f"Learning Rate: {TEST_LEARNING_RATE}")
    print(f"Converged: {results['converged']}")
    if results['converged']:
        print(f"Convergence Iteration: {results['convergence_iteration']}")
        print(f"Best AP: {results['best_ap']:.4f} @ iteration {results['best_ap_iteration']}")
    else:
        print(f"Did not converge (reached max iterations: {results['total_iterations']})")
        print(f"Best AP: {results['best_ap']:.4f} @ iteration {results['best_ap_iteration']}")
    print(f"Total Iterations: {results['total_iterations']}")
    print(f"Total Validations: {results['total_validations']}")
    print(f"Training Time: {results['training_time_hours']:.2f} hours ({results['training_time_minutes']:.1f} minutes)")
    print(f"\nResults saved to: {output_dir}")
    print(f"Live plot: {convergence_tracker.plot_path}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
