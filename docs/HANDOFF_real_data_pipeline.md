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

## 2026-10-01 — SECOND WINDOWS SESSION. READ THIS FIRST

### Headline: a capture now goes through the chain in ~19 min, not ~60

Same cine every time (`recording_114813.cine`, the Trial_1 capture: 2751
frames, 500 fps, 2560x1600), stride 10 → 276 frames, threshold 0.30, lab PC
(RTX 4070 Ti SUPER, 32 logical CPUs, 128 GB RAM).

| stage | 28 Sep (Trial_1) | 1 Oct, before fixes | **1 Oct, after fixes** |
|---|---|---|---|
| copy cine *(Full Analyse only)* | 1m 39s | 5m 13s | — (analysed in place) |
| extract frames | 2m 09s | 1m 56s | 2m 01s |
| background | 6s | 7s | 0s (reused; fresh ~7s) |
| inference | 33m 09s | 30m 53s | **15m 51s** |
| measurement | 22m 49s | 5m 00s | **54s** |
| **total, real capture** | **~58 min** | **~38 min** | **~19 min** |

**The numbers never moved:** D32 85.57 µm [83.74, 87.38], atomised 7.785%
[6.745, 9.118], on every run, before and after every change, on both machines.
The measurement is deterministic. Outputs: `E:\Experiments\2026\09\28\Trial_CINE`.

### The assumed bottleneck was wrong a THIRD time

The memory-bandwidth theory in the measurement section below ("expect this to
help Windows MORE") was **wrong**. Profiled on the lab PC:

- **Measurement:** 240 of 295 s was **rendering the 276 marked-up PNGs**,
  ~0.9 s and 7.5 MB each, written to the LaCie. On the Mac that was 15% of the
  step; here it was 82%. Without images, measurement is 43 s.
- **Inference:** the per-frame log line times only `detect_frame` (~2.2 s/frame),
  while the wall clock was ~6.7 s/frame. The missing ~4.4 s was **`to_coco`**,
  outside the timed block. For every detection (~320 per frame) it built a
  frame-sized bool mask, then `.astype(uint8)`, then `np.asfortranarray`:
  three 4 MB arrays per object, and 77% of its time was the two copies. It is
  the same full-frame bug as the two before, in the one place the crop fix
  never reached. GPU utilisation was **19%** during inference, so the stage is
  CPU-bound.
- Trial_1's "7.2 s/frame vs 1.4 benchmark" on 28 Sep was this same overhead,
  not a CPU fallback. The log confirms cuda + Eden, and its predictions were
  written after `b1678d4`.

### What changed, and how each was verified

**Inference — `tiled_inference.py`.** `_full_mask(d, np.uint8, "F")` builds the
encoder's layout directly, removing both copies. **Byte-identical** output over
1,178 detections on 4 frames, and `to_coco` is 3.7x faster. Still left:
pycocotools scans the whole frame once per detection, ~1 s/frame. Encoding the
frame-sized RLE straight from the crop is the next lever, worth it only if
16 min per run becomes the constraint.

**Images — `measure_run.py --images {all,extremes}`.** A bare `--images` still
means `all`. `extremes` draws the raw lowest/highest-D32 frames, the guarded
("solid") lowest/highest D32 when they differ, and the lowest/highest atomised
frames: 5 images for Trial_CINE. Those were **byte-identical** to the old code's,
and the CSVs and summary numbers are unchanged. `process_capture` now defaults
to `extremes` (`--images all|extremes`, `--no-images`). Any frame can be
regenerated from the cine, because the 8-bit window is pinned.

**`--ci-stride` is automatic** (closes "FPS → --ci-stride, needed" below).
`process_capture` with `ci_stride=None` sets `max(1, round(0.0205 * fps / stride))`,
taking fps from `extraction_metadata.json`. That gives 1 at 500 fps/stride 10
(unchanged), **10 at stride 1**, and 3 at 1300 fps/stride 10. Verified with a
30-frame stride-1 smoke run: `ci_stride: 10` in the provenance. Cosmetic leftover:
`measure_run` still prints its generic "CIs use ALL frames … 3x too narrow"
warning whenever the CI stride is 1, even when that is correct.

**Full Analyse Cine** (renamed from Test Pipeline). Picking a cine opens a dialog:
- If the cine sits in `<run>/shadowgraph/raw/CINE/` and was analysed before, it
  offers **that stride, reusing the analysis in place**. It skips extraction,
  background and inference and only re-measures with every image drawn: 5–8 min
  for 276 frames. Measured 5m 00s and 7m 50s; the second was probably contention
  on the LaCie.
- **Any other stride** (box defaults to 1) re-runs the whole chain into a **new**
  Trial_n, so a real run's results are never overwritten. A live estimate shows
  as you type; stride 1 on 2,751 frames ≈ 3 h 50 min and ~63 GB.
- Reuse requires `process_capture.can_reuse()`: same stride in the metadata;
  8-bit and 16-bit frame counts both complete; background present; and
  `predictions.json` newer than both `instances.json` and the newest `Eden/*.pth`.
  Trial_1 and Trial_CINE both qualify.
- **It never writes master_log.** Bug found while building it: the post-AI
  auto-save matched its row on the *last experiment's* start time, so a Full
  Analyse run after a real experiment would have **overwritten that real run's
  D32**, through both the auto-save and a later manual Save via
  `_last_ai_results`. Fixed via `summary["_save_to_log"]`. The old
  `_is_test_pipeline` flag was never set True anywhere and has been removed.

**GUI — master_log Shadowgraph column.** It used to take whatever the preview
panel showed, and the preview falls back to the newest result from *any* run, so
runs saved without AI got an old run's image. It now uses
`_lowest_d32_image(run_dir)`, this run only, else NO DATA AVAILABLE. **Rows saved
before this fix keep their wrong images**; delete those by hand.

**GUI — bubbler (spin) motor failsafe.** `_stop_bubbler_failsafe()` sends `STOP`
to the Uno **first thing** in `_on_movement_complete` (when an experiment was
active) and in `_on_experiment_timeout`, before the gas shut-off and the save.
It sends unconditionally rather than trusting `rpm_spinning`, which is GUI
bookkeeping; `STOP` is idempotent on the Uno (`stopMotor()` plus driver
disable). A failed write shows red and logs "stop it manually". Closing the GUI
and the GUI E-stop already stopped it. Ben has a physical E-stop. A firmware
heartbeat watchdog and a serial write timeout were offered and **declined**.

**GUI — the save no longer freezes the UI. This was a safety bug.** The
auto-save at experiment end ran on the GUI thread. master_log is **83 MB with
140 embedded images**, ~9 s just to load and save, and the GUI was **blocked
11.3 s**, measured, including the bubbler's Stop button. Now:
`_collect_save_job()` snapshots every widget and run value on the GUI thread,
and `_write_excel(job)` does the file work on a **single-worker**
`ThreadPoolExecutor` (FIFO, so saves keep their order). Callbacks return to the
GUI thread. The charts use `matplotlib.figure.Figure`, not pyplot's global
registry. `closeEvent` stops all hardware **first**, then waits for a pending
save so master_log is never truncated. **Verified byte-identical against git
HEAD's save**, both run on copies of the real master_log: every cell, width,
height and image (65 rows, 144 images) plus both run_summary sheets. GUI-thread
time went from 11.3 s to 0.00 s. master_log keeps growing (~10 s per save),
so consider not embedding images in it eventually.

**GUI — five `except Exception as e:` lambdas** (lamella model load, lamella
batch ×2, analysis Excel, cone angle) referenced `e` after Python had deleted it,
so the error handler would raise NameError and hide the real message. Fixed
with `lambda e=e:`.

"Settling N s" on a camera save = post-trigger seconds + 2 s of commit margin.
Intended.

### Not verified yet: do these in the lab

- **Click through the real GUI:** the Full Analyse dialog; the bubbler stopping
  by itself when a real experiment ends; buttons staying responsive while
  "Saving to Excel…" shows. Everything above was tested headless, against a
  fake Uno or on file copies, never on the rig.
- **The main AI stride field read 15 on 2026-10-01**, not the default 10. Check
  which stride each Taguchi run was analysed at. Stride changes only CI width,
  not the point estimate, but record it.
- **Optical window contamination.** Large soft grey patches sit at the *same*
  positions in frames 0.9 s apart, so they are static: out-of-focus residue on
  the window or lens. They mostly cancel in T through the background median but
  cost local contrast. Clean the window before more captures. They look like
  blobs at a glance and are not.
- **Home PC (RTX 5070 Ti, Blackwell)** needs PyTorch ≥ 2.7 built for CUDA ≥ 12.8.
  The lab's `torch 2.6.0+cu124` cannot run on it, and detectron2 must be rebuilt
  against whatever torch is installed. Check with
  `torch.zeros(1).cuda() + 1`, because `auto_device()` falls back to the CPU
  silently. Expected time ≈ the lab PC (~15–17 min AI); the CPU matters as much
  as the GPU now.
- GUI startup (1d below) is still unmeasured.

---

## OPERATING CONFIGURATION — settled 2026-09-27. Use this tomorrow.

v3 is good enough to pipe into the GUI **for D32 only**, as a RELATIVE
instrument. Configuration:

| setting | value |
|---|---|
| model | **`<LaCie>/Experiments/AI/Eden/Eden.pth`** (iter 19000; promoted 2026-09-27 from `training_2026_09_25_15_20_37/model_best.pth`, byte-identical copy — the training folder was NOT deleted) |
| inference score floor | **0.05** (`tiled_inference.py` default — keep it; the JSON stores everything and the measurement threshold is applied afterwards) |
| **measurement threshold** | **0.30** |
| **response to report** | **D32** |
| **frames per run** | **>= 75**, ideally 150 |
| do NOT rank on | the atomised fraction — see below |

**Why 0.30.** D32 is flat between 0.20 and 0.30 on both the 20-frame benchmark
(79.7 vs 80.6 um) and the trial frame (78.5 vs 79.4), so the higher value costs
no accuracy while giving better precision and far fewer spurious detections to
explain. It is a round number sitting in a flat region, so small future model
changes will not make it suddenly wrong. The atomised-fraction penalty from
0.20 -> 0.30 is small (-22.6% -> -26.1%).

**Honest caveat:** 0.30 was chosen by looking at the benchmark, which is also
the test set. Acceptable for lab use; NOT acceptable for the thesis without
re-deriving it on composite validation first. See Step 2 below.

**What you are signing up for.** D32 carries roughly **+10% bias** (benchmark)
to **+25%** (trial frame). That cancels when comparing two runs measured
identically, which is why it is fine for ranking and not fine for quoting an
absolute droplet size. Never report the number without the bias.

---

## FIRST FULL END-TO-END RUN — 2026-09-28 afternoon. Trial_1, 4000 sccm

A real capture (2751 frames, 2560x1600, 500 fps, 14.08 GB) taken through the
whole chain for the first time. **Both numbers below are measured, and the
biggest cost is not where anyone expected.**

### Stage breakdown — the whole point of adding stage timing

| stage | time | share |
|---|---|---|
| copy cine | 1m 39s | 3% | *Test Pipeline only; a real capture skips it* |
| **extract frames** | **2m 09s** | **4%** |
| background | 6s | 0% |
| **inference** | **33m 09s** | **55%** |
| **measurement** | **22m 49s** | **38%** |
| TOTAL | 59m 52s | | real capture ~58 min |

**Extraction was never the bottleneck.** It was the stage everyone feared —
2751 frames decoded to 16-bit TIFF plus 8-bit PNG — and it is **4%**, at
2.2 frames/s. Stop worrying about it.

**measure_run is 38% and has NEVER been profiled.** That is exactly the
position tiled_inference was in that morning, when the assumed bottleneck
turned out to be 6% of runtime and the real one was unexamined numpy. Prime
suspect is `--images`: it renders a marked-up full-resolution PNG for EVERY
frame (276 of them) when the Extremes tab looks at 4. A two-pass approach
(measure without images, then render only the extremes) would cut most of it.
**Profile it before acting on that guess** -- that is the whole lesson of the
morning.

**Inference came in at 7.2 s/frame against a predicted 5.1.** The gap is
detection DENSITY, not frame size: this run averaged 322 detections/frame
against the benchmark's 226. The GUI's estimate scales with megapixels only,
so it under-predicts dense runs by ~40%. Recalibrate when there are more runs.

### The measurement itself

    D32 (in-focus)     85.6 um    95% CI [83.7, 87.4]   +/-2.1%
    atomised fraction   7.78 %    95% CI [6.74, 9.12]   +/-15.2%
    276 frames, 28,769 in-focus droplets, 28,885 out of focus

**+/-2.1% at 276 frames beats the precision table above** (which predicted
+/-2.5% at 168 frames). Two runs are separable at ~2.5 um D32 / ~1.66 pp.

Confirms again that the atomised fraction is the weak response: 15% vs 2%.
**Five frames read exactly 100% atomised** -- zero filaments, so the ratio is
1 by construction -- and per-frame values ranged 0.62% to 100%. The
sparse-frame guard works and reports both: raw lowest-D32 frame was
`frame_0154` (32 droplets, atomised 100%), guarded lowest was `frame_0012`
(70 droplets, 57.6 um).

### A path bug worth remembering

The trigger derived the run root with three `dirname()` calls from the cine's
FILE path, landing one level short on `<run>/shadowgraph`. process_capture
then built `<run>/shadowgraph/shadowgraph/raw/CINE`, decided the cine was
missing, and copied 14 GB into a phantom tree -- where all analysis output
then went. Fixed with `Path(cine_path).parents[3]`.

`Path` was also not imported at module level in GUI_Clean.py (only locally
inside two functions), so the fix compiled cleanly and would have raised
NameError in the lab. **py_compile checks syntax, not names.**

### Why progress appeared to hang

A child process writing to a PIPE block-buffers stdout in ~8 KB chunks, so
stages printing a short progress line every 25 frames emitted nothing for
minutes and then a burst. `bufsize=1` on Popen only affects the PARENT's side
and cannot unbuffer the child. Fixed with `PYTHONUNBUFFERED=1` in the stage
environment. Extraction and inference now report percentage, rate and ETA.

### Still open from this run

1. **Profile measure_run** -- 38% of runtime, unexamined.
2. **GPU tile batching** -- now the only remaining inference lever, worth
   maybe 1.3-1.5x, against a 33-minute stage.
3. **Stride.** 276 frames gave +/-2.1%, better than needed. Stride 20 would
   roughly halve both big stages and still land near +/-3%.
4. **Measure the decorrelation time properly** -- see the note below.

---

## SIZE DISTRIBUTIONS — added 2026-09-30, runs automatically

`measure_run.py` now writes the **individual object sizes**, not just
aggregates. Before this, `per_frame.csv` held only counts and per-frame D32,
so recovering a single droplet's diameter meant re-deriving the focus split
from `predictions.json` plus the 16-bit frames — a 7-minute job to answer a
question that should be a file read.

Three files, in `analysis/measurement_<thr>/`:

| file | contents |
|---|---|
| `droplet_sizes.csv` | every droplet: frame, diameter_um, in_focus |
| `object_areas.csv` | every filament/blob instance: frame, class, area_px, area_mm2 |
| `size_histograms.png` | two panels — see below |

**Cost: ~0.4 s and 1.7 MB per run** (0.29 s of it just importing matplotlib),
against a measurement stage of minutes. It is in `measure_run.py`, which
`process_capture.py` already calls as stage 4, so every capture gets it with no
wiring change.

**Matplotlib is optional deliberately.** CSVs are written first and the plot is
attempted second, inside a `try`. A missing matplotlib on the lab machine
prints a note and skips the figure rather than discarding a completed
measurement. **Check it is installed on the Windows PC.**

**Binning.** Droplets get linear 25 µm bins, in-focus green and out-of-focus
magenta, stacked, matching the colours drawn on the frames. Filament and blob
areas share one panel on **log** bins — their areas span ~5 orders of magnitude
(median ~0.04 mm², max ~30), so linear bins put everything in the first one.

**The histogram counts DETECTED INSTANCES, not whole objects.** One long
filament is emitted as several overlapping sub-segments, so the instance count
is not a filament count. The atomised fraction unions them; the histogram does
not. Stated on the figure itself so a stray copy cannot be misread.

`--replot` redraws the figure from the CSVs and measures nothing, so changing
the plot costs seconds. Use it instead of re-running a measurement.

### First result: 4000 vs 4500 sccm are indistinguishable

Both re-measured 2026-09-30; point estimates reproduced exactly (D32 85.57 and
85.77), confirming the measurement is deterministic.

| | p10 | p50 | p90 | 0-25 | 25-50 | 50-75 µm | in-focus |
|---|---|---|---|---|---|---|---|
| 4000 sccm | 22.6 | 40.7 | 79.8 | 17.3% | 45.9% | 24.8% | 49.9% |
| 4500 sccm | 22.6 | 40.7 | 79.0 | 16.5% | 45.1% | 26.8% | 48.6% |

Identical medians to one decimal and matching bin-for-bin. This is **stronger
evidence than the D32 comparison alone** — two different distributions can
share a D32 by coincidence, but these agree across the whole shape.

**The competing explanation, which is not yet excluded.** This may show the
*measurement* is insensitive rather than the conditions being identical. The
mode sits in the 25-50 µm bin, and the false-positive median is 33.9 µm — so
the peak is where the detector's noise floor lives, and the distribution may be
reporting detector characteristics more than spray physics. **3000 vs 4500 is
the test that discriminates between those two readings**, which is a second,
independent reason to run it beyond the bias-stability question.

---

## MEASUREMENT IS 14.4x FASTER — 2026-09-30. And the guess was wrong again

**424 s -> 29.4 s on Trial_1 (276 frames), measurement unchanged.** Two fixes,
both found by profiling, neither where anyone expected.

### The guess that was wrong, for the second time

The handoff named `--images` as the prime suspect for `measure_run`'s 38%.
Measured on the same machine, same data: **43.3 s with images vs 37.0 s
without**. Rendering 276 full-resolution PNGs is **15%**, not the bulk. Chasing
it would have won 15% and left a 14x sitting untouched.

That is now **twice** the assumed bottleneck has been wrong — inference in the
morning (assumed GPU, actually numpy, 6% vs 94%) and measurement here. Treat
"obviously it's X" as a hypothesis to test, never a reason to start editing.

### Fix 1 — crop before the per-pixel work (2.5x)

Every detection ran `.astype()`, `.any()` and `T[mask]` over the **whole
2560x1600 frame**. `T[mb].min()` boolean-indexed 4.1 M elements to read the
darkest pixel of a droplet whose median bounding box is **16 px**.

Now `toBbox` (which reads the RLE without decoding it, and is exact, so it
cannot clip) gives the box and every operation runs inside it. **424 s ->
172 s**, verified byte-identical on nine summary fields.

Same bug, same shape, same file family as the one that made tiled inference
15.9x slow. Worth assuming it exists elsewhere.

### Fix 2 — stop decoding frame-sized masks at all (a further 5.9x)

Profiling the 172 s version put **78% in `pycocotools.decode`**, which always
materialises a full 4.1 M-pixel array regardless of object size. Measured over
6,574 detections:

| | |
|---|---|
| pixels decode writes | 26,927,104,000 |
| pixels actually needed | 10,874,420 |
| **overshoot** | **2,476x** |
| median RLE length | 19 bytes (~13 runs) |

`tiled_inference` **already held the crop** — that is what made it 15.9x faster
— and was converting back to frame-sized and discarding it when writing COCO.
It now emits both:

    "segmentation"      frame-sized RLE   (unchanged; COCO-valid, score_v2.py unaffected)
    "segmentation_crop" RLE over the object's own bounding box
    "crop_xy"           [x, y] origin of that crop

`measure_run` reads the crop when present and never builds a frame-sized array.
**Files without the field fall back automatically** to Fix 1's path — slower,
identical answer — so old predictions still work untouched.

Cost: predictions.json grows ~42% (19 MB -> 27 MB per run).

**Verification.** All 263 masks on a fresh frame were decoded both ways — full
frame, and crop placed back at its offset — and compared pixel by pixel: **zero
mismatches**. The two representations are the same mask.

### Chain timings on the Mac, 2026-09-30, Trial_1

| stage | time | share |
|---|---|---|
| extract frames | ~2.1 min | 3.6% |
| background | 6 s | 0.2% |
| **inference (CPU)** | **57.7 min** | **95.5%** |
| measurement | **29 s** | **0.8%** |
| TOTAL | ~60.5 min | |

Measurement has gone from 38% of the chain to **0.8%**. It is no longer worth
optimising. On the Mac, CPU inference is now effectively the entire cost
(12.5 s/frame, median 16 tiles) — which is simply the argument for doing real
runs on the Windows GPU, where inference is 1.4 s/frame.

**[WRONG — 2026-10-01: profiled on the lab PC, Windows was slow because of
image rendering (82% of the step) and to_coco's frame copies, not memory
bandwidth. See the 2026-10-01 section at the top.]**
**Expect this to help Windows MORE than the Mac.** Windows' measurement ran at
4.96 s/frame against the Mac's 1.54 — backwards, given the hardware. The likely
cause is memory bandwidth: the old code was shovelling 4 MB arrays per
detection, and Apple Silicon has far more bandwidth than a typical desktop. Both
fixes cut memory traffic by orders of magnitude, so the machine that was most
starved should gain most. **Unverified — measure it.**

### Still available, probably not needed

- **Multiprocessing over frames.** Frames are independent. But the GUI turns out
  to use ~1 core (20 `threading.Thread`s, all GIL-bound and I/O-blocked; no
  multiprocessing anywhere), while torch already uses 5 threads and OpenCV 15 —
  so adding more risks oversubscription. And at 29 s, measurement no longer
  justifies it.
- **A hand-written cropped-RLE decoder** (the other route to Fix 2). Not needed
  now that the crop is written at source, and strictly riskier.

---

## RUN METADATA — what is recorded, changed 2026-09-30

Five independent variables. Before today only three were recorded, and the
2026-09 captures are not fully comparable as a result — see the RPM note below.

| variable | where it lives now |
|---|---|
| Gas flow (sccm) | folder name + `run_summary.xlsx` + full time series w/ camera windows |
| Silicone flow rate (steps/s) | folder name + `run_summary.xlsx` ("Speed (steps/s)") |
| Exit orifice | folder name + `run_summary.xlsx` |
| **Bubbler height (mm)** | **NEW** — GUI field, persisted, folder name + both spreadsheets |
| **Bubbler RPM** | **NEW to the record** — GUI already had it, it was never saved |

**Run folder naming is now:**

    133346_4500sccm_1000rpm_6000sps_or1.2_bh40

Missing values become explicit tokens (`norpm`, `nosps`, `noor`, `nobh`), never
dropped segments — an unrecorded run must not look identical to a deliberate
one. All three naming sites share one `_run_id()` method. ~52 chars, well
inside Windows' path limit.

**`run_summary.xlsx` is authoritative; the folder name is a scannable copy.** Do
not parse the name back as data — a renamed folder would disagree silently.

**`Distance (mm)` is now `Motor Travel (mm)`** everywhere, including the master
log, because bubbler height is also a distance in mm and the two were one
mistake away from being confused. Motor Travel is the plunger stroke.

**master_log.xlsx went 12 -> 14 columns** (bubbler height and RPM at C and D,
beside Orifice). Migration tested on a copy of the real 60-row file: all 130
image anchors shifted correctly. The header row is now stamped from a single
`MASTER_HEADERS` constant on every save — `openpyxl`'s `insert_cols()` gives a
new column no style at all, which is why 'Mass Flow Graph' was the one unbold,
unfilled header in the file, and why every future migration would have repeated
it.

**Why this matters, concretely.** RPM was previously recorded only in free-text
Notes, and inconsistently: `101947`/`103608` say "500rpm", `133346` says
"1000rpm later on" (ambiguous, and implies it CHANGED mid-run), and `125917` and
`114715` say nothing at all. Two of the three runs compared on 2026-09-30 have
no RPM on record, so **the 4000-vs-4500 "clean pair" claim is not verifiable**.
Not backfilled by decision — this is for future runs only.

---

## SAVING IS NOW AUTOMATIC — 2026-09-30

**The spreadsheets used to stamp the wrong time.** The run folder stamped
`datetime.now()` at experiment START; `_save_to_excel` called `datetime.now()`
again when Save was clicked. They differed by the whole run duration plus
however long the notes took. Both now use `self._run_started_at`, so the folder
name, `run_summary.xlsx` and the `master_log.xlsx` row all agree.

**Two automatic saves, one row.**

1. **Experiment end** (`_on_movement_complete`) — gets the run on disk before
   anyone can forget. No D32 and no shadowgraph yet: the motor stops minutes
   before inference and measurement finish.
2. **AI chain completion** (`_on_pipeline_complete`) — fills in D32, the
   atomised fraction and the lowest-D32 frame.

A manual Save afterwards is only needed for notes typed later. **All of them
UPDATE the same row**, matched on the start timestamp, rather than appending.
`_save_to_excel` previously appended unconditionally, so before this an
accidental double-click produced two rows for one run.

Updating also purges images already anchored to that row — openpyxl keeps
images in a flat list with no notion of replacement, so they would otherwise
stack in the same cells.

Both auto-saves are wrapped in try/except. The end-of-experiment one runs during
cleanup while the gas is being shut off; a spreadsheet error must never
interrupt that.

### master_log.xlsx is now 16 columns

    A Timestamp            E Flow Range        I  D32 (um)        M Cone Image
    B Orifice              F Pressure Range    J  Atomised (%)    N Shadowgraph
    C Bubbler Height (mm)  G Speed (steps/s)   K  Avg Lamella     O Pressure Graph
    D Bubbler RPM          H Motor Travel (mm) L  Notes           P Mass Flow Graph

Everything the run PRODUCED (I, J, K) sits right of everything that was SET.
D32 and atomised are written as **plain numbers**, not "85.6 +/-2.1%", so they
sort and plot as Taguchi responses; the CIs stay in `summary.json`.

`_last_ai_results` is cleared at experiment start, so a run whose AI chain has
not finished leaves those cells **blank rather than inheriting the previous
run's D32**. A stale number in that sheet would be far worse than an empty cell.

**Migrations chain 12 -> 14 -> 16 on first save.** Tested against a copy of the
real 60-row log: all 130 image anchors landed correctly and every header kept
its style. **Back up `master_log.xlsx` before the first run tomorrow** — it is
a one-way change to the file holding every experiment logged.

### Dead code removed, and one piece that must NOT be

Removed: `_run_pipeline()` (26 lines, the Dennis-era chain), `_poll_serial()`
(body was `pass`), `self.serial_reader_thread`, `self.pulse_amplitude`, and four
unused imports. An AST scan now reports zero unreferenced methods and zero
unused imports.

`_run_pipeline` was worse than unused: it emitted `ai_run()`'s output through
`_pipeline_done`, which now lands in a handler expecting a `measure_run`
summary. Anything calling it would have failed confusingly. Removing it leaves
`src/ai/process_run.py` (15 KB) with **no callers anywhere in the repo** — left
on disk, not deleted.

**`self._arduino_thread/_worker`, `_rpm_thread/_worker`, `_mfc_thread/_worker`
look dead and are load-bearing.** Nothing reads them; holding the reference IS
the point. Without it Python garbage-collects the QThread mid-run and PySide
aborts with "QThread: Destroyed while thread is still running". All three sites
now carry a DO NOT REMOVE comment, because every static-analysis pass will flag
them again.

Stale help text fixed: the tooltips and How To still described
`ai_result.png`, `FINAL_OPTIMIZED_RESULT.png`, `Outputs/` and `LIGHT_BG`/
`DARK_BG` from the retired CV pipeline, and told you to
`conda activate Detectron2` on Windows — an env that **does not exist on the lab
PC**. `_find_latest_result()` was looking for those same retired filenames, so
the Refresh button and startup preview silently found nothing; it now reads
`summary.json` and returns the lowest-D32 frame.

---

## GUI IS SLOW TO START — analysed 2026-09-30, NOT yet measured on Windows

**The Mac is the wrong machine to profile this on**, which is the main finding.
Measured here: 1.6 s total, of which widget construction is only 0.46 s. On the
lab PC it is "much slower" — because the Mac skips most of the expensive work
entirely.

| cost | Mac | Windows |
|---|---|---|
| `from pyphantom import ...` | **skipped** (ImportError, not installed) | loads the whole camera SDK at module import |
| `import pyvisa` | skipped | loads the VISA runtime |
| `from Cone_4 import ...` | present | pulls in **scipy**, hundreds of files |
| `find_lacie_drive()` at import | 0.0 ms (`/Volumes/LaCie` exists) | probes **23 drive letters**, before the window exists |
| `comports()` x3 during construction | fast | SetupAPI/registry walk each, worst case with FTDI devices — and this rig has three |
| pandas + matplotlib.pyplot | 0.53 s | worse from a slower disk |
| Windows Defender | n/a | **scans every file on import** — multiplies the whole chain |

`_get_serial_ports()` is called once per `connection_card`, and there are three
(Portenta, Arduino Uno, AliCat MFC).

**Separately, the UI stalls periodically.** `_poll_lacie` runs **on the main
thread every 5 s** and calls `find_lacie_drive()`. Free on the Mac; on Windows
it probes 23 drive letters, and a disconnected mapped network drive makes
`.exists()` block on an SMB timeout. That matches "*sometimes* unresponsive"
exactly -- sometimes, because it depends on drive state.

Checked and CLEARED as causes: the live graphs redraw from a bounded 60 s
buffer, and the 100 ms log drain is cheap. `_refresh_shadowgraph` walks the
whole Experiments tree at startup but is correctly on a worker thread -- it will
hammer the LaCie without freezing the UI.

### Fixes, in order of expected payoff on Windows

0. **Add the repo and Python folders to Windows Defender exclusions.** Not a
   code change, free, reversible, and it may beat everything below combined.
   **Do this first so we learn how much is AV rather than code.**
1. **Call `comports()` once**, not three times — build the list and share it.
2. **Defer `pyphantom` and `pyvisa`** to first camera/AFG connect.
   `importlib.util.find_spec` can set the AVAILABLE flags without loading.
3. **Defer `pandas` and `matplotlib`** into `_save_to_excel` -- they appear in
   only two methods and nothing at startup touches either. ~0.5 s here.
4. **Defer `Cone_4`/scipy** to first use of the Cone tab.
5. **Move `_poll_lacie` off the main thread** (and poll far less often than 5 s
   -- it changes when a disk is physically unplugged).

**MEASURE BEFORE REWRITING IMPORT STRUCTURE.** None of the above is measured on
Windows; it is reasoning about what the code does there. Today alone the assumed
bottleneck was wrong twice (inference: assumed GPU, actually numpy; measurement:
assumed `--images`, actually full-frame decode). Print a timestamp at module
import, after each optional-SDK import, after construction, and after the first
paint, and let the numbers choose.

---

## RESULTS OF THE FIRST WINDOWS SESSION — 2026-09-28. READ THIS FIRST

Everything in the checklist below was done. Both headline numbers were
**measured on the lab machine**, not estimated, and both beat the estimate.

| | before | after | |
|---|---|---|---|
| camera download | 7.8 MB/s (62 Mbit) | **71.7 MB/s (574 Mbit)** | **9.2x** |
| inference | 22.8 s/frame | **1.4 s/frame** | **15.9x** |
| a 250-frame run | 95 min | **6 min** | |

**The lab machine.** RTX 4070 Ti SUPER, 17.2 GB. `torch 2.6.0+cu124`,
`detectron2 0.6`, `cv2 4.8.1`, `numpy 1.26.4`, `cine-handler 0.1.1` — all in
**system Python 3.11** (`C:\Users\55154111\AppData\Local\Programs\Python\
Python311\python.exe`). There is NO `Detectron` conda env on this machine; the
handoff assumed one and was wrong. `process_capture` spawns stages with
`sys.executable`, so launching the GUI by that absolute path keeps every stage
on the right interpreter. Launching it as a bare `python GUI_Clean.py` from
`(base)` would put the whole chain on conda's Python, which has no torch.

**Network: done.** Camera is on the built-in Intel I219-LM at `100.100.100.1`
static /16, internet on the Realtek USB dongle via DHCP. Both links negotiate
1 Gbps. Camera answers at `100.100.231.39`. The prediction of "8-15x for the
price of a cable" landed at 9.2x. Jumbo frames were NOT done — at 574 Mbit
there may still be headroom to ~900, but this is no longer the bottleneck.

**Inference: the GPU was never the problem.** See the corrected Step 4 below.
The 30x estimate was right about the hardware and wrong about where the time
went; the fix was in our own code and is now committed.

**Still outstanding from the checklist:** item 6 (Test Pipeline end-to-end on a
real .cine) has not been run. A 2970-frame, 15.2 GB capture from the speed test
is sitting in the session scratchpad on C: if a test subject is wanted.

---

## WINDOWS LAB CHECKLIST — do these in order, 2026-09-28
### (items 1-5 and 7 COMPLETE — see the results section above)

Written immediately before the first Windows session. Everything measured in
this project so far is Mac CPU; none of the below has been verified on the lab
machine.

**1. Ethernet link speed — do this FIRST, it is the biggest single win.**
See the section below. Network Connections -> camera adapter -> Status. If it
reads 100 Mbps, that is a 30-minute save that should take 2-4 minutes.

**2. `git pull` on `Testing`.** The Windows checkout predates the pinned
window, the `frames/` layout, `process_capture.py`, the GUI wiring and the Eden
promotion. Without this none of the rest applies.

**3. LaCie drive letter.** It will be E: or F: depending on what else is
plugged in. **No code change needed** — `find_lacie_drive()`
(`src/config_loader.py:27`) loops D: through Z: and matches on drive *content*
(a `LaCie`, `Phantom` or `Shadowgraph` folder at the root), not on a fixed
letter. Confirm it returns non-`None`.

**4. CUDA actually visible to torch.** `torch.cuda.is_available()` must return
`True`. Check it explicitly: `tiled_inference.auto_device()` falls back to CPU
**silently** if CUDA is missing, so a misconfigured environment looks like a
working one that is merely slow.

**5. The cine-reading library.** The likeliest missing dependency. Extraction
has only ever run on the Mac, so `cine_extract.py`'s reader has never been
exercised in the Windows conda env (`Detectron`). torch / detectron2 / opencv /
pycocotools should already be there from training.

**6. Test Pipeline button on an old .cine.** The real end-to-end check: file
dialog -> `Trial_n` folder under today's date -> all four stages -> numbers back
in the GUI.

**7. Time it.** This is Step 4 below, and it gates the whole Taguchi workflow.
Record seconds/frame on GPU and set the default `--stride` from the real number
rather than the estimate.

---

## DATA TRANSFER — FIXED 2026-09-28, measured at 71.7 MB/s. Diagnosis kept below

**Resolved.** The adapters were swapped as prescribed and a 2970-frame,
15,207 MB cine came off the camera in **212 s = 71.7 MB/s = 574 Mbit/s**,
steady the whole way. The 14.08 GB reference file would now take **3.3 min
against the original 30** — a 9.2x change, inside the predicted 8-15x band.

The diagnosis below stands as written and is kept because the reasoning is the
transferable part: measure the file and divide, before theorising about
hardware. The GUI now prints the achieved MB/s after every .cine save, so a
silent regression to 100 Mbit announces itself instead of needing a stopwatch
to find a second time.

Note 574 Mbit is ~57% of theoretical Gigabit, so jumbo frames may still have
something to give. Second-order; do not spend time on it while a 6-minute
inference run is the longer pole.

---

## DATA TRANSFER — the camera save is on a 100 Mbit link. Diagnosed 2026-09-28

**The measurement.** `recording_102003.cine` is **14,085,229,832 bytes**
(14.08 GB): 2751 frames, 500 fps, 2560x1600 at 10-bit packed = 5.12 MB/frame.
That file took **~30 minutes** to save from the camera.

    14.08 GB / 1800 s = 7.8 MB/s = 62 Mbit/s

**That number is the diagnosis.** 100BASE-TX gives 12.5 MB/s theoretical and
7-11 MB/s once TCP/IP and the Phantom protocol have taken their cut. 7.8 MB/s is
a textbook 100 Mbit link. On Gigabit the same file is **~2 minutes**; allowing
for the LaCie sustaining maybe 80-120 MB/s in practice, call it 3-4 minutes.
**An 8-15x win for the price of a cable.**

**The Python code is NOT the bottleneck and there is nothing to optimise in it.**
`PhantomController.save_recording()` (`src/gui/GUI_Clean.py:1088`) hands the
entire transfer to the SDK via `save_non_blocking()` and then does nothing but
poll `save_percentage` every 0.25 s. No per-frame or per-byte Python work is in
the path, and `progress_cb` fires only when the integer percentage changes
(<= 100 Qt events for the whole save). Do not go looking for a speedup here.

**A correction, on the record.** Earlier the same day the LaCie's rated 130 MB/s
was floated as the likely bottleneck, with an SSD as the fix. With the real
numbers that is **wrong** — at 7.8 MB/s the drive is running at about 6% of what
it can already absorb. **Do not buy an SSD for this.** Fix the network. The
general lesson: measure the file and divide, before theorising about hardware.

### The fix

The camera is not on the motherboard's built-in port (that one carries the
internet), which is itself supporting evidence — many cheap USB Ethernet
dongles are 100 Mbit only.

