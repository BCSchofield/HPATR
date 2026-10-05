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
from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from . import pipeline_spec as spec
from . import theme
from .console import ConsolePane
from .pane_outputs import OutputsPane
from .pane_runs import RunsPane


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
        main_split.addWidget(self.console)
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)

        outer.addWidget(main_split)
        self.update_outputs_context()

    def update_outputs_context(self) -> None:
        """Describe the first selected run (the tree shows ONE example) and the chosen
        output folder. Never changes a tick."""
        runs = self.runs_pane.included_runs()
        out = self.runs_pane.output_folder()
        self.outputs_pane.set_context(
            run_name=runs[0].name if runs else None,
            thr=spec.effective(self.runs_pane.settings).score_thresh,
            n_runs=len(runs), output_dir=str(out) if out else None)


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
        tabs.addTab(
            PlaceholderTab(
                "Taguchi design table + analysis\n(Phase 7: auto-detect, editable factors/levels)"
            ),
            "  Taguchi  ",
        )
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
        if not report.ok:
            self.batch_tab.runs_pane.run_btn.setEnabled(False)
            self.batch_tab.runs_pane.run_btn.setToolTip(
                "Disabled: the pipeline no longer matches pipeline_spec.py -- see the console"
            )


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
