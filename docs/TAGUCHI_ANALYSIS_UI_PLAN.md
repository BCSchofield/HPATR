<!--
Provenance: approved implementation plan for src/ai/Taguchi_Analysis_UI/.
Approved 2026-10-05. Working copy lives at
~/.claude/plans/hi-claude-time-to-squishy-meerkat.md (session-local, not
versioned) — THIS file in docs/ is the durable copy. If the plan changes
during implementation, update this file too.

Status: Phases 1-3 complete. Phases 4-10 outstanding. See the
"Implementation phases" table for the per-phase model guidance, and the
"Implementation log" at the END of this file for decisions made while
building that refine or deviate from the plan text.
-->

# Taguchi_Analysis_UI — a batch orchestrator + generalised Taguchi analyser

## Context

The droplet-measurement pipeline works, but driving it over a campaign is currently a
command-line job: `batch_runs.py` with a hand-typed list of run folders, then
`taguchi_analysis.py` with exactly nine of them. Two things make that painful.

**Driving it.** The 2026/10/05 campaign is 27 run folders (verified: a perfect L9 × 3
replicates, every folder carrying its `run_summary.xlsx`, one `.cine` each, and 9 distinct
factor tuples × 3). At the recorded 22–47 min/run that is 11–18 hours of compute, and the
handoff records this batch being **killed twice** mid-run. There is no progress view, no ETA,
no resume, and no way to say "don't write 497 PNGs per run this time".

**Analysing it.** `taguchi_analysis.py` is hardwired: exactly 9 runs, exactly the three
factors `sccm`/`rpm`/`sps`, three levels, **no replicates**, and ANOVA error borrowed from the
L9's unassigned fourth column (2 dof). It cannot use the 27-run replicated design at all — yet
replicates give a *proper pure error* with 18 dof, which is strictly better evidence than the
unassigned-column trick. It also can't analyse against orifice, bubbler height or GLR, and it
reports no size-distribution spread.

**Outcome.** A cross-platform PySide6 app at `src/ai/Taguchi_Analysis_UI/` that selects any
number of run folders from any number of date trees, runs the full per-run chain in a detached
resumable job with live progress and ETAs in a console, and then produces main effects, ANOVA
with replicate pure error, S/N, odd-frame flagging and droplet size-spread charts as a markdown
report plus an Excel workbook.

### The overriding constraint

> "If I update the analysis pipeline, this must always use the most recent pipeline."

