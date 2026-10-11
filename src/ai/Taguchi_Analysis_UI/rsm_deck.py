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


def tw_response(R, key: str, what: str):
    fr = R.fits[key]
    f = fr.full
    name = _short(fr.label)
    s = rsm_report.stationary_points(R, key)
    if what == "contour":
        title = f"{name}: {_shape_phrase(R, key)}"
    elif s is not None:
        where = ", ".join(f"{R.decode(k, c):.4g} {rsm_report._flabel(R, k).split('(')[-1].rstrip(')')}"
                          for k, c in s.coded.items())
        kind = s.kind.split(" (")[0]
        title = f"{name} in 3D: a {kind} {'centred ' if kind == 'saddle' else ''}at {where}" + (
            "" if s.inside else " (outside the range)")
    else:
        title = f"{name} in 3D"
    lof = f.lof
    detail = (f"R² {f.r2:.2f}, predicted R² {f.r2_pred:.2f}"
              + ("" if lof is None or lof.p is None else f", lack of fit p = {lof.p:.2g}") + ". "
              + (rsm_report.stationary_text(R, key, s) if s is not None else ""))
    holds = ", ".join(f"{_short(_f(R, k))} " + "/".join(f"{x:g}" for x in next(fl.levels for fl in
                      R.loaded.detected.factors if fl.key == k)) for k in R.nuisance)
    if holds:
        detail += f" One panel per {holds} (kept in the model, not mapped)."
    terms = defs("contour" if what == "contour" else "surface", "R2 pred", "lack of fit", "nuisance", "stationary")
    return title, detail, terms, ("Star = the best setting for all the goals together, not this response's own peak. "
                                  + " ".join(_plain(x) for x in rsm_report._verdict(R, key)))


def tw_desirability(R):
    best = max(rsm_report.optimum_by_hold(R), key=lambda ho: ho[1].D, default=None)
    if best is None:
        return "Desirability", "", defs("desirability", "sweet spot"), ""
    hold, o = best
    where = ", ".join(f"{_short(_f(R, k))} {R.decode(k, o.coded[k]):.4g}" for k in R.axis)
    held = ", ".join(f"{_short(_f(R, k))} {v:g}" for k, v in hold.items())
    goals = "; ".join(f"{_short(R.fits[g.key].label)} {'up' if g.direction == 'max' else 'down'}" for g in R.goals)
    edge = (f" It sits on the edge of the tested range for {', '.join(_short(_f(R, k)) for k in o.on_edge)}, so the best "
            f"point may lie beyond it." if o.on_edge else "")
    trade = "".join(f" On {_short(_f(R, k)).lower()}: {', '.join(up)} pull it up, {', '.join(down)} pull it down."
                    for k, (up, down) in rsm_report.tradeoffs(R, o).items() if up and down)
    return (f"Best overall: {where}" + (f" at {held}" if held else "") + f" (D = {o.D:.2f})",
            f"Goals: {goals}. Ramps run across each response's observed range.{edge}{trade}",
            defs("desirability", "sweet spot"), "")


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
        if fr is not None and fr.full is not None and fr.full.r2_pred is not None:
            lof = fr.full.lof
            rows.append(f"{_short(fr.label)}: predicted R² {fr.full.r2_pred:.2f}"
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
            [f"{o[_f(R, k)]:.4g}" for k in R.axis] + [o["on the edge of"] or "–"] for o in data["optimum"]]
    return head, rows


