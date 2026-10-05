"""output_tree.py -- the model behind the right-hand "what will be created" tree.

No Qt in here. The tree is DERIVED from pipeline_spec.OUTPUTS, and the tick
state maps to pipeline options only through pipeline_spec.resolve_options(), so
the tree cannot offer a control the pipeline lacks or show a file the run will
not make. tests/test_output_tree.py asserts that for every option combination:
the files the tree shows as "will be created" are exactly
pipeline_spec.active_outputs(options).

Five node states:
    group       a folder or heading -- no tick
    locked_on   mandatory and produced: a grey, un-clickable tick
    superseded  mandatory but NOT produced under the current options: grey, no tick.
                (The extreme-frame images are always made, except that "every
                frame" replaces them -- showing a tick there would be a lie.)
    on / off    optional, user-controlled
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from . import pipeline_spec as spec

GROUP, LOCKED_ON, SUPERSEDED, ON, OFF = "group", "locked_on", "superseded", "on", "off"
TICKED = (LOCKED_ON, ON)

# Folders the run-scope outputs are shown under. DISPLAY structure only: every
# name and path still comes from pipeline_spec. Longest prefix wins.
_RAW = "shadowgraph/raw"
_AN = "shadowgraph/analysis"


@dataclass
class Node:
    key: str
    label: str
    detail: str = ""
    state: str = GROUP
    output_id: str | None = None
    children: list["Node"] = field(default_factory=list)

    def walk(self) -> Iterator["Node"]:
        yield self
        for c in self.children:
            yield from c.walk()


def walk_all(roots: list[Node]) -> Iterator[Node]:
    for r in roots:
        yield from r.walk()


# ---- tick handling ------------------------------------------------------------

def toggle(ticks: set[str], output_id: str, checked: bool) -> set[str]:
    """New tick set after the user (un)ticks `output_id`.

    Outputs that feed ONE option are linked: the "every frame" boxes under
    droplets_ and liquid_ are two displays of the single `images` option (it
    reaches both stages), so ticking either ticks both. A mandatory output cannot
    be toggled -- it is returned unchanged.
    """
    out = spec.OUTPUTS_BY_ID.get(output_id)
    if out is None or out.mandatory or out.option is None:
        return set(ticks)
    linked = {o.id for o in spec.OUTPUTS
              if o.option == out.option and o.option_value == out.option_value}
    return (set(ticks) | linked) if checked else (set(ticks) - linked)


# ---- building -------------------------------------------------------------------

def _names(thr: float) -> dict[str, str]:
    return {"meas": spec.MEAS_DIR.format(thr=thr), "clas": spec.CLAS_DIR.format(thr=thr)}


def _detail(out: spec.Output, state: str, n_frames: int | None) -> str:
    if state == SUPERSEDED:
        return "not made: replaced by the every-frame images"
    parts = []
    if out.count == "n_frames":
        parts.append(f"{n_frames} files" if n_frames else "one per frame")
    if out.note:
        parts.append(out.note)
    return " · ".join(parts)


def build_tree(ticks: set[str], *, run_name: str | None = None, thr: float | None = None,
               n_runs: int = 0, output_dir: str | None = None,
               n_frames: int | None = None) -> list[Node]:
    """Two roots: ONE example run folder, and the chosen output folder.

    `ticks` is the user's tick state; what is shown is derived from the OPTIONS
    those ticks resolve to, so linked boxes always agree with each other.
    """
    s = spec.effective(spec.RunSettings(score_thresh=thr))
    names = _names(s.score_thresh)
    options = spec.resolve_options(ticks)
    active = {o.id for o in spec.active_outputs(options)}

    def leaf(o: spec.Output) -> Node:
        if o.id in active:
            state = LOCKED_ON if o.mandatory else ON
        else:
            state = SUPERSEDED if o.mandatory else OFF
        return Node(key=o.id, label=o.label, detail=_detail(o, state, n_frames),
                    state=state, output_id=o.id)

    # ---- the run folder ------------------------------------------------------
    raw = Node("grp:raw", f"{_RAW}/")
    an = Node("grp:analysis", f"{_AN}/")
    meas = Node("grp:meas", f"{names['meas']}/")
    clas = Node("grp:clas", f"{names['clas']}/")
    by_prefix = ((f"{_AN}/{names['meas']}/", meas), (f"{_AN}/{names['clas']}/", clas),
                 (f"{_RAW}/", raw), (f"{_AN}/", an))
    for o in spec.OUTPUTS:
        if o.scope != "run":
            continue
        path = o.path.format(**names)
        node = leaf(o)
        for prefix, group in by_prefix:
            if path.startswith(prefix):
                node.label = o.label        # contract labels are already relative to the group
                group.children.append(node)
                break
        else:
            raise AssertionError(f"output '{o.id}' ({path}) fits no display group; "
                                 f"add one to output_tree.build_tree")
    an.children += [meas, clas]

    shown = run_name or "<HHMMSS>_<flow>sccm_<rpm>rpm_<sps>sps_or<x>_bh<n>"
    where = (f"created identically in each of {n_runs} run folders" if n_runs > 1
             else "created in the run folder" if n_runs == 1 else "select runs to see how many")
    run_root = Node("root:run", f"ONE RUN FOLDER  —  {shown}", where, GROUP,
                    children=[raw, an])

    # ---- the output folder -----------------------------------------------------
    out_root = Node("root:out", f"OUTPUT FOLDER  —  {output_dir or '(choose an output folder)'}",
                    "reports, figures and the workbook go here; never into the run folders",
                    GROUP, children=[leaf(o) for o in spec.OUTPUTS if o.scope == "campaign"])
    return [run_root, out_root]


def states(roots: list[Node]) -> dict[str, str]:
    """{output_id: state} for every output leaf."""
    return {n.output_id: n.state for n in walk_all(roots) if n.output_id}


def created_ids(roots: list[Node]) -> set[str]:
    """What the tree says WILL be created (ticked, locked or not)."""
    return {n.output_id for n in walk_all(roots) if n.output_id and n.state in TICKED}


# ---- cost ------------------------------------------------------------------------

# MEASURED 2026-10-05 on /Volumes/LaCie/Experiments/2026/10/01/104852_..._bh1
# (497 frames, stride 10), by `du`:
#     raw/frames/8bit 746 MB + raw/frames/16bit 2.3 GB + background 9 MB + predictions 15 MB
#     analysis/measurement_0.30 (497 flat PNGs) 2.1 GB + classical_0.30/images 2.1 GB
# Everything scales with frame count; the figures are per 497 frames.
_REF_FRAMES = 497
BASE_GB_PER_RUN = 3.1
EVERY_FRAME_EXTRA_GB_PER_RUN = 4.2
# NOT measured, and NOT portable. docs/HANDOFF_real_data_pipeline.md (line 1716):
# "Drawing all images is ~70-80% of the measure and classical stages (estimated from
# earlier no-image timings, not measured here) -- ~10-13 min per run", recorded on the
# Windows PC. It is dominated by writing ~1,000 PNGs to the LaCie, and the same
# section records that write speed on that PC went from 6.8 s per image (2026-09-24) to
# 0.4-0.5 s later: a 15x swing from the drive/interface alone. So this is a rough
# order of magnitude for ONE machine, not a prediction for another. Phase 5 (eta.py)
# replaces it with this machine's own measured rate after the first run.
EVERY_FRAME_EXTRA_MIN_PER_RUN = (10, 13)
RECORDED_ON = "the Windows PC it was recorded on"


def _gb(x: float) -> str:
    return f"{x:,.0f} GB" if x >= 10 else f"{x:.1f} GB"


def cost_note(options: dict[str, Any], n_runs: int, n_frames: int | None = None,
              machine: str | None = None) -> str:
    """Disk, and (for "every frame" only) a rough time, with provenance on each number.

    This is NOT a prediction of how long a batch will take: it covers only what
    the "every frame" option adds. The real per-machine ETA is Phase 5's job.
    Disk is the same on any OS (same files); time is not.
    """
    scale = (n_frames / _REF_FRAMES) if n_frames else 1.0
    base = BASE_GB_PER_RUN * scale
    lines = [f"Disk written into each run folder: about {_gb(base)}"
             + (f" ({_gb(base * n_runs)} for {n_runs} runs)" if n_runs > 1 else "")
             + " \u2014 frames, predictions and results."]
    if options.get("images") == "all":
        extra = EVERY_FRAME_EXTRA_GB_PER_RUN * scale
        lo, hi = EVERY_FRAME_EXTRA_MIN_PER_RUN
        t = f"{lo}\u2013{hi} min per run"
        if n_runs > 1:
            t += f" ({lo * n_runs / 60:.1f}\u2013{hi * n_runs / 60:.1f} h for {n_runs} runs)"
        here = {"Darwin": "this Mac", "Windows": "this PC"}.get(machine or "", "this machine")
        lines.append(f"\u201cEvery frame\u201d adds about {_gb(extra)} per run"
                     + (f" ({_gb(extra * n_runs)} for {n_runs} runs)" if n_runs > 1 else "")
                     + f" and, very roughly, {t} on {RECORDED_ON} (an estimate, not measured; "
                       f"mostly image-write speed to the LaCie). Not known for {here}.")
    else:
        lines.append("Extreme frames only: a few PNGs per run. Tick \u201cevery frame\u201d "
                     "only if you need every frame drawn.")
    if n_frames is None:
        lines.append("Sizes are per 497 frames (measured on one real run); the frame count "
                     "of a new run is not known until its cine is extracted.")
    return "\n".join(lines)
