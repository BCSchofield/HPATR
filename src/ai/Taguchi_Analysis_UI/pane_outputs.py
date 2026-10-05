"""RIGHT pane: the tree of what will be created, with the optional parts tickable.

A thin view over output_tree (the model). All decisions -- which files exist,
which are locked, which ticks are linked -- are made there and in
pipeline_spec; this file only draws them and reports clicks.

Mandatory outputs are real Qt check items that are DISABLED and checked, which
Fusion draws as a grey tick: visibly "on, and not yours to change". Optional
ones are ordinary tickable boxes.
"""
from __future__ import annotations

import platform

from PySide6.QtCore import QEvent, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHeaderView, QLabel, QStyleOptionViewItem, QStyledItemDelegate, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import output_tree as ot
from . import pipeline_spec as spec
from . import theme

ROLE_OUTPUT = Qt.ItemDataRole.UserRole
BOX = 14                                  # checkbox edge, px
LOCKED_FILL, LOCKED_TICK = "#636366", "#d1d1d6"      # the grey tick of a mandatory output
SUPERSEDED_EDGE = "#5a5a5e"


class _CheckDelegate(QStyledItemDelegate):
    """Draws every checkbox itself.

    Fusion's unchecked box is invisible on this dark theme (it matches the field
    background), so the one control the user can actually click was undetectable --
    found by rendering the window, not by a test. Drawing the boxes here makes all
    four states legible and puts the grey locked tick under our control:

        optional, unticked   outlined box          (click to tick)
        optional, ticked     blue box, white tick  (click to untick)
        mandatory            grey box, grey tick   (cannot be changed)
        superseded           dim empty box         (not made under these options)
    """

    def initStyleOption(self, option, index) -> None:
        # QStyledItemDelegate.paint() calls this itself on a fresh copy of the option,
        # so the native indicator has to be removed HERE; stripping it in paint() was
        # silently undone and every row drew two boxes (ours and Qt's).
        super().initStyleOption(option, index)
        if index.column() == 0 and index.data(Qt.ItemDataRole.CheckStateRole) is not None:
            option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator

    def paint(self, painter, option, index) -> None:
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if state is None or index.column() != 0:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        opt.rect = option.rect.adjusted(BOX + 8, 0, 0, 0)       # leave room for our own box
        super().paint(painter, opt, index)

        checked = state == Qt.CheckState.Checked or state == 2
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        r = QRectF(option.rect.left() + 3, option.rect.center().y() - BOX / 2 + 0.5, BOX, BOX)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if checked and enabled:
            fill, edge, tick = QColor(theme.CLR_ACCENT), QColor(theme.CLR_ACCENT), QColor("white")
        elif checked:
            fill, edge, tick = QColor(LOCKED_FILL), QColor(LOCKED_FILL), QColor(LOCKED_TICK)
        elif enabled:
            fill, edge, tick = QColor(0, 0, 0, 0), QColor(theme.CLR_TEXT_SEC), None
        else:
            fill, edge, tick = QColor(0, 0, 0, 0), QColor(SUPERSEDED_EDGE), None
        painter.setPen(QPen(edge, 1.5))
        painter.setBrush(fill)
        painter.drawRoundedRect(r, 3.5, 3.5)
        if tick is not None:
            path = QPainterPath(QPointF(r.left() + BOX * 0.24, r.top() + BOX * 0.54))
            path.lineTo(r.left() + BOX * 0.43, r.top() + BOX * 0.73)
            path.lineTo(r.left() + BOX * 0.78, r.top() + BOX * 0.28)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(tick, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        flags = index.flags()
        if (index.column() == 0 and flags & Qt.ItemFlag.ItemIsUserCheckable
                and flags & Qt.ItemFlag.ItemIsEnabled):
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                now = index.data(Qt.ItemDataRole.CheckStateRole)
                ticked = now == Qt.CheckState.Checked or now == 2
                model.setData(index, 0 if ticked else 2, Qt.ItemDataRole.CheckStateRole)
                return True
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                return True              # a press / double-click never toggles; only a release does (above)
        return super().editorEvent(event, model, option, index)


class OutputsPane(QWidget):
    options_changed = Signal(dict)          # pipeline options, e.g. {"images": "all", ...}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ticks: set[str] = spec.default_ticks()
        self._rebuild_pending = False
        self._options_before: dict = {}
        self._ctx = dict(run_name=None, thr=None, n_runs=0, output_dir=None, n_frames=None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        card = theme.card()
        cl = card.layout()
        cl.addWidget(theme.section_label("OUTPUTS THAT WILL BE CREATED"))
        cl.addWidget(theme.separator())

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background-color: {theme.CLR_INPUT}; "
            f"border: 1px solid {theme.CLR_BORDER}; border-radius: 8px; }} "
            f"QTreeWidget::item {{ padding: 2px 0; }}")
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        # Fixed, not ResizeToContents: the spanned headings are very long, and sizing the
        # column to them would squeeze the file names and clip the detail text.
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 360)
        self.tree.setItemDelegateForColumn(0, _CheckDelegate(self.tree))
        self.tree.itemChanged.connect(self._on_item_changed)
        cl.addWidget(self.tree, 1)

        self.cost_label = QLabel("")
        self.cost_label.setWordWrap(True)
        self.cost_label.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 11px;")
        cl.addWidget(self.cost_label)
        layout.addWidget(card)
        self.rebuild()

    # ---- public API ------------------------------------------------------------
    def options(self) -> dict:
        """The pipeline options the current ticks resolve to."""
        return spec.resolve_options(self._ticks)

    def ticks(self) -> set[str]:
        return set(self._ticks)

    def set_ticks(self, ticks: set[str]) -> None:
        self._ticks = set(ticks)
        self.rebuild()
        self.options_changed.emit(self.options())

    def set_context(self, *, run_name: str | None = None, thr: float | None = None,
                    n_runs: int = 0, output_dir: str | None = None,
                    n_frames: int | None = None) -> None:
        """Tell the tree which run/folder to describe. Does not change any tick."""
        self._ctx = dict(run_name=run_name, thr=thr, n_runs=n_runs, output_dir=output_dir,
                         n_frames=n_frames)
        self.rebuild()

    def states(self) -> dict[str, str]:
        """{output_id: state} of what is displayed (for tests and later phases)."""
        return ot.states(self._roots)

    # ---- drawing ------------------------------------------------------------------
    def rebuild(self) -> None:
        self._roots = ot.build_tree(self._ticks, **self._ctx)
        self.tree.blockSignals(True)
        self.tree.clear()
        for root in self._roots:
            item = self._item(root, top=True)
            self.tree.addTopLevelItem(item)
            item.setFirstColumnSpanned(True)       # long folder names get the full width
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self.cost_label.setText(ot.cost_note(
            self.options(), self._ctx["n_runs"], self._ctx["n_frames"], platform.system()))

    def _item(self, node: ot.Node, top: bool = False) -> QTreeWidgetItem:
        if top:      # headings span both columns, so the explanation is not clipped
            item = QTreeWidgetItem([f"{node.label}   \u00b7   {node.detail}" if node.detail
                                    else node.label, ""])
        else:
            item = QTreeWidgetItem([node.label, node.detail])
        item.setData(0, ROLE_OUTPUT, node.output_id)
        dim = QBrush(QColor(theme.CLR_TEXT_SEC))
        item.setForeground(1, dim)
        if node.state == ot.GROUP:
            if top:
                f = QFont(item.font(0))
                f.setBold(True)
                item.setFont(0, f)
            else:
                item.setForeground(0, QBrush(QColor(theme.CLR_ACCENT)))
        elif node.state == ot.LOCKED_ON:
            # checked + disabled: Fusion draws a grey tick, and the row cannot be clicked
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setForeground(0, dim)
        elif node.state == ot.SUPERSEDED:
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setForeground(0, dim)
        else:                                   # ON / OFF: the only tickable rows
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if node.state == ot.ON
                               else Qt.CheckState.Unchecked)
        item.setToolTip(0, node.label + ("\n" + node.detail if node.detail else ""))
        item.setToolTip(1, node.detail)
        for child in node.children:
            item.addChild(self._item(child))
        return item

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        output_id = item.data(0, ROLE_OUTPUT)
        if column != 0 or not output_id:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        if not self._rebuild_pending:
            self._options_before = self.options()
        self._ticks = ot.toggle(self._ticks, output_id, checked)
        # DEFERRED, never rebuilt here. This runs inside the delegate's editorEvent
        # (model.setData -> itemChanged), and rebuild() clears the tree, destroying the
        # very item the delegate is still using: a use-after-free that segfaulted the
        # app. Waiting one event-loop turn lets the click handler return first.
        if not self._rebuild_pending:
            self._rebuild_pending = True
            QTimer.singleShot(0, self._finish_toggle)

    def _finish_toggle(self) -> None:
        self._rebuild_pending = False
        before = self._options_before
        self.rebuild()               # linked boxes and superseded rows re-derive from the options
        if self.options() != before:
            self.options_changed.emit(self.options())
