# STATUS — real-data droplet pipeline and Taguchi study

**Last updated: 2026-10-11 (Mac: CCD plan complete, Phase 7 committed 2ebc9f0; next is the 33-run CCD day).** This is the live state of the work. Claude keeps it current
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

- **Phase 1 done (2026-10-11), uncommitted:** `run_metrics.py`, the shared per-run data layer (size
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
- **Phase 2 done (2026-10-11), uncommitted, awaiting Ben's review:** richer Taguchi outputs + deck.
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
- **Phase 3a done (2026-10-11), uncommitted, awaiting review:** `rsm_detect.py` detects the
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
- **Phase 3b done (2026-10-11), uncommitted, awaiting review:** `rsm_design.py`, the generic CCF
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
- **Phase 4 done (2026-10-11), uncommitted, awaiting review:** the response-surface statistics.
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
- **Phase 4b done (2026-10-11), uncommitted, awaiting review:** the 9x3 as a gas x feed surface, run the way
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
- **Phase 5 done (2026-10-11), uncommitted, awaiting review:** the response-surface outputs generalised to
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
- **Phase 6 done (2026-10-11), uncommitted, awaiting review:** `rsm_recommend.py`, the next-run recommender.
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
  **Rig limits (Ben, 2026-10-11): gas 12,000 sccm, bubbler 1,000 rpm (0 allowed: the control), feed about
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
    afterwards in the app). NOT DONE (auto-mode safety check blocked the edit): "Use standard settings"
    still re-ticks the AI box (`self._pipeline_check.setChecked(True)`, ~line 7006 of
    src/gui/GUI_Clean.py): delete that line by hand or in a non-auto session.
  - Settings tab unchanged: no pressure limit to set (there is none), desirability goals live on the
    Model page, bin settings were already there.
  - `docs/IMAGING_PIPELINE_REFERENCE.md` §9 updated (extra responses, figures, deck) and §9b added
    (response-surface stage).

## Next steps, in order

0. **The 33-run 4-factor CCD day** (gas 7000/9000/11000, RPM 100/500/900, feed 3000/4000/5000,
   orifice 0.5/1.2/1.8; orifice blocks, 5 centres, block repeats, 0 rpm control, 0.8 mm check).
   Before it: Ben practises the Response surface tab on the 9x3 copy (`docs/RSM_GUIDE.md`, "Using
   the app"); delete `self._pipeline_check.setChecked(True)` (~line 7006, GUI_Clean.py, "Use standard
   settings"); pull `Testing` + install python-pptx on the lab PC (item 5); fix app bugs 1-2 (item 3)
   since the day's batch runs overnight; build + export the run sheet in the app, type each run's
   "CCD run N <point type>" in Notes. After it: batch on Windows, then the Response surface tab.
1. **RPM confirmation test** (Ben, lower urgency now): one gas/silicone setting, RPM alternated
   300/900/300/900... in one session (4-6 runs). Randomise run order in every future campaign.
2. ~~Ben to decide the default~~ **DECIDED 2026-10-08: 2.2.0, for good** (may revisit). What
   still follows from the diagnosis: every 2.2.0 D32 gas effect is ~2/3 selection, so it must be
   reported as "D32 of the round, sharp droplets" with that caveat. Still worth considering: the
   moved share ("non-round or blurred fraction") as its own response, since it rises cleanly with
   gas. The first L9 (10/01) is still 2.0.0; re-measuring it at 2.2.0 is ~41 s/run with `--reuse`
   if it is ever to be compared (not done).
3. **Fix the app bugs below before the next overnight batch** (1 and 2 at least).
4. **Fold in the Windows timings**: `9x3 Taguchi Repeats/_job/eta_calibration.json` +
   `_job/timings.csv` -> replace `eta.PRIORS_BY_OS["Windows"]` in `eta.py` with measured
   lo/typ/hi per stage. ~10 min, any time.
5. **Install `python-pptx` on both Windows machines** (the Taguchi app's PowerPoint deck needs it;
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
  72.5 mm); the GUI's 72.5 mm limit is what currently protects the syringe. Not yet fixed/reflashed.
- **Measurement method (longer term):** `docs/DROPLET_MEASUREMENT_METHOD.md` (2026-10-07) is the
  plan to make sizes defensible: dot-reticle + glass-bead calibration of edge, focus and depth of
  field, size-dependent DOF weighting, shape classification instead of rejection, volume-based
  sizing, Dv50 beside D32. Not started; includes what to buy and how to run the calibration.

- **RPM vs time of day** (see "Where we are"). Also worth knowing: whether the EcoFlex 00-30 was
  mixed (curing, so viscosity rises through its pot life) or a single part, and lab temperature.

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
- **Decorrelation time (~20 ms) is inferred, not measured**, and the stride default rests on it.
  Measurable from any stride-1 capture (adjacent-frame cross-correlation).
- **Old L9 (10/01) is sizer 2.0.0** and not directly comparable to the 27 runs on atomised
  fraction. Re-measuring it is ~41 s/run if ever needed.

## Known bugs, not fixed

Taguchi_Analysis_UI (found in the 2026-10-06 batch):
1. One failed log write (`worker.py:229`, `OSError: [Errno 22]` on a USB drop) kills the worker.
   It should survive, wait for the drive, retry the run once.
2. A worker crash writes `job_end status: halted`, which `batch_controller.py:243` reports as a
   contract violation with no Resume. Workaround: Run batch with "Use their existing results".
3. The SELECTED RUNS summary ("N already measured") does not update while a batch runs.
4. After a crash the "already have results" dropdown showed "Re-measure only"; check the default
   (run sheet says "Use their existing results").
5. 17 Windows-only test failures, all test-side (path separators, `os.getpgid`, symlinks needing
   admin, `?` in a fake run name, one GLR test). Self-test says READY regardless.

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
