# Imaging pipeline reference: from camera to Taguchi report

**What this is.** An exact, step-by-step description of how the shadowgraph measurement works
*as the code stands on 2026-10-07* (repo commit `7ebaa1a` plus this doc), from the camera
recording a video to the numbers in the Taguchi report. It includes the mathematics, worked
examples, every tunable constant with its file and line, what is known to be wrong or unverified,
and the steps needed before the results are publication-grade.

**Who it is for.** Ben, and any AI instance picking this up cold. Read `docs/STATUS.md` first for
what is happening *now*; this doc is *how the machine works*.

**Ground rule.** Where this doc and the code disagree, the code is right and this doc is stale:
fix it here. `docs/definitions.md` (older, still useful for vocabulary) is partly stale in places
listed in §14.

---

## 0. The whole chain on one page

```
 RIG                     CAPTURE (GUI_Clean.py)            DISK (LaCie, per run folder)
 effervescent atomiser   Phantom VEO E-340L, 390 fps,       raw/CINE/recording_HHMMSS.cine
 + backlight + camera    2048x1152, 4 us, 13 s post-trigger run_summary.xlsx (metadata, pressure)
                         Alicat gas flow, syringe motor     master_log.xlsx (one row per run)
          |
          v
 STAGE 1  cine_extract.py      every 10th frame -> 16-bit TIFF (measurement) + 8-bit PNG (model)
 STAGE 2  background           per-pixel temporal median of 40 frames -> background_median.tiff
 STAGE 3  tiled_inference.py   Mask R-CNN "Eden", 800 px tiles, cross-class NMS -> predictions.json
 STAGE 4  measure_run.py       T = I/I_bg; focus gate; half-max sizing -> droplets_0.30/ (D32 ...)
 STAGE 5  classical_liquid.py  classical liquid segmentation -> liquid_0.30/ (atomised fraction)
          (stages 1-5 = process_capture.py + classical_liquid.py, run per run by the batch)
          |
          v
 STAGE 6  Taguchi_Analysis_UI  27 runs -> responses, bootstrap CIs, ANOVA, size bins, GLR,
          (Analyse button)     figures -> taguchi_report.md, taguchi_analysis.xlsx, csv/, odd/
          |
          v
 STAGE 7  companion analyses   pulsing (pulsing/), sizer comparison (comparison_*.md)
```

Two numbers are the headline Taguchi responses: **D32 of in-focus droplets** (Stage 4) and the
**classical atomised area fraction** (Stage 5). Everything else is a secondary response.

---

## 1. The rig and capture

### 1.1 Physical setup (as recorded by the GUI; not all of it is controlled by code)

