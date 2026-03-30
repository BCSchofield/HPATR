<!-- Merge term 1 -->
# Code SOP – Files You Use Consistently

This document lists the main files and their dependencies, with paths and descriptions in the context of the HPATR system. File paths will need to be updated when you inevidably change things around, or mode into git/MAIN.

---

## TODO (top priority)

- **Add paths for outputs**  
  Document in one place all output paths (LaCie vs local, per script): e.g.  
  - High-speed camera: `{LaCie}/Phantom/Video`, TIFF sequence → `Phantom/TIFF_Output`, brightest frame → `Phantom/Flashed_Output`  
  - Experiment logs: `{LaCie}/Experiments/Logs`, serial log path from GUI config  
  - Shadowgraph pipeline: `config` → `imaging.output_root` (e.g. `{LaCie}/Shadowgraph`)  
  - Training/inference outputs: model checkpoints, prediction outputs (to be filled)  
  - Evaluation: CSV/Excel paths (see evaluate-model TODO below)

- **Work out which evaluate-model script is the correct one**  
  There are three evaluation scripts; clarify roles and when to use which:
  - **`evaluate_multiple_models.py`** (repo root) – batch evaluation from a `models.txt` list; uses Validation_100 dataset; hardcoded paths (e.g. `D:\Experiments\Validation_100`); outputs `model_comparison_results.csv`.
  - **`AI/evaluate_model.py`** – single-model evaluation; COCO-style annotations; exports to Excel; has `evaluation_results.csv` and configurable paths via CLI.
  - **`AI/Training_Analysis/evaluate_model.py`** – same purpose as `AI/evaluate_model.py` (nearly identical); no CSV constant in the snippet; likely the Training_Analysis copy.  
  **Action:** Pick one as canonical (e.g. `AI/evaluate_model.py` or `AI/Training_Analysis/evaluate_model.py`), document it here, and deprecate or redirect the other(s).

---

## 1. Main GUI and subsystems

### 1.1 Front End

| Path | Description |
|------|-------------|
| **`src/gui/Windows_Experiment_GUI.py`** | Main GUI for the whole system. CustomTkinter UI: experiment control, Arduino/Portenta connection (motor + pressure), Phantom high-speed camera control, pipeline (record → TIFF → brightest frame → save_and_analyse). Uses `config_loader` for paths and LaCie drive; calls `imaging.mp4_to_tiff` and `imaging.save_and_analyse` ONLY when pipeline is enabled. |

### 1.2 Configuration and path resolution

| Path | Description | Used by |
|------|-------------|--------|
| **`src/config_loader.py`** | Loads paths from `config/paths.yaml` (or `paths_example.yaml`). Provides `get_gui_config()`, `get_imaging_config()`, `get_mp4_config()`, `resolve_path()`, `find_lacie_drive()`. OS-aware and LaCie-aware. | GUI, imaging scripts, Cone_3 |
| **`config/paths.yaml`** | User paths (imaging, gui, mp4_to_tiff). Use `paths_example.yaml` as template. | config_loader |
| **`config/paths_example.yaml`** | Example config; copy to `paths.yaml` and edit. | reference only |
| **`src/gui/camera_settings.json`** | Phantom camera settings (IP, fps, exposure, size, output path). GUI reads/writes this; default output e.g. `E:\Phantom\Video`. | Windows_Experiment_GUI |

### 1.3 Motor and pressure (Arduino/Portenta)

| Path | Description | Used by |
|------|-------------|--------|
| **`src/gui/Pressure_Motor_Portenta.cpp`** | Firmware for Portenta: TMC5160 stepper (motor), optical switches, pressure PWM/ADC. Parses serial commands `SPEED:...;DIST:...`, `PRESSURE:...`, `PRESSURE_OFF`. Sends `ARDUINO_READY`, `MOVEMENT_START`, movement completion. If motor isn't working, try re-flashing this code (using Arduino IDE) and resetting the portenta with a long press on the main button. | Flashed to Portenta; GUI talks to it over serial |

Motor and pressure logic in the app live **inside** `Windows_Experiment_GUI.py` (e.g. `ArduinoController` class, `run_experiment()`, serial listener). No separate Python motor module required, but this could be added later down the line to clean up the main GUI script.

### 1.4 High-speed camera and where video goes

- **Recording (Phantom):**  
  GUI uses `pyphantom` (Phantom SDK) when available. Save destination comes from GUI “camera output” (from `camera_settings.json` or default). Default base path: **`{LaCie}/Phantom/Video`** (or `./camera_settings/captures` if no LaCie).
- **Pipeline mode (record → process):**  
  - Cine/TIFF sequence can be saved to **`Phantom/TIFF_Output`** (from `get_mp4_config()['default_tiff_folder']` or LaCie fallback).  
  - Brightest-frame output goes to **`Phantom/Flashed_Output`** (from `get_mp4_config()['default_flashed_output']`).

### 1.5 Imaging pipeline (MP4 → TIFF → analysis)

