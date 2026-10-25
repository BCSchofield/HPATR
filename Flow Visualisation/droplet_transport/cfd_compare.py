"""Phase 3a Part D: compare finished droplet runs, from their output folders alone: a sweep's entries (cfd_sweep), or
any run folders (run_droplets.py --compare). See PLAN.md, Phase 3a, Part D.

    comparison.md      what was compared; the air; the 0-30 µm band; the floor deposit by band against the reference,
                       with the noise from the droplet count; where each size ends up; each one's checks
    comparison.csv     per run, variant and band: floor share, centre, spread, the deposit moved, and their noise
    figures/           compare_floor.png, compare_fates.png

Agreement, per band and measure, against the reference: within the droplet-count noise (NOISE_X sd) "the same";
beyond it but within the tolerance "close"; else "differs". The noise comes from resampling each run's droplets
(the bootstrap).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from . import cfd_checks, cfd_droplets, cfd_plots
from . import cfd_results as R
from .cfd_droplets import Variant
from .cfd_report import BAND, _p
from .plots import BAND as BAND_FILL, INK, INK2, SERIES, STYLE

import matplotlib.pyplot as plt  # noqa: E402  (after .plots, which sets the Agg backend)
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

GRID_MM = 10.0                       # the air is compared on a grid this fine
SQUARE_MM = 20.0                     # "moved": the share of a deposit that lands in a different square this size
RESAMPLES = 40                       # bootstrap resamples of each run, for the noise from the droplet count
NOISE_X = 3.0                        # a difference within this many standard deviations of its noise: "the same"
MOVED_X = 2.0                        # "moved" within this many times what the droplet count alone gives: "the same"
                                     #   (each comparison makes ~20 judgements a run: 2 sd would flag one by chance)
TOLERANCE = {"floor_pp": 5.0, "centre_mm": 10.0, "spread_mm": 10.0, "moved_pct": 10.0}
VERDICTS = ("the same", "close", "differs")
OTHER = "everything else"


# ---- the air, on a common grid ---------------------------------------------------------------------------------------

def read_internal(path: Path) -> np.ndarray:
    """A volume field's internalField (ascii, nonuniform): (n, 3) for a vector, (n,) for a scalar."""
    text = Path(path).read_text(errors="replace")
    if re.search(r"^\s*format\s+binary\s*;", text[:2000], re.M):
        raise ValueError(f"{path}: binary; the comparison reads ascii fields (CfdOF writes ascii)")
    i = text.index("internalField")
    m = re.match(r"internalField\s+nonuniform\s+List<(\w+)>\s*(\d+)\s*\(", text[i:i + 300])
    if not m:
        raise ValueError(f"{path}: internalField is not a nonuniform list")
    n, start = int(m.group(2)), i + m.end()
    body = text[start:text.index("\n)", start)].replace("(", " ").replace(")", " ")
    vals = np.array(body.split(), float)
    width = 3 if m.group(1) == "vector" else 1
    if vals.size != n * width:
        raise ValueError(f"{path}: {vals.size} values, header says {n} x {width}")
    return vals.reshape(n, 3) if width == 3 else vals


