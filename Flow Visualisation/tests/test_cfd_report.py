"""Phase 3a, Part C: the plan view from the mesh, the floor maps, the grouped and weighted fates, the checks' maths
and the report. No OpenFOAM run here (the checks' cases are run by the tool; README.md)."""
import copy

import numpy as np
import pandas as pd
import pytest

from droplet_transport import cfd_checks as K
from droplet_transport import cfd_droplets as C
from droplet_transport import cfd_plots as P
from droplet_transport import cfd_report
from droplet_transport import cfd_results as R
from droplet_transport import physics
from droplet_transport.settings import ROOT, SettingsError

BASELINE = ROOT / "settings" / "droplets_baseline.yaml"
HEAD = "FoamFile {{ version 2.0; format ascii; class {cls}; object {obj}; }}\n"


@pytest.fixture
def plain():
    p, b = C.read_yaml(BASELINE)
    return copy.deepcopy(p), b


@pytest.fixture
def scn(plain):
    return C.build(*plain)


# ---- the mesh and the plan view ------------------------------------------------------------------------------------

def write_mesh(d, faces_by_patch):
    """A polyMesh with only boundary faces that matter here (no internal faces): {patch: (type, [corner lists])}."""
    pts, faces, bnd = [], [], []
    for name, (typ, polys) in faces_by_patch.items():
        start = len(faces)
        for poly in polys:
            ids = []
            for p in poly:
                pts.append(p)
                ids.append(len(pts) - 1)
            faces.append(ids)
        bnd.append(f"    {name}\n    {{\n        type {typ};\n        nFaces {len(polys)};\n"
                   f"        startFace {start};\n    }}")
    d.mkdir(parents=True)
    (d / "points").write_text(HEAD.format(cls="vectorField", obj="points") + f"\n{len(pts)}\n(\n" +
                              "\n".join(f"({x} {y} {z})" for x, y, z in pts) + "\n)\n")
    (d / "faces").write_text(HEAD.format(cls="faceList", obj="faces") + f"\n{len(faces)}\n(\n" +
                             "\n".join(f"{len(f)}({' '.join(map(str, f))})" for f in faces) + "\n)\n")
    (d / "boundary").write_text(HEAD.format(cls="polyBoundaryMesh", obj="boundary") + f"\n{len(bnd)}\n(\n" +
                                "\n".join(bnd) + "\n)\n")


def square(cx, cz, half, y):
    return [(cx - half, y, cz - half), (cx + half, y, cz - half), (cx + half, y, cz + half), (cx - half, y, cz + half)]


def test_plan_view_from_the_mesh(scn, tmp_path):
    body = square(0.1637, -0.2125, 0.031, 0.305)                      # the body's underside: 62 x 62 mm
    side = [(0.1327, 0.305, -0.24), (0.1327, 0.655, -0.24), (0.1327, 0.655, -0.18), (0.1327, 0.305, -0.18)]
    floor = square(0.175, -0.157, 0.09, 0.013)                         # on the chamber's floor: not an object
    r = 0.0005
    hole = [(0.1637 + r * np.cos(a), 0.241, -0.2125 + r * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 33)[:-1]]
    port = [(0.198, 0.611, -0.3176), (0.242, 0.611, -0.3176), (0.242, 0.655, -0.3176), (0.198, 0.655, -0.3176)]
    write_mesh(tmp_path / "polyMesh", {"outlet": ("patch", [port]), "inlet": ("patch", [hole]),
                                       "defaultFaces": ("wall", [body, side, floor])})
    faces = C.boundary_faces(tmp_path / "polyMesh", ["defaultFaces", "inlet", "outlet"])
    assert len(faces["defaultFaces"]) == 3 and faces["defaultFaces"][0].shape == (4, 3)
    plan = P.plan_view(scn, faces, ["defaultFaces"])
    assert plan["mask"].sum() * P.PX_MM ** 2 == pytest.approx(62 * 62, rel=0.03)    # the body only (the side is
    assert plan["objects_from_mm"] == pytest.approx(305 - 13)                          # edge-on, the floor a wall)
    assert plan["orifice_d_mm"] == pytest.approx(1.0, rel=0.01)
    (port_,) = plan["ports"]
    assert port_["wall_axis"] == 2 and port_["wall_mm"] == pytest.approx(-297.6)
    assert port_["d_mm"] == pytest.approx(np.sqrt(4 * 44 * 44 / np.pi), rel=1e-6)
    P.save_plan(plan, tmp_path / "plan.npz")
    back = P.load_plan(tmp_path / "plan.npz")
    assert (back["mask"] == plan["mask"]).all() and back["ports"] == plan["ports"]


