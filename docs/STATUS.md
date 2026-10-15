# STATUS — real-data droplet pipeline and Taguchi study

**Last updated: 2026-10-15 evening (Mac: TONIGHT's steps rewritten as a hand-off: home PC runs the AI on the five pours only (Claude there; commands in Next steps); Cd analysed: 0.5 mm 0.844, 0.8 mm 0.814, 1.2 mm 0.527 = the insert passes ~35% less gas than a clean bore, not written to the Cd table; the static bead photos are crowded / full of specks, so bead_calibration 1.1.0 (sparse regions only, a boxed PNG per capture) is being written). 2026-10-15 (lab PC: falling beads: only ~10% of frames have beads, kept at stride 10 with trimmed cines; today is Cd tests + bead calibration only, no silicone; spray runs postponed, the three Cd tests DONE 11:12-11:34 (`Calibration/Orifice Cd/2026/10/15/`, not yet analysed); run sheet now 36 bead rows: ONE capture per single-size sandwich at focus (no patches or bg: the slide cannot move sideways, background from the photo itself), then the mixed through-focus series ±8 mm (optional; the only depth-of-field data), then the falling beads; pulled 057a0f3 at 07:52 and GUI_Clean restarted at 07:52 on it; python-pptx 1.0.2 confirmed; the Portenta switch filter is still recorded as not flashed). 2026-10-14 (Mac: throughput is now the default: response-surface goals in-band droplets per second x3 + atomised fraction x1, Settings size band 20-60 um; Ben's new tasks added to the open list in `docs/notes/2026-10-14_plan_for_wednesday.md`; the CCD run-33 bubbler stall false trip is resolved (Ben: "I didn't plug it in"); the silicone is one part, not curing). 2026-10-13 (Mac: CCD follow-up plan approved, `docs/notes/2026-10-13_CCD_followup_plan.md`, 12 phases; phase 1 done: app bugs 3 and 6 fixed, atomised fraction / flow relabelled "by area"; phase 2 done: "no spray" runs (atomised < 2%) have size and steadiness blanked; phase 3 done: gas regimes (pressure-limited runs left out of the surfaces by default, own section), goals used/dropped and best observed runs in Best settings; F2/H1 checks done (window drops in 8 runs; volume ranks like area); liquid stage 2.3.0 built (window drops masked, volume) and being re-run on the Mac for the CCD day, old outputs archived to _liquid2.2.0/; phase 4 done: band-count response (in-focus droplets per frame, 30-50 um, Settings); phase 5 done: GUI_Clean live gas regime + run_summary gas fields (rig check pending); phase 6 done: orifice on a log scale, fitted span when runs are left out; master_log gains a Mean Diameter column and the 33 CCD rows now hold D32, mean and atomised % (atomised % updated to liquid 2.3.0 at 15:30, backup kept); liquid 2.3.0 re-run done 33/33; phase 8 done (rate: count is a concentration, gas speeds the liquid up, cines cannot give velocity; docs/notes/2026-10-13_droplet_rate_investigation.md); phase 9 done (CCD re-analysed: in the flow-controlled region atomised fraction = gas + orifice only, predicted R2 0.89; best ~10,700 sccm on 1.2 mm; the 35% runs are pressure-limited 0.5 mm; docs/notes/2026-10-13_CCD_reanalysis.md); three RSM bugs found and fixed in the re-analysis (goal gate on the wrong model, strengthen runs outside the fitted span, free factors reported as edge optima); opt-in mass-balance rate responses added (`rate`, `rate_band`: droplets produced per second, all sizes / in the band); velocity capture plan written: `docs/VELOCITY_CAPTURE_PLAN.md` (exposure series ~20 min, then a 15-capture calibration set, ~3.5 h, on a narrow strip at ~10 kfps, 1 us; PCC check of rows-vs-width first). Earlier 2026-10-13, home PC: CCD batch finished 33/33 at 2.2.0 and analysed once; the 0.5 mm block was gas-starved at a ~9.5 barA ceiling (see Recent changes and docs/notes/2026-10-13_CCD_day_explained.md); app bugs 3 (stale run list) and 6 (no atomised liquid flow on Python 3.9) found. 2026-10-12 home PC: python-pptx 1.0.2 installed in the Detectron env; CCD day checked on the LaCie: 33/33 cines + summaries, detects as a complete 4-factor CCF, quick self-test READY; batch not started. Lab PC: 33-run CCD day captured, all cines saved, run 33 valid (the GUI's stall check false-tripped; label removed); GUI_Clean camera save hardened after a lost auto-trigger capture (untried on the rig); STATUS commit refs fixed, tracked __pycache__ removed, front limit switch tested on the rig, emoji removed from GUI_Clean console messages, switch noise filter in firmware (needs flashing), GUI_Clean SCCM ramp + bubbler starts with Start Experiment (untried on the rig); Mac: CCD plan complete, Phase 7 committed 2ebc9f0; Mac light-mode theme fix; batch bugs 1-2, goal-ramp bug, feed floor 2,000 steps/s; mean diameter now a headline response and the default size goal; GUI_Clean auto-trigger at end of test and pressure cut-off (both untried on the rig); GUI_Clean review fixes + front limit switch firmware (committed 58f1b94; firmware flashed and switch-tested on the lab rig 2026-10-12, all passed); next is the 33-run CCD day).** This is the live state of the work. Claude keeps it current
(see "How this file is maintained" at the bottom). History, evidence and full reasoning are in
`docs/archive/HANDOFF_real_data_pipeline_LEGACY.md` (frozen 2026-10-07, newest section first).

## The goal, in one paragraph

A defined, reproducible measurement of effervescent silicone atomisation from shadowgraph video
that can **rank runs in a Taguchi parameter study** (PhD, high-definition silicone printing). The
ML model exists to make that measurement more accurate; it is not the goal. Do not drift into
process diagnosis or model-building for its own sake.

## Where we are right now

- **27 replicate runs (9 conditions x 3 repeats, captured 2026-10-05) are measured (2.1.0) and
  analysed** (2026-10-07, Mac, 63 s). Output: `/Volumes/LaCie/Experiments/Taguchi/9x3 Taguchi Repeats/`
  (`taguchi_report.md`, `taguchi_analysis.xlsx`, `figures/`, `csv/`, `odd/`). Error term = pure
  error, 18 dof.
- **Atomised fraction:** gas flow dominates (89%; 5.2 / 13.6 / 16.9 % at 3000 / 6000 / 9000 sccm).
  Silicone (4000 sps best) and RPM (300 best) small but significant. Lack of fit p = 0.020
  (interactions real but 0.6% of variation). Same picture as the first L9, RPM now resolved.
- **D32:** all three factors significant now that replicates exist: RPM 47.5% (81.4 / 85.0 / 86.7 um
  at 300 / 600 / 900), gas 21% (6000 best), silicone 15% (4000 best). Total spread ~5 um on ~84
  (~6%); pure-error SD 1.5 um. Robust to enforcing the 200 um ceiling (checked 2026-10-07,
  read-only: same ranking and significance, D32 ~2 um lower).
- **Caveat found in review: RPM is fully confounded with time of day.** Conditions were run in
  order T1..T9 with replicates back-to-back, so 300 rpm = 09:04-10:46, 600 = 10:55-11:55,
  900 = 12:02-12:57. Back-to-back replicates also make pure error a repeatability estimate, so
  p-values are optimistic. The 10/01 L9 had the same order. **Checked 2026-10-07:** fluid is
  single-part EcoFlex 00-30 (no curing), lab held 25 degC, and the per-run `background_median.tiff`
  shows no drift in illumination or window dirt across the day (r = +0.07 with time). D32 moves in
  steps at the RPM changes, not as a gradual drift, and within the 300 rpm block (1 h 40) it tracks
  gas only. So RPM is now the likeliest explanation, but only a randomised test can rule out
  mechanical drift.
- **Sizer 2.2.0 (sharpness rule) built and compared** (commit `7ebaa1a`; opt-in at first, the
  default everywhere since 2026-10-08). All 27 re-measured with it; their 2.1.0 results were MOVED intact to
  `<run>/shadowgraph/analysis/_sizer2.1.0/`, so the run folders now hold 2.2.0. Analysis:
  `Taguchi/9x3 Taguchi Repeats (sizer 2.2.0)/` with `comparison_2.1.0_vs_2.2.0.md` and
  `sharpness_review/` (old-vs-new frames, zoomed tiles, size-matched random sheets per gas flow).
  - Atomised fraction identical (0 difference), as designed. D32 -31% (to 55-64 um), mean -18%,
    median -12%, D90 -24%; droplets >= 100 um almost all moved out of focus.
  - **The D32 factor picture flips:** 2.1.0 RPM 47.5% / gas 21%; 2.2.0 gas 70% / RPM 13% /
    silicone 13%. Same for mean and D90.
  - **That is the predicted warning sign.** The share moved rises with gas flow: 15.7 / 17.9 /
    20.5% of in-focus droplets, and 36 / 42 / 53% of those >= 50 um, at 3000 / 6000 / 9000 sccm.
    The rule removes more at higher gas, which manufactures much of the new gas effect on D32.
  - Ben's review of the sheets (2026-10-07): the rule "looks like it's doing a decent job".
  - **Gradient diagnosed (2026-10-07, read-only, 7,955 droplets >= 50 um, 10 frames/run):**
    - Real at matched size: 50-60 um moved 16 / 22 / 29%, 60-70 um 23 / 36 / 41%; flat >= 100 um.
    - **Not crowding:** neighbours in the search ring (5-7%) and merged components (3-4%) are rare
      and don't rise with gas; removing neighbour pixels from extinction_conc changes nothing.
    - **It is shape:** at matched size droplets are less round at higher gas (elongation >= 1.3:
      17 / 28 / 32% at 50-70 um). Long axes are mostly randomly oriented, with a weak vertical
      excess rising with gas (32 -> 37%), so motion blur is at most a minor part. Mainly
      deformed, unrelaxed fragments: a real image property, so the rule is doing what it was built
      to do.
    - **But ~2/3 of the 2.2.0 gas effect on D32 is selection:** applying the 3000 sccm keep-rates
      to every gas level, the 9000 - 3000 difference shrinks from -5.6 um to -1.8 um (2.1.0: -2.5).
      2.2.0 D32 is "D32 of the round, sharp droplets", and that subset shrinks faster than the
      population as gas rises.
- **Spray pulsing (2026-10-07, read-only, per-frame series at stride 10 = 39 Hz, all 27 runs):**
  - Strong **slow pulsing at 3000 sccm** (period ~3 s, ~0.35 Hz): 43% of droplet-count variance
    below 2 Hz vs 13-16% at 6000 / 9000 (white noise ~10%); 28% vs ~10% for atomised fraction.
    Tracks GLR (r = -0.7 with log GLR); strongest at T7 / T4 (GLR 0.14 / 0.19). RPM adds a
    little (p = 0.004); silicone flow none for droplet count.
  - Upstream pressure oscillates at ~0.2-0.6 Hz (CV 2-9%) in EVERY run while gas flow holds to
    ~1%, but only the low-GLR spray follows it (droplets vs pressure r = 0.80 at T7, 0.33 at T6).
    Origin of the pressure swing unknown (atomiser / liquid line); low-GLR sprays are sensitive to
    it. Consistent with slug-like internal flow at low GLR; not proven.
  - Written up in `Taguchi/9x3 Taguchi Repeats/pulsing/` (`pulsing_report.md`, two figures, CSVs,
    the script); a summary section was appended to both 9x3 `taguchi_report.md` files (re-running
    Analyse rewrites those and drops the section; the pulsing folder stays).
  - No sign of the bubbler rotation frequency (5 / 10 / 15 Hz) in 0.1-19.5 Hz. Liquid area is very
    bursty (CV > 1) but uncorrelated frame to frame: individual slugs pass in < 25 ms. Anything
    above 19.5 Hz needs full-rate (390 fps) analysis of the cines.
  - **Consequence:** stride-10 frames are NOT independent at low GLR (droplet-count lag-1 r = 0.62
    at 3000 sccm, 0.29 at 6000, 0.18 at 9000; still ~0.15 at 410 ms at 3000). Per-run bootstrap CIs
    (ci_stride 1) are too narrow there. The Taguchi ANOVA uses repeat scatter, so it is unaffected.
- To analyse 2.1.0 again, the `_sizer2.1.0` folders must be moved back first (the app reads only
  `droplets_0.30` / `liquid_0.30`).
- Launch the app on the Mac:
  `cd /Users/benschofield/Documents/GitHub/HPATR && /Users/benschofield/anaconda3/envs/phantom/bin/python3 -m src.ai.Taguchi_Analysis_UI`

## Lab captures from 2026-10-08 (GUI changed)

- **The GUI's AI chain now measures at sizer 2.2.0 and runs the classical liquid stage**, so each
  capture finishes with `droplets_0.30/` + `liquid_0.30/` (both 2.2.0), ready for the app's
  Analyse with "Use their existing results". The Extremes tab shows the classical renders (un-atomised
  liquid filled orange) for the D32 and atomised extremes; the headline and master-log atomised
  fraction are the classical one.
- **Standard capture settings** (390 fps, 4 us, 2048x1152, 0 / 13 s, AI stride 10, AI on) are the GUI
  defaults and are checked at Start Experiment.
- These match the 10/05 run folders as they stand (2.2.0) and `9x3 Taguchi Repeats (sizer 2.2.0)/`.
- **The Taguchi app's batch also measures at 2.2.0 by default now** (`RunSettings.sharpness_rule`,
  passed to both stages; a job saved before 2026-10-08 resumes at 2.1.0). So GUI captures and app
  batches agree.
- **2.2.0 is the default EVERYWHERE since 2026-10-08, including a bare `measure_run.py` /
  `classical_liquid.py` / `process_capture.py` / `batch_runs.py` call** (Ben: "using 2.2 for good
  now, might go back"). Every script takes `--no-sharpness-rule` for 2.1.0, bit-identical to
  before. Callers pass the flag **explicitly both ways** (`process_capture` -> both child scripts,
  `batch_runs`, the app's `classical_cmd`), so a resumed pre-10-08 app job still runs at 2.1.0;
  `test_sizer_version_is_explicit_both_ways` guards that. Verified on Trial_CINE: default -> 2.2.0,
  D32 56.19 um; `--no-sharpness-rule` -> 2.1.0, 81.58 um (matches the recorded 81.59); 57,654
  droplets both ways.
- A new day is a new block: include 1-2 repeats of 10/05 conditions to measure the day offset.

## Response-surface (CCD) support + richer outputs (plan approved 2026-10-11)

Plan: `~/.claude/plans/purring-bubbling-raccoon.md` (7 phases, each ending in a stop). Extends the
Taguchi app with a Response surface tab (detect or build a CCD, analyse, validate any run, recommend
runs), richer figures/data for both analyses, and a PowerPoint deck. First real-data trial: the
9x3 as a gas x feed surface (Phase 4b).

- **Phase 1 done (2026-10-11), committed c43df2f:** `run_metrics.py`, the shared per-run data layer (size
  distribution incl. Dv10/50/90 and span; steadiness and pulsing incl. spectrum and slow share;
  pressure inside the camera window; un-atomised pieces; sizer and data quality incl. static spots;
  atomised liquid flow; capture time), cached per run in `<output>/cache/run_metrics/`. Five new
  analysed responses in the Taguchi analysis: **Dv50, atomised liquid flow, frames below half the
  mean count, lag-1 correlation, peak pressure** (42 factor tests now, BH-corrected). Matches the
  2026-10-07 pulsing analysis to 4 dp on run 124632. Real 9x3 publishes in ~80 s (first run fills
  the cache). Tests: `tests/test_run_metrics.py` (9).
- **Practice folder (2026-10-11), for all development/testing of this plan:**
  `/Volumes/LaCie/Experiments/Taguchi/Claude Experiments/Practice Folder/`. Holds `2026/10/05/<27
  runs>` (date levels kept, the app reads the date from the path) with everything except
  `raw/CINE/` and `raw/frames/` (3.4 GB; checksums match the originals), a
  `9x3 Taguchi Repeats (reference copy)/` of the published output, and `output/` for practice
  publishes. All 27 load as analysable, 0 runnable (no .cine), so the batch cannot re-measure them.
  Point test publishes here, never at `2026/10/05` or `9x3 Taguchi Repeats`.
- **Phase 2 done (2026-10-11), committed 5649800, awaiting Ben's review:** richer Taguchi outputs + deck.
  New `figures_extra.py` (size distributions + cumulative volume, Dv10-90 per run, per-run time
  series of droplets/frame with pressure and of liquid area, spectra, steadiness by condition,
  drift, replicates with t CIs, interaction plots with the L9 aliasing caveat, residual
  diagnostics, response correlations, liquid pieces, data quality, image galleries of each run's
  lowest/highest-atomised frames), `deck.py` -> `taguchi_deck.pptx` (12-13 slides, titles are
  takeaways computed from the numbers; drift slide only if a drift survives BH), 9 new workbook
  sheets / CSVs, matching report sections; `stats.main_effects_fit / drift / drifts /
  order_confounding / t_quantile`. `python-pptx` 1.0.2 installed in the Mac `phantom` env
  (Windows env not yet; without it everything else publishes and the report says why).
  Published from the practice folder to `Practice Folder/output/9x3 phase 2/` (82 s cached).
  Tests: `test_figures_extra.py` (15), `test_deck.py` (6).
  - **Phase 1 bug fixed:** Dv10/50/90 interpolated between sorted droplets, which on the pixel
    lattice always returns a lattice value: 8 distinct Dv50s in 27 runs, identical replicates,
    gas p = 5e-15. Now grouped-data interpolation across lattice cells (26 distinct; replicates
    differ by 0.2-1 um). `run_metrics.SCHEMA` 2 invalidates old caches.
  - **Drift is a light check, by Ben's call** (climate-controlled lab): kept in the report and
    workbook (none found on the 9x3: all p > 0.7), out of the headline findings and the deck
    unless a drift survives BH. RPM-vs-run-order (r = +0.91) is one caveat line.
  - **Deck has every figure (2026-10-11, after Ben's review):** 42 slides on the 9x3. Each figure slide:
    takeaway title + description with numbers from the tables + speaker notes; tall figures
    (time series, replicates, model checks) redrawn in slide-sized parts into `figures/slides/`;
    galleries as an appendix. Descriptions fall back to a plain one when numbers are missing.
  - **Deck styled like Ben's hand-made decks (2026-10-11):** built on `assets/deck_template.pptx` (his
    9x3 `taguchi_results.pptx` with its slides removed: "Atomisation Ink" theme, navy title slide,
    grey-blue cards, orange/teal/purple/yellow accents; figure factor colours now match). Each figure
    slide: takeaway title, description card, and a "Terms" card defining every statistic it uses
    (beside the figure when that leaves it bigger). Conditions are named with their levels and the
    factor driving them. Pulsing figure is 2 x 2. Slide order unchanged (Ben: no other layout changes).
  - **For Phase 5 (Ben, 2026-10-11):** `rsm_deck.pptx` must carry the 3D response surfaces (with design
    points), contour maps and profiler, every figure with a takeaway + description like the Taguchi deck.
    First real ones in Phase 4b (9x3 gas x feed).
  - **For Phase 3b:** the builder must offer half-fraction corners (resolution V) for 5 factors
    (CCF full 47 runs -> ~31). Detection and the model are already any-k in the plan.
  - **Splash is not a BG_FRAMES problem (checked 2026-10-11, Ben confirmed it is a splash):** it
    lands mid-capture and darkens (113007: clean for the first ~25%, then 0.74 -> 0.44 of its
    surround), so no static median can match every frame; more frames would not help. Impact
    nil: T on it stays > 0.86 vs the classical seed 0.70, and model detections on it are below the
    chance rate for that area (113007: 168 vs ~370 expected). Leave BG_FRAMES = 40; wipe the
    window between runs. A rolling (time-local) background is the fix if splashes get bigger.
  - **Data-quality finding:** 113007, 124030 (and mildly 120201) have a large defocused dark spot
    in the median background (~1700 px, left of centre): most likely a silicone splash on the
    window for most of that capture.

- **Phase 2 committed (5649800).**
- **Phase 3a done (2026-10-11), committed 3846548, awaiting review:** `rsm_detect.py` detects the
  response-surface design from the run folders alone (no sheet): varying factors + held-fixed list;
  design levels (uneven allowed: DESIGN coding classifies, REAL coding fits, 1.2 mm -> +0.08); special
  values that only occur with every other factor at centre (symmetric pair beyond the levels = axial,
  alpha estimated; lone inside = off-grid CHECK, e.g. 0.8 mm; lone outside = OUTSIDE, e.g. 0 rpm);
  point types; repeats; type match (CCF / CCD-alpha with rotatable/spherical / Box-Behnken / 3^k /
  two-level + centres / regular fractions / orthogonal array / irregular) with missing and extra
  points; hard-to-change (block) factor = few value changes in time order, confounded with time;
  day blocks; within-block repeats as drift pairs; Notes ("CCD run 7 centre") vs point type and
  vs capture order; quadratic estimability (separately estimable terms, pure-error and LOF df,
  largest estimable hierarchical model with aliases). Editable `RsmDesign` (design.Design +
  validation runs + block factor), saved as `rsm_design.json`. Tests `test_rsm_detect.py` (14),
  including Ben's 33-run day (FAKE folders built from his run sheet; that day has not been run),
  a 3-factor CCF day with orifice blocks (future 3-factor sessions), and the real 10/05 (read-only:
  -> L9, Taguchi tab, RPM confounded with time). Priority: the 4-factor 33-run design, then 3-factor.
  **Ben's CCD plan is now 4 factors / 33 runs** (gas 7000-11000, feed 3000-5000, RPM 100-900,
  orifice 0.5/1.2/1.8, + 0 rpm control + 0.8 mm check; doc dated 2026-10-09), not the 3-factor
  22-run day the plan file assumed; detection is any-k so nothing changed, the tests use the 33.
  Comparing the detected design with a BUILT sheet moves to 3b (the sheet format is defined
  there; the built sheet gets its own file, not `rsm_design.json`).

- **Phase 3a committed (3846548).**
- **Phase 3b done (2026-10-11), committed 0b292ee, awaiting review:** `rsm_design.py`, the generic CCF
  run-sheet builder: 2-5 factors (built-in keys or workbook fields), real low/mid/high levels
  (uneven allowed), all corners or a half fraction (last factor = product of the others: res V for
  5 factors, 16+10+5 = 31 runs), optional block factor (outer blocks: corners opened and closed by
  the block factor's face point as start/end repeats; middle block: centres first, last and spread
  through the other faces), extras (inside a block's level -> inside that block, never first or
  last; off-grid -> after every block), a first run (pressure check: opens its block, block goes
  first), seeded randomisation within blocks, Notes "CCD run N <type>" that rsm_detect reads back,
  time estimate. Saved as `rsm_run_sheet.json` (load rebuilds from the plan and checks the rows),
  exported as run_sheet.xlsx/.csv/.md. `compare(sheet, detected)`: as planned / out of order /
  settings differ / not captured yet / not on the sheet (moved here from 3a). Ben's 33-run day
  regenerated block by block; built -> captured as fake folders -> detected closes the loop.
  Tests `test_rsm_design.py` (15) + mutation checks.
  - **Near-aliasing check added to estimability (rsm_detect):** rank alone said a 4-factor
    half-fraction CCF can fit the full quadratic (orifice's uneven middle breaks the aliasing by a
    hair); VIFs are ~850 on all six interactions vs <= 3 for the full CCF. Kept terms with VIF > 50
    are "nearly aliased"; `Estimability.usable` = full and none nearly aliased.
  - Ben's sheet exported for a look: `Practice Folder/output/CCD run sheet (4 factors, 33 runs)/`.
  - **`docs/RSM_GUIDE.md`** (Ben asked for a how-to in the GUI): step-by-step guide to planning,
    running and analysing a CCD, each builder field explained; the Phase 7 tab shows it in a Guide
    panel. Marks what is built and what is not. Keep it in step with the code.

- **Phase 3b committed (0b292ee).**
- **Phase 4 done (2026-10-11), committed c786e69, awaiting review:** the response-surface statistics.
  `rsm_stats.py` (numpy only): quadratic in real coding (axis factors full quadratic; nuisance factors
  linear or linear + square, no interactions; optional centred time term); OLS with SE / t / p,
  R^2 / adjusted / predicted (PRESS); 95% CI and PI; lack of fit vs pure error; backward elimination
  with hierarchy, highest order first (nuisance terms kept); VIFs and nuisance-vs-axis correlations;
  BH q over every full-model term test of every response; time trends; Derringer-Suich desirability
  (max / min / target ramps, hard constraints) and a grid + local search optimum, continuous or at
  settable levels, with edge flags. `rsm_responses.py`: loads a detected design's runs through the
  new shared `stats.load_measured_run` (the Taguchi analysis now uses it too, so both read runs
  identically; mixed sizer versions refuse), fits every response (full + reduced), drift (centres vs
  time, block repeat pairs as z of pure error, residual trend), predicts every run outside the fit
  with its PI (pass / fail, extrapolation flagged) and finds the optimum. Default goals: atomised
  fraction max, atomised liquid flow max, count CV min, D32 min (ramps = observed range).
  Tests: `test_rsm_stats.py` (14: independent QR/scipy fit, explicit leave-one-out PRESS, the CCD
  plan's lack-of-fit formula, PI coverage by simulation, hierarchy over 100 noise draws, planted
  optima / constraints / settable levels), `test_rsm_responses.py` (8: measured fake 3-factor CCF day
  recovers its planted surface and optimum, bad validation run fails; fake 9x3 as gas x feed with RPM
  as nuisance = 8 terms, 18 pure-error df, 1 lack-of-fit df; real 9x3 RPM vs g*f r = -0.61) +
  mutation checks. No real-data analysis yet: that is Phase 4b.
  - **Open:** the rig's rated pressure limit (for the peak-pressure constraint) is not recorded
    anywhere; ask Ben.

- **Phase 4 committed (c786e69).** Rig limits (Ben, 2026-10-11): gas flow max 12,000 sccm (now enforced by
  the builder, `rsm_design.RIG_LIMITS`); there is NO rated pressure limit, so peak pressure is reported,
  never a constraint.
- **Phase 4b done (2026-10-11), committed 7c2037b, awaiting review:** the 9x3 as a gas x feed surface, run the way
  the tab's Analyse button will (select runs -> detect -> models -> `rsm_publish.publish`), into
  `Practice Folder/output/9x3 response surface (gas x feed)/` (36 s). Built for it (the plan's Phase 5
  publish, at 2-axis scope): `rsm_figures.py` (contour maps per held RPM, 3D surfaces, profiler with
  CI/PI bands, desirability with sweet spot, fit checks, model comparison, validation),
  `rsm_report.py` (tables shared by report / workbook / CSV; verdicts; stationary points by kind;
  trade-offs at the optimum; interaction agreement across models; simple next runs),
  `rsm_publish.py` (isolated steps, shared size / steadiness / quality extras, provenance), `rsm_deck.py`
  (styled like the Taguchi deck, Terms cards, takeaway titles, shared figures as an appendix),
  `rsm_stats.stationary`. Tests `test_rsm_publish.py` (8) + a workbook-field factor test (any
  run_summary.xlsx field works as a factor, keyed `wb:<field>`).
  **Findings on the real 9x3 (sizer 2.2.0):** model (a) gas x feed + RPM nuisance fits well (atomised
  fraction R^2 0.99, predicted 0.98, no lack of fit; D32 has lack of fit p = 0.039); model (b) without RPM
  shows lack of fit for nearly every response, so RPM is not noise. The gas x feed interaction flips
  between the models (atomised -0.89 p 0.005 vs +0.46 ns; D32 +0.11 ns vs -1.19 p 0.003): not separated
  from RPM (r = -0.61), as predicted. Surfaces are mostly saddles (gas and feed curve opposite ways).
  Best overall (default goals: atomised up, atomised flow up, count CV down, D32 down) ~8,700 sccm,
  8,000 steps/s (feed edge), best at 300 rpm (D 0.91 vs 0.80 at 600, 0.72 at 900); the feed edge is
  throughput's pull: atomised fraction alone favours low feed. Phase 5 generalises to k axis factors
  (pairs, holds) and the CCD day; Phase 6 is the real recommender.

- **Phase 4b committed (7c2037b).**
- **Phase 5 done (2026-10-11), committed 9c8b8d8, awaiting review:** the response-surface outputs generalised to
  3-5 factors and the CCD day. `rsm_figures.MapLayout` / `map_layout()`: the CCD plan's layout by default
  (gas x feed across/up, one panel per block factor = orifice, one figure per next factor = RPM, any
  fifth held at the best setting), overridable; all-pairs maps; drift figure; desirability maps per
  figure level. Report / deck: every map file, controls vs centres (0 rpm), best setting at settable
  levels (orifice inserts) driving the next runs, stationary point along the curving factors when one is
  a straight line (ridge), weak surfaces (predicted R^2 < 0.5) said plainly and kept out of the
  best-settings search, numbers formatted 10,900 not 1.09e+04, natural condition order (C2 before C10).
  Shared appendix now has everything non-Taguchi-specific (every run, GLR, size spread by count and
  volume, distributions, percentiles, steadiness, spectra, time series, liquid area, replicates,
  correlations, pieces, quality, galleries); the shared figures group a CCD's runs by SETTING
  (Notes "CCD run 7" are run numbers, not Taguchi trials: before, 9 runs showed as conflicts). Every
  surface slide has "What it shows" + a "How to read it" guide (Ben). `deck._Deck.figure` takes an
  optional how-to-read text. `docs/RSM_GUIDE.md` updated.
  **Simulated day** for review: `Practice Folder/SIMULATED CCD day (fake data, not real runs)/` (README
  says so; `tests/fakes.make_measured_ccd_day` + `ccd_truth`), analysed to `Practice Folder/output/
  SIMULATED CCD day (4 factors, 33 runs)/`: finds the planted gas peak (~10,500 vs planted ~10,800 sccm),
  orifice ~1.6 mm, the 0 rpm control at -6.9 centre SDs (planted -2 points), the 0.8 mm check inside its
  PI. Tests `test_rsm_ccd.py` (8). The 9x3 trial re-published with the new outputs.

- **Phase 5 committed (9c8b8d8).**
- **Phase 6 done (2026-10-11), committed b4d4baa, awaiting review:** `rsm_recommend.py`, the next-run recommender.
  confirm (best setting x3 + centre anchor, snapped to the rig's steps / existing inserts / limits) always;
  steepest (path of steepest ascent of the desirability from the best setting, outward on edge factors,
  stops at the rig limit) and new_ccd (same-size CCF shifted so the best point is inside, built by
  rsm_design, rig limits applied; nuisance factors held where the score is highest) when the optimum is on
  an edge or nothing curves; augment (D-optimal greedy on the model's terms over a runnable candidate
  grid, the first next to a failed check / validation run) when the model is weak; new_level (next insert
  size by the same ratio) only when the CCD plan's three conditions hold. Every run predicted with its 95%
  PI, extrapolation flagged; factors taken beyond the tested range with no recorded rig limit (RPM, feed)
  are named for checking. Wired into the publish: report section, workbook sheets, one deck slide per
  recommendation, `next_runs.xlsx/.csv/.md` and `next CCD/run_sheet.*`; the Phase 4b placeholder next
  runs are gone. Tests `test_rsm_recommend.py` (10, planted surfaces) + mutation checks (rig clamp, check
  condition, D-optimal pick caught; the edge-or-flat trigger is redundant with the direction check).
  On the real 9x3: confirm 8,700 sccm / 8,000 steps/s / 300 rpm (atomised 17.0%, PI 15.4-18.6); steepest
  ascent pushes feed up to 12,000 steps/s (extrapolated); new CCD gas 4,400-10,400 x feed 6,000-10,000
  at 300 rpm; 4 runs to fix D32's lack of fit.
  **Rig limits (Ben, 2026-10-11): gas 12,000 sccm, bubbler 1,000 rpm (0 allowed: the control), feed 2,000 to about
  12,000 steps/s**, in `rsm_design.RIG_LIMITS`: the builder refuses levels beyond them and the recommender
  stops there. No rated pressure limit.

- **Phase 6 committed (b4d4baa).**
- **Phase 7 committed (2ebc9f0); the CCD plan is complete.** Ben to try it himself on the 9x3 practice copy: `tab_rsm.py`, the
  **Response surface tab** (window now "Experiment Analysis"; QSettings app name unchanged so remembered
  folders survive). Sub-tabs: Design (banner, editable run table: use, point type, block, factor levels,
  validation tick, built-sheet status, Notes check; findings; block factor; saved to rsm_design.json),
  Model (factor roles: surface / nuisance slope / nuisance slope+curve / left out; settable levels;
  goals with blank ramps = observed range; time term; comparison fit; saved to rsm_model.json; an L9
  defaults to the 9x3 gas x feed trial, a CCD to all-surface with the orifice sizes seen), Analyse and
  next runs (thread, open report / deck / next runs / folder, recommendations listed), Build a run
  sheet (table + options + extras text, Load the 33-run example, Build, Export to the output folder),
  Guide (docs/RSM_GUIDE.md, now with "Using the app" and a 9x3 practice walkthrough).
  `rsm_responses.resolve_goals` (dict goals, blank ramp = observed). Tests `test_tab_rsm.py` (9, headless,
  incl. a real Analyse on the simulated CCD day). Verified headless on the real 9x3 copy: detects the
  L9, defaults to the trial, Analyse writes everything, 4 recommendations listed.
  - **GUI_Clean**: the Start Experiment standard check no longer flags "Run AI analysis: off" (the AI runs
    afterwards in the app). "Use standard settings" no longer re-ticks the AI box either (line deleted 2026-10-11).
  - Settings tab unchanged: no pressure limit to set (there is none), desirability goals live on the
    Model page, bin settings were already there.
  - `docs/IMAGING_PIPELINE_REFERENCE.md` §9 updated (extra responses, figures, deck) and §9b added
    (response-surface stage).

## Next steps, in order

**TONIGHT 2026-10-15: analyse the calibration day. ONE LaCie, so in turn: Mac (done) -> home PC (AI on the pours) -> Mac.**
What was captured (all on the LaCie):
- `Calibration/Orifice Cd/2026/10/15/`: 3 Cd tests, 1.2 (111209), 0.8 (112250), 0.5 mm (113124). ANALYSED (below).
- `Calibration/Imaging Work/2026/10/15/`: 36 GUI runs, 1 s each (one 1.15 GB cine + run_summary, all checked):
  - 130707-133119: `BEAD 155.8 / 98.1 / 76.39 / 56.28 / 37.36 z0`, one capture per single-size sandwich at focus;
  - 134805-143553: `BEAD mix z-8.00` ... `z+8.00` (31 captures), the mixed sandwich through focus (complete).
  - These static captures need NO AI (the AI chain's temporal-median background would contain the static beads).
    `bead_calibration.py` on the Mac averages 40 frames of each into one still and measures that.
- `Calibration/Imaging Work/2026/10/15/falling/`: five PCC pours, one per size, 390 fps: `BEAD fall 155.8 p1.cine`
  (2,697 frames), `98.1` (725), `76.39  p1` (two spaces; 3,025), `56.28` (1,491), `37.36` (1,535); 9,473 frames in all.
  Plus `BEAD blank bg.cine` (empty field, 276 frames): NOT for the AI; the Mac script reads it as the dust map.

**Step 1, Mac, DONE 2026-10-15 evening:** the Cd analysis (`Calibration/Orifice Cd/analysis/2026-10-15/`, nothing
written to the app's Cd table) and the 37 averaged bead stills copied to the Mac, so the code work there needs no drive.
- Cd: **0.5 mm 0.844** (5 choked steps), **0.8 mm 0.814** (2 choked; its subsonic steps agree, 0.81-0.83),
  **1.2 mm 0.527** (subsonic only, 0.48-0.54 at EVERY step, P0 1.03-1.64 barA against 1.02-1.29 expected). Not line loss
  (the 0.8 mm insert passes the same flows through the same line with no sign of it) and not the ambient pressure (it
  would move the low steps only): the 1.2 mm insert passes ~35% less gas than a clean 1.2 mm bore, as if ~0.96 mm.
  Check it for silicone residue / measure the bore before `--write`; the 1.2 mm CCD runs' gas share depends on it.

**Step 2, HOME PC (Claude there runs these; LaCie as D:; ~1.5 h, unattended).** Command Prompt or Git Bash, in order:
```
git -C "C:\Users\BenSc\Documents\GitHub\HPATR" pull
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" "C:\Users\BenSc\Documents\GitHub\HPATR\AI\Real_Data_Code\run_ai_where.py" "D:\Calibration\Imaging Work\2026\10\15\falling" --notes "BEAD fall" --dry-run
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" "C:\Users\BenSc\Documents\GitHub\HPATR\AI\Real_Data_Code\run_ai_where.py" "D:\Calibration\Imaging Work\2026\10\15\falling" --notes "BEAD fall"
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" "C:\Users\BenSc\Documents\GitHub\HPATR\AI\Real_Data_Code\run_ai_where.py" "D:\Calibration\Imaging Work\2026\10\15\falling" --notes "BEAD fall 155.8" --stride 2
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" -c "import csv,glob,statistics as st; [print(f.split('falling')[1][1:30], 'detected', len(r), 'in focus', len(d), 'median', round(st.median(d),1) if d else '-') for f in sorted(glob.glob(r'D:\Calibration\Imaging Work\2026\10\15\falling\*\shadowgraph\analysis\droplets_*\droplet_sizes.csv')) for r in [list(csv.DictReader(open(f)))] for d in [[float(x['diameter_um']) for x in r if x['in_focus']=='1']]]"
```
- The dry run must list FIVE pours (not the blank, not the static captures). If it lists fewer, a file is missing
  `.cine` (PCC drops it on names with a decimal point): stop and tell Ben.
- Line 3: all five pours at stride 10 (Ben's choice), ~950 frames, ~30 min of GPU plus copying each cine into its
  new run folder `falling\<file name>\` (28 GB in all; the LaCie has 2.5 TB free), ~45 min in all.
- Line 4: the 155.8 pour again at stride 2 (~1,350 frames, ~40 min). A 155.8 um bead crosses the field in 2-3
  frames, so stride 10 misses most of them; this replaces that pour's stride-10 result (same folder, overwritten).
- Line 5 prints per pour: detections, in-focus detections, median in-focus diameter. Record it in Recent changes.
  Rough targets: >= 20 in focus per size (37.36: sightings, each slow bead is seen several times). A size short of
  that: re-run that pour at `--stride 1`, do not re-record.
- Restartable; writes only into the new run folders under `falling\`. Python 3.9: the 057a0f3 fixes are first
  exercised here; a `TypeError: unsupported operand type(s) for |` at import means another annotation was missed.
- Then the LaCie goes back to the Mac.

**Step 3, Mac (Claude): the bead analysis.** `bead_calibration.py` is being changed tonight (1.1.0) for what the real
photos showed: the 155.8 slide has ~35 beads among ~1,000 faint specks and fibres plus the coverslip edge; the 37.36
and mixed slides are crowded (beads touching, streaks). So 1.1.0 measures only the SPARSE parts of each photo (Ben):
dark, round, isolated beads, in tiles with little dark coverage; it writes a PNG with the area used boxed into each
capture's own folder (`<run>\shadowgraph\analysis\bead_calibration\`) and a copy in the analysis folder; it reads the
PCC blank as the dust map. Then (~5 min; reads 40 frames of each capture again, writes the PNGs and the results):
   `/Users/benschofield/anaconda3/envs/phantom/bin/python3 /Users/benschofield/Documents/GitHub/HPATR/AI/Real_Data_Code/bead_calibration.py "/Volumes/LaCie/Calibration/Imaging Work/2026/10/15" --out "/Volumes/LaCie/Calibration/Imaging Work/analysis/2026-10-15"`
   It reads the pours' AI results too (the falling-bead table). Fill in `Calibration/Imaging Work/targets.json`
   (supplier, lot, each size's certified spread) when the certificates are to hand.

**Step 4:** Claude reviews the bead + Cd results with Ben (the size bias at focus, the effective DOF per size,
whether the AI pipeline sizes falling beads as the sandwiches say, the 1.2 mm Cd), before anything changes in the sizer.

**Wednesday 2026-10-14 (code / understanding) and Thursday (rig): `docs/notes/2026-10-14_plan_for_wednesday.md`**
- **Thursday 2026-10-15: NO SILICONE (Ben, morning of the 15th). DONE:**
  1. each insert's gas-only Cd test (1.2, 0.8, 0.5 mm; line loss ignored, Ben: negligible);
  2. THEN all the bead work, `docs/BEAD_CALIBRATION.md`, with the optics untouched all day:
     - 36 sandwich captures (GUI run sheet);
     - then the falling beads, recorded in PCC (one pour per size, trimmed, named
       `BEAD fall <size> p1.cine` in `Calibration/Imaging Work/2026/10/15/falling/`). `run_ai_where.py`
       turns each loose .cine into a run folder and runs the AI.

  The run sheet (`docs/notes/2026-10-15_thursday_run_sheet.csv`, same on the LaCie) is now 36 bead rows (the 3 Cd rows done and
  removed; B01-B05 one capture per single-size sandwich at focus, then B06-B36 the mixed sandwich through focus ±8 mm, optional; Cd rows now carry Motor Travel 0, as Start refuses an empty box). **Postponed to a later spray
  day, unchanged:** the 10 spray runs below, the PCC max-fps check and the exposure series (in the sheet's git history,
  commit 057a0f3).

  The 10 spray runs (postponed):
  - 1.2 mm: anchor centre 9,000/500/4,000; confirm 11,000/100/5,000 x2; 12,000/100 at feed 5,000, 6,000 and
    8,000;
  - 0.8 mm: 12,000/100/5,000;
  - 0.5 mm: the C7 repeat 7,000/900/3,000; 900 rpm at feed 4,000 and 2,000.

  Dropped from the 16: the second anchor, the third confirmation, feed 7,000, 0.8 mm at 900 rpm, 0.5 mm at
  500 rpm, and the second C7 repeat.
  Spray-run details: 1.2 mm: 2 centre anchors, 3 confirmations of 11,000/100/5,000, a 12,000 sccm feed ladder
  5,000-8,000 (longer travel for the fast feeds). 0.8 mm: 12,000/100 and /900 at feed 5,000. 0.5 mm: C7 recipe x2,
  feed 2,000 and 4,000 at 900 rpm, 500 rpm at 3,000. Notes `S2 #NN <purpose>` (never "run N"). The bubbler's maximum is 900 rpm.
- **Wednesday done:** throughput defaults; pressure/flow log gaps explained and fixed; classical 2x2 grids; GUI_Clean
  Run sheet tab + Thursday's sheet (`docs/notes/2026-10-15_thursday_run_sheet.csv`; load it on the Run sheet tab).
- **Open:** the stride pop-up (need its wording), a full-stride cine;
  pool every new run into the CCD day (needs the next-session fix, item 19); the lab PC cannot run the AI, so no
  live numbers (overnight at home); IMPORTANT after the small fixes: the calibration scripts (plan mode first).
- ~~Commit and push, then pull on the lab PC before any capture~~ DONE (lab PC pulled 057a0f3 on 2026-10-15).

0. **CCD follow-up plan** (approved 2026-10-13; `docs/notes/2026-10-13_CCD_followup_plan.md`), phase-gated:
   1 bugs 3 + 6 and the "by area" relabel (DONE 2026-10-13); 2 "no spray" runs (atomised < 2%: size and
   steadiness blanked; DONE 2026-10-13); 3 gas regimes (pressure-limited runs out of the fit, own section; best observed runs;
   goals used / dropped shown in Best settings; DONE 2026-10-13); 4 band-count response (in-focus droplets per frame,
   30-50 um; DONE; default band 20-60 um from 2026-10-14); 5 GUI_Clean regime indicator + logging (DONE, rig check pending); 6 orifice on a log scale
   (DONE); 7 area vs volume atomised fraction + window-droplet check H1 (DONE; liquid stage 2.3.0 built and
   re-run 33/33); 8 rate investigation (DONE: report, Ben to decide on a mass-balance rate response and a
   10-min exposure series); 9 re-analyse the CCD day (DONE: `Taguchi/CCD/CCD 4-factor 12-10-2026 reanalysis
   13-10-2026/`); 10 more extreme frames (DONE: back-filled for the 33 CCD runs, floor half the median); 11 window /
   lens droplets (DONE: GUI pre-run window check, rig test pending); 12 GLR + measured pressure (opinion given:
   keep set points, add gas exit mass flux as a covariate; `docs/notes/2026-10-13_phase12_physical_variables.md`).
   Then ONE commit, after Ben has reviewed the differences.
   Done: **The 33-run 4-factor CCD day** (gas 7000/9000/11000, RPM 100/500/900, feed 3000/4000/5000,
   orifice 0.5/1.2/1.8; orifice blocks, 5 centres, block repeats, 0 rpm control, 0.8 mm check).
   Before it: try the remaining GUI_Clean fixes on the rig (front limit switch firmware DONE 2026-10-12;
   still untried: cut-off, auto-trigger, static run, Alicat alarm). Ben practises the Response surface tab on the 9x3 copy (`docs/RSM_GUIDE.md`, "Using
   the app"); pull `Testing` + install python-pptx on the lab PC (item 5); (app bugs 1-2 now fixed); build + export the run sheet in the app, type each run's
   "CCD run N <point type>" in Notes. After it: batch on Windows, then the Response surface tab.
1. **RPM confirmation test** (Ben, lower urgency now): one gas/silicone setting, RPM alternated
   300/900/300/900... in one session (4-6 runs). Randomise run order in every future campaign.
2. ~~Ben to decide the default~~ **DECIDED 2026-10-08: 2.2.0, for good** (may revisit). What
   still follows from the diagnosis: every 2.2.0 D32 gas effect is ~2/3 selection, so it must be
   reported as "D32 of the round, sharp droplets" with that caveat. Still worth considering: the
   moved share ("non-round or blurred fraction") as its own response, since it rises cleanly with
   gas. The first L9 (10/01) is still 2.0.0; re-measuring it at 2.2.0 is ~41 s/run with `--reuse`
   if it is ever to be compared (not done).
3. ~~Fix the app bugs below before the next overnight batch (1 and 2 at least)~~ 1 and 2 fixed
   2026-10-11; 3-5 remain (minor).
4. **Fold in the Windows timings**: `9x3 Taguchi Repeats/_job/eta_calibration.json` +
   `_job/timings.csv` -> replace `eta.PRIORS_BY_OS["Windows"]` in `eta.py` with measured
   lo/typ/hi per stage. ~10 min, any time.
5. ~~Install `python-pptx` on the lab PC~~ **DONE** (lab PC 1.0.2 in system Python 3.11, checked 2026-10-15; home PC DONE 2026-10-12: 1.0.2 + lxml 6.1.3 + XlsxWriter 3.2.9
   into the Detectron env, numpy untouched at 2.0.2). (The Taguchi app's PowerPoint deck needs it;
   without it the publish still writes everything else and the report says why). Command Prompt:
   home PC `"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" -m pip install "python-pptx==1.0.2"`;
   lab PC `"C:\Users\55154111\AppData\Local\Programs\Python\Python311\python.exe" -m pip install "python-pptx==1.0.2"`.
   It also pulls in `lxml` and `XlsxWriter` (new installs, nothing upgraded on the Mac).
6. **Hardware:** powered USB 3 hub for the LaCie on the home PC (also the diagnostic: still drops
   on the hub -> cable or drive).

## Open questions that block or bias results

- **How the pipeline works, exactly:** `docs/IMAGING_PIPELINE_REFERENCE.md` (2026-10-07): camera to
  report, maths, every constant, limitations, and the 16-step list to publication grade.
- **Syringe steps/mm = 6800, confirmed in firmware** (`Pressure_Motor_Portenta.cpp:30`), matching
  the GUI, so recorded liquid flows and GLRs stand. Older docs saying 13,600 were an arithmetic slip
  (fixed 2026-10-07). **Firmware bug found:** the travel check allows 986,000 steps (= 145 mm, not
  72.5 mm); FIXED in 58f1b94 (MAX_TRAVEL_STEPS = 493000) and flashed 2026-10-12; the front switch is now the hard stop.
- **Measurement method (longer term):** `docs/DROPLET_MEASUREMENT_METHOD.md` (2026-10-07) is the
  plan to make sizes defensible: dot-reticle + glass-bead calibration of edge, focus and depth of
  field, size-dependent DOF weighting, shape classification instead of rejection, volume-based
  sizing, Dv50 beside D32. Not started; includes what to buy and how to run the calibration.

- **RPM vs time of day** (see "Where we are"). The silicone is ONE part of the EcoFlex, not mixed, so it does
  not cure and its viscosity does not rise in the pot (Ben, 2026-10-14). Lab temperature is not recorded.

- **Which edge is "true" diameter.** Half-max (what the sizer implements) reads ~30-35% smaller
  in diameter than Ben's free-hand eye (51 droplets, 2026-10-02). The sizer is a correct
  implementation of a convention whose correctness is unsettled. Only a **calibration target**
  (reticle / graticule / glass beads) on this rig settles it. Relative ranking across Taguchi runs
  is unaffected; absolute diameters are.
- **The reclassification rule is now in force as 2.2.0** despite the earlier verdict that it was
  unfit for Taguchi frames (1 false reject / 20 false keeps on L9 frames; opposite error on the
  benchmark). The 2026-10-07 diagnosis explained its gas gradient as real shape change (less round
  fragments at high gas), not crowding, but ~2/3 of the resulting D32 gas effect is selection. The
  9000 sccm hand-labelling that would measure its error rate there has still not been done.
- **Decorrelation time: transit is under one frame (2.56 ms), measured 2026-10-13** (was assumed ~20 ms).
  Consecutive 390 fps frames share no droplets; liquid residence time in the field is 1.4–2.8 ms.
  What still couples frames is pulsing; the stride-10 CI is conservative for transit, and a block
  bootstrap on the measured count autocorrelation is still the proper fix.
- **Old L9 (10/01) is sizer 2.0.0** and not directly comparable to the 27 runs on atomised
  fraction. Re-measuring it is ~41 s/run if ever needed.

## Known bugs, not fixed

GUI_Clean (review 2026-10-12, Mac). FIXED the same day (committed 58f1b94; firmware + front switch tested on the rig 2026-10-12, the rest offscreen only):
Alicat reader death / silence, jog limits + front switch, Clean removed, close check, cut-off clearing,
Space bar, speed 0, stopped runs marked, conditions recorded at Start, atomic writes, settings saved
half-loaded, unused code, How To button + text (details under Recent changes). Still open (Ben's call):
- Traverse driver unpowered (rig safety switch off, 2026-10-12): the motor is limp, homing counts steps to
  its 1.1M-step limit and the GUI takes ~110 s to connect, then shows HOMING_FAILED "back switch never
  triggered". Check the safety switch / supply first. Proposed, not made: a driver check before homing
  (fail in ~3 s) and Home re-sending the driver settings (Ben has not decided).
- STOP / cut-off within 0.5 s of Start does not cancel the delayed traverse command (Ben: leave).
- AI auto-save writes into whichever run is current when the AI finishes (Ben: runs never overlap).
- `_run_folder` never cleared: a manual trigger between runs writes into, and deletes the TIFFs of,
  the previous run; Disarm during a camera save clears camera RAM (Ben: leave both).
- Camera IP box is ignored (PhantomController.connect discovers); three volume calcs disagree (r=10 mm,
  25.8 mL/72.5 mm, bore 20.27 mm: up to 13%); the Homed dot stays red after the board's own start-up
  homing (the "Homing Complete" line is consumed during connect).
- Deleting GUI_Clean's main window crashes Qt (segfault / bus error), offscreen on the Mac, the committed version
  too (found 2026-10-14 writing the run-sheet tests: build + delete the window, or build twice). Not seen on the
  rig, where it is built once and deleted at exit; it may explain any crash on closing. Cause not looked at.
- FREEZES (to do separately): cone webcam on the GUI thread at 10 Hz; `find_lacie_drive()` per keystroke;
  the 83 MB master_log.xlsx rewrite holds the GIL ~10 s at every run end; Phantom live-feed conversion on
  the GUI thread; ~30 setStyleSheet/s; console never trimmed. (FIXED 2026-10-14: the 5-s LaCie poll now
  probes on a worker thread; `log_serial` queues to one writer thread.)
- The pressure cut-off is checked on the GUI thread, so a GUI stall delays it (1-4 s stalls on the CCD day,
  now mostly removed; see Recent changes 2026-10-14). Not changed: moving it to the reader thread means
  sending STOP from a second thread.

Taguchi_Analysis_UI (found in the 2026-10-06 batch):
1. ~~One failed log write kills the worker~~ **FIXED 2026-10-11** (Mac, committed 6f63e76): writes to the
   run log, events and state never fail a run or the worker (kept and retried); a run that fails with
   an OS error or with its folder / the job folder unreachable waits up to 30 min for the drive and is
   redone once (reusing finished work); if the drive does not return the worker stops as
   **drive_lost** (exit 6), that run pending, Resume offered. `tests/test_worker_drive.py` (7,
   mutation-checked). Not yet run on Windows with a real unplug.
2. ~~A crash is reported as a contract violation with no Resume~~ **FIXED 2026-10-11**: a crash is now
   status **crashed** (exit 7), resumable, with its own message; old jobs written "halted" with no
   contract-violation run also read as crashed. Only a real contract violation reads "halted".
3. The SELECTED RUNS summary ("N already measured") does not update while a batch runs. **Worse, found
   2026-10-13 (home PC, CCD day):** the run list's RunInfo (incl. `analysis.measured`) is read once when runs
   are added and NEVER re-read when the batch finishes (`pane_runs` only reloads on a settings change; "+" on
   the same folder skips runs "already in the list"). So Analyse in the same session as the batch skips every
   run as "not measured yet" and refuses. **FIXED 2026-10-13 (Mac):** the Batch tab re-reads the run list
   whenever a batch stops running (`pane_runs.refresh_runs`, console "batch ended: re-reading N run(s)");
   test `test_the_run_list_is_re_read_when_the_batch_ends`. The SELECTED RUNS summary during a batch is
   still not live (minor).
4. After a crash the "already have results" dropdown showed "Re-measure only"; check the default
   (run sheet says "Use their existing results").
5. 17 Windows-only test failures, all test-side (path separators, `os.getpgid`, symlinks needing
   admin, `?` in a fake run name, one GLR test). Self-test says READY regardless.
6. **No atomised liquid flow on the home PC (found 2026-10-13, CCD day):** `covariates._gui_formula` imports
   `GUI_Clean`, which imports `Trials/Cone_4.py`; Cone_4 uses `int | None` annotations, a TypeError on
   Python 3.9 (the Detectron env), and GUI_Clean's guard catches only ImportError. So the GUI formula is
   unavailable, `liquid_ml_min` is None, and `af_flow` ("Atomised liquid flow") has no values: "No fit", and
   the throughput goal silently drops out of the desirability (the CCD best setting became atomised fraction
   alone -> lowest feed). Recorded GLR is unaffected. Fine on Python >= 3.10 (Mac, lab PC). **FIXED
   2026-10-13 (Mac):** GUI_Clean's Cone_4 guard catches any exception; and if the formula still cannot be
   imported, both analyses now say so in capitals (console, top of the report) and the Model page marks the
   atomised liquid flow row "unavailable" (`covariates.formula_problem`, `stats.flow_warning`). The home PC
   needs `git pull`; then re-Analyse there to get atomised liquid flow.

Response surface tab, found 2026-10-11 (tested on fakes: the 9x3 + 4 next-session runs on another day):
- **Loading a next session with the original runs is not handled properly yet.** (a) Confirmation runs
  are swept INTO the fit (8,700 sccm becomes a 4th gas level, "edge" points), so they no longer test the
  model unless Validation is ticked by hand; (b) the design is re-detected as "irregular" and the
  original point types are relabelled (face centres -> "other"); (c) the fit has NO day/session offset
  term, so a day-to-day shift in D-optimal runs added to the fit is absorbed into the surface (the centre
  anchor is recommended to measure it, but nothing uses it yet). Proposed fix (not started): Notes
  "CCD next run N confirm" -> validation automatically; keep the first session's design and classify
  the new runs as added; a session offset term when runs span days, estimated via the anchor.

- ~~Model page goals: Minimise ramp unswapped; no target for Hit a target~~ **FIXED 2026-10-11**
  (`tab_rsm.goal_for_fit`): worst scores 0 and best 1 for every aim, a target is the best column
  (symmetric ramp out to worst), a backwards ramp is refused with the response named; older saved
  rsm_model.json (low/high keys) still read. Tests in test_tab_rsm.py, mutation-checked.

- ~~Steepest ascent / new CCD could walk feed down to 0 steps/s~~ **FIXED 2026-10-11:** feed floor
  2,000 steps/s (Ben: the lowest that sprays usefully) in `rsm_design.RIG_LIMITS`; found when Ben's
  practice goals (size x3 + atomised fraction, no liquid-flow goal) sent the path to "8200 sccm, 0 steps/s".
  Guide now warns that correlated goals stack and a fraction goal alone favours the lowest feed.
  **Ben's goal trial on the 9x3** (2026-10-11, `Practice Folder/Ben 9x3 CCD practice` vs
  `output/9x3 response surface (gas x feed)/Baseline (default goals, importance all 1)`): best setting
  moved from 8,744 sccm / 8,000 steps/s to 8,187 / 4,000; driven by the goal SET (liquid-flow goal
  removed, three size goals), not the importance numbers (all-1 importance gave 8,626 / 4,000).

Elsewhere:
- **Static specks detected as droplets.** The same ~5 places (e.g. x1824 y648, x336 y852,
  x1416 y108, x918 y1128) are detected as 40-60 um in-focus droplets in 20-70% of frames, in every
  run of 10/05: dirt on the window or sensor, not spray. Small, so D32 is barely affected (pulled
  slightly down); droplets per frame is inflated by a few per frame, relatively most at 3000 sccm
  (~34/frame). No trend with time. Fix later by rejecting detections that sit on static dark
  features of `background_median.tiff`. Found 2026-10-07 (scratch script, read-only).
- `measure_run.py`'s model-only atomised fraction and `score_v2.py` double-count cross-class mask
  overlap in the denominator. The quoted (classical) fraction is structurally immune.
- `master_log.xlsx`: one row saved during the GLR-column bug (after 09:04, 2026-10-05) has
  "NO DATA AVAILABLE" in Notes and graphs in O/P. Real notes are in that run's `run_summary.xlsx`.
  Scripted repair offered, not done. Close Excel first.
- `GUI_Clean.py` still creates `Brightest_Frame` (concept retired 2026-09-27).
- `score_v2.py` is model-agnostic despite its name; rename to `score_predictions.py` some time.
- `requirements.txt` is stale (lists customtkinter, not PySide6 / torch / detectron2).
- Several `__pycache__/*.pyc` files are tracked in git despite `.gitignore`; they churn across
  machines.

## The measurement currently in force (sizer 2.2.0, since 2026-10-08)

- Model: v3 "Eden" (`training_2026_09_25_15_20_37`, iter 19000), tiled inference at native scale,
  score threshold 0.30, stride 10, extremes-only images.
- **D32** = in-focus droplets only (`t_min <= 0.70` focus gate, interior-pixel robust core
  estimator), half-max sizing at/above the **40 um** split, model mask below it, **then the
  sharpness rule**: an in-focus droplet >= 50 um is reclassified out of focus when
  `fill_ratio < 0.85` or `extinction_conc < 0.60`. A reclassification, never a deletion: counts and
  the atomised fraction are unchanged. So D32 is "D32 of the round, sharp droplets"; its gas effect
  is ~2/3 selection (see Where we are). From `measure_run.py` -> `droplets_0.30/summary.json`.
  `--no-sharpness-rule` gives 2.1.0.
- **Atomised fraction (quoted)** = `liquid_0.30/classical_summary.json` `atomised_pct_pooled`:
  half-max droplet numerator over a classically segmented whole-frame liquid denominator
  (`classical_liquid.py`). `summary.json` `atomised_pct` is model-only, reference only.
- Folder names: `droplets_<thr>` / `liquid_<thr>` (readers also accept the old
  `measurement_` / `classical_`).
- Mixed `sizer_version` is refused by the analysis, by design.

## Campaigns and where the data is

| what | where |
|---|---|
| 27 replicate runs (2026-10-05) | `/Volumes/LaCie/Experiments/2026/10/05/<run>/shadowgraph/analysis/` |
| their Taguchi output | `/Volumes/LaCie/Experiments/Taguchi/9x3 Taguchi Repeats/` |
| first L9 (2026-10-01), 2.0.0 | runs in `Experiments/2026/10/01/`; re-analysis in `Experiments/Taguchi/First Taguchi Trial (RPM, SCCM, Silicone Flow)/` (Ben calls it "Taguchi First Trial") |
| 20-frame validation set | `/Volumes/LaCie/Experiments/Real_Data/06_validation/` (never trained on) |
| free-hand sizing set (51 droplets) | `/Volumes/LaCie/Experiments/Real_Data/07_validation_taguchi/` |
| pipeline code | `AI/Real_Data_Code/` (`measure_run.py`, `classical_liquid.py`, `batch_runs.py`, ...) |
| Taguchi app | `src/ai/Taguchi_Analysis_UI/` (plan: `docs/TAGUCHI_ANALYSIS_UI_PLAN.md`; Windows run sheet: `docs/TAGUCHI_WINDOWS_RUN_SHEET.md`) |
| capture GUI | `src/gui/GUI_Clean.py` |

Factors in the 27-run design: gas flow 3000/6000/9000 sccm, bubbler 300/600/900 rpm, silicone
4000/6000/8000 sps; orifice 1.2 mm, bubbler height 1. GLR is a covariate, not a factor.

## Machines

| machine | role | Python |
|---|---|---|
| Mac | analysis, development | `/Users/benschofield/anaconda3/envs/phantom/bin/python3` (no torch/detectron2) |
| home PC (BENS-PC, RTX 5060 Ti) | batches, training. LaCie = `D:` | `C:\Users\BenSc\anaconda3\envs\Detectron\python.exe` only (system 3.11 torch can't run sm_120) |
| lab PC | capture rig | system Python 3.11 (`AppData\Local\Programs\Python\Python311`) |

**LaCie on the home PC drops off USB** (3 times on 2026-10-06; hardware, not load-correlated).
exFAT has no journal: eject before unplugging; after any disconnect sound run Scan and repair
before using it.

## Settled — do not re-derive

Full statements and reasoning in the legacy handoff ("Established facts", "Decisions already
made", "Bit depth", and the dated sections).
- 10 um/px (100 px/mm), already calibrated. Frames are 12-bit stored as uint16.
- Classes in the model: droplet / blob / filament. Droplet size ceiling 200 um.
- Primary response: area-weighted atomised fraction (larger is better). Secondary: D32 of
  droplets (smaller is better). Count-based ratios rejected.
- Training data by compositing real objects, multiplicatively in transmission. 800x800 crops,
  tiled inference, never resize at inference.
- Gas density default 1.184 kg/m3 (air at 25 degC, matching the Alicat's STP), not 1.293.
- Capture: **390 fps** (Ben, 2026-10-08; the GUI standard), exposure 4 us, 2048x1152, 13 s
  post-trigger. Shorter videos than at 190 fps, so **two runs fit one syringe refill**. At stride
  10 the effective rate is 39 Hz, which has no integer ratio with the bubbler's 5 / 10 / 15 Hz, so
  no aliasing (190 fps was the earlier suggestion for the same reason). Shorter captures than the
  suggested 25 s are deliberate: don't "correct" them.
- Sizer **2.2.0** (sharpness rule) is the project's measurement, for good unless Ben says
  otherwise. Supersedes "focus rejection deferred".

## Standing rules

- Never modify raw data. Analysis code and outputs go in their own folders; one config per study.
- Phase-gated: do the phase asked for, then STOP and report. Report findings that change the plan.
- State every assumption explicitly in reports. "Not significant" is never "no effect".
- Give Ben exact paste-able commands with absolute paths and the real interpreter.

## Recent changes (newest first; trim to ~10 entries, older ones live in git history)

- 2026-10-15 (lab PC): **Calibration day, no silicone.** Cd tests DONE for 1.2 / 0.8 / 0.5 mm (11:12-11:34,
  `Calibration/Orifice Cd/2026/10/15/`, not yet analysed). Bead captures in `Calibration/Imaging Work/2026/10/15/`:
  one capture per single-size sandwich at focus (155.8 -> 37.36; no extra patches or bg: the slide cannot move
  sideways, and the background comes from each photo), then the mixed sandwich through focus -8 to +8 mm (manual
  stage, ±8 mm range); every run checked: one 1.15 GB cine and the right Notes. Falling beads recorded in PCC to
  `.../falling/`. **Falling beads: only ~10% of a pour's frames contain beads (Ben), so stride 10 can miss a
  pour's large beads.** Decided: keep stride 10 and trim each cine in PCC to the stretch with beads; re-run a
  pour at `--stride 1` if a size ends up with too few in-focus beads (docs/BEAD_CALIBRATION.md). One pour per
  size is enough if it has enough beads (the static captures carry the size bias and DOF). GUI_Clean on the rig: run sheet, Save under and the 1 s post-trigger
  worked; bead rows (0.5 mm nudge, 3.4 s) pop up "Test shorter than the video": press Trigger early.

- 2026-10-15 (Mac): **Python 3.9 (home PC Detectron env): eleven signature annotations fixed.** `X | None` in a
  function signature is evaluated at import and fails on 3.9. Affected:
  - GUI_Clean.py, 8 (4 since August/October, 4 from 2026-10-14). So GUI_Clean has NEVER imported on the home PC:
    this, not only Cone_4, is why bug 6 (no GUI formula: no atomised liquid flow or GLR there) persisted;
  - liquid_volume.py: liquid stage 2.3.0 would have crashed in the home PC's batch;
  - remeasure_liquid.py and draw_more_classical.py.
  All quoted. A scan of 94 files finds no 3.9-unsafe annotation left, and all compile with a real Python 3.9
  (the Mac's 'Hello' env). Not yet run on the home PC itself.

- 2026-10-14 (Mac): **Size calibration with glass beads, built for Thursday morning** (plan
  `~/.claude/plans/cozy-orbiting-swing.md`; procedure `docs/BEAD_CALIBRATION.md`). Beads 37.36 / 56.28 / 76.39 /
  98.1 / 155.8 um (certified) and a micrometer slide holder. The method is Blaisot & Yon 2005 (Exp. Fluids
  39:977-994, verified; Wang 2022 FocGAN has no physical calibration).
  - Captures are run-sheet rows. The run sheet has two new optional columns:
    - 'Save under' routes a run to e.g. `Calibration/Imaging Work` instead of Experiments (one helper,
      `_run_base`, for Start, save and preview);
    - 'Post-trigger (s)' sets the camera (Apply Config) to 1 s for bead rows and back to 13 s for spray rows,
      without the standard-capture question for that field only. SETUP instructions pop up.
  - Thursday's sheet is rebuilt in this order:
    - 43 sandwich captures: a mixed sandwich at 23 z from -4 to +4 mm, 4 focus patches + bg, 5 single-size
      slides x (2 + bg);
    - then the 3 Cd tests (saved under `Calibration/Orifice Cd`);
    - then the 16 spray runs;
    - last, the falling beads: 2 pours per size, 10 runs, after clearing up, optics untouched. The analysis
      pools the two pours.
  - New `AI/Real_Data_Code/bead_calibration.py` (Mac, no AI for static beads):
    - averages each capture (40 frames);
    - background from the frame itself, two passes, < 1 % on a gradient; dust from bead-free captures
      dropped (an averaged spray frame shows ~200 specks);
    - follows each bead through z;
    - per bead: the current sizer exactly (measure_run functions, a T < 0.95 mask in place of the AI's),
      d(l) curves, ring flag, and Blaisot C, chi and the contrast-corrected size, from the model computed
      numerically;
    - outputs: bias at focus, l*, ring and 2.2.0-rejection shares, effective DOF of the current rule
      (the 1/DOF weight), size-stable range, chi(z) fit; falling beads from the AI's droplet_sizes.csv;
      reticle array scale ready.
  - On synthetic Blaisot-model beads: chi recovered within ~1-2 um, contrast-corrected size within 2 %.
  - `Calibration/Imaging Work/README.md` + `targets.json` on the LaCie (Ben: add supplier, lot, spreads).
  - Tests: test_bead_calibration (11), run-sheet window checks 9.
  - Falling-bead AI at home: new `AI/Real_Data_Code/run_ai_where.py` runs the AI chain (process_capture) only on
    runs whose Notes start with given text (`--notes "BEAD fall"`; `--dry-run`; restartable), so the 48 static
    captures in the same day folder are not inferred. Command in docs/BEAD_CALIBRATION.md. Tests:
    test_run_ai_where (2).

- 2026-10-14 (Mac): **GUI_Clean top bar: master_log button, AFG light removed** (untried on the rig). A small
  button right of LaCie opens master_log.xlsx. GREEN = safe; RED and not clickable while a run is going, its
  save is pending, a save is being written, or the AI's re-save is still to come (Excel locks the file and
  the save would fail). START also checks (Windows) whether master_log is open and asks before starting, as a
  run's save fails while Excel holds it. master_log's path now comes from one helper
  (`_master_log_path`) for the save and the button. Tab padding 24 -> 18 px so the nine tabs fit a ~1,600 px
  window (all fit at 1,920). Checks: tests/gui_window_checks.py (8, run by test_run_sheet.py).

- 2026-10-14 (Mac): **GUI_Clean Run sheet tab** (after Extremes; untried on the rig). Load a .csv/.xlsx (the
  app's next_runs.csv works as it is; columns matched loosely): the next run's gas, RPM, feed, travel, insert,
  orifice length and Notes are filled in. Only once the end-of-run save to master_log has FINISHED does it ask
  'Did this run go OK?' (with a box to add to the run's Notes): Yes fills in the next run; No appends
  '[bad run, redone]' to the saved run's Notes (re-saved) and keeps the row to redo; Decide later changes
  nothing. A later save of the finished run (e.g. after the AI) keeps that run's own Notes (`_notes_lock`), not
  the next run's. Settings that differ from the sheet are listed in the question; a change of insert pops up a
  reminder (with a Cd test's instructions); nothing is filled in during a run. Progress lives on the LOCAL disk
  (~/.hpatr/run_sheet_state.json) and is resumed after a restart without filling the boxes. New
  `src/gui/run_sheet.py` (no Qt). Thursday's sheet: `docs/notes/2026-10-15_thursday_run_sheet.csv` (also
  `Experiments/Run sheets/` on the LaCie). The LaCie probe now answers through a Qt signal (a QTimer posted from
  its thread could hit a deleted window). Tests: test_run_sheet (5 + the real window's flows in a separate
  process, tests/gui_run_sheet_checks.py: building and deleting GUI_Clean's window crashes Qt, see Known bugs).

- 2026-10-14 (Mac): **Pressure / gas log: gaps then jumps, explained and fixed.** Scan of the 33 CCD runs
  (`run_summary.xlsx` Pressure sheets, ~0.22 s spacing): 30 runs have a 1-4.3 s gap followed by a burst of
  5-21 readings at one instant, 12 of them inside the camera window. Cause: each Alicat reading was stamped
  when the GUI THREAD handled it, and the GUI thread stalled; the reader kept reading (burst size = gap /
  0.2 s), so the readings were queued, then logged together. The Portenta reader stalled at the same
  moments (serial log silent 4-5 s, then a burst). Both touch the LaCie: `find_lacie_drive()` every 5 s on
  the GUI thread, and `log_serial` opening the LaCie log per line on the reader thread; most stalls fell
  25-70 s after the previous run's 15 GB cine finished saving. Effect on the CCD numbers: P0 <= 0.005 bar,
  delivered gas <= 0.6% on flow-controlled runs, up to 6% on the pulsing pressure-limited ones (110227:
  2,813 -> 2,639 sccm); no regime or conclusion changes. FIXED in GUI_Clean (untried on the rig): readings
  stamped at read time on the reader thread; serial-log lines queued to one writer thread (a busy drive no
  longer holds up the Portenta reader, whose stall could block the stepper once the board's TX buffer
  fills); the LaCie poll on a worker thread. Old logs repaired in the analysis: `operating.respace_queued`
  spreads a burst back across its stall instead of dropping all but one reading. Tests:
  test_pressure_log_timing (6).

- 2026-10-14 (Mac): **Busiest / mean-diameter frames drawn the classical way.** measure_run's drawings of
  the 2x2 slide frames outlined filaments thinly, so un-atomised liquid was hard to see (Ben). The liquid
  stage (`classical_liquid.py`, extremes mode) now draws those frames too (un-atomised liquid filled, classical
  atomised % printed; `more_extreme_frames` in its summary); the 2x2 slides, `gallery_more` sheets and
  GUI_Clean's Extremes tab prefer that drawing, and the slide notes say which drawing is shown. New
  `AI/Real_Data_Code/draw_more_classical.py` back-fills older runs: liquid stage re-run into a temp folder,
  numbers gated against the run's summary, only the new PNGs copied (about 2 min a run alone, ~4 min three at
  a time: it re-reads every frame for the window mask). CCD day back-filled 33/33, numbers unchanged in every
  run; `Taguchi/CCD/Rec CCD 4 factor 20-60um/` re-published (157 slides, all 33 grids classical, best setting
  unchanged: 11,000 / 100 / 5,000 / 1.2). Then a FAST path: a run with no window drops (26 of 33) is
  re-measured on the drawn frames only, ~4 s instead of ~2 min, per-frame rows gated (checked on 105301:
  images byte-identical to the full pass). Tests: test_more_extremes +2.

- 2026-10-14 (Mac): **Throughput is the default objective.** The spray is collected and size-filtered (Ben), so
  `rsm_responses.DEFAULT_GOALS` is now in-band droplets per second (`rate_band`, importance 3) + atomised fraction
  (importance 1), and `run_metrics.DEFAULT_BAND_UM` is 20-60 um (was 30-50; the band starts at 4 px of area,
  22.6 um). New Model pages start there; a saved `rsm_model.json` keeps its own goals. Runs without the rate
  (before liquid 2.3.0, or no syringe flow) are left with atomised fraction. The Taguchi tab's band-count
  responses also use the new band. Docs: definitions, RSM_GUIDE, IMAGING_PIPELINE_REFERENCE. Tests:
  test_tab_settings (band default), test_gas_regimes +1.

- 2026-10-13 (Mac): **Silicone film at the exit, a covariate; flux and film in the workbooks and decks.** New
  `orifice.py` (gas properties by the run's Gas tag, ideal gas-only flux choked/subsonic, Cd lookup from the new
  `orifice_cd.json` -- all Cd null = ideal 1.0 until the test -- and the split: gas share alpha, silicone speed u_L,
  annular film h). Covariate film_um beside GLR and the flux; fig_film_thickness, fig_orifice_model (a diagram with
  the maths); a "Silicone film at exit" workbook sheet in both publishes (per-run table, the diagram beside it, the
  maths and caveats in text); report sections; deck slides "How the gas flux and the silicone film are estimated"
  + flux + film (Taguchi and CCD). No-spray runs are now left out of every covariate FIT (GLR, flux, film) but
  plotted (grey x): the flux exponent on atomised fraction is +0.36 [0.29, 0.42] without the two dribbles (was
  +0.86); film exponent -0.46, r -0.76; Spearman film -0.90 / flux +0.91 over 31 spraying runs. CCD re-analysis
  re-published (deck slides 58-60). `orifice_cd.py` now uses `orifice.py`'s formula (one source). Tests:
  test_gas_flux +6, test_deck +1, test_gas_regimes +1; full suite 851 passed. The 9x3 Taguchi output was not
  re-published (its runs do have gas logs and camera windows, but are still liquid stage 2.2.0).

- 2026-10-13 (Mac): **Orifice Cd test ready; lamella AI found and compared.** New `AI/Real_Data_Code/orifice_cd.py`
  (steady gas steps from gas-only runs' logs -> Cd per insert, choked steps preferred, subsonic fallback flagged,
  optional line-loss run, `--write` updates `src/ai/Taguchi_Analysis_UI/orifice_cd.json`) and the rig procedure
  `docs/ORIFICE_CD_TEST.md` (Speed 0 static run, gas ladder 2,000-12,000 sccm, Notes "CD TEST ..."). Gas alone
  chokes 0.5 mm (from ~4,000 sccm) and 0.8 mm (10-12k); 1.2 mm is subsonic only (needs the line-loss run); 1.8 mm
  cannot be measured this way (<= 1.07 barA). Tests: test_orifice_cd (2). The lamella AI's only batch output
  (`Lamella/Tester_Tiffs/Output_Tester/lamella_thickness.csv`, 36 frames) is from
  `2026/06/25/133838_NNoNozzle_5.0BAR` (0.5 mm add-on + 1.2 mm orifice, feed 4,000, ~2.65 barA): ~0.38 mm of
  silicone per wall, against 0.31-0.35 mm from the annular estimate for the CCD 1.2 mm runs at similar pressure
  (phase-12 note).

- 2026-10-13 (Mac): **Orifice length recorded (GUI_Clean).** Nozzle card: "Orifice length" (mm, hardware state like
  bubbler height, remembered; a non-blocking reminder at Start when empty). run_summary Metadata gains
  'Orifice length (mm)' (a number, or NOT RECORDED); master_log gains 'Orifice Length (mm)' as column C (19 columns,
  A..S) via `migrate_master_orifice_length()`, which runs on the next save after the mean-diameter migration.
  Checked with a full offscreen save against a COPY of the live master_log: header right, the new row's values
  are numbers, all 292 existing images moved one row down and one column right, old rows blank in C. The lab PC's
  log migrates itself on its first save after `git pull`.
- 2026-10-13 (Mac): **Gas mass flux at the orifice, a covariate (phase 12 decision).** `covariates.py`: per run
  G = delivered gas mass flow / orifice area (kg/m2/s; camera-window gas > achieved > set point; the run's recorded
  gas density, none guessed), its standard-density exit velocity equivalent, orifice length and L/D (from
  run_summary 'Orifice length (mm)', read back from a GUI_Clean-written file: OK). Trends beside GLR; new
  fig_gas_flux (coloured by orifice, hollow = did not get its set gas, velocity on a top axis), report section,
  deck slides (Taguchi and RSM; the RSM report now takes the shared analysis), workbook sheets. Loud warning when
  runs in one analysis have different orifice lengths (a hidden factor), softer when only some record it. CCD day:
  C7 522, C8 537, 0.8 mm 342, 1.2 mm 152, 1.8 mm 68 kg/m2/s; atomised fraction r = +0.85. Tests: test_gas_flux (7)
  + 2; full suite 841 passed. Open: the two no-spray dribbles (G 3-5) dominate the power-law exponent (+0.86);
  Ben to say whether no-spray runs leave the covariate fits (recommended).

- 2026-10-13 (Mac): **Throughput is the objective; goal ramps reach the surface; master_log droplets/s.**
  Ben: the spray is collected and size-filtered, so the target is in-band droplets produced per second; band
  **20-60 um**. (1) Fix: a goal's blank "1 at (best)" is now the best its fitted surface reaches in the tested region
  (`rsm_responses.reach_surface`, `RsmResults.surface_best`; report note; Model-page text; RSM_GUIDE), not the best
  run seen. Before, every setting predicted beyond the best run scored a flat 1 and the optimiser stopped at the
  first it tried (10,740 sccm; then feed 3,000 when maximising a rate that rises with feed), which also killed
  the steepest-ascent and new-CCD suggestions. Tests in test_gas_regimes (+2). (2) Throughput analysis, 20-60 um,
  goals in-band rate x3 + atomised fraction x1 (`Taguchi/CCD/Rec CCD 4 factor 20-60um/`, `reanalyse_ccd.py
  --model --band`): best 11,000 sccm / 100 rpm / feed 5,000 / 1.2 mm, predicted 288k in-band droplets/s;
  steepest ascent to 12,000 / 0-50 rpm / feed 5,200-5,300 (~330k/s, extrapolated); suggested next CCD gas
  8-12k, rpm 0-800, feed 4,000-6,000. Best measured: C7 280k/s (0.5 mm ceiling recipe), but its twin C8 gave 187k/s.
  (3) master_log: new column N "Droplets/s (20-60 um)" (`MASTER_RATE_BAND_UM`, `droplet_rate_band`,
  `migrate_master_droplet_rate`; 20 columns A..T), written as a NUMBER by GUI_Clean after the AI chain (same maths
  as the app, matches it to the whole droplet); the 33 CCD rows back-filled (C7 280,194); backup in
  `Logs/Backups/master_log BACKUP 2026-10-13 before droplets per s.xlsx`. The live log is now 20 columns:
  **the lab PC must `git pull` BEFORE its next capture** -- the old GUI stamps its 17-column headers and would
  write rows into the wrong columns.
  Decks: every goal response now gets map slides (`rsm_figures.mapped_responses`: goals, then the headline
  responses, lag-1, pressure; the rate goal had none), and a "How droplets per second are estimated" cards slide
  (`deck.rate_cards`, both decks, when any run has a rate). 20-60 um deck: 157 slides, rate maps 4-8, the
  explanation 67. Full suite 858 passed.

- 2026-10-13 (Mac): **Phase 10, more extreme frames.** `measure_run.py`: per-frame body now `measure_frame()`;
  `pick_more_extremes()` / `write_more_extremes()` add the frames with the most in-focus droplets, the most droplets
  in total and the largest / smallest mean in-focus diameter (frames with >= `MIN_DROPLETS_FOR_MEAN` = 10 in-focus
  droplets) into `droplets_<thr>/extreme_frames_more/` (PNGs + index.json / index.csv), summary.json
  `more_extreme_frames`, per_frame.csv gains `mean_d_in_focus_um` as its last column; everything else byte-identical
  (checked on 105301). Back-fill without the model: new `render_more_extremes.py` (re-measures only the chosen
  frames from predictions.json, gate against per_frame.csv, writes via .partial/): all 33 CCD runs done, 33/33
  passed, ~2 min, only the new folders written. App: `figures_extra.gallery_more()` (galleries/gallery_more_<c>.png,
  4 columns), in the Taguchi and RSM reports and decks. GUI_Clean Extremes tab shows the four. Tests:
  test_more_extremes (16); full suite 832 passed. DECIDED (Ben, 2026-10-13): the mean-diameter extremes' floor is
  half the run's median in-focus count per frame, never below 10 (`mean_floor`; was a flat 10, which picked thin
  frames: 130918's largest mean 57.9 um from 17 droplets -> now 55.1 um from 34). All 33 CCD runs redrawn (gates
  passed; the chosen frames now have a median 35-42 droplets behind them, was 22-23); index.json records the floor.
  test_more_extremes +1. Decks (Taguchi and CCD): these frames are now one 2x2 slide PER RUN (most in focus, most in
  total / smallest, largest mean; `deck._Deck.grid`, `tw_more_run`, `more_grid_slides`), filling the slide below the
  title (3.2 x 1.8 in per frame; 16:9 frames make a 16:9 grid, so the height sets it), captions with the counts and
  means, the legend and the floor rule in the notes; the per-condition strip stays in the report. CCD deck: 150
  slides, grids 118-150 (grid frames embedded as 1000 px JPEGs, `deck._slide_jpeg`: the full-size PNGs had put the
  deck at 457 MB, now ~54 MB). Ben's own run with the recommended goals (atomised x3, in-band rate x2, D32 x1, CV x1,
  mean diameter not a goal): `Taguchi/CCD/Rec CCD 4 factor/` -> best 11,000 sccm / 100 rpm / feed ~4,100 / 1.2 mm
  (the rpm from a weak rpm x orifice term in the rate, p 0.03), best observed 125754; re-published headless with its
  own model (`reanalyse_ccd.py --model`). Confirmed: the per-frame mean uses in-focus droplets only. test_more_extremes +1. No
  `pipeline_spec.OUTPUTS` entry for the folder yet.

- 2026-10-13 (Mac): **Phase 11 (window drops, GUI side) and master_log numbers.** New `src/gui/window_check.py`
  (numpy + OpenCV, no Qt): live frame / clean reference, normalised by its median, smoothed; a spot = a piece
  < 0.90 of the clean window, >= 400 px, with a core < 0.80. Set on the CCD backgrounds: C20's drop reads 0.15 at
  its core; consecutive clean backgrounds read clean. GUI_Clean Camera tab "WINDOW CHECK" card (Save clean
  reference to ~/.hpatr/window_reference.npz, Check now, "Check at Start Experiment", remembered); Start
  Experiment checks before anything moves, shows new spots boxed, "Cancel: wipe first" / "Start anyway";
  run_summary gains "Window check (before run)"; How To updated; every run sheet's summary now says to wipe or dry
  the window before every run (`rsm_design.BEFORE_EVERY_RUN`). Tests: test_window_check (10). Offscreen-tested with
  a fake camera; NOT yet on the rig (thresholds may need tuning there). Phase 10 GUI side: the Extremes tab gains
  four panels (most in-focus, most total, smallest / largest mean diameter) read from
  `droplets_<thr>/extreme_frames_more/index.json`. master_log: GUI_Clean now writes Speed, Motor Travel, Bubbler
  RPM and Bubbler Height as NUMBERS (`as_number`; they were text from the entry boxes) in master_log and
  run_summary; the existing 263 text cells (Speed 132, Travel 131) converted and swapped in at 16:0x (backup
  `Logs/Backups/master_log BACKUP 2026-10-13 before numbers.xlsx`; re-audited: no numbers stored as text outside Notes). Phase 12 evidence and opinion: `docs/notes/2026-10-13_phase12_physical_variables.md`
  (gas exit mass flux orders both regimes, Spearman +0.91; GLR -0.21; P0 a symptom; keep set points as factors,
  add the flux as a covariate).

- 2026-10-13: **Gas flow can go to 12,000 sccm** (Ben): 11,000 was the CCD day's top set point, chosen for
  headroom. Already the app's `rsm_design.RIG_LIMITS` and GUI_Clean's entry range; the next design should use
  it (atomised fraction and the production rate still rising at 11,000).
- 2026-10-13 (Mac): **CCD follow-up, phases 8 and 9; three RSM fixes; liquid 2.3.0 re-run.**
  Liquid stage 2.3.0 re-run on the Mac for all 33 CCD runs (45 min, 0 failed; 2.2.0 outputs kept in
  `<run>/shadowgraph/analysis/_liquid2.2.0/`): atomised % rose in 10 runs (window drops / static pieces),
  e.g. C20 5.96 -> 10.51, C9 8.84 -> 16.38. (8) Rate, read-only (`docs/notes/2026-10-13_droplet_rate_investigation.md`):
  mass balance gives the liquid's residence time in the field, 1.4-2.8 ms (4-8 m/s), falling in proportion to
  gas; along the 1.2 mm gas axis the in-focus count is flat while the production rate doubles, so count goals
  under-reward gas (rate vs concentration Spearman 0.84); the 390 fps cines cannot give velocity (nothing pairs
  across 2.56 ms; 4 us blur bound <= ~4 m/s, optical); definitions.md decorrelation section corrected (transit
  < 1 frame). Ben to decide: a mass-balance rate response, and a 10-min exposure series on the rig. (9) CCD
  re-analysed headless into `Taguchi/CCD/CCD 4-factor 12-10-2026 reanalysis 13-10-2026/`
  (`docs/notes/2026-10-13_CCD_reanalysis.md`): 21 flow-controlled runs in the fit; atomised fraction = gas (+) and
  orifice (-, ln) only, simplified predicted R2 0.89, no lack of fit; rpm and feed free there; 0 rpm control =
  centres; best ~10,700 sccm, 1.2 mm; 0.8 mm check below the ln extrapolation (orifice^2 needs 0.8 in the next
  design); pressure-limited block: set gas no effect, rpm +741 and feed -1,960 sccm delivered; C7/C8 (35%) are the
  day's best and pressure-limited. Fixed (tests in test_gas_regimes): the goal gate now judges the SIMPLIFIED
  model's predicted R2 (`ResponseFit.used` / `r2_pred_used`, `weak_goals`; the full quadratic read -0.28 at 21
  runs / 14 terms and dropped every goal); "Strengthen the model" runs stay inside the fitted span and say which
  sizes were held back and why; factors no steering surface uses (`free_factors`, `RsmResults.free`) are held at
  the centre and named, not reported as edge optima (the optimiser had returned its first grid value). master_log:
  the 33 atomised % cells with 2.3.0 values are prepared and checked (only column L, 26 cells change; 292 images
  byte-identical) at `scratchpad/mlog/master_log_23.xlsx`, backup `Logs/master_log BACKUP 2026-10-13 before liquid
  2.3.0.xlsx` made. Copied in at Ben's go-ahead after Excel had re-saved the file on close (cells unchanged;
  Excel had stored identical images once, 91 -> 27 MB); the update was re-applied to that file, only column L
  changed (26 cells), all 292 image positions kept. **Opt-in mass-balance rate responses** (`run_metrics`:
  `rate`, `rate_band`, `mass_balance_rate`; syringe flow x atomised fraction by volume / pi/6 <d^3>, with a frame
  bootstrap; blank before liquid 2.3.0): a rate that does not fall when gas speeds the spray up. Tests in
  test_run_metrics (+3).

- 2026-10-13 (Mac): **CCD follow-up, phases 5 and 6.** (5) GUI_Clean: a live "Gas regime" readout beside the
  MFC values (flow-controlled / PRESSURE-LIMITED / GAS SHORT after > 5% short for 3 s; logged once per
  episode, orange log border), and run_summary Metadata gains "Gas delivered in camera window (sccm)", its
  p10-p90, "Upstream pressure in camera window (barA)", "Gas regime", "Gas settled", computed with the
  analysis app's own `operating.py` (imported by the GUI; numpy only). Offscreen-tested; NOT yet on the
  rig. (6) Orifice on a log scale: `FactorLevels.log` + `decode()`, Model page "Log scale" tick per factor
  (default orifice; older saved models get the default), passed as `log_scale`. Found and fixed with it:
  with the pressure-limited runs left out, the coding still spanned 0.5-1.8 mm, so the optimiser searched
  (and could recommend) unfitted orifices; now the levels refit to the fitted runs (1.2-1.8) and settable
  levels outside the span are not offered (warning names them). Tests: test_gas_regimes (+2),
  test_tab_rsm (Model page), test_rsm_recommend's linear-world fixture now asks for linear coding.

- 2026-10-13 (Mac): **Liquid stage 2.3.0** (`classical_liquid.py`, new `liquid_volume.py`,
  `remeasure_liquid.py`). Two passes: a persistence map of un-atomised liquid, then areas with a WINDOW
  MASK (still, compact, flat-topped pieces un-atomised in >= 20% of frames: drops that landed mid-run);
  out-of-focus model pieces with mean T >= 0.97 are not liquid (drops already divided out); per-frame
  volumes (OpenCV only: the Windows env does not promise scipy / scikit-image) for a SECONDARY
  volume-based atomised fraction. Rules off = bit-identical to 2.2.0 (C20, 508 frames). Tests:
  `test_liquid_stage.py` (12). App: refuses mixed liquid-stage versions; responses "Atomised fraction by
  volume, estimated" and "Atomised liquid flow index, volume-based" (blank before 2.3.0); provenance row.
  **CCD day re-run on the Mac** (~45 min, 3 at a time, LaCie-read bound): each run's `liquid_0.30/` moved
  intact to `shadowgraph/analysis/_liquid2.2.0/liquid_0.30/` first; droplets_0.30 and raw untouched.
  Spot checks before the run: C9 8.84 → 16.38%, C21 10.81 → 15.08%, C20 5.96 → 10.51%. The master_log's
  33 atomised % cells still hold the 2.2.0 values (to update after the re-run, with Ben's OK).
- 2026-10-13 (Mac): **CCD follow-up, phase 4: droplet count in a size band.** Response "In-focus droplets
  per frame in the size band" (`band_per_frame`; lo <= d < hi, default 30-50 um, Settings "Droplet count
  size band"; frame bootstrap); not a default goal. `stats.AnalysisOptions.band_um`. Also: the Response
  surface tab now uses the Settings size bins (it used the defaults). Docs: definitions, RSM_GUIDE,
  IMAGING_PIPELINE_REFERENCE.

- 2026-10-13 (Mac, read-only, sub-agent; numbers re-checked): **F2 area vs volume and H1 window drops on the
  CCD day** (`docs/notes/2026-10-13_area_vs_volume_and_window.md`). Masks rebuilt with `classical_liquid`
  match `classical_per_frame.csv` on 16,764 / 16,764 frames. **Volume vs area:** ρ 0.84 (all), 0.88
  (flow-controlled); volume ≈ 0.24-0.27 × area (un-atomised pieces carry ~235 um of depth per pixel,
  droplets ~50 um); no effect changes sign, but the gas effect doubles and rpm / feed fall below noise;
  volume is 3× noisier and its scale model-dependent (round vs ribbon ×1.6). **Window drops**, 8 runs, two
  routes: (A) a drop lands mid-run, so it is not in the background median and is counted as liquid from
  then on (C9 +7.2 points, C21 +4.0, C2r2 +3.5, C4, C10r2); (B) a drop in the median all run divides out
  of T but re-enters through the MODEL's out-of-focus non-droplet union, because T ≈ 1 always passes the
  out-of-focus test (C20: 41% of its un-atomised pixels; C6). Candidate fixes: (a) drop out-of-focus
  non-droplet detections with mean T ≥ 0.97 (C20 5.6 → 15.1% on the sample), (b) a persistence mask or
  rolling background. Volume is ~10× more sensitive to window drops, so a window fix must precede any
  volume response. Liquid-stage re-run: ~31 min for the day on Windows (+ volume add-on). **Decided (Ben):
  both window fixes (a) mean-T >= 0.97 rule and (b) persistent + still mask, plus volume as a SECONDARY
  response, in one liquid-stage change; re-run on the Mac (CPU only, ~45 min), old outputs archived.**

- 2026-10-13 (Mac): **CCD follow-up, phase 3: gas regimes and best settings.** New `operating.py` reads each
  run's Pressure sheet (gas + P0 in the camera window, 10 s before it, the whole-run trace) and classifies it:
  flow-controlled (>= 95% of set), pressure-limited (below, with P0 within 0.5 bar of the supply ceiling,
  new Settings field, default 9.5 barA), gas short, unknown; "settled" from medians (pulsing defeats a
  straight-line trend). Real CCD day, read-only: all ten 0.5 mm runs pressure-limited, the other 23
  flow-controlled; not settled: C1, C2 (both runs), C4, C9. Both analyses carry it (`rec["operating"]`); the
  Taguchi per-run table gains gas delivered + regime and a warning. Response surface: Model page "Runs that
  did not get their set gas" = Leave them out (default; `RunPoint.excluded`, not predicted, not drift pairs)
  / Fit them at the gas they got / Keep at set point. Report: "Gas delivered and the operating regime"
  section (per-run table, `fig_rsm_gas_delivered`, `fig_gas_traces`) with the not-delivered runs' own
  table and a main-effects fit among them ("what controlled them"); Best settings lists EVERY goal set,
  used or left out and why (the first CCD analysis silently used atomised alone); "Best runs as measured"
  (goals on observed values, every run counted); headline bullets for both; recommended runs get a
  "Pressure check" when their predicted peak pressure reaches the ceiling. Design page: "Gas delivered"
  column, read in the background. Workbook sheets: Goals used, Best observed runs, Gas delivered,
  Pressure-limited effects. Tests: `test_gas_regimes.py` (11: thresholds, settled, a log read from a
  workbook, a simulated CCD day with a pressure-limited 0.5 mm block in all three modes).

- 2026-10-13 (Mac): **CCD follow-up, phase 2: "no spray" runs.** A run below the Settings tab's new
  "No spray below (atomised %)" (default 2, 0 = off) is a dribble: `stats.load_measured_run` blanks its
  droplet size (D32, mean, median, D90, Dv50) and droplet steadiness (count CV, near-empty %, thin %,
  lag-1) with their CIs and bootstraps, and the droplet parts of its run_metrics (size block, count series,
  spectra, r pressure-vs-droplets; the cache file is untouched). Atomised %, in-focus count, liquid CV,
  atomised liquid flow and peak pressure stay. Size tables, size bins and the deck's spread / Dv50 / span /
  pulsing headlines skip it; per-run tables and `rsm_results.csv` carry a "no spray" note; the report
  names it at the top; provenance records the threshold and the runs. Settings reach both tabs through
  a new `stats.AnalysisOptions` (phase 4's size band will ride on it). Real CCD day, read-only: exactly
  C3 (112022, 0.19%) and C5 (113349, 0.45%) are flagged. Tests: `test_no_spray.py` (5, incl. a full
  response-surface publish with C3's setting as a dribble) + Settings tab.

- 2026-10-13 (Mac): **CCD follow-up, phase 1.** Taguchi app bugs 3 (run list re-read after a batch) and 6
  (GUI_Clean survives a failing Cone_4 import; missing atomised liquid flow is now reported loudly, and
  marked on the Model page) fixed, with tests. Labels: "Atomised fraction **by area**, classical (%)" and
  "Atomised liquid flow **index, area-based** (mL/min)" (keys unchanged, saved goals still work); the
  assumptions and three biases (area is not volume, concentration is not flux, one window) are in
  `docs/definitions.md`. **master_log:** new column "Mean Diameter (um)" at K, between D32 and Atomised (%);
  GUI_Clean writes it from summary.json's `droplet_d_mean_um` on every save (blank when the AI has not run)
  and migrates older logs itself (`migrate_master_mean_diameter`, images move one column right). The LaCie
  master_log was migrated and the 33 CCD rows filled with D32 / mean / atomised % from each run's
  summary.json + classical_summary.json (they match rsm_results.csv to 0.005); backup beside it:
  `Experiments/Logs/master_log BACKUP 2026-10-13 before mean column.xlsx`. 292 images byte-identical,
  each moved one column right; offscreen-tested on an old and a new log. Its two colour scales sit on I
  (Motor Travel) and J (D32); left as they were. The first CCD analysis had goals atomised (3), mean
  diameter (2) and count CV (1) set, but used atomised alone: the other two were dropped as unusable
  surfaces (predicted R² < 0.5) and the Best settings section did not say so (fix in phase 3).
  Tests: full suite 763, 758 passed first time; the 5 failures were 2 expected (deck title now "...by
  area"; the no-GLR fake campaign now also warns that atomised liquid flow is missing) and 3 stale
  real-data expectations written on 10/05, before those runs were measured (now 27 measured; the fake
  run-tree test compares only what the rig writes). All 5 updated and passing.

- 2026-10-13 (home PC): **CCD day batch finished, 33/33 ok**, all sizer 2.2.0 with droplets_0.30 +
  liquid_0.30. Output / job folder: `D:\Experiments\Taguchi\CCD\CCD 4-factor 12-10-2026\` (the LaCie's
  `Experiments/Taguchi/CCD/...` on the Mac). 18:13 -> ~05:05, 7.9-36 min per run (median ~19 min); the
  two longest (115412, 122239, ~36 min) were back to back. Next: Response surface tab Analyse (Ben).
  **First Analyse (09:09-09:14, ~5 min on this PC):** atomised fraction is the only usable surface (R² 0.93,
  predicted 0.62, LOF p 0.032): up with gas, RPM; down with feed, orifice; Orifice² and big RPM x Orifice /
  Feed x Orifice interactions. Size and steadiness surfaces predict poorly (predicted R² < 0, strong LOF);
  mean diameter barely moves (39.3 um, coefficients ~1 um). No curvature except in orifice. Best setting
  11,000 / 900 / 3,000 / 0.5 (all edges) but driven by atomised fraction ALONE (bug 6 removed the flow goal;
  mean diameter and CV dropped as weak). 0 rpm control 19.2% vs centres 17.3 +/- 1.1 and outside its PI
  (pred 12.9). 0.8 mm check inside its PIs except peak pressure (5.2 vs 6.3 predicted).
  **Read-only check of the gas traces: the whole 0.5 mm block was gas-starved.** P0 pinned at 9.2-9.6 barA
  (a supply ceiling?) and the camera-window gas flow was 33-5,554 sccm against set points of 7,000-11,000
  (delivered gas vs feed r = -0.92; more with rpm). Every 0.8/1.2/1.8 mm run got its set point. So the gas
  factor is wrong for 10 runs, which drives the interactions, LOF and the 0.5 mm "best setting". Gas
  expansion energy per kg liquid (GLR_delivered x RT ln(P0/Pa)) correlates with atomised fraction at
  r = 0.83 over all 33 runs (set-point GLR 0.35). Rotation: no effect at 1.2 mm (0/100/500/900 rpm all
  17-19%), +2.6 points at 1.8 mm. Full write-up, section by section of the deck, with the physics:
  `docs/notes/2026-10-13_CCD_day_explained.md`. Next: find the pressure ceiling; fix Taguchi app bug 6;
  re-analyse (a) without the 0.5 mm block and (b) with the delivered gas typed in.

- 2026-10-12 (home PC, read-only on the data): **CCD day ready for the batch.** `D:\Experiments\2026\10\12\`
  holds 33 runs, each one 13.93 GB cine (same size as 10/05: ~508 frames at stride 10) + run_summary.xlsx,
  nothing analysed yet. All Run status "complete", 390 fps, bh 0.5, Notes "CCD run 1..33 <type>" in capture
  order. The app's own loader + `rsm_detect` find a complete CCF, 4 factors: 16 corners, 10 faces, 5 centres
  (31 in the fit), 0 rpm = outside (control), 0.8 mm = off-grid check, orifice the block factor (3 changes,
  confounded with time), 3 drift pairs, full quadratic estimable (15 terms, 6 pure-error df, 10 LOF df), no
  missing / extra points, no Notes conflicts. Achieved flow (max of the recorded range) at 11,000 sccm on the
  0.5 mm block peaked at 11,421-11,782 in 3 of 4 runs (vs ~1-2% over elsewhere); the fit uses the setpoint. Quick self-test READY. Batch time on
  this PC from the 9x3 timings: ~23-28 min/run, so ~13-15 h for 33.

- 2026-10-12 (lab PC): **33-run CCD day captured.** All 33 runs in `E:\Experiments\2026\10\12\`
  (105301 … 151407), settings and order match the seed-1 sheet (`ben_plan()` in
  `tests/test_rsm_design.py`); every run has a full 13.93 GB cine. The two morning runs that lost their
  cine (~10:36, 11:10) were deleted by Ben. Run 33 (0.8 mm check) ran normally at 500 rpm and is a valid
  run: the GUI's stall check false-tripped on it ("STOPPED: ... stalled at 66 RPM"; Ben confirmed no stall),
  and that false label was removed (run_summary Run status "complete", master_log Notes clean; checked
  2026-10-12 on the home PC). Next: batch on Windows, then the Response surface tab.

- 2026-10-12 (lab PC, compiled only, NOT yet on the rig): **GUI_Clean lost auto-trigger capture.** A
  run's auto-trigger fired and logged "saving .cine", then failed ("Error — re-arm manually"); no .cine
  in the run folder and none in PCC. The error text went only to the status bar, which the end-of-run
  auto-save overwrote 14 s later, so the cause is unknown. Suspect: the fixed post-trigger settle used
  the GUI fields' post-trigger count, not the camera's (they differ if fields changed since Apply Config
  or the camera was power-cycled), so the cine could be opened while still recording. Changes: wait for
  `partition_recorded(1)` using the camera's own post-trigger frames / fps (fallback: old fixed settle);
  `save_recording` raises if no file / empty file (the >= 90 %-stall "done" path used to log success with
  nothing on disk); "never started" vs "stalled" save errors; Arm, Disarm / Abort, Apply Config and
  auto-arm on Start refused while a save runs (`_cam_saving`), since each overwrites or clears camera
  RAM; failures go to the console with the failing step, plus a traceback in the LaCie `Logs\serial_*.txt`,
  and say whether the cine is still in camera RAM (save it from PCC before arming). Check on the rig:
  a normal auto-trigger capture still saves, and the post-trigger wait isn't stuck on its +15 s timeout
  (that would mean `partition_recorded(1)` doesn't index partitions from 1).
  Same day, 10:50: an editor tab holding an old copy saved `GUI_Clean.py` back to the 7513f1e version
  (no SCCM ramp, no bubbler at Start, emoji back, camera fix gone). Restored from HEAD and the fix
  re-applied; the clobbered copy is not kept in the repo.

- 2026-10-12 (lab PC, offscreen-tested with fake devices, NOT yet on the rig): **GUI_Clean SCCM ramp and
  bubbler at Start.** "SCCM ramp /s" box under the cut-off (0-12000 sccm/s, empty/0 = off, remembered as
  `gas_ramp_sccm_s`). Set Flow and Start Experiment move the Alicat setpoint from its current value to
  the target at that rate (6000 sccm at 1000 sccm/s = 6 s), a new setpoint every 100 ms while ramping
  (`AlicatMFC.set_flow(sccm, ramp_rate)`; the reader polls at 10 Hz during a ramp, 5 Hz otherwise).
  Gas Flow Off, STOP EVERYTHING and the cut-off still cut to 0 at once and cancel a ramp. The traverse
  still starts 0.5 s after Start, i.e. during the ramp. Start Experiment now also spins the bubbler at
  the RPM box value (blank or 0 = no rotation); it refuses to start if the box has an RPM and the Uno is
  not connected. The ramp rate is not recorded in run_summary.
- 2026-10-12 (lab PC, compiled, NOT yet flashed): **Portenta switch noise filter.** A HOME stopped at
  mid-travel (back switch "found" after 233,673 of ~480,000 steps; back-off cleared in 0 steps, so a
  spike on pin 5, not the beam). Same fault in the serial logs on 2026-10-08 11:17 (28 mm short; the
  11:31 home then ran 23 mm past zero, so runs in between had a wrong zero; per-run travel is relative).
  Every other home since 09-09 triggers at 479,500-480,100 steps moved. Fix: both switches now count
  only after every read agrees for 2 ms (`SWITCH_HOLD_US`, `SwitchFilter`, `switchHeld()`); homing
  (`runUntilSwitch`) and the front stop use it (the front was 3 back-to-back reads, microseconds).
  Home shifts by at most ~20 steps (0.003 mm). Hardware cure if it persists: switch leads away from
  motor cables, or a stiffer pull-up / 100 nF to GND on pin 5. After flashing: home a few times from
  the far end and check "moved" is ~480,000 each time.
- 2026-10-12 (Mac, NOT yet on the rig): **GUI_Clean safety + data fixes, and Portenta firmware.**
  FIRMWARE (`src/gui/Pressure_Motor_Portenta.cpp`, Portenta H7 M7; flashed and tested on the lab rig 2026-10-12: polarity correct, jog / move / homing all stop at the front switch, the 72.5 mm soft limit stops a forward jog before the switch is reached, so the switch is a backstop only): the
  front optical switch (pin 1, previously configured but never read) is now an ABSOLUTE forward stop:
  3 consecutive HIGH reads halt any forward move, jog or homing back-off (`FRONT_LIMIT: pos=` then
  MOVEMENT_COMPLETE / JOG_LIMIT); forward moves/jogs are refused while it reads HIGH; backward always
  allowed. Assumes the back switch's polarity (HIGH = blocked); a disconnected switch reads HIGH and
  blocks forward motion (fail-safe). New `SWITCHES:` command reports both switches (also at boot).
  Soft limit 986000 steps (stale 13600-steps/mm figure = 145 mm) -> MAX_TRAVEL_STEPS = 493000 (72.5 mm).
  GUI: Alicat health (frames stamped on the reader thread; no frame for 2 s or the reader dying ->
  red alarm, cut-off shows NO DATA, STOP EVERYTHING mid-run, Set Flow / Start refused); FRONT_LIMIT,
  traverse STALL_DETECTED, MOVEMENT_TIMEOUT, ERROR:/HOMING_FAILED handled; "Check switches" button
  replaces Clean (removed); jog release always sends STOP and the GUI stops a jog at 72.5 mm; STOP
  EVERYTHING ends the run itself if no MOVEMENT_COMPLETE within 1.5 s; the watchdog now stops the
  traverse and SAVES the run; stopped runs: run_summary "Run status" = "STOPPED: <reason>" (else
  "complete"), master_log Notes prefixed "⚠ STOPPED: ...", travel credited only as far as covered;
  run conditions snapshotted at Start (re-saving Notes keeps them); speed 0 = static run (no move, no
  watchdog, ends with STOP EVERYTHING); close asks while a run / camera save is in progress and sends
  STOP to the traverse; clearing the cut-off box switches it off; Space handled by an app-level filter
  (a focused button can no longer take it); run_summary, master_log and camera_settings.json written
  to a temp file then os.replace; settings never saved part-way through loading; unused imports /
  locals / attrs removed; How To button opens How To (index from count), text rewritten.
  Checked offscreen (fake Portenta/Uno/Alicat, writes redirected to the scratchpad): 17 checks.
- 2026-10-12 (Mac, NOT yet tried on the rig): **GUI_Clean pressure cut-off** box under Gas Flow Off
  (Hardware tab, Mass Flow Control card; 0-30 barA, empty/0 = off; remembered as `pressure_cutoff_bar`). Every
  Alicat frame (~0.2 s) compares the RAW barA reading (absolute, not the smoothed trace) with it; the
  first frame at or above it runs `_pressure_off()` (traverse/silicone feed STOP, bubbler stop, gas
  zeroed), logs, flashes the console red and shows a warning. Latched (fires once), re-arms below 90%
  of the limit; status beside the box reads Off / Armed / TRIPPED. A run stopped this way still
  auto-saves (the Portenta answers STOP with MOVEMENT_COMPLETE); re-home afterwards. For the
  small-orifice / high-flow tests. Checked offscreen with fake devices.
- 2026-10-11 (Mac, NOT yet tried on the rig): **GUI_Clean "Auto-trigger at end of test"** tickbox beside
  Disarm / Abort (Camera tab; remembered in camera_settings.json as `auto_trigger_end`). On Start
  Experiment it arms the camera if needed and fires the trigger at test length - 2 s - post-trigger
  (test length = Motor Travel x 6800 / steps/s, traverse starting 0.5 s after Start), so the saved video
  ends 2 s before the traverse stops (25 s test, 13 s video: fires with 15 s left). A test too short for
  the video asks: trigger early / start without / cancel. Countdown shown under the camera buttons;
  cancelled by Disarm / Abort, Pressure Off, a timed-out run, or the traverse finishing first.
  `auto_trigger_plan()` is the timing (pure function); checked offscreen with a fake camera.
- 2026-10-11 (Mac): **mean diameter is a headline response** (Ben: same level as D32 and atomised
  fraction). Taguchi: main effects, per run, S/N, GLR, interactions, residual checks, drift, report
  summary, deck headline slides. CCD: contour maps, 3D surfaces, all-pairs maps, drift, fit checks,
  model comparison, validation, "What was found" (now two slides when it does not fit on one). And it
  REPLACES D32 as the default size goal (Ben; one size goal, so size is not double-weighted). Folders with
  saved Model choices keep their old goals. Five-response CCD figures use two rows.
  Also: the app opens maximised.
- 2026-10-11 (Mac): batch worker survives a USB drop (bugs 1-2 of the 10-06 batch): see Known bugs.
  New statuses `crashed` and `drive_lost`, both resumable; `worker.RunLog`, `Worker._wait_for_drive`.
- 2026-10-11 (Mac): dark theme made OS-independent. `theme.apply_fusion_style` now sets a full dark
  palette; before, Fusion followed the OS light/dark setting, so on a Mac in light mode the run-folder
  picker (non-native, for multi-select), list widgets and scroll bars were light text on white (Windows
  in dark mode looked fine). Also: the Response surface tab's findings/recommendation lists styled like
  the Taguchi tab's; `restyle_inputs` no longer restyles a spin box's inner editor (it drew a white box).
- 2026-10-08 (lab PC): `launch_app.py` probe fixed. It required an EXACT `sm_XY` match, so the lab's
  RTX 4070 Ti SUPER (sm_89) on torch 2.6.0+cu124 (lists sm_86, sm_90) was wrongly called
  unsupported and the launcher warned no Python could run a batch. Now follows CUDA compatibility
  (same-major cubin with lower-or-equal minor, or PTX at or below); new tests. It also prints
  "checking this Python..." first: the probe imports torch (~5 s warm, much longer on a cold start),
  and the silent wait looked like a hang.
- 2026-10-08 (lab PC): 2.2.0 adopted for good. `measure_run.py`, `classical_liquid.py`,
  `process_capture.py`, `batch_runs.py` default to it (`--no-sharpness-rule` for 2.1.0); every
  caller passes the flag explicitly; new test guards resumed 2.1.0 jobs. 390 fps settled.

- 2026-10-07: 9x3 analysed (see "Where we are"). Replicate outliers: 124030 (T9) high D32, 120201 (T7)
  high count CV. Odd pack: 94 flags (78 atomised_100pct), 33 images.

- 2026-10-07: legacy handoff frozen and archived; this file created. Plugins added (pyright-lsp,
  hookify, claude-md-management, context7, fiftyone; FiftyOne's MCP server not set up yet).
- 2026-10-06: 27/27 replicate runs measured on the home PC at 2.1.0. `selftest.py` Python gate
  lowered to 3.9; `launch_app.py` probes its interpreter and relaunches under a working one.
- 2026-10-05: sizer 2.1.0 (half-max atomised numerator, truncated detections out of classical
  D32, folders renamed, classical extremes mode 41 s vs 183 s, `--limit` guard). GUI: GLR,
  Materials tab, master_log columns looked up by header name, second Trigger button.
- 2026-10-05: Taguchi_Analysis_UI phases 1-10 built (see its plan doc).

## How this file is maintained

- Claude reads this file at the start of any work on this part of the project.
- **Claude updates it before finishing any task that changes the state**: a step done, a result
  obtained, a bug found or fixed, a decision made, a plan changed. Edit the sections in place;
  don't append a diary. Bump "Last updated" with date and machine.
- Long evidence (tables, investigations, timing breakdowns) goes in a dated note under
  `docs/notes/` or in the relevant plan doc, with a one-line pointer here. Keep this file short
  enough to read in one go (aim under ~250 lines).
- Nothing is deleted from history: the legacy handoff stays frozen, and git keeps every version
  of this file.
