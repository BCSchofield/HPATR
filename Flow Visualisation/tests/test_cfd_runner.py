"""Phase 3a: the runner's OpenFOAM call (no OpenFOAM here: plain shell commands stand in for the solver)."""
import json
import os
import time
from types import SimpleNamespace

import numpy as np
import pytest

from droplet_transport import cfd_results
from droplet_transport import cfd_runner as R

SCN = SimpleNamespace(bashrc="/dev/null")


def test_foam_returns_when_the_command_ends(tmp_path):
    assert R.foam(SCN, tmp_path, "echo End", "log.ok") >= 0


def test_foam_stops_a_command_whose_log_goes_quiet(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STALL_S", 1)
    t0 = time.time()
    with pytest.raises(R.Stalled, match="stopped changing"):
        R.foam(SCN, tmp_path, "echo starting; sleep 60", "log.stuck")
    assert time.time() - t0 < 20


HEADER = "FoamFile\n{\n    version 2.0;\n    object coordinates;\n}\n\n"
COORDS = HEADER + "2\n(\n(0.123456789012 0.2 0.3 0.376543210988) 406239 5397617 1\n(4.1896281256e-14 0.5 0.25 0.25) 7 8 2\n)\n"


def _frame(case, t, coords=COORDS):
    d = case / f"{t:g}"
    (d / "uniform").mkdir(parents=True)
    (d / "uniform" / "time").write_text("x")
    (d / "U").write_text("x")
    (d / "lagrangian" / "kinematicCloud").mkdir(parents=True)
    (d / "lagrangian" / "kinematicCloud" / "coordinates").write_text(coords)
    return d


def _case(tmp_path, frames=(0.25,)):
    (tmp_path / "0").mkdir()
    (tmp_path / "system").mkdir()
    (tmp_path / "system" / "controlDict").write_text("application x;\nstartFrom       startTime;\nstartTime 0;\n")
    for t in frames:
        _frame(tmp_path, t)
    return tmp_path


@pytest.fixture
def no_checkmesh(monkeypatch):
    """guard() without OpenFOAM: it marks the case guarded and finds no bad cells."""
    def fake_guard(scn, case):
        (case / cfd_results.GUARD_FILE).write_text('{"cells": [], "centres_m": [], "ports_m": {}}')
        return np.zeros(0, np.int64)
    monkeypatch.setattr(R, "guard", fake_guard)


def _stalls(n):
    """A stand-in for foam(): stalls n times (writing its log), then finishes."""
    calls = []

    def fake(scn, case, command, log_name, stall_s=None):
        calls.append(case)
        (case / log_name).write_text(f"attempt {len(calls)}")
        if len(calls) <= n:
            raise R.Stalled("stuck")
        return 1.0
    return fake, calls


def test_nudge_rounds_only_the_positions(tmp_path):
    d = _frame(tmp_path, 1)
    R.nudge(d, 6)
    txt = (d / "lagrangian" / "kinematicCloud" / "coordinates").read_text()
    assert txt.startswith(HEADER)
    assert "(0.123457 0.2 0.3 0.376543) 406239 5397617 1" in txt
    assert "(4.18963e-14 0.5 0.25 0.25) 7 8 2" in txt


def test_readable_zeroes_only_denormals(tmp_path):
    coords = HEADER + "2\n(\n(1.232137684e-311 0.4890045761 0.004282081402 0.5067133425) 351246 5396297 2\n" \
                      "(1.84002224e-292 0.3571639532 0.4710247731 0.1718112736) 351267 5396299 1\n)\n"
    d = _frame(tmp_path, 46.25, coords)
    (d / "lagrangian" / "kinematicCloud" / "U").write_text(HEADER + "1\n(\n(-1.741401069e-313 2.5e-3 -0.1)\n)\n")
    R.readable(d)
    cloud = d / "lagrangian" / "kinematicCloud"
    txt = (cloud / "coordinates").read_text()
    assert "(0 0.4890045761 0.004282081402 0.5067133425) 351246 5396297 2" in txt
    assert "(1.84002224e-292 0.3571639532" in txt                  # small but normal: kept
    assert "(0 2.5e-3 -0.1)" in (cloud / "U").read_text()


def test_a_stalled_stage_restarts_from_its_newest_frame(tmp_path, monkeypatch, no_checkmesh):
    case = _case(tmp_path, frames=())
    fake, calls = _stalls(1)

    def stall_after_a_frame(scn, c, command, log_name, stall_s=None):
        if not calls:
            _frame(c, 27.25)                              # the stage got as far as 27.25 s, then stuck
        return fake(scn, c, command, log_name, stall_s)
    monkeypatch.setattr(R, "foam", stall_after_a_frame)
    restarts = []
    R._foam_pruning(SCN, case, "log.stage1", [], restarts)
    assert len(calls) == 2
    assert restarts == [{"log": "log.stage1", "from_s": 27.25, "rounded_to": 10, "guarded": True, "dropped": 0,
                         "stalled_log": "log.stage1.stalled1"}]
    assert (case / cfd_results.GUARD_FILE).exists()
    assert "startFrom       latestTime;" in (case / "system" / "controlDict").read_text()
    assert (case / "log.stage1.stalled1").read_text() == "attempt 1"
    assert (case / "log.stage1").read_text() == "attempt 2"
    assert (case / "27.25" / "lagrangian" / "kinematicCloud" / "coordinates").read_text() == COORDS   # untouched


def test_restarting_from_the_frame_it_started_from_rounds_the_positions(tmp_path, monkeypatch, no_checkmesh):
    case = _case(tmp_path, frames=(0.25,))           # stage 2 starts from 0.25 and sticks before its next frame
    fake, calls = _stalls(5)
    monkeypatch.setattr(R, "foam", fake)
    restarts = []
    with pytest.raises(R.Stalled):
        R._foam_pruning(SCN, case, "log.stage2", [], restarts)
    assert [r["rounded_to"] for r in restarts] == [10, *R.NUDGE_DIGITS]   # guarded first, then rounded
    assert len(calls) == len(R.NUDGE_DIGITS) + 2
    assert "(0.123457 0.2 0.3 0.376543)" in (case / "0.25" / "lagrangian" / "kinematicCloud" / "coordinates").read_text()


def test_a_stall_before_the_first_frame_is_not_restarted(tmp_path, monkeypatch):
    case = _case(tmp_path, frames=())
    fake, calls = _stalls(1)
    monkeypatch.setattr(R, "foam", fake)
    with pytest.raises(R.Stalled):
        R._foam_pruning(SCN, case, "log.stage1", [], [])
    assert len(calls) == 1


def test_restarts_are_limited(tmp_path, monkeypatch, no_checkmesh):
    case = _case(tmp_path, frames=())
    calls = []

    def always_a_new_frame_then_stuck(scn, c, command, log_name, stall_s=None):
        calls.append(1)
        _frame(c, 0.25 * len(calls))
        (c / log_name).write_text("x")
        raise R.Stalled("stuck")
    monkeypatch.setattr(R, "foam", always_a_new_frame_then_stuck)
    restarts = []
    with pytest.raises(R.Stalled):
        R._foam_pruning(SCN, case, "log.stage1", [], restarts)
    assert len(restarts) == R.RESTARTS and len(calls) == R.RESTARTS + 1


def test_a_resumed_stage_restarts_at_once_and_keeps_the_old_logs(tmp_path, monkeypatch, no_checkmesh):
    case = _case(tmp_path, frames=(27.25,))
    (case / "log.stage1").write_text("the failed run")
    (case / "log.stage1.stalled1").write_text("an earlier stall")
    fake, calls = _stalls(0)
    monkeypatch.setattr(R, "foam", fake)
    restarts = []
    R._foam_pruning(SCN, case, "log.stage1", [], restarts, resume=True)
    assert len(calls) == 1
    assert (case / "log.stage1.stalled1").read_text() == "an earlier stall"
    assert (case / "log.stage1.stalled2").read_text() == "the failed run"
    assert restarts[0]["stalled_log"] == "log.stage1.stalled2" and restarts[0]["from_s"] == 27.25


CLOUD = {
    "coordinates": COORDS,
    "d": HEADER + "2\n(\n2e-06\n4e-06\n)\n",
    "active": HEADER + "2{1}\n",
    "U": HEADER + "2\n(\n(1 2 3)\n(4 5 6)\n)\n",
}


def test_drop_parcels_takes_the_same_droplets_out_of_every_field(tmp_path):
    d = _frame(tmp_path, 1)
    L = d / "lagrangian" / "kinematicCloud"
    for f, txt in CLOUD.items():
        (L / f).write_text(txt)
    assert R.drop_parcels(d, np.array([7, 99])) == 1                  # the second droplet is in cell 7
    assert (L / "d").read_text() == HEADER + "1\n(\n2e-06\n)\n"
    assert (L / "active").read_text() == HEADER + "1{1}\n"
    assert (L / "U").read_text() == HEADER + "1\n(\n(1 2 3)\n)\n"
    assert "(0.123456789012 0.2 0.3 0.376543210988) 406239 5397617 1" in (L / "coordinates").read_text()
    assert "7 8 2" not in (L / "coordinates").read_text()
    assert R.drop_parcels(d, np.array([5])) == 0


def _mesh_file(cls, body):
    return f"FoamFile\n{{\n    version 2.0;\n    class {cls};\n}}\n// * * //\n\n{body}"


def test_guard_zones_the_bad_cells_faces_without_touching_the_shared_mesh(tmp_path, monkeypatch):
    # 4 cells in a row: internal faces 0 (0|1), 1 (1|2), 2 (2|3); boundary faces 3, 4. Face 1 has no valid tets.
    shared = tmp_path / "flow"
    shared.mkdir()
    (shared / "owner").write_text(_mesh_file("labelList", "5\n(\n0\n1\n2\n0\n3\n)\n"))
    (shared / "neighbour").write_text(_mesh_file("labelList", "3\n(\n1\n2\n3\n)\n"))
    (shared / "faceZones").write_text(_mesh_file("regIOobject", "0()\n"))
    case = tmp_path / "case"
    mesh = case / "constant" / "polyMesh"
    mesh.mkdir(parents=True)
    for f in shared.iterdir():
        os.link(f, mesh / f.name)                    # hard links, as write_stage1 makes them
    (case / "system").mkdir()
    for f in ("controlDict", "fvSchemes", "fvSolution"):
        (case / "system" / f).write_text("x")
    (case / "constant" / "kinematicCloudProperties").write_text("cloudFunctions\n{\n    hits { }\n}\n")

    def fake_checkmesh(scn, work, command, log_name, stall_s=None):
        if command.startswith("checkMesh"):
            sets = work / "constant" / "polyMesh" / "sets"
            sets.mkdir()
            (sets / "lowQualityTetFaces").write_text(_mesh_file("faceSet", "1\n(\n1\n)\n"))
        else:                                        # writeCellCentres: cell i at x = i cm; the port's 2 faces
            (work / "0" / "C").write_text(_mesh_file("volVectorField", "internalField   nonuniform List<vector> \n4\n(\n"
                                                     + "".join(f"({i / 100:g} 0 0)\n" for i in range(4)) + ")\n;\n"
                                                     "boundaryField\n{\n    wall\n    {\n        type calculated;\n"
                                                     "        value uniform (9 9 9);\n    }\n    capture\n    {\n"
                                                     "        type calculated;\n        value nonuniform List<vector> 2"
                                                     "((0.1 0 0) (0.3 0 0));\n    }\n}\n"))
        (work / log_name).write_text("End")
        return 1.0
    monkeypatch.setattr(R, "foam", fake_checkmesh)
    scn = SimpleNamespace(bashrc="/dev/null", port_patches=["capture"])
    cells = R.guard(scn, case)
    assert cells.tolist() == [1, 2]
    zones = (mesh / "faceZones").read_text()
    assert "badTetCells" in zones and "faceLabels List<label> 3\n(\n0\n1\n2\n)" in zones   # every internal face of 1, 2
    assert (shared / "faceZones").read_text().endswith("0()\n")       # the shared file is as it was
    assert "removeParcels" in (case / "constant" / "kinematicCloudProperties").read_text()
    assert not (case / "checkMesh").exists()
    g = json.loads((case / cfd_results.GUARD_FILE).read_text())
    assert g == {"cells": [1, 2], "centres_m": [[0.01, 0, 0], [0.02, 0, 0]], "ports_m": {"capture": [0.2, 0, 0]}}
    assert R.guard(scn, case).tolist() == [1, 2]                       # once on, from its record
