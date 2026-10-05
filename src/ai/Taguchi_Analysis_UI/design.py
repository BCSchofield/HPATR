"""design.py -- the Taguchi design: which factors, which levels, which runs are
replicates of which. No Qt in here.

AUTO-DETECT, FULLY EDITABLE. `detect()` proposes a design from the discovered runs
(run_discovery.RunInfo); every part of it can then be changed by the user: factors
renamed / added (from ANY run_summary.xlsx field) / removed, a run's level
overridden, a run dropped. A run whose factor values are incomplete is listed as
UNASSIGNED rather than silently guessed, and the user fixes it by giving it values.

REPLICATES ARE DETECTED TWO INDEPENDENT WAYS AND CROSS-CHECKED, and neither is trusted
alone:
    (a) the run_summary.xlsx Notes field ("Taguchi ReRun 6 - Repeat 2", or on the
        older 10/01 runs just "Taguchi 6");
    (b) grouping by identical factor levels.
They agree when the runs sharing a trial number are exactly the runs sharing a set of
levels. Disagreement means the folder name/workbook and the notes disagree about what was
run -- reported per run, never resolved silently. (Folder order is NOT condition order:
111625 is ReRun 5 and precedes 112253, which is ReRun 4, so grouping is always by levels.)

The balance / orthogonality / replication checks in `diagnose()` are the design-level
half of what the statistics (phase 8) need: an aliased pair of factors is not
estimable, so the report says so instead of producing a number.
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import run_discovery as rd

SCHEMA = 1
DESIGN_FILENAME = "taguchi_design.json"

# Factors the app knows how to read from a run. Labels mirror
# taguchi_analysis.FACTOR_LABEL (display text only; nothing depends on them).
BUILTIN = {
    "sccm": ("Gas flow (sccm)", "attr", "sccm"),
    "rpm": ("Bubbler RPM", "attr", "rpm"),
    "sps": ("Silicone (steps/s)", "attr", "sps"),
    "orifice": ("Orifice (mm)", "attr", "orifice_mm"),
    "bh": ("Bubbler height (mm)", "attr", "bubbler_height"),
}
DEFAULT_FACTORS = ("sccm", "rpm", "sps")
# workbook fields that are not candidate factors
NOT_FACTORS = ("Timestamp", "Notes")

# The Notes field, as actually written on the lab runs:
#   2026/10/05  "Taguchi ReRun 6 - Repeat 2\nWITH NOZZLE ADAPTER"
#   2026/10/01  "Taguchi 6"            (no repeat number at all)
TRIAL_RE = re.compile(r"(?:taguchi|trial|re-?run|run)\s*#?\s*(\d+)", re.I)
REPEAT_RE = re.compile(r"(?:repeat|rep|replicate)\s*#?\s*(\d+)", re.I)


def parse_notes(notes: str | None) -> tuple[int | None, int | None]:
    """(trial, repeat) from a Notes field; either may be None. Never raises."""
    text = notes or ""
    t, r = TRIAL_RE.search(text), REPEAT_RE.search(text)
    return (int(t.group(1)) if t else None), (int(r.group(1)) if r else None)


# ---- model ---------------------------------------------------------------------

@dataclass
class Factor:
    key: str                       # stable id; never changes when the label is edited
    label: str                     # what the user sees; editable
    source: str                    # "attr" (a RunInfo value) | "workbook" (any xlsx field)
    field: str                     # RunInfo attribute, or workbook field name
    pick: str = "max"              # for workbook RANGE values: max | min | mean
    numeric: bool = True


@dataclass
class Row:
    path: Path
    name: str
    date: str | None = None
    time: str | None = None
    included: bool = True
    detected: dict = field(default_factory=dict)       # factor key -> value read from the run
    overrides: dict = field(default_factory=dict)      # factor key -> value typed by the user
    notes: str = ""
    trial: int | None = None
    repeat: int | None = None
    n_issues: int = 0

    def value(self, key: str):
        return self.overrides[key] if key in self.overrides else self.detected.get(key)


def norm(v):
    """Level values compare equal despite float noise; whole numbers read as ints."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        f = round(float(v), 6)
        return int(f) if f == int(f) else f
    return str(v).strip()


