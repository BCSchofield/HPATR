<!-- Merge term 1 -->
# HPATR - High-Performance Aerosol Testing & Research

A comprehensive toolkit for droplet imaging analysis and experimental control.

## Overview

HPATR provides:
- **Image Processing Pipeline**: Canny edge detection + Watershed segmentation + Hough circle detection with size and position optimization
- **MP4 to TIFF Converter**: Convert Phantom camera videos to TIFF frames and find brightest frame
- **Experiment Control GUI**: Control Arduino (motor), pressure controller, and Phantom camera via a unified interface

## Repository Structure

```
HPATR/
├── src/
│   ├── imaging/
│   │   ├── save_and_analyse.py      # Main image processing pipeline
│   │   ├── expansion_detection.py   # Canny + Watershed + optimization core
│   │   └── mp4_to_tiff.py           # Video to TIFF converter
│   ├── gui/
│   │   ├── Windows_Experiment_GUI.py    # Main experiment control GUI
│   │   ├── Pressure_Motor_Portenta.cpp   # Arduino code for motor/pressure
│   │   └── camera_settings.json         # Camera configuration template
│   └── config_loader.py             # Configuration management
├── config/
│   └── paths_example.yaml           # Example configuration file
├── data/
│   ├── sample_input/                # Sample test images
│   └── sample_output/               # Output examples
└── docs/                            # Documentation

```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Paths

1. Copy the example config file:
   ```bash
   cp config/paths_example.yaml config/paths.yaml
   ```

2. Edit `config/paths.yaml` with your actual paths:
   - `imaging.output_root`: Where to save processed image outputs
   - `imaging.default_input_dir`: Default location for input images
   - `gui.experiment_log_dir`: Where to save experiment logs
   - `mp4_to_tiff.*`: Paths for video processing

### 3. Phantom SDK (Optional)

**Note**: The Phantom SDK (`pyphantom`) is typically installed via pip in your Python environment. If you have it installed, the GUI will automatically detect and use it. No manual path configuration is needed.

If you need to install the Phantom SDK:
- Check with Vision Research for the latest `pyphantom` package
- Install via pip: `pip install pyphantom` (if available)
- Or follow vendor installation instructions

The GUI will gracefully handle missing SDK - camera functionality will be limited but other features will work.

## Usage

### Image Processing Pipeline

Process a single image with full optimization:

```bash
# Using config default input
python src/imaging/save_and_analyse.py

# Or specify input file
python src/imaging/save_and_analyse.py /path/to/input.tiff
```

**Output Structure** (timestamped folders):
```
output_root/
└── Month_Year/
    └── Day_Month/
        └── Timestamp/
            ├── Input/
            │   └── input.tiff
            └── Outputs/
                ├── FINAL_OPTIMIZED_RESULT.png
                ├── FINAL_ANALYSIS.csv
                ├── CANNY_DETECTION.png
                ├── WATERSHED_DETECTION.png
                ├── POSITION_MOVEMENT.png
                └── debug_images/
                    └── ...
```

### MP4 to TIFF Converter

Convert Phantom camera video to TIFF frames and find brightest frame:

```bash
# Using config defaults
python src/imaging/mp4_to_tiff.py

# Or specify paths
python src/imaging/mp4_to_tiff.py input_video.mp4 output_folder
```

### Experiment Control GUI

Launch the GUI for controlling experiments:

```bash
python src/gui/Windows_Experiment_GUI.py
```

**Features**:
- Arduino motor control (via serial)
- Pressure controller control (via serial)
- Phantom camera control (via SDK)
- Real-time data logging
- Experiment notes and metadata

**Arduino Setup**:
1. Upload `src/gui/Pressure_Motor_Portenta.cpp` to your Arduino Portenta H7
2. Connect motor driver (TMC5160) and pressure controller
3. Select the correct COM port in the GUI

## Configuration

All paths are managed through `config/paths.yaml`. Key settings:

- **Imaging**: Input/output directories, default filenames
- **GUI**: Experiment log location, camera settings file, serial log
- **MP4 to TIFF**: Video input/output paths

The system will use `config/paths_example.yaml` as fallback if `paths.yaml` doesn't exist.

## Development

### Adding New Features

- Image processing: Add functions to `src/imaging/expansion_detection.py`
- GUI features: Extend `src/gui/Windows_Experiment_GUI.py`
- New tools: Add scripts to `src/imaging/` or `src/gui/`

### Code Style

- Use relative imports within `src/`
- Load paths via `config_loader.py` (don't hard-code paths)
- Keep timestamped folder structure for outputs

## Troubleshooting

### "Config file not found"
- Copy `config/paths_example.yaml` to `config/paths.yaml`
- Or the system will use hardcoded defaults

### "Phantom SDK not available"
- Install `pyphantom` via pip (if available)
- Or camera features will be disabled (other features still work)

### "Serial port not found"
- Check Arduino is connected and drivers installed
- Verify COM port in Device Manager (Windows) or `/dev/` (Linux/Mac)

### Import errors
- Make sure you're running scripts from the repo root
- Or add `src/` to your `PYTHONPATH`

## License

[Add your license here]

## Contact

[Add contact info if desired]

