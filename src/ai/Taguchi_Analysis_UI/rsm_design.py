"""rsm_design.py -- build a face-centred central composite run sheet, and compare a built sheet
with what was actually captured. No Qt.

GENERIC: 2 to 5 factors (built-in keys -- sccm, rpm, sps, orifice, bh -- or any run_summary.xlsx
field), each with real low / middle / high levels (uneven spacing allowed: the middle is coded 0
for the design, and the fit later uses (v - mid-range) / half-range, so 1.2 on 0.5 / 1.2 / 1.8 is
+0.08). Points: all 2^k corners, or a half fraction (last factor = product of the others: resolution
k, so V for five factors), the 2k face centres, and n centres.

BLOCKING (optional): a hard-to-change factor is fitted once per block. Its low and high blocks hold
the corners at that level, opened and closed by the block factor's own face point (a start / end
repeat, so each block shows its own drift); its middle block holds the centres, interleaved with
the other factors' face points. Without a block factor every point is in one randomised block with
the centres spread through it. Runs are randomised WITHIN blocks (seeded, so a sheet is reproducible).

EXTRAS: any extra settings (check points, controls). An extra whose block-factor value is one of the
blocks' goes inside that block (the 0 rpm control among the centres); one off the grid (the 0.8 mm
insert) goes after every block. A FIRST run (the worst-case pressure check) can be named; it opens
its block and that block goes first.

Each row: run number, block, settings, point type, and the Notes to type on the day
("CCD run 7 centre"), which rsm_detect reads back. Saved as rsm_run_sheet.json and exported as
run_sheet.xlsx / .csv / .md. `compare()` matches a built sheet with the detected design of the
captured runs: captured as planned, out of order, settings differ from the plan, not yet captured,
or captured but not on the sheet.
"""
from __future__ import annotations

import csv
import itertools
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import fsops
from . import rsm_detect as rdet

SCHEMA = 1
SHEET_FILENAME = "rsm_run_sheet.json"
EXPORT_STEM = "run_sheet"
MAX_FACTORS = 5
# what the rig can physically set (Ben, 2026-10-11): the gas flow controller tops out at 12,000 sccm.
# There is no rated pressure limit, so peak pressure is watched, not constrained.
RIG_LIMITS = {"sccm": (0.0, 12000.0)}


# ---- inputs ---------------------------------------------------------------------------------------------

@dataclass
class FactorSpec:
    key: str                          # "sccm", "rpm", "sps", "orifice", "bh" or a workbook field name
    label: str                        # "Gas flow (sccm)"
    low: float
    mid: float
    high: float
    short: str = ""                   # "Gas" for the point-type text; default: label up to " ("

    @property
    def name(self) -> str:
        return self.short or self.label.split(" (")[0]

    @property
    def unit(self) -> str:
        import re
        m = re.search(r"\(([^)]+)\)", self.label)
        return m.group(1) if m else ""

    def value(self, coded: float) -> float:
        """Design code -> setting (uneven middle: each half scales separately)."""
        v = self.mid + coded * ((self.high - self.mid) if coded >= 0 else (self.mid - self.low))
        return _clean(v)

    def code(self, v: float) -> float:
        return (v - self.mid) / (self.high - self.mid) if v >= self.mid else (v - self.mid) / (self.mid - self.low)

    def real_code(self, v: float) -> float:
        return (v - (self.low + self.high) / 2) / ((self.high - self.low) / 2)


@dataclass
class Extra:
    values: dict                      # factor key -> setting
    label: str = ""                   # "Check run", "No-rotation control"; default from where it sits


@dataclass
class Plan:
    factors: list[FactorSpec]
    centres: int = 5
    block_factor: str | None = None   # a factor key, fitted once per block
    block_repeats: bool = True        # open and close each outer block on its face point
    block_order: tuple = ("low", "mid", "high")
    fraction: str | None = None       # None (all corners) or "half"
    extras: list[Extra] = field(default_factory=list)
    first: dict | None = None         # factor key -> "low" | "high": the run to do first (pressure check)
    first_label: str = "pressure check"
    seed: int = 0
    minutes_per_run: float = 9.0
    minutes_per_block_change: float = 15.0
    prefix: str = "CCD run"


# ---- the sheet -------------------------------------------------------------------------------------------

