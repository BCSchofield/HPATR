"""covariates.py -- GLR and the gas mass flux at the orifice (and the run context they come
from), and how each response relates to them. No Qt in here.

GLR = gas mass flow / liquid mass flow, dimensionless. It is NOT a Taguchi factor: it is
computed from the gas flow and the liquid (silicone) flow, so as a factor it would be
aliased with them -- the nine L9 conditions give only seven distinct GLRs. It is analysed
as a COVARIATE instead: how strongly each response follows GLR across the runs. That is
descriptive (it cannot separate GLR from the factors it is made of), and the report says so.

WHERE EACH RUN'S GLR COMES FROM, in order:
  recorded   the GLR in run_summary.xlsx, written by the capture GUI at the time;
  computed   the capture GUI's OWN formula (GUI_Clean.AtomisationApp._glr_working, called,
             not copied: change the bore or steps/mm there and this follows), from the
             workbook's gas flow, motor speed and the two densities;
  missing    no GLR and no densities recorded (the 2026/10/01 runs): not guessed.
Verified: the GUI formula reproduces the recorded GLR of all 27 runs of 2026/10/05 to 4 dp.

Also per run, for the report: the ACHIEVED-flow GLR (same formula with the plateau flow the
mass-flow controller actually reached, from the workbook's flow range, instead of the
setpoint), fluid, gas, densities and peak pressure.

GAS MASS FLUX AT THE ORIFICE (2026-10-13), G = delivered gas mass flow / orifice area, kg/m2/s:
    m_dot = sccm x rho_gas / 6e7 (kg/s; sccm is at standard conditions and rho_gas is the run's recorded
    'Gas density (kg/m3)', the one GLR uses), A = pi d^2 / 4 from the run's orifice.
Why: on the CCD day (2026-10-12, 31 spraying runs, both regimes) the gas per orifice area ordered
atomised fraction better than anything set or measured (Spearman +0.91; P0 +0.83, gas set point +0.35,
GLR -0.21), and it puts flow-controlled and pressure-limited runs on one axis
(docs/notes/2026-10-13_phase12_physical_variables.md). Like GLR it is a COVARIATE, not a factor: it is
made from the gas flow and the orifice, so it is aliased with them; the set points stay the factors.
The gas it uses, in order (gas_flux_source):
    camera window          what the run got while the camera ran (operating.py; set by with_operating()
                           once stats.load_measured_run has the run's operating point)
    achieved (flow range)  the top of the workbook's flow range (for a pressure-limited run that is the
                           flow BEFORE the silicone choked the orifice, so a poor stand-in)
    set point              the folder name's set point
    missing                no gas flow or no orifice
No gas density recorded (the 2026/10/01 runs): no flux, not guessed (as for GLR); the exit velocity
equivalent needs no density and is still given.
Compressibility: at a choked small orifice the real exit velocity is sonic and the gas there is denser
than standard, so "delivered sccm / area" is not the velocity the jet has. The MASS flux is the honest
quantity; exit_velocity_std = G / rho_gas is only its standard-density equivalent, for reading.

SILICONE FILM AT THE EXIT (2026-10-13, orifice.py): from G and the camera-window upstream pressure P0, the gas
share of the orifice area alpha = G / G_gas(P0) (G_gas = Cd x the ideal gas-only flux; Cd from
orifice_cd.json, 1.0 until measured), the silicone speed u_L = Q_L / ((1 - alpha) A) and, for an annular exit,
the film thickness h = (d/2)(1 - sqrt(alpha)). Only with a camera window (P0 and G from the same 13 s). Also a
covariate, not a factor. On the CCD day the film ordered atomised fraction best of all (Spearman -0.90 over
the 31 spraying runs; C7/C8 had the thinnest film, ~126 um).

NO-SPRAY RUNS (stats.no_spray_reason) are left out of every covariate trend FIT and kept as Trend.excluded
for plotting: the CCD day's two dribbles (G 3-5 kg/m2/s) set most of the flux exponent.

ORIFICE LENGTH: 'Orifice length (mm)' in run_summary.xlsx (GUI_Clean from 2026-10-13; no earlier run
has it). L/D is reported alongside, and orifice_length_warning() flags an analysis whose runs used
different lengths: it is not a factor, so its effect would be mixed into the others.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

from . import orifice
from . import paths
from . import run_discovery as rd

LIQ_DENSITY = "Liquid density (kg/m3)"
GAS_DENSITY = "Gas density (kg/m3)"
COVARIATES = (("glr", "GLR (set points)"), ("glr_achieved", "GLR (achieved gas flow)"),
              ("gas_flux", "Gas mass flux at the orifice, delivered (kg/m2/s)"),
              ("l_over_d", "Orifice length / diameter"),
              ("film_um", "Silicone film thickness at the exit, annular estimate (um)"))
GLR_KEYS = ("glr", "glr_achieved")
FLUX_KEYS = ("gas_flux", "l_over_d")
FILM_KEYS = ("film_um",)
CAVEAT = ("GLR is computed from the gas flow and the liquid (silicone) flow, so it is not "
          "independent of the factors: a strong relationship with GLR reflects those factors and "
          "cannot be separated from them. It describes the trend; it is not an extra factor.")
FLUX_CAVEAT = ("The gas mass flux is made from the gas flow and the orifice, so it is aliased with "
               "them: a trend with it describes those factors together and cannot be separated from "
               "them. It is a covariate, not an extra factor; the set points stay the factors.")
CAMERA, ACHIEVED, SET_POINT = "camera window", "achieved (flow range)", "set point"
SCCM_M3S = 1e-6 / 60           # 1 sccm = 1 cm3/min at standard conditions
LENGTH_TOL_MM = 0.05           # orifice lengths closer than this are the same insert


_GUI_FORMULA_ERROR: str | None = None


def _gui_formula():
    """The capture GUI's GLR function, or None if it cannot be imported (the reason is kept
    for formula_problem())."""
    global _GUI_FORMULA_ERROR
    try:
        paths.ensure_src_on_path()
        from gui.GUI_Clean import AtomisationApp
        _GUI_FORMULA_ERROR = None
        return AtomisationApp._glr_working
    except Exception as exc:                                # noqa: BLE001 -- reported, not hidden
        _GUI_FORMULA_ERROR = f"{type(exc).__name__}: {exc}"
        return None


def formula_problem() -> str | None:
    """Why the capture GUI's GLR / mL/min formula cannot be used here, or None if it can.
    Without it there is no liquid mL/min, so no atomised liquid flow (Taguchi app bug 6,
    2026-10-13: it vanished silently on the home PC's Python 3.9)."""
    if _gui_formula() is None:
        return _GUI_FORMULA_ERROR or "unknown import failure"
    return None


def glr_working(sccm: float, steps_per_s: float, rho_liquid: float, rho_gas: float) -> dict | None:
    """Every intermediate of the GLR, from the GUI's own code."""
    fn = _gui_formula()
    if fn is None or None in (sccm, steps_per_s, rho_liquid, rho_gas):
        return None
    fake = SimpleNamespace(_densities=lambda: (rho_liquid, rho_gas),
                           _flow_entry=SimpleNamespace(text=lambda: str(sccm)),
                           _speed_entry=SimpleNamespace(text=lambda: str(steps_per_s)))
    try:
        return fn(fake)
    except Exception:
        return None


@dataclass
class RunContext:
    glr: float | None = None
    glr_source: str = "missing"              # recorded | computed | missing
    glr_achieved: float | None = None
    liquid_ml_min: float | None = None
    fluid: str = ""
    gas: str = ""
    rho_liquid: float | None = None
    rho_gas: float | None = None
    achieved_sccm: float | None = None
    peak_pressure_bar: float | None = None
    note: str = ""
    orifice_mm: float | None = None
    orifice_length_mm: float | None = None   # None when not recorded (every run before 2026-10-13)
    l_over_d: float | None = None
    flux_sccm: float | None = None           # the gas the flux is built from (standard cm3/min)
    gas_flux: float | None = None            # kg/m2/s, delivered gas mass flow / orifice area
    gas_flux_source: str = "missing"         # camera window | achieved (flow range) | set point | missing
    exit_velocity_std: float | None = None   # m/s, gas_flux / rho_gas: the flux at standard density
    flux_note: str = ""
    # the orifice split (orifice.py): only with a camera window, where P0 and the gas are from the same 13 s
    p0_bar: float | None = None              # camera-window upstream pressure, barA
    gas_model: str = ""                      # air | nitrogen | co2 (from the 'Gas' tag)
    cd: float | None = None
    cd_source: str = ""                      # 'ideal (not measured)' | 'measured <date>'
    gas_only_flux: float | None = None       # Cd x ideal gas-only flux at P0, kg/m2/s
    choked: bool | None = None
    gas_share: float | None = None           # alpha = gas_flux / gas_only_flux, clipped to [0, 1]
    u_liquid_m_s: float | None = None        # silicone speed in the orifice
    film_um: float | None = None             # annular film thickness at the exit
    film_note: str = ""


def gas_flux(sccm: float | None, orifice_mm: float | None, rho_gas: float | None) -> tuple:
    """(G kg/m2/s, exit velocity at standard density m/s) for `sccm` through a round orifice; G is None
    without a gas density, both None without a flow or an orifice."""
    if sccm is None or not orifice_mm or orifice_mm <= 0 or not math.isfinite(sccm) or sccm < 0:
        return None, None
    v = sccm * SCCM_M3S / (math.pi * (orifice_mm / 1e3) ** 2 / 4)
    return (v * rho_gas if rho_gas else None), v


def _set_flux(ctx: RunContext, sccm: float | None, source: str) -> None:
    ctx.flux_sccm = sccm
    ctx.gas_flux, ctx.exit_velocity_std = gas_flux(sccm, ctx.orifice_mm, ctx.rho_gas)
    ctx.gas_flux_source = source if ctx.exit_velocity_std is not None else "missing"
    ctx.flux_note = ("" if ctx.gas_flux is not None else
                     "no orifice in the folder name or run_summary.xlsx" if not ctx.orifice_mm else
                     "no gas flow" if sccm is None else
                     "no gas density recorded: no flux (not guessed)")


def _set_film(ctx: RunContext, p0_bar: float | None) -> None:
    """The orifice split (orifice.py) from the camera-window flux and P0."""
    ctx.p0_bar = p0_bar
    name, gamma, R, gas_note = orifice.gas_properties(ctx.gas)
    ctx.gas_model = name
    ctx.cd, ctx.cd_source = orifice.lookup_cd(ctx.orifice_mm, ctx.orifice_length_mm)
    if ctx.gas_flux is None or p0_bar is None:
        ctx.film_note = ("no gas flux" if ctx.gas_flux is None else "no upstream pressure in the camera window")
        return
    ideal, ctx.choked = orifice.gas_only_flux(p0_bar, gamma, R)
    ctx.gas_only_flux = ctx.cd * ideal
    q = ctx.liquid_ml_min * 1e-6 / 60 if ctx.liquid_ml_min is not None else None
    sp = orifice.split(ctx.gas_flux, ctx.gas_only_flux, ctx.orifice_mm, q)
    ctx.gas_share, ctx.film_um, ctx.u_liquid_m_s = sp.gas_share, sp.film_um, sp.u_liquid_m_s
    ctx.film_note = "; ".join(x for x in (sp.note, gas_note) if x)


def with_operating(ctx: RunContext | None, op) -> RunContext | None:
    """Rebuild the flux from the gas the run got in the camera window (operating.OperatingPoint), when its
    pressure log has one, and the orifice split from the same window's P0; otherwise the flux stays on the
    achieved flow or the set point and there is no split."""
    if ctx is not None and op is not None and op.delivered_sccm is not None:
        _set_flux(ctx, op.delivered_sccm, CAMERA)
        _set_film(ctx, op.p0_bar)
    elif ctx is not None:
        ctx.film_note = "no camera window in the pressure log"
    return ctx


def run_context(info: rd.RunInfo) -> RunContext:
    m = info.meta
    num = lambda k: (m[k].pick("max") if k in m and not m[k].missing else None)
    ctx = RunContext(fluid=m["Fluid"].text if "Fluid" in m else "",
                     gas=m["Gas"].text if "Gas" in m else "",
                     rho_liquid=num(LIQ_DENSITY), rho_gas=num(GAS_DENSITY),
                     achieved_sccm=info.flow_achieved_sccm,
                     peak_pressure_bar=num("Pressure Range (barA)"),
                     orifice_mm=getattr(info, "orifice_mm", None),
                     orifice_length_mm=getattr(info, "orifice_length_mm", None))
    if ctx.orifice_mm and ctx.orifice_length_mm:
        ctx.l_over_d = ctx.orifice_length_mm / ctx.orifice_mm
    if ctx.achieved_sccm:
        _set_flux(ctx, ctx.achieved_sccm, ACHIEVED)
    else:
        _set_flux(ctx, getattr(info, "sccm", None), SET_POINT)
    have_densities = ctx.rho_liquid is not None and ctx.rho_gas is not None
    w = glr_working(info.sccm, info.sps, ctx.rho_liquid, ctx.rho_gas) if have_densities else None
    if w:
        ctx.liquid_ml_min = w["ml_per_min"]
    recorded = num("GLR")
    if recorded is not None:
        ctx.glr, ctx.glr_source = recorded, "recorded"
    elif w:
        ctx.glr, ctx.glr_source = w["glr"], "computed"
    else:
        ctx.note = ("no GLR in run_summary.xlsx and no densities to compute one"
                    if not have_densities else "GLR could not be computed from the workbook")
    if have_densities and ctx.achieved_sccm:
        wa = glr_working(ctx.achieved_sccm, info.sps, ctx.rho_liquid, ctx.rho_gas)
        ctx.glr_achieved = wa["glr"] if wa else None
    return ctx


# ---- relationship of a response to a covariate (GLR, gas flux, L/D) ----------------------------------------

@dataclass
class Trend:
    response: str
    covariate: str
    n: int
    r: float | None = None                   # Pearson correlation, response vs covariate
    p: float | None = None                   # H0: r = 0 (t test, n-2 df)
    exponent: float | None = None            # power law: response ~ a * covariate^b  (log-log fit)
    exponent_ci95: tuple | None = None
    r2_power: float | None = None
    note: str = ""
    points: list = field(default_factory=list)   # (covariate, response, condition) for plotting
    excluded: list = field(default_factory=list)  # the same for no-spray runs: plotted, not fitted


def _t_ppf975(df: int) -> float | None:
    try:
        from scipy.stats import t
        return float(t.ppf(0.975, df))
    except Exception:
        return None


def trend(response: str, covariate: str, xs: list, ys: list, conds: list) -> Trend:
    from .stats import f_sf
    pts = [(float(x), float(y), c) for x, y, c in zip(xs, ys, conds)
           if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    t = Trend(response, covariate, len(pts), points=pts)
    if len(pts) < 3:
        t.note = "fewer than 3 runs with both values"
        return t
    x = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        t.note = "no spread in one of the two"
        return t
    r = float(np.corrcoef(x, y)[0, 1])
    t.r = r
    dfree = len(pts) - 2
    if abs(r) < 1:
        F = r * r * dfree / (1 - r * r)          # t^2 with (1, n-2) df
        t.p = f_sf(F, 1, dfree)
    else:
        t.p = 0.0
    if np.all(x > 0) and np.all(y > 0):
        lx, ly = np.log(x), np.log(y)
        b, a = np.polyfit(lx, ly, 1)
        pred = a + b * lx
        ss_res = float(((ly - pred) ** 2).sum())
        ss_tot = float(((ly - ly.mean()) ** 2).sum())
        t.exponent = float(b)
        t.r2_power = 1 - ss_res / ss_tot if ss_tot > 0 else None
        sxx = float(((lx - lx.mean()) ** 2).sum())
        tc = _t_ppf975(dfree)
        if tc is not None and sxx > 0 and dfree > 0:
            se = math.sqrt(ss_res / dfree / sxx)
            t.exponent_ci95 = (float(b - tc * se), float(b + tc * se))
    else:
        t.note = "power law not fitted: some values are zero or negative"
    return t


def _length_text(v: float) -> str:
    return f"{v:.1f}" if abs(v * 10 - round(v * 10)) < 1e-6 else f"{v:.2f}"


def orifice_length_groups(contexts) -> list[tuple[float, int]]:
    """[(length mm, runs)] of the recorded orifice lengths, lengths within LENGTH_TOL_MM of a group's
    shortest counted as one (the median is reported)."""
    vals = sorted(c.orifice_length_mm for c in contexts if c is not None and c.orifice_length_mm is not None)
    groups: list[list[float]] = []
    for v in vals:
        if groups and v - groups[-1][0] <= LENGTH_TOL_MM:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [(float(np.median(g)), len(g)) for g in groups]


def orifice_length_warning(contexts) -> str | None:
    """A loud warning when the runs of one analysis used different orifice LENGTHS (not a factor, so its
    effect is mixed into the others), or when only some runs record it; None when all agree or none
    records it (the report says it is not recorded)."""
    contexts = list(contexts)
    groups = orifice_length_groups(contexts)
    if not groups:
        return None
    unrecorded = len(contexts) - sum(n for _, n in groups)
    if len(groups) > 1:
        return ("ORIFICE LENGTH DIFFERS BETWEEN RUNS ("
                + ", ".join(f"{_length_text(v)} mm in {n}" for v, n in groups)
                + (f"; not recorded in {unrecorded}" if unrecorded else "") + "): it is not a factor in this "
                "model, so its effect is mixed into the others.")
    if unrecorded:
        return (f"orifice length is recorded for only {len(contexts) - unrecorded} of {len(contexts)} runs "
                f"({_length_text(groups[0][0])} mm); the other {unrecorded} do not record it, so a change between "
                "runs cannot be ruled out: it is not a factor in this model, so any effect of it is mixed into "
                "the others.")
    return None


def trends(runs, responses, covariate_keys=tuple(k for k, _ in COVARIATES)) -> dict:
    """{(response key, covariate key): Trend} for analysed runs (stats.RunRecord with
    .context set). No-spray runs (rec['no_spray']) are left out of the fit and kept in Trend.excluded."""
    out = {}
    fit = [r for r in runs if not (r.rec or {}).get("no_spray")]
    dribble = [r for r in runs if (r.rec or {}).get("no_spray")]
    x_of = lambda r, ck: getattr(r.context, ck, None) if r.context else None
    for key, _label, _dir, _q in responses:
        for ck in covariate_keys:
            t = trend(key, ck, [x_of(r, ck) for r in fit], [r.values.get(key) for r in fit],
                      [r.condition for r in fit])
            t.excluded = [(float(x_of(r, ck)), float(r.values[key]), r.condition) for r in dribble
                          if x_of(r, ck) is not None and r.values.get(key) is not None
                          and math.isfinite(x_of(r, ck)) and math.isfinite(r.values[key])]
            if t.excluded:
                t.note = "; ".join(x for x in (t.note, f"{len(t.excluded)} no-spray run(s) plotted, not fitted")
                                   if x)
            out[(key, ck)] = t
    return out
