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

Three numbers are the headline responses (Taguchi and response surface): **D32 of in-focus droplets**
and their **mean diameter** (D10; Stage 4; mean diameter promoted to headline by Ben, 2026-10-11) and the
**classical atomised area fraction** (Stage 5). Everything else is a secondary response, still analysed
in full. The response-surface analysis also leads with atomised liquid flow and droplet-count CV.

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
                                            droplet_sizes.csv, object_areas.csv, extreme PNGs,
                                            extreme_frames_more/ (PNGs + index.json/csv)
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

**(d) Sizer 2.2.0 sharpness rule** (**on by default since 2026-10-08**; `--no-sharpness-rule` gives 2.1.0). For an
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
frame D32, a **model-only** atomised fraction and (last column, since 2026-10-13)
`mean_d_in_focus_um`, the mean of that frame's in-focus `droplet_sizes.csv` diameters:

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

**More extreme frames** (2026-10-13, Ben's request; `pick_more_extremes`): the frame with the
**most in-focus droplets**, the **most droplets in total** (in + out of focus), and the **largest**
and **smallest mean in-focus diameter**, the last two only among frames with at least **half the
run's median in-focus count per frame, never fewer than 10** (`mean_floor`, `MIN_DROPLETS_FOR_MEAN`;
Ben, 2026-10-13: a flat 10 picked thin frames whose mean swings by chance, e.g. 57.9 um from 17
droplets on 130918, where a typical frame has 54; with fewer than 2 such frames both are left out and
`note` says why; the floor used is written as `min_droplets_for_mean`). Ties go to the first
frame. They are drawn exactly as the other extremes (`render_frame`, same caption: that frame's D32
and **model-only** atomised %) into `droplets_<thr>/extreme_frames_more/<frame>.png`, one PNG per
distinct frame, with `index.json`:

```
{"schema": 1, "min_droplets_for_mean": 10, "note": "",
 "frames": [{"key": "most_in_focus", "label": "Most in-focus droplets", "frame": "frame_0483_n4829",
             "image": "frame_0483_n4829.png", "value": 204, "unit": "in-focus droplets",
             "droplets_in_focus": 204, "droplets_total": 439, "mean_d_um": 37.58, "d32_um": 53.42,
             "atomised_pct": 31.73}, ...]}
```

keys / labels / units: `most_in_focus` / Most in-focus droplets / in-focus droplets;
`most_total` / Most droplets in total / droplets; `mean_d_highest` / Largest mean diameter /
um mean (in focus); `mean_d_lowest` / Smallest mean diameter / um mean (in focus). `index.csv` holds the
same rows, and `summary.json` carries the list as `more_extreme_frames`. The folder is written in
every image mode (`--images all` copies the flat PNGs; no images: `index.json` with `"image": null`).
⚠ With a floor of 10 the mean-diameter extremes are usually **sparse** frames: on the CCD day the
chosen frame had a median of 22-23 in-focus droplets, below half the run's median frame in 16-21 of
33 runs. Read them as "what a sparse frame looks like", like the raw D32 extremes.

**Back-fill without the model** (`render_more_extremes.py <run or folder of runs> [--thr 0.30]
[--dry-run] [--force]`): picks the frames from the run's own `per_frame.csv` and `droplet_sizes.csv`
with the same function, re-measures only those frames from `predictions.json` + 16-bit frames +
background with measure_run's own per-frame code (`measure_frame`) and the run's provenance, and
**refuses the run** unless each frame's in-focus / out-of-focus counts, D32, atomised % and mean
diameter match its recorded row. Writes only `extreme_frames_more/` (via `.partial/` and a rename).
Done for the 33 CCD runs on 2026-10-13: 33/33 passed the gate; ~3.5 s per run on the Mac.

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

