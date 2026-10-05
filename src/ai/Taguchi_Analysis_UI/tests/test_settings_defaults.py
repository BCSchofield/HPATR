"""settings_defaults.py: every default is the pipeline's own, read live."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import eta, size_bins
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI import settings_defaults as sd

LACIE_MODEL = Path("/Volumes/LaCie/Experiments/AI/Eden")


@pytest.fixture
def pc():
    return spec.rdc_module("process_capture")


@pytest.fixture
def ti():
    return spec.rdc_module("tiled_inference")


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ---- follows the pipeline ------------------------------------------------------------------------

def test_threshold_and_stride_follow_the_pipelines_constants_live(pc, monkeypatch):
    assert sd.score_threshold().value == pc.DEFAULT_SCORE_THRESH
    assert sd.stride().value == pc.DEFAULT_STRIDE
    monkeypatch.setattr(pc, "DEFAULT_SCORE_THRESH", 0.35)
    monkeypatch.setattr(pc, "DEFAULT_STRIDE", 7)
    assert sd.score_threshold().value == 0.35 and "droplets_0.35" in sd.score_threshold().note
    assert sd.stride().value == 7


def test_the_decorrelation_arithmetic_follows_the_pipelines_constant(pc, monkeypatch):
    assert sd.independent_stride(390) == 8                  # 20.5 ms x 390 fps = 7.995 frames
    monkeypatch.setattr(pc, "DECORRELATION_S", 0.040)
    assert sd.independent_stride(390) == 16


def test_stride_note_says_what_it_means_at_the_selected_frame_rates():
    d = sd.stride([390.0, 390.0])
    assert "390 fps: frames 25.6 ms apart" in d.note and "20.5 ms" in d.note and d.warn == ""
    assert d.note.count("390 fps") == 1                      # one line per distinct rate


def test_a_stride_shorter_than_the_decorrelation_time_warns_and_names_a_better_one():
    d = sd.stride([390.0], chosen=5)
    assert "closer than the 20.5 ms decorrelation time" in d.warn and "stride 8 would be independent" in d.note
    assert sd.stride([1000.0]).warn                          # the default is too short at 1000 fps
    assert sd.stride([390.0], chosen=8).warn == ""


def test_ci_stride_is_auto_and_resolved_per_run_by_the_pipelines_function(pc):
    d = sd.ci_stride([390.0, 390.0, 1000.0], 1)
    assert d.value == "auto"
    assert f"{pc.auto_ci_stride(390, 1)} for 2 runs" in d.note and f"{pc.auto_ci_stride(1000, 1)} for 1 run" in d.note
    assert "1 for 3 runs" in sd.ci_stride([390.0] * 3, 10).note       # 390 fps, stride 10: already independent
    assert "select runs" in sd.ci_stride([], 10).note


def test_bin_defaults_come_from_size_bins():
    assert sd.bin_width().value == size_bins.DEFAULT_WIDTH_UM and sd.bin_max().value == size_bins.DEFAULT_MAX_UM


# ---- device ---------------------------------------------------------------------------------------

def test_device_is_whatever_the_pipelines_auto_device_says(ti, monkeypatch):
    monkeypatch.setattr(ti, "auto_device", lambda: "cuda")
    d = sd.device("Windows")
    assert d.value == "cuda" and d.ok and d.warn == "" and "auto_device" in d.note
    monkeypatch.setattr(ti, "auto_device", lambda: "cpu")
    assert sd.device("Windows").value == "cpu"


def test_cpu_on_a_mac_quotes_the_measured_rate_from_the_eta_priors(ti, monkeypatch):
    monkeypatch.setattr(ti, "auto_device", lambda: "cpu")
    w = sd.device("Darwin").warn
    per_frame, minutes = sd.cpu_inference_estimate("Darwin")
    assert f"{per_frame:.1f} s/frame" in w and f"{minutes:.0f} min" in w and "MacBook Air" in w
    assert per_frame == pytest.approx(eta.priors_for("Darwin")[("inference", None)][1] / eta.REF_FRAMES)
    assert 5 < per_frame < 7


def test_cpu_off_a_mac_does_not_claim_a_measurement_it_does_not_have(ti, monkeypatch):
    monkeypatch.setattr(ti, "auto_device", lambda: "cpu")
    w = sd.device("Windows").warn
    assert "No usable CUDA GPU" in w and "MacBook" not in w and sd.cpu_inference_estimate("Windows") is None


def test_device_warnings_for_the_choices_a_user_can_make():
    assert sd.device_warning("mps", "cpu", "Darwin").startswith("MPS is experimental")
    assert "probably fail" in sd.device_warning("cuda", "cpu", "Windows")
    assert sd.device_warning("cuda", "cuda", "Windows") == "" and sd.device_warning(None, "cuda", "Windows") == ""
    assert "slow" in sd.device_warning("cpu", "cuda", "Darwin")       # chosen cpu even though a GPU exists


def test_a_pipeline_that_cannot_be_asked_does_not_kill_the_window(ti, monkeypatch):
    def exits():
        raise SystemExit("torch exploded")
    monkeypatch.setattr(ti, "auto_device", exits)
    d = sd.device()
    assert not d.ok and "torch exploded" in d.note and d.value == "cpu"


# ---- model folder ---------------------------------------------------------------------------------

def make_model(root: Path, name: str, *, meta: dict | None = None, raw: bool = False) -> Path:
    folder = root / name
    folder.mkdir()
    (folder / ("model_best.pth" if raw else f"{name}.pth")).write_bytes(b"weights")
    if meta is not None:
        (folder / ("model_best.json" if raw else f"{name}_summary.json")).write_text(json.dumps(meta))
    return folder


def test_a_promoted_model_reports_its_checkpoint_iteration_and_ap(tmp, ti):
    info = sd.inspect_model(make_model(tmp, ti.PRODUCTION_MODEL, meta={"iteration": 19000, "segm_AP": 66.84}))
    assert info.ok and info.weights.name == f"{ti.PRODUCTION_MODEL}.pth" and info.iteration == 19000
    assert info.segm_ap == pytest.approx(66.84) and info.warn == ""
    text = sd.describe_model(info)
    assert "iteration 19000" in text and "segm AP 66.8" in text and "not on real frames" in text


def test_a_raw_training_output_is_read_the_way_the_pipeline_reads_it(tmp):
    info = sd.inspect_model(make_model(tmp, "training_x", meta={"iteration": 500, "segm_AP": 3.2}, raw=True))
    assert info.ok and info.weights.name == "model_best.pth" and info.iteration == 500


def test_a_model_that_is_not_the_promoted_one_says_so(tmp, ti):
    info = sd.inspect_model(make_model(tmp, "Benedict", meta={"iteration": 9000}))
    assert info.ok and f"Not the promoted production model ({ti.PRODUCTION_MODEL})" in info.warn
    assert info.segm_ap is None and "segm AP" not in sd.describe_model(info)


def test_a_folder_without_weights_or_a_non_folder_is_refused_with_a_reason(tmp):
    empty = tmp / "empty"
    empty.mkdir()
    a = sd.inspect_model(empty)
    assert not a.ok and "no weights" in a.note and "empty.pth" in a.note        # find_weights' own message
    b = sd.inspect_model(tmp / "nothing")
    assert not b.ok and "not a folder" in b.note


def test_a_corrupt_summary_file_does_not_stop_the_model_loading(tmp):
    folder = make_model(tmp, "Mx")
    (folder / "Mx_summary.json").write_text("{not json")
    info = sd.inspect_model(folder)
    assert info.ok and info.iteration is None


def test_default_model_failing_gives_an_instruction_not_a_crash(ti, monkeypatch):
    def exits():
        raise SystemExit("LaCie drive not found. Pass --model-dir explicitly.")
    monkeypatch.setattr(ti, "default_model_dir", exits)
    m = sd.model()
    assert not m.ok and m.folder is None and "LaCie drive not found" in m.note and "choose a model folder" in m.note


def test_a_fallback_the_pipeline_announces_is_shown_as_a_warning(tmp, ti, monkeypatch):
    folder = make_model(tmp, "training_2026", meta={"iteration": 500}, raw=True)

    def falls_back():
        print("  (no Eden/ found -- falling back to the newest training run)")
        return folder
    monkeypatch.setattr(ti, "default_model_dir", falls_back)
    m = sd.model()
    assert m.ok and m.folder == folder and "falling back to the newest training run" in m.warn
    assert "Not the promoted production model" in m.warn


@pytest.mark.skipif(not LACIE_MODEL.is_dir(), reason="LaCie not mounted")
def test_the_real_production_model_is_found_and_described():
    m = sd.model()
    assert m.ok and m.folder == LACIE_MODEL and m.weights.name == "Eden.pth" and m.iteration == 19000
    assert m.warn == "" and "iteration 19000" in sd.describe_model(m)


# ---- parsing what the user types -------------------------------------------------------------------------

@pytest.mark.parametrize("text,ok", [("0.3", True), ("1", True), (" 0.05 ", True), ("0", False), ("-0.1", False),
                                     ("1.01", False), ("abc", False), ("", False), ("nan", False)])
def test_threshold_parsing(text, ok):
    if ok:
        assert 0 < sd.parse_threshold(text) <= 1
    else:
        with pytest.raises(sd.Invalid):
            sd.parse_threshold(text)


@pytest.mark.parametrize("text,ok", [("10", True), ("10.0", True), ("1", True), ("0", False), ("-3", False),
                                     ("2.5", False), ("x", False), ("", False)])
def test_whole_number_parsing(text, ok):
    if ok:
        assert sd.parse_positive_int(text) == int(float(text))
    else:
        with pytest.raises(sd.Invalid):
            sd.parse_positive_int(text)


def test_ci_stride_parsing_treats_blank_and_auto_as_the_pipelines_choice():
    assert sd.parse_ci_stride("") is None and sd.parse_ci_stride("auto") is None and sd.parse_ci_stride(" AUTO ") is None
    assert sd.parse_ci_stride("4") == 4
    with pytest.raises(sd.Invalid):
        sd.parse_ci_stride("0")


def test_micrometre_parsing():
    assert sd.parse_um("25", "w") == 25.0
    for bad in ("0", "-5", "inf", "nan", "x", ""):
        with pytest.raises(sd.Invalid):
            sd.parse_um(bad, "w")


def test_everything_the_settings_tab_asks_the_pipeline_is_in_the_preflight_contract():
    """If the pipeline renames one of these, preflight must say so before the tab quietly breaks."""
    helpers = {(c.module, c.func.split(".")[-1]) for c in spec.HELPERS}
    for need in (("process_capture", "auto_ci_stride"), ("tiled_inference", "auto_device"),
                 ("tiled_inference", "default_model_dir"), ("tiled_inference", "find_weights")):
        assert need in helpers, need
    constants = set(spec.CONSTANTS)
    for need in (("process_capture", "DEFAULT_SCORE_THRESH"), ("process_capture", "DEFAULT_STRIDE"),
                 ("process_capture", "DECORRELATION_S"), ("tiled_inference", "PRODUCTION_MODEL")):
        assert need in constants, need
