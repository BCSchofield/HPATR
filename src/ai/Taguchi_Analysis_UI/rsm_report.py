"""rsm_report.py -- the response-surface tables and rsm_report.md. No Qt.

Every number comes from rsm_responses / rsm_stats results and is put into tables ONCE (tables()),
which the report, the workbook and the CSVs all draw from, so they cannot disagree (the Taguchi
report's rule). Wording is restrained the same way: p < 0.05 is "evidence", a simplified model's
p-values are flagged as optimistic, and a term whose estimate changes between models is said to be
not separated from what the models treat differently.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import rsm_detect as rdet
from . import rsm_responses as rr
from . import rsm_stats as rs
from .operating import NEAR_CEILING_BAR as NEAR_CEILING
from .report import fmt, fmt_p, md_table

ALPHA = 0.05
HEADLINE = ("atom", "d32", "d_mean", "af_flow", "cv_droplets")   # mean diameter: Ben, 2026-10-11
NEXT_RUN_STEP = {"sccm": 100, "sps": 100, "rpm": 50, "orifice": None, "bh": 0.1}    # setpoint resolution
# rsm_results.csv: the column names the CCD plan's own analysis code reads
CSV_NAMES = {"atom": "af", "d32": "d32", "d_mean": "mean_d", "d_median": "median_d", "d90": "d90_count",
             "per_frame": "infocus_per_frame", "cv_droplets": "count_cv", "cv_liquid": "liquid_cv",
             "intermit_pct": "near_empty_pct", "dv50": "dv50", "af_flow": "af_flow", "thin_pct": "thin_pct",
             "lag1": "lag1", "peak_bar": "peak_bar", "atom_vol": "af_vol", "af_flow_vol": "af_flow_vol",
             "band_per_frame": "band_per_frame", "rate": "rate_per_s", "rate_band": "rate_band_per_s"}
FACTOR_CSV = {"sccm": "gas_sccm", "sps": "feed_sps", "rpm": "rpm", "orifice": "orifice_mm", "bh": "bh_mm"}


def _short(label: str) -> str:
    return label.split(" (")[0]


def _flabel(R, k: str) -> str:
    if k == "time":
        return "time"
    return next((f.label for f in R.loaded.detected.factors if f.key == k), k)


def term_text(R, t: str) -> str:
    """'sccm*sps' -> 'Gas flow x Silicone'."""
    if t == "1":
        return "intercept"
    p = rs.term_parents(t)
    names = [_short(_flabel(R, k)) for k in p]
    if len(p) == 1:
        return names[0]
    return f"{names[0]}²" if p[0] == p[1] else f"{names[0]} × {names[1]}"


# ---- derived findings ---------------------------------------------------------------------------------

def interaction_agreement(models: dict, key: str) -> list[dict]:
    """For every axis interaction: its estimate and p under each model, and whether the models agree
    (same sign and both significant, or both not)."""
    names = list(models)
    first = models[names[0]]
    out = []
    for t in first.terms:
        p = rs.term_parents(t)
        if len(p) != 2 or p[0] == p[1]:
            continue
        row = {"term": t, "by_model": {}}
        for n in names:
            f = models[n].fits.get(key)
            f = f.full if f is not None else None
            if f is not None and t in f.terms:
                i = f.terms.index(t)
                row["by_model"][n] = (float(f.beta[i]), float(f.p[i]))
        vals = list(row["by_model"].values())
        sig = [pv < ALPHA for _, pv in vals]
        signs = {np.sign(b) for b, pv in vals if pv < ALPHA}
        row["agree"] = len(vals) < 2 or (len(set(sig)) == 1 and len(signs) <= 1)
        out.append(row)
    return out


def stationary_points(R, key: str):
    fr = R.fits.get(key)
    if fr is None or fr.reduced is None:
        return None
    fixed = dict(R.hold)
    if "time" in fr.reduced.terms:
        fixed["time"] = 0.0
    best = R.optimum.coded if R.optimum is not None else {}
    return rs.stationary(fr.reduced, R.axis, fixed, fallback=best)


def optimum_by_hold(R) -> list[tuple[dict, rs.Optimum]]:
    """The desirability optimum at every held level of the nuisance factors (the maps' panels)."""
    from . import rsm_figures as rf
    out = []
    for hold in rf._hold_sets(R):
        o = rf._optimum_at(R, hold)
        if o is not None:
            out.append((hold, o))
    return out


def controls(R) -> list[dict]:
    """Every run outside the region (a control such as 0 rpm) against the centre runs, per headline
    response: the CCD plan's "does rotation help?" comparison."""
    cen = [r for r in R.loaded.runs if r.point.in_fit and r.point.kind == rdet.CENTRE]
    out = []
    for r in R.loaded.runs:
        if r.point.kind != rdet.OUTSIDE:
            continue
        centre = {f.key: f.centre for f in R.loaded.detected.factors}
        differs = ", ".join(f"{_short(_flabel(R, k))} {v:g}" for k, v in r.point.values.items() if v != centre.get(k))
        for key in HEADLINE:
            if key not in R.fits:
                continue
            c = np.array([x.values.get(key) for x in cen if x.values.get(key) is not None], float)
            v = r.values.get(key)
            row = {"run": r.point.name, "differs from the centre in": differs, "response": R.fits[key].label,
                   "value": _r(v), "centre runs": len(c)}
            if c.size >= 2 and v is not None:
                sd = float(c.std(ddof=1))
                row.update({"centre mean": _r(c.mean()), "centre SD": _r(sd),
                            "difference in centre SDs": _r((v - c.mean()) / sd) if sd > 0 else None})
            out.append(row)
    return out


# ---- tables -------------------------------------------------------------------------------------------------

def tables(models: dict) -> dict[str, list[dict]]:
    names = list(models)
    R = models[names[0]]
    det = R.loaded.detected
    keys = [f.key for f in det.factors]
    out: dict[str, list[dict]] = {}

    runs = []
    for r in sorted(R.loaded.runs, key=lambda r: (r.point.order, r.point.name)):
        row = {"run": r.point.name, "order": r.point.order, "hours": None if r.hours is None else round(r.hours, 4),
               "point type": rdet.KIND_TEXT.get(r.point.kind, r.point.kind),
               "in fit": "yes" if r.point.in_fit else ("validation" if r.point.validation else
                                                       f"no ({r.op.regime})" if r.point.excluded else "no"),
               "block": r.point.block or ""}
        op = r.op
        row["gas delivered (sccm)"] = None if op is None or op.delivered_sccm is None else round(op.delivered_sccm)
        row["P0 in camera window (barA)"] = None if op is None or op.p0_bar is None else round(op.p0_bar, 3)
        row["regime"] = op.regime if op is not None else ""
        row["settled"] = "" if op is None or op.settled is None else ("yes" if op.settled else "NO")
        for k in keys:
            row[_flabel(R, k)] = r.point.values.get(k)
        for k in keys:
            row[f"{_short(_flabel(R, k))} (coded)"] = None if r.point.real.get(k) is None else round(r.point.real[k], 4)
        for key, fr in R.fits.items():
            v = r.values.get(key)
            row[fr.label] = None if v is None or not math.isfinite(v) else round(float(v), 6)
        row["notes"] = (r.point.row.notes or "").replace("\n", " ")
        runs.append(row)
    out["runs"] = runs

    coefs, summary = [], []
    for n, M in models.items():
        for key, fr in M.fits.items():
            if fr.full is None:
                summary.append({"model": n, "response": fr.label, "note": fr.note})
                continue
            for which, f in (("full", fr.full), ("simplified", fr.reduced)):
                for i, t in enumerate(f.terms):
                    coefs.append({"model": n, "response": fr.label, "fit": which, "term": t,
                                  "term (names)": term_text(M, t), "coefficient": round(float(f.beta[i]), 6),
                                  "SE": None if not np.isfinite(f.se[i]) else round(float(f.se[i]), 6),
                                  "t": None if not np.isfinite(f.t[i]) else round(float(f.t[i]), 4),
                                  "p": None if not np.isfinite(f.p[i]) else round(float(f.p[i]), 8),
                                  "q (BH, full models)": None if which != "full" or t not in f.q
                                  else round(float(f.q[t]), 8),
                                  "VIF": None if t == "1" or which != "full" else round(fr.vif.get(t, float("nan")), 3)})
            f, red = fr.full, fr.reduced
            lof = f.lof
            summary.append({"model": n, "response": fr.label, "runs": f.n, "terms (full)": len(f.terms),
                            "terms (simplified)": len(red.terms), "R2": _r(f.r2), "adjusted R2": _r(f.r2_adj),
                            "predicted R2": _r(f.r2_pred), "R2 (simplified)": _r(red.r2),
                            "predicted R2 (simplified)": _r(red.r2_pred), "residual SD": _r(f.s),
                            "lack-of-fit F": None if lof is None or lof.F is None else _r(lof.F),
                            "lack-of-fit df": None if lof is None else lof.df_lof,
                            "pure-error df": None if lof is None else lof.df_pe,
                            "lack-of-fit p": None if lof is None or lof.p is None else round(lof.p, 8),
                            "dropped by simplification": ", ".join(t for t, _ in red.removed)})
    out["coefficients"] = coefs
    out["fit_summary"] = summary

    comp = []
    for key in R.fits:
        for row in interaction_agreement(models, key):
            d = {"response": R.fits[key].label, "term": term_text(R, row["term"])}
            for n, (b, p) in row["by_model"].items():
                d[f"{n}: coefficient"] = round(b, 6)
                d[f"{n}: p"] = round(p, 8)
            d["models agree"] = "yes" if row["agree"] else "NO"
            comp.append(d)
    out["model_comparison"] = comp

    st = []
    for key, fr in R.fits.items():
        s = stationary_points(R, key)
        if s is None:
            continue
        d = {"response": fr.label, "kind": s.kind, "inside the tested range": "yes" if s.inside else "no",
             "fitted value there": _r(s.value)}
        for k, c in s.coded.items():
            d[_flabel(R, k)] = round(R.decode(k, c), 3)
        for k, c in s.held.items():
            d[_flabel(R, k)] = f"{num(R.decode(k, c))} (held: no curve)"
        st.append(d)
    out["stationary_points"] = st

    opt = []
    for n, M in models.items():
        rows_ = list(optimum_by_hold(M))
        if M.optimum_discrete is not None:
            rows_.append(({"__settable__": True}, M.optimum_discrete))
        for hold, o in rows_:
            settable = hold.pop("__settable__", False) if isinstance(hold, dict) else False
            d = {"model": n, "held at": ("at the levels that can be set" if settable else
                                         ", ".join(f"{_short(_flabel(M, k))} {v:g}" for k, v in hold.items()) or "-"),
                 "desirability D": round(o.D, 4), "on the edge of": ", ".join(_short(_flabel(M, k)) for k in o.on_edge)}
            for k in M.axis:
                d[_flabel(M, k)] = round(M.decode(k, o.coded[k]), 1)
            for key, v in o.preds.items():
                d[f"predicted {M.fits[key].label}"] = _r(v)
            opt.append(d)
    out["optimum"] = opt

    out["goals"] = [{"response": R.fits[g.key].label, "aim": {"max": "maximise", "min": "minimise"}.get(g.direction, "target"),
                     "0 at": g.low if g.direction == "max" else g.high, "1 at": g.high if g.direction == "max" else g.low,
                     "target": g.target, "importance": g.importance} for g in R.goals]
    out["constraints"] = [{"response": R.fits[c.key].label if c.key in R.fits else c.key, "at least": c.low,
                           "at most": c.high} for c in R.constraints]
    out["goal_status"] = [{"response": s.label, "aim": {"max": "maximise", "min": "minimise"}.get(s.aim, "target"),
                           "importance": s.importance, "used for the best setting": "yes" if s.used else "NO",
                           "why": s.why} for s in R.goal_status]
    out["gas_delivered"] = gas_rows(R)
    out["limited_effects"] = limited_effect_rows(R)
    out["best_observed"] = best_observed_rows(R)

    preds = []
    for key, fr in R.fits.items():
        for p in fr.predictions:
            preds.append({"response": fr.label, "run": p.run.point.name, "point type": rdet.KIND_TEXT.get(p.run.point.kind),
                          "observed": _r(p.observed), "predicted": _r(p.mean), "PI low": _r(p.pi[0]), "PI high": _r(p.pi[1]),
                          "inside the 95% PI": {True: "yes", False: "NO", None: "-"}[p.inside],
                          "extrapolated": "yes" if p.extrapolated else ""})
    out["predictions"] = preds

    pairs = []
    for key in HEADLINE:
        fr = R.fits.get(key)
        if fr is None:
            continue
        for block, a, b, diff, z in fr.block_pairs:
            pairs.append({"response": fr.label, "block": block, "first": a.point.name, "last": b.point.name,
                          "last - first": _r(diff), "in SDs of pure error": _r(z)})
    out["block_repeats"] = pairs

    out["correlations"] = [{"model": n, "nuisance": _flabel(M, a), "axis term": term_text(M, t), "r": round(r, 4)}
                           for n, M in models.items() for a, t, r in M.correlations]
    from . import rsm_recommend
    recs = rsm_recommend.recommend(R, R.discrete)
    out["next_runs"] = rsm_recommend.table(R, recs)
    out["recommendations"] = [{"recommendation": r.title, "kind": r.kind, "runs": len(r.rows), "why": r.why}
                              for r in recs]
    out["controls"] = controls(R)
    out["design"] = [{"level": f.level, "finding": f.text} for f in det.findings]
    return out


def gas_section(R, T, figs: set) -> list[str]:
    """'## Gas delivered': what each run got, its regime, and the runs that did not get their set gas."""
    rows = T["gas_delivered"]
    if not rows or not any(r["delivered (sccm)"] is not None for r in rows):
        return []
    L = ["## Gas delivered and the operating regime\n",
         "The gas flow and upstream pressure inside each run's camera window (`run_summary.xlsx`, Pressure sheet). "
         "**Flow-controlled**: the gas got at least 95% of its set point. **Pressure-limited**: it did not, with the "
         f"pressure within {NEAR_CEILING:g} bar of the supply ceiling ({R.loaded.opts.supply_ceiling_bar:g} barA): "
         "the silicone chokes the orifice and the gas falls to what it can pass at that pressure, so the set point no "
         "longer describes the run. **Settled**: the window's median flow within 10% (or 100 sccm) of the 10 s before "
         "it, and its two halves within the same.\n"]
    L.append(_img(figs, "fig_rsm_gas_delivered", "Gas delivered against set"))
    L.append(_img(figs, "fig_gas_traces", "Pressure and gas through each run"))
    counts: dict = {}
    for r in rows:
        counts[r["regime"]] = counts.get(r["regime"], 0) + 1
    L.append("Regimes: " + ", ".join(f"{n} {k}" for k, n in counts.items()) + ". Runs not settled when the camera "
             f"ran: {', '.join(r['run'][:6] for r in rows if r['settled'] == 'NO') or 'none'}.\n")
    nd = R.limited
    if nd:
        how = {"exclude": "They are **kept out of every surface** (the gas factor does not describe them) and "
                          "described here instead.",
               "delivered": "They are **fitted at the gas they got**, not their set point. Low gas then exists only "
                            "where the rig was pressure-limited, so its effect cannot be separated from that "
                            "orifice's.",
               "set": "They are **fitted at their SET gas**, which they did not get: their gas factor is wrong."
               }[R.limited_mode]
        L.append(f"### Runs that did not get their set gas ({len(nd)})\n")
        L.append(how + "\n")
        fac = [f.key for f in R.loaded.detected.factors]
        resp = [k for k in ("atom", "per_frame", "af_flow", "d_mean") if k in R.fits]
        L.append(md_table(["Run"] + [_short(_flabel(R, k)) for k in fac] + ["Gas delivered", "P0 (barA)", "Settled"]
                          + [_short(R.fits[k].label) for k in resp],
                          [[r.point.name[:6]] + [fmt(r.point.row.value(k), 5) for k in fac]
                           + [fmt(r.op.delivered_sccm, 5), fmt(r.op.p0_bar, 3),
                              "–" if r.op.settled is None else ("yes" if r.op.settled else "NO")]
                           + [fmt(r.values.get(k), 4) for k in resp]
                           for r in sorted(nd, key=lambda r: (r.point.order, r.point.name))]))
        eff = T["limited_effects"]
        if eff:
            L.append("\n**What controlled them** (a main-effects fit among these runs only: the change from each "
                     "factor's middle to its high level; p from the fit). If the set gas has no effect here, the rig, "
                     "not the set point, decided their gas.\n")
            L.append(md_table(["Response", "Factor", "Effect per half-range", "p", "Runs", "R²"],
                              [[e["response"], e["factor"], fmt(e["effect per half-range"], 4), fmt_p(e["p"]),
                                e["runs"], fmt(e["R²"], 3)] for e in eff]))
        L.append("")
    return L


def gas_rows(R) -> list[dict]:
    """Per run: the gas it was set to and the gas and pressure it got in the camera window (operating.py)."""
    rows = []
    for r in sorted(R.loaded.runs, key=lambda r: (r.point.order, r.point.name)):
        op = r.op
        if op is None:
            continue
        rows.append({"run": r.point.name, "set gas (sccm)": op.set_sccm,
                     "delivered (sccm)": None if op.delivered_sccm is None else round(op.delivered_sccm),
                     "delivered p10 (sccm)": None if op.delivered_p10 is None else round(op.delivered_p10),
                     "delivered p90 (sccm)": None if op.delivered_p90 is None else round(op.delivered_p90),
                     "delivered / set": None if op.delivered_share is None else round(op.delivered_share, 3),
                     "P0 (barA)": None if op.p0_bar is None else round(op.p0_bar, 3),
                     "10 s before the window (sccm)": None if op.pre_sccm is None else round(op.pre_sccm),
                     "regime": op.regime, "settled": "" if op.settled is None else ("yes" if op.settled else "NO"),
                     "in fit": "yes" if r.point.in_fit else "no", "note": op.note})
    return rows


def limited_effect_rows(R) -> list[dict]:
    """Main effects among the runs that did not get their set gas (coefficient per half-range, p)."""
    labels = {"delivered": "Gas delivered (sccm)", **{k: fr.label for k, fr in R.fits.items()}}
    rows = []
    for key, f in R.limited_effects.items():
        for t, b, p in zip(f.terms, f.beta, f.p):
            if t == "1":
                continue
            rows.append({"response": labels.get(key, key), "factor": _flabel(R, t), "effect per half-range": _r(b),
                         "p": _r(p), "runs": f.n, "R²": _r(f.r2)})
    return rows


def best_observed_rows(R) -> list[dict]:
    keys = [f.key for f in R.loaded.detected.factors]
    rows = []
    for i, (D, r, each) in enumerate(R.best_observed, 1):
        row = {"rank": i, "run": r.point.name, "D (observed)": _r(D)}
        for k in keys:
            row[_flabel(R, k)] = r.point.row.value(k)
        row["regime"] = r.op.regime if r.op is not None else ""
        row["gas delivered (sccm)"] = None if r.op is None or r.op.delivered_sccm is None else round(r.op.delivered_sccm)
        for key in each:
            v = r.values.get(key)
            row[R.fits[key].label if key in R.fits else key] = None if v is None or not math.isfinite(v) else _r(v)
        row["in fit"] = "yes" if r.point.in_fit else "no"
        rows.append(row)
    return rows


def results_csv(R) -> list[dict]:
    """One row per run in the CCD plan's column layout (gas_sccm, feed_sps, rpm, orifice_mm, af, d32, ...)."""
    rows = []
    for r in sorted(R.loaded.runs, key=lambda r: (r.point.order, r.point.name)):
        d = {"run": r.point.name, "order": r.point.order, "point_type": r.point.kind,
             "in_fit": int(r.point.in_fit), "block": r.point.block or ""}
        for k, v in r.point.values.items():
            d[FACTOR_CSV.get(k, k)] = v
        for k, name in CSV_NAMES.items():
            v = r.values.get(k)
            d[name] = None if v is None or not math.isfinite(v) else v
        d["hours"] = r.hours
        why = (r.metrics or {}).get("no_spray")
        d["note"] = f"no spray: size and steadiness not reported ({why})" if why else ""
        rows.append(d)
    return rows


def num(v) -> str:
    """A setting or value for prose: 10,900 not 1.09e+04; 1.735; 0.0899."""
    v = float(v)
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.4g}"


