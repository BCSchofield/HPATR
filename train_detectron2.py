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
ANNOTATIONS_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_1\annotations.json"
IMAGES_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_1\images"

# Training settings (optimized for RTX 2070 - 8GB VRAM)
BATCH_SIZE = 1  # Start with 1, increase to 2 if memory allows
BASE_LEARNING_RATE = 0.00025
MAX_ITER = 5000  # Adjust based on dataset size
LEARNING_RATE_DECAY_STEPS = (3000, 4000)

# Output base directory (timestamped folders will be created here)
OUTPUT_BASE_DIR = r"D:\Experiments\AI"
CHECKPOINT_INTERVAL = 500  # Save checkpoint every N iterations

# ============================================================================
# SETUP
# ============================================================================

def setup_dataset():
    """Register the COCO dataset"""
    print(f"\n{'='*60}")
    print("Registering Dataset")
    print(f"{'='*60}")
    
    # Check if files exist
    if not os.path.exists(ANNOTATIONS_PATH):
        raise FileNotFoundError(f"Annotations file not found: {ANNOTATIONS_PATH}")
    if not os.path.exists(IMAGES_PATH):
        raise FileNotFoundError(f"Images directory not found: {IMAGES_PATH}")
    
    # Register dataset
    register_coco_instances(
        DATASET_NAME,
        {},
        ANNOTATIONS_PATH,
        IMAGES_PATH
    )
    
    # Set metadata for visualization
    MetadataCatalog.get(DATASET_NAME).set(thing_classes=["droplet", "ligament"])
    
    # Get dataset info
    dataset_dicts = DatasetCatalog.get(DATASET_NAME)
    print(f"✓ Dataset registered: {DATASET_NAME}")
    print(f"✓ Number of images: {len(dataset_dicts)}")
    
    return dataset_dicts

def setup_config(output_dir):
    """Configure Detectron2"""
    print(f"\n{'='*60}")
    print("Setting up Configuration")
    print(f"{'='*60}")
    
    cfg = get_cfg()
    
    # Load pre-trained Mask R-CNN config
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )
    
    # Dataset configuration
    cfg.DATASETS.TRAIN = (DATASET_NAME,)
    cfg.DATASETS.TEST = ()  # No validation for now
    
    # Data loading
    cfg.DATALOADER.NUM_WORKERS = 2
    
    # IMPORTANT: Configure for RLE format (not polygon)
    # Detectron2 will automatically handle RLE when loading COCO annotations
    # But we need to ensure the dataset mapper uses the correct format
    
    # Model weights (pre-trained on COCO)
    cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(
        "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"
    )
    
    # Training settings
    cfg.SOLVER.IMS_PER_BATCH = BATCH_SIZE
    cfg.SOLVER.BASE_LR = BASE_LEARNING_RATE
    cfg.SOLVER.MAX_ITER = MAX_ITER
    cfg.SOLVER.STEPS = LEARNING_RATE_DECAY_STEPS
    cfg.SOLVER.GAMMA = 0.1  # Learning rate decay factor
    
    # Checkpoint saving
    cfg.SOLVER.CHECKPOINT_PERIOD = CHECKPOINT_INTERVAL  # Save checkpoint every N iterations
    
    # ROI heads
    cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 128
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2  # droplet and ligament
    
    # Output
    cfg.OUTPUT_DIR = output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"✓ Batch size: {BATCH_SIZE}")
    print(f"✓ Learning rate: {BASE_LEARNING_RATE}")
    print(f"✓ Max iterations: {MAX_ITER}")
    print(f"✓ Output directory: {output_dir}")
    print(f"✓ Checkpoint interval: {CHECKPOINT_INTERVAL} iterations")
    
    return cfg

# ============================================================================
# PROGRESS MONITORING
# ============================================================================

