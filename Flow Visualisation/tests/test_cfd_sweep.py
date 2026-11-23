"""Phase 3a, Part D: a sweep's entries from one settings file, its settings written back out, and the comparison's
maths and report. No OpenFOAM run here (README.md)."""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from droplet_transport import cfd_compare as M
from droplet_transport import cfd_droplets as C
from droplet_transport import cfd_plots as P
from droplet_transport import cfd_sweep as S
from droplet_transport.settings import ROOT, SettingsError

BASELINE = ROOT / "settings" / "droplets_baseline.yaml"
SNAPSHOTS = ROOT / "settings" / "droplets_snapshots.yaml"


def sweep_file(tmp_path, runs_yaml):
    shutil.copy2(BASELINE, tmp_path / "base.yaml")
    f = tmp_path / "sweep.yaml"
    f.write_text("base: base.yaml\nname: t\nsweep:\n  runs:\n" + runs_yaml)
    return f


# ---- the entries ---------------------------------------------------------------------------------------------------

def test_entries_change_only_what_they_name(tmp_path):
    f = sweep_file(tmp_path, "    - {label: a, flow: {iteration: 1000}}\n"
                             "    - {label: b, spray: {droplets: {speed_m_s: !measured 9}}}\n")
    sw, entries = S.expand(*C.read_yaml(f))
    (la, pa, ba), (lb, pb, bb) = entries
    assert (la, lb) == ("a", "b") and "sweep" not in pa
    assert pa["flow"]["iteration"] == 1000 and pa["flow"]["spray_patch"] == "inlet"      # merged, not replaced
    assert pb["flow"]["iteration"] == 2000 and pb["spray"]["droplets"]["speed_m_s"] == 9
    assert bb["spray.droplets.speed_m_s"][0] == "measured" and ba["spray.droplets.speed_m_s"][0] == "estimated"
    assert not any(k.startswith("sweep") for k in ba)
    assert C.build(pa, ba, f).iteration == 1000


@pytest.mark.parametrize("runs, msg", [
    ("    - {label: a, flow: {iteration: 1000}}\n", "at least two"),
    ("    - {label: a, flw: {iteration: 1}}\n    - {label: b}\n", "not a settings section"),
    ("    - {label: a b}\n    - {label: a_b}\n", "used twice"),
    ("    - {flow: {iteration: 1}}\n    - {label: b}\n", "with a label"),
    ("    - {label: Data}\n    - {label: b}\n", "is taken"),
])
def test_broken_sweeps_are_refused(tmp_path, runs, msg):
    with pytest.raises(SettingsError, match=msg):
        S.expand(*C.read_yaml(sweep_file(tmp_path, runs)))


def test_against_must_be_a_label(tmp_path):
    f = sweep_file(tmp_path, "    - {label: a}\n    - {label: b}\n")
    f.write_text(f.read_text().replace("sweep:\n", "sweep:\n  against: c\n"))
    with pytest.raises(SettingsError, match="against"):
        S.expand(*C.read_yaml(f))


def test_settings_written_out_read_back_the_same(tmp_path):
    plain, basis = C.read_yaml(BASELINE)
    (tmp_path / "s.yaml").write_text(S.dump_settings(plain, basis, "a header\nof two lines"))
    p2, b2 = C.read_yaml(tmp_path / "s.yaml")
    assert p2 == plain
    assert {k: v[0] for k, v in b2.items()} == {k: v[0] for k, v in basis.items()}
    assert (tmp_path / "s.yaml").read_text().startswith("# a header\n# of two lines\n")


def test_the_snapshot_sweep():
    sw, entries = S.expand(*C.read_yaml(SNAPSHOTS))
    its = [(lab, p["flow"]["iteration"], p["flow"]["case"]) for lab, p, _b in entries]
    assert [i for _l, i, _c in its] == [1000, 1500, 2000, 2000]
    assert its[-1][2].endswith("Chamber_v1/case") and its[0][2].endswith("Chamber_v1_jet/case")
    assert sw["against"] == "iteration 2000" and sw["show"] in [v.key for v in C.build(*entries[0][1:]).variants()]
    for _lab, p, b in entries:
        assert C.build(p, b).parallel == 10


# ---- the air -------------------------------------------------------------------------------------------------------

