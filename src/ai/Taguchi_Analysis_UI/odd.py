"""odd.py -- the odd-frame pack: frames and runs that are out of the ordinary.

Reuses `taguchi_analysis.flag_odd` for the pipeline's own categories (atomised_100pct,
no_infocus_droplets, d32_outlier, slow_stage) so the definition of "odd" stays in ONE place,
and adds the one category that only exists with replicates: a run whose value is far from
its own condition's other replicates (`replicate_outlier`, from stats.py).

THE HAZARD this wraps. flag_odd looks for classical images at `cl_dir/"images"/<frame>.png`,
a folder that only exists when the run was made with "every frame". In the default
(extreme-frames-only) mode the images are in `extreme_images/`, so the stock pack silently
records "none found" for every frame. The record handed to flag_odd carries a `cl_dir` whose
"images" resolves to whichever folder really exists, and a frame with no image is then
labelled with WHY ("this run kept extreme frames only") rather than an unexplained "none found".
Nothing in flag_odd is copied or edited.

Writes <output>/odd/odd_flags.csv, and copies images only where they exist.
"""
from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import pipeline_spec as spec

NO_IMAGE_EXTREMES = "no image kept: this run saved extreme frames only"
NO_IMAGE = "no image found"


class _ImageRoot:
    """Stands in for a run's classical output folder inside flag_odd. Only `/ "images"` is
    redirected (to the folder that exists); every other path operation is a normal Path."""

    def __init__(self, cl_dir: Path):
        self.path = Path(cl_dir)

    def images_dir(self) -> Path:
        for name in ("images", "extreme_images"):
            if (self.path / name).is_dir():
                return self.path / name
        return self.path / "images"

    def __truediv__(self, name):
        return self.images_dir() if name == "images" else self.path / name

    def __fspath__(self) -> str:
        return os.fspath(self.path)


@dataclass
class OddResult:
    csv_path: Path | None = None
    n_flags: int = 0
    by_category: dict = field(default_factory=dict)
    n_images: int = 0
    note: str = ""


def _read(csv_path: Path) -> list[dict]:
    if not csv_path.is_file():
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(csv_path: Path, rows: list[dict]) -> None:
    cols = ["run", "frame", "category", "why", "images_copied"]
    tmp = csv_path.with_name(f".{csv_path.name}.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    tmp.replace(csv_path)


def _timings(output_dir: Path) -> dict:
    ta = spec.rdc_module("taguchi_analysis")
    return ta.load_timings([Path(output_dir) / "_job" / "timings.csv"])


def _clear_previous(odd_dir: Path) -> None:
    """The pack is wholly generated here, so a previous one is replaced, not mixed in (stale
    frames from an earlier analysis would read as current). Only removed if it holds nothing
    but what this function writes -- anything else in the folder and it is left alone."""
    if not odd_dir.is_dir():
        return
    files = [p for p in odd_dir.rglob("*") if p.is_file()]
    if all(p.suffix.lower() == ".png" or p.name == "odd_flags.csv" for p in files):
        for p in files:
            p.unlink()
        for d in sorted((p for p in odd_dir.rglob("*") if p.is_dir()), reverse=True):
            d.rmdir()
    else:
        (odd_dir / "odd_flags.csv").unlink(missing_ok=True)


def make_pack(results, output_dir: Path) -> OddResult:
    """Build <output_dir>/odd/ for the analysed runs of `results` (stats.Results)."""
    ta = spec.rdc_module("taguchi_analysis")
    output_dir = Path(output_dir)
    _clear_previous(output_dir / "odd")
    records, roots = [], {}
    for r in results.runs:
        rec = dict(r.rec)
        if not rec:
            continue
        root = _ImageRoot(rec["cl_dir"])
        rec["cl_dir"] = root
        roots[rec["run"]] = root
        records.append(rec)

    ta.flag_odd(records, _timings(output_dir), output_dir)

    odd_dir = output_dir / "odd"
    csv_path = odd_dir / "odd_flags.csv"
    rows = _read(csv_path)
    for row in rows:
        if row.get("images_copied") == "none found":
            root = roots.get(row["run"])
            kept_all = root is not None and (root.path / "images").is_dir()
            row["images_copied"] = NO_IMAGE if kept_all else NO_IMAGE_EXTREMES

    for key, res in results.responses.items():
        for o in res.outliers:
            rows.append({"run": o["run"], "frame": "", "category": "replicate_outlier",
                         "why": (f"{res.label}: {o['value']:.4g} vs {o['condition_mean']:.4g} (mean of "
                                 f"condition {o['condition']}), {o['z']:+.1f} SD of replicate noise"),
                         "images_copied": ""})

    result = OddResult()
    if not rows:
        result.note = "nothing out of the ordinary was found"
        return result
    odd_dir.mkdir(parents=True, exist_ok=True)
    _write(csv_path, rows)
    result.csv_path = csv_path
    result.n_flags = len(rows)
    result.by_category = dict(Counter(r["category"] for r in rows))
    result.n_images = sum(1 for p in odd_dir.rglob("*.png"))
    if any(r.get("images_copied") == NO_IMAGE_EXTREMES for r in rows):
        result.note = ("most flagged frames have no image because the runs kept extreme frames only; "
                       "re-run with 'every frame' ticked to get them")
    return result
