"""pipeline_spec.py -- THE contract between this app and AI/Real_Data_Code.

Everything this app believes about the measurement pipeline is declared in
this one module: which functions it calls and with which parameter names,
which CLI flags it passes, which folders and files each stage writes, and
which user-facing options change any of that. No other module in the app
names a pipeline flag or an output folder.

The declarations are then VERIFIED against the live scripts by
`preflight()`. If the pipeline changes in a way that breaks a declaration --
a renamed flag, a removed parameter, a new required argument -- preflight
reports exactly which one, and the batch is disabled. The app never adapts,
guesses or falls back. That is what makes "always use the most recent
pipeline" safe: the app always RUNS the latest code (it imports and invokes
the canonical scripts; it copies none of their logic), and it refuses to
run code whose interface no longer matches what it was built against.

Every fact below was checked against the source, not the docstrings. Two
docstrings in the pipeline were found to be stale while writing this:
process_capture.py's header still says `measurement_<thr>` (the code writes
`droplets_<thr>`, line 326), and classical_liquid.py's --images-mode help
says extremes draws "4 frames" (the code draws 1-2, line 487).

stdout TEXT is deliberately NOT part of this contract. Progress parsing is
best-effort: a format change degrades a progress bar, it never fails a run.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import importlib
import inspect
import io
import itertools
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable

from . import paths

# ============================================================================
# FOLDER NAMES
# ============================================================================
# Written by process_capture.py:326 -- `analysis / f"droplets_{score_thresh:.2f}"`.
MEAS_DIR = "droplets_{thr:.2f}"
# NOT chosen by classical_liquid.py (its own default is the legacy
# `skeletonisation_testing`). This is the canonical CALLER's convention,
# batch_runs.py:86, also used by the capture GUI. We always pass it.
CLAS_DIR = "liquid_{thr:.2f}"
# Read-only: runs measured before 2026-10-05 carry these. Never written.
LEGACY_MEAS_DIR = "measurement_{thr:.2f}"
LEGACY_CLAS_DIR = "classical_{thr:.2f}"

# The chain's scripts, hashed into every report and job so a result can be
# traced to the exact code that produced it.
CHAIN_SCRIPTS = (
    "process_capture.py", "cine_extract.py", "extract_candidates.py",
    "tiled_inference.py", "measure_run.py", "classical_liquid.py",
    "taguchi_analysis.py", "_fsutil.py",
)

# ============================================================================
# INVOCATIONS -- the surface preflight verifies
# ============================================================================


@dataclass(frozen=True)
class ImportCall:
    """A function this app imports from AI/Real_Data_Code and calls.
    `params` are the parameter names the app passes -- preflight checks each
    exists, and that the function has gained no new REQUIRED parameter."""
    module: str
    func: str
    params: tuple[str, ...]

    @property
    def name(self) -> str:
        return f"{self.module}.{self.func}"


@dataclass(frozen=True)
class ScriptCall:
    """A script this app runs as a subprocess. `flags` are every flag the app
    passes; `choices` are the values it may pass to a choice-restricted flag.
    Preflight checks both against `python <script> --help`."""
    script: str
    flags: tuple[str, ...]
    choices: tuple[tuple[str, tuple[str, ...]], ...] = ()


# Stages 1-4 (extract, background, inference, measurement): ONE call into the
# documented single entry point. Signature at process_capture.py:190.
PROCESS_CAPTURE = ImportCall(
    "process_capture", "process_capture",
    ("cine", "run_dir", "stride", "score_thresh", "device", "model_dir",
     "images", "ci_stride", "bg_frames", "limit", "reuse", "log"),
)

# Stage 5. Invoked exactly as the canonical caller does (batch_runs.py:87-96).
# --root and --out-dir are ALWAYS passed: classical_liquid.py:368 defaults
# --root to a real run (2026/09/28/Trial_1), so omitting it would silently
# analyse -- and write into -- the wrong run. `classical_cmd()` enforces it
# and tests/test_pipeline_spec.py asserts it.
CLASSICAL = ScriptCall(
    "classical_liquid.py",
    ("--root", "--out-dir", "--score-thresh", "--images-mode"),
    (("--images-mode", ("extremes", "all")),),
)

# Other functions the app calls directly. Each must exist with these names.
HELPERS = (
    ImportCall("process_capture", "can_reuse", ("run_dir", "stride", "model_dir")),
    ImportCall("process_capture", "previous_analysis", ("run_dir",)),
    ImportCall("process_capture", "auto_ci_stride", ("fps", "stride")),
    # Private, but reused ON PURPOSE: it is the canonical streaming runner
    # (sets PYTHONUNBUFFERED, merges stderr, raises on non-zero). batch_runs
    # uses capture_output=True, which streams nothing. Importing it rather
    # than copying means a future fix there (e.g. a timeout) is inherited.
    ImportCall("process_capture", "_run", ("cmd", "log")),
    ImportCall("process_capture", "_fmt_dur", ("seconds",)),
    ImportCall("taguchi_analysis", "load_run", ("run", "thr")),
    ImportCall("taguchi_analysis", "pooled_responses",
               ("dia_by_frame", "frames", "S3", "S2", "DP", "TP")),
    ImportCall("taguchi_analysis", "bootstrap", ("r", "rng")),
    ImportCall("taguchi_analysis", "level_table", ("runs", "values", "factor")),
    ImportCall("taguchi_analysis", "flag_odd", ("runs", "timings", "out")),
    ImportCall("taguchi_analysis", "load_timings", ("paths",)),
    ImportCall("_fsutil", "list_files", ("directory", "pattern")),
)

# Module-level values the app reads (defaults, response tables). Read LIVE --
# never copied as literals -- so an upstream change to a default is picked up
# with no edit here.
CONSTANTS = (
    ("process_capture", "DEFAULT_SCORE_THRESH"),
    ("process_capture", "DEFAULT_STRIDE"),
    ("process_capture", "BG_FRAMES"),
    ("taguchi_analysis", "RESPONSES"),
    ("taguchi_analysis", "RESP_KEYS"),
    ("taguchi_analysis", "SN_SIGN"),
    ("taguchi_analysis", "N_BOOT"),
    ("taguchi_analysis", "SEED"),
    ("taguchi_analysis", "MIN_DISTINCT"),
    ("taguchi_analysis", "EMPTY_FRAC"),
)

# ============================================================================
# STAGES -- display and timing units
# ============================================================================


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    via: str                 # "process_capture" | "classical_liquid"
    timing_key: str | None   # key in process_capture's summary["_stage_seconds"]
    note: str = ""


# timing_key values are the `_Stage("...")` names in process_capture.py
# (lines 278, 290, 299, 311, 337). Stages skipped on reuse are simply absent
# from _stage_seconds. ETA priors are owned by eta.py, not declared here: this
# module is the contract, not an estimate.
STAGES = (
    Stage("copy_cine", "Copy cine", "process_capture", "copy cine",
          "only when the .cine lives outside the run folder"),
    Stage("extract", "Extract frames", "process_capture", "extract frames"),
    Stage("background", "Background", "process_capture", "background"),
    Stage("inference", "Inference", "process_capture", "inference"),
    Stage("measurement", "Measurement", "process_capture", "measurement"),
    Stage("classical", "Classical liquid", "classical_liquid", None),
)
TIMING_KEYS = frozenset(s.timing_key for s in STAGES if s.timing_key)

# ============================================================================
# OPTIONS + OUTPUTS -- what will be created, and which ticks change it
# ============================================================================


@dataclass(frozen=True)
class Option:
    """A user-facing choice. Ticked outputs vote for values; the highest
    value in `precedence` with a ticked output wins; none ticked -> `when_none`."""
    id: str
    precedence: tuple
    when_none: Any


OPTIONS = (
    # Feeds BOTH process_capture(images=) and classical --images-mode, so the
    # two stages can never be told different things. The extreme-frame images
    # are MANDATORY (decided with the user, 2026-10-05): "extremes" is what you
    # get unless "every frame" is ticked, so there is deliberately no way to
    # ask for zero PNGs. (The builders still accept images=None, because
    # process_capture does.)
    Option("images", ("all",), "extremes"),
    Option("flat_csvs", (True,), False),
    Option("odd_pack", (True,), False),
)
OPTIONS_BY_ID = {o.id: o for o in OPTIONS}


@dataclass(frozen=True)
class Output:
    id: str
    label: str
    path: str                 # run scope: relative to the run dir; {meas}/{clas} placeholders
    scope: str                # "run" | "campaign"
    stage: str                # Stage.id, or "analysis"/"worker" for app-made outputs
    mandatory: bool           # grey locked tick
    default_on: bool = True
    kind: str = "file"        # "file" | "dir" | "glob"
    count: str | None = None  # glob only: "n_frames" or "a-b"
    option: str | None = None
    option_value: Any = None
    # (option id, allowed values): produced only under those option values.
    # A mandatory output can still be conditional -- the extremes images are
    # always made, EXCEPT that "every frame" mode replaces them (measure_run
    # then draws all frames flat; classical writes images/ not extreme_images/).
    only_when: tuple[str, tuple] | None = None
    note: str = ""


_RAW = "shadowgraph/raw"
_AN = "shadowgraph/analysis"

OUTPUTS = (
    # ---- per run: raw/ (cine_extract.py:212-382, process_capture.py:260) ----
    Output("frames_8bit", "frames/8bit/*.png", f"{_RAW}/frames/8bit/*.png", "run",
           "extract", True, kind="glob", count="n_frames", note="pinned-window PNGs the model sees"),
    Output("frames_16bit", "frames/16bit/*.tiff", f"{_RAW}/frames/16bit/*.tiff", "run",
           "extract", True, kind="glob", count="n_frames", note="native TIFFs, measured from"),
    Output("instances_json", "instances.json", f"{_RAW}/instances.json", "run", "extract", True),
    Output("extraction_metadata", "extraction_metadata.json",
           f"{_RAW}/extraction_metadata.json", "run", "extract", True),
    Output("frame_runs_json", "frame_runs.json", f"{_RAW}/frame_runs.json", "run", "extract", True),
    Output("background", "background_median.tiff", f"{_RAW}/background_median.tiff", "run",
           "background", True, note="~9 MB"),
    # ---- per run: analysis/ ----
    Output("predictions", "predictions.json", f"{_AN}/predictions.json", "run",
           "inference", True, note="~15 MB"),
    Output("droplet_sizes", "droplet_sizes.csv", f"{_AN}/{{meas}}/droplet_sizes.csv", "run",
           "measurement", True),
    Output("object_areas", "object_areas.csv", f"{_AN}/{{meas}}/object_areas.csv", "run",
           "measurement", True),
    Output("per_frame", "per_frame.csv", f"{_AN}/{{meas}}/per_frame.csv", "run",
           "measurement", True),
    Output("meas_summary", "summary.json", f"{_AN}/{{meas}}/summary.json", "run",
           "measurement", True),
    Output("meas_hist", "size_histograms.png", f"{_AN}/{{meas}}/size_histograms.png", "run",
           "measurement", True, note="always written"),
    # measure_run.py:950-965 -- FLAT in the folder, no subfolder, up to 6
    # de-duplicated frames (raw D32 lo/hi, sparse-guarded D32 lo/hi, atomised lo/hi).
    Output("meas_extremes", "frame_*.png  extreme frames (flat)",
           f"{_AN}/{{meas}}/frame_*.png", "run", "measurement", True,
           kind="glob", count="1-6", only_when=("images", ("extremes",)),
           note="1-6 PNGs: D32 + atomised extremes (included in 'every frame' if ticked)"),
    Output("meas_all", "frame_*.png  EVERY frame (flat)",
           f"{_AN}/{{meas}}/frame_*.png", "run", "measurement", False, default_on=False,
           kind="glob", count="n_frames", option="images", option_value="all",
           note="one PNG per frame -- slow"),
    Output("classical_summary", "classical_summary.json",
           f"{_AN}/{{clas}}/classical_summary.json", "run", "classical", True),
    Output("classical_per_frame", "classical_per_frame.csv",
           f"{_AN}/{{clas}}/classical_per_frame.csv", "run", "classical", True),
    Output("classical_components", "classical_components.csv",
           f"{_AN}/{{clas}}/classical_components.csv", "run", "classical", True),
    Output("clas_hist", "size_histograms.png", f"{_AN}/{{clas}}/size_histograms.png", "run",
           "classical", True, note="always written"),
    # classical_liquid.py:438/487 -- extreme_images/ holds atomised lo/hi from
    # the CLASSICAL fraction (the one quoted): 2 PNGs, 1 if the same frame.
    Output("clas_extremes", "extreme_images/*.png",
           f"{_AN}/{{clas}}/extreme_images/*.png", "run", "classical", True,
           kind="glob", count="1-2", only_when=("images", ("extremes",)),
           note="1-2 PNGs: classical atomised extremes (replaced by images/ if 'every frame' is ticked)"),
    Output("clas_all", "images/*.png  EVERY frame",
           f"{_AN}/{{clas}}/images/*.png", "run", "classical", False, default_on=False,
           kind="glob", count="n_frames", option="images", option_value="all",
           note="one PNG per frame -- slow"),
    # ---- campaign: the chosen output folder (made by this app, phases 5-9) ----
    Output("report_md", "taguchi_report.md", "taguchi_report.md", "campaign", "analysis", True),
    Output("workbook", "taguchi_analysis.xlsx", "taguchi_analysis.xlsx", "campaign",
           "analysis", True),
    Output("figures", "figures/  (png + svg)", "figures", "campaign", "analysis", True, kind="dir"),
    Output("design_json", "taguchi_design.json", "taguchi_design.json", "campaign",
           "analysis", True),
    Output("job_dir", "_job/  (progress, logs, timings)", "_job", "campaign", "worker", True,
           kind="dir"),
    Output("flat_csvs", "csv/  flat CSVs + results JSON", "csv", "campaign", "analysis", False,
           default_on=False, kind="dir", option="flat_csvs", option_value=True),
    Output("odd_pack", "odd/  odd-frame flags + images", "odd", "campaign", "analysis", False,
           default_on=False, kind="dir", option="odd_pack", option_value=True,
           note="writes PNGs"),
)
OUTPUTS_BY_ID = {o.id: o for o in OUTPUTS}


def default_ticks() -> set[str]:
    return {o.id for o in OUTPUTS if o.mandatory or o.default_on}


def resolve_options(ticked: Iterable[str]) -> dict[str, Any]:
    """Ticked output ids -> option values. THE only path from the checkbox
    tree to pipeline flags, so the tree cannot show something the run won't do."""
    ticked = set(ticked)
    out = {}
    for opt in OPTIONS:
        voted = {o.option_value for o in OUTPUTS
                 if o.option == opt.id and o.id in ticked}
        out[opt.id] = next((v for v in opt.precedence if v in voted), opt.when_none)
    return out


