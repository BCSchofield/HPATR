"""rsm_recommend.py -- what to run next, from a fitted response surface. No Qt.

Given the primary model of an analysis (rsm_responses.RsmResults), proposes the runs for the next
session, choosing what applies and saying why:

    confirm     confirmation runs at the best setting (snapped to what can be set: the rig's steps,
                the levels that exist, the rig's limits), with one anchor repeat of the design centre
                to link the sessions. Always offered when there is a best setting.
    steepest    when the best setting is on an edge of the region, or the goal surfaces do not curve
                (the best point is outside): runs stepping outward along the path of steepest ascent
                of the desirability, from the best setting, stopping at the rig's limits.
    new_ccd     same trigger: a new face-centred CCD centred on the best setting (edge factors shifted
                so the best point sits inside), built by rsm_design and inside the rig's limits.
    augment     when the model is weak (lack of fit, a goal surface that cannot predict new runs, terms
                that could not be estimated, a failed check / validation run): D-optimal points from a
                grid of settings that can be run, each the one that most reduces the model's
                prediction variance, starting next to a failed run when there is one.
    new_level   a new level of a factor that comes in fixed sizes (an orifice insert) when the CCD plan's
                three conditions all hold: the best point is at that factor's edge; the factor's slope
                is still significant there for a goal; and the check run (e.g. 0.8 mm) matches the
                model. Proposes the next size by the same ratio as the existing step.

Every proposed run carries its predicted responses with the 95% prediction interval, flagged when it is
outside the fitted region (extrapolation: the interval is the model's, the risk is larger).
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import fsops
from . import rsm_design as rb
from . import rsm_detect as rdet
from . import rsm_responses as rr
from . import rsm_stats as rs
from .stats import f_sf

SETPOINT_STEP = {"sccm": 100, "sps": 100, "rpm": 50, "bh": 0.1}      # the rig's setpoint resolution
PREDICT_KEYS = ("atom", "d32", "af_flow", "cv_droplets", "peak_bar")
STEEPEST_STEP = 0.5                     # coded units per step along the path of steepest ascent
CURVE_ALPHA = 0.05
EXPORT_STEM = "next_runs"


@dataclass
class RecRow:
    values: dict                        # factor key -> setting to type into the rig
    label: str                          # "Confirmation", "Anchor (design centre)", "Step 2 of 4", ...
    preds: dict = field(default_factory=dict)   # response key -> (mean, PI low, PI high)
    extrapolated: bool = False


@dataclass
class Recommendation:
    kind: str                           # confirm | steepest | new_ccd | augment | new_level
    title: str
    why: str
    rows: list[RecRow] = field(default_factory=list)
    plan: rb.Plan | None = None         # new_ccd: the plan handed to the builder
    sheet: rb.Sheet | None = None


# ---- helpers ----------------------------------------------------------------------------------------

def _f(R, k) -> rdet.FactorLevels:
    return next(f for f in R.loaded.detected.factors if f.key == k)


def _model_keys(R) -> list[str]:
    return list(R.axis) + list(R.nuisance)


def snap(R, k: str, v: float, discrete: dict | None = None) -> float:
    """A setting the rig can take: the nearest existing level for a fixed-size factor, else rounded to
    the setpoint step; always inside the rig's limits."""
    if discrete and k in discrete:
        return min(discrete[k], key=lambda d: abs(d - v))
    step = SETPOINT_STEP.get(k)
    v = round(v / step) * step if step else round(v, 4)
    lo, hi = rb.RIG_LIMITS.get(k, (-math.inf, math.inf))
    v = min(max(v, lo), hi)
    return int(v) if float(v).is_integer() else v


def predict_row(R, values: dict) -> tuple[dict, bool]:
    """Predictions (mean, PI) at a real setting, and whether it is outside the fitted region."""
    x = {k: np.array([_f(R, k).real_code(values[k])]) for k in _model_keys(R)}
    if "time" in R.terms:
        x["time"] = np.array([0.0])
    preds = {}
    for key in PREDICT_KEYS + tuple(g.key for g in R.goals):
        fr = R.fits.get(key)
        if fr is None or fr.reduced is None or key in preds:
            continue
        p = fr.reduced.predict(x)
        preds[key] = (float(p["mean"][0]), float(p["pi"][0][0]), float(p["pi"][1][0]))
    ext = any(abs(_f(R, k).design_code(values[k]) or 0) > 1 + 1e-6 for k in _model_keys(R))
    return preds, ext


