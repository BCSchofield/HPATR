#!/usr/bin/env python3
"""
taguchi_analysis.py -- analyse an L9 (3 factors x 3 levels) array of measured runs.

RESPONSES
  D32            in-focus droplets only (measure_run.py), smaller-is-better
  atomised       CLASSICAL atomised fraction (classical_liquid.py), larger-is-better.
                 The model-only fraction is reported for reference and never mixed in.

Both are re-derived here from the per-frame files, so point estimate and
bootstrap use exactly the same arithmetic:
  D32      = sum(d^3) / sum(d^2) over every in-focus droplet in the run
             (per frame from droplet_sizes.csv)
  atomised = sum(droplet px) / sum(total liquid px) over every frame
             (classical_per_frame.csv) -- pooled, never an average of ratios
and checked against each run's own summary before anything else runs.

UNCERTAINTY (measurement only)
  Bootstrap over FRAMES, resampling every ci_stride-th frame (the run's own
  decorrelation stride, from its summary) so correlated frames are not treated
  as independent. B replicates per run; each replicate is shifted so it is
  centred on the all-frame point estimate.

SIGNIFICANCE -- two different questions, both reported
  1. ANOVA across the 9 runs. The L9's unassigned 4th column carries the error
     estimate: 2 degrees of freedom, so F(2,2) and p = 1/(1+F). Weak by
     construction -- a factor must dominate to reach p < 0.05.
  2. Effect vs MEASUREMENT NOISE. For each factor, the observed between-level
     sum of squares is compared with the distribution of the same statistic
     computed from bootstrap noise alone (replicate - point estimate). This says
     whether the effect is larger than the measurement can resolve. It does NOT
     include run-to-run repeatability: there are no replicate runs.

S/N ratios use the standard single-observation forms: -20 log10(D32) and
+20 log10(atomised %). With one value per run they are monotone transforms of
the response, so they cannot change a ranking; reported for completeness.

ODD FLAGS (copied to <out>/odd/ only if anything is flagged)
  per frame: classical atomised >= 99% (no un-atomised liquid in frame), zero
  in-focus droplets, per-frame D32 > 5 robust SDs from the run median (frames
  with >= 10 in-focus droplets only); per run: a stage > 2x the median of that
  stage across runs. Capped at the most extreme few per category per run.

Usage:
    python taguchi_analysis.py --out <dir> <run dir> x9
"""

import argparse
import csv
import json
import math
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

N_BOOT = 2000
SEED = 0
MAX_FLAG_IMAGES = 4  # per category per run

FACTORS = ("sccm", "rpm", "sps")
FACTOR_LABEL = {"sccm": "Gas flow (sccm)", "rpm": "Bubbler RPM", "sps": "Silicone (steps/s)"}


def parse_levels(name):
    m = re.search(r"(\d+)sccm_(\d+)rpm_(\d+)sps", name)
    if not m:
        sys.exit(f"cannot read factor levels from folder name: {name}")
    return dict(zip(FACTORS, map(int, m.groups())))


