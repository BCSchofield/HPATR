"""Velocity bounds from the blur measurements, size/contrast-matched against the slow dribble control.

Motion blur of length L (px) along the image vertical adds L^2/12 to mu_yy, so
  D_flow(spray) - D_flow(control) = L^2/12 + (shape difference)  ->  L <= sqrt(12 * upper CI of the difference)
(an upper bound: any extra shape anisotropy of spray fragments is counted as blur).
v = L * 10 um / 4 us = 2.5 m/s per px.
"""
import json
import numpy as np
from common import RUNS, CONTROL, HERE, SCCM

OUT = HERE / "results"
dr = json.loads((OUT / "blur_droplets.json").read_text())
rng = np.random.default_rng(0)


def arr(tag, key, sel):
    return np.array([x[key] for x in dr[tag] if sel(x)], float)


def boot_diff(a, b, n=4000):
    a = a[np.isfinite(a)]; b = b[np.isfinite(b)]
    d = [np.median(rng.choice(a, len(a))) - np.median(rng.choice(b, len(b))) for _ in range(n)]
    return float(np.median(a) - np.median(b)), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


sel = lambda x: 3 <= x["d_eq"] <= 5.5 and 0.2 <= x["tmin"] < 0.5
out = {}
ctl = arr(CONTROL, "D_flow", sel)
ctl_e = arr(CONTROL, "e_top", sel), arr(CONTROL, "e_bot", sel), arr(CONTROL, "e_lft", sel), arr(CONTROL, "e_rgt", sel)
ctl_ed = np.nanmean([ctl_e[0], ctl_e[1]], 0) - np.nanmean([ctl_e[2], ctl_e[3]], 0)
print(f"control ({CONTROL}) matched droplets n={len(ctl)}  D_flow median {np.median(ctl):.3f} px^2  "
      f"edge along-across {np.nanmedian(ctl_ed):.3f} px")
for tag in RUNS:
    a = arr(tag, "D_flow", sel)
    e = [arr(tag, k, sel) for k in ("e_top", "e_bot", "e_lft", "e_rgt")]
    ed = np.nanmean([e[0], e[1]], 0) - np.nanmean([e[2], e[3]], 0)
    d, lo, hi = boot_diff(a, ctl)
    de, elo, ehi = boot_diff(ed, ctl_ed)
    L_hi = np.sqrt(12 * max(hi, 0)); L_mid = np.sqrt(12 * max(d, 0))
    out[tag] = dict(sccm=SCCM[tag], n_matched=int(len(a)), D_flow_median=float(np.median(a)),
                    D_flow_minus_control=[d, lo, hi], L_px_point=float(L_mid), L_px_upper95=float(L_hi),
                    v_point_ms=float(2.5 * L_mid), v_upper95_ms=float(2.5 * L_hi),
                    edge_diff_minus_control=[de, elo, ehi])
    print(f"{tag:12s} n={len(a):4d}  D_flow {np.median(a):.3f}  minus control {d:+.3f} [{lo:+.3f}, {hi:+.3f}] px^2  "
          f"-> L <= {L_hi:.2f} px (point {L_mid:.2f})  -> v <= {2.5*L_hi:.1f} m/s (point {2.5*L_mid:.1f})   "
          f"edge-diff minus control {de:+.3f} [{elo:+.3f}, {ehi:+.3f}] px")

# gas trend among the three spray runs (all in-focus droplets 3-25 px, as blur.py)
selall = lambda x: True
med = {t: np.median(arr(t, "D_flow", selall)) for t in RUNS}
bs = {t: [np.median(rng.choice(arr(t, "D_flow", selall), len(arr(t, "D_flow", selall)))) for _ in range(2000)] for t in RUNS}
diff_hi_lo = np.array(bs["high_11000"]) - np.array(bs["low_7000"])
d_obs = med["high_11000"] - med["low_7000"]
ci = np.percentile(diff_hi_lo, [2.5, 97.5])
# if droplet velocity scaled with gas flow (v = k Q): D(11000) - D(7000) = (k*2.5um.. ) -> L^2/12 diff
# L(Q) = c Q  ->  diff = c^2 (11^2 - 7^2)/12  (Q in 1000 sccm)  ->  c <= sqrt(12*ci_hi/72)
c_hi = np.sqrt(12 * max(ci[1], 0) / (11 ** 2 - 7 ** 2))
out["gas_trend"] = dict(D_flow_median={t: float(med[t]) for t in RUNS},
                        high_minus_low=[float(d_obs), float(ci[0]), float(ci[1])],
                        if_v_proportional_to_gas_L_per_ksccm_upper95=float(c_hi),
                        implied_v_upper95_at_9000_ms=float(2.5 * c_hi * 9))
print("gas trend: D_flow medians", {t: round(float(m), 3) for t, m in med.items()},
      f" 11000-7000 = {d_obs:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}] px^2;  if v ∝ gas flow: L <= {c_hi:.3f} px per 1000 sccm "
      f"-> v(9000) <= {2.5 * c_hi * 9:.1f} m/s")
(OUT / "blur_bounds.json").write_text(json.dumps(out, indent=1))
