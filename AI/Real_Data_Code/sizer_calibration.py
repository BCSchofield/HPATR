#!/usr/bin/env python3
"""
sizer_calibration.py -- the edge, the blur-width (chi) rules, the measurement depth and the defocus look-up table of
sizer 3.0.0, from the bead calibration (sizer 3.0.0 plan, Phase 3, 2026-10-16; docs/notes/2026-10-15_sizer_3.0.0_plan.md).

It reads bead_calibration's own outputs (one or more analysis folders):

  * beads_through_focus.csv   static beads of certified size stepped through focus: they BUILD the table;
  * beads_at_focus.csv        the sharpest static beads (chi <= 16 um): they set the EDGE;
  * falling_beads.csv         beads poured through the field, single frames, found by the AI: they CHECK the table
                              and are never used to build it;
  * optionally the pours themselves (--pours): which share of the spheres the AI still calls 'droplet' at each chi.

A size is the half-max diameter on a 4x upsample (bead_calibration.measure_at d_l0.50: what sizer 3.0.0 measures
around each AI mask) minus one fixed edge offset, or Blaisot's contrast-corrected size minus its own offset, whichever
reads the sharp beads of every size better. The table holds, per certified bead size s and blur width chi, how much
larger than s that size reads: Delta(s, chi), the median over the beads and both sides of focus, made to grow with
chi. A droplet's size is the s whose s + Delta(s, chi) equals what it reads, interpolated between the beads' sizes and
with Delta held at the end beads' value beyond them (flagged).

The rules it sets (one chi limit for every size, Ben, 2026-10-15; "confident" = median within +-10 %):

    chi <= chi_sharp              sized directly (blur adds at most 5 % to what each bead size reads at focus)
    chi_sharp < chi <= chi_max    sized through the table
    beyond chi_max                outside the measurement volume
    below d_min                   counted, not sized

chi_max is the smallest of: the widest chi at which the table still sizes every falling bead size within +-10 %,
band by band; at which the AI still calls >= 90 % of the poured spheres 'droplet'; the table's own reach; and the
measurement depth staying the same for every size (+-15 %). chi_max_direct is the single cut to use if the table is
not used: the widest at which direct sizing of a slab of droplets spread evenly through depth stays within +-10 %.

    python sizer_calibration.py "<LaCie>/Calibration/Imaging Work/analysis/2026-10-15" \\
        --pours "<LaCie>/Calibration/Imaging Work/2026/10/15/falling" --out "<...>/analysis/sizer_calibration_2026-10-16"

Writes report.md, sizer_calibration.json, lookup_table.csv, the figures (and pour_classes.csv with --pours) into
--out, and with --write-profile the calibration block of the optics profile. Nothing else.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import optics  # noqa: E402
from blur import size_3, table_size  # noqa: E402,F401  (the table as sizer 3.0.0 applies it)

VERSION = "1.0.0"
SHARP_CHI = 16.0              # at-focus beads used for the edge (best focus reads ~13 um)
MIN_BEADS = 10                # a size needs this many beads to vote on the edge; a table node with fewer is 'thin'
TOL = 0.10                    # "confident": median within +-10 %
SHARP_TOL = 0.05              # chi_sharp: the table's correction within +-5 % at every bead size
DEPTH_TOL = 0.15              # the measurement depth the same for every size, +-15 % (Phase 6)
CLASS_OK = 0.90               # >= 90 % of the spheres called 'droplet'
MIN_BAND_N = 50               # a falling band needs this many beads to count
STAGE_STUCK_UM = 1.0          # the two outermost depths read the same chi: the stage did not move
CHI_GRID = (13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0, 33.0, 36.0, 40.0, 45.0,
            50.0, 55.0, 60.0)
BANDS = (0.0, 16.0, 20.0, 25.0, 30.0, 35.0, 40.0, 50.0, 60.0)
CHI_MAX_STEPS = tuple(np.round(np.arange(14.0, 60.01, 0.5), 1))
BELOW_SMALLEST_BEAD = ("sized through the table up to chi_max, Delta held at the smallest bead's value, down to d_min, "
                       "flagged table_extrapolated: one measurement volume for every size (Ben, 2026-10-16, "
                       "option 1; the reticle's 28 / 19.8 um dots check it)")
BASES = {"halfmax": ("d_l0.50", "half-max on a 4x upsample minus a fixed offset"),
         "blaisot": ("d_blaisot_um", "Blaisot's contrast-corrected size (l = 0.61) minus a fixed offset")}


# ---- reading ---------------------------------------------------------------------------------------------

def _num(v):
    if isinstance(v, str):
        if v in ("True", "False"):
            return v == "True"
        try:
            return float(v)
        except ValueError:
            return v
    return v


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [{k: _num(v) for k, v in r.items()} for r in csv.DictReader(f)]


def _ok(*v) -> bool:
    return all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)


def _med(v) -> float:
    v = [x for x in v if _ok(x)]
    return float(np.median(v)) if v else float("nan")


def _mad(v) -> float:
    v = np.asarray([x for x in v if _ok(x)], float)
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size >= 5 else float("nan")


def stage_end_repeats(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Drop the outermost depth of a series when it reads the same chi, bead by bead, as the one before it although
    the notes say >= 0.5 mm further: the stage was at the end of its travel (2026-10-15: +7 and +8 mm)."""
    drop, notes = set(), []
    for g in sorted({r["group"] for r in rows}):
        rg = [r for r in rows if r["group"] == g]
        zs = sorted({r["z_mm"] for r in rg})
        if len(zs) < 3:
            continue
        for end, prev in ((zs[-1], zs[-2]), (zs[0], zs[1])):
            a = {r["bead"]: r["chi_um"] for r in rg if r["z_mm"] == end and _ok(r.get("chi_um"))}
            b = {r["bead"]: r["chi_um"] for r in rg if r["z_mm"] == prev and _ok(r.get("chi_um"))}
            diff = [abs(a[k] - b[k]) for k in a.keys() & b.keys()]
            if abs(end - prev) >= 0.5 and diff and _med(diff) < STAGE_STUCK_UM:
                drop.add((g, end))
                notes.append(f"{g}: z {end:+g} mm reads as z {prev:+g} mm (median chi difference {_med(diff):.2f} um): "
                             "the stage did not move, dropped")
    return [r for r in rows if (r["group"], r["z_mm"]) not in drop], notes


def read_beads(dirs) -> dict:
    """The bead analysis folders, merged. tau must agree: chi depends on it."""
    through, at_focus, falling, taus, sources = [], [], [], {}, []
    for d in map(Path, dirs):
        cal = next((d / n for n in ("optics_calibration_v1.json", "optics_calibration_v2.json") if (d / n).is_file()),
                   None)
        if cal is not None:
            taus[d.name] = json.loads(cal.read_text(encoding="utf-8")).get("tau")
        for r in read_csv(d / "beads_through_focus.csv"):
            r["group"] = f"{d.name}/{r.get('slide')}"
            through.append(r)
        at_focus += read_csv(d / "beads_at_focus.csv")
        falling += read_csv(d / "falling_beads.csv")
        sources.append(str(d))
    vals = [t for t in taus.values() if _ok(t)]
    if vals and max(vals) - min(vals) > 0.002:
        raise SystemExit(f"tau differs between the analyses ({taus}): chi is not comparable; re-run bead_calibration "
                         "with --tau")
    through, notes = stage_end_repeats(through) if through else ([], [])
    return {"through": through, "at_focus": at_focus, "falling": falling, "tau": vals[0] if vals else None,
            "taus": taus, "sources": sources, "dropped": notes}


