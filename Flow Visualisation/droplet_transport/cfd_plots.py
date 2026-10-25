"""Phase 3a figures (matplotlib, PNG): the floor deposit maps, where each size ends up, and the checks. Phase 1's
style and palette (plots.STYLE: the reference data-viz palette, light mode).

The floor is drawn seen from above, in the CAD's mm. On it: the chamber's objects as seen from above (the atomiser
body, nozzle block and arm: their outline, taken from the mesh), the spray's exit orifice, and the port (a thick line
on the wall it is in). A map's colour is how densely a group of droplets landed, as % of the group fired per cm²,
smoothed (a Gaussian, its width by Scott's rule for that panel's count), on one log scale shared by every panel of a
figure; the lines enclose the densest half and the densest 90 % of what landed on the floor.
"""
from __future__ import annotations

from dataclasses import dataclass

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, LogNorm  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

from . import cfd_results as R  # noqa: E402
from .plots import AXIS, BAND, INK, INK2, MUTED, RAMP, SERIES, STYLE, SURFACE  # noqa: E402

PX_MM = 0.5                         # the objects' outline is found on this grid
MAP_MM = 1.0                        # the deposit maps' grid
MIN_FOR_MAP = 25                    # fewer droplets on the floor than this: each is shown as a dot instead
DENSITY = LinearSegmentedColormap.from_list("deposit", RAMP)
OBJ = SERIES[1]                     # the objects and the orifice
HALO = [pe.withStroke(linewidth=2.6, foreground="white")]
GROUP_COLOURS = {R.FLOOR_MOVING: SERIES[0], R.FLOOR_STILL: RAMP[2], R.SIDES: SERIES[2], R.OBJECTS: SERIES[1],
                 R.PORT: SERIES[6], "lid": SERIES[4], R.SPRAY_HOLE: SERIES[3], R.AIRBORNE: MUTED}
# (validated in this order, light mode: the six hues pass; the still-air floor is a tint of the floor's blue and
#  airborne is neutral, both on purpose; a legend and report.md's tables carry every value)


def plan_axes(scn) -> tuple[int, int]:
    """The floor's two axes (horizontal, vertical on the page)."""
    h, v = [a for a in range(3) if a != scn.up]
    return h, v


def floor_level(scn) -> float:
    return scn.inside[scn.up, 0 if scn.up_sign > 0 else 1]


def impact_point(scn) -> np.ndarray:
    """Where the spray's axis meets the floor (m)."""
    k = scn.direction[scn.up]
    if abs(k) < 1e-9:
        return np.full(3, np.nan)
    return scn.hole + (floor_level(scn) - scn.hole[scn.up]) / k * scn.direction


def _area(poly) -> np.ndarray:
    """A 3-D polygon's area vector (m², along its normal)."""
    p = np.asarray(poly, float)
    return 0.5 * np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0)


# ---- what the floor map draws on top: from the mesh, once per run -------------------------------------------------

