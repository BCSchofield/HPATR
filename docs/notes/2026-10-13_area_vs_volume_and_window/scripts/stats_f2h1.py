"""Cross-run statistics for F2 + H1 from per_run_f2h1.csv. Prints a report."""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
df = pd.read_csv(HERE / "per_run_f2h1.csv")
FC = df[df.orifice >= 0.8].copy()
pd.set_option("display.width", 250)
A, VR, VB = "af_all", "af_vol_round_all", "af_vol_ribbon_all"


def sp(a, b, d):
    r, p = spearmanr(d[a], d[b])
    return f"{r:+.3f} (p={p:.2g}, n={len(d)})"


print("=== F2: Spearman area vs volume ===")
for nm, d in [("all 33", df), ("flow-controlled (orifice>=0.8)", FC), ("FC excl 0 rpm", FC[FC.rpm > 0])]:
    print(f"  {nm}:\n    ALL FRAMES  round {sp(A, VR, d)}; ribbon {sp(A, VB, d)}; round vs ribbon {sp(VR, VB, d)}")
    print(f"    30-FRAME SAMPLE  round {sp('af_area_s', 'af_vol_round', d)}; ribbon {sp('af_area_s', 'af_vol_ribbon', d)}; "
          f"round excl. oof pieces {sp('af_area_s', 'af_vol_round_no_oof', d)}; sample area vs all-frame area {sp('af_area_s', A, d)}; "
          f"sample vol vs all-frame vol {sp('af_vol_round', VR, d)}")
    print(f"    window removed (P20) from both: area {sp(A, 'af_P20', d)} ; area-noP20 vs vol-noP20 {sp('af_P20', 'af_vol_round_noP20', d)}")

print("\n=== per run (sorted by area, all frames) ===")
cols = ["label", "gas", "rpm", "feed", "orifice", A, "af_area_ci_lo", "af_area_ci_hi", VR, "af_vol_round_ci_lo",
        "af_vol_round_ci_hi", VB, "ratio_round_all", "ratio_ribbon_all", "drop_depth_um_all", "unatom_depth_round_um_all",
        "oof_vol_share_round", "af_vol_round_noP20"]
print(df.sort_values(A, ascending=False)[cols].round(3).to_string(index=False))

for nm, d in [("all 33", df), ("FC", FC)]:
    d = d.copy()
    d["rk_area"] = d[A].rank(ascending=False)
    d["rk_round"] = d[VR].rank(ascending=False)
    d["rk_ribbon"] = d[VB].rank(ascending=False)
    d["d_round"] = d.rk_round - d.rk_area
    d["d_ribbon"] = d.rk_ribbon - d.rk_area
    print(f"\n=== rank movers ({nm}); +ve = worse under volume ===")
    print(d.reindex(d.d_round.abs().sort_values(ascending=False).index)[
        ["label", "run", "rk_area", "rk_round", "rk_ribbon", "d_round", "d_ribbon", "ratio_round_all",
         "unatom_depth_round_um_all", "oof_vol_share_round"]].head(8).round(3).to_string(index=False))
    print(f"  mean |d_rank| round {d.d_round.abs().mean():.2f}, ribbon {d.d_ribbon.abs().mean():.2f}")
    print(f"\n=== top 5 ({nm}) ===")
    t = pd.DataFrame({
        "area": d.sort_values(A, ascending=False).head(5).apply(lambda r: f"{r.label} ({r.gas:.0f}/{r.rpm:.0f}/{r.feed:.0f}/{r.orifice}) {r[A]:.1f}%", axis=1).values,
        "vol_round": d.sort_values(VR, ascending=False).head(5).apply(lambda r: f"{r.label} ({r.gas:.0f}/{r.rpm:.0f}/{r.feed:.0f}/{r.orifice}) {r[VR]:.2f}%", axis=1).values,
        "vol_ribbon": d.sort_values(VB, ascending=False).head(5).apply(lambda r: f"{r.label} {r[VB]:.2f}%", axis=1).values,
    })
    print(t.to_string(index=False))

print("\n=== does the volume/area ratio track the factors? Spearman ===")
for nm, d in [("all 33", df), ("FC", FC)]:
    for y in ["ratio_round_all", "ratio_ribbon_all"]:
        print(f"  {nm} {y}: " + "; ".join(f"{f} {sp(f, y, d)}" for f in ["gas", "feed", "orifice", "rpm"]))
    print(f"  {nm} ratio_round vs area: {sp(A, 'ratio_round_all', d)}; vs unatom depth: {sp('unatom_depth_round_um_all', 'ratio_round_all', d)}")

