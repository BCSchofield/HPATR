# Handoff — real-data droplet detection pipeline

Continuation brief for Claude Code. Written 20 September 2026 at the end of a
planning session. Read this fully before writing anything.

---

## What this is

Ben is building a droplet/ligament detection pipeline for shadowgraph imaging
of effervescent silicone atomisation (PhD, high-definition silicone printing).

The **near-term goal is not the ML model**. It is a defined, reproducible
measurement that can rank runs in an upcoming **Taguchi parameter study** —
i.e. a number that says whether a parameter change improved atomisation. The
ML model is how that measurement gets more accurate later. Do not let the work
drift into process diagnosis or model-building for its own sake.

A full planning document exists: `droplet-detection-plan.docx` (v0.4). This
file is the operational summary of it.

---

## NEXT ACTIONS — picked up 2026-09-21 (end of day)

Steps 0, 1, 2, 3 and 4 are **done**. `02_library/` is built: **213 objects —
144 droplets, 54 filaments, 15 blobs** — each with transmission map, mask
and view crop, indexed in `library.csv`. Full detail in the Step 2/3 sections
below; this block is the up-to-date status.

**Edge-touching top-up — decided 2026-09-21, after the first library build.**
The first library topped out at **274 px**, while the data contains objects to
**1208 px** — every one of them border-touching, so all were hidden by the
`--skip-border` contact sheets. 12 were deliberately admitted (9 filament,
3 blob), taking the library from 201 to 213 and the longest object to 1208 px.
- **Why the usual reject-edge-touching rule was overridden for these**: a
  chopped droplet is the wrong *shape* and composites badly, but a filament is
  roughly uniform along its length, so a truncated segment is still a valid
  filament template — and tiled inference cuts objects at every tile boundary
  anyway, so the model must see truncated examples regardless. Droplets were
  **not** topped up this way; the objection genuinely applies to them.
- **`touches_border=True` in `library.csv` marks all 12.** Their measured sizes
  are meaningless. **Exclude them from any size-distribution analysis** — they
  are shape templates only. 12 of 213 objects are affected.
- The border-touching set split into three genuinely different things, not one:
  thin threads (thread width <=30 px — the actually-missing category), thick
  ligaments (30-100 px), and **lamellae** (>100 px wide; `n5049_o0004` is
  1208 px long but 233 px *wide*, aspect only 5.2). Lamellae classify as
  "filament" purely because aspect clears 3.0 — per the established facts
  anything over ~100 px is a lamella (>1 mm), a different phenomenon. All
  three lamellae were admitted knowingly.

**Step 3 close-out:**
- Droplets and filaments both cleared target (144≥80, 45≥40).
- **Blobs: 12 against a target of 30 — accepted as a real property of this
  run, not a review failure.** The blob sheet (post true-aspect fix) shows
  genuinely compact masses only; there simply aren't more of them in a
  filament-dominated, incompletely-atomised spray. Target not formally revised
  in writing — if this number still looks short once compositing (Step 5) is
  under way, revisit then with the actual compositing need in view rather than
  the original planning-stage guess.
- Picks cross-checked in an ad-hoc review artifact before building: caught 17
  duplicate lines (collapsed) and 6 typo'd IDs that resolved confidently to
  picks already elsewhere in the list (missing underscore / leading zero /
  digit transposition — verified against `candidates.csv`, not guessed). 9
  further typo'd droplet IDs could not be resolved with confidence; dropped
  rather than guessed, since droplets were already well over target.
- `build_library.py` now supports an optional per-ID sampling weight —
  trailing number after the ID (`n199_o0042  2`), default 1.0, capped at 3.0,
  written to `library.csv` as `library_weight`. **Not used yet** — none of the
  201 picks were weighted. For Step 5's compositor to read when it exists.
  Weight for mask/focus quality only, never for "nicer-looking circle" — real
  fragments are crescents and commas (slow relaxation in high-viscosity
  silicone), so weighting toward roundness biases away from what's actually
  representative.

**Step 4 — done, 2026-09-21.** `03_backgrounds/` holds 25 clean-field frames
(16-bit primary + 8-bit viewing), picked by eye from a 60-candidate shortlist
ranked by detected liquid area. Even the cleanest frame in the whole 493-frame
pool wasn't score-zero (n4979: 828 px / 44 regions, almost certainly sensor
noise, not spray) — score ranks candidates for a by-eye check, it does not
certify emptiness, which is why the pick stayed manual.