def build(path: Path, models: dict, prov, figures_dir: Path, title: str = "Response-surface analysis",
          shared=None) -> Path:
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

    found = []
    for k in [k for k in rsm_report.HEADLINE if k in R.fits]:
        v = rsm_report._verdict(R, k)
        if v:
            text = " ".join(_plain(x).lstrip("- ").strip() for x in v)
            body = text[len(R.fits[k].label):].strip(" .")
            found.append((_short(R.fits[k].label), body[:1].upper() + body[1:] + "."))
    best = max(rsm_report.optimum_by_hold(R), key=lambda ho: ho[1].D, default=None)
    if best is not None:
        found.append(("Best overall setting", tw_desirability(R)[0].replace("Best overall: ", "") + "."))
    moved = [rsm_report.term_text(R, row["term"]) + " on " + _short(R.fits[k].label) for k in rsm_report.HEADLINE
             for row in rsm_report.interaction_agreement(models, k) if not row["agree"]]
    if moved:
        found.append(("Not separated", "; ".join(moved) + " change with the model: not interactions you can read."))
    d.cards("What was found", found[:6], dk.ORANGE)

    for k in [k for k in list(rsm_report.HEADLINE) + ["lag1", "peak_bar"]
              if k in R.fits and R.fits[k].full is not None]:                # no fit (e.g. constant): no slides
        d.figure(tw_response(R, k, "contour"), figs / f"fig_rsm_contour_{k}.png", dk.TEAL)
        d.figure(tw_response(R, k, "surface"), figs / f"fig_rsm_surface_{k}.png", dk.TEAL)
    d.figure(tw_desirability(R), figs / "fig_rsm_desirability.png", dk.ORANGE)
    d.figure(tw_profiler(R), figs / "fig_rsm_profiler.png", dk.ORANGE)
    if data["optimum"]:
        head, rows = _table_opt(R, data)
        d.table("Best settings, by held level and model", head, rows,
                detail="The desirability optimum at each held level of the nuisance factor, for each model.",
                terms=defs("desirability"), accent=dk.ORANGE)
    if data["stationary_points"]:
        d.table("Where each fitted surface peaks", ["Response", "Kind", "Inside"] + [_short(_f(R, k)) for k in R.axis],
                [[_short(s["response"]), s["kind"].split(" (")[0], s["inside the tested range"]] +
                 [f"{s[_f(R, k)]:.4g}" for k in R.axis] for s in data["stationary_points"]],
                detail="Simplified model, nuisance factors at their centre. A peak outside the range means the best "
                       "value inside it is on an edge.", terms=defs("stationary"), accent=dk.TEAL)
    if data["next_runs"]:
        cols = [c for c in data["next_runs"][0] if c != "run"]
        d.table("Suggested next runs", ["Run"] + [_short(c) for c in cols],
                [[r["run"]] + [f"{r[c]:.4g}" if isinstance(r[c], float) else r[c] for c in cols] for r in data["next_runs"]],
                detail="Confirmation runs at the best setting (rounded to what can be set) and a centre repeat to link "
                       "the sessions. The full recommender comes later.", accent=dk.ORANGE)
    d.figure(tw_fit(R), figs / "fig_rsm_fit_checks.png", dk.GREY)
    d.figure(tw_compare(models), figs / "fig_rsm_model_compare.png", dk.GREY)
    if data["predictions"]:
        d.figure(("Runs kept out of the fit against their prediction intervals", "", defs("PI"), ""),
                 figs / "fig_rsm_validation.png", dk.GREY)
    d.cards("Caveats before reading too much into this",
            [(c.split(":")[0].split(" (")[0][:40] if ":" in c[:50] else c.split(",")[0][:40], c)
             for c in rsm_report.caveats(models)], dk.YELLOW)

    if shared is not None and shared.runs:
        d.section("Appendix: the shared figures", "Droplet size, steadiness and data quality for the same runs, as in "
                                                  "the Taguchi deck.")
        bins = None
        d.figure(dk.tw_size_distribution(shared), figs / "fig_size_distribution.png", dk.TEAL)
        d.figure(dk.tw_size_percentiles(shared), figs / "fig_size_percentiles.png", dk.TEAL)
        d.figure(dk.tw_steadiness(shared), figs / "fig_steadiness.png", dk.PURPLE)
        d.figure(dk.tw_spectra(shared), figs / "fig_spectra.png", dk.PURPLE)
        d.figure(dk.tw_pieces(shared), figs / "fig_pieces.png", dk.TEAL)
        d.figure(dk.tw_quality(shared), figs / "fig_quality.png", dk.YELLOW)
        for c in dk._conds(shared):
            p = figs / figures_extra.GALLERY_DIR / f"gallery_{c}.png"
            if p.is_file():
                d.figure(dk.tw_gallery(shared, c), p, dk.GREY)
    return d.save(path)
