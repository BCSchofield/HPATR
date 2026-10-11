"""Phase 2 of the response-surface plan: the richer outputs (stats helpers, tables, extra figures).

A synthetic measured 9 x 3 campaign (fakes.make_measured_l9x3, gas flow strong, RPM none) given
the inputs the real runs have and the minimal fakes lack: a frame rate, enough frames for a
spectrum, un-atomised pieces, and extreme-frame images for two runs. Known answers are planted
where a number is checked (a drift orthogonal to every factor, a data-quality outlier), and
the CIs are checked against scipy, independently of the code under test."""
from __future__ import annotations

import csv
import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import design as dz
from src.ai.Taguchi_Analysis_UI import figures_extra as fx
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI import run_metrics, stats, tables
from src.ai.Taguchi_Analysis_UI.tests import fakes

GALLERY_RUNS = 2


@pytest.fixture(scope="module", autouse=True)
def small_bootstrap():
    ta = spec.rdc_module("taguchi_analysis")
    old = ta.N_BOOT
    ta.N_BOOT = 40
    yield
    ta.N_BOOT = old


def _enrich(run: Path, i: int, rng) -> None:
    """What a real measured run has beyond the minimal fake."""
    raw = run / "shadowgraph" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "extraction_metadata.json").write_text(json.dumps({"frame_rate_fps": 390, "stride": 10}))
    sizes = run / "shadowgraph" / "analysis" / "droplets_0.30" / "droplet_sizes.csv"
    frames = sorted({row["frame"] for row in csv.DictReader(open(sizes, encoding="utf-8"))})
    with open(sizes, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for k, fr in enumerate(frames):
            for _ in range(int(20 + 15 * math.sin(k / 3) + rng.integers(0, 10))):
                w.writerow([fr, 30.0, "0"])
    summ = run / "shadowgraph" / "analysis" / "droplets_0.30" / "summary.json"
    s = json.loads(summ.read_text())
    s.update({"droplets_in_focus": 600 + 7 * i, "droplets_out_of_focus": 400 + 5 * (i % 4)})
    summ.write_text(json.dumps(s))
    cl = run / "shadowgraph" / "analysis" / "liquid_0.30"
    with open(cl / "classical_components.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "area_px"])
        for a in rng.lognormal(np.log(300), 1.0, 200):
            w.writerow(["frame_0001_n9", round(float(a))])
    if i < GALLERY_RUNS:
        from PIL import Image
        (cl / "extreme_images").mkdir(exist_ok=True)
        for name in ("frame_0001_n9", "frame_0002_n19"):
            Image.new("RGB", (64, 36), (200, 200, 200)).save(cl / "extreme_images" / f"{name}.png")
        s = json.loads((cl / "classical_summary.json").read_text())
        s["atomised_extreme_frames"] = {"lowest": {"frame": "frame_0001_n9", "atomised_pct": 1.5},
                                        "highest": {"frame": "frame_0002_n19", "atomised_pct": 99.0}}
        (cl / "classical_summary.json").write_text(json.dumps(s))


@pytest.fixture(scope="module")
def world():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        rng = np.random.default_rng(3)
        runs = fakes.make_measured_l9x3(root / "src", n_frames=48)
        for i, run in enumerate(runs):
            _enrich(run, i, rng)
        design = dz.detect(rd.load_runs(rd.find_runs([root / "src" / "2026"]).runs, check_reuse=False))
        results = stats.analyse(design, metrics_cache=root / "out" / "cache")
        assert not results.refused, results.refused
        yield {"root": root, "results": results, "out": root / "out", "runs": runs}


# ---- stats helpers ---------------------------------------------------------------------------------

@pytest.mark.parametrize("df", [1, 2, 5, 18, 120])
def test_t_quantile_matches_scipy(df):
    from scipy.stats import t
    assert stats.t_quantile(0.05, df) == pytest.approx(t.ppf(0.975, df), rel=1e-7)


def test_main_effects_fit_is_least_squares(world):
    """fitted + residual = value, and least squares on factor columns leaves residuals that sum
    to zero within every level of every factor."""
    res = world["results"]
    fit = stats.main_effects_fit(res, "d32")
    assert np.allclose(fit.fitted + fit.resid, fit.y)
    for f in res.factors:
        for level in {r.levels[f.key] for r in fit.runs}:
            sel = [e for r, e in zip(fit.runs, fit.resid) if r.levels[f.key] == level]
            assert abs(sum(sel)) < 1e-9
    assert fit.df_resid == len(fit.y) - 7                     # 1 + 3 x (3 - 1) parameters
    assert np.isfinite(fit.std_resid).all()


def test_a_planted_drift_is_recovered_and_no_drift_is_not_invented(world, monkeypatch):
    """Time = replicate number (0, 1, 2 h), which is balanced over every factor level, so a drift
    of 0.5 per hour lands entirely in the residuals: the slope must come back as 0.5."""
    res = world["results"]
    hours = {r.name: float((r.replicate or 1) - 1) for r in res.runs}
    monkeypatch.setattr(stats, "run_hours", lambda results: hours)
    base = {r.condition: 50 + 3 * i for i, r in enumerate(res.runs)}
    saved = {r.name: dict(r.values) for r in res.runs}
    try:
        for r in res.runs:
            r.values["d32"] = base[r.condition] + 0.5 * hours[r.name]
        d = stats.drift(res, "d32")
        assert d.slope_per_h == pytest.approx(0.5, abs=1e-9) and d.p < 1e-6
        for r in res.runs:
            r.values["d32"] = base[r.condition]
        d = stats.drift(res, "d32")
        assert abs(d.slope_per_h) < 1e-9
    finally:
        for r in res.runs:
            r.values.clear()
            r.values.update(saved[r.name])


def test_rpm_is_confounded_with_time_in_the_real_run_order(world):
    """The fakes keep the real 10/05 capture order, where RPM climbed through the day."""
    conf = dict(stats.order_confounding(world["results"]))
    assert conf["Bubbler RPM"] > 0.85
    assert abs(conf["Silicone (steps/s)"]) < 0.5


# ---- tables ---------------------------------------------------------------------------------------------

def test_condition_summary_is_the_replicates_mean_and_t_interval(world):
    from scipy.stats import t
    res = world["results"]
    rows = {(r["condition"], r["response"]): r for r in tables.condition_summary(res)}
    label = res.responses["d32"].label
    for c in {r.condition for r in res.runs}:
        v = np.array([r.values["d32"] for r in res.runs if r.condition == c])
        row = rows[(c, label)]
        half = t.ppf(0.975, v.size - 1) * v.std(ddof=1) / math.sqrt(v.size)
        assert row["mean"] == pytest.approx(v.mean(), abs=1e-6)
        assert row["repeat SD"] == pytest.approx(v.std(ddof=1), abs=1e-6)
        assert row["CI high"] - row["mean"] == pytest.approx(half, abs=1e-5)


def test_size_percentiles_pool_replicates_and_match_the_per_run_metrics(world):
    res = world["results"]
    per_run = {r["run"]: r for r in tables.size_percentiles(res)}
    for r in res.runs:
        assert per_run[r.name]["Dv50 (um)"] == pytest.approx(r.metrics["size"]["dv50"], abs=1e-3)
    by_c = {r["condition"]: r for r in tables.size_percentiles_by_condition(res)}
    c = res.runs[0].condition
    pooled = np.concatenate([tables.in_focus_diameters(r) for r in res.runs if r.condition == c])
    assert by_c[c]["droplets"] == pooled.size
    assert by_c[c]["Dv50 (um)"] == pytest.approx(run_metrics.volume_percentiles(pooled)[1], abs=1e-3)


def test_a_data_quality_outlier_is_flagged_and_only_it(world):
    res = world["results"]
    saved = [dict(r.metrics.get("quality") or {}) for r in res.runs]
    try:
        for i, r in enumerate(res.runs):
            r.metrics["quality"] = {"detections_per_frame": 100 + (i % 5), "bg_median": 800.0 + (i % 3)}
        res.runs[4].metrics["quality"]["detections_per_frame"] = 400.0
        flags = tables.quality_flags(res)
        flagged = {n: f for n, f in flags.items() if f}
        assert list(flagged) == [res.runs[4].name]
        f = flagged[res.runs[4].name][0]
        assert f["column"] == "detections per frame" and f["value"] == 400.0 and f["typical"] == pytest.approx(102)
        row = next(r for r in tables.data_quality(res) if r["run"] == res.runs[4].name)
        assert "detections per frame: 400 (typical run 102" in row["flags"]
    finally:
        for r, q in zip(res.runs, saved):
            r.metrics["quality"] = q


def test_every_new_table_is_in_all_tables(world):
    data = tables.all_tables(world["results"], None)
    for key in ("condition_summary", "size_percentiles", "size_percentiles_by_condition", "steadiness",
                "drift", "residuals", "response_correlations", "liquid_pieces", "data_quality"):
        assert data[key], key


# ---- figures --------------------------------------------------------------------------------------------

def test_every_extra_figure_is_drawn_once_as_png_and_svg(world):
    out = world["out"] / "figs"
    problems: list[str] = []
    files = fx.make_all(world["results"], out, problems)
    assert problems == []
    names = {p.name for p in files}
    for fn in fx.FIGURES:
        if fn is fx.galleries:
            continue
        stem = fn.__name__
        assert {f"{stem}.png", f"{stem}.svg"} <= names, stem
        assert (out / f"{stem}.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    gal = sorted(p for p in files if p.parent.name == fx.GALLERY_DIR)
    # the two runs with images are the first two in capture order; they share no condition
    with_images = {r.condition for r in world["results"].runs
                   if r.path in world["runs"][:GALLERY_RUNS]}
    assert [p.stem for p in gal] == sorted(f"gallery_{c}" for c in with_images)


def test_a_figure_with_nothing_to_draw_writes_nothing(world, tmp_path):
    res = world["results"]
    saved = [r.metrics.get("steadiness") for r in res.runs]
    try:
        for r in res.runs:
            r.metrics["steadiness"] = None
        assert fx.fig_spectra(res, tmp_path) == [] and fx.fig_series(res, tmp_path) == []
        assert fx.fig_steadiness(res, tmp_path) == []
        assert not list(tmp_path.iterdir())
    finally:
        for r, s in zip(res.runs, saved):
            r.metrics["steadiness"] = s


def test_one_failing_figure_is_reported_and_the_rest_still_land(world, tmp_path, monkeypatch):
    def boom(results, out_dir):
        raise RuntimeError("no ink")
    monkeypatch.setattr(fx, "FIGURES", (fx.fig_drift, boom, fx.fig_replicates))
    problems: list[str] = []
    files = fx.make_all(world["results"], tmp_path, problems)
    assert problems == ["boom failed: RuntimeError: no ink"]
    assert {"fig_drift.png", "fig_replicates.png"} <= {p.name for p in files}


def test_the_l9_is_fractional_so_interaction_plots_carry_the_caveat(world):
    assert not fx.is_full_factorial(world["results"])