def _r(x, nd: int = 6):
    if x is None:
        return None
    x = float(x)
    return None if not math.isfinite(x) else round(x, nd)


# ---- the report -------------------------------------------------------------------------------------------------

def _stems(figs: set, base: str) -> list[str]:
    """The figure stems for one map (base, or base_<factor><level> for one figure per level)."""
    return sorted({Path(f).stem for f in figs if f.endswith(".png") and
                   (Path(f).stem == base or Path(f).stem.startswith(base + "_"))})


def _img(figs: set, name: str, cap: str) -> str:
    return f"![{cap}](figures/{name}.png)\n" if f"{name}.png" in figs else ""


def _verdict(R, key: str) -> list[str]:
    """Plain-words findings for one response from the primary model."""
    fr = R.fits.get(key)
    if fr is None or fr.full is None:
        return []
    f, red = fr.full, fr.reduced
    out = []
    lin = []
    for k in R.axis:
        if k in f.terms:
            i = f.terms.index(k)
            if f.p[i] < ALPHA:
                lin.append(f"{'rises' if f.beta[i] > 0 else 'falls'} with {_short(_flabel(R, k)).lower()}")
    curv = [term_text(R, t) for t in f.terms if t.endswith("^2") and rs.term_parents(t)[0] in R.axis
            and f.p_of[t] < ALPHA]
    lof = f.lof
    # predictive quality is the simplified model's: it is what the maps draw and the best setting uses
    r2p = fr.r2_pred_used
    fitq = (f"the model explains {100 * f.r2:.0f}% of the run-to-run spread (predicted R² {r2p:.2f}, simplified "
            f"model)" if f.r2 is not None and r2p is not None else "")
    lofq = ("" if lof is None or lof.p is None else
            (f"; lack of fit is significant (p = {lof.p:.3f}): the surface misses something" if lof.p < ALPHA
             else f"; no evidence of lack of fit (p = {lof.p:.2f})"))
    weak = ""
    if r2p is not None and r2p < rr.USABLE_R2_PRED:
        weak = (f" **This surface predicts new runs poorly** (predicted R² below {rr.USABLE_R2_PRED}"
                + ("; below 0, worse than just using the average" if r2p < 0 else "")
                + "): treat its map as noise, not a guide.")
    out.append(f"**{fr.label}** " + ("; ".join(lin) if lin else "shows no clear slope along the axis factors")
               + (f", and curves ({', '.join(curv)} significant)" if curv else "") + f". {fitq[:1].upper()}{fitq[1:]}{lofq}."
               + weak)
    s = stationary_points(R, key)
    if s is not None:
        out.append(f"  - {stationary_text(R, key, s)}")
    return out


