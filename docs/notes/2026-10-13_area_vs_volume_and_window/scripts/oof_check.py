"""Out-of-focus non-droplet detections: mean T inside the mask. A static
window object divides out (T~1); real out-of-focus liquid should not."""
import sys; sys.path.insert(0, '.')
import numpy as np, pandas as pd
import f2h1_core as C
from measure_run import det_crop, DROPLET
D = '/Volumes/LaCie/Experiments/2026/10/12/'
runs = sys.argv[1:]
rows = []
for r in runs:
    R = C.load_run(D + r)
    idx = np.unique(np.round(np.linspace(0, len(R.ids) - 1, 30)).astype(int))
    for k in idx:
        img = R.ids[k]; stem, T = C.read_T(R, img)
        for d in R.by_img.get(img, []):
            if d['category_id'] == DROPLET:
                continue
            mb, bx, by, bh, bw = det_crop(d)
            if not mb.any():
                continue
            t = T[by:by + bh, bx:bx + bw][mb]
            if t.min() > 0.70:
                rows.append(dict(run=r[:6], k=k, cat=d['category_id'], score=d['score'], px=int(mb.sum()),
                                 tmin=float(t.min()), tmean=float(t.mean()), t10=float(np.percentile(t, 10))))
df = pd.DataFrame(rows)
df.to_csv('oof_dets_' + '_'.join(x[:6] for x in runs) + '.csv', index=False)
df['bin'] = pd.cut(df.tmean, [0.7, 0.85, 0.9, 0.95, 0.97, 0.99, 1.01, 1.5])
print(df.groupby(['run', 'bin'], observed=True).px.agg(['size', 'sum']).unstack(0).fillna(0).astype(int).to_string())
