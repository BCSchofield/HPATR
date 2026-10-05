"""Entry point.

    python -m src.ai.Taguchi_Analysis_UI                 launch the app
    python -m src.ai.Taguchi_Analysis_UI --self-check    verify the pipeline contract, exit 0/1

The self-check path never imports Qt, so it runs headless -- it is the hook
to run after editing anything in AI/Real_Data_Code/.
"""
import argparse
import sys


def _main() -> None:
    ap = argparse.ArgumentParser(prog="python -m src.ai.Taguchi_Analysis_UI")
    ap.add_argument("--self-check", action="store_true",
                    help="verify pipeline_spec.py against AI/Real_Data_Code and exit 0 (ok) / 1 (broken)")
    ap.add_argument("--json", action="store_true", help="with --self-check: machine-readable output")
    args = ap.parse_args()

    if args.self_check:
        from .pipeline_spec import run_self_check
        sys.exit(run_self_check(as_json=args.json))

    from .app import main
    main()


if __name__ == "__main__":
    _main()
