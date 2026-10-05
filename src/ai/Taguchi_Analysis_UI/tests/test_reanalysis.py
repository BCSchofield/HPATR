"""Running the batch over folders that were ALREADY analysed (re-analysis with a new
pipeline version, a different image setting, or a newer model).

The pipeline does not clear old results before re-measuring, so the leftovers of the
previous analysis are still in the folder. The batch must neither halt on them (a false
"contract violation") nor accept them as if the new run had written them.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import jobstate, procs
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI.tests import fakes
from src.ai.Taguchi_Analysis_UI.tests.workerkit import run_state, stub_args, wait_exit

OK = spec.PreflightReport()
HOUR = 3600


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def age(run: Path, seconds: float = HOUR) -> None:
    """Make everything in the run look like it was written `seconds` ago: the usual gap
    between one analysis and the next."""
    t = time.time() - seconds
    for p in run.rglob("*"):
        os.utime(p, (t, t))


def batch(tmp, monkeypatch, runs, images="extremes", settings=None, *extra):
    monkeypatch.setenv("TAGUCHI_UI_SANDBOX_ROOT", str(tmp))
    monkeypatch.setenv("TAGUCHI_UI_CALIBRATION", str(tmp / "calib.json"))
    opts = dict(spec.default_options(), images=images)
    jd, p = jobstate.start_job(tmp / "out", runs, settings or spec.RunSettings(reuse=True), opts,
                               preflight=OK, extra_args=stub_args("--stub-frames", "30", *extra))
    return jd, wait_exit(p)


def png_count(run, sub="droplets_0.30"):
    return len(list((run / "shadowgraph" / "analysis" / sub).glob("frame_*.png")))


# ---- the hazard that was found --------------------------------------------------------------

def test_reanalysing_with_fewer_images_is_not_a_false_contract_violation(tmp, monkeypatch):
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    jd, code = batch(tmp, monkeypatch, [run], images="all")
    assert code == 0 and png_count(run) == 30
    age(run)                                         # the previous analysis is an hour old
    jd, code = batch(tmp, monkeypatch, [run], images="extremes")
    assert code == 0, "the leftovers of the previous analysis halted the batch"
    assert run_state(jd, 0)["status"] == "done"
    assert png_count(run) == 30                      # nothing was deleted
    # ... and the contract was judged on what THIS run wrote
    assert spec.verify_run_outputs(run, spec.RunSettings(), spec.default_options(),
                                   since=time.time() - 60) == []


def test_reanalysing_with_more_images_also_works(tmp, monkeypatch):
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    batch(tmp, monkeypatch, [run], images="extremes")
    age(run)
    jd, code = batch(tmp, monkeypatch, [run], images="all")
    assert code == 0 and png_count(run) == 30


def test_a_file_left_over_from_before_does_not_count_as_this_runs_output(tmp, monkeypatch):
    """The reverse risk: with `since`, a stale summary.json must not let a run that failed to
    write one pass."""
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    batch(tmp, monkeypatch, [run])
    age(run)
    jd, code = batch(tmp, monkeypatch, [run], None, None, "--stub-omit",
                     f"meas_summary@{run.name}") if False else (None, None)
    monkeypatch.setenv("TAGUCHI_UI_SANDBOX_ROOT", str(tmp))
    opts = spec.default_options()
    jd, p = jobstate.start_job(tmp / "out", [run], spec.RunSettings(reuse=True), opts, preflight=OK,
                               extra_args=stub_args("--stub-frames", "30", "--stub-omit",
                                                    f"meas_summary@{run.name}"))
    assert wait_exit(p) == 2
    st = jobstate.load_state(jd)
    assert st["runs"][0]["status"] == "contract_violation"
    assert "was not rewritten by this run" in st["runs"][0]["error"]


def test_verify_ignores_old_files_in_a_glob_but_says_so(tmp, monkeypatch):
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    batch(tmp, monkeypatch, [run], images="all")      # 30 PNGs
    age(run)
    problems = spec.verify_run_outputs(run, spec.RunSettings(), spec.default_options(),
                                       since=time.time() - 60)
    glob = next(p for p in problems if "frame_*.png" in p.where and "droplets" in p.where)
    assert "found 0 files, expected 1-6" in glob.message
    assert "30 older file(s) from a previous analysis ignored" in glob.message


def test_reused_stages_are_not_expected_to_be_fresh(tmp, monkeypatch):
    """Frames and predictions are legitimately OLD when extraction/inference are reused."""
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    batch(tmp, monkeypatch, [run])
    age(run)
    jd, code = batch(tmp, monkeypatch, [run])
    assert code == 0
    st = jobstate.load_state(jd)["runs"][0]
    assert st["reused"] is True                       # extraction + inference skipped
    log = (jd / "logs" / f"00_{run.name}.log").read_text()
    assert "reusing the existing stride-10 analysis" in log


def test_without_since_nothing_changes(tmp, monkeypatch):
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    batch(tmp, monkeypatch, [run])
    age(run)
    assert spec.verify_run_outputs(run, spec.RunSettings(), spec.default_options()) == []


# ---- re-analysing runs that came from the OLD pipeline ----------------------------------------

def test_a_run_measured_under_the_legacy_folder_names_is_remeasured_alongside(tmp, monkeypatch):
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0], analysis="legacy", sizer_version=None)
    before = rd.load_run_info(run).analysis
    assert before.measured and before.legacy_names and before.label == "measured pre-2.0.0 · legacy folders"
    age(run)
    jd, code = batch(tmp, monkeypatch, [run])
    assert code == 0
    an = run / "shadowgraph" / "analysis"
    assert (an / "droplets_0.30").is_dir() and (an / "measurement_0.30").is_dir()   # old kept
    after = rd.load_run_info(run).analysis
    assert after.measured and not after.legacy_names and after.sizer_version == "2.1.0"
    assert after.label == "measured v2.1.0"          # readers now prefer the new folders


def test_the_left_pane_would_flag_a_mix_of_old_and_new_results(tmp, monkeypatch):
    old = fakes.make_run(tmp, fakes.REAL_10_05[0][0], analysis="legacy", sizer_version=None)
    new = fakes.make_run(tmp, fakes.REAL_10_05[1][0], analysis="current", sizer_version="2.1.0")
    runs = [rd.load_run_info(old), rd.load_run_info(new)]
    assert rd.sizer_versions(runs) == {"pre-2.0.0", "2.1.0"}
    batch(tmp, monkeypatch, [old])                    # re-analyse only the old one
    runs = [rd.load_run_info(old), rd.load_run_info(new)]
    assert rd.sizer_versions(runs) == {"2.1.0"}       # the mix is resolved


def test_a_stale_extraction_is_not_reused_when_the_stride_differs(tmp, monkeypatch):
    run = fakes.make_run(tmp, fakes.REAL_10_05[0][0])
    batch(tmp, monkeypatch, [run])
    age(run)
    jd, code = batch(tmp, monkeypatch, [run], "extremes", spec.RunSettings(reuse=True, stride=20))
    assert code == 0
    assert jobstate.load_state(jd)["runs"][0]["reused"] is False   # different stride: redone
