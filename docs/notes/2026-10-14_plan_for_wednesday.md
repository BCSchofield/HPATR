# Wednesday (code and understanding) → Thursday (rig)

Written 2026-10-13, late, from everything done that day (commit `0809dea`). Wednesday is code and thinking
only; Thursday is the rig.

## Where we are, in five lines

1. **The objective is throughput.** The spray is collected and size-filtered, so the target is **in-band droplets
   produced per second, 20–60 µm** (mass balance; the "Droplets/s (20-60 um)" master_log column).
2. **Flow-controlled region (1.2–1.8 mm).** More gas and more feed give more in-band droplets per second, and a
   smaller orifice helps.
   - Model best: **11,000 sccm / 100 rpm / feed 5,000 / 1.2 mm**, about 288k/s. It sits at the edge of every
     factor, so the optimum is beyond the tested range.
   - Steepest ascent: 12,000 / 0–50 rpm / feed 5,300, about 336k/s (extrapolated).
3. **The best run measured is C7** (0.5 mm, pressure-limited, 900 rpm, feed 3,000): 280k/s. Its twin C8 gave
   187k/s, so the 0.5 mm ceiling recipe is competitive but noisy.
4. **The rate's weak spot is the volume estimate.** C7 and C8 read 12.9% and 7.9% atomised by volume, against 35%
   and 34% by area. Absolute rates are good to roughly ±30–40%.
5. **Physics.** Gas mass flux at the orifice and the silicone film thickness at the exit explain atomisation
   across both regimes (Spearman +0.91 / −0.90). The lamella AI's film (about 0.38 mm per wall) agrees with the
   model's estimate (0.31–0.35 mm) to within about 20%.

## Thursday's plan (agreed with Ben 2026-10-14: Cd tests, more 0.5 mm, 15-20 runs, feed max 8,000, 0.8 mm at 12,000 OK)

**REVISED later on 2026-10-14 (Ben):**
- Spray runs cut to 10: #01 anchor, #02 and #06 confirm, #03-#05 the 12,000 ladder at 6,000 / 8,000 / 5,000,
  #07 0.8 mm, and #08-#10 at 0.5 mm (C7, feed 4,000, feed 2,000).
- Each insert's Cd test sits just before its spray runs.
- The bead calibration (43 sandwich captures + 10 falling pours) comes at the END of the day.
- The live sheet is `docs/notes/2026-10-15_thursday_run_sheet.csv`; the table below is the original
  16-run version.

16 spray runs and 3 gas-only Cd runs (1.2, 0.8, 0.5 mm). Line loss is ignored (Ben, 2026-10-14). Blocks go 1.2 → 0.8 → 0.5 mm, so the pressure rises through the day;
the order within each block is randomised (seed 20261015). Wipe the window and run the window check before
every spray run. **Notes:** `S2 #NN <purpose>`. Do NOT write "run N": the analysis reads "run N" as a CCD-day
run number. "S2" = session 2; item 19 teaches the analysis to treat it as an added session.

**Travel:** 36 mm as on the CCD day, except the fast feeds, so every run lasts at least ~49 s like the feed-5,000
runs. At 36 mm a feed-8,000 run lasts only 31 s, leaving the camera window close to the silicone's arrival.
6,000 → 43 mm, 7,000 → 50 mm, 8,000 → 58 mm (one syringe fill per run; 72.5 mm is the limit).

