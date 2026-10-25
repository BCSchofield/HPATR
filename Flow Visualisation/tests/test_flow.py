"""The idealised jets (PLAN.md, Phase 1 check 5: the textbook centreline decay and spreading rate)."""
import math

import numpy as np
import pytest

from droplet_transport import flow as F
from droplet_transport import physics, settings

RHO = physics.air().density


def round_jet(**kw):
    mdot = physics.sccm_to_kg_s(10000, 1.184)
    return F.RoundJet([0, 0, 0], [0, 0, -1], momentum_N=mdot * 200.0, mdot=mdot, rho=RHO, **kw)


def test_round_jet_exit_and_textbook_decay():
    j = round_jet()
    assert j.centreline(0.0) == pytest.approx(j.U0)                       # u_c = U0 at the exit
    assert j.half_width(0.0) == pytest.approx(0.545 * j.d0, rel=0.01)     # about the exit's radius
    for s in (0.05, 0.1, 0.3):
        assert j.centreline(s) * (s + j.B * j.d0) == pytest.approx(j.B * j.U0 * j.d0)
    # far away: u_c = B U0 d0 / s (Hussein et al. 1994, B = 5.8)
    assert j.centreline(0.3) * 0.3 / (j.U0 * j.d0) == pytest.approx(5.8, rel=0.03)
    assert j.d0 == pytest.approx(math.sqrt(4 * j.J / (math.pi * RHO)) / j.U0)


def test_round_jet_profile_spreads_at_S():
    j = round_jet()
    s = 0.12
    P = np.array([[r, 0.0, -s] for r in np.linspace(0, 0.05, 20001)])
    ua = -j.velocity(P)[:, 2]
    r_half = P[np.argmin(np.abs(ua - ua[0] / 2)), 0]
    assert r_half / (s + j.B * j.d0) == pytest.approx(0.094, rel=1e-3)


def _divergence(fl, P, h=1e-6):
    div = np.zeros(len(P))
    for a in range(3):
        e = np.zeros(3)
        e[a] = h
        div += (fl.velocity(P + e)[:, a] - fl.velocity(P - e)[:, a]) / (2 * h)
    return div


def test_round_jet_conserves_mass():
    j = round_jet()
    rng = np.random.default_rng(3)
    s = rng.uniform(0.02, 0.3, 400)
    r = rng.uniform(0, 3, 400) * 0.094 * (s + j.B * j.d0)
    th = rng.uniform(0, 2 * np.pi, 400)
    P = np.c_[r * np.cos(th), r * np.sin(th), -s]
    scale = j.centreline(s) / (s + j.B * j.d0)
    assert np.max(np.abs(_divergence(j, P)) / scale) < 1e-4


def test_round_jet_entrains_like_ricou_spalding():
    """Inflow through a cylinder well outside the jet: ~0.23 K per metre against Ricou & Spalding's
    0.32 x/d0 (0.25 K per metre)."""
    j = round_jet()
    R = 0.15
    s = np.linspace(0.2, 0.3, 2001)
    v_r = np.array([j.velocity([[R, 0.0, -si]])[0, 0] for si in s])
    q_per_m = -2 * np.pi * R * np.trapezoid(v_r, s) / 0.1
    assert q_per_m == pytest.approx(0.25 * j.U0 * j.d0, rel=0.10)


def test_nothing_behind_the_exit():
    j = round_jet()
    assert np.allclose(j.velocity([[0.01, 0, 0.001], [0, 0, 0.05]]), 0.0)


def test_entrainment_switch():
    j = round_jet(entrainment=False)
    u = j.velocity([[0.1, 0.0, -0.1]])[0]
    assert abs(u[0]) < 1e-15 and u[2] < 0


def test_slot_jet_decay_and_mass_inside_its_span():
    mdot = physics.sccm_to_kg_s(8000, 1.184)
    A = 0.1 * 0.002
    J = physics.jet_exit(mdot, A, physics.air())["momentum_N"]
    j = F.SlotJet([0, 0, 0], [1, 0, 0], [0, 0, 1], 0.1, J, mdot, RHO)
    assert j.b0 == pytest.approx(0.002, rel=0.01)
    assert j.centreline(0.0) == pytest.approx(j.U0)
    for s in (0.02, 0.05):
        assert j.centreline(s) * math.sqrt(s + j.B ** 2 * j.b0) == pytest.approx(j.B * j.U0 * math.sqrt(j.b0))
    rng = np.random.default_rng(1)
    s = rng.uniform(0.01, 0.08, 300)
    y = rng.uniform(-2, 2, 300) * 0.1 * (s + j.B ** 2 * j.b0)
    w = rng.uniform(-0.03, 0.03, 300)
    P = np.c_[s, -y, w]                                    # cross = axis x span = x x z = -y
    scale = j.centreline(s) / (s + j.B ** 2 * j.b0)
    assert np.max(np.abs(_divergence(j, P)) / scale) < 1e-4


def test_flow_is_the_sum_and_drift_follows_the_ports(base):
    scn = settings.build(base, {})
    fl = F.build_flow(scn)
    assert [c.name for c in fl.components] == ["spray", "right inlet", "drift"]
    P = np.array([[100e-3, 80e-3, 200e-3], [250e-3, 100e-3, 175e-3]])
    assert np.allclose(fl.velocity(P), sum(c.velocity(P) for c in fl.components))
    drift = fl.components[-1].u
    q = (physics.sccm_to_kg_s(8995, 1.184) + physics.sccm_to_kg_s(8000, 1.184)) / scn.gas.density
    assert drift == pytest.approx([-q / (0.2 * 0.35), 0, 0])
    # the spray's jet: mass flow and momentum from the gas dynamics, the effective speed J / mdot
    sx = fl.notes["spray"]
    assert fl.jet("spray").U0 == pytest.approx(sx["momentum_N"] / sx["mdot_kg_s"])
