"""sizer_calibration.py (sizer 3.0.0 plan, Phase 3, 2026-10-16): the edge, the chi rules, the depth and the look-up
table. Synthetic beads with a known growth Delta(s, chi) = (chi - 13)(0.30 - 0.002 s) um and a 5 um edge offset: every
step must give back what was put in."""
from __future__ import annotations

import csv
import json
import math

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

sc = spec.rdc_module("sizer_calibration")

Z = (-8, -7, -6, -5, -4, -3, -2.5, -2, -1.5, -1.25, -1, -0.8, -0.6, -0.4, -0.2, 0, 0.2, 0.4, 0.6, 0.8, 1, 1.25, 1.5,
     2, 2.5, 3, 4, 5, 6, 7)
OFFSET = 5.0


def grow(s, chi):
    return (np.maximum(chi, 13.0) - 13.0) * (0.30 - 0.002 * s)


def chi_at(z, k=9.5):
    return math.sqrt(13.0 ** 2 + (k * z) ** 2)


def through_rows(sizes=(40.0, 60.0, 80.0), beads=12, seed=0, z=Z):
    rng = np.random.default_rng(seed)
    rows = []
    for s in sizes:
        for b in range(beads):
            for zz in z:
                c = chi_at(zz) + rng.normal(0, 0.3)
                rows.append({"certified_um": s, "z_mm": float(zz), "bead": b, "slide": "mix", "run": "r",
                             "group": "d/mix", "chi_um": c,
                             "d_l0.50": s + OFFSET + grow(s, c) + rng.normal(0, 0.5),
                             "d_blaisot_um": s + OFFSET + grow(s, c) + rng.normal(0, 1.5)})
    return rows


def falling_rows(sizes=(40.0, 60.0, 80.0, 120.0), n=400, seed=1, extra=None):
    rng = np.random.default_rng(seed)
    rows = []
    for s in sizes:
        for c in rng.uniform(13.0, 60.0, n):
            d = s + OFFSET + grow(s, c) + rng.normal(0, 0.8) + (extra(s, c) if extra else 0.0)
            rows.append({"certified_um": s, "chi_um": float(c), "d_l0.50": d, "d_blaisot_um": d + rng.normal(0, 1.0),
                         "isolated": True})
    return rows


def halfmax_edge():
    return {"base": "halfmax", "column": "d_l0.50", "offset_um": OFFSET}


def test_chi_against_depth_is_fitted_with_a_slope_each_side():
    z = np.asarray(Z, float)
    chi = np.asarray([math.sqrt(13.0 ** 2 + ((9.0 if v < 0.2 else 10.0) * (v - 0.2)) ** 2) for v in z])
    f = sc.chi_fit(z, chi)
    assert f["zf_mm"] == pytest.approx(0.2, abs=0.02) and f["chi0_um"] == pytest.approx(13.0, abs=0.1)
    assert f["k_minus_um_per_mm"] == pytest.approx(9.0, abs=0.1) and f["k_plus_um_per_mm"] == pytest.approx(10.0, abs=0.1)
    assert sc.chi_fit([0, 1], [13, 20]) == {}


def test_the_depth_is_the_share_passing_integrated_over_depth():
    z = np.round(np.arange(-4, 4.001, 0.1), 2)
    rows = [{"certified_um": 50.0, "z_mm": float(v), "chi_um": chi_at(v, k=10.0), "d_l0.50": 55.0} for v in z]
    d = sc.depth_and_bias(rows, halfmax_edge(), chi_maxes=(20.0, 80.0))
    assert d[20.0]["depth_mm"] == pytest.approx(2 * math.sqrt(20 ** 2 - 13 ** 2) / 10, abs=0.1)
    assert d[20.0]["bias"] == pytest.approx(0.0) and not d[20.0]["open"]
    assert d[80.0]["open"]                                   # the cut reaches the end of the series: depth is a floor


