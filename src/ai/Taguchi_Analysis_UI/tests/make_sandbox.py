"""Build a sandbox copy of real runs that a real batch can safely be run on.

    python src/ai/Taguchi_Analysis_UI/tests/make_sandbox.py --runs 2

For each of the first N runs of the source day it creates, under the sandbox,

    <sandbox>/2026/10/05/<exact real run name>/
        run_summary.xlsx                    COPIED (57 KB)
        cone/                               empty, as in the real run
        shadowgraph/analysis/               empty, as in the real run
        shadowgraph/raw/CINE/<cine>         SYMLINK to the real 14 GiB cine

so it is indistinguishable from a real day to the app (same names, same tree),
while every byte the pipeline WRITES lands in the sandbox. The real run is only
ever read: process_capture.py:276 skips its "copy cine" step because the symlink
resolves to the real file, and every stage is pointed at the sandbox run folder.

Safety: refuses a sandbox inside .../Experiments/2026, refuses to overwrite
anything that is not a sandbox run it made itself, and --fresh deletes only
sandbox run folders whose cine is a symlink.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

SOURCE_DAY = Path("/Volumes/LaCie/Experiments/2026/10/05")
SANDBOX = Path("/Volumes/LaCie/Experiments/Sandbox/TaguchiUI_Test")
MARKER = ".taguchi_ui_sandbox"


def _is_inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def _is_hardlink_of(a: Path, b: Path) -> bool:
    try:
        return a.exists() and os.path.samefile(a, b) and not a.is_symlink()
    except OSError:
        return False


def link_cine(src: Path, dst: Path) -> str:
    """Point dst at the real cine WITHOUT copying 14 GiB. A symlink first; on
    Windows that needs admin rights or Developer Mode, so fall back to a hard link
    (same NTFS volume only). Either way process_capture sees the cine already inside
    the run folder and skips its "copy cine" step. Returns how it was linked."""
    try:
        dst.symlink_to(src)
        return "symlinked to"
    except OSError as sym_err:
        try:
            os.link(src, dst)
            return "hard-linked to"
        except OSError as hard_err:
            raise SystemExit(
                f"could not link {dst.name} to the real cine without copying it.\n"
                f"  symlink: {sym_err}\n  hard link: {hard_err}\n"
                "On Windows: turn on Developer Mode (Settings > System > For developers) to "
                "allow symlinks, or put the sandbox on the same NTFS drive as the data for a "
                "hard link. (exFAT drives support neither.)") from None


def build(source_day: Path = SOURCE_DAY, sandbox: Path = SANDBOX, n_runs: int = 2,
          fresh: bool = False, log=print) -> list[Path]:
    experiments_tree = source_day.parent.parent                 # .../Experiments/2026 (YYYY/MM/DD)
    if _is_inside(sandbox, experiments_tree) or _is_inside(sandbox, source_day):
        raise SystemExit(f"refusing: sandbox {sandbox} is inside the real data tree {experiments_tree}")
    sources = sorted(p for p in source_day.iterdir() if p.is_dir() and not p.name.startswith("."))[:n_runs]
    if not sources:
        raise SystemExit(f"no runs in {source_day}")
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / MARKER).write_text("made by make_sandbox.py; safe to delete\n")
    day = sandbox / source_day.parent.parent.name / source_day.parent.name / source_day.name
    made = []
    for src in sources:
        dst = day / src.name
        cines = sorted(c for c in (src / "shadowgraph" / "raw" / "CINE").glob("*.cine")
                       if not c.name.startswith("._"))
        if len(cines) != 1:
            log(f"skip {src.name}: {len(cines)} cines")
            continue
        if dst.exists():
            link = dst / "shadowgraph" / "raw" / "CINE" / cines[0].name
            if not (link.is_symlink() or _is_hardlink_of(link, cines[0])):
                raise SystemExit(f"refusing: {dst} exists and is not a sandbox run")
            if fresh:
                shutil.rmtree(dst)
                log(f"removed old sandbox run {dst.name}")
            else:
                log(f"exists, kept: {dst.name}")
                made.append(dst)
                continue
        (dst / "cone").mkdir(parents=True)
        (dst / "shadowgraph" / "analysis").mkdir(parents=True)
        (dst / "shadowgraph" / "raw" / "CINE").mkdir(parents=True)
        if (src / "run_summary.xlsx").exists():
            shutil.copy2(src / "run_summary.xlsx", dst / "run_summary.xlsx")
        how = link_cine(cines[0], dst / "shadowgraph" / "raw" / "CINE" / cines[0].name)
        log(f"made {dst}  (cine {how} {cines[0]})")
        made.append(dst)
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--source-day", type=Path, default=SOURCE_DAY)
    ap.add_argument("--sandbox", type=Path, default=SANDBOX)
    ap.add_argument("--fresh", action="store_true", help="rebuild sandbox runs from scratch")
    a = ap.parse_args()
    build(a.source_day, a.sandbox, a.runs, a.fresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
