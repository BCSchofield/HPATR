"""selftest.py -- is THIS machine ready for an overnight batch? One command, plain answers.

    python -m src.ai.Taguchi_Analysis_UI --selftest [--day <day folder>] [--quick]

Checks, in order, each printed as PASS / WARN / FAIL with what to do about it:

  1. the interpreter (the one that runs this command is the one the batch will use:
     every pipeline stage is started with sys.executable)
  2. every package the app and the pipeline import, with versions; for anything missing,
     the exact pip command -- numpy PINNED to the installed version, so installing the app's
     packages can never upgrade numpy underneath torch, detectron2 and OpenCV
  3. CUDA really working (a tensor op on the GPU, not just is_available())
  4. the LaCie drive, the model folder, the pipeline contract (preflight)
  5. the day's runs: how many, how many still to do, disk space, the design
  6. LIVE, in a temporary folder, with the stub pipeline (no real run is touched): start a
     detached worker exactly as the app does, make it start a pipeline child, kill the worker
     hard, check the child died with it (no orphans), resume, and finish -- all while a
     second thread reads the job files as fast as the UI ever would (on Windows that is the
     file-lock collision that used to fail runs)
  7. sleep prevention

Output is plain ASCII on purpose (a Windows console's code page cannot print everything).
Exit code 0 when nothing FAILed.
"""
from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import paths

# The lab PC's system Python, which holds its CUDA torch. Its presence is how the self-test knows it is on the lab PC.
LAB_PYTHON = Path(r"C:\Users\55154111\AppData\Local\Programs\Python\Python311\python.exe")

# (import name, pip name, version attribute, needed by, required?)
PACKAGES = (
    ("PySide6", "PySide6", "__version__", "the app window", True),
    ("numpy", "numpy", "__version__", "everything", True),
    ("pandas", "pandas", "__version__", "the workbook", True),
    ("openpyxl", "openpyxl", "__version__", "run_summary.xlsx and the workbook", True),
    ("scipy", "scipy", "__version__", "p-values and confidence intervals", True),
    ("matplotlib", "matplotlib", "__version__", "figures (and the pipeline's images)", True),
    ("cv2", "opencv-python", "__version__", "the pipeline (every stage)", True),
    ("cine_reader", "cine-handler", None, "the pipeline (frame extraction)", True),
    ("pycocotools", "pycocotools", "__version__", "the pipeline (masks)", True),
    ("torch", None, "__version__", "the pipeline (inference)", True),
    ("detectron2", None, "__version__", "the pipeline (inference)", True),
    ("psutil", "psutil", "__version__", "more robust process checks (optional)", False),
    ("yaml", "pyyaml", "__version__", "config/paths.yaml (optional)", False),
    ("serial", "pyserial", "__version__", "the capture GUI's GLR formula, only if a run has no GLR (optional)", False),
    ("pyqtgraph", "pyqtgraph", "__version__", "the capture GUI's GLR formula, only if a run has no GLR (optional)", False),
    ("pytest", "pytest", "__version__", "running the test suite (optional)", False),
)
NO_PIP = {"torch": "install the CUDA build of PyTorch (see docs/archive/HANDOFF_real_data_pipeline_LEGACY.md); "
                   "never plain `pip install torch`, which is CPU-only on Windows",
          "detectron2": "build detectron2 0.6 against the installed torch (see the handoff)"}
GB_PER_RUN = 3.1            # output_tree.BASE_GB_PER_RUN, written into each run folder


class Report:
    def __init__(self, out=print):
        self.out = out
        self.fails: list[str] = []
        self.warns: list[str] = []

    def head(self, text: str) -> None:
        self.out("")
        self.out(f"== {text} " + "=" * max(3, 70 - len(text)))

    def ok(self, text: str) -> None:
        self.out(f"  PASS  {text}")

    def info(self, text: str) -> None:
        self.out(f"        {text}")

    def warn(self, text: str, fix: str = "") -> None:
        self.warns.append(text)
        self.out(f"  WARN  {text}")
        if fix:
            self.out(f"        -> {fix}")

    def fail(self, text: str, fix: str = "") -> None:
        self.fails.append(text)
        self.out(f"  FAIL  {text}")
        if fix:
            self.out(f"        -> {fix}")


# ---- 1-2: interpreter and packages ------------------------------------------------------------------------

