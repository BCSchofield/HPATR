"""Click-to-run launcher: open this file in Cursor / VS Code and press Run (the play button).

It does exactly what `python -m src.ai.Taguchi_Analysis_UI` does from the repository root,
which is the proper way to start the app (app.py itself cannot be run directly: the app is a
package and uses package imports). Extra arguments pass through, e.g. `launch_app.py --selftest`.

THE INTERPRETER MATTERS. The play button uses the interpreter shown in Cursor's status bar
(bottom right), and every pipeline stage the batch runs uses that same interpreter. On the lab PC
it must be the system Python 3.11 that has torch:
    C:\\Users\\55154111\\AppData\\Local\\Programs\\Python\\Python311\\python.exe
(Ctrl+Shift+P -> "Python: Select Interpreter" -> pick it, or "Enter interpreter path...").
This launcher prints which interpreter it is using and warns if torch is missing from it.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
PACKAGE = "src.ai.Taguchi_Analysis_UI"


def prepare() -> None:
    """Make this process look like `python -m <package>` started from the repo root."""
    os.chdir(REPO_ROOT)
    # Running a file puts ITS folder first on sys.path. This folder holds modules called
    # tables.py, stats.py, paths.py, ... which would shadow real libraries (pandas looks for a
    # `tables` package, for one). `-m` does not do that, so neither does this.
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != HERE]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def interpreter_note() -> str:
    try:
        import torch  # noqa: F401
        return ""
    except Exception:
        return ("WARNING: this interpreter has no torch, so a batch would fail at the inference stage "
                "(the Analyse button still works). In Cursor: Ctrl+Shift+P -> 'Python: Select "
                "Interpreter' -> the Python that has torch (lab PC: "
                r"C:\Users\55154111\AppData\Local\Programs\Python\Python311\python.exe).")


def main() -> None:
    prepare()
    print(f"Taguchi Analysis: {sys.executable}  (repo {REPO_ROOT})", flush=True)
    note = interpreter_note()
    if note:
        print(note, flush=True)
    sys.argv[0] = f"python -m {PACKAGE}"
    runpy.run_module(PACKAGE, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