def test_binary_mesh_leaves_the_objects_out(scn, tmp_path):
    write_mesh(tmp_path / "polyMesh", {"defaultFaces": ("wall", [square(0.16, -0.2, 0.01, 0.3)])})
    pts = tmp_path / "polyMesh" / "points"
    pts.write_text(pts.read_text().replace("format ascii", "format binary"))
    assert C.boundary_faces(tmp_path / "polyMesh", ["defaultFaces"]) is None
    plan = P.plan_view(scn, None, ["defaultFaces"])
    assert plan["mask"] is None and plan["ports"] == []


def test_impact_point_is_below_the_hole(scn):
    assert np.allclose(P.impact_point(scn), [0.1637, 0.013, -0.2125])
    assert np.allclose(K.impact_mm(scn), [163.7, 13, -212.5])


def test_density_keeps_what_landed(scn):
    plan = P.plan_view(scn, None, [])
    rng = np.random.default_rng(1)
    pts = np.c_[rng.normal(170, 20, 400), rng.normal(-160, 30, 400)]
    pts = pts[(pts[:, 0] > 82) & (pts[:, 0] < 268) & (pts[:, 1] > -295) & (pts[:, 1] < -20)]
    D, _sigma, _edges = P._density(plan, pts, 1000)
    total = D.sum() * (P.MAP_MM ** 2 / 100)                            # % of the group fired
    assert total == pytest.approx(100 * len(pts) / 1000, rel=0.02)     # reflecting edges keep the deposit
    lv = P._hdr_levels(D)
    assert lv[0] < lv[1]
    assert D[D >= lv[1]].sum() / D.sum() == pytest.approx(0.5, abs=0.02)


# ---- grouped fates and the weighting -------------------------------------------------------------------------------

def fake(scn, rows):
    """A droplets table: (variant key, d_um, fate, landed_s, airborne_at_switch_off)."""
    return pd.DataFrame([{"variant": v, "id": f"0:{i}", "d_um": d, "fate": f, "landed_s": t, "x_mm": 160.0,
                          "y_mm": 13.0, "z_mm": -210.0, "airborne_at_switch_off": a}
                         for i, (v, d, f, t, a) in enumerate(rows)])


def test_fate_groups(scn):
    df = fake(scn, [("gusts_on_after_2s", 10, "floor", 6.9, 0), ("gusts_on_after_2s", 10, "floor", 7.5, 1),
                    ("gusts_on_after_0s", 10, "floor", 5.5, 1), ("gusts_on_after_0s", 10, "wall x 80 mm", 1, 0),
                    ("gusts_on_after_0s", 10, R.PORT_TUBE, 1, 0), ("gusts_on_after_0s", 10, R.AIRBORNE, np.nan, 1)])
    assert list(R.fate_groups(scn, df)) == [R.FLOOR_MOVING, R.FLOOR_STILL, R.FLOOR_STILL, R.SIDES, R.PORT,
                                            R.AIRBORNE]


