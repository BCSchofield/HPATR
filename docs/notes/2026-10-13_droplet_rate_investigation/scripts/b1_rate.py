"""B1 (2026-10-13): mass-balance droplet production rate for the CCD day, read-only.

Per run (liquid stage 2.3.0 outputs, droplets_0.30 in-focus sizes, run_summary gas log):
  Q_L         syringe liquid flow, mL/min, from the feed steps/s in the folder name
  Q_atom      Q_L x atomised fraction BY VOLUME (2.3.0)   [and by area, for comparison]
  v_bar       mean in-focus droplet volume, pi/6 <d^3>
  N_dot       droplets produced per second = Q_atom / v_bar ; N_dot_band = N_dot x (in-band share by number)
  band_pf     in-focus droplets per frame in [30, 50) um (the app's response)
  t_view      band_pf / N_dot_band: in-focus droplets seen per frame per droplet produced per second (s);
              proportional to time-in-view x in-focus share. If droplets go faster, it falls.
  t_liquid    mean total liquid volume in view / Q_L (s): the liquid's mean residence time in the field,
              IF the whole spray cross-section is in the frame (volume +/-40%)
Writes b1_rate.csv and figures next to this script.
"""
import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/Users/benschofield/Documents/GitHub/HPATR")
from src.ai.Taguchi_Analysis_UI import operating  # noqa: E402

DAY = Path("/Volumes/LaCie/Experiments/2026/10/12")
BAND = (30.0, 50.0)
SYRINGE_MM2 = math.pi * (20.27 / 2) ** 2
STEPS_PER_MM = 6800.0
FRAME_MM = (20.48, 11.52)
NAME = re.compile(r"(\d{6})_(\d+)sccm_(\d+)rpm_(\d+)sps_or([\d.]+)_bh")


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    ra = np.argsort(np.argsort(a[ok])).astype(float)
    rb = np.argsort(np.argsort(b[ok])).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1]), int(ok.sum())


rows = []
for run in sorted(DAY.glob("*_bh0.5")):
    m = NAME.match(run.name)
    t, sccm, rpm, sps, orif = m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5))
    an = run / "shadowgraph" / "analysis"
    if not (an / "liquid_0.30" / "classical_summary.json").exists():
        print("not re-run yet:", run.name)
        continue
    cs = json.loads((an / "liquid_0.30" / "classical_summary.json").read_text())
    if cs.get("provenance", {}).get("liquid_version") != "2.3.0":
        print("not re-run yet:", run.name)
        continue
    cpf = list(csv.DictReader(open(an / "liquid_0.30" / "classical_per_frame.csv")))
    frames = [r["frame"] for r in cpf]
    n_fr = len(frames)
    d = np.array([float(r["diameter_um"]) for r in csv.DictReader(open(an / "droplets_0.30" / "droplet_sizes.csv"))
                  if r["in_focus"] == "1"])
    in_band = (d >= BAND[0]) & (d < BAND[1])
    q_l = SYRINGE_MM2 * sps / STEPS_PER_MM * 60 / 1000          # mL/min
    q_l_mm3s = q_l * 1000 / 60
    atom_a, atom_v = cs["atomised_pct_pooled"], cs.get("atomised_vol_pct_pooled")
    v_bar_mm3 = math.pi / 6 * float(np.mean(d ** 3)) * 1e-9 if d.size else float("nan")
    n_dot = q_l_mm3s * atom_v / 100 / v_bar_mm3 if d.size else float("nan")
    n_dot_area = q_l_mm3s * atom_a / 100 / v_bar_mm3 if d.size else float("nan")
    share = in_band.mean() if d.size else float("nan")
    n_dot_band = n_dot * share
    band_pf = in_band.sum() / n_fr
    vol_tot = np.array([float(r["total_liquid_vol_mm3"]) for r in cpf])
    vol_drop = np.array([float(r["droplet_vol_mm3"]) for r in cpf])
    t_liq = vol_tot.mean() / q_l_mm3s
    op = operating.operating_point(run / "run_summary.xlsx", sccm)
    rows.append(dict(run=run.name, time=t, set_sccm=sccm, rpm=rpm, sps=sps, orifice=orif,
                     regime=op.regime, gas_sccm=op.delivered_sccm, p0_bar=op.p0_bar,
                     q_l_ml_min=round(q_l, 3), frames=n_fr, n_focus=int(d.size),
                     focus_pf=round(d.size / n_fr, 3), band_pf=round(band_pf, 3),
                     d_mean_um=round(float(d.mean()), 2) if d.size else None,
                     d30_um=round(float(np.mean(d ** 3)) ** (1 / 3), 2) if d.size else None,
                     band_share=round(share, 4), atom_area_pct=atom_a, atom_vol_pct=atom_v,
                     n_dot_per_s=round(n_dot), n_dot_area_per_s=round(n_dot_area),
                     n_dot_band_per_s=round(n_dot_band),
                     t_view_ms=round(1000 * band_pf / n_dot_band, 4) if n_dot_band else None,
                     vol_in_view_mm3=round(vol_tot.mean(), 3), drop_vol_in_view_mm3=round(vol_drop.mean(), 4),
                     t_liquid_ms=round(1000 * t_liq, 2),
                     v_liq_m_s_long=round(FRAME_MM[0] / 1000 / t_liq, 3),
                     v_liq_m_s_short=round(FRAME_MM[1] / 1000 / t_liq, 3)))
    print(f"{run.name[:40]:40s} {op.regime:17s} band_pf {band_pf:6.2f}  Ndot_band {n_dot_band:9.0f}/s  "
          f"t_view {1000 * band_pf / n_dot_band if n_dot_band else float('nan'):.3f} ms  t_liq {1000 * t_liq:6.1f} ms")