@dataclass
class SheetRow:
    run: int
    block: str | None
    values: dict                      # factor key -> setting
    coded: dict                       # factor key -> design code
    kind: str                         # rsm_detect point kind
    label: str                        # "Corner", "Gas face", "Block repeat (start)", "Centre", "Check run"
    notes: str                        # what to type in the capture GUI's Notes


@dataclass
class Sheet:
    plan: Plan
    rows: list[SheetRow]
    findings: list[str]
    estimability: object | None

    @property
    def n_design(self) -> int:
        return sum(1 for r in self.rows if r.kind not in rdet.NOT_FITTED)

    def counts(self) -> dict:
        out: dict = {}
        for r in self.rows:
            out[r.kind] = out.get(r.kind, 0) + 1
        return out

    def blocks(self) -> list[tuple[str | None, list[SheetRow]]]:
        out: list = []
        for r in self.rows:
            if not out or out[-1][0] != r.block:
                out.append((r.block, []))
            out[-1][1].append(r)
        return out

    def minutes(self) -> float:
        changes = max(0, len(self.blocks()) - 1)
        return len(self.rows) * self.plan.minutes_per_run + changes * self.plan.minutes_per_block_change


def _clean(v: float):
    v = round(float(v), 6)
    return int(v) if v == int(v) else v


class PlanError(ValueError):
    pass


def _check(plan: Plan) -> list[str]:
    notes = []
    k = len(plan.factors)
    if not 2 <= k <= MAX_FACTORS:
        raise PlanError(f"a central composite needs 2 to {MAX_FACTORS} factors, not {k}")
    keys = [f.key for f in plan.factors]
    if len(set(keys)) != k:
        raise PlanError("two factors have the same key")
    for f in plan.factors:
        if not f.low < f.mid < f.high:
            raise PlanError(f"{f.label}: the levels must be low < middle < high ({f.low}, {f.mid}, {f.high})")
        uneven = abs((f.mid - f.low) - (f.high - f.mid)) / (f.high - f.low)
        if uneven > 0.05:
            notes.append(f"{f.label}: uneven levels ({f.low:g} / {f.mid:g} / {f.high:g}); the middle sits at "
                         f"{f.real_code(f.mid):+.2f} in the fit's coding")
    for f in plan.factors:
        lo, hi = RIG_LIMITS.get(f.key, (-math.inf, math.inf))
        if f.low < lo or f.high > hi:
            raise PlanError(f"{f.label}: {f.low:g} to {f.high:g} is outside what the rig can set ({lo:g} to {hi:g})")
    for e in plan.extras:
        for k_, v in e.values.items():
            lo, hi = RIG_LIMITS.get(k_, (-math.inf, math.inf))
            if not lo <= v <= hi:
                raise PlanError(f"extra run {e.values}: {k_} {v:g} is outside what the rig can set ({lo:g} to {hi:g})")
    if plan.block_factor is not None and plan.block_factor not in keys:
        raise PlanError(f"block factor {plan.block_factor!r} is not one of the factors")
    if plan.fraction not in (None, "half"):
        raise PlanError("fraction must be None or 'half'")
    if plan.fraction == "half" and k < 3:
        raise PlanError("a half fraction needs at least 3 factors")
    if plan.centres < 1:
        raise PlanError("at least one centre run is needed (noise, curvature, drift)")
    if plan.first:
        bad = [k_ for k_, v in plan.first.items() if k_ not in keys or v not in ("low", "high")]
        if bad or set(plan.first) != set(keys):
            raise PlanError("the first run must give every factor as 'low' or 'high' (a corner)")
    for e in plan.extras:
        if set(e.values) != set(keys):
            raise PlanError(f"extra run {e.values}: give a value for every factor")
    return notes


def _corners(k: int, fraction: str | None) -> list[tuple]:
    pts = list(itertools.product((-1, 1), repeat=k))
    if fraction == "half":
        pts = [p for p in pts if p[-1] == int(np.prod(p[:-1]))]
    return pts


def _faces(k: int) -> list[tuple]:
    return [tuple(s if j == i else 0 for j in range(k)) for i in range(k) for s in (-1, 1)]


def _spread(items: list, centres: list, rng) -> list:
    """Interleave centres through `items`: one first, one last, the rest evenly between."""
    n_c = len(centres)
    if not items:
        return list(centres)
    if n_c == 1:
        return [centres[0]] + items
    out = []
    gaps = np.array_split(np.array(items, dtype=object), n_c - 1)
    for c, gap in zip(centres[:-1], gaps):
        out.append(c)
        out.extend(gap.tolist())
    out.append(centres[-1])
    return out


