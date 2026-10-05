"""publish.py -- design -> statistics -> every deliverable, in one call. No Qt.

    analyse (stats.py) -> size bins -> figures -> odd-frame pack (optional) -> report
    -> workbook -> flat CSVs + results.json (optional)

The Analyse button runs this on a worker thread; tests call it directly.

SAFETY
  * Nothing is written into a run folder: every output lands in `output_dir`.
  * A REFUSED analysis (mixed sizer versions, nothing to analyse) writes no report, workbook
    or figures (only the design file the user just edited is saved), so a good report from an
    earlier analysis is never replaced by a refusal.
  * Each optional step (figures, odd pack, CSVs) is isolated: if one fails, the rest still
    land, and the failure is reported (console, and the report's Warnings section) rather
    than swallowed. A failing report or workbook is reported too.
  * Files are written to a temp name and moved into place.
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import design as dz
from . import figures, fsops, jobstate, odd, provenance, report, size_bins, stats, tables, workbook

REPORT_NAME = "taguchi_report.md"
WORKBOOK_NAME = "taguchi_analysis.xlsx"
FIGURES_DIR = "figures"
CSV_DIR = "csv"

Log = Callable[[str, str], None]


@dataclass
class Deliverables:
    output_dir: Path
    refused: str | None = None
    results: stats.Results | None = None
    bins: size_bins.SizeBins | None = None
    prov: provenance.Provenance | None = None
    report: Path | None = None
    workbook: Path | None = None
    figures: list[Path] = field(default_factory=list)
    csv_dir: Path | None = None
    odd: odd.OddResult | None = None
    problems: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.refused is None and self.report is not None and not self.problems


def _write_csv(path: Path, rows: list[dict]) -> None:
    cols: list[str] = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    fsops.replace(tmp, path)


def write_flat_csvs(output_dir: Path, results, bins, prov) -> Path:
    out = Path(output_dir) / CSV_DIR
    out.mkdir(parents=True, exist_ok=True)
    data = tables.all_tables(results, bins)
    for name, rows in data.items():
        if rows:
            _write_csv(out / f"{name}.csv", rows)
    jobstate.atomic_write_json(out / "results.json", {
        "provenance": dict(prov.rows()), "warnings": results.warnings,
        "multiple_comparisons": [{"response": rk, "factor": fk, "p": p, "q": q}
                                 for rk, fk, p, q in results.multiple],
        "tables": data})
    return out


def publish(design: dz.Design, output_dir: Path, *, thr: float | None = None,
            options: dict | None = None, bin_width: float = size_bins.DEFAULT_WIDTH_UM,
            bin_max: float = size_bins.DEFAULT_MAX_UM,
            progress: Callable[[int, int, str], None] | None = None,
            log: Log | None = None, do_bootstrap: bool = True) -> Deliverables:
    log = log or (lambda text, level="info": None)
    options = options or {}
    output_dir = Path(output_dir)
    t0 = time.time()
    d = Deliverables(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    dz.save(design, output_dir)

    log("analysis: reading the measured runs ...", "info")
    results = stats.analyse(design, thr, progress, do_bootstrap)
    d.results = results
    for w in results.warnings:
        log(f"analysis: {w}", "warn")
    for name, why in results.skipped:                   # before any refusal: they explain it
        log(f"analysis: skipping {name} ({why})", "warn")
    if results.refused:
        d.refused = results.refused
        d.seconds = time.time() - t0
        return d

    def step(label: str, fn):
        """Run one optional step; a failure is recorded and the rest carry on."""
        try:
            return fn()
        except Exception as exc:                       # noqa: BLE001 -- reported, never swallowed
            msg = f"{label} failed: {type(exc).__name__}: {exc}"
            d.problems.append(msg)
            results.warnings.append(msg)
            log(msg, "error")
            return None

    d.bins = step("size spread", lambda: size_bins.from_results(results, bin_width, bin_max))
    d.prov = provenance.collect(results, d.bins, output_dir)

    log("analysis: drawing figures ...", "info")
    d.figures = step("figures", lambda: figures.make_all(results, d.bins, output_dir / FIGURES_DIR)) or []

    if options.get("odd_pack"):
        log("analysis: building the odd-frame pack ...", "info")
        d.odd = step("odd-frame pack", lambda: odd.make_pack(results, output_dir))

    findings = step("design checks", lambda: dz.diagnose(design)) or []
    text = step("report", lambda: report.build(results, d.bins, d.prov, findings, d.odd, d.figures))
    if text is not None:
        def put_report():
            path = output_dir / REPORT_NAME
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text(text, encoding="utf-8")
            fsops.replace(tmp, path)
            return path
        d.report = step("report", put_report)

    d.workbook = step("workbook", lambda: workbook.write(
        output_dir / WORKBOOK_NAME, results, d.bins, d.prov, workbook.read_timings(output_dir)))

    if options.get("flat_csvs"):
        d.csv_dir = step("flat CSVs", lambda: write_flat_csvs(output_dir, results, d.bins, d.prov))

    d.seconds = time.time() - t0
    return d
