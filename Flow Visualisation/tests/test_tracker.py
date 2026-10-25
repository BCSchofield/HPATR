"""The tracker: fates, walls and outlets, plane crossings, the random walk and the accounting (PLAN.md, Phase 1
checks 6 and 7)."""
import numpy as np
import pytest

from droplet_transport import analysis, injection, settings, tracker
from droplet_transport import flow as F


def straight(base, nozzle, tilt, lean, size=500, speed=20.0):
    """A big droplet fired straight (no gas, no gravity) from `nozzle` along (tilt, lean)."""
    base["inlets"] = []
    base["spray"].update(nozzle_mm=nozzle, tilt_deg=tilt, lean_toward_deg=lean, gas_flow_sccm=0)
    base["spray"]["droplets"].update(start_radius_mm=0, cone_half_angle_deg=0, per_size=1, speed_m_s=speed,
                                     sizes_um=[size], standoff_mm=5)
    base["physics"]["gravity"] = False
    return settings.build(base, {})


def run(scn, flow=None, seed=1):
    drops = injection.fire(scn, np.random.default_rng(0))
    return drops, tracker.track(scn, flow or F.build_flow(scn), drops, np.random.default_rng(seed))


def test_hits_the_outlet_or_the_wall_and_where(base):
    scn = straight(base, [200, 100, 175], 90, 180)                 # straight at the left outlet's centre
    _d, tr = run(scn)
    assert tr.fate[0] == "outlet:left outlet"
    assert tr.end[0] == pytest.approx([0.0, 0.1, 0.175], abs=1e-9)
    scn = straight(base, [200, 40, 300], 90, 180)                  # the left wall, away from the outlet
    _d, tr = run(scn)
    assert tr.fate[0] == "wall:left"
    assert tr.end[0] == pytest.approx([0.0, 0.04, 0.3], abs=1e-9)
    scn = straight(base, [150, 100, 340], 0, 0)                    # straight down: the floor
    _d, tr = run(scn)
    assert tr.fate[0] == "wall:floor" and tr.end[0, 2] == 0.0


def test_slot_outlet_and_target_box(base):
    base["outlets"] = [{"name": "slot", "wall": "left", "centre_mm": {"y": 100, "z": 175}, "shape": "slot",
                        "width_mm": 4, "length_mm": 100, "long_side_along": "y"}]
    base["target"] = {"outlet": "slot", "band_um": [30, 60]}
    _d, tr = run(straight(base, [200, 140, 175], 90, 180))
    assert tr.fate[0] == "outlet:slot"
    _d, tr = run(straight(base, [200, 140, 180], 90, 180))         # 5 mm above a 4 mm-wide slot's centre
    assert tr.fate[0] == "wall:left"
    base["target"] = {"box_mm": {"from": [50, 80, 150], "to": [70, 120, 200]}, "band_um": [30, 60]}
    _d, tr = run(straight(base, [200, 100, 175], 90, 180))
    assert tr.fate[0] == "target" and 0.05 <= tr.end[0, 0] <= 0.0705


def test_plane_crossing_is_where_the_line_crosses(base):
    base["planes"] = [{"axis": "x", "at_mm": 123, "name": "x123"}, {"axis": "z", "at_mm": 100, "name": "low"}]
    scn = straight(base, [200, 100, 175], 90, 180)
    _d, tr = run(scn)
    assert tr.crossings[0]["pos"][0] == pytest.approx([0.123, 0.1, 0.175], abs=1e-9)
    assert np.isnan(tr.crossings[1]["t"][0])                        # never reaches z = 100 mm


def test_check6_random_walk(base):
    """Off: repeatable. On: the spread grows, the mean path does not move (uniform flow, uniform turbulence)."""
    base["inlets"] = []
    base["spray"].update(nozzle_mm=[10, 100, 175], tilt_deg=90, lean_toward_deg=0, gas_flow_sccm=0)
    base["spray"]["droplets"].update(start_radius_mm=0, cone_half_angle_deg=0, per_size=1500, speed_m_s=1.0,
                                     sizes_um=[10], standoff_mm=5)
    base["physics"]["gravity"] = False
    base["planes"] = [{"axis": "x", "at_mm": 200, "name": "far"}]
    U = F.Flow([F.Drift([1.0, 0.0, 0.0])])
    scn = settings.build(base, {})
    _d, a = run(scn, U, seed=1)
    _d, b = run(scn, U, seed=2)
    assert np.array_equal(a.crossings[0]["pos"], b.crossings[0]["pos"], equal_nan=True)
    assert np.ptp(a.crossings[0]["pos"][:, 1:], axis=0).max() < 1e-12
    base["physics"]["random_walk"] = {"on": True, "intensity": 0.2, "time_scale_s": 0.005}
    scn = settings.build(base, {})
    _d, c = run(scn, U, seed=3)
    pos = c.crossings[0]["pos"]
    assert np.isfinite(pos).all()
    sd = pos[:, 1:].std(axis=0)
    assert (sd > 1e-3).all()
    se = sd / np.sqrt(len(pos))
    assert np.all(np.abs(pos[:, 1:].mean(axis=0) - [0.1, 0.175]) < 4 * se)
    _d, d = run(scn, U, seed=3)
    assert np.array_equal(c.crossings[0]["pos"], d.crossings[0]["pos"])     # the same seed repeats


def test_check7_every_droplet_is_accounted_for(base):
    base["spray"]["droplets"]["per_size"] = 15
    scn = settings.build(base, {})
    drops, tr = run(scn)
    acc = analysis.accounting(tr, drops)
    assert acc["ok"] and acc["accounted"] == drops.d.size == 20 * 15
    assert np.isfinite(tr.end).all() and np.isfinite(tr.t_end).all()
    ps = analysis.per_size(scn, drops, tr, F.build_flow(scn))
    assert np.allclose(ps[list(analysis.CATEGORIES)].sum(axis=1), 1.0)
    fates = [c for c in ps.columns if c.startswith(("outlet:", "wall:", "airborne", "target"))
             and c != "target"]
    assert np.allclose(ps[fates].sum(axis=1), 1.0)


def test_time_limit_leaves_them_airborne(base):
    base["spray"]["droplets"].update(per_size=3, sizes_um=[10])
    base["run"]["max_time_s"] = 0.001
    scn = settings.build(base, {})
    drops, tr = run(scn)
    assert (tr.fate == "airborne").all()
    assert tr.t_end == pytest.approx(np.full(3, 0.001))
