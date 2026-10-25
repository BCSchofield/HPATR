"""The figures (matplotlib, PNG). Colours: the reference data-viz palette, light mode (categorical slots in fixed
order; one blue ramp for magnitude and for ordered sizes; text in ink, never in a series colour).

Views: side = x-z (looking from the front wall), top = x-y, end = y-z (looking at the right wall from inside).
Everything is drawn in mm.
"""
from __future__ import annotations

import math

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap, LogNorm  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, Rectangle  # noqa: E402

from . import analysis  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID, AXIS, BAND = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", \
    "#f0efec"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
RAMP = ("#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf",
        "#1c5cab", "#184f95", "#104281", "#0d366b")          # blue 100 ... 700
ORDINAL = RAMP[3:]                                            # from step 250: every step clears 2:1 on the surface
ON, OFF = SERIES[0], MUTED
CAT_COLOURS = dict(zip(analysis.CATEGORIES, SERIES))
VIEWS = {"side": (0, 2), "top": (0, 1), "end": (1, 2)}
VIEW_TITLES = {"side": "Side (from the front)", "top": "Top", "end": "End (the right wall, from inside)"}
STYLE = {"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
         "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
         "font.size": 8.5, "text.color": INK, "axes.labelcolor": INK2, "axes.edgecolor": AXIS,
         "axes.linewidth": 0.6, "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlecolor": INK,
         "axes.titlelocation": "left", "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2,
         "ytick.labelcolor": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
         "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "legend.fontsize": 7.5,
         "lines.linewidth": 1.0, "savefig.dpi": 200, "savefig.bbox": "tight"}


