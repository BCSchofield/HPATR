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


# ============================================================================
# RESPONSES
#
# D32 alone is not enough and never was. It is Sum(d^3)/Sum(d^2), so it is set
# by the largest few droplets and is nearly blind to the population: a change
# that makes many more small droplets while leaving the big ones alone does not
# move it. Measured on this very campaign, gas flow is significant on droplets
# per frame (p = 0.011), on D90 (p = 0.025) and on mean diameter, while D32
# reads p = 0.064 and looks flat.
#
# An orthogonal array constrains which RUNS you do, not how many things you
# measure from them, so every response below gets its own independent ANOVA on
# the same nine runs.
#
# MULTIPLE COMPARISONS: six responses x three factors is eighteen tests. At
# p < 0.05 you expect roughly one false positive by chance alone. A borderline p
# on one response among many is weaker evidence than a single pre-registered
# test, and the report says so.
#
#   key         label                                    direction  quantised?
RESPONSES = [
    ("d32",       "D32 in-focus (um)",                   "smaller", False),
    ("atom",      "Atomised fraction, classical (%)",    "larger",  False),
    ("d_mean",    "Mean diameter, in-focus (um)",        "smaller", False),
    ("d_median",  "Median diameter, in-focus (um)",      "smaller", True),
    ("d90",       "D90 by count, in-focus (um)",         "smaller", True),
    ("per_frame", "In-focus droplets per frame",         "larger",  False),
    # ---- FLOW CONSISTENCY -------------------------------------------------
    # Everything above is a time-AVERAGE: pool every frame, report one number.
    # A spray that pulses and a spray that runs steadily can give identical
    # averages, so none of the responses above can see steadiness at all. These
    # three measure the frame-to-frame behaviour instead, which is what you see
    # by eye at the atomiser.
    #   cv_droplets  droplet count per frame, std/mean -- spray pulsing
    #   cv_liquid    total liquid px per frame, std/mean -- delivery steadiness,
    #                independent of the model (classical pixels only)
    #   intermit_pct % of frames carrying under 5% of the run's mean droplet
    #                count: outright gaps, not just variation
    # Smaller is better for all three: steadier is better.
    ("cv_droplets", "Droplet-count CV per frame (steadiness)", "smaller", False),
    ("cv_liquid",   "Liquid-area CV per frame (steadiness)",   "smaller", False),
    ("intermit_pct", "Frames near-empty of droplets (%)",      "smaller", False),
]
RESP_KEYS = [k for k, _, _, _ in RESPONSES]
SN_SIGN = {k: (-1 if d == "smaller" else 1) for k, _, d, _ in RESPONSES}
# A response taking fewer than this many distinct values across the nine runs is
# sitting on the integer-pixel lattice rather than on a continuous measurement.
# D10 is the extreme case: 22.568 um on every run, zero variance, so its ANOVA
# would read p = 0.000 while meaning nothing at all.
MIN_DISTINCT = 4


EMPTY_FRAC = 0.05       # "near-empty" = under this fraction of the run's mean


def pooled_responses(dia_by_frame, frames, S3, S2, DP, TP):
    """Every response from one set of frames. Used for both the point estimate
    and each bootstrap replicate, so they cannot drift apart."""
    v = np.concatenate([dia_by_frame[f] for f in frames]) if frames else np.empty(0)
    n_fr = max(len(frames), 1)
    counts = np.array([len(dia_by_frame[f]) for f in frames], dtype=float)
    out = {
        "d32": S3.sum() / S2.sum() if S2.sum() else float("nan"),
        "atom": 100.0 * DP.sum() / TP.sum() if TP.sum() else float("nan"),
        "per_frame": len(v) / n_fr,
    }
    # ---- consistency: spread ACROSS frames, not pooled over them ----
    cmean = counts.mean() if counts.size else 0.0
    out["cv_droplets"] = float(counts.std() / cmean) if cmean > 0 else float("nan")
    out["intermit_pct"] = (100.0 * float((counts < EMPTY_FRAC * cmean).mean())
                           if cmean > 0 else float("nan"))
    tp = np.asarray(TP, dtype=float)
    out["cv_liquid"] = float(tp.std() / tp.mean()) if tp.size and tp.mean() > 0 else float("nan")
    if len(v):
        out["d_mean"] = float(v.mean())
        out["d_median"] = float(np.median(v))
        out["d90"] = float(np.percentile(v, 90))
    else:
        out["d_mean"] = out["d_median"] = out["d90"] = float("nan")
    return out


