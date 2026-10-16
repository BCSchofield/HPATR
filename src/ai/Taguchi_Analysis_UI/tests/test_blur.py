"""blur.py (sizer 3.0.0 plan, Phase 4, 2026-10-16): the shared measurement. It must be numpy + OpenCV only (the lab PC
has no scipy) and give exactly what the beads were measured with, which used scipy."""
from __future__ import annotations

import json
import math

import cv2
import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

blur = spec.rdc_module("blur")
mr = spec.rdc_module("measure_run")
UP = 8


def disc(d_um, chi_um, tau=0.11, size=120, centre=(60.3, 59.6), noise=0.0, seed=0):
    """Blaisot's disc: opacity 1 - tau, Gaussian PSF exp(-2 r^2/chi^2), 10 um pixels by area."""
    yy, xx = np.mgrid[0:size * UP, 0:size * UP]
    xs, ys = (xx + 0.5) / UP - 0.5, (yy + 0.5) / UP - 0.5
    t = np.where((xs - centre[0]) ** 2 + (ys - centre[1]) ** 2 <= (d_um / 20) ** 2, tau, 1.0).astype(np.float32)
    t = cv2.GaussianBlur(t, (0, 0), chi_um / 2 / 10 * UP)
    T = cv2.resize(t, (size, size), interpolation=cv2.INTER_AREA)
    if noise:
        T = T + np.random.default_rng(seed).normal(0, noise, T.shape).astype(np.float32)
    return T


