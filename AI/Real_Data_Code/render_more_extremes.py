#!/usr/bin/env python3
"""
render_more_extremes.py -- back-fill droplets_<thr>/extreme_frames_more/ for runs measured before
measure_run.py drew it (2026-10-13). No model: the frames are chosen from the run's own
per_frame.csv and droplet_sizes.csv, and only those few frames are re-measured, from the saved
predictions.json, 16-bit frames and background, with measure_run's own per-frame code.

Per run:
  1. skip it if droplets_<thr>/extreme_frames_more/index.json exists (unless --force);
  2. choose the frames with measure_run.pick_more_extremes, the rule a new measurement uses: most
     in-focus droplets, most droplets in total, largest / smallest mean in-focus diameter among
     frames with at least half the run's median in-focus count (never below 10; mean_floor);
  3. re-measure each chosen frame the way summary.json's provenance says the run was measured
     (score threshold, focus_max, sizer, sharpness rule, split, core estimator);
  4. GATE: each frame's in-focus and out-of-focus counts, D32, atomised % and mean diameter must
     match its per_frame.csv / droplet_sizes.csv numbers. Any mismatch and the run is skipped with
     the reason: a picture that does not match the run's numbers is worse than none;
  5. draw them with render_frame into extreme_frames_more.partial/, write index.json / index.csv,
     and rename the folder, so a folder that exists is complete.

Nothing else is written: not the raw capture, not summary.json or per_frame.csv, not the existing
PNGs. Only the new subfolder.

    python render_more_extremes.py /Volumes/LaCie/Experiments/2026/10/12
    python render_more_extremes.py <run folder> [<run folder> ...] --thr 0.30 --dry-run
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path, PureWindowsPath

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import measure_run as mr  # noqa: E402
import optics  # noqa: E402

# The per_frame.csv rounding: a re-measure must land on the same printed value.
GATE_D32_UM = 0.01
GATE_ATOM_PP = 0.001
GATE_MEAN_UM = 0.01


def runs_under(paths):
    out = []
    for p in paths:
        p = Path(p)
        if (p / "shadowgraph" / "analysis").is_dir():
            out.append(p)
        else:
            out += sorted(q for q in p.iterdir() if not q.name.startswith((".", "_"))
                          and (q / "shadowgraph" / "analysis").is_dir())
    return out


def read_rows(meas):
    """per_frame.csv rows, in frame order, with numbers as numbers."""
    with open(meas / "per_frame.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("droplets_in_focus", "droplets_out_of_focus"):
            r[k] = int(r[k])
        for k in ("d32_in_focus_um", "atomised_pct"):
            r[k] = float(r[k])
    return rows


def read_mean_d(meas):
    """{frame: mean in-focus diameter} from droplet_sizes.csv, as measure_run computes it."""
    per = defaultdict(list)
    with open(meas / "droplet_sizes.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["in_focus"] == "1":
                per[r["frame"]].append(float(r["diameter_um"]))
    return {s: mr.frame_mean_d(v) for s, v in per.items()}


def local(recorded, fallback_dir):
    """A provenance path as recorded when it exists here (same machine), else the file of that
    name in `fallback_dir` (a run measured on the Windows PC records D:\\... paths)."""
    if recorded and Path(recorded).exists():
        return Path(recorded)
    name = PureWindowsPath(recorded).name if recorded and "\\" in recorded else Path(recorded or "").name
    return Path(fallback_dir) / name


def settings(prov, thr):
    """How the run was measured, from summary.json's provenance. A run from before sizer 2.0.0
    records no sizer fields: it used the model's mask area and the single darkest pixel."""
    pre2 = "sizer_version" not in prov
    return {"score": float(prov.get("score_threshold", thr)),
            "focus_max": float(prov.get("focus_max", 0.70)),
            "split_um": float(prov.get("split_um", mr.SPLIT_UM)),
            "core_estimator": prov.get("core_estimator", "min" if pre2 else "robust"),
            "sizer": bool(prov.get("sizer_enabled", not pre2)),
            "sharpness_rule": bool(prov.get("sharpness_rule", False)),
            "version": prov.get("sizer_version") if mr.blur.is_sizer3(prov.get("sizer_version")) else None}


