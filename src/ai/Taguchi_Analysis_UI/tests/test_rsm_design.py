"""Phase 3b: the generic CCF run-sheet builder, and comparing a built sheet with captured runs.

Ben's 33-run day (2026-10-09 plan) is regenerated from its plan and checked block by block; the
sheet is then "captured" as fake run folders and read back by rsm_detect, closing the loop. Then
2-, 3-, 4- and 5-factor sheets, the half fraction, seeds, export and bad plans."""
from __future__ import annotations

import csv
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import rsm_design as rb
from src.ai.Taguchi_Analysis_UI import rsm_detect as rsm
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI.tests import fakes

GAS = rb.FactorSpec("sccm", "Gas flow (sccm)", 7000, 9000, 11000, "Gas")
RPM = rb.FactorSpec("rpm", "Bubbler RPM", 100, 500, 900, "RPM")
FEED = rb.FactorSpec("sps", "Silicone (steps/s)", 3000, 4000, 5000, "Feed")
ORI = rb.FactorSpec("orifice", "Orifice (mm)", 0.5, 1.2, 1.8, "Orifice")


def ben_plan(seed=1) -> rb.Plan:
    return rb.Plan(factors=[GAS, RPM, FEED, ORI], block_factor="orifice",
                   first={"sccm": "high", "rpm": "high", "sps": "high", "orifice": "low"},
                   extras=[rb.Extra({"sccm": 9000, "rpm": 0, "sps": 4000, "orifice": 1.2},
                                    "No-rotation control (not in the fit)"),
                           rb.Extra({"sccm": 9000, "rpm": 500, "sps": 4000, "orifice": 0.8})], seed=seed)


def capture(root: Path, sheet: rb.Sheet, order=None, edit=None) -> list[rd.RunInfo]:
    """Fake run folders for the sheet, captured 9 min apart in `order` (default: as planned), with
    the sheet's Notes; `edit(row) -> values` changes what was actually run."""
    rows = [sheet.rows[i] for i in (order or range(len(sheet.rows)))]
    paths = []
    start = datetime(2026, 10, 12, 8, 0)
    for i, r in enumerate(rows, 1):
        v = dict(r.values)
        if edit:
            v = edit(r) or v
        t = (start + timedelta(minutes=9 * i)).strftime("%H%M%S")
        name = f"{t}_{v['sccm']:g}sccm_{v.get('rpm', 500):g}rpm_{v['sps']:g}sps_or{v.get('orifice', 1.2):g}_bh0.5"
        paths.append(fakes.make_run(root, name, day=("2026", "10", "12"), notes=r.notes))
    return rd.load_runs(paths, check_reuse=False)


# ---- Ben's day --------------------------------------------------------------------------------------------

def test_bens_day_is_rebuilt_block_by_block():
    s = rb.build_sheet(ben_plan())
    assert len(s.rows) == 33 and s.counts() == {rsm.CORNER: 16, rsm.FACE: 10, rsm.CENTRE: 5, rsm.OUTSIDE: 1,
                                                rsm.CHECK: 1}
    blocks = s.blocks()
    assert [(b, len(rs)) for b, rs in blocks] == [("Orifice 0.5 mm", 10), ("Orifice 1.2 mm", 12),
                                                  ("Orifice 1.8 mm", 10), ("Checks", 1)]
    first = s.rows[0]
    assert first.values == {"sccm": 11000, "rpm": 900, "sps": 5000, "orifice": 0.5}
    assert first.label == "Corner, pressure check"
    for name, rs in (blocks[0], blocks[2]):
        assert rs[-1].label == "Block repeat (end)" and rs[-1].values == {"sccm": 9000, "rpm": 500, "sps": 4000,
                                                                            "orifice": rs[-1].values["orifice"]}
        assert sum(r.label.startswith("Block repeat") for r in rs) == 2
        assert sum(r.kind == rsm.CORNER for r in rs) == 8
    mid = blocks[1][1]
    assert mid[0].kind == rsm.CENTRE and mid[-1].kind == rsm.CENTRE
    assert sum(r.kind == rsm.CENTRE for r in mid) == 5 and sum(r.kind == rsm.FACE for r in mid) == 6
    ctrl = next(r for r in mid if r.kind == rsm.OUTSIDE)
    assert ctrl.values["rpm"] == 0 and mid.index(ctrl) not in (0, len(mid) - 1)
    assert s.rows[-1].kind == rsm.CHECK and s.rows[-1].values["orifice"] == 0.8
    assert all(r.notes == f"CCD run {r.run} {r.label.split(' (')[0].lower()}" for r in s.rows)


