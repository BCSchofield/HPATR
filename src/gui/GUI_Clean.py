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
    QSpacerItem, QGridLayout, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread, QSize
from PySide6.QtGui import QFont, QPixmap, QImage, QColor, QPalette, QIcon

# ── Path setup ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config_loader import get_gui_config, resolve_path, find_lacie_drive
    GUI_CONFIG = get_gui_config()
except ImportError:
    GUI_CONFIG = {}
    def resolve_path(p, lacie_base=None): return p
    def find_lacie_drive(): return None

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

# ── Backend controllers (unchanged from Windows_Experiment_GUI.py) ────────────

def log_serial(message, log_file=None):
    if log_file is None:
        log_file = GUI_CONFIG.get('serial_log_file', 'serial_log.txt')
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
        time.sleep(1)
        while self.ser.in_waiting > 0:
            response = self.ser.readline().decode().strip()
            if response: log_serial(f"Arduino response: {response}")

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
        self.ph = Phantom()
        self.ph.discover(print_list=False)
        if self.ph.camera_count == 0:
            self.ph.add_simulated_camera()
        self.cam = self.ph.Camera(min(camera_index, self.ph.camera_count - 1))
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
        self.pulse_duration = duration_seconds; self.channel = channel
        ch = f'SOUR{channel}:'
        self.afg.write(f'{ch}FUNC SQUARE')
        self.afg.write(f'{ch}FREQ {1.0 / (2.0 * duration_seconds)}')
        self.afg.write(f'{ch}VOLT {amplitude_volts}')
        self.afg.write(f'{ch}VOLT:OFFS {amplitude_volts/2.0}')
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
        self._shadow_label.setFixedSize(390, 265)
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
        panel.setFixedWidth(300)
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
        self._tabs.addTab(self._build_hardware_tab(),   "  Hardware  ")
        self._tabs.addTab(self._build_camera_tab(),     "  Camera  ")
        self._tabs.addTab(self._build_afg_tab(),        "  AFG1062  ")
        self._tabs.addTab(self._build_how_to_tab(),     "")
        self._tabs.setTabVisible(3, False)   # content shown via corner button

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
            lambda checked: self._tabs.setCurrentIndex(3 if checked else 0)
        )
        self._tabs.currentChanged.connect(
            lambda idx: _how_to_btn.setChecked(idx == 3)
        )
        self._tabs.setCornerWidget(_how_to_btn, Qt.Corner.TopRightCorner)
        return self._tabs

    # ── Hardware tab ─────────────────────────────────────────────────────────

    def _build_hardware_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        w = QWidget()
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
        self._port_combo.addItems(self._get_serial_ports())
        self._port_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        self._pressure_entry.setFixedWidth(120)
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
        w = QWidget()
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
        w = QWidget()
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
            ("PHANTOM CAMERA", [
                ("Connecting",
                 "Enter the camera IP (default 100.100.100.1) in the Camera tab and click Connect. "
                 "Use Ping to test network reachability without a full connection. The camera SDK is "
                 "Windows-only — a warning appears on other platforms."),
                ("Configuring",
                 "Set FPS, resolution (Width × Height), exposure time, and recording duration. "
                 "Click Apply Config before capturing to push settings to the camera."),
                ("Capturing",
                 "Click ● Capture to trigger a high-speed recording. Tick Run analysis pipeline to "
                 "automatically detect droplets and ligaments after capture and save the result to "
                 "Outputs/FINAL_OPTIMIZED_RESULT.png. The Latest Result panel updates on completion."),
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
                 "temperature, observations), then click Save to Excel. Logs are written to the "
                 "LaCie drive under Experiments/Logs/."),
                ("Shadowgraph result",
                 "The Latest Result panel (left) shows the most recent FINAL_OPTIMIZED_RESULT.png found "
                 "on the LaCie drive. Click ↻ Refresh to scan for a newer result after analysis."),
            ]),
            ("KEYBOARD SHORTCUTS & TIPS", [
                ("Dark/light background",
                 "The analysis pipeline saves both light- and dark-background versions of the result "
                 "image. Check the Outputs/ folder for LIGHT_BG and DARK_BG variants."),
                ("Running on macOS",
                 "The GUI runs on macOS for layout/design work. Camera capture and Arduino serial "
                 "require Windows (or the correct driver). Connect warnings will appear for unavailable hardware."),
                ("Python environment",
                 "macOS: conda activate phantom → python src/gui/GUI_Clean.py\n"
                 "Windows: conda activate Detectron2 → python src/gui/GUI_Clean.py"),
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
                                self._handle_pressure_reading(val)
                            except: pass
                        elif "HOMED" in line:
                            self._on_homed()
            except Exception:
                break
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
        self.arduino.send_motor_command(500, 0)
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
            self._afg_status_lbl.setText(f"AFG: configured ({dur*1000:.1f} ms pulse, CH{ch})")
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

        self.arduino.send_pressure_command(pressure)
        time.sleep(0.5)
        self.arduino.send_motor_command(speed, distance)
        self.cumulative_distance += distance
        self._update_travel_bar()

        if self.phantom and self.phantom.is_connected:
            self._cam_capture()

        self.pressure_data['experiment_active'] = False
        self.arduino.send_pressure_off_command()
        self.arduino.reset_state()
        # Freeze a clean copy of the experiment data at this exact moment
        self._last_experiment_snapshot = {
            'timestamps': list(self.pressure_data['experiment_data']['timestamps']),
            'pressures':  list(self.pressure_data['experiment_data']['pressures']),
        }
        self._experiment_saved = False
        self._set_status("Experiment complete ✓ — remember to Save to Excel", CLR_GREEN)

    # ─────────────────────────────────────────────────────────────────────────
    # Logic — Shadowgraph preview
    # ─────────────────────────────────────────────────────────────────────────

    def _find_latest_result(self):
        try:
            try:
                from config_loader import get_imaging_config
                cfg = get_imaging_config()
                base = resolve_path(cfg.get('output_root', ''))
            except: base = None
            if not base or not os.path.exists(base):
                lacie = find_lacie_drive()
                base  = os.path.join(lacie, "Shadowgraph") if lacie else "D:\\Shadowgraph"
            if not os.path.exists(base): return None
            def latest_subdir(path):
                items = [(os.path.join(path,i), os.path.getmtime(os.path.join(path,i)))
                         for i in os.listdir(path) if os.path.isdir(os.path.join(path,i))]
                items.sort(key=lambda x: x[1], reverse=True)
                return [x[0] for x in items]
            for month in latest_subdir(base):
                for day in latest_subdir(month):
                    for ts in latest_subdir(day):
                        f = os.path.join(ts, "Outputs", "FINAL_OPTIMIZED_RESULT.png")
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
        self._result_path_label.setText("Searching: LaCie/Shadowgraph/…/Outputs/FINAL_OPTIMIZED_RESULT.png")

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

            lacie       = find_lacie_drive()
            base        = os.path.join(lacie, "Experiments", "Logs") if lacie else "experiment_logs"
            per_run_dir = os.path.join(base, "per_run")
            os.makedirs(base, exist_ok=True)
            os.makedirs(per_run_dir, exist_ok=True)

            now          = datetime.now()
            ts           = now.strftime("%Y%m%d_%H%M%S")
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

            # ── Individual per-run file ────────────────────────────────────────
            safe_nozzle = f"N{nozzle}".replace(" ", "_")
            fname = (f"{ts}_{safe_nozzle}_{orifice}_{p_range_file}.xlsx"
                     if p_range_file else f"{ts}_{safe_nozzle}_{orifice}.xlsx")
            ind_path = os.path.join(per_run_dir, fname)

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

            # ── Master log (append-mode) ───────────────────────────────────────
            master_path = os.path.join(base, 'master_log.xlsx')
            if os.path.exists(master_path):
                wb = load_workbook(master_path)
                ws = wb.active
            else:
                wb = Workbook()
                ws = wb.active
                ws.title = 'Experiments'
                ws.append(['Timestamp', 'Nozzle', 'Orifice', 'Pressure Range',
                           'Speed (steps/s)', 'Distance (mm)', 'Notes',
                           'Pressure Graph', 'Shadowgraph', 'Cone Image'])
                for col, width in zip('ABCDEFGHIJ', [20, 8, 8, 18, 14, 12, 35, 28, 28, 28]):
                    ws.column_dimensions[col].width = width

            ws.append([ts_str, nozzle, orifice, p_range_str,
                       speed_str, distance_str, notes, '', '', ''])
            row_num = ws.max_row
            ws.row_dimensions[row_num].height = 90   # points ≈ 120 px

            # Render clean light-mode pressure thumbnail from snapshot
            if pressures:
                fig, ax = plt.subplots(figsize=(4.5, 2.0))
                fig.patch.set_facecolor('white')
                ax.set_facecolor('#f5f5f7')
                t0 = snap['timestamps'][0]
                rel_ts = [t - t0 for t in snap['timestamps']]
                ax.plot(rel_ts, pressures, color='#0a84ff', linewidth=2.5, solid_capstyle='round')
                ax.fill_between(rel_ts, pressures, alpha=0.12, color='#0a84ff')
                ax.set_xlabel('Time (s)', fontsize=8, color='#3a3a3c')
                ax.set_ylabel('Pressure (BAR)', fontsize=8, color='#3a3a3c')
                ax.set_title(f'N{nozzle}  {orifice}  {p_range_str}',
                             fontsize=8, color='#1c1c1e', pad=4)
                ax.tick_params(colors='#6e6e73', labelsize=7)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_color('#d1d1d6')
                ax.spines['bottom'].set_color('#d1d1d6')
                ax.grid(True, alpha=0.4, color='#d1d1d6', linewidth=0.6)
                ax.set_ylim(bottom=0)
                fig.tight_layout(pad=0.6)
                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                            facecolor='white')
                plt.close(fig)
                buf.seek(0)
                pimg = XLImage(buf)
                pimg.width = 210; pimg.height = 100
                ws.add_image(pimg, f'H{row_num}')
            else:
                ws.cell(row=row_num, column=8).value = 'NO DATA AVAILABLE'

            # Embed shadowgraph thumbnail if available
            shadow_path = self._result_path_label.text()
            if shadow_path and os.path.exists(shadow_path):
                simg = XLImage(shadow_path)
                simg.width = 200; simg.height = 110
                ws.add_image(simg, f'I{row_num}')
            else:
                ws.cell(row=row_num, column=9).value = 'NO DATA AVAILABLE'

            # Cone image — placeholder until cone spray workflow is implemented
            ws.cell(row=row_num, column=10).value = 'NO DATA AVAILABLE'

            wb.save(master_path)

            self._experiment_saved = True
            self._set_status(f"Saved: {fname}  +  master_log.xlsx updated", CLR_GREEN)
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
        except Exception:
            pass

    def _save_camera_settings(self):
        try:
            s = {
                "ip":          self._cam_ip.text(),
                "fps":         self._cam_fps.text(),
                "exposure_us": self._cam_exp.text(),
                "width":       self._cam_width.text(),
                "height":      self._cam_height.text(),
                "seconds":     self._cam_seconds.text(),
                "output":      self._cam_output.text(),
            }
            with open(self._settings_path(), "w") as f:
                json.dump(s, f, indent=2)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _excel_save_path_hint(self):
        lacie = find_lacie_drive()
        if lacie:
            return os.path.join(lacie, "Experiments", "Logs", "experiment_<timestamp>.xlsx")
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
