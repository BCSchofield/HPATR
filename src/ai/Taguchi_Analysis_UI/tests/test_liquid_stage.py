"""Liquid stage 2.3.0 (AI/Real_Data_Code/classical_liquid.py + liquid_volume.py, 2026-10-13): drops on the
window are not liquid, and a secondary volume-based atomised fraction.

Route A, a drop that lands on the glass mid-run, is caught by the window mask (still, compact, flat-topped
persistence); a wobbling stream is not. Route B, a drop present all run, divides out of T, so a model
out-of-focus piece with mean T >= 0.97 is not liquid. Volumes: a disc is a sphere, a strip a cylinder, a
ring a torus, and a droplet cut out of a blob does not hollow the blob."""
from __future__ import annotations

import math
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from pycocotools import mask as mask_util

from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

cl = spec.rdc_module("classical_liquid")
lv = spec.rdc_module("liquid_volume")

H, W = 300, 400


def args(**kw):
    a = SimpleNamespace(seed=cl.SEED_THR, ceiling=cl.CEILING_THR, min_area=cl.MIN_AREA,
                        droplet_cover=cl.DROPLET_COVER, droplet_max_extent=cl.DROPLET_MAX_EXTENT,
                        classical_only=False, sharpness_rule=True, focus_max=0.70, static_t=cl.STATIC_T,
                        window_p=cl.WINDOW_P, volume=False, droplet_ring=10)
    a.__dict__.update(kw)
    return a


# ---- volumes ----------------------------------------------------------------------------------------------

