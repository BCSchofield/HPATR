# CCD day (2026-10-12) re-analysed

Phase 9 of the CCD follow-up plan (`2026-10-13_CCD_followup_plan.md`). The first analysis is untouched.

| | First analysis (2026-10-13 09:13) | Re-analysis (2026-10-13 15:00) |
|---|---|---|
| Folder | `Taguchi/CCD/CCD 4-factor 12-10-2026/` | `Taguchi/CCD/CCD 4-factor 12-10-2026 reanalysis 13-10-2026/` |
| Liquid stage | 2.2.0 | **2.3.0** (window drops masked, static out-of-focus pieces not liquid, volumes) |
| Runs in the fit | 31 of 33 | **21** (10 pressure-limited runs out; their own section) |
| No spray (< 2% atomised) | treated as spray | C3, C5: size and steadiness not reported |
| Orifice coding | linear in mm | **ln(mm)** |
| Goals | atomised max ×3, mean diameter min ×2, count CV min ×1 | the same |

Made headless with the tab's own calls (`rsm_publish.publish`): the script is
`2026-10-13_CCD_reanalysis/reanalyse_ccd.py`. Open the folder in the app to see the same model.

## What changed in the data

The 2.3.0 liquid stage moved atomised fraction in 10 runs, every one up: the liquid it stopped counting
was a drop on the window. The other 23 runs moved by less than 0.1.

| Run | Before | After | Cause |
|---|---|---|---|
| C20 (142150) | 5.96 | 10.51 | 133 static out-of-focus pieces: the blob in the background median |
| C9 (123534) | 8.84 | 16.38 | 2 drops landed mid-run (2% of the frame) |
| 145702 | 8.18 | 12.18 | 1 window drop and 348 static pieces |
| 142743 | 10.81 | 15.08 | 2 window drops |
| C6 (113920) | 14.41 | 19.88 | 83 static pieces |
| C2r2 (124131) | 15.51 | 19.33 | 2 window drops |
| C4 (112619) | 17.00 | 19.02 | 1 window drop and 24 static pieces |
| 130918 | 16.53 | 18.70 | 2 window drops |
| 143939 | 13.81 | 14.47 | 1 window drop |
| 135146 | 15.64 | 15.87 | 31 static pieces |

## What the re-analysis says

**1. In the flow-controlled region, atomised fraction depends on gas and orifice only.**

- The simplified surface: 15.8 + 2.10 (gas) − 2.37 (orifice, ln scale), in coded units.
- R² 0.92, **predicted R² 0.89**, no lack of fit (p = 0.41).
- **Rotation and feed have no detectable effect** while the gas gets through: rpm +0.22 (p = 0.62),
  feed −0.54 (p = 0.25).

The first analysis had predicted R² 0.62 (simplified 0.78) and significant lack of fit (p = 0.032).
It said atomised fraction "rises with rpm, falls with silicone". Both effects came from the 0.5 mm
block, where rpm and feed decide how much gas gets through (point 5).

**2. Volume-based atomised fraction and atomised liquid flow agree.**

| Response | Simplified predicted R² | Depends on |
|---|---|---|
| Atomised fraction by volume | 0.87 | same factors as by area |
| Atomised liquid flow index (area) | 0.91 | gas, feed, orifice; rises with feed, because more liquid goes in |

Atomised liquid flow was missing from the first analysis (the bug-6 path).

**2b. Droplet production rate (mass balance, added after phase 8; opt-in).**

| Response | Depends on | Simplified predicted R² |
|---|---|---|
| Droplets produced per second in the 30–50 µm band | gas (+), feed (+), orifice (−) | **0.93**, no lack of fit (p = 0.92): the best-modelled response of the day |
| In-focus droplets per frame, total (the concentration) | feed only; no gas effect | 0.75 |

The rate matches the phase-8 hand calculation to within rounding. So a count goal would have missed
gas; the rate goal does not.

**3. Size.**

- **D32 falls with gas**, with a usable surface (predicted R² 0.65). In the first analysis it was 0.04.
- **Mean diameter has no usable surface** (0.19, in both analyses). The spraying runs span only
  38.1–42.6 µm, which is about the noise, so the goal on it is set but cannot steer.

**4. Best setting: about 10,700 sccm on the 1.2 mm insert.**

- Predicted atomised fraction 20.0% (95% PI 17.9–22.0). That is the best seen among the
  flow-controlled runs (125754, 11,000 sccm, 20.0%), not beyond it.
- **rpm and feed are free:** no goal surface in use depends on them, so they are shown at the
  centre (500 rpm, 4,000 steps/s). Choose them for another reason. Feed raises atomised liquid flow
  without hurting the fraction, so the throughput argument is for high feed.
- **1.2 mm is the edge of the fitted span.** The 0.8 mm check (151407) gave 20.2%, below the ln-scale
  extrapolation of 23.0 (PI 20.7–25.3, flagged as extrapolated). So atomised fraction flattens below
  1.2 mm. The curve (orifice²) can't be estimated from 1.2 and 1.8 alone.
- The first analysis's best setting was 11,000 / 900 rpm / 3,000 / 0.5 mm. That is a pressure-limited
  corner, chosen by a surface that did not describe it.

**5. The pressure-limited 0.5 mm block** (own section; a main-effects fit on its 10 runs):

