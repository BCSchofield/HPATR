# Response-surface (CCD) experiments: what to do, step by step

This is the guide the Response surface tab of the Experiment Analysis app shows (Guide panel). It covers
planning a central composite design (CCD), running it, and getting it analysed.

> **What is built so far (2026-10-11):** building the run sheet (step 1), detecting the design (step 3)
> and the whole analysis (step 5: fits, contour maps, 3D surfaces, profiler, desirability, fit checks,
> drift, controls, validation runs, report, workbook, CSV and deck) work, as code with tests, and have
> been run on the 9x3 practice copy and on a simulated 33-run day, and so does the recommender for the
> next session (step 6), all from the Response surface tab. The Taguchi tab is unchanged and works as
> before.

## Using the app

Launch it (Mac):

```
cd /Users/benschofield/Documents/GitHub/HPATR && /Users/benschofield/anaconda3/envs/phantom/bin/python3 -m src.ai.Taguchi_Analysis_UI
```

1. **Batch tab**: add the run folders (a day folder, or a parent of several) and tick the runs; choose an
   **output folder** (everything is written there, never into a run folder). Runs need measuring first
   (Run batch) unless they already are.
2. **Response surface tab → Design**: the banner says what the runs form. Check the table: every run's
   point type, block and levels; untick a run to leave it out; tick **Validation** to keep a run out of
   the fit and predict it instead; type in a factor cell to correct a level. Findings below say what is
   missing, what is confounded with time, and whether the quadratic can be fitted.
