"""Sizer 3.1.0's validity tests (plan 2026-10-17). The CCD day at 3.0.0 showed small droplets reading 200-430 um when
dark liquid the AI did not detect sat beside them (a jet edge, a ligament, the shadow of a drop on the window): 3.0.0
blanks only other DETECTIONS. 3.1.0 blanks every piece of liquid (liquid_map), and a droplet that sits on liquid
(attached), in a dark window (dark_surround), reads far above its own mask (inconsistent) or is a speck in the same
place frame after frame (static) is not sized. Isolated droplets, as the beads are, must come out exactly as 3.0.0."""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec
from src.ai.Taguchi_Analysis_UI.tests.test_sizer3 import BG, CAL, CASES, calib, det, frame, render

mr = spec.rdc_module("measure_run")
blur = spec.rdc_module("blur")
liquid_map = spec.rdc_module("liquid_map")


@pytest.fixture(autouse=True)
def _calib():
    old = mr.SIZER3
    mr.SIZER3 = calib()
    yield
    mr.SIZER3 = old


def measure(T, m, others_dets, version="3.1.0", liquid=True):
    """One droplet (mask m) measured at `version`, with the frame's detections (and, at 3.1.0, its liquid map)."""
    lq = liquid_map.hysteresis(T)[0] if (liquid and version == "3.1.0") else None
    return mr.measure_droplet(T, det(1, m), 0.70, version=version, calib=mr.SIZER3,
                              others=mr.occupancy(T.shape, others_dets, lq))


def bar(shape, x0, x1, t=0.15, sigma=1.2):
    """A dark ligament the AI did NOT detect, as a transmission field to multiply in."""
    b = np.zeros(shape, bool)
    b[:, x0:x1] = True
    return cv2.GaussianBlur(np.where(b, t, 1.0).astype(np.float32), (0, 0), sigma)


def test_an_isolated_droplet_comes_out_exactly_as_3_0_0():
    """The beads' case: nothing round it, so none of the tests may fire and every number is 3.0.0's."""
    T, masks = frame()
    dets = [det(1, m) for m in masks]
    f30 = mr.measure_frame(T, dets, 0.70, version="3.0.0")
    f31 = mr.measure_frame(T, dets, 0.70, version="3.1.0")
    same = lambda rows: [tuple("nan" if isinstance(v, float) and math.isnan(v) else v for v in r[:6]) for r in rows]
    assert same(f31["rows3"]) == same(f30["rows3"])
    assert [r[4] for r in f31["rows3"]] == [want for *_x, want in CASES]
    assert f31["attached"] == f31["dark_surround"] == f31["inconsistent"] == f31["static"] == 0
    for r, m in zip(f31["rows3"], masks):          # x, y and the mask's own size are recorded
        ys, xs = np.nonzero(m)
        assert r[6] == pytest.approx(xs.mean()) and r[7] == pytest.approx(ys.mean())
        assert r[8] == pytest.approx(2 * math.sqrt(m.sum() / math.pi) * mr.UM_PER_PX)


def test_undetected_liquid_beside_a_droplet_is_blanked():
    """A blurred ligament 9 px off, not a detection: its halo joins the droplet's, so 3.0.0 measures the two as one
    object and loses the droplet; 3.1.0 blanks the ligament (it is liquid) and measures the droplet as if alone."""
    alone = np.ones((140, 240), np.float32)
    m = render(alone, 60.0, 12.5, 60.0, 70.0)
    near = alone * bar(alone.shape, 72, 112, sigma=4.0)
    ref = measure(alone, m, [det(1, m)], version="3.0.0")
    v30 = measure(near, m, [det(1, m)], version="3.0.0")
    v31 = measure(near, m, [det(1, m)])
    assert v30["method"] != "direct"
    assert v31["method"] == "direct" and v31["size_um"] == pytest.approx(ref["size_um"], rel=0.03)