def default_options() -> dict[str, Any]:
    return resolve_options(default_ticks())


def ticks_for(options: dict[str, Any]) -> set[str]:
    """The canonical tick set that reproduces `options` (the inverse of
    resolve_options; used to repaint the tree from saved settings)."""
    ticks = {o.id for o in OUTPUTS if o.mandatory}
    for opt in OPTIONS:
        v = options.get(opt.id, opt.when_none)
        if v != opt.when_none:
            ticks |= {o.id for o in OUTPUTS if o.option == opt.id and o.option_value == v}
    return ticks


def all_option_combinations() -> list[dict[str, Any]]:
    values = [(*o.precedence, o.when_none) for o in OPTIONS]
    return [dict(zip(OPTIONS_BY_ID, combo)) for combo in itertools.product(*values)]


def active_outputs(options: dict[str, Any], scope: str | None = None) -> list[Output]:
    """Outputs that WILL exist under `options`: every mandatory one whose
    `only_when` holds, plus each optional one whose option resolved to its value."""
    def applies(o: Output) -> bool:
        if o.only_when is not None:
            opt, allowed = o.only_when
            if options.get(opt) not in allowed:
                return False
        return o.mandatory or options.get(o.option) == o.option_value

    return [o for o in OUTPUTS if (scope is None or o.scope == scope) and applies(o)]


