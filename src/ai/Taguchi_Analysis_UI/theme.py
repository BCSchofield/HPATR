"""Design tokens and styling helpers, shared with GUI_Clean.py.

Primary path: import the real constants/functions out of
`gui.GUI_Clean` (the existing app), so the two apps are visually one
system and a palette change made in GUI_Clean.py is picked up here too.

Fallback path: GUI_Clean.py is an 8,000-line hardware-control app and
importing it drags in pyserial, pyqtgraph and matplotlib — fine today
(all three are in the `phantom` env), but importing it should never be
able to crash THIS app's startup over an unrelated hardware dependency.
If the import raises for any reason, verbatim-copied literals below take
over and `SOURCE` says so, so a startup banner can report it rather than
silently diverging.
"""
from __future__ import annotations

from . import paths

SOURCE = "GUI_Clean"
IMPORT_ERROR: str | None = None

try:
    paths.ensure_src_on_path()
    from gui.GUI_Clean import (  # type: ignore
        CLR_BG, CLR_PANEL, CLR_INPUT, CLR_BORDER, CLR_TEXT, CLR_TEXT_SEC,
        CLR_ACCENT, CLR_GREEN, CLR_ORANGE, CLR_RED, CLR_PURPLE,
        FONT_FAMILY, RADIUS, BASE_STYLE,
        card, section_label, title_label, accent_button, ghost_button,
        input_row, separator, _darken_hex,
    )
except Exception as _exc:  # pragma: no cover - exercised when GUI_Clean's
    # own heavy deps are missing; the fallback below is the tested default
    # in that case.
    SOURCE = "fallback"
    IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

    import platform as _platform

    from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget

    # Verbatim copy of src/gui/GUI_Clean.py's Apple-dark tokens (lines
    # 104-118 at the time this was written). Keep these two literally in
    # sync; `tests/test_theme.py` asserts GUI_Clean's own values still
    # match this fallback so drift is caught rather than silently shipped.
    CLR_BG = "#111111"
    CLR_PANEL = "#1c1c1e"
    CLR_INPUT = "#2c2c2e"
    CLR_BORDER = "#3a3a3c"
    CLR_TEXT = "#f2f2f7"
    CLR_TEXT_SEC = "#8e8e93"
    CLR_ACCENT = "#0a84ff"
    CLR_GREEN = "#30d158"
    CLR_ORANGE = "#ff9f0a"
    CLR_RED = "#ff453a"
    CLR_PURPLE = "#bf5af2"

    FONT_FAMILY = "SF Pro Display" if _platform.system() == "Darwin" else "Segoe UI"
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
QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {CLR_INPUT};
    color: {CLR_TEXT};
    border: 1px solid #606064;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {CLR_ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {CLR_ACCENT};
}}
QPushButton {{
    background-color: {CLR_INPUT};
    color: {CLR_TEXT};
    border: 1px solid {CLR_BORDER};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}}
QPushButton:hover {{ background-color: {CLR_BORDER}; }}
QPushButton:pressed {{ background-color: {CLR_ACCENT}; color: white; }}
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
QTabBar::tab:selected {{ color: {CLR_ACCENT}; border-bottom: 2px solid {CLR_ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {CLR_TEXT}; }}
QProgressBar {{
    background-color: {CLR_INPUT};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ border-radius: 4px; background-color: {CLR_ACCENT}; }}
QScrollArea {{ border: none; background: transparent; }}
QCheckBox {{ spacing: 8px; color: {CLR_TEXT}; }}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {CLR_BORDER};
    background: {CLR_INPUT};
}}
QCheckBox::indicator:checked {{ background: {CLR_ACCENT}; border-color: {CLR_ACCENT}; }}
QCheckBox::indicator:disabled {{ background: #555558; border-color: #555558; }}
QToolTip {{
    background-color: #2c2c2e;
    color: {CLR_TEXT};
    border: 1px solid {CLR_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""

    def _darken_hex(hex_color: str, factor: float = 0.82) -> str:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = h[0] * 2 + h[1] * 2 + h[2] * 2
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"

    def card(parent=None, padding=16):
        f = QFrame(parent)
        f.setObjectName("card")
        f.setStyleSheet(
            f"QFrame#card {{ background-color: {CLR_PANEL}; "
            f"border: 1px solid {CLR_BORDER}; border-radius: 12px; }}"
        )
        layout = QVBoxLayout(f)
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(10)
        return f

    def section_label(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {CLR_TEXT_SEC}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;"
        )
        return lbl

    def title_label(text, size=15, bold=True):
        lbl = QLabel(text)
        weight = "700" if bold else "500"
        lbl.setStyleSheet(f"color: {CLR_TEXT}; font-size: {size}px; font-weight: {weight};")
        return lbl

    def accent_button(text, color=CLR_ACCENT, hover=None):
        btn = QPushButton(text)
        hover = hover or color
        pressed = _darken_hex(color)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color}; color: white; border: none;
                border-radius: 8px; padding: 8px 18px; font-weight: 600;
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
                background-color: transparent; color: {CLR_ACCENT};
                border: 1px solid {CLR_ACCENT}; border-radius: 8px;
                padding: 7px 16px; font-weight: 500;
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

    def separator():
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {CLR_BORDER}; background: {CLR_BORDER};")
        line.setFixedHeight(1)
        return line


def apply_fusion_style(app) -> None:
    """Fusion + the per-widget restyle loop GUI_Clean.py's main() uses.

    Native Qt style ignores custom borders/backgrounds on macOS — Fusion
    does not. Skipping the per-widget loop at the end is an hour of
    debugging missing borders on macOS; it is not optional polish.
    """
    from PySide6.QtGui import QColor, QFont, QPalette
    from PySide6.QtWidgets import QComboBox, QLineEdit

    app.setStyle("Fusion")
    app.setStyleSheet(BASE_STYLE)

    pal = app.palette()
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(44, 44, 46))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(242, 242, 247))
    app.setPalette(pal)

    font = QFont(FONT_FAMILY)
    font.setPixelSize(13)
    app.setFont(font)


def restyle_inputs(window) -> None:
    """Belt-and-suspenders per-widget restyle, run AFTER the window is
    built (findChildren needs the widgets to exist). Call once, right
    before showing the window."""
    from PySide6.QtWidgets import QComboBox, QLineEdit

    le_ss = (
        f"QLineEdit {{ background-color: {CLR_INPUT}; color: {CLR_TEXT}; "
        f"border: 1px solid #606064; border-radius: 8px; padding: 6px 10px; }} "
        f"QLineEdit:focus {{ border: 1px solid {CLR_ACCENT}; }}"
    )
    cb_ss = (
        f"QComboBox {{ background-color: {CLR_INPUT}; color: {CLR_TEXT}; "
        f"border: 1px solid #606064; border-radius: 8px; padding: 6px 10px; }} "
        f"QComboBox:focus {{ border: 1px solid {CLR_ACCENT}; }} "
        f"QComboBox::drop-down {{ border: none; padding-right: 8px; }}"
    )
    for le in window.findChildren(QLineEdit):
        le.setStyleSheet(le_ss)
    for cb in window.findChildren(QComboBox):
        cb.setStyleSheet(cb_ss)
