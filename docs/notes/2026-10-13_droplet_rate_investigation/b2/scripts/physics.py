"""Order-of-magnitude droplet/gas velocity at the measurement station from the flow set points.

Gas: Alicat sccm at 25 C / 1 atm (N2, rho_std = 1.145 kg/m3). Liquid: syringe 20.27 mm bore,
6800 steps/mm, 4000 steps/s. Orifice 1.2 mm. P0 = median pressure inside the camera window
(run_summary.xlsx, read-only). Far field: round turbulent jet, momentum-equivalent form
  u_c(x) = B * sqrt(4 J / (pi rho_a)) / x,   B = 6.0 (5.8-6.2 in the literature),
with the exit momentum flux J bracketed by two exit velocities (gas at P0 density, gas at ambient
density) applied to the whole mass flow (no slip). Station distance x is NOT recorded anywhere.
"""
import csv, json
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = Path("/Volumes/LaCie/Experiments/2026/10/12")
RUNS = {"low_7000": ("135146_7000sccm_500rpm_4000sps_or1.2_bh0.5", 7000),
        "centre_9000": ("130918_9000sccm_500rpm_4000sps_or1.2_bh0.5", 9000),
        "high_11000": ("125754_11000sccm_500rpm_4000sps_or1.2_bh0.5", 11000)}
RHO_STD = 1.145; RHO_A = 1.18; RHO_L = 1070.0; PA = 1.01325
D_OR = 1.2e-3; A_OR = np.pi * (D_OR / 2) ** 2
BORE = 20.27e-3; STEPS_MM = 6800.0; SPS = 4000.0
CP, GAM, T0 = 1040.0, 1.4, 298.15
B = 6.0
XS = [0.05, 0.10, 0.20, 0.30]

q_l = np.pi * (BORE / 2) ** 2 * (SPS / STEPS_MM) * 1e-3     # m3/s
m_l = q_l * RHO_L
rows = []
for tag, (run, sccm) in RUNS.items():
    pr = pd.read_excel(ROOT / run / "run_summary.xlsx", "Pressure")
    t0, t1 = pr["cam_start_1"].dropna().iloc[0], pr["cam_end_1"].dropna().iloc[0]
    w = pr[(pr.timestamps >= t0) & (pr.timestamps <= t1)]
    p0 = float(w.pressures.median()); qd = float(w.flows_sccm.median())
    q_std = qd * 1e-6 / 60.0
    m_g = q_std * RHO_STD
    u_amb = q_std / A_OR                    # gas at ambient density through the full orifice area
    u_p0 = u_amb * PA / p0                  # gas at P0 density
    u_isen = np.sqrt(2 * CP * T0 * (1 - (PA / p0) ** ((GAM - 1) / GAM)))   # ideal expansion, gas alone
    J_lo = (m_g + m_l) * u_p0; J_hi = (m_g + m_l) * u_amb
    r = dict(run=tag, sccm_set=sccm, sccm_delivered_cam=round(qd), P0_barA_cam=round(p0, 2),
             m_gas_g_s=round(m_g * 1e3, 4), m_liq_g_s=round(m_l * 1e3, 4), GLR=round(m_g / m_l, 3),
             q_liq_mL_min=round(q_l * 6e7, 2), u_liq_only_orifice_ms=round(q_l / A_OR, 3),
             u_gas_at_P0_ms=round(u_p0, 1), u_gas_ambient_ms=round(u_amb, 1), u_gas_isentropic_ms=round(u_isen, 0),
             J_low_N=round(J_lo, 4), J_high_N=round(J_hi, 4))
    for x in XS:
        lo = B * np.sqrt(4 * J_lo / (np.pi * RHO_A)) / x; hi = B * np.sqrt(4 * J_hi / (np.pi * RHO_A)) / x
        r[f"u_c_{int(x*1000)}mm_ms"] = f"{lo:.1f}-{hi:.1f}"
    xlo = B * np.sqrt(4 * J_lo / (np.pi * RHO_A)) / 2.0; xhi = B * np.sqrt(4 * J_hi / (np.pi * RHO_A)) / 2.0
    r["x_where_u_c_2ms_m"] = f"{xlo:.2f}-{xhi:.2f}"
    rows.append(r)
    print(r)
with open(HERE / "results" / "physics_estimates.csv", "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
