"""LEFT pane: pick run folders, see what was found, choose the output folder.

Thin UI over run_discovery. All the knowledge about what a run folder is lives
there; this file only turns it into widgets. Discovery runs on a background
thread (each run reads an xlsx off the LaCie) and reports back by signal, so the
window never freezes and the console shows progress.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget,
    QListWidgetItem, QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from . import paths, theme
from . import pipeline_spec as spec
from . import run_discovery as rd

PICK_TITLE = ("Select run folders -- or a day / month / year folder to add every run inside "
              "(Cmd/Ctrl-click or Shift-click for several)")
SETTINGS_ORG, SETTINGS_APP = "HPATR", "TaguchiAnalysisUI"
ROLE_PATH = Qt.ItemDataRole.UserRole


def default_start_dir() -> Path:
    """Last folder used, else <LaCie>/Experiments/<this year>, else home."""
    try:
        last = QSettings(SETTINGS_ORG, SETTINGS_APP).value("last_run_dir", "", type=str)
        if last and Path(last).is_dir():
            return Path(last)
    except Exception:
        pass
    try:
        paths.ensure_src_on_path()
        from config_loader import find_lacie_drive
        drive = find_lacie_drive()
        if drive:
            exp = Path(drive) / "Experiments"
            return next((p for p in sorted(exp.glob("20*"), reverse=True) if p.is_dir()), exp)
    except Exception:
        pass
    return Path.home()


def pick_directories(parent, title: str, start: Path) -> list[Path]:
    """A directory dialog that allows SEVERAL folders at once.

    Qt's native directory dialogs are single-select on both macOS and Windows.
    The non-native Qt dialog is multi-select once its inner views are switched
    to ExtendedSelection (the standard workaround), which is what lets you pick
    runs from different days in one go.
    """
    dlg = QFileDialog(parent, title, str(start))
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    enable_multi_select(dlg)
    if dlg.exec():
        return [Path(p) for p in dlg.selectedFiles()]
    return []


def enable_multi_select(dlg: QFileDialog) -> int:
    """Switch the dialog's views to extended selection. Returns how many views
    were switched (tests assert it is not zero, i.e. the workaround still bites)."""
    views = dlg.findChildren(QListView) + dlg.findChildren(QTreeView)
    for v in views:
        v.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    return len(views)


class _DropList(QListWidget):
    """A list that accepts folders dragged in from Finder / Explorer."""
    dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            self.dropped.emit([Path(u.toLocalFile()) for u in e.mimeData().urls()
                               if u.isLocalFile()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class _Bridge(QObject):
    """Worker thread -> main thread."""
    finished = Signal(object, object)       # (list[RunInfo], ScanResult)


class RunsPane(QWidget):
    selection_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.log: Callable[[str], None] = lambda s: None     # BatchTab wires the console in
        self.settings = spec.RunSettings()                   # score_thresh / stride / model_dir
        self._runs: dict[Path, rd.RunInfo] = {}
        self._included: dict[Path, bool] = {}
        self._busy = False
        self._bridge = _Bridge()
        self._bridge.finished.connect(self._on_loaded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        runs_card = theme.card()
        rc = runs_card.layout()
        header = QHBoxLayout()
        header.addWidget(theme.section_label("SELECTED RUNS"))
        header.addStretch(1)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setToolTip("Remove the highlighted runs from the list (Delete key)")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedWidth(32)
        self.add_btn.setToolTip("Add run folders (or a whole day / month / year of them)")
        self.add_btn.clicked.connect(self._choose_runs)
        for b in (self.remove_btn, self.clear_btn, self.add_btn):
            header.addWidget(b)
        rc.addLayout(header)
        rc.addWidget(theme.separator())

        self.hint = QLabel("No runs yet.\nClick +, or drag run folders here. Pick a day, month or "
                           "year folder to add everything inside it.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 12px; padding: 4px;")
        rc.addWidget(self.hint)

        self.list = _DropList()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setStyleSheet(
            f"QListWidget {{ background-color: {theme.CLR_INPUT}; "
            f"border: 1px solid {theme.CLR_BORDER}; border-radius: 8px; }}")
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.dropped.connect(self.add_paths)
        self.list.keyPressEvent = self._list_key  # Delete removes the highlighted runs
        rc.addWidget(self.list, 1)

        self.summary_label = QLabel("0 runs selected")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 11px;")
        rc.addWidget(self.summary_label)
        self.warn_label = QLabel("")
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet(f"color: {theme.CLR_ORANGE}; font-size: 11px;")
        self.warn_label.hide()
        rc.addWidget(self.warn_label)
        layout.addWidget(runs_card, 1)

        out_card = theme.card()
        oc = out_card.layout()
        oc.addWidget(theme.section_label("OUTPUT FOLDER"))
        oc.addWidget(theme.separator())
        out_row = QHBoxLayout()
        self.output_label = QLabel("(none chosen)")
        self.output_label.setStyleSheet(f"color: {theme.CLR_TEXT_SEC};")
        self.output_label.setWordWrap(True)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._choose_output_folder)
        out_row.addWidget(self.output_label, 1)
        out_row.addWidget(self.browse_btn)
        oc.addLayout(out_row)
        layout.addWidget(out_card)

        actions = QHBoxLayout()
        self.run_btn = theme.accent_button("Run batch")
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip("Worker + pipeline wiring arrives in Phases 5-6")
        self.analyse_btn = theme.ghost_button("Analyse")
        self.analyse_btn.setEnabled(False)
        self.analyse_btn.setToolTip("Statistics wiring arrives in Phases 7-8")
        actions.addWidget(self.run_btn)
        actions.addWidget(self.analyse_btn)
        layout.addLayout(actions)

        self._refresh()

    # ---- public API for later phases -----------------------------------
    def all_runs(self) -> list[rd.RunInfo]:
        return list(self._runs.values())

    def included_runs(self) -> list[rd.RunInfo]:
        """The ticked, usable runs, in chronological order."""
        return [r for r in self._sorted() if self._included.get(r.path) and r.usable]

    def output_folder(self) -> Path | None:
        text = self.output_label.text()
        return Path(text) if text and text != "(none chosen)" else None

    # ---- adding / removing ----------------------------------------------
    def _choose_runs(self) -> None:
        if self._busy:
            return
        chosen = pick_directories(self, PICK_TITLE, default_start_dir())
        if chosen:
            try:
                QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(
                    "last_run_dir", str(chosen[0].parent))
            except Exception:
                pass
            self.add_paths(chosen)

    def add_paths(self, folders: list[Path]) -> None:
        """Find every run at or under `folders` and load them in the background."""
        if self._busy or not folders:
            return
        self._busy = True
        self.add_btn.setEnabled(False)
        self.log(f"scanning {len(folders)} folder(s) for runs ...")
        known = set(self._runs)
        s = spec.effective(self.settings)

        def work() -> None:
            scan = rd.find_runs(folders)
            new = [p for p in scan.runs if p not in known]
            self.log(f"found {len(scan.runs)} run(s)"
                     + (f", {len(scan.runs) - len(new)} already in the list" if len(new) != len(scan.runs) else "")
                     + (f", skipped {len(scan.skipped)}" if scan.skipped else ""))

            def progress(i: int, n: int, info: rd.RunInfo) -> None:
                if n >= 10 and (i % 10 == 0 or i == n):
                    self.log(f"  reading run {i}/{n}")

            try:
                runs = rd.load_runs(new, progress=progress, thr=s.score_thresh,
                                    stride=s.stride, model_dir=s.model_dir)
            except Exception as exc:                 # must reach the console, not vanish
                self.log(f"ERROR while reading runs: {type(exc).__name__}: {exc}")
                runs = []
            self._bridge.finished.emit(runs, scan)

        threading.Thread(target=work, name="run-discovery", daemon=True).start()

    def _on_loaded(self, runs: list[rd.RunInfo], scan: rd.ScanResult) -> None:
        self._busy = False
        self.add_btn.setEnabled(True)
        for path, why in scan.skipped:
            self.log(f"  skipped {path.name}: {why}")
        for r in runs:
            self._runs[r.path] = r
            self._included.setdefault(r.path, r.usable)
            for issue in r.issues:
                mark = "ERROR" if issue.level == "error" else "warn"
                self.log(f"  {mark}  {r.name}: {issue.message}")
        if not scan.runs and not self._runs:
            self.log("no run folders found. Looked up to 3 levels down for folders named "
                     f"{rd.NAME_FORMAT}. Pick a run, day, month or year folder "
                     "(not the Experiments folder itself).")
        self._refresh()
        self.log(rd.summarise(self._runs.values()).headline())

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            p = Path(item.data(ROLE_PATH))
            self._runs.pop(p, None)
            self._included.pop(p, None)
        self._refresh()

    def clear(self) -> None:
        self._runs.clear()
        self._included.clear()
        self._refresh()

    def _list_key(self, e) -> None:
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected()
        else:
            QListWidget.keyPressEvent(self.list, e)

    # ---- display ------------------------------------------------------------
    def _sorted(self) -> list[rd.RunInfo]:
        return sorted(self._runs.values(),
                      key=lambda r: (f"{r.date or '0000-00-00'} {r.time or r.name}", str(r.path)))

    def _refresh(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for r in self._sorted():
            item = QListWidgetItem(self._text(r))
            item.setData(ROLE_PATH, str(r.path))
            item.setToolTip(self._tooltip(r))
            if r.usable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if self._included.get(r.path)
                                   else Qt.CheckState.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            colour = (theme.CLR_RED if r.errors else theme.CLR_ORANGE if r.warnings
                      else theme.CLR_TEXT)
            item.setForeground(QColor(colour))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.hint.setVisible(not self._runs)
        self.list.setVisible(bool(self._runs))
        self.remove_btn.setEnabled(bool(self._runs))
        self.clear_btn.setEnabled(bool(self._runs))
        self._refresh_summary()

    @staticmethod
    def _text(r: rd.RunInfo) -> str:
        tail = [] if r.analysis.label == "new" else [r.analysis.label]
        if r.errors:
            tail.append("cannot run")
        elif r.warnings:
            tail.append("⚠")
        return r.label + (("    • " + "  • ".join(tail)) if tail else "")

    @staticmethod
    def _tooltip(r: rd.RunInfo) -> str:
        lines = [str(r.path)]
        if r.cine_bytes:
            lines.append(f"cine {r.cine_bytes / 2**30:.1f} GiB" + (f" · {r.fps:g} fps" if r.fps else ""))
        if r.notes:
            lines.append("Notes: " + r.notes.splitlines()[0])
        lines.append(f"status: {r.analysis.label}")
        lines += [("ERROR: " if i.level == "error" else "warning: ") + i.message for i in r.issues]
        return "\n".join(lines)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        self._included[Path(item.data(ROLE_PATH))] = item.checkState() == Qt.CheckState.Checked
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        inc = self.included_runs()
        s = rd.summarise(inc)
        text = s.headline()
        total = len(self._runs)
        if total != s.n_runs:
            text += f"   ({total - s.n_runs} of {total} not ticked or unusable)"
        self.summary_label.setText(text)
        versions = rd.sizer_versions(inc)
        if len(versions) > 1:
            self.warn_label.setText(
                "⚠ These measured runs used different sizer versions "
                f"({', '.join(sorted(versions))}). They are not comparable: re-measure the older "
                "ones before analysing them together.")
            self.warn_label.show()
        else:
            self.warn_label.hide()
        self.selection_changed.emit()

    def _choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if folder:
            self.output_label.setText(folder)
            self.output_label.setStyleSheet(f"color: {theme.CLR_TEXT};")
