"""focus_edge.py (sizer 3.0.0 plan, Phase 1, 2026-10-16): the focus meter. Synthetic targets made with the same
optics model as the beads (a disc or an edge, Blaisot's Gaussian blur exp(-2 r^2/chi^2), 10 um pixels by area,
noise): the meter must give back the blur width and the size that were put in."""
from __future__ import annotations

import cv2
import numpy as np
import openpyxl
import pytest

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

fe = spec.rdc_module("focus_edge")
UP = 8


def _target(kind: str, chi_um: float, size=(160, 200), d_um=300.0, noise=0.0, seed=0, inside=1.0, outside=0.05,
            centre=(97.3, 81.6)):
    """kind 'disc': a disc of level `inside` on `outside`; 'line': a straight edge at 30 degrees."""
    h, w = size
    yy, xx = np.mgrid[0:h * UP, 0:w * UP]
    xs, ys = (xx + 0.5) / UP - 0.5, (yy + 0.5) / UP - 0.5
    if kind == "disc":
        m = ((xs - centre[0]) ** 2 + (ys - centre[1]) ** 2 <= (d_um / 10 / 2) ** 2)
    else:
        m = (xs - 100) * np.cos(np.radians(30)) + (ys - 80) * np.sin(np.radians(30)) < 0
    img = np.where(m, inside, outside).astype(np.float32)
    img = cv2.GaussianBlur(img, (0, 0), chi_um / 2 / 10 * UP)
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    if noise:
        img = img + np.random.default_rng(seed).normal(0, noise, img.shape).astype(np.float32)
    return img


@pytest.mark.parametrize("chi", [12.0, 13.0, 20.0, 40.0])
def test_a_pinhole_gives_back_its_blur_and_its_diameter(chi):
    r = fe.disc_edge(_target("disc", chi, noise=0.01), 10.0, certified_um=300.0)
    assert r["ok"] and r["polarity"] == "bright" and r["shape"] == "disc"
    assert r["chi_um"] == pytest.approx(chi, rel=0.06)
    assert r["diameter_um"] == pytest.approx(300.0, abs=1.5) and abs(r["scale_error_pct"]) < 0.5
    assert r["cx"] == pytest.approx(97.3, abs=0.1) and r["cy"] == pytest.approx(81.6, abs=0.1)


def test_a_dark_dot_on_a_bright_field_works_the_same():
    r = fe.disc_edge(_target("disc", 15.0, inside=0.1, outside=1.0, noise=0.02, d_um=200.0), 10.0)
    assert r["ok"] and r["polarity"] == "dark"
    assert r["chi_um"] == pytest.approx(15.0, rel=0.08) and r["diameter_um"] == pytest.approx(200.0, abs=2.0)


def test_an_8_bit_live_frame_is_fine():
    img = np.clip(_target("disc", 13.0, noise=0.01) * 230, 0, 255).astype(np.uint8)
    r = fe.disc_edge(img, 10.0, certified_um=300.0)
    assert r["ok"] and r["chi_um"] == pytest.approx(13.0, rel=0.10)


@pytest.mark.parametrize("chi", [13.0, 30.0])
def test_a_straight_edge_gives_back_its_blur(chi):
    r = fe.line_edge(_target("line", chi, noise=0.01), 10.0)
    assert r["ok"] and r["chi_um"] == pytest.approx(chi, rel=0.08)


def test_no_target_is_said_plainly():
    with pytest.raises(fe.FocusError, match="flat"):
        fe.disc_edge(np.full((80, 80), 100.0), 10.0)
    edge_cut = _target("disc", 13.0, centre=(5.0, 80.0))              # the disc runs off the frame
    with pytest.raises(fe.FocusError, match="no whole disc"):
        fe.disc_edge(edge_cut, 10.0)


def test_what_the_numbers_mean():
    assert fe.z_off_mm(21.0, 13.0) == pytest.approx(1.0)              # ~8 um of blur per mm (the beads)
    assert fe.z_off_mm(12.5, 13.0) == 0.0
    assert fe.in_focus(14.9, 13.0) and not fe.in_focus(15.1, 13.0)
    m = fe.rotation_midpoint(12.30, 12.39)
    assert m == {"axis_rail_mm": 12.345, "difference_mm": 0.09, "ok": True}
    assert not fe.rotation_midpoint(12.0, 12.5)["ok"]
    text = fe.summary_text({"when": "2026-10-20 09:12", "chi_um": 13.2, "diameter_um": 300.4, "axis_rail_mm": 12.345,
                            "difference_mm": 0.09})
    assert text == "2026-10-20 09:12, chi 13.2 um, target 300.4 um, axis at rail 12.345 mm (0/180 differ 0.09 mm)"


def test_a_focus_check_capture_is_found_by_its_notes_and_measured(tmp_path):
    run = tmp_path / "2026" / "10" / "20" / "091200_0sccm_focus"
    fr = run / "shadowgraph" / "raw" / "frames" / "16bit"
    fr.mkdir(parents=True)
    for k in range(3):
        img = _target("disc", 14.0, noise=0.02, seed=k) * 3000 + 100
        cv2.imwrite(str(fr / f"frame_{k:04d}.tiff"), img.astype(np.uint16))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Metadata"
    ws.append(["Field", "Value"])
    ws.append(["Notes", "FOCUS CHECK pinhole start of day"])
    wb.save(run / "run_summary.xlsx")
    assert fe.focus_runs([tmp_path]) == [run]
    r = fe.analyse_capture(run, 300.0, max_frames=3)
    assert r["ok"] and r["chi_um"] == pytest.approx(14.0, rel=0.08) and r["optics_profile"] == "lens1_2026-10"
    assert r["diameter_um"] == pytest.approx(300.0, abs=2.0)


@pytest.mark.parametrize("pinhole", [True, False])
def test_a_small_target_in_a_whole_live_frame_is_found(pinhole):
    """The pinhole is ~0.03 % of a 2048 x 1152 frame: found by standing out from the median, not by percentiles."""
    inside, outside = (1.0, 0.05) if pinhole else (0.1, 1.0)
    img = np.zeros((1152, 2048), np.float32) + outside
    img[500:660, 900:1100] = _target("disc", 13.0, size=(160, 200), inside=inside, outside=outside)
    img = np.clip(img * 230 + np.random.default_rng(0).normal(0, 3, img.shape), 0, 255).astype(np.uint8)
    r = fe.disc_edge(img, 10.0, 300.0)
    assert r["ok"] and r["polarity"] == ("bright" if pinhole else "dark")
    assert r["chi_um"] == pytest.approx(13.0, rel=0.06) and r["diameter_um"] == pytest.approx(300.0, abs=1.5)
    assert r["cx"] == pytest.approx(900 + 97.3, abs=0.2)
