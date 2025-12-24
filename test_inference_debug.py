"""
Debug script to test inference and see what's happening
"""
import os
import cv2
import torch
from pathlib import Path
from detectron2.engine import DefaultPredictor
from detectron2.config import get_cfg
from detectron2.data import MetadataCatalog

# Model path
MODEL_PATH = r"D:\Experiments\AI\training_2025_12_24_19_37_46\model_final.pth"

# Test image (use first image from your test folder)
TEST_IMAGE = r"D:\Experiments\TrainingData\blur_2025_12_23_20_19_28\images"

print("="*60)
print("Inference Debug Test")
print("="*60)

# Check if model exists
if not os.path.exists(MODEL_PATH):
    print(f"ERROR: Model not found: {MODEL_PATH}")
    exit(1)
print(f"[OK] Model found: {MODEL_PATH}")

# Find a test image
test_folder = Path(TEST_IMAGE)
if test_folder.is_dir():
    images = list(test_folder.glob("*.png")) + list(test_folder.glob("*.jpg"))
    if len(images) == 0:
        print(f"ERROR: No images found in {TEST_IMAGE}")
        exit(1)
    test_image_path = images[0]
else:
    test_image_path = Path(TEST_IMAGE)

print(f"[OK] Test image: {test_image_path}")

# Load image
image = cv2.imread(str(test_image_path))
if image is None:
    print(f"ERROR: Could not load image: {test_image_path}")
    exit(1)
print(f"[OK] Image loaded: {image.shape}")

# Setup config
cfg = get_cfg()
cfg.MODEL.WEIGHTS = MODEL_PATH
cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2
cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.01  # Very low threshold to see all detections
cfg.MODEL.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Need to load the config from the checkpoint or use the same config as training
# Try to load config from checkpoint
try:
    checkpoint = torch.load(MODEL_PATH, map_location="cpu")
    if "cfg" in checkpoint:
        print("[OK] Found config in checkpoint")
except Exception as e:
    print(f"[WARNING] Could not load config from checkpoint: {e}")
    print("[INFO] Using default Mask R-CNN config")

# Register metadata
MetadataCatalog.get("spray_train").set(thing_classes=["droplet", "ligament"])

# Create predictor
print("\nCreating predictor...")
predictor = DefaultPredictor(cfg)

# Run inference with different thresholds
print("\n" + "="*60)
print("Testing with different thresholds:")
print("="*60)

for threshold in [0.01, 0.1, 0.3, 0.5, 0.7]:
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = threshold
    predictor = DefaultPredictor(cfg)
    
    outputs = predictor(image)
    instances = outputs["instances"].to("cpu")
    num_detections = len(instances)
    
    if num_detections > 0:
        scores = instances.scores.numpy()
        print(f"Threshold {threshold:.2f}: {num_detections} detections")
        print(f"  Score range: {scores.min():.3f} to {scores.max():.3f}")
        print(f"  Classes: {instances.pred_classes.numpy()}")
    else:
        print(f"Threshold {threshold:.2f}: 0 detections")

print("\n" + "="*60)
print("Recommendation:")
print("="*60)
print("If you see detections at threshold 0.01 but not at 0.5:")
print("  → Lower the threshold (e.g., --threshold 0.1 or 0.2)")
print("\nIf you see 0 detections even at threshold 0.01:")
print("  → Model may need more training")
print("  → Images may be too different from training data")
print("  → Check if model loaded correctly")