def test_bens_day_estimability_and_coding():
    s = rb.build_sheet(ben_plan())
    e = s.estimability
    assert e.full and e.n_params == 15 and e.n_fit == 31 and e.df_pure_error == 6 and e.df_lack_of_fit == 10
    assert ORI.real_code(1.2) == pytest.approx(0.0769, abs=1e-3) and ORI.code(1.2) == 0
    assert ORI.value(-1) == 0.5 and ORI.value(1) == 1.8 and GAS.value(0) == 9000
    assert 5.5 < s.minutes() / 60 < 6.0


def test_a_built_sheet_captured_as_planned_is_detected_as_planned():
    s = rb.build_sheet(ben_plan())
    with tempfile.TemporaryDirectory() as d:
        det = rsm.from_runs(capture(Path(d), s)).detect()
    assert det.type_key == "ccf" and det.complete and det.k == 4
    assert not [f for p in det.points for f in p.flags]                 # every Note agrees with its settings
    assert [h[0] for h in det.blocks.hard_to_change] == ["orifice"]
    matches = rb.compare(s, det)
    assert [m.status for m in matches] == [rb.PLANNED] * 33


def test_compare_finds_out_of_order_changed_missing_and_extra_runs():
    s = rb.build_sheet(ben_plan())
    order = list(range(33))
    order[3], order[4] = order[4], order[3]           # run 5 captured before run 4
    order = order[:-1]                                # run 33 (the check) not captured yet

    def edit(r):
        if r.run == 7:                                # run 7 done at the wrong feed
            v = dict(r.values)
            v["sps"] = 4000
            return v
    with tempfile.TemporaryDirectory() as d:
        runs = capture(Path(d), s, order=order, edit=edit)
        extra = fakes.make_run(Path(d), "160000_9000sccm_500rpm_4000sps_or1.2_bh0.5", day=("2026", "10", "12"),
                               notes="extra centre")
        det = rsm.from_runs(runs + rd.load_runs([extra], check_reuse=False)).detect()
    m = {x.row.run if x.row else x.point.name[:6]: x for x in rb.compare(s, det)}
    assert m[5].status == rb.OUT_OF_ORDER and m[4].status == rb.PLANNED
    assert m[7].status == rb.DIFFERS and "sps 4000 (planned" in m[7].note
    assert m[33].status == rb.NOT_CAPTURED
    assert m["160000"].status == rb.NOT_ON_SHEET
    assert sum(x.status == rb.PLANNED for x in m.values()) == 30            # 33 - out of order - differs - missing


# ---- other sizes ------------------------------------------------------------------------------------------

def test_a_three_factor_blocked_sheet():
    plan = rb.Plan(factors=[GAS, FEED, ORI], block_factor="orifice",
                   extras=[rb.Extra({"sccm": 9000, "sps": 4000, "orifice": 0.8})])
    s = rb.build_sheet(plan)
    assert s.counts() == {rsm.CORNER: 8, rsm.FACE: 8, rsm.CENTRE: 5, rsm.CHECK: 1}
    assert [len(rs) for _, rs in s.blocks()] == [6, 9, 6, 1]
    assert s.estimability.full and s.estimability.n_params == 10


def test_a_two_factor_unblocked_sheet_spreads_its_centres():
    s = rb.build_sheet(rb.Plan(factors=[GAS, FEED], centres=3))
    assert len(s.rows) == 4 + 4 + 3 and all(r.block is None for r in s.rows)
    cen = [r.run for r in s.rows if r.kind == rsm.CENTRE]
    assert cen[0] == 1 and cen[-1] == len(s.rows) and len(cen) == 3
    assert s.estimability.full