def remeasure(run, meas, prov, stems, thr):
    """{stem: measure_frame result} for the chosen frames, plus the 8-bit view directory."""
    val = run / prov.get("val_dir", "shadowgraph/raw")
    preds_path = local(prov.get("predictions"), meas.parent)
    bg_path = local(prov.get("background"), val)
    sb_rec = prov.get("sixteen_bit_dir")
    sb_dir = Path(sb_rec) if sb_rec and Path(sb_rec).is_dir() else val / "frames" / "16bit"
    bg = cv2.imread(str(bg_path), cv2.IMREAD_UNCHANGED)
    if bg is None:
        raise RuntimeError(f"no background at {bg_path}")
    bg = bg.astype(np.float32)
    roll = None
    if prov.get("background_kind") == "rolling":   # sizer 3.1.0: the run's own rolling background, as it was measured
        import background
        rdir = local(prov.get("background_rolling"), meas.parent)
        if not (rdir / "index.json").exists():
            raise RuntimeError(f"measured with a rolling background, not found at {rdir}: re-measure the run first")
        roll = background.Rolling(rdir)
    manifest = json.loads((val / "instances.json").read_text(encoding="utf-8"))
    id_by_name = {Path(im["file_name"]).stem: im["id"] for im in manifest["images"]}
    want = {id_by_name[s]: s for s in stems}
    s = settings(prov, thr)
    if mr.blur.is_sizer3(s["version"]):
        # the calibration that sized the run, or the pictures would not match its numbers
        mr.UM_PER_PX = float(optics.profile_for(run)["um_per_px"])
        mr.SIZER3 = mr.blur.sizer3(optics.profile_for(run))
        if prov.get("optics_profile_hash") and mr.SIZER3["hash"] != prov["optics_profile_hash"]:
            raise RuntimeError(f"measured with sizer calibration {prov['optics_profile_hash']}, the profile now "
                               f"holds {mr.SIZER3['hash']}: re-measure the run first")
    dets = defaultdict(list)
    v31 = s["version"] == mr.SIZER_VERSION_31
    for d in json.loads(preds_path.read_text(encoding="utf-8")):
        if (d["image_id"] in want or v31) and d["score"] >= s["score"] and not d.get("truncated", False):
            dets[d["image_id"]].append(d)
    if v31:   # a static speck is found across the whole run, as measure_run found it
        mr.mark_static(dets, [im["id"] for im in sorted(manifest["images"], key=lambda im: Path(im["file_name"]).stem)])
    out = {}
    for img_id, stem in want.items():
        T = mr.transmission(sb_dir, stem, roll.for_stem(stem) if roll is not None else bg)
        if T is None:
            raise RuntimeError(f"no 16-bit frame for {stem} under {sb_dir}")
        out[stem] = mr.measure_frame(T, dets[img_id], s["focus_max"], split_um=s["split_um"],
                                     core_estimator=s["core_estimator"], sizer=s["sizer"],
                                     sharpness_rule=s["sharpness_rule"], keep_drawn=True, version=s["version"])
    return out, val / "frames" / "8bit"


def _close(a, b, tol):
    a, b = float(a), float(b)
    if np.isnan(a) or np.isnan(b):
        return np.isnan(a) and np.isnan(b)
    return abs(a - b) <= tol + 1e-9


def gate(row, fr, mean_d):
    """Every way the re-measured frame disagrees with its recorded numbers; [] when it agrees."""
    got = {"in-focus": len(fr["focus_a"]), "out-of-focus": len(fr["oof_a"]),
           "D32": round(fr["d32"], 2), "atomised %": round(fr["atom"], 3),
           "mean d": mr.frame_mean_d([mr.csv_um(a) for a in fr["focus_a"]])}
    was = {"in-focus": row["droplets_in_focus"], "out-of-focus": row["droplets_out_of_focus"],
           "D32": row["d32_in_focus_um"], "atomised %": row["atomised_pct"],
           "mean d": mean_d.get(row["frame"], float("nan"))}
    tol = {"in-focus": 0, "out-of-focus": 0, "D32": GATE_D32_UM, "atomised %": GATE_ATOM_PP,
           "mean d": GATE_MEAN_UM}
    return [f"{row['frame']} {k} {got[k]} vs {was[k]} recorded" for k in got
            if not _close(got[k], was[k], tol[k])]