def stationary_text(R, key: str, s) -> str:
    """The fitted surface's stationary point in words, by its kind and the response's direction."""
    fr = R.fits[key]
    where = ", ".join(f"{_short(_flabel(R, k))} {num(R.decode(k, c))}" for k, c in s.coded.items())
    ridge = " (nearly a ridge: along one direction it barely changes)" if "ridge" in s.kind else ""
    good = (s.kind.startswith("maximum") and fr.direction == "larger") or \
           (s.kind.startswith("minimum") and fr.direction == "smaller")
    inside = "inside the tested range" if s.inside else "outside the tested range"
    if s.held:
        inside += ("; " + ", ".join(_short(_flabel(R, k)) for k in s.held) + " only a straight line, so held at the "
                   "best setting: along it the best value is at an edge")
    if s.kind.startswith("saddle"):
        return (f"The surface is a saddle{ridge}: it rises along one direction and falls along another, centred at "
                f"{where} ({inside}), so the best values lie on the edges of the range, not at an interior peak.")
    if good:
        return (f"The surface has its best point at {where}{ridge} ({inside}"
                + (")." if s.inside else "; within the range the best value is on the nearest edge)."))
    return (f"The surface has its worst point at {where}{ridge} ({inside}); the best values are on the edges of "
            f"the range.")