**This app contains no measurement logic.** It calls the canonical scripts in
`AI/Real_Data_Code/` and imports their functions. Every stage, flag and output-folder name is
declared in **one** module, and a startup preflight verifies those declarations against the real
scripts. If a pipeline CLI changes, the app says so in red in the console naming the exact
missing flag — it never silently does the wrong thing. See [Single source of truth](#single-source-of-truth).

A deliberate consequence: the right-hand output tree may only offer toggles the pipeline
actually has. The real image knobs are `measure_run --images {all,extremes}` / `--no-images` and
`classical_liquid --images-mode {extremes,all}`. `size_histograms.png` is written
unconditionally, so it is shown as mandatory, not as a toggle. **The tree must not be a lie.**

### Verified image layout — the two stages differ, and not as documented

This was checked in the source and on disk, because the first draft of this plan got it wrong:

- **`measure_run.py:965` writes PNGs FLAT into `droplets_<thr>/`**, in *both* `all` and
  `extremes` mode. There is no `extreme_images/` subfolder. Confirmed on disk:
  `2026/10/01/104852…/shadowgraph/analysis/measurement_0.30/` holds 502 entries, all flat.
  `extremes` yields 4–6 PNGs (D32 low/high, sparse-guarded D32 low/high, atomised low/high,
  de-duplicated), sitting beside the CSVs.
- **`classical_liquid.py:438` does split**: `img_dir = out_dir / ("extreme_images" if
  draw_extremes else "images")` — 2 PNGs in `extreme_images/` (atomised low + high only), or
  497 in `images/`.
- The `measurement_0.30/extreme_images/` folders in the curated campaign were created **by
  hand** during curation. They are not pipeline output.

Consequence: in the measurement folder you cannot distinguish "extremes" output from a partial
"all" run by structure — only by file count. The tree labels it `frame_*.png · 4–6 · flat in
this folder`, and the artefact check verifies the count, not the folder.

---

## Window layout

```
┌───────────────────────────────┬──────────────────────────────────────┐
│ SELECTED RUNS           [+]   │ OUTPUTS THAT WILL BE CREATED         │
│ ☑ 2026/10/05 090432_3000…     │ ▸ <RUN>/shadowgraph/raw/             │
│ ☑ 2026/10/05 091303_3000…     │   ☑ frames/8bit  (497 png)    grey   │
│   … 27 runs, 9 conditions ×3  │   ☑ background_median.tiff    grey   │
│ ⚠ 1 run already analysed      │ ▸ <RUN>/shadowgraph/analysis/        │
│                               │   ☑ predictions.json          grey   │
│ OUTPUT FOLDER           […]   │   ▾ droplets_0.30/                   │
│ /Volumes/LaCie/…/ReRun1       │     ☑ droplet_sizes.csv       grey   │
│                               │     ☑ frame_*.png  4–6, FLAT  grey   │
│ [ Run batch ]  [ Analyse ]    │     ☐ every frame as PNG (×497) SLOW │
├───────────────────────────────┴──────────────────────────────────────┤
│ CONSOLE                                            [Clear] [Open log]│
│ [14:02:11] run 6/27 114108_9000sccm_600rpm_4000sps                   │
│ [14:02:11]   inference  447/497 (90%)  eta 1m 12s                    │
│ [14:02:11] campaign eta 7h 48m · elapsed 3h 11m · 0 failed           │
└──────────────────────────────────────────────────────────────────────┘
```

Tabs: **Batch** (above), **Taguchi** (design table + analysis), **Settings** (threshold,
stride, device, bin width).

Theme: import the tokens and helpers from `src/gui/GUI_Clean.py` rather than restyling —
`CLR_BG`/`CLR_PANEL`/`CLR_ACCENT`/…, `FONT_FAMILY`, `BASE_STYLE`, `card()`, `section_label()`,
`accent_button()`, `ghost_button()`, `input_row()`, `separator()`. `main()` **must** call
`app.setStyle("Fusion")` and then the `findChildren(QLineEdit)`/`findChildren(QComboBox)`
per-widget restyle loop, or macOS ignores the custom borders (this is already a known trap,
recorded in memory).

---

## Module breakdown — `src/ai/Taguchi_Analysis_UI/`

Deliberately many small modules; `GUI_Clean.py` at 8,073 lines is the pain point to avoid.

| File | ~lines | Responsibility |
|---|---|---|
| `__main__.py` | 20 | `python -m src.ai.Taguchi_Analysis_UI` |
| `app.py` | 600 | `QMainWindow`, three panes, tab wiring, Run/Analyse buttons |
| `theme.py` | 60 | Re-export GUI_Clean tokens/helpers; fall back to local copies if that import ever breaks |
| `pipeline_spec.py` | 220 | **Single source of truth**: `STAGES`, `OUTPUTS`, `preflight()` |
| `output_tree.py` | 200 | `QTreeWidget` built from `OUTPUTS`; resolves ticks → stage kwargs |
| `run_discovery.py` | 180 | Folder scan, name parse, `run_summary.xlsx` read, already-analysed detection |
| `design.py` | 260 | Generalised design inference, replicate cross-check, editable model |
| `stats.py` | 320 | Main effects, ANOVA with pure error, S/N, balance/orthogonality checks |
| `size_bins.py` | 110 | Count-% and volume-% binning |
| `figures.py` | 260 | Main effects, contributions, per-run bars, two stacked size-spread charts |
| `report.py` | 240 | `taguchi_report.md` |
| `workbook.py` | 160 | Excel workbook, sheet per table |
| `jobstate.py` | 170 | Job/state JSON schema, atomic write, liveness, resume |
| `eta.py` | 110 | Per-stage rate model |
| `worker.py` | 260 | Detached batch worker entry point — **no Qt imports**, built to run unmodified on macOS and Windows |
| `console.py` | 120 | Log queue + styled `QPlainTextEdit` |
| `settings_defaults.py` | 90 | Auto-detected defaults for the Settings tab — one call per field, same functions the pipeline itself uses |
| `tests/` | 400 | Fixtures + regression against the published L9 |

---

## Single source of truth

`pipeline_spec.py` declares the whole contract. Nothing else in the app names a flag or an
output folder.

```python
REPO = Path(__file__).resolve().parents[3]          # .../HPATR
RDC  = REPO / "AI" / "Real_Data_Code"

@dataclass(frozen=True)
class Stage:
    id: str                       # "inference"
    label: str                    # "Inference"
    kind: str                     # "import" | "script"
    target: str                   # "process_capture:process_capture" | "classical_liquid.py"
    requires: tuple[str, ...]     # upstream stage ids
    flags: tuple[str, ...]        # flags/kwargs the UI passes — PREFLIGHT CHECKS THESE
    prior_s_per_frame: float      # ETA seed from the handoff's recorded timings

@dataclass(frozen=True)
class Output:
    id: str
    label: str
    path: str                     # "{run}/shadowgraph/analysis/{droplets}/droplet_sizes.csv"
    stage: str
    mandatory: bool               # grey, always-ticked, not clickable
    default_on: bool
    kwargs: dict | None           # what ticking it changes, e.g. {"images": "all"}
    note: str                     # "×497, adds ~10 min/run"
```

`MEAS_DIR = "droplets_{thr:.2f}"`, `CLAS_DIR = "liquid_{thr:.2f}"` live here too — and reading
is done by **importing `taguchi_analysis.load_run`**, whose `_pick()` already accepts both the
current and the historical `measurement_`/`classical_` names.

`preflight()` runs on app start and again before each batch, printing a green or red block to
the console:

1. **Import stages** — `inspect.signature(process_capture.process_capture)` must accept every
   kwarg in `Stage.flags`. Also assert the helpers exist: `previous_analysis`, `can_reuse`,
   `auto_ci_stride`.
2. **Script stages** — run `python <script> --help` once (cached per session) and assert every
   declared flag appears in the output.
3. **Reused stats functions** — assert `taguchi_analysis` exposes `load_run`,
   `pooled_responses`, `bootstrap`, `level_table`, `flag_odd`, `RESPONSES`, `RESP_KEYS`,
   `SN_SIGN`, `N_BOOT`, `SEED`, `MIN_DISTINCT`, `EMPTY_FRAC`.
4. **Git provenance** — record `git rev-parse HEAD` + dirty flag into the report, so every
   report states which pipeline revision produced it.

A failure is a loud, specific console error (`PREFLIGHT FAILED: classical_liquid.py no longer
accepts --images-mode`) and the Run button disables. The app never adapts, guesses, or falls
back. `python -m src.ai.Taguchi_Analysis_UI --self-check` prints the same table and exits
non-zero — the hook to run after touching anything in `AI/Real_Data_Code/`.

Two refinements worth building in from the start:

- **Return-value check.** `process_capture` *returns* `_measurement_dir`. Compare it against the
  contract's rendered `droplets_{thr:.2f}` path after run 1, so a renamed output folder is caught
  on the first run rather than at report time eleven hours later.
- **stdout text is explicitly NOT contractual.** A progress-parser regex that stops matching
  degrades that stage to elapsed-only and logs a warning; the run continues. Treating print
  statements as a contract would make the app brittle in the one place it must not be.

### What is reused vs newly written

**Imported and called as-is:** `process_capture.process_capture()` (stages 1–4 — the documented
single entry point), `can_reuse()`, `previous_analysis()`, `auto_ci_stride()`,
`_fmt_dur()`; `classical_liquid.py` as a subprocess (stage 5); `taguchi_analysis.load_run()`,
`pooled_responses()`, `bootstrap()`, `level_table()`, `flag_odd()`, `load_timings()` and the
`RESPONSES`/`SN_SIGN` tables; `GUI_Clean`'s theme helpers and the
`_GuiLogStream`/`_ThreadLocalStream`/`_InferenceProgressFilter` console machinery;
`src/config_loader.find_lacie_drive()`/`resolve_path()`; `batch_runs.py`'s `timings.csv` column
schema.

**Newly written because the existing code is hardwired and cannot generalise:**
`taguchi_analysis.ss_factor()` hardcodes `3.0 *` (three runs per level), `anova()` reads the
module-global `FACTORS` and assumes 2 dof per factor, and `f_sf_2()` is exact *only* for two
numerator dof. `parse_levels()` hard-fails on anything but `sccm/rpm/sps`. So `stats.py`
implements the generalised versions. Two guards against drift: it reuses `level_table()`
verbatim, and a regression test asserts that on the original nine unreplicated runs it
reproduces `results_2026-10-01/taguchi_results.json`.

> **`sys.exit` hazard.** `load_run()` calls `sys.exit()` on its self-consistency gates (D32
> and atomised re-derivation) and `parse_levels()` exits on an unparseable name. In a GUI that
> would kill the app, so every call is wrapped in `try/except SystemExit` and surfaced as a
> per-run error in the console. The *refusal* is correct and preserved; only the mechanism
> changes. Factor levels are **not** taken from `parse_levels` — the app overwrites
> `rec["levels"]` with its own generalised extraction.

> **`flag_odd` hazard.** It looks for classical images at `cl_dir/"images"/<frame>.png`, which
> does not exist in the default `extremes` mode — so the odd pack silently records "none found".
> The wrapper passes a pre-resolved image-directory list and writes *"no image found (run used
> --images extremes)"* instead of an empty folder. Worth a one-line fix upstream rather than a
> fork.

