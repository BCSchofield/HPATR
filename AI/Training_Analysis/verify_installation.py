"""Verify Detectron2 installation and GPU setup"""
import sys

print("=" * 60)
print("Verifying Installation")
print("=" * 60)

# Check Python version
print(f"\n1. Python version: {sys.version}")

# Check PyTorch
try:
    import torch
    print(f"2. PyTorch version: {torch.__version__}")
    print(f"   CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"   GPU: {torch.cuda.get_device_name(0)}")
        print(f"   CUDA version: {torch.version.cuda}")
    else:
        print("   WARNING: CUDA not available!")
except ImportError:
    print("   ERROR: PyTorch not installed!")
    sys.exit(1)

# Check Detectron2
try:
    import detectron2
    print(f"3. Detectron2 version: {detectron2.__version__}")
except ImportError:
    print("   ERROR: Detectron2 not installed!")
    sys.exit(1)

# Check other dependencies
deps = ['cv2', 'matplotlib', 'pycocotools']
for dep in deps:
    try:
        __import__(dep)
        print(f"4. {dep}: OK")
    except ImportError:
        print(f"   ERROR: {dep} not installed!")

print("\n" + "=" * 60)
print("Installation check complete!")
print("=" * 60)

