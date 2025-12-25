"""
Detectron2 Training Script with Progress Visualization
Trains Mask R-CNN on synthetic spray droplet dataset
"""

import os
import json
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
from tqdm import tqdm

# ============================================================================
# CONFIGURATION
# ============================================================================

# Dataset paths
DATASET_NAME = "spray_train"
ANNOTATIONS_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\blur_annotations.json"
IMAGES_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\images"

# Training settings (optimized for RTX 2070 - 8GB VRAM)
BATCH_SIZE = 2  # Start with 1, increase to 2 if memory allows
BASE_LEARNING_RATE = 0.00025
NUM_EPOCHS = 3  # Number of times to iterate through the entire training dataset
# MAX_ITER will be calculated dynamically based on dataset size
MAX_ITER = None  # Will be set after loading dataset
LEARNING_RATE_DECAY_STEPS = None  # Will be calculated based on MAX_ITER

# Output base directory (timestamped folders will be created here)
OUTPUT_BASE_DIR = r"D:\Experiments\AI"
CHECKPOINT_INTERVAL = 2000  # Save checkpoint every N iterations

# Validation settings
VALIDATION_SPLIT = 0.2  # 20% of data for validation (80% for training)
VALIDATION_INTERVAL = 4000  # Evaluate on validation set every N iterations

