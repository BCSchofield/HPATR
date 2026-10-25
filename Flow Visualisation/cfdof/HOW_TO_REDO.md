# Redo the chamber CFD: the quick recipe

Everything done so far, as a checklist, so a run can be redone with a different nozzle, flow or chamber, droplets
included (step 7). The full explanations and screenshots-in-words are in `CFDOF_GUIDE.md` (Parts 5 and 6); why each
choice was made is in `CFD_LOG.md`. All three files are also linked from `~/OpenFOAM/cfdof_cases/`.

Current values (2026-10-24, chamber v1) are given as examples in **bold**; the "What changes" table at the end says
which ones to recompute.

---

## 0. Once per Mac (already done on this one)

- FreeCAD: **CfdOF → Open preferences → Append document name to output directory** ticked.
- FreeCAD: **Preferences → General → Units: Number of decimals 6** (else k = 0.0001 shows as 0.00).
- FreeCAD: navigation **Touchpad** (⌥ + move rotates, Shift + move pans, two-finger scroll zooms). If the status-bar
  menu will not take the click, paste in **View → Panels → Python console**:
  ```
  FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View").SetString("NavigationStyle", "Gui::TouchpadNavigationStyle"); Gui.activeDocument().activeView().setNavigationType("Gui::TouchpadNavigationStyle")
  ```

## 1. The spray inlet for your nozzle (30 s)

Edit the three numbers on the first line (orifice bore in mm, its Cd, the gas flow in sccm), paste, read the line it
prints:
```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 -c "
d_mm, cd, sccm = 1.2, 0.527, 8995
import sys, math; sys.path.insert(0, '/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation')
from droplet_transport import physics
gas = physics.air(); m = physics.sccm_to_kg_s(sccm, 1.184); A = cd*math.pi/4*(d_mm/1000)**2
ex = physics.jet_exit(m, A, gas); J = ex['momentum_N']; rho = gas.density
d_eq = math.sqrt(4*m*m/(math.pi*rho*J)); Q = m/rho
print(f'CAD spray hole {d_eq*1000:.2f} mm | CfdOF inlet {Q*1e9:,.0f} mm^3/s | speed {J/m:.0f} m/s | Mach {ex[\"mach\"]:.2f} | length scale {0.07*d_eq*1000:.3f} mm | hole refinement {0.1*d_eq*1000/8:.3f}')
"
```
For **1.2 mm, Cd 0.527, 8,995 sccm** it prints: hole **0.91 mm**, inlet **147,412 mm³/s**, **226 m/s**, Mach 0.69,
length scale **0.064 mm**, hole refinement **0.011**.

- **CAD spray hole:** the size that carries the real gas flow *and* momentum (`CFD_LOG.md` section 2). Using another
  size (chamber v1 has 1.0 mm, Ben's choice) keeps the flow right but changes the momentum by (d_eq / d)².
- **CfdOF inlet:** type it into the spray boundary as `147412 mm^3/s` (the gas flow at chamber density). It does not
  depend on the hole size.
- **Length scale:** 0.07 × the hole you actually drew (1.0 mm hole → 0.07 mm).
- **Hole refinement:** relative size for ~10 cells across the hole you drew (hole ÷ 80; 1.0 mm → 0.012). The box takes 3
  decimals; cfMesh halves cells in whole steps, so rounding is harmless.
- Cd values measured 2026-10-15: 0.5 mm insert 0.844, 0.8 mm 0.814, 1.2 mm 0.527 (bore/residue check pending).

## 2. CAD (Fusion)

1. Model the **air inside** the chamber as one solid, in **mm**. Cut out anything solid inside (atomiser body, nozzle
   block, arm, a collector plate). Leave out bolts, fillets and anything under ~5 mm that is not a port.
2. **Ports** = straight stubs the port's bore wide, 10–20 mm long, flat end (chamber v1: **44 mm × 20 mm** extraction
   port on the z = −297.6 wall, centre x 220, y 633).
3. **Spray hole** = the size from step 1, **1 mm deep**, in the nozzle tip (chamber v1: **1.0 mm** at x 163.7,
   z −212.5, opening at y 241, firing −y).