> **Directory listings** go through `AI/Real_Data_Code/_fsutil.list_files`, never `Path.glob` —
> it is what the rest of the pipeline uses, and it already handles the exFAT `._*` noise and
> ordering that a raw glob does not.

> **Other verified gotchas.** `FPS` is 390 on all 27 runs, so `auto_ci_stride(390, 10) = 1`.
> Folder order is *not* condition order — `111625` (ReRun 5 Rep 1) sorts before `112253`
> (ReRun 4 Rep 3), confirmed in the scan — so replicate grouping must key on the factor tuple,
> never on position.

---

## Run discovery — `run_discovery.py`

A run folder is valid when it matches
`^(\d{6})_(\d+)sccm_(\d+)rpm_(\d+)sps_or([\d.]+)_bh(\d+)$` and contains exactly one
`shadowgraph/raw/CINE/*.cine`. Scans must filter AppleDouble `._*` and `.DS_Store` (the LaCie is
exFAT). A missing `run_summary.xlsx` is a warning, not a rejection.

From `run_summary.xlsx` → `Metadata` (note: values are mostly **strings**, even numbers, and
`Flow Range (sccm)` uses an en-dash U+2013): `Orifice`, `Bubbler Height (mm)`, `Bubbler RPM`,
`Flow Range (sccm)`, `GLR`, `Fluid`, `Gas`, `Speed (steps/s)`, `Motor Travel (mm)`, `FPS`,
`Notes`. The `Pressure` sheet gives mean/std achieved pressure and flow as covariates.

Folder-name `sccm` is the **setpoint** (3000); the xlsx `Flow Range` max is **achieved**
(3086/3110/3098). Factor levels use the setpoint; achieved values are reported as a drift check.

Already-analysed detection uses `can_reuse(run_dir, stride, model_dir)`, so re-running a
campaign skips completed runs instead of redoing 14 GiB of work.

---

## The detached resumable worker

`worker.py` is a plain Python entry point with **no Qt imports**, launched as
`python -m src.ai.Taguchi_Analysis_UI.worker --job <output>/_job/job.json`:

- **POSIX:** `Popen(..., start_new_session=True)` — `setsid()`, so a terminal close or SIGHUP
  cannot reach it. No double fork needed.