def pressure_check(R, preds: dict) -> str:
    """A warning when a proposed run's predicted peak pressure reaches the supply ceiling: there the rig
    becomes pressure-limited and the gas set point is no longer what the run gets (operating.py)."""
    from .operating import NEAR_CEILING_BAR
    opts = getattr(R.loaded, "opts", None)
    if "peak_bar" not in preds or opts is None:
        return ""
    m = preds["peak_bar"][0]
    ceiling = opts.supply_ceiling_bar
    if m >= ceiling - NEAR_CEILING_BAR:
        return (f"⚠ predicted peak {m:.1f} barA, at the {ceiling:g} barA supply ceiling: likely pressure-limited "
                "(the gas may not reach its set point)")
    return ""


def _row(R, values: dict, label: str) -> RecRow:
    preds, ext = predict_row(R, values)
    return RecRow(values, label, preds, ext)


def best_hold(R) -> tuple[dict, object] | tuple[None, None]:
    """(nuisance hold, optimum) where the combined score is highest: with no nuisance factor, the
    settable optimum if there is one, else the continuous one."""
    if R.nuisance:
        from .rsm_report import optimum_by_hold
        best = max(optimum_by_hold(R), key=lambda ho: ho[1].D, default=None)
        return best if best is not None else (None, None)
    o = R.optimum_discrete or R.optimum
    return ({}, o) if o is not None else (None, None)


def _best_values(R, o, discrete, hold: dict | None = None) -> dict:
    vals = {k: snap(R, k, R.decode(k, o.coded[k]), discrete) for k in R.axis}
    for k in R.nuisance:
        f = _f(R, k)
        if hold and k in hold:
            vals[k] = hold[k]
        else:
            vals[k] = snap(R, k, f.decode(R.hold.get(k, 0.0)), None)
    return vals


def beyond_tested(R, values: dict) -> list[str]:
    """Factors set beyond the tested range with no known rig limit there: to be checked on the rig."""
    out = []
    for k, v in values.items():
        f = _f(R, k)
        lo, hi = float(f.low), float(f.high)
        rlo, rhi = rb.RIG_LIMITS.get(k, (None, None))
        if (v > hi and rhi is None) or (v < lo and rlo is None):
            out.append(f"{f.label} {v:g}")
    return out


def _goal_fits(R) -> dict:
    return {g.key: R.fits[g.key].reduced for g in R.goals if g.key in R.fits and R.fits[g.key].reduced is not None}


def _desirability_at(R, coded: dict) -> float:
    fits = _goal_fits(R)
    x = {k: np.array([v]) for k, v in coded.items()}
    for k, v in R.hold.items():
        x.setdefault(k, np.array([v]))
    if "time" in R.terms:
        x["time"] = np.array([0.0])
    preds = {k: f.predict(x)["mean"] for k, f in fits.items()}
    return float(rs.desirability(preds, R.goals, R.constraints)[0]) if preds else 0.0


def _curves(R) -> bool:
    """Does any goal surface curve significantly in an axis factor (a square term with p < alpha)?"""
    for g in R.goals:
        fr = R.fits.get(g.key)
        if fr is None or fr.full is None:
            continue
        for k in R.axis:
            t = f"{k}^2"
            if t in fr.full.terms and fr.full.p_of[t] < CURVE_ALPHA:
                return True
    return False


def slope_at(f: rs.Fit, k: str, coded: dict) -> tuple[float, float | None]:
    """d(prediction)/d(factor k) at a coded point, with its p (t-test on the linear combination)."""
    terms = f.terms
    c = np.zeros(len(terms))
    for i, t in enumerate(terms):
        p = rs.term_parents(t)
        if p == (k,):
            c[i] = 1.0
        elif p == (k, k):
            c[i] = 2 * coded.get(k, 0.0)
        elif len(p) == 2 and k in p:
            other = p[1] if p[0] == k else p[0]
            c[i] = coded.get(other, 0.0)
    g = float(c @ f.beta)
    if not f.s or f.df_resid <= 0:
        return g, None
    se = f.s * math.sqrt(max(float(c @ f.xtx_inv @ c), 0.0))
    return g, (f_sf((g / se) ** 2, 1, f.df_resid) if se > 0 else 0.0)


