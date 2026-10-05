"""launch_app.py: the click-to-run launcher behaves exactly like `python -m src.ai.Taguchi_Analysis_UI`."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.ai.Taguchi_Analysis_UI import launch_app, paths

LAUNCHER = Path(launch_app.__file__)


def test_it_finds_the_repository_root():
    assert launch_app.REPO_ROOT == paths.REPO_ROOT


def test_run_as_a_file_from_anywhere_it_reaches_the_app(tmp_path):
    """Run it the way Cursor's play button does (a file path, from another folder), with the
    headless self-check so no window opens."""
    r = subprocess.run([sys.executable, "-B", str(LAUNCHER), "--self-check"], cwd=tmp_path,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PREFLIGHT PASSED" in r.stdout and f"repo {paths.REPO_ROOT}" in r.stdout


def test_the_package_folder_is_not_left_on_the_import_path(tmp_path):
    """Otherwise its tables.py / stats.py would shadow real libraries."""
    code = ("import runpy, sys; sys.argv=['x']; g = runpy.run_path(r'%s', run_name='launch'); "
            "g['prepare'](); import os; "
            "print(any(os.path.abspath(p or '.') == r'%s' for p in sys.path)); print(os.getcwd())"
            % (LAUNCHER, LAUNCHER.parent))
    r = subprocess.run([sys.executable, "-B", "-c", code], cwd=LAUNCHER.parent, capture_output=True, text=True)
    out = r.stdout.split()
    assert out[0] == "False" and Path(out[1]) == paths.REPO_ROOT


def test_a_missing_torch_is_warned_about_with_the_fix(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_torch(name, *a, **k):
        if name == "torch":
            raise ImportError("no torch")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_torch)
    note = launch_app.interpreter_note()
    assert "no torch" in note and "Select Interpreter" in note and "Python311" in note
