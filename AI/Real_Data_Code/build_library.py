#!/usr/bin/env python3
"""
build_library.py -- Step 3 second half: turn reviewed picks into 02_library/.

You review the contact sheets and write the candidate IDs you want into plain
text files, one ID per line:

    02_library/droplets.txt
    02_library/filaments.txt
    02_library/blobs.txt

This copies each listed candidate's transmission map, mask and view crop into
02_library/<class>/, and writes library.csv with their measurements. Anything
not listed is left in 01_candidates/ -- rejects are kept, never deleted, so a
selection can be revisited or widened later.

The class you file an ID under WINS over the extractor's class_guess. That is
the point of the step: the guess is shape heuristics, your filing is ground
truth. Reclassifications are reported so you can see how often the heuristic
was wrong -- useful signal for whether the guess needs work.

Usage:
    python build_library.py --run-name 125917_NNA_3000sccm
    python build_library.py --run-name 125917_NNA_3000sccm --dry-run
"""

import argparse
import csv
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402

CLASSES = {"droplets": "droplet", "filaments": "filament", "blobs": "blob"}


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


MAX_WEIGHT = 3.0  # cap: reused templates should not dominate composited scenes


def read_picks(path: Path) -> list:
    """
    One candidate ID per line, blank lines and # comments ignored. An optional
    trailing number is a sampling weight for the compositor (Step 5) --
    default 1.0, capped at MAX_WEIGHT. Use this for genuinely higher mask/focus
    quality, NOT for "looks like a nicer circle" -- real fragments are
    crescents and commas (slow relaxation in high-viscosity silicone), so
    weighting toward the roundest examples would bias the library away from
    the shapes that are actually representative.

        n199_o0042
        n1419_o0007   2       # crisp edge, clean segmentation -> sample 2x
    """
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        cid = parts[0]
        weight = 1.0
        if len(parts) > 1:
            try:
                weight = min(float(parts[1]), MAX_WEIGHT)
            except ValueError:
                pass
        out.append((cid, weight))
    return out


def main():
    ap = argparse.ArgumentParser(description="Copy reviewed picks into 02_library/")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen, copy nothing")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    cand_dir = root / "01_candidates" / args.run_name
    lib_dir = root / "02_library"

    with open(cand_dir / "candidates.csv", encoding="utf-8") as f:
        rows = {r["candidate_id"]: r for r in csv.DictReader(f)}

    picked, missing, dupes, reclassified = {}, [], [], []
    seen = set()

    for fname, cls in CLASSES.items():
        for cid, weight in read_picks(lib_dir / f"{fname}.txt"):
            if cid not in rows:
                missing.append((cid, fname))
                continue
            if cid in seen:
                dupes.append(cid)
                continue
            seen.add(cid)
            if rows[cid]["class_guess"] != cls:
                reclassified.append((cid, rows[cid]["class_guess"], cls))
            picked.setdefault(cls, []).append({**rows[cid], "library_weight": weight})

    if not picked:
        sys.exit(f"No picks found. Create {lib_dir}/droplets.txt (etc) with one "
                 f"candidate ID per line -- IDs are printed under each contact "
                 f"sheet cell.")

    print(f"{'class':10s} {'picked':>7}   target")
    targets = {"droplet": 80, "filament": 40, "blob": 30}
    for cls in ("droplet", "filament", "blob"):
        n = len(picked.get(cls, []))
        t = targets[cls]
        mark = "OK" if n >= t else f"{t - n} short"
        print(f"{cls:10s} {n:7d}   {t:3d}  {mark}")

    if reclassified:
        print(f"\nreclassified by you ({len(reclassified)}) -- guess was wrong:")
        for cid, was, now in reclassified[:15]:
            print(f"  {cid:18s} {was:9s} -> {now}")
        if len(reclassified) > 15:
            print(f"  ... and {len(reclassified) - 15} more")
        pct = len(reclassified) / len(seen) * 100
        print(f"  heuristic was wrong on {pct:.0f}% of your picks")
    if missing:
        print(f"\nNOT FOUND in candidates.csv ({len(missing)}) -- typo, or from "
              f"an older extraction run:")
        for cid, fname in missing[:10]:
            print(f"  {cid}  (listed in {fname}.txt)")
    if dupes:
        print(f"\nlisted more than once ({len(dupes)}): {', '.join(dupes[:10])}")

    if args.dry_run:
        print("\n--dry-run: nothing copied")
        return

    out_rows = []
    for cls, items in picked.items():
        for sub in ("transmission", "masks", "view8"):
            (lib_dir / cls / sub).mkdir(parents=True, exist_ok=True)
        for r in items:
            cid = r["candidate_id"]
            for sub, ext in (("transmission", "tiff"), ("masks", "png"), ("view8", "png")):
                src = cand_dir / sub / f"{cid}.{ext}"
                if src.exists():
                    shutil.copy2(src, lib_dir / cls / sub / f"{cid}.{ext}")
            out_rows.append({**r, "library_class": cls})  # library_weight already in r

    fields = list(out_rows[0].keys())
    with open(lib_dir / "library.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    print(f"\ncopied {len(out_rows)} objects -> {lib_dir}")
    print(f"index: {lib_dir / 'library.csv'}")
    print(f"built {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
