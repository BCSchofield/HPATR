# Definitions — every number this pipeline produces

Reference for the vocabulary used across the HPATR droplet-detection work.
Written for anyone picking the project up, and for write-up: each entry gives
the **formula as actually implemented**, what the number means, and how it can
mislead you.

Where a definition is pinned to code, the file and function are named. If this
document and the code ever disagree, **the code is right and this is stale** —
fix it here.

Companion documents: `HANDOFF_real_data_pipeline.md` (operational state and
results), `CLAUDE_Understanding.md` (codebase structure).

---

# PART 1 — IMAGING AND PHYSICAL QUANTITIES

These are the units everything else is expressed in. If T is not clear, nothing
downstream is.

## Transmission (T)

**The fraction of light that reached the sensor, relative to what that same
pixel reads with nothing in the way.**

    T = raw_frame_16bit / background_median          measure_run.py:234

| T | meaning |
|---|---|
| 1.00 | nothing there, all light through |
| 0.29 | 71% of the light blocked |
| 0.05 | nearly opaque — the big ligaments |

**Why divide rather than subtract.** Two independent reasons:

1. **Physics.** Absorption is multiplicative (Beer–Lambert), so division matches
   it, and overlapping objects multiply. This is also why `composite.py`
   multiplies transmissions rather than alpha-blending.
2. **It cancels the illumination field.** The background varies pixel to pixel
   from lamp non-uniformity, the right-hand vignette and a top-edge smudge.
   Dividing compares every pixel to *its own* empty value, so T means the same
   thing everywhere in the frame.

T is computed on the **16-bit** frame, never the 8-bit one. The 8-bit PNG is a
display render; the 16-bit TIFF holds native camera counts.

## Background (background_median.tiff)

**Per-pixel temporal median across ~40 frames of the run's own footage.**

Spray is transient, so at any given pixel most frames are empty and the median
lands on the empty value. Anything *static* — illumination gradient, vignette,
lens dust, sensor specks — survives the median and therefore divides out to
T ≈ 1.

It is best read as "the empty scene as this camera saw it, during this run".
It is per-run and must not be shared between runs: the lamp and the dust move.

**Sensor dust is invisible in T, and that is correct, not a bug.** A speck is
static, so it is *in* the median: dark ÷ equally dark = 1.0. It is plainly
visible in the 8-bit image a human labels on, and absent from T. Both readings
are right — they are different quantities.

## t_min

**The single darkest pixel inside one object's mask.**

    t_min = T[mask].min()                            measure_run.py:246

Two jobs:

1. **Focus proxy.** A sharply focused object has a dense core, so some pixel
   gets properly dark and t_min goes low. Defocus spreads the same absorbed
   light over more pixels, so no single pixel gets very dark and t_min stays
   high. `--focus-max 0.70` asks exactly one question: *did this object ever get
   properly dark?*
2. **It sets the object's edge** — see below.

## Half-maximum edge

**The contour at (t_min + 1) / 2** — midway between the object's darkest point
and clear background. Everything darker than that is inside the object.

**Why half-maximum and not any other level.** When defocus blurs a sharp edge
the intensity ramps rather than steps, but the **50% crossing stays where the
true edge was** for any symmetric blur, because blur moves light equally both
ways about the edge and so cannot shift the midpoint. At 20% or 80% the contour
creeps outward or inward as focus changes. Half-max is the *only* threshold
invariant to defocus, which is why the pipeline is built on it. That is a
physical argument, not a convention — though the choice to define a boundary
this way remains yours to defend in a viva.

**It also explains the small-object bias exactly.** The invariance assumes the
object is big enough for its core to reach full opacity. A 3–4 px droplet is
comparable in size to the blur itself, so its light spreads before it can get
properly dark: t_min reads too high, the half-max edge sits too tight, and the
droplet measures smaller than it is — or fails the focus gate entirely. Same
physics, applied to something too small to hold it.

## In focus / out of focus (green vs magenta)

A predicted droplet is **in focus** if `t_min <= 0.70`, else **out of focus**.

- **In focus (green)** — size is trustworthy. Used for D32.
- **Out of focus (magenta)** — real object, size is not trustworthy. Excluded
  from D32, **included** in the atomised fraction.