def save_flow_grid(scn, flow_dir: Path, out: Path, foam) -> dict:
    """The flow's air velocity and k on a GRID_MM grid over the chamber, each point the nearest cell's value (points
    more than a grid step from every cell centre, inside the objects, left out): what compares flows on different
    meshes. OpenFOAM writes the cell centres in a throwaway case beside the flow copy (which stays untouched)."""
    it = str(scn.iteration)
    flow_dir = Path(flow_dir)
    d = flow_dir / it
    tmp = flow_dir.with_name(f"{flow_dir.name}.centres-{os.getpid()}-{threading.get_ident()}")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / it).mkdir(parents=True)
    for sub in ("constant", "system"):
        (tmp / sub).symlink_to(flow_dir / sub, target_is_directory=True)
    try:
        foam(scn, tmp, f"postProcess -func writeCellCentres -time {it}", "log.writeCellCentres")
        C = read_internal(tmp / it / "C")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    U = read_internal(d / "U")
    k = read_internal(d / "k") if (d / "k").exists() else np.full(len(C), np.nan)
    axes = [np.arange(lo + GRID_MM / 2, hi - GRID_MM / 2 + 1e-9, GRID_MM) for lo, hi in scn.inside * 1000]
    P = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3) / 1000
    dist, idx = cKDTree(C).query(P)
    keep = dist <= GRID_MM / 1000
    Ug = np.where(keep[:, None], U[idx], np.nan).astype(np.float32)
    kg = np.where(keep, k[idx], np.nan).astype(np.float32)
    np.savez_compressed(out, points_mm=(P * 1000).astype(np.float32), U=Ug, k=kg, cells=len(C), step_mm=GRID_MM)
    return {"cells": int(len(C)), "mean_speed_m_s": float(np.nanmean(np.linalg.norm(Ug, axis=1)))}


def air_rows(runs: list, ref: int) -> list[dict]:
    """Each flow's mean air speed and turbulence (sqrt(2k/3)) over the chamber, and how far its air is from the
    reference's: the mean |U - U_ref| as a share of the reference's mean speed."""
    grids = [np.load(r.folder / "flow_grid.npz") if (r.folder / "flow_grid.npz").exists() else None for r in runs]
    g0 = grids[ref]
    rows = []
    for r, g in zip(runs, grids):
        row = {"label": r.label, "cells": r.meta.get("flow_cells")}
        if g is None:
            rows.append(row)
            continue
        sp = np.linalg.norm(g["U"], axis=1)
        row.update(mean_speed_m_s=float(np.nanmean(sp)), turbulence_m_s=float(np.nanmean(np.sqrt(2 * g["k"] / 3))),
                   still_share=float(np.nanmean(sp < 0.1)))
        if g0 is not None and g["U"].shape == g0["U"].shape and np.allclose(g["points_mm"], g0["points_mm"]):
            ok = np.isfinite(g["U"]).all(axis=1) & np.isfinite(g0["U"]).all(axis=1)
            dU = np.linalg.norm(g["U"][ok] - g0["U"][ok], axis=1)
            row["vs_ref_pct"] = float(100 * dU.mean() / np.linalg.norm(g0["U"][ok], axis=1).mean())
            row["points"] = int(ok.sum())
        rows.append(row)
    return rows


# ---- the runs ------------------------------------------------------------------------------------------------------

@dataclass
class Run:
    label: str
    folder: Path
    meta: dict
    scn: object
    df: pd.DataFrame
    plan: dict
    checks: dict


def load_run(folder: Path, label: str | None = None) -> Run:
    folder = Path(folder)
    meta = json.loads((folder / "run.json").read_text())
    plain, basis = cfd_droplets.read_yaml(folder / "settings.yaml")
    plain.setdefault("spray", {}).setdefault("droplets", {})["per_size"] = int(meta["per_size"])
    scn = cfd_droplets.build(plain, basis, Path(meta["settings"]))
    df = pd.read_csv(folder / "droplets.csv")
    df["variant"] = df["variant"].astype(str)
    ck = json.loads((folder / "checks.json").read_text()) if (folder / "checks.json").exists() else {}
    label = label or meta.get("label") or f"{Path(meta['flow_case']).parent.name} it {meta['iteration']}"
    return Run(label, folder, meta, scn, df, cfd_plots.load_plan(folder / "plan_view.npz"), ck)


def _band(df: pd.DataFrame, lo, hi) -> pd.DataFrame:
    return df[(df.d_um > lo) & ((df.d_um <= hi) if hi is not None else True)]


def _edges(plan) -> tuple[np.ndarray, np.ndarray]:
    x0, x1, z0, z1 = plan["extent"]
    return (np.append(np.arange(x0, x1, SQUARE_MM), x1), np.append(np.arange(z0, z1, SQUARE_MM), z1))