- **Windows:** `creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP |
  CREATE_BREAKAWAY_FROM_JOB (0x01000000)`, plus `STARTUPINFO` with `SW_HIDE`.
  - Never `CREATE_NEW_CONSOLE` — that is the blank CMD window the handoff records as killing
    the batch when closed.
  - `CREATE_BREAKAWAY_FROM_JOB` is the flag that addresses the *actual* kill: if the launcher
    sits inside a Job object, the worker dies with it unless it breaks away. If the job lacks
    `JOB_OBJECT_LIMIT_BREAKAWAY_OK` this fails with `ERROR_ACCESS_DENIED`, so catch it, retry
    once without the flag, and log that the worker may not outlive the parent.
- **Keep-awake**, because 18 hours: a sibling detached `caffeinate -i -w <pid>` on macOS,
  `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` via ctypes inside the worker on
  Windows. Both best-effort, both logged.
- stdout/stderr redirected to `<output>/_job/worker.log`, `PYTHONUNBUFFERED=1`
- launched with `sys.executable`, because `process_capture` spawns its children with
  `sys.executable` — the launching interpreter determines the whole chain's (the handoff
  records this biting on the lab PC, where torch lives in system Python 3.11, not a conda env)

**IPC — files only, no sockets.** `<output>/_job/`:

| File | Written by | Read by |
|---|---|---|
| `job.json` | UI, once | worker |
| `state.json` | worker, atomically (`tmp` + `os.replace`) after every stage | UI |
| `events.jsonl` | worker, append-only one JSON per line | UI tails it |
| `heartbeat` | worker, every 5 s | UI |
| `worker.log` | worker stdout/stderr | "Open log" button |
| `timings.csv` | worker, `batch_runs.py`'s schema | the analysis step |

`state.json`: `{schema, job_id, pid, pid_started_at, started_at, config{…}, runs:[{path,
status: pending|running|done|failed|skipped, stage, stage_pct, seconds{…}, error}],
stage_rates{…}}`.

**Liveness.** `os.kill(pid, 0)` on POSIX / `ctypes` `OpenProcess` on Windows, cross-checked
against `pid_started_at` to defeat PID reuse. The UI shows **running** (heartbeat fresh),
**stalled** (PID alive, heartbeat older than 90 s — printed as a visible warning, which is
exactly the "has it stopped/broken?" signal asked for), or **dead** (PID gone, state not
`done`) → the Run button becomes **"Resume (14/27 done)"**.

On app start, if an output folder's `_job/state.json` exists and is unfinished, the UI
reattaches automatically and replays `events.jsonl` into the console.

**Cross-platform by construction, not by luck.** Every OS-specific line above is branched on
`os.name`/`sys.platform` inside `spawn_detached()` and `is_alive()` — the two functions where
it matters — never scattered. Phase 5's exit test (below) runs the detach → kill → resume cycle
on whichever OS is at hand; the Windows branch additionally gets a unit test that monkeypatches
`os.name` and asserts the exact `creationflags` bitmask and `STARTUPINFO` passed to `Popen`,
since CI here is macOS-only and that path cannot be exercised live until you run it on the lab
PC. Everything downstream — `jobstate.py`, `eta.py`, `progress.py`, the IPC files — is plain
JSON/text and inherently cross-platform; the risk is entirely in those two functions, which is
why they're the ones called out explicitly rather than assumed.

### Progress and ETA — `eta.py`

Per-stage rate in seconds-per-frame, seeded from the handoff's recorded figures (extract
190–226 s, inference 411–1559 s, measure 316–361 s, classical 41 s `extremes` / 699 s `all`,
per 497 frames) and then replaced by the median of this campaign's own completed runs as they
land. ETA = Σ(remaining stages × frames × rate). Sub-run progress comes from
`_InferenceProgressFilter(emit, every=25)` passed as `process_capture`'s `log=` callback, which
already collapses per-frame spam. The console prints a campaign line on a fixed cadence
(~10 s) even when nothing changes, so a stall is visible.

---

## Taguchi tab — generalised design

**Auto-detect, fully editable.** The app proposes a design table and lets everything be changed.

Replicates are detected **two independent ways and cross-checked**:

1. `Notes` regex — `(?:ReRun|Run|Trial)\s*(\d+)\s*-\s*Repeat\s*(\d+)` gives trial and repeat
   directly. Verified present on all 27 runs of 2026/10/05.
2. Grouping by identical factor-level tuple. Verified: 9 groups of exactly 3.

Agreement is reported as a green tick; disagreement, or any run that can't be assigned, is
listed for manual assignment. Neither method is trusted alone.

Editable table: one row per run — trial, replicate, each factor's level, include/exclude.
Factors can be renamed (`sps` → "Silicone flow (steps/s)"), levels edited, and a **new factor
added sourced from any xlsx Metadata field** (Orifice, Bubbler Height, GLR, FPS, Motor Travel).
Saved to `<output>/taguchi_design.json` and reloaded on reopen.

"Analyse" runs standalone on any already-analysed folders, so the existing 2026/10/01 L9 can be
re-reported without recomputing anything.

### Statistics — `stats.py`

Conditions are unique factor-level tuples; replicates are the runs within a condition.

- **Main effects** — level means over all runs at that level, with the frame-bootstrap CI from
  the reused `bootstrap()` plus a between-replicate SE.