| # | Insert | Gas (sccm) | RPM | Feed (steps/s) | Travel (mm) | Notes | Why |
|---|---|---|---|---|---|---|---|
| – | – | – | – | – | – | PCC: max fps at 256×1152, 512×1152, 2048×256; clean-window reference | velocity plan step 1 (no spray) |
| – | 1.2 | ladder 2–12k | – | 0 | – | `CD TEST 1.2 mm L <L> mm, room <T> C` | Cd (subsonic) |
| 1 | 1.2 | 9,000 | 500 | 4,000 | 36 | `S2 #01 anchor centre` | day-to-day check against the CCD day's 5 centres |
| 2 | 1.2 | 11,000 | 100 | 5,000 | 36 | `S2 #02 confirm` | the model's best: predicted 288k/s (PI 249–326k) |
| 3 | 1.2 | 12,000 | 100 | 6,000 | 43 | `S2 #03 ladder` | gas to the rig's limit, feed up |
| 4 | 1.2 | 12,000 | 100 | 8,000 | 58 | `S2 #04 ladder` | top of the feed ladder |
| 5 | 1.2 | 12,000 | 100 | 5,000 | 36 | `S2 #05 ladder` | gas alone up from the best setting |
| 6 | 1.2 | 12,000 | 100 | 7,000 | 50 | `S2 #06 ladder` | |
| 7 | 1.2 | 11,000 | 100 | 5,000 | 36 | `S2 #07 confirm` | |
| 8 | 1.2 | 11,000 | 100 | 5,000 | 36 | `S2 #08 confirm` | |
| 9 | 1.2 | 9,000 | 500 | 4,000 | 36 | `S2 #09 anchor centre` | second anchor, end of the block |
| – | 0.8 | ladder 2–12k | – | 0 | – | `CD TEST 0.8 mm L <L> mm, room <T> C` | Cd (choked from ~10k) |
| 10 | 0.8 | 12,000 | 100 | 5,000 | 36 | `S2 #10 0.8 capacity` | 0.8 mm at full gas; stop if P0 reaches 9.3 barA |
| 11 | 0.8 | 12,000 | 900 | 5,000 | 36 | `S2 #11 0.8 capacity` | does rpm help at 0.8 as it does at 0.5? |
| – | 0.5 | ladder 2–12k | – | 0 | – | `CD TEST 0.5 mm L <L> mm, room <T> C` | Cd (choked from ~4k) |
| 12 | 0.5 | 7,000 | 500 | 3,000 | 36 | `S2 #12 0.5 rpm` | rpm at the best feed (500 was only run at feed 4,000) |
| 13 | 0.5 | 7,000 | 900 | 3,000 | 36 | `S2 #13 C7 repeat` | C7 gave 280k/s, C8 187k/s: which is typical? |
| 14 | 0.5 | 7,000 | 900 | 4,000 | 36 | `S2 #14 0.5 feed` | between the best feed (3,000) and the poor one (5,000) |
| 15 | 0.5 | 7,000 | 900 | 3,000 | 36 | `S2 #15 C7 repeat` | |
| 16 | 0.5 | 7,000 | 900 | 2,000 | 36 | `S2 #16 0.5 feed` | less feed, more gas gets through: does throughput hold? |
| – | 0.5 | 7,000 | 900 | 3,000 | 36 | `S2 exposure series` (1 / 4 / 16 / 40 µs, ~2 s each) | velocity plan step 1; LAST, so the 4 µs exposure cannot be left changed for a real run |

**Why 0.5 mm looks like this.** At 0.5 mm every CCD run was pressure-limited, and the gas SET POINT made no
difference: at the same feed and rpm, 7,000 vs 11,000 set gave 3,832 vs 3,912 sccm delivered, and 5,370 vs
5,554. So all 0.5 runs use 7,000. The levers are rpm (100 → 900 at feed 3,000: about 3,900 → 5,450 sccm delivered
and 19% → 35% atomised) and feed (at 900 rpm: feed 3,000 gives about 5,450 sccm and 35% atomised; feed 5,000
gives 716–2,170 sccm, and at 100 rpm feed 5,000 is a dribble). Nothing yet tests feed 2,000 or 4,000 at 900 rpm,
or 500 rpm at feed 3,000.

**Totals:** about 220 mL of silicone (12.8 mL per 36 mm; 15–21 mL for the fast feeds), about 11–12 syringe fills.
About 4 h: 16 runs at ~8 min, 3 Cd runs at ~10 min, insert changes, the PCC check and the exposure series.
If time runs short, drop #11 and #16 first.

## Wednesday: code and understanding, in priority order

**Must (Thursday depends on them)**

