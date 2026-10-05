"""Tests for the output-tree model. The headline test is the first one: for EVERY
option combination, the tree's "will be created" set equals what the pipeline
contract says will exist. If that holds, the tree cannot lie."""
from __future__ import annotations

import pytest

from src.ai.Taguchi_Analysis_UI import output_tree as ot
from src.ai.Taguchi_Analysis_UI import pipeline_spec as spec

COMBOS = spec.all_option_combinations()


def tree_for(options, **kw):
    return ot.build_tree(spec.ticks_for(options), **kw)


@pytest.mark.parametrize("options", COMBOS, ids=lambda o: f"img={o['images']},csv={o['flat_csvs']},odd={o['odd_pack']}")
def test_the_tree_shows_exactly_what_the_contract_will_create(options):
    roots = tree_for(options)
    assert ot.created_ids(roots) == {o.id for o in spec.active_outputs(options)}


@pytest.mark.parametrize("options", COMBOS)
def test_ticks_read_back_from_the_tree_resolve_to_the_same_options(options):
    roots = tree_for(options)
    ticks = {i for i, s in ot.states(roots).items() if s in ot.TICKED}
    assert spec.resolve_options(ticks) == options


@pytest.mark.parametrize("options", COMBOS)
def test_every_output_appears_exactly_once(options):
    seen = [n.output_id for n in ot.walk_all(tree_for(options)) if n.output_id]
    assert sorted(seen) == sorted(o.id for o in spec.OUTPUTS)


def test_mandatory_outputs_are_locked_and_optional_ones_are_not():
    st = ot.states(ot.build_tree(spec.default_ticks()))
    for o in spec.OUTPUTS:
        if o.mandatory:
            assert st[o.id] in (ot.LOCKED_ON, ot.SUPERSEDED), o.id
        else:
            assert st[o.id] in (ot.ON, ot.OFF), o.id


def test_defaults_show_extremes_locked_and_every_frame_off():
    st = ot.states(ot.build_tree(spec.default_ticks()))
    assert st["meas_extremes"] == st["clas_extremes"] == ot.LOCKED_ON
    assert st["meas_all"] == st["clas_all"] == ot.OFF
    assert st["flat_csvs"] == st["odd_pack"] == ot.OFF


def test_every_frame_supersedes_the_mandatory_extremes_rather_than_lying():
    st = ot.states(ot.build_tree(spec.default_ticks() | {"meas_all", "clas_all"}))
    assert st["meas_all"] == st["clas_all"] == ot.ON
    assert st["meas_extremes"] == st["clas_extremes"] == ot.SUPERSEDED     # not ticked, not made
    assert {i for i, s in st.items() if s == ot.SUPERSEDED} == {"meas_extremes", "clas_extremes"}


def test_ticking_only_one_every_frame_box_still_displays_both_consistently():
    # a half-linked tick set must not display half-linked: it derives from the options
    st = ot.states(ot.build_tree(spec.default_ticks() | {"clas_all"}))
    assert st["meas_all"] == st["clas_all"] == ot.ON


def test_toggle_links_the_two_every_frame_boxes_both_ways():
    t = spec.default_ticks()
    on = ot.toggle(t, "meas_all", True)
    assert {"meas_all", "clas_all"} <= on
    off = ot.toggle(on, "clas_all", False)
    assert not ({"meas_all", "clas_all"} & off)
    assert off == t


def test_toggle_ignores_mandatory_and_unknown_outputs():
    t = spec.default_ticks()
    assert ot.toggle(t, "droplet_sizes", False) == t
    assert ot.toggle(t, "meas_extremes", False) == t
    assert ot.toggle(t, "no_such_output", True) == t
    assert ot.toggle(t, "report_md", False) == t


def test_toggle_does_not_mutate_its_input_and_is_idempotent():
    t = spec.default_ticks()
    snapshot = set(t)
    a = ot.toggle(t, "flat_csvs", True)
    assert t == snapshot and ot.toggle(a, "flat_csvs", True) == a
    assert "flat_csvs" in a and "odd_pack" not in a