def load_run(run: Path, thr: str):
    an = run / "shadowgraph" / "analysis"

    def _pick(*names):
        """Accept the current folder name or the historical one.

        Renamed 2026-10-05: measurement_<thr> -> droplets_<thr>, and
        classical_<thr> -> liquid_<thr>. Every run measured before that date
        still carries the old names, and re-measuring 20+ GB to rename a folder
        would be absurd -- so read either and let the writers move forward.
        """
        for n in names:
            if (an / n).is_dir():
                return an / n
        return an / names[0]

    meas = _pick(f"droplets_{thr}", f"measurement_{thr}")
    cl = _pick(f"liquid_{thr}", f"classical_{thr}")
    summ = json.loads((meas / "summary.json").read_text(encoding="utf-8"))
    csumm = json.loads((cl / "classical_summary.json").read_text(encoding="utf-8"))

    s3, s2, nfocus = defaultdict(float), defaultdict(float), defaultdict(int)
    # the diameters themselves, per frame -- a median or a percentile cannot be
    # rebuilt from sums, and the bootstrap has to recompute them per replicate
    dia = defaultdict(list)
    with open(meas / "droplet_sizes.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["in_focus"] == "1":
                d = float(r["diameter_um"])
                s3[r["frame"]] += d ** 3
                s2[r["frame"]] += d ** 2
                nfocus[r["frame"]] += 1
                dia[r["frame"]].append(d)
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
    dia_by_frame = {fr: np.asarray(dia.get(fr, []), dtype=float) for fr in frames}
    rec = {
        "run": run.name, "dir": run, "levels": parse_levels(run.name), "frames": frames,
        "S3": S3, "S2": S2, "DP": DP, "TP": TP, "nfocus": nfocus, "cpf": cpf,
        "dia": dia_by_frame,
        "model_atom": summ.get("atomised_pct"),
        "d32_ci_summary": summ.get("d32_ci95"), "ci_stride": ci_stride,
        "meas_dir": meas, "cl_dir": cl,
        "sizer_version": summ.get("provenance", {}).get("sizer_version"),
    }
    rec.update(pooled_responses(dia_by_frame, frames, S3, S2, DP, TP))
    return rec


def bootstrap(r, rng):
    idx_pool = np.arange(len(r["frames"]))[::max(1, r["ci_stride"])]
    n = len(idx_pool)
    fr = [r["frames"][i] for i in idx_pool]
    base = pooled_responses(r["dia"], fr, r["S3"][idx_pool], r["S2"][idx_pool],
                            r["DP"][idx_pool], r["TP"][idx_pool])
    acc = {k: np.empty(N_BOOT) for k in RESP_KEYS}
    for b in range(N_BOOT):
        i = idx_pool[rng.integers(0, n, n)]
        fb = [r["frames"][j] for j in i]
        rep = pooled_responses(r["dia"], fb, r["S3"][i], r["S2"][i],
                               r["DP"][i], r["TP"][i])
        for k in RESP_KEYS:
            acc[k][b] = rep[k]
    # centre each replicate distribution on the all-frame point estimate
    for k in RESP_KEYS:
        r[f"boot_{k}"] = acc[k] - base[k] + r[k]
        r[f"{k}_ci"] = np.percentile(r[f"boot_{k}"], [2.5, 97.5])
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

    # ---- refuse to analyse runs measured different ways --------------------
    # An L9 is a comparison across nine runs, so a sizing-method change between
    # them is fatal in a way it never is within one run. 2.1.0 moved the
    # atomised fraction ~3% relative against 2.0.0; nothing in the NUMBERS shows
    # that, only the provenance does.
    vers = {}
    for r in runs:
        vers.setdefault(r.get("sizer_version"), []).append(r["run"][:16])
    if len(vers) > 1:
        lines = "\n".join(f"    {v or '(pre-2.0.0, no field)'}: "
                           f"{', '.join(n)}" for v, n in sorted(vers.items(), key=lambda z: str(z[0])))
        sys.exit("REFUSING: these runs were measured with different sizer "
                 f"versions, so their numbers are not comparable.\n{lines}\n"
                 "    Re-measure them all with one version, or analyse each "
                 "group separately.")
    print(f"sizer_version: {next(iter(vers)) or 'pre-2.0.0 (model mask area)'} "
          f"-- consistent across all {len(runs)} runs\n")

    rng = np.random.default_rng(SEED)
    for r in runs:
        bootstrap(r, rng)

    res = {}
    degenerate = []
    for key, label, direction, _flag in RESPONSES:
        vals = [r[key] for r in runs]
        n_distinct = len({round(v, 9) for v in vals if np.isfinite(v)})
        if n_distinct < 2:
            # Zero between-run variance: SS_total is 0, F is infinite and the
            # p-value would print as 0.000 while carrying no information. D10
            # behaves exactly this way -- 22.568 um on all nine runs -- so a
            # degenerate response is reported as degenerate, never as
            # significant.
            degenerate.append((key, label, vals[0] if vals else float("nan")))
            res[key] = {"degenerate": True, "value": vals[0] if vals else None,
                        "n_distinct": n_distinct}
            continue
        res[key] = {"anova": anova(runs, vals),
                    "noise_test": noise_test(runs, key, f"boot_{key}"),
                    "n_distinct": n_distinct,
                    "quantisation_warning": n_distinct < MIN_DISTINCT}
        # S/N is a log, so it is undefined at zero or below. `intermit_pct` is
        # legitimately 0 on a perfectly steady run -- the IDEAL value -- so the
        # ratio is simply not computed there rather than being faked with an
        # epsilon that would invent a number. With one observation per run S/N
        # is a monotone transform of the response anyway and cannot change a
        # ranking; it is reported for completeness only.
        if all(v > 0 for v in vals):
            sn_vals = [SN_SIGN[key] * 20 * math.log10(v) for v in vals]
            res[key]["sn_level_means"] = {f: dict(zip(*level_table(runs, sn_vals, f)))
                                          for f in FACTORS}
        else:
            res[key]["sn_level_means"] = None
            res[key]["sn_note"] = ("not defined: the response reaches 0, which is "
                                   "its ideal value")

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
    if degenerate:
        L.append("\n> **Degenerate responses, excluded from the ANOVA.** These take "
                 "the SAME value on all nine runs, so there is nothing to "
                 "analyse; reporting a p-value for them would be arithmetic on "
                 "zero variance. This is the integer-pixel quantisation the "
                 "size floor work predicted.\n")
        for key, label, v in degenerate:
            L.append(f">  - `{key}` ({label}): {v:.3f} on every run")
        L.append("")
    for key, name, direction, _flag in RESPONSES:
        if res[key].get("degenerate"):
            continue
        better = "smaller is better" if direction == "smaller" else "larger is better"
        L.append(f"\n## {name}  [{better}]\n")
        if res[key].get("quantisation_warning"):
            L.append(f"> **Only {res[key]['n_distinct']} distinct values across the "
                     f"nine runs.** This response is sitting on the integer-pixel "
                     f"lattice, not on a continuous measurement: one run moving by a "
                     f"single quantisation step would change the p-value. Indicative "
                     f"only.\n")
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
    n_live = sum(1 for k in RESP_KEYS if not res[k].get("degenerate"))
    L.append(f"\n**Multiple comparisons.** {n_live} responses x {len(FACTORS)} factors "
             f"= {n_live * len(FACTORS)} tests. At p < 0.05 roughly "
             f"{0.05 * n_live * len(FACTORS):.1f} false positives are expected by "
             f"chance alone, so a borderline p on one response among many is weaker "
             f"evidence than a single pre-chosen test. A factor significant on "
             f"SEVERAL independent responses is the strong case; one marginal p "
             f"standing alone is not.")
    L.append("\n**Why more than one response.** D32 is Sum(d^3)/Sum(d^2), so it is set "
             "by the largest few droplets and is nearly blind to the population: a "
             "change producing many more small droplets, leaving the big ones alone, "
             "does not move it. The count-based responses can see that; D32 cannot. "
             "Reading D32 alone is what made gas flow look insignificant on droplet "
             "size when it is significant on droplets per frame and on D90.")
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
                      "atomised_pct_model_only": r["model_atom"],
                      "sizer_version": r.get("sizer_version"),
                      # every response, with its bootstrap CI
                      "responses": {k: {"value": r[k], "ci95": list(r[f"{k}_ci"])}
                                    for k in RESP_KEYS}} for r in runs],
            "results": res, "n_boot": N_BOOT, "seed": SEED, "odd_flags": n_odd,
            "responses_analysed": RESP_KEYS,
            "n_tests": sum(1 for k in RESP_KEYS if not res[k].get("degenerate"))
                       * len(FACTORS)}
    (args.out / "taguchi_results.json").write_text(json.dumps(dump, indent=2, default=float))
    print("\n".join(L))
    print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
