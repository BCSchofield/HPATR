"""The droplet physics and the integrator (PLAN.md, Phase 1 checks 1-4) and the jet exit's gas dynamics."""
import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from droplet_transport import flow as F
from droplet_transport import injection, physics, settings, tracker

GAS = physics.air(20.0, 101325.0)
RHO_D = 1070.0


def still(base, **spray):
    """No inlets, no spray gas: still air (the drift is zero too)."""
    base["inlets"] = []
    base["spray"]["gas_flow_sccm"] = 0
    base["spray"]["droplets"].update(start_radius_mm=0, cone_half_angle_deg=0, per_size=1, **spray)
    return base


def test_air_properties():
    assert GAS.density == pytest.approx(1.204, abs=0.001)
    assert GAS.viscosity == pytest.approx(1.813e-5, rel=0.002)


def test_drag_factor_meets_newton_at_re_1000():
    f = physics.drag_factor(np.array([999.999, 1000.001]))
    assert f[0] == pytest.approx(f[1], rel=5e-3)
    assert physics.drag_factor(0.0) == pytest.approx(1.0)
    assert physics.drag_factor(5.0, "stokes") == 1.0


def test_check1_terminal_speed_from_rest_in_still_air(base):
    """A droplet released at rest in still air reaches the settling speed the drag law gives."""
    base = still(base, speed_m_s=0.0, standoff_mm=1, sizes_um=[10, 30, 60, 100, 200])
    base["chamber"]["size_mm"] = [300, 200, 3000]
    base["spray"]["nozzle_mm"] = [150, 100, 3000]
    base["run"]["max_time_s"] = 2.0
    scn = settings.build(base, {})
    drops = injection.fire(scn, np.random.default_rng(0))
    tr = tracker.track(scn, F.build_flow(scn), drops)
    vt = physics.settling_speed(drops.d, RHO_D, GAS)
    assert np.allclose(-tr.v_end[:, 2], vt, rtol=2e-3)
    assert np.allclose(tr.v_end[:, :2], 0.0, atol=1e-9)
    # Stokes settling for the small ones (Re 0.002: Schiller-Naumann still adds 0.2 %), the correction for the big
    assert vt[0] == pytest.approx(physics.tau_stokes(10e-6, RHO_D, GAS) * physics.G * (1 - GAS.density / RHO_D),
                                  rel=3e-3)
    assert vt[-1] < 0.8 * physics.tau_stokes(200e-6, RHO_D, GAS) * physics.G


def test_check2_uniform_flow_stokes_is_exact_with_large_steps():
    """In uniform flow with Stokes drag the step is the exact solution, even at dt = 5 tau."""
    d = np.array([30e-6, 100e-6])
    tau = physics.tau_stokes(d, RHO_D, GAS)
    a = physics.gravity_vector(RHO_D, GAS)
    U = np.array([2.0, -1.0, 0.5])
    x = np.zeros((2, 3))
    v = np.array([[0.0, 3.0, -6.0], [5.0, 0.0, 0.0]])
    x0, v0 = x.copy(), v.copy()
    for _ in range(10):
        x, v = physics.analytic_step(x, v, np.tile(U, (2, 1)), tau, a, 5.0 * tau)
    t = 50.0 * tau[:, None]
    u_inf = U + a * tau[:, None]
    exact_v = u_inf + (v0 - u_inf) * np.exp(-t / tau[:, None])
    exact_x = x0 + u_inf * t + tau[:, None] * (v0 - u_inf) * (1 - np.exp(-t / tau[:, None]))
    assert np.allclose(v, exact_v, rtol=1e-12, atol=1e-12)
    assert np.allclose(x, exact_x, rtol=1e-12, atol=1e-12)


def test_check2_tracker_in_uniform_drift_is_exact(base):
    """The tracker too, with steps of many tau, through a uniform flow (Stokes, gravity on)."""
    base = still(base, speed_m_s=2.0, standoff_mm=10, sizes_um=[50])
    base["physics"]["drag"] = "stokes"
    base["run"].update(max_time_s=0.2, max_step_s=0.05, step_mm=1e4)
    scn = settings.build(base, {})
    drops = injection.fire(scn, np.random.default_rng(0))
    U = np.array([-0.3, 0.1, 0.2])
    tr = tracker.track(scn, F.Flow([F.Drift(U)]), drops)
    tau = float(physics.tau_stokes(50e-6, RHO_D, GAS))
    a = physics.gravity_vector(RHO_D, GAS)
    T = 0.2
    u_inf = U + a * tau
    exact = drops.x0[0] + u_inf * T + tau * (drops.v0[0] - u_inf) * (1 - math.exp(-T / tau))
    assert tr.fate[0] == "airborne"
    assert np.allclose(tr.end[0], exact, rtol=0, atol=1e-9)


def _stop_reference(d, v0, law):
    """Stopping distance in still air, no gravity, by a fine ODE solve (independent of the integrator)."""
    tau0 = float(physics.tau_stokes(d, RHO_D, GAS))

    def rhs(_t, y):
        u = max(y[1], 0.0)
        return [u, -u * float(physics.drag_factor(GAS.density * u * d / GAS.viscosity, law)) / tau0]
    sol = solve_ivp(rhs, (0, 40 * tau0), [0.0, v0], rtol=1e-10, atol=1e-13, method="LSODA")
    return sol.y[0, -1]


