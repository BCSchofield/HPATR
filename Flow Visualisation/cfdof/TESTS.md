# CFD and droplet tests: what each folder is

One line per test. Linked from `~/OpenFOAM/TESTS.md`; kept up to date by Claude. Started 2026-11-12.

## How folders are named (from 2026-11-12)

- **CFD cases:** `~/OpenFOAM/cfdof_cases/<model>_<design>_<flow>/`, e.g. `Chamber_v2_stream_30` (the carrier at
  30 L/min). The FreeCAD file has the same name, since CfdOF names the case folder after the document. No spaces or dots.
  - Each has a **`View flow.command`**: double-click to open it in ParaView (your newest saved `.pvsm` in that folder,
    else the case at its last iteration). Copy it in from `Flow Visualisation/cfdof/View flow.command` (the guides
    say when).
  - CfdOF's own `case/` and `meshCase/` sit beside it; CfdOF fixes those names.
- **Droplet runs:** `~/OpenFOAM/droplet_runs/<date>_<time>_<settings name>/`.
  - At the top: one **`View <flow>.command`** per flow (that flow's headline run in ParaView), and the report to read
    (`comparison.md` for a sweep, `report.md` for a single run).
  - **`data/`:** everything else (each flow's report, figures, CSVs, every run's view, the OpenFOAM cases).
  - Runs before 2026-11-12 are `droplet_runs/<settings name>/<date_time>/`, everything at the top.
- **Lab data** stays where GUI_Clean writes it on the LaCie; none of this touches it.

## CFD cases (`~/OpenFOAM/cfdof_cases/`)

| Folder | Made | What it tests | Status | Its droplet runs |
|---|---|---|---|---|
| `Elbow/` | 2026-10-23 | CfdOF's own tutorial (the install check) | done | none |
| `FlowVis1stTrial/` | 2026-10-24 | Ben's first STEP and FreeCAD files for Chamber_v1 and Chamber_v1_jet, and their saved views (the cases are in the two folders below) | done | none |
| `Chamber_v1/` | 2026-10-24 | Guide Part 5: the first chamber, 1.0 mm hole | done, 2,000 iterations | the Part 5 entry in `droplets_snapshots/2026-10-25_135054/` |
| `Chamber_v1_jet/` | 2026-10-24 | Guide Part 6: the jet refined | done, 1,000 / 1,500 / 2,000 | `droplets_baseline/2026-10-25_140603/`; `droplets_snapshots/2026-10-25_135054/`; Part 6 in `droplets_chamber_v2/2026-11-02_121431/` |
| `Chamber_v2/` | 2026-10-28 | Guide Part 7: the refined CAD, 1.11 mm bore, jet ladder, floor and wall layers. **The reference.** | done, 2,000 | `droplets_chamber_v2/2026-11-02_121431/` |
| `Chamber_v2_kEpsilon/` | 2026-10-28 | Chamber_v2 with the k-ε model (the second turbulence model, `CFD_LOG.md` section 8) | meshed, not solved | none |
| `Chamber_v2_stream_30/` | 2026-11-12 | Guide Part 8: carrier 10 mm at 30 L/min on the x = 80 wall (y 210, z −100), in line with a capture on the x = 270 wall (50 mm cone into a 10 mm pipe); 44 mm port sealed. A jet into the capture (push-pull) | meshed 2026-11-13: 1,652,490 cells, Mesh OK (32 faces > 70°, max 78.9°); **solved 2026-11-13** to 4,000 (1e-5; boundaries re-picked on Fusion after a first solve put capture on the floor), gas in = out; residuals plateau (U ~1e-3, p 3-6e-2); chamber-wide steady, but snapshots differ locally by 31-56 % (the spray's circulation wanders; Gentle wanders as much with no jet). Jet 7 m/s at x 100, breaks up by x 190-250, reaches the cone at 0.6-0.7 m/s (guide 8.10) | `settings/droplets_carrier_stream.yaml` |
| `Chamber_v2_gentle_30/` | 2026-11-13 | Guide Part 8.7: the same, the carrier through a 40 mm hole (no jet) | built by Claude by script from a copy of Stream (boundaries set on Fusion: carrier Face29, 40 mm, capture Face39; length scale 2.8 mm); mesh and case checked line by line against Stream's (only the carrier differs); 1,692,233 cells, Mesh OK (30 faces > 70°, max 78.8°); **solved 2026-11-13** to 4,000 (1e-5, 93 min), gas in = out; residuals plateau (U ~2e-3, p ~8e-2); chamber-wide steady, snapshots differ locally by 34-49 %. The carrier joins the spray's circulation at once (0.4 m/s, turning down); cone mouth 0.4-0.5 m/s (guide 8.10) | the same |
| `Chamber_v3/` | 2026-11-14 | **The base model from now on** (guide 8.11): Chamber_v2 with the CAD's 0.1 mm step closed (`StepFix`, the arm's end flush with the body) and the walls' layers on every atomiser face (`AtomiserLayers`, `NozzleBlockLayers` with a 2 mm surface mesh; allowDiscontinuity in meshDict, re-added by `add_layer_discontinuity.py` after any Write mesh). `Chamber_v3_air.step` is the fixed air | built by Claude by script from a copy of Chamber_v2 (faces re-found by position); 1,351,969 cells; 100 faces skewness > 4 (max 4.8) at one corner (arm side / body side / body bottom); no open or inside-out cells; first cell beside the atomiser 0.01-0.1 mm (was 0.46-1.7); case files = Chamber_v2's but createPatchDict. **Solved 2026-11-14** to 2,000 (40 min), gas in = out | `settings/droplets_chamber_v3.yaml` |
| `Chamber_v3_stream_30/` | 2026-11-14 | Stream on Chamber_v3 | built from Gentle's file with Stream's 10 mm hole and 0.7 mm length scale (case files = Stream's but createPatchDict); 1,778,254 cells; 155 faces skewness > 4 (max 4.5) at the same corner. **Solved 2026-11-14** to 4,000 (94 min), gas in = out. Its droplets stick in OpenFOAM's tracking: 5 of 6 runs of 290 s hung | the same |
| `Chamber_v3_gentle_30/` | 2026-11-14 | Gentle on Chamber_v3 | 1,818,050 cells; 157 faces skewness > 4 (max 4.5) at the same corner; case files = Gentle's but createPatchDict. **Solved 2026-11-15** to 4,000 (101 min), gas in = out | the same |
| `Chamber_v2_atomiser_layers/`, `Chamber_v2_stream_30_atomiser_layers/`, `Chamber_v2_gentle_30_atomiser_layers/` | 2026-11-14 | Superseded by Chamber_v3: layers on the atomiser's body and arm only (the nozzle block and the step's faces broke the mesh before the step was closed) | meshed and cased, never solved; deleted 2026-11-14 (Ben) | none |
| `Nozzle_A/` | to make | Guide Part 9 (`NOZZLE_WEDGE_GUIDE.md`): a round nozzle on a 2D wedge, gas only | rehearsed by Claude 2026-11-08 | none |
| `_old/` | | `case/` and `meshCase/` from 2026-10-23, before Part 0's "append document name" setting | kept, unused | |

## Droplet runs (`~/OpenFOAM/droplet_runs/`)

| Folder | Made | What it tests | Read |
|---|---|---|---|
| `droplets_baseline/2026-10-25_140603/` | 2026-10-25 | The baseline droplets through Chamber_v1_jet at 2,000 (Phase 3a Part D) | `report.md` |
| `droplets_snapshots/2026-10-25_135054/` | 2026-10-25 | Chamber_v1_jet at 1,000 / 1,500 / 2,000 and Chamber_v1 (Part 5): one snapshot is enough; the mesh matters more | `comparison.md` |
| `droplets_chamber_v2/2026-11-02_121431/` | 2026-11-02 | Part 6 against Chamber_v2 (guide 7.10): the floor and wall layers | `comparison.md` |
| `2026-11-14_1439_carrier_stream/` | 2026-11-14 | Chamber_v2 against Stream and Gentle at 2,000 / 3,000 / 4,000: the 0-30 µm band out through the capture. Both designs ~2-3× the bare chamber's fines, neither wins every snapshot; the atomiser (no near-wall layers) takes most fines with gusts on, largely an artefact (guide 8.10). Stream 3000's and Gentle 4000's gusts-off 290 s runs hung and are missing | `comparison.md` |
| `2026-11-15_0145_chamber_v3/` | overnight 2026-11-14/15 | The same sweep through Chamber_v3 and its two designs (guide 8.11). The atomiser artefact is gone (tracers on it 0.3–0.4 %, was 5–7 %). Gusts on, 290 s: Gentle takes 16–17 % of the 0–30 µm band, steady across snapshots, against 6.2 % for Chamber_v3. Stream's 290 s runs: 5 of 6 hung (stopped by the watchdog); only gusts off at 4,000 is left (12.3 %) | `comparison.md`; gusts on at 290 s is in guide 8.11 (the comparison shows 2 s, since Stream lacks 290 s) |
| `2026-11-15_1218_chamber_v3_stream/` | 2026-11-15 | Stream's three flows again (`settings/droplets_chamber_v3_stream.yaml`; the same settings as the sweep above), with the runner restarting stalled stages. Gusts on, 290 s at 2,000 finished (one restart): 7.6 % of the 0-30 µm band. Three runs of 290 s still failed (2,000 gusts off; 3,000 both): the droplet returns to the same bad face after each nudge; 4,000 gusts on died restarting (a denormal in its frame, since fixed). 4,000 gusts off repeats the overnight run exactly. The four carried on 2026-11-15 16:15, guarded (`cfdof/resume_stream_v3.sh`; `resume.log`; guide 8.11) | its `comparison.md` (Stream only) |
| `2026-11-15_1422_chamber_v3_all/` | 2026-11-15 | Superseded by `2026-11-15_1707_chamber_v3_all/`. All seven flows compared: Chamber_v3 and Gentle from `2026-11-15_0145_chamber_v3/`, Stream from the rerun (`cfdof/rerun_stream_v3.sh`). Shows gusts on at 2 s (not every Stream run has 290 s). Stream shifts the 30-60 µm floor deposit 6-8 mm; Gentle doesn't | `comparison.md`; 290 s in STATUS.md line 357 |
| `2026-11-15_1707_chamber_v3_all/` | 2026-11-15 | **All seven at 290 s** (Stream's four stuck runs carried on guarded, `cfdof/resume_stream_v3.sh`). Gusts on, 0-30 µm out through the capture: Chamber_v3 6.2 %, Gentle 15.5-17.2 % (steady), Stream 7.6 / 18.3 / 15.6 % (by snapshot); gusts off 6.7 / 7.0-8.3 / 7.0-12.6 %. Guard removed 0.3-0.7 % a run (guide 8.11) | `comparison.md` |
| `2026-11-14_1057_carrier_stream/` | 2026-11-14 | The first try of the above: filled the disk (the frames' flow copies were pruned only at each stage's end); deleted | |
| `flows/` | | Each flow's chosen iteration, reconstructed once and reused by the runs (a cache) | |