# ---- the edge --------------------------------------------------------------------------------------------

def edge(at_focus: list[dict], falling: list[dict]) -> dict:
    """Which size measure reads the sharp static beads best, and its offset. Each size with >= MIN_BEADS sharp beads
    has one vote: the offset is the median over sizes of each size's median (measured - certified)."""
    sharp = [r for r in at_focus if _ok(r.get("chi_um")) and r["chi_um"] <= SHARP_CHI]
    sizes = sorted(s for s in {r["certified_um"] for r in sharp}
                   if sum(r["certified_um"] == s for r in sharp) >= MIN_BEADS)
    out = {"sharp_chi_um": SHARP_CHI, "sizes_um": sizes,
           "n_beads": {f"{s:g}": sum(r["certified_um"] == s for r in sharp) for s in sizes}, "bases": {}}
    for base, (col, what) in BASES.items():
        per = {s: _med([r.get(col) - s for r in sharp if r["certified_um"] == s and _ok(r.get(col))]) for s in sizes}
        delta = _med(list(per.values()))
        bias = {s: _med([(r[col] - delta) / s - 1 for r in sharp if r["certified_um"] == s and _ok(r.get(col))])
                for s in sizes}
        fall = [r for r in falling if r.get("isolated") is True and _ok(r.get("chi_um"), r.get(col))
                and r["chi_um"] <= SHARP_CHI]
        fper = {s: _med([r[col] - s for r in fall if r["certified_um"] == s])
                for s in sorted({r["certified_um"] for r in fall})}
        out["bases"][base] = {"column": col, "what": what, "offset_um": round(delta, 2),
                              "offset_by_size_um": {f"{s:g}": round(v, 2) for s, v in per.items()},
                              "bias_by_size_pct": {f"{s:g}": round(100 * v, 1) for s, v in bias.items()},
                              "max_abs_bias_pct": round(100 * max(abs(v) for v in bias.values()), 1) if bias else None,
                              "falling_sharp_offset_by_size_um": {f"{s:g}": round(v, 2) for s, v in fper.items()},
                              "falling_sharp_offset_um": round(_med(list(fper.values())), 2) if fper else None}
    # a single grey level (static only: the pours were measured at half-max), for comparison
    levels = sorted({float(k[3:]) for r in sharp[:1] for k in r if k.startswith("d_l")})
    lv = {}
    for l in levels:
        b = {s: _med([r[f"d_l{l:.2f}"] / s - 1 for r in sharp if r["certified_um"] == s and _ok(r.get(f"d_l{l:.2f}"))])
             for s in sizes}
        if b and all(_ok(v) for v in b.values()):
            lv[f"{l:.2f}"] = {"bias_by_size_pct": {f"{s:g}": round(100 * v, 1) for s, v in b.items()},
                              "max_abs_bias_pct": round(100 * max(abs(v) for v in b.values()), 1)}
    out["levels"] = lv
    out["best_level"] = min(lv, key=lambda k: lv[k]["max_abs_bias_pct"]) if lv else None
    ranked = sorted((b for b in out["bases"] if out["bases"][b]["max_abs_bias_pct"] is not None),
                    key=lambda b: out["bases"][b]["max_abs_bias_pct"])
    out["base"] = ranked[0] if ranked else "halfmax"
    out["offset_um"] = out["bases"][out["base"]]["offset_um"]
    out["column"] = BASES[out["base"]][0]
    return out


def base_size(r: dict, e: dict) -> float:
    v = r.get(e["column"])
    return v - e["offset_um"] if _ok(v) else float("nan")


# ---- blur against depth ----------------------------------------------------------------------------------

def chi_fit(z, chi) -> dict:
    """chi = sqrt(chi0^2 + (k (z - zf))^2), a slope k each side of focus (the beads are not symmetric about it):
    zf and chi0 searched, each k by least squares."""
    z, chi = np.asarray(z, float), np.asarray(chi, float)
    ok = np.isfinite(z) & np.isfinite(chi)
    z, chi = z[ok], chi[ok]
    if z.size < 5:
        return {}
    best = None
    c0s = np.arange(5.0, min(25.0, chi.min() + 0.05), 0.05)
    for zf in np.arange(max(z.min(), -2.0), min(z.max(), 2.0) + 1e-9, 0.01):
        u = np.abs(z - zf)
        lo, hi = z < zf, z >= zf
        for c0 in c0s:
            y = np.sqrt(np.maximum(chi ** 2 - c0 ** 2, 0.0))
            ks = []
            for side in (lo, hi):
                den = float((u[side] ** 2).sum())
                ks.append(float((u[side] * y[side]).sum() / den) if den > 0 else 0.0)
            k = np.where(lo, ks[0], ks[1])
            sse = float(((np.sqrt(c0 ** 2 + (k * u) ** 2) - chi) ** 2).sum())
            if best is None or sse < best[0]:
                best = (sse, float(zf), float(c0), ks[0], ks[1])
    if best is None:
        return {}
    sse, zf, c0, km, kp = best
    return {"zf_mm": round(zf, 2), "chi0_um": round(c0, 2), "k_minus_um_per_mm": round(km, 2),
            "k_plus_um_per_mm": round(kp, 2), "k_um_per_mm": round((km + kp) / 2, 2),
            "rms_um": round(math.sqrt(sse / z.size), 2)}


def z_weights(zs) -> dict:
    """Trapezoid weights (mm) of a set of depths: a droplet is equally likely anywhere in depth, the steps are not
    even (0.2 mm near focus, 1 mm far out)."""
    zs = sorted(set(zs))
    w = {z: 0.0 for z in zs}
    for a, b in zip(zs[:-1], zs[1:]):
        w[a] += (b - a) / 2
        w[b] += (b - a) / 2
    return w


def depth_and_bias(rows: list[dict], e: dict, chi_maxes=CHI_MAX_STEPS) -> dict:
    """For one size on one slide, per chi limit: the measurement depth (the integral over z of the share of beads
    with chi <= the limit) and the median direct size error of a slab of droplets spread evenly through it."""
    w = z_weights([r["z_mm"] for r in rows])
    nz = {z: sum(1 for r in rows if r["z_mm"] == z) for z in w}
    ends = (min(w), max(w))
    s = rows[0]["certified_um"]
    out = {}
    for cm in chi_maxes:
        acc = [r for r in rows if _ok(r.get("chi_um")) and r["chi_um"] <= cm]
        ww = np.asarray([w[r["z_mm"]] / nz[r["z_mm"]] for r in acc], float)
        v = np.asarray([base_size(r, e) / s - 1 for r in acc], float)
        good = np.isfinite(v)
        out[cm] = {"depth_mm": round(float(ww.sum()), 3),
                   "bias": _wmedian(v[good], ww[good]) if good.any() else float("nan"),
                   "open": any(r["z_mm"] in ends for r in acc)}
    return out


