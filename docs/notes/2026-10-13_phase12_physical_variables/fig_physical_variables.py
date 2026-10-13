"""Phase 12 evidence (2026-10-13): CCD day atomised fraction (liquid 2.3.0) against candidate physical
variables, both regimes. Reads ../2026-10-13_droplet_rate_investigation/b1_rate.csv; writes the PNG
next to this script."""
import csv
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
rows = [r for r in csv.DictReader(open(HERE.parent / "2026-10-13_droplet_rate_investigation" / "b1_rate.csv"))
        if float(r["atom_area_pct"]) >= 2]
COL = {0.5: "#d62728", 0.8: "#9467bd", 1.2: "#1f77b4", 1.8: "#2ca02c"}


def feats(r):
    q, o, ql = float(r["gas_sccm"]), float(r["orifice"]), float(r["q_l_ml_min"])
    v = q * 1e-6 / 60 / (math.pi * (o / 2e3) ** 2)
    glr = (q / 60 * 1.204e-3) / (ql / 60 * 1.07)
    return {"set": float(r["set_sccm"]), "glr": glr, "p0": float(r["p0_bar"]), "v": v}


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return np.corrcoef(ra, rb)[0, 1]


y = np.array([float(r["atom_area_pct"]) for r in rows])
F = [feats(r) for r in rows]
panels = [("set", "gas set point (sccm)", False), ("glr", "GLR, delivered (mass ratio)", False),
          ("p0", "upstream pressure in the camera window (barA)", False),
          ("v", "gas exit velocity, delivered gas / orifice area (m/s, standard density)", True)]
fig, axs = plt.subplots(1, 4, figsize=(19, 4.6), sharey=True)
for ax, (k, xl, logx) in zip(axs, panels):
    x = np.array([f[k] for f in F])
    for o in sorted(COL):
        for lim in (False, True):
            sel = [i for i, r in enumerate(rows) if float(r["orifice"]) == o and (r["regime"] != "flow-controlled") == lim]
            if sel:
                ax.scatter(x[sel], y[sel], s=40, c="none" if lim else COL[o], edgecolors=COL[o], linewidths=1.4,
                           label=f"{o} mm" + (", pressure-limited" if lim else ""))
    ax.set_xlabel(xl, fontsize=9)
    if logx:
        ax.set_xscale("log")
    ax.set_title(f"Spearman {spearman(x, y):+.2f} (31 spraying runs)", fontsize=10)
    ax.grid(alpha=0.3)
axs[0].set_ylabel("atomised fraction by area (%)")
axs[0].legend(fontsize=7, loc="upper left")
fig.suptitle("CCD day 2026-10-12: which physical variable explains atomisation across BOTH regimes? "
             "(filled = flow-controlled, hollow = pressure-limited)", fontsize=11)
fig.tight_layout()
fig.savefig(HERE / "fig_physical_variables.png", dpi=120)
print("written", HERE / "fig_physical_variables.png")
