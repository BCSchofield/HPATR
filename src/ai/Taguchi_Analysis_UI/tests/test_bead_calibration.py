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
    assert bc.parse_notes("BEAD 155.8+98.1+76.39 z-1.25") == ("bead", "155.8+98.1+76.39", "z", -1.25, "")


def test_a_big_bead_sandwich_is_matched_against_its_own_sizes_only():
    targets = bc.load_targets(None)
    assert bc._slide_sizes("155.8+98.1+76.39", "bead", targets) == [76.39, 98.1, 155.8]
    assert bc._slide_sizes("155.8+98.1", "bead", targets) == [98.1, 155.8]
    assert bc._slide_sizes("98.1", "bead", targets) == [98.1]
    assert len(bc._slide_sizes("mix", "bead", targets)) == 5
    # a 70 um speck on the two-size slide is no bead; on the five-size one it would pass as a 76.39
    ids, _ = bc.assign_sizes([104.0, 103.0, 162.0, 160.0, 70.0], [98.1, 155.8])
    assert ids == [98.1, 98.1, 155.8, 155.8, None]


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


def test_the_captures_are_untouched_and_each_gets_its_region_png(day, tmp_path):
    """Ben, 2026-10-15: a PNG with the area used boxed goes into each measured capture's own folder. Nothing
    else is written there, and nothing that was there changes."""
    def files():                      # (the day is shared: an earlier test may have written the PNGs already)
        return {p: p.stat().st_mtime_ns for p in day.rglob("*") if p.is_file()}
    before = {p: t for p, t in files().items() if "bead_calibration" not in p.parts}
    bc.analyse([day], tmp_path / "a2", None, max_frames=2)
    after = files()
    assert {p: t for p, t in after.items() if "bead_calibration" not in p.parts} == before
    new = sorted(p for p in after if "bead_calibration" in p.parts)
    assert new and all(p.relative_to(p.parents[3]).as_posix() ==
                       "shadowgraph/analysis/bead_calibration/bead_region.png" for p in new)
    measured = {c.run for c in bc.find_captures([day]) if c.kind in ("z", "focus")}
    assert {p.parents[3] for p in new} == measured
    assert len(list((tmp_path / "a2" / "regions").glob("*.png"))) == len(measured)
    assert cv2.imread(str(new[0])).shape[:2] == (H, W)


# ---- the real slides of 2026-10-15: specks, debris, clumps, crowding --------------------------------------

def _frame(h=H, w=W):
    return np.ones((h, w))


def test_faint_specks_are_ignored_and_do_not_crowd_a_bead():
    """The 155.8 slide: ~1,000 faint specks (T 0.8-0.9) around ~35 beads. A speck is not a bead, and one
    beside a bead does not make the bead 'crowded'."""
    T = _frame()
    bead_T(T, 160, 120, 155.8, 12.0)
    for x, y in ((182, 120), (160, 98), (140, 140), (60, 60), (250, 200)):
        bead_T(T, x, y, 30.0, 8.0, tau=0.8)                    # faint specks, two right at the bead's edge
    beads = bc.find_beads(T.astype(np.float32))
    assert len(beads) == 1 and abs(beads[0]["cx"] - 160) < 1.5 and abs(beads[0]["cy"] - 120) < 1.5


def test_two_touching_beads_are_not_a_bead():
    T = _frame()
    bead_T(T, 150, 120, 56.28, 8.0)
    bead_T(T, 156, 120, 56.28, 8.0)                            # 6 px apart: overlapping
    bead_T(T, 60, 60, 56.28, 8.0)                              # and one on its own
    obs = bc.objects(T.astype(np.float32))
    assert [(round(o["cx"]), round(o["cy"])) for o in obs if not o["why"]] == [(60, 60)]
    assert any(o["why"] in ("not round", "crowded") for o in obs if abs(o["cx"] - 153) < 5)


