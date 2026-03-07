# CLAUDE_Understanding.md
# Claude's Full Codebase Understanding of HPATR
_Generated: 2026-03-04_

---

## 1. What This System Does (Big Picture)

HPATR (High-Performance Aerosol Testing & Research) is a research system for studying liquid spray atomisation — specifically detecting and measuring **droplets** and **ligaments** in spray plumes using **shadowgraph imaging** (backlit silhouette photography). The system controls physical hardware, captures images, and analyses them.

There are two parallel image-analysis pipelines:
1. **Traditional CV pipeline** (Canny + Watershed) — currently used in production.
2. **AI/ML pipeline** (Detectron2 Mask R-CNN) — in development, intended to eventually replace the CV pipeline.

Additionally, there is a **cone angle detection** subsystem (Cone_3) for measuring the spray cone angle, which is not yet integrated with the main system.

---

## 2. Physical System

### Hardware
- **Phantom high-speed camera**: Records at up to 1000+ fps; controlled via `pyphantom` SDK. IP: `100.100.100.1`, typical config: 1000 fps, 500µs exposure, 640×480.
- **Arduino Portenta H7** with **TMC5160 stepper driver**: Controls a motor (lead screw drive) and reads/sets pressure via a PWM/ADC interface to an **AliCat** pressure controller. Steps per mm = 13,600 (200 steps/rev × 16 microsteps / 2mm lead × 4.25 gearbox).
- **Pressure system**: 0–26.4 BAR range, 20–68% PWM duty cycle mapped to pressure, 12-bit PWM at 1 kHz.
- **Optical switches**: Front and back limit switches on the motor rail for homing.
- **LaCie external drive**: Primary storage for all captured data (videos, images, experiment logs).
- **Tektronix AFG1062** (optional): Signal generator, controlled via PyVISA if installed.
- **Webcam** (not yet installed): Intended for cone angle detection via Cone_3.

### Data Flow (Experiment)
```
Experiment trigger (GUI)
  → Phantom records Cine/video → saved to LaCie/Phantom/Video
  → GUI runs pipeline:
      mp4_to_tiff.py → TIFF frames → LaCie/Phantom/TIFF_Output
      mp4_to_tiff.py → brightest frame → LaCie/Phantom/Flashed_Output
      save_and_analyse.py → Canny+Watershed analysis → LaCie/Shadowgraph/<timestamped>
```

---

## 3. Repository Structure