| item | value on the 2026-10-05 campaign | where it comes from |
|---|---|---|
| fluid | EcoFlex 00-30, **single part** (no curing), density 1070 kg/m³ | GUI Materials tab, `camera_settings.json` |
| gas | nitrogen, density **1.145 kg/m³** (N₂ at 25 °C, matching the Alicat's 25 °C / 1 atm STP) | Materials tab |
| gas flow | 3000 / 6000 / 9000 sccm, Alicat mass-flow controller (COM4) | GUI "Target Flow" |
| liquid flow | syringe driven by a stepper at 4000 / 6000 / 8000 steps/s | GUI "Motor Speed" |
| bubbler | 300 / 600 / 900 rpm; bubbler height 1 mm; orifice 1.2 mm | typed into the GUI and recorded (not driven by this code) |
| lab temperature | 25 °C (Ben, 2026-10-07) | not logged |
| camera | Phantom VEO E-340L at IP 100.100.100.1 | `camera_settings.json` |

**Liquid volume flow** (`GUI_Clean._glr_working`, `GUI_Clean.py:4842`):

```
mL/min = pi * (20.27 mm / 2)^2 * (steps_per_s / 6800 steps/mm) / 1000 * 60
```

Example: 4000 steps/s → 4000/6800 = 0.588 mm/s × 322.7 mm² = 189.8 mm³/s = **11.39 mL/min**
(matches the report's run context). **6800 steps/mm is confirmed by the firmware**
(`src/gui/Pressure_Motor_Portenta.cpp:30`: `((200 * 16) / 2) * 4.25` = 200 steps/rev × 16
microsteps ÷ 2 mm lead × 4.25 gearbox; `driver.microsteps(16)` at `:104`), and the motor speed the
GUI sends is in microsteps/s (`stepper.setMaxSpeed(speed)`). Older notes saying 13,600 were an
arithmetic slip. Still worth one timed syringe displacement to confirm the lead and gearbox
physically (§13, item 14).

**Gas-to-liquid ratio** (a mass ratio; recorded in `run_summary.xlsx`):

```
GLR = (sccm * rho_gas * 1e-3 g/min) / (mL/min * rho_liquid * 1e-3 g/min)
```

Example, T1 (3000 sccm, 4000 steps/s): 3000 × 1.145 / (11.39 × 1070) = 3435 / 12,187 =
**0.2819**.

### 1.2 Camera settings (`src/gui/camera_settings.json`, applied by `PhantomCamera.configure`, `GUI_Clean.py:1067`)

| setting | value | consequence |
|---|---|---|
| resolution | 2048 × 1152 px (sensor windowing, not binning) | field of view 20.48 × 11.52 mm at 10 µm/px |
| frame rate | 390 fps | 2.56 ms between frames |
| exposure | 4 µs | motion blur = v × 4 µs: 1 px at 2.5 m/s |
| pre-trigger | 0 s → forced to 1 frame | cine starts at frame −1 |
| post-trigger | 13 s → 5070 frames | 5071 frames per cine, frame numbers −1 … 5069 |
| scale | 100 px/mm = **10 µm/px** (`px_per_mm`) | the single number every µm depends on (see §13) |
| bit depth | 12-bit data stored in uint16 | values 0–4095; background ~800 |

### 1.3 The capture sequence (GUI)

1. **Start Experiment** (`_start_experiment`, `GUI_Clean.py:6886`) creates the run folder
   `Experiments/YYYY/MM/DD/<HHMMSS>_<flow>sccm_<rpm>rpm_<sps>sps_or<orifice>_bh<height>/`, sets the
   gas flow on the Alicat (serial) and the syringe motor speed and travel on the Portenta, and
   starts logging pressure and gas flow.
2. **Arm** (`_cam_arm`, `:5437`) starts ring-buffer recording on the camera.
3. **Trigger** (`_cam_trigger`, `:5487`; the button or Space) freezes the buffer once the spray is
   steady. The camera keeps 1 pre + 5070 post frames. The GUI records `cam_start` / `cam_end` times
   in the pressure log.
4. The cine is saved over Ethernet to `shadowgraph/raw/CINE/recording_HHMMSS.cine`.
5. **Save** (automatic after the capture, in the background) writes `run_summary.xlsx` (sheet *Metadata*: all run fields, GLR, fluid, gas,
   densities, notes; sheet *Pressure*: `timestamps, pressures, flows_sccm, cam_start_1, cam_end_1`,
   ~4.6 Hz) and appends a row to `Experiments/Logs/master_log.xlsx`.

6. **AI chain** (if "Run AI analysis" is ticked; `_run_ai_chain`): `process_capture(stride from the
   AI-stride box, score 0.30, images "extremes", sharpness_rule=True)` then
   `process_capture.run_classical(..., sharpness_rule=True)`. **Since 2026-10-08 the GUI measures at
   sizer 2.2.0 and runs the classical stage**, so a capture comes out with `droplets_0.30/` and
   `liquid_0.30/`, both 2.2.0, ready for the app's Analyse. The headline atomised fraction and the
   master log's `Atomised (%)` are the classical figure (earlier rows hold the model-only one), and
   the Extremes tab shows the classical renders (§7). The Taguchi app's batch also defaults to
   2.2.0 (`RunSettings.sharpness_rule = True`), so the two agree.

**Campaign standard capture** (`GUI_Clean.STANDARD_CAPTURE`, 2026-10-08): 390 fps, 4 µs,
2048 × 1152, pre-trigger 0 s, post-trigger 13 s, AI stride 10, AI analysis on. These are the widget
defaults, and **Start Experiment checks the screen against them** and offers "Use standard
settings / Keep mine / Cancel" if anything differs.

The `.cine` is the **only irreplaceable file**; everything in stages 1–7 can be regenerated from it.

---

## 2. Run folder layout (what each stage writes)

```
<run>/
  run_summary.xlsx                          capture metadata + pressure/flow log
  cone/                                     cone webcam image (not used in analysis)
  shadowgraph/raw/CINE/recording_*.cine     the archival source, alone
  shadowgraph/raw/frames/16bit/*.tiff       Stage 1: native camera counts, every 10th frame
  shadowgraph/raw/frames/8bit/*.png         Stage 1: pinned-window render, what the model sees
  shadowgraph/raw/instances.json            Stage 1: COCO image manifest (id <-> frame name)
  shadowgraph/raw/extraction_metadata.json  Stage 1: fps, stride, frame numbers, window
  shadowgraph/raw/background_median.tiff    Stage 2: float32 per-pixel median
  shadowgraph/analysis/predictions.json     Stage 3: every detection with score >= 0.05
  shadowgraph/analysis/droplets_0.30/       Stage 4: summary.json, per_frame.csv,
                                            droplet_sizes.csv, object_areas.csv, extreme PNGs
  shadowgraph/analysis/liquid_0.30/         Stage 5: classical_summary.json,
                                            classical_per_frame.csv, classical_components.csv
  shadowgraph/analysis/_sizer2.1.0/         2026-10-07 only: the 2.1.0 results moved aside
                                            when the runs were re-measured at 2.2.0
```

Frame names are `frame_<index>_n<cine frame number>`, e.g. `frame_0001_n9`. `0.30` in folder names
is the score threshold. Older runs (before 2026-10-05) use `measurement_0.30/` and
`classical_0.30/`; every reader accepts both.

---

## 3. Stage 1: frame extraction (`AI/Real_Data_Code/cine_extract.py`)

**Which frames.** `range(first_frame, last_frame + 1, stride)` with stride 10
(`frame_numbers`, `:115`): frames −1, 9, 19, … 5069 → **508 frames**, one every 25.6 ms (39 Hz).
Phantom frame numbers can be negative (pre-trigger); always walk first..last, never
`range(total)`.

**16-bit TIFF.** The raw camera counts, unchanged (`frame.astype(uint16)`). All measurement uses
these.

**8-bit PNG.** A fixed linear window, identical for every frame of every run:

```
pixel_8bit = clip( (raw - 27) / (876 - 27) * 255 , 0, 255 )      PINNED_WINDOW = (27, 876), :107
```

The window was taken from the training composites (`05_dataset_v3`), so the model sees new data on
the same intensity scale it was trained on. Example: a background pixel at raw 800 →
(800 − 27)/849 × 255 = **232**; a droplet core at raw 240 (T ≈ 0.30) → **64**.
`check_window_fit` warns if > 2% of sampled pixels clip at either end.

**Manifest.** `instances.json` lists each frame as a COCO image (id, file name, 2048 × 1152).
`extraction_metadata.json` records fps (390), stride, frame list, total frames (5071) and a
`limited` flag (a `--limit` extraction is refused for reuse).

---

## 4. Stage 2: background (`process_capture.build_background` → `extract_candidates.build_temporal_background`, `:184`)

```
step = max(1, N_frames // 40);   sample = frames[::step][:40]
I_bg(x, y) = median over the 40 sampled 16-bit frames of I(x, y)
```

Spray is transient, so at any pixel most sampled frames are empty and the median lands on the empty
value. Static things (illumination gradient, vignette, dust on the window or sensor) survive the
median and therefore divide out in Stage 4. Per run, never shared between runs.

**Consequence worth knowing:** a dirt speck present in fewer than half of the sampled frames is *not*
in the median, so it can be detected as a droplet. 2026-10-07 found ~5 such fixed spots detected as
40–60 µm droplets in 20–70% of frames in every 10/05 run (§12).

---

## 5. Stage 3: detection (`AI/Real_Data_Code/tiled_inference.py`)

**Model.** Detectron2 Mask R-CNN, ResNet-50 FPN (COCO 3x init), 3 classes: **droplet (1),
filament (2), blob (3)**. Production model **"Eden"** (= v3, `training_2026_09_25_15_20_37`,
checkpoint iteration 19000, chosen on composite-validation AP; benchmark segm AP 66.8). Trained only
on **composites** of real objects pasted multiplicatively in transmission onto real empty frames
(`05_dataset_v3`). `config.yaml` travels with the weights and pins the anchors and the 800 px input.

**Tiling, never resizing.** The model expects 800 × 800 input. A 2048 × 1152 frame is cut into
evenly spaced, overlapping 800 px tiles (`tile_offsets`, `:141`):

```
n = ceil((size - 800) / (800 - 150)) + 1;   step = (size - 800) / (n - 1)
x: 2048 px -> n = 3, offsets 0 / 624 / 1248, overlap 176 px
y: 1152 px -> n = 2, offsets 0 / 352,        overlap 448 px          => 6 tiles per frame
```

Each tile goes through the model at scale 1.0 on the **8-bit** frame. Detections are mapped back to
frame coordinates.

**Seams.** A detection whose box is within 2 px of a tile edge that is *not* a frame edge is flagged
`truncated` (`_collect`, `:313`).

**Merging** (`_merge`, `:396`): **cross-class NMS on mask IoU**. Order detections by
`score + (1 if not truncated else 0)` (whole objects beat seam fragments), then for each kept
detection suppress any other with mask IoU ≥ 0.5, or that is ≥ 50% contained in it *and* at least
0.2× its area (a duplicate partial, not a small droplet sitting on a big filament).

**Rescue pass** (`_rescue_truncated`, `:476`): every still-truncated detection gets one extra
800 px tile centred on it, and the merge is repeated. Objects larger than a tile stay truncated.

**Output.** `predictions.json`: one COCO record per detection with `score >= 0.05` (inference
floor; the measurement threshold is applied later), with `category_id`, `bbox`, `score`, `area`
(mask pixels), `segmentation` (frame-sized RLE), `segmentation_crop` + `crop_xy` (the same mask
over its own box: much faster to decode), and `truncated`.

---

## 6. Stage 4: droplet measurement (`AI/Real_Data_Code/measure_run.py`)

### 6.1 Inputs and filtering

- Detections kept: `score >= 0.30` **and** `not truncated` (`:684`). Truncated droplets are
  excluded from sizing (a clipped mask has the wrong diameter).
- Transmission per frame, on the 16-bit data:

```
T(x, y) = I(x, y) / max(I_bg(x, y), 1)          1 = clear background; 0.3 = 70% of light blocked
```

Division (not subtraction) because shadowgraph attenuation is multiplicative, and it cancels the
illumination field pixel by pixel.

### 6.2 Per droplet: `measure_droplet()` (`:292`), the one place focus and size are decided

Work on a crop around the detection's box padded by 7 px (`DILATE_PX + 2`).

**(a) Core transmission** (`droplet_core`, `:166`, estimator "robust"):

```
interior = mask eroded by a 3x3 kernel
if interior is empty:  core = min(T over mask)                       (droplets under ~4-6 px)
else:                  k = max(3, round(0.05 * n_interior))
                       core = mean of the k darkest interior T values
```

The interior restriction stops tiny droplets being penalised: their every pixel straddles the edge.

**(b) Focus gate:** `in_focus = core <= 0.70` (`--focus-max`). Out-of-focus droplets are kept and
counted, but excluded from every size statistic.

**(c) Size.** Model equivalent diameter `d_model = 2 * sqrt(area_px / pi) * 10 um/px`
(`equiv_um`, `:92`).

```
if not in_focus:               area = model mask area           method "model_out_of_focus"
elif d_model < 40 um:          area = model mask area           method "model_below_split"
else:  half-max sizing (halfmax_area, :224):
       edge   = (core + 1) / 2
       search = model mask dilated by 5 px (11x11 kernel)
       grown  = search AND (T < edge)
       comp   = connected component (8-conn) of grown containing the darkest mask pixel
       if |comp| >= 4 px:  area = |comp|   method "halfmax" ("model_degenerate" if |comp| == mask area)
       else:               area = model mask area, method "model_no_component"
d = 2 * sqrt(area / pi) * 10 um
```

Why half-max: for a symmetric blur, the 50% crossing between the object's core and background stays
at the true edge as focus changes. That holds only if the core reaches its true opacity, which
fails for small objects; hence the 40 µm split, below which the model mask is used. **Whether
half-max is the true edge for these transparent droplets has never been measured** (§13).

**(d) Sizer 2.2.0 sharpness rule** (only with `--sharpness-rule`; **off by default**). For an
in-focus droplet with `d_model >= 50 um`, compute on a half-max component grown from the *single
darkest pixel* (`sharpness_metrics`, `:266`):

```
fill_ratio      = |comp| / (pi * r_enc^2)        r_enc = minimum enclosing circle of comp's contour
extinction_conc = sum_{comp} (1 - T) / sum_{search} (1 - T)
moved out of focus if fill_ratio < 0.85 OR extinction_conc < 0.60      (NaN never fails)
```

For an ellipse `fill_ratio = b/a`, so 0.85 rejects any droplet with aspect ratio > ~1.18. The sized
area and mask are kept, so counts and the atomised fraction cannot change; only D32 membership
moves. Runs measured with it record `sizer_version 2.2.0`, without it `2.1.0`.

**Worked example (illustrative numbers).** A detection with model mask 70 px → d_model = 2√(70/π)
× 10 = 94.4 µm. Interior 48 px → k = max(3, round(2.4)) = 3; the three darkest interior values
0.28, 0.30, 0.31 → core = 0.297 ≤ 0.70, in focus. Edge = (0.297 + 1)/2 = 0.648. Growing inside the
5 px-dilated mask, the component below 0.648 has 61 px → d = 2√(61/π) × 10 = **88.1 µm** (the
sizer reads 6.7% smaller than the model mask, typical of the ~0.86× area ratio seen across runs).

### 6.3 Per frame and pooled outputs

Per frame (`per_frame.csv`): in-focus and out-of-focus droplet counts, filament and blob counts,
frame D32, and a **model-only** atomised fraction:

```
atomised_model = |U droplet masks| / (|U droplet| + |U filament| + |U blob|) * 100
```

(unions within class, then summed: a droplet overlapping a filament is counted in both. This
figure is **reference only**; the quoted one is Stage 5.)

Pooled over the run (`summary.json`), never an average of per-frame values:

```
D32 = sum(d^3) / sum(d^2)        over every in-focus droplet in the run
```

Example with diameters 40, 60, 100 µm: Σd³ = 64,000 + 216,000 + 1,000,000 = 1,280,000;
Σd² = 1600 + 3600 + 10,000 = 15,200; **D32 = 84.2 µm** (the arithmetic mean is 66.7 µm). The
largest droplet carries 78% of Σd³.

Also: mean, SD (ddof = 1), min and max in-focus diameter; `diameter_method_counts`;
`sharpness_reclassified`; `d32_extreme_frames` / `atomised_extreme_frames` (extreme-frame PNGs:
green = in focus, magenta = out of focus).

**Bootstrap CI** (`boot_ci`, `:368`; 2000 resamples, seed 0, percentile 2.5/97.5). Resample
**frames** with replacement; each frame contributes its (Σd³, Σd²) pair, so a replicate D32 is
Σ(Σd³)/Σ(Σd²) over the resampled frames. Only every `ci_stride`-th frame is resampled;
`ci_stride = max(1, round(0.0205 s * fps / stride))` (`process_capture.auto_ci_stride`) = round(0.8)
= **1** at 390 fps / stride 10. ⚠ That assumes frames 25.6 ms apart are independent; at low GLR they
are not (§12).

**Edge case:** frames with no detection at score ≥ 0.30 are skipped in Stage 4 (the loop runs over
frames that have detections). All 508 frames of every 10/05 run had detections, so it did not bite.

`droplet_sizes.csv`: one row per droplet: `frame, diameter_um (sized), in_focus`.
`object_areas.csv`: filament and blob detections (instances, not whole objects).

---

## 7. Stage 5: classical liquid and the atomised fraction (`AI/Real_Data_Code/classical_liquid.py`)

The model under-reads un-atomised liquid (a 28 × 28 mask head cannot draw a 100:1 thread; objects
are cut at tile seams), so the denominator is re-measured classically on the whole frame.

Detections used: all classes, `score >= 0.30`, **truncated included** (a union reassembles a split
object). Per frame (`measure_frame`, `:265`):

**(a) Classical liquid mask** (`hysteresis`, `:98`):

```
grow  = T < 0.95                                (ceiling: bounds growth, never an edge)
components of grow (8-connected) that contain any pixel with T < 0.70 are "seeded"
for each seeded component C:  keep pixels of C with T < (min_C(T) + 1) / 2   (its own half-max)
liquid = union of kept pixels, then drop connected pieces smaller than 20 px
```

**(b) Droplet mask** (`model_masks`, `:204`): for every droplet detection, its half-max component
from `measure_droplet` where one exists (in focus, d ≥ 40 µm, component found), otherwise the
model mask. Union over all droplets, in and out of focus.

**(c) Out-of-focus un-atomised:** union of model filament / blob masks whose minimum T > 0.70 (the
classical seed cannot reach them by construction).

**(d) Per-frame atomised fraction:**

```
total       = liquid U droplets U oof_unatomised        (one union: nothing counted twice)
droplet_px  = |droplets|;   total_px = |total|;   unatomised_px = total_px - droplet_px
atomised %  = 100 * droplet_px / total_px
```

**(e) Pooled over the run** (`classical_summary.json` → `atomised_pct_pooled`, the quoted figure):

```
atomised % = 100 * sum_frames(droplet_px) / sum_frames(total_px)
```

Example: three frames with (droplet_px, total_px) = (1500, 20,000), (3000, 10,000), (500, 40,000):
pooled = 5000 / 70,000 = **7.14%**; the mean of the per-frame ratios would be 15.0%, dominated by
the sparse frame. Run `090432` (T1) reads 7.412%.

It also writes `classical_components.csv` (each un-atomised component's area, after removing
components ≥ 50% covered by a detected droplet and ≤ 100 px across) and, in extremes mode, up to
**4 extreme-frame images** in `extreme_images/`: the lowest/highest classical atomised fraction and
(since 2026-10-08) the lowest/highest per-frame D32, picked by the same rule as `measure_run`
(raw extremes among frames with an in-focus droplet, so the same frames). Rendering: un-atomised
liquid filled orange, droplets ringed green (in focus) or magenta (out of focus, including droplets
moved by the 2.2.0 rule). `classical_summary.json` records both `atomised_extreme_frames` (with
droplet count, un-atomised px and pieces) and `d32_extreme_frames`. The raw lowest-D32 frame is
often a sparse frame (e.g. 4 droplets): read the droplet count in the caption.

This fraction is **projected area**, at one axial position, of an instantaneous snapshot (not
volume, not flux): see §13.

---

## 8. Batch orchestration

- `process_capture.process_capture()` runs stages 1–4 for one cine (subprocesses, so each stage's
  CLI is the only interface). `reuse=True` skips 1–3 when `can_reuse()` finds a complete analysis
  at the same stride made after the newest model weights.
- `process_capture.run_classical()` runs Stage 5 exactly as the batch does (`--root`, `--out-dir`,
  `--score-thresh`, `--images-mode`, and `--sharpness-rule` / `--no-sharpness-rule`, always
  explicit) and adds a frame-bootstrap CI of the
  pooled classical fraction at the run's `ci_stride`. The GUI uses it.
- `batch_runs.py` loops runs: `process_capture` then `classical_liquid.py --images-mode extremes`.
- **Sizer version (2026-10-08): 2.2.0 everywhere**, by Ben's decision. The capture GUI, the
  Taguchi app's batch and the command-line scripts (`measure_run.py`, `classical_liquid.py`,
  `process_capture.py`, `batch_runs.py`) all default to it; `--no-sharpness-rule` /
  `sharpness_rule=False` gives 2.1.0. Callers pass the flag explicitly both ways, so a Taguchi app
  job saved before 2026-10-08 still resumes at 2.1.0.
- **Taguchi_Analysis_UI** (`src/ai/Taguchi_Analysis_UI/`) is the production front end: a
  detached, resumable worker (`worker.py`) runs the same chain over a selection of runs and
  records timings; the Taguchi tab runs Stage 6. Plan and build record:
  `docs/TAGUCHI_ANALYSIS_UI_PLAN.md`; Windows procedure: `docs/TAGUCHI_WINDOWS_RUN_SHEET.md`.
- Inference needs a CUDA PC (home PC RTX 5060 Ti, Detectron conda env). Stages 4–6 run on the Mac
  (`phantom` env) in ~1.5 min per run.

---

## 9. Stage 6: Taguchi analysis (Analyse button → `publish.publish()`)

**Reading a run** (`taguchi_analysis.load_run`): in-focus diameters per frame from
`droplet_sizes.csv`; `droplet_px`, `total_liquid_px` per frame from `classical_per_frame.csv`. It
recomputes D32 and the atomised fraction and **refuses** the run if they disagree with the
summaries (> 0.02 µm, > 0.002 points). The analysis refuses mixed `sizer_version`s.

**Responses** (`taguchi_analysis.RESPONSES`; all from the same frames):

| response | definition | better |
|---|---|---|
| D32 in-focus | Σd³/Σd² over in-focus droplets | smaller |
| Atomised fraction, classical | 100 Σdroplet_px / Σtotal_px | larger |
| Mean / median diameter | of in-focus droplet diameters | smaller |
| D90 by count | 90th percentile of in-focus diameters | smaller |
| In-focus droplets per frame | in-focus count / frames | larger |
| Droplet-count CV | std / mean of per-frame in-focus counts | smaller |
| Liquid-area CV | std / mean of per-frame total_liquid_px | smaller |
| Frames near-empty | % of frames with < 5% of the run's mean in-focus count | smaller |

**Per-run CIs:** frame bootstrap (2000, seed 0) at the run's `ci_stride`, centred on the
all-frame estimate. They describe measurement noise within one run, not run-to-run variation.

**Design** (`design.py`): factors detected from the run names / workbooks (gas flow, bubbler RPM,
silicone steps/s); replicates detected two ways (Notes and levels) and cross-checked; balance,
orthogonality and estimability reported.

**ANOVA** (`stats.py`): main-effects model, sum-to-zero coding, Type II sums of squares (equal to
the classic n Σ(ȳ_level − ȳ)² for a balanced design). Error term = **pure error** from replicates:

```
SS_pe = sum over runs (y - condition mean)^2,   df_pe = N - conditions = 27 - 9 = 18
F = (SS_factor / df_factor) / (SS_pe / df_pe),  p from F(df_factor, 18)
lack of fit = residual of the main-effects model beyond pure error (df 2): significant => interactions
contribution % = SS / SS_total;   pooled contribution = (SS - df * MS_pe) / SS_total
```

Benjamini–Hochberg q-values across all factor tests (9 responses × 3 factors = 27). S/N per
condition: smaller-is-better −10 log₁₀(mean y²), larger-is-better −10 log₁₀(mean 1/y²). Replicate
outliers: |y − condition mean| / √MS_pe > 3. Responses taking < 4 distinct values are flagged as
quantised.

**Size bins** (`size_bins.py`): in-focus diameters, edges 0, 25, … 200 µm and > 200 µm; % by count
and % by volume (Σd³); a condition pools its replicates' droplets (one population).

**GLR** (`covariates.py`): treated as a covariate, not a factor (it is built from gas and liquid
flow, so it is aliased with them): correlation and log–log power-law exponent per response.

**Deliverables:** `taguchi_report.md`, `taguchi_analysis.xlsx`, `figures/` (main effects,
contributions, per run, S/N, GLR, size spread by count and volume), optional `csv/` and `odd/`
(odd-frame pack), and provenance (repo revision, sizer version, thresholds, bootstrap, bins).

---

## 10. Stage 7: companion analyses (not produced by Analyse)

- **Spray pulsing** (`Taguchi/9x3 Taguchi Repeats/pulsing/pulsing_analysis.py`): Welch spectra
  (256-sample segments at 39 Hz) of per-frame droplet count and atomised fraction; "slow share" =
  variance fraction between 0.1 and 2 Hz (pure noise ≈ 10%); lag correlations; pressure/flow from
  `run_summary.xlsx` within the camera window, aligned assuming the cine starts at `cam_start`.
- **Sizer 2.1.0 vs 2.2.0** (`Taguchi/9x3 Taguchi Repeats (sizer 2.2.0)/comparison_2.1.0_vs_2.2.0.md`
  and `sharpness_review/`).

---

## 11. Where the 2026-10-05 data stands right now

| what | where | sizer |
|---|---|---|
| 27 runs' current results | `<run>/shadowgraph/analysis/droplets_0.30`, `liquid_0.30` | **2.2.0** |
| 27 runs' original results | `<run>/shadowgraph/analysis/_sizer2.1.0/` | 2.1.0 |
| Taguchi analysis, default | `Experiments/Taguchi/9x3 Taguchi Repeats/` | 2.1.0 |
| Taguchi analysis, rule on | `Experiments/Taguchi/9x3 Taguchi Repeats (sizer 2.2.0)/` | 2.2.0 |
| first L9 (2026-10-01) | `Experiments/Taguchi/First Taguchi Trial (RPM, SCCM, Silicone Flow)/` | 2.0.0 |

The default is 2.2.0 everywhere since 2026-10-08. To re-run the 2.1.0 analysis, the `_sizer2.1.0` folders must be moved
back first (the app reads only `droplets_0.30` / `liquid_0.30`).

---

## 12. Known limitations, biases and bugs (consolidated)

**Measurement physics (affect absolute values; most cancel when ranking runs)**

1. **No physical calibration of edge, focus or depth of field.** The half-max edge, the
   `core ≤ 0.70` gate and the 2.2.0 thresholds are conventions or fitted to eye labels. Ben's eye
   draws ~30–35% larger diameters than half-max (51 droplets, 2026-10-02). Nothing yet says which
   is true.
2. **Size-dependent depth of field is not corrected.** Large droplets are accepted from a deeper
   slab, so counts and D32 are biased towards large sizes. Same for droplets cut by the frame
   border or tile seams (excluded from sizing).
3. **Small droplets.** Below ~50 µm a droplet is ≤ 5 px and sits on the pixel lattice; recall at
   0–50 µm is ~75% on the benchmark. D32 is insensitive to them; counts, D10 and the size bins
   below 50 µm are not.
4. **Area-equivalent diameter assumes spheres.** Deformed fragments (commoner at high gas flow)
   get a sphere's volume. 2.2.0 excludes them instead, which biases D32 against gas flow (see
   `docs/STATUS.md`, the 2026-10-07 gradient diagnosis).