def test_a_droplet_sitting_on_a_ligament_is_attached_and_not_sized():
    """The AI calls a bump on a ligament, or a droplet over one, a droplet: its piece of liquid is the ligament."""
    T = np.ones((140, 240), np.float32)
    m = render(T, 40.0, 12.5, 98.0, 70.0)
    T *= bar(T.shape, 100, 112)                               # the droplet overlaps the ligament's edge
    v30 = measure(T, m, [det(1, m)], version="3.0.0")
    v31 = measure(T, m, [det(1, m)])
    assert v30["in_focus"] and v30["size_um"] > 200.0         # the 3.0.0 fault as on CCD 143415 (276 um)
    assert v31["method"] == "attached" and not v31["in_focus"] and not v31["in_volume"]
    assert math.isnan(v31["size_um"]) and v31["area_px"] == float(m.sum())


def test_a_speck_in_the_shadow_of_a_drop_on_the_window_is_not_sized():
    """CCD 123534: a speck inside a far-out-of-focus drop on the window read 332-358 um at 3.0.0."""
    for depth, sigma, dist in ((0.7, 10, 12), (0.6, 15, 18), (0.7, 35, 30)):
        T = np.ones((240, 240), np.float32)
        yy, xx = np.mgrid[0:240, 0:240]
        T *= (1.0 - depth * np.exp(-((xx - 120) ** 2 + (yy - 120) ** 2) / (2 * sigma ** 2))).astype(np.float32)
        m = render(T, 30.0, 12.5, 120.0 - dist, 120.0)        # on the shadow's flank
        v31 = measure(T, m, [det(1, m)])
        assert v31["method"] in ("attached", "dark_surround", "crowded") and not v31["in_focus"], (depth, v31)


def test_a_dark_window_with_no_liquid_piece_is_dark_surround():
    """Haze too faint to seed the liquid map (T > 0.70 everywhere) but dark round the droplet: not a clear background,
    so Blaisot's size is not to be trusted."""
    T = np.full((140, 240), 0.82, np.float32)                  # a uniform veil, nothing below 0.70 but the droplet
    m = render(T, 60.0, 12.5, 120.0, 70.0)
    v31 = measure(T, m, [det(1, m)])
    assert v31["method"] == "dark_surround" and not v31["in_focus"]


def test_a_size_far_above_its_own_mask_is_inconsistent():
    """The safety net: a 100 um droplet whose AI mask covers only its middle reads ~3x its mask."""
    T = np.ones((140, 240), np.float32)
    render(T, 100.0, 12.5, 120.0, 70.0)
    small = np.zeros(T.shape, np.uint8)
    cv2.circle(small, (120, 70), 1, 1, -1)
    v30 = measure(T, small.astype(bool), [det(1, small.astype(bool))], version="3.0.0")
    v31 = measure(T, small.astype(bool), [det(1, small.astype(bool))])
    assert v30["in_focus"] and v30["size_um"] > mr.INCONSISTENT_MAX * 2 * math.sqrt(small.sum() / math.pi) * 10
    assert v31["method"] == "inconsistent" and not v31["in_focus"] and math.isnan(v31["size_um"])


def test_a_speck_in_the_same_place_frame_after_frame_is_static():
    """Dust on the window: the AI calls it a droplet in frame after frame at the same pixel. A spray droplet never
    repeats (it moves 10-20 mm between frames)."""
    rng = np.random.default_rng(1)
    shape = (300, 400)
    speck = np.zeros(shape, np.uint8)
    cv2.circle(speck, (200, 150), 2, 1, -1)
    by_img, order = {}, list(range(1, 21))
    for i in order:
        dets = []
        if i % 2:                                              # the AI sees it in every other frame
            s = np.roll(speck, int(rng.integers(-1, 2)), axis=1).astype(bool)
            dets.append(det(i, s))
        for _ in range(40):                                    # spray: never in the same place twice
            m = np.zeros(shape, np.uint8)
            cv2.circle(m, (int(rng.integers(10, 390)), int(rng.integers(10, 290))), 2, 1, -1)
            dets.append(det(i, m.astype(bool)))
        by_img[i] = dets
    n = mr.mark_static(by_img, order)
    flagged = [d for ds in by_img.values() for d in ds if d.get("_static")]
    assert n == len(flagged) == 10                             # every sighting of the speck, nothing else
    assert all(abs(d["bbox"][1] + d["bbox"][3] / 2 - 150) < 2 for d in flagged)
    T = np.ones(shape, np.float32)
    d = flagged[0]
    md = mr.measure_droplet(T, d, 0.70, version="3.1.0", calib=mr.SIZER3,
                            others=mr.occupancy(T.shape, [d], liquid_map.hysteresis(T)[0]))
    assert md["method"] == "static" and not md["in_volume"] and md["weight"] == 0.0
    md30 = mr.measure_droplet(T, d, 0.70, version="3.0.0", calib=mr.SIZER3, others=mr.occupancy(T.shape, [d]))
    assert md30["method"] != "static"                          # 3.0.0 is untouched


