"""The measured size distribution: imported once from a run's droplet measurement, then weights for the sizes fired.

The model fires the same number of droplets at every size on a grid, so its delivery-against-size curve does not
depend on any distribution. Purity and the delivered size distribution do: they weight each fired size by how many
droplets of that size the spray makes, from a measured run.

What is imported (the rule master_log.band_concentrations uses for its <30 / 30-40 / ... columns): the droplets in the
measurement volume (in_volume = 1), each with its border weight; those sized (in_focus = 1, >= d_min) by their size,
the rest counted below d_min, unsized. The crowded factor scales every size alike, so it cannot change a share and
is not applied. Assumption: a snapshot is a flux, i.e. every size crosses the window at the same speed (rates.py says
the same; Phase 5's speeds by size remove it).

The droplets below d_min go in spread evenly over below_d_min_from_um to d_min (estimated: their sizes are unknown).
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np


@dataclass
class Distribution:
    lo_um: np.ndarray       # sized bins
    hi_um: np.ndarray
    count: np.ndarray       # border-weighted droplets per bin
    below_dmin: float       # border-weighted droplets in the volume below d_min (counted, not sized)
    d_min_um: float
    source: str
    header: list            # the file's '#' lines

    @property
    def total(self) -> float:
        return float(self.count.sum() + self.below_dmin)


def import_run(meas_dir: Path, out_csv: Path, bin_um: float = 2.0) -> Distribution:
    """Read a run's droplets_<thr>/ (droplet_sizes.csv and summary.json), never writing there, and save the
    distribution to out_csv."""
    meas_dir = Path(meas_dir)
    summ = json.loads((meas_dir / "summary.json").read_text(encoding="utf-8"))
    prov = summ.get("provenance") or {}
    version = str(prov.get("sizer_version") or "")
    if not version.startswith("3."):
        raise ValueError(f"{meas_dir}: measured with sizer {version or 'unknown'}; the in-volume counts need 3.x")
    d_min = float(prov.get("sizer_d_min_um") or 30.0)
    sized, wsized, below = [], [], 0.0
    with open(meas_dir / "droplet_sizes.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("in_volume") != "1" or not r.get("weight"):
                continue
            w = float(r["weight"])
            if r.get("in_focus") == "1":
                sized.append(float(r["diameter_um"]))
                wsized.append(w)
            else:
                below += w
    sized, wsized = np.array(sized), np.array(wsized)
    top = max(d_min + bin_um, float(np.ceil(sized.max() / bin_um) * bin_um) + bin_um) if sized.size else d_min + bin_um
    edges = np.arange(d_min, top + bin_um / 2.0, bin_um)
    count, _e = np.histogram(sized, bins=edges, weights=wsized)
    conc = summ.get("concentration") or {}
    header = [f"Measured droplet size distribution for Flow Visualisation (import_sizes.py, {date.today()})",
              f"source: {meas_dir}",
              f"sizer {version}; d_min {d_min:g} um; frames {conc.get('frames', '?')}; in the measurement volume, "
              f"border-weighted; crowded factor {conc.get('crowded_factor', '?')} not applied (shares only)",
              f"sized droplets {wsized.sum():.1f} (weighted, {sized.size} rows); below d_min {below:.1f} (counted, "
              f"not sized)",
              "the row with an empty d_lo_um is the counted-not-sized part below d_min"]
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        for line in header:
            fh.write(f"# {line}\n")
        w = csv.writer(fh)
        w.writerow(["d_lo_um", "d_hi_um", "weighted_count", "sized"])
        w.writerow(["", f"{d_min:g}", f"{below:.4f}", 0])
        for lo, hi, c in zip(edges[:-1], edges[1:], count):
            w.writerow([f"{lo:g}", f"{hi:g}", f"{c:.4f}", 1])
    return load(out_csv)


def load(path: Path) -> Distribution:
    path = Path(path)
    header, rows = [], []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    header = [ln[1:].strip() for ln in lines if ln.startswith("#")]
    for r in csv.DictReader([ln for ln in lines if not ln.startswith("#")]):
        rows.append(r)
    below = sum(float(r["weighted_count"]) for r in rows if r["sized"] == "0")
    d_min = min((float(r["d_hi_um"]) for r in rows if r["sized"] == "0"), default=None)
    s = [r for r in rows if r["sized"] == "1"]
    lo = np.array([float(r["d_lo_um"]) for r in s])
    if d_min is None:
        d_min = float(lo.min()) if lo.size else 0.0
    return Distribution(lo, np.array([float(r["d_hi_um"]) for r in s]),
                        np.array([float(r["weighted_count"]) for r in s]), below, d_min, str(path), header)


def cells(sizes_um) -> tuple[np.ndarray, np.ndarray]:
    """Each fired size's cell: from halfway to the size below to halfway to the size above (the end cells as wide
    as their neighbours)."""
    s = np.asarray(sizes_um, float)
    if s.size == 1:
        return s - 0.5, s + 0.5
    mid = (s[:-1] + s[1:]) / 2.0
    return np.r_[s[0] - (mid[0] - s[0]), mid], np.r_[mid, s[-1] + (s[-1] - mid[-1])]


def weights(sizes_um, dist: Distribution, below_from_um: float) -> tuple[np.ndarray, dict]:
    """How many droplets each fired size stands for (by number), from the measured distribution, uniform inside
    each measured bin; and what the fired sizes leave out."""
    c_lo, c_hi = cells(sizes_um)
    n = np.zeros(c_lo.size)
    pieces = [(dist.lo_um, dist.hi_um, dist.count)]
    if dist.below_dmin > 0:
        pieces.append((np.array([below_from_um]), np.array([dist.d_min_um]), np.array([dist.below_dmin])))
    covered = 0.0
    for lo, hi, cnt in pieces:
        for b_lo, b_hi, c in zip(lo, hi, cnt):
            if c <= 0 or b_hi <= b_lo:
                continue
            ov = np.clip(np.minimum(c_hi, b_hi) - np.maximum(c_lo, b_lo), 0.0, None) / (b_hi - b_lo)
            n += c * ov
            covered += c * ov.sum()
    total = dist.total
    sized_d = (dist.lo_um + dist.hi_um) / 2.0
    above = float(dist.count[dist.lo_um >= c_hi[-1]].sum())
    return n, {"measured_total": total, "covered": covered, "share_not_fired": 1.0 - covered / total if total else 0.0,
               "above_fired_range": above, "below_d_min": dist.below_dmin, "d_min_um": dist.d_min_um,
               "largest_measured_um": float(dist.hi_um[dist.count > 0].max()) if (dist.count > 0).any() else None,
               "mean_sized_um": float((sized_d * dist.count).sum() / dist.count.sum()) if dist.count.sum() else None}
