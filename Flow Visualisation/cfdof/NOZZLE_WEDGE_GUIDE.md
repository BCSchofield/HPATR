# Part 9. Nozzle designs on a 2D wedge

Written 2026-11-08 for Ben. This follows on from `CFDOF_GUIDE.md` (Parts 0–8, same folder): the same FreeCAD,
CfdOF, OpenFOAM and ParaView, and the same click-by-click style. Part 0's settings (the dependency check, **Append
document name to output directory**) still apply.

**What you do here.** Draw a nozzle and the air around it as a flat half-section in Fusion. CfdOF turns that into a
5° slice of the round jet, one cell thick. You solve it, fix one thing CfdOF gets wrong, solve it again, and run the
two checks that say whether the answer can be trusted.

**The example nozzle (Nozzle_A):**
- a Ø4 mm feed pipe;
- a 30° (half-angle) contraction;
- a **1.11 mm × 3 mm bore**, the same exit as your Chamber_v2;
- the **same gas**: 1.426e-4 m³/s, so 147 m/s out of the bore.

The nozzle shape is made up. It gives you a case whose numbers are known before you start. Your own designs swap
into the same domain later (9.12).

The picture of the domain, to scale, with every boundary:
**https://claude.ai/artifact/JgfQEQKsi6fua2yZBMs2Cn**

**Checked by script first** (2026-11-08, on scratch copies; the same objects and settings as the clicks below).
- **Nozzle_A:** 70,837 cells, meshed in 9 s, Mesh OK.
  - As CfdOF writes it, 1,500 iterations take 3.5 min, and the jet comes out wrong (9.6).
  - After 9.7's fix, the solve converges in 1,429 iterations (2.5 min) to a proper round jet.
- **Both checks were run too** (9.10, 9.11). 9.13 has every number.
- What was tried and why: `CFD_LOG.md` section 9.

| What | FreeCAD file | Case folder |
|---|---|---|
| The example | `cfdof_cases/Nozzle_A/Nozzle_A.FCStd` | `cfdof_cases/Nozzle_A/case` (and `case_symmetry`, 9.6) |
| Check 1: every cell halved | `cfdof_cases/Nozzle_A_fine/Nozzle_A_fine.FCStd` | `cfdof_cases/Nozzle_A_fine/case` |
| Check 2: the domain 1.5× bigger | `cfdof_cases/Nozzle_A_big/Nozzle_A_big.FCStd` | `cfdof_cases/Nozzle_A_big/case` |

(`cfdof_cases` is `/Users/benschofield/OpenFOAM/cfdof_cases/`.)

---

## 9.0 What this is, and why (read first)

**Why a 2D wedge.**
- A round nozzle with no swirl and no side holes makes the same flow at every angle round its axis.
- So one thin slice holds the whole answer. CfdOF meshes a **5° slice, one cell thick**: 70,837 cells and 2.5 min,
  where the full round jet at the same resolution would be millions of cells.
- **Not a flat 2D half.** A flat 2D model is an infinitely long slot, which makes a plane jet. A plane jet slows as
  1/√distance; a round jet slows as 1/distance. A flat model would give the wrong answer for a round hole.

**What it can't do.**
- **Anything not round:** the effervescent atomiser's discrete aerator holes, a side feed, swirl. Those need a 3D
  half or quarter model with symmetry planes.
- **Two-phase flow:** this is the gas alone. It tells you what the nozzle's shape does to the gas jet, not how the
  liquid breaks up.
- **The chamber:** that is Parts 7–8. A design that wins here can be drilled into the chamber model afterwards.
- **High speed:** 147 m/s is Mach ≈ 0.43, already at the edge of what an incompressible solve (simpleFoam) handles.
  A design that narrows the exit further at the same flow would need **Physics → Non-isothermal**
  (buoyantSimpleFoam). Choked flow needs HiSA, which isn't installed.

**How CfdOF makes the wedge.**
1. You give it a flat face swept straight into a thin block (a 1 mm "pad").
2. cfMesh meshes the block in 3D as usual.
3. A **Mesh refinement** set to **Extrusion → 2D wedge mesh** then takes only the cells on the block's flat face and
   sweeps them 5° round the axis. The 3D mesh is thrown away.

**The catch, found in the test (2026-11-08).**
- CfdOF writes the wedge's two cut faces as one **symmetry** patch. That is close to right in principle, but in
  practice it ruins this jet: it goes hollow, and its centre stops within 6 exit diameters.
- OpenFOAM has a boundary type made for this, **wedge**. The same mesh with the cut faces as wedge patches gives a
  proper round jet:

  | Cut faces | Centre speed at 0 / 4 / 10 / 30 D | Where the speed falls to half, at 30 D |
  |---|---|---|
  | CfdOF's **symmetry** | 161 / 29 / 0 / 0 m/s: hollow | 7.2 D, a ring round an empty centre |
  | OpenFOAM **wedge** | 162 / 162 / 100 / 27 m/s | 3.3 D |
  | a real round jet (textbook) | core to ~6 D, then 6 × 147 × D/x: 88 / 29 at 10 / 30 D | 2.8 D |

- CfdOF has no button for wedge patches. So you run the case once as CfdOF writes it (9.6, and you see the problem
  for yourself), then make the change by hand in Terminal (9.7) and solve it again (9.8).

**The domain** (D = the exit diameter, 1.11 mm):

