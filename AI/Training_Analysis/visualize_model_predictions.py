"""
Visualize what the model sees - shows raw predictions even if below threshold
This helps debug why the model isn't detecting anything
"""
import os
import cv2
import numpy as np
import torch
from pathlib import Path
from detectron2.engine import DefaultPredictor
from detectron2.config import get_cfg
from detectron2.utils.visualizer import Visualizer, ColorMode
from detectron2.data import MetadataCatalog
from detectron2 import model_zoo
import matplotlib.pyplot as plt

# Configuration
MODEL_PATH = r"D:\Experiments\AI\training_2025_12_24_19_37_46\model_final.pth"
TEST_IMAGE_DIR = r"D:\Experiments\TrainingData\blur_2025_12_23_20_19_28\images"
OUTPUT_DIR = Path(r"D:\Experiments\AI\InferenceTests\visualization_debug")

def setup_predictor(model_path: str, score_threshold: float = 0.01):
    """Load model with proper config"""
    cfg = get_cfg()
    cfg.merge_from_file(
        model_zoo.get_config_file("COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml")
    )
    cfg.MODEL.WEIGHTS = model_path
    cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = score_threshold
    cfg.MODEL.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    
    MetadataCatalog.get("spray_train").set(thing_classes=["droplet", "ligament"])
    
    return DefaultPredictor(cfg), cfg

def visualize_predictions(image_path, predictor, output_dir):
    """Visualize all predictions, even low-confidence ones"""
    print(f"\nProcessing: {image_path}")
    
    # Load image
    image = cv2.imread(str(image_path))
    if image is None:
        print(f"  ERROR: Could not load image")
        return
    
    # Run inference
    outputs = predictor(image)
    instances = outputs["instances"].to("cpu")
    
    num_detections = len(instances)
    print(f"  Detections: {num_detections}")
    
    if num_detections > 0:
        scores = instances.scores.numpy()
        classes = instances.pred_classes.numpy()
        print(f"  Score range: {scores.min():.4f} to {scores.max():.4f}")
        print(f"  Classes: {np.bincount(classes)} (0=droplet, 1=ligament)")
        
        # Show top 10 detections
        print(f"  Top detections:")
        for i in range(min(10, num_detections)):
            class_name = ["droplet", "ligament"][classes[i]]
            print(f"    {i+1}. {class_name}: {scores[i]:.4f}")
    else:
        print(f"  WARNING: No detections found!")
    
    # Create visualization
    vis = Visualizer(
        image[:, :, ::-1],  # BGR to RGB
        MetadataCatalog.get("spray_train"),
        scale=1.0,
        instance_mode=ColorMode.IMAGE_BW
    )
    
    vis_output = vis.draw_instance_predictions(instances)
    vis_image = vis_output.get_image()[:, :, ::-1]  # RGB to BGR
    
    # Save visualization
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{Path(image_path).stem}_predictions.png"
    cv2.imwrite(str(output_path), vis_image)
    print(f"  Saved: {output_path}")
    
    # Also create a side-by-side comparison
    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    
    # Original image
    axes[0].imshow(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    axes[0].set_title("Original Image", fontsize=14, fontweight='bold')
    axes[0].axis('off')
    
    # Predictions
    axes[1].imshow(cv2.cvtColor(vis_image, cv2.COLOR_BGR2RGB))
    title = f"Predictions (threshold=0.01)\n{num_detections} detections"
    if num_detections > 0:
        title += f"\nScores: {scores.min():.3f} - {scores.max():.3f}"
    axes[1].set_title(title, fontsize=14, fontweight='bold')
    axes[1].axis('off')
    
    plt.tight_layout()
    comparison_path = output_dir / f"{Path(image_path).stem}_comparison.png"
    plt.savefig(comparison_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved comparison: {comparison_path}")
    
    return num_detections, scores if num_detections > 0 else None

def main():
    print("="*60)
    print("Model Prediction Visualizer")
    print("="*60)
    print(f"Model: {MODEL_PATH}")
    print(f"Test images: {TEST_IMAGE_DIR}")
    print(f"Output: {OUTPUT_DIR}")
    print("="*60)
    
    # Check model exists
    if not os.path.exists(MODEL_PATH):
        print(f"ERROR: Model not found: {MODEL_PATH}")
        return
    
    # Find test images
    test_dir = Path(TEST_IMAGE_DIR)
    if not test_dir.exists():
        print(f"ERROR: Test directory not found: {TEST_IMAGE_DIR}")
        return
    
    images = list(test_dir.glob("*.png")) + list(test_dir.glob("*.jpg")) + list(test_dir.glob("*.jpeg"))
    if len(images) == 0:
        print(f"ERROR: No images found in {TEST_IMAGE_DIR}")
        return
    
    print(f"\nFound {len(images)} images")
    print("Testing first 5 images...\n")
    
    # Setup predictor with very low threshold
    predictor, cfg = setup_predictor(MODEL_PATH, score_threshold=0.01)
    
    # Process first few images
    results = []
    for i, image_path in enumerate(images[:5]):
        num_det, scores = visualize_predictions(image_path, predictor, OUTPUT_DIR)
        results.append({
            'image': image_path.name,
            'detections': num_det,
            'scores': scores.tolist() if scores is not None else []
        })
    
    # Summary
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    total_detections = sum(r['detections'] for r in results)
    print(f"Total images tested: {len(results)}")
    print(f"Total detections: {total_detections}")
    print(f"Average detections per image: {total_detections / len(results):.1f}")
    
    if total_detections == 0:
        print("\n⚠️  NO DETECTIONS FOUND!")
        print("\nPossible reasons:")
        print("  1. Model needs more training")
        print("  2. Images are too different from training data")
        print("  3. Model checkpoint may be corrupted")
        print("  4. Check if training actually completed successfully")
    else:
        all_scores = []
        for r in results:
            all_scores.extend(r['scores'])
        if all_scores:
            print(f"\nScore statistics:")
            print(f"  Min: {min(all_scores):.4f}")
            print(f"  Max: {max(all_scores):.4f}")
            print(f"  Mean: {np.mean(all_scores):.4f}")
            print(f"  Median: {np.median(all_scores):.4f}")
    
    print(f"\nVisualizations saved to: {OUTPUT_DIR}")
    print("="*60)

if __name__ == "__main__":
    main()

