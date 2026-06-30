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
  │  Left panel      │  Tab bar: Hardware / Camera /    │
  │  - Shadowgraph   │          Experiment / AFG        │
  │  - Pressure live │  Tab content                     │
  │  - Motor travel  │                                  │
  ├──────────────────┴──────────────────────────────────┤
  │  Status bar + [▶ START EXPERIMENT]                  │
  └─────────────────────────────────────────────────────┘
"""

import io
import os
import sys
import math
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
import matplotlib.pyplot as plt

import pyqtgraph as pg
pg.setConfigOption('background', '#2c2c2e')
pg.setConfigOption('foreground', '#8e8e93')
pg.setConfigOptions(antialias=True)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QTextEdit, QPlainTextEdit,
    QFrame, QTabWidget, QSizePolicy, QProgressBar, QScrollArea,
    QSpacerItem, QGridLayout, QMessageBox, QFileDialog, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QObject, QThread, QSize, QEvent, QRegularExpression
from PySide6.QtGui import QFont, QPixmap, QImage, QColor, QPalette, QIcon, QPainter, QPen, QIntValidator, QDoubleValidator, QRegularExpressionValidator

# ── Path setup ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config_loader import get_gui_config, resolve_path, find_lacie_drive
    GUI_CONFIG = get_gui_config()
except ImportError:
    GUI_CONFIG = {}
    def resolve_path(p, lacie_base=None): return p
    def find_lacie_drive(): return None

# Cone_4.py lives in Trials/ relative to the repo root
_TRIALS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Trials")
if _TRIALS_DIR not in sys.path:
    sys.path.insert(0, _TRIALS_DIR)
CONE4_AVAILABLE = False
try:
    from Cone_4 import detect_cone_angle
    CONE4_AVAILABLE = True
except ImportError:
    pass

# ── Optional SDKs ────────────────────────────────────────────────────────────
PHANTOM_SDK_AVAILABLE = False
try:
    from pyphantom import Phantom, utils, cine
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

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=5)
            time.sleep(2)
            start_time = time.time()
            try: self.ser.reset_input_buffer()
            except Exception: pass
            detected = False
            while time.time() - start_time < 8 and not detected:
                line = self.ser.readline().decode('utf-8', errors='replace').strip()
                if not line: continue
                log_serial(f"Received on connect: {line}")
                if "ARDUINO_READY" in line:
                    detected = True
                    break
                time.sleep(0.05)
            if not detected:
                raise RuntimeError("No Arduino detected on this port.")
        except serial.SerialException as e:
            if "Resource busy" in str(e):
                raise RuntimeError(f"Port {self.port} is busy.")
            raise RuntimeError(f"Could not open port {self.port}: {e}")

    def send_motor_command(self, speed, distance):
        command = f"SPEED:{speed};DIST:{distance}\n"
        self.ser.write(command.encode())
        log_serial(f"Sent: {command.strip()}")

    def send_pressure_command(self, pressure):
        command = f"PRESSURE:{pressure}\n"
        self.ser.write(command.encode())
        log_serial(f"Sent: {command.strip()}")

    def send_pressure_off_command(self):
        self.ser.write("PRESSURE_OFF\n".encode())
        log_serial("Sent: PRESSURE_OFF")

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


class PhantomController:
    def __init__(self):
        self.ph = None; self.cam = None; self.current_cine = None
        self.is_connected = False; self.is_recording = False
        self.recording_started = False; self.is_armed = False
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
        self.recording_started = False; return True

    def trigger(self):
        self.cam.trigger(); self.recording_started = True; self.is_armed = False; return True

    def save_recording(self, output_path, cine_index=1, file_format='cine', frame_range=None,
                       progress_cb=None):
        self.current_cine = self.cam.Cine(cine_index)
        fmt_map = {'cine': 0, 'tiff': -8, 'tif': -8, 'avi': -7}
        self.current_cine.save_type = utils.FileTypeEnum(fmt_map.get(file_format, 0))
        if frame_range is None:
            r = self.current_cine.range
            self.current_cine.save_range = utils.FrameRange(r.first_image, r.last_image)
        else:
            self.current_cine.save_range = utils.FrameRange(frame_range[0], frame_range[1])
        self.current_cine.save_name = output_path
        # The SDK's blocking save() has a known bug where it throws even on success.
        # Use save_non_blocking() and poll save_percentage until complete.
        # The callback sometimes stalls before reaching 100 — treat >= 90% stable
        # for 30 s as done (file is effectively complete at that point).
        self.current_cine._save_percentage = -1
        self.current_cine.save_non_blocking()
        deadline = time.time() + 600.0  # 10-min hard ceiling
        last_pct, last_change = -1, time.time()
        while time.time() < deadline:
            pct = self.current_cine.save_percentage
            if pct >= 100:
                if progress_cb: progress_cb(100)
                break
            if pct != last_pct:
                last_change = time.time()
                last_pct = pct
                if progress_cb: progress_cb(max(0, pct))
            elif pct >= 90 and time.time() - last_change > 30.0:
                if progress_cb: progress_cb(100)
                break  # stalled near end — assume complete
            time.sleep(0.25)
        else:
            raise RuntimeError(
                f"CINE save timed out (progress: {self.current_cine.save_percentage}%)")
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
        # get_imagessave uses range() which is exclusive at the end — pass f_end + 1
        for i, (_, img) in enumerate(c.get_imagessave(utils.FrameRange(f_start, f_end + 1))):
            cv2.imwrite(os.path.join(output_dir, f"{tiff_prefix}{i:06d}.tif"), img)
            if progress_cb: progress_cb(int((i + 1) / total * 100))
        return True

    def abort(self):
        if self.is_recording:
            self.cam.clear_ram(); self.is_recording = False; self.recording_started = False
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
        self.pulse_duration = 0.001; self.pulse_amplitude = 5.0
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


# ── Main application window ───────────────────────────────────────────────────

class AtomisationApp(QMainWindow):

    MAX_MOTOR_MM = 72.5   # physical travel limit

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
        self.serial_reader_thread = None

        self.rpm_arduino: RpmController | None = None
        self.rpm_connected = False
        self.rpm_spinning = False
        self._rpm_serial_active = False

        self._ramp_running = False
        self._movement_done_event = threading.Event()

        self.phantom = PhantomController() if PHANTOM_SDK_AVAILABLE else None
        self.afg     = AFGController()     if PYVISA_AVAILABLE       else None

        self.is_windows = platform.system() == "Windows"
        self.camera_available = self.is_windows and PHANTOM_SDK_AVAILABLE

        self.cumulative_distance = 0.0
        self._pre_move_cumulative  = 0.0   # cumulative_distance before the current motor move
        self._pending_move_distance = 0.0  # distance of the move in progress
        self._jogging = False
        self.cleaning_in_progress = False
        self._experiment_saved = True   # True until an experiment runs unsaved
        self._run_folder = None          # Set eagerly on Start Experiment, cleared on next start
        self._cam_pre_frames  = 0        # computed from pre-trigger seconds × fps at Apply Config
        self._cam_post_frames = 0        # computed from post-trigger seconds × fps at Apply Config

        self.pressure_data = {
            'live_buffer': {'timestamps': [], 'pressures': []},
            'experiment_data': {'timestamps': [], 'pressures': []},
            'experiment_active': False,
            'experiment_start_time': None,
        }
        self.pressure_data['live_buffer_start_time'] = time.time()
        self._last_experiment_snapshot = {'timestamps': [], 'pressures': []}
        self._last_cone_path = None   # path of most recent cone image (raw or annotated)
        self._cone_history: deque = deque(maxlen=5)  # (annotated_path, angle) tuples, newest last
        self._last_pressure: float | None = None     # last successfully set pressure (persisted)

        # Lamella analysis state (populated by _load_camera_settings; used by Phase 1 GUI)
        self._lamella_crop_cfg:   dict = {"x": 0, "y": 0, "w": 256, "h": 256}
        self._lamella_model_path: str  = ""
        self._lamella_arch:       str  = "smp"
        self._lamella_on:         bool = False   # toggle flag — True only when user enables
        self._lamella_seg        = None          # StubSegmenter or LamellaSegmenter instance
        self._lamella_busy:       bool = False   # True while inference thread is running
        self._lamella_pending_frame             = None  # latest-frame slot (replaced, never queued)
        self._lamella_result                    = None  # most recent Result — used by _live_feed_update for overlay

        # EMA smoothing state (α=0.3: strong noise rejection, <2.5s lag on step changes)
        self._pressure_smooth_enabled = True
        self._EMA_ALPHA = 0.3
        self._pressure_ema = None   # reset when new readings arrive after a gap

        self._cone_cap  = None  # cv2.VideoCapture instance — must exist before _build_ui wires signals
        self._log_queue = queue.Queue()  # thread-safe sink for pipeline/cone stdout → GUI log panel

        # ── Build UI ──────────────────────────────────────────────────────────
        self._last_saved_run_folder: str | None = None
        self._build_ui()
        self._load_camera_settings()
        QTimer.singleShot(0, self, self._poll_lacie)
        QTimer.singleShot(0, self, self._update_next_save_preview)

        # Pipeline cross-thread signal connections (UI must exist first)
        self._pipeline_done.connect(self._on_pipeline_complete)
        self._pipeline_err.connect(self._on_pipeline_error)

        # ── Timers ────────────────────────────────────────────────────────────
        self._graph_timer = QTimer(self)
        self._graph_timer.timeout.connect(self._update_pressure_graph)
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

        self._run_elapsed_timer = QTimer(self)
        self._run_elapsed_timer.setInterval(1000)
        self._run_elapsed_timer.timeout.connect(self._tick_run_timer)
        self._run_start_time: float | None = None

        self._lacie_poll_timer = QTimer(self)
        self._lacie_poll_timer.setInterval(5000)
        self._lacie_poll_timer.timeout.connect(self._poll_lacie)
        self._lacie_poll_timer.start()

        # Log panel queue drain — flushes pipeline/cone stdout into the right-panel log widget
        self._log_poll_timer = QTimer(self)
        self._log_poll_timer.timeout.connect(self._flush_log_queue)
        self._log_poll_timer.start(100)

        # Auto-connect Arduino
        ports = self._get_serial_ports()
        if ports:
            self._trigger_arduino_connect()

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
        self._hdr_pressure_lbl = QLabel("– BAR")

        # Arduino, AFG, BAR — plain dot + label
        for dot, lbl in [
            (self._hdr_arduino_dot,  self._hdr_arduino_lbl),
            (self._hdr_afg_dot,      self._hdr_afg_lbl),
            (self._hdr_pressure_dot, self._hdr_pressure_lbl),
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

        # ── Shadowgraph preview card ──────────────────────────────────────────
        preview_card = card()
        preview_card.layout().setSpacing(8)

        top_row = QWidget()
        tr = QHBoxLayout(top_row)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.addWidget(title_label("Latest Result", 13))
        tr.addStretch()
        self._refresh_btn = ghost_button("↻ Refresh")
        self._refresh_btn.setFixedHeight(28)
        self._refresh_btn.setToolTip(
            "<b>Refresh latest result</b><br>"
            "1. Scans the LaCie drive for ai_result.png<br>"
            "2. Looks in the current run's shadowgraph/analysis/ folder<br>"
            "3. Displays the most recent result in the preview above")
        self._refresh_btn.clicked.connect(self._refresh_shadowgraph)
        tr.addWidget(self._refresh_btn)
        preview_card.layout().addWidget(top_row)

        self._shadow_label = QLabel()
        self._shadow_label.setFixedSize(370, 250)
        self._shadow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shadow_label.setStyleSheet(f"""
            background-color: {CLR_INPUT};
            border-radius: 8px;
            color: {CLR_TEXT_SEC};
            font-size: 12px;
        """)
        self._shadow_label.setText("No result found\nClick ↻ Refresh")
        preview_card.layout().addWidget(self._shadow_label)

        self._result_path_label = QLabel("")
        self._result_path_label.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 10px;")
        self._result_path_label.setWordWrap(True)
        preview_card.layout().addWidget(self._result_path_label)

        self._pipeline_status = QLabel("")
        self._pipeline_status.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 11px;")
        self._pipeline_status.setWordWrap(True)
        preview_card.layout().addWidget(self._pipeline_status)

        # AI metrics — populated after pipeline run
        metrics_row = QWidget()
        mr = QHBoxLayout(metrics_row); mr.setContentsMargins(0, 0, 0, 0); mr.setSpacing(16)
        self._ai_confidence_lbl = QLabel("Confidence: –")
        self._ai_diameter_lbl   = QLabel("Avg droplet: –")
        self._ai_dl_lbl         = QLabel("D/L: –")
        for lbl in [self._ai_confidence_lbl, self._ai_diameter_lbl, self._ai_dl_lbl]:
            lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 11px;")
            mr.addWidget(lbl)
        mr.addStretch()
        preview_card.layout().addWidget(metrics_row)

        vl.addWidget(preview_card)

        # ── Pressure graph card ───────────────────────────────────────────────
        graph_card = card()
        graph_card.layout().setSpacing(6)

        graph_hdr = QWidget()
        graph_hdr_l = QHBoxLayout(graph_hdr)
        graph_hdr_l.setContentsMargins(0, 0, 0, 0)
        graph_hdr_l.setSpacing(8)
        graph_hdr_l.addWidget(title_label("Pressure (live)", 13))
        graph_hdr_l.addStretch()
        self._smooth_cb = QCheckBox("Smooth")
        self._smooth_cb.setChecked(True)
        self._smooth_cb.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        self._smooth_cb.setToolTip(
            "<b>EMA smoothing (α=0.3)</b><br>"
            "Exponential moving average — reduces electrical noise on the ADC line "
            "without introducing the step-change lag of a simple rolling average.<br>"
            "Raw values are always stored for export regardless of this setting.")
        self._smooth_cb.toggled.connect(self._on_smooth_toggled)
        graph_hdr_l.addWidget(self._smooth_cb)
        graph_card.layout().addWidget(graph_hdr)

        self._graph_widget = pg.PlotWidget()
        self._graph_widget.setFixedHeight(180)
        self._graph_widget.setBackground('#2c2c2e')

        _plot = self._graph_widget.getPlotItem()
        _plot.setLabel('left',  'Pressure', units='BAR',
                       color='#8e8e93', **{'font-size': '9pt'})
        _plot.setLabel('bottom', 'Time', units='s',
                       color='#8e8e93', **{'font-size': '9pt'})
        _plot.getAxis('left').setTextPen(pg.mkPen('#8e8e93'))
        _plot.getAxis('bottom').setTextPen(pg.mkPen('#8e8e93'))
        _plot.getAxis('left').setPen(pg.mkPen('#3a3a3c'))
        _plot.getAxis('bottom').setPen(pg.mkPen('#3a3a3c'))
        _plot.showGrid(x=True, y=True, alpha=0.15)
        _plot.setMouseEnabled(x=False, y=False)
        _plot.hideButtons()

        self._pressure_curve = _plot.plot(
            pen=pg.mkPen(color=CLR_ACCENT, width=2.5)
        )
        graph_card.layout().addWidget(self._graph_widget)
        vl.addWidget(graph_card)

        # ── Motor travel + Volume row ──────────────────────────────────────────
        motor_vol_row = QWidget()
        motor_vol_row.setStyleSheet("background: transparent;")
        mvrl = QHBoxLayout(motor_vol_row)
        mvrl.setContentsMargins(0, 0, 0, 0)
        mvrl.setSpacing(6)

        # Motor travel card (3/4 width)
        motor_card = card(padding=10)
        motor_card.layout().setSpacing(6)

        mh = QWidget()
        mhl = QHBoxLayout(mh); mhl.setContentsMargins(0,0,0,0)
        mhl.addWidget(title_label("Motor Travel", 13))
        mhl.addStretch()
        self._travel_label = QLabel(f"0.0 / {self.MAX_MOTOR_MM} mm")
        self._travel_label.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        mhl.addWidget(self._travel_label)
        motor_card.layout().addWidget(mh)

        self._travel_bar = QProgressBar()
        self._travel_bar.setRange(0, 1000)
        self._travel_bar.setValue(0)
        self._travel_bar.setTextVisible(False)
        self._travel_bar.setFixedHeight(8)
        motor_card.layout().addWidget(self._travel_bar)

        self._travel_warning = QLabel("")
        self._travel_warning.setStyleSheet(f"color: {CLR_ORANGE}; font-size: 11px;")
        motor_card.layout().addWidget(self._travel_warning)

        mvrl.addWidget(motor_card, 3)

        # Volume card (1/4 width)
        vol_card = card(padding=10)
        vol_card.layout().setSpacing(4)

        vol_card.layout().addWidget(title_label("Volume", 13))

        self._vol_label = QLabel("0.00 mL")
        self._vol_label.setStyleSheet(
            f"color: {CLR_TEXT}; font-size: 14px; font-weight: 700;")
        self._vol_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vol_card.layout().addWidget(self._vol_label)

        mvrl.addWidget(vol_card, 1)

        vl.addWidget(motor_vol_row)

        # ── Pressure Off (always visible) ─────────────────────────────────────
        pressure_off_card = card(padding=10)
        pressure_off_card.layout().setSpacing(6)
        pressure_off_card.layout().addWidget(title_label("Emergency", 13))

        self._pressure_off_btn_left = accent_button("Motor and Pressure Off", CLR_RED)
        self._pressure_off_btn_left.setFixedHeight(40)
        self._pressure_off_btn_left.setToolTip(
            "<b>Emergency pressure off</b><br>"
            "1. Sends an immediate stop command to the Arduino<br>"
            "2. Closes the pressure valve<br>"
            "3. Zeroes the AliCat setpoint")
        self._pressure_off_btn_left.clicked.connect(self._pressure_off)
        pressure_off_card.layout().addWidget(self._pressure_off_btn_left)

        vl.addWidget(pressure_off_card)
        vl.addStretch()

        # Defer the drive scan until after the window is shown — scanning
        # the LaCie drive during __init__ blocks the window from opening.
        QTimer.singleShot(500, self._refresh_shadowgraph)
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

        self._nozzle_entry = QLineEdit()
        self._nozzle_entry.setPlaceholderText("e.g. 1")
        self._nozzle_entry.setValidator(QRegularExpressionValidator(QRegularExpression(r'[A-Za-z0-9]*')))
        self._nozzle_entry.textChanged.connect(self._update_next_save_preview)
        nozzle_card.layout().addWidget(input_row("Nozzle No.", self._nozzle_entry, label_width=90))

        self._orifice_combo = QComboBox()
        self._orifice_combo.addItems(["0.2mm","0.3mm","0.5mm","0.8mm","1mm","1.2mm","1.4mm","1.6mm","1.8mm","2mm"])
        nozzle_card.layout().addWidget(input_row("Orifice", self._orifice_combo, label_width=90))

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
            "1. Reads the current run fields (pressure, date, notes, etc.)<br>"
            "2. Appends a new row to the experiment log spreadsheet<br>"
            "3. Saves the ai_result image path and metrics alongside it<br>"
            "4. Writes the file to the LaCie drive")
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
        self._tabs.addTab(self._build_camera_tab(),       "  Camera  ")
        self._tabs.addTab(self._build_afg_tab(),          "  AFG1062  ")
        self._tabs.addTab(self._build_calibration_tab(),  "  Calibration  ")
        self._tabs.addTab(self._build_cone_tab(),         "  Cone  ")
        self._tabs.addTab(self._build_testers_tab(),      "  Testers  ")
        self._tabs.addTab(self._build_how_to_tab(),       "")
        self._tabs.setTabVisible(6, False)   # content shown via corner button

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
        _how_to_btn.clicked.connect(
            lambda checked: self._tabs.setCurrentIndex(6 if checked else 0)
        )
        self._tabs.currentChanged.connect(
            lambda idx: _how_to_btn.setChecked(idx == 5)
        )
        self._tabs.setCornerWidget(_how_to_btn, Qt.Corner.TopRightCorner)
        return self._tabs

    # ── Hardware tab ─────────────────────────────────────────────────────────

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

        # ── Portenta ──────────────────────────────────────────────────────────
        c = card(w)
        c.layout().addWidget(section_label("PORTENTA"))
        c.layout().addWidget(separator())

        port_row = QWidget()
        pr = QHBoxLayout(port_row); pr.setContentsMargins(0,0,0,0); pr.setSpacing(8)
        lbl = QLabel("Port"); lbl.setFixedWidth(80)
        lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        self._port_combo.addItems(self._get_serial_ports())
        self._port_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._port_combo.setMinimumWidth(120)
        self._port_combo.setFixedHeight(51)
        refresh_port_btn = ghost_button("Refresh")
        refresh_port_btn.setFixedHeight(34)
        refresh_port_btn.setToolTip(
            "<b>Refresh serial ports</b><br>"
            "1. Re-scans all COM/USB serial ports on this computer<br>"
            "2. Updates the dropdown list with the new results")
        refresh_port_btn.clicked.connect(self._refresh_ports)
        pr.addWidget(lbl); pr.addWidget(self._port_combo); pr.addWidget(refresh_port_btn)
        c.layout().addWidget(port_row)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row); br.setContentsMargins(0,0,0,0); br.setSpacing(8)
        self._connect_btn    = accent_button("Connect",    CLR_ACCENT)
        self._disconnect_btn = ghost_button("Disconnect")
        self._disconnect_btn.setEnabled(False)
        self._connect_btn.setFixedHeight(36)
        self._disconnect_btn.setFixedHeight(36)
        self._connect_btn.setToolTip(
            "<b>Connect to Arduino</b><br>"
            "1. Opens a serial connection on the selected port<br>"
            "2. Handshakes with the Portenta H7<br>"
            "3. Enables pressure and motor controls")
        self._disconnect_btn.setToolTip(
            "<b>Disconnect Arduino</b><br>"
            "1. Sends a disconnect command to the Portenta<br>"
            "2. Closes the serial port and releases it")
        self._connect_btn.clicked.connect(self._trigger_arduino_connect)
        self._disconnect_btn.clicked.connect(self._trigger_arduino_disconnect)
        self._arduino_status_lbl = QLabel("Not connected")
        self._arduino_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        br.addWidget(self._connect_btn); br.addWidget(self._disconnect_btn)
        br.addStretch(); br.addWidget(self._arduino_status_lbl)
        c.layout().addWidget(btn_row)
        vl.addWidget(c)

        # ── Arduino Uno (RPM motor) ────────────────────────────────────────────
        cu = card(w)
        cu.layout().addWidget(section_label("ARDUINO UNO"))
        cu.layout().addWidget(separator())

        rpm_port_row = QWidget()
        rpr = QHBoxLayout(rpm_port_row); rpr.setContentsMargins(0,0,0,0); rpr.setSpacing(8)
        rpm_port_lbl = QLabel("Port"); rpm_port_lbl.setFixedWidth(80)
        rpm_port_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._rpm_port_combo = QComboBox()
        self._rpm_port_combo.setEditable(True)
        self._rpm_port_combo.addItems(self._get_serial_ports())
        self._rpm_port_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._rpm_port_combo.setMinimumWidth(120)
        self._rpm_port_combo.setFixedHeight(51)
        rpm_refresh_btn = ghost_button("Refresh")
        rpm_refresh_btn.setFixedHeight(34)
        rpm_refresh_btn.setToolTip(
            "<b>Refresh serial ports</b><br>"
            "Re-scans all COM/USB serial ports and updates the dropdown")
        rpm_refresh_btn.clicked.connect(self._refresh_rpm_ports)
        rpr.addWidget(rpm_port_lbl); rpr.addWidget(self._rpm_port_combo); rpr.addWidget(rpm_refresh_btn)
        cu.layout().addWidget(rpm_port_row)

        rpm_btn_row = QWidget()
        rbr = QHBoxLayout(rpm_btn_row); rbr.setContentsMargins(0,0,0,0); rbr.setSpacing(8)
        self._rpm_connect_btn    = accent_button("Connect",    CLR_ACCENT)
        self._rpm_disconnect_btn = ghost_button("Disconnect")
        self._rpm_disconnect_btn.setEnabled(False)
        self._rpm_connect_btn.setFixedHeight(36)
        self._rpm_disconnect_btn.setFixedHeight(36)
        self._rpm_connect_btn.setToolTip(
            "<b>Connect to Arduino Uno</b><br>"
            "Opens a serial connection on the selected port at 115200 baud")
        self._rpm_disconnect_btn.setToolTip(
            "<b>Disconnect Arduino Uno</b><br>"
            "Stops the motor and closes the serial port")
        self._rpm_connect_btn.clicked.connect(self._trigger_rpm_connect)
        self._rpm_disconnect_btn.clicked.connect(self._trigger_rpm_disconnect)
        self._rpm_status_lbl = QLabel("Not connected")
        self._rpm_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        rbr.addWidget(self._rpm_connect_btn); rbr.addWidget(self._rpm_disconnect_btn)
        rbr.addStretch(); rbr.addWidget(self._rpm_status_lbl)
        cu.layout().addWidget(rpm_btn_row)

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
        cu.layout().addWidget(rpm_ctrl_row)
        vl.addWidget(cu)

        # ── Pressure ──────────────────────────────────────────────────────────
        c2 = card(w)
        c2.layout().addWidget(section_label("PRESSURE"))
        c2.layout().addWidget(separator())

        p_input_row = QWidget()
        pir = QHBoxLayout(p_input_row); pir.setContentsMargins(0,0,0,0); pir.setSpacing(8)
        p_lbl = QLabel("Target (BAR)"); p_lbl.setFixedWidth(110)
        p_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._pressure_entry = QLineEdit(); self._pressure_entry.setPlaceholderText("0.0 – 26.4")
        self._pressure_entry.setMinimumWidth(80)
        self._pressure_entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._pressure_entry.setValidator(QDoubleValidator(0.0, 26.4, 2))
        self._pressure_entry.textChanged.connect(self._update_next_save_preview)
        set_p_btn = accent_button("Set Pressure", CLR_ACCENT)
        set_p_btn.setFixedHeight(36)
        set_p_btn.setToolTip(
            "<b>Set pressure</b><br>"
            "1. Validates the entered value (0.0 – 26.4 BAR)<br>"
            "2. Sends the setpoint to the Arduino over serial<br>"
            "3. Arduino forwards it to the AliCat controller")
        set_p_btn.clicked.connect(self._set_pressure)
        off_p_btn = accent_button("Pressure Off", CLR_RED)
        off_p_btn.setFixedHeight(36)
        off_p_btn.setToolTip(
            "<b>Pressure off</b><br>"
            "1. Immediately closes the pressure valve<br>"
            "2. Zeroes the AliCat setpoint")
        off_p_btn.clicked.connect(self._pressure_off_only)

        self._last_pressure_btn = QPushButton("Set last pressure")
        self._last_pressure_btn.setStyleSheet(f"""
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
        self._last_pressure_btn.setEnabled(False)
        self._last_pressure_btn.clicked.connect(self._set_last_pressure)

        # Stack Set Pressure + Set last pressure vertically, then slot into pir
        set_p_stack = QWidget()
        set_p_vl = QVBoxLayout(set_p_stack)
        set_p_vl.setContentsMargins(0, 0, 0, 0)
        set_p_vl.setSpacing(4)
        set_p_vl.addWidget(set_p_btn)
        set_p_vl.addWidget(self._last_pressure_btn)
        pir.addWidget(p_lbl); pir.addWidget(self._pressure_entry)
        pir.addWidget(set_p_stack); pir.addStretch(); pir.addWidget(off_p_btn)
        c2.layout().addWidget(p_input_row)

        cur_row = QWidget()
        crr = QHBoxLayout(cur_row); crr.setContentsMargins(0,0,0,0); crr.setSpacing(8)
        cur_lbl = QLabel("Current"); cur_lbl.setFixedWidth(110)
        cur_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._cur_pressure_lbl = QLabel("0.0 BAR")
        self._cur_pressure_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:16px; font-weight:700;")
        crr.addWidget(cur_lbl); crr.addWidget(self._cur_pressure_lbl); crr.addStretch()
        c2.layout().addWidget(cur_row)
        vl.addWidget(c2)

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
        _dist_rl.addWidget(input_row("Distance (mm)", self._distance_entry))
        _dist_rl.addWidget(self._volume_lbl)
        c3.layout().addWidget(_dist_row)

        motor_btns = QWidget()
        mb = QHBoxLayout(motor_btns); mb.setContentsMargins(0,0,0,0); mb.setSpacing(8)
        self._home_btn  = accent_button("🏠  Home",    CLR_ORANGE)
        self._clean_btn = accent_button("🧼  Clean",   CLR_PURPLE)
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

        self._home_btn.setFixedHeight(36); self._clean_btn.setFixedHeight(36); self._move_btn.setFixedHeight(36)
        self._home_btn.setToolTip(
            "<b>Home motor</b><br>"
            "1. Drives the motor to the reference (zero) position<br>"
            "2. Sets the internal position counter to zero<br>"
            "Run this once before any other motor commands")
        self._clean_btn.setToolTip(
            "<b>Cleaning cycle</b><br>"
            "1. Moves the motor forward through the cleaning stroke<br>"
            "2. Returns to the starting position<br>"
            "Flushes the nozzle to clear any blockages")
        self._move_btn.setToolTip(
            "<b>Move motor</b><br>"
            "1. Reads the Speed (steps/s) and Distance (mm) fields<br>"
            "2. Sends a relative move command to the Portenta<br>"
            "3. Motor moves by that distance at that speed")
        self._home_btn.clicked.connect(self._home_motor)
        self._clean_btn.clicked.connect(self._start_cleaning)
        self._move_btn.clicked.connect(self._move_motor)
        mb.addWidget(self._home_btn); mb.addWidget(self._clean_btn)
        mb.addStretch(); mb.addWidget(self._homed_dot); mb.addWidget(homed_lbl)
        mb.addStretch(); mb.addWidget(jog_widget); mb.addWidget(self._move_btn)
        c3.layout().addWidget(motor_btns)
        vl.addWidget(c3)

        vl.addStretch()
        scroll.setWidget(w)
        return scroll

    # ── Camera tab ────────────────────────────────────────────────────────────

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
        self._cam_connect_btn.setToolTip(
            "<b>Connect to Phantom camera</b><br>"
            "1. Connects to the camera at the entered IP address<br>"
            "2. Initialises the Phantom SDK<br>"
            "3. Enables capture and config controls")
        self._cam_ping_btn.setToolTip(
            "<b>Ping camera</b><br>"
            "1. Sends a network ping to the camera IP<br>"
            "2. Reports whether the camera is reachable on the network<br>"
            "Use this to check connectivity before connecting")
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
        self._cam_fps      = QLineEdit("1000"); self._cam_fps.setFixedWidth(_W)
        self._cam_exp      = QLineEdit("500");  self._cam_exp.setFixedWidth(_W)
        self._cam_exp_idx  = QLineEdit("0");    self._cam_exp_idx.setFixedWidth(_W)
        self._cam_width    = QLineEdit("2560"); self._cam_width.setFixedWidth(_W)
        self._cam_height   = QLineEdit("1600"); self._cam_height.setFixedWidth(_W)
        self._cam_pre_s    = QLineEdit("0.5");  self._cam_pre_s.setFixedWidth(_W)
        self._cam_post_s   = QLineEdit("0.5");  self._cam_post_s.setFixedWidth(_W)

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
        cap_vl.addWidget(self._cam_save_video_chk)

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
        c3.layout().addWidget(self._pipeline_check)
        _pipeline_desc = QLabel("When enabled, Dennis (Mask R-CNN) runs automatically after each capture — detecting droplets and ligaments and saving ai_result.png + metrics to the run folder.")
        _pipeline_desc.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        _pipeline_desc.setWordWrap(True)
        c3.layout().addWidget(_pipeline_desc)

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
            "2. Saves pre-trigger + post-trigger frames as CINE and TIFFs<br>"
            "3. Identifies the brightest frame<br>"
            "4. If 'Run AI analysis' is ticked, runs Dennis immediately<br>"
            "5. Camera re-arms automatically for the next trigger")
        self._cam_abort_btn.clicked.connect(self._cam_abort)
        self._cam_arm_btn.clicked.connect(self._cam_arm)
        self._cam_trigger_btn.clicked.connect(self._cam_trigger)
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

        # Test Pipeline card
        c_test = card(w)
        c_test.layout().addWidget(section_label("TEST PIPELINE"))
        c_test.layout().addWidget(separator())
        _test_desc = QLabel(
            "Runs Dennis on existing frames from {LaCie}/Phantom/frames/ "
            "and writes results to {LaCie}/Experiments/Trials/. "
            "Uses current calibration px/mm (falls back to 52.3)."
        )
        _test_desc.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        _test_desc.setWordWrap(True)
        c_test.layout().addWidget(_test_desc)
        self._test_pipeline_btn = accent_button("Test Pipeline", CLR_ACCENT)
        self._test_pipeline_btn.setFixedHeight(36)
        self._test_pipeline_btn.setToolTip(
            "<b>Test pipeline</b><br>"
            "1. Loads existing frames from {LaCie}/Phantom/frames/<br>"
            "2. Runs Dennis (Mask R-CNN) to detect droplets and ligaments<br>"
            "3. Saves results to {LaCie}/Experiments/Trials/<br>"
            "Uses current calibration px/mm (falls back to 52.3)")
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
            QPushButton:disabled {{ color: {CLR_TEXT_SEC}; border-color: {CLR_BORDER}; }}
        """)
        self._lamella_toggle_btn.setEnabled(False)   # enabled once feed is running
        self._lamella_toggle_btn.setToolTip(
            "<b>Lamella Analysis</b><br>"
            "Toggle ON to overlay detected lamella thickness on the live feed.<br>"
            "Requires the live feed to be running.<br>"
            "Has no effect on droplet detection or other modes.")
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
        self._lamella_arch_combo.addItems(["stub", "smp", "tiny"])
        self._lamella_arch_combo.setCurrentText("stub")
        self._lamella_arch_combo.setFixedHeight(28)
        self._lamella_arch_combo.setToolTip(
            "<b>stub</b> — synthetic test mask (no model required)<br>"
            "<b>smp</b> — transfer-learning U-Net (MobileNetV2, recommended)<br>"
            "<b>tiny</b> — hand-written from-scratch U-Net (thesis baseline)")
        self._lamella_arch_combo.currentTextChanged.connect(self._lamella_arch_changed)
        self._lamella_status_lbl = QLabel("No model loaded")
        self._lamella_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        lam_model_rl.addWidget(lam_model_lbl)
        lam_model_rl.addWidget(self._lamella_arch_combo)
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
        for axis, default in [("x", 0), ("y", 0), ("w", 256), ("h", 256)]:
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
        lam_batch_rl.addWidget(self._lamella_batch_btn)
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

    # ── Testers tab ───────────────────────────────────────────────────────────

    def _build_testers_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        w = QWidget()
        w.setMinimumWidth(0)
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 20, 20, 20)
        vl.setSpacing(14)

        # ── Ramp Speed Test ───────────────────────────────────────────────────
        c = card(w)
        c.layout().addWidget(section_label("RAMP SPEED TEST"))
        c.layout().addWidget(separator())

        desc = QLabel(
            "Increases motor speed by a fixed increment at regular intervals until the "
            "syringe limit (72.5 mm) is reached or STOP is pressed. "
            "Output is printed to the Console panel on the right."
        )
        desc.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        desc.setWordWrap(True)
        c.layout().addWidget(desc)

        self._ramp_start_speed_entry = QLineEdit()
        self._ramp_start_speed_entry.setPlaceholderText("e.g. 250")
        self._ramp_start_speed_entry.setValidator(QIntValidator(1, 100000))
        c.layout().addWidget(input_row("Start Speed (steps/s)", self._ramp_start_speed_entry))

        self._ramp_step_time_entry = QLineEdit()
        self._ramp_step_time_entry.setPlaceholderText("e.g. 5")
        self._ramp_step_time_entry.setValidator(QDoubleValidator(0.1, 3600.0, 1))
        c.layout().addWidget(input_row("Step Time (s)", self._ramp_step_time_entry))

        self._ramp_increment_entry = QLineEdit()
        self._ramp_increment_entry.setPlaceholderText("e.g. 25")
        self._ramp_increment_entry.setValidator(QIntValidator(1, 100000))
        c.layout().addWidget(input_row("Speed Increment (steps/s)", self._ramp_increment_entry))

        ramp_btn_row = QWidget()
        rbr = QHBoxLayout(ramp_btn_row); rbr.setContentsMargins(0, 0, 0, 0); rbr.setSpacing(8)
        self._ramp_start_btn = accent_button("Start Ramp", CLR_ACCENT)
        self._ramp_start_btn.setFixedHeight(36)
        self._ramp_stop_btn  = accent_button("STOP", CLR_RED)
        self._ramp_stop_btn.setFixedHeight(36)
        self._ramp_stop_btn.setEnabled(False)
        self._ramp_start_btn.clicked.connect(self._start_ramp_test)
        self._ramp_stop_btn.clicked.connect(self._stop_ramp_test)
        rbr.addWidget(self._ramp_start_btn)
        rbr.addWidget(self._ramp_stop_btn)
        rbr.addStretch()
        c.layout().addWidget(ramp_btn_row)

        vl.addWidget(c)
        vl.addStretch()

        scroll.setWidget(w)
        return scroll

    # ── How To tab ────────────────────────────────────────────────────────────

    def _build_how_to_tab(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent; border:none;")
        w = QWidget()
        vl = QVBoxLayout(w); vl.setContentsMargins(20,20,20,20); vl.setSpacing(14)

        sections = [
            ("GETTING STARTED", [
                ("1. Connect the Arduino",
                 "Go to the Hardware tab. Select the correct serial port from the dropdown and click Connect. "
                 "The status dot in the header turns green when connected. The Arduino controls the stepper "
                 "motor and reads pressure from the AliCat flow controller."),
                ("2. Home the motor",
                 "Before moving the nozzle, click Home. This zeroes the position counter. The Motor Travel "
                 "bar on the left updates in real-time. Never exceed the maximum travel shown — the motor "
                 f"hard limit is {AtomisationApp.MAX_MOTOR_MM} mm."),
                ("3. Set pressure",
                 "Enter a target pressure (0.0 – 26.4 BAR) and click Set Pressure. The current reading "
                 "updates live. Click Pressure Off to close the valve immediately."),
            ]),
            ("PHANTOM HIGH-SPEED CAMERA", [
                ("Connecting",
                 "Go to the Camera tab. Enter the camera IP (default 100.100.100.1) and click Connect. "
                 "Use Ping to verify network reachability without a full connection. The Phantom SDK is "
                 "Windows-only — a warning appears on other platforms."),
                ("Configuring",
                 "Set FPS, resolution (Width × Height), exposure time (µs), and recording duration (s). "
                 "Click Apply Config to push settings to the camera before capturing. Typical settings: "
                 "1000 fps, 640×480, 100 µs exposure."),
                ("Capturing",
                 "Click ● Capture to trigger a high-speed recording. The cine file is transferred and "
                 "converted to TIFF frames automatically. Tick Run analysis pipeline to detect droplets "
                 "and ligaments after capture — results are saved to Outputs/FINAL_OPTIMIZED_RESULT.png "
                 "and the Latest Result panel updates on completion."),
                ("Calibration",
                 "Go to the Calibration sub-panel to set the pixel-to-mm scale. Capture a live frame "
                 "with a known reference object in view, draw the reference line, and enter the real "
                 "distance. The scale factor is saved and used by the analysis pipeline."),
            ]),
            ("CONE ANGLE MEASUREMENT", [
                ("Overview",
                 "The Cone tab uses a standard USB webcam pointed at the spray to measure the full "
                 "spray cone angle in real time. The algorithm (Cone_4) fits sigmoid curves to each "
                 "row of the image to locate the left and right spray boundaries, then uses RANSAC "
                 "robust line fitting to compute the half-angles and report the full cone angle."),
                ("Setup",
                 "Connect the webcam, select its index (usually 0), and click Start Camera. The live "
                 "feed appears in the top panel. Adjust manual focus if your webcam supports it — "
                 "untick Auto-focus and set the focus value (0–250)."),
                ("Capturing",
                 "Click Capture & Analyse to grab a frame and run the cone detection. The annotated "
                 "result image (with fitted boundary lines overlaid) is shown immediately and saved "
                 "to cone_captures/ alongside the raw frame. The cone angle is displayed in large "
                 "text below the image."),
                ("Auto-capture",
                 "When the webcam is running and a full experiment is started (▶ START EXPERIMENT), "
                 "auto-capture activates automatically — taking a new measurement every 5 seconds "
                 "throughout the run. The status label shows 'Auto-capture: ON (every 5 s)'."),
                ("Debug output",
                 "Cone_4 also saves a 6-panel debug image alongside the annotated result showing: "
                 "the processed grayscale image, the sigmoid inflection-point map, accepted boundary "
                 "points coloured by R² quality, outermost-filtered boundary points, RANSAC inliers "
                 "(bright) vs outliers (dim), and the final annotated overlay."),
            ]),
            ("AFG1062 SIGNAL GENERATOR", [
                ("Connecting",
                 "Select CH1 or CH2 from the Channel dropdown and click Connect. The AFG generates "
                 "the electrical trigger pulse that fires the atomiser nozzle."),
                ("Firing",
                 "Set Pulse Duration (s) and click Apply Config. Use Test Fire to send a single "
                 "test pulse without running a full experiment."),
            ]),
            ("SAVING RESULTS", [
                ("Excel log",
                 "Fill in Nozzle No. and Orifice in the right panel, add any notes (fluid composition, "
                 "temperature, observations), then click Save to Excel. Results are written to a per-run "
                 "folder on the LaCie drive: Experiments/YYYY/MM/DD/HHMMSS_Nnozzle_pressureBAR/run_summary.xlsx."),
                ("Shadowgraph result",
                 "The Latest Result panel (left) shows the most recent FINAL_OPTIMIZED_RESULT.png found "
                 "in the current run's shadowgraph/analysis/ folder. Click ↻ Refresh to scan for a newer result after analysis."),
            ]),
            ("TIPS & ENVIRONMENT", [
                ("Dark/light background",
                 "The analysis pipeline saves both light- and dark-background versions of the result "
                 "image. Check the Outputs/ folder for LIGHT_BG and DARK_BG variants."),
                ("Running on macOS",
                 "The GUI runs on macOS for layout/design work. Phantom camera capture and Arduino serial "
                 "require Windows (or the correct driver). Connect warnings will appear for unavailable hardware."),
                ("Python environment",
                 "macOS: conda activate phantom → python src/gui/GUI_Clean.py\n"
                 "Windows: conda activate Detectron2 → python src/gui/GUI_Clean.py"),
                ("Cone detection dependency",
                 "Cone_4 requires scipy (pip install scipy). If 'Cone_4.py not found' appears, ensure "
                 "scipy is installed in the active conda environment and that Trials/Cone_4.py exists "
                 "in the repo."),
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

        self._start_btn = accent_button("▶  START EXPERIMENT", CLR_GREEN)
        self._start_btn.setFixedSize(200, 40)
        self._start_btn.setToolTip(
            "<b>Start experiment</b><br>"
            "1. Sets pressure to the target BAR<br>"
            "2. Waits for pressure to stabilise<br>"
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

    def _get_serial_ports(self):
        import re
        ports = serial.tools.list_ports.comports()
        result = []
        for p in ports:
            dev  = p.device
            desc = (p.description or "").strip()
            lower_desc = desc.lower()
            if dev.upper().startswith("COM") or "usb" in lower_desc or "serial" in lower_desc:
                if desc and desc != dev:
                    # Windows appends "(COMx)" to the description — strip it since we show the port separately
                    desc_clean = re.sub(r'\s*\(COM\d+\)\s*$', '', desc, flags=re.IGNORECASE).strip()
                    result.append(f"{dev} — {desc_clean}")
                else:
                    result.append(dev)
        return result

    def _refresh_ports(self):
        ports = self._get_serial_ports()
        self._port_combo.clear()
        self._port_combo.addItems(ports)
        if ports:
            self._set_status(f"Found {len(ports)} port(s)")

    def _refresh_rpm_ports(self):
        ports = self._get_serial_ports()
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
        self._set_status("RPM Arduino disconnected")

    def _toggle_spin(self):
        if not self.rpm_connected or not self.rpm_arduino:
            self._set_status("RPM Arduino not connected", CLR_ORANGE); return
        if self.rpm_spinning:
            try:
                self.rpm_arduino.send_stop()
            except Exception as e:
                self._set_status(f"RPM stop error: {e}", CLR_RED); return
            self.rpm_spinning = False
            self._rpm_spin_btn.setText("Spin")
            self._rpm_spin_btn.setStyleSheet(accent_button("Spin", CLR_RED).styleSheet())
            self._rpm_actual_lbl.setText("● 0 RPM")
            self._rpm_actual_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px; min-width:80px;")
            self._set_status("Motor stopped")
        else:
            try:
                rpm_text = self._rpm_entry.text().strip()
                rpm = float(rpm_text) if rpm_text else 100.0
                self.rpm_arduino.send_rpm(rpm)
            except Exception as e:
                self._set_status(f"RPM send error: {e}", CLR_RED); return
            self.rpm_spinning = True
            self._rpm_spin_btn.setText("Stop")
            self._rpm_spin_btn.setStyleSheet(accent_button("Stop", CLR_GREEN).styleSheet())
            self._set_status(f"Motor spinning at {rpm:.0f} RPM", CLR_GREEN)

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
                else:
                    time.sleep(0.02)
            except serial.SerialException:
                break
            except Exception:
                pass

    def _on_rpm_actual_reading(self, rpm: float):
        if rpm > 0.5:
            self._rpm_actual_lbl.setText(f"▶ {rpm:.0f} RPM")
            self._rpm_actual_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px; font-weight:600; min-width:80px;")
        else:
            self._rpm_actual_lbl.setText("● 0 RPM")
            self._rpm_actual_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px; min-width:80px;")

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
                        if line.startswith("PRESSURE_READING:"):
                            try:
                                val = float(line.split(":")[1])
                                QTimer.singleShot(0, self, lambda v=val: self._handle_pressure_reading(v))
                            except: pass
                        elif "MOVEMENT_COMPLETE" in line or "MOVEMENT_TIMEOUT" in line:
                            QTimer.singleShot(0, self, self._on_movement_complete)
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

    def _poll_serial(self):
        pass  # Serial reading handled by background thread above

    def _handle_pressure_reading(self, val):
        now = time.time()

        # ── EMA smoothing ─────────────────────────────────────────────────────
        # Initialise (or reinitialise after a gap) by seeding with the first value
        if self._pressure_ema is None:
            self._pressure_ema = val
        else:
            self._pressure_ema = self._EMA_ALPHA * val + (1.0 - self._EMA_ALPHA) * self._pressure_ema
        display_val = self._pressure_ema if self._pressure_smooth_enabled else val

        # ── Live buffer (graph) — stores display value ────────────────────────
        lb = self.pressure_data['live_buffer']
        lb['timestamps'].append(now - self.pressure_data['live_buffer_start_time'])
        lb['pressures'].append(display_val)
        # Keep 60s rolling window
        cutoff = lb['timestamps'][-1] - 60.0
        while lb['timestamps'] and lb['timestamps'][0] < cutoff:
            lb['timestamps'].pop(0); lb['pressures'].pop(0)

        # ── Experiment log — always stores raw values for accurate export ─────
        if self.pressure_data['experiment_active']:
            ed = self.pressure_data['experiment_data']
            ed['timestamps'].append(now - self.pressure_data['experiment_start_time'])
            ed['pressures'].append(val)

        # Update labels on main thread via timer (already running in thread)
        self._cur_pressure_lbl.setText(f"{display_val:.3f} BAR")
        self._hdr_pressure_lbl.setText(f"{display_val:.3f} BAR")
        self._hdr_pressure_dot.setStyleSheet(f"color:{CLR_ACCENT}; font-size:10px; background:transparent;")

    def _on_smooth_toggled(self, checked: bool):
        self._pressure_smooth_enabled = checked
        # Reset EMA state so switching modes doesn't leave a stale seed value
        self._pressure_ema = None

    @Slot()
    def _on_homed(self):
        self._homed_dot.setStyleSheet(f"color:{CLR_GREEN}; font-size:10px;")
        self._set_status("Homed", CLR_GREEN)

    @Slot()
    def _on_movement_complete(self):
        self._experiment_watchdog.stop()
        self.cumulative_distance = self._pre_move_cumulative + self._pending_move_distance
        self._pending_move_distance = 0.0
        self._update_travel_bar()
        self._movement_done_event.set()
        if self.pressure_data['experiment_active']:
            self.pressure_data['experiment_active'] = False
            self._cone_auto_timer.stop()
            self._cone_auto_status_lbl.setText("Auto-capture: inactive")
            self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
            self.arduino.send_pressure_off_command()
            self._last_experiment_snapshot = {
                'timestamps':     list(self.pressure_data['experiment_data']['timestamps']),
                'pressures':      list(self.pressure_data['experiment_data']['pressures']),
                'camera_windows': list(self.pressure_data.get('camera_windows', [])),
            }
            self._experiment_saved = False
            self._exp_progress.setRange(0, 100)
            self._exp_progress.setValue(100)
            QTimer.singleShot(800, lambda: (
                self._exp_progress.setVisible(False),
                self._exp_progress.setRange(0, 0),
            ))
            self._start_btn.setEnabled(True)
            self._stop_run_timer()
            self._set_status("Experiment complete ✓ — remember to Save to Excel", CLR_GREEN)
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

    def _update_next_save_preview(self):
        now = datetime.now()
        nozzle_raw = self._nozzle_entry.text().strip() if hasattr(self, "_nozzle_entry") else ""
        nozzle_label = (nozzle_raw or "NoNozzle").replace(" ", "_")
        pressure_raw = self._pressure_entry.text().strip() if hasattr(self, "_pressure_entry") else ""
        try:
            pressure_val = float(pressure_raw)
            pressure_str = f"{pressure_val:.1f}BAR"
        except ValueError:
            pressure_str = "?.?BAR"
        run_id = f"{now.strftime('%H%M%S')}_N{nozzle_label}_{pressure_str}"
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
        """Watchdog fired — serial reader likely died. Kill pressure and recover UI."""
        if self.pressure_data['experiment_active']:
            self.pressure_data['experiment_active'] = False
            self._cone_auto_timer.stop()
            self.arduino.send_pressure_off_command()
            self._exp_progress.setVisible(False)
            self._exp_progress.setRange(0, 0)
            self._start_btn.setEnabled(True)
            self._stop_run_timer()
            self._set_status("Experiment timed out — pressure turned off", CLR_RED)

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Pressure / Motor
    # ─────────────────────────────────────────────────────────────────────────

    def _set_pressure(self):
        if not self._require_arduino(): return
        try:
            val = float(self._pressure_entry.text())
            if not 0 <= val <= 26.4:
                raise ValueError("out of range")
            self.arduino.send_pressure_command(val)
            self._set_status(f"Pressure set to {val:.1f} BAR")
            self._last_pressure = val
            self._last_pressure_btn.setText(f"Set last: {val:.2f} BAR")
            self._last_pressure_btn.setEnabled(True)
            self._save_camera_settings()
        except ValueError:
            self._set_status("Invalid pressure value", CLR_ORANGE)
            self._warn("Invalid Pressure",
                       "Please enter a pressure between 0.0 and 26.4 BAR.")

    def _set_last_pressure(self):
        if self._last_pressure is None:
            return
        self._pressure_entry.setText(f"{self._last_pressure:.2f}")
        self._set_pressure()

    def _pressure_off_only(self):
        if not self._require_arduino(): return
        self.arduino.send_pressure_off_command()
        self._set_status("Pressure off")

    def _pressure_off(self):
        if not self._require_arduino(): return
        self.arduino.send_pressure_off_command()
        try: self.arduino.send_stop()
        except Exception: pass
        if self._ramp_running:
            self._stop_ramp_test()
        self._set_status("Motor and pressure off")

    def _home_motor(self):
        if not self._require_arduino(): return
        self.arduino.ser.write(b"HOME:1\n")
        log_serial("Sent: HOME:1")
        self.cumulative_distance      = 0.0
        self._pre_move_cumulative     = 0.0
        self._pending_move_distance   = 0.0
        self._update_travel_bar()
        self._set_status("Homing…")

    def _start_cleaning(self):
        if not self._require_arduino(): return
        self.cleaning_in_progress = not self.cleaning_in_progress
        if self.cleaning_in_progress:
            self._clean_btn.setText("⏹  Stop Clean")
            self.arduino.send_motor_command(200, 10)
            self._set_status("Cleaning in progress")
        else:
            self._clean_btn.setText("🧼  Clean")
            self._set_status("Cleaning stopped")

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
        self._move_btn.setEnabled(False)
        self._home_btn.setEnabled(False)
        self._clean_btn.setEnabled(False)
        cmd = f"JOG:{speed};DIR:{direction}\n"
        self.arduino.ser.write(cmd.encode())
        log_serial(f"Sent: {cmd.strip()}")
        label = "forward" if direction > 0 else "backward"
        self._set_status(f"Jogging {label} at {speed} steps/s — release to stop")

    def _jog_stop(self):
        if not self._jogging: return
        if not self.arduino or not self.arduino.ser: return
        self.arduino.ser.write(b"STOP\n")
        log_serial("Sent: STOP")

    @Slot()
    def _on_jog_complete(self):
        self._jogging = False
        self._move_btn.setEnabled(True)
        self._home_btn.setEnabled(True)
        self._clean_btn.setEnabled(True)
        self._set_status("Jog stopped")

    def _on_jog_pos(self, steps: int):
        mm = max(0.0, min(self.MAX_MOTOR_MM, steps / 6800.0))
        self.cumulative_distance = mm
        self._update_travel_bar()

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

    @Slot()
    def _update_pressure_graph(self):
        lb = self.pressure_data['live_buffer']
        if not lb['timestamps']:
            return
        ts = lb['timestamps']; ps = lb['pressures']
        self._pressure_curve.setData(ts, ps)
        t_max = max(ts[-1], 10.0)
        self._graph_widget.setXRange(max(0, t_max - 30), t_max, padding=0.02)
        self._graph_widget.setYRange(0, max(max(ps) * 1.2, 5), padding=0.05)

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

    def _cam_connect(self):
        if not self.phantom:
            self._cam_status_lbl.setText("Camera SDK unavailable"); return
        try:
            self.phantom.connect()
            self._cam_status_lbl.setText("Camera: connected")
            self._cam_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;")
            self._hdr_camera_dot.setStyleSheet(f"color:{CLR_GREEN}; font-size:10px; background:transparent;")
            self._hdr_camera_lbl.setStyleSheet(f"color:{CLR_TEXT}; font-size:12px;")
        except Exception as e:
            self._cam_status_lbl.setText(f"Camera error: {e}")
            self._set_status(f"Camera: {e}", CLR_RED)

    def _cam_ping(self):
        if not self.phantom: return
        ok = self.phantom.ping()
        self._cam_status_lbl.setText("Camera: connected ✓" if ok else "Camera: not responding")

    def _cam_configure(self):
        if not self.phantom: return
        try:
            fps       = float(self._cam_fps.text())
            pre_s     = float(self._cam_pre_s.text())
            post_s    = float(self._cam_post_s.text())
            pre_frames  = max(1, int(pre_s  * fps))
            post_frames = max(1, int(post_s * fps))
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
        def _do_arm():
            try:
                self.phantom.start_recording()
                QTimer.singleShot(0, self, lambda: (
                    self._cam_status_lbl.setText("Armed — buffering…"),
                    self._cam_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;"),
                    self._cam_arm_status_lbl.setText("Armed — buffering…"),
                    self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;"),
                    self._cam_arm_btn.setEnabled(False),
                    self._cam_trigger_btn.setEnabled(True),
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
        if self.phantom: self.phantom.abort()
        self._cam_status_lbl.setText("Camera: disarmed")
        self._cam_arm_status_lbl.setText("Not armed")
        self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._cam_arm_btn.setEnabled(True)
        self._cam_trigger_btn.setEnabled(False)
        self._set_camera_armed_indicator("transparent")

    def _cam_trigger(self):
        """Fire the trigger — freeze the ring buffer and save pre+post window."""
        if not self.phantom: return
        run_pipeline  = self._pipeline_check.isChecked()
        save_video    = self._cam_save_video_chk.isChecked()
        pre_frames    = self._cam_pre_frames
        post_frames   = self._cam_post_frames
        run_folder    = self._run_folder
        ts = datetime.now().strftime("%H%M%S")

        # Update UI immediately so the user knows the trigger was received
        self._cam_trigger_btn.setEnabled(False)
        self._cam_arm_btn.setEnabled(False)
        self._cam_arm_status_lbl.setText("Triggered — saving…")
        self._cam_arm_status_lbl.setStyleSheet(f"color:{CLR_ORANGE}; font-size:12px;")
        self._set_camera_armed_indicator(CLR_GREEN)

        if run_folder:
            # Mid-experiment: write into the active run folder
            cine_path    = os.path.join(run_folder, "shadowgraph", "raw", "CINE",
                                        f"recording_{ts}.cine")
            tiff_prefix  = os.path.join(run_folder, "shadowgraph", "raw", "TIFFs", "frame")
            tiff_dir     = os.path.join(run_folder, "shadowgraph", "raw", "TIFFs")
            bright_dir   = os.path.join(run_folder, "shadowgraph", "raw", "Brightest_Frame")
            analysis_dir = os.path.join(run_folder, "shadowgraph", "analysis")
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
            for _sub in [os.path.join("shadowgraph", "raw", "CINE"),
                         os.path.join("shadowgraph", "raw", "TIFFs"),
                         os.path.join("shadowgraph", "raw", "Brightest_Frame"),
                         os.path.join("shadowgraph", "analysis"),
                         "cone"]:
                os.makedirs(os.path.join(_run_folder, _sub), exist_ok=True)
            cine_path    = os.path.join(_run_folder, "shadowgraph", "raw", "CINE",
                                        f"recording_{ts}.cine")
            tiff_prefix  = os.path.join(_run_folder, "shadowgraph", "raw", "TIFFs", "frame")
            tiff_dir     = os.path.join(_run_folder, "shadowgraph", "raw", "TIFFs")
            bright_dir   = os.path.join(_run_folder, "shadowgraph", "raw", "Brightest_Frame")
            analysis_dir = os.path.join(_run_folder, "shadowgraph", "analysis")
            # Update the save path label to show where this capture went
            QTimer.singleShot(0, self,
                lambda p=_run_folder: self._cam_save_lbl.setText(f"Saving to: {p}"))

        frame_range = (-pre_frames, post_frames - 1) if pre_frames > 0 else None

        def _brightest_frame(folder):
            import glob, cv2 as _cv2
            tiffs = glob.glob(os.path.join(folder, "*.tif")) + \
                    glob.glob(os.path.join(folder, "*.tiff"))
            if not tiffs:
                return None
            best, best_val = None, -1
            for f in tiffs:
                img = _cv2.imread(f, _cv2.IMREAD_UNCHANGED)
                if img is not None:
                    val = float(img.mean())
                    if val > best_val:
                        best_val, best = val, f
            return best

        def _do_trigger():
            import shutil, glob as _glob
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
                # Fixed settle: post-trigger frames + 2 s for the camera to commit the cine.
                # wait_for_cine() polling was replaced because cam.Cine() can block at the
                # SDK level without raising, leaving the thread stuck indefinitely.
                settle = post_frames / fps_val + 2.0
                QTimer.singleShot(0, self,
                    lambda s=settle: self._cam_arm_status_lbl.setText(f"Settling {s:.1f} s…"))
                time.sleep(settle)

                def _update_progress(pct):
                    QTimer.singleShot(0, self, lambda p=pct: self._cam_save_progress.setValue(p))

                # 1 — save .cine (optional)
                if save_video:
                    QTimer.singleShot(0, self, lambda: (
                        self._cam_arm_status_lbl.setText("Saving .cine…"),
                        self._cam_save_progress.setValue(0),
                        self._cam_save_progress.setVisible(True),
                    ))
                    self.phantom.save_recording(cine_path, file_format='cine',
                                                frame_range=frame_range,
                                                progress_cb=_update_progress)
                    QTimer.singleShot(0, self, lambda: self._cam_save_progress.setValue(0))

                # 2 — read frames from camera RAM and write TIFFs ourselves.
                # This bypasses the SDK's save() which has a known bug that throws
                # an exception even when the save succeeds.
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
                self.phantom.save_tiffs_from_ram(tiff_dir, tiff_prefix='frame',
                                                 frame_range=frame_range,
                                                 progress_cb=_update_progress)
                QTimer.singleShot(0, self, lambda: self._cam_save_progress.setVisible(False))

                # 3 — find brightest frame, copy to Brightest_Frame/
                os.makedirs(bright_dir, exist_ok=True)
                best = _brightest_frame(tiff_dir)
                bright_path = None
                if best:
                    bright_path = os.path.join(bright_dir, os.path.basename(best))
                    shutil.copy2(best, bright_path)

                QTimer.singleShot(0, self,
                    lambda: self._cam_status_lbl.setText("Trigger saved ✓"))

                # 4 — kick off AI in its own thread as soon as brightest frame is known
                if run_pipeline and bright_path:
                    QTimer.singleShot(0, self,
                        lambda: self._run_pipeline(bright_dir, analysis_dir))
                elif run_pipeline:
                    QTimer.singleShot(0, self,
                        lambda: self._set_status("No frames found for pipeline", CLR_ORANGE))

                # 5 — re-arm automatically so the camera is ready for the next trigger
                QTimer.singleShot(0, self, self._cam_arm)

            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, self, lambda: (
                    self._set_status(f"Trigger error: {err}", CLR_RED),
                    self._cam_arm_status_lbl.setText("Error — re-arm manually"),
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

    def _run_pipeline(self, frames_folder: str, output_folder: str, px_per_mm: float = None):
        """Run Dennis AI pipeline in a background thread so the UI stays responsive."""
        if px_per_mm is None:
            px_per_mm = self._get_px_per_mm()
        self._pipeline_status.setText("Pipeline: running…")
        self._ai_confidence_lbl.setText("Confidence: –")
        self._ai_diameter_lbl.setText("Avg droplet: –")
        self._ai_dl_lbl.setText("D/L: –")
        self._log(f"── AI pipeline started ({os.path.basename(frames_folder)}) ──")

        def _worker():
            _stream = _GuiLogStream(self._log_queue)
            self._tl_stdout.set(_stream)
            self._tl_stderr.set(_stream)
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from ai.process_run import run as ai_run
                results = ai_run(frames_folder, output_folder, px_per_mm)
                self._pipeline_done.emit(results)
            except Exception as e:
                self._pipeline_err.emit(str(e))
            finally:
                self._tl_stdout.clear()
                self._tl_stderr.clear()
        threading.Thread(target=_worker, daemon=True).start()

    def _on_pipeline_complete(self, results: dict):
        self._pipeline_status.setText("Pipeline: complete ✓")
        self._log("── AI pipeline complete ✓ ──")
        self._flash_log_border(CLR_GREEN)
        conf = results.get("mean_confidence")
        diam = results.get("avg_droplet_um")
        dl   = results.get("dl_ratio", "–")
        self._ai_confidence_lbl.setText(f"Confidence: {conf:.1f}%" if conf is not None else "Confidence: –")
        self._ai_diameter_lbl.setText(f"Avg droplet: {diam:.1f} µm" if diam is not None else "Avg droplet: –")
        self._ai_dl_lbl.setText(f"D/L: {dl}")
        # Re-enable test button if this was a test run
        if getattr(self, '_is_test_pipeline', False):
            self._test_pipeline_btn.setEnabled(True)
            self._test_pipeline_btn.setText("Test Pipeline")
            self._is_test_pipeline = False
        # Use the result image path directly from results
        result_image = results.get("result_image")
        if result_image:
            path = str(result_image)
            img = QImage(path)
            if not img.isNull():
                pix = QPixmap.fromImage(img).scaled(
                    390, 265,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self._shadow_label.setPixmap(pix)
                self._shadow_label.setText("")
                self._result_path_label.setText(path)
                return
        self._refresh_shadowgraph()

    def _on_pipeline_error(self, err: str):
        self._pipeline_status.setText(f"Pipeline error: {err}")
        self._log(f"── AI pipeline error: {err} ──")
        self._flash_log_border("#ff3b30")
        if getattr(self, '_is_test_pipeline', False):
            self._test_pipeline_btn.setEnabled(True)
            self._test_pipeline_btn.setText("Test Pipeline")
            self._is_test_pipeline = False

    def _run_test_pipeline(self):
        """Test button: run Dennis on test paths, preferring LaCie drive."""
        _base = find_lacie_drive() or "/Volumes/Backup_PhD"
        frames_folder = os.path.join(_base, "Phantom", "frames")
        output_folder = os.path.join(_base, "Experiments", "Trials")
        px_per_mm = self._get_px_per_mm() or 52.3
        self._test_pipeline_btn.setEnabled(False)
        self._test_pipeline_btn.setText("Running…")
        self._is_test_pipeline = True  # flag so _on_pipeline_complete re-enables btn
        self._run_pipeline(frames_folder, output_folder, px_per_mm)

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Calibration
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _phantom_frame_to_pixmap(frame) -> 'QPixmap':
        """Convert a pyphantom numpy frame (any bit depth) to a display QPixmap."""
        import numpy as np
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
        self._lamella_toggle_btn.setEnabled(True)

    def _cal_stop_feed(self):
        self._live_feed_timer.stop()
        self._live_feed_pending = False
        self._cal_feed_start_btn.setEnabled(True)
        self._cal_feed_stop_btn.setEnabled(False)
        self._cal_feed_label.setText("Live feed not active")
        # Reset lamella state when feed stops
        if self._lamella_on:
            self._lamella_toggle_btn.setChecked(False)
        self._lamella_toggle_btn.setEnabled(False)
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

    def _lamella_load_segmenter(self):
        """Instantiate the selected segmenter (stub, smp, or tiny)."""
        arch = self._lamella_arch_combo.currentText()
        model_path = getattr(self, "_lamella_model_path", "")
        try:
            if arch == "stub" or not model_path:
                from src.ai.lamella.infer import StubSegmenter
                self._lamella_seg = StubSegmenter()
                self._lamella_status_lbl.setText("Stub segmenter active")
            else:
                import torch
                from src.ai.lamella.infer import LamellaSegmenter
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._lamella_seg = LamellaSegmenter.load(model_path, arch=arch, device=device)
                self._lamella_status_lbl.setText(f"{arch} model loaded ({device})")
        except Exception as e:
            self._lamella_seg = None
            self._lamella_status_lbl.setText(f"Load error: {e}")
            self._lamella_toggle_btn.setChecked(False)

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

        from src.ai.lamella.crop import OutletCrop
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

        from src.ai.lamella.crop import OutletCrop
        from src.ai.lamella.batch_tiff import run_batch

        crop_box  = OutletCrop.from_dict(self._lamella_crop_cfg)
        px_per_mm = self._get_px_per_mm()
        seg       = self._lamella_seg

        self._lamella_batch_btn.setEnabled(False)
        self._lamella_batch_progress.setValue(0)
        self._lamella_batch_progress.setVisible(True)

        def _update_progress(pct):
            QTimer.singleShot(0, self, lambda p=pct: self._lamella_batch_progress.setValue(p))

        def _run():
            try:
                out_csv = run_batch(
                    tiff_dir=tiff_dir,
                    segmenter=seg,
                    crop_box=crop_box,
                    px_per_mm=px_per_mm,
                    progress_cb=_update_progress,
                )
                QTimer.singleShot(0, self, lambda: self._lamella_batch_done(out_csv))
            except Exception as e:
                QTimer.singleShot(0, self, lambda: self._lamella_batch_error(str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _lamella_batch_done(self, out_csv: str):
        self._lamella_batch_btn.setEnabled(True)
        self._lamella_batch_progress.setVisible(False)
        self._set_status(f"Lamella batch complete — {out_csv}", CLR_GREEN)

    def _lamella_batch_error(self, err: str):
        self._lamella_batch_btn.setEnabled(True)
        self._lamella_batch_progress.setVisible(False)
        self._warn("Lamella Batch Error", err)

    # ─────────────────────────────────────────────────────────────────────────

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
        """Main-thread callback — paint the latest frame into the feed label."""
        display = frame
        if self._lamella_on and self._lamella_result is not None:
            from src.ai.lamella.overlay import draw_overlay
            display = draw_overlay(frame, self._lamella_result)
        pix = self._phantom_frame_to_pixmap(display)
        pix = pix.scaled(
            self._cal_feed_label.width(), self._cal_feed_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._cal_feed_label.setPixmap(pix)

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
            import io as _io

            class _TeeStream:
                def __init__(self, gui_stream, buf):
                    self._g, self._b = gui_stream, buf
                def write(self, text):
                    self._g.write(text); self._b.write(text)
                def flush(self):
                    self._g.flush()
                def isatty(self): return False
                def fileno(self): raise _io.UnsupportedOperation("fileno")

            _buf    = _io.StringIO()
            _stream = _GuiLogStream(self._log_queue)
            _tee    = _TeeStream(_stream, _buf)
            self._tl_stdout.set(_tee)
            self._tl_stderr.set(_tee)
            try:
                from pathlib import Path as _Path
                angle, annotated_bgr, _debug = detect_cone_angle(
                    _Path(raw_path), top_crop_ratio=top_crop)
            except Exception as e:
                def _on_err():
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

    def _start_experiment(self):
        if not self._require_arduino(): return

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
            pressure = float(self._pressure_entry.text())
            speed    = int(self._speed_entry.text())
            distance = float(self._distance_entry.text())
        except ValueError:
            self._set_status("Fill in pressure, speed, and distance first", CLR_ORANGE)
            self._warn("Missing Parameters",
                       "Please fill in all three fields before starting:\n"
                       "  • Target Pressure (BAR)\n"
                       "  • Motor Speed (steps/s)\n"
                       "  • Motor Distance (mm)")
            return
        if self.cumulative_distance + distance > self.MAX_MOTOR_MM:
            remaining = self.MAX_MOTOR_MM - self.cumulative_distance
            self._set_status("Travel limit would be exceeded!", CLR_RED)
            self._warn("Travel Limit",
                       f"This experiment would exceed the motor's travel limit of {self.MAX_MOTOR_MM} mm.\n\n"
                       f"Only {remaining:.1f} mm of travel remains.\n"
                       "Home the motor to reset.")
            return

        self.pressure_data['experiment_active'] = True
        self.pressure_data['experiment_start_time'] = time.time()
        self.pressure_data['experiment_data'] = {'timestamps':[], 'pressures':[]}
        self.pressure_data['camera_windows'] = []
        self._last_cone_path = None   # reset so we only capture this experiment's image

        # ── Create run folder eagerly ──────────────────────────────────────────
        _now = datetime.now()
        _nozzle_label = (self._nozzle_entry.text().strip() or "NoNozzle").replace(" ", "_")
        _run_id = f"{_now.strftime('%H%M%S')}_N{_nozzle_label}_{pressure:.1f}BAR"
        _lacie = find_lacie_drive()
        _exp_base = os.path.join(_lacie, "Experiments") if _lacie else os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "experiment_logs", "Experiments")
        self._run_folder = os.path.join(
            _exp_base, _now.strftime("%Y"), _now.strftime("%m"), _now.strftime("%d"), _run_id)
        for _sub in [os.path.join("shadowgraph", "raw", "CINE"),
                     os.path.join("shadowgraph", "raw", "TIFFs"),
                     os.path.join("shadowgraph", "raw", "Brightest_Frame"),
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
        self.pressure_data['live_buffer'] = {'timestamps': [], 'pressures': []}
        self.pressure_data['live_buffer_start_time'] = time.time()
        self._pressure_ema = None   # seed EMA fresh from the first reading of the run

        self._start_btn.setEnabled(False)
        self._exp_progress.setRange(0, 100)
        self._exp_progress.setValue(0)
        self._exp_progress.setVisible(True)
        self._set_status("Experiment running…", CLR_ACCENT)
        self._run_start_time = time.time()
        self._run_elapsed_timer.start()

        self.arduino.send_pressure_command(pressure)
        # Send motor command 500 ms later without blocking the UI
        QTimer.singleShot(500, lambda: self.arduino.send_motor_command(speed, distance))
        self._pre_move_cumulative   = self.cumulative_distance
        self._pending_move_distance = distance
        # cumulative_distance is finalised in _on_movement_complete so the travel bar fills live

        # Start watchdog: if serial reader dies, pressure would stay on forever without this
        _steps_per_mm = 6800
        _move_time_ms = int((distance * _steps_per_mm / speed + 30) * 1000)
        self._experiment_watchdog.start(_move_time_ms)

        # Camera is managed independently — arm/trigger from the Camera tab

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Shadowgraph preview
    # ─────────────────────────────────────────────────────────────────────────

    def _find_latest_result(self):
        try:
            # Check the active run folder first — prefer ai_result.png, fall back to CV result
            if self._run_folder:
                for fname in ("ai_result.png", "FINAL_OPTIMIZED_RESULT.png"):
                    f = os.path.join(self._run_folder, "shadowgraph", "analysis", fname)
                    if os.path.exists(f):
                        return f

            # Fall back to scanning Experiments tree for most-recent result
            lacie = find_lacie_drive()
            base  = os.path.join(lacie, "Experiments") if lacie else None
            if not base or not os.path.exists(base): return None

            def latest_subdir(path):
                items = [(os.path.join(path, i), os.path.getmtime(os.path.join(path, i)))
                         for i in os.listdir(path) if os.path.isdir(os.path.join(path, i))]
                items.sort(key=lambda x: x[1], reverse=True)
                return [x[0] for x in items]

            for year in latest_subdir(base):
                for month in latest_subdir(year):
                    for day in latest_subdir(month):
                        for run in latest_subdir(day):
                            for fname in ("ai_result.png", "FINAL_OPTIMIZED_RESULT.png"):
                                f = os.path.join(run, "shadowgraph", "analysis", fname)
                                if os.path.exists(f): return f
        except Exception as e:
            print(f"Error finding result: {e}")
        return None

    def _refresh_shadowgraph(self):
        # Run the drive scan in a background thread so the main thread stays responsive.
        def _scan():
            path = self._find_latest_result()
            QTimer.singleShot(0, self, lambda: self._apply_shadowgraph_result(path))
        threading.Thread(target=_scan, daemon=True).start()

    def _apply_shadowgraph_result(self, path):
        if path and os.path.exists(path):
            img = QImage(path)
            if not img.isNull():
                pix = QPixmap.fromImage(img).scaled(
                    390, 265,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self._shadow_label.setPixmap(pix)
                self._shadow_label.setText("")
                self._result_path_label.setText(path)
                return
        self._shadow_label.setPixmap(QPixmap())
        self._shadow_label.setText("No result found\nClick ↻ Refresh")
        self._result_path_label.setText("Searching: LaCie/Experiments/…/shadowgraph/analysis/ai_result.png")

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Excel save
    # ─────────────────────────────────────────────────────────────────────────

    def _save_to_excel(self):
        if not self._nozzle_entry.text().strip():
            self._warn("Missing Nozzle Number",
                       "Please enter a Nozzle No. in the right-hand panel before saving.")
            return
        try:
            from openpyxl import load_workbook, Workbook
            from openpyxl.drawing.image import Image as XLImage
            from openpyxl.styles import Alignment

            lacie        = find_lacie_drive()
            now          = datetime.now()
            ts_str       = now.strftime("%Y-%m-%d %H:%M:%S")

            nozzle       = self._nozzle_entry.text().strip()
            orifice      = self._orifice_combo.currentText()
            notes        = self._notes_text.toPlainText()
            speed_str    = self._speed_entry.text()
            distance_str = self._distance_entry.text()

            # Use the frozen snapshot taken at experiment end — not the live buffer
            snap = self._last_experiment_snapshot
            camera_windows = snap.get('camera_windows', [])
            pressures = snap['pressures']
            if pressures:
                p_min, p_max = min(pressures), max(pressures)
                p_range_str  = f"{p_min:.1f}–{p_max:.1f} BAR"
                p_range_file = f"{p_min:.1f}-{p_max:.1f}BAR"
            else:
                raw = self._pressure_entry.text()
                p_range_str  = f"{raw} BAR" if raw else "N/A"
                p_range_file = None

            # ── Resolve run folder (created at Start Experiment, or now as fallback) ──
            if self._run_folder:
                run_dir = self._run_folder
            else:
                _exp_base = os.path.join(lacie, "Experiments") if lacie else os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "experiment_logs", "Experiments")
                _safe_nozzle = f"N{nozzle}".replace(" ", "_")
                _run_id = f"{now.strftime('%H%M%S')}_{_safe_nozzle}_{p_range_file or 'unknownBAR'}"
                run_dir = os.path.join(_exp_base, now.strftime("%Y"), now.strftime("%m"),
                                       now.strftime("%d"), _run_id)
                for _sub in [os.path.join("shadowgraph", "raw"),
                             os.path.join("shadowgraph", "analysis"), "cone"]:
                    os.makedirs(os.path.join(run_dir, _sub), exist_ok=True)
                self._run_folder = run_dir
            ind_path = os.path.join(run_dir, "run_summary.xlsx")

            # ── Build Pressure DataFrame with camera window annotations ──────────
            # cam_start_N / cam_end_N values appear only on the row whose timestamp
            # is closest to the camera window boundary; all other rows are blank.
            press_df = None
            if snap['timestamps']:
                press_df = pd.DataFrame({'timestamps': snap['timestamps'],
                                         'pressures':  snap['pressures']})
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

            # ── Render pressure chart (shared between run_summary and master_log) ─
            # DPI = DISPLAY_H / fig_h → PNG always renders at exactly DISPLAY_H px tall.
            DISPLAY_H          = 165
            MIN_W_PX           = 347
            PX_PER_SEC         = MIN_W_PX / 10.0
            FIG_H_IN           = 2.0
            DPI                = DISPLAY_H / FIG_H_IN
            pressure_buf       = None
            pressure_img_width = MIN_W_PX
            if pressures:
                t0         = snap['timestamps'][0]
                rel_ts     = [t - t0 for t in snap['timestamps']]
                duration_s = rel_ts[-1] if rel_ts else 0.0
                target_w_px = max(MIN_W_PX, int(duration_s * PX_PER_SEC))
                fig_w = target_w_px / DPI
                fig, ax = plt.subplots(figsize=(fig_w, FIG_H_IN))
                fig.patch.set_facecolor('white')
                ax.set_facecolor('#f5f5f7')
                ax.plot(rel_ts, pressures, color='#0a84ff', linewidth=2.5, solid_capstyle='round')
                ax.fill_between(rel_ts, pressures, alpha=0.12, color='#0a84ff')
                for _cw_s, _cw_e in camera_windows:
                    ax.axvspan(_cw_s - t0, _cw_e - t0, alpha=0.2, color='red', zorder=0)
                ax.set_xlabel('Time (s)', fontsize=8, color='#3a3a3c')
                ax.set_ylabel('Pressure (BAR)', fontsize=8, color='#3a3a3c')
                ax.set_title(f'N{nozzle}  {orifice}  {p_range_str}',
                             fontsize=8, color='#1c1c1e', pad=4, loc='left')
                ax.tick_params(colors='#6e6e73', labelsize=7)
                ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
                ax.spines['left'].set_color('#d1d1d6'); ax.spines['bottom'].set_color('#d1d1d6')
                ax.grid(True, alpha=0.4, color='#d1d1d6', linewidth=0.6)
                ax.set_ylim(bottom=0)
                fig.tight_layout(pad=0.6)
                pressure_buf = io.BytesIO()
                fig.savefig(pressure_buf, format='png', dpi=DPI,
                            bbox_inches='tight', facecolor='white')
                plt.close(fig)
                import struct as _struct
                pressure_buf.seek(16)
                actual_w = _struct.unpack('>I', pressure_buf.read(4))[0]
                actual_h = _struct.unpack('>I', pressure_buf.read(4))[0]
                pressure_img_width = max(MIN_W_PX, int(actual_w * DISPLAY_H / actual_h))
                pressure_buf.seek(0)
            # Extract bytes now so PIL closing the BytesIO inside XLImage doesn't break
            # the second use of the same buffer for the master log
            pressure_bytes = pressure_buf.getvalue() if pressure_buf else None

            meta = {
                'Field': ['Timestamp', 'Nozzle', 'Orifice', 'Pressure Range',
                          'Speed (steps/s)', 'Distance (mm)', 'Notes'],
                'Value': [ts_str, nozzle, orifice, p_range_str,
                          speed_str, distance_str, notes],
            }
            with pd.ExcelWriter(ind_path, engine='openpyxl') as writer:
                pd.DataFrame(meta).to_excel(writer, sheet_name='Metadata', index=False)
                if press_df is not None:
                    press_df.to_excel(writer, sheet_name='Pressure', index=False)
                    if pressure_bytes:
                        _rs_img = XLImage(io.BytesIO(pressure_bytes))
                        _rs_img.width  = pressure_img_width
                        _rs_img.height = DISPLAY_H
                        writer.sheets['Pressure'].add_image(
                            _rs_img, f'A{len(press_df) + 3}')

            # ── Master log: insert at row 2, shift image anchors first ───────
            import re as _re
            _master_base = os.path.join(lacie, "Experiments", "Logs") if lacie else os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "experiment_logs")
            os.makedirs(_master_base, exist_ok=True)
            master_path = os.path.join(_master_base, 'master_log.xlsx')
            if os.path.exists(master_path):
                wb = load_workbook(master_path)
                ws = wb.active
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
                ws.append(['Timestamp', 'Nozzle', 'Orifice', 'Pressure Range',
                           'Speed (steps/s)', 'Distance (mm)', 'Notes',
                           'Cone Image', 'Shadowgraph', 'Pressure Graph'])
                for col, width in zip('ABCDEFGHIJ', [20, 8, 8, 18, 14, 12, 35, 36.5, 36.5, 56]):
                    ws.column_dimensions[col].width = width

            ws.insert_rows(2)
            row_num = 2
            center_mid = Alignment(horizontal='center', vertical='center', wrap_text=True)
            top_left   = Alignment(horizontal='left',   vertical='top',    wrap_text=True)
            for col, val in enumerate([ts_str, nozzle, orifice, p_range_str,
                                       speed_str, distance_str, notes, '', '', ''], start=1):
                cell = ws.cell(row=row_num, column=col)
                cell.value = val
                cell.alignment = top_left if col == 7 else center_mid
            ws.row_dimensions[row_num].height = 125

            _cone_img_path = self._last_cone_path or ""
            if _cone_img_path and os.path.exists(_cone_img_path):
                _cone_raw = cv2.imread(_cone_img_path)
                if _cone_raw is not None:
                    _ch, _cw = _cone_raw.shape[:2]
                    # Scale to match the row height (DISPLAY_H px) preserving aspect ratio
                    _cone_disp_h = DISPLAY_H
                    _cone_disp_w = max(1, int(_cw * _cone_disp_h / _ch))
                    cimg = XLImage(_cone_img_path)
                    cimg.width = _cone_disp_w; cimg.height = _cone_disp_h
                    ws.column_dimensions['H'].width = max(10, _cone_disp_w / 7.0)
                    ws.add_image(cimg, f'H{row_num}')
                else:
                    ws.cell(row=row_num, column=8).value = 'NO DATA AVAILABLE'
            else:
                ws.cell(row=row_num, column=8).value = 'NO DATA AVAILABLE'

            shadow_src = self._result_path_label.text()
            if shadow_src and os.path.exists(shadow_src):
                simg = XLImage(shadow_src); simg.width = 300; simg.height = 165
                ws.add_image(simg, f'I{row_num}')
            else:
                ws.cell(row=row_num, column=9).value = 'NO DATA AVAILABLE'

            if pressure_bytes:
                pimg = XLImage(io.BytesIO(pressure_bytes))
                pimg.width = pressure_img_width; pimg.height = DISPLAY_H
                # Widen column J to fit this image (56 chars ≈ 347 px baseline)
                ws.column_dimensions['J'].width = max(56, pressure_img_width * 56 / 347)
                ws.add_image(pimg, f'J{row_num}')
            else:
                ws.cell(row=row_num, column=10).value = 'NO DATA AVAILABLE'

            wb.save(master_path)

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
        except Exception as e:
            self._set_status(f"Save error: {e}", CLR_RED)

    # ─────────────────────────────────────────────────────────────────────────
    # Settings persistence
    # ─────────────────────────────────────────────────────────────────────────

    def _settings_path(self):
        return os.path.join(os.path.dirname(__file__), "camera_settings.json")

    def _load_camera_settings(self):
        try:
            with open(self._settings_path()) as f:
                s = json.load(f)
            self._cam_ip.setText(s.get("ip", "100.100.100.1"))
            self._cam_fps.setText(str(s.get("fps", "1000")))
            self._cam_exp.setText(str(s.get("exposure_us", "500")))
            self._cam_width.setText(str(s.get("width", "640")))
            self._cam_height.setText(str(s.get("height", "480")))
            self._cam_pre_s.setText(str(s.get("pre_trigger_s", "0.5")))
            self._cam_post_s.setText(str(s.get("post_trigger_s", "0.5")))
            self._cam_save_video_chk.setChecked(bool(s.get("save_video", True)))
            self._pipeline_check.setChecked(bool(s.get("run_ai_analysis", False)))
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
            last_p = s.get("last_pressure")
            if last_p is not None:
                self._last_pressure = float(last_p)
                self._last_pressure_btn.setText(f"Set last: {self._last_pressure:.2f} BAR")
                self._last_pressure_btn.setEnabled(True)
            # Lamella analysis settings
            self._lamella_crop_cfg   = s.get("lamella_crop",       {"x": 0, "y": 0, "w": 256, "h": 256})
            self._lamella_model_path = s.get("lamella_model_path", "")
            self._lamella_arch       = s.get("lamella_arch",       "smp")
        except Exception as e:
            print(f"[WARNING] Could not load camera settings: {e}")

    def _save_camera_settings(self):
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
                "run_ai_analysis":   self._pipeline_check.isChecked(),
                "cone_autofocus":    self._cone_autofocus_chk.isChecked(),
                "cone_focus":        self._cone_focus_spin.value(),
                "cone_top_crop":     self._cone_top_crop_spin.value(),
                "last_pressure":     self._last_pressure,
                # Lamella analysis settings
                "lamella_crop":       getattr(self, "_lamella_crop_cfg",   {"x": 0, "y": 0, "w": 256, "h": 256}),
                "lamella_model_path": getattr(self, "_lamella_model_path", ""),
                "lamella_arch":       getattr(self, "_lamella_arch",       "smp"),
            }
            with open(self._settings_path(), "w") as f:
                json.dump(s, f, indent=2)
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
        if self._run_folder:
            return os.path.join(self._run_folder, "run_summary.xlsx")
        lacie = find_lacie_drive()
        if lacie:
            return os.path.join(lacie, "Experiments", "YYYY", "MM", "DD",
                                "HHMMSS_Nnozzle_pressureBAR", "run_summary.xlsx")
        return "Saving to: experiment_logs/ (no LaCie drive found)"

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Testers
    # ─────────────────────────────────────────────────────────────────────────

    # steps/mm from the Portenta sketch: ((200 * 16) / 2) * 4.25
    _STEPS_PER_MM = 6800

    def _start_ramp_test(self):
        if not self._require_arduino(): return
        try:
            start_speed = int(self._ramp_start_speed_entry.text())
            step_time   = float(self._ramp_step_time_entry.text())
            increment   = int(self._ramp_increment_entry.text())
            if start_speed <= 0 or step_time <= 0 or increment <= 0:
                raise ValueError
        except ValueError:
            self._set_status("Fill in all ramp test fields with valid values", CLR_ORANGE)
            return

        self._ramp_running = True
        self._ramp_start_btn.setEnabled(False)
        self._ramp_stop_btn.setEnabled(True)
        self._log(f"Ramp test started — start: {start_speed} steps/s, "
                  f"+{increment} steps/s every {step_time}s")

        def _run():
            speed = start_speed
            try:
                while self._ramp_running:
                    remaining_mm = self.MAX_MOTOR_MM - self.cumulative_distance
                    if remaining_mm <= 0.01:
                        QTimer.singleShot(0, self,
                            lambda: self._log("Syringe limit reached — ramp test complete"))
                        break

                    dist_mm = (speed * step_time) / self._STEPS_PER_MM
                    dist_mm = min(dist_mm, remaining_mm)
                    clipped  = dist_mm < (speed * step_time) / self._STEPS_PER_MM

                    QTimer.singleShot(0, self,
                        lambda s=speed, d=dist_mm: self._log(
                            f"Speed: {s} steps/s  |  moving {d:.3f} mm"))

                    self._movement_done_event.clear()
                    self._pre_move_cumulative   = self.cumulative_distance
                    self._pending_move_distance = dist_mm
                    self.arduino.send_motor_command(speed, round(dist_mm, 3))

                    if clipped:
                        QTimer.singleShot(0, self,
                            lambda: self._log("Syringe limit reached — ramp test complete"))
                        self._movement_done_event.wait(timeout=step_time * 3)
                        break

                    # Wait for Portenta to confirm move complete before next command
                    if not self._movement_done_event.wait(timeout=step_time * 3):
                        QTimer.singleShot(0, self,
                            lambda: self._log("Warning: move timed out — ramp stopped"))
                        break

                    if not self._ramp_running:
                        break

                    speed += increment

            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, self, lambda: self._log(f"Ramp error: {err}"))
            finally:
                QTimer.singleShot(0, self, self._on_ramp_finished)

        threading.Thread(target=_run, daemon=True).start()

    def _stop_ramp_test(self):
        self._ramp_running = False
        self._movement_done_event.set()  # unblock any waiting ramp step
        if self.arduino and self.arduino.ser:
            try: self.arduino.ser.write(b"STOP\n")
            except Exception: pass
        self._log("Ramp test stopped")

    def _on_ramp_finished(self):
        self._ramp_running = False
        self._ramp_start_btn.setEnabled(True)
        self._ramp_stop_btn.setEnabled(False)
        self._set_status("Ramp test finished")

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
        focus = self.focusWidget()
        in_text_field = isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit))
        if not in_text_field:
            if event.key() == Qt.Key.Key_Space:
                if self._cam_trigger_btn.isEnabled():
                    self._cam_trigger()
                event.accept()  # always consume space — prevents focused buttons activating
                return
            if event.key() == Qt.Key.Key_C and self._cone_capture_btn.isEnabled():
                self._cone_capture()
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.serial_reading_active = False
        self._live_feed_timer.stop()
        if self.arduino:     self.arduino.disconnect()
        if self.rpm_arduino:
            try: self.rpm_arduino.send_stop()
            except Exception: pass
            self.rpm_arduino.disconnect()
        if self.phantom:     self.phantom.disconnect()
        if self.afg:         self.afg.disconnect()
        plt.close('all')
        super().closeEvent(event)


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
