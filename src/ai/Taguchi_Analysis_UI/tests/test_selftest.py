"""--selftest: the machine-readiness check the Windows run sheet starts with."""
from __future__ import annotations

import builtins
import importlib
import os
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import selftest


def lines_of(fn, *args, **kw):
    out = []
    r = selftest.Report(out.append)
    res = fn(r, *args, **kw)
    return r, out, res


def test_every_import_the_app_and_pipeline_make_is_checked():
    names = {m for m, *_ in selftest.PACKAGES}
    for need in ("PySide6", "numpy", "pandas", "openpyxl", "scipy", "matplotlib",
                 "cv2", "cine_reader", "pycocotools", "torch", "detectron2"):
        assert need in names


def test_missing_packages_get_an_exact_pip_command_with_numpy_pinned(monkeypatch):
    real = importlib.import_module

    def fake(name, *a, **k):
        if name in ("PySide6", "openpyxl", "torch", "psutil"):
            raise ImportError(f"No module named '{name}'")
        return real(name, *a, **k)
    monkeypatch.setattr(selftest.importlib, "import_module", fake)
    r, out, found = lines_of(selftest.check_packages)
    text = "\n".join(out)
    numpy_v = real("numpy").__version__
    req = next(l for l in out if "-m pip install" in l and "PySide6" in l)
    assert f'"numpy=={numpy_v}"' in req and '"openpyxl"' in req and '"PySide6"' in req
    assert "torch" not in req                               # never a plain pip install torch
    assert "CUDA build of PyTorch" in text
    opt = next(l for l in out if "-m pip install" in l and "psutil" in l)
    assert "PySide6" not in opt
    assert len(r.fails) == 3 and len(r.warns) == 1          # psutil is optional
    assert req.strip().startswith(f'"{os.sys.executable}"')


def test_nothing_missing_means_no_install_line():
    r, out, found = lines_of(selftest.check_packages)
    if not r.fails and not r.warns:
        assert not any("pip install" in l for l in out)


def test_a_conda_interpreter_on_windows_is_flagged(monkeypatch):
    monkeypatch.setattr(selftest.platform, "system", lambda: "Windows")
    monkeypatch.setattr(selftest.sys, "executable", r"C:\Users\x\anaconda3\python.exe")
    r, out, _ = lines_of(selftest.check_python)
    assert r.warns and "SYSTEM Python 3.11" in "\n".join(out)


def test_no_cuda_on_windows_is_a_failure_but_on_a_mac_only_a_warning(monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(selftest.platform, "system", lambda: "Windows")
    r, out, dev = lines_of(selftest.check_cuda, {"torch": "x"})
    assert dev == "cpu" and r.fails and "days, not a night" in r.fails[0]
    monkeypatch.setattr(selftest.platform, "system", lambda: "Darwin")
    r, out, dev = lines_of(selftest.check_cuda, {"torch": "x"})
    assert dev == "cpu" and not r.fails and r.warns


def test_the_runs_check_counts_what_is_left_and_the_disk_needed(tmp_path, monkeypatch):
    from src.ai.Taguchi_Analysis_UI.tests import fakes
    fakes.make_l9x3(tmp_path)
    day = tmp_path / "2026" / "10" / "05"
    r, out, _ = lines_of(selftest.check_runs, day, "cuda")
    text = "\n".join(out)
    assert "27 runs, 27 with one .cine, 0 already measured, 27 to do" in text
    assert "9 conditions" in text and "84 GB will be written" in text and not r.fails
    monkeypatch.setattr(selftest.shutil, "disk_usage", lambda p: type("U", (), {"free": 10e9})())
    r, out, _ = lines_of(selftest.check_runs, day, "cuda")
    assert any("GB needed" in f for f in r.fails)


def test_a_missing_day_folder_fails_with_the_fix(tmp_path):
    r, out, _ = lines_of(selftest.check_runs, tmp_path / "nope", "cuda")
    assert r.fails and "--day" in "\n".join(out)


def test_the_live_worker_check_passes_here_and_leaves_nothing_behind(monkeypatch):
    before = set(Path(os.environ.get("TMPDIR", "/tmp")).glob("taguchi_selftest_*"))
    env_before = {k: os.environ.get(k) for k in ("TAGUCHI_UI_SANDBOX_ROOT", "TAGUCHI_UI_CALIBRATION")}
    r, out, _ = lines_of(selftest.check_worker_live)
    text = "\n".join(out)
    assert not r.fails, text
    for want in ("worker started detached", "stopped its pipeline child", "resumable",
                 "resumed and finished both runs", "timings.csv written", "no failures"):
        assert want in text
    after = set(Path(os.environ.get("TMPDIR", "/tmp")).glob("taguchi_selftest_*"))
    assert after == before                                  # temporary folder removed
    assert {k: os.environ.get(k) for k in env_before} == env_before


def test_the_whole_selftest_says_ready_or_not_and_sets_the_exit_code(monkeypatch, tmp_path):
    from src.ai.Taguchi_Analysis_UI.tests import fakes
    fakes.make_l9x3(tmp_path)
    out = []
    code = selftest.run(day=tmp_path / "2026" / "10" / "05", quick=True, out=out.append)
    text = "\n".join(out)
    assert ("READY for the batch" in text) == (code == 0)
    assert "skipped (--quick)" in text
    assert all(ord(c) < 128 for line in out for c in line if "design:" not in line), \
        "self-test output must stay ASCII (Windows console code pages)"
