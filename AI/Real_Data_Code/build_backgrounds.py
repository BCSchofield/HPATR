#!/usr/bin/env python3
"""
build_backgrounds.py -- Step 4 second half: materialise reviewed frame picks
into 03_backgrounds/.

Reads 03_backgrounds/picks.txt (one frame ID per line, e.g. n4979 -- from the
background_review artifact, or written by hand), copies the matching 16-bit
and 8-bit frames out of 00_frames/<run>/, and writes backgrounds_metadata.json
recording what was selected and why (cleanliness score, if available).

Usage:
    python build_backgrounds.py --run-name 125917_NNA_3000sccm
    python build_backgrounds.py --run-name 125917_NNA_3000sccm --dry-run
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def read_picks(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser(description="Copy reviewed background frame picks into 03_backgrounds/")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    frame_dir = root / "00_frames" / args.run_name
    bg_dir = root / "03_backgrounds"
    picks_path = bg_dir / "picks.txt"

    picks = read_picks(picks_path)
    if not picks:
        sys.exit(f"No picks in {picks_path}. One frame ID per line, e.g. n4979.")

    # Cross-reference cleanliness scores if pick_backgrounds.py was run for this list.
    scores = {}
    cand_json = root / "01_candidates" / args.run_name / "background_candidates.json"
    if cand_json.exists():
        data = json.loads(cand_json.read_text(encoding="utf-8"))
        for it in data["items"]:
            scores[f"n{it['frame_number']}"] = it

    matched, missing = [], []
    for pid in picks:
        cands = list_files(frame_dir / "16bit", f"*_{pid}.tiff")
        if not cands:
            missing.append(pid)
        else:
            matched.append((pid, cands[0]))

    print(f"picks: {len(picks)}   matched: {len(matched)}   missing: {len(missing)}")
    if missing:
        print(f"NOT FOUND in {frame_dir}/16bit: {missing}")

    if args.dry_run:
        print("--dry-run: nothing copied")
        return

    for sub in ("16bit", "8bit"):
        (bg_dir / sub).mkdir(parents=True, exist_ok=True)

    copied = []
    for pid, tiff_path in matched:
        stem = tiff_path.stem
        shutil.copy2(tiff_path, bg_dir / "16bit" / tiff_path.name)
        png_path = frame_dir / "8bit" / f"{stem}.png"
        if png_path.exists():
            shutil.copy2(png_path, bg_dir / "8bit" / png_path.name)
        copied.append({"frame_id": pid, "stem": stem, **scores.get(pid, {})})

    meta = {
        "run_name": args.run_name,
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "n_backgrounds": len(copied),
        "source": "background_review artifact, by-eye selection from a "
                  "60-candidate cleanliness-ranked shortlist",
        "note": ("Real backgrounds -- carry the static top-edge smudge and "
                 "right-side vignette for free, which is deliberate (see "
                 "handoff Step 4). Single-run limitation: all share the same "
                 "dirt pattern; mitigate with random crops and mild intensity "
                 "jitter at composite time."),
        "frames": copied,
    }
    (bg_dir / "backgrounds_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"\ncopied {len(copied)} backgrounds -> {bg_dir}")
    print(f"metadata: {bg_dir / 'backgrounds_metadata.json'}")


if __name__ == "__main__":
    main()
