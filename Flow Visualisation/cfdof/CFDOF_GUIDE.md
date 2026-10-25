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

---

## In ParaView

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
