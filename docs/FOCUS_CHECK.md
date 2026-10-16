# Focus on the spray centre (the 300 µm pinhole)

Sizer 3.0.0 plan, Phase 1 (`docs/notes/2026-10-15_sizer_3.0.0_plan.md`), written 2026-10-16. The pinhole arrives
the week of 2026-10-19.

## Why

The new focus rule keeps only droplets whose edge blur χ is small. That is a slab about ±0.25–0.9 mm deep. If the
focal plane sits 1 mm off the spray axis, we measure the side of the spray, not its centre. Focus by eye was
already ~1 mm off on 2026-10-15 (the 155.8 µm slide read χ 21 µm against 13 at true focus), and nothing recorded
where focus was.

## The target

- **A Ø300 µm precision pinhole** (a hole in thin metal foil in a ~1" mount).
- **Its holder** seats in the insert holder in place of an orifice insert, with the foil on the orifice axis,
  facing the camera.
- **The foil is microns thick and there is no glass,** so the feature plane is the foil itself: no "which face" or
  refraction offset.
- **It looks reversed:** a bright disc on a black frame (the mount blocks the backlight).
- **Why 300 µm:** about 30 px across, with ~94 px of edge to average, so the reading is steady.
- **A scale on the camera rail** (digital or micrometer, ~0.01 mm) makes every focus move readable.

## On the rig (GUI_Clean, Camera tab, card FOCUS CHECK (SPRAY CENTRE))

1. Fit the pinhole holder. Backlight on, exposure as for spray runs.
2. Tick **Measure live** (it starts the live view). The line above shows:
   - χ now and the best χ so far;
   - roughly how far from the best (χ grows ~8 µm per mm);
   - the pinhole's measured diameter against 300 µm (a scale check).
3. **Slide the camera on its rail until χ is smallest.**
   - It turns green within 2 µm of the best (~0.25 mm).
   - χ does not say which side of focus you are on: step one way and watch it.
   - **Reset best** after moving the holder or the lighting.
4. Type the rail reading and **Record** with the turn set to **0°**.
5. **Turn the holder 180°** about the vertical axis, focus again, type the rail reading and **Record** at **180°**.
   - A foil off the axis by e sits at −e once turned, so **the axis plane is midway**. The card shows it.
   - If the two readings differ by more than 0.2 mm, re-seat or adjust the holder and repeat.
6. **Set the rail to the midpoint,** check the reading is still green, and **take the holder out before spraying**:
   silicone mist would clog the pinhole.

Every run started after that records the day's check in its run_summary, field **Focus check**. For example:
"2026-10-20 09:12, chi 13.2 um, target 300.4 um, axis at rail 12.345 mm (0/180 differ 0.09 mm)". Without a check
that day it says "NOT DONE TODAY". The records are kept on the PC in `~/.hpatr/focus_check.json`, never on the LaCie.

## Optional: an archived capture

A 1 s capture of the pinhole keeps the focus check with the day's data. Add a run-sheet row whose Notes start
`FOCUS CHECK`, e.g.:

```
Run,Orifice (mm),Gas flow (sccm),Bubbler RPM,Silicone (steps/s),Motor Travel (mm),Notes to type,Save under,Post-trigger (s)
F1,,0,,1000,0.5,FOCUS CHECK pinhole start of day,Calibration/Focus,1
```

Then measure it on the Mac (writes only `focus_check.json` into `--out`):

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 /Users/benschofield/Documents/GitHub/HPATR/AI/Real_Data_Code/focus_edge.py "/Volumes/LaCie/Calibration/Focus/2026/10/20" --certified-um 300 --out "/Volumes/LaCie/Calibration/Focus/analysis/2026-10-20"
```

## The maths

`AI/Real_Data_Code/focus_edge.py` (numpy only) fits Blaisot & Yon's Gaussian edge, `lo + (hi − lo) Φ((r − R)/σ)`,
to every pixel near the disc's edge, with r measured from the disc's centre. That averages the profile all the way
round.

- **The blur width** is χ = 2√(σ² − 1/12) × µm/px. The 1/12 px² is the pixel's own width.
- **The diameter** is 2R × µm/px, corrected for the curvature of a blurred disc (+σ²/2R).

A straight edge (a reticle square, a razor blade) works the same way with `line_edge`.

## When the reticle arrives

- Step a large square and the dots through focus. That checks the meter's χ → |z| conversion on certified targets.
- Check the pinhole's measured diameter against the reticle's certified scale.
