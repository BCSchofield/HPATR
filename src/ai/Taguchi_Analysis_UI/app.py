"""Taguchi_Analysis_UI main window.

Phase 1 scope: the window shell only — three-pane Batch tab (selected
runs / output tree / console) plus placeholder Taguchi and Settings
tabs. No pipeline logic lives here; later phases wire real content into
these same panes without changing this file's structure.
"""
from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from dataclasses import replace

from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from . import pipeline_spec as spec
from . import theme
from . import reanalysis
from .batch_controller import LIVE, BatchController, confirm_text
from .console import ConsolePane
from .pane_outputs import OutputsPane
from .pane_runs import RunsPane
from .tab_taguchi import TaguchiTab


class BatchTab(QWidget):
    """The window layout's main view: left/right panes over a full-width
    console, both resizable via nested QSplitters."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        panes_split = QSplitter(Qt.Orientation.Horizontal)
        self.runs_pane = RunsPane()
        self.outputs_pane = OutputsPane()
        panes_split.addWidget(self.runs_pane)
        panes_split.addWidget(self.outputs_pane)
        panes_split.setStretchFactor(0, 4)
        panes_split.setStretchFactor(1, 5)
        panes_split.setSizes([560, 700])

        main_split = QSplitter(Qt.Orientation.Vertical)
        main_split.addWidget(panes_split)
        self.console = ConsolePane()
        self.runs_pane.log = self.console.log
        self.runs_pane.selection_changed.connect(self.update_outputs_context)
        self.runs_pane.output_changed.connect(self.update_outputs_context)
        self.runs_pane.mode_changed.connect(self.update_outputs_context)
        main_split.addWidget(self.console)
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)

        outer.addWidget(main_split)
        self.update_outputs_context()

        # ---- batch control ----
        self.preflight_report = None
        self.controller = BatchController(self.console.log, self)
        self.console.set_status_provider(self.controller.status)
        self.controller.changed.connect(self.refresh_buttons)
        # repaint the status line the moment the batch changes state, not up to 1 s later
        self.controller.changed.connect(self.console.repaint_status)
        self.runs_pane.output_changed.connect(
            lambda: self.controller.attach(self.runs_pane.output_folder()))
        self.runs_pane.selection_changed.connect(self.refresh_buttons)
        self.runs_pane.mode_changed.connect(self.refresh_buttons)
        self.runs_pane.run_btn.clicked.connect(self._on_run)
        self.runs_pane.aux_btn.clicked.connect(self._on_aux)
        self.runs_pane.stop_btn.clicked.connect(self._on_stop_now)
        self.confirm = self._ask             # tests replace this with lambda text: True
        self.refresh_buttons()
        remembered = self.runs_pane.remembered_output_folder()
        if remembered:
            self.runs_pane.set_output_folder(remembered, remember=False)

    # ---- readiness + buttons ------------------------------------------------------
    def set_preflight(self, report) -> None:
        self.preflight_report = report
        self.refresh_buttons()

    def plan(self) -> reanalysis.Plan:
        """What Run batch would do with the current selection and the existing-results setting."""
        return reanalysis.plan_runs(self.runs_pane.included_runs(), self.runs_pane.existing_mode())

    def runnable_runs(self):
        return self.plan().process

    def ready_for_new(self) -> tuple[bool, str]:
        if self.preflight_report is None:
            return False, "Checking the pipeline \u2026"
        if not self.preflight_report.ok:
            return False, "Disabled: the pipeline no longer matches pipeline_spec.py (see console)"
        if self.runs_pane.output_folder() is None:
            return False, "Choose an output folder first"
        plan = self.plan()
        if not plan.process:
            if plan.skipped or plan.cannot:
                n = len(plan.skipped) + len(plan.cannot)
                return False, (f"Nothing to run: all {n} selected run(s) already have results and "
                               f"'{reanalysis.MODE_LABEL[reanalysis.SKIP]}' is chosen. Choose "
                               f"Re-measure or Redo everything to run them again; the statistics "
                               f"use the existing results either way.")
            return False, "Tick at least one run that has a .cine to analyse"
        n = len(plan.process)
        extra = f"; {len(plan.skipped)} left as they are" if plan.skipped else ""
        return True, f"Analyse {n} run{'s' if n != 1 else ''} in the background{extra}"

    def refresh_buttons(self) -> None:
        c, rp = self.controller, self.runs_pane
        mode = c.mode
        rp.stop_btn.setVisible(mode in LIVE)
        rp.aux_btn.hide()
        self._run_role = None
        if mode == "starting":
            rp.run_btn.setText("Starting \u2026")
            rp.run_btn.setEnabled(False)
        elif mode in LIVE:
            if c.stop_requested:
                rp.run_btn.setText("Stopping after this run \u2026")
                rp.run_btn.setEnabled(False)
            else:
                rp.run_btn.setText("Stop after this run")
                rp.run_btn.setEnabled(True)
                rp.run_btn.setToolTip("Finish the run in progress, then stop. Resume any time.")
                self._run_role = "stop"
        elif c.live is not None and c.live.resumable:
            rp.run_btn.setText(f"Resume ({c.live.n_done}/{c.live.n_total} done)")
            rp.run_btn.setEnabled(True)
            rp.run_btn.setToolTip("Carry on from where the batch stopped")
            self._run_role = "resume"
            ready, why = self.ready_for_new()
            rp.aux_btn.setText("New batch")
            rp.aux_btn.setEnabled(ready)
            rp.aux_btn.setToolTip(why if not ready else
                                  "Start a new batch from the current selection "
                                  "(the unfinished one is archived, not deleted)")
            rp.aux_btn.show()
            self._aux_role = "new"
        else:
            ready, why = self.ready_for_new()
            rp.run_btn.setText("Run batch")
            rp.run_btn.setEnabled(ready)
            rp.run_btn.setToolTip(why)
            self._run_role = "new" if ready else None
            failed = c.counts().get("failed", 0)
            if mode == "finished_with_failures" and failed:
                rp.aux_btn.setText(f"Retry failed ({failed})")
                rp.aux_btn.setEnabled(True)
                rp.aux_btn.setToolTip("Run only the failed runs again, reusing finished work")
                rp.aux_btn.show()
                self._aux_role = "retry"

    # ---- actions ----------------------------------------------------------------------
    def _ask(self, text: str, title: str = "Start batch") -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _settings(self):
        # reuse (everything except "redo"): re-running keeps finished extraction + inference
        # when process_capture.can_reuse() says they are still valid (same stride, complete,
        # newer than the model). "Redo everything" turns it off.
        return reanalysis.settings_for(self.runs_pane.existing_mode(), self.runs_pane.settings)

    def _on_run(self) -> None:
        role = getattr(self, "_run_role", None)
        if role == "new":
            self.start_new()
        elif role == "stop":
            self.controller.stop_after_run()
        elif role == "resume":
            self.controller.resume()

    def _on_aux(self) -> None:
        role = getattr(self, "_aux_role", None)
        if role == "retry":
            self.controller.resume(retry_failed=True)
        elif role == "new":
            self.start_new()

    def start_new(self) -> None:
        ready, why = self.ready_for_new()
        if not ready:
            self.console.log(why, "warn")
            return
        plan, out = self.plan(), self.runs_pane.output_folder()
        runs = plan.process
        options, settings = self.outputs_pane.options(), self._settings()
        text = confirm_text(plan, options, settings, out)
        if self.controller.live is not None and self.controller.live.resumable:
            text += ("\n\nThe unfinished batch already in this folder will be archived "
                     "(moved to _job_archive, not deleted) and cannot then be resumed.")
        if not self.confirm(text):
            return
        self.controller.start(out, [r.path for r in runs], settings, options)

    def _on_stop_now(self) -> None:
        if self.confirm("Stop the batch now?\n\nThe run in progress is interrupted and redone "
                        "on Resume (finished frames and inference are reused). Finished runs "
                        "are kept.", "Stop now"):
            self.controller.stop_now()

    def update_outputs_context(self) -> None:
        """Describe the first run the batch will PROCESS (the tree shows ONE example) and how
        many there are. Runs left as they are (already have results) are not counted: the tree
        and the disk estimate describe what Run batch will do, not what is merely selected.
        Never changes a tick."""
        runs = self.runs_pane.included_runs()
        plan = reanalysis.plan_runs(runs, self.runs_pane.existing_mode())
        shown = plan.process or runs
        out = self.runs_pane.output_folder()
        self.outputs_pane.set_context(
            run_name=shown[0].name if shown else None,
            thr=spec.effective(self.runs_pane.settings).score_thresh,
            n_runs=len(plan.process), output_dir=str(out) if out else None)


class PlaceholderTab(QWidget):
    """A single centred note for tabs not yet built."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 13px;")
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addStretch(1)


