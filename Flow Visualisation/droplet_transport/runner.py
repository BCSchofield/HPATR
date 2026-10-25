"""Run a settings file: one scenario, or one run per combination of its sweep.

Each run draws the layout first, fires the droplets with the inlets on, then the same droplets with the inlets off
(the deflection is the difference), and writes its CSVs, figures and report. Output:
    output/<name>/<YYYY-MM-DD_HHMMSS>/          the settings file copied in, report.md, figures/, CSVs
    .../runs/<NN>_<change>/                       a sweep's runs, each like the above; sweep.csv + sweep_report.md
"""
from __future__ import annotations

import itertools
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__, analysis, injection, plots, report, settings, sizes, tracker
from .flow import build_flow

FIGURES = (("layout.png", "the scenario as set: chamber, ports, nozzle, where the droplets start, the planes"),
           ("crossings.png", "the headline: where each size crosses the planes, inlets on and off, and the shift"),
           ("paths.png", "droplet paths by size, side and top, over the gas's direction"),
           ("fates_by_size.png", "where each size ends up: target, other outlets, floor, other walls, airborne"),
           ("delivery_vs_size.png", "the share reaching the target against size, inlets on and off"),
           ("gas_field.png", "the idealised gas flow: speed and direction in a side and a top cut"),
           ("speed_vs_distance.png", "each shown droplet's speed against the distance it has travelled"))


def recorded(scn, drops) -> np.ndarray:
    """Which droplets keep their paths: the first paths_per_size of each of run.path_sizes_um (nearest fired)."""
    rec = np.zeros(drops.d.size, bool)
    want = scn.run["path_sizes_um"] or list(drops.sizes_um[np.linspace(0, drops.sizes_um.size - 1,
                                                                        min(9, drops.sizes_um.size)).astype(int)])
    for s in want:
        k = int(np.argmin(np.abs(drops.sizes_um - s)))
        rec[np.flatnonzero(drops.size_index == k)[: scn.run["paths_per_size"]]] = True
    return rec


def load_distribution(scn, log=print):
    p = scn.spray.distribution
    if p is None:
        return None
    if not Path(p).exists():
        log(f"  the measured size distribution {p} is not there yet: purity is not computed "
            f"(make it with import_sizes.py; see README.md)")
        return None
    return sizes.load(p)


def _flags(scn, flow, ps, acc, dist, info, tr) -> list[str]:
    flags = []
    if not acc["ok"]:
        flags.append(f"**Accounting failed:** {acc['accounted']} of {acc['fired']} droplets have a fate.")
    else:
        flags.append(f"Every droplet is accounted for ({acc['fired']:,}): " +
                     ", ".join(f"{k} {v:,}" for k, v in sorted(acc["by_fate"].items())) + ".")
    stw = [c for c in ps.columns if c.startswith("St spray at the")][0]
    wall = stw.replace("St spray at the ", "")
    on_wall = ps[f"wall:{wall}"] if f"wall:{wall}" in ps else pd.Series(0.0, index=ps.index)
    art = ps[(ps[stw] < 1.0) & (on_wall > 0.5)]["size_um"]
    if len(art):
        flags.append(f"**Wall hits that would not happen:** {art.min():g}-{art.max():g} um mostly hit the {wall} "
                     f"where the spray's axis meets it, but their Stokes number in the spray jet there is under 1: in "
                     "the chamber they would turn with the air. Phase 1's jet does not see the wall.")
    if scn.target_box is not None:
        k, side = settings.WALLS[wall]
        on_that_wall = abs(scn.target_box[side][k] - (scn.box[k] if side else 0.0)) < 1e-9
        doubt = ps[(ps[stw] < 1.0) & (ps["target"] > 0.05) & on_that_wall]["size_um"]
        if len(doubt):
            flags.append(f"**Arrivals that may not stick:** the target lies on the {wall}, and {doubt.min():g}-"
                         f"{doubt.max():g} um reach it with a Stokes number under 1 in the spray jet there. Whether "
                         "they deposit (impaction) or turn away with the air is not modelled: Phase 1's jet does not "
                         "see the wall. The delivery of those sizes is an upper bound.")
    u_start = float(flow.jet("spray").centreline(scn.spray.standoff))
    v0 = injection.speed_for(scn.spray, scn.spray.sizes_um)
    if u_start > 2.0 * float(np.max(v0)):
        flags.append(f"**The gas at the start is faster than the droplets:** the gas-only spray jet is "
                     f"{u_start:.0f} m/s at the stand-off ({scn.spray.standoff * 1000:g} mm), the droplets start at "
                     f"{_speeds(v0)} m/s, so the small ones speed up to the gas within "
                     "millimetres. Both cannot be right near the nozzle: the liquid loading slows the real gas "
                     "there, or the droplets are faster than estimated. Phase 5's speeds by size settle it.")
    if tr.timed_out:
        flags.append(f"{tr.timed_out} droplets hit the iteration cap (counted as airborne).")
    air = float(ps["airborne"].mean())
    if air > 0:
        flags.append(f"{100 * air:.1f} % of the droplets fired are still airborne after {scn.run['max_time_s']:g} s.")
    if dist is None:
        flags.append("**No measured size distribution:** purity is not computed and delivery counts every fired size "
                     "alike. Import one with import_sizes.py (README.md).")
    else:
        flags.append(f"Sizes weighted by `{Path(dist.source).name}` (d_min {dist.d_min_um:g} um; below it "
                     f"{100 * dist.below_dmin / dist.total:.0f} % of the droplets, counted not sized, spread over "
                     f"{scn.spray.below_dmin_from_um:g}-{dist.d_min_um:g} um: estimated). "
                     f"{100 * info['share_not_fired']:.1f} % of the measured droplets fall outside the fired sizes.")
    for p in scn.inlets:
        if p.shape == "slot":
            s = analysis.nearest_distance_along(flow.jet(p.name), scn.spray.nozzle, scn.spray.axis)
            if s > p.length:
                flags.append(f"{p.name} is a slot: its plane-jet model holds to {p.length * 1000:g} mm from it, but "
                             f"the spray is {s * 1000:.0f} mm away (too fast there).")
    est = [k for k, (b, _v) in scn.basis.items() if b.startswith("estimated")]
    if est:
        flags.append("Estimated inputs: " + ", ".join(f"`{k}`" for k in est) + ".")
    return flags


