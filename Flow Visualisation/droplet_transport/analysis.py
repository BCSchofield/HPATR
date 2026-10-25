"""What a run says: each size's fate, the band's delivery and purity, where each size crosses the planes, and the
deflection by the cross-stream (the same run with the inlets off).

Definitions (Ben, 2026-10-23; the band is lo <= d < hi, as rates.band_parts):
    delivery (number)   the share of the band's droplets that reach the target
    delivery (volume)   the same, weighted by d^3 (the band's liquid)
    purity (number)     the band's share of every droplet that reaches the target
    purity (volume)     the band's share of the liquid that reaches the target
Weights per fired size come from the measured distribution (sizes.weights). Without one, delivery is the plain
mean over the band's fired sizes and purity cannot be computed (it needs to know how many of each size there are).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import physics

CATEGORIES = ("target", "other outlets", "floor", "other walls", "airborne")


def target_fate(scn) -> str:
    return f"outlet:{scn.target_outlet}" if scn.target_outlet else "target"


def category(scn, fate: np.ndarray) -> np.ndarray:
    tgt = target_fate(scn)
    out = np.full(fate.shape, "other walls", dtype=object)
    out[fate == tgt] = "target"
    out[(fate != tgt) & np.char.startswith(fate.astype(str), "outlet:")] = "other outlets"
    out[fate == "wall:floor"] = "floor"
    out[fate == "airborne"] = "airborne"
    return out


def nearest_distance_along(jet, line_point, line_dir) -> float:
    """How far along `jet`'s axis its closest approach to another line is (s* >= 0)."""
    d1, d2 = jet.axis, np.asarray(line_dir, float) / np.linalg.norm(line_dir)
    w0 = jet.origin - np.asarray(line_point, float)
    b = d1 @ d2
    denom = 1.0 - b * b
    if denom < 1e-9:
        return max(-(w0 @ d1), 0.0)
    s = (b * (d2 @ w0) - (d1 @ w0)) / denom
    return max(float(s), 0.0)


def stokes_numbers(scn, flow, sizes_um) -> dict:
    """Per inlet jet: St = tau_Stokes x u_c / (2 r_1/2) where the jet passes closest to the spray's axis."""
    tau0 = physics.tau_stokes(np.asarray(sizes_um) * 1e-6, scn.rho_d, scn.gas)
    out = {}
    for p in scn.inlets:
        jet = flow.jet(p.name)
        s = nearest_distance_along(jet, scn.spray.nozzle, scn.spray.axis)
        uc, width = float(jet.centreline(s)), 2.0 * float(jet.half_width(s))
        out[p.name] = {"s_m": s, "u_c_m_s": uc, "width_m": width,
                       "St": tau0 * uc / width if width > 0 and uc > 0 else np.full(tau0.shape, np.nan)}
    return out


def spray_wall(scn, flow, sizes_um) -> dict:
    """Where the spray's axis meets a wall, and each size's Stokes number in the spray jet there,
    St = tau_Stokes x u_c / (2 r_1/2). The idealised jet does not see the wall, so every droplet it carries there
    hits it in the model; in the chamber a droplet with St well under 1 turns with the air instead. So a wall hit
    by a size with St < 1 is an artefact of Phase 1's flow, flagged in the report."""
    sp = scn.spray
    with np.errstate(divide="ignore"):
        cand = [((0.0 - sp.nozzle[a]) / sp.axis[a] if sp.axis[a] < 0 else
                 (scn.box[a] - sp.nozzle[a]) / sp.axis[a] if sp.axis[a] > 0 else np.inf, a) for a in range(3)]
    s, a = min(cand)
    names = {0: ("left", "right"), 1: ("front", "back"), 2: ("floor", "lid")}
    wall = names[a][0 if sp.axis[a] < 0 else 1]
    jet = flow.jet("spray")
    uc, width = float(jet.centreline(s)), 2.0 * float(jet.half_width(s))
    tau0 = physics.tau_stokes(np.asarray(sizes_um) * 1e-6, scn.rho_d, scn.gas)
    return {"wall": wall, "s_m": float(s), "u_c_m_s": uc, "width_m": width,
            "St": tau0 * uc / width if uc > 0 else np.zeros(tau0.shape)}