def check_python(r: Report) -> None:
    r.head("1. Python (the batch runs every stage with THIS interpreter)")
    r.ok(f"{sys.executable}  (Python {platform.python_version()}, {platform.architecture()[0]})")
    if sys.version_info < (3, 9):
        r.fail("Python 3.9 or newer is needed", "use the system Python 3.11")
    if platform.system() == "Windows" and "conda" in sys.executable.lower() and LAB_PYTHON.exists():
        # Only on the lab PC, where torch lives in the system Python. On the home PC (RTX 5060 Ti) the
        # Detectron conda env is the one with a Blackwell-capable torch and detectron2.
        r.warn("this is a conda interpreter; on the lab PC torch lives in the SYSTEM Python 3.11",
               f"use {LAB_PYTHON}")


def check_packages(r: Report) -> dict:
    r.head("2. Packages")
    found, missing_req, missing_opt = {}, [], []
    for mod, pip, attr, why, required in PACKAGES:
        try:
            m = importlib.import_module(mod)
            v = getattr(m, attr, "") if attr else ""
            found[mod] = str(v)
            r.ok(f"{mod:<12} {str(v) or '(installed)':<18} {why}")
        except Exception as exc:                          # noqa: BLE001 -- an import can fail many ways
            detail = f"{type(exc).__name__}: {exc}".splitlines()[0][:120]
            if required:
                r.fail(f"{mod:<12} missing ({detail}) -- needed for {why}", NO_PIP.get(mod, ""))
                if pip:
                    missing_req.append(pip)
            else:
                r.warn(f"{mod:<12} missing -- {why}")
                if pip:
                    missing_opt.append(pip)
    if missing_req or missing_opt:
        pin = [f"numpy=={found['numpy']}"] if found.get("numpy") else []
        r.info("")
        r.info("Install with (numpy pinned so nothing else changes underneath torch / OpenCV):")
        if missing_req:
            r.info(f'"{sys.executable}" -m pip install ' + " ".join(f'"{p}"' for p in pin + missing_req))
        if missing_opt:
            r.info("Optional:")
            r.info(f'"{sys.executable}" -m pip install ' + " ".join(f'"{p}"' for p in pin + missing_opt))
    return found


# ---- 3: CUDA --------------------------------------------------------------------------------------------------

def check_cuda(r: Report, found: dict) -> str:
    r.head("3. GPU")
    if "torch" not in found:
        r.fail("torch is not importable, so inference cannot run at all")
        return "none"
    import torch
    if not torch.cuda.is_available():
        msg = "CUDA is not available: inference would run on the CPU"
        if platform.system() == "Windows":
            r.fail(msg + " (a 27-run batch would take days, not a night)",
                   "check the torch build: python -c \"import torch; print(torch.__version__, torch.version.cuda)\"")
        else:
            r.warn(msg + " (expected on a Mac)")
        return "cpu"
    try:
        name = torch.cuda.get_device_name(0)
        x = (torch.zeros(1, device="cuda") + 1).item()
        assert x == 1.0
        r.ok(f"CUDA works: {name}, torch {torch.__version__} (CUDA {torch.version.cuda}); a tensor op ran on the GPU")
        return "cuda"
    except Exception as exc:                              # noqa: BLE001
        r.fail(f"CUDA is reported available but a GPU operation failed: {exc}",
               "the torch build does not support this GPU (see the handoff's Blackwell note)")
        return "cpu"


# ---- 4: drive, model, contract ---------------------------------------------------------------------------------

def check_pipeline(r: Report) -> Path | None:
    r.head("4. Drive, model and pipeline contract")
    paths.ensure_src_on_path()
    lacie = None
    try:
        from config_loader import find_lacie_drive
        lacie = find_lacie_drive()
    except Exception as exc:                              # noqa: BLE001
        r.fail(f"could not look for the LaCie drive: {exc}")
    if lacie:
        r.ok(f"LaCie drive: {lacie}")
        if platform.system() == "Windows":
            r.info(f"for the run sheet, paste this line:   set LACIE={str(lacie).rstrip(chr(92))}")
    else:
        r.fail("LaCie drive not found", "plug it in; it is found by its folders, whatever its letter")
    from . import settings_defaults as sd
    m = sd.model()
    if m.ok:
        r.ok(f"model: {m.folder}  ({sd.describe_model(m)})")
        if m.warn:
            r.warn(m.warn)
    else:
        r.fail(f"model: {m.note}")
    from . import pipeline_spec as spec
    rep = spec.preflight_fresh()
    if rep.ok:
        r.ok(f"pipeline contract: preflight passed ({len(rep.passed)} checks, in a fresh interpreter)")
    else:
        r.fail("pipeline contract: preflight FAILED")
        for line in rep.render():
            r.info(line)
    return Path(lacie) if lacie else None


# ---- 5: the runs ------------------------------------------------------------------------------------------------

