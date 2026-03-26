# HPATR — File & Folder Structure Plan

**Status:** Planning — not yet fully implemented
**Last updated:** 2026-03-24
**Purpose:** Single source of truth for where every file the GUI produces or consumes should live.

---

## 1. Guiding Principles

1. **One folder per run** — every file related to a single experiment run lives inside one folder. Nothing is flat.
2. **LaCie is the data drive** — all experiment outputs go to the LaCie. The repo stays clean.
3. **Run folder created at experiment start** — not at save time. This means raw frames, cone captures, and the summary file all share the same folder naturally.
4. **Graceful LaCie fallback** — if the drive isn't connected, everything falls back to `experiment_logs/` in the project root. Same structure, different root.
5. **Local config stays local** — `camera_settings.json` is per-machine config, not experiment data. It stays in `src/gui/` and is `.gitignore`'d.

---

## 2. Full LaCie Structure

```
LaCie/
│
├── master_log.xlsx                                  ← global log, one row per run (appended)
│
├── Experiments/
│   └── YYYY/
│       └── MM/
│           └── DD/
│               └── {HHMMSS}_N{nozzle}_{pressure}BAR/    ← ONE FOLDER PER RUN
│                   │
│                   ├── run_summary.xlsx             ← metadata + pressure trace + px/mm scale
│                   ├── ai_results.xlsx              ← post-hoc, written by process_run.py
│                   │
│                   ├── shadowgraph/
│                   │   ├── raw/                     ← Phantom TIFF frames (frame_001.tiff etc.)
│                   │   └── analysis/                ← CV pipeline output
│                   │       ├── FINAL_OPTIMIZED_RESULT.png
│                   │       ├── FINAL_ANALYSIS.csv
│                   │       └── debug_images/
│                   │
│                   └── cone/
│                       ├── cone_raw_{HHMMSS}.png    ← raw webcam frame
│                       └── cone_{HHMMSS}.png        ← annotated (angle overlaid)
│
├── Phantom/
│   └── raw_cine/                                    ← .cine files direct from camera (pre-export/temp)
│
└── Calibration/
    └── cal_{YYYYMMDD_HHMMSS}.png                    ← calibration photos (one per optics setup)
```

**Run folder name example:** `143052_N0.3_4.0BAR`
Format: `{HHMMSS}_N{nozzle}_{pressure}BAR`
— time-sortable within a day, human-readable, no spaces.

---

## 3. Everything the GUI Touches — Where It Goes

| File / Output | Destination | Notes |
|---|---|---|
| **Run folder** | `LaCie/Experiments/YYYY/MM/DD/{run_id}/` | Created at "Start Experiment" click |
| **run_summary.xlsx** | `{run_folder}/run_summary.xlsx` | Sheets: Metadata, Pressure, Cone Images |
| **master_log.xlsx** | `LaCie/master_log.xlsx` | Appended on every save; one row per run |
| **ai_results.xlsx** | `{run_folder}/ai_results.xlsx` | Written post-hoc by `process_run.py` |
| **Phantom TIFF frames** | `{run_folder}/shadowgraph/raw/frame_NNN.tiff` | Exported from Phantom into run folder |
| **CV pipeline output** | `{run_folder}/shadowgraph/analysis/` | `save_and_analyse.py` target |
| **Phantom raw .cine** | `LaCie/Phantom/raw_cine/` | Temporary — can be deleted after TIFF export |
| **Cone raw frame** | `{run_folder}/cone/cone_raw_{HHMMSS}.png` | Raw webcam frame |
| **Cone annotated** | `{run_folder}/cone/cone_{HHMMSS}.png` | With angle overlay |
| **Calibration photo** | `LaCie/Calibration/cal_{YYYYMMDD_HHMMSS}.png` | Saved from Calibration tab |
| **camera_settings.json** | `src/gui/camera_settings.json` | Per-machine config — stays local, `.gitignore`'d |
| **serial_log.txt** | `LaCie/Logs/serial_log.txt` | Appended per session; fallback to repo root |

---

## 4. What Changes vs. Current Code

| Current behaviour | Target behaviour |
|---|---|
| Run folder created at **Save to Excel** time | Run folder created at **Start Experiment** click |
| Cone saves go to `LaCie/Experiments/Logs/Testing/` (flat, not per-run) | Cone saves go to `{run_folder}/cone/` |
| CV pipeline saves to `LaCie/Shadowgraph/Mon_YYYY/DD_Mon/…` (different structure) | CV pipeline target is `{run_folder}/shadowgraph/analysis/` |
| Per-run Excel named `YYYYMMDD_HHMMSS_Nnozzle_orifice.xlsx` (flat) | `run_summary.xlsx` inside the run folder |
| Calibration photos saved to `src/gui/calibration_photos/` (in repo) | `LaCie/Calibration/cal_{ts}.png` |
| `serial_log.txt` at repo root | `LaCie/Logs/serial_log.txt` |
| Excel save path hint shows `experiment_logs/` | Hint shows actual run folder path once created |

