"""The physics every phase shares: the gas, the drag on a droplet, the integrator, and a jet's momentum.

All SI inside (m, s, kg, Pa, K). Forces on a droplet: drag and gravity with buoyancy, nothing else (PLAN.md, "The
physics, in short": no evaporation, breakup or collisions; one-way coupling).

Drag: Stokes with the Schiller-Naumann correction, f = 1 + 0.15 Re^0.687, to Re = 1,000; above that the Newton
regime (Cd = 0.44, i.e. f = 0.44 Re / 24), which meets Schiller-Naumann at Re = 1,000 to 0.4 %. Also "putnam",
OpenFOAM's sphereDrag (f = 1 + Re^(2/3) / 6 to Re = 1,000, then Cd = 0.424), for checking OpenFOAM's tracker.

Integrator: the analytic exponential step Fluent's particle model uses. Over one step the gas velocity, the droplet's
relaxation time and gravity are held at their start-of-step values; the droplet's velocity and position then follow
exactly, so the step is stable however small the droplet (a 10 um drop's tau is 0.3 ms).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

G = 9.80665                 # m/s^2, standard gravity
R_AIR = 287.05              # J/(kg K)
GAMMA_AIR = 1.4
RE_NEWTON = 1000.0          # Schiller-Naumann -> Newton (Cd 0.44)
DRAG_LAWS = ("schiller_naumann", "stokes", "putnam")


@dataclass(frozen=True)
class Gas:
    temperature_K: float
    pressure_Pa: float
    density: float          # kg/m^3
    viscosity: float        # Pa s

    @property
    def nu(self) -> float:
        return self.viscosity / self.density


def air(temperature_C: float = 20.0, pressure_Pa: float = 101325.0) -> Gas:
    """Dry air as an ideal gas; viscosity by Sutherland's law (1.813e-5 Pa s at 20 degC)."""
    T = float(temperature_C) + 273.15
    mu = 1.716e-5 * (T / 273.15) ** 1.5 * (273.15 + 110.4) / (T + 110.4)
    return Gas(T, float(pressure_Pa), float(pressure_Pa) / (R_AIR * T), mu)


def drag_factor(Re, law: str = "schiller_naumann"):
    """f = Cd Re / 24: the drag over Stokes' drag at the droplet Reynolds number Re (array or scalar)."""
    Re = np.asarray(Re, float)
    if law == "stokes":
        return np.ones_like(Re)
    if law == "putnam":                                 # OpenFOAM's sphereDrag (Phase 3a's checks compare with it)
        return np.where(Re <= 1000.0, 1.0 + np.power(np.maximum(Re, 0.0), 2.0 / 3.0) / 6.0, 0.424 * Re / 24.0)
    if law != "schiller_naumann":
        raise ValueError(f"drag law {law!r}: use one of {DRAG_LAWS}")
    return np.where(Re < RE_NEWTON, 1.0 + 0.15 * np.power(np.maximum(Re, 0.0), 0.687), 0.44 * Re / 24.0)


def tau_stokes(d, rho_d: float, gas: Gas):
    """The Stokes relaxation time rho_d d^2 / (18 mu) (s) of a droplet of diameter d (m)."""
    d = np.asarray(d, float)
    return rho_d * d * d / (18.0 * gas.viscosity)


def gravity_vector(rho_d: float, gas: Gas, on: bool = True) -> np.ndarray:
    """Gravity less buoyancy on a droplet (m/s^2), z up."""
    return np.array([0.0, 0.0, -G * (1.0 - gas.density / rho_d)]) if on else np.zeros(3)


def settling_speed(d, rho_d: float, gas: Gas, law: str = "schiller_naumann", iters: int = 60, g: float = G):
    """Terminal settling speed (m/s) in still air under the drag law (fixed-point iteration on Re)."""
    d = np.asarray(d, float)
    tau0 = tau_stokes(d, rho_d, gas)
    g_eff = g * (1.0 - gas.density / rho_d)
    v = tau0 * g_eff
    for _ in range(iters):
        v = tau0 * g_eff / drag_factor(gas.density * v * d / gas.viscosity, law)
    return v