| Region | Size | For 1.11 mm | Why |
|---|---|---|---|
| Behind the exit plane | 10 D | 11.1 mm | The jet pulls air in from behind as well as from the side. |
| Radial, from the axis | 25 D | 27.75 mm | At the outlet the jet is ~20 D wide (out to where it is 5 % of its centre speed), so this leaves ~5 D clear. |
| Downstream of the exit | 100 D | 111 mm | Designs differ mostly in the first ~30 D; beyond that every jet with the same flow and push looks alike. 50 D is the shortest worth using; 100 D costs little in 2D. |
| Feed pipe before the contraction | 5 × its diameter | 20 mm for Ø4 | The gas arrives with a settled profile, whatever the inlet does. |

**The boundaries:**
- **Downstream face: Outlet, 0 Pa.**
- **Side face and back face: Open, ambient pressure, 0 Pa.** The jet drags air in through these, many times its own
  gas by the outlet. As walls they would box the jet in, which is the chamber model's job.
- **Nozzle walls: no-slip.**
- **Axis: Symmetry.** The sweep collapses the cells on the axis into thin prisms, which is correct, so this boundary
  ends up with no faces at all.
- **Inlet: a uniform velocity, not a flow rate.** CfdOF's Volumetric flow rate spreads the number you type over the
  inlet face, and in a 5° slice that face is only 5/360 of the round inlet: you'd have to type 1.426e-4 × 5/360. A
  velocity doesn't care about the angle: 1.426e-4 m³/s ÷ the Ø4 feed's area = **11.348 m/s**.

## 9.1 Three folders (1 min)

```
mkdir -p /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A_fine /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A_big
```

## 9.2 Draw it in Fusion (20 min)

You draw one closed outline: the nozzle's inside and the air round it, from the axis outwards. It looks like Fig. 2
on the picture page: a long rectangle with the nozzle notched into its bottom-left corner and the feed pipe poking out
to the left.

**1. A new design in mm.** **File → New Design.** In the browser (left), **Document Settings → Units: Millimeter**.

**2. The parameters.** **Solid** tab → **Modify → Change Parameters**. Under **User Parameters**, press **+** for
each row:

| Name | Unit | Expression | What |
|---|---|---|---|
| `D` | mm | `1.11 mm` | exit (bore) diameter |
| `Dfeed` | mm | `4 mm` | feed pipe diameter |
| `Dbody` | mm | `8 mm` | nozzle body's outside diameter |
| `Lfeed` | mm | `20 mm` | feed pipe length before the contraction |
| `Lcon` | mm | `2.5 mm` | contraction length (gives 30° with these diameters) |
| `Lbore` | mm | `3 mm` | bore length |
| `Dom` | No Units | `1` | domain size: **1** now, **1.5** for check 2 (9.11) |
| `Lback` | mm | `10 * D * Dom` | air behind the exit plane |
| `Rdom` | mm | `25 * D * Dom` | air out from the axis |
| `Ldown` | mm | `100 * D * Dom` | air downstream of the exit |

**Why parameters:** check 2 is then one number (Dom 1 → 1.5), and your own designs change only the nozzle's.

**3. The sketch.** **Solid → Create Sketch**, and click the **XY** plane (from the origin, in the browser or the
view). The nozzle axis is the **X axis** and the exit plane is the **Y axis**, so the lip sits on the origin's
vertical line. The flow goes to **+X**, and everything is drawn **above** the X axis (r along +Y).

**4. The outline.** **Line** (L). Click these ten corners in order, roughly where the table says, then click the
first one again to close it. Esc. Don't worry about exact positions: the dimensions in step 5 fix them.

| Corner | Where (x, y) mm | Line from here to the next corner is |
|---|---|---|
| P1 | (−25.5, 0) | the **inlet** (up the left end of the feed) |
| P2 | (−25.5, 2) | the **feed pipe wall** |
| P3 | (−5.5, 2) | the **contraction** (slopes down) |
| P4 | (−3, 0.555) | the **bore wall** |
| P5 | (0, 0.555) | the nozzle's **front face** (up the Y axis), from the lip |
| P6 | (0, 4) | the nozzle **body's outside** (back to the left) |
| P7 | (−11.1, 4) | the **back face** of the air (up) |
| P8 | (−11.1, 27.75) | the **side** of the air (along the top) |
| P9 | (111, 27.75) | the **outlet** (down the right end) |
| P10 | (111, 0) | the **axis** (back along the X axis to P1) |

**5. Constrain and dimension it.** Fusion adds most horizontal and vertical constraints as you draw. Check each
straight line has one (the H or V glyph), except the contraction, which slopes. Then:
- the **axis line** (P10–P1): select it and the origin's **X axis**, **Collinear**;
- the **front face line** (P5–P6): select it and the origin's **Y axis**, **Collinear**.

Then **Sketch Dimension** (D), typing the parameter name as each value:

| Dimension | Between | Value |
|---|---|---|
| inlet height | P1–P2 (vertical) | `Dfeed / 2` |
| feed pipe length | P2–P3 (horizontal) | `Lfeed` |
| contraction length | P3 to P4, horizontally | `Lcon` |
| bore length | P4–P5 (horizontal) | `Lbore` |
| bore radius | the X axis to the bore line | `D / 2` |
| body radius | the X axis to the body line (P6–P7) | `Dbody / 2` |
| air behind | the Y axis to the back face (P7–P8) | `Lback` |
| air out | the X axis to the top line (P8–P9) | `Rdom` |
| air downstream | the Y axis to the outlet line (P9–P10) | `Ldown` |

The lines turn black when it is fully constrained: those nine dimensions and the two collinears are exactly enough.
**Finish Sketch.**

