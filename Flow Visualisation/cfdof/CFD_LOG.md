# CFD work log: the chamber airflow

What has been tried on the chamber CFD, why, and what came out. Newest work at the bottom of each section; the
step-by-step clicking is in `CFDOF_GUIDE.md`, the overall plan in `../PLAN.md` (Phase 2 onwards).

**The aim.** Know where droplets of each size go in the atomisation chamber, so a collection design can be found that
reliably gathers the wanted band (0–30 µm). The CFD supplies the air flow; droplets are then tracked through it.

---

## 1. Choosing the method (2026-10-23)

| Tried / considered | Outcome | Why |
|---|---|---|
| **FluidX3D** (Moritz Lehmann's GPU lattice Boltzmann code), on the home PC's GPU | **Dropped** | Its grid is uniform. The spray has to enter as a ~0.9 mm inlet; at the 0.5–1 mm cells the GPU could afford, that inlet would carry 4–8× its real gas and the outlet flow would be ~2.6–4.7× too high. |
| **OpenFOAM, steady RANS, on the Mac** | **Chosen** | A graded mesh puts small cells only where needed (the spray hole, the jet) and large ones elsewhere, so the real spray fits on a CPU. Free, and the standard research code. |
| Turbulence model **k-ω SST** | Chosen | The usual choice for jets and recirculating flow. Check later against realizable k-ε (PLAN Phase 2). |
| **FreeCAD + CfdOF** (a GUI for OpenFOAM), **cfMesh** mesher, **ParaView** viewer | Installed for learning | Ben is new to CFD: CfdOF shows every step (geometry, boundaries, mesh, solve, view) by clicking. The thesis runs (Phase 2) use the same OpenFOAM, scripted. |

Installed and checked: OpenFOAM v2606 (OpenFOAM's own test case, pitzDaily, ran in 5 s), ParaView 6.2.0, FreeCAD 1.1.4
+ CfdOF + cfMesh (built for v2606; CfdOF's dependency check passes).

## 2. How the spray enters the model

The CFD has one gas at one density (chamber air, 1.204 kg/m³). The real spray leaves the nozzle denser and through a
smaller effective area than its bore, so the bore is not the right inlet size.

| Step | Value | Why |
|---|---|---|
| Real orifice | 1.2 mm insert | measured |
| Discharge coefficient | Cd 0.527 | measured 2026-10-15 (the 0.5 / 0.8 mm inserts gave 0.84 / 0.81; the 1.2 mm insert's residue / bore check is pending) |
| Effective hole | 1.2 × √0.527 = 0.87 mm | the gas only uses ~53 % of the bore's area |
| Exit state | Mach 0.69, 226 m/s, ~268 K, ~1.32 kg/m³ | the gas cools as it accelerates |
| Equivalent inlet at chamber density | **0.91 mm at 226 m/s** | carries the real gas flow (8,995 sccm = 1.775e-4 kg/s) **and** the real momentum (40 mN) |

Using the bare 1.2 mm bore would give the right gas flow but only 58 % of the momentum: a jet that slows and spreads too
early and stirs the chamber too weakly. **Ben's CAD keeps a 1.0 mm hole** for the learning cases (his choice): 188 m/s,
83 % of the real momentum. The thesis runs set the inlet from the settings file (0.91 mm planned).

Inlet turbulence: 5 % intensity (what fully developed pipe flow gives at the exit Reynolds number, ~12,500) and length
scale 0.07 × the hole diameter (eddies cannot be bigger than the hole). The jet's own strong turbulence is made by the
model in the shear layer. The real two-phase exit is probably rougher; a 20 % run is planned as a sensitivity check.

## 3. Learning cases (2026-10-23)

| Case | Result | Lesson |
|---|---|---|
| CfdOF's elbow demo | converged in 98 iterations | the whole loop: mesh, solve, ParaView |
| Practice box, 300 × 200 × 350 mm, 6 mm inlet (8,000 sccm), 25 mm outlet | 67,000 cells, 64 s, gas in = gas out | the first version refined only the pipes' end discs: the 6 mm pipe vanished from the 8 mm mesh, the inlet had no faces and the solver crashed ("Illegal instruction: 4"). **Refine the whole pipe.** |
| Same box + 0.91 mm spray in the lid | 83,000 cells, 78 s, outlet = inlet + spray | velocity residuals stall near 1e-2: the jet does not settle to one steady pattern |

These were checked by script first (answer key `chamber_box.FCMacro`), then written up as the guide's Parts 2–4.

## 4. Ben's real chamber, baseline (2026-10-24)

**What the model is.** The chamber as designed, **with no collection system**: the inside air of the chamber in
Fusion, exported as STEP. It shows how the air behaves with just the spray running.

| | |
|---|---|
| Inside | 190 × 692 × 280 mm (x × y × z), 35.3 L, **Y up** |
| Cut out (walls) | atomiser body 62 × 350 × 64 mm, 24.6 mm rod, nozzle block 38 × 48 × 35 mm, 30 × 30 mm arm |
| Spray | 1.0 mm hole, 1 mm deep, underside of the nozzle block, fires down (−y), 228 mm above the floor; 8,995 sccm = 147.4 cm³/s |
| 44 mm port | 20 mm stub on the z = −297.6 wall near the top. The **post-test extraction opening**, open to the room during a test through a fine mesh. Modelled as open at 0 Pa: at 0.1 m/s the mesh costs a few Pa, which shifts the whole chamber's pressure but not the flow pattern. |

**How it got there.**
- STEP v1: one clean solid, but no outlet (the spray gas had nowhere to go) → v2 with the 44 mm port.
- Checked by script on a scratch copy before Ben clicked: 66,548 cells, 2,000 iterations in ~2.5 min, gas in = out.
- Ben's first mesh had no refinements yet: 60,428 cells and the spray inlet had **0 faces** (a 1 mm hole is lost in
  8 mm cells). Added the refinements (outlet stub 2 mm cells; spray hole ~0.06 mm cells) → 66,548 cells, as checked.
- Settings: steady, isothermal, single phase, RANS k-ω SST, air; spray inlet 1.474e-4 m³/s, 5 %, 0.07 mm; outlet 0 Pa;
  walls no-slip (default for every other face); base cells 8 mm. Gravity greyed out in CfdOF (one gas at one temperature:
  no buoyancy, so it changes nothing here).
- Ran 2,000 iterations; final residuals Ux 0.021, Uz 0.015 (the jet still not settled, as in the box).

**What it shows** (probed from Ben's results, `~/OpenFOAM/cfdof_cases/Chamber_v1/case`):
- The jet fires down, lands on the floor at ~2 m/s and spreads along it at up to 2.5 m/s, up the walls and round.
- The whole chamber is stirred: mean air speed 0.54 m/s; 44 % of the volume above 0.5 m/s, 2 % below 0.1 m/s.
- Next to the hole, air flows sideways **into** the jet at 4–5 m/s (2 mm from the axis) to 0.6 m/s (15 mm): the jet's
  entrainment, at the rate the textbook (Ricou & Spalding) gives. In ParaView these look like streams at 90° to the
  hole because the stream tracer draws both ways from each seed.
- The 44 mm port draws gently: 0.13 m/s at its mouth.

**Its main flaw: the jet's first ~100 mm is smeared.** Only the hole itself was refined; a few mm below it the cells are
as wide as the jet.

| Below the hole | Real 1 mm jet (approx.) | This run |
|---|---|---|
| 10 mm | ~110 m/s | 11 m/s |
| 80 mm | ~14 m/s | 7 m/s |
| 200 mm | ~5.6 m/s | 4.5 m/s |

**What it means for droplets (estimate, no droplet model yet).** With only the spray's gas leaving, the chamber air
takes ~4 min on average to leave, while fines settle onto the floor faster. Treating the chamber as fully mixed (walls
ignored, so optimistic), the share of each size carried out of the port: 5 µm 78 %, 10 µm 46 %, 20 µm 18 %, 30 µm 9 %.
So in the bare chamber most of the 20–30 µm band settles on the floor. A droplet under 30 µm settles at most ~3 cm/s,
~20× slower than the air, so it goes where the air takes it: the circulation decides where the band ends up.

## 5. Practical lessons (FreeCAD, CfdOF, ParaView)

- Each FreeCAD workbench brings its own menus: the **Part** menu only appears in the Part workbench.
- CfdOF names the case folder after the document's internal name. Tick **Append document name to output directory**;
  after **Save As**, close and reopen so the name updates. **Write** in the solver panel empties that case folder, so
  for any variation to compare, Save As first.
- FreeCAD shows 2 decimals by default (k = 0.0001 shows as 0.00): set **Number of decimals 6** in Preferences.
- The refinement box takes 3 decimals: 0.012 gives the same mesh as 0.0125 (cfMesh halves cells in whole steps).
- Hidden or tiny faces: pick them with **Select from list** in the boundary / refinement panel.
- ParaView: a new filter works on whatever is selected (a slice of a slice is empty); rescale colours (the 200 m/s jet
  hides the 0.5 m/s chamber); press **P** over the model to put a slice there; CfdOF's own mesh view adds a diagonal
  cut (ExtractCellsByRegion), which is only a view.

## 6. Droplets through the flow (Phase 3a, 2026-10-25)

The droplets are tracked through the frozen Part 6 flow by OpenFOAM's own tracker, `icoUncoupledKinematicParcelFoam`
(one-way: they do not push the air), in the slide test's sequence: spray on for the exposure, switch-off, the flow
kept for a bracketed 0 / 2 / 10 s (how long the circulation lasts is unknown), then still air until the slides come
out (5 min). Turbulent gusts from k on and off, as a bracket. One command (`run_droplets.py`, HOW_TO_REDO step 7).

| Tried | Outcome | Why |
|---|---|---|
| Part A: 10 / 30 / 100 µm, 5,000 each, through Ben's Part 6 flow | **Works** | every droplet accounted for; ParaView shows them |
| OpenFOAM's table injection (`kinematicLookupTableInjection`) | Dropped | with random start points it takes the size from one row and the start point from another; and rounding lost droplets (1,996 of 2,000) |
| Cone-nozzle injection, one injector per size, one droplet per size per step | **Chosen** | exact counts (per_size of every size), spread evenly over the exposure; start points spread evenly over the 10 mm disc, as Phase 1. One difference from Phase 1: each droplet leans out a random 0–10°, not in proportion to its distance from the centre |
| Walls that keep a droplet stuck (`stick`) | Dropped | OpenFOAM keeps working out a stuck droplet's velocity under gravity; with a 10 s still-air step each took thousands of sub-steps: 4.6 min of still air per run |
| Walls that drop a droplet from the tracking at its first touch (`escape`), the hit record keeping where and when | **Chosen** | the same answer, 10× faster: ~30 s a run for 20,000 droplets. The landed droplets are written back into the saved frames, so ParaView shows the deposit |
| Restarting for still air | Fixed | OpenFOAM writes numbers like 8e-316 that it cannot read back: rounded to 0 first |

**Seen in the tests so far** (not yet the baseline: that is Part D):
- The jet blows most 30 µm droplets onto the floor during the exposure itself; only the finest are still airborne at
  switch-off (~25–35 % of 0–10 µm, ~20 % of 10–20 µm, ~5–7 % of 20–30 µm, gusts on).
- Where the fines end up depends on the gust model: on, a third or more of the sub-20 µm droplets land on the side
  walls; off, nearly all reach the floor. Gust models of this kind are known to overstate how many fine particles
  reach walls.
- **The tracking artefact, measured and explained (Part C, 2026-10-25).** 0.5 µm tracers, which follow the air, fed in
  like the spray for 5 s: **62 % land on the floor with gusts off** (25 % with gusts on, 68 % on some wall). The
  fired sizes up to ~10 µm match the tracers (2 µm: 64 %; 10 µm: 90 % with settling on top).

  | Tried | Outcome | What it showed |
  |---|---|---|
  | Tracers at 25, 5, 1 and 0.1 ms steps | floor 62, 62, 61 % (40–45 % on the first pass, all four); side walls 17 % at 25 ms, none at 5 and 1 ms | the floor share is not the time step; the side-wall hits are (Part D, below) |
  | Where and when | half within 0.1 s of release, median 36 mm from the impact point, 90 % within 80 mm | the first pass down the jet, in the stagnation zone |
  | The hit records | every tracer reaches the floor at exactly its settling speed (8.06 µm/s), the air's speed there 0 | the air brings it to the floor; settling finishes |
  | Gravity off | 0 of 500 touch anything (against ~40 % with gravity) | confirmed |
  | The floor cells under the jet | 1.28 mm deep (graded layers 1.3 / 2.7 / 4.4 mm) | |

  **Why:** in the cell against a wall OpenFOAM interpolates the air linearly (cellPoint), so both its speed along and
  towards the wall fall in proportion to height: a droplet riding it keeps the cell centre's approach angle and closes
  in exponentially fast, to within nanometres, where its settling speed covers the last gap. At a real no-slip wall
  the speed towards the wall falls with height squared (continuity), so the droplet is swept along instead and only
  what settles through the slow layer lands. OpenFOAM's `cellPointWallModified` only swaps the wall face's value for
  the cell's, which does not help.
  **Prototype (scratch, not in the tool):** the air in the wall-adjacent cells made parallel to the wall (its normal
  part removed, 20,747 faces): tracers on the floor 62 → 11 % (gusts off), 25 → 22 % (gusts on: the gusts dominate).
  **Options for Ben:** (a) that correction in the tool, (b) a finer near-wall mesh under the jet (first cell well
  under the ~0.6 mm stagnation layer) and a new CfdOF solve, (c) both; and read the fines' floor counts while the air
  moves as an upper bound until then. Landings in still air and the large droplets are not affected.
- **The tracking itself is exact** (column check): every size dropped from rest, in still air and in a 0.2 m/s
  cross-flow, OpenFOAM against Phase 1's integrator with OpenFOAM's drag law and air: speeds within 1e-6 %, paths
  within 0.1 mm. Settling speeds against Phase 1's own physics within 0.4 % below 60 µm and 1.7 % at 200 µm (the drag
  laws part at Re of a few).
- **The time step (Part D, 2026-10-25).** Stage 1's step is the exposure / per_size (one droplet of each size per
  step). Gusts off, flow kept 0 s, the same flow at four steps:

  | per size | step | 0–10 µm on the floor | on the side walls | airborne at switch-off |
  |---|---|---|---|---|
  | 200 | 25 ms | 85.5 % | 11.9 % | 13.0 % |
  | 600 | 8.3 ms | 94.5 % | 2.1 % | 24.0 % |
  | 1000 | 5 ms | 94.5 % | 2.3 % | 23.8 % |
  | 2000 | 2.5 ms | 94.3 % | 2.4 % | 24.4 % |

  10 µm and up: the same at every step. Gusts on: the same at every step, every band (0–10 µm: floor 43–45 %, side
  walls 33–34 %). So 25 ms was too long for the fines with gusts off; the default is now 600 per size (8.3 ms), no
  slower (the still-air stage dominates: ~1.5 min for six runs and the checks), and report.md flags a longer step
  (check 7). Part C's runs at 25 ms overstated the gusts-off fines' side-wall hits; their floor shares stand.
- **Part D: the baseline and the snapshot check (2026-10-25).** `~/OpenFOAM/droplet_runs/droplets_baseline/
  2026-10-25_140603/` and `droplets_snapshots/2026-10-25_135054/comparison.md` (a sweep: the same 600-per-size
  droplets through iterations 1000, 1500, 2000 of the Part 6 case and iteration 2000 of the Part 5 case; 5.7 min).

  | Flow, against iteration 2000 | the air (mean \|ΔU\| / mean speed) | the band's floor deposit (gusts on, flow kept 2 s) | 0–30 µm floor share, weighted, any run |
  |---|---|---|---|
  | iteration 1000 | 39 % | the same in every band | within 1.3 points |
  | iteration 1500 | 28 % | the same below 30 µm; above, centre 0.6–1.6 mm off ("close") | within 1.3 points |
  | Part 5 (jet not refined, 85,535 cells) | 34 % | differs in every band below 60 µm: fines' spread ~22 mm tighter, side walls 30 → 16 % | +13 to +19 points |

  **One snapshot is enough:** the circulation wanders between iterations (the residuals plateau at ~1e-2 from ~500
  on) but the droplets' answer does not move beyond the droplet-count noise; the brackets we carry are far wider
  (gusts on/off 42 points, flow kept 0–10 s 13 points). **The mesh matters more:** the Part 5 mesh's tracers land 99 %
  (gusts off) against 62 %, so the near-wall artefact is larger there, and most of its difference is probably that.
  The grid check and a near-wall layer (fix (b)) come with the scripted flows.
  Checks of the comparison: the same flow at 200 and 600 per size agrees in every band with gusts on (the noise model,
  the bootstrap, holds); two runs with identical settings match droplet for droplet.
  **The baseline (weighted 0–30 µm band, gusts on, flow kept 2 s):** floor 64 % (57 % while the air moves: the
  artefact's upper bound; 8 % in still air), side walls 30 %, atomiser 5 %, lid 1 %, port < 0.1 %; 17 % airborne at
  switch-off; the band is 78 % of the floor's deposit by number, 32 % by volume. Gusts off: floor ~100 %.

## 7. In progress and next

1. **Jet refinement** (guide Part 6, for Ben to click through; tested by script 2026-10-24): two cones of small cells
   along the jet, 0.5 mm in the first 40 mm and 2 mm down to the floor. 198,682 cells, 2,000 iterations in ~7 min.
   The jet now holds up: 94 / 47 / 11 m/s at 10 / 20 / 80 mm below the hole (was 11 / 5 / 7; a real 1 mm jet ~110 /
   56 / 14). The chamber barely changed (mean 0.55 vs 0.54 m/s, floor spread 2.5 m/s both): the circulation is set by
   the jet's momentum, which the coarse mesh still carried. The refined jet runs ~20 % below the textbook one, as
   two-equation models spread round jets too fast (Phase 2's second turbulence model checks it). Velocity residuals
   just under 1e-2 (was ~2e-2).
2. **Grid check** (finer jet cones) and **inlet turbulence** 5 % vs 20 %: does the answer change?
3. **Droplets through the baseline** (section 6; `../PLAN.md` Phase 3a): Parts A–D done 2026-10-25 (the tool,
   figures, report, checks, the baseline run, the snapshot check: one snapshot is enough; the mesh matters more).
   Fix (a) dropped; (b) comes with the scripted flows. Several flows compare with a sweep file or `--compare`.
   **Ben's rig check:** a 3 × 3 grid of glass slides on the floor; spray 20 s into a bin, then ~5 s free; microscopy +
   image classification for a deposit map by size and position. It also sizes the sub-30 µm droplets the shadowgraph
   counts but cannot size. To watch: fines from the warm-up reach the slides too (cover them, or a warm-up-only
   control); stains are larger than droplets (~2.5–3× if silicone wets glass: measure it); low coverage (try 1, 2, 5 s);
   wait ~10 min for fines to settle; slide positions relative to the nozzle (x 164, z −212 in the CAD).
4. **Cross-stream and collection design**: screen ideas in Phase 1's fast model (about 10 s a layout), then CFD and
   droplet tracking on the best two or three.
5. **Thesis-grade runs (PLAN Phase 2, awaiting Ben's go)**: scripted, jet refined along its length, grid check, two
   turbulence models, one compressible check, and whether a time-dependent solve is needed (the residuals never settle).

**The liquid narrows the gas's way out (found 2026-10-25, from the CCD day's run_summary pressure logs, read-only).**
While spraying, the upstream pressure is far above what the gas-only Cd predicts: 1.2 mm insert at 9,000 sccm,
3.1 barA measured against 1.39 barA, i.e. the gas gets ~41 % of its gas-only effective area (36-47 % across the 1.2 mm
runs, less with more liquid: 3,000 / 4,000 / 5,000 sps 0.46 / 0.41 / 0.39); the 0.5 mm insert 49-78 %. If all of it is
at the orifice (a liquid film ~150 um thick in the 1.2 mm, if annular), the jet is choked and carries ~71 mN, not
40 mN: the CFD's 1.0 mm hole (~33 mN) would be about half. Not yet separated: pressure lost upstream in the mixing
chamber with liquid in it, and two-phase choking (the gas-only formula then gives only an effective area). For the
scripted orifice (Phase 2): take the effective hole from each run's own pressure and gas flow, not the gas-only Cd.

**Still open.** The 1.2 mm insert's Cd (bore / residue check); the liquid carries as much mass as the gas
(2.0e-4 vs 1.8e-4 kg/s) and its push on the air is not in any model yet; sub-30 µm sizes (the slides should help).

## Where things are

| What | Where |
|---|---|
| Step-by-step guide | `Flow Visualisation/cfdof/CFDOF_GUIDE.md` |
| Practice-box answer key | `Flow Visualisation/cfdof/chamber_box.FCMacro` |
| Ben's STEP + FreeCAD file | `~/OpenFOAM/cfdof_cases/FlowVis1stTrial/` |
| Ben's case (mesh + results) | `~/OpenFOAM/cfdof_cases/Chamber_v1/` |
| The plan | `Flow Visualisation/PLAN.md` |
| Droplets: settings, command | `Flow Visualisation/settings/droplets_baseline.yaml` (a sweep: `droplets_snapshots.yaml`), `run_droplets.py` |
| Droplets: each run, all in one folder | `~/OpenFOAM/droplet_runs/<name>/<date_time>/`: report.md, figures/, paraview/<run>.command (double-click to view), openfoam/ (the cases); the flows, reconstructed once, in `flows/` |
