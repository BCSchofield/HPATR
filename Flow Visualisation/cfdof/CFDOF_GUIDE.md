# Your first CFD cases: FreeCAD + CfdOF on the Mac

Written 2026-10-23 for Ben, who is new to CFD. These are learning cases: you build the chamber by hand, see each step,
and look at the flow in ParaView. The thesis numbers come from Phase 2's scripted cases (`../PLAN.md`), which use
the same OpenFOAM.

What has been tried so far, why, and what came out: `CFD_LOG.md` (this folder).

Every step below was checked on this Mac by building the same cases by script (the answer key,
`chamber_box.FCMacro`, builds exactly what parts 2–4 build by hand; Part 5, your own chamber, was checked the same way).

## What is installed

| What | Where | Job |
|---|---|---|
| FreeCAD 1.1.4 | `/Applications/FreeCAD.app` | the CAD program; you build the geometry here |
| CfdOF (FreeCAD add-on) | inside FreeCAD (workbench "CfdOF") | sets up the CFD case: boundaries, mesh, solver |
| OpenFOAM v2606 | `/Applications/OpenFOAM-v2606.app` | the solver; CfdOF runs it for you |
| cfMesh | `~/OpenFOAM/benschofield-v2606/` | the mesher CfdOF uses |
| ParaView 6.2.0 | `/Applications/ParaView-6.2.0.app` | viewing the results |

CfdOF writes each case to `/Users/benschofield/OpenFOAM/cfdof_cases/` (OpenFOAM breaks on folder names with spaces,
so not inside `Flow Visualisation`).

**The CFD workflow, in one line:** geometry (the air volume, not the walls) → boundaries (where air comes in, leaves,
and the walls) → mesh (chop the air into cells) → solve (OpenFOAM iterates until the flow stops changing) → view.

---

## Part 0. Open it (2 min)

1. Open FreeCAD:
   ```
   open -a FreeCAD
   ```
2. At the top, the workbench drop-down (it says "Start" or "Part Design"): choose **CfdOF**.
3. Menu **CfdOF → Open preferences**, then **Run dependency checker**. Expect, and ignore:
   - "OpenFOAM version 2606 is not yet supported: Last tested version is 2512" (it works: see the checks);
   - "HiSA not found" (only for supersonic flow).

   OpenFOAM, cfMesh, ParaView and gmsh should all be found.
4. In the same preferences, tick **Append document name to output directory**, then **OK**. Otherwise every case is
   written to the same `case` folder and the next one overwrites the last.

## Part 1. Warm-up: CfdOF's own example (10 min, optional)

A 2D mixing elbow, already set up, so you only press the buttons. Copy it out first (so the original stays clean)
and open its macro:
```
cp -R "/Users/benschofield/Library/Application Support/FreeCAD/v1-1/Mod/CfdOF/Demos/Elbow" "/Users/benschofield/OpenFOAM/cfdof_cases/Elbow"
open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Elbow/elbow.FCMacro"
```
1. With the macro's text showing, menu **Macro → Execute macro**. The elbow and a **CfdAnalysis** tree appear.
2. Double-click **Pad_Mesh** in the tree: **Write mesh case**, then **Run mesher**. Wait for "Meshing completed".
   Close the panel (**OK**).
3. Double-click **CfdSolver**: **Write**, then **Run**. A residuals plot appears (the lines falling = converging).
4. When it says it has finished, press **ParaView** (in the same panel, under Results). If you closed the panel,
   double-click **CfdSolver** again to get it back. The elbow converges in about 100 iterations.

That is the whole loop. Part 2 does it for our chamber.

## Part 2. Build the chamber (20 min)

Our first scenario (`../settings/first_scenario.yaml`): 300 × 200 × 350 mm (x along the 300 mm, z up), a 6 mm
inlet on the right wall and a 25 mm outlet on the left, both centred at y 100, z 175. Each port is a 10 mm pipe stub
sticking out of its wall, so it has an end face to call "inlet" or "outlet".

1. **File → New.** Save it now as `/Users/benschofield/OpenFOAM/cfdof_cases/chamber_box.FCStd`.
2. Workbench drop-down: **Part**.
3. **The box.** Part → Primitives → **Cube** (toolbar: the cube). Select it in the tree; in the **Property** panel
   below the tree (**Data** tab) set **Length 300 mm, Width 200 mm, Height 350 mm**.
4. **The inlet pipe.** Part → Primitives → **Cylinder**. In its Data tab:
   - **Radius 3 mm, Height 10 mm**;
   - expand **Placement**: **Position** x 300, y 100, z 175; **Axis** (0, 1, 0); **Angle 90°**.
     (A cylinder points up by default; turning it 90° about y points it along +x, out of the right wall.)
5. **The outlet pipe.** Another **Cylinder**: **Radius 12.5 mm, Height 10 mm**; Position x 0, y 100, z 175;
   Axis (0, 1, 0); **Angle −90°** (points along −x, out of the left wall).
6. **Join them into one air volume.** In the tree, click the Cube, then Cmd-click both cylinders. Part → Boolean →
   **Union**. A **Fusion** appears. Select it; in its Data tab set **Refine = true** (merges the box's faces so each
   wall is one face).
7. **Check:** rotate the view (drag with the right mouse button, or use the view cube). You should see a tall box with
   a small pipe on the right wall and a fat one on the left. **Save** (Cmd-S).

## Part 3. Set up the CFD and run it (25 min)

Workbench drop-down: **CfdOF**.

1. **Analysis container** (first toolbar button). It adds a **CfdAnalysis** holding PhysicsModel, FluidProperties,
   InitialiseFields and CfdSolver.
2. **Physics** – double-click **PhysicsModel**:
   - **Steady**; **Isothermal**; **Single phase**;
   - Turbulence: **RANS** (Reynolds-averaged Navier-Stokes). A **Model** drop-down then appears below it (scroll the
     panel down): **kOmegaSST** (the turbulence model in PLAN.md);
   - Gravity is greyed out: CfdOF only uses it when there is buoyancy (not isothermal) or a free surface. For one gas
     at one temperature it changes nothing, so leave it. **OK**.
3. **The fluid** – double-click **FluidProperties**: Predefined fluid library → **Air**. **OK**.
4. **Boundaries.** Each is: press **Fluid boundary**, pick the type, add the face(s), **OK**. To add a face: choose
   **Select in model**, click the face in the 3D view (zoom in for the small pipe), press **Add**.
   - **inlet:** Boundary **Inlet**, Sub-type **Volumetric flow rate**, **1.311e-4 m^3/s** (8,000 sccm at chamber
     density). Turbulence specification **Intensity & Length Scale**: I = **5 %**, l = **0.42 mm**. Face: the **end
     disc of the small pipe** on the right. Rename it "inlet" (select it in the tree, F2).
   - **outlet:** Boundary **Outlet**, Sub-type **Static pressure**, **0 Pa**. Face: the end disc of the big pipe on
     the left. Rename "outlet".
   - **walls:** Boundary **Wall**, Sub-type **No-slip (viscous)**, and tick **Use as default boundary condition for
     unselected faces**. No faces needed. Rename "walls".
     **Don't skip this one:** without it, CfdOF makes every unchosen face a *slip* (frictionless) wall.
5. **Starting values** – double-click **InitialiseFields**:
   - Velocity: **Potential flow**;
   - Pressure: **Use value from boundary** → outlet;
   - Turbulence: untick "Use values from boundary"; k = **0.0001 m^2/s^2**, ω = **1 1/s**.
     If k shows **0.00**, FreeCAD is rounding to 2 decimals: FreeCAD menu → **Preferences** (or **Settings…**) →
     **General** → Units: **Number of decimals 6**, **OK**, then type k again (it should show 0.000100).
   (Steady solvers just need somewhere sensible to start.)
6. **The mesh.** Click the **Fusion** in the tree, then **CFD mesh**. In its panel: Mesh utility **cfMesh**, Base
   element size **8 mm**. **OK**.
   Then, with the new mesh object selected, **Mesh refinement**: **Surface refinement**, Relative element size
   **0.1** (0.8 mm cells), and add **all four pipe faces** (each pipe's side and its end disc). **OK**.
   **Why all four:** I first refined only the end discs. The 6 mm pipe then vanished from the 8 mm mesh, the inlet
   had no faces, and the solver crashed with "Illegal instruction: 4" (how a floating-point error shows on this Mac).
7. **Mesh it** – double-click the mesh object: **Write mesh case**, then **Run mesher** (a few seconds). Optional:
   **Check Mesh** (expect "Mesh OK", about 67,000 cells).
8. **Solver settings** – select **CfdSolver**; in its Data tab set **Max Iterations 2000**. Double-click it: tick
   **Solve in Parallel**, **Number of Parallel Cores 10**.
9. **Run** – in the same panel: **Write**, then **Run**. About **1 minute**. Watch the residuals plot.
   The residuals level off around 1e-3 rather than falling below the 1e-4 stop, so it runs all 2,000 iterations:
   normal here (a closed box with a weak through-flow does not settle perfectly).
10. **View** – press **ParaView** (Results). See "In ParaView" below.

**What it should give** (checked): gas in = gas out = 1.311e-4 m³/s; inlet jet ~4.6 m/s at the pipe.

## Part 4. Add the spray (optional, 15 min)

The real spray: 8,995 sccm, which at chamber density is a **0.91 mm** jet at **226 m/s**.

1. Workbench **Part**. Add a **Cylinder**: **Radius 0.455 mm, Height 5 mm**, Position x 150, y 100, z 350, Axis
   (0, 0, 1), Angle 0 (points up, out of the lid's centre).
2. Select the **Fusion**; in its Data tab, add the new cylinder to its **Shapes** list (or delete the Fusion and redo
   the Union with all four solids, Refine = true).
3. Workbench **CfdOF**. Add a boundary **spray**: **Inlet**, **Volumetric flow rate 1.474e-4 m^3/s**, Intensity
   **5 %**, Length scale **0.064 mm**; face: the nozzle's end disc (zoom right in at the lid's centre).
4. A second **Mesh refinement** on the nozzle's two faces, Relative element size **0.0125** (0.1 mm cells).
5. Re-check the inlet, outlet and refinement face lists (adding a solid can renumber faces): each should still show
   the right face highlighted.
6. Mesh and run as before. About **80 s**, ~83,000 cells.

**What it should give** (checked): gas out = inlet + spray = 2.785e-4 m³/s; up to ~245 m/s at the nozzle exit.
**The velocity residuals stop falling around 1e-2:** the flow does not settle to one steady pattern. This is the
open question in PLAN.md Phase 2 (step 5), and this mesh is far too coarse along the jet anyway. It is a picture of
the flow, not a result.

## Part 5. Your own chamber (30 min)

Your STEP: `/Users/benschofield/OpenFOAM/cfdof_cases/FlowVis1stTrial/Flow Analysis Basic.step` (Fusion, 2026-10-24).
It is the chamber's air: 190 × 692 × 280 mm (x × y × z), 35.3 L, **Y up**. The atomiser body, the rod, the nozzle
block and the 30 mm arm are cut out of it (they are walls). Two openings:
- **outlet:** a 44 mm stub, 20 mm long, on the z = −297.6 wall near the top. It vents to the room (0 Pa).
- **spray:** a 1.0 mm hole, 1 mm deep, in the underside of the nozzle block, firing down (−y). Kept at 1.0 mm (Ben),
  so at the real 8,995 sccm it leaves at 188 m/s with 83 % of the real momentum (0.91 mm would give 226 m/s, 100 %).

Checked by building the same case by script (2026-10-24): 66,500 cells, 2,000 iterations in about 2.5 min.

1. **Open it:**
   ```
   open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/FlowVis1stTrial/Flow Analysis Basic.step"
   ```
   The tree shows an assembly ("Assembly - Modular Filter Chamber"). Expand it: inside is the body **Flow Analysis
   Basic**. Use **the body**, never the assembly, for everything below: the mesh and the boundaries must point at the
   same object.
2. **Check it:** switch the workbench drop-down (top toolbar) to **Part**; a **Part** menu appears in the menu bar
   (each workbench brings its own menu). Click the body, **Part → Check Geometry**. Expect no errors.
3. **Save** (File → Save As) as `/Users/benschofield/OpenFOAM/cfdof_cases/FlowVis1stTrial/chamber_v2.FCStd`, close it
   (File → Close) and open it again:
   ```
   open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/FlowVis1stTrial/chamber_v2.FCStd"
   ```
   The top of the tree now says **chamber_v2** instead of "Unnamed". CfdOF names the case folder after that internal
   name, which only changes when the file is reopened, so this puts the case in `cfdof_cases/chamber_v2/`.
4. Workbench **CfdOF**. **Analysis container**, then **PhysicsModel** as in Part 3 (Steady, Isothermal, Single phase,
   RANS kOmegaSST). Gravity is greyed out (see Part 3) and already reads (0, −9.81, 0), which is right for Y up
   anyway. It matters once droplets go in (Phase 3). **FluidProperties:** Air.
5. **Boundaries.** The faces are tiny or hidden, so pick them from the list instead of the 3D view: in the
   boundary panel choose **Select from list**, click the body in the object list, open **▼ Select components**, and
   tick the face. Clicking a face's name highlights it in the 3D view, so check it is the right one.
   - **spray:** **Inlet**, **Volumetric flow rate**, **1.474e-4 m^3/s** (8,995 sccm). Intensity **5 %**, length scale
     **0.07 mm**. Face: **Face10** (the bottom of the 1 mm hole).
   - **outlet:** **Outlet**, **Static pressure**, **0 Pa**. Face: **Face2** (the end disc of the 44 mm stub).
   - **walls:** **Wall**, **No-slip**, tick **Use as default boundary condition for unselected faces**. No faces.
   (The face numbers are this export's. After a new export, check them by clicking each name.)
6. **InitialiseFields:** as in Part 3 (Potential flow; pressure from outlet; k 0.0001, ω 1).
7. **The mesh.** Click the body in the tree, **CFD mesh**: cfMesh, base element size **8 mm**. Then two **Mesh refinement**s
   (Surface refinement, faces from the list as above):
   - **outlet stub:** relative **0.25** (2 mm cells), **Face1** and **Face2** (its side and end disc);
   - **spray hole:** relative **0.0125** (0.1 mm cells, 10 across the hole), **Face9** and **Face10** (its wall and bottom).
     The box takes only 3 decimals, so type **0.012**: cfMesh halves cells in steps, and 0.012 gives the identical mesh
     (checked: 7 halvings, 66,548 cells either way).
8. **Mesh it:** **Write mesh case**, **Run mesher** (seconds; about 66,500 cells). Before solving, look at it:
   **Load surface mesh** (cells drawn on the model), the mesh panel's **ParaView** button (slice it: the cells should
   shrink towards the hole and the stub), and **Check Mesh** (expect "Mesh OK"). cfMesh reports a few bad faces near the
   hole and then fixes them ("Number of bad faces is 0"): fine.
9. **Solve:** CfdSolver, **Max Iterations 2000**, **Solve in Parallel**, **10 cores**. **Write**, **Run**. About 2.5 min.

**What it should give** (checked): gas out = spray in = 1.474e-4 m³/s; up to ~211 m/s just below the hole. As in
Part 4, the velocity residuals stop falling around 1e-2: the jet does not settle to one steady pattern, so this is a
picture of the flow, not a result.

**In ParaView** (metres; see below for the basics):
Your chamber in metres: x 0.08–0.27, **y 0.013–0.705 (up)**, z −0.298 to −0.018; its centre is (0.175, 0.359, −0.158).
- **Slice through the nozzle:** Normal **Z Normal**, Origin **(0.1637, 0.241, −0.2125)**. The jet runs down the
  middle of the slice from the nozzle block.
- **Slice through the outlet:** **X Normal**, Origin **(0.22, 0.633, −0.25)**: the outlet stub sticks out of the
  z = −0.298 wall near the top.
- A **Y Normal** slice is horizontal (Y is up): e.g. y **0.2**, 40 mm below the nozzle, cuts across the jet.
- **Streamlines from the spray:** Stream Tracer, Point Cloud, Center **(0.1637, 0.240, −0.2125)**, Radius **0.002**.
- Set the colour maximum to about **2 m/s** to see the chamber's circulation; the jet swamps everything otherwise.

**Saving.** The results are already on disk (`cfdof_cases/Chamber_v1/case`). Save the FreeCAD file (Cmd-S) for the
settings, and in ParaView **File → Save State…** (a `.pvsm` next to the FreeCAD file) for your slices, streamlines and
colours; **File → Load State…** brings them back (choose "Use File Names From State"). **File → Save Screenshot…** for
pictures. Running the same FreeCAD file again overwrites its case folder, so for a variation (the grid check below)
**Save As** a new name, close it and reopen it first: the case then goes to a new folder.

## Part 6. Refine along the jet (20 min clicking, ~7 min solving)

Part 5's mesh is fine only at the hole: a few mm below it the cells are as wide as the jet, which smears it (11 m/s
at 10 mm below the hole where a real 1 mm jet still has ~110 m/s). Here you add two cones of small cells along the
jet. Checked by building the same case by script (2026-10-24): 198,682 cells, 2,000 iterations in ~7 min.

