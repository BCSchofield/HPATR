"""GUI_Clean's pre-run window check (src/gui/window_check.py, 2026-10-13): new dark spots on the window
since a clean reference are found; a dimmer backlight, pixel noise, a faint gradient or a speck are not.
Thresholds were set on the CCD day's background medians: C20's window drop reads 0.15 of the clean
window at its core, the faint differences between spray runs ~0.85."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.gui import window_check as wc

H, W = 576, 1024


def clean(seed=0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W]
    bg = 800 + 60 * np.cos(xx / W * 3) + 40 * np.sin(yy / H * 2)          # an uneven backlight
    return np.clip(bg + rng.normal(0, 18, (H, W)), 0, 4095).astype(np.uint16)


def with_drop(frame, x, y, r, depth):
    out = frame.astype(np.float32)
    m = np.zeros((H, W), np.uint8)
    cv2.circle(m, (x, y), r, 1, -1)
    soft = cv2.GaussianBlur(m.astype(np.float32), (0, 0), r / 3)
    out *= 1 - (1 - depth) * soft / soft.max()
    return out.astype(np.uint16)


def test_a_clean_window_reads_clean_even_with_a_dimmer_backlight_and_new_noise():
    ref = clean(0)
    live = (clean(1).astype(np.float32) * 0.8).astype(np.uint16)          # 20% dimmer, fresh noise
    c = wc.compare(live, ref)
    assert c.ok and not c.spots and c.text() == "clean"


def test_a_drop_is_found_where_it_is():
    ref = clean(0)
    live = with_drop(clean(1), 700, 400, 30, depth=0.3)
    c = wc.compare(live, ref)
    assert not c.ok and len(c.spots) == 1
    x, y, w, h, area, darkest = c.spots[0]
    assert x < 700 < x + w and y < 400 < y + h and darkest < 0.5
    assert c.text().startswith("1 new dark spot,") and "mm2" in c.text()


def test_faint_gradients_and_specks_are_not_drops():
    ref = clean(0)
    faint = with_drop(clean(1), 300, 300, 120, depth=0.88)                 # broad and faint: no dark core
    speck = with_drop(clean(1), 300, 300, 6, depth=0.2)                    # dark but tiny (< MIN_AREA_PX)
    assert wc.compare(faint, ref).ok
    assert wc.compare(speck, ref).ok


def test_rgb_frames_and_a_size_change():
    ref = clean(0)
    live = np.dstack([with_drop(clean(1), 500, 200, 25, 0.4)] * 3)
    assert not wc.compare(live, ref).ok
    c = wc.compare(clean(1)[:, :512], ref)
    assert c.ok and c.skipped.startswith("the reference is 1024x576") and c.text().startswith("skipped:")


def test_the_reference_round_trips_and_the_overlay_is_drawable(tmp_path):
    ref = clean(0)
    assert wc.load_reference(str(tmp_path)) == (None, None)
    path = wc.save_reference(ref, note="exposure 4 us", folder=str(tmp_path))
    back, meta = wc.load_reference(str(tmp_path))
    assert path.endswith(wc.REFERENCE_NAME) and np.array_equal(back, ref) and back.dtype == ref.dtype
    assert meta["note"] == "exposure 4 us" and meta["shape"] == [H, W]
    live = with_drop(clean(1), 700, 400, 30, depth=0.3)
    ov = wc.overlay(live, wc.compare(live, back), max_width=512)
    assert ov.dtype == np.uint8 and ov.shape == (288, 512, 3) and ov.flags["C_CONTIGUOUS"]


@pytest.mark.parametrize("darkest, found", [(0.95, False), (0.85, False), (0.75, True), (0.15, True)])
def test_the_dark_core_rule(darkest, found):
    ref = clean(0)
    live = with_drop(clean(1), 512, 288, 40, depth=darkest)
    assert (not wc.compare(live, ref).ok) == found


def test_every_run_sheet_says_to_wipe_the_window(tmp_path):
    from src.ai.Taguchi_Analysis_UI import rsm_design as rb
    from src.ai.Taguchi_Analysis_UI.tests.test_rsm_design import ben_plan
    sheet = rb.build_sheet(ben_plan())
    assert rb.BEFORE_EVERY_RUN in rb.summary(sheet)
    md = next(p for p in rb.export(sheet, tmp_path) if p.suffix == ".md").read_text(encoding="utf-8")
    assert "wipe or dry the window" in md