def test_folder_names_follow_the_score_threshold():
    labels = [n.label for n in ot.walk_all(ot.build_tree(spec.default_ticks(), thr=0.45))]
    assert "droplets_0.45/" in labels and "liquid_0.45/" in labels
    assert "droplets_0.30/" not in labels


def test_default_threshold_comes_from_the_live_pipeline_default():
    labels = [n.label for n in ot.walk_all(ot.build_tree(spec.default_ticks()))]
    live = spec.effective(spec.RunSettings()).score_thresh
    assert f"droplets_{live:.2f}/" in labels


def test_leaves_sit_under_the_folder_their_path_says():
    roots = ot.build_tree(spec.default_ticks(), thr=0.30)
    parent = {}
    for n in ot.walk_all(roots):
        for c in n.children:
            parent[c.key] = n
    expect = {"frames_8bit": "shadowgraph/raw/", "background": "shadowgraph/raw/",
              "predictions": "shadowgraph/analysis/", "droplet_sizes": "droplets_0.30/",
              "meas_extremes": "droplets_0.30/", "classical_summary": "liquid_0.30/",
              "clas_extremes": "liquid_0.30/", "clas_all": "liquid_0.30/",
              "report_md": None}
    for oid, group in expect.items():
        if group is None:
            assert parent[oid].key == "root:out"
        else:
            assert parent[oid].label == group, oid


def test_run_and_output_headings_describe_the_selection():
    none = ot.build_tree(spec.default_ticks())
    assert "select runs" in none[0].detail and "(choose an output folder)" in none[1].label
    one = ot.build_tree(spec.default_ticks(), run_name="090432_x", n_runs=1)
    assert "090432_x" in one[0].label and "in the run folder" in one[0].detail
    many = ot.build_tree(spec.default_ticks(), run_name="090432_x", n_runs=27,
                         output_dir="/tmp/out")
    assert "each of 27 run folders" in many[0].detail and "/tmp/out" in many[1].label


def test_known_frame_count_replaces_one_per_frame():
    detail = lambda roots: next(n.detail for n in ot.walk_all(roots) if n.key == "frames_8bit")
    assert "one per frame" in detail(ot.build_tree(spec.default_ticks()))
    assert "497 files" in detail(ot.build_tree(spec.default_ticks(), n_frames=497))


# ---- cost note ------------------------------------------------------------------

def test_cost_note_extremes_has_disk_but_no_time_claim():
    text = ot.cost_note({"images": "extremes"}, 27)
    assert "3.1 GB" in text and "84 GB for 27 runs" in text
    assert "min per run" not in text                    # it is NOT an overall time estimate


def test_cost_note_every_frame_adds_disk_and_a_labelled_estimate():
    text = ot.cost_note({"images": "all"}, 27, machine="Darwin")
    assert "4.2 GB per run" in text and "113 GB for 27 runs" in text
    assert "10–13 min per run" in text and "4.5–5.8 h for 27 runs" in text
    assert "not measured" in text and "Windows PC" in text
    assert "Not known for this Mac" in text


def test_cost_note_names_the_machine_without_assuming():
    assert "Not known for this PC" in ot.cost_note({"images": "all"}, 3, machine="Windows")
    assert "Not known for this machine" in ot.cost_note({"images": "all"}, 3, machine="Linux")
    assert "Not known for this machine" in ot.cost_note({"images": "all"}, 3)


def test_cost_note_scales_disk_with_frame_count_and_drops_the_caveat():
    half = ot.cost_note({"images": "extremes"}, 1, n_frames=248)
    assert "1.5 GB" in half and "Sizes are per 497 frames" not in half
    assert "Sizes are per 497 frames" in ot.cost_note({"images": "extremes"}, 1)


def test_cost_note_single_run_has_no_totals():
    text = ot.cost_note({"images": "all"}, 1)
    assert "for 1 runs" not in text and "for 27 runs" not in text
