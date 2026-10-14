# Size calibration with glass beads (and later the reticle)

Written 2026-10-14 for Thursday 2026-10-15. The bead work is the LAST part of the day, after the Cd tests and
the (10) spray runs (Ben). The plan is `/Users/benschofield/.claude/plans/cozy-orbiting-swing.md`; the background is
`docs/DROPLET_MEASUREMENT_METHOD.md`.

## Why

The sizer's diameters have never been checked against anything of known size. Three things are open:

- **Edge.** Half-max (the sizer's edge, sizer 2.2.0) reads 30–35% smaller than the eye. Which is right?
- **Depth of field.** "In focus" (robust core T ≤ 0.70, plus the 2.2.0 sharpness rule) has never been
  tied to a depth. Counts, D32 and droplets/s all need to know how deep a slab each droplet size is
  counted from.
- **Transparency.** Our droplets are transparent and show a bright centre. The sizer keeps the
  half-max region around the darkest pixel and does not fill holes, so a bright centre can turn the
  region into a ring: the area reads low, and the 2.2.0 rule may then reject the droplet.

Glass beads of certified size, viewed in air, are the nearest thing to a droplet of known size.

**Method:** Blaisot & Yon 2005, *Exp. Fluids* 39:977–994, Sections 2 and 4. A target of known size is
stepped through focus. At each step we measure the contrast C = (1 − T_min)/(1 + T_min) and the
radius at relative grey levels l = 0.25, 0.61 and 0.77, where the level is T_min + l(1 − T_min). From
these come a blur width χ, and a DOF found by accepting a drop when χ < χ_max. They used chrome discs.
The beads add the transparent case.

## What you need

- **Beads:** 37.36, 56.28, 76.39, 98.1 and 155.8 µm, each certified with a small spread. Their
  details go in `Calibration/Imaging Work/targets.json`.
- Clean microscope slides and coverslips, tape, the slide holder with its micrometer, a fine sieve or
  folded paper, and something under the field to catch falling beads.
- The run sheet: `Experiments\Run sheets\2026-10-15 Thursday run sheet.csv`, loaded on GUI_Clean's
  **Run sheet** tab. The sheet's order:
  - each insert's Cd test and spray runs (1.2, 0.8, 0.5 mm; 10 runs);
  - the optional exposure series;
  - rows B01–B43, the sandwiches (saved under `Calibration\Imaging Work`, 1 s captures);
  - last, NOT in the sheet: the falling beads, recorded in PCC (step 11). Two 5 s pours per size, because
    a hand sprinkle does not cover a defined plane.

## Make the sandwiches (before the session)

- **One MIXED sandwich, with all five sizes on one slide,** for the through-focus series. The beads
  stay still, so each bead is followed through every depth. Its size at best focus tells which of the
  five it is.
- **Five SINGLE-size sandwiches,** for a clean size check per size.

For each one:
1. Lay a clean slide flat and sprinkle a **sparse** layer of beads. They must not touch: aim for a
   few dozen in the camera's 20 × 11.5 mm field.
2. Lower a coverslip onto them; the beads act as spacers.
3. Tape the edges.
4. **No glue, epoxy or varnish near the beads.** Glass in glue is index-matched (n ≈ 1.5), and the
   edge disappears.

## On the rig

1. **Pull the repo and restart GUI_Clean** first. The Run sheet's "Save under" and "Post-trigger (s)"
   columns need today's code.
2. **Freeze the optics exactly as for the CCD day:** lens, aperture (f-number), focus ring, camera to
   spray distance, backlight, 4 µs exposure, 2048 × 1152, 390 fps.
   - Photograph the lens rings.
   - Moving the camera sideways is fine; changing the focus ring, the aperture or the distance is not
     (see the table in the chat of 2026-10-14).
3. **Empty or disconnect the silicone line.** Every bead row moves the traverse 0.5 mm (3.4 s at
   1,000 steps/s) so that the auto-trigger fires. That is 21.5 mm in all, so home first.
4. **Camera tab:** Run AI analysis OFF, Window check OFF, Auto-trigger ON. The run sheet sets the
   post-trigger to 1 s for each bead row and back to 13 s for the spray rows. The "differs from the
   standard" question is not asked for that.
5. **Mount the mixed sandwich** in the holder at the spray plane, coverslip towards the camera, square
   to the camera axis. If one side of the field is sharper than the other, it is tilted.
6. **Find best focus** on the 155.8 µm beads with the micrometer, by eye on the live view. That
   reading is **z0**; write it down.
7. **Through focus (B01–B23):** z = z0 −4.00, −3.00, −2.50, −2.00, −1.50, −1.25, −1.00, −0.80, −0.60,
   −0.40, −0.20, 0, +0.20 … +4.00 mm.
   - **Always turn the micrometer the same way** (backlash).
   - Do not slide the sandwich sideways during these rows.
   - If beads still look sharp at ±4 mm, carry on in 1 mm steps and add rows by hand
     (Notes `BEAD mix z+5.00`).
8. **More beads at focus (B24–B27):** back to z0, approaching from the same side as before, then slide
   sideways to four new patches.
9. **Background (B28):** at z0, a patch with no beads in view.
10. **Single-size sandwiches (B29–B43):** for each size, refocus with the micrometer to that slide's own
    best focus, then capture two patches and one empty patch.
11. **Falling beads, recorded in PCC: LAST, after the sandwiches.** No GUI_Clean run, no motor: plain PCC
    captures.
    - Clear the field first (nozzle, holder), but **do not touch the camera, the lens (focus ring, aperture),
      its distance or the backlight**: the focal plane must be where it was in the morning.
    - **Hand the camera to PCC:** close GUI_Clean (or disconnect the camera in it).
    - **In PCC, match the day's settings:** 2048 × 1152, 390 fps, exposure **4 µs** (back from the exposure
      series), about 5 s per recording.
    - **Two pours per size.** Save each recording to the LaCie as **`BEAD fall <size> p1.cine`** and
      **`… p2.cine`**, e.g. `BEAD fall 56.28 p1.cine`, in
      `Calibration\Imaging Work\2026\10\15\falling\`.
    - **The file name is what the analysis reads.** Underscores instead of spaces are fine. Any other name
      works too, if you tell Claude which is which.
    - **Mark the focal plane first:** where the sandwich's bead layer sat.
    - **Dispense** from a small sieve or tea strainer, or a creased card, tapped gently: a slow, sparse
      rain. Not a funnel (one fast stream in one plane) and not from fingers (clumps).
    - **Use a TINY pinch:** a few mg is hundreds of beads; aim for ~5–30 in view per frame.
    - **Height and sweep:** hold it 15–20 cm above the MIDDLE of the field, away from the window, and sweep
      it slowly towards and away from the camera through the focal plane (about ±10 mm). Some beads then
      land on the sharp plane and most fall either side, which is what the AI's in-focus test needs.
    - **Beads dry, room still,** gas and bubbler off. Static and damp make glass beads clump; do not blow.
    - **Record:** start sprinkling, start/trigger the PCC recording once beads are falling, keep tapping for
      the 5 s, then save the cine with its name as above.
    - **Catch** the beads underneath.
    - **Afterwards:** clean up stray beads and **wipe the window**. A bead left on the glass is a speck in
      every later run.
    - These go through the normal AI pipeline overnight at home (below).

**After the first few captures,** check on the live view that the beads are sparse and separate and that
best focus is sharp. The analysis needs the LaCie on the Mac, so it runs afterwards.

**Order on the day:**
1. each insert's Cd test (saved under `Calibration\Orifice Cd`) and its spray runs;
2. the exposure series (optional);
3. the sandwiches (steps 5–10);
4. the falling beads (step 11), last.

Before the sandwiches: clean up the silicone, empty or disconnect the line, home the traverse, and move the
nozzle out of the way if needed. Do not touch the camera, lens, distance or backlight.

## The analysis (Mac; no AI for the static beads)

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 /Users/benschofield/Documents/GitHub/HPATR/AI/Real_Data_Code/bead_calibration.py "/Volumes/LaCie/Calibration/Imaging Work/2026/10/15" --out "/Volumes/LaCie/Calibration/Imaging Work/analysis/2026-10-15"
```