def tradeoffs(R, o) -> dict:
    """At the optimum: for each axis factor, which goals would rather it went up and which down
    (the sign of each goal's desirability slope there). Explains a best point on an edge."""
    if o is None:
        return {}
    import numpy as np
    out = {}
    h = 0.02
    for k in R.axis:
        up, down = [], []
        for g in R.goals:
            f = R.fits.get(g.key)
            if f is None or f.reduced is None:
                continue
            vals = []
            for dx in (-h, h):
                x = {kk: np.array([o.coded[kk]]) for kk in R.axis}
                x[k] = x[k] + dx
                for kk, v in R.hold.items():
                    x[kk] = np.array([v])
                if "time" in f.reduced.terms:
                    x["time"] = np.array([0.0])
                vals.append(float(g.d(f.reduced.predict(x)["mean"])[0]))
            slope = vals[1] - vals[0]
            if slope > 1e-9:
                up.append(_short(f.label))
            elif slope < -1e-9:
                down.append(_short(f.label))
        out[k] = (up, down)
    return out


def build(models: dict, prov, figure_files=(), title: str = "Response-surface analysis", shared=None) -> str:
    """`shared`: the same runs through the Taguchi analysis (rsm_publish's shared extras), for the covariate
    sections (gas mass flux at the orifice, silicone film at the exit); None leaves them out."""
    from pathlib import Path
    figs = {Path(p).name for p in figure_files}
    names = list(models)
    R = models[names[0]]
    det = R.loaded.detected
    T = tables(models)
    L = []
    n_fit = sum(1 for r in R.loaded.runs if r.point.in_fit)
    L.append(f"# {title}\n")
    L.append(f"{len(R.loaded.runs)} runs ({n_fit} in the fit) · surface over "
             f"{' × '.join(_short(_flabel(R, k)) for k in R.axis)} · generated {prov.generated} · revision {prov.revision}\n")
    if R.loaded.refused:
        return "\n".join(L + ["## Not analysed\n", R.loaded.refused]) + "\n"
    # problems reading the runs go first, where they cannot be missed (e.g. no atomised
    # liquid flow, which silently removed the throughput goal on 2026-10-13)
    for w in R.loaded.warnings:
        L.append(f"> ⚠ {w}\n")

    # what was found
    L.append("## What was found\n")
    for key in HEADLINE:
        L += [f"- {x}" if not x.startswith("  ") else x for x in _verdict(R, key)]
    for key in HEADLINE:
        disagree = [row for row in interaction_agreement(models, key) if not row["agree"]]
        for row in disagree:
            bits = "; ".join(f"{n}: {b:+.3g} ({fmt_p(p)})" for n, (b, p) in row["by_model"].items())
            L.append(f"- **{term_text(R, row['term'])} on {_short(R.fits[key].label)} changes with the model** ({bits}): "
                     f"it cannot be separated from what the models treat differently, so do not read it as an "
                     f"interaction.")
    best = max(optimum_by_hold(R), key=lambda ho: ho[1].D, default=None)
    if best is not None:
        hold, o = best
        where = ", ".join(f"{_short(_flabel(R, k))} {num(R.decode(k, o.coded[k]))}" for k in R.axis)
        held = ", ".join(f"{_short(_flabel(R, k))} {v:g}" for k, v in hold.items())
        L.append(f"- **Best overall setting** (desirability D = {o.D:.2f}): {where}" + (f" at {held}" if held else "")
                 + (f". It sits on the edge of the tested range for {', '.join(_short(_flabel(R, k)) for k in o.on_edge)}:"
                    f" the best point may lie beyond it, so confirm before going further." if o.on_edge else "."))
        if R.free:
            one = len(R.free) == 1
            L.append(f"  - {', '.join(_short(_flabel(R, k)) for k in R.free)} {'is' if one else 'are'} in none of "
                     f"the surfaces it optimises, so the best setting does not depend on {'it' if one else 'them'}: "
                     f"held at the design centre. Choose {'it' if one else 'them'} for another reason (throughput, "
                     f"steadiness, cost).")
        for k, (up, down) in tradeoffs(R, o).items():
            if up and down:
                L.append(f"  - The trade-off on {_short(_flabel(R, k)).lower()}: {', '.join(up)} would rather it went "
                         f"up; {', '.join(down)} would rather it went down. The combined score settles at "
                         f"{num(R.decode(k, o.coded[k]))}.")
    left_out = [s for s in R.goal_status if not s.used]
    used = [_short(s.label) for s in R.goal_status if s.used]
    if left_out:
        L.append(("  - It optimises " + ", ".join(used) + " only: " if used else
                  "- **No best setting**: every goal was left out: ")
                 + "; ".join(f"{_short(s.label)} was set as a goal but left out ({s.why})" for s in left_out) + ".")
    if R.best_observed:
        D, r, _each = R.best_observed[0]
        setting = ", ".join(f"{_short(_flabel(R, f.key))} {num(r.point.row.value(f.key))}"
                            for f in det.factors if r.point.row.value(f.key) is not None)
        L.append(f"- **Best run as measured** (the same goals on observed values): {r.point.name[:6]} ({setting}"
                 + (f"; {r.op.regime}, {r.op.delivered_sccm:,.0f} sccm delivered" if r.op is not None
                    and r.op.delivered_sccm is not None else "") + f"), D = {D:.2f}.")
    if R.limited:
        how = {"exclude": "kept out of the surfaces", "delivered": "fitted at the gas they got",
               "set": "fitted at their set gas, which they did not get"}[R.limited_mode]
        L.append(f"- **{len(R.limited)} run(s) did not get their set gas** ("
                 + ", ".join(sorted({r.op.regime for r in R.limited})) + f"), {how}: see *Gas delivered*.")
    L.append("")

    # the design and the models
    L.append("## The design and the models\n")
    line = f"Detected design: **{det.design_type}**."
    if det.recommendation[0] != "Response surface":
        line += (f" On its own it belongs in the {det.recommendation[0]} tab; here a surface is fitted over "
                 f"{' × '.join(_short(_flabel(R, k)) for k in R.axis)} on purpose (every combination of their levels "
                 f"was run), with the other factors handled as below.")
    L.append(line + "\n")
    for f in det.findings:
        if f.level in ("warn", "error") and not f.text.startswith("the full quadratic"):
            L.append(f"- ⚠ {f.text}")
    L.append("")
    rows = []
    for n, M in models.items():
        nuis = ", ".join(f"{_short(_flabel(M, k))} ({how})" for k, how in M.nuisance.items()) or "none"
        f0 = next((fr.full for fr in M.fits.values() if fr.full is not None), None)
        dfs = ("–" if f0 is None or f0.lof is None else
               f"{f0.n} runs; {f0.lof.df_pe} pure-error df, {f0.lof.df_lof} lack-of-fit df")
        rows.append([n, " × ".join(_short(_flabel(M, k)) for k in M.axis), nuis, len(M.terms), dfs,
                     "; ".join(M.warnings) or "–"])
    L.append(md_table(["Model", "Surface over", "Nuisance terms", "Terms", "Degrees of freedom", "Notes"], rows))
    from . import rsm_figures as rf
    lay = rf.map_layout(R)
    if lay is not None:
        L.append(f"Maps: {lay.describe(R)}.\n")
    if T["correlations"]:
        L.append("\n**Nuisance terms that track surface terms** (partial confounding: the two cannot be fully "
                 "separated)\n")
        L.append(md_table(["Model", "Nuisance", "Surface term", "r"],
                          [[c["model"], c["nuisance"], c["axis term"], f"{c['r']:+.2f}"] for c in T["correlations"]]))
    L.append("")

    L += gas_section(R, T, figs)
    if shared is not None and shared.runs:
        from .report import film_section, gas_flux_section
        L.append(gas_flux_section(shared, figs))
        L.append(film_section(shared, figs))

    # per response
    L.append("## Results by response\n")
    L.append(_img(figs, "fig_rsm_fit_checks", "Fit checks"))
    L.append(_img(figs, "fig_rsm_model_compare", "Model comparison"))
    for key, fr in R.fits.items():
        L.append(f"### {fr.label}\n")
        if fr.full is None:
            L.append(f"No fit: {fr.note}.\n")
            continue
        for x in _verdict(R, key):
            L.append(x if x.startswith("  ") else f"{x}\n")
        for stem in _stems(figs, f"fig_rsm_contour_{key}"):
            L.append(_img(figs, stem, f"{fr.label} contour map"))
        L.append(_img(figs, f"fig_rsm_surface_{key}", f"{fr.label} 3D surface"))
        L.append(_img(figs, f"fig_rsm_pairs_{key}", f"{fr.label}, every pair of factors"))
        f, red = fr.full, fr.reduced
        rows = []
        for i, t in enumerate(f.terms):
            rows.append([term_text(R, t), fmt(float(f.beta[i]), 4), fmt(float(f.se[i]), 3), fmt(float(f.t[i]), 3),
                         fmt_p(float(f.p[i])), fmt_p(f.q.get(t)), "✔" if t in red.terms else "",
                         fmt(fr.vif.get(t), 3) if t != "1" else ""])
        L.append(md_table(["Term", "Coefficient (coded)", "SE", "t", "p", "q (BH)", "In simplified", "VIF"], rows))
        lof = f.lof
        L.append(f"\nR² {fmt(f.r2, 3)}, adjusted {fmt(f.r2_adj, 3)}, predicted {fmt(f.r2_pred, 3)}; simplified model "
                 f"R² {fmt(red.r2, 3)}, predicted {fmt(red.r2_pred, 3)}. "
                 + ("" if lof is None or lof.p is None else
                    f"Lack of fit F = {fmt(lof.F, 3)} on {lof.df_lof} and {lof.df_pe} df, {fmt_p(lof.p)}. ")
                 + (f"Dropped by simplification: {', '.join(term_text(R, t) for t, _ in red.removed)}." if red.removed
                    else "") + "\n")
        others = [n for n in names[1:] if models[n].fits.get(key) and models[n].fits[key].full]
        if others:
            for n in others:
                g = models[n].fits[key].full
                L.append(f"*{n}*: R² {fmt(g.r2, 3)}, predicted {fmt(g.r2_pred, 3)}"
                         + ("" if g.lof is None or g.lof.p is None else f", lack of fit {fmt_p(g.lof.p)}") + ".\n")

    # optimum and next runs
    L.append("## Best settings\n")
    for stem in _stems(figs, "fig_rsm_desirability"):
        L.append(_img(figs, stem, "Desirability"))
    L.append(_img(figs, "fig_rsm_profiler", "Prediction profiler"))
    L.append("Desirability scores each goal from 0 (unacceptable) to 1 (ideal) and takes the geometric mean, so no goal "
             "can be traded away completely. **Every goal that was set, and whether it steered the best setting** "
             "(a goal is left out when its surface cannot predict a new run, or when it has no values):\n")
    ramps = {g["response"]: g for g in T["goals"]}
    L.append(md_table(["Response", "Aim", "Importance", "Used", "0 at", "1 at", "Why"],
                      [[s["response"], s["aim"], fmt(s["importance"], 3), s["used for the best setting"],
                        fmt(ramps.get(s["response"], {}).get("0 at")), fmt(ramps.get(s["response"], {}).get("1 at")),
                        "–" if s["why"] == "used" else s["why"]] for s in T["goal_status"]]))
    if getattr(R, "surface_best", None):
        L.append("\nA blank *1 at* is the best the fitted surface reaches inside the tested region, so 'maximise' "
                 "never tops out at the best run seen: " + "; ".join(
                     f"{_short(R.fits[k].label)} {fmt(v)}" for k, v in R.surface_best.items() if k in R.fits)
                 + ". A blank *0 at* is the worst run seen.\n")
    dropped = [s for s in T["goal_status"] if s["used for the best setting"] != "yes"]
    kept = [s["response"] for s in T["goal_status"] if s["used for the best setting"] == "yes"]
    if dropped:
        L.append(f"\n**{len(dropped)} of {len(T['goal_status'])} goals were left out**, "
                 + (f"so the best setting below optimises {', '.join(kept)} only.\n" if kept else
                    "so there is no best setting: no goal has a surface that can predict a new run.\n"))
    if T["constraints"]:
        L.append(md_table(["Constraint", "At least", "At most"],
                          [[c["response"], fmt(c["at least"]), fmt(c["at most"])] for c in T["constraints"]]))
    else:
        L.append("\nNo hard constraints (there is no rated pressure limit; peak pressure is reported, not limited).\n")
    head = ["Model", "Held at", "D"] + [_flabel(R, k) for k in R.axis] + ["On the edge of"]
    L.append(md_table(head, [[o["model"], o["held at"], fmt(o["desirability D"], 3)] +
                             [fmt(o[_flabel(R, k)], 5) for k in R.axis] + [o["on the edge of"] or "–"]
                             for o in T["optimum"]]))
    if R.free:
        L.append(f"\n{', '.join(_flabel(R, k) for k in R.free)}: in none of the surfaces that steer the best "
                 "setting, so any level gives the same score; shown at the design centre.\n")
    if T["best_observed"]:
        L.append("\n**Best runs as measured** (the same goals scored on each run's OBSERVED values; every run counts, "
                 "in the fit or not, so a reproducible pressure-limited run shows here even though the surface "
                 "leaves it out)\n")
        goal_cols = [k for k in T["best_observed"][0] if k not in
                     {"rank", "run", "D (observed)", "regime", "gas delivered (sccm)", "in fit"}
                     and k not in {_flabel(R, f.key) for f in R.loaded.detected.factors}]
        fac = [_flabel(R, f.key) for f in R.loaded.detected.factors]
        L.append(md_table(["Rank", "Run", "D"] + [_short(c) for c in fac] + ["Gas delivered", "Regime"]
                          + [_short(c) for c in goal_cols],
                          [[b["rank"], b["run"][:6], fmt(b["D (observed)"], 3)] + [fmt(b.get(c), 5) for c in fac]
                           + [fmt(b["gas delivered (sccm)"], 5), b["regime"] or "–"]
                           + [fmt(b.get(c), 4) for c in goal_cols] for b in T["best_observed"]]))
    if T["stationary_points"]:
        L.append("\n**Where each fitted surface peaks** (simplified model, nuisance factors at their centre)\n")
        L.append(md_table(["Response", "Kind", "Inside the range"] + [_flabel(R, k) for k in R.axis] + ["Fitted value"],
                          [[s["response"], s["kind"], s["inside the tested range"]] +
                           [fmt(s.get(_flabel(R, k)), 5) for k in R.axis] + [fmt(s["fitted value there"], 4)]
                           for s in T["stationary_points"]]))
    if T["recommendations"]:
        L.append("\n## Recommended next runs\n")
        L.append("What to run next, and why. Every run carries its predicted responses with the 95% prediction "
                 "interval (where it should land); runs outside the tested region are marked as extrapolated. The "
                 "same runs, numbered with the Notes to type, are in `next_runs.xlsx`.\n")
        keys = [k for k in R.axis + list(R.nuisance)]
        goals = [g.key for g in R.goals]
        for rec_ in T["recommendations"]:
            L.append(f"### {rec_['recommendation']}\n")
            L.append(rec_["why"] + "\n")
            rows = [r for r in T["next_runs"] if r["Recommendation"] == rec_["recommendation"]]
            if rows:
                warn = any(r.get("pressure check") for r in rows)
                head = ["Run", "Why this run"] + [_short(_flabel(R, k)) for k in keys] + \
                       [f"{_short(R.fits[g].label)} (95% PI)" for g in goals] + ["Extrapolated"] + \
                       (["Pressure check"] if warn else [])
                L.append(md_table(head, [[r["Run"], r["Why this run"]] + [fmt(r.get(_flabel(R, k)), 5) for k in keys]
                                         + [f"{fmt(r.get('predicted ' + R.fits[g].label), 4)} "
                                            f"({r.get(R.fits[g].label + ' 95% PI', '–')})" for g in goals]
                                         + [r["extrapolated"] or "–"]
                                         + ([r.get("pressure check") or "–"] if warn else []) for r in rows]))
            elif rec_["kind"] == "new_ccd":
                L.append("The full run sheet is in `next CCD/run_sheet.xlsx`.\n")

    # runs outside the fit, drift
    if T["controls"]:
        L.append("\n## Controls against the centre runs\n")
        L.append("A control sits outside the design (e.g. no rotation); it is compared with the centre runs, which "
                 "differ from it only in that factor.\n")
        L.append(md_table(["Run", "Differs in", "Response", "Value", "Centres (mean ± SD, n)", "Difference in SDs"],
                          [[c["run"][:6], c["differs from the centre in"], _short(c["response"]), fmt(c["value"], 4),
                            (f"{fmt(c.get('centre mean'), 4)} ± {fmt(c.get('centre SD'), 2)}, {c['centre runs']}"
                             if c.get("centre mean") is not None else "–"),
                            fmt(c.get("difference in centre SDs"), 2)] for c in T["controls"]]))
    L.append("\n## Runs kept out of the fit\n")
    if T["predictions"]:
        L.append(_img(figs, "fig_rsm_validation", "Validation runs"))
        L.append(md_table(["Response", "Run", "Type", "Observed", "Predicted", "95% PI", "Inside", "Extrapolated"],
                          [[p["response"], p["run"][:6], p["point type"], fmt(p["observed"], 4), fmt(p["predicted"], 4),
                            f"{fmt(p['PI low'], 4)} to {fmt(p['PI high'], 4)}", p["inside the 95% PI"], p["extrapolated"]]
                           for p in T["predictions"]]))
    else:
        L.append("None: every run is in the fit.\n")
    L.append("\n## Drift\n")
    L.append(_img(figs, "fig_rsm_drift", "Drift"))
    if T["block_repeats"]:
        big = [p for p in T["block_repeats"] if p["in SDs of pure error"] is not None and abs(p["in SDs of pure error"]) > 2]
        L.append(f"Repeated settings inside a block, last minus first, in standard deviations of the run-to-run noise "
                 f"(about 1 in 20 beyond ±2 by chance): {len(big)} of {len(T['block_repeats'])} beyond ±2. "
                 f"Per run in the workbook (*Block repeats*).\n")
    for key in HEADLINE:
        fr = R.fits.get(key)
        if fr is not None and fr.residual_trend is not None and fr.residual_trend.p is not None:
            t = fr.residual_trend
            L.append(f"- {_short(fr.label)}: residuals against time {t.slope_per_h:+.3g} per hour, {fmt_p(t.p)}.")
    L.append("")

    # caveats and terms
    L.append("## Caveats\n")
    L += [f"- {c}" for c in caveats(models)]
    L.append("\n## How to read it\n")
    L += ["- **Coded units**: each factor runs from −1 (low) to +1 (high); a coefficient is the change in the response "
          "for that factor moving from the middle to the high level.",
          "- **R²** is the share of the run-to-run spread the model explains; **predicted R²** the same for a run the "
          "model has not seen (from leaving each run out in turn), the honest one.",
          "- **Lack of fit** compares what the model misses with the noise between repeats: significant means the "
          "surface does not describe the data.",
          "- **q (BH)** adjusts p for the number of tests across every response; the simplified model's p-values are "
          "optimistic because the model was chosen by them.",
          "- **VIF** (variance inflation): above about 10 a term is hard to separate from the others.",
          "- **95% prediction interval**: where one new run at that setting should land 95% of the time."]
    L.append("\n## Provenance\n")
    L.append(md_table(["Item", "Value"], [[k, v] for k, v in prov.rows()]))
    return "\n".join(x for x in L if x is not None) + "\n"