def measures(scn, sel: pd.DataFrame, edges) -> dict:
    """A group's floor share, and where on the floor it landed: the centre, the median distance from the jet's
    impact point (its spread), and the share in each SQUARE_MM square (needs MIN_FOR_MAP on the floor)."""
    ch, cv, h, v = cfd_checks._plan_cols(scn)
    fl = sel[sel.fate == "floor"]
    out = {"n": len(sel), "n_floor": len(fl), "floor": len(fl) / len(sel) if len(sel) else np.nan,
           "cx": np.nan, "cz": np.nan, "r50": np.nan, "hist": None}
    if len(fl) >= cfd_plots.MIN_FOR_MAP:
        ip = cfd_checks.impact_mm(scn)
        x, z = fl[ch].to_numpy(float), fl[cv].to_numpy(float)
        H, _, _ = np.histogram2d(x, z, bins=edges)
        out.update(cx=float(x.mean()), cz=float(z.mean()), r50=float(np.median(np.hypot(x - ip[h], z - ip[v]))),
                   hist=H / H.sum())
    return out


def moved(a, b) -> float:
    """The share of one deposit that lands in a different square from the other's (half the summed difference)."""
    return np.nan if a is None or b is None else float(0.5 * np.abs(a - b).sum())


def noise(scn, sel: pd.DataFrame, edges, rng) -> dict:
    """The noise from the droplet count, by the bootstrap (RESAMPLES resamples of the group's droplets, with
    replacement, each as many as the group): each measure's standard deviation, and the share moved between two
    resamples (mean), i.e. what two runs of the same flow would differ by from the droplet count alone."""
    keys = ("floor", "cx", "cz", "r50")
    n = len(sel)
    if n < 2:
        return {**{k: np.nan for k in keys}, "moved_pair": np.nan}
    ms = [measures(scn, sel.iloc[rng.integers(0, n, n)], edges) for _ in range(RESAMPLES)]
    out = {}
    for k in keys:
        v = np.array([m[k] for m in ms], float)
        out[k] = float(np.nanstd(v, ddof=1)) if np.isfinite(v).sum() >= RESAMPLES // 2 else np.nan
    tv = [moved(a["hist"], b["hist"]) for a, b in zip(ms[::2], ms[1::2])]
    out["moved_pair"] = float(np.nanmean(tv)) if np.isfinite(tv).sum() >= RESAMPLES // 4 else np.nan
    return out


def _verdict(diff, noise_, tol, x=NOISE_X) -> int | None:
    """0 the same, 1 close, 2 differs; None when it cannot be judged (too few on the floor to know the noise)."""
    if diff is None or not np.isfinite(diff) or noise_ is None or not np.isfinite(noise_):
        return None
    if abs(diff) <= x * noise_:
        return 0
    return 1 if abs(diff) <= tol else 2


