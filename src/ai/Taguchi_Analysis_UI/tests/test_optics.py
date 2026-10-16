"""optics.py (sizer 3.0.0 plan, Phase 0, 2026-10-15): one profile per optical set-up, picked per capture.
Phase 0 changes no number: every place that used to say 10 um/px still gets 10.0, now from the profile. The
two-profile cases are what keeps a future lens (the 3x lens) from ever giving an old run the wrong scale."""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import run_metrics

optics = spec.rdc_module("optics")


def _profile(folder: Path, name: str, valid_from: str, um: float, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"name": name, "valid_from": valid_from, "um_per_px": um,
                                                     **extra}))


def _run(folder: Path, profile_name: str | None):
    folder.mkdir(parents=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Metadata"
    ws.append(["Field", "Value"])
    ws.append(["Notes", "x"])
    if profile_name is not None:
        ws.append(["Optics profile", profile_name])
    wb.save(folder / "run_summary.xlsx")
    return folder


@pytest.fixture
def two_lenses(tmp_path, monkeypatch):
    d = tmp_path / "optics"
    _profile(d, "lens1", "2025-01-01", 10.0)
    _profile(d, "lens3x", "2027-01-01", 3.3)
    monkeypatch.setenv(optics.ENV_DIR, str(d))
    monkeypatch.delenv(optics.ENV_PROFILE, raising=False)
    return tmp_path


def test_the_real_profile_is_the_current_set_up_at_10_um_per_px(monkeypatch):
    monkeypatch.delenv(optics.ENV_DIR, raising=False)
    monkeypatch.delenv(optics.ENV_PROFILE, raising=False)
    p = optics.current()
    assert p["name"] == "lens1_2026-10" and p["um_per_px"] == 10.0
    assert optics.profile_for() is p and optics.um_per_px("/Volumes/LaCie/Experiments/2026/10/12/r") == 10.0
    assert optics.mm2_per_px() == pytest.approx(1e-4)
    assert set(p["calibration"]) >= {"edge_level", "chi_max_um", "d_min_um", "depth_mm", "lookup_table"}


def test_phase_0_changes_no_number_anywhere(monkeypatch):
    monkeypatch.delenv(optics.ENV_DIR, raising=False)
    monkeypatch.delenv(optics.ENV_PROFILE, raising=False)
    for mod in ("measure_run", "classical_liquid", "bead_calibration", "run_stats", "score_v2",
                "validation_to_coco", "preview_predictions", "extract_candidates"):
        assert spec.rdc_module(mod).UM_PER_PX == 10.0, mod
    assert spec.rdc_module("measure_run").equiv_um(100.0) == pytest.approx(112.838, abs=1e-3)
    from gui import window_check
    assert window_check.UM_PER_PX == 10.0 and window_check.MIN_AREA_PX == 400
    assert run_metrics.mm2_per_px(Path("/x/2026/10/12/run/shadowgraph")) == pytest.approx(1e-4)


def test_a_run_says_which_optics_it_was_taken_with(two_lenses):
    run = _run(two_lenses / "2027" / "03" / "01" / "120000_run", "lens1")       # dated after lens3x, but says lens1
    assert optics.profile_for(run)["name"] == "lens1"
    inside = run / "shadowgraph" / "analysis" / "liquid_0.30" / "classical_components.csv"
    assert optics.um_per_px(inside) == 10.0                                    # found by walking up to the run


def test_otherwise_the_capture_date_decides(two_lenses):
    assert optics.profile_for(two_lenses / "2026" / "10" / "12" / "r")["name"] == "lens1"
    assert optics.profile_for(two_lenses / "2027" / "02" / "01" / "r")["name"] == "lens3x"
    assert optics.profile_for(_run(two_lenses / "2027" / "02" / "02" / "r", None))["name"] == "lens3x"
    assert optics.current()["name"] == "lens3x"                                # the newest: what the rig has now


def test_with_two_set_ups_an_undated_path_is_refused_not_guessed(two_lenses, monkeypatch):
    with pytest.raises(optics.OpticsProfileError, match="several optics profiles"):
        optics.profile_for(two_lenses / "Real_Data")
    with pytest.raises(optics.OpticsProfileError, match="several optics profiles"):
        optics.um_per_px()
    monkeypatch.setenv(optics.ENV_PROFILE, "lens1")                            # a tool on old data says so
    assert optics.um_per_px() == 10.0 and optics.um_per_px(two_lenses / "2027" / "02" / "01") == 10.0


def test_a_bad_profile_is_named_clearly(tmp_path, monkeypatch):
    d = tmp_path / "optics"
    _profile(d, "lens1", "2025-01-01", 10.0)
    monkeypatch.setenv(optics.ENV_DIR, str(d))
    with pytest.raises(optics.OpticsProfileError, match="no optics profile 'nope'"):
        optics.load("nope")
    with pytest.raises(optics.OpticsProfileError, match="no optics profile valid on 2024-06-01"):
        optics.profile_for(tmp_path / "2024" / "06" / "01" / "r")
    (d / "wrongname.json").write_text(json.dumps({"name": "other", "valid_from": "2026-01-01", "um_per_px": 5}))
    with pytest.raises(optics.OpticsProfileError, match="must be named after it"):
        optics.profiles()
    (d / "wrongname.json").unlink()
    (d / "partial.json").write_text(json.dumps({"name": "partial", "valid_from": "2026-01-01"}))
    with pytest.raises(optics.OpticsProfileError, match="missing um_per_px"):
        optics.profiles()