def test_four_factors_unblocked_and_five_factors_as_a_half_fraction():
    s4 = rb.build_sheet(rb.Plan(factors=[GAS, RPM, FEED, ORI]))
    assert len(s4.rows) == 16 + 8 + 5 and s4.estimability.full
    bh = rb.FactorSpec("bh", "Bubbler height (mm)", 0.3, 0.5, 0.7)
    s5 = rb.build_sheet(rb.Plan(factors=[GAS, RPM, FEED, ORI, bh], fraction="half"))
    assert s5.counts()[rsm.CORNER] == 16 and len(s5.rows) == 16 + 10 + 5
    assert s5.estimability.usable and s5.estimability.n_params == 21          # resolution V: all of it
    corners = [tuple(r.coded.values()) for r in s5.rows if r.kind == rsm.CORNER]
    assert all(c[4] == c[0] * c[1] * c[2] * c[3] for c in corners)
    full5 = rb.build_sheet(rb.Plan(factors=[GAS, RPM, FEED, ORI, bh]))
    assert len(full5.rows) == 32 + 10 + 5


def test_a_four_factor_half_fraction_warns_that_the_quadratic_is_not_estimable():
    """Resolution IV: two-factor interactions aliased in pairs. Orifice's uneven middle breaks the
    aliasing by a hair, so the rank is full; the VIF check is what catches it."""
    s = rb.build_sheet(rb.Plan(factors=[GAS, RPM, FEED, ORI], fraction="half"))
    e = s.estimability
    assert not e.usable and {t.name for t in e.nearly_aliased} == {
        "sccm*rpm", "sccm*sps", "sccm*orifice", "rpm*sps", "rpm*orifice", "sps*orifice"}
    assert any("keep all 16 corners" in f for f in s.findings)
    assert rb.build_sheet(ben_plan()).estimability.usable                  # the full 16 corners: fine


def test_the_seed_reproduces_the_order_and_a_new_seed_reshuffles_it():
    a, b, c = (rb.build_sheet(ben_plan(seed)) for seed in (1, 1, 2))
    assert [r.values for r in a.rows] == [r.values for r in b.rows]
    assert [r.values for r in a.rows] != [r.values for r in c.rows]
    assert sorted(map(str, (r.values for r in a.rows))) == sorted(map(str, (r.values for r in c.rows)))
    assert c.rows[0].label == "Corner, pressure check"                    # still first whatever the seed


def test_save_load_and_export(tmp_path):
    s = rb.build_sheet(ben_plan())
    rb.save(s, tmp_path)
    again = rb.load(tmp_path)
    assert [r.values for r in again.rows] == [r.values for r in s.rows] and not any(
        "differ" in f for f in again.findings)
    files = rb.export(s, tmp_path)
    assert {p.name for p in files} == {"run_sheet.csv", "run_sheet.xlsx", "run_sheet.md"}
    rows = list(csv.DictReader(open(tmp_path / "run_sheet.csv", encoding="utf-8")))
    assert len(rows) == 33 and rows[0]["Notes to type"] == "CCD run 1 corner, pressure check"
    assert rows[0]["Block"] == "Orifice 0.5 mm"
    assert "| 33 | Checks |" in (tmp_path / "run_sheet.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("plan, msg", [
    (rb.Plan(factors=[GAS]), "2 to 5 factors"),
    (rb.Plan(factors=[GAS, replace(FEED, mid=6000)]), "low < middle < high"),
    (rb.Plan(factors=[GAS, FEED], block_factor="rpm"), "not one of the factors"),
    (rb.Plan(factors=[GAS, FEED], first={"sccm": "high"}), "every factor"),
    (rb.Plan(factors=[GAS, RPM, FEED], fraction="half", first={"sccm": "high", "rpm": "high", "sps": "low"}),
     "not one of the design's corners"),
])
def test_bad_plans_are_refused_with_a_reason(plan, msg):
    with pytest.raises(rb.PlanError, match=msg):
        rb.build_sheet(plan)