def agreement(runs: list, ref: int, variants: list[str], tol: dict) -> pd.DataFrame:
    """Per run, variant and band, against the reference run: the measures, their differences, the noise, the verdict."""
    rng = np.random.default_rng(0)
    rows = []
    for var in variants:
        for lo, hi in R.BANDS_UM:
            stats = []
            for r in runs:
                sel = _band(r.df[r.df.variant == var], lo, hi)
                e = _edges(r.plan)
                stats.append((measures(r.scn, sel, e), noise(r.scn, sel, e, rng)))
            (m0, n0) = stats[ref]
            for i, (r, (m, nz)) in enumerate(zip(runs, stats)):
                row = {"label": r.label, "variant": var, "band": R.band_label(lo, hi), "fired": m["n"],
                       "on_floor": m["n_floor"], "floor_pct": 100 * m["floor"], "centre_x_mm": m["cx"],
                       "centre_z_mm": m["cz"], "spread_mm": m["r50"], "reference": i == ref}
                if i != ref:
                    shift = float(np.hypot(m["cx"] - m0["cx"], m["cz"] - m0["cz"]))
                    row.update(
                        d_floor_pp=100 * (m["floor"] - m0["floor"]),
                        noise_floor_pp=100 * float(np.hypot(nz["floor"], n0["floor"])),
                        d_centre_mm=shift,
                        noise_centre_mm=float(np.sqrt(nz["cx"] ** 2 + n0["cx"] ** 2 + nz["cz"] ** 2 + n0["cz"] ** 2)),
                        d_spread_mm=m["r50"] - m0["r50"], noise_spread_mm=float(np.hypot(nz["r50"], n0["r50"])),
                        moved_pct=100 * moved(m["hist"], m0["hist"]),
                        noise_moved_pct=100 * float(np.hypot(nz["moved_pair"], n0["moved_pair"]) / np.sqrt(2)))
                    vs = {"floor share": _verdict(row["d_floor_pp"], row["noise_floor_pp"], tol["floor_pp"]),
                          "centre": _verdict(row["d_centre_mm"], row["noise_centre_mm"], tol["centre_mm"]),
                          "spread": _verdict(row["d_spread_mm"], row["noise_spread_mm"], tol["spread_mm"]),
                          "moved": _verdict(row["moved_pct"], row["noise_moved_pct"], tol["moved_pct"], MOVED_X)}
                    got = [v for v in vs.values() if v is not None]
                    worst = max(got) if got else None
                    row["verdict"] = VERDICTS[worst] if worst is not None else "too few on the floor"
                    row["why"] = ", ".join(f"{k} {VERDICTS[v]}" for k, v in vs.items() if v)
                rows.append(row)
    return pd.DataFrame(rows)


# ---- the band weighted by the measured spray -------------------------------------------------------------------------

def band_rows(runs: list, variants: list[str]) -> pd.DataFrame:
    """Per run and variant: where the 0-30 µm band went, weighted by the measured spray (by number), and its share
    of the floor's deposit."""
    lo, hi = BAND
    rows = []
    for r in runs:
        w, _info = R.size_weights(r.scn)
        if w is None:
            continue
        d = r.df[r.df.variant.isin(variants)]
        t = R.weighted_groups(r.scn, d, w, lo, hi).set_index("variant")
        pur = R.floor_purity(r.scn, d, w, lo, hi)
        for var in variants:
            if var not in t.index:
                continue
            row = {"label": r.label, "variant": var, **t.loc[var].to_dict(), "purity": pur.get(var, np.nan)}
            row["floor"] = row.get(R.FLOOR_MOVING, 0) + row.get(R.FLOOR_STILL, 0)
            rows.append(row)
    return pd.DataFrame(rows)


def brackets(bt: pd.DataFrame, runs: list, ref: int) -> dict:
    """The band's floor share, % points: its range across the runs (worst over the variants), and in the reference
    the ranges we already carry as brackets (gusts on against off; the flow kept 0 to 10 s)."""
    if bt.empty:
        return {}
    across = bt.groupby("variant").floor.agg(lambda s: s.max() - s.min())
    r0 = bt[bt.label == runs[ref].label].set_index("variant").floor
    scn = runs[ref].scn
    gusts = [abs(r0.get(Variant(True, a).key, np.nan) - r0.get(Variant(False, a).key, np.nan)) for a in scn.after_s]
    kept = [r0.reindex([Variant(g, a).key for a in scn.after_s]).agg(lambda s: s.max() - s.min()) for g in scn.gusts]
    return {"across_pp": 100 * float(across.max()), "across_worst_run": str(across.idxmax()),
            "gusts_pp": 100 * float(np.nanmax(gusts)) if np.isfinite(gusts).any() else np.nan,
            "kept_pp": 100 * float(np.nanmax(kept)) if np.isfinite(kept).any() else np.nan}


# ---- figures -------------------------------------------------------------------------------------------------------

