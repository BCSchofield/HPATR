"""run_ai_where.py (2026-10-14): the AI chain on the runs whose Notes start with given text (the falling-bead
captures), not on the whole day folder. Only the selection and the dry run are tested here: the chain itself
needs torch + detectron2 (the home PC) and is process_capture, tested elsewhere."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import openpyxl

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

rw = spec.rdc_module("run_ai_where")


def _run(day: Path, name: str, notes: str, cine: bool = True) -> Path:
    run = day / name
    (run / "shadowgraph" / "raw" / "CINE").mkdir(parents=True)
    if cine:
        (run / "shadowgraph" / "raw" / "CINE" / "recording_1.cine").write_bytes(b"\0")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Metadata"
    ws.append(["Field", "Value"])
    ws.append(["Notes", notes])
    wb.save(run / "run_summary.xlsx")
    return run


def _day(tmp_path: Path) -> Path:
    day = tmp_path / "Imaging Work" / "2026" / "10" / "15"
    _run(day, "100000_0sccm_norpm_1000sps_or1.2_bh0.5", "BEAD mix z-4.00")
    _run(day, "101000_0sccm_norpm_0sps_or1.2_bh0.5", "BEAD fall 37.36")
    _run(day, "101500_0sccm_norpm_0sps_or1.2_bh0.5", "  bead FALL 56.28")       # case and spaces ignored
    _run(day, "102000_0sccm_norpm_0sps_or1.2_bh0.5", "BEAD fall 76.39", cine=False)
    _run(day, "103000_0sccm_norpm_1000sps_or1.2_bh0.5", "BEAD 56.28 bg")
    return day


def test_only_the_runs_whose_notes_match_are_selected(tmp_path):
    day = _day(tmp_path)
    sel = rw.select_runs([day], "BEAD fall")
    assert [r.name[:6] for r, _c, _n in sel] == ["101000", "101500", "102000"]
    assert [c is not None for _r, c, _n in sel] == [True, True, False]           # no .cine: listed, skipped
    assert rw.select_runs([day / "100000_0sccm_norpm_1000sps_or1.2_bh0.5"], "BEAD mix")[0][2] == "BEAD mix z-4.00"


def test_the_dry_run_lists_without_running_or_writing(tmp_path):
    day = _day(tmp_path)
    before = sorted(p for p in day.rglob("*"))
    p = subprocess.run([sys.executable, str(Path(rw.__file__)), str(day), "--notes", "BEAD fall", "--dry-run"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "3 run(s) with Notes starting 'BEAD fall'" in p.stdout and "NO .cine: skipped" in p.stdout
    assert sorted(p for p in day.rglob("*")) == before


def test_loose_pcc_cines_named_by_notes_get_their_own_run_folders(tmp_path):
    """Falling beads recorded in PCC (2026-10-14): 'BEAD fall 56.28 p1.cine' in a folder becomes the run
    folder 'BEAD fall 56.28 p1/' with Notes = the file name; the .cine itself is never touched."""
    falling = tmp_path / "falling"
    falling.mkdir()
    for name in ("BEAD fall 56.28 p1.cine", "BEAD_fall_56.28_p2.cine", "Cine3.cine"):
        (falling / name).write_bytes(b"cine")
    loose = rw.loose_cines([falling], "BEAD fall")
    assert [c.name for c, _r in loose] == ["BEAD fall 56.28 p1.cine", "BEAD_fall_56.28_p2.cine"]
    p = subprocess.run([sys.executable, str(Path(rw.__file__)), str(falling), "--notes", "BEAD fall", "--dry-run"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "2 loose .cine file(s)" in p.stdout and "2 run(s) with Notes starting 'BEAD fall'" in p.stdout
    assert sorted(x.name for x in falling.iterdir()) == ["BEAD fall 56.28 p1.cine", "BEAD_fall_56.28_p2.cine",
                                                          "Cine3.cine"]                 # a dry run makes nothing
    for cine, run in loose:
        rw.make_run_folder(cine, run)
    sel = rw.select_runs([falling], "BEAD fall")
    assert [(r.name, c.name, n) for r, c, n in sel] == [
        ("BEAD fall 56.28 p1", "BEAD fall 56.28 p1.cine", "BEAD fall 56.28 p1"),
        ("BEAD_fall_56.28_p2", "BEAD_fall_56.28_p2.cine", "BEAD fall 56.28 p2")]
    assert all((falling / n).read_bytes() == b"cine" for n in ("BEAD fall 56.28 p1.cine", "Cine3.cine"))
    bc = spec.rdc_module("bead_calibration")
    caps = bc.find_captures([falling])
    assert [(c.kind, c.slide) for c in caps] == [("fall", "56.28"), ("fall", "56.28")]