def disc(R, n=400):
    m = np.zeros((n, n), np.uint8)
    cv2.circle(m, (n // 2, n // 2), R, 1, -1)
    return m


@pytest.mark.parametrize("R", [10, 30, 80])
def test_a_disc_is_a_sphere(R):
    assert lv.body_volume_px3(disc(R)) == pytest.approx(4 / 3 * math.pi * R ** 3, rel=0.05)
    assert lv.droplet_volume_px3(disc(R)) == pytest.approx(4 / 3 * math.pi * R ** 3, rel=0.03)


@pytest.mark.parametrize("r", [10, 40])
def test_a_strip_is_a_cylinder(r):
    m = np.zeros((200, 400), np.uint8)
    m[100 - r:100 + r, 50:350] = 1
    assert lv.body_volume_px3(m) == pytest.approx(math.pi * r * r * 300, rel=0.08)


def test_a_ring_is_a_torus_not_a_filled_disc():
    m = np.zeros((500, 500), np.uint8)
    cv2.circle(m, (250, 250), 150, 1, 20)
    assert lv.body_volume_px3(m) == pytest.approx(math.pi * 10 ** 2 * 2 * math.pi * 150, rel=0.10)


def test_a_droplet_cut_out_of_a_blob_does_not_hollow_it():
    blob, hole = disc(60), disc(8)
    cut = blob & ~hole
    with_fill = lv.body_volume_px3(cut, fill=hole)
    assert with_fill == pytest.approx(lv.body_volume_px3(blob), rel=0.05)
    assert lv.body_volume_px3(cut) < 0.6 * with_fill          # without the droplet mask it would


def test_area_part_volume_columns():
    liquid = np.zeros((H, W), bool)
    liquid[100:140, 20:380] = True                             # a 40 px thick ligament (0.4 mm)
    dmask = np.zeros((H, W), bool)
    cv2.circle(dmask.view(np.uint8), (200, 220), 6, 1, -1)
    part, _c, _u = cl.area_part(liquid | dmask, dmask, np.zeros_like(dmask), args(), volume=True)
    assert part["atomised_vol_pct"] < part["atomised_pct"] / 3   # the ligament holds far more liquid
    assert part["total_liquid_vol_mm3"] > part["droplet_vol_mm3"] > 0


# ---- route B: a drop already divided out of the frame ----------------------------------------------------

def det(mask, cat, score=0.9):
    rle = mask_util.encode(np.asfortranarray(mask.astype(np.uint8)))
    rle["counts"] = rle["counts"].decode()
    ys, xs = np.nonzero(mask)
    return {"segmentation": rle, "category_id": cat, "score": score, "image_id": 1,
            "bbox": [float(xs.min()), float(ys.min()), float(np.ptp(xs) + 1), float(np.ptp(ys) + 1)]}


def test_an_out_of_focus_piece_with_nothing_left_is_not_liquid():
    T = np.ones((H, W), np.float32)
    blob = np.zeros((H, W), bool)
    cv2.circle(blob.view(np.uint8), (150, 150), 40, 1, -1)
    filament = cl.DROPLET + 1
    # T ~ 1 inside: the drop is in the background median, so the frame / background has removed it
    T[blob] = 0.995
    _d, oof = cl.model_masks([det(blob, filament)], T, 0.70, args())
    assert not oof.any() and cl.model_masks.last_static == 1
    # real out-of-focus liquid (T 0.75-0.9) still counts
    T[blob] = 0.82
    _d, oof = cl.model_masks([det(blob, filament)], T, 0.70, args())
    assert oof.sum() == blob.sum() and cl.model_masks.last_static == 0
    # the rule can be switched off (2.2.0 behaviour)
    T[blob] = 0.995
    _d, oof = cl.model_masks([det(blob, filament)], T, 0.70, args(static_t=0))
    assert oof.sum() == blob.sum()


# ---- route A: a drop that lands mid-run ------------------------------------------------------------------

def persistence_of(frames):
    p = np.zeros((H, W), np.uint16)
    for f in frames:
        p += f
    return p


def test_a_still_drop_that_landed_halfway_is_masked_and_a_wobbling_stream_is_not():
    rng = np.random.default_rng(0)
    frames = []
    for i in range(100):
        m = np.zeros((H, W), bool)
        if i >= 50:                                            # lands half way, then sits still
            cv2.circle(m.view(np.uint8), (300, 80), 25, 1, -1)
        x = int(100 + rng.normal(0, 12))                       # a stream that wobbles left and right
        m[:, x - 6:x + 6] = True
        frames.append(m)
    mask, found = cl.window_mask(persistence_of(frames), len(frames), args())
    assert len(found) == 1 and found[0][0] < 300 < found[0][0] + found[0][2]
    assert mask[80, 300] and not mask[150, 100]                # the drop, not the stream
    # a short-lived drop (in 10% of frames) is spray, not a window drop
    short = [f.copy() for f in frames]
    for i, f in enumerate(short):
        f[:] = False
        if 40 <= i < 50:
            cv2.circle(f.view(np.uint8), (300, 80), 25, 1, -1)
    assert cl.window_mask(persistence_of(short), len(short), args())[0] is None
    assert cl.window_mask(persistence_of(frames), len(frames), args(window_p=0))[0] is None


def test_the_window_is_taken_out_of_both_measures():
    liquid = np.zeros((H, W), bool)
    liquid[100:140, 50:90] = True                              # a window drop
    liquid[200:210, 20:380] = True                             # real un-atomised liquid
    dmask = np.zeros((H, W), bool)
    dmask[50:56, 200:206] = True
    liquid |= dmask
    win = np.zeros((H, W), bool)
    win[95:145, 45:95] = True
    before, _, _ = cl.area_part(liquid, dmask, np.zeros_like(dmask), args())
    after, _, unatom = cl.area_part(liquid, dmask, np.zeros_like(dmask), args(), exclude=win)
    assert before["total_liquid_px"] - after["total_liquid_px"] == 40 * 40
    assert after["droplet_px"] == before["droplet_px"] and after["atomised_pct"] > before["atomised_pct"]
    assert not unatom[win].any()


def test_measure_frame_is_unchanged_with_the_new_rules_off():
    """2.2.0 behaviour is one switch away: the regression on a real run (C20, 508 frames) was
    bit-identical in classical_per_frame.csv, components and summary."""
    T = np.ones((H, W), np.float32)
    T[100:120, 30:370] = 0.3
    row, comps, fa, oa, unatom = cl.measure_frame(T, [], args(static_t=0, window_p=0))
    assert row["total_liquid_px"] == unatom.sum() > 0 and row["droplet_px"] == 0 and comps