def plan_view(scn, faces: dict | None, walls) -> dict:
    """The chamber seen from above, for the maps: the objects' footprint (a mask on a PX_MM grid), the exit
    orifice (centre, diameter), each port (where on which wall). `faces` is cfd_droplets.boundary_faces; None (a
    binary mesh) leaves the objects and ports out."""
    h, v = plan_axes(scn)
    lo, hi = scn.inside[:, 0] * 1000, scn.inside[:, 1] * 1000
    xs = np.arange(lo[h] + PX_MM / 2, hi[h], PX_MM)
    zs = np.arange(lo[v] + PX_MM / 2, hi[v], PX_MM)
    mask = np.zeros((zs.size, xs.size), bool)
    floor = floor_level(scn) * 1000
    out = {"h": h, "v": v, "extent": [float(lo[h]), float(hi[h]), float(lo[v]), float(hi[v])], "mask": mask,
           "orifice_mm": (scn.hole * 1000).tolist(), "orifice_d_mm": None, "ports": [], "objects_from_mm": None}
    if faces is None:
        out["mask"] = None
        return out
    lowest = np.inf
    for name in walls:
        for poly in faces.get(name, []):
            pm = np.asarray(poly) * 1000
            c = pm.mean(axis=0)
            if (np.abs(c - lo) < 0.6).any() or (np.abs(c - hi) < 0.6).any() or (c < lo).any() or (c > hi).any():
                continue                                        # a chamber wall, or a port's stub
            lowest = min(lowest, abs(pm[:, scn.up] - floor).min())
            q = pm[:, [h, v]]
            if abs(_area(np.c_[q, np.zeros(len(q))])[2]) < 1e-3:
                continue                                        # edge-on from above
            i0, i1 = np.searchsorted(xs, [q[:, 0].min(), q[:, 0].max()])
            j0, j1 = np.searchsorted(zs, [q[:, 1].min(), q[:, 1].max()])
            if i1 <= i0 or j1 <= j0:
                continue
            X, Z = np.meshgrid(xs[i0:i1], zs[j0:j1])
            inside = MPath(q).contains_points(np.c_[X.ravel(), Z.ravel()]).reshape(X.shape)
            mask[j0:j1, i0:i1] |= inside
    out["objects_from_mm"] = float(lowest) if np.isfinite(lowest) else None
    sp = faces.get(scn.spray_patch, [])
    if sp:
        A = np.array([np.linalg.norm(_area(p)) for p in sp])
        out["orifice_d_mm"] = float(np.sqrt(4 * A.sum() / np.pi) * 1000)
    for name in scn.port_patches:
        ps = faces.get(name, [])
        if not ps:
            continue
        A = np.array([np.linalg.norm(_area(p)) for p in ps])
        C = np.array([np.mean(p, axis=0) for p in ps]) * 1000
        c = (A[:, None] * C).sum(axis=0) / A.sum()
        d = float(np.sqrt(4 * A.sum() / np.pi) * 1000)
        # the wall it opens through: the side wall nearest its centre
        wall = min(((a, k) for a in (h, v) for k in (0, 1)), key=lambda ak: abs(c[ak[0]] - scn.inside[ak[0], ak[1]]
                                                                                  * 1000))
        out["ports"].append({"name": name, "centre_mm": c.tolist(), "d_mm": d, "wall_axis": int(wall[0]),
                             "wall_mm": float(scn.inside[wall[0], wall[1]] * 1000),
                             "height_mm": float(c[scn.up] - floor)})
    return out


def save_plan(plan: dict, path):
    m = plan["mask"]
    meta = {k: v for k, v in plan.items() if k != "mask"}
    np.savez_compressed(path, mask=m if m is not None else np.zeros((0, 0), bool), meta=np.array(repr(meta)))


def load_plan(path) -> dict:
    z = np.load(path)
    from ast import literal_eval
    plan = literal_eval(str(z["meta"]))
    plan["mask"] = z["mask"] if z["mask"].size else None
    return plan


# ---- the floor deposit maps ------------------------------------------------------------------------------------------

@dataclass
class Panel:
    title: str
    pts: np.ndarray            # (n, 2) mm: where each landed on the floor, in the plan axes
    fired: int                 # droplets of the group fired (the map's density is a share of these)
    subtitle: str = ""


def _density(plan, pts, fired):
    """The smoothed deposit on a MAP_MM grid, as % of the group fired per cm². Adaptive smoothing (Abramson): a
    pilot pass with Scott's width, then each droplet smoothed by that width x (pilot density there / its geometric
    mean)^-1/2, so a crowded core stays sharp and a thin scatter does not break into blobs."""
    x0, x1, z0, z1 = plan["extent"]
    ex = np.arange(x0, x1 + MAP_MM / 2, MAP_MM)
    ez = np.arange(z0, z1 + MAP_MM / 2, MAP_MM)
    i = np.clip(np.searchsorted(ex, pts[:, 0]) - 1, 0, ex.size - 2)
    j = np.clip(np.searchsorted(ez, pts[:, 1]) - 1, 0, ez.size - 2)
    H, _, _ = np.histogram2d(pts[:, 1], pts[:, 0], bins=[ez, ex])
    sd = pts.std(axis=0).mean() if len(pts) > 1 else 5.0
    s0 = float(np.clip(sd * len(pts) ** (-1 / 6), 1.5, 15.0))              # Scott's rule, in 2-D
    pilot = gaussian_filter(H, s0 / MAP_MM, mode="reflect")[j, i]
    pilot = np.clip(pilot, pilot.max() * 1e-6, None)
    s = np.clip(s0 * np.sqrt(np.exp(np.log(pilot).mean()) / pilot), 1.0, 15.0)
    D = np.zeros(H.shape)
    edges = np.geomspace(1.0, 15.0, 8)
    for a, b in zip(edges[:-1], edges[1:]):                                # one smoothing per width class
        k = (s >= a) & ((s < b) | (b == edges[-1]))
        if k.any():
            Hk, _, _ = np.histogram2d(pts[k, 1], pts[k, 0], bins=[ez, ex])
            D += gaussian_filter(Hk, np.sqrt(a * b) / MAP_MM, mode="reflect")
    return D / fired * 100 / (MAP_MM ** 2 / 100), s0, (ex, ez)


