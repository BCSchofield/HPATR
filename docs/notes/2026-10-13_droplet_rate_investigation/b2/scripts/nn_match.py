"""Blob-level tests: displacement histogram of all blob pairs (k -> k+1) vs controls,
and persistence (fraction of droplets with a size-matched partner within r).

Droplet blobs: hysteresis mask (seed T<0.6, grow T<0.85), d_eq 2-30 px, not on the border.
Static blobs (same place, |d| < 3 px, in >= 50% of burst frames) are removed first.
"""
import json
import numpy as np
from common import load, segment, RUNS, HERE, CONTROL

OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
H, W = 1152, 2048


def blobs_of(stack):
    out = []
    for T in stack:
        _, bl = segment(T)
        arr = np.array([(b["cy"], b["cx"], b["d_eq"], b["tmin"]) for b in bl
                        if 2 <= b["d_eq"] <= 30 and not b["border"]]).reshape(-1, 4)
        out.append(arr)
    return out


def static_filter(blist, tol=3.0, frac=0.5):
    """Drop blobs that recur at the same position in >= frac of the frames (dirt/specks)."""
    allp = np.concatenate([b[:, :2] for b in blist])
    keep_list, n_static = [], 0
    for b in blist:
        if len(b) == 0:
            keep_list.append(b); continue
        d = np.sqrt(((b[:, None, :2] - allp[None]) ** 2).sum(-1))
        recur = (d < tol).sum(1)          # includes itself
        st = recur >= frac * len(blist)
        n_static += int(st.sum())
        keep_list.append(b[~st])
    return keep_list, n_static


def pair_vectors(b1, b2):
    if len(b1) == 0 or len(b2) == 0:
        return np.zeros((0, 2)), np.zeros((0,))
    dy = b2[None, :, 0] - b1[:, None, 0]
    dx = b2[None, :, 1] - b1[:, None, 1]
    rs = b2[None, :, 2] / b1[:, None, 2]
    return np.stack([dy.ravel(), dx.ravel()], 1), rs.ravel()


def persistence(b1, b2, radii, size_tol=0.3):
    """fraction of blobs in b1 with a blob in b2 within r (any direction) and |d_eq ratio - 1| < tol."""
    if len(b1) == 0:
        return {r: np.nan for r in radii}
    if len(b2) == 0:
        return {r: 0.0 for r in radii}
    d = np.sqrt(((b1[:, None, :2] - b2[None, :, :2]) ** 2).sum(-1))
    ok = np.abs(b2[None, :, 2] / b1[:, None, 2] - 1) < size_tol
    return {r: float(np.mean(((d < r) & ok).any(1))) for r in radii}


if __name__ == "__main__":
    radii = [10, 25, 50, 100, 200, 400]
    bins_y = np.arange(-1152, 1153, 32); bins_x = np.arange(-2048, 2049, 32)
    res = {}
    for tag in RUNS + [CONTROL]:
        D = load(tag)
        A, nA = static_filter(blobs_of(D["A"]))
        B, nB = static_filter(blobs_of(D["B"] if "B" in D else D["D"]))
        C, nC = static_filter(blobs_of(D["C"]))
        nper = np.mean([len(b) for b in A])
        sets = {"lag1": [(A[k], A[k + 1]) for k in range(len(A) - 1)] + [(B[k], B[k + 1]) for k in range(len(B) - 1)],
                "ctrl": [(A[k], C[k]) for k in range(len(C))] + [(A[k], B[k]) for k in range(len(B))]}
        r = dict(n_droplet_blobs_per_frame=float(nper), n_static_removed=int(nA + nB + nC))
        for name, pairs in sets.items():
            V = []; S = []
            pers = {rr: [] for rr in radii}
            for b1, b2 in pairs:
                v, s = pair_vectors(b1, b2); V.append(v); S.append(s)
                p = persistence(b1, b2, radii)
                for rr in radii:
                    pers[rr].append(p[rr])
            V = np.concatenate(V); S = np.concatenate(S)
            h, _, _ = np.histogram2d(V[:, 0], V[:, 1], bins=[bins_y, bins_x])
            sm = np.abs(S - 1) < 0.3
            hs, _, _ = np.histogram2d(V[sm, 0], V[sm, 1], bins=[bins_y, bins_x])
            np.save(OUT / f"nnhist_{tag}_{name}.npy", h / len(pairs))
            np.save(OUT / f"nnhist_sizematched_{tag}_{name}.npy", hs / len(pairs))
            # short-range vectors only (|d| < 200 px): count per pair
            near = np.sqrt((V ** 2).sum(1)) < 200
            r[name] = dict(n_pairs=len(pairs),
                           persistence={str(rr): float(np.nanmean(pers[rr])) for rr in radii},
                           near200_per_pair=float(near.sum() / len(pairs)),
                           near200_sizematched_per_pair=float((near & sm).sum() / len(pairs)))
        # excess map significance (size-matched): (lag1 - ctrl) / sqrt(ctrl counts)
        h1 = np.load(OUT / f"nnhist_sizematched_{tag}_lag1.npy") * len(sets["lag1"])
        h0 = np.load(OUT / f"nnhist_sizematched_{tag}_ctrl.npy") * len(sets["ctrl"])
        h0s = h0 * len(sets["lag1"]) / len(sets["ctrl"])
        z = (h1 - h0s) / np.sqrt(h0s + h1 / 1 + 1)
        iy, ix = np.unravel_index(np.argmax(z), z.shape)
        r["max_excess_z"] = float(z[iy, ix]); r["max_excess_at_dy_dx"] = [int(bins_y[iy] + 16), int(bins_x[ix] + 16)]
        r["n_bins"] = int(z.size)
        res[tag] = r
        print(tag, json.dumps(r, indent=None), flush=True)
    (OUT / "nn_summary.json").write_text(json.dumps(res, indent=1))
