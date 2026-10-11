# Response-surface (CCD) experiments: what to do, step by step

This is the guide the Response surface tab of the Experiment Analysis app shows (Guide panel). It covers
planning a central composite design (CCD), running it, and getting it analysed.

> **What is built so far (2026-10-11):** building the run sheet (step 1) and detecting the design from
> the captured runs (step 3) work, as code with tests; the tab that puts buttons on them comes in
> Phase 7. Fitting the surfaces, the contour / 3D figures, validation runs and the recommended next runs
> (step 5) are Phases 4 to 6, not built yet. The Taguchi tab is unchanged and works as before.

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

## Step 5: analyse (Phases 4 to 6, not built yet)

What it will give: one fitted surface per response (atomised fraction, D32, mean diameter, throughput,
steadiness, peak pressure), simplified to the terms that matter; checks of the fit (lack of fit,
residuals, drift); contour maps and 3D surfaces per pair of factors, with the pressure limit shaded; the
check and control runs compared with their predictions; the best settings by desirability; and a run
sheet of recommended next runs (confirmations, or a new region if the best point is at an edge). The
outputs mirror the Taguchi ones: report, workbook, figures and a PowerPoint deck.
