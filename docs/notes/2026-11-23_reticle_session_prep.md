# Reticle (PS20) session: explore on the rig, then the run sheet (2026-11-23)

This is for Ben at the rig, and for Claude on the lab PC. Ben explores with the camera first (Part 1) and sends
Claude the images and answers (Part 2). Claude then writes the run sheet (Part 3), and Ben records it.

Claude on the lab PC: read this file, then `docs/STATUS.md` ("Next steps", item 5 "Rig") and
`docs/BEAD_CALIBRATION.md` ("Later: the reticle"). Write the run sheet only after Ben's answers. Analysis code waits
for his go (plan before code). Give exact commands for Windows.

## Where things stand

- **Sizer 3.1.0** (accepted 2026-10-17) sizes blurred droplets through a defocus look-up table: how much bigger each
  size reads, by blur width χ.
  - The table is in the optics profile, `config/optics/lens1_2026-10.json`, under `calibration.lookup_table`.
  - On the LaCie: `Calibration/Imaging Work/analysis/sizer_calibration_2026-10-16/` (`fig_table.png`,
    `lookup_table.csv`, `report.md`).
- **It has only three sizes:** 37.36 µm (108 beads), 56.28 µm (31 beads) and 76.39 µm (2 beads).
  - Above 76 µm it reuses the 76 µm row.
  - The falling 98.1 and 155.8 µm beads check that this is good enough (within +4.7 % up to χ 50 µm). They are
    not part of the table.
- **The three-bead slides were dropped on 2026-10-22,** because the beads fall off when the slide is upright. The
  PS20 replaces them:
  - its dots through focus fill the top of the table (79.2–317 µm) and add the small end (14–28 µm);
  - its dot array measures the scale (10 µm/px is the recorded value) and the distortion across the field.
- **No re-measure of existing runs** (Ben, 2026-11-23). The runs are redone soon in the new box. The reticle's
  results become optics profile v2, and the new runs use it.
- **The 300 µm pinhole focus check comes first, if it isn't done yet** (`docs/FOCUS_CHECK.md`). It sets the lens's
  focus on the spray centre. The reticle must then calibrate the lens as it will be used, so nobody touches the lens
  after the pinhole.

## The slide and the field

- **PS20:** a 76 × 25 × 1.5 mm soda-lime glass slide with chrome patterns.
- **Its dots** (and squares) run in a √2 series from 3.5 µm to 3.5 mm. The ones we use, and their width at
  10 µm/px:

  | Dot (µm) | 14.0 | 19.8 | 28.0 | 39.6 | 56.0 | 79.2 | 112 | 158 | 224 | 317 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | Width (px) | 1.4 | 2.0 | 2.8 | 4.0 | 5.6 | 7.9 | 11 | 16 | 22 | 32 |

  - 14–28 µm are below the 30 µm smallest size we currently trust. They test that limit.
  - 39.6 / 56.0 / 79.2 / 158 pair with the beads 37.36 / 56.28 / 76.39 / 155.8. The difference shows the effect of
    a bead's bright centre.
- **The dot array:** 0.25 mm dots at 0.5 mm pitch.
- **The camera's field:** 2048 × 1152 px = 20.5 × 11.5 mm. If the array fills it, that is ~40 × 23 dots.
- **The layout is unknown.** We don't know where the dots, squares and array sit on the slide; the product's
  drawing wasn't found online. Part 1 finds out.

## Part 1. At the rig: what to find out (screenshots are enough; nothing recorded)

**Set up as for the real runs:**
- the same lens, focus ring and aperture;
- the same backlight setting;
- 4 µs exposure, 2048 × 1152, 390 fps.

**The new box's 5 mm wall doesn't need to be in place** (Ben, 2026-11-23). The focus shift it causes doesn't
matter, because the table works in blur relative to best focus, and focus is set through the wall anyway. After the
session, one quick check is worth two extra captures: the array at best focus with and without a 5 mm offcut of the
wall's sheet in the light path. It confirms the scale and edge sharpness agree to within ~1 %. The scale can only
change if the lens isn't telecentric (row 4 below tells), and a plastic sheet can lose a little contrast.

Then find out:
1. **Mounting.** Chrome side towards the camera, at the spray plane, on the micrometer stage, square to the
   camera.