5. **The 200 µm droplet ceiling (a settled design decision) is not enforced** in the code. Droplets
   > 200 µm carry 3–5% of in-focus volume and lower D32 by ~2 µm when removed (ranking unchanged).
6. **Atomised fraction = projected area at one axial station, in snapshots.** Not volume, not
   flux; depends on where the field of view is relative to the nozzle.
7. **Classical liquid segmentation is not validated** against hand labels; the 0.70 seed and 0.95
   ceiling are reasoned, not calibrated.

**Statistics**

8. **Frames are not independent at low GLR.** Droplet-count correlation between frames 25.6 ms apart
   is 0.62 at 3000 sccm (0.18 at 9000), so per-run bootstrap CIs at `ci_stride` 1 are too narrow
   there. The ANOVA (pure error) is unaffected.
9. **Bubbler RPM is confounded with time of day** in the 10/05 campaign (run in order T1..T9,
   replicates back to back). No drift found in lighting, window dirt, fluid or temperature, but only
   a randomised run order settles it. Back-to-back replicates also make pure error a repeatability
   (not reproducibility) estimate.

**Detection**

10. **Static specks detected as droplets** (~5 fixed spots, 40–60 µm, 20–70% of frames, every 10/05
    run). Small effect on D32; inflates droplets per frame by a few.
