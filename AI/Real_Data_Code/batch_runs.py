#!/usr/bin/env python3
"""
batch_runs.py -- put a list of run folders through the full chain, timed.

Per run, in order:
  1. process_capture()      extract -> background -> inference -> measure_run
                            (D32 + model atomised fraction), cine analysed IN
                            PLACE (it must already sit in <run>/shadowgraph/raw/CINE/)
  2. classical_liquid.py    the classical un-atomised denominator, into
                            <run>/shadowgraph/analysis/classical_<thr>/

Every stage is wall-clocked. Each run gets its full log in
<run>/shadowgraph/analysis/batch_log.txt; the campaign gets one timings CSV and
JSON in --out. One run failing does not stop the others.

Progress lines start with "RUN DONE" / "RUN FAILED" / "BATCH DONE" so a monitor
can watch for them.

Usage:
    python batch_runs.py --out <dir> --images all <run dir> <run dir> ...
"""

import argparse
import csv
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from process_capture import process_capture, _fmt_dur, DEFAULT_SCORE_THRESH  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="campaign folder for timings")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--score-thresh", type=float, default=DEFAULT_SCORE_THRESH)
    ap.add_argument("--images", choices=["extremes", "all", "none"], default="extremes")
    ap.add_argument("--reuse", action="store_true",
                    help="runs that already hold a complete analysis at this stride skip "
                         "extraction/background/inference and are only re-measured "
                         "(process_capture.can_reuse decides); others run in full")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    images = None if args.images == "none" else args.images

    rows = []
    t_batch = time.time()
    for k, run in enumerate(args.runs, 1):
        cines = sorted((run / "shadowgraph" / "raw" / "CINE").glob("*.cine"))
        row = {"run": run.name, "started": datetime.now().isoformat(timespec="seconds")}
        analysis = run / "shadowgraph" / "analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        logf = open(analysis / "batch_log.txt", "a", encoding="utf-8")

        def log(s, _f=logf):
            _f.write(s + "\n")
            _f.flush()

        try:
            if len(cines) != 1:
                raise RuntimeError(f"expected exactly one .cine, found {len(cines)}")
            t0 = time.time()
            summary = process_capture(cines[0], run, stride=args.stride,
                                      score_thresh=args.score_thresh, images=images, log=log,
                                      reuse=args.reuse)
            row["process_capture_s"] = round(time.time() - t0, 1)
            row["reused_analysis"] = summary.get("_reused_analysis", False)
            for name, secs in summary.get("_stage_seconds", {}).items():
                row[f"{name.replace(' ', '_')}_s"] = round(secs, 1)
            row["frames"] = summary.get("_frames")
            row["d32_um"] = summary.get("d32_in_focus_um")
            row["d32_ci95"] = summary.get("d32_ci95")
            row["model_atomised_pct"] = summary.get("atomised_pct")

            # liquid_<thr>: the classical whole-frame liquid segmentation that
            # gives the atomised fraction. It holds no droplet sizes.
            cl_out = analysis / f"liquid_{args.score_thresh:.2f}"
            cmd = [sys.executable, "-W", "ignore", str(HERE / "classical_liquid.py"),
                   "--root", str(run), "--out-dir", str(cl_out),
                   "--score-thresh", str(args.score_thresh)]
            if images:
                # classical now HAS an extremes mode (added with sizer 2.1.0),
                # and it picks the atomised extremes from its own fraction --
                # the one actually quoted -- rather than measure_run's
                # model-only figure. It is also 4.5x faster: 2 frames instead of
                # 497, 41 s instead of 183 s per run.
                cmd += ["--images-mode", images]
            t1 = time.time()
            res = subprocess.run(cmd, capture_output=True, text=True)
            log(res.stdout)
            log(res.stderr)
            row["classical_s"] = round(time.time() - t1, 1)
            if res.returncode != 0:
                raise RuntimeError(f"classical_liquid exited {res.returncode}: {res.stderr[-400:]}")
            cs = json.loads((cl_out / "classical_summary.json").read_text(encoding="utf-8"))
            row["classical_atomised_pct"] = cs.get("atomised_pct_pooled")
            row["total_s"] = round(time.time() - t0, 1)
            row["status"] = "ok"
            print(f"RUN DONE {k}/{len(args.runs)} {run.name} | {row['frames']} frames in "
                  f"{_fmt_dur(row['total_s'])} (inference {_fmt_dur(row.get('inference_s', 0))}, "
                  f"classical {_fmt_dur(row['classical_s'])}) | D32 {row['d32_um']} um "
                  f"{row['d32_ci95']} | atomised model {row['model_atomised_pct']}% "
                  f"classical {row['classical_atomised_pct']}%", flush=True)
        except Exception as e:
            row["status"] = f"FAILED: {e}"
            log(traceback.format_exc())
            print(f"RUN FAILED {k}/{len(args.runs)} {run.name}: {e}", flush=True)
        finally:
            logf.close()
        rows.append(row)

        # rewrite after every run, so a crash late on still leaves the earlier timings
        fields = sorted({f for r in rows for f in r}, key=lambda f: (f not in ("run", "status"), f))
        with open(args.out / "timings.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        (args.out / "timings.json").write_text(json.dumps(rows, indent=2, default=str))

    ok = sum(r["status"] == "ok" for r in rows)
    print(f"BATCH DONE {ok}/{len(rows)} ok in {_fmt_dur(time.time() - t_batch)}", flush=True)


if __name__ == "__main__":
    main()