1. ~~**Make throughput the default.**~~ **DONE 2026-10-14**: Settings band 20–60 µm; default goals in-band rate ×3
   and atomised fraction ×1 (`run_metrics.DEFAULT_BAND_UM`, `rsm_responses.DEFAULT_GOALS`). A saved `rsm_model.json`
   keeps its own goals.
2. ~~**Same-day numbers on the rig.**~~ **Dropped 2026-10-14:** the lab PC cannot run the AI; the batch runs
   overnight on the home PC. So nothing on Thursday is steered live: the feed push is a fixed ladder
   (6,000 / 7,000 / 8,000), read the next morning.
   - Making inference much faster is possible later. In the CCD batch, inference was 873 s of a 1,142 s run
     (median), on the RTX 5060 Ti at stride 10 (508 frames).
   - The model itself took 501 of the 804 s (about 0.8 s per frame for about 10 tiles, one at a time). The
     other 300 s was spent around the model.
   - Frame extraction took 2.5 min, writing a 16-bit TIFF and an 8-bit PNG per frame to the LaCie.
   - Leads: batch the tiles, half precision, find the 300 s overhead, and a quick-look stride (e.g. 50).
     Not now; see item 26.
3. ~~**Thursday's run sheet.**~~ **DONE 2026-10-14:** `docs/notes/2026-10-15_thursday_run_sheet.csv`. Check whether the app's *Build a run sheet* can take a custom list (numbered Notes,
   randomised within blocks, printable). If not, add a "custom runs" mode (about 1 h); otherwise build it by hand
   from the table above.
4. **Exposure-series analysis script** (`exposure_series.py`, from the B2 code in
   `docs/notes/2026-10-13_droplet_rate_investigation/b2/scripts/`), so Thursday's four captures are analysed that
   afternoon. About 1 h.
5. **Pressure as a hard limit on the Model page** (peak ≤ 9 barA). The analysis code supports it, but the page
   doesn't pass it on. It's needed once 0.8 mm at 12,000 sccm is in a fit. About 1 h.

**Should (better, more trustworthy data)**

6. **The C7 / C8 volume gap.** Compare their per-frame volumes and un-atomised pieces, using contact sheets of
   the frames with the largest liquid volume. The aim is a more robust pooled volume fraction (e.g. trimmed, or
   per-frame medians), because the main response rests on it. 1–2 h.
7. ~~**Settling time against feed.**~~ **SKIPPED 2026-10-14 (Ben):** the spray is not steady enough to say when it settles; maybe later. From the CCD pressure logs, find when the silicone arrives and P0 settles for
   each orifice and feed, then set Motor Travel and the auto-trigger timing for the high-feed runs. The camera
   window must sit in steady running. About 30 min.
8. **Is the 20% plateau real or optical?**
   - At high droplet density, droplets hide behind each other and liquid pieces overlap, which could cap an
     area-based fraction.
   - Check the per-frame atomised fraction against droplet count in the 1.2 mm high-gas runs.
9. **Low rpm at 1.2 mm.** Look at 100 vs 500 vs 900 rpm at 1.2 mm per frame (count CV, lag-1, pulsing): is
   there a mechanism, or is it one run each?
10. **In-band yield response:** the share of the silicone fed that ends up as 20–60 µm droplets. A
    material-efficiency check next to throughput. About 20 min.

**Nice (easier to use)**

11. A **"Re-publish with saved settings"** button or command, generalising `reanalyse_ccd.py`, so a re-analysis
    after a code change is one click.
12. A **Cd-test mode in GUI_Clean** that steps the gas ladder itself (20 s holds) during a static run. No manual
    stepping, consistent steps.
13. Faster tests (`pytest-xdist`, about half the time); a `pipeline_spec.OUTPUTS` entry for
    `extreme_frames_more/`.

## Added 2026-10-14 (Ben's list, with notes)

