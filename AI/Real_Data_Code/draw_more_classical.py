#!/usr/bin/env python3
"""
draw_more_classical.py -- back-fill CLASSICAL drawings of measure_run's busiest and mean-diameter frames
(droplets_<thr>/extreme_frames_more/) into liquid_<thr>/extreme_images/, for runs whose liquid stage ran
before classical_liquid.py drew them itself (2026-10-14).

Why: measure_run's own drawings outline filaments thinly, so at slide size the un-atomised liquid is hard
to see. The classical drawing fills it, like the atomised extremes, and prints the classical (quoted)
atomised %, not the model-only one.

Per run:
  1. skip it unless liquid_<thr>/ is at this LIQUID_VERSION and extreme_frames_more/index.json exists;
     skip it if every listed frame is already drawn (unless --force);
  2. run classical_liquid.py exactly as remeasure_liquid.py does, into a TEMPORARY folder (outside the
     run), so the run's liquid_<thr>/ is never rewritten. FAST when the run's summary records NO window
     drops: only the frames to draw are measured (--frames, --window-p 0), which gives the same per-frame
     numbers, because with no window mask a frame's measurement depends on that frame alone; seconds, not
     minutes. Otherwise (or with --full) every frame, as the window mask needs them all;
  3. GATE: each drawn frame's row (liquid, droplet and un-atomised px, atomised %, D32, counts, volumes) must
     equal the run's own classical_per_frame.csv row; on a full pass the pooled summary (atomised % by area
     and volume, D32, counts, pixel totals, window mask, extreme frames) must equal the run's too. Any
     difference and nothing is copied;
  4. copy only the newly drawn frames' PNGs into liquid_<thr>/extreme_images/.

Nothing else in the run is written; the raw capture and droplets_<thr>/ are only read.
A full pass takes as long as the liquid stage (~2 min alone on the Mac, ~4 min three at a time).

    python draw_more_classical.py /Volumes/LaCie/Experiments/2026/10/12 --workers 3
    python draw_more_classical.py <run folder> [<run folder> ...] --dry-run
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from classical_liquid import LIQUID_VERSION  # noqa: E402
from remeasure_liquid import runs_under  # noqa: E402

# the numbers that must not move: the back-fill only draws
SAME = ("frames", "atomised_pct_pooled", "atomised_vol_pct_pooled", "d32_in_focus_um", "droplets_in_focus",
        "droplets_out_of_focus", "total_liquid_px", "droplet_px", "unatomised_px", "n_components",
        "atomised_extreme_frames", "d32_extreme_frames", "static_pieces_not_counted")


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


ROW_FIELDS = ("total_liquid_px", "droplet_px", "unatomised_px", "atomised_pct", "d32_in_focus_um",
              "droplets_in_focus", "droplets_out_of_focus", "n_components", "droplet_vol_mm3",
              "total_liquid_vol_mm3", "atomised_vol_pct")


def _rows(path: Path) -> dict:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return {r["frame"]: r for r in csv.DictReader(f)}
    except (OSError, KeyError):
        return {}


def row_differences(old: dict, new: dict, frames) -> list[str]:
    out = []
    for f in frames:
        a, b = old.get(f), new.get(f)
        if a is None or b is None:
            out.append(f"{f}: no row in the {'run' if a is None else 're-measure'}")
            continue
        out += [f"{f} {k}: {a.get(k)!r} -> {b.get(k)!r}" for k in ROW_FIELDS if a.get(k) != b.get(k)]
    return out


def differences(old: dict, new: dict) -> list[str]:
    out = [f"{k}: {old.get(k)!r} -> {new.get(k)!r}" for k in SAME if old.get(k) != new.get(k)]
    ow, nw = old.get("window") or {}, new.get("window") or {}
    if ow.get("masked_px") != nw.get("masked_px"):
        out.append(f"window masked_px: {ow.get('masked_px')} -> {nw.get('masked_px')}")
    return out


def one(run: Path, thr: float, dry: bool, force: bool, tmp_root: Path | None, full: bool = False) -> str:
    an = run / "shadowgraph" / "analysis"
    cur = an / f"liquid_{thr:.2f}"
    summary = _load(cur / "classical_summary.json")
    version = (summary.get("provenance") or {}).get("liquid_version") or ("2.2.0" if summary else None)
    if version != LIQUID_VERSION:
        return f"{run.name}: liquid stage {version}, not {LIQUID_VERSION}: skipped (re-measure it first)"
    idx = an / f"droplets_{thr:.2f}" / "extreme_frames_more" / "index.json"
    frames = sorted({f.get("frame") for f in _load(idx).get("frames", []) if f.get("frame")})
    if not frames:
        return f"{run.name}: no extreme_frames_more/index.json: skipped"
    img_dir = cur / "extreme_images"
    todo = [f for f in frames if force or not (img_dir / f"{f}.png").is_file()]
    if not todo:
        return f"{run.name}: all {len(frames)} frame(s) already drawn: skipped"
    win = (summary.get("window") or {}).get("objects")
    fast = not full and win == []                  # recorded, and none: no window mask to rebuild
    if dry:
        return (f"{run.name}: would draw {len(todo)} frame(s) ({'fast' if fast else 'full pass'}): "
                f"{', '.join(todo)}")
    sharp = (summary.get("provenance") or {}).get("sharpness_rule", True)
    t0 = time.time()
    with tempfile.TemporaryDirectory(dir=tmp_root, prefix=f"more_{run.name[:6]}_") as d:
        out = Path(d) / "liquid"
        cmd = [sys.executable, "-W", "ignore", str(HERE / "classical_liquid.py"), "--root", str(run),
               "--out-dir", str(out), "--score-thresh", str(thr), "--images-mode", "extremes",
               "--sharpness-rule" if sharp else "--no-sharpness-rule", "--more-extremes", str(idx)]
        if fast:
            cmd += ["--window-p", "0", "--frames", *todo]
        p = subprocess.run(cmd, capture_output=True, text=True)
        new = _load(out / "classical_summary.json")
        if p.returncode != 0 or not new:
            return f"{run.name}: FAILED (exit {p.returncode})\n{p.stderr[-800:]}"
        diff = row_differences(_rows(cur / "classical_per_frame.csv"), _rows(out / "classical_per_frame.csv"), todo)
        if not fast:
            diff += differences(summary, new)
        if diff:
            return f"{run.name}: FAILED the gate, nothing copied: " + "; ".join(diff)
        missing = [f for f in todo if not (out / "extreme_images" / f"{f}.png").is_file()]
        if missing:
            return f"{run.name}: FAILED, not drawn: {', '.join(missing)}"
        img_dir.mkdir(exist_ok=True)
        for f in todo:
            dst = img_dir / f"{f}.png"
            tmp = img_dir / f".{f}.png.partial"
            shutil.copyfile(out / "extreme_images" / f"{f}.png", tmp)
            tmp.replace(dst)
    return (f"{run.name}: drew {len(todo)} frame(s) in {time.time() - t0:.0f}s "
            f"({'fast' if fast else 'full pass'}); numbers unchanged")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, help="run folders, or folders holding run folders")
    ap.add_argument("--score-thresh", type=float, default=0.30)
    ap.add_argument("--workers", type=int, default=3,
                    help="runs at once (the drive's read speed, not the CPU, is the limit)")
    ap.add_argument("--tmp-root", type=Path, default=None, help="where the temporary liquid folders go")
    ap.add_argument("--force", action="store_true", help="redraw frames that already have a PNG")
    ap.add_argument("--full", action="store_true",
                    help="always measure every frame, even for a run with no window drops (slower)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    runs = runs_under(args.paths)
    print(f"{len(runs)} run(s); liquid stage {LIQUID_VERSION}; {args.workers} at a time", flush=True)
    t0 = time.time()
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(one, r, args.score_thresh, args.dry_run, args.force, args.tmp_root, args.full): r
                for r in runs}
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
