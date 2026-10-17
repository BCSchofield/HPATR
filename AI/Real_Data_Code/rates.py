"""Throughput by mass balance: in-band liquid flow and in-band droplets produced per second (sizer 3.1.0 plan, Phase 3,
2026-10-17). One function for the capture GUI (master_log) and the analysis app. numpy only (the lab PC has no scipy).

All the liquid the nozzle makes comes from the syringe: Q (mm^3/s). In the frames' measurement volume, the share of
that liquid carried by droplets in the band is

    share = sum over frames of the in-band droplets' volume / sum of ALL the liquid's volume

with both measured inside the same volume (droplets of every size, ligaments and blobs: the liquid stage's
vol_liquid_in_volume_mm3; in-band droplets from their calibrated sizes, border-weighted, crowded ones added back in
proportion). Then

    in-band liquid flow (mL/min)          = Q x share
    in-band droplets produced per second  = Q x (in-band droplets per mm^3 of liquid in view)

The droplets below d_min, unsized, never enter: their volume is only in the denominator, as every other piece of
liquid is (3.0.0's formula gave it to the sized droplets, ~doubling their rate).

Assumptions, stated with every number: every piece of liquid crosses the window at the same speed (a snapshot is
not a flux: the velocity to-do removes this); one window stands for the whole spray; the volume of ligaments and
blobs comes from 2-D (bodies of revolution); only droplets the AI finds (a missed droplet counts as liquid, lowering
the share)."""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

SYRINGE_ID_MM = 20.27          # the rig's syringe bore (GUI_Clean; GLR uses the same)
STEPS_PER_MM = 6800.0          # TMC5160 plunger drive (firmware-confirmed 2026-10-07)
DEFAULT_BAND_UM = (30.0, 60.0)  # Ben, 2026-10-17: 30-60 um until the reticle brings d_min below 30
ASSUMPTIONS = ("snapshot = flux (every piece of liquid crosses the window at the same speed); one window stands for "
               "the spray; ligament and blob volumes from 2-D; only droplets the AI finds")


def syringe_mm3_s(steps_s: float) -> float:
    """The syringe's volume flow (mm^3/s) at `steps_s` plunger steps per second."""
    return math.pi * (SYRINGE_ID_MM / 2.0) ** 2 * float(steps_s) / STEPS_PER_MM


def liquid_ml_min(steps_s: float) -> float:
    return syringe_mm3_s(steps_s) * 60.0 / 1000.0


def band_parts(frames, d_by_frame: dict, w_by_frame: dict, band=DEFAULT_BAND_UM):
    """Per frame (in `frames` order): the border-weighted count of sized droplets with lo <= d < hi and their
    weighted sum of d^3 (um^3)."""
    lo, hi = band
    wb, v3 = [], []
    for f in frames:
        d = np.asarray(d_by_frame.get(f, []), float)
        w = np.asarray(w_by_frame.get(f, []), float)
        if w.size != d.size:
            w = np.ones(d.size)
        m = (d >= lo) & (d < hi)
        wb.append(float(w[m].sum()))
        v3.append(float((w[m] * d[m] ** 3).sum()))
    return np.array(wb), np.array(v3)