def _hdr_levels(D, shares=(0.9, 0.5)):
    """The density levels that enclose the densest `shares` of the deposit."""
    v = np.sort(D.ravel())[::-1]
    c = np.cumsum(v)
    if c[-1] <= 0:
        return []
    return [float(v[min(np.searchsorted(c, s * c[-1]), v.size - 1)]) for s in shares]


def draw_plan(ax, scn, plan):
    """The floor's outline, the objects seen from above, the orifice, the ports."""
    x0, x1, z0, z1 = plan["extent"]
    h, v = plan["h"], plan["v"]
    ax.plot([x0, x1, x1, x0, x0], [z0, z0, z1, z1, z0], color=INK2, lw=1.0, zorder=5, solid_joinstyle="miter")
    if plan["mask"] is not None and plan["mask"].any():
        m = plan["mask"].astype(float)
        xs = np.linspace(x0 + PX_MM / 2, x1 - PX_MM / 2, m.shape[1])
        zs = np.linspace(z0 + PX_MM / 2, z1 - PX_MM / 2, m.shape[0])
        ax.contour(xs, zs, m, levels=[0.5], colors=[OBJ], linewidths=1.4, linestyles=[(0, (4, 2))], zorder=6)
    o = plan["orifice_mm"]
    ax.plot(o[h], o[v], marker="o", ms=7.5, mfc="none", mec=OBJ, mew=1.6, zorder=8, path_effects=HALO)
    ax.plot(o[h], o[v], marker="+", ms=4.5, color=OBJ, mew=1.1, zorder=8)
    ip = impact_point(scn) * 1000
    if np.isfinite(ip).all() and np.hypot(ip[h] - o[h], ip[v] - o[v]) > 2:
        ax.plot(ip[h], ip[v], marker="x", ms=6, color=INK, mew=1.3, zorder=8, path_effects=HALO)
    for p in plan["ports"]:
        c, half = p["centre_mm"], p["d_mm"] / 2
        if p["wall_axis"] == v:
            ax.plot([c[h] - half, c[h] + half], [p["wall_mm"]] * 2, color=SERIES[6], lw=5, solid_capstyle="butt",
                    zorder=7)
        else:
            ax.plot([p["wall_mm"]] * 2, [c[v] - half, c[v] + half], color=SERIES[6], lw=5, solid_capstyle="butt",
                    zorder=7)
    ax.set_xlim(x0 - 4, x1 + 4)
    ax.set_ylim(z1 + 4, z0 - 4)                      # seen from above with y up: z runs down the page
    ax.set_aspect("equal")
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=2.5, labelsize=7)
    ax.set_xlabel(f"{'xyz'[h]} (mm)", fontsize=7.5)