1. **Keep Part 5's results:** **File → Save As** `/Users/benschofield/OpenFOAM/cfdof_cases/FlowVis1stTrial/Chamber_v1_jet.FCStd`,
   **File → Close**, and reopen it:
   ```
   open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/FlowVis1stTrial/Chamber_v1_jet.FCStd"
   ```
   The tree now starts with **Chamber_v1_jet**, so this case goes to its own folder.
2. **The near cone.** Workbench **Part**, **Part → Primitives → Cone**. In its Data tab:
   - **Radius1 2 mm, Radius2 10 mm, Height 42 mm**;
   - **Placement**: Position **x 163.7, y 243, z −212.5**; Axis **(1, 0, 0)**; Angle **90°**.
   It starts 2 mm inside the nozzle block, over the hole, and points down the jet to 40 mm below it. Rename it
   **JetNear** (F2).
3. **The far cone.** Another **Cone**: **Radius1 3 mm, Radius2 50 mm, Height 230 mm**, the same Placement. It
   reaches the floor. Rename it **JetFar**.
4. **Check:** both cones hang below the nozzle block, the far one ending on the floor. Select each and press
   **Space** to hide it if it is in the way. CfdOF only uses them to place small cells; they are not walls.
5. Workbench **CfdOF**. Click the mesh object, **Mesh refinement**. At the top choose **Volume refinement**.
   Relative element size **0.063** (0.5 mm cells). Under its references, **Select from list** and tick **JetNear**
   itself. (For a volume you tick the object, unlike a boundary's faces.) **OK**.
6. Again for **JetFar**: **Volume refinement**, **0.25** (2 mm cells), tick **JetFar**. **OK**.
7. **Mesh it:** **Write mesh case**, **Run mesher** (seconds; **~198,700 cells**), **Check Mesh**. In the mesh panel's
   ParaView, slice through the hole (X Normal, origin 0.1637, 0.241, −0.2125, Crinkle slice): a band of small cells
   now runs down the middle to the floor.
8. **Solve:** **Write**, **Run** (the solver settings are kept). About **7 min**.

**What it should give** (checked against Part 5's run):

| | Part 5 | Part 6 | Real 1 mm jet (approx.) |
|---|---|---|---|
| Jet, 10 mm below the hole | 11 m/s | 94 m/s | ~110 m/s |
| Jet, 20 mm | 5 m/s | 47 m/s | ~56 m/s |
| Jet, 80 mm | 7 m/s | 11 m/s | ~14 m/s |
| Jet, 200 mm | 4.5 m/s | 4.3 m/s | ~5.6 m/s |
| Chamber mean air speed | 0.54 m/s | 0.55 m/s | |
| Spread along the floor (40 mm out) | 2.5 m/s | 2.5 m/s | |

The lesson: refining the jet fixed the jet itself, but the chamber's circulation barely changed. The circulation is
set by the jet's momentum, which the coarse mesh still carried; the near jet is where the droplets start (the window is
~55 mm below the nozzle), so it matters for Phase 3. The refined jet still runs ~20 % below the textbook jet:
two-equation turbulence models like k-ω SST are known to spread round jets too fast. Phase 2 checks this against a
second turbulence model. The velocity residuals stall just under 1e-2 (Part 5: about 2e-2): still not fully steady.

**In ParaView:** open both cases (each has its own `pv.foam`) and show the same slice through the hole at the same
colour scale (e.g. 0–20 m/s) side by side with the **split view** button. The Part 5 jet fades within a few mm; the
Part 6 jet carries on down to the floor.

**Then the grid check** (the exercise from before): change the base element size to **5 mm**, mesh, run, and compare
the same slice at the same colour scale. Where the pattern holds, the 8 mm mesh was fine enough.

## Part 7. The refined chamber: drill the bore, the final mesh (~1 h clicking, ~35 min solving)

Your refined CAD: `/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2/Refined_Modular_Filter_Chamber.step`
(Fusion, 2026-10-26).
- **The same chamber air as Part 5:** 190 × 692 × 280 mm, 35.1 L, Y up, the same origin, the 44 mm port in the same
  place.
- **New: the nozzle's real outside.** A 35 mm round cap stands 4 mm proud of the nozzle block. The pointed insert's tip
  is a 70° point at **(163.7, 237.0, −212.5)**, level with the cap's face, in a trough 2.9 mm deep and 11 mm out.
- **It is not drilled yet:** you drill it here.

This part does three things, and says why at each step:
1. **Drill the bore** at the momentum-equivalent size (7.3–7.4).
2. **Build the final mesh** (7.6–7.7):
   - cells sized to what each part of the flow needs;
   - a ladder of cells down the jet;
   - thin layers on the floor and walls, the fix for the droplets landing on the floor too often.
3. **Solve and check it** (7.8–7.10): the jet against the textbook and Part 6, then the droplets' tracer check.

**Checked by script first** (2026-10-26, the same objects and settings on a scratch copy): 1,218,853 cells, meshed in
17 s, "Mesh OK"; 3,000 iterations in 53 min on 10 cores, with the bore at 0.91 mm (before the Cd correction; the
mesh and its checks are the same at 1.11 mm). The face numbers below are what these clicks give, checked by repeating
them by script (open the STEP, simple copy, union) at 0.91, 0.97 and 1.11 mm: they don't change.

### 7.1 Open it and save it under its own name (2 min)

```
open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2/Refined_Modular_Filter_Chamber.step"
```
**File → Save As** `/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2/Chamber_v2.FCStd`, then **File → Close**, and
reopen it:
```
open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2/Chamber_v2.FCStd"
```
**Why:** CfdOF names the case folder after the document's internal name, which only updates when the file is reopened
(Part 5, step 3). The case then goes to `cfdof_cases/Chamber_v2/case`, next to the STEP.

### 7.2 Take the body out of the assembly (3 min)

The tree shows the assembly **Refined Modular Filter Chamber** with the body **Flow Analysis Basic** inside it.
1. Workbench **Part**. Click **Flow Analysis Basic**, then **Part → Create a copy → Create simple copy**. A copy
   appears at the bottom of the tree. Rename it **Chamber** (F2).
2. Click the assembly and press **Space** to hide it. Keep it: it is the link back to the STEP.
3. Click **Chamber**, then **Part → Check Geometry**: no errors, 1 solid, 40 faces (open **Shape Content** for the
   counts).
   - If it says **Invalid**, with "Boolean operation: GeomAbs_C0" and "invalid curve on surface" on Face7, Face14 and a
     few edges, **Run BOP check** is ticked under **Settings**. That stricter check flags two small faces at the
     nozzle tip, a creased spline and the trough's rounded edge, which come that way from Fusion's STEP. The plain
     check passes, and the union and mesh work with them (checked 2026-10-27: the STEP's own body shows the same).
     Untick it and **Run check** again.

**Why:** the next step fuses the body with a cylinder. FreeCAD can't cleanly fuse a body inside an assembly with a
cylinder outside it (it warns about links "out of scope"). The simple copy is the same solid, in the same place, at
the top level of the tree.

### 7.3 Drill the bore (5 min)

1. **Part → Primitives → Cylinder**. Rename it **Bore**. In its Data tab:
   - **Radius 0.555 mm, Height 8.5 mm**;
   - **Placement:** Position **x 163.7, y 236, z −212.5**; Axis **(1, 0, 0)**; Angle **−90°**.
2. **Check:** select Bore, then **View → Standard views → Fit selection**. A thin rod pokes 1 mm out of the point and
   runs up into the nozzle.

**Why these numbers:**
- **1.11 mm across, not the insert's 1.2 mm** (Ben, 2026-10-26: the 1.2 mm insert as it is now, drilled through).
  - The solver (simpleFoam) treats the gas as incompressible, at the chamber air's density. The real exit is denser
    and faster (Mach 0.45), and the gas uses only part of the bore: the exit-only Cd is 0.82, measured on the work PC
    on 2026-10-26.
  - The hole that carries **both** the real gas flow (8,995 sccm of nitrogen, 171.6 mg/s) **and** the real push
    (momentum, 26 mN) at the chamber air's density is 1.09 mm at 153 m/s. The push drives the jet and the chamber's
    circulation; a bare 1.2 mm hole with the same flow would push with 21.6 mN, 82 % of it.
  - **Ben's case is at 1.11 mm** (2026-10-28: the bore stayed at the first, air-based size; the flow is nitrogen's).
    It carries the right gas, 171.6 mg/s, at 147 m/s, with 25.3 mN of push: 3.6 % under 1.09 mm's 26.2, so the jet's
    speeds sit ~1.8 % low. That is well inside the turbulence model's own error (7.9: 4–13 % slow against the
    textbook), so it stays.
  - **Nitrogen, not air** (2026-10-27): the rig's gas is nitrogen, and the Alicat's sccm are at 25 °C, where nitrogen
    is 1.145 kg/m³ against air's 1.184. Taking it as air (the first version of this part: 1.11 mm, 1.474e-4 m³/s)
    put 3.4 % too much gas and 3.3 % too much push in. The solver still treats the whole chamber as air, jet included:
    single phase. Nitrogen and air differ by 3 % in density and their viscosities by 2 %, so the mix in the chamber
    moves as air does; only the amount of gas in, and its push, need nitrogen's numbers.
  - Not in it: the silicone film narrowing the gas's way out while spraying. That is a later stage (`CFD_LOG.md`
    section 7).
  - The older 0.91 mm came from Cd 0.527, which turned out to include the losses in the line and the holes upstream:
    it overstated the push (40 mN).
