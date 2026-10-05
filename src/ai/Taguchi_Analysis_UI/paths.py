"""Repo-relative path resolution for Taguchi_Analysis_UI.

Single place that knows where this app sits inside HPATR, so every other
module asks here instead of re-deriving `parents[N]` arithmetic by hand —
one wrong index in one file is how a path bug hides for months.
"""
from __future__ import annotations

import sys
from pathlib import Path

# .../HPATR/src/ai/Taguchi_Analysis_UI/paths.py -> parents[3] == HPATR
REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
GUI_DIR = SRC_DIR / "gui"
RDC_DIR = REPO_ROOT / "AI" / "Real_Data_Code"  # canonical pipeline scripts


def ensure_src_on_path() -> None:
    """Put HPATR/src on sys.path.

    This is exactly what GUI_Clean.py does for itself (it inserts
    `dirname(dirname(__file__))`, i.e. src/, then does `from config_loader
    import ...` unqualified) — mirroring it here means `import gui.GUI_Clean`
    and `import config_loader` behave identically whether GUI_Clean.py or
    this app imported them first.
    """
    p = str(SRC_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def ensure_rdc_on_path() -> None:
    """Put AI/Real_Data_Code on sys.path.

    It is not a package (no __init__.py) and its own scripts import each
    other unqualified (process_capture.py does `from extract_candidates
    import ...`). Each script also inserts itself + src/ onto sys.path at
    import time, but THIS call has to run first, before our own `import
    process_capture` statement, or that import never resolves at all.
    """
    p = str(RDC_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def repo_commit(pathspec: str | None = None) -> tuple[str, bool]:
    """(short hash, dirty) of the repo HEAD, or ("unknown", False) if git
    isn't available. Used so every report states which pipeline revision
    produced it.

    `pathspec` scopes the dirty check, e.g. "AI/Real_Data_Code". Scoping
    matters: the repo tracks .pyc files that change on every run, so a
    whole-repo dirty flag is permanently True and says nothing. What a
    report needs to know is whether the PIPELINE had uncommitted edits.
    """
    import subprocess

    try:
        sha = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "unknown"
        cmd = ["git", "-C", str(REPO_ROOT), "status", "--porcelain"]
        if pathspec:
            cmd += ["--", pathspec]
        dirty = bool(subprocess.run(
            cmd, capture_output=True, text=True, timeout=5,
        ).stdout.strip())
        return sha, dirty
    except Exception:
        return "unknown", False