# ---- the recommendations ------------------------------------------------------------------------------

def confirm(R, discrete: dict | None, n: int = 3) -> Recommendation | None:
    hold, o = best_hold(R)
    if o is None:
        return None
    if R.nuisance and R.optimum_discrete is not None:
        o = R.optimum_discrete
    best = _best_values(R, o, discrete, hold)
    rows = [_row(R, best, f"Confirmation {i + 1} of {n}") for i in range(n)]
    centre = {k: snap(R, k, float(_f(R, k).centre), discrete) for k in _model_keys(R)}
    rows.append(_row(R, centre, "Anchor: design centre (links the sessions)"))
    where = ", ".join(f"{_f(R, k).label} {best[k]:g}" for k in R.axis) + \
        "".join(f", {_f(R, k).label} {best[k]:g} (kept in the model, set where the score is highest)" for k in R.nuisance)
    return Recommendation("confirm", "Confirm the best setting",
                          f"The best overall setting (desirability {o.D:.2f}) is {where}. Running it {n} times in a "
                          f"later session, mixed with a repeat of the design centre, checks that the surface "
                          f"predicts a session it was not fitted to, and the centre repeat measures any day-to-day "
                          f"offset. Each prediction's 95% interval is where the run should land.", rows)


def _outward(R, o) -> np.ndarray:
    """Gradient of the desirability at the optimum (coded axis factors), by central differences."""
    h = 0.02
    g = np.zeros(len(R.axis))
    for i, k in enumerate(R.axis):
        up = dict(o.coded)
        dn = dict(o.coded)
        up[k] += h
        dn[k] -= h
        g[i] = (_desirability_at(R, up) - _desirability_at(R, dn)) / (2 * h)
    return g


def steepest(R, discrete: dict | None, steps: int = 4) -> Recommendation | None:
    hold, o = best_hold(R)
    if not R.nuisance:
        o = R.optimum
    if o is None:
        return None
    edge = list(o.on_edge)
    flat = not _curves(R)
    if not edge and not flat:
        return None
    g = _outward(R, o)
    # only the factors whose push goes OUT of the region (edge factors pressing outward); fixed-size
    # factors stay where they are (a new size is the new_level recommendation)
    d = np.zeros(len(R.axis))
    for i, k in enumerate(R.axis):
        if discrete and k in discrete:
            continue
        at = o.coded[k]
        if (k in edge and np.sign(g[i]) == np.sign(at)) or (flat and not edge):
            d[i] = g[i]
    if not np.any(d):
        return None
    d = d / np.linalg.norm(d)
    rows = []
    for s in range(1, steps + 1):
        coded = {k: o.coded[k] + s * STEEPEST_STEP * d[i] for i, k in enumerate(R.axis)}
        vals = {k: snap(R, k, R.decode(k, coded[k]), discrete) for k in R.axis}
        for k in R.nuisance:
            vals[k] = _best_values(R, o, discrete, hold)[k]
        lo_hit = [k for k in R.axis if k in rb.RIG_LIMITS and vals[k] in rb.RIG_LIMITS[k]]
        rows.append(_row(R, vals, f"Step {s} of {steps}" + (" (at the rig's limit)" if lo_hit else "")))
        if lo_hit:
            break
    moving = ", ".join(f"{_f(R, k).label} {'up' if d[i] > 0 else 'down'}" for i, k in enumerate(R.axis) if d[i])
    unknown = sorted({b for r in rows for b in beyond_tested(R, r.values)})
    check = (" Check the rig can run " + ", ".join(unknown) + ": beyond the tested range, with no recorded limit."
             if unknown else "")
    why = ((f"The best setting is on the edge of the tested region ({', '.join(_f(R, k).label for k in edge)}), so "
            if edge else "No goal surface curves inside the region, so ")
           + f"the best point is likely outside it. These runs step from the best setting along the direction the "
             f"combined score rises fastest ({moving}), {STEEPEST_STEP:g} of a half-range per step. They are "
             f"outside what was fitted: the predictions are the model's extrapolation, a guide, not a promise."
           + check)
    return Recommendation("steepest", "Move the region: path of steepest ascent", why, rows)