11. Detection performance on real frames is known only from the 20-frame benchmark (older runs,
    lower gas flow). **Not measured at 9000 sccm**, where frames are 3× denser.

**Code**

12. `measure_run`'s model-only atomised fraction and `score_v2.py` double-count cross-class
    overlap (the quoted classical figure does not).
13. Taguchi app: a failed log write kills the worker; a worker crash is reported as a contract
    violation; the selected-runs summary doesn't refresh during a batch; 17 Windows-only test
    failures (test-side); 3 Mac test failures assume the 10/05 runs are unmeasured.
14. `GUI_Clean.py` still creates `Brightest_Frame`; `requirements.txt` is stale; tracked `.pyc` files.
15. Hardware: the LaCie drops off USB on the home PC (exFAT, no journal: eject before unplugging,
    Scan and repair after any disconnect).

---

## 13. Next steps to make this publication-grade

Ordered by value. Items 1–5 are the minimum for absolute sizes to stand up in a paper; ranking
results can be published sooner if items 9–11 are stated as limitations.

| # | step | what it settles | how / cost |
|---|---|---|---|
| 1 | **Verify the scale (10 µm/px) and distortion** with a certified dot grid at the spray plane | every µm in the project | PS20 slide's 0.5 mm-pitch dot array; minutes once the slide exists |
| 2 | **Dot-reticle through-focus calibration** | the true edge threshold, a calibrated focus criterion, DOF(d) | `docs/DROPLET_MEASUREMENT_METHOD.md` (shopping list and procedure); ~1 day |
| 3 | **Transparent-bead check** (bead sandwich, then falling beads) | whether the dot calibration transfers to transparent droplets | same doc |
| 4 | **DOF and border/seam weighting** in the size statistics | unbiased size distributions and D32 | code, after 2 |
| 5 | **Replace reject-by-shape with classify-by-shape; size by volume** (spheroids; ligaments from skeletons); report Dv50 beside D32; enforce or justify the droplet/blob boundary | non-spherical fragments measured, not discarded | code |
| 6 | **Hand-label frames from the actual conditions, including 9000 sccm** (blind, with a control group: see memory `blind-labelling-needs-a-control`) | detection recall/precision per condition and size; whether detection bias tracks gas flow | ~1–2 sittings |
| 7 | **Validate the classical liquid segmentation** against hand-labelled liquid masks | the atomised fraction's accuracy | labelling + scoring script |
| 8 | **Measure velocity once** (windowed high-fps capture, PTV) | motion blur bound at 4 µs, decorrelation time, whether flux weighting is needed | one capture + analysis |
| 9 | **Honest CIs:** block bootstrap or per-run `ci_stride` from the measured autocorrelation | per-run intervals | code; data already exist (pulsing analysis) |
| 10 | **Randomised run order and replicates across days** in the next campaign; one RPM test (alternate 300/900 at fixed gas/liquid flow) | the RPM vs time-of-day confound; reproducibility | rig time |
| 11 | **Fix and record the axial measurement station** (distance from the orifice); ideally 2–3 stations on one condition | interpretability of the atomised fraction | rig + metadata field |
| 12 | **Mask static specks** using the background (reject detections on static dark features) | droplets per frame bias | code |
| 13 | **Uncertainty budget** combining calibration, detection and sampling | the error bars a paper needs | after 2–9 |
| 14 | **Confirm the syringe calibration physically** (firmware says 6800 steps/mm: time a known displacement to confirm the 2 mm lead and 4.25 gearbox); confirm the Alicat is set to N₂ and 25 °C STP; fix the firmware travel check (986,000 steps = 145 mm, should be 72.5 × 6800 = 493,000) | liquid flow, GLR, syringe safety | 15 min + reflash |
| 15 | **Freeze and tag the code** for each published dataset (git tag, `sizer_version`, calibration file version), and keep the provenance tables | reproducibility | habit |
| 16 | **Cross-check against an independent instrument** (e.g. laser diffraction) on a few conditions, if available | external validity | if the department has one |