def ordinal_colours(n: int) -> list:
    if n <= 1:
        return [ORDINAL[len(ORDINAL) // 2]]
    idx = np.round(np.linspace(0, len(ORDINAL) - 1, n)).astype(int)
    return [ORDINAL[i] for i in idx]


def _mm(v):
    return np.asarray(v, float) * 1000.0


def _caption(fig, text: str, y: float = -0.02):
    fig.text(0.01, y, text, ha="left", va="top", fontsize=7.5, color=INK2, wrap=True)


# ---- the chamber, drawn in any view ---------------------------------------------------------------------------

def draw_chamber(ax, scn, view: str, labels: bool = True, planes: bool = True):
    h, v = VIEWS[view]
    hidden = 3 - h - v
    L = _mm(scn.box)
    ax.plot([0, L[h], L[h], 0, 0], [0, 0, L[v], L[v], 0], color=INK2, lw=1.0, zorder=3)
    for port, kind in [(p, "inlet") for p in scn.inlets] + [(p, "outlet") for p in scn.outlets]:
        is_target = kind == "outlet" and port.name == scn.target_outlet
        col = SERIES[1] if kind == "inlet" else (SERIES[0] if is_target else MUTED)
        c = _mm(port.centre)
        k = int(np.flatnonzero(port.normal)[0])
        if k == hidden:                                         # seen face-on
            if port.shape == "round":
                ax.add_patch(Circle((c[h], c[v]), port.diameter * 500, fill=False, ec=col, lw=1.6, zorder=4))
            else:
                la = int(np.flatnonzero(port.long_axis)[0])
                wh = port.length * 1000 if la == h else port.width * 1000
                wv = port.length * 1000 if la == v else port.width * 1000
                ax.add_patch(Rectangle((c[h] - wh / 2, c[v] - wv / 2), wh, wv, fill=False, ec=col, lw=1.6,
                                           zorder=4))
        else:                                                   # an edge-on wall: a thick segment along it
            along = v if k == h else h
            if port.shape == "round":
                half = port.diameter * 500
            else:
                half = (port.length if int(np.flatnonzero(port.long_axis)[0]) == along else port.width) * 500
            seg = np.array([[c[h], c[v]], [c[h], c[v]]], float)
            seg[:, 0 if along == h else 1] += [-half, half]
            ax.plot(seg[:, 0], seg[:, 1], color=col, lw=4.5, solid_capstyle="butt", zorder=5)
        if kind == "inlet":
            d = port.direction
            if abs(d[h]) + abs(d[v]) > 1e-6:
                ax.annotate("", xy=(c[h] + 28 * d[h], c[v] + 28 * d[v]), xytext=(c[h], c[v]),
                            arrowprops=dict(arrowstyle="-|>", color=col, lw=1.2), zorder=6)
        if labels:
            tag = f"{port.name}{' (target)' if is_target else ''}"
            off = (5, -12) if kind == "inlet" else (5, 7)                   # face-on ports can share a spot
            ax.annotate(tag, (c[h], c[v]), xytext=off, textcoords="offset points", fontsize=7, color=INK2,
                        ha="right" if kind == "inlet" and c[h] > 0.6 * L[h] else "left", zorder=7)
    if scn.target_box is not None:
        lo, hi = _mm(scn.target_box[0]), _mm(scn.target_box[1])
        ax.add_patch(Rectangle((lo[h], lo[v]), hi[h] - lo[h], hi[v] - lo[v], fill=False, ec=SERIES[0], lw=1.4,
                                   ls="--", zorder=4))
        if labels:
            ax.annotate("target", (hi[h], hi[v]), xytext=(3, 3), textcoords="offset points", fontsize=7, color=INK2)
    sp = scn.spray
    n, s0 = _mm(sp.nozzle), _mm(sp.start_centre)
    ax.plot([n[h], s0[h]], [n[v], s0[v]], color=INK, lw=1.0, zorder=6)
    ax.plot(n[h], n[v], marker="s", ms=5, color=INK, zorder=7)
    e1 = np.cross(sp.axis, [1.0, 0, 0] if abs(sp.axis[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(sp.axis, e1)
    phi = np.linspace(0, 2 * np.pi, 73)
    ring = s0 + sp.start_radius * 1000 * (np.cos(phi)[:, None] * e1 + np.sin(phi)[:, None] * e2)
    ax.plot(ring[:, h], ring[:, v], color=SERIES[2], lw=1.4, zorder=6)
    tip = s0 + 45 * sp.axis
    if abs(sp.axis[h]) + abs(sp.axis[v]) > 1e-6:
        ax.annotate("", xy=(tip[h], tip[v]), xytext=(s0[h], s0[v]),
                    arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.0), zorder=6)
    if labels:
        ax.annotate("nozzle", (n[h], n[v]), xytext=(5, -10), textcoords="offset points", fontsize=7, color=INK2)
    if planes:
        for ax_i, at, name in scn.planes:
            if ax_i == h:
                ax.axvline(at * 1000, color=MUTED, lw=0.8, ls=(0, (4, 3)), zorder=2)
            elif ax_i == v:
                ax.axhline(at * 1000, color=MUTED, lw=0.8, ls=(0, (4, 3)), zorder=2)
                if labels:
                    ax.annotate(name, (0.2 * L[h], at * 1000), xytext=(0, -3), textcoords="offset points",
                                ha="center", va="top", fontsize=7, color=MUTED)
    ax.set_xlim(-0.04 * L[h], 1.04 * L[h])
    ax.set_ylim(-0.04 * L[v], 1.04 * L[v])
    ax.set_aspect("equal")
    ax.set_xlabel(f"{'xyz'[h]} (mm)")
    ax.set_ylabel(f"{'xyz'[v]} (mm)")
    ax.grid(False)


def layout(scn, flow, out_png, title: str = ""):
    """The scenario as the settings file describes it: check a moved part here before anything runs."""
    with plt.rc_context(STYLE):
        L = scn.box
        fig, axs = plt.subplots(1, 3, figsize=(13, 4.4), gridspec_kw={"width_ratios": [L[0], L[0], L[1]]})
        for ax, view in zip(axs, ("side", "top", "end")):
            draw_chamber(ax, scn, view)
            ax.set_title(VIEW_TITLES[view])
        fig.suptitle(title or f"Layout: {scn.name}{' | ' + scn.label if scn.label else ''}", x=0.01, ha="left",
                     fontsize=11, fontweight="bold", color=INK)
        handles = [Line2D([], [], color=SERIES[1], lw=4, label="inlet (arrow: its jet)"),
                   Line2D([], [], color=SERIES[0], lw=4, label="target outlet"),
                   Line2D([], [], color=MUTED, lw=4, label="other outlet"),
                   Line2D([], [], color=INK, marker="s", lw=1, label="nozzle and its axis"),
                   Line2D([], [], color=SERIES[2], lw=1.4, label="where the droplets start"),
                   Line2D([], [], color=MUTED, lw=0.8, ls=(0, (4, 3)), label="plane where crossings are recorded")]
        fig.legend(handles=handles, loc="upper right", ncol=3, bbox_to_anchor=(1.0, 1.02))
        _caption(fig, describe(scn, flow), y=0.0)
        fig.savefig(out_png)
        plt.close(fig)


def describe(scn, flow) -> str:
    sx = flow.notes["spray"]
    sp = scn.spray
    parts = [f"Spray: {sp.gas_flow_sccm:,.0f} sccm through {sp.orifice_mm:g} mm (Cd {sp.orifice_cd:g}): "
             f"{sx['momentum_N'] * 1000:.1f} mN, effective {sx['effective_speed_m_s']:.0f} m/s"
             f"{', choked' if sx.get('choked') else ''}. Droplets start {sp.standoff * 1000:g} mm along the axis, "
             f"{sp.start_radius * 1000:g} mm radius, {sp.cone_half_angle * 180 / math.pi:g} deg at the edge."]
    for p in scn.inlets:
        ex = flow.notes[p.name]
        size = f"{p.diameter * 1000:g} mm" if p.shape == "round" else f"{p.width * 1000:g} x {p.length * 1000:g} mm"
        parts.append(f"{p.name}: {p.flow_sccm:,.0f} sccm, {p.shape} {size}, "
                     f"{ex.get('exit_speed_m_s', 0):.2f} m/s, {ex['momentum_N'] * 1000:.2f} mN.")
    parts.append(f"Drift {flow.notes['drift_m_s'] * 1000:.1f} mm/s.")
    return "  ".join(parts)


# ---- the gas flow ------------------------------------------------------------------------------------------------

def _plane_grid(scn, view: str, at: float, n: int = 120):
    h, v = VIEWS[view]
    hidden = 3 - h - v
    gh = np.linspace(0, scn.box[h], n)
    gv = np.linspace(0, scn.box[v], int(n * scn.box[v] / scn.box[h]))
    H, V = np.meshgrid(gh, gv)
    P = np.zeros((H.size, 3))
    P[:, h], P[:, v], P[:, hidden] = H.ravel(), V.ravel(), at
    return H, V, P


def _section_at(scn, view):
    """Where each view cuts the chamber: through the nozzle for side and end, at the first inlet's height (or the
    first horizontal plane) for the top."""
    if view == "top":
        if scn.inlets:
            return float(scn.inlets[0].centre[2])
        z_planes = [at for ax, at, _n in scn.planes if ax == 2]
        return z_planes[0] if z_planes else scn.box[2] / 2
    return scn.spray.nozzle[1] if view == "side" else scn.spray.nozzle[0]


def gas_field(scn, flow, out_png):
    with plt.rc_context(STYLE):
        fig, axs = plt.subplots(1, 2, figsize=(11, 5.0), gridspec_kw={"width_ratios": [1, 1]})
        cmap = ListedColormap(RAMP)
        norm = LogNorm(vmin=1e-3, vmax=50)
        im = None
        for ax, view in zip(axs, ("side", "top")):
            h, v = VIEWS[view]
            at = _section_at(scn, view)
            H, V, P = _plane_grid(scn, view, at)
            U = flow.velocity(P)
            spd = np.linalg.norm(U, axis=1).reshape(H.shape)
            im = ax.pcolormesh(H * 1000, V * 1000, np.clip(spd, 1e-3, None), cmap=cmap, norm=norm, shading="auto",
                               zorder=0)
            uh, uv = U[:, h].reshape(H.shape), U[:, v].reshape(H.shape)
            ax.streamplot(H[0] * 1000, V[:, 0] * 1000, uh, uv, color=INK2, linewidth=0.45, density=1.1,
                          arrowsize=0.6, zorder=1)
            draw_chamber(ax, scn, view, labels=False)
            ax.set_title(f"{VIEW_TITLES[view]}, {'xyz'[3 - h - v]} = {at * 1000:.0f} mm")
        cb = fig.colorbar(im, ax=axs, shrink=0.8, pad=0.02)
        cb.set_label("gas speed (m/s, log scale)", color=INK2)
        cb.outline.set_edgecolor(AXIS)
        fig.suptitle(f"The idealised gas flow: {scn.name}{' | ' + scn.label if scn.label else ''}", x=0.01,
                     ha="left", fontsize=11, fontweight="bold")
        _caption(fig, "Textbook jets added together (spray + inlets) and the drift; lines follow the gas in the cut. "
                      "No recirculation and no walls: the jets pass through the floor and walls unchanged. "
                      + describe(scn, flow), y=0.02)
        fig.savefig(out_png)
        plt.close(fig)


# ---- the droplets --------------------------------------------------------------------------------------------

def _path_groups(drops, tr):
    groups = {}
    for i, pts in tr.paths.items():
        groups.setdefault(int(drops.size_index[i]), []).append(pts)
    return dict(sorted(groups.items()))


def paths(scn, flow, drops, tr, out_png, subtitle: str = ""):
    with plt.rc_context(STYLE):
        fig, axs = plt.subplots(1, 2, figsize=(12, 5.2), gridspec_kw={"width_ratios": [1, 1]})
        groups = _path_groups(drops, tr)
        cols = ordinal_colours(len(groups))
        for ax, view in zip(axs, ("side", "top")):
            h, v = VIEWS[view]
            at = _section_at(scn, view)
            H, V, P = _plane_grid(scn, view, at, n=22)
            U = flow.velocity(P)
            spd = np.linalg.norm(U[:, [h, v]], axis=1)
            scale = np.cbrt(np.clip(spd, 1e-4, None)) / np.clip(spd, 1e-4, None)
            ax.quiver(H.ravel() * 1000, V.ravel() * 1000, U[:, h] * scale, U[:, v] * scale, color=MUTED, alpha=0.55,
                      width=0.0025, headwidth=3.5, scale=55, zorder=1)
            for (k, pts_list), col in zip(groups.items(), cols):
                for pts in pts_list:
                    ax.plot(pts[:, h] * 1000, pts[:, v] * 1000, color=col, lw=0.7, alpha=0.9, zorder=2)
            draw_chamber(ax, scn, view, labels=False)
            ax.set_title(VIEW_TITLES[view])
        handles = [Line2D([], [], color=c, lw=2, label=f"{drops.sizes_um[k]:g} um") for k, c in zip(groups, cols)]
        fig.legend(handles=handles, loc="upper right", ncol=min(len(handles), 10), bbox_to_anchor=(1.0, 1.0),
                   title="droplet size", title_fontsize=7.5)
        fig.suptitle(f"Droplet paths by size: {scn.name}{' | ' + subtitle if subtitle else ''}", x=0.01, ha="left",
                     fontsize=11, fontweight="bold", y=1.04)
        _caption(fig, f"{scn.run['paths_per_size']} droplets per size shown (the same starts for every size). Grey "
                      "arrows: the gas in the side cut through the nozzle and the top cut at the inlet's height "
                      "(length ~ speed^(1/3), to show direction). Idealised flow: no recirculation; the jets pass "
                      "through the walls.", y=0.02)
        fig.savefig(out_png)
        plt.close(fig)


def fates_by_size(scn, ps, out_png, subtitle: str = ""):
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(8, 4.2))
        d = ps["size_um"].to_numpy()
        ax.axvspan(*scn.band_um, color=BAND, zorder=0, lw=0)
        ys = [100 * ps[c].to_numpy() for c in analysis.CATEGORIES]
        ax.stackplot(d, ys, colors=[CAT_COLOURS[c] for c in analysis.CATEGORIES], edgecolor=SURFACE, linewidth=1.0,
                     labels=[f"{c}{' (' + scn.target_label() + ')' if c == 'target' else ''}"
                             for c in analysis.CATEGORIES], zorder=1)
        for edge in scn.band_um:
            ax.axvline(edge, color=INK, lw=0.8, ls=(0, (3, 2)), zorder=3)
        ax.set_xlim(d.min(), d.max())
        ax.set_ylim(0, 100)
        ax.set_xlabel("droplet size (um)")
        ax.set_ylabel("where they end up (% of the droplets fired)")
        ax.grid(axis="x", visible=False)
        ax.text(np.mean(scn.band_um), 101.5, f"band {scn.band_um[0]:g}-{scn.band_um[1]:g} um", ha="center",
                fontsize=7.5, color=INK2)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=5)
        ax.set_title(f"Where each size ends up: {scn.name}{' | ' + subtitle if subtitle else ''}", pad=14)
        fig.savefig(out_png)
        plt.close(fig)


def delivery_vs_size(scn, ps_on, ps_off, out_png, n_weights=None, subtitle: str = ""):
    with plt.rc_context(STYLE):
        rows = 2 if n_weights is not None else 1
        fig, axs = plt.subplots(rows, 1, figsize=(8, 3.3 * rows + 0.6), sharex=True, squeeze=False)
        ax = axs[0, 0]
        d = ps_on["size_um"].to_numpy()
        ax.axvspan(*scn.band_um, color=BAND, zorder=0, lw=0)
        ax.plot(d, 100 * ps_on["target"], color=ON, lw=1.4, label="inlets on", zorder=3)
        if ps_off is not None:
            ax.plot(d, 100 * ps_off["target"], color=OFF, lw=1.2, ls=(0, (4, 2)), label="inlets off", zorder=2)
        ax.set_ylabel(f"reaching the target (%)\n{scn.target_label()}")
        ax.set_ylim(bottom=0)
        ax.legend(loc="upper right")
        ax.set_title(f"Delivery against size: {scn.name}{' | ' + subtitle if subtitle else ''}")
        if n_weights is not None:
            a2 = axs[1, 0]
            n = np.asarray(n_weights, float)
            vol = n * d ** 3
            a2.axvspan(*scn.band_um, color=BAND, zorder=0, lw=0)
            a2.plot(d, 100 * n / n.sum(), color=SERIES[2], lw=1.4, label="by number")
            a2.plot(d, 100 * vol / vol.sum(), color=SERIES[3], lw=1.4, label="by volume")
            a2.set_ylabel("measured spray (% per fired size)")
            a2.legend(loc="upper right")
            a2.set_title("The spray's measured size distribution (the weights for purity)")
        axs[-1, 0].set_xlabel("droplet size (um)")
        axs[-1, 0].set_xlim(d.min(), d.max())
        fig.tight_layout()
        fig.savefig(out_png)
        plt.close(fig)


def cross_axis(scn, plane_axis: int) -> int:
    """The in-plane axis the cross-stream pushes along (the first inlet's strongest component), else x."""
    cands = [a for a in range(3) if a != plane_axis]
    if scn.inlets:
        d = scn.inlets[0].direction
        return max(cands, key=lambda a: abs(d[a]))
    return cands[0]


def crossings(scn, ps_on, ps_off, out_png, subtitle: str = ""):
    """The headline (Ben, 2026-10-23): how far the jets carry or deflect each size, where it crosses each plane."""
    with plt.rc_context(STYLE):
        npl = len(scn.planes)
        fig, axs = plt.subplots(3, npl, figsize=(6.5 * npl, 7.6), sharex=True, squeeze=False,
                                gridspec_kw={"height_ratios": [1, 2, 2]})
        d = ps_on["size_um"].to_numpy()
        for j, (ax_i, at, name) in enumerate(scn.planes):
            a = cross_axis(scn, ax_i)
            al = "xyz"[a]
            mean, sd = f"{name}: {al} mean mm", f"{name}: {al} sd mm"
            for row in range(3):
                axs[row, j].axvspan(*scn.band_um, color=BAND, zorder=0, lw=0)
            for ps, col, lab, ls in ((ps_on, ON, "inlets on", "-"), (ps_off, OFF, "inlets off", (0, (4, 2)))):
                if ps is None:
                    continue
                axs[0, j].plot(d, 100 * ps[f"{name}: crossed"], color=col, ls=ls, lw=1.3, label=lab)
                m, s = ps[mean].to_numpy(), ps[sd].to_numpy()
                if ps is ps_on:
                    axs[1, j].fill_between(d, m - s, m + s, color=col, alpha=0.13, lw=0, label=f"{lab}: 1 SD")
                else:
                    for edge in (m - s, m + s):
                        axs[1, j].plot(d, edge, color=col, ls=(0, (1, 2)), lw=0.8)
                axs[1, j].plot(d, m, color=col, ls=ls, lw=1.3, label=f"{lab}: mean")
            axs[0, j].set_ylabel("crossing (%)")
            axs[0, j].set_ylim(0, 105)
            axs[0, j].legend(loc="lower right")
            axs[0, j].set_title(f"Plane: {name} ({'xyz'[ax_i]} = {at * 1000:g} mm)")
            axs[1, j].set_ylabel(f"{al} where it crosses (mm)")
            axs[1, j].legend(loc="best")
            if ps_off is not None:
                shift = (ps_on[mean] - ps_off[mean]).to_numpy()
                axs[2, j].axhline(0, color=AXIS, lw=0.8)
                axs[2, j].plot(d, shift, color=ON, lw=1.4)
                axs[2, j].set_ylabel(f"shift by the inlets along {al} (mm)")
            axs[2, j].set_xlabel("droplet size (um)")
            axs[2, j].set_xlim(d.min(), d.max())
        fig.suptitle(f"Where each size crosses the planes: {scn.name}{' | ' + subtitle if subtitle else ''}",
                     x=0.01, ha="left", fontsize=11, fontweight="bold")
        fig.tight_layout()
        fig.savefig(out_png)
        plt.close(fig)


def speed_vs_distance(scn, drops, tr, out_png, subtitle: str = ""):
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(8, 4.4))
        groups = _path_groups(drops, tr)
        cols = ordinal_colours(len(groups))
        for (k, pts_list), col in zip(groups.items(), cols):
            grid, curves = None, []
            for pts in pts_list:
                dist = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(pts[:, :3], axis=0), axis=1))] * 1000
                spd = np.clip(pts[:, 3], 1e-3, None)
                ax.plot(dist, spd, color=col, lw=0.4, alpha=0.35)
                grid = np.linspace(0, dist.max(), 200) if grid is None or dist.max() < grid[-1] else grid
                curves.append((dist, spd))
            med = np.median([np.interp(grid, dd, ss) for dd, ss in curves], axis=0)
            ax.plot(grid, med, color=col, lw=1.8, label=f"{drops.sizes_um[k]:g} um")
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _p: f"{y:g}"))
        ax.yaxis.set_minor_formatter(matplotlib.ticker.FuncFormatter(
            lambda y, _p: f"{y:g}" if f"{y:g}"[0] in "25" else ""))
        ax.set_xlabel("distance travelled from the start (mm)")
        ax.set_ylabel("droplet speed (m/s)")
        ax.legend(title="droplet size (median; faint: each droplet)", title_fontsize=7.5, ncol=2, loc="upper right")
        ax.set_title(f"Speed against distance: {scn.name}{' | ' + subtitle if subtitle else ''}")
        fig.savefig(out_png)
        plt.close(fig)


