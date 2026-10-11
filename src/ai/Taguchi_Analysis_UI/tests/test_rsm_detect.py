"""Phase 3a: detecting the response-surface design from the run folders alone.

Fake run folders (fakes.make_run: real names, workbooks and Notes) laid out as Ben's 33-run
CCF day (2026-10-09 plan: gas x feed x RPM x orifice, orifice fitted once per block, five
centres, block repeats, a 0 rpm control and a 0.8 mm check), plus a CCF with a missing corner,
a rotatable CCD, a Box-Behnken and an irregular set; and the real 10/05 L9 (read-only)."""
from __future__ import annotations

import itertools
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import rsm_detect as rsm
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI.tests import fakes

REAL_10_05 = Path("/Volumes/LaCie/Experiments/2026/10/05")

# Ben's run sheet: (orifice, gas, feed, rpm, point type)
CCF_DAY = [
    (0.5, 11000, 5000, 900, "Corner, pressure check"), (0.5, 9000, 4000, 500, "Block repeat (start)"),
    (0.5, 11000, 3000, 100, "Corner"), (0.5, 7000, 3000, 100, "Corner"), (0.5, 7000, 3000, 900, "Corner"),
    (0.5, 11000, 3000, 900, "Corner"), (0.5, 11000, 5000, 100, "Corner"), (0.5, 7000, 5000, 100, "Corner"),
    (0.5, 7000, 5000, 900, "Corner"), (0.5, 9000, 4000, 500, "Block repeat (end)"),
    (1.2, 9000, 4000, 500, "Centre"), (1.2, 11000, 4000, 500, "Gas face"), (1.2, 9000, 4000, 100, "RPM face"),
    (1.2, 9000, 4000, 500, "Centre"), (1.2, 9000, 4000, 900, "RPM face"),
    (1.2, 9000, 4000, 0, "No-rotation control (not in the fit)"), (1.2, 9000, 4000, 500, "Centre"),
    (1.2, 9000, 5000, 500, "Feed face"), (1.2, 9000, 3000, 500, "Feed face"), (1.2, 9000, 4000, 500, "Centre"),
    (1.2, 7000, 4000, 500, "Gas face"), (1.2, 9000, 4000, 500, "Centre"),
    (1.8, 9000, 4000, 500, "Block repeat (start)"), (1.8, 7000, 5000, 100, "Corner"),
    (1.8, 7000, 3000, 100, "Corner"), (1.8, 7000, 5000, 900, "Corner"), (1.8, 11000, 5000, 100, "Corner"),
    (1.8, 11000, 3000, 100, "Corner"), (1.8, 11000, 5000, 900, "Corner"), (1.8, 7000, 3000, 900, "Corner"),
    (1.8, 11000, 3000, 900, "Corner"), (1.8, 9000, 4000, 500, "Block repeat (end)"),
    (0.8, 9000, 4000, 500, "Check run (not in the fit)"),
]


def _make(root: Path, rows, *, start=datetime(2026, 10, 12, 8, 0), notes=True, numbers=None) -> list[rd.RunInfo]:
    """Runs captured 9 min apart in the order given; Notes "CCD run <n> <type>" with n from
    `numbers` (default 1, 2, 3, ... = captured as planned)."""
    paths = []
    numbers = numbers or list(range(1, len(rows) + 1))
    for i, ((orifice, gas, feed, rpm, kind), n) in enumerate(zip(rows, numbers), 1):
        t = (start + timedelta(minutes=9 * i)).strftime("%H%M%S")
        name = f"{t}_{gas:g}sccm_{rpm:g}rpm_{feed:g}sps_or{orifice:g}_bh0.5"
        paths.append(fakes.make_run(root, name, day=(start.strftime("%Y"), start.strftime("%m"), start.strftime("%d")),
                                    notes=f"CCD run {n} {kind}" if notes else ""))
    return rd.load_runs(paths, check_reuse=False)


@pytest.fixture(scope="module")
def ccf_day():
    with tempfile.TemporaryDirectory() as d:
        runs = _make(Path(d), CCF_DAY)
        yield rsm.from_runs(runs).detect(), runs


def _by_note(det, n: int):
    return next(p for p in det.points if p.noted_run == n)


# ---- Ben's 33-run day ----------------------------------------------------------------------------------

