"""Phase 3a: the droplets settings, the OpenFOAM files written from them, and reading the results back.

No OpenFOAM run here (the tool's end-to-end check is a real run; README.md): these check the rules that keep the
switch-off and each stage's end on a frame, the droplet count per size, and the parsing and naming of fates."""
import copy
import textwrap

import numpy as np
import pandas as pd
import pytest

from droplet_transport import cfd_droplets as C
from droplet_transport import cfd_results as R
from droplet_transport.settings import ROOT, SettingsError

BASELINE = ROOT / "settings" / "droplets_baseline.yaml"


@pytest.fixture
def plain():
    p, b = C.read_yaml(BASELINE)
    return copy.deepcopy(p), b


def build(p, b):
    return C.build(p, b)


def test_baseline_loads(plain):
    s = build(*plain)
    assert s.sizes_um.size == 100 and s.per_size == 600 and s.dt <= C.MAX_STEP_S
    assert s.dt == pytest.approx(5 / 600)
    assert s.spray_frame_steps == 30
    assert np.allclose(s.start_centre, [0.1637, 0.186, -0.2125])
    assert np.allclose(s.gravity, [0, -9.81, 0])
    assert [v.key for v in s.variants()] == ["gusts_on_after_0s", "gusts_on_after_2s", "gusts_on_after_10s",
                                             "gusts_off_after_0s", "gusts_off_after_2s", "gusts_off_after_10s"]
    assert "slide_test.exposure_s" in s.basis and s.basis["spray.droplets.speed_m_s"][0] == "estimated"


def test_stage_lengths_land_on_frames(plain):
    s = build(*plain)
    for v in s.variants():
        n1 = s.stage1_steps(v)
        assert n1 % s.spray_frame_steps == 0                       # stage 1 ends on a frame
        assert n1 * s.dt == pytest.approx(s.exposure_s + v.after_s)
        n2, dt2 = s.still_air(v)
        assert n1 * s.dt + n2 * dt2 == pytest.approx(s.exposure_s + s.settle_s)
        assert dt2 == pytest.approx(s.still_air_frame_s, rel=0.05)


@pytest.mark.parametrize("path,value,msg", [
    ("spray.droplets.per_size", 30, "multiple of 20"),
    ("slide_test.flow_after_switch_off_s", [0, 1.1], "whole number"),
    ("slide_test.exposure_s", 5.1, "whole number"),
    ("slide_test.settle_s", 5, "longer than"),
    ("physics.turbulent_gusts", "sometimes", "on or off"),
    ("chamber.up", "w", "x, y or z"),
    ("spray.droplets.standoff_mm", 400, "not inside"),
    ("run.runs_folder", "/tmp/with space", "spaces"),
])
def test_bad_settings_are_refused(plain, path, value, msg):
    p, b = plain
    cur = p
    keys = path.split(".")
    for k in keys[:-1]:
        cur = cur[k]
    cur[keys[-1]] = value
    with pytest.raises(SettingsError, match=msg):
        build(p, b)


def test_gusts_accept_yaml_on_off(plain):
    p, b = plain
    p["physics"]["turbulent_gusts"] = "off"
    assert build(p, b).gusts == [False]
    p["physics"]["turbulent_gusts"] = [True, False]                 # YAML reads on/off as true/false
    assert build(p, b).gusts == [True, False]


def test_speed_by_size(plain):
    p, b = plain
    p["spray"]["droplets"]["speed_m_s"] = [[10, 8], [100, 4]]
    s = build(p, b)
    assert s.speed_for(10) == 8 and s.speed_for(55) == pytest.approx(6) and s.speed_for(200) == 4


def test_injectors_one_per_size_one_droplet_per_step(plain):
    s = build(*plain)
    txt = C.injectors(s)
    assert txt.count("coneNozzleInjection") == 100
    assert "d2um" in txt and "d200um" in txt
    # floor(1.5/dt x step) is 1 even when OpenFOAM's step is a hair short; injecting while t0 < duration gives
    # exactly per_size steps
    assert f"parcelsPerSecond {1.5 / s.dt:.9g};" in txt
    dur = s.exposure_s - s.dt / 2
    assert f"duration        {dur:.9g};" in txt
    t0 = np.arange(0, 2 * s.per_size) * s.dt
    assert ((t0 >= 0) & (t0 < dur)).sum() == s.per_size
    assert np.floor(1.5 / s.dt * (s.dt * (1 - 1e-12))) == 1
    assert "fixedValueDistribution { value 2e-06; }" in txt