| Effect (per half-range) | Gas delivered | Atomised fraction |
|---|---|---|
| Gas set point | +206 sccm (p = 0.21) | +0.4 (p = 0.42) |
| Bubbler rpm | **+741 sccm** (p = 0.002) | **+8.3** (p < 0.001) |
| Silicone feed | **−1,960 sccm** (p < 0.001) | **−8.9** (p < 0.001) |

- **The set point does nothing.** Rotation and a low feed let more gas through the choked orifice, and
  that gas sets the atomisation.
- **The two best atomised fractions of the day are here:** C7 (115412) at 35.2% and C8 (122239) at
  34.3%. Both are 0.5 mm, 900 rpm, feed 3,000, delivering 5,370 / 5,522 sccm and settled. They are
  reproducible across set points 7,000 / 11,000. The flow-controlled runs top out at 20%.
- So the small orifice at its pressure ceiling is a real, competitive recipe. A model on set gas
  can't see it, and it needs its own experiment (point 8).

**6. Controls.**

- **0 rpm (132817):** 19.16% against centres 17.74 ± 1.2 (+1.2 SD), inside its PI (16.1–20.2). With
  the gas getting through, **stopping the bubbler costs nothing measurable.**
- In the first analysis the 0 rpm run sat outside its PI (predicted 12.9), because the surface's rpm
  effect was borrowed from the 0.5 mm block.

**7. Comparison: the 0.5 mm block kept in, fitted at the gas it got** (`limited = delivered`; scratchpad
only).

- Gas stops being significant for atomised fraction, and rpm takes its place.
- The best setting moves to 10,920 / 900 rpm / 3,000 / 0.79 mm, a blend of two regimes.
- The 34–5,500 sccm delivered at 0.5 mm codes far outside the 7,000–11,000 design range, and gas is
  aliased with orifice. The predicted R² values look good (31 runs) but describe neither regime.
- This is why "pressure-limited out, own section" is the default.

## Found and fixed while re-analysing (code, with tests)

1. **The goal gate judged the wrong model.**
   - Goals were dropped on the *full* quadratic's predicted R², but the maps and the best setting use
     the *simplified* model.
   - With 21 runs for 14 terms the full model's leave-one-out predictions are all high-leverage
     extrapolations: atomised fraction read −0.28 full against 0.89 simplified. So every goal was
     dropped and the report said "optimises nothing only".
   - Now the gate, headline and deck use the simplified model's predicted R² and say so.
   - Caveat: its terms were chosen on the same runs, so the figure is somewhat optimistic.
2. **"Strengthen the model" runs were all 0.5 mm.**
   - On the ln scale fitted to 1.2–1.8, 0.5 mm codes to −4.3, so its prediction variance wins every
     D-optimal pick. It was also pressure-limited in all 10 runs.
   - Candidates now stay inside the fitted span, and the text says which sizes were held back and why.
     It also says that orifice² needs a third size in the next design.
3. **Free factors were reported as edge optima.**
   - A factor in none of the steering surfaces got the optimiser grid's first value (rpm 100, feed
     3,000, "on the edge"). That then moved the suggested next CCD on no evidence.
   - Such factors are now held at the centre and named as free.
4. Wording: "the best setting optimises nothing only" is now "no best setting: …".

## Caveats

- **21 runs and 14 terms leave 7 residual df** (5 pure error, 2 lack of fit), so the tests are thin.
- **Orifice is confounded with time of day.** Each insert was one block, changed 3 times.
- **Every count-based number is a concentration.** Phase 8 found gas speeds the liquid up in
  proportion to its flow. So "in-focus droplets per frame" and the band count under-reward gas
  (`2026-10-13_droplet_rate_investigation.md`).
- **"Best runs as measured" ranks on all three goals,** including mean diameter, whose 38–42 µm
  spread is mostly noise. That is why the centre run 135721 (16% atomised, the lowest mean diameter)
  tops it, not C7/C8.

## For Ben

1. **Goals.** Mean diameter can't steer on this day. Swap it for D32 (usable, 0.65) or the band
   count, or drop it, so the best-observed list isn't ranked on noise. Count CV is borderline (0.48).
2. **Next design (flow-controlled):** 0.8 / 1.2 / 1.8 mm, a geometric series that is even on ln d, so
   orifice² is estimable.
   - Gas up to **12,000 sccm**. That is the rig limit (Ben, 2026-10-13: 11,000 was a set point with
     headroom) and already the app's `RIG_LIMITS`. Atomised fraction and the production rate were still
     rising in a straight line at 11,000; e.g. gas 8,000 / 10,000 / 12,000.
   - Run a quick capacity check that 0.8 mm stays flow-controlled at the worst corner (feed 5,000,
     **12,000** sccm). Peak pressure at 0.8 mm was 5.2 barA at 9,000 sccm; scaling with flow gives
     roughly 7 barA at 12,000 before the feed's share, under the 9.5 barA ceiling but not by much.
   - rpm can be dropped as a factor in this regime, or kept as a two-level check.
3. **The 0.5 mm ceiling recipe** (C7/C8: 35%) deserves its own small study. Its factors are feed, rpm
   and the regulator pressure (the rig's real input when choked), not the gas set point. That is
   plan item D6 and the GLR / measured-pressure question (item G, phase 12).
