"""Volumes on ALL analysed frames from the saved masks (no LaCie frame reads;
background read only for the DARK70 window). Per-frame CSV per run."""
import glob
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
RUNS = HERE / "runs"
DAY = "/Volumes/LaCie/Experiments/2026/10/12/"


def one(name):
    import cv2
    import f2h1_core as C
    out_csv = RUNS / f"{name}_vol_all.csv"
    if out_csv.exists():
        return name, 0
    t0 = time.time()
    z = np.load(RUNS / f"{name}_masks.npz")
    H, W = z["shape"]
    frames = z["frames"]
    nf = len(frames)
    pers = z["pers"]
    bg = cv2.imread(DAY + name + "/shadowgraph/raw/background_median.tiff", cv2.IMREAD_UNCHANGED).astype(np.float32)
    wins = {"P20": pers >= np.ceil(0.20 * nf), "DARK70": bg < 0.70 * np.median(bg)}
    U, Dm = z["unatom"], z["dmask"]
    rows = []
    for k in range(nf):
        u = np.unpackbits(U[k])[:H * W].reshape(H, W).astype(bool)
        d = np.unpackbits(Dm[k])[:H * W].reshape(H, W).astype(bool)
        Vd, Ad, _ = C.droplet_volumes(d, daves_min_area=10 ** 9)
        rnd, rib, _, _ = C.chord_maps(u)
        r = dict(frame=frames[k], k=k, droplet_px=int(d.sum()), unatom_px=int(u.sum()), V_drop=Vd,
                 V_un_round=float(rnd[u].sum()), V_un_ribbon=float(rib[u].sum()))
        for key, m in wins.items():
            r[f"V_drop_no{key}"] = C.droplet_volumes(d & ~m, daves_min_area=10 ** 9)[0]
            r[f"V_un_round_no{key}"] = float(rnd[u & ~m].sum())
        rows.append(r)
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return name, time.time() - t0


if __name__ == "__main__":
    names = sorted(Path(p).name.replace("_done.json", "") for p in glob.glob(str(RUNS / "*_done.json")))
    t = time.time()
    with Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 10) as p:
        for name, s in p.imap_unordered(one, names):
            print(f"{time.time() - t:6.0f}s {name} {s:.0f}s", flush=True)
    print("VOL DONE", flush=True)