# ============================================================================
# SETTINGS + CALL BUILDERS -- the only place the app constructs a pipeline call
# ============================================================================


@dataclass(frozen=True)
class RunSettings:
    """None means "let the pipeline decide": the kwarg is omitted, so
    process_capture's own default applies. score_thresh and stride are
    resolved eagerly by `effective()` because the app needs their values
    itself (folder names, can_reuse)."""
    score_thresh: float | None = None
    stride: int | None = None
    device: str | None = None
    model_dir: Path | None = None
    ci_stride: int | None = None
    bg_frames: int | None = None
    limit: int | None = None
    reuse: bool = False


def rdc_module(name: str):
    """Import a module from AI/Real_Data_Code."""
    paths.ensure_rdc_on_path()
    return importlib.import_module(name)


def effective(settings: RunSettings) -> RunSettings:
    """Fill score_thresh/stride from process_capture's LIVE defaults."""
    pc = rdc_module("process_capture")
    return replace(
        settings,
        score_thresh=(settings.score_thresh if settings.score_thresh is not None
                      else pc.DEFAULT_SCORE_THRESH),
        stride=settings.stride if settings.stride is not None else pc.DEFAULT_STRIDE,
    )


def meas_dir(run_dir: Path, thr: float) -> Path:
    return Path(run_dir) / _AN / MEAS_DIR.format(thr=thr)