3. **Model**: each factor's role (surface factor = mapped; nuisance = kept in the model, not mapped; left
   out), the levels that can actually be set (orifice inserts), the goals for the best setting, and
   whether to also fit without the nuisance factors to compare.
   **Goals** steer only the best setting and the next runs (not the fits or maps). Each response scores 0
   at **worst** and 1 at **best** (Maximise: worst below best; Minimise: worst above best; Hit a target:
   best is the target and the score falls to 0 as far either side as worst is). A blank **worst** is the
   worst run seen; a blank **best** is the best the fitted surface reaches inside the tested region (changed
   2026-10-13: with the best RUN as the end, every setting predicted beyond it scored a flat 1, so the
   optimiser could not tell them apart and stopped at the first it tried, e.g. feed 3,000 when maximising a
   production rate that rises with feed). **Importance** weights the goals (all 1 = equal; e.g. atomised fraction 3, mean diameter 2).
   **Droplet count in a size band** ("In-focus droplets per frame in the size band", band in Settings,
   default 30–50 µm): maximise it to favour settings that make MANY droplets of the size you want, not
   just droplets of that size. It is a per-frame concentration, and it overlaps with atomised fraction and
   flow; give it a lower importance if all three are goals. **Droplets produced per second** (all sizes, or
   in the band; "mass balance (estimated)") is the RATE version: syringe flow × atomised fraction by volume ÷
   mean droplet volume. Unlike the per-frame count it does not drop when the gas speeds the spray up, so use
   it instead of the count when gas flow is a factor; it rests on the volume estimate. **Atomised fraction
   by volume** is secondary: use the area fraction as the headline.
   **"No spray" runs**: a run below the Settings tab's no-spray threshold (default 2% atomised) is a
   dribble; its droplet size and steadiness are left out of those fits (it stays in atomised fraction,
   droplet count and the liquid responses), so a minimise-size goal cannot be won by a run that barely
   sprays. The report names such runs at the top.
   The default goals: maximise atomised fraction and atomised liquid flow, minimise droplet-count CV and
   mean diameter (the size goal; D32 is mapped and reported but not a default goal). Set them
   before the first Analyse or change them later and press Analyse again; they are saved with the output.
   Goals that measure the same thing stack: D32, mean diameter and D90 all say "smaller droplets", so
   choosing all three triples the weight on size. Pick one per thing you care about. And a fraction goal
   alone (atomised %) rises as the liquid flow falls: keep **atomised liquid flow** as a goal if
   throughput matters, or the best setting drifts to the lowest feed. Both are **by projected area**
   (labelled so since 2026-10-13): atomised liquid flow is the syringe mL/min × the area fraction, an
   index for comparing runs, not a measured flow of droplets (`docs/definitions.md`). If the app cannot
   compute it (the capture GUI's flow formula would not import), the Model page marks the row
   "unavailable" and the report and console say so at the top: a goal on it would otherwise be dropped
   without a word.
   **Runs that did not get their set gas** (Model page): when the rig hits the supply pressure ceiling
   (Settings, default 9.5 barA), a run's gas can fall far below its set point once the silicone reaches a
   small orifice (the 0.5 mm block on 2026-10-12). The Design page's *Gas delivered* column shows what each
   run got (⚠ = not its set point). By default such runs are **left out** of the surfaces and described in
   their own report section, with a test of what controlled their gas there; *Fit them at the gas they
   got* moves their gas factor to the measured flow (low gas then exists only at that orifice, so the two
   cannot be separated); *Keep them at their set point* is the old behaviour.
   **Log scale** (Model page, per factor; on by default for the orifice): the factor is fitted on
   ln(value). The inserts 0.8 / 1.2 / 1.8 mm are a geometric series (×1.5), so they are evenly spaced only
   on a log scale, and the pressure goes roughly as a power of the diameter. Maps, the best setting and
   the next runs stay in mm. **Fitted span**: when runs are left out (e.g. a pressure-limited 0.5 mm block),
   each factor's coding follows the runs actually fitted, so the surface and the best setting stay inside
   them (orifice 1.2-1.8 mm, not 0.5-1.8); settable levels outside that span are not offered as the best
   setting and the report says which.
   **Which goals were used**: a goal is left out of the best setting when its surface cannot predict a new
   run (predicted R² of the simplified model, the one that is mapped and optimised, below 0.5) or it has no
   values; the report's Best settings table lists every goal you
   set, used or not, and why. It also lists the **best runs as measured** (your goals scored on each run's
   observed values, every run counted), so a good run the surface cannot describe still shows.
4. **Analyse and next runs**: press **Analyse**; then **Open deck**, **Open report**, **Open next runs**.
   A proposed run whose predicted peak pressure reaches the supply ceiling is flagged in the *Pressure
   check* column: it would probably be pressure-limited.
   The recommendations for the next session are listed with their reasons.
5. **Build a run sheet** (before a new experiment): type the factors and levels (or **Load the 33-run
   example**), **Build**, check the preview and summary, **Export run sheet to the output folder**. Once
   that day's runs are captured, the Design page shows each run against its row (as planned, out of
   order, settings differ, not captured yet).

Your edits (design, model choices) are saved in the output folder and come back next time.

**Practice on the 9x3:** add `/Volumes/LaCie/Experiments/Taguchi/Claude Experiments/Practice Folder/2026`,
choose a new folder under `Practice Folder/output/` as the output, open the Response surface tab. It is
an L9, so the Model page defaults to gas × feed as the surface with RPM as a nuisance term and the
comparison fit ticked (the 9x3 trial). Press Analyse (about 40 s).

## The idea in one paragraph

A response-surface experiment places runs so that a **curved surface** can be fitted through the results:
for every factor a slope and a curve, and for every pair of factors an interaction. The fitted surface
shows where the best settings are, including between and slightly around the settings you ran, rather
than just which run was best. A **face-centred CCD** does this with three levels per factor and three kinds
of run: corners, face centres and repeated centres.

## Step 1: build the run sheet (before the day)

You give the factors and their levels; the app lays out the runs, orders them, and writes the sheet.

### Factors

Choose 2 to 5 things to vary. The built-in ones are gas flow (sccm), bubbler RPM, silicone feed (steps/s),
exit orifice (mm) and bubbler height (mm); any field in run_summary.xlsx can be used too. Everything else
should be held fixed and recorded (bubbler, silicone, camera position and settings).

