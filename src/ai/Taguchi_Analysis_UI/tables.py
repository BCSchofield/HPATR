"""tables.py -- every table of the analysis as plain rows (list of dicts), built ONCE.

The report, the workbook and the flat CSVs all draw from here, so the three can never
disagree about a number. No Qt, no formatting beyond rounding to a sensible precision for
storage (the report rounds again for reading).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import covariates, run_metrics


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


# ---- the richer outputs: size percentiles, steadiness, pieces, data quality, per-condition summary ----

def _conditions(results) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in _sorted_runs(results):
        out.setdefault(r.condition, []).append(r)
    return out


def _cond_levels(results, runs) -> dict:
    return {f.label: runs[0].levels.get(f.key) for f in results.factors}


def _size_row(d) -> dict:
    """The size columns from in-focus diameters (one run, or a condition's pooled droplets)."""
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    if d.size == 0:
        return {"droplets": 0}
    v = d ** 3
    dv10, dv50, dv90 = run_metrics.volume_percentiles(d)
    return {"droplets": int(d.size), "D10 (um)": _r(float(d.mean()), 4),
            "D32 (um)": _r(float(v.sum() / (d ** 2).sum()), 4),
            "Dv10 (um)": _r(dv10, 4), "Dv50 (um)": _r(dv50, 4), "Dv90 (um)": _r(dv90, 4),
            "span": _r((dv90 - dv10) / dv50, 4) if dv50 else None,
            f"% volume < {run_metrics.SMALL_UM:g} um": _r(float(100 * v[d < run_metrics.SMALL_UM].sum() / v.sum()), 3),
            f"% volume > {run_metrics.LARGE_UM:g} um": _r(float(100 * v[d > run_metrics.LARGE_UM].sum() / v.sum()), 3)}


def in_focus_diameters(r) -> np.ndarray:
    dia = (r.rec or {}).get("dia") or {}
    parts = [np.asarray(v, float) for v in dia.values() if len(v)]
    return np.concatenate(parts) if parts else np.empty(0)


def size_percentiles(results) -> list[dict]:
    return [{"run": r.name, "condition": r.condition, **_size_row(in_focus_diameters(r))}
            for r in _sorted_runs(results)]


def size_percentiles_by_condition(results) -> list[dict]:
    """Each condition's replicates POOLED as one population (as size_bins does), not averaged."""
    rows = []
    for c, rs in _conditions(results).items():
        pooled = np.concatenate([in_focus_diameters(r) for r in rs]) if rs else np.empty(0)
        rows.append({"condition": c, **_cond_levels(results, rs), "runs": len(rs), **_size_row(pooled)})
    return rows


def steadiness(results) -> list[dict]:
    rows = []
    for r in _sorted_runs(results):
        st = (r.metrics or {}).get("steadiness") or {}
        pr = (r.metrics or {}).get("pressure") or {}
        lag = st.get("lag_r") or {}
        rows.append({"run": r.name, "condition": r.condition, "frames": st.get("frames"),
                     "analysed fps": _r(st.get("fs_hz"), 4),
                     "droplets per frame (all)": _r(st.get("count_mean"), 4),
                     "droplet-count CV": _r(st.get("count_cv"), 4),
                     "frames below half mean (%)": _r(st.get("thin_pct"), 4),
                     **{f"lag-{k} r": _r(lag.get(k), 4) for k in ("1", "2", "4", "8", "16")},
                     f"slow share < {run_metrics.SLOW_HZ:g} Hz (%)": _r(st.get("slow_share_pct"), 4),
                     "slow share if white noise (%)": _r(st.get("slow_share_noise_pct"), 4),
                     "slow peak (Hz)": _r(st.get("slow_peak_hz"), 4),
                     "liquid-area CV": _r(st.get("liquid_cv"), 4),
                     "pressure in camera window (barA)": _r(pr.get("pressure_mean"), 5),
                     "pressure CV (%)": _r(pr.get("pressure_cv_pct"), 4),
                     "gas-flow CV (%)": _r(pr.get("gas_flow_cv_pct"), 4),
                     "r pressure vs droplets": _r(pr.get("r_pressure_droplets"), 4),
                     "peak pressure (barA)": _r((r.metrics or {}).get("peak_bar"), 5),
                     "note": pr.get("note", "")})
    return rows


def liquid_pieces(results) -> list[dict]:
    rows = []
    for r in _sorted_runs(results):
        pc = (r.metrics or {}).get("pieces") or {}
        rows.append({"run": r.name, "condition": r.condition, "pieces": pc.get("n"),
                     "pieces per frame": _r(pc.get("per_frame"), 4),
                     "median area (px)": _r(pc.get("median_px"), 4), "p90 area (px)": _r(pc.get("p90_px"), 4),
                     "largest area (px)": _r(pc.get("largest_px"), 4),
                     "median area (mm2)": _r(pc.get("median_mm2"), 4),
                     "largest area (mm2)": _r(pc.get("largest_mm2"), 4)})
    return rows


# data-quality columns that are checked for odd runs: (column, metrics path)
QUALITY_COLUMNS = (
    ("moved by sharpness rule (% of in-focus)", ("quality", "moved_pct_of_in_focus")),
    ("out-of-focus share (%)", None),
    ("detections per frame", ("quality", "detections_per_frame")),
    ("background median (counts)", ("quality", "bg_median")),
    ("dark specks in background (%)", ("quality", "dark_speck_pct")),
    ("static detection spots", ("quality", "static_spots")),
)
QUALITY_Z = 3.5                  # robust z (median / 1.4826 MAD) beyond which a run is flagged


def _quality_values(r) -> dict:
    q = (r.metrics or {}).get("quality") or {}
    out = {}
    for col, path in QUALITY_COLUMNS:
        if path is None:
            n_in, n_oof = q.get("in_focus"), q.get("out_of_focus")
            out[col] = 100 * n_oof / (n_in + n_oof) if n_in is not None and n_oof is not None and (n_in + n_oof) else None
        else:
            out[col] = q.get(path[1])
    return out


def quality_flags(results) -> dict[str, list[dict]]:
    """Run name -> the data-quality checks where it is far from the other runs (robust z), as
    {"column", "value", "typical" (the median run), "z"}. A check whose runs barely vary (MAD 0)
    flags nothing."""
    vals = {r.name: _quality_values(r) for r in results.runs}
    flags: dict[str, list[dict]] = {n: [] for n in vals}
    for col, _ in QUALITY_COLUMNS:
        xs = {n: v[col] for n, v in vals.items() if v.get(col) is not None}
        if len(xs) < 5:
            continue
        a = np.array(list(xs.values()), float)
        med = float(np.median(a))
        mad = 1.4826 * float(np.median(np.abs(a - med)))
        if mad <= 0:
            continue
        for n, x in xs.items():
            z = (x - med) / mad
            if abs(z) > QUALITY_Z:
                flags[n].append({"column": col, "value": x, "typical": med, "z": z})
    return flags


def flag_text(f: dict) -> str:
    return f"{f['column']}: {f['value']:.3g} (typical run {f['typical']:.3g}, robust z {f['z']:+.0f})"


def data_quality(results) -> list[dict]:
    flags = quality_flags(results)
    rows = []
    for r in _sorted_runs(results):
        q = (r.metrics or {}).get("quality") or {}
        row = {"run": r.name, "condition": r.condition, "sizer version": q.get("sizer_version") or r.sizer_version,
               "in-focus droplets": q.get("in_focus"), "out-of-focus droplets": q.get("out_of_focus"),
               "moved by sharpness rule": q.get("moved_by_rule")}
        row.update({k: _r(v, 4) if isinstance(v, float) else v for k, v in _quality_values(r).items()})
        row["flags"] = "; ".join(flag_text(f) for f in flags.get(r.name, []))
        missing = (r.metrics or {}).get("missing") or {}
        row["missing inputs"] = "; ".join(f"{k}: {v}" for k, v in missing.items())
        rows.append(row)
    return rows


def condition_summary(results) -> list[dict]:
    """Every analysed response per condition: mean, repeat SD and the 95% CI of the mean
    (Student t on the replicates: run-to-run variation, unlike the frame-bootstrap CIs)."""
    from . import stats
    rows = []
    for c, rs in _conditions(results).items():
        for key, res in results.responses.items():
            v = np.array([r.values[key] for r in rs if r.values.get(key) is not None
                          and math.isfinite(r.values[key])], float)
            row = {"condition": c, **_cond_levels(results, rs), "response": res.label, "runs": int(v.size),
                   "mean": _r(float(v.mean())) if v.size else None, "repeat SD": None,
                   "CI low": None, "CI high": None}
            if v.size >= 2:
                sd = float(v.std(ddof=1))
                half = stats.t_quantile(0.05, v.size - 1) * sd / math.sqrt(v.size)
                row.update({"repeat SD": _r(sd), "CI low": _r(float(v.mean()) - half),
                            "CI high": _r(float(v.mean()) + half)})
            rows.append(row)
    return rows


def residuals(results) -> list[dict]:
    """Each run's value, its main-effects fit and the residual, per response, with capture time."""
    from . import stats
    hours = stats.run_hours(results)
    rows = []
    for key, res in results.responses.items():
        fit = stats.main_effects_fit(results, key)
        if fit is None:
            continue
        for r, y, f, e, z in zip(fit.runs, fit.y, fit.fitted, fit.resid, fit.std_resid):
            rows.append({"response": res.label, "run": r.name, "condition": r.condition,
                         "hours from first run": _r(hours.get(r.name), 4), "value": _r(float(y)),
                         "fitted (main effects)": _r(float(f)), "residual": _r(float(e)),
                         "standardised residual": _r(float(z), 3)})
    return rows


def drift_rows(results) -> list[dict]:
    from . import stats
    return [{"response": results.responses[d.key].label, "runs": d.n, "residual slope per hour": _r(d.slope_per_h),
             "SE": _r(d.se), "p": _r(d.p, 8), "q (BH)": _r(q, 8), "r": _r(d.r, 4)}
            for d, q in stats.drifts(results)]


def response_correlations(results) -> list[dict]:
    keys = [k for k, res in results.responses.items() if res.anova is not None]
    vals = {k: np.array([r.values.get(k) if r.values.get(k) is not None else np.nan
                         for r in results.runs], float) for k in keys}
    rows = []
    for a in keys:
        row = {"response": results.responses[a].label}
        for b in keys:
            m = np.isfinite(vals[a]) & np.isfinite(vals[b])
            ok = m.sum() >= 3 and vals[a][m].std() > 0 and vals[b][m].std() > 0
            row[results.responses[b].label] = _r(float(np.corrcoef(vals[a][m], vals[b][m])[0, 1]), 3) if ok else None
        rows.append(row)
    return rows


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
        "condition_summary": condition_summary(results),
        "size_percentiles": size_percentiles(results),
        "size_percentiles_by_condition": size_percentiles_by_condition(results),
        "steadiness": steadiness(results),
        "drift": drift_rows(results),
        "residuals": residuals(results),
        "response_correlations": response_correlations(results),
        "liquid_pieces": liquid_pieces(results),
        "data_quality": data_quality(results),
        "skipped_runs": skipped(results),
    }