def clas_dir(run_dir: Path, thr: float) -> Path:
    return Path(run_dir) / _AN / CLAS_DIR.format(thr=thr)


def find_cine(run_dir: Path) -> Path:
    """The run's single .cine. Exactly one, or a clear error (batch_runs.py
    refuses the same way)."""
    list_files = rdc_module("_fsutil").list_files
    cines = list_files(Path(run_dir) / _RAW / "CINE", "*.cine")
    if len(cines) != 1:
        raise ValueError(f"expected exactly one .cine in {Path(run_dir) / _RAW / 'CINE'}, "
                         f"found {len(cines)}")
    return cines[0]


def _check_declared(used: Iterable[str], declared: Iterable[str], what: str) -> None:
    undeclared = set(used) - set(declared)
    if undeclared:
        # A builder using a flag preflight never checks would defeat the contract.
        raise AssertionError(f"{what} uses undeclared {sorted(undeclared)} -- "
                             f"add them to pipeline_spec.py so preflight verifies them")


def process_capture_kwargs(run_dir: Path, settings: RunSettings, options: dict[str, Any],
                           log: Callable[[str], None], cine: Path | None = None) -> dict:
    s = effective(settings)
    kw: dict[str, Any] = {
        "cine": Path(cine) if cine else find_cine(run_dir),
        "run_dir": Path(run_dir),
        "stride": s.stride,
        "score_thresh": s.score_thresh,
        "images": options.get("images"),
        "reuse": s.reuse,
        "log": log,
    }
    for key in ("device", "model_dir", "ci_stride", "bg_frames", "limit"):
        value = getattr(s, key)
        if value is not None:
            kw[key] = value
    _check_declared(kw, PROCESS_CAPTURE.params, "process_capture_kwargs")
    return kw


