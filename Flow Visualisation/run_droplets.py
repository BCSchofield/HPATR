"""Droplets through the CfdOF chamber flow, with OpenFOAM's particle tracker (PLAN.md, Phase 3a). See README.md.

    python3 run_droplets.py settings/droplets_baseline.yaml                   every run, into ~/OpenFOAM/droplet_runs/
                                                                              <date>_<time>_<name>/ (run.runs_folder)
    python3 run_droplets.py settings/droplets_baseline.yaml --per-size 20     fewer droplets of each size, a quick look
    python3 run_droplets.py settings/droplets_baseline.yaml --only gusts_on_after_0s
    python3 run_droplets.py settings/droplets_baseline.yaml --write-only      write the OpenFOAM cases, run nothing
    python3 run_droplets.py --report-only <run folder>                        remake the figures and report.md
    python3 run_droplets.py --views-only <run folder>                         remake the ParaView views (no OpenFOAM)
    python3 run_droplets.py settings/droplets_snapshots.yaml                  a sweep: each entry run, then compared
    python3 run_droplets.py --compare <run folder> <run folder> --labels "a,b"   compare finished runs
    python3 run_droplets.py --resume <run folder> [<run folder> ...]          carry on the runs that stuck, from their
                                                                              newest frames (all folders at once)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from droplet_transport import cfd_compare, cfd_droplets, cfd_runner, cfd_sweep  # noqa: E402
from droplet_transport.cfd_report import run_files  # noqa: E402
from droplet_transport.settings import SettingsError  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("settings", type=Path, nargs="?", help="the droplets settings file (.yaml)")
    ap.add_argument("--out", type=Path, default=None, help="the run's folder (default <runs_folder>/<date>_<time>_<name>/; no spaces)")
    ap.add_argument("--per-size", type=int, default=None, help="droplets of each size (overrides the settings)")
    ap.add_argument("--only", default=None, help="run only these, comma-separated (e.g. gusts_on_after_0s)")
    ap.add_argument("--write-only", action="store_true", help="write the OpenFOAM cases and stop")
    ap.add_argument("--no-paraview", action="store_true", help="skip the ParaView states and pictures")
    ap.add_argument("--no-checks", action="store_true", help="skip the check cases (tracers, column)")
    ap.add_argument("--report-only", type=Path, default=None, metavar="OUTPUT_FOLDER",
                    help="remake the figures and report.md of a finished run (or sweep), nothing else")
    ap.add_argument("--views-only", type=Path, default=None, metavar="RUN_FOLDER",
                    help="remake the ParaView views, pictures and openers of a finished run (or sweep), nothing else")
    ap.add_argument("--compare", type=Path, nargs="+", default=None, metavar="OUTPUT_FOLDER",
                    help="compare finished runs (two or more run folders); into --out, default "
                         "<runs_folder>/<date>_<time>_comparison/")
    ap.add_argument("--labels", default=None, help="with --compare: a name for each, comma-separated")
    ap.add_argument("--show", default=None, help="with --compare: the run the maps show (e.g. gusts_on_after_2s)")
    ap.add_argument("--resume", type=Path, nargs="+", default=None, metavar="RUN_FOLDER",
                    help="carry on each folder's failed runs (a stuck droplet) from their newest frames, guarded; "
                         "--only picks the runs (default every failed one)")
    a = ap.parse_args(argv)
    if a.resume:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(a.resume)) as pool:
            jobs = [(f, pool.submit(cfd_runner.resume_runs, f, a.only, not a.no_paraview)) for f in a.resume]
        status = 0
        for f, job in jobs:
            try:
                print(f"done: {job.result()}")
            except cfd_runner.RunError as e:
                print(f"failed: {f}: {e}", file=sys.stderr)
                status = 1
        return status
    if a.report_only:
        files = run_files(a.report_only)
        if (files / "sweep.json").exists():
            print(f"done: {cfd_sweep.rebuild(files, log=lambda m: None)}")
        else:
            print(f"done: {cfd_runner.rebuild_report(files, log=lambda m: None)}")
        return 0
    if a.views_only:
        files = run_files(a.views_only)
        sweep = files / "sweep.json"
        folders = ([files / r["folder"] for r in json.loads(sweep.read_text())["runs"]] if sweep.exists()
                   else [files])
        for f in folders:
            print(f"done: {cfd_runner.remake_views(f)}")
        return 0
    if a.compare:
        labels = [x.strip() for x in a.labels.split(",")] if a.labels else None
        if labels and len(labels) != len(a.compare):
            ap.error(f"--labels: {len(labels)} names for {len(a.compare)} folders")
        folders = [run_files(f) for f in a.compare]
        runs = cfd_droplets.load(folders[0] / "settings.yaml").runs_folder
        out = a.out or runs / cfd_runner.fresh_stamp(runs, "comparison")
        try:
            print(f"done: {cfd_compare.compare(folders, out, labels, a.show, log=lambda m: None)}")
        except (ValueError, FileNotFoundError) as e:
            print(f"compare: {e}", file=sys.stderr)
            return 2
        return 0
    if a.settings is None:
        ap.error("a settings file is needed (or --report-only)")
    try:
        root = cfd_runner.run_file(a.settings, a.out, a.per_size, a.only, a.write_only, not a.no_paraview,
                                   not a.no_checks)
    except SettingsError as e:
        print(f"settings: {e}", file=sys.stderr)
        return 2
    except cfd_runner.RunError as e:
        print(f"failed: {e}", file=sys.stderr)
        return 1
    md = next((root / f for f in ("comparison.md", "report.md") if (root / f).exists()), root)
    print(f"done: {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
