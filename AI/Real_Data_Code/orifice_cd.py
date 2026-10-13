#!/usr/bin/env python3
"""
orifice_cd.py -- discharge coefficient (Cd) of each exit orifice insert, from GAS-ONLY runs.

WHY. The analysis app estimates how much of the orifice the silicone takes from how much gas got
through compared with what the orifice could pass with gas alone at the measured pressure
(covariates: gas share, silicone film at the exit; docs/notes/2026-10-13_phase12_physical_variables.md).
"What the orifice could pass" is the ideal flow times Cd. Until Cd is measured it is taken as 1.0,
which overstates the capacity and so understates the gas share. This script measures it.

THE TEST (docs/ORIFICE_CD_TEST.md): per insert, no silicone flowing (GUI_Clean Start Experiment with
Speed 0: gas + logging, no traverse), the gas stepped through a ladder of set points, ~20 s each, the
Notes starting "CD TEST". Each run's run_summary.xlsx Pressure sheet holds time, upstream pressure
(barA, the Alicat) and gas flow (sccm).

THE MATHS. On each steady step (flow within tolerance for >= --min-step-s; the first --settle-s
dropped), with P0 the median pressure and Q the median flow:
    m_dot   = Q x rho_std / 6e7                                  (kg/s; rho_std = the run's gas density)
    G_ideal = P0 sqrt(g / (R T)) (2 / (g+1))^((g+1) / (2 (g-1)))  if Pa / P0 <= (2 / (g+1))^(g / (g-1))  (choked)
            = P0 sqrt(2 g / ((g-1) R T) [r^(2/g) - r^((g+1)/g)])   otherwise, r = Pa / P0             (subsonic)
    Cd      = m_dot / (A G_ideal),  A = pi d^2 / 4
Per insert, Cd is the least-squares slope of m_dot against A G_ideal over the CHOKED steps (the
regime the two-phase runs are in, and the least sensitive to line losses). Gas alone only chokes the
small inserts within the MFC's 12,000 sccm (0.5 mm from ~3,700 sccm; 1.2 mm would need ~21,000), so
an insert with fewer than two choked steps is fitted on its subsonic steps above 1.1 barA instead, and
says so: that Cd leans on a pressure drop of a few tenths of a bar, so use --line-loss-run.

CAVEAT. P0 is read at the Alicat, upstream of the line and the bubbler chamber, so it includes their
pressure drop and Cd comes out LOW. --line-loss-run takes a run with the insert REMOVED (open fitting):
its pressure above ambient against flow is fitted as dP = k Q^2 and subtracted.

    python orifice_cd.py <run folder or day folder> [...] --out <folder> [--write] [--temp-c 20]
"""
import argparse
import csv
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from src.ai.Taguchi_Analysis_UI import operating  # noqa: E402  (the app's own log reader)
from src.ai.Taguchi_Analysis_UI import orifice  # noqa: E402  (the app's own gas-only formula and Cd table)

PA_BAR = orifice.PA_BAR
SUBSONIC_MIN_BAR = 1.10        # below this the pressure drop is too small for a useful Cd
CD_TABLE = orifice.CD_FILE
TAG = "CD TEST"


def gas_props(tag: str) -> tuple[float, float, str]:
    name, g, R, note = orifice.gas_properties(tag)
    return g, R, note or name


def ideal_flux(p0_bar: float, g: float, R: float, T: float) -> tuple[float, bool]:
    """(ideal gas-only mass flux kg/m2/s from P0 to atmosphere, choked?): the SAME function the analysis
    uses for the gas share, so a measured Cd and its use can never disagree."""
    return orifice.gas_only_flux(p0_bar, g, R, T, PA_BAR)


