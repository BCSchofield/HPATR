"""The Response surface tab: plan, check, analyse and recommend a response-surface (CCD) experiment.

A thin view over the response-surface modules, sharing the Batch tab's run selection and output folder
(as the Taguchi tab does). Five sub-tabs:

    Design            what the selected runs form (rsm_detect): banner (design type, completeness,
                      which tab), an editable table (use tick, point type, block, one column per factor
                      -- type to override a level -- a validation tick, the built sheet's status, the
                      Notes check), the findings, and the block factor. Saved to rsm_design.json.
    Model             each factor's role (surface factor, nuisance: slope, nuisance: slope and curve,
                      left out), the levels that can be set (e.g. the orifice inserts), the goals
                      (aim, ramp ends -- blank worst = the worst run seen, blank best = the best the surface
                      reaches -- importance), a time
                      term, and whether to also fit without the nuisance factors (to compare).
                      Saved to rsm_model.json.
    Analyse           runs rsm_publish on a thread: report, workbook, CSV, deck, figures, next runs;
                      buttons to open each; the recommendations listed.
    Build a run sheet the CCF builder (rsm_design): factors and levels, centres, block factor, half
                      fraction, extra runs, the pressure-check first run, seed; preview; export
                      rsm_run_sheet.json + run_sheet.xlsx / .csv / .md to the output folder (the Design
                      sub-tab then compares the captured runs with it).
    Guide             docs/RSM_GUIDE.md.

Analyse never starts a batch, and nothing is written into a run folder.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

from . import design as dz
from . import pipeline_spec as spec
from . import rsm_design as rb
from . import rsm_detect as rdet
from . import rsm_publish as rp
from . import rsm_responses as rr
from . import covariates, operating, stats, theme

MODEL_FILENAME = "rsm_model.json"
GUIDE = Path(__file__).resolve().parents[3] / "docs" / "RSM_GUIDE.md"
ROLES = (("surface", "Surface factor (mapped)"), ("nuisance-linear", "Nuisance: slope only"),
         ("nuisance-quadratic", "Nuisance: slope and curve"), ("out", "Left out (pooled into the error)"))
AIMS = (("max", "Maximise"), ("min", "Minimise"), ("target", "Hit a target"), ("ignore", "Not a goal"))
LIMITED_CHOICES = (("exclude", "Leave them out (own section)"), ("delivered", "Fit them at the gas they got"),
                   ("set", "Keep them at their set point"))
KIND_COLOURS = {rdet.CORNER: theme.CLR_TEXT, rdet.FACE: theme.CLR_TEXT, rdet.CENTRE: "#8be9a8",
                rdet.AXIAL: theme.CLR_TEXT, rdet.EDGE: theme.CLR_TEXT, rdet.CHECK: theme.CLR_ORANGE,
                rdet.OUTSIDE: theme.CLR_ORANGE, rdet.OTHER: theme.CLR_RED, rdet.MISSING: theme.CLR_RED}
LEVEL_COLOURS = {"ok": "#8be9a8", "info": theme.CLR_TEXT_SEC, "warn": theme.CLR_ORANGE, "error": theme.CLR_RED}
MARK = {"ok": "✔", "info": "•", "warn": "⚠", "error": "✖"}
ROLE_PATH = Qt.ItemDataRole.UserRole


def _table_css() -> str:
    return (f"QTableWidget {{ background-color: {theme.CLR_INPUT}; gridline-color: {theme.CLR_BORDER}; "
            f"border: 1px solid {theme.CLR_BORDER}; border-radius: 8px; }} "
            f"QHeaderView::section {{ background-color: {theme.CLR_PANEL}; color: {theme.CLR_TEXT_SEC}; "
            f"border: none; border-bottom: 1px solid {theme.CLR_BORDER}; padding: 6px; font-weight: 600; }}")


def goal_for_fit(g: dict) -> dict:
    """A Model-page goal {key, aim, worst, best, importance} as rsm_responses.resolve_goals takes it.
    "worst" scores 0 and "best" scores 1 whatever the aim: maximise ramps up from worst to best,
    minimise down from worst to best (so its low end is best), and a target scores 1 at best, falling
    to 0 at the same distance on either side as worst is. A blank worst is the worst run seen; a blank best
    is the best the fitted surface reaches in the tested region (rsm_responses.reach_surface); a blank
    target is the middle of the ramp. Saved files from before 2026-10-11 used low/high for
    the same two columns."""
    aim = g.get("aim", "max")
    worst = g.get("worst", g.get("low"))
    best = g.get("best", g.get("high"))
    if worst is not None and best is not None and (
            (aim == "max" and worst >= best) or (aim == "min" and worst <= best)):
        raise ValueError(f"goal on {g.get('label') or g['key']}: to {'maximise' if aim == 'max' else 'minimise'}, "
                         f"worst ({worst:g}) must be {'below' if aim == 'max' else 'above'} best ({best:g})")
    out = {"key": g["key"], "direction": aim, "importance": g.get("importance") or 1.0}
    if aim == "min":
        out.update(low=best, high=worst)
    elif aim == "target":
        out["target"] = best
        if best is not None and worst is not None and worst != best:
            d = abs(best - worst)
            out.update(low=best - d, high=best + d)
        else:
            out.update(low=None, high=None)
    else:
        out.update(low=worst, high=best)
    return out


def _list_css() -> str:
    return (f"QListWidget {{ background-color: {theme.CLR_PANEL}; border: 1px solid {theme.CLR_BORDER}; "
            f"border-radius: 8px; padding: 4px; }} QListWidget::item {{ padding: 3px 4px; }}")


def _banner_css(colour: str) -> str:
    return (f"color: {colour}; font-size: 13px; font-weight: 600; padding: 8px 10px; "
            f"background-color: {theme.CLR_PANEL}; border: 1px solid {theme.CLR_BORDER}; border-radius: 8px;")


def _note(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 12px;")
    return lab


def _num(text: str):
    text = (text or "").strip()
    if not text:
        return None
    return float(text)


# ---- the analysis thread --------------------------------------------------------------------------------

class RsmController(QObject):
    """Runs rsm_publish.publish off the UI thread (as AnalysisController does for the Taguchi tab)."""
    changed = Signal()
    finished = Signal(object)
    _done = Signal(object)

    def __init__(self, parent=None, publish_fn=None) -> None:
        super().__init__(parent)
        self.publish_fn = publish_fn or rp.publish
        self.log = lambda text, level="info": None
        self.busy = False
        self.progress_text = ""
        self.started_at = None
        self.last = None
        self._done.connect(self._on_done)

    def status(self) -> str:
        if not self.busy:
            return ""
        return f"Analysing … {self.progress_text}  ({int(time.time() - (self.started_at or time.time()))}s)"

    def start(self, design, output_dir: Path, **kw) -> bool:
        if self.busy:
            return False
        snapshot = copy.deepcopy(design)
        self.busy, self.progress_text, self.started_at = True, "starting", time.time()
        self.changed.emit()
        threading.Thread(target=self._work, args=(snapshot, Path(output_dir), kw), name="rsm-analysis",
                         daemon=True).start()
        return True

    def _work(self, design, output_dir, kw) -> None:
        def progress(i, n, name):
            self.progress_text = f"run {i}/{n}"
            self.log(f"response surface: run {i}/{n}  {name}", "info")
        try:
            result = self.publish_fn(design, output_dir, progress=progress, log=self.log, **kw)
        except Exception as exc:                          # noqa: BLE001 -- shown to the user
            result = rp.RsmDeliverables(output_dir)
            result.problems.append(f"analysis crashed: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc(limit=6), "error")
        self._done.emit(result)

    def _on_done(self, result) -> None:
        self.busy = False
        self.last = result
        log = self.log
        if result.refused:
            log(f"response surface REFUSED: {result.refused}", "error")
        else:
            for p in result.problems:
                log(p, "error")
            log(f"response surface done in {result.seconds:.0f}s", "ok" if not result.problems else "warn")
            for name in ("report", "workbook", "csv", "deck"):
                if getattr(result, name):
                    log(f"  {name:9s} {getattr(result, name)}", "ok")
            if result.next_runs:
                log(f"  next runs {result.next_runs[0]}", "ok")
        self.changed.emit()
        self.finished.emit(result)


# ---- the tab ------------------------------------------------------------------------------------------------

class _GasBridge(QObject):
    read = Signal(object)                 # {run path: OperatingPoint} read off the UI thread


class RsmTab(QWidget):
    def __init__(self, runs_pane, parent=None) -> None:
        super().__init__(parent)
        self.runs_pane = runs_pane
        # gas delivered per run (operating.py), read in the background for the Design page; keyed on the
        # run_summary's path and modification time, so an edited or re-saved workbook is read again
        self._ops: dict = {}
        self._ops_reading = False
        self._gas_bridge = _GasBridge()
        self._gas_bridge.read.connect(self._on_gas_read)
        self.design = rdet.RsmDesign(dz.detect([]))
        self.detected: rdet.Detected | None = None
        self.output_dir: Path | None = None
        self.sheet: rb.Sheet | None = None
        self.model: dict = {}
        self._building = False
        self._pending = False
        self.log = lambda text, level="info": None
        self.batch_busy = lambda: False
        self.analysis_provider = lambda: None          # Settings tab: stats.AnalysisOptions (None = defaults)
        self.bins_provider = lambda: None              # Settings tab: (bin width, bin maximum) in um
        self.ask_yes = lambda text: QMessageBox.question(self, "Response surface", text) == \
            QMessageBox.StandardButton.Yes
        self.controller = RsmController(self)
        self.controller.changed.connect(self.refresh_analyse)
        self.controller.finished.connect(self._finished)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(_banner_css(theme.CLR_TEXT_SEC))
        outer.addWidget(self.banner)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._design_page(), "Design")
        self.tabs.addTab(self._model_page(), "Model")
        self.tabs.addTab(self._analyse_page(), "Analyse and next runs")
        self.tabs.addTab(self._build_page(), "Build a run sheet")
        self.tabs.addTab(self._guide_page(), "Guide")
        outer.addWidget(self.tabs, 1)

        runs_pane.selection_changed.connect(self.sync_runs)
        runs_pane.output_changed.connect(self.sync_output)
        self.sync_runs()
        self.refresh_analyse()

    # ---- pages ----------------------------------------------------------------------------------------
    def _design_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Block factor:"))
        self.block_combo = QComboBox()
        self.block_combo.setToolTip("A hard-to-change factor fitted once per block (e.g. the orifice insert). "
                                    "Auto: the factor that changed only about once per level through the day.")
        self.block_combo.currentIndexChanged.connect(self._block_changed)
        bar.addWidget(self.block_combo)
        self.reset_btn = theme.ghost_button("Reset to detected")
        self.reset_btn.clicked.connect(self.reset)
        bar.addWidget(self.reset_btn)
        bar.addStretch(1)
        self.save_label = _note("")
        bar.addWidget(self.save_label)
        lay.addLayout(bar)
        lay.addWidget(_note("Untick a run to leave it out; tick Validation to keep it out of the fit and predict "
                            "it instead; type in a factor cell to correct a level (blank restores the detected "
                            "value)."))
        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(_table_css())
        self.table.itemChanged.connect(self._item_changed)
        split.addWidget(self.table)
        self.findings = QListWidget()
        self.findings.setWordWrap(True)
        self.findings.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.findings.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.findings.setStyleSheet(_list_css())
        split.addWidget(self.findings)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        return w

    def _model_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.model_note = _note("")
        lay.addWidget(self.model_note)
        self.roles_table = QTableWidget(0, 4)
        self.roles_table.setHorizontalHeaderLabels(["Factor", "Role in the model", "Levels that can be set "
                                                                                   "(blank = any value)", "Log scale"])
        self.roles_table.horizontalHeaderItem(3).setToolTip(
            "Fit this factor on ln(value). On by default for the orifice: the inserts 0.8 / 1.2 / 1.8 mm are a "
            "geometric series (evenly spaced only on a log scale), and on the CCD day a log scale predicted the "
            "0.8 mm check's pressure best. Maps and settings stay in the factor's own units.")
        self.roles_table.verticalHeader().setVisible(False)
        self.roles_table.setStyleSheet(_table_css())
        self.roles_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.roles_table, 1)
        opts = QHBoxLayout()
        self.compare_check = QCheckBox("Also fit without the nuisance factors (to see whether a term depends on them)")
        self.time_check = QCheckBox("Add a time term (drift)")
        for c in (self.compare_check, self.time_check):
            c.toggled.connect(self._save_model)
            opts.addWidget(c)
        opts.addStretch(1)
        lay.addLayout(opts)
        lim = QHBoxLayout()
        lim.addWidget(QLabel("Runs that did not get their set gas (pressure-limited):"))
        self.limited_combo = QComboBox()
        for key, text in LIMITED_CHOICES:
            self.limited_combo.addItem(text, key)
        self.limited_combo.setToolTip(
            "A run whose gas flow in the camera window was under 95% of its set point (the rig hit the supply "
            "pressure ceiling, e.g. the 0.5 mm block on 2026-10-12). Its set point does not describe it.\n"
            "Leave out: kept out of the surfaces, reported in their own section (default).\n"
            "Fit at the gas they got: the gas factor is moved to the measured flow (low gas then exists only "
            "at the small orifice, so the two cannot be separated).\n"
            "Keep at the set point: the old behaviour, for comparison.")
        self.limited_combo.currentIndexChanged.connect(self._save_model)
        lim.addWidget(self.limited_combo)
        lim.addStretch(1)
        lay.addLayout(lim)
        lay.addWidget(_note("Goals for the best setting (desirability): each response scores 0 at its worst value and "
                            "1 at its best (Maximise: worst below best; Minimise: worst above best; Hit a target: "
                            "best is the target, and the score falls to 0 as far either side as worst is). Blank worst = "
                            "the worst run seen; blank best = the best the fitted surface reaches in the tested "
                            "region (so Maximise never tops out at the best run seen). Importance weights each goal "
                            "(1 = equal). Goals only steer "
                            "the best setting and the next runs; set them any time and press Analyse again."))
        self.goals_table = QTableWidget(0, 5)
        self.goals_table.setHorizontalHeaderLabels(["Response", "Aim", "0 at (worst)", "1 at (best)", "Importance"])
        self.goals_table.verticalHeader().setVisible(False)
        self.goals_table.setStyleSheet(_table_css())
        self.goals_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.goals_table.itemChanged.connect(lambda _i: self._save_model())
        lay.addWidget(self.goals_table, 1)
        return w

    def _analyse_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        act = QHBoxLayout()
        self.analyse_btn = theme.accent_button("Analyse")
        self.analyse_btn.clicked.connect(self.analyse)
        act.addWidget(self.analyse_btn)
        self.open_btns = {}
        for key, text in (("report", "Open report"), ("deck", "Open deck"), ("next", "Open next runs"),
                          ("folder", "Open output folder")):
            b = theme.ghost_button(text)
            b.clicked.connect(lambda _=False, k=key: self._open(k))
            act.addWidget(b)
            self.open_btns[key] = b
        act.addStretch(1)
        lay.addLayout(act)
        self.analyse_label = _note("")
        lay.addWidget(self.analyse_label)
        lay.addWidget(_note("What to run next (each with its reason; the runs, numbered with the Notes to type and "
                            "their predictions, are in next_runs.xlsx):"))
        self.recs = QListWidget()
        self.recs.setWordWrap(True)
        self.recs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recs.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.recs.setStyleSheet(_list_css())
        lay.addWidget(self.recs, 1)
        return w

    def _build_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(_note("Give each factor its low, middle and high level (key: sccm, rpm, sps, orifice, bh, or "
                            "a run_summary.xlsx field). First run: low / high for the pressure-check corner (all or "
                            "none). Extra runs: one per line, factor=value, e.g. 'rpm=0, label=No-rotation control'."))
        self.build_table = QTableWidget(0, 7)
        self.build_table.setHorizontalHeaderLabels(["Key", "Label", "Low", "Middle", "High", "Short name",
                                                    "First run"])
        self.build_table.verticalHeader().setVisible(False)
        self.build_table.setStyleSheet(_table_css())
        self.build_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.build_table, 2)
        rows = QHBoxLayout()
        add = theme.ghost_button("Add factor")
        add.clicked.connect(lambda: self._add_build_row())
        rem = theme.ghost_button("Remove last factor")
        rem.clicked.connect(lambda: self.build_table.setRowCount(max(0, self.build_table.rowCount() - 1)))
        ex = theme.ghost_button("Load the 33-run example")
        ex.setToolTip("The 4-factor CCD from the 2026-10-09 plan: gas, RPM, feed, orifice; orifice blocks; "
                      "a 0 rpm control and a 0.8 mm check run")
        ex.clicked.connect(self.load_example)
        for b in (add, rem, ex):
            rows.addWidget(b)
        rows.addStretch(1)
        lay.addLayout(rows)
        form = QFormLayout()
        self.centres_spin = QSpinBox()
        self.centres_spin.setRange(1, 12)
        self.centres_spin.setValue(5)
        self.block_build = QLineEdit()
        self.block_build.setPlaceholderText("key of the hard-to-change factor, or blank")
        self.half_check = QCheckBox("Half fraction of the corners (5 factors)")
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 99999)
        self.seed_spin.setValue(1)
        self.extras_edit = QLineEdit()
        self.extras_edit.setPlaceholderText("rpm=0, label=No-rotation control; orifice=0.8")
        form.addRow("Centre runs", self.centres_spin)
        form.addRow("Block factor", self.block_build)
        form.addRow("", self.half_check)
        form.addRow("Extra runs (; between runs)", self.extras_edit)
        form.addRow("Seed (run order)", self.seed_spin)
        lay.addLayout(form)
        act = QHBoxLayout()
        b1 = theme.accent_button("Build")
        b1.clicked.connect(self.build_sheet)
        self.export_btn = theme.ghost_button("Export run sheet to the output folder")
        self.export_btn.clicked.connect(self.export_sheet)
        act.addWidget(b1)
        act.addWidget(self.export_btn)
        act.addStretch(1)
        lay.addLayout(act)
        self.build_summary = _note("")
        lay.addWidget(self.build_summary)
        self.preview = QTableWidget()
        self.preview.verticalHeader().setVisible(False)
        self.preview.setStyleSheet(_table_css())
        lay.addWidget(self.preview, 3)
        return w

    def _guide_page(self) -> QWidget:
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        try:
            view.setMarkdown(GUIDE.read_text(encoding="utf-8"))
        except OSError:
            view.setPlainText(f"The guide is missing: {GUIDE}")
        return view

    # ---- keeping in step with the Batch tab ---------------------------------------------------------------
    def sync_runs(self) -> None:
        self.design.base.update_runs(self.runs_pane.included_runs())
        self.rebuild()

    def sync_output(self) -> None:
        self.output_dir = self.runs_pane.output_folder()
        self.controller.last = None
        self.model = {}
        if self.output_dir is not None:
            saved = rdet.load_saved(self.output_dir)
            if saved is not None:
                for note in self.design.apply_saved(saved):
                    self.log(f"response surface: {note}", "warn")
            try:
                self.model = json.loads((self.output_dir / MODEL_FILENAME).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.model = {}
            self.sheet = rb.load(self.output_dir)
        self.rebuild()

    # ---- the Design page -------------------------------------------------------------------------------------
    def rebuild(self) -> None:
        d = self.design
        det = d.detect() if d.base.rows else None
        self.detected = det
        if det is None:
            self.banner.setText("Select runs on the Batch tab (or build a run sheet for a new experiment).")
            self.banner.setStyleSheet(_banner_css(theme.CLR_TEXT_SEC))
        else:
            tab, text = det.recommendation
            level = "ok" if det.complete and tab == "Response surface" else "warn" if tab == "Response surface" \
                else "info"
            if tab != "Response surface" and len(det.factors) >= 3:
                text += (" (as a whole). A surface over two of its factors can still be fitted here, with the "
                         "others as nuisance terms: see the Model page.")
            self.banner.setText(f"{MARK[level]}  {text}")
            self.banner.setStyleSheet(_banner_css(LEVEL_COLOURS[level]))
        self._fill_design_table(det)
        self._fill_findings(det)
        self._fill_block_combo(det)
        self._fill_model(det)
        self._save_design()
        self.refresh_analyse()

    def _matches(self) -> dict:
        if self.sheet is None or self.detected is None:
            return {}
        out = {}
        for m in rb.compare(self.sheet, self.detected):
            if m.point is not None:
                out[str(m.point.row.path)] = (m.status, m.note, m.row.run if m.row else None)
        return out

    # ---- gas delivered (Design page) ---------------------------------------------------------------------------
    @staticmethod
    def _gas_key(p) -> tuple:
        x = Path(p.row.path) / "run_summary.xlsx"
        try:
            return str(x), x.stat().st_mtime_ns
        except OSError:
            return str(x), None

    def _gas_text(self, p) -> tuple[str, str]:
        """(cell text, tooltip) for a point's gas delivered, '…' while it is being read."""
        op = self._ops.get(self._gas_key(p))
        if op is None:
            return "…", "reading the run's pressure log"
        set_sccm = p.values.get("sccm")
        if set_sccm is not None:
            op = operating.reclassify(op, set_sccm)
        if op.delivered_sccm is None:
            return "–", op.note
        mark = {"pressure-limited": "⚠ ", "gas short": "⚠ "}.get(op.regime, "")
        return (f"{mark}{op.delivered_sccm:,.0f} ({op.regime})",
                op.text() + (f"\n10th-90th percentile in the camera window: {op.delivered_p10:,.0f}-"
                             f"{op.delivered_p90:,.0f} sccm" if op.delivered_p10 is not None else "")
                + ("\nNot settled: still changing when the camera ran" if op.settled is False else ""))

    def _read_gas(self, det) -> None:
        if self._ops_reading or det is None:
            return
        todo = [p for p in det.points if self._gas_key(p) not in self._ops]
        if not todo:
            return
        self._ops_reading = True
        ceiling = getattr(self.analysis_provider() or stats.AnalysisOptions(), "supply_ceiling_bar",
                          operating.CEILING_BAR)

        def work() -> None:
            got = {}
            for p in todo:
                key = self._gas_key(p)
                got[key] = operating.operating_point(Path(key[0]), p.values.get("sccm"), ceiling)
            self._gas_bridge.read.emit(got)

        threading.Thread(target=work, name="rsm-gas", daemon=True).start()

    def _on_gas_read(self, got: dict) -> None:
        self._ops_reading = False
        self._ops.update(got)
        if self.detected is not None:
            self._fill_design_table(self.detected)

    def _fill_design_table(self, det) -> None:
        factors = det.factors if det else []
        heads = ["Use", "Run", "Point type", "Block"] + [f.label for f in factors] + \
                ["Gas delivered (sccm)", "Validation", "Sheet", "Check"]
        matches = self._matches()
        self._building = True
        self.table.blockSignals(True)
        try:
            self.table.clear()
            self.table.setColumnCount(len(heads))
            self.table.setHorizontalHeaderLabels(heads)
            pts = sorted(det.points if det else [], key=lambda p: (p.order or 10 ** 6, p.name))
            self.table.setRowCount(len(pts))
            for i, p in enumerate(pts):
                colour = QColor(KIND_COLOURS.get(p.kind, theme.CLR_TEXT) if p.included else "#636366")

                def cell(col, text, tip="", editable=False, check=None):
                    item = QTableWidgetItem(text)
                    flags = Qt.ItemFlag.ItemIsEnabled
                    if editable:
                        flags |= Qt.ItemFlag.ItemIsEditable
                    if check is not None:
                        flags |= Qt.ItemFlag.ItemIsUserCheckable
                        item.setCheckState(Qt.CheckState.Checked if check else Qt.CheckState.Unchecked)
                    item.setFlags(flags)
                    item.setForeground(QBrush(colour))
                    item.setToolTip(tip)
                    item.setData(ROLE_PATH, str(p.row.path))
                    self.table.setItem(i, col, item)
                    return item
                cell(0, "", check=p.included)
                cell(1, f"{p.row.date or ''} {p.row.time or p.name}".strip(), f"{p.name}\n{p.row.notes or ''}")
                cell(2, rdet.KIND_TEXT.get(p.kind, p.kind) + (f" (×{p.n_same})" if p.n_same > 1 else ""))
                cell(3, p.block or "")
                for j, f in enumerate(factors):
                    v = p.row.value(f.key)
                    item = cell(4 + j, "" if v is None else f"{v:g}" if isinstance(v, (int, float)) else str(v),
                                "EDITED (detected: %s)" % p.row.detected.get(f.key) if f.key in p.row.overrides
                                else "type to correct this level", editable=True)
                    item.setData(ROLE_PATH + 1, f.key)
                    if f.key in p.row.overrides:
                        item.setForeground(QBrush(QColor(theme.CLR_ACCENT)))
                gtext, gtip = self._gas_text(p)
                gitem = cell(4 + len(factors), gtext, gtip)
                if gtext.startswith("⚠"):
                    gitem.setForeground(QBrush(QColor(theme.CLR_ORANGE)))
                cell(5 + len(factors), "", "kept out of the fit and predicted instead", check=p.validation)
                status, note, run_no = matches.get(str(p.row.path), ("", "", None))
                cell(6 + len(factors), (f"run {run_no}: " if run_no else "") + status, note)
                cell(7 + len(factors), "; ".join(p.flags), "; ".join(p.flags))
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(len(heads) - 1, QHeaderView.ResizeMode.Stretch)
        finally:
            self.table.blockSignals(False)
            self._building = False
        self._read_gas(det)

    def _fill_findings(self, det) -> None:
        self.findings.clear()
        for f in (det.findings if det else []):
            item = QListWidgetItem(f"{MARK.get(f.level, '•')}  {f.text}")
            item.setForeground(QBrush(QColor(LEVEL_COLOURS.get(f.level, theme.CLR_TEXT))))
            self.findings.addItem(item)
        if self.sheet is not None and det is not None:
            counts: dict = {}
            for m in rb.compare(self.sheet, det):
                counts[m.status] = counts.get(m.status, 0) + 1
            self.findings.addItem(QListWidgetItem("•  Against the built run sheet: " +
                                                  ", ".join(f"{n} {s}" for s, n in counts.items())))

    def _fill_block_combo(self, det) -> None:
        self.block_combo.blockSignals(True)
        self.block_combo.clear()
        self.block_combo.addItem("Auto", "auto")
        self.block_combo.addItem("None", None)
        for f in (det.factors if det else []):
            self.block_combo.addItem(f.label, f.key)
        idx = self.block_combo.findData(self.design.block_factor)
        self.block_combo.setCurrentIndex(max(0, idx))
        self.block_combo.blockSignals(False)

    def _block_changed(self) -> None:
        if self._building:
            return
        self.design.block_factor = self.block_combo.currentData()
        self._defer()

    def _item_changed(self, item) -> None:
        if self._building:
            return
        path = item.data(ROLE_PATH)
        row = next((r for r in self.design.base.rows if str(r.path) == path), None)
        if row is None:
            return
        n_f = len(self.detected.factors) if self.detected else 0
        col = item.column()
        if col == 0:
            row.included = item.checkState() == Qt.CheckState.Checked
        elif col == 5 + n_f:                    # Validation (4 + n_f is Gas delivered, read-only)
            if item.checkState() == Qt.CheckState.Checked:
                self.design.validation.add(row.path)
            else:
                self.design.validation.discard(row.path)
        elif item.data(ROLE_PATH + 1):
            key = item.data(ROLE_PATH + 1)
            text = item.text().strip()
            if not text:
                row.overrides.pop(key, None)
            else:
                try:
                    self.design.base.set_value(row, key, float(text))
                except ValueError:
                    self.design.base.set_value(row, key, text)
        else:
            return
        self._defer()

    def _defer(self) -> None:
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._finish)

    def _finish(self) -> None:
        self._pending = False
        self.rebuild()

    def reset(self) -> None:
        if not self.ask_yes("Discard every edit to the response-surface design and detect it again?"):
            return
        self.design = rdet.RsmDesign(dz.detect(self.runs_pane.included_runs()))
        self.rebuild()

    def _save_design(self) -> None:
        if self.output_dir is None:
            self.save_label.setText("choose an output folder to keep your edits")
            return
        if not self.design.base.rows:
            return
        try:
            rdet.save(self.design, self.output_dir)
            self.save_label.setText(f"saved: {rdet.DESIGN_FILENAME}")
        except OSError as exc:
            self.save_label.setText(f"could not save: {exc}")

    # ---- the Model page ------------------------------------------------------------------------------------
    def default_model(self, det) -> dict:
        """Surface over every factor for a response-surface design; for an orthogonal array (the 9x3),
        the first two of gas / feed / RPM / orifice as the surface and the rest as nuisance terms, with the
        comparison fit (the Phase 4b trial). Fixed-size factors (orifice) get their sizes as settable levels."""
        from .rsm_figures import PAIR_PREFERENCE
        keys = [f.key for f in det.factors]
        roles = {k: "surface" for k in keys}
        compare = False
        if det.type_key == "oa" and len(keys) >= 3:
            order = sorted(keys, key=lambda k: PAIR_PREFERENCE.index(k) if k in PAIR_PREFERENCE else 99)
            for k in order[2:]:
                roles[k] = "nuisance-quadratic"
            compare = True
        discrete = {}
        for f in det.factors:
            if f.key == "orifice":
                vals = sorted(set(f.levels) | {v for v, kind in f.special.items() if kind == rdet.CHECK})
                discrete[f.key] = ", ".join(f"{v:g}" for v in vals)
        goals = [{"key": k, "aim": d, "worst": None, "best": None, "importance": w} for k, d, w in rr.DEFAULT_GOALS]
        return {"roles": roles, "discrete": discrete, "compare": compare, "time": False, "goals": goals,
                "limited": "exclude", "log": [f.key for f in det.factors if f.key == "orifice"]}

    def _fill_model(self, det) -> None:
        if det is None or not det.factors:
            self.roles_table.setRowCount(0)
            self.model_note.setText("No design yet.")
            return
        keys = [f.key for f in det.factors]
        if not self.model or set(self.model.get("roles", {})) != set(keys):
            self.model = self.default_model(det)
        m = self.model
        self.model_note.setText(
            "These runs are an orthogonal array (a Taguchi L9): a surface can only be fitted over two factors, "
            "with the other kept as a nuisance term. The defaults reproduce the 9x3 gas × feed trial."
            if det.type_key == "oa" else
            "Every factor is a surface factor by default. Make a factor a nuisance term to keep it in the model "
            "without mapping it.")
        self._building = True
        try:
            self.roles_table.setRowCount(len(det.factors))
            for i, f in enumerate(det.factors):
                it = QTableWidgetItem(f.label)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.roles_table.setItem(i, 0, it)
                combo = QComboBox()
                for key, text in ROLES:
                    combo.addItem(text, key)
                combo.setCurrentIndex(max(0, combo.findData(m["roles"].get(f.key, "surface"))))
                combo.currentIndexChanged.connect(self._save_model)
                self.roles_table.setCellWidget(i, 1, combo)
                lv = QLineEdit(m.get("discrete", {}).get(f.key, ""))
                lv.setPlaceholderText("e.g. 0.5, 0.8, 1.2, 1.8")
                lv.editingFinished.connect(self._save_model)
                self.roles_table.setCellWidget(i, 2, lv)
                lg = QCheckBox()
                # a model saved before the log option (2026-10-13) gets the default: orifice on a log scale
                lg.setChecked(f.key in m.get("log", ["orifice"]))
                lg.setEnabled(bool(f.numeric) and all(float(v) > 0 for v in f.levels))
                lg.toggled.connect(self._save_model)
                self.roles_table.setCellWidget(i, 3, lg)
            self.compare_check.setChecked(bool(m.get("compare")))
            self.time_check.setChecked(bool(m.get("time")))
            self.limited_combo.setCurrentIndex(max(0, self.limited_combo.findData(m.get("limited", "exclude"))))
            table = stats.responses_table()
            self.goals_table.blockSignals(True)
            self.goals_table.setRowCount(len(table))
            goals = {g["key"]: g for g in m.get("goals", [])}
            flow_problem = covariates.formula_problem()
            for i, (key, label, direction, _q) in enumerate(table):
                g = goals.get(key)
                it = QTableWidgetItem(label)
                if key == "af_flow" and flow_problem:
                    # say so where the goal is chosen, not only after Analyse
                    it.setText(f"⚠ {label}: unavailable on this PC")
                    it.setToolTip("The capture GUI's flow formula could not be imported "
                                  f"({flow_problem}), so there is no liquid mL/min and this "
                                  "response has no values: a goal on it would be dropped.")
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                it.setData(ROLE_PATH, key)
                self.goals_table.setItem(i, 0, it)
                aim = QComboBox()
                for a, text in AIMS:
                    aim.addItem(text, a)
                aim.setCurrentIndex(aim.findData(g["aim"] if g else "ignore"))
                aim.currentIndexChanged.connect(self._save_model)
                self.goals_table.setCellWidget(i, 1, aim)
                for col, field in ((2, "worst"), (3, "best"), (4, "importance")):
                    v = (g.get(field, g.get({"worst": "low", "best": "high"}.get(field, field))) if g
                         else (1.0 if field == "importance" else None))
                    self.goals_table.setItem(i, col, QTableWidgetItem("" if v is None else f"{v:g}"))
            self.goals_table.blockSignals(False)
        finally:
            self._building = False

    def read_model(self) -> dict:
        """The Model page as a dict (what is saved and what Analyse uses)."""
        if self.detected is None:
            return self.model
        roles, discrete, log = {}, {}, []
        for i, f in enumerate(self.detected.factors):
            roles[f.key] = self.roles_table.cellWidget(i, 1).currentData()
            text = self.roles_table.cellWidget(i, 2).text().strip()
            if text:
                discrete[f.key] = text
            lg = self.roles_table.cellWidget(i, 3)
            if lg is not None and lg.isChecked():
                log.append(f.key)
        goals = []
        labels = {k: lab for k, lab, _d, _q in stats.responses_table()}
        for i in range(self.goals_table.rowCount()):
            aim = self.goals_table.cellWidget(i, 1)
            if aim is None or aim.currentData() == "ignore":
                continue
            vals = {}
            for col, field in ((2, "worst"), (3, "best"), (4, "importance")):
                item = self.goals_table.item(i, col)
                try:
                    vals[field] = _num(item.text() if item else "")
                except ValueError:
                    vals[field] = None
            key = self.goals_table.item(i, 0).data(ROLE_PATH)
            # the response's own label, not the cell text (which may carry an "unavailable" mark)
            goals.append({"key": key, "aim": aim.currentData(),
                          "label": labels.get(key, self.goals_table.item(i, 0).text()), **vals})
        return {"roles": roles, "discrete": discrete, "compare": self.compare_check.isChecked(),
                "time": self.time_check.isChecked(), "goals": goals,
                "limited": self.limited_combo.currentData() or "exclude", "log": log}

    def _save_model(self, *_a) -> None:
        if self._building:
            return
        self.model = self.read_model()
        if self.output_dir is not None:
            try:
                (self.output_dir / MODEL_FILENAME).write_text(json.dumps(self.model, indent=2), encoding="utf-8")
            except OSError as exc:
                self.log(f"response surface: could not save the model choices: {exc}", "warn")

    def models_and_options(self) -> tuple[list, dict]:
        """ModelSpecs, goals and settable levels for rsm_publish, from the Model page."""
        m = self.read_model()
        axis = [k for k, r in m["roles"].items() if r == "surface"]
        nuisance = {k: ("quadratic" if r == "nuisance-quadratic" else "linear")
                    for k, r in m["roles"].items() if r.startswith("nuisance")}
        if len(axis) < 1:
            raise ValueError("choose at least one surface factor on the Model page")
        label = {f.key: f.label.split(" (")[0] for f in (self.detected.factors if self.detected else [])}
        name_a = " × ".join(label.get(k, k) for k in axis) + (
            " + " + ", ".join(label.get(k, k) for k in nuisance) + " as nuisance terms" if nuisance else "")
        models = [rp.ModelSpec(f"(a) {name_a}", axis, nuisance, time_term=m["time"])]
        if m["compare"] and nuisance:
            models.append(rp.ModelSpec("(b) " + " × ".join(label.get(k, k) for k in axis) +
                                       " only (nuisance factors pooled into the error)", axis, time_term=m["time"]))
        discrete = {}
        for k, text in m["discrete"].items():
            discrete[k] = [float(x) for x in text.replace(";", ",").split(",") if x.strip()]
        goals = [goal_for_fit(g) for g in m["goals"]]
        return models, {"goals": goals or None, "discrete": discrete or None,
                        "limited": m.get("limited", "exclude"),
                        "log_scale": list(m["log"]) if "log" in m else None}

    # ---- the Analyse page --------------------------------------------------------------------------------------
    def analyse_blocker(self) -> str | None:
        if self.controller.busy:
            return "Analysing …"
        if self.output_dir is None:
            return "Choose an output folder on the Batch tab first"
        if self.detected is None or not any(p.in_fit for p in self.detected.points):
            return "Tick the runs to analyse on the Batch tab"
        return None

    def refresh_analyse(self) -> None:
        why = self.analyse_blocker()
        self.analyse_btn.setEnabled(why is None)
        self.analyse_btn.setText("Analysing …" if self.controller.busy else "Analyse")
        self.analyse_btn.setToolTip(why or "Fit the surfaces and write the report, workbook, deck, figures and "
                                           "next runs to the output folder")
        last = self.controller.last
        for key, attr in (("report", "report"), ("deck", "deck")):
            self.open_btns[key].setEnabled(bool(last and getattr(last, attr)))
        self.open_btns["next"].setEnabled(bool(last and last.next_runs))
        self.open_btns["folder"].setEnabled(self.output_dir is not None)
        if self.controller.busy:
            self.analyse_label.setText(self.controller.status())
        elif last is None:
            self.analyse_label.setText(why or "")

    def analyse(self) -> None:
        why = self.analyse_blocker()
        if why:
            self.log(f"response surface: {why}", "warn")
            return
        try:
            models, opts = self.models_and_options()
        except ValueError as exc:
            self.analyse_label.setText(f"✖ {exc}")
            return
        if self.batch_busy() and not self.ask_yes("A batch is still running; runs it has not measured yet will be "
                                                  "left out. Analyse anyway?"):
            return
        self.controller.log = self.log
        thr = spec.effective(self.runs_pane.settings).score_thresh
        aopts = self.analysis_provider()
        if aopts is not None:
            opts = {**opts, "analysis_opts": aopts}
        bins = self.bins_provider()
        if bins is not None:
            opts = {**opts, "bin_width": bins[0], "bin_max": bins[1]}
        self.controller.start(self.design, self.output_dir, models=models, thr=thr,
                              title="Response-surface analysis", **opts)

    def _finished(self, d) -> None:
        self.recs.clear()
        if d.refused:
            self.analyse_label.setText("✖ Refused: " + d.refused)
            self.analyse_label.setStyleSheet(f"color: {theme.CLR_RED}; font-size: 12px;")
        else:
            ok = not d.problems
            R = next(iter(d.models.values()), None)
            best = ""
            if R is not None and R.optimum is not None:
                from .rsm_report import num
                label = {f.key: f.label for f in R.loaded.detected.factors}
                best = " Best setting: " + ", ".join(f"{label.get(k, k)} {num(R.decode(k, c))}"
                                                     for k, c in R.optimum.coded.items())
            self.analyse_label.setText(("✔ Done." if ok else "⚠ Finished with problems: " + "; ".join(d.problems))
                                       + best)
            self.analyse_label.setStyleSheet(f"color: {theme.CLR_GREEN if ok else theme.CLR_ORANGE}; font-size: 12px;")
            if R is not None:
                from . import rsm_recommend
                for r in rsm_recommend.recommend(R, R.discrete):
                    item = QListWidgetItem(f"{r.title}\n{r.why}")
                    self.recs.addItem(item)
        self.refresh_analyse()

    def _open(self, what: str) -> None:
        last = self.controller.last
        target = {"report": getattr(last, "report", None), "deck": getattr(last, "deck", None),
                  "next": (last.next_runs[1] if last and len(last.next_runs) > 1 else None),
                  "folder": self.output_dir}.get(what) or self.output_dir
        if target is not None and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.log(f"could not open {target}", "warn")

    # ---- the Build page -------------------------------------------------------------------------------------------
    def _add_build_row(self, values=("", "", "", "", "", "", "")) -> None:
        r = self.build_table.rowCount()
        self.build_table.setRowCount(r + 1)
        for c, v in enumerate(values):
            self.build_table.setItem(r, c, QTableWidgetItem(str(v)))

    def load_example(self) -> None:
        self.build_table.setRowCount(0)
        for row in (("sccm", "Gas flow (sccm)", 7000, 9000, 11000, "Gas", "high"),
                    ("rpm", "Bubbler RPM", 100, 500, 900, "RPM", "high"),
                    ("sps", "Silicone (steps/s)", 3000, 4000, 5000, "Feed", "high"),
                    ("orifice", "Orifice (mm)", 0.5, 1.2, 1.8, "Orifice", "low")):
            self._add_build_row(row)
        self.centres_spin.setValue(5)
        self.block_build.setText("orifice")
        self.half_check.setChecked(False)
        self.extras_edit.setText("rpm=0, label=No-rotation control (not in the fit); orifice=0.8")
        self.seed_spin.setValue(1)

    def read_plan(self) -> rb.Plan:
        factors, first = [], {}
        for r in range(self.build_table.rowCount()):
            cells = [(self.build_table.item(r, c).text().strip() if self.build_table.item(r, c) else "")
                     for c in range(7)]
            if not cells[0]:
                continue
            key, label = cells[0], cells[1] or cells[0]
            try:
                lo, mid, hi = float(cells[2]), float(cells[3]), float(cells[4])
            except ValueError:
                raise rb.PlanError(f"{label}: low, middle and high must be numbers") from None
            factors.append(rb.FactorSpec(key, label, lo, mid, hi, cells[5]))
            if cells[6]:
                first[key] = cells[6].lower()
        centre = {f.key: f.mid for f in factors}
        extras = []
        for chunk in [c for c in self.extras_edit.text().split(";") if c.strip()]:
            vals, label = dict(centre), ""
            for part in chunk.split(","):
                if "=" not in part:
                    continue
                k, v = (x.strip() for x in part.split("=", 1))
                if k == "label":
                    label = v
                elif k in vals:
                    vals[k] = float(v)
                else:
                    raise rb.PlanError(f"extra run '{chunk.strip()}': '{k}' is not one of the factors")
            extras.append(rb.Extra(vals, label))
        return rb.Plan(factors=factors, centres=self.centres_spin.value(),
                       block_factor=self.block_build.text().strip() or None,
                       fraction="half" if self.half_check.isChecked() else None, extras=extras,
                       first=first or None, seed=self.seed_spin.value())

    def build_sheet(self) -> bool:
        try:
            self.sheet = rb.build_sheet(self.read_plan())
        except rb.PlanError as exc:
            self.build_summary.setText(f"✖ {exc}")
            self.build_summary.setStyleSheet(f"color: {theme.CLR_RED}; font-size: 12px;")
            return False
        self.build_summary.setText("\n".join(rb.summary(self.sheet)))
        self.build_summary.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 12px;")
        rows = rb.table(self.sheet)
        self.preview.clear()
        self.preview.setColumnCount(len(rows[0]))
        self.preview.setRowCount(len(rows))
        self.preview.setHorizontalHeaderLabels(list(rows[0]))
        for i, row in enumerate(rows):
            for j, v in enumerate(row.values()):
                self.preview.setItem(i, j, QTableWidgetItem(f"{v:g}" if isinstance(v, float) else str(v)))
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        return True

    def export_sheet(self) -> list[Path]:
        if self.output_dir is None:
            self.build_summary.setText("✖ Choose an output folder on the Batch tab first")
            return []
        if self.sheet is None and not self.build_sheet():
            return []
        rb.save(self.sheet, self.output_dir)
        files = rb.export(self.sheet, self.output_dir)
        self.log(f"run sheet: written {', '.join(p.name for p in files)} to {self.output_dir}", "ok")
        self.build_summary.setText(self.build_summary.text() + f"\n✔ Exported to {self.output_dir}")
        self.rebuild()
        return files