- **ANOVA with replicate pure error** (the real gain from 27 runs):
  - `SS_factor = n_per_level · Σ(ȳ_level − ȳ)²`, `df = levels − 1`
  - `SS_pure_error = Σ_cond Σ_rep (y − ȳ_cond)²`, `df = N − n_conditions` (**18** here)
  - `SS_lack_of_fit = SS_total − ΣSS_factor − SS_pure_error`,
    `df = n_conditions − 1 − Σ(levels_i − 1)` (**2** here)
  - `F = MS_factor / MS_pure_error`, `p = scipy.stats.f.sf(F, df_f, df_e)` (scipy 1.17.1 is in
    the `phantom` env; a pure-Python regularised incomplete beta is the fallback)
  - A significant lack-of-fit is reported as a **warning that interactions matter**. This is the
    single biggest scientific gain from the replicates and the report should say so: the
    unreplicated L9 was using those same 2 dof *as* its error term, so it was testing against
    interaction rather than against noise
  - `% contribution` reported both raw (`SS_f/SS_total`) and **pooled/adjusted**
    (`(SS_f − df_f·MS_e)/SS_total`, the form Taguchi texts use, which stops a weak factor's
    contribution being inflated by its own error), each clearly labelled
  - An **aliased** factor pair (an empty cell in its cross-tab) gets a refusal, not a number —
    an aliased effect is not estimable, and producing a value would be fabrication. Imbalance
    with full rank falls back to Type-II SS via least squares, with a test asserting that path
    reproduces the balanced shortcut to 1e-10 on the real 27-run data
  - Unreplicated designs fall back to `taguchi_analysis.py`'s unassigned-column error, so the
    old nine-run path still works
- **S/N** — with replicates, the proper Taguchi forms: smaller-better `−10log₁₀(mean(y²))`,
  larger-better `−10log₁₀(mean(1/y²))`, using `SN_SIGN` from the existing `RESPONSES` table.
  The old single-value `±20log₁₀(y)` proxy is also reported so numbers stay comparable with the
  published L9.
- **Guards** — balance (every level equally often), orthogonality (every factor pair fully
  crossed), and the existing `MIN_DISTINCT = 4` quantisation check that stops a response sitting
  on the integer-pixel lattice from reading p ≈ 0 meaninglessly. An unbalanced design is
  **analysed anyway** via least-squares Type-II SS, with a prominent report warning — it does
  not refuse, unlike the current script's five `sys.exit` gates.
- **Multiple comparisons** — 9 responses × 3 factors is 27 tests; the report keeps the existing
  honesty note and adds a Benjamini–Hochberg adjusted column.
- **sizer_version guard** — kept. Mixed 2.0.0/2.1.0 runs are not comparable (2.1.0 moved the
  atomised fraction ~3% relative), so mixing is blocked with a clear message.

### Odd-frame flagging

Reuses `flag_odd()` for the existing categories (`atomised_100pct`, `no_infocus_droplets`,
`d32_outlier`, `slow_stage`). Added, since replicates now exist: a **replicate outlier** check
flagging any run more than *k* MAD from its own condition's mean on any response — "out of the
ordinary range for these tests". The CSV is always written; the image pack writes PNGs and so is
an unticked option.

### Size spread — `size_bins.py`

From `load_run`'s per-frame `dia` arrays, in-focus droplets only. Edges `0, 25, 50, …, 200, ∞`
with the width editable in Settings. Two measures:

- **% by count** — droplets per bin ÷ total
- **% by volume** — `Σd³` per bin ÷ `Σd³` total, which shows where the liquid actually is (a few
  200 µm droplets outweigh thousands of 30 µm ones)

Per run and pooled per condition. Two stacked bar charts, runs on X, bins as stacks, shared
legend and a perceptually ordered sequential ramp (small → large). Tables go to
`size_bins_count.csv` / `size_bins_volume.csv` and to the workbook.

---

## Settings tab — auto-populated, never a blank field

Same principle as the GUI already uses for stride → decorrelation time: **every Settings field
opens with the value the pipeline itself would choose**, computed by calling the pipeline's own
functions, not by hand-copying a constant that can drift out of date. Editable, never forced.
`settings_defaults.py` is the only module allowed to call these at startup — one function per
field, each returning `(value, source_note)` so the UI can show *why* a field holds what it
holds:

| Field | Default source | What's shown |
|---|---|---|
| Score threshold | `process_capture.DEFAULT_SCORE_THRESH` (0.30) | plain default |
| Stride | `process_capture.DEFAULT_STRIDE` (10) | plain default |
| CI stride | `process_capture.auto_ci_stride(fps, stride)` | **per-run, not global** — FPS comes from each run's own extraction metadata, so this is recomputed per run at launch time and shown as "auto (per-run)" with the formula's result for the currently-selected runs (390 fps → 1, for every run checked on 2026/10/05). An explicit override replaces auto for all selected runs. |
| Device | `tiled_inference.auto_device()` | shows the resolved value (`cpu` on this Mac, with the same non-blocking slow-inference note as the output-tree warning) plus the manual `mps`/`cuda`/`cpu` override |
| Model directory | `tiled_inference.default_model_dir()` + `find_weights()` | resolved path, which `.pth` it found, and the iteration note from `<name>_summary.json` if present — exactly what `tiled_inference.py` already prints before inference, surfaced here before the batch starts rather than buried in the log. Raises a clear "LaCie drive not found — pick a model folder" prompt rather than the script's `sys.exit` if the drive isn't mounted yet. |
| Images mode | `"extremes"` | pipeline's own default, matches the output-tree's default-off "every frame" |
| Size-bin width / max | `25 µm` / `200 µm` | this app's own new feature, no upstream default exists; documented as such rather than implying one does |

