"""Per-run tables, cross-run statistics and figures for F2 + H1. Scratch only."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
RSM = Path("/Volumes/LaCie/Experiments/Taguchi/CCD/CCD 4-factor 12-10-2026/rsm_results.csv")
FRAME_PX = 2048 * 1152
WDEFS = ["P10", "P20", "P40", "DARK70", "P20_and_DARKdil"]

rsm = pd.read_csv(RSM)
rsm = rsm.sort_values("order").reset_index(drop=True)
# deck labels: unique settings in capture order
seen, lab, rep = {}, [], {}
for _, r in rsm.iterrows():
    key = (r.gas_sccm, r.rpm, r.feed_sps, r.orifice_mm)
    if key not in seen:
        seen[key] = f"C{len(seen) + 1}"
    rep[key] = rep.get(key, 0) + 1
    lab.append(seen[key] + (f"r{rep[key]}" if rep[key] > 1 else ""))
rsm["label"] = lab
assert rsm.loc[rsm.run.str.startswith("142150"), "label"].item() == "C20", rsm[["run", "label"]]

rows = []
for _, r in rsm.iterrows():
    name = r.run
    fr = pd.read_csv(RUNS / f"{name}_frames.csv")
    sa = pd.read_csv(RUNS / f"{name}_sample.csv")
    meta = json.loads((RUNS / f"{name}_done.json").read_text())
    o = dict(run=name, label=r.label, order=r.order, gas=r.gas_sccm, rpm=r.rpm, feed=r.feed_sps,
             orifice=r.orifice_mm, af_rsm=r.af, n_frames=len(fr), gate_match=int(fr.match.sum()),
             t_io_s=fr.t_io.mean(), t_measure_s=fr.t_measure.mean(), t_vol_s=sa.t_vol.mean(),
             windows_liquid_s=meta["windows_liquid_stage_s"])
    D, T = fr.droplet_px.sum(), fr.total_px.sum()
    o["af_all"] = 100 * D / T
    o["oof_only_area_share"] = fr.oof_only_px.sum() / fr.unatom_px.sum() if fr.unatom_px.sum() else 0
    # ---- F2 on the sample
    s = sa.sum(numeric_only=True)
    o["n_sample"] = len(sa)
    o["af_area_s"] = 100 * s.droplet_px / s.total_px
    o["af_vol_round"] = 100 * s.V_drop / (s.V_drop + s.V_un_round)
    o["af_vol_ribbon"] = 100 * s.V_drop / (s.V_drop + s.V_un_ribbon)
    o["af_vol_round_no_oof"] = 100 * s.V_drop / (s.V_drop + s.V_un_round - s.V_oof_round)
    o["ratio_round"] = o["af_vol_round"] / o["af_area_s"]
    o["ratio_ribbon"] = o["af_vol_ribbon"] / o["af_area_s"]
    o["oof_vol_share_round"] = s.V_oof_round / s.V_un_round if s.V_un_round else 0
    o["oof_area_share_s"] = s.oof_only_px / s.unatom_px if s.unatom_px else 0
    # depth per px: mean thickness (um) of each class
    o["drop_depth_um"] = 10 * s.V_drop / s.droplet_px
    o["unatom_depth_round_um"] = 10 * s.V_un_round / s.unatom_px if s.unatom_px else np.nan
    o["unatom_depth_ribbon_um"] = 10 * s.V_un_ribbon / s.unatom_px if s.unatom_px else np.nan
    o["drop_daves_over_sphere"] = s.drop_daves_sub / s.drop_sph_sub if s.drop_sph_sub else np.nan
    o["drop_daves_over_sphere_round"] = s.drop_daves_round / s.drop_sph_round if s.drop_sph_round else np.nan
    o["drop_daves_over_prolate_expect"] = s.drop_daves_sub / s.drop_prolate_expect if s.drop_prolate_expect else np.nan
    o["compact_daves_over_round"] = s.compact_daves / s.compact_round if s.compact_round else np.nan
    o["n_compact"] = int(s.n_compact)
    # ---- F2 on ALL frames (from the saved masks)
    va = pd.read_csv(RUNS / f"{name}_vol_all.csv")
    assert (va.droplet_px.values == fr.droplet_px.values).all()
    v = va.sum(numeric_only=True)
    o["af_vol_round_all"] = 100 * v.V_drop / (v.V_drop + v.V_un_round)
    o["af_vol_ribbon_all"] = 100 * v.V_drop / (v.V_drop + v.V_un_ribbon)
    o["ratio_round_all"] = o["af_vol_round_all"] / o["af_all"]
    o["ratio_ribbon_all"] = o["af_vol_ribbon_all"] / o["af_all"]
    o["unatom_depth_round_um_all"] = 10 * v.V_un_round / v.unatom_px if v.unatom_px else np.nan
    o["drop_depth_um_all"] = 10 * v.V_drop / v.droplet_px
    for key in ["P20", "DARK70"]:
        o[f"af_vol_round_no{key}"] = 100 * v[f"V_drop_no{key}"] / (v[f"V_drop_no{key}"] + v[f"V_un_round_no{key}"])
    # frame bootstrap (iid frames; optimistic at low GLR where frames correlate)
    rng = np.random.default_rng(1)
    idx = rng.integers(0, len(va), (1000, len(va)))
    Dv, Uv, Ur = va.V_drop.values, va.V_un_round.values, va.V_un_ribbon.values
    Dp, Tp = fr.droplet_px.values, fr.total_px.values
    bv = 100 * Dv[idx].sum(1) / (Dv[idx].sum(1) + Uv[idx].sum(1))
    ba = 100 * Dp[idx].sum(1) / Tp[idx].sum(1)
    o["af_area_ci_lo"], o["af_area_ci_hi"] = np.percentile(ba, [2.5, 97.5])
    o["af_vol_round_ci_lo"], o["af_vol_round_ci_hi"] = np.percentile(bv, [2.5, 97.5])
    # ---- H1 over ALL frames
    for k in WDEFS:
        a = meta["win_area"][k]
        Dw, Tw = fr[f"dW_{k}"].sum(), fr[f"tW_{k}"].sum()
        af_w = 100 * (D - Dw) / (T - Tw) if T > Tw else np.nan
        o[f"win_px_{k}"] = a
        o[f"win_pct_{k}"] = 100 * a / FRAME_PX
        o[f"liq_in_win_pct_{k}"] = 100 * Tw / T          # share of the denominator that sat in window px
        o[f"af_{k}"] = af_w
        o[f"daf_{k}"] = af_w - o["af_all"]
    rows.append(o)

df = pd.DataFrame(rows)
df.to_csv(HERE / "per_run_f2h1.csv", index=False)
print("gate: frames matching classical_per_frame.csv exactly:", df.gate_match.sum(), "/", df.n_frames.sum())
print("af_all vs rsm af max abs diff:", (df.af_all - df.af_rsm).abs().max())
print("time per frame (Mac, 4 procs on the LaCie): io %.3f  measure_frame %.3f  volume %.3f s" % (
    df.t_io_s.mean(), df.t_measure_s.mean(), df.t_vol_s.mean()))
print("Windows liquid stage total: %.0f s for %d frames (%.3f s/frame)" % (
    df.windows_liquid_s.sum(), df.n_frames.sum(), df.windows_liquid_s.sum() / df.n_frames.sum()))