def build_sheet(plan: Plan) -> Sheet:
    findings = _check(plan)
    k = len(plan.factors)
    keys = [f.key for f in plan.factors]
    fs = {f.key: f for f in plan.factors}
    rng = np.random.default_rng(plan.seed)
    corners = _corners(k, plan.fraction)
    faces = _faces(k)
    centre = tuple(0 for _ in range(k))
    first = tuple(-1 if plan.first[x] == "low" else 1 for x in keys) if plan.first else None
    if first is not None and first not in corners:
        raise PlanError("the first run is not one of the design's corners (with a half fraction, choose a corner "
                        "in the fraction)")

    def label_of(p: tuple) -> tuple[str, str]:
        nz = [i for i, c in enumerate(p) if c != 0]
        if not nz:
            return rdet.CENTRE, "Centre"
        if len(nz) == k:
            return rdet.CORNER, "Corner"
        return rdet.FACE, f"{plan.factors[nz[0]].name} face"

    # (point, label override) items per block
    def item(p, label=None):
        kind, lab = label_of(p)
        return {"coded": p, "kind": kind, "label": label or lab}

    blocks: list[tuple[str | None, list]] = []
    if plan.block_factor is None:
        others = [item(p) for p in corners + faces]
        rng.shuffle(others)
        if first is not None:
            others.sort(key=lambda it: it["coded"] != first)
            others[0]["label"] = f"Corner, {plan.first_label}"
            rest = others[1:]
            body = _spread(rest, [item(centre) for _ in range(plan.centres)], rng)
            blocks.append((None, [others[0]] + body))
        else:
            blocks.append((None, _spread(others, [item(centre) for _ in range(plan.centres)], rng)))
    else:
        b = keys.index(plan.block_factor)
        bf = fs[plan.block_factor]
        order = list(plan.block_order)
        if first is not None:                         # the pressure-check block goes first
            lead_level = "low" if first[b] == -1 else "high"
            order.remove(lead_level)
            order.insert(0, lead_level)
        for level in order:
            code = {"low": -1, "mid": 0, "high": 1}[level]
            name = f"{bf.name} {bf.value(code):g} {bf.unit}".strip()
            if code == 0:
                body = [item(p) for p in faces if p[b] == 0]
                rng.shuffle(body)
                body = _spread(body, [item(centre) for _ in range(plan.centres)], rng)
            else:
                body = [item(p) for p in corners if p[b] == code]
                rng.shuffle(body)
                face = tuple(code if j == b else 0 for j in range(k))
                if first is not None and first[b] == code:
                    body.sort(key=lambda it: it["coded"] != first)
                    body[0]["label"] = f"Corner, {plan.first_label}"
                    lead, body = [body[0]], body[1:]
                else:
                    lead = []
                if plan.block_repeats:
                    body = lead + [item(face, "Block repeat (start)")] + body + [item(face, "Block repeat (end)")]
                else:
                    pos = int(rng.integers(0, len(body) + 1))
                    body = lead + body[:pos] + [item(face)] + body[pos:]
            blocks.append((name, body))

    # extras: inside the block whose level they sit at, else after every block
    tail = []
    for e in plan.extras:
        coded = tuple(fs[x].code(e.values[x]) for x in keys)
        inside = all(-1 - 1e-9 <= c <= 1 + 1e-9 for c in coded)
        kind = rdet.CHECK if inside else rdet.OUTSIDE
        label = e.label or ("Check run (not in the fit)" if inside else "Control (not in the fit)")
        it = {"coded": coded, "kind": kind, "label": label, "values": dict(e.values)}
        home = None
        if plan.block_factor is not None:
            b = keys.index(plan.block_factor)
            home = next((bl for bl in blocks
                         if any(abs(x["coded"][b] - coded[b]) < 1e-9 for x in bl[1])), None)
        if home is not None and len(home[1]) >= 2:
            pos = int(rng.integers(1, len(home[1])))          # never first or last of the block
            home[1].insert(pos, it)
        else:
            tail.append(it)
    if tail:
        blocks.append(("Checks" if plan.block_factor is not None else None, tail))

    rows = []
    n = 0
    for name, body in blocks:
        for it in body:
            n += 1
            values = it.get("values") or {x: fs[x].value(c) for x, c in zip(keys, it["coded"])}
            word = it["label"].split(" (")[0].lower()
            rows.append(SheetRow(n, name if plan.block_factor is not None else None, values,
                                 {x: round(float(c), 4) for x, c in zip(keys, it["coded"])}, it["kind"],
                                 it["label"], f"{plan.prefix} {n} {word}"))
    sheet = Sheet(plan, rows, findings, None)
    sheet.estimability = _estimability(sheet)
    if sheet.estimability is not None and not sheet.estimability.usable:
        e = sheet.estimability
        bad = ", ".join([t.name for t in e.dropped] + [f"{t.name} (VIF {t.vif:.0f})" for t in e.nearly_aliased])
        sheet.findings.append(f"the full quadratic is NOT usable from this sheet (aliased or nearly aliased: {bad}); "
                              + ("a half fraction of 4 factors aliases two-factor interactions in pairs: keep all "
                                 "16 corners" if plan.fraction == "half" and k == 4 else "add points"))
    if plan.fraction == "half":
        sheet.findings.append(f"half fraction of the corners: {len(corners)} instead of {2 ** k} (resolution {k})")
    if plan.block_factor is not None:
        sheet.findings.append(f"{fs[plan.block_factor].label} is fitted once per block, so its effect is tied to "
                              f"time of day; the block repeats show drift within each block")
    return sheet


