"""Fake run folders that mirror the REAL 2026/10/05 format exactly.

Modelled on /Volumes/LaCie/Experiments/2026/10/05/090432_3000sccm_300rpm_4000sps_or1.2_bh1
(checked 2026-10-05):

    <run>/run_summary.xlsx                          sheets: Metadata, Pressure
    <run>/cone/                                     empty
    <run>/shadowgraph/raw/CINE/recording_<hhmmss>.cine
    <run>/shadowgraph/analysis/                     empty until analysed

Details that are easy to get wrong and are reproduced on purpose:
  * the cine's timestamp is LATER than the folder's (recording_090506 in
    090432_...): it is named at save time, not at run start;
  * the Metadata sheet has exactly 16 rows in a fixed order, values mostly
    STRINGS ("300", "1.2mm"), the flow range uses an en-dash U+2013, GLR and FPS
    are real numbers, and Notes holds a newline;
  * folder order is NOT condition order (111625 is ReRun 5 / Repeat 1, and it
    precedes 112253 which is ReRun 4 / Repeat 3).

`tests/test_fakes_fidelity.py` checks these fakes against a real run when the
LaCie is mounted, so they cannot drift from reality unnoticed.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl

# Verbatim from the real run_summary.xlsx (identical on all 27 runs of 10/05).
METADATA_FIELDS = (
    "Timestamp", "Orifice", "Bubbler Height (mm)", "Bubbler RPM", "Flow Range (sccm)",
    "GLR", "Fluid", "Liquid density (kg/m3)", "Gas", "Gas density (kg/m3)",
    "Pressure Range (barA)", "Speed (steps/s)", "Motor Travel (mm)", "FPS", "Notes",
)
PRESSURE_COLUMNS = ("timestamps", "pressures", "flows_sccm", "cam_start_1", "cam_end_1")
EN_DASH = "–"

# The real 27 runs of 2026/10/05, in folder (chronological) order, with the
# trial/repeat each one's Notes field records. Note 111625 < 112253.
REAL_10_05 = (
    ("090432_3000sccm_300rpm_4000sps_or1.2_bh1", 1, 1),
    ("091303_3000sccm_300rpm_4000sps_or1.2_bh1", 1, 2),
    ("100302_3000sccm_300rpm_4000sps_or1.2_bh1", 1, 3),
    ("101038_6000sccm_300rpm_6000sps_or1.2_bh1", 2, 1),
    ("102005_6000sccm_300rpm_6000sps_or1.2_bh1", 2, 2),
    ("102703_6000sccm_300rpm_6000sps_or1.2_bh1", 2, 3),
    ("103319_9000sccm_300rpm_8000sps_or1.2_bh1", 3, 1),
    ("104015_9000sccm_300rpm_8000sps_or1.2_bh1", 3, 2),
    ("104619_9000sccm_300rpm_8000sps_or1.2_bh1", 3, 3),
    ("105504_3000sccm_600rpm_6000sps_or1.2_bh1", 4, 1),
    ("110329_3000sccm_600rpm_6000sps_or1.2_bh1", 4, 2),
    ("111625_6000sccm_600rpm_8000sps_or1.2_bh1", 5, 1),
    ("112253_3000sccm_600rpm_6000sps_or1.2_bh1", 4, 3),
    ("113007_6000sccm_600rpm_8000sps_or1.2_bh1", 5, 2),
    ("113522_6000sccm_600rpm_8000sps_or1.2_bh1", 5, 3),
    ("114108_9000sccm_600rpm_4000sps_or1.2_bh1", 6, 1),
    ("114809_9000sccm_600rpm_4000sps_or1.2_bh1", 6, 2),
    ("115534_9000sccm_600rpm_4000sps_or1.2_bh1", 6, 3),
    ("120201_3000sccm_900rpm_8000sps_or1.2_bh1", 7, 1),
    ("120758_3000sccm_900rpm_8000sps_or1.2_bh1", 7, 2),
    ("121411_3000sccm_900rpm_8000sps_or1.2_bh1", 7, 3),
    ("122042_6000sccm_900rpm_4000sps_or1.2_bh1", 8, 1),
    ("122757_6000sccm_900rpm_4000sps_or1.2_bh1", 8, 2),
    ("123411_6000sccm_900rpm_4000sps_or1.2_bh1", 8, 3),
    ("124030_9000sccm_900rpm_6000sps_or1.2_bh1", 9, 1),
    ("124632_9000sccm_900rpm_6000sps_or1.2_bh1", 9, 2),
    ("125702_9000sccm_900rpm_6000sps_or1.2_bh1", 9, 3),
)


# What the workbook says when the folder name has a no-token (norpm / nosps /
# noor / nobh). On the real 10/01 run 101035_..._or1.2_nobh the name lost the
# bubbler height but run_summary.xlsx still says 1.
_WORKBOOK_DEFAULTS = {"sccm": "3000", "rpm": "300", "sps": "4000", "orifice": "1.2", "bh": "1"}


def _parse_name(name: str) -> dict:
    """The real grammar, from GUI_Clean._run_id: HHMMSS_<n>sccm_<n>rpm|norpm_
    <n>sps|nosps_or<x>|noor_bh<x>|nobh. A no-token falls back to the workbook default."""
    import re
    m = re.match(r"(\d{6})_([\d.]+|\?|unknown)sccm_(?:([\d.]+)rpm|norpm)_(?:([\d.]+)sps|nosps)"
                 r"_(?:or([\d.]+)|noor)_(?:bh([\d.]+)|nobh)$", name)
    if not m:
        raise ValueError(f"fake run name must match the real format: {name}")
    t, sccm, rpm, sps, orifice, bh = m.groups()
    d = _WORKBOOK_DEFAULTS
    return dict(time=t, sccm=int(float(sccm)) if sccm.replace(".", "").isdigit() else int(d["sccm"]),
                rpm=int(float(rpm or d["rpm"])), sps=int(float(sps or d["sps"])),
                orifice=orifice or d["orifice"], bh=bh or d["bh"])


def _cine_name(time_hhmmss: str, delay_s: int = 34) -> str:
    """recording_<hhmmss>.cine, named ~30 s after the folder (save time)."""
    t = datetime.strptime(time_hhmmss, "%H%M%S") + timedelta(seconds=delay_s)
    return f"recording_{t.strftime('%H%M%S')}.cine"


def metadata_rows(name: str, *, day=("2026", "10", "05"), notes="", fps=390,
                  overrides: dict | None = None, omit: tuple = ()) -> list[tuple]:
    """The 16-row Metadata sheet for a run, in the real order and with the real
    types. `overrides` replaces values; `omit` drops fields (older runs lack GLR,
    Fluid, ... -- see the 10 runs on 10/01)."""
    p = _parse_name(name)
    t = p["time"]
    values = {
        "Timestamp": f"{day[0]}-{day[1]}-{day[2]} {t[0:2]}:{t[2:4]}:{t[4:6]}",
        "Orifice": f"{p['orifice']}mm",
        "Bubbler Height (mm)": p["bh"],
        "Bubbler RPM": str(p["rpm"]),
        "Flow Range (sccm)": f"0{EN_DASH}{round(p['sccm'] * 1.03)} sccm",   # achieved ~ +3%
        "GLR": 0.2819,
        "Fluid": "EcoFlex 00-30",
        "Liquid density (kg/m3)": "1070",
        "Gas": "Nitrogen Gas",
        "Gas density (kg/m3)": "1.145",
        "Pressure Range (barA)": f"1.01{EN_DASH}2.38 barA",
        "Speed (steps/s)": str(p["sps"]),
        "Motor Travel (mm)": "36",
        "FPS": fps,
        "Notes": notes,
    }
    values.update(overrides or {})
    rows = [("Field", "Value")]
    rows += [(k, values[k]) for k in METADATA_FIELDS if k not in omit]
    return rows


def write_run_summary(path: Path, rows: list[tuple]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Metadata"
    for r in rows:
        ws.append(r)
    pr = wb.create_sheet("Pressure")
    pr.append(PRESSURE_COLUMNS)
    for i in range(12):
        pr.append((0.2 * i, 1.014 + 0.01 * i, 0 if i < 4 else 3000, None, None))
    wb.save(path)


def make_run(root: Path, name: str, *, day=("2026", "10", "05"), notes: str = "",
             fps: int = 390, cines: int = 1, xlsx: bool = True, analysis: str | None = None,
             sizer_version: str | None = "2.1.0", thr: float = 0.30,
             overrides: dict | None = None, omit: tuple = (), flat: bool = False) -> Path:
    """Create one run folder under root/YYYY/MM/DD/ (or directly under root if
    `flat`). `analysis` is None (a fresh capture, like all of 10/05), "current"
    (droplets_/liquid_) or "legacy" (measurement_/classical_, like 10/01)."""
    run = (root if flat else root.joinpath(*day)) / name
    p = _parse_name(name)
    (run / "cone").mkdir(parents=True)
    (run / "shadowgraph" / "analysis").mkdir(parents=True)
    cine_dir = run / "shadowgraph" / "raw" / "CINE"
    cine_dir.mkdir(parents=True)
    for i in range(cines):
        cn = _cine_name(p["time"], 34 + 60 * i)
        (cine_dir / cn).touch()
    if xlsx:
        write_run_summary(run / "run_summary.xlsx", metadata_rows(
            name, day=day, notes=notes, fps=fps, overrides=overrides, omit=omit))
    if analysis:
        meas, clas = (("droplets", "liquid") if analysis == "current"
                      else ("measurement", "classical"))
        an = run / "shadowgraph" / "analysis"
        (an / f"{meas}_{thr:.2f}").mkdir()
        (an / f"{clas}_{thr:.2f}").mkdir()
        prov = {"sizer_version": sizer_version} if sizer_version else {}
        (an / f"{meas}_{thr:.2f}" / "summary.json").write_text(json.dumps(
            {"d32_in_focus_um": 90.0, "provenance": prov}))
        (an / f"{clas}_{thr:.2f}" / "classical_summary.json").write_text(json.dumps(
            {"atomised_pct_pooled": 8.0}))
    return run


def make_l9x3(root: Path, day=("2026", "10", "05"), analysis: str | None = None) -> list[Path]:
    """The real 10/05 campaign: 27 runs, 9 conditions x 3 replicates, in the real
    (non-condition) folder order, with the real Notes wording."""
    return [make_run(root, name, day=day, analysis=analysis,
                     notes=f"Taguchi ReRun {trial} - Repeat {rep}\nWITH NOZZLE ADAPTER")
            for name, trial, rep in REAL_10_05]