def _wmedian(v, w) -> float:
    o = np.argsort(v)
    v, w = np.asarray(v)[o], np.asarray(w)[o]
    c = np.cumsum(w)
    return float(np.interp(0.5 * c[-1], c, v))


# ---- the look-up table -----------------------------------------------------------------------------------

def _pav(y, w):
    """Pool-adjacent-violators: the closest non-decreasing sequence (weighted least squares)."""
    blocks = [[float(a), float(b), 1] for a, b in zip(y, w)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            a, b = blocks[i], blocks[i + 1]
            blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / (a[1] + b[1]), a[1] + b[1], a[2] + b[2]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    return np.concatenate([[b[0]] * b[2] for b in blocks])


def build_table(rows: list[dict], e: dict, chi_grid=CHI_GRID) -> dict:
    """Delta(s, chi) = median(size read - s) over the static beads of size s whose chi falls nearest each grid point,
    both sides of focus pooled (droplets sit on both), made non-decreasing in chi; sigma = the beads' robust
    scatter there. A size's row ends where its beads end (nan beyond)."""
    g = np.asarray(chi_grid, float)
    edges = np.concatenate([[0.0], (g[1:] + g[:-1]) / 2, [g[-1] + (g[-1] - g[-2]) / 2]])
    nodes = sorted({r["certified_um"] for r in rows})
    T = {"chi_um": g.tolist(), "nodes_um": nodes, "delta_um": [], "sigma_um": [], "n": [], "beads": [],
         "base": e["base"], "offset_um": e["offset_um"]}
    for s in nodes:
        rs = [r for r in rows if r["certified_um"] == s and _ok(r.get("chi_um"))]
        c = np.asarray([r["chi_um"] for r in rs], float)
        dv = np.asarray([base_size(r, e) - s for r in rs], float)
        med, n, sig = [], [], []
        for a, b in zip(edges[:-1], edges[1:]):
            m = (c >= a) & (c < b) & np.isfinite(dv)
            n.append(int(m.sum()))
            med.append(float(np.median(dv[m])) if m.any() else float("nan"))
            sig.append(_mad(dv[m]))
        med, n = np.asarray(med), np.asarray(n)
        ok = n > 0
        d = np.full(g.size, np.nan)
        if ok.any():
            mono = _pav(med[ok], n[ok])
            last = int(np.nonzero(ok)[0].max())
            d[:last + 1] = np.interp(g[:last + 1], g[ok], mono)
        T["delta_um"].append([round(float(x), 3) for x in d])
        T["sigma_um"].append([round(float(x), 3) for x in sig])
        T["n"].append(n.tolist())
        T["beads"].append(len({(r["group"], r.get("bead")) for r in rs}))
    # sigma where a size has too few beads in a bin: the largest of the others there, else the overall median
    S = np.asarray(T["sigma_um"], float)
    fallback = float(np.nanmedian(S)) if np.isfinite(S).any() else 2.0
    for j in range(S.shape[1]):
        col = S[:, j]
        fill = float(np.nanmax(col)) if np.isfinite(col).any() else fallback
        S[~np.isfinite(col), j] = fill
    T["sigma_um"] = [[round(float(x), 3) for x in row] for row in S]
    D = np.asarray(T["delta_um"], float)
    reach = [float(g[np.isfinite(row)].max()) for row in D if np.isfinite(row).any()]
    T["chi_reach_um"] = min(reach) if reach else None
    T["thin_nodes_um"] = [s for s, b in zip(nodes, T["beads"]) if b < MIN_BEADS]
    return T


# ---- the checks ------------------------------------------------------------------------------------------

def _bands(bands=BANDS):
    return list(zip(bands[:-1], bands[1:]))


def falling_check(falling: list[dict], e: dict, T: dict, chi_sharp: float, bands=BANDS) -> dict:
    """The falling beads band by band: direct, through the table, and the 3.0.0 rule (direct up to chi_sharp)."""
    rows = [r for r in falling if r.get("isolated") is True and _ok(r.get("chi_um"))]
    out = {}
    for s in sorted({r["certified_um"] for r in rows}):
        rs = [r for r in rows if r["certified_um"] == s]
        chi = np.asarray([r["chi_um"] for r in rs], float)
        d = np.asarray([base_size(r, e) for r in rs], float)
        t, _sg, where = table_size(d, chi, T)
        rule, _m = size_3(d, chi, T, chi_sharp, float(max(bands)))
        per = []
        for a, b in _bands(bands):
            m = (chi >= a) & (chi < b) & np.isfinite(d)
            mt = m & np.isfinite(t)
            per.append({"band": [a, b], "n": int(m.sum()),
                        "direct_pct": round(100 * (_med(d[m]) / s - 1), 1) if m.sum() >= MIN_BAND_N else None,
                        "table_pct": round(100 * (_med(t[mt]) / s - 1), 1) if mt.sum() >= MIN_BAND_N else None,
                        "rule_pct": round(100 * (_med(rule[mt]) / s - 1), 1) if mt.sum() >= MIN_BAND_N else None,
                        "rule_scatter_pct": round(100 * _mad(rule[mt]) / s, 1) if mt.sum() >= MIN_BAND_N else None,
                        "extrapolated_share": round(float(np.mean(where[mt] != "in")), 3) if mt.any() else None})
        out[f"{s:g}"] = per
    return out


def check_limit(check: dict, key: str = "rule_pct", tol: float = TOL) -> tuple[float | None, str]:
    """The widest band edge up to which every size with data stays within tol in every band."""
    edges = sorted({b["band"][1] for v in check.values() for b in v})
    reach, why = None, ""
    for hi in edges:
        bad = [(s, b[key]) for s, v in check.items() for b in v
               if b["band"][1] == hi and b[key] is not None and abs(b[key]) > 100 * tol]
        if bad:
            why = ", ".join(f"{s} um reads {v:+.1f} % at chi {hi:g}" for s, v in bad)
            break
        reach = hi
    return reach, why


def class_share(pour_rows: list[dict], bands=BANDS) -> dict:
    """Per size and chi band, the share of the isolated poured spheres the AI calls 'droplet'; and per size where its
    'filament' / 'blob' calls sit, and how many detections have no chi at all (Phase 4 must say what they count as)."""
    iso = [r for r in pour_rows if r.get("isolated") is True]
    out = {}
    for s in sorted({r["certified_um"] for r in iso}):
        ri = [r for r in iso if r["certified_um"] == s]
        rs = [r for r in ri if _ok(r.get("chi_um"))]
        per = []
        for a, b in _bands(bands):
            m = [r for r in rs if a <= r["chi_um"] < b]
            per.append({"band": [a, b], "n": len(m),
                        "droplet_share": round(sum(r["cls"] == "droplet" for r in m) / len(m), 3)
                        if len(m) >= MIN_BAND_N else None})
        other = [r["chi_um"] for r in rs if r["cls"] != "droplet"]
        drops = [r for r in ri if r["cls"] == "droplet"]
        out[f"{s:g}"] = {"bands": per, "non_droplet_n": sum(r["cls"] != "droplet" for r in ri),
                         "non_droplet_chi_median_um": round(_med(other), 1) if other else None,
                         "non_droplet_beyond_last_band_share": round(sum(c >= bands[-1] for c in other) / len(other), 3)
                         if other else None,
                         "droplet_no_chi_share": round(sum(not _ok(r.get("chi_um")) for r in drops) / len(drops), 3)
                         if drops else None}
    return out


def class_limit(share: dict, ok: float = CLASS_OK) -> tuple[float | None, str]:
    edges = sorted({b["band"][1] for v in share.values() for b in v["bands"]})
    reach, why = None, ""
    for hi in edges:
        bad = [(s, b["droplet_share"]) for s, v in share.items() for b in v["bands"]
               if b["band"][1] == hi and b["droplet_share"] is not None and b["droplet_share"] < ok]
        if bad:
            why = ", ".join(f"{s} um: {100 * v:.0f} % called droplet below chi {hi:g}" for s, v in bad)
            break
        reach = hi
    return reach, why


def pour_classes(run: Path, cert: float, tau: float, frame_step: int = 1) -> list[dict]:
    """Every AI detection of one pour, all classes, with its blur width (bead_calibration.measure_at at the mask's
    centroid): every object in a pour is a sphere, so the share called 'droplet' at each chi is how far out of
    focus the AI still recognises one. Reads the run's predictions.json, instances.json, background and frames."""
    from collections import defaultdict
    import cv2
    import bead_calibration as bc
    import measure_run as mr
    sg = run / "shadowgraph"
    names = {im["id"]: Path(im["file_name"]).stem
             for im in json.loads((sg / "raw" / "instances.json").read_text(encoding="utf-8"))["images"]}
    bg = cv2.imread(str(sg / "raw" / "background_median.tiff"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    by = defaultdict(list)
    for d in json.loads((sg / "analysis" / "predictions.json").read_text(encoding="utf-8")):
        if d["score"] >= 0.30 and not d.get("truncated", False):
            by[d["image_id"]].append(d)
    rows = []
    for img_id in sorted(by)[::max(1, frame_step)]:
        T = mr.transmission(sg / "raw" / "frames" / "16bit", names.get(img_id, ""), bg)
        if T is None:
            continue
        dets = []
        for d in by[img_id]:
            mb, bx, by_, _bh, _bw = mr.det_crop(d)
            if not mb.any():
                continue
            ys, xs = np.nonzero(mb)
            dets.append((bx + float(xs.mean()), by_ + float(ys.mean()), 2 * math.sqrt(float(d["area"]) / math.pi),
                         {mr.DROPLET: "droplet", mr.FILAMENT: "filament"}.get(d["category_id"], "blob")))
        pts = np.asarray([[x, y] for x, y, _d, _c in dets], float)
        for i, (cx, cy, dpx, cls) in enumerate(dets):
            dist = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
            dist[i] = np.inf
            nn = float(dist.min()) if len(dets) > 1 else float("inf")
            r = bc.measure_at(T, cx, cy, dpx, tau, levels=()) or {}
            rows.append({"run": run.name, "certified_um": cert, "frame": names[img_id], "cls": cls,
                         "ai_d_um": round(dpx * bc.UM_PER_PX, 2), "isolated": bool(nn > 2 * dpx + 2),
                         "chi_um": r.get("chi_um", float("nan")), "d_l0.50": r.get("d_l0.50", float("nan"))})
    return rows


# ---- choosing --------------------------------------------------------------------------------------------

def chi_sharp_from(T: dict, tol: float = SHARP_TOL, steps=CHI_MAX_STEPS) -> float:
    """The widest chi up to which blur adds no more than tol of the size to what a bead reads at best focus, at every
    bead size that is not thin: there, direct sizing and the table agree. (Growth from focus, not Delta itself: what
    one bead batch reads at focus, e.g. 56.28 um ~2 um high, is the edge offset's business, shared by all sizes.)"""
    g = np.asarray(T["chi_um"], float)
    best = float(g.min())
    for cm in steps:
        ok = True
        for s, row, b in zip(T["nodes_um"], T["delta_um"], T["beads"]):
            if b < MIN_BEADS:
                continue
            row = np.asarray(row, float)
            fin = np.isfinite(row)
            xs = np.concatenate([g[fin][g[fin] <= cm], [cm]])
            if np.any(np.abs(np.interp(xs, g[fin], row[fin]) - row[fin][0]) / s > tol):
                ok = False
        if not ok:
            break
        best = float(cm)
    return best


def table_scatter(T: dict) -> float:
    """The table's precision on the static beads: the median over the solid bead sizes and chi of sigma / size."""
    v = [sg / s for s, row, b in zip(T["nodes_um"], T["sigma_um"], T["beads"]) if b >= MIN_BEADS
         for sg in row if _ok(sg)]
    return float(np.median(v)) if v else float("nan")


def candidates(B: dict, e: dict) -> dict:
    """Both size measures carried through: table, chi_sharp and the falling check, so the report shows both."""
    out = {}
    for b in BASES:
        eb = {**e, "base": b, "offset_um": e["bases"][b]["offset_um"], "column": BASES[b][0]}
        T = build_table(B["through"], eb)
        cs = chi_sharp_from(T)
        ck = falling_check(B["falling"], eb, T, cs)
        lim, why = check_limit(ck)
        inside = [x for v in ck.values() for x in v if x["rule_pct"] is not None and lim and x["band"][1] <= lim]
        out[b] = {"edge": eb, "table": T, "chi_sharp_um": cs, "check": ck, "check_limit_um": lim, "check_why": why,
                  "at_focus_worst_pct": e["bases"][b]["max_abs_bias_pct"],
                  "static_scatter_pct": round(100 * table_scatter(T), 2),
                  "check_worst_pct": round(max(abs(x["rule_pct"]) for x in inside), 1) if inside else None,
                  "check_scatter_pct": round(_med([x["rule_scatter_pct"] for x in inside]), 1) if inside else None}
    return out


def choose_base(cands: dict) -> tuple[str, str]:
    """The plan's rule: the measure that reads the sharp beads of every size best. Within 1 point of each other that
    is noise, so then the one whose table is more precise on the static beads (never the falling ones: they check)."""
    by_focus = sorted(cands, key=lambda b: cands[b]["at_focus_worst_pct"])
    a, b = by_focus[0], by_focus[1]
    if cands[b]["at_focus_worst_pct"] - cands[a]["at_focus_worst_pct"] >= 1.0:
        return a, f"it reads the sharp beads best (worst {cands[a]['at_focus_worst_pct']} % against " \
                  f"{cands[b]['at_focus_worst_pct']} %)"
    best = min(cands, key=lambda k: cands[k]["static_scatter_pct"])
    other = [k for k in cands if k != best][0]
    return best, (f"the sharp beads read alike (worst {cands[a]['at_focus_worst_pct']} % / "
                  f"{cands[b]['at_focus_worst_pct']} %), so the more precise table on the static beads "
                  f"(scatter {cands[best]['static_scatter_pct']} % of the size against "
                  f"{cands[other]['static_scatter_pct']} %)")


def d_min_for(chi_sharp: float, provisional: dict) -> tuple[float | None, str]:
    """Phase 2's model d_min at the narrowest chi limit it tried that is >= chi_sharp."""
    tried = sorted((float(k.split("_")[2]), v) for k, v in provisional.items() if k.startswith("chi_max_"))
    for cm, v in tried:
        if cm >= chi_sharp - 1e-9:
            return v, f"Phase 2 model, chi <= {cm:g} um"
    return (tried[-1][1], f"Phase 2 model, chi <= {tried[-1][0]:g} um (the widest it tried)") if tried else (None, "")


def analyse(dirs, out: Path, profile: dict, pours: Path | None = None, pour_csv: Path | None = None,
            frame_step: int = 1) -> dict:
    B = read_beads(dirs)
    if not B["through"]:
        raise SystemExit("no beads_through_focus.csv rows in " + ", ".join(map(str, dirs)))
    out.mkdir(parents=True, exist_ok=True)
    e = edge(B["at_focus"], B["falling"])
    cands = candidates(B, e)
    base, why_base = choose_base(cands)
    e = cands[base]["edge"]

    # blur against depth, depth and direct bias, per slide and size
    fits, dep = {}, {}
    for g in sorted({r["group"] for r in B["through"]}):
        for s in sorted({r["certified_um"] for r in B["through"] if r["group"] == g}):
            rows = [r for r in B["through"] if r["group"] == g and r["certified_um"] == s]
            zs = sorted({r["z_mm"] for r in rows})
            fits[f"{g} {s:g}"] = {"certified_um": s, "beads": len({r.get("bead") for r in rows}),
                                  **chi_fit(zs, [_med([r.get("chi_um") for r in rows if r["z_mm"] == z]) for z in zs])}
            dep[f"{g} {s:g}"] = {"certified_um": s, "beads": len({r.get("bead") for r in rows}),
                                 "by_chi_max": depth_and_bias(rows, e)}
    solid = [k for k, v in dep.items() if v["beads"] >= MIN_BEADS]
    chi0 = _med([fits[k].get("chi0_um") for k in solid])
    kk = _med([fits[k].get("k_um_per_mm") for k in solid])

    def depth_spread(cm):
        d = [dep[k]["by_chi_max"][cm]["depth_mm"] for k in solid]
        return (max(d) - min(d)) / 2 / np.mean(d) if d and np.mean(d) > 0 else float("nan")

    def direct_ok(cm):
        return all(abs(dep[k]["by_chi_max"][cm]["bias"]) <= TOL for k in solid)

    chi_max_direct = None
    for cm in CHI_MAX_STEPS:
        if not direct_ok(cm):
            break
        chi_max_direct = float(cm)

    T, chi_sharp, check = cands[base]["table"], cands[base]["chi_sharp_um"], cands[base]["check"]
    lim_check, why_check = cands[base]["check_limit_um"], cands[base]["check_why"]

    pour_rows = []
    if pour_csv is not None:
        pour_rows = read_csv(pour_csv)
    elif pours is not None:
        for run in sorted(p for p in Path(pours).iterdir() if p.is_dir() and (p / "shadowgraph").is_dir()):
            toks = run.name.split()
            cert = next((float(t) for t in toks if _ok(_num(t))), None)
            if cert is not None:
                pour_rows += pour_classes(run, cert, float(B["tau"] or 0.1), frame_step)
        if pour_rows:
            with open(out / "pour_classes.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(pour_rows[0]))
                w.writeheader()
                w.writerows(pour_rows)
    share = class_share(pour_rows) if pour_rows else {}
    lim_class, why_class = class_limit(share) if share else (None, "no pours given")

    limits = {"falling check (+-10 % every size, every band)": (lim_check, why_check),
              "AI calls >= 90 % of spheres 'droplet'": (lim_class, why_class),
              "the table's reach (every bead size has data)": (T["chi_reach_um"], "")}
    found = {k: v for k, v in limits.items() if v[0] is not None}
    chi_max = min(v[0] for v in found.values()) if found else None
    set_by = min(found, key=lambda k: found[k][0]) if found else None
    if chi_max is not None:
        chi_max = float(max(c for c in CHI_MAX_STEPS if c <= chi_max))
        # the depth must be the same for every size there (+-15 %), else narrower
        while depth_spread(chi_max) > DEPTH_TOL and chi_max > CHI_MAX_STEPS[0]:
            chi_max = float(max(c for c in CHI_MAX_STEPS if c < chi_max))
            set_by = "depth the same for every size (+-15 %)"
    limits["depth the same for every size (+-15 %)"] = (
        chi_max, f"spread +-{100 * depth_spread(chi_max):.1f} % there" if chi_max is not None else "")

    prov = (profile.get("calibration") or {}).get("d_min_provisional") or {}
    d_min, d_min_src = d_min_for(chi_sharp, prov)

    def depth_at(cm):
        if cm is None:
            return None
        cm = max(c for c in CHI_MAX_STEPS if c <= cm)
        by = {k: dep[k]["by_chi_max"][cm]["depth_mm"] for k in dep}
        return {"chi_um": cm, "mean_mm": round(float(np.mean([by[k] for k in solid])), 2),
                "spread_pct": round(100 * depth_spread(cm), 1), "by_slide_and_size_mm": by}

    R = {"version": VERSION, "made": datetime.now().isoformat(timespec="seconds"), "inputs": B["sources"],
         "tau": B["tau"], "stage_end_dropped": B["dropped"], "edge": e, "base_chosen_because": why_base,
         "candidates": {b: {k: v for k, v in c.items() if k not in ("edge", "table")} for b, c in cands.items()},
         "chi_of_z": fits, "chi0_um": round(chi0, 2), "chi_k_um_per_mm": round(kk, 2),
         "depth": {k: {"certified_um": v["certified_um"], "beads": v["beads"],
                       "by_chi_max": {f"{cm:g}": {"depth_mm": x["depth_mm"], "direct_bias_pct": round(100 * x["bias"], 1)
                                                  if _ok(x["bias"]) else None, "open": x["open"]}
                                      for cm, x in v["by_chi_max"].items()}} for k, v in dep.items()},
         "table": T, "falling_check": check, "class_share": share,
         "chi_sharp_um": chi_sharp, "chi_max_um": chi_max, "chi_max_set_by": set_by,
         "chi_max_limits": {k: {"chi_um": v[0], "why": v[1]} for k, v in limits.items()},
         "chi_max_direct_um": chi_max_direct, "d_min_um": d_min, "d_min_source": d_min_src,
         "depth_sharp": depth_at(chi_sharp), "depth_max": depth_at(chi_max), "depth_direct": depth_at(chi_max_direct)}
    _write_table_csv(out / "lookup_table.csv", T)
    figs = _figures(out, R, B)
    (out / "sizer_calibration.json").write_text(json.dumps(R, indent=1, default=_json), encoding="utf-8")
    (out / "report.md").write_text(report(R, figs), encoding="utf-8")
    R["_files"] = [str(out / n) for n in ("sizer_calibration.json", "report.md", "lookup_table.csv")] + \
        [str(f) for f in figs] + ([str(out / "pour_classes.csv")] if (out / "pour_classes.csv").is_file() else [])
    return R


def _json(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _write_table_csv(path: Path, T: dict):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["certified_um", "beads"] + [f"delta_um_chi{c:g}" for c in T["chi_um"]] +
                   [f"sigma_um_chi{c:g}" for c in T["chi_um"]])
        for s, b, d, sg in zip(T["nodes_um"], T["beads"], T["delta_um"], T["sigma_um"]):
            w.writerow([s, b] + d + sg)


# ---- the profile -----------------------------------------------------------------------------------------

def profile_block(R: dict, source: str) -> dict:
    """The calibration block of the optics profile (Phase 4 reads it)."""
    T = R["table"]
    nodes = ", ".join(f"{s:g} um ({b} beads)" for s, b in zip(T["nodes_um"], T["beads"]))
    checked = sorted(float(s) for s in R["falling_check"])
    return {
        "status": f"Provisional (sizer 3.0.0 Phase 3, {R['made'][:10]}). The table is built on static beads through "
                  f"focus: {nodes}; Delta is held at the end beads' value beyond them. The falling beads check it"
                  + (f" from {checked[0]:g} to {checked[-1]:g} um" if checked else "") + ". Sizes beyond the table's "
                  "beads stay provisional until static beads of those sizes (the big-bead through-focus series) or "
                  "the PS20 reticle's dots (below 37 um; profile v2) are in.",
        "size_measure": R["edge"]["column"] + " (blur.measure around the AI mask, as bead_calibration measured the beads)",
        "edge_level": 0.5 if R["edge"]["base"] == "halfmax" else 0.61,
        "edge_base": R["edge"]["base"],
        "edge_offset_um": R["edge"]["offset_um"],
        "tau": R["tau"],
        "chi0_um": R["chi0_um"],
        "chi_k_um_per_mm": R["chi_k_um_per_mm"],
        "chi_sharp_um": R["chi_sharp_um"],
        "chi_max_um": R["chi_max_um"],
        "chi_max_direct_um": R["chi_max_direct_um"],
        "d_min_um": R["d_min_um"],
        "d_min_source": R["d_min_source"],
        "depth_mm": {"chi_sharp": (R["depth_sharp"] or {}).get("mean_mm"),
                     "chi_max": (R["depth_max"] or {}).get("mean_mm"),
                     "chi_max_direct": (R["depth_direct"] or {}).get("mean_mm")},
        "lookup_table": {"chi_um": T["chi_um"], "nodes_um": T["nodes_um"], "beads": T["beads"],
                         "delta_um": T["delta_um"], "sigma_um": T["sigma_um"], "chi_reach_um": T["chi_reach_um"],
                         "measured_range_um": [min(T["nodes_um"]), max(T["nodes_um"])],
                         "thin_nodes_um": T["thin_nodes_um"],
                         "beyond": "Delta held at the end bead's value (flagged table_extrapolated)"},
        "below_smallest_bead": BELOW_SMALLEST_BEAD,
        "source": source,
    }


def write_profile(path: Path, block: dict) -> None:
    """Fill the profile's calibration block, keeping what Phase 2 wrote (d_min_provisional)."""
    p = json.loads(path.read_text(encoding="utf-8"))
    cal = p.get("calibration") or {}
    keep = {k: cal[k] for k in ("d_min_provisional",) if k in cal}
    p["calibration"] = {**block, **keep}
    src = f"LaCie: {block['source']} (sizer calibration, Phase 3, 2026-10-16)"
    p["sources"] = [s for s in p.get("sources", []) if "sizer calibration" not in s] + [src]
    path.write_text(json.dumps(p, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# ---- figures and report ----------------------------------------------------------------------------------

COLOURS = {37.36: "#2a7de1", 56.28: "#d9822b", 76.39: "#3a9b5c", 98.1: "#9c4dc4", 155.8: "#c23b3b"}


def _figures(out: Path, R: dict, B: dict) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figs = []
    T, e = R["table"], R["edge"]
    # 1. the table, with the falling beads' own medians over it
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    g = np.asarray(T["chi_um"])
    for s, d, sg, b in zip(T["nodes_um"], T["delta_um"], T["sigma_um"], T["beads"]):
        d, sg = np.asarray(d, float), np.asarray(sg, float)
        c = COLOURS.get(s, "k")
        ax.plot(g, d, "-", color=c, lw=2, label=f"{s:g} um static ({b} beads)")
        ax.fill_between(g, d - sg, d + sg, color=c, alpha=0.12)
    fall = [r for r in B["falling"] if r.get("isolated") is True and _ok(r.get("chi_um"))]
    for s in sorted({r["certified_um"] for r in fall}):
        mids, meds = [], []
        for a, b in _bands():
            v = [base_size(r, e) - s for r in fall if r["certified_um"] == s and a <= r["chi_um"] < b]
            if len(v) >= MIN_BAND_N:
                mids.append(_med([r["chi_um"] for r in fall if r["certified_um"] == s and a <= r["chi_um"] < b]))
                meds.append(_med(v))
        ax.plot(mids, meds, "o--", color=COLOURS.get(s, "k"), ms=5, mfc="white", lw=0.8, label=f"{s:g} um falling")
    for x, lab in ((R["chi_sharp_um"], "chi_sharp"), (R["chi_max_um"], "chi_max")):
        if x:
            ax.axvline(x, color="k", ls=":", lw=0.8)
            ax.text(x, ax.get_ylim()[1] * 0.95, " " + lab, fontsize=8, va="top")
    ax.set(xlabel="blur width chi (um)", ylabel="size read - certified (um)",
           title="The look-up table: how much larger each bead size reads, by blur")
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    figs.append(out / "fig_table.png")
    fig.savefig(figs[-1], dpi=130)
    plt.close(fig)
    # 2. the check
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    for s, per in R["falling_check"].items():
        mids = [(b["band"][0] + b["band"][1]) / 2 if b["band"][0] > 0 else 14.0 for b in per]
        c = COLOURS.get(float(s), "k")
        ax.plot(mids, [b["rule_pct"] if b["rule_pct"] is not None else np.nan for b in per], "o-", color=c,
                label=f"{s} um, 3.0.0 rule")
        ax.plot(mids, [b["direct_pct"] if b["direct_pct"] is not None else np.nan for b in per], "x:", color=c,
                alpha=0.6)
    ax.axhspan(-100 * TOL, 100 * TOL, color="#3a9b5c", alpha=0.08)
    for x in (R["chi_sharp_um"], R["chi_max_um"]):
        if x:
            ax.axvline(x, color="k", ls=":", lw=0.8)
    ax.set(ylim=(-20, 60), xlabel="blur width chi (um), band centre", ylabel="median size / certified - 1 (%)",
           title="Falling beads (never used to build the table): x direct, o through the table")
    ax.legend(fontsize=7)
    fig.tight_layout()
    figs.append(out / "fig_check.png")
    fig.savefig(figs[-1], dpi=130)
    plt.close(fig)
    # 3. depth and direct bias against the chi limit
    fig, axs = plt.subplots(1, 2, figsize=(10, 4.2))
    for k, v in R["depth"].items():
        cms = [float(c) for c in v["by_chi_max"]]
        c = COLOURS.get(v["certified_um"], "k")
        lab = f"{v['certified_um']:g} um ({v['beads']} beads)"
        axs[0].plot(cms, [x["depth_mm"] for x in v["by_chi_max"].values()], "-", color=c, label=lab)
        axs[1].plot(cms, [x["direct_bias_pct"] if x["direct_bias_pct"] is not None else np.nan
                          for x in v["by_chi_max"].values()], "-", color=c, label=lab)
    axs[0].set(xlabel="chi limit (um)", ylabel="measurement depth (mm)", title="Depth: the same for every size")
    axs[1].axhspan(-100 * TOL, 100 * TOL, color="#3a9b5c", alpha=0.08)
    axs[1].set(xlabel="chi limit (um)", ylabel="median direct size error of the slab (%)",
               title="Direct sizing (no table) of a slab spread evenly in depth")
    for a in axs:
        a.legend(fontsize=7)
    fig.tight_layout()
    figs.append(out / "fig_depth.png")
    fig.savefig(figs[-1], dpi=130)
    plt.close(fig)
    # 4. the AI's classes
    if R["class_share"]:
        fig, ax = plt.subplots(figsize=(7.5, 4.2))
        for s, v in R["class_share"].items():
            per = v["bands"]
            mids = [(b["band"][0] + b["band"][1]) / 2 if b["band"][0] > 0 else 14.0 for b in per]
            ax.plot(mids, [100 * b["droplet_share"] if b["droplet_share"] is not None else np.nan for b in per], "o-",
                    color=COLOURS.get(float(s), "k"), label=f"{s} um")
        ax.axhline(100 * CLASS_OK, color="k", ls=":", lw=0.8)
        ax.set(ylim=(0, 102), xlabel="blur width chi (um), band centre", ylabel="spheres called 'droplet' (%)",
               title="Poured spheres the AI still calls droplet, by blur (isolated ones)")
        ax.legend(fontsize=7)
        fig.tight_layout()
        figs.append(out / "fig_classes.png")
        fig.savefig(figs[-1], dpi=130)
        plt.close(fig)
    return figs


def report(R: dict, figs) -> str:
    e, T = R["edge"], R["table"]
    L = [f"# Sizer 3.0.0 calibration: edge, blur-width rules, depth and look-up table (sizer_calibration "
         f"{R['version']}, {R['made'][:10]})\n",
         "Inputs: " + "; ".join(R["inputs"]) + f". tau {R['tau']} (chi depends on it; every analysis must use the same).",
         ""]
    if R["stage_end_dropped"]:
        L += ["Dropped: " + "; ".join(R["stage_end_dropped"]) + ".", ""]
    L += ["## The rules\n",
          "| | value | |",
          "|---|---|---|",
          f"| edge | {BASES[e['base']][1]}, offset {e['offset_um']} um | sharp static beads within "
          f"+-{e['bases'][e['base']]['max_abs_bias_pct']} % at every size |",
          f"| chi_sharp | {R['chi_sharp_um']:g} um | sized directly up to here: blur adds at most "
          f"{100 * SHARP_TOL:.0f} % to what each bead size reads at focus |",
          f"| chi_max | {R['chi_max_um']} um | sized through the table up to here; set by: {R['chi_max_set_by']} |",
          f"| chi_max_direct | {R['chi_max_direct_um']} um | the single cut if the table is not used (direct sizing "
          f"of a slab within +-{100 * TOL:.0f} %) |",
          f"| d_min | {R['d_min_um']} um | {R['d_min_source']} |",
          f"| chi(z) | chi0 {R['chi0_um']} um, k {R['chi_k_um_per_mm']} um/mm | |"]
    for name, key in (("chi_sharp", "depth_sharp"), ("chi_max", "depth_max"), ("chi_max_direct", "depth_direct")):
        d = R[key]
        if d:
            L.append(f"| depth at {name} | {d['mean_mm']} mm | spread across sizes +-{d['spread_pct']} % |")
    L += ["", "### What limits chi_max\n", "| limit | chi (um) | first failure |", "|---|---|---|"]
    for k, v in R["chi_max_limits"].items():
        L.append(f"| {k} | {v['chi_um']} | {v['why']} |")
    L += ["", "## The edge (sharp static beads, chi <= 16 um)\n",
          "| measure | offset (um) | " + " | ".join(f"{s:g} um" for s in e["sizes_um"]) + " | worst |",
          "|---|---|" + "---|" * len(e["sizes_um"]) + "---|"]
    for b, v in e["bases"].items():
        L.append(f"| {BASES[b][1]} | {v['offset_um']} | " +
                 " | ".join(f"{v['bias_by_size_pct'].get(f'{s:g}')} %" for s in e["sizes_um"]) +
                 f" | {v['max_abs_bias_pct']} % |")
    if e.get("best_level"):
        v = e["levels"][e["best_level"]]
        L.append(f"| one grey level, best l = {e['best_level']} (static only) | - | " +
                 " | ".join(f"{v['bias_by_size_pct'].get(f'{s:g}')} %" for s in e["sizes_um"]) +
                 f" | {v['max_abs_bias_pct']} % |")
    L += ["", f"Chosen: {BASES[e['base']][1]}. Why: {R['base_chosen_because']}.", "",
          "Both measures carried through (the falling beads check both; they did not choose):\n",
          "| measure | sharp beads, worst | table scatter on static beads | chi_sharp | falling check holds to "
          "chi | worst there | scatter there |", "|---|---|---|---|---|---|---|"]
    for b, c in R["candidates"].items():
        L.append(f"| {BASES[b][1]} | {c['at_focus_worst_pct']} % | {c['static_scatter_pct']} % | "
                 f"{c['chi_sharp_um']:g} um | {c['check_limit_um']} um | {c['check_worst_pct']} % | "
                 f"+-{c['check_scatter_pct']} % |")
    fb = e["bases"][e["base"]]
    L += ["", f"Static offsets by size (um): {fb['offset_by_size_um']}. The sharpest falling beads (chi <= 16, single "
          f"frames, moving) read {fb['falling_sharp_offset_by_size_um']}, median {fb['falling_sharp_offset_um']} um: "
          f"{(fb['falling_sharp_offset_um'] or 0) - e['offset_um']:+.1f} um more than the static ones (motion during "
          "the 4 us exposure or single-frame noise; not separated here).", ""]
    L += ["## Blur against depth (static, chi = sqrt(chi0^2 + (k (z - zf))^2))\n",
          "| slide, size | beads | zf (mm) | chi0 (um) | k before / after focus (um/mm) | rms (um) |",
          "|---|---|---|---|---|---|"]
    for k, v in R["chi_of_z"].items():
        L.append(f"| {k} | {v['beads']} | {v.get('zf_mm')} | {v.get('chi0_um')} | {v.get('k_minus_um_per_mm')} / "
                 f"{v.get('k_plus_um_per_mm')} | {v.get('rms_um')} |")
    show = ("15", "16", "18", "20", "22", "25", "30", "35", "40", "50")
    L += ["", "## Depth and direct sizing by chi limit (static, droplets spread evenly through depth)\n",
          "| slide, size | " + " | ".join(f"chi <= {c}" for c in show) + " |", "|---|" + "---|" * len(show)]
    for k, v in R["depth"].items():
        L.append(f"| {k} ({v['beads']} beads) | " + " | ".join(
            f"{v['by_chi_max'][c]['depth_mm']} mm, {v['by_chi_max'][c]['direct_bias_pct']:+} %"
            if v["by_chi_max"].get(c) and v["by_chi_max"][c]["direct_bias_pct"] is not None else "" for c in show) + " |")
    cols = [i for i, c in enumerate(T["chi_um"]) if c in (13, 15, 16, 18, 20, 24, 30, 36, 40, 50, 60)]
    L += ["", "## The look-up table: Delta(s, chi), um (scatter in brackets)\n",
          "| bead (um) | beads | " + " | ".join(f"chi {T['chi_um'][i]:g}" for i in cols) + " |",
          "|---|---|" + "---|" * len(cols)]
    for s, b, d, sg in zip(T["nodes_um"], T["beads"], T["delta_um"], T["sigma_um"]):
        L.append(f"| {s:g} | {b} | " + " | ".join(
            f"{d[i]:.1f} ({sg[i]:.1f})" if _ok(d[i]) else "" for i in cols) + " |")
    L += ["", f"Reach: chi {T['chi_reach_um']} um (where every bead size has data). Thin nodes (< {MIN_BEADS} beads): "
          f"{T['thin_nodes_um'] or 'none'}.", "",
          "## The check: falling beads, never used to build the table\n",
          "Median size / certified - 1, %: direct (no table) / the 3.0.0 rule (direct to chi_sharp, then the table), "
          "with the rule's scatter and the share sized beyond the table's bead sizes.\n",
          "| bead (um) | " + " | ".join(f"chi {b[0]:g}-{b[1]:g}" for b in _bands()) + " |",
          "|---|" + "---|" * len(_bands())]
    for s, per in R["falling_check"].items():
        L.append(f"| {s} | " + " | ".join(
            f"{b['direct_pct']:+} / **{b['rule_pct']:+}** (+-{b['rule_scatter_pct']}; n {b['n']}"
            + (f"; extrap. {100 * b['extrapolated_share']:.0f} %" if b["extrapolated_share"] else "") + ")"
            if b["rule_pct"] is not None else f"n {b['n']}" for b in per) + " |")
    if R["class_share"]:
        L += ["", "## Spheres the AI still calls 'droplet' (isolated, poured)\n",
              "| bead (um) | " + " | ".join(f"chi {b[0]:g}-{b[1]:g}" for b in _bands()) + " |",
              "|---|" + "---|" * len(_bands())]
        for s, v in R["class_share"].items():
            L.append(f"| {s} | " + " | ".join(
                f"{100 * b['droplet_share']:.0f} % (n {b['n']})" if b["droplet_share"] is not None else f"n {b['n']}"
                for b in v["bands"]) + " |")
        L += ["", "Where the 'filament' / 'blob' calls sit, and the droplet calls with no chi:\n",
              "| bead (um) | filament + blob calls | their median chi (um) | beyond chi "
              f"{BANDS[-1]:g} | droplet calls with no chi |", "|---|---|---|---|---|"]
        for s, v in R["class_share"].items():
            far = v["non_droplet_beyond_last_band_share"]
            noc = v["droplet_no_chi_share"]
            L.append(f"| {s} | {v['non_droplet_n']} | {v['non_droplet_chi_median_um']} | "
                     f"{'' if far is None else f'{100 * far:.0f} %'} | {'' if noc is None else f'{100 * noc:.0f} %'} |")
    L += ["", "## Open\n",
          f"- **Beyond the table's bead sizes** ({min(T['nodes_um']):g}-{max(T['nodes_um']):g} um) Delta is held at the "
          "end bead's value. Above, the falling beads show that holds; below the smallest bead nothing checks it "
          "until the reticle's 28 / 19.8 / 14 um dots.",
          "- **Thin table nodes** " + (", ".join(f"{s:g} um" for s in T["thin_nodes_um"]) or "none") +
          f" (< {MIN_BEADS} beads): the big-bead through-focus series replaces them.",
          "- **The edge offset differs by bead batch** (static, um): " +
          ", ".join(f"{k} {v}" for k, v in e["bases"][e["base"]]["offset_by_size_um"].items()) +
          ". Certificate or selection; the reticle's certified dots separate scale and edge.",
          "- **chi is measured on 40-frame averages here but on single frames in spray**; the falling beads (single "
          "frames) agree with the table, and Phase 2's model gives the over-count from outside a tight cut.", ""]
    L += [f"![{f.stem}]({f.name})" for f in figs] + [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("beads", nargs="+", type=Path, help="bead_calibration analysis folders (beads_through_focus.csv, "
                    "beads_at_focus.csv, falling_beads.csv)")
    ap.add_argument("--out", type=Path, required=True, help="a new folder for the results")
    ap.add_argument("--pours", type=Path, default=None, help="the falling-bead pours' folder (run folders with the "
                    "AI's predictions): which share of the spheres the AI calls droplet, by blur (slow)")
    ap.add_argument("--pour-classes", type=Path, default=None, help="a pour_classes.csv written before (instead of "
                    "--pours)")
    ap.add_argument("--frame-step", type=int, default=1, help="with --pours: measure every Nth frame")
    ap.add_argument("--write-profile", action="store_true", help="fill the optics profile's calibration block")
    a = ap.parse_args()
    profile = optics.profile_for(a.beads[0])
    R = analyse(a.beads, a.out, profile, a.pours, a.pour_classes, a.frame_step)
    print(f"edge: {R['edge']['base']} - {R['edge']['offset_um']} um; chi_sharp {R['chi_sharp_um']} um; chi_max "
          f"{R['chi_max_um']} um ({R['chi_max_set_by']}); chi_max_direct {R['chi_max_direct_um']} um; d_min "
          f"{R['d_min_um']} um")
    if a.write_profile:
        path = optics.PROFILE_DIR / f"{profile['name']}.json"
        write_profile(path, profile_block(R, str(a.out).replace("/Volumes/LaCie/", "")))
        print("profile written:", path)
    print("written:", *R["_files"], sep="\n  ")


if __name__ == "__main__":
    main()