print("\n=== factor picture, flow-controlled runs: main-effect means per level (all frames) ===")
for f in ["gas", "rpm", "feed", "orifice"]:
    g = FC.groupby(f).agg(n=("run", "size"), area=(A, "mean"), vol_round=(VR, "mean"), vol_ribbon=(VB, "mean"))
    for c, col in [("area", A), ("vol_round", VR), ("vol_ribbon", VB)]:
        g[c + "_rel%"] = 100 * g[c] / FC[col].mean()
    print(f"-- {f}\n" + g.round(3).to_string())


def fit(d, y, logy=False):
    yy = np.log(d[y].values) if logy else d[y].values
    X = np.column_stack([np.ones(len(d))] + [
        (d[f] - (d[f].max() + d[f].min()) / 2) / ((d[f].max() - d[f].min()) / 2) for f in ["gas", "rpm", "feed", "orifice"]])
    b, *_ = np.linalg.lstsq(X, yy, rcond=None)
    res = yy - X @ b
    dof = len(d) - X.shape[1]
    s2 = res @ res / dof
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return b, se, 1 - res @ res / ((yy - yy.mean()) ** 2).sum()


FC22 = FC[FC.rpm > 0]
print(f"\n=== linear fit on FC runs excl. the 0 rpm control (n={len(FC22)}), factors coded -1..+1 over their FC range "
      f"(gas 7-11k, rpm 100-900, feed 3-5k, orifice 0.8-1.8); coef = half the low-to-high change, as % of the response mean (t) ===")
for y in [A, VR, VB, "af_P20", "af_vol_round_noP20", "af_area_s", "af_vol_round"]:
    b, se, r2 = fit(FC22, y)
    m = FC22[y].mean()
    print(f"  {y:22s} mean {m:7.3f}  R2 {r2:.2f}  " + "  ".join(
        f"{f} {100 * b[i + 1] / m:+6.1f}% (t={b[i + 1] / se[i + 1]:+.1f})" for i, f in enumerate(["gas", "rpm", "feed", "orifice"])))
print("  log-response fits (coef = half the low-to-high change in ln y):")
for y in [A, VR, VB]:
    b, se, r2 = fit(FC22, y, logy=True)
    print(f"  ln {y:19s} R2 {r2:.2f}  " + "  ".join(
        f"{f} {b[i + 1]:+.3f} (t={b[i + 1] / se[i + 1]:+.1f})" for i, f in enumerate(["gas", "rpm", "feed", "orifice"])))

print("\n=== droplet / compact-piece volume cross-checks (30-frame sample) ===")
print(df[["drop_daves_over_sphere", "drop_daves_over_sphere_round", "drop_daves_over_prolate_expect",
          "compact_daves_over_round", "n_compact", "oof_vol_share_round", "oof_area_share_s"]].describe().round(3).to_string())
print("oof volume share by run (top 8):")
print(df.sort_values("oof_vol_share_round", ascending=False)[["label", "run", "oof_vol_share_round", "oof_area_share_s",
      "af_vol_round", "af_vol_round_no_oof"]].head(8).round(3).to_string(index=False))

print("\n=== H1: window ===")
wd = ["P10", "P20", "P40", "DARK70", "P20_and_DARKdil"]
for k in wd:
    print(f"  {k:16s} runs with any window px {int((df['win_px_' + k] > 0).sum())}; Spearman af vs af_without: all {sp(A, 'af_' + k, df)}; FC {sp(A, 'af_' + k, FC)};"
          f"  median |delta| {df['daf_' + k].abs().median():.2f} pt, max {df['daf_' + k].abs().max():.2f} pt")
cols = ["label", "run", A] + sum([[f"win_pct_{k}", f"liq_in_win_pct_{k}", f"daf_{k}"] for k in ["P10", "P20", "P40", "DARK70"]], [])
print(df.sort_values("daf_P20", ascending=False)[cols].round(2).to_string(index=False))
for k in ["P10", "P20", "DARK70"]:
    d = df.copy()
    d["rk0"] = d[A].rank(ascending=False)
    d["rk1"] = d["af_" + k].rank(ascending=False)
    d["drk"] = d.rk1 - d.rk0
    print(f"  rank changes under {k}: {int((d.drk != 0).sum())} runs move; max |move| {d.drk.abs().max():.0f}; "
          + ", ".join(f"{r.label} {r.rk0:.0f}->{r.rk1:.0f}" for _, r in d[d.drk.abs() >= 2].iterrows()))
print("\n=== timing ===")
print(f"  Mac (4 procs sharing the LaCie): read {df.t_io_s.mean():.3f} s/frame, measure_frame {df.t_measure_s.mean():.3f} s/frame, "
      f"volume (sample) {df.t_vol_s.mean():.3f} s/frame")
print(f"  Windows liquid stage (classical_summary elapsed_s): {df.windows_liquid_s.sum():.0f} s total, "
      f"{df.windows_liquid_s.mean():.1f} s/run, {df.windows_liquid_s.sum() / df.n_frames.sum():.3f} s/frame")