4. Note which axis is up (chamber v1: **Y up**, Fusion's default).
5. **File → Export → STEP**, then Option-drag it from iCloud into a new folder in `~/OpenFOAM/cfdof_cases/` (the terminal
   cannot read iCloud).

## 3. FreeCAD + CfdOF (by clicking)

Open the STEP: `open -a FreeCAD "<path to the .step>"`. Then:

1. **Part** workbench: click the body (inside the assembly), **Part → Check Geometry**: no errors.
2. **File → Save As** `<name>.FCStd` (no spaces), **File → Close**, reopen it: the tree's top name sets the case folder.
3. **CfdOF** workbench, **Analysis container**.
4. **PhysicsModel:** Steady, Single phase, Isothermal, Viscous; Turbulence **RANS**, Model **kOmegaSST**. Gravity is
   greyed out (no buoyancy): leave it.
5. **FluidProperties:** Air.
6. **Boundaries** (Fluid boundary; faces via **Select from list** → click the body's *name* → **▼ Select components**
   → tick; click a face name to highlight it):
   - **spray:** Inlet, Volumetric flow rate (step 1), Intensity **5 %**, Length scale (step 1). Face: the bottom of
     the hole (chamber v1: **Face10**).
   - **outlet:** Outlet, Static pressure, **0 Pa**. Face: the port stub's end disc (**Face2**).
   - **wall:** Wall, No-slip, tick **Use as default boundary condition for unselected faces**. No faces.
   Face numbers change with every new export: always check by clicking the names. Names: no spaces.
7. **InitialiseFields:** Potential flow; pressure from the outlet; untick "use values from boundary"; k **0.0001
   m^2/s^2**, ω **1 1/s**.

## 4. Mesh

1. Click the body, **CFD mesh**: **cfMesh**, base element size **8 mm**.
2. With the mesh selected, **Mesh refinement → Surface refinement** (faces from the list):
   - port stub: relative **0.25** (2 mm), its side and end disc (**Face1, Face2**);
   - spray hole: relative from step 1 (**0.012**), its wall and bottom (**Face9, Face10**).
   **Refine the whole pipe/hole, not just its end:** otherwise it vanishes from the mesh, the inlet has 0 faces and
   the solver crashes with "Illegal instruction: 4".
3. **Jet cones** (Part workbench, **Part → Primitives → Cone**; top level of the tree, not inside the assembly).
   Both: Placement Position = the hole centre with y = the hole's face + 2 mm (chamber v1: **163.7, 243, −212.5**);
   Axis/Angle so the cone points along the jet (Y up, firing down: Axis **(1, 0, 0)**, Angle **90°**).
   - **JetNear:** Radius1 **2**, Radius2 **10**, Height **42** mm.
   - **JetFar:** Radius1 **3**, Radius2 **50**, Height = hole-to-floor + 2 (chamber v1: **230** mm).
   Copy-paste JetNear (Cmd-C, Cmd-V) to make JetFar, then change the three numbers.
4. Mesh selected → **Mesh refinement → Volume refinement**, tick the cone object itself: JetNear **0.063** (0.5 mm),
   JetFar **0.25** (2 mm).
5. Double-click the mesh: **Write mesh case**, **Run mesher**, **Check Mesh** ("Mesh OK"). Chamber v1: **198,682
   cells**; every boundary must have faces (ask Claude to check, or look at the mesh in ParaView).

## 5. Solve

**CfdSolver:** Max Iterations **2000**; double-click it: **Solve in Parallel**, **10 cores**, **Write**, **Run**
(chamber v1 with cones: **~7 min**). Results: `~/OpenFOAM/cfdof_cases/<document name>/case/`. Normal for this
chamber: Uy settles (~1e-3), Ux and Uz stall near 1e-2 (the flow sways; `CFD_LOG.md`).

**Save As first** whenever the new run should not overwrite the last (Write empties the case folder); close and
reopen after Save As.

## 6. ParaView

- Open from the **CfdSolver** panel's **ParaView** button (results) or the mesh panel's (mesh only). **Apply**,
  **Last Frame** (⏭), colour by **U / Magnitude**.
- **Reuse an old view on new results:** Edit → Reset Session; File → Load State…; **Choose File Names**; point at the
  new `case/pv.foam`; then **Save State…** under a new name.
- **Slices** (chamber v1, metres; Y up): through the hole Z Normal **(0.1637, 0.241, −0.2125)** or X Normal
  **(0.1637, 0.241, −0.2125)**; through the port X Normal **(0.22, 0.633, −0.3076)**; across the jet Y Normal y
  **0.2**; just above the floor Y Normal **(0.175, 0.015, −0.158)** (not exactly on the floor at y 0.013: a plane on the boundary cuts no cells). Or hover and press **P**, then pick the normal.
- **Stream Tracer** (Point Cloud; Maximum Streamline Length **10**): spray Center **(0.1637, 0.240, −0.2125)** r
  **0.002**, 100 points; chamber **(0.175, 0.359, −0.158)** r **0.1**, 300; port **(0.22, 0.633, −0.3076)** r **0.02**,
  100, Integration Direction **BACKWARD**.
- **Colours:** **Rescale to custom range** (0–2 m/s for the circulation, 0–20 for the jet).
- **Side by side:** File → Open the other `pv.foam` (Case Type **Decomposed Case**); copy a filter's settings with the
  Properties **copy/paste** buttons; split view (**Render View**); eyes per view; right-click → **Link Camera…**.
- **Pictures:** File → **Save Screenshot…**, tick **Save All Views**; save into `iCloud/PhD/CFD/Results/<date> <what>/`.
- Gotchas: a new filter works on whatever is **selected** (pick the reader first); a view that will not rotate is in
  **2D** mode (click 2D → 3D; or **ParaView → Settings… (Cmd-,) → Render View**, cog for advanced, Default
  Interaction Mode 3D); "Hardware does not support the number of textures" = depth peeling (see-through drawing) on
  the Mac: set Opacity 1 and untick **Depth Peeling** in the same Settings → Render View (cog for advanced; it is
  not in the Properties panel); a "frozen" ParaView at 0 % CPU is
  waiting on a hidden dialog (Cmd-`), else Force Quit (nothing is lost).

## 7. Droplets through the flow (one command, Phase 3a)

Not by clicking (CfdOF has no droplet tracking). Copy the settings file, point it at your run, paste one command.

1. Copy `Flow Visualisation/settings/droplets_baseline.yaml` to a new name (no other change needed for chamber v1
   with the Part 6 mesh). Edit:
   - `flow.case`: your CfdOF case folder (`~/OpenFOAM/cfdof_cases/<document name>/case`) and `flow.iteration`
     (the last one, **2000**, unless checking another);
   - `flow.spray_patch` / `flow.port_patches`: the boundary names you gave in CfdOF (**inlet**, **outlet**);
   - for a new chamber or nozzle: `chamber.inside_mm` (the inside walls, mm, the CAD's axes), `chamber.up`,
     `spray.hole_mm` (the hole's exit) and `spray.direction`;
   - the test: `slide_test.exposure_s` (**5**), `settle_s` (**300**), `flow_after_switch_off_s` (**[0, 2, 10]**).
2. Run it (edit the file name at the end):
   ```
   /Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run_droplets.py" "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/settings/droplets_baseline.yaml"
   ```
   Six runs and four check cases at once, ~1.5 min for 60,000 droplets each (gusts on/off × 0, 2, 10 s of flow after
   switch-off). Keep `per_size` at 600 or more (a 8.3 ms step at a 5 s exposure; report.md check 7).
3. Open `report.md` in the newest `~/OpenFOAM/droplet_runs/<name>/<date_time>/` (it prints the path): the 0–30 µm
   band weighted by the measured spray, the floor deposit maps, where each size ends up, the checks and flags. To see
   a run in ParaView, double-click `paraview/<run>.command` in that folder; press **First Frame**, then **Play**. In
   the Pipeline Browser, the eyes on *0-30 µm band only* and *still airborne only* show just those; your own views'
   slices and streamlines (*Slice Through Orifice*, *Tracers Whole*, ...) are there too, hidden. The **split** tab
   puts the droplets beside the air in your views, cameras linked, for screenshots. The whole folder (report, views,
   OpenFOAM cases) can be copied anywhere and still opens.
4. For a new chamber: check `checks.column_mm` is in free air with nothing below it or downstream of the
   cross-flow (the atomiser, the port), and that the floor maps' outline of the objects looks right.
5. **Several flows at once (a sweep: snapshots, orifice sizes, ...).** A settings file that starts from yours
   (`base:`) and lists the flows under `sweep: runs:`; each entry changes only what it names, e.g.
   `{label: 0.8 mm orifice, flow: {case: ~/OpenFOAM/cfdof_cases/Chamber_v1_0p8/case}, spray: {hole_mm: [...]}}`.
   `Flow Visualisation/settings/droplets_snapshots.yaml` is the worked example (Part D's snapshot check). The same
   command runs each entry into its own folder, then writes `comparison.md` beside them: the air, the 0–30 µm band,
   the floor deposit by band against the reference (`sweep.against`) with the noise from the droplet count, and each
   one's checks. Runs already finished can be compared too: `run_droplets.py --compare <folder> <folder> ...`
   (README.md).

## What changes when you change…

| You change | Recompute / redo |
|---|---|
| Nozzle bore, Cd or gas flow | step 1 → the hole in CAD (if you follow the equivalent size), the inlet flow, length scale, hole refinement |
| Gas flow only | rerun step 1 and retype the inlet flow; the equivalent hole size also shifts a little with flow (the exit Mach changes), so redraw the CAD hole only if you follow it; length scale and refinement stay while the hole stays |
| Nozzle position or direction | CAD; the cones' Position/Axis/Angle and JetFar's Height; the slice/streamline coordinates |
| Ports (add, move, resize) | CAD; a boundary per port (inlet: its flow; outlet: 0 Pa); a 0.25 surface refinement per port |
| The chamber itself | everything from step 2; check which axis is up; the mesh base size if it is much bigger or smaller (~8 mm for ~0.2–0.7 m) |
| Any new export | the face numbers: re-check every boundary and refinement by clicking the names |
| Anything in the CFD | the droplets settings: `flow.case`, and the hole, direction and chamber walls if they moved (step 7); to compare with the old flow, a sweep or `--compare` (step 7.5) |

Naming: one folder per geometry in `cfdof_cases/` (STEP, `.FCStd`, `.pvsm` together), one FreeCAD file per run
(`Chamber_v1`, `Chamber_v1_jet`, …), and the matching `<name>_view.pvsm`.