def throughput(q_mm3_s: float, wb, v3, vliq, crowded_factor: float = 1.0, n_boot: int = 0, seed: int = 0,
               pool=None, band=DEFAULT_BAND_UM) -> dict:
    """The band's share of the liquid, the in-band liquid flow and droplets per second, with 95 % CIs by resampling
    frames (`pool`: which frame indices may be drawn, e.g. every ci_stride-th; default all).
    wb, v3: band_parts; vliq: the liquid stage's vol_liquid_in_volume_mm3 per frame; crowded_factor: the
    concentration's (crowded and other unmeasured droplets added back in proportion, sizes alike)."""
    wb, v3, vliq = (np.asarray(a, float) for a in (wb, v3, vliq))
    k = float(crowded_factor or 1.0)

    def calc(Wb, V3, VL):
        with np.errstate(all="ignore"):
            vb_mm3 = math.pi / 6.0 * V3 * 1e-9 * k
            share = np.where(VL > 0, vb_mm3 / VL, np.nan)
            rate = np.where(VL > 0, q_mm3_s * Wb * k / VL, np.nan)
            dmean = np.where(Wb > 0, (V3 / np.where(Wb > 0, Wb, 1)) ** (1.0 / 3.0), np.nan)
        return share, rate, dmean

    share, rate, dmean = (float(x) for x in calc(wb.sum(), v3.sum(), vliq.sum()))
    sig = lambda x: float(f"{x:.6g}")                       # 6 significant figures: flows can be tiny
    out = {"band_um": [float(band[0]), float(band[1])], "q_mm3_s": round(q_mm3_s, 4),
           "liquid_ml_min": sig(q_mm3_s * 0.06),
           "band_share_pct": sig(100.0 * share) if math.isfinite(share) else None,
           "band_flow_ml_min": sig(q_mm3_s * share * 0.06) if math.isfinite(share) else None,
           "band_rate_per_s": sig(rate) if math.isfinite(rate) else None,
           "band_mean_d3_um": round(dmean, 2) if math.isfinite(dmean) else None,
           "band_droplets_weighted": round(float(wb.sum()) * k, 2), "frames": int(vliq.size),
           "liquid_in_volume_mm3": round(float(vliq.sum()), 6), "crowded_factor": k,
           "assumptions": ASSUMPTIONS}
    idx = np.arange(vliq.size) if pool is None else np.asarray(pool)
    if n_boot and idx.size >= 2:
        rng = np.random.default_rng(seed)
        draws = idx[rng.integers(0, idx.size, (n_boot, idx.size))]
        W = np.zeros((n_boot, vliq.size))
        for b in range(n_boot):
            np.add.at(W[b], draws[b], 1.0)
        with np.errstate(all="ignore"):                    # macOS Accelerate: spurious matmul warnings on finite input
            s_b, r_b, _d = calc(W @ wb, W @ v3, W @ vliq)
        s0, r0, _d0 = (float(x) for x in calc(wb[idx].sum(), v3[idx].sum(), vliq[idx].sum()))
        s_b, r_b = s_b - s0 + share, r_b - r0 + rate          # centred on the full-run value
        out["boot_band_flow_ml_min"] = (q_mm3_s * s_b * 0.06).tolist()
        out["boot_band_rate_per_s"] = r_b.tolist()
        for key, reps in (("band_flow_ml_min", q_mm3_s * s_b * 0.06), ("band_rate_per_s", r_b)):
            ok = reps[np.isfinite(reps)]
            if ok.size:
                out[f"{key}_ci95"] = [sig(float(v)) for v in np.percentile(ok, [2.5, 97.5])]
    return out


def from_run_files(meas_dir: Path, liquid_dir: Path, steps_s: float, band=DEFAULT_BAND_UM, n_boot: int = 0,
                   seed: int = 0) -> dict | None:
    """The throughput of one measured run from its own files (droplets_<thr>/droplet_sizes.csv and summary.json,
    liquid_<thr>/classical_per_frame.csv), or None when the run was measured before sizer 3.1.0 (no in-volume
    liquid volume) or the syringe speed is unknown. What GUI_Clean writes into master_log."""
    import json
    meas_dir, liquid_dir = Path(meas_dir), Path(liquid_dir)
    try:
        steps = float(steps_s)
        cpf = {}
        with open(liquid_dir / "classical_per_frame.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                cpf[r["frame"]] = float(r["vol_liquid_in_volume_mm3"])
        d, w = {}, {}
        with open(meas_dir / "droplet_sizes.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("in_focus") == "1":
                    d.setdefault(r["frame"], []).append(float(r["diameter_um"]))
                    w.setdefault(r["frame"], []).append(float(r["weight"]) if r.get("weight") else 1.0)
        summ = json.loads((meas_dir / "summary.json").read_text(encoding="utf-8"))
        k = float((summ.get("concentration") or {}).get("crowded_factor") or 1.0)
    except (KeyError, TypeError, ValueError, OSError):
        return None
    if steps <= 0 or not cpf:
        return None
    frames = sorted(cpf)
    wb, v3 = band_parts(frames, d, w, band)
    return throughput(syringe_mm3_s(steps), wb, v3, np.array([cpf[f] for f in frames]), k, n_boot, seed,
                      band=band)