def describe(frames):
    unit = {"in-focus droplets": "in focus", "droplets": "total", "um mean (in focus)": "um mean"}
    return "; ".join(f"{e['key']} {e['frame']} ({e['value']} {unit.get(e['unit'], e['unit'])})"
                     for e in frames)


def backfill_run(run, thr=0.30, dry=False, force=False):
    """(status, message): status is written | exists | dry | skipped | failed."""
    run = Path(run)
    meas = run / "shadowgraph" / "analysis" / f"droplets_{thr:.2f}"
    if not all((meas / f).is_file() for f in ("per_frame.csv", "droplet_sizes.csv", "summary.json")):
        return "skipped", f"{run.name}: not measured (no {meas.name}/ outputs)"
    if (meas / mr.MORE_EXTREMES_DIR / "index.json").is_file() and not force:
        return "exists", f"{run.name}: {mr.MORE_EXTREMES_DIR}/ already there, skipped"
    rows = read_rows(meas)
    mean_d = read_mean_d(meas)
    floor = mr.mean_floor(rows)
    frames, note = mr.pick_more_extremes(rows, mean_d, floor)
    if dry:
        return "dry", f"{run.name}: would draw {describe(frames)}" + (f"  [{note}]" if note else "")
    prov = json.loads((meas / "summary.json").read_text(encoding="utf-8")).get("provenance", {})
    stems = list(dict.fromkeys(e["frame"] for e in frames))
    try:
        measured, view_dir = remeasure(run, meas, prov, stems, thr)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        return "failed", f"{run.name}: SKIPPED, could not re-measure: {type(exc).__name__}: {exc}"
    by_frame = {r["frame"]: r for r in rows}
    bad = [m for s in stems for m in gate(by_frame[s], measured[s], mean_d)]
    missing = [s for s in stems if not (view_dir / f"{s}.png").is_file()]
    if bad or missing:
        why = "; ".join(bad) if bad else f"no 8-bit frame for {', '.join(missing)} in {view_dir}"
        return "failed", f"{run.name}: SKIPPED, gate failed: {why}"
    for e in frames:
        e["image"] = f"{e['frame']}.png"

    def draw(stem, path):
        fr = measured[stem]
        mr.render_frame(view_dir / f"{stem}.png", fr["drawn"], fr["d32"], fr["atom"],
                        mr.DROPLET_RING_PX, path)

    mr.write_more_extremes(meas, frames, note, draw, floor)
    return "written", (f"{run.name}: gate passed ({len(stems)} frames); {describe(frames)}"
                       + (f"  [{note}]" if note else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, help="run folders, or folders holding run folders")
    ap.add_argument("--thr", type=float, default=0.30, help="score threshold of droplets_<thr>/")
    ap.add_argument("--dry-run", action="store_true", help="choose the frames and say which; write nothing")
    ap.add_argument("--force", action="store_true", help="redo runs that already have the folder")
    args = ap.parse_args()
    runs = runs_under(args.paths)
    print(f"{len(runs)} run(s)", flush=True)
    t0 = time.time()
    tally = defaultdict(int)
    for i, run in enumerate(runs, 1):
        status, msg = backfill_run(run, args.thr, args.dry_run, args.force)
        tally[status] += 1
        print(f"[{i}/{len(runs)}  {time.time() - t0:5.0f}s] {msg}", flush=True)
    print("done: " + ", ".join(f"{n} {k}" for k, n in sorted(tally.items())), flush=True)
    sys.exit(1 if tally["failed"] else 0)


if __name__ == "__main__":
    main()