Tooling: `AI/Real_Data_Code/pick_backgrounds.py` (ranks + writes
`background_candidates.json`) and `build_backgrounds.py` (materialises
`03_backgrounds/picks.txt` into the folder + `backgrounds_metadata.json`) —
same picks-file-then-build pattern as Step 3's library.

**Known, accepted**: the 25 cluster into two frame-number windows (4279–4469,
4919–5029) rather than spreading across the whole 5071-frame recording — a
natural consequence of the spray's intermittency (a clean lull happened to sit
near the end of this run), not a selection defect. Doesn't add to the already
documented single-run dirt-pattern risk (that's about the smudge's fixed
*position*, unaffected by which frames were picked) — mitigation unchanged:
random crops and mild intensity jitter at composite time, revisit once a
second run exists.

**Step 5 — compositor BUILT, 2026-09-21**: `AI/Real_Data_Code/composite.py`.
Multiplicative transmission compositing, 800×800, COCO/RLE, three classes.
Read its module docstring before changing anything — the physics reasoning is
there, not here. Verified before generating: COCO loads through pycocotools
with zero bbox/area/shape mismatches, and masks sit on mean pixel 82 vs 237
outside (i.e. they actually align with the dark objects).

**A new step was inserted first: background cleaning
(`clean_backgrounds.py`).** Measured on the 25 selected backgrounds: an
average of **4.7 objects per frame pass Step 2's own in-focus gates**, and
**zero backgrounds were clean**. Every composite built on them would carry
real, detectable objects with no annotation — roughly 20% of the real objects
per image — training the model to suppress exactly the detections the
measurement needs, invisibly to any loss curve. Fixed by patching those
footprints with the cached temporal median (object-free by construction) plus
MAD-matched noise, since the median of 40 frames is ~6× smoother than a single
frame and an unmatched patch would read as fake smooth structure. Result
**118 → 0**, re-verified with the same detector; 0.04–0.23% of each frame
touched. `composite.py` prefers `03_backgrounds/16bit_clean/` and warns loudly
if it has to fall back to raw.
- **Out-of-focus blobs are deliberately NOT patched out.** The pipeline
  already decided they must never be detected, so leaving them present and
  unlabelled is the negative example the model needs — not label noise.

**Two appearances verified as faithful, not bugs** (both were investigated and
both are real — do not "fix" them):
- **Faint digit-like marks inside near-opaque objects.** Present in the source
  crops, not introduced by compositing. Raw values there are 2–70, which the
  fixed 8-bit window maps to 0–12, so structured content invisible against an
  807 background becomes faintly visible against black. Ben's read: dust inside
  the camera. Mechanism fits — dust attenuates multiplicatively and divides out
  cleanly against a bright background, but where an object blocks nearly all
  light any additive component (stray light, black level) stops being
  negligible against the near-zero signal.
- **Saturated white patches beside dark masses.** Real shadowgraph bright rims
  (light refracting at the liquid boundary), measured up to T=1.24 in library
  crops, all outside the mask. They saturate because the fixed window clips
  above 876 — and **real 8-bit frames saturate identically**: mean 0.057% of
  frame, present in every sampled frame, versus 0.0003–0.17% in composites.
  Same regime, so the composites match the real distribution.

**Dataset generated, 2026-09-21**: `05_dataset/` — 2000 images, 33,456
instances (droplet 21,393 / filament 10,614 / blob 1,449), median 12 instances
per image, 0.80 GB. Regenerate any time with `composite.py --n N --seed S`;
nothing downstream depends on these exact files.
- **Known weakness going into training: blobs rest on only 15 unique
  templates** (droplets 144, filaments 54). Rotation and flips vary
  presentation, not shape, so expect weaker blob generalisation. Traces back
  to this run genuinely not producing many isolated compact masses — will not
  improve without a second run. Watch it in the Step 7 evaluation rather than
  being surprised by it.

**Next up: Step 6 — hand-mask the 15 validation frames** (Mac; LabelMe is in
the `phantom` conda env). Write the labelling protocol first, and apply the
same out-of-focus rule the extractor uses, or validation and training will
disagree about what counts as an object. Then **Step 7 — train, on Windows**.

