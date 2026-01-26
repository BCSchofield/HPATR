"""
Evaluate multiple models from a text file and output results to CSV.
Uses Validation_100 dataset and auto-detects anchor configurations.
"""

import os
import json
import csv
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

import torch
import numpy as np
from detectron2.engine import DefaultPredictor
from detectron2.config import get_cfg
from detectron2.data import DatasetCatalog, MetadataCatalog
from detectron2.evaluation import COCOEvaluator, inference_on_dataset
from detectron2 import model_zoo
from pycocotools.coco import COCO

# ============================================================================
# CONFIGURATION
# ============================================================================

MODELS_TXT_PATH = Path(r"D:\Experiments\Validation_100\Evaluation\models.txt")
VALIDATION_100_DIR = Path(r"D:\Experiments\Validation_100")
OUTPUT_CSV_PATH = Path(r"D:\Experiments\Validation_100\Evaluation\model_comparison_results.csv")

# Validation dataset paths
VALIDATION_ANNOTATIONS = VALIDATION_100_DIR / "blur_annotations.json"
VALIDATION_IMAGES = VALIDATION_100_DIR / "images"
DATASET_NAME = "validation_100"

# Score threshold for evaluation
SCORE_THRESHOLD = 0.5

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def detect_anchor_config(model_path: str) -> Optional[List[List[int]]]:
    """
    Detect which anchor configuration a model was trained with.
    Returns None for default COCO anchors, or [[8, 16, 32, 64]] for custom anchors.
    """
    model_path_lower = model_path.lower()
    
    # Check if it's Dennis or Early_Dennis (uses [8, 16, 32, 64] anchors)
    if "dennis" in model_path_lower or "early_dennis" in model_path_lower:
        return [[8, 16, 32, 64]]
    
    # Check if it's Claudia (uses default COCO anchors)
    if "claudia" in model_path_lower:
        return None  # None means use default
    
    # Default: assume default COCO anchors
    # You can add more detection logic here
    return None

def convert_path_to_windows(mac_path: str) -> str:
    """Convert Mac path to Windows path if needed."""
    # If it's already a Windows path, return as-is
    if mac_path.startswith("D:\\") or mac_path.startswith("C:\\"):
        return mac_path
    
    # Convert Mac paths to Windows
    # /Volumes/LaCie/Experiments/AI/... -> D:\Experiments\AI\...
    if mac_path.startswith("/Volumes/LaCie/"):
        return mac_path.replace("/Volumes/LaCie/", "D:\\").replace("/", "\\")
    
    # If it's a relative path or other format, try to resolve it
    return mac_path

