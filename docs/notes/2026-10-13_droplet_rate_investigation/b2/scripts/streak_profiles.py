"""Grey-level shape of small objects vs contrast, to test the motion-streak reading of the faint dashes.

For every small object (seed T < 0.85, grow T < 0.93, d_eq 2-12 px, off border, isolated):
  grey moments of w = clip(1 - T, 0) in the mask dilated by 2 px -> lambda1, lambda2, axis angle.
  L_apparent = sqrt(12 (lambda1 - lambda2))   [px]  (= box-blur length if the object were a round droplet)
  width_fwhm = 2.355 sqrt(lambda2)
Grouped by contrast (T_min) and by alignment with the flow axis. If faint dashes are motion streaks of
small droplets: L_apparent rises as contrast falls, only along the flow axis, and the effect is absent
in the slow dribble control. Output: results/small_objects_<tag>.csv and a zoomed gallery with profiles.
"""
import csv
import numpy as np
import cv2
from scipy import ndimage as ndi
from common import load, segment, RUNS, CONTROL, HERE

OUT = HERE / "results"; LOOK = HERE / "look"
AXIS = -14.0   # deg from vertical: elongation axis of in-focus droplets (blur.py), ~ flow axis


def measure(T, lab, b):
    y0, y1, x0, x1 = int(b["y0"]) - 4, int(b["y1"]) + 4, int(b["x0"]) - 4, int(b["x1"]) + 4
    H, W = T.shape
    if y0 < 0 or x0 < 0 or y1 > H or x1 > W:
        return None
    m = ndi.binary_dilation(lab[y0:y1, x0:x1] == b["label"], iterations=2)
    w = np.clip(1 - T[y0:y1, x0:x1], 0, None) * m
    s = w.sum()
    yy, xx = np.mgrid[y0:y1, x0:x1]
    cy = (w * yy).sum() / s; cx = (w * xx).sum() / s
    myy = (w * (yy - cy) ** 2).sum() / s; mxx = (w * (xx - cx) ** 2).sum() / s; mxy = (w * (yy - cy) * (xx - cx)).sum() / s
    tr = myy + mxx; dd = np.sqrt(max((myy - mxx) ** 2 / 4 + mxy ** 2, 0))
    l1, l2 = tr / 2 + dd, tr / 2 - dd
    ang = 0.5 * np.degrees(np.arctan2(2 * mxy, myy - mxx))
    return dict(cy=cy, cx=cx, tmin=b["tmin"], d_eq=b["d_eq"], l1=l1, l2=l2, ang=ang,
                L_app=float(np.sqrt(12 * max(l1 - l2, 0))), width_fwhm=float(2.355 * np.sqrt(max(l2, 0))))


rows_all = {}
for tag in RUNS + [CONTROL]:
    D = load(tag)
    rows = []
    gallery = []
    for bname, st in D.items():
        for i, T in enumerate(st):
            lab, bl = segment(T, seed=0.85, grow=0.93)
            cents = np.array([(b["cy"], b["cx"]) for b in bl]).reshape(-1, 2)
            for b in bl:
                if b["border"] or not (2 <= b["d_eq"] <= 12):
                    continue
                d = np.sqrt(((cents - [b["cy"], b["cx"]]) ** 2).sum(1))
                if (d < b["d_eq"] + 12).sum() > 1:
                    continue
                r = measure(T, lab, b)
                if r is None:
                    continue
                r["rel_ang"] = (r["ang"] - AXIS + 90) % 180 - 90
                r["burst"] = bname; r["frame"] = i
                rows.append(r)
                if (0.65 <= r["tmin"] <= 0.85 and abs(r["rel_ang"]) < 20 and r["L_app"] > 4 and len(gallery) < 12):
                    cy, cx = int(round(r["cy"])), int(round(r["cx"]))
                    c = T[cy - 12:cy + 12, cx - 12:cx + 12]
                    if c.shape == (24, 24):
                        gallery.append(c)
    rows_all[tag] = rows
    with open(OUT / f"small_objects_{tag}.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader(); wr.writerows(rows)
    if gallery:
        g = np.hstack(gallery)
        img = (np.clip((g - 0.55) / 0.5, 0, 1) * 255).astype(np.uint8)
        cv2.imwrite(str(LOOK / f"dash_zoom_{tag}.png"), cv2.resize(img, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST))
    # summary by contrast class
    tm = np.array([r["tmin"] for r in rows]); La = np.array([r["L_app"] for r in rows])
    ra = np.array([r["rel_ang"] for r in rows]); wd = np.array([r["width_fwhm"] for r in rows])
    print(f"== {tag}: {len(rows)} small isolated objects")
    for lo, hi in [(0.0, 0.4), (0.4, 0.6), (0.6, 0.75), (0.75, 0.85)]:
        s = (tm >= lo) & (tm < hi)
        if s.sum() < 5:
            print(f"   T_min {lo:.2f}-{hi:.2f}: n={s.sum()}"); continue
        al = s & (np.abs(ra) < 20); pe = s & (np.abs(ra) > 70)
        print(f"   T_min {lo:.2f}-{hi:.2f}: n={s.sum():4d}  median L_app {np.median(La[s]):.2f} px  "
              f"frac aligned(+-20deg) {al.sum()/s.sum():.2f}  perp {pe.sum()/s.sum():.2f}  "
              f"L_app aligned median {np.median(La[al]) if al.sum() else np.nan:.2f}  "
              f"width_fwhm median {np.median(wd[s]):.2f}  frac L_app>4 {np.mean(La[s] > 4):.2f}")