- **7.5 mm long,** as the real inserts: from the tip point up to where the bore leaves the mixing chamber. The gas
  enters at the top and develops on its way down, so it leaves the lip with a real velocity profile and real wall
  turbulence, not a flat plug. It also keeps the inlet away from the lip, where the flow has to be free to separate.
- **It starts 1 mm below the tip point.** Booleans fail, or leave slivers, when two surfaces only just touch: here the
  cylinder's end and the cone's point. The 1 mm below the point is air already, so overlapping costs nothing.
- **Axis (1, 0, 0), −90°:** a cylinder points along its own z. Turning it −90° about x points it up (+y). The jet
  cones in 7.7 use +90° to point down.
- **The exit lip** is where the bore meets your 70° point: at y 237.79, a 35° knife edge. On the real 1.2 mm insert
  it would sit 0.06 mm higher. That is invisible in the chamber flow (PLAN.md Phase 2a: drill one blank for every
  size).

### 7.4 Fuse it into the air (2 min)

1. Click **Chamber**, Cmd-click **Bore**, then **Part → Boolean → Union**. A **Fusion** appears.
2. Select the Fusion and, in its Data tab, set **Refine = true**.
3. **Part → Check Geometry** on the Fusion: no errors, **1 solid, 42 faces** (with Run BOP check off, as 7.2).

**Why Refine:** without it, the union leaves seam lines where the solids joined and splits faces in two. With it,
each surface is one face, so the numbers below match.

### 7.5 Physics, fluid, boundaries (10 min)

Workbench **CfdOF**. This is as Part 5, steps 4–6, with the new faces.
1. **Analysis container.** **PhysicsModel:** Steady, Isothermal, Single phase, **Viscous** ticked, RANS,
   **kOmegaSST**. (Unticked would be inviscid: no wall friction, no turbulence, no jet spreading.)
   **FluidProperties:** Air.
2. **Boundaries:** one **Fluid boundary** per boundary: the CfdOF toolbar button between Fluid properties and
   Initialise (hover for "Creates a CFD fluid boundary"), or
   **CfdOF → Fluid boundary**. It is greyed out until the analysis is active: double-click **CfdAnalysis** in the tree.
   In the panel use **Select from list**, click **Fusion**, open **▼ Select components**, and tick the face. Click
   each face's name and check it lights up the right face; the table at the end of this part gives each one's size
   and position. **OK**, then rename it (F2) to the name below: the solver's patch takes the tree name, and the
   droplets check (7.10) looks for **spray**.
   - **spray:** **Inlet**, **Volumetric flow rate**, **1.426e-4 m^3/s**; Intensity **5 %**, length scale
     **0.076 mm**. Face: **Face42**, the bore's top disc (0.97 mm², at y 244.5, hidden inside the nozzle).
   - **outlet:** **Outlet**, **Static pressure**, **0 Pa**. Face: **Face32**, the port's end disc.
   - **walls:** **Wall**, **No-slip**, tick **Use as default boundary condition for unselected faces**. No faces.
3. **InitialiseFields:** Potential flow; pressure from outlet; untick "Use values from boundary"; k **0.0001**,
   ω **1**.

**Why the same numbers as Part 5:**
- 1.426e-4 m³/s is 8,995 sccm of nitrogen (171.6 mg/s) at the chamber air's density (1.204 kg/m³). Parts 5–6 used
  1.474e-4, the same sccm taken as air.
- 5 % is pipe-flow turbulence at the exit, and the length scale is 0.07 × the hole (`CFD_LOG.md` section 2). 0.076 is
  1.09 mm's; 1.11 mm's would be 0.078, which makes no visible difference.