2. **Which dots fit in one frame.** Can 14 → 317 µm all be in view at once?
   - Every dot needs to be at least 1 mm (100 px) from the frame edge, and the dots at least 0.5 mm apart.
   - Keep dots bigger than 317 µm (448 µm and up) out of the frame. The script estimates the backlight with a
     101 px median, and that breaks next to anything that big.
   - If they don't all fit, use two frames (small end, big end) that share one dot (e.g. 79.2 or 112 µm), which ties
     them together.
   - Where the squares sit. If a run of them fits in the same frame, keep them in.
   - The smallest dot you can see at best focus.
3. **How much of the frame the dot array fills.**
   - If it covers the whole 20.5 × 11.5 mm, one centred frame measures scale and distortion everywhere, and the
     four corner rows go.
   - If not, its size in mm.
4. **Square to the camera.** At best focus on the array, check the left and right edges (and the top and bottom) are
   equally sharp. If one side goes soft first as you defocus, the slide is tilted.
   - This only catches a large tilt. 1° across the 20.5 mm field puts the edges 0.36 mm apart in focus, about 3.4 µm
     of χ (k 9.57 µm/mm), which can't be seen. Square it as well as you can by eye and move on: the analysis takes
     out what's left (below, "After the session" item 2).
5. **Stage travel.**
   - The micrometer reading at best focus on the dots (z0).
   - Whether it reaches z0 − 6 mm and z0 + 6 mm. On 2026-10-15 it didn't move from +7 to +8.
6. **Moving between the dots and the array.** Can the slide slide sideways without changing its distance to the
   lens? If it has to be re-seated, that's fine: each patch then gets its own z0.
7. **Brightness.** The dots are fully opaque, so they should read near 0. The background should be about as bright
   as on the bead day and not saturated.

### Found at the rig, 2026-11-23 (PCC and GUI_Clean screenshots)

- **The dots are one vertical column, 2534 → 3.5 µm, each centre one larger-dot diameter below the last.** So the gap
  between neighbours is only 0.146 × the larger dot. The gaps by pair (µm):

  | Pair | 1792→1267 | 634→448 | 448→317 | 317→224 | 158→112 | 112→79 | 79→56 | 56→40 | 40→28 | 28→20 | 20→14 |
  |---|---|---|---|---|---|---|---|---|---|---|---|
  | Gap | 262 | 93 | 65 | 46 | 23 | 16 | 12 | 8 | 6 | 4 | 3 |

  - At best focus (σ ≈ 4.5 µm) the dots at 56 µm and below run together into one tapering line. The 14–28 µm dots
    can't be measured as separate dots at all.
  - At |z| = 5 mm (χ ≈ 55 µm) every pair below ~634 µm overlaps on the sides that face each other. The left and right
    arcs of each dot stay clear for dots ≥ ~79 µm up to χ 50.
  - So "the small end (14–28)" and the bead pairs at 39.6 / 56.0 / 79.2 don't come from this column directly. 158
    (and 112 / 224 / 317) are clean. The rest needs isolated dots elsewhere on the slide, or a model of the whole
    column (discs × Gaussian blur), with the small end of the table simulated from the measured blur. That's a new
    method: plan before code.
- **Scale:** the 1792 µm dot measures 1791.7 µm at 10 µm/px. The ruler's ticks, 1 mm apart, are 100 px apart.
- **Focus:** best χ 8.7 µm on the 1792 µm dot, against χ0 13.15 µm in the profile (from beads).
- **The column, ruler and concentric squares all fit in one frame.** The column runs along the 1152 px axis; 1792 µm
  down to the tip is ~700 px.
- **Dust:** sharp specks all over the slide, on the slide itself, and they don't come off. Most are clear of the
  column. The analysis masks them; they're not a reason to stop.

## Part 2. What to send Claude on the lab PC

- A full frame at best focus of the dots (each patch, if two) and of the array: a GUI screenshot or a saved TIFF.
- One frame of the dots at about z0 + 5 mm (to see the blur).
- The micrometer reading at z0, and how far it goes each way.
- A phone photo of the whole slide, showing where the patterns sit, and of the certificate.
- The pinhole check: done or not.

## Part 3. The run sheet (Claude writes it from Part 2)