def test_read_internal(tmp_path):
    head = "FoamFile\n{\n    format      ascii;\n    class       volVectorField;\n}\n"
    (tmp_path / "U").write_text(head + "internalField   nonuniform List<vector> \n2\n(\n(1 2 3)\n(-4e-1 5 6)\n)\n;\n"
                                "boundaryField\n{\n wall { type fixedValue; value uniform (0 0 0); }\n}\n")
    (tmp_path / "k").write_text(head + "internalField   nonuniform List<scalar> \n3\n(\n0.1\n0.2\n3e-2\n)\n;\n")
    assert M.read_internal(tmp_path / "U").tolist() == [[1, 2, 3], [-0.4, 5, 6]]
    assert M.read_internal(tmp_path / "k").tolist() == [0.1, 0.2, 0.03]
    (tmp_path / "B").write_text(head.replace("ascii", "binary") + "internalField nonuniform List<scalar> 1(x);")
    with pytest.raises(ValueError, match="binary"):
        M.read_internal(tmp_path / "B")


# ---- the measures and the noise ------------------------------------------------------------------------------------

def fake_run(scn, n=200, dx=0.0, floor=1.0, seed=0):
    """A droplets table: n of each of a few sizes in every variant, landed around the impact point."""
    rng = np.random.default_rng(seed)
    rows = []
    for v in scn.variants():
        for d in (6, 16, 26, 40, 100):
            on = rng.random(n) < floor
            rows.append(pd.DataFrame({"variant": v.key, "id": [f"{d}:{i}" for i in range(n)], "d_um": float(d),
                                      "fate": np.where(on, "floor", "wall x 80 mm"), "landed_s": 1.0,
                                      "x_mm": rng.normal(163.7 + dx, 12, n).clip(81, 269), "y_mm": 13.0,
                                      "z_mm": rng.normal(-212.5, 12, n).clip(-297, -18),
                                      "airborne_at_switch_off": (rng.random(n) < 0.3).astype(int)}))
    return pd.concat(rows, ignore_index=True)


def test_measures_moved_and_noise():
    scn = C.load(BASELINE)
    plan = P.plan_view(scn, None, [])
    e = M._edges(plan)
    a = M.measures(scn, fake_run(scn), e)
    assert a["floor"] == 1.0 and a["cx"] == pytest.approx(163.7, abs=1.0) and a["hist"].sum() == pytest.approx(1)
    assert M.moved(a["hist"], a["hist"]) == 0
    far = M.measures(scn, fake_run(scn, dx=60), e)
    assert M.moved(a["hist"], far["hist"]) > 0.95
    rng = np.random.default_rng(1)
    small = M.noise(scn, fake_run(scn, n=50, floor=0.5), e, rng)
    big = M.noise(scn, fake_run(scn, n=800, floor=0.5), e, rng)
    assert big["floor"] < small["floor"] / 2.5 and big["cx"] < small["cx"] / 2.5            # ~1/sqrt(16) = 1/4
    assert small["floor"] == pytest.approx(np.sqrt(0.25 / (50 * 5 * 6)), rel=0.4)           # binomial, all variants


class Fake:
    def __init__(self, label, scn, df):
        self.label, self.scn, self.df, self.plan = label, scn, df, P.plan_view(scn, None, [])


def test_agreement():
    scn = C.load(BASELINE)
    key = "gusts_on_after_2s"
    same = M.agreement([Fake("a", scn, fake_run(scn, seed=0)), Fake("b", scn, fake_run(scn, seed=1))], 0, [key],
                       M.TOLERANCE)
    assert (same[~same.reference].verdict == "the same").all()
    moved = fake_run(scn, seed=1)
    moved.loc[moved.d_um == 6, "x_mm"] += 30
    ag = M.agreement([Fake("a", scn, fake_run(scn, seed=0)), Fake("b", scn, moved)], 0, [key], M.TOLERANCE)
    r = ag[~ag.reference].set_index("band")
    assert r.loc["0-10 µm", "verdict"] == "differs" and "centre differs" in r.loc["0-10 µm", "why"]
    assert r.loc["0-10 µm", "d_centre_mm"] == pytest.approx(30, abs=3)
    assert r.loc["> 60 µm", "verdict"] == "the same"


# ---- the comparison, from run folders ------------------------------------------------------------------------------

def run_folder(d, scn, df, label, it):
    d.mkdir(parents=True)
    shutil.copy2(BASELINE, d / "settings.yaml")
    df.to_csv(d / "droplets.csv", index=False)
    P.save_plan(P.plan_view(scn, None, []), d / "plan_view.npz")
    runs = [{"variant": v.key, "accounting": {"ok": True}} for v in scn.variants()]
    (d / "run.json").write_text(json.dumps({"label": label, "settings": str(BASELINE), "per_size": 200,
                                            "flow_case": str(scn.flow_case), "iteration": it, "flow_cells": 1000,
                                            "runs": runs}))
    (d / "checks.json").write_text(json.dumps({"cases": {"tracers_gusts_off": {"floor": 0.6}}, "large": []}))
    g = np.random.default_rng(it)
    pts = np.stack(np.meshgrid(*[np.arange(0, 50, 10.0)] * 3, indexing="ij"), -1).reshape(-1, 3)
    np.savez_compressed(d / "flow_grid.npz", points_mm=pts, U=g.normal(0, 0.5, (len(pts), 3)),
                        k=np.full(len(pts), 0.01), cells=1000, step_mm=10.0)


