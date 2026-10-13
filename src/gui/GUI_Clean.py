# Merge term 1
"""
GUI_Clean.py — Atomisation Control Panel (PySide6 redesign)

Clean, modern Apple-inspired UI built on PySide6.
All backend controller classes are lifted directly from Windows_Experiment_GUI.py
and are unchanged — only the UI layer is new.

Layout:
  ┌─────────────────────────────────────────────────────┐
  │  Header bar: title + live status indicators         │
  ├──────────────────┬──────────────────────────────────┤
  │  Left panel      │  Tab bar: Hardware / Camera /    │2
  │  - Shadowgraph   │          Experiment / AFG        │
  │  - Pressure live │  Tab content                     │
  │  - Motor travel  │                                  │
  ├──────────────────┴──────────────────────────────────┤
  │  Status bar + [▶ START EXPERIMENT]                  │
  └─────────────────────────────────────────────────────┘
"""

import io
import os
import re
import sys
from pathlib import Path
import time
import json
import queue
import platform
import threading
from collections import deque

import serial
import serial.tools.list_ports

import numpy as np
import pandas as pd
from datetime import datetime

import matplotlib
matplotlib.use("Agg")          # non-interactive backend — only used for snapshot renders

import pyqtgraph as pg
pg.setConfigOption('background', '#2c2c2e')
pg.setConfigOption('foreground', '#8e8e93')
pg.setConfigOptions(antialias=True)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QTextEdit, QPlainTextEdit,
    QFrame, QTabWidget, QSizePolicy, QProgressBar, QScrollArea,
    QGridLayout, QMessageBox, QFileDialog, QSpinBox, QInputDialog,
    QDialog, QDialogButtonBox, QRadioButton, QAbstractSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QObject, QThread, QSize, QEvent, QRectF, QPointF
from PySide6.QtGui import QFont, QPixmap, QImage, QColor, QPalette, QIcon, QPainter, QPen, QPolygonF, QIntValidator, QDoubleValidator, QValidator

# ── Path setup ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config_loader import find_lacie_drive
except ImportError:
    def find_lacie_drive(): return None

# What a run actually got: the gas delivered and the upstream pressure, and so its regime
# (flow-controlled / pressure-limited / gas short). The SAME code the analysis app uses
# (src/ai/Taguchi_Analysis_UI/operating.py, numpy only), so the run_summary fields and the
# app's numbers can never be defined differently.
try:
    from ai.Taguchi_Analysis_UI import operating as _operating
except Exception:                                   # the GUI must start without it
    _operating = None
SUPPLY_CEILING_BAR = _operating.CEILING_BAR if _operating else 9.5   # the regulator's setting

# Drops on the window, checked before a run against a clean reference (gui/window_check.py, numpy +
# OpenCV, no Qt). Optional: the GUI starts without it.
try:
    from gui import window_check as _window_check
except Exception:
    _window_check = None
GAS_SHORT_SHARE = 0.95       # flow below this share of the set point ...
GAS_SHORT_HOLD_S = 3.0       # ... for this long is not a transient: say so

# Cone_4.py lives in Trials/ relative to the repo root
_TRIALS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Trials")
if _TRIALS_DIR not in sys.path:
    sys.path.insert(0, _TRIALS_DIR)
CONE4_AVAILABLE = False
try:
    from Cone_4 import detect_cone_angle
    CONE4_AVAILABLE = True
except Exception:
    # Not just ImportError: Cone_4's `int | None` annotations raise TypeError
    # on Python 3.9 (the home PC's Detectron env), and that took this whole
    # module down with it -- including the GLR / mL/min formula the Taguchi
    # app imports, so atomised liquid flow silently vanished (Taguchi app
    # bug 6, 2026-10-13). The cone detector is optional.
    pass

# ── Optional SDKs ────────────────────────────────────────────────────────────
PHANTOM_SDK_AVAILABLE = False
try:
    from pyphantom import Phantom, utils
    PHANTOM_SDK_AVAILABLE = True
except ImportError:
    pass

PYVISA_AVAILABLE = False
try:
    import pyvisa
    PYVISA_AVAILABLE = True
except ImportError:
    pass

CV2_AVAILABLE = False
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    pass

# ── Design tokens ────────────────────────────────────────────────────────────
CLR_BG          = "#111111"   # window background
CLR_PANEL       = "#1c1c1e"   # card / panel surface
CLR_INPUT       = "#2c2c2e"   # input field background
CLR_BORDER      = "#3a3a3c"   # subtle border
CLR_TEXT        = "#f2f2f7"   # primary text
CLR_TEXT_SEC    = "#8e8e93"   # secondary / placeholder text
CLR_ACCENT      = "#0a84ff"   # Apple blue
CLR_GREEN       = "#30d158"   # Apple green  (connected / ok)
CLR_ORANGE      = "#ff9f0a"   # Apple orange (warning / home)
CLR_RED         = "#ff453a"   # Apple red    (danger / off)
CLR_PURPLE      = "#bf5af2"   # Apple purple (clean)

FONT_FAMILY = "SF Pro Display" if platform.system() == "Darwin" else "Segoe UI"
RADIUS = "10px"


BASE_STYLE = f"""
QMainWindow {{
    background-color: {CLR_BG};
    color: {CLR_TEXT};
    font-family: "{FONT_FAMILY}", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}}
QWidget {{
    color: {CLR_TEXT};
    font-family: "{FONT_FAMILY}", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}}
QLabel {{
    background: transparent;
    color: {CLR_TEXT};
}}
QLineEdit, QComboBox, QTextEdit {{
    background-color: {CLR_INPUT};
    color: {CLR_TEXT};
    border: 1px solid #606064;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {CLR_ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
    border: 1px solid {CLR_ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {CLR_TEXT_SEC};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: #2c2c2e;
    color: {CLR_TEXT};
    border: 1px solid #606064;
    border-radius: 8px;
    selection-background-color: {CLR_ACCENT};
    selection-color: white;
    outline: none;
}}
QPushButton {{
    background-color: {CLR_INPUT};
    color: {CLR_TEXT};
    border: 1px solid {CLR_BORDER};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {CLR_BORDER};
}}
QPushButton:pressed {{
    background-color: {CLR_ACCENT};
    color: white;
}}
QPushButton:disabled {{
    color: {CLR_TEXT_SEC};
    background-color: {CLR_INPUT};
    border-color: {CLR_BORDER};
}}
QTabWidget::pane {{
    border: none;
    background-color: {CLR_PANEL};
    border-radius: {RADIUS};
}}
QTabBar::tab {{
    background: transparent;
    color: {CLR_TEXT_SEC};
    padding: 10px 22px;
    font-weight: 500;
    font-size: 13px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {CLR_ACCENT};
    border-bottom: 2px solid {CLR_ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {CLR_TEXT};
}}
QProgressBar {{
    background-color: {CLR_INPUT};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    border-radius: 4px;
    background-color: {CLR_ACCENT};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QCheckBox {{
    spacing: 8px;
    color: {CLR_TEXT};
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {CLR_BORDER};
    background: {CLR_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {CLR_ACCENT};
    border-color: {CLR_ACCENT};
}}
QToolTip {{
    background-color: #2c2c2e;
    color: {CLR_TEXT};
    border: 1px solid {CLR_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""

# ── Helper: styled card frame ─────────────────────────────────────────────────
def card(parent=None, padding=16):
    f = QFrame(parent)
    f.setObjectName("card")
    f.setStyleSheet(f"""
        QFrame#card {{
            background-color: {CLR_PANEL};
            border: 1px solid {CLR_BORDER};
            border-radius: 12px;
        }}
    """)
    layout = QVBoxLayout(f)
    layout.setContentsMargins(padding, padding, padding, padding)
    layout.setSpacing(10)
    return f

def section_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;")
    return lbl

def title_label(text, size=15, bold=True):
    lbl = QLabel(text)
    weight = "700" if bold else "500"
    lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: {size}px; font-weight: {weight};")
    return lbl

def _darken_hex(hex_color: str, factor: float = 0.82) -> str:
    """Return a darkened version of a CSS hex color string."""
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"

def accent_button(text, color=CLR_ACCENT, hover=None):
    btn = QPushButton(text)
    hover = hover or color
    pressed = _darken_hex(color)
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {color};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 18px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {pressed}; }}
        QPushButton:disabled {{ background-color: {CLR_INPUT}; color: {CLR_TEXT_SEC}; }}
    """)
    return btn

def ghost_button(text):
    btn = QPushButton(text)
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: transparent;
            color: {CLR_ACCENT};
            border: 1px solid {CLR_ACCENT};
            border-radius: 8px;
            padding: 7px 16px;
            font-weight: 500;
        }}
        QPushButton:hover {{ background-color: rgba(10,132,255,0.15); }}
        QPushButton:pressed {{ background-color: rgba(10,132,255,0.30); }}
        QPushButton:disabled {{ color: {CLR_TEXT_SEC}; border-color: {CLR_BORDER}; }}
    """)
    return btn

def _cond_token(text, suffix, absent):
    """One condition value for a run folder name.

    A value that was never entered becomes an explicit token ("norpm"), never a
    dropped segment: an unrecorded run must not end up looking identical to a
    deliberate one. That ambiguity is exactly what made the 2026-09 captures
    impossible to compare -- RPM sat in free-text notes on some runs and nowhere
    on others, and nothing in the folder name said which.
    """
    try:
        return f"{float(str(text).strip()):g}{suffix}"
    except (TypeError, ValueError):
        return absent


def input_row(label_text, widget, label_width=130):
    row = QWidget()
    hl = QHBoxLayout(row)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(10)
    lbl = QLabel(label_text)
    lbl.setFixedWidth(label_width)
    lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
    hl.addWidget(lbl)
    hl.addWidget(widget)
    return row

def refresh_icon(color=CLR_ACCENT, size=20):
    """Circular reload arrow, painted at runtime so the repo needs no icon asset."""
    # Back the pixmap with 2x the pixels for crisp edges on HiDPI screens.  The
    # device pixel ratio makes QPainter take logical coordinates, so the geometry
    # below is still written in plain `size` units — do not scale the painter too.
    ss = 2
    px = QPixmap(size * ss, size * ss)
    px.fill(Qt.GlobalColor.transparent)
    px.setDevicePixelRatio(ss)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.20
    r  = (size - 2 * margin) / 2.0
    cx = cy = size / 2.0

    pen = QPen(QColor(color))
    pen.setWidthF(max(1.4, size * 0.13))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Open arc: 270° starting at the top, leaving the upper-right quadrant free
    # for the arrowhead.  Qt angles are 1/16°, counter-clockwise from 3 o'clock.
    p.drawArc(QRectF(margin, margin, 2 * r, 2 * r), 90 * 16, 270 * 16)

    # Arrowhead sitting on the open end at the top, pointing clockwise
    a = size * 0.17
    head = QPolygonF([
        QPointF(cx + a,       cy - r),
        QPointF(cx - a * 0.3, cy - r - a * 0.8),
        QPointF(cx - a * 0.3, cy - r + a * 0.8),
    ])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(head)
    p.end()
    return QIcon(px)

def dot_indicator(color=CLR_TEXT_SEC, size=10):
    lbl = QLabel("●")
    lbl.setStyleSheet(f"color: {color}; font-size: {size}px; background: transparent;")
    return lbl

def separator():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {CLR_BORDER}; background: {CLR_BORDER};")
    line.setFixedHeight(1)
    return line

# ── Calibration image widget ──────────────────────────────────────────────────

class ClickableLabel(QLabel):
    """Plain QLabel that emits clicked() when pressed."""
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class ClickableImageWidget(QLabel):
    """Calibration image widget with pan/zoom and sub-pixel-accurate point picking.

    Coordinate model
    ----------------
    The widget always fills its full width.  At zoom=1 the image is scaled to
    fit the widget width; at higher zoom levels the displayed region is a crop
    of the original.

    _zoom       : float, current zoom factor (1.0 = fit-to-width)
    _pan_x/y    : float, offset in *original image pixels* of the top-left
                  corner of the current view

    Screen → image:   img = pan + screen / (fit_scale * zoom)
    Image → screen:   screen = (img - pan) * fit_scale * zoom

    pointsChanged is emitted with the current list of (x, y) tuples (original
    image coordinates) every time a point is added or the list is reset.
    """
    pointsChanged = Signal(list)

    _MAX_ZOOM = 16.0
    _MIN_ZOOM = 1.0   # enforced dynamically so image never shrinks below fit

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap_orig = None
        self._points      = []
        self._zoom        = 1.0
        self._pan_x       = 0.0   # top-left of view in original image px
        self._pan_y       = 0.0
        self._drag_start  = None  # (screen_x, screen_y, pan_x, pan_y) on right-drag start
        self._hover_img   = None  # (img_x, img_y) of cursor — drives snap preview
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ── Public API ────────────────────────────────────────────────────────────

    def setCalibrationImage(self, pixmap: QPixmap):
        self._pixmap_orig = pixmap
        self._points = []
        self._zoom   = 1.0
        self._pan_x  = 0.0
        self._pan_y  = 0.0
        self._redraw()

    def resetPoints(self):
        self._points = []
        self._redraw()
        self.pointsChanged.emit(self._points)

    def getPoints(self) -> list:
        return list(self._points)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _fit_scale(self):
        """Scale factor when zoom=1 (image fits widget width)."""
        if self._pixmap_orig is None or self.width() <= 0:
            return 1.0
        return self.width() / self._pixmap_orig.width()

    def _effective_scale(self):
        return self._fit_scale() * self._zoom

    def _screen_to_img(self, sx, sy):
        s = self._effective_scale()
        return self._pan_x + sx / s, self._pan_y + sy / s

    def _img_to_screen(self, ix, iy):
        s = self._effective_scale()
        return (ix - self._pan_x) * s, (iy - self._pan_y) * s

    def _clamp_pan(self):
        """Keep pan within image bounds so you can't scroll off the edge."""
        if self._pixmap_orig is None:
            return
        ow = self._pixmap_orig.width()
        oh = self._pixmap_orig.height()
        s  = self._effective_scale()
        view_w = self.width()  / s
        view_h = self.height() / s
        self._pan_x = max(0.0, min(self._pan_x, ow - view_w))
        self._pan_y = max(0.0, min(self._pan_y, oh - view_h))

    # ── Events ────────────────────────────────────────────────────────────────

    def wheelEvent(self, event):
        if self._pixmap_orig is None:
            return
        delta   = event.angleDelta().y()
        factor  = 1.15 if delta > 0 else 1.0 / 1.15
        new_zoom = max(self._MIN_ZOOM, min(self._MAX_ZOOM, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        # Zoom centred on cursor: keep the image pixel under the cursor fixed
        cx, cy  = event.position().x(), event.position().y()
        img_cx, img_cy = self._screen_to_img(cx, cy)
        self._zoom  = new_zoom
        s_new       = self._effective_scale()
        self._pan_x = img_cx - cx / s_new
        self._pan_y = img_cy - cy / s_new
        self._clamp_pan()
        self._update_height()
        self._redraw()
        event.accept()

    def mousePressEvent(self, event):
        if self._pixmap_orig is None:
            return
        if event.button() == Qt.MouseButton.RightButton or \
           event.button() == Qt.MouseButton.MiddleButton:
            # Start pan drag
            self._drag_start = (event.position().x(), event.position().y(),
                                self._pan_x, self._pan_y)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if len(self._points) >= 2:
            return
        img_x, img_y = self._screen_to_img(event.position().x(), event.position().y())
        img_x = int(max(0, min(img_x, self._pixmap_orig.width()  - 1)))
        img_y = int(max(0, min(img_y, self._pixmap_orig.height() - 1)))
        # Second point: auto-snap to the dominant axis relative to P1
        if len(self._points) == 1:
            x1, y1 = self._points[0]
            if abs(img_y - y1) >= abs(img_x - x1):
                img_x = x1   # vertical measurement — lock X
            else:
                img_y = y1   # horizontal measurement — lock Y
        self._points.append((img_x, img_y))
        self._hover_img = None
        self._redraw()
        self.pointsChanged.emit(self._points)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            sx0, sy0, px0, py0 = self._drag_start
            dx = event.position().x() - sx0
            dy = event.position().y() - sy0
            s  = self._effective_scale()
            self._pan_x = px0 - dx / s
            self._pan_y = py0 - dy / s
            self._clamp_pan()
            self._redraw()
        elif len(self._points) == 1 and self._pixmap_orig is not None:
            # Track cursor for snap preview while placing P2
            hx, hy = self._screen_to_img(event.position().x(), event.position().y())
            hx = int(max(0, min(hx, self._pixmap_orig.width()  - 1)))
            hy = int(max(0, min(hy, self._pixmap_orig.height() - 1)))
            self._hover_img = (hx, hy)
            self._redraw()

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag_start = None
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseDoubleClickEvent(self, event):
        """Double-click resets zoom and pan to fit-to-width."""
        if self._pixmap_orig is None:
            return
        self._zoom  = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._update_height()
        self._redraw()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap_orig is not None:
            self._clamp_pan()
            self._update_height()
            self._redraw()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _update_height(self):
        """Resize widget height to match the visible portion's aspect ratio."""
        if self._pixmap_orig is None or self.width() <= 0:
            return
        s  = self._effective_scale()
        oh = self._pixmap_orig.height()
        visible_h = oh - self._pan_y          # image rows visible below pan
        screen_h  = min(visible_h * s,        # pixels those rows take on screen
                        oh * self._fit_scale()) # cap at fit-to-width height
        self.setFixedHeight(max(1, int(screen_h)))

    def _redraw(self):
        if self._pixmap_orig is None:
            return
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        s   = self._effective_scale()
        ow  = self._pixmap_orig.width()
        oh  = self._pixmap_orig.height()

        # Source rect in original image coordinates
        src_x = int(self._pan_x)
        src_y = int(self._pan_y)
        src_w = int(min(w / s, ow - src_x))
        src_h = int(min(h / s, oh - src_y))
        src_w = max(1, src_w)
        src_h = max(1, src_h)

        # Crop then scale to widget size
        crop   = self._pixmap_orig.copy(src_x, src_y, src_w, src_h)
        canvas = crop.scaled(int(src_w * s), int(src_h * s),
                             Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.FastTransformation)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Draw placed points ────────────────────────────────────────────────
        for idx, (ix, iy) in enumerate(self._points):
            # Screen position relative to current view
            sx = (ix - self._pan_x) * s
            sy = (iy - self._pan_y) * s

            # Pixel highlight box (visible when zoomed in enough)
            if s >= 4.0:
                px_left  = (ix       - self._pan_x) * s
                px_top   = (iy       - self._pan_y) * s
                px_right = (ix + 1.0 - self._pan_x) * s
                px_bot   = (iy + 1.0 - self._pan_y) * s
                highlight = QColor("#ff453a")
                highlight.setAlpha(80)
                painter.fillRect(int(px_left), int(px_top),
                                 int(px_right - px_left), int(px_bot - px_top),
                                 highlight)
                # Solid pixel-border outline
                painter.setPen(QPen(QColor("#ff453a"), 1))
                painter.drawRect(int(px_left), int(px_top),
                                 int(px_right - px_left) - 1,
                                 int(px_bot   - px_top)  - 1)

            # Crosshair (full-span lines through the chosen pixel centre)
            pen = QPen(QColor("#ff453a"), 1.5)
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawLine(int(sx), 0, int(sx), canvas.height())
            painter.drawLine(0, int(sy), canvas.width(), int(sy))

            # Small circle at intersection
            painter.setPen(QPen(QColor("#ff453a"), 1.5))
            painter.drawEllipse(int(sx) - 5, int(sy) - 5, 10, 10)

            # Label  "P1" / "P2"  with a dark backing rectangle
            label = f"P{idx + 1}  ({ix}, {iy})"
            font  = painter.font()
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            fm        = painter.fontMetrics()
            lw_px     = fm.horizontalAdvance(label) + 6
            lh_px     = fm.height() + 4
            lx        = int(sx) + 8
            ly        = int(sy) - lh_px - 4
            # Keep label inside canvas
            if lx + lw_px > canvas.width():
                lx = int(sx) - lw_px - 8
            if ly < 0:
                ly = int(sy) + 8
            backing = QColor(0, 0, 0, 160)
            painter.fillRect(lx, ly, lw_px, lh_px, backing)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(lx + 3, ly + lh_px - 5, label)

        # ── Snap preview: dashed line + V/H badge while placing P2 ──────────
        if len(self._points) == 1 and self._hover_img is not None:
            x1, y1 = self._points[0]
            hx, hy = self._hover_img
            if abs(hy - y1) >= abs(hx - x1):
                # vertical snap — P2 will lock to x1
                snap_x, snap_y = x1, hy
                snap_mode = "V"
            else:
                # horizontal snap — P2 will lock to y1
                snap_x, snap_y = hx, y1
                snap_mode = "H"
            sx1, sy1   = self._img_to_screen(x1,     y1)
            sx2, sy2   = self._img_to_screen(snap_x, snap_y)
            dash_pen = QPen(QColor("#f5a623"), 1.5)
            dash_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(dash_pen)
            painter.drawLine(int(sx1), int(sy1), int(sx2), int(sy2))
            # Ghost point at snapped position
            painter.setPen(QPen(QColor("#f5a623"), 1.5))
            painter.drawEllipse(int(sx2) - 4, int(sy2) - 4, 8, 8)
            # V / H mode badge (bottom-left of canvas)
            font = painter.font(); font.setPointSize(9); font.setBold(True)
            painter.setFont(font)
            fm    = painter.fontMetrics()
            badge = f" {snap_mode} "
            bw = fm.horizontalAdvance(badge) + 4
            bh = fm.height() + 4
            painter.fillRect(6, canvas.height() - bh - 6, bw, bh, QColor(0, 0, 0, 180))
            painter.setPen(QColor("#f5a623"))
            painter.drawText(8, canvas.height() - 8, badge)

        # ── Measurement line between P1 and P2 ───────────────────────────────
        if len(self._points) == 2:
            (x1, y1), (x2, y2) = self._points
            sx1, sy1 = self._img_to_screen(x1, y1)
            sx2, sy2 = self._img_to_screen(x2, y2)
            mpen = QPen(QColor("#f5a623"), 1.5)
            mpen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(mpen)
            painter.drawLine(int(sx1), int(sy1), int(sx2), int(sy2))

        # ── Zoom badge (top-right corner) ─────────────────────────────────────
        if self._zoom > 1.01:
            badge_txt = f"{self._zoom:.1f}×"
            font = painter.font()
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            fm    = painter.fontMetrics()
            bw    = fm.horizontalAdvance(badge_txt) + 8
            bh    = fm.height() + 4
            bx    = canvas.width() - bw - 6
            by    = 6
            painter.fillRect(bx, by, bw, bh, QColor(0, 0, 0, 160))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(bx + 4, by + bh - 5, badge_txt)

        # ── Scroll hint when not at 1× ────────────────────────────────────────
        if self._zoom <= 1.01:
            hint = "Scroll to zoom  ·  Right-drag to pan  ·  Double-click to reset"
            font = painter.font()
            font.setPointSize(7)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(180, 180, 180, 140))
            painter.drawText(6, canvas.height() - 6, hint)

        painter.end()
        self.setPixmap(canvas)


# ── Backend controllers (unchanged from Windows_Experiment_GUI.py) ────────────

_SESSION_LOG_FILE = None

def _get_session_log_file():
    """Return the path to this session's serial log, creating it lazily on first call."""
    global _SESSION_LOG_FILE
    if _SESSION_LOG_FILE is None:
        lacie = find_lacie_drive()
        if lacie:
            log_dir = os.path.join(lacie, "Logs")
        else:
            log_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(log_dir, exist_ok=True)
        _SESSION_LOG_FILE = os.path.join(
            log_dir, datetime.now().strftime("serial_%Y%m%d_%H%M%S.txt"))
    return _SESSION_LOG_FILE

def log_serial(message, log_file=None):
    if log_file is None:
        log_file = _get_session_log_file()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")

class ArduinoController:
    def __init__(self, port, baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.homing_error = None   # set by connect() if the board reports HOMING_FAILED

    # How long the board may stay COMPLETELY silent before we give up.
    CONNECT_QUIET_TIMEOUT_S = 8.0
    # Absolute ceiling once it IS talking.  Homing runs before the board's
    # first heartbeat and a home from the far end of the axis is ~49 s
    # (986,000 steps at the 10,000 steps/s search speed), so a fixed short
    # wait rejected a perfectly healthy board that simply wasn't finished yet.
    CONNECT_MAX_WAIT_S = 120.0

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)
            try: self.ser.reset_input_buffer()
            except Exception: pass
            start_time = time.time()
            last_traffic = start_time
            self.homing_error = None
            while True:
                now = time.time()
                # Silence is the real "nothing there" signal.  Anything at all
                # from the board (homing progress, debug) proves it is alive and
                # buys it more time, so we wait out a slow home instead of
                # reporting a missing board.
                if now - last_traffic > self.CONNECT_QUIET_TIMEOUT_S:
                    raise RuntimeError("No Arduino detected on this port.")
                if now - start_time > self.CONNECT_MAX_WAIT_S:
                    raise RuntimeError(
                        "Arduino is talking but never became ready "
                        f"(waited {self.CONNECT_MAX_WAIT_S:.0f} s).")
                line = self.ser.readline().decode('utf-8', errors='replace').strip()
                if not line: continue
                last_traffic = time.time()
                log_serial(f"Received on connect: {line}")
                if "HOMING_FAILED" in line:
                    # Keep waiting — the board still sends ARDUINO_READY after a
                    # failed home — but hold the reason so the GUI can show it.
                    self.homing_error = line.split("HOMING_FAILED:", 1)[-1].strip()
                if "ARDUINO_READY" in line:
                    break
        except serial.SerialException as e:
            if "Resource busy" in str(e):
                raise RuntimeError(f"Port {self.port} is busy.")
            raise RuntimeError(f"Could not open port {self.port}: {e}")

    def send_motor_command(self, speed, distance):
        command = f"SPEED:{speed};DIST:{distance}\n"
        self.ser.write(command.encode())
        log_serial(f"Sent: {command.strip()}")

    def send_stop(self):
        self.ser.write(b"STOP\n")
        log_serial("Sent: STOP")

    def disconnect(self):
        if hasattr(self, 'ser') and self.ser and self.ser.is_open:
            self.ser.close()

    def reset_state(self):
        try:
            if hasattr(self, 'ser') and self.ser and self.ser.is_open:
                self.ser.write("RESET:1\n".encode())
                start = time.time()
                while time.time() - start < 5:
                    if self.ser.in_waiting > 0:
                        response = self.ser.readline().decode().strip()
                        if "ARDUINO_READY" in response: break
                    time.sleep(0.1)
        except Exception as e:
            print(f"Reset error: {e}")


class RpmController:
    def __init__(self, port, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=2)
            time.sleep(2)  # Arduino resets on serial open; wait for it to boot
            try: self.ser.reset_input_buffer()
            except Exception: pass
        except serial.SerialException as e:
            if "Resource busy" in str(e):
                raise RuntimeError(f"Port {self.port} is busy.")
            raise RuntimeError(f"Could not open port {self.port}: {e}")

    def send_rpm(self, rpm: float):
        cmd = f"RPM:{rpm:.1f}\n"
        self.ser.write(cmd.encode())

    def send_stop(self):
        self.ser.write(b"STOP\n")

    def disconnect(self):
        if hasattr(self, 'ser') and self.ser and self.ser.is_open:
            self.ser.close()


ALICAT_DEBUG = False   # True to log every TX/RX frame to the console


class AlicatMFC:
    """Serial driver for an Alicat MCQ mass flow controller (19200 8N1).

    The unit never streams — it answers exactly one frame per command.  Commands
    and replies are both terminated by a bare CR, e.g.

        A +00.995 +030.17 +00000 +00500 +00500 +0000000     N2

    Send CR only, never CRLF: the unit ends the line at the CR and leaves the LF
    sitting in its own input buffer, so the next command reaches it as "\nA…",
    which is not a valid unit ID.  It is silently dropped and another LF is left
    behind, so one CRLF command deafens the unit until it is power-cycled.

    DTR and RTS are held high: on an RS-232 link those lines feed the adapter's
    line driver, and dropping them kills transmit while leaving receive alive.

    Threading: every port operation belongs to the reader thread.  Other threads
    only ever call set_flow()/flow_off(), which enqueue a setpoint.

    Ramping: set_flow(sccm, ramp_rate) moves the setpoint from wherever it is now
    to `sccm` at `ramp_rate` sccm/s.  The reader sends the ramp's current value on
    every cycle (RAMP_INTERVAL while ramping), so the Alicat sees a staircase of
    small steps that its own control loop smooths.  flow_off() always cuts to
    0 at once and cancels any ramp.
    """
    DEVICE_ID = "A"
    BAUD      = 19200

    def __init__(self, port: str):
        self.port = port
        self.ser: serial.Serial | None = None
        self._cmd_queue: queue.SimpleQueue = queue.SimpleQueue()   # setpoints, sccm
        self._lock = threading.Lock()
        self._commanded = 0.0     # last setpoint sent (or about to be)
        self._ramp = None         # (from_sccm, to_sccm, sccm_per_s, t0) while ramping

    # ── command builders ──────────────────────────────────────────────────
    @classmethod
    def cmd_poll(cls) -> str:
        return f"{cls.DEVICE_ID}\r"

    @classmethod
    def cmd_setpoint(cls, sccm: float) -> str:
        return f"{cls.DEVICE_ID}S{sccm:.1f}\r"

    # ── lifecycle ─────────────────────────────────────────────────────────
    def connect(self):
        try:
            self.ser = serial.Serial(
                self.port, self.BAUD,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0,          # non-blocking; the reader drains in_waiting
                rtscts=False,
                dsrdtr=False,
                xonxoff=False,
            )
        except serial.SerialException as e:
            if "Resource busy" in str(e) or "Access is denied" in str(e):
                raise RuntimeError(f"Port {self.port} is busy — close whatever else is using it.")
            raise RuntimeError(f"Could not open {self.port}: {e}")

        self.ser.dtr = True
        self.ser.rts = True
        time.sleep(0.2)             # let the line drivers settle

        # A lone CR terminates whatever partial line the unit may be holding
        # (e.g. from an earlier program that sent CRLF), so we start clean.
        self.ser.write(b"\r")
        self.ser.flush()
        time.sleep(0.2)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

        if not self._probe():
            self.ser.close()
            raise RuntimeError(
                f"No reply from the Alicat on {self.port}. Check the cable, that unit ID "
                f"is '{self.DEVICE_ID}', baud is {self.BAUD}, and control mode is Serial/Front Panel."
            )

        self._cmd_queue.put(0.0)   # always start from 0 sccm

    def _probe(self, attempts: int = 3) -> bool:
        """Poll a few times and report whether the unit answers at all."""
        for _ in range(attempts):
            self.write(self.cmd_poll())
            if self.read_frame(timeout_s=0.5) is not None:
                return True
        return False

    def close(self):
        """Reader-thread only — sets 0 sccm, then releases the port."""
        if self.ser and self.ser.is_open:
            try:
                self.write(self.cmd_setpoint(0.0))
                time.sleep(0.1)
            except Exception:
                pass
            try: self.ser.close()
            except Exception: pass

    # ── queued commands (safe from any thread) ────────────────────────────
    def set_flow(self, sccm: float, ramp_rate: float | None = None) -> float:
        """Go to `sccm`: at once, or at `ramp_rate` sccm/s from the current
        setpoint.  Returns the ramp time in seconds (0 for a jump)."""
        with self._lock:
            start = self._ramp_value() if self._ramp else self._commanded
            if ramp_rate and ramp_rate > 0 and abs(sccm - start) >= 0.1:
                self._ramp = (start, sccm, ramp_rate, time.monotonic())
                return abs(sccm - start) / ramp_rate
            self._ramp = None
            self._cmd_queue.put(sccm)
            return 0.0

    def flow_off(self):
        with self._lock:
            self._ramp = None
            self._cmd_queue.put(0.0)

    @property
    def ramping(self) -> bool:
        return self._ramp is not None

    def _ramp_value(self) -> float:
        start, target, rate, t0 = self._ramp
        step = rate * (time.monotonic() - t0)
        if step >= abs(target - start):
            return target
        return start + step if target > start else start - step

    def next_command(self) -> str:
        """A pending setpoint if one is queued, else the ramp's current value,
        else a plain status poll."""
        with self._lock:
            try:
                sccm = self._cmd_queue.get_nowait()
            except queue.Empty:
                if self._ramp is None:
                    return self.cmd_poll()
                sccm = self._ramp_value()
                if sccm == self._ramp[1]:
                    self._ramp = None          # arrived: this is the last step
            self._commanded = sccm
            return self.cmd_setpoint(sccm)

    # ── raw I/O (reader thread only) ──────────────────────────────────────
    def write(self, cmd: str):
        if self.ser and self.ser.is_open:
            raw = cmd.encode("ascii")
            if ALICAT_DEBUG:
                print(f"[ALICAT TX] {raw!r}", flush=True)
            self.ser.write(raw)
            self.ser.flush()

    def read_frame(self, timeout_s: float) -> str | None:
        """Accumulate bytes until a CR arrives; None if the unit stayed quiet.

        Leftovers after the CR are kept in _rx_buf so a frame split across two
        reads — or arriving late behind the FTDI latency timer — is never lost.
        """
        buf = getattr(self, "_rx_buf", b"")
        deadline = time.monotonic() + timeout_s
        while True:
            if b"\r" in buf:
                line, _, buf = buf.partition(b"\r")
                self._rx_buf = buf
                text = line.decode("ascii", errors="replace").strip()
                if text:
                    if ALICAT_DEBUG:
                        print(f"[ALICAT RX] {text!r}", flush=True)
                    return text
                continue                 # empty line (stray LF) — keep looking
            if time.monotonic() >= deadline:
                self._rx_buf = buf
                return None
            n = self.ser.in_waiting if self.ser else 0
            if n:
                buf += self.ser.read(n)
            else:
                time.sleep(0.005)


class PhantomController:
    def __init__(self):
        self.ph = None; self.cam = None; self.current_cine = None
        self.is_connected = False; self.is_recording = False
        self.is_armed = False
        self._fps = 1000.0  # updated by configure()

    def connect(self, ip_address=None, camera_index=0):
        if not PHANTOM_SDK_AVAILABLE:
            raise RuntimeError("Phantom SDK not installed")
        import pyphantom as _pyph
        self.ph = Phantom()
        # Check count BEFORE discover — discover() auto-adds a simulated camera
        # when no real camera is found, so post-discover count is always ≥ 1.
        real_count = self.ph.camera_count
        self.ph.discover(print_list=False)
        if real_count == 0:
            raise RuntimeError("No Phantom camera found on network")
        cam_index = min(camera_index, self.ph.camera_count - 1)
        try:
            self.cam = self.ph.Camera(cam_index)
        except Exception as e:
            if "requested parameter is missing" in str(e).lower() or "missing" in str(e).lower():
                # Camera not in live/recording state — Camera.__init__ tries to get the
                # live cine handle which requires the camera to be armed/live.
                # Bypass by creating the Camera instance without calling __init__.
                cam = object.__new__(_pyph.Camera)
                cam._camera_num = cam_index
                cam._live_cine = None
                self.cam = cam
            else:
                raise
        self.is_connected = True
        return True

    def configure(self, width, height, fps, exposure_us, partition_count=1, post_trigger_frames=0, exp_index=0):
        if not self.is_connected: raise RuntimeError("Camera not connected")
        self.cam.resolution = (int(width), int(height))
        self.cam.partition_count = int(partition_count)
        self.cam.post_trigger_frames = int(post_trigger_frames)
        self.cam.frame_rate = float(fps)
        actual_fps = self.cam.frame_rate
        self._fps = actual_fps
        max_exp = (1.0 / actual_fps) * 1e6
        if exposure_us >= max_exp:
            raise RuntimeError(f"Exposure {exposure_us}μs exceeds max {max_exp:.1f}μs")
        self.cam.exposure = float(exposure_us)
        if exp_index != 0:
            self.cam.exp_index = int(exp_index)
        return {'resolution': self.cam.resolution, 'frame_rate': actual_fps,
                'exposure': self.cam.exposure}

    def start_recording(self):
        self.cam.record(); self.is_recording = True; self.is_armed = True
        return True

    def trigger(self):
        self.cam.trigger(); self.is_armed = False; return True

    def camera_post_trigger(self):
        """(post_trigger_frames, frame_rate) as the CAMERA has them, or None.

        The GUI fields can differ from what Apply Config last pushed (fields
        edited since, or the camera power-cycled), and it is the camera's
        values that decide when the cine is actually stored."""
        try:
            return int(self.cam.post_trigger_frames), float(self.cam.frame_rate)
        except Exception:
            return None

    def wait_for_stored(self, cine_index=1, timeout_s=10.0, poll_s=0.25):
        """Poll until the camera reports the cine recorded.

        True once stored, False on timeout, None if the camera can't say (the
        query itself fails) -- callers then fall back to a fixed wait."""
        deadline = time.time() + timeout_s
        while True:
            try:
                if self.cam.partition_recorded(cine_index):
                    return True
            except Exception:
                return None
            if time.time() >= deadline:
                return False
            time.sleep(poll_s)

    # A CINE save is abandoned only when progress genuinely stops, never on a
    # fixed ceiling: a large capture can legitimately run far longer than any
    # constant while still writing steadily.  The old 600 s limit failed
    # mid-save on big buffers purely because they were big.
    CINE_STALL_TIMEOUT_S = 120.0
    CINE_ABSOLUTE_MAX_S  = 6 * 3600.0     # last-resort sanity stop

    @staticmethod
    def _eta_seconds(elapsed, done, total):
        """Linear extrapolation of time remaining; None until it's meaningful."""
        if done <= 0 or elapsed <= 0 or total <= 0 or done >= total:
            return None
        return max(0.0, elapsed * (total - done) / done)

    def save_recording(self, output_path, cine_index=1, file_format='cine', frame_range=None,
                       progress_cb=None):
        self.current_cine = self.cam.Cine(cine_index)
        fmt_map = {'cine': 0, 'tiff': -8, 'tif': -8, 'avi': -7}
        self.current_cine.save_type = utils.FileTypeEnum(fmt_map.get(file_format, 0))
        r = self.current_cine.range
        if frame_range is None:
            self.current_cine.save_range = utils.FrameRange(r.first_image, r.last_image)
        else:
            # Clamp to what the camera actually recorded — asking for frames
            # outside the cine's range errors out.  Mirrors save_tiffs_from_ram.
            self.current_cine.save_range = utils.FrameRange(
                max(r.first_image, frame_range[0]),
                min(r.last_image,  frame_range[1]))
        self.current_cine.save_name = output_path
        # The SDK's blocking save() has a known bug where it throws even on success.
        # Use save_non_blocking() and poll save_percentage until complete.
        # The callback sometimes stalls before reaching 100 — treat >= 90% stable
        # for 30 s as done (file is effectively complete at that point).
        self.current_cine._save_percentage = -1
        self.current_cine.save_non_blocking()
        started = time.time()
        hard_deadline = started + self.CINE_ABSOLUTE_MAX_S
        last_pct, last_change = -1, started
        while time.time() < hard_deadline:
            pct = self.current_cine.save_percentage
            now = time.time()
            if pct >= 100:
                if progress_cb: progress_cb(100, 0.0)
                break
            if pct != last_pct:
                last_change = now
                last_pct = pct
                if progress_cb:
                    progress_cb(max(0, pct),
                                self._eta_seconds(now - started, pct, 100))
            elif pct >= 90 and now - last_change > 30.0:
                if progress_cb: progress_cb(100, 0.0)
                break  # stalled near end — assume complete
            elif now - last_change > self.CINE_STALL_TIMEOUT_S:
                if pct < 0:
                    raise RuntimeError(
                        f"CINE save never started — no progress from the SDK in "
                        f"{self.CINE_STALL_TIMEOUT_S:.0f} s")
                raise RuntimeError(
                    f"CINE save stalled at {pct}% — no progress for "
                    f"{self.CINE_STALL_TIMEOUT_S:.0f} s")
            time.sleep(0.25)
        else:
            raise RuntimeError(
                f"CINE save exceeded {self.CINE_ABSOLUTE_MAX_S / 3600:.0f} h "
                f"(progress: {self.current_cine.save_percentage}%)")
        # "Done" above is the SDK's progress callback (or a stall at >= 90%),
        # not proof of a file.  A save that reports done with nothing on disk
        # used to be logged as a success.
        try:
            size = os.path.getsize(output_path)
        except OSError:
            size = -1
        if size <= 0:
            raise RuntimeError(
                f"the SDK reported the .cine save finished (last progress {last_pct}%) "
                f"but {'the file is empty' if size == 0 else 'no file was written'}: "
                f"{output_path}")
        return True

    def save_tiffs_from_ram(self, output_dir, tiff_prefix='frame', cine_index=1, frame_range=None,
                            progress_cb=None):
        """Read frames from camera RAM and write TIFFs directly — no SDK save() involved."""
        c = self.cam.Cine(cine_index)
        r = c.range
        if frame_range is not None:
            f_start = max(r.first_image, frame_range[0])
            f_end   = min(r.last_image,  frame_range[1])
        else:
            f_start, f_end = r.first_image, r.last_image
        total = max(1, f_end - f_start + 1)
        started = time.time()
        last_pct = -1
        # get_imagessave uses range() which is exclusive at the end — pass f_end + 1
        for i, (_, img) in enumerate(c.get_imagessave(utils.FrameRange(f_start, f_end + 1))):
            cv2.imwrite(os.path.join(output_dir, f"{tiff_prefix}{i:06d}.tif"), img)
            if progress_cb:
                done = i + 1
                pct  = int(done / total * 100)
                # Only emit when the percentage actually moves.  Firing per frame
                # queued one Qt event per TIFF — tens of thousands of them on a
                # long capture, which floods the GUI event loop.
                if pct != last_pct:
                    last_pct = pct
                    progress_cb(pct, self._eta_seconds(time.time() - started, done, total))
        return True

    def abort(self):
        if self.is_recording:
            self.cam.clear_ram(); self.is_recording = False
        self.is_armed = False
        return True

    def ping(self):
        try: _ = self.cam.frame_rate; return True
        except Exception: self.is_connected = False; return False

    def disconnect(self):
        try:
            if self.cam: self.cam.close(); self.cam = None
            if self.ph: self.ph.close(); self.ph = None
        except Exception: pass
        self.is_connected = False; self.is_recording = False


class AFGController:
    def __init__(self):
        self.rm = None; self.afg = None; self.is_connected = False
        self.pulse_duration = 0.001
        self.channel = 1

    def connect(self, resource_name=None):
        if not PYVISA_AVAILABLE: raise RuntimeError("PyVISA not installed")
        self.rm = pyvisa.ResourceManager()
        resources = self.rm.list_resources()
        if resource_name:
            self.afg = self.rm.open_resource(resource_name)
        else:
            found = False
            for res in resources:
                if 'USB' in res.upper() or '0x0699' in res:
                    try:
                        self.afg = self.rm.open_resource(res)
                        idn = self.afg.query('*IDN?')
                        if 'AFG' in idn: found = True; break
                    except:
                        if self.afg: self.afg.close(); self.afg = None
            if not found: raise RuntimeError("AFG1062 not found")
        self.afg.timeout = 5000
        self.is_connected = True
        return True

    def configure_pulse(self, duration_seconds, amplitude_volts=5.0, channel=1):
        if not self.is_connected: raise RuntimeError("AFG not connected")
        self.pulse_duration = duration_seconds
        self.channel = channel
        ch = f'SOUR{channel}:'

        # Set waveform to PULSE — allows direct pulse width control
        # independent of period, unlike SQUARE (which is always 50% duty cycle)
        self.afg.write(f'{ch}FUNC PULS')

        # Set period just slightly longer than the pulse width (10% overhead, min 1ms dead time)
        # A large period (e.g. 10x) causes the AFG to linger in an unexpected output state
        # during the dead time, making the pulse appear much longer than intended
        period_seconds = duration_seconds + max(duration_seconds * 0.1, 1e-3)
        self.afg.write(f'{ch}FREQ {1.0 / period_seconds}')

        # Set pulse width directly in seconds
        # AFG1062 accepts pulse width via PULSe:WIDTh command
        self.afg.write(f'{ch}PULS:WIDT {duration_seconds}')

        # Set TTL-compatible 0-5V output using HIGH/LOW only
        # (avoids conflict between VOLT/VOLT:OFFS and VOLT:HIGH/LOW)
        self.afg.write(f'{ch}VOLT:LOW 0.0')
        self.afg.write(f'{ch}VOLT:HIGH {amplitude_volts}')

        # Configure burst mode: single pulse per manual trigger
        self.afg.write(f'{ch}BURS:STAT ON')
        self.afg.write(f'{ch}BURS:MODE TRIG')
        self.afg.write(f'{ch}BURS:NCYC 1')
        self.afg.write(f'{ch}BURS:TRIG:SOUR MAN')

        # Enable channel output
        self.afg.write(f'OUTP{channel}:STAT ON')

    def trigger(self, channel=1):
        if not self.is_connected: raise RuntimeError("AFG not connected")
        self.afg.write('*TRG')

    def disconnect(self):
        try:
            if self.afg:
                try: self.afg.write('OUTP1:STAT OFF'); self.afg.write('OUTP2:STAT OFF')
                except: pass
                self.afg.close(); self.afg = None
            if self.rm: self.rm.close(); self.rm = None
        except: pass
        self.is_connected = False

# ── Worker thread helper ──────────────────────────────────────────────────────

class Worker(QObject):
    """Generic worker — emit result(obj) or error(str) from a background thread."""
    result = Signal(object)
    error  = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn; self._args = args; self._kwargs = kwargs

    def run(self):
        try:
            self.result.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            self.error.emit(str(e))

class _GuiLogStream:
    """Sink that routes written text into the GUI log queue."""
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str):
        for line in text.splitlines():
            if line.strip():
                self._q.put(line)

    def flush(self):
        pass

    def isatty(self):
        return False

    def fileno(self):
        raise io.UnsupportedOperation("fileno")


class _ElidingLabel(QLabel):
    """Label that shortens its text from the MIDDLE to fit the width it is given.

    QLabel's word wrap breaks on whitespace, and a Windows path has none, so a
    long result path just gets chopped at the right edge and the filename --
    the only part anyone reads -- is the part that disappears. Eliding the
    middle keeps the drive and the filename; the full text stays in a tooltip.
    """
    def __init__(self, text=""):
        super().__init__()
        self._full = text
        self.setMinimumWidth(40)
        self._apply()

    def setText(self, text):                      # noqa: N802  (Qt naming)
        self._full = text or ""
        self._apply()

    def resizeEvent(self, e):                     # noqa: N802
        super().resizeEvent(e)
        self._apply()

    def _apply(self):
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideMiddle,
                                      max(40, self.width() - 4)))
        self.setToolTip(self._full)


class _FitImageLabel(QLabel):
    """Label that scales its image to the width available, keeping aspect.

    Holds the ORIGINAL pixmap and rescales from it on every resize, so
    repeated resizing never compounds resampling artefacts the way rescaling
    an already-scaled copy would.
    """
    def __init__(self):
        super().__init__()
        self._src = None
        self.setMinimumHeight(80)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def setSourcePixmap(self, pix):               # noqa: N802
        self._src = pix
        self._rescale()

    def clearImage(self, message=""):             # noqa: N802
        self._src = None
        super().clear()
        super().setText(message)

    def resizeEvent(self, e):                     # noqa: N802
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if self._src is None or self._src.isNull():
            return
        w = max(1, self.width())
        super().setPixmap(self._src.scaledToWidth(
            w, Qt.TransformationMode.SmoothTransformation))


class _InferenceProgressFilter:
    """Condense tiled_inference's per-frame output into grouped progress + ETA.

    tiled_inference prints one line per frame.  At stride 10 a 2500-frame
    capture is 250 of them, which buries every other stage in the console, and
    none of them says how much longer the run has to go.

    This sits in process_capture's `log` callback and rewrites that stream:
    frame lines are counted and summarised every `every` frames, everything
    else passes through untouched.  Deliberately done here rather than in
    tiled_inference -- process_capture is the single entry point for both the
    GUI and the CLI, and a stage that printed differently depending on its
    caller is exactly what that design forbids.
    """

    # "frame_0056_n559   2560x1600  24 tiles   64.8s  det  391 (>=0.5: 252) ..."
    _FRAME_RE = re.compile(r"^\s*(\S+)\s+\d+x\d+\s+(\d+) tiles\s+([\d.]+)s\s+det\s+(\d+)")
    # "=== 3/4  inference on 250 frames ==="
    _TOTAL_RE = re.compile(r"inference on (\d+) frames")

    def __init__(self, emit, every=25):
        self._emit = emit
        self._every = max(1, every)
        self._total = None
        self._done = 0
        self._elapsed = 0.0
        self._dets = 0
        self._t0 = None

    def __call__(self, line: str):
        text = line.rstrip()

        m = self._TOTAL_RE.search(text)
        if m:
            self._total = int(m.group(1))
            self._done = 0
            self._elapsed = 0.0
            self._dets = 0
            self._t0 = time.time()
            self._emit(text)
            return

        m = self._FRAME_RE.match(text)
        if m is None:
            self._emit(text)
            return

        self._done += 1
        self._elapsed += float(m.group(3))
        self._dets += int(m.group(4))

        last = self._total is not None and self._done >= self._total
        if self._done == 1 or last or self._done % self._every == 0:
            self._emit(self._summary())

    def _summary(self) -> str:
        # Wall clock, not the sum of per-frame times: the gap between them is
        # image loading and JSON writing, which the user waits through too.
        wall = (time.time() - self._t0) if self._t0 else self._elapsed
        per = wall / self._done if self._done else 0.0
        head = (f"  inference {self._done}/{self._total}" if self._total
                else f"  inference {self._done}")
        pct = f" ({self._done * 100 // self._total}%)" if self._total else ""
        eta = ""
        if self._total and self._done < self._total and per > 0:
            eta = f" — {AtomisationApp._fmt_eta(per * (self._total - self._done))} left"
        return (f"{head}{pct}   {per:.1f} s/frame   "
                f"{self._dets:,} detections{eta}")


class _ThreadLocalStream:
    """Thread-local stdout/stderr router installed once at app startup.

    Each worker thread calls set(stream) to route its prints into the GUI log,
    and clear() in its finally block when done.  All other threads (including
    the main thread) fall through to the original stdout/stderr.
    """
    _local = threading.local()

    def __init__(self, fallback):
        self._fallback = fallback

    def set(self, stream):
        self._local.stream = stream

    def clear(self):
        self._local.stream = None

    def write(self, text: str):
        s = getattr(self._local, 'stream', None)
        (s or self._fallback).write(text)

    def flush(self):
        s = getattr(self._local, 'stream', None)
        (s or self._fallback).flush()

    def isatty(self):
        return False

    def fileno(self):
        raise io.UnsupportedOperation("fileno")


class _BlankOrRangeValidator(QDoubleValidator):
    """A QDoubleValidator that also accepts an empty box (meaning "off").
    QDoubleValidator calls empty text Intermediate, and editingFinished only
    fires on Acceptable text, so clearing the box used to change nothing."""

    def validate(self, text, pos):
        if not text.strip():
            return (QValidator.State.Acceptable, text, pos)
        return super().validate(text, pos)


# ── Safe file writes ──────────────────────────────────────────────────────────
# Spreadsheets and settings are written to a temporary file in the same folder
# and then swapped in with os.replace, which is atomic on one volume: a crash, a
# full disk or a LaCie dropout mid-write leaves the previous file intact rather
# than a truncated one. (Windows: the swap fails if Excel has the file open,
# exactly as writing it in place did.)

def _tmp_path(path):
    """`run_summary.xlsx` -> `run_summary.saving.xlsx` (keeps the extension the
    writers infer the format from)."""
    root, ext = os.path.splitext(path)
    return f"{root}.saving{ext}"


def _commit_tmp(tmp, path):
    try:
        os.replace(tmp, path)
    except Exception:
        try: os.remove(tmp)
        except OSError: pass
        raise


def _replace_atomically(path, write):
    """Call write(tmp_path), then swap the result in over `path`."""
    tmp = _tmp_path(path)
    try:
        write(tmp)
    except Exception:
        try: os.remove(tmp)
        except OSError: pass
        raise
    _commit_tmp(tmp, path)


def migrate_master_mean_diameter(ws) -> bool:
    """Insert 'Mean Diameter (um)' between 'D32 (um)' and 'Atomised (%)' in a
    master_log sheet still in the 17-column layout, moving every image from that
    column rightwards one column with it (insert_cols moves cell values, never
    images). Returns True if it changed the sheet; once the column is in, K reads
    'Mean Diameter (um)' and this cannot fire twice. Module-level so a one-off
    back-fill of an existing log uses exactly the GUI's migration."""
    from openpyxl.utils import get_column_letter, column_index_from_string
    if not (ws.cell(row=1, column=10).value == 'D32 (um)'
            and ws.cell(row=1, column=11).value == 'Atomised (%)'):
        return False
    ws.insert_cols(11)
    ws.cell(row=1, column=11).value = 'Mean Diameter (um)'
    for _img in ws._images:
        _anc = _img.anchor
        if isinstance(_anc, str):
            _m = re.match(r'^([A-Z]+)(\d+)$', _anc)
            if _m and column_index_from_string(_m.group(1)) >= 11:
                _new_col = get_column_letter(column_index_from_string(_m.group(1)) + 1)
                _img.anchor = f'{_new_col}{_m.group(2)}'
        elif hasattr(_anc, '_from'):
            if _anc._from.col >= 10:   # 0-indexed: 10 == Excel col K
                _anc._from.col += 1
            if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 10:
                _anc.to.col += 1
    return True


def migrate_master_orifice_length(ws) -> bool:
    """Insert 'Orifice Length (mm)' after 'Orifice' in a master_log sheet in the 18-column layout
    (B = Orifice, C = Bubbler Height), moving every image from column C rightwards one column with it.
    Returns True if it changed the sheet; once the column is in, C reads 'Orifice Length (mm)' and this
    cannot fire twice. Runs after migrate_master_mean_diameter, which keys on the layout before it."""
    from openpyxl.utils import get_column_letter, column_index_from_string
    if not (ws.cell(row=1, column=2).value == 'Orifice'
            and ws.cell(row=1, column=3).value == 'Bubbler Height (mm)'):
        return False
    ws.insert_cols(3)
    ws.cell(row=1, column=3).value = 'Orifice Length (mm)'
    for _img in ws._images:
        _anc = _img.anchor
        if isinstance(_anc, str):
            _m = re.match(r'^([A-Z]+)(\d+)$', _anc)
            if _m and column_index_from_string(_m.group(1)) >= 3:
                _new_col = get_column_letter(column_index_from_string(_m.group(1)) + 1)
                _img.anchor = f'{_new_col}{_m.group(2)}'
        elif hasattr(_anc, '_from'):
            if _anc._from.col >= 2:    # 0-indexed: 2 == Excel col C
                _anc._from.col += 1
            if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 2:
                _anc.to.col += 1
    return True


MASTER_RATE_BAND_UM = (20.0, 60.0)   # master_log's droplets/s column: the band kept after filtering (Ben, 2026-10-13)
MASTER_RATE_HEADER = f"Droplets/s ({MASTER_RATE_BAND_UM[0]:g}-{MASTER_RATE_BAND_UM[1]:g} um)"


def droplet_rate_band(results: dict, speed_steps_s, band=MASTER_RATE_BAND_UM):
    """In-band droplets produced per second, by mass balance, exactly as the analysis app's
    run_metrics.mass_balance_rate: syringe flow x atomised fraction BY VOLUME (liquid stage >= 2.3.0)
    / (pi/6 <d^3>) over the run's in-focus droplets, x the in-focus share with lo <= d < hi. The
    per-second comes from the syringe, not the camera, so the recording length does not enter. ''
    when anything is missing (no AI results, an older liquid stage, speed 0)."""
    import csv as _csv
    import math as _math
    try:
        sps = float(speed_steps_s)
        cls = results.get('_classical') or {}
        vol_pct = float(cls['atomised_vol_pct_pooled'])
        try:                                   # pooled from the per-frame volumes, as the app does (the
            with open(os.path.join(cls['_liquid_dir'], 'classical_per_frame.csv'), newline='',
                      encoding='utf-8') as fh:            # summary rounds to 3 dp)
                rows = list(_csv.DictReader(fh))
            tot = sum(float(r['total_liquid_vol_mm3']) for r in rows)
            if tot > 0:
                vol_pct = 100.0 * sum(float(r['droplet_vol_mm3']) for r in rows) / tot
        except (KeyError, TypeError, ValueError, OSError):
            pass
        sizes = os.path.join(results['_measurement_dir'], 'droplet_sizes.csv')
        with open(sizes, newline='', encoding='utf-8') as fh:
            d = np.array([float(r['diameter_um']) for r in _csv.DictReader(fh) if r.get('in_focus') == '1'])
    except (KeyError, TypeError, ValueError, OSError):
        return ''
    if sps <= 0 or d.size == 0:
        return ''
    q_mm3_s = _math.pi * (20.27 / 2) ** 2 * (sps / 6800)          # the GUI's syringe (GLR uses the same)
    v_mean_mm3 = _math.pi / 6 * float((d ** 3).mean()) * 1e-9
    share = float(((d >= band[0]) & (d < band[1])).mean())
    return int(round(q_mm3_s * vol_pct / 100 / v_mean_mm3 * share))


def migrate_master_droplet_rate(ws) -> bool:
    """Insert the droplets/s column after 'Atomised (%)' in a master_log sheet in the 19-column layout
    (M = Atomised, N = Avg Lamella Thickness), moving every image from column N rightwards with it.
    Returns True if it changed the sheet; cannot fire twice. Runs after migrate_master_orifice_length."""
    from openpyxl.utils import get_column_letter, column_index_from_string
    if not (ws.cell(row=1, column=13).value == 'Atomised (%)'
            and ws.cell(row=1, column=14).value == 'Avg Lamella Thickness'):
        return False
    ws.insert_cols(14)
    ws.cell(row=1, column=14).value = MASTER_RATE_HEADER
    for _img in ws._images:
        _anc = _img.anchor
        if isinstance(_anc, str):
            _m = re.match(r'^([A-Z]+)(\d+)$', _anc)
            if _m and column_index_from_string(_m.group(1)) >= 14:
                _new_col = get_column_letter(column_index_from_string(_m.group(1)) + 1)
                _img.anchor = f'{_new_col}{_m.group(2)}'
        elif hasattr(_anc, '_from'):
            if _anc._from.col >= 13:   # 0-indexed: 13 == Excel col N
                _anc._from.col += 1
            if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 13:
                _anc.to.col += 1
    return True


# ── Main application window ───────────────────────────────────────────────────

def as_number(text):
    """A typed value as a NUMBER for the spreadsheets ('4000' -> 4000, '36.5' -> 36.5), so Excel can sort,
    filter and plot it: a number written as text does neither (Ben, 2026-10-13: every speed and travel
    in master_log was text). Anything that is not a plain number comes back unchanged ('', '1.2mm',
    'NOT RECORDED')."""
    if text is None or isinstance(text, bool) or isinstance(text, (int, float)):
        return text
    try:
        f = float(str(text).strip())
    except ValueError:
        return text
    if f != f or f in (float("inf"), float("-inf")):
        return text
    return int(f) if f.is_integer() else f


def auto_trigger_plan(distance_mm, speed_sps, pre_s, post_s, *, steps_per_mm=6800,
                      motor_delay_s=0.5, buffer_s=2.0, arm_lead_s=1.0):
    """When to fire the camera so its recording covers the END of a Start Experiment run.

    All times are seconds after Start is clicked. The traverse starts motor_delay_s
    after Start (_start_experiment sends the motor command 500 ms later) and runs
    distance_mm * steps_per_mm / speed_sps seconds. The camera saves pre_s before
    the trigger and post_s after it, so firing at
        motor end - buffer_s - post_s
    makes the saved window end buffer_s before the traverse stops (the buffer
    covers the motor's ramp and timing slack). E.g. a 25 s test with a 13 s
    window fires with 15 s left.

    fits is False when the test is too short for the window: the window would
    start before the traverse does, or the trigger would come before the camera
    has had arm_lead_s to start buffering.
    """
    test_s = float(distance_mm) * steps_per_mm / float(speed_sps)
    end_s = motor_delay_s + test_s
    trigger_s = end_s - buffer_s - float(post_s)
    start_s = trigger_s - float(pre_s)
    fits = start_s >= motor_delay_s and trigger_s >= arm_lead_s
    return {"test_s": test_s, "end_s": end_s, "trigger_s": trigger_s,
            "window_s": (start_s, trigger_s + float(post_s)), "fits": fits}


class AtomisationApp(QMainWindow):

    MAX_MOTOR_MM = 72.5   # physical travel limit

    # Alicat MFC lives on the FTDI RS232 adapter, which enumerates as COM4 on
    # this rig.  Used when camera_settings.json has no saved port yet.
    ALICAT_DEFAULT_PORT = "COM4"

    # Must match STALL_SG_THRESHOLD in RAMP_RPM_Motor_Control.ino — the SG
    # readout goes red at the exact point the firmware itself stops the motor.
    # If that constant is retuned on the Arduino, update this to match.
    RPM_STALL_SG_THRESHOLD = 20

    # Cross-thread signals for pipeline callbacks
    _pipeline_done = Signal(object)
    _pipeline_err  = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Atomisation Control Panel")

        # Install thread-local stdout/stderr router so pipeline and cone threads
        # can route their prints to the GUI log independently without fighting
        # over the global sys.stdout.
        self._tl_stdout = _ThreadLocalStream(sys.stdout)
        self._tl_stderr = _ThreadLocalStream(sys.stderr)
        sys.stdout = self._tl_stdout
        sys.stderr = self._tl_stderr

        # ── State ─────────────────────────────────────────────────────────────
        self.arduino: ArduinoController | None = None
        self.arduino_connected = False
        self.serial_reading_active = False

        self.rpm_arduino: RpmController | None = None
        self.rpm_connected = False
        self.rpm_spinning = False
        self._last_actual_rpm = 0.0
        self._motor_stalled = False   # latched by a firmware stall; cleared on next Spin
        self._rpm_serial_active = False

        self.alicat: AlicatMFC | None = None
        self.alicat_connected = False
        self._alicat_serial_active = False
        self._alicat_thread: threading.Thread | None = None
        self._last_flow: float | None = None
        self._alicat_saved_port: str = self.ALICAT_DEFAULT_PORT

        self.phantom = PhantomController() if PHANTOM_SDK_AVAILABLE else None
        self.afg     = AFGController()     if PYVISA_AVAILABLE       else None

        self.camera_available = platform.system() == "Windows" and PHANTOM_SDK_AVAILABLE
        # True from a trigger until its save has finished or failed.  Arm,
        # Disarm, Apply Config and auto-arm on Start all overwrite or clear the
        # camera's RAM, so they are refused while it is set.
        self._cam_saving = False

        self.cumulative_distance = 0.0
        self._pre_move_cumulative  = 0.0   # cumulative_distance before the current motor move
        self._pending_move_distance = 0.0  # distance of the move in progress
        self._jogging = False
        self._experiment_saved = True   # True until an experiment runs unsaved
        self._run_folder = None          # Set eagerly on Start Experiment, cleared on next start
        self._run_started_at = None      # datetime of that start; the spreadsheets stamp THIS
        self._last_ai_results = None     # measure_run summary for the CURRENT run only
        self._cam_pre_frames  = 0        # computed from pre-trigger seconds × fps at Apply Config
        self._cam_post_frames = 0        # computed from post-trigger seconds × fps at Apply Config

        # Pressure and mass flow both arrive in the same Alicat frame, so they
        # share one timestamp series.
        self.pressure_data = {
            'live_buffer':     {'timestamps': [], 'pressures': [], 'flows': []},
            'experiment_data': {'timestamps': [], 'pressures': [], 'flows': []},
            'experiment_active': False,
            'experiment_start_time': None,
        }
        self.pressure_data['live_buffer_start_time'] = time.time()
        self._last_experiment_snapshot = {'timestamps': [], 'pressures': [], 'flows': []}
        self._last_cone_path = None   # path of most recent cone image (raw or annotated)
        self._cone_history: deque = deque(maxlen=5)  # (annotated_path, angle) tuples, newest last

        # Lamella analysis state (populated by _load_camera_settings; used by Phase 1 GUI)
        self._lamella_crop_cfg:   dict = {"x": 860, "y": 829, "w": 307, "h": 583}
        self._lamella_model_path: str  = ""
        self._lamella_arch:       str  = "tiny"
        self._lamella_on:         bool = False   # mirrors checkbox — True when user enables
        self._lamella_seg        = None          # StubSegmenter or LamellaSegmenter instance
        self._lamella_busy:       bool = False   # True while inference thread is running
        self._lamella_pending_frame             = None  # latest-frame slot (replaced, never queued)
        self._lamella_result                    = None  # most recent Result — used by _live_feed_update for overlay
        self._last_tiff_dir:      str | None = None  # TIFF folder from last camera trigger (for master_log)

        # EMA smoothing state (α=0.3: strong noise rejection, <2.5s lag on step changes)
        # One toggle drives both the pressure and mass flow traces.
        self._smooth_enabled = True
        self._EMA_ALPHA = 0.3
        self._pressure_ema = None   # reset when new readings arrive after a gap
        self._flow_ema     = None

        # Pressure cut-off: None = off. Latched once tripped so it fires once per
        # excursion; re-arms when the raw reading falls back below 90% of it.
        self._cutoff_bar     = None
        self._cutoff_tripped = False
        # Gas ramp, sccm per second: None = setpoints jump straight to the target.
        self._flow_ramp = None
        # How the current run ended early, if it did (None = ran to completion).
        # Recorded in run_summary ("Run status") and prefixed to the master_log
        # Notes. _move_stopped_early / _last_move_pct give the travel actually
        # covered, so the travel counter is not credited the full distance.
        self._run_stop_reason    = None
        self._move_stopped_early = False
        self._last_move_pct      = 0
        self._front_limit_steps  = None
        # The run's conditions as they were at Start (see _snapshot_run_conditions)
        self._run_conditions     = None
        # True from Jog press to release, independent of the board's replies
        self._jog_held           = False
        # Alicat health: time of the last frame (monotonic) and a latched alarm
        self._alicat_last_frame_t = None
        self._alicat_stale        = False
        # Live gas regime (_update_gas_regime): when the flow first fell short, and the regime logged
        self._gas_short_since     = None
        self._gas_short_flagged   = None

        # Guard flag — set while the save-format checkboxes are being corrected
        # programmatically so the toggled handler doesn't recurse.
        self._save_fmt_guard = False

        self._cone_cap  = None  # cv2.VideoCapture instance — must exist before _build_ui wires signals
        self._log_queue = queue.Queue()  # thread-safe sink for pipeline/cone stdout → GUI log panel

        # ── Build UI ──────────────────────────────────────────────────────────
        self._last_saved_run_folder: str | None = None
        self._build_ui()
        self._load_camera_settings()
        # Space = camera trigger (see _SpaceTriggerFilter)
        self._space_filter = _SpaceTriggerFilter(self)
        QApplication.instance().installEventFilter(self._space_filter)
        # Bring the MFC up on its own — the rig always has one, and every run
        # needs the flow and pressure trace it provides.
        QTimer.singleShot(800, self, self._auto_connect_alicat)
        QTimer.singleShot(0, self, self._poll_lacie)
        QTimer.singleShot(0, self, self._update_next_save_preview)

        # Pipeline cross-thread signal connections (UI must exist first)
        self._pipeline_done.connect(self._on_pipeline_complete)
        self._pipeline_err.connect(self._on_pipeline_error)

        # ── Timers ────────────────────────────────────────────────────────────
        self._graph_timer = QTimer(self)
        self._graph_timer.timeout.connect(self._update_graphs)
        self._graph_timer.start(500)

        self._cone_feed_timer = QTimer(self)
        self._cone_feed_timer.timeout.connect(self._cone_update_feed)
        # started/stopped by Start Camera / Stop Camera buttons

        self._cone_auto_timer = QTimer(self)
        self._cone_auto_timer.setSingleShot(True)
        self._cone_auto_timer.timeout.connect(self._cone_capture)
        # started (single-shot, 5 s) in _start_experiment(); stop() cancels if not yet fired

        self._live_feed_timer = QTimer(self)
        self._live_feed_timer.setInterval(100)   # ~10 fps
        self._live_feed_timer.timeout.connect(self._live_feed_tick)
        self._live_feed_pending = False          # throttle: only one grab in-flight at a time

        # Experiment watchdog — fires if MOVEMENT_COMPLETE is never received (P4-C3)
        # NOTE: this timer is started in _start_experiment and stopped in _on_movement_complete.
        # If it fires it means the serial reader died mid-experiment — pressure will stay on
        # indefinitely without this safety net.
        self._experiment_watchdog = QTimer(self)
        self._experiment_watchdog.setSingleShot(True)
        self._experiment_watchdog.timeout.connect(self._on_experiment_timeout)

        # Auto-trigger at the end of a test (Camera tab tickbox): one shot to fire,
        # one 1 s tick for the countdown shown under the camera buttons.
        self._auto_trig_timer = QTimer(self)
        self._auto_trig_timer.setSingleShot(True)
        self._auto_trig_timer.timeout.connect(self._auto_trigger_fire)
        self._auto_trig_tick = QTimer(self)
        self._auto_trig_tick.setInterval(1000)
        self._auto_trig_tick.timeout.connect(self._auto_trigger_countdown)
        self._auto_trig_due = None

        self._run_elapsed_timer = QTimer(self)
        self._run_elapsed_timer.setInterval(1000)
        self._run_elapsed_timer.timeout.connect(self._tick_run_timer)
        self._run_start_time: float | None = None

        self._lacie_poll_timer = QTimer(self)
        self._lacie_poll_timer.setInterval(5000)
        self._lacie_poll_timer.timeout.connect(self._poll_lacie)
        self._lacie_poll_timer.start()

        # Ends a run after STOP EVERYTHING when no MOVEMENT_COMPLETE follows
        self._stop_fallback_timer = QTimer(self)
        self._stop_fallback_timer.setSingleShot(True)
        self._stop_fallback_timer.timeout.connect(self._end_run_after_stop)

        # Alicat health check (see _check_alicat_alive)
        self._alicat_health_timer = QTimer(self)
        self._alicat_health_timer.setInterval(500)
        self._alicat_health_timer.timeout.connect(self._check_alicat_alive)
        self._alicat_health_timer.start()

        # Log panel queue drain — flushes pipeline/cone stdout into the right-panel log widget
        self._log_poll_timer = QTimer(self)
        self._log_poll_timer.timeout.connect(self._flush_log_queue)
        self._log_poll_timer.start(100)

        # Auto-connect the Portenta.  Gated on actually identifying one rather
        # than taking the first port in the list: the enumeration order is not
        # stable across reboots or COM-port reassignment, and the first entry
        # is just as likely to be the Alicat's FTDI adapter — connecting to
        # that would seize the MFC's port and leave the traverse unconnected.
        if self._portenta_port_present():
            self._trigger_arduino_connect()

        # Auto-connect the RPM Arduino.  Gated on actually identifying an Uno
        # rather than just taking the first port: with the Uno unplugged the
        # top entry would be the Portenta, and connecting would seize the
        # traverse controller's port as an RPM controller.  Staggered so the
        # two connect workers don't start in the same instant.
        if self._uno_port_present():
            QTimer.singleShot(400, self, self._trigger_rpm_connect)

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setMinimumSize(1200, 700)
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header
        root_layout.addWidget(self._build_header())

        # Body (left panel + tabs)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(16, 12, 16, 12)
        body_layout.setSpacing(16)
        body_layout.addWidget(self._build_left_panel(),   stretch=0)
        body_layout.addWidget(self._build_tabs(),          stretch=1)
        body_layout.addWidget(self._build_right_panel(),   stretch=0)
        root_layout.addWidget(body, stretch=1)

        # Status / action bar
        root_layout.addWidget(self._build_status_bar())

    # ── Header ───────────────────────────────────────────────────────────────

    def _build_header(self):
        header = QFrame()
        header.setFixedHeight(52)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {CLR_PANEL};
                border-bottom: 1px solid {CLR_BORDER};
            }}
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(16)

        app_title = QLabel("ATOMISATION CONTROL")
        app_title.setStyleSheet(f"color: {CLR_TEXT}; font-size: 15px; font-weight: 700; letter-spacing: 1px;")
        hl.addWidget(app_title)

        self._hdr_lacie_dot = dot_indicator(CLR_RED)
        self._hdr_lacie_lbl = QLabel("LaCie")
        self._hdr_lacie_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        hl.addWidget(self._hdr_lacie_dot)
        hl.addWidget(self._hdr_lacie_lbl)

        hl.addStretch()

        # Last save path — "No Current Runs" until first save; becomes clickable afterwards
        self._hdr_last_save_lbl = ClickableLabel("No Current Runs")
        self._hdr_last_save_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        self._hdr_last_save_lbl.clicked.connect(self._open_last_save_folder)
        hl.addWidget(self._hdr_last_save_lbl)

        _sep_paths = QLabel("|")
        _sep_paths.setStyleSheet(f"color: {CLR_BORDER}; font-size: 12px;")
        hl.addWidget(_sep_paths)

        # Next save path — live preview built from current parameter state
        self._hdr_next_save_lbl = QLabel("…")
        self._hdr_next_save_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        hl.addWidget(self._hdr_next_save_lbl)

        hl.addStretch()

        _sep_after_paths = QFrame(); _sep_after_paths.setFixedWidth(1); _sep_after_paths.setFixedHeight(18)
        _sep_after_paths.setStyleSheet(f"background: {CLR_BORDER};")
        hl.addWidget(_sep_after_paths)

        # Pixels/mm display (updated by calibration; persists via settings)
        self._hdr_pxmm_lbl = QLabel("– px/mm")
        self._hdr_pxmm_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        hl.addWidget(self._hdr_pxmm_lbl)
        _sep = QFrame(); _sep.setFixedWidth(1); _sep.setFixedHeight(18)
        _sep.setStyleSheet(f"background: {CLR_BORDER};")
        hl.addWidget(_sep)

        # Status dots — order: Arduino · Camera · AFG · BAR
        self._hdr_arduino_dot  = dot_indicator(CLR_TEXT_SEC)
        self._hdr_arduino_lbl  = QLabel("Portenta")
        self._hdr_camera_dot   = dot_indicator(CLR_TEXT_SEC)
        self._hdr_camera_lbl   = QLabel("Camera")
        self._hdr_afg_dot      = dot_indicator(CLR_RED)
        self._hdr_afg_lbl      = QLabel("AFG")
        self._hdr_pressure_dot = dot_indicator(CLR_TEXT_SEC)
        self._hdr_pressure_lbl = QLabel("– barA")
        self._hdr_mfc_dot      = dot_indicator(CLR_TEXT_SEC)
        self._hdr_mfc_lbl      = QLabel("MFC")

        # Arduino, AFG, BAR, MFC — plain dot + label
        for dot, lbl in [
            (self._hdr_arduino_dot,  self._hdr_arduino_lbl),
            (self._hdr_afg_dot,      self._hdr_afg_lbl),
            (self._hdr_pressure_dot, self._hdr_pressure_lbl),
            (self._hdr_mfc_dot,      self._hdr_mfc_lbl),
        ]:
            lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")

        # Camera — dot + label wrapped in a box frame (lights up green when armed)
        self._hdr_camera_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        self._hdr_camera_box = QFrame()
        self._hdr_camera_box.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
            }}
        """)
        _cam_box_hl = QHBoxLayout(self._hdr_camera_box)
        _cam_box_hl.setContentsMargins(5, 2, 5, 2)
        _cam_box_hl.setSpacing(4)
        _cam_box_hl.addWidget(self._hdr_camera_dot)
        _cam_box_hl.addWidget(self._hdr_camera_lbl)

        # Add all indicators in order: Arduino · Camera · AFG · BAR
        hl.addWidget(self._hdr_arduino_dot)
        hl.addWidget(self._hdr_arduino_lbl)
        _sp = QFrame(); _sp.setFixedWidth(10); _sp.setStyleSheet("background: transparent;")
        hl.addWidget(_sp)

        hl.addWidget(self._hdr_camera_box)
        _sp2 = QFrame(); _sp2.setFixedWidth(10); _sp2.setStyleSheet("background: transparent;")
        hl.addWidget(_sp2)

        hl.addWidget(self._hdr_afg_dot)
        hl.addWidget(self._hdr_afg_lbl)
        _sp3 = QFrame(); _sp3.setFixedWidth(10); _sp3.setStyleSheet("background: transparent;")
        hl.addWidget(_sp3)

        hl.addWidget(self._hdr_pressure_dot)
        hl.addWidget(self._hdr_pressure_lbl)
        _sp_mfc = QFrame(); _sp_mfc.setFixedWidth(10); _sp_mfc.setStyleSheet("background: transparent;")
        hl.addWidget(_sp_mfc)
        hl.addWidget(self._hdr_mfc_dot)
        hl.addWidget(self._hdr_mfc_lbl)

        _sep2 = QFrame(); _sep2.setFixedWidth(1); _sep2.setFixedHeight(18)
        _sep2.setStyleSheet(f"background: {CLR_BORDER};")
        hl.addWidget(_sep2)

        self._hdr_timer_lbl = QLabel("00:00")
        self._hdr_timer_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 12px; font-weight: 700;")
        hl.addWidget(self._hdr_timer_lbl)

        return header

    # ── Left panel ────────────────────────────────────────────────────────────

    def _build_left_panel(self):
        scroll = QScrollArea()
        scroll.setFixedWidth(440)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        panel = QFrame()
        panel.setStyleSheet("background: transparent;")
        panel.setMinimumWidth(0)
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(12)

        # ── Live camera view card ─────────────────────────────────────────────
        # Pinned to the height the old Latest Result card rendered at (404 px)
        # so the graphs below do not move. The image takes whatever the title
        # and button rows leave, and its size policy is Ignored so a frame's
        # pixmap can never push the card taller.
        self._live_card = card()
        self._live_card.setFixedHeight(404)
        self._live_card.layout().setSpacing(8)

        top_row = QWidget()
        tr = QHBoxLayout(top_row)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.addWidget(title_label("Live Camera View", 13))
        tr.addStretch()
        # Mirrors the Camera tab's status line, so Connect/Ping report back
        # here without switching tabs.
        self._live_status_lbl = QLabel("Camera: idle")
        self._live_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        tr.addWidget(self._live_status_lbl)
        self._live_card.layout().addWidget(top_row)

        self._live_view_label = QLabel()
        self._live_view_label.setMinimumSize(1, 1)
        self._live_view_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                            QSizePolicy.Policy.Ignored)
        self._live_view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._live_view_label.setStyleSheet(f"""
            background-color: {CLR_INPUT};
            border-radius: 8px;
            color: {CLR_TEXT_SEC};
            font-size: 12px;
        """)
        self._live_view_label.setText("Live feed not active")
        self._live_card.layout().addWidget(self._live_view_label, stretch=1)

        live_btn_row = QWidget()
        lbr = QHBoxLayout(live_btn_row); lbr.setContentsMargins(0, 0, 0, 0); lbr.setSpacing(8)
        self._live_connect_btn = accent_button("Connect", CLR_ACCENT)
        self._live_connect_btn.setToolTip(self._cam_connect_tooltip())
        self._live_connect_btn.clicked.connect(self._cam_connect)
        self._live_ping_btn = ghost_button("Ping")
        self._live_ping_btn.setToolTip(self._cam_ping_tooltip())
        self._live_ping_btn.clicked.connect(self._cam_ping)
        self._live_feed_btn = accent_button("▶ Live Feed", CLR_GREEN)
        self._live_feed_btn.setToolTip(
            "<b>Start / stop live feed</b><br>"
            "Same feed as the Calibration tab — starting or stopping it here "
            "starts or stops it there too.<br>"
            "Connect the camera first.")
        self._live_feed_btn.clicked.connect(self._toggle_live_feed)
        for b in (self._live_connect_btn, self._live_ping_btn, self._live_feed_btn):
            b.setFixedHeight(36)
            lbr.addWidget(b, stretch=1)
        if not self.camera_available:
            for b in (self._live_connect_btn, self._live_ping_btn, self._live_feed_btn):
                b.setEnabled(False)
            self._live_view_label.setText(
                "Live feed requires Windows + Phantom SDK")
        self._live_card.layout().addWidget(live_btn_row)

        vl.addWidget(self._live_card)

        # ── Live graph cards (mass flow above pressure) ───────────────────────
        # Both traces come from the Alicat MFC and share the Smooth toggle.
        GRAPH_H = 108      # 0.6 × the original 180 px so both fit without scrolling

        def _live_plot(ylabel, units, colour):
            """Build a styled PlotWidget and return (widget, curve)."""
            pw = pg.PlotWidget()
            pw.setFixedHeight(GRAPH_H)
            pw.setBackground('#2c2c2e')
            pi = pw.getPlotItem()
            pi.setLabel('left', ylabel, units=units,
                        color='#8e8e93', **{'font-size': '9pt'})
            pi.setLabel('bottom', 'Time', units='s',
                        color='#8e8e93', **{'font-size': '9pt'})
            pi.getAxis('left').setTextPen(pg.mkPen('#8e8e93'))
            pi.getAxis('bottom').setTextPen(pg.mkPen('#8e8e93'))
            pi.getAxis('left').setPen(pg.mkPen('#3a3a3c'))
            pi.getAxis('bottom').setPen(pg.mkPen('#3a3a3c'))
            pi.showGrid(x=True, y=True, alpha=0.15)
            pi.setMouseEnabled(x=False, y=False)
            pi.hideButtons()
            return pw, pi.plot(pen=pg.mkPen(color=colour, width=2.5))

        # Mass flow card — carries the shared Smooth checkbox
        flow_card = card()
        flow_card.layout().setSpacing(6)

        flow_hdr = QWidget()
        flow_hdr_l = QHBoxLayout(flow_hdr)
        flow_hdr_l.setContentsMargins(0, 0, 0, 0)
        flow_hdr_l.setSpacing(8)
        flow_hdr_l.addWidget(title_label("Mass Flow (live)", 13))
        flow_hdr_l.addStretch()
        self._smooth_cb = QCheckBox("Smooth")
        self._smooth_cb.setChecked(True)
        self._smooth_cb.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        self._smooth_cb.setToolTip(
            "<b>EMA smoothing (α=0.3)</b><br>"
            "Exponential moving average — reduces measurement noise without the "
            "step-change lag of a simple rolling average.<br>"
            "Applies to both the mass flow and pressure traces.<br>"
            "Raw values are always stored for export regardless of this setting.")
        self._smooth_cb.toggled.connect(self._on_smooth_toggled)
        flow_hdr_l.addWidget(self._smooth_cb)
        flow_card.layout().addWidget(flow_hdr)

        self._flow_graph_widget, self._flow_curve = _live_plot(
            'Mass Flow', 'sccm', CLR_GREEN)
        flow_card.layout().addWidget(self._flow_graph_widget)
        vl.addWidget(flow_card)

        # Pressure card
        graph_card = card()
        graph_card.layout().setSpacing(6)
        graph_card.layout().addWidget(title_label("Pressure (live)", 13))

        self._graph_widget, self._pressure_curve = _live_plot(
            'Pressure', 'barA', CLR_ACCENT)
        graph_card.layout().addWidget(self._graph_widget)
        vl.addWidget(graph_card)

        # Motor travel and Volume now live in the status bar, left of START —
        # see _build_status_bar().

        # ── Emergency off (always visible) ────────────────────────────────────
        pressure_off_card = card(padding=10)
        pressure_off_card.layout().setSpacing(6)
        pressure_off_card.layout().addWidget(title_label("Emergency", 13))

        self._pressure_off_btn_left = accent_button("STOP EVERYTHING", CLR_RED)
        self._pressure_off_btn_left.setFixedHeight(40)
        self._pressure_off_btn_left.setToolTip(
            "<b>Emergency stop</b><br>"
            "Stops every connected device, independently:<br>"
            "1. Halts the traverse motor (Portenta)<br>"
            "2. Stops the spin motor (Arduino Uno)<br>"
            "3. Zeroes the AliCat flow setpoint<br>"
            "<i>Re-home the traverse motor afterwards — the travel counter "
            "credits the full commanded distance on an aborted move.</i>")
        self._pressure_off_btn_left.clicked.connect(lambda: self._pressure_off())
        pressure_off_card.layout().addWidget(self._pressure_off_btn_left)

        vl.addWidget(pressure_off_card)
        vl.addStretch()

        scroll.setWidget(panel)
        return scroll

    # ── Right panel (permanent experiment info) ───────────────────────────────

    def _build_right_panel(self):
        panel = QFrame()
        panel.setFixedWidth(260)
        panel.setMinimumWidth(0)
        panel.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(12)

        # ── Nozzle card ───────────────────────────────────────────────────────
        nozzle_card = card()
        nozzle_card.layout().addWidget(section_label("NOZZLE"))
        nozzle_card.layout().addWidget(separator())

        self._orifice_combo = QComboBox()
        self._orifice_combo.addItems(["0.2mm","0.3mm","0.5mm","0.8mm","1mm","1.2mm","1.4mm","1.6mm","1.8mm","2mm"])
        self._orifice_combo.currentTextChanged.connect(self._save_camera_settings)
        nozzle_card.layout().addWidget(input_row("Orifice", self._orifice_combo, label_width=100))

        # Hardware state like the bubbler height: it stays until the insert is changed.
        self._orifice_len_entry = QLineEdit()
        self._orifice_len_entry.setPlaceholderText("mm")
        self._orifice_len_entry.setValidator(QDoubleValidator(0.0, 100.0, 2))
        self._orifice_len_entry.setToolTip(
            "<b>Orifice length (mm)</b><br>"
            "Length of the exit orifice bore: the straight section of the insert. It changes "
            "how the two-phase flow discharges (L/D), so update it whenever an insert with a "
            "different length goes in.<br><br>"
            "Recorded in run_summary.xlsx and master_log; the analysis app reports L/D and "
            "warns if runs in one analysis have different lengths.")
        self._orifice_len_entry.editingFinished.connect(self._save_camera_settings)
        nozzle_card.layout().addWidget(
            input_row("Orifice length", self._orifice_len_entry, label_width=100))

        # Hardware state, not a per-run setting: it persists between runs and is
        # only correct if you update it after physically moving the bubbler.
        self._bubbler_height_entry = QLineEdit()
        self._bubbler_height_entry.setPlaceholderText("mm")
        self._bubbler_height_entry.setValidator(QDoubleValidator(0.0, 1000.0, 1))
        self._bubbler_height_entry.setToolTip(
            "<b>Bubbler height (mm)</b><br>"
            "Distance from the bottom of the bubbler to the inside of the "
            "atomisation chamber. A smaller height means more shear thinning "
            "of the silicone.<br><br>"
            "This is a HARDWARE STATE and persists between runs — update it "
            "when you physically move the bubbler, not per run.<br><br>"
            "Not the same as Motor Travel, which is the plunger stroke.")
        self._bubbler_height_entry.editingFinished.connect(self._save_camera_settings)
        nozzle_card.layout().addWidget(
            input_row("Bubbler height", self._bubbler_height_entry, label_width=100))

        vl.addWidget(nozzle_card)

        # ── Notes card ────────────────────────────────────────────────────────
        notes_card = card()
        notes_card.layout().addWidget(section_label("NOTES"))
        notes_card.layout().addWidget(separator())

        self._notes_text = QTextEdit()
        self._notes_text.setPlaceholderText("Fluid composition, temperature, observations...")
        self._notes_text.setMinimumHeight(60)
        self._notes_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {CLR_INPUT};
                color: {CLR_TEXT};
                border: 1px solid #606064;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
            }}
            QTextEdit:focus {{ border: 1px solid {CLR_ACCENT}; }}
        """)
        notes_card.layout().addWidget(self._notes_text)

        save_row = QWidget()
        sr = QHBoxLayout(save_row); sr.setContentsMargins(0, 0, 0, 0); sr.setSpacing(8)
        self._save_path_lbl = QLabel(self._excel_save_path_hint())
        self._save_path_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px;")
        self._save_path_lbl.setWordWrap(True)
        save_btn = accent_button("Save to Excel", CLR_ACCENT)
        save_btn.setFixedHeight(36)
        save_btn.setToolTip(
            "<b>Save to Excel</b><br>"
            "1. Reads the run fields (orifice, bubbler height, RPM, notes, …)<br>"
            "2. Writes run_summary.xlsx in the run folder and a row in master_log.xlsx<br>"
            "3. Adds D32, atomised fraction and the lowest-D32 frame once the AI chain "
            "has finished<br>"
            "4. UPDATES this run's existing row rather than adding a second one<br><br>"
            "Runs automatically when an experiment ends and again when the AI chain "
            "completes — you only need this to save notes written afterwards.")
        save_btn.clicked.connect(self._save_to_excel)
        sr.addWidget(self._save_path_lbl, stretch=1)
        sr.addWidget(save_btn)
        notes_card.layout().addWidget(save_row)

        vl.addWidget(notes_card, stretch=2)

        # ── Console card ──────────────────────────────────────────────────────
        log_card = card(padding=10)
        log_hdr = QWidget()
        lh = QHBoxLayout(log_hdr); lh.setContentsMargins(0, 0, 0, 0)
        lh.addWidget(section_label("CONSOLE:"))
        lh.addStretch()
        _clear_btn = QPushButton("Clear")
        _clear_btn.setFixedHeight(20)
        _clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {CLR_TEXT_SEC};
                border: 1px solid {CLR_BORDER}; border-radius: 4px;
                font-size: 10px; padding: 0 6px;
            }}
            QPushButton:hover {{ color: {CLR_TEXT}; }}
        """)
        _clear_btn.clicked.connect(lambda: self._pipeline_log.clear())
        lh.addWidget(_clear_btn)
        log_card.layout().addWidget(log_hdr)
        log_card.layout().addWidget(separator())

        self._pipeline_log = QPlainTextEdit()
        self._pipeline_log.setReadOnly(True)
        self._pipeline_log.setFont(QFont("Menlo, Monaco, Courier New", 10))
        self._pipeline_log.setPlaceholderText(">")
        self._pipeline_log.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #1a1a1c;
                color: #30d158;
                border: 1px solid {CLR_BORDER};
                border-radius: 8px;
                padding: 6px;
                font-size: 10px;
            }}
            QScrollBar:vertical {{
                background: {CLR_PANEL}; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {CLR_BORDER}; border-radius: 3px; min-height: 20px;
            }}
        """)
        log_card.layout().addWidget(self._pipeline_log)
        self._pipeline_log_base_style = self._pipeline_log.styleSheet()
        vl.addWidget(log_card, stretch=1)

        return panel

    # ── Tab widget ────────────────────────────────────────────────────────────

    def _build_tabs(self):
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {CLR_PANEL};
                border: 1px solid {CLR_BORDER};
                border-radius: 12px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {CLR_TEXT_SEC};
                padding: 12px 24px;
                font-weight: 500;
                font-size: 13px;
                border: none;
                border-bottom: 2px solid transparent;
                margin-bottom: -1px;
            }}
            QTabBar::tab:selected {{
                color: {CLR_ACCENT};
                border-bottom: 2px solid {CLR_ACCENT};
            }}
            QTabBar::tab:hover:!selected {{ color: {CLR_TEXT}; }}
        """)
        self._tabs.addTab(self._build_hardware_tab(),     "  Hardware  ")
        self._tabs.addTab(self._build_materials_tab(),    "  Materials  ")
        self._tabs.addTab(self._build_camera_tab(),       "  Camera  ")
        self._tabs.addTab(self._build_afg_tab(),          "  AFG1062  ")
        self._tabs.addTab(self._build_calibration_tab(),  "  Calibration  ")
        self._tabs.addTab(self._build_cone_tab(),         "  Cone  ")
        self._tabs.addTab(self._build_extremes_tab(),     "  Extremes  ")
        self._tabs.addTab(self._build_how_to_tab(),       "")
        # Hide the How To tab itself — its content is reached via the corner
        # button below.  Indexed off the count so adding/removing a tab above
        # can't leave this pointing at the wrong one.
        self._tabs.setTabVisible(self._tabs.count() - 1, False)

        # "How To" corner button — styled as a tab, physically right-aligned
        _how_to_btn = QPushButton("  How To  ")
        _how_to_btn.setCheckable(True)
        _how_to_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {CLR_TEXT_SEC};
                border: none;
                border-bottom: 2px solid transparent;
                padding: 10px 22px;
                font-weight: 500;
                font-size: 13px;
            }}
            QPushButton:hover {{ color: {CLR_TEXT}; }}
            QPushButton:checked {{
                color: {CLR_ACCENT};
                border-bottom: 2px solid {CLR_ACCENT};
            }}
        """)
        # Index of the How To tab itself (always last), not a hard-coded number:
        # it was 6 / 5 after two tabs were added, opening Extremes and lighting
        # the button on Cone.
        _how_to_idx = self._tabs.count() - 1
        _how_to_btn.clicked.connect(
            lambda checked: self._tabs.setCurrentIndex(_how_to_idx if checked else 0)
        )
        self._tabs.currentChanged.connect(
            lambda idx: _how_to_btn.setChecked(idx == _how_to_idx)
        )
        self._tabs.setCornerWidget(_how_to_btn, Qt.Corner.TopRightCorner)
        return self._tabs

    # ── Hardware tab ─────────────────────────────────────────────────────────

    def _build_materials_tab(self):
        """Fluid and gas densities -- the only inputs the GLR needs that the rig
        does not already know.

        Everything else in the ratio is a set point the GUI already holds: gas
        flow in sccm, and liquid mL/min derived from motor speed through the
        bore area. These two are properties of WHAT is being pumped, so they
        live here rather than with the hardware.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        w = QWidget()
        w.setMinimumWidth(0)
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 20, 20, 20)
        vl.setSpacing(14)

        c = card(w)
        c.layout().addWidget(section_label("DENSITIES"))
        c.layout().addWidget(separator())

        self._rho_liquid_entry = QLineEdit()
        self._rho_liquid_entry.setPlaceholderText("e.g. 970  kg/m³")
        self._rho_liquid_entry.setValidator(QDoubleValidator(0.0, 100000.0, 4))
        self._rho_liquid_entry.setText(f"{self.DEFAULT_RHO_LIQUID:g}")

        self._rho_gas_entry = QLineEdit()
        self._rho_gas_entry.setPlaceholderText("e.g. 1.184  kg/m³")
        self._rho_gas_entry.setValidator(QDoubleValidator(0.0, 100000.0, 6))
        self._rho_gas_entry.setText(f"{self.DEFAULT_RHO_GAS:g}")

        # A density alone does not say WHAT was pumped. 970 kg/m3 is several
        # different silicones, and the viscosity that distinguishes them is not
        # in any number this GUI records. Free text, because the point is to
        # capture whatever identifies the material to the person who used it.
        self._fluid_tag_entry = QLineEdit()
        self._fluid_tag_entry.setPlaceholderText("e.g. 3000cP Silicone")

        self._gas_tag_entry = QLineEdit()
        self._gas_tag_entry.setPlaceholderText("e.g. Nitrogen gas")

        _fluid_wrap = QWidget()
        _fw = QVBoxLayout(_fluid_wrap)
        _fw.setContentsMargins(0, 0, 0, 0); _fw.setSpacing(6)
        _fw.addWidget(input_row("Density of fluid (kg/m³)", self._rho_liquid_entry))
        _fw.addWidget(input_row("Fluid", self._fluid_tag_entry))
        c.layout().addWidget(_fluid_wrap)

        _gas_wrap = QWidget()
        _gw = QVBoxLayout(_gas_wrap)
        _gw.setContentsMargins(0, 0, 0, 0); _gw.setSpacing(2)
        _gw.addWidget(input_row("Density of gas (kg/m³)", self._rho_gas_entry))
        # Not decoration: "sccm" means STANDARD cm³/min, and the standard state
        # is what the gas density has to be quoted at or the mass flow is wrong.
        # 25 °C is the Alicat default, which is the controller this rig uses.
        _gas_note = QLabel("At 25 °C and 1 atm")
        _gas_note.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 11px;")
        _gw.addWidget(_gas_note)
        _gw.addSpacing(4)
        _gw.addWidget(input_row("Gas", self._gas_tag_entry))
        c.layout().addWidget(_gas_wrap)
        vl.addWidget(c)

        c2 = card(w)
        c2.layout().addWidget(section_label("GAS-TO-LIQUID RATIO"))
        c2.layout().addWidget(separator())
        self._glr_detail_lbl = QLabel("GLR –")
        self._glr_detail_lbl.setStyleSheet(
            f"color: {CLR_ACCENT}; font-size: 22px; font-weight: 700;")
        c2.layout().addWidget(self._glr_detail_lbl)
        _expl = QLabel(
            "GLR = gas mass flow ÷ liquid mass flow, so it is dimensionless.\n"
            "    gas mass    = gas flow (sccm) × gas density\n"
            "    liquid mass = motor flow (mL/min) × fluid density")
        _expl.setWordWrap(True)
        _expl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        c2.layout().addWidget(_expl)

        # The same arithmetic with the CURRENT inputs substituted in. Monospaced
        # so the columns line up, and live, so a typo in a density is visible as
        # a wrong mass flow rather than only as a wrong ratio.
        self._glr_working_lbl = QLabel("")
        self._glr_working_lbl.setWordWrap(False)
        self._glr_working_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._glr_working_lbl.setStyleSheet(
            f"color: {CLR_TEXT}; font-size: 12px; "
            f"font-family: 'SF Mono', Menlo, Consolas, monospace; "
            f"background: {CLR_INPUT}; border-radius: 6px; padding: 10px;")
        c2.layout().addWidget(self._glr_working_lbl)

        _caveat = QLabel(
            "Both flows are COMMANDED set points, not measurements, so this is "
            "the run's mean GLR. It does not depend on when in the run a video "
            "was taken — but it also does not capture delivery steadiness, and "
            "the L9 found droplet-count variability rising with bubbler RPM.")
        _caveat.setWordWrap(True)
        _caveat.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        c2.layout().addWidget(_caveat)
        vl.addWidget(c2)

        vl.addStretch()
        for _e in (self._rho_liquid_entry, self._rho_gas_entry):
            _e.textChanged.connect(self._update_glr_label)
            _e.editingFinished.connect(self._save_camera_settings)
        for _e in (self._fluid_tag_entry, self._gas_tag_entry):
            _e.editingFinished.connect(self._save_camera_settings)
        scroll.setWidget(w)
        return scroll

    def _build_hardware_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        w = QWidget()
        w.setMinimumWidth(0)
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 20, 20, 20)
        vl.setSpacing(14)

        # ── Connections (Portenta · Arduino Uno · Alicat MFC) ─────────────────
        # All three share the same shape, so build them from one helper and lay
        # them out a third of the width each in a single row.
        COMBO_H = 56      # tall enough to read the port + description comfortably
        BTN_H   = 46      # sized so the card lands at 1.3x its previous height
        ICON_PX = 16      # refresh glyph, well inside the 56px square button

        def connection_card(title, on_refresh, on_connect, on_disconnect,
                            refresh_tip, connect_tip, disconnect_tip, prefer=None):
            cd = card(w, padding=20)
            cd.layout().setSpacing(12)
            cd.layout().addWidget(section_label(title))
            cd.layout().addWidget(separator())

            prow = QWidget()
            prow.setStyleSheet("background: transparent;")
            prl = QHBoxLayout(prow); prl.setContentsMargins(0,0,0,0); prl.setSpacing(6)
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems(self._get_serial_ports(prefer=prefer))
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.setMinimumWidth(0)          # must be free to shrink at 1/3 width
            combo.setFixedHeight(COMBO_H)
            combo.setStyleSheet("QComboBox { font-size: 14px; padding-left: 10px; }")
            # Icon-only button: ghost_button's 7px/16px padding would squeeze the
            # content rect to ~22px and clip the glyph, so restate the style with
            # zero padding rather than trying to override it.
            rfb = QPushButton("")
            rfb.setIcon(refresh_icon(size=ICON_PX))
            rfb.setIconSize(QSize(ICON_PX, ICON_PX))
            rfb.setFixedSize(COMBO_H, COMBO_H)   # square, matched to the dropdown
            rfb.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: 1px solid {CLR_ACCENT};
                    border-radius: 8px;
                    padding: 0px;
                }}
                QPushButton:hover {{ background-color: rgba(10,132,255,0.15); }}
                QPushButton:pressed {{ background-color: rgba(10,132,255,0.30); }}
            """)
            rfb.setToolTip(refresh_tip)
            rfb.clicked.connect(on_refresh)
            prl.addWidget(combo, 1); prl.addWidget(rfb)
            cd.layout().addWidget(prow)

            brow = QWidget()
            brow.setStyleSheet("background: transparent;")
            brl = QHBoxLayout(brow); brl.setContentsMargins(0,0,0,0); brl.setSpacing(6)
            cbtn = accent_button("Connect", CLR_ACCENT)
            dbtn = ghost_button("Disconnect")
            for b in (cbtn, dbtn):
                b.setFixedHeight(BTN_H)
                b.setMinimumWidth(0)
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            dbtn.setEnabled(False)
            cbtn.setToolTip(connect_tip); dbtn.setToolTip(disconnect_tip)
            cbtn.clicked.connect(on_connect); dbtn.clicked.connect(on_disconnect)
            brl.addWidget(cbtn); brl.addWidget(dbtn)
            cd.layout().addWidget(brow)

            # Status on its own line — there is no room beside the buttons here
            status = QLabel("Not connected")
            status.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
            cd.layout().addWidget(status)
            return cd, combo, cbtn, dbtn, status

        conn_row = QWidget()
        conn_row.setStyleSheet("background: transparent;")
        crl = QHBoxLayout(conn_row)
        crl.setContentsMargins(0, 0, 0, 0)
        crl.setSpacing(10)

        (c, self._port_combo, self._connect_btn,
         self._disconnect_btn, self._arduino_status_lbl) = connection_card(
            "PORTENTA", self._refresh_ports,
            self._trigger_arduino_connect, self._trigger_arduino_disconnect,
            "<b>Refresh serial ports</b><br>"
            "1. Re-scans all COM/USB serial ports on this computer<br>"
            "2. Updates the dropdown list with the new results",
            "<b>Connect to Arduino</b><br>"
            "1. Opens a serial connection on the selected port<br>"
            "2. Handshakes with the Portenta H7<br>"
            "3. Enables the motor controls",
            "<b>Disconnect Arduino</b><br>"
            "1. Sends a disconnect command to the Portenta<br>"
            "2. Closes the serial port and releases it",
            prefer=self._is_portenta_port)

        (cu, self._rpm_port_combo, self._rpm_connect_btn,
         self._rpm_disconnect_btn, self._rpm_status_lbl) = connection_card(
            "ARDUINO UNO", self._refresh_rpm_ports,
            self._trigger_rpm_connect, self._trigger_rpm_disconnect,
            "<b>Refresh serial ports</b><br>"
            "Re-scans all COM/USB serial ports and updates the dropdown",
            "<b>Connect to Arduino Uno</b><br>"
            "Opens a serial connection on the selected port at 115200 baud",
            "<b>Disconnect Arduino Uno</b><br>"
            "Stops the motor and closes the serial port",
            prefer=self._is_uno_port)

        (ca, self._mfc_port_combo, self._mfc_connect_btn,
         self._mfc_disconnect_btn, self._mfc_status_lbl) = connection_card(
            "ALICAT MFC", self._refresh_mfc_ports,
            self._trigger_mfc_connect, self._trigger_mfc_disconnect,
            "Re-scans all COM/USB serial ports and updates the dropdown",
            "<b>Connect to Alicat MFC</b><br>"
            "Opens RS232 at 19200 baud and sets flow to 0 sccm",
            "<b>Disconnect Alicat MFC</b><br>"
            "Sets flow to 0 sccm then closes the serial port")

        for _cd in (c, cu, ca):
            crl.addWidget(_cd, 1)
        vl.addWidget(conn_row)

        # ── Motor speed (Arduino Uno) ─────────────────────────────────────────
        # Split out of the Uno card: it needs more width than a third of the row.
        cu_ctrl = card(w, padding=20)
        cu_ctrl.layout().setSpacing(14)
        cu_ctrl.layout().addWidget(section_label("MOTOR SPEED"))
        cu_ctrl.layout().addWidget(separator())

        rpm_ctrl_row = QWidget()
        rcr = QHBoxLayout(rpm_ctrl_row); rcr.setContentsMargins(0,0,0,0); rcr.setSpacing(8)
        rpm_lbl = QLabel("RPM"); rpm_lbl.setFixedWidth(80)
        rpm_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._rpm_entry = QLineEdit()
        self._rpm_entry.setPlaceholderText("e.g. 100")
        self._rpm_entry.setMinimumWidth(80)
        self._rpm_entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._rpm_entry.setValidator(QDoubleValidator(0.0, 10000.0, 1))
        self._rpm_spin_btn = accent_button("Spin", CLR_RED)
        self._rpm_spin_btn.setFixedHeight(36)
        self._rpm_spin_btn.setEnabled(False)
        self._rpm_spin_btn.setToolTip(
            "<b>Spin / Stop motor</b><br>"
            "Sends the RPM value to the Arduino and starts the motor.<br>"
            "Click again to stop.")
        self._rpm_spin_btn.clicked.connect(self._toggle_spin)
        self._rpm_actual_lbl = QLabel("● 0 RPM")
        self._rpm_actual_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px; min-width:80px;")
        self._rpm_actual_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rcr.addWidget(rpm_lbl); rcr.addWidget(self._rpm_entry); rcr.addWidget(self._rpm_spin_btn)
        rcr.addWidget(self._rpm_actual_lbl)
        cu_ctrl.layout().addWidget(rpm_ctrl_row)

        # ── Driver status row: SG · OTPW · OT · Current ───────────────────────
        # Populated from the TMC5160's MOTOR_STATUS: line — see _on_motor_status.
        # Green is the normal/healthy state for all four; SG additionally has an
        # amber early-warning band above the firmware's own stall cutoff.
        def _status_readout(label_text, tooltip):
            rw = QWidget()
            rw.setToolTip(tooltip)
            rvl = QVBoxLayout(rw); rvl.setContentsMargins(0,0,0,0); rvl.setSpacing(2)
            rl = QLabel(label_text)
            rl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
            rl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rv = QLabel("–")
            rv.setStyleSheet(f"color:{CLR_TEXT}; font-size:14px; font-weight:700;")
            rv.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rvl.addWidget(rl); rvl.addWidget(rv)
            return rw, rv

        status_row = QWidget()
        srr = QHBoxLayout(status_row); srr.setContentsMargins(0,0,0,0)

        _sgw, self._rpm_sg_lbl = _status_readout(
            "SG",
            "<b>StallGuard result</b><br>"
            "TMC5160 back-EMF load estimate, 0–1023. Falls as load increases; "
            "the Arduino stops the motor itself once this crosses its own "
            "internal threshold — this box turns red at that same point, "
            "amber as an earlier warning, and stays red until you press Spin "
            "again. Shown grey while stopped or below the trusted-speed floor "
            "— the reading is 0 by design at rest, not an indication of load.")
        _otpww, self._rpm_otpw_lbl = _status_readout(
            "OTPW",
            "<b>Over-temperature pre-warning</b><br>"
            "Driver die is running hot. Motor keeps running — treat this as "
            "an early warning to check cooling or current before OT trips.")
        _otw, self._rpm_ot_lbl = _status_readout(
            "OT",
            "<b>Over-temperature shutdown</b><br>"
            "Driver has disabled its own output stage to protect itself. "
            "Motor will not respond until it cools and this clears.")
        _csw, self._rpm_current_lbl = _status_readout(
            "Current",
            "<b>Actual coil current</b><br>"
            "Computed from the driver's live current-scale register — the real "
            "figure, not just the programmed MOTOR_CURRENT. Reads about half of "
            "MOTOR_CURRENT while idle (the driver's automatic hold-current "
            "reduction) and the full value while running. That halving is "
            "normal and unrelated to CoolStep, which isn't enabled here.")
        for _sw in (_sgw, _otpww, _otw, _csw):
            srr.addWidget(_sw, 1)          # equal stretch -> evenly spaced
        cu_ctrl.layout().addWidget(status_row)

        vl.addWidget(cu_ctrl)

        # ── Mass Flow Control ─────────────────────────────────────────────────
        c_mfc = card(w)
        c_mfc.layout().addWidget(section_label("MASS FLOW CONTROL"))
        c_mfc.layout().addWidget(separator())

        mf_input_row = QWidget()
        mfir = QHBoxLayout(mf_input_row); mfir.setContentsMargins(0,0,0,0); mfir.setSpacing(8)
        mf_lbl = QLabel("Target (sccm)"); mf_lbl.setFixedWidth(110)
        mf_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._flow_entry = QLineEdit()
        self._flow_entry.setPlaceholderText("0 – 12000")
        self._flow_entry.setMinimumWidth(80)
        self._flow_entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._flow_entry.setValidator(QDoubleValidator(0.0, 12000.0, 1))
        self._flow_entry.textChanged.connect(self._update_next_save_preview)
        self._flow_entry.textChanged.connect(self._update_glr_label)
        set_f_btn = accent_button("Set Flow", CLR_ACCENT)
        set_f_btn.setFixedHeight(36)
        set_f_btn.setToolTip(
            "<b>Set mass flow</b><br>"
            "1. Validates the entered value (0 – 12000 sccm)<br>"
            "2. Sends the setpoint to the Alicat MFC over RS232")
        set_f_btn.clicked.connect(self._set_flow)
        off_f_btn = accent_button("Gas Flow Off", CLR_RED)
        off_f_btn.setFixedHeight(36)
        off_f_btn.setToolTip(
            "<b>Gas flow off</b><br>"
            "Immediately sets the Alicat setpoint to 0 sccm")
        off_f_btn.clicked.connect(self._flow_off)

        # Automatic STOP EVERYTHING, driven by the Alicat pressure.
        self._cutoff_entry = QLineEdit()
        self._cutoff_entry.setPlaceholderText("off")
        self._cutoff_entry.setFixedWidth(56)
        self._cutoff_entry.setValidator(_BlankOrRangeValidator(0.0, 30.0, 2))
        self._cutoff_entry.setToolTip(
            "<b>Pressure cut-off (barA, 0–30)</b><br>"
            "If the live Alicat pressure ever reaches this value, STOP EVERYTHING "
            "fires automatically: traverse (silicone feed) stopped, bubbler motor "
            "stopped, gas zeroed.<br><br>"
            "Compared against the <b>raw</b> barA reading (the Alicat's absolute "
            "pressure, ≈ gauge + 1 bar), not the smoothed trace, so it acts on the "
            "first frame over (~0.2 s polling).<br>"
            "Fires once, then re-arms when the pressure falls below 90% of the "
            "cut-off. Leave empty or 0 to switch it off. Remembered between "
            "sessions.<br><br>"
            "<i>A run stopped this way is saved as normal (the traverse reports "
            "complete on STOP); re-home afterwards as for any emergency stop.</i>")
        self._cutoff_entry.editingFinished.connect(self._on_cutoff_changed)
        self._cutoff_status_lbl = QLabel("Off")
        self._cutoff_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        cut_lbl = QLabel("Cut-off barA")
        cut_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        cutoff_row = QWidget()
        crl = QHBoxLayout(cutoff_row)
        crl.setContentsMargins(0, 0, 0, 0)
        crl.setSpacing(6)
        crl.addWidget(cut_lbl)
        crl.addWidget(self._cutoff_entry)
        crl.addWidget(self._cutoff_status_lbl)

        # Gas ramp: how fast Set Flow and Start Experiment move the setpoint.
        self._ramp_entry = QLineEdit()
        self._ramp_entry.setPlaceholderText("off")
        self._ramp_entry.setFixedWidth(56)
        self._ramp_entry.setValidator(_BlankOrRangeValidator(0.0, 12000.0, 0))
        self._ramp_entry.setToolTip(
            "<b>SCCM ramp (sccm per second, 0–12000)</b><br>"
            "Set Flow and Start Experiment move the gas smoothly from the current "
            "setpoint to the target at this rate: 1000 takes 6000 sccm up from 0 "
            "in 6 s. The setpoint is updated 10 times a second.<br><br>"
            "Gas Flow Off, STOP EVERYTHING and the pressure cut-off always cut the "
            "gas at once. Leave empty or 0 to jump straight to the target. "
            "Remembered between sessions.")
        self._ramp_entry.editingFinished.connect(self._on_ramp_changed)
        ramp_lbl = QLabel("SCCM ramp /s")
        ramp_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        ramp_row = QWidget()
        rrl = QHBoxLayout(ramp_row)
        rrl.setContentsMargins(0, 0, 0, 0)
        rrl.setSpacing(6)
        rrl.addWidget(ramp_lbl)
        rrl.addWidget(self._ramp_entry)
        rrl.addStretch()
        off_f_stack = QWidget()
        off_f_vl = QVBoxLayout(off_f_stack)
        off_f_vl.setContentsMargins(0, 0, 0, 0)
        off_f_vl.setSpacing(4)
        off_f_vl.addWidget(off_f_btn)
        off_f_vl.addWidget(cutoff_row)
        off_f_vl.addWidget(ramp_row)

        self._last_flow_btn = QPushButton("Set last flow")
        self._last_flow_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {CLR_INPUT};
                color: {CLR_TEXT_SEC};
                border: 1px solid {CLR_BORDER};
                border-radius: 8px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{ background-color: #3a3a3c; color: {CLR_TEXT}; }}
            QPushButton:pressed {{ background-color: #4a4a4e; }}
            QPushButton:disabled {{ color: #555; border-color: #333; }}
        """)
        self._last_flow_btn.setEnabled(False)
        self._last_flow_btn.clicked.connect(self._set_last_flow)

        set_f_stack = QWidget()
        set_f_vl = QVBoxLayout(set_f_stack)
        set_f_vl.setContentsMargins(0, 0, 0, 0)
        set_f_vl.setSpacing(4)
        set_f_vl.addWidget(set_f_btn)
        set_f_vl.addWidget(self._last_flow_btn)
        mfir.addWidget(mf_lbl); mfir.addWidget(self._flow_entry)
        mfir.addWidget(set_f_stack); mfir.addStretch(); mfir.addWidget(off_f_stack)
        c_mfc.layout().addWidget(mf_input_row)

        # Live readouts
        mf_readout_row = QWidget()
        mfrr = QHBoxLayout(mf_readout_row); mfrr.setContentsMargins(0,0,0,0); mfrr.setSpacing(20)

        def _mfc_readout(label_text):
            rw = QWidget()
            rvl = QVBoxLayout(rw); rvl.setContentsMargins(0,0,0,0); rvl.setSpacing(2)
            rl = QLabel(label_text)
            rl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
            rv = QLabel("–")
            rv.setStyleSheet(f"color:{CLR_TEXT}; font-size:14px; font-weight:700;")
            rvl.addWidget(rl); rvl.addWidget(rv)
            return rw, rv

        _fw,  self._mfc_flow_lbl  = _mfc_readout("Mass Flow")
        _sw,  self._mfc_setpt_lbl = _mfc_readout("Setpoint")
        _pw,  self._mfc_pres_lbl  = _mfc_readout("Pressure")
        _tw,  self._mfc_temp_lbl  = _mfc_readout("Temperature")
        _rw,  self._mfc_regime_lbl = _mfc_readout("Gas regime")
        self._mfc_regime_lbl.setToolTip(
            "Flow-controlled: the gas is at its set point. PRESSURE-LIMITED: it has been more than 5% "
            f"short for {GAS_SHORT_HOLD_S:g} s with the pressure at the supply ceiling (~{SUPPLY_CEILING_BAR:g} "
            "barA): the silicone is choking the orifice and the set point is not what the run gets. "
            "GAS SHORT: short with the pressure lower (check the supply and the Alicat).")
        mfrr.addWidget(_fw); mfrr.addWidget(_sw)
        mfrr.addWidget(_pw); mfrr.addWidget(_tw); mfrr.addWidget(_rw); mfrr.addStretch()
        c_mfc.layout().addWidget(mf_readout_row)
        vl.addWidget(c_mfc)

        # ── Motor ─────────────────────────────────────────────────────────────
        c3 = card(w)
        c3.layout().addWidget(section_label("MOTOR"))
        c3.layout().addWidget(separator())

        self._speed_entry    = QLineEdit(); self._speed_entry.setPlaceholderText("e.g. 1000  steps/s")
        self._distance_entry = QLineEdit(); self._distance_entry.setPlaceholderText("e.g. 10.0  mm")
        self._speed_entry.setValidator(QDoubleValidator(0.0, 100000.0, 0))
        self._distance_entry.setValidator(QDoubleValidator(0.0, 72.5, 2))
        self._distance_entry.textChanged.connect(self._update_volume_label)
        self._speed_entry.textChanged.connect(self._update_flowrate_label)

        _speed_row = QWidget()
        _speed_rl = QHBoxLayout(_speed_row); _speed_rl.setContentsMargins(0,0,0,0); _speed_rl.setSpacing(6)
        self._flowrate_lbl = QLabel("≈ – mL/min")
        self._flowrate_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        _speed_rl.addWidget(input_row("Speed (steps/s)", self._speed_entry))
        _speed_rl.addWidget(self._flowrate_lbl)
        c3.layout().addWidget(_speed_row)

        _dist_row = QWidget()
        _dist_rl = QHBoxLayout(_dist_row); _dist_rl.setContentsMargins(0,0,0,0); _dist_rl.setSpacing(6)
        self._volume_lbl = QLabel("≈ – mL")
        self._volume_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        _dist_rl.addWidget(input_row("Motor Travel (mm)", self._distance_entry))
        _dist_rl.addWidget(self._volume_lbl)
        c3.layout().addWidget(_dist_row)

        motor_btns = QWidget()
        mb = QHBoxLayout(motor_btns); mb.setContentsMargins(0,0,0,0); mb.setSpacing(8)
        self._home_btn  = accent_button("🏠  Home",    CLR_ORANGE)
        self._switches_btn = ghost_button("Check switches")
        self._move_btn  = accent_button("Move",        CLR_ACCENT)
        self._homed_dot = dot_indicator(CLR_RED)
        homed_lbl = QLabel("Homed"); homed_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        # Jog buttons (▲ / ▼) — hold to move, release to stop
        jog_widget = QWidget()
        jog_vl = QVBoxLayout(jog_widget)
        jog_vl.setContentsMargins(0, 0, 0, 0)
        jog_vl.setSpacing(2)
        self._jog_up_btn   = QPushButton("↑")
        self._jog_down_btn = QPushButton("↓")
        _jog_style = f"""
            QPushButton {{
                background-color: {CLR_INPUT};
                color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER};
                border-radius: 5px;
                font-size: 14px;
                font-weight: 700;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton:hover   {{ background-color: {CLR_ACCENT}; color: white; border-color: {CLR_ACCENT}; }}
            QPushButton:pressed {{ background-color: {_darken_hex(CLR_ACCENT)}; color: white; }}
            QPushButton:disabled {{ color: {CLR_TEXT_SEC}; border-color: {CLR_BORDER}; }}
        """
        self._jog_up_btn.setStyleSheet(_jog_style)
        self._jog_down_btn.setStyleSheet(_jog_style)
        self._jog_up_btn.setFixedSize(32, 20)
        self._jog_down_btn.setFixedSize(32, 20)
        self._jog_up_btn.setToolTip("<b>Jog forward</b><br>Hold to move motor forward at the current speed")
        self._jog_down_btn.setToolTip("<b>Jog backward</b><br>Hold to move motor backward at the current speed")
        self._jog_up_btn.pressed.connect(lambda: self._jog_start(1))
        self._jog_up_btn.released.connect(self._jog_stop)
        self._jog_down_btn.pressed.connect(lambda: self._jog_start(-1))
        self._jog_down_btn.released.connect(self._jog_stop)
        jog_vl.addWidget(self._jog_up_btn)
        jog_vl.addWidget(self._jog_down_btn)

        self._home_btn.setFixedHeight(36); self._switches_btn.setFixedHeight(36); self._move_btn.setFixedHeight(36)
        self._home_btn.setToolTip(
            "<b>Home motor</b><br>"
            "1. Drives the motor to the reference (zero) position<br>"
            "2. Sets the internal position counter to zero<br>"
            "Run this once before any other motor commands")
        self._switches_btn.setToolTip(
            "<b>Check limit switches</b><br>"
            "Asks the Portenta for the raw state of both optical switches and logs it "
            "to the console: back (home) and front (absolute forward stop).<br>"
            "Each should read LOW with the beam clear and HIGH with it blocked. "
            "The front switch stops any forward move or jog the moment it reads HIGH; "
            "a front switch that reads HIGH with the beam clear (unplugged, or wired "
            "the other way round) blocks all forward motion.")
        self._move_btn.setToolTip(
            "<b>Move motor</b><br>"
            "1. Reads the Speed (steps/s) and Motor Travel (mm) fields<br>"
            "2. Sends a relative move command to the Portenta<br>"
            "3. Motor moves by that distance at that speed")
        self._home_btn.clicked.connect(self._home_motor)
        self._switches_btn.clicked.connect(self._check_switches)
        self._move_btn.clicked.connect(self._move_motor)
        mb.addWidget(self._home_btn); mb.addWidget(self._switches_btn)
        mb.addStretch(); mb.addWidget(self._homed_dot); mb.addWidget(homed_lbl)
        mb.addStretch(); mb.addWidget(jog_widget); mb.addWidget(self._move_btn)
        c3.layout().addWidget(motor_btns)
        vl.addWidget(c3)

        vl.addStretch()
        scroll.setWidget(w)
        return scroll

    # ── Camera tab ────────────────────────────────────────────────────────────

    # Shared by the Camera tab and the Live Camera View card.
    @staticmethod
    def _cam_connect_tooltip():
        return ("<b>Connect to Phantom camera</b><br>"
                "1. Connects to the camera at the IP address in the Camera tab<br>"
                "2. Initialises the Phantom SDK<br>"
                "3. Enables capture and config controls")

    @staticmethod
    def _cam_ping_tooltip():
        return ("<b>Ping camera</b><br>"
                "1. Sends a network ping to the camera IP<br>"
                "2. Reports whether the camera is reachable on the network<br>"
                "Use this to check connectivity before connecting")

    def _build_camera_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w = QWidget()
        w.setMinimumWidth(0)
        vl = QVBoxLayout(w); vl.setContentsMargins(20,20,20,20); vl.setSpacing(14)

        # Connection card
        c1 = card(w)
        c1.layout().addWidget(section_label("CONNECTION"))
        c1.layout().addWidget(separator())

        ip_row = QWidget()
        ipr = QHBoxLayout(ip_row); ipr.setContentsMargins(0,0,0,0); ipr.setSpacing(8)
        ip_lbl = QLabel("IP Address"); ip_lbl.setFixedWidth(100)
        ip_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._cam_ip = QLineEdit("100.100.100.1")
        self._cam_connect_btn = accent_button("Connect", CLR_ACCENT)
        self._cam_ping_btn    = ghost_button("Ping")
        self._cam_connect_btn.setFixedHeight(36); self._cam_ping_btn.setFixedHeight(36)
        self._cam_connect_btn.setToolTip(self._cam_connect_tooltip())
        self._cam_ping_btn.setToolTip(self._cam_ping_tooltip())
        self._cam_connect_btn.clicked.connect(self._cam_connect)
        self._cam_ping_btn.clicked.connect(self._cam_ping)
        ipr.addWidget(ip_lbl); ipr.addWidget(self._cam_ip)
        ipr.addWidget(self._cam_connect_btn); ipr.addWidget(self._cam_ping_btn)
        c1.layout().addWidget(ip_row)

        self._cam_status_lbl = QLabel("Camera: idle")
        self._cam_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        c1.layout().addWidget(self._cam_status_lbl)

        if not self.camera_available:
            warn = QLabel("⚠  Camera SDK requires Windows + pyphantom")
            warn.setStyleSheet(f"color:{CLR_ORANGE}; font-size:12px; font-weight:600;")
            c1.layout().addWidget(warn)
        vl.addWidget(c1)

        # Config card
        c2 = card(w)
        c2.layout().addWidget(section_label("CONFIGURATION"))
        c2.layout().addWidget(separator())

        grid_w = QWidget()
        grid = QGridLayout(grid_w); grid.setSpacing(10)

        _W = 80  # uniform input width
        _std = {k: v for k, _l, v in self.STANDARD_CAPTURE}
        self._cam_fps      = QLineEdit(_std["fps"]);            self._cam_fps.setFixedWidth(_W)
        self._cam_exp      = QLineEdit(_std["exposure_us"]);    self._cam_exp.setFixedWidth(_W)
        self._cam_exp_idx  = QLineEdit("0");                    self._cam_exp_idx.setFixedWidth(_W)
        self._cam_width    = QLineEdit(_std["width"]);          self._cam_width.setFixedWidth(_W)
        self._cam_height   = QLineEdit(_std["height"]);         self._cam_height.setFixedWidth(_W)
        self._cam_pre_s    = QLineEdit(_std["pre_trigger_s"]);  self._cam_pre_s.setFixedWidth(_W)
        self._cam_post_s   = QLineEdit(_std["post_trigger_s"]); self._cam_post_s.setFixedWidth(_W)

        self._cam_fps.setValidator(QDoubleValidator(1.0, 100000.0, 0))
        self._cam_exp.setValidator(QDoubleValidator(1.0, 1000000.0, 0))
        self._cam_exp_idx.setValidator(QIntValidator(0, 999))
        self._cam_width.setValidator(QIntValidator(1, 2560))
        self._cam_height.setValidator(QIntValidator(1, 1600))
        self._cam_pre_s.setValidator(QDoubleValidator(0.0, 60.0, 3))
        self._cam_post_s.setValidator(QDoubleValidator(0.0, 60.0, 3))

        def glbl(t):
            l=QLabel(t); l.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
            return l

        grid.addWidget(glbl("FPS"),               0,0); grid.addWidget(self._cam_fps,    0,1)
        grid.addWidget(glbl("Height"),            1,0); grid.addWidget(self._cam_height, 1,1)
        grid.addWidget(glbl("Width"),             2,0); grid.addWidget(self._cam_width,  2,1)
        grid.addWidget(glbl("Pre-trigger (s)"),   3,0); grid.addWidget(self._cam_pre_s,  3,1)
        grid.addWidget(glbl("Post-trigger (s)"),  4,0); grid.addWidget(self._cam_post_s, 4,1)
        grid.addWidget(glbl("Exposure (μs)"),     5,0); grid.addWidget(self._cam_exp,    5,1)
        grid.addWidget(glbl("Exposure Index"),    6,0); grid.addWidget(self._cam_exp_idx,6,1)
        grid.setColumnStretch(1, 1)

        # Capacity info box — sits to the right of the grid
        cap_box = QFrame()
        cap_box.setFixedWidth(150)
        cap_box.setStyleSheet(f"""
            QFrame {{
                background: {CLR_INPUT};
                border: 1px solid {CLR_BORDER};
                border-radius: 6px;
            }}
        """)
        cap_vl = QVBoxLayout(cap_box)
        cap_vl.setContentsMargins(10, 10, 10, 10)
        cap_vl.setSpacing(2)
        _cap_title = QLabel("RAM CAPACITY")
        _cap_title.setStyleSheet(
            f"color:{CLR_TEXT_SEC}; font-size:9px; font-weight:700; letter-spacing:1px;")
        cap_vl.addWidget(_cap_title)
        _cap_sub = QLabel("18 GB  Veo-E 340L")
        _cap_sub.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px;")
        cap_vl.addWidget(_cap_sub)
        cap_vl.addSpacing(6)
        self._cam_capacity_lbl = QLabel("—")
        self._cam_capacity_lbl.setStyleSheet(
            f"color:{CLR_TEXT}; font-size:22px; font-weight:600;")
        cap_vl.addWidget(self._cam_capacity_lbl)
        self._cam_capacity_frames_lbl = QLabel("")
        self._cam_capacity_frames_lbl.setStyleSheet(
            f"color:{CLR_TEXT_SEC}; font-size:10px;")
        self._cam_capacity_frames_lbl.setWordWrap(True)
        cap_vl.addWidget(self._cam_capacity_frames_lbl)
        cap_vl.addStretch()
        cap_vl.addSpacing(8)
        self._cam_save_video_chk = QCheckBox("Save video (.cine)")
        self._cam_save_video_chk.setChecked(True)
        self._cam_save_video_chk.setStyleSheet(f"color:{CLR_TEXT}; font-size:11px;")
        self._cam_save_video_chk.setToolTip(
            "<b>Save video (.cine)</b><br>"
            "Writes the captured window as a single .cine file to shadowgraph/raw/CINE.<br>"
            "At least one of .cine / TIFFs must stay ticked.")
        cap_vl.addWidget(self._cam_save_video_chk)

        self._cam_save_tiffs_chk = QCheckBox("Save TIFFs")
        self._cam_save_tiffs_chk.setChecked(True)
        self._cam_save_tiffs_chk.setStyleSheet(f"color:{CLR_TEXT}; font-size:11px;")
        self._cam_save_tiffs_chk.setToolTip(
            "<b>Save TIFFs</b><br>"
            "Writes the captured window as a numbered .tif sequence to shadowgraph/raw/TIFFs.<br>"
            "Required by the brightest-frame step, the AI pipeline and lamella analysis — "
            "with this off those are skipped.<br>"
            "At least one of .cine / TIFFs must stay ticked.")
        cap_vl.addWidget(self._cam_save_tiffs_chk)

        # Mutual minimum: untick the last one and the other flips back on.
        self._cam_save_video_chk.toggled.connect(
            lambda _c: self._on_save_format_changed("cine"))
        self._cam_save_tiffs_chk.toggled.connect(
            lambda _c: self._on_save_format_changed("tiff"))

        body_row = QWidget()
        br = QHBoxLayout(body_row)
        br.setContentsMargins(0, 0, 0, 0); br.setSpacing(12)
        br.addWidget(grid_w, stretch=1)
        br.addWidget(cap_box, alignment=Qt.AlignmentFlag.AlignTop)
        c2.layout().addWidget(body_row)

        # Wire up live capacity updates — also call once to populate initial value
        self._cam_fps.textChanged.connect(self._update_cam_capacity)
        self._cam_width.textChanged.connect(self._update_cam_capacity)
        self._cam_height.textChanged.connect(self._update_cam_capacity)
        self._update_cam_capacity()
        # The stride note quotes fps and the capture length, so it has to follow
        # every field that feeds it, not just the stride box.
        for _f in (self._cam_fps, self._cam_pre_s, self._cam_post_s,
                   self._cam_width, self._cam_height):
            _f.textChanged.connect(self._update_stride_note)

        # Read-only label showing where captures will be saved
        self._cam_save_lbl = QLabel(self._cam_path_hint())
        self._cam_save_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px;")
        self._cam_save_lbl.setWordWrap(True)
        c2.layout().addWidget(self._cam_save_lbl)

        apply_btn = accent_button("Apply Config", CLR_ACCENT)
        apply_btn.setFixedHeight(36)
        apply_btn.setToolTip(
            "<b>Apply camera config</b><br>"
            "1. Reads FPS, resolution, exposure and duration fields<br>"
            "2. Validates against camera maximums<br>"
            "3. Pushes the settings to the Phantom camera")
        apply_btn.clicked.connect(self._cam_configure)
        c2.layout().addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignRight)
        vl.addWidget(c2)

        # Capture card
        c3 = card(w)
        c3.layout().addWidget(section_label("CAPTURE"))
        c3.layout().addWidget(separator())

        self._pipeline_check = QCheckBox("Run AI analysis after capture")
        self._pipeline_check.setStyleSheet(f"color:{CLR_TEXT}; font-size:13px;")
        self._pipeline_check.stateChanged.connect(self._save_camera_settings)
        self._pipeline_check.setToolTip(
            "<b>Run AI analysis after capture</b><br>"
            "Runs the full chain on the saved .cine: frame extraction → "
            "background → tiled inference → D32 and atomised fraction.<br>"
            "Unticked, the capture is saved and nothing else happens.")

        # Stride sits beside the checkbox it governs, with a live note giving
        # the real cost -- frames analysed and expected inference time at the
        # camera's current fps. The cost of stride 1 is an hour, and that is
        # not something to discover after pressing go.
        self._ai_stride = QLineEdit(str(self.DEFAULT_STRIDE))
        self._ai_stride.setFixedWidth(56)
        self._ai_stride.setValidator(QIntValidator(1, 1000))
        self._ai_stride.setToolTip(
            "<b>Analyse every Nth frame</b><br>"
            "1 = every frame. Higher = fewer frames, proportionally faster.<br>"
            "The default matches the decorrelation time: frames closer together "
            "than that largely contain the SAME droplets, so they add compute "
            "without adding independent information.")
        _ai_row = QWidget()
        _ar = QHBoxLayout(_ai_row); _ar.setContentsMargins(0, 0, 0, 0); _ar.setSpacing(8)
        _ar.addWidget(self._pipeline_check)
        _ar.addStretch()
        _sl = QLabel("Stride"); _sl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        _ar.addWidget(_sl)
        _ar.addWidget(self._ai_stride)
        c3.layout().addWidget(_ai_row)

        self._ai_stride_note = QLabel("")
        self._ai_stride_note.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        self._ai_stride_note.setWordWrap(True)
        c3.layout().addWidget(self._ai_stride_note)

        self._ai_stride.textChanged.connect(self._update_stride_note)
        self._ai_stride.editingFinished.connect(self._save_camera_settings)
        self._pipeline_check.stateChanged.connect(self._update_stride_note)

        self._cam_arm_status_lbl = QLabel("Not armed")
        self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        c3.layout().addWidget(self._cam_arm_status_lbl)

        self._cam_save_progress = QProgressBar()
        self._cam_save_progress.setRange(0, 100)
        self._cam_save_progress.setValue(0)
        self._cam_save_progress.setFixedHeight(6)
        self._cam_save_progress.setTextVisible(False)
        self._cam_save_progress.setStyleSheet(
            f"QProgressBar {{ background-color:{CLR_INPUT}; border:none; border-radius:3px; }}"
            f"QProgressBar::chunk {{ background-color:{CLR_ACCENT}; border-radius:3px; }}"
        )
        self._cam_save_progress.setVisible(False)
        c3.layout().addWidget(self._cam_save_progress)

        cap_row = QWidget()
        cpr = QHBoxLayout(cap_row); cpr.setContentsMargins(0,0,0,0); cpr.setSpacing(8)
        self._cam_abort_btn   = ghost_button("Disarm / Abort")
        self._cam_arm_btn     = accent_button("Arm", CLR_ACCENT)
        self._cam_trigger_btn = accent_button("● Trigger", CLR_RED)
        self._cam_abort_btn.setFixedHeight(40)
        self._cam_arm_btn.setFixedHeight(40)
        self._cam_trigger_btn.setFixedHeight(40)
        self._cam_trigger_btn.setEnabled(False)   # enabled only when armed
        self._cam_abort_btn.setToolTip(
            "<b>Disarm / Abort</b><br>"
            "1. Stops the ring-buffer recording<br>"
            "2. Clears camera RAM<br>"
            "3. Re-enables the Arm button")
        self._cam_arm_btn.setToolTip(
            "<b>Arm camera</b><br>"
            "1. Applies current config to the Phantom camera<br>"
            "2. Starts continuous ring-buffer recording<br>"
            "3. Camera will buffer footage until you click Trigger<br>"
            "Must click Apply Config first if settings have changed")
        self._cam_trigger_btn.setToolTip(
            "<b>Trigger</b><br>"
            "1. Freezes the ring buffer at this moment<br>"
            "2. Saves pre-trigger + post-trigger frames in the formats ticked "
            "under RAM CAPACITY (.cine and/or TIFFs)<br>"
            "3. Identifies the brightest frame (needs TIFFs)<br>"
            "4. If 'Run AI analysis' is ticked, runs Dennis immediately<br>"
            "5. Camera re-arms automatically for the next trigger")
        self._cam_abort_btn.clicked.connect(self._cam_abort)
        self._cam_arm_btn.clicked.connect(self._cam_arm)
        self._cam_trigger_btn.clicked.connect(self._cam_trigger)
        self._auto_trig_chk = QCheckBox("Auto-trigger at end of test")
        self._auto_trig_chk.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        self._auto_trig_chk.setToolTip(
            "<b>Auto-trigger at end of test</b><br>"
            "On Start Experiment, arms the camera (if it is not armed) and fires the "
            "trigger by itself so the saved video is the LAST part of the test: it ends "
            "2 s before the traverse stops.<br>"
            "Trigger time = test length − 2 s − Post-trigger (s); test length = "
            "Motor Travel × 6800 / Speed (steps/s).<br>"
            "E.g. a 25 s test with a 13 s video triggers with 15 s left.<br>"
            "Cancelled by Disarm / Abort, Pressure Off or a timed-out run. Remembered "
            "between sessions.")
        self._auto_trig_chk.stateChanged.connect(self._save_camera_settings)
        cpr.addWidget(self._auto_trig_chk)
        cpr.addStretch()
        cpr.addWidget(self._cam_abort_btn)
        cpr.addWidget(self._cam_arm_btn)
        cpr.addWidget(self._cam_trigger_btn)
        c3.layout().addWidget(cap_row)
        vl.addWidget(c3)

        if not self.camera_available:
            for btn in [self._cam_connect_btn, self._cam_ping_btn,
                        apply_btn, self._cam_abort_btn, self._cam_arm_btn, self._cam_trigger_btn]:
                btn.setEnabled(False)

        # Window check card (drops on the window / lens, 2026-10-13)
        c_win = card(w)
        c_win.layout().addWidget(section_label("WINDOW CHECK"))
        c_win.layout().addWidget(separator())
        _win_desc = QLabel(
            "A drop on the window is counted as un-atomised liquid (on the CCD day one cut a run's "
            "atomised fraction from 10.5% to 6.0%). Wipe the window, save a clean reference with the "
            "backlight on and nothing in view, and each Start Experiment compares the live view with it "
            "and warns about new dark spots.")
        _win_desc.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        _win_desc.setWordWrap(True)
        c_win.layout().addWidget(_win_desc)
        self._window_ref_lbl = QLabel(self._window_ref_text())
        self._window_ref_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        self._window_ref_lbl.setWordWrap(True)
        c_win.layout().addWidget(self._window_ref_lbl)
        win_row = QWidget()
        wrl = QHBoxLayout(win_row); wrl.setContentsMargins(0, 0, 0, 0); wrl.setSpacing(8)
        self._window_chk = QCheckBox("Check at Start Experiment")
        self._window_chk.setChecked(True)
        self._window_chk.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        self._window_chk.setToolTip(
            "<b>Check at Start Experiment</b><br>"
            "Before the gas starts, grabs one live frame and compares it with the clean reference. "
            "New dark spots (a drop, a smear) are shown boxed, and you choose to wipe first or start "
            "anyway. The result goes into run_summary ('Window check (before run)'). Remembered "
            "between sessions.")
        self._window_chk.stateChanged.connect(self._save_camera_settings)
        self._window_save_btn = ghost_button("Save clean reference")
        self._window_save_btn.setToolTip(
            "Keep the live view as the clean-window reference (on this PC). Do it after wiping the "
            "window, backlight on, no spray, and again whenever the camera, lens or backlight moves.")
        self._window_save_btn.clicked.connect(self._window_save_reference)
        self._window_now_btn = ghost_button("Check now")
        self._window_now_btn.setToolTip("Compare the live view with the clean reference now.")
        self._window_now_btn.clicked.connect(self._window_check_now)
        wrl.addWidget(self._window_chk)
        wrl.addStretch()
        wrl.addWidget(self._window_save_btn)
        wrl.addWidget(self._window_now_btn)
        c_win.layout().addWidget(win_row)
        if not self.camera_available or _window_check is None:
            self._window_save_btn.setEnabled(False)
            self._window_now_btn.setEnabled(False)
        vl.addWidget(c_win)

        # Full Analyse Cine card
        c_test = card(w)
        c_test.layout().addWidget(section_label("FULL ANALYSE CINE"))
        c_test.layout().addWidget(separator())
        _test_desc = QLabel(
            "Pick a .cine, choose a stride, and get a marked-up image of EVERY "
            "analysed frame. If the cine was analysed before, that stride is "
            "offered first and reuses the AI results. Real captures draw only "
            "the extreme frames. Never writes to the master log."
        )
        _test_desc.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        _test_desc.setWordWrap(True)
        c_test.layout().addWidget(_test_desc)
        self._test_pipeline_btn = accent_button(self.FULL_ANALYSE_LABEL, CLR_ACCENT)
        self._test_pipeline_btn.setFixedHeight(36)
        self._test_pipeline_btn.setToolTip(
            "<b>Full Analyse Cine</b><br>"
            "1. Asks for a .cine file<br>"
            "2. Asks for a stride — the one it was analysed at before (reuses "
            "the AI results, only draws images) or any other (1 = every frame)<br>"
            "3. A new stride runs extract → background → inference → D32 + "
            "atomised into Experiments/YYYY/MM/DD/Trial_n/<br>"
            "4. Draws a marked-up image of every analysed frame<br>"
            "Same code path as a real capture, which draws only the extremes. "
            "Results never go into master_log.")
        self._test_pipeline_btn.clicked.connect(self._run_test_pipeline)
        c_test.layout().addWidget(self._test_pipeline_btn, alignment=Qt.AlignmentFlag.AlignRight)
        vl.addWidget(c_test)

        vl.addStretch()
        scroll.setWidget(w); return scroll

    # ── AFG tab ───────────────────────────────────────────────────────────────

    def _build_afg_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w = QWidget()
        w.setMinimumWidth(0)
        vl = QVBoxLayout(w); vl.setContentsMargins(20,20,20,20); vl.setSpacing(14)

        c = card(w)
        c.layout().addWidget(section_label("TEKTRONIX AFG1062"))
        c.layout().addWidget(separator())

        ch_row = QWidget()
        chr_ = QHBoxLayout(ch_row); chr_.setContentsMargins(0,0,0,0); chr_.setSpacing(8)
        ch_lbl = QLabel("Channel"); ch_lbl.setFixedWidth(100)
        ch_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._afg_channel = QComboBox(); self._afg_channel.addItems(["CH1","CH2"])
        self._afg_channel.setFixedWidth(80)
        self._afg_connect_btn = accent_button("Connect", CLR_ACCENT)
        self._afg_connect_btn.setFixedHeight(36)
        self._afg_connect_btn.setToolTip(
            "<b>Connect to AFG1062</b><br>"
            "1. Scans all available VISA resources (USB/GPIB)<br>"
            "2. Identifies the Tektronix AFG1062<br>"
            "3. Opens a PyVISA connection to it")
        self._afg_connect_btn.clicked.connect(self._afg_connect)
        chr_.addWidget(ch_lbl); chr_.addWidget(self._afg_channel)
        chr_.addStretch(); chr_.addWidget(self._afg_connect_btn)
        c.layout().addWidget(ch_row)

        self._afg_duration = QLineEdit("0.001")
        self._afg_duration.setFixedWidth(120)
        self._afg_duration.setValidator(QDoubleValidator(0.000001, 10.0, 6))
        c.layout().addWidget(input_row("Pulse Duration (s)", self._afg_duration))

        action_row = QWidget()
        ar = QHBoxLayout(action_row); ar.setContentsMargins(0,0,0,0); ar.setSpacing(8)
        self._afg_apply_btn = accent_button("Apply Config",  CLR_ACCENT)
        self._afg_test_btn  = ghost_button("Test Fire")
        self._afg_disc_btn  = ghost_button("Disconnect")
        for btn in [self._afg_apply_btn, self._afg_test_btn, self._afg_disc_btn]:
            btn.setFixedHeight(36)
        self._afg_apply_btn.setToolTip(
            "<b>Apply AFG config</b><br>"
            "1. Reads the pulse duration and waveform settings<br>"
            "2. Pushes them to the selected channel on the AFG1062")
        self._afg_test_btn.setToolTip(
            "<b>Test fire</b><br>"
            "1. Sends a single pulse to the selected AFG channel<br>"
            "2. Triggers the atomiser once<br>"
            "Use this to verify the signal before a full experiment")
        self._afg_disc_btn.setToolTip(
            "<b>Disconnect AFG</b><br>"
            "1. Closes the PyVISA session<br>"
            "2. Releases the USB resource")
        self._afg_apply_btn.clicked.connect(self._afg_configure)
        self._afg_test_btn.clicked.connect(self._afg_test)
        self._afg_disc_btn.clicked.connect(self._afg_disconnect)
        ar.addWidget(self._afg_apply_btn); ar.addWidget(self._afg_test_btn)
        ar.addStretch(); ar.addWidget(self._afg_disc_btn)
        c.layout().addWidget(action_row)

        self._afg_status_lbl = QLabel("AFG: Not connected")
        self._afg_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        c.layout().addWidget(self._afg_status_lbl)

        if not PYVISA_AVAILABLE:
            warn = QLabel("⚠  PyVISA not installed — install with: pip install pyvisa")
            warn.setStyleSheet(f"color:{CLR_ORANGE}; font-size:12px; font-weight:600;")
            c.layout().addWidget(warn)
            for btn in [self._afg_connect_btn, self._afg_apply_btn,
                        self._afg_test_btn, self._afg_disc_btn]:
                btn.setEnabled(False)

        vl.addWidget(c)
        vl.addStretch()
        scroll.setWidget(w); return scroll

    # ── Calibration tab ───────────────────────────────────────────────────────

    def _build_calibration_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w = QWidget()
        w.setMinimumWidth(0)
        vl = QVBoxLayout(w); vl.setContentsMargins(20,20,20,20); vl.setSpacing(14)

        # ── LIVE FEED card ────────────────────────────────────────────────────
        c1 = card(w)
        c1.layout().addWidget(section_label("LIVE FEED"))
        c1.layout().addWidget(separator())

        if not self.camera_available:
            warn = QLabel("⚠  Live feed requires Windows + Phantom SDK.\n"
                          "Use 'Load from File' below to load a calibration image.")
            warn.setStyleSheet(f"color:{CLR_ORANGE}; font-size:12px; font-weight:600;")
            warn.setWordWrap(True)
            c1.layout().addWidget(warn)

        self._cal_feed_label = QLabel()
        self._cal_feed_label.setMinimumHeight(320)
        self._cal_feed_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._cal_feed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cal_feed_label.setStyleSheet(f"""
            background-color: {CLR_INPUT};
            border-radius: 8px;
            color: {CLR_TEXT_SEC};
            font-size: 12px;
        """)
        self._cal_feed_label.setText("Live feed not active")
        c1.layout().addWidget(self._cal_feed_label)

        feed_btn_row = QWidget()
        fbr = QHBoxLayout(feed_btn_row); fbr.setContentsMargins(0,0,0,0); fbr.setSpacing(8)
        self._cal_load_btn = ghost_button("Load from File")
        self._cal_load_btn.setFixedHeight(36)
        self._cal_load_btn.setToolTip(
            "<b>Load calibration image from file</b><br>"
            "1. Opens a file browser dialog<br>"
            "2. Loads the selected image (e.g. a photo of a ruler)<br>"
            "3. Displays it in the calibration panel for point selection")
        self._cal_load_btn.clicked.connect(self._cal_load_photo)
        self._cal_take_btn = accent_button("Use as Calibration Image", CLR_ACCENT)
        self._cal_take_btn.setFixedHeight(36)
        self._cal_take_btn.setToolTip(
            "<b>Use live frame as calibration image</b><br>"
            "1. Freezes the current Phantom live feed frame<br>"
            "2. Loads it into the calibration panel below<br>"
            "3. Ready for click-point selection")
        self._cal_take_btn.clicked.connect(self._cal_take_photo)
        self._cal_feed_start_btn = accent_button("▶ Start Feed", CLR_GREEN)
        self._cal_feed_start_btn.setFixedHeight(36)
        self._cal_feed_start_btn.setToolTip(
            "<b>Start live feed</b><br>"
            "1. Connects to the Phantom camera<br>"
            "2. Starts a live preview in the panel above<br>"
            "Use this to frame and focus before calibrating")
        self._cal_feed_start_btn.clicked.connect(self._cal_start_feed)
        self._cal_feed_stop_btn = ghost_button("■ Stop Feed")
        self._cal_feed_stop_btn.setFixedHeight(36)
        self._cal_feed_stop_btn.setEnabled(False)
        self._cal_feed_stop_btn.setToolTip(
            "<b>Stop live feed</b><br>"
            "1. Stops the Phantom live preview<br>"
            "2. Releases the camera feed")
        self._cal_feed_stop_btn.clicked.connect(self._cal_stop_feed)
        if not self.camera_available:
            self._cal_take_btn.setEnabled(False)
            self._cal_take_btn.setToolTip(
                "<b>Use live frame as calibration image</b><br>"
                "Not available on macOS — requires the Phantom SDK on Windows")
            self._cal_feed_start_btn.setEnabled(False)
        fbr.addWidget(self._cal_feed_start_btn)
        fbr.addWidget(self._cal_feed_stop_btn)
        fbr.addStretch()
        fbr.addWidget(self._cal_load_btn)
        fbr.addWidget(self._cal_take_btn)
        c1.layout().addWidget(feed_btn_row)

        vl.addWidget(c1)

        # ── LAMELLA ANALYSIS card ─────────────────────────────────────────────
        c_lam = card(w, padding=10)
        c_lam.layout().addWidget(section_label("LAMELLA ANALYSIS"))
        c_lam.layout().addWidget(separator())

        # Toggle + thickness readout row
        lam_top_row = QWidget()
        lam_top_rl  = QHBoxLayout(lam_top_row)
        lam_top_rl.setContentsMargins(0, 0, 0, 0); lam_top_rl.setSpacing(8)

        self._lamella_toggle_btn = QPushButton("Lamella Analysis  OFF")
        self._lamella_toggle_btn.setCheckable(True)
        self._lamella_toggle_btn.setFixedHeight(34)
        self._lamella_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {CLR_ACCENT};
                border: 1px solid {CLR_ACCENT};
                border-radius: 8px;
                padding: 4px 14px;
                font-weight: 500; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: rgba(10,132,255,0.15); }}
            QPushButton:checked {{
                background-color: {CLR_GREEN};
                color: white; border-color: {CLR_GREEN};
            }}
            QPushButton:checked:hover {{ background-color: #25a244; }}
        """)
        self._lamella_toggle_btn.setToolTip(
            "<b>Lamella Analysis</b><br>"
            "Persistent — stays ON across feed start/stop and experiments.<br>"
            "Overlay appears on the live feed when active.<br>"
            "Auto-runs batch analysis on TIFFs after each camera trigger.")
        self._lamella_toggle_btn.toggled.connect(self._lamella_toggle)

        self._lamella_thickness_lbl = QLabel("–")
        self._lamella_thickness_lbl.setStyleSheet(
            f"color:{CLR_TEXT}; font-size:14px; font-weight:600;")
        self._lamella_thickness_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        lam_top_rl.addWidget(self._lamella_toggle_btn)
        lam_top_rl.addStretch()
        lam_top_rl.addWidget(QLabel("Thickness:"))
        lam_top_rl.addWidget(self._lamella_thickness_lbl)
        c_lam.layout().addWidget(lam_top_row)

        # Model selector row
        lam_model_row = QWidget()
        lam_model_rl  = QHBoxLayout(lam_model_row)
        lam_model_rl.setContentsMargins(0, 0, 0, 0); lam_model_rl.setSpacing(8)
        lam_model_lbl = QLabel("Model:")
        lam_model_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._lamella_arch_combo = QComboBox()
        self._lamella_arch_combo.addItems(["tiny", "smp"])
        self._lamella_arch_combo.setCurrentText("tiny")
        self._lamella_arch_combo.setFixedHeight(28)
        self._lamella_arch_combo.setToolTip(
            "<b>tiny</b> — hand-written from-scratch U-Net (fastest, best on this dataset)<br>"
            "<b>smp</b> — transfer-learning U-Net (MobileNetV2)")
        self._lamella_arch_combo.currentTextChanged.connect(self._lamella_arch_changed)
        self._lamella_browse_btn = ghost_button("Browse…")
        self._lamella_browse_btn.setFixedHeight(26)
        self._lamella_browse_btn.setToolTip("Select a trained .pt model file")
        self._lamella_browse_btn.clicked.connect(self._lamella_browse_model)
        self._lamella_status_lbl = QLabel("No model loaded")
        self._lamella_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        lam_model_rl.addWidget(lam_model_lbl)
        lam_model_rl.addWidget(self._lamella_arch_combo)
        lam_model_rl.addWidget(self._lamella_browse_btn)
        lam_model_rl.addStretch()
        lam_model_rl.addWidget(self._lamella_status_lbl)
        c_lam.layout().addWidget(lam_model_row)

        # Crop config row (x, y, w, h spinboxes)
        lam_crop_row = QWidget()
        lam_crop_rl  = QHBoxLayout(lam_crop_row)
        lam_crop_rl.setContentsMargins(0, 0, 0, 0); lam_crop_rl.setSpacing(6)
        crop_lbl = QLabel("Outlet crop:")
        crop_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        lam_crop_rl.addWidget(crop_lbl)
        for axis, default in [("x", 860), ("y", 829), ("w", 307), ("h", 583)]:
            lbl = QLabel(axis + ":")
            lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
            spin = QSpinBox(); spin.setRange(0, 4096); spin.setValue(default)
            spin.setFixedWidth(60); spin.setFixedHeight(26)
            setattr(self, f"_lamella_crop_{axis}", spin)
            spin.valueChanged.connect(self._lamella_crop_changed)
            lam_crop_rl.addWidget(lbl)
            lam_crop_rl.addWidget(spin)
        lam_crop_rl.addStretch()
        c_lam.layout().addWidget(lam_crop_row)

        # Batch TIFF runner row
        lam_batch_row = QWidget()
        lam_batch_rl  = QHBoxLayout(lam_batch_row)
        lam_batch_rl.setContentsMargins(0, 0, 0, 0); lam_batch_rl.setSpacing(8)
        self._lamella_batch_btn = ghost_button("Run on TIFF Folder…")
        self._lamella_batch_btn.setFixedHeight(30)
        self._lamella_batch_btn.setToolTip(
            "<b>Run lamella analysis on a folder of TIFF frames</b><br>"
            "Select a directory of .tif/.tiff files — the model runs over every frame "
            "in sorted order and writes <i>lamella_thickness.csv</i> alongside them.")
        self._lamella_batch_btn.clicked.connect(self._lamella_run_batch)
        self._lamella_batch_progress = QProgressBar()
        self._lamella_batch_progress.setRange(0, 100)
        self._lamella_batch_progress.setValue(0)
        self._lamella_batch_progress.setFixedHeight(6)
        self._lamella_batch_progress.setTextVisible(False)
        self._lamella_batch_progress.setStyleSheet(
            f"QProgressBar {{ background-color:{CLR_INPUT}; border:none; border-radius:3px; }}"
            f"QProgressBar::chunk {{ background-color:{CLR_GREEN}; border-radius:3px; }}"
        )
        self._lamella_batch_progress.setVisible(False)
        self._lamella_save_masks_cb = QCheckBox("Output masks")
        self._lamella_save_masks_cb.setToolTip(
            "Save a 2-panel image for each frame: original crop | masked overlay with probe lines")
        lam_batch_rl.addWidget(self._lamella_batch_btn)
        lam_batch_rl.addWidget(self._lamella_save_masks_cb)
        lam_batch_rl.addWidget(self._lamella_batch_progress, stretch=1)
        c_lam.layout().addWidget(lam_batch_row)

        vl.addWidget(c_lam)

        # ── CALIBRATION IMAGE card ────────────────────────────────────────────
        c2 = card(w)
        c2.layout().addWidget(section_label("CALIBRATION"))
        c2.layout().addWidget(separator())

        instr = QLabel("Scroll to zoom, right-drag to pan, double-click to reset view. "
                       "Click two points on a known distance, "
                       "enter the real-world distance in mm, then press Calculate.")
        instr.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        instr.setWordWrap(True)
        c2.layout().addWidget(instr)

        self._cal_image_widget = ClickableImageWidget()
        self._cal_image_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._cal_image_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cal_image_widget.setStyleSheet(f"""
            background-color: {CLR_INPUT};
            border-radius: 8px;
            color: {CLR_TEXT_SEC};
            font-size: 12px;
        """)
        self._cal_image_widget.setText("Load a photo to begin calibration")
        self._cal_image_widget.pointsChanged.connect(self._cal_on_points_changed)
        c2.layout().addWidget(self._cal_image_widget)

        self._cal_point_status = QLabel("Point 1: not set  |  Point 2: not set")
        self._cal_point_status.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        c2.layout().addWidget(self._cal_point_status)

        self._cal_dist_entry = QLineEdit()
        self._cal_dist_entry.setPlaceholderText("e.g. 10.0")
        c2.layout().addWidget(input_row("Distance (mm):", self._cal_dist_entry, label_width=110))

        calc_btn_row = QWidget()
        cbr = QHBoxLayout(calc_btn_row); cbr.setContentsMargins(0,0,0,0); cbr.setSpacing(8)
        self._cal_reset_btn = ghost_button("Reset Points")
        self._cal_reset_btn.setFixedHeight(36)
        self._cal_reset_btn.setToolTip(
            "<b>Reset calibration points</b><br>"
            "1. Clears both click-points from the image<br>"
            "2. Resets the point status labels<br>"
            "3. Ready for a fresh selection")
        self._cal_reset_btn.clicked.connect(self._cal_reset_points)
        self._cal_calc_btn = accent_button("Calculate px/mm", CLR_ACCENT)
        self._cal_calc_btn.setFixedHeight(36)
        self._cal_calc_btn.setEnabled(False)
        self._cal_calc_btn.setToolTip(
            "<b>Calculate px/mm</b><br>"
            "1. Measures the pixel distance between the two selected points<br>"
            "2. Divides by the real-world distance entered above<br>"
            "3. Stores the px/mm result for use in analysis<br>"
            "Enabled once both points are placed")
        self._cal_calc_btn.clicked.connect(self._cal_calculate)
        cbr.addWidget(self._cal_reset_btn)
        cbr.addStretch()
        cbr.addWidget(self._cal_calc_btn)
        c2.layout().addWidget(calc_btn_row)

        self._cal_result_lbl = QLabel("Pixels/mm:  –")
        self._cal_result_lbl.setStyleSheet(
            f"color:{CLR_TEXT}; font-size:14px; font-weight:600;")
        c2.layout().addWidget(self._cal_result_lbl)

        vl.addWidget(c2)
        vl.addStretch()
        scroll.setWidget(w); return scroll

    # ── Cone tab ──────────────────────────────────────────────────────────────

    # The four extreme frames, in the order they are stacked in the tab.
    # (summary key, sub-key, heading, what the reader should take from it)
    EXTREME_PANELS = (
        ("d32_extreme_frames", "lowest",
         "LOWEST D32 — finest atomisation in the run",
         "The finest spray the run produced."),
        ("d32_extreme_frames", "highest",
         "HIGHEST D32 — coarsest atomisation in the run",
         "The coarsest. The lowest/highest ratio is the frame-to-frame swing."),
        ("atomised_extreme_frames", "highest",
         "HIGHEST atomised fraction",
         "Often degenerate: a frame with no un-atomised liquid reads 100% by "
         "construction. Check the un-atomised area before believing it."),
        ("atomised_extreme_frames", "lowest",
         "LOWEST atomised fraction",
         "Mostly unbroken liquid — threads and lamellae, little droplet area."),
    )

    # Four more (Ben, 2026-10-13), from measure_run's droplets_<thr>/extreme_frames_more/index.json
    # (also back-filled for the CCD day by render_more_extremes.py). (index key, heading, what it shows)
    MORE_EXTREME_PANELS = (
        ("most_in_focus", "MOST IN-FOCUS DROPLETS",
         "The frame where the most droplets were sharp enough to size."),
        ("most_total", "MOST DROPLETS IN TOTAL",
         "In focus and out of focus: the densest spray of the run."),
        ("mean_d_lowest", "SMALLEST MEAN DIAMETER",
         "Among frames with at least half the run's typical (median) count of in-focus droplets, "
         "never fewer than 10, so a thin frame's chance mean is not 'the smallest'."),
        ("mean_d_highest", "LARGEST MEAN DIAMETER",
         "Among frames with at least half the run's typical count of in-focus droplets (never "
         "fewer than 10): a thin frame that caught a few big drops is not 'the coarsest'."),
    )

    def _build_extremes_tab(self):
        """Full-resolution views of the four extreme frames of the last run.

        Shown at native resolution in a scroll area rather than scaled to fit:
        the point is to look at individual droplets and filament edges, which a
        390 px thumbnail cannot show. The per-frame numbers sit above each
        image so a degenerate frame is identifiable without cross-referencing
        per_frame.csv.
        """
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        w = QWidget(); vl = QVBoxLayout(w)
        vl.setSpacing(16); vl.setContentsMargins(16, 16, 16, 16)

        # ── Whole-run numbers ─────────────────────────────────────────────────
        # measure_run's pooled values over every analysed frame -- not any one
        # of the extreme frames below.
        summary = card()
        summary.layout().addWidget(section_label("WHOLE RUN"))

        metrics_row = QWidget()
        mr = QHBoxLayout(metrics_row); mr.setContentsMargins(0, 0, 0, 0); mr.setSpacing(16)
        self._ai_diameter_lbl   = QLabel("Run SMD: –")
        self._ai_dl_lbl         = QLabel("Atomised Fraction: –")
        for lbl in [self._ai_diameter_lbl, self._ai_dl_lbl]:
            lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 14px; font-weight:600;")
            mr.addWidget(lbl)
        mr.addStretch()
        summary.layout().addWidget(metrics_row)

        # The CI line gets its own full-width row: sharing a horizontal row
        # with the two headline numbers left it about 40 characters short, so
        # the droplet count fell off the right-hand edge.
        self._ai_confidence_lbl = QLabel("Confidence: –")
        self._ai_confidence_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 11px;")
        self._ai_confidence_lbl.setWordWrap(True)
        summary.layout().addWidget(self._ai_confidence_lbl)

        self._pipeline_status = QLabel("")
        self._pipeline_status.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 11px;")
        self._pipeline_status.setWordWrap(True)
        summary.layout().addWidget(self._pipeline_status)
        vl.addWidget(summary)

        self._extreme_hint = QLabel(
            "No run analysed yet — these populate when the AI chain finishes.")
        self._extreme_hint.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._extreme_hint.setWordWrap(True)
        vl.addWidget(self._extreme_hint)

        self._extreme_labels = {}      # (key, sub) -> (caption QLabel, image QLabel)
        for key, sub, heading, why in self.EXTREME_PANELS:
            c = card()
            c.layout().addWidget(section_label(heading))

            why_lbl = QLabel(why)
            why_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
            why_lbl.setWordWrap(True)
            c.layout().addWidget(why_lbl)

            cap = QLabel("–")
            cap.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px; font-weight:600;")
            cap.setWordWrap(True)
            c.layout().addWidget(cap)

            # Scaled to the tab width rather than shown at native resolution:
            # a 2560x1600 frame meant scrolling in two directions to see one
            # image. The full-resolution file is on disk and its path is under
            # each image, for when the detail actually matters.
            img = _FitImageLabel()
            img.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
            img.clearImage("not available")
            c.layout().addWidget(img)

            path_lbl = _ElidingLabel("")
            path_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px;")
            c.layout().addWidget(path_lbl)

            self._extreme_labels[(key, sub)] = (cap, img, path_lbl)
            vl.addWidget(c)

        self._more_extreme_labels = {}     # index key -> (caption, image, path)
        for key, heading, why in self.MORE_EXTREME_PANELS:
            c = card()
            c.layout().addWidget(section_label(heading))
            why_lbl = QLabel(why)
            why_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
            why_lbl.setWordWrap(True)
            c.layout().addWidget(why_lbl)
            cap = QLabel("–")
            cap.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px; font-weight:600;")
            cap.setWordWrap(True)
            c.layout().addWidget(cap)
            img = _FitImageLabel()
            img.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
            img.clearImage("not available")
            c.layout().addWidget(img)
            path_lbl = _ElidingLabel("")
            path_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px;")
            c.layout().addWidget(path_lbl)
            self._more_extreme_labels[key] = (cap, img, path_lbl)
            vl.addWidget(c)

        vl.addStretch()
        scroll.setWidget(w)
        return scroll

    def _update_extremes_tab(self, results: dict):
        """Fill the Extremes tab from a finished run.

        Prefers the CLASSICAL pass (liquid_<thr>/extreme_images/): un-atomised
        liquid filled orange, droplets ringed green (in focus) or magenta (out
        of focus, including those the 2.2.0 sharpness rule moved), and its
        extremes are picked from the quoted classical atomised fraction. Falls
        back to measure_run's images for runs without a classical pass.
        """
        cls = results.get("_classical") or {}
        cdir = cls.get("_liquid_dir")
        if cdir and (cls.get("d32_extreme_frames") or cls.get("atomised_extreme_frames")):
            src, img_dir = cls, os.path.join(cdir, "extreme_images")
            source = "classical pass"
        else:
            src, img_dir = results, results.get("_measurement_dir")
            source = "measure_run (no classical pass for this run)"
        found = 0
        for key, sub, _heading, _why in self.EXTREME_PANELS:
            cap, img, path_lbl = self._extreme_labels[(key, sub)]
            ext = (src.get(key) or {}).get(sub) or {}
            stem = ext.get("frame")
            if not stem:
                cap.setText("– (not reported for this run)")
                img.clearImage("not available")
                path_lbl.setText("")
                continue

            if "d32_um" in ext:
                bits = [f"D32 {ext['d32_um']} µm",
                        f"{ext.get('droplets_in_focus', '?')} in-focus droplets"]
                if "atomised_pct" in ext:
                    bits.append(f"atomised {ext['atomised_pct']} %")
            elif "unatomised_px" in ext:                       # classical entry
                un_mm2 = ext["unatomised_px"] * 1e-4           # 10 um/px -> 1e-4 mm^2/px
                bits = [f"atomised {ext['atomised_pct']} %",
                        f"{ext.get('droplets', '?')} droplets",
                        f"un-atomised liquid {un_mm2:.2f} mm² in "
                        f"{ext.get('n_components', '?')} piece(s)"]
                if ext["unatomised_px"] == 0:
                    bits.append("⚠ no un-atomised liquid — 100% by construction")
            else:                                              # measure_run entry
                fil = ext.get("filaments")
                bits = [f"atomised {ext['atomised_pct']} % (model-only)",
                        f"{ext.get('droplets', '?')} droplets",
                        f"{fil} filaments"]
                if fil == 0:
                    bits.append("⚠ zero filaments — ratio is 1 by construction")
            cap.setText(f"{stem}   ·   " + "   ·   ".join(str(b) for b in bits))

            path = os.path.join(img_dir, f"{stem}.png") if img_dir else None
            if path and os.path.exists(path):
                pix = QPixmap(path)
                if not pix.isNull():
                    img.setSourcePixmap(pix)
                    path_lbl.setText(f"{path}   ({pix.width()}×{pix.height()} full size)")
                    found += 1
                    continue
            img.clearImage(f"image not found: {path}")
            path_lbl.setText(path or "")

        self._update_more_extremes(results.get("_measurement_dir"))
        legend = ("orange = un-atomised liquid, green = in-focus droplet, magenta = out of "
                  "focus" if source == "classical pass" else
                  "green = in-focus droplet, magenta = out of focus")
        if found:
            self._extreme_hint.setText(
                f"From {os.path.basename(results.get('_run_dir', '') or '')} — "
                f"{results.get('_frames', '?')} frames at stride "
                f"{results.get('_stride', '?')}. Images from the {source}: {legend}.")
        else:
            self._extreme_hint.setText(
                "Run finished but no marked-up images were found — "
                "measure_run needs --images (process_capture passes it by default).")

    def _update_more_extremes(self, mdir) -> int:
        """The four count / mean-diameter extremes from <droplets dir>/extreme_frames_more/index.json;
        the number of images shown. Runs measured before 2026-10-13 have no index (unless back-filled)."""
        frames, note = {}, ""
        folder = os.path.join(mdir, "extreme_frames_more") if mdir else None
        try:
            with open(os.path.join(folder, "index.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            frames = {f["key"]: f for f in data.get("frames", []) if isinstance(f, dict) and f.get("key")}
            note = data.get("note") or ""
        except (OSError, ValueError, TypeError, AttributeError):
            note = "measured before these frames were added"
        shown = 0
        for key, _heading, _why in self.MORE_EXTREME_PANELS:
            cap, img, path_lbl = self._more_extreme_labels[key]
            e = frames.get(key)
            if not e:
                cap.setText("– (not available for this run" + (f": {note}" if note else "") + ")")
                img.clearImage("not available")
                path_lbl.setText("")
                continue
            bits = [f"{e.get('value')} {e.get('unit', '')}".strip(),
                    f"{e.get('droplets_in_focus', '?')} in focus, {e.get('droplets_total', '?')} in total"]
            if e.get("mean_d_um") is not None:
                bits.append(f"mean {e['mean_d_um']} µm")
            if e.get("d32_um") is not None:
                bits.append(f"D32 {e['d32_um']} µm")
            cap.setText(f"{e.get('frame', '?')}   ·   " + "   ·   ".join(bits))
            path = os.path.join(folder, e["image"]) if e.get("image") else None
            pix = QPixmap(path) if path and os.path.exists(path) else None
            if pix is not None and not pix.isNull():
                img.setSourcePixmap(pix)
                path_lbl.setText(f"{path}   ({pix.width()}×{pix.height()} full size)")
                shown += 1
            else:
                img.clearImage(f"image not found: {path}" if path else "no image saved")
                path_lbl.setText(path or "")
        return shown

    def _build_cone_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w = QWidget(); vl = QVBoxLayout(w); vl.setSpacing(16); vl.setContentsMargins(16, 16, 16, 16)

        # ── Card 1: Live Feed ────────────────────────────────────────────────
        c1 = card()
        c1.layout().addWidget(section_label("LIVE FEED"))

        if not CV2_AVAILABLE:
            warn = QLabel("⚠  opencv-python (cv2) is not installed — webcam unavailable")
            warn.setStyleSheet(f"color:{CLR_ORANGE}; font-size:12px;")
            warn.setWordWrap(True)
            c1.layout().addWidget(warn)

        self._cone_feed_lbl = QLabel("No camera")
        self._cone_feed_lbl.setFixedHeight(300)
        self._cone_feed_lbl.setMinimumWidth(120)
        self._cone_feed_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cone_feed_lbl.setStyleSheet(
            f"background:{CLR_INPUT}; color:{CLR_TEXT_SEC}; border-radius:8px; font-size:13px;")
        feed_row = QWidget()
        feed_hl  = QHBoxLayout(feed_row)
        feed_hl.setContentsMargins(0, 0, 0, 0)
        feed_hl.addStretch()
        feed_hl.addWidget(self._cone_feed_lbl)
        feed_hl.addStretch()
        c1.layout().addWidget(feed_row)

        spin_style = f"background:{CLR_INPUT}; color:{CLR_TEXT}; border:1px solid {CLR_BORDER}; border-radius:6px; padding:4px;"

        self._cone_idx_spin = QSpinBox()
        self._cone_idx_spin.setRange(0, 9)
        self._cone_idx_spin.setValue(0)
        self._cone_idx_spin.setFixedWidth(60)
        self._cone_idx_spin.setStyleSheet(spin_style)
        c1.layout().addWidget(input_row("Camera index:", self._cone_idx_spin))

        cam_row = QWidget(); cam_hl = QHBoxLayout(cam_row); cam_hl.setContentsMargins(0,0,0,0); cam_hl.setSpacing(10)
        self._cone_start_cam_btn = accent_button("Start Camera")
        self._cone_start_cam_btn.clicked.connect(self._cone_start_camera)
        self._cone_start_cam_btn.setEnabled(CV2_AVAILABLE)
        self._cone_start_cam_btn.setToolTip(
            "<b>Start cone camera</b><br>"
            "1. Opens the webcam at the selected camera index<br>"
            "2. Starts the live cone-angle detection feed<br>"
            "3. Overlays the detected spray cone boundary in real time")
        self._cone_stop_cam_btn  = ghost_button("Stop Camera")
        self._cone_stop_cam_btn.clicked.connect(self._cone_stop_camera)
        self._cone_stop_cam_btn.setEnabled(False)
        self._cone_stop_cam_btn.setToolTip(
            "<b>Stop cone camera</b><br>"
            "1. Stops the live webcam feed<br>"
            "2. Releases the camera so other apps can use it")
        cam_hl.addWidget(self._cone_start_cam_btn)
        cam_hl.addWidget(self._cone_stop_cam_btn)
        cam_hl.addStretch()
        c1.layout().addWidget(cam_row)

        self._cone_cam_status_lbl = QLabel("Camera stopped")
        self._cone_cam_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        c1.layout().addWidget(self._cone_cam_status_lbl)

        c1.layout().addWidget(separator())
        c1.layout().addWidget(section_label("ANGLE HISTORY"))

        hist_row = QWidget()
        hist_hl = QHBoxLayout(hist_row)
        hist_hl.setContentsMargins(0, 4, 0, 4)
        hist_hl.setSpacing(8)

        THUMB_H = 150
        self._cone_hist_cells = []
        for _ in range(5):
            cell = QWidget()
            cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            cell_vl = QVBoxLayout(cell)
            cell_vl.setContentsMargins(0, 0, 0, 0)
            cell_vl.setSpacing(3)

            img_lbl = QLabel()
            img_lbl.setFixedHeight(THUMB_H)
            img_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setStyleSheet(
                f"background:{CLR_INPUT}; border:1px solid {CLR_BORDER}; border-radius:5px; color:{CLR_TEXT_SEC}; font-size:9px;")
            img_lbl.setText("–")

            ang_lbl = QLabel("–")
            ang_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ang_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px;")

            cell_vl.addWidget(img_lbl)
            cell_vl.addWidget(ang_lbl)
            hist_hl.addWidget(cell)
            self._cone_hist_cells.append((img_lbl, ang_lbl))
        c1.layout().addWidget(hist_row)

        c1.layout().addWidget(separator())
        c1.layout().addWidget(section_label("CROP REGION"))

        from PySide6.QtWidgets import QDoubleSpinBox
        self._cone_top_crop_spin = QDoubleSpinBox()
        self._cone_top_crop_spin.setRange(0.0, 0.5)
        self._cone_top_crop_spin.setSingleStep(0.01)
        self._cone_top_crop_spin.setDecimals(3)
        self._cone_top_crop_spin.setValue(0.05)
        self._cone_top_crop_spin.setFixedWidth(80)
        self._cone_top_crop_spin.setStyleSheet(spin_style)
        self._cone_top_crop_spin.setToolTip(
            "<b>Top crop ratio</b><br>"
            "Fraction of image height cropped from the top before analysis<br>"
            "The red band on the live feed shows the excluded region")
        self._cone_top_crop_spin.valueChanged.connect(self._save_camera_settings)
        crop_note = QLabel("Drag the spinner or type a value. The red band on the live feed shows the excluded region.")
        crop_note.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        crop_note.setWordWrap(True)
        c1.layout().addWidget(input_row("Top crop ratio:", self._cone_top_crop_spin))
        c1.layout().addWidget(crop_note)

        c1.layout().addWidget(separator())
        c1.layout().addWidget(section_label("FOCUS"))

        self._cone_autofocus_chk = QCheckBox("Auto-focus")
        self._cone_autofocus_chk.setChecked(True)
        self._cone_autofocus_chk.setStyleSheet(f"color:{CLR_TEXT}; font-size:13px;")
        self._cone_autofocus_chk.toggled.connect(self._cone_apply_focus)
        c1.layout().addWidget(self._cone_autofocus_chk)

        self._cone_focus_spin = QSpinBox()
        self._cone_focus_spin.setRange(0, 250)
        self._cone_focus_spin.setValue(0)
        self._cone_focus_spin.setFixedWidth(80)
        self._cone_focus_spin.setStyleSheet(spin_style)
        self._cone_focus_spin.setEnabled(False)  # disabled while auto-focus is on
        self._cone_focus_spin.editingFinished.connect(self._cone_apply_focus)
        self._cone_autofocus_chk.toggled.connect(
            lambda checked: self._cone_focus_spin.setEnabled(not checked)
        )
        focus_row = input_row("Manual focus (0–250):", self._cone_focus_spin)
        focus_note = QLabel("Note: focus control support depends on your webcam model")
        focus_note.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        focus_note.setWordWrap(True)
        c1.layout().addWidget(focus_row)
        c1.layout().addWidget(focus_note)

        vl.addWidget(c1)

        # ── Card 2: Capture & Results ────────────────────────────────────────
        c2 = card()
        c2.layout().addWidget(section_label("CAPTURE & RESULTS"))

        self._cone_capture_btn = accent_button("Manual Capture")
        self._cone_capture_btn.setEnabled(False)
        self._cone_capture_btn.setToolTip(
            "<b>Manual cone capture</b><br>"
            "1. Captures the current webcam frame<br>"
            "2. Runs cone-angle detection on it<br>"
            "3. Saves it as the result image for this run<br>"
            "Most recent capture always overwrites the previous one")
        self._cone_capture_btn.clicked.connect(self._cone_capture)
        c2.layout().addWidget(self._cone_capture_btn)

        self._cone_auto_status_lbl = QLabel("Auto-capture: inactive")
        self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        c2.layout().addWidget(self._cone_auto_status_lbl)

        c2.layout().addWidget(separator())

        self._cone_result_img_lbl = QLabel()
        self._cone_result_img_lbl.setFixedSize(500, 300)
        self._cone_result_img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cone_result_img_lbl.setStyleSheet(
            f"background:{CLR_INPUT}; color:{CLR_TEXT_SEC}; border-radius:8px; font-size:13px;")
        self._cone_result_img_lbl.setText("No capture yet")
        self._cone_result_img_lbl.setVisible(False)
        c2.layout().addWidget(self._cone_result_img_lbl)

        self._cone_angle_lbl = QLabel("")
        self._cone_angle_lbl.setStyleSheet(
            f"color:{CLR_TEXT}; font-size:20px; font-weight:700;")
        self._cone_angle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cone_angle_lbl.setVisible(False)
        c2.layout().addWidget(self._cone_angle_lbl)

        self._cone_saved_lbl = QLabel("")
        self._cone_saved_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        self._cone_saved_lbl.setWordWrap(True)
        self._cone_saved_lbl.setVisible(False)
        c2.layout().addWidget(self._cone_saved_lbl)

        vl.addWidget(c2)
        vl.addStretch()
        scroll.setWidget(w); return scroll

    # ── How To tab ────────────────────────────────────────────────────────────

    def _build_how_to_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        w = QWidget()
        vl = QVBoxLayout(w); vl.setContentsMargins(20,20,20,20); vl.setSpacing(14)

        sections = [
            ("LAYOUT", [
                ("Header",
                 "Left to right: LaCie (green when the drive is found), the last saved run "
                 "(click it to open the folder) and the folder the next run will go to "
                 "(orange if it already exists), the calibrated px/mm, then the Portenta, "
                 "Camera, AFG, live pressure (barA) and MFC indicators, and the run timer. "
                 "The Camera box is outlined orange while armed and green while a "
                 "trigger is saving."),
                ("Left panel",
                 "Live Camera View with its own Connect, Ping and Live Feed buttons (the "
                 "same feed as the Calibration tab). Below it the live Mass Flow and "
                 "Pressure graphs from the Alicat (last 60 s). Smooth applies an EMA to "
                 "both traces on screen only; the saved data is always raw. At the bottom, "
                 "STOP EVERYTHING."),
                ("Tabs",
                 "Hardware (connections, bubbler RPM, gas flow, traverse), Materials, "
                 "Camera, AFG1062, Calibration, Cone and Extremes. This page is the How "
                 "To button at the top right."),
                ("Right panel and bottom bar",
                 "Right: Nozzle (orifice, bubbler height), Notes with Save to Excel, and "
                 "the Console log. Bottom: status message, GLR, Volume, the Motor Travel "
                 "bar, START EXPERIMENT and a second camera Trigger."),
            ]),
            ("CONNECTING", [
                ("Portenta (traverse / silicone feed)",
                 "Connects by itself at launch when a Portenta port is found; otherwise "
                 "pick the port on the Hardware tab and click Connect. The board homes "
                 "once at start-up and Connect waits for it, which can take up to a "
                 "minute. A failed home shows HOMING FAILED and the reason in the status "
                 "bar. The Homed dot only turns green after you press Home in this "
                 "session, so Home before the first run."),
                ("Arduino Uno (bubbler spin motor)",
                 "Also connects by itself when an Uno is found. Enter the RPM and click "
                 "Spin (it becomes Stop; click again to stop). The actual RPM is shown "
                 "beside it. SG goes amber as an early warning and red at the "
                 "firmware's stall threshold; on a stall the board stops the motor itself "
                 "and SG stays red until the next Spin. SG is grey while stopped or below "
                 "60 RPM. OTPW = driver running hot, OT = driver has shut itself off. "
                 "Current reading about half while idle is normal."),
                ("Alicat MFC (gas)",
                 "Connects by itself at launch on the last port used (COM4 by default) "
                 "and sets 0 sccm. Enter a target (0 – 12000 sccm) and click Set Flow; "
                 "Set last flow re-sends the previous setpoint; Gas Flow Off zeroes it. "
                 "Mass flow, setpoint, pressure and temperature update every 0.2 s and "
                 "feed the graphs and the header."),
                ("Phantom camera",
                 "Windows + Phantom SDK only. Connect and Ping on the Camera tab or the "
                 "Live Camera View. Set FPS, size, Pre-/Post-trigger (s) and exposure; the "
                 "RAM CAPACITY box shows how long the camera can hold at those settings. "
                 "Tick Save video (.cine) and/or Save TIFFs (one must stay on). Apply "
                 "Config pushes the settings, Arm starts the ring buffer, Trigger saves "
                 "the pre + post window and re-arms by itself, Disarm / Abort stops "
                 "buffering and clears the camera RAM."),
                ("Standard capture settings",
                 "If any capture field differs from the campaign standard (390 fps, 4 µs, "
                 "2048×1152, 0 s pre, 13 s post, stride 10), START EXPERIMENT asks first: "
                 "Use standard settings, Keep mine, or Cancel."),
                ("AFG1062",
                 "Pick CH1 or CH2, Connect, set Pulse Duration (s), Apply Config, then "
                 "Test Fire for a single pulse. It is stand-alone: START EXPERIMENT does "
                 "not fire it."),
            ]),
            ("SAFETY", [
                ("STOP EVERYTHING",
                 "Stops the traverse (Portenta), stops the bubbler motor (Uno) and zeroes "
                 "the gas setpoint, each independently, so one device missing or failing "
                 "cannot block the others. It also cancels a pending auto-trigger. It "
                 "does not touch the camera."),
                ("Pressure cut-off",
                 "The Cut-off barA box under Gas Flow Off. If the raw Alicat pressure "
                 "(absolute, about gauge + 1 bar) reaches it, STOP EVERYTHING fires "
                 "automatically and a warning appears. Status reads Off, Armed, TRIPPED, "
                 "or NO DATA when there are no live Alicat readings (it cannot fire then, "
                 "so START is refused while it is set). It fires once, then re-arms when "
                 "the pressure falls below 90% of the cut-off. Empty or 0 switches it "
                 "off. Remembered between sessions."),
                ("Alicat readings lost",
                 "If the Alicat stops sending readings for 2 s, or its connection drops, "
                 "the console turns red and the header pressure reads 'no data'. During a "
                 "run, STOP EVERYTHING fires and the run is marked stopped. Set Flow and "
                 "START are refused until it is reconnected. Close the gas at the valve "
                 "if in doubt: with no connection, Gas Flow Off cannot reach the unit."),
                ("Front limit switch",
                 "The front optical switch on the traverse is an absolute stop. The "
                 "Portenta halts the motor the moment it is reached, in any move or jog, "
                 "whatever the step count says, and refuses to drive further forward "
                 "while it is triggered; you can always drive back off it. The GUI fires "
                 "STOP EVERYTHING, ends the run and marks it stopped. Check switches (Motor "
                 "card) logs both switches: each should read LOW with the beam clear and "
                 "HIGH with it blocked. Check the front one before relying on it."),
                ("Re-home after any emergency stop",
                 "After STOP EVERYTHING, the pressure cut-off or the front limit switch, "
                 "press Home before the next move. The travel counter can be wrong after "
                 "an interrupted move."),
                ("Watchdog",
                 "If the Portenta never reports the traverse finished (move time + 30 s), "
                 "the GUI stops the traverse, bubbler and gas, and saves the run marked "
                 "stopped."),
            ]),
            ("MOTOR (TRAVERSE)", [
                ("Speed and Motor Travel",
                 "Speed is in steps/s (6800 steps/mm), with the matching mL/min shown "
                 "beside it. Motor Travel is the stroke in mm, with its volume beside it. "
                 "Both feed the GLR."),
                ("Home, Move, Jog",
                 "Home drives to the back switch and zeroes the counter. Move travels "
                 "Motor Travel at Speed. Hold the ↑ / ↓ buttons to jog at Speed; release "
                 "to stop; a jog also stops at the travel limit. Move and Start are "
                 "refused if they would take the traverse past "
                 f"{AtomisationApp.MAX_MOTOR_MM} mm from home."),
                ("Speed 0 (static run)",
                 "START with Speed 0 runs the gas, logging (and the bubbler, if spinning) "
                 "with no traverse move. It has no end of its own: finish it with STOP "
                 "EVERYTHING (or the cut-off); it is saved as a static run."),
                ("Motor Travel bar",
                 f"Bottom bar: position out of {AtomisationApp.MAX_MOTOR_MM} mm. Turns "
                 "orange at 70% and red at 90%, with the remaining mm shown. Volume "
                 "beside it is the silicone used so far. Home to reset it."),
            ]),
            ("RUNNING AN EXPERIMENT", [
                ("1. Set the conditions",
                 "Materials tab: fluid and gas densities plus the Fluid and Gas tags (the "
                 "GLR is NOT SET without the densities). Nozzle: orifice, orifice length "
                 "(the exit bore's length: update it when an insert of another length goes "
                 "in) and bubbler height (hardware states, so only change them when the "
                 "hardware changes). "
                 "Hardware tab: target flow, RPM, Speed and Motor Travel. START does not "
                 "spin the bubbler: click Spin first."),
                ("2. START EXPERIMENT",
                 "Needs the Portenta. Creates the run folder, sets the gas to the target "
                 "flow, starts logging pressure and flow and the run timer, and sends the "
                 "traverse move 0.5 s later. If the cone webcam is running, it takes one "
                 "cone capture 5 s in. If the previous run was not saved you are asked "
                 "first."),
                ("3. Auto-trigger at end of test",
                 "Tickbox beside Disarm / Abort on the Camera tab. On START it arms the "
                 "camera if needed and fires at: test length − 2 s − Post-trigger, so the "
                 "saved video covers the last part of the test and ends 2 s before the "
                 "traverse stops (test length = Motor Travel × 6800 / Speed). If the test "
                 "is too short you can Trigger early, Start without, or Cancel. A "
                 "countdown shows under the camera buttons."),
                ("4. Manual trigger",
                 "Trigger in the bottom bar or on the Camera tab, or press Space. Works "
                 "only while the camera is armed. Space is ignored while you are typing in "
                 "a text box. Press C for a cone capture (cone webcam running)."),
                ("5. Window check",
                 "Camera tab, WINDOW CHECK. Wipe the window, backlight on, nothing in view, "
                 "and click Save clean reference (again whenever the camera, lens or "
                 "backlight moves). With Check at Start Experiment ticked, START compares "
                 "the live view with it first: new dark spots (a drop on the window) are "
                 "shown boxed, and you wipe and Start again or start anyway. The result is "
                 "in run_summary.xlsx as 'Window check (before run)'. A drop on the window "
                 "is measured as un-atomised liquid."),
            ]),
            ("END OF RUN", [
                ("Automatic save",
                 "When the traverse finishes, the bubbler and gas are stopped and the run "
                 "is saved: a folder on the LaCie under Experiments/YYYY/MM/DD/<run id> "
                 "(time_flow_rpm_speed_orifice_bubbler-height), run_summary.xlsx with "
                 "the pressure and flow data and graphs, and a row in "
                 "Experiments/Logs/master_log.xlsx. Camera windows are shaded red on the "
                 "graphs."),
                ("Runs stopped early",
                 "Runs ended by STOP EVERYTHING, the pressure cut-off, the front limit "
                 "switch, a traverse or bubbler stall, lost Alicat readings or the "
                 "watchdog are still saved, and marked: 'Run status' in run_summary.xlsx "
                 "reads STOPPED and the reason, and the master_log Notes start with ⚠ "
                 "STOPPED. Motor Travel is credited only with the distance covered."),
                ("Notes and the next run",
                 "Type Notes after the run and click Save to Excel: it updates the same "
                 "row, never adds a second one. The run's conditions are recorded as they "
                 "were at START, so you can already type the next run's values and still "
                 "re-save Notes for the last one."),
            ]),
            ("ANALYSIS AND OTHER TABS", [
                ("AI analysis (optional)",
                 "Tick Run AI analysis after capture on the Camera tab and set the Stride "
                 "(analyse every Nth frame; the note shows frames and expected time). It "
                 "runs on the saved .cine, so Save video must be ticked: frame "
                 "extraction, detection, then D32 and atomised fraction into "
                 "shadowgraph/analysis/. The run's row is re-saved with the results. "
                 "Full Analyse Cine runs the same chain on any .cine without touching "
                 "master_log."),
                ("Extremes",
                 "Fills in when the AI finishes: the WHOLE RUN numbers (Run SMD, "
                 "atomised fraction, confidence), then the lowest and highest D32 and "
                 "highest and lowest atomised-fraction frames, then the frames with the "
                 "most in-focus droplets, the most droplets in total, and the smallest and "
                 "largest mean diameter (among frames with at least half the run's typical "
                 "count of in-focus droplets, never fewer than 10). "
                 "Green = in-focus droplet, magenta = out of focus, orange = un-atomised "
                 "liquid."),
                ("Calibration (px/mm)",
                 "Start Feed and Use as Calibration Image, or Load from File. Scroll to "
                 "zoom, right-drag to pan, double-click to reset. Click two points a "
                 "known distance apart, enter the distance in mm and Calculate px/mm. "
                 "The value goes in the header and is remembered. The Lamella Analysis "
                 "card is on this tab too."),
                ("Cone",
                 "Pick the webcam index and Start Camera. Set the top crop (red band on "
                 "the feed) and focus. Manual Capture (or C) runs the cone-angle fit; the "
                 "annotated image goes into the run's cone/ folder, the last five show in "
                 "the history strip, and the run's cone image goes into master_log."),
                ("Running on macOS",
                 "Layout work only: the Phantom camera needs Windows and its SDK, so the "
                 "camera buttons are disabled on the Mac."),
            ]),
        ]

        for section_title, items in sections:
            c = card(w)
            c.layout().addWidget(section_label(section_title))
            c.layout().addWidget(separator())
            for step_title, step_body in items:
                title_lbl = QLabel(step_title)
                title_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:13px; font-weight:600;")
                c.layout().addWidget(title_lbl)
                body_lbl = QLabel(step_body)
                body_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
                body_lbl.setWordWrap(True)
                c.layout().addWidget(body_lbl)
            vl.addWidget(c)

        vl.addStretch()
        scroll.setWidget(w); return scroll

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {CLR_PANEL};
                border-top: 1px solid {CLR_BORDER};
            }}
        """)
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(16)

        self._status_dot = dot_indicator(CLR_TEXT_SEC, 12)
        self._status_lbl = QLabel("Awaiting input...")
        self._status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:13px;")
        hl.addWidget(self._status_dot)
        hl.addWidget(self._status_lbl)
        hl.addStretch()

        # ── Motor travel + Volume ─────────────────────────────────────────────
        # Compact versions of the old left-panel cards, sized to the 56 px bar.
        # Plain QWidgets rather than card(): the bar's own "QFrame { ... }" rule
        # would cascade a border-top onto any QFrame child.
        travel_box = QWidget()
        travel_box.setFixedSize(210, 38)    # 14 title + 6 bar + 12 warning + spacing
        travel_box.setStyleSheet("background: transparent;")
        tvl = QVBoxLayout(travel_box)
        tvl.setContentsMargins(0, 0, 0, 0)
        tvl.setSpacing(3)

        travel_hdr = QWidget()
        travel_hdr.setStyleSheet("background: transparent;")
        thl = QHBoxLayout(travel_hdr)
        thl.setContentsMargins(0, 0, 0, 0)
        thl.setSpacing(6)
        _travel_title = QLabel("Motor Travel")
        _travel_title.setStyleSheet(f"color:{CLR_TEXT}; font-size:11px; font-weight:600;")
        self._travel_label = QLabel(f"0.0 / {self.MAX_MOTOR_MM} mm")
        self._travel_label.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        thl.addWidget(_travel_title)
        thl.addStretch()
        thl.addWidget(self._travel_label)
        tvl.addWidget(travel_hdr)

        self._travel_bar = QProgressBar()
        self._travel_bar.setRange(0, 1000)
        self._travel_bar.setValue(0)
        self._travel_bar.setTextVisible(False)
        self._travel_bar.setFixedHeight(6)
        tvl.addWidget(self._travel_bar)

        # Fixed height so the bar above doesn't shift when the warning appears
        self._travel_warning = QLabel("")
        self._travel_warning.setStyleSheet(f"color:{CLR_ORANGE}; font-size:10px;")
        self._travel_warning.setFixedHeight(12)
        tvl.addWidget(self._travel_warning)
        # travel_box is added to the bar AFTER GLR and Volume (below), so the
        # read-outs sit to the left and Motor Travel sits beside the controls.

        # GLR, immediately left of Volume and styled to match it. Both are
        # derived read-outs rather than set points, so they belong together.
        glr_box = QWidget()
        glr_box.setFixedSize(72, 38)
        glr_box.setStyleSheet("background: transparent;")
        gvl = QVBoxLayout(glr_box)
        gvl.setContentsMargins(0, 0, 0, 0)
        gvl.setSpacing(3)
        _glr_title = QLabel("GLR")
        _glr_title.setStyleSheet(f"color:{CLR_TEXT}; font-size:11px; font-weight:600;")
        _glr_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glr_lbl = QLabel("–")
        self._glr_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:13px; font-weight:700;")
        self._glr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glr_box.setToolTip(
            "<b>Gas-to-liquid mass ratio</b> (dimensionless)<br>"
            "gas mass = flow (sccm) × gas density<br>"
            "liquid mass = motor flow (mL/min) × fluid density<br>"
            "Set both densities in the <b>Materials</b> tab.")
        gvl.addWidget(_glr_title)
        gvl.addWidget(self._glr_lbl)
        hl.addWidget(glr_box, 0, Qt.AlignmentFlag.AlignVCenter)

        vol_box = QWidget()
        vol_box.setFixedSize(72, 38)
        vol_box.setStyleSheet("background: transparent;")
        vvl = QVBoxLayout(vol_box)
        vvl.setContentsMargins(0, 0, 0, 0)
        vvl.setSpacing(3)
        _vol_title = QLabel("Volume")
        _vol_title.setStyleSheet(f"color:{CLR_TEXT}; font-size:11px; font-weight:600;")
        _vol_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vol_label = QLabel("0.00 mL")
        self._vol_label.setStyleSheet(f"color:{CLR_TEXT}; font-size:13px; font-weight:700;")
        self._vol_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vvl.addWidget(_vol_title)
        vvl.addWidget(self._vol_label)
        hl.addWidget(vol_box, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addWidget(travel_box, 0, Qt.AlignmentFlag.AlignVCenter)

        _sb_sep = QFrame()
        _sb_sep.setFixedSize(1, 32)
        _sb_sep.setStyleSheet(f"background-color:{CLR_BORDER}; border:none;")
        hl.addWidget(_sb_sep)

        self._start_btn = accent_button("▶  START EXPERIMENT", CLR_GREEN)
        self._start_btn.setFixedSize(200, 40)
        self._start_btn.setToolTip(
            "<b>Start experiment</b><br>"
            "1. Sets the AliCat to the target flow (sccm)<br>"
            "2. Starts logging mass flow and pressure<br>"
            "3. Triggers the AFG pulse (atomiser)<br>"
            "4. Captures video with the Phantom camera<br>"
            "5. Runs Dennis AI analysis (if checkbox ticked)<br>"
            "6. Saves all results and metrics to Excel")
        self._start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {CLR_GREEN};
                color: #000000;
                border: none;
                border-radius: 10px;
                padding: 8px 20px;
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{ background-color: #26b84e; }}
            QPushButton:pressed {{ background-color: #1e9940; }}
        """)
        self._start_btn.clicked.connect(self._start_experiment)
        hl.addWidget(self._start_btn)

        # A second Trigger, so the camera can be fired from this screen as well
        # as the Camera tab. Same handler, and its enabled state is driven by
        # _set_trigger_enabled() together with the Camera tab's button, so it
        # is live only while the camera is armed.
        self._bar_trigger_btn = accent_button("● Trigger", CLR_RED)
        self._bar_trigger_btn.setFixedSize(120, 40)
        self._bar_trigger_btn.setEnabled(False)   # enabled only when armed
        self._bar_trigger_btn.setToolTip(
            "<b>Trigger camera</b> — same as the Camera tab's Trigger<br>"
            "Live only while the camera is armed (Arm it in the Camera tab).<br>"
            "Space bar also triggers, when no text box has focus.")
        self._bar_trigger_btn.clicked.connect(self._cam_trigger)
        hl.addWidget(self._bar_trigger_btn)

        self._exp_progress = QProgressBar()
        self._exp_progress.setRange(0, 0)   # indeterminate by default
        self._exp_progress.setFixedHeight(10)
        self._exp_progress.setTextVisible(False)
        self._exp_progress.setVisible(False)
        self._exp_progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {CLR_INPUT};
                border: none;
                border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background-color: {CLR_GREEN};
                border-radius: 5px;
            }}
        """)
        hl.addWidget(self._exp_progress)
        return bar

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Arduino
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_port(text: str) -> str:
        """Strip the description suffix from a combo entry like 'COM3 — Arduino Uno'."""
        return text.split(" — ")[0].strip()

    def _get_serial_ports(self, prefer=None):
        """Return "COMx — description" labels for the available serial ports.

        prefer: optional predicate taking a pyserial ListPortInfo.  Matching
        ports are moved to the front of the list so the right device is the
        dropdown's default selection.  The sort is stable, so everything else
        keeps its original order.
        """
        import re
        entries = []
        for p in serial.tools.list_ports.comports():
            dev  = p.device
            desc = (p.description or "").strip()
            lower_desc = desc.lower()
            if dev.upper().startswith("COM") or "usb" in lower_desc or "serial" in lower_desc:
                if desc and desc != dev:
                    # Windows appends "(COMx)" to the description — strip it since we show the port separately
                    desc_clean = re.sub(r'\s*\(COM\d+\)\s*$', '', desc, flags=re.IGNORECASE).strip()
                    entries.append((f"{dev} — {desc_clean}", p))
                else:
                    entries.append((dev, p))
        if prefer is not None:
            entries.sort(key=lambda e: not prefer(e[1]))
        return [label for label, _ in entries]

    # Arduino Uno USB identifiers, matched as exact VID:PID pairs.
    # Vendor ID alone is NOT enough: the Portenta H7 is also an Arduino board
    # and shares vendor 0x2341 (it enumerates as 2341:025b), so a VID-only test
    # matches the traverse controller too.  Clones typically present a CH340
    # bridge instead, hence the description fallback.  No FTDI entry here —
    # the Alicat MFC is an FT232 and must never match.
    UNO_IDS = (
        (0x2341, 0x0043),   # Uno R3
        (0x2341, 0x0001),   # Uno (original)
        (0x2341, 0x0243),   # Uno R3 variant
        (0x2A03, 0x0043),   # Arduino srl Uno
        (0x1A86, 0x7523),   # CH340 clone
        (0x1A86, 0x7522),   # CH340 clone
    )
    UNO_DESC_HINTS = ("arduino uno", "ch340", "ch341", "usb2.0-serial")

    # Portenta H7 (traverse controller), also matched as exact VID:PID pairs.
    # It shares Arduino's vendor 0x2341 with the Uno, so only the product ID
    # separates them.  Windows binds it to the generic CDC driver, so it shows
    # up as "USB Serial Device" by "Microsoft" — the description carries no
    # useful identity, which is why the ID table has to do the work.
    PORTENTA_IDS = (
        (0x2341, 0x025B),   # Portenta H7, running a sketch
        (0x2341, 0x035B),   # Portenta H7, bootloader/DFU
        (0x2341, 0x045B),   # Portenta H7 Lite
        (0x2341, 0x805B),   # Portenta H7, alternate CDC descriptor
    )

    @classmethod
    def _is_uno_port(cls, p) -> bool:
        if (p.vid, p.pid) in cls.UNO_IDS:
            return True
        text = f"{p.description or ''} {p.manufacturer or ''}".lower()
        return any(hint in text for hint in cls.UNO_DESC_HINTS)

    @classmethod
    def _is_portenta_port(cls, p) -> bool:
        if (p.vid, p.pid) in cls.PORTENTA_IDS:
            return True
        text = f"{p.description or ''} {p.manufacturer or ''}".lower()
        return "portenta" in text

    def _uno_port_present(self) -> bool:
        """True when a device matching the Arduino Uno's USB IDs is attached."""
        return any(self._is_uno_port(p) for p in serial.tools.list_ports.comports())

    def _portenta_port_present(self) -> bool:
        """True when a device matching the Portenta H7's USB IDs is attached."""
        return any(self._is_portenta_port(p) for p in serial.tools.list_ports.comports())

    def _refresh_ports(self):
        ports = self._get_serial_ports(prefer=self._is_portenta_port)
        self._port_combo.clear()
        self._port_combo.addItems(ports)
        if ports:
            self._set_status(f"Found {len(ports)} port(s)")

    def _refresh_rpm_ports(self):
        ports = self._get_serial_ports(prefer=self._is_uno_port)
        self._rpm_port_combo.clear()
        self._rpm_port_combo.addItems(ports)
        if ports:
            self._set_status(f"Found {len(ports)} port(s)")

    def _trigger_arduino_connect(self):
        port = self._extract_port(self._port_combo.currentText())
        if not port:
            self._set_status("No port selected", CLR_ORANGE); return
        self._connect_btn.setEnabled(False)
        self._set_status(f"Connecting to {port}…")
        thread = QThread(self)
        worker = Worker(self._do_arduino_connect, port)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._on_arduino_connected)
        worker.error.connect(self._on_arduino_error)
        worker.result.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()
        # DO NOT REMOVE: these look unused and are not. Nothing reads them --
        # holding the reference IS the point. Without it Python garbage-collects
        # the QThread while it is still running and PySide aborts with
        # "QThread: Destroyed while thread is still running". Static analysis
        # and tidy-up passes flag these as dead every time; they are load-bearing.
        self._arduino_thread = thread; self._arduino_worker = worker

    def _do_arduino_connect(self, port):
        ctrl = ArduinoController(port)
        ctrl.connect()
        return ctrl

    def _on_arduino_connected(self, ctrl):
        self.arduino = ctrl
        self.arduino_connected = True
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
        self._arduino_status_lbl.setText("Connected")
        self._arduino_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px; font-weight:600;")
        self._hdr_arduino_dot.setStyleSheet(f"color:{CLR_GREEN}; font-size:10px; background:transparent;")
        self._hdr_arduino_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        self._homed_dot.setStyleSheet(f"color:{CLR_RED}; font-size:10px;")
        # A board that failed to home still connects, so say so plainly here —
        # otherwise the only symptom is an axis that silently isn't homed.
        if getattr(ctrl, "homing_error", None):
            self._set_status(f"Connected — HOMING FAILED: {ctrl.homing_error}", CLR_ORANGE)
        else:
            self._set_status("Arduino connected", CLR_GREEN)
        self._start_serial_reader()

    def _on_arduino_error(self, msg):
        self._connect_btn.setEnabled(True)
        self._set_status(f"Arduino error: {msg}", CLR_RED)

    def _trigger_arduino_disconnect(self):
        if self.arduino:
            self.arduino.disconnect()
            self.arduino = None
        self.arduino_connected = False
        self.serial_reading_active = False
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._arduino_status_lbl.setText("Not connected")
        self._arduino_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._hdr_arduino_dot.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px; background:transparent;")
        self._set_status("Arduino disconnected")

    # ── RPM Arduino (Uno) ─────────────────────────────────────────────────────

    def _trigger_rpm_connect(self):
        port = self._extract_port(self._rpm_port_combo.currentText())
        if not port:
            self._set_status("No port selected for RPM Arduino", CLR_ORANGE); return
        self._rpm_connect_btn.setEnabled(False)
        self._set_status(f"Connecting RPM Arduino on {port}…")
        thread = QThread(self)
        worker = Worker(self._do_rpm_connect, port)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._on_rpm_connected)
        worker.error.connect(self._on_rpm_error)
        worker.result.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()
        # DO NOT REMOVE: these look unused and are not. Nothing reads them --
        # holding the reference IS the point. Without it Python garbage-collects
        # the QThread while it is still running and PySide aborts with
        # "QThread: Destroyed while thread is still running". Static analysis
        # and tidy-up passes flag these as dead every time; they are load-bearing.
        self._rpm_thread = thread; self._rpm_worker = worker

    def _do_rpm_connect(self, port):
        ctrl = RpmController(port)
        ctrl.connect()
        return ctrl

    def _on_rpm_connected(self, ctrl):
        self.rpm_arduino = ctrl
        self.rpm_connected = True
        self._rpm_connect_btn.setEnabled(False)
        self._rpm_disconnect_btn.setEnabled(True)
        self._rpm_spin_btn.setEnabled(True)
        self._rpm_status_lbl.setText("Connected")
        self._rpm_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px; font-weight:600;")
        self._set_status("RPM Arduino connected", CLR_GREEN)
        self._start_rpm_serial_reader()

    def _on_rpm_error(self, msg):
        self._rpm_connect_btn.setEnabled(True)
        self._set_status(f"RPM Arduino error: {msg}", CLR_RED)

    def _trigger_rpm_disconnect(self):
        self._rpm_serial_active = False
        self._motor_stalled = False
        if self.rpm_arduino:
            if self.rpm_spinning:
                try: self.rpm_arduino.send_stop()
                except Exception: pass
            self.rpm_arduino.disconnect()
            self.rpm_arduino = None
        self.rpm_connected = False
        self.rpm_spinning = False
        self._rpm_connect_btn.setEnabled(True)
        self._rpm_disconnect_btn.setEnabled(False)
        self._rpm_spin_btn.setEnabled(False)
        self._rpm_spin_btn.setText("Spin")
        self._rpm_spin_btn.setStyleSheet(accent_button("Spin", CLR_RED).styleSheet())
        self._rpm_status_lbl.setText("Not connected")
        self._rpm_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._rpm_actual_lbl.setText("● 0 RPM")
        self._rpm_actual_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px; min-width:80px;")
        for _lbl in (self._rpm_sg_lbl, self._rpm_otpw_lbl, self._rpm_ot_lbl, self._rpm_current_lbl):
            _lbl.setText("–")
            _lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:14px; font-weight:700;")
        self._set_status("RPM Arduino disconnected")

    # ── Alicat MFC ────────────────────────────────────────────────────────────

    def _refresh_mfc_ports(self):
        ports = self._get_serial_ports()
        self._mfc_port_combo.clear()
        self._mfc_port_combo.addItems(ports)

    def _trigger_mfc_connect(self):
        port = self._extract_port(self._mfc_port_combo.currentText())
        if not port:
            self._set_status("No port selected for Alicat MFC", CLR_ORANGE); return
        self._mfc_connect_btn.setEnabled(False)
        self._set_status(f"Connecting Alicat MFC on {port}…")
        thread = QThread(self)
        worker = Worker(self._do_mfc_connect, port)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._on_mfc_connected)
        worker.error.connect(self._on_mfc_error)
        worker.result.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.start()
        # DO NOT REMOVE: these look unused and are not. Nothing reads them --
        # holding the reference IS the point. Without it Python garbage-collects
        # the QThread while it is still running and PySide aborts with
        # "QThread: Destroyed while thread is still running". Static analysis
        # and tidy-up passes flag these as dead every time; they are load-bearing.
        self._mfc_thread = thread; self._mfc_worker = worker

    def _do_mfc_connect(self, port):
        ctrl = AlicatMFC(port)
        ctrl.connect()
        return ctrl

    def _on_mfc_connected(self, ctrl):
        self.alicat = ctrl
        self.alicat_connected = True
        self._alicat_saved_port = ctrl.port
        self._mfc_connect_btn.setEnabled(False)
        self._mfc_disconnect_btn.setEnabled(True)
        self._mfc_status_lbl.setText("Connected")
        self._mfc_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px; font-weight:600;")
        self._hdr_mfc_dot.setStyleSheet(f"color:{CLR_GREEN}; font-size:10px; background:transparent;")
        self._hdr_mfc_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        self._set_status("Alicat MFC connected — flow at 0 sccm", CLR_GREEN)
        self._save_camera_settings()
        # Give the first poll a full stale window before alarming.
        self._alicat_last_frame_t = time.monotonic()
        self._alicat_stale = False
        self._start_alicat_reader()
        self._update_cutoff_status()

    def _on_mfc_error(self, msg):
        self._mfc_connect_btn.setEnabled(True)
        self._set_status(f"Alicat MFC error: {msg}", CLR_RED)

    def _trigger_mfc_disconnect(self):
        # The reader thread owns the port: signal it to stop and let its finally
        # block set 0 sccm and close, rather than closing under it from here.
        self._alicat_serial_active = False
        t = getattr(self, "_alicat_thread", None)
        if t and t.is_alive():
            t.join(timeout=1.0)
        if self.alicat:
            if self.alicat.ser and self.alicat.ser.is_open:
                try: self.alicat.ser.close()      # fallback if the thread hung
                except Exception: pass
            self.alicat = None
        self.alicat_connected = False
        self._mfc_connect_btn.setEnabled(True)
        self._mfc_disconnect_btn.setEnabled(False)
        self._mfc_status_lbl.setText("Not connected")
        self._mfc_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._hdr_mfc_dot.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px; background:transparent;")
        self._hdr_mfc_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._mfc_flow_lbl.setText("–")
        self._mfc_setpt_lbl.setText("–")
        self._mfc_pres_lbl.setText("–")
        self._mfc_temp_lbl.setText("–")
        self._mfc_regime_lbl.setText("–")
        self._gas_short_since = None
        self._gas_short_flagged = None
        self._alicat_last_frame_t = None
        self._update_cutoff_status()
        self._set_status("Alicat MFC disconnected")

    def _auto_connect_alicat(self):
        """Connect the MFC on startup — the saved port, or COM4 if none is saved."""
        if self.alicat_connected:
            return
        port = self._alicat_saved_port or self.ALICAT_DEFAULT_PORT
        for i in range(self._mfc_port_combo.count()):
            if self._extract_port(self._mfc_port_combo.itemText(i)) == port:
                self._mfc_port_combo.setCurrentIndex(i)
                break
        else:
            self._mfc_port_combo.setCurrentText(port)
        self._trigger_mfc_connect()

    # One request/response exchange every 200 ms; the unit replies in ~30–50 ms.
    ALICAT_POLL_INTERVAL = 0.2
    ALICAT_REPLY_TIMEOUT = 0.15
    # While a gas ramp runs: a new setpoint every 100 ms (10 steps a second).
    ALICAT_RAMP_INTERVAL = 0.1

    def _start_alicat_reader(self):
        if not self.alicat or not self.alicat.ser: return
        self._alicat_serial_active = True
        self._alicat_thread = threading.Thread(target=self._alicat_reader_loop, daemon=True)
        self._alicat_thread.start()

    def _alicat_reader_loop(self):
        """Sole owner of the serial port once connected.

        Each cycle sends one command — a queued setpoint if the GUI asked for
        one, otherwise a status poll — waits for the reply, then sleeps out the
        rest of the 200 ms window so the port is never hammered back-to-back.
        """
        mfc = self.alicat
        misses = 0
        try:
            while self._alicat_serial_active:
                cycle_start = time.monotonic()

                mfc.write(mfc.next_command())
                frame = mfc.read_frame(self.ALICAT_REPLY_TIMEOUT)

                if frame is None:
                    misses += 1
                    if misses in (25, 250):      # ~5 s and ~50 s of silence
                        print(f"[ALICAT] no reply to {misses} consecutive polls "
                              f"on {mfc.port}", flush=True)
                else:
                    misses = 0
                    self._parse_alicat_line(frame)

                interval = (self.ALICAT_RAMP_INTERVAL if mfc.ramping
                            else self.ALICAT_POLL_INTERVAL)
                remaining = interval - (time.monotonic() - cycle_start)
                if remaining > 0:
                    time.sleep(remaining)
        except serial.SerialException as e:
            print(f"[ALICAT] serial error: {e}", flush=True)
            crash = f"serial error: {e}"
        except Exception as e:
            print(f"[ALICAT] reader stopped: {e}", flush=True)
            crash = f"reader stopped: {e}"
        else:
            crash = None                  # Disconnect cleared _alicat_serial_active
        finally:
            self._alicat_serial_active = False
            try: mfc.close()
            except Exception: pass
        if crash:
            QTimer.singleShot(0, self, lambda c=crash: self._on_alicat_reader_died(c))

    def _parse_alicat_line(self, line: str):
        # Frame: A +00.995 +030.17 +00000 +00500 +00500 +0000000     N2
        #        id  press   temp   volum   mass   setpt    total    gas
        parts = line.split()
        if len(parts) < 6 or parts[0] != AlicatMFC.DEVICE_ID:
            return
        try:
            pressure  = float(parts[1])
            temp      = float(parts[2])
            mass_flow = float(parts[4])
            setpoint  = float(parts[5])
            # Stamped here, on the reader thread, so a busy GUI thread (a save,
            # a modal dialog) cannot make healthy readings look stale.
            self._alicat_last_frame_t = time.monotonic()
            QTimer.singleShot(0, self, lambda p=pressure, t=temp, m=mass_flow, s=setpoint:
                self._on_alicat_reading(p, t, m, s))
        except (ValueError, IndexError):
            pass

    def _on_alicat_reading(self, pressure: float, temp: float, mass_flow: float, setpoint: float):
        self._alicat_last_frame_t = time.monotonic()
        if self._alicat_stale:
            self._alicat_stale = False
            self._log("Alicat readings are back.")
            self._update_cutoff_status()
        self._mfc_flow_lbl.setText(f"{mass_flow:.1f} sccm")
        self._mfc_setpt_lbl.setText(f"{setpoint:.1f} sccm")
        self._mfc_pres_lbl.setText(f"{pressure:.2f} barA")
        self._mfc_temp_lbl.setText(f"{temp:.1f} °C")
        clr = CLR_GREEN if mass_flow > 0.5 else CLR_TEXT
        self._mfc_flow_lbl.setStyleSheet(f"color:{clr}; font-size:14px; font-weight:700;")
        self._check_pressure_cutoff(pressure)
        self._update_gas_regime(pressure, mass_flow, setpoint)
        # The Alicat is the only source for the live graphs and the run log.
        self._record_alicat_sample(pressure, mass_flow)

    def _update_gas_regime(self, pressure: float, flow: float, setpoint: float):
        """Live: is the gas at its set point? A flow more than 5% short for GAS_SHORT_HOLD_S is not a
        transient (the line filling, a ramp step): with the pressure at the supply ceiling the run is
        PRESSURE-LIMITED (on 2026-10-12 every 0.5 mm run fell to 33-5,554 sccm against 7,000-11,000 once
        the silicone arrived, and nobody could see it until the next day). Logged once per episode."""
        now = time.monotonic()
        if setpoint is None or setpoint < 100:
            self._gas_short_since = None
            self._mfc_regime_lbl.setText("–")
            self._mfc_regime_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:14px; font-weight:700;")
            return
        short = flow < GAS_SHORT_SHARE * setpoint
        if not short:
            self._gas_short_since = None
            if self._gas_short_flagged:
                self._log(f"Gas back at its set point ({flow:.0f} of {setpoint:.0f} sccm).")
                self._gas_short_flagged = None
            self._mfc_regime_lbl.setText("flow-controlled")
            self._mfc_regime_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:14px; font-weight:700;")
            return
        if self._gas_short_since is None:
            self._gas_short_since = now
        if now - self._gas_short_since < GAS_SHORT_HOLD_S:
            return                                             # may be a transient: wait
        regime = ("PRESSURE-LIMITED" if pressure >= SUPPLY_CEILING_BAR - 0.5 else "GAS SHORT")
        self._mfc_regime_lbl.setText(f"{regime} ({100 * flow / setpoint:.0f}% of set)")
        self._mfc_regime_lbl.setStyleSheet(f"color:{CLR_ORANGE}; font-size:14px; font-weight:700;")
        if self._gas_short_flagged != regime:
            self._gas_short_flagged = regime
            why = ("the pressure is at the supply ceiling: the silicone is choking the orifice, so this run is "
                   "getting much less gas than set" if regime == "PRESSURE-LIMITED" else
                   "the pressure is below the ceiling: check the gas supply and the Alicat")
            self._log(f"⚠ {regime}: gas {flow:.0f} of {setpoint:.0f} sccm set for over "
                      f"{GAS_SHORT_HOLD_S:g} s at {pressure:.2f} barA; {why}.")
            self._flash_log_border(CLR_ORANGE)

    # ── Alicat health ────────────────────────────────────────────────────────
    # The Alicat is the only pressure source, so the cut-off is only as good as
    # its readings. The reader thread can die (USB adapter pulled, driver error)
    # or the unit can stop answering; either way the UI used to stay "Connected",
    # the cut-off stayed "Armed" and Gas Off only queued a command nobody sent.

    ALICAT_STALE_S = 2.0      # ~10 missed 200 ms polls

    def _alicat_live(self) -> bool:
        """True when the reader is running and a frame arrived recently."""
        return (self.alicat_connected and self._alicat_serial_active
                and self._alicat_last_frame_t is not None
                and time.monotonic() - self._alicat_last_frame_t < self.ALICAT_STALE_S)

    def _check_alicat_alive(self):
        """Every 0.5 s: alarm once if a connected Alicat has gone quiet."""
        if not self.alicat_connected or self._alicat_stale:
            return
        last = self._alicat_last_frame_t
        if last is None or time.monotonic() - last < self.ALICAT_STALE_S:
            return
        self._alicat_stale = True
        self._alicat_alarm(f"no readings for {time.monotonic() - last:.0f} s")

    def _on_alicat_reader_died(self, why: str):
        """The reader thread exited on an error: the port is closed, nothing is
        polled and queued gas commands will never be sent."""
        self._trigger_mfc_disconnect()          # first, so its status line doesn't hide the alarm
        self._alicat_stale = True
        self._alicat_alarm(f"connection lost ({why})")
        self._mfc_status_lbl.setText("LOST — reconnect")
        self._mfc_status_lbl.setStyleSheet(f"color:{CLR_RED}; font-size:12px; font-weight:600;")
        self._hdr_mfc_dot.setStyleSheet(f"color:{CLR_RED}; font-size:10px; background:transparent;")

    def _alicat_alarm(self, why: str):
        msg = f"ALICAT: {why} — pressure is NOT being monitored"
        self._log(f"{msg}.")
        self._hdr_pressure_lbl.setText("no data")
        self._hdr_pressure_dot.setStyleSheet(f"color:{CLR_RED}; font-size:10px; background:transparent;")
        self._flash_log_border(CLR_RED)
        self._update_cutoff_status()
        if self.pressure_data['experiment_active']:
            self._pressure_off(f"Alicat {why}")
            self._set_status(f"{msg} — run stopped", CLR_RED)
            QTimer.singleShot(0, self, lambda: self._warn(
                "Alicat readings lost",
                f"The Alicat {why}.\n\nPressure was not being monitored, so the run was "
                "stopped (STOP EVERYTHING). Check the gas is off at the valve, then "
                "reconnect the MFC on the Hardware tab."))
        else:
            self._set_status(f"{msg} — check the MFC and reconnect", CLR_RED)

    def _on_cutoff_changed(self):
        """Read the cut-off box (empty or 0 = off), re-arm it and remember it."""
        text = self._cutoff_entry.text().strip()
        try:
            val = float(text) if text else 0.0
        except ValueError:
            val = 0.0
        new = val if 0.0 < val <= 30.0 else None
        if new != self._cutoff_bar:
            self._log(f"Pressure cut-off {'set to %.2f barA' % new if new else 'switched off'}.")
        self._cutoff_bar, self._cutoff_tripped = new, False
        self._update_cutoff_status()
        self._save_camera_settings()

    def _on_ramp_changed(self):
        """Read the SCCM ramp box (empty or 0 = off) and remember it."""
        text = self._ramp_entry.text().strip()
        try:
            val = float(text) if text else 0.0
        except ValueError:
            val = 0.0
        new = val if 0.0 < val <= 12000.0 else None
        if new != self._flow_ramp:
            self._log(f"Gas ramp {'set to %.0f sccm/s' % new if new else 'switched off'}.")
        self._flow_ramp = new
        self._save_camera_settings()

    def _send_flow(self, sccm: float) -> str:
        """Send a setpoint, ramped if the SCCM ramp box is set; returns a status
        phrase for the caller to show."""
        secs = self.alicat.set_flow(sccm, self._flow_ramp)
        if secs > 0:
            self._log(f"Gas ramping to {sccm:.0f} sccm at {self._flow_ramp:.0f} sccm/s "
                      f"({secs:.1f} s).")
            return f"ramping to {sccm:.1f} sccm ({secs:.1f} s)"
        return f"set to {sccm:.1f} sccm"

    def _update_cutoff_status(self):
        if self._cutoff_bar is None:
            text, clr = "Off", CLR_TEXT_SEC
        elif self._alicat_stale or not self.alicat_connected:
            text, clr = "NO DATA", CLR_RED
        elif self._cutoff_tripped:
            text, clr = "TRIPPED", CLR_RED
        else:
            text, clr = "Armed", CLR_GREEN
        self._cutoff_status_lbl.setText(text)
        self._cutoff_status_lbl.setStyleSheet(f"color:{clr}; font-size:12px; font-weight:600;")

    def _check_pressure_cutoff(self, pressure: float):
        """STOP EVERYTHING the first frame the raw pressure reaches the cut-off."""
        limit = self._cutoff_bar
        if limit is None:
            return
        if self._cutoff_tripped:
            if pressure < 0.9 * limit:
                self._cutoff_tripped = False
                self._log(f"Pressure cut-off re-armed ({pressure:.2f} barA).")
                self._update_cutoff_status()
            return
        if pressure < limit:
            return
        self._cutoff_tripped = True
        self._pressure_off(f"pressure cut-off: {pressure:.2f} barA reached the "
                           f"{limit:.2f} barA limit")
        msg = f"PRESSURE CUT-OFF: {pressure:.2f} barA reached the {limit:.2f} barA limit"
        self._log(f"{msg} — traverse, bubbler and gas stopped.")
        self._set_status(f"{msg} — everything stopped", CLR_RED)
        self._flash_log_border(CLR_RED)
        self._update_cutoff_status()
        # After the stop commands have gone out; the dialog runs its own loop.
        QTimer.singleShot(0, self, lambda: self._warn(
            "Pressure cut-off",
            f"The pressure reached {pressure:.2f} barA (cut-off {limit:.2f} barA).\n\n"
            "STOP EVERYTHING has fired: traverse, bubbler motor and gas flow are "
            "stopped. Re-home the traverse before the next run."))

    def _set_flow(self):
        if not self.alicat_connected or not self.alicat:
            self._set_status("Alicat MFC not connected", CLR_ORANGE); return
        if not self._alicat_live():
            self._warn("Alicat not responding",
                       "The Alicat is not sending readings, so the setpoint may never "
                       "reach it and the pressure is not being monitored.\n\n"
                       "Reconnect the MFC on the Hardware tab first.")
            return
        try:
            val = float(self._flow_entry.text())
            if not 0 <= val <= 12000:
                raise ValueError
            self._set_status(f"Flow {self._send_flow(val)}")
            self._last_flow = val
            self._last_flow_btn.setText(f"Set last: {val:.1f} sccm")
            self._last_flow_btn.setEnabled(True)
            self._save_camera_settings()
        except ValueError:
            self._set_status("Invalid flow value", CLR_ORANGE)
            self._warn("Invalid Flow", "Please enter a flow rate between 0 and 12000 sccm.")

    def _set_last_flow(self):
        if self._last_flow is None: return
        self._flow_entry.setText(f"{self._last_flow:.1f}")
        self._set_flow()

    def _flow_off(self):
        if not self.alicat_connected or not self.alicat:
            self._set_status("Alicat MFC not connected — close the gas at the valve", CLR_RED); return
        self.alicat.flow_off()
        if self._alicat_live():
            self._set_status("Gas flow off")
        else:
            self._set_status("Gas Off sent, but the Alicat is not responding — "
                             "close the gas at the valve", CLR_RED)

    def _reset_rpm_spin_ui(self, clear_sg: bool = True):
        """Return the RPM controls to their stopped state.

        Shared by the Spin toggle, the emergency stop and the stall handler.
        The stall handler passes clear_sg=False so its red SG reading survives.
        """
        self.rpm_spinning = False
        self._last_actual_rpm = 0.0
        self._rpm_spin_btn.setText("Spin")
        self._rpm_spin_btn.setStyleSheet(accent_button("Spin", CLR_RED).styleSheet())
        self._rpm_actual_lbl.setText("● 0 RPM")
        self._rpm_actual_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px; min-width:80px;")
        if clear_sg:
            self._motor_stalled = False
            self._rpm_sg_lbl.setText("–")
            self._rpm_sg_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:14px; font-weight:700;")

    def _toggle_spin(self):
        if not self.rpm_connected or not self.rpm_arduino:
            self._set_status("RPM Arduino not connected", CLR_ORANGE); return
        if self.rpm_spinning:
            try:
                self.rpm_arduino.send_stop()
            except Exception as e:
                self._set_status(f"RPM stop error: {e}", CLR_RED); return
            self._reset_rpm_spin_ui()   # deliberate stop, not a stall
            self._set_status("Motor stopped")
        else:
            rpm_text = self._rpm_entry.text().strip()
            if self._start_spin(float(rpm_text) if rpm_text else 100.0):
                self._set_status(f"Motor spinning at {self._spin_rpm:.0f} RPM", CLR_GREEN)

    def _start_spin(self, rpm: float) -> bool:
        """Send the RPM to the Uno and show the motor as spinning."""
        try:
            self.rpm_arduino.send_rpm(rpm)
        except Exception as e:
            self._set_status(f"RPM send error: {e}", CLR_RED)
            return False
        self._spin_rpm = rpm
        self.rpm_spinning = True
        self._motor_stalled = False   # fresh start clears any previous stall indication
        self._rpm_spin_btn.setText("Stop")
        self._rpm_spin_btn.setStyleSheet(accent_button("Stop", CLR_GREEN).styleSheet())
        return True

    def _start_rpm(self) -> float | None:
        """The RPM in the box if Start Experiment should spin the bubbler, else None."""
        try:
            rpm = float(self._rpm_entry.text().strip())
        except ValueError:
            return None
        return rpm if rpm > 0 else None

    def _start_rpm_serial_reader(self):
        if not self.rpm_arduino or not self.rpm_arduino.ser: return
        self._rpm_serial_active = True
        t = threading.Thread(target=self._rpm_serial_reader_loop, daemon=True)
        t.start()

    def _rpm_serial_reader_loop(self):
        while self._rpm_serial_active and self.rpm_arduino and self.rpm_arduino.ser:
            try:
                if self.rpm_arduino.ser.in_waiting > 0:
                    line = self.rpm_arduino.ser.readline().decode('utf-8', errors='replace').strip()
                    if line.startswith("RPM_ACTUAL:"):
                        try:
                            val = float(line.split(":")[1])
                            QTimer.singleShot(0, self, lambda v=val: self._on_rpm_actual_reading(v))
                        except Exception:
                            pass
                    elif line.startswith("MOTOR_STATUS:"):
                        self._parse_motor_status(line)
                    elif line.startswith("STALL_DETECTED"):
                        stall_rpm = None
                        try:
                            stall_rpm = float(line.split("rpm=", 1)[1])
                        except (IndexError, ValueError):
                            pass
                        QTimer.singleShot(0, self, lambda r=stall_rpm: self._on_stall_detected(r))
                else:
                    time.sleep(0.02)
            except serial.SerialException:
                break
            except Exception:
                pass

    def _on_rpm_actual_reading(self, rpm: float):
        self._last_actual_rpm = rpm
        if rpm > 0.5:
            self._rpm_actual_lbl.setText(f"▶ {rpm:.0f} RPM")
            self._rpm_actual_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px; font-weight:600; min-width:80px;")
        else:
            self._rpm_actual_lbl.setText("● 0 RPM")
            self._rpm_actual_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px; min-width:80px;")

    def _parse_motor_status(self, line: str):
        # MOTOR_STATUS:sg=<0-1023>,otpw=<0/1>,ot=<0/1>,ma=<actual mA>
        fields = {}
        try:
            for part in line.split(":", 1)[1].split(","):
                k, v = part.split("=")
                fields[k] = int(v)
        except (ValueError, IndexError):
            return
        if not {"sg", "otpw", "ot", "ma"} <= fields.keys():
            return
        QTimer.singleShot(0, self, lambda f=fields: self._on_motor_status(
            f["sg"], bool(f["otpw"]), bool(f["ot"]), f["ma"]))

    # SG_RESULT below this is shown amber as an early-warning margin before
    # STALL_SG_THRESHOLD on the Arduino actually trips the motor off.
    SG_WARN_THRESHOLD = 150

    # Console progress granularity, in percent, for long saves.  The status
    # label still updates every percent; this only thins what reaches the log
    # panel, so a long save cannot bury the rest of the run's output.
    CONSOLE_PROGRESS_STEP = 10

    # How many inference frames between console progress lines.  At stride 10
    # a 2500-frame capture is 250 inference frames, so 25 gives ~10 updates —
    # often enough to see it is alive, sparse enough not to flood the panel.
    INFERENCE_LOG_EVERY = 25

    # The pick-a-.cine button's label, restored after every run.
    FULL_ANALYSE_LABEL = "Full Analyse Cine"

    # Liquid crosses the 20.5 mm field of view at ~1 m/s, so the scene is fully
    # replaced every ~20.5 ms.  Frames closer together than that largely contain
    # the SAME droplets and are not independent samples.
    #
    # CAVEAT, and it matters: the velocity is inferred from motion blur (at
    # 10 um/px and 10 us exposure, ~1 m/s gives the ~1 px of blur observed), not
    # measured.  At 2 m/s the right stride would be half this.  Measure it
    # properly by correlating frame n against n+k on a real capture.
    DECORRELATION_MS = 20.5
    DEFAULT_STRIDE = 10

    # THE CAMPAIGN STANDARD (set 2026-10-08). Every Taguchi capture uses these so
    # runs on different days are measured identically to the 2026-10-05 9x3.
    # They are the widget defaults, and Start Experiment offers to restore them
    # if anything on screen differs (see _check_standard_capture).
    STANDARD_CAPTURE = (
        # (settings key, label, value)
        ("fps",            "Frame rate (fps)",   "390"),
        ("exposure_us",    "Exposure (us)",      "4"),
        ("width",          "Width (px)",         "2048"),
        ("height",         "Height (px)",        "1152"),
        ("pre_trigger_s",  "Pre-trigger (s)",    "0"),
        ("post_trigger_s", "Post-trigger (s)",   "13"),
        ("ai_stride",      "AI stride",          "10"),
    )
    # The AI chain measures at sizer 2.2.0 (the sharpness rule) and runs the
    # classical liquid stage, so a capture comes out with droplets_0.30/ AND
    # liquid_0.30/, both 2.2.0, ready for the Taguchi app's Analyse. The app's
    # own batch still defaults to 2.1.0: do not "Re-measure" these runs there.
    SHARPNESS_RULE = True

    # Inference cost scales with frame AREA, not frame count, so the estimate
    # has to know the resolution.  Measured 2026-09-28 on the RTX 4070 Ti SUPER
    # after the mask-storage fix, split by size:
    #     2048x1152 (2.36 MP)   2.3 s/frame   ->  0.97 s/MP
    #     2560x1600 (4.10 MP)   5.1 s/frame   ->  1.25 s/MP
    # Superlinear because a bigger frame needs more tiles AND holds more
    # detections.  The higher figure is used: over-estimating a wait is much
    # less annoying than under-estimating it, and a flat per-frame constant
    # told a 2560x1600 user 6 min for a job that actually took 23.
    INFERENCE_S_PER_MEGAPIXEL = 1.25

    # Canonical master_log.xlsx layout, A..R. MASTER_HEADERS is stamped onto row 1
    # on every save, so a rename here reaches existing workbooks and a column added
    # by a migration cannot end up nameless or unstyled (which is how 'Mass Flow
    # Graph' ended up the only unbold, unfilled header in the file).
    # _write_excel finds every column by its NAME in this tuple -- never by
    # letter -- so adding a column here cannot misplace the images again.
    # Shadowgraph (P) is sized for the 300 px images placed there; the cone (O)
    # and the two graph columns (Q, R) are widened further from their actual
    # rendered image sizes when those images exist.
    # Mean Diameter (in-focus droplets, from summary.json like D32) added
    # 2026-10-13 (Ben); migrate_master_mean_diameter() moves older logs to it.
    # Orifice Length (C) added the same day (Ben: the exit orifice length
    # sometimes changes); migrate_master_orifice_length() moves logs to it.
    # Droplets/s (N, in-band droplets produced per second by mass balance,
    # droplet_rate_band) the same day; migrate_master_droplet_rate().
    MASTER_HEADERS = ('Timestamp', 'Orifice', 'Orifice Length (mm)', 'Bubbler Height (mm)', 'Bubbler RPM',
                      'Flow Range (sccm)', 'GLR', 'Pressure Range (barA)',
                      'Speed (steps/s)',
                      'Motor Travel (mm)', 'D32 (um)', 'Mean Diameter (um)', 'Atomised (%)',
                      MASTER_RATE_HEADER, 'Avg Lamella Thickness', 'Notes',
                      'Cone Image', 'Shadowgraph', 'Pressure Graph', 'Mass Flow Graph')
    MASTER_COL_COUNT  = 20
    MASTER_COL_LETTERS = 'ABCDEFGHIJKLMNOPQRST'
    MASTER_COL_WIDTHS = (20, 8, 10, 16, 12, 18, 10, 18, 14, 12, 11, 12, 12, 14, 12, 35, 36.5, 43, 56, 56)

    # Header row style, matched to what the existing master_log.xlsx already uses:
    # theme-1 fill at 0.15 tint (dark grey) with bold white Calibri.
    MASTER_HDR_FILL_THEME, MASTER_HDR_FILL_TINT = 1, 0.1499984740745262
    MASTER_HDR_FONT_THEME = 0

    # Shadowgraph thumbnails are placed at a fixed width; the column above is
    # derived from it (Excel column width ~= pixels / 7).
    SHADOWGRAPH_W_PX = 300

    # Must match MIN_STALL_CHECK_RPM in RAMP_RPM_Motor_Control.ino — below this
    # speed SG_RESULT is not trustworthy (mirrors the firmware's own stall-check
    # gate), so the GUI shouldn't paint it red/amber either. It also reads ~0 at
    # a dead stop by design — that isn't a stall, it's "not measuring".
    RPM_MIN_STALL_CHECK = 60

    def _on_motor_status(self, sg: int, otpw: bool, ot: bool, ma: int):
        # SG is only meaningful while genuinely spinning above the trusted-speed
        # floor; otherwise show it neutral rather than a misleading red "0".
        trustworthy = self.rpm_spinning and self._last_actual_rpm >= self.RPM_MIN_STALL_CHECK
        if trustworthy:
            stall_zone = sg < self.RPM_STALL_SG_THRESHOLD
            warn_zone  = sg < self.SG_WARN_THRESHOLD
            sg_colour  = CLR_RED if stall_zone else (CLR_ORANGE if warn_zone else CLR_GREEN)
            self._rpm_sg_lbl.setText(str(sg))
            self._rpm_sg_lbl.setStyleSheet(f"color:{sg_colour}; font-size:14px; font-weight:700;")
        elif self._motor_stalled:
            pass   # keep the red stall indication until the next Spin — see _toggle_spin
        else:
            self._rpm_sg_lbl.setText(str(sg) if self.rpm_spinning else "–")
            self._rpm_sg_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:14px; font-weight:700;")

        otpw_colour = CLR_ORANGE if otpw else CLR_GREEN
        self._rpm_otpw_lbl.setText("TRIPPED" if otpw else "OK")
        self._rpm_otpw_lbl.setStyleSheet(f"color:{otpw_colour}; font-size:14px; font-weight:700;")

        ot_colour = CLR_RED if ot else CLR_GREEN
        self._rpm_ot_lbl.setText("TRIPPED" if ot else "OK")
        self._rpm_ot_lbl.setStyleSheet(f"color:{ot_colour}; font-size:14px; font-weight:700;")

        # ~half MOTOR_CURRENT while idle (ihold) is expected, not a fault —
        # see the tooltip.
        self._rpm_current_lbl.setText(f"{ma} mA")
        self._rpm_current_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:14px; font-weight:700;")

    def _on_stall_detected(self, stall_rpm: float | None):
        """Firmware detected SG_RESULT below threshold and already stopped the
        motor on its own; mirror that here rather than waiting on RPM_ACTUAL."""
        self._reset_rpm_spin_ui(clear_sg=False)
        self._motor_stalled = True
        # Stays red until the next Spin — this is the one case SG should alarm
        # even though the motor is now stopped, since it's *why* it stopped.
        self._rpm_sg_lbl.setStyleSheet(f"color:{CLR_RED}; font-size:14px; font-weight:700;")
        rpm_note = f" — stalled at {stall_rpm:.0f} RPM" if stall_rpm is not None else ""
        self._set_status(f"Motor stall detected{rpm_note} — stopped automatically", CLR_RED)
        if self.pressure_data['experiment_active']:
            # The traverse and gas carry on, so the run still ends normally, but
            # the bubbler was not at its set speed for all of it.
            self._mark_run_stopped(f"bubbler motor stalled mid-run{rpm_note.replace(' — ', ' ')}",
                                   early=False)
            self._log(f"Bubbler stalled during the run{rpm_note}; the run will be "
                      "marked as stopped.")

    def _start_serial_reader(self):
        if not self.arduino or not self.arduino.ser: return
        self.serial_reading_active = True
        t = threading.Thread(target=self._serial_reader_loop, daemon=True)
        t.start()

    def _serial_reader_loop(self):
        while self.serial_reading_active and self.arduino and self.arduino.ser:
            try:
                if self.arduino.ser.in_waiting > 0:
                    line = self.arduino.ser.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        log_serial(f"Received: {line}")
                        if line.startswith("FRONT_LIMIT"):
                            QTimer.singleShot(0, self, lambda l=line: self._on_front_limit(l))
                        elif line.startswith("STALL_DETECTED"):
                            QTimer.singleShot(0, self, lambda l=line: self._on_traverse_stall(l))
                        elif "MOVEMENT_TIMEOUT" in line:
                            QTimer.singleShot(0, self, lambda: self._mark_run_stopped(
                                "the Portenta's own movement timeout fired", early=False))
                            QTimer.singleShot(0, self, self._on_movement_complete)
                        elif "MOVEMENT_COMPLETE" in line:
                            QTimer.singleShot(0, self, self._on_movement_complete)
                        elif line.startswith("SWITCHES:"):
                            QTimer.singleShot(0, self, lambda l=line: self._on_switch_report(l))
                        elif line.startswith("ERROR:") or line.startswith("HOMING_FAILED"):
                            QTimer.singleShot(0, self, lambda l=line: self._on_portenta_error(l))
                        elif line.startswith("JOG_POS:"):
                            try:
                                steps = int(line.split(":")[1])
                                QTimer.singleShot(0, self, lambda s=steps: self._on_jog_pos(s))
                            except: pass
                        elif line == "ARDUINO_READY" and self._jogging:
                            QTimer.singleShot(0, self, self._on_jog_complete)
                        elif "JOG_LIMIT" in line and self._jogging:
                            QTimer.singleShot(0, self, self._on_jog_complete)
                        elif "Homing Complete" in line:
                            QTimer.singleShot(0, self, self._on_homed)
                        elif line.startswith("DEBUG: Movement progress:"):
                            try:
                                pct = int(line.split(":")[-1].strip().replace("%", ""))
                                live_dist = self._pre_move_cumulative + (self._pending_move_distance * pct / 100.0)
                                QTimer.singleShot(0, self, lambda p=pct, d=live_dist: (
                                    setattr(self, "_last_move_pct", p),
                                    self._exp_progress.setValue(p),
                                    self._update_travel_bar(d),
                                ))
                            except: pass
                else:
                    # Only sleep when idle — sleeping with data waiting fills the Portenta TX buffer
                    # and causes Serial.print() to block, stalling AccelStepper::run() on the board
                    time.sleep(0.01)
            except serial.SerialException:
                break  # port closed or disconnected — exit cleanly
            except Exception as e:
                log_serial(f"Serial reader warning: {e}")

    def _record_alicat_sample(self, pressure: float, flow: float):
        """Feed one Alicat frame into the live graphs and the experiment log."""
        now = time.time()

        # ── EMA smoothing ─────────────────────────────────────────────────────
        # Initialise (or reinitialise after a gap) by seeding with the first value
        a = self._EMA_ALPHA
        self._pressure_ema = pressure if self._pressure_ema is None else \
            a * pressure + (1.0 - a) * self._pressure_ema
        self._flow_ema = flow if self._flow_ema is None else \
            a * flow + (1.0 - a) * self._flow_ema
        disp_p = self._pressure_ema if self._smooth_enabled else pressure
        disp_f = self._flow_ema     if self._smooth_enabled else flow

        # ── Live buffer (graphs) — stores display values ──────────────────────
        lb = self.pressure_data['live_buffer']
        lb['timestamps'].append(now - self.pressure_data['live_buffer_start_time'])
        lb['pressures'].append(disp_p)
        lb['flows'].append(disp_f)
        # Keep 60s rolling window
        cutoff = lb['timestamps'][-1] - 60.0
        while lb['timestamps'] and lb['timestamps'][0] < cutoff:
            lb['timestamps'].pop(0); lb['pressures'].pop(0); lb['flows'].pop(0)

        # ── Experiment log — always stores raw values for accurate export ─────
        if self.pressure_data['experiment_active']:
            ed = self.pressure_data['experiment_data']
            ed['timestamps'].append(now - self.pressure_data['experiment_start_time'])
            ed['pressures'].append(pressure)
            ed['flows'].append(flow)

        self._hdr_pressure_lbl.setText(f"{disp_p:.3f} barA")
        self._hdr_pressure_dot.setStyleSheet(f"color:{CLR_ACCENT}; font-size:10px; background:transparent;")

    def _on_smooth_toggled(self, checked: bool):
        self._smooth_enabled = checked
        # Reset EMA state so switching modes doesn't leave a stale seed value
        self._pressure_ema = None
        self._flow_ema     = None

    @Slot()
    def _on_homed(self):
        self._homed_dot.setStyleSheet(f"color:{CLR_GREEN}; font-size:10px;")
        self._set_status("Homed", CLR_GREEN)

    @Slot()
    def _stop_bubbler_failsafe(self, reason: str):
        """End-of-experiment failsafe: stop the bubbler (spin) motor.

        Sent unconditionally rather than gated on self.rpm_spinning -- that flag
        is GUI bookkeeping and can be stale, while STOP on the Uno is idempotent
        (stopMotor() + driver disabled, harmless when already stopped). Runs
        FIRST in the end-of-experiment paths, before the gas shut-off and the
        Excel save, so nothing that follows can delay it.
        """
        if not (self.rpm_connected and self.rpm_arduino):
            return
        try:
            self.rpm_arduino.send_stop()
            self._reset_rpm_spin_ui()
            self._log(f"Bubbler motor stopped automatically ({reason}).")
        except Exception as e:
            self._log(f"Bubbler motor auto-stop FAILED ({e}) -- stop it manually.")
            self._set_status(f"Bubbler auto-stop failed: {e}", CLR_RED)

    def _on_movement_complete(self):
        self._experiment_watchdog.stop()
        self._stop_fallback_timer.stop()
        self._auto_trigger_cancel("the traverse finished before the camera fired")
        if self._front_limit_steps is not None:
            # The board reported exactly where it stopped
            self.cumulative_distance = min(self.MAX_MOTOR_MM, self._front_limit_steps / 6800.0)
        elif self._move_stopped_early:
            # Credit only the travel actually covered (last progress report)
            self.cumulative_distance = (self._pre_move_cumulative
                                        + self._pending_move_distance * self._last_move_pct / 100.0)
        else:
            self.cumulative_distance = self._pre_move_cumulative + self._pending_move_distance
        # A second MOVEMENT_COMPLETE (e.g. after the STOP fallback already ended
        # the run) must not move the counter back to the start of this move.
        self._pre_move_cumulative = self.cumulative_distance
        self._pending_move_distance = 0.0
        self._move_stopped_early = False
        self._front_limit_steps = None
        self._last_move_pct = 0
        self._update_travel_bar()
        if self.pressure_data['experiment_active']:
            self._stop_bubbler_failsafe("experiment complete")
            self.pressure_data['experiment_active'] = False
            self._cone_auto_timer.stop()
            self._cone_auto_status_lbl.setText("Auto-capture: inactive")
            self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
            if self.alicat_connected and self.alicat:
                try: self.alicat.flow_off()
                except Exception: pass
            self._last_experiment_snapshot = {
                'timestamps':     list(self.pressure_data['experiment_data']['timestamps']),
                'pressures':      list(self.pressure_data['experiment_data']['pressures']),
                'flows':          list(self.pressure_data['experiment_data']['flows']),
                'camera_windows': list(self.pressure_data.get('camera_windows', [])),
            }
            self._experiment_saved = False
            # Save immediately, so a run is on disk before anyone can forget.
            # Notes are written AFTER a run, so this row is expected to be
            # incomplete -- saving again once they are typed updates this same
            # row rather than adding a second one (matched on the start
            # timestamp). Never let a save failure break the end-of-experiment
            # flow: the pressure is off and the UI must finish resetting.
            # Runs in the background (see _save_to_excel_async), so the GUI --
            # including the bubbler Stop -- stays responsive during the ~10 s
            # master_log write.
            def _after_auto_save(ok, err):
                if ok:
                    self._log("Experiment saved automatically — add Notes and save "
                              "again to update the same row.")
                else:
                    self._log(f"Auto-save failed ({err}) — use Save to Excel.")
            try:
                self._save_to_excel_async(on_done=_after_auto_save)
            except Exception as _e:
                self._log(f"Auto-save failed ({_e}) — use Save to Excel.")
            self._exp_progress.setRange(0, 100)
            self._exp_progress.setValue(100)
            QTimer.singleShot(800, lambda: (
                self._exp_progress.setVisible(False),
                self._exp_progress.setRange(0, 0),
            ))
            self._start_btn.setEnabled(True)
            self._stop_run_timer()
            if self._run_stop_reason:
                self._set_status(f"Run STOPPED ({self._run_stop_reason}) — saved and "
                                 "marked as stopped", CLR_RED)
                self._log(f"Run stopped early: {self._run_stop_reason}. Saved with "
                          "Run status = stopped.")
            else:
                self._set_status("Experiment complete ✓ — remember to Save to Excel", CLR_GREEN)
            if self.arduino:
                threading.Thread(target=self.arduino.reset_state, daemon=True).start()

    @staticmethod
    def _open_folder(path: str):
        import subprocess, sys as _sys
        if _sys.platform == "win32":
            os.startfile(path)
        elif _sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def _open_last_save_folder(self):
        path = getattr(self, "_last_saved_run_folder", None)
        if path and os.path.exists(path):
            self._open_folder(path)

    def _update_volume_label(self):
        import math as _math
        try:
            dist_mm = float(self._distance_entry.text())
            vol_ul = _math.pi * 10.0 ** 2 * dist_mm   # µL  (radius=10mm, area in mm²)
            vol_ml = vol_ul / 1000.0
            self._volume_lbl.setText(f"≈ {vol_ml:.2f} mL")
        except (ValueError, AttributeError):
            self._volume_lbl.setText("≈ – mL")

    # Default densities. Silicone oil ~970 kg/m3; air at 25 degC and 1 atm is
    # 1.184 kg/m3.
    #
    # The reference state is not a detail. "sccm" means STANDARD cm3/min, and
    # the standard is whatever the mass flow controller says it is -- Alicat,
    # which is what this rig uses, defaults to 25 degC / 1 atm, NOT the 0 degC
    # that "standard conditions" means in much of the literature. Quoting the
    # gas density at the wrong reference biases every gas mass flow by 9%
    # (1.293 vs 1.184), and silently, because the number still looks plausible.
    DEFAULT_RHO_LIQUID = 970.0
    DEFAULT_RHO_GAS    = 1.184

    def _densities(self):
        """(rho_liquid, rho_gas) in kg/m3 from the Materials tab, or None."""
        try:
            rl = float(self._rho_liquid_entry.text())
            rg = float(self._rho_gas_entry.text())
            return (rl, rg) if rl > 0 and rg > 0 else (None, None)
        except (ValueError, AttributeError):
            return (None, None)

    def _glr_working(self):
        """Every intermediate in the GLR, so the Materials tab can show the
        actual arithmetic rather than just the formula. None when an input is
        missing. `_compute_glr` is the thin wrapper that returns only the ratio.
        """
        import math as _math
        rho_l, rho_g = self._densities()
        if rho_l is None:
            return None
        try:
            sccm = float(self._flow_entry.text())
            speed_steps_s = float(self._speed_entry.text())
        except (ValueError, AttributeError):
            return None
        _AREA_MM2 = _math.pi * (20.27 / 2) ** 2
        ml_per_min = (_AREA_MM2 * (speed_steps_s / 6800) / 1000.0) * 60.0
        if ml_per_min <= 0 or sccm <= 0:
            return None
        # cm3/min x kg/m3 -> g/min needs x1e-6 m3/cm3 then x1e3 g/kg, i.e. x1e-3.
        # The same factor applies to both, so it cancels in the ratio -- but it
        # is kept here because the per-line mass flows are shown in g/min.
        gas_g_min = sccm * rho_g * 1e-3
        liq_g_min = ml_per_min * rho_l * 1e-3
        return {"sccm": sccm, "rho_g": rho_g, "gas_g_min": gas_g_min,
                "ml_per_min": ml_per_min, "rho_l": rho_l, "liq_g_min": liq_g_min,
                "glr": gas_g_min / liq_g_min}

    def _compute_glr(self):
        """Gas-to-liquid MASS ratio, dimensionless. None when inputs are missing.

            gas mass flow    = sccm [cm3/min] x rho_gas [kg/m3] x 1e-6 x 1000
            liquid mass flow = mL/min [cm3/min] x rho_liquid [kg/m3] x 1e-6 x 1000

        The unit factors are identical on both sides and cancel, so the ratio is
        just (sccm x rho_gas) / (mL/min x rho_liquid).

        Both flows are COMMANDED set points, not measurements. The gas is held to
        ~1% of set point, but liquid delivery through the bubbler is not
        necessarily steady -- the L9 found droplet-count CV rising with bubbler
        RPM. So this is the run's mean GLR; the instantaneous value is not
        guaranteed constant.
        """
        w = self._glr_working()
        return None if w is None else w["glr"]

    def _update_glr_label(self):
        glr = self._compute_glr()
        if not hasattr(self, "_glr_lbl"):
            return
        self._glr_lbl.setText("–" if glr is None else f"{glr:.3f}")
        if hasattr(self, "_glr_detail_lbl"):
            self._glr_detail_lbl.setText("GLR –" if glr is None else f"GLR {glr:.3f}")
        if hasattr(self, "_glr_working_lbl"):
            w = self._glr_working()
            if w is None:
                # say WHICH input is missing rather than just showing a dash
                missing = []
                if self._densities()[0] is None:
                    missing.append("both densities above")
                if not (self._flow_entry.text() or "").strip():
                    missing.append("gas flow (sccm), on the Hardware tab")
                if not (self._speed_entry.text() or "").strip():
                    missing.append("motor speed (steps/s), on the Hardware tab")
                need = "; ".join(missing) if missing else "valid, non-zero inputs"
                self._glr_working_lbl.setText(
                    f"<i>Needs {need}.</i>")
            else:
                self._glr_working_lbl.setText(
                    "With your current inputs:<br>"
                    f"&nbsp;&nbsp;gas&nbsp;&nbsp;&nbsp;&nbsp;{w['sccm']:,.0f} sccm "
                    f"&times; {w['rho_g']:g} kg/m³ &nbsp;=&nbsp; "
                    f"<b>{w['gas_g_min']:.3f} g/min</b><br>"
                    f"&nbsp;&nbsp;liquid&nbsp;&nbsp;{w['ml_per_min']:.2f} mL/min "
                    f"&times; {w['rho_l']:g} kg/m³ &nbsp;=&nbsp; "
                    f"<b>{w['liq_g_min']:.3f} g/min</b><br>"
                    f"&nbsp;&nbsp;GLR&nbsp;&nbsp;&nbsp;&nbsp;{w['gas_g_min']:.3f} "
                    f"&divide; {w['liq_g_min']:.3f} &nbsp;=&nbsp; "
                    f"<b>{w['glr']:.3f}</b>")

    def _update_flowrate_label(self):
        import math as _math
        _STEPS_PER_MM = 6800
        _RADIUS_MM    = 20.27 / 2          # bore diameter 20.27 mm
        _AREA_MM2     = _math.pi * _RADIUS_MM ** 2
        try:
            speed_steps_s = float(self._speed_entry.text())
            mm_per_s  = speed_steps_s / _STEPS_PER_MM
            ml_per_min = (_AREA_MM2 * mm_per_s / 1000.0) * 60.0
            self._flowrate_lbl.setText(f"≈ {ml_per_min:.2f} mL/min")
        except (ValueError, AttributeError):
            self._flowrate_lbl.setText("≈ – mL/min")
        self._update_glr_label()

    def _update_next_save_preview(self):
        now = datetime.now()
        flow_raw = self._flow_entry.text().strip() if hasattr(self, "_flow_entry") else ""
        try:
            flow_str = f"{float(flow_raw):.0f}sccm"
        except ValueError:
            flow_str = "?sccm"
        run_id = self._run_id(now, flow_str)
        lacie = find_lacie_drive()
        exp_base = os.path.join(lacie, "Experiments") if lacie else os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "experiment_logs", "Experiments")
        preview = os.path.join(exp_base, now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"), run_id)
        colour = "#FFA500" if os.path.exists(preview) else CLR_TEXT_SEC
        self._hdr_next_save_lbl.setText(preview)
        self._hdr_next_save_lbl.setStyleSheet(f"color: {colour}; font-size: 12px;")

    def _tick_run_timer(self):
        if self._run_start_time is None: return
        elapsed = int(time.time() - self._run_start_time)
        m, s = divmod(elapsed, 60)
        self._hdr_timer_lbl.setText(f"{m:02d}:{s:02d}")
        self._hdr_timer_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 12px; font-weight: 700;")

    def _stop_run_timer(self):
        self._run_elapsed_timer.stop()
        self._run_start_time = None
        self._hdr_timer_lbl.setText("00:00")
        self._hdr_timer_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 12px; font-weight: 700;")

    def _poll_lacie(self):
        connected = find_lacie_drive() is not None
        colour = CLR_GREEN if connected else CLR_RED
        self._hdr_lacie_dot.setStyleSheet(
            f"color:{colour}; font-size:10px; background:transparent;")
        self._hdr_lacie_lbl.setStyleSheet(
            f"color:{'#e5e5ea' if connected else CLR_TEXT_SEC}; font-size:12px;")

    def _on_experiment_timeout(self):
        """Watchdog fired: no MOVEMENT_COMPLETE within the expected time + 30 s
        (Portenta reader dead, board hung, or a lost message). Stop the
        traverse, then end and SAVE the run through the normal path -- gas off,
        bubbler stopped, trace kept, marked as stopped."""
        self._auto_trigger_cancel("the run timed out")
        if not self.pressure_data['experiment_active']:
            return
        self._mark_run_stopped("GUI watchdog: no end-of-move message from the Portenta "
                               "within the expected time + 30 s")
        if self.arduino_connected and self.arduino:
            try: self.arduino.send_stop()
            except Exception: pass
        self._on_movement_complete()

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Motor
    # ─────────────────────────────────────────────────────────────────────────

    def _pressure_off(self, reason: str = "STOP EVERYTHING pressed"):
        """Emergency stop — halt everything that moves and cut the gas.

        Each device is attempted independently so a failure on one (or one
        simply not being connected) can't prevent the others from stopping.
        `reason` is recorded against the run if one is in progress.
        """
        stopped = []
        self._auto_trigger_cancel("Pressure Off")
        self._mark_run_stopped(reason)

        # Traverse motor (Portenta)
        if self.arduino_connected and self.arduino:
            try:
                self.arduino.send_stop()
                stopped.append("traverse")
            except Exception: pass

        # Spin motor (Arduino Uno) — separate board, needs its own STOP
        if self.rpm_connected and self.rpm_arduino:
            try:
                self.rpm_arduino.send_stop()
                self._reset_rpm_spin_ui()
                stopped.append("spin motor")
            except Exception: pass

        # Gas (Alicat MFC)
        if self.alicat_connected and self.alicat:
            try:
                self.alicat.flow_off()
                stopped.append("gas")
            except Exception: pass

        if stopped:
            self._set_status(f"EMERGENCY STOP — {', '.join(stopped)} off", CLR_RED)
        else:
            self._set_status("Emergency stop — nothing connected to stop", CLR_ORANGE)
        # The Portenta answers STOP with MOVEMENT_COMPLETE only while a move is
        # running. With no move (speed 0 run, the 0.5 s before the move starts,
        # a dead reader) nothing would end the run, so end it here if that
        # message has not arrived within 1.5 s.
        # Started once: a second stop (e.g. the cut-off firing again) must not
        # keep pushing it back.
        if self.pressure_data['experiment_active'] and not self._stop_fallback_timer.isActive():
            self._stop_fallback_timer.start(1500)

    def _end_run_after_stop(self):
        if self.pressure_data['experiment_active']:
            self._log("No end-of-move message after STOP — ending the run here.")
            self._on_movement_complete()

    def _mark_run_stopped(self, reason: str, early: bool = True):
        """Record why the current run ended early (first reason wins)."""
        if not self.pressure_data['experiment_active']:
            return
        if early:
            self._move_stopped_early = True
        if self._run_stop_reason is None:
            if (self._run_conditions or {}).get('static'):
                reason = f"static run (speed 0), ended by {reason}"
            self._run_stop_reason = reason

    def _on_front_limit(self, line: str):
        """The board stopped at the front optical switch (absolute forward stop)."""
        try:
            self._front_limit_steps = int(line.split("pos=")[1].split()[0])
        except (IndexError, ValueError):
            self._front_limit_steps = None
        pos = (f" at {self._front_limit_steps / 6800.0:.1f} mm"
               if self._front_limit_steps is not None else "")
        self._log(f"FRONT LIMIT SWITCH reached{pos} — the Portenta stopped the traverse.")
        self._flash_log_border(CLR_RED)
        if self.pressure_data['experiment_active']:
            self._mark_run_stopped(f"front limit switch reached{pos}")
            self._pressure_off(f"front limit switch reached{pos}")
        else:
            self._set_status(f"Front limit switch reached{pos} — traverse stopped. "
                             "Re-home before the next run.", CLR_RED)

    def _on_traverse_stall(self, line: str):
        """Portenta: the traverse stopped moving for 2 s before its target."""
        self._log(f"Traverse stalled: {line}")
        self._mark_run_stopped(f"traverse stalled ({line.split(':', 1)[-1].strip()})")

    def _on_switch_report(self, line: str):
        """Reply to Check switches: 'SWITCHES: back=LOW front=LOW pos=123'."""
        self._log(line)
        front_high = "front=HIGH" in line
        self._set_status(
            "Front switch reads HIGH (blocked, or unplugged) — forward motion is "
            "blocked" if front_high else "Front switch reads LOW (clear)",
            CLR_RED if front_high else CLR_GREEN)

    def _on_portenta_error(self, line: str):
        """A move the Portenta refused, or a failed homing: say so, and end a run
        that is waiting for a move that will never come."""
        self._log(f"Portenta: {line}")
        self._set_status(f"Portenta: {line}", CLR_RED)
        if line.startswith("HOMING_FAILED"):
            self._homed_dot.setStyleSheet(f"color:{CLR_RED}; font-size:10px;")
        elif self.pressure_data['experiment_active']:
            self._pressure_off(f"the Portenta refused the move ({line[6:].strip()})")

    def _home_motor(self):
        if not self._require_arduino(): return
        self.arduino.ser.write(b"HOME:1\n")
        log_serial("Sent: HOME:1")
        self.cumulative_distance      = 0.0
        self._pre_move_cumulative     = 0.0
        self._pending_move_distance   = 0.0
        self._update_travel_bar()
        self._set_status("Homing…")

    def _check_switches(self):
        """Ask the Portenta for both limit switches; the reply is logged by the reader."""
        if not self._require_arduino(): return
        try:
            self.arduino.ser.write(b"SWITCHES:\n")
            self._log("Asked the Portenta for the limit switch states…")
        except Exception as e:
            self._set_status(f"Could not ask for switch states: {e}", CLR_RED)

    def _move_motor(self):
        if not self._require_arduino(): return
        try:
            speed = int(self._speed_entry.text())
            dist  = float(self._distance_entry.text())
        except ValueError:
            self._set_status("Invalid speed or distance", CLR_ORANGE)
            self._warn("Invalid Motor Values",
                       "Please enter a valid speed (steps/s) and distance (mm).")
            return
        if self.cumulative_distance + dist > self.MAX_MOTOR_MM:
            remaining = self.MAX_MOTOR_MM - self.cumulative_distance
            self._set_status(f"Only {remaining:.1f} mm remaining!", CLR_ORANGE)
            self._warn("Travel Limit",
                       f"This move would exceed the motor's travel limit of {self.MAX_MOTOR_MM} mm.\n\n"
                       f"Only {remaining:.1f} mm of travel remains.\n"
                       "Home the motor to reset.")
            return
        self.arduino.send_motor_command(speed, dist)
        self._pre_move_cumulative   = self.cumulative_distance
        self._pending_move_distance = dist
        self._set_status(f"Moving {dist} mm at {speed} steps/s")

    def _jog_start(self, direction: int):
        if not self._require_arduino(): return
        try:
            speed = int(float(self._speed_entry.text()))
            if speed <= 0:
                raise ValueError
        except ValueError:
            self._set_status("Enter a valid speed before jogging", CLR_ORANGE)
            return
        if direction > 0 and self.cumulative_distance >= self.MAX_MOTOR_MM:
            self._set_status("At travel limit — home to reset", CLR_ORANGE)
            return
        if direction < 0 and self.cumulative_distance <= 0:
            self._set_status("Already at home position", CLR_ORANGE)
            return
        self._jogging = True
        self._jog_held = True
        self._move_btn.setEnabled(False)
        self._home_btn.setEnabled(False)
        self._switches_btn.setEnabled(False)
        cmd = f"JOG:{speed};DIR:{direction}\n"
        self.arduino.ser.write(cmd.encode())
        log_serial(f"Sent: {cmd.strip()}")
        label = "forward" if direction > 0 else "backward"
        self._set_status(f"Jogging {label} at {speed} steps/s — release to stop")

    def _jog_stop(self):
        # Keyed on the button being held, not on _jogging: a periodic
        # ARDUINO_READY read just after the press used to clear _jogging, so the
        # release sent nothing and the jog ran on to the board's limit.
        if not self._jog_held: return
        self._jog_held = False
        if not self.arduino or not self.arduino.ser: return
        self.arduino.ser.write(b"STOP\n")
        log_serial("Sent: STOP")

    @Slot()
    def _on_jog_complete(self):
        self._jogging = False
        self._move_btn.setEnabled(True)
        self._home_btn.setEnabled(True)
        self._switches_btn.setEnabled(True)
        self._set_status("Jog stopped")

    def _on_jog_pos(self, steps: int):
        mm = max(0.0, min(self.MAX_MOTOR_MM, steps / 6800.0))
        self.cumulative_distance = mm
        self._update_travel_bar()
        # Soft limit, enforced here as well as on the board
        if self._jog_held and steps / 6800.0 >= self.MAX_MOTOR_MM:
            self._jog_stop()
            self._set_status(f"Jog stopped at the {self.MAX_MOTOR_MM} mm travel limit", CLR_ORANGE)

    def _update_travel_bar(self, distance=None):
        d = distance if distance is not None else self.cumulative_distance
        pct = d / self.MAX_MOTOR_MM
        self._travel_bar.setValue(int(pct * 1000))
        remaining = self.MAX_MOTOR_MM - d
        self._travel_label.setText(f"{d:.1f} / {self.MAX_MOTOR_MM} mm")
        if pct >= 0.9:
            self._travel_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {CLR_RED}; border-radius:4px; }}")
            self._travel_warning.setText(f"⚠  Only {remaining:.1f} mm remaining")
        elif pct >= 0.7:
            self._travel_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {CLR_ORANGE}; border-radius:4px; }}")
            self._travel_warning.setText(f"{remaining:.1f} mm remaining")
        else:
            self._travel_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {CLR_ACCENT}; border-radius:4px; }}")
            self._travel_warning.setText("")
        vol_ml = 25.8 * (d / self.MAX_MOTOR_MM)
        self._vol_label.setText(f"{vol_ml:.2f} mL")

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Pipeline log panel
    # ─────────────────────────────────────────────────────────────────────────

    def _flash_log_border(self, colour: str, duration_ms: int = 5000):
        """Briefly colour the console border, then restore it."""
        flashed = self._pipeline_log_base_style.replace(
            f"border: 1px solid {CLR_BORDER}", f"border: 2px solid {colour}"
        )
        self._pipeline_log.setStyleSheet(flashed)
        QTimer.singleShot(duration_ms, lambda:
            self._pipeline_log.setStyleSheet(self._pipeline_log_base_style)
        )

    def _log(self, text: str):
        """Append a line directly to the log panel (main-thread safe)."""
        ts = datetime.now().strftime("%H:%M:%S")
        self._pipeline_log.appendPlainText(f"[{ts}]  {text}")
        sb = self._pipeline_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _flush_log_queue(self):
        """Drain the cross-thread log queue into the log widget (called by timer on main thread)."""
        changed = False
        while True:
            try:
                line = self._log_queue.get_nowait()
                ts = datetime.now().strftime("%H:%M:%S")
                self._pipeline_log.appendPlainText(f"[{ts}]  {line}")
                changed = True
                if "low fit quality" in line.lower():
                    self._flash_log_border(CLR_ORANGE)
            except queue.Empty:
                break
        if changed:
            sb = self._pipeline_log.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Pressure graph
    # ─────────────────────────────────────────────────────────────────────────

    # Smallest y-axis span per graph, in that graph's own units.  Without this a
    # dead-flat trace would autoscale onto its own sensor quantisation — the
    # Alicat's ±0.001 barA last digit would fill the plot as a square wave.
    ALICAT_MIN_SPAN_FLOW     = 20.0    # sccm
    ALICAT_MIN_SPAN_PRESSURE = 0.05    # barA

    @Slot()
    def _update_graphs(self):
        """Redraw the live mass flow and pressure traces from the Alicat buffer.

        Both y-axes track the data currently on screen rather than sitting on a
        fixed range, so small variations stay readable at low flows and at
        near-atmospheric pressures.
        """
        lb = self.pressure_data['live_buffer']
        ts = lb['timestamps']
        if not ts:
            return
        t_max = max(ts[-1], 10.0)
        x_lo, x_hi = max(0.0, t_max - 30), t_max

        # Autoscale against the samples actually on screen, not the whole 60s
        # buffer — otherwise an old spike keeps the axis stretched after it
        # has scrolled out of view.
        first = next((i for i, t in enumerate(ts) if t >= x_lo), 0)

        for widget, curve, ys, min_span in (
                (self._flow_graph_widget, self._flow_curve,     lb['flows'],
                 self.ALICAT_MIN_SPAN_FLOW),
                (self._graph_widget,      self._pressure_curve, lb['pressures'],
                 self.ALICAT_MIN_SPAN_PRESSURE)):
            curve.setData(ts, ys)
            widget.setXRange(x_lo, x_hi, padding=0.02)

            window = ys[first:] or ys
            lo, hi = min(window), max(window)
            centre = (lo + hi) / 2.0
            span   = max(hi - lo, min_span) * 1.3      # 15% headroom above and below
            y_lo, y_hi = centre - span / 2.0, centre + span / 2.0
            if y_lo < 0:                                # neither quantity goes negative
                y_lo = 0.0
                y_hi = max(y_hi, min_span)
            widget.setYRange(y_lo, y_hi, padding=0)

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Camera
    # ─────────────────────────────────────────────────────────────────────────

    def _update_cam_capacity(self):
        """Recalculate and display how many frames/seconds the camera RAM can hold."""
        _RAM_BYTES = 18 * 1024 ** 3  # Phantom Veo-E 340L — 18 GB
        try:
            fps    = float(self._cam_fps.text())
            width  = int(self._cam_width.text() or 1)
            height = int(self._cam_height.text() or 1)
            if fps <= 0 or width <= 0 or height <= 0:
                raise ValueError
            bytes_per_frame = width * height * 2   # 12-bit Phantom data in 16-bit containers
            max_frames = int(_RAM_BYTES / bytes_per_frame)
            max_secs   = max_frames / fps
            if max_secs >= 60:
                time_str = f"{max_secs/60:.1f} min"
            else:
                time_str = f"{max_secs:.1f} s"
            self._cam_capacity_lbl.setText(time_str)
            self._cam_capacity_frames_lbl.setText(f"({max_frames:,} frames)")
        except (ValueError, ZeroDivisionError):
            self._cam_capacity_lbl.setText("—")
            self._cam_capacity_frames_lbl.setText("")

    def _set_live_status(self, text, color=CLR_TEXT_SEC):
        """Short status in the Live Camera View title row; full text on hover."""
        short = text if len(text) <= 32 else text[:31] + "…"
        self._live_status_lbl.setText(short)
        self._live_status_lbl.setToolTip(text)
        self._live_status_lbl.setStyleSheet(f"color:{color}; font-size:11px;")

    def _cam_connect(self):
        if not self.phantom:
            self._cam_status_lbl.setText("Camera SDK unavailable")
            self._set_live_status("Camera SDK unavailable", CLR_ORANGE); return
        try:
            self.phantom.connect()
            self._cam_status_lbl.setText("Camera: connected")
            self._cam_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;")
            self._set_live_status("Camera: connected", CLR_GREEN)
            self._hdr_camera_dot.setStyleSheet(f"color:{CLR_GREEN}; font-size:10px; background:transparent;")
            self._hdr_camera_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        except Exception as e:
            self._cam_status_lbl.setText(f"Camera error: {e}")
            self._set_live_status(f"Camera error: {e}", CLR_RED)
            self._set_status(f"Camera: {e}", CLR_RED)

    def _cam_ping(self):
        if not self.phantom: return
        ok = self.phantom.ping()
        self._cam_status_lbl.setText("Camera: connected ✓" if ok else "Camera: not responding")
        self._set_live_status("Camera: reachable ✓" if ok else "Camera: not responding",
                              CLR_GREEN if ok else CLR_RED)

    def _get_ai_stride(self) -> int:
        """Stride from the field, falling back to the default if unusable."""
        try:
            return max(1, int(self._ai_stride.text()))
        except (ValueError, AttributeError):
            return self.DEFAULT_STRIDE

    def _update_stride_note(self):
        """Live cost of the current stride at the camera's current settings.

        Reads fps and the capture length from the live fields, so changing the
        frame rate updates the note without needing Apply Config.
        """
        if not hasattr(self, "_ai_stride_note"):
            return
        if not self._pipeline_check.isChecked():
            self._ai_stride_note.setText("AI analysis off — the capture is saved and nothing else runs.")
            return

        stride = self._get_ai_stride()
        try:
            fps = float(self._cam_fps.text())
        except (ValueError, AttributeError):
            fps = 0.0

        parts = []
        if fps > 0:
            gap_ms = stride * 1000.0 / fps
            decor = gap_ms / self.DECORRELATION_MS
            ideal = max(1, round(self.DECORRELATION_MS * fps / 1000.0))
            parts.append(f"stride {stride} at {fps:.0f} fps = {gap_ms:.1f} ms apart "
                         f"({decor:.2f}× the ~{self.DECORRELATION_MS:.1f} ms decorrelation time)")
            if decor < 0.9:
                parts.append(f"⚠ below one decorrelation time — frames share droplets, "
                             f"so the extra compute buys little new information "
                             f"(stride {ideal} matches it)")
        else:
            parts.append(f"stride {stride} — set a frame rate to see the timing")

        pre, post = self._cam_frame_counts()
        total = pre + post
        if total > 0:
            n = max(1, total // stride)
            try:
                mp = (float(self._cam_width.text()) *
                      float(self._cam_height.text())) / 1e6
            except (ValueError, AttributeError):
                mp = 0.0
            if mp > 0:
                secs = n * mp * self.INFERENCE_S_PER_MEGAPIXEL
                parts.append(f"{total:,} captured → {n:,} analysed → "
                             f"~{self._fmt_eta(secs)} inference at {mp:.1f} MP "
                             f"(plus extraction)")
            else:
                parts.append(f"{total:,} captured → {n:,} analysed")
        self._ai_stride_note.setText(".  ".join(parts) + ".")

    @classmethod
    def _transfer_summary(cls, path: str, elapsed: float) -> str:
        """One line describing how fast a file actually came off the camera.

        Measured 2026-09-28 on the Gigabit link: 71.7 MB/s (574 Mbit/s).  The
        same rig managed 7.8 MB/s while the camera was on a 100 Mbit adapter,
        so a rate printed every save is the cheapest possible guard against
        silently regressing to that — it took a stopwatch and a file size to
        find it the first time.
        """
        try:
            mb = os.path.getsize(path) / 1e6
        except OSError:
            return f"── .cine saved in {cls._fmt_eta(elapsed)} ──"
        if elapsed <= 0:
            return f"── .cine saved: {mb:,.0f} MB ──"
        rate = mb / elapsed
        warn = "   ⚠ well below the 71 MB/s this link has done" if rate < 40 else ""
        return (f"── .cine saved: {mb:,.0f} MB in {cls._fmt_eta(elapsed)}"
                f"  ({rate:.1f} MB/s = {rate * 8:.0f} Mbit/s){warn} ──")

    @staticmethod
    def _fmt_eta(seconds) -> str:
        """Human-readable time remaining, e.g. '45s', '2m 05s', '1h 12m'."""
        if seconds is None:
            return "estimating…"
        seconds = int(round(seconds))
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m {seconds % 60:02d}s"
        return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"

    def _cam_frame_counts(self):
        """Pre/post-trigger frame counts from the CURRENT camera fields.

        Read live rather than from a cache.  These counts decide how much of the
        ring buffer gets saved, and they used to be set only by Apply Config —
        so a freshly launched GUI held 0, the save range came out as None, and
        the whole buffer was written instead of the configured window.

        Returns (0, 0) when the fields aren't usable, which callers treat as
        "save everything" — the same as the old behaviour, and lossless.
        """
        try:
            fps = float(self._cam_fps.text())
        except (ValueError, AttributeError):
            return 0, 0
        if fps <= 0:
            return 0, 0

        def _frames(field):
            try:
                secs = float(field.text())
            except (ValueError, AttributeError):
                return 0
            # At least one frame even for 0 s, so a valid config never
            # collapses to "no range" and re-triggers the full-buffer save.
            return max(1, int(secs * fps))

        return _frames(self._cam_pre_s), _frames(self._cam_post_s)

    def _cam_refuse_while_saving(self, action: str) -> bool:
        """True (and say so) if a capture is still being saved off the camera.
        `action` would overwrite or clear camera RAM and lose that capture."""
        if not self._cam_saving:
            return False
        self._log(f"{action} refused: the last capture is still being saved off the "
                  "camera, and this would wipe it from camera RAM.")
        self._set_status(f"{action} refused: camera is still saving", CLR_ORANGE)
        return True

    def _cam_configure(self):
        if not self.phantom: return
        if self._cam_refuse_while_saving("Apply Config"): return
        try:
            fps       = float(self._cam_fps.text())
            pre_frames, post_frames = self._cam_frame_counts()
            self._cam_pre_frames  = pre_frames
            self._cam_post_frames = post_frames
            self.phantom.configure(
                width=int(self._cam_width.text()),
                height=int(self._cam_height.text()),
                fps=fps,
                exposure_us=float(self._cam_exp.text()),
                post_trigger_frames=post_frames,
                exp_index=int(self._cam_exp_idx.text() or "0"),
            )
            self._cam_status_lbl.setText(
                f"Config applied — {pre_frames} pre / {post_frames} post frames")
            self._save_camera_settings()
        except Exception as e:
            self._set_status(f"Camera config error: {e}", CLR_RED)

    def _set_trigger_enabled(self, on: bool):
        """Enable/disable BOTH Trigger buttons -- the Camera tab's and the copy
        beside Start Experiment. Every state change goes through here so the
        two can never disagree (e.g. one still live while a save is running)."""
        for btn in (getattr(self, "_cam_trigger_btn", None),
                    getattr(self, "_bar_trigger_btn", None)):
            if btn is not None:
                btn.setEnabled(on)

    def _set_camera_armed_indicator(self, colour: str):
        """Coloured border on the Camera header box: orange=armed, green=recording, transparent=off."""
        self._hdr_camera_box.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: 1px solid {colour};
                border-radius: 5px;
            }}
        """)

    def _cam_arm(self):
        """Start continuous ring-buffer recording. Camera buffers until Trigger is clicked."""
        if not self.phantom: return
        if self._cam_refuse_while_saving("Arm"): return
        def _do_arm():
            try:
                self.phantom.start_recording()
                QTimer.singleShot(0, self, lambda: (
                    self._cam_status_lbl.setText("Armed — buffering…"),
                    self._cam_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;"),
                    self._cam_arm_status_lbl.setText("Armed — buffering…"),
                    self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;"),
                    self._cam_arm_btn.setEnabled(False),
                    self._set_trigger_enabled(True),
                    self._set_camera_armed_indicator(CLR_ORANGE),
                ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, self, lambda: (
                    self._set_status(f"Arm error: {err}", CLR_RED),
                    self._cam_arm_status_lbl.setText("Arm failed"),
                ))
        threading.Thread(target=_do_arm, daemon=True).start()

    def _cam_abort(self):
        if self._cam_refuse_while_saving("Disarm / Abort"): return
        self._auto_trigger_cancel("camera disarmed")
        if self.phantom: self.phantom.abort()
        self._cam_status_lbl.setText("Camera: disarmed")
        self._cam_arm_status_lbl.setText("Not armed")
        self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._cam_arm_btn.setEnabled(True)
        self._set_trigger_enabled(False)
        self._set_camera_armed_indicator("transparent")

    # ── Auto-trigger at the end of a test ────────────────────────────────────

    def _auto_trigger_check(self, distance, speed):
        """Before Start Experiment: None if auto-trigger is off or there is no camera,
        a plan dict to schedule, or "cancel" if the user backed out of a test that is
        too short for the video."""
        if not (hasattr(self, "_auto_trig_chk") and self._auto_trig_chk.isChecked()):
            return None
        if not (self.phantom and self.phantom.is_connected):
            self._log("Auto-trigger is ticked but the camera is not connected: "
                      "this run will have no video.")
            self._set_status("Auto-trigger skipped: camera not connected", CLR_ORANGE)
            return None
        try:
            pre_s = float(self._cam_pre_s.text() or 0)
            post_s = float(self._cam_post_s.text() or 0)
        except ValueError:
            self._warn("Auto-trigger", "Pre-trigger and Post-trigger (s) must be numbers.")
            return "cancel"
        plan = auto_trigger_plan(distance, speed, pre_s, post_s)
        if plan["fits"]:
            return plan
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Test shorter than the video")
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setText(
            f"This test runs for {plan['test_s']:.1f} s, but the video is "
            f"{pre_s + post_s:g} s and auto-trigger keeps a 2 s margin before the end.\n\n"
            "Trigger as soon as the camera is buffering (the video will run past the "
            "end of the test), start without auto-trigger, or cancel?")
        early = dlg.addButton("Trigger early", QMessageBox.ButtonRole.AcceptRole)
        without = dlg.addButton("Start without", QMessageBox.ButtonRole.DestructiveRole)
        dlg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dlg.exec()
        if dlg.clickedButton() == early:
            plan["trigger_s"] = max(plan["trigger_s"], 1.0 + pre_s)
            return plan
        if dlg.clickedButton() == without:
            return None
        return "cancel"

    def _auto_trigger_schedule(self, plan):
        if self._cam_saving:
            # Arming now would record over the capture still being saved.
            self._log("Auto-trigger: the camera is still saving the previous capture, "
                      "so it can't be armed. This run will have no video.")
            self._set_status("Auto-trigger skipped: camera still saving", CLR_ORANGE)
            return
        if not self.phantom.is_armed:
            self._cam_arm()                       # buffering from now on
        delay_ms = int(max(plan["trigger_s"], 1.0) * 1000)
        self._auto_trig_due = time.time() + delay_ms / 1000
        self._auto_trig_timer.start(delay_ms)
        self._auto_trig_tick.start()
        a, b = plan["window_s"]
        self._log(f"Auto-trigger: test {plan['test_s']:.1f} s; camera fires {delay_ms / 1000:.1f} s "
                  f"after Start, saving {a:.1f}–{b:.1f} s (the traverse stops at {plan['end_s']:.1f} s).")
        self._auto_trigger_countdown()

    def _auto_trigger_countdown(self):
        if self._auto_trig_due is None:
            self._auto_trig_tick.stop()
            return
        left = max(0, int(round(self._auto_trig_due - time.time())))
        self._cam_arm_status_lbl.setText(f"Auto-trigger in {left} s")
        self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_ORANGE}; font-size:12px;")

    def _auto_trigger_fire(self):
        self._auto_trig_due = None
        self._auto_trig_tick.stop()
        if not self.pressure_data['experiment_active']:
            self._log("Auto-trigger: the run had already stopped; not fired.")
            return
        if not (self.phantom and self.phantom.is_armed):
            self._log("Auto-trigger: the camera was not armed (already triggered, or arming "
                      "failed); not fired.")
            self._set_status("Auto-trigger did not fire: camera not armed", CLR_ORANGE)
            return
        self._log("Auto-trigger: firing the camera.")
        self._cam_trigger()

    def _auto_trigger_cancel(self, why):
        timer = getattr(self, "_auto_trig_timer", None)        # None during start-up
        if timer is None or (self._auto_trig_due is None and not timer.isActive()):
            return
        self._auto_trig_timer.stop()
        self._auto_trig_tick.stop()
        self._auto_trig_due = None
        self._log(f"Auto-trigger cancelled: {why}.")

    def _on_save_format_changed(self, source: str):
        """Keep at least one save format ticked, then persist the pair.

        Both may be on.  Turning off whichever one was ticked last leaves the
        capture with nothing to write, so the *other* box is flipped back on —
        the one the user just clicked stays off, as they asked.
        """
        if self._save_fmt_guard:
            return
        if not (self._cam_save_video_chk.isChecked() or self._cam_save_tiffs_chk.isChecked()):
            other = self._cam_save_tiffs_chk if source == "cine" else self._cam_save_video_chk
            self._save_fmt_guard = True
            try:
                other.setChecked(True)
            finally:
                self._save_fmt_guard = False
        self._save_camera_settings()

    def _cam_trigger(self):
        """Fire the trigger — freeze the ring buffer and save pre+post window."""
        if not self.phantom: return
        run_pipeline  = self._pipeline_check.isChecked()
        save_video    = self._cam_save_video_chk.isChecked()
        save_tiffs    = self._cam_save_tiffs_chk.isChecked()
        # Derive from the live fields so the values on screen are the ones used,
        # falling back to whatever Apply Config last pushed to the camera.
        pre_frames, post_frames = self._cam_frame_counts()
        if pre_frames  <= 0: pre_frames  = self._cam_pre_frames
        if post_frames <= 0: post_frames = self._cam_post_frames
        run_folder    = self._run_folder
        ts = datetime.now().strftime("%H%M%S")

        # Update UI immediately so the user knows the trigger was received
        self._set_trigger_enabled(False)
        self._cam_arm_btn.setEnabled(False)
        self._cam_arm_status_lbl.setText("Triggered — saving…")
        self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_ORANGE}; font-size:12px;")
        self._set_camera_armed_indicator(CLR_GREEN)

        if run_folder:
            # Mid-experiment: write into the active run folder
            cine_path    = os.path.join(run_folder, "shadowgraph", "raw", "CINE",
                                        f"recording_{ts}.cine")
            tiff_dir     = os.path.join(run_folder, "shadowgraph", "raw", "TIFFs")
        else:
            # Manual trigger — create a new run folder with the same structure
            _now   = datetime.now()
            _lacie = find_lacie_drive()
            _base  = os.path.join(_lacie, "Experiments") if _lacie else os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "experiment_logs", "Experiments")
            _run_folder = os.path.join(
                _base, _now.strftime("%Y"), _now.strftime("%m"),
                _now.strftime("%d"), f"{_now.strftime('%H%M%S')}_Manual")
            # As above: TIFFs/ is made on demand only.
            for _sub in [os.path.join("shadowgraph", "raw", "CINE"),
                         os.path.join("shadowgraph", "analysis"),
                         "cone"]:
                os.makedirs(os.path.join(_run_folder, _sub), exist_ok=True)
            cine_path    = os.path.join(_run_folder, "shadowgraph", "raw", "CINE",
                                        f"recording_{ts}.cine")
            tiff_dir     = os.path.join(_run_folder, "shadowgraph", "raw", "TIFFs")
            # Update the save path label to show where this capture went
            QTimer.singleShot(0, self,
                lambda p=_run_folder: self._cam_save_lbl.setText(f"Saving to: {p}"))

        frame_range = (-pre_frames, post_frames - 1) if pre_frames > 0 else None
        self._cam_saving = True     # cleared when the save thread ends, either way

        def _do_trigger():
            import glob as _glob
            import traceback as _tb
            step = "trigger"
            try:
                QTimer.singleShot(0, self, lambda: self._cam_arm_status_lbl.setText("Triggering…"))
                self.phantom.trigger()
                _trigger_wall = time.time()
                fps_val = float(self._cam_fps.text()) if self._cam_fps.text() else 1000.0
                if self.pressure_data.get('experiment_active') and \
                        self.pressure_data.get('experiment_start_time') is not None:
                    _trel = _trigger_wall - self.pressure_data['experiment_start_time']
                    self.pressure_data['camera_windows'].append((
                        _trel - pre_frames / fps_val,
                        _trel + post_frames / fps_val,
                    ))
                # Wait for the camera to finish its post-trigger frames and store
                # the cine.  How long that takes is set by the CAMERA's
                # post-trigger count and frame rate, which need not match the
                # fields (edited since Apply Config, or camera power-cycled).  A
                # fixed sleep based on the fields could open the cine while the
                # camera was still recording it.  Polls partition_recorded, not
                # cam.Cine(), which can block in the SDK without raising.
                step = "waiting for the camera to store the cine"
                cam_pt = self.phantom.camera_post_trigger()
                if cam_pt is not None:
                    cam_post, cam_fps = cam_pt
                    if cam_post != post_frames:
                        self._log_queue.put(
                            f"  Note: the camera is set to {cam_post} post-trigger frames "
                            f"but the fields give {post_frames}. Press Apply Config to "
                            "make them agree; waiting on the camera's count.")
                    expect = cam_post / max(cam_fps, 1.0)
                else:
                    expect = post_frames / fps_val
                QTimer.singleShot(0, self,
                    lambda s=expect: self._cam_arm_status_lbl.setText(
                        f"Recording post-trigger ({s:.1f} s)…"))
                time.sleep(min(expect, 0.5))
                stored = self.phantom.wait_for_stored(1, timeout_s=expect + 15.0)
                if stored is None:
                    time.sleep(max(0.0, expect - 0.5) + 2.0)     # can't ask: old fixed settle
                elif not stored:
                    self._log_queue.put(
                        f"  Warning: the camera hadn't reported the cine stored "
                        f"{expect + 15:.0f} s after the trigger; trying the save anyway.")
                else:
                    time.sleep(0.5)      # let the camera finish committing the header

                def _progress_reporter(label):
                    """Progress callback: status label, progress bar, and console.

                    The status label updates on every percent, but the console
                    gets one line per CONSOLE_PROGRESS_STEP% — a 100-line wall
                    of progress would push the rest of the run's log out of
                    view, which is the thing the console is actually for.
                    """
                    state = {"next_log": 0}
                    def _cb(pct, eta=None):
                        txt = f"{label} {pct}%"
                        if eta is not None:
                            txt += f" — {self._fmt_eta(eta)} left"
                        QTimer.singleShot(0, self, lambda p=pct, t=txt: (
                            self._cam_save_progress.setValue(p),
                            self._cam_arm_status_lbl.setText(t),
                        ))
                        if pct >= state["next_log"] or pct >= 100:
                            state["next_log"] = pct + self.CONSOLE_PROGRESS_STEP
                            self._log_queue.put(f"  {txt}")
                    return _cb

                # 1 — save .cine (optional)
                if save_video:
                    QTimer.singleShot(0, self, lambda: (
                        self._cam_arm_status_lbl.setText("Saving .cine…"),
                        self._cam_save_progress.setValue(0),
                        self._cam_save_progress.setVisible(True),
                    ))
                    _t_cine = time.time()
                    step = "saving the .cine"
                    self._log_queue.put(f"── saving .cine → {os.path.basename(cine_path)} ──")
                    self.phantom.save_recording(cine_path, file_format='cine',
                                                frame_range=frame_range,
                                                progress_cb=_progress_reporter("Saving .cine"))
                    # Report the achieved rate, not just that it finished — a
                    # save that silently drops to 8 MB/s is the difference
                    # between 3 minutes and half an hour, and the only way to
                    # notice is to print it every time.
                    self._log_queue.put(self._transfer_summary(cine_path, time.time() - _t_cine))
                    QTimer.singleShot(0, self, lambda: self._cam_save_progress.setValue(0))

                # 2 — read frames from camera RAM and write TIFFs ourselves.
                # This bypasses the SDK's save() which has a known bug that throws
                # an exception even when the save succeeds.
                if save_tiffs:
                    QTimer.singleShot(0, self, lambda: (
                        self._cam_arm_status_lbl.setText("Saving TIFFs…"),
                        self._cam_save_progress.setValue(0),
                        self._cam_save_progress.setVisible(True),
                    ))
                    os.makedirs(tiff_dir, exist_ok=True)
                    for _old in (_glob.glob(os.path.join(tiff_dir, "*.tif")) +
                                 _glob.glob(os.path.join(tiff_dir, "*.tiff"))):
                        try: os.remove(_old)
                        except OSError: pass
                    _t_tiff = time.time()
                    step = "saving TIFFs"
                    self._log_queue.put("── saving TIFFs ──")
                    self.phantom.save_tiffs_from_ram(tiff_dir, tiff_prefix='frame',
                                                     frame_range=frame_range,
                                                     progress_cb=_progress_reporter("Saving TIFFs"))
                    self._log_queue.put(
                        f"── TIFFs done in {self._fmt_eta(time.time() - _t_tiff)} ──")
                    QTimer.singleShot(0, self, lambda: self._cam_save_progress.setVisible(False))

                    # 2b — auto-run lamella batch on saved TIFFs if analysis is enabled
                    if self._lamella_on:
                        _captured_tiff_dir = tiff_dir
                        self._last_tiff_dir = _captured_tiff_dir
                        QTimer.singleShot(0, self,
                            lambda d=_captured_tiff_dir: self._lamella_run_batch_auto(d))

                else:
                    # No TIFF sequence on disk — the AI and lamella steps both
                    # read from it, so they have nothing to work on.
                    if run_pipeline or self._lamella_on:
                        QTimer.singleShot(0, self, lambda: self._log(
                            "  (Save TIFFs is off — AI pipeline and lamella "
                            "analysis skipped for this capture)"))

                QTimer.singleShot(0, self,
                    lambda: self._cam_status_lbl.setText("Trigger saved ✓"))

                # 4 — AI chain, ONLY if "Run AI analysis after capture" is ticked.
                #
                # Runs on the saved .cine, not on the brightest frame: the whole
                # measurement is a per-run statistic over many frames, so a
                # single frame cannot produce it. Same entry point the Test
                # Pipeline button uses, so a dry run there proves this path.
                if run_pipeline:
                    if save_video and os.path.exists(cine_path):
                        # <run>/shadowgraph/raw/CINE/recording.cine -> <run>.
                        # parents[] is indexed from the FILE, so the run root is
                        # [3], not [2]: three dirname() calls land on
                        # <run>/shadowgraph and process_capture then builds
                        # <run>/shadowgraph/shadowgraph/raw/CINE, decides the
                        # cine is missing, and copies the whole 14 GB into it.
                        _run_folder_for_ai = str(Path(cine_path).parents[3])
                        QTimer.singleShot(0, self, lambda c=cine_path, r=_run_folder_for_ai: (
                            self._log("── AI analysis enabled — starting on the saved .cine ──"),
                            self._run_ai_chain(c, run_dir=r),
                        ))
                    else:
                        QTimer.singleShot(0, self, lambda: (
                            self._set_status(
                                "AI analysis needs the .cine — tick Save video (.cine)",
                                CLR_ORANGE),
                            self._log("  (AI analysis skipped: no .cine was saved)"),
                        ))

                # 5 — re-arm automatically so the camera is ready for the next trigger.
                # The flag is cleared first: the re-arm runs on the GUI thread and
                # would otherwise be refused as "still saving".
                self._cam_saving = False
                QTimer.singleShot(0, self, self._cam_arm)

            except Exception as e:
                self._cam_saving = False
                err = f"{type(e).__name__}: {e}"
                # The console, not just the status bar: the end-of-run auto-save
                # overwrites the status bar seconds later, and that is how the
                # cause of a lost capture went unrecorded (2026-10-12).
                try:
                    log_serial(f"Camera capture failed while {step}:\n{_tb.format_exc()}")
                except Exception:
                    pass
                in_ram = None
                try:
                    in_ram = bool(self.phantom.cam.partition_recorded(1))
                except Exception:
                    pass
                if in_ram:
                    advice = ("The recording is still in camera RAM. Save it from PCC "
                              "before pressing Arm: arming records over it.")
                elif in_ram is False:
                    advice = "The camera reports no stored recording."
                else:
                    advice = ("Check PCC for the recording before pressing Arm: "
                              "arming records over it.")
                self._log_queue.put(f"CAMERA CAPTURE FAILED while {step}: {err}")
                self._log_queue.put(f"  {advice}")
                QTimer.singleShot(0, self, lambda: (
                    self._set_status(f"Capture failed while {step}: {err}", CLR_RED),
                    self._cam_arm_status_lbl.setText("Capture failed — see console"),
                    self._cam_arm_btn.setEnabled(True),
                    self._set_camera_armed_indicator("transparent"),
                    self._cam_save_progress.setVisible(False),
                ))

        threading.Thread(target=_do_trigger, daemon=True).start()

    def _get_px_per_mm(self) -> float:
        """Return the current calibrated px/mm value, falling back to 0.0 if not set."""
        txt = self._hdr_pxmm_lbl.text().replace("px/mm", "").strip()
        try:
            return float(txt) if txt not in ("–", "") else 0.0
        except ValueError:
            return 0.0

    def _on_pipeline_complete(self, results: dict):
        """
        Display a finished measure_run summary.

        Shows the LOWEST-D32 frame rather than the brightest one -- the old CV
        path picked by image brightness, which says nothing about the spray.
        Lowest D32 is the finest-atomised frame in the run, which is the one
        worth looking at.
        """
        self._pipeline_status.setText("Pipeline: complete ✓")
        self._log("── AI chain complete ✓ ──")
        self._flash_log_border(CLR_GREEN)
        # Full Analyse Cine re-analyses some OTHER cine. Its numbers must never
        # reach the master log: the row is matched on the last experiment's
        # start time, so they would overwrite that real run's D32 -- both via
        # the auto-save below and via a later manual Save reading
        # _last_ai_results.
        to_log = results.get("_save_to_log", True)
        if to_log:
            # Held for the spreadsheet row. Cleared at experiment start so a run
            # whose AI chain has not finished can never inherit the previous
            # run's D32 -- a stale number in the master log is worse than a
            # blank one.
            self._last_ai_results = results

        self._test_pipeline_btn.setEnabled(True)
        self._test_pipeline_btn.setText(self.FULL_ANALYSE_LABEL)

        d32 = results.get("d32_in_focus_um")
        ci = results.get("d32_ci95") or [None, None]
        # The quoted atomised fraction is the CLASSICAL one. measure_run's
        # model-only figure is shown only if the classical stage did not run.
        cls = results.get("_classical") or {}
        if cls.get("atomised_pct_pooled") is not None:
            atom, aci, atom_src = (cls["atomised_pct_pooled"],
                                   cls.get("atomised_ci95") or [None, None], "classical")
        else:
            atom, aci, atom_src = (results.get("atomised_pct"),
                                   results.get("atomised_ci95") or [None, None], "model-only")
        n_focus = results.get("droplets_in_focus")

        # The two headline numbers carry the value only; both confidence
        # intervals live in the Confidence slot, so the run's precision is read
        # in one place rather than as two separate +/- tails.
        self._ai_diameter_lbl.setText(
            f"Run SMD: {d32:.1f} µm" if d32 is not None else "Run SMD: –")
        self._ai_dl_lbl.setText(
            f"Atomised Fraction ({atom_src}): {atom:.2f} %" if atom is not None
            else "Atomised Fraction: –")

        # Line 1 — precision of the two run numbers.
        bits = []
        if d32 is not None and None not in ci:
            half = (ci[1] - ci[0]) / 2
            bits.append(f"SMD {ci[0]:.1f}–{ci[1]:.1f} µm (±{100 * half / d32:.1f}%)"
                        if d32 else f"SMD {ci[0]:.1f}–{ci[1]:.1f} µm")
        if atom is not None and None not in aci:
            ahalf = (aci[1] - aci[0]) / 2
            bits.append(f"atomised {aci[0]:.2f}–{aci[1]:.2f} % "
                        f"(±{100 * ahalf / atom:.0f}%)" if atom
                        else f"atomised {aci[0]:.2f}–{aci[1]:.2f} %")
        # Line 3 — what the numbers were computed FROM. Its own line because
        # it answers a different question again: not how precise or how
        # varied, but how much evidence is behind them.
        frames = results.get("_frames", results.get("frames", "?"))
        counted = []
        if frames not in (None, "?"):
            stride = results.get("_stride")
            counted.append(f"{frames:,} frames" if isinstance(frames, int)
                           else f"{frames} frames")
            if stride:
                counted.append(f"stride {stride}")
        if n_focus is not None:
            counted.append(f"{n_focus:,} in-focus droplets")
        n_oof = results.get("droplets_out_of_focus")
        if n_oof is not None:
            counted.append(f"{n_oof:,} out of focus")

        # Line 2 — the SIZE DISTRIBUTION, which is a different thing entirely.
        # Kept on its own line and explicitly labelled so the spread is never
        # mistaken for an error bar on the SMD above it.
        mean = results.get("droplet_d_mean_um")
        sd   = results.get("droplet_d_std_um")
        dmin = results.get("droplet_d_min_um")
        dmax = results.get("droplet_d_max_um")
        dist = []
        if mean is not None:
            dist.append(f"mean {mean:.1f} µm")
        if sd is not None:
            dist.append(f"SD {sd:.1f} µm")
        if dmin is not None and dmax is not None:
            dist.append(f"range {dmin:.1f}–{dmax:.1f} µm")

        lines = []
        if bits:
            lines.append("95% CI:  " + "   ".join(bits))
        if dist:
            lines.append("Droplet spread:  " + "   ".join(dist))
        if counted:
            lines.append("Measured from:  " + "   ".join(counted))
        self._ai_confidence_lbl.setText("\n".join(lines) if lines else "Confidence: –")

        self._log(f"  D32 {d32} µm   95% CI {ci}")
        self._log(f"  atomised ({atom_src}) {atom} %   95% CI {aci}")
        _sv = (results.get("provenance") or {}).get("sizer_version")
        if _sv:
            self._log(f"  sizer {_sv}")
        if results.get("_classical_error"):
            self._log(f"  classical stage failed: {results['_classical_error']}")

        # Stage breakdown, so a slow run says WHICH stage was slow.
        stages = results.get("_stage_seconds") or {}
        if stages:
            total = results.get("_elapsed_total_s") or sum(stages.values())
            self._log("  ── stage breakdown ──")
            for name, secs in stages.items():
                share = f"{secs / total * 100:3.0f}%" if total else "  ?"
                self._log(f"    {name:16s}{self._fmt_eta(secs):>10}  {share}")
            self._log(f"    {'TOTAL':16s}{self._fmt_eta(total):>10}")

        # The marked-up extreme frames, lowest-D32 included, live in the
        # Extremes tab alongside the whole-run numbers above.
        self._update_extremes_tab(results)
        ext = (results.get("d32_extreme_frames") or {}).get("lowest") or {}
        if ext.get("frame"):
            self._log(f"  lowest-D32 frame: {ext['frame']} ({ext.get('d32_um')} µm)")
        self._autosave_after_ai(to_log)

    def _autosave_after_ai(self, to_log=True):
        """Second save, once the AI chain has produced numbers and an image.

        The end-of-experiment save runs when the motor stops, which is minutes
        before inference and measurement finish -- so that row has no D32, no
        atomised fraction and no shadowgraph. Saving again here fills them in.
        It UPDATES the same row rather than adding one, matched on the
        experiment's start timestamp.
        """
        if not to_log:
            self._log("  Full Analyse Cine -- master_log not touched.")
            return
        def _after(ok, err):
            if ok:
                self._log("  master_log updated with the AI results.")
            else:
                self._log(f"  (auto-save after AI failed: {err} -- use Save to Excel)")
        try:
            self._save_to_excel_async(on_done=_after)
        except Exception as e:
            self._log(f"  (auto-save after AI failed: {e} -- use Save to Excel)")

    def _on_pipeline_error(self, err: str):
        self._pipeline_status.setText(f"Pipeline error: {err}")
        self._log(f"── AI chain error: {err} ──")
        self._flash_log_border("#ff3b30")
        self._test_pipeline_btn.setEnabled(True)
        self._test_pipeline_btn.setText(self.FULL_ANALYSE_LABEL)

    # Per-frame costs measured on the lab PC, 2026-10-01 (Trial_CINE, 500 fps,
    # 2560x1600). Used only for the Full Analyse estimate -- approximate, and
    # inference scales with detection density, not just frame count.
    _EST_EXTRACT_FPS = 2.4
    _EST_INFER_S = 3.45
    _EST_MEASURE_S = 0.2
    _EST_IMAGE_S = 0.9
    _EST_COPY_S = 300

    @staticmethod
    def _ai_code_on_path():
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "..", "AI", "Real_Data_Code")
        if p not in sys.path:
            sys.path.insert(0, p)

    def _ask_full_analyse_stride(self, prev, reusable):
        """Ask which stride to analyse a picked cine at.

        Offers the stride it was analysed at before (reusing that analysis, so
        only the images are drawn) or a typed stride, which re-runs the AI into
        a new Trial folder. Returns (stride, reuse) or None if cancelled.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("Full Analyse Cine")
        v = QVBoxLayout(dlg)
        total = (prev or {}).get("total_frames_in_cine")

        rb_prev, prev_stride = None, None
        if prev and prev.get("stride"):
            prev_stride = int(prev["stride"])
            n_prev = prev.get("frame_count") or 0
            when = str(prev.get("extracted_utc", ""))[:10]
            v.addWidget(QLabel(
                f"This cine was analysed at <b>stride {prev_stride}</b> "
                f"({n_prev:,} of {total:,} frames) on {when}."
                if total else
                f"This cine was analysed at <b>stride {prev_stride}</b> "
                f"({n_prev:,} frames) on {when}."))
            if reusable:
                secs = n_prev * (self._EST_MEASURE_S + self._EST_IMAGE_S)
                text = (f"Use stride {prev_stride} — reuse the AI results and just "
                        f"draw all {n_prev:,} images (~{self._fmt_eta(secs)})")
            else:
                text = (f"Use stride {prev_stride} — re-run (the previous frames or "
                        f"predictions are missing or out of date)")
            rb_prev = QRadioButton(text)
            rb_prev.setChecked(True)
            v.addWidget(rb_prev)
        else:
            v.addWidget(QLabel("No previous analysis found next to this cine."))

        row = QHBoxLayout()
        rb_new = QRadioButton("Use a different stride:" if rb_prev else "Stride:")
        edit = QLineEdit("1")
        edit.setFixedWidth(56)
        edit.setValidator(QIntValidator(1, 1000))
        row.addWidget(rb_new)
        row.addWidget(edit)
        row.addWidget(QLabel("(1 = every frame)"))
        row.addStretch()
        v.addLayout(row)
        if rb_prev is None:
            rb_new.setChecked(True)

        est = QLabel("")
        est.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        est.setWordWrap(True)
        v.addWidget(est)

        def _update_estimate():
            try:
                s = max(1, int(edit.text()))
            except ValueError:
                est.setText("")
                return
            if total:
                n = -(-total // s)
                secs = (self._EST_COPY_S + n / self._EST_EXTRACT_FPS
                        + n * (self._EST_INFER_S + self._EST_MEASURE_S + self._EST_IMAGE_S))
                est.setText(f"Stride {s}: {n:,} frames, ~{self._fmt_eta(secs)} "
                            f"(approx., from the 2026-10-01 timings). Re-runs the "
                            f"AI into a new Trial folder.")
            else:
                est.setText(f"Stride {s}: re-runs the AI into a new Trial folder.")

        edit.textChanged.connect(_update_estimate)
        edit.textEdited.connect(lambda _t: rb_new.setChecked(True))
        _update_estimate()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        if rb_prev is not None and rb_prev.isChecked():
            return prev_stride, reusable
        try:
            s = max(1, int(edit.text()))
        except ValueError:
            return None
        return s, (reusable and s == prev_stride)

    def _run_test_pipeline(self):
        """
        Full Analyse Cine: pick a .cine, choose a stride, and run the AI chain
        drawing a marked-up image of EVERY analysed frame.

        If the cine sits in a run folder that was already analysed, that
        stride is offered first and reuses the analysis in place (only the
        images are drawn). Any other stride re-runs the AI into a new Trial_n,
        so a real run's results are never overwritten. Never writes to the
        master log -- see _on_pipeline_complete.

        Deliberately the SAME entry point a real capture uses
        (process_capture.process_capture), so this proves the live path rather
        than exercising a parallel one that could drift from it.
        """
        start_dir = find_lacie_drive() or os.path.expanduser("~")
        cine_path, _ = QFileDialog.getOpenFileName(
            self, "Pick a .cine to analyse",
            start_dir, "Phantom cine (*.cine);;All files (*)")
        if not cine_path:
            return

        lacie = find_lacie_drive()
        if not lacie:
            self._warn("No LaCie drive",
                       "The trial run folder is created on the LaCie drive, "
                       "which isn't mounted.")
            return

        # <run>/shadowgraph/raw/CINE/<file>.cine -> <run>
        picked = Path(cine_path)
        run = None
        if (len(picked.parents) > 3 and picked.parent.name == "CINE"
                and picked.parents[1].name == "raw"
                and picked.parents[2].name == "shadowgraph"):
            run = picked.parents[3]

        self._ai_code_on_path()
        from process_capture import previous_analysis, can_reuse
        prev = previous_analysis(run) if run else None
        if prev and Path(prev.get("source_cine", "")).name != picked.name:
            prev = None          # another cine's analysis in the same folder
        reusable = bool(prev) and can_reuse(run, int(prev.get("stride") or 0))

        choice = self._ask_full_analyse_stride(prev, reusable)
        if choice is None:
            return
        stride, reuse = choice
        self._log(f"── Full Analyse Cine: stride {stride}, "
                  f"{'reusing the existing analysis in ' + str(run) if reuse else 'new Trial folder'} ──")
        self._run_ai_chain(cine_path, run_dir=str(run) if reuse else None,
                           images="all", stride=stride,
                           reuse=reuse, save_to_log=False)

    def _run_ai_chain(self, cine_path, run_dir=None, images="extremes",
                      stride=None, reuse=False, save_to_log=True):
        """
        Run process_capture in a worker thread, streaming its log to the panel.

        run_dir=None creates the next Trial_n under today's date; a real
        capture passes its own already-created run folder instead.

        images="extremes" (real captures) draws only the frames the Extremes
        tab shows; Full Analyse Cine passes "all". Drawing every frame was ~80%
        of measurement time on the lab PC, and the .cine can regenerate any
        frame later.

        stride=None uses the main AI stride field. reuse=True lets
        process_capture skip to measurement if run_dir already holds a complete
        analysis at that stride. save_to_log=False (Full Analyse Cine) keeps
        the results out of the master log.
        """

        self._ai_code_on_path()
        if stride is None:
            stride = self._get_ai_stride()

        self._test_pipeline_btn.setEnabled(False)
        self._test_pipeline_btn.setText("Running…")
        self._pipeline_status.setText("Pipeline: running…")
        self._log(f"── AI chain started on {os.path.basename(cine_path)} ──")

        def _worker():
            try:
                from process_capture import process_capture, next_trial_dir
                target = run_dir
                if target is None:
                    target = next_trial_dir(
                        Path(find_lacie_drive()) / "Experiments")
                self._log_queue.put(f"run folder: {target}\n")

                _t_chain = time.time()
                summary = process_capture(
                    cine_path, target,
                    stride=stride,
                    score_thresh=0.30,
                    images=images,
                    reuse=reuse,
                    log=_InferenceProgressFilter(
                        lambda s: self._log_queue.put(s + "\n"),
                        every=self.INFERENCE_LOG_EVERY),
                    sharpness_rule=self.SHARPNESS_RULE,
                )
                # Stage 5, the classical liquid pass: the quoted atomised
                # fraction and the extreme-frame images the Extremes tab shows.
                # A failure here keeps the droplet results; it is reported, and
                # the run can be finished later by the Taguchi app's batch.
                try:
                    from process_capture import run_classical
                    ci_stride = (summary.get("provenance") or {}).get("ci_stride") or 1
                    summary["_classical"] = run_classical(
                        target, score_thresh=0.30, images=images,
                        sharpness_rule=self.SHARPNESS_RULE, ci_stride=ci_stride,
                        log=lambda s: self._log_queue.put(s + "\n"))
                except Exception as e:
                    summary["_classical_error"] = str(e)
                    self._log_queue.put(f"classical liquid stage FAILED: {e}\n")
                summary["_save_to_log"] = save_to_log
                self._log_queue.put(
                    f"── AI chain finished in {self._fmt_eta(time.time() - _t_chain)} ──\n")
                self._pipeline_done.emit(summary)
            except Exception as e:
                self._pipeline_err.emit(str(e))

        threading.Thread(target=_worker, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Calibration
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _phantom_frame_to_pixmap(frame) -> 'QPixmap':
        """Convert a pyphantom numpy frame (any bit depth) to a display QPixmap."""
        # Normalise to uint8 — Phantom outputs 12-bit packed in uint16
        if frame.dtype != np.uint8:
            f_min, f_max = int(frame.min()), int(frame.max())
            if f_max > f_min:
                frame = ((frame.astype(np.float32) - f_min) * 255.0 / (f_max - f_min)).astype(np.uint8)
            else:
                frame = np.zeros_like(frame, dtype=np.uint8)
        # Ensure C-contiguous so QImage can read the buffer directly
        frame = np.ascontiguousarray(frame)
        h, w = frame.shape[:2]
        fmt = QImage.Format.Format_RGB888 if len(frame.shape) == 3 \
              else QImage.Format.Format_Grayscale8
        img = QImage(frame.data, w, h, int(frame.strides[0]), fmt)
        return QPixmap.fromImage(img)

    def _cal_take_photo(self):
        """Freeze the current live frame and load it into the calibration widget."""
        if not self.phantom or not self.phantom.is_connected:
            self._warn("Camera Not Connected", "Connect the Phantom camera first.")
            return
        try:
            frame = self.phantom.cam.get_live_image()
            pixmap = self._phantom_frame_to_pixmap(frame)
            lacie = find_lacie_drive()
            save_dir = os.path.join(lacie, "Calibration") if lacie \
                       else os.path.join(os.path.dirname(__file__), "calibration_photos")
            os.makedirs(save_dir, exist_ok=True)
            fname = datetime.now().strftime("cal_%Y%m%d_%H%M%S.png")
            path = os.path.join(save_dir, fname)
            pixmap.save(path)
            self._cal_load_image_into_widget(path)
            self._set_status(f"Calibration photo saved: {fname}", CLR_GREEN)
        except Exception as e:
            self._warn("Capture Failed",
                       f"Could not capture live frame:\n{e}\n\nUse 'Load from File' instead.")

    def _cal_start_feed(self):
        if not self.phantom or not self.phantom.is_connected:
            self._warn("Camera Not Connected", "Connect the Phantom camera first.")
            return
        self._live_feed_timer.start()
        self._cal_feed_start_btn.setEnabled(False)
        self._cal_feed_stop_btn.setEnabled(True)
        self._cal_feed_label.setText("")
        self._live_view_label.setText("")
        self._live_feed_btn.setText("■ Stop Feed")

    def _cal_stop_feed(self):
        self._live_feed_timer.stop()
        self._live_feed_pending = False
        self._cal_feed_start_btn.setEnabled(True)
        self._cal_feed_stop_btn.setEnabled(False)
        self._cal_feed_label.setText("Live feed not active")
        self._live_view_label.setText("Live feed not active")
        self._live_feed_btn.setText("▶ Live Feed")
        # Clear live-feed lamella state — overlay pauses but checkbox stays as-is
        self._lamella_result = None
        self._lamella_pending_frame = None

    # ── Lamella Analysis ──────────────────────────────────────────────────────

    def _lamella_toggle(self, checked: bool):
        """Called when the Lamella Analysis toggle button is flipped."""
        self._lamella_on = checked
        if checked:
            self._lamella_toggle_btn.setText("Lamella Analysis  ON")
            self._lamella_thickness_lbl.setText("–")
            self._lamella_result = None
            self._lamella_pending_frame = None
            # Build segmenter lazily (runs quickly for stub; blocks for model load)
            if self._lamella_seg is None:
                self._lamella_load_segmenter()
        else:
            self._lamella_toggle_btn.setText("Lamella Analysis  OFF")
            self._lamella_thickness_lbl.setText("–")
            self._lamella_result = None
            self._lamella_pending_frame = None

    def _lamella_browse_model(self):
        """Open file picker to select a trained .pt model file."""
        start_dir = os.path.dirname(self._lamella_model_path) if self._lamella_model_path else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Lamella Model", start_dir, "PyTorch Model (*.pt *.pth)"
        )
        if not path:
            return
        self._lamella_model_path = path
        fname = os.path.basename(path)
        self._lamella_status_lbl.setText(f"{fname} — click toggle to load")
        self._lamella_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        self._lamella_seg = None
        self._save_camera_settings()

    def _lamella_load_segmenter(self):
        """Instantiate the selected segmenter in a background thread so the GUI stays responsive."""
        arch = self._lamella_arch_combo.currentText()
        model_path = getattr(self, "_lamella_model_path", "")

        if not model_path:
            self._lamella_status_lbl.setText("No model selected — use Browse…")
            self._lamella_status_lbl.setStyleSheet(f"color:#e05252; font-size:11px;")
            self._lamella_toggle_btn.setChecked(False)
            return

        self._lamella_status_lbl.setText("Loading model…")
        self._lamella_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")

        def _load():
            try:
                import torch
                from ai.lamella.infer import LamellaSegmenter
                if torch.cuda.is_available():
                    device = "cuda"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"
                seg = LamellaSegmenter.load(model_path, arch=arch, device=device)
                fname = os.path.basename(model_path)
                QTimer.singleShot(0, self, lambda: _on_done(seg, fname, device, None))
            except Exception as e:
                # e=e: Python deletes `e` when the except block ends, so a bare
                # lambda would raise NameError when the timer fires and the real
                # error would never be shown. Same fix at every site below.
                QTimer.singleShot(0, self, lambda e=e: _on_done(None, None, None, e))

        def _on_done(seg, fname, device, err):
            if err:
                self._lamella_seg = None
                self._lamella_status_lbl.setText(f"Load error: {err}")
                self._lamella_status_lbl.setStyleSheet(f"color:#e05252; font-size:11px;")
                self._lamella_toggle_btn.setChecked(False)
            else:
                self._lamella_seg = seg
                self._lamella_status_lbl.setText(f"{fname} ({device})")
                self._lamella_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:11px;")
                # If user toggled off while model was loading, honour their intent
                if not self._lamella_on:
                    self._lamella_toggle_btn.setChecked(False)

        threading.Thread(target=_load, daemon=True).start()

    def _lamella_arch_changed(self, arch: str):
        """Reset segmenter when arch selector changes so it reloads on next toggle."""
        self._lamella_seg = None
        self._lamella_arch = arch
        self._lamella_status_lbl.setText("No model loaded")
        self._save_camera_settings()

    def _lamella_crop_changed(self):
        """Update crop config dict when any spinbox changes."""
        self._lamella_crop_cfg = {
            "x": self._lamella_crop_x.value(),
            "y": self._lamella_crop_y.value(),
            "w": self._lamella_crop_w.value(),
            "h": self._lamella_crop_h.value(),
        }
        self._save_camera_settings()

    def _lamella_kick_inference(self):
        """Take the pending frame and start a background inference thread."""
        frame = self._lamella_pending_frame
        if frame is None or self._lamella_seg is None:
            return
        self._lamella_pending_frame = None
        self._lamella_busy = True

        from ai.lamella.crop import OutletCrop
        crop_box = OutletCrop.from_dict(self._lamella_crop_cfg)
        px_per_mm = self._get_px_per_mm()
        seg = self._lamella_seg

        def _infer():
            try:
                result = seg.analyse_frame(frame, crop_box, px_per_mm)
                QTimer.singleShot(0, self, lambda: self._lamella_result_ready(result))
            except Exception as e:
                print(f"[Lamella] Inference error: {e}")
                QTimer.singleShot(0, self, self._lamella_inference_done)

        threading.Thread(target=_infer, daemon=True).start()

    def _lamella_result_ready(self, result):
        """Main-thread callback — store result, update readout, kick next inference if pending."""
        self._lamella_result = result
        t = result.thickness
        if t.ok:
            if t.thickness_mm is not None:
                self._lamella_thickness_lbl.setText(f"{t.thickness_mm:.3f} mm")
            else:
                self._lamella_thickness_lbl.setText(f"{t.thickness_px:.1f} px  (no cal)")
        else:
            self._lamella_thickness_lbl.setText("No liquid detected")
        self._lamella_inference_done()

    def _lamella_inference_done(self):
        """Clear busy flag and kick next inference if a newer frame arrived while busy."""
        self._lamella_busy = False
        if self._lamella_on and self._lamella_pending_frame is not None:
            self._lamella_kick_inference()

    def _lamella_run_batch(self):
        """Open a TIFF folder, run batch analysis with progress bar."""
        tiff_dir = QFileDialog.getExistingDirectory(self, "Select TIFF Folder")
        if not tiff_dir:
            return
        if self._lamella_seg is None:
            self._lamella_load_segmenter()
        if self._lamella_seg is None:
            return

        from ai.lamella.crop import OutletCrop
        from ai.lamella.batch_tiff import run_batch

        crop_box  = OutletCrop.from_dict(self._lamella_crop_cfg)
        px_per_mm = self._get_px_per_mm()
        seg        = self._lamella_seg
        save_masks = self._lamella_save_masks_cb.isChecked()

        self._lamella_batch_btn.setEnabled(False)
        self._lamella_batch_progress.setValue(0)
        self._lamella_batch_progress.setVisible(True)

        self._log(f"── Lamella batch started ({tiff_dir}){' [masks ON]' if save_masks else ''} ──")

        _last_milestone = [-1]

        def _update_progress(pct):
            milestone = (pct // 10) * 10
            if milestone > _last_milestone[0]:
                _last_milestone[0] = milestone
                QTimer.singleShot(0, self, lambda p=milestone: self._log(f"Lamella batch: {p}%"))
            QTimer.singleShot(0, self, lambda p=pct: self._lamella_batch_progress.setValue(p))

        def _run():
            try:
                out_csv = run_batch(
                    tiff_dir=tiff_dir,
                    segmenter=seg,
                    crop_box=crop_box,
                    px_per_mm=px_per_mm,
                    progress_cb=_update_progress,
                    save_masks=save_masks,
                )
                QTimer.singleShot(0, self, lambda: self._lamella_batch_done(out_csv))
            except Exception as e:
                import traceback
                traceback.print_exc()
                QTimer.singleShot(0, self, lambda e=e: self._lamella_batch_error(str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _lamella_batch_done(self, out_csv: str):
        self._lamella_batch_btn.setEnabled(True)
        self._lamella_batch_progress.setVisible(False)
        self._log(f"── Lamella batch complete → {os.path.basename(out_csv)} ──")
        self._flash_log_border(CLR_GREEN)
        self._set_status(f"Lamella batch complete — {out_csv}", CLR_GREEN)
        self._lamella_try_analysis(out_csv)

    def _lamella_try_analysis(self, thickness_csv: str):
        """Auto-detect run_summary, ask for fps/run if needed, generate analysis Excel."""
        from ai.lamella.analysis import find_run_summary, read_run_summary, generate_analysis_excel

        tiff_dir = os.path.dirname(thickness_csv)
        summary_path = find_run_summary(tiff_dir)
        if summary_path is None:
            self._log("No run_summary.xlsx found — skipping analysis Excel.")
            return

        self._log(f"Found run_summary: {summary_path}")
        info = read_run_summary(summary_path)

        _dlg_style = (
            "QDialog { background: white; }"
            "QLabel  { color: black; }"
            "QLineEdit, QDoubleSpinBox, QComboBox, QListView { color: black; background: white; }"
            "QPushButton { color: black; }"
        )

        # FPS: use run_summary value, or ask
        fps = info["fps"]
        if fps is None:
            dlg = QInputDialog(self)
            dlg.setWindowTitle("Camera FPS")
            dlg.setLabelText("FPS not found in run_summary.\nEnter the camera FPS for this recording:")
            dlg.setInputMode(QInputDialog.InputMode.DoubleInput)
            dlg.setDoubleValue(40.0)
            dlg.setDoubleMinimum(1.0)
            dlg.setDoubleMaximum(1000000.0)
            dlg.setDoubleDecimals(1)
            dlg.setStyleSheet(_dlg_style)
            if not dlg.exec():
                self._log("Analysis Excel cancelled — no FPS provided.")
                return
            fps = dlg.doubleValue()

        # Camera run: ask if more than one
        windows = info["camera_windows"]  # list of (cam_start, cam_end, run_index)
        if not windows:
            self._log("No camera windows found in run_summary — skipping analysis Excel.")
            return

        if len(windows) == 1:
            cam_start, cam_end, run_index = windows[0]
        else:
            choices = [
                f"Run {idx}:  start={start:.2f}s  end={end:.2f}s"
                for start, end, idx in windows
            ]
            dlg = QInputDialog(self)
            dlg.setWindowTitle("Select Camera Run")
            dlg.setLabelText("Multiple camera captures found.\nWhich run do these TIFFs belong to?")
            dlg.setInputMode(QInputDialog.InputMode.TextInput)
            dlg.setComboBoxItems(choices)
            dlg.setComboBoxEditable(False)
            dlg.setStyleSheet(_dlg_style)
            if not dlg.exec():
                self._log("Analysis Excel cancelled — no run selected.")
                return
            sel = choices.index(dlg.textValue())
            cam_start, cam_end, run_index = windows[sel]

        self._log(f"Generating analysis Excel (run {run_index}, fps={fps}, cam_start={cam_start:.3f}s)…")

        def _run():
            try:
                out = generate_analysis_excel(
                    tiff_dir=tiff_dir,
                    thickness_csv=thickness_csv,
                    fps=fps,
                    cam_start=cam_start,
                    cam_end=cam_end,
                    run_index=run_index,
                    summary_path=summary_path,
                )
                QTimer.singleShot(0, self, lambda: self._lamella_analysis_done(out))
            except Exception as e:
                import traceback; traceback.print_exc()
                QTimer.singleShot(0, self, lambda e=e: self._log(f"Analysis Excel error: {e}"))

        threading.Thread(target=_run, daemon=True).start()

    def _lamella_analysis_done(self, out_path: str):
        self._log(f"── Analysis Excel saved → {os.path.basename(out_path)} ──")
        self._flash_log_border(CLR_GREEN)
        self._set_status(f"Analysis saved — {os.path.basename(out_path)}", CLR_GREEN)

    def _lamella_batch_error(self, err: str):
        self._lamella_batch_btn.setEnabled(True)
        self._lamella_batch_progress.setVisible(False)
        self._log(f"── Lamella batch error: {err} ──")
        self._flash_log_border("#ff3b30")
        self._set_status(f"Lamella batch error — {err}", "#e05252")
        self._warn("Lamella Batch Error", err)

    def _lamella_run_batch_auto(self, tiff_dir: str):
        """Auto-triggered lamella batch after camera save — no dialog, no masks."""
        if self._lamella_seg is None:
            self._lamella_load_segmenter()
        if self._lamella_seg is None:
            self._log("Lamella auto-batch skipped — no model loaded.")
            return

        from ai.lamella.crop import OutletCrop
        from ai.lamella.batch_tiff import run_batch

        crop_box  = OutletCrop.from_dict(self._lamella_crop_cfg)
        px_per_mm = self._get_px_per_mm()
        seg       = self._lamella_seg

        self._lamella_batch_btn.setEnabled(False)
        self._lamella_batch_progress.setValue(0)
        self._lamella_batch_progress.setVisible(True)
        self._log(f"── Lamella auto-batch started ({os.path.basename(tiff_dir)}) ──")

        _last_milestone = [-1]

        def _update_progress(pct):
            milestone = (pct // 10) * 10
            if milestone > _last_milestone[0]:
                _last_milestone[0] = milestone
                QTimer.singleShot(0, self, lambda p=milestone: self._log(f"Lamella batch: {p}%"))
            QTimer.singleShot(0, self, lambda p=pct: self._lamella_batch_progress.setValue(p))

        def _run():
            try:
                out_csv = run_batch(
                    tiff_dir=tiff_dir,
                    segmenter=seg,
                    crop_box=crop_box,
                    px_per_mm=px_per_mm,
                    progress_cb=_update_progress,
                    save_masks=False,
                )
                QTimer.singleShot(0, self, lambda: self._lamella_batch_done_auto(out_csv))
            except Exception as e:
                import traceback
                traceback.print_exc()
                QTimer.singleShot(0, self, lambda e=e: self._lamella_batch_error(str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _lamella_batch_done_auto(self, out_csv: str):
        """Auto-batch complete — analysis Excel deferred until after Save Experiment."""
        self._lamella_batch_btn.setEnabled(True)
        self._lamella_batch_progress.setVisible(False)
        self._log(f"── Lamella auto-batch complete → {os.path.basename(out_csv)} ──")
        self._log("  (Run 'Run on TIFF Folder…' after Save Experiment for analysis Excel)")

    # ─────────────────────────────────────────────────────────────────────────

    def _toggle_live_feed(self):
        """Live Camera View button — one control for the shared feed."""
        if self._live_feed_timer.isActive():
            self._cal_stop_feed()
        else:
            self._cal_start_feed()

    def _live_feed_tick(self):
        """Timer callback — grab one frame in a background thread."""
        if self._live_feed_pending:
            return
        if not self.phantom or not self.phantom.is_connected:
            self._cal_stop_feed()
            return
        self._live_feed_pending = True
        def _grab():
            try:
                frame = self.phantom.cam.get_live_image()
                # Latest-frame-only slot: replace any unprocessed frame, never queue
                if self._lamella_on:
                    self._lamella_pending_frame = frame
                    if not self._lamella_busy:
                        self._lamella_kick_inference()
                QTimer.singleShot(0, self, lambda: self._live_feed_update(frame))
            except Exception:
                QTimer.singleShot(0, self, lambda: self._cal_stop_feed())
            finally:
                self._live_feed_pending = False
        threading.Thread(target=_grab, daemon=True).start()

    def _live_feed_update(self, frame):
        """Main-thread callback — paint the latest frame into both feed labels.

        The Live Camera View is always on screen; the Calibration tab's copy is
        only repainted while that tab is showing.
        """
        if not self._live_feed_timer.isActive():
            return      # a grab that landed after Stop must not repaint
        display = frame
        if self._lamella_on and self._lamella_result is not None:
            from ai.lamella.overlay import draw_overlay
            display = draw_overlay(frame, self._lamella_result)
        pix = self._phantom_frame_to_pixmap(display)
        for lbl in (self._live_view_label, self._cal_feed_label):
            if lbl.isVisible():
                lbl.setPixmap(pix.scaled(
                    lbl.width(), lbl.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                ))

    def _cal_load_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Calibration Image", "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)"
        )
        if path:
            self._cal_load_image_into_widget(path)

    def _cal_load_image_into_widget(self, path):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._warn("Load Failed", f"Could not load image:\n{path}")
            return
        self._cal_image_widget.setCalibrationImage(pixmap)
        self._cal_point_status.setText("Point 1: not set  |  Point 2: not set")
        self._cal_calc_btn.setEnabled(False)
        self._cal_result_lbl.setText("Pixels/mm:  –")
        self._set_status("Calibration image loaded — click two points on a known distance")

    def _cal_on_points_changed(self, points):
        labels = []
        for i, (x, y) in enumerate(points):
            labels.append(f"Point {i + 1}: ({x}, {y})")
        for i in range(len(points), 2):
            labels.append(f"Point {i + 1}: not set")
        if len(points) == 2:
            (x1, y1), (x2, y2) = points
            axis = "vertical" if abs(y2 - y1) >= abs(x2 - x1) else "horizontal"
            px   = max(abs(x2 - x1), abs(y2 - y1))
            labels.append(f"[{axis}  {px} px]")
        self._cal_point_status.setText("  |  ".join(labels))
        self._cal_calc_btn.setEnabled(len(points) == 2)

    def _cal_reset_points(self):
        self._cal_image_widget.resetPoints()
        self._cal_point_status.setText("Point 1: not set  |  Point 2: not set")
        self._cal_calc_btn.setEnabled(False)

    def _cal_calculate(self):
        points = self._cal_image_widget.getPoints()
        if len(points) != 2:
            self._warn("Calibration Error", "Please click exactly two points on the image first.")
            return
        try:
            dist_mm = float(self._cal_dist_entry.text())
            if dist_mm <= 0:
                raise ValueError
        except ValueError:
            self._warn("Invalid Distance", "Enter a positive real-world distance in millimetres.")
            return
        (x1, y1), (x2, y2) = points
        pixel_dist = max(abs(x2 - x1), abs(y2 - y1))  # one axis is always 0 after snap
        if pixel_dist < 1:
            self._warn("Points Too Close",
                       "The two points are too close together.\nSelect points further apart.")
            return
        px_per_mm = pixel_dist / dist_mm
        self._cal_result_lbl.setText(f"Pixels/mm:  {px_per_mm:.2f}")
        self._apply_calibration_result(px_per_mm)
        self._set_status(f"Calibration set: {px_per_mm:.2f} px/mm", CLR_GREEN)

    def _apply_calibration_result(self, val: float):
        """Update the header px/mm label and persist the value to settings."""
        self._hdr_pxmm_lbl.setText(f"{val:.1f} px/mm")
        self._hdr_pxmm_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 12px;")
        self._save_camera_settings()

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Cone
    # ─────────────────────────────────────────────────────────────────────────

    def _cone_save_dir(self):
        """Return the directory to save cone images into, creating it if needed."""
        if self._run_folder:
            save_dir = os.path.join(self._run_folder, "cone")
        else:
            # Standalone / no active experiment — use original fallback locations
            lacie = find_lacie_drive()
            save_dir = os.path.join(lacie, "Experiments", "Logs", "Testing") if lacie \
                       else os.path.join(os.path.dirname(__file__), "cone_captures")
        os.makedirs(save_dir, exist_ok=True)
        return save_dir

    def _cone_apply_focus(self):
        """Push current focus settings to the open camera (silently ignored if unsupported)."""
        if self._cone_cap is None or not self._cone_cap.isOpened():
            return
        if self._cone_autofocus_chk.isChecked():
            self._cone_cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        else:
            self._cone_cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            self._cone_cap.set(cv2.CAP_PROP_FOCUS, self._cone_focus_spin.value())
        self._save_camera_settings()

    def _cone_bgr_to_pixmap(self, bgr_arr) -> QPixmap:
        """Convert a numpy BGR array to a QPixmap."""
        rgb = cv2.cvtColor(bgr_arr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(bytes(rgb.data), w, h, w * ch, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(img)

    def _cone_history_push(self, annotated_path: str, angle: float):
        """Add a result to the rolling history strip and refresh the thumbnails."""
        self._cone_history.append((annotated_path, angle))
        THUMB_H = 150
        history_list = list(self._cone_history)
        for i, (img_lbl, ang_lbl) in enumerate(self._cone_hist_cells):
            if i < len(history_list):
                path, ang = history_list[i]
                pix = QPixmap(path)
                if not pix.isNull():
                    w = img_lbl.width() if img_lbl.width() > 0 else 200
                    pix = pix.scaled(w, THUMB_H,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
                    img_lbl.setPixmap(pix)
                    img_lbl.setText("")
                ang_lbl.setText(f"{ang:.1f}°")
                ang_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:10px; font-weight:600;")
            else:
                img_lbl.setPixmap(QPixmap())
                img_lbl.setText("–")
                ang_lbl.setText("–")
                ang_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:10px;")

    def _cone_start_camera(self):
        if not CV2_AVAILABLE:
            return
        idx = self._cone_idx_spin.value()
        self._cone_cam_status_lbl.setText(f"Opening camera {idx}…")
        self._cone_cam_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        # cv2.VideoCapture can block for several seconds on Windows — run in a thread.
        # On Windows, DirectShow (CAP_DSHOW) is more reliable than the default MSMF backend.
        def _open():
            if platform.system() == "Windows":
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(idx)
            QTimer.singleShot(0, self, lambda: self._cone_on_camera_opened(cap, idx))
        threading.Thread(target=_open, daemon=True).start()

    def _cone_on_camera_opened(self, cap, idx):
        if not cap.isOpened():
            self._cone_cam_status_lbl.setText(f"Failed to open camera {idx}")
            self._cone_cam_status_lbl.setStyleSheet(f"color:{CLR_RED}; font-size:12px;")
            return
        self._cone_cap = cap
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._cone_cam_status_lbl.setText(f"Camera running ({w}×{h})")
        self._cone_cam_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;")
        self._cone_start_cam_btn.setEnabled(False)
        self._cone_stop_cam_btn.setEnabled(True)
        self._cone_capture_btn.setEnabled(True)
        self._cone_feed_timer.start(100)
        self._cone_apply_focus()
        self._save_camera_settings()  # persist index for auto-connect on next launch

    def _cone_stop_camera(self):
        self._cone_feed_timer.stop()
        self._cone_auto_timer.stop()
        self._cone_auto_status_lbl.setText("Auto-capture: inactive")
        self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        if self._cone_cap is not None:
            self._cone_cap.release()
            self._cone_cap = None
        self._cone_feed_lbl.setMinimumWidth(120)
        self._cone_feed_lbl.setMaximumWidth(16777215)
        self._cone_feed_lbl.setText("No camera")
        self._cone_feed_lbl.setPixmap(QPixmap())
        self._cone_cam_status_lbl.setText("Camera stopped")
        self._cone_cam_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._cone_start_cam_btn.setEnabled(CV2_AVAILABLE)
        self._cone_stop_cam_btn.setEnabled(False)
        self._cone_capture_btn.setEnabled(False)

    def _cone_update_feed(self):
        if self._cone_cap is None or not self._cone_cap.isOpened():
            self._cone_feed_timer.stop()
            return
        ret, frame = self._cone_cap.read()
        if not ret:
            self._cone_feed_timer.stop()
            self._cone_cam_status_lbl.setText("Camera lost")
            self._cone_cam_status_lbl.setStyleSheet(f"color:{CLR_RED}; font-size:12px;")
            return
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        top_crop = self._cone_top_crop_spin.value()
        if top_crop > 0:
            top_px = int(frame.shape[0] * top_crop)
            if top_px > 0:
                overlay = frame.copy()
                cv2.rectangle(overlay, (0, 0), (frame.shape[1] - 1, top_px - 1), (0, 0, 200), -1)
                cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
                cv2.line(frame, (0, top_px), (frame.shape[1] - 1, top_px), (0, 0, 255), 1)
        pm = self._cone_bgr_to_pixmap(frame).scaled(
            9999, self._cone_feed_lbl.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cone_feed_lbl.setFixedWidth(pm.width())
        self._cone_feed_lbl.setPixmap(pm)

    def _cone_capture(self):
        if self._cone_cap is None or not self._cone_cap.isOpened():
            self._cone_cam_status_lbl.setText("No camera — cannot capture")
            self._cone_cam_status_lbl.setStyleSheet(f"color:{CLR_RED}; font-size:12px;")
            return
        ret, frame = self._cone_cap.read()
        if not ret:
            self._cone_cam_status_lbl.setText("Capture failed")
            return
        _cap_time = datetime.now().strftime("%H:%M:%S")
        self._cone_capture_btn.setEnabled(False)   # block until analysis done
        self._cone_auto_status_lbl.setText(f"Captured at {_cap_time} — analysing…")
        self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_ACCENT}; font-size:12px;")

        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir  = self._cone_save_dir()
        raw_path  = os.path.join(save_dir, f"cone_raw_{ts}.png")
        cv2.imwrite(raw_path, frame)
        self._last_cone_path = raw_path   # fallback if analysis not yet done

        if not CONE4_AVAILABLE:
            self._cone_angle_lbl.setText("Cone_4.py not found — raw image saved only")
            self._cone_angle_lbl.setVisible(True)
            self._cone_result_img_lbl.setVisible(False)
            self._cone_saved_lbl.setText(f"Saved: {raw_path}")
            self._cone_saved_lbl.setVisible(True)
            self._cone_capture_btn.setEnabled(True)
            return

        self._cone_angle_lbl.setText("Analysing…")
        self._cone_angle_lbl.setVisible(True)
        top_crop = self._cone_top_crop_spin.value()
        self._log(f"── Cone analysis started ({os.path.basename(raw_path)}) ──")

        def _analyse():

            class _TeeStream:
                def __init__(self, gui_stream, buf):
                    self._g, self._b = gui_stream, buf
                def write(self, text):
                    self._g.write(text); self._b.write(text)
                def flush(self):
                    self._g.flush()
                def isatty(self): return False
                def fileno(self): raise io.UnsupportedOperation("fileno")

            _buf    = io.StringIO()
            _stream = _GuiLogStream(self._log_queue)
            _tee    = _TeeStream(_stream, _buf)
            self._tl_stdout.set(_tee)
            self._tl_stderr.set(_tee)
            try:
                angle, annotated_bgr, _debug = detect_cone_angle(
                    Path(raw_path), top_crop_ratio=top_crop)
            except Exception as e:
                def _on_err(e=e):
                    self._cone_angle_lbl.setText(f"Analysis error: {e}")
                    self._cone_angle_lbl.setVisible(True)
                    self._cone_capture_btn.setEnabled(True)
                    self._flash_log_border("#ff3b30")
                QTimer.singleShot(0, self, _on_err)
                return
            finally:
                self._tl_stdout.clear()
                self._tl_stderr.clear()

            had_warning = "low fit quality" in _buf.getvalue().lower()

            annotated_path = os.path.join(save_dir, f"cone_{ts}.png")
            cv2.imwrite(annotated_path, annotated_bgr)

            def _update_ui():
                if not had_warning:
                    self._flash_log_border(CLR_GREEN)
                self._last_cone_path = annotated_path
                self._cone_history_push(annotated_path, angle)
                pm = self._cone_bgr_to_pixmap(annotated_bgr).scaled(
                    self._cone_result_img_lbl.width(), self._cone_result_img_lbl.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._cone_result_img_lbl.setPixmap(pm)
                self._cone_result_img_lbl.setVisible(True)
                self._cone_angle_lbl.setText(f"Cone angle: {angle:.1f}°")
                self._cone_angle_lbl.setVisible(True)
                self._cone_saved_lbl.setText(f"Saved: {annotated_path}")
                self._cone_saved_lbl.setVisible(True)
                self._cone_auto_status_lbl.setText(f"Last capture: {_cap_time} — {angle:.1f}°  (will be used in Excel)")
                self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;")
                self._cone_capture_btn.setEnabled(True)

            QTimer.singleShot(0, self, _update_ui)

        threading.Thread(target=_analyse, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — AFG
    # ─────────────────────────────────────────────────────────────────────────

    def _afg_connect(self):
        if not self.afg: return
        try:
            self.afg.connect()
            self._afg_status_lbl.setText("AFG: connected")
            self._afg_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;")
            self._hdr_afg_dot.setStyleSheet(f"color:{CLR_ORANGE}; font-size:10px; background:transparent;")
            self._hdr_afg_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        except Exception as e:
            self._afg_status_lbl.setText(f"AFG error: {e}")
            self._set_status(f"AFG: {e}", CLR_RED)

    def _afg_configure(self):
        if not self.afg: return
        try:
            ch = 1 if self._afg_channel.currentText() == "CH1" else 2
            dur = float(self._afg_duration.text())
            self.afg.configure_pulse(dur, channel=ch)
            pulse_us = dur * 1e6
            if pulse_us >= 1000:
                pulse_str = f"{dur*1000:.1f} ms"
            else:
                pulse_str = f"{pulse_us:.0f} µs"
            self._afg_status_lbl.setText(f"AFG: configured ({pulse_str} pulse, CH{ch})")
            self._hdr_afg_dot.setStyleSheet(f"color:{CLR_GREEN}; font-size:10px; background:transparent;")
            self._hdr_afg_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        except Exception as e:
            self._set_status(f"AFG config error: {e}", CLR_RED)

    def _afg_test(self):
        if not self.afg or not self.afg.is_connected:
            self._set_status("AFG not connected", CLR_ORANGE); return
        try:
            ch = 1 if self._afg_channel.currentText() == "CH1" else 2
            self.afg.trigger(ch)
            self._set_status("AFG test fired")
        except Exception as e:
            self._set_status(f"AFG trigger error: {e}", CLR_RED)

    def _afg_disconnect(self):
        if self.afg: self.afg.disconnect()
        self._afg_status_lbl.setText("AFG: disconnected")
        self._afg_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._hdr_afg_dot.setStyleSheet(f"color:{CLR_RED}; font-size:10px; background:transparent;")
        self._hdr_afg_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Experiment
    # ─────────────────────────────────────────────────────────────────────────

    def _standard_capture_diffs(self):
        """[(label, on screen, standard)] for every capture field that differs from
        STANDARD_CAPTURE. The AI-analysis box is not checked: the AI runs afterwards in the
        Experiment Analysis app's batch (CCD plan Phase 7), so capturing with it off is normal."""
        fields = {"fps": self._cam_fps, "exposure_us": self._cam_exp,
                  "width": self._cam_width, "height": self._cam_height,
                  "pre_trigger_s": self._cam_pre_s, "post_trigger_s": self._cam_post_s,
                  "ai_stride": self._ai_stride}
        diffs = []
        for key, label, std in self.STANDARD_CAPTURE:
            cur = fields[key].text().strip()
            try:
                same = abs(float(cur) - float(std)) < 1e-9
            except ValueError:
                same = False
            if not same:
                diffs.append((label, cur or "(blank)", std))
        return diffs

    def _check_standard_capture(self) -> bool:
        """Before a run: offer to restore the campaign standard if anything differs.
        Returns False only if the user cancels the run."""
        diffs = self._standard_capture_diffs()
        if not diffs:
            return True
        lines = "\n".join(f"  • {label}: {cur}  (standard {std})" for label, cur, std in diffs)
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Capture settings differ from the standard")
        dlg.setText("These settings differ from the Taguchi campaign standard:\n\n"
                    f"{lines}\n\n"
                    "Runs captured differently are not directly comparable with the "
                    "2026-10-05 campaign.")
        dlg.setIcon(QMessageBox.Icon.Warning)
        use_btn  = dlg.addButton("Use standard settings", QMessageBox.ButtonRole.AcceptRole)
        keep_btn = dlg.addButton("Keep mine", QMessageBox.ButtonRole.DestructiveRole)
        dlg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dlg.exec()
        clicked = dlg.clickedButton()
        if clicked == use_btn:
            fields = {"fps": self._cam_fps, "exposure_us": self._cam_exp,
                      "width": self._cam_width, "height": self._cam_height,
                      "pre_trigger_s": self._cam_pre_s, "post_trigger_s": self._cam_post_s,
                      "ai_stride": self._ai_stride}
            for key, _label, std in self.STANDARD_CAPTURE:
                fields[key].setText(std)
            if self.phantom:
                self._cam_configure()          # push to the camera; also saves settings
            else:
                self._save_camera_settings()
            self._log("Capture settings reset to the campaign standard.")
            return True
        return clicked == keep_btn

    # ── Window check: drops on the window / lens (2026-10-13) ────────────────
    # A drop is measured as un-atomised liquid whenever it differs from the run's background median
    # (it lands, grows, drips), so it is caught here, before the run: the live view against a reference
    # taken when the window was clean (gui/window_check.py).

    def _window_ref_text(self) -> str:
        if _window_check is None:
            return "Window check unavailable: gui/window_check.py did not import."
        try:
            frame, meta = _window_check.load_reference()
        except Exception as e:
            return f"Clean reference unreadable ({e}): save a new one."
        if frame is None:
            return "No clean reference yet: wipe the window, then Save clean reference."
        h, w = frame.shape[:2]
        return f"Clean reference: saved {meta.get('saved', '?')}, {w}×{h}."

    def _window_grab(self):
        """(one live frame, '') or (None, why not)."""
        if not self.phantom or not self.phantom.is_connected:
            return None, "the camera is not connected"
        try:
            return self.phantom.cam.get_live_image(), ""
        except Exception as e:
            return None, f"no live frame ({e})"

    def _window_save_reference(self):
        frame, why = self._window_grab()
        if frame is None:
            self._warn("Window check", f"No reference saved: {why}.")
            return
        try:
            path = _window_check.save_reference(frame, note=f"exposure {self._cam_exp.text()} us")
        except OSError as e:
            self._warn("Window check", f"Could not save the reference:\n{e}")
            return
        self._window_ref_lbl.setText(self._window_ref_text())
        self._log(f"Window check: clean reference saved ({path}).")
        self._set_status("Clean window reference saved", CLR_GREEN)

    def _window_compare(self):
        """(WindowCheck, the live frame or None)."""
        try:
            ref, _meta = _window_check.load_reference()
        except Exception as e:
            return _window_check.WindowCheck(True, skipped=f"the reference is unreadable ({e})"), None
        if ref is None:
            return _window_check.WindowCheck(True, skipped="no clean reference saved"), None
        frame, why = self._window_grab()
        if frame is None:
            return _window_check.WindowCheck(True, skipped=why), None
        return _window_check.compare(frame, ref), frame

    def _window_dialog(self, chk, frame, at_start: bool) -> bool:
        """The live view with the new spots boxed. At Start: True = start anyway."""
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Window check")
        dlg.setText(f"{chk.text()[:1].upper()}{chk.text()[1:]} since the clean reference.\n\n"
                    "A drop on the window is measured as un-atomised liquid and lowers the atomised "
                    "fraction. Wipe or dry the window"
                    + (", then Start again; or start anyway (run_summary records it)." if at_start else "."))
        try:
            dlg.setIconPixmap(self._phantom_frame_to_pixmap(_window_check.overlay(frame, chk, 640)))
        except Exception:
            pass                                            # the text says it all without the picture
        start_btn = None
        if at_start:
            dlg.addButton("Cancel: wipe first", QMessageBox.ButtonRole.RejectRole)
            start_btn = dlg.addButton("Start anyway", QMessageBox.ButtonRole.AcceptRole)
        else:
            dlg.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        dlg.setStyleSheet(f"""
            QMessageBox {{ background-color: {CLR_PANEL}; color: {CLR_TEXT}; }}
            QLabel {{ color: {CLR_TEXT}; font-size: 13px; }}
            QPushButton {{
                background-color: {CLR_INPUT}; color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER}; border-radius: 8px;
                padding: 6px 20px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {CLR_ACCENT}; color: white; }}
        """)
        dlg.exec()
        return start_btn is not None and dlg.clickedButton() is start_btn

    def _window_check_now(self):
        if _window_check is None:
            return
        chk, frame = self._window_compare()
        self._log(f"Window check: {chk.text()}")
        if chk.skipped:
            self._warn("Window check", f"Not checked: {chk.skipped}.")
        elif chk.ok:
            self._set_status("Window check: clean", CLR_GREEN)
        else:
            self._window_dialog(chk, frame, at_start=False)

    def _window_check_at_start(self) -> bool:
        """Before Start Experiment moves anything. False = the user chose to wipe first. The result is
        kept for this run's run_summary ('Window check (before run)')."""
        if _window_check is None or not self._window_chk.isChecked():
            self._window_check_result = "off"
            return True
        chk, frame = self._window_compare()
        self._window_check_result = chk.text()
        self._log(f"Window check: {chk.text()}")
        if chk.skipped or chk.ok:
            return True
        if self._window_dialog(chk, frame, at_start=True):
            self._window_check_result = chk.text() + " (started anyway)"
            return True
        self._set_status("Start cancelled: wipe the window, then Start again", CLR_ORANGE)
        return False

    def _start_experiment(self):
        if not self._require_arduino(): return
        if not self._check_standard_capture(): return

        # Warn if previous experiment data hasn't been saved yet
        if not self._experiment_saved and self.pressure_data['experiment_data']['timestamps']:
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Unsaved Experiment Data")
            dlg.setText(
                "You have unsaved data from the previous experiment.\n\n"
                "Starting a new experiment will discard it.\n"
                "Save to Excel first, or click Discard to continue anyway."
            )
            dlg.setIcon(QMessageBox.Icon.Warning)
            save_btn     = dlg.addButton("Save First",          QMessageBox.ButtonRole.RejectRole)
            discard_btn  = dlg.addButton("Discard & Continue",  QMessageBox.ButtonRole.DestructiveRole)  # noqa: F841
            dlg.setStyleSheet(f"""
                QMessageBox {{ background-color: {CLR_PANEL}; color: {CLR_TEXT}; }}
                QLabel {{ color: {CLR_TEXT}; font-size: 13px; }}
                QPushButton {{
                    background-color: {CLR_INPUT}; color: {CLR_TEXT};
                    border: 1px solid {CLR_BORDER}; border-radius: 8px;
                    padding: 6px 20px; font-size: 13px;
                }}
                QPushButton:hover {{ background-color: {CLR_ACCENT}; color: white; }}
            """)
            dlg.exec()
            if dlg.clickedButton() == save_btn:
                return  # let user save first before continuing

        try:
            flow     = float(self._flow_entry.text())
            speed    = int(self._speed_entry.text())
            distance = float(self._distance_entry.text())
        except ValueError:
            self._set_status("Fill in flow, speed, and distance first", CLR_ORANGE)
            self._warn("Missing Parameters",
                       "Please fill in all three fields before starting:\n"
                       "  • Target Flow (sccm)\n"
                       "  • Motor Speed (steps/s)\n"
                       "  • Motor Travel (mm)")
            return
        static = speed <= 0          # speed 0: gas + bubbler + logging, no traverse move
        if not static and self.cumulative_distance + distance > self.MAX_MOTOR_MM:
            remaining = self.MAX_MOTOR_MM - self.cumulative_distance
            self._set_status("Travel limit would be exceeded!", CLR_RED)
            self._warn("Travel Limit",
                       f"This experiment would exceed the motor's travel limit of {self.MAX_MOTOR_MM} mm.\n\n"
                       f"Only {remaining:.1f} mm of travel remains.\n"
                       "Home the motor to reset.")
            return
        # Pressure must be live: a connected Alicat that has gone quiet means the
        # setpoint may never arrive and nothing is watching the pressure.
        if self.alicat_connected and not self._alicat_live():
            self._warn("Alicat not responding",
                       "The Alicat is connected but not sending readings.\n\n"
                       "Reconnect the MFC on the Hardware tab before starting.")
            return
        if self._cutoff_bar is not None and not self._alicat_live():
            self._warn("Pressure cut-off has no readings",
                       f"The pressure cut-off is set ({self._cutoff_bar:g} barA) but there are "
                       "no live Alicat readings, so it could not fire.\n\n"
                       "Connect the MFC, or switch the cut-off off, before starting.")
            return
        # A value in the RPM box means this run spins the bubbler.
        start_rpm = self._start_rpm()
        if start_rpm is not None and not (self.rpm_connected and self.rpm_arduino):
            self._warn("Bubbler motor not connected",
                       f"The RPM box says {start_rpm:g} RPM, but the RPM Arduino is not "
                       "connected, so the bubbler would not spin.\n\n"
                       "Connect it on the Hardware tab, or clear the RPM box for a run "
                       "without rotation.")
            return
        if not self._window_check_at_start():
            return
        if not self._orifice_len_entry.text().strip():
            # not a blocker: older inserts may not have been measured yet
            self._log("Orifice length is empty (Nozzle card): this run records it as NOT RECORDED.")
            self._set_status("Orifice length not set: recorded as NOT RECORDED", CLR_ORANGE)
        if static:
            auto_plan = None
            if self._auto_trig_chk.isChecked():
                self._log("Auto-trigger skipped: speed 0 has no end of test to time it from.")
        else:
            auto_plan = self._auto_trigger_check(distance, speed)
        if auto_plan == "cancel":
            return

        self.pressure_data['experiment_active'] = True
        self.pressure_data['experiment_start_time'] = time.time()
        self.pressure_data['experiment_data'] = {'timestamps':[], 'pressures':[], 'flows':[]}
        self.pressure_data['camera_windows'] = []
        self._last_cone_path = None   # reset so we only capture this experiment's image
        self._last_ai_results = None  # ditto: never carry a previous run's D32 into this row
        self._run_stop_reason = None
        self._move_stopped_early = False
        self._front_limit_steps = None
        self._last_move_pct = 0
        # The run is recorded with THESE conditions, however often it is re-saved
        # and whatever is typed for the next run in the meantime.
        self._run_conditions = self._snapshot_run_conditions()

        # ── Create run folder eagerly ──────────────────────────────────────────
        # Kept so the spreadsheets can stamp the moment the experiment STARTED
        # rather than the moment Save was clicked. Those differ by the whole run
        # duration plus however long the notes took, which made the master_log
        # timestamp disagree with the run folder it refers to.
        _now = datetime.now()
        self._run_started_at = _now
        _run_id = self._run_id(_now, f"{flow:.0f}sccm")
        _lacie = find_lacie_drive()
        _exp_base = os.path.join(_lacie, "Experiments") if _lacie else os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "experiment_logs", "Experiments")
        self._run_folder = os.path.join(
            _exp_base, _now.strftime("%Y"), _now.strftime("%m"), _now.strftime("%d"), _run_id)
        # Only the folders every run uses. TIFFs/ is created at the point of use
        # instead — with Save TIFFs off it was being made empty on every single
        # run and never written to. Brightest_Frame is gone entirely: the GUI
        # shows the lowest-D32 frame from summary.json instead (2026-09-27).
        for _sub in [os.path.join("shadowgraph", "raw", "CINE"),
                     os.path.join("shadowgraph", "analysis"),
                     "cone"]:
            os.makedirs(os.path.join(self._run_folder, _sub), exist_ok=True)
        # Update the camera save path label to reflect the active run folder
        if hasattr(self, '_cam_save_lbl'):
            self._cam_save_lbl.setText(self._cam_path_hint())

        # Schedule a single cone capture 5 s after experiment start
        if self._cone_cap is not None and self._cone_cap.isOpened():
            self._cone_auto_timer.start(5000)
            self._cone_auto_status_lbl.setText("Cone capture: in 5 s")
            self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;")
        # Reset live buffer and EMA so the graph X-axis starts from 0 at experiment start
        self.pressure_data['live_buffer'] = {'timestamps': [], 'pressures': [], 'flows': []}
        self.pressure_data['live_buffer_start_time'] = time.time()
        self._pressure_ema = None   # seed EMAs fresh from the first reading of the run
        self._flow_ema     = None
        self._last_tiff_dir = None  # reset so previous experiment's CSV doesn't bleed over

        self._start_btn.setEnabled(False)
        self._exp_progress.setRange(0, 0 if static else 100)    # busy bar: no end to count to
        self._exp_progress.setValue(0)
        self._exp_progress.setVisible(True)
        self._set_status("Static run (speed 0) — runs until STOP EVERYTHING" if static
                         else "Experiment running…", CLR_ACCENT)
        self._run_start_time = time.time()
        self._run_elapsed_timer.start()

        if self.alicat_connected and self.alicat:
            self._send_flow(flow)
        if start_rpm is not None and self._start_spin(start_rpm):
            self._log(f"Bubbler motor started at {start_rpm:g} RPM.")
        self._pre_move_cumulative   = self.cumulative_distance
        if static:
            # No move, so no MOVEMENT_COMPLETE and no watchdog: the run ends with
            # STOP EVERYTHING (or the pressure cut-off).
            self._pending_move_distance = 0.0
            self._log("Speed 0: no traverse move. Gas, bubbler and logging run until "
                      "STOP EVERYTHING.")
        else:
            # Send motor command 500 ms later without blocking the UI
            QTimer.singleShot(500, lambda: self.arduino.send_motor_command(speed, distance))
            self._pending_move_distance = distance
            # cumulative_distance is finalised in _on_movement_complete so the travel bar fills live

            # Start watchdog: if serial reader dies, the gas would stay on forever without this
            _steps_per_mm = 6800
            _move_time_ms = int((distance * _steps_per_mm / speed + 30) * 1000)
            self._experiment_watchdog.start(_move_time_ms)

        # Camera: armed/triggered from the Camera tab, or by itself near the end of
        # the test when "Auto-trigger at end of test" is ticked
        if isinstance(auto_plan, dict):
            self._auto_trigger_schedule(auto_plan)

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Shadowgraph preview
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _lowest_d32_image(run_dir):
        """The marked-up lowest-D32 frame for a finished run, or None.

        Reads the frame name out of measure_run's summary.json rather than
        guessing a filename, so this agrees with what the pipeline actually
        chose and with what _on_pipeline_complete displays.
        """
        import glob as _g
        analysis = os.path.join(run_dir, "shadowgraph", "analysis")
        if not os.path.isdir(analysis):
            return None
        # The classical pass's rendering first (un-atomised liquid filled), from
        # its own summary; then measure_run's, for runs without a classical pass.
        for ldir in sorted(_g.glob(os.path.join(analysis, "liquid_*")),
                           key=os.path.getmtime, reverse=True):
            try:
                with open(os.path.join(ldir, "classical_summary.json"), encoding="utf-8") as fh:
                    stem = (((json.load(fh).get("d32_extreme_frames") or {})
                             .get("lowest") or {}).get("frame"))
            except (OSError, ValueError):
                continue
            if stem:
                f = os.path.join(ldir, "extreme_images", f"{stem}.png")
                if os.path.exists(f):
                    return f
        # droplets_* is the current name; measurement_* is what every run
        # measured before 2026-10-05 is called. Both are searched so older runs
        # still open in the GUI.
        _cands = (_g.glob(os.path.join(analysis, "droplets_*"))
                  + _g.glob(os.path.join(analysis, "measurement_*")))
        for mdir in sorted(_cands, key=os.path.getmtime, reverse=True):
            summary = os.path.join(mdir, "summary.json")
            if not os.path.exists(summary):
                continue
            try:
                with open(summary, encoding="utf-8") as fh:
                    ext = (json.load(fh).get("d32_extreme_frames") or {})
                stem = (ext.get("lowest") or {}).get("frame")
            except (OSError, ValueError):
                continue
            if stem:
                f = os.path.join(mdir, f"{stem}.png")
                if os.path.exists(f):
                    return f
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Excel save
    # ─────────────────────────────────────────────────────────────────────────

    # ── Saving runs OFF the GUI thread ───────────────────────────────────────
    # master_log.xlsx is ~83 MB with 140 embedded images (2026-10-01); loading
    # and re-saving it alone measured ~9 s. Run on the GUI thread -- as the
    # end-of-experiment auto-save did -- that froze every button, including
    # the bubbler motor's Stop, for the whole save. Now: everything read from
    # the GUI is snapshotted here on the GUI thread (fast), and the file work
    # runs on a single background worker. One worker means saves run one at a
    # time in the order requested, exactly as the old synchronous calls did.

    def _save_to_excel(self):
        """Save button and auto-saves. Returns immediately; see _save_to_excel_async."""
        self._save_to_excel_async()

    def _save_to_excel_async(self, on_done=None):
        """Snapshot the run now, write the spreadsheets in the background.

        `on_done(ok, err)` is called back on the GUI thread when the write
        finishes.
        """
        try:
            job = self._collect_save_job()
        except Exception as e:
            self._set_status(f"Save error: {e}", CLR_RED)
            if on_done:
                on_done(False, str(e))
            return

        ex = getattr(self, "_excel_executor", None)
        if ex is None:
            from concurrent.futures import ThreadPoolExecutor
            ex = self._excel_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="excel-save")
        self._set_status("Saving to Excel…")

        def _run():
            try:
                result = self._write_excel(job)
            except Exception as e:
                QTimer.singleShot(0, self, lambda e=e: self._on_excel_save_failed(e, on_done))
            else:
                QTimer.singleShot(0, self, lambda r=result: self._on_excel_saved(r, on_done))
        ex.submit(_run)

    def _on_excel_saved(self, result, on_done):
        ind_path, master_path, run_dir = result
        self._experiment_saved = True
        self._set_status("Saved: run_summary.xlsx  +  master_log.xlsx updated", CLR_GREEN)
        self._save_path_lbl.setText(f"{ind_path}\nMaster: {master_path}")

        # Update header last-save label to this run folder (clickable, bold, underlined)
        self._last_saved_run_folder = run_dir
        _folder_name = os.path.basename(run_dir)
        self._hdr_last_save_lbl.setText(_folder_name)
        self._hdr_last_save_lbl.setStyleSheet(
            f"color: {CLR_TEXT}; font-size: 12px; font-weight: 700; text-decoration: underline;"
            " cursor: pointer;"
        )
        self._hdr_last_save_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_next_save_preview()
        if on_done:
            on_done(True, None)

    def _on_excel_save_failed(self, e, on_done):
        self._set_status(f"Save error: {e}", CLR_RED)
        if on_done:
            on_done(False, str(e))

    def _snapshot_run_conditions(self) -> dict:
        """The run conditions as they are in the widgets NOW. Taken at Start, so
        re-saving a run (e.g. to add Notes) records what was actually run, not
        whatever has since been typed for the next one."""
        try:
            static = float(self._speed_entry.text() or 0) <= 0
        except ValueError:
            static = False
        return {
            'orifice':      self._orifice_combo.currentText(),
            'orifice_length_str': self._orifice_len_entry.text().strip(),
            'speed_str':    self._speed_entry.text(),
            'distance_str': "0" if static else self._distance_entry.text(),
            'bubbler_str':  self._bubbler_height_entry.text().strip(),
            'rpm_str':      self._rpm_entry.text().strip(),
            'flow_entry':   self._flow_entry.text(),
            'fps_text':     self._cam_fps.text(),
            # Snapshot the GLR and the densities it came from. _write_excel runs
            # on the save worker and must not read widgets, and recording the
            # densities means a GLR in an old sheet can always be traced back to
            # the numbers that produced it.
            'glr':          self._compute_glr(),
            'rho_liquid':   self._rho_liquid_entry.text(),
            'rho_gas':      self._rho_gas_entry.text(),
            'fluid_tag':    self._fluid_tag_entry.text(),
            'gas_tag':      self._gas_tag_entry.text(),
            'static':       static,
            # what the window check said at this run's Start ('clean', '2 new dark spots ...', 'off')
            'window_check': getattr(self, '_window_check_result', 'NOT RECORDED'),
        }

    def _collect_save_job(self) -> dict:
        """Everything the save reads from the GUI or from run state, read NOW on
        the GUI thread. _write_excel touches nothing else of self's mutable
        state, so a new experiment starting mid-save cannot leak into the row
        being written."""
        lacie        = find_lacie_drive()
        # The experiment's start, so the spreadsheet row, the run_summary and
        # the run folder all carry the same time. Falls back to now() only
        # when there is no run folder to agree with (a save with no
        # experiment behind it, which builds its own folder below).
        now          = getattr(self, "_run_started_at", None) or datetime.now()

        # Use the frozen snapshot taken at experiment end — not the live buffer.
        # Copied, so the background write never shares lists with the GUI.
        snap = {k: (list(v) if isinstance(v, list) else v)
                for k, v in self._last_experiment_snapshot.items()}
        flows = snap.get('flows', [])
        # The conditions of the run being saved (taken at its Start); live values
        # only for a save with no run behind it.
        cond = self._run_conditions or self._snapshot_run_conditions()
        f_range_file = f"{max(flows):.0f}sccm" if flows else None

        # ── Resolve run folder (created at Start Experiment, or now as fallback) ──
        if self._run_folder:
            run_dir = self._run_folder
        else:
            _exp_base = os.path.join(lacie, "Experiments") if lacie else os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "experiment_logs", "Experiments")
            _run_id = self._run_id(now, f_range_file or 'unknownsccm')
            run_dir = os.path.join(_exp_base, now.strftime("%Y"), now.strftime("%m"),
                                   now.strftime("%d"), _run_id)
            for _sub in [os.path.join("shadowgraph", "raw"),
                         os.path.join("shadowgraph", "analysis"), "cone"]:
                os.makedirs(os.path.join(run_dir, _sub), exist_ok=True)
            self._run_folder = run_dir

        return {
            **cond,
            'lacie':        lacie,
            'now':          now,
            'notes':        self._notes_text.toPlainText(),     # live: typed after the run
            'run_status':   (f"STOPPED: {self._run_stop_reason}" if self._run_stop_reason
                             else "complete") if self._run_conditions else "",
            'ai':           dict(self._last_ai_results or {}),
            'snap':         snap,
            'run_dir':      run_dir,
            'last_tiff_dir': self._last_tiff_dir,
            'px_per_mm':    self._get_px_per_mm(),
            'last_cone_path': self._last_cone_path,
        }

    @staticmethod
    def _gas_fields(snap: dict, set_text) -> dict:
        """run_summary Metadata: what the run actually got in its camera window (operating.py, the
        analysis app's own definitions). 'Flow Range' is the max over the whole run, which on the
        0.5 mm block on 2026-10-12 read 0-11,737 sccm for a run that got ~2,200 while the camera ran."""
        keys = ('Gas delivered in camera window (sccm)', 'Gas delivered p10-p90 (sccm)',
                'Upstream pressure in camera window (barA)', 'Gas regime', 'Gas settled')
        if _operating is None:
            return dict.fromkeys(keys, 'NOT RECORDED')
        windows = snap.get('camera_windows') or []
        if not windows or not snap.get('timestamps') or not snap.get('flows'):
            return dict.fromkeys(keys, 'NO CAMERA WINDOW' if snap.get('timestamps') else 'NO GAS LOG')
        try:
            set_sccm = float(set_text) if set_text not in (None, '') else None
        except (TypeError, ValueError):
            set_sccm = None
        tr = _operating.Trace(np.asarray(snap['timestamps'], float), np.asarray(snap['pressures'], float),
                              np.asarray(snap['flows'], float), tuple(windows[0]))
        op = _operating.classify(_operating.window_stats(tr), set_sccm, SUPPLY_CEILING_BAR)
        if op.delivered_sccm is None:
            return dict.fromkeys(keys, 'TOO FEW SAMPLES IN THE WINDOW')
        return {keys[0]: round(op.delivered_sccm),
                keys[1]: f"{op.delivered_p10:.0f}-{op.delivered_p90:.0f}",
                keys[2]: round(op.p0_bar, 3) if op.p0_bar is not None else 'NOT RECORDED',
                keys[3]: op.regime,
                keys[4]: 'unknown' if op.settled is None else ('yes' if op.settled else 'NO')}

    def _write_excel(self, job: dict):
        """The file work of a save: run_summary.xlsx and the master_log row.
        Runs on the save worker -- reads only `job` and class constants, never
        a widget. Returns (ind_path, master_path, run_dir). Raises on failure.
        """
        from openpyxl import load_workbook, Workbook
        from openpyxl.drawing.image import Image as XLImage
        from openpyxl.styles import Alignment, PatternFill, Font, Color
        from openpyxl.utils import get_column_letter, column_index_from_string
        from matplotlib.figure import Figure

        lacie        = job['lacie']
        now          = job['now']
        ts_str       = now.strftime("%Y-%m-%d %H:%M:%S")

        orifice      = job['orifice']
        _olen        = job.get('orifice_length_str') or ''
        orifice_len  = as_number(_olen) if _olen else 'NOT RECORDED'
        notes        = job['notes']
        speed_str    = job['speed_str']
        distance_str = job['distance_str']
        bubbler_str  = job['bubbler_str']
        rpm_str      = job['rpm_str']

        # Plain numbers, not "85.6 +/-2.1%": these are Taguchi responses and
        # need to sort and plot in Excel. The confidence intervals live in
        # the run's summary.json. Blank when the AI chain has not run --
        # never a stale value from a previous run (cleared at run start).
        _ai = job['ai']
        d32_val  = _ai.get('d32_in_focus_um', '')
        # Classical (the quoted figure) since 2026-10-08; earlier rows hold
        # measure_run's model-only fraction.
        atom_val = (_ai.get('_classical') or {}).get('atomised_pct_pooled',
                                                      _ai.get('atomised_pct', ''))
        # In-focus mean diameter, from the same summary.json as D32.
        mean_val = _ai.get('droplet_d_mean_um', '')
        if mean_val is None:
            mean_val = ''
        # In-band droplets produced per second (mass balance), a number; blank before the AI chain.
        rate_val = droplet_rate_band(_ai, job.get('speed_str'))

        snap = job['snap']
        camera_windows = snap.get('camera_windows', [])
        pressures = snap['pressures']
        flows     = snap.get('flows', [])
        if pressures:
            p_min, p_max = min(pressures), max(pressures)
            p_range_str  = f"{p_min:.2f}–{p_max:.2f} barA"
        else:
            p_range_str  = "N/A"
        if flows:
            f_min, f_max = min(flows), max(flows)
            f_range_str  = f"{f_min:.0f}–{f_max:.0f} sccm"
        else:
            raw = job['flow_entry']
            f_range_str  = f"{raw} sccm" if raw else "N/A"

        run_dir  = job['run_dir']
        ind_path = os.path.join(run_dir, "run_summary.xlsx")

        # ── Build data frame with camera window annotations ──────────────────
        # cam_start_N / cam_end_N values appear only on the row whose timestamp
        # is closest to the camera window boundary; all other rows are blank.
        press_df = None
        if snap['timestamps']:
            _cols = {'timestamps': snap['timestamps'],
                     'pressures':  snap['pressures']}
            if flows:
                _cols['flows_sccm'] = flows
            press_df = pd.DataFrame(_cols)
            if camera_windows:
                _ts_arr = snap['timestamps']
                for _i, (_cw_s, _cw_e) in enumerate(camera_windows, start=1):
                    _col_s, _col_e = f'cam_start_{_i}', f'cam_end_{_i}'
                    press_df[_col_s] = float('nan')
                    press_df[_col_e] = float('nan')
                    _idx_s = min(range(len(_ts_arr)), key=lambda j: abs(_ts_arr[j] - _cw_s))
                    _idx_e = min(range(len(_ts_arr)), key=lambda j: abs(_ts_arr[j] - _cw_e))
                    press_df.at[_idx_s, _col_s] = round(_cw_s, 3)
                    press_df.at[_idx_e, _col_e] = round(_cw_e, 3)

        # ── Render charts (shared between run_summary and master_log) ────────
        # DPI = DISPLAY_H / fig_h → PNG always renders at exactly DISPLAY_H px tall.
        DISPLAY_H          = 165
        MIN_W_PX           = 347
        PX_PER_SEC         = MIN_W_PX / 10.0
        FIG_H_IN           = 2.0
        DPI                = DISPLAY_H / FIG_H_IN

        def _render_chart(series, ylabel, colour, range_str):
            """Render one trace to PNG bytes; returns (bytes, display width px)."""
            if not series:
                return None, MIN_W_PX
            t0          = snap['timestamps'][0]
            rel_ts      = [t - t0 for t in snap['timestamps']]
            duration_s  = rel_ts[-1] if rel_ts else 0.0
            target_w_px = max(MIN_W_PX, int(duration_s * PX_PER_SEC))
            # Figure, not plt.subplots: this runs on the save worker, and
            # pyplot's global figure registry is not thread-safe. Same Agg
            # renderer, so the PNG is identical.
            fig = Figure(figsize=(target_w_px / DPI, FIG_H_IN))
            ax = fig.subplots()
            fig.patch.set_facecolor('white')
            ax.set_facecolor('#f5f5f7')
            ax.plot(rel_ts, series, color=colour, linewidth=2.5, solid_capstyle='round')
            ax.fill_between(rel_ts, series, alpha=0.12, color=colour)
            for _cw_s, _cw_e in camera_windows:
                ax.axvspan(_cw_s - t0, _cw_e - t0, alpha=0.2, color='red', zorder=0)
            ax.set_xlabel('Time (s)', fontsize=8, color='#3a3a3c')
            ax.set_ylabel(ylabel, fontsize=8, color='#3a3a3c')
            ax.set_title(f'{orifice}  {range_str}',
                         fontsize=8, color='#1c1c1e', pad=4, loc='left')
            ax.tick_params(colors='#6e6e73', labelsize=7)
            ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#d1d1d6'); ax.spines['bottom'].set_color('#d1d1d6')
            ax.grid(True, alpha=0.4, color='#d1d1d6', linewidth=0.6)
            ax.set_ylim(bottom=0)
            fig.tight_layout(pad=0.6)
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=DPI, bbox_inches='tight', facecolor='white')
            import struct as _struct
            buf.seek(16)
            actual_w = _struct.unpack('>I', buf.read(4))[0]
            actual_h = _struct.unpack('>I', buf.read(4))[0]
            width_px = max(MIN_W_PX, int(actual_w * DISPLAY_H / actual_h))
            # Return bytes, not the buffer: PIL closes the BytesIO inside XLImage,
            # and the same image is reused for the master log.
            return buf.getvalue(), width_px

        pressure_bytes, pressure_img_width = _render_chart(
            pressures, 'Pressure (barA)', '#0a84ff', p_range_str)
        flow_bytes, flow_img_width = _render_chart(
            flows, 'Mass Flow (sccm)', '#30d158', f_range_str)

        fps_val = float(job['fps_text']) if job['fps_text'] else 1000.0
        gas_fields = self._gas_fields(snap, job.get('flow_entry'))
        # 'NOT SET' rather than blank or 0: a missing density is a thing someone
        # forgot to enter, and that must not be mistaken for a measured ratio.
        _glr = job.get('glr')
        glr_val = round(_glr, 4) if isinstance(_glr, (int, float)) else 'NOT SET'
        meta = {
            'Field': ['Timestamp', 'Orifice', 'Orifice length (mm)', 'Bubbler Height (mm)',
                      'Bubbler RPM', 'Flow Range (sccm)', 'GLR',
                      'Fluid', 'Liquid density (kg/m3)',
                      'Gas', 'Gas density (kg/m3)',
                      'Pressure Range (barA)', 'Speed (steps/s)', 'Motor Travel (mm)',
                      'FPS', 'Notes', 'Run status', 'Window check (before run)'] + list(gas_fields),
            'Value': [ts_str, orifice, orifice_len, as_number(bubbler_str) if bubbler_str else 'NOT RECORDED',
                      as_number(rpm_str) if rpm_str else 'NOT RECORDED', f_range_str, glr_val,
                      job.get('fluid_tag') or 'NOT RECORDED',
                      job.get('rho_liquid') or 'NOT SET',
                      job.get('gas_tag') or 'NOT RECORDED',
                      job.get('rho_gas') or 'NOT SET',
                      p_range_str,
                      as_number(speed_str), as_number(distance_str), fps_val, notes,
                      job.get('run_status') or 'NOT RECORDED',
                      job.get('window_check') or 'NOT RECORDED'] + list(gas_fields.values()),
        }
        # Written to a temporary file and swapped in, so a crash or a drive
        # dropout mid-write leaves the previous run_summary intact.
        _ind_tmp = _tmp_path(ind_path)
        with pd.ExcelWriter(_ind_tmp, engine='openpyxl') as writer:
            pd.DataFrame(meta).to_excel(writer, sheet_name='Metadata', index=False)
            if press_df is not None:
                press_df.to_excel(writer, sheet_name='Pressure', index=False)
                _anchor_row = len(press_df) + 3
                _ws = writer.sheets['Pressure']
                if pressure_bytes:
                    _rs_img = XLImage(io.BytesIO(pressure_bytes))
                    _rs_img.width  = pressure_img_width
                    _rs_img.height = DISPLAY_H
                    _ws.add_image(_rs_img, f'A{_anchor_row}')
                if flow_bytes:
                    # Sit the flow chart immediately right of the pressure chart:
                    # default column width is ~64 px, so step that many columns over.
                    _col = (pressure_img_width // 64) + 2 if pressure_bytes else 1
                    _fl_img = XLImage(io.BytesIO(flow_bytes))
                    _fl_img.width  = flow_img_width
                    _fl_img.height = DISPLAY_H
                    _ws.add_image(_fl_img, f'{get_column_letter(_col)}{_anchor_row}')
        _commit_tmp(_ind_tmp, ind_path)

        # ── Compute lamella thickness value for master_log ────────────────
        import csv as _csv_mod, re as _re
        _lamella_cell_val = 'N/A'
        _lamella_orange   = False
        if job['last_tiff_dir']:
            _lam_csv = os.path.join(job['last_tiff_dir'], 'lamella_thickness.csv')
            if os.path.exists(_lam_csv):
                _thicknesses = []
                with open(_lam_csv, newline='') as _lf:
                    for _lr in _csv_mod.DictReader(_lf):
                        if str(_lr.get('ok', '')).lower() == 'true':
                            try:
                                _thicknesses.append(float(_lr['thickness_px']))
                            except (ValueError, KeyError):
                                pass
                if _thicknesses:
                    _avg_px    = sum(_thicknesses) / len(_thicknesses)
                    _pxmm      = job['px_per_mm']
                    if _pxmm > 0:
                        _lamella_cell_val = f"{_avg_px:.1f} px / {_avg_px / _pxmm:.3f} mm"
                    else:
                        _lamella_cell_val = f"{_avg_px:.1f} px"
                else:
                    _lamella_orange   = True
                    _lamella_cell_val = 'Input Self'
            else:
                _lamella_orange   = True
                _lamella_cell_val = 'Input Self'

        # ── Master log: insert at row 2, shift image anchors first ───────
        _master_base = os.path.join(lacie, "Experiments", "Logs") if lacie else os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "experiment_logs")
        os.makedirs(_master_base, exist_ok=True)
        master_path = os.path.join(_master_base, 'master_log.xlsx')
        # Row for THIS run, if it is already logged. The Timestamp column
        # holds the experiment's start time, which is unique per run, so it
        # identifies the row without needing a hidden key. Set below once
        # the migrations have guaranteed column A is Timestamp.
        _existing_row = None
        if os.path.exists(master_path):
            wb = load_workbook(master_path)
            ws = wb.active

            # ── Migrate old header format (no Avg Lamella Thickness column) ──
            _hdr = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
            if len(_hdr) >= 7 and _hdr[6] == 'Notes':
                ws.insert_cols(7)
                ws.cell(row=1, column=7).value = 'Avg Lamella Thickness'
                ws.column_dimensions['G'].width = 12
                # Shift image anchors that were in columns H+ (index >= 7, 1-based)
                for _img in ws._images:
                    _anc = _img.anchor
                    if isinstance(_anc, str):
                        _m = _re.match(r'^([A-Z]+)(\d+)$', _anc)
                        if _m and column_index_from_string(_m.group(1)) >= 8:
                            _new_col = get_column_letter(column_index_from_string(_m.group(1)) + 1)
                            _img.anchor = f'{_new_col}{_m.group(2)}'
                    elif hasattr(_anc, '_from'):
                        if _anc._from.col >= 7:  # 0-indexed: 7 = Excel col H
                            _anc._from.col += 1
                        if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 7:
                            _anc.to.col += 1

            # ── Migrate to the flow-first format ────────────────────────────
            # Old layout: D = 'Pressure Range' (BAR, from the retired pressure
            # controller).  New layout inserts 'Flow Range (sccm)' at D and pushes
            # pressure to E, so every column from D rightwards shifts by one, and
            # a 'Mass Flow Graph' column is appended at the end.
            _hdr = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
            if len(_hdr) >= 4 and _hdr[3] == 'Pressure Range':
                ws.insert_cols(4)
                ws.cell(row=1, column=4).value = 'Flow Range (sccm)'
                ws.cell(row=1, column=5).value = 'Pressure Range (barA)'
                ws.column_dimensions['D'].width = 18
                ws.column_dimensions['E'].width = 18
                for _img in ws._images:
                    _anc = _img.anchor
                    if isinstance(_anc, str):
                        _m = _re.match(r'^([A-Z]+)(\d+)$', _anc)
                        if _m and column_index_from_string(_m.group(1)) >= 4:
                            _new_col = get_column_letter(column_index_from_string(_m.group(1)) + 1)
                            _img.anchor = f'{_new_col}{_m.group(2)}'
                    elif hasattr(_anc, '_from'):
                        if _anc._from.col >= 3:   # 0-indexed: 3 == Excel col D
                            _anc._from.col += 1
                        if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 3:
                            _anc.to.col += 1
            # ── Migrate away from the Nozzle column ─────────────────────────
            # Runs after the migrations above have brought an older file up to
            # the 13-column with-Nozzle layout.  Nozzle was column B, so every
            # column from C rightwards shifts one to the left.
            if ws.cell(row=1, column=2).value == 'Nozzle':
                if ws.cell(row=1, column=13).value != 'Mass Flow Graph':
                    ws.cell(row=1, column=13).value = 'Mass Flow Graph'
                ws.delete_cols(2)
                for _img in ws._images:
                    _anc = _img.anchor
                    if isinstance(_anc, str):
                        _m = _re.match(r'^([A-Z]+)(\d+)$', _anc)
                        if _m and column_index_from_string(_m.group(1)) >= 3:
                            _new_col = get_column_letter(column_index_from_string(_m.group(1)) - 1)
                            _img.anchor = f'{_new_col}{_m.group(2)}'
                    elif hasattr(_anc, '_from'):
                        if _anc._from.col >= 2:   # 0-indexed: 2 == Excel col C
                            _anc._from.col -= 1
                        if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 2:
                            _anc.to.col -= 1

            # ── Migrate to the bubbler format ───────────────────────────────
            # Runs after the migrations above have brought an older file up to
            # the 12-column layout, where C is 'Flow Range (sccm)'. Bubbler
            # height and RPM go in beside Orifice as C and D, so every column
            # from C rightwards shifts two to the right.
            if ws.cell(row=1, column=3).value == 'Flow Range (sccm)':
                ws.insert_cols(3, 2)
                ws.cell(row=1, column=3).value = 'Bubbler Height (mm)'
                ws.cell(row=1, column=4).value = 'Bubbler RPM'
                for _img in ws._images:
                    _anc = _img.anchor
                    if isinstance(_anc, str):
                        _m = _re.match(r'^([A-Z]+)(\d+)$', _anc)
                        if _m and column_index_from_string(_m.group(1)) >= 3:
                            _new_col = get_column_letter(column_index_from_string(_m.group(1)) + 2)
                            _img.anchor = f'{_new_col}{_m.group(2)}'
                    elif hasattr(_anc, '_from'):
                        if _anc._from.col >= 2:   # 0-indexed: 2 == Excel col C
                            _anc._from.col += 2
                        if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 2:
                            _anc.to.col += 2

            # ── Migrate to the measurement format ───────────────────────────
            # D32 and atomised fraction go in beside the other measured
            # responses, left of Avg Lamella Thickness, so everything the run
            # PRODUCED sits together and to the right of everything that was
            # SET. Column I was Avg Lamella in the 14-column layout.
            if ws.cell(row=1, column=9).value == 'Avg Lamella Thickness':
                ws.insert_cols(9, 2)
                ws.cell(row=1, column=9).value = 'D32 (um)'
                ws.cell(row=1, column=10).value = 'Atomised (%)'
                for _img in ws._images:
                    _anc = _img.anchor
                    if isinstance(_anc, str):
                        _m = _re.match(r'^([A-Z]+)(\d+)$', _anc)
                        if _m and column_index_from_string(_m.group(1)) >= 9:
                            _new_col = get_column_letter(column_index_from_string(_m.group(1)) + 2)
                            _img.anchor = f'{_new_col}{_m.group(2)}'
                    elif hasattr(_anc, '_from'):
                        if _anc._from.col >= 8:   # 0-indexed: 8 == Excel col I
                            _anc._from.col += 2
                        if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 8:
                            _anc.to.col += 2

            # ── Migrate to the GLR format ───────────────────────────────────
            # LAST, deliberately: every migration above keys on a column index,
            # and inserting a column earlier in the row would move the ones they
            # look for. GLR goes at F, immediately right of the gas flow it is
            # computed from, so everything from F rightwards shifts one. Once in,
            # F reads 'GLR' and this cannot fire twice.
            if ws.cell(row=1, column=6).value == 'Pressure Range (barA)':
                ws.insert_cols(6)
                ws.cell(row=1, column=6).value = 'GLR'
                ws.column_dimensions['F'].width = 10
                for _img in ws._images:
                    _anc = _img.anchor
                    if isinstance(_anc, str):
                        _m = _re.match(r'^([A-Z]+)(\d+)$', _anc)
                        if _m and column_index_from_string(_m.group(1)) >= 6:
                            _new_col = get_column_letter(column_index_from_string(_m.group(1)) + 1)
                            _img.anchor = f'{_new_col}{_m.group(2)}'
                    elif hasattr(_anc, '_from'):
                        if _anc._from.col >= 5:   # 0-indexed: 5 == Excel col F
                            _anc._from.col += 1
                        if hasattr(_anc, 'to') and _anc.to and _anc.to.col >= 5:
                            _anc.to.col += 1

            # ── Migrate to the mean-diameter format ─────────────────────────
            # After GLR, for the same reason: it keys on the post-GLR layout
            # (J = D32, K = Atomised) and puts Mean Diameter at K between them.
            migrate_master_mean_diameter(ws)
            # ── Migrate to the orifice-length format (after mean diameter) ──
            migrate_master_orifice_length(ws)
            # ── ... then the droplets/s column (after orifice length) ────────
            migrate_master_droplet_rate(ws)

            _mf_col = self.MASTER_COL_COUNT
            if ws.cell(row=1, column=_mf_col).value != 'Mass Flow Graph':
                ws.cell(row=1, column=_mf_col).value = 'Mass Flow Graph'
                ws.column_dimensions[get_column_letter(_mf_col)].width = 56

            # Is this run already logged? Re-saving must UPDATE that row, not
            # append a second one -- the experiment auto-saves when it ends,
            # and you then write the Notes and save again. Appending would
            # give two rows per run, and a stray double-click on Save would
            # do the same.
            for _r in range(2, ws.max_row + 1):
                if str(ws.cell(row=_r, column=1).value).strip() == ts_str:
                    _existing_row = _r
                    break

            # Everything below only makes room for a NEW row. Updating an
            # existing one must not shift anything.
            if _existing_row is None:
                # Shift row_dimensions down one row before inserting
                old_dims = {r: ws.row_dimensions[r].height
                            for r in list(ws.row_dimensions.keys()) if r >= 2}
                for r in sorted(old_dims.keys(), reverse=True):
                    ws.row_dimensions[r + 1].height = old_dims[r]

                # Shift every existing image anchor down one row before inserting
                for img in ws._images:
                    anchor = img.anchor
                    if isinstance(anchor, str):
                        m = _re.match(r'^([A-Z]+)(\d+)$', anchor)
                        if m and int(m.group(2)) >= 2:
                            img.anchor = f'{m.group(1)}{int(m.group(2)) + 1}'
                    elif hasattr(anchor, '_from'):
                        if anchor._from.row >= 1:   # 0-indexed: row 1 == Excel row 2
                            anchor._from.row += 1
                        if hasattr(anchor, 'to') and anchor.to and anchor.to.row >= 1:
                            anchor.to.row += 1
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = 'Experiments'
            ws.append(list(self.MASTER_HEADERS))
            for col, width in zip(self.MASTER_COL_LETTERS, self.MASTER_COL_WIDTHS):
                ws.column_dimensions[col].width = width

        # Stamp the canonical header names and style on EVERY save, for both
        # new and migrated workbooks. openpyxl's insert_cols() gives a new
        # column no style at all, and setting .value on it does not inherit
        # one from its neighbours -- which is why 'Mass Flow Graph' was the
        # single unbold, unfilled header in the existing log. Doing it here
        # also carries renames (Distance -> Motor Travel) into old files.
        _hdr_fill = PatternFill(fill_type='solid',
                                start_color=Color(theme=self.MASTER_HDR_FILL_THEME,
                                                  tint=self.MASTER_HDR_FILL_TINT))
        _hdr_font = Font(name='Calibri', size=11, bold=True,
                         color=Color(theme=self.MASTER_HDR_FONT_THEME))
        for _c, _name in enumerate(self.MASTER_HEADERS, start=1):
            _hc = ws.cell(row=1, column=_c)
            _hc.value = _name
            _hc.fill = _hdr_fill
            _hc.font = _hdr_font

        # Reapply the canonical widths on every save.  openpyxl's
        # insert_cols()/delete_cols() above move cell values but NOT
        # column_dimensions, so a format migration leaves widths attached to
        # the wrong column — Shadowgraph inherits the old Pressure Graph width
        # and renders enormous.  Reapplying here also repairs workbooks that
        # were migrated before this was fixed.
        # M/N/O/P are re-set from their actual images further down.
        for col, width in zip(self.MASTER_COL_LETTERS, self.MASTER_COL_WIDTHS):
            ws.column_dimensions[col].width = width

        if _existing_row is None:
            ws.insert_rows(2)
            row_num = 2
        else:
            row_num = _existing_row
            # Drop the images already anchored to this row. openpyxl keeps
            # them in a flat list with no concept of replacement, so without
            # this the new cone/shadowgraph/graph images stack on top of the
            # old ones in the same cells.
            _r0 = row_num - 1          # anchors are 0-indexed
            ws._images = [im for im in ws._images
                          if not (hasattr(im.anchor, '_from')
                                  and im.anchor._from.row == _r0)]

        # Every column below is looked up BY HEADER NAME, never by letter or
        # index. When GLR was inserted at F, the image code here still used the
        # pre-GLR letters M/N/O/P, so the cone's "NO DATA AVAILABLE" landed on
        # Notes (erasing it), the shadowgraph went in the Cone column and both
        # graphs shifted one left. Looking columns up from MASTER_HEADERS means
        # a future column can move things only by changing that tuple.
        _col = {h: i for i, h in enumerate(self.MASTER_HEADERS, start=1)}
        c_notes, c_lamella = _col['Notes'], _col['Avg Lamella Thickness']
        c_cone, c_shadow = _col['Cone Image'], _col['Shadowgraph']
        c_press, c_flow = _col['Pressure Graph'], _col['Mass Flow Graph']

        center_mid = Alignment(horizontal='center', vertical='center', wrap_text=True)
        top_left   = Alignment(horizontal='left',   vertical='top',    wrap_text=True)
        row_vals = {
            'Timestamp':             ts_str,
            'Orifice':               orifice,
            'Orifice Length (mm)':   orifice_len,
            'Bubbler Height (mm)':   as_number(bubbler_str) if bubbler_str else 'NOT RECORDED',
            'Bubbler RPM':           as_number(rpm_str) if rpm_str else 'NOT RECORDED',
            'Flow Range (sccm)':     f_range_str,
            'GLR':                   glr_val,
            'Pressure Range (barA)': p_range_str,
            'Speed (steps/s)':       as_number(speed_str),
            'Motor Travel (mm)':     as_number(distance_str),
            'D32 (um)':              d32_val,
            'Mean Diameter (um)':    mean_val,
            'Atomised (%)':          atom_val,
            MASTER_RATE_HEADER:      rate_val,
            'Avg Lamella Thickness': _lamella_cell_val,
            # A stopped run is flagged where it is seen: at the front of its
            # Notes. (run_summary.xlsx has its own "Run status" field; its
            # Notes stay untouched because the Taguchi app reads them.)
            'Notes':                 (f"⚠ {job['run_status']}\n{notes}".rstrip()
                                      if str(job.get('run_status', '')).startswith("STOPPED")
                                      else notes),
        }
        for name, col in _col.items():
            cell = ws.cell(row=row_num, column=col)
            cell.value = row_vals.get(name, '')     # image columns start blank
            cell.alignment = top_left if col == c_notes else center_mid
        # Orange highlight for "Input Self" lamella cell
        if _lamella_orange:
            _lc = ws.cell(row=row_num, column=c_lamella)
            _lc.fill = PatternFill(start_color='FFA500', end_color='FFA500', fill_type='solid')
            _lc.font = Font(color='000000', bold=True)
        ws.row_dimensions[row_num].height = 125

        _cone_img_path = job['last_cone_path'] or ""
        if _cone_img_path and os.path.exists(_cone_img_path):
            _cone_raw = cv2.imread(_cone_img_path)
            if _cone_raw is not None:
                _ch, _cw = _cone_raw.shape[:2]
                # Scale to match the row height (DISPLAY_H px) preserving aspect ratio
                _cone_disp_h = DISPLAY_H
                _cone_disp_w = max(1, int(_cw * _cone_disp_h / _ch))
                cimg = XLImage(_cone_img_path)
                cimg.width = _cone_disp_w; cimg.height = _cone_disp_h
                _L = get_column_letter(c_cone)
                ws.column_dimensions[_L].width = max(10, _cone_disp_w / 7.0)
                ws.add_image(cimg, f'{_L}{row_num}')
            else:
                ws.cell(row=row_num, column=c_cone).value = 'NO DATA AVAILABLE'
        else:
            ws.cell(row=row_num, column=c_cone).value = 'NO DATA AVAILABLE'

        # THIS run's lowest-D32 frame only. It used to take whatever the
        # preview panel showed, and the preview falls back to the newest
        # result from ANY run -- so a run saved without AI analysis got an
        # old run's image beside its blank D32 cells.
        shadow_src = self._lowest_d32_image(run_dir)
        if shadow_src:
            simg = XLImage(shadow_src)
            simg.width = self.SHADOWGRAPH_W_PX; simg.height = DISPLAY_H
            # Size the column to the image rather than leaving whatever
            # width the migration left behind (Excel width ~= px / 7)
            _L = get_column_letter(c_shadow)
            ws.column_dimensions[_L].width = self.SHADOWGRAPH_W_PX / 7.0
            ws.add_image(simg, f'{_L}{row_num}')
        else:
            ws.cell(row=row_num, column=c_shadow).value = 'NO DATA AVAILABLE'

        # Pressure graph in its column, mass flow graph immediately right of it
        for _col_idx, _img_bytes, _img_w in (
                (c_press, pressure_bytes, pressure_img_width),
                (c_flow,  flow_bytes,     flow_img_width)):
            _col_letter = get_column_letter(_col_idx)
            if _img_bytes:
                _gimg = XLImage(io.BytesIO(_img_bytes))
                _gimg.width = _img_w; _gimg.height = DISPLAY_H
                # Widen the column to fit the image (56 chars ≈ 347 px baseline)
                ws.column_dimensions[_col_letter].width = max(56, _img_w * 56 / 347)
                ws.add_image(_gimg, f'{_col_letter}{row_num}')
            else:
                ws.cell(row=row_num, column=_col_idx).value = 'NO DATA AVAILABLE'

        # master_log holds every run (~83 MB): never write it in place. Save to
        # a temporary file beside it and swap it in, so a crash or a LaCie
        # dropout mid-write leaves the previous master_log intact.
        _replace_atomically(master_path, wb.save)
        return ind_path, master_path, run_dir

    # ─────────────────────────────────────────────────────────────────────────
    # Settings persistence
    # ─────────────────────────────────────────────────────────────────────────

    def _settings_path(self):
        return os.path.join(os.path.dirname(__file__), "camera_settings.json")

    def _load_camera_settings(self):
        # Setting widgets fires their save signals (Run AI analysis, the cone
        # spinboxes, …); saving half-way through a load wrote defaults over the
        # values not loaded yet (last flow, Alicat port, cut-off, lamella model).
        self._loading_settings = True
        try:
            self._load_camera_settings_inner()
        finally:
            self._loading_settings = False

    def _load_camera_settings_inner(self):
        try:
            with open(self._settings_path()) as f:
                s = json.load(f)
            self._cam_ip.setText(s.get("ip", "100.100.100.1"))
            _std = {k: v for k, _l, v in self.STANDARD_CAPTURE}
            self._cam_fps.setText(str(s.get("fps", _std["fps"])))
            self._cam_exp.setText(str(s.get("exposure_us", _std["exposure_us"])))
            self._cam_width.setText(str(s.get("width", _std["width"])))
            self._cam_height.setText(str(s.get("height", _std["height"])))
            self._cam_pre_s.setText(str(s.get("pre_trigger_s", _std["pre_trigger_s"])))
            self._cam_post_s.setText(str(s.get("post_trigger_s", _std["post_trigger_s"])))
            # Restore both save-format boxes with signals blocked, then repair the
            # pair in case the file somehow holds "neither".
            _saved_cine  = bool(s.get("save_video", True))
            _saved_tiffs = bool(s.get("save_tiffs", True))
            if not (_saved_cine or _saved_tiffs):
                _saved_tiffs = True
            self._save_fmt_guard = True
            try:
                self._cam_save_video_chk.setChecked(_saved_cine)
                self._cam_save_tiffs_chk.setChecked(_saved_tiffs)
            finally:
                self._save_fmt_guard = False
            self._pipeline_check.setChecked(bool(s.get("run_ai_analysis", True)))
            self._auto_trig_chk.blockSignals(True)     # no save half-way through loading
            self._auto_trig_chk.setChecked(bool(s.get("auto_trigger_end", False)))
            self._auto_trig_chk.blockSignals(False)
            self._window_chk.blockSignals(True)
            self._window_chk.setChecked(bool(s.get("window_check_at_start", True)))
            self._window_chk.blockSignals(False)
            try:                        # a bad value must not stop the rest loading
                _cut = float(s.get("pressure_cutoff_bar") or 0)
            except (TypeError, ValueError):
                _cut = 0.0
            self._cutoff_bar = _cut if 0 < _cut <= 30 else None
            self._cutoff_entry.setText(f"{_cut:g}" if self._cutoff_bar else "")
            self._update_cutoff_status()
            try:
                _ramp = float(s.get("gas_ramp_sccm_s") or 0)
            except (TypeError, ValueError):
                _ramp = 0.0
            self._flow_ramp = _ramp if 0 < _ramp <= 12000 else None
            self._ramp_entry.setText(f"{_ramp:g}" if self._flow_ramp else "")
            self._ai_stride.setText(str(s.get("ai_stride", self.DEFAULT_STRIDE)))
            if hasattr(self, "_rho_liquid_entry"):
                self._rho_liquid_entry.setText(
                    str(s.get("rho_liquid") or f"{self.DEFAULT_RHO_LIQUID:g}"))
                self._rho_gas_entry.setText(
                    str(s.get("rho_gas") or f"{self.DEFAULT_RHO_GAS:g}"))
                # no default: an empty tag is honest, a guessed one is not
                self._fluid_tag_entry.setText(str(s.get("fluid_tag") or ""))
                self._gas_tag_entry.setText(str(s.get("gas_tag") or ""))
                self._update_glr_label()
            # Orifice — only restore a value the combo actually offers, so an old
            # or hand-edited settings file can't leave it blank.
            _orifice = s.get("orifice", "")
            self._orifice_len_entry.setText(str(s.get("orifice_length_mm") or ""))
            if _orifice and self._orifice_combo.findText(_orifice) >= 0:
                self._orifice_combo.blockSignals(True)
                self._orifice_combo.setCurrentText(_orifice)
                self._orifice_combo.blockSignals(False)
            self._bubbler_height_entry.blockSignals(True)
            self._bubbler_height_entry.setText(str(s.get("bubbler_height_mm", "")))
            self._bubbler_height_entry.blockSignals(False)
            self._update_cam_capacity()
            px_per_mm = float(s.get("px_per_mm", 0.0))
            if px_per_mm > 0:
                self._hdr_pxmm_lbl.setText(f"{px_per_mm:.1f} px/mm")
                self._hdr_pxmm_lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: 12px;")
            cone_idx = int(s.get("cone_camera_index", -1))
            if cone_idx >= 0 and CV2_AVAILABLE:
                self._cone_idx_spin.setValue(cone_idx)
                QTimer.singleShot(500, self._cone_start_camera)  # attempt auto-connect after UI is ready
            autofocus = bool(s.get("cone_autofocus", True))
            self._cone_autofocus_chk.setChecked(autofocus)
            self._cone_focus_spin.setValue(int(s.get("cone_focus", 0)))
            self._cone_focus_spin.setEnabled(not autofocus)
            self._cone_top_crop_spin.setValue(float(s.get("cone_top_crop", 0.05)))
            last_f = s.get("last_flow")
            if last_f is not None:
                self._last_flow = float(last_f)
                self._last_flow_btn.setText(f"Set last: {self._last_flow:.1f} sccm")
                self._last_flow_btn.setEnabled(True)
            # Auto-connect itself is scheduled unconditionally in __init__; this
            # only overrides which port it will try.
            alicat_port = s.get("alicat_port", "")
            if alicat_port:
                self._alicat_saved_port = alicat_port
            # Lamella analysis settings
            self._lamella_crop_cfg   = s.get("lamella_crop",       {"x": 860, "y": 829, "w": 307, "h": 583})
            self._lamella_model_path = s.get("lamella_model_path", "")
            self._lamella_arch       = s.get("lamella_arch",       "tiny")
            # Push loaded values into the widgets
            for axis in ("x", "y", "w", "h"):
                spin = getattr(self, f"_lamella_crop_{axis}", None)
                if spin is not None:
                    spin.blockSignals(True)
                    spin.setValue(self._lamella_crop_cfg.get(axis, 0))
                    spin.blockSignals(False)
            self._lamella_arch_combo.blockSignals(True)
            self._lamella_arch_combo.setCurrentText(self._lamella_arch)
            self._lamella_arch_combo.blockSignals(False)
            if self._lamella_model_path:
                fname = os.path.basename(self._lamella_model_path)
                self._lamella_status_lbl.setText(f"{fname} — click toggle to load")
            if s.get("lamella_on") and self._lamella_model_path:
                self._lamella_toggle_btn.setChecked(True)
        except Exception as e:
            print(f"[WARNING] Could not load camera settings: {e}")

    def _run_id(self, now, flow_str):
        """`HHMMSS_4500sccm_1000rpm_6000sps_or1.2_bh40`.

        run_summary.xlsx remains authoritative; this is a human-scannable copy
        so a folder listing shows the condition without opening anything. Do not
        parse it back as data -- a renamed folder would silently disagree with
        the spreadsheet and nothing would say which was right.
        """
        orifice = (self._orifice_combo.currentText() or "").replace("mm", "").strip()
        bh = _cond_token(self._bubbler_height_entry.text(), "", "")
        parts = [
            flow_str,
            _cond_token(self._rpm_entry.text(), "rpm", "norpm"),
            _cond_token(self._speed_entry.text(), "sps", "nosps"),
            f"or{orifice}" if orifice else "noor",
            f"bh{bh}" if bh else "nobh",
        ]
        return f"{now.strftime('%H%M%S')}_" + "_".join(parts)

    def _save_camera_settings(self):
        if getattr(self, "_loading_settings", False):
            return
        try:
            # Read existing px_per_mm so it's preserved even if called before calibration
            try:
                with open(self._settings_path()) as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
            lbl_text = self._hdr_pxmm_lbl.text().replace("px/mm", "").strip()
            try:
                px_per_mm = float(lbl_text) if lbl_text not in ("–", "") else existing.get("px_per_mm", 0.0)
            except ValueError:
                px_per_mm = existing.get("px_per_mm", 0.0)
            s = {
                "rho_liquid":        self._rho_liquid_entry.text()
                                     if hasattr(self, "_rho_liquid_entry") else "",
                "rho_gas":           self._rho_gas_entry.text()
                                     if hasattr(self, "_rho_gas_entry") else "",
                "fluid_tag":         self._fluid_tag_entry.text()
                                     if hasattr(self, "_fluid_tag_entry") else "",
                "gas_tag":           self._gas_tag_entry.text()
                                     if hasattr(self, "_gas_tag_entry") else "",
                "ip":                self._cam_ip.text(),
                "fps":               self._cam_fps.text(),
                "exposure_us":       self._cam_exp.text(),
                "width":             self._cam_width.text(),
                "height":            self._cam_height.text(),
                "pre_trigger_s":     self._cam_pre_s.text(),
                "post_trigger_s":    self._cam_post_s.text(),
                "px_per_mm":         px_per_mm,
                "cone_camera_index": self._cone_idx_spin.value() if (self._cone_cap is not None and self._cone_cap.isOpened()) else existing.get("cone_camera_index", -1),
                "save_video":        self._cam_save_video_chk.isChecked(),
                "save_tiffs":        self._cam_save_tiffs_chk.isChecked(),
                "orifice":           self._orifice_combo.currentText(),
                "orifice_length_mm": self._orifice_len_entry.text().strip(),
                "bubbler_height_mm": self._bubbler_height_entry.text().strip(),
                "run_ai_analysis":   self._pipeline_check.isChecked(),
                "auto_trigger_end":  self._auto_trig_chk.isChecked()
                                     if hasattr(self, "_auto_trig_chk") else False,
                "window_check_at_start": self._window_chk.isChecked()
                                     if hasattr(self, "_window_chk") else True,
                "pressure_cutoff_bar": getattr(self, "_cutoff_bar", None),
                "gas_ramp_sccm_s":   getattr(self, "_flow_ramp", None),
                "ai_stride":         self._get_ai_stride(),
                "cone_autofocus":    self._cone_autofocus_chk.isChecked(),
                "cone_focus":        self._cone_focus_spin.value(),
                "cone_top_crop":     self._cone_top_crop_spin.value(),
                "last_flow":         self._last_flow,
                "alicat_port":       self._alicat_saved_port,
                # Lamella analysis settings
                "lamella_crop":       getattr(self, "_lamella_crop_cfg",   {"x": 860, "y": 829, "w": 307, "h": 583}),
                "lamella_model_path": getattr(self, "_lamella_model_path", ""),
                "lamella_arch":       getattr(self, "_lamella_arch",       "smp"),
                "lamella_on":         getattr(self, "_lamella_on",         False),
            }
            def _write(tmp):
                with open(tmp, "w") as f:
                    json.dump(s, f, indent=2)
            _replace_atomically(self._settings_path(), _write)
        except Exception as e:
            print(f"[WARNING] Could not save camera settings: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _cam_path_hint(self) -> str:
        """Return a human-readable string showing where the next camera capture will be saved."""
        from datetime import date
        today = date.today()
        lacie = find_lacie_drive()
        base  = os.path.join(lacie, "Experiments") if lacie else os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "experiment_logs", "Experiments")
        if self._run_folder:
            return f"Saving to: {self._run_folder}"
        return (f"Saving to: {base}/{today.strftime('%Y/%m/%d')}/{{HHMMSS}}_Manual/")

    def _excel_save_path_hint(self):
        lacie = find_lacie_drive()
        if lacie:
            return os.path.join(lacie, "Experiments", "YYYY", "MM", "DD",
                                "HHMMSS_flowsccm", "run_summary.xlsx")
        return "Saving to: experiment_logs/ (no LaCie drive found)"

    def _warn(self, title, message):
        dlg = QMessageBox(self)
        dlg.setWindowTitle(title)
        dlg.setText(message)
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.setStyleSheet(f"""
            QMessageBox {{
                background-color: {CLR_PANEL};
                color: {CLR_TEXT};
            }}
            QLabel {{
                color: {CLR_TEXT};
                font-size: 13px;
            }}
            QPushButton {{
                background-color: {CLR_INPUT};
                color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER};
                border-radius: 8px;
                padding: 6px 20px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {CLR_ACCENT}; color: white; }}
        """)
        dlg.exec()

    def _require_arduino(self):
        if not self.arduino_connected:
            self._set_status("Arduino not connected", CLR_ORANGE)
            self._warn("Arduino Not Connected",
                       "No Arduino is connected.\n\n"
                       "Go to the Hardware tab, select the correct serial port, "
                       "and click Connect.")
            return False
        return True

    def _set_status(self, msg, color=None):
        self._status_lbl.setText(msg)
        c = color or CLR_TEXT_SEC
        self._status_lbl.setStyleSheet(f"color:{c}; font-size:13px;")
        self._status_dot.setStyleSheet(
            f"color:{c}; font-size:12px; background:transparent;")

    def keyPressEvent(self, event):
        # Space (camera trigger) is handled by _SpaceTriggerFilter: a focused
        # button takes Space before it ever reaches this method.
        focus = self.focusWidget()
        in_text_field = isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit))
        if not in_text_field:
            if event.key() == Qt.Key.Key_C and self._cone_capture_btn.isEnabled():
                self._cone_capture()
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        busy = []
        if self.pressure_data['experiment_active']:
            busy.append("an experiment is running (closing stops the traverse, "
                        "bubbler and gas)")
        if not self._cam_save_progress.isHidden():
            busy.append("the camera is saving a capture (closing will cut it short)")
        if busy:
            ans = QMessageBox.question(
                self, "Close Atomisation Control?",
                "Close now?\n\n• " + "\n• ".join(busy),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.serial_reading_active = False
        self._live_feed_timer.stop()
        if self.arduino:
            # Closing the port does not stop the board: halt the traverse first.
            try: self.arduino.send_stop()
            except Exception: pass
            self.arduino.disconnect()
        if self.rpm_arduino:
            try: self.rpm_arduino.send_stop()
            except Exception: pass
            self.rpm_arduino.disconnect()
        if self.alicat:
            # Stops the reader thread, which sets 0 sccm and closes the port.
            self._alicat_serial_active = False
            t = getattr(self, "_alicat_thread", None)
            if t and t.is_alive():
                t.join(timeout=1.0)
        if self.phantom:     self.phantom.disconnect()
        if self.afg:         self.afg.disconnect()
        # Let a save in progress finish -- AFTER the hardware above is stopped,
        # so it never delays a motor or the gas. Killing it mid-write could
        # leave a truncated master_log.xlsx, which holds every run ever logged.
        ex = getattr(self, "_excel_executor", None)
        if ex is not None:
            ex.shutdown(wait=True)
        super().closeEvent(event)


class _SpaceTriggerFilter(QObject):
    """Space = camera trigger, anywhere in the main window except while typing.

    Installed on the QApplication so it sees the key BEFORE the focused widget:
    a QPushButton with focus treats Space as a click, so handling Space in the
    window's keyPressEvent let it re-press whatever button was last clicked
    (Spin, Set Flow, Home, STOP EVERYTHING) instead of firing the camera.
    Press and release are both swallowed so no button half-activates. Dialogs
    are left alone (Space still presses their buttons)."""

    _TEXT_INPUTS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event):
        et = event.type()
        if et not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if event.key() != Qt.Key.Key_Space:
            return False
        if QApplication.activeWindow() is not self._window:
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, self._TEXT_INPUTS) or (
                isinstance(focus, QComboBox) and focus.isEditable()):
            return False
        if et == QEvent.Type.KeyPress and not event.isAutoRepeat():
            if self._window._cam_trigger_btn.isEnabled():
                self._window._cam_trigger()
        return True


class _OpaqueTooltipFilter(QObject):
    """Force tooltip windows to be fully opaque on macOS.

    macOS compositing makes tooltip windows translucent by default.
    This event filter catches every tooltip as it appears and removes
    the translucent-background attribute so the QToolTip stylesheet
    background is rendered solid.
    """
    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Polish):
            if isinstance(obj, QWidget) and (
                    obj.windowFlags() & Qt.WindowType.ToolTip):
                obj.setAttribute(
                    Qt.WidgetAttribute.WA_TranslucentBackground, False)
        return False


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Atomisation Control")
    app.setApplicationDisplayName("Atomisation Control")

    # macOS: rename the menu-bar entry from "Python" to "Atomisation Control"
    if platform.system() == "Darwin":
        try:
            from AppKit import NSBundle  # requires pyobjc-framework-Cocoa
            info = NSBundle.mainBundle().infoDictionary()
            if info is not None:
                info["CFBundleName"] = "Atomisation Control"
        except Exception:
            pass  # pyobjc not installed — menu bar will still show "Python"

    # App icon (dock / taskbar / window chrome)
    _icon_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "docs", "water-drop.png"
    )
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    # Fusion style renders identically on macOS + Windows and fully respects
    # Qt stylesheets (native macOS style ignores custom borders/backgrounds)
    app.setStyle("Fusion")
    app.setStyleSheet(BASE_STYLE)

    # Solid, opaque tooltips — palette tells Fusion the base colours,
    # event filter removes macOS translucent-background on tooltip windows
    _pal = app.palette()
    _pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(44, 44, 46))
    _pal.setColor(QPalette.ColorRole.ToolTipText, QColor(242, 242, 247))
    app.setPalette(_pal)
    app.installEventFilter(_OpaqueTooltipFilter(app))

    # Use system font
    font = QFont(FONT_FAMILY)
    font.setPixelSize(13)
    app.setFont(font)

    window = AtomisationApp()

    # Explicitly style every input widget — belt-and-suspenders against any
    # remaining cascade issues in deeply-nested layouts
    _le_ss = (
        f"QLineEdit {{ background-color: {CLR_INPUT}; color: {CLR_TEXT}; "
        f"border: 1px solid #606064; border-radius: 8px; padding: 6px 10px; }} "
        f"QLineEdit:focus {{ border: 1px solid {CLR_ACCENT}; }}"
    )
    _cb_ss = (
        f"QComboBox {{ background-color: {CLR_INPUT}; color: {CLR_TEXT}; "
        f"border: 1px solid #606064; border-radius: 8px; padding: 6px 10px; }} "
        f"QComboBox:focus {{ border: 1px solid {CLR_ACCENT}; }} "
        f"QComboBox::drop-down {{ border: none; padding-right: 8px; }} "
        f"QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; "
        f"border-right: 4px solid transparent; border-top: 6px solid {CLR_TEXT_SEC}; "
        f"margin-right: 8px; }} "
        f"QComboBox QAbstractItemView {{ background-color: #2c2c2e; color: {CLR_TEXT}; "
        f"border: 1px solid #606064; selection-background-color: {CLR_ACCENT}; "
        f"selection-color: white; outline: none; }}"
    )
    for le in window.findChildren(QLineEdit):
        le.setStyleSheet(_le_ss)
    for cb in window.findChildren(QComboBox):
        cb.setStyleSheet(_cb_ss)

    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
