"""Shared helpers: load cached frames, transmission, blob segmentation."""
from pathlib import Path
import numpy as np
from scipy import ndimage as ndi

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
RUNS = ["low_7000", "centre_9000", "high_11000"]
SCCM = {"low_7000": 7000, "centre_9000": 9000, "high_11000": 11000, "dribble_C3": 33}
CONTROL = "dribble_C3"   # 0.5 mm gas-starved run (33 sccm delivered): slow mist, used as a zero-blur / trackable control
DT = 1 / 390.0          # s between frames
PX = 10e-6              # m per px
EXPO = 4e-6             # s exposure


def load(tag):
    bg = np.load(CACHE / f"{tag}_bg.npy").astype(np.float32)
    bg = np.maximum(bg, 1.0)
    out = {}
    for b in "ABCD":
        f = CACHE / f"{tag}_{b}.npy"
        if not f.exists():
            continue
        st = np.load(f).astype(np.float32)
        out[b] = st / bg[None]
    return out


def segment(T, seed=0.6, grow=0.85):
    """Hysteresis dark-blob segmentation of one transmission frame.
    Returns label image and a list of dicts (one per component)."""
    lab_g, n = ndi.label(T < grow, structure=np.ones((3, 3)))
    seeded = np.unique(lab_g[T < seed])
    seeded = seeded[seeded > 0]
    keep = np.zeros(n + 1, bool)
    keep[seeded] = True
    mask = keep[lab_g]
    lab, n2 = ndi.label(mask, structure=np.ones((3, 3)))
    objs = ndi.find_objects(lab)
    blobs = []
    H, W = T.shape
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        m = lab[sl] == i
        area = int(m.sum())
        ys, xs = np.nonzero(m)
        ys = ys + sl[0].start
        xs = xs + sl[1].start
        tmin = float(T[sl][m].min())
        d_eq = 2 * np.sqrt(area / np.pi)
        border = (sl[0].start == 0 or sl[1].start == 0 or sl[0].stop == H or sl[1].stop == W)
        # binary second moments (orientation / elongation of the mask)
        cy, cx = ys.mean(), xs.mean()
        myy = ((ys - cy) ** 2).mean(); mxx = ((xs - cx) ** 2).mean(); mxy = ((ys - cy) * (xs - cx)).mean()
        tr = myy + mxx; det = myy * mxx - mxy ** 2
        l1 = tr / 2 + np.sqrt(max(tr ** 2 / 4 - det, 0)); l2 = tr / 2 - np.sqrt(max(tr ** 2 / 4 - det, 0))
        # angle of major axis from the image vertical (deg, 0 = vertical, +-90 = horizontal)
        ang = 0.5 * np.degrees(np.arctan2(2 * mxy, myy - mxx))
        blobs.append(dict(label=i, area=area, d_eq=d_eq, cy=cy, cx=cx, tmin=tmin, border=border,
                          major=4 * np.sqrt(max(l1, 0)), minor=4 * np.sqrt(max(l2, 0)), ang_from_vertical=ang,
                          y0=sl[0].start, y1=sl[0].stop, x0=sl[1].start, x1=sl[1].stop))
    return lab, blobs