def read_factor(run: rd.RunInfo, f: Factor):
    """One factor's value for one run, or None if the run has no such value."""
    if f.source == "attr":
        return norm(getattr(run, f.field, None))
    v = run.meta.get(f.field)
    if v is None or v.missing:
        return None
    num = v.pick(f.pick)
    return norm(num) if num is not None else (v.text or None)


@dataclass
class Design:
    factors: list[Factor] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    runs: dict = field(default_factory=dict)           # path -> RunInfo (not saved)
    customised: bool = False                           # factors edited by the user

    # ---- factors -------------------------------------------------------------
    def factor(self, key: str) -> Factor:
        return next(f for f in self.factors if f.key == key)

    def has(self, key: str) -> bool:
        return any(f.key == key for f in self.factors)

    def _refresh(self, f: Factor) -> None:
        for row in self.rows:
            run = self.runs.get(row.path)
            row.detected[f.key] = read_factor(run, f) if run else row.detected.get(f.key)
        vals = [row.detected[f.key] for row in self.rows if row.detected.get(f.key) is not None]
        f.numeric = all(isinstance(v, (int, float)) for v in vals) if vals else True

    def add_factor(self, field_id: str, label: str | None = None, pick: str = "max") -> Factor:
        """Add a built-in factor by key ("orifice", "bh", ...) or ANY run_summary.xlsx
        field by its name ("GLR", "FPS", "Motor Travel (mm)", ...)."""
        if field_id in BUILTIN:
            key, (lab, source, fld) = field_id, BUILTIN[field_id]
        else:
            key, lab, source, fld = f"wb:{field_id}", field_id, "workbook", field_id
        if self.has(key):
            raise ValueError(f"'{label or lab}' is already a factor")
        f = Factor(key=key, label=label or lab, source=source, field=fld, pick=pick)
        self._refresh(f)
        self.factors.append(f)
        self.customised = True
        return f

    def remove_factor(self, key: str) -> None:
        self.factors = [f for f in self.factors if f.key != key]
        for row in self.rows:
            row.detected.pop(key, None)
            row.overrides.pop(key, None)
        self.customised = True

    def rename_factor(self, key: str, label: str) -> None:
        label = label.strip()
        if not label:
            raise ValueError("a factor needs a name")
        if any(f.label == label and f.key != key for f in self.factors):
            raise ValueError(f"another factor is already called '{label}'")
        self.factor(key).label = label
        self.customised = True

    def set_pick(self, key: str, pick: str) -> None:
        f = self.factor(key)
        f.pick = pick
        self._refresh(f)
        self.customised = True

    def candidates(self) -> list[tuple[str, str]]:
        """(field id, description) for everything that could be added as a factor."""
        out = [(k, f"{lab}   [from the run folder / workbook]") for k, (lab, _, _) in BUILTIN.items()
               if not self.has(k)]
        seen: dict[str, None] = {}
        for run in self.runs.values():
            for name in run.meta:
                if name not in NOT_FACTORS:
                    seen.setdefault(name)
        for name in seen:
            if not self.has(f"wb:{name}"):
                out.append((name, f"{name}   [workbook field]"))
        return out

    # ---- rows ----------------------------------------------------------------------
    def set_value(self, row: Row, key: str, value) -> None:
        """A user edit. Typing the detected value back removes the override."""
        value = norm(value)
        if value == row.detected.get(key):
            row.overrides.pop(key, None)
        else:
            row.overrides[key] = value

    def active(self) -> list[Row]:
        return [r for r in self.rows if r.included]

    def levels_of(self, row: Row) -> tuple | None:
        vals = tuple(row.value(f.key) for f in self.factors)
        return None if not self.factors or any(v is None for v in vals) else vals

    def reset(self, runs: list[rd.RunInfo]) -> "Design":
        return detect(runs)

    def update_runs(self, runs: list[rd.RunInfo]) -> None:
        """The selection changed: keep every edit (factors, overrides, dropped runs) for
        runs still present, add new runs with the detected values, drop vanished ones."""
        self.runs = {r.path: r for r in runs}
        keep = {row.path: row for row in self.rows}
        rows = []
        for run in runs:
            row = keep.get(run.path) or _row_for(run)
            row.name, row.date, row.time = run.name, run.date, run.time
            row.notes = run.notes
            row.trial, row.repeat = parse_notes(run.notes)
            row.n_issues = len(run.issues)
            rows.append(row)
        self.rows = rows
        if self.customised:
            for f in self.factors:
                self._refresh(f)
        else:
            self.factors = _detect_factors(self.rows, self.runs)
            for f in self.factors:
                self._refresh(f)

    # ---- persistence ---------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA, "customised": self.customised,
            "factors": [{"key": f.key, "label": f.label, "source": f.source, "field": f.field,
                         "pick": f.pick} for f in self.factors],
            "runs": [{"path": str(r.path), "name": r.name, "included": r.included,
                      "overrides": r.overrides} for r in self.rows],
        }

    def apply_saved(self, saved: dict) -> list[str]:
        """Re-apply a saved design onto THIS design's runs. Returns notes for the user
        (runs in the file that are no longer selected, fields no run has any more)."""
        notes = []
        if not isinstance(saved, dict) or saved.get("schema") != SCHEMA:
            return ["the saved design is from a different version and was ignored"]
        if saved.get("customised"):
            self.factors = []
            for f in saved.get("factors", []):
                fac = Factor(key=f["key"], label=f["label"], source=f["source"], field=f["field"],
                             pick=f.get("pick", "max"))
                self._refresh(fac)
                self.factors.append(fac)
                if fac.source == "workbook" and not any(
                        fac.field in r.meta for r in self.runs.values()):
                    notes.append(f"'{fac.label}': none of the selected runs has a "
                                 f"'{fac.field}' field in run_summary.xlsx")
            self.customised = True
        else:
            # factors were never edited: keep today's detection, but restore labels
            labels = {f["key"]: f["label"] for f in saved.get("factors", [])}
            for f in self.factors:
                f.label = labels.get(f.key, f.label)
        by_path = {str(r.path): r for r in self.rows}
        missing = 0
        for s in saved.get("runs", []):
            row = by_path.get(s["path"])
            if row is None:
                missing += 1
                continue
            row.included = bool(s.get("included", True))
            row.overrides = {k: norm(v) for k, v in (s.get("overrides") or {}).items()
                             if any(f.key == k for f in self.factors)}
        if missing:
            notes.append(f"{missing} run(s) in the saved design are not in the current selection")
        return notes


