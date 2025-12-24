# Detectron2 Training & Inference Guide

## Part 1: Training Outputs

When you run `python train_detectron2.py`, you'll see:

### Real-time Terminal Output:
```
[10/5000] (0.2%)
  Total Loss: 2.3456
  Time: 0.2 min elapsed, ETA: 83.5 min (1.4 hours)
  Speed: 0.50 iter/sec
    loss_cls: 0.8234
    loss_box_reg: 0.4567
    loss_mask: 1.2345
  📊 Loss plot saved: output/plots/loss_curve.png
```

**What to look for:**
- ✅ **Loss decreasing**: Should start high (2-3) and gradually decrease
- ✅ **Stable training**: Loss should decrease smoothly, not spike randomly
- ✅ **GPU usage**: Check with `nvidia-smi` - should show high GPU utilization

### Files Created During Training:

1. **`output/model_*.pth`** - Checkpoints (saved every 500 iterations)
2. **`output/model_final.pth`** - Final trained model (use this for inference!)
3. **`output/plots/loss_curve.png`** - Loss curve (updates every 50 iterations)
4. **`output/metrics.json`** - Training metrics log

### How to Know It's Working:

1. **Loss is decreasing** (check the plot or terminal output)
2. **GPU is being used** (check `nvidia-smi` in another terminal)
3. **No errors** in the terminal
4. **Checkpoints are being saved** (check `output/` folder)

---

## Part 2: Using the Trained Model (Inference)

After training completes, use `inference_detectron2.py` to test on new images.

### Basic Usage:

**Single image:**
```powershell
python inference_detectron2.py --model output/model_final.pth --images path/to/image.png
```

**Multiple images:**
```powershell
python inference_detectron2.py --model output/model_final.pth --images image1.png image2.png image3.png
```

**Entire directory:**
```powershell
python inference_detectron2.py --model output/model_final.pth --images path/to/images/
```

**With size calibration (if you know pixels_per_mm):**
```powershell
python inference_detectron2.py --model output/model_final.pth --images image.png --pixels-per-mm 10.0
```

### Output Structure:

After running inference, you'll get:

```
inference_results/
├── visualizations/
│   ├── image1_result.png      # Image with colored masks overlaid
│   └── image2_result.png
├── masks/
│   ├── image1/
│   │   ├── droplet_1_mask.png  # Individual binary masks
│   │   ├── droplet_2_mask.png
│   │   └── ligament_1_mask.png
│   └── image2/
│       └── ...
└── data/
    ├── image1_results.json     # Numerical data for each detection
    ├── image2_results.json
    └── summary.json            # Summary of all results
```

### What You Get:

#### 1. Visual Outputs (`visualizations/`):
- **Colored overlay images**: Original image with detected masks colored
- Green = droplets, Red = ligaments
- Easy to see if detections are correct

#### 2. Mask Images (`masks/`):
- **Binary mask files**: One PNG file per detected object
- White pixels = object, Black = background
- Can be used for further analysis

#### 3. Numerical Data (`data/`):

Each `*_results.json` file contains:

```json
{
  "image_path": "path/to/image.png",
  "num_detections": 15,
  "detections": [
    {
      "class_name": "droplet",
      "score": 0.95,
      "area_pixels": 1250.5,
      "equivalent_diameter_pixels": 39.9,
      "ellipse": {
        "center": {"x": 450.2, "y": 320.1},
        "major_axis_pixels": 42.3,
        "minor_axis_pixels": 37.8,
        "angle_degrees": 15.2
      }
    },
    ...
  ]
}
```

**If you provide `--pixels-per-mm`**, you also get:
- `area_mm2`: Area in square millimeters
- `equivalent_diameter_mm`: Diameter in millimeters
- `ellipse.major_axis_mm`, `ellipse.minor_axis_mm`: Ellipse axes in mm

### Example Workflow:

1. **Train the model:**
   ```powershell
   python train_detectron2.py
   ```

2. **Test on a single image:**
   ```powershell
   python inference_detectron2.py --model output/model_final.pth --images test_image.png
   ```

3. **Check the visualization:**
   ```powershell
   start inference_results\visualizations\test_image_result.png
   ```

4. **Extract size data:**
   - Open `inference_results/data/test_image_results.json`
   - Use the `ellipse` data to calculate droplet sizes
   - If calibrated: use `equivalent_diameter_mm` directly

5. **Process many images:**
   ```powershell
   python inference_detectron2.py --model output/model_final.pth --images D:\Experiments\TestImages\ --pixels-per-mm 10.0
   ```

---

## Part 3: Adjusting Detection Sensitivity

If the model is:
- **Missing droplets**: Lower the threshold
  ```powershell
  python inference_detectron2.py --model output/model_final.pth --images image.png --threshold 0.3
  ```

- **Detecting too many false positives**: Raise the threshold
  ```powershell
  python inference_detectron2.py --model output/model_final.pth --images image.png --threshold 0.7
  ```

Default threshold is 0.5 (50% confidence).

---

## Quick Reference

| Task | Command |
|------|---------|
| Train model | `python train_detectron2.py` |
| Test single image | `python inference_detectron2.py --model output/model_final.pth --images image.png` |
| Test directory | `python inference_detectron2.py --model output/model_final.pth --images path/to/images/` |
| With calibration | `python inference_detectron2.py --model output/model_final.pth --images image.png --pixels-per-mm 10.0` |
| Lower threshold | `python inference_detectron2.py --model output/model_final.pth --images image.png --threshold 0.3` |

---

## Troubleshooting

**Training:**
- Loss not decreasing? → Model might need more training iterations
- Out of memory? → Reduce `BATCH_SIZE` in `train_detectron2.py`
- GPU not used? → Check CUDA installation

**Inference:**
- No detections? → Lower `--threshold`
- Too many false positives? → Raise `--threshold` or retrain with more data
- Wrong sizes? → Check `--pixels-per-mm` calibration value