def test_the_ccf_day_is_a_complete_four_factor_face_centred_ccd(ccf_day):
    det, _ = ccf_day
    assert det.type_key == "ccf" and det.k == 4 and det.complete, det.findings
    assert {f.key for f in det.factors} == {"sccm", "rpm", "sps", "orifice"}
    assert ("Bubbler height (mm)", 0.5) in det.fixed
    assert det.recommendation[0] == "Response surface"
    assert "31 design runs + 2 check / control run(s)" in det.recommendation[1]


def test_every_run_of_the_day_gets_the_right_point_type(ccf_day):
    det, _ = ccf_day
    c = det.counts()
    assert c == {rsm.CORNER: 16, rsm.FACE: 10, rsm.CENTRE: 5, rsm.OUTSIDE: 1, rsm.CHECK: 1}
    assert _by_note(det, 16).kind == rsm.OUTSIDE              # 0 rpm control
    assert _by_note(det, 33).kind == rsm.CHECK                # the 0.8 mm insert
    assert all(_by_note(det, n).kind == rsm.FACE for n in (2, 10, 23, 32))   # orifice faces = block repeats
    assert all(_by_note(det, n).kind == rsm.CENTRE for n in (11, 14, 17, 20, 22))
    assert not [f for p in det.points for f in p.flags]      # Notes agree with every run, order as planned


def test_orifice_levels_coding_and_special_values(ccf_day):
    det, _ = ccf_day
    o = next(f for f in det.factors if f.key == "orifice")
    r = next(f for f in det.factors if f.key == "rpm")
    assert o.levels == [0.5, 1.2, 1.8] and o.special == {0.8: rsm.CHECK}
    assert r.levels == [100, 500, 900] and r.special == {0: rsm.OUTSIDE}
    assert o.design_code(1.2) == 0 and o.design_code(0.5) == -1 and o.design_code(1.8) == 1
    assert o.real_code(1.2) == pytest.approx((1.2 - 1.15) / 0.65)          # the plan's +0.08
    assert o.real_code(0.8) == pytest.approx((0.8 - 1.15) / 0.65)


def test_the_orifice_is_flagged_as_a_block_confounded_with_time(ccf_day):
    det, _ = ccf_day
    assert [h[0] for h in det.blocks.hard_to_change] == ["orifice"]
    assert det.blocks.block_factor == "orifice"
    pairs = {(a.noted_run, b.noted_run) for _, a, b in det.blocks.drift_pairs}
    assert {(2, 10), (23, 32), (11, 22)} <= pairs              # block repeats + first/last centre
    assert any("confounded with time of day" in f.text for f in det.findings)


def test_the_full_quadratic_is_estimable_with_the_plans_degrees_of_freedom(ccf_day):
    det, _ = ccf_day
    e = det.estimability
    assert e.full and e.n_fit == 31 and e.n_params == 15
    assert e.df_pure_error == 4 + 1 + 1                        # 5 centres, two orifice-face pairs
    assert e.df_lack_of_fit == 31 - 15 - 6


def test_a_disagreeing_note_and_an_out_of_order_run_are_flagged():
    rows = [list(r) for r in CCF_DAY]
    rows[2][4] = "Centre"                                     # run 3 is a corner
    numbers = list(range(1, 34))
    rows[5], rows[6] = rows[6], rows[5]                       # run 7 captured before run 6
    numbers[5], numbers[6] = 7, 6
    with tempfile.TemporaryDirectory() as d:
        det = rsm.from_runs(_make(Path(d), [tuple(r) for r in rows], numbers=numbers)).detect()
    assert any("Notes say centre, the settings are a corner" in f for f in _by_note(det, 3).flags)
    late = [p.noted_run for p in det.points if any("out of the planned order" in f for f in p.flags)]
    assert late == [6]
    assert det.type_key == "ccf" and det.complete             # the settings themselves are still the CCF


def test_a_missing_corner_is_named():
    rows = [r for r in CCF_DAY if not (r[0] == 1.8 and r[1:4] == (11000, 3000, 900))]
    with tempfile.TemporaryDirectory() as d:
        det = rsm.from_runs(_make(Path(d), rows)).detect()
    assert det.type_key == "ccf" and not det.complete
    assert det.missing == [{"kind": rsm.CORNER, "coded": (1.0, 1.0, -1.0, 1.0),
                            "values": {"Gas flow (sccm)": 11000, "Bubbler RPM": 900, "Silicone (steps/s)": 3000,
                                       "Orifice (mm)": 1.8}}]
    assert any("corner not run" in f.text for f in det.findings)