class ProgressTracker:
    """Track and visualize training progress"""
    
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.losses = []
        self.iterations = []
        self.start_time = time.time()
        self.last_log_time = time.time()
        
        # Create plots directory
        self.plots_dir = self.output_dir / "plots"
        self.plots_dir.mkdir(exist_ok=True)
        
    def update(self, iteration, loss_dict):
        """Update progress tracking"""
        if loss_dict is None:
            return
        
        current_time = time.time()
        elapsed = current_time - self.start_time
        time_since_last = current_time - self.last_log_time
        
        # Extract total loss
        total_loss = loss_dict.get('total_loss', 0.0)
        self.losses.append(float(total_loss))
        self.iterations.append(iteration)
        
        # Calculate progress
        progress_pct = (iteration / MAX_ITER) * 100
        avg_time_per_iter = elapsed / iteration if iteration > 0 else 0
        remaining_iters = MAX_ITER - iteration
        eta_seconds = remaining_iters * avg_time_per_iter
        eta_minutes = eta_seconds / 60
        eta_hours = eta_minutes / 60
        
        # Print progress
        print(f"\n[{iteration}/{MAX_ITER}] ({progress_pct:.1f}%)")
        print(f"  Total Loss: {total_loss:.4f}")
        print(f"  Time: {elapsed/60:.1f} min elapsed, ETA: {eta_minutes:.1f} min ({eta_hours:.1f} hours)")
        print(f"  Speed: {1/time_since_last:.2f} iter/sec")
        
        # Detailed loss breakdown
        for key, value in loss_dict.items():
            if key != 'total_loss':
                print(f"    {key}: {float(value):.4f}")
        
        self.last_log_time = current_time
        
        # Save plot every 50 iterations
        if iteration % 50 == 0:
            self.save_plot()
    
    def save_plot(self):
        """Save loss curve plot"""
        if len(self.losses) < 2:
            return
        
        try:
            plt.figure(figsize=(12, 6))
            plt.plot(self.iterations, self.losses, 'b-', linewidth=2, label='Total Loss')
            plt.xlabel('Iteration', fontsize=12)
            plt.ylabel('Loss', fontsize=12)
            plt.title('Training Loss Curve', fontsize=14, fontweight='bold')
            plt.grid(True, alpha=0.3)
            plt.legend()
            plt.tight_layout()
            
            plot_path = self.plots_dir / "loss_curve.png"
            plt.savefig(plot_path, dpi=150, bbox_inches='tight')
            plt.close()
            
            print(f"  [OK] Loss plot saved: {plot_path}")
        except Exception as e:
            print(f"  [WARNING] Failed to save plot: {e}")

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
    """Custom trainer with progress tracking and RLE support"""
    
    @classmethod
    def build_train_loader(cls, cfg):
        """Build data loader with custom mapper for RLE format"""
        from detectron2.data import build_detection_train_loader
        from detectron2.data import get_detection_dataset_dicts
        
        dataset_dicts = get_detection_dataset_dicts(cfg.DATASETS.TRAIN)
        
        # Create custom mapper
        mapper = RLEDatasetMapper(cfg, is_train=True)
        
        return build_detection_train_loader(cfg, mapper=mapper)
    
    def __init__(self, cfg, progress_tracker=None):
        super().__init__(cfg)
        self.progress_tracker = progress_tracker
    
    def run_step(self):
        """Override to track progress"""
        loss_dict = super().run_step()
        
        if self.progress_tracker and loss_dict is not None and self.iter % 10 == 0:  # Log every 10 iterations
            self.progress_tracker.update(self.iter, loss_dict)
        
        return loss_dict

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
    dataset_dicts = setup_dataset()
    cfg = setup_config(str(OUTPUT_DIR))
    
    # Initialize progress tracker
    progress_tracker = ProgressTracker(OUTPUT_DIR)
    
    # Create trainer
    print(f"\n{'='*60}")
    print("Starting Training")
    print(f"{'='*60}")
    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"Training will run for {MAX_ITER} iterations")
    print(f"Checkpoints will be saved every {CHECKPOINT_INTERVAL} iterations")
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