def load_models_from_txt(txt_path: Path) -> List[str]:
    """Load model paths from text file, skipping comments and empty lines."""
    models = []
    if not txt_path.exists():
        raise FileNotFoundError(f"Models file not found: {txt_path}")
    
    with open(txt_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Convert to Windows path if needed
            model_path = convert_path_to_windows(line)
            if Path(model_path).exists():
                models.append(model_path)
            else:
                print(f"Warning: Model not found, skipping: {model_path}")
    
    return models

def setup_validation_dataset():
    """Register Validation_100 dataset."""
    if not VALIDATION_ANNOTATIONS.exists():
        raise FileNotFoundError(f"Validation annotations not found: {VALIDATION_ANNOTATIONS}")
    if not VALIDATION_IMAGES.exists():
        raise FileNotFoundError(f"Validation images directory not found: {VALIDATION_IMAGES}")
    
    # Register dataset using register_coco_instances
    from detectron2.data.datasets import register_coco_instances
    
    try:
        DatasetCatalog.get(DATASET_NAME)
        print(f"[OK] Dataset already registered: {DATASET_NAME}")
    except KeyError:
        register_coco_instances(DATASET_NAME, {}, str(VALIDATION_ANNOTATIONS), str(VALIDATION_IMAGES))
        MetadataCatalog.get(DATASET_NAME).set(thing_classes=["droplet", "ligament"])
        print(f"[OK] Registered dataset: {DATASET_NAME}")
    
    print(f"[OK] Annotations: {VALIDATION_ANNOTATIONS}")
    print(f"[OK] Images: {VALIDATION_IMAGES}")


def evaluate_model_with_coco(model_path: str) -> Dict:
    """
    Evaluate a single model using COCO evaluator.
    Returns dictionary with all metrics.
    """
    print(f"\n{'='*80}")
    print(f"Evaluating: {model_path}")
    print(f"{'='*80}")
    
    # Auto-detect anchor configuration
    anchor_config = detect_anchor_config(model_path)
    if anchor_config:
        print(f"  [INFO] Detected custom anchors: {anchor_config}")
    else:
        print(f"  [INFO] Using default COCO anchors")
    
    # Setup config (don't create predictor yet, we need the model directly)
    cfg = get_cfg()
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )
    
    # Set anchor sizes BEFORE loading weights (critical!)
    if anchor_config is None:
        print(f"  [OK] Using default COCO anchor configuration")
    else:
        cfg.MODEL.ANCHOR_GENERATOR.SIZES = anchor_config
        print(f"  [OK] Using custom anchor sizes: {anchor_config}")
    
    # Set model weights
    cfg.MODEL.WEIGHTS = model_path
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2  # droplet and ligament
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = SCORE_THRESHOLD
    
    # Set device
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cfg.MODEL.DEVICE = device
    
    # Set NUM_WORKERS to 0 to avoid multiprocessing issues on Windows
    cfg.DATALOADER.NUM_WORKERS = 0
    
    # Register dataset
    from detectron2.data.datasets import register_coco_instances
    try:
        DatasetCatalog.get(DATASET_NAME)
        print(f"  [OK] Dataset already registered: {DATASET_NAME}")
    except KeyError:
        register_coco_instances(DATASET_NAME, {}, str(VALIDATION_ANNOTATIONS), str(VALIDATION_IMAGES))
        MetadataCatalog.get(DATASET_NAME).set(thing_classes=["droplet", "ligament"])
        print(f"  [OK] Registered dataset: {DATASET_NAME}")
    
    # Create COCO evaluator (use Evaluation folder for temp files)
    eval_output_dir = OUTPUT_CSV_PATH.parent / "temp_eval"
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Build test loader and evaluator
    from detectron2.data import build_detection_test_loader
    from detectron2.modeling import build_model
    
    # Build model
    model = build_model(cfg)
    model.eval()
    
    # Load weights
    from detectron2.checkpoint import DetectionCheckpointer
    checkpointer = DetectionCheckpointer(model)
    checkpointer.load(cfg.MODEL.WEIGHTS)
    
    # Build test loader
    test_loader = build_detection_test_loader(cfg, DATASET_NAME)
    
    # Create evaluator
    evaluator = COCOEvaluator(DATASET_NAME, output_dir=str(eval_output_dir), use_fast_impl=False)
    
    # Run evaluation
    print(f"  Running COCO evaluation on {DATASET_NAME}...")
    print(f"  This may take a few minutes...")
    results = inference_on_dataset(model, test_loader, evaluator)
    
    # Calculate precision and recall from COCO results
    # Read the COCO results file before cleanup
    coco_results_file = eval_output_dir / "coco_instances_results.json"
    precision = None
    recall = None
    
    if coco_results_file.exists():
        try:
            from pycocotools.coco import COCO as COCO_API
            from pycocotools.cocoeval import COCOeval
            
            # Load ground truth
            coco_gt = COCO_API(str(VALIDATION_ANNOTATIONS))
            
            # Load predictions
            coco_dt = coco_gt.loadRes(str(coco_results_file))
            
            # Create evaluator for segmentation
            coco_eval = COCOeval(coco_gt, coco_dt, 'segm')
            coco_eval.evaluate()
            coco_eval.accumulate()
            
            # Extract precision and recall
            # Precision array: [T x R x K x A x M]
            # Recall array: [T x K x A x M]
            # T=IoU thresholds, R=recall thresholds, K=classes, A=area, M=maxDets
            if hasattr(coco_eval, 'eval') and coco_eval.eval is not None:
                eval_precision = coco_eval.eval['precision']
                eval_recall = coco_eval.eval['recall']
                
                # Average precision across all dimensions (IoU thresholds, recall levels, classes, areas, maxDets)
                # Only count valid entries (> -1)
                valid_precision = eval_precision[eval_precision > -1]
                valid_recall = eval_recall[eval_recall > -1]
                
                if len(valid_precision) > 0:
                    precision = float(np.mean(valid_precision))
                if len(valid_recall) > 0:
                    recall = float(np.mean(valid_recall))
                    
                if precision is not None:
                    print(f"  [OK] Precision: {precision:.4f}")
                if recall is not None:
                    print(f"  [OK] Recall: {recall:.4f}")
        except Exception as e:
            print(f"  [WARNING] Could not calculate precision/recall: {e}")
            import traceback
            traceback.print_exc()
    
    # Clean up temp directory
    import shutil
    if eval_output_dir.exists():
        shutil.rmtree(eval_output_dir)
    
    # Flatten nested results if needed
    flattened_results = {}
    if isinstance(results, dict):
        if 'segm' in results and isinstance(results['segm'], dict):
            for key, value in results['segm'].items():
                flattened_results[f'segm/{key}'] = value
        if 'bbox' in results and isinstance(results['bbox'], dict):
            for key, value in results['bbox'].items():
                flattened_results[f'bbox/{key}'] = value
        
        # Also check if already flattened
        if not flattened_results and any('/' in k for k in results.keys()):
            flattened_results = results
    
    # Use flattened results (or original if flattening didn't work)
    final_results = flattened_results if flattened_results else results
    
    # Debug: print all available keys (for first model only)
    if not hasattr(evaluate_model_with_coco, '_printed_keys'):
        all_keys = list(final_results.keys())
        print(f"  [INFO] Available metrics ({len(all_keys)} total): {', '.join(all_keys[:15])}...")
        evaluate_model_with_coco._printed_keys = True
    
    # Extract model name from path
    model_name = Path(model_path).stem
    
    # Prepare result dictionary
    result_dict = {
        'model_name': model_name,
        'model_path': model_path,
        'anchor_config': str(anchor_config) if anchor_config else 'default',
    }
    
    # Add all AP metrics
    ap_metrics = [
        'segm/AP', 'segm/AP50', 'segm/AP75',
        'segm/AP-droplet', 'segm/AP-ligament',
        'bbox/AP', 'bbox/AP50', 'bbox/AP75',
        'bbox/AP-droplet', 'bbox/AP-ligament',
    ]
    
    for metric in ap_metrics:
        value = final_results.get(metric, None)
        result_dict[metric] = float(value) if value is not None else None
    
    # Add precision and recall if calculated
    if precision is not None:
        result_dict['precision'] = precision
    if recall is not None:
        result_dict['recall'] = recall
    
    # Add all available metrics (APs, APm, APl for small/medium/large objects)
    for key in final_results.keys():
        if key not in result_dict:  # Don't duplicate already-added metrics
            value = final_results.get(key, None)
            if value is not None:
                try:
                    result_dict[key] = float(value)
                except (ValueError, TypeError):
                    result_dict[key] = str(value)
    
    # Print summary
    if 'segm/AP' in final_results:
        print(f"  [OK] segm/AP: {final_results['segm/AP']:.4f}")
    if 'segm/AP50' in final_results:
        print(f"  [OK] segm/AP50: {final_results['segm/AP50']:.4f}")
    if 'segm/AP75' in final_results:
        print(f"  [OK] segm/AP75: {final_results['segm/AP75']:.4f}")
    if 'segm/AP-droplet' in final_results:
        print(f"  [OK] segm/AP-droplet: {final_results['segm/AP-droplet']:.4f}")
    if 'segm/AP-ligament' in final_results:
        print(f"  [OK] segm/AP-ligament: {final_results['segm/AP-ligament']:.4f}")
    
    return result_dict