def run_one(scn, out_dir: Path, dist=None, log=print) -> dict:
    out_dir = Path(out_dir)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    flow = build_flow(scn)
    plots.layout(scn, flow, fig_dir / "layout.png")
    seed = scn.run["seed"]
    drops = injection.fire(scn, np.random.default_rng(seed))
    rec = recorded(scn, drops)
    t0 = time.time()
    tr = tracker.track(scn, flow, drops, np.random.default_rng(seed + 1), rec)
    ps = analysis.per_size(scn, drops, tr, flow)
    ps_off = tr_off = None
    if scn.run["compare_without_inlets"] and scn.inlets:
        scn_off = scn.with_inlets_off()
        flow_off = build_flow(scn_off)
        tr_off = tracker.track(scn_off, flow_off, drops, np.random.default_rng(seed + 1))
        ps_off = analysis.per_size(scn_off, drops, tr_off, flow_off)
    seconds = time.time() - t0
    n_w, info = (sizes.weights(drops.sizes_um, dist, scn.spray.below_dmin_from_um) if dist is not None
                 else (None, {}))
    m = analysis.band_metrics(ps, scn.band_um, n_w)
    m_off = analysis.band_metrics(ps_off, scn.band_um, n_w) if ps_off is not None else None
    acc = analysis.accounting(tr, drops)
    band_shift = band_push = None
    defl = None
    if ps_off is not None:
        defl = analysis.deflection(scn, ps, ps_off)
        if scn.planes:
            ax_i, _at, pname = scn.planes[0]
            col = f"{pname}: {'xyz'[plots.cross_axis(scn, ax_i)]} shift mm"
            inb = (defl["size_um"] >= scn.band_um[0]) & (defl["size_um"] < scn.band_um[1])
            band_shift = float(defl.loc[inb, col].mean()) if inb.any() else None
            if band_shift is not None and not np.isfinite(band_shift):
                band_shift = None                                    # the band never crosses the plane
            if band_shift is not None and scn.inlets:
                # along the cross-stream: positive = the way the first inlet blows
                band_push = band_shift * float(np.sign(scn.inlets[0].direction[plots.cross_axis(scn, ax_i)]) or 1.0)
        defl.to_csv(out_dir / "deflection.csv", index=False, float_format="%.6g")
    ps.to_csv(out_dir / "per_size.csv", index=False, float_format="%.6g")
    per_droplet = None if n_w is None else (n_w / scn.spray.per_size)[drops.size_index]
    analysis.droplet_table(scn, drops, tr, per_droplet).to_csv(out_dir / "droplets.csv", index=False,
                                                                float_format="%.6g")
    sub = scn.label
    plots.crossings(scn, ps, ps_off, fig_dir / "crossings.png", sub)
    plots.paths(scn, flow, drops, tr, fig_dir / "paths.png", sub)
    plots.fates_by_size(scn, ps, fig_dir / "fates_by_size.png", sub)
    plots.delivery_vs_size(scn, ps, ps_off, fig_dir / "delivery_vs_size.png", n_w, sub)
    plots.gas_field(scn, flow, fig_dir / "gas_field.png")
    plots.speed_vs_distance(scn, drops, tr, fig_dir / "speed_vs_distance.png", sub)
    flags = _flags(scn, flow, ps, acc, dist, info, tr)
    summary = {"name": scn.name, "label": scn.label, "version": __version__, "seconds": round(seconds, 2),
               "band_um": list(scn.band_um), "metrics": m, "metrics_inlets_off": m_off,
               "band_shift_mm": band_shift, "band_push_mm": band_push, "accounting": acc, "distribution": info or None,
               "gas": {k: v for k, v in flow.notes.items()}, "flags": flags}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=_json))
    ctx = {"scn": scn, "flow": flow, "ps": ps, "ps_off": ps_off, "metrics": m, "metrics_off": m_off,
           "band_shift_mm": band_shift, "band_push_mm": band_push, "flags": flags, "figures": FIGURES, "version": __version__,
           "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "seconds": seconds, "n_fired": drops.d.size,
           "settings_name": scn.source.name if scn.source else "-", "weighted": n_w is not None}
    (out_dir / "report.md").write_text(report.run_report(ctx), encoding="utf-8")
    log(f"  {scn.label or scn.name}: {drops.d.size:,} droplets x {2 if ps_off is not None else 1} in {seconds:.1f} s;"
        f" band delivery {_pct(m.get('delivery_number'))} (inlets off {_pct((m_off or {}).get('delivery_number'))}),"
        f" purity {_pct(m.get('purity_number'))}, band pushed {_mm(band_push)} along the cross-stream")
    return {"label": scn.label, **{k: m.get(k) for k in ("delivery_number", "delivery_volume", "purity_number",
                                                         "purity_volume")},
            **{f"{k} off": (m_off or {}).get(k) for k in ("delivery_number", "delivery_volume", "purity_number",
                                                           "purity_volume")},
            "band_shift_mm": band_shift, "band_push_mm": band_push, "ps": ps}