**Before the Tuesday capture session**: confirm the new recordings use the
same bubbler/spinner position as `recording_130057`, or they will be unusable
for over-training and validation exactly as the other three 2026-09-09 runs
were. See the note under "Only one run is usable right now".

**macOS sidecar files on the exFAT drive — know about this one.** The LaCie is
exFAT (so Windows can read it), which has no native extended attributes, so
macOS stores them in AppleDouble sidecars named `._<name>`. Finder regenerates
them just by browsing the drive or generating a Quick Look preview — cleaning
up is not a permanent fix.

They matter because **`pathlib.Path.glob("*.png")` MATCHES dot-prefixed names,
while `glob.glob` does not.** A folder of 15 frames silently lists as 19. Tools
that read directories directly (LabelMe among them) also try to open them and
error out. Every listing in `AI/Real_Data_Code/` therefore goes through
`_fsutil.list_files()`, which filters them — **do not go back to bare
`.glob()`**. To clear them when a GUI tool complains:

    python AI/Real_Data_Code/_fsutil.py /Volumes/LaCie/Experiments/Real_Data

**If working on the Windows machine**: verify drive detection picks the right
letter — `python -c "import sys; sys.path.insert(0,'src'); from config_loader
import find_lacie_drive; print(find_lacie_drive())"`. Untested there.

---

## Established facts — do not re-derive these

**Imaging**
- Scale: **100 px/mm = 10 µm/px**. Already calibrated. Do not ask for a graticule.
- Example run: 2048×1152, 1300 fps, 10 µs exposure, **12-bit** stored as uint16
  (corrected 2026-09-20 — see Bit depth section below; do not re-derive as 10-bit).
- Field of view: 20.5 × 11.5 mm.
- No intensity clipping. Background mode ~807 (≈20% of the 4095 full-scale
  ceiling), frame minima 2–70, zero pixels at 0.
- Bright specular highlights (light reflecting off a droplet/filament surface
  into the lens rather than passing through it) reach up to ~1911 in ~5% of
  frames (25/508 in `recording_130057`) — unremarkable at 12-bit (47% of full
  scale), not an anomaly. Confirmed 2026-09-20, bit-identical to a fresh
  direct re-read of the source `.cine`, so not an extraction artefact.
- Liquid velocity ~1 m/s (features show shape, not streaks, at 10 µs).
- Decorrelation time ~20 ms — frames closer than that are not independent samples.

**What the spray actually looks like**
- Atomisation is **incomplete**. ~68% of detected liquid area is in filaments,
  only ~2% by volume has become droplets.
- Process is **intermittent** — some frames dense with threads and mm-scale
  lamellae, others nearly empty. Per-frame stats are useless; average per run.
- Small fragments are **crescents/commas, not spheres** (high-viscosity silicone
  relaxes slowly).
- Filaments reach 2–4 px wide by 1000+ px long (20–40 µm by several mm).
- Roughly half the objects are out of focus (soft grey, not sharp black).
- **Static artefacts**: fixed dark smudge along the top edge + vignette at right,
  present in every frame including pre-trigger. Dirt/illumination, not spray.

**Feature sizes**

| Feature | Pixels | Real |
|---|---|---|
| Small fragments | 3–5 px | 30–50 µm |
| Typical crescent | 12 × 4–5 px | 120 µm × 40–50 µm |
| Thin filaments | 2–4 px wide, 1000+ long | 20–40 µm × several mm |
| Thick ligament | ~40 px | ~400 µm |
| Lamella | >100 px | >1 mm |

---

## Decisions already made — treat as settled

1. **Three object classes**: `droplet` / `blob` / `filament`.
   - Droplet = compact, below the size ceiling.
   - Blob = compact but above the ceiling → unbroken mass, belongs in the denominator.
   - Filament = thin thread.
2. **Droplet size ceiling = 200 µm, fixed across the whole Taguchi matrix.**
   Justified by Rayleigh breakup: a ligament of width w yields droplets ~1.9w;
   mean filament width is 87 µm → ~165 µm, rounded to 200. Report sensitivity
   at 150 and 300 µm.
3. **Primary response = area-weighted atomised fraction** (droplet area ÷ total
   detected liquid area, 0–1, larger-is-better).
   **Secondary = D32 of the droplet class only** (smaller-is-better), plus a
   volume-weighted fraction reported with caveats (droplets as spheres,
   filaments as L × w × w with thickness assumed = width).
   Count-based ratios are rejected — one lamella outweighs 1000 fragments.
