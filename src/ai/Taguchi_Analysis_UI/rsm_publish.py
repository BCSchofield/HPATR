"""rsm_publish.py -- the response-surface analysis, end to end, in one call: what the Response
surface tab's Analyse button runs (as publish.publish is for the Taguchi tab). No Qt.

    detect (rsm_detect, with the user's edits) -> save rsm_design.json -> load every run
    (rsm_responses.load) -> fit each MODEL (rsm_responses.analyse) -> figures (rsm_figures) ->
    shared extras (the Taguchi analysis' size / steadiness / quality figures and galleries, from the
    same runs) -> rsm_report.md -> rsm_analysis.xlsx -> rsm_results.csv (the CCD plan's columns) ->
    rsm_deck.pptx

MODELS. One or more ModelSpecs on the same runs; the FIRST is the primary one (maps, optimum, deck).
More than one is how a nuisance factor's influence is checked: the 9x3 trial fits gas x feed with
RPM as a nuisance term AND without it, and reports where they disagree.

SAFETY as publish.py: nothing is written into a run folder; a refused analysis writes no report;
each step is isolated (a failure is recorded and the rest still lands); files are written to a
temporary name and moved into place.
"""
from __future__ import annotations

import copy
import csv
import dataclasses
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from . import deck as deck_mod
from . import figures, figures_extra, fsops, provenance, rsm_detect, rsm_figures, rsm_report, rsm_responses, size_bins, stats
from .workbook import _style

REPORT_NAME = "rsm_report.md"
WORKBOOK_NAME = "rsm_analysis.xlsx"
CSV_NAME = "rsm_results.csv"
DECK_NAME = "rsm_deck.pptx"
FIGURES_DIR = "figures"
METRICS_CACHE = "cache/run_metrics"

SHEETS = (("Runs", "runs"), ("Fit summary", "fit_summary"), ("Coefficients", "coefficients"),
          ("Model comparison", "model_comparison"), ("Stationary points", "stationary_points"),
          ("Best settings", "optimum"), ("Goals", "goals"), ("Constraints", "constraints"),
          ("Next runs", "next_runs"), ("Predictions", "predictions"), ("Block repeats", "block_repeats"),
          ("Correlations", "correlations"), ("Design checks", "design"))

Log = Callable[[str, str], None]


@dataclass
class ModelSpec:
    name: str
    axis: list[str]
    nuisance: dict = field(default_factory=dict)      # factor key -> "linear" | "quadratic"
    hold: dict = field(default_factory=dict)          # nuisance factor -> real value for the optimum
    time_term: bool = False


@dataclass
class RsmDeliverables:
    output_dir: Path
    refused: str | None = None
    detected: object = None
    loaded: object = None
    models: dict = field(default_factory=dict)
    report: Path | None = None
    workbook: Path | None = None
    csv: Path | None = None
    deck: Path | None = None
    figures: list[Path] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.refused is None and self.report is not None and not self.problems


def _write_csv(path: Path, rows: list[dict]) -> Path:
    cols: list = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    fsops.replace(tmp, path)
    return path


