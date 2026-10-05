"""tables.py -- every table of the analysis as plain rows (list of dicts), built ONCE.

The report, the workbook and the flat CSVs all draw from here, so the three can never
disagree about a number. No Qt, no formatting beyond rounding to a sensible precision for
storage (the report rounds again for reading).
"""
from __future__ import annotations

import math
from typing import Any

from . import covariates


def _r(x: Any, nd: int = 6):
    if x is None:
        return None
    if isinstance(x, float):
        if math.isnan(x):
            return None
        if math.isinf(x):
            return "inf"
        return round(x, nd)
    return x


def _flabel(results, key: str) -> str:
    return next((f.label for f in results.factors if f.key == key), key)


def level_text(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _sorted_runs(results):
    return sorted(results.runs, key=lambda r: (r.condition, r.replicate or 0, r.name))


def per_run(results) -> list[dict]:
    rows = []
    for r in _sorted_runs(results):
        row = {"run": r.name, "condition": r.condition, "replicate": r.replicate}
        for f in results.factors:
            row[f.label] = r.levels.get(f.key)
        for key, res in results.responses.items():
            row[res.label] = _r(r.values.get(key))
            ci = r.ci95.get(key)
            if ci is not None:
                row[f"{res.label} CI low"] = _r(float(ci[0]))
                row[f"{res.label} CI high"] = _r(float(ci[1]))
        c = r.context
        row["GLR"] = _r(c.glr) if c else None
        row["GLR source"] = c.glr_source if c else "missing"
        row["frames"] = r.frames
        row["sizer version"] = r.sizer_version or "pre-2.0.0"
        rows.append(row)
    return rows


def design_matrix(results) -> list[dict]:
    rows = []
    for r in _sorted_runs(results):
        row = {"run": r.name, "condition": r.condition, "replicate": r.replicate}
        row.update({f.label: r.levels.get(f.key) for f in results.factors})
        rows.append(row)
    return rows


def main_effects(results) -> list[dict]:
    rows = []
    for key, res in results.responses.items():
        for f in results.factors:
            for e in res.effects.get(f.key, []):
                rows.append({"response": res.label, "factor": f.label, "level": e.level, "runs": e.n,
                             "mean": _r(e.mean), "SE": _r(e.se),
                             "bootstrap CI low": _r(e.ci95[0]) if e.ci95 else None,
                             "bootstrap CI high": _r(e.ci95[1]) if e.ci95 else None})
    return rows


def _q_lookup(results) -> dict:
    return {(rk, fk): q for rk, fk, _p, q in results.multiple}


def anova_rows(results) -> list[dict]:
    q = _q_lookup(results)
    out = []
    for key, res in results.responses.items():
        a = res.anova
        if a is None:
            out.append({"response": res.label, "source": "(no ANOVA)",
                        "note": "no variation in this response" if res.degenerate else "too few runs"})
            continue
        for f in results.factors:
            r = a.rows.get(f.key)
            if r is None:
                continue
            out.append({"response": res.label, "source": f.label, "SS": _r(r.ss), "df": r.df,
                        "MS": _r(r.ms), "F": _r(r.F), "p": _r(r.p, 8), "q (BH)": _r(q.get((key, f.key)), 8),
                        "contribution %": _r(r.contribution_pct, 3),
                        "pooled contribution %": _r(r.pooled_contribution_pct, 3), "note": r.note})
        if a.lack_of_fit is not None:
            r = a.lack_of_fit
            out.append({"response": res.label, "source": "lack of fit", "SS": _r(r.ss), "df": r.df,
                        "MS": _r(r.ms), "F": _r(r.F), "p": _r(r.p, 8),
                        "contribution %": _r(100 * r.ss / a.total_ss if a.total_ss else None, 3),
                        "note": "significant = interactions matter"})
        if a.error is not None:
            r = a.error
            out.append({"response": res.label, "source": f"error ({a.error_source})", "SS": _r(r.ss),
                        "df": r.df, "MS": _r(r.ms), "contribution %": _r(r.contribution_pct, 3)})
        out.append({"response": res.label, "source": "total", "SS": _r(a.total_ss), "df": a.total_df})
    return out


def sn_rows(results) -> list[dict]:
    rows = []
    for key, res in results.responses.items():
        if not res.sn_defined:
            if res.anova is not None:
                rows.append({"response": res.label, "factor": "", "level": "", "S/N mean (dB)": None,
                             "note": res.sn_note})
            continue
        for f in results.factors:
            for level, v in res.sn_effects.get(f.key, {}).items():
                rows.append({"response": res.label, "factor": f.label, "level": level,
                             "S/N mean (dB)": _r(v, 4), "note": ""})
    return rows


def sn_by_condition(results) -> list[dict]:
    rows = []
    for key, res in results.responses.items():
        for cond, eta in res.sn_by_condition.items():
            rows.append({"response": res.label, "direction": f"{res.direction} is better",
                         "condition": cond, "S/N (dB)": _r(eta, 4)})
    return rows


def size_bins_rows(bins, measure: str, by: str = "run") -> list[dict]:
    return bins.table(measure, by) if bins is not None else []


def glr_context(results) -> list[dict]:
    rows = []
    for r in _sorted_runs(results):
        c = r.context or covariates.RunContext()
        rows.append({"run": r.name, "condition": r.condition, "GLR": _r(c.glr, 5),
                     "GLR source": c.glr_source, "GLR (achieved gas flow)": _r(c.glr_achieved, 5),
                     "liquid flow (mL/min)": _r(c.liquid_ml_min, 4), "fluid": c.fluid, "gas": c.gas,
                     "liquid density (kg/m3)": c.rho_liquid, "gas density (kg/m3)": c.rho_gas,
                     "achieved gas flow (sccm)": _r(c.achieved_sccm, 2),
                     "peak pressure (barA)": c.peak_pressure_bar, "note": c.note})
    return rows


def glr_trends(results) -> list[dict]:
    labels = dict(covariates.COVARIATES)
    rows = []
    for (rk, ck), t in results.trends.items():
        res = results.responses.get(rk)
        rows.append({"response": res.label if res else rk, "against": labels.get(ck, ck), "runs": t.n,
                     "r": _r(t.r, 4), "p": _r(t.p, 8), "power-law exponent": _r(t.exponent, 4),
                     "exponent CI low": _r(t.exponent_ci95[0], 4) if t.exponent_ci95 else None,
                     "exponent CI high": _r(t.exponent_ci95[1], 4) if t.exponent_ci95 else None,
                     "R2 (log-log)": _r(t.r2_power, 4), "note": t.note})
    return rows


def outliers(results) -> list[dict]:
    return [{"response": res.label, "run": o["run"], "condition": o["condition"],
             "value": _r(o["value"]), "condition mean": _r(o["condition_mean"]), "SD of noise": _r(o["z"], 2)}
            for res in results.responses.values() for o in res.outliers]


def skipped(results) -> list[dict]:
    return [{"run": n, "why": w} for n, w in results.skipped]


def all_tables(results, bins) -> dict[str, list[dict]]:
    """name -> rows, for the CSV pack and the workbook."""
    return {
        "per_run": per_run(results),
        "design_matrix": design_matrix(results),
        "main_effects": main_effects(results),
        "anova": anova_rows(results),
        "sn_ratios": sn_rows(results),
        "sn_by_condition": sn_by_condition(results),
        "size_bins_count": size_bins_rows(bins, "count"),
        "size_bins_volume": size_bins_rows(bins, "volume"),
        "size_bins_count_by_condition": size_bins_rows(bins, "count", "condition"),
        "size_bins_volume_by_condition": size_bins_rows(bins, "volume", "condition"),
        "glr_context": glr_context(results),
        "glr_trends": glr_trends(results),
        "replicate_outliers": outliers(results),
        "skipped_runs": skipped(results),
    }