4. **Build the new training set by compositing REAL objects**, not by rendering
   synthetic ones. Cut real objects from real frames, paste onto real empty
   frames. Appearance is real by construction; masks are free.
5. **Composite multiplicatively in transmission**, never alpha-blend.
   Shadowgraph is I = I_bg × T, so store objects as T = I_obj / I_local_bg and
   paste as I_new = I_bg × T. Overlaps then multiply correctly.
6. **Fixed training crop size 800×800**, tiled inference at native scale for any
   frame size. Never resize at inference — droplet pixel size must mean the same
   thing at train and test time.
   - **Frames smaller than 800×800** (e.g. shooting at reduced resolution for
     higher FPS): pad up to 800×800 with a background-matched border — padding
     adds empty margin, it does not rescale content, so this doesn't violate
     "never resize." Run one tile, crop detections back to the true frame
     extent, discard anything only present in the padding.
   - **Confirmed 2026-09-20, from the official Phantom VEO E-340L datasheet**:
     this camera achieves higher FPS at lower resolution via sensor
     **windowing/ROI cropping**, not pixel binning — pixel size is listed as a
     single fixed 10 μm figure across every resolution in the frame-rate table,
     with no separate binned mode (contrast with Phantom's VEO 1310 datasheet,
     which explicitly documents one). **This means µm/px does not change when
     shooting at reduced resolution** — the existing 10 µm/px calibration and
     any trained model both remain valid without recalibration or retraining.
     Source: `ds_web-veo-e-310l-e-340l.pdf` (phantomhighspeed.com).
   - **Real consequence that is separate from the above**: windowing reads a
     smaller physical patch of the sensor, not the same field of view at fewer
     pixels. At 640×480 the real-world patch is ~6.4×4.8 mm vs the full
     25.6×16 mm sensor — if the outlet/spray region doesn't fit inside that
     smaller window, the camera needs re-aiming. A rig/framing decision, not
     a software one.
7. **Split the pipeline by morphology**: Mask R-CNN for compact objects;
   classical ridge-detection/skeletonisation for filaments. The 28×28 mask head
   cannot represent a 100:1 aspect ratio thread — architectural, not fixable by
   retraining.
8. **Train v2 from scratch** from COCO weights. Do NOT fine-tune the old model
   ("Dennis") — class count and anchor layout both changed. Archive Dennis
   untouched as the Paper 2 synthetic-only baseline.
9. Anchors: one size per FPN level (the old `[[8,16,32,64]]` broadcast to all
   five levels is wrong). `ResizeShortestEdge` disabled, `RandomCrop` added.

---

## Paths

**Code** → `/Users/benschofield/Documents/GitHub/HPATR/AI/Real_Data_Code/`

**Output** → `/Volumes/LaCie/Experiments/Real_Data/`

```
00_manifest/        run registry + train/validation split
00_frames/          extracted PNGs, one subfolder per run — EVERYTHING
                    downstream reads from here, nothing else touches a .cine
                      125917_NNA_3000sccm/
                        16bit/   frame_0000_n-1.png ...   (primary, for physics)
                        8bit/    frame_0000_n-1.png ...   (for viewing only)
                        extraction_metadata.json
01_candidates/      auto-extracted objects, unreviewed
02_library/         reviewed + sorted
                      droplets/  blobs/  filaments/  rejected/
03_backgrounds/     clean-field frames
04_contact_sheets/  review sheets
05_dataset/         composited training set
                      images/  annotations/
06_validation/      hand-masked real frames, NEVER trained on
07_models/          checkpoints + configs
08_inference/       outputs
```

Numbered because the order is the pipeline.

**Existing scripts** (written in an earlier session, currently in
`HPATR/Trials/Camera_Tester/Analysis/`) — **treat as a throwaway prototype,
do not migrate or patch them**:
- `cine_inspect.py` — diagnostic on a .cine
- `cine_extract.py` — evenly-spaced frame extraction with fixed intensity
  mapping. **Output is 8-bit only** — does not meet the bit-depth requirement
  below. Not reusable for the real pipeline.
- `run_metrics.py` — run-level metrics, two classes only. Already run once
  against `recording_130057` (see `recording_130057_summary.json` alongside
  it) — useful as a sanity-check reference number, nothing more.

