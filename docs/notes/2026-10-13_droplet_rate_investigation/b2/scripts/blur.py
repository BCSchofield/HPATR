"""Motion-blur bound from the shape of isolated in-focus droplets (4 us exposure: 1 px = 2.5 m/s).

Per droplet (hysteresis blob, d_eq 3-25 px, T_min < 0.5, isolated, off the border):
  * grey-level second moments of w = clip(1-T, 0) inside the blob mask dilated by 2 px:
      D_flow  = mu_yy - mu_xx  (flow axis = image vertical, see orientation check)
      D_diag  = 2 mu_xy        (difference between the two diagonals: an isotropy control)
    A box blur of length L along y adds L^2/12 to mu_yy.
  * 20-80 % edge widths from interpolated T profiles through the centroid:
      top, bottom (along flow) and left, right (across flow).
    Sharp edge * Gaussian(sigma): w2080 = 1.683 sigma; box blur L adds L^2/12 to sigma^2.
Also: orientation of elongated liquid objects (flow-axis check) and head/tail asymmetry.
"""
import json
import numpy as np
from scipy import ndimage as ndi
from common import load, segment, RUNS, HERE, SCCM, CONTROL

OUT = HERE / "results"
OUT.mkdir(exist_ok=True)


def edge_width(prof, step):
    """prof: T samples from outside (index 0) inward to the profile minimum. Returns 20-80% width in px."""
    pmin = prof.min(); pbg = np.median(prof[:3])
    if pbg - pmin < 0.3:
        return np.nan
    n = (prof - pmin) / (pbg - pmin)
    i_min = int(np.argmin(prof))
    n = n[:i_min + 1]

    def cross(level):
        idx = np.nonzero(n < level)[0]
        if len(idx) == 0 or idx[0] == 0:
            return np.nan
        j = idx[0]
        # linear interpolation between j-1 (>= level) and j (< level)
        f = (n[j - 1] - level) / (n[j - 1] - n[j])
        return (j - 1 + f) * step

    return cross(0.2) - cross(0.8)


def droplet_measures(T, blobs, lab):
    out = []
    H, W = T.shape
    cents = np.array([(b["cy"], b["cx"]) for b in blobs])
    step = 0.25
    for b in blobs:
        if b["border"] or not (3 <= b["d_eq"] <= 25) or b["tmin"] >= 0.5:
            continue
        r = b["d_eq"] / 2
        # isolation: no other blob centroid within d_eq + 12 px
        d = np.sqrt(((cents - [b["cy"], b["cx"]]) ** 2).sum(1))
        if (d < b["d_eq"] + 12).sum() > 1:
            continue
        pad = int(np.ceil(r)) + 6
        y0, y1 = int(b["y0"]) - 6, int(b["y1"]) + 6
        x0, x1 = int(b["x0"]) - 6, int(b["x1"]) + 6
        if y0 < 0 or x0 < 0 or y1 > H or x1 > W:
            continue
        t = T[y0:y1, x0:x1]
        m = ndi.binary_dilation(lab[y0:y1, x0:x1] == b["label"], iterations=2)
        w = np.clip(1 - t, 0, None) * m
        s = w.sum()
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cy = (w * yy).sum() / s; cx = (w * xx).sum() / s
        myy = (w * (yy - cy) ** 2).sum() / s; mxx = (w * (xx - cx) ** 2).sum() / s
        mxy = (w * (yy - cy) * (xx - cx)).sum() / s
        # edge profiles through the grey-level centroid, 3-line average, 0.25 px sampling
        L = pad + 2
        ts = np.arange(-L, L + step / 2, step)
        prof_v = np.mean([ndi.map_coordinates(T, [cy + ts, np.full_like(ts, cx + o)], order=1) for o in (-0.5, 0, 0.5)], 0)
        prof_h = np.mean([ndi.map_coordinates(T, [np.full_like(ts, cy + o), cx + ts], order=1) for o in (-0.5, 0, 0.5)], 0)
        mid = len(ts) // 2
        e_top = edge_width(prof_v[:mid + 1], step) if True else np.nan
        e_bot = edge_width(prof_v[mid:][::-1], step)
        e_lft = edge_width(prof_h[:mid + 1], step)
        e_rgt = edge_width(prof_h[mid:][::-1], step)
        out.append(dict(d_eq=b["d_eq"], tmin=b["tmin"], myy=myy, mxx=mxx, mxy=mxy,
                        D_flow=myy - mxx, D_diag=2 * mxy,
                        e_top=e_top, e_bot=e_bot, e_lft=e_lft, e_rgt=e_rgt,
                        ext_y=b["y1"] - b["y0"], ext_x=b["x1"] - b["x0"]))
    return out


