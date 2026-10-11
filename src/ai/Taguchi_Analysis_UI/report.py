"""report.py -- taguchi_report.md, written for someone reading it cold.

Order: what was found (plain words) -> the design -> each response in full -> size spread ->
GLR -> odd runs and what was left out -> how to read the statistics -> provenance. Every
number comes from tables.py / stats.py; nothing is recomputed here, so the report cannot
disagree with the workbook.

Significance wording is deliberately restrained: p < 0.05 is called "evidence", never "proof";
with several dozen tests the report says how many false alarms to expect; and "not significant"
is never worded as "no effect" (a 9-run design can only detect large effects).
"""
from __future__ import annotations

import math
from pathlib import Path

from . import covariates, run_metrics, size_bins, stats, tables

ALPHA = 0.05
HEADLINE = ("d32", "d_mean", "atom")          # figures.HEADLINE
CONFOUNDED_R = 0.5             # |r| between a factor's level and capture time worth a warning
OUTLIER_STD = 3.0              # standardised residuals listed in the model checks
SUMMARY_KEYS = ("d32", "atom", "dv50", "af_flow", "per_frame", "cv_droplets", "thin_pct", "lag1", "peak_bar")


def fmt(x, nd: int = 4) -> str:
    if x is None:
        return "\u2013"
    if isinstance(x, str):
        return x
    if isinstance(x, int):
        return str(x)
    if math.isinf(x):
        return "\u221e"
    if x != 0 and abs(x) < 10 ** -nd:
        return f"{x:.2e}"
    return f"{x:.{nd}g}" if abs(x) < 1000 else f"{x:,.0f}"