def floor_maps(scn, plan, rows, out_png, title: str, caption: str = ""):
    """A grid of floor maps: rows of Panels (row label, [Panel, ...]), or (label, panels, plan, scn) for a row on
    its own flow (a sweep); one log colour scale for all."""
    rows = [(r[0], r[1], r[2] if len(r) > 2 else plan, r[3] if len(r) > 3 else scn) for r in rows]
    ncol = max(len(r[1]) for r in rows)
    dens = {}
    for r, (_lab, panels, r_plan, _s) in enumerate(rows):
        for c, p in enumerate(panels):
            if len(p.pts) >= MIN_FOR_MAP:
                dens[r, c] = _density(r_plan, p.pts, p.fired)
    top = max((d[0].max() for d in dens.values()), default=1.0)
    norm = LogNorm(vmin=top / 2e3, vmax=top)
    x0, x1, z0, z1 = plan["extent"]
    w = 2.55
    H = w * (z1 - z0) / (x1 - x0) * len(rows) + 1.35
    if len(rows) == 1:
        top, bottom, cap_y = 0.86, 0.135, 0.89
    else:                                               # the margins in inches, as tuned for two rows
        top, bottom, cap_y = 1 - 1.11 / H, 0.89 / H, 1 - 0.58 / H
    with plt.rc_context(STYLE):
        fig, axs = plt.subplots(len(rows), ncol, figsize=(w * ncol + 1.0, H), squeeze=False)
        im = None
        for r, (lab, panels, r_plan, r_scn) in enumerate(rows):
            for c in range(ncol):
                ax = axs[r, c]
                if c >= len(panels):
                    ax.set_axis_off()
                    continue
                p = panels[c]
                ax.add_patch(Rectangle((x0, z0), x1 - x0, z1 - z0, color=SURFACE, zorder=0))
                if (r, c) in dens:
                    D, sigma, (ex, ez) = dens[r, c]
                    Dm = np.ma.masked_less(D, norm.vmin)
                    im = ax.pcolormesh(ex, ez, Dm, cmap=DENSITY, norm=norm, shading="flat", zorder=1,
                                       rasterized=True)
                    xc, zc = (ex[:-1] + ex[1:]) / 2, (ez[:-1] + ez[1:]) / 2
                    lv = _hdr_levels(D)
                    if len(lv) == 2 and lv[0] < lv[1]:
                        ax.contour(xc, zc, D, levels=lv, colors=[INK], linewidths=[0.7, 1.1],
                                   linestyles=[(0, (1.5, 1.5)), "solid"], zorder=4)
                    i = np.clip(np.searchsorted(ex, p.pts[:, 0]) - 1, 0, D.shape[1] - 1)
                    j = np.clip(np.searchsorted(ez, p.pts[:, 1]) - 1, 0, D.shape[0] - 1)
                    lone = p.pts[D[j, i] < norm.vmin]                   # too sparse to colour: each one a dot
                    ax.plot(lone[:, 0], lone[:, 1], ls="none", marker="o", ms=1.8, mfc=RAMP[8], mec="none",
                            zorder=3)
                elif len(p.pts):
                    ax.plot(p.pts[:, 0], p.pts[:, 1], ls="none", marker="o", ms=2.6, mfc=RAMP[9], mec="white",
                            mew=0.4, zorder=3)
                draw_plan(ax, r_scn, r_plan)
                ax.set_title(p.title, fontsize=9.5, pad=13 if p.subtitle else 6)
                if p.subtitle:
                    ax.text(0.0, 1.015, p.subtitle, transform=ax.transAxes, fontsize=7, color=INK2, va="bottom")
                if c == 0:
                    ax.set_ylabel(f"{lab}\n\n{'xyz'[plan['v']]} (mm)" if lab else f"{'xyz'[plan['v']]} (mm)",
                                  fontsize=7.5)
                else:
                    ax.set_yticklabels([])
        fig.suptitle(title, x=0.01, y=0.98 if len(rows) == 1 else 1 - 0.18 / H, ha="left", fontsize=11,
                     fontweight="bold", color=INK)
        fig.subplots_adjust(left=0.07, right=0.9, top=top, bottom=bottom, wspace=0.12, hspace=0.32)
        if im is not None:
            cb_y = 0.25 if len(rows) == 1 else bottom + 0.13 * (top - bottom)
            cax = fig.add_axes([0.915, cb_y, 0.012, 0.55 if len(rows) == 1 else 0.71 * (top - bottom)])
            cb = fig.colorbar(im, cax=cax)
            cb.set_label("landed, % of the group fired per cm² (log)", color=INK2, fontsize=7.5)
            cb.outline.set_edgecolor(AXIS)
            cb.ax.tick_params(labelsize=7)
        o_h = plan["orifice_mm"][scn.up] - floor_level(scn) * 1000
        one_d = len({round(float(r[2]["orifice_d_mm"] or 0), 2) for r in rows}) == 1
        handles = [Line2D([], [], color=OBJ, lw=1.3, ls=(0, (5, 2.5)),
                          label="atomiser body, nozzle block and arm, seen from above"
                                + (f" (from {plan['objects_from_mm']:.0f} mm up)" if plan["objects_from_mm"] else "")),
                   Line2D([], [], color=OBJ, marker="o", mfc="none", ms=7, mew=1.5, ls="none",
                          label="exit orifice" + (f", {plan['orifice_d_mm']:.1f} mm" if plan["orifice_d_mm"] and one_d
                                                  else "")
                                + f", {o_h:.0f} mm up (the jet lands below it)"),
                   Line2D([], [], color=INK, lw=1.1, label="densest half of the deposit"),
                   Line2D([], [], color=INK, lw=0.7, ls=(0, (1.5, 1.5)), label="densest 90 %")]
        for p in plan["ports"][:1]:
            handles.insert(2, Line2D([], [], color=SERIES[6], lw=5, label=f"{p['d_mm']:.0f} mm port, "
                                                                          f"{p['height_mm']:.0f} mm up"))
        fig.legend(handles=handles, loc="lower left", ncol=3, bbox_to_anchor=(0.06, 0.0), fontsize=7)
        if caption:
            fig.text(0.07, cap_y, caption, fontsize=7.5, color=INK2, va="bottom")
        fig.savefig(out_png)
        plt.close(fig)