`AI/Real_Data_Code/` is the real home for this pipeline's code, written
fresh, one script per step, only when that step is actually reached:
- **`cine_extract.py` is needed now** (Step 0) — write it fresh, 16-bit
  primary + 8-bit viewing output, per the bit-depth section below.
- `cine_inspect.py`-equivalent and the three-class `run_metrics.py` rewrite
  are **not needed yet** — the run's characteristics are already captured
  in "Established facts" above, and the metrics rewrite is Step 8, after v2
  is trained. Don't write them early.

The old prototype folder is currently untracked and has no `.gitignore`
entry — add one (`Trials/Camera_Tester/Analysis/extract/`, `.../inspect/`,
loose frame PNGs, any `*.cine`) before touching anything else, so none of
it gets swept into a commit.

Reference cine:
`/Volumes/LaCie/Experiments/2026/09/09/125917_NNA_3000sccm/shadowgraph/raw/CINE/recording_130057.cine`
(300 rpm, 3000 sccm, 5071 frames)

Reading .cine on macOS: `cine-handler` (`pip install cine-handler`), import as
`from cine_reader import Cine`. Phantom frame numbers can be **negative**
(pre-trigger) — always iterate `first_frame_number..last_frame_number`, never
`range(total_frames)`.

---

## Bit depth — read this before writing any image code

The camera is **12-bit** (4095 levels), stored in `uint16` containers. This was
originally logged as 10-bit in this doc, inferred from typical frame content
(background ~807, most values under ~1000) without checking against the
codebase. Corrected 2026-09-20: `GUI_Clean.py` (`get_live_image`, the live-feed
normaliser, and the RAM-buffer sizing comment) and `docs/lamella_ai_plan.md`
all already documented 12-bit independently, and the full stride-10 extraction
of `recording_130057` found real values up to 1911 — impossible under a true
10-bit ceiling of 1023, unremarkable at 12-bit (47% of full scale). Background
~807 sits at ~20% of the real 4095 ceiling, not near the top of a 1023 one —
this is why clipping was never observed even before the correction.

- **Do all physics in 16-bit**: transmission maps, compositing, measurement.
  The transmission calculation divides one frame by another, so quantisation
  error compounds, and faint out-of-focus objects sit close to the threshold.
- **Convert to 8-bit only at the very end**, when writing composited training
  images for Detectron2, which assumes 0–255 pixel normalisation. Record that
  mapping in the manifest.
- Reading 16-bit PNGs back requires `cv2.imread(path, cv2.IMREAD_UNCHANGED)`.
  Plain `cv2.imread` silently downconverts to 8-bit BGR and undoes the point.

---

## IMMEDIATE NEXT STEP — Step 0: extract frames to disk

Create the folder structure above at `/Volumes/LaCie/Experiments/Real_Data/`,
set up `AI/Real_Data_Code/` in the repo, and add a `.gitignore` entry so no
extracted frames or datasets get committed.

Then extract the reference cine to `00_frames/125917_NNA_3000sccm/` at
**stride 10** (~507 frames), 16-bit primary plus 8-bit for viewing, with one
**fixed intensity mapping applied identically to every frame**, recorded in
`extraction_metadata.json`.

**Why extract to disk at all.** Every downstream step — candidate extraction,
contact sheets, review, background picking, compositing — becomes ordinary file
operations on a folder. The alternative is every script carrying cine-reading
logic, handling negative Phantom frame numbers, and re-decoding the same frames
repeatedly.

**Why the mapping must be fixed once, here.** The transmission maps in Step 2 are
computed against a background frame. If different frames were mapped differently,
transmission values would not be comparable between objects and backgrounds, and
compositing would produce visible seams and wrong intensities. Fixing it at
extraction makes everything downstream inherit one consistent scale.

**Why stride 10 and not 26.** ~20 ms decorrelation at 1300 fps means every 26th
frame for independent *measurement* samples. But for building an object library,
correlation matters much less — you want variety of objects, and seeing a droplet
twice is harmless in a way that double-counting it in a measurement is not.
Extract generously at stride 10; let the measurement code do its own independent
sampling from what is on disk.