def caveats(models: dict) -> list[str]:
    names = list(models)
    R = models[names[0]]
    det = R.loaded.detected
    out = []
    if det.type_key == "oa":
        out.append("These runs are an orthogonal array (a Taguchi L9), not a response-surface design: the surface is "
                   "fitted through nine settings, so it is a sketch to guide the next session, not a substitute for one.")
    for k, label, changes, nl in det.blocks.hard_to_change:
        out.append(f"{label} changed only {changes} time(s) through the session, so it is confounded with time of day.")
    if any(r for r in R.correlations if abs(r[2]) >= 0.5):
        out.append("A nuisance factor tracks a surface term (see the correlations): the two are partly confounded.")
    unsure = [(k, row) for k in HEADLINE for row in interaction_agreement(models, k) if not row["agree"]]
    if unsure:
        out.append("Interactions that change with the model are not separated from the nuisance factor; read only "
                   "the terms the models agree on.")
    if any(str(r.sizer_version) == "2.2.0" for r in R.loaded.runs):
        out.append("Sizer 2.2.0: size responses are of round, sharp droplets, and part of any effect on them is "
                   "selection by the sharpness rule.")
    if any(str(r.sizer_version) == "3.0.0" for r in R.loaded.runs):
        out.append("Sizer 3.0.0: sizes are calibrated on certified glass beads (37-155.8 um, provisional) and count "
                   "only droplets inside the measurement volume; below 37 um the bead table is extrapolated.")
    out.append("The surface is trustworthy inside the tested range only; a best point on an edge needs confirming "
               "runs before anything beyond it is believed.")
    return out