@pytest.mark.parametrize("d_um, ratio", [(30, 0.746), (60, 0.647)])
def test_check3_schiller_naumann_shortens_the_stop(base, d_um, ratio):
    """At 4 m/s the droplets start past Stokes: SN stops them sooner than Stokes by the ODE's ratio (PLAN.md:
    about a quarter at 30 um, a third at 60 um), and the tracker matches the ODE."""
    d = d_um * 1e-6
    sn, st = _stop_reference(d, 4.0, "schiller_naumann"), _stop_reference(d, 4.0, "stokes")
    assert st == pytest.approx(4.0 * float(physics.tau_stokes(d, RHO_D, GAS)), rel=1e-6)
    assert sn / st == pytest.approx(ratio, abs=0.005)
    for step_mm, tol in ((0.05, 0.003), (0.5, 0.02)):
        b = still(base, speed_m_s=4.0, standoff_mm=1, sizes_um=[d_um])
        b["spray"].update(nozzle_mm=[10, 100, 175], tilt_deg=90, lean_toward_deg=0)
        b["physics"]["gravity"] = False
        b["run"].update(step_mm=step_mm, max_time_s=40 * float(physics.tau_stokes(d, RHO_D, GAS)))
        scn = settings.build(b, {})
        drops = injection.fire(scn, np.random.default_rng(0))
        tr = tracker.track(scn, F.build_flow(scn), drops)
        assert tr.end[0, 0] - drops.x0[0, 0] == pytest.approx(sn, rel=tol)


def test_check4_size_sorts_the_deflection(base):
    """A very small droplet follows the gas; a very large one barely notices a jet; the deflection by the
    cross-jet falls steadily with size."""
    base["spray"]["gas_flow_sccm"] = 0
    base["spray"]["droplets"].update(start_radius_mm=0, cone_half_angle_deg=0, per_size=1, speed_m_s=0.5,
                                     sizes_um=[1, 5, 10, 20, 30, 45, 60, 80, 100, 150, 200, 300, 500, 1000, 2000])
    base["inlets"][0]["flow_sccm"] = 20000
    base["planes"] = [{"axis": "z", "at_mm": 100, "name": "below"}]
    scn = settings.build(base, {})
    drops = injection.fire(scn, np.random.default_rng(0))
    fl = F.build_flow(scn)
    tr = tracker.track(scn, fl, drops)
    moved = drops.x0[:, 0] - tr.end[:, 0]                 # towards the outlet wall (x = 0)
    assert (np.diff(moved) <= 1e-6).all(), moved
    assert moved[0] > 100e-3 and moved[-1] < 5e-3      # (500 um still moves ~23 mm: 2 m/s of jet)
    # the 1 um droplet (tau 3 us) moves with the gas: its velocity where it crosses a plane = the gas's + settling
    tiny = physics.settling_speed(1e-6, RHO_D, GAS)
    b2 = settings.build({**base, "planes": [{"axis": "x", "at_mm": 100, "name": "mid"}]}, {})
    tr2 = tracker.track(b2, fl, injection.fire(b2, np.random.default_rng(0)))
    pos, vel = tr2.crossings[0]["pos"][0], tr2.crossings[0]["v"][0]
    ug = fl.velocity(pos[None])[0] + np.array([0, 0, -tiny])
    assert np.isfinite(pos).all()
    assert np.linalg.norm(vel - ug) < 0.02 * np.linalg.norm(ug)


def test_jet_exit_low_speed_is_q_over_a():
    mdot = physics.sccm_to_kg_s(8000, 1.184)
    A = math.pi / 4 * 0.006 ** 2
    ex = physics.jet_exit(mdot, A, GAS)
    assert not ex["choked"]
    assert ex["exit_speed_m_s"] == pytest.approx(mdot / (GAS.density * A), rel=1e-3)
    assert ex["momentum_N"] == pytest.approx(mdot * ex["exit_speed_m_s"])


def test_jet_exit_reproduces_the_cd_test():
    """12,000 sccm through the 0.8 mm insert (Cd 0.814) needed 2.41 barA (Cd tests, 2026-10-15)."""
    ex = physics.jet_exit(physics.sccm_to_kg_s(12000, 1.184), 0.814 * math.pi / 4 * 0.0008 ** 2, GAS)
    assert ex["choked"]
    assert ex["p0_Pa"] / 1e5 == pytest.approx(2.41, rel=0.03)
    assert ex["momentum_N"] > ex["mach"] * 0 + physics.sccm_to_kg_s(12000, 1.184) * ex["exit_speed_m_s"]


def test_jet_exit_is_continuous_where_it_chokes():
    A = 0.5e-6
    k = math.sqrt(1.4 / (physics.R_AIR * GAS.temperature_K))
    m_choke = A * GAS.pressure_Pa / 0.528282 * k * 0.578704
    lo, hi = physics.jet_exit(m_choke * (1 - 1e-5), A, GAS), physics.jet_exit(m_choke * (1 + 1e-5), A, GAS)
    assert not lo["choked"] and hi["choked"]
    assert lo["momentum_N"] == pytest.approx(hi["momentum_N"], rel=1e-4)
    assert lo["p0_Pa"] == pytest.approx(hi["p0_Pa"], rel=1e-4)
