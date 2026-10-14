"""bead_calibration.py (2026-10-14): size calibration from glass beads of certified size, later the reticle.
Synthetic beads follow Blaisot & Yon's model -- a disc of transmission tau convolved with a Gaussian PSF
exp(-2 r^2 / chi^2), optionally with a bright centre (a transparent sphere) -- on a smooth, uneven backlight,
written as GUI_Clean-like run folders (run_summary.xlsx Notes + 16-bit frames). The checks: the model,
the measurements against what was built in, the background, identity on a mixed slide, the through-focus
summary (acceptance depth, chi(z)), and the end-to-end files."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np
import openpyxl
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

bc = spec.rdc_module("bead_calibration")

H, W, UP = 240, 320, 8
BG = 30000.0
SIZES = [37.36, 56.28, 76.39, 98.1, 155.8]


def backlight(h=H, w=W):
    yy, xx = np.mgrid[0:h, 0:w]
    return BG * (1 + 0.15 * (xx / w) - 0.10 * (yy / h))                  # uneven, as a real backlight


def bead_T(T, cx, cy, d_um, chi_um, tau=0.05, bright=0.0):
    """Multiply one bead into T (frame pixels at 10 um/px), modelled on an 8x grid then binned."""
    half = int(d_um / 10 / 2 + 3 * max(chi_um, 5) / 10 + 4)
    x0, y0 = int(cx) - half, int(cy) - half
    n = 2 * half + 1
    yy, xx = np.mgrid[0:n * UP, 0:n * UP]
    r = d_um / 10 * UP / 2
    ccx, ccy = (cx - x0 + 0.5) * UP, (cy - y0 + 0.5) * UP
    rr2 = (xx - ccx) ** 2 + (yy - ccy) ** 2
    disc = (rr2 <= r * r).astype(np.float64)
    t = 1 - (1 - tau) * disc
    if bright:
        t += bright * np.exp(-rr2 / (2 * (r / 3) ** 2)) * disc
    sigma = chi_um / 10 * UP / 2
    if sigma > 0.3:
        t = cv2.GaussianBlur(t, (0, 0), sigma)
    T[y0:y0 + n, x0:x0 + n] *= cv2.resize(t, (n, n), interpolation=cv2.INTER_AREA)


def write_run(day: Path, name: str, notes: str, T: np.ndarray, frames=3, seed=0):
    run = day / name
    fr = run / "shadowgraph" / "raw" / "frames" / "16bit"
    fr.mkdir(parents=True)
    rng = np.random.default_rng(seed)
    img = backlight() * T
    for k in range(frames):
        cv2.imwrite(str(fr / f"frame_{k:04d}_n{k}.tiff"), np.clip(img + rng.normal(0, 60, img.shape), 0, 65535)
                    .astype(np.uint16))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Metadata"
    ws.append(["Field", "Value"])
    ws.append(["Notes", notes])
    wb.save(run / "run_summary.xlsx")
    return run


GRID = [(60, 60), (160, 60), (260, 60), (60, 170), (160, 170), (260, 170)]
MIX = [155.8, 76.39, 98.1, 56.28, 155.8, 98.1]          # six beads, four sizes, on the mixed slide


def chi_of(z):
    return 12.0 + 40.0 * abs(z - 0.1)                     # chi0 12 um, k 40 um/mm, best focus at z = +0.1 mm


@pytest.fixture(scope="module")
def day(tmp_path_factory):
    d = tmp_path_factory.mktemp("beads") / "2026" / "10" / "15"
    zs = [-2.0, -1.0, -0.5, -0.2, 0.0, 0.2, 0.5, 1.0, 2.0]
    for k, z in enumerate(zs):
        T = np.ones((H, W))
        for (x, y), s in zip(GRID, MIX):
            bead_T(T, x, y, s, chi_of(z))
        bead_T(T, 110, 115, 40.0, 8.0)                     # the same speck: dust, not a bead
        write_run(d, f"10{k:02d}00_0sccm_mix", f"BEAD mix z{z:+.2f}", T, seed=k)
    T = np.ones((H, W))
    for (x, y), s in zip(GRID, [98.1] * 6):
        bead_T(T, x, y, s, 10.0, bright=0.8)               # transparent: a bright centre (at 56 um, blur hides it)
    write_run(d, "110000_0sccm_s98", "BEAD 98.1 z0 p1", T, seed=20)
    T = np.ones((H, W))
    bead_T(T, 110, 115, 40.0, 8.0)                         # a speck on the window: in the bead-free capture too
    write_run(d, "110100_0sccm_bg", "BEAD 98.1 bg", T, seed=21)
    for k, base in ((1, 50.0), (2, 54.0)):                  # two pours of one size, as on the day
        fall = write_run(d, f"11020{k}_0sccm_fall", f"BEAD fall 56.28 p{k}", np.ones((H, W)), seed=21 + k)
        m = fall / "shadowgraph" / "analysis" / "droplets_0.30"
        m.mkdir(parents=True)
        with open(m / "droplet_sizes.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["frame", "diameter_um", "in_focus"])
            w.writerows([["f", base + j % 5, 1] for j in range(20)] + [["f", 80.0, 0]] * 5)
    write_run(d, "110300_9000sccm_spray", "S2 #01 anchor centre", np.ones((H, W)), seed=23)   # not a capture
    return d


def test_notes_are_parsed_as_the_run_sheet_writes_them():
    assert bc.parse_notes("BEAD mix z-1.25") == ("bead", "mix", "z", -1.25, "")
    assert bc.parse_notes("BEAD mix z+0.00") == ("bead", "mix", "z", 0.0, "")
    assert bc.parse_notes("BEAD mix z0 p3") == ("bead", "mix", "focus", 0.0, "p3")
    assert bc.parse_notes("BEAD 56.28 bg") == ("bead", "56.28", "bg", None, "")
    assert bc.parse_notes("BEAD fall 155.8") == ("bead", "155.8", "fall", None, "")
    assert bc.parse_notes("BEAD fall 155.8 p2")[:3] == ("bead", "155.8", "fall")
    assert bc.parse_notes("RETICLE array tl") == ("reticle", "reticle", "array", None, "tl")
    assert bc.parse_notes("RETICLE z+0.40")[2:4] == ("z", 0.4)
    assert bc.parse_notes("S2 #01 anchor centre") is None and bc.parse_notes(None) is None


def test_the_model_reduces_to_a_sharp_disc_and_widens_with_blur():
    assert bc.p_level(0.5, 0.999) == pytest.approx(1.0, abs=0.05)              # sharp: half-max is the edge
    assert bc.p_width(0.999) > bc.p_width(0.3) > 0
    assert bc.c0_from(1 / 3, 0.5) == pytest.approx(1.0, abs=0.002)            # Eq. 8: C_max = (1-tau)/(1+tau)


@pytest.mark.parametrize("d,chi", [(155.8, 30.0), (155.8, 60.0), (76.39, 20.0), (98.1, 15.0)])
def test_a_bead_is_measured_as_built(d, chi):
    T = np.ones((H, W))
    bead_T(T, 160, 120, d, chi)
    r = bc.measure_at(T.astype(np.float32), 160, 120, d / 10, tau=0.05)
    assert r["detected"] and r["in_focus_current"] and not r["ring"]
    assert r["chi_um"] == pytest.approx(chi, rel=0.15)
    assert r["d_blaisot_um"] == pytest.approx(d, rel=0.04)                     # contrast-corrected
    assert r["d_l0.50"] < d * 1.01                                             # half-max reads small as blur grows


def test_a_bright_centre_is_a_ring_and_filling_restores_the_size():
    T = np.ones((H, W))
    bead_T(T, 160, 120, 98.1, 14.0, bright=0.8)
    r = bc.measure_at(T.astype(np.float32), 160, 120, 9.8, tau=0.05)
    assert r["ring"] and r["centre_t"] > r["core_t"] + 0.2
    assert r["d_l0.50"] == pytest.approx(98.1, rel=0.05)                       # filled
    assert r["draw_l0.50"] < r["d_l0.50"]                                      # as a ring: low


def test_the_background_comes_from_the_frame_itself():
    T = np.ones((H, W))
    for (x, y), s in zip(GRID, MIX):
        bead_T(T, x, y, s, 15.0)
    img = (backlight() * T).astype(np.float32)
    bg = bc.estimate_background(img)
    far = np.ones((H, W), bool)
    for x, y in GRID:
        far[max(0, y - 25):y + 25, max(0, x - 25):x + 25] = False
    far[:8], far[-8:], far[:, :8], far[:, -8:] = False, False, False, False
    assert np.abs(bg[far] / backlight()[far] - 1).max() < 0.01


def test_a_mixed_slide_is_sorted_by_size_even_with_a_common_bias():
    measured = [0.8 * s for s in SIZES] + [0.8 * 66.0]                        # 66 sits between 56.28 and 76.39
    ids, k = bc.assign_sizes(measured, SIZES)
    assert k == pytest.approx(0.8, abs=0.02)
    assert ids[:5] == SIZES and ids[5] is None


def test_the_day_end_to_end(day, tmp_path):
    out = tmp_path / "analysis"
    R = bc.analyse([day], out, None, max_frames=3)
    assert R["captures"] == 13                                                 # 9 + focus + bg + 2 pours
    tf = R["through_focus"]["mix"]
    assert tf["info"]["n_beads"] == 6
    big = tf["155.8"]
    fit = big["chi_fit"]
    assert fit["k_um_per_mm"] == pytest.approx(40.0, rel=0.25) and fit["zf_mm"] == pytest.approx(0.1, abs=0.15)
    assert fit["chi0_um"] == pytest.approx(12.0, abs=6.0)
    assert big["dof_effective_mm"] > 0 and 0 < big["dof_50pct_mm"] <= 4.0
    assert set(R["at_focus"]) >= {"155.8", "98.1", "76.39", "56.28"}
    s98 = R["at_focus"]["98.1"]
    assert s98["n_beads"] == 8 and s98["ring_share"] >= 0.7                    # 6 transparent + 2 from the mix
    assert R["dust_spots"] == 1                                               # the speck, excluded everywhere
    assert R["falling"][0]["n_in_focus"] == 20 and R["falling"][0]["certified_um"] == 56.28
    pooled = R["falling"][-1]
    assert pooled["run"] == "all 2 pours" and pooled["n_in_focus"] == 40 and pooled["n_detected"] == 50
    assert pooled["d_in_focus_median_um"] == 54.0                              # 50-54 and 54-58: 54 twice as often
    for name in ("optics_calibration_v1.json", "report.md", "beads_at_focus.csv", "beads_through_focus.csv",
                 "fig_at_focus.png", "fig_through_focus.png"):
        assert (out / name).is_file(), name
    saved = json.loads((out / "optics_calibration_v1.json").read_text())
    assert saved["at_focus"]["155.8"]["n_beads"] >= 2 and "## At best focus" in (out / "report.md").read_text()
    assert not any(p.name == "analysis" for p in day.rglob("*") if p.is_dir() and p.parent == day)  # nothing written there


def test_nothing_is_written_into_the_capture_folders(day, tmp_path):
    before = {p: p.stat().st_mtime_ns for p in day.rglob("*") if p.is_file()}
    bc.analyse([day], tmp_path / "a2", None, max_frames=2)
    after = {p: p.stat().st_mtime_ns for p in day.rglob("*") if p.is_file()}
    assert before == after