def ligament_orientation(T, blobs, lab):
    res = []
    for b in blobs:
        if b["d_eq"] < 12 or b["minor"] <= 0 or b["major"] / max(b["minor"], 1e-6) < 3:
            continue
        # head/tail: grey-level mass skewness along the major axis
        y0, y1, x0, x1 = int(b["y0"]), int(b["y1"]), int(b["x0"]), int(b["x1"])
        m = lab[y0:y1, x0:x1] == b["label"]
        w = np.clip(1 - T[y0:y1, x0:x1], 0, None) * m
        yy, xx = np.mgrid[y0:y1, x0:x1]
        s = w.sum(); cy = (w * yy).sum() / s; cx = (w * xx).sum() / s
        th = np.radians(b["ang_from_vertical"])
        u = (yy - cy) * np.cos(th) + (xx - cx) * np.sin(th)   # coordinate along major axis, +down-ish
        sk = (w * u ** 3).sum() / s / max(((w * u ** 2).sum() / s) ** 1.5, 1e-9)
        res.append(dict(ang=b["ang_from_vertical"], aspect=b["major"] / b["minor"], d_eq=b["d_eq"], skew=sk))
    return res


if __name__ == "__main__":
    allres = {}
    summary = {}
    for tag in RUNS + [CONTROL]:
        D = load(tag)
        drops, ligs = [], []
        for st in D.values():
            for T in st:
                lab, bl = segment(T)
                drops += droplet_measures(T, bl, lab)
                ligs += ligament_orientation(T, bl, lab)
        allres[tag] = dict(drops=drops, ligs=ligs)
        dd = {k: np.array([x[k] for x in drops], float) for k in drops[0]}
        ang = np.array([x["ang"] for x in ligs]); sk = np.array([x["skew"] for x in ligs])
        along = np.nanmean([dd["e_top"], dd["e_bot"]], 0); across = np.nanmean([dd["e_lft"], dd["e_rgt"]], 0)
        ok = np.isfinite(along) & np.isfinite(across)
        def boot(x, n=2000, f=np.median):
            rng = np.random.default_rng(0); x = x[np.isfinite(x)]
            bs = [f(rng.choice(x, len(x))) for _ in range(n)]
            return float(f(x)), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
        sig_al = along[ok] / 1.683; sig_ac = across[ok] / 1.683
        Lsq_edge = 12 * (np.median(sig_al ** 2) - np.median(sig_ac ** 2))
        small = (dd["d_eq"] < 6)
        summary[tag] = dict(
            sccm=SCCM[tag], n_droplets=len(drops), d_eq_median=float(np.median(dd["d_eq"])),
            D_flow_median=boot(dd["D_flow"]), D_diag_median=boot(dd["D_diag"]),
            D_flow_small_median=boot(dd["D_flow"][small]), n_small=int(small.sum()),
            edge_along_median=boot(along[ok]), edge_across_median=boot(across[ok]),
            edge_diff_median=boot(along[ok] - across[ok]), n_edges=int(ok.sum()),
            edge_top=boot(dd["e_top"]), edge_bot=boot(dd["e_bot"]), edge_lft=boot(dd["e_lft"]), edge_rgt=boot(dd["e_rgt"]),
            L_from_edges_px=float(np.sign(Lsq_edge) * np.sqrt(abs(Lsq_edge))),
            frac_drops_taller_than_wide=float(np.mean(dd["ext_y"] > dd["ext_x"])),
            frac_drops_wider_than_tall=float(np.mean(dd["ext_y"] < dd["ext_x"])),
            n_ligaments=len(ligs), lig_abs_angle_median=float(np.median(np.abs(ang))) if len(ang) else None,
            lig_frac_within_30deg_of_vertical=float(np.mean(np.abs(ang) < 30)) if len(ang) else None,
            lig_frac_within_30deg_of_horizontal=float(np.mean(np.abs(ang) > 60)) if len(ang) else None,
            lig_frac_mass_skew_positive=float(np.mean(sk[np.abs(ang) < 30] > 0)) if len(ang) else None,
            elong_axis_deg_from_vertical=float(0.5 * np.degrees(np.arctan2(np.median(dd["D_diag"]), np.median(dd["D_flow"])))),
        )
        print(tag, {k: (np.round(v, 3).tolist() if isinstance(v, (list, tuple, float)) else v) for k, v in summary[tag].items()}, flush=True)
    (OUT / "blur_summary.json").write_text(json.dumps(summary, indent=1))
    (OUT / "blur_droplets.json").write_text(json.dumps({k: v["drops"] for k, v in allres.items()}))
    (OUT / "ligaments.json").write_text(json.dumps({k: v["ligs"] for k, v in allres.items()}))