def check_runs(r: Report, day: Path | None, device: str) -> None:
    r.head("5. The runs")
    if day is None:
        r.fail("no day folder to check (no LaCie drive, and no --day given)")
        return
    if not day.is_dir():
        r.fail(f"{day} does not exist", "pass the day folder with --day")
        return
    from . import design as dz
    from . import eta
    from . import run_discovery as rd
    found = rd.find_runs([day])
    runs = rd.load_runs(found.runs, check_reuse=False)
    runnable = [x for x in runs if x.runnable]
    measured = [x for x in runs if x.analysis.measured]
    todo = [x for x in runnable if not x.analysis.measured]
    r.ok(f"{day}: {len(runs)} runs, {len(runnable)} with one .cine, {len(measured)} already measured, "
         f"{len(todo)} to do")
    for x in runs:
        for i in x.errors:
            r.fail(f"{x.name}: {i.message}")
    no_xlsx = [x.name for x in runs if not x.has_xlsx]
    if no_xlsx:
        r.warn(f"{len(no_xlsx)} run(s) without run_summary.xlsx: {', '.join(no_xlsx[:3])}")
    text, level = dz.headline(dz.detect(runs))
    (r.ok if level in ("ok", "info") else r.warn)(f"design: {text}")
    need = GB_PER_RUN * len(todo) * 1.25
    free = shutil.disk_usage(day).free / 1e9
    if free < need:
        r.fail(f"disk: {free:.0f} GB free on that drive, about {need:.0f} GB needed",
               "free some space before starting")
    else:
        r.ok(f"disk: {free:.0f} GB free, about {GB_PER_RUN * len(todo):.0f} GB will be written")
    if not os.access(day, os.W_OK):
        r.fail(f"{day} is not writable")
    if todo:
        pri = eta.priors_for(platform.system())
        per_run = sum(pri[k][1] for k in (("extract", None), ("background", None), ("inference", None),
                                           ("measurement", "extremes"), ("classical", "extremes")))
        if device != "cuda" and platform.system() == "Windows":
            r.info("(time estimate skipped: no working GPU)")
        else:
            r.info(f"time: very roughly {per_run * len(todo) / 3600:.1f} h for {len(todo)} runs "
                   f"(prior: {eta.prior_source(platform.system())}; the app refines it after each run)")


# ---- 6: the detached worker, live -------------------------------------------------------------------------------

