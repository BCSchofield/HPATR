"""rsm_deck.py -- rsm_deck.pptx: the response-surface analysis as slides, styled like taguchi_deck.pptx
(Ben's "Atomisation Ink" template, deck._Deck). No Qt.

    title -> design and models -> what was found -> per response: contour map, 3D surface ->
    desirability -> profiler -> best settings (table) -> where each surface peaks -> next runs ->
    fit checks -> model comparison -> runs kept out of the fit -> caveats ->
    appendix: the shared size / steadiness / quality figures and the image galleries

Every figure slide: a takeaway title and a description written from the numbers (rsm_report's
tables and verdicts, so the deck cannot disagree with the report), a Terms card, speaker notes.
"""
from __future__ import annotations

from pathlib import Path

from . import deck as dk
from . import figures_extra, rsm_report, tables
from . import rsm_responses as rr

DEFINE = dict(dk.DEFINE)
DEFINE.update({
    "coded": "Coded units: each factor from −1 (low) to +1 (high); a coefficient is the change from the middle to "
             "the high level.",
    "surface": "Response surface: the fitted quadratic (a slope and a curve per factor, plus interactions) drawn "
               "over the factors.",
    "contour": "Contour map: the fitted surface seen from above; each line joins settings with the same predicted "
               "value.",
    "R2": "R²: share of the run-to-run spread the model explains.",
    "R2 pred": "Predicted R²: the same for runs the model has not seen (each run left out in turn): the honest one.",
    "nuisance": "Nuisance factor: kept in the model so its effect does not bias the others, but not mapped; the "
                "maps hold it at a chosen value.",
    "desirability": "Desirability D: each goal scored 0 (unacceptable) to 1 (ideal), combined as a geometric mean, "
                    "so no goal can be traded away entirely.",
    "sweet spot": "Sweet spot: settings where every goal is at least half met (each score ≥ 0.5).",
    "PI": "95% prediction interval: where one new run at that setting should land 95% of the time.",
    "profiler": "Profiler: each factor swept through the best setting with the others held there.",
    "stationary": "Stationary point: where the fitted surface is flat in every direction: a peak, a trough or a "
                  "saddle.",
    "Pareto": "Standardised effect: |coefficient / SE| = |t|; beyond the dotted line is significant at 5%.",
    "VIF": "VIF (variance inflation): how much a term's uncertainty is inflated by its overlap with the others; "
           "above about 10 it is hard to separate.",
    "simplified": "Simplified model: non-significant terms dropped one at a time, highest order first, keeping a "
                  "slope while its curve or interaction stays.",
})


def defs(*keys: str) -> str:
    return "  ·  ".join(DEFINE[k] for k in keys if k in DEFINE)


def _plain(s: str) -> str:
    return dk._plain(s).strip()


def _f(R, k):
    return rsm_report._flabel(R, k)


def _short(s):
    return s.split(" (")[0]


def _shape_phrase(R, key: str) -> str:
    """'up with gas flow, down with silicone; curved' from the full model's significant terms."""
    f = R.fits[key].full
    bits = []
    for k in R.axis:
        if k in f.terms and f.p_of[k] < rsm_report.ALPHA:
            bits.append(f"{'up' if f.coef()[k] > 0 else 'down'} with {_short(_f(R, k)).lower()}")
    curved = any(t.endswith("^2") and rs_parents(t)[0] in R.axis and f.p_of[t] < rsm_report.ALPHA for t in f.terms)
    return (", ".join(bits) or "no clear slope") + ("; curved" if curved else "")


def rs_parents(t):
    from .rsm_stats import term_parents
    return term_parents(t)


