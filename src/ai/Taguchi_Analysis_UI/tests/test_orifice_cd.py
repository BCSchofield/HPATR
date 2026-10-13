"""AI/Real_Data_Code/orifice_cd.py (2026-10-13): the discharge coefficient of an orifice insert from a
gas-only run is recovered from a log made with a known Cd; subsonic steps are kept out of the fit; the
Cd table is updated by diameter (and length)."""
from __future__ import annotations

import json
import math
import subprocess
import sys

import numpy as np
import openpyxl
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

cd_mod = spec.rdc_module("orifice_cd")
G, R, RHO, T = 1.40, 296.8, 1.145, 293.15          # nitrogen, the rig's gas


def fake_run(folder, d_mm, cd, p0s, length=None, seed=0, notes="CD TEST 0.5 mm"):
    """A run_summary.xlsx like GUI_Clean's: Metadata + a 4 Hz Pressure log, 20 s per gas step."""
    rng = np.random.default_rng(seed)
    A = math.pi * (d_mm * 1e-3) ** 2 / 4
    t, p, q = [], [], []
    for i, p0 in enumerate(p0s):
        flux, _ = cd_mod.ideal_flux(p0, G, R, T)
        sccm = cd * A * flux * 6e7 / RHO
        for k in range(80):
            t.append(i * 20 + k * 0.25)
            settle = 1 - math.exp(-k / 4)                     # the first seconds still moving
            p.append(1.01325 + (p0 - 1.01325) * settle + rng.normal(0, 0.005))
            q.append(sccm * settle + rng.normal(0, 5))
    folder.mkdir(parents=True)
    wb = openpyxl.Workbook()
    m = wb.active
    m.title = "Metadata"
    m.append(["Field", "Value"])
    for row in (("Orifice", f"{d_mm}mm"), ("Orifice length (mm)", length if length is not None else "NOT RECORDED"),
                ("Gas", "Nitrogen Gas"), ("Gas density (kg/m3)", "1.145"), ("Speed (steps/s)", 0), ("Notes", notes)):
        m.append(list(row))
    ps = wb.create_sheet("Pressure")
    ps.append(["timestamps", "pressures", "flows"])
    for row in zip(t, p, q):
        ps.append(list(row))
    wb.save(folder / "run_summary.xlsx")


def test_choked_and_subsonic_branches():
    choked, ch = cd_mod.ideal_flux(9.18, 1.4, 287.05, 293.0)
    assert ch and choked == pytest.approx(2168, rel=0.01)          # the C7 check in the phase-12 note
    sub, ch2 = cd_mod.ideal_flux(1.5, 1.4, 287.05, 293.0)
    assert not ch2 and 0 < sub < cd_mod.ideal_flux(1.9, 1.4, 287.05, 293.0)[0]
    assert cd_mod.ideal_flux(1.0, 1.4, 287.05, 293.0) == (0.0, False)


def test_a_known_cd_is_recovered_and_the_table_updated(tmp_path, monkeypatch):
    fake_run(tmp_path / "runs" / "r05", 0.5, 0.82, [1.5, 3.0, 5.0, 7.0, 9.0], length=2.0)
    # 1.2 mm cannot choke on gas alone within 12,000 sccm: subsonic steps only (1.15-1.6 barA), fitted as such
    fake_run(tmp_path / "runs" / "r12", 1.2, 0.70, [1.15, 1.3, 1.45, 1.6], seed=1, notes="cd test 1.2")
    fake_run(tmp_path / "runs" / "other", 1.2, 0.30, [3.0], seed=2, notes="a normal run")   # not a CD TEST
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, cd_mod.__file__, str(tmp_path / "runs"), "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    s = {e["diameter_mm"]: e for e in json.loads((out / "orifice_cd_summary.json").read_text())["inserts"]}
    assert s[0.5]["cd"] == pytest.approx(0.82, abs=0.01) and s[0.5]["n_points"] == 4 and s[0.5]["n_subsonic"] == 1
    assert s[0.5]["basis"] == "choked"
    assert s[1.2]["cd"] == pytest.approx(0.70, abs=0.02) and s[1.2]["basis"] == "subsonic" and s[1.2]["n_points"] == 4
    assert "subsonic only" in r.stdout
    assert (out / "orifice_cd.png").is_file() and (out / "orifice_cd_points.csv").is_file()
    # --write: by diameter and length, into the app's table (here a temporary copy)
    table = tmp_path / "orifice_cd.json"
    table.write_text(json.dumps({"schema": 1, "note": "", "inserts": [
        {"diameter_mm": 0.5, "length_mm": None, "cd": None, "cd_sd": None, "n_points": 0, "measured": "", "source": ""},
        {"diameter_mm": 1.8, "length_mm": None, "cd": None, "cd_sd": None, "n_points": 0, "measured": "", "source": ""}]}))
    monkeypatch.setattr(cd_mod, "CD_TABLE", table)
    cd_mod._write_table(list(s.values()))
    t = {e["diameter_mm"]: e for e in json.loads(table.read_text())["inserts"]}
    assert t[0.5]["cd"] == pytest.approx(0.82, abs=0.01) and t[0.5]["length_mm"] == 2.0 and t[0.5]["measured"]
    assert t[1.2]["cd"] == pytest.approx(0.70, abs=0.02)                  # added
    assert t[1.8]["cd"] is None                                          # untouched