def floor_figure(runs: list, show: str, out_png: Path, title: str):
    sizes = {round(float(r.plan["orifice_d_mm"] or 0), 2) for r in runs}
    rows = []
    for r in runs:
        lab = r.label + (f"\n{r.plan['orifice_d_mm']:.2f} mm orifice" if len(sizes) > 1 and r.plan["orifice_d_mm"]
                         else "")
        rows.append((lab, cfd_plots.band_panels(r.scn, r.plan, r.df[r.df.variant == show]), r.plan, r.scn))
    s0 = runs[0].scn
    cfd_plots.floor_maps(s0, runs[0].plan, rows, out_png, title,
                         f"{_label(s0, show)}. One row per flow; each size counted equally ({s0.per_size} of each). "
                         "Seen from above.")


def fates_figure(runs: list, ref: int, show: str, out_png: Path, title: str):
    """Small multiples by fate group: the share of each size, one line per run; the grey band is the reference's
    noise from the droplet count (2 standard deviations)."""
    panels = [R.FLOOR_MOVING, R.FLOOR_STILL, R.SIDES, R.PORT, OTHER, "airborne at switch-off"]
    sizes = runs[ref].scn.sizes_um
    with plt.rc_context(STYLE):
        fig, axs = plt.subplots(2, 3, figsize=(11.5, 6.6), sharex=True)
        for i, r in enumerate(runs):
            g = r.df[r.df.variant == show].copy()
            g["group"] = R.fate_groups(r.scn, g)
            g.loc[~g.group.isin(panels), "group"] = OTHER
            share = (g.groupby(["d_um", "group"]).size().unstack(fill_value=0).reindex(index=sizes, fill_value=0))
            n = share.sum(axis=1).replace(0, np.nan)
            share = share.div(n, axis=0)
            share["airborne at switch-off"] = g.groupby("d_um").airborne_at_switch_off.mean().reindex(sizes)
            for ax, k in zip(axs.flat, panels):
                y = share[k].to_numpy() if k in share else np.zeros(sizes.size)
                if i == ref:
                    sd = np.sqrt(y * (1 - y) / n.to_numpy())
                    ax.fill_between(sizes, 100 * (y - 2 * sd), 100 * (y + 2 * sd), color=BAND_FILL, lw=0, zorder=0)
                ax.plot(sizes, 100 * y, color=SERIES[i % len(SERIES)], lw=1.6 if i == ref else 1.2, zorder=2 + i)
        for ax, k in zip(axs.flat, panels):
            ax.axvline(30, color=INK, lw=0.8, ls=(0, (1, 1.5)), zorder=1)
            cfd_plots._size_axis(ax, sizes)
            ax.set_ylim(bottom=0)
            ax.set_title(k if k != OTHER else "objects, lid, back up the hole, airborne", fontsize=9)
        for ax in axs[1]:
            ax.set_xlabel("droplet size (µm)")
        for ax in axs[:, 0]:
            ax.set_ylabel("share of the size fired (%)")
        handles = [Line2D([], [], color=SERIES[i % len(SERIES)], lw=1.6, label=r.label + (" (reference)" if i == ref
                                                                                           else ""))
                   for i, r in enumerate(runs)]
        handles.append(Rectangle((0, 0), 1, 1, color=BAND_FILL, label="the reference's droplet-count noise (2 sd)"))
        fig.legend(handles=handles, loc="lower center", ncol=min(len(handles), 4), fontsize=7.5)
        fig.suptitle(title, x=0.01, ha="left", fontsize=11, fontweight="bold")
        fig.text(0.01, 0.935, f"{_label(runs[ref].scn, show)}. Where each size was when the slides came out; the "
                              "last panel is a moment (switch-off). Dotted: 30 µm.", fontsize=7.5, color=INK2)
        fig.subplots_adjust(left=0.07, right=0.98, top=0.87, bottom=0.17, wspace=0.18, hspace=0.32)
        fig.savefig(out_png)
        plt.close(fig)


# ---- comparison.md ---------------------------------------------------------------------------------------------------

def _label(scn, key: str) -> str:
    return next((v.label for v in scn.variants() if v.key == key), key)


def _f(x, fmt="{:.1f}") -> str:
    return "–" if x is None or (isinstance(x, float) and not np.isfinite(x)) else fmt.format(x)