def _row_for(run: rd.RunInfo) -> Row:
    trial, repeat = parse_notes(run.notes)
    return Row(path=run.path, name=run.name, date=run.date, time=run.time, notes=run.notes,
               trial=trial, repeat=repeat, n_issues=len(run.issues))


def _detect_factors(rows: list[Row], runs: dict) -> list[Factor]:
    """Factors = the built-in candidates whose levels VARY across the runs; if none vary
    (a single run, or a constant selection) fall back to the usual three so the table has
    columns the user can fill in."""
    cands = []
    for key, (label, source, fld) in BUILTIN.items():
        f = Factor(key=key, label=label, source=source, field=fld)
        vals = {read_factor(runs[r.path], f) for r in rows if r.path in runs}
        vals.discard(None)
        cands.append((f, len(vals)))
    varying = [f for f, n in cands if n >= 2]
    keys = {f.key for f in varying} or set(DEFAULT_FACTORS)
    return [f for f, _ in cands if f.key in keys]


def detect(runs: list[rd.RunInfo]) -> Design:
    d = Design()
    d.runs = {r.path: r for r in runs}
    d.rows = [_row_for(r) for r in runs]
    d.factors = _detect_factors(d.rows, d.runs)
    for f in d.factors:
        d._refresh(f)
    return d


# ---- assignment + the two-way replicate cross-check -------------------------------------------

AGREE, TUPLE_ONLY, CONFLICT, UNASSIGNED, DROPPED = ("agree", "tuple-only", "conflict",
                                                    "unassigned", "dropped")
STATUS_TEXT = {
    AGREE: "agrees",
    TUPLE_ONLY: "no trial in Notes",
    CONFLICT: "CONFLICT",
    UNASSIGNED: "UNASSIGNED",
    DROPPED: "dropped",
}


@dataclass
class Condition:
    index: int
    label: str                       # "T4" when the Notes name a trial, else "C4"
    levels: tuple
    rows: list[Row]
    trial: int | None


@dataclass
class RowResult:
    status: str
    condition: Condition | None = None
    replicate: int | None = None     # shown number: Notes' repeat if usable, else time order
    detail: str = ""