# ---- estimability of a sheet (reuses rsm_detect) -------------------------------------------------------------

@dataclass
class _P:
    real: dict
    setting: tuple
    in_fit: bool = True


def _estimability(sheet: Sheet):
    fs = {f.key: f for f in sheet.plan.factors}
    keys = list(fs)
    pts = [_P({x: fs[x].real_code(r.values[x]) for x in keys}, tuple(r.values[x] for x in keys))
           for r in sheet.rows if r.kind not in rdet.NOT_FITTED]
    return rdet.estimability(pts, keys)


# ---- save / load / export -------------------------------------------------------------------------------------

def to_dict(sheet: Sheet) -> dict:
    return {"schema": SCHEMA, "plan": asdict(sheet.plan), "rows": [asdict(r) for r in sheet.rows],
            "findings": sheet.findings}


def plan_from_dict(d: dict) -> Plan:
    p = dict(d)
    p["factors"] = [FactorSpec(**f) for f in p["factors"]]
    p["extras"] = [Extra(**e) for e in p.get("extras", [])]
    p["block_order"] = tuple(p.get("block_order", ("low", "mid", "high")))
    return Plan(**p)


def save(sheet: Sheet, output_dir: Path) -> Path:
    from . import jobstate
    path = Path(output_dir) / SHEET_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    jobstate.atomic_write_json(path, to_dict(sheet))
    return path