def test_compare_writes_the_report(tmp_path):
    scn = C.load(BASELINE)
    run_folder(tmp_path / "a", scn, fake_run(scn, seed=0), "iteration 1000", 1000)
    run_folder(tmp_path / "b", scn, fake_run(scn, seed=1, dx=25), "iteration 2000", 2000)
    md_path = M.compare([tmp_path / "a", tmp_path / "b"], tmp_path / "out", against="iteration 2000")
    md = md_path.read_text()
    for part in ("## What was compared", "## Verdict", "## The air", "## The 0-30 µm band", "## The floor deposit",
                 "## Each run's checks", "## How agreement is judged", "(reference)", "differs"):
        assert part in md, part
    assert "| iteration 1000 | 1,000 |" in md and "60 / – %" in md
    for f in ("compare_floor.png", "compare_fates.png"):
        assert (tmp_path / "out" / "figures" / f).stat().st_size > 20_000
    csv = pd.read_csv(tmp_path / "out" / "comparison.csv")
    assert set(csv.label) == {"iteration 1000", "iteration 2000"} and len(csv) == 2 * 5 * len(scn.variants())
    with pytest.raises(ValueError, match="labels must differ"):
        M.compare([tmp_path / "a", tmp_path / "a"], tmp_path / "out2")


def test_a_top_level_comparison_links_into_data(tmp_path):
    """A sweep's comparison.md sits in the run's top folder; its figures, csv and each flow's folder in data/."""
    scn = C.load(BASELINE)
    top = tmp_path / "2026-01-01_0000_t"
    run_folder(top / "data" / "a", scn, fake_run(scn, seed=0), "iteration 1000", 1000)
    run_folder(top / "data" / "b", scn, fake_run(scn, seed=1), "iteration 2000", 2000)
    md = M.compare([top / "data" / "a", top / "data" / "b"], top / "data", md=top / "comparison.md")
    text = md.read_text()
    assert md == top / "comparison.md" and (top / "data" / "figures" / "compare_floor.png").exists()
    assert (top / "data" / "comparison.csv").exists() and not (top / "data" / "comparison.md").exists()
    for part in ("](data/figures/compare_floor.png)", "](data/figures/compare_fates.png)", "[a](data/a/report.md)",
                 "`View <flow>.command`", "`data/comparison.csv`"):
        assert part in text, part


# ---- one folder per run, and its ParaView opener -------------------------------------------------------------------

def test_run_folders_are_named_by_date_and_test(tmp_path):
    import re
    from droplet_transport import cfd_runner
    a = cfd_runner.fresh_stamp(tmp_path, "carrier_stream")
    b = cfd_runner.fresh_stamp(tmp_path, "carrier_stream")
    assert re.fullmatch(r"\d{4}-\d\d-\d\d_\d{4}_carrier_stream", a) and (tmp_path / a).is_dir()
    assert b == f"{a}_2" or b[:15] != a[:15]                          # the same minute, or the next


def test_where_a_runs_report_and_files_go(tmp_path):
    from droplet_transport.cfd_report import link_prefix, report_path, run_files
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (new / "data" / "stream").mkdir(parents=True)
    assert run_files(old) == old and run_files(new) == new / "data" and run_files(new / "data") == new / "data"
    assert report_path(new / "data") == new / "report.md"
    assert report_path(new / "data", "comparison.md") == new / "comparison.md"
    assert report_path(new / "data" / "stream") == new / "data" / "stream" / "report.md"
    assert report_path(old) == old / "report.md"
    assert link_prefix(new / "data", new / "report.md") == "data/" and link_prefix(old, old / "report.md") == ""


