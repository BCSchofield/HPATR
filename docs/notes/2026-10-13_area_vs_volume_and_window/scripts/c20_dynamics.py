"""C20 (142150): is the window blob static (divides out) or changing?
Per frame: how much of the blob is counted as un-atomised, and the raw
intensity / transmission inside the blob vs a ring around it."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
NAME = sys.argv[1] if len(sys.argv) > 1 else "142150_7000sccm_100rpm_3000sps_or1.8_bh0.5"
RUN = Path("/Volumes/LaCie/Experiments/2026/10/12") / NAME
raw = RUN / "shadowgraph" / "raw"
z = np.load(HERE / "runs" / f"{NAME}_masks.npz")
H, W = z["shape"]
frames = list(z["frames"])
bg = cv2.imread(str(raw / "background_median.tiff"), cv2.IMREAD_UNCHANGED).astype(np.float32)
dark = (bg < 0.70 * np.median(bg)).astype(np.uint8)
n, lab, st, cen = cv2.connectedComponentsWithStats(dark, 8)
# the blob = the largest dark component
i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
blob = lab == i
x, y, w, h, a = st[i]
print(f"blob: bbox x{x} y{y} w{w} h{h}, area {a} px ({a * 1e-4:.2f} mm2), centroid {cen[i].round(0)}, "
      f"bg min {bg[blob].min():.0f} vs bg median {np.median(bg):.0f}")
blob_dil = cv2.dilate(blob.astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool)
ring = blob_dil & ~cv2.dilate(blob.astype(np.uint8), np.ones((11, 11), np.uint8)).astype(bool)
core = cv2.erode(blob.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
fr = pd.read_csv(HERE / "runs" / f"{NAME}_frames.csv")
rows = []
for k, stem in enumerate(frames):
    u = np.unpackbits(z["unatom"][k])[:H * W].reshape(H, W).astype(bool)
    raw16 = cv2.imread(str(raw / "frames" / "16bit" / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    T = raw16 / np.maximum(bg, 1)
    ub = u & blob_dil
    if ub.any():
        ys, xs = np.nonzero(ub)
        cy, cx = ys.mean(), xs.mean()
    else:
        cy = cx = np.nan
    rows.append(dict(k=k, frame=stem, unatom_in_blob=int((u & blob).sum()), unatom_near_blob=int(ub.sum()),
                     blob_cover=float((u & blob).sum() / a), cy=cy, cx=cx,
                     raw_core=float(raw16[core].mean()), raw_ring=float(raw16[ring].mean()),
                     T_core=float(T[core].mean()), T_min_blob=float(T[blob_dil].min()),
                     T_ring=float(T[ring].mean()),
                     total_px=int(fr.total_px[k]), droplet_px=int(fr.droplet_px[k]), oof_only=int(fr.oof_only_px[k])))
d = pd.DataFrame(rows)
d.to_csv(HERE / f"c20_blob_per_frame_{NAME[:6]}.csv", index=False)
cnt = (d.blob_cover >= 0.5).sum()
print(f"frames {len(d)}; blob >=50% counted in {cnt} ({100 * cnt / len(d):.1f}%); >=10% in {(d.blob_cover >= 0.1).sum()}")
print(f"share of the run's un-atomised px that sits on/near the blob: "
      f"{d.unatom_near_blob.sum() / (d.total_px - d.droplet_px).sum():.3f}")
print("raw intensity in blob core over the run (deciles of frame order):")
d["dec"] = pd.cut(d.k, 10, labels=False)
print(d.groupby("dec").agg(k0=("k", "min"), raw_core=("raw_core", "mean"), raw_ring=("raw_ring", "mean"),
                           T_core=("T_core", "mean"), Tmin=("T_min_blob", "median"),
                           cover=("blob_cover", "mean"), n_counted=("blob_cover", lambda s: (s >= 0.5).sum())).round(3).to_string())
print("frames counted (>=50%):", d.loc[d.blob_cover >= 0.5, "k"].tolist())
print(f"bg core raw (median image): {bg[core].mean():.1f}; ring {bg[ring].mean():.1f}")
c = d[d.blob_cover >= 0.5]
if len(c):
    print(f"centroid of counted piece: cx {c.cx.mean():.0f}+-{c.cx.std():.0f}, cy {c.cy.mean():.0f}+-{c.cy.std():.0f}; "
          f"blob centroid {cen[i][0]:.0f},{cen[i][1]:.0f}; T_core when counted {c.T_core.mean():.3f} vs not {d[d.blob_cover < 0.1].T_core.mean():.3f}")
