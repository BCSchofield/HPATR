# Merge term 1
"""
Setup Training Dataset
Copies and organizes data from source to Detectron2 training structure
"""

import os
import shutil
import json
from pathlib import Path

# Source and destination paths
SOURCE_DIR = Path(r"D:\Experiments\TrainingData\blur_2025_12_23_20_21_35")
DEST_DIR = Path(r"D:\Experiments\TrainingData\Detectron_Trial_1")

# Detectron2 structure
IMAGES_DIR = DEST_DIR / "images"
ANNOTATIONS_FILE = DEST_DIR / "annotations.json"

def setup_dataset():
    """Copy and organize dataset for Detectron2"""
    
    print("=" * 60)
    print("Setting up Detectron2 Training Dataset")
    print("=" * 60)
    
    # Check source exists
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(f"Source directory not found: {SOURCE_DIR}")
    
    print(f"\nSource: {SOURCE_DIR}")
    print(f"Destination: {DEST_DIR}")
    
    # Create destination structure
    print(f"\n1. Creating directory structure...")
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"   [OK] Created: {DEST_DIR}")
    print(f"   [OK] Created: {IMAGES_DIR}")
    
    # Copy images
    print(f"\n2. Copying images...")
    source_images_dir = SOURCE_DIR / "images"
    
    if not source_images_dir.exists():
        raise FileNotFoundError(f"Images directory not found: {source_images_dir}")
    
    image_files = list(source_images_dir.glob("blur_image_*.png"))
    print(f"   Found {len(image_files)} images")
    
    copied_count = 0
    for img_file in image_files:
        dest_file = IMAGES_DIR / img_file.name
        shutil.copy2(img_file, dest_file)
        copied_count += 1
        if copied_count % 100 == 0:
            print(f"   Copied {copied_count}/{len(image_files)} images...")
    
    print(f"   [OK] Copied {copied_count} images to {IMAGES_DIR}")
    
    # Copy and fix annotations
    print(f"\n3. Processing annotations...")
    source_annotations = SOURCE_DIR / "blur_annotations.json"
    
    if not source_annotations.exists():
        raise FileNotFoundError(f"Annotations file not found: {source_annotations}")
    
    # Load annotations
    with open(source_annotations, 'r') as f:
        annotations = json.load(f)
    
    print(f"   Loaded annotations: {len(annotations.get('images', []))} images, {len(annotations.get('annotations', []))} annotations")
    
    # Verify image filenames match (they should already be correct)
    # The annotations should reference "blur_image_XXXX.png" which matches the copied files
    # No renaming needed since we're keeping the same filenames
    
    # Save annotations
    with open(ANNOTATIONS_FILE, 'w') as f:
        json.dump(annotations, f, indent=2)
    
    print(f"   [OK] Saved annotations to {ANNOTATIONS_FILE}")
    
    # Summary
    print(f"\n{'=' * 60}")
    print("Dataset Setup Complete!")
    print(f"{'=' * 60}")
    print(f"\nFinal structure:")
    print(f"  {DEST_DIR}/")
    print(f"    - images/")
    print(f"        - blur_image_0001.png")
    print(f"        - blur_image_0002.png")
    print(f"        - ... ({len(image_files)} images)")
    print(f"    - annotations.json")
    print(f"\nTotal images: {len(image_files)}")
    print(f"Total annotations: {len(annotations.get('annotations', []))}")
    print(f"\nYou can now train using:")
    print(f"  python train_detectron2.py")
    print(f"\n(Update train_detectron2.py to use:")
    print(f"  ANNOTATIONS_PATH = r'{ANNOTATIONS_FILE}'")
    print(f"  IMAGES_PATH = r'{IMAGES_DIR}')")
    print(f"{'=' * 60}\n")

if __name__ == "__main__":
    setup_dataset()