**Swap them.** Camera into the built-in Gigabit port; internet onto the dongle.
Correct allocation of bandwidth: the camera moves 14 GB in a burst, browsing
and email are fine on 100 Mbit. Confirm the built-in port really is Gigabit
(most are; many recent boards are 2.5 GbE).

**Windows adapter config must swap too** — the static IP currently lives on the
wrong adapter:

| adapter | setting |
|---|---|
| built-in port (now camera) | static IPv4 `100.100.100.2`, mask `255.255.255.0`, **no gateway** |
| dongle (now internet) | back to DHCP / "Obtain an IP address automatically" |

Leaving the gateway off the camera adapter stops Windows trying to route
internet traffic down it.

**No code change is needed for any of this.** `PhantomController.connect()`
(`src/gui/GUI_Clean.py:1022`) accepts an `ip_address` argument but **never uses
it** — the body calls `self.ph.discover()`, which finds the camera by broadcast.
The `100.100.100.1` field in the Camera tab is cosmetic (saved in settings,
not used to connect). The camera will be found on whichever adapter can see it.

Also worth checking: a Cat5 cable caps at 100 Mbit (you need Cat5e/Cat6), a
single damaged pair silently drops a Gigabit link to 100 Mbit, and any old
switch in the path caps the whole link at its own speed.

**Jumbo frames — second-order, do it only after the link is confirmed Gigabit.**
Standard Ethernet carries at most 1500 bytes per packet (the MTU); jumbo frames
raise that to ~9000. Every packet costs fixed overhead — headers plus a CPU
interrupt — so for a 14 GB file it is ~9.4 M packets versus ~1.6 M, about 6x
fewer. Phantom recommend it for download performance. **It is lossless and has
nothing to do with image data** — no effect on resolution or bit depth, the
bytes arriving are bit-identical; it only changes how they are parcelled in
transit. Both ends must agree on MTU or you get dropped packets, so with a
direct camera-to-PC cable there are only two ends to set. If anything goes
flaky, turn it off — the Gigabit link alone is the bulk of the win.

---

## BACKUP / SYNC POLICY — sync the irreplaceable, regenerate the rest

FreeFileSync was observed running at **~12 KB/s** over the recent output.

**That is a small-files problem, not a bandwidth problem.** No disk or cable is
inherently 12 KB/s. Every file costs an open, a metadata write, a data write, a
close and a directory update, and on a spinning disk several of those can each
cost a ~10 ms seek — capping throughput at roughly 50-100 *files*/s regardless
of size. This pipeline is a small-file machine: one run at stride 10 is 276 PNGs
plus 276 TIFFs; a full stride-1 extraction is 2751 of each — **5,502 files from
a single run**, before marked-up output images. Real-time antivirus scanning
each file on write multiplies it further.

**The fix is to stop syncing derived data.**

| regenerable — EXCLUDE from sync | irreplaceable — MUST sync |
|---|---|
| `frames/8bit/*.png` | the `.cine` files |
| `frames/16bit/*.tiff` | hand-labelled annotation JSONs |
| `background_median.tiff` | `Eden/Eden.pth` (hours of GPU time) |
| `predictions.json` | code (already in git) |
| marked-up output images | `summary.json` / `per_frame.csv` (tiny, keep) |

**This is what pinning the 8-bit window bought, and it is worth stating plainly.**
Because the window is now fixed at `[27.0, 876.0]` rather than computed per-run,
re-extracting a cine produces **byte-identical** frames to the ones deleted.
Before pinning, regenerated frames would have differed from the originals and
discarding them would have been genuinely lossy. Derived data is now safe to
throw away and rebuild on demand.

Excluding `frames/` alone turns a sync of tens of thousands of small files into
a handful of large `.cine` files, which run at full disk speed — one 14 GB
sequential file has essentially no per-file overhead.

Two settings to check in FreeFileSync:

1. **Comparison mode** must be *file size and date*, not *content*. Comparing by
   content reads both sides of every file in full on every run.
2. **Exclusion filter** for `frames`, `8bit`, `16bit` and the marked-up image
   folders.

**Saving to the drive mid-sync is safe but slow.** FreeFileSync scans, builds a
list, then works the list; files created after the scan are picked up next run.
Nothing corrupts. The real problem is **contention** — two workloads on one
spinning disk do far worse than half speed each, because the head seeks between
them. **Pause the sync during lab captures.**

**Verify the `.cine` files have actually finished syncing.** They are the only
truly irreplaceable experimental data, and a job crawling through PNGs for hours
may never have reached them.

---

## FOLDER LAYOUT — CHANGED 2026-09-28. Runs before this date differ

    <run>/shadowgraph/raw/CINE/recording_*.cine     the archival source, ALONE
    <run>/shadowgraph/raw/frames/16bit/             native TIFFs
    <run>/shadowgraph/raw/frames/8bit/              PNGs, pinned window
    <run>/shadowgraph/raw/instances.json            manifest (an INPUT)
    <run>/shadowgraph/raw/background_median.tiff
    <run>/shadowgraph/analysis/predictions.json
    <run>/shadowgraph/analysis/measurement_<thr>/   csv + summary + images

**`raw/` is now the `--val-dir`**, not `raw/CINE/`. Frames used to live inside
CINE/ purely to satisfy the `<val-dir>/frames/8bit` + `instances.json`
contract that 06_validation and 09_experiments also satisfy — the thing that
lets a capture be analysed by exactly the same code as the thesis validation
set. Moving the boundary up one level keeps that contract intact (verified by
test) while getting 30 GB of regenerable frames out of the same folder as the
one irreplaceable file.

Backup rule becomes simply: **sync `raw/CINE/`, skip the rest of `raw/`.**

`TIFFs/` and `Brightest_Frame/` are no longer created eagerly — with Save
TIFFs off they were made empty on every run and never written to.

---

## GUI — what exists as of 2026-09-28

- **Stride field** beside "Run AI analysis after capture", with a live note
  giving the frame gap in decorrelation times, frames analysed, and estimated
  inference time at the current fps AND resolution. Warns below one
  decorrelation time and names the stride that matches. Persists in
  camera_settings.json as `ai_stride`.
- **Extremes tab** (after Cone): lowest/highest D32 and highest/lowest
  atomised fraction, scaled to the tab width, each captioned with the frame's
  own numbers. A zero-filament frame is flagged inline as degenerate rather
  than hidden — seeing where the measure breaks is the point.
- **Three-line stats block** under the preview: 95% CI (precision) /
  droplet spread (mean, SD, min, max) / measured-from (frames, stride,
  in-focus and out-of-focus counts). Deliberately separated — the SD is a
  distribution statistic and must never be read as an error bar on D32, which
  is a ratio of moments and sits above the mean by construction.
