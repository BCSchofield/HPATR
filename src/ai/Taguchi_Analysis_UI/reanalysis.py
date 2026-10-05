"""reanalysis.py -- what to do with runs that ALREADY have results. No Qt in here.

Selecting runs never computes anything; only "Run batch" does. But when some selected
runs have already been analysed, the user has to be able to say what they want:

    skip       Use their existing results. Nothing is re-run for them (the default: a
               batch must never silently redo hours of work). The statistics read these
               results as they are; only runs that still need work are processed.
    remeasure  Re-run droplet measurement + classical liquid (cheap, minutes), keeping the
               extracted frames and the AI predictions. For a new measure_run /
               classical_liquid version.
    redo       Redo everything, including frame extraction and the AI (hours). For a new
               model or a changed inference script: the app notices a newer MODEL by itself
               (process_capture.can_reuse), but it cannot tell that tiled_inference.py has
               changed, so this is the way to say so.

The SELECTION is what the analysis covers; the MODE is only what compute is needed to
get there. A run left as-is is still analysed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import pipeline_spec as spec
from . import run_discovery as rd

SKIP, REMEASURE, REDO = "skip", "remeasure", "redo"
DEFAULT_MODE = SKIP
MODES = (
    (SKIP, "Use their existing results (don't re-run them)"),
    (REMEASURE, "Re-measure only (keep frames + AI predictions)"),
    (REDO, "Redo everything, including the AI"),
)
MODE_LABEL = dict(MODES)


@dataclass
class Plan:
    mode: str
    process: list[rd.RunInfo] = field(default_factory=list)      # what the batch will run
    skipped: list[rd.RunInfo] = field(default_factory=list)      # have results; left as they are
    cannot: list[rd.RunInfo] = field(default_factory=list)       # have results, no cine to re-run

    @property
    def reuse(self) -> bool:
        return self.mode != REDO

    @property
    def new(self) -> list[rd.RunInfo]:
        """Never fully analysed: the whole chain runs (a half-measured run counts here
        too, but may still reuse its frames and predictions)."""
        return [r for r in self.process if not r.analysis.measured]

    @property
    def remeasured(self) -> list[rd.RunInfo]:
        return [r for r in self.process if r.analysis.measured]

    @property
    def keep_ai(self) -> list[rd.RunInfo]:
        """Re-measured runs whose frames + AI predictions are still valid and will be reused."""
        if self.mode == REDO:
            return []
        return [r for r in self.remeasured if r.analysis.reusable]

    @property
    def redo_ai(self) -> list[rd.RunInfo]:
        """Re-measured runs whose AI will be run again: asked for, or their frames and
        predictions are missing, partial, from a different stride, or older than the model."""
        if self.mode == REDO:
            return self.remeasured
        return [r for r in self.remeasured if not r.analysis.reusable]


def has_results(run: rd.RunInfo) -> bool:
    return run.analysis.measured


def plan_runs(runs: list[rd.RunInfo], mode: str = DEFAULT_MODE) -> Plan:
    """Split the selected runs into: to process / left as they are / cannot be re-run."""
    if mode not in dict(MODES):
        raise ValueError(f"unknown mode {mode!r}")
    plan = Plan(mode)
    for r in runs:
        if has_results(r) and mode == SKIP:
            plan.skipped.append(r)
        elif r.runnable:
            plan.process.append(r)
        elif has_results(r):
            plan.cannot.append(r)           # re-run requested, but the .cine is not here
    return plan


def settings_for(mode: str, base: spec.RunSettings) -> spec.RunSettings:
    """`reuse` is how the pipeline is told to keep extraction + inference when
    process_capture.can_reuse() says they are still valid; "redo" turns it off."""
    return replace(base, reuse=(mode != REDO))


def describe(plan: Plan) -> list[str]:
    """Plain-language lines for the confirmation dialog."""
    out = []
    if plan.new:
        out.append(f"{len(plan.new)} run(s) have no complete results: the full chain runs "
                   f"(including the AI where it has not been done).")
    if plan.keep_ai:
        out.append(f"{len(plan.keep_ai)} run(s) already have results and will be re-measured; "
                   f"their frames and AI predictions are reused.")
    if plan.redo_ai:
        why = ("you chose to redo everything" if plan.mode == REDO else
               "their frames or predictions are missing, partial, from a different stride, or "
               "older than the model")
        out.append(f"{len(plan.redo_ai)} run(s) already have results and the AI will be run again "
                   f"({why}). This is the slow part; expect hours on a CPU.")
    if plan.skipped:
        out.append(f"{len(plan.skipped)} run(s) already have results and are left as they are "
                   f"(the analysis still uses them).")
    if plan.cannot:
        out.append(f"{len(plan.cannot)} run(s) have results but no .cine here, so they cannot be "
                   f"re-run and are left as they are.")
    if plan.mode == REDO and plan.remeasured:
        out.append("Redoing everything also re-extracts the frames: the old frames are replaced.")
    return out