def test_cloud_properties(plain):
    s = build(*plain)
    patches = [("outlet", "patch", 442), ("inlet", "patch", 249), ("wall", "wall", 0), ("defaultFaces", "wall", 20747)]
    on = C.cloud_properties(s, True, patches)
    assert "dispersionModel stochasticDispersionRAS;" in on
    # every patch listed (even empty ones), all 'escape': a droplet leaves the tracking at its first touch
    assert "inlet            { type escape; }" in on and "defaultFaces     { type escape; }" in on
    assert "wall             { type escape; }" in on and "stick" not in on
    assert "patches          (outlet inlet wall defaultFaces);" in on
    still = C.cloud_properties(s, False, patches, inject=False)
    assert "dispersionModel none;" in still and "coneNozzleInjection" not in still


def test_read_patches(tmp_path):
    f = tmp_path / "boundary"
    f.write_text(textwrap.dedent("""
        FoamFile { version 2.0; format ascii; class polyBoundaryMesh; object boundary; }
        2
        (
            outlet
            {
                type            patch;
                nFaces          442;
                startFace       663673;
            }
            defaultFaces
            {
                type            wall;
                inGroups        1(wall);
                nFaces          20747;
                startFace       664364;
            }
        )"""))
    assert C.read_patches(f) == [("outlet", "patch", 442), ("defaultFaces", "wall", 20747)]


def test_round_denormals():
    txt = "(0 8.0248182e-316 0.5) 1e-30 -2.5e-310 3.2e-3 12e-300"
    assert C.round_denormals(txt) == "(0 0 0.5) 1e-30 0 3.2e-3 0"


def test_copied_flow_fields_lose_denormals(tmp_path):
    from droplet_transport.cfd_runner import _round_denormals_in
    (tmp_path / "p").write_text("(\n-8.1e-06\n4.94065645841247e-324\n)\n")       # as in Chamber_v2's p
    (tmp_path / "U").write_text("((0 0 0.5))\n")
    (tmp_path / "uniform").mkdir()
    _round_denormals_in(tmp_path)
    assert (tmp_path / "p").read_text() == "(\n-8.1e-06\n0\n)\n"
    assert (tmp_path / "U").read_text() == "((0 0 0.5))\n"


def test_prune_keeps_flow_restart_and_droplets(tmp_path):
    for t in ("0", "0.25", "5"):
        d = tmp_path / t
        (d / "lagrangian" / "kinematicCloud").mkdir(parents=True)
        (d / "U").write_text("x" * 100)
        (d / "uniform").mkdir()
        for f in ("positions", "d", "active", "coordinates", "UTurb"):
            (d / "lagrangian" / "kinematicCloud" / f).write_text("1")
    freed = C.prune(tmp_path, {5.0})
    assert freed > 100
    assert (tmp_path / "0" / "U").exists() and (tmp_path / "5" / "U").exists()
    assert not (tmp_path / "0.25" / "U").exists() and not (tmp_path / "0.25" / "uniform").exists()
    kept = {f.name for f in (tmp_path / "0.25" / "lagrangian" / "kinematicCloud").iterdir()}
    assert kept == {"positions", "d", "active"}


# ---- results -----------------------------------------------------------------------------------------------------

HDR = ('# Time           currentProc " (coordinates0 coordinates1 coordinates2 coordinates3) (position0 position1 '
       'position2) celli tetFacei tetPti facei stepFraction origProc origId active typeId nParticle d dTarget (U0 U1 '
       'U2) rho age"\n')


def hit(t, x, y, z, i, d):
    return f"{t:.8e}\t0 (0 0.5 0.3 0.2) ({x} {y} {z}) 5 6 1 6 0.5 0 {i} 1 -1 1 {d} 0 (0 -1 0) 1070 0.1\n"


def field(name, cls, body):
    return f"FoamFile\n{{\n    class {cls};\n    object {name};\n}}\n// * * //\n{body}\n// end\n"


