"""size_limit.py (sizer 3.0.0 plan, Phase 2, 2026-10-16): the optics model and the rule that turns it into d_min."""
from __future__ import annotations

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

sl = spec.rdc_module("size_limit")


def test_a_rendered_disc_blocks_the_light_its_area_says():
    rng = np.random.default_rng(0)
    T, cx, cy = sl.render(76.39, 10.0, 0.1, rng, noise=0.0)
    blocked = float((1.0 - T).sum())                                    # px of full darkness
    expected = (1 - 0.1) * np.pi * (76.39 / 10 / 2) ** 2
    assert blocked == pytest.approx(expected, rel=0.02)
    assert T.min() == pytest.approx(0.1, abs=0.05) and abs(cx - T.shape[1] // 2) <= 0.5


def test_a_sharp_large_disc_is_found_and_sized_and_a_tiny_faint_one_is_not():
    rng = np.random.default_rng(1)
    r = sl.measure(76.39, 10.0, 0.11, rng, noise=0.0)
    assert r["found"] and r["halfmax_up4"] == pytest.approx(76.39, rel=0.05)
    assert r["chi"] == pytest.approx(12.5, abs=2.5)                      # chi measured ~ the optical blur
    tiny = [sl.measure(5.0, 13.0, 0.11, rng, noise=0.0)["found"] for _ in range(5)]
    assert not any(tiny)                                                 # never reaches 4 px below T 0.95


def test_blur_makes_the_measured_chi_and_the_half_max_size_grow():
    c = sl.chi_curve(37.36, [10.0, 30.0], 0.11, 0.0, 8, seed=2)
    assert c[1]["chi"] > c[0]["chi"] + 10 and c[1]["halfmax_up4"] > c[0]["halfmax_up4"] * 1.1


def test_chi0_is_recovered_from_a_target_the_model_itself_made():
    target = sl.chi_curve(76.39, [11.0], 0.11, 0.0, 30, seed=3)[0]["chi"]
    assert sl.calibrate_chi0(target, 76.39, 0.11, 0.0, n=30) == pytest.approx(11.0, abs=1.0)


def test_d_min_is_the_smallest_size_from_which_every_larger_one_is_confident():
    def row(d, bias, found):
        return {"d_um": d, "halfmax_up4_bias": bias, "found_and_passed_inside": found}
    t = [row(15, 0.40, 0.95), row(20, 0.12, 0.95), row(25, 0.08, 0.92), row(30, -0.03, 0.97), row(40, 0.02, 0.99),
         row(60, 0.01, 0.99)]
    assert sl.d_min(t, "halfmax_up4") == 25
    t[3]["found_and_passed_inside"] = 0.85                               # a gap above: the limit moves past it
    assert sl.d_min(t, "halfmax_up4") == 40
    assert sl.d_min([row(15, 0.5, 0.9), row(20, 0.4, 0.9)], "halfmax_up4") is None


def test_the_volume_edge_is_where_the_reference_disc_reads_chi_max():
    curve = [{"chi_opt": c, "chi": c + 2.0} for c in (10.0, 20.0, 30.0)]
    assert sl.slab_chi_opt(20.0, curve) == pytest.approx(18.0)