def how_map(R, key: str) -> str:
    from . import rsm_figures as rf
    fr = R.fits[key]
    L = rf.map_layout(R)
    if L is None:
        return ""
    a, b = (_short(_f(R, k)).lower() for k in L.pair)
    better = "higher" if fr.direction == "larger" else "lower"
    bits = [f"{a.capitalize()} runs across, {b} up. Colour is the predicted {_short(fr.label).lower()}: yellow high, "
            f"purple low ({better} is better). White lines join settings with the same prediction; where they bunch "
            f"up the response changes fast."]
    if L.panel:
        bits.append(f"Each panel is one {_short(_f(R, L.panel)).lower()}" +
                    (f"; each slide one {_short(_f(R, L.figure)).lower()}" if L.figure else "") + ".")
    bits.append("Filled circles are runs made at that setting, hollow ones runs made elsewhere; the star is the best "
                "setting for all the goals together on that map.")
    return " ".join(bits)


def how_surface(R, key: str) -> str:
    from . import rsm_figures as rf
    fr = R.fits[key]
    L = rf.map_layout(R)
    if L is None:
        return ""
    a, b = (_short(_f(R, k)).lower() for k in L.pair)
    return (f"The same fitted surface as the map, as a landscape: {a} and {b} along the floor, height and colour the "
            f"predicted {_short(fr.label).lower()}. A dome is a peak inside the range, a bowl a trough, a saddle rises "
            f"one way and falls the other; a flat tilt means the best value is at an edge. Black dots are the measured "
            f"runs at that setting: dots off the surface are what the model misses."
            + (f" One panel per {_short(_f(R, L.panel)).lower()}." if L.panel else ""))


HOW_PAIRS = ("Each small map is one pair of factors (across and up) with every other factor held at the best "
             "setting; colour is the predicted value, the star the best setting. Read a row or a column to see how "
             "one factor plays against each of the others.")
HOW_DESIRABILITY = ("Colour is the overall desirability D for that setting: pale = every goal met well, dark = at "
                    "least one goal poorly met. Hatched areas meet every goal at least halfway (the sweet spot); "
                    "the star is the best D on that map.")
HOW_PROFILER = ("Each column sweeps one factor from low to high with every other factor held at the best setting "
                "(dotted line); each row is one response. The line is the prediction, the dark band its 95% "
                "confidence interval, the light band where a single new run would land 95% of the time.")


def tw_response(R, key: str, what: str):
    fr = R.fits[key]
    f = fr.full
    name = _short(fr.label)
    s = rsm_report.stationary_points(R, key)
    r2p = fr.r2_pred_used                      # the simplified model's: what the maps draw
    weak = r2p is not None and r2p < rr.USABLE_R2_PRED
    r2p_s = "–" if r2p is None else f"{r2p:.2f}"
    if what == "contour":
        title = f"{name}: {_shape_phrase(R, key)}" if not weak else f"{name}: no usable surface (predicted R² {r2p_s})"
    elif s is not None:
        where = ", ".join(f"{rsm_report.num(R.decode(k, c))} {rsm_report._flabel(R, k).split('(')[-1].rstrip(')')}"
                          for k, c in s.coded.items())
        kind = s.kind.split(" (")[0]
        title = f"{name} in 3D: a {kind} {'centred ' if kind == 'saddle' else ''}at {where}" + (
            "" if s.inside else " (outside the range)")
    else:
        title = f"{name} in 3D"
    lof = f.lof
    detail = (f"R² {f.r2:.2f}, predicted R² {r2p_s} (simplified model)"
              + ("" if lof is None or lof.p is None else f", lack of fit p = {lof.p:.2g}") + ". "
              + (rsm_report.stationary_text(R, key, s) if s is not None else ""))
    holds = ", ".join(f"{_short(_f(R, k))} " + "/".join(f"{x:g}" for x in next(fl.levels for fl in
                      R.loaded.detected.factors if fl.key == k)) for k in R.nuisance)
    if holds:
        detail += f" One panel per {holds} (kept in the model, not mapped)."
    if what == "contour":                       # three-panel maps: keep the card short so the maps stay big
        short = ""
        if s is not None:
            where = ", ".join(f"{_short(_f(R, k)).lower()} {rsm_report.num(R.decode(k, c))}" for k, c in s.coded.items())
            short = {"saddle": f" A saddle centred at {where}: the best values are on the edges.",
                     "maximum": f" Highest at {where}.", "minimum": f" Lowest at {where}."}.get(
                s.kind.split(" (")[0], "") + ("" if s.inside or not s.kind else " (outside the range)")
        detail = (f"R² {f.r2:.2f}, predicted R² {r2p_s} (simplified model)"
                  + ("" if lof is None or lof.p is None else f", lack of fit p = {lof.p:.2g}") + "." + short)
        terms = defs("contour", *(("nuisance",) if R.nuisance else ()))
    else:
        terms = defs("surface", "R2 pred", "lack of fit", "stationary", *(("nuisance",) if R.nuisance else ()))
    shows = f"What it shows: {detail}" if detail else ""
    return (title, shows, terms, " ".join(_plain(x) for x in rsm_report._verdict(R, key)),
            how_map(R, key) if what == "contour" else how_surface(R, key))


