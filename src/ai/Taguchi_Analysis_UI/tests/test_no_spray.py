"""'No spray' runs (2026-10-13): a run whose atomised fraction is below the threshold (default 2%) is a
dribble. Its few droplets are real but say nothing about atomisation (CCD C3: 0.19%, a continuous stream
with stray specks; "99% of C3's droplets below 50 um" topped the deck). Its droplet size and steadiness
are blanked everywhere they are read; its atomised fraction, droplet count and liquid figures stay."""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import design as dz
from src.ai.Taguchi_Analysis_UI import provenance
from src.ai.Taguchi_Analysis_UI import rsm_design as rb
from src.ai.Taguchi_Analysis_UI import rsm_detect as rsm
from src.ai.Taguchi_Analysis_UI import rsm_publish as rp
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI import size_bins, stats, tables
from src.ai.Taguchi_Analysis_UI.tests import fakes
from src.ai.Taguchi_Analysis_UI.tests.test_rsm_design import ben_plan

BLANKED = stats.NO_SPRAY_KEYS
KEPT = ("atom", "per_frame", "cv_liquid", "af_flow", "peak_bar")


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def dribble(run: Path, seed: int = 0) -> None:
    """Rewrite a measured fake run as a dribble: ~0.2% atomised, a few small stray droplets."""
    fakes.write_results(run, np.random.default_rng(seed), 27.0, 0.002, n_frames=12, per_frame=4)


# ---- the rule ---------------------------------------------------------------------------------------------

def test_the_threshold_and_off():
    assert stats.no_spray_reason(0.19) == "atomised 0.19% < 2%"
    assert stats.no_spray_reason(1.99) and stats.no_spray_reason(2.0) is None
    assert stats.no_spray_reason(5.96) is None and stats.no_spray_reason(None) is None
    assert stats.no_spray_reason(float("nan")) is None
    assert stats.no_spray_reason(0.19, stats.AnalysisOptions(no_spray_atom_pct=0)) is None      # 0 = off
    assert stats.no_spray_reason(4.0, stats.AnalysisOptions(no_spray_atom_pct=5)) == "atomised 4.00% < 5%"


def test_one_run_is_blanked_where_it_is_read(tmp):
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    dribble(run)
    info = rd.load_run_info(run, check_reuse=False)
    skipped, warnings = [], []
    rec, values, ci, _ctx, metrics = stats.load_measured_run(run, info, 0.30, np.random.default_rng(0), True,
                                                             tmp / "cache", skipped, warnings)
    assert rec["no_spray"].startswith("atomised 0.") and not skipped
    assert all(values[k] is None for k in BLANKED), {k: values[k] for k in BLANKED}
    assert all(k not in ci for k in BLANKED) and "boot_d32" not in rec and "d32" not in rec
    assert values["atom"] < 2 and values["per_frame"] > 0 and values["cv_liquid"] is not None
    assert metrics["size"] is None and "count_series" not in metrics["steadiness"]
    assert "liquid_series" in metrics["steadiness"]                   # liquid steadiness stays
    assert tables.in_focus_diameters(type("R", (), {"rec": rec})()).size == 0
    assert len(warnings) == 1 and run.name in warnings[0] and "no spray" in warnings[0]
    # the cache keeps the full metrics: the blanking is per analysis, not written back
    again = stats.load_measured_run(run, info, 0.30, np.random.default_rng(0), False, tmp / "cache", [], [],
                                    stats.AnalysisOptions(no_spray_atom_pct=0))
    assert again[1]["d32"] is not None and again[4]["size"] is not None and "no_spray" not in again[0]


# ---- a Taguchi campaign with one dribble ------------------------------------------------------------------

def test_a_campaign_keeps_the_dribble_for_atomisation_and_drops_it_for_size(tmp):
    runs = fakes.make_measured_l9x3(tmp)
    dribble(runs[0])
    design = dz.detect(rd.load_runs(rd.find_runs([tmp / "2026"]).runs, check_reuse=False))
    res = stats.analyse(design, do_bootstrap=False, metrics_cache=tmp / "cache")
    assert res.refused is None and len(res.runs) == 27
    assert res.responses["atom"].n_used == 27 and res.responses["d32"].n_used == 26 and res.responses["d_mean"].n_used == 26 and res.responses["cv_droplets"].n_used == 26
    assert any(runs[0].name in w and "no spray" in w for w in res.warnings)
    bins = size_bins.from_results(res)
    assert runs[0].name not in {s.name for s in bins.runs} and len(bins.runs) == 26
    row = next(r for r in tables.per_run(res) if r["run"] == runs[0].name)
    assert row["note"].startswith("no spray: size not reported")
    assert next(r for r in tables.size_percentiles(res) if r["run"] == runs[0].name)["droplets"] == 0
    cond = next(r.condition for r in res.runs if r.name == runs[0].name)
    pooled = next(r for r in tables.size_percentiles_by_condition(res) if r["condition"] == cond)
    assert pooled["runs"] == 2                                       # its two replicates, not three
    prov = dict(provenance.collect(res, bins, tmp / "out").rows())
    assert prov["No spray below (atomised %)"].startswith("2; 1 run(s) flagged") and runs[0].name in \
        prov["No spray below (atomised %)"]


# ---- the response surface: C3's setting as a dribble on the simulated CCD day -------------------------------

@pytest.fixture(scope="module")
def ccd():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        runs = fakes.make_measured_ccd_day(root / "src", rb.build_sheet(ben_plan()), seed=3)
        c3 = next(r for r in runs if "_11000sccm_100rpm_5000sps_or0.5_" in r.name)
        dribble(c3, seed=1)
        design = rsm.from_runs(rd.load_runs(rd.find_runs([root / "src" / "2026"]).runs, check_reuse=False))
        keys = [f.key for f in design.detect().factors]
        res = rp.publish(design, root / "out", [rp.ModelSpec("full quadratic", keys)],
                         discrete={"orifice": [0.5, 0.8, 1.2, 1.8]}, title="CCD day with a dribble")
        rows = list(csv.DictReader(open(root / "out" / "rsm_results.csv", newline="", encoding="utf-8")))
        yield {"res": res, "c3": c3.name, "rows": rows,
               "report": (root / "out" / "rsm_report.md").read_text(encoding="utf-8")}


def test_the_surface_fits_leave_the_dribble_out_of_size_only(ccd):
    res = ccd["res"]
    assert res.ok, res.problems
    R = next(iter(res.models.values()))
    assert R.fits["d32"].full.n == R.fits["atom"].full.n - 1
    assert R.fits["lag1"].full.n == R.fits["atom"].full.n - 1
    row = next(r for r in ccd["rows"] if r["run"] == ccd["c3"])
    assert row["d32"] == "" and row["mean_d"] == "" and row["count_cv"] == "" and float(row["af"]) < 2
    assert row["note"].startswith("no spray: size and steadiness not reported")
    assert all(r["note"] == "" for r in ccd["rows"] if r["run"] != ccd["c3"])


def test_the_report_says_so_at_the_top(ccd):
    top = ccd["report"].split("## What was found")[0]
    assert f"> ⚠ {ccd['c3']}: no spray (atomised 0." in top
    assert "No spray below (atomised %) | 2; 1 run(s) flagged" in ccd["report"]
