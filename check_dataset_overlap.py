"""
Check if Validation_100 images overlap with training dataset
"""

import json
from pathlib import Path

# Training dataset paths
TRAINING_IMAGES_PATH = Path(r"D:\Experiments\TrainingData\Detectron_Trial_2\images")
TRAINING_ANNOTATIONS_PATH = Path(r"D:\Experiments\TrainingData\Detectron_Trial_2\blur_annotations.json")

# Validation dataset paths (try common locations)
VALIDATION_CANDIDATES = [
    Path(r"D:\Experiments\Validation_100"),
    Path(r"D:\Experiments\AI\Validation_100"),
    Path(r"C:\Users\BenSc\Documents\GitHub\HPATR\AI\Validation_100"),
]

def find_validation_dir():
    """Find the Validation_100 directory"""
    for candidate in VALIDATION_CANDIDATES:
        if candidate.exists():
            # Check if it has images or an images subdirectory
            if (candidate / "images").exists():
                return candidate / "images"
            elif any(candidate.glob("*.png")):
                return candidate
    return None

def get_image_filenames(directory):
    """Get all image filenames from a directory"""
    if not directory.exists():
        return set()
    
    # Get all PNG files
    image_files = list(directory.glob("*.png"))
    # Filter out macOS metadata files (._ files)
    filenames = {f.name for f in image_files if not f.name.startswith("._")}
    return filenames

def get_annotated_filenames(annotations_path):
    """Get image filenames from annotations JSON"""
    if not annotations_path.exists():
        return set()
    
    with open(annotations_path, 'r') as f:
        data = json.load(f)
    
    filenames = {img['file_name'] for img in data.get('images', [])}
    return filenames

def main():
    print("=" * 60)
    print("Checking Dataset Overlap")
    print("=" * 60)
    
    # Get training images
    print(f"\n1. Training Dataset:")
    print(f"   Images directory: {TRAINING_IMAGES_PATH}")
    print(f"   Annotations: {TRAINING_ANNOTATIONS_PATH}")
    
    training_images = get_image_filenames(TRAINING_IMAGES_PATH)
    training_annotated = get_annotated_filenames(TRAINING_ANNOTATIONS_PATH)
    
    print(f"   Found {len(training_images)} image files in directory")
    print(f"   Found {len(training_annotated)} images in annotations")
    
    # Combine training filenames (from directory and annotations)
    all_training = training_images | training_annotated
    print(f"   Total unique training images: {len(all_training)}")
    
    # Get validation images
    print(f"\n2. Validation Dataset:")
    validation_dir = find_validation_dir()
    
    if validation_dir is None:
        print("   [ERROR] Validation_100 directory not found!")
        print(f"   Tried: {[str(c) for c in VALIDATION_CANDIDATES]}")
        return
    
    print(f"   Validation directory: {validation_dir}")
    
    validation_images = get_image_filenames(validation_dir)
    print(f"   Found {len(validation_images)} image files")
    
    # Check for annotations in validation directory
    validation_annotations = None
    for ann_file in ["blur_annotations.json", "annotations.json"]:
        ann_path = validation_dir.parent / ann_file
        if ann_path.exists():
            validation_annotations = ann_path
            break
    
    if validation_annotations:
        validation_annotated = get_annotated_filenames(validation_annotations)
        print(f"   Found {len(validation_annotated)} images in annotations")
        # Use annotated filenames if available (more accurate)
        validation_images = validation_annotated
    else:
        print(f"   No annotations file found (using directory listing)")
    
    # Check for overlap
    print(f"\n3. Overlap Analysis:")
    print("=" * 60)
    
    overlap = all_training & validation_images
    
    if len(overlap) == 0:
        print("   [OK] NO OVERLAP FOUND!")
        print("   Validation_100 contains completely NEW images")
        print("   This is a TRUE test of generalization!")
    else:
        print(f"   [WARNING] OVERLAP DETECTED!")
        print(f"   {len(overlap)} images appear in both datasets")
        print(f"   This means the model has seen {len(overlap)}/{len(validation_images)} validation images during training")
        print(f"   Overlap percentage: {100 * len(overlap) / len(validation_images):.1f}%")
        
        if len(overlap) <= 5:
            print(f"\n   Overlapping files:")
            for filename in sorted(overlap):
                print(f"     - {filename}")
        else:
            print(f"\n   First 10 overlapping files:")
            for filename in sorted(list(overlap))[:10]:
                print(f"     - {filename}")
            print(f"     ... and {len(overlap) - 10} more")
    
    # Additional stats
    print(f"\n4. Summary:")
    print("=" * 60)
    print(f"   Training images: {len(all_training)}")
    print(f"   Validation images: {len(validation_images)}")
    print(f"   Overlapping images: {len(overlap)}")
    print(f"   Unique validation images: {len(validation_images) - len(overlap)}")
    
    if len(overlap) == 0:
        print(f"\n   [EXCELLENT] Your model is being tested on completely unseen data!")
        print(f"   This is the gold standard for evaluation!")
    elif len(overlap) < len(validation_images) * 0.1:
        print(f"\n   [GOOD] Only {100 * len(overlap) / len(validation_images):.1f}% overlap")
        print(f"   Most validation images are new")
    else:
        print(f"\n   [WARNING] Significant overlap detected")
        print(f"   Consider using a separate test set for true evaluation")

if __name__ == "__main__":
    main()

