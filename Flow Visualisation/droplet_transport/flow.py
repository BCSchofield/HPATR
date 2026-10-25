"""The idealised airflow of Phase 1: textbook jets added together, plus a slow drift towards the outlets.

What it is not (PLAN.md, Phase 1): the jets do not bend each other, there is no recirculation, and the walls do not
turn the flow. In the closed chamber the spray jet's circulation dominates, so delivery to the target from this flow
is idealised; the headline is how far each jet carries or deflects each size.

Every jet is set by its MASS FLOW and MOMENTUM (corrected 2026-10-23: the 100-460 m/s 'exit speeds' were the
standard-density Q/A equivalents). From the momentum flux J and the chamber gas density rho:

    round jet: K = U0 d0 = sqrt(4 J / (pi rho)), U0 = J / mdot (the effective speed), d0 = K / U0
               centreline u_c = B K / xi,  half-width r_1/2 = S xi,  xi = s + B d0
    slot jet:  K = U0^2 b0 = J / (rho L) per unit length,  u_c = B U0 sqrt(b0 / xi),  y_1/2 = S xi,  xi = s + B^2 b0

s is the distance along the jet's axis from its exit. The shift of the origin by B d0 (B^2 b0) puts u_c = U0 at the
exit and, with S B ~ 0.55, the half-width at about the exit's radius; far from the exit it is the textbook decay
(Hussein, Capp & George 1994: B 5.8, S 0.094; plane jet B 2.4, S 0.10). Profiles are Gaussian. The velocity across
the jet comes from continuity (the self-similar solution), so the jet entrains: far from a round jet's axis the
inflow is -B K sigma^2 / (2 r) (sigma^2 = S^2 / ln 2), 0.23 K per metre of jet against Ricou & Spalding's 0.25.
A slot jet is a plane jet over its length, fading at its ends over a half-width: right for distances under the
slot's length, too fast beyond (it never turns round).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import erf

from . import physics

LN2 = math.log(2.0)


def _dot(a, v):
    """(N, 3) . (3,) without matmul (macOS Accelerate raises spurious warnings on finite input)."""
    return a[:, 0] * v[0] + a[:, 1] * v[1] + a[:, 2] * v[2]


class RoundJet:
    def __init__(self, origin, axis, momentum_N: float, mdot: float, rho: float, B: float = 5.8,
                 S: float = 0.094, entrainment: bool = True, name: str = "jet"):
        self.origin = np.asarray(origin, float)
        self.axis = np.asarray(axis, float) / np.linalg.norm(axis)
        self.J, self.mdot, self.rho = float(momentum_N), float(mdot), float(rho)
        self.B, self.S, self.entrainment, self.name = float(B), float(S), bool(entrainment), name
        self.K = math.sqrt(4.0 * self.J / (math.pi * self.rho)) if self.J > 0 else 0.0
        self.U0 = self.J / self.mdot if self.mdot > 0 else 0.0
        self.d0 = self.K / self.U0 if self.U0 > 0 else 0.0
        self.sigma2 = self.S ** 2 / LN2

    def xi(self, s):
        return np.asarray(s, float) + self.B * self.d0

    def centreline(self, s):
        return self.B * self.K / self.xi(s) if self.K > 0 else np.zeros_like(np.asarray(s, float))

    def half_width(self, s):
        return self.S * self.xi(s)

    def velocity(self, P) -> np.ndarray:
        P = np.asarray(P, float)
        out = np.zeros_like(P)
        if self.K <= 0:
            return out
        d = P - self.origin
        s = _dot(d, self.axis)
        ok = s > 0.0
        if not ok.any():
            return out
        s, d = s[ok], d[ok]
        rvec = d - s[:, None] * self.axis
        r2 = np.einsum("ij,ij->i", rvec, rvec)
        xi = self.xi(s)
        T = r2 / (self.sigma2 * xi * xi)                       # = ln2 (r / r_1/2)^2
        eT = np.exp(-T)
        A = self.B * self.K
        u = (A / xi * eT)[:, None] * self.axis
        if self.entrainment:
            # v_r = A r h(T) / (2 xi^2), h = (1 - (1 + 2T) e^-T) / -T: outwards near the axis, inwards beyond
            with np.errstate(invalid="ignore", divide="ignore"):
                h = np.where(T > 1e-6, -(1.0 - (1.0 + 2.0 * T) * eT) / np.maximum(T, 1e-300), 1.0 - 1.5 * T)
            u = u + (A * h / (2.0 * xi * xi))[:, None] * rvec
        out[ok] = u
        return out


class SlotJet:
    def __init__(self, origin, axis, long_axis, length: float, momentum_N: float, mdot: float, rho: float,
                 B: float = 2.4, S: float = 0.10, entrainment: bool = True, name: str = "slot jet"):
        self.origin = np.asarray(origin, float)
        self.axis = np.asarray(axis, float) / np.linalg.norm(axis)
        w = np.asarray(long_axis, float) - (np.asarray(long_axis, float) @ self.axis) * self.axis
        self.span = w / np.linalg.norm(w)
        self.cross = np.cross(self.axis, self.span)
        self.L, self.J, self.mdot, self.rho = float(length), float(momentum_N), float(mdot), float(rho)
        self.B, self.S, self.entrainment, self.name = float(B), float(S), bool(entrainment), name
        Kp = self.J / (self.rho * self.L) if self.J > 0 else 0.0
        self.U0 = self.J / self.mdot if self.mdot > 0 else 0.0
        self.b0 = Kp / self.U0 ** 2 if self.U0 > 0 else 0.0
        self.sigma = self.S / math.sqrt(LN2)

    def xi(self, s):
        return np.asarray(s, float) + self.B ** 2 * self.b0

    def centreline(self, s):
        return self.B * self.U0 * np.sqrt(self.b0 / self.xi(s)) if self.b0 > 0 else np.zeros_like(np.asarray(s))

    def half_width(self, s):
        return self.S * self.xi(s)

    def velocity(self, P) -> np.ndarray:
        P = np.asarray(P, float)
        out = np.zeros_like(P)
        if self.b0 <= 0:
            return out
        d = P - self.origin
        s = _dot(d, self.axis)
        ok = s > 0.0
        if not ok.any():
            return out
        s, d = s[ok], d[ok]
        y, w = _dot(d, self.cross), _dot(d, self.span)
        xi = self.xi(s)
        yh = self.S * xi
        over = np.maximum(np.abs(w) - self.L / 2.0, 0.0)
        g = np.exp(-LN2 * (over / yh) ** 2)                    # fades beyond the slot's ends
        A = self.B * self.U0 * math.sqrt(self.b0)
        T = np.abs(y) / (self.sigma * xi)
        u = (A / np.sqrt(xi) * np.exp(-T * T) * g)[:, None] * self.axis
        if self.entrainment:
            v = -A * self.sigma / np.sqrt(xi) * (math.sqrt(math.pi) / 4.0 * erf(T) - T * np.exp(-T * T))
            u = u + (v * np.sign(y) * g)[:, None] * self.cross
        out[ok] = u
        return out


class Drift:
    """The through-flow spread over the chamber: (inlets + spray gas) / cross-section, towards the outlets."""

    def __init__(self, velocity):
        self.u = np.asarray(velocity, float)
        self.name = "drift"

    def velocity(self, P) -> np.ndarray:
        return np.broadcast_to(self.u, np.shape(P)).copy()


class Flow:
    def __init__(self, components: list, notes: dict | None = None):
        self.components = components
        self.notes = notes or {}

    def velocity(self, P) -> np.ndarray:
        P = np.atleast_2d(np.asarray(P, float))
        u = np.zeros_like(P)
        for c in self.components:
            u += c.velocity(P)
        return u

    def jet(self, name: str):
        return next(c for c in self.components if c.name == name)


def spray_exit(scn) -> dict:
    """The spray gas's exit through its orifice (effective area Cd x the bore's)."""
    mdot = physics.sccm_to_kg_s(scn.spray.gas_flow_sccm, scn.standard_density)
    area = scn.spray.orifice_cd * math.pi / 4.0 * (scn.spray.orifice_mm / 1000.0) ** 2
    out = physics.jet_exit(mdot, area, scn.gas) if mdot > 0 else {"momentum_N": 0.0, "effective_speed_m_s": 0.0,
                                                                  "exit_speed_m_s": 0.0, "mach": 0.0,
                                                                  "p0_Pa": scn.gas.pressure_Pa, "choked": False}
    out.update(mdot_kg_s=mdot, area_m2=area)
    return out


def build_flow(scn) -> Flow:
    """The scenario's idealised gas flow: the spray jet, one jet per inlet, and the drift."""
    rho, J = scn.gas.density, scn.jets
    comps, notes = [], {}
    sx = spray_exit(scn)
    notes["spray"] = sx
    comps.append(RoundJet(scn.spray.nozzle, scn.spray.axis, sx["momentum_N"], sx["mdot_kg_s"], rho,
                          J["round_B"], J["round_S"], scn.entrainment, name="spray"))
    q_total = sx["mdot_kg_s"] / rho
    for p in scn.inlets:
        mdot = physics.sccm_to_kg_s(p.flow_sccm, scn.standard_density)
        ex = physics.jet_exit(mdot, p.area, scn.gas) if mdot > 0 else {"momentum_N": 0.0}
        ex.update(mdot_kg_s=mdot)
        notes[p.name] = ex
        q_total += mdot / rho
        if p.shape == "round":
            comps.append(RoundJet(p.centre, p.direction, ex["momentum_N"], mdot, rho, J["round_B"], J["round_S"],
                                  scn.entrainment, name=p.name))
        else:
            comps.append(SlotJet(p.centre, p.direction, p.long_axis, p.length, ex["momentum_N"], mdot, rho,
                                 J["slot_B"], J["slot_S"], scn.entrainment, name=p.name))
    # the drift: from the inlets' mean position (or the nozzle) to the outlets' mean position
    src = np.mean([p.centre for p in scn.inlets], axis=0) if scn.inlets else scn.spray.nozzle
    dst = np.mean([p.centre for p in scn.outlets], axis=0)
    e = dst - src
    if np.linalg.norm(e) > 0 and q_total > 0:
        e = e / np.linalg.norm(e)
        Lx, Ly, Lz = scn.box
        a_cross = abs(e[0]) * Ly * Lz + abs(e[1]) * Lx * Lz + abs(e[2]) * Lx * Ly
        comps.append(Drift(e * q_total / a_cross))
        notes["drift_m_s"] = q_total / a_cross
    else:
        notes["drift_m_s"] = 0.0
    notes["through_flow_m3_s"] = q_total
    return Flow(comps, notes)