def test_weighted_groups_and_floor_purity(scn):
    w = pd.Series(0.0, index=scn.sizes_um)
    w[10.0], w[20.0], w[100.0] = 1.0, 3.0, 1.0
    k = "gusts_on_after_0s"
    rows = [(k, 10, "floor", 1.0, 0)] * scn.per_size + [(k, 20, "floor", 9.0, 1)] * (scn.per_size // 2) + \
        [(k, 20, "wall x 80 mm", 2.0, 0)] * (scn.per_size // 2) + [(k, 100, "floor", 0.5, 0)] * scn.per_size
    df = fake(scn, rows)
    t = R.weighted_groups(scn, df, w, 0, 30).iloc[0]
    assert t[R.FLOOR_MOVING] == pytest.approx(1 / 4) and t[R.FLOOR_STILL] == pytest.approx(1.5 / 4)
    assert t[R.SIDES] == pytest.approx(1.5 / 4) and t["airborne at switch-off"] == pytest.approx(1.5 / 4)
    assert sum(t[g] for g in R.GROUPS) == pytest.approx(1.0)
    tv = R.weighted_groups(scn, df, w, 0, 30, volume=True).iloc[0]
    assert tv[R.FLOOR_MOVING] == pytest.approx(1000 / (1000 + 3 * 8000))
    # on the floor: 10 um (weight 1) + half of 20 um (1.5) in the band, 100 um (1) not
    assert R.floor_purity(scn, df, w, 0, 30)[k] == pytest.approx(2.5 / 3.5)
    assert R.floor_purity(scn, df, w, 0, 30, groups=(R.FLOOR_STILL,))[k] == pytest.approx(1.0)


def test_size_weights_from_the_measured_spray(scn):
    w, info = R.size_weights(scn)
    assert (w[w.index < 9] == 0).all() and (w[(w.index >= 12) & (w.index <= 28)] > 0).all()   # spread from 10 um
    assert info["d_min_um"] == 30


# ---- the checks' maths ---------------------------------------------------------------------------------------------

def test_putnam_drag_is_openfoams():
    assert physics.drag_factor(0.0, "putnam") == pytest.approx(1.0)
    assert physics.drag_factor(8.0, "putnam") == pytest.approx(1 + 4 / 6)
    assert physics.drag_factor(2000.0, "putnam") == pytest.approx(0.424 * 2000 / 24)


def test_check_cases_and_settings(plain):
    p, b = plain
    s = C.build(p, b)
    assert K.cases(s) == ["tracers_gusts_on", "tracers_gusts_off", "column_still_air", "column_cross_flow"]
    t = K.tracer_scenario(s)
    assert t.sizes_um.tolist() == [K.TRACER_UM] and t.per_size == 1800 and t.dt == pytest.approx(s.dt / 3)
    p2 = copy.deepcopy(p)
    p2["checks"] = {"tracers": 0}
    assert K.cases(C.build(p2, b)) == []
    p["checks"]["column_mm"] = [240, 800, -60]
    with pytest.raises(SettingsError, match="not inside"):
        C.build(p, b)


def test_integrator_reaches_the_settling_speed(scn):
    gas = physics.Gas(293.15, 101325.0, 1.204, 1.204 * 1.5e-5)
    T, X, V = K.integrate(scn, [10, 100], gas, "putnam", [0, 0, 0], 0.8)
    vt = physics.settling_speed(np.array([10e-6, 100e-6]), scn.rho_d, gas, "putnam", g=C.G)
    assert -V[-1, :, 1] == pytest.approx(vt, rel=1e-4)
    assert np.allclose(X[:, :, [0, 2]], scn.column[[0, 2]])            # straight down in still air


def test_column_result_on_a_perfect_tracker(scn):
    """Frames made by the integrator itself: no gap, no speed difference."""
    gas = physics.Gas(293.15, 101325.0, 1.204, 1.204 * 1.5e-5)
    s = copy.copy(scn)
    s.sizes_um = np.array([10.0, 50.0])
    T, X, V = K.integrate(s, s.sizes_um, gas, "putnam", [0, 0, -0.2], 0.8)
    rows = []
    for i in range(500, T.size, 500):
        for k, d in enumerate(s.sizes_um):
            rows.append({"t": T[i], "id": k, "d": d * 1e-6, "age": T[i], "x": X[i, k, 0], "y": X[i, k, 1],
                         "z": X[i, k, 2], "ux": V[i, k, 0], "uy": V[i, k, 1], "uz": V[i, k, 2]})
    col = K.column_result(s, pd.DataFrame(rows), gas, [0, 0, -0.2])
    assert col.openfoam_vs_integrator_pct.abs().max() < 1e-9 and col.path_gap_mm.max() < 1e-6
    assert col.at_terminal.all() and col.cross_flow_lag_mm_s.max() < 1e-3


def test_read_vectors(tmp_path):
    f = tmp_path / "U"
    f.write_text(HEAD.format(cls="vectorField", obj="U") + "\n2\n(\n(1 2 3)\n(-4e-05 5 6)\n)\n")
    assert K.read_vectors(f).tolist() == [[1, 2, 3], [-4e-05, 5, 6]]
    f.write_text(HEAD.format(cls="vectorField", obj="U") + "\n3{(0 0 0)}\n")
    assert K.read_vectors(f).shape == (3, 3)


def test_gusts_compare_and_large_droplets(scn):
    rows = []
    for v, dx in (("gusts_on_after_2s", 20.0), ("gusts_off_after_2s", 0.0)):
        for d in (10, 100):
            rows += [(v, d, "floor", 1.0, 0)] * 4
    df = fake(scn, rows)
    df.loc[(df.variant == "gusts_on_after_2s") & (df.d_um == 10), "x_mm"] += 20.0
    gc = {g["band"]: g for g in K.gusts_compare(scn, df)}
    assert gc["0-10 µm"]["centre_shift_mm"] == pytest.approx(20.0)
    assert gc["> 60 µm"]["centre_shift_mm"] == pytest.approx(0.0)
    lg = K.large_near_impact(scn, df)
    assert all(g["r90_mm"] == pytest.approx(np.hypot(160 - 163.7, -210 + 212.5)) for g in lg)


# ---- figures and the report ----------------------------------------------------------------------------------------

def test_figures_and_report(scn, tmp_path):
    rng = np.random.default_rng(0)
    rows = []
    for v in scn.variants():
        for d in (2, 10, 20, 40, 100):
            for _ in range(30):
                fate = "floor" if d >= 20 or rng.random() < 0.5 else "wall x 80 mm"
                rows.append((v.key, d, fate, rng.uniform(0, 300), int(rng.random() < 0.3)))
    df = fake(scn, rows)
    df["x_mm"] = rng.normal(165, 15, len(df)).clip(81, 269)
    df["z_mm"] = rng.normal(-210, 15, len(df)).clip(-297, -18)
    plan = P.plan_view(scn, None, [])
    P.floor_maps(scn, plan, [("", P.band_panels(scn, plan, df[df.variant == "gusts_on_after_0s"]))],
                 tmp_path / "floor.png", "t")
    P.fates_by_size(scn, df, tmp_path / "fates.png", "t")
    assert (tmp_path / "floor.png").stat().st_size > 10_000 and (tmp_path / "fates.png").stat().st_size > 10_000
    meta = {"when": "now", "version": "x", "runs": [{"variant": v.key, "label": v.label,
                                                      "accounting": {"found": 1, "fired_expected": 1, "ok": True}}
                                                     for v in scn.variants()],
            "wall_clock_s": 60, "cases": "/c"}
    ck = {"cases": {}, "gusts": K.gusts_compare(scn, df), "large": K.large_near_impact(scn, df),
          "tracers_vs_sizes": []}
    md = cfd_report.report(scn, "s.yaml", meta, df, ck, [("floor_x.png", "the floor")])
    for part in ("## Headline", "By number", "By volume", "## Checks", "1. Every droplet accounted for: PASS",
                 "5. Gusts on against off", "6. Large droplets", "## Flags", "## Inputs, by how they are known"):
        assert part in md
