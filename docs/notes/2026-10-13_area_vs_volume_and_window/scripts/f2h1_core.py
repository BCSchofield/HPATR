"""F2 + H1 core: rebuild classical_liquid masks with the pipeline's own code,
then volume (F2) and persistence/window (H1) measures. READ-ONLY on the LaCie."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.morphology import skeletonize

REPO = Path("/Users/benschofield/Documents/GitHub/HPATR")
sys.path.insert(0, str(REPO / "AI" / "Real_Data_Code"))
import classical_liquid as cl  # noqa: E402
from measure_run import SPLIT_UM  # noqa: E402


def make_args(prov):
    """argparse namespace as classical_liquid.main builds it for the batch call
    (--root --out-dir --score-thresh 0.30 --sharpness-rule [--images-mode extremes])."""
    return SimpleNamespace(
        seed=prov.get("seed_thr", cl.SEED_THR),
        ceiling=prov.get("ceiling_thr", cl.CEILING_THR),
        min_area=prov.get("min_area_px", cl.MIN_AREA),
        droplet_cover=prov.get("droplet_cover", cl.DROPLET_COVER),
        droplet_max_extent=prov.get("droplet_max_extent", cl.DROPLET_MAX_EXTENT),
        score_thresh=prov.get("score_threshold", 0.30),
        classical_only=bool(prov.get("classical_only", False)),
        sharpness_rule=bool(prov.get("sharpness_rule", True)),
        focus_max=0.70,
        droplet_ring=10,
        split_um=SPLIT_UM,
        core_estimator="robust",
        no_sizer=False,
    )


class Capture:
    """Wrap cl.hysteresis / cl.model_masks so measure_frame runs UNCHANGED and we
    still get its intermediate masks."""

    def __init__(self):
        self.liquid = None
        self.dmask = None
        self.oof = None
        self._h = cl.hysteresis
        self._m = cl.model_masks

    def install(self):
        cap = self

        def h(*a, **k):
            out = cap._h(*a, **k)
            cap.liquid = out[0]
            return out

        def m(*a, **k):
            out = cap._m(*a, **k)
            cap.dmask, cap.oof = out
            return out
        cl.hysteresis = h
        cl.model_masks = m


def load_run(run):
    run = Path(run)
    raw = run / "shadowgraph" / "raw"
    ana = run / "shadowgraph" / "analysis"
    pred = ana / "predictions_crop.json"
    if not pred.exists():
        pred = ana / "predictions.json"
    summ = json.loads((ana / "liquid_0.30" / "classical_summary.json").read_text())
    args = make_args(summ["provenance"])
    bg = cv2.imread(str(raw / "background_median.tiff"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    preds = json.loads(pred.read_text())
    inst = json.loads((raw / "instances.json").read_text())
    stem_by_id = {im["id"]: im["file_name"].rsplit(".", 1)[0] for im in inst["images"]}
    by_img = {}
    for d in preds:
        if d["score"] >= args.score_thresh:
            by_img.setdefault(d["image_id"], []).append(d)
    ids = sorted(stem_by_id)
    return SimpleNamespace(run=run, raw=raw, ana=ana, args=args, bg=bg, by_img=by_img,
                           ids=ids, stem_by_id=stem_by_id, summary=summ)


def read_T(R, img_id):
    stem = R.stem_by_id[img_id]
    raw16 = cv2.imread(str(R.raw / "frames" / "16bit" / f"{stem}.tiff"), cv2.IMREAD_UNCHANGED)
    if raw16 is None:
        return stem, None
    return stem, raw16.astype(np.float32) / np.maximum(R.bg, 1.0)


# ----------------------------------------------------------------------------
# volumes (all in px^3; 1 px = 10 um)
# ----------------------------------------------------------------------------
SUB = 4  # sub-pixel supersampling for Daves slicing


def daves_volume(ys, xs):
    """Blaisot & Yon 2005 s3.4 / Daves 1993: slice perpendicular to the
    principal axis, each 1-px slab a disc of diameter = slab width.
    Pixels supersampled SUBxSUB so the slab widths do not alias."""
    n = ys.size
    if n == 0:
        return 0.0
    off = (np.arange(SUB) + 0.5) / SUB - 0.5
    oy, ox = np.meshgrid(off, off, indexing="ij")
    Y = (ys[:, None] + oy.ravel()[None, :]).ravel()
    X = (xs[:, None] + ox.ravel()[None, :]).ravel()
    cy, cx = Y.mean(), X.mean()
    if n < 3:
        # degenerate: treat as sphere of equal area
        d = np.sqrt(4 * n / np.pi)
        return np.pi * d ** 3 / 6
    cov = np.cov(np.vstack([Y - cy, X - cx]))
    w, v = np.linalg.eigh(cov)
    u = v[:, np.argmax(w)]
    s = (Y - cy) * u[0] + (X - cx) * u[1]
    b = np.floor(s - s.min()).astype(int)
    width = np.bincount(b) / (SUB * SUB)  # area in a 1-px slab = width x 1
    return float(np.sum(np.pi * (width / 2.0) ** 2))


def droplet_volumes(dmask, daves_min_area=20):
    """Per connected component of dmask: sphere from the area-equivalent
    diameter. Daves cross-check on components >= daves_min_area px."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dmask.astype(np.uint8), 8)
    if n <= 1:
        return 0.0, 0, np.zeros(7)
    A = stats[1:, cv2.CC_STAT_AREA].astype(float)
    d = np.sqrt(4 * A / np.pi)
    v_sph = np.pi * d ** 3 / 6
    V = float(v_sph.sum())
    # Daves on the bigger ones
    acc = np.zeros(7)   # sph_all, daves_all, n_all, sph_round, daves_round, n_round, sph*(b/a)^0.5 (prolate expectation)
    big = np.nonzero(A >= daves_min_area)[0] + 1
    for i in big:
        x0, y0, w, h = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]
        comp = lab[y0:y0 + h, x0:x0 + w] == i
        ys, xs = np.nonzero(comp)
        vd = daves_volume(ys.astype(float), xs.astype(float))
        ev = np.linalg.eigvalsh(np.cov(np.vstack([ys, xs]).astype(float)))
        asp = np.sqrt(ev[1] / ev[0]) if ev[0] > 0 else 99.0
        acc[:3] += (v_sph[i - 1], vd, 1)
        acc[6] += v_sph[i - 1] / np.sqrt(asp)
        if asp <= 1.15:
            acc[3:6] += (v_sph[i - 1], vd, 1)
    return V, int(A.sum()), acc


