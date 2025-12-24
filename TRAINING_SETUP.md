# Detectron2 Training Setup Guide

## Step 1: Verify Installation

Run the verification script:
```powershell
python verify_installation.py
```

You should see:
- ✓ Python 3.9.25
- ✓ PyTorch with CUDA available
- ✓ Detectron2 installed
- ✓ All dependencies OK

## Step 2: Organize Your Dataset

Create the folder structure:
```powershell
mkdir datasets
mkdir datasets\spray_dataset
mkdir datasets\spray_dataset\images
```

Copy your data:
```powershell
# If your data is on LaCie drive (adjust path as needed)
Copy-Item "D:\Experiments\TrainingData\blur_*\images\blur_image_*.png" -Destination "datasets\spray_dataset\images\" -Recurse

# Copy annotations (you may need to merge multiple annotation files if you have multiple runs)
Copy-Item "D:\Experiments\TrainingData\blur_*\blur_annotations.json" -Destination "datasets\spray_dataset\" -Recurse
```

**Important:** Make sure `blur_annotations.json` references the correct image filenames!

## Step 3: Install Additional Dependencies

```powershell
pip install tqdm matplotlib
```

## Step 4: Start Training

```powershell
python train_detectron2.py
```

## What You'll See During Training

- **Progress updates** every 10 iterations showing:
  - Current iteration / total iterations
  - Progress percentage
  - Total loss and individual loss components
  - Elapsed time and ETA
  - Training speed (iterations per second)

- **Loss curve plot** saved every 50 iterations to `output/plots/loss_curve.png`

- **Checkpoints** saved every 500 iterations to `output/model_*.pth`

- **Final model** saved as `output/model_final.pth`

## Monitoring Training

### Real-time Monitoring

The script prints progress to the terminal. You can also:

1. **Watch the loss plot** (updates every 50 iterations):
   ```powershell
   # Open the plot file
   start output\plots\loss_curve.png
   ```

2. **Check GPU usage** (in another terminal):
   ```powershell
   nvidia-smi -l 1
   ```

### Expected Training Time

- **RTX 2070 (8GB) with batch_size=1:**
  - ~0.5-1 second per iteration
  - 5000 iterations ≈ 40-80 minutes (1-1.5 hours)

### Stopping Training

- Press `Ctrl+C` to stop early
- The script will save a checkpoint before exiting
- You can resume later by modifying the script to use `resume=True`

## After Training

Your trained model will be at:
- `output/model_final.pth`

Use this for inference on new images!