def test_the_opener_follows_the_folder(tmp_path):
    """A run's paraview/<key>.command rewrites the view's paths to wherever the folder now is, and opens it."""
    import os
    import subprocess
    from droplet_transport import cfd_runner
    scn = C.load(BASELINE)
    made = tmp_path / "runs" / "2026-01-01_000000"
    (made / "paraview").mkdir(parents=True)
    (made / "paraview" / "k.pvsm").write_text(f'<P value="{made}/openfoam/k/cloud.foam"/><P value="{made}/x"/>')
    f = cfd_runner.write_opener(scn, made, "k", "gusts on")
    assert os.access(f, os.X_OK) and f.read_text().startswith("#!/bin/bash\n# gusts on.")
    moved = tmp_path / "a folder with spaces & more" / "copy"
    shutil.copytree(made, moved)
    shutil.rmtree(made)
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "open").write_text(f'#!/bin/bash\necho "$@" > "{tmp_path}/args"\n')
    (stub / "open").chmod(0o755)
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}"}
    subprocess.run(["bash", str(moved / "paraview" / "k.command")], env=env, check=True)
    args = (tmp_path / "args").read_text()
    assert str(scn.paraview_bin.parent.parent) in args
    state = Path(args.split("--state=")[1].strip()).read_text()
    assert state == f'<P value="{moved}/openfoam/k/cloud.foam"/><P value="{moved}/x"/>'


def test_the_top_level_opener_follows_the_folder(tmp_path):
    """View <flow>.command, in a run's top folder, opens that flow's headline run through the run's own opener,
    wherever the top folder is moved; a flow without that view gets none, and older ones are replaced."""
    import os
    import subprocess
    from droplet_transport import cfd_runner
    scn = C.load(BASELINE)
    key = "gusts_on_after_2s"
    top = tmp_path / "runs" / "2026-01-01_0000_carrier_stream"
    run = top / "data" / "stream"
    (run / "paraview").mkdir(parents=True)
    (run / "paraview" / f"{key}.pvsm").write_text(f'<P value="{run}/openfoam/{key}/cloud.foam"/>')
    cfd_runner.write_opener(scn, run, key, "gusts on")
    (top / "View old.command").write_text("")
    made = cfd_runner.write_fronts(top, [("Stream", run, scn, key), ("Gentle", top / "data" / "gentle", scn, key)])
    assert [f.name for f in made] == ["View Stream.command"] and not (top / "View old.command").exists()
    assert os.access(made[0], os.X_OK) and "Stream: gusts on, flow kept 2 s after switch-off." in made[0].read_text()
    moved = tmp_path / "a folder with spaces & more" / "copy"
    shutil.copytree(top, moved)
    shutil.rmtree(top)
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "open").write_text(f'#!/bin/bash\nprintf "%s " "$@" > "{tmp_path}/args"\n')
    (stub / "open").chmod(0o755)
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}"}
    subprocess.run(["bash", str(moved / "View Stream.command")], env=env, check=True)
    state = Path((tmp_path / "args").read_text().split("--state=")[1].strip()).read_text()
    assert state == f'<P value="{moved}/data/stream/openfoam/{key}/cloud.foam"/>'


def test_the_case_viewer(tmp_path):
    """cfdof/View flow.command, copied into a CfdOF case's folder: opens the newest saved view there, else the case
    through CfdOF's own ParaView script with the case's full path."""
    import os
    import subprocess
    import time
    viewer = ROOT / "cfdof" / "View flow.command"
    assert os.access(viewer, os.X_OK)
    folder = tmp_path / "Chamber_v2_stream_30"
    (folder / "case").mkdir(parents=True)
    shutil.copy2(viewer, folder)
    (folder / "case" / "pvScript.py").write_text("pfoam = OpenFOAMReader(FileName=r'pv.foam')\n")
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "open").write_text(f'#!/bin/bash\nprintf "%s " "$@" > "{tmp_path}/args"\n')
    (stub / "open").chmod(0o755)
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}"}

    def opened():
        subprocess.run(["bash", str(folder / "View flow.command")], env=env, check=True)
        return (tmp_path / "args").read_text()

    script = Path(opened().split("--script=")[1].strip()).read_text()
    assert script == f"pfoam = OpenFOAMReader(FileName=r'{folder}/case/pv.foam')\n"
    (folder / "a.pvsm").write_text("")
    time.sleep(1.1)
    (folder / "b.pvsm").write_text("")
    assert opened().strip().endswith(f"--state={folder}/b.pvsm")


def test_bens_views_settings_and_port_seed():
    """Ben's CfdOF views go into every run's ParaView state: their cuts square to x by default, and the port's
    streamlines seeded half way along its stub."""
    from droplet_transport import cfd_runner
    scn = C.load(BASELINE)
    assert scn.flow_slices_normal == 0
    plan = {"ports": [{"centre_mm": [220.0, 633.0, -317.6], "wall_axis": 2, "wall_mm": -297.6, "d_mm": 44.0}]}
    assert cfd_runner._port_seed(plan) == pytest.approx([0.22, 0.633, -0.3076])
    assert cfd_runner._port_seed({"ports": []}) is None and cfd_runner._port_seed(None) is None