def classical_cmd(run_dir: Path, settings: RunSettings, options: dict[str, Any]) -> list[str]:
    s = effective(settings)
    cmd = [sys.executable, "-W", "ignore", str(paths.RDC_DIR / CLASSICAL.script),
           "--root", str(Path(run_dir)),
           "--out-dir", str(clas_dir(run_dir, s.score_thresh)),
           # Explicit, never defaulted: classical_liquid.py has its OWN literal
           # 0.30 default. Passing process_capture's value keeps the two stages
           # (and the droplets_/liquid_ folder names) in lockstep.
           "--score-thresh", str(s.score_thresh)]
    images = options.get("images")
    if images:
        cmd += ["--images-mode", images]
    _check_declared((c for c in cmd if c.startswith("--")), CLASSICAL.flags, "classical_cmd")
    return cmd


# ============================================================================
# VIOLATIONS + RUNTIME CHECKS (used by the worker after each run)
# ============================================================================


@dataclass(frozen=True)
class Violation:
    level: str      # "error" | "warn"
    where: str
    message: str
    fix: str = ""


def check_measurement_dir(summary: dict, run_dir: Path, thr: float) -> list[Violation]:
    """process_capture RETURNS where it wrote. If that ever stops matching our
    folder name, catch it on run 1 -- not at report time eleven hours later."""
    got = summary.get("_measurement_dir")
    want = meas_dir(run_dir, thr)
    if got is None:
        return [Violation("error", "process_capture return value",
                          "summary has no '_measurement_dir' key",
                          "update check_measurement_dir in pipeline_spec.py")]
    if Path(got).resolve() != want.resolve():
        return [Violation("error", "process_capture return value",
                          f"measurement written to {got}, contract expects {want}",
                          "update MEAS_DIR in pipeline_spec.py to match process_capture.py")]
    return []


def check_stage_seconds(summary: dict) -> list[Violation]:
    unknown = set(summary.get("_stage_seconds", {})) - TIMING_KEYS
    return [Violation("warn", "process_capture _stage_seconds",
                      f"unknown stage '{k}' -- ETA cannot account for it",
                      "add a Stage to STAGES in pipeline_spec.py")
            for k in sorted(unknown)]