```
HPATR/
├── src/                            # Core production code
│   ├── config_loader.py            # Path resolution + LaCie detection
│   ├── gui/
│   │   ├── Windows_Experiment_GUI.py   # Main experiment control GUI
│   │   ├── Pressure_Motor_Portenta.cpp # Arduino firmware (Portenta H7)
│   │   └── camera_settings.json        # Phantom camera config
│   └── imaging/
│       ├── expansion_detection.py  # Core CV: Canny+Watershed+optimisation
│       ├── save_and_analyse.py     # Pipeline runner + output saving
│       └── mp4_to_tiff.py         # ⚠️ MISSING FROM REPO (referenced but not committed)
│
├── AI/                             # AI/ML development
│   ├── evaluate_model.py           # Single-model evaluation → Excel + CSV (CANONICAL)
│   ├── synthetic_data/
│   │   ├── blur_spray_dataset_generator.py       # Production dataset generator
│   │   ├── conjoined_blur_spray_dataset_generator.py  # Newer version (unstaged/testing)
│   │   └── spray_dataset_generator.py            # Older/earlier version
│   ├── Training_Analysis/
│   │   ├── train_detectron2.py     # Training script (also at repo root)
│   │   ├── inference_detectron2.py # Inference script (also at repo root)
│   │   ├── evaluate_model.py       # Similar to AI/evaluate_model.py (slightly different)
│   │   ├── plot_from_metrics.py    # Plot training metrics from JSON
│   │   ├── setup_training_dataset.py  # One-off dataset organiser
│   │   ├── check_image_identity.py    # Verify no data leakage between train/val
│   │   └── visualize_*.py         # Various result visualisers
│   ├── Validation_100/
│   │   └── blur_annotations.json  # Ground-truth for 100-image validation set
│   └── Testing_FUN/               # Hyperparameter sweep results and analysis
│       ├── Hyperparameter_Tests/  # Earlier sweep runs
│       │   └── LR_Anchor_Sweep_Final/    # Final LR × anchor size sweep (9 combos)
│       ├── Warmup_Decay_Final/    # Warmup + decay schedule sweep (9 combos)
│       └── analyze_three_runs_metrics.py
│
├── Trials/                         # Cone angle detection (experimental)
│   ├── Cone_2.py                  # Older approach with CSV params
│   ├── Cone_3.py                  # Current: PCA-based cone angle from TIFF
│   ├── cone_GUI.py                # Tkinter GUI to tune Cone_2/3 params + save CSV
│   ├── Cone_Tester.py             # Quick test script
│   └── *.jpeg                     # Trial images
│
├── config/
│   ├── paths.yaml                 # Active paths config (LaCie-aware)
│   ├── paths_example.yaml         # Template for paths.yaml
│   └── context/
│       └── Hyperparameter Context.txt  # Full sweep methodology notes
│
├── docs/
│   ├── CODE_SOP.md                # File guide and dependency map
│   ├── CLAUDE_Understanding.md    # This file
│   ├── LOOP_CLARIFICATION.md      # Explanation of nested loops in expansion_detection
│   ├── OPTIMIZATION_EXPLANATIONS.md  # NumPy mask + gradient descent docs
│   ├── gradient_descent_example.py   # Standalone GD demo
│   └── numpy_mask_example.py         # Standalone NumPy mask demo
│
├── README.md                      # Setup and usage guide
├── TRAINING_SETUP.md              # Detectron2 training walkthrough
├── INFERENCE_GUIDE.md             # Inference usage guide
├── requirements.txt               # Python deps (core; Detectron2 installed separately)
│
├── hyperparameter_sweep.py        # Main sweep runner (7000 iter, 2% val split)
├── extract_sweep_metrics.py       # Extract metrics from sweep JSON files
├── evaluate_multiple_models.py    # Batch evaluate models from models.txt → CSV
├── compare_training_metrics.py    # Compare metrics across runs
├── train_detectron2.py            # Root copy of training script (main one to use)
├── inference_detectron2.py        # Root copy of inference script
├── plot_from_metrics.py           # Root copy of plotting script
├── check_dataset_overlap.py       # Check for train/val image overlap
├── check_sweep_progress.py        # Monitor running sweep progress
├── convergence_test.py            # Test model convergence
├── visualize_dennis_vs_claudia.py # Visual comparison of two models
├── verify_installation.py         # Check Detectron2 + CUDA setup
├── activate_conda.ps1             # PowerShell script to activate "Detectron" conda env
└── serial_log.txt                 # Serial communication log from GUI
```

---

## 4. Key File Explanations