def band_panels(scn, plan, g: pd.DataFrame) -> list[Panel]:
    """One panel per size band: where that band's droplets landed on the floor (each size counted equally)."""
    h, v = plan["h"], plan["v"]
    cols = {0: "x_mm", 1: "y_mm", 2: "z_mm"}
    out = []
    for lo, hi in R.BANDS_UM:
        sel = g[(g.d_um > lo) & ((g.d_um <= hi) if hi is not None else True)]
        fl = sel[sel.fate == "floor"]
        share = len(fl) / len(sel) if len(sel) else 0.0
        out.append(Panel(R.band_label(lo, hi), fl[[cols[h], cols[v]]].to_numpy(float), max(len(sel), 1),
                         f"floor {100 * share:.0f} % of {len(sel):,} fired"))
    return out



# ---- where each size ends up -------------------------------------------------------------------------------------

def _size_axis(ax, sizes):
    ax.set_xscale("log")
    ax.set_xlim(sizes.min(), sizes.max())
    ticks = [t for t in (2, 5, 10, 20, 30, 50, 100, 200) if sizes.min() <= t <= sizes.max()]
    ax.set_xticks(ticks, [f"{t:g}" for t in ticks])
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())


def fates_by_size(scn, df: pd.DataFrame, out_png, title: str):
    """Small multiples, one per run (gusts by row, flow kept by column): the share of each size in each fate group,
    stacked, and the share still airborne at switch-off (a line)."""
    variants = [v for v in scn.variants() if v.key in set(df.variant.astype(str))]
    rows = [g for g in scn.gusts if any(v.gusts == g for v in variants)]
    cols = [a for a in scn.after_s if any(v.after_s == a for v in variants)]
    d = df.copy()
    d["group"] = R.fate_groups(scn, d)
    sizes = scn.sizes_um
    with plt.rc_context(STYLE):
        fig, axs = plt.subplots(len(rows), len(cols), figsize=(3.6 * len(cols) + 0.6, 2.7 * len(rows) + 1.3),
                                sharex=True, sharey=True, squeeze=False)
        for v in variants:
            ax = axs[rows.index(v.gusts), cols.index(v.after_s)]
            g = d[d.variant.astype(str) == v.key]
            share = (g.groupby(["d_um", "group"]).size().unstack(fill_value=0).reindex(index=sizes, columns=R.GROUPS,
                                                                                    fill_value=0))
            share = share.div(share.sum(axis=1).replace(0, np.nan), axis=0) * 100
            ax.stackplot(sizes, [share[k].to_numpy() for k in R.GROUPS],
                         colors=[GROUP_COLOURS[k] for k in R.GROUPS], edgecolor=SURFACE, linewidth=0.6, zorder=1)
            off = g.groupby("d_um").airborne_at_switch_off.mean().reindex(sizes) * 100
            ax.plot(sizes, off, color=INK, lw=1.2, ls=(0, (4, 2)), zorder=3)
            ax.axvline(30, color="white", lw=2.2, zorder=3)
            ax.axvline(30, color=INK, lw=0.8, ls=(0, (1, 1.5)), zorder=4)
            _size_axis(ax, sizes)
            ax.set_ylim(0, 100)
            ax.grid(False)
            ax.set_title(f"gusts {'on' if v.gusts else 'off'}, flow kept {v.after_s:g} s", fontsize=8.5)
            if v.gusts == rows[-1]:
                ax.set_xlabel("droplet size (µm)")
            if v.after_s == cols[0]:
                ax.set_ylabel("share of the size fired (%)")
        handles = [Rectangle((0, 0), 1, 1, color=GROUP_COLOURS[k], label=k) for k in R.GROUPS]
        handles.append(Line2D([], [], color=INK, lw=1.2, ls=(0, (4, 2)), label="still airborne at switch-off"))
        fig.legend(handles=handles, loc="lower center", ncol=5, bbox_to_anchor=(0.5, 0.0), fontsize=7.5)
        fig.suptitle(title, x=0.01, ha="left", fontsize=11, fontweight="bold")
        fig.text(0.01, 0.935, "Where each size finally was when the slides came out (the dotted line: 30 µm, the top of "
                              "the band). Each size counted equally.", fontsize=7.5, color=INK2)
        fig.subplots_adjust(left=0.07, right=0.98, top=0.86, bottom=0.17 if len(rows) > 1 else 0.3, wspace=0.08,
                            hspace=0.3)
        fig.savefig(out_png)
        plt.close(fig)


