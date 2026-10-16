"""Sizer 3.0.0 in the pipeline (sizer 3.0.0 plan, Phase 4, 2026-10-16). Droplets are Blaisot's model discs (opacity
1 - tau, Gaussian PSF exp(-2 r^2/chi^2), 10 um pixels), so the true size and blur are known; the calibration is a test
profile's (HPATR_OPTICS_DIR), not the rig's. In the volume if chi <= chi_max and its window fits in the frame; sized
directly up to chi_sharp, through the table up to chi_max; below d_min counted, not sized; 2.x untouched."""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from pycocotools import mask as mask_util

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

mr = spec.rdc_module("measure_run")
blur = spec.rdc_module("blur")
UP = 8
TAU = 0.11
TABLE = {"chi_um": [13.0, 20.0, 40.0, 60.0], "nodes_um": [40.0, 80.0],
         "delta_um": [[0.0, 2.0, 6.0, 9.0], [0.0, 1.0, 3.0, 4.0]], "sigma_um": [[1.0] * 4, [1.0] * 4],
         "chi_reach_um": 60.0}
CAL = {"status": "test", "tau": TAU, "edge_base": "blaisot", "edge_offset_um": 1.5, "chi_sharp_um": 15.0,
       "chi_max_um": 40.0, "d_min_um": 30.0, "lookup_table": TABLE}


def calib():
    return blur.sizer3({"name": "t", "calibration": CAL})


def render(T, d_um, chi_um, cx, cy):
    """Multiply a model disc into T (in place); return its AI-style mask (the true disc) as a frame-sized bool."""
    half = int(d_um / 20 + 3 * chi_um / 10 + 6)
    x0, y0 = int(cx) - half, int(cy) - half
    n = 2 * half + 1
    yy, xx = np.mgrid[0:n * UP, 0:n * UP]
    xs, ys = (xx + 0.5) / UP - 0.5 + x0, (yy + 0.5) / UP - 0.5 + y0
    t = np.where((xs - cx) ** 2 + (ys - cy) ** 2 <= (d_um / 20) ** 2, TAU, 1.0).astype(np.float32)
    t = cv2.GaussianBlur(t, (0, 0), chi_um / 2 / 10 * UP)
    patch = cv2.resize(t, (n, n), interpolation=cv2.INTER_AREA)
    ya, yb, xa, xb = max(0, y0), min(T.shape[0], y0 + n), max(0, x0), min(T.shape[1], x0 + n)
    T[ya:yb, xa:xb] *= patch[ya - y0:yb - y0, xa - x0:xb - x0]
    m = np.zeros(T.shape, np.uint8)
    cv2.circle(m, (int(round(cx)), int(round(cy))), max(1, int(round(d_um / 20))), 1, -1)
    return m.astype(bool)


def det(img_id, m, cat=None):
    r = mask_util.encode(np.asfortranarray(m.astype(np.uint8)))
    r["counts"] = r["counts"].decode("ascii")
    x, y, w, h = (float(v) for v in mask_util.toBbox(r))
    return {"image_id": img_id, "category_id": cat or mr.DROPLET, "score": 0.9, "segmentation": r,
            "area": float(mask_util.area(r)), "bbox": [x, y, w, h]}


# the cases: (true diameter um, optical blur chi um, centre) -> what 3.0.0 must make of it
CASES = [(60.0, 12.5, (60.0, 60.0), "direct"), (100.0, 12.5, (160.0, 60.0), "direct"),
         (60.0, 28.0, (260.0, 60.0), "table"), (60.0, 75.0, (360.0, 70.0), "outside"),
         (20.0, 12.5, (440.0, 60.0), "below_d_min"), (60.0, 12.5, (6.0, 140.0), "border")]


def frame():
    T = np.ones((180, 480), np.float32)
    masks = [render(T, d, c, *xy) for d, c, xy, _ in CASES]
    return T, masks