### 4.1 `src/config_loader.py`
Central path management. Uses `config/paths.yaml` (or `paths_example.yaml` as fallback). Resolves `{lacie_drive}` placeholder to the actual LaCie drive path (auto-detected per OS: `/Volumes/LaCie` on Mac, `D:\` or `E:\` etc. on Windows by checking for Phantom/Shadowgraph folders). Provides: `get_gui_config()`, `get_imaging_config()`, `get_mp4_config()`, `resolve_path()`, `find_lacie_drive()`.

### 4.2 `src/gui/Windows_Experiment_GUI.py`
Main CustomTkinter GUI (dark theme). Key components:
- **ArduinoController class**: Serial communication with Portenta, sends `SPEED:...;DIST:...` and `PRESSURE:...` / `PRESSURE_OFF` commands, receives `ARDUINO_READY`, `MOVEMENT_START`, progress % messages.
- **Camera section**: Uses `pyphantom` SDK for Phantom camera control; degrades gracefully without it.
- **AFG1062 section**: Optional PyVISA-based function generator control.
- **Pipeline**: When pipeline mode enabled: calls `find_brightest_frame` (from `mp4_to_tiff`) then `process_and_save_to_lacie` (from `save_and_analyse`).
- Reads camera settings from `src/gui/camera_settings.json`.
- Logs serial to `serial_log.txt`.

### 4.3 `src/gui/Pressure_Motor_Portenta.cpp`
Arduino firmware for Portenta H7. Uses TMC5160 stepper (SPI) + AccelStepper. Key:
- Steps per mm: `((200 × 16) / 2) × 4.25 = 13,600`
- Pressure: 12-bit PWM on pin 13, ADC reading on A0; maps 0–26.4 BAR to 20–68% duty cycle via LLC (logic level converter: 3.3V ↔ 5V).
- Homes on startup using front/back optical switches.
- Serial commands: `SPEED:N;DIST:M` for motor movement, `PRESSURE:X` to set target, `PRESSURE_OFF` to disable.
- Pressure smoothing: rolling average over 4 readings.
- **If motor doesn't work**: re-flash this firmware using Arduino IDE and long-press reset.

### 4.4 `src/imaging/expansion_detection.py`
Core CV pipeline. `process_image()` accepts an image path and returns a rich dict. Pipeline:
1. **Preprocessing**: Median blur (denoise), CLAHE (local contrast), gamma correction, Gaussian blur.
2. **Canny**: Edge detection → Hough circle detection → candidate circles.
3. **Watershed**: Threshold → morphological open → distance transform → markers (Hough seeds + connected components) → watershed segmentation → fit circles to labelled regions.
4. **Merging**: Combines Canny and Watershed circle candidates.
5. **Size optimisation**: For each circle, tests radii ±20% in steps using NumPy circle masks, maximises "black percentage" (droplets are dark on bright background).
6. **Position optimisation**: Gradient descent from initial position to maximise black percentage.
7. **Deduplication**: Removes overlapping circles.
8. Returns: `canny_circles`, `watershed_circles`, `all_circles_before_optimization`, `size_optimized_circles`, `optimized_circles`, `final_image`, `optimization_data`, `position_optimization_data`, `circle_sources`, `canny_edges`, `watershed_debug_images`, `preprocess_debug`, `preprocess_params`.

Key tunable parameters (with defaults in `process_image()` signature): `denoise_ksize=1`, `clahe_clip=8.0`, `clahe_tile=(18,18)`, `gamma=0.4`, `blur_ksize=1`, and Canny/Watershed/optimisation params.

### 4.5 `src/imaging/save_and_analyse.py`
Orchestrates the full pipeline. `process_and_save_to_lacie(input_source_path)`:
1. Creates timestamped folder structure: `{output_root}/Mon_YYYY/DD_Mon/Mon_DD_YYYY_HH_MM_SS/`
2. Copies input to `Input/` subfolder.
3. Creates `Outputs/` subfolder.
4. Calls `expansion_detection.process_image()`.
5. Saves: `FINAL_OPTIMIZED_RESULT.png`, `FINAL_ANALYSIS.csv`, `CANNY_EDGES.png`, `CANNY_DETECTION.png`, `WATERSHED_DETECTION.png`, `POSITION_MOVEMENT.png`, and in `debug_images/`: `PREPROCESSING_OVERVIEW.png`, `COMPLETE_PIPELINE_VISUALIZATION_*.png`, `WATERSHED_DEBUG_VISUALIZATION_*.png`.

### 4.6 `src/imaging/mp4_to_tiff.py`
**⚠️ This file is referenced throughout the codebase and README but does NOT exist in the repository.** It is expected at `src/imaging/mp4_to_tiff.py` and should provide `find_brightest_frame()` used by the GUI pipeline. This is a gap that needs addressing.

---

## 5. AI/ML Pipeline

### 5.1 Model Architecture
- **Detectron2 Mask R-CNN** with ResNet-50 FPN 3x backbone.
- **2 classes**: `droplet` (id=0), `ligament` (id=1).
- Annotations in **COCO format with RLE masks** (not polygons).
- Custom `RLEDatasetMapper` handles RLE → numpy → BitMask conversion.

### 5.2 Named Models
| Name | Notes |
|------|-------|
| **Dennis** / **Early_Dennis** | Current best. Uses anchors `[8,16,32,64]`. Needs more training with fringe data before use on real images. |
| **Benedict** | Previous model; used as resume checkpoint for Dennis training. |
| **Claudia** | Uses default COCO anchors; used for comparison. |

### 5.3 Training (`train_detectron2.py` at root — canonical copy)
- **Dataset**: `D:\Experiments\TrainingData\Detectron_Trial_4\` (14,000 images synthetic data).
- **Split**: 90% train / 10% val (fixed seed 42).
- **Batch size**: 2, **LR**: 0.0002, **Epochs**: 1 (dynamic MAX_ITER).
- **LR decay**: at 60% and 80% of MAX_ITER (gamma=0.1).
- **Checkpoints**: every 250 iterations to `D:\Experiments\AI\training_<timestamp>\`.
- **Resuming**: Set `RESUME_FROM_MODEL` to a `.pth` path (e.g. Benedict → Dennis).
- **ProgressTracker**: Saves `loss_curve.png` every 50 iterations, tracks train vs. val loss (generalization gap).
- Handles missing images gracefully (dummy black image + empty instances).
- Windows-specific: silently ignores `[Errno 22]` from Detectron2's event writer.

### 5.4 Synthetic Dataset Generator (`AI/synthetic_data/blur_spray_dataset_generator.py`)
Generates 1280×800 PNG images simulating **shadowgraph imaging** of sprays. Key characteristics:
- **Background**: Very bright (240–255 intensity) with low-frequency gradients and Gaussian noise.
- **Droplets**: Dark (20–80 intensity), absorption-style radial profiles with soft edges and bright rim. Log-normal size distribution (µ=2.5, σ=0.8 in log space), radius 2–50px.
- **Ligaments**: Dark, curvilinear, non-uniform thickness, can be broken.
- **Annotations**: COCO format with RLE masks.
- **Multiprocessing**: Uses all CPU cores by default.
- Currently configured for `Detectron_Trial_4` (1000 images, production mode).
- `conjoined_blur_spray_dataset_generator.py`: Newer unstaged version (10 images default, still in testing; differences TBD).

### 5.5 Hyperparameter Sweep (`hyperparameter_sweep.py`)
Systematic grid search over learning rate × anchor sizes:
- **Current config**: Fixed 7000 iterations per run, 2% val split (~400 images), validation every 500 iterations.
- **LRs tested**: [0.0005, 0.001, 0.0025, 0.005, 0.01]
- **Anchor configs tested**: `[8,16,32,64]`, `[8,16,32,64,128]`, `[16,32,64,128]`
- **Warmup/Decay sweep** also done: 0/500/1000 warmup steps × none/step/cosine decay.
- Results stored under `AI/Testing_FUN/Hyperparameter_Tests/LR_Anchor_Sweep_Final/` and `AI/Testing_FUN/Hyperparameter_Tests/Warmup_Decay_Final/`.
- **Best config found**: LR=0.0025, anchors=[8,16,32,64] (from the sweep results/Excel analysis in `Graphically_Challenged.xlsx`).
- Has resume capability (skips completed runs in `sweep_results.csv`).
- Uses non-interactive matplotlib backend (no popups; saves plots to file).
- Retry decorator on file I/O operations to handle LaCie drive disconnections.

### 5.6 Evaluation Scripts
Three evaluation scripts exist (see CODE_SOP TODO):

| Script | Role | Output |
|--------|------|--------|
| `AI/evaluate_model.py` | **Canonical single-model eval**. Default model: `Early_Dennis`. Score threshold: 0.1. | Excel (3 sheets) + appends to `evaluation_results.csv` + per-image JSON + visualisations |
| `AI/Training_Analysis/evaluate_model.py` | Near-identical to above. Has `SCORE_THRESHOLD = 0.1` constant but no CSV append. | Excel + per-image JSON + visualisations |
| `evaluate_multiple_models.py` (root) | Batch eval from `models.txt`. Uses Detectron2's COCOEvaluator (mAP). | `model_comparison_results.csv` |

**Recommendation from CODE_SOP**: `AI/evaluate_model.py` should be the canonical one. The `AI/Training_Analysis/` version is a copy. The root batch script serves a different purpose (multiple models, COCO mAP).

Metrics computed per-image: TP, FP, FN, Precision, Recall, F1, Avg IoU. IoU threshold for matching: 0.5. Category matching handles 0-indexed vs 1-indexed GT categories.

---

## 6. Cone Detection (`Trials/`)

**Status**: Experimental, not integrated with the main system. Webcam not yet installed.

| Script | Description |
|--------|-------------|
| `Cone_3.py` | **Current version**. PCA-based. Loads TIFF → grayscale → Gaussian blur → morphological close → finds largest contour → splits into left/right edges → PCA on each to find dominant direction → angle between them = cone angle. Imports `config_loader`. Has DEBUG_MODE overlay. |
| `Cone_2.py` | Older approach. Loads params from CSV (`params_1.csv`). Uses CLAHE, adaptive threshold, weighted processing, line fitting. |
| `cone_GUI.py` | Tkinter GUI for tuning Cone_2 parameters interactively with sliders. Can Save/Load params to CSV. Uses matplotlib TkAgg backend embedded in Tkinter. Has 6-panel layout: original, preprocessing steps, annotated result. |

CSV params format (for Cone_2/cone_GUI): two-column (name, value) with keys like `CLAHE_CLIP`, `BLUR_KSIZE`, `GAMMA`, `TOP_BAND_FRAC`, etc.

---

## 7. Configuration System

### `config/paths.yaml`
All paths use `{lacie_drive}` placeholder. Key settings:
- `imaging.output_root`: `{lacie_drive}/Shadowgraph`
- `imaging.default_input_dir`: `{lacie_drive}/Phantom/Flashed_Output`
- `mp4_to_tiff.default_video_path`: `{lacie_drive}/Phantom/Video/Shadowgraph_Video.mp4`
- `mp4_to_tiff.default_tiff_folder`: `{lacie_drive}/Phantom/TIFF_Output`
- `mp4_to_tiff.default_flashed_output`: `{lacie_drive}/Phantom/Flashed_Output`
- `gui.experiment_log_dir`: `{lacie_drive}/Experiments/Logs`
- `gui.serial_log_file`: `serial_log.txt` (relative)
- `gui.camera_settings_file`: `src/gui/camera_settings.json`

### `src/gui/camera_settings.json`
```json
{"ip": "100.100.100.1", "fps": "1000", "exposure_us": "500", "width": "640", "height": "480", "seconds": "0.020", "output": "E:\\Phantom\\Video"}
```

---

## 8. Dependencies

### Core Python Packages (`requirements.txt`)
- `opencv-python>=4.5.0`
- `numpy>=1.20.0,<2.0` (NumPy 2.x breaks `pyphantom`)
- `matplotlib`, `pandas`, `customtkinter`, `Pillow`, `openpyxl`
- `pyserial>=3.5`
- `PyYAML>=5.4.0`
- `pycocotools>=2.0.0`

### Optional/Separate
- `pyphantom` (Phantom SDK) — Windows only for camera control
- `pyvisa` — for AFG1062 function generator
- `detectron2` + `torch` (CUDA) — AI training/inference; install separately
- `win32api` — optional in config_loader for Windows volume label detection
- Conda environment: **"Detectron"** (Windows, contains Detectron2 + CUDA)

---

## 9. Known Gaps and TODOs

| Issue | Details |
|-------|---------|
| **`mp4_to_tiff.py` missing** | Referenced in README, CODE_SOP, GUI, and `save_and_analyse.py` but not in the repo. Needs to be located and committed. |
| **Canonical evaluate script** | `AI/evaluate_model.py` is most complete; `AI/Training_Analysis/evaluate_model.py` is a near-duplicate. Should decide which is canonical and deprecate the other. |
| **Dennis needs more training** | Current best model; needs training with fringe/boundary data before deployment on real images. |
| **Cone detection not integrated** | Cone_3 works standalone but webcam isn't installed yet and it's not connected to GUI or AI pipeline. |
| **AI pipeline not yet in GUI** | GUI currently uses only the CV pipeline (`save_and_analyse`). AI inference isn't wired into the GUI yet. |
| **Output paths not fully documented** | CODE_SOP has a TODO to document all output paths in one place. |
| **`conjoined_blur_spray_dataset_generator.py`** | Unstaged new file. Purpose vs. `blur_spray_dataset_generator.py` unclear — presumably adds "conjoined" droplet/ligament pairs. |
| **Pressure controller in GUI** | TODO in GUI code: adding pressure controller control box. |
| **Hard-coded Windows paths** | Several scripts have `D:\Experiments\...` hardcoded (e.g. `evaluate_multiple_models.py`, `setup_training_dataset.py`). These need the LaCie path resolution treatment. |

---

## 10. Optimization Techniques in CV Pipeline

The docs folder explains two key optimizations used in `expansion_detection.py`:

**NumPy Circle Masks** (replaces pixel-sampling loops):
- Instead of iterating every pixel inside a circle with Python, creates a boolean mask using `np.ogrid` and distance calculation, then does vectorized black-pixel counting.
- Speedup: 50–200×.

**Gradient Descent Position Optimization** (replaces grid search):
- Instead of testing ~6,400 positions in a grid, follows the gradient of "black percentage" as a function of (x,y) to converge to the optimal circle centre.
- Speedup: ~100–300× fewer evaluations (~20–50 steps vs 6,400).
- Combined speedup over naive approach: 100–1000×.

---

## 11. Typical Workflows

### Running an Experiment
1. Launch `python src/gui/Windows_Experiment_GUI.py`
2. Select COM port, connect to Portenta.
3. Set motor speed/distance, pressure target.
4. Enable pipeline mode, set camera params.
5. Click Run — GUI records, converts to TIFF, runs CV analysis, saves to LaCie.

### Generating Training Data
1. Edit `NUM_IMAGES` and `CUSTOM_OUTPUT_FOLDER` in `blur_spray_dataset_generator.py`.
2. Run `python AI/synthetic_data/blur_spray_dataset_generator.py`.
3. Output: `D:\Experiments\TrainingData\<folder>\images\` + `blur_annotations.json`.

### Training a Model
1. Set `ANNOTATIONS_PATH`, `IMAGES_PATH`, `RESUME_FROM_MODEL` in `train_detectron2.py`.
2. Activate "Detectron" conda env.
3. Run `python train_detectron2.py`.
4. Model saved to `D:\Experiments\AI\training_<timestamp>\model_final.pth`.

### Running a Hyperparameter Sweep
1. Configure `hyperparameter_sweep.py` (LR list, anchor configs, iterations).
2. Run `python hyperparameter_sweep.py`.
3. Results in `D:\Experiments\AI\Hyperparameters\sweep_<timestamp>\`.
4. Analyse with `extract_sweep_metrics.py` and Excel.

### Evaluating a Model
```bash
python AI/evaluate_model.py --model "D:\Experiments\AI\<training_folder>\model_final.pth" --model-name "MyModel"
```
Outputs Excel to current directory and appends to `evaluation_results.csv` on LaCie.

### Running Inference
```bash
python inference_detectron2.py --model output/model_final.pth --images path/to/images/ --pixels-per-mm 10.0
```

---

## 12. File Duplication Map

Several scripts exist at both the repo root and in `AI/Training_Analysis/`. The root versions appear to be the more actively maintained copies:

| Root | AI/Training_Analysis/ | Notes |
|------|-----------------------|-------|
| `train_detectron2.py` | `AI/Training_Analysis/train_detectron2.py` | Root is canonical (has Benedict resume config) |
| `inference_detectron2.py` | `AI/Training_Analysis/inference_detectron2.py` | Root is canonical |
| `plot_from_metrics.py` | `AI/Training_Analysis/plot_from_metrics.py` | Likely same |
| `check_image_identity.py` | `AI/Training_Analysis/check_image_identity.py` | Likely same |
| `setup_training_dataset.py` | `AI/Training_Analysis/setup_training_dataset.py` | Likely same |
| `test_inference_debug.py` | `AI/Training_Analysis/test_inference_debug.py` | Likely same |
| `verify_installation.py` | `AI/Training_Analysis/verify_installation.py` | Likely same |
| `visualize_coco_results.py` | `AI/Training_Analysis/visualize_coco_results.py` | Likely same |
| `visualize_model_predictions.py` | `AI/Training_Analysis/visualize_model_predictions.py` | Likely same |

---

_This document was generated by Claude (claude-sonnet-4-6) by reading all Python, C++, YAML, JSON, Markdown, and text files in the repository._
