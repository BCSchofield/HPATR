"""
Check if Validation_100 images are actually the same files as training images
or just have the same names
"""

import hashlib
from pathlib import Path

# Training dataset paths
TRAINING_IMAGES_PATH = Path(r"D:\Experiments\TrainingData\Detectron_Trial_2\images")
VALIDATION_IMAGES_PATH = Path(r"D:\Experiments\Validation_100\images")

def get_file_hash(filepath):
    """Calculate MD5 hash of a file"""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def check_file_identity():
    """Check if files are the same (same hash) or just same name"""
    print("=" * 60)
    print("Checking Image File Identity")
    print("=" * 60)
    
    # Get validation images
    validation_files = sorted(list(VALIDATION_IMAGES_PATH.glob("*.png")))
    validation_files = [f for f in validation_files if not f.name.startswith("._")]
    
    print(f"\nValidation images: {len(validation_files)}")
    print(f"Training images directory: {TRAINING_IMAGES_PATH}")
    
    # Check first 10 validation images
    print(f"\nChecking first 10 validation images...")
    print("-" * 60)
    
    same_files = 0
    different_files = 0
    missing_files = 0
    
    for val_file in validation_files[:10]:
        val_hash = get_file_hash(val_file)
        train_file = TRAINING_IMAGES_PATH / val_file.name
        
        if not train_file.exists():
            print(f"  {val_file.name}: NOT FOUND in training set")
            missing_files += 1
        else:
            train_hash = get_file_hash(train_file)
            if val_hash == train_hash:
                print(f"  {val_file.name}: SAME FILE (identical hash)")
                same_files += 1
            else:
                print(f"  {val_file.name}: DIFFERENT FILE (different hash)")
                different_files += 1
    
    # Check all validation images
    print(f"\nChecking all {len(validation_files)} validation images...")
    same_count = 0
    different_count = 0
    missing_count = 0
    
    for val_file in validation_files:
        val_hash = get_file_hash(val_file)
        train_file = TRAINING_IMAGES_PATH / val_file.name
        
        if not train_file.exists():
            missing_count += 1
        else:
            train_hash = get_file_hash(train_file)
            if val_hash == train_hash:
                same_count += 1
            else:
                different_count += 1
    
    print("-" * 60)
    print(f"\nResults:")
    print(f"  Same files (identical): {same_count}/{len(validation_files)}")
    print(f"  Different files (same name, different content): {different_count}/{len(validation_files)}")
    print(f"  Missing from training set: {missing_count}/{len(validation_files)}")
    
    if same_count == len(validation_files):
        print(f"\n[PROBLEM] All validation images are IDENTICAL to training images!")
        print(f"  This means they were copied or are the same files.")
        print(f"  Possible causes:")
        print(f"    1. Validation images were accidentally copied into training set")
        print(f"    2. Training set includes the validation images")
        print(f"    3. Same image generation script created duplicates")
    elif different_count > 0:
        print(f"\n[OK] Some validation images have same names but different content")
        print(f"  This is fine - just a naming coincidence")
    elif missing_count == len(validation_files):
        print(f"\n[OK] Validation images are NOT in training set!")
        print(f"  The overlap check was wrong - they just have same names")
    
    # Check file sizes and modification times
    print(f"\n" + "=" * 60)
    print("File Metadata Comparison (first 5 files):")
    print("=" * 60)
    for val_file in validation_files[:5]:
        train_file = TRAINING_IMAGES_PATH / val_file.name
        if train_file.exists():
            val_size = val_file.stat().st_size
            train_size = train_file.stat().st_size
            val_mtime = val_file.stat().st_mtime
            train_mtime = train_file.stat().st_mtime
            
            print(f"\n{val_file.name}:")
            print(f"  Validation: {val_size:,} bytes, modified {val_mtime}")
            print(f"  Training:   {train_size:,} bytes, modified {train_mtime}")
            if val_size == train_size and abs(val_mtime - train_mtime) < 1:
                print(f"  [SAME] Same size and modification time - likely same file")
            elif val_size == train_size:
                print(f"  [SIMILAR] Same size but different modification time")
            else:
                print(f"  [DIFFERENT] Different sizes - definitely different files")

if __name__ == "__main__":
    check_file_identity()