def test_each_droplet_gets_the_verdict_and_size_3_0_0_gives_it():
    T, masks = frame()
    cal = calib()
    for (d_um, chi, _xy, want), m in zip(CASES, masks):
        md = mr.measure_droplet(T, det(1, m), 0.70, version="3.0.0", calib=cal, want_mask=True)
        assert md["method"] == want, (d_um, chi, md)
        assert md["in_volume"] == (want in ("direct", "table", "below_d_min"))
        assert md["in_focus"] == (want in ("direct", "table"))
        if md["in_focus"]:
            # Blaisot's size of his own model disc is the true size; minus the 1.5 um offset and the table's Delta
            expect = d_um - 1.5 - (np.interp(md["chi_um"], TABLE["chi_um"], TABLE["delta_um"][0]) * 0.5
                                   + np.interp(md["chi_um"], TABLE["chi_um"], TABLE["delta_um"][1]) * 0.5
                                   if want == "table" else 0.0)
            assert md["size_um"] == pytest.approx(expect, rel=0.06)
            assert float(mr.equiv_um(md["area_px"])) == pytest.approx(md["size_um"], abs=1e-9)
            assert md["mask"] is not None                        # the atomised numerator's half-max edge
        else:
            assert math.isnan(md["size_um"]) and md["area_px"] == float(m.sum()) and md["mask"] is None
    assert abs(mr.measure_droplet(T, det(1, masks[0]), 0.70, version="3.0.0", calib=cal)["chi_um"] - 13) < 2.5


def test_the_frame_counts_what_is_in_the_volume_and_what_is_sized():
    T, masks = frame()
    mr.SIZER3 = calib()
    try:
        fr = mr.measure_frame(T, [det(1, m) for m in masks], 0.70, version="3.0.0")
    finally:
        mr.SIZER3 = None
    assert len(fr["focus_a"]) == 3 and len(fr["oof_a"]) == 3
    assert (fr["in_volume"], fr["unsized"], fr["border"]) == (4, 1, 1)
    assert [r[4] for r in fr["rows3"]] == [c[3] for c in CASES]


def test_a_droplet_beside_the_jet_is_measured_on_its_own_profile():
    """The 2026-10-16 spray check: a small droplet beside a dark ligament read 200-550 um, because the bead code takes
    the nearest dark piece when the centre is pale, and that was the ligament. Others are now blanked out."""
    cal = calib()
    alone = np.ones((140, 240), np.float32)
    m = render(alone, 60.0, 12.5, 60.0, 70.0)
    jet = np.zeros(alone.shape, bool)
    jet[:, 80:120] = True                                    # a ligament ~10 px beyond the droplet's edge
    jet_t = cv2.GaussianBlur(np.where(jet, 0.15, 1.0).astype(np.float32), (0, 0), 1.2)
    near = alone * jet_t
    ref = mr.measure_droplet(alone, det(1, m), 0.70, version="3.0.0", calib=cal)
    md = mr.measure_droplet(near, det(1, m), 0.70, version="3.0.0", calib=cal,
                            others=mr.occupancy(near.shape, [det(1, m), det(1, jet, mr.FILAMENT)]))
    assert md["method"] == "direct" and md["size_um"] == pytest.approx(ref["size_um"], rel=0.03)
    lone = mr.measure_droplet(alone, det(1, m), 0.70, version="3.0.0", calib=cal,
                              others=mr.occupancy(alone.shape, [det(1, m)]))
    assert lone["size_um"] == pytest.approx(ref["size_um"], abs=1e-9)   # nothing to blank: exactly the beads' way


def test_a_droplet_touching_another_detection_is_crowded():
    cal = calib()
    T = np.ones((140, 240), np.float32)
    a = render(T, 60.0, 12.5, 60.0, 70.0)
    b = render(T, 60.0, 12.5, 66.0, 70.0)                    # overlapping: two droplets the AI split
    md = mr.measure_droplet(T, det(1, a), 0.70, version="3.0.0", calib=cal,
                            others=mr.occupancy(T.shape, [det(1, a), det(1, b)]))
    assert md["method"] == "crowded" and not md["in_volume"] and not md["in_focus"]


def test_2_x_is_untouched():
    T, masks = frame()
    for sharp in (True, False):
        a = mr.measure_droplet(T * 1.0, det(1, masks[1]), 0.70, sharpness_rule=sharp)
        b = mr.measure_droplet(T * 1.0, det(1, masks[1]), 0.70, sharpness_rule=sharp,
                               version="2.2.0" if sharp else "2.1.0")
        assert a == b and "chi_um" not in a
    assert mr.measure_frame(T, [det(1, m) for m in masks], 0.70)["rows3"] == []


# ---- a whole synthetic run through measure_run.py --sizer 3.0.0 --------------------------------------------

BG = 40000.0