# ---- sweeps --------------------------------------------------------------------------------------------------

def sweep_trends(table, axes, out_png, band):
    """One swept setting: lines against it. Two: a heat map per number. More: none (see sweep.csv)."""
    if len(axes) not in (1, 2):
        return False
    metrics = [("delivery_number", "band delivered, by number (%)"), ("purity_number", "band purity, by number (%)"),
               ("band_push_mm", "band pushed along the cross-stream (mm)")]
    with plt.rc_context(STYLE):
        if len(axes) == 1:
            name = axes[0][0]
            x = table[name].to_numpy()
            ticks = None
            if not np.issubdtype(np.asarray(axes[0][1]).dtype, np.number):     # labelled values: evenly spaced
                ticks, x = list(x), np.arange(len(x), dtype=float)
            fig, axs = plt.subplots(1, 3, figsize=(13, 3.8))
            for ax, (key, lab) in zip(axs[:2], metrics[:2]):
                kind = key.split("_")[0]
                for suff, col, nm in (("number", SERIES[0], "by number"), ("volume", SERIES[1], "by volume")):
                    col_key = f"{kind}_{suff}"
                    if col_key in table and table[col_key].notna().any():
                        ax.plot(x, 100 * table[col_key], color=col, marker="o", ms=5, lw=1.4, label=nm)
                    if f"{col_key} off" in table and table[f"{col_key} off"].notna().any():
                        ax.plot(x, 100 * table[f"{col_key} off"], color=col, marker="o", ms=4, lw=1.0, alpha=0.5,
                                ls=(0, (4, 2)), label=f"{nm}, inlets off")
                ax.set_ylabel(f"band {kind} (%)")
                ax.set_xlabel(name)
                if ax.lines:
                    ax.legend(loc="best")
                else:
                    ax.text(0.5, 0.5, "needs a measured\nsize distribution", ha="center", va="center",
                            transform=ax.transAxes, color=MUTED)
            axs[2].axhline(0, color=AXIS, lw=0.8)
            axs[2].plot(x, table["band_push_mm"], color=SERIES[0], marker="o", ms=5, lw=1.4)
            axs[2].set_ylabel(metrics[2][1])
            axs[2].set_xlabel(name)
            xn = np.asarray(x, float)
            pad = 0.06 * (xn.max() - xn.min()) if xn.max() > xn.min() else 1.0
            for ax, t in zip(axs, ("Delivery", "Purity", "Deflection")):
                ax.set_title(f"{t}, band {band[0]:g}-{band[1]:g} um")
                ax.set_xlim(xn.min() - pad, xn.max() + pad)            # every panel spans the whole sweep
                if ticks is not None:
                    ax.set_xticks(xn, ticks, rotation=20, ha="right")
        else:
            (n1, v1), (n2, v2) = axes
            fig, axs = plt.subplots(1, 3, figsize=(14, 4.2))
            cmap = ListedColormap(RAMP)
            for ax, (key, lab) in zip(axs, metrics):
                if key not in table or table[key].isna().all():
                    ax.text(0.5, 0.5, "needs a measured\nsize distribution", ha="center", va="center",
                            transform=ax.transAxes, color=MUTED)
                    ax.set_axis_off()
                    continue
                M = np.full((len(v2), len(v1)), np.nan)
                for _i, r in table.iterrows():
                    M[[str(v) for v in v2].index(str(r[n2])), [str(v) for v in v1].index(str(r[n1]))] = \
                        r[key] * (100 if key != "band_push_mm" else 1)
                top = 100.0 if key != "band_push_mm" else max(float(np.nanmax(np.abs(M))), 1e-9)
                bottom = 0.0 if key != "band_push_mm" else min(0.0, float(np.nanmin(M)))
                im = ax.imshow(M, origin="lower", cmap=cmap, aspect="auto", vmin=bottom, vmax=top)   # from 0, so
                # near-equal values look near-equal
                for (i, j), val in np.ndenumerate(M):
                    if np.isfinite(val):
                        ax.text(j, i, f"{val:.2g}" if abs(val) < 10 else f"{val:.0f}", ha="center", va="center",
                                fontsize=7.5, color="white" if im.norm(val) > 0.55 else INK)
                ax.set_xticks(range(len(v1)), [str(v) for v in v1], rotation=20 if any(
                    len(str(v)) > 6 for v in v1) else 0, ha="right" if any(len(str(v)) > 6 for v in v1) else "center")
                ax.set_yticks(range(len(v2)), [str(v) for v in v2])
                ax.set_xlabel(n1)
                ax.set_ylabel(n2)
                ax.set_title(lab)
                ax.grid(False)
        fig.tight_layout()
        fig.savefig(out_png)
        plt.close(fig)
    return True


def sweep_delivery_curves(results, out_png, band, title: str):
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(8.5, 4.4))
        ax.axvspan(*band, color=BAND, zorder=0, lw=0)
        cols = ordinal_colours(len(results))
        for (label, ps), col in zip(results, cols):
            ax.plot(ps["size_um"], 100 * ps["target"], color=col, lw=1.3, label=label)
        ax.set_xlabel("droplet size (um)")
        ax.set_ylabel("reaching the target (%)")
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=6.5, loc="upper right")
        ax.set_title(title)
        fig.savefig(out_png)
        plt.close(fig)
