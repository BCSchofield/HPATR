# Flow Visualisation: how to run it

Phase 1 of `PLAN.md`: where droplets of each size go in the atomisation chamber, through an **idealised** airflow
(textbook jets added together), with the droplet physics Phase 3 reuses in the real chamber flow. Runs on the Mac in
the `phantom` env; a scenario takes ~10 s.

## Run a scenario

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run.py" "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/settings/first_scenario.yaml"
```

The results go to `output/<scenario name>/<date_time>/` (not committed): `report.md` first, then `figures/`, the CSVs
and a copy of the settings. Open the newest one:

```
open "$(ls -dt "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/output/first scenario/"*/ | head -1)report.md"
```

Options: `--layout-only` draws just the layout picture (check a moved port or nozzle before running);
`--per-size 30` fires fewer droplets per size for a quick look; `--out <folder>` writes somewhere else.

## Change the scenario

Everything is in the settings file (`settings/first_scenario.yaml`, commented). Units are in the names.

- **Coordinates:** x along the 300 mm length (0 = the left wall, the outlet), y across the 200 mm (0 = the front
  wall), z up from the floor. Walls: `left`, `right`, `front`, `back`, `floor`, `lid`.
- **Inlets and outlets:** any number. Each has a `wall`, its centre on that wall in the wall's two coordinates
  (`centre_mm: {y: 100, z: 175}` on the left or right wall), `shape: round` with `diameter_mm`, or `shape: slot` with
  `width_mm`, `length_mm` and `long_side_along` (y or z on the left or right wall). Inlets have `flow_sccm` and blow
  square to their wall unless given a `direction: [x, y, z]`.
- **The nozzle:** `nozzle_mm: [x, y, z]`, `tilt_deg` from straight down, `lean_toward_deg` (0 = towards the right
  wall, 90 = the back, 180 = the left wall).
- **The droplets fired:** `sizes_um: {from: 10, to: 200, step: 2}` or a list; `per_size`. They start on a disc at
  `standoff_mm` along the nozzle's axis (where the shadowgraph measures them), at `speed_m_s` (one number, or
  `[[size_um, m/s], ...]` once Phase 5 measures them by size).
- **The target and the band:** `target: {outlet: left outlet, band_um: [30, 60]}`, or a box anywhere
  (`box_mm: {from: [x, y, z], to: [x, y, z]}`). Changing the band changes only the analysis: every droplet's size and
  fate are in `droplets.csv`.
- **Planes:** where each droplet crosses them is recorded: the headline figure (`crossings.png`).
- **How each number is known:** tag it `!measured`, `!estimated` or `!design`; the report lists them all.

## Sweep a setting

A sweep file starts from another settings file and lists the values to try; one run per combination:

```yaml
base: first_scenario.yaml
name: inlet size and flow
sweep:
  - path: inlets.0.diameter_mm      # inlets.0 = the first inlet
    values: [4, 6, 10]
  - path: inlets.0.flow_sccm
    values: [8000, 16000, 32000]
```

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run.py" "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/settings/sweep_inlet_size_and_flow.yaml"
```

`sweep_report.md` and `sweep.csv` compare the runs (`figures/sweep_trends.png`: lines for one swept setting, heat maps
for two); each run's own folder is under `runs/`. Any setting can be swept by its dotted path, e.g.
`spray.tilt_deg`, `inlets.0.centre_mm` (values as `{y: 100, z: 250}`), `target.band_um` (values as `[30, 60]`).

## A different band from a saved run (no re-run)

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/band.py" "$(ls -dt "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/output/first_scenario/"*/ | head -1)" 20 50
```

prints the band's delivery and purity (by number and by volume, inlets on and off) for 20-50 um from that run's
saved fates. For a sweep, point it at one run's folder under `runs/`.

## The measured size distribution (for purity)

Purity needs to know how many droplets of each size the spray makes. Import it once from a measured run (sizer 3.x;
read only, nothing is written in the run). With the LaCie on the Mac, for CCD run 131450:

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/import_sizes.py" "/Volumes/LaCie/Experiments/2026/10/12/"131450*"/shadowgraph/analysis/droplets_0.30" --name ccd_131450
```

That writes `data/ccd_131450_sizes.csv`, which `first_scenario.yaml` already names. Until it exists, runs say so and
leave purity out.

## Droplets through the CFD flow (Phase 3a)