def read_meta(xlsx: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    try:
        if "Metadata" not in wb.sheetnames:
            return {}
        return {str(r[0]).strip(): r[1] for r in wb["Metadata"].iter_rows(min_row=2, values_only=True)
                if r and r[0] is not None}
    finally:
        wb.close()


def _num(v):
    m = re.search(r"[-+]?\d*\.?\d+", str(v)) if v is not None else None
    return float(m.group()) if m else None


def steps(t, p, q, min_s: float, settle_s: float, tol_frac: float = 0.015, tol_abs: float = 30.0) -> list:
    """Steady gas steps: [(t0, t1, median P0, median Q)]. A step grows while each sample stays within
    tolerance of the step's running median; it counts when it lasts >= min_s; its first settle_s
    are dropped before the medians."""
    out, i, n = [], 0, len(t)
    while i < n:
        j = i + 1
        while j < n:
            ref = float(np.median(q[i:j]))
            if abs(q[j] - ref) > max(tol_frac * abs(ref), tol_abs):
                break
            j += 1
        if t[j - 1] - t[i] >= min_s and np.median(q[i:j]) > 50:
            keep = (t[i:j] >= t[i] + settle_s)
            out.append((float(t[i]), float(t[j - 1]), float(np.median(p[i:j][keep])), float(np.median(q[i:j][keep]))))
        i = j
    return out


def runs_under(paths) -> list[Path]:
    out = []
    for p in map(Path, paths):
        if (p / "run_summary.xlsx").is_file():
            out.append(p)
        elif p.is_dir():
            out += sorted(q for q in p.iterdir() if (q / "run_summary.xlsx").is_file())
    return out


def line_loss_k(run: Path, min_s: float, settle_s: float) -> float:
    """k in dP = k Q^2 (bar / sccm^2) from an open-fitting run (insert removed)."""
    tr = operating.read_trace(run / "run_summary.xlsx")
    if tr is None:
        sys.exit(f"{run.name}: no pressure log for the line-loss fit")
    st = steps(tr.t, tr.p, tr.q, min_s, settle_s)
    if not st:
        sys.exit(f"{run.name}: no steady steps for the line-loss fit")
    Q = np.array([s[3] for s in st])
    dP = np.array([s[2] - PA_BAR for s in st])
    return float((dP * Q ** 2).sum() / (Q ** 4).sum())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="run folders, or folders holding run folders")
    ap.add_argument("--out", required=True, type=Path, help="output folder (points CSV, summary, figure)")
    ap.add_argument("--tag", default=TAG, help=f"only runs whose Notes contain this (default '{TAG}')")
    ap.add_argument("--temp-c", type=float, default=20.0, help="gas temperature at the orifice (C)")
    ap.add_argument("--min-step-s", type=float, default=8.0)
    ap.add_argument("--settle-s", type=float, default=3.0)
    ap.add_argument("--line-loss-run", type=Path, help="a run with the insert removed (open fitting)")
    ap.add_argument("--write", action="store_true", help=f"update {CD_TABLE.relative_to(REPO)}")
    args = ap.parse_args()
    T = args.temp_c + 273.15
    k = line_loss_k(args.line_loss_run, args.min_step_s, args.settle_s) if args.line_loss_run else 0.0
    if k:
        print(f"line loss: dP = {k:.3e} bar/sccm^2 x Q^2 ({k * 1e8:.3f} bar at 10,000 sccm), subtracted")

    rows = []
    for run in runs_under(args.paths):
        meta = read_meta(run / "run_summary.xlsx")
        notes = str(meta.get("Notes") or "")
        if args.tag and args.tag.lower() not in notes.lower():
            continue
        d = _num(meta.get("Orifice"))
        length = _num(meta.get("Orifice length (mm)"))
        rho = _num(meta.get("Gas density (kg/m3)"))
        g, R, gas = gas_props(str(meta.get("Gas") or ""))
        if d is None or rho is None:
            print(f"{run.name}: skipped (no orifice or no gas density in run_summary)")
            continue
        if (_num(meta.get("Speed (steps/s)")) or 0) > 0:
            print(f"{run.name}: WARNING speed > 0 -- silicone may have been flowing; Cd needs gas only")
        tr = operating.read_trace(run / "run_summary.xlsx")
        if tr is None or not np.any(tr.q > 0):
            print(f"{run.name}: skipped (no gas flow logged)")
            continue
        A = math.pi * (d * 1e-3) ** 2 / 4
        for t0, t1, p0, q in steps(tr.t, tr.p, tr.q, args.min_step_s, args.settle_s):
            p_noz = p0 - k * q * q
            G, choked = ideal_flux(p_noz, g, R, T)
            mdot = q * rho / 6e7
            rows.append({"run": run.name, "diameter_mm": d, "length_mm": length, "gas": gas,
                         "t_start_s": round(t0, 1), "t_end_s": round(t1, 1), "flow_sccm": round(q, 1),
                         "p0_barA": round(p0, 4), "p_nozzle_barA": round(p_noz, 4), "choked": choked,
                         "mdot_g_s": round(mdot * 1e3, 5), "ideal_g_s": round(A * G * 1e3, 5),
                         "cd": round(mdot / (A * G), 4) if G > 0 else None})
    if not rows:
        sys.exit(f"no steady steps found in runs whose Notes contain '{args.tag}'")
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "orifice_cd_points.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    inserts = {}
    for r in rows:
        inserts.setdefault((r["diameter_mm"], r["length_mm"]), []).append(r)
    summary = []
    for (d, length), pts in sorted(inserts.items(), key=lambda kv: kv[0][0]):
        ch = [p for p in pts if p["choked"] and p["cd"] is not None]
        sub = [p for p in pts if not p["choked"] and p["cd"] is not None and p["p_nozzle_barA"] >= SUBSONIC_MIN_BAR]
        # choked steps when there are two or more; otherwise the subsonic ones. Gas alone only chokes the
        # small inserts within the MFC's 12,000 sccm (0.5 mm from ~3,700; 1.2 mm would need ~21,000), so
        # 1.2 / 1.8 mm are subsonic-only: their Cd leans on a small pressure drop, so the line loss matters
        basis, fit = ("choked", ch) if len(ch) >= 2 else ("subsonic", sub)
        x = np.array([p["ideal_g_s"] for p in fit]); y = np.array([p["mdot_g_s"] for p in fit])
        cd = float((x * y).sum() / (x * x).sum()) if len(fit) else None
        sd = float(np.std([p["cd"] for p in fit], ddof=1)) if len(fit) > 1 else None
        summary.append({"diameter_mm": d, "length_mm": length, "cd": None if cd is None else round(cd, 4),
                        "cd_sd": None if sd is None else round(sd, 4), "n_points": len(fit), "basis": basis,
                        "n_choked": len(ch), "n_subsonic": len(pts) - len(ch), "runs": sorted({p["run"] for p in pts})})
        name = f"  {d:g} mm" + (f", L {length:g} mm" if length else "")
        if cd is None:
            print(f"{name}: no usable steps (none choked, none subsonic above {SUBSONIC_MIN_BAR} barA)")
        else:
            print(f"{name}: Cd {cd:.3f}" + (f" (sd {sd:.3f}" if sd is not None else " (") + f", {len(fit)} {basis} steps)"
                  + ("  <- subsonic only: sensitive to line loss, use --line-loss-run" if basis == "subsonic" else ""))
    (args.out / "orifice_cd_summary.json").write_text(json.dumps(
        {"measured": date.today().isoformat(), "temp_c": args.temp_c, "line_loss_k": k, "inserts": summary},
        indent=2), encoding="utf-8")
    _figure(rows, summary, args.out / "orifice_cd.png")
    print(f"written: {args.out / 'orifice_cd_points.csv'}, orifice_cd_summary.json, orifice_cd.png")
    if args.write:
        _write_table(summary)