**Liquid stage 2.3.0 (2026-10-13): drops on the window, and volume.** `classical_summary.json` →
`provenance.liquid_version`. Two passes: pass 1 measures every frame and builds a per-pixel persistence
map of un-atomised liquid; pass 2 recomputes each frame's areas with the window mask taken out of
numerator and denominator.
- **Route A (a drop lands mid-run, so it is not in the background median):** a piece un-atomised in
  ≥ 20% of frames (`--window-p`), ≤ 400 px across, aspect ≤ 3, flat-topped (≥ 60% within 70% of its peak
  persistence: a drop on the glass sits still, a jet wobbles) is masked (grown 3 px) in every frame;
  `classical_summary.window` lists the objects and the masked area.
- **Route B (a drop present all run divides out of T, but the model still sees it on the raw frame):** an
  out-of-focus non-droplet detection whose mean T is ≥ 0.97 (`--static-t`) is not liquid;
  `static_pieces_not_counted`.
- **Volume (secondary, `--volume`):** per frame `droplet_vol_mm3` (spheres), `total_liquid_vol_mm3`
  (un-atomised pieces with a round cross-section, `liquid_volume.py`, OpenCV only), `atomised_vol_pct`;
  pooled `atomised_vol_pct_pooled`. Ranks runs like the area fraction; scale good to about ±40%.
- With `--static-t 0 --window-p 0 --no-volume` the output is bit-identical to 2.2.0 (checked on C20).
- CCD day: C9 8.84 → 16.38%, C21 10.81 → 15.08%, C20 5.96 → 10.51%; runs without drops unchanged.
  `remeasure_liquid.py` re-runs only this stage from the existing predictions (no inference; CPU; on the
  Mac ~1.5 min per run, LaCie-read bound), archiving the old `liquid_0.30/` to `_liquid2.2.0/`. The app
  refuses to mix liquid-stage versions.

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
moved by the 2.2.0 rule). Since 2026-10-14 it also draws, the same way, measure_run's busiest and
mean-diameter frames (`droplets_<thr>/extreme_frames_more/index.json`, or `--more-extremes`); the 2×2 slides
and the GUI show these drawings in preference to measure_run's. `classical_summary.json` records both
`atomised_extreme_frames` (with droplet count, un-atomised px and pieces) and `d32_extreme_frames`, and
`more_extreme_frames` (the frames drawn). `draw_more_classical.py` back-fills older runs: a re-run into a
temporary folder, each drawn frame's row checked against the run's per-frame CSV (and on a full pass the pooled
summary too), only the new images copied. A run whose summary records no window drops is re-measured on the
drawn frames alone (`--frames`, `--window-p 0`: with no window mask a frame depends only on itself), ~4 s. The raw lowest-D32 frame is
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

**"No spray" runs** (`stats.no_spray_reason`, 2026-10-13): a run whose atomised fraction is below the
Settings tab's threshold (default **2%**, 0 = off) is a dribble. Its droplet **size** (D32, mean, median,
D90, Dv50, the size spread) and droplet **steadiness** (count CV, near-empty %, frames below half,
lag-1, spectra) are blanked in both analyses, every table and figure, and the deck's headlines; its
atomised fraction, in-focus count, liquid CV, atomised liquid flow and peak pressure stay (near zero is
the true answer there). The run is named in the warnings at the top of the report and in provenance.
On the CCD day it catches C3 (0.19%) and C5 (0.45%); the next run up is 5.96%.

**Responses** (`taguchi_analysis.RESPONSES`; all from the same frames):

| response | definition | better |
|---|---|---|
| D32 in-focus | Σd³/Σd² over in-focus droplets | smaller |
| Atomised fraction by area, classical | 100 Σdroplet_px / Σtotal_px (projected area, not volume: see `definitions.md`) | larger |
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

**Gas mass flux at the orifice** (`covariates.py`, added 2026-10-13): G = ṁ_gas / A, ṁ_gas = sccm × ρ_gas /
6×10⁷ kg/s (ρ_gas the recorded gas density, as for GLR), A = π d²/4 of the run's orifice. The sccm is what the
run got in the camera window (`operating.py`), else the workbook's achieved flow, else the set point. Also a
covariate, not a factor (made from gas and orifice): same correlation and power-law exponent per response, and
`fig_gas_flux` (log x, coloured by orifice, hollow = did not get its set gas), in the Taguchi and the
response-surface outputs. Exit velocity equivalent = G / ρ_gas, for reading only: at a choked orifice the
real exit is sonic and denser. Why: on the CCD day it ordered atomised fraction best of everything tried
(Spearman +0.91; GLR −0.21). The exit orifice **length** (`run_summary.xlsx` *Orifice length (mm)*, written
from 2026-10-13) and L/D are reported with it; runs with different lengths in one analysis raise a warning,
since the length is not a factor and its effect would be mixed into the others.