# ---- other designs -------------------------------------------------------------------------------------------

def _grid(points, centre=(9000, 4000, 500), step=(2000, 1000, 200), orifice=1.2):
    out = []
    for p in points:
        g, f, r = (round(c + x * s) for c, x, s in zip(centre, p, step))
        out.append((orifice, g, f, r, ""))
    return out


def test_a_rotatable_ccd_is_recognised_with_its_alpha():
    a = (2 ** 3) ** 0.25
    pts = list(itertools.product((-1, 1), repeat=3)) + \
        [tuple(s * a if j == i else 0 for j in range(3)) for i in range(3) for s in (-1, 1)] + [(0, 0, 0)] * 4
    with tempfile.TemporaryDirectory() as d:
        det = rsm.from_runs(_make(Path(d), _grid(pts), notes=False)).detect()
    assert det.type_key == "ccd" and det.complete, det.findings
    assert det.alpha == pytest.approx(a, rel=0.01) and "rotatable" in det.design_type
    assert det.counts() == {rsm.CORNER: 8, rsm.AXIAL: 6, rsm.CENTRE: 4}
    assert det.estimability.full


def test_a_box_behnken_is_recognised():
    pts = [tuple(s1 if j == a else s2 if j == b else 0 for j in range(3))
           for a, b in itertools.combinations(range(3), 2) for s1 in (-1, 1) for s2 in (-1, 1)] + [(0, 0, 0)] * 3
    with tempfile.TemporaryDirectory() as d:
        det = rsm.from_runs(_make(Path(d), _grid(pts), notes=False)).detect()
    assert det.type_key == "bbd" and det.complete and det.counts() == {rsm.EDGE: 12, rsm.CENTRE: 3}
    assert det.estimability.full and det.recommendation[0] == "Response surface"


def test_an_irregular_set_falls_back_to_an_estimable_reduced_model():
    # a gas x feed square with centres and an odd extra point; RPM moved only at the centre, so
    # nothing pairs RPM with the other factors' extremes and its interactions cannot be estimated
    pts = [(-1, -1, 0), (1, -1, 0), (-1, 1, 0), (1, 1, 0), (0, 0, 0), (0, 0, 0), (0.5, -1, 0), (0, 0, 1), (0, 0, -1)]
    with tempfile.TemporaryDirectory() as d:
        det = rsm.from_runs(_make(Path(d), _grid(pts), notes=False)).detect()
    e = det.estimability
    assert not e.full and e.dropped
    assert all(t.kept for t in e.terms if len(t.parents) == 1)        # every linear term stays
    assert "reduced model" in det.recommendation[1]


def test_validation_runs_and_left_out_runs_leave_the_fit(ccf_day):
    _, runs = ccf_day
    d = rsm.from_runs(runs)
    centre = next(r for r in d.base.rows if "CCD run 22 " in r.notes)
    corner = next(r for r in d.base.rows if "CCD run 31 " in r.notes)
    d.validation.add(centre.path)
    corner.included = False
    det = d.detect()
    assert det.estimability.n_fit == 29
    assert not det.complete and det.missing and det.missing[0]["kind"] == rsm.CORNER


def test_the_edits_save_and_reload(ccf_day, tmp_path):
    _, runs = ccf_day
    d = rsm.from_runs(runs)
    d.validation.add(d.base.rows[0].path)
    d.block_factor = None
    d.base.rename_factor("sps", "Silicone feed")
    rsm.save(d, tmp_path)
    again = rsm.from_runs(runs)
    notes = again.apply_saved(rsm.load_saved(tmp_path))
    assert notes == [] and again.validation == {d.base.rows[0].path} and again.block_factor is None
    assert again.base.factor("sps").label == "Silicone feed"
    assert again.detect().blocks.block_factor is None


# ---- the real 9x3 -----------------------------------------------------------------------------------------

