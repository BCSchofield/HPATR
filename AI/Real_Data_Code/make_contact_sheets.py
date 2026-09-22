#!/usr/bin/env python3
"""
make_contact_sheets.py -- Step 3 review aid.

Renders grids of candidate crops with their masks outlined, so thousands of
candidates can be triaged by eye quickly instead of opening files one at a
time. Writes into 04_contact_sheets/<run>/.

Sheets are grouped by class guess and sorted LARGEST FIRST within each class.
That is deliberate: the library needs ~80 droplets / ~40 filaments / ~30
blobs, and large objects are both scarcer and more valuable (the handoff asks
to over-sample large droplets and borderline cases). Reviewing biggest-first
means the early sheets carry most of the value, and you can stop when objects
become small and repetitive.

Each cell shows the 8-bit view crop with the mask outlined in red, labelled
with the candidate id and equivalent diameter in um. The id is what you record
when sorting into 02_library/.

Usage:
    python make_contact_sheets.py --run-name 125917_NNA_3000sccm
    python make_contact_sheets.py --run-name 125917_NNA_3000sccm --class blob
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv-python is required:  pip install opencv-python")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from config_loader import find_lacie_drive  # noqa: E402

LABEL_H = 22

# Size bands for --stratify, in um equivalent diameter. Chosen from the
# measured distribution on this run: p25=32, p50=45, p75=64, p90=93, p99=166.
SIZE_BANDS = [(0, 30), (30, 40), (40, 60), (60, 80), (80, 120), (120, 10**9)]


def real_data_root() -> Path:
    drive = find_lacie_drive()
    if drive is None:
        sys.exit("LaCie drive not found. Pass --root explicitly.")
    return Path(drive) / "Experiments" / "Real_Data"


def build_cell(view_path: Path, mask_path: Path, cell: int, row: dict) -> np.ndarray:
    """One labelled cell: view crop, mask outlined, scaled to fit, captioned."""
    canvas = np.full((cell + LABEL_H, cell, 3), 40, dtype=np.uint8)

    view = cv2.imread(str(view_path), cv2.IMREAD_UNCHANGED)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
    if view is None or mask is None:
        return canvas

    if view.ndim == 2:
        view = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)
    cont, _ = cv2.findContours((mask > 0).astype(np.uint8),
                               cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(view, cont, -1, (0, 0, 255), 1)

    # Scale to fit, never up past 4x -- a 6px crop blown to 128px is just mush.
    h, w = view.shape[:2]
    s = min(cell / max(w, 1), cell / max(h, 1), 4.0)
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    resized = cv2.resize(view, (nw, nh), interpolation=cv2.INTER_NEAREST)

    y0, x0 = (cell - nh) // 2, (cell - nw) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = resized

    dia = float(row["equiv_diameter_um"])
    flag = "*" if row["touches_border"] == "True" else ""
    cv2.putText(canvas, f'{row["candidate_id"]}{flag}', (2, cell + 9),
                cv2.FONT_HERSHEY_SIMPLEX, 0.28, (200, 200, 200), 1)
    cv2.putText(canvas, f'{dia:.0f}um', (2, cell + 19),
                cv2.FONT_HERSHEY_SIMPLEX, 0.30, (120, 220, 120), 1)
    return canvas


def main():
    ap = argparse.ArgumentParser(description="Render contact sheets of candidates for review")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--class", dest="cls", default=None,
                    help="only this class_guess (droplet/blob/filament)")
    ap.add_argument("--cols", type=int, default=10)
    ap.add_argument("--rows", type=int, default=6)
    ap.add_argument("--cell", type=int, default=128)
    ap.add_argument("--skip-border", action="store_true",
                    help="omit border-touching objects (marked * otherwise)")
    ap.add_argument("--stratify", action="store_true",
                    help="one sheet set per size band instead of one long "
                         "largest-first run. The library needs objects ACROSS "
                         "the size range, but 41%% of droplets sit under 40um -- "
                         "a plain largest-first review fills the quota from the "
                         "big end and never reaches the rest.")
    ap.add_argument("--max-sheets-per-band", type=int, default=2,
                    help="with --stratify, cap sheets per size band (default 2). "
                         "You only need ~13 picks per band; seeing 625 candidates "
                         "to choose 13 is wasted effort. Largest-first within the "
                         "band, so the cap keeps the best of each size range.")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()

    root = args.root or real_data_root()
    cand_dir = root / "01_candidates" / args.run_name
    out_dir = root / "04_contact_sheets" / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = cand_dir / "candidates.csv"
    if not csv_path.exists():
        sys.exit(f"No candidates.csv at {csv_path}. Run extract_candidates.py first.")
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if args.skip_border:
        rows = [r for r in rows if r["touches_border"] != "True"]

    classes = [args.cls] if args.cls else sorted({r["class_guess"] for r in rows})
    per_sheet = args.cols * args.rows

    def render(sub, cls, tag):
        """Render one group of candidates as numbered sheets."""
        sub.sort(key=lambda r: -float(r["area_px"]))
        n_sheets = (len(sub) + per_sheet - 1) // per_sheet
        for s in range(n_sheets):
            chunk = sub[s * per_sheet:(s + 1) * per_sheet]
            cw, ch = args.cell, args.cell + LABEL_H
            sheet = np.full((ch * args.rows + 30, cw * args.cols, 3), 25, dtype=np.uint8)
            hdr = (f"{args.run_name}  |  {cls}  |  {tag}  |  sheet {s+1}/{n_sheets}"
                   f"  |  largest first  |  * = touches border")
            cv2.putText(sheet, hdr, (6, 20), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 255), 1)
            for i, row in enumerate(chunk):
                cid = row["candidate_id"]
                cell_img = build_cell(cand_dir / "view8" / f"{cid}.png",
                                      cand_dir / "masks" / f"{cid}.png",
                                      args.cell, row)
                r, c = divmod(i, args.cols)
                sheet[30 + r * ch:30 + (r + 1) * ch, c * cw:(c + 1) * cw] = cell_img
            name = f"{cls}_{tag}_sheet_{s+1:03d}.png" if tag != "all" else f"{cls}_sheet_{s+1:03d}.png"
            cv2.imwrite(str(out_dir / name), sheet)
        return n_sheets

    for cls in classes:
        sub = [r for r in rows if r["class_guess"] == cls]
        if not args.stratify:
            n = render(sub, cls, "all")
            print(f"{cls}: {len(sub)} candidates -> {n} sheets")
            continue
        print(f"{cls}: {len(sub)} candidates, stratified by size")
        for lo, hi in SIZE_BANDS:
            band = [r for r in sub
                    if lo <= float(r["equiv_diameter_um"]) < hi]
            if not band:
                continue
            band.sort(key=lambda r: -float(r["area_px"]))
            tag = f"{lo:03d}-{hi}um" if hi < 10**9 else f"{lo:03d}plus_um"
            capped = band[:args.max_sheets_per_band * per_sheet] \
                if args.max_sheets_per_band else band
            n = render(capped, cls, tag)
            note = f"  (capped from {len(band)})" if len(capped) < len(band) else ""
            print(f"   {tag:14s} {len(capped):5d} shown -> {n} sheets{note}")

    print(f"\nsheets -> {out_dir}")


if __name__ == "__main__":
    main()