Those two populations differ *on purpose*. D32 is a size statistic, so it must
only see objects whose size means something. The atomised fraction is an area
share — an out-of-focus droplet is still liquid that has atomised, and dropping
it would shrink the numerator while its filaments stayed in the denominator.

## µm per pixel

**`UM_PER_PX = 10.0`** (`measure_run.py:74`). One pixel is 10 µm at the object
plane. The 2560×1600 sensor therefore sees 25.6 × 16.0 mm.

Every micron figure in the project rests on this one constant. It is a
calibration, and if the optics change it must be re-measured.

## The pinned 8-bit window

    pixel_8bit = clip((raw - lo) / (hi - lo) * 255)
    PINNED_WINDOW = (27.0, 876.0)                    cine_extract.py

A **fixed linear rescale** from 16-bit camera counts to the 8-bit PNG the model
is fed, identical for every frame of every run, taken from the `05_dataset_v3`
training composites.

**Why it must be pinned.** Every run before 2026-09-27 computed its own
percentile window, which made runs incomparable to each other *and* to the data
the model was trained on. Worked example: an object at T = 0.3 (raw ≈ 242) maps
to pixel **65** under the training window but **54** under one run's own — a
~17% contrast difference for a physically identical object.

Second-order benefit: re-extraction is now deterministic, so extracted frames
are regenerable byte-identically and need not be backed up.

**Clipping warning.** `check_window_fit()` samples 20 frames and warns if more
than 2% of pixels clip at either end. Measured on the 4500 sccm run: 0.00%
below, 1.28% above.

## 8-bit vs 16-bit — which is used where

| | 8-bit PNG | 16-bit TIFF |
|---|---|---|
| what | display render, pinned window | native camera counts |
| used for | **model input** and human labelling | **all measurement** (T, t_min, focus) |
| never used for | measuring anything | feeding the model |

The model is trained on and fed 8-bit only. The 16-bit frames never touch the
network — they exist so that measurement happens on real data rather than on a
display transform.

---

# PART 2 — SIZE AND COMPOSITION STATISTICS

## Equivalent diameter (d)

**The diameter of the circle with the same area as the detected mask.**

    d = 2 * sqrt(area_px / pi) * 10 um/px            measure_run.py:92

Droplets are not perfectly circular, so this is an **area-equivalent** diameter.
It is a deliberate modelling choice: it converts a 2-D mask into one length, and
in doing so assumes sphericity. For genuinely spherical droplets it is exact;
for a ligament fragment it is a summary, not a measurement.

## D32 — Sauter Mean Diameter

**The diameter of the droplet whose volume-to-surface-area ratio equals that of
the whole spray.**

    D32 = sum(d^3) / sum(d^2)                        measure_run.py:96

Computed over **in-focus droplets only**.

**What it is for.** Spray physics cares about the surface area available per
unit volume of liquid — that governs evaporation, heat transfer and how well a
spray coats a surface. D32 is the single diameter that preserves that ratio, so
it is the standard atomisation response.

**Why it is not an average.** It is a **ratio of moments**, not a mean of
diameters. Given droplets of 1, 2, 2 and 3 µm:

    sum(d^3) = 1 + 8 + 8 + 27 = 44
    sum(d^2) = 1 + 4 + 4 + 9  = 18
    D32 = 44/18 = 2.44 um          (the arithmetic mean is 2.0)

D32 always sits **above** the arithmetic mean, because cubing weights large
droplets more heavily than squaring. A handful of big droplets dominate it.
**Never present the mean diameter and D32 as if they were the same quantity.**

**POOLED, NEVER AVERAGED.** Because D32 is a ratio of sums, every droplet in the
run goes into a single Σd³/Σd². Averaging per-frame D32 values weights a
3-droplet frame the same as a 300-droplet one and is simply wrong. Per-frame
D32 is reported for diagnostics only.

**What this project's D32 actually is.** "D32 of the droplets this model
detected and could size confidently." It is **not** an unbiased estimate of the
spray's true D32 — small in-focus droplets are under-detected (~75% recall at
0–50 µm) and missing small droplets inflates a Sauter mean. Against hand labels
it reads roughly **+10% (benchmark) to +25% (trial frame)**.

That bias is acceptable for **ranking** runs, because it applies to every run
measured identically. It must never be quoted as an absolute droplet size
without the bias stated alongside it.

## Atomised area fraction

