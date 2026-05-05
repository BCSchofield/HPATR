# Taguchi Experiment Data Plan

**Status:** Planning — not yet implemented
**Last updated:** 2026-05-05

---

## Goal

Make the HPATR experiment workflow Taguchi-compatible so that results from an L-array test campaign can be retrieved, grouped, and analysed with minimal manual effort.

---

## Current State (as of 2026-05-05)

### Folder structure generated per run

```
LaCie/Experiments/
└── YYYY/MM/DD/
    └── HHMMSS_N<nozzle>_<pressure>BAR/
        ├── run_summary.xlsx
        ├── shadowgraph/
        │   ├── raw/
        │   │   ├── CINE/
        │   │   ├── TIFFs/
        │   │   └── Brightest_Frame/
        │   └── analysis/
        │       ├── flashed_output.tiff
        │       ├── ai_result.png
        │       ├── ai_results.json       ← AI outputs (numeric)
        │       └── ai_summary.xlsx
        └── cone/
            └── cone_<timestamp>.png
```

### Master log

`LaCie/Experiments/Logs/master_log.xlsx` — one row per run, newest at top.

Columns: Timestamp · Nozzle · Orifice · Pressure Range · Speed (steps/s) · Distance (mm) · Notes · Cone Image (embedded) · Shadowgraph (embedded) · Pressure Graph (embedded)

### Per-run summary (`run_summary.xlsx`)

- Sheet **Metadata**: Timestamp, Nozzle, Orifice, Pressure Range, Speed, Distance, Notes
- Sheet **Pressure**: raw time-series (timestamps + pressures)

### AI outputs (`ai_results.json`)

Keys: `n_droplets`, `n_ligaments`, `mean_confidence`, `avg_droplet_um`, `dl_ratio`, `score_threshold`, `pixels_per_mm`, `detections` (per-object list)

---

## Identified Gaps

### Gap 1 — No commanded set-points, only measured ranges

`Pressure Range` is stored as e.g. `"11.8–12.3 BAR"` (live min–max). For Taguchi the *factor level* is the commanded value (e.g. `12.0 BAR`). These are different things. Same applies to Speed and Distance — stored as raw strings but not validated as numbers.

### Gap 2 — No experiment / trial / replicate identity

No concept of "this is Trial 3, Replicate 2 of experiment L9-NozzleStudy". Without this, grouping runs for analysis requires reading timestamps and guessing.

### Gap 3 — AI response variables not in master log

The master log has an embedded shadowgraph image but the numeric AI outputs (N droplets, avg droplet µm, D/L ratio, mean confidence) are not in any column. These are the *response variables* for Taguchi — they need to be in a flat table.

### Gap 4 — Cone angle not stored as a number

The cone image is embedded in the master log visually. If cone angle is a response variable it needs to be a numeric column.

---

## Recommended Changes

### Priority 1 — Must have (required for Taguchi to work)

#### 1a. Add Experiment Name + Trial + Replicate to GUI

Three new fields in the left panel (below or within the Nozzle card):

| Field | Type | Behaviour |
|---|---|---|
| Experiment Name | Text box | Persists via settings (so you don't retype it each run) |
| Trial | Integer spinner or text box | Set manually before each trial group |
| Replicate | Integer spinner or text box | Optionally auto-increments after each run |

#### 1b. Embed trial/replicate in folder name

Change run folder name from:
```
HHMMSS_N<nozzle>_<pressure>BAR
```
to:
```
T<trial>_R<replicate>_HHMMSS_N<nozzle>_<pressure>BAR
```

Example: `T03_R2_143022_N1_12.0BAR`

This means Taguchi assignment is recoverable from the folder name alone — no database needed.

#### 1c. Add fields to `run_summary.xlsx` Metadata sheet

Add to the existing Metadata sheet:

| Field | Value |
|---|---|
| Experiment Name | e.g. `"L9-NozzleStudy-May2026"` |
| Trial | e.g. `3` |
| Replicate | e.g. `2` |
| Pressure Setpoint (BAR) | e.g. `12.0` — the commanded value, not min–max |

The pressure set-point is already available as `self._pressure_entry.text()` at experiment start.

---

### Priority 2 — Must have (required for analysis without manual work)

#### 2a. Add AI response columns to master log

Add after the Notes column, before the embedded images:

| Experiment | Trial | Replicate | Pressure SP (BAR) | N Droplets | N Ligaments | Avg Droplet (µm) | D/L Ratio | Confidence (%) |

These values are already in `ai_results.json` inside the run folder — the save function just needs to read them at save time.

If Dennis hasn't run yet when you click Save, these cells get `"N/A"` and can be filled in later (or a re-save button added).

---

### Priority 3 — Should have

#### 3a. Cone angle as a number

Store the computed cone half-angle (in degrees) from `Cone_4.py` as a numeric column in both `run_summary.xlsx` and the master log. Currently only the image is saved.

Requires `Cone_4.py` to return the angle value to the GUI (it may already compute it — needs checking).

---

### Priority 4 — Optional / nice to have

#### 4a. Experiment group folder

Wrap runs in a named experiment folder above the date:

```
LaCie/Experiments/
└── L9-NozzleStudy-May2026/
    └── 2026/05/08/
        └── T03_R2_143022_N1_12.0BAR/
```

Makes it easier to archive entire campaigns. Not strictly required if the Experiment Name is in every Excel row.

#### 4b. Experiment manifest

A single `experiment_manifest.xlsx` at the experiment group level — one row per run, auto-populated at save time. Would serve as a pre-assembled Taguchi results table. Low priority because the master log with the new columns achieves the same thing.

---

## Do You Need a Database?

**No.** For L9/L16 with 2–3 replicates (27–48 runs), a flat Excel master log is sufficient. A database only makes sense at hundreds of runs queried across many experiments. The master log with proper columns is effectively a flat-file database, and pandas can do all the filtering and S/N ratio calculations needed for Taguchi analysis.

---

## Do You Need a New GUI?

**No.** The three new fields (Experiment Name, Trial, Replicate) fit naturally into the existing left panel without restructuring the layout.

---

## Implementation Order (when ready to code)

1. Add Experiment Name + Trial + Replicate fields to left panel
2. Persist Experiment Name via `camera_settings.json`
3. Update folder naming to include `T##_R#_` prefix
4. Update `run_summary.xlsx` Metadata sheet to include new fields
5. Update master log: add new text columns + read `ai_results.json` at save time
6. (Later) Store cone angle as a number

---

## Analysis Workflow (post-experiment)

Once the above is implemented, a Taguchi campaign analysis would look like:

1. Open `master_log.xlsx`, filter by `Experiment Name`
2. Each row is one run with factor levels (Nozzle, Orifice, Pressure SP, Speed, Distance) and response variables (N Droplets, Avg Droplet µm, D/L Ratio, Cone Angle)
3. Load into Minitab / pandas, compute S/N ratios per response, build main effects plots
4. Raw data (pressure traces, images, per-detection JSON) still in run folders for drill-down

---

## Open Questions

- [ ] What are the specific Taguchi factors and levels for the first campaign?
- [ ] Which variables are the response variables? (droplet size, D/L ratio, cone angle, all three?)
- [ ] Does `Cone_4.py` already return a numeric angle, or does it only produce an image?
- [ ] Should replicate auto-increment, or is manual control preferred?
- [ ] Is the experiment group folder (Priority 4a) worth doing before the first campaign?
