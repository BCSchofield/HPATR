"""The Settings tab: every field opens with the value the pipeline itself would choose.

A thin view over settings_defaults.py (which asks the pipeline) and RunsPane.settings (which
the batch, the plan and the analysis all read). Per row: the editor, a note saying WHERE the
value comes from (and what it means for the runs selected now), an orange warning where the
choice has a cost, a red message if what was typed is not valid, and a reset button.

  * A value typed equal to the default is stored as "let the pipeline decide" (None), so the
    row stays marked "default" and nothing is pinned.
  * An invalid entry is NOT applied: the last valid value stays in force and the row says why.
  * Settings are NOT remembered between launches: each start proposes the pipeline's own
    defaults again, so a stale override can never quietly outlive the reason it was set.
  * Device and model folder are resolved on a background thread (the model lookup touches the
    LaCie drive, which may be asleep or absent); the rows say "resolving" until then.
"""
from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from . import pipeline_spec as spec
from . import settings_defaults as sd
from . import size_bins, theme

DEVICES = (("auto", None), ("cpu", "cpu"), ("cuda", "cuda"), ("mps", "mps"))


class _Bridge(QObject):
    resolved = Signal(object, object)         # (device Default, ModelInfo)


class SettingRow(QWidget):
    """label | editor | edited-tag | reset  /  note  /  warning  /  error"""
    committed = Signal()
    reset_requested = Signal()

    def __init__(self, title: str, editor: QWidget, *, browse: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.title = QLabel(title)
        self.title.setFixedWidth(150)
        self.title.setStyleSheet(f"color: {theme.CLR_TEXT}; font-size: 13px; font-weight: 600;")
        top.addWidget(self.title)
        top.addWidget(editor, 1 if browse else 0)
        self.browse_btn = None
        if browse:
            self.browse_btn = theme.ghost_button("Browse…")
            top.addWidget(self.browse_btn)
        self.tag = QLabel("")
        self.tag.setFixedWidth(52)
        self.reset_btn = theme.ghost_button("Reset")
        self.reset_btn.clicked.connect(self.reset_requested)
        top.addWidget(self.tag)
        top.addWidget(self.reset_btn)
        if not browse:
            top.addStretch(1)
        v.addLayout(top)
        self.note = self._line(theme.CLR_TEXT_SEC)
        self.warn = self._line(theme.CLR_ORANGE)
        self.error = self._line(theme.CLR_RED)
        for w in (self.note, self.warn, self.error):
            v.addWidget(w)
        self.set_edited(False)
        if isinstance(editor, QLineEdit):
            editor.editingFinished.connect(self.committed)
        elif isinstance(editor, QComboBox):
            editor.activated.connect(lambda _i: self.committed.emit())

    @staticmethod
    def _line(colour: str) -> QLabel:
        lbl = QLabel("")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {colour}; font-size: 11px; padding-left: 160px;")
        lbl.hide()
        return lbl

    def _set(self, lbl: QLabel, text: str) -> None:
        lbl.setText(text)
        lbl.setVisible(bool(text))

    def set_note(self, text: str) -> None:
        self._set(self.note, text)

    def set_warn(self, text: str) -> None:
        self._set(self.warn, "⚠ " + text if text else "")

    def set_error(self, text: str) -> None:
        self._set(self.error, "✖ " + text if text else "")

    def set_edited(self, edited: bool) -> None:
        self.tag.setText("edited" if edited else "default")
        self.tag.setStyleSheet(f"color: {theme.CLR_ACCENT if edited else theme.CLR_TEXT_SEC}; font-size: 11px;")
        self.reset_btn.setEnabled(edited)


class SettingsTab(QWidget):
    bins_changed = Signal()

    def __init__(self, runs_pane, parent=None, resolver: Callable | None = None) -> None:
        super().__init__(parent)
        self.runs_pane = runs_pane
        self.log: Callable = lambda text, level="info": None
        self.bin_width = size_bins.DEFAULT_WIDTH_UM
        self.bin_max = size_bins.DEFAULT_MAX_UM
        self.device_default: sd.Default | None = None
        self.model_default: sd.ModelInfo | None = None
        self._resolver = resolver or (lambda: (sd.device(), sd.model()))
        self._bridge = _Bridge()
        self._bridge.resolved.connect(self._on_resolved)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        intro = QLabel("Each field starts with the value the pipeline would choose itself, and says where "
                       "it came from. Change one only when you mean to. Settings return to the defaults "
                       "each time the app starts.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 12px;")
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("settingsBody")
        ground = f"background-color: {theme.CLR_BG};"
        body.setStyleSheet(f"QWidget#settingsBody {{ {ground} }}")
        scroll.viewport().setObjectName("settingsViewport")   # scoped by name: a bare rule would cascade to labels
        scroll.viewport().setStyleSheet(f"QWidget#settingsViewport {{ {ground} }}")
        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(14)

        batch = theme.card()
        batch.layout().addWidget(theme.section_label("BATCH (used when you press Run batch)"))
        self.thr = SettingRow("Score threshold", self._edit(110))
        self.stride = SettingRow("Frame stride", self._edit(110))
        self.ci = SettingRow("CI stride", self._edit(110))
        self.device = SettingRow("Inference device", self._combo())
        self.model = SettingRow("Model folder", self._edit(0), browse=True)
        for r in (self.thr, self.stride, self.ci, self.device, self.model):
            batch.layout().addWidget(r)
        self.images_note = QLabel("")
        self.images_note.setWordWrap(True)
        self.images_note.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 11px;")
        batch.layout().addWidget(self.images_note)
        form.addWidget(batch)

        analysis = theme.card()
        analysis.layout().addWidget(theme.section_label("ANALYSIS (used when you press Analyse)"))
        self.width = SettingRow("Size-bin width (µm)", self._edit(110))
        self.maxd = SettingRow("Size-bin maximum (µm)", self._edit(110))
        analysis.layout().addWidget(self.width)
        analysis.layout().addWidget(self.maxd)
        form.addWidget(analysis)
        form.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        bar = QHBoxLayout()
        self.reset_all_btn = theme.ghost_button("Reset all to defaults")
        self.reset_all_btn.clicked.connect(self.reset_all)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.CLR_TEXT_SEC}; font-size: 11px;")
        bar.addWidget(self.reset_all_btn)
        bar.addWidget(self.status, 1)
        outer.addLayout(bar)

        self.thr.committed.connect(self._commit_thr)
        self.stride.committed.connect(self._commit_stride)
        self.ci.committed.connect(self._commit_ci)
        self.device.committed.connect(self._commit_device)
        self.model.committed.connect(self._commit_model)
        self.model.browse_btn.clicked.connect(self._browse_model)
        self.width.committed.connect(self._commit_bins)
        self.maxd.committed.connect(self._commit_bins)
        self.thr.reset_requested.connect(lambda: self._reset("thr"))
        self.stride.reset_requested.connect(lambda: self._reset("stride"))
        self.ci.reset_requested.connect(lambda: self._reset("ci"))
        self.device.reset_requested.connect(lambda: self._reset("device"))
        self.model.reset_requested.connect(lambda: self._reset("model"))
        self.width.reset_requested.connect(lambda: self._reset("bins"))
        self.maxd.reset_requested.connect(lambda: self._reset("bins"))

        runs_pane.selection_changed.connect(self.refresh)
        runs_pane.settings_changed.connect(self.refresh)
        self.fill_editors()
        self.refresh()
        self.start_resolving()

    # ---- widgets ---------------------------------------------------------------------------
    @staticmethod
    def _edit(width: int) -> QLineEdit:
        e = QLineEdit()
        if width:
            e.setFixedWidth(width)
        return e

    @staticmethod
    def _combo() -> QComboBox:
        c = QComboBox()
        c.setFixedWidth(220)
        for label, _ in DEVICES:
            c.addItem(label)
        return c

    # ---- the pipeline's answers ----------------------------------------------------------------
    def start_resolving(self) -> None:
        self.device.set_note("asking the pipeline …")
        self.model.set_note("looking for the model …")

        def work() -> None:
            try:
                d, m = self._resolver()
            except BaseException as exc:             # noqa: BLE001 -- shown, never fatal
                d = sd.Default("cpu", f"could not ask the pipeline: {type(exc).__name__}: {exc}", ok=False)
                m = sd.ModelInfo(None, note=f"{type(exc).__name__}: {exc}", ok=False)
            self._bridge.resolved.emit(d, m)

        threading.Thread(target=work, name="settings-resolve", daemon=True).start()

    def _on_resolved(self, device: sd.Default, model: sd.ModelInfo) -> None:
        self.device_default, self.model_default = device, model
        self.device.editor.setItemText(0, f"auto → {device.value}" if device.ok else "auto")
        if model.folder is not None:
            self.model.editor.setPlaceholderText(str(model.folder))
        else:
            self.model.editor.setPlaceholderText("no model found: choose a folder")
        self.refresh()

    # ---- showing ---------------------------------------------------------------------------
    def fill_editors(self) -> None:
        """Put the current effective values in the editors (used at start and after a reset)."""
        s = spec.effective(self.runs_pane.settings)
        self.thr.editor.setText(f"{s.score_thresh:g}")
        self.stride.editor.setText(str(s.stride))
        self.ci.editor.setText("auto" if s.ci_stride is None else str(s.ci_stride))
        idx = next((i for i, (_, v) in enumerate(DEVICES) if v == s.device), 0)
        self.device.editor.setCurrentIndex(idx)
        self.model.editor.setText(str(s.model_dir) if s.model_dir else "")
        self.width.editor.setText(f"{self.bin_width:g}")
        self.maxd.editor.setText(f"{self.bin_max:g}")

    def refresh(self) -> None:
        """Notes, warnings and the edited tags, from the settings in force and the runs selected."""
        raw = self.runs_pane.settings
        eff = spec.effective(raw)
        fps = self.runs_pane.fps_values()
        self.thr.set_note(sd.score_threshold().note)
        self.thr.set_edited(raw.score_thresh is not None and raw.score_thresh != sd.score_threshold().value)
        st = sd.stride(fps, eff.stride)
        self.stride.set_note(st.note)
        self.stride.set_warn(st.warn)
        self.stride.set_edited(raw.stride is not None and raw.stride != st.value)
        ci = sd.ci_stride(fps, eff.stride)
        if raw.ci_stride is None:
            self.ci.set_note(ci.note)
        else:
            self.ci.set_note(f"you chose {raw.ci_stride}, used for every run instead of the pipeline's "
                             f"per-run choice")
        self.ci.set_edited(raw.ci_stride is not None)

        auto = self.device_default.value if self.device_default else None
        if self.device_default is None:
            pass                                                   # still resolving
        else:
            self.device.set_note(self.device_default.note)
            self.device.set_warn(sd.device_warning(raw.device, auto))
        self.device.set_edited(raw.device is not None)

        m = self.model_default
        if raw.model_dir:
            info = sd.inspect_model(Path(raw.model_dir))
            self.model.set_note(sd.describe_model(info))
            self.model.set_warn(info.warn)
        elif m is not None:
            self.model.set_note("the pipeline's choice (tiled_inference.default_model_dir): "
                                + sd.describe_model(m))
            self.model.set_warn(m.warn if m.ok else "")
        self.model.set_edited(raw.model_dir is not None)

        self.width.set_note(sd.bin_width().note)
        self.maxd.set_note(sd.bin_max().note)
        self.width.set_edited(self.bin_width != sd.bin_width().value)
        self.maxd.set_edited(self.bin_max != sd.bin_max().value)
        self.images_note.setText("Per-frame images: extreme frames are always written; “every frame” is "
                                 "a tick on the Batch tab's output tree, not a setting.")
        n = self.n_edited()
        self.status.setText(f"{n} setting{'s' if n != 1 else ''} changed from the defaults" if n
                            else "all settings are the pipeline's defaults")
        self.reset_all_btn.setEnabled(n > 0)

    def n_edited(self) -> int:
        rows = (self.thr, self.stride, self.ci, self.device, self.model, self.width, self.maxd)
        return sum(1 for r in rows if r.tag.text() == "edited")

    # ---- committing -----------------------------------------------------------------------------
    def _apply(self, **changes) -> None:
        self.runs_pane.set_settings(replace(self.runs_pane.settings, **changes))
        self.refresh()

    def _commit_thr(self) -> None:
        try:
            v = sd.parse_threshold(self.thr.editor.text())
        except sd.Invalid as exc:
            self.thr.set_error(str(exc))
            return
        self.thr.set_error("")
        self._apply(score_thresh=None if v == sd.score_threshold().value else v)
        self.thr.editor.setText(f"{v:g}")

    def _commit_stride(self) -> None:
        try:
            v = sd.parse_positive_int(self.stride.editor.text())
        except sd.Invalid as exc:
            self.stride.set_error(str(exc))
            return
        self.stride.set_error("")
        self._apply(stride=None if v == sd.stride().value else v)
        self.stride.editor.setText(str(v))

    def _commit_ci(self) -> None:
        try:
            v = sd.parse_ci_stride(self.ci.editor.text())
        except sd.Invalid as exc:
            self.ci.set_error(str(exc) + ", or 'auto'")
            return
        self.ci.set_error("")
        self._apply(ci_stride=v)
        self.ci.editor.setText("auto" if v is None else str(v))

    def _commit_device(self) -> None:
        self._apply(device=DEVICES[self.device.editor.currentIndex()][1])

    def _commit_model(self) -> None:
        text = self.model.editor.text().strip()
        if not text:
            self.model.set_error("")
            self._apply(model_dir=None)
            return
        info = sd.inspect_model(Path(text))
        if not info.ok:
            self.model.set_error(info.note)
            return
        self.model.set_error("")
        same = self.model_default is not None and self.model_default.folder == info.folder
        self._apply(model_dir=None if same else info.folder)
        if same:
            self.model.editor.setText("")

    def _browse_model(self) -> None:
        start = (self.runs_pane.settings.model_dir
                 or (self.model_default.folder if self.model_default else None) or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose the model folder", str(start))
        if folder:
            self.model.editor.setText(folder)
            self._commit_model()

    def _commit_bins(self) -> None:
        try:
            w = sd.parse_um(self.width.editor.text(), "bin width")
            m = sd.parse_um(self.maxd.editor.text(), "bin maximum")
            size_bins.make_edges(w, m)
        except sd.Invalid as exc:
            self.width.set_error(str(exc))
            return
        except ValueError:
            self.width.set_error("the maximum must be at least one bin width")
            return
        self.width.set_error("")
        self.bin_width, self.bin_max = w, m
        self.bins_changed.emit()
        self.refresh()

    # ---- resetting ---------------------------------------------------------------------------------
    def _reset(self, which: str) -> None:
        if which == "thr":
            self._apply(score_thresh=None)
            self.thr.set_error("")
        elif which == "stride":
            self._apply(stride=None)
            self.stride.set_error("")
        elif which == "ci":
            self._apply(ci_stride=None)
            self.ci.set_error("")
        elif which == "device":
            self._apply(device=None)
        elif which == "model":
            self._apply(model_dir=None)
            self.model.set_error("")
        elif which == "bins":
            self.bin_width, self.bin_max = size_bins.DEFAULT_WIDTH_UM, size_bins.DEFAULT_MAX_UM
            self.width.set_error("")
            self.bins_changed.emit()
        self.fill_editors()
        self.refresh()

    def reset_all(self) -> None:
        self.bin_width, self.bin_max = size_bins.DEFAULT_WIDTH_UM, size_bins.DEFAULT_MAX_UM
        for r in (self.thr, self.stride, self.ci, self.model, self.width):
            r.set_error("")
        self.runs_pane.set_settings(replace(self.runs_pane.settings, score_thresh=None, stride=None,
                                            ci_stride=None, device=None, model_dir=None))
        self.bins_changed.emit()
        self.fill_editors()
        self.refresh()