---

## 14. Notes for another AI instance

- **Read first:** `CLAUDE.md` → `docs/STATUS.md` → this doc. History and evidence:
  `docs/archive/HANDOFF_real_data_pipeline_LEGACY.md` (frozen; cite by section heading).
- **Ben's working style:** phase-gated; do the phase asked, then stop and report. Findings that
  change the plan are reported, not silently absorbed. Give exact paste-able commands with absolute
  paths and the real interpreter.
- **Never modify raw data.** Analyses write to their own output folders. Before any re-measure,
  move or copy `droplets_0.30/` and `liquid_0.30/` aside (re-measure overwrites in place).
- **Interpreters:** Mac `/Users/benschofield/anaconda3/envs/phantom/bin/python3` (no torch);
  home PC `C:\Users\BenSc\anaconda3\envs\Detectron\python.exe` (torch + detectron2, CUDA);
  lab PC system Python 3.11.
- **Paths:** LaCie at `/Volumes/LaCie` (Mac) or `D:` (home PC). Runs:
  `Experiments/YYYY/MM/DD/<run>/`. Campaign outputs: `Experiments/Taguchi/<campaign>/`. The first
  L9's folder on disk is "First Taguchi Trial (RPM, SCCM, Silicone Flow)", not what Ben calls it.