| Path | Description | Used by |
|------|-------------|--------|
| **`src/imaging/mp4_to_tiff.py`** | Converts MP4 to TIFF frames; finds brightest frame and can save it. Uses `get_mp4_config()` for default video path, TIFF folder, and flashed output folder. | GUI pipeline (find_brightest_frame); also runnable as standalone script |
| **`src/imaging/save_and_analyse.py`** | Full pipeline: copy input to LaCie, run Canny+Watershed processing via `expansion_detection.process_image`, write outputs (e.g. `FINAL_ANALYSIS.csv`) under a timestamped folder. Uses `get_imaging_config()` for `output_root` (e.g. `{LaCie}/Shadowgraph`). | GUI pipeline (`process_and_save_to_lacie`) |
| **`src/imaging/expansion_detection.py`** | Core image processing: Canny, Watershed, droplet detection, optimization. Exposes `process_image()` and visualization helpers. | save_and_analyse |

Run from GUI: when pipeline is enabled, after recording the GUI calls `find_brightest_frame` then `process_and_save_to_lacie` (which uses `expansion_detection` under the hood). **Eventually, this will be replaced with the AI model**

---

## 2. Blur dataset generation

| Path | Description | Dependencies |
|------|-------------|--------------|
| **`AI/synthetic_data/blur_spray_dataset_generator.py`** | Generates synthetic blur/spray datasets (images + COCO-style annotations) for training. No project-internal imports; uses opencv, numpy, pycocotools, matplotlib, etc. | None, standalone.|

---

## 3. Detectron2 training and inference

| Path | Description | Dependencies |
|------|-------------|--------------|
| **`AI/Training_Analysis/train_detectron2.py`** | Trains Detectron2 models (e.g. Mask R-CNN) on COCO-format data. Registers datasets, builds config, runs DefaultTrainer, evaluation. | detectron2, torch, pycocotools; no local project imports |
| **`AI/Training_Analysis/inference_detectron2.py`** | Runs a trained Detectron2 model on images; visualization and output. | detectron2, torch; no local project imports |

Typical flow: data from `blur_spray_dataset_generator.py` (or similar) → train with `train_detectron2.py` → run inference with `inference_detectron2.py`. **Current best model is Dennis, but needs further training with fringe data before real images.**

---

## 4. Cone detection and params CSV

| Path | Description | Dependencies |
|------|-------------|--------------|
| **`Trials/Cone_3.py`** | Cone angle detection from a single TIFF: contour + PCA on left/right edges. **Currently not fully implemented, as webcam needs to be installed first**. Uses `config_loader.get_imaging_config()` (adds `src` to path). | `src/config_loader` (get_imaging_config) |
| **Params CSV** | Cone processing parameters (e.g. CLAHE, blur, gamma, weights, morphology, line-fit limits). **`Trials/Cone_2.py`** loads from CSV via `load_params_from_csv()` and applies to constants (e.g. default `params_1.csv` in same dir). **`Trials/cone_GUI.py`** has sliders and Save/Load Params (CSV). Cone_3 does not yet load a params CSV; same CSV format/knowledge can be used when you add it. | Cone_2, cone_GUI; intended for Cone_3 later |

Params CSV format: two columns (e.g. parameter name, value); keys align to constants in Cone_2 (e.g. `CLAHE_CLIP`, `BLUR_KSIZE`, `GAMMA`, `TOP_BAND_FRAC`, …).

---

## 5. Evaluate-model scripts (see TODO above)

| Path | Role (to be confirmed) |
|------|-------------------------|
| **`evaluate_multiple_models.py`** (root) | Batch evaluation from `models.txt`; Validation_100; outputs CSV. |
| **`AI/evaluate_model.py`** | Single-model evaluation; COCO annotations; Excel + optional CSV. |
| **`AI/Training_Analysis/evaluate_model.py`** | Same idea as `AI/evaluate_model.py`; clarify which is canonical. |

---

## 6. Quick dependency overview

```
Windows_Experiment_GUI.py
├── config_loader (paths, LaCie, gui/imaging/mp4 configs)
├── camera_settings.json
├── imaging.mp4_to_tiff (find_brightest_frame)
├── imaging.save_and_analyse (process_and_save_to_lacie)
│   └── imaging.expansion_detection (process_image)
└── Pressure_Motor_Portenta.cpp (firmware; serial)

config_loader
└── config/paths.yaml (or paths_example.yaml)

Cone_3.py
└── config_loader (get_imaging_config)

blur_spray_dataset_generator.py  — standalone
train_detectron2.py              — standalone (detectron2/torch)
inference_detectron2.py          — standalone (detectron2/torch)
```

---

## 7. Output paths (summary – to be completed in TODO)

| Purpose | Typical path / source |
|--------|------------------------|
| Phantom video (raw) | `camera_settings.json` "output" or default `{LaCie}/Phantom/Video` |
| TIFF sequence (pipeline) | `get_mp4_config()['default_tiff_folder']` → e.g. `{LaCie}/Phantom/TIFF_Output` |
| Flashed (brightest frame) | `get_mp4_config()['default_flashed_output']` → e.g. `{LaCie}/Phantom/Flashed_Output` |
| Shadowgraph pipeline outputs | `get_imaging_config()['output_root']` → e.g. `{LaCie}/Shadowgraph` (timestamped subfolders) |
| Experiment logs | `get_gui_config()['experiment_log_dir']` → e.g. `{LaCie}/Experiments/Logs` |
| Serial log | `get_gui_config()['serial_log_file']` |
| Evaluation results | See TODO: decide canonical evaluate script and document its output paths |

All of the above use `resolve_path()` and `find_lacie_drive()` when `{lacie_drive}` is in the config.