def write_cloud(d, rows):
    """rows: (id, d, active, x, y, z)."""
    L = d / "lagrangian" / "kinematicCloud"
    L.mkdir(parents=True)
    n = len(rows)
    (L / "origProcId").write_text(field("origProcId", "labelField", f"{n}{{0}}"))
    (L / "origId").write_text(field("origId", "labelField", f"{n}\n(\n" + "\n".join(str(r[0]) for r in rows) + "\n)"))
    (L / "d").write_text(field("d", "scalarField", f"{n}\n(\n" + "\n".join(str(r[1]) for r in rows) + "\n)"))
    (L / "active").write_text(field("active", "labelField", f"{n}\n(\n" + "\n".join(str(r[2]) for r in rows) +
                                    "\n)"))
    (L / "positions").write_text(field("positions", "Cloud<basicKinematicCollidingParcel>", f"{n}\n(\n" +
                                       "\n".join(f"({r[3]} {r[4]} {r[5]}) 7" for r in rows) + "\n)"))


@pytest.fixture
def small(plain):
    p, b = plain
    p["spray"]["droplets"]["sizes_um"] = [10, 30]
    p["spray"]["droplets"]["per_size"] = 20
    p["slide_test"]["flow_after_switch_off_s"] = [0]
    p["physics"]["turbulent_gusts"] = "on"
    return build(p, b)


def test_where(small):
    s = small
    assert R.where(s, "defaultFaces", (0.16, 0.013, -0.2)) == "floor"
    assert R.where(s, "defaultFaces", (0.16, 0.705, -0.2)) == "lid"
    assert R.where(s, "defaultFaces", (0.08, 0.3, -0.2)) == "wall x 80 mm"
    assert R.where(s, "defaultFaces", (0.2, 0.3, -0.2976)) == "wall z -297.6 mm"
    assert R.where(s, "defaultFaces", (0.22, 0.633, -0.31)) == R.PORT_TUBE      # in the port's stub
    assert R.where(s, "outlet", (0.22, 0.633, -0.3176)) == R.PORT_MESH
    assert R.where(s, "inlet", (0.1637, 0.242, -0.2125)) == R.SPRAY_HOLE
    assert R.where(s, "defaultFaces", (0.16, 0.25, -0.21)) == R.OBJECTS
    s.wall_names = {"x_min": "front"}
    assert R.where(s, "defaultFaces", (0.08, 0.3, -0.2)) == "front"


def test_droplets_table(small, tmp_path):
    s = small
    v = s.variants()[0]
    case = tmp_path
    hits = case / "postProcessing" / "lagrangian" / "kinematicCloud" / "hits"
    (hits / "0.25").mkdir(parents=True)
    (hits / "0.25" / "defaultFaces.dat").write_text(HDR + hit(0.1, 0.16, 0.013, -0.2, 0, 3e-5) +
                                                    hit(0.2, 0.08, 0.3, -0.2, 1, 1e-5))
    (hits / "0.25" / "outlet.dat").write_text(HDR + hit(0.2, 0.22, 0.633, -0.3176, 2, 1e-5))
    (hits / "0.25" / "inlet.dat").write_text(HDR)                       # header only: no hits
    (case / "0").mkdir()
    # at switch-off (5 s): droplet 3 airborne, 0-2 stuck; at the end (305 s): droplet 3 still airborne, droplet 4
    # (never in a hit record) stuck without a hit (would be a lost-track oddity)
    write_cloud(case / "5", [(0, 3e-5, 0, 0.16, 0.013, -0.2), (1, 1e-5, 0, 0.08, 0.3, -0.2),
                             (2, 1e-5, 0, 0.22, 0.633, -0.3176), (3, 1e-5, 1, 0.2, 0.4, -0.1)])
    write_cloud(case / "305", [(0, 3e-5, 0, 0.16, 0.013, -0.2), (1, 1e-5, 0, 0.08, 0.3, -0.2),
                               (2, 1e-5, 0, 0.22, 0.633, -0.3176), (3, 1e-5, 1, 0.2, 0.35, -0.1),
                               (4, 3e-5, 0, 0.2, 0.2, -0.1)])
    df = R.droplets(s, v, case)
    by = df.set_index("id")
    assert list(df.id) == ["0:0", "0:1", "0:2", "0:3", "0:4"]
    assert by.loc["0:0", "fate"] == "floor" and by.loc["0:0", "d_um"] == 30
    assert by.loc["0:1", "fate"] == "wall x 80 mm"
    assert by.loc["0:2", "fate"] == R.PORT_MESH
    assert by.loc["0:3", "fate"] == R.AIRBORNE and by.loc["0:3", "y_mm"] == pytest.approx(350)
    assert by.loc["0:4", "fate"] == "stopped, no wall hit"
    assert list(df.airborne_at_switch_off) == [0, 0, 0, 1, 0]
    acc = R.accounting(s, df)
    assert not acc["ok"] and acc["found"] == 5 and acc["fired_expected"] == 40
    t = R.fates_by_size(s, df)
    assert set(t.columns) >= {"fired", "floor", R.AIRBORNE, "airborne at switch-off", "stopped, no wall hit"}
    assert t.set_index("d_um").loc[10.0, "fired"] == 3
    b = R.bands(s, df)
    assert list(b.band) == ["0-10 µm", "20-30 µm"]
    assert b.set_index("band").loc["0-10 µm", "airborne at switch-off"] == pytest.approx(1 / 3)


