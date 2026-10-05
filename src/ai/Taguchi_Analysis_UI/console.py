"""The console pane: a thread-safe log sink feeding a styled read-only
text widget.

Pattern lifted deliberately from src/gui/GUI_Clean.py, which has already
solved this: background work never touches a Qt widget directly — it
pushes strings into a plain `queue.Queue`, and a 100 ms `QTimer` on the
main thread drains that queue into the widget. Two different timers run
at two different rates for two different jobs (see `ConsolePane`):
draining text is cheap and wants a tight interval; the status line below
it is recomputed from local state on every tick regardless of whether a
new line arrived, which is what makes a stall visible instead of silent.
"""
from __future__ import annotations

import queue
import time
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from . import theme

DRAIN_INTERVAL_MS = 100
STATUS_INTERVAL_MS = 1000

# A stall is "still alive but nothing has happened in a while" — the
# distinction that matters is silence vs progress, not a single fixed
# threshold; these are starting points, tuned against real batch runs in
# a later phase.
STALL_WARN_S = 90
STALL_DANGER_S = 120


class LogQueue:
    """The thread-safe hand-off point. Any thread (or, later, a tailed
    worker-process event file) calls `put()`; only the Qt main thread
    calls `drain()`."""

    def __init__(self) -> None:
        self._q: queue.Queue[str] = queue.Queue()

    def put(self, line: str) -> None:
        self._q.put(line)

    def drain(self) -> list[str]:
        lines = []
        while True:
            try:
                lines.append(self._q.get_nowait())
            except queue.Empty:
                break
        return lines


class ConsolePane(QWidget):
    """Bottom pane: a terminal-styled log plus a status line that repaints
    every second from local state, independent of whether a log line
    arrived — so silence reads as silence, not as "nothing to show"."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.log_queue = LogQueue()
        self._last_line_monotonic: float | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        card = theme.card(padding=10)
        card_layout = card.layout()

        header = QHBoxLayout()
        header.addWidget(theme.section_label("CONSOLE"))
        header.addStretch(1)
        clear_btn = theme.ghost_button("Clear")
        clear_btn.setFixedHeight(26)
        clear_btn.clicked.connect(self._clear)
        header.addWidget(clear_btn)
        card_layout.addLayout(header)
        card_layout.addWidget(theme.separator())

        self.status_label = QLabel("idle")
        self.status_label.setStyleSheet(
            f"color: {theme.CLR_TEXT_SEC}; font-size: 12px; padding: 2px 2px;"
        )
        card_layout.addWidget(self.status_label)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(">")
        self.text.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background-color: #1a1a1c;
                color: {theme.CLR_GREEN};
                border: 1px solid {theme.CLR_BORDER};
                border-radius: 8px;
                padding: 6px;
                font-family: "Menlo", "Monaco", "Courier New", monospace;
                font-size: 10pt;
            }}
            QScrollBar:vertical {{ width: 6px; background: transparent; }}
            """
        )
        card_layout.addWidget(self.text, 1)
        outer.addWidget(card)

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(DRAIN_INTERVAL_MS)
        self._drain_timer.timeout.connect(self._flush)
        self._drain_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(STATUS_INTERVAL_MS)
        self._status_timer.timeout.connect(self._repaint_status)
        self._status_timer.start()

        # The function the status line calls each tick to describe current
        # state. Later phases (the batch worker) replace this; phase 1's
        # default just reports console silence.
        self.status_provider = None  # type: ignore[assignment]

    # -- public API -----------------------------------------------------
    def log(self, text: str) -> None:
        """Thread-safe: call from any thread."""
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{stamp}] {text}")

    def set_status_provider(self, fn) -> None:
        """`fn() -> str` is called every STATUS_INTERVAL_MS and its return
        value becomes the status line. Keeping this pluggable means the
        batch worker (later phases) can report live progress without the
        console pane knowing anything about jobs."""
        self.status_provider = fn

    # -- internals --------------------------------------------------------
    def _flush(self) -> None:
        lines = self.log_queue.drain()
        if not lines:
            return
        self._last_line_monotonic = time.monotonic()
        for line in lines:
            self.text.appendPlainText(line)

    def _repaint_status(self) -> None:
        if self.status_provider is not None:
            try:
                self.status_label.setText(self.status_provider())
                self.status_label.setStyleSheet(
                    f"color: {theme.CLR_TEXT_SEC}; font-size: 12px; padding: 2px 2px;"
                )
                return
            except Exception as exc:  # status providers must never crash the UI
                self.status_label.setText(f"status error: {exc}")
                self.status_label.setStyleSheet(
                    f"color: {theme.CLR_RED}; font-size: 12px; padding: 2px 2px;"
                )
                return

        if self._last_line_monotonic is None:
            self.status_label.setText("idle")
            self.status_label.setStyleSheet(
                f"color: {theme.CLR_TEXT_SEC}; font-size: 12px; padding: 2px 2px;"
            )
            return

        silence = time.monotonic() - self._last_line_monotonic
        if silence < STALL_WARN_S:
            self.status_label.setText(f"last line {silence:.0f}s ago")
            colour = theme.CLR_TEXT_SEC
        elif silence < STALL_DANGER_S:
            self.status_label.setText(f"NO OUTPUT FOR {silence:.0f}s")
            colour = theme.CLR_ORANGE
        else:
            self.status_label.setText(f"NO OUTPUT FOR {silence:.0f}s — may be stalled")
            colour = theme.CLR_RED
        self.status_label.setStyleSheet(f"color: {colour}; font-size: 12px; padding: 2px 2px;")

    def _clear(self) -> None:
        self.text.clear()