**Only one run is usable right now** (125917_NNA_3000sccm, 300 rpm, 3000 sccm,
`recording_130057.cine`). Confirmed 2026-09-20: three other `.cine` files exist
from the same day (`105831`, `142813`, `144056` run folders) but were captured
at different bubbler/spinner positions — not valid for droplet detection, do
not use them. Build the pipeline on `recording_130057` only, then over-train
with new runs captured Tuesday. **Before that session**: confirm the new
recordings use the same bubbler/spinner position as this run, or they will
have the same usability problem and won't serve as over-training/validation
data for this model. The structure should already be per-run so adding valid
runs later is a drop-in, not a refactor.

---

## Step 1 — Validation split

With frames on disk, pick **15 full frames** spread across the sparse/dense range
and record them in `00_manifest/validation_split.json` with source cine, frame
numbers, and a note on why each was chosen. Copy them into `06_validation/frames/`.

**Ben picks these by eye, from the extracted frames — do not automate the
selection.** It is a coverage judgement across the intermittent sparse/dense
range, and he has seen more of the footage than a script can assess.

**Critical**: the manifest is the authoritative exclusion list, and the extractor
in Step 2 must **load it and skip those frames in code**. Do not rely on the
copies in `06_validation/` or on anyone remembering. If validation frames leak
into the training objects, the model gets tested on objects it memorised, the
accuracy figure is worthless, and the contamination is untraceable after the fact.

With only one run available, the split is necessarily by frame rather than by run.
**Note this as a known limitation** — frames from one run share optics state,
dirt and spray condition, so the validation set is less independent than it
should be. Re-do the split by run once a second run exists.

Every extracted object must carry its source frame and run.

---

## Then, in order

