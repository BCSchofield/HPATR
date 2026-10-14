# Orifice discharge coefficient (Cd): gas-only test

Written 2026-10-13, for later in the week. It measures how much gas each exit orifice insert really
passes compared with an ideal orifice (Cd). The analysis app uses Cd to split the orifice between gas and
silicone, giving the gas share, the silicone speed and the film thickness at the exit
(`docs/notes/2026-10-13_phase12_physical_variables.md`). Until an insert is measured, the app uses 1.0
and says so. Cd = 1.0 overstates the gas capacity, which makes the gas share read low and the silicone
film read thick.

## What it can and cannot measure

Gas alone has to build enough pressure across the orifice. Expected upstream pressure, assuming
Cd ≈ 0.8, nitrogen at 20 °C and no line loss (* = choked):

| Gas (sccm) | 0.5 mm | 0.8 mm | 1.2 mm | 1.8 mm |
|---|---|---|---|---|
| 2,000 | 1.27 | 1.05 | 1.02 | 1.01 |
| 4,000 | 2.09* | 1.17 | 1.04 | 1.02 |
| 6,000 | 3.14* | 1.37 | 1.08 | 1.03 |
| 8,000 | 4.19* | 1.66 | 1.14 | 1.04 |
| 10,000 | 5.23* | 2.04* | 1.21 | 1.05 |
| 12,000 | 6.28* | 2.45* | 1.29 | 1.07 |

- **0.5 mm and 0.8 mm:** good. They are choked over most of the ladder, which is the regime the
  two-phase runs are in.
- **1.2 mm:** marginal. It is subsonic only, with a 0.2–0.3 bar drop. Line loss is IGNORED (Ben,
  2026-10-14): it is negligible against the choked 0.5 / 0.8 mm pressures, and for 1.2 mm a line loss of a
  few hundredths of a bar would make its Cd read low by a few percent.
- **1.8 mm (the bubbler's own exit, no insert):** gas alone hardly raises the pressure (≤ 1.07 barA,
  within the sensor's noise), so its Cd cannot be measured this way. Leave it at "not measured". Either
  use a literature value for the exit's shape, or come back to it with a restrictor or a higher-flow
  MFC. Its ladder is still run, as the line-loss reference (step 4).

## On the rig (about 10 min per insert)

1. **Prepare.** `git pull` on the lab PC first: GUI_Clean needs today's "Orifice length" box.
   - No silicone may flow: the traverse stays put (Speed **0**) and the RPM box stays empty.
   - Purge the nozzle dry first with gas at about 6,000 sccm for 30 s. Silicone left in the orifice
     blocks area and would read as a low Cd.
2. **For each insert (0.5, 0.8, 1.2 mm):**
   - Fit it. In the Nozzle card, pick the **Orifice** and type its **Orifice length (mm)**.
   - Notes: `CD TEST <d> mm L <L> mm, room <T> C`. The script finds runs by "CD TEST".
   - Speed 0, then **START EXPERIMENT**. This is a static run: gas and logging, no traverse, and no end
     of its own.
   - Step the gas with Set Flow: 2,000 → 4,000 → 6,000 → 8,000 → 10,000 → 12,000 sccm, holding each
     **about 20 s** (at least 10 s once it has settled).
   - **STOP EVERYTHING** to end. The run saves itself, with the pressure and flow log in
     `run_summary.xlsx`.
3. **Check the readings on the day** against the table above. A pressure well above it means
   something blocks the orifice (silicone, debris) or the line loss is large.
4. **Line-loss run (OPTIONAL; skipped, Ben 2026-10-14):** the same ladder on the bare **1.8 mm bubbler** (no insert).
   The rig has no open fitting: 1.8 mm is the bubbler's own exit and the largest opening there is
   (Ben, 2026-10-14). Notes: `CD TEST 1.8 mm line loss`. Its gas-only pressure is mostly line loss,
   plus the 1.8 mm exit's own small drop (ideally 0.01–0.07 bar over the ladder, table above). The
   script fits that run's pressure rise as dP = k Q² and subtracts it from every other run. Because the
   1.8 mm drop is counted as line loss, k reads slightly high and the 1.2 mm Cd slightly high. To do:
   subtract the 1.8 mm exit's ideal drop first and give the 1.2 mm Cd as a range.

The camera is not needed. AI analysis can stay off.

## The analysis (Mac or lab PC)

Run it on the day folder. The output folder is new, and nothing in the run folders is changed. Since
2026-10-14 the run sheet saves the Cd runs under `Calibration/Orifice Cd` (its "Save under" column), so
they stay out of the spray runs' day folder:

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 /Users/benschofield/Documents/GitHub/HPATR/AI/Real_Data_Code/orifice_cd.py "/Volumes/LaCie/Calibration/Orifice Cd/2026/10/<DD>" --out "/Volumes/LaCie/Calibration/Orifice Cd/analysis/2026-10-<DD>"
```

Line loss is ignored (Ben, 2026-10-14); add `--line-loss-run "<run folder>"` only if a line-loss run was
made.

It writes:

- `orifice_cd_points.csv`: every steady step, with P0, flow, ideal flow, Cd, and whether it was choked;
- `orifice_cd_summary.json`: per insert, Cd, its SD, the number of steps, and whether the fit was
  choked or subsonic;
- `orifice_cd.png`: measured flow against pressure, with the ideal curve and the fitted Cd.

Add `--write` once the numbers look right. That writes the Cd values into the app's table
(`src/ai/Taguchi_Analysis_UI/orifice_cd.json`), which every later analysis uses, so re-run the CCD
analysis afterwards. Without `--line-loss-run` the 1.2 mm result is printed with a warning.

## The maths (also in the script's header)

On each steady step, with P0 and Q the medians after the first 3 s:

    m_dot   = Q × ρ_std / 6×10⁷                                (kg/s; ρ_std = the run's recorded gas density)
    G_ideal = P0 √(γ / (R T)) (2 / (γ+1))^((γ+1) / (2(γ−1)))     when Pa / P0 ≤ 0.528 (choked)
            = P0 √(2γ / ((γ−1) R T) [r^(2/γ) − r^((γ+1)/γ)])      otherwise, r = Pa / P0
    Cd      = m_dot / (A × G_ideal),   A = π d² / 4

Per insert, Cd is the least-squares slope of the measured flow against A × G_ideal:

- over the **choked** steps when there are at least two;
- otherwise over the subsonic steps above 1.1 barA, flagged as such.

**Caveats:**

- P0 is the Alicat's upstream reading, so without the line-loss correction Cd reads low.
- Cd can differ between choked and subsonic flow, and with orifice length (L/D). That is why the
  table is keyed by diameter and length.
- In the two-phase runs, the 1.2 mm and 1.8 mm inserts work at 1.4–3.3 barA. The ideal capacity there
  comes from this same formula, so their Cd matters as much as the 0.5 mm one.