@dataclass
class Assignment:
    conditions: list[Condition]
    result: dict                     # row.path -> RowResult
    notes_available: bool

    def of(self, row: Row) -> RowResult:
        return self.result[row.path]

    @property
    def n_runs(self) -> int:
        return sum(len(c.rows) for c in self.conditions)

    def counts(self) -> dict:
        out: dict = {}
        for r in self.result.values():
            out[r.status] = out.get(r.status, 0) + 1
        return out


def _chrono(rows):
    return sorted(rows, key=lambda r: (r.date or "", r.time or "", r.name))


def assign(design: Design) -> Assignment:
    active = design.active()
    groups: dict[tuple, list[Row]] = {}
    unassigned = []
    for r in active:
        lv = design.levels_of(r)
        (groups.setdefault(lv, []) if lv is not None else unassigned).append(r)
    ordered = sorted(groups.items(), key=lambda kv: (_chrono(kv[1])[0].date or "",
                                                     _chrono(kv[1])[0].time or ""))
    # Only runs whose levels are KNOWN take part in the comparison. A run with unknown
    # levels (UNASSIGNED) cannot contradict anything, and counting it here would make its
    # perfectly good siblings look conflicted.
    by_trial: dict[int, list[Row]] = {}
    for rows_ in groups.values():
        for r in rows_:
            if r.trial is not None:
                by_trial.setdefault(r.trial, []).append(r)
    notes_available = any(r.trial is not None for r in active)

    conditions, result = [], {}
    for r in design.rows:
        if not r.included:
            result[r.path] = RowResult(DROPPED, detail="left out of the analysis")
    for r in unassigned:
        missing = [f.label for f in design.factors if r.value(f.key) is None]
        why = ("no factors are defined" if not design.factors
               else "no value for " + ", ".join(missing))
        result[r.path] = RowResult(UNASSIGNED, detail=why + " -- give it values to include it")

    for idx, (levels, rows) in enumerate(ordered, 1):
        rows = _chrono(rows)
        trials = {r.trial for r in rows if r.trial is not None}
        trial = trials.pop() if len(trials) == 1 else None
        cond = Condition(idx, f"T{trial}" if trial is not None else f"C{idx}", levels, rows, trial)
        conditions.append(cond)
        group = {r.path for r in rows}
        repeats = [r.repeat for r in rows if r.repeat is not None]
        dup = {x for x in repeats if repeats.count(x) > 1}
        for ordinal, r in enumerate(rows, 1):
            rep = r.repeat if (r.repeat is not None and r.repeat not in dup) else ordinal
            if r.trial is None:
                res = RowResult(TUPLE_ONLY, cond, rep,
                                "Notes do not name a trial (grouped by factor levels only)")
            else:
                same_trial = {x.path for x in by_trial[r.trial]}
                if same_trial != group:
                    # the root cause comes first: the Notes and the levels disagree about
                    # which runs belong together (a repeat number shared by two runs is
                    # usually just a symptom of that)
                    other = [x for x in by_trial[r.trial] if x.path not in group]
                    where = (f"also named trial {r.trial}: {', '.join(x.name[:6] for x in other)}"
                             if other else
                             "the other runs at these levels belong to a different trial")
                    res = RowResult(CONFLICT, cond, rep,
                                    f"Notes say trial {r.trial}, but the factor levels group it "
                                    f"differently ({where})")
                elif r.repeat in dup:
                    res = RowResult(CONFLICT, cond, rep,
                                    f"'Repeat {r.repeat}' appears more than once in this condition")
                else:
                    res = RowResult(AGREE, cond, rep)
            result[r.path] = res
    return Assignment(conditions, result, notes_available)


# ---- headline + diagnostics ----------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    level: str          # ok | info | warn | error
    text: str


def outside_design(design: Design, a: Assignment | None = None) -> list[Row]:
    """Runs that are probably not part of the experiment: their Notes name no trial while
    other runs' Notes do (e.g. 10/01's 'MAX TEST' and its blank-note run). Only offered when
    the Notes can tell the two apart; never applied automatically."""
    a = a or assign(design)
    if not a.notes_available:
        return []
    return [r for r in design.active() if a.of(r).status == TUPLE_ONLY]


def analysis_factors(design: Design, a: Assignment | None = None) -> list[Factor]:
    """Factors with at least two levels among the assigned runs; a constant factor
    cannot be analysed (and the user is told)."""
    a = a or assign(design)
    out = []
    for i, f in enumerate(design.factors):
        if len({c.levels[i] for c in a.conditions}) >= 2:
            out.append(f)
    return out