def fmt_p(p) -> str:
    if p is None:
        return "\u2013"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def p_eq(p) -> str:
    """'p = 0.028' / 'p < 0.001' (never 'p = <0.001')."""
    if p is None:
        return "p = \u2013"
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def md_table(header: list[str], rows: list[list]) -> str:
    if not rows:
        return ""
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(esc(h) for h in header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _q(results) -> dict:
    return {(rk, fk): q for rk, fk, _p, q in results.multiple}


# ---- sections ----------------------------------------------------------------------------------------------

def _findings(results, bins) -> list[str]:
    out = []
    q = _q(results)
    for key in HEADLINE:
        res = results.responses.get(key)
        if res is None:
            continue
        if res.anova is None:
            out.append(f"**{res.label}**: no analysis possible ({'no variation between runs' if res.degenerate else 'too few runs'}).")
            continue
        a = res.anova
        if a.error is None:
            out.append(f"**{res.label}**: the design has no spare degrees of freedom, so effects are shown "
                       f"but cannot be tested.")
            continue
        sig = [(f, a.rows[f.key]) for f in results.factors
               if f.key in a.rows and a.rows[f.key].p is not None and a.rows[f.key].p < ALPHA]
        if res.quantisation_warning:
            out.append(f"**{res.label}**: only {res.n_distinct} distinct values across the runs; it sits on the "
                       f"measurement's pixel lattice, so its p-values are not meaningful. Read the level means only.")
            continue
        if sig:
            parts = []
            for f, r in sorted(sig, key=lambda t: -(t[1].contribution_pct or 0)):
                robust = q.get((key, f.key))
                tag = "" if robust is None or robust < ALPHA else " (does not survive the multiple-test correction)"
                parts.append(f"{f.label} ({p_eq(r.p)}, {fmt(r.contribution_pct, 3)}% of the variation){tag}")
            out.append(f"**{res.label}**: evidence of an effect of " + "; ".join(parts) + ".")
        else:
            out.append(f"**{res.label}**: no factor reaches p < {ALPHA}. With {a.n} runs this means any effect "
                       f"is smaller than the design can detect, not that there is none.")
        if a.lack_of_fit is not None and a.lack_of_fit.p is not None and a.lack_of_fit.p < ALPHA:
            out.append(f"  - Lack of fit is significant ({p_eq(a.lack_of_fit.p)}): the factors acting "
                       f"separately do not explain everything; **interactions are likely**.")
    glr = [(rk, t) for (rk, ck), t in results.trends.items()
           if ck == "glr" and rk in HEADLINE and t.r is not None]
    if glr:
        bits = [f"{results.responses[rk].label}: r = {t.r:+.2f}" + (f", {p_eq(t.p)}" if t.p is not None else "")
                for rk, t in glr]
        out.append("**GLR** (a trend, not a factor): " + "; ".join(bits) + ".")
    drifting = [d for d, q in stats.drifts(results) if q < ALPHA]
    if drifting:
        out.append("**Drift**: " + "; ".join(f"{results.responses[d.key].label} residuals drift "
                                             f"{d.slope_per_h:+.3g} per hour ({p_eq(d.p)}, BH q < {ALPHA})"
                                             for d in drifting) + ".")
    flagged = {n: f for n, f in tables.quality_flags(results).items() if f}
    if flagged:
        out.append(f"**Data quality**: {len(flagged)} run(s) stand out on a data-quality check "
                   f"({', '.join(n[:6] for n in sorted(flagged))}); see *Sizer and data quality*.")
    return out


def _design_section(results, findings) -> str:
    lines = ["## Design\n"]
    conds: dict[str, list] = {}
    for r in results.runs:
        conds.setdefault(r.condition, []).append(r)
    reps = sorted({len(v) for v in conds.values()})
    shape = (f"{len(results.runs)} runs in {len(conds)} conditions"
             + (f", {reps[0]} replicates each" if len(reps) == 1 else f", {reps[0]}\u2013{reps[-1]} replicates (unbalanced)"))
    lines.append(f"{shape}. Error term: **{results.error_source}**"
                 + {"pure error": " \u2013 the spread between replicates of the same condition, which is the "
                                  "right noise estimate and also allows a lack-of-fit test.",
                    "residual": " \u2013 no replicates, so effects are tested against what the main effects leave "
                                "unexplained (this mixes noise with any interactions).",
                    "none": " \u2013 the design is saturated, so effects cannot be tested."}.get(results.error_source, ".")
                 + "\n")
    header = ["Condition"] + [f.label for f in results.factors] + ["Runs"]
    rows = [[c] + [tables.level_text(rs[0].levels[f.key]) for f in results.factors] + [len(rs)]
            for c, rs in conds.items()]
    lines.append(md_table(header, rows))
    if findings:
        lines.append("\n**Checks on the design**\n")
        mark = {"ok": "\u2714", "info": "\u2022", "warn": "\u26a0", "error": "\u2716"}
        bullet = "\u2022"
        lines += [f"- {mark.get(f.level, bullet)} {f.text}" for f in findings]
        lines.append("")
    return "\n".join(lines) + "\n"


def _response_section(results, key, q) -> str:
    res = results.responses[key]
    better = "smaller" if res.direction == "smaller" else "larger"
    lines = [f"### {res.label}\n", f"*{better.capitalize()} is better.*  {res.n_used} runs.\n"]
    if res.anova is None:
        lines.append("No analysis: " + ("the response is the same in every run." if res.degenerate
                                       else "too few runs with a value.") + "\n")
        return "\n".join(lines)
    if res.quantisation_warning:
        lines.append(f"> \u26a0 Only {res.n_distinct} distinct values: this response sits on the pixel lattice, so "
                     f"the p-values below are not meaningful. Use the level means.\n")
    a = res.anova
    rows = []
    for f in results.factors:
        r = a.rows.get(f.key)
        if r is None:
            continue
        rows.append([f.label, fmt(r.ss), fmt(r.df), fmt(r.ms), fmt(r.F, 3), fmt_p(r.p),
                     fmt_p(q.get((key, f.key))), fmt(r.contribution_pct, 3),
                     fmt(r.pooled_contribution_pct, 3), r.note])
    if a.lack_of_fit is not None:
        r = a.lack_of_fit
        rows.append(["lack of fit", fmt(r.ss), fmt(r.df), fmt(r.ms), fmt(r.F, 3), fmt_p(r.p), "\u2013",
                     fmt(100 * r.ss / a.total_ss if a.total_ss else None, 3), "\u2013", ""])
    if a.error is not None:
        r = a.error
        rows.append([f"error ({a.error_source})", fmt(r.ss), fmt(r.df), fmt(r.ms), "\u2013", "\u2013", "\u2013",
                     fmt(r.contribution_pct, 3), "\u2013", ""])
    rows.append(["total", fmt(a.total_ss), fmt(a.total_df), "", "", "", "", "100", "", ""])
    lines.append(md_table(["Source", "SS", "df", "MS", "F", "p", "q (BH)", "% of variation",
                           "% pooled", "Note"], rows))
    for f in results.factors:
        effs = res.effects.get(f.key, [])
        if not effs:
            continue
        lines.append(f"\n**{f.label}: level means**\n")
        lines.append(md_table(["Level", "Runs", "Mean", "SE", "Bootstrap 95% CI"],
                              [[tables.level_text(e.level), e.n, fmt(e.mean), fmt(e.se),
                                (f"{fmt(e.ci95[0])} to {fmt(e.ci95[1])}" if e.ci95 else "\u2013")]
                               for e in effs]))
    if res.sn_defined:
        lines.append("\n**Signal-to-noise** (higher is better, always)\n")
        lines.append(md_table(["Factor", "Level", "S/N mean (dB)"],
                              [[f.label, tables.level_text(l), fmt(v, 4)] for f in results.factors
                               for l, v in res.sn_effects.get(f.key, {}).items()]))
        if res.sn_anova is not None and res.sn_anova.error is not None:
            best = [f"{f.label}: {tables.level_text(max(res.sn_effects[f.key], key=res.sn_effects[f.key].get))}"
                    for f in results.factors if res.sn_effects.get(f.key)]
            lines.append("Best level by S/N \u2013 " + "; ".join(best) + ".\n")
    elif res.sn_note:
        lines.append(f"\n*S/N {res.sn_note}.*\n")
    if res.outliers:
        lines.append("\n**Replicates out of the ordinary**\n")
        lines.append(md_table(["Run", "Condition", "Value", "Condition mean", "SD of noise"],
                              [[o["run"], o["condition"], fmt(o["value"]), fmt(o["condition_mean"]),
                                f"{o['z']:+.1f}"] for o in res.outliers]))
    return "\n".join(lines) + "\n"


def _responses_section(results) -> str:
    q = _q(results)
    keys = [k for k in results.responses]
    head = [k for k in keys if k in HEADLINE]
    rest = [k for k in keys if k not in HEADLINE]
    lines = ["## Results by response\n",
             "The headline responses first (D32, mean diameter, atomised fraction); every other response the "
             "pipeline measures follows.\n"]
    lines += [_response_section(results, k, q) for k in head + rest]
    return "\n".join(lines)


def _size_section(bins, figs: set[str]) -> str:
    if bins is None or not bins.runs:
        return ""
    edges = ", ".join("\u221e" if e == math.inf else f"{e:g}" for e in bins.edges)
    lines = ["## Droplet size spread\n",
             f"In-focus droplets only, binned at {edges} \u00b5m. **% by count** is the share of droplets in each bin; "
             f"**% by volume** is the share of the liquid (\u03a3d\u00b3), which shows where the liquid actually is: a few "
             f"large droplets can outweigh thousands of small ones. Replicates of a condition are pooled as one "
             f"population, not averaged. {size_bins.CAVEAT}\n"]
    for name, title in (("fig_size_spread_count", "by count"), ("fig_size_spread_volume", "by volume")):
        if f"{name}.png" in figs:
            lines.append(f"![Size spread {title}](figures/{name}.png)\n")
    for measure, title in (("count", "% of droplets"), ("volume", "% of liquid volume")):
        rows = bins.table(measure, "condition")
        lines.append(f"\n**{title}, per condition**\n")
        lines.append(md_table(["Condition", "Droplets"] + bins.labels,
                              [[r["condition"], f"{r['droplets']:,}"] + [fmt(r[l], 3) for l in bins.labels]
                               for r in rows]))
    lines.append("\nPer-run tables are in the workbook (sheets *Size bins (count)* and *Size bins (volume)*).\n")
    return "\n".join(lines) + "\n"


def _img(figs: set[str], name: str, caption: str) -> str:
    return f"![{caption}](figures/{name}.png)\n" if f"{name}.png" in figs else ""


def _by_condition(rows: list[dict], cols: list[str]) -> list[list]:
    """Condition means of per-run table rows (keeps the table order)."""
    acc: dict[str, list] = {}
    for r in rows:
        acc.setdefault(r["condition"], []).append(r)
    out = []
    for c, rs in acc.items():
        line = [c]
        for col in cols:
            v = [r[col] for r in rs if isinstance(r.get(col), (int, float)) and math.isfinite(r[col])]
            line.append(fmt(sum(v) / len(v), 3) if v else "\u2013")
        out.append(line)
    return out


def _size_detail_section(results, figs: set[str]) -> str:
    rows = tables.size_percentiles_by_condition(results)
    if not rows or not any(r.get("droplets") for r in rows):
        return ""
    lo, hi = f"% volume < {run_metrics.SMALL_UM:g} um", f"% volume > {run_metrics.LARGE_UM:g} um"
    lines = ["## Droplet size distributions\n",
             "In-focus droplets, each condition's replicates pooled. **Dv10 / Dv50 / Dv90** are the diameters below "
             "which 10 / 50 / 90% of the liquid volume lies; **span** = (Dv90 \u2212 Dv10) / Dv50. Percentiles are "
             "interpolated across the pixel lattice's diameter cells, so they move continuously. "
             f"{size_bins.CAVEAT}\n",
             _img(figs, "fig_size_distribution", "Size distributions per condition"),
             _img(figs, "fig_size_percentiles", "Volume percentiles per run")]
    lines.append(md_table(["Condition", "Droplets", "D10", "D32", "Dv10", "Dv50", "Dv90", "Span",
                           f"% vol < {run_metrics.SMALL_UM:g} \u00b5m", f"% vol > {run_metrics.LARGE_UM:g} \u00b5m"],
                          [[r["condition"], f"{r['droplets']:,}", fmt(r.get("D10 (um)"), 4), fmt(r.get("D32 (um)"), 4),
                            fmt(r.get("Dv10 (um)"), 4), fmt(r.get("Dv50 (um)"), 4), fmt(r.get("Dv90 (um)"), 4),
                            fmt(r.get("span"), 3), fmt(r.get(lo), 3), fmt(r.get(hi), 3)] for r in rows]))
    lines.append("\nPer run: workbook sheet *Size percentiles*.\n")
    return "\n".join(l for l in lines if l) + "\n"


def _steadiness_section(results, figs: set[str]) -> str:
    rows = tables.steadiness(results)
    if not any(r.get("droplets per frame (all)") is not None for r in rows):
        return ""
    slow = f"slow share < {run_metrics.SLOW_HZ:g} Hz (%)"
    noise = next((r["slow share if white noise (%)"] for r in rows if r.get("slow share if white noise (%)")), None)
    cols = ["droplets per frame (all)", "droplet-count CV", "frames below half mean (%)", "lag-1 r", slow,
            "liquid-area CV", "pressure CV (%)", "r pressure vs droplets"]
    lines = ["## Steadiness and pulsing\n",
             "From the droplet count of every frame (in and out of focus, so independent of the sizer version) and the "
             "classical liquid area. **Lag-1 r** is the correlation of each frame's count with the next one's: near 0 "
             "is frame-to-frame noise, high values mean the spray comes and goes in bursts. **Slow share** is the part of "
             f"the count's variance below {run_metrics.SLOW_HZ:g} Hz (Welch spectrum)"
             + (f"; white noise would put about {noise:.0f}% there" if noise else "") + ". **r pressure vs droplets** "
             "correlates the logged upstream pressure with the droplet count inside the camera window.\n",
             _img(figs, "fig_steadiness", "Steadiness by condition"),
             _img(figs, "fig_spectra", "Droplet-count spectra"),
             _img(figs, "fig_series", "Droplets per frame and pressure through each capture"),
             _img(figs, "fig_series_liquid", "Liquid area through each capture")]
    lines.append("**Condition means**\n")
    lines.append(md_table(["Condition", "Droplets/frame", "Count CV", "Frames < half mean %", "Lag-1 r",
                           "Slow share %", "Liquid CV", "Pressure CV %", "r(pressure, droplets)"],
                          _by_condition(rows, cols)))
    lines.append("\nPer run (with lag-2 to lag-16 and the slow peak): workbook sheet *Steadiness*.\n")
    return "\n".join(l for l in lines if l) + "\n"


def _drift_section(results, figs: set[str]) -> str:
    rows = tables.drift_rows(results)
    if not rows:
        return ""
    conf = stats.order_confounding(results)
    lines = ["## Drift, replicates and interactions\n",
             "A check for anything that changes slowly through a session (window dirt, gas supply, the silicone, "
             "nozzle fouling), on what the factors leave unexplained: each response's main-effects residuals against "
             "capture time (straight line, slope per hour), with BH q across the responses.\n"]
    if conf:
        lines.append("Factor level against capture time: " + "; ".join(
            f"{f} r = {r:+.2f}" + (" (**confounded with time of day**)" if abs(r) >= CONFOUNDED_R else "")
            for f, r in conf) + ". A drift that follows a confounded factor appears as that factor's effect, "
            "not as residual drift.\n")
    lines.append(_img(figs, "fig_drift", "Responses against capture time"))
    lines.append(md_table(["Response", "Runs", "Residual slope per hour", "SE", "p", "q (BH)", "r"],
                          [[r["response"], r["runs"], fmt(r["residual slope per hour"], 3), fmt(r["SE"], 3),
                            fmt_p(r["p"]), fmt_p(r["q (BH)"]), fmt(r["r"], 3)] for r in rows]))
    lines.append(_img(figs, "fig_replicates", "Replicates per condition"))
    if "fig_interactions.png" in figs:
        from . import figures_extra
        lines.append(_img(figs, "fig_interactions", "Condition means for each pair of factors"))
        if not figures_extra.is_full_factorial(results):
            lines.append("> The design is fractional: in the interaction plots each point also changes the other "
                         "factor(s), so non-parallel lines can be another factor's main effect. In an L9 every "
                         "two-factor interaction is aliased with the third factor; only the lack-of-fit test (above, "
                         "per response) says whether interactions matter at all.\n")
    return "\n".join(l for l in lines if l) + "\n"


def _diagnostics_section(results, figs: set[str]) -> str:
    if "fig_diagnostics.png" not in figs and "fig_correlations.png" not in figs:
        return ""
    lines = ["## Model checks\n",
             "Residuals of the main-effects model the ANOVA tests against, standardised by the residual standard "
             "deviation and leverage. Points beyond \u00b12 are expected about 1 time in 20; a curved normal plot or a "
             "pattern against the fitted value or time means the model misses something.\n",
             _img(figs, "fig_diagnostics", "Model checks")]
    big = []
    for key in results.responses:
        fit = stats.main_effects_fit(results, key)
        if fit is None:
            continue
        for r, z in zip(fit.runs, fit.std_resid):
            if math.isfinite(z) and abs(z) > OUTLIER_STD:
                big.append([results.responses[key].label, r.name, r.condition, f"{z:+.2f}"])
    if big:
        lines.append(f"\n**Standardised residuals beyond \u00b1{OUTLIER_STD:g}**\n")
        lines.append(md_table(["Response", "Run", "Condition", "Standardised residual"], big))
    lines.append(_img(figs, "fig_correlations", "Response correlations"))
    lines.append("Correlations are across all runs, so they include the factors' own effects: two responses that "
                 "both follow gas flow correlate strongly whether or not one causes the other.\n")
    return "\n".join(l for l in lines if l) + "\n"


def _pieces_section(results, figs: set[str]) -> str:
    rows = tables.liquid_pieces(results)
    if not any(r.get("pieces") for r in rows):
        return ""
    lines = ["## Un-atomised liquid pieces\n",
             "Connected regions of un-atomised liquid in the classical masks (`classical_components.csv`).\n",
             _img(figs, "fig_pieces", "Un-atomised liquid pieces"),
             md_table(["Condition", "Pieces per frame", "Median area (mm\u00b2)", "Largest (mm\u00b2)"],
                      _by_condition(rows, ["pieces per frame", "median area (mm2)", "largest area (mm2)"]))]
    return "\n".join(l for l in lines if l) + "\n"


def _quality_section(results, figs: set[str]) -> str:
    rows = tables.data_quality(results)
    if not rows:
        return ""
    versions = sorted({str(r.get("sizer version")) for r in rows})
    lines = ["## Sizer and data quality\n",
             f"Sizer version: {', '.join(versions)}. Each check is compared across runs with a robust z "
             f"(median and MAD); a run beyond {tables.QUALITY_Z:g} is flagged. **Moved by the sharpness rule** is the "
             "share of round droplets the 2.2.0 rule reclassified as out of focus; **dark specks** is the share of the "
             "median background darker than 75% of its surroundings (dirt on the window or sensor); **static spots** "
             "are places with a droplet detection in at least "
             f"{100 * run_metrics.STATIC_FRAC:.0f}% of frames.\n",
             _img(figs, "fig_quality", "Sizer and data quality")]
    flagged = [(r["run"], r["condition"], r["flags"]) for r in rows if r.get("flags")]
    if flagged:
        lines.append(md_table(["Run", "Condition", "Stands out on"], [list(f) for f in flagged]))
    else:
        lines.append("No run stands out on any check.\n")
    missing = [(r["run"], r["missing inputs"]) for r in rows if r.get("missing inputs")]
    if missing:
        lines.append("\n**Inputs missing** (those parts are blank, the rest is computed)\n")
        lines.append(md_table(["Run", "Missing"], [list(m) for m in missing]))
    return "\n".join(l for l in lines if l) + "\n"


def _condition_summary_section(results) -> str:
    keys = [k for k in SUMMARY_KEYS if k in results.responses and results.responses[k].anova is not None]
    if not keys:
        return ""
    rows = tables.condition_summary(results)
    cell = {(r["condition"], r["response"]): r for r in rows}
    conds = list(dict.fromkeys(r["condition"] for r in rows))
    out = []
    for c in conds:
        line = [c]
        for k in keys:
            r = cell.get((c, results.responses[k].label))
            if r is None or r["mean"] is None:
                line.append("\u2013")
            elif r["CI high"] is None:
                line.append(fmt(r["mean"], 4))
            else:
                line.append(f"{fmt(r['mean'], 4)} \u00b1 {fmt(r['CI high'] - r['mean'], 2)}")
        out.append(line)
    return "\n".join([
        "## Per-condition summary\n",
        "Mean \u00b1 half-width of the 95% confidence interval of the mean, from the replicates (run-to-run "
        "variation, Student t). Every analysed response, with the repeat SD, is in the workbook sheet "
        "*Condition summary*.\n",
        md_table(["Condition"] + [results.responses[k].label for k in keys], out)]) + "\n"


def _gallery_section(results, figure_files) -> str:
    gal = sorted(Path(p) for p in figure_files if Path(p).parent.name == "galleries")
    if not gal:
        return ""
    lines = ["## Images\n",
             "Each run's lowest- and highest-atomised frame (classical overlays: brown = un-atomised liquid, circles = "
             "droplets), one sheet per condition:\n"]
    lines += [f"- [{p.stem.replace('gallery_', '')}](figures/galleries/{p.name})" for p in gal]
    return "\n".join(lines) + "\n"


def _glr_section(results, figs: set[str]) -> str:
    runs_with = [r for r in results.runs if r.context and r.context.glr is not None]
    lines = ["## Gas-to-liquid ratio (GLR)\n"]
    if not runs_with:
        why = next((r.context.note for r in results.runs if r.context and r.context.note), "")
        lines.append(f"No run has a GLR (**{why or 'none recorded'}**), so there is no GLR analysis. "
                     f"Nothing was guessed.\n")
        return "\n".join(lines) + "\n"
    src: dict = {}
    for r in runs_with:
        src[r.context.glr_source] = src.get(r.context.glr_source, 0) + 1
    lines.append(f"{len(runs_with)} of {len(results.runs)} runs have a GLR "
                 f"({', '.join(f'{n} {s}' for s, n in sorted(src.items()))}). *recorded* = written by the capture "
                 f"GUI into run_summary.xlsx; *computed* = the capture GUI's own formula applied to the "
                 f"workbook's flows and densities.\n")
    lines.append(f"> {covariates.CAVEAT}\n")
    if "fig_glr.png" in figs:
        lines.append("![Responses against GLR](figures/fig_glr.png)\n")
    labels = dict(covariates.COVARIATES)
    rows = []
    for (rk, ck), t in results.trends.items():
        res = results.responses.get(rk)
        if res is None or t.r is None:
            continue
        ci = f"{fmt(t.exponent_ci95[0], 3)} to {fmt(t.exponent_ci95[1], 3)}" if t.exponent_ci95 else "\u2013"
        rows.append([res.label, labels.get(ck, ck), t.n, f"{t.r:+.3f}", fmt_p(t.p), fmt(t.exponent, 3), ci,
                     t.note])
    lines.append(md_table(["Response", "Against", "Runs", "r", "p", "Power-law exponent", "Exponent 95% CI",
                           "Note"], rows))
    ctx = {}
    for r in results.runs:
        c = r.context
        if c is not None:
            ctx.setdefault(r.condition, c)
    if ctx:
        lines.append("\n**Run context** (first run of each condition; every run is in the workbook)\n")
        lines.append(md_table(["Condition", "GLR", "Source", "Liquid mL/min", "Fluid", "Gas",
                               "Liquid kg/m\u00b3", "Gas kg/m\u00b3", "Achieved sccm", "Peak barA"],
                              [[k, fmt(c.glr, 4), c.glr_source, fmt(c.liquid_ml_min, 4), c.fluid or "\u2013",
                                c.gas or "\u2013", fmt(c.rho_liquid), fmt(c.rho_gas), fmt(c.achieved_sccm, 5),
                                fmt(c.peak_pressure_bar)] for k, c in ctx.items()]))
    return "\n".join(lines) + "\n"


def _odd_section(results, odd) -> str:
    lines = ["## Odd runs and frames\n"]
    out = tables.outliers(results)
    if out:
        lines.append(f"{len(out)} replicate value(s) are more than 3 standard deviations of replicate noise from "
                     f"their condition's mean (listed under each response above).\n")
    else:
        lines.append("No replicate is out of the ordinary for any response.\n")
    if odd is not None:
        if odd.csv_path is None:
            lines.append(f"Odd-frame pack: {odd.note}.\n")
        else:
            cats = ", ".join(f"{n} {c}" for c, n in sorted(odd.by_category.items()))
            lines.append(f"Odd-frame pack written to `odd/` ({odd.n_flags} flags: {cats}; {odd.n_images} images).  "
                         f"{odd.note}\n")
    return "\n".join(lines) + "\n"


def _left_out_section(results) -> str:
    lines = []
    if results.skipped:
        lines.append("## Runs left out\n")
        lines.append(md_table(["Run", "Why"], [[n, w] for n, w in results.skipped]))
    if results.warnings:
        lines.append("\n## Warnings\n")
        lines += [f"- {w}" for w in results.warnings]
    return "\n".join(lines) + "\n" if lines else ""


def _method_section(results) -> str:
    n_tests = len(results.multiple)
    expect = n_tests * ALPHA
    return "\n".join([
        "## How to read the statistics\n",
        "- **Sums of squares are Type II**, from a least-squares fit of the main effects, so they are correct "
        "for unbalanced designs and equal the classic Taguchi formula for balanced ones.",
        "- **p** tests whether a factor explains more than the error term would by chance. **% of variation** is "
        "that factor's share of the total sum of squares; **% pooled** subtracts the share the error would "
        "contribute by itself (the form Taguchi texts use).",
        f"- **Multiple tests.** {n_tests} factor tests were run. At p < {ALPHA} about {expect:.1f} would come out "
        f"'significant' by chance alone. **q (BH)** is the Benjamini\u2013Hochberg adjusted value; trust a result "
        f"most when q is also below {ALPHA}.",
        "- **Not significant is not 'no effect'.** A small design can only detect large effects.",
        "- **Standard errors** come from the ANOVA error term; **bootstrap intervals** reflect measurement noise "
        "within a run (resampling frames), not run-to-run variation.",
        "- **S/N** with replicates is \u221210\u00b7log10(mean y\u00b2) for smaller-is-better and "
        "\u221210\u00b7log10(mean 1/y\u00b2) for larger-is-better; higher is better. It is undefined when a "
        "response reaches 0.",
        "- **Lack of fit** compares what the main effects miss with the replicate noise; a significant value "
        "means the factors interact.",
    ]) + "\n"


def _provenance_section(prov) -> str:
    return "## Provenance\n\n" + md_table(["Item", "Value"], [[k, v] for k, v in prov.rows()]) + "\n"


# ---- the document -----------------------------------------------------------------------------------------------

def build(results, bins, prov, findings=(), odd=None, figure_files=(), title: str | None = None) -> str:
    figs = {Path(p).name for p in figure_files}
    head = [f"# {title or 'Taguchi analysis'}\n",
            f"{len(results.runs)} runs, {results.n_conditions} conditions \u00b7 generated {prov.generated} \u00b7 "
            f"revision {prov.revision}\n"]
    if results.refused:
        return "\n".join(head + ["## Not analysed\n", results.refused, "", _left_out_section(results)])
    body = ["## What was found\n", *[f"- {l}" for l in _findings(results, bins)], "\n"]
    body.append(_design_section(results, findings))
    for name, cap in (("fig_main_effects", "Main effects"), ("fig_contributions", "What drives each response"),
                      ("fig_per_run", "Every run"), ("fig_sn", "Signal-to-noise")):
        if f"{name}.png" in figs:
            body.append(f"![{cap}](figures/{name}.png)\n")
    body.append(_responses_section(results))
    body.append(_size_section(bins, figs))
    body.append(_size_detail_section(results, figs))
    body.append(_steadiness_section(results, figs))
    body.append(_drift_section(results, figs))
    body.append(_diagnostics_section(results, figs))
    body.append(_pieces_section(results, figs))
    body.append(_quality_section(results, figs))
    body.append(_condition_summary_section(results))
    body.append(_gallery_section(results, figure_files))
    body.append(_glr_section(results, figs))
    body.append(_odd_section(results, odd))
    body.append(_left_out_section(results))
    body.append(_method_section(results))
    body.append(_provenance_section(prov))
    return "\n".join(head + [b for b in body if b]) + "\n"