def _wait(pred, timeout: float, step: float = 0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


def check_worker_live(r: Report) -> None:
    r.head("6. Detached worker, live (temporary folder, stub pipeline; no real run touched)")
    from . import jobstate, procs
    from . import pipeline_spec as spec
    from .tests import fakes
    saved = {k: os.environ.get(k) for k in ("TAGUCHI_UI_SANDBOX_ROOT", "TAGUCHI_UI_CALIBRATION")}
    tmp = Path(tempfile.mkdtemp(prefix="taguchi_selftest_"))
    stop_reader = threading.Event()
    reads = {"n": 0, "clashes": 0, "errors": 0}

    def reader(jd: Path) -> None:
        """Read the job files the way the UI does (jobstate.read_json: 3 tries, 50 ms apart), as fast as
        possible. On Windows a read can land while the worker swaps a file in and be briefly refused; those
        clashes are counted, but only a read that still fails after the UI's retries is a problem."""
        while not stop_reader.is_set():
            for name in ("state.json", "heartbeat.json", "worker.lock"):
                for attempt in range(3):
                    try:
                        with open(jd / name, "rb") as f:
                            f.read()
                        reads["n"] += 1
                        break
                    except FileNotFoundError:
                        break
                    except OSError:
                        reads["clashes"] += 1
                        if attempt == 2:
                            reads["errors"] += 1
                        else:
                            time.sleep(0.05)

    worker = child = None
    try:
        os.environ["TAGUCHI_UI_SANDBOX_ROOT"] = str(tmp)
        os.environ["TAGUCHI_UI_CALIBRATION"] = str(tmp / "calib.json")     # never the real ETA memory
        runs = [fakes.make_run(tmp, name) for name, _, _ in fakes.REAL_10_05[:2]]
        jd = jobstate.create_job(tmp / "output", runs, spec.RunSettings(), spec.default_options())
        threading.Thread(target=reader, args=(jd,), daemon=True).start()
        stub = ["--impl", "stub", "--stub-stage-s", "0.05", "--heartbeat-s", "0.3"]

        worker = procs.spawn_detached(jd, stub + ["--stub-child", runs[0].name])
        if getattr(worker, "breakaway", True):
            r.ok(f"worker started detached (pid {worker.pid})")
        else:
            r.warn(f"worker started (pid {worker.pid}) but Windows refused job breakaway: it may stop if "
                   f"the window that started the app is closed", "keep that window open overnight")
        pid_file = jd / "stub_child.pid"
        if not _wait(pid_file.exists, 60):
            r.fail("the worker never started its pipeline child", f"see {jd / 'worker.log'}")
            return
        child = int(pid_file.read_text())
        if _wait(lambda: (jobstate.liveness(jd).state == "running"), 20):
            r.ok("worker is running and its heartbeat is fresh")
        else:
            r.fail(f"worker liveness: {jobstate.liveness(jd).detail}")
        if procs.is_alive(child):
            r.ok(f"it started a pipeline child (pid {child}), as a real stage does")

        procs.kill_tree(worker.pid)
        worker.wait(timeout=20)
        if _wait(lambda: not procs.is_alive(child), 15):
            r.ok("killing the worker also stopped its pipeline child (no orphan left running)")
        else:
            r.fail(f"the pipeline child (pid {child}) outlived the worker",
                   f"stop it by hand: taskkill /PID {child} /F (Windows) or kill {child}")
        live = jobstate.liveness(jd)
        if live.resumable:
            r.ok(f"the killed job is seen as resumable ({live.detail})")
        else:
            r.fail(f"after the kill the job reads as: {live.detail}")

        worker = jobstate.resume(jd, extra_args=stub)
        code = worker.wait(timeout=120)
        st = jobstate.load_state(jd) or {}
        statuses = [x.get("status") for x in st.get("runs", [])]
        if code == 0 and statuses == ["done", "done"]:
            r.ok("resumed and finished both runs")
        else:
            r.fail(f"resume ended with code {code}, runs {statuses}", f"see {jd / 'worker.log'}")
        rows = (jd / "timings.csv").read_text(encoding="utf-8").splitlines() if (jd / "timings.csv").exists() else []
        if len(rows) == 3:
            r.ok("timings.csv written (one row per run)")
        else:
            r.fail(f"timings.csv has {max(0, len(rows) - 1)} rows, expected 2")
        stop_reader.set()
        if reads["errors"] == 0:
            clashes = (f" ({reads['clashes']} momentary lock clash(es), all cleared by the UI's retry)"
                       if reads["clashes"] else "")
            r.ok(f"job files read {reads['n']} times while the worker rewrote them: no failures{clashes}")
        else:
            r.warn(f"{reads['errors']} reads of the job files still failed after the UI's retries "
                   f"({reads['n']} succeeded)")
        failed = [e for e in jobstate.EventTail(jd, from_start=True).poll() if e.get("k") == "error"]
        if failed:
            r.fail(f"the worker logged {len(failed)} error(s): {failed[0].get('detail')}")
    except Exception as exc:                              # noqa: BLE001 -- the self-test must report, not crash
        r.fail(f"live worker test crashed: {type(exc).__name__}: {exc}")
    finally:
        stop_reader.set()
        for p in (worker,):
            if p is not None and p.poll() is None:
                procs.kill_tree(p.pid)
        if child and procs.is_alive(child):
            procs.kill_tree(child)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)


# ---- 7: sleep ------------------------------------------------------------------------------------------------------

def check_sleep(r: Report) -> None:
    r.head("7. Sleep")
    from . import procs
    what = procs.keep_awake()
    if what.startswith("could not") or what.startswith("no sleep"):
        r.warn(what, "set the power plan to never sleep while plugged in")
    else:
        r.ok(f"the worker will use: {what}")
    if platform.system() == "Windows":
        r.info("It cannot stop a Windows Update RESTART: pause updates before leaving it overnight.")


# ---- main -----------------------------------------------------------------------------------------------------------

def run(day: Path | None = None, quick: bool = False, out=print) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    r = Report(out)
    out(f"Taguchi Analysis self-test  ({platform.system()} {platform.release()}, {platform.node()})")
    check_python(r)
    found = check_packages(r)
    device = check_cuda(r, found)
    lacie = check_pipeline(r)
    if day is None and lacie is not None:
        day = lacie / "Experiments" / "2026" / "10" / "05"
    check_runs(r, day, device)
    if quick:
        r.head("6. Detached worker, live")
        r.info("skipped (--quick)")
    else:
        check_worker_live(r)
    check_sleep(r)
    out("")
    if r.fails:
        out(f"NOT READY: {len(r.fails)} problem(s) above marked FAIL" +
            (f" (and {len(r.warns)} warning(s))" if r.warns else "") + ".")
        return 1
    out("READY for the batch" + (f" ({len(r.warns)} warning(s) above, none blocking)." if r.warns else "."))
    return 0