def relaxation_time(d, slip_speed, rho_d: float, gas: Gas, law: str = "schiller_naumann"):
    """tau = tau_Stokes / f(Re) at the droplet's present slip speed."""
    d = np.asarray(d, float)
    Re = gas.density * np.asarray(slip_speed, float) * d / gas.viscosity
    return tau_stokes(d, rho_d, gas) / drag_factor(Re, law)


def analytic_step(x, v, u_gas, tau, a, dt):
    """One step of du/dt = (u_gas - u)/tau + a with u_gas, tau, a held constant over dt: exact for that case.

    x, v, u_gas: (N, 3); tau, dt: (N,); a: (3,) or (N, 3). Returns the new position and velocity."""
    tau = np.asarray(tau, float)[:, None]
    dt = np.asarray(dt, float)[:, None]
    u_inf = u_gas + a * tau                         # where the droplet's velocity is heading in this gas
    e = np.exp(-dt / tau)
    dv = v - u_inf
    return x + u_inf * dt + tau * dv * (1.0 - e), u_inf + dv * e


def sccm_to_kg_s(sccm: float, standard_density: float) -> float:
    """Mass flow (kg/s) of a standard volume flow in sccm (standard cm^3 per minute)."""
    return float(sccm) * 1e-6 / 60.0 * float(standard_density)


def jet_exit(mdot: float, area: float, gas: Gas, T0: float | None = None, gamma: float = GAMMA_AIR) -> dict:
    """The exit of a gas jet of mass flow mdot (kg/s) through an effective area (Cd x the bore's area, m^2) into
    the gas at its pressure: one-dimensional, isentropic, single-phase.

    Subsonic: the exit pressure is the chamber's; the exit Mach number follows from the mass flow. Choked: sonic at
    the exit, the excess pressure adds (p* - p_a) A to the thrust (an under-expanded jet). Returns the exit speed,
    the momentum flux J (N, the thrust), the jet's effective speed J / mdot, the Mach number, the upstream stagnation
    pressure and whether it is choked. T0: the supply's stagnation temperature (default the chamber's)."""
    T0 = gas.temperature_K if T0 is None else float(T0)
    pa = gas.pressure_Pa
    k = math.sqrt(gamma / (R_AIR * T0))
    crit = (2.0 / (gamma + 1.0)) ** ((gamma + 1.0) / (2.0 * (gamma - 1.0)))     # 0.5787 for air
    p_ratio = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))                   # p*/p0 = 0.5283
    mdot_choke = area * (pa / p_ratio) * k * crit       # the most mass flow the exit passes at ambient pressure
    if mdot <= mdot_choke:
        # mdot = A pa M sqrt(gamma / (R T0)) sqrt(1 + (gamma-1)/2 M^2): monotone in M on [0, 1]
        target = mdot / (area * pa * k)
        lo, hi = 0.0, 1.0
        for _ in range(80):
            m = 0.5 * (lo + hi)
            if m * math.sqrt(1.0 + 0.5 * (gamma - 1.0) * m * m) < target:
                lo = m
            else:
                hi = m
        M = 0.5 * (lo + hi)
        T = T0 / (1.0 + 0.5 * (gamma - 1.0) * M * M)
        u = M * math.sqrt(gamma * R_AIR * T)
        p0 = pa * (1.0 + 0.5 * (gamma - 1.0) * M * M) ** (gamma / (gamma - 1.0))
        J = mdot * u
        choked = False
    else:
        p0 = mdot / (area * k * crit)
        T = T0 * 2.0 / (gamma + 1.0)
        u = math.sqrt(gamma * R_AIR * T)
        M = 1.0
        J = mdot * u + (p_ratio * p0 - pa) * area
        choked = True
    return {"exit_speed_m_s": u, "momentum_N": J, "effective_speed_m_s": J / mdot if mdot > 0 else 0.0,
            "mach": M, "p0_Pa": p0, "choked": choked}