def save_results_to_csv(results_list: List[Dict], output_path: Path):
    """Save evaluation results to CSV file."""
    if not results_list:
        print("No results to save!")
        return
    
    # Get all unique keys from all results
    all_keys = set()
    for result in results_list:
        all_keys.update(result.keys())
    
    # Define column order (important metrics first, organized for easy graphing)
    priority_keys = [
        # Model info
        'model_name', 'model_path', 'anchor_config',
        # Precision and Recall (if available)
        'precision', 'recall',
        # Segmentation AP metrics (main metrics)
        'segm/AP', 'segm/AP50', 'segm/AP75',
        'segm/APs', 'segm/APm', 'segm/APl',  # Small, medium, large objects
        'segm/AP-droplet', 'segm/AP-ligament',
        # Bounding box AP metrics
        'bbox/AP', 'bbox/AP50', 'bbox/AP75',
        'bbox/APs', 'bbox/APm', 'bbox/APl',  # Small, medium, large objects
        'bbox/AP-droplet', 'bbox/AP-ligament',
    ]
    
    # Add remaining keys in sorted order
    remaining_keys = sorted(all_keys - set(priority_keys))
    fieldnames = [k for k in priority_keys if k in all_keys] + remaining_keys
    
    # Write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in results_list:
            # Convert None to empty string for CSV
            row = {k: (result.get(k, '') if result.get(k) is not None else '') for k in fieldnames}
            writer.writerow(row)
    
    print(f"\n{'='*80}")
    print(f"Results saved to: {output_path}")
    print(f"Total models evaluated: {len(results_list)}")
    print(f"{'='*80}")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"\n{'='*80}")
    print("Multi-Model Evaluation Script")
    print(f"{'='*80}")
    
    # Load models from text file
    print(f"\nLoading models from: {MODELS_TXT_PATH}")
    model_paths = load_models_from_txt(MODELS_TXT_PATH)
    
    if not model_paths:
        print("ERROR: No valid models found in models.txt!")
        return
    
    print(f"Found {len(model_paths)} model(s) to evaluate:")
    for i, path in enumerate(model_paths, 1):
        print(f"  {i}. {path}")
    
    # Setup validation dataset
    print(f"\nSetting up validation dataset...")
    setup_validation_dataset()
    
    # Evaluate each model
    results_list = []
    for i, model_path in enumerate(model_paths, 1):
        print(f"\n[{i}/{len(model_paths)}] Processing model...")
        try:
            result = evaluate_model_with_coco(model_path)
            results_list.append(result)
        except Exception as e:
            print(f"  [ERROR] Failed to evaluate {model_path}: {e}")
            import traceback
            traceback.print_exc()
            # Add error entry
            results_list.append({
                'model_name': Path(model_path).stem,
                'model_path': model_path,
                'error': str(e)
            })
    
    # Save results to CSV
    print(f"\nSaving results...")
    save_results_to_csv(results_list, OUTPUT_CSV_PATH)
    
    # Print summary
    print(f"\n{'='*80}")
    print("EVALUATION SUMMARY")
    print(f"{'='*80}")
    
    successful_results = [r for r in results_list if 'error' not in r and 'segm/AP' in r]
    if successful_results:
        print(f"\nSuccessful evaluations: {len(successful_results)}")
        print(f"\n{'Model':<25} {'segm/AP':<10} {'segm/AP50':<10} {'segm/AP75':<10} {'segm/AP-droplet':<15} {'segm/AP-ligament':<15}")
        print("-" * 100)
        for result in successful_results:
            ap = result.get('segm/AP', 'N/A')
            ap50 = result.get('segm/AP50', 'N/A')
            ap75 = result.get('segm/AP75', 'N/A')
            ap_drop = result.get('segm/AP-droplet', 'N/A')
            ap_lig = result.get('segm/AP-ligament', 'N/A')
            if isinstance(ap, (int, float)):
                print(f"{result['model_name']:<25} {ap:<10.2f} {ap50:<10.2f} {ap75:<10.2f} {ap_drop:<15.2f} {ap_lig:<15.2f}")
            else:
                print(f"{result['model_name']:<25} {ap:<10} {ap50:<10} {ap75:<10} {ap_drop:<15} {ap_lig:<15}")
        
        print(f"\nNote: AP (Average Precision) combines precision and recall.")
        print(f"      For separate precision/recall metrics, use the per-image evaluation script.")
    
    failed_results = [r for r in results_list if 'error' in r]
    if failed_results:
        print(f"\nFailed evaluations: {len(failed_results)}")
        for result in failed_results:
            print(f"  - {result['model_name']}: {result.get('error', 'Unknown error')}")
    
    print(f"\n{'='*80}")
    print("Done!")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
