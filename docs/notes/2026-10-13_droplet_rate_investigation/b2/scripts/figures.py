"""Figures for the B2 velocity-feasibility note (static PNGs)."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from common import load, RUNS, CONTROL, HERE, SCCM

RES = HERE / "results"; FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)
COL = {"low_7000": "#2a78d6", "centre_9000": "#eb6834", "high_11000": "#1baf7a", CONTROL: "#6b6a66"}
LAB = {"low_7000": "7000 sccm", "centre_9000": "9000 sccm", "high_11000": "11000 sccm", CONTROL: "C3 dribble (control)"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 130,
                     "savefig.bbox": "tight", "axes.titlesize": 9.5, "axes.titleweight": "bold"})


def tshow(ax, T, title):
    ax.imshow(T, cmap="gray", vmin=0.3, vmax=1.05, interpolation="nearest")
    ax.set_title(title, loc="left"); ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)


# ---------- Fig 1: frame pairs ----------
Dc = load("high_11000"); Dd = load(CONTROL)
y0, x0, h, w = 564, 1408, 400, 640      # densest 400x640 crop over consecutive frames (searched)
fig, axs = plt.subplots(2, 3, figsize=(11, 5.4))
tshow(axs[0, 0], Dc["A"][23][y0:y0 + h, x0:x0 + w], "11000 sccm, frame k (n=2523)")
tshow(axs[0, 1], Dc["A"][24][y0:y0 + h, x0:x0 + w], "frame k+1 (+2.56 ms)")
tshow(axs[0, 2], Dc["A"][25][y0:y0 + h, x0:x0 + w], "frame k+2 (+5.13 ms)")
yd, xd = 0, 1350
ks = [12, 13, 20]
for j, k in enumerate(ks):
    T = Dd["D"][k][yd:yd + h, xd:xd + w]
    tshow(axs[1, j], T, f"C3 dribble, frame {1630 + k}" + (" (k)" if j == 0 else f" (k+{k - ks[0]})"))
# mark the two tracked mist droplets in the dribble (positions from the blob tracker)
from common import segment
for j, k in enumerate(ks):
    _, bl = segment(Dd["D"][k])
    for b in bl:
        if 2 <= b["d_eq"] <= 12 and yd <= b["cy"] < yd + h and xd <= b["cx"] < xd + w:
            axs[1, j].add_patch(Circle((b["cx"] - xd, b["cy"] - yd), 14, fill=False, ec="#eb6834", lw=1.2))
fig.suptitle("Consecutive full-rate frames (T = I / I_bg, 400 x 640 px = 4.0 x 6.4 mm crops). "
             "Spray: nothing in k reappears in k+1. Dribble: the same mist droplets drift ~5 px/frame (circled), the stream persists.",
             x=0.0, ha="left", fontsize=9.5, color=INK)
fig.savefig(FIG / "fig1_frame_pairs.png"); plt.close(fig)

# ---------- Fig 2: correlation ----------
piv = json.loads((RES / "piv_summary.json").read_text())


def snr_map(tag, name, half=400):
    e = np.load(RES / f"ens_full_{tag}_{name}.npy").astype(np.float64)
    H2, W2 = e.shape; cy, cx = (H2 - 1) // 2, (W2 - 1) // 2
    dy = np.arange(H2) - cy; dx = np.arange(W2) - cx
    ov = (1152 - np.abs(dy))[:, None] * (2048 - np.abs(dx))[None, :]
    e = e / ov                                   # per-overlap-pixel correlation
    e[cy - 2:cy + 3, cx - 2:cx + 3] = np.nan     # zero shift masked (static residue)
    s = (e - np.nanmean(e)) / np.nanstd(e)
    return s[cy - half:cy + half + 1, cx - half:cx + half + 1]


fig = plt.figure(figsize=(11.5, 6.6))
gs = fig.add_gridspec(2, 3, height_ratios=[1, 0.85], hspace=0.38, wspace=0.18)
maps = [("centre_9000", "lag1_A", "9000 sccm: k vs k+1 (29 pairs)"),
        ("centre_9000", "ctrl_lag50", "9000 sccm: k vs k+50 (control)"),
        (CONTROL, "lag1_A", "C3 dribble: k vs k+1 (positive control)")]
for j, (tag, name, title) in enumerate(maps):
    ax = fig.add_subplot(gs[0, j])
    s = snr_map(tag, name)
    im = ax.imshow(np.clip(s, 0, 12), cmap="Blues", vmin=0, vmax=12, extent=[-400, 400, 400, -400], interpolation="nearest")
    ax.set_title(title, loc="left"); ax.grid(False)
    ax.set_xlabel("dx (px)"); ax.set_ylabel("dy (px, + = down)")
    iy, ix = np.unravel_index(np.nanargmax(s), s.shape)
    ax.text(0.02, 0.03, f"max {np.nanmax(s):.0f} sd at ({iy - 400:+d}, {ix - 400:+d})", transform=ax.transAxes,
            fontsize=8, color=INK, bbox=dict(fc="white", ec="none", alpha=0.8))
cb = fig.colorbar(im, ax=fig.axes[:3], fraction=0.015, pad=0.01); cb.set_label("sd above mean")
ax = fig.add_subplot(gs[1, :])
rowsets = [("lag1_A", "k vs k+1 (burst A)"), ("lag1_B", "k vs k+1 (burst B)"), ("lag2_A", "k vs k+2"),
           ("ctrl_lag50", "control: k vs k+50"), ("ctrl_AvsB", "control: burst A vs B")]
ylabels = []
yy = 0
for key, lab in rowsets:
    for tag in RUNS:
        v = piv[tag][key]["ens_full"]["snr"]
        ax.plot(v, yy, "o", ms=7, color=COL[tag], mec="white", mew=1.0, label=LAB[tag] if key == "lag1_A" else None)
    ylabels.append((yy, lab)); yy += 1
syn = piv["synthetic_centre_9000"]
for f in ["0.05", "0.1", "0.25"]:
    ax.plot(syn[f]["ensemble_snr"], yy, "D", ms=6, color="#6250d6", mec="white", mew=1.0,
            label="synthetic: f of k's droplets re-placed at (+150, +40) px" if f == "0.05" else None)
    ylabels.append((yy, f"synthetic, {int(float(f) * 100)} % persist (9000 sccm)")); yy += 1
for key, lab in [("lag1_A", "C3 dribble: k vs k+1 (A)"), ("lag1_D", "C3 dribble: k vs k+1 (D)"),
                 ("ctrl_lag50", "C3 dribble: control k vs k+50")]:
    ax.plot(piv[CONTROL][key]["ens_full"]["snr"], yy, "s", ms=6, color=COL[CONTROL],
            mec=COL[CONTROL] if key.startswith("ctrl") else "white", mew=1.2,
            mfc=COL[CONTROL] if not key.startswith("ctrl") else "white",
            label="C3 dribble (slow mist, real data; open = control)" if key == "lag1_A" else None)
    ylabels.append((yy, lab)); yy += 1
ctrl_max = max(piv[t][k]["ens_full"]["snr"] for t in RUNS for k in ("ctrl_lag50", "ctrl_AvsB"))
ax.axvline(ctrl_max, color=INK2, lw=1, ls="--"); ax.text(ctrl_max * 0.95, 6.0, "highest spray control", color=INK2, fontsize=8, ha="right", va="center")
ax.set_xscale("log"); ax.set_xlim(3, 300)
ax.set_yticks([y for y, _ in ylabels]); ax.set_yticklabels([l for _, l in ylabels]); ax.invert_yaxis()
ax.set_xlabel("ensemble correlation peak, sd above the plane mean (zero shift excluded)")
ax.set_title("Peak strength: real consecutive pairs sit at the control level; 5 % persistence would be obvious", loc="left")
ax.legend(loc="upper right", fontsize=7.5, frameon=False)
fig.savefig(FIG / "fig2_correlation.png"); plt.close(fig)

# ---------- Fig 3: blob tests ----------
nn = json.loads((RES / "nn_summary.json").read_text())
sec = json.loads((RES / "nn_sector.json").read_text())
fig, axs = plt.subplots(1, 4, figsize=(13, 3.4), gridspec_kw=dict(width_ratios=[1.25, 1, 1, 1], wspace=0.3))
ax = axs[0]
for tag in RUNS + [CONTROL]:
    r = [int(k) for k in nn[tag]["lag1"]["persistence"]]
    ax.plot(r, [nn[tag]["lag1"]["persistence"][str(k)] for k in r], "-o", color=COL[tag], lw=2, ms=4, label=LAB[tag] + ", k+1")
    ax.plot(r, [nn[tag]["ctrl"]["persistence"][str(k)] for k in r], "--", color=COL[tag], lw=1.2, label=None)
ax.set_xscale("log"); ax.set_xlabel("search radius (px; 100 px = 1 mm)"); ax.set_ylabel("fraction of droplets with a partner")
ax.set_title("Persistence: solid k+1, dashed control", loc="left"); ax.legend(fontsize=7, frameon=False, loc="upper left")
edges = np.array(sec["edges"]); ctr = (edges[:-1] + edges[1:]) / 2
for j, tag in enumerate(RUNS):
    ax = axs[j + 1]
    ax.plot(ctr, sec[tag]["lag1"]["hist_per_pair"], "-", color=COL[tag], lw=2, label="k vs k+1")
    ax.plot(ctr, sec[tag]["ctrl"]["hist_per_pair"], "--", color=INK2, lw=1.2, label="control")
    for v in (2.0, 4.0):
        dy = v / 390 / 10e-6
        ax.axvline(dy, color=INK2, lw=0.8, ls=":"); ax.text(dy + 15, ax.get_ylim()[1] * 0.92 if False else 0, f"{v:.0f} m/s", fontsize=7, color=INK2, rotation=90, va="bottom")
    e, s_ = sec[tag]["excess_per_pair"]
    ax.set_title(f"{LAB[tag]}: downstream column", loc="left")
    ax.text(0.02, 0.97, f"downstream excess {e:+.1f} ± {s_:.1f} /pair\nexpected if all at 2 m/s: {sec[tag]['expected_reseen_per_pair_if_all_move_at_v']['2.0']:.0f}",
            transform=ax.transAxes, va="top", fontsize=7.5, color=INK)
    ax.set_xlabel("dy (px, + = down)"); ax.set_ylabel("pair vectors per frame pair" if j == 0 else "")
    if j == 0:
        ax.legend(fontsize=7, frameon=False, loc="lower left", bbox_to_anchor=(0.0, 0.55))
fig.text(0.37, -0.06, "Panels 2-4: dy of every size-matched (d_eq within 30 %) droplet pair with |dx| < 150 px, k -> k+1 vs control pairs. "
         "A droplet re-seen downstream would add a bump at its dy; dotted lines = 2 and 4 m/s.", fontsize=8, color=INK2)
fig.savefig(FIG / "fig3_blob_matching.png"); plt.close(fig)

# ---------- Fig 4: blur ----------
bb = json.loads((RES / "blur_bounds.json").read_text())
bs = json.loads((RES / "blur_summary.json").read_text())
fig, axs = plt.subplots(1, 3, figsize=(12.5, 3.6), gridspec_kw=dict(wspace=0.35))
ax = axs[0]
xs = {t: i for i, t in enumerate(RUNS + [CONTROL])}
for t in RUNS + [CONTROL]:
    m, lo, hi = bs[t]["D_flow_median"]
    ax.errorbar(xs[t], m, yerr=[[m - lo], [hi - m]], fmt="o", color=COL[t], ms=7, capsize=3, lw=1.5)
    m2, lo2, hi2 = bs[t]["D_diag_median"]
    ax.errorbar(xs[t] + 0.18, m2, yerr=[[m2 - lo2], [hi2 - m2]], fmt="s", color=COL[t], mfc="white", ms=6, capsize=3, lw=1.2)
ax.axhline(0, color=INK2, lw=0.8)
ax.set_xticks(list(xs.values())); ax.set_xticklabels(["7000", "9000", "11000", "C3\ndribble"])
ax.set_ylabel("px²"); ax.set_title("Droplet anisotropy (median, 95% CI)\n● μyy−μxx (flow axis)   □ 2μxy (diagonal)", loc="left")
ax = axs[1]
for t in RUNS + [CONTROL]:
    for k, mk, off in (("edge_along_median", "o", -0.1), ("edge_across_median", "o", 0.1)):
        m, lo, hi = bs[t][k]
        ax.errorbar(xs[t] + off, m, yerr=[[m - lo], [hi - m]], fmt=mk, color=COL[t], mfc=COL[t] if "along" in k else "white",
                    ms=6, capsize=3, lw=1.2)
ax.set_xticks(list(xs.values())); ax.set_xticklabels(["7000", "9000", "11000", "C3\ndribble"])
ax.set_ylabel("20–80 % edge width (px)")
ax.set_title("20-80 % edge widths (median, 95% CI)\n● along flow (top/bottom)  ○ across (left/right)", loc="left")
ax.text(0.02, 0.03, "control droplets are smaller (3.7 px vs 7 px);\nsize-matched comparison in panel 3", transform=ax.transAxes, fontsize=7.5, color=INK2)
ax = axs[2]
for t in RUNS:
    i = xs[t]
    ax.plot([i, i], [0, bb[t]["v_upper95_ms"]], color=COL[t], lw=6, solid_capstyle="butt", alpha=0.35)
    ax.plot(i, bb[t]["v_point_ms"], "o", color=COL[t], ms=7)
    ax.text(i + 0.12, bb[t]["v_upper95_ms"], f"≤ {bb[t]['v_upper95_ms']:.1f}", fontsize=8, va="center", color=INK)
ax.axhline(2.5, color=INK2, lw=0.8, ls=":"); ax.text(2.45, 2.55, "1 px blur at 4 µs", fontsize=7.5, color=INK2, ha="right")
ax.set_xticks([0, 1, 2]); ax.set_xticklabels(["7000", "9000", "11000"]); ax.set_xlim(-0.5, 2.8); ax.set_ylim(0, 6)
ax.set_ylabel("in-plane velocity (m/s)")
ax.set_title("Blur velocity, matched to control\nbar: 0 to 95 % upper bound; dot: point", loc="left")
fig.savefig(FIG / "fig4_blur.png"); plt.close(fig)

# ---------- Fig 5: velocity constraints summary ----------
fig, ax = plt.subplots(figsize=(9.5, 3.4))
rows = [
    ("on-axis gas jet at 100 mm (7000–11000 sccm)", 7.0, 16.1, "#9a9994"),
    ("on-axis gas jet at 300 mm", 2.3, 5.4, "#9a9994"),
    ("blur bound, detected sharp droplets (95 % upper)", 0.0, 4.2, "#eb6834"),
    ("pairable now: 390 fps, ≤ 5 mm/frame along flow", 0.0, 2.0, "#2a78d6"),
    ("proposed: 50 kfps (Δt 20 µs), 5–50 px", 2.5, 25.0, "#1baf7a"),
    ("proposed: 100 kfps (Δt 10 µs), 5–50 px", 5.0, 50.0, "#1baf7a"),
]
for i, (lab, lo, hi, c) in enumerate(rows):
    ax.plot([max(lo, 0.1), hi], [i, i], color=c, lw=9, solid_capstyle="butt")
    ax.text(hi * 1.08, i, f"{lo:g}–{hi:g} m/s", va="center", fontsize=8, color=INK)
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows]); ax.invert_yaxis()
ax.set_xscale("log"); ax.set_xlim(0.1, 120); ax.set_xlabel("velocity (m/s)")
ax.set_title("What each constraint says about droplet velocity at the measurement station (distance not recorded)", loc="left")
fig.savefig(FIG / "fig5_velocity_constraints.png"); plt.close(fig)
print("figures written to", FIG)
