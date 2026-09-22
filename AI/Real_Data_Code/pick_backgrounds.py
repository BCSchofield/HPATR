#!/usr/bin/env python3
"""
pick_backgrounds.py -- Step 4 helper: rank training-pool frames by cleanliness.

Step 4 wants 20-30 of the cleanest frames -- checked by eye for faint objects,
per the handoff -- copied into 03_backgrounds/. This script does the ranking
so you're not scrolling through 493 frames by hand: it scores every frame in
the training pool by how much liquid it contains and writes the cleanest N as
browsable data for a review page (build_backgrounds_page.py), where you make
the actual by-eye call.

Score = total area of loose-threshold regions (same detect_threshold as
extract_candidates.py, no half-max/focus refinement -- this only needs to
rank frames relative to each other, not measure individual objects). Lower
score = cleaner frame. A score of 0 does not guarantee nothing is visible --
a very faint or tiny object can sit under the threshold -- which is exactly
why this ranks candidates for a human look rather than picking automatically.

Usage:
    python pick_backgrounds.py --run-name 125917_NNA_3000sccm
    python pick_backgrounds.py --run-name 125917_NNA_3000sccm --top 60
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402

DETECT_THRESHOLD = 0.95   # matches extract_candidates.py's loose net
BLUR_SIGMA = 0.5
MIN_AREA = 4


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def score_frame(img: np.ndarray, bg: np.ndarray) -> dict:
    T = img.astype(np.float32) / np.maximum(bg, 1.0)
    Ts = cv2.GaussianBlur(T, (0, 0), BLUR_SIGMA)
    cand = (Ts < DETECT_THRESHOLD).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(cand, 8)
    areas = [int(stats[i, 4]) for i in range(1, n) if stats[i, 4] >= MIN_AREA]
    return {"total_area_px": sum(areas), "n_regions": len(areas)}


def make_thumb(view_path: Path, size: int = 220) -> str:
    import base64
    view = cv2.imread(str(view_path), cv2.IMREAD_UNCHANGED)
    if view is None:
        return None
    h, w = view.shape[:2]
    s = size / max(w, h)
    resized = cv2.resize(view, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", resized, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    return base64.b64encode(buf).decode("ascii") if ok else None


def main():
    ap = argparse.ArgumentParser(description="Rank training-pool frames by cleanliness for Step 4")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--top", type=int, default=60,
                    help="how many cleanest frames to surface for review (default 60, "
                         "target pick is 20-30 -- extra headroom so a by-eye reject "
                         "still leaves enough to choose from)")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    frame_dir = root / "00_frames" / args.run_name
    cand_dir = root / "01_candidates" / args.run_name
    bg_path = cand_dir / "background_median.tiff"
    if not bg_path.exists():
        sys.exit(f"No cached background at {bg_path}. Run extract_candidates.py first "
                 f"(it builds and caches this).")
    bg = cv2.imread(str(bg_path), cv2.IMREAD_UNCHANGED).astype(np.float32)

    files = list_files(frame_dir / "16bit", "*.tiff")
    if not files:
        sys.exit(f"No frames in {frame_dir}/16bit")

    print(f"scoring {len(files)} frames...")
    scored = []
    for i, p in enumerate(files):
        img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        n = int(p.stem.split("_n")[-1])
        s = score_frame(img, bg)
        scored.append({"frame_number": n, "stem": p.stem, **s})
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(files)}")

    scored.sort(key=lambda r: r["total_area_px"])
    top = scored[:args.top]

    print(f"\ncleanest frame: n{top[0]['frame_number']} ({top[0]['total_area_px']} px, "
          f"{top[0]['n_regions']} regions)")
    print(f"cutoff at top {args.top}: n{top[-1]['frame_number']} "
          f"({top[-1]['total_area_px']} px, {top[-1]['n_regions']} regions)")
    print(f"(for reference, dirtiest frame in the pool: "
          f"{scored[-1]['total_area_px']} px)")

    for r in top:
        thumb = make_thumb(frame_dir / "8bit" / f"{r['stem']}.png")
        r["thumb"] = thumb

    out = {
        "run_name": args.run_name,
        "n_scored": len(scored),
        "n_shown": len(top),
        "detect_threshold": DETECT_THRESHOLD,
        "items": top,
    }
    out_path = cand_dir / "background_candidates.json"
    out_path.write_text(json.dumps(out), encoding="utf-8")
    print(f"\nwritten: {out_path}")


if __name__ == "__main__":
    main()
