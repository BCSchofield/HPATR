"""run_sheet.py -- a run sheet for GUI_Clean (2026-10-14): load a list of runs, fill in each run's settings, and
keep track of which are done. No Qt, so it can be tested on its own; GUI_Clean's Run sheet tab drives it.

A sheet is a .csv or .xlsx with one row per run and a header row. Column names are matched loosely
(case and spacing ignored), so the analysis app's next_runs.csv works as it is:

    run / #                         the run's number on the sheet
    orifice (mm) / insert (mm)      the insert, e.g. 1.2
    gas flow (sccm) / gas (sccm)    the gas set point
    bubbler rpm / rpm               blank or 0: no rotation (the RPM box is cleared)
    silicone (steps/s) / feed / speed (steps/s)
                                    0 = a static run (gas and logging only, no traverse)
    motor travel (mm) / travel (mm) optional; blank keeps what is in the box
    orifice length (mm)             optional; blank keeps what is in the box
    notes to type / notes           typed into Notes
    instructions / why this run     shown above the table (e.g. a Cd test's gas ladder); one that starts
                                    with "SETUP" also pops up when the run is filled in
    save under / folder             optional: where the run folder goes, relative to the LaCie (e.g.
                                    Calibration/Imaging Work); blank = Experiments, as always
    post-trigger (s) / capture (s)  optional: the camera's post-trigger for this run (e.g. 1 for a
                                    calibration capture); blank = the campaign standard

Progress (done / redo / skipped per row, which row is next, each finished run's folder) is kept in a small
JSON file on the LOCAL disk (~/.hpatr/run_sheet_state.json), never on the LaCie, so a busy drive cannot hold
up the GUI.
"""
from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

PENDING, DONE, REDO, SKIPPED = "pending", "done", "redo", "skipped"
STATUSES = (PENDING, DONE, REDO, SKIPPED)
BAD_RUN_NOTE = "[bad run, redone]"      # added to a run's Notes when it is redone, so the analysis can drop it

# column -> the header names that mean it (normalised: lower case, no spaces, brackets or punctuation)
COLUMNS = {
    "run": ("run", "#", "runno", "runnumber", "no"),
    "orifice": ("orificemm", "insertmm", "orifice", "insert", "nozzlemm"),
    "gas": ("gasflowsccm", "gassccm", "gas", "flowsccm", "sccm", "targetflowsccm"),
    "rpm": ("bubblerrpm", "rpm"),
    "feed": ("siliconestepss", "feedstepss", "speedstepss", "feed", "speed", "silicone", "motorspeedstepss"),
    "travel": ("motortravelmm", "travelmm", "travel", "distancemm"),
    "orifice_length": ("orificelengthmm", "lengthmm"),
    "notes": ("notestotype", "notes"),
    "instructions": ("instructions", "whythisrun", "purpose", "why"),
    "save_under": ("saveunder", "savefolder", "folder"),
    "post_trigger": ("posttriggers", "posttrigger", "captures", "capture"),
}


class SheetError(ValueError):
    pass


def _key(header) -> str:
    return re.sub(r"[^a-z0-9#]", "", str(header or "").lower())


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    s = re.sub(r"\s*(mm|sccm|rpm|steps/s)$", "", s, flags=re.I)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(v) -> str:
    """A number as the GUI's boxes want it: 11000 not 11000.0, 1.2 not 1.20."""
    return "" if v is None else f"{v:g}"


@dataclass
class Row:
    number: str
    orifice: float | None
    gas: float | None
    rpm: float | None
    feed: float | None
    travel: float | None = None
    orifice_length: float | None = None
    notes: str = ""
    instructions: str = ""
    save_under: str = ""                 # relative to the LaCie; "" = Experiments
    post_trigger_s: float | None = None  # None = the campaign standard

    @property
    def static(self) -> bool:
        return (self.feed or 0) <= 0

    def label(self) -> str:
        bits = [f"{_fmt(self.orifice)} mm" if self.orifice is not None else "",
                f"{self.gas:,.0f} sccm" if self.gas is not None else "",
                f"{_fmt(self.rpm)} rpm" if self.rpm else "no rotation",
                "static (speed 0)" if self.static else f"feed {self.feed:,.0f}"]
        return " · ".join(b for b in bits if b)

    def fields(self) -> dict:
        """The GUI box values for this run. A key is left out when the sheet leaves it blank (the box keeps
        what it has); rpm is always set ('' clears the box: no rotation)."""
        out = {"rpm": _fmt(self.rpm) if self.rpm else "", "notes": self.notes}
        if self.gas is not None:
            out["flow"] = _fmt(self.gas)
        if self.feed is not None:
            out["speed"] = f"{int(round(self.feed))}"
        if self.travel is not None:
            out["distance"] = _fmt(self.travel)
        if self.orifice is not None:
            out["orifice"] = f"{_fmt(self.orifice)}mm"            # GUI_Clean's combo items: "0.5mm", "1.2mm", "1mm"
        if self.orifice_length is not None:
            out["orifice_length"] = _fmt(self.orifice_length)
        if self.post_trigger_s is not None:
            out["post_trigger"] = _fmt(self.post_trigger_s)
        return out

    def folder_parts(self) -> list[str]:
        """save_under as path parts ([] = the default, Experiments); never absolute or escaping upwards."""
        parts = [p for p in re.split(r"[\\/]+", self.save_under.strip()) if p not in ("", ".")]
        if any(p == ".." or ":" in p for p in parts):
            raise SheetError(f"run {self.number}: 'save under' must be a folder on the LaCie, not "
                             f"{self.save_under!r}")
        return parts