def test_the_unmeasured_count_in_the_concentration_and_static_does_not():
    rows = [{"droplets_in_volume": 8, "droplets_outside": 2, "droplets_no_chi": 0, "droplets_crowded": 1,
             "droplets_attached": 2, "droplets_dark_surround": 1, "droplets_inconsistent": 1, "droplets_static": 7}]
    c = mr.concentration(rows, [(8.0, 3.0, 5.0)], (100, 100), {"depth_mm": 10.0}, n_frames=4)
    assert c["crowded"] == 5                                   # 1 crowded + 2 attached + 1 dark + 1 inconsistent
    assert c["crowded_factor"] == pytest.approx(1 + 0.8 * 5 / 8)
    assert c["frames"] == 4                                    # every frame, not only those with a detection
    assert c["in_volume_per_mm3"] == pytest.approx(round(8.0 * (1 + 0.8 * 5 / 8) / (4 * 1.0 * 10.0), 6))


# ---- end to end: measure_run and the liquid stage at --sizer 3.1.0 ---------------------------------------------

@pytest.fixture(scope="module")
def run31(tmp_path_factory):
    """Six frames: the CASES droplets, a droplet sitting on an undetected ligament, and a speck in the same place in
    every frame."""
    mr_ = spec.rdc_module("measure_run")
    root = tmp_path_factory.mktemp("sizer31")
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
    for i in range(6):
        stem = f"frame_{i:04d}_n{i * 10 - 1}"
        T = np.ones((180, 480), np.float32)
        free = [render(T, 60.0, 12.5, 60.0 + 6 * i, 60.0), render(T, 100.0, 12.5, 400.0 - 6 * i, 60.0)]
        on_lig = render(T, 40.0, 12.5, 198.0, 40.0 + 20 * i)           # rides down the ligament's edge
        lig = np.zeros(T.shape, bool)
        lig[:, 200:212] = True
        T *= cv2.GaussianBlur(np.where(lig, 0.15, 1.0).astype(np.float32), (0, 0), 1.2)
        speck = render(T, 30.0, 12.5, 300.0, 150.0)                      # dust: the same place every frame
        cv2.imwrite(str(raw / "frames" / "16bit" / f"{stem}.tiff"), (T * BG).astype(np.uint16))
        cv2.imwrite(str(raw / "frames" / "8bit" / f"{stem}.png"), (T * 255).astype(np.uint8))
        images.append({"id": i + 1, "file_name": f"{stem}.png", "width": 480, "height": 180})
        preds += [det(i + 1, m) for m in free] + [det(i + 1, on_lig), det(i + 1, speck)]
    (raw / "instances.json").write_text(json.dumps({"images": images}))
    (run / "shadowgraph" / "analysis" / "predictions.json").write_text(json.dumps(preds))
    env = dict(os.environ, HPATR_OPTICS_DIR=str(prof))
    env.pop("HPATR_OPTICS_PROFILE", None)
    meas = run / "shadowgraph" / "analysis" / "droplets_0.30"
    cmd = [sys.executable, "-W", "ignore", mr_.__file__, "--pred",
           str(run / "shadowgraph" / "analysis" / "predictions.json"), "--root", str(run),
           "--val-dir", "shadowgraph/raw", "--background", str(raw / "background_median.tiff"),
           "--sixteen-bit-dir", str(raw / "frames" / "16bit"), "--score-thresh", "0.30",
           "--out-dir", str(meas), "--n-boot", "20", "--sizer", "3.1.0"]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return {"run": run, "meas": meas, "env": env, "stdout": p.stdout}


