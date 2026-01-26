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
MODEL_PATH = r"D:\Experiments\AI\Claudia\Claudia.pth"

# Detection threshold (0.0 to 1.0)
# Lower = more detections (but more false positives)
# Higher = fewer detections (but more accurate)
SCORE_THRESHOLD = 0.5

# Output directories
# Output to the same folder as the model file
OUTPUT_DIR = Path(MODEL_PATH).parent
VISUALIZATIONS_DIR = OUTPUT_DIR / "visualizations"
MASKS_DIR = OUTPUT_DIR / "masks"
DATA_DIR = OUTPUT_DIR / "data"

# ============================================================================
# SETUP
# ============================================================================

def detect_anchor_config(model_path: str) -> List[List[int]]:
    """
    Detect which anchor configuration a model was trained with.
    This is critical because anchor sizes affect the RPN head architecture.
    
    Returns:
        Anchor sizes configuration (list of lists)
    """
    model_path_lower = model_path.lower()
    
    # Check if it's Dennis or Early_Dennis (uses [8, 16, 32, 64] anchors)
    if "dennis" in model_path_lower or "early_dennis" in model_path_lower:
        print(f"[INFO] Detected Dennis/Early_Dennis model - using anchors [8, 16, 32, 64]")
        return [[8, 16, 32, 64]]
    
    # Check if it's Claudia (uses default COCO anchors)
    if "claudia" in model_path_lower:
        print(f"[INFO] Detected Claudia model - using default COCO anchors")
        return None  # None means use default
    
    # Default: assume it uses [8, 16, 32, 64] if it's in the current training setup
    # You can add more detection logic here based on model folder names, etc.
    print(f"[INFO] Model type not detected - assuming default COCO anchors")
    print(f"[WARNING] If model fails to load, it may need [8, 16, 32, 64] anchors")
    return None

