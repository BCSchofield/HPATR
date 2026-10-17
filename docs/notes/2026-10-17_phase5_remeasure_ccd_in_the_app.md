# Phase 5: re-measure and re-analyse the CCD day at sizer 3.1.0, in the app (Ben)

Ben does this himself so he knows the steps and the result is like for like. Sizer 3.1.0 plan:
`2026-10-17_sizer_3.1.0_plan.md`.

**Rehearsed 2026-10-17 (Claude, on a scratch copy of CCD run 125754):** the re-measure kept the 3.0.0 results in
`_sizer3.0.0/`, built the rolling background (1 window drop, from frame 100), marked 835 static specks, wrote the
largest-droplets sheet, and took 7 min 08 s (sizing with the background 4 min 06 s, liquid stage 3 min). The app's
master_log fill, run on a copy of the live log, migrated it to the new layout and wrote the run's row: D32 49.24 µm,
30-60 µm droplets/s 77,289, bands 48.4 / 5.45 / 3.14 / 0.40 / 0.04 per cm³, in-band flow 0.156 mL/min,
concentration 57.4 per cm³, atomised in volume 41.6 %, Sizer 3.1.0.

## Before you start

- **The LaCie is plugged into the Mac.**
- **Excel is closed by the time you press Analyse** (step 4). The batch itself never touches master_log. With Excel
  open, the analysis skips master_log, says so, and the analysis still stands.
- **Nothing old is lost.** Re-measuring moves each run's 3.0.0 results (`droplets_0.30/`, `liquid_0.30/`) into
  `shadowgraph/analysis/_sizer3.0.0/` first. The 2.2.0 ones are already in `_sizer2.2.0/`. The old analyses and decks
  in `Experiments/Taguchi/CCD/` are never touched, since the new analysis goes to a new folder.
- **Time: about 4 hours.** The app runs one run at a time, ~7 min each (the 3.0.0 re-measure took 1.5 h only because
  Claude's script ran four at a time). The progress window shows the ETA. The batch runs in its own process, so
  closing the app window does not stop it; the Mac sleeping does.

## 1. The new output folder, with the old analysis's model (Terminal)

The Batch and Response surface tabs share one output folder. A new folder keeps the 2.2.0 and 3.0.0 analyses
untouched. Copying the old analysis's `rsm_design.json` and `rsm_model.json` into it makes the Model page open with
exactly the factors and goals of `Rec CCD 4 factor 20-60um` (gas, rpm, silicone, orifice 0.5/0.8/1.2/1.8 on a log
scale; goals: droplets per second in the band ×3, atomised fraction ×1). The band itself comes from Settings.

```
mkdir "/Volumes/LaCie/Experiments/Taguchi/CCD/Rec CCD 4 factor 30-60um sizer 3.1.0"
cp "/Volumes/LaCie/Experiments/Taguchi/CCD/Rec CCD 4 factor 20-60um/rsm_design.json" "/Volumes/LaCie/Experiments/Taguchi/CCD/Rec CCD 4 factor 20-60um/rsm_model.json" "/Volumes/LaCie/Experiments/Taguchi/CCD/Rec CCD 4 factor 30-60um sizer 3.1.0/"
cd /Users/benschofield/Documents/GitHub/HPATR && /Users/benschofield/anaconda3/envs/phantom/bin/python3 -m src.ai.Taguchi_Analysis_UI
```

To keep the Mac awake for the ~4 h, in a second Terminal window (Ctrl-C to end it early; it ends itself after 6 h):

```
caffeinate -dims -t 21600
```

## 2. Re-measure (Batch tab)

1. **OUTPUT FOLDER → Browse…** → `Experiments/Taguchi/CCD/Rec CCD 4 factor 30-60um sizer 3.1.0`.
2. Click **+** and add `/Volumes/LaCie/Experiments/2026/10/12`. The 33 runs appear, each flagged
   "re-measure: sizer 3.0.0, the default is 3.1.0". All 33 ticked.
3. In the box under the output folder ("runs that already have results"), choose
   **"Re-measure only (keep frames + AI predictions)"**.
4. **Settings tab:** "Droplet count size band (µm)" reads **30-60**. It starts from the default on every launch.
5. Back on the Batch tab, press **Run batch**. The confirmation should say the frames and AI predictions are
   reused. If it says the AI will run again, cancel: the Mac cannot run it.

## 3. Check it finished

All 33 "ok". A failed run is recorded and the batch moves on; **Retry failed** redoes just those.

## 4. Analyse (Response surface tab)

1. **Design page:** the 33 runs, detected as the 4-factor CCD.
2. **Model page:** check it came back as above (the copied files). "In-band liquid flow (mL/min)" is a new goal you
   can add; leave it off for a like-for-like with the 20-60 analysis.
3. Close Excel.
4. **Analyse and next runs → Analyse.** You get the report, workbook, deck (with each run's largest-droplets slide
   and the new frame keys) and next runs in the new folder, and **master_log fills itself** for the 33 rows. The log
   should say `master_log: updated 33 row(s); backup master_log BACKUP <today> before analysis update.xlsx`
   (in `Experiments/Logs/Backups/`). The first time, this also moves master_log to the new layout: the six
   "Sizer 3.0.0" columns go, the nine new columns appear right of "Droplets/s (30-60 um)". Rows not analysed keep
   their values, with "Sizer" blank.

## 5. Then (Claude)

- **The 2.2.0 / 3.0.0 / 3.1.0 comparison,** with each run's largest-droplets slide looked at by eye.
- **Phase 6 of the 3.0.0 plan:** your go or no-go.
- **Phase 7:** re-measure every other day (Taguchi 10-05, L9 10-01) the same way.

## Lab PC

`git pull` before the next capture. 3.1.0 is the default there too, and GUI_Clean writes master_log's new layout.
An old GUI_Clean would write into the wrong columns once master_log has moved to the new layout (step 4).