def _count_ok(spec: str, n: int, n_frames: int | None) -> bool:
    if spec == "n_frames":
        return n_frames is not None and n == n_frames
    lo, hi = (int(x) for x in spec.split("-"))
    return lo <= n <= hi


# Stages that run again on EVERY analysis, even when extraction and inference are reused.
# Their outputs are checked for freshness; the reused stages' outputs (frames, predictions)
# are legitimately older than the run and are not.
RERUN_STAGES = ("measurement", "classical")
MTIME_SLACK_S = 2.0         # FAT-family file systems store modification times to 2 s


def verify_run_outputs(run_dir: Path, settings: RunSettings, options: dict[str, Any],
                       n_frames: int | None = None, since: float | None = None) -> list[Violation]:
    """Every output the contract promises for these options must exist, with the declared
    count. Run by the worker after each run.

    RE-ANALYSIS: the pipeline does not clear old results before re-measuring, so a folder
    analysed before can hold files from the PREVIOUS analysis -- e.g. 497 per-frame PNGs from
    an "every frame" run when this run drew only the extremes. Pass `since` (the run's start
    time, epoch seconds) and the measurement/classical outputs are judged on what THIS run
    wrote: a stale file does not count towards a glob, and does not satisfy a required file.
    Nothing is deleted. Without `since`, existence and counts only (as before)."""
    list_files = rdc_module("_fsutil").list_files
    run_dir = Path(run_dir)
    s = effective(settings)
    if n_frames is None:
        meta = rdc_module("process_capture").previous_analysis(run_dir) or {}
        n_frames = meta.get("frame_count")
    names = {"meas": MEAS_DIR.format(thr=s.score_thresh),
             "clas": CLAS_DIR.format(thr=s.score_thresh)}
    cutoff = None if since is None else since - MTIME_SLACK_S

    def fresh(path: Path, out: Output) -> bool:
        if cutoff is None or out.stage not in RERUN_STAGES:
            return True
        try:
            return path.stat().st_mtime >= cutoff
        except OSError:
            return False

    problems = []
    for out in active_outputs(options, scope="run"):
        rel = out.path.format(**names)
        target = run_dir / rel
        if out.kind == "glob":
            found = list_files(target.parent, target.name)
            n = sum(fresh(f, out) for f in found)
            if not _count_ok(out.count, n, n_frames):
                want = f"{n_frames} (n_frames)" if out.count == "n_frames" else out.count
                stale = len(found) - n
                extra = f" ({stale} older file(s) from a previous analysis ignored)" if stale else ""
                problems.append(Violation("error", rel, f"found {n} files, expected {want}{extra}",
                                          f"Output '{out.id}' in pipeline_spec.py"))
        elif not target.exists():
            problems.append(Violation("error", rel, "missing",
                                      f"Output '{out.id}' in pipeline_spec.py"))
        elif not fresh(target, out):
            problems.append(Violation(
                "error", rel, "was not rewritten by this run (it is left over from an earlier "
                              "analysis, so this run did not produce it)",
                f"Output '{out.id}' in pipeline_spec.py"))
    return problems


# ============================================================================
# PREFLIGHT
# ============================================================================


@dataclass
class PreflightReport:
    violations: list[Violation] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    commit: str = "unknown"
    pipeline_dirty: bool = False
    script_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.level == "error"]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.level == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> list[str]:
        state = "uncommitted edits" if self.pipeline_dirty else "clean"
        lines = [f"PREFLIGHT  pipeline @ {self.commit} (AI/Real_Data_Code {state})"]
        lines += [f"  ok    {p}" for p in self.passed]
        for v in self.violations:
            tag = "FAIL " if v.level == "error" else "WARN "
            lines.append(f"  {tag} {v.where}: {v.message}")
            if v.fix:
                lines.append(f"        fix: {v.fix}")
        if self.ok:
            tail = f", {len(self.warnings)} warning(s)" if self.warnings else ""
            lines.append(f"PREFLIGHT PASSED ({len(self.passed)} checks{tail})")
        else:
            lines.append(f"PREFLIGHT FAILED: {len(self.errors)} error(s), "
                         f"{len(self.warnings)} warning(s) -- batch disabled")
        return lines

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PreflightReport":
        return cls(violations=[Violation(**v) for v in d.get("violations", [])],
                   passed=list(d.get("passed", [])), commit=d.get("commit", "unknown"),
                   pipeline_dirty=d.get("pipeline_dirty", False),
                   script_hashes=dict(d.get("script_hashes", {})))