**Written 2026-11-23: `docs/notes/2026-11-23_reticle_run_sheet.csv`, 20 rows** (copy:
`E:\Experiments\Run sheets\2026-11-23 Reticle run sheet.csv`). R01–R19 are the column at ±6 mm; R20 is one array
capture (`RETICLE array c`). It differs from the plan below:
- **Static runs:** Silicone 0, so no pump, no homing and no pump vibration. Each row: START, Arm, Trigger, wait for
  "saved", then STOP EVERYTHING, which saves the run with its Notes.
- **The dial has no reading,** only 0.5 mm per turn. So z0 is wherever the slide is in focus, and each row says how
  many turns forwards to move.
- **Ben dropped the z0 repeat and the bg row:** best focus comes from the fit, and there's no clear patch. The
  background is estimated from each frame, with the patterns and dust masked. Nothing in the sheet checks for drift.
- **One array capture,** centred, not the corners.
- **No array through focus** (the lens is telecentric) and **no wall-offcut check** (there's no offcut).
- **Framing:** one frame for the whole column, from the 1792 µm dot to the tip.

The original plan, kept for reference:

**Template:** `docs/notes/2026-10-16_big_bead_through_focus_run_sheet.csv`, with the same columns. Save it as
`docs/notes/<date>_reticle_run_sheet.csv` and load it in GUI_Clean's **Run sheet** tab, which fills in each row's
Notes and settings.

**Every row:**
- Gas 0; Silicone 1000 steps/s; Motor Travel 0.5 mm. Start needs a travel, so empty or disconnect the silicone line
  and home the traverse first.
- Camera:
  - exposure 4 µs, 2048 × 1152, 390 fps;
  - Run AI analysis OFF, Window check OFF, Auto-trigger ON;
  - save the **.cine only** (no TIFFs); Pre-trigger 0.
  - **Post-trigger 0.15 s** (~58 frames). `bead_calibration.py` averages 40 frames. The bead day used 1 s, which
    made each row slower.

**The rows** (about 30 at most; an estimate of ~20–25 min):
1. `RETICLE bg`: a clear patch of the slide.
   - **Optional.** The script estimates the backlight from each frame itself.
   - It is a cross-check (T ≈ 1) and a dust map, which helps tell the 14–20 µm dots from specks. One row.
2. **The dots through focus, 19 depths:** z = −6, −5, −4, −3, −2, −1.5, −1, −0.5, −0.25, 0, +0.25, +0.5, +1, +1.5,
   +2, +3, +4, +5, +6 mm.
   - Notes `RETICLE z-6.00` … `RETICLE z+6.00`, with ` p1` / ` p2` added if there are two patches (then 38 rows).
   - Take up the backlash first: go past −6 and come back to −6, then always turn forwards.
3. **The array at z0:** `RETICLE array c`. Add `tl tr bl br` only if the array doesn't fill the frame.
4. ~~The array through focus~~ **Dropped (Ben, 2026-11-23): the lens is telecentric**, as the optics profile
   already records (Ben, 2026-10-16).
   - If a z ever goes into an array row: **write z before "array".** The parser lets the later token set the kind,
     so `RETICLE array c z-5.00` would be read as a dots capture.

**Why these depths and not the old 31:**
- The analysis fits blur against depth as a V (χ = χ0 + k|z − zf|). The profile has χ0 13.15 µm and k 9.57 µm/mm.
  A V needs points on both arms more than closely spaced points near focus.
- χ reaches the 50 µm limit at about ±4–5 mm, so depths beyond ±6 mm are never used.
- One target replaces three slides, so this is one series instead of three.

## After the session (each on Ben's go)

1. The certificate's values go into `Calibration/Imaging Work/targets.json`.
2. `bead_calibration.py` gains the 14 / 19.8 / 28 µm dots, the squares (a shape per target) and the
   array-through-focus result (the scale against z).
   - **Best focus is fitted per dot, not once per patch.** The dots sit at different places on the slide, so any tilt
     gives each one its own zf. Fitting zf per dot takes the tilt out whatever the eye check said.
   - The array through focus gives zf at every array dot, so a plane zf(x, y) fitted to them measures the tilt
     directly. Report it; if it is more than ~0.1 mm across the frame, re-square the slide before the new box's
     runs.
3. The sizer calibration is redone with both days, which gives optics profile v2. The new box's runs use it.

## Not now

- No re-measure of existing runs.
- The big-bead slides, unless the beads can be made to stay on upright.
