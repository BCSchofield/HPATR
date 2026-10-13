import sys, time, csv
sys.path.insert(0, '.')
import numpy as np
import f2h1_core as C
from classical_liquid import measure_frame
import classical_liquid as cl
cap = C.Capture(); cap.install()
D = '/Volumes/LaCie/Experiments/2026/10/12/'
runs = ['142150_7000sccm_100rpm_3000sps_or1.8_bh0.5', '112022_11000sccm_100rpm_5000sps_or0.5_bh0.5', '134001_9000sccm_500rpm_3000sps_or1.2_bh0.5']
for r in runs:
    t0=time.time(); R = C.load_run(D + r); tl=time.time()-t0
    ref = {row['frame']: row for row in csv.DictReader(open(R.ana / 'liquid_0.30' / 'classical_per_frame.csv'))}
    print(r, 'load', round(tl,1), 's', vars(R.args))
    for img_id in R.ids[:5]:
        t1=time.time(); stem, T = C.read_T(R, img_id); tio=time.time()-t1
        t2=time.time(); row, *_ , unatom = measure_frame(T, R.by_img.get(img_id, []), R.args); tm=time.time()-t2
        total = unatom | cap.dmask
        rr = ref[stem]
        ok = (row['droplet_px']==int(rr['droplet_px']) and row['total_liquid_px']==int(rr['total_liquid_px']) and int(total.sum())==row['total_liquid_px'])
        print(f"  {stem}: drop {row['droplet_px']} vs {rr['droplet_px']}  total {row['total_liquid_px']} vs {rr['total_liquid_px']}  {'MATCH' if ok else 'MISMATCH'}  io {tio:.2f}s measure {tm:.2f}s")