def new_ccd(R, discrete: dict | None, centres: int = 5) -> Recommendation | None:
    hold, o = best_hold(R)
    if not R.nuisance:
        o = R.optimum
    if o is None or (not o.on_edge and _curves(R)):
        return None
    det = R.loaded.detected
    factors = []
    for k in R.axis:
        f = _f(R, k)
        lo, mid, hi = float(f.low), float(f.centre), float(f.high)
        half_lo, half_hi = mid - lo, hi - mid
        if discrete and k in discrete:
            factors.append(rb.FactorSpec(k, f.label, lo, mid, hi))
            continue
        best = R.decode(k, o.coded[k])
        if k in o.on_edge:                     # centre the new region on the edge the optimum pressed against
            new_mid = best
        else:
            new_mid = mid + (best - mid) * 0.5  # move half way towards the optimum
        new_mid = snap(R, k, new_mid, None)
        nlo, nhi = new_mid - half_lo, new_mid + half_hi
        rlo, rhi = rb.RIG_LIMITS.get(k, (-math.inf, math.inf))
        if nhi > rhi:                          # keep the whole region inside the rig's limits
            shift = nhi - rhi
            nlo, new_mid, nhi = nlo - shift, new_mid - shift, rhi
        if nlo < rlo:
            shift = rlo - nlo
            nlo, new_mid, nhi = rlo, new_mid + shift, nhi + shift
        factors.append(rb.FactorSpec(k, f.label, snap(R, k, nlo, None), snap(R, k, new_mid, None),
                                     snap(R, k, nhi, None)))
    block = det.blocks.block_factor if det.blocks.block_factor in R.axis else None
    plan = rb.Plan(factors=factors, centres=centres, block_factor=block)
    try:
        sheet = rb.build_sheet(plan)
    except rb.PlanError as exc:
        return Recommendation("new_ccd", "Move the region: a new CCD", f"A new CCD could not be built: {exc}.")
    moved = [f"{fs.label} {_f(R, fs.key).low:g}-{_f(R, fs.key).high:g} -> {fs.low:g}-{fs.high:g}"
             for fs in factors if (fs.low, fs.high) != (float(_f(R, fs.key).low), float(_f(R, fs.key).high))]
    why = ("A face-centred CCD around the best setting, same size as this one, shifted so the best point sits inside "
           f"it: {'; '.join(moved) or 'no factor needed moving'}. {len(sheet.rows)} runs. Built by the run-sheet "
           f"builder (rig limits applied); the rows are its sheet.")
    held = {k: (hold or {}).get(k, _f(R, k).centre) for k in R.nuisance}
    if held:
        why += " Held for the whole design: " + ", ".join(f"{_f(R, k).label} {v:g}" for k, v in held.items()) + \
               " (where the combined score was highest)."
    unknown = sorted({b for fs in factors for b in beyond_tested(R, {fs.key: fs.high}) + beyond_tested(R, {fs.key: fs.low})})
    if unknown:
        why += " Check the rig can run " + ", ".join(unknown) + ": beyond the tested range, with no recorded limit."
    rows = [RecRow(dict(r.values, **held), r.label) for r in sheet.rows]
    return Recommendation("new_ccd", "Move the region: a new CCD around the best setting", why, rows, plan, sheet)


def _held_back(R, discrete: dict | None) -> dict:
    """Settable sizes of a fixed-size factor outside the FITTED span (factor key -> sizes). They are not
    offered as runs to strengthen the model: a prediction there is an extrapolation, so its variance is
    large only because it is far away (on the CCD day, 0.5 mm on the ln scale fitted to 1.2-1.8 mm codes
    to -4.3 and would win every pick), and the runs there may not be flow-controlled at all."""
    out = {}
    for k, sizes in (discrete or {}).items():
        if k not in _model_keys(R):
            continue
        f = _f(R, k)
        far = [v for v in sizes if f.real_code(v) is not None and abs(f.real_code(v)) > 1 + rr.EXTRAPOLATION_TOL]
        if far and len(far) < len(sizes):
            out[k] = far
    return out


