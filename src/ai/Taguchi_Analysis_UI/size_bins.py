"""size_bins.py -- the droplet size spread of each run: % by count and % by volume.

From the IN-FOCUS droplet diameters (the same population D32 uses: load_run's per-frame
`dia` arrays, read from droplet_sizes.csv). Bins are 25 um wide up to 200 um by default,
then one open-ended bin; both are settings, and the edges used are printed with the results.

    % by count   share of droplets in each bin
    % by volume  share of LIQUID in each bin: sum of d^3 in the bin / sum of d^3 overall.
                 (d^3, not pi d^3 / 6: the constant cancels -- do not "fix" it.)

The two tell different stories: a few 200 um droplets can carry more liquid than thousands
of 30 um ones, so the count spread can look fine while the volume spread does not.

Each condition is pooled from ALL its replicates' droplets (one population), not averaged
from per-run percentages -- the same discipline load_run's pooled responses follow.

CAVEAT kept with the numbers: the smallest bins sit near the integer-pixel lattice (one
pixel of radius is ~22.6 um at 10 um/px) and the campaign's own size-floor work found mask
sizes unreliable below ~50 um, so the <25 and 25-50 um bins are indicative only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

DEFAULT_WIDTH_UM = 25.0
DEFAULT_MAX_UM = 200.0
SMALL_BIN_CAVEAT_UM = 50.0
CAVEAT = ("Bins below 50 um sit near the integer-pixel lattice (one pixel of radius is ~22.6 um "
          "at 10 um/px) and mask sizes were found unreliable there: treat them as indicative.")


def make_edges(width_um: float = DEFAULT_WIDTH_UM, max_um: float = DEFAULT_MAX_UM) -> list[float]:
    if width_um <= 0 or max_um <= 0 or max_um < width_um:
        raise ValueError("bin width and maximum must be positive, and the maximum at least one bin")
    n = int(round(max_um / width_um))
    edges = [round(i * width_um, 6) for i in range(n + 1)]
    if edges[-1] < max_um:
        edges.append(max_um)
    return edges + [math.inf]


def _fmt(x: float) -> str:
    return f"{x:g}"


def make_labels(edges: list[float]) -> list[str]:
    labels = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        if lo == 0:
            labels.append(f"<{_fmt(hi)}")
        elif math.isinf(hi):
            labels.append(f">{_fmt(lo)}")
        else:
            labels.append(f"{_fmt(lo)}–{_fmt(hi)}")
    return labels


@dataclass
class Spread:
    name: str                     # run name or condition label
    n: int                        # droplets
    sum_d3: float
    pct_count: list[float]
    pct_volume: list[float]
    counts: list[int] = field(default_factory=list)


def spread(name: str, diameters, edges: list[float]) -> Spread:
    d = np.asarray(diameters, dtype=float)
    d = d[np.isfinite(d)]
    idx = np.searchsorted(edges, d, side="right") - 1            # bin i holds [edge_i, edge_i+1)
    nb = len(edges) - 1
    idx = np.clip(idx, 0, nb - 1)
    counts = np.bincount(idx, minlength=nb).astype(int)
    vol = np.bincount(idx, weights=d ** 3, minlength=nb)
    n, total_v = int(d.size), float(vol.sum())
    pc = (100.0 * counts / n).tolist() if n else [0.0] * nb
    pv = (100.0 * vol / total_v).tolist() if total_v > 0 else [0.0] * nb
    return Spread(name, n, total_v, pc, pv, counts.tolist())


@dataclass
class SizeBins:
    edges: list[float]
    labels: list[str]
    runs: list[Spread]
    conditions: list[Spread]
    run_condition: dict[str, str]
    caveat: str = CAVEAT

    def table(self, measure: str = "count", by: str = "run") -> list[dict]:
        """Tidy rows for CSV / the workbook: one row per run (or condition)."""
        rows = []
        for s in (self.runs if by == "run" else self.conditions):
            pct = s.pct_count if measure == "count" else s.pct_volume
            row = {"run" if by == "run" else "condition": s.name}
            if by == "run":
                row["condition"] = self.run_condition.get(s.name, "")
            row["droplets"] = s.n
            row.update({lab: round(v, 4) for lab, v in zip(self.labels, pct)})
            rows.append(row)
        return rows


def size_bins(per_run: list[tuple[str, str, object]], width_um: float = DEFAULT_WIDTH_UM,
              max_um: float = DEFAULT_MAX_UM) -> SizeBins:
    """per_run: (run name, condition label, in-focus diameters in um) for each run."""
    edges = make_edges(width_um, max_um)
    labels = make_labels(edges)
    runs, pooled, order = [], {}, []
    for name, cond, dia in per_run:
        d = np.asarray(dia, dtype=float)
        runs.append(spread(name, d, edges))
        if cond not in pooled:
            pooled[cond], order = [], order + [cond]
        pooled[cond].append(d)
    conds = [spread(c, np.concatenate(pooled[c]) if pooled[c] else np.empty(0), edges) for c in order]
    return SizeBins(edges, labels, runs, conds, {n: c for n, c, _ in per_run})


def from_results(results, width_um: float = DEFAULT_WIDTH_UM, max_um: float = DEFAULT_MAX_UM
                 ) -> SizeBins:
    """Size bins for the runs of a stats.Results (uses each run's load_run diameters)."""
    per_run = []
    for r in results.runs:
        dia = r.rec.get("dia") or {}
        arrays = [np.asarray(v, dtype=float) for v in dia.values()]
        per_run.append((r.name, r.condition, np.concatenate(arrays) if arrays else np.empty(0)))
    return size_bins(per_run, width_um, max_um)
