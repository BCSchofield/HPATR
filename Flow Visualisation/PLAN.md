# Flow Visualisation: plan

**2026-10-23. DRAFT for Ben's review. No code is written until Ben approves a phase** (Ben, 2026-10-23: "plan each
step out on all of these things WELL before we ever begin coding"). Each phase ends with a stop and a report.
Phase 0 is answered (below), so nothing is open for Phase 1.
A check of the numbers (2026-10-23, Claude) corrected three statements (marked **Corrected**) and made four
proposals, all accepted by Ben the same day (marked **Decided**). Ben's decisions carry his name and the date.

## The goal

A free tool that shows where droplets of each size go inside Ben's atomisation chamber, and how much of a chosen
size band (30–60 µm to start) reaches a target, as the air flow and inlet settings change. It should give numbers
and graphs good enough for the thesis, and trends across settings.
Plus the measurement that feeds it: how fast real droplets of each size move.

This is not droplet sizing. The droplets come in with a known size and speed; the question is where the gas takes them.

## Ground rules

- **Free software only** (Ben): Python (the `phantom` env on the Mac), OpenFOAM, ParaView, PyVista / Plotly; Ansys
  Student only as a free fall-back. (FluidX3D was planned and dropped, 2026-10-23: Phase 2.)
- **Machines:**
  - the Mac (`phantom` env; OpenFOAM) for everything: the simple model, the chamber airflow, plotting and analysis;
  - the lab PC for captures.
- **Phase-gated:** do the phase, stop, report, and wait for Ben's go before the next.
- **Raw captures on the LaCie are never modified.** Everything writes to its own output folder.
- **Every number that is assumed rather than measured is labelled as such,** in the settings file and on the figures.

---

## Phase 0. Ben's answers (2026-10-23)

