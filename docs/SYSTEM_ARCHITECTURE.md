# HPATR — System Architecture Reference

**Last updated:** 2026-03-18
**Status:** Authoritative reference. Update this file when significant changes are made.

---

## Contents

1. [Repository Structure & File Inventory](#1-repository-structure--file-inventory)
2. [GUI — GUI_Clean.py](#2-gui--gui_cleanpy)
3. [Arduino Firmware — Pressure_Motor_Portenta.cpp](#3-arduino-firmware--pressure_motor_portentacpp)
4. [Serial Communications Protocol](#4-serial-communications-protocol)
5. [Data Flow — Complete Experiment Run](#5-data-flow--complete-experiment-run)
6. [Imaging Pipeline (CV)](#6-imaging-pipeline-cv)
7. [AI/ML Pipeline — Detectron2](#7-aiml-pipeline--detectron2)
8. [Cone Detection](#8-cone-detection)
9. [Configuration System](#9-configuration-system)
10. [Output Paths Summary](#10-output-paths-summary)
11. [Hardware Summary](#11-hardware-summary)
12. [Known Bugs & TODOs](#12-known-bugs--todos)
13. [Dependencies & Environments](#13-dependencies--environments)

---

## 1. Repository Structure & File Inventory

### 1.1 Top-Level Layout

```
HPATR/
├── src/                    Core production code
├── AI/                     AI/ML pipeline development
├── Trials/                 Experimental (cone detection)
├── config/                 YAML config + paths
├── data/                   Sample reference data
├── docs/                   Documentation
├── tests/                  Test utilities
├── experiment_logs/        Generated experiment logs
├── train_detectron2.py     CANONICAL training script (root)
├── inference_detectron2.py CANONICAL inference script (root)
├── hyperparameter_sweep.py Grid search runner
├── extract_sweep_metrics.py Analyze sweep results
├── evaluate_multiple_models.py Batch mAP evaluation
├── compare_training_metrics.py Compare training runs
├── plot_from_metrics.py    Visualise metrics JSON
├── check_dataset_overlap.py Detect train/val leakage
├── convergence_test.py     Test model convergence
├── visualize_dennis_vs_claudia.py Compare two models visually
├── verify_installation.py  Check Detectron2 + CUDA
├── activate_conda.ps1      Windows PowerShell conda helper
├── requirements.txt        Core Python dependencies
├── README.md               Setup and usage overview
├── TRAINING_SETUP.md       Detectron2 training walkthrough
└── INFERENCE_GUIDE.md      Inference usage guide
```

### 1.2 `src/`

```
src/
├── config_loader.py              Central path resolution (LaCie-aware, OS-aware)
├── gui/
│   ├── GUI_Clean.py              PRIMARY GUI (PySide6, dark theme) — ~2,650 lines
│   ├── Windows_Experiment_GUI.py ⚠ LEGACY GUI (CustomTkinter) — superseded, keep for reference
│   ├── Pressure_Motor_Portenta.cpp Arduino firmware (TMC5160 + AliCat pressure)
│   └── camera_settings.json      Phantom + cone camera persistent settings
└── imaging/
    ├── expansion_detection.py    Core CV: Canny + Watershed + gradient-descent optimisation
    ├── save_and_analyse.py       Pipeline orchestrator — wraps expansion_detection, saves to LaCie
    └── mp4_to_tiff.py            MP4 → TIFF frame extractor (present; was once missing from repo)
```

### 1.3 `AI/`

```
AI/
├── evaluate_model.py             CANONICAL evaluation script ← use this one
├── synthetic_data/
│   ├── blur_spray_dataset_generator.py       Current synthetic data generator
│   ├── conjoined_blur_spray_dataset_generator.py  NEW (unstaged) — purpose vs old TBD
│   └── spray_dataset_generator.py            ⚠ LEGACY — superseded
├── Training_Analysis/
│   ├── train_detectron2.py       ⚠ DUPLICATE of root — root is canonical
│   ├── inference_detectron2.py   ⚠ DUPLICATE
│   ├── evaluate_model.py         ⚠ NEAR-DUPLICATE of AI/evaluate_model.py — deprecate
│   ├── plot_from_metrics.py      ⚠ DUPLICATE
│   ├── check_image_identity.py   ⚠ DUPLICATE
│   └── visualize_*.py            ⚠ DUPLICATES
├── Validation_100/
│   └── blur_annotations.json     100-image validation ground truth (COCO format)
└── Testing_FUN/
    ├── Hyperparameter_Tests/
    │   ├── LR_Anchor_Sweep_Final/    9 LR × anchor configs → Dennis found here
    │   └── Warmup_Decay_Final/       9 warmup × decay configs
    └── analyze_three_runs_metrics.py
```

**⚠ File duplication note:** All scripts under `AI/Training_Analysis/` are copies of root-level scripts. Root versions are canonical. `Training_Analysis/` copies should be considered deprecated.

### 1.4 `Trials/` (Cone Detection)

```
Trials/
├── Cone_3.py          Current algorithm (PCA-based) — integrate this one
├── Cone_2.py          ⚠ OLDER algorithm (CLAHE-based) — superseded
├── cone_GUI.py        Tkinter parameter tuner for Cone_2 — reference only
├── Cone_Tester.py     Quick test runner — reference only
└── params_*.csv       Parameter configs for Cone_2 — no longer needed
```

### 1.5 `config/`

```
config/
├── paths.yaml              USER config — fill in {lacie_drive}
├── paths_example.yaml      Template
└── context/
    └── Hyperparameter Context.txt   Methodology notes on sweep design
```

**`paths.yaml` key sections:**
```yaml
imaging:
  output_root: {lacie_drive}/Shadowgraph
  default_input_dir: {lacie_drive}/Phantom/Flashed_Output
gui:
  experiment_log_dir: {lacie_drive}/Experiments/Logs
  serial_log_file: serial_log.txt
  camera_settings_file: src/gui/camera_settings.json
mp4_to_tiff:
  default_video_path: {lacie_drive}/Phantom/Video/Shadowgraph_Video.mp4
  default_tiff_folder: {lacie_drive}/Phantom/TIFF_Output
  default_flashed_output: {lacie_drive}/Phantom/Flashed_Output
```

### 1.6 `docs/`

| File | Purpose |
|------|---------|
| `SYSTEM_ARCHITECTURE.md` | **This file** — full system reference |
| `CLAUDE_Understanding.md` | High-level system overview (Claude-generated) |
| `AI_PIPELINE_PLAN.md` | AI post-processing design (post-Phantom hardware testing) |
| `CODE_SOP.md` | File guide + dependency map + TODOs |

---

## 2. GUI — GUI_Clean.py

**File:** `src/gui/GUI_Clean.py`
**Framework:** PySide6 (Qt6), Fusion style, dark Apple-inspired theme
**Main class:** `AtomisationApp(QMainWindow)`
**~2,650 lines**

### 2.1 Window Layout

```
┌──────────────────────────────────────────────────────────┐
│  HEADER BAR (52px)                                        │
│  "ATOMISATION CONTROL"  ● Arduino  ● Pressure  ● Camera  │
│  Pixels/mm: 42.3                                          │
├────────────────┬────────────────────────┬────────────────┤
│  LEFT PANEL    │  CENTRAL TABS          │  RIGHT PANEL   │
│  (440px fixed) │                        │  (260px fixed) │
│                │  Hardware | Camera |   │  Nozzle card   │
│  Shadowgraph   │  AFG1062 | Cal | Cone  │  Notes card    │
│  preview card  │  How To (hidden)       │  Save to Excel │
│  (370×250 px)  │                        │                │
│                │  (scrollable content)  │                │
│  Pressure live │                        │                │
│  graph (180px) │                        │                │
│                │                        │                │
│  Motor travel  │                        │                │
│  bar card      │                        │                │
│                │                        │                │
│  Emergency     │                        │                │
│  Pressure Off  │                        │                │
├────────────────┴────────────────────────┴────────────────┤
│  STATUS BAR — status text                [START EXPERIMENT]│
└──────────────────────────────────────────────────────────┘
```

### 2.2 Design Tokens

```python
CLR_BG       = "#111111"   # Window background
CLR_PANEL    = "#1c1c1e"   # Card surface
CLR_INPUT    = "#2c2c2e"   # Input fields
CLR_BORDER   = "#3a3a3c"   # Borders
CLR_TEXT     = "#f2f2f7"   # Primary text
CLR_TEXT_SEC = "#8e8e93"   # Secondary text
CLR_ACCENT   = "#0a84ff"   # Apple blue (interactive)
CLR_GREEN    = "#30d158"   # Connected
CLR_ORANGE   = "#ff9f0a"   # Warning / homing
CLR_RED      = "#ff453a"   # Error / off
CLR_PURPLE   = "#bf5af2"   # Clean button
```

**Helper functions:** `card()`, `section_label()`, `title_label()`, `accent_button()`, `ghost_button()`, `input_row()`, `dot_indicator()`, `separator()`

**Custom widgets:** `ClickableImageWidget(QLabel)` — 2-point click handler for calibration

### 2.3 Core State Variables

```python
# Hardware connections
self.arduino: ArduinoController | None
self.arduino_connected: bool = False
self.serial_reading_active: bool = False
self.serial_reader_thread: QThread | None

self.phantom: PhantomController        # if pyphantom available
self.afg: AFGController                # if PyVISA available
self.is_windows: bool
self.camera_available: bool            # Windows + pyphantom only

# Experiment tracking
self.cumulative_distance: float = 0.0  # Total motor travel (mm)
self.cleaning_in_progress: bool = False
self._experiment_saved: bool = True    # False = unsaved data exists

self.pressure_data = {
    'live_buffer':       {'timestamps': [], 'pressures': []},
    'experiment_data':   {'timestamps': [], 'pressures': []},
    'experiment_active': bool,
    'experiment_start_time': float | None,
    'live_buffer_start_time': float,
}
self._last_experiment_snapshot: dict   # Copy of last experiment data

# Calibration
self.pixels_per_mm: float | None
self._cal_image_path: str | None

# Cone / webcam
self._cone_cap: cv2.VideoCapture | None
```

### 2.4 Timers

| Timer | Interval | Purpose |
|-------|----------|---------|
| `_serial_timer` | 200 ms | Poll serial port for incoming messages |
| `_graph_timer` | 500 ms | Refresh live pressure graph |
| `_cone_feed_timer` | 100 ms | Update live cone webcam feed |
| `_cone_auto_timer` | 5000 ms (default) | Auto-capture cone image during experiment |

### 2.5 Tabs

#### Tab 0 — Hardware

**Arduino section:**
- Port dropdown (auto-scanned via `serial.tools.list_ports`)
- Connect → `_trigger_arduino_connect()` → Worker thread → `_do_arduino_connect(port)` → `_on_arduino_connected()`
- Disconnect → `_trigger_arduino_disconnect()`

**Pressure section:**
- Target BAR input (0.0–26.4)
- Set Pressure → `_set_pressure()` → sends `PRESSURE:X\n`
- Pressure Off → `_pressure_off()` → sends `PRESSURE_OFF\n`
- Live current pressure label (updated by `_handle_pressure_reading()`)

**Motor section:**
- Speed (steps/s) + Distance (mm) inputs
- Move → `_move_motor()` → sends `SPEED:X;DIST:Y\n`
- Home → `_home_motor()` → sends `HOME:1\n`
- Clean → `_start_cleaning()` → automated multi-pass cleaning sequence
- Homed indicator dot (red → green after homing)

#### Tab 1 — Camera (Phantom)

- IP address input (default `100.100.100.1`)
- Connect → `_cam_connect()` / Ping → `_cam_ping()`
- Config: FPS, width, height, duration (s), exposure (μs), output path
- Apply Config → `_cam_configure()` → saves to `camera_settings.json`
- Capture → `_cam_capture()` → `phantom.start_recording() → trigger() → save_recording()`
  - Optional: Run CV pipeline after capture (`_run_pipeline(path)`)
- Abort → `_cam_abort()`
- ⚠ Only functional on Windows with pyphantom SDK installed

#### Tab 2 — AFG1062

- Auto-detect or manual PyVISA resource string
- Connect/Disconnect → `_afg_connect()` / `_afg_disconnect()`
- Configure: pulse duration, amplitude (V), channel (CH1/CH2)
- Configure → `_afg_configure()` → SCPI commands (square wave, burst mode, etc.)
- Trigger → `_afg_test()` → sends `*TRG`

#### Tab 3 — Calibration

- Take Photo → `_cal_take_photo()` (Phantom capture or webcam)
- Load Photo → `_cal_load_photo()` (file picker)
- `ClickableImageWidget`: click 2 points → crosshair overlays
- Calculate → `_cal_calculate()`:
  - Requires exactly 2 points
  - Computes vertical pixel distance: `pixel_dist = abs(y2 - y1)` (vertical-only — mount is always vertical)
  - Prompts for known distance in mm
  - Computes `pixels_per_mm = pixel_dist / mm_dist`
  - Saves to settings, updates header label
- Reset Points → clears clicks

#### Tab 4 — Cone

**Card 1 — Live Feed:**
- Camera index spinner (0–9) — USB webcam, independent of Phantom
- Start Camera → `_cone_start_camera()` → `cv2.VideoCapture(index)`, starts `_cone_feed_timer`
- Stop Camera → `_cone_stop_camera()` → releases cap, stops timers
- Auto-focus checkbox + manual focus spinbox (0–255) → `_cone_apply_focus()`
  - Sets `cv2.CAP_PROP_AUTOFOCUS` and `cv2.CAP_PROP_FOCUS`
  - Hardware-dependent; may be silently ignored by some webcams
- All settings (camera index, autofocus, focus value) persist in `camera_settings.json`
- Auto-connect on startup if saved index ≥ 0

**Card 2 — Capture & Results:**
- Capture & Analyse → `_cone_capture()`:
  - Grabs frame from `_cone_cap`
  - Rotates 90° clockwise (`cv2.ROTATE_90_CLOCKWISE`) — camera is mounted sideways
  - Saves raw PNG to `_cone_save_dir()` with timestamp
  - Calls `detect_cone_angle(Path(raw_path))` from `Cone_3.py`
  - Saves annotated result, displays in result card
  - Shows cone angle + save path labels
- Auto-capture status: `"Auto-capture: inactive"` → `"Auto-capture: ON (every 5 s)"`
- Result image (500×300 px), angle label, saved path label

**Save path logic:**
```python
def _cone_save_dir(self):
    lacie = find_lacie_drive()
    if lacie:
        return os.path.join(lacie, "Experiments", "Logs", "Testing")
    else:
        return os.path.join(os.path.dirname(__file__), "cone_captures")
```

**Auto-capture during experiment:**
- `_start_experiment()` starts `_cone_auto_timer` (5000 ms) if camera is open
- `_on_movement_complete()` stops `_cone_auto_timer`, resets status label

#### Tab 5 — How To (Hidden)

- Triggered by corner `QPushButton` in tab bar
- `setTabVisible(5, False)` by default
- Contains help text / instructions

### 2.6 All Methods

#### Initialisation
| Method | Purpose |
|--------|---------|
| `__init__()` | Init state, build UI, load settings, start timers, auto-connect |
| `_build_ui()` | Assemble main layout |
| `_build_header()` | Header bar + status dots |
| `_build_left_panel()` | Shadowgraph + graph + motor travel + emergency cards |
| `_build_right_panel()` | Nozzle + notes + save cards |
| `_build_tabs()` | Tab widget; How To corner button |
| `_build_[tab]_tab()` | Individual tab builders |
| `_build_status_bar()` | Bottom bar + START EXPERIMENT button |

#### Serial Port
| Method | Purpose |
|--------|---------|
| `_get_serial_ports()` | List available COM/tty ports |
| `_refresh_ports()` | Re-scan, update dropdown |
| `_trigger_arduino_connect()` | Spawn Worker thread to avoid blocking UI |
| `_do_arduino_connect(port)` | Blocking connect logic (called by Worker) |
| `_on_arduino_connected(ctrl)` | UI update on success; start serial reader |
| `_on_arduino_error(msg)` | Show `_warn()` popup |
| `_trigger_arduino_disconnect()` | Close connection, stop reader |
| `_start_serial_reader()` | Spawn background thread → `_serial_reader_loop()` |
| `_serial_reader_loop()` | Blocking readline loop; parses messages; emits via `QTimer.singleShot()` |
| `_handle_pressure_reading(val)` | Append to buffers, update labels |

#### Hardware Control
| Method | Purpose |
|--------|---------|
| `_set_pressure()` | Parse input, validate 0–26.4 BAR, send `PRESSURE:X\n` |
| `_pressure_off()` | Send `PRESSURE_OFF\n`, update UI |
| `_home_motor()` | Send `HOME:1\n`; wait for `ARDUINO_READY` |
| `_on_homed()` | Green dot, reset cumulative distance |
| `_move_motor()` | Send `SPEED:X;DIST:Y\n`, show progress bar |
| `_start_cleaning()` | Automated multi-pass cleaning sequence |
| `_update_travel_bar()` | Update motor progress bar + cumulative label |
| `_on_movement_complete()` | Stop pressure, reset Arduino, snapshot data, enable start |

#### Camera (Phantom)
| Method | Purpose |
|--------|---------|
| `_cam_connect()` / `_do_camera_connect()` | Connect to Phantom SDK |
| `_cam_ping()` | Test connection |
| `_cam_configure()` | Apply + save config |
| `_cam_capture()` | Record, trigger, save; optionally run CV pipeline |
| `_cam_abort()` | Abort recording |
| `_run_pipeline(path)` | Import and call `save_and_analyse.process_and_save_to_lacie()` |

#### Calibration
| Method | Purpose |
|--------|---------|
| `_cal_take_photo()` | Capture from camera or webcam |
| `_cal_load_photo()` | File picker → load into widget |
| `_cal_load_image_into_widget(path)` | Convert to QPixmap, display |
| `_cal_on_points_changed(points)` | Callback on click |
| `_cal_reset_points()` | Clear clicks |
| `_cal_calculate()` | Compute px/mm, prompt for mm distance, apply |
| `_apply_calibration_result(val)` | Save to settings, update header |

#### Cone Detection
| Method | Purpose |
|--------|---------|
| `_cone_start_camera()` | Open `cv2.VideoCapture(index)`, start feed timer, apply focus |
| `_cone_stop_camera()` | Release cap, stop timers |
| `_cone_update_feed()` | Read frame, rotate 90° CW, convert to QPixmap, display |
| `_cone_capture()` | Grab + rotate frame, save PNG, call `detect_cone_angle()`, display result |
| `_cone_apply_focus()` | Set `CAP_PROP_AUTOFOCUS` / `CAP_PROP_FOCUS`, save settings |
| `_cone_bgr_to_pixmap(arr)` | NumPy BGR → QPixmap helper |
| `_cone_save_dir()` | LaCie path or local fallback |

#### Experiment
| Method | Purpose |
|--------|---------|
| `_start_experiment()` | Init buffers, send motor command, start cone timer |
| `_on_movement_complete()` | Snapshot data, stop cone timer, mark unsaved |
| `_save_to_excel()` | Write openpyxl workbook (summary + pressure + cone sheets) |
| `_find_latest_result()` | Scan LaCie Shadowgraph for newest timestamped result |
| `_refresh_shadowgraph()` | Display latest result in left panel |

#### Settings
| Method | Purpose |
|--------|---------|
| `_load_camera_settings()` | Read JSON, populate Camera tab + Cone tab inputs |
| `_save_camera_settings()` | Write JSON from current inputs |

#### UI Helpers
| Method | Purpose |
|--------|---------|
| `_warn(title, msg)` | Dark-styled QMessageBox |
| `_require_arduino()` | Guard: show warning and return False if not connected |
| `_set_status(msg, color)` | Update status bar |
| `closeEvent(event)` | Cleanup: disconnect, stop threads, save settings |

### 2.7 Threading Model

| Thread | What runs | Communication |
|--------|-----------|---------------|
| **Main (Qt event loop)** | UI rendering, timers, user interactions | — |
| **Serial Reader (QThread)** | `_serial_reader_loop()` — blocking `ser.readline()` | `QTimer.singleShot()` to main thread |
| **Arduino Connect Worker** | `_do_arduino_connect()` — blocking connect | Signal → `_on_arduino_connected()` |
| **Camera Connect Worker** | `_do_camera_connect()` — blocking SDK connect | Signal → `_on_camera_connected()` |

### 2.8 Experiment State Machine

```
IDLE (_experiment_saved=True)
  │
  ▼ [User clicks START EXPERIMENT]
RUNNING (experiment_active=True)
  ├─ Pressure readings accumulated every 250ms
  ├─ Cone auto-capture every 5s (if camera open)
  └─ Motor executing movement
  │
  ▼ [MOVEMENT_COMPLETE received via serial]
COMPLETE (_experiment_saved=False)
  ├─ Progress bar hidden
  ├─ Save button enabled
  └─ Status: "Experiment complete ✓ — remember to Save to Excel"
  │
  ▼ [User clicks SAVE TO EXCEL]
SAVED (_experiment_saved=True)
```

---

## 3. Arduino Firmware — Pressure_Motor_Portenta.cpp

**File:** `src/gui/Pressure_Motor_Portenta.cpp`
**Hardware:** Arduino Portenta H7 + TMC5160 stepper driver
**Upload:** Arduino IDE, Portenta H7 board selected

### 3.1 Hardware Pin Map

| Signal | Pin | Notes |
|--------|-----|-------|
| STEP | IO6 (pin 3) | TMC5160 step pulse |
| DIR | IO13 (pin 2) | TMC5160 direction |
| EN | IO26 (pin 0) | TMC5160 enable (active LOW) |
| CS | IO4 (pin 6) | TMC5160 SPI chip select |
| MOSI/MISO/SCK | pins 8/10/9 | SPI bus |
| PRESSURE_PWM | pin 13 | PWM out → LLC → AliCat 5V input |
| PRESSURE_ADC | A0 | 12-bit ADC ← AliCat feedback (via LLC) |
| LIMIT_FRONT | pin 1 | INPUT_PULLUP — front optical switch |
| LIMIT_BACK | pin 5 | INPUT_PULLUP — back optical switch (homing) |
| Serial (USB CDC) | — | 9600 baud, GUI ↔ Arduino |
| Serial1 (UART) | — | 115200 baud, Arduino ↔ Pi camera system |

### 3.2 Motor Specifications

| Parameter | Value |
|-----------|-------|
| Steps/revolution | 200 |
| Microstepping | 16× |
| Lead screw pitch | 2 mm |
| Gearbox ratio | 4.25× |
| **Steps/mm** | **13,600 steps/mm** |
| Acceleration | 1,000 mm/s² (= 13,600,000 steps/s²) |
| Travel limit | 0–72.5 mm (0–986,000 steps) |

**Homing sequence:**
1. Move toward back optical switch at −10,000 steps/s
2. If switch already triggered, move away first
3. On switch trigger, set current position = 0
4. Move forward a small amount (clear switch)
5. Log: `Homing Complete!` → `ARDUINO_READY`

### 3.3 Pressure Control

| Parameter | Value |
|-----------|-------|
| PWM frequency | 1 kHz |
| PWM resolution | 12-bit (0–4095) |
| Duty cycle range | 20% (0 BAR) to 68% (26.4 BAR) |
| Pressure range | 0–26.4 BAR |

**ADC → Pressure reading:**
```
V = ADC / 4096 × 3.3 V
Linear map: 0.48 V → 0 BAR, 2.4 V → 50 BAR
Correction: Actual = (Reading − 0.6) / 1.032
Clamped to 0–26.4 BAR
Smoothed: rolling average of 4 readings (1-second window)
```

**Pressure setpoint → PWM:**
```
Compensated = (Desired + 0.2) / 1.16
Duty% = 20 + (Compensated / 26.4) × 48
PWM = (Duty% / 100) × 4095   (clamped 819–2785)
```

### 3.4 Key Firmware Variables

```cpp
constexpr uint32_t steps_per_mm = 13600;
AccelStepper stepper(DRIVER, STEP_PIN, DIR_PIN);

int  moveFinished = 1;          // 1 = idle, 0 = moving
bool homed = false;
float targetPressure = 0.0;
bool pressureControlEnabled = false;
float pressureBuffer[4] = {0}; // Rolling average

// Stall detection
unsigned long lastPositionChangeTime = 0;
```

### 3.5 Main Loop Structure

```
loop():
  ├─ [Once] if !homed → homing() → ARDUINO_READY
  ├─ [Every 3 s, when idle] → Serial.println("ARDUINO_READY")
  ├─ [Every 250 ms] → readPressure() → PRESSURE_READING:X.XX
  ├─ [Every byte] → accumulate inputString until '\n'
  ├─ [On newline] → parse + dispatch command
  └─ [When moveFinished==0]
      ├─ stepper.run()
      ├─ [Every 100 ms] → "DEBUG: Movement progress: X%"
      ├─ Stall detection (no position change for 2 s)
      └─ [On distanceToGo()==0] → MOVEMENT_COMPLETE → ARDUINO_READY
```

---

## 4. Serial Communications Protocol

### 4.1 GUI → Arduino (Commands)

| Command | Format | Purpose |
|---------|--------|---------|
| Set pressure | `PRESSURE:<float>\n` | Set target BAR (e.g. `PRESSURE:10.5\n`) |
| Pressure off | `PRESSURE_OFF\n` | Disable pressure (0% PWM) |
| Motor move | `SPEED:<int>;DIST:<float>\n` | Move motor (steps/s, mm) |
| Home | `HOME:1\n` | Run homing sequence |
| Reset state | `RESET:1\n` | Clear movement state / re-arm |
| Camera passthrough | `CAM:<msg>\n` | Forward to Pi via Serial1 |

### 4.2 Arduino → GUI (Messages)

| Message | Format | When |
|---------|--------|------|
| Ready | `ARDUINO_READY\n` | On startup, after homing, after reset, every 3 s idle |
| Pressure ack | `PRESSURE_SET:X.XX\n` | After each `PRESSURE:` command |
| Pressure disabled | `PRESSURE_DISABLED\n` | After `PRESSURE_OFF` |
| Pressure reading | `PRESSURE_READING:X.XX\n` | Every 250 ms (always streaming) |
| Movement start | `MOVEMENT_START:Pos=... Target=... Steps=...\n` | On movement begin |
| Movement progress | `DEBUG: Movement progress: X%\n` | Every 100 ms during movement |
| Movement complete | `MOVEMENT_COMPLETE\n` | When move finishes or stalls |
| Homing | `Stepper is Homing…\n` → `Homing Complete!\n` | During homing |
| Debug lines | `DEBUG: <text>\n` | Throughout (verbose logging always on) |

### 4.3 GUI Serial Reader

- Background `QThread` spawned by `_start_serial_reader()` after Arduino connects
- Runs `_serial_reader_loop()`: blocking `ser.readline()` → parse → `QTimer.singleShot()` to main thread
- Exits cleanly on `serial.SerialException` (port closed / disconnected)
- `MOVEMENT_COMPLETE` → calls `_on_movement_complete()` on main thread

---

## 5. Data Flow — Complete Experiment Run

### 5.1 Pre-conditions

- Arduino connected (`arduino_connected = True`)
- Motor homed (homed indicator green)
- Pressure target entered
- Calibration loaded (pixels/mm set)

### 5.2 Step-by-Step

**1. User clicks START EXPERIMENT**
```
_start_experiment():
  → check _experiment_saved, warn if unsaved data
  → pressure_data['experiment_active'] = True
  → pressure_data['experiment_start_time'] = time.time()
  → pressure_data['experiment_data'] = {'timestamps': [], 'pressures': []}
  → _cone_auto_timer.start(5000)   [if cone camera open]
  → arduino.send("SPEED:X;DIST:Y\n")
  → show progress bar, disable START button
```

**2. Arduino executes movement**
```
  ← MOVEMENT_START:...
  ← DEBUG: Movement progress: 10%   (every ~1s for 100ms Arduino loop × 10% steps)
  ← PRESSURE_READING:X.XX           (every 250ms throughout)
  ...
  ← MOVEMENT_COMPLETE
  ← ARDUINO_READY
```

**3. GUI during movement**
```
Serial reader thread:
  PRESSURE_READING → _handle_pressure_reading(val)
                   → append {time, pressure} to experiment_data
  DEBUG progress   → update progress bar
  MOVEMENT_COMPLETE → QTimer.singleShot → _on_movement_complete()
Graph timer (500ms) → _update_pressure_graph()
Cone auto timer (5s) → _cone_capture() → save PNG + run Cone_3
```

**4. _on_movement_complete()**
```
  → experiment_active = False
  → _cone_auto_timer.stop()
  → arduino.send("PRESSURE_OFF\n")
  → arduino.send("RESET:1\n")
  → _last_experiment_snapshot = copy of experiment_data
  → _experiment_saved = False
  → hide progress bar, enable START button
  → status: "Experiment complete ✓ — remember to Save to Excel"
```

**5. User clicks SAVE TO EXCEL**
```
  → openpyxl Workbook created
  → Sheet 1 — Summary: nozzle, orifice, notes, pressure stats, duration
  → Sheet 2 — Pressure: timestamp (s) | pressure (BAR) columns
  → Sheet 3 — Cone images: filenames (if captures were made)
  → Save dialog (default: ~/Desktop/experiment_<timestamp>.xlsx)
  → _experiment_saved = True
```

---

## 6. Imaging Pipeline (CV)

### 6.1 Entry Point

```python
save_and_analyse.process_and_save_to_lacie(input_source_path)
```

**Creates timestamped output folder:**
```
{lacie}/Shadowgraph/Mon_YYYY/DD_Mon/Mon_DD_YYYY_HH_MM_SS/
  ├── Input/input.ext
  └── Outputs/
      ├── FINAL_OPTIMIZED_RESULT.png
      ├── FINAL_ANALYSIS.csv
      ├── CANNY_EDGES.png
      ├── CANNY_DETECTION.png
      ├── WATERSHED_DETECTION.png
      ├── POSITION_MOVEMENT.png
      └── debug_images/
          ├── PREPROCESSING_OVERVIEW.png
          ├── COMPLETE_PIPELINE_VISUALIZATION_*.png
          └── WATERSHED_DEBUG_VISUALIZATION_*.png
```

### 6.2 Core Algorithm (`expansion_detection.process_image()`)

```
Input image
  │
  ▼ Preprocessing
    Median blur → CLAHE → Gamma correction → Normalize → Gaussian blur
  │
  ├─▶ Canny Edge Detection (small droplets)
  │     Canny(thresh1=50, thresh2=150)
  │     Find contours → min enclosing circles → filter radius ≥5px
  │     → canny_circles[]
  │
  ├─▶ Watershed + Hough (large droplets)
  │     Otsu threshold → morphological open
  │     Hough circle detection (seeds)
  │     Watershed segmentation
  │     Filter by component size
  │     → watershed_circles[]
  │
  ▼ Merge + Deduplicate
    Combine both lists, remove overlaps
  │
  ▼ Size Optimisation
    For each circle: test radii in [r×0.8, r×1.2]
    Maximise dark pixel % (NumPy vectorised mask)
    → size_optimized_circles[]
  │
  ▼ Position Optimisation
    Gradient descent on (x, y) for each circle
    Maximise dark pixel % within circle
    ~20–50 steps per circle
    → optimized_circles[]   ← FINAL RESULT
  │
  ▼ Return dict:
    {'optimized_circles', 'final_image', 'canny_edges',
     'watershed_debug_images', 'optimization_data', ...}
```

**Key optimisation techniques:**
- **NumPy circle masks** (50–200× faster than pixel loops)
- **Gradient descent** for position (vs brute-force 6,400-position grid = 100–300× faster)

---

## 7. AI/ML Pipeline — Detectron2

### 7.1 Model Architecture

| Property | Value |
|----------|-------|
| Framework | Detectron2 Mask R-CNN |
| Backbone | ResNet-50 FPN 3× |
| Classes | 2: `droplet` (0), `ligament` (1) |
| Annotation format | COCO with RLE binary masks |

**Best hyperparameters (Dennis model):**
```python
cfg.MODEL.ANCHOR_GENERATOR.SIZES = [[8, 16, 32, 64]]
cfg.SOLVER.BASE_LR = 0.0025
cfg.SOLVER.WARMUP_ITERS = 1000
cfg.SOLVER.LR_SCHEDULER_NAME = "WarmupCosineAnnealingLR"
cfg.MODEL.ROI_HEADS.BATCH_SIZE_PER_IMAGE = 512
cfg.MODEL.ROI_HEADS.NUM_CLASSES = 2
cfg.SOLVER.CHECKPOINT_PERIOD = 10000
cfg.TEST.EVAL_PERIOD = 500
MAX_ITER = 78000
```

### 7.2 Named Models

| Name | Status | LR | Anchors | Notes |
|------|--------|----|---------|-------|
| **Dennis** / **Early_Dennis** | **Current best** | 0.0025 | [8,16,32,64] | Needs fringe/boundary data before real-image deployment |
| **Benedict** | Checkpoint | 0.0025 | [8,16,32,64] | Resume point for Dennis training |
| **Claudia** | Baseline | 0.0002 | COCO default | Lower performance; comparison only |

### 7.3 Training (`train_detectron2.py` — root, canonical)

**Key variables:**
```python
BATCH_SIZE = 2
BASE_LEARNING_RATE = 0.0025
ANCHOR_SIZES = [[8, 16, 32, 64]]
WARMUP_ITERS = 1000
LR_DECAY_TYPE = "cosine"    # "cosine" | "step" | "none"
MAX_ITER = 78000
CHECKPOINT_INTERVAL = 10000
VALIDATION_SPLIT = 0.1      # or VALIDATION_SIZE = 20 for fixed count
VALIDATION_INTERVAL = 500
RESUME_FROM_MODEL = None    # set to checkpoint path to resume

# Windows paths (training machine)
ANNOTATIONS_PATH = r"D:\Experiments\TrainingData\Detectron_Trial_2\blur_annotations.json"
IMAGES_PATH      = r"D:\Experiments\TrainingData\Detectron_Trial_2\images"
OUTPUT_BASE_DIR  = r"D:\Experiments\AI"
```

**Output:**
```
D:\Experiments\AI\training_<timestamp>\
  ├── model_final.pth
  ├── metrics.json
  └── (loss plots)
```

### 7.4 Synthetic Data Generator (`AI/synthetic_data/blur_spray_dataset_generator.py`)

**Purpose:** Generate realistic shadowgraph images with pixel-level instance masks for training.

**Image parameters:**
```python
IMAGE_WIDTH = 1280, IMAGE_HEIGHT = 800
BACKGROUND_INTENSITY_MIN = 240   # Very bright (real shadowgraph is backlit)

# Droplets: log-normal size distribution
DROPLET_SIZE_MU = 2.5, SIGMA = 0.8
DROPLET_RADIUS_MIN = 2, MAX = 50
DROPLET_POISSON_LAMBDA = 10      # ~10 per image

# Ligaments: curvy, non-uniform thickness
LIGAMENT_LENGTH_MIN = 30, MAX = 600
LIGAMENT_THICKNESS_MIN = 3, MAX = 50
LIGAMENT_POISSON_LAMBDA = 20
```

**Generation steps:**
1. Bright background (240–255) + low-frequency gradient + Gaussian noise
2. Droplets: radial absorption profile + Gaussian edge blur + bright halo rim
3. Ligaments: Bézier curves, non-uniform thickness, intensity variation
4. Background layer: out-of-focus droplets (heavy blur, low opacity)
5. Domain randomisation: Gaussian blur, motion blur, noise, intensity scaling
6. Save PNG images + `blur_annotations.json` (COCO RLE masks)

**Output:** `images/` folder + `blur_annotations.json`
**Parallelised:** Multiprocessing across all CPU cores.

**`conjoined_blur_spray_dataset_generator.py`** (NEW, unstaged): Purpose vs older generator is TBD — review before committing.

### 7.5 Hyperparameter Sweep (`hyperparameter_sweep.py`)

**Grid searched:**
```python
LEARNING_RATES = [0.0005, 0.001, 0.0025, 0.005, 0.01]
ANCHOR_SIZES   = [[8,16,32,64], [8,16,32,64,128], [16,32,64,128]]
WARMUP_CONFIGS = [0, 500, 1000]
DECAY_CONFIGS  = ["none", "step", "cosine"]
ITERATIONS_PER_RUN = 7000
```

**Results:** `AI/Testing_FUN/Hyperparameter_Tests/LR_Anchor_Sweep_Final/`
**Best:** LR=0.0025, anchors=[8,16,32,64], cosine decay → Dennis model

### 7.6 Evaluation (`AI/evaluate_model.py` — canonical)

```bash
python AI/evaluate_model.py \
  --model path/to/model_final.pth \
  --annotations path/to/annotations.json \
  --images path/to/images/ \
  --output results.xlsx
```

**Metrics per image:** TP, FP, FN, Precision, Recall, F1, Avg IoU
**Score threshold:** 0.1

**Outputs:**
1. Excel (3 sheets: Summary, Per-image, Category breakdown)
2. Appends row to `evaluation_results.csv` on LaCie
3. Prediction overlay PNGs
4. Per-image JSON

**⚠ `AI/Training_Analysis/evaluate_model.py` is a near-duplicate — use `AI/evaluate_model.py` instead.**

### 7.7 AI Post-Processing (Planned — not yet built)

See `docs/AI_PIPELINE_PLAN.md` for full spec. Summary:

- **`src/ai/process_run.py`**: Load TIFFs from a run folder → Detectron2 inference → compute SMD/D10/D90 → write `ai_results.xlsx`
- **`src/ai/metrics.py`**: Pure-function helpers for D32/D10/D90, Drop:Lig ratio
- **GUI additions**: "Process Run" button, AI result panel

**Blocked on:** Phantom hardware testing (frame capture mechanism TBD)

---

## 8. Cone Detection

### 8.1 Cone_3.py (Current — PCA-based)

**File:** `Trials/Cone_3.py`
**Status:** Complete, tested, integrated into GUI Cone tab

**API:**
```python
from Cone_3 import detect_cone_angle
angle, annotated_bgr, debug_info = detect_cone_angle(Path("frame.tiff"))
# Returns: (float degrees, np.ndarray BGR, dict)
# ⚠ Requires pathlib.Path input (calls .exists() on it)
# Saves annotated PNG as {stem}_cone3{ext} alongside input
```

**Algorithm:**
1. Load image, convert to grayscale
2. Gaussian blur (5×5)
3. Morphological close (7×7 kernel)
4. Find contours → select largest (spray silhouette)
5. Split contour into left / right halves by x-coordinate
6. Apply PCA to each half → dominant direction vector
7. Compute angle between vectors → cone angle in degrees

### 8.2 Cone_2.py (Legacy)

CLAHE-based, requires parameter CSV. Superseded by Cone_3. `cone_GUI.py` was the tuning UI for this version.

---

## 9. Configuration System

**File:** `src/config_loader.py`

### LaCie Auto-Detection

| OS | Paths checked |
|----|---------------|
| macOS | `/Volumes/LaCie`, then `/Volumes/*lacie*` |
| Windows | D:, E:, F:… for `Phantom/`, `Shadowgraph/`, `LaCie/` folders or volume label "lacie" |
| Linux | `/media/*lacie*`, `/mnt/*lacie*` |

### Key Functions

| Function | Returns |
|----------|---------|
| `find_lacie_drive()` | Path string or `None` |
| `get_config()` | Full config dict (lazy-loaded from `paths.yaml`) |
| `get_gui_config()` | `config['gui']` |
| `get_imaging_config()` | `config['imaging']` |
| `get_mp4_config()` | `config['mp4_to_tiff']` |
| `resolve_path(path_str)` | Normalised path with `{lacie_drive}` substituted |

---

## 10. Output Paths Summary

| Purpose | Path | Configured by |
|---------|------|---------------|
| CV pipeline results | `{lacie}/Shadowgraph/Mon_YYYY/DD_Mon/Mon_DD_YYYY_HH_MM_SS/` | `get_imaging_config()['output_root']` |
| Phantom video (raw) | `{lacie}/Phantom/Video/` | GUI Camera tab → `camera_settings.json` |
| TIFF frames | `{lacie}/Phantom/TIFF_Output/` | `get_mp4_config()` |
| Brightest frame | `{lacie}/Phantom/Flashed_Output/` | `get_mp4_config()` |
| Experiment logs | `{lacie}/Experiments/Logs/` | `get_gui_config()['experiment_log_dir']` |
| Cone captures | `{lacie}/Experiments/Logs/Testing/` or `src/gui/cone_captures/` | `_cone_save_dir()` |
| Serial log | `serial_log.txt` (repo root) | `get_gui_config()['serial_log_file']` |
| Excel exports | User-chosen (Save dialog) | User |
| AI training | `D:\Experiments\AI\training_<timestamp>\` | `train_detectron2.py OUTPUT_BASE_DIR` |
| Sweep results | `AI/Testing_FUN/Hyperparameter_Tests/LR_Anchor_Sweep_Final/` | `hyperparameter_sweep.py` |
| Evaluation | Excel + `evaluation_results.csv` on LaCie | `AI/evaluate_model.py` |

---

## 11. Hardware Summary

| Component | Model | Interface | Commanded by | Feedback |
|-----------|-------|-----------|--------------|----------|
| Stepper motor | TMC5160 (SPI) | USB serial | `SPEED:X;DIST:Y\n` | Progress %, `MOVEMENT_COMPLETE` |
| Pressure controller | AliCat | PWM + ADC (via Portenta) | `PRESSURE:X\n` | `PRESSURE_READING:X.XX` every 250 ms |
| Home switches | 2× optical | GPIO | (passive) | Homing trigger |
| High-speed camera | Phantom | Ethernet (pyphantom SDK) | GUI Camera tab | Video cine |
| Function generator | Tektronix AFG1062 | USB (PyVISA / SCPI) | GUI AFG tab | None |
| Cone webcam | USB | OpenCV (`cv2.VideoCapture`) | GUI Cone tab | Live feed, frame capture |

**Serial baud rates:**
- GUI ↔ Portenta: **9600 baud** (USB CDC)
- Portenta ↔ Pi: **115200 baud** (Serial1 UART)

---

## 12. Known Bugs & TODOs

### High Priority

| Issue | Location | Notes |
|-------|----------|-------|
| **Dennis needs fringe training data** | `AI/` | Best model, but trained only on clean spray; real images have fringe droplets not in training set |
| **Canonical evaluate script** | `AI/` | Use `AI/evaluate_model.py` — `AI/Training_Analysis/evaluate_model.py` is a near-duplicate and should be deleted |

### Medium Priority

| Issue | Location | Notes |
|-------|----------|-------|
| **AI pipeline not built** | `src/ai/` | `process_run.py` and `metrics.py` don't exist yet — blocked on Phantom hardware testing |
| **Phantom frame capture TBD** | `src/gui/` | Whether LED flash auto-triggers Phantom save, or GUI must call SDK method, is unresolved |
| **pyphantom `_cal_take_photo()`** | `GUI_Clean.py` ~line 1973 | TODO: verify correct pyphantom method for live calibration image |

### Low Priority

| Issue | Location | Notes |
|-------|----------|-------|
| **Calibration save path** | `GUI_Clean.py` ~line 1964 | TODO: change to `config_loader.get_gui_config()['calibration_output_dir']` |
| **Hard-coded Windows paths** | Multiple AI scripts | `D:\Experiments\...` hardcoded — should use `config_loader.resolve_path()` |
| **`conjoined_blur_spray_dataset_generator.py`** | `AI/synthetic_data/` | Unstaged new file; purpose vs old generator not documented |
| **`AI/Training_Analysis/` duplicates** | `AI/Training_Analysis/` | All scripts are copies of root-level scripts — safe to delete |
| **Cone webcam focus** | `GUI_Clean.py` | `cv2.CAP_PROP_FOCUS` is hardware-dependent; may be silently ignored |
| **Per-run folder structure** | `GUI_Clean.py` | `_save_to_excel()` uses flat structure; `AI_PIPELINE_PLAN.md` specifies `per_run/YYYY/MM/DD/N{nozzle}_{pressure}BAR_{HHMMSS}/` — not yet implemented |

---

## 13. Dependencies & Environments

### `requirements.txt` (core)

```
opencv-python>=4.5.0
numpy>=1.20.0,<2.0      # NumPy 2.x breaks pyphantom
matplotlib
pandas
customtkinter           # Legacy GUI only
Pillow
openpyxl
pyserial>=3.5
PyYAML>=5.4.0
pycocotools>=2.0.0
PySide6
pyqtgraph
```

### Optional / Separate

| Package | Purpose | Platform |
|---------|---------|----------|
| `pyphantom` | Phantom camera SDK | Windows only (vendor) |
| `pyvisa` | AFG1062 SCPI control | Any |
| `detectron2` | Mask R-CNN training/inference | Windows (CUDA) |
| `torch` (CUDA) | PyTorch GPU backend | Windows (NVIDIA) |
| `win32api` | Windows volume label detection | Windows (optional — graceful fallback) |

### Environments

**macOS (development):**
- Python 3.9+, conda optional
- Detectron2 not installed (training done on Windows)
- GUI fully functional except Camera tab (pyphantom) and AI inference

**Windows (training + lab):**
- Conda env `detectron2`: torch + detectron2 + CUDA 11.x
- Python 3.9+
- NVIDIA GPU required for training
- Full GUI functionality (pyphantom available)

### Cross-Platform Notes

| Feature | macOS | Windows |
|---------|-------|---------|
| GUI | Full (except Camera tab) | Full |
| Phantom SDK | Not available | Available (pyphantom) |
| Webcam (Cone tab) | `cv2.VideoCapture(0)` | Same |
| LaCie path | `/Volumes/LaCie/` | `D:\` (auto-detected) |
| Serial ports | `/dev/tty.usbmodem...` | `COM3`, `COM4`… |
| Detectron2 training | Not supported | Conda env `detectron2` |
