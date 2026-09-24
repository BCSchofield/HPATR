#!/usr/bin/env python3
"""
clean_backgrounds.py -- remove residual in-focus objects from the background
library, so composited training images contain no unlabelled real objects.

THE PROBLEM
-----------
No frame in this run is genuinely empty. Measured over the 25 selected
backgrounds: an average of 4.7 objects per frame pass the SAME in-focus gates
Step 2 uses to decide an object is real, and zero backgrounds are clean. Every
composite built on such a background therefore contains real, detectable
objects carrying no annotation -- roughly 20% of the real objects in a typical
composite. That trains the model to suppress exactly the detections the
measurement depends on, and it is invisible in a loss curve.

THE FIX
-------
The cached temporal-median background is object-free by construction: it is
literally what each pixel looks like with nothing in front of it. So a
residual object's footprint is replaced by the median, plus noise matched to
this frame's own noise level -- the median of 40 frames is ~6x smoother than a
single frame, so an unmatched patch would read as a suspiciously smooth blob,
which is its own kind of fake structure.

WHAT IS AND IS NOT REMOVED
--------------------------
Only objects that PASS the focus gate are patched. Faint out-of-focus blobs
are deliberately LEFT IN: the pipeline already decided (handoff Step 6,
out-of-focus cutoff) that those should never be detected, so leaving them
present-but-unlabelled is not noise -- it is exactly the negative example the
model needs. Removing them would teach nothing.

Usage:
    python clean_backgrounds.py --run-name 125917_NNA_3000sccm
    python clean_backgrounds.py --run-name 125917_NNA_3000sccm --dry-run
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402

# Must stay identical to extract_candidates.py, or "what counts as an object"
# means one thing in the library and another in the backgrounds.
DETECT_THRESHOLD = 0.95
FOCUS_MAX = 0.70
BLUR_SIGMA = 0.5
MIN_AREA = 4
MAX_PIECES = 1


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def find_in_focus_objects(img, bg_med):
    """Union mask of everything that would pass Step 2's gates."""
    T = img / np.maximum(bg_med, 1.0)
    Ts = cv2.GaussianBlur(T, (0, 0), BLUR_SIGMA)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(
        (Ts < DETECT_THRESHOLD).astype(np.uint8), 8)
    out = np.zeros(img.shape, dtype=bool)
    kept = 0
    for i in range(1, n):
        if stats[i, 4] < MIN_AREA:
            continue
        m = (lab == i)
        t_min = float(T[m].min())
        if t_min > FOCUS_MAX:
            continue                      # out of focus -> deliberately left in
        refined = m & (T < (t_min + 1.0) / 2.0)
        if refined.sum() < MIN_AREA:
            continue
        k, _, ps, _ = cv2.connectedComponentsWithStats(refined.astype(np.uint8), 8)
        if sum(1 for j in range(1, k) if ps[j, 4] >= MIN_AREA) > MAX_PIECES:
            continue                      # fragmented -> out of focus
        # Patch the whole loose-threshold region, not just the half-max core:
        # the soft halo outside the core is part of the object and would
        # otherwise survive as a faint ring.
        out |= m
        kept += 1
    return out, kept


def robust_sigma(resid):
    """MAD-based noise estimate -- unaffected by the objects still in frame."""
    med = np.median(resid)
    mad = np.median(np.abs(resid - med))
    return float(1.4826 * mad)


def clean_frame(img, bg_med, dilate_px, feather_px, rng):
    mask, n_objects = find_in_focus_objects(img, bg_med)
    if not mask.any():
        return img.copy(), 0, 0.0

    if dilate_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1,) * 2)
        mask = cv2.dilate(mask.astype(np.uint8), k).astype(bool)

    sigma = robust_sigma((img - bg_med).ravel())
    patch = bg_med + rng.normal(0.0, sigma, size=img.shape).astype(np.float32)

    # Feather so the patch boundary is not a step edge.
    if feather_px > 0:
        d = cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, 5)
        alpha = np.clip(1.0 - d / float(feather_px), 0.0, 1.0)
        alpha[mask] = 1.0
    else:
        alpha = mask.astype(np.float32)

    out = img * (1.0 - alpha) + patch * alpha
    return out, n_objects, float(mask.mean())