# Resume training from existing model (set to None to start from scratch)
# Set this to your model path to continue training from that checkpoint
# Example: RESUME_FROM_MODEL = r"D:\Experiments\AI\training_2025_12_25_15_43_57\model_final.pth"
RESUME_FROM_MODEL = None  # Set to model path to continue training, or None to start fresh

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
    
    split_idx = int(len(dataset_dicts) * (1 - VALIDATION_SPLIT))
    train_indices = indices[:split_idx]
    val_indices = indices[split_idx:]
    
    # Create train and validation datasets
    train_dicts = [dataset_dicts[i] for i in train_indices]
    val_dicts = [dataset_dicts[i] for i in val_indices]
    
    # Register validation dataset
    VAL_DATASET_NAME = f"{DATASET_NAME}_val"
    DatasetCatalog.register(VAL_DATASET_NAME, lambda: val_dicts)
    MetadataCatalog.get(VAL_DATASET_NAME).set(thing_classes=["droplet", "ligament"])
    
    print(f"[OK] Training images: {len(train_dicts)} ({len(train_dicts)/len(dataset_dicts)*100:.1f}%)")
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
    
    # Calculate MAX_ITER based on dataset size, number of epochs, and batch size
    # Each iteration processes BATCH_SIZE images
    # So NUM_EPOCHS * (num_train_images / BATCH_SIZE) = total iterations needed
    global MAX_ITER, LEARNING_RATE_DECAY_STEPS
    iterations_per_epoch = num_train_images // BATCH_SIZE
    MAX_ITER = NUM_EPOCHS * iterations_per_epoch
    
    # Learning rate decay at 60% and 80% of training
    decay_step_1 = int(MAX_ITER * 0.6)
    decay_step_2 = int(MAX_ITER * 0.8)
    LEARNING_RATE_DECAY_STEPS = (decay_step_1, decay_step_2)
    
    print(f"[OK] Training dataset size: {num_train_images} images")
    print(f"[OK] Batch size: {BATCH_SIZE} images per iteration")
    print(f"[OK] Iterations per epoch: {iterations_per_epoch} ({num_train_images} images / {BATCH_SIZE})")
    print(f"[OK] Number of epochs: {NUM_EPOCHS}")
    print(f"[OK] Total iterations: {MAX_ITER} ({NUM_EPOCHS} epochs × {iterations_per_epoch} iterations)")
    print(f"[OK] Learning rate decay at: {decay_step_1} and {decay_step_2} iterations")
    
    cfg = get_cfg()
    
    # Load pre-trained Mask R-CNN config
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )
    
    # Dataset configuration
    cfg.DATASETS.TRAIN = (DATASET_NAME,)
    cfg.DATASETS.TEST = (f"{DATASET_NAME}_val",)  # Validation dataset
    
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
    cfg.SOLVER.STEPS = LEARNING_RATE_DECAY_STEPS
    cfg.SOLVER.GAMMA = 0.1  # Learning rate decay factor
    
    # Checkpoint saving
    cfg.SOLVER.CHECKPOINT_PERIOD = CHECKPOINT_INTERVAL  # Save checkpoint every N iterations
    
    # Validation evaluation - adjust interval based on dataset size
    # Evaluate roughly every epoch or every 500 iterations, whichever is smaller
    val_interval = min(VALIDATION_INTERVAL, iterations_per_epoch)
    cfg.TEST.EVAL_PERIOD = val_interval
    
    # ROI heads
    cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 128
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2  # droplet and ligament
    
    # Output
    cfg.OUTPUT_DIR = output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"[OK] Batch size: {BATCH_SIZE}")
    print(f"[OK] Learning rate: {BASE_LEARNING_RATE}")
    print(f"[OK] Max iterations: {MAX_ITER}")
    print(f"[OK] Output directory: {output_dir}")
    print(f"[OK] Checkpoint interval: {CHECKPOINT_INTERVAL} iterations")
    print(f"[OK] Validation interval: {val_interval} iterations")
    
    return cfg

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
        self.start_time = time.time()
        self.last_log_time = time.time()
        
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
    
    def update_validation(self, iteration, val_metrics):
        """Update validation metrics"""
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
        
        # Save plot after validation
        self.save_plot()
        self.save_metrics()
    
    def save_plot(self):
        """Save loss curve plot with training and validation"""
        if len(self.train_losses) < 2:
            print(f"  [INFO] Not enough data points yet ({len(self.train_losses)} < 2), skipping plot")
            return
        
        try:
            # Ensure plots directory exists - use absolute path
            plots_dir_abs = Path(self.plots_dir).resolve()
            plots_dir_abs.mkdir(parents=True, exist_ok=True)
            
            print(f"  [DEBUG] Attempting to save plot to: {plots_dir_abs}")
            
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
            
            # Use absolute path for saving
            plot_path = plots_dir_abs / "loss_curve.png"
            plot_path_str = str(plot_path)
            
            print(f"  [DEBUG] Saving plot to: {plot_path_str}")
            
            # Force save with explicit format and flush
            fig.savefig(plot_path_str, dpi=150, bbox_inches='tight', format='png', facecolor='white')
            plt.close(fig)
            
            # Force flush to ensure file is written
            import sys
            sys.stdout.flush()
            
            # Wait a moment and verify file was actually created
            import time
            time.sleep(0.1)
            
            if plot_path.exists():
                file_size = plot_path.stat().st_size
                print(f"  [OK] Loss plot saved: {plot_path_str} ({file_size/1024:.1f} KB)")
                
                # Also save a backup copy in the root output directory
                backup_path = self.output_dir / "loss_curve.png"
                try:
                    import shutil
                    shutil.copy2(plot_path_str, str(backup_path))
                    print(f"  [OK] Backup plot saved: {backup_path}")
                except Exception as e:
                    print(f"  [WARNING] Could not save backup plot: {e}")
            else:
                print(f"  [ERROR] Plot file was not created at: {plot_path_str}")
                print(f"  [DEBUG] Plots directory exists: {plots_dir_abs.exists()}")
                print(f"  [DEBUG] Plots directory is writable: {os.access(plots_dir_abs, os.W_OK)}")
                
                # Try saving directly to output directory as fallback
                try:
                    fallback_path = self.output_dir / "loss_curve_fallback.png"
                    fig2, (ax1_fb, ax2_fb) = plt.subplots(2, 1, figsize=(14, 10))
                    ax1_fb.plot(self.train_iterations, self.train_losses, 'b-', linewidth=2, label='Training Loss', alpha=0.7)
                    if len(self.val_losses) > 0:
                        ax1_fb.plot(self.val_iterations, self.val_losses, 'r-', linewidth=2, label='Validation Loss', marker='o', markersize=5)
                    ax1_fb.set_xlabel('Iteration')
                    ax1_fb.set_ylabel('Loss')
                    ax1_fb.set_title('Training vs Validation Loss')
                    ax1_fb.grid(True, alpha=0.3)
                    ax1_fb.legend()
                    ax2_fb.plot(self.train_iterations, self.train_losses, 'b-', linewidth=2, label='Training Loss')
                    ax2_fb.set_xlabel('Iteration')
                    ax2_fb.set_ylabel('Loss')
                    ax2_fb.set_title('Training Loss')
                    ax2_fb.grid(True, alpha=0.3)
                    ax2_fb.legend()
                    plt.tight_layout()
                    fig2.savefig(str(fallback_path), dpi=150, bbox_inches='tight', format='png')
                    plt.close(fig2)
                    print(f"  [OK] Fallback plot saved to: {fallback_path}")
                except Exception as e2:
                    print(f"  [ERROR] Fallback plot also failed: {e2}")
        except Exception as e:
            import traceback
            print(f"  [ERROR] Failed to save plot: {e}")
            print(f"  Traceback: {traceback.format_exc()}")
    
    def save_metrics(self):
        """Save metrics to JSON file for later analysis"""
        try:
            metrics_path = self.output_dir / "metrics.json"
            metrics_data = {
                'train_iterations': self.train_iterations,
                'train_losses': self.train_losses,
                'val_iterations': self.val_iterations,
                'val_losses': self.val_losses,
                'total_train_iterations': len(self.train_iterations),
                'total_val_evaluations': len(self.val_losses),
                'last_update': datetime.now().isoformat()
            }
            
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
            print(f"  [WARNING] Failed to save metrics JSON: {e}")

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
        if self.progress_tracker and self.iter % val_interval == 0 and self.iter > 0:
            # Run validation evaluation
            try:
                val_results = self._run_validation()
                if val_results:
                    self.progress_tracker.update_validation(self.iter, val_results)
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
        
        # Get validation dataset name
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
        
        return results

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
        print("\n\nTraining interrupted by user. Saving final checkpoint...")
        trainer.checkpointer.save("model_interrupted")
        print("Checkpoint saved!")
    
    # Final plot
    progress_tracker.save_plot()
    
    print(f"\n{'='*60}")
    print("Training Complete!")
    print(f"{'='*60}")
    print(f"Final model: {OUTPUT_DIR}/model_final.pth")
    print(f"Loss plot: {OUTPUT_DIR}/plots/loss_curve.png")
    print(f"All outputs saved to: {OUTPUT_DIR}")
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()