- **Progress + ETA** on .cine save, TIFF save, frame extraction and inference.
  The .cine save also prints the achieved MB/s every time, so a silent
  regression to the 100 Mbit link announces itself instead of needing a
  stopwatch to find twice.
- New `summary.json` fields: `droplet_d_mean_um`, `droplet_d_std_um`,
  `droplet_d_min_um`, `droplet_d_max_um`, `atomised_extreme_frames`,
  `_stage_seconds`, `_stride`.

**Min/max droplet diameter are single detections** — the minimum sits on the
model's noise floor (FP median 33.9 um, 71% under 50 um), so treat them as a
statement about detector limits as much as about the spray. The SD is the
trustworthy shape statistic.

---

## THE CAPTURE-TO-MEASUREMENT CHAIN — built 2026-09-27

`process_capture.py` is **the** entry point. The GUI calls it; the CLI calls it.
Nothing else re-implements the chain. That is a hard constraint: if the lab
quick-look and the offline path diverge, the lab number will not match the
thesis number and the discrepancy will be expensive to chase.

    .cine -> cine_extract -> background -> tiled_inference -> measure_run

**Folder layout produced** (`Trial_n` for test runs, real name for captures):

    <run>/shadowgraph/raw/CINE/recording_*.cine        archival source
    <run>/shadowgraph/raw/CINE/frames/16bit/           native TIFFs (measurement)
    <run>/shadowgraph/raw/CINE/frames/8bit/            PNGs, pinned window (model input)
    <run>/shadowgraph/raw/CINE/instances.json          COCO manifest, images-only
    <run>/shadowgraph/raw/CINE/background_median.tiff
    <run>/shadowgraph/analysis/predictions.json
    <run>/shadowgraph/analysis/measurement_<thr>/      csv + summary + images

`<run>/shadowgraph/raw/TIFFs/` stays separate: manual/optional camera exports,
never read by the AI chain.

### The pinned 8-bit window — the important change

`PINNED_WINDOW = (27.0, 876.0)` in `cine_extract.py`, taken from the
`05_dataset_v3` composites. **Every past run computed its own percentile window**
(e.g. `[66.0, 901.0]` for `101947_NNA_4500sccm`), which made runs incomparable
to each other *and* to the data the model was trained on. Worked example: an
object at transmission 0.3 (raw ~242) maps to pixel **65** under the training
window but **54** under that run's own — a ~17% contrast difference for an
identical object.

`--window-per-run` restores the old behaviour; do not use it for anything that
will be compared. `check_window_fit()` samples 20 frames and warns if more than
`CLIP_WARN_FRACTION` (2%) of pixels clip at either end. Measured on the 4500sccm
run: **0.00% below, 1.28% above** — comfortably inside tolerance, so pinning is
evidenced for this rig, not just assumed.

Second-order benefit: re-extraction is now deterministic, which is what makes
the derived-data-is-disposable backup policy above valid.

### Device selection

