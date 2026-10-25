"""End to end: a run and a sweep write their reports, figures and CSVs; the layout-only mode stops early."""
import json
import textwrap

import pandas as pd
import pytest

from droplet_transport import runner

from test_settings import YAML


def small(tmp_path, extra=""):
    text = YAML.replace("per_size: 5", "per_size: 4").replace("step: 2}", "step: 20}") + textwrap.dedent("""
        planes:
          - {axis: z, at_mm: 175, name: mid}
        run:
          paths_per_size: 2
          path_sizes_um: [10, 50, 190]
        """) + extra
    p = tmp_path / "small.yaml"
    p.write_text(text)
    return p


def test_a_run_writes_everything(tmp_path):
    root = runner.run_file(small(tmp_path), tmp_path / "out", log=lambda *a: None)
    for f in ("report.md", "per_size.csv", "droplets.csv", "deflection.csv", "summary.json", "settings.yaml"):
        assert (root / f).exists(), f
    for f, _d in runner.FIGURES:
        assert (root / "figures" / f).stat().st_size > 10_000, f
    s = json.loads((root / "summary.json").read_text())
    assert s["accounting"]["ok"] and s["accounting"]["fired"] == 10 * 4
    assert s["metrics"]["purity_number"] is None                        # no distribution named
    d = pd.read_csv(root / "droplets.csv")
    assert len(d) == 40 and set(d["category"]) <= {"target", "other outlets", "floor", "other walls", "airborne"}
    rep = (root / "report.md").read_text()
    assert "Idealised flow" in rep and "## Inputs, by how they are known" in rep


def test_a_sweep_compares_its_runs(tmp_path):
    extra = "sweep:\n  - path: inlets.0.flow_sccm\n    values: [8000, 30000]\n"
    root = runner.run_file(small(tmp_path, extra), tmp_path / "out", log=lambda *a: None)
    t = pd.read_csv(root / "sweep.csv")
    assert list(t["inlets.0.flow_sccm"]) == [8000, 30000]
    assert (root / "sweep_report.md").exists() and (root / "figures" / "sweep_trends.png").exists()
    assert len(list((root / "runs").iterdir())) == 2
    # more flow in the cross-jet pushes the band further towards the outlet (x falls)
    assert t["band_shift_mm"].iloc[1] < t["band_shift_mm"].iloc[0] < 0
    assert (t["band_push_mm"] == -t["band_shift_mm"]).all()


def test_layout_only(tmp_path):
    root = runner.run_file(small(tmp_path), tmp_path / "out", layout_only=True, log=lambda *a: None)
    assert (root / "layout.png").exists() and not (root / "report.md").exists()


def test_a_new_band_from_a_saved_run(tmp_path):
    import sys
    sys.path.insert(0, str(runner.settings.ROOT))
    import band
    root = runner.run_file(small(tmp_path), tmp_path / "out", log=lambda *a: None)
    saved = json.loads((root / "summary.json").read_text())["metrics"]
    again = band.rebands(root, (30, 60))["inlets on"]
    assert again["delivery_number"] == pytest.approx(saved["delivery_number"])
    other = band.rebands(root, (10, 200))
    assert set(other) == {"inlets on", "inlets off"} and other["inlets on"]["sizes_in_band"] == 10


def test_a_sweep_from_a_base_keeps_its_base(tmp_path):
    (tmp_path / "first.yaml").write_text(small(tmp_path).read_text())
    child = tmp_path / "child.yaml"
    child.write_text("base: first.yaml\nsweep:\n  - path: spray.tilt_deg\n    values: [0, 20]\n")
    root = runner.run_file(child, tmp_path / "out", log=lambda *a: None)
    assert (root / "first.yaml").exists()
    assert len(runner.settings.load(root / "settings.yaml")) == 2          # the copy loads on its own


def test_a_target_on_the_floor_is_flagged_as_an_upper_bound(tmp_path):
    extra = "target:\n  outlet: null\n  box_mm: {from: [110, 70, 0], to: [190, 130, 2]}\n  band_um: [30, 60]\n"
    text = small(tmp_path).read_text().replace("target:\n  outlet: left outlet\n  band_um: !design [30, 60]\n", "")
    p = tmp_path / "floor.yaml"
    p.write_text(text + extra)
    root = runner.run_file(p, tmp_path / "out", log=lambda *a: None)
    s = json.loads((root / "summary.json").read_text())
    assert s["metrics"]["delivery_number"] > 0.5                       # straight down into the floor area
    assert any("may not stick" in f for f in s["flags"])