More factors cost runs quickly: 3 factors = 8 corners + 6 faces + centres (about 19 runs); 4 factors =
16 + 8 + centres (about 29); 5 factors = 32 + 10 + centres (about 47), or about 31 with a half fraction.

### Low, middle and high levels

For each factor give three real values. They become the design's **coded levels**:

| You type | Coded | Meaning |
| --- | --- | --- |
| Low | −1 | the bottom of the region you want the surface to cover |
| Middle | 0 | the centre: where the centre runs and the face points of the other factors sit |
| High | +1 | the top of the region |

- **The region is the box between low and high.** The fitted surface is trustworthy inside it and
  increasingly not outside it. Put low and high where you would still be willing to run, and where the
  answer might plausibly be.
- **Stay inside what the rig can do at every corner**, not just on its own: a corner combines extremes
  (e.g. high gas with the smallest orifice), which is the hardest case for pressure. Use the first-run
  pressure check (below).
- **Uneven middles are fine** (orifice inserts 0.5 / 1.2 / 1.8 mm). The design still treats 1.2 as the
  middle; the fit uses the real spacing (1.2 mm sits at +0.08 on a −1..+1 scale), and the sheet says so.
- Levels must be strictly low < middle < high.

### Centre runs (default 5)

Repeats at the middle of every factor. They give the **run-to-run noise** (pure error), the check for
**curvature** (whether the middle sits off the straight line between low and high), and, spread through
the day, a check for **drift**. Keep at least 3; 5 is the usual.

### Block factor (optional): a factor that is slow to change

If one factor is a hassle to change (an orifice insert), choose it as the block factor: each of its levels
is fitted **once**, and all its runs are done together.

- The **low and high blocks** hold that level's corners, opened and closed by the same run (that factor at
  low or high, every other factor at the middle): the **block repeats**. The pair shows drift within the block.
- The **middle block** holds the centre runs (first, last and spread through it) and the other factors'
  face points.
- **The cost:** a blocked factor's effect is tied to time of day, because each level was run at one time.
  A slow drift would look like its effect. The block repeats and centres let you check for drift, and a
  later session that refits the outer levels settles it.
- Without a block factor every run is in one randomised block.

### Half fraction (5 factors only, in practice)

Runs half the corners, chosen so that every term of the quadratic can still be fitted (for 5 factors:
16 corners instead of 32). **Do not use it with 4 factors**: the two-factor interactions would be tied in
pairs and could not be told apart. The app warns if you try.

### Extra runs: check points and controls

Settings that are not part of the design and are **not used in the fit**; the fitted surface predicts
them, which tests it.

- A **check point** sits inside the region but off the grid (the 0.8 mm insert): it tests the surface
  between levels. It goes after every block.
- A **control** sits outside the region (0 rpm, no rotation): it answers a yes/no question (does rotation
  help?). If it is at one block's level, it goes inside that block, among the centres.

### First run (optional): the pressure check

Name the worst-case corner (e.g. highest gas, highest feed, highest RPM, smallest orifice). It is run first
and its block goes first. Watch the logged pressure against the rig's limit: within it, carry on (the run
counts as a normal corner); over it, stop, lower the range for the whole day, and rebuild the sheet.

### Seed

The run order inside each block is random (so nothing else that changes through the day lines up with a
factor). The seed fixes that randomness: the same seed rebuilds exactly the same sheet. Change the seed
for a different order.

### What you get

`run_sheet.xlsx`, `.csv` and `.md`, plus `rsm_run_sheet.json` (the plan, so the sheet can be rebuilt):

- one row per run in order: run number, block, the settings, the point type, and the **Notes to type**
  (`CCD run 7 centre`)
- a summary: run counts, about how long the day takes (9 min a run + 15 min a block change by default),
  whether the full quadratic can be fitted, and its degrees of freedom for noise (pure error) and for
  lack of fit