def _held_back_text(R, held: dict) -> str:
    """'Orifice 0.5, 0.8 are outside the fitted span (1.2 to 1.8) and not offered: at 0.5 all 10 runs were
    pressure-limited; 0.8 ran flow-controlled (151407)'."""
    bits = []
    for k, sizes in held.items():
        f = _f(R, k)
        why = []
        for v in sizes:
            at = [r for r in R.loaded.runs if r.point.values.get(k) is not None
                  and math.isclose(float(r.point.values[k]), v, rel_tol=1e-6)]
            lim = [r for r in at if r.op is not None and getattr(r.op, "not_delivered", False)]
            if at and len(lim) == len(at):
                why.append(f"at {v:g} all {len(at)} runs were pressure-limited")
            elif at:
                why.append(f"{v:g} ran {'flow-controlled' if not lim else 'partly flow-controlled'} ("
                           + ", ".join(r.point.name[:6] for r in at if r not in lim) + ")")
        bits.append(f"{f.label.split(' (')[0]} {', '.join(f'{v:g}' for v in sizes)} "
                    f"{'is' if len(sizes) == 1 else 'are'} outside the fitted span ({float(f.low):g} to "
                    f"{float(f.high):g}) and not offered" + (": " + "; ".join(why) if why else ""))
    return ". ".join(bits)


def _candidates(R, discrete: dict | None) -> list[dict]:
    """Settings that can be run, inside the region: 5 levels per continuous factor (the design levels and
    the midpoints), the existing levels of fixed-size factors inside the fitted span (_held_back);
    nuisance factors at their levels."""
    axes = {}
    held = _held_back(R, discrete)
    for k in _model_keys(R):
        f = _f(R, k)
        if discrete and k in discrete:
            axes[k] = [v for v in discrete[k] if v not in held.get(k, [])]
        elif k in R.nuisance:
            axes[k] = list(f.levels)
        else:
            lo, mid, hi = float(f.low), float(f.centre), float(f.high)
            axes[k] = sorted({snap(R, k, v, None) for v in (lo, (lo + mid) / 2, mid, (mid + hi) / 2, hi)})
    import itertools
    keys = list(axes)
    return [dict(zip(keys, combo)) for combo in itertools.product(*[axes[k] for k in keys])]


