"""rsm_report.py -- the response-surface tables and rsm_report.md. No Qt.

Every number comes from rsm_responses / rsm_stats results and is put into tables ONCE (tables()),
which the report, the workbook and the CSVs all draw from, so they cannot disagree (the Taguchi
report's rule). Wording is restrained the same way: p < 0.05 is "evidence", a simplified model's
p-values are flagged as optimistic, and a term whose estimate changes between models is said to be
not separated from what the models treat differently.
"""
from __future__ import annotations

import math

import numpy as np

from . import rsm_detect as rdet
from . import rsm_stats as rs
from .report import fmt, fmt_p, md_table

ALPHA = 0.05
HEADLINE = ("atom", "d32", "af_flow", "cv_droplets")
NEXT_RUN_STEP = {"sccm": 100, "sps": 100, "rpm": 50, "orifice": None, "bh": 0.1}    # setpoint resolution
# rsm_results.csv: the column names the CCD plan's own analysis code reads
CSV_NAMES = {"atom": "af", "d32": "d32", "d_mean": "mean_d", "d_median": "median_d", "d90": "d90_count",
             "per_frame": "infocus_per_frame", "cv_droplets": "count_cv", "cv_liquid": "liquid_cv",
             "intermit_pct": "near_empty_pct", "dv50": "dv50", "af_flow": "af_flow", "thin_pct": "thin_pct",
             "lag1": "lag1", "peak_bar": "peak_bar"}
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
    return rs.stationary(fr.reduced, R.axis, fixed)


def optimum_by_hold(R) -> list[tuple[dict, rs.Optimum]]:
    """The desirability optimum at every held level of the nuisance factors (the maps' panels)."""
    from . import rsm_figures as rf
    out = []
    for hold in rf._hold_sets(R):
        o = rf._optimum_at(R, hold)
        if o is not None:
            out.append((hold, o))
    return out