def _read_table(path: Path) -> list[list]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.worksheets[0]
            return [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.reader(f)]


def load(path) -> list[Row]:
    """The sheet's runs, in order. Raises SheetError with a reason a person can act on."""
    path = Path(path)
    try:
        table = [r for r in _read_table(path) if any(str(c or "").strip() for c in r)]
    except (OSError, ValueError, KeyError) as e:
        raise SheetError(f"could not read {path.name}: {e}") from e
    if len(table) < 2:
        raise SheetError(f"{path.name} has no runs under its header row")
    head = [_key(h) for h in table[0]]
    col = {}
    for name, keys in COLUMNS.items():
        for k in keys:                                  # the most specific name first
            if k in head:
                col[name] = head.index(k)
                break
    missing = [n for n in ("gas", "feed") if n not in col]
    if missing:
        raise SheetError(f"{path.name}: no column for {' or '.join(missing)} "
                         f"(headers: {', '.join(str(h) for h in table[0])})")
    rows = []
    for i, r in enumerate(table[1:], 1):
        get = lambda n: r[col[n]] if n in col and col[n] < len(r) else None
        gas, feed = _num(get("gas")), _num(get("feed"))
        if gas is None and feed is None:
            continue                                     # a note line, not a run
        row = Row(number=str(get("run") if get("run") not in (None, "") else i).strip(),
                  orifice=_num(get("orifice")), gas=gas, rpm=_num(get("rpm")), feed=feed,
                  travel=_num(get("travel")), orifice_length=_num(get("orifice_length")),
                  notes=str(get("notes") or "").strip(), instructions=str(get("instructions") or "").strip(),
                  save_under=str(get("save_under") or "").strip(), post_trigger_s=_num(get("post_trigger")))
        row.folder_parts()                               # refuse a bad folder at load, not at Start
        if row.post_trigger_s is not None and row.post_trigger_s <= 0:
            raise SheetError(f"run {row.number}: post-trigger must be above 0 s")
        rows.append(row)
    if not rows:
        raise SheetError(f"{path.name}: no row has a gas flow or a feed")
    return rows


@dataclass
class Progress:
    sheet: str
    status: list[str]
    current: int = 0
    folders: dict = field(default_factory=dict)        # row index (str) -> [run folders, oldest first]
    updated: str = ""

    @classmethod
    def new(cls, sheet, n: int) -> "Progress":
        return cls(str(sheet), [PENDING] * n, 0, {}, datetime.now().isoformat(timespec="seconds"))

    def counts(self) -> dict:
        return {s: self.status.count(s) for s in STATUSES}

    def next_open(self, after: int = -1) -> int | None:
        """The first row after `after` still to run (pending or redo), wrapping round; None when all are done."""
        n = len(self.status)
        for k in range(1, n + 1):
            i = (after + k) % n
            if self.status[i] in (PENDING, REDO):
                return i
        return None

    def finish(self, i: int, ok: bool, folder: str | None) -> int | None:
        """Row i has been run: done (ok) or to redo. Returns the row to fill in next (None: the sheet is done)."""
        self.status[i] = DONE if ok else REDO
        if folder:
            self.folders.setdefault(str(i), []).append(folder)
        nxt = self.next_open(i) if ok else i
        self.current = nxt if nxt is not None else i
        self.updated = datetime.now().isoformat(timespec="seconds")
        return nxt


def state_path() -> Path:
    return Path(os.environ.get("HPATR_RUN_SHEET_STATE") or Path.home() / ".hpatr" / "run_sheet_state.json")


def save_state(p: Progress, path: Path | None = None) -> None:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(p), indent=1), encoding="utf-8")
    tmp.replace(path)


def load_state(n_rows: int, sheet, path: Path | None = None) -> Progress | None:
    """The saved progress for this sheet, if it is the one last used and still has the same number of rows."""
    path = path or state_path()
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        p = Progress(**d)
    except (OSError, ValueError, TypeError):
        return None
    if Path(p.sheet) != Path(sheet) or len(p.status) != n_rows or any(s not in STATUSES for s in p.status):
        return None
    p.current = min(max(0, int(p.current)), n_rows - 1)
    return p


def differences(row: Row, cond: dict) -> list[str]:
    """What the run actually used (GUI_Clean's Start snapshot) against the sheet: e.g. ['gas 11000 (sheet 12000)']."""
    out = []
    want = row.fields()
    for key, label, cond_key in (("flow", "gas", "flow_entry"), ("speed", "feed", "speed_str"),
                                 ("rpm", "rpm", "rpm_str"), ("orifice", "insert", "orifice"),
                                 ("distance", "travel", "distance_str")):
        if key not in want or (key == "distance" and row.static):
            continue
        got = str(cond.get(cond_key, "") or "").strip()
        a, b = _num(got), _num(want[key])
        same = (a == b) if (a is not None and b is not None) else (got.lower() == str(want[key]).lower())
        if key == "rpm" and not want[key]:
            same = a in (None, 0.0)
        if not same:
            out.append(f"{label} {got or 'blank'} (sheet {want[key] or 'blank'})")
    return out