Droplets fired through the real chamber's air flow (a CfdOF case, e.g. guide Part 6) with OpenFOAM's particle tracker,
in the slide test's sequence: the spray on for the exposure, switch-off, the flow kept for a bracketed time, then still
air until the slides come out. One command; every run (gusts on and off x each flow-after time) and the checks at
once, ~1.5 min in all at 600 droplets per size:

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run_droplets.py" "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/settings/droplets_baseline.yaml"
```

Then open the newest run's report:

```
open "$(ls -dt ~/OpenFOAM/droplet_runs/droplets_baseline/*/ | head -1)report.md"
```

`report.md`: where the 0-30 µm band ends up, weighted by the spray's measured sizes (by number and by volume), and
its share of the floor's deposit; the floor deposit maps by size band (seen from above, with the atomiser body,
nozzle block and arm outlined, the exit orifice and the port), where each size ends up, the checks (accounting,
OpenFOAM's tracking and settling against Phase 1, the tracers' near-wall artefact, gusts on against off, large
droplets near the impact point), the flags and the runs. The figures are in `figures/`. Also `droplets.csv` (every
droplet: size, fate, when and where it landed, airborne at switch-off), `fates_by_size.csv`, `bands.csv`,
`checks.json` and its csv files.

**Everything for a run is in one folder**, `~/OpenFOAM/droplet_runs/<name>/<date_time>/` (`run.runs_folder`; no spaces,
as OpenFOAM cannot work in them): the report and figures, the ParaView views in `paraview/`, and the OpenFOAM cases in
`openfoam/` (each with its own mesh files). **To view a run in ParaView, double-click `paraview/<run>.command` in
Finder** (then First Frame, Play). The folder can be copied or moved anywhere whole (Finder, a drive): the
`.command` rewrites the view's paths to where it now sits. Only `flows/` (the reconstructed flows, reused) is shared
between runs, and nothing in a run's folder needs it.

Each view has two tabs. **droplets**: the flow on a grey cut through the hole, the outlines, every droplet coloured by
size; hidden layers (click their eyes): the 0-30 µm band only, the still-airborne only, and Ben's own CfdOF views
(`Slice Through Orifice`, `Slice Through Outlet`, `Tracers From Orifice`, `Tracers Outlet`, `Tracers Whole`, built as
in his `jet_refined_chamber_v1_view.pvsm`, on his 0-5 m/s colour scale). **split: droplets | the air**: the droplets
beside the air in Ben's views, cameras linked, seen from the +x side as in his comparison view, for screenshots
(`paraview/<run>_split_switch_off.png` is a picture of it). To remake a finished run's views after a change to them,
without running OpenFOAM: `run_droplets.py --views-only <run folder>` (a sweep's folder does every entry).

Options: `--per-size 20` for a quick look (its 250 ms step is flagged in report.md: the fines need 8.3 ms or less,
so 600 per size at a 5 s exposure); `--only gusts_on_after_0s` (names as in `report.md`); `--write-only` writes
the OpenFOAM cases and stops; `--no-paraview`; `--no-checks` (skips the four check cases: tracers with gusts on and
off, every size dropped in still air and in a cross-flow). To remake the figures and report of a finished run (after
a change to them), without running anything:

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run_droplets.py" --report-only "$(ls -dt ~/OpenFOAM/droplet_runs/droplets_baseline/*/ | head -1)"
```

The settings file says which CfdOF case and iteration (the flow is reconstructed once into
`~/OpenFOAM/droplet_runs/flows/` and reused; the CfdOF case is only read), the chamber's inside walls in the CAD's
coordinates, the spray hole and its direction, where and how the droplets start (as Phase 1), the exposure, settling
time and flow-after bracket, and gusts on/off. Two rules keep the switch-off on a saved frame: `per_size` is a
multiple of the exposure's frames (20 at 5 s and 0.25 s frames), and each flow-after time is a whole number of
frames. Settings that break them are refused with the reason. `checks` sets the tracers' count and where the column
check drops its droplets (free air, clear of the atomiser and the port).

**Several flows, compared (a sweep).** A settings file with a `sweep:` block runs the same droplets through each
entry's flow in turn (each entry changes only what it names, as `base:` does), each into its own folder with its own
report, then compares them. The snapshot check (PLAN.md, Phase 3a, Part D: iterations 1000 / 1500 / 2000 and the
Part 5 case, 600 per size, ~6 min):

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run_droplets.py" "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/settings/droplets_snapshots.yaml"
open "$(ls -dt ~/OpenFOAM/droplet_runs/droplets_snapshots/*/ | head -1)comparison.md"
```

`comparison.md`: what was compared (case, iteration, cells, orifice); a verdict per flow; the air on a common 10 mm
grid (mean speed, turbulence, how far each is from the reference's); the 0–30 µm band weighted by the measured spray,
every run, beside the gusts and flow-kept brackets; the floor maps by band, one row per flow; per band the floor
share, the deposit's centre, its spread and the share moved to a different 20 mm square, each against the reference
with the noise from the droplet count (the bootstrap), and the verdict (the same / close / differs; how it is judged
is at its end); where each size ends up, one line per flow; each run's checks. Also `comparison.csv`. The same for
runs already finished (two or more output folders; `--labels` names them, `--show gusts_off_after_2s` picks the run
the maps show; into `~/OpenFOAM/droplet_runs/comparisons/<date_time>/` unless `--out`):

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/run_droplets.py" --compare "<output folder 1>" "<output folder 2>" --labels "first,second"
```

`--report-only` on a sweep's folder remakes every entry's report and the comparison.

## Tests

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m pytest "/Users/benschofield/Documents/GitHub/HPATR/Flow Visualisation/tests" -q
```

`test_cfd_droplets.py`, `test_cfd_report.py` and `test_cfd_sweep.py` check the droplets tool (no OpenFOAM run: the
settings, the files written, reading the results, the plan view from the mesh, the maps, the weighting, the checks'
maths, the report; a sweep's entries and settings written back out, the comparison's measures, noise and report). The rest are PLAN.md's Phase 1 checks (terminal speed, the exact solution in uniform flow, Schiller-Naumann against an
ODE solve, size sorting the deflection, the jets' textbook decay, spreading and mass conservation, the random walk,
every droplet accounted for), plus the gas dynamics (the Cd test's 2.41 barA), the settings and the importer (the same
rule as master_log's size-band columns).

## What the idealised flow can and cannot say

It gives how far the spray jet and each inlet jet carry or push aside each size, and trends across settings, in
seconds. It has no recirculation and the jets pass through the walls, so its delivery to the target is idealised and
small droplets that would turn with the air at the floor are counted as floor hits (the report flags both). Thesis
numbers come from Phase 3, the same droplet code through the real chamber flow (Phase 2).