def _pm(d, nz, fmt="{:+.1f}", x=NOISE_X) -> str:
    return "–" if d is None or not np.isfinite(d) else f"{fmt.format(d)} (± {_f(x * nz)})"


def compare(folders: list, out: Path, labels: list[str] | None = None, show: str | None = None,
            against: str | None = None, tolerance: dict | None = None, title: str | None = None,
            log=print) -> Path:
    runs = [load_run(f, labels[i] if labels else None) for i, f in enumerate(folders)]
    if len(runs) < 2:
        raise ValueError("compare: at least two run folders")
    if len({r.label for r in runs}) < len(runs):
        raise ValueError(f"compare: the labels must differ: {[r.label for r in runs]}")
    tol = {**TOLERANCE, **(tolerance or {})}
    ref = next((i for i, r in enumerate(runs) if r.label == against), 0) if against else 0
    common = [v.key for v in runs[ref].scn.variants() if all(v.key in set(r.df.variant) for r in runs)]
    if not common:
        raise ValueError("compare: the runs have no variant (gusts, flow kept) in common")
    s0 = runs[ref].scn
    if show is None or show not in common:
        mid = Variant(True if True in s0.gusts else s0.gusts[0], s0.after_s[len(s0.after_s) // 2]).key
        show = mid if mid in common else common[0]
    out = Path(out)
    figs = out / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    title = title or "The same droplets through each flow"
    ag = agreement(runs, ref, common, tol)
    ag.to_csv(out / "comparison.csv", index=False, float_format="%.4g")
    bt = band_rows(runs, common)
    floor_figure(runs, show, figs / "compare_floor.png", "Where each size band lands on the floor, flow by flow")
    fates_figure(runs, ref, show, figs / "compare_fates.png", "Where each size ends up, flow by flow")
    air = air_rows(runs, ref)
    text = report(runs, ref, show, common, tol, ag, bt, air, title)
    (out / "comparison.md").write_text(text, encoding="utf-8")
    log(f"comparison: {out / 'comparison.md'}")
    return out / "comparison.md"


def report(runs, ref, show, common, tol, ag, bt, air, title) -> str:
    r0 = runs[ref]
    s0 = r0.scn
    L = [f"# {title}", "", f"Made {datetime.now():%Y-%m-%d %H:%M}. The reference is **{r0.label}**; the maps and the "
         f"size curves show **{_label(s0, show)}**. Each run's own report.md has everything else.", ""]
    L += ["## What was compared", "", "| run | flow case | iteration | cells | orifice | droplets | folder |",
          "|---|---|---|---|---|---|---|"]
    for r in runs:
        L.append(f"| {r.label}{' (reference)' if r is r0 else ''} | `{r.meta['flow_case']}` | {r.meta['iteration']} | "
                 f"{_f(r.meta.get('flow_cells'), '{:,}')} | {_f(r.plan.get('orifice_d_mm'), '{:.2f} mm')} | "
                 f"{r.scn.per_size} of each of {r.scn.sizes_um.size} sizes | [{r.folder.name}]"
                 f"({r.folder.name}/report.md) |")
    L.append("")

    sv = ag[(ag.variant == show) & ~ag.reference]
    L += ["## Verdict", ""]
    for r in runs:
        if r is r0:
            continue
        g = sv[sv.label == r.label]
        worst = max((VERDICTS.index(v) for v in g.verdict if v in VERDICTS), default=None)
        diff = [f"{b} ({w})" for b, v, w in zip(g.band, g.verdict, g.why) if v in VERDICTS[1:]]
        L.append(f"- **{r.label}** against {r0.label}: "
                 + ("every band's floor deposit **the same** within the droplet-count noise." if worst == 0 else
                    f"**{VERDICTS[worst]}** at worst: " + "; ".join(diff) + "." if worst is not None else
                    "too few on the floor to judge."))
    bk = brackets(bt, runs, ref)
    if bk:
        L += ["", f"The 0-{BAND[1]:g} µm band's floor share (weighted by the measured spray) varies by up to "
                  f"**{bk['across_pp']:.1f} points** across these flows"
                  + (f" (worst in {_label(s0, bk['across_worst_run'])})" if bk["across_pp"] > 0 else "") + "; "
                  f"in {r0.label} the brackets we already carry span {bk['gusts_pp']:.1f} points (gusts on against "
                  f"off) and {bk['kept_pp']:.1f} points (the flow kept {s0.after_s[0]:g} to {s0.after_s[-1]:g} s)."]
    L += ["", "![the floor deposit by band, flow by flow](figures/compare_floor.png)", ""]

    L += ["## The air", "", "Each flow sampled on a {:g} mm grid over the chamber (the nearest cell's value), so flows on "
          "different meshes compare point by point.".format(GRID_MM), "",
          "| run | cells | mean air speed (m/s) | turbulence, sqrt(2k/3) (m/s) | air below 0.1 m/s | mean difference "
          "from the reference's air |", "|---|---|---|---|---|---|"]
    for a in air:
        L.append(f"| {a['label']} | {_f(a.get('cells'), '{:,}')} | {_f(a.get('mean_speed_m_s'), '{:.3f}')} | "
                 f"{_f(a.get('turbulence_m_s'), '{:.3f}')} | {_p(a.get('still_share'))} % | "
                 f"{'–' if a['label'] == r0.label else _f(a.get('vs_ref_pct'), '{:.0f} %')} |")
    L += ["", "The difference is the mean |U − U_ref| over the chamber as a share of the reference's mean speed: 0 % "
              "for the same flow; two unrelated flows of the same mean speed would be ~100 % or more.", ""]

    if not bt.empty:
        cols = [c for c in [*R.GROUPS, "airborne at switch-off"] if c in bt and (bt[c] > 0).any()]
        b = bt[bt.variant == show]
        L += [f"## The 0-{BAND[1]:g} µm band, weighted by the measured spray", "",
              f"By number, % of the band, {_label(s0, show)}:", "",
              "| run | " + " | ".join(cols) + " | the band's share of the floor's deposit |",
              "|---|" + "---|" * (len(cols) + 1)]
        for rec in b.to_dict("records"):
            L.append(f"| {rec['label']} | " + " | ".join(_p(rec[c]) for c in cols) + f" | {_p(rec['purity'])} |")
        L += ["", "Its floor share (both floor columns), every run, %:", "",
              "| run | " + " | ".join(_label(s0, v) for v in common) + " |", "|---|" + "---|" * len(common)]
        for r in runs:
            g = bt[bt.label == r.label].set_index("variant")
            L.append(f"| {r.label} | " + " | ".join(_p(g.floor.get(v)) for v in common) + " |")
        L.append("")

    L += ["## The floor deposit by band, against the reference", "",
          f"{_label(s0, show)}. Each size counted equally. A difference is shown with its noise from the droplet count "
          f"(± {NOISE_X:g} sd); *moved* is the share of the band's floor deposit that lands in a different "
          f"{SQUARE_MM:g} mm square, with {MOVED_X:g}× what the droplet count alone would move.", "",
          "| run | band | on the floor | floor share (points) | centre shift (mm) | spread change (mm) | moved (%) | "
          "verdict |", "|---|---|---|---|---|---|---|---|"]
    for rec in ag[ag.variant == show].to_dict("records"):
        if rec["reference"]:
            L.append(f"| {rec['label']} (reference) | {rec['band']} | {rec['on_floor']:,} of {rec['fired']:,} "
                     f"({rec['floor_pct']:.0f} %) | | | spread {_f(rec['spread_mm'], '{:.0f}')} mm | | |")
            continue
        L.append(f"| {rec['label']} | {rec['band']} | {rec['on_floor']:,} of {rec['fired']:,} ({rec['floor_pct']:.0f} %) | "
                 f"{_pm(rec['d_floor_pp'], rec['noise_floor_pp'])} | "
                 f"{_pm(rec['d_centre_mm'], rec['noise_centre_mm'], '{:.1f}')} | "
                 f"{_pm(rec['d_spread_mm'], rec['noise_spread_mm'])} | "
                 f"{_pm(rec['moved_pct'], rec['noise_moved_pct'], '{:.0f}', MOVED_X)} | {rec['verdict']} |")
    others = ag[~ag.reference & (ag.variant != show)]
    if len(others):
        L += ["", "Every other run (gusts, flow kept), the verdicts only (numbers in `comparison.csv`):", "",
              "| run | " + " | ".join(_label(s0, v) for v in common if v != show) + " |",
              "|---|" + "---|" * (len(common) - 1)]
        for r in runs:
            if r is r0:
                continue
            cells = []
            for v in common:
                if v == show:
                    continue
                g = others[(others.label == r.label) & (others.variant == v)]
                worst = max((VERDICTS.index(x) for x in g.verdict if x in VERDICTS), default=None)
                bands = [b for b, x in zip(g.band, g.verdict) if x == VERDICTS[2]]
                cells.append("–" if worst is None else VERDICTS[worst] + (f" ({', '.join(bands)})" if bands else ""))
            L.append(f"| {r.label} | " + " | ".join(cells) + " |")
    L += ["", "![where each size ends up, flow by flow](figures/compare_fates.png)", ""]

    L += ["## Each run's checks", "", "| run | every droplet accounted for | tracers on the floor, gusts off / on | "
          "≥ 80 µm within (mm) of the impact point, 90 % | flags in its report |", "|---|---|---|---|---|"]
    for r in runs:
        acc = all((x.get("accounting") or {}).get("ok") for x in r.meta.get("runs", []))
        cases = (r.checks or {}).get("cases", {})
        tr = " / ".join(_p((cases.get(f"tracers_gusts_{g}") or {}).get("floor"), 0) for g in ("off", "on"))
        lg = [x.get("r90_mm") for x in (r.checks or {}).get("large", []) if x.get("variant") == show]
        rep = (r.folder / "report.md").read_text(encoding="utf-8") if (r.folder / "report.md").exists() else ""
        L.append(f"| {r.label} | {'yes' if acc else 'NO'} | {tr} % | {_f(lg[0] if lg else None, '{:.0f}')} | "
                 f"{rep.count('FLAG')} |")
    L += ["", "The tracers show the near-wall artefact (PLAN.md, Phase 3a): it depends on the mesh, so a flow on "
              "another mesh can carry more or less of it.", ""]

    L += ["## How agreement is judged", "",
          f"- **The noise from the droplet count:** each run's droplets resampled with replacement {RESAMPLES} times "
          "(the bootstrap); a measure's noise is its standard deviation over the resamples, and a difference's "
          "combines both runs'.",
          f"- **The same:** within {NOISE_X:g} sd of its noise (for *moved*, {MOVED_X:g}× the share two runs of the "
          "same flow would differ by from the droplet count alone). Each comparison makes ~20 such judgements a run, "
          "so a looser test would flag some by chance.",
          f"- **Close:** beyond the noise but within the tolerance: floor share {tol['floor_pp']:g} points, centre "
          f"{tol['centre_mm']:g} mm, spread {tol['spread_mm']:g} mm, moved {tol['moved_pct']:g} % (`sweep.tolerance` "
          "in the settings).",
          "- **Differs:** beyond both. A band with fewer than "
          f"{cfd_plots.MIN_FOR_MAP} droplets on the floor (or whose resamples often fall below that) gets only the "
          "floor share.",
          f"- More droplets per size shrink the noise (as 1/sqrt): {s0.per_size} of each here.", ""]
    L += ["## Files", "", "- `comparison.csv`: every run, variant and band: the measures, differences and noise.",
          "- `figures/compare_floor.png`, `figures/compare_fates.png`.",
          "- One folder per run, each with its report.md, figures and ParaView states.", ""]
    return "\n".join(L)
