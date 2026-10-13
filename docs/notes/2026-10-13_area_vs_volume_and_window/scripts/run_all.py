"""Pass over every analysed frame of every CCD run (READ-ONLY on the LaCie).

Per frame: classical_liquid.measure_frame UNCHANGED (masks captured), gate vs
classical_per_frame.csv, packed masks kept for the persistence pass.
On the 30-frame sample: F2 volumes.
Writes only to OUT (scratch)."""
import csv
import glob
import json
import sys
import time
import traceback
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import os
LIMIT = int(os.environ.get("F2H1_LIMIT", "0"))
OUT = HERE / ("runs_test" if LIMIT else "runs")
OUT.mkdir(exist_ok=True)
DAY = "/Volumes/LaCie/Experiments/2026/10/12/"
N_SAMPLE = 30
P_LEVELS = (10, 20, 40)


def sample_idx(n, k=N_SAMPLE):
    return set(np.unique(np.round(np.linspace(0, n - 1, k)).astype(int)).tolist())


def do_run(run_dir):
    import f2h1_core as C
    from classical_liquid import measure_frame
    import cv2
    from scipy import ndimage as ndi

    name = Path(run_dir).name
    if (OUT / f"{name}_done.json").exists():
        return name, "skip"
    cap = C.Capture()
    cap.install()
    t_start = time.time()
    R = C.load_run(run_dir)
    if LIMIT:
        R.ids = R.ids[:LIMIT]
    ref = {r["frame"]: r for r in csv.DictReader(open(R.ana / "liquid_0.30" / "classical_per_frame.csv"))}
    n = len(R.ids)
    samp = sample_idx(n)
    H, W = R.bg.shape
    pers = np.zeros((H, W), np.uint16)
    pers_tot = np.zeros((H, W), np.uint16)
    packed_u, packed_d, frames = [], [], []
    rows, srows = [], []
    for k, img_id in enumerate(R.ids):
        t0 = time.time()
        stem, T = C.read_T(R, img_id)
        t_io = time.time() - t0
        if T is None:
            continue
        t1 = time.time()
        row, _, _, _, unatom = measure_frame(T, R.by_img.get(img_id, []), R.args)
        t_meas = time.time() - t1
        dmask, liquid, oof = cap.dmask, cap.liquid, cap.oof
        total = unatom | dmask
        rr = ref.get(stem)
        match = (rr is not None and row["droplet_px"] == int(rr["droplet_px"])
                 and row["total_liquid_px"] == int(rr["total_liquid_px"])
                 and int(total.sum()) == row["total_liquid_px"])
        oof_only = unatom & oof & ~liquid
        pers += unatom
        pers_tot += total
        packed_u.append(np.packbits(unatom))
        packed_d.append(np.packbits(dmask))
        frames.append(stem)
        rows.append(dict(frame=stem, k=k, droplet_px=row["droplet_px"], total_px=row["total_liquid_px"],
                         unatom_px=row["unatomised_px"], oof_only_px=int(oof_only.sum()),
                         ref_droplet_px=rr["droplet_px"] if rr else "", ref_total_px=rr["total_liquid_px"] if rr else "",
                         match=int(match), t_io=round(t_io, 4), t_measure=round(t_meas, 4)))
        if k in samp:
            t2 = time.time()
            Vd, Ad, acc = C.droplet_volumes(dmask)
            rnd, rib, Rm, ls = C.chord_maps(unatom)
            c_s, c_d, c_n = C.compact_daves_check(ndi.binary_fill_holes(unatom), rnd, ls)
            t_vol = time.time() - t2
            srows.append(dict(frame=stem, k=k, droplet_px=row["droplet_px"], total_px=row["total_liquid_px"],
                              unatom_px=int(unatom.sum()), oof_only_px=int(oof_only.sum()),
                              V_drop=Vd, V_un_round=float(rnd[unatom].sum()), V_un_ribbon=float(rib[unatom].sum()),
                              V_oof_round=float(rnd[oof_only].sum()), V_oof_ribbon=float(rib[oof_only].sum()),
                              drop_sph_sub=acc[0], drop_daves_sub=acc[1], n_drop_sub=int(acc[2]),
                              drop_sph_round=acc[3], drop_daves_round=acc[4], n_drop_round=int(acc[5]), drop_prolate_expect=acc[6],
                              compact_round=c_s, compact_daves=c_d, n_compact=c_n,
                              R_area_mean=float(Rm[unatom].mean()) if unatom.any() else 0.0,
                              t_vol=round(t_vol, 3)))
    nf = len(frames)
    # ---- H1: window masks ----
    bg = R.bg
    dark = bg < 0.70 * np.median(bg)
    defs = {f"P{p}": pers >= np.ceil(p / 100.0 * nf) for p in P_LEVELS}
    defs["DARK70"] = dark
    dark_dil = cv2.dilate(dark.astype(np.uint8), np.ones((11, 11), np.uint8)).astype(bool)
    defs["P20_and_DARKdil"] = defs["P20"] & dark_dil
    for i, r in enumerate(rows):
        u = np.unpackbits(packed_u[i])[:H * W].reshape(H, W).astype(bool)
        d = np.unpackbits(packed_d[i])[:H * W].reshape(H, W).astype(bool)
        t = u | d
        for key, m in defs.items():
            r[f"dW_{key}"] = int((d & m).sum())
            r[f"tW_{key}"] = int((t & m).sum())
    # save
    with open(OUT / f"{name}_frames.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(OUT / f"{name}_sample.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(srows[0].keys()))
        w.writeheader()
        w.writerows(srows)
    np.savez_compressed(OUT / f"{name}_masks.npz", unatom=np.stack(packed_u), dmask=np.stack(packed_d),
                        frames=np.array(frames), pers=pers, pers_tot=pers_tot, shape=np.array([H, W]))
    meta = dict(run=name, n_frames=nf, n_ids=n, elapsed_s=round(time.time() - t_start, 1),
                gate_all=int(sum(r["match"] for r in rows)),
                win_area={k: int(m.sum()) for k, m in defs.items()},
                windows_liquid_stage_s=R.summary.get("elapsed_s"),
                atomised_pct_pooled_summary=R.summary.get("atomised_pct_pooled"))
    (OUT / f"{name}_done.json").write_text(json.dumps(meta, indent=1))
    return name, meta


def safe(run_dir):
    try:
        return do_run(run_dir)
    except Exception:
        return Path(run_dir).name, "ERROR " + traceback.format_exc()


if __name__ == "__main__":
    runs = sorted(glob.glob(DAY + "1*_bh0.5"))
    if len(sys.argv) > 1:
        runs = [r for r in runs if any(a in r for a in sys.argv[2:])] if sys.argv[1] == "only" else runs
    nproc = 4
    t = time.time()
    with Pool(nproc) as p:
        for name, meta in p.imap_unordered(safe, runs):
            if isinstance(meta, dict):
                print(f"{time.time() - t:7.0f}s  {name}  frames {meta['n_frames']}  gate {meta['gate_all']}/{meta['n_frames']}  {meta['elapsed_s']}s", flush=True)
            else:
                print(f"{time.time() - t:7.0f}s  {name}  {meta}", flush=True)
    print("ALL DONE", flush=True)