def check_import(call: ImportCall, module: Any = None) -> tuple[list[Violation], str | None]:
    """Verify one ImportCall. `module` may be injected (tests pass a fake)."""
    fix = f"update {call.name} in pipeline_spec.py to match AI/Real_Data_Code/{call.module}.py"
    try:
        mod = module if module is not None else rdc_module(call.module)
    except Exception as exc:
        return [Violation("error", call.module, f"import failed: {type(exc).__name__}: {exc}",
                          f"fix AI/Real_Data_Code/{call.module}.py")], None
    fn = getattr(mod, call.func, None)
    if fn is None or not callable(fn):
        return [Violation("error", call.name, "function no longer exists", fix)], None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        return [Violation("error", call.name, f"cannot read signature: {exc}", fix)], None
    params = sig.parameters
    takes_kwargs = any(p.kind is p.VAR_KEYWORD for p in params.values())
    problems = []
    missing = [p for p in call.params if p not in params]
    if missing and not takes_kwargs:
        problems.append(Violation("error", call.name,
                                  f"no longer accepts {', '.join(missing)}", fix))
    new_required = [n for n, p in params.items()
                    if p.default is p.empty
                    and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                    and n not in call.params]
    if new_required:
        problems.append(Violation("error", call.name,
                                  f"has new required parameter(s) {', '.join(new_required)}",
                                  fix))
    if problems:
        return problems, None
    return [], f"{call.name}({', '.join(call.params)})"


def _usage_block(help_text: str) -> str | None:
    """argparse's generated usage block: from 'usage:' to the first blank line.

    Flags are searched for HERE, never in the whole --help text. The full text
    includes the script's docstring as its description, and docstrings carry
    usage EXAMPLES ("python classical_liquid.py --root <run>") that would keep
    "proving" a flag exists after it was removed. The mutation test
    test_removed_root_flag_is_caught exists because exactly that happened.
    The usage block is generated from the parser itself, lists every option
    (with choices, e.g. {extremes,all}), and is never truncated -- only wrapped.
    """
    lines = help_text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("usage:")), None)
    if start is None:
        return None
    block = []
    for ln in lines[start:]:
        if not ln.strip():
            break
        block.append(ln)
    return "\n".join(block)


@functools.lru_cache(maxsize=32)
def _script_help(script: str, mtime_ns: int, size: int) -> tuple[int, str]:
    """`python <script> --help`, cached on (path, mtime, size) so an edited
    script is re-read rather than served stale."""
    proc = subprocess.run([sys.executable, script, "--help"], capture_output=True,
                          text=True, timeout=60, cwd=str(Path(script).parent))
    return proc.returncode, proc.stdout + proc.stderr


def check_script(call: ScriptCall, script_path: Path | None = None
                 ) -> tuple[list[Violation], str | None]:
    """Verify one ScriptCall. `script_path` may be injected (the mutation test
    points it at an edited copy)."""
    path = Path(script_path) if script_path else paths.RDC_DIR / call.script
    fix = f"update {call.script} entry (CLASSICAL) in pipeline_spec.py to match the script"
    if not path.is_file():
        return [Violation("error", call.script, f"script not found at {path}",
                          "restore the script or update pipeline_spec.py")], None
    st = path.stat()
    try:
        code, text = _script_help(str(path), st.st_mtime_ns, st.st_size)
    except subprocess.TimeoutExpired:
        return [Violation("error", call.script, "--help timed out", fix)], None
    if code != 0:
        tail = " | ".join(text.strip().splitlines()[-3:])
        return [Violation("error", call.script, f"--help exited {code}: {tail}",
                          f"fix AI/Real_Data_Code/{call.script}")], None
    usage = _usage_block(text)
    if usage is None:
        return [Violation("error", call.script, "no argparse 'usage:' block in --help output",
                          fix)], None
    problems = []
    for flag in call.flags:
        if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", usage):
            problems.append(Violation("error", call.script, f"no longer accepts {flag}", fix))
    for flag, values in call.choices:
        m = re.search(rf"{re.escape(flag)}\s+\{{([^}}]*)\}}", usage)
        offered = {v.strip() for v in m.group(1).split(",")} if m else set()
        for v in values:
            if v not in offered:
                problems.append(Violation(
                    "error", call.script,
                    f"{flag} no longer offers '{v}' (offers: {sorted(offered) or 'none'})", fix))
    if problems:
        return problems, None
    return [], f"{call.script} accepts {' '.join(call.flags)}"