**The share of detected liquid area that is in droplets rather than in
unbroken structures.**

    atomised % = union(droplet) / [union(droplet) + union(filament) + union(blob)] * 100
                                                     measure_run.py:257-261

Computed over **all droplets**, in focus and out.

Higher is better atomisation: more of the liquid has broken into droplets. On
Trial_1 it read 7.78%, i.e. ~92% of detected liquid area was still in filaments
and blobs — atomisation is markedly incomplete at these conditions.

**Union, not sum.** One long filament is emitted by the model as several
overlapping sub-segments. Summing their areas double-counts the overlap
(measured: filament 20.5%, blob 10.6%, droplet 0%). `union_area()` merges the
RLEs so each pixel is counted once.

**Known open bug.** The union is taken *within* each class and the three totals
are then added, so a droplet mask overlapping a filament mask still contributes
those pixels to both, and therefore twice to the denominator — biasing the
fraction **down**. See OPEN BUGS in the handoff. Hand labels overlap ~0% across
classes, so this is prediction-side only.

**Degenerate frames.** A frame containing zero filaments and zero blobs reads
exactly **100%** by construction, not because atomisation was perfect. Five
frames on Trial_1 did this. The GUI flags them inline rather than hiding them.

**This is the weak response.** It measures at ±15% against D32's ±2%, and
cannot reliably rank runs. Use D32 as the primary Taguchi response.

## Size distributions (`droplet_sizes.csv`, `object_areas.csv`)

**Every individual object's size, one row each** — as opposed to the aggregates
in `per_frame.csv`.

- `droplet_sizes.csv` — frame, `diameter_um` (equivalent diameter), `in_focus`
  (1/0). One row per droplet above the score threshold.
- `object_areas.csv` — frame, `class` (filament/blob), `area_px`, `area_mm2`
  where `area_mm2 = area_px × µm_per_px² / 10⁶`.

`size_histograms.png` plots them: droplets on linear 25 µm bins split by focus,
filaments and blobs together on **log** bins (their areas span ~5 orders of
magnitude, so linear bins collapse them into one column).

**Filament and blob rows are DETECTED INSTANCES, not whole objects.** One long
filament is emitted by the model as several overlapping sub-segments, so
counting rows over-counts filaments and summing `area_mm2` double-counts the
overlap. For area share use the atomised fraction, which unions them.

Regenerate the figure with `measure_run.py --replot --out-dir <dir>`; it reads
the CSVs and measures nothing.

## Classical un-atomised liquid (`classical_liquid.py`)

**The un-atomised half of the atomised fraction, measured by thresholding the
whole frame instead of by the model.**

The model's masks are untrustworthy for un-atomised liquid in two independent
ways: its 28x28 mask head cannot represent a 100:1 aspect-ratio thread, and
objects larger than a tile get cut at tile seams. Both inflate the atomised
fraction, because both make un-atomised liquid read smaller than it is.