with open(HERE / "b1_rate.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(len(rows), "runs ->", HERE / "b1_rate.csv")

# ---- comparisons --------------------------------------------------------------------------------------
fc = [r for r in rows if r["regime"] == operating.FLOW_CONTROLLED]
spray = [r for r in rows if r["atom_area_pct"] >= 2.0]
for label, sub in (("all spraying runs", spray), ("flow-controlled", [r for r in fc if r in spray])):
    g = lambda k: [r[k] for r in sub]  # noqa: E731
    print(f"\n{label} (n={len(sub)})")
    print("  Spearman band_pf vs N_dot_band       ", "%.3f (n=%d)" % spearman(g("band_pf"), g("n_dot_band_per_s")))
    print("  Spearman focus_pf vs N_dot           ", "%.3f (n=%d)" % spearman(g("focus_pf"), g("n_dot_per_s")))
    print("  Spearman N_dot (vol) vs N_dot (area) ", "%.3f (n=%d)" % spearman(g("n_dot_per_s"), g("n_dot_area_per_s")))
    print("  Spearman t_view vs delivered gas     ", "%.3f (n=%d)" % spearman(g("t_view_ms"), g("gas_sccm")))
    print("  Spearman t_liquid vs delivered gas   ", "%.3f (n=%d)" % spearman(g("t_liquid_ms"), g("gas_sccm")))
    print("  Spearman t_view vs t_liquid          ", "%.3f (n=%d)" % spearman(g("t_view_ms"), g("t_liquid_ms")))
    top_pf = sorted(sub, key=lambda r: -r["band_pf"])[:5]
    top_nd = sorted(sub, key=lambda r: -r["n_dot_band_per_s"])[:5]
    print("  best 5 by band_pf   ", [r["time"] for r in top_pf])
    print("  best 5 by N_dot_band", [r["time"] for r in top_nd])

# ---- figures ------------------------------------------------------------------------------------------
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

COL = {0.5: "#d62728", 0.8: "#9467bd", 1.2: "#1f77b4", 1.8: "#2ca02c"}


def scatter(ax, sub, x, y, xl, yl, label_runs=True):
    for o in sorted(COL):
        s = [r for r in sub if r["orifice"] == o]
        if not s:
            continue
        lim = [r for r in s if r["regime"] != operating.FLOW_CONTROLLED]
        ok = [r for r in s if r["regime"] == operating.FLOW_CONTROLLED]
        ax.scatter([r[x] for r in ok], [r[y] for r in ok], c=COL[o], label=f"{o} mm", s=36)
        ax.scatter([r[x] for r in lim], [r[y] for r in lim], facecolors="none", edgecolors=COL[o], s=36,
                   label=f"{o} mm, pressure-limited")
    if label_runs:
        for r in sub:
            ax.annotate(r["time"][:4], (r[x], r[y]), fontsize=6, alpha=0.6, xytext=(2, 2), textcoords="offset points")
    ax.set_xlabel(xl)
    ax.set_ylabel(yl)
    ax.grid(alpha=0.3)


fig, axs = plt.subplots(1, 3, figsize=(16, 4.8))
scatter(axs[0], spray, "band_pf", "n_dot_band_per_s", "in-focus droplets per frame, 30-50 um (concentration)",
        "30-50 um droplets produced per second (mass balance)")
axs[0].set_yscale("log")
axs[0].set_title("Rate vs concentration (spraying runs)")
scatter(axs[1], spray, "gas_sccm", "t_view_ms", "gas delivered in the camera window (sccm)",
        "concentration / rate (ms)")
axs[1].set_title("In view per droplet made: falls if droplets go faster")
scatter(axs[2], spray, "gas_sccm", "t_liquid_ms", "gas delivered in the camera window (sccm)",
        "liquid volume in view / liquid flow (ms)")
axs[2].axhline(1000 / 390, color="k", lw=0.8, ls="--")
axs[2].text(axs[2].get_xlim()[0], 1000 / 390, " 2.56 ms between frames", fontsize=7, va="bottom")
axs[2].set_title("Mean residence time of the liquid in the field")
axs[0].legend(fontsize=7, loc="lower right")
fig.tight_layout()
fig.savefig(HERE / "b1_rate.png", dpi=130)
print("figure ->", HERE / "b1_rate.png")