def tw_desirability(R):
    best = max(rsm_report.optimum_by_hold(R), key=lambda ho: ho[1].D, default=None)
    if best is None:
        return "Desirability", "", defs("desirability", "sweet spot"), ""
    hold, o = best
    where = ", ".join(f"{_short(_f(R, k))} {rsm_report.num(R.decode(k, o.coded[k]))}" for k in R.axis)
    held = ", ".join(f"{_short(_f(R, k))} {v:g}" for k, v in hold.items())
    goals = ", ".join(f"{_short(R.fits[g.key].label).lower()} {'up' if g.direction == 'max' else 'down'}"
                      for g in R.goals)
    dropped = [w.split(": ", 1)[1] for w in R.warnings if w.startswith("left out of the best-settings search")]
    edge = (f" On the edge of the range for {', '.join(_short(_f(R, k)).lower() for k in o.on_edge)}: the best point "
            f"may lie beyond it." if o.on_edge else "")

    def who(names):
        return names[0] + " pulls" if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] + " pull"
    trade = " ".join(f"On {_short(_f(R, k)).lower()}, {who(up)} it up and {who(down)} it down."
                     for k, (up, down) in rsm_report.tradeoffs(R, o).items() if up and down)
    return (f"Best overall: {where}" + (f" at {held}" if held else "") + f" (D = {o.D:.2f})",
            f"Goals: {goals}." + (f" Left out (surface not usable): {dropped[0]}." if dropped else "") + edge,
            defs("desirability", "sweet spot"), trade)


def tw_profiler(R):
    o = R.optimum
    if o is None:
        return "Prediction profiler", "", defs("profiler", "PI"), ""
    preds = "; ".join(f"{_short(R.fits[k].label)} {v:.3g}" for k, v in o.preds.items())
    return ("Each response through the best setting", f"Predicted at the best setting: {preds}.",
            defs("profiler", "PI", "CI"), "")


def tw_fit(R):
    rows = []
    for k in rsm_report.HEADLINE:
        fr = R.fits.get(k)
        if fr is not None and fr.full is not None and fr.r2_pred_used is not None:
            lof = fr.full.lof
            rows.append(f"{_short(fr.label)}: predicted R² {fr.r2_pred_used:.2f}"
                        + ("" if lof is None or lof.p is None else f", lack of fit p = {lof.p:.2g}"))
    bad = [k for k in rsm_report.HEADLINE if k in R.fits and R.fits[k].full is not None and R.fits[k].full.lof
           is not None and R.fits[k].full.lof.p is not None and R.fits[k].full.lof.p < rsm_report.ALPHA]
    title = ("The surfaces fit well" if not bad else
             f"Lack of fit for {', '.join(_short(R.fits[k].label) for k in bad)}; the rest fit well")
    return title, "; ".join(rows) + ".", defs("R2", "R2 pred", "Pareto", "lack of fit", "residual"), ""


