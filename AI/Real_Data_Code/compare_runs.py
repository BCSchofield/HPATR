#!/usr/bin/env python3
"""
compare_runs.py -- compare N measured runs and say which differences are REAL.

Takes the summary.json files written by measure_run.py and answers the only
question a Taguchi array actually asks: is run A different from run B, or is
the gap inside the measurement noise?

WHY THIS EXISTS AS A TOOL RATHER THAN A GLANCE AT TWO NUMBERS
--------------------------------------------------------------
D32 on this rig currently measures to roughly +/-8% at 20 frames. Two runs
reading 88 um and 93 um look different and are not. Eyeballing the point
estimates is the single easiest way to build a Taguchi table out of noise, and
it is very hard to detect afterwards.

WHAT "DIFFERENT" MEANS HERE
----------------------------
Two runs are called distinguishable when their 95% confidence intervals do not
overlap. That is a deliberately CONSERVATIVE test -- non-overlapping CIs imply
significance at well below p=0.05, so some real differences will be called
"not resolved". For ranking that is the right way to be wrong: it fails to
split runs rather than inventing an order.

The bias in D32 (~+23% against hand labels, from under-detecting small
droplets) CANCELS between runs measured identically, which is why comparison is
valid when the absolute number is not. That only holds if every run used the
same model, threshold and focus cutoff -- so this script refuses to compare runs
that did not, rather than quietly producing a meaningless ranking.

Usage:
    python compare_runs.py A/summary.json B/summary.json C/summary.json
    python compare_runs.py --label 3000sccm A/summary.json --label 4500sccm B/summary.json
"""

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path


def load(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    for k in ("d32_in_focus_um", "d32_ci95", "atomised_pct", "atomised_ci95"):
        if k not in d:
            sys.exit(f"{path} is missing '{k}' -- is it a measure_run.py summary.json?")
    return d


def overlap(a, b):
    """Do two [lo, hi] intervals overlap?"""
    return not (a[1] < b[0] or b[1] < a[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("summaries", nargs="+", type=Path,
                    help="summary.json from measure_run.py, one per run")
    ap.add_argument("--label", action="append", default=None,
                    help="name for each run, in the same order. Defaults to the "
                         "parent folder name.")
    ap.add_argument("--sort-by", choices=("d32", "atomised", "none"), default="d32")
    args = ap.parse_args()

    runs = [load(p) for p in args.summaries]
    if args.label and len(args.label) != len(runs):
        sys.exit(f"{len(args.label)} labels for {len(runs)} runs.")
    labels = args.label or [p.parent.name for p in args.summaries]

    # Refuse to compare incomparable runs. A different threshold, focus cutoff or
    # model changes what the number MEANS, and the bias no longer cancels.
    keys = ("score_threshold", "focus_max", "um_per_px", "ci_stride")
    base = {k: runs[0]["provenance"].get(k) for k in keys}
    mismatched = []
    for lab, r in zip(labels, runs):
        got = {k: r["provenance"].get(k) for k in keys}
        if got != base:
            mismatched.append((lab, got))
    if mismatched:
        print("REFUSING TO COMPARE -- these runs were not measured the same way.\n")
        print(f"  reference ({labels[0]}): {base}")
        for lab, got in mismatched:
            print(f"  {lab}: {got}")
        print("\nThe D32 bias only cancels between runs measured identically.")
        print("Re-measure them with matching --score-thresh / --focus-max.")
        sys.exit(1)

    print(f"comparing {len(runs)} runs at score >= {base['score_threshold']}, "
          f"focus cutoff {base['focus_max']}")

    # A CI built from consecutive frames is roughly 3x too narrow, which makes
    # the REAL/not-resolved verdicts below over-confident. Say so up front --
    # a wrong "REAL" is the failure mode that quietly corrupts a Taguchi table.
    if any(r["provenance"].get("ci_assumes_independence", True) for r in runs):
        print("\n  !! These CIs were computed with --ci-stride 1, i.e. assuming every")
        print("     frame is an independent sample. If the captures were CONSECUTIVE")
        print("     frames, the intervals are ~3x too narrow and the 'REAL' verdicts")
        print("     below are over-confident. Re-measure with --ci-stride 10 (500 fps)")
        print("     before trusting any ranking.")
    print()

    order = list(range(len(runs)))
    if args.sort_by == "d32":
        order.sort(key=lambda i: runs[i]["d32_in_focus_um"])
    elif args.sort_by == "atomised":
        order.sort(key=lambda i: -runs[i]["atomised_pct"])

    print(f"{'run':>22} {'frames':>7} {'droplets':>9} {'D32 um':>9} {'95% CI':>17} "
          f"{'atomised %':>11} {'95% CI':>17}")
    for i in order:
        r, lab = runs[i], labels[i]
        print(f"{lab:>22} {r['frames']:>7} {r['droplets_in_focus']:>9} "
              f"{r['d32_in_focus_um']:>9.1f} "
              f"{'[%.1f, %.1f]' % tuple(r['d32_ci95']):>17} "
              f"{r['atomised_pct']:>11.2f} "
              f"{'[%.2f, %.2f]' % tuple(r['atomised_ci95']):>17}")

    if args.sort_by != "none":
        metric = "D32 (smaller = finer)" if args.sort_by == "d32" else \
                 "atomised fraction (larger = more atomised)"
        print(f"\n  sorted best-first by {metric}")

    print("\n" + "=" * 78)
    print("PAIRWISE -- is the difference real?")
    print("=" * 78)
    any_real = False
    for i, j in combinations(order, 2):
        a, b = runs[i], runs[j]
        la, lb = labels[i], labels[j]
        dd = b["d32_in_focus_um"] - a["d32_in_focus_um"]
        da = b["atomised_pct"] - a["atomised_pct"]
        d_real = not overlap(a["d32_ci95"], b["d32_ci95"])
        a_real = not overlap(a["atomised_ci95"], b["atomised_ci95"])
        any_real |= d_real or a_real
        print(f"\n  {la}  vs  {lb}")
        print(f"    D32       {dd:+7.1f} um   "
              f"{'REAL (CIs do not overlap)' if d_real else 'not resolved -- inside the noise'}")
        print(f"    atomised  {da:+7.2f} pp   "
              f"{'REAL (CIs do not overlap)' if a_real else 'not resolved -- inside the noise'}")

    print("\n" + "=" * 78)
    if not any_real:
        print("NO pair separates on either response.")
        print("Either the conditions genuinely do not differ, or -- more likely --")
        print("there are not enough frames yet. Precision improves as 1/sqrt(n):")
        print("4x the frames halves the interval. Check frame counts above before")
        print("concluding a parameter has no effect.")
    else:
        print("Differences marked REAL clear the measurement noise. Treat anything")
        print("marked 'not resolved' as UNRANKED, not as equal -- absence of")
        print("evidence is not evidence of absence, especially at low frame counts.")
    print("\nReminder: D32 here is 'D32 of confidently-sized droplets', biased high")
    print("by under-detection of small droplets. Valid for ranking, never as an")
    print("absolute droplet size.")


if __name__ == "__main__":
    main()