def test_it_runs_without_scipy():
    """As on the lab PC: scipy blocked, blur measures a disc and sizes it through a table."""
    import subprocess
    import sys
    code = ("import sys; sys.modules['scipy'] = None; sys.path.insert(0, sys.argv[1]); import numpy as np, blur;"
            "T = np.ones((60, 60), np.float32); T[25:35, 25:35] = 0.2;"
            "r = blur.measure(T, 30, 30, 10, 0.11, lambda t, m: float(t[m].min()), 10.0);"
            "assert r['chi_um'] > 0, r;"
            "t = {'chi_um': [13.0, 60.0], 'nodes_um': [40.0, 80.0], 'delta_um': [[0, 8], [0, 4]],"
            " 'sigma_um': [[1, 1], [1, 1]], 'chi_reach_um': 60.0};"
            "s, m = blur.size_3([50.0], [30.0], t, 15.0, 50.0); assert m[0] == 'table', m")
    rdc = str(spec.paths.RDC_DIR)
    p = subprocess.run([sys.executable, "-c", code, rdc], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_the_bessel_function_matches_scipy():
    special = pytest.importorskip("scipy.special")
    x = np.linspace(0, 300, 30001)
    assert np.max(np.abs(blur.i0e(x) - special.i0e(x)) / special.i0e(x)) < 1e-13


def test_the_stored_model_is_the_model():
    m = blur.compute_model()
    stored = json.loads(blur.MODEL_FILE.read_text(encoding="utf-8"))
    assert np.allclose(m["C0"], stored["C0"], atol=1e-14)
    for l, v in m["r"].items():
        assert np.allclose(v, stored["r"][l], atol=1e-12)


def test_holes_are_filled_as_scipy_fills_them():
    ndimage = pytest.importorskip("scipy.ndimage")
    rng = np.random.default_rng(3)
    for _ in range(200):
        m = rng.random((rng.integers(5, 40), rng.integers(5, 40))) < rng.uniform(0.3, 0.8)
        assert np.array_equal(blur.fill_holes(m), ndimage.binary_fill_holes(m))


@pytest.mark.parametrize("d_um,chi_um", [(37.36, 13.0), (76.39, 13.0), (76.39, 30.0), (155.8, 20.0)])
def test_a_disc_gives_back_its_blur_and_its_size(d_um, chi_um):
    r = blur.measure(disc(d_um, chi_um), 60.3, 59.6, d_um / 10, 0.11, mr.droplet_core, 10.0)
    assert r["chi_um"] == pytest.approx(chi_um, rel=0.15)
    assert r["d_blaisot_um"] == pytest.approx(d_um, rel=0.08)
    assert abs(r["cx"] - 60.3) < 0.6 and abs(r["cy"] - 59.6) < 0.6


def test_smoothing_a_crop_is_smoothing_the_frame():
    T = disc(56.28, 18.0, size=200, centre=(100.2, 97.7), noise=0.02)
    loc = blur.locate(T, 100.2, 97.7, 5.6)
    full = cv2.GaussianBlur(T, (0, 0), blur.SMOOTH_SIGMA)
    h = loc["half"]
    assert np.array_equal(loc["Tsc"], full[loc["y0"]:loc["y0"] + 2 * h + 1, loc["x0"]:loc["x0"] + 2 * h + 1])


def test_too_near_the_edge_is_not_measured():
    T = disc(76.39, 13.0, size=120, centre=(12.0, 60.0))
    assert blur.measure(T, 12.0, 60.0, 7.6, 0.11, mr.droplet_core, 10.0) is None
    flat = np.ones((80, 80), np.float32)
    r = blur.measure(flat, 40, 40, 4.0, 0.11, mr.droplet_core, 10.0)
    assert r is not None and math.isnan(r["chi_um"])                     # nothing there: no edge to measure


def test_the_settings_come_from_the_profile_or_not_at_all():
    with pytest.raises(blur.CalibrationMissing, match="sizer_calibration"):
        blur.sizer3({"name": "x", "calibration": {"chi_max_um": None}})
    cal = {"tau": 0.11, "edge_base": "blaisot", "edge_offset_um": 5.6, "chi_sharp_um": 15.0, "chi_max_um": 50.0,
           "d_min_um": 30.0, "lookup_table": {"chi_um": [13.0, 60.0], "nodes_um": [40.0], "delta_um": [[0.0, 5.0]],
                                             "sigma_um": [[1.0, 1.0]], "chi_reach_um": 60.0}}
    s = blur.sizer3({"name": "p", "calibration": cal})
    assert s["column"] == "d_blaisot_um" and s["chi_max_um"] == 50.0 and len(s["hash"]) == 12
    assert blur.sizer3({"name": "p", "calibration": dict(cal, chi_max_um=40.0)})["hash"] != s["hash"]


def test_the_sizer_version():
    assert blur.resolve_sizer(None, True) == "2.2.0" and blur.resolve_sizer(None, False) == "2.1.0"
    assert blur.resolve_sizer("3.0.0", False) == "3.0.0"
    with pytest.raises(ValueError):
        blur.resolve_sizer("2.3.0")


def _shape(fn, chi, size=(160, 240), tau=0.11):
    yy, xx = np.mgrid[0:size[0] * UP, 0:size[1] * UP]
    xs, ys = (xx + 0.5) / UP - 0.5, (yy + 0.5) / UP - 0.5
    t = cv2.GaussianBlur(np.where(fn(xs, ys), tau, 1.0).astype(np.float32), (0, 0), chi / 2 / 10 * UP)
    T = cv2.resize(t, (size[1], size[0]), interpolation=cv2.INTER_AREA)
    m = T < 0.95
    ys_, xs_ = np.nonzero(m)
    return T, m[ys_.min():ys_.max() + 1, xs_.min():xs_.max() + 1], xs_.min(), ys_.min()


@pytest.mark.parametrize("d_um,chi_um", [(37.36, 25.0), (60.0, 40.0), (155.8, 25.0)])
def test_any_shape_blur_agrees_with_the_droplet_measurement_on_a_disc(d_um, chi_um):
    T, m, x0, y0 = _shape(lambda x, y: (x - 120) ** 2 + (y - 80) ** 2 <= (d_um / 20) ** 2, chi_um)
    disc_chi = blur.measure(T, 120, 80, d_um / 10, 0.11, mr.droplet_core, 10.0)["chi_um"]
    any_chi = blur.object_chi(T, m, x0, y0, 0.11, mr.droplet_core, 10.0)["chi_um"]
    assert any_chi == pytest.approx(disc_chi, rel=0.10)


@pytest.mark.parametrize("chi_um", [25.0, 40.0, 60.0])
def test_any_shape_blur_of_a_ligament_and_a_blob(chi_um):
    bar = lambda x, y: (np.abs((y - 80) * np.cos(0.4) - (x - 120) * np.sin(0.4)) <= 5) & (np.abs(x - 120) < 90)
    blob = lambda x, y: ((x - 120) / 20) ** 2 + ((y - 80) / 7.5) ** 2 <= 1
    for fn in (bar, blob):
        T, m, x0, y0 = _shape(fn, chi_um)
        assert blur.object_chi(T, m, x0, y0, 0.11, mr.droplet_core, 10.0)["chi_um"] == pytest.approx(chi_um, rel=0.10)
    # a second object right beside it is blanked out: the ligament's own blur, as if alone
    T, m, x0, y0 = _shape(bar, chi_um)
    alone = blur.object_chi(T, m, x0, y0, 0.11, mr.droplet_core, 10.0)["chi_um"]
    T2, m2, _x, _y = _shape(lambda x, y: bar(x, y) | ((x - 150) ** 2 + (y - 40) ** 2 <= 36), chi_um)
    others = T2 < 0.95
    near = blur.object_chi(T2, m, x0, y0, 0.11, mr.droplet_core, 10.0, others=others)["chi_um"]
    assert near == pytest.approx(alone, rel=0.05)