def _speeds(v) -> str:
    lo, hi = float(np.min(v)), float(np.max(v))
    return f"{lo:g}" if abs(hi - lo) < 1e-9 else f"{lo:g}-{hi:g}"


def _json(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def _pct(x):
    return "–" if x is None or not np.isfinite(x) else f"{100 * x:.1f} %"


def _mm(x):
    return "–" if x is None or not np.isfinite(x) else f"{x:+.1f} mm"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.=_-]+", "_", text).strip("_")[:80]


def out_root(scns, out: Path | None) -> Path:
    if out is not None:
        return Path(out)
    return settings.ROOT / "output" / _slug(scns[0].name) / datetime.now().strftime("%Y-%m-%d_%H%M%S")


def run_file(settings_path: Path, out: Path | None = None, layout_only: bool = False, per_size: int | None = None,
             log=print) -> Path:
    settings_path = Path(settings_path)
    scns = settings.load(settings_path)
    if per_size:
        for s in scns:
            s.spray.per_size = int(per_size)
    root = out_root(scns, out)
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings_path, root / "settings.yaml")
    for b in settings.base_files(settings_path):                 # what it starts from, under its own name, so
        shutil.copy2(b, root / b.name)                           # the copy's `base:` still finds it
    if layout_only:
        for i, s in enumerate(scns):
            name = "layout.png" if len(scns) == 1 else f"layout_{i + 1:02d}_{_slug(s.label)}.png"
            plots.layout(s, build_flow(s), root / name)
        log(f"layout drawn: {root}")
        return root
    dist = load_distribution(scns[0], log)
    log(f"{settings_path.name}: {len(scns)} run{'s' if len(scns) > 1 else ''} -> {root}")
    if len(scns) == 1:
        run_one(scns[0], root, dist, log)
        return root
    axes = settings.sweep_shown(settings_path)
    combos = list(itertools.product(*[range(len(v)) for _p, v in axes]))     # the order settings.load runs them
    rows, runs, curves = [], [], []
    for i, s in enumerate(scns):
        folder = f"{i + 1:02d}_{_slug(s.label)}"
        r = run_one(s, root / "runs" / folder, dist, log)
        vals = {p: v[j] for (p, v), j in zip(axes, combos[i])}
        rows.append({**vals, **{k: v for k, v in r.items() if k != "ps"}})
        runs.append((folder, s.label))
        curves.append((s.label, r["ps"]))
    table = pd.DataFrame(rows)
    table.to_csv(root / "sweep.csv", index=False, float_format="%.6g")
    fig_dir = root / "figures"
    fig_dir.mkdir(exist_ok=True)
    figs = []
    if plots.sweep_trends(table, axes, fig_dir / "sweep_trends.png", scns[0].band_um):
        figs.append(("sweep_trends.png", "the band's delivery, purity and deflection across the sweep"))
    plots.sweep_delivery_curves(curves, fig_dir / "sweep_delivery_curves.png", scns[0].band_um,
                                f"Delivery against size across the sweep: {scns[0].name}")
    figs.append(("sweep_delivery_curves.png", "the share reaching the target against size, one line per run"))
    (root / "sweep_report.md").write_text(
        report.sweep_report(scns[0].name, settings_path.name, datetime.now().strftime("%Y-%m-%d %H:%M"), axes,
                            table, runs, figs, __version__), encoding="utf-8")
    return root