def load(output_dir: Path) -> Sheet | None:
    """The saved sheet, rebuilt from its plan (same seed, same rows) and checked against the
    saved rows, so an edited file cannot silently disagree with its plan."""
    try:
        d = json.loads((Path(output_dir) / SHEET_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if d.get("schema") != SCHEMA:
        return None
    sheet = build_sheet(plan_from_dict(d["plan"]))
    if [asdict(r) for r in sheet.rows] != d.get("rows"):
        sheet.findings.append("the saved rows differ from what the saved plan builds: the plan's rows are used")
    return sheet


def table(sheet: Sheet) -> list[dict]:
    rows = []
    for r in sheet.rows:
        row = {"Run": r.run}
        if sheet.plan.block_factor is not None:
            row["Block"] = r.block
        for f in sheet.plan.factors:
            row[f.label] = r.values[f.key]
        row["Point type"] = r.label
        row["Notes to type"] = r.notes
        rows.append(row)
    return rows


def export(sheet: Sheet, output_dir: Path) -> list[Path]:
    """run_sheet.xlsx / .csv / .md, written atomically."""
    import pandas as pd
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = table(sheet)
    written = []
    p = out / f"{EXPORT_STEM}.csv"
    tmp = p.with_name(f".{p.name}.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    fsops.replace(tmp, p)
    written.append(p)
    p = out / f"{EXPORT_STEM}.xlsx"
    tmp = p.with_name(f".{p.stem}.tmp.xlsx")
    with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
        pd.DataFrame(rows).to_excel(xw, sheet_name="Run sheet", index=False)
        pd.DataFrame([{"": t} for t in summary(sheet)]).to_excel(xw, sheet_name="Summary", index=False)
    fsops.replace(tmp, p)
    written.append(p)
    p = out / f"{EXPORT_STEM}.md"
    tmp = p.with_name(f".{p.name}.tmp")
    head = list(rows[0])
    lines = [f"# Run sheet ({len(sheet.rows)} runs)\n"] + [f"- {t}" for t in summary(sheet)] + [""]
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "|".join("---" for _ in head) + "|")
    lines += ["| " + " | ".join(str(r[h]) for h in head) + " |" for r in rows]
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fsops.replace(tmp, p)
    written.append(p)
    return written


def summary(sheet: Sheet) -> list[str]:
    c = sheet.counts()
    k = len(sheet.plan.factors)
    out = [f"{k} factors: " + "; ".join(f"{f.label} {f.low:g} / {f.mid:g} / {f.high:g}" for f in sheet.plan.factors),
           f"{len(sheet.rows)} runs: " + ", ".join(f"{n} {rdet.KIND_TEXT[kk]}" for kk, n in sorted(c.items())),
           f"about {sheet.minutes() / 60:.1f} h at {sheet.plan.minutes_per_run:g} min a run"
           + (f" and {sheet.plan.minutes_per_block_change:g} min a block change" if sheet.plan.block_factor else ""),
           f"seed {sheet.plan.seed} (the same seed rebuilds the same order)"]
    e = sheet.estimability
    if e is not None:
        out.append(f"full quadratic {'estimable' if e.usable else 'NOT usable'}: {e.n_params} terms, {e.n_fit} design runs, "
                   f"{e.df_pure_error} pure-error df, {e.df_lack_of_fit} lack-of-fit df")
    return out + sheet.findings


# ---- compare a built sheet with the captured runs ------------------------------------------------------------

PLANNED, OUT_OF_ORDER, DIFFERS, NOT_CAPTURED, NOT_ON_SHEET = (
    "as planned", "out of order", "settings differ", "not captured yet", "not on the sheet")


@dataclass
class Match:
    status: str
    row: SheetRow | None
    point: object | None             # rsm_detect.RunPoint
    note: str = ""


def compare(sheet: Sheet, detected) -> list[Match]:
    """Each sheet row matched to a captured run: by the run number in its Notes when there is one
    (then the settings are checked), else by identical settings in capture order. Captured runs
    with no sheet row are listed too."""
    keys = [f.key for f in sheet.plan.factors]
    pts = [p for p in detected.points if p.included]
    for f in keys:
        if pts and f not in pts[0].values:
            return [Match(NOT_CAPTURED, r, None, f"the captured runs have no factor '{f}'") for r in sheet.rows]
    used: set = set()
    out: list[Match] = []
    by_number = {p.noted_run: p for p in pts if p.noted_run is not None}

    def same(r: SheetRow, p) -> bool:
        return all(p.values.get(x) == r.values[x] for x in keys)

    for r in sheet.rows:
        p = by_number.get(r.run)
        if p is not None and id(p) not in used:
            used.add(id(p))
            if same(r, p):
                out.append(Match(PLANNED, r, p))
            else:
                diff = ", ".join(f"{x} {p.values.get(x)} (planned {r.values[x]})" for x in keys
                                 if p.values.get(x) != r.values[x])
                out.append(Match(DIFFERS, r, p, diff))
            continue
        cand = [q for q in sorted(pts, key=lambda q: q.order) if id(q) not in used and q.noted_run is None
                and same(r, q)]
        if cand:
            used.add(id(cand[0]))
            out.append(Match(PLANNED, r, cand[0], "matched by settings (no run number in its Notes)"))
        else:
            out.append(Match(NOT_CAPTURED, r, None))
    # order: matched runs whose capture order disagrees with the sheet's
    matched = [m for m in out if m.point is not None and m.point.order]
    for a, b in zip(matched, matched[1:]):
        if b.point.order < a.point.order and b.status == PLANNED:
            b.status = OUT_OF_ORDER
            b.note = f"captured before run {a.row.run}"
    for p in pts:
        if id(p) not in used:
            out.append(Match(NOT_ON_SHEET, None, p, f"{p.name[:6]}: {', '.join(f'{x} {p.values.get(x)}' for x in keys)}"))
    return out
