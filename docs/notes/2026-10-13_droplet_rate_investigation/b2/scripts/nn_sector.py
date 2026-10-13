"""Down-stream sector test: do droplets in frame k reappear in k+1 lower in the frame (any speed that
keeps them in view, dy = 0..1100 px = 0..4.3 m/s), roughly straight down (|dx| < 150 px), at a similar size?
Counts size-matched (d_eq ratio within +-30 %) pair vectors per frame pair in the sector, lag1 vs control,
and compares with the count expected if a fraction of droplets moved at a given speed and stayed in focus.
"""
import json
import numpy as np
from common import load, RUNS, CONTROL, HERE
from nn_match import blobs_of, static_filter, pair_vectors

OUT = HERE / "results"
res = {}
edges = np.arange(-1152, 1153, 64)
for tag in RUNS:
    D = load(tag)
    A, _ = static_filter(blobs_of(D["A"])); B, _ = static_filter(blobs_of(D["B"])); C, _ = static_filter(blobs_of(D["C"]))
    sets = {"lag1": [(A[k], A[k + 1]) for k in range(len(A) - 1)] + [(B[k], B[k + 1]) for k in range(len(B) - 1)],
            "ctrl": [(A[k], C[k]) for k in range(len(C))] + [(A[k], B[k]) for k in range(len(B))]}
    r = {}
    for name, pairs in sets.items():
        dys = []
        n_sector, n_flank = [], []
        for b1, b2 in pairs:
            v, s = pair_vectors(b1, b2)
            sm = np.abs(s - 1) < 0.3
            down = (v[:, 0] > 50) & (v[:, 0] < 1100)
            m = (np.abs(v[:, 1]) < 150) & sm
            dys.append(v[m, 0])
            n_sector.append(int((m & down).sum()))
            n_flank.append(int((sm & down & (np.abs(v[:, 1]) >= 150) & (np.abs(v[:, 1]) < 450)).sum()))
        dys = np.concatenate(dys)
        h, _ = np.histogram(dys, edges)
        r[name + "_sector"] = np.array(n_sector); r[name + "_flank"] = np.array(n_flank)
        r[name] = dict(n_pairs=len(pairs), hist_per_pair=(h / len(pairs)).tolist(),
                       sector_per_pair=float(np.mean(n_sector)), sector_sem=float(np.std(n_sector) / np.sqrt(len(pairs))))
    # chance level from the flanks of the SAME pairs (removes count correlation between consecutive frames);
    # sector/flank ratio for chance pairs calibrated on the control pairs. Bootstrap over pairs.
    ls, lf = r.pop("lag1_sector"), r.pop("lag1_flank"); cs, cf = r.pop("ctrl_sector"), r.pop("ctrl_flank")
    rng = np.random.default_rng(0)
    bs = []
    for _ in range(4000):
        i = rng.integers(0, len(ls), len(ls)); j = rng.integers(0, len(cs), len(cs))
        ratio = cs[j].sum() / max(cf[j].sum(), 1)
        bs.append(ls[i].mean() - ratio * lf[i].mean())
    ratio = cs.sum() / max(cf.sum(), 1)
    exc = float(ls.mean() - ratio * lf.mean()); err = float(np.std(bs))
    r["chance_ratio_sector_over_flank_ctrl"] = float(ratio)
    r["chance_ratio_sector_over_flank_lag1"] = float(ls.sum() / max(lf.sum(), 1))
    nper = np.mean([len(b) for b in A + B])
    # expected re-seen droplets per pair if ALL droplets moved straight down at v and stayed in focus:
    exp = {}
    for v_ms in (1.0, 2.0, 3.0, 4.0):
        dy = v_ms * (1 / 390) / 10e-6
        exp[str(v_ms)] = float(nper * max(0.0, 1 - dy / 1152))
    r["excess_per_pair"] = [float(exc), float(err)]
    r["upper95_reseen_per_pair"] = float(exc + 1.96 * err)
    r["droplets_per_frame"] = float(nper)
    r["expected_reseen_per_pair_if_all_move_at_v"] = exp
    r["upper95_fraction_reseen_vs_expected_at_3ms"] = float((exc + 1.96 * err) / exp["3.0"]) if exp["3.0"] > 0 else None
    res[tag] = r
    print(f"{tag:12s} droplets/frame {nper:.1f}  sector vectors/pair lag1 {r['lag1']['sector_per_pair']:.2f} vs ctrl "
          f"{r['ctrl']['sector_per_pair']:.2f}  excess {exc:+.2f} +- {err:.2f}  (95% upper {exc + 1.96 * err:.2f})  "
          f"expected if all at 1/2/3/4 m/s: " + "/".join(f"{x:.1f}" for x in exp.values()))
res["edges"] = edges.tolist()
(OUT / "nn_sector.json").write_text(json.dumps(res, indent=1))
