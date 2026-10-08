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


def test_the_probe_says_ok_or_why_not(tmp_path):
    assert launch_app.probe(sys.executable).startswith(("OK", "missing ", "torch "))
    assert launch_app.probe(tmp_path / "no_such_python.exe").startswith("could not start it")


LAB_TORCH_ARCHS = ['sm_50', 'sm_60', 'sm_61', 'sm_70', 'sm_75', 'sm_80', 'sm_86', 'sm_90']  # 2.6.0+cu124


def test_gpu_support_follows_cuda_compatibility_not_exact_match():
    s = launch_app.gpu_supported
    assert s(8, 9, LAB_TORCH_ARCHS)              # lab RTX 4070 Ti SUPER: runs the sm_86 code
    assert s(8, 6, LAB_TORCH_ARCHS) and s(9, 0, LAB_TORCH_ARCHS)
    assert not s(12, 0, LAB_TORCH_ARCHS)         # Blackwell (home 5060 Ti) on that build: no
    assert s(12, 0, LAB_TORCH_ARCHS + ['sm_120'])
    assert not s(8, 5, ['sm_86'])                # cubins never run on a LOWER minor
    assert s(8, 9, ['compute_80'])               # PTX JIT-compiles upward
    assert not s(8, 0, ['compute_86'])
    assert not s(9, 0, ['sm_90a'])               # arch-specific builds are not portable


def test_the_probe_carries_the_same_rule():
    assert launch_app._SUPPORTS_SRC in launch_app.PROBE and "gpu_supported(" in launch_app.PROBE


def test_a_bad_interpreter_restarts_with_the_first_candidate_that_works(tmp_path, monkeypatch):
    bad, good = tmp_path / "bad.exe", tmp_path / "good.exe"
    for p in (bad, good):
        p.write_text("")
    monkeypatch.delenv("TAGUCHI_PYTHON", raising=False)
    monkeypatch.setattr(launch_app, "CANDIDATES", (tmp_path / "absent.exe", bad, good))
    monkeypatch.setattr(launch_app, "probe", lambda p: "OK" if Path(p) == good else "missing detectron2")
    assert launch_app.better_interpreter() == good
    monkeypatch.setenv("TAGUCHI_PYTHON", str(bad))
    monkeypatch.setattr(launch_app, "probe", lambda p: "OK")
    assert launch_app.better_interpreter() == bad            # TAGUCHI_PYTHON is tried first


def test_no_working_candidate_means_no_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("TAGUCHI_PYTHON", raising=False)
    monkeypatch.setattr(launch_app, "CANDIDATES", (tmp_path / "absent.exe",))
    assert launch_app.better_interpreter() is None
