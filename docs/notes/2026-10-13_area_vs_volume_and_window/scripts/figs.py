"""Figures for F2 + H1 (scratch)."""
import sys
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
DAY = Path("/Volumes/LaCie/Experiments/2026/10/12")
df = pd.read_csv(HERE / "per_run_f2h1.csv")
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
OR_COL = {0.5: "#2a78d6", 1.2: "#eb6834", 1.8: "#1baf7a", 0.8: "#52514e"}
OR_MK = {0.5: "o", 1.2: "o", 1.8: "o", 0.8: "D"}
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False})


def orifice_scatter(ax, x, y, labels=True):
    for o in [0.5, 1.2, 1.8, 0.8]:
        d = df[df.orifice == o]
        ax.scatter(d[x], d[y], s=42, c=OR_COL[o], marker=OR_MK[o], edgecolors="white", linewidths=1.2,
                   label=f"{o} mm (n={len(d)})", zorder=3)
        if labels:
            for _, r in d.iterrows():
                ax.annotate(r.label, (r[x], r[y]), xytext=(3, 3), textcoords="offset points", fontsize=6.5, color=INK2)


# 1. area vs volume
fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
for ax, y, nm in [(axes[0], "af_vol_round_all", "round cross-section"), (axes[1], "af_vol_ribbon_all", "ribbon (thickness = half width)")]:
    orifice_scatter(ax, "af_all", y)
    r_all = spearmanr(df.af_all, df[y])[0]
    fc = df[df.orifice >= 0.8]
    r_fc = spearmanr(fc.af_all, fc[y])[0]
    ax.set_xlabel("atomised fraction by AREA, all 508 frames (%)")
    ax.set_ylabel(f"atomised fraction by VOLUME, {nm} (%)")
    ax.set_yscale("log")
    ax.set_title(f"Volume vs area, {nm}\nSpearman all 33: {r_all:+.2f}   orifice >= 0.8 mm: {r_fc:+.2f}", fontsize=10, color=INK)
axes[0].legend(title="orifice", fontsize=8, title_fontsize=8, frameon=False)
fig.tight_layout()
fig.savefig(HERE / "fig1_area_vs_volume.png", dpi=150)
plt.close(fig)

# 2. ratio vs factors
fig, axes = plt.subplots(1, 4, figsize=(15, 4), sharey=True)
rng = np.random.default_rng(0)
for ax, f, xl in zip(axes, ["gas", "feed", "orifice", "rpm"], ["gas (sccm)", "feed (steps/s)", "orifice (mm)", "bubbler (rpm)"]):
    span = df[f].max() - df[f].min()
    for o in [0.5, 1.2, 1.8, 0.8]:
        d = df[df.orifice == o]
        ax.scatter(d[f] + rng.uniform(-0.025, 0.025, len(d)) * span, d.ratio_round_all, s=36, c=OR_COL[o], marker=OR_MK[o],
                   edgecolors="white", linewidths=1.0, label=f"{o} mm", zorder=3)
    fc = df[df.orifice >= 0.8]
    ax.set_title(f"{xl}\nSpearman all {spearmanr(df[f], df.ratio_round_all)[0]:+.2f}, FC {spearmanr(fc[f], fc.ratio_round_all)[0]:+.2f}",
                 fontsize=9, color=INK)
    ax.set_xlabel(xl)
axes[0].set_ylabel("volume / area atomised fraction (round)")
axes[0].set_yscale("log")
axes[0].legend(title="orifice", fontsize=7, title_fontsize=7, frameon=False)
fig.tight_layout()
fig.savefig(HERE / "fig2_ratio_vs_factors.png", dpi=150)
plt.close(fig)

# 3. window delta per run
d = df.sort_values("order").merge(pd.read_csv(HERE / "per_run_meanT_fix.csv")[["run", "daf_fix97"]], on="run", how="left")
keys = [("P10", "#2a78d6"), ("P20", "#eb6834"), ("P40", "#1baf7a"), ("DARK70", "#eda100")]
fig, (ax, ax2) = plt.subplots(2, 1, figsize=(15, 7.5), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
x = np.arange(len(d))
bw = 0.2
for j, (k, c) in enumerate(keys):
    ax.bar(x + (j - 1.5) * bw, d[f"daf_{k}"], width=bw * 0.9, color=c, label={"P10": "persistence >= 10%",
           "P20": "persistence >= 20%", "P40": "persistence >= 40%", "DARK70": "bg < 70% of bg median"}[k], zorder=3)
ax.axhline(0, color=INK2, lw=0.8)
ax.set_ylabel("change in atomised fraction (points)\nwindow px removed from both sides")
ax.set_title("H1: removing 'window' pixels (persistence / dark background), all 508 frames per run", fontsize=10, color=INK)
ax.legend(frameon=False, fontsize=8, ncol=4)
ax2.bar(x, d["daf_fix97"], width=0.6, color="#6250d6", zorder=3,
        label="drop out-of-focus model pieces with mean T >= 0.97 (30-frame sample)")
ax2.axhline(0, color=INK2, lw=0.8)
ax2.set_ylabel("change (points)")
ax2.set_title("Static objects re-entering via the model's out-of-focus union (mean-T rule, 30-frame sample)", fontsize=10, color=INK)
ax2.legend(frameon=False, fontsize=8)
ax2.set_xticks(x)
ax2.set_xticklabels([f"{r.label}\n{r.orifice}" for _, r in d.iterrows()], fontsize=7)
ax2.set_xlabel("deck label / orifice (mm), capture order")
fig.tight_layout()
fig.savefig(HERE / "fig3_window_delta.png", dpi=150)
plt.close(fig)
print("figs done")