14. ~~**Open the master_log from GUI_Clean** (a button).~~ **DONE 2026-10-14:** top-bar button, green only when safe; START checks it is closed. Excel locks the file on Windows, so if it is open when a
    run ends, the GUI's save fails. Open a read-only COPY, or warn while a run is in progress. About 20 min.
15. ~~**Pressure / flow logs that lag, drop points, then jump.**~~ **DONE 2026-10-14** (STATUS Recent changes). Scan every CCD run's pressure log for gaps
    (time steps far above the median) and step jumps, and list where they fall (camera window or not). The
    likely cause is already on the known-bugs list: the GUI thread blocks for about 10 s while it rewrites the
    83 MB master_log at run end, plus `find_lacie_drive()` and serial logging on the GUI thread. The gas flux
    and film use the camera-window mean P0 and flow, so a gap inside the window biases them. About 1 h for the
    scan; the fix depends on what it finds.
16. **The "stride is different" pop-up.** Not found by its wording yet; need the exact text or a screenshot.
    The nearest is the Taguchi app's Start batch confirmation ("from a different stride ... the AI will be run
    again"). That one DOES matter: it says hours of AI re-running. Keep anything that changes what the
    analysis computes; remove only pure notices.
17. **A full cine (stride 1).** Consecutive 390 fps frames share no droplets, so it gives no velocity. What it
    gives:
    - 10× the frames, so tighter confidence intervals;
    - a pulsing spectrum up to 195 Hz, not 19.5 Hz. At stride 10 the bubbler's rotation (1.7–15 Hz at
      100–900 rpm) sits near the limit and its harmonics alias;
    - a true lag-1 at 2.56 ms.
    It costs about 10× the AI time. Try one run (C7, or a 1.2 mm high-gas run) first. About 1 h, plus the AI.
18. ~~**Run sheets drive GUI_Clean** (a new tab after Extremes).~~ **DONE 2026-10-14** (untried on the rig).
    - Load the app's `next_runs.csv` / `.xlsx`. It already has gas, rpm, feed, orifice and "Notes to type" per run.
    - Pre-fill the settings and Notes for the current row; Start Experiment as now.
    - Only after the master_log is saved: "Did this run go OK?" Yes ticks the row and loads the next one; No
      keeps the row for a redo and flags the run in Notes.
    - Typed Notes are what the app uses to detect the design, so this also removes typing slips.
    About half a day.

## Suggested additions (Claude, 2026-10-14)

19. **Pool every new run into the CCD day's data (Ben, 2026-10-14: the plan).** Must, before Thursday's runs
    are analysed with the CCD day.
    - **Evidence of no drift WITHIN the CCD day:**
      - 0 of 10 block repeats moved beyond ±2 SD;
      - residuals against time are flat (p 0.95 atomised, 0.43 D32, 0.60 mean diameter).
      - Caveat: orifice was run in blocks, so it is mixed with time of day.
    - **Between days it is untested.** Thursday's two centre anchors (9,000 / 500 / 4,000 / 1.2) against the
      CCD day's centres measure it. If they sit within the replicate scatter, pool with no day term; if not,
      fit a day offset.
    - **What the code still does wrong** (STATUS "Known bugs"):
      - runs from a second day are swept into the fit as design points, so the confirmation runs stop
        testing the prediction;
      - the design is re-detected as irregular and the point types are relabelled;
      - there is no day term.
    - **Needed:**
      - "CCD next run N confirm" in Notes → first scored as a test of the prediction, then (optionally) added
        to the fit;
      - the original design kept, the new runs labelled as added (the 12,000 sccm and 6,000–8,000 feed runs
        are outside the original region, so the region the optimiser searches grows with them);
      - an anchor check in the report;
      - a day term that is only used when the anchors disagree.
    - About half a day.
20. **An odd-frame pack for the CCD analysis.** The response-surface publish has none (only the Taguchi tab,
    opt-in). Extreme and busiest frames exist per run; an odd-frame pack would flag things like
    window-drop frames and no-droplet frames. About 1 h.
22. **Check the syringe flow on the rig.** The rate rests on Q_L from motor steps. A one-off: weigh the
    silicone out over a timed run at feed 3,000 and 5,000 (scale + stopwatch), against the steps formula.
