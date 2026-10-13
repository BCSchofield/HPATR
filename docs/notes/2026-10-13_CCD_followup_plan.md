# CCD follow-up: count goal, no-spray runs, gas regimes, area vs volume, then re-analyse the CCD day

## Context

Mean in-focus diameter can't tell a spray with 5 droplets at 40 µm from one with 100,000 at
40 µm. Ben wants a count goal to maximise alongside it. Two choices are already made: use a
**fixed size band** that applies to every run (not a window around each run's own mean), and
**look into a production rate**, because a per-frame count measures concentration, not rate.

Facts that shape the plan:
- "In-focus droplets per frame" (`per_frame`) already exists. It is in `taguchi_analysis.RESPONSES`
  and appears as a row in the Model page's goals table.
- On the CCD day (read-only check, 33 runs) the 30–50 µm band count correlates with the total
  in-focus count at r = 0.94 (around each run's mean: 0.92). So on that day the band adds little
  beyond the total, because the size distribution barely moves. It will separate from the total
  where the distribution shifts.
- Caveats to carry with the response:
  - It is a concentration (rate × time in view), so it understates fast, high-gas sprays.
  - The 2.2.0 sharpness rule removes more droplets at high gas.
  - Below 50 µm, sizes are near the pixel lattice and only indicative (`size_bins.CAVEAT`).
  - It overlaps with atomised fraction and atomised liquid flow in the desirability.
- The camera (`IMAGING_PIPELINE_REFERENCE.md` §1.2) runs at 390 fps (2.56 ms between frames), with a
  4 µs exposure and a 20.48 × 11.52 mm field. Item 8 of that doc's next steps is already "measure
  velocity once (PTV)". The phantom env can read cines (`cine_reader` imports OK).

Scope, agreed with Ben on 2026-10-13: everything below, then re-analyse the CCD day to see whether
anything changes. If it doesn't, Ben will describe what he sees in the videos, and the approach will be
reconsidered to match what is really happening. That is a later conversation, not part of this plan.
Calibrated depth of field (the dot-reticle χ method, Blaisot & Yon 2005 §2.6 / §4.2) waits for the
reticle; it is not in this plan.

Phase-gated: follow the Phase order at the end. Each phase stops and reports.

---

## Phase A: "In-focus droplets per frame in the size band" response

**Definition:** the number of in-focus droplets per frame with lo ≤ d < hi. The edges are half-open,
the same convention as `size_bins.spread`. It uses the same population and frame list as `per_frame`
(load_run's `rec["dia"]` / `rec["frames"]`), divided by the analysed frame count. The direction is
larger-is-better. It is **not** added to `DEFAULT_GOALS`; Ben opts in on the Model page.

**Default band: 30–50 µm.** This brackets the CCD day's mean (38–42 µm), and both edges fall
between pixel-lattice diameters (7/8 px and 19/20 px of area). It is an app setting that can be
changed in the Settings tab.

### Changes
1. **`src/ai/Taguchi_Analysis_UI/run_metrics.py`**
   - Add `("band_per_frame", "In-focus droplets per frame in the size band", "larger", False)` to
     `EXTRA_RESPONSES`, and update the "kept to five" comment to six, giving the reason.
   - Add `DEFAULT_BAND_UM = (30.0, 50.0)`.
   - `response_values(m, rec, n_boot, seed, band=None)`: compute the per-frame band counts from
     `rec["dia"]` (not cached, since it is cheap, so changing the band never needs a cache bust).
     The value is `c.sum() / len(frames)`. The bootstrap uses the existing frame-weight matrix `W`
     exactly as `thin_pct` does (`(W @ c) / W.sum(1)`, centred on the point estimate). The value is
     None when there is no `rec`.
2. **`stats.py`**: `load_measured_run(..., band=None)` passes it to `response_values`.
   `stats.analyse(..., band=None)` threads it through. Update the docstrings ("extra six").
3. **`rsm_responses.py`**: `load(..., band=None)` threads it through and records it on `Loaded`
   (`band: tuple`) for the report.
4. **Settings**:
   - `settings_defaults.count_band()` returns a `Default`, following the pattern of `bin_width()` /
     `bin_max()`.
   - `tab_settings.py` gets "Count band from / to (µm)" next to the size-bin fields. Validation: both
     > 0 and lo < hi. It is persisted and reset the same way as `bin_width` / `bin_max`.
5. **Plumbing to both analyses**:
   - `app.py` sets `taguchi_tab.band_provider` and `rsm_tab.band_provider` from the Settings tab,
     following the pattern of the existing `bins_provider` (`app.py:254`).
   - The band reaches `stats.analyse` via `tab_taguchi` → `analysis_controller` → publish, and
     reaches `rsm_responses.load` via `tab_rsm` → `rsm_publish.publish` (`rsm_publish.py:133`).
   - Small side fix in the same place: `rsm_publish.py:179` uses `size_bins.DEFAULT_*`, not the
     Settings bins. Pass the Settings bins through the same provider.
6. **Outputs**:
   - `rsm_report.CSV_NAMES` gets `"band_per_frame": "band_per_frame"`.
   - The Terms / definitions text in the RSM report and the Taguchi report states the band edges
     used and the four caveats in one short paragraph.
   - `provenance.collect` records the band.
   - Deck: no headline change (the response is opt-in).
7. **Docs**:
   - `docs/definitions.md`: the definition and the caveats.
   - `docs/RSM_GUIDE.md`, goals section: when to use it, the overlap with atomised fraction / flow
     (lower its importance if all three are maximised), and that it is a concentration.
   - `docs/IMAGING_PIPELINE_REFERENCE.md` §9: the response list.
   - `docs/STATUS.md`: updated with the change.
8. **Tests** (`tests/test_run_metrics.py`, plus one through `stats`):
   - Band count on a synthetic `rec`: half-open edges (d == hi excluded, d == lo included) and
     frames with no droplets counted in the denominator.
   - The bootstrap is centred on the point estimate.
   - The band reaches the value through `load_measured_run`, and a changed band changes the value.
   - `test_publish` already checks one `###` section per response, so it covers the new row.

### Verification (Phase A)
- `/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m pytest /Users/benschofield/Documents/GitHub/HPATR/src/ai/Taguchi_Analysis_UI/tests -q`
- Launch the app and re-analyse the CCD day into a **new** output folder, so the first analysis is
  not overwritten.
  - Check that `rsm_results.csv` has `band_per_frame` and that it matches the scratch numbers
    (e.g. 130918: 23.64, 115412: 42.33, 112022: 0.71).
  - Check that the Model page lists the row and that Maximise on it enters the desirability.

---

## Phase B: production rate, investigation only (read-only on the LaCie; report, then stop)

**B1. Mass-balance rate estimate (Mac, minutes).** For each CCD run, estimate the in-band droplets
produced per second:

  Ṅ_band ≈ Q_liquid × (atomised % / 100) × (volume share of in-focus droplets in band) / mean(π d³/6 in band)

This is independent of velocity and of time in view. Compare it with the per-frame band count:
- correlation between the two;
- whether the ranking of runs changes;
- whether the gap grows with gas flow, which is the expected velocity effect.

It rests on two assumptions, which will be stated: the area-based atomised fraction stands in for a
volume fraction, and the in-focus size distribution is representative. If it holds up, it is a
candidate response: it needs only data the app already has (`af_flow` × the size distribution).

**B2. Velocity feasibility from the existing cines.**
- At 2.56 ms between frames, a droplet stays pairable between consecutive frames only if it moves
  less than about 5 mm, i.e. v < ~2 m/s.
- Using `cine_reader`, extract ~20 consecutive full-rate frames from three cines (low / centre /
  high gas at 1.2 or 1.8 mm) into the scratchpad.
- Test for a coherent frame-to-frame displacement: background-subtracted cross-correlation
  (PIV-style), plus a nearest-neighbour check on the blobs.
- Separately, bound the velocity from motion-blur elongation along the flow axis (4 µs exposure:
  1 px = 2.5 m/s).
- Outcome: either "the existing cines give velocity, so a flux response is possible" or "a new
  capture is needed (windowed, higher fps)", with the settings that capture would need.

**Deliverable:** `docs/notes/<date>_droplet_rate_investigation.md` with the numbers and figures in
the scratchpad, plus a STATUS update. A rate response is built only after Ben decides (a later
phase).

---

## Further items (C, D and E decided by Ben 2026-10-13)

### C. "No spray" runs must not feed the size and steadiness statistics
C3 (0.5 mm, 11,000 set / 33 sccm delivered, feed 5,000, 100 rpm) is a dribble:
- 1,876 in-focus droplets (3.7 per frame), no static spots, 8 moved by the sharpness rule;
- one continuous liquid piece per frame (median 6.4 mm²);
- atomised fraction 0.19%.

Its droplets are real, so a minimum-count gate doesn't catch it. But its size numbers (mean
26.9 µm, "99% below 50 µm") describe stray specks, not a spray. They bend the fitted surfaces and
lead the deck's headlines. A "minimise mean diameter" goal would also reward the dribble.

Proposed:
- **DECIDED:** classify a run as **"no spray"** when atomised fraction < 2% (a setting). On the CCD day that
  catches C3 (0.19) and C5 (0.45); the next lowest is 5.96.
- For "no spray" runs, the size and droplet-steadiness responses are set to missing, with the
  reason recorded:
  - size: D32, mean, median, D90, Dv50, size spread;
  - droplet steadiness: count CV, thin %, lag-1, near-empty %.
- These responses keep their values for "no spray" runs: atomised fraction, in-focus count, band
  count, atomised liquid flow, liquid CV and peak pressure. There, a value near zero is a true
  result.
- The deck and report label the run "no spray: size not reported", and the appendix headlines skip
  it.

### D. Gas set point vs gas delivered: two operating regimes

**What the traces show** (read-only, 10 s bins of `run_summary.xlsx` → `Pressure`, all ten
0.5 mm runs):
- Every 0.5 mm run passed its full set flow at 6–8 barA *until the silicone arrived*. The pressure
  then jumped to the ~9.2–9.5 barA ceiling, and the gas fell to whatever the orifice could pass.
  - C1 (the first run of the day, line priming) ran at 11,000 sccm and ~7 bar for 50 s, then fell
    to 967–2,914 sccm.
  - Liquid arrival is the switch: two-phase choking needs far more pressure than gas alone.
- After that the run is **pressure-limited**. Gas is no longer an input: it is the atomiser's
  two-phase capacity at the ceiling, set by feed and rpm (and orifice).
- At feed 3,000 the pressure-limited operation is **steady and reproducible**:
  - C7 / C8 (set 7,000 / 11,000): 5,370 / 5,554 sccm delivered, 35.2 / 34.3% atomised;
  - C4 / C6: 3,832 / 3,912 sccm, 17.0 / 14.4%.
  So a pressure-limited setting can be a legitimate, good recipe, and its gas set point doesn't
  matter.
- At feed 4,000–5,000 it is at a **cliff edge**:
  - C1 vs C9 (same feed and rpm) give 2,170 vs 716 sccm and 20.1 vs 8.8%;
  - C1 is still changing inside the camera window (967 → 2,914);
  - C2 repeat is falling (2,231 → 1,347);
  - at 100 rpm the gas collapses entirely (C3, C5: 30–55 sccm, a dribble).
- All 0.8 / 1.2 / 1.8 mm runs are **flow-controlled**: they hold their set point at a pressure
  below the ceiling.

**Proposed handling:**
1. **Per-run operating point (analysis):** for each run, report the following from the camera
   window:
   - delivered gas (median, p10, p90) and P0 (median);
   - the **regime**: flow-controlled if delivered ≥ 95% of the set point; pressure-limited if P0 is
     within 0.3 bar of the ceiling and delivered is < 95%;
   - a **settled** flag: the camera-window median within ±10% of the preceding 10 s, and no trend.

   These are shown on the Design page and in the report, plus two new figures:
   - delivered vs set gas, coloured by orifice;
   - per-run P0 / gas traces with the camera window shaded.
2. **Fit (DECIDED):** pressure-limited runs are left out of the response-surface fit by default (shown, not
   hidden), because the design's gas factor doesn't describe them.
   - They get their own section, "Pressure-limited runs": inputs are feed, rpm, orifice and P0;
     outputs are delivered gas, atomised %, count, etc. The 0.5 mm block is a duplicated 2³ (set gas
     × rpm × feed), so "set gas has no effect once limited" is testable.
   - A Model-page option keeps them in with the delivered gas as their factor value, for
     comparison. Caveat: low gas then exists only at 0.5 mm, so gas and orifice are aliased.
3. ~~Physics model across both regimes (expansion energy)~~: not now (Ben, 2026-10-13).
4. **Best settings (DECIDED: include the best observed runs list):**
   - The model optimum and next runs stay inside the flow-controlled region, with a warning if any
     recommendation's predicted P0 exceeds the ceiling (a setting, default 9.3 barA).
   - Separately, the report lists the **best observed runs** with their regime, so a reproducible
     pressure-limited recipe (C7 / C8) is visible as a candidate.
5. **GUI_Clean (rig) (DECIDED: regime indicator + logging; NOT the auto-trigger wait):**
   - A live regime indicator, with a warning when the gas stays > 5% short for > 3 s.
   - `run_summary` records the camera-window delivered gas, P0, the regime and the settled flag.
   - ~~The auto-trigger waits until P0 and gas have settled~~: not now. The analysis-side settled
     flag covers it.
6. **Rig / procedure (no code):**
   - Before designing around a small orifice, do a quick capacity test: at the ceiling, step the
     feed (and rpm) and log the delivered gas, about 10 min per insert. That maps the feasible
     region.
   - For inserts that are always pressure-limited, the regulator pressure, not the gas set point,
     is the factor to vary (up to the rig limit).

### E. Other fixes (decided 2026-10-13)
1. **Bug 6:** at `GUI_Clean.py:74`, change `except ImportError` to `except Exception` (the cone
   detector is optional). The analysis also warns loudly, in the console, the report and the Model
   page, when atomised liquid flow can't be computed, instead of silently dropping that goal.
2. **Bug 3:** reload the run list (`pane_runs._reload_runs()`) when a batch finishes, with a test.
3. ~~GUI_Clean false stall trip~~: not a bug. The bubbler motor was unplugged; Ben has already
   fixed it. Run 33 was spinning at 500 rpm during the capture (Ben), so it stays a valid check run.
4. **Orifice on a log scale.** A Model-page option, per factor, to fit on ln(factor); the default is
   on for orifice. The evidence (read-only, CCD day):
   - The inserts 0.8 / 1.2 / 1.8 mm are a geometric series (ratio 1.5). On ln d they are exactly
     equally spaced, so a 0.8 / 1.2 / 1.8 design is a true face-centred design on ln d, but not on d.
   - With the pressure-limited 0.5 mm runs out of the fit, orifice has only two levels (1.2, 1.8),
     and the 0.8 mm check becomes an extrapolation. The predicted peak pressure at 0.8 mm (observed
     5.2 barA) under each scale: d 4.52, **ln d 5.06**, 1/d 5.87, 1/d² 7.08. Atomised % (observed
     20.2): d 21.9, ln d 23.9, 1/d 26.9, 1/d² 31.4. So 1/area is the worst on both, and ln d is the
     best compromise.
   - Coding: coded = (ln x − ln centre) / (ln hi − ln centre) for a geometric design; generally the
     same (lo, hi) → (−1, +1) mapping applied to ln x. Decoding is the inverse, so maps, the
     optimum and the next runs stay in mm. Rows outside the fitted range are flagged as
     extrapolated, as they are now.
   - Touches: `rsm_responses._x` / factor coding (`RsmResults.decode`), `rsm_stats` coding,
     `rsm_figures` axes (show mm ticks on a log axis), `rsm_recommend` (decode), and the Model page
     roles table (a "log" tick per factor, saved in the model json). Tests: round-trip
     coding / decoding, and a fit on synthetic data generated from ln d recovers its
     coefficients.
5. ~~Expansion energy covariate~~: not now (Ben, 2026-10-13).
6. **Design advice (no code):**
   - Pure error comes from back-to-back centres in one block; put centre repeats on another day.
   - The next design should use 0.8 / 1.2 / 1.8 mm, with a capacity check that 0.8 mm stays
     flow-controlled at the worst corner (11,000 sccm, feed 5,000).

### F. Atomised fraction: area vs volume (decided 2026-10-13)
**Why:** atomised fraction = Σ droplet px / Σ liquid px. It is a *projected-area* ratio, and
"atomised liquid flow" = syringe mL/min × that ratio. That treats pixels as volume:
- a sphere carries 2d/3 of depth per pixel (about 27 µm for a 40 µm droplet);
- a ligament or stream of thickness D carries πD/4 (about 390 µm for 0.5 mm).

So the area ratio overstates the atomised volume share, and by a different amount in each run (thicker
un-atomised pieces at low gas), which can change the ranking of runs. Blaisot & Yon (2005, *Exp. Fluids*
39:977) §3.4 rebuild volume from a 2D image by slicing perpendicular to the principal axis, with each
slice a disc (Daves et al. 1993). We generalise that to curved ligaments by slicing along the skeleton.
The same paper (§4.5) compares image and PDPA distributions only after checking that size and velocity
are uncorrelated: the concentration vs flux point, which is Phase B's job.

1. **Relabel (code + docs, small).** Labels only; keys stay, so saved goals still work.
   - `af_flow` becomes "Atomised liquid flow index, area-based (mL/min)".
   - `atom` becomes "Atomised fraction by area, classical (%)" (`AI/Real_Data_Code/taguchi_analysis.py`
     RESPONSES).
   - `docs/definitions.md`, `docs/RSM_GUIDE.md`, `docs/IMAGING_PIPELINE_REFERENCE.md` §9: what each is,
     the assumption (area share = mass share of the whole flow, at this station), and the three biases
     (area ≠ volume, concentration ≠ flux, one window at one distance).
2. **Read-only check: does the ranking change?** (Mac; scratchpad only; nothing written to the LaCie)
   - **Inputs (confirmed present on every run):** `shadowgraph/raw/frames/16bit/*.tiff`,
     `raw/instances.json`, `analysis/predictions.json`, `raw/background_median.tiff`; `pycocotools`
     imports in the phantom env.
   - A scratch script imports `classical_liquid.measure_frame` / `model_masks` / `hysteresis` with the
     run's own provenance settings (seed, ceiling, focus_max, sharpness rule 2.2.0, thr 0.30, as in
     `liquid_0.30/classical_summary.json`) and rebuilds, per frame, the total-liquid mask and the droplet
     mask. **Gate:** the rebuilt per-frame `droplet_px` / `total_liquid_px` must match
     `classical_per_frame.csv` exactly (or the check stops and says why).
   - **Volumes:**
     - droplets: each droplet's own sphere volume π d³/6 from its measured diameter. Cross-check:
       Daves slicing of its mask gives the same within a few %.
     - un-atomised pieces (total minus droplet mask, connected components): skeleton slicing. Each
       pixel's chord through an assumed round cross-section is 2√(R² − (R − e)²), with e = the pixel's
       distance to the edge (distance transform) and R = the local radius at its nearest skeleton point.
       Also the Daves principal-axis version on compact pieces, as a cross-check. Out-of-focus model-only
       pieces are counted by the same rule, and flagged as the least certain part.
   - **Sample:** all 33 runs, 30 frames each, evenly spread through the capture (same stride for every
     run).
   - **Report:**
     - per run: the area fraction (reproduces `af` within sampling), the volume fraction, and their
       ratio;
     - **Spearman rank correlation** across runs, area vs volume;
     - which runs move most in rank, and whether the ratio tracks gas / feed / orifice;
     - the best-5 lists side by side;
     - the factor picture on the flow-controlled runs (signs and rough sizes of the effects) under
       both measures;
     - sensitivity: the round-cross-section assumption bounds the answer, so also report it with
       ribbon-like pieces (thickness = ½ the width).
   - Deliverable: `docs/notes/<date>_area_vs_volume_atomised_fraction.md` + figures (scratchpad,
     copied into `docs/notes/figures/` if useful), STATUS update. **Stop and report.**
3. **If the ranking or the factor picture changes** (Ben decides at the stop):
   - add a volume-based atomised fraction to the pipeline: `classical_liquid` writes per-frame
     `droplet_vol` / `total_liquid_vol` alongside the pixel columns;
   - the app gains "Atomised fraction by volume (%)" and "Atomised liquid flow, volume-based (mL/min)";
   - the area versions stay for comparison.
   - This needs the liquid stage re-run on Windows for the 33 runs, using the existing predictions
     (no model re-inference). The time per run is measured during the check and given at the stop.
   - If the ranking does *not* change: keep area-based, relabelled, and note the volume/area ratio as
     a known scale bias.

### G. Analyse on GLR and measured pressure instead of sccm and steps/s (Ben, 2026-10-13: NOT YET)
Ben asked for this to be planned but not done, with Claude's opinion at the end of the plan, and
possibly as a separate part. To be written up after phase 9 (the CCD re-analysis), when there is
evidence to judge it against:
- what it would mean: fit the surfaces on (GLR_delivered, P0_measured, rpm, orifice) per run,
  in place of the set points (gas sccm, feed steps/s);
- what the CCD data says about it (the 0.5 mm block is where set points and reality part ways);
- the costs: measured variables are not set independently (P0 depends on gas, feed and
  orifice), so the design is no longer orthogonal and the predictors are correlated; the
  recommender would have to translate a recommended (GLR, P0) back into settings the rig can set;
- an opinion: replace, add as a second "physics" model alongside the set-point model, or leave.

### H. Droplets on the window / lens counted as liquid (Ben, 2026-10-13: do after)
**Seen on C20 (142150, 1.8 mm, 7,000 sccm, 100 rpm, feed 3,000; atomised 5.96%, the lowest off
the 0.5 mm block):**
- `raw/background_median.tiff` holds a large dark blob at the lower middle: a droplet on the
  window or lens. Being in the median, it normally divides out.
- In the lowest-atomised frame (0172, 1.35%), the classical segmentation colours almost exactly
  that blob as un-atomised liquid. In frame 0443 (100%) it isn't counted.
- So it leaks in whenever it differs from the median (it moved, grew or dripped, or a droplet
  landed mid-run). That hurts most in sparse runs, where it can outweigh the real liquid in a frame.
- A truly static object present all run divides out. Anything that changes during the run does not.

**Plan:**
1. **Read-only impact check (all 33 CCD runs).**
   - Find "window" liquid: components that sit on the same pixels in many frames. Use a
     per-pixel persistence map of the classical liquid mask; a pixel is window if it is liquid in
     ≥ X% of frames (sweep X, e.g. 10 / 20 / 40%), and/or dark in the background median.
   - Recompute the atomised fraction with those pixels excluded from numerator and denominator.
   - Report per run: the masked area, Δ atomised fraction, and whether the ranking changes.
   - Contact sheet of the worst runs (C20 first).
   - This can share the mask rebuild with F2, so do the two together.
2. **Fix, if it matters (Ben decides):**
   - (a) A persistence mask in `classical_liquid` (and the droplet sizing): exclude window pixels
     from both measures, and record the masked area per run.
   - (b) Or a rolling background (temporal median over a sliding window, e.g. ±20 analysed
     frames) so slowly changing window droplets are tracked. Costs extraction time.
   - Either needs the liquid stage re-run on Windows from the existing predictions, the same as F3.
     F3 and H2 together would be one re-run.
3. **Rig / GUI:**
   - A pre-run window check in GUI_Clean: compare the pre-trigger frame or a quick grab with a
     clean reference background and warn if new dark blobs are present.
   - Note on the run sheet: wipe or dry the window between runs.
- Existing related code: `run_metrics` already flags static droplet detections (6 px grid, ≥ 20%
  of frames) and dark specks in the background, but nothing does this for liquid components.

### I. More extreme frames (Ben, 2026-10-13: do after)
Add to the extreme-frame images (currently lowest/highest D32 and atomised %):
- the frame with the **most in-focus droplets**;
- the frame with the **most droplets in total**;
- the frames with the **highest and lowest mean diameter**.

**For the CCD runs, without re-running the AI:**
- Every run still has its 16-bit frames (`raw/frames/16bit/`), `predictions.json`,
  `droplet_sizes.csv` / `per_frame.csv` and the classical outputs.
- Choose the frames from the per-frame tables, then render the marked-up images with the
  pipeline's own drawing code (`measure_run` circles, `classical_liquid` orange) from the saved
  frames and predictions. No inference.
- Write them to a new folder per run, `shadowgraph/analysis/droplets_0.30/extreme_frames_more/`,
  plus an index CSV (frame, reason, value). Nothing existing is overwritten. Mean-diameter extremes
  are only taken from frames with at least N in-focus droplets (e.g. 10), so a frame with one
  speck isn't "the smallest mean".
- **Going forward:** `measure_run` produces the same set in every batch, and the app's galleries
  and the GUI's Extremes tab show them.

---

## Phase order (decided)
1. Bugs 6 and 3 (E1, E2) + the relabel (F1).
2. "No spray" (C).
3. Regimes, analysis side (D1, D2, D4).
4. Band-count response (Phase A).
5. GUI_Clean regime indicator and logging (D5). Needs a rig check.
6. Orifice on a log scale (E4).
7. Area vs volume check (F2). Read-only; report, then stop. **F2 and H1 (the window check) DONE early,
   2026-10-13, by a sub-agent alongside phases 2-3: `docs/notes/2026-10-13_area_vs_volume_and_window.md`.**
   **Decided (Ben, 2026-10-13): F3 + H2 together.** In `classical_liquid` (version bump): (a) drop model
   out-of-focus non-droplet pieces whose mean T is >= 0.97 (nothing left after background division); (b) mask
   window objects that are persistent (liquid in >= 20% of frames) AND still (same pixels frame to frame; a
   real jet wobbles); (c) per-frame volume columns, giving a SECONDARY response "Atomised fraction by volume
   (est.)" and its flow index, never a default goal, area stays the headline. Re-run the liquid stage for
   the 33 CCD runs HERE ON THE MAC (CPU only; ~45 min, LaCie-read bound), archiving each run's current
   `liquid_0.30/` first, restartable per run. Windows picks the code up with the final commit. If Ben says so, F3 (pipeline +
   Windows re-run of the liquid stage) comes next.
8. Rate investigation (Phase B). Read-only; report, then stop. B1 uses the volume fraction if F3
   was done.
9. Re-analyse the CCD day into a new output folder with all of the above. Compare with the first
   analysis (`Taguchi/CCD/CCD 4-factor 12-10-2026/`):
   - which surfaces became usable;
   - the best setting and the next runs;
   - the 0 rpm control and the 0.8 mm check;
   - what the pressure-limited section says about the 0.5 mm block.
   Write `docs/notes/<date>_CCD_reanalysis.md`.
10. More extreme frames (I): render them for the CCD runs from saved data, then add them to
    `measure_run` for future batches.
11. Window / lens droplets (H): the read-only impact check, then a fix if Ben wants one.
    Recommendation (to raise at phase 7): do the H1 check together with F2, because both rebuild the
    same liquid masks. If either needs a Windows re-run of the liquid stage, do it once, before the
    phase-9 re-analysis.
12. GLR and measured pressure as the analysis variables (G): opinion and plan only, at the end.

Each phase: tests pass, update STATUS.md, report to Ben and stop.
