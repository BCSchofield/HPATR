"""
Model Evaluation Script for Synthetic Spray Dataset

This script evaluates trained Detectron2 models against ground truth annotations
from the synthetic dataset generator. It computes comprehensive metrics and exports
results to Excel for analysis.

Usage:
    python evaluate_model.py --config path/to/config.yaml --weights path/to/model.pth --annotations path/to/blur_annotations.json --images path/to/images/ --output results.xlsx
"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd
from pycocotools.coco import COCO
from pycocotools import mask as coco_mask
import cv2
from detectron2.engine import DefaultPredictor
from detectron2.config import get_cfg
from detectron2.data import MetadataCatalog
from detectron2.utils.visualizer import Visualizer
from detectron2.structures import BoxMode
import torch


def load_ground_truth(annotations_path: str) -> Dict:
    """Load ground truth annotations from COCO format JSON."""
    with open(annotations_path, 'r') as f:
        gt_data = json.load(f)
    return gt_data


def compute_iou(mask1: np.ndarray, mask2: np.ndarray) -> float:
    """Compute Intersection over Union (IoU) between two binary masks."""
    intersection = np.logical_and(mask1, mask2).sum()
    union = np.logical_or(mask1, mask2).sum()
    if union == 0:
        return 0.0
    return float(intersection) / float(union)


def decode_rle(rle: Dict) -> np.ndarray:
    """Decode RLE mask to binary array."""
    if isinstance(rle, list):
        # Polygon format - convert to RLE first
        h, w = rle['size']
        rle_obj = coco_mask.frPyObjects(rle, h, w)
        rle_obj = coco_mask.merge(rle_obj)
    else:
        rle_obj = rle
    return coco_mask.decode(rle_obj)


def evaluate_image(
    predictor: DefaultPredictor,
    image_path: str,
    gt_annotations: List[Dict],
    image_id: int,
    category_names: Dict[int, str]
) -> Dict:
    """
    Evaluate a single image against ground truth.
    
    Returns dictionary with:
    - detections: List of predicted instances
    - gt_instances: List of ground truth instances
    - matches: List of (pred_idx, gt_idx, iou) tuples
    - metrics: Dictionary of computed metrics
    """
    # Load image
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Could not load image: {image_path}")
    
    # Run inference
    outputs = predictor(image)
    instances = outputs["instances"]
    
    # Extract predictions
    pred_boxes = instances.pred_boxes.tensor.cpu().numpy()
    pred_classes = instances.pred_classes.cpu().numpy()
    pred_scores = instances.scores.cpu().numpy()
    pred_masks = instances.pred_masks.cpu().numpy()
    
    # Convert predictions to list of dicts
    pred_instances = []
    for i in range(len(instances)):
        pred_instances.append({
            'bbox': pred_boxes[i].tolist(),
            'category_id': int(pred_classes[i]),
            'score': float(pred_scores[i]),
            'mask': pred_masks[i],
            'area': int(pred_masks[i].sum())
        })
    
    # Filter ground truth for this image
    gt_instances = [ann for ann in gt_annotations if ann['image_id'] == image_id]
    
    # Decode GT masks
    for gt in gt_instances:
        if 'segmentation' in gt:
            if isinstance(gt['segmentation'], dict):
                # RLE format
                gt['mask'] = decode_rle(gt['segmentation'])
            else:
                # Polygon format - convert to mask
                h, w = gt['height'], gt['width']
                rle = coco_mask.frPyObjects(gt['segmentation'], h, w)
                rle = coco_mask.merge(rle)
                gt['mask'] = decode_rle(rle)
    
    # Match predictions to ground truth (greedy matching by IoU)
    matches = []  # (pred_idx, gt_idx, iou)
    matched_pred = set()
    matched_gt = set()
    
    # Sort predictions by score (highest first)
    pred_sorted = sorted(enumerate(pred_instances), key=lambda x: x[1]['score'], reverse=True)
    
    for pred_idx, pred in pred_sorted:
        if pred_idx in matched_pred:
            continue
        
        best_iou = 0.0
        best_gt_idx = None
        
        for gt_idx, gt in enumerate(gt_instances):
            if gt_idx in matched_gt:
                continue
            
            # Only match if same category
            if pred['category_id'] != gt['category_id']:
                continue
            
            # Compute IoU
            iou = compute_iou(pred['mask'], gt['mask'])
            
            if iou > best_iou and iou >= 0.5:  # IoU threshold for matching
                best_iou = iou
                best_gt_idx = gt_idx
        
        if best_gt_idx is not None:
            matches.append((pred_idx, best_gt_idx, best_iou))
            matched_pred.add(pred_idx)
            matched_gt.add(best_gt_idx)
    
    # Compute metrics
    tp = len(matches)  # True positives
    fp = len(pred_instances) - tp  # False positives
    fn = len(gt_instances) - tp  # False negatives
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # Average IoU for matched instances
    avg_iou = np.mean([iou for _, _, iou in matches]) if matches else 0.0
    
    # Count by category
    pred_droplets = sum(1 for p in pred_instances if p['category_id'] == 1)
    pred_ligaments = sum(1 for p in pred_instances if p['category_id'] == 2)
    gt_droplets = sum(1 for g in gt_instances if g['category_id'] == 1)
    gt_ligaments = sum(1 for g in gt_instances if g['category_id'] == 2)
    
    # Area statistics
    pred_total_area = sum(p['area'] for p in pred_instances)
    gt_total_area = sum(g.get('area', g['mask'].sum()) for g in gt_instances)
    
    return {
        'image_id': image_id,
        'image_name': Path(image_path).name,
        'tp': tp,
        'fp': fp,
        'fn': fn,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'avg_iou': avg_iou,
        'pred_droplets': pred_droplets,
        'pred_ligaments': pred_ligaments,
        'gt_droplets': gt_droplets,
        'gt_ligaments': gt_ligaments,
        'pred_total_area': pred_total_area,
        'gt_total_area': gt_total_area,
        'area_ratio': pred_total_area / gt_total_area if gt_total_area > 0 else 0.0,
        'matches': matches,
        'pred_instances': pred_instances,
        'gt_instances': gt_instances
    }


def evaluate_model(
    config_path: str,
    weights_path: str,
    annotations_path: str,
    images_dir: str,
    output_path: str,
    model_name: str = "Model",
    score_threshold: float = 0.5
) -> None:
    """
    Evaluate a trained model and export results to Excel.
    
    Args:
        config_path: Path to Detectron2 config file
        weights_path: Path to trained model weights
        annotations_path: Path to ground truth annotations JSON
        images_dir: Directory containing validation images
        output_path: Path to output Excel file (if just filename, saves in images_dir)
        model_name: Name of the model (for labeling in Excel)
        score_threshold: Minimum confidence score for predictions
    """
    # If output_path is just a filename (no directory), save it in the images_dir
    output_path_obj = Path(output_path)
    if not output_path_obj.parent or str(output_path_obj.parent) == '.':
        # Just a filename, save in images_dir
        images_dir_path = Path(images_dir)
        output_path = str(images_dir_path / output_path)
    else:
        # Full path provided, use as-is
        output_path = str(output_path_obj)
    
    print(f"Loading ground truth annotations from {annotations_path}...")
    gt_data = load_ground_truth(annotations_path)
    
    # Create COCO object for easier access
    coco = COCO()
    coco.dataset = gt_data
    coco.createIndex()
    
    # Setup Detectron2
    print(f"Loading model from {weights_path}...")
    cfg = get_cfg()
    
    # Try to load config from checkpoint first (Detectron2 often saves config in model)
    # If not available, try config file, otherwise create a basic one
    config_loaded = False
    
    if config_path and Path(config_path).exists():
        # Try config file first if provided
        try:
            cfg.merge_from_file(config_path)
            print(f"  Loaded config from file: {config_path}")
            config_loaded = True
        except Exception as e:
            print(f"  Warning: Could not load config file: {e}")
    
    if not config_loaded:
        # Try to load from checkpoint
        try:
            checkpoint = torch.load(weights_path, map_location="cpu")
            if "cfg" in checkpoint:
                # Config is stored in checkpoint
                cfg = checkpoint["cfg"]
                print("  Loaded config from model checkpoint")
                config_loaded = True
        except Exception as e:
            print(f"  Note: Could not load config from checkpoint: {e}")
    
    if not config_loaded:
        # Last resort: create minimal config for Mask R-CNN
        print("  Creating basic config (using defaults for Mask R-CNN)...")
        # Start with a base config - try to use a standard one
        try:
            # Try to use a standard Detectron2 config as base
            from detectron2 import model_zoo
            cfg.merge_from_file(model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml"))
            # Override for our 2 classes
            cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2
            print("  Using COCO Mask R-CNN base config with 2 classes")
        except:
            # Fallback: minimal config
            cfg.merge_from_list([
                "MODEL.META_ARCHITECTURE", "GeneralizedRCNN",
                "MODEL.ROI_HEADS.NUM_CLASSES", 2,  # droplet and ligament
            ])
            print("  Created minimal config")
    
    # Set model weights and score threshold
    cfg.MODEL.WEIGHTS = weights_path
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = score_threshold
    
    # Ensure device is set
    if torch.cuda.is_available():
        cfg.MODEL.DEVICE = "cuda"
    else:
        cfg.MODEL.DEVICE = "cpu"
    
    print(f"  Using device: {cfg.MODEL.DEVICE}")
    print(f"  Score threshold: {score_threshold}")
    
    predictor = DefaultPredictor(cfg)
    
    # Category mapping
    category_names = {1: 'droplet', 2: 'ligament'}
    
    # Get list of images
    images_dir = Path(images_dir)
    image_files = sorted(list(images_dir.glob("*.png")))
    
    print(f"Evaluating {len(image_files)} images...")
    
    # Evaluate each image
    results = []
    all_instance_details = []
    
    for img_file in image_files:
        # Find corresponding image_id in ground truth
        img_name = img_file.name
        img_info = next((img for img in gt_data['images'] if img['file_name'] == img_name), None)
        
        if img_info is None:
            print(f"Warning: No ground truth found for {img_name}, skipping...")
            continue
        
        image_id = img_info['id']
        gt_annotations = [ann for ann in gt_data['annotations'] if ann['image_id'] == image_id]
        
        try:
            result = evaluate_image(predictor, img_file, gt_annotations, image_id, category_names)
            results.append(result)
            
            # Add instance-level details
            for pred_idx, pred in enumerate(result['pred_instances']):
                # Check if this prediction was matched
                matched = any(m[0] == pred_idx for m in result['matches'])
                match_info = next((m for m in result['matches'] if m[0] == pred_idx), None)
                
                all_instance_details.append({
                    'image_id': image_id,
                    'image_name': img_name,
                    'model': model_name,
                    'instance_type': 'prediction',
                    'category_id': pred['category_id'],
                    'category': category_names.get(pred['category_id'], 'unknown'),
                    'score': pred['score'],
                    'area': pred['area'],
                    'matched': matched,
                    'iou': match_info[2] if match_info else 0.0,
                    'gt_idx': match_info[1] if match_info else None
                })
            
            for gt_idx, gt in enumerate(result['gt_instances']):
                matched = any(m[1] == gt_idx for m in result['matches'])
                
                all_instance_details.append({
                    'image_id': image_id,
                    'image_name': img_name,
                    'model': model_name,
                    'instance_type': 'ground_truth',
                    'category_id': gt['category_id'],
                    'category': category_names.get(gt['category_id'], 'unknown'),
                    'score': None,
                    'area': gt.get('area', gt['mask'].sum() if 'mask' in gt else 0),
                    'matched': matched,
                    'iou': None,
                    'gt_idx': gt_idx
                })
            
        except Exception as e:
            print(f"Error evaluating {img_name}: {e}")
            continue
    
    if not results:
        print("No results to export!")
        return
    
    print(f"Computing summary statistics...")
    
    # Create DataFrames
    # 1. Per-image results
    per_image_df = pd.DataFrame([{
        'model': model_name,
        'image_id': r['image_id'],
        'image_name': r['image_name'],
        'tp': r['tp'],
        'fp': r['fp'],
        'fn': r['fn'],
        'precision': r['precision'],
        'recall': r['recall'],
        'f1': r['f1'],
        'avg_iou': r['avg_iou'],
        'pred_droplets': r['pred_droplets'],
        'pred_ligaments': r['pred_ligaments'],
        'gt_droplets': r['gt_droplets'],
        'gt_ligaments': r['gt_ligaments'],
        'pred_total_area': r['pred_total_area'],
        'gt_total_area': r['gt_total_area'],
        'area_ratio': r['area_ratio']
    } for r in results])
    
    # 2. Model summary
    summary_data = {
        'model': model_name,
        'num_images': len(results),
        'avg_precision': per_image_df['precision'].mean(),
        'avg_recall': per_image_df['recall'].mean(),
        'avg_f1': per_image_df['f1'].mean(),
        'avg_iou': per_image_df['avg_iou'].mean(),
        'total_tp': per_image_df['tp'].sum(),
        'total_fp': per_image_df['fp'].sum(),
        'total_fn': per_image_df['fn'].sum(),
        'overall_precision': per_image_df['tp'].sum() / (per_image_df['tp'].sum() + per_image_df['fp'].sum()) if (per_image_df['tp'].sum() + per_image_df['fp'].sum()) > 0 else 0.0,
        'overall_recall': per_image_df['tp'].sum() / (per_image_df['tp'].sum() + per_image_df['fn'].sum()) if (per_image_df['tp'].sum() + per_image_df['fn'].sum()) > 0 else 0.0,
        'avg_pred_droplets': per_image_df['pred_droplets'].mean(),
        'avg_pred_ligaments': per_image_df['pred_ligaments'].mean(),
        'avg_gt_droplets': per_image_df['gt_droplets'].mean(),
        'avg_gt_ligaments': per_image_df['gt_ligaments'].mean(),
        'avg_area_ratio': per_image_df['area_ratio'].mean()
    }
    summary_df = pd.DataFrame([summary_data])
    
    # 3. Instance details
    instance_df = pd.DataFrame(all_instance_details)
    
    # Export to Excel
    print(f"Exporting results to {output_path}...")
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        summary_df.to_excel(writer, sheet_name='Model Summary', index=False)
        per_image_df.to_excel(writer, sheet_name='Per Image Results', index=False)
        instance_df.to_excel(writer, sheet_name='Instance Details', index=False)
    
    print(f"Evaluation complete! Results saved to {output_path}")
    print(f"\nSummary for {model_name}:")
    print(f"  Average Precision: {summary_data['avg_precision']:.3f}")
    print(f"  Average Recall: {summary_data['avg_recall']:.3f}")
    print(f"  Average F1: {summary_data['avg_f1']:.3f}")
    print(f"  Average IoU: {summary_data['avg_iou']:.3f}")


def auto_detect_paths(model_path: str, validation_dir: str = None) -> Dict[str, str]:
    """
    Auto-detect paths for evaluation.
    
    Args:
        model_path: Path to model_final.pth file
        validation_dir: Optional path to Validation_100 directory (auto-detected if None)
    
    Returns:
        Dictionary with detected paths
    """
    model_path = Path(model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    
    # Find config file - check training directory first, then common locations
    training_dir = model_path.parent
    
    # For Detectron2, we can also create a config programmatically if needed
    # But first try to find an existing config
    config_candidates = [
        training_dir / "config.yaml",
        training_dir.parent / "config.yaml",
        Path("/Users/benschofield/Documents/GitHub/HPATR/AI") / "config.yaml",
        Path("/Volumes/LaCie/Experiments/AI") / "config.yaml",
        Path("/Users/benschofield/Documents/GitHub/HPATR") / "config.yaml",
    ]
    
    config_path = None
    for candidate in config_candidates:
        if candidate.exists():
            config_path = str(candidate)
            break
    
    # Config is optional - we'll try to load it from the model checkpoint
    # If not found, we'll create a basic one
    if config_path is None:
        print(f"Note: Config file not found in standard locations.")
        print(f"  Will attempt to load config from model checkpoint or create a basic one.")
        config_path = ""  # Empty string means "not found, will use model or create"
    
    # Find validation directory
    if validation_dir is None:
        validation_candidates = [
            Path("/Users/benschofield/Documents/GitHub/HPATR/AI/Validation_100"),
            Path("/Volumes/LaCie/Experiments/AI/Validation_100"),
            training_dir.parent / "Validation_100",
        ]
        
        validation_dir = None
        for candidate in validation_candidates:
            if candidate.exists():
                validation_dir = str(candidate)
                break
        
        if validation_dir is None:
            raise FileNotFoundError(f"Validation_100 directory not found. Tried: {[str(c) for c in validation_candidates]}")
    
    validation_dir = Path(validation_dir)
    
    # Find annotations file
    annotations_candidates = [
        validation_dir / "blur_annotations.json",
        validation_dir / "annotations.json",
    ]
    
    annotations_path = None
    for candidate in annotations_candidates:
        if candidate.exists():
            annotations_path = str(candidate)
            break
    
    if annotations_path is None:
        raise FileNotFoundError(f"Annotations file not found in {validation_dir}")
    
    # Find images directory (might be in Validation_100/images or directly in Validation_100)
    images_dir = validation_dir / "images"
    if not images_dir.exists():
        # Try Validation_100 directly
        if any(validation_dir.glob("*.png")):
            images_dir = validation_dir
        else:
            raise FileNotFoundError(f"Images not found in {validation_dir} or {validation_dir / 'images'}")
    
    return {
        'config': config_path,
        'weights': str(model_path),
        'annotations': annotations_path,
        'images': str(images_dir),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate Detectron2 model against ground truth",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect all paths (recommended)
  python evaluate_model.py --model /Volumes/LaCie/Experiments/AI/training_2025_12_25_15_43_57/model_final.pth
  
  # Specify all paths manually
  python evaluate_model.py --config config.yaml --weights model.pth --annotations annotations.json --images Validation_100 --output results.xlsx
        """
    )
    
    # Auto-detect mode
    parser.add_argument("--model", help="Path to model_final.pth (auto-detects other paths)")
    parser.add_argument("--validation-dir", help="Path to Validation_100 directory (auto-detected if not specified)")
    
    # Manual mode
    parser.add_argument("--config", help="Path to Detectron2 config file")
    parser.add_argument("--weights", help="Path to trained model weights")
    parser.add_argument("--annotations", help="Path to ground truth annotations JSON")
    parser.add_argument("--images", help="Directory containing validation images")
    
    # Common options
    parser.add_argument("--output", default="evaluation_results.xlsx", help="Path to output Excel file (default: evaluation_results.xlsx)")
    parser.add_argument("--model-name", default="Model", help="Name of the model")
    parser.add_argument("--score-threshold", type=float, default=0.5, help="Minimum confidence score")
    
    args = parser.parse_args()
    
    # Auto-detect mode
    if args.model:
        print("Auto-detecting paths...")
        detected = auto_detect_paths(args.model, args.validation_dir)
        print(f"  Config: {detected['config']}")
        print(f"  Weights: {detected['weights']}")
        print(f"  Annotations: {detected['annotations']}")
        print(f"  Images: {detected['images']}")
        
        config_path = detected['config']
        weights_path = detected['weights']
        annotations_path = detected['annotations']
        images_dir = detected['images']
    else:
        # Manual mode - require all paths
        if not all([args.config, args.weights, args.annotations, args.images]):
            parser.error("Either --model (for auto-detect) or all of --config, --weights, --annotations, --images must be provided")
        
        config_path = args.config
        weights_path = args.weights
        annotations_path = args.annotations
        images_dir = args.images
    
    evaluate_model(
        config_path,
        weights_path,
        annotations_path,
        images_dir,
        args.output,
        args.model_name,
        args.score_threshold
    )