def setup_predictor(model_path: str, score_threshold: float = 0.5, nms_threshold: float = 0.3, anchor_sizes: List[List[int]] = None):
    """
    Load trained model and create predictor.
    
    Args:
        model_path: Path to model checkpoint
        score_threshold: Detection score threshold
        nms_threshold: NMS threshold
        anchor_sizes: Anchor sizes configuration. If None, uses default COCO anchors.
                      If provided (e.g., [[8, 16, 32, 64]]), uses custom anchors.
    """
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
    
    # CRITICAL: Set anchor sizes BEFORE loading model weights!
    # Anchor sizes determine the RPN head architecture, so they must match training
    if anchor_sizes is None:
        # Use default COCO anchors (different size per FPN level)
        # Default is typically [[32], [64], [128], [256], [512]] for 5 FPN levels
        print(f"[OK] Using default COCO anchor configuration")
    else:
        # Use custom anchor sizes (same sizes for all FPN levels)
        cfg.MODEL.ANCHOR_GENERATOR.SIZES = anchor_sizes
        print(f"[OK] Using custom anchor sizes: {anchor_sizes}")
        print(f"[OK] This means all 5 FPN levels use the same {len(anchor_sizes[0])} anchor sizes")
        print(f"[OK] With 3 aspect ratios, that's {len(anchor_sizes[0]) * 3} anchors per spatial location")
    
    # Set model weights (must be AFTER setting anchor sizes!)
    cfg.MODEL.WEIGHTS = model_path
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2  # droplet and ligament
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
    save_data: bool = True,
    output_prefix: str = None
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
        prefix = f"{output_prefix}_" if output_prefix else ""
        vis_path = output_dir / "visualizations" / f"{prefix}{Path(image_path).stem}_result.png"
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
        prefix = f"{output_prefix}_" if output_prefix else ""
        masks_subdir = output_dir / "masks" / f"{prefix}{Path(image_path).stem}"
        masks_subdir.mkdir(parents=True, exist_ok=True)
        
        for i, detection in enumerate(detections):
            # Reconstruct mask from properties (we need to get it from instances)
            mask = instances.pred_masks[i].numpy().astype(np.uint8) * 255
            mask_path = masks_subdir / f"{detection['class_name']}_{i+1}_mask.png"
            cv2.imwrite(str(mask_path), mask)
        
        print(f"  [OK] Masks saved to: {masks_subdir}")
    
    # Save numerical data
    if save_data:
        prefix = f"{output_prefix}_" if output_prefix else ""
        data_path = output_dir / "data" / f"{prefix}{Path(image_path).stem}_results.json"
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
    pixels_per_mm: float = None,
    anchor_sizes: List[List[int]] = None,
    output_prefix: str = None
):
    """
    Process multiple images
    
    Args:
        anchor_sizes: Anchor configuration. If None, will auto-detect from model path.
    """
    
    # Create output directories
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "visualizations").mkdir(exist_ok=True)
    (output_dir / "masks").mkdir(exist_ok=True)
    (output_dir / "data").mkdir(exist_ok=True)
    
    # Auto-detect anchor configuration if not provided
    if anchor_sizes is None:
        anchor_sizes = detect_anchor_config(model_path)
    
    # Setup predictor
    predictor, cfg = setup_predictor(model_path, score_threshold, nms_threshold, anchor_sizes)
    
    # Process each image
    all_results = []
    for image_path in image_paths:
        try:
            result = run_inference(
                predictor,
                image_path,
                output_dir,
                pixels_per_mm=pixels_per_mm,
                output_prefix=output_prefix
            )
            all_results.append(result)
        except Exception as e:
            print(f"  ERROR processing {image_path}: {e}")
    
    # Save summary
    prefix = f"{output_prefix}_" if output_prefix else ""
    summary_path = output_dir / f"{prefix}summary.json"
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
    parser.add_argument("--anchor-sizes", type=str, default=None,
                       help="Anchor sizes (e.g., '8,16,32,64' for Dennis, or 'default' for COCO). Auto-detected if not specified.")
    
    args = parser.parse_args()
    
    # Parse anchor sizes if provided
    anchor_sizes = None
    if args.anchor_sizes:
        if args.anchor_sizes.lower() == "default":
            anchor_sizes = None  # Use default
        else:
            # Parse comma-separated values like "8,16,32,64"
            try:
                sizes = [int(x.strip()) for x in args.anchor_sizes.split(",")]
                anchor_sizes = [sizes]  # Wrap in list for FPN format
            except ValueError:
                print(f"ERROR: Invalid anchor sizes format: {args.anchor_sizes}")
                print("Expected format: '8,16,32,64' or 'default'")
                return
    
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
        args.pixels_per_mm,
        anchor_sizes
    )

if __name__ == "__main__":
    # Quick test mode: use specific model and image
    import sys
    
    # If no arguments provided, use quick test defaults
    if len(sys.argv) == 1:
        print("Running quick test with Dennis model...")
        test_image = r"D:\Experiments\AI\Dennis\input.jpg"
        test_model = r"D:\Experiments\AI\Dennis\Dennis.pth"
        test_output = Path(test_model).parent
        
        # Verify files exist
        if not Path(test_image).exists():
            print(f"ERROR: Image not found: {test_image}")
            sys.exit(1)
        if not Path(test_model).exists():
            print(f"ERROR: Model not found: {test_model}")
            sys.exit(1)
        
        print(f"Model: {test_model}")
        print(f"Image: {test_image}")
        print(f"Output: {test_output}")
        
        # Auto-detect anchor configuration for the model
        anchor_config = detect_anchor_config(test_model)
        
        # Process the single image with Dennis prefix
        process_images(
            [test_image],
            test_model,
            test_output,
            score_threshold=SCORE_THRESHOLD,
            nms_threshold=0.3,
            pixels_per_mm=None,
            anchor_sizes=anchor_config,
            output_prefix="Dennis"
        )
    else:
        main()

