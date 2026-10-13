# The 33-run CCD day (2026-10-12): what the analysis actually tells us

Written 2026-10-13 (home PC) from the first Response surface Analyse
(`D:\Experiments\Taguchi\CCD\CCD 4-factor 12-10-2026\`, generated 09:13, revision 4001088, sizer 2.2.0),
plus read-only checks of the per-run data and the gas / pressure traces in each `run_summary.xlsx`. It
follows the deck (`rsm_deck.pptx`, 108 slides) section by section. Conditions are named the way the deck
names them (C1 ... C27, in capture order; C2 and C18 have block repeats, C10 is the 1.2 mm centre).

Physics background used throughout:

- **Effervescent atomisation**: gas is bubbled into the liquid upstream of the exit orifice. The two-phase
  mixture is forced through the orifice, and as the gas leaves it expands from the upstream pressure P0 to
  atmosphere, shattering the liquid into ligaments and then droplets. The atomising energy comes from that
  expansion, so it depends on **how much gas there is per kg of liquid (GLR)** and **how far it expands
  (P0 / Pa)**. Standard references: Sovani, Sojka & Lefebvre, "Effervescent atomization", *Prog. Energy
  Combust. Sci.* 27 (2001); Lefebvre, *Atomization and Sprays*. The usual findings: drop size falls and
  atomisation improves with GLR, steeply at first and then with diminishing returns; spray quality depends
  only weakly on the exit orifice size *for a given GLR and pressure*; at low GLR the internal flow becomes
  slug-like and the spray pulses.
- **Two-phase flow through an orifice chokes at a much lower velocity than gas alone.** The sound speed of
  a bubbly mixture (Wood's equation) is only tens of m/s, far below either phase's. So the upstream pressure
  is set by the *mixture* mass flux through the orifice area, and more liquid takes flow capacity away from
  the gas.
- **EcoFlex 00-30 is very viscous** (of order Pa·s; the mixed product is quoted at ~3,000 cP). For a 50 µm
  droplet the Ohnesorge number (viscous vs. surface-tension and inertial forces) is ~100, so breakup is
  ligament / filament thinning rather than clean drop pinch-off. That is why atomised fractions are tens of
  per cent rather than near 100%, and why the model's "filament" class exists.

---

## 0. Read this first: the 0.5 mm block did not get its gas

The single most important fact about this day is **not in the deck at all**. In every one of the ten 0.5 mm
runs, the pressure sat at a ceiling of **9.2–9.6 barA**, and the Alicat could not deliver the set gas flow.
Median gas flow inside the camera window:

| Run | Set gas | rpm | Feed | Delivered gas (camera window) | Atomised % |
|---|---|---|---|---|---|
| 115412 (C7) | 7,000 | 900 | 3,000 | **5,370** | 35.2 |
| 122239 (C8) | 11,000 | 900 | 3,000 | **5,554** | 34.3 |
| 112619 (C4) | 7,000 | 100 | 3,000 | 3,833 | 17.0 |
| 113920 (C6) | 11,000 | 100 | 3,000 | 3,912 | 14.4 |
| 110227 (C2) | 9,000 | 500 | 4,000 | 2,639 | 19.3 |
| 124131 (C2 repeat) | 9,000 | 500 | 4,000 | 2,151 | 15.5 |
| 105301 (C1) | 11,000 | 900 | 5,000 | 2,171 | 20.1 |
| 123534 (C9) | 7,000 | 900 | 5,000 | 716 | 8.8 |
| 113349 (C5) | 7,000 | 100 | 5,000 | **55** | 0.45 |
| 112022 (C3) | 11,000 | 100 | 5,000 | **33** | 0.19 |

Every 0.8, 1.2 and 1.8 mm run got its set point to within ~0.5%. (The "11,7xx sccm" achieved flows
recorded for some 0.5 mm runs are the ramp overshoot before the pressure built up.)

What this means:

- **At 0.5 mm the rig was pressure-limited, not flow-controlled.** Something upstream (the supply or
  regulator setting, or the line) caps P0 at about 9.5 barA, and the orifice cannot pass 7,000–11,000 sccm of
  gas plus silicone at that pressure. The gas set point is therefore meaningless for this block: C7 (7,000)
  and C8 (11,000) received the same ~5,500 sccm and gave the same ~35%.
- **What *did* control the delivered gas at 0.5 mm was the liquid feed and the rpm.** Delivered gas vs. feed:
  r = −0.92. This is two-phase choking: at a fixed P0, every extra gram of silicone takes flow capacity from
  the gas. At feed 5,000 and 100 rpm almost no gas got through at all (C3, C5). The liquid was pushed out
  as an essentially unbroken stream, which is why C3 has ~1 "un-atomised piece" per frame and almost no
  droplets.
- **Rotation let more gas through.** At feed 3,000, 100 rpm passed ~3,850 sccm and 900 rpm ~5,450; at feed
  5,000, 33–55 vs 716–2,171. A plausible reading is that the rotating bubbler breaks the gas into a
  finer, better-mixed bubbly flow that passes the orifice more easily than gas-liquid slugs. That's a
  hypothesis, but the effect is large and consistent.
- **Consequence for the statistics:** the analysis was told these 10 runs had 7,000–11,000 sccm. They
  didn't. That mis-specification is behind much of what looks odd in the deck: the strong RPM × orifice and
  feed × orifice interactions, the orifice curvature, the lack of fit, the negative predicted R² values, and
  the "best setting". Each section below says how.

**Check on the rig:** what sets ~9.5 barA. If the supply can go higher safely, the 0.5 mm insert can be
re-run properly; if not, 0.5 mm is outside the usable range at these flows. (The 0.8 mm check run got its
full 9,000 sccm at 4.8 barA, so 0.8 mm works.)

---

## 1. The design and the models (slides 1–3)

**What it shows:** the app recognised a complete face-centred CCD in 4 factors: 31 fitted runs (16 corners,
10 face centres, 5 centres), with the 0 rpm control and the 0.8 mm check kept out of the fit. The full
quadratic has 15 terms, and there are 6 pure-error df and 10 lack-of-fit df.

**What it means:**
- The design was run exactly as planned; the statistical structure is sound.
- **Orifice is confounded with time of day** (one block each: 0.5 mm 10:53–12:41, 1.2 mm 12:52–13:57,
  1.8 mm 14:10–15:02, 0.8 mm at 15:14). Anything that drifted through the day would show up as an orifice
  effect. The block repeats (section 9) show little drift, which helps, but this can't be ruled out.
- **The pure error comes from 5 centres run back to back within ~65 minutes in one block.** It measures
  short-term repeatability, not true run-to-run noise (the same issue as the 9x3). This is why lack of fit
  is "significant" for most responses even where the surface looks reasonable: the yardstick is optimistic.

---

## 2. Atomised fraction (slides 4–8): the one surface that works

**What it shows:** up with gas flow, up with rpm, down with feed, down with orifice; Orifice² significant;
strong RPM × orifice (−3.5) and feed × orifice (+5.1) interactions. R² 0.93, predicted R² 0.62 (simplified
model 0.78), lack of fit p = 0.03. Its 3D peak is at 0.23 mm, outside the range.

**Where the gas was actually delivered (0.8–1.8 mm), the robust findings are:**

| Effect | Evidence | Size |
|---|---|---|
| **Smaller orifice → more atomisation** | at 9,000 / 500 / 4,000: 0.8 mm 20.2%, 1.2 mm 17.3 ± 1.1% (5 centres), 1.8 mm 13.8% (2 runs) | ~6 points from 0.8 to 1.8 mm |
| **More gas → more atomisation** | 1.2 mm faces: 7,000 → 15.6, 9,000 → 17.3, 11,000 → 20.0; 1.8 mm corners: 7,000 mean 8.9 vs 11,000 mean 14.0 | +4 to +5 points over the range |
| **Feed matters little at 1.2 mm** | 3,000 → 19.6, 5,000 → 17.8 (centre 17.3) | within ~2 points |
| **At 1.8 mm more feed *helps*** | corners: feed 3,000 mean 10.1 vs 5,000 mean 12.8 | +2.7 points |
| **RPM: nothing at 1.2 mm, a little at 1.8 mm** | 1.2 mm: 0 rpm 19.2, 100 rpm 19.0, 900 rpm 18.6 vs centres 17.3 ± 1.1; 1.8 mm pairs, 900 − 100 rpm: +2.2, +4.6, +1.5, +2.2 | 0 at 1.2 mm; +2.6 points at 1.8 mm |

**The physics that ties it together: gas expansion energy per kg of liquid.** The isothermal expansion work
of the gas, per kg of liquid, is

  E = GLR × (R/M) × T × ln(P0 / Pa)

using the gas actually delivered and the pressure in the camera window. **E alone correlates with atomised
fraction at r = +0.83 across all 33 runs** (r² ≈ 0.69), against r = +0.35 for the set-point GLR. Within
the 0.5 mm block, r = +0.87.

- The orifice effect is mostly a pressure effect. A smaller orifice raises P0 (1.6 → 3.1 → 4.8 barA from
  1.8 → 1.2 → 0.8 mm at 9,000 sccm), so each kg of gas does more expansion work. This fits the literature:
  orifice size matters little *at fixed GLR and pressure*, but in practice it sets the pressure.
- It explains why feed *helps* at 1.8 mm: more liquid raises P0 a little (1.45–1.64 → 1.58–1.82 barA) at
  a pressure where ln(P0/Pa) is small and sensitive. At 1.8 mm, af vs P0 gives r = +0.76. At 1.2 mm the
  pressure is already high, so the GLR loss from extra feed dominates instead.
- It explains the 0.5 mm results: high pressure but little gas. The 0.5 mm, 900 rpm, feed 3,000 runs are
  the best of the day (35%) because they combine the highest P0 with the most gas that got through
  (E ≈ 132–136 kJ/kg, the highest of the day).
- **Diminishing returns with GLR:** the CCD sits at GLR 0.53–1.38 (set point), mostly above the 9x3's range
  (0.14–0.84). The gas effect here (+4 to 5 points) is far weaker than in the 9x3 (5 → 17% from 3,000 to
  9,000 sccm). That is the classic flattening of atomisation quality with GLR.

**How much to trust the fitted surface:** the shape near 0.5 mm is wrong. The model's RPM slope and the
RPM × orifice / feed × orifice interactions are largely the gas starvation (rpm and feed controlled the
delivered gas there). The "peak at 0.23 mm" is an extrapolation of that. Within 0.8–1.8 mm the direction
of each effect is right. The 0.8 mm check (20.2% observed vs 18.2% predicted, inside its PI) supports the
orifice trend between the inserts.

---

## 3. Droplet size: D32 and mean diameter (slides 9–18)

**What it shows:** "no usable surface" for D32 (predicted R² −0.86) and mean diameter (−1.40); strong lack
of fit. Mean diameter sits at 39.3 µm with coefficients of ~1 µm.

**What it means:**
- **Where gas was delivered, size barely moves:** mean diameter 38.0–39.7 µm and D32 53.5–57.9 µm across
  every 0.8–1.8 mm run. The only consistent trend is the expected GLR one: at 1.8 mm the 7,000 sccm runs
  have D32 57–58 µm against 53.5–56 µm at 11,000 (mean diameter vs set GLR r = −0.31 off the 0.5 mm block).
- **The 0.5 mm runs are bigger** (mean 39.5–42.6 µm, D32 54–64.5 µm) because they had less gas per kg of
  liquid. Low GLR gives coarser sprays.
- **Why the fits fail:** two starved runs are extreme, high-leverage points: C3 has a mean diameter of
  26.9 µm from only 3.7 droplets per frame, a meaningless number, and C5 is similar. A smooth quadratic
  cannot follow them, and leaving each one out in turn (what predicted R² does) breaks the prediction, hence
  the negative values. Against the tiny pure error (centre SD 0.55 µm), any misfit reads as lack of fit.
- **Measurement limits compress size:** at 10 µm/px, a 39 µm mean is ~4 px across. The median diameter
  lands on the pixel lattice (35.68 µm in most runs). The sharpness rule (2.2.0) keeps only round, sharp
  droplets, and the 200 µm ceiling caps the top. So the size responses have little room to move: differences
  of 1–2 µm are near the method's resolution. The physics says sizes *should* shrink with GLR and with
  expansion energy; this method can only just see that at these settings.
- **Practical reading:** in the usable range (0.8–1.8 mm, full gas), droplet size isn't a lever.
  Atomised fraction is the response that discriminates settings.

---

## 4. Steadiness and pulsing: count CV and lag-1 correlation (slides 19–28)

**Droplet-count CV** (spread of droplets per frame / mean): "no usable surface". Off the 0.5 mm block it is
nearly flat at 0.36–0.45 (one run 0.57). The fitted "falls with orifice" is driven by the starved 0.5 mm
runs (C5 = 1.56).

**Lag-1 correlation** (how much each frame's droplet count resembles the next at 39 Hz: a slow-pulsing
spray has high lag-1): an excellent fit (R² 0.95, predicted 0.78, no lack of fit). It is **almost entirely an
orifice effect**:

| Orifice | Lag-1 range | Reading |
|---|---|---|
| 0.5 mm | 0.35–0.80 | strong slow pulsing |
| 0.8 mm | 0.22 | mild |
| 1.2 mm | −0.02–0.20 | steady |
| 1.8 mm | 0.04–0.47 | steady at high gas, pulsing at 7,000 sccm |

**Physics:**
- At 0.5 mm the gas flow inside the camera window swings hard: the minimum is 400–1,150 sccm against medians
  of 2,000–5,500. With P0 pinned at the ceiling, the flow alternates between liquid slugs blocking the
  orifice and gas bursting through. That is the slug / intermittent regime described for effervescent
  atomisers at low effective GLR, made worse here by the pressure limit. So pulsing at 0.5 mm is a
  **rig-limited** behaviour, not necessarily intrinsic to that orifice.
- At 1.8 mm the pulsing runs are the low-gas ones (C26 at 7,000 sccm: 0.47), at the lowest pressures of the day
  (1.4–1.6 barA). Their droplets per frame follow the logged pressure (r up to +0.66, slides 58–66). This is
  the same low-GLR, low-pressure sensitivity the 9x3 found at 3,000 sccm, and it matches the 9x3's view that
  the upstream pressure oscillation (~0.2–0.8 Hz) drives the spray when there is little expansion energy to
  smooth it.
- 1.2 mm at ~3 barA is the steadiest place in this design.

---

## 5. Peak pressure (slides 29–33)

**What it shows:** R² 0.998, Orifice and Orifice² only; minimum at 1.8 mm.

**What it means:**
- At 0.5 mm the "peak pressure" is the ~9.5 barA **ceiling**, not a property of the spray. That flat top
  is part of why the quadratic fits so tightly and why gas flow seems to have no effect on pressure.
- Off the ceiling the pressure does what two-phase choking predicts: at 1.2 mm it rises with gas
  (7,000 → 2.8, 9,000 → ~3.05, 11,000 → 3.3 barA) and with feed (3,000 → 2.8, 5,000 → 3.3); at 1.8 mm the
  same, smaller (1.4–1.8 barA).
- Pressure vs orifice is strongly non-linear (roughly with 1/area), which a quadratic in diameter
  forced through the capped 0.5 mm point represents badly. That is why the **0.8 mm check missed its pressure
  PI** (5.2 barA peak vs 6.3 predicted). Fitting orifice as area, or 1/d², would describe it better.

---

## 6. Best settings: desirability, profiler, peaks (slides 34–39)

**What it shows:** D = 0.99 at 11,000 sccm / 900 rpm / feed 3,000 / 0.5 mm, every factor on an edge.

**What it means:**
- **This "best" setting is atomised fraction alone.** Atomised liquid flow had no values (a software bug on
  this PC: the Python 3.9 env cannot import the capture GUI's flow formula; see STATUS, Taguchi app bug 6),
  and mean diameter and count CV were excluded as unusable surfaces. A fraction-only goal always favours the
  lowest feed (the guide warns about this).
- **"11,000 sccm at 0.5 mm" is not a setting the rig can deliver at the current supply pressure:** the run
  at exactly that setting (C8) received ~5,550 sccm. The real best condition of the day is "0.5 mm, 900 rpm,
  feed 3,000, with whatever gas ~9.2 barA lets through".
- **Atomised liquid flow, worked out by hand** (feed mL/min × atomised fraction, the GUI's own formula: bore
  20.27 mm, 6,800 steps/mm):

  | Run | Setting | Atomised % | Atomised liquid flow (mL/min) |
  |---|---|---|---|
  | C7 / C8 | 0.5 mm, 900 rpm, feed 3,000 (5,400–5,550 sccm delivered) | 35.2 / 34.3 | **3.0 / 2.9** |
  | C1 | 0.5 mm, 900 rpm, feed 5,000 (2,170 delivered) | 20.1 | 2.9 |
  | C12 (130400) | 1.2 mm, 9,000, 500 rpm, feed 5,000 | 17.8 | **2.5** |
  | 151407 | 0.8 mm, 9,000, 500 rpm, feed 4,000 | 20.2 | 2.3 |
  | 145142 | 1.8 mm, 11,000, 900 rpm, feed 5,000 | 16.1 | 2.3 |
  | 1.2 mm centres | 9,000 / 500 / 4,000 | 17.3 | 2.0 |

  Throughput is much flatter than atomised fraction: 2–3 mL/min of atomised silicone across most good
  settings. Higher feed loses fraction but gains flow. With the flow goal restored, the best setting is
  likely to move to higher feed.
- **Where each surface peaks (slide 39):** almost every row reads "held: no curve" for gas, rpm and feed.
  Only orifice curves. See section 11 for what "no curve" means.

---

## 7. Recommended next runs (slides 40–43)

All four recommendations come from the mis-specified 0.5 mm block, so **don't run them as they stand**:
- *Confirm* 11,000 / 900 / 3,000 / 0.5 would really run at ~5,500 sccm and should reproduce ~35%. It
  confirms the run, not the model.
- *Steepest ascent* (11,200 / 1,000 / 2,600) and the *new CCD* (gas 8,000–12,000) push gas set points that
  0.5 mm cannot pass at this supply pressure.
- *Strengthen the model* picks four more 0.5 mm runs (D-optimal), which would be gas-starved too.

Re-analyse first (section 12), then take recommendations from the corrected fit.

---

## 8. The 0 rpm control (slide 44)

**What it shows:** the 0 rpm run gave 19.2% against the centres' 17.3 ± 1.1 (+1.7 SD), and the model
predicted 12.9 (outside its PI).

**What it means:** at 1.2 mm, 9,000 sccm and feed 4,000, **rotation made no measurable difference**:
0 rpm 19.2, 100 rpm 19.0, 500 rpm 17.3 ± 1.1, 900 rpm 18.6. The model's prediction is low because its rpm
slope was learned from the 0.5 mm block (where rotation changed the delivered gas) and the 1.8 mm corners.
The control isn't the odd one out; the model is. Size and CV at 0 rpm were also indistinguishable from the
centres.

Physically, at ~3 barA the pressure drop through the orifice probably mixes the two phases enough on its
own. Rotation may matter where that isn't true: at 1.8 mm (low pressure, +2.6 points from 100 → 900 rpm)
and at 0.5 mm (where it let gas through). This is a hypothesis; only one 0 rpm run exists. A 0 rpm run at
1.8 mm would test it directly.

---

## 9. Drift, lack of fit, validation (slides 45–47)

- **Drift:** 1 of 12 block-repeat differences beyond ±2 SD (about what chance gives); no residual trend with
  time. The 1.8 mm block repeats agree (13.5 vs 14.2%). The 0.5 mm pair differs (19.3 vs 15.5%), but it also
  received different gas (2,639 vs 2,151 sccm): starvation again, not drift. So no evidence that time of
  day biased the orifice effect, within the limits of 3 pairs.
- **Lack of fit:** see sections 1 and 3: an optimistic pure error (centres back to back) plus
  mis-specified gas at 0.5 mm. Lag-1, liquid-area CV, frames below half the mean and peak pressure show none.
- **Validation runs:** the 0.8 mm check landed inside its PI for every spray response (atomised 20.2 vs
  18.2; D32 55.4 vs 55.7; mean diameter 40.3 vs 39.1), which is good evidence the orifice trend interpolates
  between the inserts. It missed only on pressure (section 5).

---

## 10. The appendix (slides 49–108)

Most of the appendix "headline" extremes are the starved 0.5 mm runs, so read the titles with section 0
in mind:
- **Slides 52–55 (size distributions, Dv50, span):** "99% of C3's droplets below 50 µm", "43% of C3's
  liquid in droplets above 125 µm", "Dv50 47.4 (C3) to 69.9 µm (C9)", "span widest at C3" all come from
  runs with almost no gas (C3: 33 sccm, ~4 droplets per frame; C9: 716 sccm). They describe a failed spray,
  not a size trend.
- **Slide 51 (atomised fraction vs GLR, r = +0.35):** weak because the set-point GLR is wrong for the 0.5 mm
  block. With the delivered gas and the pressure (expansion energy) it is r = +0.83 (section 2).
- **Slides 56–57 (pulsing spectra):** strongest at C5 and C3 (starved 0.5 mm), peaking near 0.8 Hz:
  the gas-flow / pressure ceiling oscillation.
- **Slides 58–66 (droplets vs pressure through each capture):** the spray follows the pressure most at low
  gas on the large orifice (C19, C26: r +0.66, +0.61) and at 0 rpm (C15: +0.56). Low expansion energy means
  the spray is at the mercy of the supply oscillation.
- **Slides 67–75 (liquid area burstiness, CV 0.9–1.4):** liquid arrives in bursts at every setting (CV
  near 1), as the 9x3 found: individual slugs pass in < 25 ms, faster than the 39 Hz frame sampling can
  resolve.
- **Slide 80 (un-atomised pieces):** most at C25 (1.8 mm, 11,000, 900 rpm, feed 5,000: lots of liquid,
  broken into many un-atomised pieces), fewest at C3 (~1 per frame: one continuous stream, nothing broken
  up).
- **Slide 50 (replicates within 6% median CV)** and **slide 81 (15 runs flagged on data quality):** worth a
  look for splash or static-speck flags, as on 10/05.
- **Galleries (82–108):** the lowest- and highest-atomised frames of every condition. C3 and C5 are worth
  looking at as the picture of "no gas".

---

## 11. "No curve": does it mean the best results are outside the range?

Partly, and in a useful way:

- **A significant squared term means a surface bends**, so its peak (or trough) can sit inside the range.
  When a factor is "a straight line", the best value along it is at whichever edge it slopes towards. That
  is what "held: no curve" means, and why the best setting is on the edges.
- **That doesn't automatically mean "go further"**. Within this range, gas, feed and rpm had modest,
  roughly linear effects (and rpm almost none at 1.2 mm). For gas, the physics predicts flattening (diminishing
  returns with GLR), and the move from the 9x3 (steep) to the CCD (gentle) already shows it. Beyond 11,000
  sccm you'd expect small gains at higher pressure and cost, and the rig limit is 12,000.
- **Orifice is the factor that does curve** (and it drives pressure), and the real gain is at the small end:
  0.8 mm gave 20.2% at full gas. The 0.5 mm result says smaller orifice plus high pressure is even better
  *if* the gas can be delivered.
- **A curve isn't the goal in itself**. For a process you want a region where the response is high *and*
  insensitive to small changes (flat near the top), which a curved peak gives you. A straight-line result is
  still a result: it tells you the direction to move and where you hit a constraint (here, supply pressure,
  then the 12,000 sccm limit).

---

## 12. What to do next

1. **Rig:** find what caps P0 at ~9.5 barA. Decide whether 0.5 mm is in scope (needs higher supply pressure)
   or out (then 0.8 mm is the small end).
2. **Software:** fix bug 6 (one line in `GUI_Clean.py`), so atomised liquid flow is computed on this PC,
   then re-Analyse with the flow goal back.
3. **Re-analyse in the app, two ways**, and compare:
   - (a) **without the 0.5 mm block** (untick its 10 runs): an honest 3-factor surface at 1.2 / 1.8 mm, with
     orifice as a block / nuisance term and 0.8 mm as the check.
   - (b) **all runs with the delivered gas typed in** for the 0.5 mm runs (Design page, gas cell = the
     camera-window median in section 0). The design becomes irregular, but the fit uses real values, and the
     RPM / feed / orifice interactions should shrink once gas is right.
4. **Treat the 0.5 mm block as its own finding:** at a pressure ceiling, delivered gas falls with liquid
   feed (r −0.92) and rises with rotation. That is a measurement of the atomiser's two-phase flow capacity.
5. **Cheap physics follow-up:** expansion energy per kg of liquid (r = 0.83 with atomised fraction across
   all runs) is a candidate one-variable correlate for the thesis. It needs P0 recorded reliably (it is) and
   the delivered gas (from the Alicat trace, not the set point).
6. **Rotation:** one 0 rpm run at 1.8 mm, and a repeat of the 0 rpm run at 1.2 mm, would tell whether the
   bubbler helps only at low pressure.

---

## 13. Handover: everything else from the 2026-10-12/13 home-PC session, and the Mac to-do

### What happened on the home PC

- **Data check before the batch:** all 33 runs in `D:\Experiments\2026\10\12\`, each with one 13.93 GB cine
  and a `run_summary.xlsx`; all "complete", 390 fps, bh 0.5, Notes "CCD run 1..33 <type>" in capture order.
  The app detected a complete 4-factor CCF with no missing or extra points and no Notes conflicts.
- **Run 33 (151407, 0.8 mm check) is a valid run.** The GUI's stall check false-tripped on it ("stalled at
  66 RPM"). Ben confirmed it ran normally and removed the label: run_summary says "complete" with RPM 500,
  and master_log is clean. The analysis app never reads Run status. Logged as a GUI_Clean known bug (false
  stall trip, cause not investigated).
- **python-pptx 1.0.2 installed** in the home PC's Detectron env (plus lxml 6.1.3 and XlsxWriter 3.2.9; numpy
  untouched at 2.0.2). The lab PC still needs it.
- **Batch:** 33/33 ok, all sizer 2.2.0, 18:13 → ~05:05 (7.9–36 min per run, median ~19 min). Output and job
  folder: `D:\Experiments\Taguchi\CCD\CCD 4-factor 12-10-2026\`, i.e.
  `/Volumes/LaCie/Experiments/Taguchi/CCD/CCD 4-factor 12-10-2026/` on the Mac.
- **Analyse took ~5 min on this PC** (09:09–09:14), including filling the per-run cache.
- **csv/ and odd/ ticks:** only the Taguchi tab's Analyse reads them. The Response surface Analyse always
  writes `rsm_results.csv` and `rsm_analysis.xlsx`, and never an odd-frame pack.
- **Contour map colours** follow the response value (dark = low, yellow = high), not the goal. For a
  minimise goal the good region is dark. Only the desirability maps are oriented "bright = better". Ben is
  happy with that (no change).
- **Goals advice:** leave "In-focus droplets per frame" as Not a goal. It double-counts size and
  throughput, and the sharpness rule moves more droplets out of focus at high gas. Droplet-count CV
  (in-focus count SD / mean per frame) is the steadiness goal (minimise). The deck's "count CV" Terms text
  and the Steadiness appendix use the all-droplet version: same idea, slightly different numbers.

### Two app bugs found (both in STATUS, "Known bugs", Taguchi_Analysis_UI 3 and 6)

- **Bug 3, stale run list after a batch.** The Batch tab reads each run's "measured?" state once, when runs
  are added, and never again: `pane_runs` only reloads on a settings change, and "+" skips runs already in
  the list. So an Analyse in the same session as the batch skipped all 33 runs as "not measured yet" and
  refused. Workaround used: Batch tab → Clear → add the day folder again → Analyse. **Fix:** reload the run
  list (`pane_runs._reload_runs()`) when the batch finishes, with a test.
- **Bug 6, no atomised liquid flow on Python 3.9.** `covariates._gui_formula` imports `GUI_Clean` for the
  GLR / mL/min formula. `GUI_Clean.py:72` imports `Trials/Cone_4.py`, whose `int | None` annotations raise
  TypeError on Python 3.9, and the guard at `GUI_Clean.py:74` catches only ImportError. So the import fails,
  `liquid_ml_min` is None, "Atomised liquid flow" has no values ("No fit"), and the throughput goal silently
  drops out of the desirability. **Fix:** `except ImportError:` → `except Exception:` at `GUI_Clean.py:74`
  (the cone detector is optional), and arguably make the analysis say loudly when GLR / mL/min can't be
  computed, instead of silently dropping a default goal. The Mac is probably unaffected (the 9x3 trials on
  the Mac had atomised liquid flow), but check that it has values after re-Analyse. The per-run cache key
  includes `liquid_ml_min`, so the cached runs recompute by themselves once the value exists; no need to
  delete `cache/`.

### Mac to-do, in order

1. Pull `Testing` (this note and STATUS come with it once pushed from the home PC).
2. Fix bug 6 (`GUI_Clean.py:74`) and bug 3 (`pane_runs`), with tests. Run the suite:
   `/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m pytest /Users/benschofield/Documents/GitHub/HPATR/src/ai/Taguchi_Analysis_UI/tests -q`
3. Decide how the app should handle a run whose delivered gas differs from its set point. The camera-window
   median flow is already in `run_summary.xlsx` → `Pressure` (`flows_sccm` between `cam_start_1` and
   `cam_end_1`). Options: warn on the Design page when delivered differs from set by > ~5%; offer "use the
   delivered gas" as the factor value; or flag the run as pressure-limited. The 0.5 mm block is the test
   case.
4. Launch the app and re-analyse the CCD (output folder above), two ways, into **separate output folders** so
   neither overwrites the first analysis:
   - (a) the 0.5 mm block unticked (23 fitted runs + the 0 rpm control + the 0.8 mm check);
   - (b) all runs, with the gas cell of each 0.5 mm run set to its delivered flow (section 0 table).
   Keep atomised liquid flow as a goal. Compare the best settings and the recommendations.
   Launch: `cd /Users/benschofield/Documents/GitHub/HPATR && /Users/benschofield/anaconda3/envs/phantom/bin/python3 -m src.ai.Taguchi_Analysis_UI`
   (the design saved in the output folder has the home PC's `D:\` run paths: re-detection on the Mac is fine,
   but any Validation ticks won't carry over).
5. Optional, worth it for the thesis: add expansion energy per kg of liquid
   (GLR_delivered × (R/M) × T × ln(P0/Pa)) as a covariate next to GLR, computed from the delivered gas and the
   camera-window pressure.
6. Rig, before the next session: find what caps P0 at ~9.5 barA. Decide whether 0.5 mm is in scope. If not,
   0.8 mm is the small end, and a new design would use 0.8 / 1.2 / 1.8 or similar.
7. Lab PC: install python-pptx (STATUS next step 5).

### Open questions for Ben

- What sets the ~9.5 barA ceiling (regulator setting, bottle, line, Alicat inlet)? Can it safely go higher?
- Should 0.5 mm stay in the study at all?
- Does the false stall trip on run 33 need fixing in GUI_Clean before the next session?

---

Numbers in sections 0, 2, 6 and 8 that are not in the deck come from read-only checks run on 2026-10-13: the
camera-window medians of `run_summary.xlsx` → `Pressure`, the GUI's GLR formula, and the per-run values in
`rsm_results.csv`. Nothing on the LaCie was changed.