2. **Auto-extract object candidates** — threshold + connected components over
   the frames in `00_frames/`, skipping anything in the validation manifest.
   Save each object as a cropped transmission map plus mask, class guess,
   measurements, and provenance (source run + frame number).

   **BUILT 2026-09-20: `AI/Real_Data_Code/extract_candidates.py`.** Settled
   parameters and the reasoning behind each — do not re-derive:

   | Parameter | Value | Why |
   |---|---|---|
   | Background | temporal median, 40 frames | see below |
   | `--detect-threshold` | 0.95 | loose net only; does NOT define object size |
   | `--focus-max` | **0.70** | the out-of-focus cutoff (Ben, 2026-09-20) |
   | Edge rule | per-object half-maximum `(t_min+1)/2` | see below |
   | `--max-pieces` | **1** | fragmentation gate — the out-of-focus detector |
   | `--blur-sigma` | 0.5 | noise suppression; **do not raise** |
   | `--min-area` | 4 px | smallest real fragments are 3-5 px |
   | `--pad` | 12 px | context for reviewing the mask edge in Step 3 |

   - **Fragmentation gate is the real out-of-focus detector**, not `focus-max`.
     When an object's core is shallow, its half-maximum edge lands in noise and
     the refined mask shatters into disconnected specks — visually obvious as a
     "scattered" boundary. Calibrated on three examples Ben labelled by eye
     (2026-09-20), all ~1400 px area so size is not the variable:

     | example | Ben's verdict | t_min | mask pieces |
     |---|---|---|---|
     | `n4109_o1976` | in focus | 0.003 | 1 |
     | `n709_o0417` | **borderline — the limit of acceptable** | 0.134 | 1 |
     | `n4719_o2812` | clearly out of focus | 0.672 | **40** |

     Rejecting `pieces > 1` removes 20% of filaments and 25% of blobs but only
     1.3% of droplets — it targets exactly the large-faint failure mode. It is
     **size-independent**, which a contrast threshold is not: `focus-max` tight
     enough to catch `n4719_o2812` (0.672) would have to sit near Ben's own
     limit (0.134), annihilating every small object. Keep both gates; they
     catch different things.
   - **Class guess: TWO rules, settled 2026-09-21 after three failed attempts.**
     A filament is `major_px >= 20` AND `true_aspect >= 3.0`, where
     `true_aspect = major_px / thread_width` and `thread_width` is twice the
     maximum of the mask's distance transform (the largest inscribed circle).
     That measures how long an object is **relative to its own width, along
     itself** — which holds for any shape, because a thread is thin everywhere
     regardless of the path it takes.
     - `major_px >= 20` (200 um): a filament must actually be long. Without it,
       67 candidates under 10 px area were called filaments with a median major
       axis of **2.2 px** — at that size shape metrics measure noise.
     - **Do not reintroduce `minAreaRect` elongation or solidity.** Both were
       tried and both failed, and the failures are instructive:
       - Bounding-box elongation misses every curved thread — a U-shaped
         filament has a near-square box. Measured on three ligaments Ben
         flagged (a crescent, a V, a loop): elongation **1.36 / 1.44 / 1.49**
         against **1.39** for a genuine compact droplet. Indistinguishable.
         Their true aspects were **6.5 / 6.3 / 7.6** against **1.5**.
       - Solidity caught curves but promoted ragged-edged compact objects; the
         patch for that (an elongation floor) re-broke the curved shapes
         solidity existed to catch. Stacking shape proxies made it worse, not
         better — the single correct measurement replaced all of them.
     - Distribution at the settled threshold (area >= 20 px): droplet median
       true_aspect 1.14 (p90 2.10), filament median 4.64 (p25 3.35). Threshold
       3.0 contaminates 2.3% of droplets.
     - `solidity` and bbox `elongation` are still written to the CSV for
       reference. They are **not** used for classification.

   - **Background is a per-pixel temporal median**, not morphological closing.
     Closing was tried and rejected: it dilates before eroding, so the max
     over the kernel biased the estimate ~8% bright (image median 804 vs
     estimate 866). Ordinary background then fell below threshold, 83% of the
     frame "detected", and every real object merged into one 1.95M-px region.
     The temporal median puts background at exactly T=1.0000 and absorbs the
     static vignette and top-edge smudge for free, so those never detect as
     objects. Cached as `01_candidates/<run>/background_median.tiff`.
   - **Edge is per-object half-maximum, not a global threshold.** A global
     level cannot work: on a thin dark streak it put the boundary out in the
     diffuse halo, giving a mask both oversized and the wrong shape. Each
     object's boundary is set midway between its own darkest pixel and
     background. Standard shadowgraphy/PDIA practice. Consequence: measured
     sizes are smaller than a naive global threshold gives — those earlier
     numbers were inflated, these are the honest ones.
   - **`--blur-sigma` must stay at or below 0.5.** At 1.0 a 3-5 px object is
     spread wide enough that it no longer registers at all — the entire
     30-50 um fragment class silently disappears. Verified by measurement.
   - **Focus gate is size-biased, and this is accepted.** It is a contrast
     test, and small objects have low contrast even in perfect focus (at
     3-5 px you are at the resolution limit, where PSF and pixel sampling
     flatten the core regardless of focus). Pass rates at fm=0.70: 1% of
     4-10 px, 14% of 10-25 px, 24% of 25-100 px, 46% of >100 px.
   - **RESULTING MEASUREMENT FLOOR — state this in the thesis.** Of objects
     passing fm=0.70, equivalent diameter p1 = p5 = **22.6 um**, median
     46.5 um, p95 154 um. Nothing below ~23 um is measured. The response
     variables therefore describe **resolved, in-focus liquid only** — not
     the whole illuminated volume. Ben accepted this explicitly, noting the
     step can be re-run with a looser gate later if the small end matters.
   - Tuning tool: `AI/Real_Data_Code/preview_thresholds.py` renders detection
     overlays (full-frame and 3x zoom) for any frame and parameter set.
     **Always look at both views** — at full-frame scale a 3-5 px object is
     sub-pixel and invisible, and a zoom crop can land on an unrepresentative
     sparse patch (this happened, and made filament counts look alarmingly
     low when they were fine).
   - Both scripts resolve the LaCie via `src/config_loader.find_lacie_drive()`
     so they work unchanged on Mac and the Windows machine. Never hardcode
     `/Volumes/...`. Verify on Windows that it picks the right drive letter.
3. **Review and sort** via contact sheets into `02_library/`. Delete rubbish,
   reclassify, hand-correct masks. Target ~80 droplets across the size range,
   ~40 filaments, ~30 blobs. Over-sample large droplets and borderline cases.
   Keep rejects. **This step is the point of the exercise** — training on raw
   threshold masks just teaches the model to imitate the threshold.
4. **Background library** — 20–30 cleanest frames, checked by eye for faint
   objects. Real backgrounds carry the smudge/vignette/noise for free and teach
   the model they are not objects. With one run only, all backgrounds share the
   same dirt pattern — there is a real risk the model memorises it. Mitigate with
   random crops and mild intensity jitter, and revisit once a second run exists.
