"""Thumbnail grid of all 33 persistence maps (un-atomised share of frames)."""
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
df = pd.read_csv(HERE / "per_run_f2h1.csv").sort_values("order")
S = 0.16
tiles = []
for _, r in df.iterrows():
    z = np.load(HERE / "runs" / f"{r.run}_masks.npz")
    nf = len(z["frames"])
    p = np.clip(100.0 * z["pers"] / nf / 50.0 * 255, 0, 255).astype(np.uint8)
    t = cv2.resize(cv2.applyColorMap(p, cv2.COLORMAP_VIRIDIS), None, fx=S, fy=S, interpolation=cv2.INTER_AREA)
    txt = f"{r.label} {r.orifice}mm P20 {r.win_pct_P20:.1f}% d{r.daf_P20:+.1f}"
    cv2.putText(t, txt, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1, cv2.LINE_AA)
    tiles.append(t)
while len(tiles) % 6:
    tiles.append(np.zeros_like(tiles[0]))
rows = [np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]
cv2.imwrite(str(HERE / "persistence_all_runs.png"), np.vstack(rows))
print("ok")
