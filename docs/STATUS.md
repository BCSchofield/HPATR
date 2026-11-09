# STATUS — real-data droplet pipeline and Taguchi study

**Last updated: 2026-11-08 (Mac: nozzle CFD, at Ben's request: an example 2D wedge domain for a round nozzle (artifact) and a headless rehearsal on a dummy nozzle. The block must be ≥ 4 coarsest cells thick; the face may touch the axis; CfdOF's 2D wedge writes the cut faces as `symmetry`, which makes the jet go hollow, and converting them to OpenFOAM `wedge` patches gives a proper round jet (decay 4.96/(x/D − 2.8), half-width 0.11 x). Details CFD_LOG.md section 9. Then guide Part 9 written as its own file, `Flow Visualisation/cfdof/NOZZLE_WEDGE_GUIDE.md`, click-through (Ben: no script), with the mesh and domain checks, all rehearsed. Earlier 2026-11-04 (Mac: the PS20 reticle has ARRIVED (Ben); its plan is `docs/BEAD_CALIBRATION.md` 'Later: the reticle' and the sizer 3.0.0 plan's 'When the reticle arrives'; before its session: certificate values, the small dots and squares in `bead_calibration.py`, a run sheet. Session TABLED to the week of 2026-11-09 (Ben); the larger beads through focus stay dropped (the reticle's dots replace them). Earlier 2026-11-02 14:35 (Mac: Flow Visualisation, at Ben's request: CFDOF_GUIDE.md PART 8 WRITTEN (Phase 7 step 3), for Ben to click. NEW REQUIREMENT (Ben): the capture feeds an AJP, so the carrier is PUSHED in (the AJP head needs pressure behind it; no pump before it); the 44 mm port sealed, the capture the only exit. Push vs pull is the same incompressible solve, so the first pair is jet vs no jet at 30 L/min: STREAM (10 mm inlet on the x = 270 wall, 6.4 m/s, 3.8 mN) vs GENTLE (40 mm, 0.4 m/s), capture 10 mm on the x = 80 wall at (80, 80, -212.5), in the spray's plane 67 mm above the floor. Plain cylinders added to Ben's existing Fusion (FreeCAD 1.1 renumbers his CfdOF links itself, checked by script); a 0.5/1/2 mm cone ladder along the stream. Checked headless on a scratch copy: Mesh OK, 1.52/1.56 M cells, 30 iterations clean, gas in = out; full solve not run (Mac on battery). Droplets: `Flow Visualisation/settings/droplets_carrier_stream.yaml` (Chamber_v2 vs Stream vs Gentle; flow kept 2 s and 120 s). Open for the AJP: the head's carrier flow (the capture line will need a split) and the droplet size it takes. Lesson: two cfMesh runs at once stalled at the layers stage. Recorded in PLAN Phase 7 and CFD_LOG section 8. Earlier 12:45: (1) NEW CASE FOLDER `~/OpenFOAM/cfdof_cases/Chamber_v2_kEpsilon/` made for the second-turbulence-model run: `Chamber_v2_kEpsilon.FCStd` (a copy of Chamber_v2.FCStd), meshCase (no re-mesh needed) and the STEP; CfdOF writes each case to DefaultOutputPath + the document name (AppendDocNameToOutputPath on), and headless FreeCAD confirms the copy opens as Chamber_v2_kEpsilon and writes there, never into Chamber_v2 (untouched); its turbulence model is STILL kOmegaSST, left for Ben to click to kEpsilon. CfdOF does NOT offer realizable k-epsilon (its dropdown: kOmegaSST, kEpsilon, SpalartAllmaras, DES/LES variants): PLAN and CFD_LOG corrected to kEpsilon, expected to spread the round jet MORE, so the two models bracket the error. (2) GUIDE 7.10 DONE (`~/OpenFOAM/droplet_runs/droplets_chamber_v2/2026-11-02_121431/`, ~9 min): Phase 7 step 1, the capture BASELINE. Tracers on the floor 0 % (Part 6: 24-62 %): the floor artefact is gone on this mesh (7.3 % of tracers on walls with gusts on: the unlayered atomiser + isotropic gusts; the report's check-4 'FLAG' wording is stale). The 0-30 um band (weighted, by number, gusts on, flow kept 2 s): ONLY 1.2 % LEAVES THROUGH THE 44 mm PORT (2.5 % gusts off), ~90 % on the floor, 48 % AIRBORNE AT SWITCH-OFF (15 % gusts off) and SPREAD THROUGH THE WHOLE CHAMBER, so the extraction flow should matter more than the port position (supports the well-mixed estimate); > 30 um land within ~15 mm of the jet's impact, 0-20 um evenly over the floor (half-spread 83-89 mm), so slides > ~50 mm from the impact collect almost only the band; gusts on vs off (48 vs 15 % airborne) is now the widest error bar for the fines. Recorded in CFD_LOG section 7 and PLAN Phase 7 step 1. Figures and the ParaView animation opened for Ben. Earlier 2026-10-30 16:05: PLAN.md Phase 7 updated with Ben's new answers (2026-10-30): the HEPA/carbon CAN be disconnected for a test and the 44 mm port then sits open to the room AND he can cover it, so BOTH routes are open (leave open for suction, cover for blow-in); **the chamber walls are 5 mm POLYCARBONATE**. Answered 'do I need a rotameter for the compressed air?': NO for the compressed air -- discharge the line into a bag/sack of known volume and time the fill (60 L in 36 s = 100 L/min, good to ~20 %, enough to answer 'over 150 L/min or not'); and if the BLOWER route is taken the number may not be needed at all. DO NOT use the chamber as the known volume (5 mm polycarbonate, never pressurise). BUT a flowmeter IS needed for the EXTRACTION, which is the real reason to buy one (the CFD runs at a stated flow). RS: this class is usually well under GBP 100 but **Claude cannot check RS's live catalogue or prices**, so the plan gives a SPEC TABLE to match instead of a part number: 0-150 L/min air (puts 100 at ~2/3 scale and 30 at ~20 %; 0-100 would put 100 at full scale and read badly), calibrated for AIR AT ATMOSPHERIC DISCHARGE (a rotameter only reads true at its calibration pressure -- do NOT fit it in the 5 bar line and read it there), note L/min vs sL/min, hose or 1/4-1/2 BSP connections; under suction the ~500 Pa density error is ~0.5 %, negligible; a thermal mass flow meter would read 30 and 100 both well but likely exceeds GBP 100; CHECK FIRST whether a larger Alicat already exists in the lab (the one in use stops at 12 L/min). New section **'Working in 5 mm polycarbonate'**: ports are easy (step drill or hole saw at low speed, backed with scrap; polycarbonate does not craze like acrylic), but NO acetone/MEK/acrylic solvent cement and cyanoacrylate can craze it -- use a mechanical bulkhead with gaskets or neutral-cure silicone; negative pressure is a non-issue (800 Pa on a 190x692 panel is ~105 N, it just flexes) but if blow-in is used with the port covered LEAVE A DELIBERATE RELIEF PATH so a blocked collector cannot pressurise it; mask the z-walls when drilling (they are the shadowgraph windows) and cut ports only in the x-walls. **NEW LOSS MECHANISM NOT IN THE CFD: STATIC** -- insulating plastic walls hold charge and atomised droplets are often charged, so the CFD (inertia, gravity, drag only) will UNDER-predict wall losses if charging matters; mitigate with earthed metal/conductive extraction tubing (standard aerosol-sampling practice) and an antistatic wipe; it is a hypothesis, and the cheap test is Phase 4's on/off comparison (measured capture consistently below predicted = charge is the prime suspect). Also added to the shopping list: a filter on the 44 mm make-up port (so what lands on the slide came from the spray, not the room), conductive extraction tubing, and a step drill / hole saw. Earlier 2026-10-30 15:35: PLAN.md Phase 7 gained a **shopping and look-into list** (Ben asked). Sequenced so A and B unlock the rest and D waits for A. A, free: run guide 7.10 (decides where the port goes); is there already a shop vac in the lab; how the HEPA/carbon attaches to the 44 mm port and can it be disconnected; what the chamber walls are and how thick; measure the compressed air. B, buy first: a 0-150 L/min air ROTAMETER (~GBP 30-60) -- it measures the supply, sets the extraction AND makes the CFD comparison meaningful (the Alicats stop at 12 L/min). C, first slide test: a 20-25 mm bulkhead port + gasket, a needle/ball throttle valve, a SHORT STRAIGHT tube with NO BEND between chamber and slide (bends lose the droplets), plain 25x75 slides, a blank for the 44 mm port if blow-in is tried. D, only after A: an air amplifier/mover if the compressed air exceeds ~150 L/min free delivery, else a radial blower (~GBP 20-40) or diaphragm pump; plus a filter + housing between collector and pump, exhausting into the existing HEPA/carbon. E, make: the impactor body (10 mm nozzle facing a slide ~10 mm away, printable, holds no pressure); the ejector body only if that route is taken, in resin with a bought blunt needle/brass tube as the 1-1.5 mm nozzle. F, look into: **does the extraction disturb the shadowgraph** (30-100 L/min past the imaging region could move the spray in the measurement window -- the CFD screen must check the window velocity on vs off BEFORE any hole is cut); how far silicone spreads on glass (sets the sizing correction and the exposure time before spots merge); bare vs coated substrate; a cascade impactor later as the Phase 4 reference instrument (a size distribution directly instead of one cut + microscopy); whether the port sample represents the chamber; and the still-outstanding stand-off. Earlier 2026-10-30 15:10: PLAN.md Phase 7 gained **'The suction source'** (Ben asked: buy or 3D-print a venturi ejector, and can one run without compressed air?). ANSWER: an ejector CANNOT run without a motive fluid -- it is a jet pump, the jet IS the pump. Alternatives: a WATER ASPIRATOR (tap-driven, no compressed air, but only ~10-30 L/min induced: covers 30 L/min, short of 100, needs a drain), or -- RECOMMENDED -- just a BLOWER, because the suction duty is tiny: 100 L/min at 400-800 Pa is 6 m3/h under 1 kPa, and 30 L/min needs only 36-73 Pa. A radial/centrifugal blower (1-3 kPa) is plenty, throttled; an AXIAL/computer fan (15-50 Pa) is NOT enough at 100 L/min though fine at 30; a vacuum cleaner with a bleed valve is enough for the very first slide test and needs no purchase. The ejector's real cost is the air it eats -- about as much compressed air as the flow it makes (0.8/1.0/1.5 mm nozzle at 5 bar = 32/50/113 L/min consumed, inducing 1-2x) -- so it is only attractive if the supply exceeds ~150 L/min free delivery and no electrics is worth paying for. BUYING: GBP 15-60, pick from the curve AT ~500 Pa, and note a 'vacuum generator' (suction cups: high vacuum, low flow) is the wrong end -- an 'air amplifier / air mover' (low pressure, high induced flow) is this duty. MAKING: realistic -- nozzle 1.0-1.5 mm, mixing throat 8-10 mm (6-10x the nozzle), throat length 5-8x its dia, diffuser 3-5 deg half-angle, nozzle exit 0.5-1 throat-dia upstream, suction radial; print in RESIN not FDM (FDM leaks and cannot hold a smooth 1 mm nozzle), or print only the body and glue in a bought blunt dispensing needle / brass tube as the nozzle; expect 2-3 iterations. EITHER WAY: a flowmeter in the extraction line (the CFD is run at a stated flow, so the rig's flow must be set and read; the same 0-150 L/min meter measures the compressed-air supply too) and a filter between the collector and the pump, exhausting into the existing HEPA/carbon. Earlier 2026-10-30 14:40: PLAN.md **Phase 7 now has Ben's answers and the two routes** (2026-10-30). Ben: the existing 44 mm port is post-test only (into HEPA + carbon); a NEW port does the capture, first test = can droplets land on a glass slide; a big fan is possible but a ~5 bar compressed-air design is also wanted (supply flow UNKNOWN, Ben measures it next lab visit); ports may go anywhere on the vertical walls EXCEPT the lower z = -17.5 / -297.6 walls (the shadowgraph images through them), so both 280 x 692 x-walls are fully free; band 0-30 um confirmed. ANSWERED 'do I seal the other outlet?': it depends on the route. SUCTION (recommended): leave it OPEN as the make-up inlet (extraction 30-100 L/min vs the spray's 9 means 21-91 L/min must enter; sealed = unknown leaks + undefined CFD boundary); at 44 mm that is 0.33-1.10 m/s and 0.2-2.2 mN against the spray's 25, and it keeps the chamber NEGATIVE so leaks are inward -- but DISCONNECT the HEPA/carbon while testing (backwards flow through a loaded filter). BLOW-IN: SEAL it, or the air short-circuits out of the 44 mm port instead of through the collector's ~10 mm nozzle; chamber goes positive, leaks outward. Blown-in air MUST be a diffuser >= 25 mm (46 mm or a perforated plate better): at 100 L/min a 4 mm inlet is 265 mN and a 10 mm 42 mN against the spray's 25 mN, i.e. it would run the chamber -- which is also why Phase 1's 'fines to the side' (4 mm at 32,000 sccm) is not the layout to copy. A compressed-air EJECTOR outside the chamber gives suction from the compressed-air supply (no jet in the chamber, no fan to buy; 1-1.5 mm motive nozzle at 5 bar is the right order, to check against a datasheet). THE GLASS SLIDE MUST BE AN IMPACTOR IN A DUCT AT THE PORT, not a slide in the chamber (the band follows the air; at the chamber's 0.45 m/s a slide catches almost nothing). 10 mm nozzle: 50 % cut 11 um at 30 L/min, 5.9 um at 100 L/min (270 Pa) -- the sweet spot; 6 mm at 30 L/min gives 5.0 um at 190 Pa. Two efficiencies measured separately: transport (CFD) and collection (the impactor). Extraction also cuts the chamber's residence from 234 s to 70 s (30 L/min) or 21 s (100 L/min), i.e. 11x less time for the band to settle out. Ben to measure: the compressed air's free-delivery flow and its pressure while flowing (the Alicats stop at 12 L/min, so a 0-150 L/min rotameter or a timed fill of a known volume). Earlier 2026-10-30 14:05: PLAN.md **Phase 7 DRAFTED**, awaiting Ben's go: capture design for the 0-30 um band in the real chamber (CFD_LOG section 8 item 4, now planned). The physics: the band follows the air (0-30 um settles <= 3 cm/s against the chamber's 0.45 m/s mean), so capture is set by through-flow, not by nudging droplets sideways; a well-mixed estimate puts the half-out flow at ~10 / 40 / 90 L/min for 10 / 20 / 30 um against the spray gas's own ~9 L/min, i.e. extraction of tens of L/min (a fan, not only the 5 bar supply); the big droplets self-sort (floor impaction ~20-30 um cut, settling), so purity should come largely free. Phase 1 is NOT the screen for this band (its own flag: air-following sizes, no recirculation, jets through walls); screen in the CFD instead (~35 min a case). Steps: 1 the 7.10 baseline map (Ben, ~9 min), 2 concepts (extraction only / gentle sweep / 'fines to the side' adapted), 3 Ben clicks the first in (guide Part 8, to be written), 4 the scripted screen (extends Phase 2a), 5 the best 1-2 properly (the 25-70 mN push bracket, grid check, second turbulence model), 6 Phase 4 on the rig. Four answers wanted from Ben: what is behind the outlet (filter / print surface), the extraction available (fan L/min vs compressed air), where ports can go, and that the band is 0-30 um (the CCD analysis still uses 30-60). Also today: CCD ANOVA for Ben's progress review (orifice and gas flow about equal, ~23 % of the variance each, p <= 0.003; rpm 5 % and silicone 3 %, both inside the 2.6 pp centre-repeat scatter; ~40 % of the variance shared between orifice and gas, so the design cannot rank them; at 0.5 mm the order flips: silicone -25 pp (p 0.015) and rpm +20 pp (p 0.034) because they set the delivered gas; worst flow-controlled 19.9 % -> 40.9 % repeatable at the 1.2 mm centre (model optimum 43.1 %), best single run 49.7 % (0.5 mm, never repeated); 33 runs, 2.75 M droplets detected, 347,005 sized). FLAGGED, not fixed: report.py:505-510's hard-coded gas-flux paragraph is stale (says Spearman +0.91, 'sat near 20 %', 'only two runs reached 35 %'; the table under it gives r +0.49 and eight runs are above 35 %). Earlier 2026-10-28 23:55: Ben's Chamber_v2 solve DONE: 2,000 iterations on 10 cores in 35 min, 1,225,011 cells; the 7.9 check PASSED (probed at iteration 2,000: jet 169 m/s at 2 mm, 47 / 22 / 15.5 / 10.4 m/s at 20 / 40 / 55 / 80 mm, floor wall jet 2.9 m/s at 40 mm, all within ~5 % of the prediction; residuals ~2e-3; CFD_LOG section 7); next: Ben runs the droplets check 7.10 (`settings/droplets_chamber_v2.yaml`); guide Part 7's ParaView notes say how to reuse his Part 6 states on it. Earlier 2026-10-28 22:45: Ben's Chamber_v2 case kept the 1.11 mm bore (Radius 0.555) with nitrogen's 1.426e-4 m³/s: 147 m/s, 25.3 mN, 3.6 % under 1.09 mm's 26.2, jet ~1.8 % slow, kept; guide Part 7, CFD_LOG section 7, droplets_chamber_v2.yaml (lip y 237.79), PLAN updated to 1.11; guide 7.5 says where Fluid boundary is and to rename, 7.7 step 5's ParaView slice made exact (Solid Color, Crinkle slice, not Extract Cells By Region); Ben meshed at 21:40 and is starting the 2,000-iteration solve. Earlier 2026-10-27 16:55 (Mac: Flow Visualisation, guide Part 7 corrected for NITROGEN, the rig's gas: 8,995 sccm at the Alicat's 25 °C is 171.6 mg/s, not air's 177.5, so the inlet is 1.426e-4 m³/s (was 1.474e-4), the push 26.2 mN, the bore 1.09 mm (was 1.11), length scale 0.076 mm; still single phase, all air; 7.2 notes that Check Geometry's BOP check flags two faces at the nozzle tip that come from the STEP and are harmless. Earlier 2026-10-26 22:25 (Mac: Flow Visualisation, Ben's refined chamber CAD (`~/OpenFOAM/cfdof_cases/Chamber_v2/Refined_Modular_Filter_Chamber.step`, undrilled pointed tip at 163.7, 237.0, -212.5). Wrote CFDOF_GUIDE.md PART 7 for Ben to click: simple copy out of the STEP's assembly, drill the bore (Bore cylinder, 7.5 mm up from 1 mm below the tip point), union, boundaries (spray Face42, outlet Face32), the FINAL MESH: bore 0.0625 mm, tip 0.25, cap 1, port 2, a five-cone jet ladder (0.125/0.25/0.5/1/2 mm, 8-10 cells across the jet's half-width all the way down), floor 2 mm slab + 8 layers (first cell 0.05 mm, was 1.28) and walls 10 layers (~0.1 mm): 1,218,853 cells, meshed in 17 s, Mesh OK (54 faces >70 deg at the knife-edge lip and where wall layers meet the arm). Rehearsed by script on a scratch copy at 0.91 mm (53 min, 3,000 its): gas in = out, residuals 2e-3 (Part 6 1e-2), jet 4-13 % under Hussein at 20-80 mm (the rest is k-omega SST over-spreading, not the mesh), y+ < 1 on floor and walls, floor wall jet resolved. DROPLETS: tracers on the floor (gusts off) 61.8 % in Part 6 -> 0.1 %: FIX (b) WORKS; the 0-30 um band's side-wall share 30 -> 4 %, airborne at switch-off 17 -> 40 %, floor 64 -> 87 %; leftover artefact only on the unlayered atomiser (8.9 % tracers, gusts on); iterations 2,000 vs 3,000 'close' -> guide solves 2,000 (~35 min). BORE SIZE: the work PC's exit-only Cd today (1.2 mm drilled 0.82) makes the old 0.91 mm (Cd 0.527) stale; Ben chose 1.11 mm (27 mN, 153 m/s; 0.97 mm if matching the CCD day's undrilled insert). Face numbers checked the same at 0.91/0.97/1.11. Fixed: OpenFOAM saves values like 4.9e-324 it can't read back; the droplets tool now rounds them to 0 when copying a flow (`cfd_runner._round_denormals_in`, test; 104 pass). New `settings/droplets_chamber_v2.yaml` (Part 6 vs Ben's Chamber_v2 case). CFD_LOG.md section 7 has it all. Uncommitted. Earlier 2026-10-26 evening (work PC: Cd = 0.85 FOR EVERY ORIFICE SIZE in the app (Ben): `orifice_cd.json` gains `default_cd` 0.85 (+ `default_note`), `orifice.lookup_cd` falls back to it for any size (a per-insert cd still overrides); the report (a boxed note), workbook explanation, deck 'Cd' definition, film figure caption, definitions.md, IMAGING_PIPELINE_REFERENCE and ORIFICE_CD_TEST say so explicitly. NO re-analysis (Ben): runs analysed before today keep Cd 1.0; it applies to the next CCD runs and any run analysed from now. Tests in test_gas_flux updated (0.85: gas share 0.288, film 116 um for the C7 fake). Uncommitted; the lab / home PCs need a pull. Earlier late afternoon (work PC: LINE + HOLES SEPARATED. Ben's 1.8 mm line-loss run (135241: 1.28 barA at 12,000 sccm) and a NO-EXIT run (135647, Orifice box 2mm as a label: gas out straight from the 18 x 0.3 + 1 x 0.4 mm holes; 1.195 barA at 12,000) give the line + holes as an orifice of ~1.03 mm2 (0.90-1.07 over 4-12k sccm). Solving each step for the chamber pressure behind the exit (scratch script `series_cd.py`, not in the repo; nothing --written), the EXIT-ONLY Cd is 0.5 mm 0.85, 0.8 mm 0.86, 1.2 mm (drilled) 0.82, as short tubes should; the 1.2 before drilling 0.60 (10-15) / 0.62 (10-22), i.e. ~1.02 mm effective; the bare 1.8 mm exit 0.59 (small dP, least certain). Consequences for Ben: the CCD (10-12) '1.2 mm' was presumably this insert undrilled (~1.0 mm effective) - to confirm; the app should use the chamber pressure, not the Alicat P0, at the exit (orifice_cd.py and the app's gas share need the series model); Flow Visualisation's 1.2 mm momentum figures used the raw 0.537. Earlier afternoon (work PC: the 1.2 mm Cd RE-RUN captured 13:35 (`Calibration/Orifice Cd/2026/10/26/133522_...`; no line-loss run): 1.43 barA at 12,000 sccm (10-22: 1.61; a good bore ~1.29). orifice_cd.py (scratch output only, not --write) gives Cd 0.657; but the script uses a fixed ambient 1.01325 bar while the logs' no-flow pressure was 1.007 / 0.998 / 0.992 on 10-15 / 10-22 / 10-26, which matters for the subsonic 1.2 mm: with each day's own ambient the 1.2 mm reads 0.51 / 0.54 / 0.63 (today rising 0.61 -> 0.65 with flow; equivalent bore at Cd 0.82 ~1.05 mm, was ~0.97). Better but still short of 0.8; Ben drilled the bore through at 1.2 mm before this run. Likely cause of the rest: the 18 x 0.3 + 1 x 0.4 mm holes upstream (1.40 mm2, only 1.24x the 1.2 mm exit; at Cd ~0.8 they act like ~1.11 mm2 in series, which accounts for the 0.63; small next to the 0.5 / 0.8 mm exits). Ben is running the 1.8 mm line-loss row (expect ~1.22 barA at 12,000 sccm if the holes are the cause); a third row 'LL no exit' (exit removed, holes only, Orifice 2mm as a label, Notes without CD TEST; expect ~1.17) was added to the sheet and the LaCie copy. Proposed: the script reads ambient from each run's no-flow start; run the 1.8 mm line-loss row. Earlier (work PC: run sheet for the 1.2 mm insert's Cd test again, after Ben's pin-gauge check of the bore from both ends: `docs/notes/2026-10-26_cd_1.2_rerun_run_sheet.csv`, copy on the LaCie `Experiments/Run sheets/2026-10-26 1.2 mm Cd rerun run sheet.csv`; row 2 is the optional 1.8 mm line-loss run (on the 10-22 sheet but never captured: only 104111 is in `Calibration/Orifice Cd/2026/10/22`). Earlier 09:08 (Mac: LaCie backup plan and sizes, `docs/notes/2026-10-26_lacie_backup.md`; merged the work PC's 2026-10-22 commits (orifice lengths 7.5 mm, Cd, beads dropped); before that, parked the exit-lip CFD idea in Flow Visualisation PLAN.md; before that, Ben's new CAD: the orifice tip pointed and undrilled; the bore (7.5 mm, from the mixing chamber; its top face the inlet) is drilled from the tip point at the equivalent size, by hand in FreeCAD in the guided session, then by the script. His real inserts' tips differ slightly by bore; drilling one blank instead was judged invisible in the chamber flow (PLAN.md Phase 2a). Earlier 17:05: agreed order for Phase 2a: Ben makes the new CAD, then a guided click-through of the better mesh in FreeCAD/CfdOF (a new CFDOF_GUIDE part), then Claude codes the runs. CCD day (12 Oct) gas flows looked up: 7,000/9,000/11,000 sccm within 0.5 %, inserts 0.5/1.2/1.8 (+ one 0.8); 16 distinct jets; the 0.5 mm pressures behave oddly (less with more liquid; repeats 6.0 vs 7.3 barA), worth a check. Later: flows built from a run's run_summary.xlsx. Earlier 16:00: committed the Flow Visualisation work on Testing (7be789b, not pushed). Wrote plan 1 as PLAN.md Phase 2a, the scripted flow builder: one settings file of orifice sizes -> for each, the momentum-equivalent hole (d_eq from the bore and Cd, or a run's measured pressure and flow) fused onto the CAD, meshed with the jet cones and a floor layer (fix (b)), solved, as a normal CfdOF case; then the droplets sweep across sizes and a grid check. Parts A (can CfdOF be scripted headless: a spike) to D; awaiting Ben's go and his answers (sizes; gas-only vs measured effective hole; one gas flow or each insert's; liquid momentum left out?). Ben makes the new CAD this week (spec in Phase 2a). Earlier 15:45: every droplets run's ParaView state now also carries Ben's CfdOF views (two slices, three streamline sets, his colour scale; hidden) and a 'split' tab (droplets | the air, cameras linked) for screenshots; `run_droplets.py --views-only <run folder>` remakes a finished run's views; today's runs remade. 103 tests pass. Earlier 15:25: Ben asked for everything under ~/OpenFOAM: each droplets run is now one folder, ~/OpenFOAM/droplet_runs/<name>/<date_time>/ (report, figures, ParaView views, OpenFOAM cases in openfoam/ with hard-linked meshes); double-click paraview/<run>.command to view it, from wherever the folder is copied (checked on a copy). Setting run.runs_folder (old cases_folder still read). Today's baseline and snapshot sweep moved in; Phase 1 results stay in Flow Visualisation/output/. 102 tests pass. Earlier 14:10: Phase 3a Part D DONE, stopped for Ben's review (Flow Visualisation/PLAN.md, Part D results; cfdof/CFD_LOG.md section 6). Built a sweep (one droplets settings file through several flows, then compared: `comparison.md`; `run_droplets.py --compare` for finished runs) so orifice sizes can be compared later. Snapshot check: iterations 1000/1500/2000 give the same droplet deposit within the droplet-count noise (0-30 um band's floor share within 1.3 points; brackets 42 and 13) although the air differs 28-39 % point by point: one snapshot is enough, no pimpleFoam needed for this. The Part 5 (jet not refined) mesh differs a lot (band floor share +13 to +19 points, tracers 99 % vs 62 % on the floor): the mesh matters more, so the grid check + near-wall layer (plan 1). Found and fixed: the spray-stage step (exposure / per_size) at the old default 200 (25 ms) sent a tenth of the 0-10 um droplets to the side walls with gusts off (2 % at 8.3/5/2.5 ms); default now 600 per size (8.3 ms, ~1.5 min a baseline), longer steps flagged (report check 7). Also fixed: runs started together collided. Baseline: output/droplets_baseline/2026-10-25_140603. 101 tests pass. Next: Ben's go on planning plan 1 (scripted flows, orifice from code). Earlier 11:30: Ben: orifice-as-code waits for his better CAD model (then plan 1, the scripted flow builder, which also carries the near-wall fix (b); fix (a) dropped). His question 'does the silicone in the orifice make it smaller?' checked on the CCD day's run_summary pressure logs (read-only): yes, apparently a lot: 1.2 mm at 9,000 sccm reads 3.1 barA while spraying vs 1.39 barA gas-only, so the gas gets ~41 % of its gas-only area (less with more liquid), 0.5 mm 49-78 %; if it is all at the orifice the jet is choked at ~71 mN, not 40 (the CFD's 1.0 mm hole ~33 mN); upstream losses and two-phase choking not yet separated (CFD_LOG section 7). Fixed: report.md said the liquid carries as much momentum as the gas; it is mass. Next proposed: Part D (baseline run + snapshot check) before plan 1. Earlier 11:00: Ben asked for the orifice size as a setting and questioned fix (a) as 'cheating'. Answered: (a) edits the solved flow, so at most a disclosed bracket, not the main model; proposed a scripted flow builder (orifice bore/Cd/gas flow -> the equivalent hole in the CAD, the mesh with a thin floor layer, the solve, then droplets), which is also fix (b) and Phase 2's first step; quicker alternative: the same mesh with the inlet set to the insert's momentum. Numbers at 8,995 sccm: 0.5 mm insert 78.6 mN (d_eq 0.65 mm), 0.8 mm 53.9 mN (0.79), 1.2 mm 40.1 mN (0.91); the 1.0 mm CAD hole gives 42 / 62 / 83 % of those. Awaiting Ben's choice. Earlier 10:30: Phase 3a Part C BUILT (figures, report, checks), awaiting Ben's choice on the near-wall artefact, then Part D. Every droplets run now ends with `report.md` + `figures/` (`run_droplets.py --report-only <output folder>` remakes them): floor deposit maps by size band seen from above, with the atomiser body / nozzle block / arm outlined from the mesh, the exit orifice and the port; where each size ends up (floor split: air moving / still air); the 0-30 um band weighted by CCD 131450's measured sizes (in effect 10-30 um), by number and volume, and its share of the floor deposit; checks as 4 extra OpenFOAM cases (~1 min for everything): accounting PASS, OpenFOAM's tracking = Phase 1's integrator (1e-6 %, 0.1 mm) PASS, settling vs Phase 1 within 0.4 % below 60 um / 1.7 % at 200 um (drag laws), large droplets within 24 mm of the impact point PASS, gusts on vs off (large unchanged). FLAG, measured and explained: 0.5 um tracers that follow the air land on the floor (62 % in 5 s gusts off, 25 % on; fired sizes to ~10 um the same): OpenFOAM's linear interpolation in the 1.3 mm wall cell brings a follower within nm of the floor and settling finishes it (hit at exactly the settling speed; none land with gravity off; time step 0.1-25 ms makes no difference); mostly the first pass, within ~80 mm of the impact point. Fines' floor/wall counts while the air moves are upper bounds until fixed. Options for Ben: (a) air in wall cells made parallel to the wall (scratch prototype: 62 -> 11 %), (b) finer near-wall mesh + new CfdOF solve, (c) both. physics.py gained the 'putnam' drag law (OpenFOAM's) and a g argument to settling_speed; 89 tests pass (14 new in tests/test_cfd_report.py); tested end to end in scratch only, nothing in ~/OpenFOAM/droplet_runs yet; CFD_LOG section 6, PLAN Phase 3a status, README, HOW_TO_REDO step 7 updated. Earlier 2026-10-25 01:15: Phase 3a Part B BUILT, awaiting Ben's go for Part C. The droplets tool: `Flow Visualisation/run_droplets.py` + `settings/droplets_baseline.yaml` (README 'Droplets through the CFD flow'; HOW_TO_REDO step 7). It copies a CfdOF case's iteration (reconstructed once into `~/OpenFOAM/droplet_runs/flows/`), runs OpenFOAM's tracker for gusts on/off x flow kept 0/2/10 s after switch-off (6 runs at once, ~30 s each at 20,000 droplets: 2-200 um, 200 each), then still air to 5 min; writes droplets.csv, fates_by_size.csv, bands.csv, run.md and a ParaView state per run (flow cut, wall edges, droplets by size, deposit building up). Choices: one cone-nozzle injector per size, one droplet per size per step; walls 'escape' + hit records instead of 'stick' (stick kept integrating stuck droplets: 4.6 min vs 4 s of still air per run); landed droplets written back into the frames for ParaView. 23 new tests (75 in Flow Visualisation pass); checked end to end in scratch only, nothing in ~/OpenFOAM/droplet_runs yet. FLAG for Part C: with gusts off, even 2 um droplets land on the floor near the jet's landing point (a tracking artefact: the tracker follows the air into the layer against the floor); Part C measures it with tracer droplets. Part A (earlier 2026-10-25): 10/30/100 um test through Ben's Part 6 flow, all accounted for; the jet blows 30 um onto the floor during the exposure; the fines hinge on the gust model. Earlier 2026-10-24 16:30 (Mac: Ben ran guide Part 5 himself by clicking (case `~/OpenFOAM/cfdof_cases/Chamber_v1/case`, 66,548 cells, 2,000 iterations, residuals as the scripted check). Probed: the spray entrains air radially at 0.6-5 m/s within 15 mm of the hole (matches Ricou & Spalding, ~0.32 Q0/d), the jet lands at ~2 m/s and spreads along the floor at up to 2.5 m/s, chamber mean speed 0.54 m/s (44 % of the volume above 0.5 m/s), outlet 0.13 m/s. BUT the jet's first ~100 mm is smeared by the mesh (refined only at the hole): centreline 11 m/s at 10 mm and 7 m/s at 80 mm where a real 1 mm jet has ~110 and ~14 m/s; it needs a volume refinement along the jet (Phase 2 step 3 already says so). Guide: saving (FreeCAD, ParaView state, Save As per variation). Ben (2026-10-24): this model is the BASELINE chamber with no collection; the 44 mm port is the post-test extraction opening, not a collector. Well-mixed estimate for it (spray gas the only through-flow, 240 s residence; Stokes settling onto the 190 x 280 mm floor; walls ignored): the share of each size carried out of that port is 5 um 78 %, 10 um 46 %, 20 um 18 %, 30 um 9 %, i.e. most of the band settles on the floor. Ben's sequence (agreed): jet refinement, then droplets through the baseline (where each size goes), then a cross-stream + collection design, screened in Phase 1's fast model before CFD. Also noted: the liquid carries as much mass as the gas (2.0e-4 vs 1.8e-4 kg/s), not yet in any flow model; sub-30 um droplets are counted but not sized (d_min ~30 um), the main limit on any 0-30 um delivery figure. Ben's validation plan for step 2: a 3 x 3 grid of glass slides on the chamber floor, spray warmed up 20 s into a bin, ~5 s free, then microscopy + image classification for a deposit map by size and position (also sizes the sub-30 um droplets the shadowgraph cannot). Flagged: fines from the 20 s warm-up spill into the chamber (cover the slides or run a warm-up-only control), stains are ~2.5-3x the droplet diameter if silicone wets glass (measure the spread), keep coverage low, wait ~10 min for fines to settle. The 44 mm port has a fine mesh: a few Pa at 0.1 m/s, so it stays an open 0 Pa outlet in the model. Guide Part 6 (jet refinement, by clicking) written and checked by script: two cones of 0.5 / 2 mm cells along the jet, 198,682 cells, ~7 min; jet 94 / 47 / 11 m/s at 10 / 20 / 80 mm below the hole (was 11 / 5 / 7; textbook ~110 / 56 / 14), chamber circulation unchanged (mean 0.55 m/s). Work log of the CFD: `Flow Visualisation/cfdof/CFD_LOG.md`. Ben ran Part 6 himself (`~/OpenFOAM/cfdof_cases/Chamber_v1_jet/case`, matches the scripted check). Redo recipe `Flow Visualisation/cfdof/HOW_TO_REDO.md` (with a one-line spray-inlet calculator for any bore / Cd / flow); it, the guide and the CFD log are linked from `~/OpenFOAM/cfdof_cases/`. PLAN.md Phase 3a DRAFTED: droplets through the CfdOF baseline with OpenFOAM's uncoupledKinematicParcelFoam (recommended; Python keeps inputs/outputs and cross-checks), floor deposit map + per-slide counts by size for Ben's slide grid, spray-on 5 s then settling bracketed (still air vs flow running), snapshot check on iterations 1000/1500/2000; Ben (2026-10-24/25): OpenFOAM's tracker; rig = warm-up into the bin with slides covered, bin away + slides uncovered for the exposure (whole spray <= 45 s), then system off and settle in still air (no bin in the model; settling time sets the smallest size caught: 10 um ~3.6 min). Flagged: warm-up fines escape the bin and settle onto the slides once uncovered (control run / filter on the bin / shorter warm-up). Slide-comparison code and slide positions: later. Plan agreed; building waits for Ben's go. Earlier 2026-10-24 11:30 (Mac: Ben's real-chamber STEP v2 (`~/OpenFOAM/cfdof_cases/FlowVis1stTrial/Flow Analysis Basic.step`) is runnable: a 44 mm outlet stub added (vents to the room, 0 Pa); the spray hole stays 1.0 mm (Ben), so at 8,995 sccm it leaves at 188 m/s with 83 % of the real momentum. Checked by script on a scratch copy: 66,500 cells (cfMesh 8 mm, 0.1 mm at the hole, 2 mm at the outlet), 2,000 iterations in 142 s on 10 cores, gas in = out (1.474e-4 m3/s), peak 211 m/s, velocity residuals stall ~1e-2 (as the box with spray). CFDOF_GUIDE.md gained Part 5 (his chamber, by clicking; faces picked from CfdOF's list). Next: Ben clicks through Part 5. Earlier 2026-10-24 10:45 (Mac: Ben's first real-chamber STEP for CfdOF (`~/OpenFOAM/cfdof_cases/FlowVis1stTrial/Flow Analysis Basic v1.step`) checked read-only: one valid closed solid in mm, 190 x 692 x 280 mm, 35.3 L of air, apparently Y up (Fusion); the atomiser body, nozzle block and a 30 x 30 mm arm are cut out of it. Not runnable yet: no gas outlet (the spray hole is the only opening) and the spray hole is 1.0 mm, not the 0.91 mm equivalent (17 % too little momentum). Ben adds the ports and re-exports; then the guide gets a Part 5 (his chamber, by clicking). Earlier 2026-10-23 17:30 (Mac: Flow Visualisation Phase 2 switched to OpenFOAM steady RANS on the Mac (Ben); FluidX3D dropped: its uniform grid would have put the spray in carrying 4-8x its real gas, making the outlet flow ~2.6-4.7x too high. Installed: OpenFOAM v2606 (Homebrew tap gerlero/openfoam), ParaView 6.2.0, FreeCAD 1.1.4 + CfdOF (GUI, so Ben can learn CFD hands-on) + cfMesh built against v2606; CfdOF's dependency check passes (v2606 'not yet supported' warning only). Ben's guide `Flow Visualisation/cfdof/CFDOF_GUIDE.md` (answer key `cfdof/chamber_box.FCMacro`), checked by script: chamber box 67,000 cells, 2,000 iterations in 64 s on 10 cores, gas in = gas out; with the 0.91 mm spray 83,000 cells, 78 s, velocity residuals stall ~1e-2. PLAN.md Phase 2 rewritten (spray as its real gas flow and momentum, 0.91 mm at 226 m/s; k-omega SST; checks: two meshes, two turbulence models, compressible on one setting); the home-PC FluidX3D hand-off deleted. Next: Ben works through the guide; Phase 2's scripted box case waits for his go. Also today: band changed to 0-30 um (Ben) and all seven studies re-run (best: 'fines to the side', side jet 4 mm / 32,000 sccm + 200 x 80 mm slot outlet at z 150: 73.7 % of the band at 92.7 % purity by number, jet model); two replies were cut off by a safety classifier and their re-sends forked the conversation (leftover files explained, nothing lost). Earlier 2026-10-23 13:10 (Mac: Flow Visualisation, Ben's floor-collection idea run in the Phase 1 tool (no new physics): 40 x 40 mm area on the floor + 4 mm / 32,000 sccm side jet + 6 mm lid down-jet; jet model: area at x 100-140 with no down jet 77 % of the 30-60 um band at 42 % purity (x 120-160: 37 % at 61 %); the down jet raises delivery (93-99 %) but drags fines in (purity 25-30 %). Not modelled: impaction on the plate, estimated 50 % cut ~27 um at the floor, scaling with distance from the nozzle. Tool fixes: arrivals on a floor target flagged as an upper bound; sweep values get short labels; heat maps coloured from 0 (52 tests pass). Open (Ben): plate or extraction outlet? Earlier 2026-10-23 12:25 (Mac: Flow Visualisation, a band under 30 um (Ben): 10-30 um, sub-30 sizes spread evenly (estimated); the jet model delivers almost none (13.2 % via the 4 mm / 32,000 sccm inlet, 0.7 % via 6 mm, both 100 % pure; 0.4 % at 45 deg; 0 elsewhere) but these sizes follow the air and are the ones it handles worst; a perfectly stirred chamber (settle or flush) lets 31-50 % out; the truth is between, Phases 2-3 decide; settings/sub30_*.yaml + output/band_under_30_um_comparison/; deck now 20 slides with what each figure shows and how to read it. Earlier 2026-10-23 12:00 (Mac: Flow Visualisation Phase 1 results with purity: CCD 131450's size distribution imported read-only from the LaCie (`Flow Visualisation/data/ccd_131450_sizes.csv`, sizer 3.1.0: 13,154 sized, 64,841 below 30 um); stand-off 55 mm (Ben's estimate); all three runs re-done: nozzle straight down delivers none of the band (cross-jet push 5.5 mm, 3-29 mm across the inlet sweep); the 4 mm / 32,000 sccm inlet strips 10-22 um fines to the outlet (a fines cut); nozzle 45 deg towards the outlet delivers 6.0 % of the band by number at 74.6 % purity (inlet off 8.5 % / 44.2 %); deck of the results (17 slides) https://claude.ai/artifact/2aRQfYQT4WvsE9RvpsQ9wh; still uncommitted. Earlier 2026-10-23 11:35 (Mac: Flow Visualisation Phase 1 BUILT (Ben's go 2026-10-23), awaiting his review; uncommitted: `Flow Visualisation/` droplet_transport 1.0.0 (run.py, band.py, import_sizes.py, settings/ with the first scenario + 2 example sweeps, README.md with the commands), 50 tests pass (PLAN's 7 checks + gas dynamics, settings, importer = master_log's band rule, end to end); ~10 s a scenario. Idealised results: with the nozzle straight down, CCD 131450's spray jet (40 mN at the 1.2 mm insert's Cd) takes every size to the floor; a 4-10 mm, 8,000-32,000 sccm right-wall inlet pushes the 30-60 um band 3-29 mm towards the outlet (~flow / diameter) and delivers nothing; tilting the nozzle 45 deg towards the outlet delivers ~9 % of the band (18 % at 80-105 um, none under 25 um): aiming the spray is the stronger lever. Flags: 10-76 um floor hits are artefacts (St < 1 at the floor); the gas-only jet is 39 m/s at the 25 mm stand-off vs droplets at 6 m/s (Phase 5 settles it). PLAN's momentum figures corrected again (isentropic exit with Cd: 10,200 sccm through the 1.2 mm insert = 50 mN, 35 mN if clean). Needs: 131450's size distribution imported (LaCie) for purity; the stand-off measured. Earlier 2026-10-23 11:00 (Mac: Flow Visualisation Phase 0 DONE (Ben): target = the left outlet; the air crosses the 300 mm length (in square to the right-hand 200 mm wall); all four of Claude's proposals accepted; PLAN.md now has the first scenario's defaults (x along the 300 mm, nozzle top centre straight down, CCD 131450's gas + sizes, 6 m/s start, placeholder 6 mm inlet / 25 mm outlet at mid-height, each marked measured / estimated / design choice); still no code, Phase 1 waits for Ben's go; the stand-off (orifice to image centre) is to be measured on the velocity rig day. Earlier 2026-10-23 10:50 (Mac: Flow Visualisation PLAN.md checked and updated, still no code: Ben's answers: nozzle position + direction editable (default top centre, straight down), droplet sizes fired and the band delivered both editable (band changes need no re-run), purity by number AND volume both headlines, chamber not built yet (soon), Phase 4 checked on the cross-stream on/off ratio + size-distribution shape (absolute delivery cannot be: in-band droplets/s is only known to +-50-60 %). Corrected: the 100-460 m/s 'exit speed' is the standard-density Q/A equivalent, so jets are set by mass flow + momentum (1.2 mm insert at 10,200 sccm: 30 mN clean bore, 47 mN at its Cd); an equivalent spray inlet can keep momentum but not also mass flow; 150 um settles at ~0.5 m/s. Found: the spray entrains ~80x its own gas by 300 mm and has 18-700x the 8,000 sccm inlet's momentum, so the chamber circulation is the spray's; FluidX3D at 0.5 mm is ~1.5-2.5 days a setting (est.), 1 mm ~2-4 h; LES (Smagorinsky) required. Awaiting Ben: target, axes, and four proposals (droplets start at the window, Phase 1 headline = deflection by size, 1 mm sweep + one 0.5 mm check, mean flow + random walk). Earlier 2026-10-23 later (Mac: Flow Visualisation PLAN.md updated with Ben's Phase 0 answers: chamber ~300 x 200 x 350 mm in Fusion; air in on the right, out on the left, ~8,000 sccm, inlets/outlets editable in one settings file; goal: deliver a size band (30-60 um, editable) to a target; thesis numbers + trends, so the rig check is needed; RTX 5060 Ti 16 GB fits 0.5 mm cells. First estimates: 8,000 sccm is ~2 mm/s over the chamber, so delivery must come from the inlet jet; the spray's own gas jet likely dominates; a band needs two cuts (purity). Six questions still open. Earlier 2026-10-23 (Mac: new folder `Flow Visualisation/` with PLAN.md, a DRAFT plan for to-do items 9-11 (droplet transport by a carrier gas + cross-stream: Phase 0 Ben's answers, 1 a simple Python model, 2 the chamber airflow in FluidX3D on the home PC, 3 droplets through it, 4 a rig check, 5 droplet speeds, 6 optional nozzle CFD); Ben: plan every step before any code, so nothing is coded until he approves a phase. Earlier 2026-10-22 (Mac: new separate to-do part (Ben), `docs/notes/2026-10-17_todo.md` items 9-11: a droplet transport model (carrier gas + cross-stream, Python first, from 2026-10-23), the droplet-speed capture next week (256 x 1152 at 10 kfps, 1 us; first look ~1.5 h), an optional gas-only nozzle CFD; free software only. Lab today: the 2026-10-22 sheet (big beads, then the 1.2 mm Cd check). Earlier 2026-10-22 (work PC, committed 309686b / a0c09f8, merged on the Mac 2026-10-26: ORIFICE LENGTHS: every exit insert is 7.5 mm long (Ben), not the 8 typed on 2026-10-15: master_log's 'Orifice Length (mm)' changed 8 -> 7.5 on the 39 rows of 2026-10-15 (the only rows with a length besides today's 7.5; 372 images kept; backup `Logs/Backups/master_log BACKUP 2026-10-22 before orifice length 7.5.xlsx`); the run folders' run_summary still say 8 (raw, not edited): `orifice_cd.py --orifice-length-mm 7.5` overrides them. Cd RE-ANALYSED with both days (`Calibration/Orifice Cd/analysis/2026-10-22/`, not --write; orifice_cd.json still empty, so the app's outputs are unchanged): 0.5 mm 0.844, 0.8 mm 0.814, 1.2 mm 0.537 (10-15 0.527, today's repeat 104111 0.547). L/D 15 / 9.4 / 6.25: short tubes, all should read ~0.8-0.85 with the 1.2 the highest; the 1.2 mm still passes as if ~0.97 mm. No single line loss fits (one large enough to lift the 1.2 to ~0.75 pushes the 0.8 to 0.92). DECIDED (Ben): do the Cd RIGHT, no assumed 0.8 (the film covariate correlates -0.90 with atomised fraction across inserts), so orifice_cd.json stays EMPTY until the 1.2 is resolved: Ben buys pin gauges, checks the 1.2 bore (from both ends); if it is wrong he re-makes the 1.2 insert and re-runs its Cd test. Today's rig tests: NO analysis (Ben). The 2026-10-15 Cd analysis folder was regenerated with L 7.5 (numbers unchanged); the 39 run folders' run_summary keep 8 (Ben: leave raw data). The 1.2 was CLEANED before today's test and its bore looks the right size (Ben), so not residue. NEXT: the line-loss run on the bare 1.8 mm exit, added to today's sheet (`Cd 1.8 LL`, Notes `CD TEST 1.8 mm line loss`; ~1.07 barA at 12,000 sccm if the line is clean), then re-run with `--line-loss-run`; and a go / no-go pin check of the 1.2 bore from BOTH ends (a stepped or undersize drilling inside the 7.5 mm). Earlier today: the BIG-BEAD THROUGH-FOCUS SERIES IS DROPPED (Ben: the beads do not stick to the slide well enough: turned upright into the camera's focus window they fall off; not a glass/optics problem, so the 10-15 sandwich data stand); today's sheet is now just the 1.2 mm insert's Cd check, `docs/notes/2026-10-22_thursday_run_sheet.csv` (Motor Travel 0; the bead sheet in git history), LaCie copy updated; the big sizes rest on the 10-15 falling pours and, for depth and the table's big nodes, the reticle's dots; Ben gets a 100 um reticle today, to use ONLY as the GUI focus check target (FOCUS CHECK card; the meter's diameter readout is hard-wired to 300 um, GUI_Clean FOCUS_PINHOLE_UM), the PS20 graticules soon; uncommitted. Earlier 2026-10-21 (Mac: big-bead through-focus series re-planned (Ben, to save rig time): ONE sandwich of the three big sizes (155.8 + 98.1 + 76.39 um) through focus instead of a slide each, then the 1.2 mm insert's Cd check (inspect for residue, measure the bore, re-run the ladder); run sheet `docs/notes/2026-10-22_big_beads_through_focus_run_sheet.csv` (33 rows: ~30-35 min of beads + ~15 min of Cd; copy on the LaCie in `Experiments/Run sheets/2026-10-22 Thursday run sheet.csv`); bead_calibration reads a slide named '155.8+98.1+76.39' as just those sizes (2 tests; full app suite 995 passed; uncommitted). Earlier 2026-10-19 (Mac: frame-image colours changed (Ben): brighter, ten clearly different verdict colours, 3 px rings with a thin dark edge, filaments/blobs and the un-atomised fill in one orange; committed and pushed 3ab9606 (drawing only, no number changes; the lab PC and home PC must git pull); images already in run folders keep the old colours until re-drawn. Ben's 'Best atomisation so far' deck (38 slides, Desktop) uses the new colours; the falling beads measured at 3.1.0 read +0.8 to +2.4% for single beads, with 21% / 12% touching pairs at 37 / 56 um (to-do 5b). Earlier 2026-10-17 23:00 (Mac: Ben ACCEPTED sizer 3.1.0 (Phase 6 passed), dropped Phase 7 (no re-measure of the Taguchi 10-05 / L9 10-01 days: the CCD day is the reference) and chose to report sizes above 155.8 um; the comparison deck gained the master_log definitions (atomised every object vs in the volume, concentration and why droplets/s needs no speed) and to-do item 4's frame figure (three frames rebuilt with the liquid stage's own code, matching their recorded numbers; per-run chart: in the volume ~2.1x every object at 1.2/1.8 mm, 1.5x at 0.5 mm), now 27 slides; Phase 8 docs DONE; draw.io and FiftyOne to-dos removed (Ben). Earlier 2026-10-17 19:30 (Mac: Ben ran the 3.1.0 analysis in the app (`Taguchi/CCD/Rec CCD 4 factor 30-60um sizer 3.1.0/`, master_log 33 rows filled, backup kept); the 2.2.0/3.0.0/3.1.0 COMPARISON is done: deck https://claude.ai/artifact/3LjGxwXAm9PjMYWmcYQUTE (20 slides; PDF + editable PPTX, per-run xlsx, frames in `Taguchi/CCD/CCD sizer 3.1.0 remeasure 17-10-2026/`): every 3.0.0 runaway traced to liquid the AI did not outline or a window drop, all caught by 3.1.0; atomised and concentration unchanged; droplets/s ~3x lower and re-ordered, its surface now predicts poorly (pred R2 0.44 vs 0.91 at 2.2.0; centre repeats CV 21% vs 11%), so the 3.1.0 best setting rests on atomised alone (10,200 sccm, 500 rpm, 4,000 sps, 1.2 mm); best run 131450. NEXT: Ben's Phase 6 go/no-go, then Phase 7 (10-05, 10-01). Earlier 2026-10-17 18:40 (Mac: the CCD day RE-MEASURED AT 3.1.0, 33/33 ok (2 runs in the app, 31 four at a time, 16:27-18:37); every run has 3.1.0 in droplets_0.30 + liquid_0.30, 3.0.0 in _sizer3.0.0/, 2.2.0 in _sizer2.2.0/, and a largest_droplets.png; D32 median 2.2.0 54.5 / 3.0.0 57.3 / 3.1.0 49.5 um (3.1.0 range 33.0-61.4; the 3.0.0 runaways gone: 112022 287.9 -> 33.0 (the dribble), 113349 243.4 -> 53.7, 123534 101.9 -> 57.0); window drops caught by the rolling background in 15 runs; NEXT: Ben sets 10 um size bins (max 100) and runs Analyse in the Response surface tab (master_log fills), then Claude's 2.2.0/3.0.0/3.1.0 comparison. Earlier 2026-10-17 ~16:05 (Mac: Ben's Phase 5 batch in the app HALTED on run 1 by a stale contract: pipeline_spec said 1-4 classical extreme images, the liquid stage has drawn up to 8 since 2026-10-14 (measure_run's busiest / mean-diameter frames); never seen because every batch since ran through scripts. Fixed (count 1-8; run 1's outputs then pass every check), and the app's ETA no longer costs the AI for a re-measure batch (it read 28 h for a ~4.5 h batch) and trusts this job's own run times over remembered ones (two remembered 2.2.0 runs made it read 0.7 h); all uncommitted; the batch restarted 16:15 (33 runs, the halted job in _job_archive), but one at a time it would end ~20:30, so at 16:26 (Ben) the app's batch was stopped after run 2 and the rest re-measured FOUR at a time by `Taguchi/CCD/CCD sizer 3.1.0 remeasure 17-10-2026/scripts/remeasure_ccd_31.py` (the same batch_runs --reuse --sizer 3.1.0 chain, each run checked against the app's contract; progress.log there); expected ~18:30. Do NOT press Resume in the app while it runs. Then Ben: Response surface tab, Analyse. Earlier 2026-10-17 evening (Mac: Phase 5 READY for Ben: the whole re-measure chain rehearsed on a scratch copy of CCD 125754 (7 min a run: 3.0.0 kept in _sizer3.0.0/, rolling background, static specks, largest-droplets sheet) and the app's master_log fill rehearsed on a copy of the live log (migrated to the new layout, row filled: 77,289 droplets/s 30-60 um, 0.156 mL/min, Sizer 3.1.0); Ben's steps, with the timing (~4 h, one run at a time) and the old model copied into a new output folder: docs/notes/2026-10-17_phase5_remeasure_ccd_in_the_app.md). Earlier 2026-10-17 (Mac: sizer 3.1.0 Phase 4 DONE (uncommitted): master_log in one shared module (master_log.py) for GUI_Clean and the app, the app fills the analysed runs' rows after every analysis, new columns right of Droplets/s (30-60 um): <30 / 30-40 / 40-60 / 60-100 / 100+ um per cm3, in-band flow, concentration, atomised in volume, Sizer (Ben); the six 3.0.0 columns go; Re-measure keeps the old results in _sizer<old>/; frame images coloured by verdict with a key; a largest-droplets sheet + slide per run; deck 63 slides; NEXT: Phase 5, Ben re-measures the CCD day in the app (docs/notes/2026-10-17_phase5_remeasure_ccd_in_the_app.md); **lab PC must git pull before its next capture**). Earlier 2026-10-17 (Mac: sizer 3.1.0 Phase 3 DONE: throughput by one shared function (rates.py): in-band droplets/s = syringe flow x in-band droplets per mm3 of liquid in the measurement volume, in-band liquid flow (mL/min) = syringe flow x their share of it; band 30-60 um (Ben); CCD 125754 77,000/s (0.16 mL/min), 143415 19,000/s, 123534 4,500/s, CIs +-50-60 %; master_log layout decided (Ben): Droplets/s stays, becomes 30-60, new columns to its right (Phase 4); next Phase 4). Earlier 2026-10-17 (Mac: sizer 3.1.0 Phase 2 DONE: the rolling background (25-frame blocks, median of +/-25 frames, in analysis/background_rolling/) divides out drops that land on the window mid-run and logs them (123534: 2 drops from frames 250/275, its shadow droplets sized again); **3.1.0 is now the DEFAULT sizer**; next Phase 3, throughput). Earlier 2026-10-17 (Mac: sizer 3.1.0 Phase 1 DONE (selectable as --sizer 3.1.0): every undetected piece of liquid round a droplet is blanked, and droplets that are attached / in dark surroundings / far above their mask / static dust are not sized; CCD D32 123534 101.9 -> 56.9, 143415 83.8 -> 52.3, 125754 51.0 -> 49.2 um, concentration and atomised unchanged; dust specks at fixed pixels in every CCD run found; plan `docs/notes/2026-10-17_sizer_3.1.0_plan.md`, approved by Ben; air purge ruled out (Ben); next Phase 2, the rolling background). 2026-10-16 night (Mac: the CCD day re-measured at 3.0.0, 33/33, 2.2.0 kept in each run's _sizer2.2.0/, comparison + PROVISIONAL response surfaces in `Taguchi/CCD/CCD sizer 3.0.0 remeasure 16-10-2026/`, master_log gains six 3.0.0 columns at the end (backup kept); found: small droplets beside dark liquid the AI did not detect read 200-430 um and inflate the 3.0.0 D32 (fix first, to-do item 0a); no-spray cut fixed to read every object (uncommitted)). Earlier 2026-10-16 late (Mac: Phase 5 + 3.0.0 as the default committed and pushed, f022452; Ben's questions answered in `docs/notes/2026-10-17_todo.md` (master_log columns and size bands, the app writing master_log, droplets/s kept but wrong at 3.0.0 until fixed, why the in-volume atomised fraction is higher: 80 % of filament/blob area is outside the volume against 45 % of droplet area, the AI, partly in-focus ligaments, frame size); next: the CCD day re-measured at 3.0.0 overnight on the Mac, at Ben's go). Earlier 2026-10-16 evening (Mac: sizer 3.0.0 Phase 5 DONE: concentration per mm3 (depth 10.3 mm, the lens is telecentric so the volume is a box; CCD 125754: 0.057 per mm3) and the atomised fraction inside the volume (125754: 41.6 % in the volume vs 20.5 % all objects); pours 96-99 % in the volume (37 um crowded pour 88 %: the AI misses beads); **3.0.0 is now the DEFAULT sizer** (Ben) in the app, GUI_Clean and the pipeline, and the app flags runs measured with an older sizer or bead calibration for 'Re-measure only'; deck 46 slides). Earlier 2026-10-16 (Mac: sizer 3.0.0 Phase 4 code DONE, opt-in (`--sizer 3.0.0`; 2.2.0 stays the default until Ben's Phase 6 go; 2.2.0 output byte-identical to the committed code on CCD 125754): shared blur.py (numpy + OpenCV, identical to the bead measurement on 4,118 real objects), each spray droplet measured on its own profile (other detections blanked; touching = crowded), CCD 125754 at 3.0.0: D32 51.0 um (2.2.0: 54.0), 84 % of in-volume droplets below d_min 30 um, 98 % of sized droplets sized through the table; Phases 3-4 committed and pushed with the deck's 12 new slides; next Phase 5). Earlier 2026-10-16 (Mac: Phases 1-2 committed and pushed, 3e3ab27; sizer 3.0.0 Phase 3 DONE, provisional: edge = Blaisot's contrast-corrected size - 5.6 um, chi_sharp 15 um, chi_max 50 um with the look-up table (built on the static beads, checked on the falling ones: every size 37-155.8 um within +4.7 %), depth 10.3 mm and the same for every size, written into the optics profile; big-bead through-focus run sheet written (93 rows, needs neither the pinhole nor the meter); Ben chose option 1: 30-37 um droplets sized through the extrapolated table, one volume for every size; Phase 4 started). Earlier 2026-10-16 (Mac: sizer 3.0.0 Phase 1 code DONE: focus_edge.py + GUI_Clean Focus check card + docs/FOCUS_CHECK.md, ready for the pinhole; deck updated with the plan and Phase 2). Earlier 2026-10-16 (Mac: sizer 3.0.0 Phase 2 DONE: provisional d_min 30-35 um (half-max), the model matches the beads near focus only, a tight chi cut over-counts small droplets; next Phase 1 code). Earlier 2026-10-16 (Mac: Phase 1 focus target is now a 300 um precision pinhole (Ben; arrives the week of 2026-10-19), plan updated). 2026-10-15 late (Mac: sizer 3.0.0 plan APPROVED (docs/notes/2026-10-15_sizer_3.0.0_plan.md); Phase 0 DONE: one optics profile, config/optics/ + optics.py, no number changes (checked on a real CCD run); next Phases 1 + 2). Earlier the same evening (Mac: falling beads re-measured bead by bead: a blur-width (chi) focus rule brings them back to the static values; the at-focus bias looks like a fixed ~+6 um edge offset, not the 8.6 % scale error read earlier (the 155.8 slide was ~1 mm off focus); the AI calls far-out-of-focus spheres filament/blob, so pure spheres read 62-89 % atomised; spray check: chi <= 20 would move D32 ~55 -> ~36 um (not yet a result); deck now 20 slides with a draft sizer 3.0.0 plan; rig ask: big-bead through-focus series). 2026-10-15 ~21:00 (Mac: pulled the home PC's step 2 and merged STATUS; step 3 DONE on the LaCie: bead results + a boxed PNG per capture; the falling beads' error is defocus (they read like static beads 2.5 mm off focus), not the edge). 2026-10-15 late evening (Mac: bead_calibration 1.1.0 written and run on the copied stills, preliminary: every size reads ~8.6 % large at focus (a scale error?, 9.21 um/px fits), the in-focus rule counts beads over 9-15 mm of depth while size holds over 1-2.5 mm; a boxed PNG per capture is written when the LaCie is back; deck of what was tried). 2026-10-15 19:10 (home PC: step 2 DONE 18:19-19:05, all five pours through the AI, no failures; falling beads read high, measured ~= 0.94 x nominal + 22 um; LaCie free to go back to the Mac for step 3; merged with the Mac's at 20:45). 2026-10-15 evening (Mac: TONIGHT's steps rewritten as a hand-off: home PC runs the AI on the five pours only (Claude there; commands in Next steps); Cd analysed: 0.5 mm 0.844, 0.8 mm 0.814, 1.2 mm 0.527 = the insert passes ~35% less gas than a clean bore, not written to the Cd table; the static bead photos are crowded / full of specks, so bead_calibration 1.1.0 (sparse regions only, a boxed PNG per capture) is being written). 2026-10-15 (lab PC: falling beads: only ~10% of frames have beads, kept at stride 10 with trimmed cines; today is Cd tests + bead calibration only, no silicone; spray runs postponed, the three Cd tests DONE 11:12-11:34 (`Calibration/Orifice Cd/2026/10/15/`, not yet analysed); run sheet now 36 bead rows: ONE capture per single-size sandwich at focus (no patches or bg: the slide cannot move sideways, background from the photo itself), then the mixed through-focus series ±8 mm (optional; the only depth-of-field data), then the falling beads; pulled 057a0f3 at 07:52 and GUI_Clean restarted at 07:52 on it; python-pptx 1.0.2 confirmed; the Portenta switch filter is still recorded as not flashed). 2026-10-14 (Mac: throughput is now the default: response-surface goals in-band droplets per second x3 + atomised fraction x1, Settings size band 20-60 um; Ben's new tasks added to the open list in `docs/notes/2026-10-14_plan_for_wednesday.md`; the CCD run-33 bubbler stall false trip is resolved (Ben: "I didn't plug it in"); the silicone is one part, not curing). 2026-10-13 (Mac: CCD follow-up plan approved, `docs/notes/2026-10-13_CCD_followup_plan.md`, 12 phases; phase 1 done: app bugs 3 and 6 fixed, atomised fraction / flow relabelled "by area"; phase 2 done: "no spray" runs (atomised < 2%) have size and steadiness blanked; phase 3 done: gas regimes (pressure-limited runs left out of the surfaces by default, own section), goals used/dropped and best observed runs in Best settings; F2/H1 checks done (window drops in 8 runs; volume ranks like area); liquid stage 2.3.0 built (window drops masked, volume) and being re-run on the Mac for the CCD day, old outputs archived to _liquid2.2.0/; phase 4 done: band-count response (in-focus droplets per frame, 30-50 um, Settings); phase 5 done: GUI_Clean live gas regime + run_summary gas fields (rig check pending); phase 6 done: orifice on a log scale, fitted span when runs are left out; master_log gains a Mean Diameter column and the 33 CCD rows now hold D32, mean and atomised % (atomised % updated to liquid 2.3.0 at 15:30, backup kept); liquid 2.3.0 re-run done 33/33; phase 8 done (rate: count is a concentration, gas speeds the liquid up, cines cannot give velocity; docs/notes/2026-10-13_droplet_rate_investigation.md); phase 9 done (CCD re-analysed: in the flow-controlled region atomised fraction = gas + orifice only, predicted R2 0.89; best ~10,700 sccm on 1.2 mm; the 35% runs are pressure-limited 0.5 mm; docs/notes/2026-10-13_CCD_reanalysis.md); three RSM bugs found and fixed in the re-analysis (goal gate on the wrong model, strengthen runs outside the fitted span, free factors reported as edge optima); opt-in mass-balance rate responses added (`rate`, `rate_band`: droplets produced per second, all sizes / in the band); velocity capture plan written: `docs/VELOCITY_CAPTURE_PLAN.md` (exposure series ~20 min, then a 15-capture calibration set, ~3.5 h, on a narrow strip at ~10 kfps, 1 us; PCC check of rows-vs-width first). Earlier 2026-10-13, home PC: CCD batch finished 33/33 at 2.2.0 and analysed once; the 0.5 mm block was gas-starved at a ~9.5 barA ceiling (see Recent changes and docs/notes/2026-10-13_CCD_day_explained.md); app bugs 3 (stale run list) and 6 (no atomised liquid flow on Python 3.9) found. 2026-10-12 home PC: python-pptx 1.0.2 installed in the Detectron env; CCD day checked on the LaCie: 33/33 cines + summaries, detects as a complete 4-factor CCF, quick self-test READY; batch not started. Lab PC: 33-run CCD day captured, all cines saved, run 33 valid (the GUI's stall check false-tripped; label removed); GUI_Clean camera save hardened after a lost auto-trigger capture (untried on the rig); STATUS commit refs fixed, tracked __pycache__ removed, front limit switch tested on the rig, emoji removed from GUI_Clean console messages, switch noise filter in firmware (needs flashing), GUI_Clean SCCM ramp + bubbler starts with Start Experiment (untried on the rig); Mac: CCD plan complete, Phase 7 committed 2ebc9f0; Mac light-mode theme fix; batch bugs 1-2, goal-ramp bug, feed floor 2,000 steps/s; mean diameter now a headline response and the default size goal; GUI_Clean auto-trigger at end of test and pressure cut-off (both untried on the rig); GUI_Clean review fixes + front limit switch firmware (committed 58f1b94; firmware flashed and switch-tested on the lab rig 2026-10-12, all passed); next is the 33-run CCD day).** This is the live state of the work. Claude keeps it current
(see "How this file is maintained" at the bottom). History, evidence and full reasoning are in
`docs/archive/HANDOFF_real_data_pipeline_LEGACY.md` (frozen 2026-10-07, newest section first).

## The goal, in one paragraph

A defined, reproducible measurement of effervescent silicone atomisation from shadowgraph video
that can **rank runs in a Taguchi parameter study** (PhD, high-definition silicone printing). The
ML model exists to make that measurement more accurate; it is not the goal. Do not drift into
process diagnosis or model-building for its own sake.

## Where we are right now

- **27 replicate runs (9 conditions x 3 repeats, captured 2026-10-05) are measured (2.1.0) and
  analysed** (2026-10-07, Mac, 63 s). Output: `/Volumes/LaCie/Experiments/Taguchi/9x3 Taguchi Repeats/`
  (`taguchi_report.md`, `taguchi_analysis.xlsx`, `figures/`, `csv/`, `odd/`). Error term = pure
  error, 18 dof.
- **Atomised fraction:** gas flow dominates (89%; 5.2 / 13.6 / 16.9 % at 3000 / 6000 / 9000 sccm).
  Silicone (4000 sps best) and RPM (300 best) small but significant. Lack of fit p = 0.020
  (interactions real but 0.6% of variation). Same picture as the first L9, RPM now resolved.
- **D32:** all three factors significant now that replicates exist: RPM 47.5% (81.4 / 85.0 / 86.7 um
  at 300 / 600 / 900), gas 21% (6000 best), silicone 15% (4000 best). Total spread ~5 um on ~84
  (~6%); pure-error SD 1.5 um. Robust to enforcing the 200 um ceiling (checked 2026-10-07,
  read-only: same ranking and significance, D32 ~2 um lower).
- **Caveat found in review: RPM is fully confounded with time of day.** Conditions were run in
  order T1..T9 with replicates back-to-back, so 300 rpm = 09:04-10:46, 600 = 10:55-11:55,
  900 = 12:02-12:57. Back-to-back replicates also make pure error a repeatability estimate, so
  p-values are optimistic. The 10/01 L9 had the same order. **Checked 2026-10-07:** fluid is
  single-part EcoFlex 00-30 (no curing), lab held 25 degC, and the per-run `background_median.tiff`
  shows no drift in illumination or window dirt across the day (r = +0.07 with time). D32 moves in
  steps at the RPM changes, not as a gradual drift, and within the 300 rpm block (1 h 40) it tracks
  gas only. So RPM is now the likeliest explanation, but only a randomised test can rule out
  mechanical drift.
- **Sizer 2.2.0 (sharpness rule) built and compared** (commit `7ebaa1a`; opt-in at first, the
  default everywhere since 2026-10-08). All 27 re-measured with it; their 2.1.0 results were MOVED intact to
  `<run>/shadowgraph/analysis/_sizer2.1.0/`, so the run folders now hold 2.2.0. Analysis:
  `Taguchi/9x3 Taguchi Repeats (sizer 2.2.0)/` with `comparison_2.1.0_vs_2.2.0.md` and
  `sharpness_review/` (old-vs-new frames, zoomed tiles, size-matched random sheets per gas flow).
  - Atomised fraction identical (0 difference), as designed. D32 -31% (to 55-64 um), mean -18%,
    median -12%, D90 -24%; droplets >= 100 um almost all moved out of focus.
  - **The D32 factor picture flips:** 2.1.0 RPM 47.5% / gas 21%; 2.2.0 gas 70% / RPM 13% /
    silicone 13%. Same for mean and D90.
  - **That is the predicted warning sign.** The share moved rises with gas flow: 15.7 / 17.9 /
    20.5% of in-focus droplets, and 36 / 42 / 53% of those >= 50 um, at 3000 / 6000 / 9000 sccm.
    The rule removes more at higher gas, which manufactures much of the new gas effect on D32.
  - Ben's review of the sheets (2026-10-07): the rule "looks like it's doing a decent job".
  - **Gradient diagnosed (2026-10-07, read-only, 7,955 droplets >= 50 um, 10 frames/run):**
    - Real at matched size: 50-60 um moved 16 / 22 / 29%, 60-70 um 23 / 36 / 41%; flat >= 100 um.
    - **Not crowding:** neighbours in the search ring (5-7%) and merged components (3-4%) are rare
      and don't rise with gas; removing neighbour pixels from extinction_conc changes nothing.
    - **It is shape:** at matched size droplets are less round at higher gas (elongation >= 1.3:
      17 / 28 / 32% at 50-70 um). Long axes are mostly randomly oriented, with a weak vertical
      excess rising with gas (32 -> 37%), so motion blur is at most a minor part. Mainly
      deformed, unrelaxed fragments: a real image property, so the rule is doing what it was built
      to do.
    - **But ~2/3 of the 2.2.0 gas effect on D32 is selection:** applying the 3000 sccm keep-rates
      to every gas level, the 9000 - 3000 difference shrinks from -5.6 um to -1.8 um (2.1.0: -2.5).
      2.2.0 D32 is "D32 of the round, sharp droplets", and that subset shrinks faster than the
      population as gas rises.
- **Spray pulsing (2026-10-07, read-only, per-frame series at stride 10 = 39 Hz, all 27 runs):**
  - Strong **slow pulsing at 3000 sccm** (period ~3 s, ~0.35 Hz): 43% of droplet-count variance
    below 2 Hz vs 13-16% at 6000 / 9000 (white noise ~10%); 28% vs ~10% for atomised fraction.
    Tracks GLR (r = -0.7 with log GLR); strongest at T7 / T4 (GLR 0.14 / 0.19). RPM adds a
    little (p = 0.004); silicone flow none for droplet count.
  - Upstream pressure oscillates at ~0.2-0.6 Hz (CV 2-9%) in EVERY run while gas flow holds to
    ~1%, but only the low-GLR spray follows it (droplets vs pressure r = 0.80 at T7, 0.33 at T6).
    Origin of the pressure swing unknown (atomiser / liquid line); low-GLR sprays are sensitive to
    it. Consistent with slug-like internal flow at low GLR; not proven.
  - Written up in `Taguchi/9x3 Taguchi Repeats/pulsing/` (`pulsing_report.md`, two figures, CSVs,
    the script); a summary section was appended to both 9x3 `taguchi_report.md` files (re-running
    Analyse rewrites those and drops the section; the pulsing folder stays).
  - No sign of the bubbler rotation frequency (5 / 10 / 15 Hz) in 0.1-19.5 Hz. Liquid area is very
    bursty (CV > 1) but uncorrelated frame to frame: individual slugs pass in < 25 ms. Anything
    above 19.5 Hz needs full-rate (390 fps) analysis of the cines.
  - **Consequence:** stride-10 frames are NOT independent at low GLR (droplet-count lag-1 r = 0.62
    at 3000 sccm, 0.29 at 6000, 0.18 at 9000; still ~0.15 at 410 ms at 3000). Per-run bootstrap CIs
    (ci_stride 1) are too narrow there. The Taguchi ANOVA uses repeat scatter, so it is unaffected.
- To analyse 2.1.0 again, the `_sizer2.1.0` folders must be moved back first (the app reads only
  `droplets_0.30` / `liquid_0.30`).
- Launch the app on the Mac:
  `cd /Users/benschofield/Documents/GitHub/HPATR && /Users/benschofield/anaconda3/envs/phantom/bin/python3 -m src.ai.Taguchi_Analysis_UI`

## Lab captures from 2026-10-08 (GUI changed)

- **The GUI's AI chain now measures at sizer 2.2.0 and runs the classical liquid stage**, so each
  capture finishes with `droplets_0.30/` + `liquid_0.30/` (both 2.2.0), ready for the app's
  Analyse with "Use their existing results". The Extremes tab shows the classical renders (un-atomised
  liquid filled orange) for the D32 and atomised extremes; the headline and master-log atomised
  fraction are the classical one.
- **Standard capture settings** (390 fps, 4 us, 2048x1152, 0 / 13 s, AI stride 10, AI on) are the GUI
  defaults and are checked at Start Experiment.
- These match the 10/05 run folders as they stand (2.2.0) and `9x3 Taguchi Repeats (sizer 2.2.0)/`.
- **The Taguchi app's batch also measures at 2.2.0 by default now** (`RunSettings.sharpness_rule`,
  passed to both stages; a job saved before 2026-10-08 resumes at 2.1.0). So GUI captures and app
  batches agree.
- **2.2.0 is the default EVERYWHERE since 2026-10-08, including a bare `measure_run.py` /
  `classical_liquid.py` / `process_capture.py` / `batch_runs.py` call** (Ben: "using 2.2 for good
  now, might go back"). Every script takes `--no-sharpness-rule` for 2.1.0, bit-identical to
  before. Callers pass the flag **explicitly both ways** (`process_capture` -> both child scripts,
  `batch_runs`, the app's `classical_cmd`), so a resumed pre-10-08 app job still runs at 2.1.0;
  `test_sizer_version_is_explicit_both_ways` guards that. Verified on Trial_CINE: default -> 2.2.0,
  D32 56.19 um; `--no-sharpness-rule` -> 2.1.0, 81.58 um (matches the recorded 81.59); 57,654
  droplets both ways.
- A new day is a new block: include 1-2 repeats of 10/05 conditions to measure the day offset.

## Response-surface (CCD) support + richer outputs (plan approved 2026-10-11)

Plan: `~/.claude/plans/purring-bubbling-raccoon.md` (7 phases, each ending in a stop). Extends the
Taguchi app with a Response surface tab (detect or build a CCD, analyse, validate any run, recommend
runs), richer figures/data for both analyses, and a PowerPoint deck. First real-data trial: the
9x3 as a gas x feed surface (Phase 4b).

- **Phase 1 done (2026-10-11), committed c43df2f:** `run_metrics.py`, the shared per-run data layer (size
  distribution incl. Dv10/50/90 and span; steadiness and pulsing incl. spectrum and slow share;
  pressure inside the camera window; un-atomised pieces; sizer and data quality incl. static spots;
  atomised liquid flow; capture time), cached per run in `<output>/cache/run_metrics/`. Five new
  analysed responses in the Taguchi analysis: **Dv50, atomised liquid flow, frames below half the
  mean count, lag-1 correlation, peak pressure** (42 factor tests now, BH-corrected). Matches the
  2026-10-07 pulsing analysis to 4 dp on run 124632. Real 9x3 publishes in ~80 s (first run fills
  the cache). Tests: `tests/test_run_metrics.py` (9).
- **Practice folder (2026-10-11), for all development/testing of this plan:**
  `/Volumes/LaCie/Experiments/Taguchi/Claude Experiments/Practice Folder/`. Holds `2026/10/05/<27
  runs>` (date levels kept, the app reads the date from the path) with everything except
  `raw/CINE/` and `raw/frames/` (3.4 GB; checksums match the originals), a
  `9x3 Taguchi Repeats (reference copy)/` of the published output, and `output/` for practice
  publishes. All 27 load as analysable, 0 runnable (no .cine), so the batch cannot re-measure them.
  Point test publishes here, never at `2026/10/05` or `9x3 Taguchi Repeats`.
- **Phase 2 done (2026-10-11), committed 5649800, awaiting Ben's review:** richer Taguchi outputs + deck.
  New `figures_extra.py` (size distributions + cumulative volume, Dv10-90 per run, per-run time
  series of droplets/frame with pressure and of liquid area, spectra, steadiness by condition,
  drift, replicates with t CIs, interaction plots with the L9 aliasing caveat, residual
  diagnostics, response correlations, liquid pieces, data quality, image galleries of each run's
  lowest/highest-atomised frames), `deck.py` -> `taguchi_deck.pptx` (12-13 slides, titles are
  takeaways computed from the numbers; drift slide only if a drift survives BH), 9 new workbook
  sheets / CSVs, matching report sections; `stats.main_effects_fit / drift / drifts /
  order_confounding / t_quantile`. `python-pptx` 1.0.2 installed in the Mac `phantom` env
  (Windows env not yet; without it everything else publishes and the report says why).
  Published from the practice folder to `Practice Folder/output/9x3 phase 2/` (82 s cached).
  Tests: `test_figures_extra.py` (15), `test_deck.py` (6).
  - **Phase 1 bug fixed:** Dv10/50/90 interpolated between sorted droplets, which on the pixel
    lattice always returns a lattice value: 8 distinct Dv50s in 27 runs, identical replicates,
    gas p = 5e-15. Now grouped-data interpolation across lattice cells (26 distinct; replicates
    differ by 0.2-1 um). `run_metrics.SCHEMA` 2 invalidates old caches.
  - **Drift is a light check, by Ben's call** (climate-controlled lab): kept in the report and
    workbook (none found on the 9x3: all p > 0.7), out of the headline findings and the deck
    unless a drift survives BH. RPM-vs-run-order (r = +0.91) is one caveat line.
  - **Deck has every figure (2026-10-11, after Ben's review):** 42 slides on the 9x3. Each figure slide:
    takeaway title + description with numbers from the tables + speaker notes; tall figures
    (time series, replicates, model checks) redrawn in slide-sized parts into `figures/slides/`;
    galleries as an appendix. Descriptions fall back to a plain one when numbers are missing.
  - **Deck styled like Ben's hand-made decks (2026-10-11):** built on `assets/deck_template.pptx` (his
    9x3 `taguchi_results.pptx` with its slides removed: "Atomisation Ink" theme, navy title slide,
    grey-blue cards, orange/teal/purple/yellow accents; figure factor colours now match). Each figure
    slide: takeaway title, description card, and a "Terms" card defining every statistic it uses
    (beside the figure when that leaves it bigger). Conditions are named with their levels and the
    factor driving them. Pulsing figure is 2 x 2. Slide order unchanged (Ben: no other layout changes).
  - **For Phase 5 (Ben, 2026-10-11):** `rsm_deck.pptx` must carry the 3D response surfaces (with design
    points), contour maps and profiler, every figure with a takeaway + description like the Taguchi deck.
    First real ones in Phase 4b (9x3 gas x feed).
  - **For Phase 3b:** the builder must offer half-fraction corners (resolution V) for 5 factors
    (CCF full 47 runs -> ~31). Detection and the model are already any-k in the plan.
  - **Splash is not a BG_FRAMES problem (checked 2026-10-11, Ben confirmed it is a splash):** it
    lands mid-capture and darkens (113007: clean for the first ~25%, then 0.74 -> 0.44 of its
    surround), so no static median can match every frame; more frames would not help. Impact
    nil: T on it stays > 0.86 vs the classical seed 0.70, and model detections on it are below the
    chance rate for that area (113007: 168 vs ~370 expected). Leave BG_FRAMES = 40; wipe the
    window between runs. A rolling (time-local) background is the fix if splashes get bigger.
  - **Data-quality finding:** 113007, 124030 (and mildly 120201) have a large defocused dark spot
    in the median background (~1700 px, left of centre): most likely a silicone splash on the
    window for most of that capture.

- **Phase 2 committed (5649800).**
- **Phase 3a done (2026-10-11), committed 3846548, awaiting review:** `rsm_detect.py` detects the
  response-surface design from the run folders alone (no sheet): varying factors + held-fixed list;
  design levels (uneven allowed: DESIGN coding classifies, REAL coding fits, 1.2 mm -> +0.08); special
  values that only occur with every other factor at centre (symmetric pair beyond the levels = axial,
  alpha estimated; lone inside = off-grid CHECK, e.g. 0.8 mm; lone outside = OUTSIDE, e.g. 0 rpm);
  point types; repeats; type match (CCF / CCD-alpha with rotatable/spherical / Box-Behnken / 3^k /
  two-level + centres / regular fractions / orthogonal array / irregular) with missing and extra
  points; hard-to-change (block) factor = few value changes in time order, confounded with time;
  day blocks; within-block repeats as drift pairs; Notes ("CCD run 7 centre") vs point type and
  vs capture order; quadratic estimability (separately estimable terms, pure-error and LOF df,
  largest estimable hierarchical model with aliases). Editable `RsmDesign` (design.Design +
  validation runs + block factor), saved as `rsm_design.json`. Tests `test_rsm_detect.py` (14),
  including Ben's 33-run day (FAKE folders built from his run sheet; that day has not been run),
  a 3-factor CCF day with orifice blocks (future 3-factor sessions), and the real 10/05 (read-only:
  -> L9, Taguchi tab, RPM confounded with time). Priority: the 4-factor 33-run design, then 3-factor.
  **Ben's CCD plan is now 4 factors / 33 runs** (gas 7000-11000, feed 3000-5000, RPM 100-900,
  orifice 0.5/1.2/1.8, + 0 rpm control + 0.8 mm check; doc dated 2026-10-09), not the 3-factor
  22-run day the plan file assumed; detection is any-k so nothing changed, the tests use the 33.
  Comparing the detected design with a BUILT sheet moves to 3b (the sheet format is defined
  there; the built sheet gets its own file, not `rsm_design.json`).

- **Phase 3a committed (3846548).**
- **Phase 3b done (2026-10-11), committed 0b292ee, awaiting review:** `rsm_design.py`, the generic CCF
  run-sheet builder: 2-5 factors (built-in keys or workbook fields), real low/mid/high levels
  (uneven allowed), all corners or a half fraction (last factor = product of the others: res V for
  5 factors, 16+10+5 = 31 runs), optional block factor (outer blocks: corners opened and closed by
  the block factor's face point as start/end repeats; middle block: centres first, last and spread
  through the other faces), extras (inside a block's level -> inside that block, never first or
  last; off-grid -> after every block), a first run (pressure check: opens its block, block goes
  first), seeded randomisation within blocks, Notes "CCD run N <type>" that rsm_detect reads back,
  time estimate. Saved as `rsm_run_sheet.json` (load rebuilds from the plan and checks the rows),
  exported as run_sheet.xlsx/.csv/.md. `compare(sheet, detected)`: as planned / out of order /
  settings differ / not captured yet / not on the sheet (moved here from 3a). Ben's 33-run day
  regenerated block by block; built -> captured as fake folders -> detected closes the loop.
  Tests `test_rsm_design.py` (15) + mutation checks.
  - **Near-aliasing check added to estimability (rsm_detect):** rank alone said a 4-factor
    half-fraction CCF can fit the full quadratic (orifice's uneven middle breaks the aliasing by a
    hair); VIFs are ~850 on all six interactions vs <= 3 for the full CCF. Kept terms with VIF > 50
    are "nearly aliased"; `Estimability.usable` = full and none nearly aliased.
  - Ben's sheet exported for a look: `Practice Folder/output/CCD run sheet (4 factors, 33 runs)/`.
  - **`docs/RSM_GUIDE.md`** (Ben asked for a how-to in the GUI): step-by-step guide to planning,
    running and analysing a CCD, each builder field explained; the Phase 7 tab shows it in a Guide
    panel. Marks what is built and what is not. Keep it in step with the code.

- **Phase 3b committed (0b292ee).**
- **Phase 4 done (2026-10-11), committed c786e69, awaiting review:** the response-surface statistics.
  `rsm_stats.py` (numpy only): quadratic in real coding (axis factors full quadratic; nuisance factors
  linear or linear + square, no interactions; optional centred time term); OLS with SE / t / p,
  R^2 / adjusted / predicted (PRESS); 95% CI and PI; lack of fit vs pure error; backward elimination
  with hierarchy, highest order first (nuisance terms kept); VIFs and nuisance-vs-axis correlations;
  BH q over every full-model term test of every response; time trends; Derringer-Suich desirability
  (max / min / target ramps, hard constraints) and a grid + local search optimum, continuous or at
  settable levels, with edge flags. `rsm_responses.py`: loads a detected design's runs through the
  new shared `stats.load_measured_run` (the Taguchi analysis now uses it too, so both read runs
  identically; mixed sizer versions refuse), fits every response (full + reduced), drift (centres vs
  time, block repeat pairs as z of pure error, residual trend), predicts every run outside the fit
  with its PI (pass / fail, extrapolation flagged) and finds the optimum. Default goals: atomised
  fraction max, atomised liquid flow max, count CV min, D32 min (ramps = observed range).
  Tests: `test_rsm_stats.py` (14: independent QR/scipy fit, explicit leave-one-out PRESS, the CCD
  plan's lack-of-fit formula, PI coverage by simulation, hierarchy over 100 noise draws, planted
  optima / constraints / settable levels), `test_rsm_responses.py` (8: measured fake 3-factor CCF day
  recovers its planted surface and optimum, bad validation run fails; fake 9x3 as gas x feed with RPM
  as nuisance = 8 terms, 18 pure-error df, 1 lack-of-fit df; real 9x3 RPM vs g*f r = -0.61) +
  mutation checks. No real-data analysis yet: that is Phase 4b.
  - **Open:** the rig's rated pressure limit (for the peak-pressure constraint) is not recorded
    anywhere; ask Ben.

- **Phase 4 committed (c786e69).** Rig limits (Ben, 2026-10-11): gas flow max 12,000 sccm (now enforced by
  the builder, `rsm_design.RIG_LIMITS`); there is NO rated pressure limit, so peak pressure is reported,
  never a constraint.
- **Phase 4b done (2026-10-11), committed 7c2037b, awaiting review:** the 9x3 as a gas x feed surface, run the way
  the tab's Analyse button will (select runs -> detect -> models -> `rsm_publish.publish`), into
  `Practice Folder/output/9x3 response surface (gas x feed)/` (36 s). Built for it (the plan's Phase 5
  publish, at 2-axis scope): `rsm_figures.py` (contour maps per held RPM, 3D surfaces, profiler with
  CI/PI bands, desirability with sweet spot, fit checks, model comparison, validation),
  `rsm_report.py` (tables shared by report / workbook / CSV; verdicts; stationary points by kind;
  trade-offs at the optimum; interaction agreement across models; simple next runs),
  `rsm_publish.py` (isolated steps, shared size / steadiness / quality extras, provenance), `rsm_deck.py`
  (styled like the Taguchi deck, Terms cards, takeaway titles, shared figures as an appendix),
  `rsm_stats.stationary`. Tests `test_rsm_publish.py` (8) + a workbook-field factor test (any
  run_summary.xlsx field works as a factor, keyed `wb:<field>`).
  **Findings on the real 9x3 (sizer 2.2.0):** model (a) gas x feed + RPM nuisance fits well (atomised
  fraction R^2 0.99, predicted 0.98, no lack of fit; D32 has lack of fit p = 0.039); model (b) without RPM
  shows lack of fit for nearly every response, so RPM is not noise. The gas x feed interaction flips
  between the models (atomised -0.89 p 0.005 vs +0.46 ns; D32 +0.11 ns vs -1.19 p 0.003): not separated
  from RPM (r = -0.61), as predicted. Surfaces are mostly saddles (gas and feed curve opposite ways).
  Best overall (default goals: atomised up, atomised flow up, count CV down, D32 down) ~8,700 sccm,
  8,000 steps/s (feed edge), best at 300 rpm (D 0.91 vs 0.80 at 600, 0.72 at 900); the feed edge is
  throughput's pull: atomised fraction alone favours low feed. Phase 5 generalises to k axis factors
  (pairs, holds) and the CCD day; Phase 6 is the real recommender.

- **Phase 4b committed (7c2037b).**
- **Phase 5 done (2026-10-11), committed 9c8b8d8, awaiting review:** the response-surface outputs generalised to
  3-5 factors and the CCD day. `rsm_figures.MapLayout` / `map_layout()`: the CCD plan's layout by default
  (gas x feed across/up, one panel per block factor = orifice, one figure per next factor = RPM, any
  fifth held at the best setting), overridable; all-pairs maps; drift figure; desirability maps per
  figure level. Report / deck: every map file, controls vs centres (0 rpm), best setting at settable
  levels (orifice inserts) driving the next runs, stationary point along the curving factors when one is
  a straight line (ridge), weak surfaces (predicted R^2 < 0.5) said plainly and kept out of the
  best-settings search, numbers formatted 10,900 not 1.09e+04, natural condition order (C2 before C10).
  Shared appendix now has everything non-Taguchi-specific (every run, GLR, size spread by count and
  volume, distributions, percentiles, steadiness, spectra, time series, liquid area, replicates,
  correlations, pieces, quality, galleries); the shared figures group a CCD's runs by SETTING
  (Notes "CCD run 7" are run numbers, not Taguchi trials: before, 9 runs showed as conflicts). Every
  surface slide has "What it shows" + a "How to read it" guide (Ben). `deck._Deck.figure` takes an
  optional how-to-read text. `docs/RSM_GUIDE.md` updated.
  **Simulated day** for review: `Practice Folder/SIMULATED CCD day (fake data, not real runs)/` (README
  says so; `tests/fakes.make_measured_ccd_day` + `ccd_truth`), analysed to `Practice Folder/output/
  SIMULATED CCD day (4 factors, 33 runs)/`: finds the planted gas peak (~10,500 vs planted ~10,800 sccm),
  orifice ~1.6 mm, the 0 rpm control at -6.9 centre SDs (planted -2 points), the 0.8 mm check inside its
  PI. Tests `test_rsm_ccd.py` (8). The 9x3 trial re-published with the new outputs.

- **Phase 5 committed (9c8b8d8).**
- **Phase 6 done (2026-10-11), committed b4d4baa, awaiting review:** `rsm_recommend.py`, the next-run recommender.
  confirm (best setting x3 + centre anchor, snapped to the rig's steps / existing inserts / limits) always;
  steepest (path of steepest ascent of the desirability from the best setting, outward on edge factors,
  stops at the rig limit) and new_ccd (same-size CCF shifted so the best point is inside, built by
  rsm_design, rig limits applied; nuisance factors held where the score is highest) when the optimum is on
  an edge or nothing curves; augment (D-optimal greedy on the model's terms over a runnable candidate
  grid, the first next to a failed check / validation run) when the model is weak; new_level (next insert
  size by the same ratio) only when the CCD plan's three conditions hold. Every run predicted with its 95%
  PI, extrapolation flagged; factors taken beyond the tested range with no recorded rig limit (RPM, feed)
  are named for checking. Wired into the publish: report section, workbook sheets, one deck slide per
  recommendation, `next_runs.xlsx/.csv/.md` and `next CCD/run_sheet.*`; the Phase 4b placeholder next
  runs are gone. Tests `test_rsm_recommend.py` (10, planted surfaces) + mutation checks (rig clamp, check
  condition, D-optimal pick caught; the edge-or-flat trigger is redundant with the direction check).
  On the real 9x3: confirm 8,700 sccm / 8,000 steps/s / 300 rpm (atomised 17.0%, PI 15.4-18.6); steepest
  ascent pushes feed up to 12,000 steps/s (extrapolated); new CCD gas 4,400-10,400 x feed 6,000-10,000
  at 300 rpm; 4 runs to fix D32's lack of fit.
  **Rig limits (Ben, 2026-10-11): gas 12,000 sccm, bubbler 1,000 rpm (0 allowed: the control), feed 2,000 to about
  12,000 steps/s**, in `rsm_design.RIG_LIMITS`: the builder refuses levels beyond them and the recommender
  stops there. No rated pressure limit.

- **Phase 6 committed (b4d4baa).**
- **Phase 7 committed (2ebc9f0); the CCD plan is complete.** Ben to try it himself on the 9x3 practice copy: `tab_rsm.py`, the
  **Response surface tab** (window now "Experiment Analysis"; QSettings app name unchanged so remembered
  folders survive). Sub-tabs: Design (banner, editable run table: use, point type, block, factor levels,
  validation tick, built-sheet status, Notes check; findings; block factor; saved to rsm_design.json),
  Model (factor roles: surface / nuisance slope / nuisance slope+curve / left out; settable levels;
  goals with blank ramps = observed range; time term; comparison fit; saved to rsm_model.json; an L9
  defaults to the 9x3 gas x feed trial, a CCD to all-surface with the orifice sizes seen), Analyse and
  next runs (thread, open report / deck / next runs / folder, recommendations listed), Build a run
  sheet (table + options + extras text, Load the 33-run example, Build, Export to the output folder),
  Guide (docs/RSM_GUIDE.md, now with "Using the app" and a 9x3 practice walkthrough).
  `rsm_responses.resolve_goals` (dict goals, blank ramp = observed). Tests `test_tab_rsm.py` (9, headless,
  incl. a real Analyse on the simulated CCD day). Verified headless on the real 9x3 copy: detects the
  L9, defaults to the trial, Analyse writes everything, 4 recommendations listed.
  - **GUI_Clean**: the Start Experiment standard check no longer flags "Run AI analysis: off" (the AI runs
    afterwards in the app). "Use standard settings" no longer re-ticks the AI box either (line deleted 2026-10-11).
  - Settings tab unchanged: no pressure limit to set (there is none), desirability goals live on the
    Model page, bin settings were already there.
  - `docs/IMAGING_PIPELINE_REFERENCE.md` §9 updated (extra responses, figures, deck) and §9b added
    (response-surface stage).

## Next steps, in order

**NOW (2026-10-17 evening): sizer 3.1.0 is ACCEPTED and the CCD day (10-12) at 3.1.0 is the reference** (Ben):
Phase 6 passed; the Taguchi (10-05) and L9 (10-01) days are NOT re-measured (Phase 7 dropped); sizes above 155.8 µm
are reported. Comparison deck https://claude.ai/artifact/3LjGxwXAm9PjMYWmcYQUTE (27 slides; PDF, editable PPTX,
per-run xlsx, frames: `Experiments/Taguchi/CCD/CCD sizer 3.1.0 remeasure 17-10-2026/`).

**URGENT (2026-10-26): back up the LaCie, on the home PC** (`docs/notes/2026-10-26_lacie_backup.md`).
- Now: everything except the run `.cine` and frames (~520 GB) to Ben's 1 TB drive. Check its free space first.
- Then: a 16–20 TB desktop drive for the full mirror, plus university storage.

Next, in order:
1. **Phase 8: the docs DONE 2026-10-17** (IMAGING_PIPELINE_REFERENCE §4.1, §6.4, §7.1, §9c, §9d new; definitions.md's 3.1.0 section; DROPLET_MEASUREMENT_METHOD status; BEAD_CALIBRATION). Left as is on purpose: the optics profile's calibration `status` text still says sizes beyond the beads are provisional, because the calibration hash covers that block and editing it would flag every CCD run for re-measuring.
2. **Before the next test day: the app's batch runs several runs at a time** (one at a time took ~4 h for 33 runs;
   four at a time ~2 h). App code only (worker.py / jobstate.py / the Batch tab).
3. **Commit and push** the uncommitted app fixes (the classical extreme-image count 1-8, the ETA for re-measure
   batches) and the docs, when Ben says. The lab PC pulls before its next capture.
4. **The to-do list, `docs/notes/2026-10-17_todo.md`:** 5a rescue small droplets the AI missed, 5b split touching
   pairs, 5c fine-tune the AI only if those fall short; 6 partly in-focus ligaments; 7 frame-size changes; 7b speed
   weighting (needs the velocity capture); the liquid stage reusing the sizing verdicts; droplets/s needing more
   repeats or longer captures (CCD centre repeats CV 21%).
   Separate part (2026-10-22): 9 droplet transport model (from 2026-10-23), 10 droplet-speed capture (next week), 11 optional nozzle CFD.
   Plan: `Flow Visualisation/PLAN.md` (no code until Ben approves a phase; Phase 0 done 2026-10-23; Phase 1 BUILT 2026-10-23, awaiting Ben's review; results in PLAN.md's 'Phase 1 status', commands in `Flow Visualisation/README.md`, deck https://claude.ai/artifact/2aRQfYQT4WvsE9RvpsQ9wh).
   Phase 2: OpenFOAM on the Mac (installed 2026-10-23; FluidX3D dropped); the first box case waits for Ben's go.
   Phase 3a (droplets through Ben's CfdOF baseline, PLAN.md): Parts A–D done 2026-10-25 (tracker proof; the tool, `run_droplets.py`; figures, report, checks; the baseline run and the snapshot check: one snapshot is enough, the mesh matters more; a sweep / `--compare` for several flows). Fix (a) dropped; (b) with plan 1. Next: Phase 2a, the scripted flow builder (orifice from code, near-wall layer, grid check), planned in PLAN.md 2026-10-25, awaiting Ben's go and answers; Ben makes the new CAD this week (Part A, the CfdOF scripting spike, does not need it).
   Learning CFD: FreeCAD + CfdOF installed; Ben's guide `Flow Visualisation/cfdof/CFDOF_GUIDE.md`. His real-chamber STEP v2 (2026-10-24) runs; guide Part 5 walks him through it (spray hole kept at 1.0 mm, Ben). Work log of what was tried and why: `Flow Visualisation/cfdof/CFD_LOG.md`.
   **Nozzle CFD (item 11, 2026-11-08): 2D wedge rehearsed** (CFD_LOG.md section 9; example domain https://claude.ai/artifact/JgfQEQKsi6fua2yZBMs2Cn). Ben draws the half-section in Fusion as one closed outline on XY (axis on X), extrudes it 1 mm, STEP. Found: the block must be ≥ 4 coarsest cells thick (1 mm block, 0.25 mm cells); the face can touch the axis; CfdOF's 2D wedge makes the cut faces `symmetry`, which wrecks the jet, so they must be converted to OpenFOAM `wedge` patches after CfdOF writes the case (then a proper round jet). **Guide written 2026-11-08: `Flow Visualisation/cfdof/NOZZLE_WEDGE_GUIDE.md` (Part 9), for Ben to click through** (no script, his choice): Fusion sketch with parameters, FreeCAD/CfdOF setup, the run as CfdOF writes it, the by-hand wedge fix (`cfdof/wedge/` dicts + foamDictionary), the solve, ParaView comparison, mesh check (all cells halved: within 1–4 % to 50 D; the fine mesh misbehaves past ~70 D near the outlet, so compare designs inside 50 D) and domain check (×1.5: within 0.4 %). All rehearsed headless exactly as written.
   **Phase 7 capture (2026-11-02): Ben clicks guide Part 8** (two push designs, Stream 10 mm vs Gentle 40 mm, 30 L/min, capture 10 mm opposite, 44 mm port sealed; the capture feeds an AJP), solves each on the charger (~45 min), then runs `settings/droplets_carrier_stream.yaml` (~1 h); Claude then probes the flows as guide 7.9 did.
   **Chamber v2 (2026-10-26): Ben clicks guide Part 7** (the refined CAD, bore 1.11 mm (kept from the air version; 1.09 is nitrogen's equivalent), inlet 1.426e-4 m³/s (nitrogen), the final mesh, solve 2,000 its ~35 min on the proper charger), then runs the check `settings/droplets_chamber_v2.yaml`. His case is the reference for the staged variants (CFD_LOG.md section 8: the hole while spraying, redone with the series model; inlet turbulence 20 %; realizable k-epsilon; the grid check; atomiser layers; the liquid's push), and the template Phase 2a's script must reproduce.
   Parked (2026-10-26): CFD of silicone building up on the exit lip (mainly splashes, likely microbubbles bursting at the edge). The reasoning, approach, costs and cheaper tests are in PLAN.md 'Parked (2026-10-26)'. Not started; Ben may pick it up later.
5. **Rig:** clean the window between runs (23 drops in 15 CCD runs); the 300 µm pinhole (week of 2026-10-19) with
   its holder and rail scale; the 1.2 mm insert (cleaned 10-22, still Cd 0.547; pin-gauge the bore from both ends, then re-run its Cd:
   `docs/notes/2026-10-26_cd_1.2_rerun_run_sheet.csv`); the velocity exposure series; the PS20 reticle (arrived 2026-11-04).

**TONIGHT 2026-10-15: analyse the calibration day. ONE LaCie, so in turn: Mac (done) -> home PC (AI on the pours) -> Mac.**
What was captured (all on the LaCie):
- `Calibration/Orifice Cd/2026/10/15/`: 3 Cd tests, 1.2 (111209), 0.8 (112250), 0.5 mm (113124). ANALYSED (below).
- `Calibration/Imaging Work/2026/10/15/`: 36 GUI runs, 1 s each (one 1.15 GB cine + run_summary, all checked):
  - 130707-133119: `BEAD 155.8 / 98.1 / 76.39 / 56.28 / 37.36 z0`, one capture per single-size sandwich at focus;
  - 134805-143553: `BEAD mix z-8.00` ... `z+8.00` (31 captures), the mixed sandwich through focus (complete).
  - These static captures need NO AI (the AI chain's temporal-median background would contain the static beads).
    `bead_calibration.py` on the Mac averages 40 frames of each into one still and measures that.
- `Calibration/Imaging Work/2026/10/15/falling/`: five PCC pours, one per size, 390 fps: `BEAD fall 155.8 p1.cine`
  (2,697 frames), `98.1` (725), `76.39  p1` (two spaces; 3,025), `56.28` (1,491), `37.36` (1,535); 9,473 frames in all.
  Plus `BEAD blank bg.cine` (empty field, 276 frames): NOT for the AI; the Mac script reads it as the dust map.

**Step 1, Mac, DONE 2026-10-15 evening:** the Cd analysis (`Calibration/Orifice Cd/analysis/2026-10-15/`, nothing
written to the app's Cd table) and the 37 averaged bead stills copied to the Mac, so the code work there needs no drive.
- Cd: **0.5 mm 0.844** (5 choked steps), **0.8 mm 0.814** (2 choked; its subsonic steps agree, 0.81-0.83),
  **1.2 mm 0.527** (subsonic only, 0.48-0.54 at EVERY step, P0 1.03-1.64 barA against 1.02-1.29 expected). Not line loss
  (the 0.8 mm insert passes the same flows through the same line with no sign of it) and not the ambient pressure (it
  would move the low steps only): the 1.2 mm insert passes ~35% less gas than a clean 1.2 mm bore, as if ~0.96 mm.
  Check it for silicone residue / measure the bore before `--write`; the 1.2 mm CCD runs' gas share depends on it.

**Step 2, HOME PC, DONE 2026-10-15 18:19-19:05 (46 min, no failures; results in Recent changes: the sizer reads
falling beads ~0.94 x nominal + 22 um).** The LaCie can go back to the Mac. What was run, in order:
```
git -C "C:\Users\BenSc\Documents\GitHub\HPATR" pull
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" "C:\Users\BenSc\Documents\GitHub\HPATR\AI\Real_Data_Code\run_ai_where.py" "D:\Calibration\Imaging Work\2026\10\15\falling" --notes "BEAD fall" --dry-run
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" "C:\Users\BenSc\Documents\GitHub\HPATR\AI\Real_Data_Code\run_ai_where.py" "D:\Calibration\Imaging Work\2026\10\15\falling" --notes "BEAD fall"
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" "C:\Users\BenSc\Documents\GitHub\HPATR\AI\Real_Data_Code\run_ai_where.py" "D:\Calibration\Imaging Work\2026\10\15\falling" --notes "BEAD fall 155.8" --stride 2
"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" -c "import csv,glob,statistics as st; [print(f.split('falling')[1][1:30], 'detected', len(r), 'in focus', len(d), 'median', round(st.median(d),1) if d else '-') for f in sorted(glob.glob(r'D:\Calibration\Imaging Work\2026\10\15\falling\*\shadowgraph\analysis\droplets_*\droplet_sizes.csv')) for r in [list(csv.DictReader(open(f)))] for d in [[float(x['diameter_um']) for x in r if x['in_focus']=='1']]]"
```
- The dry run must list FIVE pours (not the blank, not the static captures). If it lists fewer, a file is missing
  `.cine` (PCC drops it on names with a decimal point): stop and tell Ben.
- Line 3: all five pours at stride 10 (Ben's choice), ~950 frames, ~30 min of GPU plus copying each cine into its
  new run folder `falling\<file name>\` (28 GB in all; the LaCie has 2.5 TB free), ~45 min in all.
- Line 4: the 155.8 pour again at stride 2 (~1,350 frames, ~40 min). A 155.8 um bead crosses the field in 2-3
  frames, so stride 10 misses most of them; this replaces that pour's stride-10 result (same folder, overwritten).
- Line 5 prints per pour: detections, in-focus detections, median in-focus diameter. Record it in Recent changes.
  Rough targets: >= 20 in focus per size (37.36: sightings, each slow bead is seen several times). A size short of
  that: re-run that pour at `--stride 1`, do not re-record.
- Restartable; writes only into the new run folders under `falling\`. Python 3.9: the 057a0f3 fixes are first
  exercised here; a `TypeError: unsupported operand type(s) for |` at import means another annotation was missed.
- Then the LaCie goes back to the Mac.

**Step 3, Mac, DONE 2026-10-15 ~21:00: the final bead run on the LaCie** (`Calibration/Imaging Work/analysis/2026-10-15/`: report.md, optics_calibration_v1.json, CSVs, figures, regions/; a `bead_region.png` in each of the 36 capture folders; the LaCie README updated; numbers identical to the run on the copied stills; the falling table and its equivalent defocus in; the PCC blank shows no dark dust). `bead_calibration.py` 1.1.0 is written and
tested (uncommitted on the Mac): it measures only dark (T_min < 0.35), round, isolated beads in the SPARSE part of
each photo (Ben), and writes a PNG with that area boxed into each capture's own folder
(`<run>\shadowgraph\analysis\bead_calibration\bead_region.png`) plus a copy in `analysis/2026-10-15/regions/`; it reads
the PCC blank as the dust map. Already run on the 36 averaged stills copied to the Mac (results below, preliminary).
On the LaCie it writes everything for real and picks up the pours' AI results (~6 min):
   `/Users/benschofield/anaconda3/envs/phantom/bin/python3 /Users/benschofield/Documents/GitHub/HPATR/AI/Real_Data_Code/bead_calibration.py "/Volumes/LaCie/Calibration/Imaging Work/2026/10/15" --out "/Volumes/LaCie/Calibration/Imaging Work/analysis/2026-10-15"`
   Fill in `Calibration/Imaging Work/targets.json` (supplier, lot, each size's certified spread) when the
   certificates are to hand. What was tried and failed on the way, with pictures: the Slides deck "Bead calibration:
   what we tried, what failed" (https://claude.ai/artifact/GwVFTvtkgDMR9N5bLG25PG, private to Ben).

**Step 4: SIZER 3.0.0, plan APPROVED by Ben 2026-10-15: `docs/notes/2026-10-15_sizer_3.0.0_plan.md`.** Phase-gated, 9 phases:
0 one optics profile; 1 focus on the spray centre (a 300 um precision pinhole held on the orifice axis + a live blur-width
meter in GUI_Clean); 2 the smallest size we can confidently measure; 3 calibrate the edge, the focus rule and a defocus
look-up table from the beads; 4 the 3.0.0 code; 5 concentration per mm3 and an in-focus atomised fraction; 6 prove
it on the beads (Ben's go / no-go); 7 re-measure every day (2.2.0 kept); 8 docs. Decided: one chi_max for every
size; atomised fraction in-focus only with the old one alongside; below d_min counted not sized; "confident" =
median bias within +-10% and >= 90% found; the look-up table in 3.0.0 now, improved with the reticle later.
- **Phase 0 DONE 2026-10-15 (Mac), no number changes** (committed ec53bcc "Optics Phase 1").
- **Phase 2 DONE 2026-10-16 (Mac): provisional d_min 30 um (chi <= 15) / 35 um (chi <= 20-25), half-max sizing**
  (details in Recent changes; `Calibration/Imaging Work/analysis/size_limit_2026-10-16/`).
- **Phase 1 code DONE 2026-10-16 (Mac): the focus meter is ready for the pinhole** (`docs/FOCUS_CHECK.md`). NEXT,
  when the pinhole arrives (week of 2026-10-19): the rig session (holder + rail scale; focus with the meter, the
  0/180 check). Committed and pushed with Phase 2 (3e3ab27); the lab PC must pull before that session.
- **Phase 3 DONE 2026-10-16 (Mac), PROVISIONAL: `AI/Real_Data_Code/sizer_calibration.py`; results in
  `Calibration/Imaging Work/analysis/sizer_calibration_2026-10-16/`; the optics profile's calibration block is filled**
  (the 2.2.0 sizer reads none of it). Edge: Blaisot's contrast-corrected size minus 5.6 um (half-max minus 5.2 um
  read the sharp beads as well, 4.3 % vs 4.0 % worst; Blaisot's table is the more precise). chi_sharp 15 um (sized
  directly), chi_max 50 um (through the table; the falling check fails beyond it: 37 um reads +17 % at chi 50-60),
  chi_max_direct 24 um (the single cut without the table), d_min 30 um (Phase 2), depth 1.06 / 10.3 / 4.7 mm and the
  same for every size within +-3 %. Details in Recent changes. **Decided (Ben, 2026-10-16, option 1):** droplets
  below the smallest bead (30-37 um) are sized through the table up to chi_max with Delta held at the 37 um value,
  flagged table_extrapolated: one measurement volume for every size (profile `below_smallest_bead`); the reticle's
  28 / 19.8 um dots check it.
- **Phase 5 DONE 2026-10-16 (Mac), uncommitted: droplets per mm3 and the atomised fraction inside the volume.**
  Details in Recent changes. Ben's decisions applied: frame-edge droplets by a border correction, crowded ones added
  back in proportion, faint no-chi ones outside the volume. **3.0.0 is the default sizer since 2026-10-16 (Ben,
  overriding the plan's wait for Phase 6)**; existing campaigns (the CCD day first) need 'Re-measure only' in the app to
  be analysed at 3.0.0. NEXT: Phase 6 (Ben's go / no-go: beads band by band, two CCD runs side by side), then Phase 7
  (re-measure every day).
- **Phase 4 code DONE 2026-10-16 (Mac), committed and pushed with Phase 3 (f57655a); now the default (above).** `--sizer 3.0.0` on measure_run / classical_liquid /
  process_capture / batch_runs, `RunSettings.sizer` in the app, `GUI_Clean.SIZER` (None = 2.2.0); 2.2.0 stays the
  default until Ben's Phase 6 go. Shared measurement `AI/Real_Data_Code/blur.py`. Details and the CCD 125754 check in
  Recent changes. NEXT: Phase 5 (concentration per mm3, the in-volume atomised fraction), then Phase 6 (Ben's go /
  no-go on the beads and two CCD runs side by side).
  **The big-bead series does not need the pinhole or the meter**: run it at the next rig session; then re-run Phase 3
  with both days (commands in `docs/BEAD_CALIBRATION.md`). Phase 1 target (Ben, 2026-10-16): a **300 um precision pinhole**, arriving the week of
  2026-10-19 (thin foil, no glass: the feature plane is the foil; a 180-degree rotation check finds the axis). Ben:
  a holder that seats in the insert holder with the foil on the orifice axis, and a scale on the camera rail.
- **Reticle, add:** step the dot array through focus (+-5 mm) to check the lens really is telecentric over the
  measurement depth (dot spacing constant), since the concentration's volume assumes it.
- **Rig asks:** (the big-bead through-focus series DROPPED 2026-10-22: beads fall off the slide when it is turned upright; the reticle's dots through focus replace it); the 300 um pinhole + its
  holder + a rail scale; the 1.2 mm insert (residue / bore); the PS20 reticle, **ARRIVED 2026-11-04 (Ben)**: needs its certificate values in targets.json, the 14 / 19.8 / 28 um dots and the squares added to `bead_calibration.py`, and a run sheet, before its session (dot array; 14-317 um dots and a large
  square through focus; the pinhole's diameter against the certified scale).

**Wednesday 2026-10-14 (code / understanding) and Thursday (rig): `docs/notes/2026-10-14_plan_for_wednesday.md`**
- **Thursday 2026-10-15: NO SILICONE (Ben, morning of the 15th). DONE:**
  1. each insert's gas-only Cd test (1.2, 0.8, 0.5 mm; line loss ignored, Ben: negligible);
  2. THEN all the bead work, `docs/BEAD_CALIBRATION.md`, with the optics untouched all day:
     - 36 sandwich captures (GUI run sheet);
     - then the falling beads, recorded in PCC (one pour per size, trimmed, named
       `BEAD fall <size> p1.cine` in `Calibration/Imaging Work/2026/10/15/falling/`). `run_ai_where.py`
       turns each loose .cine into a run folder and runs the AI.

  The run sheet (`docs/notes/2026-10-15_thursday_run_sheet.csv`, same on the LaCie) is now 36 bead rows (the 3 Cd rows done and
  removed; B01-B05 one capture per single-size sandwich at focus, then B06-B36 the mixed sandwich through focus ±8 mm, optional; Cd rows now carry Motor Travel 0, as Start refuses an empty box). **Postponed to a later spray
  day, unchanged:** the 10 spray runs below, the PCC max-fps check and the exposure series (in the sheet's git history,
  commit 057a0f3).

  The 10 spray runs (postponed):
  - 1.2 mm: anchor centre 9,000/500/4,000; confirm 11,000/100/5,000 x2; 12,000/100 at feed 5,000, 6,000 and
    8,000;
  - 0.8 mm: 12,000/100/5,000;
  - 0.5 mm: the C7 repeat 7,000/900/3,000; 900 rpm at feed 4,000 and 2,000.

  Dropped from the 16: the second anchor, the third confirmation, feed 7,000, 0.8 mm at 900 rpm, 0.5 mm at
  500 rpm, and the second C7 repeat.
  Spray-run details: 1.2 mm: 2 centre anchors, 3 confirmations of 11,000/100/5,000, a 12,000 sccm feed ladder
  5,000-8,000 (longer travel for the fast feeds). 0.8 mm: 12,000/100 and /900 at feed 5,000. 0.5 mm: C7 recipe x2,
  feed 2,000 and 4,000 at 900 rpm, 500 rpm at 3,000. Notes `S2 #NN <purpose>` (never "run N"). The bubbler's maximum is 900 rpm.
- **Wednesday done:** throughput defaults; pressure/flow log gaps explained and fixed; classical 2x2 grids; GUI_Clean
  Run sheet tab + Thursday's sheet (`docs/notes/2026-10-15_thursday_run_sheet.csv`; load it on the Run sheet tab).
- **Open:** the stride pop-up (need its wording), a full-stride cine;
  pool every new run into the CCD day (needs the next-session fix, item 19); the lab PC cannot run the AI, so no
  live numbers (overnight at home); IMPORTANT after the small fixes: the calibration scripts (plan mode first).
- ~~Commit and push, then pull on the lab PC before any capture~~ DONE (lab PC pulled 057a0f3 on 2026-10-15).

0. **CCD follow-up plan** (approved 2026-10-13; `docs/notes/2026-10-13_CCD_followup_plan.md`), phase-gated:
   1 bugs 3 + 6 and the "by area" relabel (DONE 2026-10-13); 2 "no spray" runs (atomised < 2%: size and
   steadiness blanked; DONE 2026-10-13); 3 gas regimes (pressure-limited runs out of the fit, own section; best observed runs;
   goals used / dropped shown in Best settings; DONE 2026-10-13); 4 band-count response (in-focus droplets per frame,
   30-50 um; DONE; default band 20-60 um from 2026-10-14); 5 GUI_Clean regime indicator + logging (DONE, rig check pending); 6 orifice on a log scale
   (DONE); 7 area vs volume atomised fraction + window-droplet check H1 (DONE; liquid stage 2.3.0 built and
   re-run 33/33); 8 rate investigation (DONE: report, Ben to decide on a mass-balance rate response and a
   10-min exposure series); 9 re-analyse the CCD day (DONE: `Taguchi/CCD/CCD 4-factor 12-10-2026 reanalysis
   13-10-2026/`); 10 more extreme frames (DONE: back-filled for the 33 CCD runs, floor half the median); 11 window /
   lens droplets (DONE: GUI pre-run window check, rig test pending); 12 GLR + measured pressure (opinion given:
   keep set points, add gas exit mass flux as a covariate; `docs/notes/2026-10-13_phase12_physical_variables.md`).
   Then ONE commit, after Ben has reviewed the differences.
   Done: **The 33-run 4-factor CCD day** (gas 7000/9000/11000, RPM 100/500/900, feed 3000/4000/5000,
   orifice 0.5/1.2/1.8; orifice blocks, 5 centres, block repeats, 0 rpm control, 0.8 mm check).
   Before it: try the remaining GUI_Clean fixes on the rig (front limit switch firmware DONE 2026-10-12;
   still untried: cut-off, auto-trigger, static run, Alicat alarm). Ben practises the Response surface tab on the 9x3 copy (`docs/RSM_GUIDE.md`, "Using
   the app"); pull `Testing` + install python-pptx on the lab PC (item 5); (app bugs 1-2 now fixed); build + export the run sheet in the app, type each run's
   "CCD run N <point type>" in Notes. After it: batch on Windows, then the Response surface tab.
1. **RPM confirmation test** (Ben, lower urgency now): one gas/silicone setting, RPM alternated
   300/900/300/900... in one session (4-6 runs). Randomise run order in every future campaign.
2. ~~Ben to decide the default~~ **DECIDED 2026-10-08: 2.2.0, for good** (may revisit). What
   still follows from the diagnosis: every 2.2.0 D32 gas effect is ~2/3 selection, so it must be
   reported as "D32 of the round, sharp droplets" with that caveat. Still worth considering: the
   moved share ("non-round or blurred fraction") as its own response, since it rises cleanly with
   gas. The first L9 (10/01) is still 2.0.0; re-measuring it at 2.2.0 is ~41 s/run with `--reuse`
   if it is ever to be compared (not done).
3. ~~Fix the app bugs below before the next overnight batch (1 and 2 at least)~~ 1 and 2 fixed
   2026-10-11; 3-5 remain (minor).
4. **Fold in the Windows timings**: `9x3 Taguchi Repeats/_job/eta_calibration.json` +
   `_job/timings.csv` -> replace `eta.PRIORS_BY_OS["Windows"]` in `eta.py` with measured
   lo/typ/hi per stage. ~10 min, any time.
5. ~~Install `python-pptx` on the lab PC~~ **DONE** (lab PC 1.0.2 in system Python 3.11, checked 2026-10-15; home PC DONE 2026-10-12: 1.0.2 + lxml 6.1.3 + XlsxWriter 3.2.9
   into the Detectron env, numpy untouched at 2.0.2). (The Taguchi app's PowerPoint deck needs it;
   without it the publish still writes everything else and the report says why). Command Prompt:
   home PC `"C:\Users\BenSc\anaconda3\envs\Detectron\python.exe" -m pip install "python-pptx==1.0.2"`;
   lab PC `"C:\Users\55154111\AppData\Local\Programs\Python\Python311\python.exe" -m pip install "python-pptx==1.0.2"`.
   It also pulls in `lxml` and `XlsxWriter` (new installs, nothing upgraded on the Mac).
6. **Hardware:** powered USB 3 hub for the LaCie on the home PC (also the diagnostic: still drops
   on the hub -> cable or drive).

## Open questions that block or bias results

- **Sizer 3.0.0 (Phase 5):** the pours miss the >= 98 % atomised target where the AI misses or misclassifies
  beads (crowded 37 um pour 88.5 %; 56 / 76 um 96-97 %). Counting small round liquid pieces with no AI detection as
  droplets would close most of the 37 um gap: Ben's call. 3.0.0 is the default now, so the CCD day must be
  re-measured ('Re-measure only') before it can be analysed again at 3.0.0.
- **Sizer 3.0.0 (Phase 4 findings, for Phase 5/6):** on CCD 125754 most sized droplets come through the look-up
  table, and 48 % of those through its extrapolated parts (4,772 at 30-37 um, below the smallest bead; 170 above 76 um): the big-bead series and
  the reticle's 28 / 19.8 um dots are what make those sizes solid. 84 % of in-volume droplets are below d_min. Phase 5
  must say what no-chi (faint centre, 10 %), crowded (2 %) and border (5 %) droplets count as in a concentration.
- **How the pipeline works, exactly:** `docs/IMAGING_PIPELINE_REFERENCE.md` (2026-10-07): camera to
  report, maths, every constant, limitations, and the 16-step list to publication grade.
- **Syringe steps/mm = 6800, confirmed in firmware** (`Pressure_Motor_Portenta.cpp:30`), matching
  the GUI, so recorded liquid flows and GLRs stand. Older docs saying 13,600 were an arithmetic slip
  (fixed 2026-10-07). **Firmware bug found:** the travel check allows 986,000 steps (= 145 mm, not
  72.5 mm); FIXED in 58f1b94 (MAX_TRAVEL_STEPS = 493000) and flashed 2026-10-12; the front switch is now the hard stop.
- **Measurement method (longer term):** `docs/DROPLET_MEASUREMENT_METHOD.md` (2026-10-07) is the
  plan to make sizes defensible: dot-reticle + glass-bead calibration of edge, focus and depth of
  field, size-dependent DOF weighting, shape classification instead of rejection, volume-based
  sizing, Dv50 beside D32. Not started; includes what to buy and how to run the calibration.

- **RPM vs time of day** (see "Where we are"). The silicone is ONE part of the EcoFlex, not mixed, so it does
  not cure and its viscosity does not rise in the pot (Ben, 2026-10-14). Lab temperature is not recorded.

- **Which edge is "true" diameter.** Half-max (what the sizer implements) reads ~30-35% smaller
  in diameter than Ben's free-hand eye (51 droplets, 2026-10-02). The sizer is a correct
  implementation of a convention whose correctness is unsettled. Only a **calibration target**
  (reticle / graticule / glass beads) on this rig settles it. Relative ranking across Taguchi runs
  is unaffected; absolute diameters are.
- **The reclassification rule is now in force as 2.2.0** despite the earlier verdict that it was
  unfit for Taguchi frames (1 false reject / 20 false keeps on L9 frames; opposite error on the
  benchmark). The 2026-10-07 diagnosis explained its gas gradient as real shape change (less round
  fragments at high gas), not crowding, but ~2/3 of the resulting D32 gas effect is selection. The
  9000 sccm hand-labelling that would measure its error rate there has still not been done.
- **Decorrelation time: transit is under one frame (2.56 ms), measured 2026-10-13** (was assumed ~20 ms).
  Consecutive 390 fps frames share no droplets; liquid residence time in the field is 1.4–2.8 ms.
  What still couples frames is pulsing; the stride-10 CI is conservative for transit, and a block
  bootstrap on the measured count autocorrelation is still the proper fix.
- **Old L9 (10/01) is sizer 2.0.0** and not directly comparable to the 27 runs on atomised
  fraction. Re-measuring it is ~41 s/run if ever needed.

## Known bugs, not fixed

GUI_Clean (review 2026-10-12, Mac). FIXED the same day (committed 58f1b94; firmware + front switch tested on the rig 2026-10-12, the rest offscreen only):
Alicat reader death / silence, jog limits + front switch, Clean removed, close check, cut-off clearing,
Space bar, speed 0, stopped runs marked, conditions recorded at Start, atomic writes, settings saved
half-loaded, unused code, How To button + text (details under Recent changes). Still open (Ben's call):
- Traverse driver unpowered (rig safety switch off, 2026-10-12): the motor is limp, homing counts steps to
  its 1.1M-step limit and the GUI takes ~110 s to connect, then shows HOMING_FAILED "back switch never
  triggered". Check the safety switch / supply first. Proposed, not made: a driver check before homing
  (fail in ~3 s) and Home re-sending the driver settings (Ben has not decided).
- STOP / cut-off within 0.5 s of Start does not cancel the delayed traverse command (Ben: leave).
- AI auto-save writes into whichever run is current when the AI finishes (Ben: runs never overlap).
- `_run_folder` never cleared: a manual trigger between runs writes into, and deletes the TIFFs of,
  the previous run; Disarm during a camera save clears camera RAM (Ben: leave both).
- Camera IP box is ignored (PhantomController.connect discovers); three volume calcs disagree (r=10 mm,
  25.8 mL/72.5 mm, bore 20.27 mm: up to 13%); the Homed dot stays red after the board's own start-up
  homing (the "Homing Complete" line is consumed during connect).
- Deleting GUI_Clean's main window crashes Qt (segfault / bus error), offscreen on the Mac, the committed version
  too (found 2026-10-14 writing the run-sheet tests: build + delete the window, or build twice). Not seen on the
  rig, where it is built once and deleted at exit; it may explain any crash on closing. Cause not looked at.
- FREEZES (to do separately): cone webcam on the GUI thread at 10 Hz; `find_lacie_drive()` per keystroke;
  the 83 MB master_log.xlsx rewrite holds the GIL ~10 s at every run end; Phantom live-feed conversion on
  the GUI thread; ~30 setStyleSheet/s; console never trimmed. (FIXED 2026-10-14: the 5-s LaCie poll now
  probes on a worker thread; `log_serial` queues to one writer thread.)
- The pressure cut-off is checked on the GUI thread, so a GUI stall delays it (1-4 s stalls on the CCD day,
  now mostly removed; see Recent changes 2026-10-14). Not changed: moving it to the reader thread means
  sending STOP from a second thread.

Taguchi_Analysis_UI (found in the 2026-10-06 batch):
1. ~~One failed log write kills the worker~~ **FIXED 2026-10-11** (Mac, committed 6f63e76): writes to the
   run log, events and state never fail a run or the worker (kept and retried); a run that fails with
   an OS error or with its folder / the job folder unreachable waits up to 30 min for the drive and is
   redone once (reusing finished work); if the drive does not return the worker stops as
   **drive_lost** (exit 6), that run pending, Resume offered. `tests/test_worker_drive.py` (7,
   mutation-checked). Not yet run on Windows with a real unplug.
2. ~~A crash is reported as a contract violation with no Resume~~ **FIXED 2026-10-11**: a crash is now
   status **crashed** (exit 7), resumable, with its own message; old jobs written "halted" with no
   contract-violation run also read as crashed. Only a real contract violation reads "halted".
3. The SELECTED RUNS summary ("N already measured") does not update while a batch runs. **Worse, found
   2026-10-13 (home PC, CCD day):** the run list's RunInfo (incl. `analysis.measured`) is read once when runs
   are added and NEVER re-read when the batch finishes (`pane_runs` only reloads on a settings change; "+" on
   the same folder skips runs "already in the list"). So Analyse in the same session as the batch skips every
   run as "not measured yet" and refuses. **FIXED 2026-10-13 (Mac):** the Batch tab re-reads the run list
   whenever a batch stops running (`pane_runs.refresh_runs`, console "batch ended: re-reading N run(s)");
   test `test_the_run_list_is_re_read_when_the_batch_ends`. The SELECTED RUNS summary during a batch is
   still not live (minor).
4. After a crash the "already have results" dropdown showed "Re-measure only"; check the default
   (run sheet says "Use their existing results").
5. 17 Windows-only test failures, all test-side (path separators, `os.getpgid`, symlinks needing
   admin, `?` in a fake run name, one GLR test). Self-test says READY regardless.
6. **No atomised liquid flow on the home PC (found 2026-10-13, CCD day):** `covariates._gui_formula` imports
   `GUI_Clean`, which imports `Trials/Cone_4.py`; Cone_4 uses `int | None` annotations, a TypeError on
   Python 3.9 (the Detectron env), and GUI_Clean's guard catches only ImportError. So the GUI formula is
   unavailable, `liquid_ml_min` is None, and `af_flow` ("Atomised liquid flow") has no values: "No fit", and
   the throughput goal silently drops out of the desirability (the CCD best setting became atomised fraction
   alone -> lowest feed). Recorded GLR is unaffected. Fine on Python >= 3.10 (Mac, lab PC). **FIXED
   2026-10-13 (Mac):** GUI_Clean's Cone_4 guard catches any exception; and if the formula still cannot be
   imported, both analyses now say so in capitals (console, top of the report) and the Model page marks the
   atomised liquid flow row "unavailable" (`covariates.formula_problem`, `stats.flow_warning`). The home PC
   needs `git pull`; then re-Analyse there to get atomised liquid flow.

Response surface tab, found 2026-10-11 (tested on fakes: the 9x3 + 4 next-session runs on another day):
- **Loading a next session with the original runs is not handled properly yet.** (a) Confirmation runs
  are swept INTO the fit (8,700 sccm becomes a 4th gas level, "edge" points), so they no longer test the
  model unless Validation is ticked by hand; (b) the design is re-detected as "irregular" and the
  original point types are relabelled (face centres -> "other"); (c) the fit has NO day/session offset
  term, so a day-to-day shift in D-optimal runs added to the fit is absorbed into the surface (the centre
  anchor is recommended to measure it, but nothing uses it yet). Proposed fix (not started): Notes
  "CCD next run N confirm" -> validation automatically; keep the first session's design and classify
  the new runs as added; a session offset term when runs span days, estimated via the anchor.

- ~~Model page goals: Minimise ramp unswapped; no target for Hit a target~~ **FIXED 2026-10-11**
  (`tab_rsm.goal_for_fit`): worst scores 0 and best 1 for every aim, a target is the best column
  (symmetric ramp out to worst), a backwards ramp is refused with the response named; older saved
  rsm_model.json (low/high keys) still read. Tests in test_tab_rsm.py, mutation-checked.

- ~~Steepest ascent / new CCD could walk feed down to 0 steps/s~~ **FIXED 2026-10-11:** feed floor
  2,000 steps/s (Ben: the lowest that sprays usefully) in `rsm_design.RIG_LIMITS`; found when Ben's
  practice goals (size x3 + atomised fraction, no liquid-flow goal) sent the path to "8200 sccm, 0 steps/s".
  Guide now warns that correlated goals stack and a fraction goal alone favours the lowest feed.
  **Ben's goal trial on the 9x3** (2026-10-11, `Practice Folder/Ben 9x3 CCD practice` vs
  `output/9x3 response surface (gas x feed)/Baseline (default goals, importance all 1)`): best setting
  moved from 8,744 sccm / 8,000 steps/s to 8,187 / 4,000; driven by the goal SET (liquid-flow goal
  removed, three size goals), not the importance numbers (all-1 importance gave 8,626 / 4,000).

Elsewhere:
- **Static specks detected as droplets.** The same ~5 places (e.g. x1824 y648, x336 y852,
  x1416 y108, x918 y1128) are detected as 40-60 um in-focus droplets in 20-70% of frames, in every
  run of 10/05: dirt on the window or sensor, not spray. Small, so D32 is barely affected (pulled
  slightly down); droplets per frame is inflated by a few per frame, relatively most at 3000 sccm
  (~34/frame). No trend with time. Fix later by rejecting detections that sit on static dark
  features of `background_median.tiff`. Found 2026-10-07 (scratch script, read-only).
- `measure_run.py`'s model-only atomised fraction and `score_v2.py` double-count cross-class mask
  overlap in the denominator. The quoted (classical) fraction is structurally immune.
- `master_log.xlsx`: one row saved during the GLR-column bug (after 09:04, 2026-10-05) has
  "NO DATA AVAILABLE" in Notes and graphs in O/P. Real notes are in that run's `run_summary.xlsx`.
  Scripted repair offered, not done. Close Excel first.
- `GUI_Clean.py` still creates `Brightest_Frame` (concept retired 2026-09-27).
- `score_v2.py` is model-agnostic despite its name; rename to `score_predictions.py` some time.
- `requirements.txt` is stale (lists customtkinter, not PySide6 / torch / detectron2).
- Several `__pycache__/*.pyc` files are tracked in git despite `.gitignore`; they churn across
  machines.

## The measurement currently in force (sizer 2.2.0, since 2026-10-08)

- Model: v3 "Eden" (`training_2026_09_25_15_20_37`, iter 19000), tiled inference at native scale,
  score threshold 0.30, stride 10, extremes-only images.
- **D32** = in-focus droplets only (`t_min <= 0.70` focus gate, interior-pixel robust core
  estimator), half-max sizing at/above the **40 um** split, model mask below it, **then the
  sharpness rule**: an in-focus droplet >= 50 um is reclassified out of focus when
  `fill_ratio < 0.85` or `extinction_conc < 0.60`. A reclassification, never a deletion: counts and
  the atomised fraction are unchanged. So D32 is "D32 of the round, sharp droplets"; its gas effect
  is ~2/3 selection (see Where we are). From `measure_run.py` -> `droplets_0.30/summary.json`.
  `--no-sharpness-rule` gives 2.1.0.
- **Atomised fraction (quoted)** = `liquid_0.30/classical_summary.json` `atomised_pct_pooled`:
  half-max droplet numerator over a classically segmented whole-frame liquid denominator
  (`classical_liquid.py`). `summary.json` `atomised_pct` is model-only, reference only.
- Folder names: `droplets_<thr>` / `liquid_<thr>` (readers also accept the old
  `measurement_` / `classical_`).
- Mixed `sizer_version` is refused by the analysis, by design.

## Campaigns and where the data is

| what | where |
|---|---|
| 27 replicate runs (2026-10-05) | `/Volumes/LaCie/Experiments/2026/10/05/<run>/shadowgraph/analysis/` |
| their Taguchi output | `/Volumes/LaCie/Experiments/Taguchi/9x3 Taguchi Repeats/` |
| first L9 (2026-10-01), 2.0.0 | runs in `Experiments/2026/10/01/`; re-analysis in `Experiments/Taguchi/First Taguchi Trial (RPM, SCCM, Silicone Flow)/` (Ben calls it "Taguchi First Trial") |
| 20-frame validation set | `/Volumes/LaCie/Experiments/Real_Data/06_validation/` (never trained on) |
| free-hand sizing set (51 droplets) | `/Volumes/LaCie/Experiments/Real_Data/07_validation_taguchi/` |
| pipeline code | `AI/Real_Data_Code/` (`measure_run.py`, `classical_liquid.py`, `batch_runs.py`, ...) |
| Taguchi app | `src/ai/Taguchi_Analysis_UI/` (plan: `docs/TAGUCHI_ANALYSIS_UI_PLAN.md`; Windows run sheet: `docs/TAGUCHI_WINDOWS_RUN_SHEET.md`) |
| capture GUI | `src/gui/GUI_Clean.py` |

Factors in the 27-run design: gas flow 3000/6000/9000 sccm, bubbler 300/600/900 rpm, silicone
4000/6000/8000 sps; orifice 1.2 mm, bubbler height 1. GLR is a covariate, not a factor.

## Machines

| machine | role | Python |
|---|---|---|
| Mac | analysis, development | `/Users/benschofield/anaconda3/envs/phantom/bin/python3` (no torch/detectron2) |
| home PC (BENS-PC, RTX 5060 Ti) | batches, training. LaCie = `D:` | `C:\Users\BenSc\anaconda3\envs\Detectron\python.exe` only (system 3.11 torch can't run sm_120) |
| lab PC | capture rig | system Python 3.11 (`AppData\Local\Programs\Python\Python311`) |

**LaCie on the home PC drops off USB** (3 times on 2026-10-06; hardware, not load-correlated).
exFAT has no journal: eject before unplugging; after any disconnect sound run Scan and repair
before using it.

**The LaCie has no backup yet (2026-10-26).** 2.1 TiB used, 2.4 TiB free: about 4–5 more big rig days.
The plan, the measured sizes and the exact FreeFileSync steps are in `docs/notes/2026-10-26_lacie_backup.md`.

## Settled — do not re-derive

Full statements and reasoning in the legacy handoff ("Established facts", "Decisions already
made", "Bit depth", and the dated sections).
- 10 um/px (100 px/mm), recorded as calibrated earlier; the beads agree (their at-focus bias is a fixed ~+6 um
  edge offset, not a scale error). The reticle's dot array will measure it directly. One value, in the optics
  profile. Frames are 12-bit stored as uint16.
- Classes in the model: droplet / blob / filament. Droplet size ceiling 200 um.
- Primary response: area-weighted atomised fraction (larger is better). Secondary: D32 of
  droplets (smaller is better). Count-based ratios rejected.
- Training data by compositing real objects, multiplicatively in transmission. 800x800 crops,
  tiled inference, never resize at inference.
- Gas density default 1.184 kg/m3 (air at 25 degC, matching the Alicat's STP), not 1.293.
- Capture: **390 fps** (Ben, 2026-10-08; the GUI standard), exposure 4 us, 2048x1152, 13 s
  post-trigger. Shorter videos than at 190 fps, so **two runs fit one syringe refill**. At stride
  10 the effective rate is 39 Hz, which has no integer ratio with the bubbler's 5 / 10 / 15 Hz, so
  no aliasing (190 fps was the earlier suggestion for the same reason). Shorter captures than the
  suggested 25 s are deliberate: don't "correct" them.
- Sizer **3.0.0** has been the default since 2026-10-16 (Ben), with 2.2.0 kept for comparison; 3.1.0 is being built
  (plan 2026-10-17). It superseded 2.2.0 (sharpness rule, 2026-10-08), which superseded "focus rejection deferred".
- **A window air purge is not an option** (Ben, 2026-10-17; tested earlier).
  - Even at high-ish pressure it does not stop large, high-inertia droplets.
  - It disrupts the spray: secondary atomisation, so its extra droplets could not be separated from the nozzle's.
  - Drops on the window are handled in the analysis instead: the rolling background and the window mask.

## Standing rules

- Never modify raw data. Analysis code and outputs go in their own folders; one config per study.
- Phase-gated: do the phase asked for, then STOP and report. Report findings that change the plan.
- State every assumption explicitly in reports. "Not significant" is never "no effect".
- Give Ben exact paste-able commands with absolute paths and the real interpreter.

## Recent changes (newest first; trim to ~10 entries, older ones live in git history)

- 2026-10-17 (Mac): **Sizer 3.1.0 Phase 4: outputs** (uncommitted).
  - **master_log** is one shared module (`AI/Real_Data_Code/master_log.py`) used by GUI_Clean and the app.
    - The app fills the analysed runs' existing rows (measured columns only) at the end of every Taguchi / RSM
      analysis, with a daily backup, and refuses while Excel has it open.
    - **New layout, Ben's columns:** Droplets/s (30-60 um), then <30 / 30-40 / 40-60 / 60-100 / 100+ um (per cm³,
      adding up to the concentration), in-band flow (mL/min), concentration, atomised in volume, Sizer.
    - The six 'Sizer 3.0.0' columns of 2026-10-16 are removed by the migration.
    - Checked on copies of the live log, incl. GUI_Clean's real save: 370 images moved with their columns, every
      other cell unchanged.
  - **The old results are kept:** 'Re-measure only' (and any re-measure through process_capture) moves the earlier
    `droplets_` / `liquid_` into `_sizer<old>/` first, never overwriting an archive.
  - **Frame images:** coloured by 3.x verdict, with a key of the verdicts in that frame and their counts
    (measure_run, the liquid stage, the Extremes tab).
  - **The largest-droplets sheet:** 25 crops per run (measure_run), and one slide per run in both decks.
  - **Report warnings:** window drops, a D32 resting on droplets beyond the largest bead, many unmeasurable
    droplets.
  - **Bead deck:** +9 slides (63).
  - **Tests:** test_master_log (5) and test_sizer31 +3.
  - **The lab PC must `git pull` before its next capture** (the master_log layout, 3.1.0).
- 2026-10-17 (Mac): **Sizer 3.1.0 Phase 3: throughput by one shared function** (uncommitted).
  - **`rates.py`:**
    - in-band share = in-band droplet volume ÷ all the liquid inside the measurement volume;
    - in-band flow = syringe flow × share;
    - in-band droplets/s = syringe flow × in-band droplets per mm³ of liquid in view;
    - 95% CIs by resampling frames.
  - **The droplets below d_min are only in the denominator.** That was 3.0.0's bug, so 3.0.0 runs get no rate.
  - **The liquid stage at 3.1.0** writes the in-volume liquid volume per frame, each piece by its best size (sized:
    calibrated; below d_min: measured; unmeasured: mask × the run's size/mask ratio; ligaments: bodies of
    revolution).
  - **App:** `rate_band` / `rate` at 3.1.0 from rates.py, new `band_flow` (mL/min); band default **30-60 µm** (Ben).
  - **CCD (scratch):**
    - 125754: 77,000/s (0.16 mL/min);
    - 143415: 19,000/s;
    - 123534: 4,500/s;
    - CIs ±50-60%: the liquid in view is heavy-tailed.
    - By volume inside the volume, atomised is 0.2-2.7%: ligaments and jets hold nearly all the liquid.
  - **master_log layout decided (Ben):** 'Droplets/s' stays and becomes 30-60 µm; the new columns go to its right.
    GUI_Clean moves to rates.py in Phase 4 with that migration.
  - **Tests:** test_sizer31 +3.
- 2026-10-17 (Mac): **Sizer 3.1.0 Phase 2: the rolling background; 3.1.0 the default** (uncommitted).
  - **Code:** `background.py`. Each block of 25 frames is divided by the median of the ±25 frames round it, stored in
    the run's `analysis/background_rolling/` (16-bit PNGs plus index.json, ~36 MB, ~2 min a run, built
    automatically).
  - **Window log:** drops landing on the window are logged as events, grouped into drops with the frame first seen
    (provenance `window_drops`).
  - **Where:** measure_run and the liquid stage (`--background-rolling auto|DIR|none`; separate frames such as the
    hand-labelled set keep the static background) and render_more_extremes.
  - **123534:** droplets in the window drop's shadow are measured again (dark surroundings 559 → 29); D32 57.0 µm.
  - **143415 / 125754:** D32 52.4 / 49.2 µm.
  - **Bead pours unchanged** (medians 38.0 / 77.2 µm, in-volume atomised within 0.1 point).
  - **Concentration** within 1%; atomised fractions move ≤ 0.5 point.
  - **Default:** 3.1.0 in blur, pipeline_spec and GUI_Clean. The app flags 3.0.0 runs for re-measure.
  - **The lab PC must pull before using it.**
  - **Tests:** +2 in test_sizer31; pinned defaults updated.
- 2026-10-17 (Mac): **Sizer 3.1.0 Phase 1: the validity tests** (plan `docs/notes/2026-10-17_sizer_3.1.0_plan.md`;
  uncommitted).
  - **Liquid map:** `liquid_map.py` holds the hysteresis, moved out of classical_liquid.
  - **3.1.0 blanks every piece of liquid round a droplet,** AI-detected or not.
  - **New verdicts, none sized:**
    - `attached`: sits on liquid;
    - `dark_surround`: dark measuring window;
    - `inconsistent`: > 1.3× its own mask;
    - `static`: the same place in 3 of ±10 frames: dust.
  - **Counting:** the first three count like crowded; static is not counted.
  - **New outputs:** `droplet_sizes.csv` gains x, y, mask_d_um; per_frame and summary count each test; the
    concentration divides by every frame.
  - **Thresholds** from ~22,700 droplets in 3 CCD runs and 3 bead pours. Every 3.0.0 runaway was caught; the beads
    are unchanged (< 0.3%).
  - **CCD at 3.1.0:**
    - D32 123534 101.9 → 56.9, 143415 83.8 → 52.3, 125754 51.0 → 49.2 µm;
    - concentration and atomised fraction unchanged;
    - 341-835 dust detections per run left out. Dust sits at the same pixels in every run of the day.
  - **Version threading:** 3.1.0 recognised wherever 3.0.0 is (`blur.is_sizer3`; app refusals, run discovery,
    pipeline_spec, batch, validate_classical, render_more_extremes, the remeasure tools). Default still 3.0.0 until
    Phase 2.
  - **Tests:** `test_sizer31.py` (10; each fault reproduced synthetically: a 40 µm droplet on a ligament's edge reads
    232-281 µm at 3.0.0).

- 2026-10-16 night (Mac): **The CCD day re-measured at sizer 3.0.0 (Ben: "reanalyse the CCD runs ... save the old data so we can compare").**
  - **The re-measure:** 33/33 runs, from the saved predictions (no AI), 1 h 32 min, four at a time.
    - 2.2.0 results moved into each run's `shadowgraph/analysis/_sizer2.2.0/`.
    - The 2.2.0 analyses and decks in `Taguchi/CCD/` are untouched.
  - **Output:** `Experiments/Taguchi/CCD/CCD sizer 3.0.0 remeasure 16-10-2026/`:
    - the comparison workbook and figure;
    - both saved response-surface analyses re-run at 3.0.0, marked PROVISIONAL;
    - a README with the caveats.
  - **master_log:** six 'Sizer 3.0.0 ...' columns appended AFTER 'Mass Flow Graph'. GUI_Clean writes only A-T, so
    they survive the lab PC's saves.
    - 33 CCD rows filled; the 2.2.0 columns are unchanged.
    - A-T and all 370 images checked identical.
    - Backup: `Logs/Backups/master_log BACKUP 2026-10-16 before sizer 3.0.0 columns.xlsx`.
  - **Findings:**
    - Within the bead calibration, 3.0.0 D32 is 47-58 um, a few um below 2.2.0 for every run.
    - But **small droplets next to dark liquid the AI did not detect read 200-430 um.** The liquid is a jet edge, a
      ligament, or an out-of-focus drop on the window. The ring outside them reads T 0.36-0.72; each is > 1.6x its
      AI mask size (mask ~35-70 um).
      - They are 2-3 % of sized droplets but ~85 % of the d3 where they occur.
      - 123534: D32 64.5 -> 101.9; 143415: 57.4 -> 83.8. 2.2.0 rejected them.
      - Fix in measure_droplet_3 first (to-do item 0a).
    - Atomised in the volume is ~2x the every-object figure (rank correlation with 2.2.0 0.66).
    - Concentration 29-101 per cm3.
  - **Fixed (uncommitted):** the no-spray cut reads the every-object fraction at 3.0.0. Dribble 112022 reads 4.3 % in
    the volume against 0.19 % over every object. `stats.py`, plus a test.
    - Full suite 967 passed: 966 in the run, plus one GUI test that timed out while the batch held the LaCie and
      passes alone.
  - **Deck:** 8 comparison slides added (54 now; artifact GwVFTvtkgDMR9N5bLG25PG). Full exports are refreshed in
    `Calibration/Imaging Work/analysis/2026-10-15/slides/`; the section alone ('CCD day - sizer 2.2.0 vs 3.0.0',
    PDF + editable PPTX) is in the re-measure folder.
  - **To-do updated:** `docs/notes/2026-10-17_todo.md` items 0 and 7 (frame size: nothing breaks, but counts per
    frame compare badly across ROI sizes).

- 2026-10-16 evening (Mac): **Sizer 3.0.0 Phase 5, and 3.0.0 made the default sizer (Ben).** Committed and pushed, f022452.
  - **Concentration** (measure_run): droplets per mm3 in the measurement volume = frame area x the calibrated depth
    (10.29 mm at chi 50, the same for every size; the lens is TELECENTRIC (Ben), so the area is the same at every
    depth and the volume is a box). Each droplet in the volume is weighted for the frame edge, W H / ((W-2h)(H-2h))
    with h its measuring window (blur.border_weight); crowded droplets are added back in proportion; no-chi ones count
    as outside (Ben's three decisions). droplet_sizes.csv gains `weight`; per_frame.csv gains outside / no-chi counts
    and weighted counts; summary.json a `concentration` block. CCD 125754: 0.0573 per mm3 in the volume (57 per cm3),
    0.0091 sized, 0.0483 below 30 um; volume 2,428 mm3 a frame; crowded factor 1.017. A snapshot, not a flux.
  - **Atomised fraction inside the volume** (classical_liquid at 3.0.0): every piece of liquid is judged by its own
    blur width (new blur.object_chi: Blaisot's edge width generalised to any shape, equal to the droplet measurement
    on discs and within ~6 % of known blur on bars and blobs at chi >= 25), droplets by their own verdict; per frame
    droplet_px_in_volume / total_liquid_px_in_volume / atomised_pct_in_volume beside the old columns, pooled
    atomised_pct_in_volume_pooled. CCD 125754: 41.6 % in the volume, 20.5 % all objects (2.2.0: 20.0 %).
  - **Checks:** bead pours, in the volume (all objects): 155.8 98.7 % (71.3), 98.1 98.9 % (69.6), 56.28 96.8 % (80.0),
    76.39 96.1 % (61.6), 37.36 88.5 % (79.2). The target was >= 98 %: what is left is detection, not the volume (37 um:
    86 % of the leftover area is beads the AI never detected, 13 % its filament/blob calls; 76 um: 98 % filament/blob
    calls, mostly touching pairs). Results `Calibration/Imaging Work/analysis/phase5_pours_2026-10-16/`. Hand-labelled
    frames (validate_classical.py --sizer 3.0.0, `Real_Data/06_validation/classical_validation_2026-10-16_sizer3/`): in
    the volume 8.1 % against the labels' 10.3 % (measurable) / 8.7 % (all); all objects 6.0 %.
  - **The app** (taguchi_analysis.load_run, run_metrics, stats, rsm_responses): for a 3.0.0 run the headline atomised
    fraction is the in-volume one; new extra responses `conc`, `conc_band` (your size band) and `atom_all`, each with a
    frame bootstrap; steadiness responses count every detection. Caveats in the deck and RSM report say so.
  - **3.0.0 is the default** (blur.DEFAULT_SIZER): the app (RunSettings.sizer), GUI_Clean (SIZER), process_capture,
    batch_runs, measure_run and classical_liquid with no flag, run_ai_where. --sharpness-rule / --no-sharpness-rule
    still mean 2.2.0 / 2.1.0; jobs saved before resume at their own version. **It follows the calibration:** every
    3.0.0 run records its calibration's hash; the app's run list marks a run measured with an older sizer or an older
    bead calibration ("re-measure: ..."), and the statistics refuse to mix sizer versions OR calibrations. So when the
    big-bead series or the reticle updates the profile (sizer_calibration.py --write-profile), new runs use it and old
    ones are flagged for 'Re-measure only'.
  - Telecentric lens recorded in the optics profile (description + `lens`), not in the calibration (its hash is
    unchanged). Tests: test_sizer3 (now 18), test_blur (18); 11 older tests updated for the new default (labels gain
    "re-measure: ...", the extremes tests pin 2.2.0, the response list grew); full suite 966 passed; Python 3.9 clean.

- 2026-10-16 (Mac): **Deck now 42 slides, and an editable PowerPoint.** Six more real frames (run 125754, and the
  0.5 / 0.8 / 1.8 mm orifices) with every droplet ringed by its 3.0.0 verdict in eight clearly different colours (thin dark-edged
  rings set outside each droplet, so the droplet shows; Ben, 2026-10-16)
  (full-resolution copies: `Calibration/Imaging Work/analysis/sizer3_frames_2026-10-16/`), a Phase 5 slide, the
  commit lines brought up to date. `analysis/2026-10-15/slides/` now holds the PDF, the HTML and
  `... (editable).pptx`: every text, table, card, picture and arrow a native PowerPoint object (laid out by Chrome in
  Georgia / Arial, rebuilt with python-pptx), speaker notes included.
- 2026-10-16 (Mac): **Sizer 3.0.0 Phase 4: the 3.0.0 sizer in the pipeline, opt-in.** Committed and pushed with Phase 3. The deck has 12 new slides on Phases 1, 3 and 4 (35 in all; PDF + HTML re-exported to the LaCie).
  - **`AI/Real_Data_Code/blur.py`** (new; numpy + OpenCV only, the lab PC has no scipy): the bead measurement
    (re-centre, the object, the level curve on a 4x upsample, chi and Blaisot's size), Blaisot's model from a stored
    table (`blaisot_model.json`; a numpy Cephes i0e matches scipy to 1e-15, the stored model the scipy-built one to
    1e-15), the look-up table and the 3.0.0 rule (moved from sizer_calibration). bead_calibration.measure_at now calls
    it: **identical to before on 4,118 real falling-bead measurements** (0 differences, 294 at the edge included).
  - **measure_run `--sizer 3.0.0`** (`measure_droplet_3`, the one decision point): blur width chi and Blaisot's size
    measured around the AI mask as the beads were, minus the edge offset; direct to chi_sharp, the table to chi_max;
    below d_min counted not sized; no 40 um split, no sharpness rule, no 0.70 core test for droplets. Settings and a
    12-character hash from the run's own profile (refuses a profile without a calibration). droplet_sizes.csv gains
    chi_um, in_volume, size_method (in_focus = sized, so every reader of the first three columns is unchanged);
    per_frame.csv and summary.json gain droplets_in_volume / _unsized_in_volume / _border / _crowded; provenance
    gains optics_profile_hash, sizer_edge, sizer_chi_sharp_um / _chi_max_um / _d_min_um / _tau / _table_beads_um.
  - **A spray droplet is measured on its own profile:** the first run gave D32 99.5 um because a small droplet beside a
    ligament read 200-550 um (the bead code takes the nearest dark piece when the centre is pale; for an isolated bead
    that is the bead, in a spray it is the jet). Now every OTHER detection's mask (grown 3 px) is blanked to
    background first, no nearest-piece fallback, and a droplet another detection touches (within 3 px) is `crowded`
    (counted apart, not measured). The liquid stage builds the same occupancy, so both stages agree.
  - **Threaded through** classical_liquid (droplet verdicts and the atomised numerator's droplet edge; filaments and
    blobs keep the 0.70 test until Phase 5), process_capture (`sizer=`, `sizer_flags`), batch_runs, remeasure_liquid,
    draw_more_classical and render_more_extremes (a 3.0.0 run is redrawn only with the calibration that sized it),
    pipeline_spec (`RunSettings.sizer`, `sizer_of`, preflight of `--sizer`), jobstate (old jobs keep their version),
    the stub, GUI_Clean (`SIZER = None`), compare_runs (refuses runs sized with different calibrations), and the 3.0.0
    caveats in the deck and the RSM report.
  - **CCD 125754, measured on the Mac into scratch (nothing written to the run):** 2.2.0 with the new code is
    byte-identical to the committed code (every CSV, the extremes index, the summary but its timestamp). 3.0.0:
    D32 51.0 um, 95 % CI [48.7, 54.2] (2.2.0: 54.0 [53.2, 54.9]); mean 40.7 um (39.1); 10,353 sized of 66,158 in the
    volume; 55,805 (84 %) of the in-volume droplets read below d_min 30 um (counted, not sized); only 170 sized
    directly (chi <= 15), the rest through the table, 48 % of them (4,942) beyond its beads: 4,772 at 30-37 um, below
    the smallest bead, and 170 above 76 um;
    outside the volume 8,699, no chi 9,391 (faint centre), near the frame edge 4,327, crowded 1,472. 128 s against
    81 s at 2.2.0.
  - Tests: `test_blur.py` (12, incl. it runs with scipy blocked), `test_sizer3.py` (12: model discs in / out / below
    d_min / border, beside a jet, touching, a whole synthetic run through measure_run and the liquid stage, the
    backfill, a refused foreign calibration, the app's flags, job resume); test_pipeline_spec's fake signature gains
    `sizer`. Full suite 955 passed; every changed file compiles under Python 3.9.

- 2026-10-16 (Mac): **Sizer 3.0.0 Phase 3 (provisional): the edge, the chi rules, the depth and the defocus look-up
  table, from the beads of 2026-10-15.** New `AI/Real_Data_Code/sizer_calibration.py` (+ `test_sizer_calibration.py`,
  12 tests on synthetic beads; full suite 931 passed, Python 3.9 clean); `bead_calibration.py --tau` (a new series must use 0.1115: chi depends on tau).
  Results: `Calibration/Imaging Work/analysis/sizer_calibration_2026-10-16/` (report.md, figures, lookup_table.csv,
  pour_classes.csv); the profile `config/optics/lens1_2026-10.json` calibration block filled.
  - **The table is 2-D (size x chi), not one curve of chi/d:** the beads' growth with blur does not collapse on
    Blaisot's chi/d (37 vs 76 um differ by 5-8 % at the same chi/d). Built from the static beads only (Delta = how much
    larger each certified size reads, both sides of focus pooled, made to grow with chi; nodes 37.36 (108 beads),
    56.28 (31), 76.39 (**2**)), held constant beyond them.
  - **Checked on the falling beads only** (never used to build it): with the table every size from 37 to 155.8 um
    reads within +4.7 % (median, band by band) up to chi 50, against up to +18 % sized directly. Static and falling
    beads agree at the same chi to 1-3 %.
  - **Depth is the same for every size at a given chi limit** (Blaisot's claim holds): +-3 % at chi <= 25 and above.
  - **The AI recognises spheres inside the volume:** >= 97 % of poured spheres are called droplet in every chi band up
    to 60 um; its filament / blob calls sit at median chi 114-149 um. So the 62-89 % 'atomised' of pure spheres is
    entirely objects outside the volume, which Phase 5's in-volume fraction drops.
  - **7-17 % of the AI's droplet calls get no chi:** mostly within the measuring window of the frame edge (62-96 % of
    them), the rest masks much smaller than the bead (fragments). Phase 4: a border strip outside the volume.
  - The stage did not move from +7 to +8 mm on 2026-10-15 (chi identical); that step is dropped.
  - Run sheet for the big-bead series: `docs/notes/2026-10-16_big_bead_through_focus_run_sheet.csv` (G01-G93).

- 2026-10-16 (Mac): **Sizer 3.0.0 Phase 1 code: the focus meter, ready for the 300 um pinhole.** Procedure:
  `docs/FOCUS_CHECK.md`.
  - `AI/Real_Data_Code/focus_edge.py` (numpy only, the lab PC has no scipy): fits Blaisot's Gaussian edge
    lo + (hi - lo) Phi((r - R)/sigma) to every pixel round a disc (a pinhole bright on dark, or a dot) or across a
    straight edge; chi = 2 sqrt(sigma^2 - 1/12) um/px; the diameter with the blurred-disc curvature correction
    (+sigma^2/2R) as a scale check; finds a target that is 0.03 % of a 2048 x 1152 frame (it stands out from the
    median); ~30 ms a full frame. CLI measures 'FOCUS CHECK' captures into a focus_check.json.
  - GUI_Clean, Camera tab, card FOCUS CHECK (SPRAY CENTRE): Measure live (on the live feed, latest frame only, a
    worker thread like the lamella overlay), chi now / best / ~mm from the best / pinhole diameter, green within
    2 um of the best; Record with the rail reading at 0 or 180 degrees, the axis plane = the midpoint (warns if they
    differ by > 0.2 mm); records in ~/.hpatr/focus_check.json (HPATR_FOCUS_STATE for tests); each run's
    run_summary gets 'Focus check' (today's latest + the axis line, or NOT DONE TODAY), taken at Start.
  - Tests: `test_focus_edge.py` (13: chi 12-40 um and the diameter back within ~5 % / 1.5 um, bright and dark,
    8-bit, straight edges, a small target in a whole frame, no target, the rotation midpoint, a FOCUS CHECK
    capture); a new GUI window check (the panel reads a synthetic pinhole, records 0/180, the snapshot carries the
    axis); Python 3.9 clean. Full suite: 918 passed, 1 failed only because test_run_sheet pinned 9 window checks
    (now 10; fixed, that file passes).

- 2026-10-16 (Mac): **Sizer 3.0.0 Phase 2 done: the smallest size we can confidently measure is ~30-35 um on this lens
  (provisional).** New `AI/Real_Data_Code/size_limit.py` (+ `test_size_limit.py`, 6 tests); results in
  `Calibration/Imaging Work/analysis/size_limit_2026-10-16/` (report.md, size_limit.json, model_grid.csv, figure).
  - Model: an opaque disc (bead tau 0.11) * Gaussian PSF, 10 um pixels at random sub-pixel positions, the measured
    single-frame noise (0.022 in T, CCD 125754), measured with the beads' own code. Optical blur at best focus chi0 =
    11.4 um (so a 76 um disc reads the real 13.75 um); the real beads' edge offset (+7.8 um, sharpest falling) added
    as a constant.
  - **Check against the real beads: good near focus (chi <~ 16 um), but with more blur real beads grow faster than
    a Gaussian PSF predicts** (median 6-12 %; at chi 30 a 56 um bead reads ~1.37x vs the model's 1.15x): the real
    defocus blur is more disc-like. So the model's limits are sound for a tight focus rule and optimistic for loose
    ones, and Phase 3's look-up table must be MEASURED on beads, not taken from the model.
  - **d_min** ("confident": median bias within +-10 % after the edge correction, >= 90 % found and passed): half-max
    30 um at chi <= 15, 35 um at chi <= 20 / 25 (~3-3.5 px; the literature's ~3 px detection, ~5 px resolution).
    Blaisot's correction gives 20 um in the model, but only because the model is his; the real beads' corrected sizes
    level off 15-25 % high off focus, so unverified (the reticle's 14-28 um dots test it). Detection sets no limit:
    the model finds >= 96 % from 15 um, and the AI's recall is 92-96 % flat from ~20 um (2026-10-02 benchmark).
  - **New: a tight chi cut makes the counting volume depend on size.** Small droplets' chi is noisier, so more come in
    from outside the nominal volume: at chi <= 15, 37-51 % of the passed 20-50 um droplets (8-13 % at 80-150 um), so
    small ones would be over-counted ~1.7x; at chi <= 20, 16-30 % (~1.3x). Supports the two-tier design: a looser
    chi_vol for counting, sizes from the table; Phase 5 needs the effective depth per size.
  - On CCD 125754, ~36 % of in-focus droplets read below 30 um (their true sizes are smaller): with d_min 30 these
    would be counted, not sized. The profile records the provisional d_min (`calibration.d_min_provisional`); nothing
    reads it yet.

- 2026-10-15 late (Mac): **Sizer 3.0.0 plan approved; Phase 0 done: one optics profile, no number changes.**
  - `config/optics/lens1_2026-10.json` holds the scale (10.0 um/px) and placeholders for the Phase 3 calibration;
    `AI/Real_Data_Code/optics.py` picks a capture's profile: `HPATR_OPTICS_PROFILE`, else the run's run_summary field
    "Optics profile" (GUI_Clean now writes it), else the capture date in the path, else the only profile; with two
    set-ups and no way to tell it refuses rather than guess. A profile added while a program runs is picked up.
  - Every hard-coded 10 um/px now reads it (11 places: measure_run, classical_liquid, bead_calibration,
    extract_candidates, score_v2, validation_to_coco, run_stats, preview_predictions, composite, window_check, plus
    the 1e-4 mm2/px in run_metrics, figures_extra and GUI_Clean). measure_run, classical_liquid and the bead script
    take the run's own profile; summary.json / classical_summary.json / the bead result record `optics_profile`.
  - Checked: CCD run 125754 re-measured into a temp folder: droplet_sizes.csv and object_areas.csv byte-identical;
    D32 54.04, atomised and counts identical; per_frame.csv differs only by the newer mean_d_in_focus_um column.
    The liquid stage too: classical_per_frame.csv and classical_components.csv byte-identical, every summary
    value the same (atomised 19.99 % by area). New tests: `test_optics.py` (6). Full suite 900 passed, 0 skipped
    (LaCie plugged in, so the real-data tests ran too; 17.5 min). Python 3.9 compile + annotation scan clean.

- 2026-10-15 late (Mac): **Falling beads bead by bead, and what it means.** `bead_calibration.falling_detail`
  re-measures every AI droplet of each pour exactly as the pipeline does (2.2.0) plus its blur width chi, contrast and
  nearest neighbour (`analysis/2026-10-15/falling_beads.csv`, ~45,000 rows; `fig_falling_chi.png`; report section).
  - **Falling beads lie on the static through-focus curve** (size / certified against chi): they are ordinary beads
    seen off focus. The pipeline counts them in focus out to chi ~60 um (median chi of the counted ones 36 um on 98.1).
  - **A blur-width rule brings them back** (isolated, chi <= 15 / 20 um; median vs certificate): 37.36 +54.0 ->
    +13.0 / +24.5 %; 56.28 +36.0 -> +13.4 / +18.6; 76.39 +21.8 -> +6.5 / +8.5; 98.1 +15.6 -> +6.0 / +7.9; 155.8 +8.2
    -> +4.5 / +5.4. It keeps 7-14 % (chi <= 15) of what the pipeline counts now: the sampled depth shrinks from ~10 mm
    to < 1 mm. 37 um needs the tighter cut (below 40 um the pipeline sizes from the AI mask).
  - **CORRECTION to the "~8.6 % scale error" read earlier this evening:** every falling size reaches chi ~13 um at its
    sharpest, but the static 155.8 slide read chi 21 um "at focus", so that slide was probably ~1 mm off focus (focused
    by eye). The sharpest falling beads, 56-155.8 um, read a FIXED offset: +7.5 / +5.0 / +5.9 / +6.9 um, fit slope
    1.002, offset +6.1 um. So edge (~0.6 px of diameter) now looks likelier than scale; the reticle settles it.
  - **The AI on pure spheres:** it calls far-out-of-focus beads "filament" or "blob" (big faint round discs; checked by
    eye on 98.1): 2.5-16 % of detections, but enough area that a 100 %-droplet scene reads 62-89 % atomised by area
    (37.36 89, 56.28 82, 76.39 62, 98.1 65, 155.8 83). In spray the same happens to droplets well off the plane, so
    the atomised fraction reads low by an amount that depends on spray depth.
  - **Spray check** (CCD 125754 11,000 sccm and 135146 7,000 sccm, 1.2 mm, every 10th frame): median chi of the
    in-focus droplets 18 um (the spray sits nearer focus than the pours); ~60 % within chi 20 um. chi <= 20 would move
    D32 55.7 -> 37.3 / 53.7 -> 35.5 um and the mean ~39 -> 31 um. Not a result until the cut is proved per size.
  - **The mixed slide has no usable big beads anywhere** (~98 um: 8 round and isolated, 1 in the sparse area; ~156 um:
    none), so there is no through-focus data above 76 um. Rig ask: the same -8..+8 mm series on the 155.8, 98.1 and
    76.39 single-size slides (~1 h; Notes `BEAD 155.8 z-1.25` etc.; no code change).
  - Deck updated to 20 slides (falling bead-by-bead, the AI on spheres, the spray check, what it means, a DRAFT plan
    for sizer 3.0.0) and re-exported to `analysis/2026-10-15/slides/` (PDF + HTML). Ben (2026-10-15): with a
    calibrated focus rule the size special cases (sharpness rule >= 50 um, AI mask < 40 um) can go.

- 2026-10-15 evening (Mac): **Bead calibration, first numbers (PRELIMINARY: from 40-frame averaged stills; the
  pours and the certificates' spreads not in yet).** `bead_calibration.py` 1.0 could not cope with the real slides
  (it counted specks as beads: on the 155.8 slide the median object is a 48 um speck), so 1.1.0, after three
  attempts (deck above): only dark (T_min < 0.35), round (core axis ratio <= 1.4), isolated beads, in the sparse
  128-px tiles; single-size slides within 20 % of their most common size; a boxed PNG per capture. Beads used:
  155.8: 23, 98.1: 42, 76.39: 198 (+2 mix), 56.28: 484 (+31), 37.36: 722 (+108).
  - (SEE the later entry: the scale reading below is probably wrong; edge offset likelier.) **At focus the current sizer (2.2.0, half-max on a T < 0.95 stand-in mask) reads every size ~8.6 % LARGE**
    (37.36 +8.9, 56.28 +13.4, 76.39 +4.5, 98.1 +7.6, 155.8 +8.6 %): the same share for 37 and 155.8 um, the
    signature of a SCALE error, not an edge error (that would add fixed um). One common factor, 9.21 um/px instead
    of 10, brings three sizes within 1 % and the other two within 4.5 %. 10 um/px has never been measured: the
    reticle's dot array settles it. Hypothesis, not a correction.
  - No rings: at this magnification the glass beads look opaque. At focus 91-98 % count as in focus; the 2.2.0
    rule rejects 2-10 %.
  - **Through focus (mixed slide, 108 / 31 / 2 beads of 37 / 56 / 76 um; none of 98 / 155.8 in its sparse part):
    the current rule counts beads as in focus over ~9 / 12 / 15 mm, but their size holds within 5 % over only
    0.8 / 1.2 / 2.5 mm** (a 37 um bead 4 mm out reads ~1.8x). Blur width chi = ~13 um at focus, +~8 um per mm,
    the same for every size. So the in-focus count samples a slab ~10-15 mm deep, deeper for bigger drops.
  - Cd (same evening, `Calibration/Orifice Cd/analysis/2026-10-15/`, not written to the Cd table): 0.5 mm 0.844,
    0.8 mm 0.814, **1.2 mm 0.527 at every step**: not a leak (that reads high), not line loss or ambient; the insert
    itself passes ~35 % less gas (as if ~0.96 mm). Check for silicone residue / measure the bore.
  - Found on the way: `bead_calibration.find_captures` and `run_ai_where.select_runs` skipped every run when the
    folder given sat under a path with a '.'/'_' part (e.g. ~/.claude): fixed in bead_calibration (checks only
    below the folder given); run_ai_where still has it (harmless for D:\Calibration\..., fix after tonight).
  - **Falling beads (home PC's step 2) against the static ones: the falling error is DEFOCUS, not the edge.** The
    home PC read it as "0.94 x nominal + 22 um, a fixed offset at the edge". But the pours' in-focus sizes are narrow
    (not a focus peak with a tail), 155.8 falling = static at focus (168.5 vs 169.3), and static beads at z = +2.5 mm
    read 1.54 / 1.33 / 1.18 x (37 / 56 / 76 um) against falling 1.54 / 1.36 / 1.22 (misfit 1.8 %; -2.5 mm 4.0 %). A
    hand pour does not fall on the focal plane, and the current rule accepts beads 2.5 mm out. Now computed by
    `bead_calibration.equivalent_defocus` and printed in the report. Consequence for spray: droplets a few mm off the
    plane are counted in focus and oversized, most for the small ones.
  - Tests: the run-sheet test and the GUI window checks read the LIVE day sheet, so cutting it to the 36 bead
    rows on the day (b55c142) broke 1 test + 7 window checks. The test now checks the sheet as run; the window
    checks use a frozen copy of the 57-row plan (`tests/data/run_sheet_57_rows_2026-10-15.csv`). Six new bead
    tests (specks, touching pairs, pale debris outnumbering beads, the sparse region + PNG, loose PCC cines).

- 2026-10-15 18:19-19:05 (home PC): **Step 2 DONE: the AI on the five falling-bead pours**, sizer 2.2.0, no failures
  (exit 0 both passes; Python 3.9 imports fine with the 057a0f3 fixes). Five run folders under `.../falling/<file name>/`;
  155.8 is the stride-2 result (1,349 frames, replaced its stride-10 one), the rest stride 10. 46 min in all (copy
  ~48 MB/s; inference 0.45 s/frame sparse, 1.75 s/frame on the crowded 37.36 pour). Line 5, in-focus detections
  (sightings, not distinct beads) and median in-focus diameter:

  | Nominal (um) | Detected | In focus | Median (um) | Error (um) |
  |---|---|---|---|---|
  | 37.36 | 23,455 | 13,837 | 57.5 | +20.1 |
  | 56.28 | 10,370 | 5,421 | 76.5 | +20.2 |
  | 76.39 | 7,045 | 3,288 | 93.0 | +16.6 |
  | 98.1 | 3,182 | 2,052 | 113.4 | +15.3 |
  | 155.8 (stride 2) | 8,986 | 6,496 | 168.5 | +12.7 |

  All sizes far above the >= 20 target; no stride-1 re-run needed. **The sizer reads falling beads high, almost
  linearly: measured ~= 0.94 x nominal + 22 um (all five within ~1.3 um)**, i.e. a large fixed offset (edge placement:
  half-max on a blurred edge / ~1-2 px each side) plus a small ~6% scale error. 155.8's median is the same at stride
  10 and 2 (168.5). 37.36 is crowded (~150 detections/frame, 41% out of focus), so merged neighbours may add to its
  error. For step 4, against the sandwich stills at focus (step 3); nothing changed in the sizer.
- 2026-10-15 (lab PC): **Calibration day, no silicone.** Cd tests DONE for 1.2 / 0.8 / 0.5 mm (11:12-11:34,
  `Calibration/Orifice Cd/2026/10/15/`, not yet analysed). Bead captures in `Calibration/Imaging Work/2026/10/15/`:
  one capture per single-size sandwich at focus (155.8 -> 37.36; no extra patches or bg: the slide cannot move
  sideways, and the background comes from each photo), then the mixed sandwich through focus -8 to +8 mm (manual
  stage, ±8 mm range); every run checked: one 1.15 GB cine and the right Notes. Falling beads recorded in PCC to
  `.../falling/`. **Falling beads: only ~10% of a pour's frames contain beads (Ben), so stride 10 can miss a
  pour's large beads.** Decided: keep stride 10 and trim each cine in PCC to the stretch with beads; re-run a
  pour at `--stride 1` if a size ends up with too few in-focus beads (docs/BEAD_CALIBRATION.md). One pour per
  size is enough if it has enough beads (the static captures carry the size bias and DOF). GUI_Clean on the rig: run sheet, Save under and the 1 s post-trigger
  worked; bead rows (0.5 mm nudge, 3.4 s) pop up "Test shorter than the video": press Trigger early.

- 2026-10-15 (Mac): **Python 3.9 (home PC Detectron env): eleven signature annotations fixed.** `X | None` in a
  function signature is evaluated at import and fails on 3.9. Affected:
  - GUI_Clean.py, 8 (4 since August/October, 4 from 2026-10-14). So GUI_Clean has NEVER imported on the home PC:
    this, not only Cone_4, is why bug 6 (no GUI formula: no atomised liquid flow or GLR there) persisted;
  - liquid_volume.py: liquid stage 2.3.0 would have crashed in the home PC's batch;
  - remeasure_liquid.py and draw_more_classical.py.
  All quoted. A scan of 94 files finds no 3.9-unsafe annotation left, and all compile with a real Python 3.9
  (the Mac's 'Hello' env). Not yet run on the home PC itself.

- 2026-10-14 (Mac): **Size calibration with glass beads, built for Thursday morning** (plan
  `~/.claude/plans/cozy-orbiting-swing.md`; procedure `docs/BEAD_CALIBRATION.md`). Beads 37.36 / 56.28 / 76.39 /
  98.1 / 155.8 um (certified) and a micrometer slide holder. The method is Blaisot & Yon 2005 (Exp. Fluids
  39:977-994, verified; Wang 2022 FocGAN has no physical calibration).
  - Captures are run-sheet rows. The run sheet has two new optional columns:
    - 'Save under' routes a run to e.g. `Calibration/Imaging Work` instead of Experiments (one helper,
      `_run_base`, for Start, save and preview);
    - 'Post-trigger (s)' sets the camera (Apply Config) to 1 s for bead rows and back to 13 s for spray rows,
      without the standard-capture question for that field only. SETUP instructions pop up.
  - Thursday's sheet is rebuilt in this order:
    - 43 sandwich captures: a mixed sandwich at 23 z from -4 to +4 mm, 4 focus patches + bg, 5 single-size
      slides x (2 + bg);
    - then the 3 Cd tests (saved under `Calibration/Orifice Cd`);
    - then the 16 spray runs;
    - last, the falling beads: 2 pours per size, 10 runs, after clearing up, optics untouched. The analysis
      pools the two pours.
  - New `AI/Real_Data_Code/bead_calibration.py` (Mac, no AI for static beads):
    - averages each capture (40 frames);
    - background from the frame itself, two passes, < 1 % on a gradient; dust from bead-free captures
      dropped (an averaged spray frame shows ~200 specks);
    - follows each bead through z;
    - per bead: the current sizer exactly (measure_run functions, a T < 0.95 mask in place of the AI's),
      d(l) curves, ring flag, and Blaisot C, chi and the contrast-corrected size, from the model computed
      numerically;
    - outputs: bias at focus, l*, ring and 2.2.0-rejection shares, effective DOF of the current rule
      (the 1/DOF weight), size-stable range, chi(z) fit; falling beads from the AI's droplet_sizes.csv;
      reticle array scale ready.
  - On synthetic Blaisot-model beads: chi recovered within ~1-2 um, contrast-corrected size within 2 %.
  - `Calibration/Imaging Work/README.md` + `targets.json` on the LaCie (Ben: add supplier, lot, spreads).
  - Tests: test_bead_calibration (11), run-sheet window checks 9.
  - Falling-bead AI at home: new `AI/Real_Data_Code/run_ai_where.py` runs the AI chain (process_capture) only on
    runs whose Notes start with given text (`--notes "BEAD fall"`; `--dry-run`; restartable), so the 48 static
    captures in the same day folder are not inferred. Command in docs/BEAD_CALIBRATION.md. Tests:
    test_run_ai_where (2).

- 2026-10-14 (Mac): **GUI_Clean top bar: master_log button, AFG light removed** (untried on the rig). A small
  button right of LaCie opens master_log.xlsx. GREEN = safe; RED and not clickable while a run is going, its
  save is pending, a save is being written, or the AI's re-save is still to come (Excel locks the file and
  the save would fail). START also checks (Windows) whether master_log is open and asks before starting, as a
  run's save fails while Excel holds it. master_log's path now comes from one helper
  (`_master_log_path`) for the save and the button. Tab padding 24 -> 18 px so the nine tabs fit a ~1,600 px
  window (all fit at 1,920). Checks: tests/gui_window_checks.py (8, run by test_run_sheet.py).

- 2026-10-14 (Mac): **GUI_Clean Run sheet tab** (after Extremes; untried on the rig). Load a .csv/.xlsx (the
  app's next_runs.csv works as it is; columns matched loosely): the next run's gas, RPM, feed, travel, insert,
  orifice length and Notes are filled in. Only once the end-of-run save to master_log has FINISHED does it ask
  'Did this run go OK?' (with a box to add to the run's Notes): Yes fills in the next run; No appends
  '[bad run, redone]' to the saved run's Notes (re-saved) and keeps the row to redo; Decide later changes
  nothing. A later save of the finished run (e.g. after the AI) keeps that run's own Notes (`_notes_lock`), not
  the next run's. Settings that differ from the sheet are listed in the question; a change of insert pops up a
  reminder (with a Cd test's instructions); nothing is filled in during a run. Progress lives on the LOCAL disk
  (~/.hpatr/run_sheet_state.json) and is resumed after a restart without filling the boxes. New
  `src/gui/run_sheet.py` (no Qt). Thursday's sheet: `docs/notes/2026-10-15_thursday_run_sheet.csv` (also
  `Experiments/Run sheets/` on the LaCie). The LaCie probe now answers through a Qt signal (a QTimer posted from
  its thread could hit a deleted window). Tests: test_run_sheet (5 + the real window's flows in a separate
  process, tests/gui_run_sheet_checks.py: building and deleting GUI_Clean's window crashes Qt, see Known bugs).

- 2026-10-14 (Mac): **Pressure / gas log: gaps then jumps, explained and fixed.** Scan of the 33 CCD runs
  (`run_summary.xlsx` Pressure sheets, ~0.22 s spacing): 30 runs have a 1-4.3 s gap followed by a burst of
  5-21 readings at one instant, 12 of them inside the camera window. Cause: each Alicat reading was stamped
  when the GUI THREAD handled it, and the GUI thread stalled; the reader kept reading (burst size = gap /
  0.2 s), so the readings were queued, then logged together. The Portenta reader stalled at the same
  moments (serial log silent 4-5 s, then a burst). Both touch the LaCie: `find_lacie_drive()` every 5 s on
  the GUI thread, and `log_serial` opening the LaCie log per line on the reader thread; most stalls fell
  25-70 s after the previous run's 15 GB cine finished saving. Effect on the CCD numbers: P0 <= 0.005 bar,
  delivered gas <= 0.6% on flow-controlled runs, up to 6% on the pulsing pressure-limited ones (110227:
  2,813 -> 2,639 sccm); no regime or conclusion changes. FIXED in GUI_Clean (untried on the rig): readings
  stamped at read time on the reader thread; serial-log lines queued to one writer thread (a busy drive no
  longer holds up the Portenta reader, whose stall could block the stepper once the board's TX buffer
  fills); the LaCie poll on a worker thread. Old logs repaired in the analysis: `operating.respace_queued`
  spreads a burst back across its stall instead of dropping all but one reading. Tests:
  test_pressure_log_timing (6).

- 2026-10-14 (Mac): **Busiest / mean-diameter frames drawn the classical way.** measure_run's drawings of
  the 2x2 slide frames outlined filaments thinly, so un-atomised liquid was hard to see (Ben). The liquid
  stage (`classical_liquid.py`, extremes mode) now draws those frames too (un-atomised liquid filled, classical
  atomised % printed; `more_extreme_frames` in its summary); the 2x2 slides, `gallery_more` sheets and
  GUI_Clean's Extremes tab prefer that drawing, and the slide notes say which drawing is shown. New
  `AI/Real_Data_Code/draw_more_classical.py` back-fills older runs: liquid stage re-run into a temp folder,
  numbers gated against the run's summary, only the new PNGs copied (about 2 min a run alone, ~4 min three at
  a time: it re-reads every frame for the window mask). CCD day back-filled 33/33, numbers unchanged in every
  run; `Taguchi/CCD/Rec CCD 4 factor 20-60um/` re-published (157 slides, all 33 grids classical, best setting
  unchanged: 11,000 / 100 / 5,000 / 1.2). Then a FAST path: a run with no window drops (26 of 33) is
  re-measured on the drawn frames only, ~4 s instead of ~2 min, per-frame rows gated (checked on 105301:
  images byte-identical to the full pass). Tests: test_more_extremes +2.

- 2026-10-14 (Mac): **Throughput is the default objective.** The spray is collected and size-filtered (Ben), so
  `rsm_responses.DEFAULT_GOALS` is now in-band droplets per second (`rate_band`, importance 3) + atomised fraction
  (importance 1), and `run_metrics.DEFAULT_BAND_UM` is 20-60 um (was 30-50; the band starts at 4 px of area,
  22.6 um). New Model pages start there; a saved `rsm_model.json` keeps its own goals. Runs without the rate
  (before liquid 2.3.0, or no syringe flow) are left with atomised fraction. The Taguchi tab's band-count
  responses also use the new band. Docs: definitions, RSM_GUIDE, IMAGING_PIPELINE_REFERENCE. Tests:
  test_tab_settings (band default), test_gas_regimes +1.

- 2026-10-13 (Mac): **Silicone film at the exit, a covariate; flux and film in the workbooks and decks.** New
  `orifice.py` (gas properties by the run's Gas tag, ideal gas-only flux choked/subsonic, Cd lookup from the new
  `orifice_cd.json` -- all Cd null = ideal 1.0 until the test -- and the split: gas share alpha, silicone speed u_L,
  annular film h). Covariate film_um beside GLR and the flux; fig_film_thickness, fig_orifice_model (a diagram with
  the maths); a "Silicone film at exit" workbook sheet in both publishes (per-run table, the diagram beside it, the
  maths and caveats in text); report sections; deck slides "How the gas flux and the silicone film are estimated"
  + flux + film (Taguchi and CCD). No-spray runs are now left out of every covariate FIT (GLR, flux, film) but
  plotted (grey x): the flux exponent on atomised fraction is +0.36 [0.29, 0.42] without the two dribbles (was
  +0.86); film exponent -0.46, r -0.76; Spearman film -0.90 / flux +0.91 over 31 spraying runs. CCD re-analysis
  re-published (deck slides 58-60). `orifice_cd.py` now uses `orifice.py`'s formula (one source). Tests:
  test_gas_flux +6, test_deck +1, test_gas_regimes +1; full suite 851 passed. The 9x3 Taguchi output was not
  re-published (its runs do have gas logs and camera windows, but are still liquid stage 2.2.0).

- 2026-10-13 (Mac): **Orifice Cd test ready; lamella AI found and compared.** New `AI/Real_Data_Code/orifice_cd.py`
  (steady gas steps from gas-only runs' logs -> Cd per insert, choked steps preferred, subsonic fallback flagged,
  optional line-loss run, `--write` updates `src/ai/Taguchi_Analysis_UI/orifice_cd.json`) and the rig procedure
  `docs/ORIFICE_CD_TEST.md` (Speed 0 static run, gas ladder 2,000-12,000 sccm, Notes "CD TEST ..."). Gas alone
  chokes 0.5 mm (from ~4,000 sccm) and 0.8 mm (10-12k); 1.2 mm is subsonic only (needs the line-loss run); 1.8 mm
  cannot be measured this way (<= 1.07 barA). Tests: test_orifice_cd (2). The lamella AI's only batch output
  (`Lamella/Tester_Tiffs/Output_Tester/lamella_thickness.csv`, 36 frames) is from
  `2026/06/25/133838_NNoNozzle_5.0BAR` (0.5 mm add-on + 1.2 mm orifice, feed 4,000, ~2.65 barA): ~0.38 mm of
  silicone per wall, against 0.31-0.35 mm from the annular estimate for the CCD 1.2 mm runs at similar pressure
  (phase-12 note).

- 2026-10-13 (Mac): **Orifice length recorded (GUI_Clean).** Nozzle card: "Orifice length" (mm, hardware state like
  bubbler height, remembered; a non-blocking reminder at Start when empty). run_summary Metadata gains
  'Orifice length (mm)' (a number, or NOT RECORDED); master_log gains 'Orifice Length (mm)' as column C (19 columns,
  A..S) via `migrate_master_orifice_length()`, which runs on the next save after the mean-diameter migration.
  Checked with a full offscreen save against a COPY of the live master_log: header right, the new row's values
  are numbers, all 292 existing images moved one row down and one column right, old rows blank in C. The lab PC's
  log migrates itself on its first save after `git pull`.
- 2026-10-13 (Mac): **Gas mass flux at the orifice, a covariate (phase 12 decision).** `covariates.py`: per run
  G = delivered gas mass flow / orifice area (kg/m2/s; camera-window gas > achieved > set point; the run's recorded
  gas density, none guessed), its standard-density exit velocity equivalent, orifice length and L/D (from
  run_summary 'Orifice length (mm)', read back from a GUI_Clean-written file: OK). Trends beside GLR; new
  fig_gas_flux (coloured by orifice, hollow = did not get its set gas, velocity on a top axis), report section,
  deck slides (Taguchi and RSM; the RSM report now takes the shared analysis), workbook sheets. Loud warning when
  runs in one analysis have different orifice lengths (a hidden factor), softer when only some record it. CCD day:
  C7 522, C8 537, 0.8 mm 342, 1.2 mm 152, 1.8 mm 68 kg/m2/s; atomised fraction r = +0.85. Tests: test_gas_flux (7)
  + 2; full suite 841 passed. Open: the two no-spray dribbles (G 3-5) dominate the power-law exponent (+0.86);
  Ben to say whether no-spray runs leave the covariate fits (recommended).

- 2026-10-13 (Mac): **Throughput is the objective; goal ramps reach the surface; master_log droplets/s.**
  Ben: the spray is collected and size-filtered, so the target is in-band droplets produced per second; band
  **20-60 um**. (1) Fix: a goal's blank "1 at (best)" is now the best its fitted surface reaches in the tested region
  (`rsm_responses.reach_surface`, `RsmResults.surface_best`; report note; Model-page text; RSM_GUIDE), not the best
  run seen. Before, every setting predicted beyond the best run scored a flat 1 and the optimiser stopped at the
  first it tried (10,740 sccm; then feed 3,000 when maximising a rate that rises with feed), which also killed
  the steepest-ascent and new-CCD suggestions. Tests in test_gas_regimes (+2). (2) Throughput analysis, 20-60 um,
  goals in-band rate x3 + atomised fraction x1 (`Taguchi/CCD/Rec CCD 4 factor 20-60um/`, `reanalyse_ccd.py
  --model --band`): best 11,000 sccm / 100 rpm / feed 5,000 / 1.2 mm, predicted 288k in-band droplets/s;
  steepest ascent to 12,000 / 0-50 rpm / feed 5,200-5,300 (~330k/s, extrapolated); suggested next CCD gas
  8-12k, rpm 0-800, feed 4,000-6,000. Best measured: C7 280k/s (0.5 mm ceiling recipe), but its twin C8 gave 187k/s.
  (3) master_log: new column N "Droplets/s (20-60 um)" (`MASTER_RATE_BAND_UM`, `droplet_rate_band`,
  `migrate_master_droplet_rate`; 20 columns A..T), written as a NUMBER by GUI_Clean after the AI chain (same maths
  as the app, matches it to the whole droplet); the 33 CCD rows back-filled (C7 280,194); backup in
  `Logs/Backups/master_log BACKUP 2026-10-13 before droplets per s.xlsx`. The live log is now 20 columns:
  **the lab PC must `git pull` BEFORE its next capture** -- the old GUI stamps its 17-column headers and would
  write rows into the wrong columns.
  Decks: every goal response now gets map slides (`rsm_figures.mapped_responses`: goals, then the headline
  responses, lag-1, pressure; the rate goal had none), and a "How droplets per second are estimated" cards slide
  (`deck.rate_cards`, both decks, when any run has a rate). 20-60 um deck: 157 slides, rate maps 4-8, the
  explanation 67. Full suite 858 passed.

- 2026-10-13 (Mac): **Phase 10, more extreme frames.** `measure_run.py`: per-frame body now `measure_frame()`;
  `pick_more_extremes()` / `write_more_extremes()` add the frames with the most in-focus droplets, the most droplets
  in total and the largest / smallest mean in-focus diameter (frames with >= `MIN_DROPLETS_FOR_MEAN` = 10 in-focus
  droplets) into `droplets_<thr>/extreme_frames_more/` (PNGs + index.json / index.csv), summary.json
  `more_extreme_frames`, per_frame.csv gains `mean_d_in_focus_um` as its last column; everything else byte-identical
  (checked on 105301). Back-fill without the model: new `render_more_extremes.py` (re-measures only the chosen
  frames from predictions.json, gate against per_frame.csv, writes via .partial/): all 33 CCD runs done, 33/33
  passed, ~2 min, only the new folders written. App: `figures_extra.gallery_more()` (galleries/gallery_more_<c>.png,
  4 columns), in the Taguchi and RSM reports and decks. GUI_Clean Extremes tab shows the four. Tests:
  test_more_extremes (16); full suite 832 passed. DECIDED (Ben, 2026-10-13): the mean-diameter extremes' floor is
  half the run's median in-focus count per frame, never below 10 (`mean_floor`; was a flat 10, which picked thin
  frames: 130918's largest mean 57.9 um from 17 droplets -> now 55.1 um from 34). All 33 CCD runs redrawn (gates
  passed; the chosen frames now have a median 35-42 droplets behind them, was 22-23); index.json records the floor.
  test_more_extremes +1. Decks (Taguchi and CCD): these frames are now one 2x2 slide PER RUN (most in focus, most in
  total / smallest, largest mean; `deck._Deck.grid`, `tw_more_run`, `more_grid_slides`), filling the slide below the
  title (3.2 x 1.8 in per frame; 16:9 frames make a 16:9 grid, so the height sets it), captions with the counts and
  means, the legend and the floor rule in the notes; the per-condition strip stays in the report. CCD deck: 150
  slides, grids 118-150 (grid frames embedded as 1000 px JPEGs, `deck._slide_jpeg`: the full-size PNGs had put the
  deck at 457 MB, now ~54 MB). Ben's own run with the recommended goals (atomised x3, in-band rate x2, D32 x1, CV x1,
  mean diameter not a goal): `Taguchi/CCD/Rec CCD 4 factor/` -> best 11,000 sccm / 100 rpm / feed ~4,100 / 1.2 mm
  (the rpm from a weak rpm x orifice term in the rate, p 0.03), best observed 125754; re-published headless with its
  own model (`reanalyse_ccd.py --model`). Confirmed: the per-frame mean uses in-focus droplets only. test_more_extremes +1. No
  `pipeline_spec.OUTPUTS` entry for the folder yet.

- 2026-10-13 (Mac): **Phase 11 (window drops, GUI side) and master_log numbers.** New `src/gui/window_check.py`
  (numpy + OpenCV, no Qt): live frame / clean reference, normalised by its median, smoothed; a spot = a piece
  < 0.90 of the clean window, >= 400 px, with a core < 0.80. Set on the CCD backgrounds: C20's drop reads 0.15 at
  its core; consecutive clean backgrounds read clean. GUI_Clean Camera tab "WINDOW CHECK" card (Save clean
  reference to ~/.hpatr/window_reference.npz, Check now, "Check at Start Experiment", remembered); Start
  Experiment checks before anything moves, shows new spots boxed, "Cancel: wipe first" / "Start anyway";
  run_summary gains "Window check (before run)"; How To updated; every run sheet's summary now says to wipe or dry
  the window before every run (`rsm_design.BEFORE_EVERY_RUN`). Tests: test_window_check (10). Offscreen-tested with
  a fake camera; NOT yet on the rig (thresholds may need tuning there). Phase 10 GUI side: the Extremes tab gains
  four panels (most in-focus, most total, smallest / largest mean diameter) read from
  `droplets_<thr>/extreme_frames_more/index.json`. master_log: GUI_Clean now writes Speed, Motor Travel, Bubbler
  RPM and Bubbler Height as NUMBERS (`as_number`; they were text from the entry boxes) in master_log and
  run_summary; the existing 263 text cells (Speed 132, Travel 131) converted and swapped in at 16:0x (backup
  `Logs/Backups/master_log BACKUP 2026-10-13 before numbers.xlsx`; re-audited: no numbers stored as text outside Notes). Phase 12 evidence and opinion: `docs/notes/2026-10-13_phase12_physical_variables.md`
  (gas exit mass flux orders both regimes, Spearman +0.91; GLR -0.21; P0 a symptom; keep set points as factors,
  add the flux as a covariate).

- 2026-10-13: **Gas flow can go to 12,000 sccm** (Ben): 11,000 was the CCD day's top set point, chosen for
  headroom. Already the app's `rsm_design.RIG_LIMITS` and GUI_Clean's entry range; the next design should use
  it (atomised fraction and the production rate still rising at 11,000).
- 2026-10-13 (Mac): **CCD follow-up, phases 8 and 9; three RSM fixes; liquid 2.3.0 re-run.**
  Liquid stage 2.3.0 re-run on the Mac for all 33 CCD runs (45 min, 0 failed; 2.2.0 outputs kept in
  `<run>/shadowgraph/analysis/_liquid2.2.0/`): atomised % rose in 10 runs (window drops / static pieces),
  e.g. C20 5.96 -> 10.51, C9 8.84 -> 16.38. (8) Rate, read-only (`docs/notes/2026-10-13_droplet_rate_investigation.md`):
  mass balance gives the liquid's residence time in the field, 1.4-2.8 ms (4-8 m/s), falling in proportion to
  gas; along the 1.2 mm gas axis the in-focus count is flat while the production rate doubles, so count goals
  under-reward gas (rate vs concentration Spearman 0.84); the 390 fps cines cannot give velocity (nothing pairs
  across 2.56 ms; 4 us blur bound <= ~4 m/s, optical); definitions.md decorrelation section corrected (transit
  < 1 frame). Ben to decide: a mass-balance rate response, and a 10-min exposure series on the rig. (9) CCD
  re-analysed headless into `Taguchi/CCD/CCD 4-factor 12-10-2026 reanalysis 13-10-2026/`
  (`docs/notes/2026-10-13_CCD_reanalysis.md`): 21 flow-controlled runs in the fit; atomised fraction = gas (+) and
  orifice (-, ln) only, simplified predicted R2 0.89, no lack of fit; rpm and feed free there; 0 rpm control =
  centres; best ~10,700 sccm, 1.2 mm; 0.8 mm check below the ln extrapolation (orifice^2 needs 0.8 in the next
  design); pressure-limited block: set gas no effect, rpm +741 and feed -1,960 sccm delivered; C7/C8 (35%) are the
  day's best and pressure-limited. Fixed (tests in test_gas_regimes): the goal gate now judges the SIMPLIFIED
  model's predicted R2 (`ResponseFit.used` / `r2_pred_used`, `weak_goals`; the full quadratic read -0.28 at 21
  runs / 14 terms and dropped every goal); "Strengthen the model" runs stay inside the fitted span and say which
  sizes were held back and why; factors no steering surface uses (`free_factors`, `RsmResults.free`) are held at
  the centre and named, not reported as edge optima (the optimiser had returned its first grid value). master_log:
  the 33 atomised % cells with 2.3.0 values are prepared and checked (only column L, 26 cells change; 292 images
  byte-identical) at `scratchpad/mlog/master_log_23.xlsx`, backup `Logs/master_log BACKUP 2026-10-13 before liquid
  2.3.0.xlsx` made. Copied in at Ben's go-ahead after Excel had re-saved the file on close (cells unchanged;
  Excel had stored identical images once, 91 -> 27 MB); the update was re-applied to that file, only column L
  changed (26 cells), all 292 image positions kept. **Opt-in mass-balance rate responses** (`run_metrics`:
  `rate`, `rate_band`, `mass_balance_rate`; syringe flow x atomised fraction by volume / pi/6 <d^3>, with a frame
  bootstrap; blank before liquid 2.3.0): a rate that does not fall when gas speeds the spray up. Tests in
  test_run_metrics (+3).

- 2026-10-13 (Mac): **CCD follow-up, phases 5 and 6.** (5) GUI_Clean: a live "Gas regime" readout beside the
  MFC values (flow-controlled / PRESSURE-LIMITED / GAS SHORT after > 5% short for 3 s; logged once per
  episode, orange log border), and run_summary Metadata gains "Gas delivered in camera window (sccm)", its
  p10-p90, "Upstream pressure in camera window (barA)", "Gas regime", "Gas settled", computed with the
  analysis app's own `operating.py` (imported by the GUI; numpy only). Offscreen-tested; NOT yet on the
  rig. (6) Orifice on a log scale: `FactorLevels.log` + `decode()`, Model page "Log scale" tick per factor
  (default orifice; older saved models get the default), passed as `log_scale`. Found and fixed with it:
  with the pressure-limited runs left out, the coding still spanned 0.5-1.8 mm, so the optimiser searched
  (and could recommend) unfitted orifices; now the levels refit to the fitted runs (1.2-1.8) and settable
  levels outside the span are not offered (warning names them). Tests: test_gas_regimes (+2),
  test_tab_rsm (Model page), test_rsm_recommend's linear-world fixture now asks for linear coding.

- 2026-10-13 (Mac): **Liquid stage 2.3.0** (`classical_liquid.py`, new `liquid_volume.py`,
  `remeasure_liquid.py`). Two passes: a persistence map of un-atomised liquid, then areas with a WINDOW
  MASK (still, compact, flat-topped pieces un-atomised in >= 20% of frames: drops that landed mid-run);
  out-of-focus model pieces with mean T >= 0.97 are not liquid (drops already divided out); per-frame
  volumes (OpenCV only: the Windows env does not promise scipy / scikit-image) for a SECONDARY
  volume-based atomised fraction. Rules off = bit-identical to 2.2.0 (C20, 508 frames). Tests:
  `test_liquid_stage.py` (12). App: refuses mixed liquid-stage versions; responses "Atomised fraction by
  volume, estimated" and "Atomised liquid flow index, volume-based" (blank before 2.3.0); provenance row.
  **CCD day re-run on the Mac** (~45 min, 3 at a time, LaCie-read bound): each run's `liquid_0.30/` moved
  intact to `shadowgraph/analysis/_liquid2.2.0/liquid_0.30/` first; droplets_0.30 and raw untouched.
  Spot checks before the run: C9 8.84 → 16.38%, C21 10.81 → 15.08%, C20 5.96 → 10.51%. The master_log's
  33 atomised % cells still hold the 2.2.0 values (to update after the re-run, with Ben's OK).
- 2026-10-13 (Mac): **CCD follow-up, phase 4: droplet count in a size band.** Response "In-focus droplets
  per frame in the size band" (`band_per_frame`; lo <= d < hi, default 30-50 um, Settings "Droplet count
  size band"; frame bootstrap); not a default goal. `stats.AnalysisOptions.band_um`. Also: the Response
  surface tab now uses the Settings size bins (it used the defaults). Docs: definitions, RSM_GUIDE,
  IMAGING_PIPELINE_REFERENCE.

- 2026-10-13 (Mac, read-only, sub-agent; numbers re-checked): **F2 area vs volume and H1 window drops on the
  CCD day** (`docs/notes/2026-10-13_area_vs_volume_and_window.md`). Masks rebuilt with `classical_liquid`
  match `classical_per_frame.csv` on 16,764 / 16,764 frames. **Volume vs area:** ρ 0.84 (all), 0.88
  (flow-controlled); volume ≈ 0.24-0.27 × area (un-atomised pieces carry ~235 um of depth per pixel,
  droplets ~50 um); no effect changes sign, but the gas effect doubles and rpm / feed fall below noise;
  volume is 3× noisier and its scale model-dependent (round vs ribbon ×1.6). **Window drops**, 8 runs, two
  routes: (A) a drop lands mid-run, so it is not in the background median and is counted as liquid from
  then on (C9 +7.2 points, C21 +4.0, C2r2 +3.5, C4, C10r2); (B) a drop in the median all run divides out
  of T but re-enters through the MODEL's out-of-focus non-droplet union, because T ≈ 1 always passes the
  out-of-focus test (C20: 41% of its un-atomised pixels; C6). Candidate fixes: (a) drop out-of-focus
  non-droplet detections with mean T ≥ 0.97 (C20 5.6 → 15.1% on the sample), (b) a persistence mask or
  rolling background. Volume is ~10× more sensitive to window drops, so a window fix must precede any
  volume response. Liquid-stage re-run: ~31 min for the day on Windows (+ volume add-on). **Decided (Ben):
  both window fixes (a) mean-T >= 0.97 rule and (b) persistent + still mask, plus volume as a SECONDARY
  response, in one liquid-stage change; re-run on the Mac (CPU only, ~45 min), old outputs archived.**

- 2026-10-13 (Mac): **CCD follow-up, phase 3: gas regimes and best settings.** New `operating.py` reads each
  run's Pressure sheet (gas + P0 in the camera window, 10 s before it, the whole-run trace) and classifies it:
  flow-controlled (>= 95% of set), pressure-limited (below, with P0 within 0.5 bar of the supply ceiling,
  new Settings field, default 9.5 barA), gas short, unknown; "settled" from medians (pulsing defeats a
  straight-line trend). Real CCD day, read-only: all ten 0.5 mm runs pressure-limited, the other 23
  flow-controlled; not settled: C1, C2 (both runs), C4, C9. Both analyses carry it (`rec["operating"]`); the
  Taguchi per-run table gains gas delivered + regime and a warning. Response surface: Model page "Runs that
  did not get their set gas" = Leave them out (default; `RunPoint.excluded`, not predicted, not drift pairs)
  / Fit them at the gas they got / Keep at set point. Report: "Gas delivered and the operating regime"
  section (per-run table, `fig_rsm_gas_delivered`, `fig_gas_traces`) with the not-delivered runs' own
  table and a main-effects fit among them ("what controlled them"); Best settings lists EVERY goal set,
  used or left out and why (the first CCD analysis silently used atomised alone); "Best runs as measured"
  (goals on observed values, every run counted); headline bullets for both; recommended runs get a
  "Pressure check" when their predicted peak pressure reaches the ceiling. Design page: "Gas delivered"
  column, read in the background. Workbook sheets: Goals used, Best observed runs, Gas delivered,
  Pressure-limited effects. Tests: `test_gas_regimes.py` (11: thresholds, settled, a log read from a
  workbook, a simulated CCD day with a pressure-limited 0.5 mm block in all three modes).

- 2026-10-13 (Mac): **CCD follow-up, phase 2: "no spray" runs.** A run below the Settings tab's new
  "No spray below (atomised %)" (default 2, 0 = off) is a dribble: `stats.load_measured_run` blanks its
  droplet size (D32, mean, median, D90, Dv50) and droplet steadiness (count CV, near-empty %, thin %,
  lag-1) with their CIs and bootstraps, and the droplet parts of its run_metrics (size block, count series,
  spectra, r pressure-vs-droplets; the cache file is untouched). Atomised %, in-focus count, liquid CV,
  atomised liquid flow and peak pressure stay. Size tables, size bins and the deck's spread / Dv50 / span /
  pulsing headlines skip it; per-run tables and `rsm_results.csv` carry a "no spray" note; the report
  names it at the top; provenance records the threshold and the runs. Settings reach both tabs through
  a new `stats.AnalysisOptions` (phase 4's size band will ride on it). Real CCD day, read-only: exactly
  C3 (112022, 0.19%) and C5 (113349, 0.45%) are flagged. Tests: `test_no_spray.py` (5, incl. a full
  response-surface publish with C3's setting as a dribble) + Settings tab.

- 2026-10-13 (Mac): **CCD follow-up, phase 1.** Taguchi app bugs 3 (run list re-read after a batch) and 6
  (GUI_Clean survives a failing Cone_4 import; missing atomised liquid flow is now reported loudly, and
  marked on the Model page) fixed, with tests. Labels: "Atomised fraction **by area**, classical (%)" and
  "Atomised liquid flow **index, area-based** (mL/min)" (keys unchanged, saved goals still work); the
  assumptions and three biases (area is not volume, concentration is not flux, one window) are in
  `docs/definitions.md`. **master_log:** new column "Mean Diameter (um)" at K, between D32 and Atomised (%);
  GUI_Clean writes it from summary.json's `droplet_d_mean_um` on every save (blank when the AI has not run)
  and migrates older logs itself (`migrate_master_mean_diameter`, images move one column right). The LaCie
  master_log was migrated and the 33 CCD rows filled with D32 / mean / atomised % from each run's
  summary.json + classical_summary.json (they match rsm_results.csv to 0.005); backup beside it:
  `Experiments/Logs/master_log BACKUP 2026-10-13 before mean column.xlsx`. 292 images byte-identical,
  each moved one column right; offscreen-tested on an old and a new log. Its two colour scales sit on I
  (Motor Travel) and J (D32); left as they were. The first CCD analysis had goals atomised (3), mean
  diameter (2) and count CV (1) set, but used atomised alone: the other two were dropped as unusable
  surfaces (predicted R² < 0.5) and the Best settings section did not say so (fix in phase 3).
  Tests: full suite 763, 758 passed first time; the 5 failures were 2 expected (deck title now "...by
  area"; the no-GLR fake campaign now also warns that atomised liquid flow is missing) and 3 stale
  real-data expectations written on 10/05, before those runs were measured (now 27 measured; the fake
  run-tree test compares only what the rig writes). All 5 updated and passing.

- 2026-10-13 (home PC): **CCD day batch finished, 33/33 ok**, all sizer 2.2.0 with droplets_0.30 +
  liquid_0.30. Output / job folder: `D:\Experiments\Taguchi\CCD\CCD 4-factor 12-10-2026\` (the LaCie's
  `Experiments/Taguchi/CCD/...` on the Mac). 18:13 -> ~05:05, 7.9-36 min per run (median ~19 min); the
  two longest (115412, 122239, ~36 min) were back to back. Next: Response surface tab Analyse (Ben).
  **First Analyse (09:09-09:14, ~5 min on this PC):** atomised fraction is the only usable surface (R² 0.93,
  predicted 0.62, LOF p 0.032): up with gas, RPM; down with feed, orifice; Orifice² and big RPM x Orifice /
  Feed x Orifice interactions. Size and steadiness surfaces predict poorly (predicted R² < 0, strong LOF);
  mean diameter barely moves (39.3 um, coefficients ~1 um). No curvature except in orifice. Best setting
  11,000 / 900 / 3,000 / 0.5 (all edges) but driven by atomised fraction ALONE (bug 6 removed the flow goal;
  mean diameter and CV dropped as weak). 0 rpm control 19.2% vs centres 17.3 +/- 1.1 and outside its PI
  (pred 12.9). 0.8 mm check inside its PIs except peak pressure (5.2 vs 6.3 predicted).
  **Read-only check of the gas traces: the whole 0.5 mm block was gas-starved.** P0 pinned at 9.2-9.6 barA
  (a supply ceiling?) and the camera-window gas flow was 33-5,554 sccm against set points of 7,000-11,000
  (delivered gas vs feed r = -0.92; more with rpm). Every 0.8/1.2/1.8 mm run got its set point. So the gas
  factor is wrong for 10 runs, which drives the interactions, LOF and the 0.5 mm "best setting". Gas
  expansion energy per kg liquid (GLR_delivered x RT ln(P0/Pa)) correlates with atomised fraction at
  r = 0.83 over all 33 runs (set-point GLR 0.35). Rotation: no effect at 1.2 mm (0/100/500/900 rpm all
  17-19%), +2.6 points at 1.8 mm. Full write-up, section by section of the deck, with the physics:
  `docs/notes/2026-10-13_CCD_day_explained.md`. Next: find the pressure ceiling; fix Taguchi app bug 6;
  re-analyse (a) without the 0.5 mm block and (b) with the delivered gas typed in.

- 2026-10-12 (home PC, read-only on the data): **CCD day ready for the batch.** `D:\Experiments\2026\10\12\`
  holds 33 runs, each one 13.93 GB cine (same size as 10/05: ~508 frames at stride 10) + run_summary.xlsx,
  nothing analysed yet. All Run status "complete", 390 fps, bh 0.5, Notes "CCD run 1..33 <type>" in capture
  order. The app's own loader + `rsm_detect` find a complete CCF, 4 factors: 16 corners, 10 faces, 5 centres
  (31 in the fit), 0 rpm = outside (control), 0.8 mm = off-grid check, orifice the block factor (3 changes,
  confounded with time), 3 drift pairs, full quadratic estimable (15 terms, 6 pure-error df, 10 LOF df), no
  missing / extra points, no Notes conflicts. Achieved flow (max of the recorded range) at 11,000 sccm on the
  0.5 mm block peaked at 11,421-11,782 in 3 of 4 runs (vs ~1-2% over elsewhere); the fit uses the setpoint. Quick self-test READY. Batch time on
  this PC from the 9x3 timings: ~23-28 min/run, so ~13-15 h for 33.

- 2026-10-12 (lab PC): **33-run CCD day captured.** All 33 runs in `E:\Experiments\2026\10\12\`
  (105301 … 151407), settings and order match the seed-1 sheet (`ben_plan()` in
  `tests/test_rsm_design.py`); every run has a full 13.93 GB cine. The two morning runs that lost their
  cine (~10:36, 11:10) were deleted by Ben. Run 33 (0.8 mm check) ran normally at 500 rpm and is a valid
  run: the GUI's stall check false-tripped on it ("STOPPED: ... stalled at 66 RPM"; Ben confirmed no stall),
  and that false label was removed (run_summary Run status "complete", master_log Notes clean; checked
  2026-10-12 on the home PC). Next: batch on Windows, then the Response surface tab.

- 2026-10-12 (lab PC, compiled only, NOT yet on the rig): **GUI_Clean lost auto-trigger capture.** A
  run's auto-trigger fired and logged "saving .cine", then failed ("Error — re-arm manually"); no .cine
  in the run folder and none in PCC. The error text went only to the status bar, which the end-of-run
  auto-save overwrote 14 s later, so the cause is unknown. Suspect: the fixed post-trigger settle used
  the GUI fields' post-trigger count, not the camera's (they differ if fields changed since Apply Config
  or the camera was power-cycled), so the cine could be opened while still recording. Changes: wait for
  `partition_recorded(1)` using the camera's own post-trigger frames / fps (fallback: old fixed settle);
  `save_recording` raises if no file / empty file (the >= 90 %-stall "done" path used to log success with
  nothing on disk); "never started" vs "stalled" save errors; Arm, Disarm / Abort, Apply Config and
  auto-arm on Start refused while a save runs (`_cam_saving`), since each overwrites or clears camera
  RAM; failures go to the console with the failing step, plus a traceback in the LaCie `Logs\serial_*.txt`,
  and say whether the cine is still in camera RAM (save it from PCC before arming). Check on the rig:
  a normal auto-trigger capture still saves, and the post-trigger wait isn't stuck on its +15 s timeout
  (that would mean `partition_recorded(1)` doesn't index partitions from 1).
  Same day, 10:50: an editor tab holding an old copy saved `GUI_Clean.py` back to the 7513f1e version
  (no SCCM ramp, no bubbler at Start, emoji back, camera fix gone). Restored from HEAD and the fix
  re-applied; the clobbered copy is not kept in the repo.

- 2026-10-12 (lab PC, offscreen-tested with fake devices, NOT yet on the rig): **GUI_Clean SCCM ramp and
  bubbler at Start.** "SCCM ramp /s" box under the cut-off (0-12000 sccm/s, empty/0 = off, remembered as
  `gas_ramp_sccm_s`). Set Flow and Start Experiment move the Alicat setpoint from its current value to
  the target at that rate (6000 sccm at 1000 sccm/s = 6 s), a new setpoint every 100 ms while ramping
  (`AlicatMFC.set_flow(sccm, ramp_rate)`; the reader polls at 10 Hz during a ramp, 5 Hz otherwise).
  Gas Flow Off, STOP EVERYTHING and the cut-off still cut to 0 at once and cancel a ramp. The traverse
  still starts 0.5 s after Start, i.e. during the ramp. Start Experiment now also spins the bubbler at
  the RPM box value (blank or 0 = no rotation); it refuses to start if the box has an RPM and the Uno is
  not connected. The ramp rate is not recorded in run_summary.
- 2026-10-12 (lab PC, compiled, NOT yet flashed): **Portenta switch noise filter.** A HOME stopped at
  mid-travel (back switch "found" after 233,673 of ~480,000 steps; back-off cleared in 0 steps, so a
  spike on pin 5, not the beam). Same fault in the serial logs on 2026-10-08 11:17 (28 mm short; the
  11:31 home then ran 23 mm past zero, so runs in between had a wrong zero; per-run travel is relative).
  Every other home since 09-09 triggers at 479,500-480,100 steps moved. Fix: both switches now count
  only after every read agrees for 2 ms (`SWITCH_HOLD_US`, `SwitchFilter`, `switchHeld()`); homing
  (`runUntilSwitch`) and the front stop use it (the front was 3 back-to-back reads, microseconds).
  Home shifts by at most ~20 steps (0.003 mm). Hardware cure if it persists: switch leads away from
  motor cables, or a stiffer pull-up / 100 nF to GND on pin 5. After flashing: home a few times from
  the far end and check "moved" is ~480,000 each time.
- 2026-10-12 (Mac, NOT yet on the rig): **GUI_Clean safety + data fixes, and Portenta firmware.**
  FIRMWARE (`src/gui/Pressure_Motor_Portenta.cpp`, Portenta H7 M7; flashed and tested on the lab rig 2026-10-12: polarity correct, jog / move / homing all stop at the front switch, the 72.5 mm soft limit stops a forward jog before the switch is reached, so the switch is a backstop only): the
  front optical switch (pin 1, previously configured but never read) is now an ABSOLUTE forward stop:
  3 consecutive HIGH reads halt any forward move, jog or homing back-off (`FRONT_LIMIT: pos=` then
  MOVEMENT_COMPLETE / JOG_LIMIT); forward moves/jogs are refused while it reads HIGH; backward always
  allowed. Assumes the back switch's polarity (HIGH = blocked); a disconnected switch reads HIGH and
  blocks forward motion (fail-safe). New `SWITCHES:` command reports both switches (also at boot).
  Soft limit 986000 steps (stale 13600-steps/mm figure = 145 mm) -> MAX_TRAVEL_STEPS = 493000 (72.5 mm).
  GUI: Alicat health (frames stamped on the reader thread; no frame for 2 s or the reader dying ->
  red alarm, cut-off shows NO DATA, STOP EVERYTHING mid-run, Set Flow / Start refused); FRONT_LIMIT,
  traverse STALL_DETECTED, MOVEMENT_TIMEOUT, ERROR:/HOMING_FAILED handled; "Check switches" button
  replaces Clean (removed); jog release always sends STOP and the GUI stops a jog at 72.5 mm; STOP
  EVERYTHING ends the run itself if no MOVEMENT_COMPLETE within 1.5 s; the watchdog now stops the
  traverse and SAVES the run; stopped runs: run_summary "Run status" = "STOPPED: <reason>" (else
  "complete"), master_log Notes prefixed "⚠ STOPPED: ...", travel credited only as far as covered;
  run conditions snapshotted at Start (re-saving Notes keeps them); speed 0 = static run (no move, no
  watchdog, ends with STOP EVERYTHING); close asks while a run / camera save is in progress and sends
  STOP to the traverse; clearing the cut-off box switches it off; Space handled by an app-level filter
  (a focused button can no longer take it); run_summary, master_log and camera_settings.json written
  to a temp file then os.replace; settings never saved part-way through loading; unused imports /
  locals / attrs removed; How To button opens How To (index from count), text rewritten.
  Checked offscreen (fake Portenta/Uno/Alicat, writes redirected to the scratchpad): 17 checks.
- 2026-10-12 (Mac, NOT yet tried on the rig): **GUI_Clean pressure cut-off** box under Gas Flow Off
  (Hardware tab, Mass Flow Control card; 0-30 barA, empty/0 = off; remembered as `pressure_cutoff_bar`). Every
  Alicat frame (~0.2 s) compares the RAW barA reading (absolute, not the smoothed trace) with it; the
  first frame at or above it runs `_pressure_off()` (traverse/silicone feed STOP, bubbler stop, gas
  zeroed), logs, flashes the console red and shows a warning. Latched (fires once), re-arms below 90%
  of the limit; status beside the box reads Off / Armed / TRIPPED. A run stopped this way still
  auto-saves (the Portenta answers STOP with MOVEMENT_COMPLETE); re-home afterwards. For the
  small-orifice / high-flow tests. Checked offscreen with fake devices.
- 2026-10-11 (Mac, NOT yet tried on the rig): **GUI_Clean "Auto-trigger at end of test"** tickbox beside
  Disarm / Abort (Camera tab; remembered in camera_settings.json as `auto_trigger_end`). On Start
  Experiment it arms the camera if needed and fires the trigger at test length - 2 s - post-trigger
  (test length = Motor Travel x 6800 / steps/s, traverse starting 0.5 s after Start), so the saved video
  ends 2 s before the traverse stops (25 s test, 13 s video: fires with 15 s left). A test too short for
  the video asks: trigger early / start without / cancel. Countdown shown under the camera buttons;
  cancelled by Disarm / Abort, Pressure Off, a timed-out run, or the traverse finishing first.
  `auto_trigger_plan()` is the timing (pure function); checked offscreen with a fake camera.
- 2026-10-11 (Mac): **mean diameter is a headline response** (Ben: same level as D32 and atomised
  fraction). Taguchi: main effects, per run, S/N, GLR, interactions, residual checks, drift, report
  summary, deck headline slides. CCD: contour maps, 3D surfaces, all-pairs maps, drift, fit checks,
  model comparison, validation, "What was found" (now two slides when it does not fit on one). And it
  REPLACES D32 as the default size goal (Ben; one size goal, so size is not double-weighted). Folders with
  saved Model choices keep their old goals. Five-response CCD figures use two rows.
  Also: the app opens maximised.
- 2026-10-11 (Mac): batch worker survives a USB drop (bugs 1-2 of the 10-06 batch): see Known bugs.
  New statuses `crashed` and `drive_lost`, both resumable; `worker.RunLog`, `Worker._wait_for_drive`.
- 2026-10-11 (Mac): dark theme made OS-independent. `theme.apply_fusion_style` now sets a full dark
  palette; before, Fusion followed the OS light/dark setting, so on a Mac in light mode the run-folder
  picker (non-native, for multi-select), list widgets and scroll bars were light text on white (Windows
  in dark mode looked fine). Also: the Response surface tab's findings/recommendation lists styled like
  the Taguchi tab's; `restyle_inputs` no longer restyles a spin box's inner editor (it drew a white box).
- 2026-10-08 (lab PC): `launch_app.py` probe fixed. It required an EXACT `sm_XY` match, so the lab's
  RTX 4070 Ti SUPER (sm_89) on torch 2.6.0+cu124 (lists sm_86, sm_90) was wrongly called
  unsupported and the launcher warned no Python could run a batch. Now follows CUDA compatibility
  (same-major cubin with lower-or-equal minor, or PTX at or below); new tests. It also prints
  "checking this Python..." first: the probe imports torch (~5 s warm, much longer on a cold start),
  and the silent wait looked like a hang.
- 2026-10-08 (lab PC): 2.2.0 adopted for good. `measure_run.py`, `classical_liquid.py`,
  `process_capture.py`, `batch_runs.py` default to it (`--no-sharpness-rule` for 2.1.0); every
  caller passes the flag explicitly; new test guards resumed 2.1.0 jobs. 390 fps settled.

- 2026-10-07: 9x3 analysed (see "Where we are"). Replicate outliers: 124030 (T9) high D32, 120201 (T7)
  high count CV. Odd pack: 94 flags (78 atomised_100pct), 33 images.

- 2026-10-07: legacy handoff frozen and archived; this file created. Plugins added (pyright-lsp,
  hookify, claude-md-management, context7, fiftyone; FiftyOne's MCP server not set up yet).
- 2026-10-06: 27/27 replicate runs measured on the home PC at 2.1.0. `selftest.py` Python gate
  lowered to 3.9; `launch_app.py` probes its interpreter and relaunches under a working one.
- 2026-10-05: sizer 2.1.0 (half-max atomised numerator, truncated detections out of classical
  D32, folders renamed, classical extremes mode 41 s vs 183 s, `--limit` guard). GUI: GLR,
  Materials tab, master_log columns looked up by header name, second Trigger button.
- 2026-10-05: Taguchi_Analysis_UI phases 1-10 built (see its plan doc).

## How this file is maintained

- Claude reads this file at the start of any work on this part of the project.
- **Claude updates it before finishing any task that changes the state**: a step done, a result
  obtained, a bug found or fixed, a decision made, a plan changed. Edit the sections in place;
  don't append a diary. Bump "Last updated" with date and machine.
- Long evidence (tables, investigations, timing breakdowns) goes in a dated note under
  `docs/notes/` or in the relevant plan doc, with a one-line pointer here. Keep this file short
  enough to read in one go (aim under ~250 lines).
- Nothing is deleted from history: the legacy handoff stays frozen, and git keeps every version
  of this file.