def test_a_3_1_0_run_records_each_verdict_and_where_each_droplet_was(run31):
    with open(run31["meas"] / "droplet_sizes.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert {"x", "y", "mask_d_um"} <= set(rows[0])
    def where(r):
        x, y = float(r["x"]), float(r["y"])
        return "speck" if abs(x - 300) < 2 and abs(y - 150) < 2 else "ligament" if abs(x - 198) < 2 else "free"
    got = {}
    for r in rows:
        got.setdefault(where(r), set()).add(r["size_method"])
    assert got == {"speck": {"static"}, "ligament": {"attached"}, "free": {"direct"}}
    s = json.loads((run31["meas"] / "summary.json").read_text())
    assert s["provenance"]["sizer_version"] == "3.1.0"
    assert s["droplets_static"] == 6 and s["droplets_attached"] == 6
    assert s["concentration"]["frames"] == 6
    assert "sizer 3.1.0" in run31["stdout"]


@pytest.fixture(scope="module")
def liq31(run31):
    out = run31["run"] / "shadowgraph" / "analysis" / "liquid_0.30"
    p = subprocess.run([sys.executable, "-W", "ignore", str(spec.paths.RDC_DIR / "classical_liquid.py"), "--root",
                        str(run31["run"]), "--out-dir", str(out), "--score-thresh", "0.30", "--sizer", "3.1.0"],
                       capture_output=True, text=True, env=run31["env"])
    assert p.returncode == 0, p.stderr[-2000:]
    return {"out": out, "stdout": p.stdout}


def test_the_liquid_stage_leaves_the_static_speck_out_at_3_1_0(run31, liq31):
    out = liq31["out"]
    assert "6 static droplet detections left out" in liq31["stdout"]
    cs = json.loads((out / "classical_summary.json").read_text())
    assert cs["provenance"]["sizer_version"] == "3.1.0"
    assert cs["atomised_pct_in_volume_pooled"] is not None


# ---- the rolling background (Phase 2) --------------------------------------------------------------------------

bgmod = spec.rdc_module("background")


def write_sequence(d, n=60, land=30, shape=(64, 96), seed=0):
    """n frames of a flat 800-count background with a transient droplet in each (spray) and, from frame `land`, a
    dark drop sitting on the window at (70, 30)."""
    rng = np.random.default_rng(seed)
    d.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    for i in range(n):
        f = np.full(shape, 800.0)
        cx, cy = rng.integers(5, shape[1] - 5), rng.integers(5, shape[0] - 5)
        f[(xx - cx) ** 2 + (yy - cy) ** 2 <= 9] = 200.0
        if i >= land:
            f *= 1.0 - 0.6 * np.exp(-((xx - 70) ** 2 + (yy - 30) ** 2) / (2 * 6.0 ** 2))
        cv2.imwrite(str(d / f"frame_{i:04d}_n{i * 10 - 1}.tiff"), f.astype(np.uint16))


def test_the_rolling_background_takes_in_a_drop_that_lands_mid_run(tmp_path):
    write_sequence(tmp_path / "16bit")
    idx = bgmod.build_rolling(tmp_path / "16bit", tmp_path / "roll", log=lambda s: None)
    assert idx["block"] == 25 and len(idx["blocks"]) == 3 and idx["n_frames"] == 60
    r = bgmod.Rolling(tmp_path / "roll")
    early, late = r.for_stem("frame_0005_n49"), r.for_stem("frame_0055_n549")
    assert early[30, 70] == pytest.approx(800, abs=2)              # before it landed: clear
    assert late[30, 70] == pytest.approx(800 * 0.4, abs=4)         # after: the drop is in the background ...
    raw = cv2.imread(str(tmp_path / "16bit" / "frame_0055_n549.tiff"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    assert (raw / late)[30, 70] == pytest.approx(1.0, abs=0.02)   # ... so it divides out
    assert late[10, 10] == pytest.approx(800, abs=2)               # the moving droplets median away
    landed = [e for e in idx["window_events"] if e["kind"] == "landed"]
    assert len(idx["window_drops"]) == 1 and idx["window_drops"][0]["first_frame"] in ("frame_0025_n249", "frame_0050_n499")
    assert landed and abs(landed[0]["x"] - 70) <= 3 and abs(landed[0]["y"] - 30) <= 3
    # the same frames: reused; other frames: rebuilt
    assert bgmod.ensure_rolling(tmp_path / "16bit", tmp_path / "roll", log=lambda s: None).index == idx
    (tmp_path / "16bit" / "frame_0059_n589.tiff").unlink()
    assert bgmod.ensure_rolling(tmp_path / "16bit", tmp_path / "roll", log=lambda s: None).index["n_frames"] == 59


def test_a_droplet_beside_a_drop_on_the_window_is_measured_with_the_rolling_background(tmp_path):
    """A run where a drop lands on the window at frame 25 and a droplet keeps passing beside its shadow: with the
    whole-run background the shadow stays in every later frame and the droplet cannot be measured; with the rolling
    background it is divided out and the droplet is sized."""
    prof = tmp_path / "optics"
    prof.mkdir()
    (prof / "test_lens.json").write_text(json.dumps({"name": "test_lens", "valid_from": "2000-01-01",
                                                     "um_per_px": 10.0, "calibration": CAL}))
    run = tmp_path / "130000_9000sccm_500rpm_4000sps_or1.2_bh0.5"
    raw = run / "shadowgraph" / "raw"
    for d in (raw / "frames" / "16bit", raw / "frames" / "8bit", run / "shadowgraph" / "analysis"):
        d.mkdir(parents=True, exist_ok=True)
    (raw / "extraction_metadata.json").write_text(json.dumps({"stride": 10, "frame_count": 50}))
    cv2.imwrite(str(raw / "background_median.tiff"), np.full((120, 240), BG, np.uint16))
    yy, xx = np.mgrid[0:120, 0:240]
    shadow = (1.0 - 0.6 * np.exp(-((xx - 150) ** 2 + (yy - 60) ** 2) / (2 * 18.0 ** 2))).astype(np.float32)
    images, preds = [], []
    for i in range(50):
        stem = f"frame_{i:04d}_n{i * 10 - 1}"
        T = np.ones((120, 240), np.float32)
        th = 2 * np.pi * ((i * 17) % 50) / 50                           # beside the shadow, never twice in a place
        m = render(T, 60.0, 12.5, 150.0 + 26.0 * np.cos(th), 60.0 + 26.0 * np.sin(th))
        if i >= 25:
            T *= shadow
        cv2.imwrite(str(raw / "frames" / "16bit" / f"{stem}.tiff"), (T * BG).astype(np.uint16))
        cv2.imwrite(str(raw / "frames" / "8bit" / f"{stem}.png"), (T * 255).astype(np.uint8))
        images.append({"id": i + 1, "file_name": f"{stem}.png", "width": 240, "height": 120})
        preds.append(det(i + 1, m))
    (raw / "instances.json").write_text(json.dumps({"images": images}))
    (run / "shadowgraph" / "analysis" / "predictions.json").write_text(json.dumps(preds))
    env = dict(os.environ, HPATR_OPTICS_DIR=str(prof))
    env.pop("HPATR_OPTICS_PROFILE", None)

    def go(rolling, out):
        cmd = [sys.executable, "-W", "ignore", mr.__file__, "--pred", str(run / "shadowgraph/analysis/predictions.json"),
               "--root", str(run), "--val-dir", "shadowgraph/raw", "--background", str(raw / "background_median.tiff"),
               "--score-thresh", "0.30", "--out-dir", str(out), "--n-boot", "10", "--sizer", "3.1.0",
               "--background-rolling", rolling]
        p = subprocess.run(cmd, capture_output=True, text=True, env=env)
        assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
        with open(out / "droplet_sizes.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        return rows, json.loads((out / "summary.json").read_text())

    late = lambda rows: [r["size_method"] for r in rows if int(r["frame"][6:10]) >= 30]
    static_rows, s_static = go("none", tmp_path / "static")
    roll_rows, s_roll = go("auto", tmp_path / "rolling")
    assert s_static["provenance"]["background_kind"] == "static"
    assert s_roll["provenance"]["background_kind"] == "rolling"
    assert (run / "shadowgraph" / "analysis" / "background_rolling" / "index.json").exists()
    assert s_roll["provenance"]["window_events_landed"] >= 1
    assert not any(m == "direct" for m in late(static_rows))             # the shadow spoils every later frame
    assert sum(m == "direct" for m in late(roll_rows)) >= 15             # divided out: sized again
    assert not any(r["size_method"] == "static" for r in roll_rows)      # it moved: not dust



# ---- throughput (Phase 3) ---------------------------------------------------------------------------------------

rates = spec.rdc_module("rates")


def test_the_throughput_arithmetic():
    """Q x share of the liquid for the flow; Q x in-band droplets per mm3 of liquid for the rate; and the two agree
    through the mean in-band droplet's volume."""
    assert rates.syringe_mm3_s(6800) == pytest.approx(math.pi * (20.27 / 2) ** 2)
    assert rates.liquid_ml_min(6800) == pytest.approx(rates.syringe_mm3_s(6800) * 0.06)
    wb, v3 = rates.band_parts(["a", "b"], {"a": [40.0, 20.0, 70.0], "b": [40.0]}, {"a": [1.0, 1.0, 1.0], "b": [2.0]})
    assert list(wb) == [1.0, 2.0] and list(v3) == [40.0 ** 3, 2 * 40.0 ** 3]       # 20 and 70 um are out of 30-60
    t = rates.throughput(100.0, wb, v3, [2.0, 2.0])
    vol40 = math.pi / 6 * 40.0 ** 3 * 1e-9
    assert t["band_rate_per_s"] == pytest.approx(100.0 * 3 / 4, rel=1e-3)
    assert t["band_share_pct"] == pytest.approx(100 * 3 * vol40 / 4, rel=1e-3)
    assert t["band_flow_ml_min"] == pytest.approx(t["band_rate_per_s"] * vol40 * 0.06, rel=1e-3)
    assert t["band_mean_d3_um"] == pytest.approx(40.0)
    t2 = rates.throughput(100.0, wb, v3, [2.0, 2.0], crowded_factor=1.2)
    assert t2["band_rate_per_s"] == pytest.approx(1.2 * t["band_rate_per_s"], rel=1e-3)   # crowded added back
    tb = rates.throughput(100.0, np.ones(40), np.full(40, 40.0 ** 3), np.full(40, 2.0), n_boot=200)
    lo, hi = tb["band_rate_per_s_ci95"]
    assert lo <= tb["band_rate_per_s"] <= hi


def test_the_liquid_stage_writes_the_liquid_inside_the_volume(run31, liq31):
    """Each piece by its best size: the sized droplets' volume must be what their calibrated sizes give."""
    with open(liq31["out"] / "classical_per_frame.csv", newline="") as f:
        cpf = {r["frame"]: r for r in csv.DictReader(f)}
    with open(run31["meas"] / "droplet_sizes.csv", newline="") as f:
        sized = [r for r in csv.DictReader(f) if r["in_focus"] == "1"]
    for fr, r in cpf.items():
        mine = [float(x["diameter_um"]) for x in sized if x["frame"] == fr]
        assert float(r["vol_sized_in_volume_mm3"]) == pytest.approx(math.pi / 6 * sum(d ** 3 for d in mine) * 1e-9,
                                                                     rel=1e-3)
        parts = sum(float(r[k]) for k in ("vol_sized_in_volume_mm3", "vol_below_d_min_in_volume_mm3",
                                          "vol_unmeasured_in_volume_mm3", "vol_unatomised_in_volume_mm3"))
        assert float(r["vol_liquid_in_volume_mm3"]) == pytest.approx(parts, rel=1e-6)
        assert float(r["vol_unmeasured_in_volume_mm3"]) > 0          # the droplet sitting on the ligament
    cs = json.loads((liq31["out"] / "classical_summary.json").read_text())
    assert 0.3 < cs["unmeasured_size_factor"] < 1.2
    assert cs["liquid_in_volume_mm3"] > cs["droplets_in_volume_mm3"] > 0


def test_the_app_and_the_capture_gui_get_the_same_throughput(run31, liq31):
    """GUI_Clean (master_log) reads rates.from_run_files; the app reads its run record through the same function."""
    steps = 4000.0
    gui = rates.from_run_files(run31["meas"], liq31["out"], steps, band=(30.0, 60.0), n_boot=50)
    assert gui["band_rate_per_s"] > 0 and gui["band_flow_ml_min"] > 0
    assert gui["band_flow_ml_min"] == pytest.approx(
        gui["band_rate_per_s"] * math.pi / 6 * gui["band_mean_d3_um"] ** 3 * 1e-9 * 0.06, rel=1e-3)
    ta = spec.rdc_module("taguchi_analysis")
    rm = __import__("src.ai.Taguchi_Analysis_UI.run_metrics", fromlist=["x"])
    rec = ta.load_run(run31["run"], "0.30")
    v = rm.response_values({"throughput": {"liquid_ml_min": rates.liquid_ml_min(steps)}}, rec, n_boot=50,
                           band=(30.0, 60.0))
    assert v["rate_band"] == pytest.approx(gui["band_rate_per_s"], rel=1e-3)
    assert v["band_flow"] == pytest.approx(gui["band_flow_ml_min"], rel=1e-3)
    assert v["rate"] >= v["rate_band"] and len(v["boot_band_flow"]) == 50


# ---- outputs (Phase 4) ------------------------------------------------------------------------------------------

def test_a_3_1_0_frame_is_drawn_by_verdict_with_a_key(tmp_path):
    T, masks = frame()
    dets = [det(1, m) for m in masks]
    fr = mr.measure_frame(T, dets, 0.70, keep_drawn=True, version="3.1.0")
    assert all(len(it) == 8 for it in fr["drawn"])                      # the verdict rides with each item
    view = tmp_path / "v.png"
    cv2.imwrite(str(view), (T * 255).astype(np.uint8))
    mr.render_frame(view, fr["drawn"], fr["d32"], fr["atom"], 3, tmp_path / "out.png")
    out = cv2.imread(str(tmp_path / "out.png"))
    H = out.shape[0]
    assert (out[H - 40:H, :60] > 200).all(axis=2).mean() > 0.3          # the key's pale plate, bottom-left
    f30 = mr.measure_frame(T, dets, 0.70, keep_drawn=True, version="3.0.0")
    assert all(len(it) == 7 for it in mr.measure_frame(T, dets, 0.70, keep_drawn=True, version="2.2.0")["drawn"])
    assert all(len(it) == 8 for it in f30["drawn"])                      # 3.0.0 runs are drawn by verdict too


def test_a_3_1_0_run_writes_its_largest_droplets_sheet(run31):
    sheet = run31["meas"] / "largest_droplets.png"
    idx = json.loads((run31["meas"] / "largest_droplets.json").read_text())
    assert sheet.exists() and idx["n"] >= 1
    sizes = [e["size_um"] for e in idx["droplets"]]
    assert sizes == sorted(sizes, reverse=True)
    assert all(e["method"] in ("direct", "table", "table_extrapolated") for e in idx["droplets"])
    assert not any(abs(e["x"] - 198) < 2 for e in idx["droplets"])       # the attached one is never in it


def test_the_report_warns_of_window_drops_and_a_d32_resting_on_big_droplets(tmp_path):
    st = __import__("src.ai.Taguchi_Analysis_UI.stats", fromlist=["x"])
    (tmp_path / "summary.json").write_text(json.dumps({
        "provenance": {"sizer_version": "3.1.0", "window_drops_first_frames": ["frame_0250_n2499"]},
        "droplets_in_focus": 100, "droplets_attached": 30, "droplets_dark_surround": 0, "droplets_inconsistent": 0}))
    rec = {"meas_dir": str(tmp_path), "dia": {"a": [50.0] * 50 + [300.0]}}
    w = st.sizer31_warnings("R", rec)
    assert any("landed on the camera window" in x and "frame_0250" in x for x in w)
    assert any("largest calibration bead" in x for x in w)
    assert any("could not be measured" in x for x in w)
    (tmp_path / "summary.json").write_text(json.dumps({"provenance": {"sizer_version": "3.0.0"}}))
    assert st.sizer31_warnings("R", rec) == []