| Question | Answer |
|---|---|
| The chamber | Built in Fusion (any export format). About 300 × 200 mm in plan and 350 mm tall. |
| Air in and out | Air enters on the RIGHT and leaves on the LEFT. Inlet and outlet positions and sizes are not decided: Ben wants to **edit them**. |
| Gas and flow | Air, from a supply of up to 5 bar; flow probably about **8,000 sccm**. Editable. |
| What "working" means | **Delivering a size band to a target**, the band editable, starting at **30–60 µm**. |
| How accurate | **Numbers and graphs for the thesis, and trends.** So Phase 4 (checking against the rig) is needed, not optional. |
| GPU | RTX 5060 Ti, 16 GB dedicated. (Not needed since FluidX3D was dropped, 2026-10-23: OpenFOAM runs on the Mac's CPU.) |
| The spray's position and direction | **Editable**, like the ports. Default top centre, pointing straight down (a design choice, not a measurement). |
| Which droplet sizes | **Editable:** both the sizes fired in and the band to deliver (see the settings file). |
| Purity | **By number and by volume of liquid, both as headlines.** |
| The physical chamber | Not built yet; it will be soon. Phase 4 waits for it. |
| Phase 4 agreement | Checked on quantities where the spray's production rate cancels (see Phase 4). |
| The target | **The left outlet.** |
| Axes | **The air crosses the 300 mm length:** it comes in through the right-hand 200 mm wall, square to it, and leaves through the left. |

---

## The settings file: everything Ben can edit

One commented settings file (YAML) per scenario. The same file drives Phase 1 (the simple model) and Phases 2–3 (the
real chamber), so a design change is made in one place. Each value is marked **measured**, **estimated** or
**design choice**, and the file is copied into every output folder.

- **Chamber:** the box size (300 × 200 × 350 mm to start), or the STL exported from Fusion.
- **Inlets** (any number; the first is on the right wall):
  - which wall, the position on it, the shape (round or slot) and size;
  - the flow (sccm or L/min) and its direction.
- **Outlets** (the first is on the left wall): which wall, position, shape and size.
- **The spray** (moved and turned like the ports; Ben, 2026-10-23):
  - the nozzle's position (x, y, z in mm) and direction (tilt from straight down, and which way it leans); default
    top centre, straight down;
  - its own gas: flow (sccm), orifice (mm) and the orifice's measured Cd, so the jet's momentum is right (see below).
    It enters the chamber too;
  - the droplets: sizes (a list, a range, or a measured size distribution from a CCD run), speed by size, spread, how
    many.
  - **Decided (Ben, 2026-10-23):** the droplets start where they are measured, at the shadowgraph window's distance
    along the nozzle axis, not at the orifice. Moving or tilting the nozzle moves that start with it.
- **The target:** a region (e.g. the left outlet, or a box or plate anywhere) and the **size band** to deliver
  (30–60 µm to start).
  - **Changing the band needs no re-run.** Every droplet's size and fate are saved, so delivery and purity for any
    band are recomputed from a saved run. Only a change to the sizes fired in needs a re-run; by default they span
    10–200 µm, so any band inside that is already covered.
- **The gas:** air at 20 °C and about 1 atm in the chamber (5 bar is the supply side, before the flow controller).
- **Physics switches:** gravity, the drag law, the turbulent random walk.

**The first scenario's defaults** (every one editable; placeholders are swept in Phase 1, not trusted):

| Setting | Default | Marked |
|---|---|---|
| Axes | x along the 300 mm length (0 = the left wall with the outlet, 300 = the right wall with the inlet); y across the 200 mm; z up from the floor, 0–350 | |
| Nozzle | top centre (150, 100, 350), pointing straight down | design choice (Ben) |
| Spray gas and droplet sizes | one CCD run's gas flow, orifice (with its measured Cd) and measured size distribution; default the best run, 131450 | measured |
| Droplets below 30 µm | a flagged 10–30 µm range, counted from the same run | estimated (counted, not sized) |
| Droplet start | on the nozzle axis, at the stand-off (orifice to shadowgraph image centre) | estimated until the velocity rig day measures it |
| Droplet speed | 6 m/s down the axis, every size alike (swept 4–8) | estimated (mass balance) until Phase 5 |
| Inlet | round, 6 mm, centre of the right wall at mid-height (z = 175), 8,000 sccm, square to the wall | design choice (placeholder) |
| Outlet = target | round, 25 mm, centre of the left wall at mid-height | design choice (placeholder) |
| Band | 30–60 µm | design choice (Ben) |

**Inlets and outlets are drawn from the settings file, not the CAD.** Phase 2 marks them as patches on the chamber
walls, so moving or resizing one needs no new CAD export. Once a design is chosen, the real ports can come from the
CAD.

**A layout picture before every run.** The model draws the scenario from its settings file (side and top views: the
walls, the ports, the nozzle and its axis, where the droplets start, the target) so a moved part can be checked before
anything runs.

**Any setting can be swept.** List the values in the file's `sweep:` section by the setting's dotted path (e.g.
`spray.tilt_deg: [0, 15, 30]`, `inlets.0.diameter_mm: [4, 6, 10]`) and one run is made per combination, with the
trend charts drawn across them. A sweep file can start from another with `base: first_scenario.yaml` and give only
what differs, so a design change is made in one place.

---

## What the numbers already say (first estimates, to be confirmed by Phase 1)

- **8,000 sccm is a slow drift if spread over the chamber.** 8 L/min across the chamber's 200 × 350 mm side is about
  **2 mm/s**. The air only moves fast as a jet from the inlet, and the inlet's size sets that speed:

  | Inlet at 8,000 sccm | Area | Jet speed at the inlet |
  |---|---|---|
  | round, 25 mm | 491 mm² | 0.27 m/s |
  | slot, 100 × 2 mm | 200 mm² | 0.67 m/s |
  | round, 10 mm | 79 mm² | 1.7 m/s |
  | round, 6 mm | 28 mm² | 4.7 m/s |
  | round, 4 mm | 13 mm² | 10.6 m/s |

- **A uniform drift cannot carry the band across.**
  - A droplet that settles at v_t while drifting at U travels U × h / v_t sideways while falling h.
  - Settling speeds: 30 µm about 3 cm/s, 60 µm about 12 cm/s.
  - To carry a 60 µm droplet 300 mm across while it falls no more than 350 mm takes U ≈ 10 cm/s. Over the whole
    chamber side that is about 400 L/min, 50 times the 8 L/min available.
  - So delivery has to come from where the inlet jet goes, not from a general drift.
- **The spray's own gas is the strongest flow in the chamber, by far.**
  - The atomiser puts 7,000–12,000 sccm through a 0.5–1.2 mm orifice.
  - **Corrected:** the 100–460 m/s quoted earlier is gas flow ÷ orifice area at standard density, an equivalent, not
    the exit speed. The small orifices choke, so the real exit is sonic and the gas there denser (`docs/definitions.md`).
    Every jet is therefore set by its **mass flow and momentum**, not an exit speed.
  - The momentum depends on the effective bore. **Corrected again (Phase 1, isentropic exit with the Cd; the first
    figures here were incompressible with Cd 1):** 10,200 sccm through the 1.2 mm insert is 50 mN at its measured Cd
    (0.527; Mach 0.77 at the exit, not choked), 35 mN if it were clean (Cd ~0.82, like the 0.5 and 0.8 mm inserts).
    CCD run 131450 (8,995 sccm, the first scenario): 40 mN.
  - A round jet slows as about 6 × √(4J/πρ) / distance: at 40 mN about 11 m/s at 100 mm and 4 m/s at 300 mm below the
    nozzle (single-phase; the liquid loading changes it).
  - It drags in the chamber air: about 27× its own gas by 100 mm and 80× by 300 mm (~800 L/min). That sets up the
    chamber's circulation.
  - The 8,000 sccm inlet has 1/24 (4 mm inlet) to 1/950 (25 mm) of 131450's spray momentum. So the chamber's
    circulation is the spray's, the cross-stream competes only near its own jet, and the spray jet must be in every
    model.
- **A band needs two cuts.**
  - Large droplets are easy to remove: they settle or hit a wall.
  - Small ones are harder: anything that carries 60 µm to the target carries 20 µm even more easily.
  - If it matters which sizes reach the target (purity), the design needs a second cut that sends the small ones
    with the air somewhere else, e.g. the air turns and the small droplets follow it while 30–60 µm carry on.
  - The models report both how much of the band arrives (delivery) and what else arrives (purity).
- **Droplets below 30 µm are counted, not sized.** On the best CCD run (131450) they are ~5× more numerous than
  30–60 µm. For purity they are the main unwanted arrivals, but their sizes are unknown. They go in as a range
  (e.g. 10–30 µm) and are flagged.
- **The mesh (superseded 2026-10-23):** the uniform-grid estimate for FluidX3D (0.5 mm, ~170 million cells) no
  longer applies. OpenFOAM's graded mesh is an estimated 1–5 million cells (Phase 2).

---

## The physics, in short (why this is tractable)

- **One-way coupling.** At our concentrations (~100 droplets per cm³) the liquid is ~0.0007 % of the volume, so the
  droplets do not change the gas. The gas flow is solved once; droplets are then fired through it.
  - **The exception is the spray jet** near the nozzle, where the liquid's mass is similar to the gas's. There the
    spray is entered as a jet plus droplets with measured speeds, not solved.
- **Forces on a droplet: drag and gravity (with buoyancy).** Drag uses Stokes' law with the Schiller–Naumann
  correction, f = 1 + 0.15 Re^0.687, valid to Re ≈ 1,000.
- **What can be left out:**
  - evaporation: the silicone barely evaporates;
  - breakup: a 100 µm drop at 10 m/s in air has a Weber number below 1, far under the ~12 needed;
  - collisions: the spray is dilute away from the nozzle.
- **Walls:** a silicone droplet that touches a wall sticks.
- **One number per size,** the relaxation time τ = ρ_d d² / 18 µ_g. For EcoFlex 00-30 (1,070 kg/m³) in air, Stokes:

  | Droplet | τ | Settling speed | Stops within, from 4 m/s in still air |
  |---|---|---|---|
  | 30 µm | 3 ms | 3 cm/s | ~12 mm |
  | 50 µm | 8 ms | 8 cm/s | ~33 mm |
  | 60 µm | 12 ms | 12 cm/s | ~47 mm |
  | 100 µm | 33 ms | ~0.3 m/s | ~13 cm |
  | 150 µm | 74 ms | ~0.5 m/s | ~30 cm |

  Settling speeds hold (**Corrected:** 100 and 150 µm include the Schiller–Naumann correction; Stokes alone gives
  0.32 and 0.72 m/s). The stopping distances do not: at 4 m/s every size starts past Stokes
  (Re ≈ 8 at 30 µm, 16 at 60 µm), so with Schiller–Naumann they stop about a quarter (30 µm) to a third (60 µm)
  sooner (~9 mm and ~31 mm), and the larger sizes sooner still.

---

## Phase 1. The simple model: idealised airflow, real droplet physics (Mac, Python)

**Why.**
- It gives the trends in seconds: how the band's delivery and purity change with inlet flow, size, height and
  position, and with the spray settings.
- Its droplet code is reused unchanged in Phase 3, where the real chamber flow replaces the idealised one.

**What it is not.** The idealised flows are textbook jets added together. They ignore how the jets bend each other
and the circulation they set up together. So Phase 1 gives **trends and orders of magnitude**; the thesis numbers
come from Phases 2–4.

**Decided (Ben, 2026-10-23):** added-together free jets have no recirculation and do not conserve mass in a closed
box, and the spray's circulation dominates the chamber. So Phase 1's delivery to the target is not trustworthy even
as a trend. Its headline is instead how far the spray jet and each inlet jet carry or deflect each size (where each
size crosses a chosen plane). Delivery and purity are still computed, flagged as idealised; the thesis ones come from
Phase 3.

**The airflow, built from the settings file:**
- **The spray jet:** a round turbulent jet from the nozzle (the textbook self-similar profile: speed falling with
  distance, spreading at a fixed angle), from the spray gas flow and orifice.
- **Each inlet:** a round or slot jet from its wall patch, the same way.
- **The background drift:** inlet flow ÷ chamber cross-section, towards the outlets.
- **The chamber:** the box with its walls, outlets and target region.

**The droplets:** sizes or a measured CCD size distribution, a starting speed and direction, a spread at the nozzle
(width and cone angle), and so many per size.

**Equations:**
- drag (Stokes + Schiller–Naumann) and gravity with buoyancy;
- integrated with the analytic exponential step that Fluent's particle model uses: exact for a constant local gas
  velocity, so it stays stable for the smallest droplets;
- an optional turbulent random walk (set intensity and time scale; off by default).

**Each droplet ends as one of:** reached the target, left through another outlet (which), stuck on a wall (where),
or still airborne at the time limit.

**Outputs.**
- **For the size band (30–60 µm unless changed):**
  - **delivery:** the share of the band's droplets that reach the target;
  - **purity:** the band's share of everything that reaches the target, by number and by volume, both as headlines
    (Ben, 2026-10-23).
- **Delivery against droplet size** (a curve per setting), with the band shaded.
- **Paths coloured by size,** side and top views, over the chamber outline, with the air shown as arrows.
- **Where each size ends up:** the target, each outlet, each wall.
- **Trend charts from sweeps:** e.g. the band's delivery and purity against inlet flow, inlet height and inlet size
  (contour maps for two at a time).
- **Speed against distance** for each size.
- **A table per size:** τ, settling speed, Stokes number in the inlet jet, the share reaching the target.
- **A CSV of every droplet,** and a short report that lists every estimated input.

**Checks (tests, before any result is believed).**
- A droplet released at rest in still air reaches the terminal speed that the drag law gives.
- In uniform flow with Stokes drag, the integrator matches the exact solution, even with large time steps.
- At higher Re, Schiller–Naumann shortens the stopping distance against Stokes, by the expected amount.
- A very small droplet follows the gas; a very large one barely notices a jet; the deflection falls steadily with
  size.
- The jet model gives the textbook centreline decay and spreading rate.
- With the random walk off, the result is repeatable; with it on, the spread grows but the mean path does not move.
- Every droplet is accounted for (target + outlets + walls + airborne = all).

**Folder layout (built 2026-10-23):**
- `Flow Visualisation/PLAN.md` (this file) and `README.md` (how to run it, with the commands);
- `run.py` (a scenario or a sweep) and `import_sizes.py` (a run's measured size distribution, read only);
- `Flow Visualisation/droplet_transport/`: the code (physics, flow, tracker separate from plots and report);
- `Flow Visualisation/settings/`: one commented settings file per scenario (`first_scenario.yaml`, two example
  sweeps, and `sub30_*.yaml`: the same three with the band under 30 µm);
- `Flow Visualisation/data/`: imported size distributions;
- `Flow Visualisation/tests/`;
- `Flow Visualisation/output/`: Phase 1's results, not committed to git. Phase 3a's droplet runs go to
  `~/OpenFOAM/droplet_runs/` (one folder per run).

**Time:** building it (the code, the checks above, the first figures) is the 1–2 days at most; running it takes
seconds a scenario and minutes a sweep. Then stop and report with the figures.

### Phase 1 status (2026-10-23): BUILT, awaiting Ben's review

- **The tool:** `droplet_transport` 1.0.0; `run.py` (a scenario or a sweep, ~10 s a scenario: 19,200 droplets with
  the inlets on and again off), `band.py` (another band from a saved run), `import_sizes.py`. How to run:
  `README.md`. 50 tests pass: every check above (Schiller–Naumann's stop against an ODE solve within 2 % at the
  default 0.5 mm step; the jets' decay, spread and mass conservation; entrainment within 10 % of Ricou & Spalding),
  plus the gas dynamics (the Cd test's 2.41 barA), the settings and the importer (the same rule as master_log's
  size-band columns).
- **Inputs (2026-10-23, later):** CCD 131450's measured size distribution imported (`data/ccd_131450_sizes.csv`,
  sizer 3.1.0: 13,154 sized, 64,841 counted below 30 µm, i.e. 83 % below d_min), so purity is computed; stand-off
  55 mm (Ben's estimate, until the rig day measures it).
- **First scenario** (nozzle top centre, straight down; CCD 131450's spray, 40 mN; 6 mm / 8,000 sccm inlet at
  mid-height): every size goes to the floor. The inlet pushes the 30–60 µm band 5.5 mm towards the outlet by the
  time it nears the floor (10 µm 6.9 mm, 200 µm 1.7 mm).
- **Inlet size × flow** (4 / 6 / 10 mm × 8,000 / 16,000 / 32,000 sccm): the band's push grows about as flow ÷ diameter
  (the jet's √J), 3.4 to 29 mm; **none of the band reaches the outlet in any of the nine**. The strongest (4 mm,
  32,000 sccm: ~42 m/s, 26 mN, two-thirds of the spray's momentum) carries 10–22 µm to the outlet (42 % of the
  10 µm ones): a fines cut, the 'second cut' above, not delivery.
- **Nozzle tilted towards the outlet** (0–60°): only 45° delivers: **6.0 % of the band by number (7.3 % by volume),
  purity 74.6 % by number (55.8 % by volume)**; with the inlet off 8.5 % and 44.2 % (the cross-jet keeps fines away:
  arrivals under 30 µm 52 % → 18 % by number). Delivery peaks near 16 % around 100 µm, none under 26 µm. The jet's
  axis meets the left wall ~25 mm above the outlet's centre, so the small droplets that follow the gas miss and the
  heavier ones drop into it. 30° (axis meets the wall ~90 mm up) and 60° (~263 mm) miss. Sensitive to aim: worth a
  finer sweep before believing the percentages.
- **What it says, idealised:** the spray's own jet decides where droplets go; a cross-stream of this size nudges
  them by millimetres; aiming the spray is the stronger lever. Phases 2–3 are needed for numbers: no recirculation
  here, and the jets pass through walls.
- **Flags it raises itself:**
  - 10–76 µm hit the floor while their Stokes number in the spray jet there is under 1: in the chamber they would
    turn with the air. An artefact of the idealised jet.
  - The gas-only spray jet is 20 m/s at the 55 mm stand-off, against droplets started at 6 m/s: the small ones speed
    up to the gas within millimetres. Either the liquid loading slows the real gas there, or the droplets are faster
    than the mass-balance estimate. Phase 5's speeds by size settle it.
- **A band under 30 µm (Ben, 2026-10-23):** 10–30 µm (the model fires down to 10 µm; the measured sub-30 droplets
  are counted, not sized, and spread evenly: estimated). Re-banded from the saved runs (`band.py`) and re-run with the
  band shaded (`settings/sub30_*.yaml`). The jet model delivers almost none: 13.2 % (4.6 % by volume) through the
  4 mm inlet at 32,000 sccm and 0.7 % through 6 mm, both 100 % pure; 0.4 % at 45° (2.6 % with the inlet off); 0
  elsewhere. But these sizes follow the air (St ≪ 1) and the jet model sends its air through the floor, so they are
  the sizes it handles worst. The opposite idealisation, a perfectly stirred chamber (leave with the air or settle:
  Q ÷ (Q + v_t × floor area); script and figure in `output/band_under_30_um_comparison/`), lets 31 % of the band out
  at 8,000 sccm and 50 % at 32,000 sccm (30–60 µm: 10 % and 22 %), 92 % of the arrivals under 30 µm. The real
  chamber lies between: Phases 2–3 decide. In the stirred picture more gas flow flushes fines out faster.
- **Floor collection (Ben's idea, 2026-10-23):** the collection area on the floor (40 × 40 mm), the 4 mm /
  32,000 sccm side jet to push the small droplets aside, and a 6 mm jet from the lid to push the band down
  (`settings/floor_collection.yaml`; sweep of the area's position × the down jet's flow,
  `settings/sweep_floor_collection.yaml`). Jet model, 30–60 µm band: with the area at x 100–140 mm and no down jet,
  **77 % delivered at 42 % purity by number**; moving it to x 120–160, 37 % at 61 %. The down jet raises delivery
  (93 % at 8,000 sccm, 99 % at 16,000) but lowers purity (30 %, 25 %): it drags the fines down into the area too, so
  the side jet does the sorting and the down jet works against it. **Not modelled:** whether arrivals stick. A jet
  hitting a plate is an impactor: the spray jet at the floor (350 mm, 3.4 m/s, ~67 mm wide) has an estimated 50 % cut
  of ~27 µm (Stk50 0.24), rising in step with the plate's distance from the nozzle (12 µm at 150 mm), so the plate
  itself would turn many fines away and the plate's height is a size knob. The report now flags arrivals on a target
  lying on the wall the spray hits as an upper bound. Open (Ben): is the collection area a solid plate (impaction) or
  an extraction outlet (the fines follow the air into it)?
- **Deck of the results** (20 slides, each figure with what it shows and how to read it):
  https://claude.ai/artifact/2aRQfYQT4WvsE9RvpsQ9wh
- **Still needed:** the stand-off and the droplet speeds by size, measured on the velocity rig day. Worth deciding
  (Ben): is aiming the nozzle an option on the rig, and should a strong cross-jet be the fines cut?

---

## Phase 2. The real chamber's airflow (Mac, OpenFOAM)

**Why.** The jets bend each other, set up circulation and leave dead zones; where the band goes depends on all of it.
These are the numbers for the thesis.

**Method (Ben, 2026-10-23): OpenFOAM, steady RANS, on the Mac.** FluidX3D (lattice Boltzmann, home PC GPU) was
planned and dropped the same day:
- Its grid is uniform, so the 1.2 mm spray exit could not be resolved.
- The spray would have gone in as a larger inlet with the same momentum but 4–8x the real gas. The spray's 8,995 sccm
  is about half the chamber's through-flow, so the outlet flow would have been ~2.6–4.7x too high, overstating the
  fines' delivery.
- OpenFOAM's mesh can be fine at the exit and coarse elsewhere. Steady RANS gives exactly what Phase 3's random walk
  needs: the mean flow plus k and omega in every cell. It is the usual method for spray and aerosol chambers.
- It is GPL: free for any use, and publishing results places no obligation on us (we write case files, not
  OpenFOAM).

**What.**
1. **Install.** OpenFOAM v2606, the native Apple Silicon build (Homebrew tap `gerlero/openfoam`, built from
   OpenCFD's source), and ParaView. Run a standard tutorial to check it works and to time the Mac.
   **Done 2026-10-23:** OpenFOAM v2606 and ParaView 6.2.0 installed with Homebrew; the pitzDaily tutorial
   (simpleFoam, 12,225 cells) converged in 283 iterations, 5 s. Too small to time a chamber case: the first box
   case does that.
   **Also 2026-10-23 (Ben, to learn CFD hands-on):** FreeCAD 1.1.4 + the CfdOF add-on (a GUI for OpenFOAM) and
   cfMesh (built against v2606); Ben's step-by-step guide `Flow Visualisation/cfdof/CFDOF_GUIDE.md`, answer key
   `cfdof/chamber_box.FCMacro`. Checked by script: the box with the 6 mm inlet and 25 mm outlet, 67,000 cells,
   2,000 iterations in 64 s on 10 cores, gas in = gas out; with the 0.91 mm spray, 83,000 cells, 78 s, up to
   245 m/s at the nozzle, but the velocity residuals stall near 1e-2 (step 5's steady-or-not question). Learning
   cases only: far too coarse along the jet.
2. **Geometry.** A plain box first. Later, the Fusion STL of the chamber's inside (the air volume, in mm, watertight)
   once the ports are designed.
3. **Mesh.** Fine at the spray exit (~10 cells across it) and along the jets, a few mm in the far field: an estimated
   1–5 million cells (the first mesh sets it). Inlets and outlets are patches placed from the settings file, so they
   move without a new CAD export.
4. **The spray jet:** its real gas flow AND its real momentum. At chamber density both together fix an inlet of
   0.91 mm at 226 m/s (Phase 1's d0; the measured Cd is built in).
   - Start incompressible (simpleFoam). The real exit is Mach 0.69, so the density is off in the first few
     diameters. Check one setting with the compressible solver (rhoSimpleFoam).
   - To decide here: whether the liquid's momentum is added to the gas's.
5. **Turbulence: k-omega SST**, the usual choice for jets and recirculation.
   - Check one setting with a second model (realizable k-epsilon): how much the answer depends on the model.
   - RANS jets spread at a model-dependent rate: check a lone jet against Hussein 1994 (S = 0.094).
   - A closed box with a jet hitting the floor may not settle to a steady state. If a setting does not, run it in time
     (pimpleFoam) and average.
   - **Decided (Ben, 2026-10-23):** a time-averaged flow plus Phase 1's random walk, its turbulence from k and omega.
6. **Case from the settings file.** Python writes the OpenFOAM case (mesh, ports, flows) from the same YAML settings.
   Editing an inlet needs only the settings file. Runs from one script; results in `output/` like Phase 1.
7. **Run and export.** Run until the residuals, the outlet flow and a few probe velocities stop changing. Export to
   VTK for ParaView and Phase 3.
8. **Run time:** an estimated one to a few hours a setting on the M5 Pro (15 cores, 24 GB), unmeasured until step 1.
   Long runs plugged in under `caffeinate`, ideally overnight.

**Outputs:** ParaView figures and videos:
- colour-mapped slices through the chamber at chosen planes;
- streamlines from each inlet and from the spray;
- surfaces of equal speed (recirculation and dead zones);
- fly-throughs.

**Checks.**
- Gas in = gas out.
- The same answer on two meshes (the grid check: the sweep on one mesh, one setting on a finer one).
- A lone inlet jet decays and spreads at the textbook rates.
- The two turbulence models, and incompressible against compressible, on one setting.

**Time:** a few days of setup (OpenFOAM is new), then hours of CPU a setting. Stop and report.

---

## Phase 3a. Droplets through the CfdOF baseline: first pass (Mac) — Parts A–D done (Ben's go 2026-10-25); stopped for review

**Why.** The first answer, in the real chamber's geometry, to "where does each size go with just the spray running", and
a floor deposit map to lay over Ben's 3 × 3 slide grid: the first check of flow + droplets against the rig. It also
builds the machinery that Phase 3 reuses for the cross-stream designs.

**What it runs on.** Ben's guide Part 6 case (`~/OpenFOAM/cfdof_cases/Chamber_v1_jet/case`: 198,682 cells, jet refined,
the spray as drawn, 1.0 mm). Read-only: the droplet run works in its own copy.

**The tracker (decision for Ben).**
- **Recommended: OpenFOAM's own particle tracker**, `uncoupledKinematicParcelFoam` (part of the installed v2606). It moves
  droplets through a frozen flow on the same mesh and walls the flow was solved on, and comes with drag, gravity,
  turbulent dispersion from the k field (`StochasticDispersionRAS`), sticking on walls, and recorders (which droplet
  hit which wall, where, at what size; counts through any polygon, e.g. each slide). ParaView reads its output
  directly: droplets as moving dots coloured by size.
- **Python (Phase 1's code) keeps the inputs and outputs:** the measured size distribution in; band delivery and
  purity, per-slide counts, figures and the report out. Its integrator cross-checks OpenFOAM's tracker in simple
  flows.
- The alternative, as Phase 3 first said: extend Phase 1's Python tracker to walk through the OpenFOAM mesh. Same
  droplet code throughout, but finding droplets among 200,000 irregular cells and detecting the walls is real work
  that OpenFOAM's tracker already does well. Choosing OpenFOAM's changes Phase 3 to "OpenFOAM tracker + Python".

**Steps.**
1. **A settings file** (`settings/droplets_baseline.yaml`, Phase 1's style: every value marked measured / estimated /
   design):
   - the flow case and which saved iterations;
   - where droplets start: the shadowgraph window, 55 mm below the hole along the jet (estimated), a 5 mm-radius disc,
     10° cone half-angle (as Phase 1);
   - sizes: 2–200 µm, an equal number fired per size (as Phase 1), weighted afterwards by CCD 131450's measured
     distribution (the counted-not-sized sub-30 droplets spread over 10–30 µm, estimated) or any imported run;
   - start speed 6 m/s (estimated; Phase 5 replaces it); silicone 1,070 kg/m³;
   - the slide test's timing: the exposure (a few seconds) and the settling time after switch-off (both settings);
   - the slide positions come later, with the slide-comparison code (see Later, below).
2. **Python writes and runs the particle case** (a copy of the flow case plus the cloud settings and the injection
   table): one paste-able command.
3. **Physics:** drag (OpenFOAM's sphereDrag; Phase 1's Schiller–Naumann differs by < 3 % up to Re 10, nil below Re 1), gravity, turbulent dispersion on (one run with it off to show its
   effect); droplets stick wherever they touch a wall (silicone sticks); the port mesh records and stops them; one-way
   (droplets do not push the air).
4. **The stages of the slide test** (Ben, 2026-10-25): warm-up into the bin with the slides covered (~20 s); bin away and
   slides uncovered for the exposure (a few seconds; the whole spray is 45 s at most); then the system switched off and
   the droplets left to settle.
   - **Warm-up: not modelled.** When the bin comes away, the jet reaches the floor in ~0.1 s and the circulation
     re-forms in ~1–2 s, short against the exposure.
     **Flag for the rig:** the covers keep warm-up droplets off the slides only while they are on. Most of the fines
     (below ~20 µm) follow the gas back out of the bin, stay in the air for minutes, and will settle onto the slides
     once uncovered, on top of the exposure's. Ways round it: a control run (the same sequence with the bin left on,
     slides uncovered at the same moment), a fine filter over the bin's exhaust, or a shorter warm-up.
   - **Stage 1, exposure:** droplets fed in continuously through the free-jet flow (Ben's Part 6 case) for the
     exposure time (a setting).
   - **Stage 2, system off: still air.** The jet stops at once and the chamber's circulation dies away over a few
     seconds. Bracket it: the flow kept running for 0, 2 and 10 s after switch-off, then still air, in which each
     droplet settles straight down from where it is. Rough well-mixed numbers: a 60 µm droplet settles at 12 cm/s and
     is mostly down during the exposure; at 30 µm (2.9 cm/s) and 10 µm (0.3 cm/s) ~90 % or more of the band is still
     in the air at switch-off, so this stage decides where the band lands.
   - **Settling time = the smallest size collected** (falling the chamber's full 0.69 m in still air): 30 µm ~24 s,
     20 µm ~53 s, 10 µm ~3.6 min, 5 µm ~14 min. The model uses the same wait as the rig (a setting); slides taken out
     earlier miss the smallest sizes.
   - The shut-off dribble and big drops under the nozzle: not modelled (Ben accepts them; the centre slide shows them).
5. **Snapshot check** (the flow never fully settles): the same run on saved iterations 1000, 1500 and 2000, and on the
   Part 5 (coarse jet) case. If the deposit maps agree, one snapshot is enough; if not, the time-dependent solver
   (pimpleFoam) moves up the list.
6. **Outputs** (a folder per run, as Phase 1):
   - **in ParaView:** droplets as moving dots coloured by size (the exposure and the settling), their paths, and deposit
     maps on the floor and walls;
   - **fates by size:** floor, each wall, the nozzle block and atomiser body, the port mesh, still airborne; by number
     and by volume;
   - **the floor deposit map by size band** (0–10, 10–20, 20–30, 30–60, > 60 µm) and **per-slide counts by size**, in
     the same table layout as Ben's microscope results, so the two lie side by side;
   - where the 0–30 µm band ends up; `report.md` with flags (as Phase 1).

**Checks.**
- Every droplet fired is accounted for.
- In still air, settling speeds match Phase 1's physics within 1 %; a few droplets tracked by both OpenFOAM and Phase
  1's integrator in a uniform flow agree.
- Large droplets (> ~80 µm) land near the jet's impact point, as in Phase 1.
- Dispersion on vs off: the fines' map changes, the large droplets' does not.

**What it cannot say yet (flagged in every report).**
- Sub-30 µm sizes are estimated (counted, not sized): the slides measure them.
- The start speed is estimated (Phase 5 measures it).
- Near the nozzle the liquid carries as much mass as the gas; its push on the air is left out (Phase 2's open
  question).
- The flow is one steady snapshot of a flow that sways (step 5 says how much that matters).
- Droplets stick where they touch: no bounce, splash or coalescence.

**By clicking?** No: CfdOF has no droplet tracking. A run is one command (edit the settings file, paste the command);
everything is then viewed in ParaView, with the figures and report.

**Time:** an estimated 1–2 days to build; a run from minutes to about an hour (droplet count and settling time;
measured on the first run). **Stop and report** after the first baseline run with the snapshot check, before any
cross-stream work.

**How the comparison with the slides works.** The model gives, per slide, the number of droplets of each size per
droplet fired; the microscope gives stains per slide, converted to droplet sizes with the spread calibration. The
total number of droplets the spray makes is only known to ±50–60 %, so the first comparison is of **patterns**: how
the counts share out across the 9 slides, and how the size mix shifts from the slide under the nozzle to the outer
ones. Absolute counts are compared second.

**Decided (Ben, 2026-10-24/25):** OpenFOAM's tracker. The rig sequence: warm-up into the bin with the slides covered,
bin away and slides uncovered for the exposure, then the system off and the droplets left to settle (no bin in the
model). Build approved 2026-10-25, in parts with a check-in after each (Ben: "come back to me at every major part").

**Later (not part of Phase 3a's first build):** the slide comparison as code. It reads the microscope results per
slide, converts stain sizes to droplet sizes (the spread calibration), takes the slide positions, and lays them over
the model's per-slide prediction (patterns first, then absolute counts). The slide positions come in then; until then
the floor map covers the whole floor.

### Phase 3a status (2026-10-25)

**Part A, the tracker proof: DONE.** 10 / 30 / 100 µm, 5,000 each, through Ben's Part 6 flow; 5 s exposure, 5 min of
still air; every droplet accounted for; shown in ParaView (`../cfdof/CFD_LOG.md` section 6).

**Part B, the tool: BUILT** (awaiting Ben's go for Part C). One command, `run_droplets.py` with
`settings/droplets_baseline.yaml` (README.md, "Droplets through the CFD flow"; `cfdof/HOW_TO_REDO.md` step 7):
- copies the CfdOF case's chosen iteration (reconstructed once into `~/OpenFOAM/droplet_runs/flows/`, reused);
- writes and runs one OpenFOAM case per run (gusts on/off × flow kept 0 / 2 / 10 s after switch-off: 6 runs, all at
  once), under `~/OpenFOAM/droplet_runs/<name>/<date_time>/` (OpenFOAM cannot work in a path with spaces);
- 100 sizes (2–200 µm), 200 of each by default = 20,000 droplets a run, fed in evenly over the exposure; ~30 s a run;
- collects every droplet's fate (floor, each side wall, lid, the atomiser / nozzle block / arm, port mesh or tube,
  back up the spray hole, airborne), when and where it landed, and whether it was airborne at switch-off:
  `droplets.csv`, `fates_by_size.csv`, `bands.csv`, `run.md` (tables by band, each size counted equally);
- a ParaView state per run (the flow during the spray on a cut through the hole, the walls' edges, every droplet
  coloured by size, the deposit building up; hidden: the 0–30 µm band only, the airborne only) and two pictures.
- 23 tests (`tests/test_cfd_droplets.py`; no OpenFOAM run); checked end to end in scratch: all six runs at 20 per
  size (~1 min), one at 200 per size (~30 s), every droplet accounted for, the state reloads with the flow and all
  droplets.

Choices made while building (why in `cfdof/CFD_LOG.md` section 6):
- one cone-nozzle injector per size, one droplet per size per time step, so the spray-stage step is exposure / per_size
  (25 ms at the defaults). Each droplet's lean is random 0–10°, not in proportion to its distance from the disc's
  centre as in Phase 1;
- a droplet leaves the tracking at its first wall touch (OpenFOAM's `escape`; its hit record keeps where and when),
  not `stick` (10× slower for the same answer); the landed droplets are written back into the frames for ParaView;
- still air steps 10 s (one frame a step); each frame's copy of the frozen flow is deleted (~150 MB a run is kept);
- rules that keep the switch-off on a saved frame: per_size a multiple of the exposure's frames (20), each flow-after
  time a whole number of frames (0.25 s); broken settings are refused with the reason.

**Part C, figures, report and checks: BUILT** (awaiting Ben's choice on the artefact, then Part D). Every run now
ends with `report.md` and `figures/` (`--report-only <output folder>` remakes them):
- **floor deposit maps by size band**, one per run and gusts on against off: seen from above, the atomiser body,
  nozzle block and arm outlined (from the mesh), the exit orifice and the port marked; colour = % of the band fired
  per cm² (smoothed, one log scale), lines round the densest half and 90 %;
- **where each size ends up**, every run: floor (split: landed while the air moved / in still air), side walls,
  atomiser, port, lid, back up the hole, airborne; and airborne at switch-off;
- **the 0–30 µm band weighted by the measured spray** (CCD 131450; in effect 10–30 µm, as the counted-not-sized
  droplets are spread from 10 µm), by number and volume, and its share of the floor's deposit;
- **the checks**, four OpenFOAM cases run alongside (~15 s each): accounting PASS; OpenFOAM's tracking against
  Phase 1's integrator PASS (speeds within 1e-6 %, paths within 0.1 mm); settling against Phase 1's physics within
  0.4 % below 60 µm, 1.7 % at 200 µm (sphereDrag against Schiller–Naumann); gusts on against off (the large
  droplets' deposit moves 0.2 mm, the fines' 15–21 mm); large droplets (≥ 80 µm) PASS, 90 % within 24 mm of the
  impact point; **tracers FLAG** (below).
- 14 more tests (`tests/test_cfd_report.py`); a full run of all six plus the checks takes ~1 min.

**Flag: the near-wall artefact (measured and explained; `../cfdof/CFD_LOG.md` section 6).** 0.5 µm tracers, which
follow the air, land on the floor: 62 % in 5 s with gusts off, 25 % with gusts on; the fired sizes to ~10 µm do the
same. They arrive at their settling speed with the air at rest, mostly on the first pass, within ~80 mm of the jet's
impact point; with gravity off none land; the time step does not matter. Cause: OpenFOAM interpolates the air
linearly in the cell against a wall (1.3 mm deep under the jet), so a droplet that follows the air is brought within
nanometres of the floor and settling finishes it; at a real wall the speed towards it falls with height squared and
the droplet is swept along. **Until fixed, the fines' floor and wall counts while the air moves are upper bounds and
their airborne shares lower bounds.** Landings in still air and the large droplets are not affected.
**Decision for Ben:** (a) correct the air in the wall cells to run parallel to the wall (prototype: tracers on the
floor 62 → 11 % gusts off; cheap, no new CFD); (b) a finer near-wall mesh under the jet and a new CfdOF solve; (c)
both, (a) now and (b) with Phase 2's thesis runs.

**Ben's choice (2026-10-25):** fix (a) dropped (a correction to the air, not the physics); (b) comes with the scripted
flow builder (Phase 2, "plan 1"), which also sets the orifice from code. Until then the flag stands in every report.

**Part D, the first baseline run and the snapshot check: DONE (2026-10-25; results below).** Ben: "setting this all up
so we can do many runs of this with different orifice sizes, and see what happens". So the snapshot check is built as
the general tool for that:
- **A sweep file:** a droplets settings file (`base:` the baseline) with a `sweep:` list. Each entry changes only what it
  names (a flow case, an iteration; later an orifice's flow case and its hole). One command runs the droplets through
  each in turn (each a full run folder with its own report.md), then compares them.
- **The comparison** (`comparison.md` and figures; also for any finished run folders, `--compare`):
  - the air itself: each flow sampled on a 10 mm grid; its mean speed and how far it is from the reference's (mean
    |ΔU| as % of the mean speed);
  - the 0–30 µm band weighted by the measured spray, every entry and run side by side, beside the gusts and flow-kept
    brackets we already carry;
  - floor maps by band, one row per entry; where each size ends up, one line per entry;
  - per band, against the reference: the floor share, the deposit's centre, its median spread, and the share of the
    deposit that lands in a different 20 mm square, each with the noise from the droplet count (the bootstrap);
  - each entry's checks (the tracers' artefact depends on the mesh).
- **Agreement:** a difference within the droplet-count noise (3 sd; the deposit moved, 2× what the count alone
  moves) is "the same"; beyond it but within a tolerance (5 points of floor share, 10 mm of centre or spread, 10 % of
  the deposit moved; settings) "close"; else "differs".
- **Runs:** the baseline (`droplets_baseline.yaml`, 200 per size, all six runs and the checks) and
  `droplets_snapshots.yaml`: iterations 1000, 1500 and 2000 of Ben's Part 6 case, and iteration 2000 of the Part 5 case
  (jet not refined, 85,535 cells), 600 of each size for a small droplet-count noise. A steady solver's iterations are not time, but these wander because the jet never
  settles (residuals ~1e-2): their spread stands in for the flow's swaying.
- **Done when:** both have run and the comparison says whether one snapshot is enough. Stop and report.

**Part D results (2026-10-25).** `~/OpenFOAM/droplet_runs/droplets_baseline/2026-10-25_140603/report.md` and
`~/OpenFOAM/droplet_runs/droplets_snapshots/2026-10-25_135054/comparison.md`; detail in `cfdof/CFD_LOG.md` section 6.
- **One snapshot is enough.** Iterations 1000 and 1500 against 2000: every band's floor deposit the same within the
  droplet-count noise (gusts on, flow kept 2 s); elsewhere at worst "close" (the large droplets' centre 0.4–1.7 mm,
  the fines' with gusts off 4–10 mm). The weighted 0–30 µm band's floor share within 1.3 points across the three,
  against the 42-point gusts bracket and 13-point flow-kept bracket. Yet the air itself differs by 28–39 % point by
  point (mean |ΔU|; mean speed the same): the circulation wanders, the droplets' answer does not. pimpleFoam is not
  needed for this.
- **The mesh matters more.** Ben's Part 5 case (jet not refined) differs in every fine band: the weighted 0–30 µm
  band's floor share +13 to +19 points (gusts on; per band +12 to +20), the fines' spread ~22 mm tighter, side walls
  30 → 16 %. Its tracers land 99 % (gusts off),
  against 62 %: the near-wall artefact is worse on that mesh. So the grid check and a near-wall layer (fix (b)) are
  what matter next, both part of the scripted flows.
- **Found and fixed: the time step.** Stage 1's step is exposure / per_size; at the old default (200, 25 ms) a tenth
  of the 0–10 µm droplets hit the side walls with gusts off (2 % at 8.3, 5 and 2.5 ms, which agree), and 13 % rather
  than 24 % were airborne at switch-off. Gusts on and the larger sizes do not depend on it. Default now 600 per size
  (8.3 ms; no slower: the still-air stage dominates, ~1.5 min for the six runs and checks); longer steps are flagged
  in report.md (check 7). Part C's "not the time step" holds for the floor share only.
- **Checks of the comparison itself:** the same flow at 200 and 600 per size, gusts on: every band "the same" (the
  noise model holds); the baseline and the sweep's iteration 2000 (identical settings) match droplet for droplet.
- Also fixed: runs started together no longer collide (their flow copy and case folders).
- **Everything for a run in one folder (Ben, 2026-10-25):** `~/OpenFOAM/droplet_runs/<name>/<date_time>/` holds the
  report, figures, ParaView views and the OpenFOAM cases (`openfoam/`, each with its own mesh files, hard-linked: no
  extra disk); `paraview/<run>.command` opens a view from wherever the folder has been copied or moved (checked: a
  copy in a path with spaces, the original hidden, opened with all its data). The two runs above were moved in.
  Phase 1's results (the fast Python model) stay in `Flow Visualisation/output/`.
- **Ben's views in every run (Ben, 2026-10-25):** each run's ParaView state also carries his CfdOF view's two slices
  and three streamline sets (hidden; his colour scale), and a second tab, a split of the droplets beside the air in
  his views with linked cameras, for screenshots. `--views-only <run folder>` remakes a finished run's views (the
  runs above were remade).
- The baseline's numbers (weighted 0–30 µm band, gusts on, flow kept 2 s): floor 64 % (57 while the air moves, the
  artefact's upper bound; 8 in still air), side walls 30 %, atomiser 5 %, port < 0.1 %; 17 % still airborne at
  switch-off; the band is 78 % of the floor's deposit by number, 32 % by volume. Gusts off: floor ~100 %.

**Next (Ben's choice):** the scripted flow builder (Phase 2, "plan 1": the orifice from code, a near-wall layer, the
grid check), planned first in this file; its flows then go through a sweep file (`settings/droplets_snapshots.yaml`
is the pattern) to compare orifice sizes.

---

## Phase 3. Droplets through the real chamber (Python, Mac)

**Why.** Phase 1's droplet code, in Phase 2's flow: the thesis numbers for delivery and purity. (The tracker is decided
in Phase 3a.)

**What.**
- Read the exported flow and interpolate it at each droplet position. Walls come from the mesh's wall patches
  (droplets stick); outlets and the target come from the settings file.
- The same inputs and outputs as Phase 1, now in the real flow:
  - the band's delivery and purity, and delivery against size;
  - where on the walls each size lands (deposition maps);
  - paths and animations;
  - an interactive 3D view that can be rotated in a browser (PyVista / Plotly; can be published as a web page).
- **Trends** come from running Phase 2 for a handful of settings (e.g. 3 inlet flows × 3 inlet heights).
  - Each run takes hours of CPU, so the sweep is chosen from Phase 1's trends: Phase 1 says where the interesting
    settings are, and Phase 2–3 gives the numbers there.
- **Size of the field:** a few million cells (mean velocity, k, omega): small enough to track on the Mac.

**Checks.**
- Where the chamber flow is simple, the results agree with Phase 1.
- Every droplet is accounted for.

**Time:** a few days. Stop and report.

---

## Phase 4. Check it against the rig (needed for thesis numbers)

**Why.** A simulation always shows plausible flow. Only a measurement says it is right.

**Options, cheapest first (to be planned in detail when Phases 1–3 are done):**
- **The existing shadowgraph.** Since sizer 3.1.0, every droplet's position in the frame is saved with its size.
  Compare the sizes, and how many of each, across the frame with the cross-stream off and on.
- **A collector at the target:** a slide or plate. Image and size what lands on it, and compare with the predicted
  delivered size distribution.
- **High-fps tracks (Phase 5's method)** where the inlet jet deflects the droplets.

**Agreement (Ben, 2026-10-23): checked on what does not depend on how many band droplets the spray makes.** That
rate is only known to ±50–60 % (CCD centre repeats vary by 21 %), so absolute delivery cannot be checked to ±20 %.
- The ratio of the band delivered with the cross-stream on to off, same spray, against the predicted ratio (the
  tolerance is set when Phase 4 is planned in detail).
- The shape of the delivered size distribution: the median size at the target within ±5 µm.
- Drops caught on a collector are caps, not spheres: sizing them needs a spreading correction for silicone on that
  surface, measured first.

**Waits for the chamber** (not built yet; soon, Ben 2026-10-23).

---

## Phase 5. Droplet speed: the high-fps capture and its analysis (to-do item 10; rig next week)

The capture is already planned in detail: `docs/VELOCITY_CAPTURE_PLAN.md`. In short:
- **The capture:** 256 × 1152 at 10,000 fps, 1 µs exposure: a 2.6 mm strip, the full 11.5 mm along the flow.
  - A 5 m/s droplet moves 50 px a frame, so it is seen ~20 times on its way through.
  - 3 s is ~30,000 frames (13 GB).
- **On the rig:**
  1. PCC check that a narrow window raises the frame rate (otherwise rotate the camera 90°).
  2. The exposure series (1, 4, 16, 40 µs).
  3. The captures: a first look of about 1.5 h (the CCD centre, the 3.1.0 best setting, the C7-like 0.5 mm run),
     or the full 15-capture set (~3.5 h).

**The analysis needs its own plan before any code** (Phase 5b, to write before the rig day):
- **Finding droplets in each frame:** whether the AI is needed, or a threshold on the background-divided frame is
  enough at 1 µs.
- **Linking them into tracks:** 2-frame pairs to ~10 m/s, 3-frame tracks above. Gating by size and direction.
- **Sizing:** the 3.1.0 sizer on each track (the track's sharpest frame, or the median over its frames).
- **Speed and slowing:** a fit of position against time along each track gives speed and deceleration. Grouped by
  size class and by position in the frame.
- **Checks:**
  - tracks do not jump between droplets (a synthetic test with known paths);
  - the streak speeds from the exposure series agree;
  - the measured liquid flux adds up to the syringe flow.

**It feeds:** the droplets' starting speeds in Phases 1 and 3 (replacing the 4–8 m/s estimate), the spray jet's
strength in Phase 2, and to-do 7b (speed weighting).

---

## Phase 6 (optional). Gas-only CFD of the nozzle (to-do item 11)

- **What:** the gas through the bubbler and orifice, in Ansys Student or OpenFOAM (compressible, since the 0.5 mm
  orifice chokes).
- **Validate it** against the Cd tests: the measured upstream pressure against flow (e.g. 2.41 barA at 12,000 sccm
  through the 0.8 mm insert).
- **Not needed** for the droplet transport. Gas + silicone inside the nozzle, and breakup into droplets, are not
  planned.

---

## Order

1. Phase 0: done (2026-10-23).
2. Phase 1: the simple model (built 2026-10-23; awaiting Ben's review).
3. Phase 5b: the speed-analysis plan, written before the rig day.
4. Phase 5: the rig day for speeds (next week).
5. Phase 3a: droplets through Ben's CfdOF baseline (Parts A–D done 2026-10-25: one snapshot is enough, the mesh matters more), checked against his slide grid.
6. Phase 2 and Phase 3, then Phase 4.
7. Phase 6 only if wanted.

## Decided (Ben, 2026-10-23)

Nothing is open for Phase 1.
- The target is the left outlet. The air crosses the 300 mm length, in through the right-hand 200 mm wall.
- The nozzle's position and direction are editable (default top centre, straight down), and so are the sizes fired
  in and the band delivered.
- Purity by number and by volume, both as headlines.
- The chamber is not built yet (soon). Phase 4 is checked on the cross-stream on/off ratio and the shape of the size
  distribution.
- Claude's four proposals, all accepted:
  - the droplets start at the shadowgraph window, along the nozzle axis;
  - Phase 1's headline is the deflection of each size, not delivery;
  - the Phase 2 sweep on one mesh, with one finer mesh as the grid check (was 1 mm and 0.5 mm for FluidX3D);
  - a time-averaged flow plus the random walk.
- Phase 2's method: OpenFOAM steady RANS on the Mac; FluidX3D dropped (Ben, 2026-10-23).

To measure, not blocking Phase 1: the stand-off (orifice exit to shadowgraph image centre), on the velocity rig day
(`docs/VELOCITY_CAPTURE_PLAN.md`).