def tw_compare(models):
    names = list(models)
    R = models[names[0]]
    moved = []
    for k in rsm_report.HEADLINE:
        for row in rsm_report.interaction_agreement(models, k):
            if not row["agree"]:
                moved.append(f"{rsm_report.term_text(R, row['term'])} on {_short(R.fits[k].label)} ("
                             + "; ".join(f"{n.split(':')[0]} {b:+.2g}, p {p:.2g}" for n, (b, p) in row["by_model"].items())
                             + ")")
    nuis = [_short(_f(R, k)) for k in R.nuisance]
    if moved:
        title = (f"The interaction changes with the model: not separated from {', '.join(nuis) or 'what differs'}")
    else:
        title = "The models agree on every term"
    return title, ("Changes between models: " + "; ".join(moved) + "." if moved else
                   "Every interaction has the same sign and significance in each model."), defs("nuisance", "aliased", "p"), ""


def _table_opt(R, data):
    head = ["Model", "Held at", "D"] + [_short(_f(R, k)) for k in R.axis] + ["Edge"]
    rows = [[o["model"].split(":")[0], o["held at"], f"{o['desirability D']:.2f}"] +
            [rsm_report.num(o[_f(R, k)]) for k in R.axis] + [o["on the edge of"] or "–"] for o in data["optimum"]]
    return head, rows


