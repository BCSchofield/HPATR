#!/usr/bin/env python3
"""
remeasure_liquid.py -- re-run ONLY the liquid stage (classical_liquid.py) on measured runs, from their
existing predictions and frames: no model inference, CPU only, so it runs on the Mac.

Written for liquid stage 2.3.0 (2026-10-13: drops on the window, volume). Per run:

  1. skip it if liquid_<thr>/classical_summary.json already says this LIQUID_VERSION;
  2. MOVE the current liquid_<thr>/ to shadowgraph/analysis/_liquid<old version>/liquid_<thr>/, intact
     (once: a re-started run whose archive exists is not archived again);
  3. run classical_liquid.py exactly as process_capture.run_classical does (--root, --out-dir,
     --score-thresh, --images-mode extremes, the run's own sharpness-rule setting) into
     liquid_<thr>.partial/, and rename that to liquid_<thr>/ only when it finishes and its summary
     checks out, so an interruption never leaves a half-written folder that looks complete.

Restartable: run it again and it carries on. Nothing outside shadowgraph/analysis/ is touched; the raw
capture and droplets_<thr>/ are never written.

    python remeasure_liquid.py /Volumes/LaCie/Experiments/2026/10/12 --workers 3
    python remeasure_liquid.py <run folder> [<run folder> ...] --dry-run
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from classical_liquid import LIQUID_VERSION  # noqa: E402


def runs_under(paths: list[Path]) -> list[Path]:
    out = []
    for p in paths:
        p = Path(p)
        if (p / "shadowgraph" / "analysis").is_dir():
            out.append(p)
        else:
            out += sorted(q for q in p.iterdir() if not q.name.startswith((".", "_"))
                          and (q / "shadowgraph" / "analysis").is_dir())
    return out


def _version(summary: Path) -> "str | None":
    try:
        return json.loads(summary.read_text(encoding="utf-8"))["provenance"].get("liquid_version") or "2.2.0"
    except (OSError, ValueError, KeyError):
        return None


def one(run: Path, thr: float, dry: bool) -> str:
    an = run / "shadowgraph" / "analysis"
    name = f"liquid_{thr:.2f}"
    cur = an / name
    if _version(cur / "classical_summary.json") == LIQUID_VERSION:
        return f"{run.name}: already {LIQUID_VERSION}, skipped"
    old = _version(cur / "classical_summary.json")
    try:
        prov = json.loads((cur / "classical_summary.json").read_text(encoding="utf-8"))["provenance"]
    except (OSError, ValueError, KeyError):
        prov = {}
    sharp = prov.get("sharpness_rule", True)
    # the run's own sizer: 3.0.0 named, 2.2.0 / 2.1.0 by the sharpness switch, exactly as before
    sizer = ["--sizer", "3.0.0"] if prov.get("sizer_version") == "3.0.0" else \
        ["--sharpness-rule" if sharp else "--no-sharpness-rule"]
    archive = an / f"_liquid{old}" / name if old else None
    if dry:
        return (f"{run.name}: would archive {name}/ ({old}) to {archive.relative_to(run)} and re-run"
                if old else f"{run.name}: no {name}/ to archive; would run")
    if old and cur.is_dir() and not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        cur.rename(archive)                                  # same volume: a rename, not a copy
    part = an / f"{name}.partial"
    if part.exists():
        shutil.rmtree(part)
    cmd = [sys.executable, "-W", "ignore", str(HERE / "classical_liquid.py"), "--root", str(run),
           "--out-dir", str(part), "--score-thresh", str(thr), "--images-mode", "extremes", *sizer]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    (part.parent / f"{name}.partial.log").write_text(p.stdout + "\n" + p.stderr, encoding="utf-8") \
        if part.exists() else None
    if p.returncode != 0 or _version(part / "classical_summary.json") != LIQUID_VERSION:
        return f"{run.name}: FAILED (exit {p.returncode}); {name}.partial/ left for inspection\n{p.stderr[-800:]}"
    if cur.exists():                                          # e.g. a run with nothing to archive
        shutil.rmtree(cur)
    part.rename(cur)
    log = an / f"{name}.partial.log"
    if log.exists():
        log.rename(cur / f"remeasure_{LIQUID_VERSION}_log.txt")
    s = json.loads((cur / "classical_summary.json").read_text(encoding="utf-8"))
    was = json.loads((archive / "classical_summary.json").read_text(encoding="utf-8")) if archive and \
        (archive / "classical_summary.json").exists() else {}
    win = s.get("window") or {}
    return (f"{run.name}: {time.time() - t0:.0f}s  atomised {was.get('atomised_pct_pooled', '?')} -> "
            f"{s['atomised_pct_pooled']} %  (by volume {s.get('atomised_vol_pct_pooled')} %)  "
            f"window {len(win.get('objects', []))} drop(s) {win.get('masked_pct_of_frame', 0)}%  "
            f"static pieces {s.get('static_pieces_not_counted', 0)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, help="run folders, or folders holding run folders")
    ap.add_argument("--score-thresh", type=float, default=0.30)
    ap.add_argument("--workers", type=int, default=3,
                    help="runs at once (the drive's read speed, not the CPU, is the limit)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    runs = runs_under(args.paths)
    print(f"{len(runs)} run(s); liquid stage {LIQUID_VERSION}; {args.workers} at a time", flush=True)
    t0 = time.time()
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(one, r, args.score_thresh, args.dry_run): r for r in runs}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                msg = f.result()
            except Exception as exc:                             # noqa: BLE001 -- reported, others carry on
                msg = f"{futs[f].name}: CRASHED {type(exc).__name__}: {exc}"
            failed += "FAILED" in msg or "CRASHED" in msg
            print(f"[{i}/{len(runs)}  {time.time() - t0:5.0f}s] {msg}", flush=True)
    print(f"done in {time.time() - t0:.0f}s; {failed} failed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