def headline(design: Design, a: Assignment | None = None) -> tuple[str, str]:
    """(text, level) for the banner above the table."""
    a = a or assign(design)
    c = a.counts()
    n, ncond = a.n_runs, len(a.conditions)
    if not design.rows:
        return "No runs selected: tick runs on the Batch tab.", "info"
    reps = sorted({len(x.rows) for x in a.conditions})
    if not reps:
        return "No run has a complete set of factor levels yet.", "error"
    design_txt = (f"{n} runs = {ncond} condition{'s' if ncond != 1 else ''} × "
                  f"{reps[0]} replicate{'s' if reps[0] != 1 else ''}"
                  if len(reps) == 1 else
                  f"{n} runs in {ncond} conditions, {reps[0]}–{reps[-1]} replicates (unbalanced)")
    bad = c.get(CONFLICT, 0) + c.get(UNASSIGNED, 0)
    if c.get(CONFLICT):
        return (f"{design_txt}: {c[CONFLICT]} run(s) where the Notes and the factor levels "
                f"DISAGREE about the replicates", "error")
    if c.get(UNASSIGNED):
        return f"{design_txt}; {c[UNASSIGNED]} run(s) cannot be assigned yet", "warn"
    if not a.notes_available:
        return (f"{design_txt}, grouped by factor levels only (the Notes name no trial, so "
                f"there is nothing to cross-check)", "info")
    if c.get(AGREE) == n and not bad:
        return f"{design_txt}: replicates confirmed two independent ways (Notes and factor levels)", "ok"
    return (f"{design_txt}: {c.get(AGREE, 0)} confirmed by both methods, "
            f"{c.get(TUPLE_ONLY, 0)} by factor levels only (no trial in their Notes)", "info")


def _crosstab(design: Design, a: Assignment, i: int, j: int):
    levels_i = sorted({c.levels[i] for c in a.conditions}, key=str)
    levels_j = sorted({c.levels[j] for c in a.conditions}, key=str)
    cells = {(x, y): 0 for x in levels_i for y in levels_j}
    for c in a.conditions:
        cells[(c.levels[i], c.levels[j])] += len(c.rows)
    return levels_i, levels_j, cells