None of these values are duplicated as literals anywhere else in the app — `pipeline_spec.py`
and `settings_defaults.py` both import the same constants/functions from
`AI/Real_Data_Code`, so a changed default upstream (e.g. `DEFAULT_SCORE_THRESH` moving to 0.35)
changes what the Settings tab proposes automatically, with no edit to this app at all. This is
the same single-source-of-truth discipline as the [pipeline contract](#single-source-of-truth),
applied to defaults instead of flags.

---

## Deliverables in the output folder

```
<output>/
  taguchi_report.md
  taguchi_analysis.xlsx
  figures/            png + svg, 300 dpi
    fig_main_effects  fig_contributions  fig_per_run
    fig_size_spread_count  fig_size_spread_volume  fig_sn
  taguchi_design.json
  _job/               job.json state.json events.jsonl heartbeat worker.log timings.csv
  [csv/]              per_run.csv main_effects.csv anova.csv size_bins_*.csv results.json   (optional)
  [odd/]              odd_flags.csv + model/classical PNG pairs                             (optional)
```

Workbook sheets: `Per-run responses`, `Design matrix` (with replicates), `Main effects`,
`ANOVA`, `S-N ratios`, `Size bins (count)`, `Size bins (volume)`, `Timings`, `Provenance`.
Written with `pandas.ExcelWriter(engine="openpyxl")` — `xlsxwriter` is not installed.

Every report states the git revision, model directory, `sizer_version`, score threshold, stride
and bin edges that produced it.

---

## Implementation phases

**After every phase I stop, report what was built and what was verified, and state which model
to use for the next phase before starting it.** No phase runs on into the next.

| # | Phase | Model | Why that model |
|---|---|---|---|
| 1 | Skeleton + `theme.py` + `console.py` — three-pane window, queue + 100 ms `QTimer` drain | **Sonnet** | Mechanical scaffolding; visibly wrong if wrong |
| 2 | `pipeline_spec.py` + `preflight()` — the contract and its verification | **Opus** | Enforces the "always latest pipeline" rule; fails *silently* if subtly wrong |
| 3 | `run_discovery.py` — folder scan, xlsx read, left pane | **Sonnet** | Well-specified parsing with a known expected answer (27 runs / 9 × 3) |
| 4 | `output_tree.py` — right pane, grey mandatory ticks, ticks → kwargs | **Sonnet** | Straightforward once the spec exists |
| 5 | `jobstate.py` + `worker.py` + `eta.py` — detach, resume, heartbeat, ETA | **Opus** | Cross-platform detachment, PID-reuse-safe liveness, atomic writes; a mistake loses a 14-hour batch |
| 6 | Real batch wired through the spec, proven on the **sandbox** | **Opus** | First contact with real compute; also where the Mac inference benchmark happens |
| 7 | `design.py` — inference, two-way replicate cross-check, editable table | **Sonnet** | Logic is clear and the expected answer is known |
| 8 | `stats.py` + `size_bins.py` | **Opus** | Pure-error vs lack-of-fit df bookkeeping; wrong maths yields plausible p-values |
| 9 | `figures.py` + `report.py` + `workbook.py` | **Sonnet** | Presentation; errors are obvious on sight |
| 10 | Polish — Settings tab, Mac slow-inference warning, reattach-on-start | **Sonnet** | Small, low-risk |

Phase 2 must be finished and tested before 3–6 begin; everything downstream reads
`pipeline_spec`. Switch with `/model sonnet` and `/model opus`.

---

## Testing — a sandbox that cannot reach the 27 runs

**Hard requirement: nothing in testing touches `/Volumes/LaCie/Experiments/2026/10/05/`.**
Those 27 runs stay pristine.

### The sandbox

```
/Volumes/LaCie/Experiments/Sandbox/TaguchiUI_Test/
  runs/
    S1_090432_3000sccm_300rpm_4000sps_or1.2_bh1/
      run_summary.xlsx                         ← real file, COPIED (57 KB)
      shadowgraph/raw/CINE/recording_090506.cine  ← SYMLINK to the real cine
    S2_…  S3_…
  output/                                      ← campaign outputs land here
```

Built by `tests/make_sandbox.py`, which copies each `run_summary.xlsx` and **symlinks** the
`.cine`. Three properties make this safe and cheap, all verified:

- **No 14 GiB copy.** `process_capture.py:276` compares `cine.resolve() != local_cine.resolve()`
  before copying. A symlink resolves to the real path, so the "copy cine" stage is skipped.
- **Symlinks work on the LaCie** despite exFAT (the macOS `fskit` exfat driver supports them),
  so the sandbox can sit beside the real data in its own tree.
- **Source runs are only ever read.** Every write — frames, `predictions.json`, `droplets_0.30/`
  — lands in the sandbox run folder, because `run_dir` is the sandbox path.

Belt and braces: a `SANDBOX_ONLY` assertion in the test harness that every target `run_dir`
resolves under the sandbox root, and the sandbox-builder refuses to run if a target path lies
inside `Experiments/2026/`.

### Frame count

`--limit 40` and `--stride 10` → 40 extracted frames instead of 497, so one sandbox run takes
minutes rather than half an hour. 40 is also exactly `BG_FRAMES`, so the background gets its
full sample; `build_temporal_background` does `step = max(1, len//n_sample)` then `[:n_sample]`,
so it would degrade gracefully with fewer anyway.

Two caveats worth knowing, neither a problem for mechanism tests:

- `--limit` takes the **first** N frames, not a spread across the run, so the background is
  built from the opening ~400 cine frames only. Fine for "does the chain work", useless as a
  number.
- A limited extraction writes `"limited": true` into `extraction_metadata.json`, so
  `can_reuse()` correctly refuses it. Sandbox runs can therefore never be mistaken for real
  analyses — a feature, not a bug.

### Three test tiers

**Tier 1 — no compute, no cine, no real data (phases 7–9).** A fixture fabricates a synthetic
*analysed* campaign in the scratchpad: 9 conditions × 3 replicates of self-consistent
`droplet_sizes.csv` / `per_frame.csv` / `summary.json` / `classical_*`, with numbers chosen so
`load_run`'s D32 and atomised gates pass. Exercises discovery → design → stats → size bins →
report → workbook in under a second.

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m pytest /Users/benschofield/Documents/GitHub/HPATR/src/ai/Taguchi_Analysis_UI/tests -v
```

**Tier 2 — real pipeline, sandbox only, 40 frames (phase 6).** Build the sandbox, then run the
batch over 2–3 sandbox runs with per-frame PNGs **unticked**. This is also where the Mac
MPS/CPU inference rate gets measured.

```
cd /Users/benschofield/Documents/GitHub/HPATR && /Users/benschofield/anaconda3/envs/phantom/bin/python3 src/ai/Taguchi_Analysis_UI/tests/make_sandbox.py --runs 3 --limit 40
```

**Tier 3 — real analysis, read-only, no compute.** Analyse the nine already-measured runs under
`/Volumes/LaCie/Experiments/Taguchi/First Taguchi Trial (RPM, SCCM, Silicone Flow)/runs/` and
assert the result reproduces `results_2026-10-01/taguchi_results.json` main effects and ANOVA
within tolerance. The strongest correctness check available, and it writes nothing to the source:

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m pytest /Users/benschofield/Documents/GitHub/HPATR/src/ai/Taguchi_Analysis_UI/tests/test_l9_regression.py -v
```

### Other verification

**Preflight contract test** — every flag declared in `pipeline_spec.py` still exists in the real
scripts, so a pipeline change fails a 1-second test rather than a 14-hour batch. Paired with a
**mutation test**: a temp copy of `classical_liquid.py` with `--images-mode` renamed *must*
produce an error-level violation. That second test is the actual proof the mechanism works —
without it, a preflight that silently passes everything would look identical.

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m pytest /Users/benschofield/Documents/GitHub/HPATR/src/ai/Taguchi_Analysis_UI/tests/test_preflight.py -v
```

**Dry-run the batch machinery** — `worker.py` takes a `--pipeline-impl` injection point
(default the real `process_capture`; in tests a stub that sleeps, replays a recorded
`batch_log.txt` transcript, and writes the fixture artefacts). That makes the real failure
testable in ~10 s: spawn detached → `kill -9` mid-run → reattach → assert the interrupted run
is back to `pending` → resume → assert `timings.csv` has every row. This exercises precisely the
failure that killed the batch twice. For Windows, at minimum a unit test monkeypatching
`os.name` and asserting the `creationflags` bitmask and `STARTUPINFO` handed to `Popen`.

Progress-parser tests get their corpus for free: `batch_log.txt` already exists in every
analysed run folder.

```
/Users/benschofield/anaconda3/envs/phantom/bin/python3 -m src.ai.Taguchi_Analysis_UI.worker --job /private/tmp/claude-501/-Users-benschofield-Documents-GitHub-HPATR/e3a8cf60-789a-44d4-86ab-5d798cf6a555/scratchpad/dryrun/_job/job.json --dry-run
```

**Launch the app:**

```
cd /Users/benschofield/Documents/GitHub/HPATR && /Users/benschofield/anaconda3/envs/phantom/bin/python3 -m src.ai.Taguchi_Analysis_UI
```

**The real 27 runs are only touched once everything above passes**, and then as a deliberate,
user-initiated batch — never from a test.

---

## Open items, deliberately deferred

- **Mac runs on CPU, not MPS — correcting an earlier assumption.** `tiled_inference.auto_device()`
  returns `cpu` on macOS *deliberately*: its docstring says MPS is not auto-selected because
  "detectron2's support for it is patchy and a wrong answer is worse than a slow one". So the
  warning must be specific and non-blocking: *"device cpu — inference measured at 0.8–3.1 s/frame
  on CUDA; expect several times that here. Pass device=mps to try Metal."* Speed is still
  unmeasured; phase 6 measures it on a 40-frame sandbox run and the warning then quotes a real
  number.
- The 4-phase deep re-analysis (`phase1_inspect` … `make_report`) and the `For_Powerpoint` pack
  are **not** in scope. Those scripts live only on the LaCie, not in git — worth moving into the
  repo later so they too are versioned.
- Lamella thickness is not in scope.

---

## Implementation log

Decisions made while building, where they refine or deviate from the plan above.

### Phase 1 — skeleton, theme, console (2026-10-05)

- `paths.py` added (not in the module table): the single place that knows where the app sits
  in the repo (`REPO_ROOT`, `SRC_DIR`, `RDC_DIR`) and how to put `src/` and
  `AI/Real_Data_Code/` on `sys.path`.
- `theme.py` imports the real tokens from `gui.GUI_Clean`; a verbatim fallback takes over
  if that import ever fails (tested by blocking `serial`).

### Phase 2 — pipeline contract + preflight (2026-10-05)

- **Verified against source, not docstrings.** Two stale docstrings found:
  `process_capture.py`'s header says `measurement_<thr>` (code writes `droplets_<thr>`,
  line 326); `classical_liquid.py`'s `--images-mode` help says extremes draws "4 frames"
  (code draws 1–2, line 487).
- **Data-safety hazard found:** `classical_liquid.py:368` defaults `--root` to a real run
  (`2026/09/28/Trial_1`) and `--out-dir` to the legacy `skeletonisation_testing`. The
  contract's `classical_cmd()` always passes both; a test asserts no option combination
  can omit them.
- **Mutation tests caught a real preflight bug:** checking flags against the whole `--help`
  text let a removed `--root` pass, because the docstring's usage examples still mention it.
  Flags are now checked only against argparse's generated usage block.
- **Extreme-frame images are MANDATORY** (user decision, 2026-10-05; first built as an
  optional tick, then changed). They are grey-locked in the tree. The only way to get more
  is to tick "every frame", which *replaces* them (`measure_run` then draws every frame flat;
  `classical_liquid` writes `images/` instead of `extreme_images/`), expressed in the contract
  as `Output.only_when`. There is deliberately no way to ask for zero PNGs.
- **Exact image counts** (verified in code): `droplets_<thr>/` extremes = 1–6 PNGs, flat;
  `liquid_<thr>/extreme_images/` = 1–2 PNGs. The four named files (`__d32_lowest` etc.) in the
  First Taguchi Trial folder were assembled by hand, never by the pipeline. A named
  four-file pack assembled by this app is a possible optional output — not yet in scope.
- **ETA priors are not in `pipeline_spec.py`.** The spec is the contract; estimates belong
  to `eta.py` (phase 5), with their sources.
- `resolve_options()` / `ticks_for()` (the tick ↔ option mapping) and `verify_run_outputs()`
  live in `pipeline_spec.py` because they are contract knowledge; phases 4–6 call them.
- **Preflight runs in a fresh interpreter** (`preflight_fresh()` → `--self-check --json`) so
  pipeline edits made while the app is open are seen, using the same `sys.executable` a batch
  worker will. Script `--help` results are cached on (path, mtime, size), so edits are re-read.
- Pipeline dirtiness is scoped to `AI/Real_Data_Code`: the repo tracks `.pyc` files, so a
  whole-repo dirty flag is permanently true.
- **Tests use stdlib `unittest`** — pytest is not installed in the `phantom` env. pytest runs
  them unchanged if installed later.

### Phase 3 — run discovery + left pane (2026-10-05)

- **Surveyed the real data first** (all of `/Volumes/LaCie/Experiments/2026`): 38 run folders
  match the grammar below (27 on 10/05, 11 on 10/01); 61 older folders use a different scheme
  (`04/08/110302_N6_1.0BAR`) and are reported as *skipped, with the reason*, never dropped.
  `run_summary.xlsx` fields vary (10 older runs lack GLR/Fluid/densities); **FPS is 800 on some
  runs and 390 on others** (the earlier "390 on all 27" held for 10/05 only).
- **The folder-name grammar is not just digits.** Written by `GUI_Clean._run_id()`:
  `HHMMSS_<n>sccm|?sccm|unknownsccm_<n>rpm|norpm_<n>sps|nosps_or<x>|noor_bh<x>|nobh`. A value
  never entered becomes an explicit token. My first regex rejected the real 10/01 run
  `101035_..._or1.2_nobh`; it was caught by running the scan on real data, not by a test.
- **`run_summary.xlsx` is authoritative; the folder name is a convenience copy.** That is
  `_run_id`'s own docstring ("Do not parse it back as data"). So rpm / sps / orifice / bubbler
  height come from the workbook where it has a value; the name fills gaps and supplies the flow
  **setpoint** (the workbook only records the achieved range). Disagreement is a warning that
  says the workbook was used. `RunInfo.sources` records which won, per field. On the real
  `nobh` run the name lost the bubbler height but the workbook says 1, so it now groups with
  its `bh1` replicates. This refines the plan's "levels from folder names".
- **Three analysis states, not two:** `measured` (droplet + classical summaries), `droplets
  measured, no classical stage` (the real `nobh` run, which predates `classical_liquid.py`),
  and `new`. Legacy `measurement_`/`classical_` names are read, never written.
- **Sizer versions:** a summary with no `sizer_version` is labelled **pre-2.0.0** (that is
  what `process_capture`'s own log calls it). The pane warns when selected measured runs span
  versions. On disk: the nine 10/01 L9 runs carry no `sizer_version`; only `120606` records
  `2.0.0`. The handoff's statement that the nine are 2.0.0 does not match their `summary.json`.
- **Scan depth is 3 levels** (pick a year, month, day or run folder). Picking `Experiments/`
  itself finds nothing, and the pane says so explicitly rather than showing an empty list.
- **Fixtures mirror the real 10/05 format, and a fidelity test proves it** (`tests/fakes.py`,
  `tests/test_fakes_fidelity.py`): same tree, same 16 Metadata rows in the same order and
  types (en-dash flow range, string numerics, a newline in Notes), cine time later than folder
  time, and the real 27-run name/notes table in the real non-condition order. Fakes are
  compared against a live run whenever the LaCie is mounted.
- Deferred: the `Pressure` sheet is not read (the plan listed it as a drift covariate);
  nothing needs it yet.
- Multi-folder selection uses Qt's non-native directory dialog with its views switched to
  extended selection (native dialogs are single-select on both macOS and Windows). Folders can
  also be dragged onto the list.
- Tests: pytest now installed; 142 pass (`python -m pytest src/ai/Taguchi_Analysis_UI/tests`),
  including read-only checks against the real 10/05 and 10/01 data, one of which asserts
  discovery changes nothing on disk in a real run folder.