def augment(R, discrete: dict | None, n: int = 4) -> Recommendation | None:
    reasons = []
    for g in R.goals:
        fr = R.fits.get(g.key)
        if fr is None or fr.full is None:
            continue
        lof = fr.full.lof
        if lof is not None and lof.p is not None and lof.p < 0.05:
            reasons.append(f"lack of fit on {fr.label} (p = {lof.p:.2g})")
    weak = [w for w in R.warnings if w.startswith("left out of the best-settings search")]
    if weak:
        reasons.append("goal surfaces that cannot predict new runs")
    if R.dropped_terms:
        reasons.append("terms that could not be estimated (" + ", ".join(R.dropped_terms) + ")")
    failed = []
    for g in R.goals:
        fr = R.fits.get(g.key)
        for p in (fr.predictions if fr else []):
            if p.inside is False and not p.extrapolated and p.run not in failed:
                failed.append(p.run)
    if failed:
        reasons.append("a run outside the fit that missed its prediction (" +
                       ", ".join(r.point.name[:6] for r in failed) + ")")
    if not reasons:
        return None
    # D-optimal augmentation of the CURRENT design on the model's terms: each pick maximises x' M^-1 x
    terms = list(R.terms)
    fit_runs = [r for r in R.loaded.runs if r.point.in_fit]
    keys = _model_keys(R)
    X = rs.model_matrix({k: np.array([r.point.real[k] for r in fit_runs]) for k in keys} |
                        ({"time": np.zeros(len(fit_runs))} if "time" in terms else {}), terms)
    with np.errstate(all="ignore"):            # Accelerate BLAS false alarms on finite inputs
        M = X.T @ X
    cands = _candidates(R, discrete)
    for c in R.constraints:                    # a hard limit on a response excludes settings predicted over it
        cands = [v for v in cands if c.ok([predict_row(R, v)[0].get(c.key, (0,))[0]])[0]]
    C = rs.model_matrix({k: np.array([_f(R, k).real_code(v[k]) for v in cands]) for k in keys} |
                        ({"time": np.zeros(len(cands))} if "time" in terms else {}), terms)
    rows = []
    chosen = []
    if failed:                                 # first: the runnable setting nearest the failed run
        r0 = failed[0]
        dist = [sum((_f(R, k).real_code(v[k]) - r0.point.real[k]) ** 2 for k in keys) for v in cands]
        i0 = int(np.argmin(dist))
        chosen.append(i0)
        rows.append(_row(R, cands[i0], f"Next to {r0.point.name[:6]}, which missed its prediction"))
        M = M + np.outer(C[i0], C[i0])
    while len(chosen) < n:
        with np.errstate(all="ignore"):
            Minv = np.linalg.pinv(M)
            lev = np.einsum("ij,jk,ik->i", C, Minv, C)
        lev[chosen] = -np.inf
        i = int(np.argmax(lev))
        chosen.append(i)
        rows.append(_row(R, cands[i], f"Strengthen the model (prediction variance {lev[i]:.2f} before)"))
        M = M + np.outer(C[i], C[i])
    held = _held_back_text(R, _held_back(R, discrete))
    unest = [t for t in R.dropped_terms if t.endswith("^2") and rs.term_parents(t)[0] in _held_back(R, discrete)]
    return Recommendation("augment", "Strengthen the model where it is weakest",
                          "The model is weak here: " + "; ".join(reasons) + ". These runs are the settings that "
                          "most reduce the model's uncertainty (each one chosen where the current prediction is "
                          "least certain, D-optimal), from settings that can actually be run, inside the fitted "
                          "span." + (f" {held}." if held else "")
                          + (f" {', '.join(unest)} needs a third size inside the fitted runs, which these runs "
                             "cannot give: plan it into the next design." if unest else ""), rows)


def new_level(R, discrete: dict | None, alpha: float = 0.05) -> list[Recommendation]:
    """The CCD plan's three conditions for making a new size of a fixed-size factor (an insert)."""
    out = []
    o = R.optimum_discrete or R.optimum
    if o is None or not discrete:
        return out
    for k, sizes in discrete.items():
        if k not in R.axis:
            continue
        f = _f(R, k)
        lo, hi = float(f.low), float(f.high)
        at = R.decode(k, o.coded[k])
        if abs(at - lo) < 1e-6:
            edge, inner, outward = lo, min((s for s in sizes if s > lo), default=None), -1
        elif abs(at - hi) < 1e-6:
            edge, inner, outward = hi, max((s for s in sizes if s < hi), default=None), +1
        else:
            continue                            # condition 1 fails: not at an edge
        slopes = []
        for g in R.goals:
            fr = R.fits.get(g.key)
            if fr is None or fr.reduced is None:
                continue
            gr, p = slope_at(fr.reduced, k, o.coded)
            improves = (gr * outward > 0) == (g.direction == "max")
            if p is not None and p < alpha and improves:
                slopes.append(f"{fr.label} (slope {gr:+.3g} per coded unit, p = {p:.2g})")
        if not slopes:
            continue                            # condition 2 fails
        checks = [(fr.label, p) for key, fr in R.fits.items() if key in {g.key for g in R.goals}
                  for p in fr.predictions if p.run.point.kind == rdet.CHECK and p.run.point.values.get(k) is not None]
        if not checks:
            continue                            # condition 3 cannot be judged: no check run at this factor
        if not all(p.inside for _, p in checks):
            continue                            # condition 3 fails: the check run missed
        new = edge * (edge / inner) if inner else None
        if new is None or new <= 0:
            continue
        vals = {kk: snap(R, kk, R.decode(kk, o.coded[kk]), discrete) for kk in R.axis}
        vals[k] = round(new, 2)
        hold, _ = best_hold(R)
        for kk in R.nuisance:
            vals[kk] = _best_values(R, o, discrete, hold)[kk]
        rows = [_row(R, vals, f"With a new {f.label} of about {new:.2g} (to be made)")]
        out.append(Recommendation(
            "new_level", f"Make a new {f.label.split(' (')[0].lower()}: about {new:.2g}",
            f"All three conditions hold: the best setting is at the {edge:g} edge; the slope there is still "
            f"significant and still improving ({'; '.join(slopes)}); and the check run"
            f"{'s' if len(checks) > 1 else ''} matched the model (inside the 95% prediction interval), so its "
            f"predictions between sizes can be trusted. The next size by the same ratio as the existing step "
            f"({inner:g} -> {edge:g}) is about {new:.2g}. The prediction there is an extrapolation.", rows))
    return out


