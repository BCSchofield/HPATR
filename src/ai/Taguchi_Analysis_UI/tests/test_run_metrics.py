"""run_metrics: the shared per-run data layer (Phase 1 of the response-surface plan).

Known answers on hand-built inputs, graceful degradation on the minimal fake runs, the
cache, the extra responses' bootstraps, and the integration into stats.analyse. One
real-data check (skipped without the LaCie) against the 2026-10-07 pulsing analysis."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import covariates, design as dz, pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import run_discovery as rd, run_metrics as rm, stats
from src.ai.Taguchi_Analysis_UI.tests import fakes

REAL = Path("/Volumes/LaCie/Experiments/2026/10/05/124632_9000sccm_900rpm_6000sps_or1.2_bh1")
needs_lacie = pytest.mark.skipif(not REAL.is_dir(), reason="LaCie not mounted")


@pytest.fixture(autouse=True)
def fast_bootstrap(monkeypatch):
    monkeypatch.setattr(spec.rdc_module("taguchi_analysis"), "N_BOOT", 100)


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ---- pure arithmetic -----------------------------------------------------------------------------

def test_volume_percentiles_by_hand():
    # volumes 1, 8, 27, 64 (sum 100); cells 0.5-1.5, 1.5-2.5, 2.5-3.5, 3.5-4.5 with cumulative
    # volume 0, 0.01, 0.09, 0.36, 1.00 at their edges
    d = [1, 2, 3, 4]
    dv10, dv50, dv90 = rm.volume_percentiles(d)
    assert dv10 == pytest.approx(2.5 + (0.10 - 0.09) / (0.36 - 0.09))
    assert dv50 == pytest.approx(3.5 + (0.50 - 0.36) / (1.00 - 0.36))
    assert dv90 == pytest.approx(3.5 + (0.90 - 0.36) / (1.00 - 0.36))
    assert rm.volume_percentiles([]) == [None, None, None]
    assert rm.volume_percentiles([7.0, 7.0]) == [7.0, 7.0, 7.0]


def test_volume_percentiles_move_continuously_on_a_lattice():
    """Many droplets per lattice value (as the real in-focus diameters): the old interpolation
    between sorted droplets returned a lattice value whatever the distribution did; across
    cells, a small shift of volume moves Dv50 a little, not a lattice step or not at all."""
    lattice = np.array([50.0, 51.0, 52.0, 53.0, 54.0])
    base = np.repeat(lattice, [400, 400, 400, 400, 400])
    shifted = np.concatenate([base, np.full(40, 54.0)])          # 2% more droplets at the top
    a, b = rm.volume_percentiles(base)[1], rm.volume_percentiles(shifted)[1]
    assert a not in lattice and b not in lattice
    assert 0 < b - a < 0.5


def test_size_part_matches_the_definitions():
    rng = np.random.default_rng(1)
    dia = {f"f{i}": rng.lognormal(np.log(50), 0.5, 200) for i in range(5)}
    s = rm.size_part(dia, [0, 25, 50, 75, 100, 125, 150, 175, 200, float("inf")])
    d = np.concatenate(list(dia.values()))
    assert s["n"] == d.size
    assert s["d10"] == pytest.approx(d.mean())
    assert s["d32"] == pytest.approx((d ** 3).sum() / (d ** 2).sum())
    v = d ** 3
    assert s["vol_pct_below_small"] == pytest.approx(100 * v[d < 50].sum() / v.sum())
    assert s["vol_pct_above_large"] == pytest.approx(100 * v[d > 125].sum() / v.sum())
    assert sum(s["pct_count"]) == pytest.approx(100) and sum(s["pct_volume"]) == pytest.approx(100)
    assert s["dv10"] < s["dv50"] < s["dv90"]
    assert s["span"] == pytest.approx((s["dv90"] - s["dv10"]) / s["dv50"])


def test_steadiness_thin_frames_lags_and_slow_pulsing():
    frames = [f"frame_{i:04d}_n{i * 10 - 1}" for i in range(512)]
    t = np.arange(512) / 39.0
    slow = 100 + 60 * np.sin(2 * np.pi * 0.35 * t)          # a strong 0.35 Hz pulse
    counts = dict(zip(frames, np.round(slow).astype(int)))
    st = rm.steadiness_part(frames, counts, {f: 1000.0 for f in frames}, 39.0)
    c = np.round(slow)
    assert st["thin_pct"] == pytest.approx(100 * (c < 0.5 * c.mean()).mean())
    assert st["lag1"] > 0.9                                   # slow -> neighbours alike
    assert st["slow_share_pct"] > 80 and st["slow_share_noise_pct"] == pytest.approx(9.794, abs=0.01)
    assert abs(st["slow_peak_hz"] - 0.35) < 0.16
    white = rm.steadiness_part(frames, dict(zip(frames, np.random.default_rng(0).poisson(100, 512))),
                               {}, 39.0)
    assert abs(white["lag1"]) < 0.15 and white["slow_share_pct"] < 25


def test_capture_time_from_the_folder_path():
    assert rm.capture_time(Path("/x/2026/10/05/124632_9000sccm_900rpm")) == "2026-10-05T12:46:32"
    assert rm.capture_time(Path("/x/Trial_3")) is None


# ---- whole runs on the fakes ---------------------------------------------------------------------

def _measured(tmp, name="090432_3000sccm_300rpm_4000sps_or1.2_bh1"):
    run = fakes.make_run(tmp, name, notes="Taguchi 1")
    fakes.write_results(run, np.random.default_rng(0), 50.0, 0.1, n_frames=40)
    return run


def test_a_minimal_run_degrades_part_by_part(tmp):
    run = _measured(tmp)
    rec = stats.load_run_responses(run, 0.30)
    ctx = covariates.run_context(rd.load_run_info(run, thr=0.30))
    m = rm.compute(run, 0.30, rec=rec, context=ctx)
    assert m["size"]["n"] > 0 and m["steadiness"]["frames"] == 40
    # the fake has no components, background, predictions or camera window: each is reported,
    # none stops the rest
    assert "pieces" in m["missing"] and "quality.background" in m["missing"]
    assert m["pressure"]["note"].startswith("no camera window")
    assert m["throughput"]["af_flow_ml_min"] == pytest.approx(ctx.liquid_ml_min * rec["atom"] / 100)
    assert m["peak_bar"] == pytest.approx(2.38)              # the fake workbook's pressure range
    json.dumps(m)                                             # plain JSON all the way down


def test_cache_hits_then_recomputes_when_an_input_changes(tmp):
    run = _measured(tmp)
    rec = stats.load_run_responses(run, 0.30)
    cache = tmp / "cache"
    a = rm.load_or_compute(run, 0.30, cache_dir=cache, rec=rec)
    cfile = cache / f"{run.name}.json"
    assert cfile.is_file()
    stamp = cfile.stat().st_mtime_ns
    b = rm.load_or_compute(run, 0.30, cache_dir=cache, rec=rec)
    assert cfile.stat().st_mtime_ns == stamp and b == a        # served from the cache
    sizes = run / "shadowgraph" / "analysis" / "droplets_0.30" / "droplet_sizes.csv"
    time.sleep(0.01)
    sizes.write_text(sizes.read_text() + "frame_0000_n-1,500.0,1\n")
    os.utime(sizes)
    c = rm.load_or_compute(run, 0.30, cache_dir=cache, rec=stats.load_run_responses(run, 0.30)
                           if False else rec)
    assert c["_signature"] != a["_signature"]                  # input changed -> recomputed


def test_response_values_bootstraps_are_centred_and_sized(tmp):
    run = _measured(tmp)
    ta = spec.rdc_module("taguchi_analysis")
    rec = stats.load_run_responses(run, 0.30, np.random.default_rng(0))
    m = rm.compute(run, 0.30, rec=rec, context=covariates.run_context(rd.load_run_info(run, thr=0.30)))
    v = rm.response_values(m, rec, n_boot=ta.N_BOOT, seed=0)
    for k in ("dv50", "thin_pct", "af_flow"):
        b = np.asarray(v[f"boot_{k}"])
        assert b.size == ta.N_BOOT
        lo, hi = np.nanpercentile(b, [2.5, 97.5])
        assert lo <= v[k] <= hi
    assert "boot_lag1" not in v and "boot_peak_bar" not in v  # no honest frame bootstrap for these
    assert rm.response_values(m, rec)["dv50"] == v["dv50"]     # no bootstrap asked: values only


def test_analyse_carries_the_extra_responses(tmp):
    runs = fakes.make_measured_l9x3(tmp, seed=3, n_frames=8)
    design = dz.detect(rd.load_runs(runs, thr=0.30))
    res = stats.analyse(design, 0.30, metrics_cache=tmp / "cache")
    keys = [k for k, *_ in stats.responses_table()]
    assert keys[-5:] == ["dv50", "af_flow", "thin_pct", "lag1", "peak_bar"]
    for k in ("dv50", "af_flow"):
        assert res.responses[k].anova is not None, k
    # the fakes put exactly 50 droplets in every frame and one pressure range in every workbook,
    # so these three carry no variation here: present, and honestly reported as degenerate
    for k in ("thin_pct", "lag1", "peak_bar"):
        assert k in res.responses and (res.responses[k].anova or res.responses[k].degenerate), k
    r0 = res.runs[0]
    assert r0.metrics["size"]["dv50"] == pytest.approx(r0.values["dv50"])
    assert "dv50" in r0.ci95 and "lag1" not in r0.ci95
    assert len(list((tmp / "cache").glob("*.json"))) == 27


# ---- real data ------------------------------------------------------------------------------------

@needs_lacie
def test_real_run_matches_the_pulsing_analysis():
    """Same run, same numbers as Taguchi/9x3 Taguchi Repeats/pulsing (2026-10-07)."""
    m = rm.compute(REAL, 0.30, detections=False)
    st, p = m["steadiness"], m["pressure"]
    assert st["lag1"] == pytest.approx(0.41717, abs=1e-4)
    assert st["slow_share_pct"] == pytest.approx(18.733, abs=0.01)
    assert st["liquid_cv"] == pytest.approx(1.39151, abs=1e-4)
    assert p["r_pressure_droplets"] == pytest.approx(0.72678, abs=1e-4)
    assert p["gas_flow_cv_pct"] == pytest.approx(0.95240, abs=1e-4)