- The hole is now 1.11 mm instead of 1.0, so the gas leaves at 147 m/s instead of 188 (25 mN against Part 6's 33).

### 7.6 How the mesh is laid out, and why (read this first)

- **One background size, 8 mm cubes,** for the bulk, where the air moves at under a metre a second and changes
  slowly.
- **Smaller cells where the flow changes over shorter distances:** in the bore, at the lip, along the jet, and
  against the floor and walls. The rest stays coarse, which keeps the cell count, and so the run time, down.
- **cfMesh only makes cells by halving 8 mm:** 4, 2, 1, 0.5, 0.25, 0.125, 0.0625 mm. CfdOF's **Relative element
  size** is the size you want ÷ 8 mm, rounded **down** to the next halving.
  - The values below sit safely inside a step, so they can't round to the wrong one. 0.04 gives 0.25 mm; 0.03 would
    give 0.125 mm.
  - The box takes 3 decimals.
- **Neighbouring cells differ by at most 2×,** because cfMesh grades them. So the jet ladder steps
  0.125 → 0.25 → 0.5 → 1 → 2 mm.

| Refinement | Kind | Faces / object | Relative size | Cells | Why |
|---|---|---|---|---|---|
| **BoreRefinement** | surface | Face40, Face41, Face42 (the lip's cone, the bore wall, the inlet) | **0.012** | 0.0625 mm | About 18 cells across the 1.11 mm bore: enough for the gas to develop a real pipe-flow profile on its way down (checked at 0.91 mm: its centre left at 1.14× the mean, as developed pipe flow does). The bore's wall cells sit at y⁺ ≈ 10 (5–15) at 0.91 mm, a little lower at 1.11. That is in the buffer layer, where k-ω SST's wall functions are least exact, but it costs little: the bore's wall friction is ~1.4 % of the jet's push. Getting under y⁺ 5 would take 0.03 mm cells and 8× the bore's cells, for no visible change. |
| **TipRefinement** | surface | Face34–Face39 (the point's flank and the trough) | **0.04** | 0.25 mm | The air drawn into the jet flows along these. The trough (2.9 mm deep) needs about 10 cells to keep its shape. |
| **CapRefinement** | surface | Face30, Face33 (the cap's side and face) | **0.15** | 1 mm | The rest of the nozzle the entrained air sweeps past. |
| **OutletRefinement** | surface | Face27, Face32 (the port's side and end) | **0.3** | 2 mm | As Part 5: the port keeps its shape and its faces. |
| **FloorRefinement** | surface + layers | Face20 (the floor) | **0.3**, thickness **10 mm**; **8** layers, ratio **1.25**, max first **0.1 mm** | a 2 mm slab; first cell 0.05 mm | The droplets fix (below), and the wall jet along the floor. |
| **WallsRefinement** | surface + layers | Face10, Face18, Face19, Face21, Face26 (the four sides and the lid) | **1**; **10** layers, ratio **1.3**, max first **0.15 mm** | first cell ~0.1 mm | The same fix on the walls the fines also reach. |
| **JetCore … JetFloor** | volume | five cones | 0.02 … 0.3 | 0.125 … 2 mm | The jet ladder (below). |

**The jet ladder.**
- **The jet widens in proportion to the distance it has travelled.** Its half-width, where the speed is half the
  centre's, grows by about 0.1 mm per mm. In Part 6's flow it was 0.9 / 2.3 / 4.8 / 10 / 18 mm at 10 / 20 / 40 / 80 /
  150 mm below the hole.
- **So the cells can double each time the distance doubles,** and still keep about 7–10 cells across that half-width
  all the way down. Part 6's single 0.5 mm cone had fewer than 2 at 10 mm below the hole.
- **Each cone is drawn 2.2–2.7 half-widths wide,** out to where the jet's speed has fallen to a few % of the centre's,
  so the jet never leaves its cone.

**The layers (fix (b) from the droplets work, `CFD_LOG.md` section 6).**
- **The problem:** tracers that follow the air were landing on the floor 62 % of the time where the real air would
  sweep them along. In the cell against a wall, OpenFOAM blends the air's speed linearly, and that lets a droplet creep
  in to the wall.
- **The cure:** make that wall cell much thinner than the slow layer under the jet (~0.6 mm).
  - Floor: 8 layers bring the first cell from Part 6's 1.28 mm to 0.05 mm.
  - Walls: 10 layers bring it to about 0.1 mm.
- **Thin wall cells also suit k-ω SST:** y⁺ ≈ 1 there, where it resolves the wall instead of guessing.
- **Expansion ratio 1.25–1.3:** each layer is 25–30 % thicker than the one below, so the layers grow smoothly into
  the 2 or 8 mm cells above. Much more than ~1.3 and the solver sees a jump.
- **Max first cell height** is a cap on the thinnest layer. cfMesh fits the layers into the first ordinary cell, so
  the result is a little thinner than the cap (0.05 mm on the floor).
- **The 10 mm slab on the floor:** the jet throws air along the floor (a wall jet, ~2.5 m/s and a few mm thick), and
  it crosses the whole floor before climbing the walls. 2 mm cells over it show it properly. This is the air over
  your slide grid.

### 7.7 Make the mesh (25 min)

1. Click **Fusion**, then **CFD mesh**: **cfMesh**, base element size **8 mm**. **OK.**
2. **The surface refinements.** With the mesh object selected: **Mesh refinement**, **Surface refinement**, faces
   **Select from list** (as Part 5). Rename each (F2) as in the table:
   - **BoreRefinement:** **0.012**; Face40, Face41, Face42.
   - **TipRefinement:** **0.04**; Face34, Face35, Face36, Face37, Face38, Face39.
   - **CapRefinement:** **0.15**; Face30, Face33.
   - **OutletRefinement:** **0.3**; Face27, Face32.
   - **FloorRefinement:** **0.3**, **Refinement thickness 10 mm**; tick **Boundary layers**: Number of layers **8**,
     Expansion ratio **1.25**, Max first cell height **0.1 mm**; Face20.
   - **WallsRefinement:** **1**; tick **Boundary layers**: **10**, **1.3**, **0.15 mm**; Face10, Face18, Face19,
     Face21, Face26.
3. **The jet cones.** Workbench **Part**, then **Part → Primitives → Cone**. All five share one Placement: Position
   **x 163.7, y 240, z −212.5**; Axis **(1, 0, 0)**; Angle **90°**. They point down the jet and start 2.35 mm above
   the lip, inside the nozzle, so the exit is covered.

   | Cone | Radius1 (top) | Radius2 (bottom) | Height | reaches, below the lip | Relative size | Cells |
   |---|---|---|---|---|---|---|
   | **JetCore** | 0.8 mm | 4 mm | 15 mm | 12.6 mm | **0.02** | 0.125 mm |
   | **JetNear** | 1.5 mm | 7.5 mm | 28 mm | 25.6 mm | **0.04** | 0.25 mm |
   | **JetMid** | 2 mm | 14 mm | 53 mm | 50.6 mm | **0.08** | 0.5 mm |
   | **JetFar** | 3 mm | 27 mm | 103 mm | 100.6 mm | **0.15** | 1 mm |
   | **JetFloor** | 4 mm | 60 mm | 230 mm | to the floor (3 mm past it) | **0.3** | 2 mm |

   - **Shortcut:** make JetCore, then **Edit → Copy** and **Edit → Paste** four times, and change only the radii and
     height. The placement comes with the copy. Rename each (F2).
   - Workbench **CfdOF**. For each cone: mesh object selected, **Mesh refinement**, **Volume refinement**, the relative
     size from the table, **Select from list**, and tick the cone itself (for a volume you tick the object, not a
     face).
   - Hide the cones (Space). They only place small cells; they are not walls. Where they overlap, the finest wins.
4. **Mesh it:** double-click the mesh object, **Write mesh case**, **Run mesher**. It takes about 20 s and gives
   **~1,218,900 cells**.
   - **Check Mesh** says "Mesh OK" and flags ~54 faces as over 70° non-orthogonal: 9 at the knife-edge lip, the rest
     where the walls' layers meet the arm on the x = 80 wall.
   - That is harmless at this count. CfdOF's solver settings correct for it (5 non-orthogonal correctors, a limited
     Laplacian), and checkMesh only fails a mesh over 70° when the count is large.
5. **Look at it:** the mesh panel's **ParaView**, then (the case selected) a **Slice**, **Z Normal**, origin
   **(0.1637, 0.237, −0.2125)**, **Crinkle slice** ticked (further down the Slice panel), **Show Plane** unticked.
   Colour **Solid Color**, shown as **Surface With Edges**; hide the case (eye) and look down Z (the **−Z** view
   button). Not **Extract Cells By Region**: that keeps whole cells around its own plane, a diagonal staircase unless
   its plane is set the same.
   - The cells should shrink step by step down the ladder to the hole.
   - Zoom right in on the floor and a wall to see the layers.

### 7.8 Solve (2 min clicking, ~35 min)

1. **CfdSolver**, Data tab: **Max Iterations 2000**, **Steady Write Interval 500**.
2. Double-click it: **Solve in Parallel**, **10 cores**.
3. Plug the Mac into its own charger (70 W or more) and stop it sleeping. On a 35 W adapter the battery drains at
   ~45 W under this load: it can run flat before the solve ends. This keeps it awake for 2 h:
   ```
   caffeinate -i -t 7200
   ```
4. **Write**, then **Run**.

**Why 500:** each save of a 1.2-million-cell flow is ~240 MB. Saving every 500 iterations keeps four snapshots (the
whole case is ~1.5 GB), enough for a snapshot check.
**Why 2,000:** in the scripted run, iterations 2,000 and 3,000 gave the same jet (within 0.5 %) and the same droplet
deposit in every band (the droplets check, 7.10). The residuals level off from ~500 on: the jet never settles
completely, so more iterations only wander.

### 7.9 What it should give (checked)

From the scripted run with the bore at **0.91 mm** (iteration 3,000), beside Part 6's flow probed the same way. "Below
the lip" is along the jet's axis.

**Your run is at 1.11 mm:** 25 mN of push instead of 40. Expect:
- the same cell count, residuals, y⁺ and gas balance;
- jet speeds from ~20 mm down, and the floor's wall jet, at about **0.80×** these, because speed goes as the square
  root of the push. That is roughly 45 / 22 / 15 / 10 / 7 m/s at 20 / 40 / 55 / 80 / 120 mm, and 2.2 / 2.9 / 1.6 /
  1.3 m/s on the floor;
- the centre 2 mm below the lip ~1.14 × 147 ≈ 168 m/s.

| | Part 6 (1.0 mm hole, 188 m/s, 220,433 cells) | Part 7 checked at 0.91 mm (226 m/s, 1,218,853 cells) |
|---|---|---|
| Gas in = gas out | yes | 1.4740e-4 = 1.4740e-4 m³/s |
| Velocity residuals at the end | ~1e-2 | ~2e-3 (still not fully steady, but 5× calmer) |
| 2 mm below the lip (centre) | 183 m/s | 258 m/s: 1.14× the mean, the developed pipe-flow profile from the bore |
| 10 / 20 / 40 mm | 112 / 49 / 23 m/s | 129 / 57 / 27 m/s |
| 55 mm (the window) | 17 m/s | 19 m/s |
| 80 / 120 / 200 mm | 11 / 7.7 / 4.3 m/s | 13 / 8.5 / 4.7 m/s |
| Against the textbook round jet with the same push (Hussein 1994), 20–80 mm | 11–17 % slow | 4–13 % slow |
| The jet's half-width at 10 / 20 / 40 / 80 / 150 mm | 0.9 / 2.3 / 4.8 / 10 / 18 mm | 1.0 / 2.2 / 4.6 / 9.5 / 19 mm |
| Cells across that half-width | 1.8 at 10 mm (0.5 mm cells) | 8–10 at every height |
| The floor's wall jet, 20 / 40 / 80 / 120 mm out | 2.5 / 3.3 / 1.7 / 1.6 m/s, peak not resolved (first cell 1.28 mm) | 2.8 / 3.6 / 2.0 / 1.6 m/s, peak 0.8–1 mm above the floor (first cell 0.05 mm) |
| Chamber's mean air speed; share above 0.5 m/s | 0.56 m/s; 47 % | 0.57 m/s; 50 % |

y⁺ of the wall cells (the wall cell's height in the wall's own units; under ~1 means the slow layer at the wall is
resolved, not modelled):

| Floor under the jet | Rest of the floor | Side walls and lid | Tip and cap | Atomiser (no layers) | Bore |
|---|---|---|---|---|---|
| 0.74 | 0.25 | 0.16 | 0.57 | 2.3 (max 15) | 9.8 (max 15) |

**What it says:**
- **The jet is now mesh-sharp near the nozzle.** About 8–10 cells across it all the way down, and the bore gives it a
  real exit profile.
- **The ~10–15 % it still runs slow is the turbulence model, not the mesh.** Its half-width grows ~0.13 mm per mm
  against the textbook's 0.094. That is k-ω SST's known fault with round jets: it spreads them too fast, so the centre
  slows sooner. The lever is a second turbulence model (the next stage), not more cells. Near the floor, the jet
  also slows because it is about to hit it, which the free-jet textbook doesn't have.
- **The floor's wall jet is resolved for the first time:** its peak sits ~1 mm above the floor, and the floor and
  walls are at y⁺ under 1 everywhere.
- **It is ~10 % faster than Part 6's,** as it should be: 21 % more push (40 against 33 mN), and speed goes as the
  square root of the push.
- **The chamber's circulation hardly changed** (mean 0.57 against 0.56 m/s): it is set by the jet's push, as Part 6
  found.
- **2,000 against 3,000 iterations:** the jet is the same to within 0.5 %, the floor's wall jet within 1 % (9 % at
  120 mm), and the chamber's mean speed within 2 %.

**Your run should match these to a few %.** If the cell count is off by more than ~1 %, a refinement has the wrong
faces or relative size: check the list in 7.7 against the face table below.

### 7.10 The droplets' tracer check

The real test of the layers: the baseline droplets through Part 6's flow and through yours, side by side, with the
tracer check (0.5 µm droplets that follow the air: any that touch a wall show the tracking's artefact). About 9 min:
```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run_droplets.py" "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/settings/droplets_chamber_v2.yaml"
```
It writes `~/OpenFOAM/droplet_runs/<date>_<time>_droplets_chamber_v2/comparison.md` (runs before 2026-11-12:
`droplet_runs/droplets_chamber_v2/<date_time>/`); each run's `report.md` has the tracer check under Checks.

**What the scripted run gave (0.91 mm; yours will differ a little in the numbers, not the picture):**

| | Part 6 | Part 7 (0.91 mm) |
|---|---|---|
| Tracers on the floor, gusts off | **61.8 %** | **0.1 %** |
| Tracers on any wall, gusts on | 65 % (floor 24, side walls 34, atomiser 6) | 8.9 % (all on the atomiser, the one part without layers) |
| 0–30 µm band (gusts on, flow kept 2 s): on the side walls | 30 % | 4 % |
| ... airborne at switch-off | 17 % | 40 % |
| ... on the floor, settled in still air | 8 % | 33 % |
| ... on the floor in all | 64 % | 87 % |
| The gusts on/off bracket on the band's floor share | 42 points (Part D) | 18 points |

**What it says:**
- **The layers fixed the artefact.** Part 6's walls caught droplets the real air would have carried along: 62 % of
  the tracers. Now 0.1 %.
- **The fines stay up much longer.** Their side-wall hits mostly went with the artefact, so 40 % of the band is still
  airborne at switch-off and settles onto the floor afterwards. For the slide test, that makes the still-air wait
  (and covering the slides during the warm-up) matter more.
- **The atomiser still shows it:** 8.9 % of the tracers with gusts on, because it has no layers. That is a later
  stage, if it matters.
- **2,000 against 3,000 iterations: "close" at worst** (only the > 60 µm centre, 0.5 mm). The band is the same.

### The faces of Chamber_v2 (to check what lights up)

| Face | What | Area | Centre (mm) |
|---|---|---|---|
| Face42 | the bore's top disc: **spray inlet** | 0.97 mm² | (163.7, 244.5, −212.5) |
| Face41 | the bore's wall | 23.4 mm² | (163.7, 241.2, −212.5) |
| Face40 | the point's last 0.1 mm, round the lip | 0.67 mm² | (163.7, 237.9, −212.5) |
| Face34–Face39 | the point's flank and the trough | 323 / 18 / 44 / 16 / 12 / 22 mm² | around (163.7, 238–240, −212.5) |
| Face33 | the cap's flat face | 563 mm² | (163.7, 237.0, −212.5) |
| Face30 | the cap's round side | 440 mm² | (163.7, 239.0, −212.5) |
| Face32 | the port's end disc: **outlet** | 1,521 mm² | (220, 633, −317.6) |
| Face27 | the port's side | 2,765 mm² | (220, 633, −307.6) |
| Face20 | the floor | 53,219 mm² | y = 13 |
| Face18 | the lid | 53,219 mm² | y = 705.35 |
| Face10 / Face26 | the x = 80 / x = 270 walls | 193,027 / 193,927 mm² | |
| Face21 / Face19 | the z = −17.5 / z = −297.6 walls | 131,546 / 130,026 mm² | |

Faces 1–17, 22–25, 28, 29 and 31 are the atomiser body, rod, nozzle block and arm: walls by default, no refinement.

**In ParaView** (metres): the chamber is the same as Part 5's, and the lip is at **(0.1637, 0.23779, −0.2125)**.
- **Slice through the jet:** Z Normal, origin (0.1637, 0.2, −0.2125).
- **Across the jet at the window:** Y Normal, y **0.183** (55 mm below the lip).
- **Streamlines from the spray:** Stream Tracer, Point Cloud, centre (0.1637, 0.236, −0.2125), radius 0.001.
- **The floor's wall jet:** Y Normal, y **0.0135** (0.5 mm above the floor), colour maximum ~3 m/s.
- **Your Part 6 views on this flow:** **File → Load State**, `FlowVis1stTrial/chamber_v1_jet_view.pvsm`; Load State
  Data File Options **Choose File Names**, and point OpenFOAMReader1 at `Chamber_v2/case/pv.foam` (Case Type stays
  Decomposed). Then **Tracers From Orifice**: seed centre y **0.236**, radius **0.001** (Part 6's 0.24 sits inside
  this nozzle, so few seeds survive). The slices and the other tracers fit as they are. **Last Frame**, then **File →
  Save State** as `Chamber_v2/chamber_v2_view.pvsm`. For the two side by side: `Comparison_Jet_Refinement.pvsm` the
  same way, Part 5's reader → `Chamber_v1_jet`, Part 6's → `Chamber_v2` (move its Tracers From Orifice seed as above), and rename the readers and the two text
  labels.

---

## Part 8. A carrier stream: two push designs (~1 h clicking, ~1.5 h solving each)

Written 2026-11-02 (`../PLAN.md` Phase 7, step 3); **rewritten 2026-11-12 to your layout** (the first version had
the carrier on the x = 270 wall and a plain 10 mm capture low on the x = 80 wall, crossing the spray). Both designs
are **your Chamber_v2 case**, with everything in it kept: the 1.11 mm bore, the five jet cones, the tip and cap
refinements, the floor and wall layers. To it you add:
- a **carrier inlet**: a 20 mm long stub on the x = 80 wall at y 210, z −100, blowing 30 L/min straight across the
  chamber, beside the spray rather than through it;
- a **capture**: on the opposite x = 270 wall, **in line with the carrier**: a cone from a 50 mm mouth down to 10 mm,
  then a 10 mm pipe, where the air leaves (the AJP line, later);
- **the 44 mm port, sealed**: the capture is the only way out.

| | **Stream** (`Chamber_v2_stream_30`) | **Gentle** (`Chamber_v2_gentle_30`) |
|---|---|---|
| Carrier inlet | **10 mm**, 30 L/min | **40 mm**, 30 L/min |
| Speed at the inlet | 6.4 m/s | 0.4 m/s (below the chamber's 0.45 m/s mean) |
| Push (momentum) | 3.8 mN, 15 % of the spray's 25 mN | 0.24 mN, 1 % |
| What it tests | a jet aimed straight into the capture (push-pull) | the same through-flow with no jet |
| Capture | 50 mm cone to a 10 mm pipe; 38.6 L/min out (0.34 m/s at the mouth, 8.2 m/s in the pipe) | the same |

**Checked** (2026-11-12, on a copy of your file after 8.2; nothing of yours touched): the three parts fuse into one
valid solid with 47 faces, every Part 7 link follows its face, and Gentle's 40 mm carrier gives the same face numbers.
Not checked for this layout: the mesh and the solve (the first layout meshed and ran clean by script). See 8.10.

### 8.0 The design, and why (read first)

**Push, not pull: you're right, for the AJP.**
- An AJP head needs the aerosol pushed into it. Its nozzle opens to the room at the substrate, so it can't sit in a
  suction line.
- A pump can't go before it either: the aerosol would go through the pump, and the droplets would be lost in it.
- So the chamber is pressurised slightly by the carrier, and the capture line carries the aerosol out under that
  pressure.
- On "sucking all the droplets into the suction thing": for a slide collector that is what you'd want, with the slide
  in the extraction line. The problem for the AJP is where the pump would have to sit.

**Why not one push design and one pull design?** In the CFD they are the same run.
- The solver is incompressible: pushing 30 L/min in through a hole, or pulling 30 L/min out so that 30 L/min comes in
  through the same hole, gives the same flow. Only the pressure level differs, and the solver doesn't care about
  that.
- What differs between real push and pull designs is **where the momentum goes in**.
  - A small inlet makes a **jet**. It keeps its push, so it reaches across the chamber: its speed falls only as
    1/distance.
  - A suction port is a **sink**. It draws from all round, so its pull dies fast. For the 10 mm capture at
    38.6 L/min: ~0.6 m/s one hole-width out, ~3 cm/s at 50 mm. That is slower than a 30 µm droplet settles.
  - Pull designs normally have a big, gentle make-up opening, so they have no jet.
- So the comparison worth making is **jet against no jet at the same flow**: Stream against Gentle. Gentle is also
  what a suction design looks like to the solver.

**A plain carrier, a cone on the capture (you, 2026-11-12).**
- The carrier's jet is set by its flow and its diameter; a plain cylinder is enough.
- At a sharp 10 mm capture hole the air separates at the edge and throws the bigger droplets onto the pipe wall. The
  cone brings the air in at 0.34 m/s and speeds it up over ~38 mm instead.
- All three parts go in FreeCAD, fused into your Fusion, so no new STEP is needed (a new one would mean re-picking
  Part 7's ~25 faces). That is also what the scripted builder will do later.

**30 L/min first.**
- It is the middle of Phase 7's 30–100 L/min.
- Air then leaves at 38.6 L/min (with the spray's 8.6), so the chamber's air is replaced every **55 s**. Today, with
  the 44 mm port, it is every 4.1 min.
- The well-mixed estimate (`../PLAN.md` Phase 7) says half of the 20 µm droplets get out at ~40 L/min.
- 10 and 100 L/min come next, on whichever design wins. At 100 L/min a 10 mm inlet would push 42 mN, more than the
  spray, so the hole has to grow with the flow (Phase 7's table).

**Where (your layout, 2026-11-12).**
- **Height y 210:** 28 mm below the nozzle's tip, above the layer the big droplets stay in. In the Chamber_v2 droplet
  run (`CFD_LOG.md` section 8), droplets over 60 µm never got above y 180; at your capture's spot the air had 1.0–1.2×
  the chamber's average of 0–20 µm droplets and none over 60 µm.
- **z −100, beside the spray, not through it:** the stream passes 112 mm in front of the spray's plane. The spray mixes
  the fines through the whole chamber within seconds anyway; the carrier's job is the through-flow.
- **In line, carrier to capture (push-pull):**
  - The jet entrains as it goes: by the far wall it carries ~180 L/min, ~5× its own flow, most of it chamber air.
  - The capture takes 38.6 L/min of that, from the jet's middle. By a free-jet estimate, a fifth to a quarter of the
    air there is fresh carrier gas that has picked up no droplets.
  - Whether the entrainment or the fresh gas wins is what Stream against Gentle shows: Gentle's 0.4 m/s is lost
    within a few cm, so its capture draws the chamber's own air.
  - If the fresh gas wins, the next variant moves the capture out of line (z −212.5 in the spray's plane: the same
    face numbers, and 1.1–1.3× the average of 0–30 µm there).
- **The stream passes 27 mm above the shadowgraph window's height** (y 182.8), 112 mm in front of the spray. 8.8 checks
  that the spray at the window is unchanged.
- **Clear of everything:** the arm runs up the x = 80 wall at y 250–530 (z −228 to −197), the atomiser's parts are
  all above y 237, and the z walls are the imaging windows.
- **One level slice at y 210** in ParaView shows the stream, the capture and the spray's cross-section.

**What to expect (textbook estimates; the CFD will say).**
- A free 10 mm jet at 6.4 m/s would be ~3.7 m/s half way across and ~2 m/s at the capture, about as wide as the cone's
  mouth by then.
- Nothing stands in its way, so it should arrive roughly straight, unless the chamber's circulation (0.45 m/s mean,
  driven by a spray pushing ~7× harder) bends it.
- Gentle's 0.4 m/s will be lost in the spray's circulation within a few cm of the inlet.

**For the AJP, later.**
- **The capture line will need a split before the head.** Your head takes 1.0–1.5 L/min of aerosol (the sheath gas is
  added in the head), ~30× less than the capture's 38.6 L/min, so a virtual impactor goes before it (`../PLAN.md`
  Phase 7).
- **The virtual impactor keeps everything above its cut, big droplets included.** So the capture's height is the
  upper cut: another reason it sits above the big droplets' layer.
- **For the chamber, the numbers to compare are the share of the band that leaves through the capture, and that share
  ÷ the capture's flow** (how concentrated it is).

**On the rig: the capture becomes the chamber's only way out, and its relief.** The CFD put the first layout's
chamber at ~+40 Pa (the capture pipe's 8.2 m/s). Never block the capture line with the carrier on (5 mm polycarbonate, `../PLAN.md`
Phase 7).

### 8.1 Two folders, then open your case under a new name (3 min)

Two folders, each with a double-click viewer in it, then FreeCAD:
```
mkdir -p /Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_stream_30 /Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_gentle_30
cp "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof/View flow.command" /Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_stream_30/
cp "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof/View flow.command" /Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_gentle_30/
open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2/Chamber_v2.FCStd"
```
**File → Save As** `/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_stream_30/Chamber_v2_stream_30.FCStd`, then
**File → Close**, and reopen it:
```
open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_stream_30/Chamber_v2_stream_30.FCStd"
```
**Why:**
- **Reopen:** as 7.1. CfdOF writes the case to `cfdof_cases/<document name>/case`. Reopened, the name is
  Chamber_v2_stream_30, so the case goes to `cfdof_cases/Chamber_v2_stream_30/case` and your Chamber_v2 stays as it is.
- **The names** are `<model>_<design>_<flow>`: the `_30` is the carrier's 30 L/min, so 10 and 100 L/min later become
  `_10` and `_100` beside them. No spaces or dots (OpenFOAM).
- **`View flow.command`:** double-click it in Finder to open the case in ParaView (8.8). It opens your newest saved
  view in that folder, or else the case at its last iteration.

### 8.2 The carrier and the capture (10 min)

Workbench **Part**. **Part → Primitives**: a **Cylinder**, a **Cone** and another **Cylinder**. Rename them (F2) and
set their Data tab. All three have Axis **(0, 1, 0)**:

| Name | Shape | Size | Position | Angle |
|---|---|---|---|---|
| **Carrier** | Cylinder | Radius **5 mm**, Height **21 mm** | x **81**, y **210**, z **−100** | **−90°** (shown as 270°) |
| **CaptureCone** | Cone | Radius1 **25 mm**, Radius2 **4 mm**, Height **40 mm** | x **269**, y **210**, z **−100** | **90°** |
| **Capture** | Cylinder | Radius **5 mm**, Height **25 mm** | x **300**, y **210**, z **−100** | **90°** |

**Check:** a short rod sticking 20 mm out of the x = 80 wall, and opposite it, in line, a funnel narrowing into a
10 mm pipe out of the x = 270 wall. Both 197 mm above the floor, 28 mm below the nozzle's tip, in front of the
atomiser.

**Why:**
- **They start 1 mm inside the chamber,** as the bore did (7.3): booleans fail where two surfaces only just touch. That
  1 mm is air already.
- **Axis (0, 1, 0), −90°** turns the cylinder's own z to −x, out through the x = 80 wall. **90°** turns it to +x, out
  through the x = 270 wall.
- **The cone** is 49 mm across where it meets the wall and 10 mm at 38 mm out (a ~28° taper). Then 18 mm of 10 mm pipe
  to the end disc at x 325.
- **Its tip is 4 mm, not 5:** the cone's surface then crosses the pipe's cleanly, instead of meeting it along a shared
  edge.
- **Each port has its own end disc** to pick as the boundary, as the 44 mm port does; the carrier comes in through a
  short pipe.

### 8.3 Add them to your Fusion (3 min)

1. In the tree, **drag Carrier, CaptureCone and Capture onto Fusion**, one at a time. They tuck under it. (Or: select
   Fusion, Data tab, **Shapes**, the **…** button, and add all three.)
   - **Fusion, not Fusion_Mesh.** Fusion sits at the top level of the tree (scroll up). Dropped on Fusion_Mesh, they
     join its refinement list instead and the chamber doesn't change. If that happens, drag them from there onto Fusion.
   - Close any open task panel first (its **Close** button): the tree and Recompute wait for it.
2. **Recompute** (the circular-arrows button right of Undo/Redo, Edit → Recompute, or ⌘R) if Fusion shows the blue
   recompute mark. It's greyed out when nothing needs recomputing.
3. **Part → Check Geometry** on Fusion: no errors, **1 solid, 47 faces** (Run BOP check off, as 7.2).
4. **Check your boundaries followed the faces.** Double-click **spray**: its face list should now say **Face47**. Click
   it: the bore's top lights up. Do the same for one refinement, e.g. **FloorRefinement → Face21**. Close each with
   **Cancel**.

**Why add them to the Fusion you have, not make a new union:**
- Every boundary and refinement you made points at Fusion's faces.
- When Fusion changes, FreeCAD 1.1 renumbers those links itself. Checked on a copy of your file: spray Face42 →
  Face47, and every other one (the table at the end of this part).
- A new union would have meant picking all ~25 faces again.
- **If a link didn't follow** (the wrong face lights up in step 4), re-pick it from the table at the end of this part.

### 8.4 Boundaries (5 min)

Workbench **CfdOF**; double-click **CfdAnalysis** if the tools are greyed out.

**Every face number in this part is Fusion's.** In a face picker's **Select from list** tab, click **Fusion** under
"Select objects" first, then tick the faces. Whichever object is highlighted there is the one whose faces you're ticking,
and **Flow Analysis Basic** (the imported STEP, 40 faces) has its own Face22, Face29 and so on, in other places. In the
list of picked faces, each should read **Fusion:Face…**.

1. **outlet → capture.** Double-click **outlet**.
   - **Remove** its face (Face35, the 44 mm port's end), and **add Face39**: the capture pipe's end disc, 78.5 mm²,
     at x 325.
   - Keep **Outlet, Static pressure, 0 Pa**. **OK**, then rename it **capture** (F2).
2. **carrier.** A new **Fluid boundary**:
   - **Inlet**, **Volumetric flow rate**, **5.0e-4 m^3/s**;
   - Intensity **5 %**, length scale **0.7 mm**;
   - Face: **Face29**, the carrier stub's end disc, 78.5 mm², at x 60. **OK**, rename it **carrier**.
3. **spray** and **wall**: unchanged.
4. **InitialiseFields:** double-click it and check the pressure comes from **capture**. It follows by itself, because
   capture is the same object your outlet was.

**Why:**
- **The 44 mm port is sealed by picking nothing.** Its end disc drops into the default wall.
- **Reusing the outlet object** keeps the initial pressure linked to it. A new outlet would have left that link empty.
- **5.0e-4 m³/s is 30 L/min.** The length scale is 0.07 × the hole, as for the spray (7.5).
- **Gas in = gas out:** 1.426e-4 (spray) + 5.0e-4 (carrier) = **6.426e-4 m³/s** out through the capture.
- The droplets tool counts what leaves through **capture** by that name (8.9).

### 8.5 The mesh (10 min clicking, ~25 s meshing)

Everything from Part 7 stays. OutletRefinement still refines the sealed port; leave it (harmless). Add, as in 7.7:
1. **Surface refinements** (mesh object selected, **Mesh refinement**, **Surface refinement**):
   - **CarrierRefinement:** **0.15**; Face22, Face29 (the carrier stub's side and end).
   - **CaptureRefinement:** **0.15**; Face34, Face37, Face39 (the cone, the pipe's side, the pipe's end).
2. **The stream cones.** Workbench **Part**, **Part → Primitives → Cone**, three times. All three share one Placement:
   Position **x 59, y 210, z −100**; Axis **(0, 1, 0)**; Angle **90°**. They start at the carrier's end and point
   across the chamber.

   | Cone | Radius1 | Radius2 | Height | reaches | Relative size | Cells |
   |---|---|---|---|---|---|---|
   | **StreamNear** | 7 mm | 10 mm | 71 mm | x 130, 50 mm into the chamber | **0.08** | 0.5 mm |
   | **StreamMid** | 8 mm | 20 mm | 131 mm | x 190, past the spray's x | **0.15** | 1 mm |
   | **StreamFar** | 10 mm | 45 mm | 216 mm | x 275, into the capture's mouth | **0.3** | 2 mm |

   - Shortcut, as 7.7: make one, copy and paste it twice, change only the radii and height.
   - Back in **CfdOF**: a **Volume refinement** for each, with the relative size from the table, ticking the cone
     itself. Hide the cones (Space).
   - **CaptureInside:** one more **Volume refinement**, **0.15**, ticking **CaptureCone** itself (the one already in
     Fusion; no new cone). 1 mm cells right through the cone, ~30,000 of them.
3. **Mesh it:** **Write mesh case**, **Run mesher**. About 25 s; **~1,652,500 cells** (Ben's Stream, 2026-11-13).
   - **Check Mesh:** "Mesh OK". Ben's Stream: 32 faces over 70° non-orthogonal, max 78.9°; max skewness 3.27 (Part
     7: ~54 faces). They sit where the x walls' layers stop at the carrier and the cone, as at the 44 mm port.
     Harmless at that count (7.7). Tell me if it says otherwise.
   - The panel only says OK or not. For the numbers (~15 s; the full report lands in `meshCase/checkMesh.log`):
     ```
     bash -c 'source /Applications/OpenFOAM-v2606.app/Contents/Resources/etc/bashrc && cd /Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_stream_30/meshCase && checkMesh -meshQuality > checkMesh.log 2>&1; grep -iE "cells:|non-orthogonal|skewness|Mesh OK|Failed" checkMesh.log'
     ```
   - **Run one mesher at a time.** In the check, two meshes run together sat for 10 min at the layers stage; alone,
     each took 23 s.

**Why these cells:**
- **The same rule as the spray's ladder (7.6):** about 10 cells across the stream's half-width all the way across.
  - Its half-width is ~5 mm for the first ~50 mm (the 10 mm hole's core), ~10 mm half way across and ~19 mm at the
    far wall: it spreads ~0.1 mm per mm.
  - So the cells go 0.5 → 1 → 2 mm, doubling as the stream's width doubles.
- **The last cone is wide (45 mm)** in case the chamber's circulation bends the stream off its straight line.
- **1 mm on the ports:** 10 cells across each 10 mm hole, and ~50 across the cone's mouth.
  - CaptureRefinement fines only the cone's wall; inside, the cells would grow towards the axis, and StreamFar stops at
    x 275, 5 mm into the cone.
  - CaptureInside keeps 1 mm all the way in. The stream converges there, and that's where the bigger droplets hit the
    cone or get through (the entrance losses, 8.9). It costs ~2% more cells.
- **No layers on the carrier, the cone or the pipe**, as on the 44 mm port. Droplets landing in the cone and pipe do
  matter here (the entrance losses, 8.9); without layers the fines' share there reads high (the near-wall artefact,
  report.md Checks 4), so read it for the 20–30 µm band.

### 8.6 Solve (~1 h)

1. Click **CfdSolver** in the tree (once; don't double-click). In the **property view's Data tab**, under Iteration
   Control: **Convergence Tol 1e-5**, **Max Iterations 4000**, **Steady Write Interval 500**.
   - They're not in the solver's task panel. No property view under the tree? **View → Panels → Property view**.
2. Double-click **CfdSolver**: **Solve in Parallel**, **10 cores**; **Write**, **Run**.
- **Plug in first** (70 W or more): the solve draws ~70 W, and on battery it would run flat partway through.
- Keep the Mac awake for 2 h, in the background so the Terminal window stays free:
  ```
  caffeinate -i -t 7200 &
  ```
- **~1.5 h** (Stream and Gentle 93 min each: 1.4 s an iteration on 10 cores, steady from the start).

**Why 4,000, when the droplets use iteration 2,000:**
- **2,000 matches the reference.** Chamber_v2's run used 2,000, so Stream and Gentle compare at the same point.
- **4,000 checks that 2,000 was enough.** The steady solve never fully settles: Part 7's residuals plateaued at ~2e-3,
  and the circulation wanders. In Part 6, droplets through iterations 1,000, 1,500 and 2,000 gave the same answer
  (CFD_LOG.md section 6).
- **This flow is new:** a second jet, and a capture that drives the circulation. Writing every 500 keeps 2,000, 3,000
  and 4,000, so the droplets can be run through two of them and compared.
- **Why Convergence Tol 1e-5:** CfdOF's default stops the solve once every residual is under 1e-3. Ben's first Stream
  solve (2026-11-13) stopped there at iteration 1,072, in 15 min, with no 2,000.
  - At the stop, Ux and Uz were still falling steadily, so the flow was still changing.
  - p had been flat at ~1e-3 since ~400, so with 1e-5 the solve runs the full 4,000.
  - Restarting from 0 costs nothing: the same mesh and cores give the same 500 and 1,000 again.

**Gas in = gas out** once it has finished (~30 s):
```
bash -c 'source /Applications/OpenFOAM-v2606.app/Contents/Resources/etc/bashrc && cd /Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_stream_30/case && for p in spray carrier capture; do mpiexec -np 10 postProcess -parallel -func "flowRatePatch(name=$p)" -latestTime 2>&1 | grep "of phi"; done'
```
It should print spray **−0.0001426**, carrier **−0.0005**, capture **+0.0006426** (in negative, out positive; checked
on the scripted case). It also writes a `postProcessing` folder into the case, which is harmless.

### 8.7 The second design: Gentle (10 min clicking, ~1.5 h solving)

1. **File → Save As** `/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_gentle_30/Chamber_v2_gentle_30.FCStd`,
   **File → Close**, and reopen:
   ```
   open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_gentle_30/Chamber_v2_gentle_30.FCStd"
   ```
2. Change only two things:
   - the **Carrier** cylinder's **Radius: 20 mm** (40 mm across);
   - the **carrier** boundary's length scale: **2.8 mm** (0.07 × 40 mm).
3. Recompute and **Check Geometry**: still **47 faces**. The face numbers don't change (checked on a copy of your
   file).
4. **Mesh** (~25 s, about 1.65 million cells like Stream's, Mesh OK; for the numbers, 8.5's checkMesh line with
   `Chamber_v2_gentle_30` in the path), then **solve** as 8.6. Run the gas balance with
   `Chamber_v2_gentle_30` in the path:
   ```
   bash -c 'source /Applications/OpenFOAM-v2606.app/Contents/Resources/etc/bashrc && cd /Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v2_gentle_30/case && for p in spray carrier capture; do mpiexec -np 10 postProcess -parallel -func "flowRatePatch(name=$p)" -latestTime 2>&1 | grep "of phi"; done'
   ```

**Ben's Gentle (2026-11-13), built by Claude by script** from a copy of Stream's saved file: Carrier radius 20 mm, carrier length scale 2.8 mm, both boundaries set on Fusion (carrier Face29, now 1,257 mm²; capture Face39), the solver at 4,000 / 1e-5 / 500. Mesh and case compared with Stream's file by file: only the carrier's surfaces and its length scale differ. 1,692,233 cells (40,000 more, the wider stub); Mesh OK, 30 faces over 70°, max 78.8°, skewness 3.27; patches spray 366, capture 445, carrier 3,590 faces.

**Why the stream cones stay:** the two meshes then differ only at the inlet, so any difference in where the droplets
go is the stream, not the mesh.

### 8.8 What to look at in ParaView

**Double-click `View flow.command`** in `cfdof_cases/Chamber_v2_stream_30/` (or open it from CfdOF as before), **Last
Frame**, colour by **U** (Magnitude), max **~3 m/s**. Once it looks right, **File → Save State** into the same folder
(e.g. `stream_view.pvsm`): the viewer opens your newest saved view from then on.
1. **Two cuts:**
   - **Slice**, **Y Normal**, origin **(0.175, 0.21, −0.157)**: a level cut through the stream, the capture and the
     spray just below the tip, seen from above.
   - **Slice**, **Z Normal**, origin **(0.175, 0.2, −0.1)**: the stream and the capture side-on.
2. **Where the carrier's gas goes:** **Stream Tracer**, Seed Type **Point Cloud**, Center
   **(0.070, 0.21, −0.1)**, Radius **0.004** (Gentle: **0.018**), Number of Points 200.
3. **Where the capture's air comes from:** the same at Center **(0.316, 0.21, −0.1)** (in the capture's pipe), Radius
   **0.004**. The tracer draws both ways from its seeds, so these lines show the path into the capture.
4. **The spray at the shadowgraph window:** **Filters → Data Analysis → Probe Location** at
   **(0.1637, 0.1828, −0.2125)** (55 mm below the lip). Your Chamber_v2 gives 15.5 m/s there. **The designs should
   match it within a few %.** If not, the stream is moving the spray in your measurement.

What to note:
- Does the stream arrive at the capture straight, or does the chamber's circulation bend it away?
- Does the capture's air come straight from the carrier (step 3's lines trace back to it), or from round about?
- How different is Gentle from Chamber_v2, away from the inlet?

### 8.9 The droplets through both (~6 h, unattended)

Once both have solved (plugged in; caffeinate keeps the Mac awake for 8 h). It leaves ~12 GB a flow (~85 GB for
the seven); the first try, on 2026-11-14, filled the disk, because the frames' flow copies were deleted only as each
stage ended (~500 GB at once for two 290 s runs). They are now deleted as it runs (`df -h /System/Volumes/Data`
shows what's free):
```
caffeinate -i -t 28800 &
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run_droplets.py" "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/settings/droplets_carrier_stream.yaml"
```

**What it runs** (`settings/droplets_carrier_stream.yaml`):
- The same droplets as 7.10, through seven flows:
  - **Chamber_v2:** the reference, the band leaving through the 44 mm port;
  - **Stream** and **Gentle**, each at iterations 2,000, 3,000 and 4,000: the band leaving through the capture.
    Neither design converges, and Stream's jet reaches the capture at 3,000 but not at 2,000 or 4,000 (8.10). The
    three snapshots' spread is the uncertainty.
- **Two endings, each with gusts on and off:**
  - **2 s:** the spray and carrier stop together after the 5 s spray, as in the slide test.
  - **290 s:** the flow keeps running for ~5 chamber volumes, then 10 s of still air to the rig's 300 s. This is
    **continuous running** into the AJP, the case that matters.
    - The droplets don't touch each other or the flow, so a continuous spray is many 5 s pulses added up. Each
      droplet's eventual fate is the answer, so the run lasts until almost nothing is left airborne.
    - Well mixed, 290 s leaves <1 % of the fines airborne in the designs. 120 s (the first plan) left ~1/9, which
      would have read the capture's share up to ~10 points low. Chamber_v2's port takes 8.6 L/min, so ~30 % of its
      fines are still airborne at 290 s; compare it as "where things stand at 5 min", not as an eventual fate.
- Results: one folder, `~/OpenFOAM/droplet_runs/<date>_<time>_carrier_stream/` (it prints the path):
  - **`View Stream.command`, `View Gentle.command`, `View Chamber_v2.command`:** double-click to open that flow's
    headline run in ParaView (gusts on, the flow kept 290 s); then First Frame, Play.
  - **`comparison.md`:** the results to read.
  - **`data/`:** everything else: each flow's own report, figures and CSVs, the other runs' views
    (`data/<flow>/paraview/*.command`), and the OpenFOAM cases.

**What to read in it** (the 0–30 µm band, weighted by the measured spray, by number):
- **"port":** the share that leaves through the capture (the 44 mm port for Chamber_v2, today 1.2 %). This is the
  headline. Compare it at 290 s and at 2 s.
- **Floor, walls, airborne at switch-off:** where the rest goes.
- **How concentrated:** the "port" share ÷ the flow out: 38.6 L/min for the designs, 8.6 L/min for Chamber_v2.
- **The > 30 µm bands at the capture:** what the stream lets through that the AJP doesn't want.

**What "port" lumps together** (the tool's fates, not yet split by port):
- The band tables' **"port"** is two fates added together:
  - **"port mesh":** reached the capture's end disc;
  - **"port tube":** touched anything beyond the chamber's walls, i.e. the inside of any stub (the capture's cone and
    pipe, the carrier's, the sealed 44 mm port's), or the carrier's end disc.
- `fates_by_size.csv` in each run's folder keeps them apart. **"port mesh" is what the capture delivers.**
- **"port tube" at the capture is lost on its cone and pipe walls:** the entrance losses the cone is there to cut.
  In `droplets.csv`, x_mm above 270 is the capture's cone and pipe, below 80 the carrier's stub. Without layers there,
  the fines' share reads high (8.5); read it for the 20–30 µm band.
- Droplets reaching the carrier's stub against its inflow should be next to none.

### 8.10 What the checks gave

**Your layout** (2026-11-12, on a copy of your file after 8.2):

| | Stream | Gentle |
|---|---|---|
| Fusion | 1 solid, **47 faces**, valid | the same |
| Your links after 8.3 | all followed their faces (table below) | the same |

**The first layout** (2026-11-02, by script; carrier on the x = 270 wall, a plain 10 mm capture at y 80 on the
x = 80 wall), for scale:

| | Stream | Gentle |
|---|---|---|
| Cells; meshing | 1,522,608; 23 s | 1,561,252; 23 s |
| checkMesh | Mesh OK; 65 faces over 70°, max 80.2°; max skewness 2.77 | the same |
| 30 iterations (on 7 cores, with setup) | ran clean; 2 min | ran clean |
| Gas in = gas out (iteration 30) | 1.426e-4 + 5.000e-4 = **6.426e-4 m³/s** out | |

**Your layout's Stream mesh (Ben, 2026-11-13):** 1,652,490 cells; Mesh OK; 32 faces over 70°, max 78.9°; max
skewness 3.27. All 9 volume refinements (CaptureInside among them) and both new surface refinements were in its
meshDict.

**Your Stream's first solve (Ben, 2026-11-13, CfdOF's default 1e-3 stop):** converged at iteration 1,072 in 15 min (0.81 s an iteration on 10 cores). Gas in = gas out: 1.426e-4 + 5.000e-4 = 6.426e-4 m³/s out through capture. Re-solved to 4,000 at 1e-5 for the droplets' 2,000 (8.6): ran clean (53 min), but **both new boundaries were on the wrong faces**. `capture` was the whole floor (18,792 faces at y 13) and `carrier` the atomiser arm's underside (y 250, x 80–143), picked on Flow Analysis Basic's Face39 and Face29, not Fusion's (the 8.4 note). The refinements were all on the right faces. Gas in = gas out can't catch this: it holds whichever faces they are. **Check the patches before solving:** after Write mesh case, `meshCase/constant/triSurface/` holds one `patch_*.stl` per boundary; the capture's should sit at x 325 and the carrier's at x 60.

**Your two flows at 4,000 (2026-11-13, patches checked):** Stream (Ben, re-picked on Fusion) and Gentle (by script)
each took 93 min. Both put gas in = gas out exactly at 2,000 and 4,000.

- **Neither reaches 1e-5.** The residuals level off by ~1,000: Stream at U ~1e-3, p 3–6e-2; Gentle at U ~2e-3,
  p 8–10e-2.
- **Chamber-wide, both are steady.** Mean speed is 0.40–0.44 m/s for Stream and 0.43–0.46 m/s for Gentle, with
  ~27 % of the volume above 0.5 m/s in each.
- **Locally, both wander.** Each 500-iteration snapshot differs from the 2,000 one by 31–56 % of the mean speed in
  Stream and 34–49 % in Gentle. Gentle wanders as much with no jet, so the wander is mostly the spray's own
  circulation (25 mN, against the stream's 3.8 mN), not the stream flapping. Pick a snapshot and the droplets
  inherit that one; 2,000, 3,000 and 4,000 together give the spread.
- **Stream's jet** (probes along y 210, z −100, at 2,000 / 3,000 / 4,000): 7.0 m/s at x 100; 2.8–6.2 at x 130;
  1.7–2.3 at x 190; 0.4–1.2 at x 250. It reaches the cone mouth at 0.56–0.70 m/s, off-centre: the jet carries air
  about two-thirds of the way across, then breaks up.
- **Gentle's carrier** leaves the 40 mm hole at 0.4 m/s and turns down at once (x 100: +0.28, −0.31, −0.14 m/s).
  Along the same line it runs 0.17–0.55 m/s, which is the chamber's own circulation, and the cone mouth sees
  0.39–0.52 m/s. The capture draws from wherever the circulation brings air.
- **Both:** the spray at the window runs 15.3–16.3 m/s, the capture pipe 9.2–9.3 m/s, and the floor jet spreads
  out at up to ~1.5 m/s.

- **Where the capture's air comes from** (400 seeds in the capture pipe, traced back, 2026-11-13). In Stream, the
  share coming straight from the carrier (within 0.6 m of path; the direct line is ~0.25 m) changes a lot from
  snapshot to snapshot. At 1,000–4,000 in steps of 500 it is 10, 32, 0, 14, 62, 0 and 0 %. The jet reaches the
  capture in some snapshots (3,000 best) and is bent toward the spray in most. In Gentle the share is 0 % in every
  snapshot. Most of the capture's air comes round the chamber's circulation.

Which design catches more of the 0–30 µm band is the droplet runs' question (8.9).

**The droplets (2026-11-14, `droplet_runs/2026-11-14_1439_carrier_stream/comparison.md`):** all seven flows, every
droplet accounted for. Stream 3000's and Gentle 4000's gusts-off 290 s runs hung (one droplet looping in OpenFOAM's
tracking) and are missing.
- **Out through the capture**, gusts on, flow kept 290 s, % of each size fired:

  | | 2 µm | 6 µm | 10 µm | 20 µm | 30 µm | 0–30 µm band, by the measured spray |
  |---|---|---|---|---|---|---|
  | Chamber_v2 (the 44 mm port) | 15 | 16 | 8 | 5 | 0.5 | 4.8 |
  | Stream 2,000 / 3,000 / 4,000 | 41 / 30 / 44 | 31 / 23 / 41 | 25 / 19 / 33 | 9 / 6 / 13 | 1 / 1 / 3 | 9.6 / 7.6 / 13.7 |
  | Gentle 2,000 / 3,000 / 4,000 | 45 / 39 / 47 | 39 / 32 / 38 | 31 / 24 / 34 | 10 / 13 / 11 | 1 / 2 / 2 | 12.3 / 12.2 / 12.4 |

- **Both designs take ~2–3× the bare chamber's fines; neither wins every snapshot.** Gentle is steady from snapshot
  to snapshot; Stream swings, and its worst snapshot (3,000) is the one where the jet goes straight in (carrier gas,
  not chamber air, into the capture). With gusts off, Stream takes more at 10–14 µm (44–50 % against 30–32 %).
- **The fines' biggest sink is the atomiser and its arm** (gusts on: 40–60 % of ≤ 6 µm in the designs, 70–83 % in
  Chamber_v2). Largely an artefact: the atomiser has no near-wall layers (only the floor and walls got them, 7.6),
  and 0.5 µm tracers land on it 5–7 % in 5 s with gusts on (under 1 % with gusts off; 0 % on the layered floor).
  With gusts off the designs' capture takes 47–66 % of 2–6 µm, the atomiser 15–29 %, and 19–26 % of the 2 µm stay
  airborne on closed streamlines. Until the atomiser has layers, the capture's true share of the fines is somewhere
  between the two.
- **The floor's cut** (gusts on, within 30 mm of the spray axis): Chamber_v2 27–28 µm (the 2 Nov run's 28 µm
  reproduced), Gentle 27–28.5, Stream 29–31; gusts off 21–25.
- **The floor's share of the 0–30 µm band** across snapshots: Stream 62.8–67.9 %, Gentle 63.5–65.7 % (the tolerance
  is 5 points).

**Not checked:** the two hung runs. The atomiser with near-wall layers on it is checked in 8.11: the artefact goes,
and Gentle's capture share rises to 16–17 %.

### 8.11 Chamber_v3: the base model from now on (built by Claude, 2026-11-14; ~10.5 h overnight)

**Chamber_v3 is Chamber_v2 with the atomiser treated like the floor:** the near-wall layers on every face a droplet
can touch, so the fines' deposit on it is no longer the tracking's artefact (8.10). **Start new designs from
`~/OpenFOAM/cfdof_cases/Chamber_v3/Chamber_v3.FCStd`**, not Chamber_v2. Your Chamber_v2 files are untouched.

**What changed, in the FreeCAD tree:**
- **`StepFix (0.1 mm: arm end flush with body)`**, a box in `Fusion`. The imported air had a 0.1 mm step:
  - the arm's end below the body was at x = 130.0, while the body's side above it is at x = 129.9;
  - the box (x 129.9–130.0, y 280–305, z −227.5 to −197.5) is air, so the arm's end is now flush with the body.
  - The step wasn't on the real atomiser; it broke the layers there (open cells).
  - Every boundary's and refinement's faces were re-found by position (the face numbers shift).
  - **`Chamber_v3_air.step`** beside the `.FCStd` is the fixed air body, to open in Fusion 360 or anything else.
- **`AtomiserLayers`** (11 faces, 115,403 mm²: the body and arm) and **`NozzleBlockLayers`** (12 faces, 13,238 mm²:
  the nozzle block, its neck, the pocket round them and the body's underside), under the mesh.
  - Both have the walls' layers: 10, ratio 1.3, first 0.15 mm.
  - `NozzleBlockLayers` also has a finer surface mesh (0.25 of the base, 2 mm). The pocket is 13 mm across, and at
    the base 8 mm the layers from its sides collided (inside-out cells).
  - The tip, cap and bore keep their own refinements, as before.
- **`allowDiscontinuity 1`** on both, in `meshCase/system/meshDict`. Without it, cfMesh spreads their layer count to
  the nozzle tip and skews the mesh there (85–90 faces). CfdOF has no box for it, and **Write mesh drops it**. After
  every Write mesh of a Chamber_v3 case, run this before Run mesher:
  ```
  /Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof/add_layer_discontinuity.py" ~/OpenFOAM/cfdof_cases/<case>/meshCase
  ```
  It prints "allowDiscontinuity added" (or "already has") for both.

**The three cases** (`~/OpenFOAM/cfdof_cases/`):

| Case | Made from | Cells | checkMesh |
|---|---|---|---|
| `Chamber_v3` | `Chamber_v2` | 1,351,969 (was 1,225,011) | 100 faces skewness > 4 (max 4.8) |
| `Chamber_v3_stream_30` | `Chamber_v2_gentle_30`'s file, the carrier hole back to 10 mm and its length scale to 0.7 mm (Stream's own file on disk predates its boundary fix) | 1,778,254 (was 1,652,490) | 155 faces skewness > 4 (max 4.5) |
| `Chamber_v3_gentle_30` | `Chamber_v2_gentle_30` | 1,818,050 (was 1,692,233) | 157 faces skewness > 4 (max 4.5) |

- **The skewed faces** all sit at one corner, within ~1 mm. That's where the arm's side meets the body's side and
  its bottom edge (x 129–129.5, y 304–305, z −227.5 or −197.5), a mix of inside and outside corners. Matching the
  surface mesh on all three faces there didn't change it (92–97 faces, max 4.6).
  - Skewness above 4 is checkMesh's warning, not an error.
  - It's away from the jet and the capture. There are no open or inside-out cells.
- **The layers formed:** the first cell centre beside the atomiser is 0.01–0.1 mm from it, down from 0.46–1.7 mm
  (the walls' is 0.06 mm).
- **The cases:** every file is the same as the original's except `system/createPatchDict`, which merges the two new
  patches into the walls. That includes Stream's carrier inlet, rebuilt from Gentle's file.
- **On the way** (scratch builds, since deleted): `Chamber_v2_*_atomiser_layers` layered only the body and arm.
  Everything else gave open or inside-out cells until the step was closed and the pocket's mesh refined.

**Look at it:**
- **In FreeCAD:** open `Chamber_v3.FCStd`. `StepFix` is in `Fusion`; the two layer settings are under the mesh.
- **In ParaView:** open the mesh with the command below, Apply, then **Slice** at z = −212.5 (normal z), shown as
  **Surface With Edges**. Zoom in on the atomiser: the thin layers hug it all round, as they do the walls.

```
open -n -a /Applications/ParaView-6.2.0.app --args /Users/benschofield/OpenFOAM/cfdof_cases/Chamber_v3/meshCase/pv.foam
```

**Overnight** (plugged in; it solves the three flows one after another, then runs the droplets,
`settings/droplets_chamber_v3.yaml`):
```
cd "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof"
caffeinate -i -t 43200 &
./overnight_chamber_v3.sh
```
- **The watchdog:** a droplet run whose log stops changing for 15 minutes is stopped and logged as failed, and the
  sweep carries on. A stopped run is left out of the comparison; its flow's other runs are kept. (Since
  2026-11-15 a stalled droplet stage restarts instead, below.)
- **One risk:** Chamber_v3 stops early if its residuals all fall below 1e-3. Chamber_v2's sat at U ~2e-3, p ~6e-3
  at 2,000. If it does stop early, iteration 2,000 won't exist, and only its droplet runs fail.

**What it gave (2026-11-14/15, `droplet_runs/2026-11-15_0145_chamber_v3/comparison.md`):**
- **The flows:** all three solved to the end (Chamber_v3 2,000 in 40 min; Stream and Gentle 4,000 in 94 and 101 min),
  no errors, gas in = gas out exactly. The air is as on v2: mean speed 0.44–0.46 m/s, and the designs' air differs from
  Chamber_v3's by 44–70 % (33–77 % on v2).
- **The atomiser artefact is gone.** 0.5 µm tracers on the atomiser, gusts on: 0.3–0.4 % (5–7 % on v2). The 0–30 µm
  band's deposit on it, gusts on, flow kept 290 s: 4–6 % (17–22 % on v2); at 2 µm, 19 % in Chamber_v3 and 5–8 % in
  Gentle (83 % and 40–60 % on v2). What is left is the fines' own settling and impaction.
- **Out through the capture**, gusts on, flow kept 290 s, % of each size fired:

  | | 2 µm | 6 µm | 10 µm | 14 µm | 20 µm | 30 µm | 0–30 µm band, by the measured spray |
  |---|---|---|---|---|---|---|---|
  | Chamber_v3 (the 44 mm port) | 37 | 32 | 20 | 11 | 4 | 0 | 6.2 (4.8 on v2) |
  | Gentle 2,000 / 3,000 / 4,000 | 70 / 71 / 72 | 67 / 67 / 70 | 48 / 46 / 50 | 30 / 30 / 30 | 12 / 9 / 12 | 1 / 2 / 1 | 16.2 / 15.5 / 17.2 (12.2–12.4 on v2) |
  | Stream 2,000 / 3,000 / 4,000 (the rerun, below) | 41 / 77 / 72 | 33 / 62 / 62 | 21 / 49 / 45 | 12 / 33 / 26 | 6 / 15 / 10 | 0 / 3 / 1 | 7.6 / 18.3 / 15.6 |

  - **Gentle takes ~2.6× the bare chamber's fines**, and the same in every snapshot (within 2 points). The fines the
    atomiser used to take now reach the capture. In Chamber_v3, 40 % of the 2 µm are still airborne at 290 s.
  - **Gusts off** (290 s): Chamber_v3 6.7 %, Gentle 7.0–8.3 %, Stream 4,000 12.3 %. Stream takes more at 10–14 µm
    (57 and 27 % against Gentle's 47–54 and 12–15 %), as on v2.
- **Stream's 290 s runs mostly hung:** 5 of its 6 (both at 2,000 and 3,000, gusts on at 4,000), stopped by the
  watchdog 13–50 s into the spray (1 of 6 on v2). Every 2 s run finished. By 2 s the capture has taken only 1.5–4.4 %
  (Stream) and 3.5–4.2 % (Gentle), too early to rank them. OpenFOAM v2606's tracking loop has no limit for a stuck
  droplet: `maxTrackAttempts` is declared in `KinematicParcel.C` but `move()` never uses it.
- **Why they hang (found 2026-11-15):**
  - The runs repeat exactly, because the gusts' random numbers are seeded by the processor number. A rerun from 0
    hangs at the same moment.
  - The stuck droplet is in a near-wall layer cell so thin and twisted that OpenFOAM can't split it into valid tets.
    The log says "No base point for face ..., produces a valid tet decomposition".
  - The one caught is a 0.035 mm sliver on the nozzle block's underside (x 181, y 241, z −216).
  - `checkMesh -allGeometry` finds 2,239 such faces in Stream v3, 2,238 in Gentle v3 and 1,809 in Stream v2, out of
    5.4 M. Most are in the capture cone's layers; v3 adds some on the atomiser.
  - Every run passes through them, Gentle's and Chamber_v3's too. Now and then a droplet hits one exactly and loops.
  - A restart from the last frame (positions rounded to 10 digits, a nudge of ~1e-10 m) runs past it.
- **The fix (2026-11-15):** a droplet stage that stalls for 5 minutes now restarts from its newest frame, up to
  4 times, instead of failing. Restarting from the frame it began from would repeat exactly, so there the droplets'
  positions are first rounded to 8 figures, then 6. Each run's `run.json` lists its restarts, and the stuck logs are
  kept as `log.stage1.stalled1` and so on. Tested on the caught case: it restarted once and ran on.
- **Stream again** (~2.5 h; then all seven flows compared, `droplet_runs/<date>_<time>_chamber_v3_all/comparison.md`):
  ```
  cd "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof"
  caffeinate -i ./rerun_stream_v3.sh
  ```
- **What the rerun gave (2026-11-15, `droplet_runs/2026-11-15_1218_chamber_v3_stream/`):**
  - Stream 2,000, gusts on, 290 s finished after one restart: 7.6 % of the 0–30 µm band out through the capture.
  - Stream 4,000 repeated the overnight runs exactly.
  - Four runs of 290 s still failed. In three, after every nudge the droplet came back onto the same bad face: the air
    carries droplets into those cells. In the fourth (4,000, gusts on), the frame it restarted from held a number
    OpenFOAM writes but can't read back (1.2e-311); such numbers are now set to 0 before a restart.
- **The guard (2026-11-15):** from a stage's first stall on, droplets are kept out of those cells.
  - The cells are both sides of every face `checkMesh -allGeometry` flags: 2,851 cells in Stream v3. A faceZone of
    their internal faces carries OpenFOAM's `removeParcels`, which takes a droplet out the moment it reaches one.
    Droplets already in one are taken out of the frame the stage restarts from.
  - Only the flagged faces is not enough: the droplet loops inside the cell without touching its bad face (tested).
  - They are near-wall layer cells, so a removed droplet counts as a hit on the wall its cell is on, or as port if the
    cell is within 80 mm of the capture's end (its cone and pipe). `droplets.csv` flags each one (`removed_in_bad_cell`),
    and `run.json` gives how many and where.
  - Counting the cone's as port matters. Tested on the stuck cases, about a third of the droplets reaching the cone
    went into its bad cells. Without the guard, droplets that reach the mouth are almost all captured: 687 against
    10 on the x = 270 wall by 28 s.
  - Each case's own `faceZones` and cloud file are new files. The meshes stay shared (hard links) and unchanged.
- **Stream's four stuck runs carried on** from their newest frames, guarded (~1 h; then all seven compared again):
  ```
  cd "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof"
  caffeinate -i ./resume_stream_v3.sh
  ```
  Any run folder's stuck runs: `run_droplets.py --resume <flow folder> [<flow folder> ...]`.
- **What it gave (2026-11-15 17:07, `droplet_runs/2026-11-15_1707_chamber_v3_all/comparison.md`, all seven at 290 s):**
  - All four finished after one guarded restart each; 60,000 of 60,000 droplets accounted for in every run.
  - The guard removed 200–432 droplets a run (0.3–0.7 %): 58–72 % of them at the capture cone (counted as port), the
    rest at the atomiser.
  - The 0–30 µm band out through the capture, by the measured spray:

    | | gusts on | gusts off |
    |---|---|---|
    | Chamber_v3 | 6.2 | 6.7 |
    | Gentle 2,000 / 3,000 / 4,000 | 16.2 / 15.5 / 17.2 | 7.0 / 8.3 / 7.9 |
    | Stream 2,000 / 3,000 / 4,000 | 7.6 / 18.3 / 15.6 | 7.0 / 12.6 / 12.3 |

  - **Gentle is steady:** about 2.6× the bare chamber with gusts on, within 2 points across the snapshots.
  - **Stream depends on the snapshot.** At 3,000 and 4,000 it matches or beats Gentle (2 µm: 72–77 % against 70–72 %).
    At 2,000 it barely beats the bare chamber, gusts on or off. Their mean (13.8 % gusts on) is below Gentle's (16.3 %).
    The steady solve's snapshots stand in for a jet that wanders in time (8.10: 3,000 is the snapshot where 62 % of
    the capture's air came straight from the carrier; 2,000 and 4,000 had none), so the real jet is likely somewhere
    in between, varying.
  - **Gusts off**, Stream is at or above Gentle in all three (12–13 % at 3,000 and 4,000).
  - **The guard's own effect is small.** Not counting the cone's removed droplets as port lowers Stream's numbers by at
    most 1.5 points (gusts on 17.2 / 15.1 at 3,000 / 4,000). Its atomiser removals add ~1 point to the atomiser's share
    in the guarded runs. Stream 2,000 gusts on is unguarded (it got past on a plain restart).

### The faces after 8.3

**Your existing links, renumbered by FreeCAD** (checked on a copy of your file; re-pick from here if one didn't
follow):

| Link | Was (Part 7) | Now |
|---|---|---|
| spray | Face42 | **Face47** |
| outlet (the 44 mm port's end) | Face32 | Face35 (then swapped for Face39 in 8.4) |
| BoreRefinement | Face40, 41, 42 | **Face45, 46, 47** |
| TipRefinement | Face34–39 | **Face38, 40, 41, 42, 43, 44** |
| CapRefinement | Face30, 33 | **Face32, 36** |
| OutletRefinement | Face27, 32 | **Face28, 35** |
| FloorRefinement | Face20 | **Face21** |
| WallsRefinement | Face10, 18, 19, 21, 26 | **Face10 (x = 80), 18 (lid), 19 (z = −17.5), 20 (z = −297.6), 27 (x = 270)** |

**The new faces** (the same numbers for Stream and Gentle, and with the capture moved to z −212.5):

| Face | What | Area (Stream / Gentle) | Centre (mm) |
|---|---|---|---|
| Face29 | the carrier stub's end disc: **carrier** | 78.5 / 1,257 mm² | (60, 210, −100) |
| Face22 | the carrier stub's side | 628 / 2,513 mm² | (70, 210, −100) |
| Face39 | the capture pipe's end disc: **capture** | 78.5 mm² | (325, 210, −100) |
| Face37 | the capture pipe's side | 562 mm² | (316, 210, −100) |
| Face34 | the capture's cone | 3,880 mm² | (284.5, 210, −100) |
| Face10 / Face27 | the x = 80 / x = 270 walls, now with the holes | 192,949 / 192,045 mm² (Gentle: 191,771 at x = 80) | |

---

## Part 9. Nozzle designs on a 2D wedge

Its own guide: **`NOZZLE_WEDGE_GUIDE.md`** (this folder, written 2026-11-08). A round nozzle drawn as a half-section
in Fusion, meshed by CfdOF as a 5° slice, the fix CfdOF's wedge needs (its cut faces), and the mesh and domain checks.

---

## In ParaView

**To open a case without FreeCAD:** double-click **`View flow.command`** in its folder, `~/OpenFOAM/cfdof_cases/<case>/`.
It opens your newest saved view there (**File → Save State** into that folder), or else the case at its last
iteration. Every case has one from 2026-11-12 (copy it into a new case's folder from
`Flow Visualisation/cfdof/View flow.command`; 8.1 shows how). `~/OpenFOAM/TESTS.md` says what each case is.

The case opens with the mesh in **metres** (the box is 0–0.3, 0–0.2, 0–0.35). The slice and streamline positions
below are for the **box** (Parts 3–4). Your own chamber has different coordinates: use the ones in Part 5.

1. Press **Apply** (green, Properties panel) if the model is grey.
2. Top toolbar: the **Last Frame** button (⏭), so you see the final iteration, not the start.
3. Colour by velocity: the drop-down above the view → **U**, then **Magnitude**.
4. **A slice through the middle:** Filters → Common → **Slice**. Normal **Y Normal**, Origin y **0.1**. **Apply**.
   Hide the main object (eye icon) to see the slice. This is the chamber cut through the inlet, outlet and nozzle.
5. **Streamlines from the inlet:** select the case again, Filters → Common → **Stream Tracer**. Seed Type **Point
   Cloud**, Center (0.3, 0.1, 0.175), Radius 0.003, Number of Points 200. **Apply**.
6. Rescale the colours to what you see: the **Rescale to data range** button (with the spray, the 245 m/s nozzle
   swamps everything; type a smaller max, e.g. 2 m/s, in the colour map editor to see the chamber's slow circulation).

## If you get stuck

- **The answer key.** `chamber_box.FCMacro` (this folder) builds parts 2–3 in one go: open it in FreeCAD
  (File → Open), then **Macro → Execute macro**. Set `SPRAY = True` at the top for part 4.
  ```
  open -a FreeCAD "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof/chamber_box.FCMacro"
  ```
- **"Illegal instruction: 4"** when the solver starts: a boundary has no faces (a pipe lost from the mesh). Refine
  the whole pipe (part 3, step 6).
- **The flow looks frictionless at the walls:** the walls boundary is missing its "default" tick (part 3, step 4).
- **Nothing happens on Run:** the CfdOF report view (View → Panels → Report view) shows OpenFOAM's messages.