def next_runs(R, best: tuple[dict, rs.Optimum] | None, n_confirm: int = 3) -> list[dict]:
    """Confirmation runs at the optimum (rounded to what can be set), plus one anchor repeat at the
    design centre. The full recommender (moving the region, augmenting the model) is Phase 6."""
    from .rsm_design import RIG_LIMITS
    if best is None:
        return []
    hold, o = best
    setting = {}
    for k in R.axis:
        v = R.decode(k, o.coded[k])
        step = NEXT_RUN_STEP.get(k)
        v = round(v / step) * step if step else v
        lo, hi = RIG_LIMITS.get(k, (-math.inf, math.inf))
        setting[k] = min(max(v, lo), hi)
    setting.update(hold)
    rows = [{"run": i + 1, "why": "confirmation at the optimum", **{_flabel(R, k): v for k, v in setting.items()}}
            for i in range(n_confirm)]
    centre = {f.key: f.centre for f in R.loaded.detected.factors}
    rows.append({"run": n_confirm + 1, "why": "anchor: repeat of the design centre (links the sessions)",
                 **{_flabel(R, k): v for k, v in centre.items()}})
    return rows


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
               "in fit": "yes" if r.point.in_fit else ("validation" if r.point.validation else "no"),
               "block": r.point.block or ""}
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
        st.append(d)
    out["stationary_points"] = st

    opt = []
    for n, M in models.items():
        for hold, o in optimum_by_hold(M):
            d = {"model": n, "held at": ", ".join(f"{_short(_flabel(M, k))} {v:g}" for k, v in hold.items()) or "-",
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
    best = max(optimum_by_hold(R), key=lambda ho: ho[1].D, default=None)
    out["next_runs"] = next_runs(R, best)
    out["design"] = [{"level": f.level, "finding": f.text} for f in det.findings]
    return out


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
        rows.append(d)
    return rows


def _r(x, nd: int = 6):
    if x is None:
        return None
    x = float(x)
    return None if not math.isfinite(x) else round(x, nd)


# ---- the report -------------------------------------------------------------------------------------------------

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
    fitq = (f"the model explains {100 * f.r2:.0f}% of the run-to-run spread (predicted R² {f.r2_pred:.2f})"
            if f.r2 is not None and f.r2_pred is not None else "")
    lofq = ("" if lof is None or lof.p is None else
            (f"; lack of fit is significant (p = {lof.p:.3f}): the surface misses something" if lof.p < ALPHA
             else f"; no evidence of lack of fit (p = {lof.p:.2f})"))
    out.append(f"**{fr.label}** " + ("; ".join(lin) if lin else "shows no clear slope along the axis factors")
               + (f", and curves ({', '.join(curv)} significant)" if curv else "") + f". {fitq[:1].upper()}{fitq[1:]}{lofq}.")
    s = stationary_points(R, key)
    if s is not None:
        out.append(f"  - {stationary_text(R, key, s)}")
    return out


def stationary_text(R, key: str, s) -> str:
    """The fitted surface's stationary point in words, by its kind and the response's direction."""
    fr = R.fits[key]
    where = ", ".join(f"{_short(_flabel(R, k))} {R.decode(k, c):.4g}" for k, c in s.coded.items())
    ridge = " (nearly a ridge: along one direction it barely changes)" if "ridge" in s.kind else ""
    good = (s.kind.startswith("maximum") and fr.direction == "larger") or \
           (s.kind.startswith("minimum") and fr.direction == "smaller")
    inside = "inside the tested range" if s.inside else "outside the tested range"
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


def build(models: dict, prov, figure_files=(), title: str = "Response-surface analysis") -> str:
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
        where = ", ".join(f"{_short(_flabel(R, k))} {R.decode(k, o.coded[k]):.4g}" for k in R.axis)
        held = ", ".join(f"{_short(_flabel(R, k))} {v:g}" for k, v in hold.items())
        L.append(f"- **Best overall setting** (desirability D = {o.D:.2f}): {where}" + (f" at {held}" if held else "")
                 + (f". It sits on the edge of the tested range for {', '.join(_short(_flabel(R, k)) for k in o.on_edge)}:"
                    f" the best point may lie beyond it, so confirm before going further." if o.on_edge else "."))
        for k, (up, down) in tradeoffs(R, o).items():
            if up and down:
                L.append(f"  - The trade-off on {_short(_flabel(R, k)).lower()}: {', '.join(up)} would rather it went "
                         f"up; {', '.join(down)} would rather it went down. The combined score settles at "
                         f"{R.decode(k, o.coded[k]):.4g}.")
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
    if T["correlations"]:
        L.append("\n**Nuisance terms that track surface terms** (partial confounding: the two cannot be fully "
                 "separated)\n")
        L.append(md_table(["Model", "Nuisance", "Surface term", "r"],
                          [[c["model"], c["nuisance"], c["axis term"], f"{c['r']:+.2f}"] for c in T["correlations"]]))
    L.append("")

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
        L.append(_img(figs, f"fig_rsm_contour_{key}", f"{fr.label} contour map"))
        L.append(_img(figs, f"fig_rsm_surface_{key}", f"{fr.label} 3D surface"))
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
    L.append(_img(figs, "fig_rsm_desirability", "Desirability"))
    L.append(_img(figs, "fig_rsm_profiler", "Prediction profiler"))
    L.append("Desirability scores each goal from 0 (unacceptable) to 1 (ideal) and takes the geometric mean, so no goal "
             "can be traded away completely. The goals and their ramps:\n")
    L.append(md_table(["Response", "Aim", "0 at", "1 at"],
                      [[g["response"], g["aim"], fmt(g["0 at"]), fmt(g["1 at"])] for g in T["goals"]]))
    if T["constraints"]:
        L.append(md_table(["Constraint", "At least", "At most"],
                          [[c["response"], fmt(c["at least"]), fmt(c["at most"])] for c in T["constraints"]]))
    else:
        L.append("\nNo hard constraints (there is no rated pressure limit; peak pressure is reported, not limited).\n")
    head = ["Model", "Held at", "D"] + [_flabel(R, k) for k in R.axis] + ["On the edge of"]
    L.append(md_table(head, [[o["model"], o["held at"], fmt(o["desirability D"], 3)] +
                             [fmt(o[_flabel(R, k)], 5) for k in R.axis] + [o["on the edge of"] or "–"]
                             for o in T["optimum"]]))
    if T["stationary_points"]:
        L.append("\n**Where each fitted surface peaks** (simplified model, nuisance factors at their centre)\n")
        L.append(md_table(["Response", "Kind", "Inside the range"] + [_flabel(R, k) for k in R.axis] + ["Fitted value"],
                          [[s["response"], s["kind"], s["inside the tested range"]] +
                           [fmt(s.get(_flabel(R, k)), 5) for k in R.axis] + [fmt(s["fitted value there"], 4)]
                           for s in T["stationary_points"]]))
    if T["next_runs"]:
        L.append("\n**Suggested next runs** (confirmation at the best setting, plus a centre repeat to link the sessions; "
                 "the full recommender, which can also move the region, comes later)\n")
        cols = [c for c in T["next_runs"][0] if c not in ("run",)]
        L.append(md_table(["Run"] + cols, [[r["run"]] + [fmt(r[c], 5) if isinstance(r[c], float) else r[c]
                                                         for c in cols] for r in T["next_runs"]]))

    # runs outside the fit, drift
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
    out.append("The surface is trustworthy inside the tested range only; a best point on an edge needs confirming "
               "runs before anything beyond it is believed.")
    return out
