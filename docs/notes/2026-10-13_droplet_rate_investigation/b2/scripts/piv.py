"""PIV-style cross-correlation between consecutive frames vs unrelated-frame controls.

Signal image: a = clip(1 - T / median_burst(T), 0, 1), high-passed (minus a 10-px Gaussian),
so static residue (specks, background mismatch) is removed and droplet-scale structure kept.

1. Whole frame, overlap-normalised NCC over shifts |dy| <= 560, |dx| <= 1000 px.
2. 256-px interrogation windows (non-overlapping, 4 x 8), search |d| <= 64 px.
3. Ensemble: correlation planes summed over all pairs (sparse-PIV trick), then normalised.
Controls: (k, k+50) [A vs C bursts] and (A_k, B_k) [~1500 frames apart].
"""
import json
import numpy as np
from scipy import ndimage as ndi
from common import load, RUNS, HERE, DT, PX

OUT = HERE / "results"
OUT.mkdir(exist_ok=True)


def signal(stack):
    med = np.median(stack, axis=0)
    a = np.clip(1.0 - stack / np.maximum(med, 1e-3)[None], 0, 1)
    hp = np.stack([f - ndi.gaussian_filter(f, 10) for f in a])
    return hp.astype(np.float32)


def xcorr_full(a, b, max_dy=560, max_dx=1000):
    """Overlap-normalised NCC c(dy,dx) = sum a(x) b(x+d) / sqrt(sum_ov a^2 sum_ov b^2)."""
    H, W = a.shape
    sh = (2 * H, 2 * W)
    Fa = np.fft.rfft2(a, sh); Fb = np.fft.rfft2(b, sh)
    num = np.fft.irfft2(np.conj(Fa) * Fb, sh)            # num[d] = sum a(x) b(x+d)
    one = np.ones_like(a)
    Fo = np.fft.rfft2(one, sh)
    ea = np.fft.irfft2(np.conj(np.fft.rfft2(a * a, sh)) * Fo, sh)   # sum over overlap of a^2
    eb = np.fft.irfft2(np.conj(Fo) * np.fft.rfft2(b * b, sh), sh)   # sum over overlap of b^2
    num = np.fft.fftshift(num); ea = np.fft.fftshift(ea); eb = np.fft.fftshift(eb)
    cy, cx = H, W
    sl = (slice(cy - max_dy, cy + max_dy + 1), slice(cx - max_dx, cx + max_dx + 1))
    c = num[sl] / np.sqrt(np.maximum(ea[sl] * eb[sl], 1e-12))
    return c, num[sl]


def window_corr(a, b, win=256, search=64):
    H, W = a.shape
    res = []
    planes = []
    for y0 in range(0, H - win + 1, win):
        for x0 in range(0, W - win + 1, win):
            wa = a[y0:y0 + win, x0:x0 + win]; wb = b[y0:y0 + win, x0:x0 + win]
            wa = wa - wa.mean(); wb = wb - wb.mean()
            na = np.sqrt((wa ** 2).sum()); nb = np.sqrt((wb ** 2).sum())
            if na < 1e-6 or nb < 1e-6:
                continue
            sh = (2 * win, 2 * win)
            c = np.fft.fftshift(np.fft.irfft2(np.conj(np.fft.rfft2(wa, sh)) * np.fft.rfft2(wb, sh), sh))
            c = c[win - search:win + search + 1, win - search:win + search + 1] / (na * nb)
            planes.append(c)
            iy, ix = np.unravel_index(np.argmax(c), c.shape)
            pk = c[iy, ix]
            # secondary peak: mask 5x5 around primary
            c2 = c.copy(); c2[max(iy - 3, 0):iy + 4, max(ix - 3, 0):ix + 4] = -np.inf
            res.append(dict(y0=y0, x0=x0, peak=float(pk), dy=int(iy - search), dx=int(ix - search),
                            ratio=float(pk / max(c2.max(), 1e-9)) if c2.max() > 0 else np.inf))
    return res, planes


def summarise_pairs(pairs, label):
    full_pk, full_d, zero, win_pk, win_ratio, win_d = [], [], [], [], [], []
    ens_num = None
    ens_win = None
    for a, b in pairs:
        c, num = xcorr_full(a, b)
        cy, cx = (np.array(c.shape) - 1) // 2
        zero.append(float(c[cy, cx]))
        cc = c.copy(); cc[cy - 2:cy + 3, cx - 2:cx + 3] = -np.inf     # exclude zero shift
        iy, ix = np.unravel_index(np.argmax(cc), cc.shape)
        full_pk.append(float(cc[iy, ix])); full_d.append((int(iy - cy), int(ix - cx)))
        ens_num = num if ens_num is None else ens_num + num
        res, planes = window_corr(a, b)
        for r in res:
            win_pk.append(r["peak"]); win_ratio.append(r["ratio"]); win_d.append((r["dy"], r["dx"]))
        s = np.sum(planes, axis=0)
        ens_win = s if ens_win is None else ens_win + s
    return dict(label=label, n_pairs=len(pairs), zero=zero, full_pk=full_pk, full_d=full_d,
                win_pk=win_pk, win_ratio=win_ratio, win_d=win_d), ens_num, ens_win