Each capture is averaged over 40 frames, spread through its 1 s (about 20 s a capture from the LaCie;
`--max-frames` changes it), so the full set takes about 15-20 min. Anything dark in a bead-free (`bg`)
capture is treated as dust (window, sensor or slide) and dropped wherever it turns up: an averaged spray
frame shows about 200 such specks. So take the `bg` captures. `targets.json` (supplier, lot, spreads) is
found by itself in `Calibration/Imaging Work`.

**What it does:**
- Finds the captures by their Notes (`BEAD …`) and averages each 1 s capture.
- Estimates the background from the frame itself, in two passes:
  - a large-window median;
  - then the local average of everything that is not a bead, which follows a backlight gradient to
    better than 1 % (tested).
- Finds the beads and follows each one through every depth.

**Per bead, it measures:**
- what the current sizer gives: robust core, half-max area, in focus or not, and the 2.2.0 rule;
- diameter against threshold level;
- whether it comes out as a ring;
- C and χ.

**It reports:**
- at focus, the sizer's bias per size against the certificate;
- the threshold level that gives the certified size;
- the share of rings, and the share of in-focus beads the 2.2.0 rule rejects;
- through focus, the depth range in which the current rule counts each size as in focus (the
  1/DOF(d) weight);
- the depth range sized within ±5%;
- the χ(z) fit.