@pytest.mark.skipif(not REAL_10_05.is_dir(), reason="LaCie not mounted")
def test_the_real_10_05_campaign_is_an_l9_for_the_taguchi_tab():
    runs = rd.load_runs(sorted(p for p in REAL_10_05.iterdir() if p.is_dir()), check_reuse=False)
    det = rsm.from_runs(runs).detect()
    assert det.type_key == "oa" and "L9" in det.design_type
    assert det.recommendation == ("Taguchi", "orthogonal array (Taguchi L9): use the Taguchi tab")
    assert [h[0] for h in det.blocks.hard_to_change] == ["rpm"]       # RPM rose with time of day


def test_a_three_factor_ccf_day_with_orifice_blocks_and_a_check_run():
    """The 3-factor version of the day (gas x feed x orifice, RPM held at 500): orifice blocks with
    start/end repeats, five centres, a 0.8 mm check run."""
    corners = list(itertools.product((7000, 11000), (3000, 5000)))
    rows = ([(0.5, 9000, 4000, 500, "Block repeat (start)")] + [(0.5, g, f, 500, "Corner") for g, f in corners]
            + [(0.5, 9000, 4000, 500, "Block repeat (end)")]
            + [(1.2, 9000, 4000, 500, "Centre"), (1.2, 11000, 4000, 500, "Gas face"), (1.2, 9000, 4000, 500, "Centre"),
               (1.2, 9000, 5000, 500, "Feed face"), (1.2, 9000, 4000, 500, "Centre"), (1.2, 9000, 3000, 500, "Feed face"),
               (1.2, 7000, 4000, 500, "Gas face"), (1.2, 9000, 4000, 500, "Centre"), (1.2, 9000, 4000, 500, "Centre")]
            + [(1.8, 9000, 4000, 500, "Block repeat (start)")] + [(1.8, g, f, 500, "Corner") for g, f in corners]
            + [(1.8, 9000, 4000, 500, "Block repeat (end)"), (0.8, 9000, 4000, 500, "Check run")])
    with tempfile.TemporaryDirectory() as d:
        det = rsm.from_runs(_make(Path(d), rows)).detect()
    assert det.type_key == "ccf" and det.k == 3 and det.complete, det.findings
    assert {f.key for f in det.factors} == {"sccm", "sps", "orifice"} and ("Bubbler RPM", 500) in det.fixed
    assert det.counts() == {rsm.CORNER: 8, rsm.FACE: 8, rsm.CENTRE: 5, rsm.CHECK: 1}   # 4 gas/feed + 4 orifice faces
    assert [h[0] for h in det.blocks.hard_to_change] == ["orifice"]
    e = det.estimability
    assert e.full and e.n_params == 10 and e.n_fit == 21 and e.df_pure_error == 4 + 1 + 1
    assert not [f for p in det.points for f in p.flags]


def test_a_factor_that_is_a_run_summary_field_works_like_a_built_in_one():
    """Any run_summary.xlsx field can be a factor (here Motor Travel, 30 / 36 / 42 mm, crossed with gas
    flow as a 2-factor CCF): detection, levels, point types and estimability are the same."""
    pts = list(itertools.product((-1, 1), repeat=2)) + [(-1, 0), (1, 0), (0, -1), (0, 1)] + [(0, 0)] * 3
    paths = []
    with tempfile.TemporaryDirectory() as d:
        start = datetime(2026, 10, 12, 8, 0)
        for i, (g, m) in enumerate(pts, 1):
            t = (start + timedelta(minutes=9 * i)).strftime("%H%M%S")
            paths.append(fakes.make_run(Path(d), f"{t}_{9000 + 2000 * g:g}sccm_500rpm_4000sps_or1.2_bh0.5",
                                        day=("2026", "10", "12"), overrides={"Motor Travel (mm)": str(36 + 6 * m)}))
        design = rsm.from_runs(rd.load_runs(paths, check_reuse=False))
        design.base.add_factor("Motor Travel (mm)")
        det = design.detect()
    assert {f.key for f in det.factors} == {"sccm", "wb:Motor Travel (mm)"}      # workbook factors are keyed "wb:<field>"
    travel = next(f for f in det.factors if f.key == "wb:Motor Travel (mm)")
    assert travel.levels == [30, 36, 42] and travel.label == "Motor Travel (mm)"
    assert det.type_key == "ccf" and det.complete and det.estimability.full
    assert det.counts() == {rsm.CORNER: 4, rsm.FACE: 4, rsm.CENTRE: 3}