5. **Compositor** — background + K objects, random position/rotation/flip,
   multiplicative in transmission, 800×800, COCO annotations, three classes.
   Randomise rotation and flip but **not scale** (scale is the measurement).
   Control the class mix — generate droplet-rich scenes that don't exist in the
   data yet, and a range of densities. Convert to 8-bit on write.
6. **Hand-mask the 15 validation frames** — by hand, not by threshold, full
   frames not crops. Write the labelling protocol first (minimum object size,
   droplet touching filament, out-of-focus cutoff).
   - **Out-of-focus cutoff — DECIDED 2026-09-20 (Ben): out-of-focus objects
     are NOT masked.** The test is "can this be confidently identified as an
     in-focus droplet" — if not, it is not labelled. Rationale: defocus
     inflates apparent size, so any measurement built on those objects is
     untrustworthy, and labelling objects you cannot confidently identify
     trains the model on your uncertainty. Matches standard shadowgraphy /
     PDIA practice of rejecting out-of-focus particles. Implemented in Step 2
     via the hysteresis seed threshold (0.85), which rejects soft-cored
     objects. **Apply the same rule when hand-masking here**, or validation
     and training will disagree about what counts as an object.
   - **Consequence to keep consistent**: the primary response is droplet area
     ÷ total detected liquid area. Out-of-focus liquid must be excluded from
     BOTH numerator and denominator or the ratio is meaningless. The measure
     is then explicitly "within the focal slice" — state that rather than
     implying it covers the whole illuminated volume.
7. **Train v2 from scratch.**
8. **Wire tiled inference into `run_metrics.py`**, keeping the response-variable
   definitions unchanged, then re-process every run with the same code.

---

## Still outstanding from the repo

Never supplied in the earlier export, still wanted:
- `src/ai/process_run.py` and `src/imaging/save_and_analyse.py` (full)
- The synthetic generator's **final composite function** — the order in which
  noise, motion blur, background gradient and intensity scale/shift are applied
- A histogram of annotation equivalent diameters in `blur_annotations.json`,
  split by category

---

## Known issues to keep in mind

- `requirements.txt` is stale — lists `customtkinter` but not PySide6, torch or
  detectron2.
- Two near-duplicate copies each of `inference_detectron2.py` and
  `train_detectron2.py` (repo root vs `AI/Training_Analysis/`). Confirm which is
  live before editing.
- **GUI acquisition — planned two-button shape** (Ben, 2026-09-20). Decided,
  not yet built:
  - **Save .cine** — the archival path. The `.cine` is always kept; it is the
    only thing the analysis-of-record is re-derivable from.
  - **Use RAM** — lab quick-look. Strides over frames already in camera RAM
    after a trigger, in memory, no disk write. `save_tiffs_from_ram` already
    has the loop; this is that loop with a stride and no `imwrite`.
  - **The stride must be a user-editable box, not hardcoded.** Decorrelation
    time falls as droplet velocity rises, so the stride that gives
    independent samples changes with operating condition. See the
    decorrelation note below.
  - **Hard constraint**: the RAM quick-look and the offline cine path must
    share the same measurement code and the same fixed intensity mapping.
    If they diverge, the lab number won't match the thesis number and the
    discrepancy will be expensive to chase. Structure it as a frame-source
    abstraction (RAM iterator / cine iterator / folder iterator) feeding one
    shared metrics function. This lands with Step 8, not before.

- **Decorrelation time — what it is and why the stride depends on it.**
  Liquid crosses the 20.5 mm field of view at ~1 m/s, so the scene refreshes
  in ~20 ms; at 1300 fps that is 26 frames. Frames closer together than that
  share physical droplets, so measuring both double-counts them — inflating
  apparent sample size, shrinking error bars, and overstating confidence when
  ranking two Taguchi runs. Applies to **measurement only**: for building the
  object library, duplicates are harmless, which is why extraction uses
  stride 10 and measurement uses stride 26.
- **TIFFs should never be written in the lab.** The `.cine` is the archival
  format; TIFFs are derived offline. This is a workflow decision already made.

---

## Tone note

Ben is deep in this and does not need concepts re-explained. He has correctly
pushed back on drift into process diagnosis — stay on the measurement and the
pipeline. Flag real problems directly; don't soften them.