def recommend(R, discrete: dict | None = None, n_confirm: int = 3, n_augment: int = 4) -> list[Recommendation]:
    recs = []
    for r in (confirm(R, discrete, n_confirm), steepest(R, discrete), new_ccd(R, discrete),
              augment(R, discrete, n_augment)):
        if r is not None:
            recs.append(r)
    recs += new_level(R, discrete)
    return recs


# ---- the run sheet ---------------------------------------------------------------------------------------

def table(R, recs: list[Recommendation], prefix: str = "CCD next run") -> list[dict]:
    """One row per proposed run, numbered, with the Notes to type and each prediction (mean and PI)."""
    rows = []
    n = 0
    for rec in recs:
        if rec.kind == "new_ccd":
            continue                            # a whole new design: its own sheet (exported separately)
        for r in rec.rows:
            n += 1
            d = {"Run": n, "Recommendation": rec.title, "Why this run": r.label}
            for k in _model_keys(R):
                d[_f(R, k).label] = r.values.get(k)
            for key, (m, lo, hi) in r.preds.items():
                lab = R.fits[key].label
                d[f"predicted {lab}"] = round(m, 4)
                d[f"{lab} 95% PI"] = f"{lo:.4g} to {hi:.4g}"
            d["extrapolated"] = "yes" if r.extrapolated else ""
            d["pressure check"] = pressure_check(R, r.preds)
            d["Notes to type"] = f"{prefix} {n} {rec.kind}"
            rows.append(d)
    return rows


def export(R, recs: list[Recommendation], output_dir: Path) -> list[Path]:
    """next_runs.csv / .xlsx / .md, and the new CCD (if one is recommended) as its own run sheet."""
    import pandas as pd
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = table(R, recs)
    written = []
    if rows:
        p = out / f"{EXPORT_STEM}.csv"
        tmp = p.with_name(f".{p.name}.tmp")
        cols: list = []
        for r in rows:
            cols += [c for c in r if c not in cols]
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        fsops.replace(tmp, p)
        written.append(p)
        p = out / f"{EXPORT_STEM}.xlsx"
        tmp = p.with_name(f".{p.stem}.tmp.xlsx")
        with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
            pd.DataFrame(rows).to_excel(xw, sheet_name="Next runs", index=False)
            pd.DataFrame([{"Recommendation": r.title, "Why": r.why} for r in recs]).to_excel(
                xw, sheet_name="Why", index=False)
        fsops.replace(tmp, p)
        written.append(p)
        p = out / f"{EXPORT_STEM}.md"
        tmp = p.with_name(f".{p.name}.tmp")
        lines = ["# Recommended next runs\n"]
        for rec in recs:
            lines += [f"## {rec.title}\n", rec.why, ""]
        head = ["Run", "Recommendation", "Why this run"] + [_f(R, k).label for k in _model_keys(R)] + ["Notes to type"]
        lines += ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
        lines += ["| " + " | ".join(str(r.get(h, "")) for h in head) + " |" for r in rows]
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fsops.replace(tmp, p)
        written.append(p)
    for rec in recs:
        if rec.kind == "new_ccd" and rec.sheet is not None:
            sub = out / "next CCD"
            rb.save(rec.sheet, sub)
            written += rb.export(rec.sheet, sub)
    return written