def chord_maps(mask):
    """Per-pixel chord (px) through an assumed ROUND cross-section and the
    ribbon chord (= R), from skeleton slicing. Returns (round, ribbon, R, info).

    e = pixel centre to edge = edt - 0.5;  R = local radius at the nearest
    skeleton pixel of the SAME component = edt(skel) - 0.5;
    chord = 2 sqrt(R^2 - (R - min(e,R))^2)."""
    H, W = mask.shape
    rnd = np.zeros((H, W), np.float32)
    rib = np.zeros((H, W), np.float32)
    Rm = np.zeros((H, W), np.float32)
    if not mask.any():
        return rnd, rib, Rm, []
    # Geometry on the HOLE-FILLED mask: a droplet sitting inside a blob is cut
    # out of the un-atomised mask (total & ~dmask) and leaves a hole, which
    # puts skeleton loops round it with tiny R. The body continues through it.
    # Callers sum chords over the ORIGINAL mask only.
    mask = ndi.binary_fill_holes(mask)
    dist = ndi.distance_transform_edt(mask).astype(np.float32)
    skel = skeletonize(mask)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    info = []
    for i in range(1, n):
        x0, y0, w, h = stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]
        sl = (slice(y0, y0 + h), slice(x0, x0 + w))
        comp = lab[sl] == i
        dc = dist[sl]
        sk = skel[sl] & comp
        if not sk.any():
            yy, xx = np.unravel_index(np.argmax(np.where(comp, dc, -1)), comp.shape)
            sk = np.zeros_like(comp)
            sk[yy, xx] = True
        Rsk = np.where(sk, dc - 0.5, 0).astype(np.float32)
        Rsk = np.maximum(Rsk, 0.5 * sk)
        if sk.sum() == 1:
            Rp = np.full(comp.shape, Rsk[sk][0], np.float32)
        else:
            iy, ix = ndi.distance_transform_edt(~sk, return_distances=False, return_indices=True)
            Rp = Rsk[iy, ix]
        e = np.minimum(dc - 0.5, Rp)
        e = np.maximum(e, 0)
        ch = 2.0 * np.sqrt(np.maximum(Rp ** 2 - (Rp - e) ** 2, 0))
        rnd[sl][comp] = ch[comp]
        rib[sl][comp] = Rp[comp]
        Rm[sl][comp] = Rp[comp]
        info.append((i, int(stats[i, cv2.CC_STAT_AREA]), w, h))
    return rnd, rib, Rm, (lab, stats, info)


def compact_daves_check(mask, rnd, lab_stats, min_area=50):
    """Daves principal-axis volume vs skeleton-round volume on COMPACT
    un-atomised pieces (solidity >= 0.9, aspect <= 3)."""
    if not lab_stats:
        return 0.0, 0.0, 0
    lab, stats, info = lab_stats
    vs = vd = 0.0
    n = 0
    for i, area, w, h in info:
        if area < min_area:
            continue
        x0, y0 = stats[i, 0], stats[i, 1]
        comp = lab[y0:y0 + h, x0:x0 + w] == i
        cnts, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        hull = cv2.convexHull(max(cnts, key=cv2.contourArea))
        ha = cv2.contourArea(hull)
        if ha <= 0 or area / ha < 0.9:
            continue
        ys, xs = np.nonzero(comp)
        c = np.cov(np.vstack([ys, xs]).astype(float))
        ev = np.linalg.eigvalsh(c)
        if ev[0] <= 0 or np.sqrt(ev[1] / ev[0]) > 3:
            continue
        vd += daves_volume(ys.astype(float), xs.astype(float))
        vs += float(rnd[y0:y0 + h, x0:x0 + w][comp].sum())
        n += 1
    return vs, vd, n