**Falling beads: the AI first, at home overnight.** The pours need the AI chain; the static captures do not.
`git pull` on the home PC first. In Command Prompt, with the LaCie as `D:`, point it at the folder of PCC
recordings:

```
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" "C:\Users\BenSc\Documents\GitHub\HPATR\AI\Real_Data_Code\run_ai_where.py" "D:\Calibration\Imaging Work\2026\10\15\falling" --notes "BEAD fall"
```

- Add `--dry-run` first to see the ten recordings it picks (two per size); a dry run creates nothing.
- **Each recording becomes a run folder next to it,** `falling\BEAD fall 56.28 p1\`, with a
  `run_summary.xlsx` whose Notes are the file name. The AI chain copies the .cine into that folder (its rule:
  the video lives in the run), so each pour is stored twice (~6 GB each). The original file is never
  changed.
- It is restartable, and writes only into those run folders.
- At stride 10, a 5 s pour is about 195 frames, about 6 min a run on the GPU (about an hour for the ten).
- The analysis lists each pour and pools the two pours of each size.
- Then re-run the analysis command above on the Mac; the falling-bead table fills in.

Results go in `analysis/<date>/`, including `optics_calibration_v1.json`. **Nothing in the pipeline
changes yet:** a new sizer (3.0.0) is decided with Ben once the beads, and later the reticle, are in.

## Later: the reticle (Graticules Optics PS20), when it arrives

It adds three things the beads cannot give:

1. **Scale and distortion across the field,** from the 0.25 mm dot array at 0.5 mm pitch. Captures at
   z0: centre and four corners (Notes `RETICLE array c|tl|tr|bl|br`). Today 10 µm/px is hardcoded in
   seven places; if the array disagrees, that becomes one value from the calibration file.
2. **Opaque discs of certified size,** 39.6, 56.0, 79.2, 112, 158, 224 and 317 µm (±0.5 µm), stepped
   through the same z list as the mixed sandwich (Notes `RETICLE z-1.25` …), plus a clear-glass
   background (`RETICLE bg`). Mount it **chrome side towards the camera**. This is Blaisot & Yon's own
   target, so their model applies directly.
3. **The transparency effect, isolated.** These pairs are nearly the same size:

   | Bead (µm) | Reticle dot (µm) |
   |---|---|
   | 37.36 | 39.6 |
   | 56.28 | 56.0 |
   | 76.39 | 79.2 |
   | 155.8 | 158 |

   Bead minus dot, at the same depth, is the bright centre's effect.

The same script handles the reticle: `targets.json` lists the dots and the array pitch. Its output is
`optics_calibration_v2.json`.

## Caveats

- **Refractive index.** Soda-lime glass is n ≈ 1.52 and silicone n ≈ 1.40, so a bead's bright centre is
  not exactly a droplet's. Sizes are close enough for the edge; the centre spot may differ a little.
- **Coverslip.** The sandwich beads are seen through a 0.17 mm coverslip, which shifts focus by about
  0.06 mm. That is negligible against the depth of field.
- **37.36 µm is about 3.7 px across,** near our detection limit. Expect scatter.
- **Bead identity on the mixed slide** comes from the size at best focus. Beads that sit between two
  sizes are dropped.
