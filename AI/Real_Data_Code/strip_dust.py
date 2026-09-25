#!/usr/bin/env python3
"""
strip_dust.py -- Step 6 cleanup: remove sensor-dust specks from hand labels.

Dust is static, so it lives in the temporal-median background and divides out
of the transmission image. It is therefore visible in the 8-bit view a human
labels on and invisible in T -- easy to label by mistake, and exactly what
happened here (~19 per frame). See `_dust.py` for the full explanation.

Why these must come out of the ground truth rather than stay in it:

  All 2000 training composites are built on real background frames, which carry
  the same specks, unlabelled. The model is therefore trained that dust is
  background. Ground truth saying otherwise scores the model wrong for doing
  exactly what it was taught -- guaranteed false negatives that punish correct
  behaviour. They do not affect D32 (dust sits at T ~ 0.95, so it is already
  `measurable=false`), only detection scoring.

REVERSIBILITY
-------------
Removed shapes are written to <frame>.dust_removed.json, and the working file
is copied to <frame>.predust.json before any change. Dust is also stripped from
<frame>.original.json, otherwise `refine_labels.py --from-original` would
reintroduce it later.

Usage:
    python strip_dust.py --dry-run          # report only, change nothing
    python strip_dust.py                    # all labelled frames
    python strip_dust.py --frame frame_0062_n619
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402
from _fsutil import list_files  # noqa: E402
from _dust import dust_mask, is_dust, describe  # noqa: E402
from validation_to_coco import shape_to_mask  # noqa: E402


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def find_background(root: Path, run: str = None) -> Path:
    """
    The run's cached temporal median.

    `run` is REQUIRED once more than one run exists. The old behaviour -- take
    the first 01_candidates/* directory that has one -- silently picked by
    alphabetical order, so adding run 101947 would have had it used against
    run 125917's frames, making every transmission value wrong. Refuses to
    guess rather than pick the wrong illumination field.
    """
    if run:
        cand = root / "01_candidates" / run / "background_median.tiff"
        if not cand.exists():
            sys.exit(f"No cached background_median.tiff for run '{run}' at {cand}")
        return cand
    runs = sorted(d.name for d in (root / "01_candidates").iterdir()
                  if (d / "background_median.tiff").exists() and not d.name.endswith("backup"))
    if len(runs) == 1:
        return root / "01_candidates" / runs[0] / "background_median.tiff"
    sys.exit(f"More than one run has a cached background "
             f"({', '.join(runs)}). Pass --run explicitly -- using the wrong "
             f"run's median makes every transmission value wrong.")


def strip_file(path: Path, T, dust, h, w):
    """Returns (kept_shapes, removed_shapes) without writing anything."""
    data = json.loads(path.read_text(encoding="utf-8"))
    kept, removed = [], []
    for sh in data.get("shapes", []):
        m = shape_to_mask(sh, h, w)
        (removed if is_dust(m, T, dust) else kept).append(sh)
    return data, kept, removed


def main():
    ap = argparse.ArgumentParser(description="Remove sensor-dust specks from validation labels")
    ap.add_argument("--frame", help="one frame stem; default is every labelled frame")
    ap.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    ap.add_argument("--val-dir", default="06_validation",
                    help="which validation set, e.g. 06_validation_run2")
    ap.add_argument("--run", default="125917_NNA_3000sccm",
                    help="the run these frames came from -- selects the temporal "
                         "median the dust map is derived from. Dust is a property "
                         "of the CAMERA so the specks are the same, but the median "
                         "must match the run or T is wrong everywhere.")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    val = root / args.val_dir
    lab_dir = val / "labels"

    bg = cv2.imread(str(find_background(root, args.run)), cv2.IMREAD_UNCHANGED).astype(np.float32)
    dust = dust_mask(bg)
    print(f"dust map from the temporal median: {describe(bg)}\n")

    if args.frame:
        stems = [args.frame]
    else:
        stems = sorted(p.stem for p in list_files(lab_dir, "*.json")
                       if not any(s in p.name for s in
                                  (".original.", ".prerefine.", ".dust_removed.", ".predust.")))

    total_removed = 0
    print(f"{'frame':26s} {'shapes':>7} {'dust':>6} {'kept':>6}")
    for stem in stems:
        work = lab_dir / f"{stem}.json"
        if not work.exists():
            print(f"{stem:26s}  (no labels file)")
            continue
        raw = cv2.imread(str(val / "frames" / "16bit" / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
        if raw is None:
            print(f"{stem:26s}  (no 16-bit frame -- skipped)")
            continue
        T = raw.astype(np.float32) / np.maximum(bg, 1.0)
        h, w = T.shape[:2]

        data, kept, removed = strip_file(work, T, dust, h, w)
        print(f"{stem:26s} {len(data.get('shapes', [])):7d} {len(removed):6d} {len(kept):6d}")
        total_removed += len(removed)
        if args.dry_run or not removed:
            continue

        shutil.copy2(work, work.with_suffix(".predust.json"))
        (work.with_suffix(".dust_removed.json")).write_text(
            json.dumps({**data, "shapes": removed}, indent=2), encoding="utf-8")
        data["shapes"] = kept
        work.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Same treatment for the first-touch backup, or --from-original would
        # quietly put the dust back.
        orig = work.with_suffix(".original.json")
        if orig.exists():
            odata, okept, oremoved = strip_file(orig, T, dust, h, w)
            if oremoved:
                odata["shapes"] = okept
                orig.write_text(json.dumps(odata, indent=2), encoding="utf-8")

    print(f"\n{'DRY RUN -- nothing changed. ' if args.dry_run else ''}"
          f"dust shapes {'found' if args.dry_run else 'removed'}: {total_removed}")
    if not args.dry_run and total_removed:
        print("removed shapes kept in <frame>.dust_removed.json; "
              "pre-change copy in <frame>.predust.json")


if __name__ == "__main__":
    main()