# ---- the checks ------------------------------------------------------------------------------------------------------

def check_column(col: pd.DataFrame, out_png):
    """The column check: OpenFOAM's settling speed against Phase 1's integrator (the same drag law and air: the
    tracking) and against Phase 1's own settling speed (Schiller-Naumann, Phase 1's air: the physics)."""
    with plt.rc_context(STYLE):
        fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
        for key, ls, lab in (("column_still_air", "-", "still air"),
                             ("column_cross_flow", (0, (4, 2)), "uniform cross-flow")):
            c = col[col.variant == key].sort_values("size_um")
            if c.empty:
                continue
            s = c.size_um.to_numpy()
            axs[0].plot(s, c.openfoam_vs_phase1_pct, color=SERIES[1], ls=ls, lw=1.3,
                        label=f"against Phase 1's own ({lab})")
            axs[0].plot(s, c.openfoam_vs_integrator_pct, color=SERIES[0], ls=ls, lw=1.3,
                        label=f"against Phase 1's integrator, OpenFOAM's drag ({lab})")
            axs[1].plot(s, c.path_gap_mm, color=SERIES[0], ls=ls, lw=1.3, label=lab)
        for ax in axs:
            _size_axis(ax, col.size_um.to_numpy())
            ax.set_xlabel("droplet size (µm)")
        axs[0].axhline(0, color=AXIS, lw=0.8)
        axs[0].axhspan(-1, 1, color=BAND, lw=0, zorder=0)
        axs[0].set_ylabel("settling speed: OpenFOAM's\nover the other, minus 1 (%)")
        axs[0].set_title("Settling speed (the grey band is ±1 %)")
        axs[0].legend(loc="upper left", fontsize=6.8)
        axs[1].set_ylabel("largest gap between the paths (mm)")
        axs[1].set_title("Path against Phase 1's integrator")
        axs[1].set_ylim(bottom=0)
        axs[1].legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(out_png)
        plt.close(fig)