## Step 2: on the day

1. Follow the sheet in order. Let flows settle for the same time before every capture, including after an
   orifice or RPM change.
2. **Type the sheet's Notes exactly into the capture GUI's Notes field** (`CCD run 7 centre`). The app reads
   them back to match each captured run to its row, and flags any run whose Notes disagree with its settings.
3. Leave the capture GUI's AI analysis off: the app runs the AI afterwards in its batch.
4. If something has to change (a run redone, done out of order, a setting off), carry on and note it. The
   app detects what was actually run from the folder names and workbooks, not from the plan, and lists
   every difference.
5. Short of time: drop the check run first, then the block repeats. Keep all the centres and the control.

## Step 3: after the day, check the design

Select the day's run folders. The app works out what experiment they form, with no sheet needed:

| It finds | What it means |
| --- | --- |
| Factors and levels | what varied, the low / middle / high of each, and what was held fixed |
| Point type of every run | corner, face centre, centre, axial, edge, check point, outside the region (control) |
| Design type | e.g. "face-centred central composite, 4 factors", with any expected run that is **missing** named |
| Repeats | runs at identical settings (they give the noise estimate) |
| Block factor | a factor that changed only about once per level through the day: tied to time of day |
| Drift pairs | settings repeated inside one block |
| Notes check | runs whose Notes disagree with their settings, and runs captured out of the planned order |
| Can the quadratic be fitted | yes or no; noise (pure error) and lack-of-fit degrees of freedom; if no, the largest model that can be, and why each term was dropped |
| Which tab | an orthogonal array (the 9 × 3 L9) belongs in the Taguchi tab; a CCD in the Response surface tab |

If a sheet was built, each captured run is compared with its row: **as planned**, **out of order**,
**settings differ**, **not captured yet**, or **not on the sheet**.

You can edit before analysing: rename a factor, correct a run's level, leave a run out, mark a run as a
**validation run** (kept out of the fit and predicted instead), or change the block factor.

### Terms used

- **Pure error**: the spread between runs at identical settings: real run-to-run noise.
- **Lack of fit**: what the fitted surface misses beyond that noise. Significant lack of fit means the
  surface does not describe the data well.
- **Degrees of freedom (df)**: how many independent pieces of information go into each of those.
- **Aliased**: two effects the runs cannot tell apart. **Nearly aliased** (variance inflation factor above
  50): technically separable, but so weakly that the estimate is meaningless.

## Step 4: run the AI batch

As for Taguchi: the Batch tab runs the AI and the classical measurement on the selected runs.

## Step 5: analyse

What you get, in the output folder (`rsm_report.md`, `rsm_analysis.xlsx`, `rsm_results.csv`,
`rsm_deck.pptx`, `figures/`):

