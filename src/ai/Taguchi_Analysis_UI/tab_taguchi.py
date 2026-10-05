"""The Taguchi tab: the detected design, fully editable.

A thin view over design.py. It shows a banner (is the design what it should be?), a
table with one row per run (include tick, run, condition, replicate, one editable
column per factor, and the cross-check result for that run), and a findings list.

Editing:
    tick / untick a row       leave a run in or out of the analysis
    type in a factor cell     override that run's level (typing the detected value back
                              removes the override); this is also how an UNASSIGNED run
                              is given the values it lacks
    double-click a header     rename the factor
    right-click a header      rename / remove / (for ranges) use max, min or mean
    Add factor...             any built-in factor, or ANY run_summary.xlsx field
    Leave out runs with no trial   drops the side tests the Notes can identify

With an output folder chosen, every change is saved to <output>/taguchi_design.json and
reloaded next time, so edits survive reopening the app.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import design as dz
from . import theme

COL_USE, COL_RUN, COL_COND, COL_REP = 0, 1, 2, 3
FIXED_COLS = 4                                    # then one column per factor, then the check
ROLE_PATH = Qt.ItemDataRole.UserRole
LEVEL_COLOURS = {"ok": "#8be9a8", "info": theme.CLR_TEXT_SEC, "warn": theme.CLR_ORANGE,
                 "error": theme.CLR_RED}
STATUS_COLOURS = {dz.AGREE: theme.CLR_TEXT, dz.TUPLE_ONLY: theme.CLR_TEXT_SEC,
                  dz.CONFLICT: theme.CLR_RED, dz.UNASSIGNED: theme.CLR_ORANGE,
                  dz.DROPPED: "#636366"}
MARK = {"ok": "✔", "info": "•", "warn": "⚠", "error": "✖"}


class TaguchiTab(QWidget):
    def __init__(self, runs_pane, parent=None) -> None:
        super().__init__(parent)
        self.runs_pane = runs_pane
        self.design = dz.detect([])
        self.output_dir: Path | None = None
        self.saved_to: Path | None = None
        self._building = False
        self._rebuild_pending = False
        self.ask_text = self._ask_text                # tests replace these
        self.ask_yes = lambda text: QMessageBox.question(self, "Taguchi", text) == QMessageBox.StandardButton.Yes
        self.log = lambda text, level="info": None    # BatchTab wires the console in

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(self._banner_css(theme.CLR_TEXT_SEC))
        outer.addWidget(self.banner)

        bar = QHBoxLayout()
        self.add_btn = theme.ghost_button("Add factor…")
        self.add_btn.setToolTip("Add a factor from the run folder names or ANY field of run_summary.xlsx")
        self.add_btn.clicked.connect(self._add_menu)
        self.stray_btn = theme.ghost_button("Leave out runs with no trial")
        self.stray_btn.setToolTip("Untick runs whose Notes name no trial while the others do "
                                  "(side tests outside the design)")
        self.stray_btn.clicked.connect(self.leave_out_stray)
        self.reset_btn = theme.ghost_button("Reset to detected")
        self.reset_btn.setToolTip("Discard every edit and detect the design again")
        self.reset_btn.clicked.connect(self.reset)
        self.save_label = QLabel("")
        self.save_label.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 11px;")
        for w in (self.add_btn, self.stray_btn, self.reset_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.save_label)
        outer.addLayout(bar)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {theme.CLR_INPUT}; gridline-color: {theme.CLR_BORDER}; "
            f"border: 1px solid {theme.CLR_BORDER}; border-radius: 8px; }} "
            f"QHeaderView::section {{ background-color: {theme.CLR_PANEL}; color: {theme.CLR_TEXT_SEC}; "
            f"border: none; border-bottom: 1px solid {theme.CLR_BORDER}; padding: 6px; font-weight: 600; }}")
        hh = self.table.horizontalHeader()
        hh.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._header_menu)
        hh.sectionDoubleClicked.connect(self._header_double_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        split.addWidget(self.table)

        self.findings = QListWidget()
        self.findings.setWordWrap(True)
        self.findings.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.findings.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.findings.setStyleSheet(
            f"QListWidget {{ background-color: {theme.CLR_PANEL}; border: 1px solid {theme.CLR_BORDER}; "
            f"border-radius: 8px; padding: 4px; }} QListWidget::item {{ padding: 3px 4px; }}")
        split.addWidget(self.findings)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, 1)

        runs_pane.selection_changed.connect(self.sync_runs)
        runs_pane.output_changed.connect(self.sync_output)
        self.sync_runs()

    # ---- styling ---------------------------------------------------------------------
    @staticmethod
    def _banner_css(colour: str) -> str:
        return (f"color: {colour}; font-size: 13px; font-weight: 600; padding: 8px 10px; "
                f"background-color: {theme.CLR_PANEL}; border: 1px solid {theme.CLR_BORDER}; "
                f"border-radius: 8px;")

    # ---- keeping in step with the Batch tab ----------------------------------------------
    def sync_runs(self) -> None:
        runs = self.runs_pane.included_runs()
        self.design.update_runs(runs)
        self.rebuild()

    def sync_output(self) -> None:
        self.output_dir = self.runs_pane.output_folder()
        self.saved_to = None
        if self.output_dir is not None:
            saved = dz.load_saved(self.output_dir)
            if saved is not None:
                for note in self.design.apply_saved(saved):
                    self.log(f"design: {note}", "warn")
                self.log(f"design: restored your edits from {dz.design_path(self.output_dir)}", "info")
        self.rebuild()

    # ---- building the view -------------------------------------------------------------------
    def rebuild(self) -> None:
        d = self.design
        a = dz.assign(d)
        text, level = dz.headline(d, a)
        self.banner.setText(f"{MARK.get(level, '')}  {text}")
        self.banner.setStyleSheet(self._banner_css(LEVEL_COLOURS[level]))

        factors = d.factors
        self._building = True
        self.table.blockSignals(True)
        try:
            self.table.clear()
            ncol = FIXED_COLS + len(factors) + 1
            self.table.setColumnCount(ncol)
            self.table.setRowCount(len(d.rows))
            heads = ["Use", "Run", "Condition", "Rep"] + [f.label for f in factors] + ["Cross-check"]
            self.table.setHorizontalHeaderLabels(heads)
            for i, f in enumerate(factors):
                tip = f"{f.label}\ndouble-click to rename; right-click for more"
                if f.source == "workbook":
                    tip += f"\nfrom run_summary.xlsx: {f.field}" + (f" (range: {f.pick})" if f.pick else "")
                self.table.horizontalHeaderItem(FIXED_COLS + i).setToolTip(tip)

            def order(r: dz.Row):
                res = a.of(r)
                if res.status == dz.UNASSIGNED:
                    return (0, 0, 0, r.date or "", r.time or "")
                if res.status == dz.DROPPED or res.condition is None:
                    return (2, 0, 0, r.date or "", r.time or "")
                return (1, res.condition.index, res.replicate or 0, r.date or "", r.time or "")

            self._rows = sorted(d.rows, key=order)
            for row_i, r in enumerate(self._rows):
                self._fill_row(row_i, r, a.of(r), factors)
            hh = self.table.horizontalHeader()
            hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(ncol - 1, QHeaderView.ResizeMode.Stretch)
        finally:
            self.table.blockSignals(False)
            self._building = False

        self.findings.clear()
        for f in dz.diagnose(d):
            item = QListWidgetItem(f"{MARK[f.level]}  {f.text}")
            item.setForeground(QBrush(QColor(LEVEL_COLOURS[f.level])))
            self.findings.addItem(item)
        stray = dz.outside_design(d, a)
        self.stray_btn.setEnabled(bool(stray))
        self.stray_btn.setText(f"Leave out {len(stray)} run{'s' if len(stray) != 1 else ''} with no trial"
                               if stray else "Leave out runs with no trial")
        self.add_btn.setEnabled(bool(d.rows))
        self._save()

    def _fill_row(self, row_i: int, r: dz.Row, res: dz.RowResult, factors) -> None:
        colour = QColor(STATUS_COLOURS[res.status])
        dim = res.status == dz.DROPPED

        use = QTableWidgetItem("")
        use.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        use.setCheckState(Qt.CheckState.Checked if r.included else Qt.CheckState.Unchecked)
        use.setData(ROLE_PATH, str(r.path))
        self.table.setItem(row_i, COL_USE, use)

        def cell(col: int, text: str, tip: str = "", editable: bool = False) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            flags = Qt.ItemFlag.ItemIsEnabled | (Qt.ItemFlag.ItemIsEditable if editable else Qt.ItemFlag(0))
            item.setFlags(flags)
            item.setForeground(QBrush(colour))
            item.setToolTip(tip)
            item.setData(ROLE_PATH, str(r.path))
            self.table.setItem(row_i, col, item)
            return item

        when = f"{r.date}  " if r.date else ""
        cell(COL_RUN, f"{when}{r.time or r.name}", f"{r.name}\n{r.path}"
             + (f"\nNotes: {r.notes.strip().splitlines()[0]}" if r.notes.strip() else ""))
        cell(COL_COND, "" if dim or res.condition is None else res.condition.label)
        cell(COL_REP, "" if res.replicate is None or dim else str(res.replicate))
        for i, f in enumerate(factors):
            v = r.value(f.key)
            overridden = f.key in r.overrides
            item = cell(FIXED_COLS + i, "" if v is None else str(v),
                        ("EDITED by you (detected: "
                         f"{r.detected.get(f.key)})" if overridden else
                         "detected; type to override" if v is not None else
                         "no value found: type one to include this run"), editable=True)
            item.setData(Qt.ItemDataRole.UserRole + 1, f.key)
            if overridden:
                item.setForeground(QBrush(QColor(theme.CLR_ACCENT)))
                font = item.font()
                font.setItalic(True)
                item.setFont(font)
            if v is None:
                item.setBackground(QBrush(QColor(255, 159, 10, 40)))
        cell(self.table.columnCount() - 1, dz.STATUS_TEXT[res.status] + (f": {res.detail}" if res.detail else ""),
             res.detail)

    # ---- edits -----------------------------------------------------------------------------------
    def _row_of(self, item: QTableWidgetItem) -> dz.Row | None:
        path = item.data(ROLE_PATH)
        return next((r for r in self.design.rows if str(r.path) == path), None)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._building:
            return
        row = self._row_of(item)
        if row is None:
            return
        if item.column() == COL_USE:
            row.included = item.checkState() == Qt.CheckState.Checked
        elif item.column() >= FIXED_COLS and item.data(Qt.ItemDataRole.UserRole + 1):
            key = item.data(Qt.ItemDataRole.UserRole + 1)
            text = item.text().strip()
            if text == "":
                row.overrides.pop(key, None)
            else:
                f = self.design.factor(key)
                try:
                    value = float(text) if f.numeric else text
                except ValueError:
                    value = text
                    f.numeric = False        # a word where a number was: it is categorical now
                self.design.set_value(row, key, value)
        else:
            return
        self._defer_rebuild()

    def _defer_rebuild(self) -> None:
        """Never rebuild inside the table's own itemChanged: clearing the table while it is
        still handling the edit is the same use-after-free that crashed the output tree."""
        if not self._rebuild_pending:
            self._rebuild_pending = True
            QTimer.singleShot(0, self._finish_edit)

    def _finish_edit(self) -> None:
        self._rebuild_pending = False
        self.rebuild()

    def rename_factor(self, key: str, label: str) -> bool:
        try:
            self.design.rename_factor(key, label)
        except ValueError as exc:
            self.log(f"design: {exc}", "warn")
            return False
        self.rebuild()
        return True

    def remove_factor(self, key: str) -> None:
        self.design.remove_factor(key)
        self.rebuild()

    def add_factor(self, field_id: str) -> bool:
        try:
            self.design.add_factor(field_id)
        except ValueError as exc:
            self.log(f"design: {exc}", "warn")
            return False
        self.rebuild()
        return True

    def set_pick(self, key: str, pick: str) -> None:
        self.design.set_pick(key, pick)
        self.rebuild()

    def leave_out_stray(self) -> None:
        stray = dz.outside_design(self.design)
        for r in stray:
            r.included = False
        if stray:
            self.log(f"design: left out {len(stray)} run(s) with no trial in their Notes: "
                     + ", ".join(r.time or r.name for r in stray), "info")
        self.rebuild()

    def reset(self) -> None:
        if self.design.customised or any(r.overrides or not r.included for r in self.design.rows):
            if not self.ask_yes("Discard every edit to the design and detect it again?"):
                return
        self.design = dz.detect(self.runs_pane.included_runs())
        self.rebuild()
        self.log("design: reset to the detected design", "info")

    # ---- menus -----------------------------------------------------------------------------------------
    @staticmethod
    def _ask_text(title: str, label: str, text: str = "") -> str | None:
        value, ok = QInputDialog.getText(None, title, label, text=text)
        return value if ok else None

    def _factor_at(self, section: int):
        i = section - FIXED_COLS
        return self.design.factors[i] if 0 <= i < len(self.design.factors) else None

    def _header_double_clicked(self, section: int) -> None:
        f = self._factor_at(section)
        if f is None:
            return
        label = self.ask_text("Rename factor", "Name:", f.label)
        if label:
            self.rename_factor(f.key, label)

    def _header_menu(self, pos) -> None:
        f = self._factor_at(self.table.horizontalHeader().logicalIndexAt(pos))
        if f is None:
            return
        menu = QMenu(self)
        menu.addAction("Rename…", lambda: self._header_double_clicked(
            FIXED_COLS + self.design.factors.index(f)))
        if f.source == "workbook":
            for how in ("max", "min", "mean"):
                act = menu.addAction(f"If the field is a range, use the {how}",
                                     lambda h=how: self.set_pick(f.key, h))
                act.setCheckable(True)
                act.setChecked(f.pick == how)
        menu.addAction("Remove this factor", lambda: self.remove_factor(f.key))
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _add_menu(self) -> None:
        menu = QMenu(self)
        cands = self.design.candidates()
        if not cands:
            menu.addAction("(every available field is already a factor)").setEnabled(False)
        for field_id, text in cands:
            menu.addAction(text, lambda fid=field_id: self.add_factor(fid))
        menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))

    # ---- saving ----------------------------------------------------------------------------------------------
    def _save(self) -> None:
        if self.output_dir is None:
            self.save_label.setText("choose an output folder to keep your edits")
            return
        if not self.design.rows:
            return
        try:
            self.saved_to = dz.save(self.design, self.output_dir)
            self.save_label.setText(f"saved: {self.saved_to.name}")
        except OSError as exc:
            self.save_label.setText(f"could not save the design: {exc}")
            self.log(f"design: could not save to {self.output_dir}: {exc}", "error")
