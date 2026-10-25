"""Run a Flow Visualisation scenario (or its sweep) from its settings file. See README.md.

    python3 run.py settings/first_scenario.yaml                 the run, into output/<name>/<date_time>/
    python3 run.py settings/first_scenario.yaml --layout-only   just the layout picture, to check a moved part
    python3 run.py settings/first_scenario.yaml --per-size 30   fewer droplets per size, for a quick look
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from droplet_transport import runner  # noqa: E402
from droplet_transport.settings import SettingsError  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("settings", type=Path, help="the scenario's settings file (.yaml)")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default output/<name>/<date_time>/)")
    ap.add_argument("--layout-only", action="store_true", help="draw the layout and stop")
    ap.add_argument("--per-size", type=int, default=None, help="droplets per size (overrides the settings)")
    a = ap.parse_args(argv)
    try:
        root = runner.run_file(a.settings, a.out, a.layout_only, a.per_size)
    except SettingsError as e:
        print(f"settings: {e}", file=sys.stderr)
        return 2
    report = root / ("sweep_report.md" if (root / "sweep_report.md").exists() else "report.md")
    print(f"done: {report if report.exists() else root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
