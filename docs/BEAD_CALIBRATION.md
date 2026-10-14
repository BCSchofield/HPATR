# Size calibration with glass beads (and later the reticle)

Written 2026-10-14 for the session on Thursday 2026-10-15, which comes before the Cd tests and the spray
runs. The plan is `/Users/benschofield/.claude/plans/cozy-orbiting-swing.md`; the background is
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
  **Run sheet** tab. Rows B01–B48 and F1–F5 are the beads; they save under
  `Calibration\Imaging Work` with 1 s captures.

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
11. **Falling beads (F1–F5):** take the sandwich and holder out of the field.
    - Each row is a static run: START, pour a pinch of one size slowly through the field from above,
      press **Trigger** (Space) while they fall, and STOP EVERYTHING once the 5 s video is saved.
    - Catch the beads underneath.
    - These go through the normal AI pipeline overnight at home.

**After the first five captures,** run the analysis on them (below). It shows straight away whether the
background, the focus and the bead density are workable.

Then the Cd tests (rows `Cd 1.2`, `Cd 0.8`, `Cd 0.5`, saved under `Calibration\Orifice Cd`), then the
spray runs if there is time.

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
