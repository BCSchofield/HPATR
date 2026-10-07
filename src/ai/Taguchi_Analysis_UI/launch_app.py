"""Click-to-run launcher: open this file in Cursor / VS Code and press Run (the play button).

It does exactly what `python -m src.ai.Taguchi_Analysis_UI` does from the repository root,
which is the proper way to start the app (app.py itself cannot be run directly: the app is a
package and uses package imports). Extra arguments pass through, e.g. `launch_app.py --selftest`.

THE INTERPRETER MATTERS. The play button uses the interpreter shown in Cursor's status bar
(bottom right), and every pipeline stage the batch runs uses that same interpreter. So before
starting, this launcher checks that interpreter can run the pipeline (PySide6, torch, detectron2,
cine_reader, and a torch build that supports this GPU). If it cannot, it restarts itself with the
first known interpreter that can:
    home PC (RTX 5060 Ti):  %USERPROFILE%\\anaconda3\\envs\\Detectron\\python.exe
    lab PC:                 C:\\Users\\55154111\\AppData\\Local\\Programs\\Python\\Python311\\python.exe
or the one named by the TAGUCHI_PYTHON environment variable, which is tried first. If none can,
it carries on with the current one and prints why a batch would fail.
"""
from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
PACKAGE = "src.ai.Taguchi_Analysis_UI"
REEXEC_FLAG = "TAGUCHI_LAUNCHER_REEXEC"     # set on the restarted launcher so it never restarts again

CANDIDATES = (
    Path.home() / "anaconda3" / "envs" / "Detectron" / "python.exe",                     # home PC
    Path(r"C:\Users\55154111\AppData\Local\Programs\Python\Python311\python.exe"),       # lab PC
)

# Run in a fresh interpreter: prints OK, or why that interpreter cannot run a batch.
PROBE = r"""
import sys
missing = []
for m in ("PySide6", "torch", "detectron2", "cine_reader"):
    try:
        __import__(m)
    except Exception:
        missing.append(m)
if missing:
    print("missing " + ", ".join(missing)); sys.exit(1)
import torch
if torch.cuda.is_available():
    major, minor = torch.cuda.get_device_capability(0)
    archs = torch.cuda.get_arch_list()
    if f"sm_{major}{minor}" not in archs and f"compute_{major}{minor}" not in archs:
        print(f"torch {torch.__version__} does not support the {torch.cuda.get_device_name(0)} "
              f"(sm_{major}{minor})"); sys.exit(1)
print("OK")
"""


def prepare() -> None:
    """Make this process look like `python -m <package>` started from the repo root."""
    os.chdir(REPO_ROOT)
    # Running a file puts ITS folder first on sys.path. This folder holds modules called
    # tables.py, stats.py, paths.py, ... which would shadow real libraries (pandas looks for a
    # `tables` package, for one). `-m` does not do that, so neither does this.
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def probe(python: Path | str) -> str:
    """'OK', or why `python` cannot run a batch."""
    try:
        res = subprocess.run([str(python), "-c", PROBE], capture_output=True, text=True, timeout=120,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not start it ({type(exc).__name__})"
    lines = (res.stdout or "").strip().splitlines()
    return lines[-1] if lines else f"probe exited with code {res.returncode}"


def better_interpreter() -> Path | None:
    """The first candidate interpreter that can run a batch, other than this one."""
    here = Path(sys.executable).resolve()
    extra = os.environ.get("TAGUCHI_PYTHON")
    for cand in ((Path(extra),) if extra else ()) + CANDIDATES:
        if cand.is_file() and cand.resolve() != here and probe(cand) == "OK":
            return cand
    return None


def main() -> None:
    if not os.environ.get(REEXEC_FLAG):
        why = probe(sys.executable)
        if why != "OK":
            print(f"Taguchi Analysis: {sys.executable} cannot run a batch: {why}", flush=True)
            better = better_interpreter()
            if better is not None:
                print(f"Restarting with {better}", flush=True)
                env = dict(os.environ, **{REEXEC_FLAG: "1"})
                sys.exit(subprocess.call([str(better), str(Path(__file__).resolve()), *sys.argv[1:]], env=env))
            print("WARNING: no interpreter on this PC can run a batch (the Analyse button still works). "
                  "In Cursor: Ctrl+Shift+P -> 'Python: Select Interpreter' -> the Python with torch and "
                  "detectron2, or set TAGUCHI_PYTHON to its path.", flush=True)
    prepare()
    print(f"Taguchi Analysis: {sys.executable}  (repo {REPO_ROOT})", flush=True)
    sys.argv[0] = f"python -m {PACKAGE}"
    runpy.run_module(PACKAGE, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