@pytest.fixture(scope="module")
def run3(tmp_path_factory):
    root = tmp_path_factory.mktemp("sizer3")
    prof = root / "optics"
    prof.mkdir()
    (prof / "test_lens.json").write_text(json.dumps({"name": "test_lens", "valid_from": "2000-01-01",
                                                     "um_per_px": 10.0, "calibration": CAL}))
    run = root / "120000_9000sccm_500rpm_4000sps_or1.2_bh0.5"
    raw = run / "shadowgraph" / "raw"
    for d in (raw / "frames" / "16bit", raw / "frames" / "8bit", run / "shadowgraph" / "analysis"):
        d.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(raw / "background_median.tiff"), np.full((180, 480), BG, np.uint16))
    images, preds = [], []
    for i in range(3):
        stem = f"frame_{i:04d}_n{i * 10 - 1}"
        T, masks = frame()
        fil = np.zeros(T.shape, bool)
        fil[160:168, 40:400] = True
        T[fil] *= 0.3
        cv2.imwrite(str(raw / "frames" / "16bit" / f"{stem}.tiff"), (T * BG).astype(np.uint16))
        cv2.imwrite(str(raw / "frames" / "8bit" / f"{stem}.png"), (T * 255).astype(np.uint8))
        images.append({"id": i + 1, "file_name": f"{stem}.png", "width": 480, "height": 180})
        preds += [det(i + 1, m) for m in masks] + [det(i + 1, fil, mr.FILAMENT)]
    (raw / "instances.json").write_text(json.dumps({"images": images}))
    (run / "shadowgraph" / "analysis" / "predictions.json").write_text(json.dumps(preds))
    env = dict(os.environ, HPATR_OPTICS_DIR=str(prof))
    env.pop("HPATR_OPTICS_PROFILE", None)
    meas = run / "shadowgraph" / "analysis" / "droplets_0.30"
    cmd = [sys.executable, "-W", "ignore", str(Path(mr.__file__)), "--pred",
           str(run / "shadowgraph" / "analysis" / "predictions.json"), "--root", str(run),
           "--val-dir", "shadowgraph/raw", "--background", str(raw / "background_median.tiff"),
           "--sixteen-bit-dir", str(raw / "frames" / "16bit"), "--score-thresh", "0.30",
           "--out-dir", str(meas), "--n-boot", "20", "--sizer", "3.0.0"]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return {"run": run, "meas": meas, "env": env, "stdout": p.stdout}