**Silicone film at the exit** (`orifice.py`, added 2026-10-13): G over the gas-only capacity at the
camera-window P0, G_gas = Cd · P0 · √(γ/(R T)) · (2/(γ+1))^((γ+1)/(2(γ−1))) when choked (P0 ≥ 1.89 Pa; the
subsonic isentropic form below), 20 °C, γ and R from the *Gas* tag, is the gas share α of the orifice area.
Then u_L = Q_L / ((1 − α) A) (syringe flow) and, for an annular exit, h = (d/2)(1 − √α). Cd per insert from
`orifice_cd.json` (1.0, "ideal (not measured)", until measured gas-only). A covariate (`film_um`), with
`fig_film_thickness`, the diagram `fig_orifice_model`, a report section, the workbook sheet *Silicone film at
exit* (diagram and maths beside the table) and deck slides, in both analyses. CCD day: Spearman −0.90 with
atomised fraction over 31 spraying runs. P0 is read upstream, so α is underestimated; separated, frozen flow
is assumed. **No-spray runs are left out of every covariate fit** (plotted as grey ×).

**Added 2026-10-13:** atomised fraction by volume (estimated, liquid stage ≥ 2.3.0, secondary) and its
flow index; in-focus droplets per frame in the size band (Settings, default 20–60 µm since 2026-10-14, half-open): how many
droplets of the wanted size, a concentration, not a rate; droplets produced per second (all sizes and in the
band), by mass balance: syringe flow × atomised fraction by volume ÷ π/6⟨d³⟩, a rate that does not fall when
the spray speeds up (liquid stage ≥ 2.3.0; `run_metrics.mass_balance_rate`). From 2026-10-14 the in-band rate
is the default response-surface goal (importance 3, atomised fraction 1).