23. **GUI_Clean's run-end freeze.** Not the cause of item 15 after all: that was LaCie access on the GUI and
    serial threads (fixed). The master_log save already runs on a worker thread, but its 83 MB rewrite still
    holds the interpreter for about 10 s, which would delay the pop-up in item 18. Linking the images instead
    of embedding them would shrink it.
25. Small items: fold in the Windows timings (`eta.py`, 10 min); the master_log row with "NO DATA AVAILABLE"
    (scripted repair); `Brightest_Frame` still created; `requirements.txt` stale.

26. Faster inference (see item 2): batched tiles, half precision, the overhead around the model, a
    quick-look stride. Only if same-day numbers become worth it.

## IMPORTANT, after the small fixes: calibration scripts (plan mode first)

**27. ~~Scripts for the size calibration~~ BUILT 2026-10-14 (beads; reticle ready in the same script), see `docs/BEAD_CALIBRATION.md`; captures Thursday 2026-10-15, first thing.** Was: scripts for the size calibration, ready before the parts arrive (Ben, 2026-10-14), so the calibration
is a quick session once the parts are in hand. This is a big task: go into plan mode for it once the small
fixes above are done, not before.
- Method and parts list: `docs/DROPLET_MEASUREMENT_METHOD.md` ("Calibration: what to buy and how to run it").
  The parts are a PS20 dot reticle (21 dots from 3.5 µm to 3.5 mm, including 39.6–317 µm, plus a 0.25 mm dot
  array), a 25 mm micrometer stage, and glass-bead "sandwiches".
- What the scripts need to give:
  - the scale (µm/px) and distortion across the field, from the dot array;
  - the true edge threshold for each dot size, compared with half-max (which currently reads 30–35% smaller
    than the eye);
  - the depth of field against size, from a through-focus series, and the in-focus rule checked against it;
  - the beads: how a transparent sphere's bright centre affects its measured size.
- Output: a calibration file the sizer reads, with a version bump. This is what makes absolute sizes
  defensible in the thesis (STATUS open question "Which edge is true diameter").

**28. After calibration: can a classical detector replace the AI for droplets?** (Ben, 2026-10-14.) The AI is
still needed: it decides which dark shapes are droplets (vs ligament fragments and blobs), splits touching droplets
and finds droplets on ligaments. Every droplet number and the atomised fraction's numerator come from it.
Calibration fixes how a found object is MEASURED, not how it is found. Once the calibrated edge rule exists, test a
classical droplet detector (threshold at that edge, then roundness and size) against the 20 hand-labelled
validation frames. If it is close enough, the lab PC could give same-day numbers without the AI.

## Physical prep (Ben, before or on Thursday)

- **Push, then pull on the lab PC.** `git push origin Testing` on the Mac, then `git pull` on the lab PC
  **before any capture**: the master_log is now 20 columns.
- **Lab PC set-up.**
  - Install python-pptx (STATUS item 5).
  - Flash the Portenta limit-switch filter if it isn't done yet, then home a few times and check "moved" is about
    480,000.
- **Check GUI_Clean on the rig.**
  - Save a clean-window reference.
  - Type each insert's orifice length (measure the bore with calipers first).
  - Check the gas-regime readout.
  - After one run, check that `run_summary` has the new gas and window fields.
- **Silicone stock.** The high-feed runs use up to twice the silicone per second; budget refills, and the extra
  travel for the 6,000–8,000 runs.
- **PCC check, stand-off distance, window wiped before every run.**

## Questions for Wednesday

- ~~Can the lab PC run the AI per run?~~ No (Ben, 2026-10-14): the batch runs overnight at home.
- What's the highest sensible feed: syringe pressure, silicone supply, or run time?
- Is the 0.5 mm route attractive in practice (at the ceiling, sensitive to feed and rpm), or is 1.2 mm the
  production route and 0.5 mm only a curiosity?
- How long is Thursday? The table above fills about a full day.