def test_read_list_forms(tmp_path):
    f = tmp_path / "x"
    f.write_text(field("x", "labelField", "3{1}"))
    assert list(R.read_list(f)) == [1, 1, 1]
    f.write_text(field("x", "scalarField", "0()"))
    assert R.read_list(f).size == 0
    f.write_text(field("x", "scalarField", "2\n(\n1e-05\n2.5e-05\n)"))
    assert list(R.read_list(f)) == [1e-5, 2.5e-5]


def test_bands_are_by_size(small):
    df = pd.DataFrame({"variant": "v", "d_um": [10.0, 30.0, 30.0], "fate": ["floor", "floor", R.AIRBORNE],
                       "airborne_at_switch_off": [1, 0, 1]})
    b = R.bands(small, df).set_index("band")
    assert b.loc["20-30 µm", "floor"] == 0.5 and b.loc["0-10 µm", "fired"] == 1


def test_add_landed_puts_the_deposit_into_each_frame(small, tmp_path):
    case = tmp_path
    (case / "0").mkdir()
    write_cloud(case / "5", [(3, 1e-5, 1, 0.2, 0.4, -0.1)])                    # one airborne at switch-off
    (case / "305").mkdir()                                                     # none left in the air at the end
    df = pd.DataFrame({"id": ["0:0", "0:1", "0:3"], "d_um": [30.0, 10.0, 10.0], "fate": ["floor", "lid", "floor"],
                       "landed_s": [0.1, 6.0, 100.0], "x_mm": [160.0, 200, 210], "y_mm": [13.0, 705, 13],
                       "z_mm": [-200.0, -100, -150]})
    assert R.add_landed(case, df) == 2
    five = R.read_cloud(case / "5").set_index("id")
    assert list(five.index) == [3, 0] and five.loc[0, "active"] == 0 and five.loc[3, "active"] == 1
    assert five.loc[0, "y"] == pytest.approx(0.013) and five.loc[0, "d"] == pytest.approx(3e-5)
    end = R.read_cloud(case / "305")
    assert sorted(end.id) == [0, 1, 3] and (end.active == 0).all()
    assert R.add_landed(case, df) == 0                                         # once only
    assert len(R.read_cloud(case / "305")) == 3


def test_entries_read_long_short_and_uniform_lists():
    h = "FoamFile\n{\n    class vectorField;\n}\n// * //\n"
    assert R._entries(h + "2\n(\n(0 0 1)\n(1 2 3)\n)\n", "U")[1] == ["(0 0 1)", "(1 2 3)"]
    assert R._entries(h + "2((0 0 1) (1 2 3))\n", "U")[1] == ["(0 0 1)", "(1 2 3)"]
    assert R._entries(h + "3(1 0 1)\n", "active")[1] == ["1", "0", "1"]
    assert R._entries(h + "2{0}\n", "origProcId")[1] == ["0", "0"]
    assert R._entries(h + "2\n(\n(0.1 0.2 0.3) 7\n(0.4 0.5 0.6) 8\n)\n", "positions")[1] == \
        ["(0.1 0.2 0.3) 7", "(0.4 0.5 0.6) 8"]