def to_8bit(frame, lo, hi):
    return np.clip((frame - lo) / max(hi - lo, 1e-9) * 255.0, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description="Patch residual in-focus objects out of backgrounds")
    ap.add_argument("--run-name", required=True,
                    help="the run these backgrounds came from. Its temporal median "
                         "and 8-bit window are used for patching, so backgrounds "
                         "from different runs must be cleaned in separate passes.")
    ap.add_argument("--only", nargs="+", default=None, metavar="STEM",
                    help="clean only frames whose stem contains one of these. Needed "
                         "once 03_backgrounds/ mixes runs: cleaning a frame against "
                         "another run's median would patch it with the wrong "
                         "illumination field.")
    ap.add_argument("--dilate", type=int, default=8,
                    help="grow each object's footprint before patching, to catch its "
                         "soft halo (default 8 px)")
    ap.add_argument("--feather", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    bg_dir = root / "03_backgrounds"
    src = bg_dir / "16bit"
    med_path = root / "01_candidates" / args.run_name / "background_median.tiff"
    if not med_path.exists():
        sys.exit(f"No temporal median at {med_path} -- run extract_candidates.py first.")
    bg_med = cv2.imread(str(med_path), cv2.IMREAD_UNCHANGED).astype(np.float32)

    win = json.loads((root / "00_frames" / args.run_name / "extraction_metadata.json")
                     .read_text(encoding="utf-8"))["viewing_window_8bit"]
    lo, hi = float(win["low"]), float(win["high"])

    paths = list_files(src, "*.tiff")
    if args.only:
        paths = [q for q in paths if any(o in q.stem for o in args.only)]
        print(f"--only: {len(paths)} background(s) selected for this pass")
    if not paths:
        sys.exit(f"No backgrounds at {src}")

    rng = np.random.default_rng(args.seed)
    out16 = bg_dir / "16bit_clean"
    out8 = bg_dir / "8bit_clean"
    prev = bg_dir / "_clean_preview"
    if not args.dry_run:
        for d in (out16, out8, prev):
            d.mkdir(parents=True, exist_ok=True)

    report, total_before = [], 0
    for i, p in enumerate(paths):
        img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED).astype(np.float32)
        cleaned, n_obj, frac = clean_frame(img, bg_med, args.dilate, args.feather, rng)
        total_before += n_obj

        # Verify: re-run the same detector on the cleaned frame.
        _, n_after = find_in_focus_objects(cleaned, bg_med)
        report.append({"file": p.name, "objects_before": n_obj,
                       "objects_after": n_after, "area_patched": round(frac, 5)})
        print(f"  {p.name:28s} {n_obj:3d} -> {n_after:3d} objects   "
              f"{frac*100:5.2f}% of frame patched")

        if args.dry_run:
            continue
        cv2.imwrite(str(out16 / p.name), np.clip(cleaned, 0, 65535).astype(np.uint16),
                    [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        cv2.imwrite(str(out8 / f"{p.stem}.png"), to_8bit(cleaned, lo, hi))
        if i < 3:
            before, after = to_8bit(img, lo, hi), to_8bit(cleaned, lo, hi)
            pair = np.hstack([cv2.cvtColor(before, cv2.COLOR_GRAY2BGR),
                              cv2.cvtColor(after, cv2.COLOR_GRAY2BGR)])
            cv2.putText(pair, "BEFORE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 2)
            cv2.putText(pair, "AFTER", (img.shape[1] + 20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                        1.2, (0, 255, 255), 2)
            cv2.imwrite(str(prev / f"{p.stem}_before_after.png"), pair)

    after_total = sum(r["objects_after"] for r in report)
    print(f"\nin-focus objects across all backgrounds: {total_before} -> {after_total}")
    print(f"mean per background: {total_before/len(paths):.1f} -> {after_total/len(paths):.1f}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    meta = {
        "run_name": args.run_name,
        "cleaned_utc": datetime.now(timezone.utc).isoformat(),
        "method": "residual in-focus objects patched with the cached temporal-median "
                  "background plus MAD-matched noise",
        "gates": {"detect_threshold": DETECT_THRESHOLD, "focus_max": FOCUS_MAX,
                  "blur_sigma": BLUR_SIGMA, "min_area": MIN_AREA, "max_pieces": MAX_PIECES},
        "dilate_px": args.dilate, "feather_px": args.feather,
        "objects_before": total_before, "objects_after": after_total,
        "note": "Out-of-focus blobs are deliberately NOT removed -- the pipeline "
                "decided they should never be detected, so leaving them present and "
                "unlabelled is the negative example the model needs.",
        "frames": report,
    }
    (bg_dir / "cleaning_report.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\ncleaned -> {out16}")
    print(f"before/after previews -> {prev}")


if __name__ == "__main__":
    main()