`auto_device()` in `tiled_inference.py` returns `cuda` if
`torch.cuda.is_available()` else `cpu` — chosen by capability, not by OS. MPS is
deliberately NOT auto-selected (detectron2's support is patchy). `--device`
still overrides. **It falls back silently**, so verify CUDA explicitly on
Windows rather than inferring it from the fact that inference ran.

### Model resolution

`default_model_dir()` prefers `<LaCie>/Experiments/AI/Eden/`, falling back to
the newest `training_*` folder with a printed notice. `find_weights()` accepts
`<dir>/<dirname>.pth` first, then `model_best.pth`, matching the existing
`Dennis/Dennis.pth` convention. `config.yaml` must travel with the weights — it
pins the anchor layout and the 800 px input; without it the model loads with
wrong anchors and detects almost nothing.

**Eden is on the LaCie drive only and is not in git** (335 MB). The fallback
copy at `training_2026_09_25_15_20_37/` is on the same drive, so it is not
protection against drive failure. See the backup table above.

---

## THE MEASUREMENT PIPELINE — built 2026-09-27

Two new tools. Neither needs ground truth; both are the intended GUI entry
points.

### `measure_run.py` — measure one run

    python measure_run.py --pred <...>/v3_predictions.json \
      --val-dir 09_experiments/20_new_frames \
      --background <...>/01_candidates/<run>/background_median.tiff \
      --sixteen-bit-dir <...>/00_frames/<run>/16bit \
      --score-thresh 0.30 --images

Splits every predicted droplet by its OWN `t_min`, using the same focus test
the hand labels use:

| | |
|---|---|
| **D32** | **IN-FOCUS droplets only** (green). A size statistic must only see objects whose size means something. |
| **atomised fraction** | **ALL droplets** (green + magenta) against all liquid. An out-of-focus droplet is still atomised liquid; dropping it would understate the numerator while its filaments stayed in the denominator. |

Different populations on purpose. Outputs `per_frame.csv`, `summary.json` (with
full provenance — model, threshold, focus cutoff, um/px, timestamp) and
optionally one marked-up full-res PNG per frame carrying **only** D32 and the
atomised fraction top-left.

**Measured on the 20-frame set at 0.30:** D32 (in-focus) **90.5 um**, 95% CI
[82.8, 98.0], +/-8.4%. Atomised **10.08%**, CI [6.89, 15.06], +/-40.5%.
2,264 in focus / 2,496 out (52.4%). 30-39 s for 20 frames.

**Why in-focus-only D32, even though it scores WORSE against the benchmark**
(+23% vs +10% for all droplets): the all-droplets number is only closer because
noise-floor detections happen to offset the small droplets the model misses —
two errors cancelling, and there is no guarantee the cancellation is stable
across operating conditions, which is exactly what would scramble a ranking.
In-focus-only is a cleanly defined population with ONE knowable bias mechanism
(small-droplet recall ~75%). For a ranking instrument that is the better
property. **It measures "D32 of confidently-sized droplets", not the spray's
true D32** — never quote it as an absolute size.

### `compare_runs.py` — compare N runs

    python compare_runs.py A/summary.json B/summary.json C/summary.json
    python compare_runs.py --label 3000sccm A/... --label 4500sccm B/...

Ranks them and does every pairwise test, calling a difference REAL only when
the 95% CIs do not overlap. Deliberately conservative: it fails to split runs
rather than inventing an order.

**It refuses to compare runs measured with different `--score-thresh`,
`--focus-max` or `um_per_px`**, because the D32 bias only cancels between runs
measured identically — otherwise the ranking is meaningless and nothing would
have flagged it.

This exists as a tool rather than a glance at two numbers because D32 measures
to ~+/-8% at 20 frames: two runs reading 88 and 93 um look different and are
not. Eyeballing point estimates is the easiest way to build a Taguchi table out
of noise, and it is very hard to detect afterwards.

### Scale: it handles any number of frames

Nothing caps the frame count. The run-level bootstrap was rewritten to resample
per-frame `(Sum d^3, Sum d^2)` pairs rather than pooled droplet lists —
mathematically identical (D32 is the ratio of the summed pairs), but it turns
each resample from "concatenate 240,000 areas" into "add up N pairs". At 1,000
frames the naive version would have done ~500M operations per run; it now does
~2M. Verified to give bit-identical CIs on the 20-frame set.

### Still needed before a real campaign

1. **Block bootstrap — PARTIALLY ADDRESSED 2026-09-27 via `--ci-stride`.**
   `measure_run.py` now takes `--ci-stride N`: the POINT ESTIMATE always pools
   every frame (more data only helps it); the CONFIDENCE INTERVAL bootstraps
   only every Nth frame, so it sees genuinely independent samples instead of
   ~3x-too-narrow correlated ones. Demonstrated: duplicating 20 frames 10x
   (zero new information) narrowed a test interval 3.2x -- that is the failure
   this avoids. Cheap and honest, but throws away real precision that a proper
   block bootstrap (resampling CONTIGUOUS chunks, not single frames) would
   keep. Do the block bootstrap when there is time; `--ci-stride` is the
   correct stopgap for tomorrow.
   - **`--ci-stride` is not yet automatic from FPS.** See "FPS -> ci-stride,
     needed" below.
2. **Streaming for very large runs** — fine at 20, holds all droplet areas in
   memory at 10,000. (The bootstrap itself was already rewritten to work on
   per-frame `(Sum d^3, Sum d^2)` pairs rather than pooled droplet lists, so it
   scales; this item is about the raw per-droplet storage, not the bootstrap.)
3. **Sanity guards** — flag frames with zero filaments (the atomised fraction is
   trivially 100% there) and frames with too few droplets for a meaningful
   per-frame number.
4. **The video -> frames pipeline** — cine to 8-bit + 16-bit frames with the
   correct fixed intensity window, feeding this. Not started.
5. ~~**FPS -> `--ci-stride`, needed.**~~ **DONE 2026-10-01, in
   `process_capture.auto_ci_stride()`** (not in measure_run, which still takes
   it by hand when run directly). Decorrelation time is fixed physically
   (~20.5 ms, liquid crossing the 20.5 mm FOV at ~1 m/s), so the correct stride
   in FRAMES depends on fps: `round(0.0205 * fps)` -- 10 at 500 fps, 26 at
   1300 fps (matches the figure already used elsewhere in this document).
   `frame_rate_fps` is ALREADY recorded per run in
   `00_frames/<run>/extraction_metadata.json`, so `measure_run.py` should read
   it and compute the default stride itself rather than requiring `--fps` or
   `--ci-stride` by hand. Currently manual. Small task, do it before relying on
   CIs for a real campaign.
6. **Per-run min/max D32 frame, needed in `measure_run.py`.** The older
   `run_stats.py` reports the highest- and lowest-D32 frame (with a
   sparse-frame guard, restricting to frames with >= half the median droplet
   count so a near-empty frame cannot masquerade as "finest spray"). The newer
   production tool, `measure_run.py`, does not yet report this. **Workaround
   with no code changes**: `measurement_<thresh>/per_frame.csv` already has a
   `d32_in_focus_um` column per frame -- sort it in Excel for the extremes
   today. Port the guarded logic from `run_stats.py` into `measure_run.py`
   before relying on the extremes for anything written up.

---

## MEASUREMENT PRECISION — 20 unlabelled frames, 2026-09-27

**The verdict is split: D32 is usable, the atomised fraction is not.**

`09_experiments/20_new_frames/` — 20 frames from `101947_NNA_4500sccm`, same
selection rule as the trial frame (40-50 frames clear of every
library-contributing frame; benchmark frames and the trial frame excluded).
No hand labels, so this measures PRECISION, not accuracy. New tool:
`run_stats.py`, the production counterpart to `score_v2.py`.

Pooled over 4,760 droplets at score >= 0.30:

| | value | 95% CI | precision | min. detectable difference |
|---|---|---|---|---|
| **D32** | **79.7 um** | [74.0, 85.7] | **+/-7.3%** | **~8.2 um** |
| atomised fraction | 10.08 % | [7.57, 14.09] | **+/-32.4%** | ~4.6 pp |

CIs are bootstrap over FRAMES, not droplets — droplets within a frame share an
illumination field, a focal plane and a moment of the spray, so resampling
droplets would treat correlated samples as independent and give a falsely
tight interval.

### The primary/secondary responses are the wrong way round

This document has said since Step 6 that the PRIMARY Taguchi response is the
area-weighted atomised fraction and D32 is secondary. **On this evidence that
is backwards, and it should be changed before any array is run.**

Per-frame atomised fraction across the 20 frames ranged from **1.99% to
100.00%**. The 100% is `frame_0184_n1839`: 56 droplets, **zero filaments**, so
the ratio is trivially 1. Atomisation is intermittent (already an established
fact in this document) and a ratio with an intermittent denominator is
unstable by construction. Two runs would need to differ by ~4.6 percentage
points on a ~10% value — a 45% relative change — before the difference could
be called.

D32's area weighting is what saves it: the same property that makes it
insensitive to the 2x false-positive over-count also makes it insensitive to
frame-to-frame filament intermittency.

### Frames needed, from the measured CI (noise ~ 1/sqrt(n))

| target precision | D32 | atomised |
|---|---|---|
| +/-5% | 42 frames | 850 frames |
| +/-3.8% | 75 frames | — |
| +/-2.5% | 168 frames | — |
| +/-10% | — | 213 frames |

**75-150 frames per run** puts D32 at +/-3-4%. The atomised fraction needs 200+
for anything respectable and is not worth the compute until the filament-area
work lands.

**Do not trust a 20-frame number.** Pooled D32 was still drifting at frame 20
(87.9 um after 2 frames -> 79.7 after 20), exactly consistent with the +/-7.3%
interval.

### Timing, and why the GPU test matters

**745 s for 20 frames = ~35 s/frame** on Mac CPU, all 2560x1600, 13-32 tiles
each (12-92 s depending on density). So 75-150 frames per run is **45-90
minutes per condition** on CPU. At the estimated GPU speed that is 2-4 minutes.
That is the entire argument for Step 4 in one line.

---

## NEXT ACTIONS — updated 2026-10-01

### 0. Analyse the Taguchi run Ben has just captured. TOP PRIORITY

**D32 does not need skeletonisation. Start ranking on it now.** D32 is computed
from the model's in-focus **droplet** masks only (see `measure_run.py`). A
skeleton pass replaces the **filament** area, which feeds only the atomised
fraction's denominator. D32 is also the response that can actually rank runs
(±2% at 276 frames, against ±15% for atomised). Item 2 below makes it the
primary response.

1. **Inventory first.** List the Taguchi run folders. For each, record whether
   `analysis/measurement_0.30/summary.json` exists, its stride (`_stride`, or
   `raw/extraction_metadata.json`), frame count, and the five set variables from
   `run_summary.xlsx` (gas sccm, silicone steps/s, orifice, bubbler height,
   bubbler RPM). Runs whose AI never ran: use Full Analyse Cine (reuses nothing,
   new Trial folder) or run `process_capture.py <cine> --run-dir <run>` directly.
   **Check the stride.** The main field read 15 on 2026-10-01.
2. **Rank on D32** with `compare_runs.py --label <cond> <summary.json> …`. It
   refuses mismatched threshold, focus cut-off or µm/px, and calls a difference
   real only when the 95% CIs do not overlap. Then the Taguchi analysis proper
   (S/N ratios, main effects) on D32 across the array.
3. **Before quoting the atomised fraction across the array, build the skeleton
   filament area.** The design is already settled; see "Split the pipeline by
   morphology" (item 7 of the original plan, further down). In short:
   - Keep the tiled model for **droplets**; discard its filament masks for area.
   - On the **whole frame** (filaments reach 1000+ px and would be cut at tile
     seams), segment liquid with `extract_candidates.py`'s existing rule
     (T < 0.95, edge at each object's own half-maximum). Do not invent a second
     threshold.
   - **Subtract the droplet masks first**, then treat the remainder as
     filament/blob, or the denominator counts the same liquid twice. Fix OPEN
     BUG 1 (cross-class union) at the same time: it is the same denominator.
   - Area = ∫ local width along the skeleton, width from the distance
     transform (`thread_width` in `extract_candidates.py`).
   - **Build it inside `measure_run.py`.** It only needs the 16-bit frames and
     the background, both already on disk, and not the model. Every Taguchi run
     can then be re-measured with `process_capture.py --reuse` at about a minute
     each, with no re-inference.
   - **Validate before trusting it:** score it against the hand labels on the
     20-frame benchmark and record how the atomised-fraction gap (−23 to −26%)
     moves. Then re-measure **every** run with it. Never mix old-method and
     new-method atomised numbers in one table.
4. The 3000 vs 4500 sccm bias-stability test (item 4) matters more now: the
   Taguchi ranking assumes D32's bias is the same across conditions.

### Status of the 2026-09-30 list

- **1c (full runthrough on Windows): DONE 2026-10-01** except the GUI
  click-through. See the section at the top.
- **1d (GUI startup on the lab PC): still open.**

## NEXT ACTIONS — updated 2026-09-27

**Status:** v3 trained, scored on the 20-frame benchmark, validated on an unseen
labelled frame, and characterised for precision on 20 unlabelled frames.
**Cleared for lab use on D32 only** — see OPERATING CONFIGURATION above.

Answered since this list was written:

- **Step 1 (are the FPs real?)** — YES, mostly. Only ~18% of FPs land on
  real-but-unmeasurable objects; 102 of 124 at score 0.30 are genuinely
  spurious. v4 still needs the small-droplet FP work. See the trial results.
- **Step 3 (measurability trial)** — DONE. 83.5% blind human/code agreement,
  and the definition turns out to move D32 by only ~3%.

Still open, in priority order:

0. ~~**Fix the 100 Mbit camera link**~~ **DONE 2026-09-28** — 9.2x, measured at
   71.7 MB/s. See DATA TRANSFER above.
1. ~~**Step 4 — GPU benchmark**~~ **DONE 2026-09-28** — 15.9x, commit `b1678d4`.
   The bottleneck was our own mask handling, not the GPU. See the corrected
   Step 4, and note the "batch the tiles" advice there is now retracted.

   **Both throughput blockers are cleared. A 250-frame condition is ~6 min of
   inference plus ~3.3 min to pull the .cine. The remaining work is all
   measurement science, not engineering — the items below are now the
   critical path.**

1a. ~~**Run the end-to-end Test Pipeline on a real .cine**~~ **DONE
   2026-09-28** — Trial_1, 4000 sccm. See the first section of this document
   for the stage breakdown and results.
1b. ~~**Profile `measure_run`**~~ **DONE 2026-09-30 — 14.4x, 424 s -> 29.4 s.**
   The `--images` suspicion was wrong (15%); the real cost was full-frame numpy
   and full-frame RLE decoding. See the measurement-speed section above. It is
   now 0.8% of the chain and not worth further work.

1c. **FULL RUNTHROUGH TEST — do this first on the Windows machine.**
   Everything below has changed since the last end-to-end run and none of it has
   been exercised together on the lab PC:

   - `measure_run` speedups (both fixes)
   - `tiled_inference` emitting `segmentation_crop` / `crop_xy`
   - size-distribution CSVs + histograms (needs **matplotlib** — confirm it is
     installed, or the figure silently skips)
   - the new GUI Bubbler height field, and that it persists
   - the new run folder naming, `<time>_<flow>sccm_<rpm>rpm_<sps>sps_or<x>_bh<y>`
   - `run_summary.xlsx` gaining Bubbler Height + Bubbler RPM
   - **master_log.xlsx migrating 12 -> 14 columns on first save** — back the file
     up before the first run; the migration is tested but only against a copy
   - `Distance (mm)` -> `Motor Travel (mm)` throughout

   Use the Test Pipeline button on an old .cine first, then a real capture.
   **Record the stage timings** — the Windows measurement figure is the one
   number that would confirm or kill the memory-bandwidth theory above.
   Also grab `python -c "import os; print(os.cpu_count())"` while there.

   **Back up `master_log.xlsx` first** — it migrates 12 -> 16 columns on the
   first save and that is one-way.

   Also new and untested together: automatic saving at experiment end and again
   at AI-chain completion, updating one row rather than appending; the
   Timestamp now being the experiment's START; D32 and atomised fraction as
   columns I and J.

1d. **MEASURE GUI STARTUP ON THE LAB PC.** See the GUI-slowness section above.
   It is "much slower" there than the 1.6 s measured on the Mac, and the Mac
   cannot reproduce it — `pyphantom` and `pyvisa` are not installed here, so
   the two most expensive imports never run.

   Order of work:
   - **First, add the repo + Python folders to Windows Defender exclusions.**
     Free, reversible, and it may be most of the problem. Re-time afterwards.
   - Then instrument: print a timestamp at module import, after each optional
     SDK import, after construction, and after first paint.
   - Only then change import structure. The candidate fixes are listed above
     in expected-payoff order, but **do not start editing until the numbers
     say which one matters** — the assumed bottleneck was wrong twice today.
2. **Swap the primary and secondary Taguchi responses.** The atomised fraction
   measures at +/-32% and cannot rank runs; D32 measures at +/-7.3% and can.
   This document has it the wrong way round throughout — fix before any array.
3. **Step 2 below — re-derive the 0.30 threshold on composite validation**, so
   the thesis does not rest on a value chosen by looking at the test set.
4. **Bias stability across 3000 vs 4500 sccm** — still the decisive test for
   whether D32 can rank runs across conditions, not just within one.
5. The cross-class union bug (OPEN BUGS), then bootstrap CIs on the benchmark.

### Step 1 — decide whether the FP rate is worth a v4  [ANSWERED: yes, mostly real]

v3's extra false positives are **1,284 of 1,442 droplets, median 33.9 um, 71%
under 50 um**: the loosened focus gate firing near the noise floor. That is a
targeted fix, not a redesign. Options, cheapest first:

1. **Size-dependent score threshold** — require a higher score below ~40 um.
   No retraining. Try it on the composite validation set, NOT the benchmark.
2. **Tighten the focus gate partway** for v4 and rebuild the library. Risks
   giving back the small-droplet recall gain (0.61 -> 0.75), so measure both.
3. Accept it and run measurement at a higher threshold — costs filament recall,
   which is the thing v3 just fixed. Least attractive.

### Step 2 — pick the measurement operating point WITHOUT using the benchmark

`score_v2.py` calls its best-F1 threshold a "candidate MEASUREMENT operating
point". **For v3 that label is wrong**: best F1 lands at 0.90, which is v3's
*worst* atomised-fraction error (-51.8%), while 0.30 gives -26.1%. F1 optimises
detection; the Taguchi responses are area-weighted. These are different
objectives and they disagree.

Choosing 0.30 because it scores best on the benchmark would turn the benchmark
into a tuning set. **Derive the threshold on composite validation**, then apply
it to the benchmark once.

### Step 3 — the measurability trial  [DONE 2026-09-27 — see RESULTS]

One new, carefully labelled frame splitting droplets into "visible" and
"should be measured", to test the human judgement against the `t_min < 0.70`
criterion and against the model. Full design in the PLANNED section below. It
needs no model change — measurability is an attribute, not a class.

Do this alongside Step 1: it answers the same false-positive question from the
other direction, and if it shows the FPs are mostly real-but-unmeasurable
objects, the v4 priorities change.

### Step 4 — GPU INFERENCE  [DONE 2026-09-28 — 15.9x, but NOT for the expected reason]

**Result: 22.8 s/frame -> 1.4 s/frame. A 250-frame run is 6 min, not 95.**
Committed as `b1678d4`. Read the next four paragraphs before optimising
anything else in this pipeline, because the first measurement was misleading
and the handoff's own recommendation was wrong.

**The GPU was never the bottleneck.** First clean run on the RTX 4070 Ti SUPER
came in at 22.8 s/frame — *slower per tile than the Mac CPU*, with GPU
utilisation sitting at **2%**. That looks like a broken CUDA setup. It was not:
a bare forward pass on an 800x800 tile, timed with `cuda.synchronize()`,
measures **56 ms** — almost exactly the 50 ms estimated below. The card was
doing what was predicted and then waiting.

**cProfile found the real cost, and it was our own code.** On frame_0056
(391 detections): `_merge` 31.9 s, `_collect` 25.9 s, model forward 3.9 s.
**94% was numpy on full-frame masks.** `_collect` allocated a
`np.zeros((1600, 2560))` — 4.1 MB — for *every detection*, so a blob 40 px
across cost the same as the whole frame, and every later step then scanned
4.1M pixels to reach a few hundred. 1.6 GB of masks resident per frame.

**The fix was to store each mask as a crop plus a frame offset.** Same pixels,
different container. Output verified **byte-identical**: 4514 detections, same
order, same RLE strings, same areas, unchanged in every class and size band —
so no past number is invalidated and nothing needs re-running. 456 s -> 29 s on
the 20-frame benchmark; memory 9.8 GB -> 1.8 GB; GPU util 2% -> 22%.

**CORRECTION — ignore the "batch the tiles" advice at the end of this section.**
It was written before anything was profiled. Batching optimises the forward
pass, which was **6%** of runtime, so the ceiling on that entire approach was a
6% gain — a week of work for nothing. The lesson generalises: performance
intuition here was wrong by a factor of fifteen, and one cProfile run found it
in two minutes. **Profile before optimising.** Post-fix the forward pass is
~75% of what remains, so batching is *now* the only real lever left, worth
perhaps 1.3-1.5x. Not obviously worth it against a 6-minute run.

---

#### The original estimate, kept for the record

**Everything measured so far is Mac CPU. Nothing has ever been timed on the
GPU.** This is not a convenience question — it decides whether the Taguchi
workflow is viable at all.

Measured Mac CPU: **~1.4 s/tile** average (50 s for a 24-tile 2560x1600 frame;
5.5 min for all 20 benchmark frames).

Estimated GPU, anchored on THIS project's own training throughput rather than a
generic figure: v3 trained at **0.31 s/iter at IMS_PER_BATCH=2** = 0.155 s per
800x800 image forward+backward. Inference is forward-only, roughly a third of
that, so **~50 ms/tile**.

| | per tile | 20-frame benchmark | 1,000-frame run |
|---|---|---|---|
| Mac CPU (measured) | ~1.4 s | 5.5 min | **~4.7 h** |
| GPU (estimated ~30x) | ~50 ms | ~15 s | **~10 min** |

4.7 hours per condition is not a workflow. 10 minutes is. **Verify this before
planning any Taguchi campaign around CPU inference.**

    python tiled_inference.py --all --device cuda \
      --out <scratch>/v3_gpu_timing.json

(`--model-dir` is no longer needed — it defaults to `Eden/` now. Omitting
`--device` auto-detects, but pass `cuda` explicitly here so the run fails loudly
rather than silently timing the CPU.)

Compare per-frame times against the CPU log. Caveats: the one-third
forward-only ratio is a rule of thumb, data loading will not shrink, and the
4.9 s model load becomes proportionally larger. If it comes in far below 30x,
the next lever is batching tiles — `DefaultPredictor` runs one image per
forward pass and tiles are independent.

### Step 5 — MAX_ITER never got changed

The v3 run used **MAX_ITER = 20000**, not the 30000 the edit table specified.
The dataset and anchor edits did land. Cost looks small: AP gained +0.23 segm
over the last 4k iterations and the curve is flat from ~12k, so 30k was probably
worth under half a point. **Do not re-run v3 to find out** — spend the GPU time
on v4.

---

## v3 RESULTS — scored 2026-09-25. Compare future models to THIS

Run: `training_2026_09_25_15_20_37`. Best checkpoint iter 19000 (selected on
composite validation, not on the benchmark). Scored once, at score >= 0.05,
`model_best.pth`, same tiler and same thresholds as the v2 baseline.

### READ THIS BEFORE READING ANY score_v2.py OUTPUT

**Sections 4 and 5 evaluate at each model's OWN best-F1 threshold.** v2's is
0.30, v3's is 0.90. So the size-band and measurement tables it prints for two
models are **not comparable** — they are at different operating points. Taken at
face value the printout says v3 made the atomised fraction worse (-51.8% vs
v2's -37.8%). Recomputed at matched thresholds, v3 is **better at every
threshold from 0.05 to 0.70**. Always match the threshold before comparing.

### Detection — both models on the same 20 frames

| | v2 | v3 | |
|---|---|---|---|
| bbox AP (all) | 15.5 | **17.3** | +12% |
| segm AP (all) | 10.4 | **13.7** | +32% |
| bbox AP (measurable) | 19.8 | **22.6** | +14% |
| segm AP (measurable) | 13.8 | **17.6** | +28% |
| segm AP50 (all) | 31.7 | **39.0** | +23% |

Per class (bbox/segm AP): droplet 12.1/11.0 -> 11.6/11.5 (flat), filament
25.8/15.0 -> **36.2/25.6**, blob 8.8/5.2 -> 4.1/3.9 (worse).

### The two rows v3 existed to fix — both fixed

Recall at a **matched** 0.30 threshold:

| band | class | n | v2 | v3 | delta |
|---|---|---|---|---|---|
| 50-100 um | **filament** | 30 | 0.067 | **0.500** | +0.43 |
| 100-200 um | **filament** | 94 | 0.415 | **0.883** | +0.47 |
| 200-500 um | filament | 61 | 0.738 | **0.885** | +0.15 |
| 0-50 um | droplet | 975 | 0.608 | **0.746** | +0.14 |
| 50-100 um | droplet | 532 | 0.923 | 0.906 | -0.02 |
| 100-200 um | droplet | 61 | 0.902 | 0.885 | -0.02 |
| >500 um | filament | 17 | 0.647 | 0.529 | -0.12 |
| 200-500 um | blob | 27 | 0.519 | 0.333 | -0.19 |
| >500 um | blob | 5 | 0.800 | 0.200 | -0.60 |

Short filaments 0.07 -> 0.50 confirms the class-definition diagnosis and closes
it. Blob rows are n=5 and n=27 — do not over-read them.

### The cost — precision

| threshold | model | precision | recall | F1 |
|---|---|---|---|---|
| 0.30 | v2 | **0.653** | 0.692 | **0.672** |
| 0.30 | v3 | 0.420 | **0.791** | 0.549 |
| 0.90 | v2 | **0.736** | 0.561 | 0.637 |
| 0.90 | v3 | 0.642 | **0.606** | 0.624 |

**v2 still has the better best-F1** (0.672 vs 0.624). The precision dip was
predicted; this is larger than "a dip".

**Part of it is a scoring artifact, and it was measured.** Section 3 matches
against measurable GT only, so a correct detection of a real-but-unmeasurable
object scores as a false positive — and v3 was trained through a looser focus
gate to see exactly those. Matching against ALL GT instead:

| model | vs measurable GT | vs all GT |
|---|---|---|
| v2 | P 0.653 / R 0.692 | P 0.729 / R 0.411 |
| v3 | P 0.420 / R 0.791 | P 0.578 / R 0.579 |

**540 of v3's 1,982 "false positives" (27%) are real objects** that merely are
not measurable, against 146 for v2. Real, but it does not explain the gap away:
1,442 genuine FPs remain vs v2's 521.

### Measurement — at matched thresholds. This is the Taguchi-relevant table

Ground truth: 1,571 droplets, D32 **73.3 um**, atomised fraction **8.33%**.

| thr | model | droplets | D32 | D32 err | atomised | atom err |
|---|---|---|---|---|---|---|
| 0.05 | v2 | 1948 | 87.7 | +19.6% | 5.63% | -32.4% |
| 0.05 | v3 | 4053 | 104.4 | +42.3% | **7.54%** | **-9.4%** |
| 0.30 | v2 | 1627 | 89.3 | +21.7% | 5.18% | -37.8% |
| 0.30 | **v3** | 3053 | **80.6** | **+9.9%** | **6.15%** | **-26.1%** |
| 0.50 | v2 | 1504 | 90.2 | +23.0% | 5.03% | -39.6% |
| 0.50 | v3 | 2609 | 82.4 | +12.3% | 5.69% | -31.6% |
| 0.90 | v2 | 1175 | 92.6 | +26.2% | 4.73% | -43.2% |
| 0.90 | v3 | 1448 | 81.6 | +11.3% | 4.02% | -51.8% |

**D32 error less than halved** at 0.30 (+21.7% -> +9.9%). Atomised fraction
improved at every threshold up to 0.70.

**Two cautions on that.** v3 predicts **3,053 droplets against a truth of
1,571** at 0.30 — nearly 2x over-detection, so any **count-based metric is
unusable**. D32 and area fraction are area-weighted and the spurious detections
are small (median 33.9 um), so they survive it — but that is a property of the
metric, not evidence the detections are right.

### What this closes and what it opens

The library changes worked. The composite-to-real gap narrowed (segm AP 10.4 ->
13.7 against composite-val 66.8) — so **image realism is NOT the binding
constraint** and the "redirect effort to the compositor" contingency written
before the run is not triggered. The next lever is the small-droplet false
positive rate.

### Training run health

20,000 iterations, 15:20-17:28, no divergence. Loss 0.73 late (v2: 0.45) and
0.31 s/it (v2: 0.22) — both exactly what 62 instances/image predicts. AP
plateaus from ~12k. Dataset verified: 4,000 images, 249,183 instances,
69% droplet / 27% filament / 3.8% blob.

**The composite-validation AP is not a v2-vs-v3 comparison** — v3 scores 66.8
segm against v2's 70.0, but each is scored on its own split and v3's is
deliberately harder. Lower here means harder exam, not worse model. Only the
benchmark above compares them.

---

## MEASURABILITY TRIAL — RESULTS, 2026-09-27

Run on `frame_0015_n149` (4500 sccm, provably unseen). 394 shapes after dust
removal: 102 droplet_measure, 267 droplet_seen, 21 filament, 4 blob.
Ground truth at `09_experiments/02_Chosen_Frame/instances.json`.

### 1. The measurability definition barely matters for D32

| definition | n | D32 |
|---|---|---|
| code `measurable` (t_min <= 0.70, no border) | 126 | 63.7 um |
| human, revised after refinement | 102 | 62.7 um |
| human, blind first pass | 155 | 64.9 um |

**A 2.2 um spread (~3%) across definitions differing by 50% in how many
droplets they admit.** The objects the three definitions disagree about are all
small and faint, and small droplets contribute almost nothing to Sum(d^3)/Sum(d^2).
So the 0.70-cutoff argument, while still live for the atomised fraction, is
**not a threat to D32**. One less thing gating the Taguchi work.

### 2. Human vs code: 83.5% agreement, and the trap in measuring it

| | code: measurable | code: not |
|---|---|---|
| **human: measure** | 110 | **45** |
| **human: seen** | 16 | 198 |

83.5% agreement, 16.5% disagreement, lopsided ~3:1 toward over-calling
measurability. Not boundary scatter — the disagreeing group sits at t_min
median 0.754, well clear of 0.70.

**The trap:** the working labels were later revised using refinement's outcome,
and refinement's main rejection test IS `t_min > FOCUS_MAX` — the same test as
`measurable`. Measured on the revised labels the "agreement" reads 93.5% with
**zero** disagreements in the critical cell, which measures nothing but our own
circular definition. Only the BLIND first pass is independent evidence.
`validation_to_coco.py --human-verdict-from` records both; quote the blind row.

### 3. Dust is over-called as measurable, ~3:1

Of the 38 dust specks removed, **26 had been labelled `droplet_measure`** vs 12
`droplet_seen` — 14.4% of measure labels were dust against 5.3% of seen labels.
Sensor dust is a crisp, sharp, dark speck, which is the exact appearance
signature of a well-focused droplet. The by-eye measurability call keys on
"sharp and dark", and anything sharp and dark passes.

### 4. Refinement succeeds or fails on CONTRAST, not size

Of 155 blind `droplet_measure`: 103 refined, 52 did not.

| | refined | unrefined |
|---|---|---|
| t_min | 0.489 | 0.754 |
| edge sharpness | 1.253 | 0.696 |
| equiv. diameter | 60.8 um | 40.7 um |
| radial position | 0.458 | 0.481 |

Refined fraction is a **cliff, not a slope**: 93-97% below t_min 0.65, 80% at
0.65-0.70, **0% above 0.70**. 100% of the refined group reaches the cutoff; 87%
of the unrefined never does. Size correlates but is a proxy — small and faint
co-occur, and a 3-5 px object physically cannot reach a deep t_min. Radial
position has no effect, which rules out vignetting.

### 5. v3 on this frame: better than benchmark, and the FP question answered

| | trial frame | 20-frame benchmark |
|---|---|---|
| bbox AP | **22.0** | 17.3 |
| segm AP | **17.5** | 13.7 |
| filament bbox/segm | **52.2 / 37.6** | 36.2 / 25.6 |
| droplet bbox/segm | 13.7 / 15.0 | 11.6 / 11.5 |

Better on a frame it has never seen. Recall reaches 0.88.

**Where the false positives land** (the open question from the v3 review):

| thr | TP | FP | FP on a REAL object | truly spurious | adjusted precision | raw |
|---|---|---|---|---|---|---|
| 0.05 | 127 | 197 | 29 | 168 | 0.481 | 0.392 |
| **0.30** | 125 | 124 | **22** | **102** | **0.590** | 0.502 |
| 0.70 | 117 | 68 | 15 | 53 | 0.714 | 0.632 |

**The labelling-convention artifact is real but small — ~18% of FPs.** The other
102 are genuinely spurious: 92 droplets, median 44 um, 56% under 50 um — the
same noise-floor signature as the benchmark.

**So the precision problem is mostly REAL, not a scoring artifact.** v4 should
target the small-droplet false-positive rate; the three options in Step 1 all
stand. (Of the 22 FPs that did hit real objects, 13 were ones the human blindly
called `droplet_measure` — the population where human, model and code all
disagree.)

---

## PLANNED — the measurability trial (design, 2026-09-26)

One new frame, labelled more carefully than the benchmark 20, to test whether
the **human** judgement of "this droplet's size is trustworthy" agrees with the
**code** criterion currently making that call, and with what the model detects.

### This needs NO model change

The model predicts three classes and never needs to know about this. What is
wanted already exists as an **attribute**, not a class: every annotation carries
`measurable`, and `score_v2.py` already uses it — detection is scored against all
annotations, size statistics against measurable ones only. The protocol's
division of labour has always been: human decides existence and class, code
decides measurability, `refine_labels.py` decides the edge.

The trial moves the measurability call into the human column **for one frame**
and records both, so they can be compared.

### Label schema

Label with two droplet names, everything else unchanged:

    labelme <frame dir> \
      --labels droplet_seen,droplet_measure,filament,blob \
      --validate-label exact \
      --output <labels dir>

At import, map **both** to `category_id = 1` and set a new per-annotation field
`human_measurable` from which name was used. The model sees no difference.

**They are a hierarchy, not two kinds of object.** Every `droplet_measure` is
also visible by eye; total droplets = seen + measure. Do not report them as
separate populations.

### What `refine_labels.py` does -- and why it does NOT invalidate this

A recurring misreading, so state it plainly: **refinement only moves edges. It
never decides measurability and never touches a label.**

Per shape it rasterises what you drew as a *search region*, takes the connected
component containing your centroid, finds that component's darkest pixel `t_min`
in the 16-bit transmission data, and thresholds at the **half-maximum,
`(t_min + 1) / 2`**.

Half-maximum is **per-object and relative**. A droplet at `t_min = 0.95` is
thresholded at 0.975 and keeps a sensible boundary. This is a different thing
from the `t_min < 0.70` measurability cutoff, which is computed separately and
afterwards. The trial survives refinement intact.

**The one real caveat:** refinement is least reliable on exactly the faint
objects this trial is about. It flags rather than edits when it finds nothing
near the focus cutoff, and half-maximum on an object barely darker than
background gives an unstable edge. Expect a higher flag rate than usual, and
treat the *areas* of `droplet_seen` objects as soft — they do not enter D32 by
definition, so this costs nothing as long as nobody later computes statistics
from them.

`<name>.original.json` is written on first touch, so pre-refinement shapes are
always recoverable and the two can be compared directly.

### Candidate frames — SELECTED 2026-09-26

`09_experiments/01_Unseen_Frames/` holds 20 candidates from
`101947_NNA_4500sccm` (the 4500 sccm run), plus `manifest.json` recording the
provenance check. **Pick one.**

Contamination was checked route by route, not assumed:

| route | finding |
|---|---|
| Library objects | Only **28 frames** of this run fed the library (320 of the 750 objects), at n99, n199 … n2699 — **every 100 cine frames**, not every 10. Those are the only frames whose *content* reached the model. |
| Compositing backgrounds | **None from this run.** All 25 came from `125917_NNA_3000sccm`. Route clear. |
| Benchmark | 5 frames (n559, n769, n859, n1649, n1719) excluded. |

**The offset-5 idea was the right instinct but the wrong number.** This run is
**500 fps**, so the stride-10 extraction grid is 20 ms apart — exactly one
decorrelation time. An offset-5 frame sits 10 ms from its neighbours, i.e. *half*
a decorrelation time, and would share physical droplets with them.

It is also unnecessary: because the library sampled every 100 frames rather than
every 10, most extracted frames never contributed anything. Selecting for
maximum distance from the 28 that did gives **40-50 frames (80-100 ms, 4-5
decorrelation times)** of separation — far cleaner than offset-5 would have been,
and the frames already exist as extracted PNGs, so nothing needs re-extracting
from the cine.

Choose on content. `dark_pixel_pct` in the manifest spans 0.019% (essentially
empty — nothing to label) to 3.96% (very dense — punishing to label carefully).
Something in the **0.3-1.7%** band is the sensible working range.

16-bit source for refinement stays at `00_frames/101947_NNA_4500sccm/16bit/` —
deliberately not duplicated into the experiment folder.

### CHOSEN: `frame_0015_n149` (2026-09-26)

Staged at `09_experiments/02_Chosen_Frame/`, laid out to mirror `06_validation`
exactly so the existing tools work on it with `--val-dir` and nothing else:

    02_Chosen_Frame/
      frames/8bit/frame_0015_n149.png
      frames/16bit/frame_0015_n149.tiff
      labels/                            <- labelme --output target
      frame_runs.json                    <- maps it to 101947_NNA_4500sccm

Every tool must be told `--run 101947_NNA_4500sccm`. The temporal-median
background is per-run and the default is the 3000 sccm run, so omitting it
divides by the wrong illumination field and silently corrupts every
transmission value.

**This trial deliberately inverts Rule 1 of the labelling protocol.** That rule
says *never judge focus by eye — label everything, the code decides
measurability*. Here the human judgement IS the experimental variable, so it is
made deliberately, for this one frame only. The benchmark 20 stay under the
original rule; do not re-label them this way.

Effort guidance inverts too. The protocol says spend effort on filaments and
blobs rather than droplets. For this frame droplets are the entire point — take
the time on them, and on the seen/measure call in particular.

**Expect scatter near the cutoff and do not read anything into it.** The
protocol's own warning is that an eye cannot separate T=0.70 from T=0.78, which
is exactly the boundary in question. Disagreement *at* the boundary is expected
and uninformative. The informative outcome is **systematic** disagreement — the
human consistently calling objects measurable that sit at T~0.85, or
consistently rejecting ones the code accepts at T~0.65.

### Two hard requirements before labelling

1. **Verify the frame's provenance.** Done for the 20 candidates above — see
   `manifest.json`. If a frame is chosen from anywhere else, repeat all three
   route checks. A leaked frame turns the trial into a memorisation test.
2. **Do NOT append it to `06_validation/instances.json`.** Adding a frame
   renumbers every `image_id` and silently invalidates existing prediction
   files. That already happened at 15 -> 20 frames and surfaced as AP 0.0 only
   by luck. Keep the trial frame as its own benchmark file so the 20-frame set
   and `v3_predictions.json` stay comparable.

Softer, but real: **label blind.** Do not look at model predictions for that
frame until the labels are finished, or the judgement anchors to them.

### Post-labelling order of operations — do not improvise this

1. **Label** existence + class by hand (`droplet_seen` / `droplet_measure` /
   `filament` / `blob`).
2. **`strip_dust.py`** — remove sensor-dust specks. **Required, and easy to
   forget.** Dust is static, so it divides out of the transmission image but is
   plainly visible in the 8-bit view being labelled on — ~19 specks per frame
   were caught this way on the benchmark. Every training composite is built on
   real backgrounds carrying the same unlabelled specks, so the model is taught
   dust is background; ground truth saying otherwise scores it wrong for doing
   what it was taught. Affects detection scoring only — dust sits at T ~ 0.95 so
   it is already `measurable=false` and never touches D32. Run `--dry-run` first.
3. **`refine_labels.py`** — snap edges to half-maximum. Expect a higher flag rate
   than usual on the faint `droplet_seen` objects (see above).
4. **Compute** `measurable` in code as usual, so the `t_min < 0.70` verdict and
   the human `human_measurable` verdict sit side by side on every annotation.
   The whole point of the trial is comparing those two columns.

Both dust-stripping and refinement are reversible — `.predust.json`,
`.dust_removed.json` and `.original.json` are written before anything changes.

### What the trial answers

1. **Human judgement vs the `t_min < 0.70` criterion.** Substantial disagreement
   would put a question mark over every number computed so far, since that
   criterion defines the measurable subset behind the D32 and atomised-fraction
   biases.
2. **Model false positives vs `droplet_seen`.** If v3's extra detections land
   mostly on real-but-unmeasurable objects, the precision "problem" is largely a
   labelling-convention artifact and v4 should be aimed elsewhere entirely.
3. **Model detections vs `droplet_measure`.** Which score threshold best
   reproduces the droplets a human thinks should count — a more defensible basis
   for the operating point than fitting to aggregate benchmark numbers.

**Limits.** One frame is a methodology check, not a recalibration; do not
re-derive thresholds from it. And the human-labelled set is a ceiling: a
genuinely real object nobody labelled scores as a false positive no matter what
(`check_missed.py` makes this point).

### When a 4th model class becomes worth it

If the trial shows human measurability is predictable from appearance, training
the model to separate sharp from faint droplets becomes attractive — the
compositor knows each template's focus level, so those labels are free. The
model could then emit "droplet I can size" vs "droplet I can only see". That is
a dataset rebuild plus a retrain, so establish that the distinction is learnable
first. This trial is that test.

---

## WRITING THIS UP — notes for the paper

Collected 2026-09-26. Not a draft; the things that are easy to lose and
expensive to reconstruct later.

### Settle the terminology first

The code says **`filament`**; the classes are `droplet` / `filament` / `blob`.
Older models (Dennis, Claudia) and parts of this document say **`ligament`**,
and the feature-size table still has a row called "thick ligament". Pick one for
the paper and sweep the doc. Atomisation literature generally uses *ligament*
for the elongated liquid structures preceding breakup, so that is probably the
term a reviewer expects — but the code and every stored annotation say
`filament`, so a mapping sentence in the methods is needed either way.

### Methods — parameters in one place

**Imaging**
- Phantom VEO E-340L, **10 µm/px** (100 px/mm), fixed across all resolutions
  (sensor windowing, not binning — confirmed from the datasheet 2026-09-20).
- Benchmark recordings: 2048×1152 and 2560×1600, 12-bit stored as uint16.
- Reference run: 1300 fps, **10 µs exposure**, FOV 20.5 × 11.5 mm.
- Liquid velocity ~1 m/s → ~1 px motion blur at 10 µs.
- Decorrelation time ~20 ms.

**Training data (v3)**
- Real objects cut from real frames, composited onto real empty frames —
  **not** synthetic rendering. Appearance is real by construction; masks are free.
- Compositing is **multiplicative in transmission** (`I_new = I_bg × T`), never
  alpha blending, so overlaps multiply correctly.
- Library: 750 objects. Dataset: **4,000 images, 249,183 instances**
  (69.0% droplet, 27.2% filament, 3.8% blob), 62.3 instances/image.
- Fixed 800×800 training crops.

**Model and training**
- Mask R-CNN, ResNet-50 FPN 3x, COCO-initialised (not fine-tuned from v2 —
  v3 deliberately changed the filament class boundary).
- 3 classes. LR 0.0025, 20,000 iterations, IMS_PER_BATCH 2,
  ROI_HEADS.BATCH_SIZE_PER_IMAGE 128, warmup 1,000, no LR decay steps.
- Anchors `[[8,12],[20,32],[50,80],[125,200],[320,500]]`, aspect ratios
  `[0.25, 0.5, 1.0, 2.0, 4.0]`.
- INPUT min/max 800 both train and test.
- Run `training_2026_09_25_15_20_37`, 2h08m, best checkpoint iteration 19,000
  selected on composite validation.

**Inference**
- Tiled at 800 px with overlap, merged with cross-class mask-IoU NMS plus a
  containment rule; truncated detections re-tiled. **Never rescaled** — droplet
  pixel size must mean the same thing at train and test time.
- Score threshold 0.05 at inference; measurement threshold applied afterwards.

**Benchmark**
- 20 hand-labelled frames, 3,409 annotations, never trained on.
- Two conditions: 15 frames `125917_NNA_3000sccm`, 5 frames
  `101947_NNA_4500sccm` (see `frame_runs.json`).

### Metric definitions — write these out explicitly

- **Equivalent diameter** of a mask: `d = 2·√(area/π) × 10 µm/px`. The mask's
  pixel count becomes "the circle with the same area", and its diameter is `d`.
  Shape is discarded at this step; only area survives.
- **D32 (Sauter mean)**: `Σd³ / Σd²`. Since sphere volume ∝ d³ and surface area
  ∝ d², this is (total volume)/(total surface area) — the diameter of the ONE
  droplet whose volume-to-surface ratio matches the whole spray. It never
  computes a per-droplet volume; it is a single ratio of two sums.
  Smaller-the-better.
  - **Pooled, never averaged.** Because it is a ratio of sums, every droplet in
    the run goes into one Σd³/Σd². Computing D32 per frame and averaging those
    values is WRONG and gives a plausible-looking wrong answer — it weights a
    3-droplet frame the same as a 300-droplet one.
  - **Sphericity assumption — declare this.** A 2D projected area is called a
    circle, then that circle is implicitly treated as a SPHERE by the d³/d²
    weighting. This project's own observations say the small fragments are
    "crescents/commas, not spheres" (high-viscosity silicone relaxes slowly),
    so the assumption is doing real work and is weakest exactly where most of
    the droplets are. Standard practice and defensible, but state it rather
    than let a reviewer find it.
- **Atomised area fraction**: droplet area ÷ total detected liquid area, where
  each class area is the **UNION of masks within a frame**, summed across
  frames — never the sum of instances. The model emits one long filament as
  several overlapping sub-segments (measured overlap: filament 20.5%, blob
  10.6%, droplet 0%; hand labels ~0% for all), so summing double-counts.
  Larger-the-better.
- **Do not confuse area fraction with volume fraction.** The "~2% by volume"
  figure elsewhere in this document is a different quantity from the 8.33%
  area fraction and they must not be quoted interchangeably.
- Size bands are **physical (µm)**, not COCO small/medium/large — COCO "small"
  is under 32² px, which is nearly every droplet here.

### Statistical treatment

- Liquid crosses the field of view in ~20 ms, so **frames closer than that are
  not independent samples**. Extraction uses stride 10 (duplicates harmless);
  **measurement must use stride 26** at 1300 fps, or the equivalent at whatever
  frame rate was used. Measuring adjacent frames inflates apparent sample size,
  shrinks error bars and overstates confidence when ranking two runs.
- The process is **intermittent** — per-frame statistics are meaningless.
  Average over a run.
- **There is currently no uncertainty estimate on any reported number.** A
  bootstrap over frames would give confidence intervals on D32 and the atomised
  fraction cheaply, and any ranking claim is weak without them. Do this before
  writing.

### Threats to validity — the honest list

A reviewer will find these. Better to state them first.

1. **Operating thresholds were selected on the benchmark**, which is also the
   test set. Mitigation argument: the threshold applies identically to every
   experimental run, so it biases reported *accuracy*, not the *ranking*. State
   it; do not hide it. Deriving the threshold on composite validation instead
   would remove the objection entirely.
2. **The benchmark is 20 frames from two conditions of one nozzle.** It cannot
   support a claim of general accuracy.
3. **Training data is composited, not real scenes.** The sim-to-real gap is
   large and measured: segm AP 66.8 on composites vs 13.7 on real frames.
4. **Recall is size-dependent** (0.75 at 0-50 µm, 0.91 at 50-100 µm), so the
   measurement bias varies with the droplet size distribution — which is the
   thing the experiment varies. This is the most serious threat to using the
   metric for ranking, and the 3000 vs 4500 sccm split is the available test.
5. **Predicted filament area is structurally untrustworthy** — a 28×28 mask
   head cannot represent a 100:1 aspect ratio thread. The atomised fraction has
   filament area in its denominator and inherits this.
6. **Human labels are the ceiling.** A real object nobody labelled scores as a
   false positive; the measured accuracy is accuracy *relative to one
   annotator's judgement*, not to ground truth.
7. **Count-based metrics are unusable.** v3 predicts ~2× the true droplet count
   at score 0.30. Only area-weighted quantities survive this.
8. **No inter- or intra-observer agreement has been measured.** One person
   labelled everything, once. Re-labelling two or three frames blind, some weeks
   apart, would give a repeatability figure and costs almost nothing.

### Questions to have an answer ready for

- Why composite training data rather than hand-labelling real frames?
  (Labelling cost; masks free by construction; appearance real.)
- Why Mask R-CNN rather than a classical threshold method? (State what the
  classical baseline scores — **this comparison has not been run and should
  be**; the CV pipeline exists in the repo.)
- How do you know the model is not memorising? (Benchmark frames verified
  absent from the training pool and from compositing backgrounds.)
- Why is the atomised fraction biased low by ~25%? (Answer not yet established —
  the numerator/denominator decomposition is outstanding.)
- What is the measurement uncertainty? (Not yet estimated — see above.)

### Before any claim stronger than "ranks runs"

Absolute numbers are not yet defensible: D32 is +9-10% biased and the atomised
fraction −23 to −26% at the recommended operating point. To claim a
*measurement* rather than a *ranking*, at minimum: the bias-stability check
across conditions, bootstrap confidence intervals, the filament-area fix, and
ideally a comparison against an independent sizing method on the same spray.

---

## NEXT ACTIONS — superseded 2026-09-25 evening (kept for the pre-training record)

**Status:** v3 dataset built (4,000 images / 249,183 instances from a 750-object
library). Benchmark consolidated into ONE 20-frame set, all refined. Nothing
blocks training.

### Step 1 — Windows: train v3

Edits table below. Quick test at 500 iterations first. 3-4 h for the real run.

### Step 2 — Mac, in parallel: fix the scoring path BEFORE scoring v3

Three defects, all of which would corrupt the v2-vs-v3 comparison:

1. **`score_v2.py` section 2 is INVALID.** pycocotools overwrites the `ignore`
   flag one line after reading it, so the "measurable only" COCOeval numbers are
   meaningless duplicates of section 1. Set `iscrowd` instead, or delete the
   section. The greedy matching in section 3 is correct and unaffected.
2. **Class area must be the UNION of masks, not the sum of instances.** Measured
   on v2: predicted filament masks overlap by **20.5%**, blob 10.6%, droplet 0%
   (hand labels: ~0% for all, so this is a prediction-side error only). Summing
   inflates filament area and drags the atomised fraction down — union moved it
   4.25% -> 4.93% against a truth of 7.34%. Costs only instance *counting*,
   which the Taguchi metrics do not use.
3. **`tiled_inference.py` has never run on a 2560x1600 frame.** Five of the
   twenty are now that size (12 tiles instead of 6). The layout maths handles it
   in principle; smoke-test one frame before committing to a full run.

### Step 3 — score v3 once, on all 20

    python tiled_inference.py --all --preview --preview-thresh 0.3 \
      --out <LaCie>/Experiments/Real_Data/06_validation/v3_predictions.json
    python score_v2.py --pred <LaCie>/.../06_validation/v3_predictions.json

### v2 BASELINE on the same 20 frames — measured 2026-09-25, compare v3 to THIS

Not to the older 15-frame numbers. `v2_predictions.json` in `06_validation/`
has been regenerated against the 20-frame ground truth.

| | all annotations | measurable only |
|---|---|---|
| bbox AP | 15.5 | **19.8** |
| segm AP | 10.4 | **13.8** |
| bbox AP50 | 32.9 | 41.1 |
| segm AP50 | 31.7 | 41.8 |

Per class (bbox/segm AP): droplet 12.1/11.0, filament 25.8/15.0, blob 8.8/5.2.

Operating point, best F1 at score >= 0.30: **precision 0.653, recall 0.692,
F1 0.672** (TP 1256 / FP 667 / FN 559).

Measurement:

| | droplets | D32 | atomised fraction (union) |
|---|---|---|---|
| ground truth | 1571 | **73.3 um** | **8.33%** |
| v2 predicted | 1627 | **89.3 um** | **5.18%** |

**Recall by size — these two rows are what v3 exists to fix:**

| band | class | n | recall |
|---|---|---|---|
| 0-50 um | droplet | 975 | **0.61** |
| 50-100 um | droplet | 532 | 0.92 |
| 100-200 um | droplet | 61 | 0.90 |
| **50-100 um** | **filament** | **30** | **0.07** |
| **100-200 um** | **filament** | **94** | **0.42** |
| 200-500 um | filament | 61 | 0.74 |
| >500 um | filament | 17 | 0.65 |
| 200-500 um | blob | 27 | 0.52 |

**What "better" should look like, and what would be a surprise.** Short filaments
are the confident prediction: training contained essentially none under 20 px, so
7% recall is the model never having seen the thing, not failing to learn it.
Small droplets should lift too. **Precision may NOT improve and could dip** --
the focus gate was deliberately loosened, so the model now trains on fainter
objects nearer the noise floor. Blobs will stay weak (31 templates).

If v3 does NOT improve, that is informative rather than a failure: it would say
the composite-to-real gap (AP 70 vs 10.4) is dominated by something other than
class definition, density and template variety -- i.e. image realism itself --
which redirects effort from the library toward the compositor.

### Scoring-path fixes, done 2026-09-25 (all three verified working)

1. **`score_v2.py` section 2 now uses `iscrowd`, not `ignore`.** pycocotools
   discards `ignore`; `iscrowd` is the flag that reaches the matcher, and its
   semantics are right -- a detection on a crowd region is neither TP nor FP.
   The section now shows a real difference (19.8 vs 15.5 bbox AP) instead of
   duplicating section 1.
2. **Class area is now the UNION of masks.** Ground truth barely moves (8.33 vs
   8.35) because hand labels do not overlap; the prediction moves 4.79% ->
   5.18%, i.e. closer to truth. Both are printed.
3. **`tiled_inference.py` verified on 2560x1600** -- 12 base tiles plus rescue
   passes (up to 26 on the densest frame), no errors.

**New guard:** `score_v2.py` refuses to run if prediction `image_id`s are absent
from the ground truth, and warns if most frames have no detections. Adding the
5 frames renumbered every image and silently invalidated the old predictions;
it surfaced as AP 0.0, which was luck -- had the count stayed equal and only the
order changed, the score would have been quietly wrong.

### Step 4 — RE-SCORE v2 on the same 20 frames

**Do not skip this.** v2's published numbers (AP 11.7, droplet D32 92.9 um) come
from the **15-frame** benchmark. Comparing v3-on-20 against v2-on-15 conflates
model improvement with benchmark change. Re-running v2 inference is ~3 minutes
and gives a genuine like-for-like baseline.

This is not checkpoint-shopping: same model, same weights, scored on a superset.
The score-once rule forbids *picking* a checkpoint because it flatters you on the
test set; it does not forbid establishing a baseline on the benchmark you will
actually report.

---

### The edits for Windows

Three line changes to `train_detectron2.py`, everything else exactly as the v2
run had it:

| line | from | to |
|---|---|---|
| `ANNOTATIONS_PATH` | `...05_dataset_6k\annotations\instances.json` | `<LaCie>\Experiments\Real_Data\05_dataset_v3\annotations\instances.json` |
| `IMAGES_PATH` | `...05_dataset_6k\images` | `<LaCie>\Experiments\Real_Data\05_dataset_v3\images` |
| `MAX_ITER` | 20000 | **30000** |

`CHECKPOINT_INTERVAL` is already 5000. **Keep `RESUME_FROM_MODEL = None`** — start
fresh from COCO weights, because v2 learned the OLD filament class boundary and
v3 deliberately changes it; fine-tuning would fight that.

**Run `QUICK_TEST_ITERATIONS = 500` first** (15 min). It catches path typos,
confirms 3 classes register with the right names, and proves the much larger
annotation file decodes — all cheap now, expensive three hours in.

**Expect a slower run than v2.** Each image now carries ~43 instances instead of
~12. `ROI_HEADS.BATCH_SIZE_PER_IMAGE` caps ROI-head cost at 128/image so it does
not scale linearly, but RPN and mask head will. v2 ran 0.28 s/it for 1h34m;
budget 3-4 h for 30k. The annotations file is **62 MB** (was ~8 MB) so startup
before iteration 1 is slow — not a hang.

**After training:** score v3 against BOTH benchmarks —
`06_validation/instances.json` (15 frames, 3000 sccm, 2048x1152) and
`06_validation_run2/` once hand-labelled (5 frames, 4500 sccm, 2560x1600).
Use `tiled_inference.py` then `score_v2.py`. **Score each once.**

---

## What changed for v3 — 2026-09-24, after scoring v2

Every change below is a response to a measured v2 failure, not a guess.

### Data pipeline parameters

| change | from | to | why |
|---|---|---|---|
| `FILAMENT_TRUE_ASPECT` | 3.0 | **1.5** | separates hand labels at 95% filament recall / 0.9% droplet false rate; the old rule matched only 47% of hand-labelled filaments |
| `FILAMENT_MIN_LENGTH_PX` | 20 | **10** | hand-labelled filaments start at 11.1 px |
| `FILAMENT_MAX_THREAD_PX` | (none) | **20** | NEW. Without it, aspect 1.5 swept 35.7% of hand-labelled BLOBS into filament and blob candidates fell 19 -> 9 |
| `--focus-max` | 0.70 | **0.80** | 0.70 admitted only 48.8% of hand-labelled droplets; 0.80 admits 81.7% |
| composite `--min/--max-objects` | 3-60 (median 12) | **10-200 (median 43)** | real frames hold a median of 46 per equivalent 800x800 area |

### Assets rebuilt

| asset | v2 | v3 |
|---|---|---|
| library | 213 objects (144/54/15) | **593** (345 droplet / 228 filament / 20 blob) |
| library runs | 1 | **2** (273 from 3000 sccm, 320 from 4500) |
| backgrounds | 25, one run, two time windows | **27**, two runs, two frame sizes |
| dataset | 5,900 images / ~70k instances | **4,000 images / 248,151 instances** |
| — filament instances | 10,614 | **68,438** |

Of the 593 picks, **132 droplets were newly admitted** by the looser focus gate
and **84 filaments** were shorter than the old 20 px floor — i.e. exactly the two
populations v2 scored 65% and 28% recall on could not previously enter training
at all.

Density check after the change: instances/image p10 13, median 43, p90 144
against real frames at 13 / 46 / 70. Median and p10 now match; the p90 overshoots
because log-uniform sampling has a fatter tail than reality. **Left deliberately**
— over-representing crowded scenes is the safer error, since v2 trained sparse
and then met dense tiles.

### Tooling changes (all needed before v3 could be built)

- **`build_library.py` is run-aware.** Picks lines may be `<run> <candidate_id>`.
  Library filenames get a run-qualified stem (`101947__n1099_o2001`) with
  `source_run` / `source_candidate_id` preserved in `library.csv`; the qualified
  stem goes in the `candidate_id` column so `composite.py` resolves paths
  unchanged. **Necessary**: candidate IDs are frame+object index and frame
  numbering restarts per recording, so `n199_o0641` exists in both runs and means
  a different object in each. Without this the second copy silently overwrites
  the first.
- **`clean_backgrounds.py --only <stems>`.** Backgrounds are cleaned against
  their own run's temporal median and 8-bit window, so a mixed folder must be
  cleaned in separate per-run passes or frames get patched with the wrong
  illumination field.
- **`extract_candidates.py` validation exclusion is scoped by run.** See the
  safety note below.
- `02_library/` had three empty plural directories (`blobs/`, `droplets/`,
  `filaments/`) colliding with the `*.txt` picks files. Removed.

### SAFETY: the validation manifest is now scoped by run

The manifest identified held-out frames **by number only**, which was
unambiguous while one run existed. Frame numbering restarts every recording, so
run 101947's frame 619 is a completely different physical frame from run
125917's. Extraction on the new run aborted with 8 false collisions.

`load_excluded_frames(manifest_path, run_name)` now uses the manifest's own
`source_run` field, and looks for a per-run manifest by convention
(`00_manifest/validation_split_<run>.json`) before falling back. It returns an
empty set for other runs **and says so loudly** — a silent "nothing excluded" is
exactly what this safeguard exists to prevent.

Verified: 125917 excludes its 15, 101947 excludes its 5, neither leaks.

### The previous library is archived, NOT merged

`02_library_preV3/` holds the old 213 objects, picks and `library.csv`.
`01_candidates/125917_NNA_3000sccm_preV3backup/` holds the pre-re-extraction
candidates. **Do not merge the old library into v3**: its picks reference the old
extraction, and because the looser focus gate shifted object indices, the same
candidate ID now points at a different object.

---

## New recordings, 2026-09-22 — one usable, one not

Two runs at `<LaCie>/Experiments/2026/09/22/`, both 4500 sccm (the original is
3000 sccm), both **2560x1600** (the original is 2048x1152 — full sensor, not a
different magnification: object sizes match at p50 4->5 px, p90 14->20 px, so
templates are compatible). Both ~2,750 frames, extracted at stride 10 -> 276.

**`101947_NNA_4500sccm` — GOOD.** Background 830 counts, comparable to the
original's 807. Used for v3 templates, backgrounds and the second validation set.

**`103608_NNA_4500sccm` — DO NOT USE.** Background **94 counts**, about 1/9th
the light. Its auto-computed 8-bit window spans only 49 counts, so **everything
darker than T≈0.72 clips to pure black** — a faint filament and a near-opaque
ligament render identically, and for a model that eats 8-bit that information is
gone. The 16-bit data survives but at 0.011 transmission per count, 9x coarser
than the other runs.
- **Something changed between 10:19 and 10:36** (lamp, aperture or exposure).
  Check exposure at capture time in future; a run this dark is nearly useless and
  was only caught weeks later.
- Possibly salvageable by re-extracting with a forced full-range window. Not
  attempted.

**On the per-run 8-bit window generally:** `cine_extract.py` computes it from
each run's own percentiles. Comparing the two *well-exposed* runs, the difference
is only a ~4.5% contrast gain ([27,876] vs [66,901]) — small relative to the
5.4-level background noise, and not worth re-extracting for. But run 103608 shows
the percentile window failing outright when exposure drops, so pinning it is
still worth doing as cheap insurance.

---

## THE BENCHMARK IS NOW ONE 20-FRAME SET — consolidated 2026-09-25

`06_validation_run2/` was **merged into `06_validation/`**. Everything lives
there now: 20 frames, 20 label files, one `instances.json`. The run2 folder is
empty and can be deleted.

**3,409 annotations** (was 2,458): droplet 3,097 / filament 241 / blob 71.
Measurable: 1,571 / 204 / 40. Droplet D32 **73 um** measurable-only (83 um over
all annotations). Objects per frame: min 12, median 169, max 309.

Decision: **score the combined set, do not report the two runs separately** —
Ben does not need the 3000-vs-4500 difference. But every image carries
`source_run`, so the split can be recovered at any time without re-running.

**`06_validation/frame_runs.json` is new and load-bearing.** It maps each frame
stem to its source run. Frame numbering restarts per recording and each run has
its own temporal median, so **anything computing transmission must look the
frame up here** rather than assume one run.

One LabelMe command now covers all 20:

    labelme <LaCie>/Experiments/Real_Data/06_validation/frames/8bit \
      --labels droplet,filament,blob --validate-label exact \
      --output <LaCie>/Experiments/Real_Data/06_validation/labels

### Run-scoping bugs found and fixed while merging (same class as the manifest bug)

Frame numbers stopped being unique identifiers the moment a second run existed.
Three tools were silently picking the wrong run's data:

- **`find_background()` in `check_missed.py`, `strip_dust.py`,
  `prelabel_frame.py`, `refine_labels.py`, `validation_to_coco.py`** took the
  FIRST `01_candidates/*` directory with a cached median — i.e. alphabetical
  order, which since run 101947 exists meant run 125917's frames would be
  divided by the wrong illumination field. Every transmission value, focus flag
  and `measurable` decision wrong, with no error raised. All now require an
  explicit run and **refuse to guess** when more than one exists.
- **`validation_to_coco.py` loaded one background for every frame.** Now reads
  `frame_runs.json` and uses the matching median per frame.
- **Its held-out check compared frame numbers alone**, which is ambiguous across
  runs. Now matches on `(run, frame_number)` and reads every
  `00_manifest/validation_split*.json`.

`check_missed.py`, `strip_dust.py` and `refine_labels.py` also gained
`--val-dir` and `--run`.

### Dust, second set

176 specks removed across the 5 new frames (30-42 each) before refinement.
The dust map built from run 101947's median found **100 specks** versus 32 on
the original frames — same camera, but the full 2560x1600 sensor exposes more
area than the old 2048x1152 crop did.

### Superseded description of the second set (kept for the reasoning)

5 frames held out of `101947_NNA_4500sccm`, physically moved out of the training
pool and protected by `00_manifest/validation_split_101947_NNA_4500sccm.json`.
Selected spanning the run's density range (53 / 84 / 132 / 185 / 262 detected
objects, run range 15-445): **n559, n769, n859, n1649, n1719**.

**Why a second set:** the original 15 frames are all 3000 sccm at 2048x1152, so
they cannot detect condition-dependent or resolution-dependent bias — and if the
model performs differently at 4500 than 3000, the Taguchi *ranking* inherits that
as a confound. They had also been scored against twice by this point, so
information about them had already leaked into design decisions.

Not yet labelled. LabelMe command:

    labelme <LaCie>/Experiments/Real_Data/06_validation_run2/frames/8bit \
      --labels droplet,filament,blob --validate-label exact \
      --output <LaCie>/Experiments/Real_Data/06_validation_run2/labels

Same rules as the first set. Note these frames are bigger and denser — a
partially labelled second benchmark is still worth far more than none, provided
every frame that IS finished is complete.

---

## NEXT ACTIONS — superseded 2026-09-24 evening (kept below for the v2 record)

**v2 is trained.** Run: `<LaCie>/Experiments/AI/training_2026_09_24_16_25_00/`
(moved off the Windows B: drive, hash-verified). Use **`model_best.pth`**
(iteration 18,000) with **`config.yaml`** from the same folder — the config
rebuilds the exact model (3 classes, 10-anchor layout, 800 px native input);
strict-load of all 307 tensors verified. Composite-val mask AP **70.0**, box AP
**78.7** — composites only, NOT the real benchmark. Full record in "STEP 7 —
DONE" below.

**Do these next, in order:**

1. **Check whether Detectron2 is installed on the Mac.** In the env you use:
   ```
   python -c "import detectron2, torch; print(detectron2.__version__, torch.__version__)"
   ```
   If it fails, install from source (needs Xcode command-line tools + PyTorch):
   ```
   pip install 'git+https://github.com/facebookresearch/detectron2.git'
   ```
   The Windows machine runs Detectron2 **0.6**; match it if you can. On the Mac
   it runs **CPU only** — set `cfg.MODEL.DEVICE = "cpu"`. Do not try MPS:
   Detectron2 does not reliably support it (ROIAlign and friends).
2. **Smoke-test loading the model on the Mac** before writing anything:
   ```python
   from detectron2.config import get_cfg
   from detectron2.engine import DefaultPredictor
   cfg = get_cfg(); cfg.merge_from_file(".../config.yaml")
   cfg.MODEL.WEIGHTS = ".../model_best.pth"; cfg.MODEL.DEVICE = "cpu"
   p = DefaultPredictor(cfg)   # then run it on ONE 800x800 composite
   ```
   **Time that one call.** GPU is ~0.05 s/tile; CPU is guessed at 1-3 s/tile
   but unmeasured. It decides whether bulk run-processing stays on Windows.
3. **Build the tiler** (Step 8, see below). Not written yet — no tiling code
   exists anywhere in the repo (`inference_detectron2.py` has none).
4. **Score v2 against the 15-frame benchmark** (`06_validation/instances.json`)
   with the filtering rules in Step 8. **Score it ONCE.** The checkpoint was
   chosen on composites; do not now pick a different checkpoint or iteration
   because it scores better on the real frames — with only 15 frames there is
   no second test set, and doing so turns the benchmark into a tuning set.
5. Then Step 8's `run_metrics.py` rewrite (shared frame-source abstraction,
   stride 26 for measurement).

**Also outstanding (not blocking):**
- Nothing from 2026-09-24 is **committed** yet: `train_detectron2.py`,
  `AI/Real_Data_Code/composite.py`, `AI/Real_Data_Code/_fsutil.py`, this doc.
- `<LaCie>/Experiments/AI/training_2026_09_24_15_05_35` is the first, broken
  quick test (LR never warmed up — see Step 7 record). 351 MB, safe to delete.
- `<LaCie>/Experiments/AI/training_2026_09_24_15_14_35` is the working 500-iter
  quick test on the old 2000-image set. Also deletable.
- 2026-09-22 capture session outcome still not recorded here.

---

## Status record — as of 2026-09-23 (Step 6 ground rules settled; Steps 0-5 done)

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

**SUPERSEDED 2026-09-24 by `05_dataset_6k/`** — what v2 was actually trained on.
6000 images, 113,045 instances (droplet 78,409 / filament 30,298 / blob 4,338),
`composite.py --run-name 125917_NNA_3000sccm --n 6000 --seed 1 --out-name 05_dataset_6k`.
`05_dataset/` is kept, untouched, but has both defects below. Two fixes went in first:
- **Near-validation exclusion (`--exclude-near-val`, default 10).** Exact
  validation frames were already excluded, but frames are extracted every 10
  (7.7 ms) while the scene refreshes every ~26 (20 ms) — so **23 of 213 library
  objects came from the frame directly adjacent to a validation frame**, i.e.
  very likely the same physical droplet that is hand-labelled in the benchmark.
  `composite.py` now reads `00_manifest/validation_split.json` on every run,
  drops any library object within N frames of a validation frame, exits if the
  manifest is missing, and records the dropped ids in the COCO
  `info.excluded_near_validation`. Ben chose 7.7 ms, not 20 ms: 21 more objects
  sit 15 ms away and were **kept, knowingly** (dropping them too would have cost
  3 of 15 blob templates). Available library: droplet 128 / filament 49 / blob 13.
  Three backgrounds also sit within 20 ms of val frame 5019 — accepted: their
  objects were patched out, only static dirt is shared, and every frame has that.
- **The 12 smallest droplets could never be placed (bug, fixed).** The
  `--min-visible-px 12` rule, meant to reject *clipped slivers*, also rejected
  every object whose *entire* mask is under 12 px — all 12 of the 3x3 px droplet
  templates, on every attempt, silently. Now `min(12, object's own area)`.
  Result: 190/190 available objects used (was 178), 14,356 instances under 12 px
  (was 0 from those templates). This affects `05_dataset/` too.
- **Verified before training, not assumed**: 6000/6000 distinct pixel content,
  0 duplicates; 100/5900 split rebuilt exactly as `train_detectron2.py` does it
  (seed 42) shares 0 files and 0 pixel content; 0 overlap with `05_dataset/`;
  0 excluded objects used; closest source frame to any validation frame = 20.
- `composite.py` now writes through `_fsutil.write_image` (see "Windows machine").
- **Known weakness going into training: blobs rest on only 15 unique
  templates** (droplets 144, filaments 54). Rotation and flips vary
  presentation, not shape, so expect weaker blob generalisation. Traces back
  to this run genuinely not producing many isolated compact masses — will not
  improve without a second run. Watch it in the Step 7 evaluation rather than
  being surprised by it.

**Step 6 in progress.** Protocol written (`docs/VALIDATION_LABELLING_PROTOCOL.md`),
LabelMe workflow set up (AI-Box/AI-Points, SAM2 cached locally), a refinement
tool built (`AI/Real_Data_Code/refine_labels.py`) that snaps each hand/SAM
shape to the exact half-maximum edge used everywhere else in this pipeline,
run frame-by-frame as each one is finished. **1 of 15 frames labelled**
(`frame_0062_n619`: 144 shapes — 66 refined, 78 kept unrefined).

### Step 6 ground rules — settled 2026-09-22/23, do not relitigate

**1. Validation labels are hand-made. Never auto-propose into `06_validation/labels/`.**
`AI/Real_Data_Code/prelabel_frame.py` exists and works (it proposed 195 shapes
on frame 2: 166 droplet / 23 filament / 6 blob), but Ben deliberately chose to
hand-label all 15 frames instead. **Why**: it proposes shapes using
`extract_candidates.py`'s own detector, which also built the training data.
Scoring a model against those labels measures "does the model reproduce the
extractor", not "does the model find real spray" — and would hide the
small-object focus bias documented below *by construction*. Its output belongs
in `06_validation/extractor_proposals/`, where `validation_to_coco.py` cannot
see it (that directory holds the frame-2 proposal; comparing it against the
eventual hand labels is a legitimate, useful measurement of extractor bias).

**2. Out-of-focus objects are KEPT and TAGGED, never deleted.** An out-of-focus
object is **real but unmeasurable**. Deleting it tells the benchmark it does not
exist, so a model that correctly detects it scores as a false positive — i.e.
you would be selecting for a model that ignores real spray. This is the same
treatment `touches_border` already gets, for the same reason.
- `validation_to_coco.py` now writes `min_transmission`, `in_focus` and
  `measurable` on **every** annotation. Detection scoring uses all annotations;
  **size statistics (D32, atomised fraction) must filter to `measurable=true`.**
- `min_transmission` is stored as a raw number, so **the focus cutoff can be
  moved or swept later without re-labelling anything.**
- **Do not add a fourth class for blurry droplets.** Validation categories must
  match training categories exactly or the class indices mean different things
  in training and evaluation. Focus is an *attribute*, not a class.
- Ben's only judgement while labelling is "is this a real object, and what
  class". Darkness is never judged by eye — it is measured afterwards. The
  labelling floor is **recognisability**: if you cannot tell what it is, do not
  label it.

**3. `refine_labels.py --drop-flagged` must NEVER be run on a hand-labelled
frame.** It lets the extractor's focus cutoff overrule the human's judgement,
which is exactly what rule 1 exists to prevent. It was used once on frame 1
(removing 78 shapes) and has been fully reverted via `--from-original`.

**4. Never delete a `<frame>.original.json`.** Every measurement (`t_min`, area,
aspect) can be recomputed from the image at any time; **Ben's judgement about
what is an object cannot.** Those backups are the only irreplaceable artifact in
`06_validation/`. `refine_labels.py --from-original` rebuilds a working file
from one — refinement is deterministic, so nothing is lost by re-running it.

**5. Refine DROPLETS ONLY for now — `--classes droplet` is the default.**
*(This reverses an earlier same-day decision to refine all three classes. The
reversal is evidence-driven; the original reasoning and why it lost are both
below, because the argument for refining everything is still sound in principle
and should win again once the filament refiner is fixed.)*

**The argument for refining everything**: the atomised fraction is a **ratio**,
so refining the numerator (droplets) at half-max while leaving the denominator
(filaments) at the hand-drawn fuzzy edge mixes two edge definitions inside one
number. Hand-drawn shapes over-mask by a size-dependent amount — measured
refined-area-as-fraction-of-drawn: **droplet 45%, filament 61%, blob 54%** on
frame 2. So leaving filaments unrefined inflates filament area by roughly
**1.6x relative to droplets**, biasing the atomised fraction **down**.

**Why it lost anyway**: refining filaments does not merely tighten their edge,
it **truncates them**. Measured over 51 refined filaments on frame 2:

| | median kept | 10th pct | worst |
|---|---|---|---|
| width | 83% | 61% | 24% |
| **length** | **83%** | **42%** | **12%** |

**23 of 51 lost more than 20% of their LENGTH.** Width loss is legitimate halo
removal. Length loss is the refiner eating faint sections at a filament's ends
and middle — destroying *extent*, which is exactly the judgement the human is
better at and the code is worse at. Ben spotted this by eye before it was
measured.

A **known, uniform, documentable** bias (1.6x on filament area, identical every
frame, correctable afterwards) beats an **uncontrolled per-object** error
affecting ~45% of filaments by wildly varying amounts. Nothing is lost by
waiting: `.original.json` preserves every hand-drawn shape and refinement is
deterministic, so filaments can be refined retroactively with no re-labelling.

**The fix that would let rule 5 revert to "refine everything"**: a local or
adaptive threshold along the filament instead of one global half-max derived
from its single darkest pixel (which is also the root cause of the `fragmented`
flag being unreliable for filaments — same bug, two symptoms). A cheap interim:
a **length-preservation guard** that rejects any refinement changing an object's
extent by more than ~20%, keeping the ~28 of 51 that refine cleanly and falling
back to hand-drawn for the rest.

**Known finding, 2026-09-21 — the small-object focus bias is real and shows up
in hand-labelling too, not just the automated extractor.** Running the
refiner on frame 1 flagged 74 of 125 hand-drawn droplets as never reaching the
0.70 focus cutoff (an earlier figure of 82/126 predates the circle fix in
`mask_to_points` and is superseded). Checked four across the full range at high zoom against
real pixels: **all four are real droplets**, not noise. A 2-4 px object
physically cannot reach the same peak darkness as a larger one regardless of
focus quality (pixel-sampling/PSF limit) — this is the same size bias already
documented for `extract_candidates.py`'s focus gate, now confirmed to affect
hand-labelling by the same underlying physics, not a labelling error. **Do not
delete or "fix" these** — the flagged-but-untouched shapes are correctly left
as originally drawn; there is no better boundary available for something this
small.

**How much does this bias actually cost? Measured on frame 1, 2026-09-23:
2 um.** Droplet D32 over all 125 annotations is **66 um**; over the 75
`measurable=true` ones it is **68 um**. Excluding 40% of the droplets by count
moves the reported number by ~3%. The reason is structural and will hold on
every frame: **D32 is Σd³/Σd², so it is dominated by the largest objects**, and
the focus-excluded population is almost entirely small. The area-weighted
atomised fraction behaves the same way.
- **Practical consequence for labelling effort**: be quick and generous on small
  droplets, and spend the care on **filaments and blobs** — they are large, far
  fewer, and they *are* the un-atomised side of the atomised-fraction ratio, so
  each carries far more weight in the reported numbers than any droplet. This
  runs opposite to where labelling attention naturally drifts.
- At ~4 px diameter a single pixel of mask changes a droplet's area by ~8%.
  Small droplets are quantisation-limited however carefully anyone draws them.
  Do not chase precision the optics cannot deliver.

**Depth-of-field bias — know this, state it in the write-up, do not try to
remove it by relabelling.** Focus-gating samples a **size-dependent volume**: a
small droplet leaves focus over a shorter axial distance than a large one, so
small droplets are under-sampled and **D32 is biased upward**. Standard
shadowgraphy/PDIA effect, not a pipeline defect. With fixed optics it largely
cancels when *ranking* Taguchi runs against each other — the near-term goal — but
it does **not** cancel in absolute terms. Recorded in the COCO `info` block as
`known_bias`.

**Consequence for Step 7/8, recorded now so it is not a surprise later:**
`extract_candidates.py` uses this identical threshold to build the training
set, so it almost certainly excludes real small droplets the same way. v2 may
genuinely under-detect small droplets — not a model defect, a known gap in the
training pipeline's focus rule at small sizes. The validation set, correctly
including these objects, will measure that gap accurately. Consider reporting
accuracy split by size band at evaluation time, since a single aggregate
number will conflate "model is bad" with "training data never had these."
**A future fix worth considering**: a size-adjusted focus threshold in
`extract_candidates.py`, looser for small objects. Not done now — flagged for
whoever tackles Step 8 evaluation or a v3 retrain.

**Separate, algorithmic caveat**: `refine_labels.py`'s `fragmented` flag is
unreliable specifically for filaments. It fits one global threshold from one
darkest point, which can split a long, curved, genuinely-in-focus filament
into disconnected pieces purely because brightness varies along its length —
confirmed on the frame-1 figure-8 filament (independently verified correct
earlier, `t_min=0.078`, nowhere near the cutoff) which still flagged
`fragmented`. Treat this flag on a filament as "look at it," not "probably
wrong" — unlike on compact objects, where it reliably indicates defocus.
All 4 filaments flagged `fragmented` on frame 1 were confirmed by eye as
genuine filaments and restored. Refinement itself is **not** broadly broken for
filaments: it succeeded on 14 of 18, and the 4 failures were loud (flagged),
not silent. **Worth fixing properly at some point** with a local/adaptive
threshold along the filament rather than one global value from its single
darkest pixel.

**Bug found and fixed 2026-09-23 — `keep_component_at` measured neighbouring
objects.** When a drawn shape sat on something too faint to survive the focus
cutoff, the old code fell back to "keep the largest connected component in the
search region". Since the search region is dilated by `DILATE_PX`, a
**different object** only had to come within 5 px to be grabbed and written into
this shape's annotation — silently, with the neighbour's `t_min` reported as if
it were this object's. Caught on `frame_0072_n719` shape 263: 0 refined pixels
inside the drawn circle, 15 outside it.
- **Do not "simplify" this back to nearest/largest.** The first attempted fix
  (reject unless the shape's centroid sits on a dark region) was worse: a
  curved, hooked or looped filament encloses empty background, so its centroid
  lands *off* the object — that change alone broke 23 of 58 filaments. The
  correct rule, now implemented, is **the component overlapping the drawn shape
  most**, which handles curved filaments and rejects non-overlapping neighbours.
- Shapes with no overlapping in-focus region now flag
  `nothing_in_focus_at_centre` and report darkness over the **drawn shape only**,
  so the number describes what was actually drawn rather than a neighbour.

**Sensor dust was labelled as droplets — 286 shapes removed, 2026-09-24.**
There are **32 static specks** on the sensor (0.16% of frame, 10-35% darker than
the field). Because they are static they sit *in* the temporal-median
background, so they divide out of T entirely — visible in the 8-bit view Ben
labels on, invisible in the transmission data. ~19 per frame were labelled as
droplets across all 15 frames.
- **Why they had to come out, despite looking exactly like droplets**: all 2000
  training composites are built on real background frames carrying the same
  specks, **unlabelled**. `clean_backgrounds.py` never removed them and could
  not have — it detects objects in T, where dust does not exist. So the model is
  trained that dust is background. Ground truth saying otherwise scores it wrong
  for doing what it was taught: ~19 guaranteed false negatives per frame.
- They never affected D32 — at T ~ 0.95 they were already `measurable=false`.
  Detection scoring only.
- Dust is also a **transient hardware defect Ben is fixing**, so encoding it in a
  permanent benchmark would tie the measuring stick to a fault that will not
  exist in future recordings, and a model tuned to find dust would throw false
  positives on clean data.
- Tooling: `_dust.py` (shared map, built from the background — never from a
  single frame), `strip_dust.py` (removal, reversible via
  `<frame>.dust_removed.json` and `<frame>.predust.json`, and it strips
  `.original.json` too so `--from-original` cannot reintroduce them).
  `check_missed.py` now refuses to propose dust and warns if any is still
  labelled.
- **Do not "fix" dust by patching it out of the training backgrounds.** Leaving
  it present-and-unlabelled is what teaches the model to ignore it, which is the
  behaviour wanted on this recording. Patching it would mean the model had never
  seen a speck and might call one a droplet.

**Second bug, fixed 2026-09-23 — `focus-max` was silently setting droplet
SIZE, not just gating.** `refine_one` built its candidate pixel set as
`T < FOCUS_MAX` and then applied the half-maximum edge *within that set*. Since
`edge = (t_min + 1) / 2`, any object with `t_min > 0.40` has its edge above
0.70, so 0.70 became the binding constraint and the object was cut at a **fixed
contrast threshold** — precisely what the per-object half-maximum rule exists to
avoid. Measured over frames 1-2: **104 refined droplets affected**, true area a
median **1.5x larger** (worst 14x), diameters understated ~22% at the median.
Fixed by thresholding within the dilated search region and keeping the component
overlapping the candidate, so `FOCUS_MAX` only ever decides *which object*, never
*how big it is*. **Effect on the reported number: droplet D32 (measurable only)
went 74 -> 80 um.** Ben found this by asking whether 0.70 was altering sizes.

**Step 8 evaluation caveat — do not score unrefined shapes on strict mask IoU.**
Shapes that never reached the focus cutoff keep the **hand-drawn boundary**,
which is roughly **2-3x too generous in area** (the half-max core averages ~30%
of the visible blob's area on frame 1). That costs nothing in the measurements,
since those objects are `measurable=false` and excluded from D32 and atomised
fraction by definition. But their masks are loose, so a model producing a
*correct, tight* mask could fail a mask-IoU threshold against them and be scored
as a miss. **Score `measurable=false` objects on detection only** (box IoU, or a
forgiving threshold); reserve strict mask IoU for `measurable=true` objects.

**Also crude for filaments: the `in_focus` flag itself.** `min_transmission` is
the single darkest pixel in the whole shape. Fair for a compact droplet; for a
long filament whose brightness varies along its length, one dark section marks
the entire object in-focus even when most of it is soft. Do not lean on the
focus flag for filaments at analysis time. Cheap improvement when needed: also
record mean transmission per annotation (`extract_candidates.py` already
computes this for candidates).

**Verified NOT a bug, 2026-09-23 — refined circle centres.** Refined droplet
circles look visibly off-centre and too small at high zoom. Measured across all
44 circles in frame 1: the written centre sits on the refined mask's centroid to
within **0.17 px mean / 0.57 px max** — correctly centred on what it measures.
The apparent offset is a median **2.0 px** difference from the *hand-drawn*
centre, which at ~25-30x zoom on a ~4 px object renders as a large visible gap
and is well within normal hand placement variation. The apparent shrink is
intended: the circle covers the half-max core, not the defocus halo. Do not
"fix" this.

**LabelMe autosave will silently wipe a labels file.** Launched without
`--output` pointed at `06_validation/labels`, LabelMe does not load the existing
JSON, treats the frame as unannotated, and overwrites it with an empty shape list
on navigate/close. This destroyed 33 shapes on `frame_0072_n719` on 2026-09-22.
**The `--output` flag is not optional** — see the launch command in
`docs/VALIDATION_LABELLING_PROTOCOL.md`.

---

## STEP 7 — DONE, 2026-09-24. What was actually run

**Run**: `<LaCie>/Experiments/AI/training_2026_09_24_16_25_00/` — trained on
`05_dataset_6k/` (5900 train / 100 held-out composites), 20,000 iterations
(~6.8 epochs), 1 h 34 min on the RTX 5060 Ti (0.28 s/it incl. validation).
Contents: `config.yaml`, `model_best.pth` + `model_best.json`, `model_final.pth`,
checkpoints every 5k, `validation_results.csv`, `metrics.json` (per-20-iter
losses/LR), TensorBoard events, `plots/`, `validation_visualizations/`.

**Final settings in `train_detectron2.py`** (all verified by a dry run, a
quick test and a smoke test before the real run):

| setting | value | why |
|---|---|---|
| dataset | `05_dataset_6k` | see Step 5 SUPERSEDED note |
| classes | `CLASS_NAMES = ["droplet","filament","blob"]`, one constant feeding all 3 `thing_classes` + `NUM_CLASSES` | can't drift apart |
| `ANCHOR_GENERATOR.SIZES` | `[[8,12],[20,32],[50,80],[125,200],[320,500]]` | **the plan's `[[8,12],[20],[50],[125],[320]]` crashes** — see corrections |
| `ASPECT_RATIOS` | `[[0.25,0.5,1.0,2.0,4.0]]` | 10 anchors/location |
| `TEST.DETECTIONS_PER_IMAGE` | 300 | |
| `cfg.INPUT` | MIN/MAX train and test all 800 | resize is an identity on 800x800; mapper raises if anything is ever rescaled |
| batch / LR / warmup / decay | 2 / 0.0025 / 1000 / cosine | unchanged from the sweep |
| `MAX_ITER` | 20,000 | |
| `VALIDATION_SIZE` / interval | 100 composites / every 1000 | 20 gave ~14 blobs — too noisy to read |
| `CHECKPOINT_INTERVAL` | 5000 | |
| save-best | `model_best.pth` by composite segm/AP | selected on composites ONLY |
| `OUTPUT_BASE_DIR` | `B:\Experiments\AI` (local), moved to the LaCie afterwards | see "Windows machine" |
| `config.yaml` | now dumped automatically at the start of every run | inference needs it |

**Result — composite validation only (these flatter the model):**

| iter | mask AP | box AP | droplet m/b | filament m/b | blob m/b |
|---|---|---|---|---|---|
| 1000 | 59.8 | 66.0 | 63.8 / 58.4 | 52.5 / 71.0 | 63.2 / 68.7 |
| 3000 | 66.0 | 72.4 | 67.5 / — | 61.1 / 80.5 | 69.3 / — |
| 9000 | 69.3 | 77.0 | 70.3 / — | 64.8 / 83.7 | 72.6 / — |
| **18000 (best)** | **70.0** | **78.7** | | | |
| 20000 | 69.8 | 78.5 | 70.9 / 67.3 | 65.4 / 86.6 | 73.1 / 81.4 |

- **Plateaued by ~9k.** +6 AP in the first 3k, then <1 point, inside the
  validation-to-validation scatter. Best (18k) and final (20k) differ by 0.2 —
  noise. **A longer run is not worth it.** No sign of memorisation (no
  sustained fall), which is what the 6k set + cosine were for.
- **Filament box-vs-mask gap held at ~20 points the entire run** (18.5 at 1k,
  21.2 at 20k): boxes kept improving, masks stalled at ~64-65. That is the 28x28
  mask head's resolution limit, not under-training — direct evidence for
  decision 7. **Filament extent must come from ridge detection, not these masks.**
  Filament *detection* (box AP 86.6) is the strongest of the three classes.
- Droplet box AP (67) sits below droplet mask AP (71): at 3-9 px a 1 px box
  offset costs a large IoU fraction, so strict COCO IoU 0.5:0.95 punishes tiny
  boxes. Mostly arithmetic, not mislocalisation.
- Blob numbers rest on 78 held-out instances and 13 templates — noisy.

**Bugs found and fixed in `train_detectron2.py` on the way (none would have crashed):**
1. **The mapper never applied ANY augmentation.** It checked `self.tfm_gens`,
   which Detectron2 0.6 renamed to `self.augmentations` — always False, so no
   resize and no flip. Fixing the name alone would have been WORSE: the mapper
   transformed masks but not boxes, so flipped images would have had boxes on
   the unflipped positions. Now boxes and masks go through the same transforms
   (verified: 0.00 px box-vs-mask disagreement over 60 images).
2. **LR never warmed up when `WARMUP_ITERS >= MAX_ITER`.** Detectron2 warms up
   toward the cosine value at the END of warmup; with warmup 1000 and a 500-iter
   quick test that value is 0, so LR only ever fell (2.4e-6 → 5e-9) and AP was
   0.000 everywhere. Warmup is now capped at 10% of `MAX_ITER`. (Did not affect
   20k runs; did make every quick test meaningless.)
3. **Validation ran twice per interval** (stock `EvalHook` + the custom one) and
   the custom one never ran on the final iteration (0-based `iter % N`). Stock
   hook removed; custom one uses `(iter+1) % N`.
4. **Validation metrics were never recorded**: `COCOEvaluator` returns nested
   `{'segm': {'AP': ..}}`, the script looked for flat `'segm/AP'`. Now flattened
   — the CSV and AP plot work, and the CSV gained AP50/75, size bands and
   **per-class AP** for masks and boxes.
5. **Loss curve never plotted**: `DefaultTrainer.run_step()` returns None. Now
   read from the event storage.

**Known cosmetic lies in the console output — ignore them:**
- "Validation Loss" / "Generalization Gap (Overfitting/Underfitting)" — that
  "loss" is `(100 - AP)/100`, not a loss; comparing it to training loss is
  meaningless. Read the AP curve instead.
- The script's own ETA (inflated early) and "Speed: x iter/sec" (off by ~10x).
  Detectron2's `eta:` line is right.
- "Number of epochs: 1" and "Train/Val split: 90%/10%" — stale prints.
- "Skip loading parameter ..." at startup — expected: the COCO output layers
  (80 classes, 3 anchors) are re-initialised for 3 classes / 10 anchors.

**Corrections to the original plan below:**
- The LaCie is **`D:`** on the Windows machine, not `E:`. `find_lacie_drive()`
  works there.
- **`[[8, 12], [20], [50], [125], [320]]` does not build**: Detectron2's RPN
  head asserts every FPN level has the same anchor count. Fixed by two sizes per
  level. The coverage table below was computed for the non-building config, so
  the actual config's coverage was never separately measured (it is a superset:
  same P2 sizes, extra sizes elsewhere).
- "Checkpoints ... a longer run can always be resumed rather than restarted" is
  **wrong under cosine decay**: LR reaches ~0 at `MAX_ITER`, so a run that is too
  short is redone with a larger `MAX_ITER`, not resumed. Likewise a mid-run
  checkpoint (e.g. 10k of 20k) is not equivalent to a finished 10k run.
- The line saying keep `ANCHOR_SIZES = [[8, 16, 32, 64]]` is stale; the
  "CHANGE THE ANCHORS" section after it wins.

---

## STEP 7 — original plan (SUPERSEDED — kept for the anchor/aspect reasoning)

**Status going in (2026-09-24): Step 6 is COMPLETE.** 15/15 frames labelled,
dust stripped, droplets refined, `06_validation/instances.json` written with
**2458 annotations** (droplet 2237 / filament 165 / blob 56). The training set
(`05_dataset/`, 2000 composites, 33,456 instances) has been ready since
2026-09-21 and has never seen any validation frame.

### Before you touch anything

1. **Find the LaCie drive letter.** Everything below assumes `E:`; substitute
   whatever it actually is.
   ```
   python -c "import sys; sys.path.insert(0,'src'); from config_loader import find_lacie_drive; print(find_lacie_drive())"
   ```
   This is untested on Windows — if it returns None, pass paths explicitly.
2. `conda activate Detectron`
3. Confirm both COCO files load and agree on categories:
   ```
   python -c "import json; [print(p, [(c['id'],c['name']) for c in json.load(open(p))['categories']]) for p in [r'E:\Experiments\Real_Data\05_dataset\annotations\instances.json', r'E:\Experiments\Real_Data\06_validation\instances.json']]"
   ```
   Both must print `[(1,'droplet'), (2,'filament'), (3,'blob')]`. Verified
   matching on 2026-09-24 — if they ever diverge, class indices mean different
   things in training and evaluation and every number is garbage.

### Edits required to `train_detectron2.py`

It is currently configured for the OLD 2-class dataset. Four changes:

| line (approx) | from | to |
|---|---|---|
| ~117 `ANNOTATIONS_PATH` | `...Detectron_Trial_2\blur_annotations.json` | `E:\Experiments\Real_Data\05_dataset\annotations\instances.json` |
| ~118 `IMAGES_PATH` | `...Detectron_Trial_2\images` | `E:\Experiments\Real_Data\05_dataset\images` |
| 188, 221, 226 `thing_classes` | `["droplet", "ligament"]` | `["droplet", "filament", "blob"]` |
| 337 `cfg.MODEL.ROI_HEADS.NUM_CLASSES` | `2` | `3` |
| 335 `ANCHOR_GENERATOR.SIZES` | `[[8, 16, 32, 64]]` | `[[8, 12], [20], [50], [125], [320]]` — see anchors below |
| (add near 335) `ANCHOR_GENERATOR.ASPECT_RATIOS` | unset (default `[[0.5,1.0,2.0]]`) | `[[0.25, 0.5, 1.0, 2.0, 4.0]]` |
| (add) `cfg.TEST.DETECTIONS_PER_IMAGE` | unset (default `100`) | `300` |
| ~128 `MAX_ITER` | `78000` | `20000` to start — see below |

**All three `thing_classes` lines must change** — they are set separately for
the combined, train and val catalogs, and missing one gives mislabelled
visualisations that look like a model failure.

Keep the swept hyperparameters as they are for v2: `BASE_LR = 0.0025`,
`ANCHOR_SIZES = [[8, 16, 32, 64]]`, `BATCH_SIZE = 2`, cosine decay. Those came
from `LR_Anchor_Sweep_Final`.

**But know that the anchors are inherited from a DIFFERENT dataset and are not
verified for this one.** The sweep ran on `Detectron_Trial_2` (2 classes).
Measured against the new training set (2026-09-24), bbox max-dimension in px:

| class | n | p50 | p95 | max |
|---|---|---|---|---|
| droplet | 21,393 | 9 | 19 | 35 |
| filament | 10,614 | 42 | 343 | 800 |
| blob | 1,449 | 34 | 460 | 770 |

**19.9% of training objects are smaller than the smallest anchor (8 px) and
11.9% are larger than the biggest (64 px)** — about a third outside the range.
Small ones mostly survive because Detectron2's matcher gives every ground-truth
box its best anchor regardless of IoU, but regressing a 64 px anchor out to an
800 px filament is a long stretch, and filaments are the half of the
atomised-fraction ratio that matters most. Note `[[8,16,32,64]]` is a single
list, so it applies at EVERY FPN level; stock Detectron2 uses one increasing
size per level (32→512).

**Aspect ratios are mismatched too**, and `train_detectron2.py` never sets them,
so the Detectron2 default `[[0.5, 1.0, 2.0]]` applies. Measured bbox aspect
(h/w) on the training set:

| class | p5 | p50 | p95 | max | **outside 0.5-2.0** |
|---|---|---|---|---|---|
| droplet | 0.67 | 1.00 | 1.50 | 5.3 | 1.4% |
| filament | 0.30 | 1.00 | 3.40 | **24.0** | **35.7%** |
| blob | 0.47 | 1.00 | 1.94 | 9.0 | 10.1% |

So filaments are handicapped twice — on size AND on shape — and they are the
class the atomised fraction depends on most.

**CHANGE THE ANCHORS BEFORE THE REAL RUN.** An earlier draft of this handoff
said to keep them and "change one variable at a time". That was wrong: holding
a variable fixed only buys attribution when there is a BASELINE to attribute
against, and there is none — v2 is the first 3-class model on this data. Keeping
known-mismatched anchors just spends a full training run confirming a problem
already measured. A defensible starting point derived from the table above:

```python
# roughly geometric across the five FPN levels, covering the measured 5-800 px.
# Two sizes on P2 because droplets cluster there (median 9 px) -- see below.
cfg.MODEL.ANCHOR_GENERATOR.SIZES = [[8, 12], [20], [50], [125], [320]]
# 4:1 both ways covers filaments to ~p95 (3.40)
cfg.MODEL.ANCHOR_GENERATOR.ASPECT_RATIOS = [[0.25, 0.5, 1.0, 2.0, 4.0]]
```

**Do NOT add anchors smaller than 8 px — measured, it achieves nothing.** P2 has
stride 4, so an object sits up to 2 px from the nearest anchor centre. Median
droplet IoU allowing for that realistic offset:

| P2 sizes | anchors | droplet IoU |
|---|---|---|
| `[8]` | 25 | 0.406 |
| **`[8, 12]`** | 30 | **0.444** |
| `[5, 8, 12]` | 35 | 0.444 — the 5 contributes nothing |
| `[2, 4, 8]` | 35 | 0.406 — nothing |
| `[6, 9, 14]` | 35 | 0.412 — worse |

Sub-8px droplets score **0.333 under every configuration tried**, including one
with a 2 px anchor. Shrinking an anchor makes it MORE sensitive to grid
misalignment, which cancels the size benefit exactly. **The binding constraint
on tiny droplets is feature-map resolution, not anchor size** — if small-droplet
recall is the bottleneck at Step 8, the levers are upsampling the input or
adding a finer FPN level, both of which need training data at matching scale.
Adding the 12 px anchor is worth it (+9% droplet coverage for 5 anchor shapes);
anything below 8 px is pure cost.

Note the existing `[[8, 16, 32, 64]]` is a SINGLE list, so it is broadcast to
every FPN level; stock Detectron2 uses one increasing size per level, which is
what the replacement above does.

**This does NOT cost small-droplet detection — verified, not assumed.** Best
achievable IoU between every training object and its nearest anchor shape:

| class | n | OLD median | NEW median | OLD poorly covered (<0.3) | NEW poorly covered |
|---|---|---|---|---|---|
| droplet | 21,393 | 0.656 | **0.656** | 4.9% | **4.9%** |
| filament | 10,614 | 0.635 | 0.602 | 9.8% | **0.7%** |
| blob | 1,449 | 0.647 | 0.607 | 15.9% | **0.2%** |

Droplets under 8 px (n=6,593) score **0.562 under both** configurations —
identical. The 8 px anchor survives at the finest FPN level (P2, stride 4),
which is the only level where small objects are detected anyway; the old
config's 8 px anchors on P4/P5/P6 were smaller than a single feature cell and
were wasted compute, not coverage. Median IoU for filament/blob dips slightly
(one size per level instead of four at every level) but the TAIL improves
enormously, and a 0.60 match trains fine where a 0.10 match does not.

Cost: 25 anchor shapes per location instead of 12, so roughly double the RPN
anchors and somewhat slower training.

**Also unset and wrong for this data: `TEST.DETECTIONS_PER_IMAGE`** defaults to
**100**, while validation frames hold a median of **168** objects and a max of
**309**. On a whole frame the model cannot report more than 100 no matter how
good it is. Tiling largely rescues this (~50 objects per 800x800 tile) but set
it explicitly anyway:

```python
cfg.TEST.DETECTIONS_PER_IMAGE = 300
```

**What does NOT need changing**: `BASE_LR = 0.0025` is not a dataset-specific
discovery — it is the standard linear scaling of Detectron2's COCO recipe
(0.02 at batch 16) down to batch 2. Learning rate follows batch size and
optimiser, not image content, which is exactly why it carries over when anchors
do not.

**`MAX_ITER` is currently 78000**, sized for the old dataset. The new one is
2000 images at batch 2 = 1000 iters/epoch, so 78000 is ~78 epochs. Start with
`QUICK_TEST_ITERATIONS = 500` to prove the pipeline end to end (~15 min), then
set it back to `None` and run the real thing.

### Do not confuse the two "validations"

- `VALIDATION_SIZE = 20` holds out 20 **composites** from the training set. That
  is in-training monitoring only — same generator, same biases. It tells you
  whether the model is learning, nothing about whether it measures real spray.
- The **real benchmark** is `06_validation/instances.json`, the 15 hand-labelled
  frames. It is NOT used during training at all. It is Step 8.

### Run the quick test FIRST — do not skip this

Set `QUICK_TEST_ITERATIONS = 500` and run:

```
python train_detectron2.py
```

~15 minutes. It is not about model quality at 500 iterations (there is none);
it exists to prove the whole path before committing a multi-hour run. **Check
all of these before going further:**

| check | what right looks like |
|---|---|
| dataset registers | `2000` images found, no path error |
| class count | 3 classes, and visualisations say **droplet / filament / blob** — if any say "ligament", a `thing_classes` line was missed |
| annotations load | 33,456 instances, no pycocotools RLE decode errors |
| masks align | the sample visualisations show masks sitting on dark objects, not offset or empty |
| loss falls | total loss drops from ~2-3 toward ~1; flat or NaN means the LR or anchors are wrong |
| checkpoints write | a `.pth` appears in `D:\Experiments\AI\<run>\` — catches full disks and permission problems |
| GPU is used | if it is running on CPU the iteration rate will be ~50x slower; check before assuming the model is slow |

If loss goes NaN immediately, the usual cause is the anchor change above having
a typo (e.g. a bare list instead of a list of lists).

### Then the real run

Set `QUICK_TEST_ITERATIONS = None` and run again. 2000 images at batch 2 is
1000 iterations per epoch, so the current `MAX_ITER = 78000` is ~78 epochs —
inherited from the old dataset and probably longer than needed. **Start at
`MAX_ITER = 20000` (20 epochs)** and read the validation curve before spending
more; checkpoints land in `D:\Experiments\AI\` every 10000 iterations, so a
longer run can always be resumed rather than restarted.

---

## STEP 8 — DONE for v2, 2026-09-24. The numbers, and what they mean

Tooling built: **`tiled_inference.py`** (tiling + merge) and **`score_v2.py`**
(COCO scoring with the measurable/detection split). Predictions at
`06_validation/v2_predictions.json`, per-frame previews at
`06_validation/review_images/<frame>_v2pred.png`.

**Speed, measured:** model loads once in ~4 s, then **0.94 s/tile on Mac CPU**.
15 frames = ~2.5 min. A full 195-frame bulk run is ~18 min. **Bulk processing
does not need to stay on Windows** — that open question is closed.

### The headline: a large sim-to-real gap

| | composite validation | real benchmark |
|---|---|---|
| mask AP | **70.0** | **11.7** |
| box AP | **78.7** | **16.7** |

Per class (bbox/segm AP): droplet 11.4/10.8, filament 30.6/19.0, blob 7.9/5.3.

**The model learned its training distribution well and that distribution is not
reality.** This is exactly what the benchmark was built to detect, and it is why
v3 changes the DATA rather than the training schedule. Training longer optimises
composites it already scores 70 on.

### A fairer view — operating point on measurable objects

Greedy mask-IoU>=0.5 matching, measurable ground truth only:

| score | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|
| 0.05 | 998 | 856 | 263 | 0.538 | 0.791 | 0.641 |
| **0.30** | 917 | 533 | 344 | **0.632** | **0.727** | **0.677** |
| 0.70 | 808 | 366 | 453 | 0.688 | 0.641 | 0.664 |

So at its best operating point v2 finds **73% of measurable objects at 63%
precision**. Use **0.05 for AP scoring** (AP integrates over recall and needs the
low-confidence tail) and a separate, higher operating point for MEASUREMENT.

### Recall by physical size — the actionable diagnostic

| band | class | n | recall |
|---|---|---|---|
| 0-50 um | droplet | 686 | **0.65** |
| 50-100 um | droplet | 352 | 0.92 |
| 100-200 um | droplet | 43 | 0.86 |
| 50-100 um | filament | 25 | **0.28** |
| 100-200 um | filament | 71 | **0.58** |
| 200-500 um | filament | 43 | 0.84 |
| >500 um | filament | 10 | 0.70 |

**Two distinct failures.** Small droplets at 65% is the documented focus-gate
bias. **Short filaments at 28% was NOT predicted** and turned out to be a
definition conflict, not a learning failure — see below.

### The measurement numbers

| | droplets | D32 | atomised area fraction |
|---|---|---|---|
| ground truth | 1082 | **70.5 um** | **7.4%** |
| v2 predicted | 1159 | **92.9 um** | **3.6%** |

D32 **32% high** because a third of the small droplets are missed, so the
surviving population skews large. Atomised fraction roughly **half**, compounded
by blob over-prediction. **Neither is usable for the Taguchi study yet.**

### Root cause found: the class definition conflicted with the labels

The extractor required `major >= 20 AND true_aspect >= 3`. Against the hand
labels: 33% of filaments fail the length test, 53% fail the aspect test, **55%
fail one or both** — so the extractor would call only 47% of hand-labelled
filaments "filament", and training contained essentially none of the short ones.
The model was not blind to them; it was calling them droplets, exactly as taught.

Re-derived from the labels (n=2237 droplets, 165 filaments): droplet true_aspect
p50 0.84 / p95 0.91; filament p5 1.48 / p50 2.90. They separate cleanly at ~1.5.

### Merge bugs found in the tiler and fixed

Measured 88 duplicate pairs at score>=0.3 on the benchmark:

1. **Class-aware NMS** (the COCO default) never compares a droplet against a
   filament, so both survived on one object — **58 of the 88**. A physical object
   has one class. Now cross-class.
2. **Box IoU** is a bad proxy for elongated objects: a diagonal filament's box is
   mostly empty space. Now **mask IoU**.
3. **Containment**: a partial detection of a big object has LOW IoU with the whole
   (upper half of a filament vs the filament ~0.4), so NMS keeps both. Now also
   suppresses when one is >=50% contained in another AND >=20% of its size. The
   size-ratio guard protects a small droplet genuinely lying on a filament — a
   real configuration, and in the ground truth only 11 of 2458 annotations are
   >=80% contained in another, all tiny-on-large.

Result on one frame: 44 duplicate pairs -> **2**. Blob count fell 23 -> 15, so
part of the "blob over-prediction" was duplicate labels on filaments.

**What NMS cannot fix:** one filament emitted as several detections covering
different *stretches*. Those are genuinely different regions, not duplicates.
Measured overlap inflation: filament **20.5%**, blob 10.6%, droplet 0% (ground
truth: ~0% for all).
- **So total area per class must be computed as the UNION of masks, not the sum
  of instances.** That alone moved the predicted atomised fraction 4.25% ->
  4.93% against a truth of 7.34%. It costs only instance *counting*, which the
  Taguchi metrics do not need.

### Known limitation in `score_v2.py`

**Superseded 2026-09-25** — section 2 was fixed to use `iscrowd`. A *different*
limitation was found on 2026-09-25 evening and is NOT fixed: sections 4 and 5
report at each model's own best-F1 threshold, so two models' tables are not
comparable. See "READ THIS BEFORE READING ANY score_v2.py OUTPUT" above.

The original note follows. Its section 2 ("measurable only" via COCOeval) was
**invalid** — pycocotools
overwrites the `ignore` flag one line after reading it
(`gt['ignore'] = 'iscrowd' in gt and gt['iscrowd']`), so ignore markers are
discarded and it prints numbers identical to section 1. The greedy matching in
section 3 is correct and is what the measurable-only conclusions rest on.

---

## STEP 8 — the plan as originally written (kept for the tiler reasoning)

### Added 2026-09-24 — what the tiler must do (nothing is written yet)

- **Model**: `model_best.pth` + `config.yaml` from the v2 run (see NEXT ACTIONS).
  Load with `cfg.merge_from_file(config.yaml)` — never rebuild the config by
  hand, the anchor layout must match exactly.
- **Never feed a whole frame.** `config.yaml` pins `MIN_SIZE_TEST = MAX_SIZE_TEST
  = 800`, so a whole frame is shrunk to fit 800: a 2048x1152 frame by 0.39, a
  2560x1600 frame by **0.31** (a 9 px droplet arrives as ~3 px). An 800x800 tile
  passes at exactly 1.0.
- **Tile layout**: 800x800, ~100 px overlap, last row/column shifted back to sit
  flush with the frame edge (no padding, no rescale). 2048x1152 → 3x2 = 6 tiles;
  2560x1600 → 4x3 = 12 tiles. Merge across tiles with NMS on the overlaps.
  Frames smaller than 800 on a side: pad with background-matched border (decision 6).
- **Intensity**: convert 16-bit frames to 8-bit with **exactly** the window the
  composites used — `[27.0, 876.0]`, from `00_frames/<run>/extraction_metadata.json`
  (`viewing_window_8bit`), also recorded in the dataset's COCO `info`. The
  validation frames' 8-bit PNGs were extracted with this window already.
- **Long filaments will be split at tile seams** — a 1000+ px thread cannot fit
  one tile. Expected; filament extent is ridge detection's job (decision 7), and
  the Step 7 result confirms the masks cannot carry it anyway.
- **Speed**: GPU ~0.05 s/tile compute. Mac CPU unmeasured (guess 1-3 s/tile):
  15 benchmark frames are fine either way; bulk run processing (~195 frames/run
  at stride 26) may belong on Windows — decide after timing it.
- **2560x1600 recordings**: pixel size is fine (full sensor, same 10 um pixels),
  but the model's scale assumes **100 px/mm magnification** — confirm the lens /
  working distance matched `recording_130057` before trusting any size. The
  extra border is outside every training background (all 2048x1152), so expect
  more false positives in the new edge region; check a few frames by eye.

### Scoring rules (restated so nothing is missed)
- Score the benchmark **once**, with `model_best.pth`. No checkpoint shopping.
- Detection: all 2458 annotations. Size stats (D32, atomised fraction):
  `measurable == true` only (1261). `measurable == false`: box IoU / detection
  only, never strict mask IoU.
- Report by **physical size band (um)**, not COCO's small/medium/large (COCO
  "small" = under 32^2 px area, which is nearly every droplet).
- Filament masks from Mask R-CNN are not a valid measure of filament area —
  see the Step 7 box-vs-mask gap.

**Tiled inference is required, not optional, and here is the arithmetic.**
Training images are **800x800**; validation frames are **2048x1152**.
`train_detectron2.py` sets no `cfg.INPUT` values, so Detectron2 defaults apply:
`MIN_SIZE_TEST = 800`, `MAX_SIZE_TEST = 1333`. Feeding a whole frame therefore
scales it by `min(800/1152, 1333/2048) = 0.65` — a 7 px median validation
droplet arrives as **4.5 px**. That alone would make v2 look broken.

Tile into 800x800 windows with overlap: each tile needs no resizing (scale
1.0), so objects reach the model at exactly the scale it trained on. Merge
detections across tiles with NMS at the seams.

**Expect small-object recall to be the weak point regardless**, because the
size distributions genuinely differ — measured 2026-09-24:

| | median droplet | fraction < 8 px |
|---|---|---|
| training composites | 9 px | **19.9%** |
| validation frames | 7 px | **72.1%** |

That is the small-object focus bias with a number on it: the extractor's 0.70
cutoff kept faint small objects out of training, while they were deliberately
labelled in the benchmark. The gap is the measurement working, not a defect.

**Filter correctly when computing numbers** — this is what the per-annotation
flags are for:

- **Detection scoring**: use ALL 2458 annotations. Every one is a real object.
- **Size statistics (D32, atomised fraction)**: use only `measurable == true`
  (1261 of 2458). The rest are out of focus or cut by the frame edge, so their
  sizes are not trustworthy.
- **Do NOT use strict mask IoU on `measurable == false` objects.** Their masks
  are the hand-drawn outer boundary (2-3x too generous), so a model producing a
  correct tight mask would fail the IoU threshold and score as a miss. Score
  those on detection alone.
- Report accuracy **split by size band**. A single aggregate number conflates
  "model is bad" with "training data never contained these".

### What the benchmark already tells you to expect

- **Small droplets may be under-detected.** `extract_candidates.py` built the
  training set with the same 0.70 focus cutoff, so faint small objects are
  largely absent from training while present in the benchmark. A known gap, not
  a model defect.
- **Blobs will generalise weakly.** All 1449 blob instances derive from just
  **15 unique templates**; rotation and flips vary presentation, not shape.
  Validation has only 56 blobs, so that number will be noisy either way.
- **Filament masks are hand-drawn, not refined**, so their areas are ~1.6x
  inflated relative to refined droplets. This biases the atomised fraction down
  in absolute terms but preserves run-to-run ranking (see rule 5 above).
- **The focus cutoff discards LARGE objects too**, not just small ones. On the
  full 15-frame set droplet D32 is 83 um over all annotations but 70 um over
  measurable only — the excluded population skews *large*. The flat 0.70 cutoff
  is wrong at both ends; a size-dependent threshold is the fix, and because
  `min_transmission` is stored per annotation it can be applied at analysis time
  with **no re-labelling and no retraining**.

**Capture session was scheduled for Tuesday 2026-09-22 — OUTCOME NOT RECORDED
HERE.** Before relying on any new recording: confirm it uses the same
bubbler/spinner position as `recording_130057`, or it will be unusable for
over-training and validation exactly as the other three 2026-09-09 runs were.
See the note under "Only one run is usable right now". If new runs did land,
they do not affect the Step 6 work in progress — the validation set is built
from `125917_NNA_3000sccm` and stays that way.

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

## Transmission, t_min and the half-maximum edge — the units everything is in

Every threshold, gate and edge in this pipeline is expressed in **T**. If T is
not clear, none of the rest is.

**T = transmission = the fraction of light that reached the sensor**, relative
to what that same pixel reads with nothing in the way:

    T = raw_frame / background_median

- `T = 1.0` — nothing there. All light through.
- `T = 0.29` — 71% of the light blocked.
- `T = 0.05` — nearly opaque (the big ligaments).

A real slice through a small droplet in `frame_0201_n2009`, showing why this
is a physical quantity and not a display setting:

| x | raw | background | T |
|---|---|---|---|
| 959 | 831 | 811 | 1.03 (empty) |
| 961 | 572 | 811 | 0.705 (edge) |
| 965 | 238 | 814 | 0.292 (core) |
| 973 | 548 | 817 | 0.671 (edge) |
| 975 | 834 | 821 | 1.016 (empty) |

**Why divide rather than subtract.** Two reasons:
1. Absorption is multiplicative (Beer-Lambert), so division matches the physics
   and overlapping objects multiply — which is also why `composite.py` multiplies
   transmissions instead of alpha-blending.
2. It cancels the illumination field. The background varies pixel to pixel
   (811, 817, 830, 824 above) from lamp non-uniformity, the right-hand vignette
   and the top-edge smudge. Dividing compares every pixel to **its own** empty
   value, so T means the same thing everywhere in the frame.

The background is the temporal median of 40 frames: spray is transient so it
medians away, anything static survives. It is "the empty scene as this camera
sees it".

**t_min = the darkest single pixel in one object.** It does two jobs:
1. **Focus proxy.** An in-focus object has a sharp dense core, so t_min goes
   low. Defocus spreads the same absorbed light over more pixels, so no single
   pixel gets very dark and t_min stays high. That is all `--focus-max 0.70`
   asks: *did this object ever get properly dark?*
2. **Sets the edge**, below.

**The half-maximum edge = (t_min + 1) / 2.** Midway between the object's
darkest point and clear background. Everything darker than that is inside.

**Why half-maximum specifically, and not any other level.** When defocus blurs
a sharp edge, the intensity ramps instead of stepping — but the **50% crossing
stays exactly where the true edge was**, for any symmetric blur, because blur
moves light equally both ways about the edge so the midpoint cannot shift. At
20% or 80% the contour creeps outward or inward as focus changes. **Half-max is
the only threshold invariant to defocus**, which is why the whole pipeline is
built on it. It is a physical argument, not a convention — though the *choice*
to define an object's boundary this way is still yours to defend.

**And this explains the small-object bias exactly.** That invariance assumes
the object is large enough for its core to reach full opacity. A 3-4 px droplet
is comparable in size to the blur itself, so its light spreads before it can
ever get properly dark: t_min reads too high, the half-max edge derived from it
sits too tight, and the droplet measures smaller than it is — or fails the
focus gate entirely. Same physics, applied to something too small to hold it.

**Sensor dust is invisible in T, and that is not a bug.** Specks on the sensor
are static, so they are *in* the background median: dark ÷ equally dark = 1.0.
They are plainly visible in the 8-bit view a human labels on and absent from T.
Both readings are correct — they are different quantities. See the dust section
under Step 6.

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
- **CAVEAT, added 2026-09-28. The 20.5 ms is INFERRED, not measured, and the
  whole stride default rests on it.** The chain is: 10 µm/px at 10 µs exposure
  means 1 m/s produces exactly 1 px of motion blur, so "features show shape,
  not streaks" implies v of order 1 m/s; then 20.5 mm FOV ÷ 1 m/s = 20.5 ms.
  Two problems. (a) "No streaks" bounds velocity from ABOVE only — 0.3 m/s
  would also show no streaking — so it bounds decorrelation from BELOW, and
  stride 10 may be *smaller* than needed, i.e. paying for correlated frames.
  (b) It only counts transit time. Atomisation is intermittent (per-frame
  atomised fraction 0.62%–100% on Trial_1), and if the pulsing is slower than
  20 ms then intermittency, not transit, sets the real decorrelation time.
  **Both are directly measurable from any capture:** at 500 fps consecutive
  frames are 2 ms apart, so 1 m/s = 200 px of displacement — cross-correlate
  adjacent stride-1 frames for velocity, and correlate frame n against n+k for
  the decay itself, which captures transit and intermittency together. Worth
  doing: it is the parameter deciding whether a condition costs 23 min or 4 h.

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
   - **STILL OUTSTANDING as of 2026-09-27, and it caps the atomised fraction.**
     Predicted filament area is in the denominator, so the atomised fraction
     inherits the mask head's error. More frames improve its PRECISION and can
     never fix its ACCURACY. Do this before quoting an atomised fraction.
   - **Proposed shape (Ben, 2026-09-27), and it works:** run the tiled model for
     droplets, discard its filament detections, then skeletonise filaments
     separately. The two halves genuinely want different things:
     - **Droplets need TILES at native scale** — see the tiling note below;
       a whole frame gets shrunk 0.31x and a 9 px droplet arrives as 3 px.
     - **Filaments need the WHOLE FRAME** — they reach 1000+ px and would be
       cut at every tile boundary. Skeletonising per-tile would measure
       fragments, not threads.
     So: two passes over the same frame, each at the scale its objects need.
   - **Two things to get right when building it:**
     1. **Segment before skeletonising.** The machinery already exists —
        `extract_candidates.py` detects liquid at T < 0.95 then sets each
        object's edge at its own half-maximum. Reuse that, do not invent a
        second thresholding rule.
     2. **Do not double-count.** A pixel could be claimed by both a model
        droplet mask and the classical liquid mask. Subtract the droplet masks
        from the liquid mask first and treat the remainder as filament, or the
        atomised fraction's denominator counts the same liquid twice.
   - **Area from the skeleton** = integral of local width along the skeleton,
     with width from the distance transform (the same `thread_width` measure
     `extract_candidates.py` already computes). That is what replaces the
     untrustworthy 28×28 mask area.
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

## FUTURE WORK — v5+ ideas, not scoped, do not build yet

### Droplet/filament tracking across frames (PTV) — discussed 2026-09-27

Ben's question: could consecutive frames be linked so a droplet or filament
persisting across several frames is counted ONCE instead of once per frame?
That is particle TRACKING velocimetry (PTV — tracks individual objects), not
PIV (a statistical velocity FIELD from window cross-correlation) — closer to
what is wanted, but still a real project, for reasons specific to this data:

- **Motion is large relative to the objects.** At 1 m/s and 10 um/px, frame-to-
  frame displacement at 500 fps is `1 m/s * 0.002 s = 2 mm = 200 px` — against
  droplets 3-100 px. A naive nearest-neighbour match would often grab the
  wrong object in a dense frame (300+ detections).
- **Birth and death.** A filament fragmenting mid-sequence creates new
  droplets that did not exist a frame ago — not "the same object moved",
  a genuinely new track.
- **Merge and split.** A filament splitting into two droplets, or two objects
  merging, is the hardest case — track identity through it is ambiguous even
  by eye, and it is exactly the event most worth counting correctly.
- **Depth ambiguity.** Shadowgraph is a 2D projection of a 3D spray cone. Two
  unrelated droplets at different depths can overlap in projection, appear to
  merge, then split — indistinguishable from a real merge/split with one
  camera. A known limitation of single-camera shadowgraphy generally, not
  specific to this rig.

**Verdict: feasible in principle, moderate-to-large scope, not needed for the
near-term goal.** Standard atomisation-research practice is exactly what this
pipeline already does — treat each frame as one independent snapshot of an
ensemble, and rely on enough samples rather than on tracked identity, for a
valid size distribution. Tracking would enable velocity statistics and breakup
trajectories, which are a different (interesting) research question from
ranking Taguchi conditions. A tracker with real errors at merge/split events
could easily introduce MORE counting error than the decorrelation-stride
approach (see `--ci-stride` above) it would replace. Log as v5+; do not build
until the core measurement (filament-area fix, small-droplet recall) is solid.

---

## Known issues to keep in mind

### OPEN BUGS — not fixed, found 2026-09-26/27

**1. The atomised fraction double-counts cross-class mask overlap.**
`class_area_union()` in `score_v2.py` takes the union of masks **within each
class**, then sums the three class totals:

    by[image_id][category_id].append(segmentation)   # union is per (frame, class)
    tot_u = sum(u.values())                          # then simply added

So overlapping *filament* sub-segments are correctly counted once — that was
the bug this function was written to fix (filament overlap 20.5%, blob 10.6%).
But a **droplet mask overlapping a filament mask** still contributes those same
pixels to both unions, and therefore twice to the denominator. The atomised
fraction is biased DOWN whenever classes overlap.

Cross-class NMS (added during the Step 8 merge fixes) makes it rarer, but
nothing removes it, and it is the same family of problem as the filament-merge
bug found in `refine_labels.py` on 2026-09-27: a droplet touching a filament is
the case every one of these tools handles badly. Hand labels overlap ~0% across
classes, so this is prediction-side only — it biases the PREDICTED fraction
against the ground truth, i.e. in the direction of the -23 to -26% gap already
being investigated. **Quantify it before attributing that gap to the model.**

Fix: union across ALL classes for the denominator, keep per-class union for the
numerator. Cheap to implement, and it should be measured (not just fixed) so the
size of the effect is on record.

**3. `Brightest_Frame` is still created despite being dropped.** The brightest-frame
concept was retired on 2026-09-27 (the GUI now shows the **lowest-D32** frame
instead, from `summary.json`'s `d32_extreme_frames`), but the capture path still
makes the folder at `src/gui/GUI_Clean.py:4672` and `:4689`, and still populates
it via `_brightest_frame()` when Save TIFFs is on. Harmless, just dead weight and
one more folder to sync. Remove when next touching that code.

**2. `score_v2.py` is misleadingly named.** It is the scorer, and it is
model-agnostic — it has already been run against `v3_predictions.json`. The
"v2" is a fossil from Step 8 when it was written for the v2 model. There is no
`score_v3.py` and there should not be: one scorer, many models. Rename to
`score_predictions.py` when convenient, since the current name will keep
prompting "why are we using v2 for v3?"

### Tiler issues found and FIXED 2026-09-25 evening

Both were live during the v2 and v3 scoring runs; neither affected any number.

1. **Preview filenames were hardcoded `_v2pred.png`** regardless of model, so
   scoring any other model overwrote v2's previews with someone else's
   detections under v2's name. It happened during the v3 run. Now
   `--tag`, defaulting to the `--out` stem (`v3_predictions.json` -> `v3`), so
   files say which model drew them. Both sets were regenerated afterwards.
2. **`default_model_dir()` was hardcoded to `training_2026_09_24_16_25_00`**
   (v2), so an unqualified run scored the old model silently. Now resolves to
   the newest `training_*` with a `model_best.pth`. Because a 500-iteration
   quick test is also "newest", the run now prints the resolved directory **and
   its best-checkpoint iteration and composite AP** before inference — check
   that line before trusting any output.

- **Windows machine (BENS-PC, RTX 5060 Ti) — verified 2026-09-24.**
  - LaCie is `D:`. Detectron2 env: `C:\Users\BenSc\anaconda3\envs\Detectron`
    (Detectron2 0.6, CUDA OK). `conda` may not be on PATH in non-interactive
    shells — call that env's `python.exe` directly.
  - **Writing to the LaCie from Windows is very slow** (USB drive, write caching
    off under Windows' default "quick removal" policy; macOS caches, so the Mac
    never showed it). Measured: `cv2.imwrite` of one 800x800 PNG **6.8 s** on
    the LaCie vs 0.01 s on local SSD (it writes in many small chunks, each
    waiting on the device); encode-then-single-write 0.32 s. A 351 MB checkpoint
    **38 s** on the LaCie vs 0.3 s on C: (NVMe) and ~2 s on B: (internal HDD).
    Reads from the LaCie are fine (training data loading ~0.05 s/batch).
  - Consequences: `_fsutil.write_image()` (encode + one write) replaces
    `cv2.imwrite` in `composite.py`; the **other 7 Real_Data_Code scripts still
    use `cv2.imwrite`** — fine on the Mac, slow if run on Windows against the
    LaCie. Big generation jobs: write to local disk, then `robocopy /MT` to the
    LaCie. Training writes to `B:\Experiments\AI` and runs are moved to the
    LaCie afterwards (robocopy exit codes 0-7 mean success).

- `requirements.txt` is stale — lists `customtkinter` but not PySide6, torch or
  detectron2.
- Two near-duplicate copies each of `inference_detectron2.py` and
  `train_detectron2.py` (repo root vs `AI/Training_Analysis/`). **The repo-root
  `train_detectron2.py` is the live one** — v2 was trained with it (2026-09-24);
  the `AI/Training_Analysis/` copy is still the old 2-class version. Neither
  `inference_detectron2.py` tiles — Step 8 needs new code.
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