def check_constant(module: str, name: str) -> tuple[list[Violation], str | None]:
    try:
        mod = rdc_module(module)
    except Exception as exc:
        return [Violation("error", module, f"import failed: {type(exc).__name__}: {exc}",
                          f"fix AI/Real_Data_Code/{module}.py")], None
    if not hasattr(mod, name):
        return [Violation("error", f"{module}.{name}", "no longer defined",
                          f"update CONSTANTS in pipeline_spec.py")], None
    return [], None


def script_hashes() -> dict[str, str]:
    out = {}
    for name in CHAIN_SCRIPTS:
        p = paths.RDC_DIR / name
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else "missing"
    return out


def preflight() -> PreflightReport:
    """Verify every declaration in this module against the live pipeline.

    In-process: reflects the modules as first imported into THIS process. The
    UI uses `preflight_fresh()` instead, which runs this in a new interpreter
    so it always sees the code a new batch worker would actually run."""
    report = PreflightReport()
    report.commit, report.pipeline_dirty = paths.repo_commit("AI/Real_Data_Code")
    report.script_hashes = script_hashes()

    for call in (PROCESS_CAPTURE, *HELPERS):
        problems, ok = check_import(call)
        report.violations += problems
        if ok:
            report.passed.append(ok)

    problems, ok = check_script(CLASSICAL)
    report.violations += problems
    if ok:
        report.passed.append(ok)

    const_problems = []
    for module, name in CONSTANTS:
        problems, _ = check_constant(module, name)
        const_problems += problems
    report.violations += const_problems
    if not const_problems:
        report.passed.append(f"{len(CONSTANTS)} constants present "
                             f"({', '.join(n for _, n in CONSTANTS)})")

    # Internal consistency: the builders must only use declared flags/params.
    try:
        probe = Path("/__preflight_probe__")
        for opts in all_option_combinations():
            classical_cmd(probe, RunSettings(), opts)
            process_capture_kwargs(probe, RunSettings(), opts, log=print,
                                   cine=probe / "x.cine")
        report.passed.append("call builders use only declared flags, for all "
                             f"{len(all_option_combinations())} option combinations")
    except AssertionError as exc:
        report.violations.append(Violation("error", "pipeline_spec.py", str(exc)))
    return report


JSON_MARKER = "@@PREFLIGHT_JSON@@"


def run_self_check(as_json: bool = False) -> int:
    """`python -m src.ai.Taguchi_Analysis_UI --self-check [--json]`."""
    noise = io.StringIO()
    # config_loader prints "Detected LaCie drive..." on import; keep it out of
    # the JSON channel.
    with contextlib.redirect_stdout(noise):
        report = preflight()
    if as_json:
        print(JSON_MARKER + json.dumps(report.to_dict()))
    else:
        print("\n".join(report.render()))
    return 0 if report.ok else 1


def preflight_fresh(timeout: float = 120) -> PreflightReport:
    """Preflight in a NEW interpreter -- the same `sys.executable` a batch
    worker will use -- so edits made to the pipeline while the app is open are
    seen. The UI calls this at startup and before every batch."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "src.ai.Taguchi_Analysis_UI", "--self-check", "--json"],
            capture_output=True, text=True, timeout=timeout, cwd=str(paths.REPO_ROOT))
    except subprocess.TimeoutExpired:
        return PreflightReport(violations=[Violation(
            "error", "preflight", f"self-check timed out after {timeout:.0f}s")])
    for line in proc.stdout.splitlines():
        if line.startswith(JSON_MARKER):
            return PreflightReport.from_dict(json.loads(line[len(JSON_MARKER):]))
    tail = " | ".join((proc.stdout + proc.stderr).strip().splitlines()[-4:])
    return PreflightReport(violations=[Violation(
        "error", "preflight", f"self-check crashed (exit {proc.returncode}): {tail}")])