def diagnose(design: Design) -> list[Finding]:
    """Balance, orthogonality, replication and a few things that quietly ruin a
    Taguchi analysis. Each finding says what it means for the statistics."""
    a = assign(design)
    out: list[Finding] = []
    c = a.counts()
    if c.get(UNASSIGNED):
        out.append(Finding("warn", f"{c[UNASSIGNED]} run(s) are left out until they have a value "
                                   f"for every factor (see the UNASSIGNED rows)."))
    if c.get(CONFLICT):
        out.append(Finding("error", f"{c[CONFLICT]} run(s) are named as one trial in their Notes but "
                                    f"sit with different levels (or the reverse). One of the two is "
                                    f"wrong; fix the Notes, or edit the levels."))
    if c.get(DROPPED):
        out.append(Finding("info", f"{c[DROPPED]} run(s) are deliberately left out."))
    stray = outside_design(design, a)
    if stray:
        names = ", ".join(f"{r.time or r.name[:6]}" + (f" ('{r.notes.strip()[:20]}')" if r.notes.strip() else "")
                          for r in stray[:5])
        out.append(Finding("warn", f"{len(stray)} run(s) have no trial in their Notes while the others do "
                                   f"({names}). They look like side tests outside the design, and extra "
                                   f"levels like these make the design non-orthogonal or partly aliased. Use "
                                   f"'Leave out runs with no trial' if that is right."))
    if not a.conditions:
        return out or [Finding("info", "Nothing to analyse yet.")]

    days = {r.date for c_ in a.conditions for r in c_.rows if r.date}
    if len(days) > 1:
        out.append(Finding("warn", f"Runs come from {len(days)} different days. Day is not a factor in "
                                   f"this design, so any day-to-day difference is mixed into the error."))
    if any(f.source == "workbook" and "Flow Range" in f.field for f in design.factors):
        out.append(Finding("warn", "A factor uses the ACHIEVED flow (the workbook's flow range). It "
                                   "differs a little between replicates by construction, so every run "
                                   "becomes its own level and the design looks unbalanced. Use the "
                                   "setpoint ('Gas flow (sccm)', from the folder name)."))

    usable = analysis_factors(design, a)
    for f in design.factors:
        if f not in usable:
            out.append(Finding("warn", f"'{f.label}' has a single level, so it cannot be analysed and "
                                       f"is left out of the statistics."))
    idx = {f.key: i for i, f in enumerate(design.factors)}

    for f in usable:
        i = idx[f.key]
        counts = {}
        for cond in a.conditions:
            counts[cond.levels[i]] = counts.get(cond.levels[i], 0) + len(cond.rows)
        shown = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items(), key=lambda kv: str(kv[0])))
        if len(set(counts.values())) == 1:
            out.append(Finding("ok", f"{f.label}: {len(counts)} levels, balanced ({shown})."))
        else:
            out.append(Finding("warn", f"{f.label}: levels are not used equally often ({shown}). The "
                                       f"analysis still runs, using an unbalanced-design method."))
        if len(counts) > 6:
            out.append(Finding("warn", f"{f.label} has {len(counts)} distinct levels: is it really a "
                                       f"factor, or a measured value that varies run to run?"))

    # Aliasing means LOST RANK, not merely a missing combination of levels. One definition,
    # shared with the ANOVA (stats.estimability), so the tab and the report cannot disagree.
    from . import stats
    lv = {f.key: [c.levels[idx[f.key]] for c in a.conditions for _ in c.rows] for f in usable}
    est = stats.estimability(lv) if usable else {}
    for f in usable:
        got, nominal = est.get(f.key, (0, 0))
        if got == 0:
            out.append(Finding("error", f"{f.label} is ALIASED: its levels only ever occur together with "
                                        f"particular levels of other factors, so its effect cannot be "
                                        f"separated from theirs. The report will give no numbers for it."))
        elif got < nominal:
            out.append(Finding("warn", f"{f.label} is partly aliased: only {got} of its {nominal} degrees "
                                       f"of freedom can be estimated (a level occurs only together with "
                                       f"one level of another factor)."))
    for f, g in itertools.combinations(usable, 2):
        li, lj, cells = _crosstab(design, a, idx[f.key], idx[g.key])
        empty = [k for k, v in cells.items() if v == 0]
        if empty:
            more = f" (and {len(empty) - 1} other combination(s))" if len(empty) > 1 else ""
            out.append(Finding("warn", f"{f.label} × {g.label} is not orthogonal: no run has "
                                       f"{empty[0][0]} with {empty[0][1]}{more}. Both effects are still "
                                       f"analysed, but they are correlated, so an unbalanced-design "
                                       f"method is used."))
        elif len(set(cells.values())) > 1:
            out.append(Finding("warn", f"{f.label} × {g.label} is not fully balanced: the "
                                       f"combinations are not equally replicated, so the two effects "
                                       f"are partly confounded."))
        else:
            out.append(Finding("ok", f"{f.label} × {g.label}: every combination appears, equally "
                                     f"often (orthogonal)."))

    n, ncond = a.n_runs, len(a.conditions)
    sizes = sorted({len(x.rows) for x in a.conditions})
    if sizes == [1]:
        out.append(Finding("warn", f"No replicates: {n} runs, {ncond} conditions. The error term has "
                                   f"to come from the design itself (the unassigned-column method), "
                                   f"which tests against interactions rather than noise."))
    elif len(sizes) == 1:
        out.append(Finding("ok", f"{sizes[0]} replicates of every condition: the error comes from the "
                                 f"replicates themselves ({n - ncond} degrees of freedom)."))
    else:
        thin = [x.label for x in a.conditions if len(x.rows) == sizes[0]]
        out.append(Finding("warn", f"Replication is uneven ({sizes[0]}–{sizes[-1]} per condition; "
                                   f"fewest: {', '.join(thin[:6])}). Error degrees of freedom: "
                                   f"{n - ncond}."))
    return out


# ---- files ---------------------------------------------------------------------------------------------

def design_path(output_dir: Path) -> Path:
    return Path(output_dir) / DESIGN_FILENAME


def save(design: Design, output_dir: Path) -> Path:
    from . import jobstate
    path = design_path(output_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    jobstate.atomic_write_json(path, design.to_dict())
    return path


def load_saved(output_dir: Path) -> dict | None:
    p = design_path(output_dir)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