def _workbook(path: Path, data: dict, prov) -> Path:
    import os
    tmp = path.with_name(f".{path.stem}.{os.getpid()}.tmp.xlsx")
    try:
        with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
            for name, key in SHEETS:
                rows = data.get(key) or []
                if not rows:
                    continue
                frame = pd.DataFrame(rows)
                frame.to_excel(xw, sheet_name=name[:31], index=False)
                _style(xw.sheets[name[:31]], frame)
            frame = pd.DataFrame(prov.rows(), columns=["Item", "Value"])
            frame.to_excel(xw, sheet_name="Provenance", index=False)
            _style(xw.sheets["Provenance"], frame)
        fsops.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def publish(design: rsm_detect.RsmDesign, output_dir: Path, models: list[ModelSpec], *, thr: float | None = None,
            goals: list | None = None, constraints: list | None = None, discrete: dict | None = None,
            shared_extras: bool = True, title: str = "Response-surface analysis",
            progress: Callable[[int, int, str], None] | None = None, log: Log | None = None) -> RsmDeliverables:
    log = log or (lambda text, level="info": None)
    output_dir = Path(output_dir)
    t0 = time.time()
    d = RsmDeliverables(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log("response surface: detecting the design ...", "info")
    det = design.detect()
    d.detected = det
    rsm_detect.save(design, output_dir)
    for f in det.findings:
        if f.level in ("warn", "error"):
            log(f"design: {f.text}", "warn")

    log("response surface: reading the measured runs ...", "info")
    L = rsm_responses.load(det, design.base.runs, thr, output_dir / METRICS_CACHE, progress)
    d.loaded = L
    for name, why in L.skipped:
        log(f"response surface: skipping {name} ({why})", "warn")
    if L.refused:
        d.refused = L.refused
        d.seconds = time.time() - t0
        return d

    def step(label: str, fn):
        try:
            return fn()
        except Exception as exc:                       # noqa: BLE001 -- reported, never swallowed
            msg = f"{label} failed: {type(exc).__name__}: {exc}"
            d.problems.append(msg)
            log(msg, "error")
            return None

    for m in models:
        log(f"response surface: fitting {m.name} ...", "info")
        R = step(f"model {m.name}", lambda m=m: rsm_responses.analyse(
            L, axis=m.axis, nuisance=m.nuisance, hold=m.hold, time_term=m.time_term, goals=goals,
            constraints=constraints, discrete=discrete))
        if R is not None:
            d.models[m.name] = R
    if not d.models:
        d.refused = "no model could be fitted"
        return d

    log("response surface: drawing figures ...", "info")
    problems: list[str] = []
    d.figures = step("figures", lambda: rsm_figures.make_all(d.models, output_dir / FIGURES_DIR, problems)) or []
    for p in problems:
        d.problems.append(p)
        log(p, "error")

    shared = bins = None
    if shared_extras:
        log("response surface: the shared size / steadiness / quality figures ...", "info")
        # grouped by SETTING: a CCD's "CCD run 7" Notes are run numbers, not the Taguchi trial numbers
        # design.assign would otherwise read them as (and then report every repeat as a conflict)
        base = copy.copy(design.base)
        base.rows = [dataclasses.replace(r, trial=None, repeat=None) for r in design.base.rows]
        shared = step("shared extras", lambda: stats.analyse(base, thr, None, False,
                                                             metrics_cache=output_dir / METRICS_CACHE))
        if shared is not None and not shared.refused:
            bins = step("size bins", lambda: size_bins.from_results(shared, size_bins.DEFAULT_WIDTH_UM,
                                                                    size_bins.DEFAULT_MAX_UM))
            extra: list[str] = []
            figs = output_dir / FIGURES_DIR
            # everything the Taguchi publish draws that is not Taguchi-specific (main effects, contributions,
            # S/N, condition-mean interactions and the main-effects diagnostics are left out: the response-
            # surface fit and its checks replace them)
            d.figures += step("shared figures", lambda: figures_extra.make_all(shared, figs, extra)) or []
            for fn in (lambda: figures.fig_per_run(shared, figs), lambda: figures.fig_glr(shared, figs)):
                d.figures += step("shared figures", fn) or []
            if bins is not None:
                d.figures += step("size spread", lambda: figures.fig_size_spread_count(bins, figs)
                                  + figures.fig_size_spread_volume(bins, figs)) or []
            d.problems += extra
    prov = provenance.collect(shared, bins, output_dir) if shared is not None and not shared.refused else \
        provenance.Provenance(time.strftime("%Y-%m-%d %H:%M"), "unknown", False, [], L.thr, 0, 0, [], [])

    text = step("report", lambda: rsm_report.build(d.models, prov, d.figures, title))
    if text is not None:
        def put():
            path = output_dir / REPORT_NAME
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text(text, encoding="utf-8")
            fsops.replace(tmp, path)
            return path
        d.report = step("report", put)
    data = step("tables", lambda: rsm_report.tables(d.models)) or {}
    d.workbook = step("workbook", lambda: _workbook(output_dir / WORKBOOK_NAME, data, prov))
    primary = next(iter(d.models.values()))
    d.csv = step("results CSV", lambda: _write_csv(output_dir / CSV_NAME, rsm_report.results_csv(primary)))
    reason = deck_mod.available()
    if reason:
        log(f"response surface: {reason}", "warn")
    else:
        log("response surface: building the PowerPoint deck ...", "info")
        from . import rsm_deck
        d.deck = step("deck", lambda: rsm_deck.build(output_dir / DECK_NAME, d.models, prov,
                                                     output_dir / FIGURES_DIR, title,
                                                     shared if shared is not None and not shared.refused else None,
                                                     bins))
    d.seconds = time.time() - t0
    return d