**Hysteresis segmentation.** Seed on pixels darker than T<0.70 ("definitely
liquid"), then grow each seeded region out to **its own half-maximum edge**,
`(t_min + 1)/2` — the same edge definition hand labels and the model's training
targets use. A single threshold cannot do this job: T<0.95 yields ~36,700
components per frame of mostly sensor noise, while T<0.70 alone loses real
objects' faint edges.

    numerator   = union(model droplet masks)
    denominator = union(classical liquid, model droplets,
                        OUT-OF-FOCUS model filaments/blobs)

Only **out-of-focus** model filaments are unioned in, because the 0.70 seed
cannot reach them by construction (out-of-focus *is* t_min > 0.70). Unioning all
model masks was tried and was wrong — a union can only add, so the model's
over-wide filament masks became a floor the classical measurement could never
get below.

**One union, not three summed** — which structurally removes the cross-class
double-counting bug in the denominator.

**No filament/blob split.** A real region is routinely both: the largest in
`frame_0074_n739` is a 560,985 px blob with thin threads attached, one connected
piece of liquid. The ratio only needs droplet vs not-droplet.

**Not validated against ground truth.** Direction is well-supported; magnitude
depends on the seed threshold and should be checked against the hand-labelled
benchmark before being quoted.

## Mean, SD, min and max droplet diameter

Reported alongside D32 as a **distribution** summary over every in-focus droplet
in the run (`measure_run.py:304-308`; SD uses `ddof=1`, the sample standard
deviation).

**The SD is not an error bar on D32.** It describes how spread out the droplets
are — a physical property of the spray. The uncertainty on D32 is the confidence
interval, which is a different quantity entirely and is roughly an order of
magnitude smaller. The GUI deliberately separates these into different lines
for this reason.

**Min and max are single detections.** The minimum sits on the model's noise
floor (false-positive median 33.9 µm, 71% under 50 µm), so read them as a
statement about detector limits as much as about the spray. The SD is the
trustworthy shape statistic.

---

# PART 3 — UNCERTAINTY

## CI — Confidence Interval

**A range that expresses how precisely a number is pinned down by the data.**

Reported here as **95% CI**: loosely, if the experiment were repeated many
times, ~95% of such intervals would contain the true value. It is quoted two
ways — as an interval `[83.7, 87.4]` and as a half-width percentage `±2.1%`.

**A CI measures PRECISION, not ACCURACY.** It answers "how much would this
number move if I collected another sample of frames?" It says nothing whatever
about systematic bias. D32 here carries a known +10–25% bias *and* a ±2.1% CI:
the number is highly repeatable and simultaneously offset. Tightening the CI by
taking more frames does nothing at all to the bias.

This is the single most important distinction in this document. A tight CI on a
biased instrument is a precise wrong answer.

## Bootstrap

**How the CIs here are computed**, since D32 is a ratio of sums with no clean
analytic standard error.

    boot_ci()                                        measure_run.py:110

Procedure, repeated `--n-boot` times (default 2000):

1. Draw a resample of the **frames**, with replacement, the same size as the
   original set.
2. Recompute the statistic on that resample.
3. Keep the value.

Then take the **2.5th and 97.5th percentiles** of the 2000 values — hence
"percentile bootstrap". The spread of results across resamples estimates how
much the statistic would move under resampling, without assuming a distribution.

**Resampling is over FRAMES, not droplets.** Droplets within one frame are
correlated — they share a spray pulse, an illumination state and a moment in
time — so treating 28,769 droplets as 28,769 independent samples would report a
wildly overconfident interval. The frame is the sampling unit.

**Efficiency detail.** Because D32 = Σd³/Σd², each frame's `(Σd³, Σd²)` pair is
a sufficient statistic and the pooled value is just the ratio of summed pairs.
Resampling those pairs is mathematically identical to resampling the pooled
droplet list, and turns ~500M operations per run into ~2M
(`measure_run.py:314-329`).

## `--ci-stride`

**The point estimate uses every frame; the CI bootstraps only every Nth frame.**

    ci_stems = stems[::ci_stride]                    measure_run.py:343

Consecutive frames are **not independent samples** — liquid crosses the field of
view in ~20 ms, so at 500 fps frames fewer than ~10 apart contain physically the
same droplets. Bootstrapping them as if independent reports the precision of a
sample you do not have: duplicating 20 frames ten times adds zero information
yet narrows the interval 3.2x.

Too-narrow intervals make `compare_runs.py` declare differences real that are
not — the dangerous direction — so the stopgap is to bootstrap a strided
subsample. This throws away genuine precision (a strided interval is wider than
a correct block bootstrap over all frames) but it is honest and it errs safely.
A proper block bootstrap remains outstanding.

## Decorrelation time

**How long until a frame is a genuinely new sample of the spray.**

Currently taken as **~20 ms**, from: 20.5 mm field of view ÷ ~1 m/s liquid
velocity.

**This is INFERRED, not measured, and the default stride rests on it.** The
velocity comes from "features show shape, not streaks at 10 µs exposure", which
bounds velocity from **above** only — 0.3 m/s would also show no streaking. So
it bounds decorrelation from *below*, and stride 10 may be smaller than needed.
It also counts transit time only: atomisation is intermittent (per-frame
atomised fraction ranged 0.62%–100% on Trial_1), and if the pulsing is slower
than 20 ms then intermittency, not transit, sets the real figure.

Both are directly measurable by cross-correlating frames. Worth doing — it
decides whether a condition costs 23 minutes or 4 hours.

## Separability

Two runs are called **different** only if their 95% CIs do not overlap
(`compare_runs.py`). On Trial_1's precision that threshold is ~2.5 µm D32 or
~1.66 percentage points atomised.

`compare_runs.py` **refuses to compare** runs whose `score_threshold`,
`focus_max`, `um_per_px` or `ci_stride` differ, because the bias only cancels
between runs measured identically.

---

# PART 4 — DETECTION SCORING

These describe how good the model is. They need **ground truth** (hand labels)
and so only exist for the benchmark set, never for a production run.

## TP, FP, FN

Assigned by **greedy mask-IoU matching, per class, at one score threshold**
(`score_v2.py:108`):

- Detections above the score threshold are sorted **highest score first**.
- Each takes the unmatched ground-truth object it overlaps most, provided
  **IoU ≥ 0.5**.

| term | meaning |
|---|---|
| **TP** — true positive | a detection that matched a real object |
| **FP** — false positive | a detection that matched nothing — the model saw something that is not there, or double-detected |
| **FN** — false negative | a real object no detection matched — the model missed it |

There is no "true negative": the image is not divided into candidate slots, so
there is nothing to count.

**Greedy, not optimal.** Matching highest-score-first is the convention and is
what COCO does; it is not guaranteed to produce the maximum possible number of
matches.

## IoU — Intersection over Union

**Overlap between two shapes, from 0 (disjoint) to 1 (identical).**

    IoU = area(A and B) / area(A or B)

Used as the test of whether a detection "is" a given ground-truth object.
**IoU ≥ 0.5** is the operating-point threshold here.

Two flavours, and they are not interchangeable:

- **bbox IoU** — on the rectangular bounding boxes.
- **segm IoU** — on the pixel masks. Strictly harder, and the one that matters
  for this project, since every measurement is made from mask area.

## Precision, Recall, F1

    precision = TP / (TP + FP)      of what I detected, how much was real
    recall    = TP / (TP + FN)      of what was there, how much did I find
    F1        = 2 * P * R / (P + R)  harmonic mean

They trade off against each other via the score threshold: lowering it finds
more real objects (recall up) and more spurious ones (precision down).

**F1 is the wrong objective for this project.** It weights every object equally,
whereas D32 and the atomised fraction are **area-weighted** — one large filament
matters more than twenty specks. On v3 the best-F1 threshold is 0.90, which is
also v3's *worst* atomised-fraction error (−51.8%), while 0.30 gives −26.1%.
Optimising detection and optimising the measurement are different objectives and
they genuinely disagree.

## AP — Average Precision

**The area under the precision–recall curve: one number summarising detection
quality across all operating points at once.**

Reported from COCO's `COCOeval` (`score_v2.py:66-91`).

- **AP** (written `AP` or `AP@[.50:.95]`) — precision averaged over 101 recall
  points, then averaged over **ten IoU thresholds** from 0.50 to 0.95 in steps
  of 0.05, then over classes. The multi-IoU average is what makes it strict: to
  score well you must localise well, not merely detect.
- **AP50** — the same at IoU 0.50 only. Much more forgiving; roughly "did you
  find it at all".
- **bbox AP** vs **segm AP** — computed with box IoU and mask IoU respectively.
  `Eden` scores segm AP 66.8, bbox AP 71.5; bbox is nearly always the higher of
  the two because boxes are easier to get right than outlines.

Values are percentages, 0–100, higher better.

**AP is threshold-free and therefore does not describe your operating point.**
It integrates over score thresholds, while production runs at a single fixed
one (0.30). A model can gain AP while getting worse at the threshold you
actually use. AP is for comparing *models*; precision/recall at 0.30 is for
understanding *your measurement*.

**maxDets** caps detections counted per image. The COCO default of 100 is far
too low here — frames carry 300+ objects — so it is raised, and `ap_at_max()`
reads AP at the largest setting.

## Score / confidence

**The model's own 0–1 estimate that a detection is a real object of that class.**

Two distinct thresholds, deliberately different:

- **Inference floor 0.05** (`tiled_inference.py`) — everything above this is
  written to `predictions.json`. Kept low so the JSON is a superset and
  thresholds can be re-applied later without re-running the model.
- **Measurement threshold 0.30** — applied at measurement time. Chosen because
  D32 is flat between 0.20 and 0.30 on both the benchmark and the trial frame,
  so the higher value costs no accuracy while giving better precision and fewer
  spurious detections. A round number in a flat region is robust to small
  future model changes.

**Score is not calibrated probability.** A 0.9 detection is not "90% likely
real". It is an ordering, useful for thresholding, not a probability to be
reasoned with.

---

# PART 5 — TRAINING

## Loss

**A single number measuring how wrong the model is on the current batch.**
Training minimises it by gradient descent. It has no units and its absolute
value is close to meaningless — only the **trend** matters.

Mask R-CNN's total loss is a sum of five parts, all visible in
`metrics.json`:

| component | what it penalises |
|---|---|
| `loss_cls` | wrong class on a proposed region (cross-entropy) |
| `loss_box_reg` | wrong box refinement (smooth L1) |
| `loss_mask` | wrong pixels in the mask (per-pixel binary cross-entropy, computed only for the ground-truth class) |
| `loss_rpn_cls` | region proposal network wrongly calling a location object/not-object |
| `loss_rpn_loc` | region proposal network's box offsets being wrong |

**Falling loss does not mean a better model.** It means better fit to the
*training* data, which past a point is memorisation. Model quality is judged on
held-out validation AP, never on training loss.

## Iteration, batch, epoch

- **Iteration** — one gradient update on one batch. v3 ran `MAX_ITER = 20000`.
- **IMS_PER_BATCH** — images per batch (2 here), so 20,000 iterations is 40,000
  image presentations.
- **Epoch** — one full pass through the dataset. Detectron2 counts iterations,
  not epochs, so the term rarely appears here.

## Learning rate (LR)

**How large a step each gradient update takes.** Too high diverges; too low
crawls or sticks in a poor minimum. Settled at **0.0025** by sweep.

## Anchors

**Pre-defined candidate boxes the region proposal network scores and refines.**
Objects far from any anchor's size or shape are hard to detect at all.

Tuned to this data as **[8, 16, 32, 64]** with 4:1 aspect ratios both ways —
roughly geometric across the five FPN levels, covering the measured 5–800 px
range, with two sizes on P2 because droplets cluster there (median 9 px).
COCO's defaults assume much larger objects and perform materially worse here.

## Checkpoint selection / `model_best.pth`

**The saved weights from the iteration with the best validation score**, not
the last iteration. `Eden` is iteration 19000 of 20000, selected on **composite
validation AP**, never on the benchmark.

Selecting on the benchmark would turn the benchmark into a tuning set and make
every number computed from it optimistic. This separation is the reason the
benchmark's numbers can be quoted at all.

## Train / validation / benchmark — three distinct sets

| set | what it is | used for |
|---|---|---|
| **train** | synthetic composites | fitting weights |
| **validation** | held-out composites | choosing the checkpoint and hyperparameters |
| **benchmark** | 15–20 hand-labelled **real** frames | final honest scoring, touched as rarely as possible |

The train/validation split is composite-to-composite, which is why the
**sim-to-real gap** appears only against the benchmark.

---

# PART 6 — PIPELINE AND ARCHITECTURE VOCABULARY

## Mask R-CNN

The detection architecture. Two stages: a **region proposal network (RPN)**
suggests locations that might contain objects, then a head classifies each
proposal, refines its box, and predicts a per-pixel **mask** within it. "Mask"
distinguishes it from Faster R-CNN, which stops at boxes.

Instance segmentation, not semantic segmentation: it separates *this droplet*
from *that droplet*, rather than merely labelling pixels "droplet".

## ResNet-50 FPN 3x

The backbone. **ResNet-50** is a 50-layer residual CNN extracting features.
**FPN** (Feature Pyramid Network) combines features at several scales — levels
P2–P6 — so small and large objects are each detected at an appropriate
resolution. **3x** denotes the COCO pre-training schedule of the starting
weights.

## bbox

**Bounding box** — the axis-aligned rectangle enclosing an object, as
`[x, y, width, height]`. Cheap to compare, but never used for measurement here:
every size number comes from mask area, because a rectangle around a curved
ligament is mostly empty space.

## Mask, RLE

The **mask** is the per-pixel set belonging to one detection. Stored as **RLE**
(run-length encoding) — the COCO format, which records runs of identical values
rather than every pixel. `pycocotools` computes areas, unions and IoU directly
on RLEs without expanding them.

Expanding masks to full frames was the cause of the 15.9x slowdown fixed on
2026-09-28: a full-frame `np.zeros((1600, 2560))` per detection cost 4.1 MB
whether the object was 4 px or 400.

## `segmentation_crop` / `crop_xy`

**The same mask as `segmentation`, stored over its own bounding box instead of
the whole frame**, with `crop_xy` giving that box's top-left corner in frame
coordinates. Added to `predictions.json` on 2026-09-30.

`segmentation` (frame-sized, COCO-standard) is still written and unchanged, so
scoring tools are unaffected. The crop exists because decoding a frame-sized
RLE costs 4.1 M pixels regardless of object size, and the median detection is a
16 px box — a 2,476x overshoot that made measurement 14x slower than necessary.

Reconstructing one from the other is exact: decode the crop and place it at
`crop_xy`. Verified pixel-identical across a full frame's detections.

Predictions written before this date simply lack the fields; `measure_run`
falls back to decoding the frame and slicing, giving the same answer more
slowly.

## NMS — Non-Maximum Suppression

**Removes duplicate detections of the same object.** Where two detections
overlap above an IoU threshold, the lower-scoring one is dropped. Cross-class
NMS additionally suppresses across categories, which is what stops the same
ligament being emitted as both a filament and a blob.

## Tiled inference

**The frame is cut into 800×800 tiles, each run through the model at native
scale, and the detections merged.**

The config pins `MIN_SIZE_TEST = MAX_SIZE_TEST = 800`. Without tiling,
detectron2 would resize a 2560×1600 frame to fit 800 px — a 0.31x shrink that
would reduce a 9 px droplet to under 3 px and destroy it. Tiles keep every
object at the scale the model was trained on. Tiles overlap, and merging plus
NMS reconciles objects crossing a boundary.

## The three classes

| id | class | colour in output |
|---|---|---|
| 1 | droplet | green (in focus) / magenta (out of focus) |
| 2 | filament | orange |
| 3 | blob | blue |

**Filament** — an elongated, not-yet-broken liquid structure. **Blob** — a
large irregular mass that is neither a clean droplet nor a clear ligament.
Both count as un-atomised liquid in the denominator of the atomised fraction.

## Sim-to-real gap

**The drop in performance between synthetic composites and real frames.** The
model trains on composites built from a library of real extracted objects, but
those never quite reproduce real backgrounds, overlaps and noise. The gap is
why the benchmark exists and why composite validation AP must never be quoted
as the model's real-world accuracy.

---

# PART 7 — CONFUSIONS WORTH NAMING

| these are different | and the difference is |
|---|---|
| **D32** vs **mean diameter** | ratio of moments vs arithmetic mean; D32 is always higher |
| **CI** vs **standard deviation** | precision of the estimate vs spread of the droplets; ~10x different in size |
| **precision** (CI) vs **accuracy** (bias) | how repeatable vs how correct; more frames fixes only the first |
| **AP** vs **precision/recall at 0.30** | model comparison across all thresholds vs your actual operating point |
| **bbox AP** vs **segm AP** | box overlap vs mask overlap; bbox reads higher and is not what you measure from |
| **score 0.05** vs **score 0.30** | what gets written to JSON vs what gets measured |
| **8-bit** vs **16-bit** | what the model sees vs what you measure from |
| **union** vs **sum** of areas | counts overlapping pixels once vs twice |
| **pooled D32** vs **mean of per-frame D32** | correct vs wrong — the second weights sparse frames equally |
| **FP** vs **"the model is wrong"** | ~18% of FPs are real objects that are merely unmeasurable |
| **loss** vs **model quality** | fit to training data vs performance on held-out data |
| **validation set** vs **benchmark** | composites, used freely vs real frames, touched rarely |

---

## Appendix — where each number is produced

| number | file | function |
|---|---|---|
| T, t_min, focus split | `measure_run.py` | main loop, line 234/246 |
| equivalent diameter | `measure_run.py` | `equiv_um()` |
| D32 | `measure_run.py` | `d32()` |
| atomised fraction | `measure_run.py` | `union_area()` + main loop |
| bootstrap CI | `measure_run.py` | `boot_ci()` |
| TP/FP/FN, precision, recall | `score_v2.py` | `greedy_match()` |
| AP, AP50 | `score_v2.py` | `run_eval()`, `ap_at_max()` |
| loss components | detectron2 | written to `metrics.json` |
| pinned 8-bit window | `cine_extract.py` | `PINNED_WINDOW` |