def test_the_table_gives_back_the_size_it_was_built_from_and_flags_what_it_extrapolates():
    T = sc.build_table(through_rows(), halfmax_edge())
    assert T["nodes_um"] == [40.0, 60.0, 80.0] and T["beads"] == [12, 12, 12] and T["chi_reach_um"] == 60.0
    for s in (40.0, 50.0, 70.0, 80.0):
        for c in (14.0, 25.0, 45.0):
            size, sig, where = sc.table_size(s + grow(s, c), c, T)
            assert size[0] == pytest.approx(s, abs=0.6) and 0 < sig[0] < 2
            assert where[0] == "in" or s in (40.0, 80.0)       # at an end bead, a hair either side
    size, _s, where = sc.table_size(30 + grow(30, 40.0), 40.0, T)          # below the smallest bead: Delta held
    assert where[0] == "below" and size[0] == pytest.approx(30 + grow(30, 40.0) - grow(40, 40.0), abs=0.6)
    size, _s, where = sc.table_size(150 + grow(150, 40.0), 40.0, T)
    assert where[0] == "above" and size[0] == pytest.approx(150 + grow(150, 40.0) - grow(80, 40.0), abs=0.6)
    size, _s, where = sc.table_size(60.0, 75.0, T)                           # beyond the table's reach
    assert where[0] == "off" and np.isnan(size[0])


def test_the_table_only_grows_with_blur():
    rows = through_rows(sizes=(40.0,))
    for r in rows:                                          # a dip far out (as Blaisot's size does) is flattened
        if r["chi_um"] > 40:
            r["d_l0.50"] -= 0.1 * (r["chi_um"] - 40)
    d = np.asarray(sc.build_table(rows, halfmax_edge())["delta_um"][0], float)
    assert np.all(np.diff(d[np.isfinite(d)]) >= -1e-9)


def test_the_3_0_0_rule_sizes_directly_then_through_the_table_then_not_at_all():
    T = sc.build_table(through_rows(), halfmax_edge())
    d = np.asarray([60.0 + grow(60, 14.0), 60.0 + grow(60, 30.0), 60.0 + grow(60, 55.0)])
    size, method = sc.size_3(d, [14.0, 30.0, 55.0], T, chi_sharp=15.0, chi_max=50.0)
    assert list(method) == ["direct", "table", "outside"]
    assert size[0] == pytest.approx(d[0]) and size[1] == pytest.approx(60.0, abs=0.6) and np.isnan(size[2])
    _s, method = sc.size_3([200.0], [30.0], T, 15.0, 50.0)
    assert method[0] == "table_extrapolated"


def test_chi_sharp_is_where_blur_has_added_five_percent_at_every_bead_size():
    T = sc.build_table(through_rows(), halfmax_edge())
    # 40 um grows 0.22 um per um of chi: 5 % (2 um) after ~9 um of blur past the first point; 60 and 80 later
    assert sc.chi_sharp_from(T) == pytest.approx(13.0 + 2.0 / 0.22, abs=1.0)


def test_the_falling_check_and_how_far_it_holds():
    T = sc.build_table(through_rows(), halfmax_edge())
    ok = sc.falling_check(falling_rows(), halfmax_edge(), T, chi_sharp=15.0)
    assert set(ok) == {"40", "60", "80", "120"}
    assert all(abs(b["rule_pct"]) < 3 for v in ok.values() for b in v if b["rule_pct"] is not None)
    assert sc.check_limit(ok) == (60.0, "")
    bad = sc.falling_check(falling_rows(n=1000, extra=lambda s, c: 6.0 if s == 40 and c >= 35 else 0.0),
                           halfmax_edge(), T, 15.0)
    lim, why = sc.check_limit(bad)
    assert lim == 35.0 and "40 um" in why
    thin = sc.falling_check(falling_rows(n=60), halfmax_edge(), T, 15.0)     # < 50 beads in a band: no evidence
    assert all(b["rule_pct"] is None for v in thin.values() for b in v)


def test_the_edge_measure_that_reads_sharp_beads_best_and_its_offset():
    rng = np.random.default_rng(2)
    rows = []
    for s in (40.0, 60.0, 80.0, 100.0):
        for _ in range(30):
            rows.append({"certified_um": s, "chi_um": 13.5, "d_l0.50": s + OFFSET + rng.normal(0, 0.3),
                         "d_blaisot_um": 1.08 * s + rng.normal(0, 0.3)})     # Blaisot's reads 8 % large at all sizes
    e = sc.edge(rows, [])
    assert e["base"] == "halfmax" and e["offset_um"] == pytest.approx(OFFSET, abs=0.2)
    assert e["bases"]["halfmax"]["max_abs_bias_pct"] < 1 and e["bases"]["blaisot"]["max_abs_bias_pct"] > 2


