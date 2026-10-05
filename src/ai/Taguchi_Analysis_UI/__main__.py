"""Entry point.

    python -m src.ai.Taguchi_Analysis_UI                 launch the app
    python -m src.ai.Taguchi_Analysis_UI --self-check    verify the pipeline contract, exit 0/1
    python -m src.ai.Taguchi_Analysis_UI --selftest      is THIS machine ready for a batch? (selftest.py)

The self-check path never imports Qt, so it runs headless -- it is the hook
to run after editing anything in AI/Real_Data_Code/.
"""
import argparse
import sys
from pathlib import Path


def _main() -> None:
    ap = argparse.ArgumentParser(prog="python -m src.ai.Taguchi_Analysis_UI")
    ap.add_argument("--self-check", action="store_true",
                    help="verify pipeline_spec.py against AI/Real_Data_Code and exit 0 (ok) / 1 (broken)")
    ap.add_argument("--json", action="store_true", help="with --self-check: machine-readable output")
    ap.add_argument("--selftest", action="store_true",
                    help="check this machine is ready for a batch: packages, GPU, drive, model, runs, and a "
                         "live detached-worker test in a temporary folder")
    ap.add_argument("--day", type=Path, default=None, help="with --selftest: the day folder to check")
    ap.add_argument("--quick", action="store_true", help="with --selftest: skip the live worker test")
    args = ap.parse_args()

    if args.selftest:
        from .selftest import run
        sys.exit(run(day=args.day, quick=args.quick))

    if args.self_check:
        from .pipeline_spec import run_self_check
        sys.exit(run_self_check(as_json=args.json))

    from .app import main
    main()


if __name__ == "__main__":
    _main()