**6. Pad it.** **Extrude** (E). Click inside the outline (one profile, the whole shape). **Distance 1 mm**, Direction
**One Side**, Operation **New Body**. **OK.** Positive distance goes along +Z, as in the check; the other way would
work too, since CfdOF sweeps the slice evenly either side of the sketch plane.

**Why 1 mm:** cfMesh needs the block to be at least **4 of its biggest cells thick**, and the biggest cells here are
0.25 mm. In the test, a 1 mm block with 1 mm or 0.5 mm cells lost the inlet and outlet completely (they came out
with no faces), and the mesh was broken. Thicker only makes the throwaway 3D mesh bigger.

**7. Export.** **File → Export…**, Type **STEP Files (*.stp, *.step)**, tick **Save to my computer**, and save it as
`/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/Nozzle_A.step`. **Save** the Fusion design too (e.g. "Nozzle_A
wedge").

## 9.3 Open it in FreeCAD (3 min)

```
open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/Nozzle_A.step"
```
1. The tree shows the design (an assembly) with the body inside it. Use **the body** for everything below, never the
   assembly (Part 5).
2. **File → Save As** `/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/Nozzle_A.FCStd`, **File → Close**, and reopen:
   ```
   open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/Nozzle_A.FCStd"
   ```
   The tree now starts with **Nozzle_A**, so the case goes to `cfdof_cases/Nozzle_A/case` (Part 5, step 3).
3. Workbench **Part**, click the body, **Part → Check Geometry**: no errors, **1 solid, 12 faces** (Shape Content).
4. **Find the faces.** Hover over a face: the status bar at the bottom shows its name (FaceN) and the point under the
   cursor. Fusion numbers the faces its own way, so **your numbers will differ from the check's**: identify each by
   where it is. Write your numbers into the last column; the boundaries and the mesh need them.

   | What | Where (mm) | Area | Your FaceN |
   |---|---|---|---|
   | **inlet**: the left end of the feed | x = −25.5, y 0–2 | 2.0 mm² | |
   | feed pipe wall | y = 2, x −25.5 to −5.5 | 20.0 mm² | |
   | contraction (sloping) | x −5.5 to −3 | 2.89 mm² | |
   | bore wall | y = 0.555, x −3 to 0 | 3.0 mm² | |
   | front face of the nozzle | x = 0, y 0.555–4 | 3.45 mm² | |
   | body's outside | y = 4, x −11.1 to 0 | 11.1 mm² | |
   | **back face** of the air | x = −11.1, y 4–27.75 | 23.75 mm² | |
   | **side** of the air (top) | y = 27.75 | 122.1 mm² | |
   | **outlet**: the right end | x = 111 | 27.75 mm² | |
   | **axis** strip (bottom) | y = 0 | 136.5 mm² | |
   | **the flat face at z = 0** (the sketch's side) | z = 0 | 3,389 mm² | |
   | the flat face at z = 1 | z = 1 | 3,389 mm² | |

   The strips are each 1 mm wide (the pad). The two big flat faces look alike: the one you want is at **z = 0**,
   the sketch plane (hover and read z in the status bar).

## 9.4 Physics, fluid, boundaries (10 min)

Workbench **CfdOF**.
1. **Analysis container.**
2. **PhysicsModel:** **Steady**, **Isothermal**, **Single phase**, **Viscous** ticked, **RANS**, **kOmegaSST**.
3. **FluidProperties:** **Air**.
4. **Boundaries.** One **Fluid boundary** each (double-click **CfdAnalysis** first if the button is greyed out). Faces
   by **Select from list**: click the body, open **▼ Select components**, tick the face, click its name to check it
   lights up. **OK**, then rename it (F2) exactly as below.
   - **inlet:** **Inlet**, **Uniform velocity**. Velocity: **Cartesian components (X,Y,Z)**: **11.348 m/s, 0, 0**.
     Turbulence specification **Intensity & Length Scale**: **5 %**, **0.28 mm**. Face: the inlet strip.
   - **outlet:** **Outlet**, **Static pressure**, **0 Pa**. Face: the outlet strip.
   - **open:** **Open**, **Ambient pressure**, **0 Pa**. Faces: the **back face** and the **side** strips (both).
   - **axis:** **Constraint**, **Symmetry**. Face: the axis strip.
   - **walls:** **Wall**, **No-slip (viscous)**, tick **Use as default boundary condition for unselected faces**.
     Faces: the five nozzle strips (feed pipe wall, contraction, bore wall, front face, body's outside).
5. **InitialiseFields:** Velocity **Potential flow**; Pressure **Use value from boundary → outlet**; untick "Use values
   from boundary" for turbulence: k **0.0001 m^2/s^2**, ω **1 1/s** (as Part 3).

**Why:**
- **11.348 m/s along +x** is the Chamber_v2 gas, 1.426e-4 m³/s, over the Ø4 feed (9.0 says why not a flow rate).
- **5 %, 0.28 mm:** pipe-flow turbulence, and 0.07 × the 4 mm feed (as the spray's, Part 7.5).
- **The walls name their faces and are also the default.** The default catches the z = 1 face, which the sweep throws
  away anyway; naming the nozzle's faces matches the checked case exactly.
- **Rename them exactly:** the solver's patches take these names, and 9.8's gas check asks for inlet, outlet and open.

## 9.5 The mesh (10 min clicking, ~10 s meshing)

**How it is laid out (read first):**
- **Base element size 0.25 mm,** for the far air. It is also what sets the block's 1 mm (four of these, 9.2 step 6).
- **cfMesh halves the base size in steps:** 0.125, 0.0625, 0.03125 mm. The relative size you type is rounded **down**
  to the next step, so 0.15 gives 0.03125 mm and 0.3 gives 0.0625 mm (both safely inside their step, as Part 7.6).
- **Two boxes of small cells** do the work:

  | Box | Covers | Cells | Why |
  |---|---|---|---|
  | **BoreBox** | the bore, the lip, and the jet's first 3 mm (2.7 D) | 0.03125 mm | 18 across the 0.555 mm exit radius: the bore's velocity profile and the thin shear layer off the lip, where the jet starts mixing. |
  | **NearBox** | the contraction to 12 mm out (10.8 D) | 0.0625 mm | the potential core (to ~7 D) and the jet's first growth, ~15 cells across its half-width. |

  Beyond 12 mm, 0.25 mm cells still give ~15 across the jet's half-width at 30 D (3.7 mm).
- **No layers on the walls:** the bore's friction is a small part of the jet's push (Part 7.6 found ~1.4 % in the
  chamber's bore). Layers come later, if a design depends on wall friction.

**Steps:**
1. Click the **body**, then **CFD mesh**: Mesh utility **cfMesh**, Base element size **0.25 mm**. **OK.**
2. **The two boxes.** Workbench **Part**, **Part → Primitives → Cube**, twice. Rename (F2) and set the Data tab:
   - **BoreBox:** **Length 6.5 mm, Width 1.7 mm, Height 2 mm**; Placement Position **x −3.5, y −0.5, z −0.5**.
   - **NearBox:** **Length 18 mm, Width 3.5 mm, Height 2 mm**; Position **x −6, y −0.5, z −0.5**.

   They stick out below the axis and through both sides of the pad on purpose: only the part inside the air
   counts, and overlapping the edges makes sure nothing at the axis or the faces is missed.
3. Workbench **CfdOF**. For each box: mesh object selected, **Mesh refinement**, **Volume refinement**, relative
   element size **0.15** (BoreBox) or **0.3** (NearBox), **Select from list**, tick the box itself. Rename them
   **BoreBoxRefinement** and **NearBoxRefinement**. Hide both boxes (Space).
4. **The wedge.** Mesh object selected, **Mesh refinement**. At the top choose **Extrusion**. Then:
   - **Extrusion type: 2D wedge mesh**;
   - **Angle 5°**;
   - **Axis point (X,Y,Z): 0, 0, 0**; **Axis direction (X,Y,Z): 1, 0, 0** (the X axis: your nozzle's axis);
   - ignore Thickness, Number of layers and Expansion ratio (they're for the other extrusion types);
   - Reference: **Select from list**, tick **the flat face at z = 0** (your number from 9.3).

   **OK**, then rename it **Wedge**: exactly that, capital W. CfdOF names the cut-face patch after it, and 9.7
   looks for a patch called **Wedge**.
5. **Mesh it:** double-click the mesh object, **Write mesh case**, **Run mesher**. About 10 s.
6. **Check Mesh:** **70,837 cells**, "**Mesh OK**". It also lists 69,596 hexahedra and **959 prisms**: the prisms are
   the cells on the axis that the sweep collapsed, as it should. At this stage it says "Mesh has 3 geometric
   directions": 9.7 changes that.
7. **Look at it:** the mesh panel's **ParaView**. **Apply**, show it as **Surface With Edges**, and look along Z
   (the **−Z** view button). It is the half-section you drew. Zoom in on the nozzle: 0.25 mm cells far out, the
   0.0625 mm NearBox band, and the 0.03125 mm BoreBox around the bore and lip.

## 9.6 Solve it as CfdOF writes it, and see the problem (~4 min)

1. **CfdSolver**, Data tab: **Max Iterations 1500**, **Steady Write Interval 1500**.
2. Double-click it: **untick Solve in Parallel**. At 71,000 cells one core is quick, and 9.7–9.8 are easier on a
   case that isn't split across cores.
3. **Write**, then **Run**. About 3.5 min. The Uz residual stays near 0.03 and never falls, so it runs all 1,500.
   That is the first sign that something is off: there should be no flow out of the slice's plane to solve for.
4. Press **ParaView** (Results). **Apply**, **Last Frame**, colour by **U** (Magnitude), look along Z (**−Z**).
   Rescale the colours to **0–170**. The jet leaves the bore at 160 m/s and then **hollows out**: within a few mm the
   fast gas is in a ring off the axis, and the axis itself has stopped. A real jet keeps its fast core for ~6 D and
   stays fastest on the axis.
5. **Keep this run for comparison,** then clear its result out of the case. Close ParaView first:
   ```
   cp -R /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/case /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/case_symmetry
   rm -rf /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/case/1500
   ```
   The `rm` deletes only the 1500 folder inside `case` (this run's result), which is now kept in `case_symmetry`.

**Why run it at all:** CfdOF's **Run** prepares the case (copies the mesh in, names the patches, sets up the
turbulence library, starts the flow from a potential-flow guess) before solving. 9.7 builds on that prepared case.
And you've now seen what the wrong boundary does, which is worth more than being told.

## 9.7 Make the cut faces true wedges (5 min, in Terminal)

All in Terminal, in the case folder. Each step says what it does; paste them one at a time and read the output.

**1. OpenFOAM's commands, and the case folder:**
```
source /Applications/OpenFOAM-v2606.app/Contents/Resources/etc/bashrc
cd /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/case
```

**2. Copy in the two instruction files.** They live in the repo, next to this guide:
```
cp "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof/wedge/topoSetDict" "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/cfdof/wedge/createPatchDict.wedge" system/
```
- **topoSetDict** sorts the faces of the **Wedge** patch into two sets: **frontSet**, the faces pointing +z, and
  **backSet**, those pointing −z. The slice runs from −2.5° to +2.5° about z = 0, so each cut face points almost
  exactly one way.
- **createPatchDict.wedge** makes each set its own patch, **WedgeFront** and **WedgeBack**, of type **wedge**.
  Wedge is then empty, so OpenFOAM removes it.
- Open them in TextEdit if you want to read them (`open -e system/topoSetDict`): each line is commented.

**3. Sort the faces, then make the new patches:**
```
topoSet
createPatch -dict system/createPatchDict.wedge -overwrite
```
topoSet should end with **"faceSet frontSet now size 70837"** and **"faceSet backSet now size 70837"**: the
70,837 cells' front and back faces, half each. (`-overwrite` writes the mesh in place instead of to a new time
folder.) createPatch prints a warning about "allowSystemOperations": harmless, it says that on every run.

**4. Check OpenFOAM now sees it as round:**
```
checkMesh | grep -E "geometric|Mesh OK"
```
It should say **"Mesh has 2 geometric (non-empty/wedge) directions (1 1 0)"** and **"Mesh OK."** Before, it said
3. Two means it treats the slice as round: it stops solving for flow across the slice (Uz), and it handles the
angle between the two cut faces properly.

**5. Tell the flow fields about the new patches.** Each field file in `0/` (U, p, k, ω, ν_t) has an entry per patch.
This removes each one's **Wedge** entry and adds **WedgeFront** and **WedgeBack** as type **wedge**:
```
for f in U p k omega nut; do foamDictionary 0/$f -entry boundaryField.Wedge -remove; foamDictionary 0/$f -entry boundaryField.WedgeFront -add "{ type wedge; }"; foamDictionary 0/$f -entry boundaryField.WedgeBack -add "{ type wedge; }"; done
```
It prints the entries it adds. Without this step the solver stops with **"Cannot find patchField entry for
WedgeFront"**.

**Don't press Write or Run in CfdOF for this case from now on.** Write clears the case folder and writes CfdOF's
version again; Run copies CfdOF's mesh back in. Either undoes this part. If it happens, do 9.6 (Run, then you can
Stop it as soon as the residual plot starts) and 9.7 again.

## 9.8 Solve the wedge (~3 min) and check the gas

**1. Start from a potential-flow guess, then solve,** in the same Terminal:
```
potentialFoam -initialiseUBCs -pName p
simpleFoam | tee log.simpleFoam
```
The iterations scroll past (`tee` also saves them to `log.simpleFoam`). After about 2.5 min it ends with
**"SIMPLE solution converged in 1429 iterations"** and **"End"**: the residuals all fell below CfdOF's 1e-3 stop
(its default), which the symmetry run never managed. The result is in the folder **1429**.

**2. Gas in = gas out** (in the same Terminal):
```
for p in inlet outlet open; do postProcess -func "flowRatePatch(name=$p)" -latestTime 2>&1 | grep "of phi"; done
```
Expect (in negative, out positive, m³/s):
- inlet **−1.973e-06**: the 5° slice's share. × 72 (360/5) = 1.42e-4, the full 1.426e-4 within 0.4 % (the inlet
  strip's edge is faceted);
- outlet **+7.06e-05**: many times the jet's own gas, because it carries the air the jet has dragged in;
- open **−6.87e-05**: that dragged-in air, coming in through the side and back faces.

They add up to zero.

**3. The pressure it takes to push the gas through** (useful when comparing designs, 9.12):
```
postProcess -fields '(p)' -func "patchAverage(name=inlet,fields=(p))" -latestTime 2>&1 | grep "areaAverage(inlet)"
```
Expect **≈ 13,185**. simpleFoam's pressure is divided by the density, so × 1.20 kg/m³ = **15.8 kPa** above the room
(0.16 bar) at the inlet: ~1.2 × the jet's dynamic pressure (13 kPa), the extra being the contraction and the bore.

## 9.9 Compare the two in ParaView (10 min)

1. Open the wedge case:
   ```
   open -n -a /Applications/ParaView-6.2.0.app --args --data="/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/case/pv.foam"
   ```
   **Apply**, **Last Frame**. Rename it **wedge** (F2 in the Pipeline Browser).
2. **File → Open**, `/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/case_symmetry/pv.foam`, **Apply**, **Last
   Frame**. Rename it **symmetry**.
3. **The picture.** For each: colour **U** (Magnitude), range **0–170**, view along Z (**−Z**). For the whole jet,
   not just its top half: select it, **Filters → Alphabetical → Reflect**, Plane **Y Min**, **Apply** (it mirrors the
   slice about the axis). Use the **split view** button to put the two side by side, and link the cameras (right-click
   in a view → **Link Camera…**, click the other).
   - **wedge:** a solid core for ~7 mm, then a jet that widens steadily and fades.
   - **symmetry:** a core that dies within 5 mm and a ring of fast gas peeling off the axis.
4. **Along the axis.** Select **wedge**, **Filters → Data Analysis → Plot Over Line**: Point1 **(−0.003, 0.00001, 0)**,
   Point2 **(0.111, 0.00001, 0)**, **Apply**. In the line chart, show only **U_X**. Do the same on **symmetry**. (The
   line sits 0.01 mm above the axis, inside the cells, rather than on the collapsed edge.)
5. **Exact values:** **Filters → Data Analysis → Probe Location** on **wedge**, at the points below; read U_X in the
   spreadsheet view. Change the point and **Apply** for each.

   | Distance from the exit | Point (m) | wedge (checked) | symmetry (checked) | textbook round jet |
   |---|---|---|---|---|
   | 0 (the lip) | (0, 0.00001, 0) | 162 m/s | 161 | 147 mean, ~160 centre |
   | 4 D, 4.4 mm | (0.00444, 0.00001, 0) | 162 | 29 | ~150 (in the core) |
   | 10 D, 11.1 mm | (0.0111, 0.00001, 0) | 100 | 0 | 88 |
   | 30 D, 33.3 mm | (0.0333, 0.00001, 0) | 27 | 0 | 29 |
   | 50 D, 55.5 mm | (0.0555, 0.00001, 0) | 15.5 | 0 | 17.7 |
   | 99 D, 110 mm | (0.1099, 0.00001, 0) | 7.7 | 0 | 8.9 |

   ParaView's numbers can differ from these by a few % (it interpolates differently); the pattern is what to check.
6. **How wide, at 30 D.** **Plot Over Line** on **wedge** from **(0.0333, 0.00001, 0)** to **(0.0333, 0.0277, 0)**.
   U_X starts at 27 m/s on the axis; it falls to half (13.5 m/s) at **r ≈ 3.7 mm (3.3 D)**. On **symmetry**, the
   same line starts at 0 and peaks at 7 m/s, 4.4 mm out: the hollow ring.

**What it says:**
- **The wedge case is a round jet.** Its centre slows as **4.96 × D ÷ (x − 2.8 D)** from 15 to 60 D, against the
  textbook's ~6 × D ÷ x, and it widens as 0.11 × distance against 0.094.
- **It spreads ~20 % too fast:** k-ω SST's known fault with round jets, the same as your chamber's jet (Part 7.9).
  Fine for comparing designs, which all share it; not for absolute numbers.
- **The symmetry case is not a jet at all,** which is why 9.7 is not optional.

**Save the view:** **File → Save State…** as `/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A/nozzle_a_view.pvsm`.

## 9.10 Check 1: the mesh (halve every cell) (5 min clicking, ~20 min meshing and solving)

**The question:** are the cells small enough? Halve every cell; if the jet barely changes, they were.

1. In FreeCAD, with Nozzle_A open: **File → Save As**
   `/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A_fine/Nozzle_A_fine.FCStd`, **File → Close**, and reopen:
   ```
   open -a FreeCAD "/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A_fine/Nozzle_A_fine.FCStd"
   ```
2. **CfdSolver**, Data tab: **Max Iterations 3000**, **Steady Write Interval 3000**. The finer mesh needs ~2,180
   iterations to converge, more than the 1,500 the file came with.
3. Double-click the mesh object: **Base element size 0.125 mm**. Change nothing else in the mesh. The relative
   sizes follow, so every cell halves: 0.125 / 0.03125 / 0.015625 mm. The 1 mm block is now 8 cells thick, still fine.
4. **Write mesh case**, **Run mesher**: about **90 s** (cfMesh's throwaway 3D mesh is 8× bigger; it peaks at
   ~3.8 GB of memory). **Check Mesh:** **277,764 cells**, Mesh OK.
5. **CfdSolver:** **Write**, **Run**, and as soon as the residual plot starts moving, **Stop**. That is enough: Run's
   preparation is done (9.6, "Why run it at all"), and nothing is written until the end, so there's nothing to clear.
6. **9.7 in this case.** Steps 2–5 exactly as written; only step 1's folder changes:
   ```
   source /Applications/OpenFOAM-v2606.app/Contents/Resources/etc/bashrc
   cd /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A_fine/case
   ```
   topoSet now reports **277764** for each set.
7. **9.8:** potentialFoam, simpleFoam, the gas check. About **17 min**: it converges at about **2,180** iterations
   (4× the cells need more iterations, and each is slower). The result is in that iteration's folder.
8. **Compare** with Nozzle_A: open `Nozzle_A_fine/case/pv.foam` next to the wedge case in ParaView and probe the same
   points (9.9 steps 5–6), out to 50 D.

**What the check gave** (9.13): the jet within 1–4 % out to 50 D, so the 0.25 mm mesh is fine enough for comparing
designs. Past ~70 D the fine mesh misbehaves near the outlet (9.13 says how): don't read it there.

## 9.11 Check 2: the domain (1.5× bigger) (20 min clicking, ~6 min solving)

**The question:** is the domain big enough that its edges don't shape the jet? Make it 1.5× bigger; if the jet
barely changes, it was.

1. **In Fusion:** **Change Parameters**, **Dom = 1.5**. The air grows to 15 D behind, 37.5 D out and 150 D
   downstream; the nozzle and feed stay the same. **File → Export…** STEP as
   `/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A_big/Nozzle_A_big.step`. Set **Dom back to 1** afterwards.
2. **In FreeCAD, a new document from it:** 9.3 (open the STEP; **Save As**
   `/Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A_big/Nozzle_A_big.FCStd`; close; reopen), then 9.4 and 9.5 again.
   It's the same clicks, with the faces picked anew (a new STEP numbers them afresh). The nozzle's faces are as in
   9.3's table; these change:

   | What | Where (mm) | Area |
   |---|---|---|
   | back face | x = −16.65, y 4–41.6 | 37.6 mm² |
   | side (top) | y = 41.625 | 183.2 mm² |
   | outlet | x = 166.5 | 41.6 mm² |
   | axis strip | y = 0 | 192.0 mm² |
   | flat face at z = 0 | z = 0 | 7,602 mm² |

   The boxes stay where they are (they're about the nozzle, not the domain). Mesh: about **35 s**, **139,114 cells**,
   Mesh OK.
3. **CfdSolver:** **Max Iterations 1500**, **Steady Write Interval 1500**, **Solve in Parallel** unticked; **Write**,
   **Run**, **Stop** once the residuals move (as 9.10 step 5).
4. **9.7** with:
   ```
   source /Applications/OpenFOAM-v2606.app/Contents/Resources/etc/bashrc
   cd /Users/benschofield/OpenFOAM/cfdof_cases/Nozzle_A_big/case
   ```
   then **9.8** (about **6 min**). topoSet reports **139114** for each set. It runs all 1,500 iterations without
   the "converged" message: fine, its jet matches Nozzle_A to 0.4 % (9.13).
5. **Compare** with Nozzle_A at the same points (9.9 steps 5–6). The gas balance's outlet and open numbers will be
   bigger (a longer jet drags in more air); the inlet stays −1.973e-06.

**What the check gave** (9.13): the jet within 0.4 % everywhere to 99 D, so the 10 / 25 / 100 D domain is big
enough.

## 9.12 Your own nozzle designs

**In Fusion:** keep the domain parameters and the outline's air part; change the nozzle.
- **The simple way:** change the nozzle parameters (D, Dfeed, Lcon, Lbore, Dbody) or move corners P2–P6 in a copy of
  the sketch.
- **From your real nozzle's CAD:** bring the nozzle body into the design with its axis on X and its exit on the Y
  axis, make a sketch on XY, and use **Sketch → Project / Include → Intersect** on the body. That gives the body's
  exact cross-section on the sketch plane. Trace the outline over it (inside passage + outside surfaces), keep only
  the half above the axis, and close it with the same air lines (back face, side, outlet, axis).
- **Name each design** (Nozzle_B, Nozzle_C, …): its own folder, STEP and FreeCAD file, as 9.1–9.3.

**In FreeCAD, things that change with the design:**
- **The inlet velocity,** if the feed diameter changes: 1.426e-4 ÷ (π × (Dfeed/2)²), in m and m/s. Ø4 mm gives
  11.348 m/s; Ø3 mm would give 20.17 m/s. The length scale stays 0.07 × Dfeed.
- **The boxes,** if the bore is longer or the exit smaller. BoreBox must cover the bore and the lip; NearBox the
  contraction to ~10 D out. For a smaller exit, keep ~18 cells across its radius: halve BoreBox's relative size for
  half the exit.
- **The speed:** at the same flow, the exit speed goes as 1/D². Above ~150 m/s (Mach 0.45), switch **Physics →
  Non-isothermal** and check the run: incompressible stops being a fair approximation.

**What to compare between designs** (all at the same gas flow):

| | How | What it tells you |
|---|---|---|
| Core length | where U_X on the axis drops below 95 % of the lip's | how far the jet stays undisturbed |
| Centre speed at 10 and 30 D | Probe Location (9.9 step 5) | how fast it slows |
| Width at 30 D | Plot Over Line across, where U_X is half the axis's (9.9 step 6) | how fast it spreads |
| Supply pressure | patchAverage on the inlet × 1.2 (9.8 step 3) | what it costs to push the gas through |

Compare inside **50 D** (9.13: the far end isn't reliable on finer meshes), and treat differences under ~4 % as
within the mesh's error. Run the mesh check on a design whose features are much smaller than Nozzle_A's (a sharper
lip, a thinner gap).

(How much room air the jet drags in would be worth comparing too, but the outlet's flow isn't a fair measure of it:
it moved 25 % with the mesh. Measuring it properly, as the jet's own flow across a plane at 30 D, is a later step.)

## 9.13 What the check by script gave

All on scratch copies, with the same objects and settings as 9.2–9.11 (FreeCAD drew the outline instead of Fusion,
so the face numbers there were 1–12 in outline order).

| | Nozzle_A | Nozzle_A_fine (check 1) | Nozzle_A_big (check 2) |
|---|---|---|---|
| Cells | **70,837** (959 prisms on the axis) | **277,764** | **139,114** |
| Meshing | 9 s | 86 s, 3.8 GB peak | 33 s |
| checkMesh, before / after 9.7 | Mesh OK, 3 / **2** geometric directions | the same | the same |
| Solve (one core) | converged at **1,429** iterations, 2.5 min | converged at **2,176**, 17 min | 1,500 without the converged message, 6 min |
| Gas: inlet / outlet / open (m³/s) | −1.973e-6 / +7.06e-5 / −6.87e-5 | −1.974e-6 / +5.64e-5 / −5.44e-5 | −1.973e-6 / +8.82e-5 / −8.62e-5 |
| Centre speed at 0 / 4 / 10 / 30 / 50 / 99 D (m/s) | 162 / 162 / 99.7 / 26.9 / 15.5 / 7.7 | 164 / 164.5 / 103.3 / 27.4 / 15.9 / **16.4** | 162 / 162 / 99.7 / 26.9 / 15.5 / 7.7 |
| Half-speed radius at 10 / 30 / 60 D | 0.92 / 3.33 / 7.00 D | 0.88 / 3.29 / 6.79 D | 0.92 / 3.33 / 7.00 D |
| Centre speed fit, 15–60 D | U0 × 4.96 D ÷ (x − 2.8 D) | U0 × 5.14 D ÷ (x − 2.3 D) | U0 × 4.97 D ÷ (x − 2.7 D) |
| Inlet pressure (simpleFoam's p) | 13,185 (15.8 kPa) | 13,530 (16.2 kPa) | 13,188 (15.8 kPa) |

**As CfdOF writes it** (symmetry cut faces, the same mesh): 1,500 iterations without converging (Uz stalls near
0.03), 3.5 min; centre speed 161 / 92 / 29 / 7 / 0 at 0 / 2 / 4 / 6 / 10 D; peak 34 m/s at 1.2 D off the axis at
10 D; gas inlet / outlet / open −1.973e-6 / +4.66e-5 / −4.46e-5.

**Nozzle_A run on to 3,000 iterations** (a copy, the convergence stop turned off): the same jet to 0.1 m/s
everywhere, so 1,429 is converged. Only the outlet's flow crept up (7.06e-5 → 7.32e-5), as the slow air far from the
jet keeps adjusting.

**What the checks say:**
- **The domain is big enough.** 1.5× bigger changes nothing on the jet: at most 0.4 % anywhere to 99 D, with the
  same widths and the same inlet pressure. Only the gas check's outlet and open flows grow, because a longer domain
  lets the jet drag in more air before it leaves.
- **The mesh is fine enough for comparing designs, though not exact.** Halving every cell:
  - raises the centre speed by 1.3 % at the lip, 3.6 % at 10 D and 2–3 % from 20 to 50 D;
  - narrows the jet by 1–4 %;
  - raises the inlet pressure by 2.6 %.

  Much of it starts in the bore, where the finer cells give a slightly more peaked exit profile. A difference between
  two designs smaller than ~4 % is inside this; bigger ones are real.
- **Past ~70 D the fine mesh goes wrong.** Its jet speeds up again and narrows towards the outlet (16.4 m/s at 99 D
  against 7.7), with the air near the outlet converging onto the axis. The 0.25 mm mesh and the big domain don't do
  this. So **compare designs inside 50 D**. Don't use the outlet's flow as a measure of how much air the jet drags
  in: it moved 25 % with the mesh.

## The faces of Nozzle_A (from the check; yours will be numbered differently)

| Check's FaceN | What | Area | Centre (mm) | Goes to |
|---|---|---|---|---|
| Face1 | inlet strip | 2.0 mm² | (−25.5, 1.0, 0.5) | **inlet** |
| Face2 | feed pipe wall | 20.0 mm² | (−15.5, 2.0, 0.5) | walls |
| Face3 | contraction | 2.89 mm² | (−4.25, 1.28, 0.5) | walls |
| Face4 | bore wall | 3.0 mm² | (−1.5, 0.555, 0.5) | walls |
| Face5 | nozzle front face | 3.45 mm² | (0, 2.28, 0.5) | walls |
| Face6 | body's outside | 11.1 mm² | (−5.55, 4.0, 0.5) | walls |
| Face7 | back face of the air | 23.75 mm² | (−11.1, 15.9, 0.5) | **open** |
| Face8 | side of the air (top) | 122.1 mm² | (49.95, 27.75, 0.5) | **open** |
| Face9 | outlet strip | 27.75 mm² | (111, 13.9, 0.5) | **outlet** |
| Face10 | axis strip | 136.5 mm² | (42.75, 0, 0.5) | **axis** |
| Face11 | flat face at z = 0 | 3,389 mm² | (42.75, 13.9, 0) | **Wedge** (the extrusion) |
| Face12 | flat face at z = 1 | 3,389 mm² | (42.75, 13.9, 1) | nothing (the walls default; the sweep drops it) |

## If you get stuck

- **topoSet stops with an error about patch Wedge, or its sets come out size 0:** the wedge refinement isn't named
  exactly **Wedge** (9.5 step 4). Rename it, then **Write mesh case**, **Run mesher**, and 9.6 onwards again.
- **potentialFoam or simpleFoam: "Cannot find patchField entry for WedgeFront":** 9.7 step 5 was skipped or ran in
  another folder.
- **checkMesh still says 3 geometric directions:** 9.7 step 3 didn't run in this case, or CfdOF's Write or Run was
  pressed afterwards. Redo 9.7.
- **The inlet or outlet has no faces** (the solver crashes at once, "Illegal instruction: 4", as Part 3): the block
  is thinner than 4 of the biggest cells. Check the pad is 1 mm and the base size 0.25 mm.
- **The jet is hollow:** you're looking at the symmetry run (`case_symmetry`), or 9.7 was undone.
- **postProcess on the pressure stops with "Bad token - could not get scalar value"** and the file has numbers like
  `4.94065645841247e-324`: on longer runs the outlet's pressure gets values too small for OpenFOAM to read back
  (seen on the fine mesh). They are zero in all but name. ParaView reads them fine, and the gas check (it reads the
  flux, not p) is unaffected. To run the pressure check anyway, zero them in the last result's p, e.g. for 2176:
  ```
  sed -i '' -E 's/[0-9.]+e-3[0-9][0-9]/0/g' 2176/p
  ```
  (It replaces only numbers smaller than 1e-299, in that one file; checked on the fine mesh's result.)
- **Gas in ≠ gas out by more than ~1 %:** not converged; check the end of `log.simpleFoam` says "SIMPLE solution
  converged".
