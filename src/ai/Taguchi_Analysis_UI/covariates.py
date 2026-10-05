"""covariates.py -- GLR (and the run context it comes from), and how each response
relates to it. No Qt in here.

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
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

from . import paths
from . import run_discovery as rd

LIQ_DENSITY = "Liquid density (kg/m3)"
GAS_DENSITY = "Gas density (kg/m3)"
COVARIATES = (("glr", "GLR (set points)"), ("glr_achieved", "GLR (achieved gas flow)"))
CAVEAT = ("GLR is computed from the gas flow and the liquid (silicone) flow, so it is not "
          "independent of the factors: a strong relationship with GLR reflects those factors and "
          "cannot be separated from them. It describes the trend; it is not an extra factor.")


def _gui_formula():
    """The capture GUI's GLR function, or None if it cannot be imported."""
    try:
        paths.ensure_src_on_path()
        from gui.GUI_Clean import AtomisationApp
        return AtomisationApp._glr_working
    except Exception:
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


def run_context(info: rd.RunInfo) -> RunContext:
    m = info.meta
    num = lambda k: (m[k].pick("max") if k in m and not m[k].missing else None)
    ctx = RunContext(fluid=m["Fluid"].text if "Fluid" in m else "",
                     gas=m["Gas"].text if "Gas" in m else "",
                     rho_liquid=num(LIQ_DENSITY), rho_gas=num(GAS_DENSITY),
                     achieved_sccm=info.flow_achieved_sccm,
                     peak_pressure_bar=num("Pressure Range (barA)"))
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


# ---- relationship of a response to GLR ---------------------------------------------------------

@dataclass
class Trend:
    response: str
    covariate: str
    n: int
    r: float | None = None                   # Pearson correlation, response vs covariate
    p: float | None = None                   # H0: r = 0 (t test, n-2 df)
    exponent: float | None = None            # power law: response ~ a * GLR^b  (log-log fit)
    exponent_ci95: tuple | None = None
    r2_power: float | None = None
    note: str = ""
    points: list = field(default_factory=list)   # (covariate, response, condition) for plotting


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


def trends(runs, responses, covariate_keys=("glr", "glr_achieved")) -> dict:
    """{(response key, covariate key): Trend} for analysed runs (stats.RunRecord with
    .context set)."""
    out = {}
    for key, _label, _dir, _q in responses:
        for ck in covariate_keys:
            xs = [getattr(r.context, ck, None) if r.context else None for r in runs]
            ys = [r.values.get(key) for r in runs]
            out[(key, ck)] = trend(key, ck, xs, ys, [r.condition for r in runs])
    return out