def test_pale_debris_is_not_taken_for_beads_even_when_it_outnumbers_them():
    """Attempt 2's failure on the 98.1 slide: pale debris with a darker centre (core T ~0.45) outnumbered the
    beads 7 to 1, and the slide's 'most common size' became the debris. Beads are dark (core T ~0.1)."""
    T = _frame(480, 640)
    rng = np.random.default_rng(3)
    beads = [(80, 80), (560, 80), (80, 400), (560, 400)]
    for x, y in beads:
        bead_T(T, x, y, 98.1, 10.0)
    for x in range(170, 480, 60):                              # 6 x 5 = 30 pale objects, apart (overlapping
        for y in range(60, 430, 85):                           # pale debris is dark enough to be a bead)
            bead_T(T, x + rng.uniform(-5, 5), y + rng.uniform(-5, 5), 80.0, 10.0, tau=0.45)
    rows, k, rejected = bc.detect_and_identify(T.astype(np.float32), [98.1])
    assert sorted((round(r["cx"] / 10), round(r["cy"] / 10)) for r in rows) == sorted((x // 10, y // 10)
                                                                                       for x, y in beads)
    assert k == pytest.approx(1.0, abs=0.08)


def test_the_sparse_region_leaves_out_a_crowded_patch_and_the_png_shows_it(tmp_path):
    T = _frame(512, 768)
    for j in range(8):                                         # a crowded streak in the bottom-left tile
        for i in range(8):
            bead_T(T, 20 + 12 * i, 400 + 12 * j, 76.39, 8.0)
    for x, y in ((450, 300), (600, 420), (700, 150)):
        bead_T(T, x, y, 76.39, 8.0)
    region, info = bc.sparse_region(T.astype(np.float32))
    assert not region[440, 60] and region[300, 450] and region[420, 600] and region[150, 700]
    assert 0.5 < info["share_of_frame"] < 1.0 and not info["fallback_sparsest"]
    rows, _k, rejected = bc.detect_and_identify(T.astype(np.float32), [76.39], region=region)
    assert len(rows) == 3
    png = tmp_path / "x" / "bead_region.png"
    bc.region_png(T.astype(np.float32), region, rows, rejected, "test", [76.39], [png])
    img = cv2.imread(str(png)).astype(int)
    assert img.shape[:2] == (512, 768)
    assert img[505, 122, 0] - img[505, 122, 2] > 10                 # the left-out tile is shaded (bluish)
    assert abs(img[300, 300, 0] - img[300, 300, 2]) < 3              # the area used is not


def test_a_loose_pcc_cine_is_a_capture_by_its_file_name(tmp_path):
    """The PCC blank (no beads, the dust map) sits in falling/ as 'BEAD blank bg.cine'. A recording inside a
    run's CINE folder, one that run_ai_where has given a run folder, and macOS '._' files are not captures.
    The day may sit under a folder whose name starts with '.' (the check is below the folder given)."""
    day = tmp_path / ".hidden_parent" / "15"
    fall = day / "falling"
    (fall / "BEAD fall 56.28 p1" / "shadowgraph" / "raw" / "CINE").mkdir(parents=True)
    for p in (fall / "BEAD blank bg.cine", fall / "._BEAD blank bg.cine", fall / "BEAD fall 56.28 p1.cine",
              fall / "BEAD fall 56.28 p1" / "shadowgraph" / "raw" / "CINE" / "BEAD fall 56.28 p1.cine"):
        p.write_bytes(b"cine")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Metadata"
    ws.append(["Field", "Value"])
    ws.append(["Notes", "BEAD fall 56.28 p1"])
    wb.save(fall / "BEAD fall 56.28 p1" / "run_summary.xlsx")
    caps = sorted(bc.find_captures([day]), key=lambda c: c.notes)
    assert [(c.notes, c.kind, c.slide, c.run.name) for c in caps] == [
        ("BEAD blank bg", "bg", "blank", "BEAD blank bg.cine"),
        ("BEAD fall 56.28 p1", "fall", "56.28", "BEAD fall 56.28 p1")]


def test_the_falling_beads_equivalent_defocus_is_found():
    """2026-10-15: falling beads read ~0.94 x nominal + 22 um; static beads 2.5-3 mm from focus read the same.
    Built here: static size grows 10 % per mm off focus, the pours read 20 % large -> 2 mm, either side."""
    rows = [{"z_mm": z, "certified_um": c, "d_current_um": c * (1 + 0.1 * abs(z)), "in_focus_current": True}
            for z in (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0) for c in (40.0, 80.0)]
    fall = [{"run": "p1", "certified_um": 40.0, "d_in_focus_median_um": 48.0},
            {"run": "p1", "certified_um": 80.0, "d_in_focus_median_um": 96.0},
            {"run": "all 2 pours", "certified_um": 40.0, "d_in_focus_median_um": 60.0}]   # pooled rows are skipped
    e = bc.equivalent_defocus(rows, fall)
    assert abs(e["best_z_mm"]) == 2.0 and e["misfit_pct"] == 0.0 and abs(e["other_side_z_mm"]) == 2.0
    assert e["sizes_um"] == [40.0, 80.0] and e["falling_ratio"] == {"40": 1.2, "80": 1.2}
    assert bc.equivalent_defocus(rows, []) == {}


def _rle(mask, x0, y0):
    from pycocotools import mask as mask_util
    ys, xs = np.nonzero(mask)
    y, x, y1, x1 = ys.min(), xs.min(), ys.max() + 1, xs.max() + 1
    crop = np.asfortranarray(mask[y:y1, x:x1].astype(np.uint8))
    rle = mask_util.encode(crop)
    rle["counts"] = rle["counts"].decode("ascii")
    full = np.zeros((H, W), np.uint8, order="F")
    full[y:y1, x:x1] = crop
    rle_full = mask_util.encode(full)
    rle_full["counts"] = rle_full["counts"].decode("ascii")
    return {"segmentation": rle_full, "segmentation_crop": rle, "crop_xy": [int(x), int(y)],
            "bbox": [float(x), float(y), float(x1 - x), float(y1 - y)], "area": float(mask.sum())}


def test_falling_beads_are_remeasured_one_by_one(tmp_path):
    """2026-10-15: each AI droplet of a pour re-measured as the pipeline does, plus its blur width; the AI's
    classes on spheres; a blur-width rule keeps the sharp beads and drops the blurred ones."""
    import json as _json
    sg = tmp_path / "BEAD fall 76.39 p1" / "shadowgraph"
    fr = sg / "raw" / "frames" / "16bit"
    fr.mkdir(parents=True)
    (sg / "analysis").mkdir()
    bgimg = backlight()
    cv2.imwrite(str(sg / "raw" / "background_median.tiff"), bgimg.astype(np.uint16))
    images, preds = [], []
    for k, chi in enumerate((10.0, 60.0)):                     # frame 0 sharp, frame 1 well out of focus
        T = np.ones((H, W))
        for x in (100, 230):
            bead_T(T, x, 120, 76.39, chi)
        stem = f"frame_{k:04d}_n{k}"
        cv2.imwrite(str(fr / f"{stem}.tiff"), np.clip(bgimg * T, 0, 65535).astype(np.uint16))
        images.append({"id": k + 1, "file_name": stem + ".png", "width": W, "height": H})
        for x in (100, 230):
            m = np.zeros((H, W), bool)
            m[100:141, x - 20:x + 21] = T[100:141, x - 20:x + 21] < 0.9
            preds.append({"image_id": k + 1, "category_id": 1, "score": 0.99, "truncated": False, **_rle(m, 0, 0)})
    m = np.zeros((H, W), bool)
    m[20:24, 20:80] = True                                     # one 'filament', as the AI calls a defocused bead
    preds.append({"image_id": 1, "category_id": 2, "score": 0.9, "truncated": False, **_rle(m, 0, 0)})
    (sg / "raw" / "instances.json").write_text(_json.dumps({"images": images, "annotations": [], "categories": []}))
    (sg / "analysis" / "predictions.json").write_text(_json.dumps(preds))
    rows, info = bc.falling_detail(sg.parent, 76.39, tau=0.05)
    assert info["classes_n"] == {"droplet": 4, "filament": 1} and 0 < info["atomised_pct_by_area"] < 100
    sharp = [r for r in rows if r["frame"].endswith("n0")]
    blurred = [r for r in rows if r["frame"].endswith("n1")]
    assert len(sharp) == 2 and len(blurred) == 2 and all(r["isolated"] for r in rows)
    assert max(r["chi_um"] for r in sharp) < 20 < min(r["chi_um"] for r in blurred)
    assert all(r["pipeline_d_um"] == pytest.approx(76.39, rel=0.12) for r in sharp)
    s = bc.falling_summary(rows, 76.39, static_ratio=1.0)
    assert s["detections"] == 4 and s["chi_rule"]["20"]["n"] == 2 and s["chi_rule"]["40"]["n"] == 2


def test_the_big_bead_sandwich_runs_through_focus_as_the_2026_10_22_sheet_writes_it(tmp_path):
    d = tmp_path / "2026" / "10" / "22"
    write_run(d, "090000_0sccm_blank", "BEAD blank bg", np.ones((H, W)), seed=40)
    for k, z in enumerate([-1.0, -0.4, 0.0, 0.4, 1.0]):
        T = np.ones((H, W))
        for (x, y), s in zip(GRID, [155.8, 98.1, 76.39, 155.8, 98.1, 76.39]):
            bead_T(T, x, y, s, chi_of(z))
        bead_T(T, 110, 115, 56.28, chi_of(z))              # dark, round and alone, but not one of its sizes
        write_run(d, f"09{k + 1:02d}00_0sccm_big", f"BEAD 155.8+98.1+76.39 z{z:+.2f}", T, seed=41 + k)
    R = bc.analyse([d], tmp_path / "analysis", None, max_frames=3)
    assert R["captures"] == 6
    tf = R["through_focus"]["155.8+98.1+76.39"]
    assert tf["info"]["n_beads"] == 6
    assert {k for k in tf if k != "info"} == {"155.8", "98.1", "76.39"}