def test_a_3_0_0_run_records_every_droplet_and_its_calibration(run3):
    meas = run3["meas"]
    with open(meas / "droplet_sizes.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == ["frame", "diameter_um", "in_focus", "chi_um", "in_volume", "size_method"]
    assert len(rows) == 3 * len(CASES)
    assert [r["size_method"] for r in rows[:len(CASES)]] == [c[3] for c in CASES]
    sized = [float(r["diameter_um"]) for r in rows[:len(CASES)] if r["in_focus"] == "1"]
    assert sized[0] == pytest.approx(58.5, rel=0.06) and sized[1] == pytest.approx(98.5, rel=0.06)
    with open(meas / "per_frame.csv", newline="") as f:
        pf = list(csv.DictReader(f))
    assert (pf[0]["droplets_in_focus"], pf[0]["droplets_in_volume"], pf[0]["droplets_unsized_in_volume"],
            pf[0]["droplets_border"], pf[0]["droplets_crowded"]) == ("3", "4", "1", "1", "0")
    s = json.loads((meas / "summary.json").read_text())
    p = s["provenance"]
    assert p["sizer_version"] == "3.0.0" and p["optics_profile"] == "test_lens"
    assert p["optics_profile_hash"] == calib()["hash"] and p["sizer_chi_max_um"] == 40.0
    assert p["sizer_edge"] == "blaisot - 1.5 um" and p["sizer_d_min_um"] == 30.0
    assert s["droplets_in_volume"] == 12 and s["droplets_unsized_in_volume"] == 3 and s["droplets_border"] == 3
    assert "measurement volume" in s["definitions"]["d32"]
    assert "sizer 3.0.0: in the volume 12" in run3["stdout"]


def test_the_extremes_backfill_re_measures_a_3_0_0_run_to_the_same_numbers(run3, monkeypatch):
    rme = spec.rdc_module("render_more_extremes")
    monkeypatch.setenv("HPATR_OPTICS_DIR", run3["env"]["HPATR_OPTICS_DIR"])
    s = json.loads((run3["meas"] / "summary.json").read_text())
    with open(run3["meas"] / "per_frame.csv", newline="") as f:
        stems = [r["frame"] for r in csv.DictReader(f)]
    out, _view = rme.remeasure(run3["run"], run3["meas"], s["provenance"], stems[:1], 0.30)
    fr = out[stems[0]]
    assert len(fr["focus_a"]) == 3 and fr["in_volume"] == 4
    mr.SIZER3 = None


def test_a_3_0_0_run_refuses_to_redraw_with_another_calibration(run3, monkeypatch, tmp_path):
    rme = spec.rdc_module("render_more_extremes")
    other = tmp_path / "optics"
    other.mkdir()
    (other / "test_lens.json").write_text(json.dumps({"name": "test_lens", "valid_from": "2000-01-01",
                                                      "um_per_px": 10.0, "calibration": dict(CAL, chi_max_um=35.0)}))
    monkeypatch.setenv("HPATR_OPTICS_DIR", str(other))
    s = json.loads((run3["meas"] / "summary.json").read_text())
    with pytest.raises(RuntimeError, match="re-measure the run first"):
        rme.remeasure(run3["run"], run3["meas"], s["provenance"], [], 0.30)
    mr.SIZER3 = None


def test_the_liquid_stage_measures_droplets_at_3_0_0(run3):
    cl = spec.paths.RDC_DIR / "classical_liquid.py"
    out = run3["run"] / "shadowgraph" / "analysis" / "liquid_0.30"
    p = subprocess.run([sys.executable, "-W", "ignore", str(cl), "--root", str(run3["run"]), "--out-dir", str(out),
                        "--score-thresh", "0.30", "--sizer", "3.0.0"], capture_output=True, text=True,
                       env=run3["env"])
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    s = json.loads((out / "classical_summary.json").read_text())
    assert s["provenance"]["sizer_version"] == "3.0.0"
    assert s["provenance"]["optics_profile_hash"] == calib()["hash"]


def test_a_profile_without_a_calibration_is_refused_plainly(tmp_path):
    prof = tmp_path / "optics"
    prof.mkdir()
    (prof / "bare.json").write_text(json.dumps({"name": "bare", "valid_from": "2000-01-01", "um_per_px": 10.0}))
    env = dict(os.environ, HPATR_OPTICS_DIR=str(prof))
    env.pop("HPATR_OPTICS_PROFILE", None)
    p = subprocess.run([sys.executable, "-W", "ignore", str(Path(mr.__file__)), "--root", str(tmp_path),
                        "--pred", "x", "--background", "y", "--sizer", "3.0.0"], capture_output=True, text=True,
                       env=env)
    assert p.returncode != 0 and "no sizer 3.0.0 calibration" in p.stderr


def test_the_app_and_the_pipeline_pass_the_version_on():
    pc = spec.rdc_module("process_capture")
    assert pc.sizer_flags(None, True) == ["--sharpness-rule"] and pc.sizer_flags(None, False) == ["--no-sharpness-rule"]
    assert pc.sizer_flags("3.0.0", True) == ["--sizer", "3.0.0"]
    s = spec.RunSettings(sizer="3.0.0")
    assert spec.sizer_of(s) == "3.0.0" and spec.sizer_of(spec.RunSettings()) == "2.2.0"
    assert spec.sizer_of(spec.RunSettings(sharpness_rule=False)) == "2.1.0"
    cmd = spec.classical_cmd(Path("/tmp/x"), s, {})
    assert cmd[-2:] == ["--sizer", "3.0.0"]
    assert spec.classical_cmd(Path("/tmp/x"), spec.RunSettings(), {})[-1] == "--sharpness-rule"


def test_a_job_keeps_its_sizer_when_resumed():
    jobstate = __import__("src.ai.Taguchi_Analysis_UI.jobstate", fromlist=["x"])
    d = jobstate._settings_dict(spec.RunSettings(sizer="3.0.0"))
    assert jobstate.settings_from(json.loads(json.dumps(d))).sizer == "3.0.0"
    old = jobstate.settings_from({"score_thresh": 0.3})          # saved before the sharpness rule existed
    assert spec.sizer_of(old) == "2.1.0"
