"""Contact sheet of the worst window runs: background median, persistence map,
one frame with the window mask outlined. Reads the LaCie, writes scratch only."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DAY = Path("/Volumes/LaCie/Experiments/2026/10/12")
df = pd.read_csv(HERE / "per_run_f2h1.csv")
key = sys.argv[1] if len(sys.argv) > 1 else "P20"
worst = df.reindex(df[f"daf_{key}"].abs().sort_values(ascending=False).index).head(4)
if not worst.run.str.startswith("142150").any():
    worst = pd.concat([df[df.run.str.startswith("142150")], worst.head(3)])
S = 0.42
tiles = []


def put(img, txt, y=20):
    cv2.putText(img, txt, (6, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, txt, (6, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


for _, r in worst.iterrows():
    raw = DAY / r.run / "shadowgraph" / "raw"
    z = np.load(HERE / "runs" / f"{r.run}_masks.npz")
    H, W = z["shape"]
    nf = len(z["frames"])
    bg = cv2.imread(str(raw / "background_median.tiff"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    v = np.clip((bg - 27) / (876 - 27) * 255, 0, 255).astype(np.uint8)
    a = cv2.cvtColor(v, cv2.COLOR_GRAY2BGR)
    dark = (bg < 0.70 * np.median(bg)).astype(np.uint8)
    cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(a, cnts, -1, (214, 120, 42), 3)
    pers = 100.0 * z["pers"] / nf
    p8 = np.clip(pers / 50.0 * 255, 0, 255).astype(np.uint8)
    b = cv2.applyColorMap(p8, cv2.COLORMAP_VIRIDIS)
    win = (z["pers"] >= np.ceil(0.20 * nf)).astype(np.uint8)
    wc, _ = cv2.findContours(win, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(b, wc, -1, (255, 255, 255), 2)
    fr = pd.read_csv(HERE / "runs" / f"{r.run}_frames.csv")
    k = int(fr[f"tW_{key}"].idxmax())
    stem = fr.frame[k]
    v8 = cv2.imread(str(raw / "frames" / "8bit" / f"{stem}.png"), cv2.IMREAD_UNCHANGED)
    c = cv2.cvtColor(v8, cv2.COLOR_GRAY2BGR) if v8.ndim == 2 else v8.copy()
    u = np.unpackbits(z["unatom"][k])[:H * W].reshape(H, W).astype(bool)
    c[u] = (0.55 * c[u] + 0.45 * np.array([52, 104, 235])).astype(np.uint8)   # orange fill (BGR)
    cv2.drawContours(c, wc, -1, (214, 120, 42), 3)                              # window outline, blue
    a, b, c = [cv2.resize(x, None, fx=S, fy=S, interpolation=cv2.INTER_AREA) for x in (a, b, c)]
    put(a, f"{r.label} {r.run[:6]} bg median; blue = bg<70% median")
    put(b, "persistence (share of frames un-atomised), 0-50%")
    put(b, f"white = >=20% ({100 * win.sum() / (H * W):.2f}% of frame)", 42)
    pa = 100 * fr.droplet_px[k] / fr.total_px[k] if fr.total_px[k] else float('nan')
    put(c, f"{stem}: orange un-atomised, blue P20 window")
    put(c, f"frame {pa:.1f}%; run {r.af_all:.2f}% -> {r[f'af_{key}']:.2f}% without window", 42)
    row = np.hstack([a, b, c])
    tiles.append(row)
sheet = np.vstack(tiles)
cv2.imwrite(str(HERE / f"contact_sheet_window_{key}.png"), sheet)
print("contact sheet", sheet.shape, worst[["label", "run", f"daf_{key}"]].to_string())