class _PreflightBridge(QObject):
    """Carries the preflight result from its worker thread to the main thread
    (a signal emitted off-thread is delivered queued, on the receiver's thread)."""
    done = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.preflight_report = None  # PreflightReport once checked; gates the batch
        self.setWindowTitle("Taguchi Analysis")
        self.resize(1400, 900)

        tabs = QTabWidget()
        self.batch_tab = BatchTab()
        tabs.addTab(self.batch_tab, "  Batch  ")
        self.taguchi_tab = TaguchiTab(self.batch_tab.runs_pane)
        self.taguchi_tab.log = self.batch_tab.console.log
        tabs.addTab(self.taguchi_tab, "  Taguchi  ")
        tabs.addTab(
            PlaceholderTab(
                "Auto-populated settings\n(Phase 10: score threshold, stride, device, model dir, bin width)"
            ),
            "  Settings  ",
        )
        self.setCentralWidget(tabs)

        if theme.SOURCE == "fallback":
            self.batch_tab.console.log(
                f"theme: using fallback tokens (GUI_Clean import failed: {theme.IMPORT_ERROR})"
            )
        else:
            self.batch_tab.console.log("theme: tokens loaded from gui.GUI_Clean")

        self._preflight_bridge = _PreflightBridge()
        self._preflight_bridge.done.connect(self._on_preflight)
        self.run_preflight()

    def run_preflight(self) -> None:
        """Verify the pipeline contract in a FRESH interpreter (the code a new
        batch would actually run), off the UI thread. Called at startup; later
        phases call it again immediately before every batch."""
        console = self.batch_tab.console
        console.log("preflight: verifying pipeline_spec.py against AI/Real_Data_Code ...")

        def work() -> None:
            from .pipeline_spec import preflight_fresh
            report = preflight_fresh()
            for line in report.render():
                console.log(line)
            self._preflight_bridge.done.emit(report)

        threading.Thread(target=work, name="preflight", daemon=True).start()

    def _on_preflight(self, report) -> None:
        self.preflight_report = report
        self.batch_tab.set_preflight(report)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Taguchi Analysis")
    app.setApplicationDisplayName("Taguchi Analysis")

    theme.apply_fusion_style(app)

    window = MainWindow()
    theme.restyle_inputs(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