def test_a_tie_at_focus_goes_to_the_more_precise_table():
    c = {"halfmax": {"at_focus_worst_pct": 4.3, "static_scatter_pct": 3.5},
         "blaisot": {"at_focus_worst_pct": 4.0, "static_scatter_pct": 2.6}}
    assert sc.choose_base(c)[0] == "blaisot"
    c["blaisot"]["static_scatter_pct"] = 4.0
    assert sc.choose_base(c)[0] == "halfmax"
    c["halfmax"]["at_focus_worst_pct"] = 6.0                 # >= 1 point apart: the sharp beads decide
    assert sc.choose_base(c)[0] == "blaisot"


def test_a_stage_that_stopped_moving_is_dropped():
    rows = through_rows(sizes=(40.0,), beads=3, z=(-2, -1, 0, 1, 7, 8))
    for r in rows:
        if r["z_mm"] == 8:
            r["chi_um"] = next(q["chi_um"] for q in rows if q["z_mm"] == 7 and q["bead"] == r["bead"])
    kept, notes = sc.stage_end_repeats(rows)
    assert {r["z_mm"] for r in kept} == {-2, -1, 0, 1, 7} and len(notes) == 1 and "+8" in notes[0]


def test_the_ai_class_limit():
    rows = [{"certified_um": 40.0, "chi_um": float(c), "isolated": True,
             "cls": "droplet" if c < 40 or i % 4 else "filament"} for i, c in enumerate(np.linspace(13, 59.9, 2000))]
    rows += [{"certified_um": 40.0, "chi_um": 120.0, "isolated": True, "cls": "blob"}] * 10
    share = sc.class_share(rows)
    assert share["40"]["bands"][0]["droplet_share"] == 1.0
    assert sc.class_limit(share)[0] == 40.0
    assert share["40"]["non_droplet_beyond_last_band_share"] > 0


def test_the_whole_calibration_on_synthetic_beads(tmp_path):
    d = tmp_path / "beads"
    d.mkdir()

    def write(name, rows):
        keys = sorted({k for r in rows for k in r})
        with open(d / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    through = through_rows(z=Z + (8,))
    for r in through:                                        # the stage stuck at +7 on the last step
        if r["z_mm"] == 8:
            r["chi_um"] = next(q["chi_um"] for q in through if q["z_mm"] == 7 and q["bead"] == r["bead"]
                               and q["certified_um"] == r["certified_um"])
    write("beads_through_focus.csv", [{k: v for k, v in r.items() if k != "group"} for r in through])
    write("beads_at_focus.csv", [r for r in through if r["z_mm"] == 0])
    write("falling_beads.csv", falling_rows())
    (d / "optics_calibration_v1.json").write_text(json.dumps({"tau": 0.1115}))
    prof = {"name": "t", "calibration": {"d_min_provisional": {"chi_max_15_um": 30.0, "chi_max_20_um": 35.0,
                                                               "chi_max_25_um": 35.0}}}
    R = sc.analyse([d], tmp_path / "out", prof)
    assert R["edge"]["base"] == "halfmax" and R["edge"]["offset_um"] == pytest.approx(OFFSET, abs=0.3)
    assert len(R["stage_end_dropped"]) == 1
    assert R["chi_max_um"] == 60.0 and R["chi_sharp_um"] == pytest.approx(22.0, abs=1.0) and R["d_min_um"] == 35.0
    assert R["depth_max"]["spread_pct"] < 5 and R["chi0_um"] == pytest.approx(13.0, abs=0.5)
    for n in ("report.md", "sizer_calibration.json", "lookup_table.csv", "fig_table.png", "fig_check.png"):
        assert (tmp_path / "out" / n).is_file()
    # the profile: the keys Phase 4 reads, and Phase 2's d_min kept
    p = tmp_path / "t.json"
    p.write_text(json.dumps({**prof, "um_per_px": 10.0, "sources": []}))
    sc.write_profile(p, sc.profile_block(R, "x"))
    cal = json.loads(p.read_text())["calibration"]
    assert set(cal) >= {"edge_level", "edge_offset_um", "chi_sharp_um", "chi_max_um", "d_min_um", "depth_mm",
                        "lookup_table", "tau", "d_min_provisional"}
    T = cal["lookup_table"]
    size, _s, where = sc.table_size(60 + grow(60, 30.0), 30.0, T)
    assert where[0] == "in" and size[0] == pytest.approx(60.0, abs=0.6)