def load_run(run: Path, thr: str):
    an = run / "shadowgraph" / "analysis"
    meas = an / f"measurement_{thr}"
    cl = an / f"classical_{thr}"
    summ = json.loads((meas / "summary.json").read_text(encoding="utf-8"))
    csumm = json.loads((cl / "classical_summary.json").read_text(encoding="utf-8"))

    s3, s2, nfocus = defaultdict(float), defaultdict(float), defaultdict(int)
    with open(meas / "droplet_sizes.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["in_focus"] == "1":
                d = float(r["diameter_um"])
                s3[r["frame"]] += d ** 3
                s2[r["frame"]] += d ** 2
                nfocus[r["frame"]] += 1
    cpf = {}
    with open(cl / "classical_per_frame.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cpf[r["frame"]] = r
    frames = sorted(cpf)
    S3 = np.array([s3.get(fr, 0.0) for fr in frames])
    S2 = np.array([s2.get(fr, 0.0) for fr in frames])
    DP = np.array([float(cpf[fr]["droplet_px"]) for fr in frames])
    TP = np.array([float(cpf[fr]["total_liquid_px"]) for fr in frames])

    d32 = S3.sum() / S2.sum()
    atom = 100.0 * DP.sum() / TP.sum()
    # the re-derivation must agree with what each tool already reported
    if abs(d32 - summ["d32_in_focus_um"]) > 0.02:
        sys.exit(f"{run.name}: D32 re-derived {d32:.3f} != summary {summ['d32_in_focus_um']}")
    if abs(atom - csumm["atomised_pct_pooled"]) > 0.002:
        sys.exit(f"{run.name}: atomised re-derived {atom:.4f} != "
                 f"classical summary {csumm['atomised_pct_pooled']}")

    ci_stride = int(summ.get("provenance", {}).get("ci_stride") or 1)
    return {
        "run": run.name, "dir": run, "levels": parse_levels(run.name), "frames": frames,
        "S3": S3, "S2": S2, "DP": DP, "TP": TP, "nfocus": nfocus, "cpf": cpf,
        "d32": d32, "atom": atom, "model_atom": summ.get("atomised_pct"),
        "d32_ci_summary": summ.get("d32_ci95"), "ci_stride": ci_stride,
        "meas_dir": meas, "cl_dir": cl,
    }


def bootstrap(r, rng):
    idx_pool = np.arange(len(r["frames"]))[::max(1, r["ci_stride"])]
    n = len(idx_pool)
    d_ci = r["S3"][idx_pool].sum() / r["S2"][idx_pool].sum()
    a_ci = 100.0 * r["DP"][idx_pool].sum() / r["TP"][idx_pool].sum()
    D, A = np.empty(N_BOOT), np.empty(N_BOOT)
    for b in range(N_BOOT):
        i = idx_pool[rng.integers(0, n, n)]
        D[b] = r["S3"][i].sum() / r["S2"][i].sum()
        A[b] = 100.0 * r["DP"][i].sum() / r["TP"][i].sum()
    # centre on the all-frame point estimate
    r["boot_d32"] = D - d_ci + r["d32"]
    r["boot_atom"] = A - a_ci + r["atom"]
    r["d32_ci"] = np.percentile(r["boot_d32"], [2.5, 97.5])
    r["atom_ci"] = np.percentile(r["boot_atom"], [2.5, 97.5])
    r["n_ci_frames"] = n


def level_table(runs, values, factor):
    lv = sorted({r["levels"][factor] for r in runs})
    return lv, [np.mean([v for r, v in zip(runs, values) if r["levels"][factor] == L]) for L in lv]


def ss_factor(runs, values, factor):
    grand = np.mean(values)
    _, means = level_table(runs, values, factor)
    return 3.0 * sum((m - grand) ** 2 for m in means)


def f_sf_2(F, d2):
    """P(F(2,d2) > F) -- exact for 2 numerator dof."""
    return (1.0 + 2.0 * F / d2) ** (-d2 / 2.0)


def anova(runs, values):
    grand = np.mean(values)
    ss_t = sum((v - grand) ** 2 for v in values)
    out = {f: ss_factor(runs, values, f) for f in FACTORS}
    ss_e = ss_t - sum(out.values())
    dof_e = len(values) - 1 - 2 * len(FACTORS)
    ms_e = ss_e / dof_e if dof_e > 0 else float("nan")
    res = {}
    for f in FACTORS:
        F = (out[f] / 2.0) / ms_e if ms_e and ms_e > 0 else float("inf")
        res[f] = {"SS": out[f], "dof": 2, "F": F,
                  "p": f_sf_2(F, dof_e) if math.isfinite(F) else 0.0,
                  "contribution_pct": 100.0 * out[f] / ss_t if ss_t else float("nan")}
    res["error"] = {"SS": ss_e, "dof": dof_e,
                    "contribution_pct": 100.0 * ss_e / ss_t if ss_t else float("nan")}
    return res


def noise_test(runs, key_point, key_boot):
    """p = fraction of noise-only bootstrap SS_factor >= observed SS_factor."""
    obs_vals = [r[key_point] for r in runs]
    res = {}
    for f in FACTORS:
        obs = ss_factor(runs, obs_vals, f)
        null = np.array([ss_factor(runs, [r[key_boot][b] - r[key_point] for r in runs], f)
                         for b in range(N_BOOT)])
        lv, _ = level_table(runs, obs_vals, f)
        lvl_boot = np.array([level_table(runs, [r[key_boot][b] for r in runs], f)[1]
                             for b in range(N_BOOT)])
        res[f] = {"SS_observed": obs,
                  "p_vs_noise": float((null >= obs).mean()),
                  "levels": lv,
                  "level_means": level_table(runs, obs_vals, f)[1],
                  "level_ci95": np.percentile(lvl_boot, [2.5, 97.5], axis=0).T.tolist()}
    return res


def flag_odd(runs, timings, out):
    flags = []
    for r in runs:
        stems = r["frames"]
        # classical atomised ~100%: no un-atomised liquid at all
        full = [(s, float(r["cpf"][s]["atomised_pct"])) for s in stems
                if r["cpf"][s]["atomised_pct"] not in ("", "nan")
                and float(r["cpf"][s]["atomised_pct"]) >= 99.0]
        for s, v in full[:MAX_FLAG_IMAGES]:
            flags.append((r, s, "atomised_100pct",
                          f"classical atomised {v:.1f}%: no un-atomised liquid in frame "
                          f"({len(full)} such frames in this run)"))
        empty = [s for s in stems if r["nfocus"].get(s, 0) == 0]
        for s in empty[:MAX_FLAG_IMAGES]:
            flags.append((r, s, "no_infocus_droplets",
                          f"zero in-focus droplets ({len(empty)} such frames in this run)"))
        dense = [(s, r["S3"][i] / r["S2"][i]) for i, s in enumerate(stems)
                 if r["nfocus"].get(s, 0) >= 10]
        if len(dense) > 10:
            vals = np.array([v for _, v in dense])
            med = np.median(vals)
            mad = 1.4826 * np.median(np.abs(vals - med)) or 1.0
            out_f = sorted(((s, v, (v - med) / mad) for s, v in dense if abs(v - med) / mad > 5),
                           key=lambda t: -abs(t[2]))
            for s, v, z in out_f[:MAX_FLAG_IMAGES]:
                flags.append((r, s, "d32_outlier",
                              f"frame D32 {v:.1f} um vs run median {med:.1f} "
                              f"({z:+.1f} robust SD)"))
    slow = []
    if timings:
        for stage in ("extract_frames_s", "inference_s", "measurement_s", "classical_s"):
            vals = [t[stage] for t in timings.values() if t.get(stage)]
            if len(vals) >= 3:
                med = float(np.median(vals))
                for run, t in timings.items():
                    if t.get(stage) and t[stage] > 2 * med:
                        slow.append(f"{run}: {stage} {t[stage]:.0f} s vs median {med:.0f} s")

    if not flags and not slow:
        return 0
    odd = out / "odd"
    odd.mkdir(parents=True, exist_ok=True)
    with open(odd / "odd_flags.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run", "frame", "category", "why", "images_copied"])
        for r, s, cat, why in flags:
            dst = odd / r["run"][:6] / cat
            dst.mkdir(parents=True, exist_ok=True)
            got = []
            for src, tag in ((r["meas_dir"] / f"{s}.png", "model"),
                             (r["cl_dir"] / "images" / f"{s}.png", "classical")):
                if src.exists():
                    shutil.copy2(src, dst / f"{s}_{tag}.png")
                    got.append(tag)
            w.writerow([r["run"], s, cat, why, "+".join(got) or "none found"])
        for s in slow:
            w.writerow([s.split(":")[0], "", "slow_stage", s, ""])
    return len(flags) + len(slow)


def load_timings(paths):
    t = {}
    for p in paths:
        if not p.exists():
            continue
        with open(p, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "ok":
                    continue
                cur = t.setdefault(row["run"], {})
                for k, v in row.items():
                    if k.endswith("_s") and v not in ("", None):
                        cur[k] = float(v)
    return t


def plot(runs, res, out):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib missing -- plots skipped")
        return
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.5), sharey="row")
    for row, (key, title) in enumerate((("d32", "D32 in-focus (um)  [smaller is better]"),
                                        ("atom", "Atomised fraction, classical (%)  [larger is better]"))):
        nt = res[key]["noise_test"]
        an = res[key]["anova"]
        for col, f in enumerate(FACTORS):
            ax = axes[row, col]
            lv = nt[f]["levels"]
            m = np.array(nt[f]["level_means"])
            ci = np.array(nt[f]["level_ci95"])
            ax.errorbar(range(3), m, yerr=[m - ci[:, 0], ci[:, 1] - m], fmt="o-",
                        capsize=4, color="#2a6fdb" if row == 0 else "#d9822b")
            ax.axhline(np.mean([r[key] for r in runs]), color="grey", lw=0.8, ls="--")
            ax.set_xticks(range(3), [str(x) for x in lv])
            ax.set_xlabel(FACTOR_LABEL[f])
            ax.set_title(f"ANOVA p={an[f]['p']:.3f} | vs noise p={nt[f]['p_vs_noise']:.3f}",
                         fontsize=9)
            if col == 0:
                ax.set_ylabel(title, fontsize=9)
    fig.suptitle("L9 main effects -- level means with 95% bootstrap CI (measurement noise only)")
    fig.tight_layout()
    fig.savefig(out / "main_effects.png", dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    labels = [f"T{i+1}\n{r['levels']['sccm']}/{r['levels']['rpm']}/{r['levels']['sps']}"
              for i, r in enumerate(runs)]
    for ax, key, cikey, col, yl in ((axes[0], "d32", "d32_ci", "#2a6fdb", "D32 in-focus (um)"),
                                    (axes[1], "atom", "atom_ci", "#d9822b", "Atomised, classical (%)")):
        v = np.array([r[key] for r in runs])
        ci = np.array([r[cikey] for r in runs])
        ax.bar(range(len(runs)), v, color=col, alpha=0.75,
               yerr=[v - ci[:, 0], ci[:, 1] - v], capsize=3)
        ax.set_xticks(range(len(runs)), labels, fontsize=7)
        ax.set_ylabel(yl)
    axes[0].set_xlabel("run (sccm / rpm / steps-per-s)")
    axes[1].set_xlabel("run (sccm / rpm / steps-per-s)")
    fig.tight_layout()
    fig.savefig(out / "per_run.png", dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs=9, type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--score-thresh", default="0.30")
    ap.add_argument("--timings", type=Path, nargs="*", default=[],
                    help="timings.csv files from batch_runs.py (later files win)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    runs = [load_run(r, args.score_thresh) for r in args.runs]
    # L9 sanity: every level 3x, every pair of factors fully crossed
    for f in FACTORS:
        counts = defaultdict(int)
        for r in runs:
            counts[r["levels"][f]] += 1
        if sorted(counts.values()) != [3, 3, 3]:
            sys.exit(f"not an L9: {f} levels {dict(counts)}")
    for i, a in enumerate(FACTORS):
        for b in FACTORS[i + 1:]:
            if len({(r["levels"][a], r["levels"][b]) for r in runs}) != 9:
                sys.exit(f"not orthogonal: {a} x {b}")

    rng = np.random.default_rng(SEED)
    for r in runs:
        bootstrap(r, rng)

    res = {}
    for key, kb in (("d32", "boot_d32"), ("atom", "boot_atom")):
        vals = [r[key] for r in runs]
        res[key] = {"anova": anova(runs, vals), "noise_test": noise_test(runs, key, kb)}
    sn = {"d32": [-20 * math.log10(r["d32"]) for r in runs],
          "atom": [20 * math.log10(r["atom"]) for r in runs]}
    for key in sn:
        res[key]["sn_level_means"] = {f: dict(zip(*level_table(runs, sn[key], f)))
                                      for f in FACTORS}

    timings = load_timings(args.timings)
    n_odd = flag_odd(runs, timings, args.out)
    plot(runs, res, args.out)

    # ---- report -----------------------------------------------------------
    L = []
    L.append("# L9 Taguchi results\n")
    L.append("| run | sccm | rpm | sps | frames | D32 um [95% CI] | atomised % classical [95% CI] | (model-only atomised %) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in runs:
        lv = r["levels"]
        L.append(f"| {r['run'][:6]} | {lv['sccm']} | {lv['rpm']} | {lv['sps']} | {len(r['frames'])} "
                 f"| {r['d32']:.2f} [{r['d32_ci'][0]:.2f}, {r['d32_ci'][1]:.2f}] "
                 f"| {r['atom']:.2f} [{r['atom_ci'][0]:.2f}, {r['atom_ci'][1]:.2f}] "
                 f"| {r['model_atom']} |")
    for key, name in (("d32", "D32 (um)"), ("atom", "Atomised fraction, classical (%)")):
        L.append(f"\n## {name}\n")
        L.append("| factor | level means | range | ANOVA F | ANOVA p | % contribution | p vs measurement noise |")
        L.append("|---|---|---|---|---|---|---|")
        an, nt = res[key]["anova"], res[key]["noise_test"]
        for f in FACTORS:
            m = nt[f]["level_means"]
            lvls = ", ".join(f"{l}: {v:.2f}" for l, v in zip(nt[f]["levels"], m))
            L.append(f"| {FACTOR_LABEL[f]} | {lvls} | {max(m) - min(m):.2f} | {an[f]['F']:.2f} "
                     f"| {an[f]['p']:.3f} | {an[f]['contribution_pct']:.1f} | {nt[f]['p_vs_noise']:.4f} |")
        L.append(f"| error (unassigned column) | | | | | {an['error']['contribution_pct']:.1f} | |")
    L.append("\nANOVA: error from the L9's unassigned column, 2 dof -> F(2,2), p = 1/(1+F). "
             "'vs measurement noise': bootstrap over frames; does NOT include run-to-run "
             "repeatability (no replicate runs).")
    if timings:
        L.append("\n## Timings (s)\n")
        stages = sorted({k for t in timings.values() for k in t})
        L.append("| run | " + " | ".join(stages) + " |")
        L.append("|---|" + "---|" * len(stages))
        for r in runs:
            t = timings.get(r["run"], {})
            L.append(f"| {r['run'][:6]} | " + " | ".join(
                f"{t[s]:.0f}" if s in t else "" for s in stages) + " |")
    L.append(f"\nOdd flags: {n_odd}" + (" -- see odd/odd_flags.csv" if n_odd else " (none)"))
    (args.out / "taguchi_report.md").write_text("\n".join(L), encoding="utf-8")

    dump = {"runs": [{"run": r["run"], "levels": r["levels"], "frames": len(r["frames"]),
                      "ci_stride": r["ci_stride"], "n_ci_frames": r["n_ci_frames"],
                      "d32_um": r["d32"], "d32_ci95": list(r["d32_ci"]),
                      "atomised_pct_classical": r["atom"], "atomised_ci95": list(r["atom_ci"]),
                      "atomised_pct_model_only": r["model_atom"]} for r in runs],
            "results": res, "n_boot": N_BOOT, "seed": SEED, "odd_flags": n_odd}
    (args.out / "taguchi_results.json").write_text(json.dumps(dump, indent=2, default=float))
    print("\n".join(L))
    print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