def build(path: Path, models: dict, prov, figures_dir: Path, title: str = "Response-surface analysis",
          shared=None, bins=None) -> Path:
    figs = Path(figures_dir)
    names = list(models)
    R = models[names[0]]
    det = R.loaded.detected
    data = rsm_report.tables(models)
    d = dk._Deck(f"{title} · generated {prov.generated} · revision {prov.revision}")
    n_fit = sum(1 for r in R.loaded.runs if r.point.in_fit)
    d.title(title, [f"{len(R.loaded.runs)} runs ({n_fit} in the fit) · surface over "
                    + " × ".join(_short(_f(R, k)) for k in R.axis),
                    f"Detected design: {det.design_type}"])
    d.table("The models fitted", ["Model", "Surface over", "Nuisance terms", "Terms"],
            [[n, " × ".join(_short(_f(M, k)) for k in M.axis),
              ", ".join(f"{_short(_f(M, k))} ({h})" for k, h in M.nuisance.items()) or "none", len(M.terms)]
             for n, M in models.items()],
            detail=f"{det.design_type}. " + " ".join(c for c in rsm_report.caveats(models)[:2]),
            terms=defs("nuisance", "coded", "aliased"), accent=dk.NAVY)

    found, more = [], []
    for k in [k for k in rsm_report.HEADLINE if k in R.fits]:
        v = rsm_report._verdict(R, k)
        if v:
            text = " ".join(_plain(x).lstrip("- ").strip() for x in v)
            body = text[len(R.fits[k].label):].strip(" .")
            found.append((_short(R.fits[k].label), body[:1].upper() + body[1:] + "."))
    best = max(rsm_report.optimum_by_hold(R), key=lambda ho: ho[1].D, default=None)
    if best is not None:
        more.append(("Best overall setting", tw_desirability(R)[0].replace("Best overall: ", "") + "."))
    moved = [rsm_report.term_text(R, row["term"]) + " on " + _short(R.fits[k].label) for k in rsm_report.HEADLINE
             for row in rsm_report.interaction_agreement(models, k) if not row["agree"]]
    if moved:
        more.append(("Not separated", "; ".join(moved) + " change with the model: not interactions you can read."))
    if len(found) + len(more) <= 6:
        d.cards("What was found", found + more, dk.ORANGE)
    else:                                       # five headline responses: one slide for them, one for the rest
        d.cards("What was found: the headline responses", found[:6], dk.ORANGE)
        if more:
            d.cards("What was found: the best setting", more, dk.ORANGE)

    from . import rsm_figures as rf
    lay = rf.map_layout(R)
    all_figs = {p.name for p in figs.glob("*.png")}
    for k in [k for k in rf.mapped_responses(R) if R.fits[k].full is not None]:   # no fit (constant): no slides
        for stem in rsm_report._stems(all_figs, f"fig_rsm_contour_{k}"):
            t, det_, terms, notes, how = tw_response(R, k, "contour")
            lvl = stem[len(f"fig_rsm_contour_{k}"):].lstrip("_")
            if lvl and lay is not None and lay.figure and lvl.startswith(lay.figure):
                t = f"{t} ({_short(_f(R, lay.figure))} {lvl[len(lay.figure):]})"
            d.figure((t, det_, terms, notes, how), figs / f"{stem}.png", dk.TEAL)
        d.figure(tw_response(R, k, "surface"), figs / f"fig_rsm_surface_{k}.png", dk.TEAL)
        if (figs / f"fig_rsm_pairs_{k}.png").is_file():
            d.figure((f"{_short(R.fits[k].label)}: every pair of factors at the best setting",
                      f"What it shows: the fitted {_short(R.fits[k].label).lower()} for every pair of factors, so no "
                      f"pairing is hidden by the map layout.", defs("contour", "coded"), "", HOW_PAIRS),
                     figs / f"fig_rsm_pairs_{k}.png", dk.TEAL)
    for stem in rsm_report._stems(all_figs, "fig_rsm_desirability"):
        t, det_, terms, notes = tw_desirability(R)
        lvl = stem[len("fig_rsm_desirability"):].lstrip("_")
        if lvl and lay is not None and lay.figure:
            here = f"{_short(_f(R, lay.figure))} {lvl[len(lay.figure):]}"
            det_ = f"What it shows: where all the goals are met at {here}. {t} across every setting. " + det_
            t = f"Where the goals are met at {here}"
        else:
            det_ = "What it shows: " + det_
        d.figure((t, det_, terms, notes, HOW_DESIRABILITY), figs / f"{stem}.png", dk.ORANGE)
    d.figure(tw_profiler(R) + (HOW_PROFILER,), figs / "fig_rsm_profiler.png", dk.ORANGE)
    if data["optimum"]:
        head, rows = _table_opt(R, data)
        d.table("Best settings, by held level and model", head, rows,
                detail="The desirability optimum at each held level of the nuisance factor, for each model.",
                terms=defs("desirability"), accent=dk.ORANGE)
    if data["stationary_points"]:
        d.table("Where each fitted surface peaks", ["Response", "Kind", "Inside"] + [_short(_f(R, k)) for k in R.axis],
                [[_short(s["response"]), s["kind"].split(" (")[0], s["inside the tested range"]] +
                 [(s[_f(R, k)] if isinstance(s[_f(R, k)], str) else rsm_report.num(s[_f(R, k)])) for k in R.axis]
                 for s in data["stationary_points"]],
                detail="Simplified model, nuisance factors at their centre. A peak outside the range means the best "
                       "value inside it is on an edge.", terms=defs("stationary"), accent=dk.TEAL)
    keys = list(R.axis) + list(R.nuisance)
    for rec_ in data.get("recommendations", []):
        rows = [r for r in data["next_runs"] if r["Recommendation"] == rec_["recommendation"]][:9]
        if rows:
            g = R.goals[0].key if R.goals else None
            head = ["Run", "Why this run"] + [_short(_f(R, k)) for k in keys] + \
                   ([f"{_short(R.fits[g].label)} (PI)"] if g else [])
            body = [[r["Run"], r["Why this run"][:38]] + [rsm_report.num(r[_f(R, k)]) if isinstance(r[_f(R, k)], (int, float))
                                                           else r[_f(R, k)] for k in keys]
                    + ([f"{r.get('predicted ' + R.fits[g].label, float('nan')):.3g} ({r.get(R.fits[g].label + ' 95% PI', '–')})"]
                       if g else []) for r in rows]
            d.table(f"Next: {rec_['recommendation'][:70]}", head, body, detail=rec_["why"], accent=dk.ORANGE)
        else:
            d.cards(f"Next: {rec_['recommendation'][:70]}",
                    [("Why", rec_["why"]), ("The run sheet", "Every run of the new design, in order, with the Notes to "
                                                              "type: next CCD/run_sheet.xlsx (and .csv, .md).")],
                    dk.ORANGE)
    if data.get("controls"):
        d.table("Controls against the centre runs", ["Run", "Differs in", "Response", "Value", "Centres", "In SDs"],
                [[c["run"][:6], c["differs from the centre in"], _short(c["response"]), f"{c['value']:.4g}"
                  if c["value"] is not None else "–",
                  f"{c['centre mean']:.4g} ± {c['centre SD']:.2g}" if c.get("centre mean") is not None else "–",
                  f"{c['difference in centre SDs']:+.1f}" if c.get("difference in centre SDs") is not None else "–"]
                 for c in data["controls"]],
                detail="A control differs from the centre runs in one factor only (e.g. no rotation), so the difference "
                       "is that factor's doing: beyond about ±2 centre SDs is a real difference.",
                terms=defs("SD"), accent=dk.PURPLE)
    if (figs / "fig_rsm_drift.png").is_file():
        trends = [f"{_short(R.fits[k].label)} {R.fits[k].centre_trend.slope_per_h:+.3g}/h (p {R.fits[k].centre_trend.p:.2g})"
                  for k in rsm_report.HEADLINE if k in R.fits and R.fits[k].centre_trend is not None
                  and R.fits[k].centre_trend.p is not None]
        drift = [t for t in trends if float(t.split("(p ")[1].rstrip(")")) < 0.05]
        d.figure(("Drift through the day: " + ("none in the centre runs" if trends and not drift else
                                                "check " + ", ".join(t.split(" ")[0] for t in drift) if drift else
                                                "the repeated settings"),
                  "Centre runs against time: " + "; ".join(trends) + "." if trends else
                  "Repeated settings inside each block, first to last.", defs("drift"), ""),
                 figs / "fig_rsm_drift.png", dk.GREY)
    d.figure(tw_fit(R), figs / "fig_rsm_fit_checks.png", dk.GREY)
    d.figure(tw_compare(models), figs / "fig_rsm_model_compare.png", dk.GREY)
    if data["predictions"]:
        d.figure(("Runs kept out of the fit against their prediction intervals", "", defs("PI"), ""),
                 figs / "fig_rsm_validation.png", dk.GREY)
    gas = data.get("gas_delivered") or []
    nd = [g for g in gas if g["regime"] in ("pressure-limited", "gas short")]
    if gas:
        d.figure(((f"{len(nd)} of {len(gas)} runs did not get their set gas" if nd else
                   "Every run got its set gas"),
                  ("Gas delivered in the camera window against the set point. "
                   + (f"Pressure-limited at the supply ceiling: {', '.join(g['run'][:6] for g in nd)}; "
                      + {"exclude": "kept out of the surfaces (own section in the report).",
                         "delivered": "fitted at the gas they got.",
                         "set": "fitted at their set gas, which they did not get."}[R.limited_mode]
                      if nd else "")), "", "Bar: 10th-90th percentile of the gas flow in the window."),
                 figs / "fig_rsm_gas_delivered.png", dk.ORANGE)
        d.figure(("Pressure and gas through each run",
                  "Gas (blue) and upstream pressure (red) from Start; grey = camera window. On a small orifice the "
                  "pressure jumps to the supply ceiling when the silicone arrives and the gas collapses.", "", ""),
                 figs / "fig_gas_traces.png", dk.ORANGE)
    d.cards("Caveats before reading too much into this",
            [(c.split(":")[0].split(" (")[0][:40] if ":" in c[:50] else c.split(",")[0][:40], c)
             for c in rsm_report.caveats(models)], dk.YELLOW)

    if shared is not None and shared.runs:
        d.section("Appendix: the shared figures", "Everything the Taguchi deck shows that is not Taguchi-specific: every "
                                                  "run, GLR, gas flux and silicone film, droplet size, steadiness, "
                                                  "pieces, data quality, images. Conditions are the distinct settings "
                                                  "(C1, C2, ...).")
        parts = figs / dk.SLIDE_FIG_DIR
        conds = list(dk._conds(shared))
        d.figure(dk.tw_per_run(shared), figs / "fig_per_run.png", dk.ORANGE)
        d.figure(dk.tw_glr(shared), figs / "fig_glr.png", dk.ORANGE)
        d.figure(dk.tw_orifice_model(shared), figs / "fig_orifice_model.png", dk.ORANGE)
        d.figure(dk.tw_gas_flux(shared), figs / "fig_gas_flux.png", dk.ORANGE)
        d.figure(dk.tw_film_thickness(shared), figs / "fig_film_thickness.png", dk.ORANGE)
        if dk.has_rate(shared):
            d.cards("How droplets per second are estimated", dk.rate_cards(shared), dk.ORANGE)
        if bins is not None:
            d.figure(dk.tw_spread_count(shared, bins), figs / "fig_size_spread_count.png", dk.TEAL)
            d.figure(dk.tw_spread_volume(shared, bins), figs / "fig_size_spread_volume.png", dk.TEAL)
        d.figure(dk.tw_size_distribution(shared), figs / "fig_size_distribution.png", dk.TEAL)
        d.figure(dk.tw_size_percentiles(shared), figs / "fig_size_percentiles.png", dk.TEAL)
        d.figure(dk.tw_steadiness(shared), figs / "fig_steadiness.png", dk.PURPLE)
        d.figure(dk.tw_spectra(shared), figs / "fig_spectra.png", dk.PURPLE)
        for i, part in enumerate(dk._chunks(conds, dk.SERIES_PER_SLIDE), 1):
            f1 = figures_extra.fig_series(shared, parts, only=part, name=f"fig_series_{i}", formats=("png",))
            if f1:
                d.figure(dk.tw_series(shared, part), f1[0], dk.PURPLE)
        for i, part in enumerate(dk._chunks(conds, dk.SERIES_PER_SLIDE), 1):
            f2 = figures_extra.fig_series_liquid(shared, parts, only=part, name=f"fig_series_liquid_{i}",
                                                 formats=("png",))
            if f2:
                d.figure(dk.tw_series_liquid(shared, part), f2[0], dk.PURPLE)
        analysed = [k for k in shared.responses if dk._analysed(shared, k)]
        size_keys = [k for k in analysed if k in dk.SIZE_KEYS]
        other = [k for k in analysed if k not in dk.SIZE_KEYS]
        for i, (keys, what) in enumerate(((size_keys, "droplet size"), (other[:5], "atomisation and steadiness"),
                                          (other[5:], "pulsing and pressure")), 1):
            if keys:
                f3 = figures_extra.fig_replicates(shared, parts, keys=keys, name=f"fig_replicates_{i}", formats=("png",))
                if f3:
                    d.figure(dk.tw_replicates(shared, keys, what), f3[0], dk.GREY)
        d.figure(dk.tw_correlations(shared), figs / "fig_correlations.png", dk.GREY)
        d.figure(dk.tw_pieces(shared), figs / "fig_pieces.png", dk.TEAL)
        d.figure(dk.tw_quality(shared), figs / "fig_quality.png", dk.YELLOW)
        for c in dk._conds(shared):
            p = figs / figures_extra.GALLERY_DIR / f"gallery_{c}.png"
            if p.is_file():
                d.figure(dk.tw_gallery(shared, c), p, dk.GREY)
        dk.more_grid_slides(d, shared)
        dk.largest_slides(d, shared)
    return d.save(path)
