# AI Post-Processing Pipeline — Planning Document

**Status:** Planning / Pre-implementation
**Last updated:** 2026-03-10
**Phantom integration:** TBD — revisit once hardware testing is complete

---

## 1. Architecture Overview

Processing is split into two phases:

```
DURING TEST (GUI running):
  ├─ Pressure data logged in real time
  ├─ Metadata recorded (nozzle, orifice, speed, distance, notes)
  ├─ Raw shadowgraph frames saved by Phantom (mechanism TBD)
  └─ Run folder created on LaCie drive

AFTER TEST (user clicks "Process Run"):
  ├─ process_run.py loads each saved frame
  ├─ Detectron2 Mask R-CNN runs inference on each frame
  ├─ SMD / D10 / D90 computed per frame using px/mm calibration
  ├─ ai_results.xlsx written into run folder
  └─ GUI result panel updates with best frame + summary stats
```

Post-hoc processing was chosen over live/streaming because:
- No timing pressure on the model during the experiment
- Can re-run if the model is retrained
- Simpler to implement and debug

---

## 2. Folder Structure

```
experiment_logs/
├── master_log.xlsx                            ← global log of all runs
└── per_run/
    └── YYYY/
        └── MM/
            └── DD/
                └── N{nozzle}_{pressure}BAR_{HHMMSS}/   ← one folder per run
                    ├── run_summary.xlsx       ← pressure trace, metadata, px/mm scale
                    ├── ai_results.xlsx        ← AI model output (written post-hoc)
                    ├── shadowgraph/           ← raw frames from Phantom (TIFF)
                    │   ├── frame_001.tiff
                    │   ├── frame_002.tiff
                    │   └── ...
                    └── cone/                  ← reserved, empty for now
```

**Run folder naming example:** `N0.3_4.0BAR_143052`
Nozzle size + pressure + time-of-day (HHMMSS). Unique, human-readable, sortable by time within a day.

---

## 3. Shadowgraph Frame Capture

**Status: TBD — pending Phantom hardware testing**

Open questions to resolve:
- Does the LED flash every ~10 s trigger the Phantom to auto-save a TIFF, or does the GUI need to request it via the SDK?
- Is it one frame per flash, or a short burst?
- What is the exact TIFF naming/format output by the Phantom SDK?
- Does frame saving happen automatically to the LaCie, or does the GUI need to initiate a transfer?

Once these are answered this section will be updated with the exact capture mechanism.

---

## 4. AI Results Excel — Schema

**One row per frame.**

| Column | Description |
|---|---|
| Frame | Sequential frame index (1, 2, 3…) |
| Timestamp (s) | Elapsed seconds from test start |
| Image File | Filename of the source TIFF (relative to shadowgraph/) |
| N Droplets | Number of droplet instances detected |
| N Ligaments | Number of ligament instances detected |
| Drop:Lig Ratio | N Droplets / N Ligaments (indicator of atomisation completeness) |
| SMD D32 (mm) | Sauter Mean Diameter = Σd³ / Σd² across all detected droplets |
| D10 (mm) | 10th percentile equivalent diameter |
| D90 (mm) | 90th percentile equivalent diameter |
| Mean Confidence | Average detection confidence across all instances in this frame |
| Best Frame | TRUE on the row with the highest mean confidence, FALSE elsewhere |

**Notes:**
- D10 and D90 are almost free alongside D32 and characterise the width of the size distribution — a tight D10–D90 range means a uniform spray
- Equivalent diameter is derived from mask area: `d = 2 * sqrt(area_px / π)`, then converted to mm via px/mm calibration
- Drop:Lig ratio in a well-atomised spray should be high; low ratio indicates lingering ligaments

---

## 5. px/mm Calibration

A persistent-per-session input field in the GUI (Hardware tab or Experiment tab), labelled **"Scale (px/mm)"**.

- Editable at any time — re-enter when the lens or working distance changes
- Does **not** persist across GUI restarts (intentional — avoids using a stale value from a previous session with different optics)
- Written into `run_summary.xlsx` at save time so the calibration used is always recorded alongside the data
- Used by `process_run.py` when computing diameters in mm

---

## 6. What to Show in the GUI Result Panel

After AI processing completes, the left-panel result section should display:

| Field | Priority | Notes |
|---|---|---|
| Best frame image | High | Frame with highest mean confidence; shown as the representative shadowgraph |
| SMD D32 (mm) | High | Primary atomisation quality metric |
| D10 / D90 (mm) | High | Characterises spray uniformity |
| Mean confidence (%) | High | Flags low-certainty results to the user |
| Avg droplets / frame | Medium | Spray density indicator |
| Avg ligaments / frame | Medium | Complement to droplet count |
| Drop:Lig ratio | Medium | Single-number atomisation completeness |
| Frames processed | Medium | e.g. "12 / 12" — confirms run completed |

Histograms and SMD-over-time trend plots are the natural next step but are deferred until the above is working.

---

## 7. New Code Required

| File | Purpose |
|---|---|
| `src/ai/process_run.py` | Main post-processing script. Takes a run folder path as argument. Loads each TIFF from `shadowgraph/`, runs Detectron2 inference, computes metrics, writes `ai_results.xlsx`. Can also be run from command line for batch reprocessing. |
| `src/ai/metrics.py` | Pure-function helpers: D32/D10/D90 from a list of mask areas + px/mm scale, Drop:Lig ratio, best-frame selection. Unit-testable independently of the model. |
| `GUI_Clean.py` (updates) | Updated folder structure (per-run folder), px/mm calibration field, "Process Run" button (appears after test completes), result panel updated to show AI summary stats. |

**Platform note:** `process_run.py` requires Detectron2 and therefore only runs on Windows (conda env "Detectron"). The GUI itself is cross-platform (PySide6) — on macOS it will show "AI results not available" gracefully if `ai_results.xlsx` is absent.

---

## 8. Open Items / Decisions Pending

- [ ] Phantom frame capture mechanism (see Section 3)
- [ ] Exact px/mm value once optics are set up
- [ ] Whether "Process Run" runs in a subprocess (non-blocking GUI) or blocks — likely subprocess given model inference time
- [ ] Whether to add a per-detection sheet to `ai_results.xlsx` later (currently deferred — 1 row per frame is sufficient for now)
- [ ] Cone camera integration (folder reserved but empty until hardware is available)
