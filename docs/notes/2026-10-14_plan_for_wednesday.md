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

## A draft for Thursday (to finalise on Wednesday)

This is about 17 spray runs plus the short tests. Order the blocks 1.2 → 0.8 → 0.5 mm (rising pressure),
randomise within each block, and wipe the window and run the window check before every run.

| Block | Runs | Why |
|---|---|---|
| **Start (no silicone)** | PCC window check (max fps at 256×1152, 512×1152, 2048×256), stand-off distance, clean-window reference | Velocity plan step 1; open item |
| **1.2 mm, Cd test first** | Gas-only ladder 2–12k sccm, plus the line-loss run with the insert out (`docs/ORIFICE_CD_TEST.md`) | Discharge coefficient → gas share and film |
| 1.2 mm | Centre anchor 9,000 / 500 / 4,000 (×1 at the start, ×1 at the end of the day) | Links to the CCD day; drift check |
| 1.2 mm | **Model best 11,000 / 100 / 5,000 ×3** | Confirms the prediction (288k/s, PI 249–326k) |
| 1.2 mm | 11,000 / **500** / 5,000 ×2 | Is low rotation really better? (a weak rpm × orifice term) |
| 1.2 mm | **12,000 / 0 / 5,300 ×2** | Steepest ascent at the rig's gas limit |
| 1.2 mm | 12,000 / 100 / **6,000, 7,000, 8,000** ×1 each, ascending | Where does feed stop paying? (Use more travel: 8,000 steps/s over 36 mm lasts only 31 s; the limit is 72.5 mm.) |
| 1.2 mm | Exposure series at the centre: 1 / 4 / 16 / 40 µs, about 2 s each | Velocity step 1 |
| **0.8 mm, Cd test first** | Gas-only ladder | Chokes at 10–12k sccm, so a good Cd |
| 0.8 mm | 12,000 / 100 / 5,000 ×2; watch P0, and stop if it nears 9.3 barA | Capacity check; the orifice² point the model lacks |
| **0.5 mm, Cd test first** | Gas-only ladder | Chokes from about 4k sccm |
| 0.5 mm | **C7 recipe 7,000 / 900 / 3,000 ×3** | Is 280k/s repeatable, or is C8's 187k/s the norm? |

That's about 17 spray runs at roughly 8 minutes each (the CCD day averaged that), plus about 1.5 h of short
tests: a full day.

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
3. **Thursday's run sheet.** Check whether the app's *Build a run sheet* can take a custom list (numbered Notes,
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
7. **Settling time against feed.** From the CCD pressure logs, find when the silicone arrives and P0 settles for
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

14. **Open the master_log from GUI_Clean** (a button). Excel locks the file on Windows, so if it is open when a
    run ends, the GUI's save fails. Open a read-only COPY, or warn while a run is in progress. About 20 min.
15. **Pressure / flow logs that lag, drop points, then jump.** Scan every CCD run's pressure log for gaps
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
18. **Run sheets drive GUI_Clean** (a new tab after Extremes).
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
23. **GUI_Clean's run-end freeze.** The master_log rewrite (about 10 s) is the likely cause of item 15 and
    would also delay the pop-up in item 18. Move the save to a worker thread, or link the images instead of
    embedding them.
25. Small items: fold in the Windows timings (`eta.py`, 10 min); the master_log row with "NO DATA AVAILABLE"
    (scripted repair); `Brightest_Frame` still created; `requirements.txt` stale.

26. Faster inference (see item 2): batched tiles, half precision, the overhead around the model, a
    quick-look stride. Only if same-day numbers become worth it.

## IMPORTANT, after the small fixes: calibration scripts (plan mode first)

**27. Scripts for the size calibration, ready before the parts arrive** (Ben, 2026-10-14), so the calibration
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