---

## 5. Run Folder Lifecycle

```
[User fills in Nozzle + Pressure fields]
        ↓
[START EXPERIMENT clicked]
  → run_id = "{HHMMSS}_N{nozzle}_{pressure}BAR"
  → run_folder = LaCie/Experiments/YYYY/MM/DD/{run_id}/
  → create subfolders: shadowgraph/raw/, shadowgraph/analysis/, cone/
  → GUI stores run_folder path for the rest of this experiment

[During experiment]
  → cone auto-captures save to {run_folder}/cone/
  → Phantom frames save to {run_folder}/shadowgraph/raw/

[SAVE TO EXCEL clicked]
  → run_summary.xlsx written to {run_folder}/
  → master_log.xlsx updated at LaCie root
  → GUI shows run_folder path in status bar

[POST-HOC — user clicks "Process Run" (not yet built)]
  → process_run.py loads {run_folder}/shadowgraph/raw/
  → runs Detectron2 inference
  → writes {run_folder}/ai_results.xlsx
```

---

## 6. LaCie Not Connected — Fallback

If `find_lacie_drive()` returns `None`, replace `LaCie/` with `experiment_logs/` (project root).
Structure is identical underneath. A status bar warning should appear when the fallback is active.

---

## 7. `config_loader.py` Keys to Add

The following paths should be surfaced via `config_loader.py` so nothing is hardcoded in the GUI:

```python
get_lacie_paths() → {
    'experiments_root':   '{lacie}/Experiments/',
    'master_log':         '{lacie}/master_log.xlsx',
    'phantom_raw_cine':   '{lacie}/Phantom/raw_cine/',
    'calibration':        '{lacie}/Calibration/',
    'serial_log':         '{lacie}/Logs/serial_log.txt',
}
```

The run folder path itself is constructed at runtime by the GUI from `experiments_root + YYYY/MM/DD/{run_id}/`.

---

## 8. `run_summary.xlsx` Schema

Three sheets (replaces the current per-run Excel format):

**Sheet 1 — Metadata**
| Field | Value |
|---|---|
| Timestamp | 2026-03-24 14:30:52 |
| Nozzle | 0.3 |
| Orifice | 0.5mm |
| Pressure Range | 3.5–4.5 BAR |
| Speed (steps/s) | 5000 |
| Distance (mm) | 25.0 |
| px/mm Scale | 42.3 |
| Notes | free text |

**Sheet 2 — Pressure**
Two columns: `Timestamp (s)` | `Pressure (BAR)` — one row per 250 ms reading.

**Sheet 3 — Cone Images**
Filenames of all cone captures taken during this run (relative paths within the run folder).

---

## 9. Files That Stay in the Repo (NOT on LaCie)

| File | Why |
|---|---|
| `src/gui/camera_settings.json` | Per-machine (Phantom IP, cone camera index, exposure, crop). Not experiment data. Add to `.gitignore`. |
| `src/config/paths.yaml` | User-edited config with `{lacie_drive}` placeholder. Already in repo. |

---

## 10. Standalone Testing Fallbacks

Some GUI tabs (Cone, Calibration, Camera) can be used independently without an active experiment. When there is no run folder, these fall back to their **current save locations** — no change from today's behaviour:

| Feature | Active experiment | No experiment (standalone / testing) |
|---|---|---|
| Cone captures | `{run_folder}/cone/` | `LaCie/Experiments/Logs/Testing/` (or `src/gui/cone_captures/` if no LaCie) |
| Calibration photos | `LaCie/Calibration/cal_{ts}.png` | `src/gui/calibration_photos/` (current behaviour, unchanged) |
| Phantom capture | `{run_folder}/shadowgraph/raw/` | User-specified path in Camera tab output field (current behaviour, unchanged) |

The GUI determines which path to use by checking whether `self._run_folder` is set (i.e. an experiment has been started and not yet cleared).

---

## 11. Decisions

- [ ] **Phantom frame export mechanism** — does the GUI call `phantom.save_recording()` directly into `{run_folder}/shadowgraph/raw/`, or does the user export from PCC manually? **Blocked on hardware testing — revisit once Phantom is set up.**
- [x] **Run folder creation timing** — **Eager.** Folder is created the moment "Start Experiment" is clicked, before any captures happen.
- [x] **serial_log.txt** — **One file per session**, named `serial_{YYYYMMDD_HHMMSS}.txt`, saved to `LaCie/Logs/`. Avoids the file growing unboundedly across many sessions.
- [x] **Calibration** — **Global.** `LaCie/Calibration/cal_{YYYYMMDD_HHMMSS}.png`. The px/mm value used is always recorded in `run_summary.xlsx` so it's traceable per-run.
