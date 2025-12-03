# HPATR Testing Checklist

## Pre-Testing Setup

### 1. Install Dependencies
```bash
cd /Users/benschofield/Documents/GitHub/HPATR
pip install -r requirements.txt
```

### 2. Create Config File
```bash
cp config/paths_example.yaml config/paths.yaml
# Edit config/paths.yaml with your actual paths
```

**Important**: Update paths in `config/paths.yaml`:
- Mac: `/Volumes/LaCie/...` 
- Windows: `D:\LaCie\...` or `C:\Users\...\...` (use forward slashes `/` or double backslashes `\\`)

## Testing Steps

### ✅ Test 1: Config System
**Platform**: Mac ✅ | Windows ✅

```bash
cd /Users/benschofield/Documents/GitHub/HPATR
python -c "from src.config_loader import get_config; print(get_config())"
```

**Expected**: Should print your config dictionary without errors.

**If it fails**: Check that `config/paths.yaml` exists or `config/paths_example.yaml` is present.

---

### ✅ Test 2: Image Processing Pipeline (No Hardware Needed)
**Platform**: Mac ✅ | Windows ✅

**Prerequisites**: 
- A test image file (TIFF or JPG)
- Output directory must exist or be writable

```bash
# Test with a sample image
python src/imaging/save_and_analyse.py /path/to/your/test_image.tiff

# Or use config default (if set)
python src/imaging/save_and_analyse.py
```

**Expected**:
- Creates timestamped folder structure
- Processes image (Canny + Watershed + optimization)
- Saves outputs to `Outputs/` folder
- No import errors

**What to check**:
- ✓ Folder structure created: `output_root/Month_Year/Day_Month/Timestamp/`
- ✓ `Input/input.tiff` exists
- ✓ `Outputs/FINAL_OPTIMIZED_RESULT.png` exists
- ✓ `Outputs/FINAL_ANALYSIS.csv` exists
- ✓ `Outputs/debug_images/` folder with visualizations

**Common issues**:
- **Import error**: Make sure you're running from repo root, or add `src/` to PYTHONPATH
- **Path error**: Check `config/paths.yaml` - use forward slashes on Windows too
- **Permission error**: Check output directory is writable

---

### ✅ Test 3: MP4 to TIFF Converter (No Hardware Needed)
**Platform**: Mac ✅ | Windows ✅

**Prerequisites**: An MP4 video file

```bash
# Test with a video file
python src/imaging/mp4_to_tiff.py /path/to/video.mp4 /path/to/output_folder

# Or use config defaults
python src/imaging/mp4_to_tiff.py
```

**Expected**:
- Converts MP4 to TIFF frames
- Finds brightest frame
- Saves to output folder

**What to check**:
- ✓ TIFF frames created in output folder
- ✓ `flashed_output.tiff` created in flashed output folder

---

### ✅ Test 4: Expansion Detection (Direct Execution)
**Platform**: Mac ✅ | Windows ✅

```bash
# Test expansion_detection directly
python src/imaging/expansion_detection.py /path/to/test_image.tiff
```

**Expected**: 
- Processes image and shows visualizations
- Saves to `data/sample_output/` (local testing)

---

### ⚠️ Test 5: GUI - Serial Communication (Hardware Dependent)
**Platform**: Mac ⚠️ | Windows ⚠️

**Mac vs Windows Differences**:
- **Mac**: Serial ports are `/dev/tty.usbserial-*` or `/dev/cu.usbserial-*`
- **Windows**: Serial ports are `COM1`, `COM2`, etc.

**The GUI should auto-detect ports**, but you can check:

```python
# Quick test script
from serial.tools import list_ports
ports = list_ports.comports()
for port in ports:
    print(f"{port.device} - {port.description}")
```

**To test GUI**:
```bash
python src/gui/Windows_Experiment_GUI.py
```

**What to check**:
- ✓ GUI launches without errors
- ✓ Serial port dropdown shows available ports
- ✓ Can connect to Arduino (if connected)
- ✓ Camera settings load/save (even without Phantom SDK)

**Common issues**:
- **"No module named 'customtkinter'"**: `pip install customtkinter`
- **Serial port not found**: Check Arduino drivers installed, port not in use
- **Phantom SDK warning**: Expected if SDK not installed - other features still work

---

### ❌ Test 6: Phantom SDK (Skip if not installed)
**Platform**: Mac ❌ | Windows ❌

**Note**: Skip this if you don't have Phantom SDK installed. The GUI will work without it.

If you have it installed:
- GUI should detect `pyphantom` automatically
- Camera tab should be functional
- No manual path configuration needed

---

## Platform-Specific Notes

### Mac
- ✅ Paths: Use `/Volumes/LaCie/...` format
- ✅ Serial: `/dev/tty.usbserial-*` or `/dev/cu.usbserial-*`
- ✅ File paths: Forward slashes work everywhere

### Windows
- ⚠️ Paths: Can use `D:\LaCie\...` or `D:/LaCie/...` (both work in Python)
- ⚠️ Serial: `COM1`, `COM2`, etc.
- ⚠️ File paths: Forward slashes `/` work in Python, but Windows Explorer uses `\`

**Recommendation**: Use forward slashes `/` in `config/paths.yaml` - Python handles it on both platforms.

---

## Quick Smoke Test (All Platforms)

Run this to verify basic functionality:

```bash
cd /Users/benschofield/Documents/GitHub/HPATR

# 1. Test imports
python -c "from src.config_loader import get_config; print('Config OK')"
python -c "from src.imaging.expansion_detection import process_image; print('Imaging OK')"
python -c "from src.imaging.mp4_to_tiff import video_to_tiff_frames; print('MP4 converter OK')"

# 2. Test GUI imports (may show Phantom SDK warning - that's OK)
python -c "import sys; sys.path.insert(0, 'src'); from gui.Windows_Experiment_GUI import *; print('GUI imports OK')"
```

All should print "OK" without errors (Phantom SDK warning is fine).

---

## Troubleshooting

### Import Errors
**Problem**: `ModuleNotFoundError: No module named 'src'` or similar

**Solution**: 
- Make sure you're running from repo root: `cd /Users/benschofield/Documents/GitHub/HPATR`
- Or add to PYTHONPATH: `export PYTHONPATH="${PYTHONPATH}:/Users/benschofield/Documents/GitHub/HPATR/src"`

### Path Errors on Windows
**Problem**: Paths not working

**Solution**: 
- Use forward slashes in `config/paths.yaml`: `D:/LaCie/...` 
- Or use raw strings: `r"D:\LaCie\..."`
- Python's `os.path.join()` handles both

### Serial Port Issues
**Problem**: Can't find Arduino port

**Solution**:
- **Mac**: Check `/dev/tty.*` or `/dev/cu.*` in terminal: `ls /dev/tty.*`
- **Windows**: Check Device Manager → Ports (COM & LPT)
- Make sure Arduino drivers installed
- Close other programs using the port (Arduino IDE, etc.)

---

## Success Criteria

✅ All tests pass = Ready to use!

If any test fails, check the error message and refer to troubleshooting section above.

