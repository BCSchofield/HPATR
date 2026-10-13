"""Candidate H2 fix, read-only estimate on the 30-frame sample: drop non-droplet
detections that are 'out of focus' (T_min > 0.70) AND have mean T >= TMEAN in their
mask (nothing there after background division = a static object the model sees in the
un-normalised frame). Filtering dets before measure_frame is exactly the patched rule,
because non-droplet dets only enter via model_masks' oof union."""
import glob, sys, time
from multiprocessing import Pool
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DAY = '/Volumes/LaCie/Experiments/2026/10/12/'
TMEANS = (0.95, 0.97)

def one(run):
    import f2h1_core as C
    from classical_liquid import measure_frame
    from measure_run import det_crop, DROPLET
    cap = C.Capture(); cap.install()
    R = C.load_run(run)
    idx = np.unique(np.round(np.linspace(0, len(R.ids) - 1, 30)).astype(int))
    rows = []
    for k in idx:
        img = R.ids[k]; stem, T = C.read_T(R, img)
        dets = R.by_img.get(img, [])
        tm = {}
        for i, d in enumerate(dets):
            if d['category_id'] == DROPLET:
                continue
            mb, bx, by, bh, bw = det_crop(d)
            if not mb.any():
                continue
            t = T[by:by + bh, bx:bx + bw][mb]
            if t.min() > 0.70:
                tm[i] = float(t.mean())
        r = dict(run=Path(run).name, k=k)
        for tag, thr in [('orig', None)] + [(f'fix{t}', t) for t in TMEANS]:
            dd = dets if thr is None else [d for i, d in enumerate(dets) if not (i in tm and tm[i] >= thr)]
            row, _, _, _, un = measure_frame(T, dd, R.args)
            r[f'd_{tag}'] = row['droplet_px']; r[f't_{tag}'] = row['total_liquid_px']
            if tag in ('orig', 'fix0.97'):
                Vd, _, _ = C.droplet_volumes(cap.dmask, daves_min_area=10 ** 9)
                rnd, rib, _, _ = C.chord_maps(un)
                r[f'Vd_{tag}'] = Vd; r[f'Vu_{tag}'] = float(rnd[un].sum())
        rows.append(r)
    return rows

if __name__ == '__main__':
    runs = sorted(glob.glob(DAY + '1*_bh0.5'))
    out = []
    with Pool(4) as p:
        for rows in p.imap_unordered(one, runs):
            out += rows
            print(rows[0]['run'], flush=True)
    pd.DataFrame(out).to_csv(HERE / 'fix_check_frames.csv', index=False)
    print('FIX DONE')