def per_size(scn, drops, tr, flow) -> pd.DataFrame:
    sizes = drops.sizes_um
    cat = category(scn, tr.fate)
    fates = sorted(set(tr.fate))
    rows = []
    St = stokes_numbers(scn, flow, sizes)
    sw = spray_wall(scn, flow, sizes)
    vs = physics.settling_speed(sizes * 1e-6, scn.rho_d, scn.gas, scn.drag)
    tau0 = physics.tau_stokes(sizes * 1e-6, scn.rho_d, scn.gas)
    for k, s in enumerate(sizes):
        m = drops.size_index == k
        n = int(m.sum())
        row = {"size_um": s, "n": n, "tau_ms": tau0[k] * 1e3, "settling_mm_s": vs[k] * 1e3}
        for c in CATEGORIES:
            row[c] = float((cat[m] == c).mean())
        for f in fates:
            row[f] = float((tr.fate[m] == f).mean())
        for name, st in St.items():
            row[f"St {name}"] = float(st["St"][k])
        row[f"St spray at the {sw['wall']}"] = float(sw["St"][k])
        for pc, (ax, _c, pname) in zip(tr.crossings, scn.planes):
            pos = pc["pos"][m]
            ok = np.isfinite(pos[:, 0])
            row[f"{pname}: crossed"] = float(ok.mean())
            for a in range(3):
                if a == ax:
                    continue
                ax_l = "xyz"[a]
                row[f"{pname}: {ax_l} mean mm"] = float(pos[ok, a].mean() * 1e3) if ok.any() else np.nan
                row[f"{pname}: {ax_l} sd mm"] = float(pos[ok, a].std() * 1e3) if ok.sum() > 1 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def band_metrics(ps: pd.DataFrame, band, n_weights: np.ndarray | None) -> dict:
    d = ps["size_um"].to_numpy(float)
    P = ps["target"].to_numpy(float)
    inb = (d >= band[0]) & (d < band[1])
    out = {"band_um": list(band), "sizes_in_band": int(inb.sum())}
    if not inb.any():
        return {**out, "delivery_number": None, "delivery_volume": None, "purity_number": None,
                "purity_volume": None, "weighting": "no fired size in the band"}
    if n_weights is None:
        out.update(delivery_number=float(P[inb].mean()),
                   delivery_volume=float((P * d ** 3)[inb].sum() / (d ** 3)[inb].sum()),
                   purity_number=None, purity_volume=None,
                   weighting="none: every fired size counts alike; purity needs a measured distribution")
        return out
    n = np.asarray(n_weights, float)
    v = n * d ** 3
    arr_n, arr_v = n * P, v * P

    def share(num, den):
        return float(num / den) if den > 0 else None
    out.update(delivery_number=share(arr_n[inb].sum(), n[inb].sum()),
               delivery_volume=share(arr_v[inb].sum(), v[inb].sum()),
               purity_number=share(arr_n[inb].sum(), arr_n.sum()),
               purity_volume=share(arr_v[inb].sum(), arr_v.sum()),
               arrivals_below_band_number=share(arr_n[d < band[0]].sum(), arr_n.sum()),
               arrivals_above_band_number=share(arr_n[d >= band[1]].sum(), arr_n.sum()),
               arrivals_below_band_volume=share(arr_v[d < band[0]].sum(), arr_v.sum()),
               arrivals_above_band_volume=share(arr_v[d >= band[1]].sum(), arr_v.sum()),
               weighting="the measured distribution, by number and by d^3")
    return out


def deflection(scn, ps_on: pd.DataFrame, ps_off: pd.DataFrame) -> pd.DataFrame:
    """Per size and plane: where it crosses with the inlets on minus with them off (mm), and the target shares."""
    out = pd.DataFrame({"size_um": ps_on["size_um"], "target on": ps_on["target"], "target off": ps_off["target"]})
    for ax, _c, pname in scn.planes:
        for a in range(3):
            if a == ax:
                continue
            col = f"{pname}: {'xyz'[a]} mean mm"
            out[f"{pname}: {'xyz'[a]} shift mm"] = ps_on[col] - ps_off[col]
    return out


def accounting(tr, drops) -> dict:
    """Every droplet ends somewhere: target + outlets + walls + airborne = all fired."""
    vals, counts = np.unique(tr.fate.astype(str), return_counts=True)
    by = dict(zip(vals.tolist(), counts.tolist()))
    total = int(sum(by.values()))
    return {"fired": int(drops.d.size), "accounted": total, "ok": total == drops.d.size
            and not any(v == "" for v in vals), "by_fate": by, "iteration_cap_hits": tr.timed_out}


def droplet_table(scn, drops, tr, n_per_droplet: np.ndarray | None) -> pd.DataFrame:
    t = pd.DataFrame({"size_um": drops.sizes_um[drops.size_index],
                      "start_x_mm": drops.x0[:, 0] * 1e3, "start_y_mm": drops.x0[:, 1] * 1e3,
                      "start_z_mm": drops.x0[:, 2] * 1e3,
                      "fate": tr.fate.astype(str), "category": category(scn, tr.fate),
                      "end_x_mm": tr.end[:, 0] * 1e3, "end_y_mm": tr.end[:, 1] * 1e3, "end_z_mm": tr.end[:, 2] * 1e3,
                      "time_s": tr.t_end})
    for pc, (_ax, _c, pname) in zip(tr.crossings, scn.planes):
        for a in range(3):
            t[f"{pname}: {'xyz'[a]} mm"] = pc["pos"][:, a] * 1e3
    if n_per_droplet is not None:
        t["number_weight"] = n_per_droplet
    return t