- **One fitted surface per response** (atomised fraction, D32, mean diameter, throughput, steadiness,
  peak pressure and the rest), the full quadratic and a simplified one (terms dropped highest order
  first, keeping a slope while its curve or interaction stays), with R², predicted R² and lack of fit.
  A surface whose simplified model has predicted R² below 0.5 is flagged as not usable and is kept out of
  the best-settings search. (The simplified model is judged, not the full quadratic: with few runs per term
  the full model's leave-one-out predictions are all high-leverage extrapolations. On the CCD day with the
  pressure-limited block out, 21 runs for 14 terms, atomised fraction read −0.28 full and 0.89 simplified.
  Because the simplified model's terms were chosen on the same runs, its figure is somewhat optimistic.)
  A factor that appears in none of the surfaces steering the best setting is **free**: no level of it
  changes the score, so the best setting holds it at the design centre and the report says so; choose it
  for another reason (throughput, steadiness, cost).
- **Contour maps** laid out as the plan draws them: gas across, feed up, one panel per orifice, one map per
  RPM; the runs at each setting marked and the best setting starred. **3D surfaces** of the same, an
  **all-pairs** view (every pair of factors at the best setting), and a **profiler** (each factor swept
  through the best setting with its uncertainty bands).
- **Where each surface peaks** (a maximum, minimum or saddle, inside or outside the range).
- **Best settings** by desirability (every goal scored 0 to 1, combined), continuous and at the levels
  that can actually be set (e.g. the orifice inserts that exist), with what pulls each factor up or down.
- **Controls** against the centre runs (does rotation help: the 0 rpm run vs the five centres), **check
  and validation runs** against their 95% prediction intervals, and **drift** (centres over the day,
  block repeats).
- **Gas mass flux at the orifice** (a covariate, as GLR is in the Taguchi analysis): every run against its
  delivered gas mass flow per orifice area (kg/m²/s, from the gas it got in the camera window), coloured by
  orifice and hollow where it did not get its set gas, so both regimes sit on one axis. On the CCD day it
  ordered atomised fraction better than any set point (Spearman +0.91). It is not a factor: it is made from
  the gas and the orifice, so it cannot be separated from them, and the surfaces stay on the set points. The
  section also gives the exit orifice **length** and L/D where `run_summary.xlsx` records them (from
  2026-10-13); if the runs used different lengths the report warns at the top, because the length is not in
  the model and its effect is mixed into the others.
- **Silicone film at the exit** (a covariate too): the measured gas flux over what gas alone could pass at the
  camera-window P0 is the gas share α of the orifice; from it the silicone speed in the orifice,
  u_L = Q_L / ((1 − α) A), and, for an annular exit, the film thickness h = (d/2)(1 − √α). On the CCD day the
  film ordered atomised fraction best (Spearman −0.90; C7/C8 had the thinnest film, ~126 µm). The report, the
  workbook sheet *Silicone film at exit* (per run, with the diagram and the maths beside it) and the deck (a
  diagram slide before the gas flux slide) explain it. Cd is 1.0 until each insert is measured gas-only
  (`orifice_cd.json`). No-spray runs are plotted but left out of every covariate fit.
- The size, steadiness, quality figures and image sheets from the Taguchi analysis that are not
  Taguchi-specific, as an appendix.
- Every slide in the deck says what it shows and how to read it, with the terms it uses defined.

## Step 6: what to run next

`next_runs.xlsx` (and `.csv`, `.md`) is a ready-to-use run sheet, numbered, with the Notes to type and
every run's predicted responses and 95% prediction interval. It holds whichever of these apply, each with
the reason:

- **Confirm the best setting**: three runs there (rounded to what the rig can set, at an insert that
  exists) and a repeat of the design centre to link the sessions. Always.
- **Move the region**, when the best setting is on an edge or nothing curves: runs stepping outward along
  the direction the combined score rises fastest (stopping at the rig's limits: gas 12,000 sccm, bubbler 1,000 rpm, feed 2,000 to 12,000 steps/s), and a
  whole new CCD centred on the best setting (in `next CCD/`). Runs beyond the tested range are marked as
  extrapolation, and any factor taken beyond its tested range with no recorded rig limit (RPM, feed) is
  named, so it can be checked on the rig first.
- **Strengthen the model**, when it is weak (lack of fit, a goal surface that cannot predict new runs, a
  check run that missed): the runnable settings that most reduce the model's uncertainty, the first next
  to any run that missed. Only sizes inside the fitted span are offered (a size outside it wins every pick
  just by being far away); the text names the sizes held back and whether their runs were pressure-limited,
  and says when a curve term (orifice²) needs a third size in the next design.
- **Make a new insert**, only when the plan's three conditions all hold: the best point is at the 0.5 or
  1.8 mm edge, the orifice slope is still significant and improving there, and the 0.8 mm check run
  matched the model. The size is the next step by the same ratio (e.g. 1.8 → about 2.7 mm).

A **nuisance factor** can be kept in the model without being mapped (RPM in the 9x3 trial), and several
models can be fitted side by side to see whether a term depends on it.