- **Versions matter:** never mix `sizer_version`s in one analysis; bump `SIZER_VERSION` for any
  change that moves a reported number, and record new provenance fields.
- **Tests:** `/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m pytest
  /Users/benschofield/Documents/GitHub/HPATR/src/ai/Taguchi_Analysis_UI/tests -q` (618 pass, 3
  known data-state failures on 2026-10-07).
- **Stale statements in `docs/definitions.md`:** t_min is now the robust interior core, not the
  single darkest pixel; the quoted atomised fraction is the classical one (Stage 5), not
  `measure_run`'s; current frames are 2048 × 1152 (20.5 × 11.5 mm), not the 2560 × 1600 sensor;
  "D32 is the primary response, atomised fraction weak" predates the classical fraction and the
  replicated design (both are now strongly resolved).

---

## Appendix A: every tunable constant

| constant | value | file:line | role |
|---|---|---|---|
| `UM_PER_PX` | 10.0 | `measure_run.py:74` | scale |
| `PINNED_WINDOW` | (27, 876) | `cine_extract.py:107` | 8-bit render for the model |
| stride | 10 | `process_capture.py:60` | every 10th frame |
| `BG_FRAMES` | 40 | `process_capture.py:61` | background median sample |
| `DECORRELATION_S` | 0.0205 s | `process_capture.py:64` | sets `ci_stride` (inferred, not measured) |
| `TILE` / `MIN_OVERLAP` | 800 / 150 px | `tiled_inference.py:62-63` | tiling |
| `EDGE_MARGIN` | 2 px | `tiled_inference.py:64` | seam truncation flag |
| `NMS_IOU` | 0.5 | `tiled_inference.py:65` | cross-class mask NMS |
| `CONTAIN_FRAC` / `CONTAIN_MIN_RATIO` | 0.5 / 0.2 | `tiled_inference.py:78-79` | duplicate-partial suppression |
| inference score floor | 0.05 | `tiled_inference.py:589` | written to predictions.json |
| `DEFAULT_SCORE_THRESH` | 0.30 | `process_capture.py:59` | measurement threshold |
| `--focus-max` | 0.70 | `measure_run.py` CLI | in-focus gate on the core |
| `CORE_MIN_PX` / `CORE_FRAC` | 3 / 0.05 | `measure_run.py:162-163` | robust core |
| `SPLIT_UM` | 40 µm | `measure_run.py:160` | half-max sizing threshold |
| `DILATE_PX` | 5 px | `measure_run.py:161` | half-max search region |
| `SHARPNESS_SPLIT_UM` | 50 µm | `measure_run.py:257` | 2.2.0 rule applies above |
| `FILL_RATIO_MIN` / `EXTINCTION_CONC_MIN` | 0.85 / 0.60 | `measure_run.py:258-259` | 2.2.0 rule |
| `SIZER_VERSION` | "2.1.0" ("2.2.0" with the rule) | `measure_run.py:158-159` | provenance guard |
| `SEED_THR` / `CEILING_THR` | 0.70 / 0.95 | `classical_liquid.py:91-92` | classical liquid hysteresis |
| `MIN_AREA` | 20 px | `classical_liquid.py:93` | smallest liquid piece kept |
| `DROPLET_COVER` / `DROPLET_MAX_EXTENT` | 0.50 / 100 px | `classical_liquid.py:94-95` | component size distribution only |
| bootstrap | 2000, seed 0 | `measure_run.py`, `taguchi_analysis.py:60-61` | CIs |
| `EMPTY_FRAC` | 0.05 | `taguchi_analysis.py:127` | near-empty frame |
| `MIN_DISTINCT` | 4 | `taguchi_analysis.py:124` | quantised-response flag |
| size bins | 25 µm to 200 µm + open | `size_bins.py:28-29` | report bins |
