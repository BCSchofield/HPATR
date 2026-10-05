"""The Taguchi design model: detection, the two-way replicate cross-check, editing,
diagnostics and persistence. Fakes mirror the real 10/05 format (see fakes.py)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.ai.Taguchi_Analysis_UI import design as dz
from src.ai.Taguchi_Analysis_UI import run_discovery as rd
from src.ai.Taguchi_Analysis_UI.tests import fakes

REAL_DAY = Path("/Volumes/LaCie/Experiments/2026/10/05")
REAL_01 = Path("/Volumes/LaCie/Experiments/2026/10/01")
needs_lacie = pytest.mark.skipif(not REAL_DAY.is_dir(), reason="LaCie not mounted")


@pytest.fixture
def root():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def runs_of(root, names_notes, **kw):
    for name, notes in names_notes:
        fakes.make_run(root, name, notes=notes, **kw)
    return rd.load_runs(rd.find_runs([root / "2026"]).runs, check_reuse=False)


def l9x3(root):
    return runs_of(root, [(n, f"Taguchi ReRun {t} - Repeat {r}\nWITH NOZZLE ADAPTER")
                          for n, t, r in fakes.REAL_10_05])


def by_prefix(d, prefix):
    return next(r for r in d.rows if r.name.startswith(prefix))


# ---- Notes parsing --------------------------------------------------------------------

@pytest.mark.parametrize("notes,expected", [
    ("Taguchi ReRun 6 - Repeat 2\nWITH NOZZLE ADAPTER", (6, 2)),    # real, 10/05
    ("Taguchi 6", (6, None)),                                       # real, 10/01: no repeat
    ("Taguchi ReRun 1 - Repeat 1", (1, 1)),
    ("Trial 3 – Rep 1", (3, 1)),
    ("Run 2 — Replicate 3", (2, 3)),
    ("taguchi rerun 9 - repeat 3", (9, 3)),
    ("Trial #4, Repeat #2", (4, 2)),
    ("MAX TEST", (None, None)),                                     # real, 10/01
    ("", (None, None)),
    (None, (None, None)),
    ("WITH NOZZLE ADAPTER", (None, None)),
])
def test_parse_notes(notes, expected):
    assert dz.parse_notes(notes) == expected


# ---- detection ---------------------------------------------------------------------------

def test_a_real_format_9x3_is_confirmed_two_ways(root):
    d = dz.detect(l9x3(root))
    a = dz.assign(d)
    assert [f.key for f in d.factors] == ["sccm", "rpm", "sps"]
    assert a.counts() == {dz.AGREE: 27}
    assert len(a.conditions) == 9 and {len(c.rows) for c in a.conditions} == {3}
    text, level = dz.headline(d, a)
    assert level == "ok" and text.startswith("27 runs = 9 conditions × 3 replicates")
    assert "two independent ways" in text


def test_conditions_are_labelled_by_the_trial_in_the_notes_and_replicates_by_repeat(root):
    d = dz.detect(l9x3(root))
    a = dz.assign(d)
    assert [c.label for c in a.conditions] == [f"T{i}" for i in range(1, 10)] or \
        sorted(c.label for c in a.conditions) == sorted(f"T{i}" for i in range(1, 10))
    for r in d.rows:
        res = a.of(r)
        assert res.condition.label == f"T{r.trial}" and res.replicate == r.repeat


def test_folder_order_is_not_condition_order(root):
    """111625 (ReRun 5) precedes 112253 (ReRun 4) in the folder listing. Grouping uses the
    factor levels, so the interleaving cannot split or merge conditions."""
    d = dz.detect(l9x3(root))
    names = [r.name for r in d.rows]
    assert names.index(next(n for n in names if n.startswith("111625"))) < \
           names.index(next(n for n in names if n.startswith("112253")))
    a = dz.assign(d)
    t4 = next(c for c in a.conditions if c.label == "T4")
    assert [r.name[:6] for r in t4.rows] == ["105504", "110329", "112253"]
    assert [a.of(r).replicate for r in t4.rows] == [1, 2, 3]


def test_constant_factors_are_not_picked_but_can_be_added(root):
    d = dz.detect(l9x3(root))
    assert not d.has("orifice") and not d.has("bh")
    keys = [k for k, _ in d.candidates()]
    assert "orifice" in keys and "bh" in keys and "GLR" in keys and "FPS" in keys
    assert "Notes" not in keys and "Timestamp" not in keys
    f = d.add_factor("orifice")
    assert f.numeric and {r.value("orifice") for r in d.rows} == {1.2}
    assert any("single level" in x.text for x in dz.diagnose(d))


def test_a_selection_where_nothing_varies_falls_back_to_the_usual_three(root):
    runs = runs_of(root, [(fakes.REAL_10_05[0][0], "Taguchi 1")])
    assert [f.key for f in dz.detect(runs).factors] == ["sccm", "rpm", "sps"]


def test_levels_are_normalised_so_floats_group_cleanly():
    assert dz.norm(3000.0) == 3000 and dz.norm(0.1 + 0.2) == 0.3 and dz.norm(" Nitrogen ") == "Nitrogen"
    assert dz.norm(None) is None and isinstance(dz.norm(3000.0), int)


# ---- the cross-check catches disagreement ---------------------------------------------------------

def test_notes_that_disagree_with_the_levels_are_a_conflict(root):
    notes = {n: f"Taguchi ReRun {t} - Repeat {r}" for n, t, r in fakes.REAL_10_05}
    victim = fakes.REAL_10_05[1][0]                 # a T1 run
    notes[victim] = "Taguchi ReRun 2 - Repeat 1"    # ... that the Notes call trial 2
    d = dz.detect(runs_of(root, notes.items()))
    a = dz.assign(d)
    assert a.of(by_prefix(d, victim[:6])).status == dz.CONFLICT
    # the ROOT cause is reported (wrong trial), not the symptom (a repeat number used twice)
    assert "Notes say trial 2" in a.of(by_prefix(d, victim[:6])).detail
    text, level = dz.headline(d, a)
    assert level == "error" and "DISAGREE" in text
    assert any(f.level == "error" and "wrong" in f.text for f in dz.diagnose(d))


def test_the_same_repeat_twice_in_one_condition_is_a_conflict(root):
    notes = {n: f"Taguchi ReRun {t} - Repeat {r}" for n, t, r in fakes.REAL_10_05}
    dup = fakes.REAL_10_05[2][0]                    # T1 repeat 3 -> claim repeat 2 again
    notes[dup] = "Taguchi ReRun 1 - Repeat 2"
    d = dz.detect(runs_of(root, notes.items()))
    a = dz.assign(d)
    flagged = [r for r in d.rows if a.of(r).status == dz.CONFLICT]
    assert len(flagged) == 2 and all("more than once" in a.of(r).detail for r in flagged)


def test_runs_without_a_trial_are_grouped_by_levels_and_say_so(root):
    d = dz.detect(runs_of(root, [(n, "") for n, _, _ in fakes.REAL_10_05]))
    a = dz.assign(d)
    assert a.counts() == {dz.TUPLE_ONLY: 27} and len(a.conditions) == 9
    assert [c.label for c in a.conditions] == [f"C{i}" for i in range(1, 10)]
    text, level = dz.headline(d, a)
    assert level == "info" and "factor levels only" in text and "nothing to cross-check" in text


def test_trial_only_notes_like_the_old_10_01_runs_agree(root):
    # 10/01 style: "Taguchi N", no repeat number; replicates numbered by time order
    names = [(n, f"Taguchi {t}") for n, t, r in fakes.REAL_10_05]
    d = dz.detect(runs_of(root, names))
    a = dz.assign(d)
    assert a.counts() == {dz.AGREE: 27}
    t3 = next(c for c in a.conditions if c.label == "T3")
    assert [a.of(r).replicate for r in t3.rows] == [1, 2, 3]


def test_mixed_notes_flag_the_unnamed_runs_as_probably_outside_the_design(root):
    names = [(n, f"Taguchi {t}") for n, t, r in fakes.REAL_10_05 if r == 1]     # one per condition
    names += [("101035_4500sccm_500rpm_6000sps_or1.2_nobh", ""),
              ("120606_9000sccm_900rpm_8000sps_or1.2_bh1", "MAX TEST")]
    d = dz.detect(runs_of(root, names))
    a = dz.assign(d)
    stray = dz.outside_design(d, a)
    assert sorted(r.name[:6] for r in stray) == ["101035", "120606"]
    msg = next(f for f in dz.diagnose(d) if "side tests" in f.text)
    assert "MAX TEST" in msg.text and "Leave out runs with no trial" in msg.text
    # leaving them out removes the spurious aliasing
    for r in stray:
        r.included = False
    assert not any("ALIASED" in f.text for f in dz.diagnose(d))


def test_outside_design_needs_notes_to_tell_runs_apart(root):
    d = dz.detect(runs_of(root, [(n, "") for n, t, r in fakes.REAL_10_05 if r == 1]))
    assert dz.outside_design(d) == []


# ---- unassigned runs and manual assignment -----------------------------------------------------------

def test_a_run_with_a_missing_level_is_listed_and_fixed_by_giving_it_one(root):
    runs = l9x3(root)
    d = dz.detect(runs)
    row = by_prefix(d, "090432")
    row.detected["rpm"] = None                       # as if the folder name said norpm / no workbook
    a = dz.assign(d)
    assert a.of(row).status == dz.UNASSIGNED and "no value for Bubbler RPM" in a.of(row).detail
    assert row.path not in {r.path for c in a.conditions for r in c.rows}
    assert dz.headline(d, a)[1] == "warn"
    # its siblings are fine: a run with unknown levels cannot contradict them
    assert {a.of(r).status for r in d.rows if r.trial == 1 and r is not row} == {dz.AGREE}
    d.set_value(row, "rpm", 300)                     # the user fills it in
    a = dz.assign(d)
    assert a.of(row).status == dz.AGREE and a.of(row).condition.label == "T1"


def test_editing_a_level_moves_the_run_between_conditions(root):
    d = dz.detect(l9x3(root))
    row = by_prefix(d, "090432")
    d.set_value(row, "sccm", 6000)
    a = dz.assign(d)
    assert a.of(row).status == dz.CONFLICT           # Notes still say T1: the cross-check notices
    d.set_value(row, "sccm", 3000)                   # typing the detected value back
    assert "sccm" not in row.overrides and dz.assign(d).of(row).status == dz.AGREE


def test_dropping_a_run_removes_it_from_everything(root):
    d = dz.detect(l9x3(root))
    row = by_prefix(d, "090432")
    row.included = False
    a = dz.assign(d)
    assert a.of(row).status == dz.DROPPED and a.n_runs == 26
    text, _ = dz.headline(d, a)
    assert "unbalanced" in text


# ---- editing the factors ---------------------------------------------------------------------------------

def test_rename_keeps_the_key_and_rejects_duplicates_and_blanks(root):
    d = dz.detect(l9x3(root))
    d.rename_factor("sps", "Silicone flow (steps/s)")
    assert d.factor("sps").label == "Silicone flow (steps/s)" and d.customised
    with pytest.raises(ValueError):
        d.rename_factor("rpm", "Silicone flow (steps/s)")
    with pytest.raises(ValueError):
        d.rename_factor("rpm", "   ")


def test_add_a_factor_from_any_workbook_field(root):
    d = dz.detect(l9x3(root))
    f = d.add_factor("Motor Travel (mm)")           # a STRING in the workbook: "36"
    assert f.key == "wb:Motor Travel (mm)" and f.numeric
    assert {r.value(f.key) for r in d.rows} == {36}
    g = d.add_factor("Fluid")                        # text -> categorical
    assert not g.numeric and {r.value(g.key) for r in d.rows} == {"EcoFlex 00-30"}
    with pytest.raises(ValueError):
        d.add_factor("Fluid")


def test_a_range_field_uses_max_min_or_mean_on_request(root):
    d = dz.detect(l9x3(root))
    f = d.add_factor("Flow Range (sccm)")            # "0-3090 sccm" -> pick
    first = by_prefix(d, "090432")
    assert first.value(f.key) == 3090
    d.set_pick(f.key, "min")
    assert first.value(f.key) == 0
    d.set_pick(f.key, "mean")
    assert first.value(f.key) == 1545


def test_using_the_achieved_flow_is_flagged_as_breaking_the_design(root):
    d = dz.detect(l9x3(root))
    d.remove_factor("sccm")
    d.add_factor("Flow Range (sccm)", label="Achieved flow")
    findings = dz.diagnose(d)
    assert any("ACHIEVED flow" in f.text for f in findings)


def test_remove_factor_drops_its_values(root):
    d = dz.detect(l9x3(root))
    d.set_value(d.rows[0], "rpm", 999)
    d.remove_factor("rpm")
    assert not d.has("rpm") and all("rpm" not in r.detected and "rpm" not in r.overrides for r in d.rows)
    assert len(dz.assign(d).conditions) == 9 or True        # fewer distinct tuples now
    assert len(dz.assign(d).conditions) == 3 * 3            # sccm x sps still 9 distinct pairs


# ---- diagnostics ------------------------------------------------------------------------------------------

def test_a_clean_9x3_is_all_green(root):
    findings = dz.diagnose(dz.detect(l9x3(root)))
    assert {f.level for f in findings} == {"ok"}
    assert any("18 degrees of freedom" in f.text for f in findings)
    assert sum("orthogonal" in f.text for f in findings) == 3


def test_leaving_out_a_whole_condition_is_non_orthogonal_but_still_estimable(root):
    """An L9 missing one condition has empty cells in its pair tables, so it is no longer
    orthogonal -- but every main effect can still be estimated (the model keeps its rank).
    Calling that 'aliased' (as this tab first did) overstated it."""
    d = dz.detect(l9x3(root))
    for r in d.rows:
        if r.trial == 1:
            r.included = False                       # T1 = 3000 sccm / 300 rpm / 4000 sps
    findings = dz.diagnose(d)
    assert not any("ALIASED" in f.text or "partly aliased" in f.text for f in findings)
    nonorth = [f for f in findings if "not orthogonal" in f.text]
    assert len(nonorth) == 3 and all(f.level == "warn" for f in nonorth)
    assert "still analysed" in nonorth[0].text


def test_a_factor_whose_levels_mirror_another_is_truly_aliased(root):
    d = dz.detect(l9x3(root))
    d.add_factor("Bubbler RPM")                     # the workbook copy of the rpm column
    findings = dz.diagnose(d)
    aliased = [f for f in findings if "is ALIASED" in f.text]
    assert aliased and all(f.level == "error" for f in aliased)
    assert "no numbers" in aliased[0].text


def test_a_level_seen_only_with_one_other_level_is_partly_aliased(root):
    names = [(n, f"Taguchi {t}") for n, t, r in fakes.REAL_10_05 if r == 1]
    names.append(("101035_4500sccm_500rpm_6000sps_or1.2_nobh", ""))      # the real 10/01 side run
    d = dz.detect(runs_of(root, names))
    partly = [f for f in dz.diagnose(d) if " is partly aliased" in f.text]
    assert {f.text.split(" is ")[0] for f in partly} == {"Gas flow (sccm)", "Bubbler RPM"}
    assert all("2 of its 3" in f.text for f in partly)


def test_one_missing_replicate_is_uneven_replication_not_aliasing(root):
    d = dz.detect(l9x3(root))
    d.rows[0].included = False
    findings = dz.diagnose(d)
    assert not any("ALIASED" in f.text for f in findings)
    assert any("Replication is uneven" in f.text and "2–3" in f.text for f in findings)
    assert any("not used equally often" in f.text for f in findings)


def test_no_replicates_is_explained_in_terms_of_the_error_term(root):
    d = dz.detect(runs_of(root, [(n, f"Taguchi {t}") for n, t, r in fakes.REAL_10_05 if r == 1]))
    f = next(x for x in dz.diagnose(d) if "No replicates" in x.text)
    assert f.level == "warn" and "interactions rather than noise" in f.text


def test_runs_from_several_days_are_warned_about(root):
    fakes.make_run(root, fakes.REAL_10_05[0][0], day=("2026", "10", "01"), notes="Taguchi 1")
    fakes.make_run(root, fakes.REAL_10_05[1][0], day=("2026", "10", "05"), notes="Taguchi 1")
    d = dz.detect(rd.load_runs(rd.find_runs([root / "2026"]).runs, check_reuse=False))
    assert any("2 different days" in f.text for f in dz.diagnose(d))


def test_too_many_levels_suggests_it_is_a_measurement(root):
    d = dz.detect(l9x3(root))
    d.add_factor("Pressure Range (barA)", label="Pressure")
    for i, r in enumerate(d.rows):
        d.set_value(r, "wb:Pressure Range (barA)", 1.0 + i / 10)
    assert any("really a factor" in f.text for f in dz.diagnose(d))


# ---- rebasing on a changed selection ------------------------------------------------------------------------------

def test_edits_survive_a_change_of_selection(root):
    runs = l9x3(root)
    d = dz.detect(runs)
    d.rename_factor("sps", "Silicone flow")
    d.add_factor("GLR")
    d.rows[0].included = False
    d.set_value(d.rows[1], "rpm", 999)
    kept = d.rows[1].path
    d.update_runs(runs[:20])                          # fewer runs selected
    assert len(d.rows) == 20 and d.factor("sps").label == "Silicone flow" and d.has("wb:GLR")
    assert d.rows[0].included is False and d.rows[1].overrides == {"rpm": 999}
    d.update_runs(runs)                               # back to all 27: new rows are detected fresh
    assert len(d.rows) == 27 and d.rows[1].path == kept and d.rows[1].overrides == {"rpm": 999}
    assert d.rows[25].included and not d.rows[25].overrides


def test_uncustomised_factors_are_redetected_when_the_selection_changes(root):
    runs = l9x3(root)
    d = dz.detect(runs[:1])                           # one run: nothing varies -> usual three
    assert [f.key for f in d.factors] == ["sccm", "rpm", "sps"]
    d.update_runs(runs)
    assert [f.key for f in d.factors] == ["sccm", "rpm", "sps"] and not d.customised


# ---- persistence ------------------------------------------------------------------------------------------------------------

def test_save_load_round_trip_restores_every_edit(root):
    runs = l9x3(root)
    d = dz.detect(runs)
    d.rename_factor("sps", "Silicone flow")
    d.add_factor("Flow Range (sccm)", pick="min")
    d.rows[3].included = False
    d.set_value(d.rows[4], "rpm", 450)
    path = dz.save(d, root / "out")
    assert path == root / "out" / "taguchi_design.json" and json.loads(path.read_text())["schema"] == 1
    assert [p.name for p in (root / "out").iterdir()] == ["taguchi_design.json"]     # no temp litter

    fresh = dz.detect(runs)
    notes = fresh.apply_saved(dz.load_saved(root / "out"))
    assert notes == []
    assert fresh.factor("sps").label == "Silicone flow" and fresh.has("wb:Flow Range (sccm)")
    assert fresh.factor("wb:Flow Range (sccm)").pick == "min"
    assert fresh.rows[3].included is False and fresh.rows[4].overrides == {"rpm": 450}
    assert fresh.to_dict() == d.to_dict()


def test_loading_matches_runs_by_path_and_reports_the_ones_that_are_gone(root):
    runs = l9x3(root)
    d = dz.detect(runs)
    d.rows[0].included = False
    dz.save(d, root / "out")
    fresh = dz.detect(runs[1:])                       # the first run is no longer selected
    notes = fresh.apply_saved(dz.load_saved(root / "out"))
    assert any("1 run(s) in the saved design are not in the current selection" in n for n in notes)
    assert all(r.included for r in fresh.rows)


def test_a_workbook_factor_nobody_has_any_more_is_reported(root):
    runs = l9x3(root)
    d = dz.detect(runs)
    d.add_factor("GLR")
    dz.save(d, root / "out")
    stripped = runs_of(root / "other", [(n, "x") for n, _, _ in fakes.REAL_10_05[:3]],
                       omit=("GLR",))
    fresh = dz.detect(stripped)
    notes = fresh.apply_saved(dz.load_saved(root / "out"))
    assert any("none of the selected runs has a 'GLR' field" in n for n in notes)


def test_a_corrupt_or_foreign_saved_design_is_ignored_safely(root):
    d = dz.detect(l9x3(root))
    (root / "out").mkdir()
    (root / "out" / "taguchi_design.json").write_text("{not json")
    assert dz.load_saved(root / "out") is None
    assert dz.load_saved(root / "nowhere") is None
    assert "different version" in d.apply_saved({"schema": 99})[0]
    assert "different version" in d.apply_saved(None)[0]


# ---- real data, read-only ------------------------------------------------------------------------------------------------------

@needs_lacie
def test_real_10_05_is_a_confirmed_9x3():
    runs = rd.load_runs(rd.find_runs([REAL_DAY]).runs, check_reuse=False)
    d = dz.detect(runs)
    a = dz.assign(d)
    assert [f.key for f in d.factors] == ["sccm", "rpm", "sps"]
    assert a.counts() == {dz.AGREE: 27} and len(a.conditions) == 9
    assert sorted(c.label for c in a.conditions) == sorted(f"T{i}" for i in range(1, 10))
    assert dz.headline(d, a)[1] == "ok" and {f.level for f in dz.diagnose(d)} == {"ok"}


@needs_lacie
@pytest.mark.skipif(not REAL_01.is_dir(), reason="10/01 not present")
def test_real_10_01_flags_its_two_side_runs_and_is_clean_without_them():
    runs = rd.load_runs(rd.find_runs([REAL_01]).runs, check_reuse=False)
    d = dz.detect(runs)
    stray = dz.outside_design(d)
    assert sorted(r.time for r in stray) == ["101035", "120606"]
    for r in stray:
        r.included = False
    a = dz.assign(d)
    assert a.counts()[dz.AGREE] == 9 and len(a.conditions) == 9
    assert not any(f.level == "error" for f in dz.diagnose(d))
    assert any("No replicates" in f.text for f in dz.diagnose(d))      # one run per condition


@needs_lacie
@pytest.mark.skipif(not REAL_01.is_dir(), reason="10/01 not present")
def test_real_both_days_agree_that_the_conditions_are_the_same_nine():
    runs = rd.load_runs(rd.find_runs([REAL_01, REAL_DAY]).runs, check_reuse=False)
    d = dz.detect(runs)
    for r in dz.outside_design(d):
        r.included = False
    a = dz.assign(d)
    assert len(a.conditions) == 9 and {len(c.rows) for c in a.conditions} == {4}
    assert a.counts() == {dz.AGREE: 36, dz.DROPPED: 2}
    assert any("2 different days" in f.text for f in dz.diagnose(d))
