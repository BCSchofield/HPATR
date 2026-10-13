"""Collect the per-run numbers into one CSV: b2_summary.csv (next to this script)."""
import csv, json
import numpy as np
from common import RUNS, CONTROL, HERE, SCCM

R = HERE / "results"
piv = json.loads((R / "piv_summary.json").read_text())
nn = json.loads((R / "nn_summary.json").read_text())
sec = json.loads((R / "nn_sector.json").read_text())
bs = json.loads((R / "blur_summary.json").read_text())
bb = json.loads((R / "blur_bounds.json").read_text())
phys = {r["run"]: r for r in csv.DictReader(open(R / "physics_estimates.csv"))}
rows = []
for t in RUNS + [CONTROL]:
    p = piv[t]
    lagkeys = [k for k in p if k.startswith("lag1")]
    ctrlkeys = [k for k in p if k.startswith("ctrl")]
    r = dict(run=t, gas_sccm=SCCM[t],
             droplet_blobs_per_frame=round(nn[t]["n_droplet_blobs_per_frame"], 1),
             piv_ens_snr_lag1=" / ".join(f"{p[k]['ens_full']['snr']:.1f}" for k in lagkeys),
             piv_ens_peak_lag1_dy_dx=" / ".join(f"({p[k]['ens_full']['dy']},{p[k]['ens_full']['dx']})" for k in lagkeys),
             piv_ens_snr_controls=" / ".join(f"{p[k]['ens_full']['snr']:.1f}" for k in ctrlkeys),
             piv_full_best_ncc_median_lag1=round(float(np.median(p[lagkeys[0]]["full_pk"])), 3),
             piv_full_best_ncc_median_ctrl=round(float(np.median(p["ctrl_lag50"]["full_pk"])), 3),
             piv_win256_peak_median_lag1=round(float(np.median(p[lagkeys[0]]["win_pk"])), 3),
             piv_win256_peak_median_ctrl=round(float(np.median(p["ctrl_lag50"]["win_pk"])), 3),
             persist_r10_lag1=round(nn[t]["lag1"]["persistence"]["10"], 3), persist_r10_ctrl=round(nn[t]["ctrl"]["persistence"]["10"], 3),
             persist_r50_lag1=round(nn[t]["lag1"]["persistence"]["50"], 3), persist_r50_ctrl=round(nn[t]["ctrl"]["persistence"]["50"], 3),
             persist_r100_lag1=round(nn[t]["lag1"]["persistence"]["100"], 3), persist_r100_ctrl=round(nn[t]["ctrl"]["persistence"]["100"], 3),
             nn_hist_max_excess_z=round(nn[t]["max_excess_z"], 1))
    if t in sec:
        e, s = sec[t]["excess_per_pair"]
        r.update(downstream_excess_per_pair=f"{e:+.1f} +- {s:.1f}", downstream_upper95_per_pair=round(sec[t]["upper95_reseen_per_pair"], 1),
                 expected_if_all_at_2ms=round(sec[t]["expected_reseen_per_pair_if_all_move_at_v"]["2.0"], 1),
                 expected_if_all_at_3ms=round(sec[t]["expected_reseen_per_pair_if_all_move_at_v"]["3.0"], 1))
    b = bs[t]
    r.update(n_infocus_droplets_blur=b["n_droplets"], D_flow_px2=f"{b['D_flow_median'][0]:.3f} [{b['D_flow_median'][1]:.3f},{b['D_flow_median'][2]:.3f}]",
             D_diag_px2=f"{b['D_diag_median'][0]:.3f}", edge_along_px=round(b["edge_along_median"][0], 3), edge_across_px=round(b["edge_across_median"][0], 3),
             anisotropy_axis_deg_from_vertical=round(b["elong_axis_deg_from_vertical"], 1),
             ligament_signed_median_angle_deg=None)
    if t in bb:
        r.update(matched_D_flow_minus_control_px2=f"{bb[t]['D_flow_minus_control'][0]:+.3f} [{bb[t]['D_flow_minus_control'][1]:+.3f},{bb[t]['D_flow_minus_control'][2]:+.3f}]",
                 blur_L_point_px=round(bb[t]["L_px_point"], 2), blur_L_upper95_px=round(bb[t]["L_px_upper95"], 2),
                 blur_v_point_ms=round(bb[t]["v_point_ms"], 1), blur_v_upper95_ms=round(bb[t]["v_upper95_ms"], 1))
    if t in phys:
        ph = phys[t]
        r.update(P0_barA=ph["P0_barA_cam"], u_gas_exit_ambient_density_ms=ph["u_gas_ambient_ms"], u_gas_exit_P0_density_ms=ph["u_gas_at_P0_ms"],
                 jet_u_c_100mm_ms=ph["u_c_100mm_ms"], jet_u_c_300mm_ms=ph["u_c_300mm_ms"], jet_x_for_2ms_m=ph["x_where_u_c_2ms_m"])
    rows.append(r)
lig = json.loads((R / "ligaments.json").read_text())
for r in rows:
    a = np.array([x["ang"] for x in lig[r["run"]] if x["aspect"] > 4])
    r["ligament_signed_median_angle_deg"] = round(float(np.median(a)), 1) if len(a) else None
keys = []
for r in rows:
    for k in r:
        if k not in keys:
            keys.append(k)
with open(HERE / "b2_summary.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
for r in rows:
    print(r)