def _figure(rows, summary, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, s in enumerate(summary):
        pts = [r for r in rows if r["diameter_mm"] == s["diameter_mm"] and r["length_mm"] == s["length_mm"]]
        c = f"C{i}"
        for choked, mk in ((True, "o"), (False, "^")):
            sel = [p for p in pts if p["choked"] == choked]
            ax.scatter([p["p_nozzle_barA"] for p in sel], [p["mdot_g_s"] for p in sel], marker=mk,
                       edgecolors=c, facecolors=c if choked else "none")
        ax.scatter([], [], color=c, label=f"{s['diameter_mm']:g} mm: Cd {s['cd']}" if s["cd"] else f"{s['diameter_mm']:g} mm")
        if s["cd"]:
            pp = np.array(sorted(p["p_nozzle_barA"] for p in pts))
            ideal = np.array([p["ideal_g_s"] for p in sorted(pts, key=lambda p: p["p_nozzle_barA"])])
            ax.plot(pp, ideal, c=c, ls=":", lw=1)
            ax.plot(pp, s["cd"] * ideal, c=c, lw=1.2)
    ax.set_xlabel("pressure at the nozzle (barA)")
    ax.set_ylabel("gas mass flow (g/s)")
    ax.set_title("Gas only: measured flow (points; triangles subsonic, not fitted), ideal (dotted), Cd x ideal (line)",
                 fontsize=9)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def _write_table(summary):
    try:
        table = json.loads(CD_TABLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        table = {"schema": 1, "note": "Discharge coefficients of the exit orifice inserts, gas only, measured with "
                                      "AI/Real_Data_Code/orifice_cd.py (docs/ORIFICE_CD_TEST.md).", "inserts": []}
    today = date.today().isoformat()
    for s in summary:
        if s["cd"] is None:
            continue
        hit = next((e for e in table["inserts"] if abs(e["diameter_mm"] - s["diameter_mm"]) < 0.01
                    and (e.get("length_mm") is None or s["length_mm"] is None
                         or abs(e["length_mm"] - s["length_mm"]) < 0.05)), None)
        if hit is None:
            hit = {"diameter_mm": s["diameter_mm"]}
            table["inserts"].append(hit)
        hit.update({"length_mm": s["length_mm"], "cd": s["cd"], "cd_sd": s["cd_sd"], "n_points": s["n_points"],
                    "measured": today, "source": ", ".join(s["runs"])})
    table["inserts"].sort(key=lambda e: (e["diameter_mm"], e.get("length_mm") or 0))
    CD_TABLE.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    print(f"updated {CD_TABLE}")


if __name__ == "__main__":
    main()
