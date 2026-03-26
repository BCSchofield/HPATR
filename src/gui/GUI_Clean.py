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
import platform
import threading

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
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QTextEdit,
    QFrame, QTabWidget, QSizePolicy, QProgressBar, QScrollArea,
    QSpacerItem, QGridLayout, QMessageBox, QFileDialog, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread, QSize
from PySide6.QtGui import QFont, QPixmap, QImage, QColor, QPalette, QIcon, QPainter, QPen

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

def accent_button(text, color=CLR_ACCENT, hover=None):
    btn = QPushButton(text)
    hover = hover or color
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
        QPushButton:pressed {{ opacity: 0.8; }}
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

class ClickableImageWidget(QLabel):
    """QLabel subclass that records up to 2 click positions (in original image
    pixel coordinates) and overlays crosshair markers.

    pointsChanged is emitted with the current list of (x, y) tuples every time
    a point is added or the list is reset.
    """
    pointsChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap_orig = None   # full-resolution original
        self._points = []          # list of (x, y) in original image coords
        self.setCursor(Qt.CursorShape.CrossCursor)

    def setCalibrationImage(self, pixmap: QPixmap):
        self._pixmap_orig = pixmap
        self._points = []
        self._redraw()

    def resetPoints(self):
        self._points = []
        self._redraw()
        self.pointsChanged.emit(self._points)

    def getPoints(self) -> list:
        return list(self._points)

    def mousePressEvent(self, event):
        if self._pixmap_orig is None or len(self._points) >= 2:
            return
        lw, lh = self.width(), self.height()
        ow, oh = self._pixmap_orig.width(), self._pixmap_orig.height()
        scale  = min(lw / ow, lh / oh)
        disp_w, disp_h = ow * scale, oh * scale
        ox = (lw - disp_w) / 2
        oy = (lh - disp_h) / 2
        cx, cy = event.position().x(), event.position().y()
        if ox <= cx <= ox + disp_w and oy <= cy <= oy + disp_h:
            img_x = int((cx - ox) / scale)
            img_y = int((cy - oy) / scale)
            self._points.append((img_x, img_y))
            self._redraw()
            self.pointsChanged.emit(self._points)

    def _redraw(self):
        if self._pixmap_orig is None:
            return
        pm = self._pixmap_orig.copy()
        if self._points:
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor("#ff453a"), 3)
            painter.setPen(pen)
            for (x, y) in self._points:
                arm = max(15, pm.width() // 40)
                painter.drawLine(x - arm, y, x + arm, y)
                painter.drawLine(x, y - arm, x, y + arm)
                painter.drawEllipse(x - 6, y - 6, 12, 12)
            painter.end()
        self.setPixmap(pm.scaled(
            self.width(), self.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))


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


class PhantomController:
    def __init__(self):
        self.ph = None; self.cam = None; self.current_cine = None
        self.is_connected = False; self.is_recording = False
        self.recording_started = False

    def connect(self, ip_address=None, camera_index=0):
        if not PHANTOM_SDK_AVAILABLE:
            raise RuntimeError("Phantom SDK not installed")
        import pyphantom as _pyph
        self.ph = Phantom()
        self.ph.discover(print_list=False)
        if self.ph.camera_count == 0:
            raise RuntimeError("No Phantom camera found")
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

    def configure(self, width, height, fps, exposure_us, partition_count=1, post_trigger_frames=0):
        if not self.is_connected: raise RuntimeError("Camera not connected")
        self.cam.resolution = (int(width), int(height))
        self.cam.partition_count = int(partition_count)
        self.cam.post_trigger_frames = int(post_trigger_frames)
        self.cam.frame_rate = float(fps)
        actual_fps = self.cam.frame_rate
        max_exp = (1.0 / actual_fps) * 1e6
        if exposure_us >= max_exp:
            raise RuntimeError(f"Exposure {exposure_us}μs exceeds max {max_exp:.1f}μs")
        self.cam.exposure = float(exposure_us)
        return {'resolution': self.cam.resolution, 'frame_rate': actual_fps,
                'exposure': self.cam.exposure}

    def start_recording(self):
        self.cam.record(); self.is_recording = True; self.recording_started = False; return True

    def trigger(self):
        self.cam.trigger(); self.recording_started = True; return True

    def save_recording(self, output_path, cine_index=1, file_format='cine', frame_range=None):
        self.current_cine = self.cam.Cine(cine_index)
        fmt_map = {'cine': 0, 'tiff': -8, 'tif': -8, 'avi': -7}
        self.current_cine.save_type = utils.FileTypeEnum(fmt_map.get(file_format, 0))
        if frame_range is None:
            r = self.current_cine.range
            self.current_cine.save_range = utils.FrameRange(r.first_image, r.last_image)
        self.current_cine.save_name = output_path
        self.current_cine.save()
        return True

    def abort(self):
        if self.is_recording:
            self.cam.clear_ram(); self.is_recording = False; self.recording_started = False
        return True

    def ping(self):
        try: _ = self.cam.frame_rate; return True
        except: self.is_connected = False; return False

    def disconnect(self):
        try:
            if self.cam: self.cam.close(); self.cam = None
            if self.ph: self.ph.close(); self.ph = None
        except: pass
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

        # Set period to 10x the pulse width — gives 10% duty cycle baseline
        # This is only the carrier period; burst mode means it fires once per trigger
        period_seconds = max(duration_seconds * 10, 1e-3)  # minimum 1ms period
        self.afg.write(f'{ch}FREQ {1.0 / period_seconds}')

        # Set pulse width directly in seconds
        # AFG1062 accepts pulse width via PULSe:WIDTh command
        self.afg.write(f'{ch}PULS:WIDT {duration_seconds}')

        # Set amplitude and offset for TTL-compatible 0-5V output
        self.afg.write(f'{ch}VOLT {amplitude_volts}')
        self.afg.write(f'{ch}VOLT:OFFS {amplitude_volts / 2.0}')
        self.afg.write(f'{ch}VOLT:LOW 0.0')
        self.afg.write(f'{ch}VOLT:HIGH {amplitude_volts}')

        # Configure burst mode: single pulse per manual trigger
        self.afg.write(f'{ch}BURS:STAT ON')
        self.afg.write(f'{ch}BURS:MODE TRIG')
        self.afg.write(f'{ch}BURS:NCYC 1')
        self.afg.write(f'{ch}BURS:TRIG:SOUR MAN')
        self.afg.write(f'{ch}TRIG:SOUR MAN')

    def trigger(self, channel=1):
        if not self.is_connected: raise RuntimeError("AFG not connected")
        self.afg.write('*TRG')

    def disconnect(self):
        try:
            if self.afg:
                try: self.afg.write('SOUR1:OUTP OFF'); self.afg.write('SOUR2:OUTP OFF')
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

# ── Main application window ───────────────────────────────────────────────────

class AtomisationApp(QMainWindow):

    MAX_MOTOR_MM = 72.5   # physical travel limit

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Atomisation Control Panel")

        # ── State ─────────────────────────────────────────────────────────────
        self.arduino: ArduinoController | None = None
        self.arduino_connected = False
        self.serial_reading_active = False
        self.serial_reader_thread = None

        self.phantom = PhantomController() if PHANTOM_SDK_AVAILABLE else None
        self.afg     = AFGController()     if PYVISA_AVAILABLE       else None

        self.is_windows = platform.system() == "Windows"
        self.camera_available = self.is_windows and PHANTOM_SDK_AVAILABLE

        self.cumulative_distance = 0.0
        self.cleaning_in_progress = False
        self._experiment_saved = True   # True until an experiment runs unsaved
        self._run_folder = None          # Set eagerly on Start Experiment, cleared on next start

        self.pressure_data = {
            'live_buffer': {'timestamps': [], 'pressures': []},
            'experiment_data': {'timestamps': [], 'pressures': []},
            'experiment_active': False,
            'experiment_start_time': None,
        }
        self.pressure_data['live_buffer_start_time'] = time.time()
        self._last_experiment_snapshot = {'timestamps': [], 'pressures': []}

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()
        self._load_camera_settings()

        # ── Timers ────────────────────────────────────────────────────────────
        self._serial_timer = QTimer(self)
        self._serial_timer.timeout.connect(self._poll_serial)
        self._serial_timer.start(200)

        self._graph_timer = QTimer(self)
        self._graph_timer.timeout.connect(self._update_pressure_graph)
        self._graph_timer.start(500)

        self._cone_feed_timer = QTimer(self)
        self._cone_feed_timer.timeout.connect(self._cone_update_feed)
        # started/stopped by Start Camera / Stop Camera buttons

        self._cone_auto_timer = QTimer(self)
        self._cone_auto_timer.timeout.connect(self._cone_capture)
        # started in _start_experiment(), stopped in _on_movement_complete()

        self._cone_cap = None  # cv2.VideoCapture instance

        # Auto-connect Arduino
        ports = self._get_serial_ports()
        if ports:
            self._trigger_arduino_connect()

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
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
        hl.addStretch()

        # Pixels/mm display (updated by calibration; persists via settings)
        self._hdr_pxmm_lbl = QLabel("– px/mm")
        self._hdr_pxmm_lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
        hl.addWidget(self._hdr_pxmm_lbl)
        _sep = QFrame(); _sep.setFixedWidth(1); _sep.setFixedHeight(18)
        _sep.setStyleSheet(f"background: {CLR_BORDER};")
        hl.addWidget(_sep)

        # Status dots
        self._hdr_arduino_dot  = dot_indicator(CLR_TEXT_SEC)
        self._hdr_arduino_lbl  = QLabel("Arduino")
        self._hdr_pressure_dot = dot_indicator(CLR_TEXT_SEC)
        self._hdr_pressure_lbl = QLabel("– BAR")
        self._hdr_camera_dot   = dot_indicator(CLR_TEXT_SEC)
        self._hdr_camera_lbl   = QLabel("Camera")

        for dot, lbl in [
            (self._hdr_arduino_dot,  self._hdr_arduino_lbl),
            (self._hdr_pressure_dot, self._hdr_pressure_lbl),
            (self._hdr_camera_dot,   self._hdr_camera_lbl),
        ]:
            lbl.setStyleSheet(f"color: {CLR_TEXT_SEC}; font-size: 12px;")
            hl.addWidget(dot)
            hl.addWidget(lbl)
            sp = QFrame()
            sp.setFixedWidth(16)
            sp.setStyleSheet("background: transparent;")
            hl.addWidget(sp)

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

        vl.addWidget(preview_card)

        # ── Pressure graph card ───────────────────────────────────────────────
        graph_card = card()
        graph_card.layout().setSpacing(6)
        graph_card.layout().addWidget(title_label("Pressure (live)", 13))

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

        # ── Motor travel card ─────────────────────────────────────────────────
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

        vl.addWidget(motor_card)

        # ── Pressure Off (always visible) ─────────────────────────────────────
        pressure_off_card = card(padding=10)
        pressure_off_card.layout().setSpacing(6)
        pressure_off_card.layout().addWidget(title_label("Emergency", 13))

        self._pressure_off_btn_left = accent_button("Pressure Off", CLR_RED)
        self._pressure_off_btn_left.setFixedHeight(40)
        self._pressure_off_btn_left.clicked.connect(self._pressure_off)
        pressure_off_card.layout().addWidget(self._pressure_off_btn_left)

        vl.addWidget(pressure_off_card)
        vl.addStretch()

        self._refresh_shadowgraph()
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
        nozzle_card.layout().addWidget(input_row("Nozzle No.", self._nozzle_entry, label_width=90))

        self._orifice_combo = QComboBox()
        self._orifice_combo.addItems(["1mm","1.2mm","1.4mm","1.6mm","1.8mm","2mm"])
        nozzle_card.layout().addWidget(input_row("Orifice", self._orifice_combo, label_width=90))

        vl.addWidget(nozzle_card)

        # ── Notes card ────────────────────────────────────────────────────────
        notes_card = card()
        notes_card.layout().addWidget(section_label("NOTES"))
        notes_card.layout().addWidget(separator())

        self._notes_text = QTextEdit()
        self._notes_text.setPlaceholderText("Fluid composition, temperature, observations...")
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
        save_btn.clicked.connect(self._save_to_excel)
        sr.addWidget(self._save_path_lbl, stretch=1)
        sr.addWidget(save_btn)
        notes_card.layout().addWidget(save_row)

        vl.addWidget(notes_card, stretch=1)
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
        self._tabs.addTab(self._build_how_to_tab(),       "")
        self._tabs.setTabVisible(5, False)   # content shown via corner button

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
            lambda checked: self._tabs.setCurrentIndex(5 if checked else 0)
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

        # ── Arduino ───────────────────────────────────────────────────────────
        c = card(w)
        c.layout().addWidget(section_label("ARDUINO"))
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
        refresh_port_btn = ghost_button("Refresh")
        refresh_port_btn.setFixedHeight(34)
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
        self._connect_btn.clicked.connect(self._trigger_arduino_connect)
        self._disconnect_btn.clicked.connect(self._trigger_arduino_disconnect)
        self._arduino_status_lbl = QLabel("Not connected")
        self._arduino_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        br.addWidget(self._connect_btn); br.addWidget(self._disconnect_btn)
        br.addStretch(); br.addWidget(self._arduino_status_lbl)
        c.layout().addWidget(btn_row)
        vl.addWidget(c)

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
        set_p_btn = accent_button("Set Pressure", CLR_ACCENT)
        set_p_btn.setFixedHeight(36)
        set_p_btn.clicked.connect(self._set_pressure)
        off_p_btn = accent_button("Pressure Off", CLR_RED)
        off_p_btn.setFixedHeight(36)
        off_p_btn.clicked.connect(self._pressure_off)
        pir.addWidget(p_lbl); pir.addWidget(self._pressure_entry)
        pir.addWidget(set_p_btn); pir.addStretch(); pir.addWidget(off_p_btn)
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
        c3.layout().addWidget(input_row("Speed (steps/s)", self._speed_entry))
        c3.layout().addWidget(input_row("Distance (mm)",   self._distance_entry))

        motor_btns = QWidget()
        mb = QHBoxLayout(motor_btns); mb.setContentsMargins(0,0,0,0); mb.setSpacing(8)
        self._home_btn  = accent_button("🏠  Home",    CLR_ORANGE)
        self._clean_btn = accent_button("🧼  Clean",   CLR_PURPLE)
        self._move_btn  = accent_button("Move",        CLR_ACCENT)
        self._homed_dot = dot_indicator(CLR_RED)
        homed_lbl = QLabel("Homed"); homed_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        self._home_btn.setFixedHeight(36); self._clean_btn.setFixedHeight(36); self._move_btn.setFixedHeight(36)
        self._home_btn.clicked.connect(self._home_motor)
        self._clean_btn.clicked.connect(self._start_cleaning)
        self._move_btn.clicked.connect(self._move_motor)
        mb.addWidget(self._home_btn); mb.addWidget(self._clean_btn)
        mb.addStretch(); mb.addWidget(self._homed_dot); mb.addWidget(homed_lbl)
        mb.addStretch(); mb.addWidget(self._move_btn)
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
        self._cam_width    = QLineEdit("640");  self._cam_width.setFixedWidth(_W)
        self._cam_height   = QLineEdit("480");  self._cam_height.setFixedWidth(_W)
        self._cam_seconds  = QLineEdit("0.020");self._cam_seconds.setFixedWidth(_W)
        self._cam_output   = QLineEdit()

        def glbl(t):
            l=QLabel(t); l.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
            return l

        grid.addWidget(glbl("FPS"),           0,0); grid.addWidget(self._cam_fps,     0,1)
        grid.addWidget(glbl("Height"),        1,0); grid.addWidget(self._cam_height,  1,1)
        grid.addWidget(glbl("Width"),         2,0); grid.addWidget(self._cam_width,   2,1)
        grid.addWidget(glbl("Duration (s)"),  3,0); grid.addWidget(self._cam_seconds, 3,1)
        grid.addWidget(glbl("Exposure (μs)"), 4,0); grid.addWidget(self._cam_exp,     4,1)
        grid.addWidget(glbl("Output path"),   5,0); grid.addWidget(self._cam_output,  5,1)
        grid.setColumnStretch(1, 1)
        c2.layout().addWidget(grid_w)

        apply_btn = accent_button("Apply Config", CLR_ACCENT)
        apply_btn.setFixedHeight(36); apply_btn.clicked.connect(self._cam_configure)
        c2.layout().addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignRight)
        vl.addWidget(c2)

        # Capture card
        c3 = card(w)
        c3.layout().addWidget(section_label("CAPTURE"))
        c3.layout().addWidget(separator())

        self._pipeline_check = QCheckBox("Run analysis pipeline after capture")
        self._pipeline_check.setStyleSheet(f"color:{CLR_TEXT}; font-size:13px;")
        c3.layout().addWidget(self._pipeline_check)
        _pipeline_desc = QLabel("When enabled, the CV/AI analysis pipeline runs automatically after each capture — detecting droplets and ligaments and saving the result to Outputs/FINAL_OPTIMIZED_RESULT.png.")
        _pipeline_desc.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        _pipeline_desc.setWordWrap(True)
        c3.layout().addWidget(_pipeline_desc)

        cap_row = QWidget()
        cpr = QHBoxLayout(cap_row); cpr.setContentsMargins(0,0,0,0); cpr.setSpacing(8)
        self._cam_abort_btn   = ghost_button("Abort")
        self._cam_capture_btn = accent_button("● Capture", CLR_RED)
        self._cam_abort_btn.setFixedHeight(40); self._cam_capture_btn.setFixedHeight(40)
        self._cam_abort_btn.clicked.connect(self._cam_abort)
        self._cam_capture_btn.clicked.connect(self._cam_capture)
        cpr.addStretch(); cpr.addWidget(self._cam_abort_btn); cpr.addWidget(self._cam_capture_btn)
        c3.layout().addWidget(cap_row)
        vl.addWidget(c3)

        if not self.camera_available:
            for btn in [self._cam_connect_btn, self._cam_ping_btn,
                        apply_btn, self._cam_abort_btn, self._cam_capture_btn]:
                btn.setEnabled(False)

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
        self._afg_connect_btn.clicked.connect(self._afg_connect)
        chr_.addWidget(ch_lbl); chr_.addWidget(self._afg_channel)
        chr_.addStretch(); chr_.addWidget(self._afg_connect_btn)
        c.layout().addWidget(ch_row)

        self._afg_duration = QLineEdit("0.001")
        self._afg_duration.setFixedWidth(120)
        c.layout().addWidget(input_row("Pulse Duration (s)", self._afg_duration))

        action_row = QWidget()
        ar = QHBoxLayout(action_row); ar.setContentsMargins(0,0,0,0); ar.setSpacing(8)
        self._afg_apply_btn = accent_button("Apply Config",  CLR_ACCENT)
        self._afg_test_btn  = ghost_button("Test Fire")
        self._afg_disc_btn  = ghost_button("Disconnect")
        for btn in [self._afg_apply_btn, self._afg_test_btn, self._afg_disc_btn]:
            btn.setFixedHeight(36)
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
        self._cal_feed_label.setFixedSize(500, 300)
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
        self._cal_load_btn.clicked.connect(self._cal_load_photo)
        self._cal_take_btn = accent_button("Take Photo", CLR_ACCENT)
        self._cal_take_btn.setFixedHeight(36)
        self._cal_take_btn.clicked.connect(self._cal_take_photo)
        if not self.camera_available:
            self._cal_take_btn.setEnabled(False)
            self._cal_take_btn.setToolTip("Connect Phantom camera on Windows to capture live frame")
        fbr.addStretch()
        fbr.addWidget(self._cal_load_btn)
        fbr.addWidget(self._cal_take_btn)
        c1.layout().addWidget(feed_btn_row)

        vl.addWidget(c1)

        # ── CALIBRATION IMAGE card ────────────────────────────────────────────
        c2 = card(w)
        c2.layout().addWidget(section_label("CALIBRATION"))
        c2.layout().addWidget(separator())

        instr = QLabel("Click two points on a known distance, "
                       "enter the real-world distance in mm, then press Calculate.")
        instr.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:11px;")
        instr.setWordWrap(True)
        c2.layout().addWidget(instr)

        self._cal_image_widget = ClickableImageWidget()
        self._cal_image_widget.setFixedSize(500, 300)
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
        self._cal_reset_btn.clicked.connect(self._cal_reset_points)
        self._cal_calc_btn = accent_button("Calculate px/mm", CLR_ACCENT)
        self._cal_calc_btn.setFixedHeight(36)
        self._cal_calc_btn.setEnabled(False)
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
        self._cone_feed_lbl.setFixedSize(500, 300)
        self._cone_feed_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cone_feed_lbl.setStyleSheet(
            f"background:{CLR_INPUT}; color:{CLR_TEXT_SEC}; border-radius:8px; font-size:13px;")
        c1.layout().addWidget(self._cone_feed_lbl)

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
        self._cone_stop_cam_btn  = ghost_button("Stop Camera")
        self._cone_stop_cam_btn.clicked.connect(self._cone_stop_camera)
        self._cone_stop_cam_btn.setEnabled(False)
        cam_hl.addWidget(self._cone_start_cam_btn)
        cam_hl.addWidget(self._cone_stop_cam_btn)
        cam_hl.addStretch()
        c1.layout().addWidget(cam_row)

        self._cone_cam_status_lbl = QLabel("Camera stopped")
        self._cone_cam_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
        c1.layout().addWidget(self._cone_cam_status_lbl)

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
            "Fraction of image height cropped from the top before analysis.\n"
            "The red band on the live feed shows the excluded region.")
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

        self._cone_capture_btn = accent_button("Capture & Analyse")
        self._cone_capture_btn.setEnabled(False)
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

    def _get_serial_ports(self):
        ports = serial.tools.list_ports.comports()
        result = []
        for p in ports:
            dev  = p.device
            desc = (p.description or "").lower()
            if dev.upper().startswith("COM") or "usb" in desc or "serial" in desc:
                result.append(dev)
        return result

    def _refresh_ports(self):
        ports = self._get_serial_ports()
        self._port_combo.clear()
        self._port_combo.addItems(ports)
        if ports:
            self._set_status(f"Found {len(ports)} port(s)")

    def _trigger_arduino_connect(self):
        port = self._port_combo.currentText()
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
                        elif "Homing Complete" in line:
                            QTimer.singleShot(0, self, self._on_homed)
                        elif line.startswith("DEBUG: Movement progress:"):
                            try:
                                pct = int(line.split(":")[-1].strip().replace("%", ""))
                                QTimer.singleShot(0, self, lambda p=pct: (
                                    self._exp_progress.setRange(0, 100),
                                    self._exp_progress.setValue(p)
                                ))
                            except: pass
            except serial.SerialException:
                break  # port closed or disconnected — exit cleanly
            except Exception as e:
                log_serial(f"Serial reader warning: {e}")
            time.sleep(0.05)

    def _poll_serial(self):
        pass  # Serial reading handled by background thread above

    def _handle_pressure_reading(self, val):
        now = time.time()
        lb  = self.pressure_data['live_buffer']
        lb['timestamps'].append(now - self.pressure_data['live_buffer_start_time'])
        lb['pressures'].append(val)
        # Keep 60s rolling window
        cutoff = lb['timestamps'][-1] - 60.0
        while lb['timestamps'] and lb['timestamps'][0] < cutoff:
            lb['timestamps'].pop(0); lb['pressures'].pop(0)
        if self.pressure_data['experiment_active']:
            ed = self.pressure_data['experiment_data']
            ed['timestamps'].append(now - self.pressure_data['experiment_start_time'])
            ed['pressures'].append(val)
        # Update labels on main thread via timer (already running in thread)
        self._cur_pressure_lbl.setText(f"{val:.1f} BAR")
        self._hdr_pressure_lbl.setText(f"{val:.1f} BAR")
        self._hdr_pressure_dot.setStyleSheet(f"color:{CLR_ACCENT}; font-size:10px; background:transparent;")

    def _on_homed(self):
        self._homed_dot.setStyleSheet(f"color:{CLR_GREEN}; font-size:10px;")
        self.cumulative_distance = 0.0
        self._update_travel_bar()

    def _on_movement_complete(self):
        if self.pressure_data['experiment_active']:
            self.pressure_data['experiment_active'] = False
            self._cone_auto_timer.stop()
            self._cone_auto_status_lbl.setText("Auto-capture: inactive")
            self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_TEXT_SEC}; font-size:12px;")
            self.arduino.send_pressure_off_command()
            self.arduino.reset_state()
            self._last_experiment_snapshot = {
                'timestamps': list(self.pressure_data['experiment_data']['timestamps']),
                'pressures':  list(self.pressure_data['experiment_data']['pressures']),
            }
            self._experiment_saved = False
            self._exp_progress.setVisible(False)
            self._start_btn.setEnabled(True)
            self._set_status("Experiment complete ✓ — remember to Save to Excel", CLR_GREEN)

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
        except ValueError:
            self._set_status("Invalid pressure value", CLR_ORANGE)
            self._warn("Invalid Pressure",
                       "Please enter a pressure between 0.0 and 26.4 BAR.")

    def _pressure_off(self):
        if not self._require_arduino(): return
        self.arduino.send_pressure_off_command()
        self._set_status("Pressure off")

    def _home_motor(self):
        if not self._require_arduino(): return
        self.arduino.ser.write(b"HOME:1\n")
        log_serial("Sent: HOME:1")
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
        self.cumulative_distance += dist
        self._update_travel_bar()
        self._set_status(f"Moving {dist} mm at {speed} steps/s")

    def _update_travel_bar(self):
        pct = self.cumulative_distance / self.MAX_MOTOR_MM
        self._travel_bar.setValue(int(pct * 1000))
        remaining = self.MAX_MOTOR_MM - self.cumulative_distance
        self._travel_label.setText(f"{self.cumulative_distance:.1f} / {self.MAX_MOTOR_MM} mm")
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

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Pressure graph
    # ─────────────────────────────────────────────────────────────────────────

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
            self.phantom.configure(
                width=int(self._cam_width.text()),
                height=int(self._cam_height.text()),
                fps=float(self._cam_fps.text()),
                exposure_us=float(self._cam_exp.text()),
            )
            self._cam_status_lbl.setText("Config applied")
            self._save_camera_settings()
        except Exception as e:
            self._set_status(f"Camera config error: {e}", CLR_RED)

    def _cam_abort(self):
        if self.phantom: self.phantom.abort()
        self._cam_status_lbl.setText("Camera: aborted")

    def _cam_capture(self):
        if not self.phantom: return
        try:
            self.phantom.start_recording()
            self.phantom.trigger()
            out = self._cam_output.text() or "capture"
            self.phantom.save_recording(out)
            self._cam_status_lbl.setText("Capture saved")
            if self._pipeline_check.isChecked():
                self._run_pipeline(out)
        except Exception as e:
            self._set_status(f"Capture error: {e}", CLR_RED)

    def _run_pipeline(self, source_path):
        self._pipeline_status.setText("Pipeline: running…")
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from imaging.save_and_analyse import process_and_save_to_lacie
            process_and_save_to_lacie(source_path)
            self._pipeline_status.setText("Pipeline: complete ✓")
            self._refresh_shadowgraph()
        except Exception as e:
            self._pipeline_status.setText(f"Pipeline error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Calibration
    # ─────────────────────────────────────────────────────────────────────────

    def _cal_take_photo(self):
        """Capture a frame from the Phantom live feed and load it into the
        calibration widget.

        TODO(calibration): Change save_dir to:
            os.path.join(find_lacie_drive(), "Phantom", "Calibration")
        when the LaCie drive is reliably available.  Use find_lacie_drive()
        from src/config_loader.py.  For now images are saved locally.
        """
        if not self.phantom or not self.phantom.is_connected:
            self._warn("Camera Not Connected", "Connect the Phantom camera first.")
            return
        try:
            # TODO(calibration): verify the correct pyphantom method for a live
            # single-frame grab (e.g. cam.get_image() / cam.live_image()).
            frame = self.phantom.cam.get_image()
            h, w = frame.shape[:2]
            fmt = QImage.Format.Format_RGB888 if len(frame.shape) == 3 \
                  else QImage.Format.Format_Grayscale8
            img = QImage(frame.data, w, h, int(frame.strides[0]), fmt)
            pixmap = QPixmap.fromImage(img)
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
        pixel_dist = abs(y2 - y1)  # vertical only — calibration target is always mounted vertically
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
        img = QImage(rgb.data, w, h, w * ch, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(img)

    def _cone_start_camera(self):
        if not CV2_AVAILABLE:
            return
        idx = self._cone_idx_spin.value()
        cap = cv2.VideoCapture(idx)
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
            self._cone_feed_lbl.width(), self._cone_feed_lbl.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
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

        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir  = self._cone_save_dir()
        raw_path  = os.path.join(save_dir, f"cone_raw_{ts}.png")
        cv2.imwrite(raw_path, frame)

        if not CONE4_AVAILABLE:
            self._cone_angle_lbl.setText("Cone_4.py not found — raw image saved only")
            self._cone_angle_lbl.setVisible(True)
            self._cone_result_img_lbl.setVisible(False)
            self._cone_saved_lbl.setText(f"Saved: {raw_path}")
            self._cone_saved_lbl.setVisible(True)
            return

        try:
            from pathlib import Path as _Path
            angle, annotated_bgr, _debug = detect_cone_angle(
                _Path(raw_path), top_crop_ratio=self._cone_top_crop_spin.value())
        except Exception as e:
            self._cone_angle_lbl.setText(f"Analysis error: {e}")
            self._cone_angle_lbl.setVisible(True)
            return

        annotated_path = os.path.join(save_dir, f"cone_{ts}.png")
        cv2.imwrite(annotated_path, annotated_bgr)

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

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — AFG
    # ─────────────────────────────────────────────────────────────────────────

    def _afg_connect(self):
        if not self.afg: return
        try:
            self.afg.connect()
            self._afg_status_lbl.setText("AFG: connected")
            self._afg_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;")
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
        for _sub in [os.path.join("shadowgraph", "raw"),
                     os.path.join("shadowgraph", "analysis"), "cone"]:
            os.makedirs(os.path.join(self._run_folder, _sub), exist_ok=True)

        # Start cone auto-capture (every 5 s) if webcam is already running
        if self._cone_cap is not None and self._cone_cap.isOpened():
            self._cone_auto_timer.start(5000)
            self._cone_auto_status_lbl.setText("Auto-capture: ON (every 5 s)")
            self._cone_auto_status_lbl.setStyleSheet(f"color:{CLR_GREEN}; font-size:12px;")
        # Reset live buffer so the graph X-axis starts from 0 at experiment start
        self.pressure_data['live_buffer'] = {'timestamps': [], 'pressures': []}
        self.pressure_data['live_buffer_start_time'] = time.time()

        self._start_btn.setEnabled(False)
        self._exp_progress.setRange(0, 0)   # indeterminate pulsing
        self._exp_progress.setVisible(True)
        self._set_status("Experiment running…", CLR_ACCENT)

        self.arduino.send_pressure_command(pressure)
        # Send motor command 500 ms later without blocking the UI
        QTimer.singleShot(500, lambda: self.arduino.send_motor_command(speed, distance))
        self.cumulative_distance += distance
        self._update_travel_bar()

        if self.phantom and self.phantom.is_connected:
            self._cam_capture()

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Shadowgraph preview
    # ─────────────────────────────────────────────────────────────────────────

    def _find_latest_result(self):
        try:
            # Check the active run folder first
            if self._run_folder:
                f = os.path.join(self._run_folder, "shadowgraph", "analysis",
                                 "FINAL_OPTIMIZED_RESULT.png")
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
                            f = os.path.join(run, "shadowgraph", "analysis",
                                             "FINAL_OPTIMIZED_RESULT.png")
                            if os.path.exists(f): return f
        except Exception as e:
            print(f"Error finding result: {e}")
        return None

    def _refresh_shadowgraph(self):
        path = self._find_latest_result()
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
        self._result_path_label.setText("Searching: LaCie/Experiments/…/shadowgraph/analysis/FINAL_OPTIMIZED_RESULT.png")

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

            meta = {
                'Field': ['Timestamp', 'Nozzle', 'Orifice', 'Pressure Range',
                          'Speed (steps/s)', 'Distance (mm)', 'Notes'],
                'Value': [ts_str, nozzle, orifice, p_range_str,
                          speed_str, distance_str, notes],
            }
            with pd.ExcelWriter(ind_path, engine='openpyxl') as writer:
                pd.DataFrame(meta).to_excel(writer, sheet_name='Metadata', index=False)
                if snap['timestamps']:
                    pd.DataFrame(snap).to_excel(writer, sheet_name='Pressure', index=False)

            # ── Render pressure thumbnail ─────────────────────────────────────
            # Strategy: set DPI = DISPLAY_H / fig_h so the PNG renders at
            # exactly DISPLAY_H pixels tall.  That means we embed at 1:1 scale
            # vertically — no squash/stretch — and text always appears the same
            # visual size regardless of how wide the chart is.
            DISPLAY_H   = 165          # Excel display height, pixels
            MIN_W_PX    = 347          # minimum display width (= 10 s baseline)
            PX_PER_SEC  = MIN_W_PX / 10.0
            FIG_H_IN    = 2.0
            DPI         = DISPLAY_H / FIG_H_IN   # ≈ 82.5 — height is always 165 px
            pressure_buf = None
            pressure_img_width = MIN_W_PX
            if pressures:
                t0 = snap['timestamps'][0]
                rel_ts = [t - t0 for t in snap['timestamps']]
                duration_s = rel_ts[-1] if rel_ts else 0.0
                target_w_px = max(MIN_W_PX, int(duration_s * PX_PER_SEC))
                fig_w = target_w_px / DPI
                fig, ax = plt.subplots(figsize=(fig_w, FIG_H_IN))
                fig.patch.set_facecolor('white')
                ax.set_facecolor('#f5f5f7')
                ax.plot(rel_ts, pressures, color='#0a84ff', linewidth=2.5, solid_capstyle='round')
                ax.fill_between(rel_ts, pressures, alpha=0.12, color='#0a84ff')
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
                # Read actual PNG dimensions from header; bbox_inches='tight' may
                # trim a few pixels, so derive final Excel width from true size.
                import struct as _struct
                pressure_buf.seek(16)
                actual_w = _struct.unpack('>I', pressure_buf.read(4))[0]
                actual_h = _struct.unpack('>I', pressure_buf.read(4))[0]
                # Scale to DISPLAY_H — height ratio ≈ 1 so width ≈ actual_w
                pressure_img_width = max(MIN_W_PX, int(actual_w * DISPLAY_H / actual_h))
                pressure_buf.seek(0)

            # ── Master log: insert at row 2, shift image anchors first ───────
            import re as _re
            _master_base = lacie if lacie else os.path.join(
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

            ws.cell(row=row_num, column=8).value = 'NO DATA AVAILABLE'

            shadow_src = self._result_path_label.text()
            if shadow_src and os.path.exists(shadow_src):
                simg = XLImage(shadow_src); simg.width = 300; simg.height = 165
                ws.add_image(simg, f'I{row_num}')
            else:
                ws.cell(row=row_num, column=9).value = 'NO DATA AVAILABLE'

            if pressure_buf:
                pimg = XLImage(pressure_buf)
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
            self._cam_seconds.setText(str(s.get("seconds", "0.020")))
            self._cam_output.setText(s.get("output", ""))
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
        except Exception:
            pass

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
                "seconds":           self._cam_seconds.text(),
                "output":            self._cam_output.text(),
                "px_per_mm":         px_per_mm,
                "cone_camera_index": self._cone_idx_spin.value() if (self._cone_cap is not None and self._cone_cap.isOpened()) else existing.get("cone_camera_index", -1),
                "cone_autofocus":    self._cone_autofocus_chk.isChecked(),
                "cone_focus":        self._cone_focus_spin.value(),
                "cone_top_crop":     self._cone_top_crop_spin.value(),
            }
            with open(self._settings_path(), "w") as f:
                json.dump(s, f, indent=2)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _excel_save_path_hint(self):
        if self._run_folder:
            return os.path.join(self._run_folder, "run_summary.xlsx")
        lacie = find_lacie_drive()
        if lacie:
            return os.path.join(lacie, "Experiments", "YYYY", "MM", "DD",
                                "HHMMSS_Nnozzle_pressureBAR", "run_summary.xlsx")
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

    def closeEvent(self, event):
        self.serial_reading_active = False
        if self.arduino:     self.arduino.disconnect()
        if self.phantom:     self.phantom.disconnect()
        if self.afg:         self.afg.disconnect()
        plt.close('all')
        super().closeEvent(event)


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