def peak_snr(plane, excl=2):
    cy, cx = (np.array(plane.shape) - 1) // 2
    p = plane.copy()
    z = float(p[cy, cx])
    p[cy - excl:cy + excl + 1, cx - excl:cx + excl + 1] = np.nan
    mu, sd = np.nanmean(p), np.nanstd(p)
    iy, ix = np.unravel_index(np.nanargmax(p), p.shape)
    return dict(peak=float(p[iy, ix]), dy=int(iy - cy), dx=int(ix - cx), snr=float((p[iy, ix] - mu) / sd),
                zero_snr=float((z - mu) / sd))


def shift_zero(img, dy, dx):
    out = np.zeros_like(img)
    H, W = img.shape
    ys = slice(max(dy, 0), H + min(dy, 0)); yd = slice(max(-dy, 0), H + min(-dy, 0))
    xs = slice(max(dx, 0), W + min(dx, 0)); xd = slice(max(-dx, 0), W + min(-dx, 0))
    out[ys, xs] = img[yd, xd]
    return out


def synthetic_test(tag, fracs=(0.05, 0.1, 0.25, 0.5), true=(150, 40), npairs=15, seed=1):
    """Positive control: k+1 := real unrelated frame k+1 + a copy of a fraction f of frame k's
    blobs shifted by `true` (dy, dx) px. Does the method recover the shift?"""
    from common import segment
    rng = np.random.default_rng(seed)
    D = load(tag)
    A = signal(D["A"])
    out = {}
    for f in fracs:
        hits, snr_true, pk = 0, [], []
        ens = None
        for k in range(npairs):
            lab, bl = segment(D["A"][k])
            labs = np.array([b["label"] for b in bl])
            keep = labs[rng.random(len(labs)) < f]
            m = ndi.binary_dilation(np.isin(lab, keep), iterations=3)
            b_syn = A[k + 1] + shift_zero(A[k] * m, *true)
            c, num = xcorr_full(A[k], b_syn)
            cy, cx = (np.array(c.shape) - 1) // 2
            cc = c.copy(); cc[cy - 2:cy + 3, cx - 2:cx + 3] = -np.inf
            iy, ix = np.unravel_index(np.argmax(cc), cc.shape)
            pk.append(float(cc[iy, ix]))
            hits += int(abs(iy - cy - true[0]) <= 3 and abs(ix - cx - true[1]) <= 3)
            ens = num if ens is None else ens + num
        e = peak_snr(ens)
        out[str(f)] = dict(frac_pairs_recovered=hits / npairs, median_best_ncc=float(np.median(pk)),
                           ensemble_peak_at=[e["dy"], e["dx"]], ensemble_snr=e["snr"])
        print(f"  synthetic {tag} f={f}: single-pair recovery {hits}/{npairs}, median best NCC {np.median(pk):.3f}, "
              f"ensemble peak at {e['dy']},{e['dx']} SNR {e['snr']:.1f}", flush=True)
    return out


if __name__ == "__main__":
    import sys
    from common import CONTROL
    summary = {}
    tags = RUNS + [CONTROL]
    for tag in tags:
        D = load(tag)
        A = signal(D["A"])
        C = signal(np.concatenate([D["C"], D["A"][:10]]))[:10]
        if tag == CONTROL:
            B = signal(D["D"]); bname = "D"
        else:
            B = signal(D["B"]); bname = "B"
        sets = {
            "lag1_A": [(A[k], A[k + 1]) for k in range(len(A) - 1)],
            f"lag1_{bname}": [(B[k], B[k + 1]) for k in range(len(B) - 1)],
            "lag2_A": [(A[k], A[k + 2]) for k in range(len(A) - 2)],
            "ctrl_lag50": [(A[k], C[k]) for k in range(10)],
            f"ctrl_Avs{bname}": [(A[k], B[k]) for k in range(min(len(A), len(B), 20))],
        }
        summary[tag] = {}
        for name, pairs in sets.items():
            s, ens, ensw = summarise_pairs(pairs, name)
            s["ens_full"] = peak_snr(ens)
            s["ens_win"] = peak_snr(ensw)
            np.save(OUT / f"ens_full_{tag}_{name}.npy", ens.astype(np.float32))
            np.save(OUT / f"ens_win_{tag}_{name}.npy", ensw.astype(np.float32))
            summary[tag][name] = s
            fp = np.array(s["full_pk"]); wp = np.array(s["win_pk"]); wr = np.array(s["win_ratio"])
            print(f"{tag:12s} {name:11s} n={len(pairs):2d}  full-frame best NCC median {np.median(fp):.3f} "
                  f"(max {fp.max():.3f})  zero-shift NCC median {np.median(s['zero']):.3f}  "
                  f"win peak median {np.median(wp):.3f} p90 {np.percentile(wp, 90):.3f}  "
                  f"win ratio>1.5 frac {np.mean(wr > 1.5):.2f}  "
                  f"ensemble full SNR {s['ens_full']['snr']:.1f} at {s['ens_full']['dy']},{s['ens_full']['dx']}  "
                  f"zeroSNR {s['ens_full']['zero_snr']:.1f}  ens win SNR {s['ens_win']['snr']:.1f} at "
                  f"{s['ens_win']['dy']},{s['ens_win']['dx']}", flush=True)
    summary["synthetic_centre_9000"] = synthetic_test("centre_9000")
    (OUT / "piv_summary.json").write_text(json.dumps(summary, indent=1))