**Extra responses** (`run_metrics.py`, the shared per-run data layer, cached in `<output>/cache/`):
Dv50 (volume median, grouped-data interpolation across the pixel lattice's diameter cells), atomised
liquid flow index, area-based (syringe mL/min × atomised fraction by area: an index, not a measured flow), frames below half the mean count, lag-1 correlation of the
droplet count, peak pressure: 14 responses, 42 factor tests on the 9x3.

**Deliverables:** `taguchi_report.md`, `taguchi_analysis.xlsx`, `figures/` (main effects,
contributions, per run, S/N, GLR, gas mass flux, silicone film and the orifice model diagram, size spread
by count and volume; plus `figures_extra.py`: size
distributions and percentiles, per-run time series with pressure, liquid area, spectra, steadiness,
drift, replicates, interaction plots, residual checks, correlations, liquid pieces, data quality, image
galleries: `gallery_<c>` the classical least / most atomised frames, `gallery_more_<c>` the
`extreme_frames_more/` frames, skipped for runs without one), `taguchi_deck.pptx` (`deck.py`, on Ben's template; needs python-pptx), optional `csv/` and
`odd/` (odd-frame pack), and provenance (repo revision, sizer version, thresholds, bootstrap, bins).

---

## 9b. Stage 6b: response-surface analysis (Response surface tab → `rsm_publish.publish()`)

For a central composite design (or any run set where a quadratic can be fitted). Guide for users:
`docs/RSM_GUIDE.md` (shown in the tab).

- **Design detection** (`rsm_detect.py`): factors, design levels (uneven allowed: design coding −1/0/+1
  classifies points, real coding (v − mid-range)/half-range fits, so 1.2 on 0.5/1.2/1.8 is +0.08), axial
  pairs, off-grid check runs and controls outside the region, point types, repeats, design type with
  missing points, hard-to-change block factor (confounded with time), Notes vs point type and order,
  estimability (rank + VIF > 50 = nearly aliased).
- **Gas delivered and the operating regime** (`operating.py`, 2026-10-13): each run's `run_summary.xlsx`
  → Pressure sheet gives the gas flow and P0 inside the camera window. **Flow-controlled**: ≥ 95% of the
  set gas; **pressure-limited**: below that with P0 within 0.5 bar of the supply ceiling (Settings, default
  9.5 barA); **gas short**: below that with lower pressure; **settled**: the window's median within 10% (or
  100 sccm) of the 10 s before and of its own first half. Runs that did not get their set gas are, by
  default, kept out of the fit (`RunPoint.excluded`) and reported in their own section with a main-effects
  test among them; the Model page can instead fit them at the gas they got, or keep the set point. On the
  CCD day all ten 0.5 mm runs are pressure-limited (33–5,554 sccm against 7,000–11,000) and every other
  run flow-controlled. Figures: `fig_rsm_gas_delivered`, `fig_gas_traces`.
- **Factor coding** (2026-10-13): `FactorLevels.log` codes a factor on ln(value) (Model page tick, default
  the orifice); `decode()` is the inverse used everywhere. When runs are left out of the fit, the levels
  are refitted to the fitted runs (`rsm_responses._recode`), so maps and the optimum stay in the fitted
  span; settable levels outside it are not offered.
- **Run-sheet builder** (`rsm_design.py`): face-centred CCD for 2–5 factors, optional half fraction,
  block factor with start/end repeats, extras, pressure-check first run, seeded order; rig limits gas
  12,000 sccm, 1,000 rpm, feed 2,000 to 12,000 steps/s.
- **Fit** (`rsm_stats.py`, `rsm_responses.py`): quadratic in real coding over the surface factors, nuisance
  factors as slope or slope + curve; OLS with SE/t/p, R², adjusted, predicted (PRESS); lack of fit vs pure
  error; backward elimination with hierarchy; BH q across responses; CI and PI; drift (centres, block
  repeats, residuals vs time); runs outside the fit predicted with 95% PI; Derringer–Suich desirability
  (goal surfaces with predicted R² < 0.5 left out), optimum continuous and at settable levels.
- **Outputs** (`rsm_figures.py`, `rsm_report.py`, `rsm_deck.py`): contour maps (gas × feed per orifice per
  RPM by default), 3D surfaces, all-pairs maps, profiler, desirability with sweet spot, fit checks, model
  comparison, drift, validation; `rsm_report.md`, `rsm_analysis.xlsx`, `rsm_results.csv` (the CCD plan's
  columns), `rsm_deck.pptx` (every slide: what it shows, how to read it, terms).
- **Next runs** (`rsm_recommend.py`): confirmation at the best setting + centre anchor; steepest ascent and a
  new CCD when the optimum is on an edge; D-optimal runs when the model is weak; a new insert size only
  when the CCD plan's three conditions hold; `next_runs.xlsx/.csv/.md` and `next CCD/`.

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
   flux; depends on where the field of view is relative to the nozzle. One pixel of a round
   ligament holds 5–15× the liquid of one pixel of droplet, so the area share overstates the
   volume share, by a run-dependent amount. Labelled "by area" (and atomised liquid flow "index,
   area-based") since 2026-10-13; a read-only area-vs-volume check on the CCD day is planned.
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
| 8 | **Measure velocity once** (windowed high-fps capture, PTV). 2026-10-13: the 390 fps cines cannot give it (nothing pairs across 2.56 ms; the 4 µs blur bound is ≤ ~4 m/s and optical); the mass balance gives 4–8 m/s mean liquid speed, proportional to gas; transit decorrelation < 1 frame. Next: a 10-min exposure series (1/4/16/40 µs), then a windowed high-fps capture (~10 kfps on a 2.56 mm strip along the flow, 1 µs) of a 15-capture calibration set, or a double-pulsed backlight (`docs/VELOCITY_CAPTURE_PLAN.md`) | velocity, whether flux weighting is needed, whether fast droplets are lost to blur | exposure series: 10 min; PTV: one capture + analysis |
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
