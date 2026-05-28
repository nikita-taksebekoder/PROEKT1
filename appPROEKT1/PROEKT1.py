import os
import sys
import io
import collections
import importlib
import threading
import time
import queue
import glob
import struct
import json
import math
import subprocess
from typing import Optional, Union, Tuple, Any, cast, List
import asyncio
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QMessageBox, QDialog, QSpinBox, QSlider, QTableWidget, QTableWidgetItem, QRadioButton, QButtonGroup, QInputDialog, QLineEdit, QCheckBox, QSystemTrayIcon, QMenu, QGroupBox, QColorDialog, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QSizePolicy, QPlainTextEdit, QStackedWidget
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPointF, QRectF, QPoint, QUrl, Slot
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property, QSize
from PySide6.QtGui import QIcon
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPixmap, QPainterPath, QImage, QFontMetrics, QRadialGradient, QLinearGradient, QGradient, QTransform, QFontDatabase
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPointF, QRectF, QEvent, QAbstractNativeEventFilter
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
import ctypes
from ctypes import wintypes

# ─────────────────── Темы оформления (3 варианта из дизайн-макета) ───────────────────
# Палитры синхронизированы с appDESIGN/design-preview.html
THEMES = {
    'violet': {
        'name': 'Фиолетовый',
        'bg': '#0f112b',
        'surface': '#1c1d38',
        'surface_low': '#181933',
        'surface_high': '#262843',
        'card_bg_rgb': '28,29,56',
        'card_bg_alpha': 180,
        'border_rgb': '255,255,255',
        'border_alpha': 22,
        'text': '#e1e0ff',
        'text_dim': '#cac3d8',
        'text_dim_rgb': '202,195,216',
        'accent': '#7c4dff',
        'accent_rgb': '124,77,255',
        'accent_light': '#cdbdff',
        'accent_light_rgb': '205,189,255',
        'secondary': '#8bd5ff',
        'error': '#ffb4ab',
        'sidebar_bg_rgb': '18,19,46',
        'sidebar_bg_alpha': 180,
        'input_bg_rgb': '24,25,51',
        'input_bg_alpha': 220,
        'ghost_bg_rgb': '46,46,46',
        'fullscreen_bg': '#08091a',
    },
    'graphite': {
        'name': 'Графит',
        'bg': '#14151a',
        'surface': '#1f2026',
        'surface_low': '#1a1b20',
        'surface_high': '#2b2c33',
        'card_bg_rgb': '20,21,26',
        'card_bg_alpha': 200,
        'border_rgb': '255,255,255',
        'border_alpha': 20,
        'text': '#e8e8ec',
        'text_dim': '#bcbcc4',
        'text_dim_rgb': '188,188,196',
        'accent': '#6f6f78',
        'accent_rgb': '111,111,120',
        'accent_light': '#d4d4dc',
        'accent_light_rgb': '212,212,220',
        'secondary': '#a8c5d8',
        'error': '#ff8a80',
        'sidebar_bg_rgb': '18,19,22',
        'sidebar_bg_alpha': 200,
        'input_bg_rgb': '26,27,32',
        'input_bg_alpha': 220,
        'ghost_bg_rgb': '40,41,46',
        'fullscreen_bg': '#0c0d0f',
    },
    'light': {
        'name': 'Белый',
        'bg': '#e8ebf3',
        'surface': '#ffffff',
        'surface_low': '#f5f6fa',
        'surface_high': '#dde0eb',
        'card_bg_rgb': '255,255,255',
        'card_bg_alpha': 200,
        'border_rgb': '100,80,180',
        'border_alpha': 46,
        'text': '#1a1b2e',
        'text_dim': '#4a4b6e',
        'text_dim_rgb': '74,75,110',
        'accent': '#5e35cf',
        'accent_rgb': '94,53,207',
        'accent_light': '#7c4dff',
        'accent_light_rgb': '124,77,255',
        'secondary': '#0288d1',
        'error': '#c62828',
        'sidebar_bg_rgb': '255,255,255',
        'sidebar_bg_alpha': 220,
        'input_bg_rgb': '255,255,255',
        'input_bg_alpha': 235,
        'ghost_bg_rgb': '220,224,235',
        'fullscreen_bg': '#1c1d2e',
    },
}

_current_theme_name = 'violet'
_active_palette = THEMES['violet']
APP_FONT_FAMILY = "Inter"
APP_FONT_FALLBACK = "Segoe UI"
_app_font_loaded = False
_app_font_family_effective = APP_FONT_FAMILY


def palette() -> dict:
    """Активная палитра темы (читать на момент создания виджета)."""
    return _active_palette


def current_theme_name() -> str:
    return _current_theme_name


def set_active_theme(theme_name: str) -> str:
    """Установить активную палитру (без перерисовки). Возвращает имя применённой темы."""
    global _current_theme_name, _active_palette
    if theme_name not in THEMES:
        theme_name = 'violet'
    _current_theme_name = theme_name
    _active_palette = THEMES[theme_name]
    return theme_name


def _load_design_font_family() -> str:
    """Загрузить Inter из проекта/Windows Fonts и вернуть фактическое семейство для UI."""
    global _app_font_loaded, _app_font_family_effective
    if _app_font_loaded:
        return _app_font_family_effective

    font_dirs = [
        os.path.join(os.path.dirname(__file__), "fonts"),
        os.path.join(os.path.dirname(__file__), "fonts", "Inter"),
    ]
    win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if os.path.isdir(win_fonts):
        font_dirs.append(win_fonts)

    loaded_families = []
    for folder in font_dirs:
        if not os.path.isdir(folder):
            continue
        for pattern in ("Inter*.ttf", "Inter*.otf"):
            for font_path in glob.glob(os.path.join(folder, pattern)):
                try:
                    font_id = QFontDatabase.addApplicationFont(font_path)
                    if font_id >= 0:
                        loaded_families.extend(QFontDatabase.applicationFontFamilies(font_id))
                except Exception:
                    pass

    try:
        known_families = set(QFontDatabase.families())
    except Exception:
        known_families = set()
    if APP_FONT_FAMILY in loaded_families or APP_FONT_FAMILY in known_families:
        _app_font_family_effective = APP_FONT_FAMILY
    else:
        _app_font_family_effective = APP_FONT_FALLBACK
    _app_font_loaded = True
    return _app_font_family_effective


def design_font_family() -> str:
    return _load_design_font_family()


def apply_design_font(app: 'QApplication') -> str:
    """Применить семейство шрифта из HTML-макета ко всему Qt-приложению."""
    family = _load_design_font_family()
    if app is not None:
        font = QFont(app.font())
        font.setFamily(family)
        app.setFont(font)
    return family


def apply_label_typography(label: QLabel, point_size: float, weight: QFont.Weight = QFont.Weight.Normal,
                           letter_spacing_px: Optional[float] = None) -> None:
    """Точно применить типографику из HTML-макета к QLabel."""
    try:
        font = QFont(label.font())
        font.setFamily(design_font_family())
        font.setPointSizeF(float(point_size))
        font.setWeight(weight)
        if letter_spacing_px is not None:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(letter_spacing_px))
        label.setFont(font)
    except Exception:
        pass


# Шаблон QSS — заполняется значениями активной палитры.
QSS_TEMPLATE = """
QMainWindow, QDialog {{
    background-color: {bg};
    color: {text};
    font-family: "Inter", "Segoe UI", sans-serif;
    font-size: 11pt;
}}

QWidget#glassCard, QFrame#glassCard {{
    background-color: rgba({card_bg_rgb}, {card_bg_alpha});
    border: 1px solid rgba({border_rgb}, {border_alpha});
    border-radius: 20px;
}}

QLabel {{ color: {text}; background: transparent; }}

QPushButton {{
    background-color: {accent};
    color: #fcf6ff;
    border: none;
    border-radius: 12px;
    padding: 8px 18px;
    font-size: 11pt;
    font-weight: 600;
    min-height: 32px;
}}
QPushButton:hover  {{ background-color: {accent_light}; color: #1a1b2e; }}
QPushButton:pressed{{ background-color: {accent}; }}
QPushButton:disabled {{ background-color: rgba({accent_rgb},60); color: rgba(252,246,255,110); }}

QPushButton[variant="ghost"] {{
    background-color: rgba({border_rgb}, 14);
    color: {text};
    border: 1px solid rgba({border_rgb}, 26);
}}
QPushButton[variant="ghost"]:hover {{ background-color: rgba({border_rgb}, 26); color: {text}; }}

QPushButton[variant="icon"] {{
    background-color: rgba({border_rgb}, 14);
    border: 1px solid rgba({border_rgb}, 22);
    border-radius: 10px;
    padding: 0;
    min-width: 40px; min-height: 40px;
}}
QPushButton[variant="icon"]:hover {{
    background-color: rgba({accent_rgb}, 60);
    border-color: {accent};
}}

QComboBox {{
    background-color: rgba({input_bg_rgb}, {input_bg_alpha});
    color: {text};
    border: 1px solid rgba({border_rgb}, {border_alpha});
    border-radius: 10px;
    padding: 6px 14px;
    min-height: 32px;
    font-size: 11pt;
}}
QComboBox:hover  {{ border-color: {accent}; }}
QComboBox:focus  {{ border-color: {accent_light}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {accent_light};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {surface};
    color: {text};
    border: 1px solid rgba({border_rgb}, 26);
    border-radius: 8px;
    selection-background-color: {accent};
    selection-color: #fcf6ff;
    padding: 4px;
    outline: none;
}}

QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: rgba({input_bg_rgb}, 200);
    color: {text};
    border: 1px solid rgba({border_rgb}, {border_alpha});
    border-radius: 10px;
    padding: 6px 12px;
    selection-background-color: {accent};
    selection-color: #fcf6ff;
    font-size: 11pt;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {accent_light}; }}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: rgba({border_rgb}, 14);
    border: none; width: 18px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background-color: {accent}; }}

QSlider::groove:horizontal {{ background: rgba({border_rgb}, 26); height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {accent_light};
    border: 2px solid rgba(252,246,255,200);
    width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ background: {accent_light}; }}

QCheckBox, QRadioButton {{ color: {text_dim}; spacing: 8px; font-size: 11pt; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid rgba({border_rgb}, 50);
    background: rgba({border_rgb}, 14);
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {accent_light}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: none; }}
QRadioButton::indicator:checked {{ background: {accent_light}; border: 4px solid {surface}; }}

QGroupBox {{
    border: 1px solid rgba({border_rgb}, {border_alpha});
    border-radius: 14px;
    margin-top: 18px; padding: 14px;
    background-color: rgba({input_bg_rgb}, 140);
    color: {text}; font-size: 11pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 16px; top: -2px; padding: 0 8px;
    color: {accent_light}; font-weight: 700;
    font-size: 9pt; letter-spacing: 1px;
}}

QMenu {{
    background-color: {surface}; color: {text};
    border: 1px solid rgba({border_rgb}, 26);
    border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background-color: {accent}; color: #fcf6ff; }}
QMenu::separator {{ height: 1px; background: rgba({border_rgb}, 26); margin: 4px 8px; }}

QToolTip {{
    background-color: {surface}; color: {text};
    border: 1px solid rgba({accent_rgb}, 120);
    border-radius: 8px; padding: 6px 10px;
}}

QTableWidget {{
    background-color: rgba({input_bg_rgb}, 200);
    color: {text};
    border: 1px solid rgba({border_rgb}, {border_alpha});
    border-radius: 12px;
    gridline-color: rgba({border_rgb}, 18);
    selection-background-color: {accent};
    selection-color: #fcf6ff;
}}
QHeaderView::section {{
    background-color: {surface_low}; color: {accent_light};
    border: none; border-bottom: 1px solid rgba({border_rgb}, {border_alpha});
    padding: 6px; font-weight: 700; font-size: 9pt; letter-spacing: 1px;
}}

QScrollBar:vertical   {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:vertical   {{ background: rgba({accent_rgb},120); border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:horizontal {{ background: rgba({accent_rgb},120); border-radius: 4px; min-width: 24px; }}
QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {{ background: {accent_light}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; height: 0; }}

QLabel[role="header"]  {{ color: {accent_light}; font-size: 22pt; font-weight: 700; letter-spacing: -0.5px; }}
QLabel[role="caption"] {{ color: {text_dim}; font-size: 9pt; letter-spacing: 1px; font-weight: 700; }}

QLabel[card="metric"] {{
    background-color: rgba({card_bg_rgb}, {card_bg_alpha});
    border: 1px solid rgba({border_rgb}, {border_alpha});
    border-radius: 16px; padding: 12px;
    color: {text}; font-size: 18pt; font-weight: 600;
}}
QLabel[card="metric"][severity="ok"]   {{ color: {secondary}; }}
QLabel[card="metric"][severity="warn"] {{ color: #ffd166; }}
QLabel[card="metric"][severity="hot"]  {{ color: {error}; }}

QLabel[card="info"] {{
    background-color: rgba({card_bg_rgb}, 160);
    border: 1px solid rgba({border_rgb}, 18);
    border-radius: 14px; padding: 10px 14px;
    color: {text_dim}; font-size: 11pt;
}}
"""

DEFAULT_THEME_QSS = QSS_TEMPLATE.format(**THEMES['violet'])


def apply_app_theme(app: 'QApplication', theme_name: Optional[str] = None):
    """Применить тему оформления. Если theme_name=None — читает из config.json."""
    try:
        if app is None:
            return
        apply_design_font(app)
        if theme_name is None:
            try:
                cfg_path = os.path.join(os.path.dirname(__file__), 'config.json')
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        theme_name = data.get('theme', 'violet')
            except Exception:
                theme_name = None
            if theme_name is None:
                theme_name = 'violet'
        applied = set_active_theme(theme_name)
        # Если есть полностью настроенный theme.qss для violet — используем его как «эталон»
        if applied == 'violet':
            theme_path = os.path.join(os.path.dirname(__file__), 'theme.qss')
            if os.path.exists(theme_path):
                try:
                    with open(theme_path, 'r', encoding='utf-8') as f:
                        app.setStyleSheet(f.read())
                        return
                except Exception:
                    pass
        app.setStyleSheet(QSS_TEMPLATE.format(**_active_palette))
    except Exception:
        try:
            if app is not None:
                app.setStyleSheet(DEFAULT_THEME_QSS)
        except Exception:
            pass

def apply_windows_backdrop(widget: 'QWidget'):
    try:
        if not ENABLE_GLASS_BACKDROP:
            return
        if os.name != 'nt':
            return
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
        is_main_window = False
        try:
            is_main_window = widget.objectName() == "mainWindow"
        except Exception:
            is_main_window = False

        # MainWindow is rounded by Qt per-pixel alpha; DWM rounding/backdrop can leak a white corner.
        try:
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_DONOTROUND = 1
            DWMWCP_ROUND = 2
            corner_pref = ctypes.c_int(DWMWCP_DONOTROUND if is_main_window else DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), ctypes.c_int(DWMWA_WINDOW_CORNER_PREFERENCE), ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))
        except Exception:
            pass

        # Windows 11 can add a bright native border around frameless rounded windows.
        # Disable it so only our antialiased Qt-painted radius is visible.
        try:
            DWMWA_BORDER_COLOR = 34
            DWMWA_COLOR_NONE = 0xFFFFFFFE
            border_color = ctypes.c_uint(DWMWA_COLOR_NONE)
            dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), ctypes.c_int(DWMWA_BORDER_COLOR), ctypes.byref(border_color), ctypes.sizeof(border_color))
        except Exception:
            pass

        if is_main_window:
            return

        # Try Mica (Windows 11)
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_MAINWINDOW = 2
        value = ctypes.c_int(DWMSBT_MAINWINDOW)
        hr = dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), ctypes.c_int(DWMWA_SYSTEMBACKDROP_TYPE), ctypes.byref(value), ctypes.sizeof(value))
        if hr == 0:
            return

        # Fallback: Acrylic blur (Win10/11)
        class ACCENTPOLICY(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int), ("GradientColor", ctypes.c_int), ("AnimationId", ctypes.c_int)]
        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [("Attrib", ctypes.c_int), ("pvData", ctypes.c_void_p), ("cbData", ctypes.c_size_t)]
        WCA_ACCENT_POLICY = 19
        ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
        # ABGR color with alpha in highest byte. 0x00000000 = fully transparent (no tint, pure blur)
        gradient_color = 0x00000000
        policy = ACCENTPOLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 0, gradient_color, 0)
        data = WINDOWCOMPOSITIONATTRIBDATA(WCA_ACCENT_POLICY, ctypes.addressof(policy), ctypes.sizeof(policy))
        # SetWindowCompositionAttribute
        SWCA = getattr(user32, 'SetWindowCompositionAttribute', None)
        if SWCA:
            SWCA(wintypes.HWND(hwnd), ctypes.byref(data))
    except Exception:
        pass


ENABLE_GLASS_BACKDROP = True  # NEBULA CONTROL: dark + glass backdrop

# ─────────────────── Глобальный перехватчик логов ───────────────────
class _LogSignalEmitter(QObject):
    new_line = Signal(str)

_log_emitter = _LogSignalEmitter()
_log_lines: collections.deque = collections.deque(maxlen=2000)
_log_unread: int = 0
_log_lock = threading.Lock()


class _LogCapture:
    """Перехватывает sys.stdout / sys.stderr и сохраняет строки в глобальный буфер."""
    def __init__(self, original):
        self._original = original

    def write(self, text: str):
        global _log_unread
        if self._original:
            try:
                self._original.write(text)
            except Exception:
                pass
        text = text or ""
        stripped = text.strip()
        if stripped:
            ts = time.strftime("%H:%M:%S")
            line = f"[{ts}] {stripped}"
            with _log_lock:
                _log_lines.append(line)
                _log_unread += 1
            try:
                _log_emitter.new_line.emit(line)
            except Exception:
                pass

    def flush(self):
        if self._original:
            try:
                self._original.flush()
            except Exception:
                pass

    def fileno(self):
        if self._original:
            try:
                return self._original.fileno()
            except Exception:
                pass
        raise io.UnsupportedOperation("fileno")

    def isatty(self):
        return False


def _install_log_capture():
    """Устанавливает перехват sys.stdout и sys.stderr."""
    sys.stdout = _LogCapture(sys.__stdout__)
    sys.stderr = _LogCapture(sys.__stderr__)
# ────────────────────────────────────────────────────────────────────


# Helper mixin: drag-to-move for frameless windows and subtle drop shadow
class FramelessWindowMixin:
    _dragging: bool = False
    _drag_pos = None
    _fw_filter = None

    class _FramelessFilter(QObject):
        def __init__(self, parent):
            super().__init__(parent)
            self._parent = parent

        def eventFilter(self, obj, event):  # type: ignore[override]
            try:
                if obj is self._parent:
                    t = event.type()
                    if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                        # start drag only when background area clicked
                        w = cast(Any, self._parent)
                        child = w.childAt(event.position().toPoint())
                        allow = False
                        try:
                            # Allow drag if click on empty area or on our background frame
                            if child is None:
                                allow = True
                            else:
                                allow = getattr(child, 'objectName', lambda: '')() == 'dialogCard'
                        except Exception:
                            allow = False
                        if allow:
                            w._dragging = True
                            w._drag_pos = event.globalPosition().toPoint() - w.frameGeometry().topLeft()
                            return True
                    elif t == QEvent.Type.MouseMove and getattr(self._parent, "_dragging", False) and (event.buttons() & Qt.MouseButton.LeftButton):
                        w = cast(Any, self._parent)
                        w.move(event.globalPosition().toPoint() - (w._drag_pos or event.globalPosition().toPoint()))
                        return True
                    elif t == QEvent.Type.MouseButtonRelease and getattr(self._parent, "_dragging", False):
                        w = cast(Any, self._parent)
                        w._dragging = False
                        return True
            except Exception:
                pass
            return False

    def enable_frameless_drag(self):
        try:
            if self._fw_filter is None:
                w = cast(Any, self)
                self._fw_filter = FramelessWindowMixin._FramelessFilter(w)
                w.installEventFilter(self._fw_filter)
        except Exception:
            pass

    def apply_drop_shadow(self, blur: int = 48, y_offset: int = 12, alpha: int = 77, target: Any | None = None):
        try:
            w = cast(Any, target if target is not None else self)
            effect = QGraphicsDropShadowEffect(w)
            effect.setBlurRadius(blur)
            effect.setOffset(0, y_offset)
            effect.setColor(QColor(0, 0, 0, max(0, min(255, alpha))))
            w.setGraphicsEffect(effect)
        except Exception:
            pass

# BLE imports
try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
    BLE_AVAILABLE = True
except ImportError:
    BleakClient = None
    BleakScanner = None
    BleakError = Exception
    BLE_AVAILABLE = False

# Serial imports
try:
    import serial as pyserial
    SERIAL_AVAILABLE = True
    try:
        from serial.tools import list_ports as serial_list_ports
    except ImportError:
        serial_list_ports = None  # type: ignore[assignment]
except ImportError:
    pyserial = None  # type: ignore[assignment]
    serial_list_ports = None  # type: ignore[assignment]
    SERIAL_AVAILABLE = False


def ensure_serial_backend() -> bool:
    global pyserial, serial_list_ports, SERIAL_AVAILABLE
    if SERIAL_AVAILABLE and pyserial is not None:
        return True

    def _inject_project_venv_sitepackages() -> None:
        try:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(app_dir)
            venv_lib = os.path.join(project_root, ".venv", "Lib")
            if not os.path.isdir(venv_lib):
                return
            candidates = []
            for name in os.listdir(venv_lib):
                if name.lower().startswith("site-packages"):
                    candidates.append(os.path.join(venv_lib, name))
            for path in candidates:
                if os.path.isdir(path) and path not in sys.path:
                    sys.path.append(path)
        except Exception:
            pass

    try:
        pyserial = importlib.import_module("serial")  # type: ignore[assignment]
        SERIAL_AVAILABLE = True
        try:
            serial_list_ports = importlib.import_module("serial.tools.list_ports")  # type: ignore[assignment]
        except Exception:
            serial_list_ports = None  # type: ignore[assignment]
        return True
    except Exception as e:
        _inject_project_venv_sitepackages()
        try:
            pyserial = importlib.import_module("serial")  # type: ignore[assignment]
            SERIAL_AVAILABLE = True
            try:
                serial_list_ports = importlib.import_module("serial.tools.list_ports")  # type: ignore[assignment]
            except Exception:
                serial_list_ports = None  # type: ignore[assignment]
            return True
        except Exception:
            pass
        SERIAL_AVAILABLE = False
        pyserial = None  # type: ignore[assignment]
        serial_list_ports = None  # type: ignore[assignment]
        try:
            print(f"USB serial backend unavailable: {e} (python: {sys.executable})")
        except Exception:
            pass
        return False

# Глобальные переменные
tx_cmd_queue = queue.Queue()
global_pump_hours = None
_rpm_lock = threading.Lock()
_rpm1 = 0
_rpm2 = 0
_water_lock = threading.Lock()
_water_temp = "--"
_water_last_ts = 0.0
_loop_status_lock = threading.Lock()
_loop_status_code = 0  # default to disabled until first read; -1=unknown, 1=connected, 2=broken
_fan_curve = [{'s': 100.0}]
_last_preset_name = '--'
_ble_last_address = None

# Константы
DEVICE_NAME = "PROEKT1"
SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
CFG_CHAR_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
LED_CHAR_UUID = "0000ffe3-0000-1000-8000-00805f9b34fb"
PUMP_CFG_CHAR_UUID = "0000ffe4-0000-1000-8000-00805f9b34fb"
RPM_CHAR_UUID = "0000ffe5-0000-1000-8000-00805f9b34fb"
HOURS_CHAR_UUID = "0000ffe6-0000-1000-8000-00805f9b34fb"
WATER_CHAR_UUID = "0000ffe7-0000-1000-8000-00805f9b34fb"
CONTROL_CHAR_UUID = "0000ffe9-0000-1000-8000-00805f9b34fb"
LOOP_STAT_CHAR_UUID = "0000ffea-0000-1000-8000-00805f9b34fb"  # петля защиты (статус)

LED_STRIP_LEDS = 20  # должно совпадать с прошивкой (LED_STRIP_LENGTH)
# Минимальный полезный уровень яркости (5% от 255 =~13). Значение 0 означает «выключить ленту».
LED_MIN_BRIGHT = 13

def _set_rpm(r1, r2, flags, src=""):
    global _rpm1, _rpm2
    with _rpm_lock:
        _rpm1 = r1
        _rpm2 = r2
    try:
        global _rpm_flags
        _rpm_flags = int(flags)
    except Exception:
        pass
    print(f"RPM from {src}: {r1}, {r2}")

def _build_tt_ble(cpu_temp, gpu_temp):
    return struct.pack('<ii', cpu_temp, gpu_temp)

def _build_tt_usb(cpu_temp, gpu_temp):
    return b'TT' + struct.pack('<ii', cpu_temp, gpu_temp)

def _build_lx_usb(mode, brightness, r, g, b, custom_colors=None):
    """Build LX packet for USB transport matching firmware parser:
    Custom (mode=4): header 'LX'<ver=1><mode><brightness> + 20*RGB bytes
    Gradient (mode=5): header 'LX'<ver=1><mode><brightness> + 7 bytes (startRGB,endRGB,speed)
    Solid/other modes: header 'LX'<ver=1><mode><brightness><r><g><b>
    """
    if custom_colors is not None:
        # Preserve user colors exactly (allow all-black)
        return b'LX' + struct.pack('<BBB', 1, mode, brightness) + custom_colors
    return b'LX' + struct.pack('<BBBBBB', 1, mode, brightness, r, g, b)

def _build_ctrl_usb(cmd: str) -> bytes:
    # Control packets are simple 2-byte ASCII commands
    if cmd == 'PG':
        return b'PG'
    if cmd == 'ST':
        return b'ST'
    if cmd == 'SP':
        return b'SP'
    raise ValueError('Unknown control cmd')

# Пути
LHM_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

# Классы транспорта
class StatusEmitter(QObject):
    signal = Signal(str)

class BLETempSender(threading.Thread):
    def __init__(self, get_temps_func, update_status_func):
        super().__init__()
        self.get_temps = get_temps_func
        self.update_status = update_status_func
        self.emitter = StatusEmitter()
        self.stop_flag = False
        self.urgent_purge = False
        self._purge_done = threading.Event()

    def stop(self):
        self.stop_flag = True

    async def _find_device(self):
        if not BLE_AVAILABLE:
            print("BLE: модуль bleak не доступен")
            return None
        print("BLE: запуск сканирования устройств...")
        try:
            if not BLE_AVAILABLE or BleakScanner is None:
                print("BLE: BleakScanner не доступен")
                return None
            devices = await BleakScanner.discover(timeout=8.0)
            print(f"BLE: найдено устройств: {len(devices)}")
            for idx, d in enumerate(devices):
                # rssi и uuids доступны напрямую в bleak >=0.20.0
                rssi = getattr(d, 'rssi', None)
                uuids = getattr(d, 'uuids', None)
                if uuids is None:
                    uuids = getattr(d, 'metadata', {}).get('uuids', [])
                print(f"  [{idx}] {d.name} | {d.address} | RSSI={rssi} | uuids={uuids}")
            # Сначала ищем по имени
            for d in devices:
                if d.name and DEVICE_NAME in d.name:
                    print(f"BLE: найдено устройство по имени: {d.name} ({d.address})")
                    return d
            # Затем ищем по UUID сервиса
            for d in devices:
                uuids = getattr(d, 'uuids', None)
                if uuids is None:
                    uuids = getattr(d, 'metadata', {}).get('uuids', [])
                if uuids:
                    for u in uuids:
                        if SERVICE_UUID.lower() in u.lower():
                            print(f"BLE: найдено устройство по UUID: {d.name} ({d.address})")
                            return d
            print("BLE: подходящее устройство не найдено")
            return None
        except Exception as e:
            print(f"BLE: ошибка сканирования: {e}")
            return None

    async def _connect_and_send(self, address):
        if not BLE_AVAILABLE or BleakClient is None:
            print("BLE: BleakClient не доступен")
            return False
        try:
            async with BleakClient(address, timeout=10.0) as client:
                if not client.is_connected:
                    return False
                self.emitter.signal.emit("BLE: Подключено")
                # Подписка на уведомления статуса петли (мгновенные обновления UI)
                try:
                    def _on_loop_notify(sender: int, data: bytearray):
                        try:
                            code = int(data[0]) if data and len(data) >= 1 else -1
                        except Exception:
                            code = -1
                        if code != -1:
                            with _loop_status_lock:
                                global _loop_status_code
                                _loop_status_code = code
                            # Сообщение в UI-поток, чтобы обновить немедленно
                            self.emitter.signal.emit(f"LOOP:{code}")
                    await client.start_notify(LOOP_STAT_CHAR_UUID, _on_loop_notify)
                except Exception as e:
                    print(f"BLE: не удалось подписаться на LOOP notify: {e}")
                # Сохраняем текущий локальный статус; устройство синхронизируем отдельной командой LP
                while not self.stop_flag:
                    # Urgent purge — немедленная отправка PG в обход очереди
                    if self.urgent_purge:
                        try:
                            await client.write_gatt_char(CONTROL_CHAR_UUID, b'PG', response=False)
                            print("BLE: urgent purge PG sent")
                        except Exception as e:
                            print(f"BLE: urgent purge error: {e}")
                        self.urgent_purge = False
                        self._purge_done.set()
                    # Очередь команд
                    try:
                        while not tx_cmd_queue.empty():
                            kind, payload = tx_cmd_queue.get_nowait()
                            try:
                                if kind == "fan_curve":
                                    print(f"Sending fan curve, len={len(payload)}")
                                    await client.write_gatt_char(CFG_CHAR_UUID, payload, response=False)
                                elif kind == "pump_curve":
                                    print(f"Sending pump curve, len={len(payload)}")
                                    await client.write_gatt_char(PUMP_CFG_CHAR_UUID, payload, response=False)
                                elif kind == "hours_write":
                                    # payload may be (blob, force); BLE ignores force
                                    blob = payload[0] if isinstance(payload, tuple) else payload
                                    print(f"Sending pump hours, len={len(blob)}")
                                    await client.write_gatt_char(HOURS_CHAR_UUID, blob, response=False)
                                elif kind == "led":
                                    print(f"Sending LED command, len={len(payload)}")
                                    # Use write-with-response to allow long writes (custom colors > 20 bytes)
                                    await client.write_gatt_char(LED_CHAR_UUID, payload, response=True)
                                elif kind == "ctrl":
                                    print(f"Sending control cmd, len={len(payload)}")
                                    await client.write_gatt_char(CONTROL_CHAR_UUID, payload, response=False)
                                elif kind == "read_loop_status_once":
                                    try:
                                        data = await client.read_gatt_char(LOOP_STAT_CHAR_UUID)
                                        if data and len(data) >= 1:
                                            code = int(data[0])
                                            with _loop_status_lock:
                                                global _loop_status_code
                                                _loop_status_code = code
                                            self.emitter.signal.emit(f"LOOP:{code}")
                                    except Exception:
                                        pass
                            except Exception as e:
                                print(f"BLE cmd error: {e}")
                    except queue.Empty:
                        pass
                    # Отправка температур
                    cpu, gpu = self.get_temps()
                    if cpu != "--" and gpu != "--":
                        data = struct.pack('<ii', int(cpu), int(gpu))
                        try:
                            await client.write_gatt_char(CHAR_UUID, data, response=False)
                        except Exception as e:
                            self.emitter.signal.emit(f"BLE: ошибка отправки {e}")
                            return False
                    # Чтение RPM
                    try:
                        data = await client.read_gatt_char(RPM_CHAR_UUID)
                        rpm1, rpm2, flags = struct.unpack('<iiI', data)
                        _set_rpm(rpm1, rpm2, flags, "BLE")
                    except Exception:
                        pass
                    # Чтение температуры воды
                    try:
                        data = await client.read_gatt_char(WATER_CHAR_UUID)
                        (water_c,) = struct.unpack('<i', data)
                        with _water_lock:
                            global _water_temp
                            _water_temp = str(int(water_c))
                            global _water_last_ts
                            _water_last_ts = time.time()
                    except Exception:
                        pass
                    # Чтение моточасов
                    try:
                        data = await client.read_gatt_char(HOURS_CHAR_UUID)
                        global global_pump_hours
                        global_pump_hours = data
                    except Exception:
                        pass
                    # Статус петли теперь приходит по notify; периодическое чтение необязательно
                    for _ in range(10):
                        if self.stop_flag or self.urgent_purge:
                            break
                        await asyncio.sleep(0.1)
        except Exception as e:
            self.emitter.signal.emit(f"BLE: ошибка {e}")
            return False
        return True

    def run(self):
        try:
            asyncio.run(self._main())
        except Exception as e:
            print(f"BLE thread error: {e}")

    async def _main(self):
        try:
            while not self.stop_flag:
                dev = await self._find_device()
                if not dev:
                    self.emitter.signal.emit("BLE: устройство не найдено, повтор")
                    await asyncio.sleep(5)
                    continue
                success = await self._connect_and_send(dev.address)
                if not success:
                    await asyncio.sleep(2)
        except Exception as e:
            print(f"BLE main error: {e}")

class USBTempSender(threading.Thread):
    def __init__(self, get_temps_func, update_status_func):
        super().__init__()
        self.get_temps = get_temps_func
        self.update_status = update_status_func
        self.emitter = StatusEmitter()
        self.stop_flag = False
        self._buf = bytearray()
        self.ser: Optional[Any] = None
        self.last_port = None
        self._requested_hours = False

    def stop(self):
        self.stop_flag = True
        self._close_serial()

    def _close_serial(self):
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.last_port = None

    def _score_port_info(self, info: Any) -> int:
        score = 0
        try:
            desc_parts = [
                str(getattr(info, 'description', '') or ''),
                str(getattr(info, 'manufacturer', '') or ''),
                str(getattr(info, 'product', '') or ''),
                str(getattr(info, 'name', '') or ''),
            ]
            desc = ' '.join(desc_parts).lower()
        except Exception:
            desc = ''
        for kw in ("proekt", "usb-serial", "usb serial", "cp210", "silicon labs", "ch340", "ftdi", "uart"):
            if kw in desc:
                score += 2
        for bad in ("bluetooth", "nfc", "gps", "modem"):
            if bad in desc:
                score -= 2
        try:
            vid = getattr(info, 'vid', None)
            if vid in (0x10C4, 0x1A86, 0x0403, 0x2341):
                score += 2
        except Exception:
            pass
        return score

    def _auto_detect_ports(self) -> List[str]:
        ports: List[str] = []
        seen = set()
        debug_rows: List[str] = []
        if serial_list_ports:
            try:
                port_infos = list(serial_list_ports.comports())  # type: ignore[call-arg]
            except Exception:
                port_infos = []
            scored = []
            for info in port_infos:
                device = str(getattr(info, 'device', '') or '').upper()
                if not device:
                    continue
                if device in seen:
                    continue
                seen.add(device)
                score = self._score_port_info(info)
                desc = str(getattr(info, 'description', '') or '')
                scored.append((score, device, desc))
            scored.sort(key=lambda item: (-item[0], item[1]))
            ports.extend([dev for _, dev, _ in scored])
            if scored:
                for score, dev, desc in scored:
                    debug_rows.append(f"{dev}: score={score} desc='{desc}'")
        if not ports:
            # Fallback heuristic range
            for i in range(3, 11):
                name = f"COM{i}"
                if name not in seen:
                    seen.add(name)
                    ports.append(name)
                    debug_rows.append(f"{name}: score=fallback desc='N/A'")
        try:
            if debug_rows:
                print("USB auto-detect: кандидаты:\n  " + "\n  ".join(debug_rows))
        except Exception:
            pass
        return ports

    def open_serial(self):
        if not ensure_serial_backend():
            self.emitter.signal.emit(f"USB: библиотека pyserial не установлена (python: {sys.executable})")
            return False
        if self.ser and getattr(self.ser, "is_open", False):
            return True

        ports_to_try = self._auto_detect_ports()
        if self.last_port:
            ports_to_try = [self.last_port] + [p for p in ports_to_try if p != self.last_port]
        # Deduplicate while preserving order
        seen_ports: set[str] = set()
        ordered_ports: List[str] = []
        for port in ports_to_try:
            norm = port.strip().upper()
            if norm and norm not in seen_ports:
                seen_ports.add(norm)
                ordered_ports.append(norm)
        ports_to_try = ordered_ports

        if not ports_to_try:
            self.emitter.signal.emit("USB: COM-порты не найдены. Подключите устройство по USB.")
            return False

        preview = ", ".join(ports_to_try[:3])
        suffix = "…" if len(ports_to_try) > 3 else ""
        self.emitter.signal.emit(f"USB: авто-поиск портов ({preview}{suffix})")

        self._close_serial()
        for port in ports_to_try:
            if self._try_open_port(port):
                return True

        self.emitter.signal.emit("USB: устройство не найдено (проверьте кабель)")
        return False

    def _try_open_port(self, port: str) -> bool:
        port = port.strip()
        if not port:
            return False
        self.emitter.signal.emit(f"USB: Открытие {port}...")
        try:
            if not ensure_serial_backend() or pyserial is None:
                return False
            self.ser = pyserial.Serial(
                port=port,
                baudrate=115200,
                timeout=0.2,
                write_timeout=1,
                rtscts=False,
                dsrdtr=False,
                xonxoff=False
            )
            try:
                self.ser.setDTR(False)  # type: ignore[attr-defined]
                self.ser.setRTS(False)  # type: ignore[attr-defined]
            except Exception:
                pass
            time.sleep(0.25)
            try:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            except Exception:
                pass
            self.last_port = port
            self.emitter.signal.emit(f"USB: Подключено ({port})")
            self._requested_hours = False
            return True
        except Exception as e:
            msg = str(e)
            if "Access is denied" in msg or "PermissionError" in msg:
                self.emitter.signal.emit(f"USB: Порт {port} занят другим приложением.")
            else:
                self.emitter.signal.emit(f"USB: Ошибка порта {port}: {msg}")
            self._close_serial()
            return False

    @staticmethod
    def _is_valid_rp(rpm1: int, rpm2: int, flags: int) -> bool:
        return (0 <= rpm1 <= 30000) and (0 <= rpm2 <= 30000) and (0 <= flags <= 3)

    def _parse_rp_buffer(self):
        while True:
            idx = self._buf.find(b'RP')
            if idx == -1:
                if len(self._buf) > 16384:
                    self._buf = self._buf[-4096:]
                break
            if len(self._buf) - idx < 14:
                if idx > 0 and idx > 8192:
                    del self._buf[:idx]
                break
            payload = bytes(self._buf[idx+2:idx+14])
            try:
                rpm1, rpm2, flags = struct.unpack('<iiI', payload)
                if self._is_valid_rp(rpm1, rpm2, flags):
                    _set_rpm(rpm1, rpm2, flags, src="USB")
                    del self._buf[:idx+14]
                    continue
                else:
                    del self._buf[idx:idx+1]
                    continue
            except Exception:
                del self._buf[idx:idx+1]
                continue

    def _parse_wt_buffer(self):
        # Parse 'WT' + <i> water temperature packets
        while True:
            idx = self._buf.find(b'WT')
            if idx == -1:
                break
            if len(self._buf) - idx < 6:
                # not enough data yet
                if idx > 0 and idx > 8192:
                    del self._buf[:idx]
                break
            try:
                (water_c,) = struct.unpack('<i', self._buf[idx+2:idx+6])
                with _water_lock:
                    global _water_temp
                    _water_temp = str(int(water_c))
                    global _water_last_ts
                    _water_last_ts = time.time()
                del self._buf[:idx+6]
            except Exception:
                del self._buf[idx:idx+1]
                continue

    def run(self):
        while not self.stop_flag:
            if not self.open_serial():
                time.sleep(2)
                continue

            while not self.stop_flag:
                try:
                    # Отправка команд
                    try:
                        while not tx_cmd_queue.empty():
                            kind, payload = tx_cmd_queue.get_nowait()
                            try:
                                if not self.ser or not getattr(self.ser, "is_open", False):
                                    raise IOError("port closed")
                                # Map commands for USB
                                out: Optional[bytes] = None
                                if kind in ("fan_curve", "pump_curve", "led", "ctrl"):
                                    out = cast(bytes, payload)
                                elif kind == "hours_write":
                                    # payload may be (blob, force)
                                    blob: bytes
                                    force = False
                                    if isinstance(payload, tuple) and len(payload) == 2:
                                        blob, force = payload  # type: ignore[misc]
                                    else:
                                        blob = cast(bytes, payload)
                                    op = b'F' if force else b'W'
                                    out = b'HR' + op + blob
                                else:
                                    # Unknown kind, try raw
                                    out = cast(bytes, payload)
                                if out:
                                    self.ser.write(out)
                                    self.ser.flush()
                            except Exception:
                                try:
                                    tx_cmd_queue.put((kind, payload))
                                except Exception:
                                    pass
                                break
                    except queue.Empty:
                        pass

                    # Отправка температур
                    cpu, gpu = self.get_temps()
                    if cpu != "--" and gpu != "--" and self.ser and getattr(self.ser, "is_open", False):
                        data = _build_tt_usb(int(cpu), int(gpu))
                        try:
                            self.ser.write(data)
                            self.ser.flush()
                        except Exception:
                            pass


                    # Чтение RPM
                    try:
                        if self.ser and getattr(self.ser, "in_waiting", 0) > 0:
                            data = self.ser.read(self.ser.in_waiting or 1)
                            if data:
                                self._buf.extend(data)
                                # First parse any water temp frames
                                self._parse_wt_buffer()
                                self._parse_hr_buffer()
                                self._parse_ls_buffer()
                                self._parse_rp_buffer()
                    except Exception:
                        pass

                    # Request hours once after connect
                    try:
                        if self.ser and getattr(self.ser, "is_open", False) and not self._requested_hours:
                            self.ser.write(b'HRR')
                            self.ser.flush()
                            self._requested_hours = True
                    except Exception:
                        pass

                except Exception:
                    break

                time.sleep(0.1)

            self._close_serial()
            time.sleep(1)

    def send_cmd(self, cmd):
        tx_cmd_queue.put(("fan_curve", cmd))

    def _parse_hr_buffer(self):
        # Parse 'HR' + <blob> where blob is 1+4+8+8 bytes
        blob_len = 1 + 4 + 8 + 8
        frame_len = 2 + blob_len
        while True:
            idx = self._buf.find(b'HR')
            if idx == -1:
                break
            if len(self._buf) - idx < frame_len:
                if idx > 0 and idx > 8192:
                    del self._buf[:idx]
                break
            try:
                blob = bytes(self._buf[idx+2:idx+2+blob_len])
                if len(blob) == blob_len and blob[0] in (1,):
                    # Update global buffer like BLE path
                    global global_pump_hours
                    global_pump_hours = blob
                del self._buf[:idx+frame_len]
            except Exception:
                del self._buf[idx:idx+1]
                continue

    def _parse_ls_buffer(self):
        """Parse 'LS' + <uint8 code> loop status packets from ESP32.
        Codes: 0=disabled, 1=ok(was pause), 2=broken, 3=restored(was running), 4=auto-started."""
        while True:
            idx = self._buf.find(b'LS')
            if idx == -1:
                break
            if len(self._buf) - idx < 3:
                if idx > 0 and idx > 8192:
                    del self._buf[:idx]
                break
            try:
                code = int(self._buf[idx + 2])
                with _loop_status_lock:
                    global _loop_status_code
                    _loop_status_code = code
                self.emitter.signal.emit(f"LOOP:{code}")
                del self._buf[:idx + 3]
            except Exception:
                del self._buf[idx:idx + 1]
                continue


class ConsoleReporter(threading.Thread):
    """Prints a concise CPU/GPU status every 5 seconds to the console."""
    def __init__(self, get_temps_func):
        super().__init__(daemon=True)
        self.get_temps = get_temps_func
        self.stop_flag = False

    def stop(self):
        self.stop_flag = True

    def run(self):
        while not self.stop_flag:
            try:
                cpu, gpu = self.get_temps()
                # Normalize empty values to '--'
                cpu_s = cpu if cpu is not None else '--'
                gpu_s = gpu if gpu is not None else '--'
                # Format as requested: CPU:52°C GPU:46°C
                print(f"CPU:{cpu_s}°C GPU:{gpu_s}°C")
            except Exception:
                print("CPU -- GPU --")
            for _ in range(5):
                if self.stop_flag:
                    break
                time.sleep(1)

# ─── LibreHardwareMonitor — прямая загрузка DLL через pythonnet ──────────────
import threading as _lhm_threading
_lhm_lock = _lhm_threading.Lock()
_lhm_computer = None   # экземпляр Computer из DLL
_lhm_dll_ok = False    # True если DLL загружена успешно
# Кэш температур — обновляется фоновым потоком, читается главным
_cached_cpu: str | None = None
_cached_gpu: str | None = None
_cached_temps_lock = _lhm_threading.Lock()

def _ensure_pawnio_installed():
    """Устанавливает PawnIO kernel driver без GUI, если ещё не установлен. Требует прав администратора."""
    import winreg as _winreg
    _UNINSTALL_KEY = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO'

    def _is_installed():
        try:
            k = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_KEY)
            _winreg.CloseKey(k)
            return True
        except FileNotFoundError:
            return False

    try:
        if _is_installed():
            return True  # уже установлен

        setup_exe = os.path.join(LHM_DIR, 'PawnIO_setup.exe')
        if not os.path.exists(setup_exe):
            print('[PawnIO] PawnIO_setup.exe не найден, пропускаем установку.')
            return False

        import subprocess, time
        r = subprocess.run(
            [setup_exe, '-install', '-silent'],
            capture_output=True, text=True, timeout=60,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        print(f'[PawnIO] setup rc={r.returncode} stdout={r.stdout.strip()!r} stderr={r.stderr.strip()!r}')
        time.sleep(1.0)

        if _is_installed():
            print('[PawnIO] Установлен успешно.')
            return True
        print('[PawnIO] Установка не подтверждена реестром.')
        return False
    except Exception as e:
        print(f'[PawnIO] Ошибка установки: {e}')
        return False

def _open_lhm_dll():
    """Загружает LibreHardwareMonitorLib.dll и открывает Computer."""
    global _lhm_computer, _lhm_dll_ok
    try:
        import clr  # pythonnet
        dll_path = os.path.join(LHM_DIR, 'LibreHardwareMonitorLib.dll')
        if not os.path.exists(dll_path):
            print(f'[LHM] DLL не найдена: {dll_path}')
            return False
        if LHM_DIR not in sys.path:
            sys.path.insert(0, LHM_DIR)
        clr.AddReference('LibreHardwareMonitorLib')
        from LibreHardwareMonitor.Hardware import Computer
        _ensure_pawnio_installed()
        computer = Computer()
        computer.IsCpuEnabled = True
        computer.IsGpuEnabled = True
        computer.Open()
        _lhm_computer = computer
        _lhm_dll_ok = True
        print('[LHM] DLL загружена, Computer открыт.')
        return True
    except Exception as e:
        print(f'[LHM] Ошибка загрузки DLL: {e}')
        return False

def _close_lhm_dll():
    """Закрывает Computer и выгружает ресурсы."""
    global _lhm_computer, _lhm_dll_ok
    if _lhm_computer is not None:
        try:
            _lhm_computer.Close()
            print('[LHM] Computer закрыт.')
        except Exception:
            pass
    _lhm_computer = None
    _lhm_dll_ok = False

def _read_temps_from_dll():
    """Считывает CPU/GPU температуры напрямую из DLL. Возвращает (cpu|None, gpu|None)."""
    with _lhm_lock:
        if not _lhm_dll_ok or _lhm_computer is None:
            return None, None
        try:
            from LibreHardwareMonitor.Hardware import SensorType
            cpu_prio = None   # (priority, value)
            gpu_prio = None   # (priority, value)

            for hw in _lhm_computer.Hardware:
                hw.Update()
                hw_type = str(hw.HardwareType)
                is_cpu = 'Cpu' in hw_type
                is_gpu = 'Gpu' in hw_type

                # Собираем все датчики (включая subhardware)
                sensors = list(hw.Sensors)
                for sub in hw.SubHardware:
                    sub.Update()
                    sensors.extend(list(sub.Sensors))

                for sensor in sensors:
                    if sensor.SensorType != SensorType.Temperature:
                        continue
                    if sensor.Value is None:
                        continue
                    val = float(sensor.Value)
                    name = sensor.Name.lower()

                    if is_cpu:
                        # Приоритет: package(0) > core max(1) > core average(2) > tdie/tctl(3) > прочее(9)
                        if 'distance' in name or 'tjmax' in name.replace(' ', ''):
                            continue  # не настоящая температура
                        if 'package' in name:
                            prio = 0
                        elif 'core max' in name or 'cpu core max' in name:
                            prio = 1
                        elif 'core average' in name:
                            prio = 2
                        elif 'tdie' in name or 'tctl' in name:
                            prio = 3
                        else:
                            prio = 9
                        if cpu_prio is None or prio < cpu_prio[0]:
                            cpu_prio = (prio, val)

                    if is_gpu:
                        # Hot spot предпочтительнее, иначе первый попавшийся
                        if 'hot spot' in name or 'hotspot' in name:
                            gpu_prio = (0, val)
                        elif gpu_prio is None:
                            gpu_prio = (1, val)

            cpu = str(int(cpu_prio[1])) if cpu_prio is not None else None
            gpu = str(int(gpu_prio[1])) if gpu_prio is not None else None
            return cpu, gpu
        except Exception as e:
            print(f'[LHM] Ошибка чтения сенсоров: {e}')
            return None, None

def get_current_temps():
    with _cached_temps_lock:
        return _cached_cpu or '--', _cached_gpu or '--'

def _lhm_poll_loop():
    """Фоновый поток: инициализирует LHM, затем опрашивает сенсоры каждые 2 с и кэширует результат."""
    global _cached_cpu, _cached_gpu
    import time as _time
    _open_lhm_dll()  # инициализация целиком в фоновом потоке
    while True:
        cpu, gpu = _read_temps_from_dll()
        with _cached_temps_lock:
            _cached_cpu = cpu
            _cached_gpu = gpu
        _time.sleep(2.0)


def start_lhm():
    """Запускает фоновый поток инициализации LHM и опроса температур."""
    t = _lhm_threading.Thread(target=_lhm_poll_loop, daemon=True, name='lhm-poll')
    t.start()
    return None

class CurveEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 400)
        self.fan_points = []  # list of (t, s)
        self.pump_points = []
        self.selected = None
        self.selected_curve = None  # "fan" or "pump"
        self.current_curve = "fan"  # for adding points
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def setFanPoints(self, points):
        self.fan_points = sorted(points, key=lambda x: x[0])
        self.update()

    def setPumpPoints(self, points):
        self.pump_points = sorted(points, key=lambda x: x[0])
        self.update()

    def getFanPoints(self):
        return self.fan_points[:]

    def getPumpPoints(self):
        return self.pump_points[:]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        margin = 40
        graph_rect = QRectF(margin, margin, rect.width() - 2*margin, rect.height() - 2*margin)
        # Оси
        painter.setPen(QPen(QColor(128, 128, 128), 2))
        painter.drawLine(int(graph_rect.left()), int(graph_rect.bottom()), int(graph_rect.right()), int(graph_rect.bottom()))  # x
        painter.drawLine(int(graph_rect.left()), int(graph_rect.bottom()), int(graph_rect.left()), int(graph_rect.top()))  # y
        # Шкалы
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QPen(QColor(179, 179, 179)))
        for t in range(40, 111, 10):
            x = graph_rect.left() + (t - 40) / 70 * graph_rect.width()
            painter.drawLine(int(x), int(graph_rect.bottom()), int(x), int(graph_rect.bottom() + 5))
            painter.drawText(int(x - 10), int(graph_rect.bottom() + 15), str(t))
        for s in range(30, 101, 10):
            y = graph_rect.bottom() - ((s - 30) / 70) * graph_rect.height()
            painter.drawLine(int(graph_rect.left() - 5), int(y), int(graph_rect.left()), int(y))
            painter.drawText(int(graph_rect.left() - 25), int(y + 5), str(s))
        # Подписи осей
        painter.drawText(int(graph_rect.right() - 50), int(graph_rect.bottom() + 30), "температуры")
        painter.drawText(int(graph_rect.left() - 30), int(graph_rect.top() - 10), "обороты")
        # Сетка
        painter.setPen(QPen(QColor(128, 128, 128), 1))
        for t in range(40, 111, 10):
            x = graph_rect.left() + (t - 40) / 70 * graph_rect.width()
            painter.drawLine(int(x), int(graph_rect.top()), int(x), int(graph_rect.bottom()))
        for s in range(30, 101, 10):
            y = graph_rect.bottom() - ((s - 30) / 70) * graph_rect.height()
            painter.drawLine(int(graph_rect.left()), int(y), int(graph_rect.right()), int(y))
        # Кривые
        # Fan curve - purple
        if len(self.fan_points) > 1:
            painter.setPen(QPen(QColor(124, 77, 255), 3))
            path = QPainterPath()
            for i, (t, s) in enumerate(self.fan_points):
                x = graph_rect.left() + (t - 40) / 70 * graph_rect.width()
                y = graph_rect.bottom() - ((s - 30) / 70) * graph_rect.height()
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.drawPath(path)
        # Pump curve - cyan
        if len(self.pump_points) > 1:
            painter.setPen(QPen(QColor(0, 255, 255), 3))
            path = QPainterPath()
            for i, (t, s) in enumerate(self.pump_points):
                x = graph_rect.left() + (t - 40) / 70 * graph_rect.width()
                y = graph_rect.bottom() - ((s - 30) / 70) * graph_rect.height()
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.drawPath(path)
        # Точки
        # Fan points
        for i, (t, s) in enumerate(self.fan_points):
            x = graph_rect.left() + (t - 40) / 70 * graph_rect.width()
            y = graph_rect.bottom() - ((s - 30) / 70) * graph_rect.height()
            color = QColor(124, 77, 255)
            painter.setPen(QPen(color, 2))
            fill_color = QColor(Qt.GlobalColor.white) if not (self.selected == i and self.selected_curve == "fan") else color
            painter.setBrush(QBrush(fill_color))
            radius = 8 if self.selected == i and self.selected_curve == "fan" else 6
            painter.drawEllipse(QPointF(x, y), radius, radius)
        # Pump points
        for i, (t, s) in enumerate(self.pump_points):
            x = graph_rect.left() + (t - 40) / 70 * graph_rect.width()
            y = graph_rect.bottom() - ((s - 30) / 70) * graph_rect.height()
            color = QColor(0, 255, 255)
            painter.setPen(QPen(color, 2))
            fill_color = QColor(Qt.GlobalColor.white) if not (self.selected == i and self.selected_curve == "pump") else color
            painter.setBrush(QBrush(fill_color))
            radius = 8 if self.selected == i and self.selected_curve == "pump" else 6
            painter.drawEllipse(QPointF(x, y), radius, radius)

        # Draw tooltip for selected point
        if self.selected is not None and self.selected_curve:
            points = self.fan_points if self.selected_curve == "fan" else self.pump_points
            t, s = points[self.selected]
            x = graph_rect.left() + (t - 40) / 70 * graph_rect.width()
            y = graph_rect.bottom() - ((s - 30) / 70) * graph_rect.height()
            text = f"{t:.0f}°C, {s:.0f}%"
            painter.setFont(QFont(design_font_family(), 10, QFont.Weight.Bold))
            painter.setPen(QPen(QColor(255, 255, 255)))
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(text)
            text_height = fm.height()
            # Position: prefer top-right of point
            tx = x + 10
            ty = y - 10
            if tx + text_width > graph_rect.right():
                tx = x - 10 - text_width
            if ty < graph_rect.top() + text_height:
                ty = y + 10 + text_height
            painter.drawText(int(tx), int(ty), text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                # Добавить точку в текущую кривую (определяется radio)
                # Но поскольку radio переключает, и мы редактируем текущую
                # Для простоты, добавлять в обе? Нет, в текущую.
                # Но selected_curve определяет.
                # Для dblclick добавлять в fan или pump в зависимости от radio.
                # Но radio не здесь.
                # Поскольку editor не знает radio, добавить параметр или метод.
                # Для простоты, dblclick добавляет в ближайшую кривую или в обе? Лучше в текущую, но поскольку editor общий, добавить self.current_curve = "fan"
                # В FanPumpCurveDialog: self.editor.current_curve = "fan" if radio_fan else "pump"
                # В on_curve_type_changed.
                points = self.fan_points if self.current_curve == "fan" else self.pump_points
                rect = self.rect()
                margin = 40
                graph_rect = QRectF(margin, margin, rect.width() - 2*margin, rect.height() - 2*margin)
                x = event.position().x()
                y = event.position().y()
                if graph_rect.contains(QPointF(x, y)):
                    t = 40 + (x - graph_rect.left()) / graph_rect.width() * 70
                    s = 30 + (graph_rect.bottom() - y) / graph_rect.height() * 70
                    t = max(40, min(110, t))
                    s = max(30, min(100, s))
                    if len(points) < 10:
                        points.append((t, s))
                        points.sort(key=lambda x: x[0])
                        self.selected = points.index((t, s))
                        self.selected_curve = self.current_curve
                        self.update()
            else:
                # Выбрать точку только из текущей кривой
                rect = self.rect()
                margin = 40
                graph_rect = QRectF(margin, margin, rect.width() - 2*margin, rect.height() - 2*margin)
                x = event.position().x()
                y = event.position().y()
                min_dist = 10
                self.selected = None
                self.selected_curve = None
                pts = self.fan_points if self.current_curve == "fan" else self.pump_points
                for i, (t, s) in enumerate(pts):
                    px = graph_rect.left() + (t - 40) / 70 * graph_rect.width()
                    py = graph_rect.bottom() - ((s - 30) / 70) * graph_rect.height()
                    dist = ((x - px)**2 + (y - py)**2)**0.5
                    if dist < min_dist:
                        min_dist = dist
                        self.selected = i
                        self.selected_curve = self.current_curve
                self.update()

    def mouseMoveEvent(self, event):
        if self.selected is not None and self.selected_curve and event.buttons() & Qt.MouseButton.LeftButton:
            points = self.fan_points if self.selected_curve == "fan" else self.pump_points
            rect = self.rect()
            margin = 40
            graph_rect = QRectF(margin, margin, rect.width() - 2*margin, rect.height() - 2*margin)
            x = event.position().x()
            y = event.position().y()
            t = 40 + (x - graph_rect.left()) / graph_rect.width() * 70
            s = 30 + (graph_rect.bottom() - y) / graph_rect.height() * 70
            t = max(40, min(110, t))
            s = max(30, min(100, s))
            points[self.selected] = (t, s)
            points.sort(key=lambda x: x[0])
            self.selected = points.index((t, s))
            self.update()

    def keyPressEvent(self, event):
        if self.selected is not None and self.selected_curve:
            points = self.fan_points if self.selected_curve == "fan" else self.pump_points
            t, s = points[self.selected]
            step_t = 1
            step_s = 1
            if event.key() == Qt.Key.Key_Left:
                t = max(40, t - step_t)
            elif event.key() == Qt.Key.Key_Right:
                t = min(110, t + step_t)
            elif event.key() == Qt.Key.Key_Up:
                s = min(100, s + step_s)
            elif event.key() == Qt.Key.Key_Down:
                s = max(30, s - step_s)
            elif event.key() == Qt.Key.Key_Delete:
                del points[self.selected]
                self.selected = None
                self.selected_curve = None
                self.update()
                return
            points[self.selected] = (t, s)
            points.sort(key=lambda x: x[0])
            self.selected = points.index((t, s))
            self.update()
        super().keyPressEvent(event)

class FanPumpCurveDialog(QDialog, FramelessWindowMixin):
    def __init__(self, parent=None):
        global _last_preset_name
        super().__init__(parent)
        # Secondary window: frameless
        try:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        except Exception:
            pass
        # Transparent background; draw card frame inside
        if ENABLE_GLASS_BACKDROP:
            try:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            except Exception:
                pass
        # Subtle shadow
        try:
            pass
        except Exception:
            pass
        # Enable drag-to-move on background
        try:
            self.enable_frameless_drag()
        except Exception:
            pass
        self.main_window = parent
        self.setWindowTitle("Настройка кривых PWM")
        # Outer layout and card frame with border + rounded corners
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 20, 20, 20)
        outer_layout.setSpacing(0)
        card = QFrame()
        card.setObjectName("dialogCard")
        card.setStyleSheet("QFrame#dialogCard { background-color: #1e1e1e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; }")
        content_layout = QVBoxLayout(card)
        content_layout.setContentsMargins(40, 40, 40, 40)
        content_layout.setSpacing(10)
        outer_layout.addWidget(card)
        # Apply shadow to the card for correct shape
        try:
            self.apply_drop_shadow(target=card)
        except Exception:
            pass
        self.curves_path = os.path.join(os.path.dirname(__file__), "curves.json")
        # По умолчанию
        self.fan_points = [[40.0, 70.0], [55.0, 80.0], [70.0, 90.0], [90.0, 95.0], [110.0, 100.0]]
        self.pump_points = [[40.0, 50.0], [55.0, 60.0], [70.0, 70.0], [90.0, 75.0], [110.0, 80.0]]
        # Гистерезис (в процентах): по умолчанию 5% для обеих кривых, допустимый диапазон [3..10]
        self.hyst_fan = 5
        self.hyst_pump = 5
        self.source_mode = 2
        self.presets = self.main_window.presets if self.main_window else {"Стандарт": {"fan_curve": self.fan_points[:], "pump_curve": self.pump_points[:]} }
        self.selected_preset = _last_preset_name
        try:
            with open(self.curves_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.fan_points = data.get("fan_curve", self.fan_points)
                self.pump_points = data.get("pump_curve", self.pump_points)
                self.source_mode = data.get("source_mode", self.source_mode)
                self.presets = data.get("presets", self.presets)
                self.selected_preset = data.get("selected_preset", self.selected_preset)
                # Загрузка гистерезиса, с ограничением [3..10]
                self.hyst_fan = max(3, min(10, int(data.get("hyst_fan", self.hyst_fan))))
                self.hyst_pump = max(3, min(10, int(data.get("hyst_pump", self.hyst_pump))))
                _last_preset_name = self.selected_preset
                # Задержки включения/выключения
                v = data.get("delay_on_seconds", None)
                self.delay_on_seconds = int(v) if v is not None else 0
                v = data.get("delay_off_seconds", None)
                self.delay_off_seconds = int(v) if v is not None else 0
        except Exception:
            pass
        # Fallback: если delay не были загружены из curves.json — берём из MainWindow / config.json
        if not hasattr(self, 'delay_on_seconds'):
            self.delay_on_seconds = int(getattr(self.main_window, 'delay_on_seconds', 0))
        if not hasattr(self, 'delay_off_seconds'):
            self.delay_off_seconds = int(getattr(self.main_window, 'delay_off_seconds', 0))
        # Source and radios in one line
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(15)  # Add spacing between elements
        self.radio_fan = QRadioButton("Вентиляторы")
        self.radio_fan.setChecked(True)
        self.radio_pump = QRadioButton("Насосы")
        label_source = QLabel("Отправная точка:")
        label_source.setStyleSheet("color: #FFFFFF; font-size: 14pt;")
        settings_layout.addWidget(self.radio_fan)
        settings_layout.addWidget(self.radio_pump)
        settings_layout.addWidget(label_source)
        self.source_mode_combo = QComboBox()
        self.source_mode_combo.setStyleSheet("QComboBox { font-size: 14pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 32px; height: 40px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid #FFFFFF; margin-right: 8px; } QComboBox:hover { background-color: #3e3e3e; }")
        self.source_mode_combo.addItems(["CPU", "GPU", "MAX"])
        self.source_mode_combo.setCurrentIndex(self.source_mode)
        settings_layout.addWidget(self.source_mode_combo)
        self.radio_fan.setStyleSheet("QRadioButton { color: #FFFFFF; font-size: 14pt; } QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid #FFFFFF; border-radius: 7px; background-color: #1e1e1e; } QRadioButton::indicator:checked { background-color: #800080; }")
        self.radio_pump.setStyleSheet("QRadioButton { color: #FFFFFF; font-size: 14pt; } QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid #FFFFFF; border-radius: 7px; background-color: #1e1e1e; } QRadioButton::indicator:checked { background-color: #00FFFF; }")
        content_layout.addLayout(settings_layout)
        # Гистерезис
        hyst_layout = QHBoxLayout()
        hyst_label = QLabel("Гистерезис (%):")
        hyst_label.setStyleSheet("color: #FFFFFF; font-size: 14pt;")
        hyst_layout.addWidget(hyst_label)
        self.hyst_spin = QSpinBox()
        self.hyst_spin.setRange(3, 10)
        self.hyst_spin.setValue(self.hyst_fan)
        self.hyst_spin.setStyleSheet("QSpinBox { font-size: 14pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 12px; height: 40px; } QSpinBox::up-button, QSpinBox::down-button { width: 22px; }")
        def on_hyst_changed(val:int):
            if self.radio_fan.isChecked():
                self.hyst_fan = int(val)
            else:
                self.hyst_pump = int(val)
        self.hyst_spin.valueChanged.connect(on_hyst_changed)
        hyst_layout.addWidget(self.hyst_spin)
        content_layout.addLayout(hyst_layout)
        # Задержки включения / выключения
        delay_layout = QHBoxLayout()
        delay_label = QLabel("Задержка включения / выключения (сек):")
        delay_label.setStyleSheet("color: #FFFFFF; font-size: 14pt;")
        delay_layout.addWidget(delay_label)
        self.delay_on_combo = QComboBox()
        self.delay_off_combo = QComboBox()
        delay_opts = ["Выкл", "5 сек", "10 сек", "15 сек", "20 сек", "30 сек"]
        self._delay_vals = [0, 5, 10, 15, 20, 30]
        self.delay_on_combo.addItems(delay_opts)
        self.delay_off_combo.addItems(delay_opts)
        self.delay_on_combo.setStyleSheet("QComboBox { font-size: 14pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 32px; height: 40px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid #FFFFFF; margin-right: 8px; } QComboBox:hover { background-color: #3e3e3e; }")
        self.delay_off_combo.setStyleSheet("QComboBox { font-size: 14pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 32px; height: 40px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid #FFFFFF; margin-right: 8px; } QComboBox:hover { background-color: #3e3e3e; }")
        try:
            idx_on = self._delay_vals.index(int(self.delay_on_seconds)) if int(self.delay_on_seconds) in self._delay_vals else 0
        except Exception:
            idx_on = 0
        try:
            idx_off = self._delay_vals.index(int(self.delay_off_seconds)) if int(self.delay_off_seconds) in self._delay_vals else 0
        except Exception:
            idx_off = 0
        self.delay_on_combo.setCurrentIndex(idx_on)
        self.delay_off_combo.setCurrentIndex(idx_off)
        delay_layout.addWidget(self.delay_on_combo)
        delay_layout.addWidget(self.delay_off_combo)
        content_layout.addLayout(delay_layout)
        # Editor
        self.editor = CurveEditor()
        self.editor.current_curve = "fan"
        self.editor.setFanPoints(self.fan_points)
        self.editor.setPumpPoints(self.pump_points)
        content_layout.addWidget(self.editor)
        # Presets
        preset_layout = QHBoxLayout()
        preset_label = QLabel("Пресет:")
        preset_label.setStyleSheet("color: #FFFFFF; font-size: 14pt;")
        preset_layout.addWidget(preset_label)
        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet("QComboBox { font-size: 14pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 32px; height: 40px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid #FFFFFF; margin-right: 8px; } QComboBox:hover { background-color: #3e3e3e; }")
        self.preset_combo.addItems(["Стандарт"])
        self.preset_combo.clear()
        self.preset_combo.addItems(list(self.presets.keys()))
        self.preset_combo.setCurrentText(self.selected_preset)
        self.preset_combo.currentTextChanged.connect(self.on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        btn_add_preset = QPushButton("добавить")
        btn_add_preset.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        btn_add_preset.clicked.connect(self.on_add_preset)
        preset_layout.addWidget(btn_add_preset)
        btn_rename_preset = QPushButton("переименовать")
        btn_rename_preset.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        btn_rename_preset.clicked.connect(self.on_rename_preset)
        preset_layout.addWidget(btn_rename_preset)
        btn_del_preset = QPushButton("удалить")
        btn_del_preset.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        btn_del_preset.clicked.connect(self.on_del_preset)
        preset_layout.addWidget(btn_del_preset)
        content_layout.addLayout(preset_layout)
        # Save / Reset / Close buttons
        self.btn_save = QPushButton("сохранить")
        self.btn_save.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        self.btn_save.clicked.connect(self.on_save_clicked)
        self.btn_reset = QPushButton("сбросить")
        self.btn_reset.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        self.btn_reset.setFixedWidth(220)
        self.btn_reset.clicked.connect(self.on_reset_clicked)
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_reset)
        btn_close = QPushButton("закрыть")
        btn_close.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(btn_close)
        content_layout.addLayout(btn_layout)
        # Connect
        self.radio_fan.toggled.connect(self.on_curve_type_changed)
        self.radio_pump.toggled.connect(self.on_curve_type_changed)
        self.on_curve_type_changed()

    def closeEvent(self, event):
        self.editor.selected = None
        self.editor.selected_curve = None
        event.accept()

    def on_curve_type_changed(self):
        self.editor.current_curve = "fan" if self.radio_fan.isChecked() else "pump"
        self.editor.selected = None
        self.editor.selected_curve = None
        self.editor.update()
        # Переключение отображаемого гистерезиса в зависимости от выбранной кривой
        if self.radio_fan.isChecked():
            self.hyst_spin.blockSignals(True)
            self.hyst_spin.setValue(int(self.hyst_fan))
            self.hyst_spin.blockSignals(False)
        else:
            self.hyst_spin.blockSignals(True)
            self.hyst_spin.setValue(int(self.hyst_pump))
            self.hyst_spin.blockSignals(False)

    def on_add_preset(self):
        name, ok = QInputDialog.getText(self, "Новый пресет", "Название:")
        if ok and name:
            self.preset_combo.addItem(name)
            self.presets[name] = {"fan_curve": [p[:] for p in self.fan_points], "pump_curve": [p[:] for p in self.pump_points]}
            self.selected_preset = name
            self.preset_combo.setCurrentText(name)
            self.save_config()

    def on_rename_preset(self):
        current = self.preset_combo.currentText()
        if current == "Стандарт":
            return
        name, ok = QInputDialog.getText(self, "Переименовать", "Новое название:", text=current)
        if ok and name:
            idx = self.preset_combo.currentIndex()
            self.preset_combo.setItemText(idx, name)
            self.presets[name] = self.presets.pop(current)
            self.selected_preset = name
            self.save_config()

    def on_del_preset(self):
        current = self.preset_combo.currentText()
        if current != "Стандарт":
            del self.presets[current]
            self.preset_combo.removeItem(self.preset_combo.currentIndex())
            if current == self.selected_preset:
                self.selected_preset = "default"
            self.save_config()

    def on_preset_changed(self, preset):
        if preset in self.presets:
            self.fan_points = [p[:] for p in self.presets[preset]["fan_curve"]]
            self.pump_points = [p[:] for p in self.presets[preset]["pump_curve"]]
            self.selected_preset = preset
            global _last_preset_name
            _last_preset_name = preset
            if self.main_window:
                self.main_window.info_label.setText(f'<html><body><p>{self.main_window.targets}</p><p>Профиль: {preset}</p><p>{self.main_window.link_status}</p></body></html>')
            self.editor.setFanPoints(self.fan_points)
            self.editor.setPumpPoints(self.pump_points)
            self.on_curve_type_changed()

    def save_config(self):
        source_mode = self.source_mode_combo.currentIndex()
        # Считать текущие значения задержек из комбобоксов
        try:
            self.delay_on_seconds = self._delay_vals[self.delay_on_combo.currentIndex()]
        except Exception:
            self.delay_on_seconds = 0
        try:
            self.delay_off_seconds = self._delay_vals[self.delay_off_combo.currentIndex()]
        except Exception:
            self.delay_off_seconds = 0
        try:
            with open(self.curves_path, "w", encoding="utf-8") as f:
                json.dump({
                    "fan_curve": self.fan_points,
                    "pump_curve": self.pump_points,
                    "source_mode": source_mode,
                    "presets": self.presets,
                    "selected_preset": self.selected_preset,
                    "hyst_fan": int(self.hyst_fan),
                    "hyst_pump": int(self.hyst_pump),
                    "delay_on_seconds": int(self.delay_on_seconds),
                    "delay_off_seconds": int(self.delay_off_seconds)
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения: {e}")
        # Применить задержки к MainWindow и сбросить состояния delay-машины
        if self.main_window:
            old_on = getattr(self.main_window, 'delay_on_seconds', -1)
            old_off = getattr(self.main_window, 'delay_off_seconds', -1)
            self.main_window.delay_on_seconds = int(self.delay_on_seconds)
            self.main_window.delay_off_seconds = int(self.delay_off_seconds)
            # Сброс delay-состояний при смене настроек
            if old_on != int(self.delay_on_seconds) or old_off != int(self.delay_off_seconds):
                try:
                    with self.main_window._temp_hold_lock:
                        self.main_window._fan_running_state = False
                        self.main_window._fan_on_timer_start = None
                        self.main_window._fan_pending_off_until = None
                        self.main_window._fan_last_on_temps = None
                        self.main_window._pump_running_state = False
                        self.main_window._pump_on_timer_start = None
                        self.main_window._pump_pending_off_until = None
                        self.main_window._pump_last_on_temps = None
                    print(f"Delay settings changed: on={self.delay_on_seconds}s off={self.delay_off_seconds}s — states reset")
                except Exception:
                    pass
            try:
                self.main_window.save_app_config()
            except Exception:
                pass

    def on_save_clicked(self):
        self.fan_points = self.editor.getFanPoints()
        self.pump_points = self.editor.getPumpPoints()
        source_mode = self.source_mode_combo.currentIndex()
        self.presets[self.selected_preset] = {"fan_curve": [p[:] for p in self.fan_points], "pump_curve": [p[:] for p in self.pump_points]}
        self.save_config()
        if self.main_window:
            self.main_window.presets = self.presets
        # Сохранить график
        try:
            pixmap = QPixmap(self.editor.size())
            self.editor.render(pixmap)
            pixmap.save("curve_graph.png")
        except Exception as e:
            print(f"Ошибка сохранения графика: {e}")
        # Отправка на ESP32
        def build_curve_packet(tag1, tag2, points, source_mode, hyst_pct, interp_mode=1):
            pkt = bytearray()
            pkt.append(ord(tag1))
            pkt.append(ord(tag2))
            # Версия 2 с поддержкой гистерезиса
            pkt.append(2)
            pkt.append(source_mode)
            pkt.append(interp_mode)
            # Порядок полей для v2: ver, src, mode, N, hyst
            n = len(points)
            hyst = max(3, min(10, int(hyst_pct)))
            pkt.append(n)
            pkt.append(hyst)
            for tC, sP in points:
                tC10 = int(round(float(tC) * 10))
                sP_int = int(round(float(sP)))
                pkt += struct.pack('<hB', tC10, sP_int)
            return bytes(pkt)
        try:
            fan_pkt = build_curve_packet('F', 'C', self.fan_points, source_mode, self.hyst_fan)
            pump_pkt = build_curve_packet('P', 'C', self.pump_points, source_mode, self.hyst_pump)
            tx_cmd_queue.put(("fan_curve", fan_pkt))
            tx_cmd_queue.put(("pump_curve", pump_pkt))
            print("Кривые отправлены")
        except Exception as e:
            print(f"Ошибка отправки: {e}")
        # Сбросить выделение
        self.editor.selected = None
        self.editor.selected_curve = None
        # Отключить кнопку и показать сообщение
        self.btn_save.setEnabled(False)
        self.btn_save.setText("сохранено")
        QTimer.singleShot(3000, self.reset_button)

    def reset_button(self):
        self.btn_save.setText("сохранить")
        self.btn_save.setEnabled(True)

    def on_reset_clicked(self):
        # Сбросить кривые
        self.fan_points = [[70.0, 70.0], [80.0, 100.0], [110.0, 100.0]]
        self.pump_points = [[70.0, 30.0], [80.0, 50.0], [110.0, 50.0]]
        self.editor.setFanPoints(self.fan_points)
        self.editor.setPumpPoints(self.pump_points)
        self.editor.selected = None
        self.editor.selected_curve = None
        self.editor.update()

class ColorPalette(QFrame):
    def __init__(self, colors, mode_combo, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.Box)
        self.colors = list(colors) if colors is not None else []
        self._ensure_colors_len()
        self.mode_combo = mode_combo
        self.mode = "Свободное"
        self.selected = None
        self.points = []  # will be set in reset_positions
        self.relative_vectors = [(40, 40) for _ in range(20)]  # initial relative vectors for secondaries
        self.last_pos = None
        self.speed = 5  # default 5 seconds
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.animate_gradient)
        self.animation_t = 0.0
        palette_w, palette_h = 800, 360
        self.setFixedSize(palette_w, palette_h)
        self.setMouseTracking(True)
        # Create palette image
        self.palette_image = QImage(palette_w, palette_h, QImage.Format.Format_RGB32)
        for x in range(palette_w):
            for y in range(palette_h):
                hue = int(360 * x / palette_w)
                color = QColor.fromHsv(hue, 255, 255)  # pure colors only
                self.palette_image.setPixel(x, y, color.rgb())

    def _ensure_colors_len(self):
        if len(self.colors) < 20:
            last = self.colors[-1] if self.colors else QColor(0, 0, 0)
            self.colors.extend([last] * (20 - len(self.colors)))
        elif len(self.colors) > 20:
            self.colors = self.colors[:20]

    def get_color_at_position(self, x, y):
        hue = int(360 * x / self.width()) % 360
        return QColor.fromHsv(hue, 255, 255)

    def update_colors(self):
        self.animation_timer.stop()
        self._ensure_colors_len()
        if self.mode == "Свободное":
            pass  # colors updated in mouseMove
        elif self.mode == "Зависимое":
            for i in range(20):
                x, y = self.points[i][0]
                self.colors[i] = self.get_color_at_position(x, y)
        elif self.mode == "Мне повезёт":
            pass  # random
        elif self.mode == "Свободное градиентное":
            # Interpolate between points
            sorted_points = sorted(enumerate(self.points), key=lambda x: x[1][0][0])
            for i in range(len(sorted_points) - 1):
                start_idx, start_pts = sorted_points[i]
                end_idx, end_pts = sorted_points[i+1]
                start_color = self.colors[start_idx]
                end_color = self.colors[end_idx]
                start_x = start_pts[0][0]
                end_x = end_pts[0][0]
                for j in range(start_idx, end_idx + 1):
                    if end_x != start_x:
                        t = (self.points[j][0][0] - start_x) / (end_x - start_x)
                    else:
                        t = 0
                    t = max(0, min(1, t))
                    self.colors[j] = self.interpolate_color(start_color, end_color, t)
        elif self.mode == "Зависимое градиентное":
            # Same as free gradient but colors are from positions
            for i in range(20):
                x, y = self.points[i][0]
                self.colors[i] = self.get_color_at_position(x, y)
            # Then interpolate? Wait, perhaps just set to position color
            # But user wants gradient, so maybe interpolate the position colors
            sorted_points = sorted(enumerate(self.points), key=lambda x: x[1][0][0])
            for i in range(len(sorted_points) - 1):
                start_idx, start_pts = sorted_points[i]
                end_idx, end_pts = sorted_points[i+1]
                start_color = self.colors[start_idx]
                end_color = self.colors[end_idx]
                start_x = start_pts[0][0]
                end_x = end_pts[0][0]
                for j in range(start_idx, end_idx + 1):
                    if end_x != start_x:
                        t = (self.points[j][0][0] - start_x) / (end_x - start_x)
                    else:
                        t = 0
                    t = max(0, min(1, t))
                    self.colors[j] = self.interpolate_color(start_color, end_color, t)
        elif self.mode == "Моно цвет":
            if self.points:
                x, y = self.points[0][0]
                color = self.get_color_at_position(x, y)
                self.colors = [color] * 20
        elif self.mode == "Моно градиентный":
            if len(self.points) >= 2:
                start_x, start_y = self.points[0][0]
                end_x, end_y = self.points[1][0]
                start_color = self.get_color_at_position(start_x, start_y)
                end_color = self.get_color_at_position(end_x, end_y)
                for i in range(20):
                    t = i / 19.0
                    self.colors[i] = self.interpolate_color(start_color, end_color, t)
            if self.speed > 0:
                self.animation_timer.start(100)
            else:
                self.animation_timer.stop()

    def interpolate_color(self, c1, c2, t):
        r = int(c1.red() + (c2.red() - c1.red()) * t)
        g = int(c1.green() + (c2.green() - c1.green()) * t)
        b = int(c1.blue() + (c2.blue() - c1.blue()) * t)
        return QColor(r, g, b)

    def animate_gradient(self):
        if self.mode == "Моно градиентный" and len(self.points) >= 2:
            self.animation_t += 0.1 / self.speed
            if self.animation_t >= 1:
                self.animation_t = 0
            start_x, start_y = self.points[0][0]
            end_x, end_y = self.points[1][0]
            start_color = self.get_color_at_position(start_x, start_y)
            end_color = self.get_color_at_position(end_x, end_y)
            for i in range(20):
                t = (i / 19.0 + self.animation_t) % 1.0
                self.colors[i] = self.interpolate_color(start_color, end_color, t)
            self.update()
            # Send to device if possible
            # Removed to avoid spamming BLE

    

    def update_mode(self, mode):
        self.mode = mode
        if "градиентное" in mode:
            if not self.points or len(self.points) < 20:
                self.reset_positions()
            for i in range(20):
                if len(self.points[i]) == 1:
                    x, y = self.points[i][0]
                    self.points[i].append((x + 40, y + 40))  # add second point
                    self.relative_vectors[i] = (40, 40)
        elif mode == "Моно цвет":
            if not self.points or len(self.points) != 1:
                self.points = [[(self.width() // 2, self.height() // 2)]]  # один круг в центре
        elif mode == "Моно градиентный":
            if not self.points or len(self.points) < 2:
                self.points = [[(self.width() // 4, self.height() // 2)], [(3 * self.width() // 4, self.height() // 2)]]  # два круга
            else:
                self.points = [self.points[0], self.points[1]]
        else:
            if not self.points or len(self.points) < 20:
                self.reset_positions()
            else:
                for i in range(20):
                    self.points[i] = [self.points[i][0]]  # keep only first
        self.update()

    def randomize_positions(self):
        self.reset_positions()  # start from centered line
        import random
        for i in range(20):
            x = random.randint(0, self.width())
            y = random.randint(0, self.height())
            self.points[i][0] = (x, y)
            if len(self.points[i]) > 1:
                x2 = random.randint(0, self.width())
                y2 = random.randint(0, self.height())
                self.points[i][1] = (x2, y2)
            # update color
            hue = int(360 * x / self.width())
            val = 255
            self.colors[i] = QColor.fromHsv(hue, 255, val)
        self.update()

    def lucky_gradient_randomize(self):
        self.reset_positions()  # start from centered line
        import random
        w = self.width() or 800
        h = self.height() or 600
        for i in range(20):
            if len(self.points[i]) < 2:
                x, y = self.points[i][0]
                self.points[i].append((x + 20, y + 20))
            x = random.randint(0, w - 1)
            y = random.randint(0, h - 1)
            self.points[i][0] = (x, y)
            # second point not far
            dx = random.choice([-1, 1]) * random.randint(30, 80)
            dy = random.choice([-1, 1]) * random.randint(30, 80)
            x2 = max(0, min(w - 1, x + dx))
            y2 = max(0, min(h - 1, y + dy))
            self.points[i][1] = (x2, y2)
            # update color for main point
            hue = int(360 * x / w)
            val = 255
            self.colors[i] = QColor.fromHsv(hue, 255, val)
        self.update()

    def reset_positions(self):
        if self.mode == "Моно цвет":
            self.points = [[(self.width() // 2, self.height() // 2)]]
        elif self.mode == "Моно градиентный":
            self.points = [[(self.width() // 4, self.height() // 2)], [(3 * self.width() // 4, self.height() // 2)]]
        else:
            y_base = int(self.height() * 0.66)
            self.points = [[(50 + i * 35, y_base)] for i in range(20)]
            self.relative_vectors = [(20, 20) for _ in range(20)]
            if "градиентное" in self.mode:
                for i in range(20):
                    if len(self.points[i]) == 1:
                        x, y = self.points[i][0]
                        self.points[i].append((x + 20, y + 20))  # add second point
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        width = self.width()
        height = self.height()
        # Set clip path for rounded corners
        path = QPainterPath()
        path.addRoundedRect(0, 0, width, height, 20, 20)
        painter.setClipPath(path)
        # Draw color palette
        painter.drawImage(0, 0, self.palette_image)
        # Draw points
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        for i, pts in enumerate(self.points):
            for j, (x, y) in enumerate(pts):
                painter.setBrush(self.colors[i])
                painter.drawEllipse(int(x - 15), int(y - 15), 30, 30)
                if self.mode == "Моно цвет":
                    label = "Цвет"
                elif self.mode == "Моно градиентный":
                    label = "Старт" if i == 0 else "Конец"
                else:
                    label = f"{i+1}" if j == 0 else f"{i+1}.{j+1}"
                painter.setPen(Qt.GlobalColor.white)
                painter.setFont(QFont(design_font_family(), 10, QFont.Weight.Medium))
                painter.drawText(int(x - 10), int(y + 5), label)
                painter.setPen(QPen(Qt.GlobalColor.black, 2))
            if len(pts) > 1:
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
                painter.drawLine(int(pts[0][0]), int(pts[0][1]), int(pts[1][0]), int(pts[1][1]))
        # Draw line for mono gradient
        if self.mode == "Моно градиентный" and len(self.points) >= 2:
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawLine(int(self.points[0][0][0]), int(self.points[0][0][1]), int(self.points[1][0][0]), int(self.points[1][0][1]))

    def mousePressEvent(self, event):
        x, y = event.position().toPoint().x(), event.position().toPoint().y()
        for i, pts in enumerate(self.points):
            for j, (px, py) in enumerate(pts):
                if (x - px)**2 + (y - py)**2 < 225:
                    self.selected = (i, j)
                    self.last_pos = (x, y)
                    return

    def mouseMoveEvent(self, event):
        if self.selected is None:
            return
        i, j = self.selected
        x = max(0, min(self.width(), event.position().toPoint().x()))
        y = max(0, min(self.height(), event.position().toPoint().y()))
        if self.mode == "Свободное":
            self.points[i][0] = (int(x), int(y))
        elif self.mode == "Зависимое":
            # Snake-like movement: move head, adjust body to maintain distances
            d = 40.0  # fixed distance
            self.points[i][0] = (int(x), int(y))
            # Adjust points after i
            for k in range(i + 1, 20):
                prev_x, prev_y = self.points[k - 1][0]
                curr_x, curr_y = self.points[k][0]
                dx = curr_x - prev_x
                dy = curr_y - prev_y
                dist = math.sqrt(dx**2 + dy**2)
                if dist > 0:
                    curr_x = prev_x + (dx / dist) * d
                    curr_y = prev_y + (dy / dist) * d
                    self.points[k][0] = (int(curr_x), int(curr_y))
            # Adjust points before i
            for k in range(i - 1, -1, -1):
                next_x, next_y = self.points[k + 1][0]
                curr_x, curr_y = self.points[k][0]
                dx = curr_x - next_x
                dy = curr_y - next_y
                dist = math.sqrt(dx**2 + dy**2)
                if dist > 0:
                    curr_x = next_x + (dx / dist) * d
                    curr_y = next_y + (dy / dist) * d
                    self.points[k][0] = (int(curr_x), int(curr_y))
        elif "градиентное" in self.mode:
            if "зависимое" in self.mode.lower():
                # Set selected point
                self.points[i][j] = (int(x), int(y))
                if j == 0:
                    # Move secondary with primary using relative vector
                    vx, vy = self.relative_vectors[i]
                    sx = x + vx
                    sy = y + vy
                    sx = max(0, min(self.width() - 1, sx))
                    sy = max(0, min(self.height() - 1, sy))
                    self.points[i][1] = (int(sx), int(sy))
                else:
                    # Update relative vector
                    vx = x - self.points[i][0][0]
                    vy = y - self.points[i][0][1]
                    self.relative_vectors[i] = (vx, vy)
                # Snake for primaries and move secondaries
                d = 40.0
                # Adjust points after i
                for k in range(i + 1, 20):
                    prev_x, prev_y = self.points[k - 1][0]
                    curr_x, curr_y = self.points[k][0]
                    dx = curr_x - prev_x
                    dy = curr_y - prev_y
                    dist = math.sqrt(dx**2 + dy**2)
                    if dist > 0:
                        curr_x = prev_x + (dx / dist) * d
                        curr_y = prev_y + (dy / dist) * d
                        self.points[k][0] = (int(curr_x), int(curr_y))
                        # Move secondary
                        vx, vy = self.relative_vectors[k]
                        sx = curr_x + vx
                        sy = curr_y + vy
                        sx = max(0, min(self.width() - 1, sx))
                        sy = max(0, min(self.height() - 1, sy))
                        self.points[k][1] = (int(sx), int(sy))
                # Adjust points before i
                for k in range(i - 1, -1, -1):
                    next_x, next_y = self.points[k + 1][0]
                    curr_x, curr_y = self.points[k][0]
                    dx = curr_x - next_x
                    dy = curr_y - next_y
                    dist = math.sqrt(dx**2 + dy**2)
                    if dist > 0:
                        curr_x = next_x + (dx / dist) * d
                        curr_y = next_y + (dy / dist) * d
                        self.points[k][0] = (int(curr_x), int(curr_y))
                        # Move secondary
                        vx, vy = self.relative_vectors[k]
                        sx = curr_x + vx
                        sy = curr_y + vy
                        sx = max(0, min(self.width() - 1, sx))
                        sy = max(0, min(self.height() - 1, sy))
                        self.points[k][1] = (int(sx), int(sy))
                # Collision detection only for primary points
                min_dist = 45
                for p in range(20):
                    for r in range(p + 1, 20):
                        px, py = self.points[p][0]
                        rx, ry = self.points[r][0]
                        dx = rx - px
                        dy = ry - py
                        dist = math.sqrt(dx**2 + dy**2)
                        if dist < min_dist and dist > 0:
                            overlap = min_dist - dist
                            dx /= dist
                            dy /= dist
                            # Move primaries apart
                            self.points[p][0] = (int(px - dx * overlap / 2), int(py - dy * overlap / 2))
                            self.points[r][0] = (int(rx + dx * overlap / 2), int(ry + dy * overlap / 2))
                            # Clamp to bounds
                            self.points[p][0] = (
                                max(0, min(self.width() - 1, int(self.points[p][0][0]))),
                                max(0, min(self.height() - 1, int(self.points[p][0][1]))),
                            )
                            self.points[r][0] = (
                                max(0, min(self.width() - 1, int(self.points[r][0][0]))),
                                max(0, min(self.height() - 1, int(self.points[r][0][1]))),
                            )
                            # Move secondaries with primaries
                            if len(self.points[p]) > 1:
                                vx, vy = self.relative_vectors[p]
                                sx = self.points[p][0][0] + vx
                                sy = self.points[p][0][1] + vy
                                sx = max(0, min(self.width() - 1, sx))
                                sy = max(0, min(self.height() - 1, sy))
                                self.points[p][1] = (int(sx), int(sy))
                            if len(self.points[r]) > 1:
                                vx, vy = self.relative_vectors[r]
                                sx = self.points[r][0][0] + vx
                                sy = self.points[r][0][1] + vy
                                sx = max(0, min(self.width() - 1, sx))
                                sy = max(0, min(self.height() - 1, sy))
                                self.points[r][1] = (int(sx), int(sy))
            else:
                # Free gradient
                if j == 0:  # main point
                    dx = x - self.points[i][0][0]
                    dy = y - self.points[i][0][1]
                    self.points[i][0] = (int(x), int(y))
                    if len(self.points[i]) > 1:
                        px, py = self.points[i][1]
                        self.points[i][1] = (int(px + dx), int(py + dy))
                else:  # second point
                    self.points[i][j] = (int(x), int(y))
        elif self.mode == "Моно цвет":
            if self.selected and self.selected[1] == 0:
                self.points[0][0] = (int(x), int(y))
        elif self.mode == "Моно градиентный":
            if self.selected:
                i, j = self.selected
                self.points[i][j] = (int(x), int(y))
        # Update color
        if self.mode == "Свободное":
            hue = int(360 * x / self.width())
            val = 255
            self.colors[i] = QColor.fromHsv(hue, 255, val)
        if self.mode not in ["Свободное градиентное", "Зависимое градиентное", "Моно цвет", "Моно градиентный"]:
            self.update_colors()
        self.last_pos = (x, y)
        self.update()

    def mouseReleaseEvent(self, event):
        self.selected = None
        self.last_pos = None
        self.update_colors()
        self.update()
        # Notify dialog to apply and save current palette
        try:
            dlg = getattr(self, 'dialog', None)
            if dlg and hasattr(dlg, 'on_palette_commit'):
                dlg.on_palette_commit()
        except Exception:
            pass

class LEDCustomDialog(QDialog, FramelessWindowMixin):
    def __init__(self, colors, parent=None, points=None, mode="Свободное", profiles=None, speed: int = 5):
        super().__init__(parent)
        # Secondary window: frameless
        try:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        except Exception:
            pass
        # Transparent background; draw card frame inside
        if ENABLE_GLASS_BACKDROP:
            try:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            except Exception:
                pass
        # Subtle shadow
        try:
            pass
        except Exception:
            pass
        # Enable drag-to-move on background
        try:
            self.enable_frameless_drag()
        except Exception:
            pass
        # Remember MainWindow reference for sending previews and saving
        self.main_window = parent
        self.colors = colors.copy()
        self.led_profiles = profiles or {}
        self.setWindowTitle("Редактор индивидуальных цветов LED")
        self.setFixedSize(1000, 850)
        # Outer layout and card frame
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 20, 20, 20)
        outer_layout.setSpacing(0)
        card = QFrame()
        card.setObjectName("dialogCard")
        card.setStyleSheet("QFrame#dialogCard { background-color: #1e1e1e; border: 1px solid #555555; border-radius: 8px; }")
        content_layout = QVBoxLayout(card)
        content_layout.setContentsMargins(40, 40, 40, 40)
        content_layout.setSpacing(20)
        outer_layout.addWidget(card)
        try:
            self.apply_drop_shadow(target=card)
        except Exception:
            pass
        # Верхняя линия: Профиль и Режим
        top_layout = QHBoxLayout()
        profile_label = QLabel("Профиль:")
        profile_label.setStyleSheet("color: #FFFFFF; font-size: 12pt;")
        top_layout.addWidget(profile_label)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(list(self.led_profiles.keys()))
        self.profile_combo.setStyleSheet("QComboBox { font-size: 12pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 4px; padding: 0 8px; height: 30px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 3px solid #FFFFFF; } QComboBox:hover { background-color: #3e3e3e; } QComboBox QAbstractItemView { color: #FFFFFF; background-color: #171717; selection-background-color: #7C4DFF; selection-color: #FFFFFF; }")
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        top_layout.addWidget(self.profile_combo)
        mode_label = QLabel("Режим редактирования:")
        mode_label.setStyleSheet("color: #FFFFFF; font-size: 12pt;")
        top_layout.addWidget(mode_label)
        self.edit_mode_combo = QComboBox()
        self.edit_mode_combo.addItems(["Свободное", "Зависимое", "Мне повезёт", "Свободное градиентное", "Зависимое градиентное", "Моно цвет", "Моно градиентный"])
        self.edit_mode_combo.setStyleSheet("QComboBox { font-size: 12pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 4px; padding: 0 8px; height: 30px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 3px solid #FFFFFF; } QComboBox:hover { background-color: #3e3e3e; } QComboBox QAbstractItemView { color: #FFFFFF; background-color: #171717; selection-background-color: #7C4DFF; selection-color: #FFFFFF; }")
        self.edit_mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        top_layout.addWidget(self.edit_mode_combo)
        content_layout.addLayout(top_layout)
        speed_layout = QHBoxLayout()
        speed_label = QLabel("Скорость перелива (сек):")
        speed_label.setStyleSheet("color: #FFFFFF; font-size: 12pt;")
        speed_layout.addWidget(speed_label)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 30)
        self.speed_slider.setValue(10)  # default 5 seconds mapped
        self.speed_slider.setStyleSheet("QSlider::groove:horizontal { background: #555555; height: 4px; } QSlider::handle:horizontal { background: #FFFFFF; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }")
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        self.speed_slider.sliderReleased.connect(self.on_speed_released)
        self.speed_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        speed_layout.addWidget(self.speed_slider, 1)
        content_layout.addLayout(speed_layout)
        content_layout.addSpacing(20)
        self.color_palette = ColorPalette(self.colors, self.edit_mode_combo)
        self.color_palette.speed = self._speed_from_slider(self.speed_slider.value())
        if points:
            self.color_palette.points = points
            self.color_palette.update_mode(mode)
        else:
            self.color_palette.reset_positions()
        self.color_palette.mode = mode
        self.color_palette.update_mode(mode)
        try:
            self.speed_slider.blockSignals(True)
            self.speed_slider.setValue(self._slider_from_speed(speed))
        finally:
            self.speed_slider.blockSignals(False)
        try:
            self.color_palette.speed = int(speed)
        except Exception:
            pass
        self.edit_mode_combo.setCurrentText(mode)
        self.color_palette.setStyleSheet("border: 1px solid #555555; border-radius: 20px;")
        # Allow palette to call back into this dialog on user commit
        setattr(self.color_palette, 'dialog', self)
        content_layout.addWidget(self.color_palette)
        content_layout.addSpacing(20)
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("сброс")
        reset_btn.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        reset_btn.clicked.connect(self.color_palette.reset_positions)
        btn_layout.addWidget(reset_btn)
        self.save_profile_btn = QPushButton("сохранить профиль")
        self.save_profile_btn.setStyleSheet("QPushButton { font-size: 14pt; background-color: #4CAF50; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #5CBF60; }")
        self.save_profile_btn.clicked.connect(self.save_current_profile)
        btn_layout.addWidget(self.save_profile_btn)
        ok_btn = QPushButton("ok")
        ok_btn.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("закрыть")
        cancel_btn.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        content_layout.addLayout(btn_layout)

    def on_speed_changed(self):
        self.color_palette.speed = self._speed_from_slider(self.speed_slider.value())
        # Only update local animation; send on release
        try:
            self.color_palette.update_colors()
        except Exception:
            pass

    def on_speed_released(self):
        # Send preview and persist only when user releases the slider
        self.send_current_led_preview()
        self.save_as_current_profile()

    def on_mode_changed(self):
        mode = self.edit_mode_combo.currentText()
        if mode == "Мне повезёт":
            self.color_palette.randomize_positions()
        self.color_palette.update_mode(mode)
        # Live preview when switching modes
        self.send_current_led_preview()
        # Persist as current profile
        self.save_as_current_profile()

    def on_profile_changed(self):
        profile = self.profile_combo.currentText()
        if profile in self.led_profiles:
            data = self.led_profiles[profile]
            self.colors = [QColor(*c) for c in data['colors']]
            self.color_palette.colors = self.colors
            self.custom_colors = self.colors.copy()
            self.color_palette.points = data.get('points', self.color_palette.points)
            self.color_palette.mode = data.get('mode', 'Свободное')
            self.color_palette.speed = data.get('speed', 5)
            self.speed_slider.setValue(self._slider_from_speed(self.color_palette.speed))
            self.color_palette.update_mode(self.color_palette.mode)
            self.edit_mode_combo.setCurrentText(self.color_palette.mode)
            self.color_palette.update()
            # Live preview when profile applied
            self.send_current_led_preview()
            # Also persist as current
            self.save_as_current_profile()

    def _speed_from_slider(self, slider_val: int) -> int:
        try:
            v = int(slider_val)
        except Exception:
            v = 1
        return max(1, int(round(v / 2.0)))

    def _slider_from_speed(self, speed_val: int) -> int:
        try:
            s = int(speed_val)
        except Exception:
            s = 1
        return max(1, min(30, int(round(s * 2.0))))

    def save_current_profile(self):
        name, ok = QInputDialog.getText(self, "Сохранить профиль", "Имя профиля:")
        if ok and name:
            colors = [c.getRgb() for c in self.colors]
            points = self.color_palette.points
            mode = self.color_palette.mode
            speed = self.color_palette.speed
            self.led_profiles[name] = {"colors": colors, "points": points, "mode": mode, "speed": speed}
            self.profile_combo.addItem(name)
            self.profile_combo.setCurrentText(name)
            if self.main_window:
                self.main_window.led_profiles = self.led_profiles
            # Сохранить в файл
            self.save_led_profiles_to_file()
            # Send preview/apply
            self.send_current_led_preview()
            # UI feedback: show 'сохранено' on the save button for 3 seconds
            try:
                self.save_profile_btn.setEnabled(False)
                old_text = self.save_profile_btn.text()
                self.save_profile_btn.setText("сохранено")
                QTimer.singleShot(3000, lambda: (self.save_profile_btn.setText(old_text), self.save_profile_btn.setEnabled(True)))
            except Exception:
                pass

    def on_palette_commit(self):
        """Called by ColorPalette on mouse release to apply and save."""
        self.send_current_led_preview()
        self.save_as_current_profile()

    def save_as_current_profile(self):
        try:
            self.led_profiles["Текущий"] = {
                "colors": [(c.red(), c.green(), c.blue()) for c in self.color_palette.colors],
                "points": self.color_palette.points,
                "mode": self.color_palette.mode,
                "speed": self.color_palette.speed,
            }
            # Reflect into MainWindow and persist file
            if self.main_window:
                self.main_window.custom_colors = self.color_palette.colors
                self.main_window.led_profiles = self.led_profiles
            self.save_led_profiles_to_file()
        except Exception:
            pass

    def send_current_led_preview(self):
        # Safely send a preview of current palette/mode to device via MainWindow
        try:
            mw = getattr(self, 'main_window', None)
            if not mw:
                return
            mode = self.edit_mode_combo.currentText()
            brightness = getattr(mw, 'brightness', 255)
            # Map UI mode to device modes: 4=custom, 5=gradient anim, else solid (0)
            if mode == "Моно градиентный" and len(self.color_palette.points) >= 2:
                # Gradient anim preview (mode 5)
                start_x, start_y = self.color_palette.points[0][0]
                end_x, end_y = self.color_palette.points[1][0]
                start_color = self.color_palette.get_color_at_position(start_x, start_y)
                end_color = self.color_palette.get_color_at_position(end_x, end_y)
                custom_bytes = bytes([
                    start_color.red(), start_color.green(), start_color.blue(),
                    end_color.red(),  end_color.green(),  end_color.blue(),
                    int(self.color_palette.speed) if self.color_palette.speed else 5
                ])
                mw.send_led_command(5, brightness, 0, 0, 0, custom_bytes)
            elif mode in ("Свободное", "Зависимое", "Свободное градиентное", "Зависимое градиентное", "Мне повезёт"):
                # Treat as custom 20 colors (mode 4)
                colors = self.color_palette.colors
                mw.send_led_command(4, brightness, 0, 0, 0, colors)
            elif mode == "Моно цвет":
                if self.color_palette.points:
                    x, y = self.color_palette.points[0][0]
                    c = self.color_palette.get_color_at_position(x, y)
                    mw.send_led_command(0, brightness, c.red(), c.green(), c.blue())
            else:
                # Fallback: send current custom colors
                colors = self.color_palette.colors
                mw.send_led_command(4, brightness, 0, 0, 0, colors)
        except Exception:
            pass

    def save_led_profiles_to_file(self):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            data = {}
        data["led_profiles"] = self.led_profiles
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

class SettingsDialog(QDialog, FramelessWindowMixin):
    def __init__(self, current_transport, autostart, minimized, pump_hours, brightness, oled_brightness=207, display_lang="RU", theme="violet", parent=None):
        super().__init__(parent)
        # Secondary window: frameless
        try:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        except Exception:
            pass
        # Transparent background; draw card frame inside
        if ENABLE_GLASS_BACKDROP:
            try:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            except Exception:
                pass
        # Subtle shadow
        try:
            pass
        except Exception:
            pass
        # Enable drag-to-move on background
        try:
            self.enable_frameless_drag()
        except Exception:
            pass
        self.main_window = parent
        self.led_profiles = self.load_led_profiles()
        self.brightness = brightness
        self.oled_brightness = oled_brightness
        # Outer and card
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 20, 20, 20)
        outer_layout.setSpacing(0)
        card = QFrame()
        card.setObjectName("glassCard")
        content_layout = QVBoxLayout(card)
        content_layout.setContentsMargins(40, 40, 40, 40)
        content_layout.setSpacing(20)
        outer_layout.addWidget(card)
        try:
            self.apply_drop_shadow(target=card)
        except Exception:
            pass
        try:
            apply_windows_backdrop(self)
        except Exception:
            pass
        # Тема оформления
        theme_layout = QHBoxLayout()
        label_theme = QLabel("Тема оформления:")
        label_theme.setStyleSheet("color: #FFFFFF; font-size: 14pt;")
        theme_layout.addWidget(label_theme)
        self.theme_combo = QComboBox()
        self._theme_keys = ['violet', 'graphite', 'light']
        for k in self._theme_keys:
            self.theme_combo.addItem(THEMES[k]['name'], userData=k)
        try:
            cur_idx = self._theme_keys.index(theme if theme in THEMES else 'violet')
        except Exception:
            cur_idx = 0
        self.theme_combo.setCurrentIndex(cur_idx)
        self.theme_combo.setStyleSheet("QComboBox { font-size: 14pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 32px; height: 40px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid #FFFFFF; margin-right: 8px; } QComboBox:hover { background-color: #3e3e3e; } QComboBox QAbstractItemView { color: #FFFFFF; background-color: #171717; selection-background-color: #7C4DFF; selection-color: #FFFFFF; }")
        theme_layout.addWidget(self.theme_combo)
        content_layout.addLayout(theme_layout)
        # Транспорт
        transport_layout = QHBoxLayout()
        label_transport = QLabel("Подключение:")
        label_transport.setStyleSheet("color: #FFFFFF; font-size: 14pt;")
        transport_layout.addWidget(label_transport)
        self.transport_combo = QComboBox()
        self.transport_combo.addItems(["BLE", "USB"])
        self.transport_combo.setCurrentText(current_transport)
        self.transport_combo.setStyleSheet("QComboBox { font-size: 14pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 32px; height: 40px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid #FFFFFF; margin-right: 8px; } QComboBox:hover { background-color: #3e3e3e; } QComboBox QAbstractItemView { color: #FFFFFF; background-color: #171717; selection-background-color: #7C4DFF; selection-color: #FFFFFF; }")
        transport_layout.addWidget(self.transport_combo)
        content_layout.addLayout(transport_layout)
        # Автозагрузка
        self.autostart_cb = QCheckBox("Автозагрузка вместе с Windows")
        self.autostart_cb.setChecked(autostart)
        self.autostart_cb.setStyleSheet("QCheckBox { color: #FFFFFF; font-size: 14pt; } QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #FFFFFF; border-radius: 7px; background-color: #1e1e1e; } QCheckBox::indicator:checked { background-color: #800080; }")
        content_layout.addWidget(self.autostart_cb)
        # Свернутый запуск
        self.minimized_cb = QCheckBox("Запуск приложения сразу свёрнутым")
        self.minimized_cb.setChecked(minimized)
        self.minimized_cb.setStyleSheet("QCheckBox { color: #FFFFFF; font-size: 14pt; } QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #FFFFFF; border-radius: 7px; background-color: #1e1e1e; } QCheckBox::indicator:checked { background-color: #00FFFF; }")
        content_layout.addWidget(self.minimized_cb)
        # Подсветка без соединения (рядом с автозапуском и свёрнутым запуском)
        self.keep_led_cb = QCheckBox("Оставить подсветку без соединения с ПК")
        try:
            self.keep_led_cb.setChecked(getattr(parent, 'keep_led_on_disconnected', False))
        except Exception:
            self.keep_led_cb.setChecked(False)
        self.keep_led_cb.setStyleSheet("QCheckBox { color: #FFFFFF; font-size: 14pt; } QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #FFFFFF; border-radius: 7px; background-color: #1e1e1e; } QCheckBox::indicator:checked { background-color: #7C4DFF; }")
        content_layout.addWidget(self.keep_led_cb)
        # Продувка при выключении / при сне
        self.purge_on_shutdown_cb = QCheckBox("Продувка после выключения")
        try:
            self.purge_on_shutdown_cb.setChecked(getattr(parent, 'purge_on_shutdown_enabled', False))
        except Exception:
            self.purge_on_shutdown_cb.setChecked(False)
        self.purge_on_shutdown_cb.setStyleSheet("QCheckBox { color: #FFFFFF; font-size: 14pt; } QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #FFFFFF; border-radius: 7px; background-color: #1e1e1e; } QCheckBox::indicator:checked { background-color: #0061C1; }")
        content_layout.addWidget(self.purge_on_shutdown_cb)
        # Защита гидролинии (в прошивке: LP)
        self.loopprot_cb = QCheckBox("Защита гидролинии (стоп при разрыве)")
        try:
            self.loopprot_cb.setChecked(getattr(parent, 'loop_protection_enabled', False))
        except Exception:
            self.loopprot_cb.setChecked(False)
        self.loopprot_cb.setStyleSheet("QCheckBox { color: #FFFFFF; font-size: 14pt; } QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #FFFFFF; border-radius: 7px; background-color: #1e1e1e; } QCheckBox::indicator:checked { background-color: #00BFA5; }")
        content_layout.addWidget(self.loopprot_cb)
        # Счетчик моточасов (всегда активен, без возможности выключения)
        always_on_label = QLabel("Счётчик моточасов: активен")
        always_on_label.setStyleSheet("color: #FFFFFF; font-size: 12pt;")
        content_layout.addWidget(always_on_label)
        self.pump_hours_label = QLabel('<div><p style="font-size:20pt; color:#FFFFFF; font-family: monospace;">00000.00&nbsp;&nbsp;&nbsp;00%</p><p style="font-size:8pt; color:#FFFFFF; margin-top: 2px;">часы&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;средние обороты</p></div>')
        self.pump_hours_label.setStyleSheet("border: 2px solid #555555; border-radius: 8px; padding: 8px;")
        self.pump_hours_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.pump_hours_label)
        self.reset_button = QPushButton("Обнулить счётчик")
        self.reset_button.setStyleSheet("QPushButton { font-size: 12pt; background-color: #444444; color: #FFFFFF; border: 1px solid #555555; border-radius: 6px; padding: 4px 8px; } QPushButton:hover { background-color: #545454; }")
        self.reset_button.clicked.connect(self.reset_pump_hours)
        self.reset_button.hide()  # Скрываем кнопку
        content_layout.addWidget(self.reset_button)
        # LED настройки
        led_group = QGroupBox("")
        led_group.setStyleSheet("QGroupBox { border: none; margin-top: 0px; }")
        led_layout = QVBoxLayout()
        # Кнопка настройки подсветки
        self.led_setup_btn = QPushButton("настроить подсветку")
        self.led_setup_btn.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        self.led_setup_btn.clicked.connect(self.open_led_editor)
        led_layout.addWidget(self.led_setup_btn)
        # Ползунок яркости
        brightness_layout = QHBoxLayout()
        brightness_label = QLabel("Яркость:")
        brightness_label.setStyleSheet("color: #FFFFFF; font-size: 12pt;")
        brightness_layout.addWidget(brightness_label)
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        # Разрешаем 0 для полного выключения, а минимальный полезный уровень — LED_MIN_BRIGHT
        self.brightness_slider.setRange(0, 255)
        try:
            init_b = int(self.brightness)
        except Exception:
            init_b = 255
        if init_b == 0:
            self.brightness_slider.setValue(0)
        else:
            self.brightness_slider.setValue(max(init_b, LED_MIN_BRIGHT))
        self.brightness_slider.setStyleSheet("QSlider::groove:horizontal { background: #555555; height: 4px; } QSlider::handle:horizontal { background: #FFFFFF; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }")
        self.brightness_slider.valueChanged.connect(self.update_brightness_value)
        # Вариант А: отправлять только при отпускании ползунка (без промежуточных отправок)
        # Убраны debounce-таймер и отправка по valueChanged; оставляем только sliderReleased.
        # И гарантированная отправка на отпускании ползунка
        self.brightness_slider.sliderReleased.connect(self.on_brightness_changed)
        brightness_layout.addWidget(self.brightness_slider)
        led_layout.addLayout(brightness_layout)
        # Ползунок яркости дисплея (OLED)
        oled_br_layout = QHBoxLayout()
        oled_br_label = QLabel("Яркость экрана:")
        oled_br_label.setStyleSheet("color: #FFFFFF; font-size: 12pt;")
        oled_br_layout.addWidget(oled_br_label)
        self.oled_brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.oled_brightness_slider.setRange(0, 255)
        self.oled_brightness_slider.setValue(self.oled_brightness)
        self.oled_brightness_slider.setStyleSheet("QSlider::groove:horizontal { background: #555555; height: 4px; } QSlider::handle:horizontal { background: #FFFFFF; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }")
        self.oled_brightness_slider.valueChanged.connect(self.update_oled_brightness_value)
        self.oled_brightness_slider.sliderReleased.connect(self.on_oled_brightness_changed)
        oled_br_layout.addWidget(self.oled_brightness_slider)
        led_layout.addLayout(oled_br_layout)
        led_group.setLayout(led_layout)
        content_layout.addWidget(led_group)
        # Язык дисплея (OLED)
        lang_layout = QHBoxLayout()
        lang_label = QLabel("Язык дисплея:")
        lang_label.setStyleSheet("color: #FFFFFF; font-size: 14pt;")
        lang_layout.addWidget(lang_label)
        self.display_lang_combo = QComboBox()
        self.display_lang_combo.addItems(["RU", "ENG"])
        self.display_lang_combo.setCurrentText("ENG" if display_lang == "ENG" else "RU")
        self.display_lang_combo.setStyleSheet("QComboBox { font-size: 14pt; background-color: #171717; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 32px; height: 40px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 4px solid #FFFFFF; margin-right: 8px; } QComboBox:hover { background-color: #3e3e3e; } QComboBox QAbstractItemView { color: #FFFFFF; background-color: #171717; selection-background-color: #7C4DFF; selection-color: #FFFFFF; }")
        lang_layout.addWidget(self.display_lang_combo)
        content_layout.addLayout(lang_layout)
        # Кнопки Сохранить / Отмена в одной строке
        btn_row = QHBoxLayout()
        btn_save = QPushButton("сохранить")
        btn_save.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 16px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("отмена")
        btn_cancel.setStyleSheet("QPushButton { font-size: 14pt; background-color: #2e2e2e; color: #FFFFFF; border: 1px solid #555555; border-radius: 8px; padding: 0 16px; height: 40px; } QPushButton:hover { background-color: #3e3e3e; }")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_save)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_cancel)
        content_layout.addLayout(btn_row)

    def get_transport(self):
        return self.transport_combo.currentText()

    def get_autostart(self):
        return self.autostart_cb.isChecked()

    def get_minimized(self):
        return self.minimized_cb.isChecked()

    def get_keep_led(self):
        return self.keep_led_cb.isChecked()
    def get_purge_on_shutdown(self):
        return self.purge_on_shutdown_cb.isChecked()

    # pump hours is always on; no getter needed
    def get_loopprot(self):
        return self.loopprot_cb.isChecked()
    def get_pump_hours(self):
        return True
    def get_display_lang(self) -> str:
        return self.display_lang_combo.currentText()
    def get_theme(self) -> str:
        try:
            return self.theme_combo.currentData() or 'violet'
        except Exception:
            return 'violet'

    def update_pump_hours_display(self, hours, percentage):
        hours_int = int(hours)
        minutes = (hours - hours_int) * 60
        text = f"{hours_int:05d}.{int(minutes):02d}"
        pct_text = f"{percentage:02.0f}%"
        html = f'<div><p style="font-size:20pt; color:#FFFFFF; font-family: monospace;">{text}&nbsp;&nbsp;&nbsp;{pct_text}</p><p style="font-size:8pt; color:#FFFFFF; margin-top: 2px;">часы&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;средние обороты</p></div>'
        self.pump_hours_label.setText(html)

    def reset_pump_hours(self):
        if hasattr(self, 'main_window') and self.main_window:
            reply = QMessageBox.question(self, "Подтверждение", "Обнулить счётчик моточасов? Данные на ESP32 и локально будут сброшены.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.main_window.reset_pump_hours()
        else:
            print("DEBUG: main_window not set")
            self.update_pump_hours_display(0, 0)

    def load_led_profiles(self):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("led_profiles", {
                    "Стандарт": {"colors": [[0,0,0]]*20, "points": [[(50+i*35,400)] for i in range(20)], "mode": "Свободное", "speed": 5},
                    "Движение": {"colors": [[0,0,0]]*20, "points": [[(100,300)], [(700,300)]], "mode": "Моно градиентный", "speed": 5}
                })
        except:
            return {"Стандарт": {"colors": [[0,0,0]]*20, "points": [[(50+i*35,400)] for i in range(20)], "mode": "Свободное"}}

    def open_led_editor(self):
        profile = self.led_profiles.get("Текущий", self.led_profiles.get("Стандарт", {"colors": [[0,0,0]]*20, "points": [[(50+i*35,400)] for i in range(20)], "mode": "Свободное"}))
        mode_val = profile.get("mode")
        if not isinstance(mode_val, str):
            # Санитизация старых конфигов: если вдруг попало число (например 4/5), подставим строковый режим
            mode_val = "Свободное"
        dialog = LEDCustomDialog(
            getattr(self.main_window, 'custom_colors', [QColor(0,0,0) for _ in range(20)]),
            self.main_window,
            points=profile.get("points"),
            mode=(mode_val or "Свободное"),
            profiles=self.led_profiles,
            speed=int(profile.get("speed", 5) or 5)
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self.main_window:
                self.main_window.custom_colors = dialog.colors
                self.main_window.led_custom_colors = dialog.colors  # update for brightness slider
            # сохранить профиль
            self.led_profiles["Текущий"] = {"colors": [c.getRgb() for c in dialog.colors], "points": dialog.color_palette.points, "mode": dialog.color_palette.mode, "speed": dialog.color_palette.speed}
            self.save_led_profiles()
            # Отправить на ESP32
            if dialog.color_palette.mode == "Моно градиентный" and dialog.color_palette.speed > 0 and len(dialog.color_palette.points) >= 2:
                start_x, start_y = dialog.color_palette.points[0][0]
                end_x, end_y = dialog.color_palette.points[1][0]
                start_color = dialog.color_palette.get_color_at_position(start_x, start_y)
                end_color = dialog.color_palette.get_color_at_position(end_x, end_y)
                custom_colors = bytes([start_color.red(), start_color.green(), start_color.blue(),
                                       end_color.red(), end_color.green(), end_color.blue(),
                                       dialog.color_palette.speed])
                if self.main_window:
                    self.main_window.send_led_command(5, self.brightness, 0, 0, 0, custom_colors)
            elif dialog.color_palette.mode == "Моно цвет":
                if self.main_window:
                    try:
                        x, y = dialog.color_palette.points[0][0]
                        c = dialog.color_palette.get_color_at_position(x, y)
                        self.main_window.send_led_command(0, self.brightness, c.red(), c.green(), c.blue())
                    except Exception:
                        c0 = dialog.color_palette.colors[0] if dialog.color_palette.colors else QColor(0, 0, 0)
                        self.main_window.send_led_command(0, self.brightness, c0.red(), c0.green(), c0.blue())
            else:
                if self.main_window:
                    self.main_window.send_led_command(4, self.brightness, 0, 0, 0, dialog.color_palette.colors)
            # Перезагрузить профили, так как могли быть сохранены новые
            self.led_profiles = self.load_led_profiles()
            # Обновить MainWindow
            if self.main_window:
                self.main_window.led_profiles = self.led_profiles
            # Сохранить в MainWindow
            if self.main_window:
                self.main_window.save_app_config()

    def save_led_profiles(self):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            data = {}
        data["led_profiles"] = self.led_profiles
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def update_brightness_value(self, value):
        # 0 = выключить ленту; иначе минимальный полезный уровень = LED_MIN_BRIGHT (≈5%)
        try:
            v = int(value)
        except Exception:
            v = LED_MIN_BRIGHT
        if v == 0:
            self.brightness = 0
        else:
            if v < LED_MIN_BRIGHT:
                v = LED_MIN_BRIGHT
            self.brightness = v

    def update_oled_brightness_value(self, value):
        self.oled_brightness = value

    def on_oled_brightness_changed(self):
        print(f"DEBUG: OLED brightness changed to {self.oled_brightness}")
        if hasattr(self, 'main_window') and self.main_window:
            try:
                self.main_window.oled_brightness = int(self.oled_brightness)
            except Exception:
                pass
            self.main_window.send_oled_brightness(self.oled_brightness)

    def on_brightness_changed(self):
        print(f"DEBUG: Brightness changed to {self.brightness}")
        # Send brightness-only update to ESP32, preserving current LED mode/params
        if hasattr(self, 'main_window') and self.main_window:
            try:
                self.main_window.brightness = int(self.brightness)
            except Exception:
                pass
            self.main_window.send_led_brightness_only(self.brightness)

# Главный класс
class TriStateSwitch(QWidget):
    """
    Трёхпозиционный переключатель: [Стоп | Работа | Продувка]
    - Левое положение: Стоп (0)
    - Центральное: Работа (1)
    - Правое: Продувка (2)
    Перетаскивание мышью с прилипающими позициями. Плавная анимация при отпускании и
    при программном изменении состояния. Сигнал stateChanged(int, bool) включает флаг
    userInitiated для подавления обратной отправки команд при внешнем управлении.
    """
    stateChanged = Signal(int, bool)  # (state, userInitiated)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # Dimensions; will be overridden by setMetrics to match site buttons
        self.setMinimumHeight(36)
        self.setFixedHeight(40)
        self.setMouseTracking(True)

        # Geometry/config
        self._margin = 0
        self._pill_height = self.height() - 2*self._margin
        self._segment_ratio = 1.0/3.0  # каждый сегмент занимает треть трека
        self._dragging = False
        self._drag_start_x = 0.0
        self._posf = 0.0  # 0.0..1.0, 0=left(Stop), 0.5=mid(Run), 1.0=right(Purge)
        self._state = 0
        self._suppress_emit = False

        # Soft-block mode: allow dragging but do not fix to "работа/продувка",
        # keep pause color and show rotating helper messages.
        self._soft_blocked = False
        self._soft_msgs = ["подключите гидролинии", "проверьте контакты"]
        self._soft_msg_idx = 0
        self._soft_timer = QTimer(self)
        self._soft_timer.setSingleShot(False)
        self._soft_timer.setInterval(3000)
        self._soft_timer.timeout.connect(self._on_soft_tick)

        # Overlay text (takes precedence over normal labels; ignored when soft-blocked)
        self._overlay_text = None  # type: Optional[str]
        # Marquee scrolling for long overlay text
        self._marquee_enabled = False
        self._marquee_offset = 0
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setSingleShot(False)
        self._marquee_timer.setInterval(40)  # ~25 FPS
        self._marquee_timer.timeout.connect(self._on_marquee_tick)
        self._web_sync_callback = None

        # Colors (NEBULA CONTROL — glass dark + violet accents)
        self._track_bg = QColor(10, 11, 37, 160)        # rgba(10,11,37,0.63) — как .triswitch
        self._track_border = QColor(255, 255, 255, 26)  # rgba(255,255,255,0.1)
        self._pill_colors = [
            QColor(180, 60, 70),   # пауза — приглушённый красно-розовый (под палитру error)
            QColor(124, 77, 255),  # работа — primary violet (#7C4DFF)
            QColor(0, 189, 253),   # продувка — secondary cyan (#00BDFD)
        ]
        self._text_color = QColor(252, 246, 255)        # on-primary-container
        self._text_pt: Optional[int] = None  # explicit font size override

        # Animation on floating position
        self._anim = QPropertyAnimation(self, b"posf")
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.setDuration(160)

    # Expose posf as Qt Property for animation
    def get_posf(self) -> float:
        return self._posf

    def set_posf(self, v: float) -> None:
        self._posf = max(0.0, min(1.0, float(v)))
        self.update()

    posf = Property(float, fget=get_posf, fset=set_posf)

    def sizeHint(self):  # type: ignore[override]
        return self.minimumSizeHint()

    def minimumSizeHint(self):  # type: ignore[override]
        return QSize(220, 40)

    def _track_rect(self) -> QRectF:
        return QRectF(0.5, 0.5, max(1.0, self.width() - 1.0), max(1.0, self.height() - 1.0))

    def _pill_rect_from_posf(self, tr: QRectF) -> QRectF:
        # Когда отображается overlay-текст или soft-block — расширяем пилюлю,
        # чтобы вместить длинную надпись; в обычном режиме пилюля = 1/3 трека.
        wide = bool(self._overlay_text) or self._soft_blocked
        ratio = 0.62 if wide else self._segment_ratio
        pill_w = tr.width() * ratio
        pill_h = tr.height()
        left_limit = tr.left()
        right_limit = tr.right() - pill_w
        x = left_limit + (right_limit - left_limit) * self._posf
        return QRectF(x, tr.top(), pill_w, pill_h)

    def _posf_from_x(self, tr: QRectF, x: float) -> float:
        pill_w = tr.width() * self._segment_ratio
        left = tr.left() + pill_w/2
        right = tr.right() - pill_w/2
        if right <= left:
            return 0.0
        return max(0.0, min(1.0, (x - left) / (right - left)))

    def paintEvent(self, event):  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tr = self._track_rect()

        # Фон-капсула трека (тёмная стеклянная)
        p.setPen(QPen(self._track_border, 1))
        p.setBrush(self._track_bg)
        radius = 14.0
        p.drawRoundedRect(tr, radius, radius)

        labels = ["СТОП", "РАБОТА", "ПРОДУВКА"]
        font = QFont(self.font())
        font.setFamily(design_font_family())
        pt = self._text_pt if self._text_pt is not None else max(8, int(tr.height() * 0.24))
        font.setPointSize(pt)
        font.setBold(True)
        # letter-spacing визуально через uppercase-надпись и stretch шрифта
        try:
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108.0)
        except Exception:
            pass
        p.setFont(font)

        # Размер активной плитки = 1/3 трека (минус мелкий зазор)
        gap = 4.0
        # Учитываем 2 внешних + 2 внутренних зазора между 3 сегментами
        seg_w = (tr.width() - gap * 4) / 3.0
        seg_h = tr.height() - gap * 2
        seg_top = tr.top() + gap

        # ── Активная плитка (плавный сдвиг по posf 0..1) ──
        active_idx = 0 if self._soft_blocked else self._state
        active_color = self._pill_colors[active_idx]
        # Точная привязка: индекс 0 → 0, 1 → seg_w+gap, 2 → 2*(seg_w+gap)
        slot_x = tr.left() + gap + (seg_w + gap) * (self._posf * 2.0)
        active_rect = QRectF(slot_x, seg_top, seg_w, seg_h)

        # Тонкая тень-свечение под активной плиткой
        glow = QRectF(active_rect)
        glow.adjust(-2, 1, 2, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(active_color.red(), active_color.green(), active_color.blue(), 70))
        p.drawRoundedRect(glow, 11.0, 11.0)

        # Сама плитка
        p.setBrush(QColor(active_color.red(), active_color.green(), active_color.blue(), 220))
        p.drawRoundedRect(active_rect, 11.0, 11.0)
        # Лёгкая обводка
        p.setPen(QPen(QColor(active_color.red(), active_color.green(), active_color.blue(), 180), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(active_rect, 11.0, 11.0)

        # ── Подписи трёх сегментов ──
        inactive_color = QColor(202, 195, 216, 170)
        active_text_color = QColor(252, 246, 255)
        for i, lab in enumerate(labels):
            seg_rect = QRectF(tr.left() + gap + i * (seg_w + gap), seg_top, seg_w, seg_h)
            if i == active_idx and not self._overlay_text and not self._soft_blocked:
                p.setPen(active_text_color)
            else:
                p.setPen(inactive_color)
            p.drawText(seg_rect, int(Qt.AlignmentFlag.AlignCenter), lab)

        # ── Overlay-текст или soft-block hint поверх активной плитки ──
        if self._overlay_text or self._soft_blocked:
            text = self._overlay_text or ""
            if self._soft_blocked:
                try:
                    text = self._soft_msgs[self._soft_msg_idx % len(self._soft_msgs)]
                except Exception:
                    text = "подключите гидролинии"
            # Расширим прямоугольник для длинного текста: возьмём всю ширину трека
            full = QRectF(tr.left() + gap, seg_top, tr.width() - gap * 2, seg_h)
            p.setPen(active_text_color)
            fm = QFontMetrics(font)
            text_width = fm.horizontalAdvance(text)
            view_rect = full.adjusted(8, 0, -8, 0)
            if self._marquee_enabled and text_width > view_rect.width():
                p.save()
                p.setClipRect(full)
                gap2 = int(view_rect.height() * 0.4) + 20
                total = text_width + gap2
                x0 = view_rect.left() - (self._marquee_offset % max(1, total))
                y = view_rect.top()
                r1 = QRectF(x0, y, text_width, view_rect.height())
                r2 = QRectF(x0 + total, y, text_width, view_rect.height())
                p.drawText(r1, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
                p.drawText(r2, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
                p.restore()
            else:
                p.drawText(full, int(Qt.AlignmentFlag.AlignCenter), text)

    # Public: match web button metrics
    def setMetrics(self, height_px: int, text_pt: Optional[int] = None):
        try:
            height_px = int(height_px)
        except Exception:
            height_px = 40
        self.setFixedHeight(max(28, height_px))
        self._margin = 0
        self._text_pt = int(text_pt) if text_pt is not None else None
        self.update()

    def mousePressEvent(self, e):  # type: ignore[override]
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._anim.stop()
        self._drag_start_x = e.position().x()
        # Сразу подвинем пилюлю под курсор — клик по сегменту = переключение
        tr = self._track_rect()
        self.set_posf(self._posf_from_x(tr, e.position().x()))

    def mouseMoveEvent(self, e):  # type: ignore[override]
        if not self._dragging:
            return
        tr = self._track_rect()
        self.set_posf(self._posf_from_x(tr, e.position().x()))

    def mouseReleaseEvent(self, e):  # type: ignore[override]
        if not self._dragging:
            return
        self._dragging = False
        if self._soft_blocked:
            # Always return to STOP and emit state=0 only
            self._animate_to_posf(0.0)
            if self._state != 0:
                self._apply_state(0, user=True)
        else:
            # Snap to nearest third
            snap = round(self._posf * 2.0) / 2.0  # 0.0, 0.5, 1.0
            new_state = int(round(snap * 2.0))  # 0,1,2
            self._animate_to_posf(snap)
            self._apply_state(new_state, user=True)

    def _animate_to_posf(self, v: float):
        self._anim.stop()
        self._anim.setStartValue(self._posf)
        self._anim.setEndValue(max(0.0, min(1.0, v)))
        self._anim.start()

    def _apply_state(self, st: int, user: bool):
        st = max(0, min(2, int(st)))
        changed = (st != self._state)
        self._state = st
        if changed:
            # Move knob if needed
            snap = [0.0, 0.5, 1.0][st]
            self._animate_to_posf(snap)
        if not self._suppress_emit:
            self.stateChanged.emit(self._state, user)
        self.update()
        self._notify_web_sync()

    def setState(self, st: int, animated: bool = True, external: bool = False):
        self._suppress_emit = external  # suppress echo back if external
        st = max(0, min(2, int(st)))
        # Even in soft block, external state changes (e.g. forced STOP) should update label mapping
        self._state = st if not self._soft_blocked else 0
        target = [0.0, 0.5, 1.0][st]
        if animated:
            self._animate_to_posf(target)
        else:
            self.set_posf(target)
        if not self._suppress_emit:
            self.stateChanged.emit(self._state, False)
        self._suppress_emit = False
        self._notify_web_sync()

    def state(self) -> int:
        return self._state

    def setSoftBlocked(self, on: bool):
        on = bool(on)
        if self._soft_blocked == on:
            return
        self._soft_blocked = on
        self._soft_msg_idx = 0
        if on:
            # Ensure pill shows pause color and text immediately
            self._soft_timer.start()
            # Snap position back to STOP smoothly
            self._animate_to_posf(0.0)
            # Do not emit here to avoid sending duplicate SP; MainWindow logic handles STOP
        else:
            self._soft_timer.stop()
        self.update()
        self._notify_web_sync()

    def _on_soft_tick(self):
        try:
            self._soft_msg_idx = (self._soft_msg_idx + 1) % max(1, len(self._soft_msgs))
        except Exception:
            self._soft_msg_idx = 0
        self.update()

    def setOverlayText(self, text: Optional[str], marquee: bool = False):
        # Ignore overlay when soft-blocked; soft messages have priority
        new_text = (text or None)
        new_marq = bool(marquee)
        same_text = (self._overlay_text == new_text)
        same_marq = (self._marquee_enabled == new_marq)
        self._overlay_text = new_text
        self._marquee_enabled = new_marq
        # Only reset offset if content/state changed
        if not (same_text and same_marq):
            self._marquee_offset = 0
        # Start/stop marquee timer lazily; actual need checked in paintEvent for width
        if self._overlay_text and self._marquee_enabled:
            self._marquee_timer.start()
        else:
            self._marquee_timer.stop()
        self.update()
        self._notify_web_sync()

    def _notify_web_sync(self):
        cb = getattr(self, '_web_sync_callback', None)
        if callable(cb):
            try:
                cb(self)
            except Exception:
                pass

    def clearOverlayText(self):
        self.setOverlayText(None, marquee=False)

    def _on_marquee_tick(self):
        # Increase monotonically; wrapping handled in paintEvent by modulo text cycle length
        self._marquee_offset += 1
        self.update()


# ---------------------------------------------------------------------------
# NEBULA CONTROL — composite glass cards (Stitch design parity)
# ---------------------------------------------------------------------------

def _hex_rgb(h: str) -> str:
    h = h.lstrip("#")
    return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"


# ---------------------------------------------------------------------------
# Векторные иконки (без зависимости от Material Symbols / эмодзи-шрифтов).
# Все иконки рисуются QPainter'ом по линиям (stroke) — стабильны на любой ОС.
# ---------------------------------------------------------------------------

def _parse_color(value) -> QColor:
    """Преобразовать строку (#hex / rgba(r,g,b,a) / именованный цвет) или QColor в QColor."""
    if isinstance(value, QColor):
        return QColor(value)
    s = str(value).strip()
    if s.lower().startswith("rgba(") and s.endswith(")"):
        try:
            parts = [p.strip() for p in s[5:-1].split(",")]
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            a = int(parts[3]) if len(parts) > 3 else 255
            return QColor(r, g, b, a)
        except Exception:
            return QColor(202, 195, 216, 255)
    if s.lower().startswith("rgb(") and s.endswith(")"):
        try:
            parts = [int(p.strip()) for p in s[4:-1].split(",")]
            return QColor(parts[0], parts[1], parts[2])
        except Exception:
            return QColor(202, 195, 216, 255)
    c = QColor(s)
    return c if c.isValid() else QColor(202, 195, 216, 255)


def _icon_pixmap(key: str, size: int = 20, color="#cac3d8",
                 stroke: float = 1.6) -> QPixmap:
    """Сгенерировать QPixmap с иконкой по ключу."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = _parse_color(color)
    pen = QPen(c)
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)
    pad = s * 0.15
    inner = s - 2*pad

    if key == "dashboard":
        # 4 квадрата 2×2
        gap = s * 0.06
        sz = (inner - gap) / 2
        for r in range(2):
            for col in range(2):
                x = pad + col * (sz + gap)
                y = pad + r * (sz + gap)
                p.drawRoundedRect(QRectF(x, y, sz, sz), 2.0, 2.0)
    elif key == "drop":
        # Капля: треугольник с округлым низом
        path = QPainterPath()
        path.moveTo(s/2, pad)
        path.cubicTo(s - pad, s*0.45,  s - pad*1.2, s - pad,  s/2, s - pad)
        path.cubicTo(pad*1.2, s - pad,  pad, s*0.45,  s/2, pad)
        p.drawPath(path)
    elif key == "spark":
        # 4-конечная звезда (искра)
        cx, cy = s/2, s/2
        p.drawLine(QPointF(cx, pad), QPointF(cx, s - pad))
        p.drawLine(QPointF(pad, cy), QPointF(s - pad, cy))
        d = inner * 0.28
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
    elif key == "sparkle":
        # ✦ — четырёхлучевая звезда с вогнутыми гранями (как в макете-логотипе)
        import math
        cx, cy = s/2, s/2
        r_out = inner * 0.50
        r_in = inner * 0.16
        path = QPainterPath()
        for i in range(8):
            a = (i / 8.0) * 2 * math.pi - math.pi/2
            r = r_out if (i % 2 == 0) else r_in
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
    elif key == "led_sun":
        # Солнце: центральный круг + 8 лучей (под пункт «Подсветка»)
        import math
        cx, cy = s/2, s/2
        r = inner * 0.20
        p.drawEllipse(QPointF(cx, cy), r, r)
        ray_in = inner * 0.30
        ray_out = inner * 0.45
        for i in range(8):
            a = (i / 8.0) * 2 * math.pi
            x1 = cx + ray_in * math.cos(a)
            y1 = cy + ray_in * math.sin(a)
            x2 = cx + ray_out * math.cos(a)
            y2 = cy + ray_out * math.sin(a)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    elif key == "settings_sliders":
        # 3 горизонтальных слайдера с круглыми ручками на разных позициях
        cx_left = pad
        cx_right = s - pad
        knob_r = inner * 0.10
        positions = [0.30, 0.62, 0.42]  # x-доли ручек на каждой строке
        for i, pos in enumerate(positions):
            y = pad + inner * (0.18 + i * 0.32)
            knob_cx = pad + inner * pos
            # линия слева до ручки
            p.drawLine(QPointF(cx_left, y), QPointF(knob_cx - knob_r * 1.5, y))
            # линия справа от ручки
            p.drawLine(QPointF(knob_cx + knob_r * 1.5, y), QPointF(cx_right, y))
            # ручка
            p.drawEllipse(QPointF(knob_cx, y), knob_r, knob_r)
    elif key == "thermo":
        # Термометр: вертикальная капсула + шарик
        bw = inner * 0.34
        x0 = (s - bw) / 2
        top = pad
        bulb_r = bw * 0.95
        # Вертикальный ствол
        path = QPainterPath()
        path.moveTo(x0, top + bw/2)
        path.arcTo(x0, top, bw, bw, 180, -180)
        path.lineTo(x0 + bw, s - pad - bulb_r * 1.2)
        # Шарик
        path.arcTo(x0 - bulb_r*0.45, s - pad - bulb_r*1.7, bw + bulb_r*0.9,
                   bw + bulb_r*0.9, 60, -300)
        path.closeSubpath()
        p.drawPath(path)
        # Шкала
        for i in range(3):
            yy = top + bw + i * (inner*0.18)
            p.drawLine(QPointF(x0 + bw + 1, yy),
                       QPointF(x0 + bw + bw*0.4, yy))
    elif key == "gear":
        # Шестерёнка: круг + 8 зубцов
        cx, cy = s/2, s/2
        r_out = inner * 0.42
        r_in = inner * 0.30
        teeth = 8
        path = QPainterPath()
        import math
        for i in range(teeth*2):
            a = (i / (teeth*2.0)) * 2 * math.pi - math.pi/2
            r = r_out if (i % 2 == 0) else r_in
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)
        # Внутренний круг
        p.drawEllipse(QPointF(cx, cy), inner*0.12, inner*0.12)
    elif key == "cyclone":
        # Циклон / вентилятор: 3 лопасти, изгибы вокруг центра
        import math
        cx, cy = s/2, s/2
        r = inner * 0.42
        for i in range(3):
            a0 = i * 120 - 90
            path = QPainterPath()
            path.moveTo(cx, cy)
            ax = cx + r * math.cos(math.radians(a0))
            ay = cy + r * math.sin(math.radians(a0))
            ctrl_x = cx + r * 0.7 * math.cos(math.radians(a0 + 60))
            ctrl_y = cy + r * 0.7 * math.sin(math.radians(a0 + 60))
            path.quadTo(ctrl_x, ctrl_y, ax, ay)
            p.drawPath(path)
        # центральная точка
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy), inner*0.07, inner*0.07)
    elif key == "info":
        # Круг + i
        cx, cy = s/2, s/2
        r = inner * 0.45
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.drawLine(QPointF(cx, cy - r*0.45), QPointF(cx, cy - r*0.25))
        p.drawLine(QPointF(cx, cy - r*0.05), QPointF(cx, cy + r*0.45))
    elif key == "power":
        # Кнопка питания: ⏻
        cx, cy = s/2, s/2
        r = inner * 0.42
        # Дуга (открытая сверху)
        rect = QRectF(cx - r, cy - r, 2*r, 2*r)
        p.drawArc(rect, int(120 * 16), int(300 * 16))
        # Вертикальная палочка
        p.drawLine(QPointF(cx, cy - r*1.05), QPointF(cx, cy - r*0.1))
    elif key == "terminal":
        # Терминал: рамка + стрелка > и нижнее подчёркивание
        rect = QRectF(pad, pad + inner*0.1, inner, inner*0.8)
        p.drawRoundedRect(rect, 2.0, 2.0)
        # стрелка
        ax = pad + inner*0.22
        ay = pad + inner*0.35
        p.drawLine(QPointF(ax, ay), QPointF(ax + inner*0.2, ay + inner*0.18))
        p.drawLine(QPointF(ax + inner*0.2, ay + inner*0.18),
                   QPointF(ax, ay + inner*0.36))
        # подчёркивание справа
        p.drawLine(QPointF(pad + inner*0.5, pad + inner*0.74),
                   QPointF(pad + inner*0.78, pad + inner*0.74))
    elif key == "minus":
        # Тонкая горизонтальная линия по центру
        y = s/2
        pad2 = s * 0.28
        p.drawLine(QPointF(pad2, y), QPointF(s - pad2, y))
    elif key == "close":
        # Крестик
        pad2 = s * 0.28
        p.drawLine(QPointF(pad2, pad2), QPointF(s - pad2, s - pad2))
        p.drawLine(QPointF(s - pad2, pad2), QPointF(pad2, s - pad2))
    elif key == "verified":
        # Печать с галочкой (упрощённо: круг + ✓)
        cx, cy = s/2, s/2
        r = inner * 0.42
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.drawLine(QPointF(cx - r*0.45, cy + r*0.05),
                   QPointF(cx - r*0.05, cy + r*0.40))
        p.drawLine(QPointF(cx - r*0.05, cy + r*0.40),
                   QPointF(cx + r*0.50, cy - r*0.30))
    elif key == "thermo_fill":
        # Заполненный термометр: точная геометрия SVG 12x12 из HTML-макета.
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        u = s / 12.0
        p.drawRoundedRect(QRectF(4.7*u, 1.0*u, 2.6*u, 7.8*u), 1.3*u, 1.3*u)
        p.drawEllipse(QPointF(6.0*u, 9.5*u), 2.2*u, 2.2*u)
    elif key == "fan_blade":
        # 4 заполненные лопасти + центральный круг: точная геометрия SVG 12x12.
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        u = s / 12.0
        cx, cy = 6.0*u, 6.0*u
        path = QPainterPath()
        path.moveTo(6.0*u, 4.8*u)
        path.cubicTo(6.5*u, 2.2*u, 10.8*u, 1.3*u, 10.8*u, 4.5*u)
        path.cubicTo(10.8*u, 6.1*u, 8.1*u, 6.4*u, 6.0*u, 6.1*u)
        path.closeSubpath()
        for ang in (0, 90, 180, 270):
            p.save()
            p.translate(cx, cy)
            p.rotate(ang)
            p.translate(-cx, -cy)
            p.drawPath(path)
            p.restore()
        p.drawEllipse(QPointF(cx, cy), 1.3*u, 1.3*u)
    elif key == "info_fill":
        # Заполненный круг с «вырезанным» i: точная геометрия SVG 12x12.
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        u = s / 12.0
        cx, cy = 6.0*u, 6.0*u
        r = 5.2*u
        path.addEllipse(QPointF(cx, cy), r, r)
        path.addEllipse(QPointF(cx, 3.6*u), 0.85*u, 0.85*u)
        path.addRect(QRectF(5.3*u, 5.4*u, 1.4*u, 3.5*u))
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
    elif key == "bolt":
        # Заполненная молния: точная геометрия SVG 12x12.
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        u = s / 12.0
        path = QPainterPath()
        path.moveTo(7*u, 1*u)
        path.lineTo(3*u, 7*u)
        path.lineTo(6*u, 7*u)
        path.lineTo(5*u, 11*u)
        path.lineTo(9*u, 5*u)
        path.lineTo(6*u, 5*u)
        path.closeSubpath()
        p.drawPath(path)
    else:
        # fallback: маленький квадрат
        p.drawRoundedRect(QRectF(pad, pad, inner, inner), 3.0, 3.0)
    p.end()
    return pm


def _icon_label(key: str, size: int = 18, color: str = "#cac3d8") -> QLabel:
    """QLabel со встроенной нарисованной иконкой (для inline-вставки в layout)."""
    lbl = QLabel()
    lbl.setPixmap(_icon_pixmap(key, size=size, color=color))
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet("background: transparent; border: none;")
    return lbl


class _GlassCard(QFrame):
    """Glass-карта с радиальными «блобами» и тонкой обводкой (как .metric-card / .fan-card / .info-card в макете).

    blobs: список кортежей (cx_frac, cy_frac, r_frac, color_hex_or_rgb, alpha_0_255).
    Каждый блоб — мягкий радиальный градиент: cx/cy от 0 до 1 (доли от ширины/высоты),
    r_frac — радиус как доля от max(w,h), color — пиковый цвет с указанной alpha.
    """
    def __init__(self, parent: Optional[QWidget] = None, radius: int = 16,
                 blobs: Optional[list] = None, base_alpha: int = 170,
                 border_alpha: int = 18):
        super().__init__(parent)
        self._radius = int(radius)
        self._blobs = list(blobs or [])
        self._base = QColor(14, 16, 40, base_alpha)
        self._border = QColor(255, 255, 255, border_alpha)
        self._top_hl = QColor(255, 255, 255, 16)
        # Без QSS-фона: всё рисуется в paintEvent
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setStyleSheet("")

    def setBlobs(self, blobs: list):
        self._blobs = list(blobs or [])
        self.update()

    def setBaseColor(self, c: QColor):
        self._base = QColor(c)
        self.update()

    def setBorderColor(self, c: QColor):
        self._border = QColor(c)
        self.update()

    def paintEvent(self, e):  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        # Заливаем по контуру (клип)
        p.save()
        p.setClipPath(path)
        # Базовый цвет
        p.fillRect(self.rect(), self._base)
        # Радиальные блобы
        w = float(self.width()); h = float(self.height())
        diag = max(w, h)
        for cx_frac, cy_frac, r_frac, col, alpha in self._blobs:
            cx = w * float(cx_frac)
            cy = h * float(cy_frac)
            rad = max(20.0, diag * float(r_frac))
            grad = QRadialGradient(QPointF(cx, cy), rad)
            base = _parse_color(col)
            c0 = QColor(base); c0.setAlpha(int(alpha))
            c1 = QColor(base); c1.setAlpha(0)
            grad.setColorAt(0.0, c0)
            grad.setColorAt(1.0, c1)
            p.fillRect(self.rect(), grad)
        p.restore()
        # Тонкая верхняя «глянцевая» подсветка (inset top highlight)
        if self._top_hl.alpha() > 0:
            p.setPen(QPen(self._top_hl, 1))
            p.drawLine(QPointF(self._radius, 1.5),
                       QPointF(self.width() - self._radius, 1.5))
        # Обводка
        p.setPen(QPen(self._border, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


# Палитры блобов под каждую карточку — взяты 1:1 с CSS макета (appDESIGN/design-preview.html).
_BLOBS_CPU  = [(0.92, 0.08, 0.95, "#8bd5ff", 20), (0.08, 0.90, 0.55, "rgb(80,150,220)", 13)]
_BLOBS_GPU  = [(0.12, 0.12, 0.85, "#cdbdff", 20), (0.90, 0.90, 0.60, "#7c4dff", 15)]
_BLOBS_WAT  = [(0.50, 1.05, 0.80, "rgb(70,215,190)", 18), (0.88, 0.08, 0.50, "#8bd5ff", 13)]
_BLOBS_FAN1 = [(0.98, 0.50, 0.85, "#cdbdff", 18), (0.02, 0.80, 0.70, "#8bd5ff", 10)]
_BLOBS_FAN2 = [(0.02, 0.50, 0.85, "#8bd5ff", 18), (0.96, 0.20, 0.70, "#cdbdff", 10)]
_BLOBS_INFO = [(0.82, 0.85, 0.85, "#7c4dff", 20),
               (0.08, 0.15, 0.70, "#8bd5ff", 15),
               (0.55, 0.05, 0.50, "#cdbdff", 10)]


class _MetricBar(QWidget):
    """Тонкая полоска прогресса с градиентной заливкой и «светящейся» точкой на конце (как .metric-bar-fill::after)."""
    def __init__(self, accent: str = "#8bd5ff", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._accent = _parse_color(accent)
        self._pct = 0.0
        self.setFixedHeight(14)  # 4px бар + место под свечение
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setAccent(self, color):
        self._accent = _parse_color(color)
        self.update()

    def setPct(self, p: float):
        self._pct = max(0.0, min(1.0, float(p)))
        self.update()

    def paintEvent(self, e):  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        h = 4.0
        y = (self.height() - h) / 2.0
        w_total = float(self.width())
        # Фон
        bg = QColor(self._accent); bg.setAlpha(36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, y, w_total, h), 2.0, 2.0)
        # Заливка
        fill_w = w_total * self._pct
        if fill_w > 1.0:
            light = QColor(self._accent).lighter(125)
            grad = QLinearGradient(0, 0, fill_w, 0)
            grad.setColorAt(0.0, self._accent)
            grad.setColorAt(1.0, light)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(0, y, fill_w, h), 2.0, 2.0)
            # Свечение на конце
            cx = max(3.5, fill_w - 1.0)
            cy = self.height() / 2.0
            # halo (большой мягкий радиальный)
            halo = QRadialGradient(QPointF(cx, cy), 10.0)
            h0 = QColor(self._accent); h0.setAlpha(140)
            h1 = QColor(self._accent); h1.setAlpha(0)
            halo.setColorAt(0.0, h0)
            halo.setColorAt(1.0, h1)
            p.setBrush(QBrush(halo))
            p.drawEllipse(QPointF(cx, cy), 10.0, 10.0)
            # точка
            dot = QColor(self._accent).lighter(120)
            p.setBrush(dot)
            p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
        p.end()


def _temp_bar_color(val: float) -> str:
    """Плавная интерполяция цвета бара по температуре (как в design-preview.html).
    0–30: голубой; 30–45: голубой→розовый; 45–65: розовый; 65–85: розовый→красный."""
    def _lerp(a, b, t):
        t = max(0.0, min(1.0, t))
        ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
        br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
        return "#{:02x}{:02x}{:02x}".format(
            int(round(ar + (br - ar) * t)),
            int(round(ag + (bg - ag) * t)),
            int(round(ab + (bb - ab) * t)),
        )
    BLUE, PINK, RED = "#8bd5ff", "#ff85c2", "#ff2828"
    try:
        v = float(val)
    except Exception:
        return BLUE
    if v <= 30: return BLUE
    if v <= 45: return _lerp(BLUE, PINK, (v - 30) / 15.0)
    if v <= 65: return PINK
    return _lerp(PINK, RED, (v - 65) / 20.0)


class MetricCard(_GlassCard):
    """Карта температуры: подпись (CPU/GPU/Вода), большое число, °C, прогресс-бар.
    Использует радиальные блобы _BLOBS_* по семантическому ключу.
    """
    _BLOB_MAP = {
        "cpu": _BLOBS_CPU, "gpu": _BLOBS_GPU, "вода": _BLOBS_WAT,
        "water": _BLOBS_WAT,
    }

    def __init__(self, caption: str, accent: str = "#8bd5ff",
                 blobs: Optional[list] = None, parent: Optional[QWidget] = None):
        key = (caption or "").strip().lower()
        if blobs is None:
            blobs = self._BLOB_MAP.get(key, _BLOBS_CPU)
        super().__init__(parent, radius=16, blobs=blobs)
        self._accent = accent
        self._pct = 0.0
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(4)
        self.cap = QLabel(caption.upper())
        self.cap.setStyleSheet(
            "color: rgba(202,195,216,180); font-size: 8pt; font-weight: 700;"
            " letter-spacing: 1.5px; background: transparent; border: none;"
        )
        apply_label_typography(self.cap, 8, QFont.Weight.Bold, 1.5)
        v.addWidget(self.cap)
        row = QHBoxLayout()
        row.setSpacing(2)
        row.setContentsMargins(0, 0, 0, 0)
        self.value_lbl = QLabel("--")
        self.value_lbl.setStyleSheet(
            f"color: {accent}; font-size: 22pt; font-weight: 700;"
            " background: transparent; border: none;"
        )
        apply_label_typography(self.value_lbl, 22, QFont.Weight.Bold)
        self.unit_lbl = QLabel("°C")
        self.unit_lbl.setStyleSheet(
            f"color: {accent}; font-size: 10pt; background: transparent; border: none;"
        )
        apply_label_typography(self.unit_lbl, 10, QFont.Weight.Normal)
        row.addWidget(self.value_lbl, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addWidget(self.unit_lbl, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addStretch(1)
        v.addLayout(row)
        # Прогресс-бар со светящейся точкой
        self._bar = _MetricBar(accent)
        v.addWidget(self._bar)

    def setValue(self, value: Any, unit: str = "°C", max_for_bar: float = 100.0):
        num_val = None
        if value in (None, "", "--"):
            self.value_lbl.setText("--")
            self._pct = 0.0
        else:
            try:
                num = float(value)
                num_val = num
                self.value_lbl.setText(f"{int(round(num))}")
                self._pct = max(0.0, min(1.0, num / max(1.0, max_for_bar)))
            except Exception:
                self.value_lbl.setText(str(value))
                self._pct = 0.0
        self.unit_lbl.setText(unit)
        # Цвет бара и цифр по температуре (как в макете: blue→pink→red)
        if num_val is not None and unit in ("°C", "C", "c"):
            col = _temp_bar_color(num_val)
            self._bar.setAccent(col)
            self.value_lbl.setStyleSheet(
                f"color: {col}; font-size: 22pt; font-weight: 700;"
                " background: transparent; border: none;"
            )
            apply_label_typography(self.value_lbl, 22, QFont.Weight.Bold)
            self.unit_lbl.setStyleSheet(
                f"color: {col}; font-size: 10pt; background: transparent; border: none;"
            )
            apply_label_typography(self.unit_lbl, 10, QFont.Weight.Normal)
        self._bar.setPct(self._pct)

    def setAccent(self, color: str):
        self._accent = color
        self.value_lbl.setStyleSheet(
            f"color: {color}; font-size: 22pt; font-weight: 700;"
            " background: transparent; border: none;"
        )
        apply_label_typography(self.value_lbl, 22, QFont.Weight.Bold)
        self.unit_lbl.setStyleSheet(
            f"color: {color}; font-size: 10pt; background: transparent; border: none;"
        )
        apply_label_typography(self.unit_lbl, 10, QFont.Weight.Normal)
        self._bar.setAccent(color)


class _FanSpinIcon(QWidget):
    """Вращающаяся иконка вентилятора — соответствует анимации .fan-icon { animation: fan-spin } в макете."""
    def __init__(self, size: int = 44, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._size = int(size)
        self.setFixedSize(self._size, self._size)
        self._angle = 0.0
        self._period_ms = 1800   # 1.8s оборот (как в CSS-анимации)
        self._fps = 30
        self._spin = True
        self._color = QColor(205, 189, 255, 140)  # rgba(205,189,255,0.55)
        self._bg = QColor(49, 50, 78, 160)
        self._border = QColor(255, 255, 255, 22)
        self._icon_size = max(16, int(self._size * 0.6))
        self._pix = _icon_pixmap("fan_blade", size=self._icon_size, color=self._color)
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / self._fps))
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setSpin(self, on: bool):
        on = bool(on)
        if on and not self._timer.isActive():
            self._timer.start()
        elif (not on) and self._timer.isActive():
            self._timer.stop()
        self._spin = on
        if not on:
            self._angle = 0.0
        self.update()

    def setColors(self, icon: QColor, bg: QColor, border: QColor):
        self._color = QColor(icon)
        self._bg = QColor(bg)
        self._border = QColor(border)
        self._pix = _icon_pixmap("fan_blade", size=self._icon_size, color=self._color)
        self.update()

    def _on_tick(self):
        # 360° за period_ms
        step = 360.0 * (self._timer.interval() / float(self._period_ms))
        self._angle = (self._angle + step) % 360.0
        self.update()

    def paintEvent(self, e):  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Кружок-подложка
        r = min(self._size, self._size) / 2.0 - 0.5
        cx = self._size / 2.0
        cy = self._size / 2.0
        p.setPen(QPen(self._border, 1))
        p.setBrush(self._bg)
        p.drawEllipse(QPointF(cx, cy), r, r)
        # Иконка с поворотом
        p.translate(cx, cy)
        p.rotate(self._angle)
        p.translate(-self._icon_size / 2.0, -self._icon_size / 2.0)
        p.drawPixmap(0, 0, self._pix)
        p.end()


class FanCard(_GlassCard):
    """Карта вентилятора: подпись + RPM-значение слева, вращающаяся иконка-кружок справа."""
    def __init__(self, caption: str, parent: Optional[QWidget] = None,
                 blobs: Optional[list] = None):
        super().__init__(parent, radius=16, blobs=(blobs or _BLOBS_FAN1))
        self._caption = caption.upper()
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        self.cap = QLabel(self._caption)
        self.cap.setStyleSheet(
            "color: rgba(202,195,216,180); font-size: 8pt; font-weight: 700;"
            " letter-spacing: 1.5px; background: transparent; border: none;"
        )
        apply_label_typography(self.cap, 8, QFont.Weight.Bold, 1.5)
        col.addWidget(self.cap)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)
        self.value_lbl = QLabel("--")
        self.value_lbl.setStyleSheet(
            "color: #e1e0ff; font-size: 20pt; font-weight: 600;"
            " background: transparent; border: none;"
        )
        apply_label_typography(self.value_lbl, 20, QFont.Weight.DemiBold)
        self.unit_lbl = QLabel("RPM")
        self.unit_lbl.setStyleSheet(
            "color: rgba(202,195,216,180); font-size: 8pt; font-weight: 700;"
            " letter-spacing: 1px; background: transparent; border: none;"
        )
        apply_label_typography(self.unit_lbl, 8, QFont.Weight.Bold, 1.0)
        row.addWidget(self.value_lbl, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addWidget(self.unit_lbl, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addStretch(1)
        col.addLayout(row)
        h.addLayout(col, 1)
        # Вращающаяся иконка справа
        self.icon = _FanSpinIcon(size=44)
        h.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self._alarm = False

    def setRpm(self, value: Any):
        if value in (None, "", "--"):
            self.value_lbl.setText("--")
            try: self.icon.setSpin(False)
            except Exception: pass
        else:
            try:
                v = int(value)
                self.value_lbl.setText(f"{v}")
                try: self.icon.setSpin(v > 0)
                except Exception: pass
            except Exception:
                self.value_lbl.setText(str(value))

    def setAlarm(self, on: bool, message: str = ""):
        on = bool(on)
        if on:
            self.value_lbl.setStyleSheet(
                "color: #ffaf56; font-size: 20pt; font-weight: 600;"
                " background: transparent; border: none;"
            )
            apply_label_typography(self.value_lbl, 20, QFont.Weight.DemiBold)
            try:
                self.icon.setColors(QColor("#ffaf56"),
                                    QColor(255, 175, 86, 40),
                                    QColor(255, 175, 86, 140))
                self.icon.setSpin(False)
            except Exception:
                pass
            self.cap.setText(f"{self._caption} · {message.upper()}" if message else self._caption)
            apply_label_typography(self.cap, 8, QFont.Weight.Bold, 1.5)
            self.setBaseColor(QColor(40, 18, 12, 200))
            self.setBorderColor(QColor(255, 175, 86, 140))
        else:
            self.value_lbl.setStyleSheet(
                "color: #e1e0ff; font-size: 20pt; font-weight: 600;"
                " background: transparent; border: none;"
            )
            apply_label_typography(self.value_lbl, 20, QFont.Weight.DemiBold)
            try:
                self.icon.setColors(QColor(205, 189, 255, 140),
                                    QColor(49, 50, 78, 160),
                                    QColor(255, 255, 255, 22))
                self.icon.setSpin(True)
            except Exception:
                pass
            self.cap.setText(self._caption)
            apply_label_typography(self.cap, 8, QFont.Weight.Bold, 1.5)
            self.setBaseColor(QColor(14, 16, 40, 170))
            self.setBorderColor(QColor(255, 255, 255, 18))
        self._alarm = on


class InfoCard(_GlassCard):
    """Широкая карта статуса: Цели + бэйдж связи; разделитель; Профиль + статус гидролиний."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, radius=18, blobs=_BLOBS_INFO)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(10)
        # Верхняя строка: Цели + бэйдж связи
        top = QHBoxLayout()
        top.setSpacing(10)
        col_t = QVBoxLayout()
        col_t.setSpacing(2)
        self._cap_targets = QLabel("ЦЕЛИ")
        self._cap_targets.setStyleSheet(
            "color: rgba(202,195,216,160); font-size: 8pt; font-weight: 700;"
            " letter-spacing: 1.5px; background: transparent; border: none;"
        )
        apply_label_typography(self._cap_targets, 8, QFont.Weight.Bold, 1.5)
        self.targets_lbl = QLabel("--")
        self.targets_lbl.setStyleSheet(
            "color: #e1e0ff; font-size: 11pt; background: transparent; border: none;"
        )
        apply_label_typography(self.targets_lbl, 11, QFont.Weight.Normal)
        col_t.addWidget(self._cap_targets)
        col_t.addWidget(self.targets_lbl)
        top.addLayout(col_t, 1)
        self.link_badge = QLabel("Связь: --")
        self.link_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_link_badge_style(active=False)
        top.addWidget(self.link_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(top)
        # Разделитель
        sep = QFrame(self)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,18); border: none;")
        v.addWidget(sep)
        # Нижняя строка: Профиль + статус гидролиний
        bot = QHBoxLayout()
        bot.setSpacing(10)
        col_b = QVBoxLayout()
        col_b.setSpacing(2)
        cap_p = QLabel("ПРОФИЛЬ")
        cap_p.setStyleSheet(
            "color: rgba(202,195,216,160); font-size: 8pt; font-weight: 700;"
            " letter-spacing: 1.5px; background: transparent; border: none;"
        )
        apply_label_typography(cap_p, 8, QFont.Weight.Bold, 1.5)
        self.profile_lbl = QLabel("--")
        self.profile_lbl.setStyleSheet(
            "color: #e1e0ff; font-size: 11pt; background: transparent; border: none;"
        )
        apply_label_typography(self.profile_lbl, 11, QFont.Weight.Normal)
        col_b.addWidget(cap_p)
        col_b.addWidget(self.profile_lbl)
        bot.addLayout(col_b, 1)
        self.loop_lbl = QLabel("Гидролинии: --")
        self.loop_lbl.setStyleSheet(
            "color: #cac3d8; font-size: 11pt; background: transparent; border: none;"
        )
        apply_label_typography(self.loop_lbl, 11, QFont.Weight.Normal)
        self.loop_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bot.addWidget(self.loop_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(bot)

    def _set_link_badge_style(self, active: bool):
        if active:
            self.link_badge.setStyleSheet(
                "background-color: rgba(124,77,255,55);"
                " border: 1px solid rgba(124,77,255,160);"
                " border-radius: 12px; padding: 4px 12px;"
                " color: #cdbdff; font-size: 9pt; font-weight: 700;"
                " letter-spacing: 1px;"
            )
            apply_label_typography(self.link_badge, 9, QFont.Weight.Bold, 1.0)
        else:
            self.link_badge.setStyleSheet(
                "background-color: rgba(255,255,255,18);"
                " border: 1px solid rgba(255,255,255,28);"
                " border-radius: 12px; padding: 4px 12px;"
                " color: rgba(202,195,216,200); font-size: 9pt; font-weight: 700;"
                " letter-spacing: 1px;"
            )
            apply_label_typography(self.link_badge, 9, QFont.Weight.Bold, 1.0)

    def setTargets(self, text: str):
        t = (text or "").strip()
        if t.lower().startswith("цели:"):
            t = t.split(":", 1)[1].strip()
        self.targets_lbl.setText(t or "--")

    def setProfile(self, name: str):
        self.profile_lbl.setText(name or "--")

    def setLink(self, text: str):
        t = (text or "").strip()
        if t.lower().startswith("связь:"):
            t = t.split(":", 1)[1].strip()
        active = bool(t) and "—" not in t and "--" not in t and "ошибк" not in t.lower() and "нет" not in t.lower()
        self.link_badge.setText(t if t else "Связь: --")
        self._set_link_badge_style(active)

    def setLoop(self, text: str, ok: bool):
        self.loop_lbl.setText(text or "Гидролинии: --")
        if ok:
            self.loop_lbl.setStyleSheet(
                "color: #8bd5ff; font-size: 11pt;"
                " background: transparent; border: none;"
            )
        else:
            self.loop_lbl.setStyleSheet(
                "color: #ffb4ab; font-size: 11pt;"
                " background: transparent; border: none;"
            )
        apply_label_typography(self.loop_lbl, 11, QFont.Weight.Normal)

    def setText(self, html_or_text: str):  # type: ignore[override]
        """Compat: принимает старый HTML '<p>...</p><p>...</p><p>...</p>'
        и раскладывает по полям карты."""
        try:
            import re as _re
            txt = html_or_text or ""
            parts = _re.findall(r"<p[^>]*>(.*?)</p>", txt, flags=_re.IGNORECASE | _re.DOTALL)
            if not parts:
                self.setTargets(txt)
                return
            tgt = parts[0] if len(parts) > 0 else "--"
            prof = parts[1] if len(parts) > 1 else "--"
            link = parts[2] if len(parts) > 2 else "--"
            if prof.lower().startswith("профиль:"):
                prof = prof.split(":", 1)[1].strip()
            self.setTargets(tgt)
            self.setProfile(prof)
            self.setLink(link)
        except Exception:
            pass



class SidebarNavButton(QPushButton):
    """Пункт навигации левой боковой панели — с цветной полоской-индикатором слева."""
    def __init__(self, icon_key: str, label: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self._icon_key = icon_key
        self._active = False

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 14, 0)
        h.setSpacing(0)
        # Полоска-индикатор удалена (по макету её нет — активность отмечается только фоном)
        self._accent = QFrame()
        self._accent.setFixedWidth(0)
        self._accent.setVisible(False)
        self._accent.setStyleSheet("background: transparent; border: none;")
        # Внутренний бокс с иконкой и текстом
        inner = QWidget()
        inner.setStyleSheet("background: transparent; border: none;")
        ih = QHBoxLayout(inner)
        ih.setContentsMargins(13, 0, 0, 0)
        ih.setSpacing(12)
        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(20, 20)
        self._icon_lbl.setStyleSheet("background: transparent; border: none;")
        self._text = QLabel(label)
        self._text.setStyleSheet(
            "background: transparent; border: none;"
            " font-size: 10pt; font-weight: 600; letter-spacing: 0.2px;"
        )
        ih.addWidget(self._icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        ih.addWidget(self._text, 1, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(inner, 1)

        self._apply_style(False)
        self._refresh_icon(False)
        self.toggled.connect(self._on_toggled)

    def _apply_style(self, active: bool):
        if active:
            self.setStyleSheet(
                "QPushButton { text-align: left; padding: 0; border: none;"
                " border-radius: 12px;"
                " background: rgba(124,77,255,42); }"
                "QPushButton:hover { background: rgba(124,77,255,60); }"
            )
            self._accent.setStyleSheet(
                "background: transparent; border: none;"
            )
            self._text.setStyleSheet(
                "background: transparent; border: none; color: #ffffff;"
                " font-size: 10pt; font-weight: 700; letter-spacing: 0.2px;"
            )
            apply_label_typography(self._text, 10, QFont.Weight.Bold, 0.2)
        else:
            self.setStyleSheet(
                "QPushButton { text-align: left; padding: 0; border: none;"
                " border-radius: 12px; background: transparent; }"
                "QPushButton:hover { background: rgba(255,255,255,18); }"
            )
            self._accent.setStyleSheet("background: transparent; border: none;")
            self._text.setStyleSheet(
                "background: transparent; border: none;"
                " color: rgba(202,195,216,210);"
                " font-size: 10pt; font-weight: 600; letter-spacing: 0.2px;"
            )
            apply_label_typography(self._text, 10, QFont.Weight.DemiBold, 0.2)

    def _refresh_icon(self, active: bool):
        col = QColor(255, 255, 255) if active else QColor(202, 195, 216, 210)
        self._icon_lbl.setPixmap(_icon_pixmap(self._icon_key, size=20, color=col, stroke=1.4))

    def _on_toggled(self, active: bool):
        self._active = bool(active)
        self._apply_style(self._active)
        self._refresh_icon(self._active)


class WindowControlButton(QPushButton):
    """Кнопка управления окном — скруглённый квадрат 27×27 (по макету .win-btn)."""
    def __init__(self, icon_key: str, hover_color: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(27, 27)
        # Текстовые иконки как в макете («—» / «✕»)
        if icon_key == "minus":
            self.setText("—")
        elif icon_key == "close":
            self.setText("✕")
        else:
            self.setText("")
        css = (
            "QPushButton {"
            "  background: rgba(255,255,255,14);"
            "  border: 1px solid rgba(255,255,255,22);"
            "  border-radius: 8px;"
            "  color: #cac3d8;"
            "  font-size: 11px; font-weight: 500;"
            "  padding: 0px;"
            "  min-width: 27px; max-width: 27px;"
            "  min-height: 27px; max-height: 27px;"
            "}"
            "QPushButton:hover {"
            "  background: __HOVER__;"
            "  border: 1px solid rgba(205,189,255,72);"
            "  color: #e1e0ff;"
            "}"
            "QPushButton:pressed {"
            "  background: rgba(255,255,255,28);"
            "}"
        ).replace("__HOVER__", hover_color)
        self.setStyleSheet(css)


class DragHandle(QWidget):
    """Прозрачная зона, по которой можно тащить безрамочное окно."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._drag_pos = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, QPushButton):
                self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.window()
            if hasattr(w, "_toggle_maximize"):
                w._toggle_maximize()
        super().mouseDoubleClickEvent(event)


class _RoundedWindowFrame(QWidget):
    """Антиалиасный фон главного окна без Win32 region-mask."""
    def __init__(self, parent: Optional[QWidget] = None, radius: int = 24):
        super().__init__(parent)
        self._radius = int(radius)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("")

    def paintEvent(self, event):  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        grad = QLinearGradient(QPointF(0, 0), QPointF(max(1, self.width()), max(1, self.height())))
        grad.setColorAt(0.0, QColor("#161735"))
        grad.setColorAt(0.55, QColor("#121431"))
        grad.setColorAt(1.0, QColor("#0d0f28"))
        p.fillPath(path, QBrush(grad))
        p.setPen(QPen(QColor(255, 255, 255, 31), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


class _RoundedSidebar(DragHandle):
    """Сайдбар с закруглением только внешних левых углов."""
    def __init__(self, parent: Optional[QWidget] = None, radius: int = 24):
        super().__init__(parent)
        self._radius = int(radius)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("")

    def paintEvent(self, event):  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        rad = min(float(self._radius), r.width() / 2.0, r.height() / 2.0)
        path = QPainterPath()
        path.moveTo(r.left() + rad, r.top())
        path.lineTo(r.right(), r.top())
        path.lineTo(r.right(), r.bottom())
        path.lineTo(r.left() + rad, r.bottom())
        path.quadTo(r.left(), r.bottom(), r.left(), r.bottom() - rad)
        path.lineTo(r.left(), r.top() + rad)
        path.quadTo(r.left(), r.top(), r.left() + rad, r.top())
        path.closeSubpath()
        p.fillPath(path, QColor(18, 19, 46, 255))
        p.end()


class _LifecycleSpinner(QWidget):
    """Лёгкая canvas-анимация для экранов запуска и закрытия."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._angle = 0.0
        self._theme_name = current_theme_name()
        self.setFixedSize(76, 76)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def setTheme(self, theme_name: Optional[str] = None):
        self._theme_name = theme_name if theme_name in THEMES else current_theme_name()
        self.update()

    def start(self):
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        self._angle = (self._angle + 0.038) % (math.pi * 2.0)
        self.update()

    def paintEvent(self, event):  # type: ignore[override]
        theme = THEMES.get(self._theme_name, THEMES['violet'])
        secondary = _parse_color(theme.get('secondary', '#8bd5ff'))
        accent = _parse_color(theme.get('accent_light', '#cdbdff'))
        text = _parse_color(theme.get('text', '#e1e0ff'))
        ring_alpha = 42 if self._theme_name != 'light' else 64

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        ring_rect = QRectF(9, 9, self.width() - 18, self.height() - 18)

        muted_ring = QColor(text)
        muted_ring.setAlpha(ring_alpha)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(muted_ring, 1.2))
        painter.drawEllipse(ring_rect)

        arc_color = QColor(secondary)
        arc_color.setAlpha(220)
        painter.setPen(QPen(arc_color, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(ring_rect, int((-self._angle * 180.0 / math.pi) * 16), 96 * 16)

        accent_dot = QColor(accent)
        accent_dot.setAlpha(180)
        dot_angle = self._angle - math.radians(96)
        dot_radius = ring_rect.width() / 2.0
        dot_center = QPointF(
            center.x() + math.cos(dot_angle) * dot_radius,
            center.y() + math.sin(dot_angle) * dot_radius,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent_dot))
        painter.drawEllipse(dot_center, 2.6, 2.6)

        mark_color = QColor(text)
        mark_color.setAlpha(205)
        painter.setPen(QPen(mark_color, 1.15))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        mark = QPainterPath()
        mark.moveTo(center.x(), center.y() - 10)
        mark.lineTo(center.x() + 3, center.y() - 3)
        mark.lineTo(center.x() + 10, center.y())
        mark.lineTo(center.x() + 3, center.y() + 3)
        mark.lineTo(center.x(), center.y() + 10)
        mark.lineTo(center.x() - 3, center.y() + 3)
        mark.lineTo(center.x() - 10, center.y())
        mark.lineTo(center.x() - 3, center.y() - 3)
        mark.closeSubpath()
        painter.drawPath(mark)
        painter.end()


class _LifecycleOverlay(QWidget):
    """Полнооконный экран инициализации/закрытия поверх WebEngine и legacy-слоя."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._mode = "startup"
        self._base_status = ""
        self._dots = 0
        self._theme_name = current_theme_name()
        self._fade_anim: Optional[QPropertyAnimation] = None
        self.setObjectName("lifecycleOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 42, 42, 42)
        layout.setSpacing(8)
        layout.addStretch(1)

        self.spinner = _LifecycleSpinner(self)
        layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignHCenter)

        self.title_lbl = QLabel("ПРОЕКТ 1")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setStyleSheet("color: #ffffff; font-size: 18pt; font-weight: 700; letter-spacing: 1.4px; background: transparent;")
        apply_label_typography(self.title_lbl, 18, QFont.Weight.Bold, 1.4)
        layout.addWidget(self.title_lbl)

        self.state_lbl = QLabel("")
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_lbl.setStyleSheet("color: rgba(139,213,255,0.82); font-size: 8.5pt; font-weight: 700; letter-spacing: 2.2px; background: transparent;")
        apply_label_typography(self.state_lbl, 8.5, QFont.Weight.Bold, 2.2)
        layout.addWidget(self.state_lbl)

        self.status_lbl = QLabel("")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setMinimumHeight(24)
        self.status_lbl.setStyleSheet("color: rgba(225,224,255,0.72); font-size: 10pt; font-weight: 500; background: transparent;")
        apply_label_typography(self.status_lbl, 10, QFont.Weight.Medium, 0.0)
        layout.addWidget(self.status_lbl)

        progress = QFrame(self)
        self.progress = progress
        progress.setFixedSize(220, 4)
        self.setTheme(self._theme_name)
        layout.addSpacing(8)
        layout.addWidget(progress, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(360)
        self._dots_timer.timeout.connect(self._tick_dots)

    def current_mode(self) -> str:
        return self._mode

    def setTheme(self, theme_name: Optional[str] = None):
        self._theme_name = theme_name if theme_name in THEMES else current_theme_name()
        theme = THEMES.get(self._theme_name, THEMES['violet'])
        text = theme.get('text', '#e1e0ff')
        secondary = theme.get('secondary', '#8bd5ff')
        accent_light = theme.get('accent_light', '#cdbdff')
        text_dim_rgb = theme.get('text_dim_rgb', '202,195,216')
        self.spinner.setTheme(self._theme_name)
        self.title_lbl.setStyleSheet(f"color: {text}; font-size: 18pt; font-weight: 700; letter-spacing: 1.4px; background: transparent;")
        self.state_lbl.setStyleSheet(f"color: {secondary}; font-size: 8.5pt; font-weight: 700; letter-spacing: 2.2px; background: transparent;")
        self.status_lbl.setStyleSheet(f"color: rgba({text_dim_rgb},185); font-size: 10pt; font-weight: 500; background: transparent;")
        self.progress.setStyleSheet(
            "QFrame {"
            f" background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba({text_dim_rgb},28), stop:0.5 {accent_light}, stop:1 rgba({text_dim_rgb},28));"
            " border: none; border-radius: 2px;"
            "}"
        )
        self.update()

    def show_startup(self, theme_name: Optional[str] = None):
        self.setTheme(theme_name or current_theme_name())
        self._set_mode("startup", "ИНИЦИАЛИЗАЦИЯ", "поднимаю интерфейс")

    def show_shutdown(self, theme_name: Optional[str] = None):
        self.setTheme(theme_name or current_theme_name())
        self._set_mode("shutdown", "ЗАКРЫТИЕ", "сохраняю состояние")

    def _set_mode(self, mode: str, title: str, status: str):
        self._mode = mode
        self._base_status = status
        self._dots = 0
        self.setGraphicsEffect(None)
        self.state_lbl.setText(title)
        self.status_lbl.setText(status)
        self.show()
        self.raise_()
        self.spinner.start()
        if not self._dots_timer.isActive():
            self._dots_timer.start()
        self.update()

    def _tick_dots(self):
        self._dots = (self._dots + 1) % 4
        self.status_lbl.setText(self._base_status + ("." * self._dots))

    def fade_out(self, duration_ms: int = 360):
        if not self.isVisible():
            return
        self._dots_timer.stop()
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(1.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(max(80, int(duration_ms)))
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim = anim
        def _finish():
            self.spinner.stop()
            self.hide()
            self.setGraphicsEffect(None)
        anim.finished.connect(_finish)
        anim.start()

    def paintEvent(self, event):  # type: ignore[override]
        theme_name = self._theme_name if self._theme_name in THEMES else 'violet'
        theme = THEMES[theme_name]

        # Base fill: card_bg of the active theme (fully opaque).
        cbg_r, cbg_g, cbg_b = (int(p.strip()) for p in theme.get('card_bg_rgb', '14,16,40').split(',')[:3])
        bg_base = QColor(cbg_r, cbg_g, cbg_b)

        # Glow 1: accent at 10% opacity — radial-gradient(72% 88% at 96% 8%, rgba(accent,0.10) 0%, transparent 58%)
        acc_r, acc_g, acc_b = (int(p.strip()) for p in theme.get('accent_rgb', '124,77,255').split(',')[:3])
        glow1 = QColor(acc_r, acc_g, acc_b, int(255 * 0.10))

        # Glow 2: secondary at 7% opacity — radial-gradient(48% 62% at 2% 98%, rgba(secondary,0.07) 0%, transparent 55%)
        sec_hex = theme.get('secondary', '#8bd5ff').lstrip('#')
        sec_r, sec_g, sec_b = int(sec_hex[0:2], 16), int(sec_hex[2:4], 16), int(sec_hex[4:6], 16)
        glow2 = QColor(sec_r, sec_g, sec_b, int(255 * 0.07))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        w, h = self.width(), self.height()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 24, 24)

        # 1. Base dark fill.
        painter.fillPath(path, QBrush(bg_base))

        # 2. Elliptical radial glow #1: accent, top-right.
        #    CSS: radial-gradient(72% 88% at 96% 8%, rgba(acc,0.10) 0%, transparent 58%)
        #    ObjectMode maps (0,0)-(1,1) to the filled rect, so a (0.5,0.5,0.5) circle
        #    becomes an ellipse filling the rect exactly — matches CSS % semantics.
        rg1 = QRadialGradient(0.5, 0.5, 0.5)
        rg1.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        rg1.setColorAt(0.0,  glow1)
        rg1.setColorAt(0.58, QColor(acc_r, acc_g, acc_b, 0))
        rg1.setColorAt(1.0,  QColor(acc_r, acc_g, acc_b, 0))
        cx1, cy1 = w * 0.96, h * 0.08
        rx1, ry1 = w * 0.72, h * 0.88
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(cx1 - rx1, cy1 - ry1, rx1 * 2, ry1 * 2), QBrush(rg1))
        painter.restore()

        # 3. Elliptical radial glow #2: secondary, bottom-left.
        #    CSS: radial-gradient(48% 62% at 2% 98%, rgba(sec,0.07) 0%, transparent 55%)
        rg2 = QRadialGradient(0.5, 0.5, 0.5)
        rg2.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        rg2.setColorAt(0.0,  glow2)
        rg2.setColorAt(0.55, QColor(sec_r, sec_g, sec_b, 0))
        rg2.setColorAt(1.0,  QColor(sec_r, sec_g, sec_b, 0))
        cx2, cy2 = w * 0.02, h * 0.98
        rx2, ry2 = w * 0.48, h * 0.62
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(cx2 - rx2, cy2 - ry2, rx2 * 2, ry2 * 2), QBrush(rg2))
        painter.restore()

        # 4. Grain texture: matches card ::after (opacity 0.18, mix-blend-mode soft-light).
        noise_tile = _LifecycleOverlay._noise_tile()
        painter.save()
        painter.setClipPath(path)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SoftLight)
        painter.setOpacity(0.18)
        tw, th_t = noise_tile.width(), noise_tile.height()
        for ty in range(0, h + th_t, th_t):
            for tx in range(0, w + tw, tw):
                painter.drawImage(tx, ty, noise_tile)
        painter.restore()

        # 5. Border: 1px solid rgba(border_rgb, border_alpha).
        bp = [int(p.strip()) for p in str(theme.get('border_rgb', '255,255,255')).split(',')[:3]]
        painter.setPen(QPen(QColor(bp[0], bp[1], bp[2], int(theme.get('border_alpha', 18))), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()

    @staticmethod
    def _noise_tile() -> 'QImage':
        """Lazily generate and cache a 160×160 greyscale noise tile.
        Values are limited to [80, 176] (centred at 128, same as neutral
        soft-light) to approximate the feTurbulence fractalNoise output
        and avoid harsh full-contrast white noise."""
        tile = getattr(_LifecycleOverlay, '_cached_noise_tile', None)
        if tile is not None:
            return tile
        import os as _os
        size = 160
        raw = _os.urandom(size * size)
        # Map 0-255 → 80-176 (range 96, centred at 128)
        data = bytes(80 + (b % 96) for b in raw)
        img = QImage(data, size, size, size, QImage.Format.Format_Grayscale8).copy()
        _LifecycleOverlay._cached_noise_tile = img
        return img


class TopBar(QFrame):
    """Тонкая шапка с тремя цветными кружками и центрированным заголовком."""
    def __init__(self, title: str, parent: Optional[QWidget] = None,
                 on_close=None, on_minimize=None, on_maximize=None):
        super().__init__(parent)
        self._drag_pos = None
        self.setFixedHeight(36)
        self.setStyleSheet(
            "QFrame {"
            " background: rgba(15,17,43,140);"
            " border-bottom: 1px solid rgba(255,255,255,18);"
            " border-top-left-radius: 20px;"
            " border-top-right-radius: 20px; }"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(6)
        dot_actions = [on_close, on_minimize, on_maximize]
        for color, action in zip(("#ffb4ab", "#00bdfd", "#cdbdff"), dot_actions):
            dot = QPushButton("")
            dot.setFixedSize(10, 10)
            dot.setFlat(True)
            dot.setStyleSheet(
                f"QPushButton {{"
                f" background-color: rgba({_hex_rgb(color)},120);"
                f" border: 1px solid rgba({_hex_rgb(color)},80);"
                " border-radius: 5px; }"
                f"QPushButton:hover {{"
                f" background-color: rgba({_hex_rgb(color)},220);"
                " }"
            )
            if action is not None:
                dot.setCursor(Qt.CursorShape.PointingHandCursor)
                dot.clicked.connect(action)
            h.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addStretch(1)
        self.title = QLabel(title)
        self.title.setStyleSheet(
            "color: #cdbdff; font-size: 11pt; font-weight: 700;"
            " letter-spacing: -0.5px; background: transparent; border: none;"
        )
        h.addWidget(self.title, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addStretch(1)
        # пустышка для симметрии (под три кружка)
        spacer = QLabel("")
        spacer.setFixedWidth(40)
        h.addWidget(spacer)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, QPushButton):
                self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


# ─────────────────── Окно логов ───────────────────
class LogWindow(QDialog, FramelessWindowMixin):
    """Отображает перехваченные print()-логи в реальном времени."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(700, 440)
        self.resize(820, 500)
        self.setWindowTitle("Логи")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("dialogCard")
        card.setStyleSheet(
            "QFrame#dialogCard {"
            " background-color: #08091a;"
            " border: 1px solid rgba(124,77,255,90);"
            " border-radius: 18px;"
            "}"
        )
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # ── Заголовок ──
        hdr = QHBoxLayout()
        title_lbl = QLabel("Логи приложения")
        title_lbl.setStyleSheet("font-size: 12pt; font-weight: 700; color: #cdbdff; padding: 0;")
        hdr.addWidget(title_lbl)
        hdr.addStretch()

        _btn_style = (
            "QPushButton { font-size: 9pt; font-weight: 600; color: #b0aad4;"
            " background: rgba(28,29,56,200); border: 1px solid rgba(255,255,255,22);"
            " border-radius: 8px; padding: 0 12px; height: 28px; }"
            " QPushButton:hover { border-color: #7c4dff; color: #e1e0ff; }"
            " QPushButton:pressed { background: rgba(124,77,255,80); }"
        )

        btn_copy = QPushButton("Копировать")
        btn_copy.setStyleSheet(_btn_style)
        btn_copy.clicked.connect(self._copy_all)

        btn_clear = QPushButton("Очистить")
        btn_clear.setStyleSheet(_btn_style)
        btn_clear.clicked.connect(self._clear)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setStyleSheet(
            "QPushButton { font-size: 10pt; color: #cdbdff;"
            " background: rgba(28,29,56,200); border: 1px solid rgba(255,255,255,22);"
            " border-radius: 8px; padding: 0; }"
            " QPushButton:hover { background: rgba(200,50,50,180); color: #fff;"
            " border-color: rgba(200,50,50,220); }"
        )
        btn_close.clicked.connect(self.hide)

        hdr.addWidget(btn_copy)
        hdr.addSpacing(6)
        hdr.addWidget(btn_clear)
        hdr.addSpacing(6)
        hdr.addWidget(btn_close)
        layout.addLayout(hdr)

        # ── Текстовая область ──
        self.text_area = QPlainTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setMaximumBlockCount(2000)
        self.text_area.setStyleSheet(
            "QPlainTextEdit {"
            " background-color: #04050f;"
            " color: #a8ffb8;"
            " font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;"
            " font-size: 9pt;"
            " border: 1px solid rgba(255,255,255,14);"
            " border-radius: 10px;"
            " padding: 8px;"
            " selection-background-color: rgba(124,77,255,120);"
            "}"
            "QScrollBar:vertical { background: rgba(28,29,56,180); width: 8px; border-radius: 4px; border: none; }"
            "QScrollBar::handle:vertical { background: rgba(124,77,255,140); border-radius: 4px; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
            "QScrollBar:horizontal { height: 0px; }"
        )
        layout.addWidget(self.text_area)

        self.enable_frameless_drag()
        self.apply_drop_shadow(blur=40, y_offset=10, alpha=90)

        # ── Загрузить накопленные строки ──
        with _log_lock:
            existing = list(_log_lines)
        if existing:
            self.text_area.setPlainText("\n".join(existing))
            self._scroll_to_bottom()

        # ── Подключиться к сигналу новых строк ──
        _log_emitter.new_line.connect(self._on_new_line)

    def _on_new_line(self, line: str):
        self.text_area.appendPlainText(line)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        sb = self.text_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy_all(self):
        QApplication.clipboard().setText(self.text_area.toPlainText())

    def _clear(self):
        global _log_unread
        with _log_lock:
            _log_lines.clear()
            _log_unread = 0
        self.text_area.clear()
        if self.parent():
            try:
                self.parent()._update_log_btn()
            except Exception:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        global _log_unread
        with _log_lock:
            _log_unread = 0
        if self.parent():
            try:
                self.parent()._update_log_btn()
            except Exception:
                pass
# ──────────────────────────────────────────────────


class _WebUiBridge(QObject):
    def __init__(self, owner: 'MainWindow'):
        super().__init__(owner)
        self._owner = owner

    @Slot(int)
    def setSwitchState(self, state: int):
        try:
            self._owner._on_web_switch_state(int(state))
        except Exception:
            pass

    @Slot(str)
    def navClicked(self, key: str):
        try:
            self._owner._on_web_nav_clicked(str(key or ""))
        except Exception:
            pass

    @Slot(str)
    def windowAction(self, action: str):
        try:
            self._owner._on_web_window_action(str(action or ""))
        except Exception:
            pass

    @Slot(str)
    def settingsAction(self, action: str):
        try:
            self._owner._on_web_settings_action(str(action or ""))
        except Exception:
            pass

    @Slot(str)
    def applySettings(self, payload_json: str):
        try:
            self._owner._apply_web_settings_json(str(payload_json or "{}"))
        except Exception:
            pass

    @Slot(str)
    def curvesAction(self, action: str):
        try:
            self._owner._on_web_curves_action(str(action or ""))
        except Exception:
            pass

    @Slot(str)
    def applyCurves(self, payload_json: str):
        try:
            self._owner._apply_web_curves_json(str(payload_json or "{}"))
        except Exception:
            pass

    @Slot()
    def notifyWebUiReady(self):
        """Called from JS (bridge.notifyWebUiReady()) at the end of bindBridge —
        i.e. after QWebChannel connected and all event handlers are set up.
        By this time Chromium has had enough cycles to composite the first frame,
        so web_view.show() reveals a fully-rendered interface (no violet flash)."""
        try:
            self._owner._finish_startup_overlay()
        except Exception:
            pass


class _WebEngineChromeView(QWebEngineView):
    """QWebEngineView с drag-зонами для frameless-окна."""
    def __init__(self, owner: 'MainWindow', parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._owner = owner
        self._drag_active = False
        self._drag_origin_global = QPoint()
        self._drag_window_origin = QPoint()

    def _is_drag_zone(self, pos) -> bool:
        x = float(pos.x())
        y = float(pos.y())
        w = float(max(1, self.width()))
        if x >= w - 76 and 12 <= y <= 62:
            return False
        if x >= 244 and 12 <= y <= 66:
            return True
        if x < 244 and y <= 88:
            return True
        return False

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._is_drag_zone(event.position()):
            self._drag_active = True
            self._drag_origin_global = event.globalPosition().toPoint()
            try:
                self._drag_window_origin = self._owner.frameGeometry().topLeft()
            except Exception:
                self._drag_window_origin = self._owner.pos()
            event.accept()
            return
        self._drag_active = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if self._drag_active and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_origin_global
            self._owner.move(self._drag_window_origin + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        if self._drag_active:
            self._drag_active = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _design_preview_html_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(os.path.join(meipass, "appDESIGN", "design-preview.html"))
    candidates.extend([
        os.path.join(here, "..", "appDESIGN", "design-preview.html"),
        os.path.join(here, "appDESIGN", "design-preview.html"),
    ])
    for path in candidates:
        path = os.path.abspath(path)
        if os.path.exists(path):
            return path
    return os.path.abspath(candidates[-1])


class MainWindow(QMainWindow, FramelessWindowMixin):
    def __init__(self):
        super().__init__()
        self.setObjectName("mainWindow")
        try:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        except Exception:
            pass
        if ENABLE_GLASS_BACKDROP:
            try:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
                self.setAutoFillBackground(False)
            except Exception:
                pass
        try:
            self.enable_frameless_drag()
        except Exception:
            pass
        try:
            apply_app_theme(QApplication.instance())
        except Exception:
            pass
        self.setStyleSheet("QMainWindow#mainWindow { background: transparent; border: none; }")
        self.purge_active = False
        self._prev_loop_status_code = None  # track LOOP: status code (legacy, kept for reconnect reset)
        self.current_mode = 0
        self.current_r = 255
        self.current_g = 0
        self.current_b = 0
        self.current_custom_colors = None
        self._last_led_payload: Optional[bytes] = None
        self._last_led_sent_payload: Optional[bytes] = None
        self._last_led_sent_ts: float = 0.0
        self._led_pending_payload: Optional[bytes] = None
        self._led_min_interval_sec: float = 0.25
        self._led_same_suppress_sec: float = 2.0
        self._led_debounce_timer = QTimer(self)
        self._led_debounce_timer.setSingleShot(True)
        self._led_debounce_timer.timeout.connect(self._flush_pending_led_payload)
        self._last_valid_temps: Optional[tuple[str, str]] = None
        self._last_valid_temp_ts: float = 0.0
        self._temp_hold_seconds: float = 10.0
        self.setWindowTitle("PROEKT1 — Мониторинг температур")
        self.setWindowIcon(QIcon())
        self.setMinimumSize(960, 660)
        self.resize(1100, 760)
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon())
        self.tray_icon.setToolTip("PROEKT1")
        # Tray menu with Show and Exit
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Показать окно")
        exit_action = tray_menu.addAction("Выход")
        show_action.triggered.connect(self.restore_from_tray)
        exit_action.triggered.connect(QApplication.quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()
        self._lhm_proc = start_lhm()
        # Console reporter: concise CPU/GPU output every 5 seconds
        try:
            self._console_reporter = ConsoleReporter(get_current_temps)
            self._console_reporter.start()
        except Exception:
            self._console_reporter = None
        # Timer to auto-return switch to STOP after manual PURGE (non-test)
        self._auto_return_timer = QTimer(self)
        self._auto_return_timer.setSingleShot(True)
        self._auto_return_timer.timeout.connect(self._on_auto_return_timer)
        # Автозапуск после подключения гидролиний (обратный отсчёт)
        self._autostart_countdown_active = False
        self._autostart_secs = 0
        self._autostart_timer = QTimer(self)
        self._autostart_timer.setSingleShot(False)
        self._autostart_timer.setInterval(1000)
        self._autostart_timer.timeout.connect(self._on_autostart_tick)
        central = _RoundedWindowFrame()
        central.setObjectName("glassRoot")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        legacy_visual_layer = QWidget(central)
        legacy_visual_layer.setObjectName("legacyVisualLayer")
        legacy_visual_layer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        legacy_visual_layer.setStyleSheet("background: transparent;")
        central_layout.addWidget(legacy_visual_layer)
        root_h = QHBoxLayout(legacy_visual_layer)
        root_h.setContentsMargins(0, 0, 0, 0)
        root_h.setSpacing(0)

        # ─────────────── Боковая панель ───────────────
        sidebar = _RoundedSidebar()
        sidebar.setObjectName("sidebar")
        self.sidebar = sidebar
        sidebar.setFixedWidth(244)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(20, 30, 16, 22)
        sb_layout.setSpacing(0)

        # Логотип-блок: иконка + название
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(0, 0, 0, 0)
        logo_row.setSpacing(10)
        logo_dot = QLabel()
        logo_dot.setFixedSize(34, 34)
        logo_dot.setPixmap(_icon_pixmap("sparkle", size=22, color="#cdbdff"))
        logo_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_dot.setStyleSheet(
            "background: rgba(124,77,255,55); border-radius: 10px;"
            " border: 1px solid rgba(124,77,255,90);"
        )
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        title_lbl = QLabel("ПРОЕКТ 1")
        self.title_lbl = title_lbl
        title_lbl.setStyleSheet(
            "color: #ffffff; font-size: 13pt; font-weight: 700;"
            " letter-spacing: 0.5px; background: transparent;"
        )
        apply_label_typography(title_lbl, 13, QFont.Weight.Bold, 0.5)
        status_lbl = QLabel("v2.4 · STABLE")
        self.status_lbl = status_lbl
        status_lbl.setStyleSheet(
            "color: rgba(139,213,255,200); font-size: 8pt; font-weight: 600;"
            " letter-spacing: 1.5px; background: transparent;"
        )
        apply_label_typography(status_lbl, 8, QFont.Weight.DemiBold, 1.5)
        title_box.addWidget(title_lbl)
        title_box.addWidget(status_lbl)
        logo_row.addWidget(logo_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        logo_row.addLayout(title_box, 1)
        logo_wrap = QWidget()
        logo_wrap.setLayout(logo_row)
        logo_wrap.setStyleSheet("background: transparent;")
        sb_layout.addWidget(logo_wrap)
        sb_layout.addSpacing(34)

        # Навигационные пункты (пока активна только «Панель управления»)
        self.sidebar_buttons: dict[str, SidebarNavButton] = {}
        nav_items = [
            ("dashboard", "dashboard",         "Панель управления"),
            ("pump",      "drop",              "Настройки оборотов"),
            ("led",       "led_sun",           "Подсветка"),
            ("settings",  "settings_sliders",  "Настройки"),
        ]
        nav_group = QButtonGroup(self)
        nav_group.setExclusive(True)
        for key, icon, label in nav_items:
            btn = SidebarNavButton(icon, label)
            self.sidebar_buttons[key] = btn
            nav_group.addButton(btn)
            sb_layout.addWidget(btn)
            sb_layout.addSpacing(4)
        self.sidebar_buttons["dashboard"].setChecked(True)
        # Заглушки прочих экранов: открываем существующие диалоги; экраны-страницы добавим позже
        self.sidebar_buttons["pump"].clicked.connect(self.show_curve_dialog)
        self.sidebar_buttons["led"].clicked.connect(lambda: self._sidebar_placeholder("Подсветка"))
        self.sidebar_buttons["settings"].clicked.connect(self.show_settings_dialog)
        # После клика возвращаем подсветку «Панели управления»
        for key in ("pump", "led", "settings"):
            self.sidebar_buttons[key].clicked.connect(
                lambda _checked=False: self.sidebar_buttons["dashboard"].setChecked(True)
            )

        sb_layout.addStretch(1)

        # Системная продувка + ссылка «Логи» — в макете отсутствуют, поэтому скрыты;
        # функционал сохранён: продувка доступна через TriStateSwitch (сегмент «ПРОДУВКА»),
        # логи — через хоткей Ctrl+L (см. ниже)
        self.btn_purge_system = QPushButton("ПРОДУВКА СИСТЕМЫ")
        self.btn_purge_system.setVisible(False)
        self.btn_purge_system.clicked.connect(self._on_sidebar_purge_clicked)

        self.btn_log = QPushButton("ЛОГИ")
        self.btn_log.setVisible(False)
        self.btn_log.clicked.connect(self._open_log_window)

        # Глобальный хоткей Ctrl+L → открыть окно логов
        try:
            from PySide6.QtGui import QShortcut, QKeySequence
            self._log_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
            self._log_shortcut.activated.connect(self._open_log_window)
        except Exception:
            pass

        root_h.addWidget(sidebar)
        _sidebar_sep = QFrame()
        _sidebar_sep.setObjectName("sidebarSep")
        _sidebar_sep.setFixedWidth(1)
        _sidebar_sep.setStyleSheet("QFrame#sidebarSep { background: rgba(255,255,255,14); border: none; }")
        root_h.addWidget(_sidebar_sep)

        # ─────────────── Контентная область ───────────────
        main_area = QWidget()
        main_area.setObjectName("mainArea")
        main_area.setStyleSheet("QWidget#mainArea { background: transparent; }")
        ma_layout = QVBoxLayout(main_area)
        ma_layout.setContentsMargins(24, 18, 24, 24)
        ma_layout.setSpacing(20)

        # Заголовок: название экрана слева, кнопки управления окном справа
        header = DragHandle()
        header.setFixedHeight(44)
        h_h = QHBoxLayout(header)
        h_h.setContentsMargins(0, 0, 0, 0)
        h_h.setSpacing(8)
        page_title = QLabel("ПАНЕЛЬ УПРАВЛЕНИЯ")
        self.page_title = page_title
        page_title.setStyleSheet(
            "color: #ffffff; font-size: 13pt; font-weight: 700;"
            " letter-spacing: 1px; background: transparent;"
        )
        apply_label_typography(page_title, 13, QFont.Weight.Bold, 1.0)
        page_subtitle = QLabel("· онлайн")
        self.page_subtitle = page_subtitle
        page_subtitle.setStyleSheet(
            "color: rgba(139,213,255,200); font-size: 9pt; font-weight: 600;"
            " letter-spacing: 1px; background: transparent;"
        )
        apply_label_typography(page_subtitle, 9, QFont.Weight.DemiBold, 1.0)
        h_h.addWidget(page_title, 0, Qt.AlignmentFlag.AlignVCenter)
        h_h.addWidget(page_subtitle, 0, Qt.AlignmentFlag.AlignVCenter)
        h_h.addStretch(1)
        self.btn_win_min = WindowControlButton("minus", "rgba(124,77,255,90)")
        self.btn_win_min.clicked.connect(self.showMinimized)
        self.btn_win_close = WindowControlButton("close", "rgba(255,180,171,110)")
        self.btn_win_close.clicked.connect(self.close)
        h_h.addWidget(self.btn_win_min)
        h_h.addWidget(self.btn_win_close)
        ma_layout.addWidget(header)

        # Stacked area для будущих экранов — пока только дашборд
        self.stack = QStackedWidget()
        ma_layout.addWidget(self.stack, 1)

        dashboard = QFrame()
        dashboard.setObjectName("dashboardCard")
        dashboard.setStyleSheet(
            "QFrame#dashboardCard {"
            " background: rgba(28,29,56,170);"
            " border: 1px solid rgba(255,255,255,18);"
            " border-radius: 24px; }"
        )
        # Без drop shadow на dashboard: по макету только окно даёт тень,
        # внутренние карточки тени не имеют (паразитные тёмные углы).
        d_outer = QVBoxLayout(dashboard)
        d_outer.setContentsMargins(34, 30, 34, 26)
        d_outer.setSpacing(22)

        # Один столбец: метрики/вентиляторы/состояние, тонкий разделитель, tri-switch снизу
        # ───── Контент дашборда ─────
        left_col = QVBoxLayout()
        left_col.setSpacing(22)

        # Температуры
        left_col.addWidget(self._section_caption("thermo_fill", "ТЕМПЕРАТУРЫ"))
        temp_row = QHBoxLayout()
        temp_row.setSpacing(12)
        self.cpu_card = MetricCard("CPU", accent="#8bd5ff")
        self.gpu_card = MetricCard("GPU", accent="#cdbdff")
        self.water_card = MetricCard("Вода", accent="#8bd5ff")
        self.cpu_label = self.cpu_card
        self.gpu_label = self.gpu_card
        self.water_label = self.water_card
        temp_row.addWidget(self.cpu_card)
        temp_row.addWidget(self.gpu_card)
        temp_row.addWidget(self.water_card)
        left_col.addLayout(temp_row)

        # Вентиляторы
        left_col.addSpacing(2)
        left_col.addWidget(self._section_caption("fan_blade", "ОБОРОТЫ ВЕНТИЛЯТОРОВ"))
        rpm_row = QHBoxLayout()
        rpm_row.setSpacing(12)
        self.fan1_card = FanCard("Вентилятор 1")
        self.fan2_card = FanCard("Вентилятор 2", blobs=_BLOBS_FAN2)
        self.fan1_val = self.fan1_card
        self.fan2_val = self.fan2_card
        rpm_row.addWidget(self.fan1_card)
        rpm_row.addWidget(self.fan2_card)
        left_col.addLayout(rpm_row)

        # Статус
        left_col.addSpacing(2)
        left_col.addWidget(self._section_caption("info_fill", "СОСТОЯНИЕ"))
        self.info_card = InfoCard()
        self.info_label = self.info_card
        left_col.addWidget(self.info_card)
        # loop_label-прокси (совместимость со старым кодом)
        class _LoopProxy:
            def __init__(self, owner):
                self._owner = owner
            def setText(self, t):
                low = (t or "").lower()
                ok = ("норма" in low) or ("подключ" in low) or ("восстанов" in low)
                if ("разрыв" in low) or ("выключ" in low) or ("--" in low):
                    ok = False
                self._owner.info_card.setLoop(t, ok)
        self.loop_label = _LoopProxy(self)
        left_col.addStretch(1)

        left_wrap = QWidget()
        left_wrap.setLayout(left_col)
        d_outer.addWidget(left_wrap, 1)

        # Тонкий разделитель перед нижней секцией «РЕЖИМ РАБОТЫ»
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(255,255,255,18); border: none;")
        d_outer.addWidget(sep)

        # ───── Нижняя секция: «⚡ РЕЖИМ РАБОТЫ» + tri-switch во всю ширину ─────
        bottom_col = QVBoxLayout()
        bottom_col.setSpacing(14)
        bottom_col.setContentsMargins(0, 4, 0, 0)
        bottom_col.addWidget(self._section_caption("bolt", "РЕЖИМ РАБОТЫ"))
        self.tri_switch = TriStateSwitch()
        self.tri_switch.stateChanged.connect(self.on_switch_state_changed)
        self.tri_switch.setState(1, animated=False, external=True)
        self.tri_switch.setMetrics(height_px=48, text_pt=11)
        bottom_col.addWidget(self.tri_switch)
        d_outer.addLayout(bottom_col)

        # Скрытые управляющие виджеты (функционал сохранён, доступ — через сайдбар «Настройки»/«Настройки оборотов»)
        self.btn_settings = QPushButton()
        self.btn_settings.setVisible(False)
        self.btn_settings.clicked.connect(self.show_settings_dialog)

        self.transport_combo = QComboBox()
        self.transport_combo.addItems(["BLE", "USB"])
        self.transport_combo.setCurrentText("BLE")
        self.transport_combo.setVisible(False)
        self.transport_combo.currentTextChanged.connect(self.on_transport_mode_changed)

        self.btn_curve = QPushButton("НАСТРОИТЬ ОБОРОТЫ")
        self.btn_curve.setVisible(False)
        self.btn_curve.clicked.connect(self.show_curve_dialog)

        self.stack.addWidget(dashboard)
        self.stack.setCurrentWidget(dashboard)

        root_h.addWidget(main_area, 1)
        self._legacy_visual_layer = legacy_visual_layer
        self._legacy_visual_layer.hide()

        # Совместимость: top_bar более не используется; чтобы внешний код не падал
        self.top_bar = None

        # Начальное состояние системы
        self.system_running = True  # assume normal operation initially
        self.setCentralWidget(central)
        self._closing_in_progress = False
        self._allow_close = False
        self._startup_overlay_started_at = time.monotonic()
        self._lifecycle_overlay = _LifecycleOverlay(central)
        self._lifecycle_overlay.setGeometry(central.rect())
        self._lifecycle_overlay.show_startup(current_theme_name())
        self._lifecycle_overlay.raise_()
        self._web_ready = False
        self._web_last_info = {
            "targets": "--",
            "profile": "--",
            "link": "Связь: --",
            "linkActive": False,
            "loop": "Гидролинии: --",
            "loopOk": False,
        }
        try:
            self.tri_switch._web_sync_callback = self._sync_web_triswitch
            self._install_web_engine_ui(central)
        except Exception as exc:
            try:
                print(f"WEB UI init failed: {exc}")
            except Exception:
                pass
        try:
            # Safety net: if loadFinished never fires (e.g. Chromium process crash
            # or sandboxing issue), force-show the web view after 20 s so the
            # window is not stuck on the loading overlay indefinitely.
            def _web_show_fallback():
                try:
                    wv = getattr(self, 'web_view', None)
                    if wv is not None and not wv.isVisible():
                        wv.show()
                    ov = getattr(self, '_lifecycle_overlay', None)
                    if ov is not None and ov.isVisible() and ov.current_mode() == "startup":
                        ov.fade_out(400)
                except Exception:
                    pass
            QTimer.singleShot(20000, _web_show_fallback)
        except Exception:
            pass
        try:
            apply_windows_backdrop(self)
        except Exception:
            pass
        try:
            QTimer.singleShot(0, self._apply_rounded_mask)
            QTimer.singleShot(120, self._apply_rounded_mask)
        except Exception:
            pass
        # Окно логов (создаём один раз, показываем по кнопке)
        self._log_window = LogWindow(parent=self)
        _log_emitter.new_line.connect(self._on_log_new_line)
        # Пути к файлам конфигурации/кривым и начальная загрузка до старта транспорта,
        # чтобы избежать ранней переотправки дефолтного красного профиля
        self.curves_path = os.path.join(os.path.dirname(__file__), "curves.json")
        self.config_path = os.path.join(os.path.dirname(__file__), "config.json")
        self.autostart = False
        self.minimized = False
        self.keep_led_on_disconnected = False
        self.loop_protection_enabled = False
        self.purge_on_shutdown_enabled = False
        self.app_language = "RU"
        self.pump_hours = True
        self.led_custom_colors = [QColor(0, 0, 0) for _ in range(20)]
        self.led_config_loaded = False
        self.transport = "BLE"
        self.load_app_config()
        try:
            self._lifecycle_overlay.setTheme(getattr(self, 'theme', current_theme_name()))
        except Exception:
            pass
        self._sync_web_settings()
        self._transport_thread = None
        self.on_transport_mode_changed(self.transport)  # Запуск в соответствии с сохранённым режимом

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(1000)  # Обновление каждую секунду
        self.pump_hours_timer = QTimer()
        self.pump_hours_timer.timeout.connect(self.sync_pump_hours_to_esp)
        # Sync pump hours every 3 hours to reduce flash wear; still force-sync on app close
        self.pump_hours_timer.start(3 * 60 * 60 * 1000)  # 3 hours
        # Длительность продувки (для автозакрытия)
        self.PURGE_TOTAL_MS = 16000  # ~3s stop + 1s valve + 12s pump@60%
        # Load curves (curves_path уже задан выше)
        if self.minimized:
            self.showMinimized()
        self.link_status = "Связь: --"
        self.targets = "Цели: --"
        self.fan_points = [[40.0, 70.0], [55.0, 80.0], [70.0, 90.0], [90.0, 95.0], [110.0, 100.0]]
        self.pump_points = [[40.0, 50.0], [55.0, 60.0], [70.0, 70.0], [90.0, 75.0], [110.0, 80.0]]
        self.source_mode = 2
        self.hyst_fan = 5
        self.hyst_pump = 5
        self.presets = {"Стандарт": {"fan_curve": [p[:] for p in self.fan_points], "pump_curve": [p[:] for p in self.pump_points]}}
        # Pump hours
        self.pump_hours_base = {"version": 1, "total_minutes": 0, "total_running_ms": 0, "sum_percent_ms": 0}
        self.pump_hours_acc_run_ms = 0
        self.pump_hours_acc_sum_pct_ms = 0.0
        self.pump_hours_last_sync = time.time()
        # Fan alarm variables
        self.fan1_alarm_start = None
        self.fan1_alarm_state = 0
        self.fan1_last_switch = 0
        self.fan2_alarm_start = None
        self.fan2_alarm_state = 0
        self.fan2_last_switch = 0
        self.alarm_triggered = False
        # Minimum run/hold logic for fans/pumps (ensure at least N seconds run after start)
        # Delays (configurable in settings)
        self.delay_on_seconds = 0    # задержка включения (сек); 0 = выкл
        self.delay_off_seconds = 0   # задержка выключения (сек); 0 = выкл
        self.display_lang = "RU"     # язык дисплея ESP32: "RU" или "ENG"

        # Internal per-component state for on/off delays
        self._fan_on_timer_start: Optional[float] = None
        self._fan_pending_off_until: Optional[float] = None
        self._fan_last_on_temps: Optional[Tuple[int, int]] = None
        self._fan_running_state: bool = False

        self._pump_on_timer_start: Optional[float] = None
        self._pump_pending_off_until: Optional[float] = None
        self._pump_last_on_temps: Optional[Tuple[int, int]] = None
        self._pump_running_state: bool = False

        self._last_target_fan = 0.0
        self._last_target_pump = 0.0
        self._temp_hold_lock = threading.Lock()
        # Connection grace period
        self.connection_start_time = None
        try:
            with open(self.curves_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.fan_points = data.get("fan_curve", self.fan_points)
                self.pump_points = data.get("pump_curve", self.pump_points)
                self.source_mode = data.get("source_mode", self.source_mode)
                self.hyst_fan = max(3, min(10, int(data.get("hyst_fan", self.hyst_fan))))
                self.hyst_pump = max(3, min(10, int(data.get("hyst_pump", self.hyst_pump))))
                self.delay_on_seconds = int(data.get("delay_on_seconds", self.delay_on_seconds))
                self.delay_off_seconds = int(data.get("delay_off_seconds", self.delay_off_seconds))
                self.presets = data.get("presets", self.presets)
                selected_preset = data.get("selected_preset", "Стандарт")
                global _last_preset_name
                _last_preset_name = selected_preset
        except Exception:
            pass
        # Ensure window visible (in case previous geometry was off-screen)
        QTimer.singleShot(200, self.ensure_visible)
        # Подключить сигнал смены экрана (нужен показ окна, поэтому с задержкой)
        QTimer.singleShot(300, self._connect_screen_changed)

        # Установка перехватчика системных событий Windows (сон/завершение работы)
        try:
            self._shutdown_purge_initiated = False
            class _WinEventFilter(QAbstractNativeEventFilter):
                def __init__(self, cb):
                    super().__init__()
                    self._cb = cb
                def nativeEventFilter(self, eventType, message):  # type: ignore[override]
                    try:
                        # PySide6 may pass eventType as bytes (QByteArray) or str
                        et = None
                        try:
                            et = eventType.decode(errors='ignore') if isinstance(eventType, (bytes, bytearray)) else str(eventType)
                        except Exception:
                            et = str(eventType)
                        if 'windows' not in et.lower():
                            return False, 0
                        # message can be an int pointer or a sip.voidptr; normalize to int address
                        try:
                            addr = int(message)
                        except Exception:
                            try:
                                addr = int(message.__int__())  # type: ignore[attr-defined]
                            except Exception:
                                return False, 0
                        msg = wintypes.MSG.from_address(addr)
                        WM_QUERYENDSESSION = 0x0011
                        WM_ENDSESSION = 0x0016
                        if msg.message == WM_QUERYENDSESSION or msg.message == WM_ENDSESSION:
                            try:
                                print("SYS EVT: shutdown notice received")
                            except Exception:
                                pass
                            self._cb('shutdown', msg.wParam, msg.lParam)
                    except Exception:
                        pass
                    return False, 0
            def _sys_evt(kind, wParam, lParam):
                # Отправляем продувку строго по выбранным событиям, без дублирования
                try:
                    if kind == 'shutdown':
                        if getattr(self, 'purge_on_shutdown_enabled', False) and not getattr(self, '_shutdown_purge_initiated', False):
                            self._shutdown_purge_initiated = True
                            # Просим Windows подождать — блокируем завершение до окончания продувки
                            try:
                                hwnd = int(self.winId())
                                ctypes.windll.user32.ShutdownBlockReasonCreate(
                                    wintypes.HWND(hwnd),
                                    "PROEKT1: продувка контура охлаждения"
                                )
                            except Exception:
                                pass
                            try:
                                print("SYS EVT: initiating purge due to shutdown")
                            except Exception:
                                pass
                            self._direct_serial_purge()
                except Exception:
                    pass
            self._native_filter = _WinEventFilter(_sys_evt)
            QApplication.instance().installNativeEventFilter(self._native_filter)
        except Exception:
            pass

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        try:
            web_view = getattr(self, 'web_view', None)
            cw = self.centralWidget()
            if web_view is not None and cw is not None:
                web_view.setGeometry(cw.rect())
                self._reset_web_view_clip()
                self._apply_web_view_native_round_rgn()
                web_view.raise_()
            overlay = getattr(self, '_lifecycle_overlay', None)
            if overlay is not None and cw is not None:
                overlay.setGeometry(cw.rect())
                if overlay.isVisible():
                    overlay.raise_()
        except Exception:
            pass
        self._apply_rounded_mask()

    def _raise_overlay_hwnd_above_webview(self):
        """Win32-level Z-order fix: place the lifecycle overlay's HWND above the
        QWebEngineView's HWND so the overlay is visible even though Chromium uses
        a native child HWND that normally paints over non-native Qt widgets.

        SetWindowPos(web_hwnd, hWndInsertAfter=overlay_hwnd) places web_hwnd
        *after* (i.e., below) overlay_hwnd in Z-order, which is what we want.
        """
        try:
            overlay = getattr(self, '_lifecycle_overlay', None)
            web_view = getattr(self, 'web_view', None)
            if overlay is None or web_view is None:
                return
            overlay_hwnd = int(overlay.winId())
            web_hwnd = int(web_view.winId())
            if not overlay_hwnd or not web_hwnd:
                return
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            # Place web_hwnd BELOW (z-after) overlay_hwnd so overlay is always on top
            ctypes.windll.user32.SetWindowPos(
                web_hwnd, overlay_hwnd, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            pass

    def _apply_web_view_native_round_rgn(self):
        """Hard-clip the QWebEngineView native HWND to the rounded app frame.

        Why: Qt per-pixel alpha rounds the MainWindow silhouette, but the
        QWebEngineView creates its own native HWND whose Chromium GPU compositor
        renders OPAQUE pixels into rectangular bounds. SetWindowRgn on that HWND
        is hardware clipping, independent of the Chromium compositor state.

        The slight jaggedness of HRGN is masked by `_RoundedWindowFrame`'s
        antialiased 24px gradient fillPath drawn on top.
        """
        if os.name != 'nt':
            return
        web_view = getattr(self, 'web_view', None)
        if web_view is None:
            return
        # In fullscreen mode the dark backdrop is painted by Chromium across the
        # whole screen rect — applying a rounded HRGN here would round its corners
        # too (the user sees that as "the fullscreen fill has rounded corners").
        # Strip the region so the backdrop fills the entire screen rectangle.
        # The inner 1100x760 .app-window keeps its own 24px rounding via CSS clip-path.
        if getattr(self, '_web_fs_active', False):
            try:
                user32 = ctypes.windll.user32
                user32.SetWindowRgn.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
                user32.SetWindowRgn.restype = ctypes.c_int
                top_hwnd = int(web_view.winId())
                user32.SetWindowRgn(wintypes.HWND(top_hwnd), 0, True)
            except Exception:
                pass
            return
        try:
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32
            top_hwnd = int(web_view.winId())
            logical_w = max(int(web_view.width()), 1)
            logical_h = max(int(web_view.height()), 1)
            native_w = logical_w
            native_h = logical_h
            user32.GetClientRect.argtypes = [
                wintypes.HWND, ctypes.POINTER(wintypes.RECT),
            ]
            user32.GetClientRect.restype = wintypes.BOOL
            rect = wintypes.RECT()
            if user32.GetClientRect(wintypes.HWND(top_hwnd), ctypes.byref(rect)):
                client_w = int(rect.right - rect.left)
                client_h = int(rect.bottom - rect.top)
                if client_w > 0 and client_h > 0:
                    native_w = client_w
                    native_h = client_h
            scale_x = native_w / float(logical_w)
            scale_y = native_h / float(logical_h)
            dpi_scale = max(0.5, min(4.0, (scale_x + scale_y) / 2.0))
            radius_diam = max(1, int(round(48 * dpi_scale)))  # 2 * 24px in native HWND pixels
            gdi32.CreateRoundRectRgn.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int,
            ]
            gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
            user32.SetWindowRgn.argtypes = [
                wintypes.HWND, ctypes.c_void_p, wintypes.BOOL,
            ]
            user32.SetWindowRgn.restype = ctypes.c_int

            def _apply_to(hwnd_int: int, cw: int, ch: int):
                try:
                    rgn = gdi32.CreateRoundRectRgn(0, 0, cw + 1, ch + 1, radius_diam, radius_diam)
                    if rgn:
                        # SetWindowRgn takes ownership of rgn — do NOT delete.
                        user32.SetWindowRgn(wintypes.HWND(hwnd_int), rgn, True)
                except Exception:
                    pass

            _apply_to(top_hwnd, native_w, native_h)

            # NOTE: we deliberately do NOT clip Chromium child HWNDs.
            # Applying SetWindowRgn to the internal D3D / RenderWidgetHost
            # children makes Chromium consider its surface occluded and it
            # stops painting entirely — the page goes invisible on startup.
            # The top-level web_view region alone is enough to clip the
            # rounded silhouette; the inner content stays painted via the
            # Chromium compositor's own bounds.
        except Exception:
            pass

    def _reset_web_view_clip(self):
        web_view = getattr(self, 'web_view', None)
        if web_view is None:
            return
        try:
            web_view.clearMask()
        except Exception:
            pass
        # Re-apply native rounded region — Qt's clearMask() can drop the
        # SetWindowRgn we installed on the QWebEngineView's HWND.
        self._apply_web_view_native_round_rgn()

    def _refresh_web_view_surface(self):
        web_view = getattr(self, 'web_view', None)
        if web_view is None:
            return
        try:
            web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            web_view.setStyleSheet("background: transparent; border: none;")
            # Page background must stay fully transparent so the area outside the rounded
            # .app-window does not paint a rectangular backing layer underneath the Qt frame.
            web_view.page().setBackgroundColor(QColor(0, 0, 0, 0))
            web_view.update()
            self.update()
            web_view.page().runJavaScript("""
(function(){
  document.documentElement.style.background = 'transparent';
  document.body.style.background = 'transparent';
  document.body.classList.remove('fullscreen');
  var win = document.getElementById('app-window');
  if (win) {
    win.style.left = '';
    win.style.top = '';
    win.style.transform = 'translateZ(0)';
    win.style.backfaceVisibility = 'hidden';
    requestAnimationFrame(function(){
      win.style.transform = '';
      win.style.backfaceVisibility = '';
    });
  }
})();
""")
        except Exception:
            pass

    def _set_native_corner_preference(self, rounded: bool):
        # MainWindow shape is defined by Qt per-pixel alpha (24px rounded path
        # in _RoundedWindowFrame). Letting DWM apply its own native rounding
        # (~8px in Windows 11) on top of that produces a competing rounded
        # silhouette around the Qt frame: the corner ring between Qt-24px
        # cutoff and DWM-8px outer shape is alpha=0 and shows the desktop —
        # the visible "tongues" with a different (smaller) radius. So MainWindow
        # is ALWAYS forced to DWMWCP_DONOTROUND regardless of fullscreen state;
        # the `rounded` argument is kept for backward compatibility only.
        del rounded  # intentionally unused
        if os.name != 'nt':
            return
        try:
            hwnd = int(self.winId())
            dwmapi = ctypes.windll.dwmapi
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_DONOTROUND = 1
            corner_pref = ctypes.c_int(DWMWCP_DONOTROUND)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_int(DWMWA_WINDOW_CORNER_PREFERENCE),
                ctypes.byref(corner_pref),
                ctypes.sizeof(corner_pref),
            )
        except Exception:
            pass

    def _reapply_translucent_window(self):
        """Re-assert per-pixel alpha + DWM corner/border attributes on MainWindow.

        After `showFullScreen()` / `showNormal()` Qt on Windows can drop the
        `WS_EX_LAYERED` extended style and DWM resets the corner preference to
        the system default (rounded). That makes the area outside the 24px
        Qt rounded fillPath suddenly OPAQUE / rounded with the smaller DWM
        radius, producing visible "full corners" around the application.
        Re-applying `WA_TranslucentBackground` forces Qt to put the layered
        style back, and `apply_windows_backdrop()` re-asserts DONOTROUND +
        no native border.
        """
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.setAutoFillBackground(False)
        except Exception:
            pass
        try:
            apply_windows_backdrop(self)
        except Exception:
            pass
        try:
            central = self.centralWidget()
            if central is not None:
                central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                central.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
                central.setAutoFillBackground(False)
                central.update()
            self.update()
        except Exception:
            pass

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        try:
            apply_windows_backdrop(self)
            self._apply_rounded_mask()
            self.update()
        except Exception:
            pass

    def _apply_rounded_mask(self):
        try:
            self.clearMask()
        except Exception:
            pass
        if os.name == 'nt':
            try:
                hwnd = int(self.winId())
                user32 = ctypes.windll.user32
                user32.SetWindowRgn(wintypes.HWND(hwnd), 0, True)
            except Exception:
                pass
        self._set_native_corner_preference(not self.isFullScreen())

    def _force_native_redraw(self):
        """Force a full DWM recomposition of the window.

        On first exit from web-fullscreen the Qt rounded silhouette is correct
        but DWM's cached frame of the previous geometry can still be visible at
        the corners (looks like "extra rounded backdrop"). Triggering
        `SetWindowPos(SWP_FRAMECHANGED)` + `RedrawWindow(RDW_INVALIDATE|
        RDW_FRAME|RDW_ALLCHILDREN|RDW_UPDATENOW)` is exactly what the screenshot
        hotkey (Win+Shift+S) indirectly causes via desktop recomposition — and
        it clears the stale corner pixels reliably.
        """
        if os.name != 'nt':
            try:
                self.update()
            except Exception:
                pass
            return
        try:
            hwnd = wintypes.HWND(int(self.winId()))
            user32 = ctypes.windll.user32
            # Bind argtypes / restypes so 64-bit handles aren't truncated to 32-bit.
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.RedrawWindow.argtypes = [
                wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
            ]
            user32.RedrawWindow.restype = wintypes.BOOL
            user32.InvalidateRect.argtypes = [
                wintypes.HWND, ctypes.c_void_p, wintypes.BOOL,
            ]
            user32.InvalidateRect.restype = wintypes.BOOL
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            user32.SetWindowPos(
                hwnd, wintypes.HWND(0), 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            RDW_INVALIDATE = 0x0001
            RDW_FRAME = 0x0400
            RDW_ALLCHILDREN = 0x0080
            RDW_UPDATENOW = 0x0100
            RDW_ERASE = 0x0004
            user32.RedrawWindow(
                hwnd, None, None,
                RDW_INVALIDATE | RDW_FRAME | RDW_ALLCHILDREN | RDW_UPDATENOW | RDW_ERASE,
            )
            user32.InvalidateRect(hwnd, None, True)
        except Exception:
            pass
        try:
            central = self.centralWidget()
            if central is not None:
                central.update()
            self.update()
        except Exception:
            pass

    def _force_geometry_nudge(self):
        """Nudge the window by 1px and back to force DWM/Chromium to fully
        re-composite the rounded surface. This is the heaviest hammer — used
        only after fullscreen exit when the corner pixels stay stale otherwise.
        """
        try:
            g = self.geometry()
            from PySide6.QtCore import QRect
            g_plus = QRect(g.x(), g.y(), g.width() + 1, g.height())
            self.setGeometry(g_plus)
            QTimer.singleShot(0, lambda: self.setGeometry(g))
            QTimer.singleShot(20, self._force_native_redraw)
        except Exception:
            pass

    def _install_web_engine_ui(self, host: QWidget):
        self._web_bridge = _WebUiBridge(self)
        self._web_channel = QWebChannel(self)
        self._web_channel.registerObject("proekt1Bridge", self._web_bridge)

        self.web_view = _WebEngineChromeView(self, host)
        self.web_view.setObjectName("webEngineUi")
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.web_view.setStyleSheet("background: transparent; border: none;")
        # Use the mid-point of the _RoundedWindowFrame gradient so Chromium shows
        # the theme colour before the HTML page has painted anything, instead of
        # a white or transparent flash during GPU surface initialisation.
        self.web_view.page().setBackgroundColor(QColor("#121431"))
        self.web_view.page().setWebChannel(self._web_channel)
        try:
            settings = self.web_view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        except Exception:
            pass
        try:
            self.web_view.page().fullScreenRequested.connect(self._on_web_fullscreen_requested)
        except Exception:
            pass
        self.web_view.setGeometry(host.rect())
        self._reset_web_view_clip()
        # Keep web_view hidden until the page is ready so the lifecycle overlay
        # (which is a non-native QWidget and would be painted *behind* Chromium's
        # native HWND if the view were visible) can actually be seen by the user
        # during the startup loading phase.  web_view.show() is called from
        # _finish_startup_overlay once _on_page_ready confirms the JS runtime
        # has executed and Chromium has had 200 ms to composite the first frame.
        self.web_view.hide()
        self.web_view.loadFinished.connect(self._on_web_engine_loaded)

        html_path = _design_preview_html_path()
        if os.path.exists(html_path):
            self.web_view.load(QUrl.fromLocalFile(html_path))
        else:
            self.web_view.setHtml(
                "<html><body style='background:#0a0b20;color:#e1e0ff;font-family:Segoe UI'>"
                "design-preview.html не найден</body></html>",
                QUrl.fromLocalFile(os.path.dirname(os.path.abspath(__file__)) + os.sep)
            )

    def _on_web_fullscreen_requested(self, request):
        try:
            toggle_on = bool(request.toggleOn())
            request.accept()
        except Exception:
            return
        try:
            if toggle_on:
                # Save full state for clean restore. Do NOT call showFullScreen()
                # or change windowState — on Windows that destroys the native peer
                # and Qt loses WS_EX_LAYERED (per-pixel alpha), after which the
                # rounded silhouette can never be re-established without
                # destroying/recreating the window. Instead just resize the
                # already frameless+translucent MainWindow to the screen geometry.
                self._web_fs_restore_geometry = self.geometry()
                self._web_fs_was_maximized = self.isMaximized()
                self._web_fs_active = True
                try:
                    self.web_view.clearMask()
                except Exception:
                    pass
                try:
                    self.clearMask()
                except Exception:
                    pass
                try:
                    screen = self.screen() or QApplication.primaryScreen()
                    scr_geom = screen.geometry() if screen is not None else self.geometry()
                except Exception:
                    scr_geom = self.geometry()
                if self.isMaximized():
                    # Leave the maximized state — just move the window above the taskbar
                    # to cover the full screen rect; Qt won't touch native styles.
                    try:
                        # showNormal would reset styles, so toggle through a flag-safe path
                        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMaximized)
                    except Exception:
                        pass
                self.setGeometry(scr_geom)
                self._sync_web_fullscreen_state(True)
                # Strip rounded HRGN from web_view HWND so the dark fullscreen
                # backdrop fills the screen as a full rectangle (no rounded edges).
                self._apply_web_view_native_round_rgn()
                QTimer.singleShot(0, self._apply_web_view_native_round_rgn)
                QTimer.singleShot(120, self._apply_web_view_native_round_rgn)
            else:
                self._web_fs_active = False
                self._sync_web_fullscreen_state(False)
                geom = getattr(self, '_web_fs_restore_geometry', None)
                if getattr(self, '_web_fs_was_maximized', False):
                    try:
                        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
                    except Exception:
                        if geom is not None:
                            self.setGeometry(geom)
                else:
                    if geom is not None:
                        self.setGeometry(geom)
                    self.ensure_visible()
                self._reset_web_view_clip()
                self._refresh_web_view_surface()
                self._apply_rounded_mask()
                self._force_native_redraw()
                QTimer.singleShot(0, lambda: self._sync_web_fullscreen_state(False))
                QTimer.singleShot(120, lambda: self._sync_web_fullscreen_state(False))
                QTimer.singleShot(0, self._reset_web_view_clip)
                QTimer.singleShot(120, self._reset_web_view_clip)
                QTimer.singleShot(40, self._refresh_web_view_surface)
                QTimer.singleShot(180, self._refresh_web_view_surface)
                QTimer.singleShot(0, self._apply_rounded_mask)
                QTimer.singleShot(120, self._apply_rounded_mask)
                QTimer.singleShot(400, self._apply_rounded_mask)
                QTimer.singleShot(0, self._force_native_redraw)
                QTimer.singleShot(60, self._force_native_redraw)
                QTimer.singleShot(180, self._force_native_redraw)
                QTimer.singleShot(400, self._force_native_redraw)
                # Heaviest hammer — 1px geometry nudge, which forces a full
                # native repaint chain (Qt resizeEvent + Chromium GPU surface
                # rebuild + DWM recomposition). This reliably clears any
                # stale corner pixels left over from the fullscreen rect.
                QTimer.singleShot(80, self._force_geometry_nudge)
                QTimer.singleShot(260, self._force_geometry_nudge)
        except Exception:
            pass
        except Exception:
            pass

    def _sync_web_fullscreen_state(self, active: bool):
        try:
            web_view = getattr(self, 'web_view', None)
            if web_view is None:
                return
            web_view.page().runJavaScript(
                "window.__PROEKT1_SET_FULLSCREEN_ACTIVE__ && "
                f"window.__PROEKT1_SET_FULLSCREEN_ACTIVE__({str(bool(active)).lower()});"
            )
        except Exception:
            pass

    def _on_web_engine_loaded(self, ok: bool):
        if not ok:
            # Race on quick app restart: Chromium child process may not be ready
            # yet, or the file:// load gets cancelled mid-flight. Retry a few
            # times before giving up so the UI doesn't stay invisible.
            attempts = getattr(self, '_web_load_attempts', 0) + 1
            self._web_load_attempts = attempts
            try:
                print(f"WEB UI: design-preview.html load failed (attempt {attempts})")
            except Exception:
                pass
            if attempts <= 5:
                def _retry():
                    try:
                        html_path = _design_preview_html_path()
                        if os.path.exists(html_path):
                            self.web_view.load(QUrl.fromLocalFile(html_path))
                    except Exception:
                        pass
                QTimer.singleShot(300 * attempts, _retry)
            else:
                # All retries exhausted — show the web view anyway so the user
                # is not stuck on the loading overlay with a broken UI behind it.
                try:
                    if not self.web_view.isVisible():
                        self.web_view.show()
                    ov = getattr(self, '_lifecycle_overlay', None)
                    if ov is not None and ov.isVisible():
                        ov.fade_out(400)
                except Exception:
                    pass
            return
        self._web_load_attempts = 0
        runtime_js = r"""
(function() {
  if (window.__PROEKT1_RUNTIME_READY__) return;
  window.__PROEKT1_RUNTIME_READY__ = true;
  document.body.classList.add('proekt1-runtime');

  const css = document.createElement('style');
  css.id = 'proekt1-runtime-css';
  css.textContent = `
        html, body { width:100%; height:100%; margin:0 !important; padding:0 !important; overflow:hidden !important; }
        /* Page surface MUST be transparent in normal mode so only the rounded .app-window
           is visible; otherwise a rectangular body fill peeks out from under the 24px corners. */
        html, body.proekt1-runtime { background:transparent !important; }
    body.proekt1-runtime .legend, body.proekt1-runtime .names-panel { display:none !important; }
        body.proekt1-runtime .app-window {
            width:100vw !important; height:100vh !important; left:0 !important; top:0 !important;
            transform:none !important; box-shadow:none !important;
            border-radius:24px !important; overflow:hidden !important;
            background-clip:padding-box !important;
            clip-path:inset(0 round 24px) !important;
            will-change:clip-path, transform;
        }
        /* Only fullscreen mode paints the dark backdrop behind the centered 1100x760 window.
           The color is controlled by the CSS variable --proekt1-fs-bg which is set from Python
           (current theme's fullscreen_bg) on load and on every theme change. */
        body.proekt1-runtime.fullscreen, html:fullscreen body.proekt1-runtime { background:var(--proekt1-fs-bg,#08091a) !important; }
        body.proekt1-runtime.fullscreen .app-window,
        html:fullscreen body.proekt1-runtime .app-window {
            width:1100px !important; height:760px !important; left:50% !important; top:50% !important;
            transform:translate(-50%, -50%) scale(1.2) !important;
            box-shadow:0 40px 120px rgba(0,0,0,0.7) !important;
            border-radius:24px !important; overflow:hidden !important;
            background-clip:padding-box !important;
            clip-path:inset(0 round 24px) !important;
        }
    body.proekt1-runtime .nav-btn, body.proekt1-runtime .triswitch-seg, body.proekt1-runtime .win-btn { user-select:none; -webkit-user-select:none; }
    body.proekt1-runtime .fan-card.web-alarm { border-color:rgba(255,175,86,0.55) !important; }
    body.proekt1-runtime .fan-card.web-alarm .fan-cap, body.proekt1-runtime .fan-card.web-alarm .fan-icon { color:#ffaf56 !important; }
    body.proekt1-runtime #tri-switch.web-soft-blocked .triswitch-seg:not(.active) { opacity:0.48; }
    body.proekt1-runtime #tri-switch.web-overlay { position:relative; }
    body.proekt1-runtime #tri-switch.web-overlay .triswitch-seg { color:transparent !important; }
    body.proekt1-runtime #tri-switch.web-overlay::after {
      content:attr(data-overlay); position:absolute; left:4px; right:4px; top:4px; bottom:4px;
      display:flex; align-items:center; justify-content:center; border-radius:11px;
      background:rgba(124,77,255,0.86); color:#fcf6ff; font-size:11pt; font-weight:700;
      letter-spacing:1px; text-transform:uppercase; pointer-events:none; white-space:nowrap;
    }
    body.proekt1-runtime #tri-switch.web-soft-blocked.web-overlay::after { background:rgba(180,60,70,0.86); }
  `;
  document.head.appendChild(css);

  const byId = id => document.getElementById(id);
  const clean = v => (v === null || v === undefined || v === '') ? '--' : String(v);
  const setText = (id, text) => { const el = byId(id); if (el) el.textContent = clean(text); };

    const fsIconExpand = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1 4.5V2a1 1 0 0 1 1-1h2.5M7.5 1H10a1 1 0 0 1 1 1v2.5M11 7.5V10a1 1 0 0 1-1 1H7.5M4.5 11H2a1 1 0 0 1-1-1V7.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
    const fsIconRestore = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M4 1H2a1 1 0 0 0-1 1v2M8 1h2a1 1 0 0 1 1 1v2M11 8v2a1 1 0 0 1-1 1H8M4 11H2a1 1 0 0 1-1-1V8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
    window.__PROEKT1_SET_FULLSCREEN_ACTIVE__ = function(active) {
        const body = document.body;
        const btn = byId('btn-win-max');
        const win = byId('app-window');
        if (active) {
            body.classList.add('fullscreen');
            if (btn) btn.innerHTML = fsIconRestore;
        } else {
            body.classList.remove('fullscreen');
            if (btn) btn.innerHTML = fsIconExpand;
            if (win) {
                win.style.transition = '';
                win.style.left = '';
                win.style.top = '';
                win.style.transform = '';
            }
        }
    };

    function initSettingsElements() {
        const root = byId('view-settings');
        if (!root || root.__proekt1SettingsTagged) return;
        root.__proekt1SettingsTagged = true;
        const toggles = Array.from(root.querySelectorAll('[data-toggle]'));
        ['autostart', 'minimized', 'purgeOnShutdown', 'loopProtection', 'keepLed'].forEach((key, idx) => {
            if (toggles[idx]) toggles[idx].dataset.setting = key;
        });
        const dropdowns = Array.from(root.querySelectorAll('.set-dropdown'));
        ['transport', 'theme', 'appLanguage', 'displayLang'].forEach((key, idx) => {
            if (dropdowns[idx]) dropdowns[idx].dataset.setting = key;
        });
        const ledRange = root.querySelector('input.set-range[data-target="led-val"]');
        const oledRange = root.querySelector('input.set-range[data-target="oled-val"]');
        if (ledRange) ledRange.dataset.setting = 'brightness';
        if (oledRange) oledRange.dataset.setting = 'oledBrightness';
    }

    function formatCurveRange(el) {
        const value = String(el?.value ?? '0');
        const kind = el?.dataset?.curveRange || '';
        if (kind === 'hyst') return value + '%';
        if (kind === 'delayOn' || kind === 'delayOff') return value + ' сек';
        return value;
    }
    function refreshCurveRange(el) {
        if (!el) return;
        const min = Number(el.min || 0);
        const max = Number(el.max || 100);
        const value = Number(el.value || 0);
        const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
        el.style.setProperty('--p', Math.max(0, Math.min(100, pct)) + '%');
        const outKey = el.dataset.target;
        const out = outKey ? document.querySelector('[data-out="' + outKey + '"]') : null;
        if (out) out.textContent = formatCurveRange(el);
    }
    function sourceLabel(index) {
        const value = Number(index);
        if (value === 0) return 'CPU';
        if (value === 1) return 'GPU';
        if (value === 3) return 'ВОДА';
        return 'MAX';
    }
    function curveState() {
        if (!window.__PROEKT1_CURVES_STATE__) {
            window.__PROEKT1_CURVES_STATE__ = {
                fanCurve: [[40, 30], [110, 100]],
                pumpCurve: [[40, 30], [110, 100]],
                sourceMode: 2,
                selectedPreset: 'Стандарт',
                profiles: ['Стандарт'],
                presets: { 'Стандарт': { fanCurve: [[40, 30], [110, 100]], pumpCurve: [[40, 30], [110, 100]] } },
                hystFan: 5,
                hystPump: 5,
                delayOnSeconds: 0,
                delayOffSeconds: 0
            };
        }
        return window.__PROEKT1_CURVES_STATE__;
    }
    function curveRootMode() {
        const active = document.querySelector('[data-curve-mode].active');
        return active?.dataset.curveMode === 'fan' ? 'fan' : 'pump';
    }
    const clampCurveValue = (value, min, max) => Math.max(min, Math.min(max, Number(value)));
    const curveMinTemp = 30;
    const curveMaxTemp = 110;
    const curveMapX = temp => ((clampCurveValue(temp, curveMinTemp, curveMaxTemp) - curveMinTemp) / (curveMaxTemp - curveMinTemp)) * 1000;
    const curveMapY = speed => 1000 - clampCurveValue(speed, 0, 100) * 10;
    const smoothCurveValue = value => Math.round(Number(value) * 100) / 100;
    function roundedCurvePoint(point) {
        return [
            Math.round(clampCurveValue(point?.[0], curveMinTemp, curveMaxTemp)),
            Math.round(clampCurveValue(point?.[1], 0, 100))
        ];
    }
    let _curveGeom = null;
    function readCurveGeom(root = document) {
        const svg = (root || document).querySelector('.curve-svg');
        const plotEl = byId('curve-plot');
        if (!svg || !plotEl) return null;
        const svgRect = svg.getBoundingClientRect();
        const plotRect = plotEl.getBoundingClientRect();
        if (!svgRect.width || !svgRect.height) return null;
        _curveGeom = {
            svgLeft: svgRect.left,
            svgTop: svgRect.top,
            svgWidth: svgRect.width,
            svgHeight: svgRect.height,
            plotLeft: plotRect.left,
            plotTop: plotRect.top
        };
        return _curveGeom;
    }
    function getCurveGeom(root = document) { return _curveGeom || readCurveGeom(root); }
    function invalidateCurveGeom() { _curveGeom = null; }
    window.addEventListener('resize', invalidateCurveGeom);
    function normalizeCurvePoints(points) {
        const normalized = (Array.isArray(points) ? points : [])
            .map(point => [
                smoothCurveValue(clampCurveValue(point?.[0], 30, 110)),
                smoothCurveValue(clampCurveValue(point?.[1], 0, 100))
            ])
            .filter(point => Number.isFinite(point[0]) && Number.isFinite(point[1]))
            .sort((a, b) => a[0] - b[0])
            .slice(0, 16);
        return normalized.length >= 2 ? normalized : [[40, 30], [110, 100]];
    }
    function curveSelection() {
        if (!window.__PROEKT1_CURVE_SELECTION__) window.__PROEKT1_CURVE_SELECTION__ = { fan: 0, pump: 0 };
        return window.__PROEKT1_CURVE_SELECTION__;
    }
    function curvePointsKey(mode) {
        return mode === 'fan' ? 'fanCurve' : 'pumpCurve';
    }
    function getCurvePoints(mode) {
        const state = curveState();
        const key = curvePointsKey(mode);
        state[key] = normalizeCurvePoints(state[key]);
        return state[key];
    }
    function setCurvePoints(mode, points) {
        const state = curveState();
        const key = curvePointsKey(mode);
        state[key] = normalizeCurvePoints(points);
        return state[key];
    }
    function selectedCurvePoint(mode) {
        const points = getCurvePoints(mode);
        const selection = curveSelection();
        selection[mode] = Math.max(0, Math.min(points.length - 1, Number(selection[mode]) || 0));
        return selection[mode];
    }
    function setSelectedCurvePoint(mode, index) {
        const points = getCurvePoints(mode);
        curveSelection()[mode] = Math.max(0, Math.min(points.length - 1, Number(index) || 0));
        return curveSelection()[mode];
    }
    function applyCurveProfile(name) {
        const state = curveState();
        const profile = state.presets && state.presets[name] ? state.presets[name] : null;
        state.selectedPreset = name || 'Стандарт';
        if (profile) {
            state.fanCurve = normalizeCurvePoints(profile.fanCurve || profile.fan_curve || []);
            state.pumpCurve = normalizeCurvePoints(profile.pumpCurve || profile.pump_curve || []);
        }
        setText('curve-profile-chip', state.selectedPreset);
        setText('curve-title', state.selectedPreset);
        setCurveMode(curveRootMode());
    }
    function curvePathD(points) {
        return points.map((point, idx) => (idx ? 'L ' : 'M ') + curveMapX(point[0]).toFixed(1) + ' ' + curveMapY(point[1]).toFixed(1)).join(' ');
    }
    function curveSegmentD(from, to) {
        return 'M ' + curveMapX(from[0]).toFixed(1) + ' ' + curveMapY(from[1]).toFixed(1) + ' L ' + curveMapX(to[0]).toFixed(1) + ' ' + curveMapY(to[1]).toFixed(1);
    }
    function hideCurvePreview() {
        byId('curve-plot')?.classList.remove('is-previewing');
        byId('curve-preview-before')?.setAttribute('d', '');
        byId('curve-preview-after')?.setAttribute('d', '');
    }
    function hideCursorDot() {
        byId('curve-cursor-dot')?.classList.remove('is-visible');
        byId('curve-cursor-label')?.classList.remove('is-visible');
    }
    function updateCursorDot(point, mode, geom = getCurveGeom()) {
        const dot = byId('curve-cursor-dot');
        const label = byId('curve-cursor-label');
        if (!dot || !label || !geom || !point) { hideCursorDot(); return; }
        const x = geom.svgLeft - geom.plotLeft + curveMapX(point[0]) / 1000 * geom.svgWidth;
        const y = geom.svgTop  - geom.plotTop  + curveMapY(point[1]) / 1000 * geom.svgHeight;
        dot.style.setProperty('--curve-x', x.toFixed(1) + 'px');
        dot.style.setProperty('--curve-y', y.toFixed(1) + 'px');
        dot.classList.toggle('is-pump', mode !== 'fan');
        dot.classList.toggle('is-fan',  mode === 'fan');
        dot.classList.add('is-visible');
        label.style.setProperty('--curve-x', x.toFixed(1) + 'px');
        label.style.setProperty('--curve-y', (y - 11).toFixed(1) + 'px');
        const rounded = roundedCurvePoint(point);
        const labelText = rounded[0] + '\u00b0C / ' + rounded[1] + '%';
        if (label.textContent !== labelText) label.textContent = labelText;
        label.classList.toggle('is-pump', mode !== 'fan');
        label.classList.toggle('is-fan',  mode === 'fan');
        label.classList.add('is-visible');
    }
    function previewCurvePoint(point, mode) {
        const plot = byId('curve-plot');
        const beforePath = byId('curve-preview-before');
        const afterPath = byId('curve-preview-after');
        const points = getCurvePoints(mode);
        if (!plot || !beforePath || !afterPath || !point || points.length >= 16) {
            hideCurvePreview();
            return;
        }
        let before = null;
        let after = null;
        points.forEach(item => {
            if (item[0] <= point[0]) before = item;
            else if (!after) after = item;
        });
        const previewClass = 'curve-preview-path curve-preview-' + mode;
        beforePath.setAttribute('class', previewClass);
        afterPath.setAttribute('class', previewClass);
        beforePath.setAttribute('d', before ? curveSegmentD(before, point) : '');
        afterPath.setAttribute('d', after ? curveSegmentD(point, after) : '');
        plot.classList.toggle('is-previewing', !!(before || after));
    }
    function placeCurveTooltip(point, mode, geom = getCurveGeom(), pointCount = null) {
        const tooltip = byId('curve-tooltip');
        if (!tooltip || !geom || !point) return;
        tooltip.classList.remove('has-edit');
        const x = geom.svgLeft - geom.plotLeft + curveMapX(point[0]) / 1000 * geom.svgWidth;
        const y = geom.svgTop - geom.plotTop + curveMapY(point[1]) / 1000 * geom.svgHeight;
        const rounded = roundedCurvePoint(point);
        tooltip.classList.toggle('is-fan', mode === 'fan');
        tooltip.classList.toggle('is-pump', mode !== 'fan');
        const tempInput = byId('curve-tt-temp');
        const pctInput = byId('curve-tt-pct');
        if (tempInput && document.activeElement !== tempInput && tempInput.value !== String(rounded[0])) tempInput.value = String(rounded[0]);
        if (pctInput && document.activeElement !== pctInput && pctInput.value !== String(rounded[1])) pctInput.value = String(rounded[1]);
        const pctField = pctInput?.closest('.curve-tt-field');
        if (pctField) pctField.classList.toggle('is-off', rounded[1] === 0);
        const deleteBtn = byId('curve-tt-delete');
        const hideDelete = (pointCount ?? getCurvePoints(mode).length) <= 2;
        if (deleteBtn) deleteBtn.style.display = hideDelete ? 'none' : '';
        const layoutKey = mode + ':' + rounded[0] + ':' + rounded[1] + ':' + (hideDelete ? 'locked' : 'editable');
        if (tooltip.dataset.layoutKey !== layoutKey || !tooltip._curveSize) {
            tooltip.dataset.layoutKey = layoutKey;
            tooltip._curveSize = { width: tooltip.offsetWidth, height: tooltip.offsetHeight };
        }
        tooltip._rightEdge = Math.round(x + tooltip._curveSize.width / 2);
        tooltip.style.left = Math.round(x - tooltip._curveSize.width / 2) + 'px';
        tooltip.style.right = '';
        tooltip.style.top = Math.round(y - 20 - tooltip._curveSize.height) + 'px';
    }
    function renderCurveLayer(mode, activeMode) {
        const normalized = getCurvePoints(mode);
        const active = mode === activeMode;
        const path = byId('curve-path-' + mode);
        const group = byId('curve-points-' + mode);
        if (path) {
            path.setAttribute('d', curvePathD(normalized));
            path.setAttribute('class', 'curve-path curve-path-' + mode + (active ? ' is-active' : ' is-muted'));
        }
        if (group) {
            const selected = selectedCurvePoint(mode);
            group.innerHTML = normalized.map((point, idx) => {
                const selectedClass = active && idx === selected ? ' is-selected' : '';
                const mutedClass = active ? '' : ' is-muted';
                const radius = active ? (idx === selected ? 10 : 8) : 5;
                return '<circle class="curve-point curve-point-' + mode + mutedClass + selectedClass + '" data-curve-mode="' + mode + '" data-point-index="' + idx + '" cx="' + curveMapX(point[0]).toFixed(1) + '" cy="' + curveMapY(point[1]).toFixed(1) + '" r="' + radius + '"></circle>';
            }).join('');
        }
        return normalized;
    }
    function stackActiveCurve(activeMode) {
        const inactiveMode = activeMode === 'fan' ? 'pump' : 'fan';
        const pathLayer = byId('curve-path-layer');
        const pointLayer = byId('curve-point-layer');
        if (pathLayer) {
            const inactivePath = byId('curve-path-' + inactiveMode);
            const activePath = byId('curve-path-' + activeMode);
            if (inactivePath) pathLayer.appendChild(inactivePath);
            if (activePath) pathLayer.appendChild(activePath);
        }
        if (pointLayer) {
            const inactiveGroup = byId('curve-points-' + inactiveMode);
            const activeGroup = byId('curve-points-' + activeMode);
            if (inactiveGroup) pointLayer.appendChild(inactiveGroup);
            if (activeGroup) pointLayer.appendChild(activeGroup);
        }
    }
    function renderCurve(points, mode) {
        const normalized = setCurvePoints(mode, points);
        renderCurveLayer('pump', mode);
        renderCurveLayer('fan', mode);
        stackActiveCurve(mode);
        const label = byId('curve-type-label');
        if (label) label.textContent = mode === 'fan' ? 'Обороты вентиляторов %' : 'Обороты насоса %';
        const count = byId('curve-points-count');
        if (count) count.textContent = String(normalized.length);
    }
    function updateCurveLayerLive(mode, points, activeMode) {
        const active = mode === activeMode;
        const path = byId('curve-path-' + mode);
        const group = byId('curve-points-' + mode);
        if (path) {
            path.setAttribute('d', curvePathD(points));
            path.setAttribute('class', 'curve-path curve-path-' + mode + (active ? ' is-active' : ' is-muted'));
        }
        if (group) {
            const circles = Array.from(group.querySelectorAll('.curve-point'));
            if (circles.length !== points.length) {
                renderCurveLayer(mode, activeMode);
                return;
            }
            const selected = Math.max(0, Math.min(points.length - 1, Number(curveSelection()[mode]) || 0));
            points.forEach((point, idx) => {
                const selectedClass = active && idx === selected ? ' is-selected' : '';
                const mutedClass = active ? '' : ' is-muted';
                const radius = active ? (idx === selected ? 10 : 8) : 5;
                const circle = circles[idx];
                circle.setAttribute('class', 'curve-point curve-point-' + mode + mutedClass + selectedClass);
                circle.setAttribute('data-curve-mode', mode);
                circle.setAttribute('data-point-index', String(idx));
                circle.setAttribute('cx', curveMapX(point[0]).toFixed(1));
                circle.setAttribute('cy', curveMapY(point[1]).toFixed(1));
                circle.setAttribute('r', String(radius));
            });
        }
    }
    function renderCurveLive(points, mode) {
        const normalized = setCurvePoints(mode, points);
        updateCurveLayerLive(mode, normalized, mode);
        const count = byId('curve-points-count');
        if (count) count.textContent = String(normalized.length);
        return normalized;
    }
    function setCurveMode(mode) {
        const next = mode === 'fan' ? 'fan' : 'pump';
        hideCurvePreview();
        cancelTooltipHide();
        byId('curve-tooltip')?.classList.remove('is-visible');
        document.querySelectorAll('[data-curve-mode]').forEach(btn => {
            const active = btn.dataset.curveMode === next;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-checked', active ? 'true' : 'false');
        });
        const state = curveState();
        const points = getCurvePoints(next);
        const hyst = next === 'fan' ? state.hystFan : state.hystPump;
        const hystInput = document.querySelector('[data-curve-range="hyst"]');
        if (hystInput) {
            hystInput.value = String(Math.max(3, Math.min(10, Number(hyst) || 5)));
            refreshCurveRange(hystInput);
        }
        const stat = byId('curve-hyst-stat');
        if (stat) stat.textContent = String(Math.max(3, Math.min(10, Number(hyst) || 5))) + '%';
        renderCurve(points, next);
        _updateCurveHistoryBtns();
    }
    var _curveHistoryMap = { pump: [], fan: [] };
    var _curveRedoMap    = { pump: [], fan: [] };
    function _updateCurveHistoryBtns() {
        const mode = curveRootMode();
        const undoBtn = byId('curve-undo-btn');
        const redoBtn = byId('curve-redo-btn');
        if (undoBtn) undoBtn.disabled = !(_curveHistoryMap[mode]?.length);
        if (redoBtn) redoBtn.disabled = !(_curveRedoMap[mode]?.length);
    }
    let _curveTooltipHideTimer = null;
    function cancelTooltipHide() {
        clearTimeout(_curveTooltipHideTimer);
        _curveTooltipHideTimer = null;
    }
    function scheduleTooltipHide() {
        clearTimeout(_curveTooltipHideTimer);
        _curveTooltipHideTimer = setTimeout(() => {
            byId('curve-tooltip')?.classList.remove('is-visible');
            _curveTooltipHideTimer = null;
        }, 2000);
    }
    function initCurvesElements() {
        const root = byId('view-curves');
        if (!root || root.__proekt1CurvesTagged) return;
        root.__proekt1CurvesTagged = true;
        root.querySelectorAll('[data-curve-mode]').forEach(btn => {
            btn.addEventListener('click', event => {
                event.stopPropagation();
                setCurveMode(btn.dataset.curveMode);
            });
        });
        root.querySelectorAll('[data-source-mode]').forEach(btn => {
            btn.addEventListener('click', event => {
                event.stopPropagation();
                root.querySelectorAll('[data-source-mode]').forEach(item => item.classList.remove('active'));
                btn.classList.add('active');
                const stat = byId('curve-source-stat');
                if (stat) stat.textContent = sourceLabel(btn.dataset.sourceMode);
            });
        });
        root.querySelectorAll('[data-curve-range]').forEach(input => {
            refreshCurveRange(input);
            input.addEventListener('input', () => {
                const state = curveState();
                const mode = curveRootMode();
                const value = Number(input.value || 0);
                if (input.dataset.curveRange === 'hyst') {
                    if (mode === 'fan') state.hystFan = value;
                    else state.hystPump = value;
                    const stat = byId('curve-hyst-stat');
                    if (stat) stat.textContent = value + '%';
                } else if (input.dataset.curveRange === 'delayOn') {
                    state.delayOnSeconds = value;
                } else if (input.dataset.curveRange === 'delayOff') {
                    state.delayOffSeconds = value;
                }
                refreshCurveRange(input);
            });
        });
        const minT = 30;
        const maxT = 110;
        const mapX = temp => ((clampCurveValue(temp, minT, maxT) - minT) / (maxT - minT)) * 1000;
        const mapY = speed => 1000 - clampCurveValue(speed, 0, 100) * 10;
        function pointFromEvent(event, geom = getCurveGeom(root)) {
            if (!geom) return null;
            return [
                smoothCurveValue(clampCurveValue(minT + ((event.clientX - geom.svgLeft) / geom.svgWidth) * (maxT - minT), minT, maxT)),
                smoothCurveValue(clampCurveValue(100 - ((event.clientY - geom.svgTop) / geom.svgHeight) * 100, 0, 100))
            ];
        }
        function pickPoint(event, geom = getCurveGeom(root), points = getCurvePoints(curveRootMode())) {
            if (!geom) return null;
            let best = null;
            let bestDist = 18;
            points.forEach((point, idx) => {
                const px = geom.svgLeft + mapX(point[0]) / 1000 * geom.svgWidth;
                const py = geom.svgTop + mapY(point[1]) / 1000 * geom.svgHeight;
                const dist = Math.hypot(event.clientX - px, event.clientY - py);
                if (dist < bestDist) { best = idx; bestDist = dist; }
            });
            return best;
        }
        function addCurvePoint(point) {
            const mode = curveRootMode();
            const points = getCurvePoints(mode).map(item => item.slice());
            if (points.length >= 16) { showMaxPointsToast(); return; }
            pushHistory(mode);
            const next = point || points[selectedCurvePoint(mode)] || points[points.length - 1] || [70, 70];
            const nextPoint = [
                smoothCurveValue(clampCurveValue(next[0], minT, maxT)),
                smoothCurveValue(clampCurveValue(next[1], 0, 100))
            ];
            points.push(nextPoint);
            const sorted = setCurvePoints(mode, points);
            const selected = sorted.findIndex(item => item[0] === nextPoint[0] && item[1] === nextPoint[1]);
            setSelectedCurvePoint(mode, selected >= 0 ? selected : sorted.length - 1);
            renderCurve(sorted, mode);
            placeCurveTooltip(sorted[selectedCurvePoint(mode)], mode);
            byId('curve-tooltip')?.classList.add('is-visible');
            scheduleTooltipHide();
        }
        function removeSelectedCurvePoint() {
            const mode = curveRootMode();
            const points = getCurvePoints(mode).map(item => item.slice());
            if (points.length <= 2) return;
            pushHistory(mode);
            const idx = selectedCurvePoint(mode);
            points.splice(idx, 1);
            const sorted = setCurvePoints(mode, points);
            setSelectedCurvePoint(mode, Math.min(idx, sorted.length - 1));
            renderCurve(sorted, mode);
        }
        const plot = byId('curve-plot');
        let dragIndex = null;
        function isNearTooltip(cx, cy) {
            const tt = byId('curve-tooltip');
            if (!tt?.classList.contains('is-visible')) return false;
            const r = tt.getBoundingClientRect();
            return cx >= r.left - 10 && cx <= r.right + 10 &&
                   cy >= r.top  - 10 && cy <= r.bottom + 10;
        }
        let maxToastTimer = null;
        function showMaxPointsToast() {
            const toast = byId('curve-max-toast');
            if (!toast) return;
            toast.textContent = 'максимум точек достигнут';
            toast.classList.add('is-visible');
            clearTimeout(maxToastTimer);
            maxToastTimer = setTimeout(() => toast.classList.remove('is-visible'), 1800);
        }
        // ── История: undo/redo ──
        function pushHistory(mode) {
            mode = mode || curveRootMode();
            const pts = getCurvePoints(mode).map(p => p.slice());
            const h = _curveHistoryMap[mode];
            if (h.length && JSON.stringify(h[h.length - 1]) === JSON.stringify(pts)) return;
            h.push(pts);
            if (h.length > 40) h.shift();
            _curveRedoMap[mode].length = 0;
            _updateCurveHistoryBtns();
        }
        function undoCurve() {
            const mode = curveRootMode();
            const h = _curveHistoryMap[mode], r = _curveRedoMap[mode];
            if (!h.length) return;
            r.push(getCurvePoints(mode).map(p => p.slice()));
            const prev = h.pop();
            setCurvePoints(mode, prev);
            renderCurve(getCurvePoints(mode), mode);
            cancelTooltipHide();
            byId('curve-tooltip')?.classList.remove('is-visible');
            _updateCurveHistoryBtns();
        }
        function redoCurve() {
            const mode = curveRootMode();
            const h = _curveHistoryMap[mode], r = _curveRedoMap[mode];
            if (!r.length) return;
            h.push(getCurvePoints(mode).map(p => p.slice()));
            const next = r.pop();
            setCurvePoints(mode, next);
            renderCurve(getCurvePoints(mode), mode);
            cancelTooltipHide();
            byId('curve-tooltip')?.classList.remove('is-visible');
            _updateCurveHistoryBtns();
        }
        function resetCurveToDefault(mode) {
            mode = mode || curveRootMode();
            pushHistory(mode);
            setCurvePoints(mode, [[30,20],[60,55],[85,88],[110,100]]);
            renderCurve(getCurvePoints(mode), mode);
            cancelTooltipHide();
            byId('curve-tooltip')?.classList.remove('is-visible');
            _updateCurveHistoryBtns();
        }
        if (plot) {
            plot.setAttribute('tabindex', '0');
            let pendingPointerMove = null;
            let pointerMoveRaf = 0;
            function cancelPointerMoveFrame() {
                pendingPointerMove = null;
                if (pointerMoveRaf) cancelAnimationFrame(pointerMoveRaf);
                pointerMoveRaf = 0;
            }
            function handlePointerMove(event) {
                const geom = getCurveGeom(root);
                if (!geom) return;
                const mode = curveRootMode();
                if (dragIndex === null) {
                    if (isNearTooltip(event.clientX, event.clientY)) {
                        plot.style.cursor = 'default';
                        hideCurvePreview();
                        hideCursorDot();
                        return;
                    }
                    const points = getCurvePoints(mode);
                    if (pickPoint(event, geom, points) !== null) {
                        plot.style.cursor = 'pointer';
                        hideCurvePreview();
                        hideCursorDot();
                        return;
                    }
                    plot.style.cursor = '';
                    const hPoint = pointFromEvent(event, geom);
                    previewCurvePoint(hPoint, mode);
                    updateCursorDot(hPoint, mode, geom);
                    return;
                }
                const point = pointFromEvent(event, geom);
                if (!point) return;
                const points = getCurvePoints(mode).map(item => item.slice());
                points[dragIndex] = point;
                const sorted = setCurvePoints(mode, points);
                const selected = sorted.findIndex(item => item[0] === point[0] && item[1] === point[1]);
                setSelectedCurvePoint(mode, selected >= 0 ? selected : Math.min(dragIndex, sorted.length - 1));
                dragIndex = selectedCurvePoint(mode);
                renderCurveLive(sorted, mode);
                placeCurveTooltip(sorted[dragIndex], mode, geom, sorted.length);
            }
            plot.addEventListener('pointerdown', event => {
                if (event.button !== undefined && event.button !== 0) return;
                if (event.target.closest('#curve-tooltip')) return;
                readCurveGeom(root);
                hideCursorDot();
                const idx = pickPoint(event);
                hideCurvePreview();
                if (idx === null) {
                    const point = pointFromEvent(event);
                    if (!point) return;
                    event.preventDefault();
                    event.stopPropagation();
                    addCurvePoint(point);
                    return;
                }
                event.preventDefault();
                event.stopPropagation();
                const mode = curveRootMode();
                pushHistory(mode);
                dragIndex = idx;
                plot.classList.add('is-dragging');
                try { plot.setPointerCapture(event.pointerId); } catch (exc) {}
                setSelectedCurvePoint(mode, idx);
                const points = getCurvePoints(mode);
                renderCurveLive(points, mode);
                placeCurveTooltip(points[selectedCurvePoint(mode)], mode, getCurveGeom(root), points.length);
                byId('curve-tooltip')?.classList.add('is-visible');
                cancelTooltipHide();
            });
            plot.addEventListener('pointermove', event => {
                if (dragIndex !== null) event.preventDefault();
                pendingPointerMove = { clientX: event.clientX, clientY: event.clientY, pointerId: event.pointerId };
                if (pointerMoveRaf) return;
                pointerMoveRaf = requestAnimationFrame(() => {
                    const next = pendingPointerMove;
                    pendingPointerMove = null;
                    pointerMoveRaf = 0;
                    if (next) handlePointerMove(next);
                });
            });
            const stopDrag = event => {
                cancelPointerMoveFrame();
                dragIndex = null;
                plot.classList.remove('is-dragging');
                try { plot.releasePointerCapture(event.pointerId); } catch (exc) {}
                if (byId('curve-tooltip')?.classList.contains('is-visible')) scheduleTooltipHide();
            };
            plot.addEventListener('pointerup', stopDrag);
            plot.addEventListener('pointercancel', stopDrag);
            plot.addEventListener('pointerenter', () => readCurveGeom(root));
            plot.addEventListener('pointerleave', () => { cancelPointerMoveFrame(); invalidateCurveGeom(); plot.style.cursor = ''; hideCurvePreview(); hideCursorDot(); });
            plot.addEventListener('dblclick', event => {
                if (pickPoint(event) !== null) return;
                if (event.target.closest('#curve-tooltip')) return;
                event.preventDefault();
                event.stopPropagation();
                addCurvePoint(pointFromEvent(event));
            });
            plot.addEventListener('keydown', event => {
                if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;
                if (event.key === 'Delete' || event.key === 'Backspace') {
                    event.preventDefault();
                    removeSelectedCurvePoint();
                }
            });
        }
        document.addEventListener('pointerdown', event => {
            if (event.target.closest('#curve-tooltip') || event.target.closest('.curve-point')) return;
            byId('curve-tooltip')?.classList.remove('is-visible');
            cancelTooltipHide();
        }, { capture: true });
        function applyTooltipInputs() {
            const mode = curveRootMode();
            const idx = selectedCurvePoint(mode);
            const points = getCurvePoints(mode).map(item => item.slice());
            if (idx < 0 || idx >= points.length) return;
            const tempInput = byId('curve-tt-temp');
            const pctInput = byId('curve-tt-pct');
            const tempVal = clampCurveValue(parseInt(tempInput?.value, 10) || points[idx][0], minT, maxT);
            const pctVal = clampCurveValue(parseInt(pctInput?.value, 10) || points[idx][1], 0, 100);
            pushHistory(mode);
            points[idx] = [tempVal, pctVal];
            const sorted = setCurvePoints(mode, points);
            const selected = sorted.findIndex(point => point[0] === tempVal && point[1] === pctVal);
            setSelectedCurvePoint(mode, selected >= 0 ? selected : Math.min(idx, sorted.length - 1));
            renderCurve(sorted, mode);
            placeCurveTooltip(sorted[selectedCurvePoint(mode)], mode);
        }
        ['curve-tt-temp', 'curve-tt-pct'].forEach(id => {
            const input = byId(id);
            if (!input) return;
            input.addEventListener('change', applyTooltipInputs);
            input.addEventListener('keydown', event => {
                if (event.key === 'Backspace' || event.key === 'Delete') { event.stopPropagation(); return; }
                if (event.key === 'Enter') { applyTooltipInputs(); event.target.blur(); }
            });
            input.addEventListener('input', () => {
                const tt = byId('curve-tooltip');
                if (!tt) return;
                tt.classList.add('has-edit');
                requestAnimationFrame(() => {
                    if (tt._rightEdge !== undefined)
                        tt.style.left = Math.round(tt._rightEdge - tt.offsetWidth) + 'px';
                });
            });
            input.addEventListener('focus', cancelTooltipHide);
            input.addEventListener('blur', scheduleTooltipHide);
        });
        byId('curve-tt-confirm')?.addEventListener('click', event => {
            event.stopPropagation();
            applyTooltipInputs();
            const tt = byId('curve-tooltip');
            tt?.classList.remove('is-visible', 'has-edit');
            cancelTooltipHide();
        });
        byId('curve-tt-delete')?.addEventListener('click', event => {
            event.stopPropagation();
            const mode = curveRootMode();
            const points = getCurvePoints(mode).map(item => item.slice());
            if (points.length <= 2) return;
            pushHistory(mode);
            const idx = selectedCurvePoint(mode);
            points.splice(idx, 1);
            const sorted = setCurvePoints(mode, points);
            setSelectedCurvePoint(mode, Math.min(idx, sorted.length - 1));
            renderCurve(sorted, mode);
            placeCurveTooltip(sorted[selectedCurvePoint(mode)], mode);
            scheduleTooltipHide();
        });
        // Кнопки отмены/повтора/сброса
        byId('curve-undo-btn')?.addEventListener('click', undoCurve);
        byId('curve-redo-btn')?.addEventListener('click', redoCurve);
        const _resetBtn = byId('curve-reset-btn');
        const _resetConfirm = byId('curve-reset-confirm');
        _resetBtn?.addEventListener('click', () => {
            _resetBtn.style.display = 'none';
            _resetConfirm?.classList.add('is-open');
        });
        byId('curve-reset-no')?.addEventListener('click', () => {
            _resetConfirm?.classList.remove('is-open');
            if (_resetBtn) _resetBtn.style.display = '';
        });
        byId('curve-reset-yes')?.addEventListener('click', () => {
            resetCurveToDefault();
            _resetConfirm?.classList.remove('is-open');
            if (_resetBtn) _resetBtn.style.display = '';
        });
        // Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z
        document.addEventListener('keydown', event => {
            const ae = document.activeElement;
            if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA')) return;
            if (!event.ctrlKey) return;
            if (event.key === 'z' && !event.shiftKey) { event.preventDefault(); undoCurve(); }
            else if (event.key === 'y' || (event.key === 'z' && event.shiftKey)) { event.preventDefault(); redoCurve(); }
        });
        // Автоскрытие тултипа: если курсор >10px от тултипа — скрываем через 2с
        document.addEventListener('pointermove', event => {
            const tt = byId('curve-tooltip');
            if (!tt?.classList.contains('is-visible')) return;
            if (dragIndex !== null) return;
            if (isNearTooltip(event.clientX, event.clientY)) {
                cancelTooltipHide();
            } else if (!_curveTooltipHideTimer) {
                scheduleTooltipHide();
            }
        });
    }

    function themeKeyToLabel(key) {
        return key === 'graphite' ? 'Графит' : key === 'light' ? 'Белый' : 'Фиолетовый';
    }
    function themeLabelToKey(label) {
        return label === 'Графит' ? 'graphite' : label === 'Белый' ? 'light' : 'violet';
    }
    function applyThemeClass(key) {
        document.body.classList.remove('theme-graphite', 'theme-light');
        if (key === 'graphite') document.body.classList.add('theme-graphite');
        else if (key === 'light') document.body.classList.add('theme-light');
        // Preview fullscreen backdrop colour immediately, even before clicking Save.
        // These values must match fullscreen_bg in the Python THEMES dict.
        const fsBg = key === 'graphite' ? '#0c0d0f' : key === 'light' ? '#1c1d2e' : '#08091a';
        document.documentElement.style.setProperty('--proekt1-fs-bg', fsBg);
    }
    function dropdownBySetting(key) {
        initSettingsElements();
        return document.querySelector('.set-dropdown[data-setting="' + key + '"]');
    }
    function dropdownMenuFor(dd) {
        if (!dd) return null;
        const btn = dd.querySelector('.set-dropdown-btn');
        return Array.from(document.querySelectorAll('.set-dropdown-menu')).find(menu => menu._ownerBtn === btn) || dd.querySelector('.set-dropdown-menu');
    }
    function setDropdownSetting(key, value) {
        const dd = dropdownBySetting(key);
        if (!dd) return;
        const label = dd.querySelector('.set-dropdown-label');
        const text = key === 'theme' ? themeKeyToLabel(value) : String(value || 'RU');
        dd.dataset.val = text;
        if (label) label.textContent = text;
        const menu = dropdownMenuFor(dd);
        if (menu) {
            menu.querySelectorAll('.set-dropdown-item').forEach(item => {
                item.classList.toggle('selected', item.dataset.value === text);
            });
        }
        if (key === 'theme') applyThemeClass(themeLabelToKey(text));
    }
    function getDropdownSetting(key) {
        const dd = dropdownBySetting(key);
        if (!dd) return key === 'theme' ? 'violet' : 'RU';
        const value = dd.dataset.val || dd.querySelector('.set-dropdown-label')?.textContent || '';
        return key === 'theme' ? themeLabelToKey(value) : value;
    }
    function setToggleSetting(key, on) {
        initSettingsElements();
        const el = document.querySelector('[data-toggle][data-setting="' + key + '"]');
        if (el) el.classList.toggle('on', !!on);
    }
    function getToggleSetting(key) {
        initSettingsElements();
        return !!document.querySelector('[data-toggle][data-setting="' + key + '"]')?.classList.contains('on');
    }
    function setRangeSetting(key, value) {
        initSettingsElements();
        const el = document.querySelector('input.set-range[data-setting="' + key + '"]');
        if (!el) return;
        const v = Math.max(Number(el.min || 0), Math.min(Number(el.max || 255), Number(value) || 0));
        el.value = String(v);
        const pct = ((v - Number(el.min || 0)) / (Number(el.max || 255) - Number(el.min || 0))) * 100;
        el.style.setProperty('--p', pct + '%');
        const outKey = el.dataset.target;
        const out = outKey ? document.querySelector('[data-out="' + outKey + '"]') : null;
        if (out) out.textContent = String(v);
    }
    function getRangeSetting(key) {
        initSettingsElements();
        return Number(document.querySelector('input.set-range[data-setting="' + key + '"]')?.value || 0);
    }

  window.PROEKT1 = {
    setMetric(key, value, pct, color) {
      const text = clean(value);
      const card = byId(key + '-card');
      const val = byId(key + '-val');
      const bar = byId(key + '-bar');
      if (val) val.textContent = text;
      if (card && color) card.style.setProperty('--bar-color', color);
      if (val && color) val.style.color = color;
      if (bar) bar.style.width = Math.max(0, Math.min(100, Number(pct) || 0)) + '%';
    },
    setFan(key, rpm, alarm, message) {
      const card = byId(key + '-card');
      const val = byId(key + '-val');
      if (val) val.textContent = clean(rpm);
      if (card) {
        card.classList.toggle('web-alarm', !!alarm);
        const cap = card.querySelector('.fan-cap');
        const base = key === 'fan1' ? 'ВЕНТИЛЯТОР 1' : 'ВЕНТИЛЯТОР 2';
        if (cap) cap.textContent = alarm && message ? base + ' · ' + String(message).toUpperCase() : base;
      }
    },
    setInfo(targets, profile, link, linkActive, loop, loopOk) {
      setText('targets-lbl', targets);
      setText('profile-lbl', profile);
      setText('link-badge', link);
      const badge = byId('link-badge');
      if (badge) badge.classList.toggle('active', !!linkActive);
      const loopEl = byId('loop-lbl');
      if (loopEl) {
        loopEl.textContent = clean(loop);
        loopEl.style.color = loopOk ? '#8bd5ff' : '#ffb4ab';
      }
    },
    setSwitch(state, softBlocked, overlay) {
      const ids = ['ts-stop', 'ts-work', 'ts-purge'];
      const st = Math.max(0, Math.min(2, Number(state) || 0));
      ids.forEach((id, idx) => { const el = byId(id); if (el) el.classList.toggle('active', idx === st); });
      const sw = byId('tri-switch');
      if (!sw) return;
      const text = clean(overlay);
      sw.classList.toggle('web-soft-blocked', !!softBlocked);
      sw.classList.toggle('web-overlay', text !== '--');
      if (text !== '--') sw.setAttribute('data-overlay', text);
      else sw.removeAttribute('data-overlay');
    },
        setPumpHours(hoursText, pctText) {
            setText('hours-val', hoursText || '00000.00');
            setText('hours-pct', pctText || '0%');
        },
        setSettings(state) {
            initSettingsElements();
            const s = state || {};
            setDropdownSetting('transport', s.transport || 'BLE');
            setDropdownSetting('theme', s.theme || 'violet');
            setDropdownSetting('appLanguage', s.appLanguage || 'RU');
            setDropdownSetting('displayLang', s.displayLang || 'RU');
            setToggleSetting('autostart', !!s.autostart);
            setToggleSetting('minimized', !!s.minimized);
            setToggleSetting('purgeOnShutdown', !!s.purgeOnShutdown);
            setToggleSetting('loopProtection', !!s.loopProtection);
            setToggleSetting('keepLed', !!s.keepLed);
            setRangeSetting('brightness', s.brightness ?? 255);
            setRangeSetting('oledBrightness', s.oledBrightness ?? 207);
            this.setPumpHours(s.hoursText, s.hoursPct);
        },
        getSettingsDraft() {
            initSettingsElements();
            return {
                transport: getDropdownSetting('transport'),
                theme: getDropdownSetting('theme'),
                appLanguage: getDropdownSetting('appLanguage'),
                displayLang: getDropdownSetting('displayLang'),
                autostart: getToggleSetting('autostart'),
                minimized: getToggleSetting('minimized'),
                purgeOnShutdown: getToggleSetting('purgeOnShutdown'),
                loopProtection: getToggleSetting('loopProtection'),
                keepLed: getToggleSetting('keepLed'),
                brightness: getRangeSetting('brightness'),
                oledBrightness: getRangeSetting('oledBrightness')
            };
        },
        setCurves(state) {
            initCurvesElements();
            const incoming = state || {};
            const incomingPresets = incoming.presets && typeof incoming.presets === 'object' ? incoming.presets : {};
            const presets = {};
            Object.keys(incomingPresets).forEach(name => {
                const profile = incomingPresets[name] || {};
                presets[name] = {
                    fanCurve: normalizeCurvePoints(profile.fanCurve || profile.fan_curve || []),
                    pumpCurve: normalizeCurvePoints(profile.pumpCurve || profile.pump_curve || [])
                };
            });
            window.__PROEKT1_CURVES_STATE__ = {
                fanCurve: normalizeCurvePoints(incoming.fanCurve || incoming.fan_curve || []),
                pumpCurve: normalizeCurvePoints(incoming.pumpCurve || incoming.pump_curve || []),
                sourceMode: Number(incoming.sourceMode ?? incoming.source_mode ?? 2),
                selectedPreset: String(incoming.selectedPreset || incoming.selected_preset || 'Стандарт'),
                profiles: Array.isArray(incoming.profiles) && incoming.profiles.length ? incoming.profiles : ['Стандарт'],
                presets: Object.keys(presets).length ? presets : { 'Стандарт': { fanCurve: normalizeCurvePoints(incoming.fanCurve || incoming.fan_curve || []), pumpCurve: normalizeCurvePoints(incoming.pumpCurve || incoming.pump_curve || []) } },
                hystFan: Number(incoming.hystFan ?? incoming.hyst_fan ?? 5),
                hystPump: Number(incoming.hystPump ?? incoming.hyst_pump ?? 5),
                delayOnSeconds: Number(incoming.delayOnSeconds ?? incoming.delay_on_seconds ?? 0),
                delayOffSeconds: Number(incoming.delayOffSeconds ?? incoming.delay_off_seconds ?? 0)
            };
            const s = curveState();
            setText('curve-profile-chip', s.selectedPreset || 'Стандарт');
            setText('curve-title', s.selectedPreset || 'Стандарт');
            const sourceStat = byId('curve-source-stat');
            if (sourceStat) sourceStat.textContent = sourceLabel(s.sourceMode);
            document.querySelectorAll('[data-source-mode]').forEach(btn => {
                btn.classList.toggle('active', Number(btn.dataset.sourceMode) === Number(s.sourceMode));
            });
            const dd = document.querySelector('[data-curve-profile="true"]');
            if (dd) {
                dd.dataset.val = s.selectedPreset || 'Стандарт';
                const label = dd.querySelector('.set-dropdown-label');
                if (label) label.textContent = s.selectedPreset || 'Стандарт';
                const menu = dropdownMenuFor(dd);
                if (menu) {
                    menu.innerHTML = s.profiles.map(name => '<div class="set-dropdown-item' + (name === s.selectedPreset ? ' selected' : '') + '" data-value="' + String(name).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;') + '">' + String(name).replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</div>').join('');
                    menu.querySelectorAll('.set-dropdown-item').forEach(item => {
                        item.addEventListener('click', event => {
                            event.stopPropagation();
                            menu.querySelectorAll('.set-dropdown-item').forEach(i => i.classList.remove('selected'));
                            item.classList.add('selected');
                            dd.dataset.val = item.dataset.value;
                            if (label) label.textContent = item.dataset.value;
                            menu.classList.remove('open');
                            if (menu._ownerBtn) menu._ownerBtn.classList.remove('open');
                            applyCurveProfile(item.dataset.value);
                        });
                    });
                }
            }
            const delayOn = document.querySelector('[data-curve-range="delayOn"]');
            const delayOff = document.querySelector('[data-curve-range="delayOff"]');
            if (delayOn) { delayOn.value = String(Math.max(0, Math.min(30, s.delayOnSeconds || 0))); refreshCurveRange(delayOn); }
            if (delayOff) { delayOff.value = String(Math.max(0, Math.min(30, s.delayOffSeconds || 0))); refreshCurveRange(delayOff); }
            setCurveMode(curveRootMode());
        },
        getCurvesDraft() {
            initCurvesElements();
            const s = curveState();
            const activeSource = document.querySelector('[data-source-mode].active');
            const profile = document.querySelector('[data-curve-profile="true"]')?.dataset.val || s.selectedPreset || 'Стандарт';
            return {
                selectedPreset: profile,
                fanCurve: normalizeCurvePoints(s.fanCurve || []),
                pumpCurve: normalizeCurvePoints(s.pumpCurve || []),
                sourceMode: Number(activeSource?.dataset.sourceMode ?? s.sourceMode ?? 2),
                hystFan: Number(s.hystFan || 5),
                hystPump: Number(s.hystPump || 5),
                delayOnSeconds: Number(document.querySelector('[data-curve-range="delayOn"]')?.value || s.delayOnSeconds || 0),
                delayOffSeconds: Number(document.querySelector('[data-curve-range="delayOff"]')?.value || s.delayOffSeconds || 0)
            };
        },
        showCurves() {
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
            byId('nav-pump')?.classList.add('active');
            byId('view-curves')?.classList.add('active');
            setText('page-title', 'НАСТРОЙКИ ОБОРОТОВ');
            setText('page-subtitle', '· кривые по температуре');
        },
    showDashboard() {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      byId('nav-dashboard')?.classList.add('active');
      byId('view-dashboard')?.classList.add('active');
      setText('page-title', 'ПАНЕЛЬ УПРАВЛЕНИЯ');
      setText('page-subtitle', '· онлайн');
    }
  };

  function bindBridge(bridge) {
    if (!bridge || window.__PROEKT1_BRIDGE_BOUND__) return;
    window.__PROEKT1_BRIDGE_BOUND__ = true;
        initSettingsElements();
        initCurvesElements();
    [['ts-stop', 0], ['ts-work', 1], ['ts-purge', 2]].forEach(([id, state]) => {
      const el = byId(id);
      if (el) el.addEventListener('click', event => { event.stopPropagation(); bridge.setSwitchState(state); }, true);
    });
    [['nav-dashboard', 'dashboard'], ['nav-pump', 'pump'], ['nav-led', 'led'], ['nav-settings', 'settings']].forEach(([id, key]) => {
      const el = byId(id);
      if (el) el.addEventListener('click', () => bridge.navClicked(key));
    });
    byId('btn-win-min')?.addEventListener('click', event => { event.stopPropagation(); bridge.windowAction('minimize'); }, true);
    byId('btn-win-close')?.addEventListener('click', event => { event.stopPropagation(); bridge.windowAction('close'); }, true);
        byId('btn-log')?.addEventListener('click', event => { event.stopPropagation(); bridge.settingsAction('log'); });
        byId('btn-settings-cancel')?.addEventListener('click', event => { event.stopPropagation(); bridge.settingsAction('cancel'); });
        byId('btn-settings-save')?.addEventListener('click', event => {
            event.stopPropagation();
            bridge.applySettings(JSON.stringify(window.PROEKT1.getSettingsDraft()));
        });
        byId('btn-curves-cancel')?.addEventListener('click', event => { event.stopPropagation(); bridge.curvesAction('cancel'); });
        byId('btn-curves-save')?.addEventListener('click', event => {
            event.stopPropagation();
            bridge.applyCurves(JSON.stringify(window.PROEKT1.getCurvesDraft()));
        });
        byId('sc-light')?.querySelector('.set-btn-ghost')?.addEventListener('click', event => {
            event.stopPropagation();
            bridge.settingsAction('led');
        });
        document.addEventListener('click', event => {
            const item = event.target && event.target.closest ? event.target.closest('.set-dropdown-item') : null;
            if (!item) return;
            // NOTE: menus are portalled to document.body, so item.closest('.set-dropdown') is null.
            // Must reach the original dropdown container via menu._ownerBtn instead.
            const menu = item.closest('.set-dropdown-menu');
            const dd = menu && menu._ownerBtn ? menu._ownerBtn.closest('.set-dropdown') : null;
            const isTheme = dd && (dd.dataset.setting === 'theme' || dd.dataset.theme === 'true');
            if (isTheme) applyThemeClass(themeLabelToKey(item.dataset.value));
        }, true);  // capture phase — fires before stopPropagation in dropdown item handlers
    // Signal Python that the bridge is connected and all event handlers are bound.
    // _finish_startup_overlay() will call web_view.show() only after this fires,
    // guaranteeing that Chromium has already composited the first GPU frame and
    // the interface is fully ready — eliminating the ~1 s violet-background flash.
    try { bridge.notifyWebUiReady(); } catch(e) {}
  }

  function initChannel() {
    if (typeof qt === 'undefined' || typeof QWebChannel === 'undefined') return;
    new QWebChannel(qt.webChannelTransport, channel => bindBridge(channel.objects.proekt1Bridge));
  }
  if (typeof QWebChannel === 'undefined') {
    const script = document.createElement('script');
    script.src = 'qrc:///qtwebchannel/qwebchannel.js';
    script.onload = initChannel;
    document.head.appendChild(script);
  } else {
    initChannel();
  }
})();
"""
        self.web_view.page().runJavaScript(runtime_js)
        # Apply the current theme's fullscreen backdrop colour immediately.
        # Use a JS callback on the LAST runJavaScript call so we know the renderer
        # has actually executed the setup code.  Only after that +200 ms GPU-paint
        # grace period do we allow the loading overlay to start fading — this
        # prevents the brief "violet frame" flash that happens when the overlay
        # becomes transparent before Chromium has composited the first GPU frame.
        try:
            _th = THEMES.get(current_theme_name(), THEMES['violet'])
            _fs_bg = _th.get('fullscreen_bg', '#08091a')
            def _on_page_ready(_result=None):
                # Primary path: bridge.notifyWebUiReady() fires from bindBridge
                # when QWebChannel connects (~1 s after loadFinished) — by that
                # time Chromium has composited its first frame, so web_view.show()
                # reveals the fully-rendered interface with no violet flash.
                # This timer is a safety fallback in case QWebChannel never connects
                # (e.g. qwebchannel.js fails to load).  The __init__ 20 s timer
                # is the last resort.
                QTimer.singleShot(8000, self._finish_startup_overlay)
            self.web_view.page().runJavaScript(
                f"document.documentElement.style.setProperty('--proekt1-fs-bg', {repr(_fs_bg)}); true;",
                _on_page_ready
            )
        except Exception:
            # Fallback: call directly if runJavaScript with callback fails.
            self._finish_startup_overlay()
        self._web_ready = True
        # Do NOT raise web_view here — the lifecycle overlay must stay above it
        # until _finish_startup_overlay fades it out.  Raising web_view now would
        # put it on top of the overlay and cause a flash of unstyled/transparent
        # Chromium surface before the overlay has had a chance to fade.
        self._reset_web_view_clip()
        self._refresh_web_view_surface()
        self._apply_rounded_mask()
        QTimer.singleShot(100, self._sync_web_snapshot)

    def _update_web_fullscreen_theme(self, theme_name: str = None):
        """Update the --proekt1-fs-bg CSS variable in the loaded WebEngine page
        so that the fullscreen backdrop colour matches the currently active theme.
        Safe to call at any time; does nothing if the web view is not yet ready."""
        try:
            web_view = getattr(self, 'web_view', None)
            if web_view is None or not getattr(self, '_web_ready', False):
                return
            if theme_name is None:
                theme_name = current_theme_name()
            palette = THEMES.get(theme_name, THEMES['violet'])
            fs_bg = palette.get('fullscreen_bg', '#08091a')
            web_view.page().runJavaScript(
                f"document.documentElement.style.setProperty('--proekt1-fs-bg', {repr(fs_bg)});"
            )
        except Exception:
            pass

    def _finish_startup_overlay(self):
        overlay = getattr(self, '_lifecycle_overlay', None)
        web_view = getattr(self, 'web_view', None)
        if overlay is None or web_view is None:
            if web_view is not None and not web_view.isVisible():
                web_view.show()
            return
        # Idempotency guard — notifyWebUiReady and the 8000 ms fallback timer
        # both call this method; only the first call should start the transition.
        if getattr(self, '_startup_transition_started', False):
            return
        self._startup_transition_started = True
        try:
            elapsed_ms = int((time.monotonic() - getattr(self, '_startup_overlay_started_at', time.monotonic())) * 1000)
            # Keep the overlay FULLY OPAQUE (web_view still hidden) until Chromium
            # has composited its first GPU frame.  We wait until at least 1800 ms
            # from app start, but no less than 500 ms from this call (bridge
            # connected), so the GPU pipeline has time to flush.
            # IMPORTANT: do NOT fade the overlay before web_view.show() — the fade
            # makes the overlay transparent which reveals the parent gradient
            # (violet/navy) behind it, causing the very flash we're trying to avoid.
            # Instead: reveal web_view first → overlay instantly goes behind the
            # Chromium HWND → then fade overlay silently (user can't see it).
            delay_ms = max(500, 1800 - elapsed_ms)

            def _reveal():
                if not web_view.isVisible():
                    web_view.show()
                # Overlay is now hidden behind the Chromium HWND — user can't see it.
                # Fade out to clean up widget state (stop spinner timer, hide widget).
                try:
                    if overlay.isVisible() and overlay.current_mode() == "startup":
                        overlay.fade_out(360)
                except Exception:
                    pass

            QTimer.singleShot(delay_ms, _reveal)
        except Exception:
            try:
                if not web_view.isVisible():
                    web_view.show()
            except Exception:
                pass

    def _show_lifecycle_shutdown(self):
        overlay = getattr(self, '_lifecycle_overlay', None)
        cw = self.centralWidget()
        if overlay is None or cw is None:
            return
        try:
            web_view = getattr(self, 'web_view', None)
            if web_view is not None:
                # QWebEngineView can keep a native Chromium surface above QWidget children on Windows.
                # Hide it before showing the shutdown layer so the closing screen is actually visible.
                web_view.hide()
            overlay.setGeometry(cw.rect())
            overlay.show_shutdown(getattr(self, 'theme', current_theme_name()))
            overlay.raise_()
            overlay.repaint()
            QApplication.processEvents()
        except Exception:
            pass

    def _web_js_call(self, name: str, *args):
        if not getattr(self, '_web_ready', False):
            return
        try:
            args_js = ", ".join(json.dumps(arg, ensure_ascii=False) for arg in args)
            self.web_view.page().runJavaScript(f"window.PROEKT1 && window.PROEKT1.{name}({args_js});")
        except Exception:
            pass

    def _web_metric_payload(self, value: Any, fallback_color: str) -> tuple[str, float, str]:
        text = "--"
        pct = 0.0
        color = fallback_color
        try:
            if value is not None and str(value) != "--":
                num = float(value)
                text = f"{int(round(num))}"
                pct = max(0.0, min(100.0, num))
                color = _temp_bar_color(num)
        except Exception:
            text = str(value) if value is not None else "--"
        return text, pct, color

    def _web_set_metric(self, key: str, value: Any, fallback_color: str):
        text, pct, color = self._web_metric_payload(value, fallback_color)
        self._web_js_call("setMetric", key, text, pct, color)

    def _web_set_fan(self, key: str, rpm: Any, alarm: bool = False, message: str = ""):
        text = "--" if rpm is None or str(rpm) == "--" else str(int(rpm)) if str(rpm).isdigit() else str(rpm)
        self._web_js_call("setFan", key, text, bool(alarm), message or "")

    def _settings_hours_values(self) -> tuple[str, str]:
        try:
            total_ms = self.pump_hours_base["total_running_ms"] + self.pump_hours_acc_run_ms
            total_min = self.pump_hours_base["total_minutes"] + self.pump_hours_acc_run_ms // 60000
            hours = total_min // 60
            minutes = total_min % 60
            avg_pct = 0.0
            if total_ms > 0:
                avg_pct = (self.pump_hours_base["sum_percent_ms"] + self.pump_hours_acc_sum_pct_ms) / total_ms * 100.0
            return f"{int(hours):05d}.{int(minutes):02d}", f"{avg_pct:.0f}%"
        except Exception:
            return "00000.00", "0%"

    def _web_set_pump_hours(self):
        hours_text, pct_text = self._settings_hours_values()
        self._web_js_call("setPumpHours", hours_text, pct_text)

    def _web_settings_snapshot(self) -> dict:
        hours_text, pct_text = self._settings_hours_values()
        return {
            "transport": getattr(self, 'transport', 'BLE') if getattr(self, 'transport', 'BLE') in ("BLE", "USB") else "BLE",
            "autostart": bool(getattr(self, 'autostart', False)),
            "minimized": bool(getattr(self, 'minimized', False)),
            "purgeOnShutdown": bool(getattr(self, 'purge_on_shutdown_enabled', False)),
            "loopProtection": bool(getattr(self, 'loop_protection_enabled', False)),
            "keepLed": bool(getattr(self, 'keep_led_on_disconnected', False)),
            "brightness": int(max(0, min(255, int(getattr(self, 'brightness', 255) or 0)))),
            "oledBrightness": int(max(0, min(255, int(getattr(self, 'oled_brightness', 207) or 0)))),
            "theme": getattr(self, 'theme', 'violet') if getattr(self, 'theme', 'violet') in THEMES else 'violet',
            "appLanguage": getattr(self, 'app_language', 'RU') if getattr(self, 'app_language', 'RU') in ("RU", "ENG") else "RU",
            "displayLang": getattr(self, 'display_lang', 'RU') if getattr(self, 'display_lang', 'RU') in ("RU", "ENG") else "RU",
            "hoursText": hours_text,
            "hoursPct": pct_text,
        }

    def _sync_web_settings(self):
        self._web_js_call("setSettings", self._web_settings_snapshot())

    def _curve_points_for_web(self, points: Any) -> list[list[float]]:
        cleaned: list[list[float]] = []
        try:
            for point in points or []:
                t_c = float(point[0])
                speed = float(point[1])
                if not math.isfinite(t_c) or not math.isfinite(speed):
                    continue
                cleaned.append([
                    round(max(30.0, min(110.0, t_c)), 2),
                    round(max(0.0, min(100.0, speed)), 2),
                ])
        except Exception:
            return []
        cleaned.sort(key=lambda item: item[0])
        return cleaned[:16]

    def _web_curves_snapshot(self) -> dict:
        selected = _last_preset_name if _last_preset_name and _last_preset_name != "--" else "Стандарт"
        try:
            profiles = list((getattr(self, 'presets', {}) or {}).keys()) or ["Стандарт"]
        except Exception:
            profiles = ["Стандарт"]
        if selected not in profiles:
            selected = profiles[0]
        presets_payload = {}
        try:
            for name, preset in (getattr(self, 'presets', {}) or {}).items():
                presets_payload[str(name)] = {
                    "fanCurve": self._curve_points_for_web((preset or {}).get("fan_curve", [])),
                    "pumpCurve": self._curve_points_for_web((preset or {}).get("pump_curve", [])),
                }
        except Exception:
            presets_payload = {}
        return {
            "fanCurve": self._curve_points_for_web(getattr(self, 'fan_points', [])),
            "pumpCurve": self._curve_points_for_web(getattr(self, 'pump_points', [])),
            "sourceMode": int(getattr(self, 'source_mode', 2) if getattr(self, 'source_mode', 2) in (0, 1, 2) else 2),
            "selectedPreset": selected,
            "profiles": profiles,
            "presets": presets_payload,
            "hystFan": int(max(3, min(10, int(getattr(self, 'hyst_fan', 5) or 5)))),
            "hystPump": int(max(3, min(10, int(getattr(self, 'hyst_pump', 5) or 5)))),
            "delayOnSeconds": int(max(0, min(30, int(getattr(self, 'delay_on_seconds', 0) or 0)))),
            "delayOffSeconds": int(max(0, min(30, int(getattr(self, 'delay_off_seconds', 0) or 0)))),
        }

    def _sync_web_curves(self):
        self._web_js_call("setCurves", self._web_curves_snapshot())

    def _build_curve_packet(self, tag1: str, tag2: str, points: Any, source_mode: int, hyst_pct: int, interp_mode: int = 1) -> bytes:
        pkt = bytearray()
        pkt.append(ord(tag1))
        pkt.append(ord(tag2))
        pkt.append(2)
        pkt.append(int(source_mode) if int(source_mode) in (0, 1, 2) else 2)
        pkt.append(int(interp_mode))
        clean_points = self._curve_points_for_web(points)[:16]
        if len(clean_points) < 2:
            clean_points = [[40.0, 30.0], [110.0, 100.0]]
        pkt.append(len(clean_points))
        pkt.append(max(3, min(10, int(hyst_pct))))
        for temp_c, speed_pct in clean_points:
            pkt += struct.pack('<hB', int(round(float(temp_c) * 10)), int(round(max(0.0, min(100.0, float(speed_pct))))))
        return bytes(pkt)

    def _save_curves_config(self, selected_preset: str):
        presets = getattr(self, 'presets', {}) or {}
        if not presets:
            presets = {"Стандарт": {"fan_curve": [p[:] for p in self.fan_points], "pump_curve": [p[:] for p in self.pump_points]}}
        if selected_preset not in presets:
            selected_preset = next(iter(presets), "Стандарт")
        presets[selected_preset] = {
            "fan_curve": self._curve_points_for_web(getattr(self, 'fan_points', [])),
            "pump_curve": self._curve_points_for_web(getattr(self, 'pump_points', [])),
        }
        self.presets = presets
        with open(self.curves_path, "w", encoding="utf-8") as f:
            json.dump({
                "fan_curve": self._curve_points_for_web(getattr(self, 'fan_points', [])),
                "pump_curve": self._curve_points_for_web(getattr(self, 'pump_points', [])),
                "source_mode": int(getattr(self, 'source_mode', 2) if getattr(self, 'source_mode', 2) in (0, 1, 2) else 2),
                "presets": self.presets,
                "selected_preset": selected_preset,
                "hyst_fan": int(max(3, min(10, int(getattr(self, 'hyst_fan', 5) or 5)))),
                "hyst_pump": int(max(3, min(10, int(getattr(self, 'hyst_pump', 5) or 5)))),
                "delay_on_seconds": int(max(0, min(30, int(getattr(self, 'delay_on_seconds', 0) or 0)))),
                "delay_off_seconds": int(max(0, min(30, int(getattr(self, 'delay_off_seconds', 0) or 0)))),
            }, f, ensure_ascii=False, indent=2)

    def _reset_curve_delay_state_if_needed(self, old_on: int, old_off: int):
        try:
            if old_on == int(getattr(self, 'delay_on_seconds', 0)) and old_off == int(getattr(self, 'delay_off_seconds', 0)):
                return
            with self._temp_hold_lock:
                self._fan_running_state = False
                self._fan_on_timer_start = None
                self._fan_pending_off_until = None
                self._fan_last_on_temps = None
                self._pump_running_state = False
                self._pump_on_timer_start = None
                self._pump_pending_off_until = None
                self._pump_last_on_temps = None
        except Exception:
            pass

    def _send_current_curves(self):
        try:
            source_mode = int(getattr(self, 'source_mode', 2))
            if source_mode not in (0, 1, 2):
                source_mode = 2
            fan_pkt = self._build_curve_packet('F', 'C', getattr(self, 'fan_points', []), source_mode, getattr(self, 'hyst_fan', 5))
            pump_pkt = self._build_curve_packet('P', 'C', getattr(self, 'pump_points', []), source_mode, getattr(self, 'hyst_pump', 5))
            tx_cmd_queue.put(("fan_curve", fan_pkt))
            tx_cmd_queue.put(("pump_curve", pump_pkt))
        except Exception as exc:
            try:
                print(f"Ошибка отправки кривых из WebUI: {exc}")
            except Exception:
                pass

    def _apply_web_curves_json(self, payload_json: str):
        global _last_preset_name
        try:
            data = json.loads(payload_json or "{}")
        except Exception:
            data = {}
        presets = getattr(self, 'presets', {}) or {}
        selected = str(data.get("selectedPreset") or _last_preset_name or "Стандарт")
        if selected not in presets:
            selected = "Стандарт" if "Стандарт" in presets else next(iter(presets), "Стандарт")

        incoming_fan = data.get("fanCurve", data.get("fan_curve", None))
        incoming_pump = data.get("pumpCurve", data.get("pump_curve", None))
        fan_from_web = self._curve_points_for_web(incoming_fan) if incoming_fan is not None else []
        pump_from_web = self._curve_points_for_web(incoming_pump) if incoming_pump is not None else []
        if len(fan_from_web) >= 2:
            self.fan_points = fan_from_web
        if len(pump_from_web) >= 2:
            self.pump_points = pump_from_web

        if selected in presets and (len(fan_from_web) < 2 or len(pump_from_web) < 2):
            try:
                if len(fan_from_web) < 2:
                    self.fan_points = self._curve_points_for_web(presets[selected].get("fan_curve", self.fan_points))
                if len(pump_from_web) < 2:
                    self.pump_points = self._curve_points_for_web(presets[selected].get("pump_curve", self.pump_points))
            except Exception:
                pass
        try:
            source_mode = int(data.get("sourceMode", getattr(self, 'source_mode', 2)))
        except Exception:
            source_mode = 2
        self.source_mode = source_mode if source_mode in (0, 1, 2) else 2
        try:
            self.hyst_fan = max(3, min(10, int(data.get("hystFan", getattr(self, 'hyst_fan', 5)))))
        except Exception:
            self.hyst_fan = 5
        try:
            self.hyst_pump = max(3, min(10, int(data.get("hystPump", getattr(self, 'hyst_pump', 5)))))
        except Exception:
            self.hyst_pump = 5
        old_on = int(getattr(self, 'delay_on_seconds', 0) or 0)
        old_off = int(getattr(self, 'delay_off_seconds', 0) or 0)
        try:
            self.delay_on_seconds = max(0, min(30, int(data.get("delayOnSeconds", old_on))))
        except Exception:
            self.delay_on_seconds = old_on
        try:
            self.delay_off_seconds = max(0, min(30, int(data.get("delayOffSeconds", old_off))))
        except Exception:
            self.delay_off_seconds = old_off
        _last_preset_name = selected
        try:
            self._save_curves_config(selected)
            self._reset_curve_delay_state_if_needed(old_on, old_off)
            self.save_app_config()
            self._send_current_curves()
        except Exception as exc:
            try:
                print(f"Ошибка сохранения кривых из WebUI: {exc}")
            except Exception:
                pass
        self._web_set_info(profile=_last_preset_name)
        self._sync_web_curves()

    def _apply_windows_autostart(self, enabled: bool):
        if os.name != 'nt':
            return
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    if getattr(sys, 'frozen', False):
                        cmd = f'"{sys.executable}"'
                    else:
                        cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
                    winreg.SetValueEx(key, "PROEKT1", 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, "PROEKT1")
                    except FileNotFoundError:
                        pass
        except Exception as exc:
            try:
                print(f"autostart apply error: {exc}")
            except Exception:
                pass

    def _sanitize_web_brightness(self, value: Any) -> int:
        try:
            v = int(value)
        except Exception:
            v = 255
        v = max(0, min(255, v))
        if v != 0 and v < LED_MIN_BRIGHT:
            v = LED_MIN_BRIGHT
        return v

    def _apply_web_settings_json(self, payload_json: str):
        try:
            data = json.loads(payload_json or "{}")
        except Exception:
            data = {}
        new_transport = str(data.get("transport", getattr(self, 'transport', 'BLE'))).upper()
        if new_transport not in ("BLE", "USB"):
            new_transport = "BLE"
        if new_transport != getattr(self, 'transport', 'BLE'):
            try:
                self.transport_combo.blockSignals(True)
                self.transport_combo.setCurrentText(new_transport)
            except Exception:
                pass
            finally:
                try:
                    self.transport_combo.blockSignals(False)
                except Exception:
                    pass
            self.on_transport_mode_changed(new_transport)
        else:
            self.transport = new_transport

        self.autostart = bool(data.get("autostart", False))
        self._apply_windows_autostart(self.autostart)
        self.minimized = bool(data.get("minimized", False))
        self.purge_on_shutdown_enabled = bool(data.get("purgeOnShutdown", False))

        self.keep_led_on_disconnected = bool(data.get("keepLed", False))
        self.send_keep_led_flag()
        self.loop_protection_enabled = bool(data.get("loopProtection", False))
        self.send_loopprot_flag()

        old_brightness = int(getattr(self, 'brightness', 255) or 0)
        new_brightness = self._sanitize_web_brightness(data.get("brightness", old_brightness))
        self.brightness = new_brightness
        if new_brightness != old_brightness:
            self.send_led_brightness_only(new_brightness)

        old_oled = int(getattr(self, 'oled_brightness', 207) or 0)
        try:
            new_oled = int(data.get("oledBrightness", old_oled))
        except Exception:
            new_oled = old_oled
        new_oled = max(0, min(255, new_oled))
        self.oled_brightness = new_oled
        if new_oled != old_oled:
            self.send_oled_brightness(new_oled)

        new_display_lang = str(data.get("displayLang", getattr(self, 'display_lang', 'RU'))).upper()
        if new_display_lang not in ("RU", "ENG"):
            new_display_lang = "RU"
        if new_display_lang != getattr(self, 'display_lang', 'RU'):
            self.display_lang = new_display_lang
            self.send_display_lang()
        else:
            self.display_lang = new_display_lang

        new_app_lang = str(data.get("appLanguage", getattr(self, 'app_language', 'RU'))).upper()
        self.app_language = new_app_lang if new_app_lang in ("RU", "ENG") else "RU"

        new_theme = str(data.get("theme", getattr(self, 'theme', 'violet')))
        if new_theme not in THEMES:
            new_theme = "violet"
        if new_theme != getattr(self, 'theme', 'violet'):
            self.theme = new_theme
            try:
                apply_app_theme(QApplication.instance(), new_theme)
            except Exception:
                pass
            try:
                self._lifecycle_overlay.setTheme(new_theme)
            except Exception:
                pass
            self._update_web_fullscreen_theme(new_theme)
        else:
            self.theme = new_theme

        self.save_app_config()
        self._sync_web_settings()

    def _on_web_settings_action(self, action: str):
        if action == "cancel":
            self._sync_web_settings()
        elif action == "log":
            self._open_log_window()
        elif action == "led":
            self._open_led_editor_from_web()

    def _open_led_editor_from_web(self):
        default_profile = {"colors": [[0, 0, 0]] * 20, "points": [[(50 + i * 35, 400)] for i in range(20)], "mode": "Свободное", "speed": 5}
        profiles = getattr(self, 'led_profiles', {}) or {}
        profile = profiles.get("Текущий", profiles.get("Стандарт", default_profile))
        mode_val = profile.get("mode") if isinstance(profile, dict) else "Свободное"
        if not isinstance(mode_val, str):
            mode_val = "Свободное"
        dialog = LEDCustomDialog(
            getattr(self, 'custom_colors', [QColor(0, 0, 0) for _ in range(20)]),
            self,
            points=profile.get("points") if isinstance(profile, dict) else None,
            mode=(mode_val or "Свободное"),
            profiles=profiles,
            speed=int(profile.get("speed", 5) or 5) if isinstance(profile, dict) else 5,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.custom_colors = dialog.colors
            self.led_custom_colors = dialog.colors
            self.led_profiles = getattr(dialog, 'led_profiles', profiles) or profiles
            self.led_profiles["Текущий"] = {
                "colors": [c.getRgb() for c in dialog.colors],
                "points": dialog.color_palette.points,
                "mode": dialog.color_palette.mode,
                "speed": dialog.color_palette.speed,
            }
            if dialog.color_palette.mode == "Моно градиентный" and dialog.color_palette.speed > 0 and len(dialog.color_palette.points) >= 2:
                start_x, start_y = dialog.color_palette.points[0][0]
                end_x, end_y = dialog.color_palette.points[1][0]
                start_color = dialog.color_palette.get_color_at_position(start_x, start_y)
                end_color = dialog.color_palette.get_color_at_position(end_x, end_y)
                custom_colors = bytes([start_color.red(), start_color.green(), start_color.blue(), end_color.red(), end_color.green(), end_color.blue(), dialog.color_palette.speed])
                self.send_led_command(5, self.brightness, 0, 0, 0, custom_colors)
            elif dialog.color_palette.mode == "Моно цвет":
                try:
                    x, y = dialog.color_palette.points[0][0]
                    c = dialog.color_palette.get_color_at_position(x, y)
                except Exception:
                    c = dialog.color_palette.colors[0] if dialog.color_palette.colors else QColor(0, 0, 0)
                self.send_led_command(0, self.brightness, c.red(), c.green(), c.blue())
            else:
                self.send_led_command(4, self.brightness, 0, 0, 0, dialog.color_palette.colors)
            self.save_app_config()
            self._sync_web_settings()
        except Exception as exc:
            try:
                print(f"web LED editor error: {exc}")
            except Exception:
                pass

    def _strip_info_prefix(self, text: str, prefix: str) -> str:
        value = (text or "").strip()
        if value.lower().startswith(prefix.lower()):
            value = value.split(":", 1)[1].strip()
        return value or "--"

    def _web_link_active(self, text: str) -> bool:
        low = (text or "").lower()
        return bool(text) and "--" not in text and "—" not in text and "ошиб" not in low and "нет" not in low

    def _web_set_info(self, targets=None, profile=None, link=None, loop=None, loop_ok=None):
        info = getattr(self, '_web_last_info', {}).copy()
        if targets is not None:
            info["targets"] = self._strip_info_prefix(str(targets), "Цели:")
        if profile is not None:
            info["profile"] = self._strip_info_prefix(str(profile), "Профиль:")
        if link is not None:
            link_text = self._strip_info_prefix(str(link), "Связь:")
            info["link"] = link_text if link_text != "--" else "Связь: --"
            info["linkActive"] = self._web_link_active(link_text)
        if loop is not None:
            info["loop"] = str(loop or "Гидролинии: --")
        if loop_ok is not None:
            info["loopOk"] = bool(loop_ok)
        self._web_last_info = info
        self._web_js_call(
            "setInfo",
            info.get("targets", "--"),
            info.get("profile", "--"),
            info.get("link", "Связь: --"),
            bool(info.get("linkActive", False)),
            info.get("loop", "Гидролинии: --"),
            bool(info.get("loopOk", False)),
        )

    def _sync_web_triswitch(self, switch=None):
        switch = switch or getattr(self, 'tri_switch', None)
        if switch is None:
            return
        try:
            state = switch.state()
        except Exception:
            state = 1 if getattr(self, 'system_running', True) else 0
        soft = bool(getattr(switch, '_soft_blocked', False))
        overlay = getattr(switch, '_overlay_text', None)
        if soft and not overlay:
            overlay = "подключите гидролинии"
        self._web_js_call("setSwitch", int(state), soft, overlay or "")

    def _sync_web_snapshot(self):
        try:
            self._web_set_metric("cpu", getattr(getattr(self, 'cpu_card', None), 'value_lbl', None).text(), "#8bd5ff")
        except Exception:
            self._web_set_metric("cpu", "--", "#8bd5ff")
        try:
            self._web_set_metric("gpu", getattr(getattr(self, 'gpu_card', None), 'value_lbl', None).text(), "#cdbdff")
        except Exception:
            self._web_set_metric("gpu", "--", "#cdbdff")
        try:
            self._web_set_metric("water", getattr(getattr(self, 'water_card', None), 'value_lbl', None).text(), "#8bd5ff")
        except Exception:
            self._web_set_metric("water", "--", "#8bd5ff")
        try:
            self._web_set_fan("fan1", getattr(getattr(self, 'fan1_card', None), 'value_lbl', None).text())
            self._web_set_fan("fan2", getattr(getattr(self, 'fan2_card', None), 'value_lbl', None).text())
        except Exception:
            pass
        self._web_set_info(link=getattr(self, 'link_status', "Связь: --"), targets=getattr(self, 'targets', "Цели: --"), profile=_last_preset_name)
        self._sync_web_triswitch()
        self._sync_web_settings()
        self._sync_web_curves()

    def _on_web_switch_state(self, state: int):
        state = max(0, min(2, int(state)))
        try:
            if getattr(self.tri_switch, '_soft_blocked', False) and state != 0:
                self.tri_switch.setState(0, animated=True, external=True)
                self._sync_web_triswitch()
                return
            self.tri_switch.setState(state, animated=True, external=True)
            self.on_switch_state_changed(state, True)
            self._sync_web_triswitch()
        except Exception:
            pass

    def _on_web_nav_clicked(self, key: str):
        if key == "pump":
            self._sync_web_curves()
        elif key == "led":
            try:
                self._sidebar_placeholder("Подсветка")
            finally:
                self._web_js_call("showDashboard")
        elif key == "settings":
            # HTML-макет сам переключает nav-settings -> view-settings.
            # Старый SettingsDialog больше не открываем поверх WebEngine UI.
            pass

    def _on_web_curves_action(self, action: str):
        if action == "cancel":
            self._sync_web_curves()
        elif action == "editor":
            self.show_curve_dialog()
            self._sync_web_curves()
            self._web_js_call("showCurves")

    def _on_web_window_action(self, action: str):
        if action == "minimize":
            self.showMinimized()
        elif action == "close":
            self.close()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger or reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_from_tray()

    def restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.ensure_visible()

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _section_caption(self, icon_key: str, text: str) -> QWidget:
        """Подпись раздела внутри панели управления (иконка + название капсом)."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        ico = _icon_label(icon_key, size=12, color="rgba(202,195,216,166)")
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: rgba(202,195,216,166); font-size: 8pt; font-weight: 700;"
            " letter-spacing: 2px; background: transparent;"
        )
        apply_label_typography(lbl, 8, QFont.Weight.Bold, 2.0)
        h.addWidget(ico)
        h.addWidget(lbl)
        h.addStretch(1)
        return w

    def _sidebar_placeholder(self, name: str):
        """Заглушка для ещё не реализованных экранов боковой панели."""
        try:
            QMessageBox.information(self, "PROEKT1", f"Экран «{name}» появится позже.")
        except Exception:
            pass

    def _on_sidebar_purge_clicked(self):
        """Кнопка ПРОДУВКА СИСТЕМЫ слева — переводит tri-switch в режим продувки."""
        try:
            self.tri_switch.setState(2, animated=True, external=False)
        except Exception:
            pass

    def ensure_visible(self):
        """Гарантирует, что окно видимо на каком-либо мониторе и умещается в его рабочую область."""
        try:
            g = self.geometry()
            # Ищем экран, на котором находится центр окна
            screen = QApplication.screenAt(g.center())
            if screen is None:
                # Центр за пределами всех экранов — ищем пересечение
                for s in QApplication.screens():
                    if s.availableGeometry().intersects(g):
                        screen = s
                        break
            if screen is None:
                # Окно полностью вне экранов — переместить на основной
                screen = QApplication.primaryScreen()
                avail = screen.availableGeometry()
                self.resize(min(1100, avail.width() - 40), min(760, avail.height() - 40))
                g = self.geometry()
                center = avail.center()
                self.move(center.x() - g.width() // 2, center.y() - g.height() // 2)
                return
            avail = screen.availableGeometry()
            # Подгоняем размер окна под рабочую область экрана
            new_w = max(self.minimumWidth(), min(g.width(), avail.width()))
            new_h = max(self.minimumHeight(), min(g.height(), avail.height()))
            if new_w != g.width() or new_h != g.height():
                self.resize(new_w, new_h)
            g = self.geometry()
            # Подгоняем позицию, чтобы окно не выходило за границы экрана
            x = max(avail.left(), min(g.x(), avail.right() - g.width()))
            y = max(avail.top(), min(g.y(), avail.bottom() - g.height()))
            if x != g.x() or y != g.y():
                self.move(x, y)
        except Exception:
            pass

    def _connect_screen_changed(self):
        """Подключает сигналы смены экрана/DPI для адаптации WebEngine-маски."""
        try:
            handle = self.windowHandle()
            if handle is not None:
                handle.screenChanged.connect(self._on_screen_changed)
                self._connect_screen_dpi_signals(handle.screen())
        except Exception:
            pass

    def _connect_screen_dpi_signals(self, screen):
        try:
            if screen is None or getattr(self, '_dpi_signal_screen', None) is screen:
                return
            self._dpi_signal_screen = screen
            screen.logicalDotsPerInchChanged.connect(self._on_screen_dpi_changed)
            screen.geometryChanged.connect(self._on_screen_dpi_changed)
            screen.availableGeometryChanged.connect(self._on_screen_dpi_changed)
        except Exception:
            pass

    def _on_screen_dpi_changed(self, *args):
        try:
            QTimer.singleShot(0, self._refresh_dpi_dependent_layout)
            QTimer.singleShot(120, self._refresh_dpi_dependent_layout)
        except Exception:
            pass

    def _refresh_dpi_dependent_layout(self):
        try:
            cw = self.centralWidget()
            web_view = getattr(self, 'web_view', None)
            if cw is not None and web_view is not None:
                web_view.setGeometry(cw.rect())
                self._reset_web_view_clip()
                web_view.raise_()
            self.ensure_visible()
            self._apply_rounded_mask()
        except Exception:
            pass

    def _on_screen_changed(self, screen):
        """Вызывается Qt при перетаскивании окна на монитор с другим DPI.
        Подгоняет размер и позицию окна под новый экран."""
        try:
            if screen is None:
                return
            self._connect_screen_dpi_signals(screen)
            avail = screen.availableGeometry()
            g = self.geometry()
            new_w = max(self.minimumWidth(), min(g.width(), avail.width()))
            new_h = max(self.minimumHeight(), min(g.height(), avail.height()))
            if new_w != g.width() or new_h != g.height():
                self.resize(new_w, new_h)
            g = self.geometry()
            x = max(avail.left(), min(g.x(), avail.right() - g.width()))
            y = max(avail.top(), min(g.y(), avail.bottom() - g.height()))
            if x != g.x() or y != g.y():
                self.move(x, y)
            self._refresh_dpi_dependent_layout()
        except Exception:
            pass

    def interpolate_curve(self, curve, temp, is_pump=False):
        if not curve:
            return 0
        curve = sorted(curve, key=lambda x: x[0])
        for i in range(len(curve) - 1):
            t1, s1 = curve[i]
            t2, s2 = curve[i + 1]
            if t1 <= temp <= t2:
                s = s1 + (s2 - s1) * (temp - t1) / (t2 - t1)
                if is_pump and s > 0:
                    s = max(s, 30)
                return s
        if temp < curve[0][0]:
            return 0
        else:
            s = curve[-1][1]
        if is_pump and s > 0:
            s = max(s, 30)
        return s

    def is_fan_alarm(self, pwm, rpm):
        if pwm <= 0:
            return False
        expected = pwm * 18  # 100% = 1800 RPM
        if rpm == 0 or rpm < expected / 2:  # не крутится или в два раза медленнее
            return True
        if pwm >= 30 and rpm < 450:  # низкие обороты при PWM >=30%
            return True
        if rpm < expected * 0.7:  # расхождение более 30%
            return True
        return False

    # ------------------------------------------------------------------
    # NEBULA CONTROL: хелперы применения темы (оставлены пустыми — setText живёт в InfoCard)
    # ------------------------------------------------------------------

    def update_ui(self):
        target_fan = 0.0
        have_temp = False
        temp_val = 0.0
        cpu, gpu = get_current_temps()
        self.cpu_card.setValue(cpu)
        self.gpu_card.setValue(gpu)
        self._web_set_metric("cpu", cpu, "#8bd5ff")
        self._web_set_metric("gpu", gpu, "#cdbdff")
        # Water temperature from ESP32 via USB (if available)
        with _water_lock:
            water = _water_temp
            last_ts = _water_last_ts
        # Print water once per second to console; ERR if not updated in ~1.5s
        now = time.time()
        if last_ts and (now - last_ts) <= 1.5:
            try:
                wv = int(water)
                print(f"water {wv}")
            except Exception:
                print("water ERR")
        else:
            print("water ERR")
        self.water_card.setValue(water)
        self._web_set_metric("water", water, "#8bd5ff")
        # Calculate fan target
        if cpu != "--" and gpu != "--":
            if self.source_mode == 0:
                temp = float(cpu)
                src = "CPU"
            elif self.source_mode == 1:
                temp = float(gpu)
                src = "GPU"
            else:
                temp = max(float(cpu), float(gpu))
                src = "MAX"
            have_temp = True
            temp_val = float(temp)
            target_fan = self.interpolate_curve(self.fan_points, temp)
            target_pump = self.interpolate_curve(self.pump_points, temp, is_pump=True)
            # Формат под макет: источник → режим агрегации
            if self.source_mode == 0:
                src_text = "CPU"
            elif self.source_mode == 1:
                src_text = "GPU"
            else:
                src_text = "CPU + GPU → Макс"
            self.targets = f"Цели: {src_text}"
            # Подсказка с фактическими процентами выводов
            try:
                self.info_card.targets_lbl.setToolTip(
                    f"Вентиляторы: {int(round(target_fan))}%   Помпа: {int(round(target_pump))}%"
                )
            except Exception:
                pass
            # Pump hours accumulation
            if target_pump > 30:
                pct = target_pump / 100
                self.pump_hours_acc_run_ms += 1000
                self.pump_hours_acc_sum_pct_ms += pct * 1000
        else:
            self.targets = "Цели: —"
        self.info_label.setText(f'<html><body><p>{self.targets}</p><p>Профиль: {_last_preset_name}</p><p>{self.link_status}</p></body></html>')
        self._web_set_info(targets=self.targets, profile=_last_preset_name, link=self.link_status)
        # Обновление статуса гидролиний из глобального кода
        # Отображение стойкого дефолта до первого чтения: если код ещё -1 и локальный флаг выключен
        try:
            with _loop_status_lock:
                code = _loop_status_code
            if code == -1 and not self.loop_protection_enabled:
                code = 0
            mapping = {
                0: "Гидролинии: защита выключена",
                1: "Гидролинии: норма",
                2: "Гидролинии: разрыв",
                3: "Гидролинии: норма",
                4: "Гидролинии: норма",
            }
            loop_text = mapping.get(code, "Гидролинии: --")
            self.loop_label.setText(loop_text)
            self._web_set_info(loop=loop_text, loop_ok=(code in (1, 3, 4)))
        except Exception:
            code = -1
        # Блокировка режима работы если защита включена и петля разорвана
        try:
            # code 2 = broken, code 3 = restored+was running, code 1 = restored+was paused, code 0 = disabled
            lock_needed = self.loop_protection_enabled and code == 2
            if lock_needed:
                # Принудительно UI в стоп
                if self.tri_switch.state() != 0:
                    self.tri_switch.setState(0, animated=False, external=True)
                self.system_running = False
                # Мягкая блокировка: разрешить перетаскивание без смены режима
                self.tri_switch.setSoftBlocked(True)
            else:
                self.tri_switch.setSoftBlocked(False)
        except Exception:
            pass
        # Отображение статуса ожидания целевых температур в режиме "работа"
        waiting_for_targets = False
        try:
            if (self.tri_switch.state() == 1) and not getattr(self, '_autostart_countdown_active', False) and not self.tri_switch._soft_blocked:
                # Новый критерий: если целевые значения по кривым равны 0 (ничего не нужно крутить), ждём достижения порога
                tf = 0.0
                tp = 0.0
                try:
                    tf = float(self.interpolate_curve(self.fan_points, temp_val)) if have_temp else 0.0
                except Exception:
                    tf = 0.0
                try:
                    tp = float(self.interpolate_curve(self.pump_points, temp_val, is_pump=True)) if have_temp else 0.0
                except Exception:
                    tp = 0.0
                waiting_for_targets = (tf <= 0.0 and tp <= 0.0)
                if waiting_for_targets:
                    # Включим скролл, если текст не помещается
                    self.tri_switch.setOverlayText("ожидаю целевые температуры", marquee=True)
                else:
                    if getattr(self.tri_switch, '_overlay_text', None) == "ожидаю целевые температуры":
                        self.tri_switch.clearOverlayText()
            else:
                if getattr(self.tri_switch, '_overlay_text', None) == "ожидаю целевые температуры":
                    self.tri_switch.clearOverlayText()
        except Exception:
            waiting_for_targets = False
            pass
        # Send TW flag to ESP32 when waiting state changes
        prev_wt = getattr(self, '_prev_waiting_for_targets', False)
        if waiting_for_targets != prev_wt:
            self._prev_waiting_for_targets = waiting_for_targets
            try:
                payload = b'TW' + bytes([1 if waiting_for_targets else 0])
                tx_cmd_queue.put(("ctrl", payload))
            except Exception:
                pass
        # Work mode flag: аварии только в режиме "работа"
        try:
            work_mode = (self.tri_switch.state() == 1) and bool(getattr(self, 'system_running', True)) and not bool(getattr(self, 'purge_active', False))
        except Exception:
            work_mode = True
        with _rpm_lock:
            # Fault flags from device (bit0=f1, bit1=f2)
            try:
                f1_flag = bool((_rpm_flags or 0) & 0x01)
                f2_flag = bool((_rpm_flags or 0) & 0x02)
            except Exception:
                f1_flag = f2_flag = False
            # Fan 1 alarm logic
            fan1_message = ""
            fan1_icon = str(_rpm1)
            # Prefer device flag; fallback to heuristic
            fan1_should_alarm = work_mode and (not waiting_for_targets) and (f1_flag or (target_fan > 0 and self.is_fan_alarm(target_fan, _rpm1)))
            if fan1_should_alarm:
                # Check 10s grace period after connection
                # If device raised flag, ignore local grace; trust firmware
                in_grace = (not f1_flag) and (self.connection_start_time and (time.time() - self.connection_start_time < 10))
                if not in_grace:
                    if self.fan1_alarm_start is None:
                        self.fan1_alarm_start = time.time()
                    elif time.time() - self.fan1_alarm_start > 5:
                        messages = ["авария", "проверьте крыльчатку", "вероятно заклинивание"]
                        if time.time() - self.fan1_last_switch > 2:
                            self.fan1_alarm_state = (self.fan1_alarm_state + 1) % 3
                            self.fan1_last_switch = time.time()
                        fan1_message = messages[self.fan1_alarm_state]
                        fan1_icon = '<span style="color:#ffaf56; font-size:24pt;">⚠️</span>'
                else:
                    # In grace period, reset alarm state
                    self.fan1_alarm_start = None
                    self.fan1_alarm_state = 0
            else:
                self.fan1_alarm_start = None
                self.fan1_alarm_state = 0
            # Fan 2 alarm logic
            fan2_message = ""
            fan2_icon = str(_rpm2)
            fan2_should_alarm = work_mode and (not waiting_for_targets) and (f2_flag or (target_fan > 0 and self.is_fan_alarm(target_fan, _rpm2)))
            if fan2_should_alarm:
                # Check 10s grace period after connection
                in_grace = (not f2_flag) and (self.connection_start_time and (time.time() - self.connection_start_time < 10))
                if not in_grace:
                    if self.fan2_alarm_start is None:
                        self.fan2_alarm_start = time.time()
                    elif time.time() - self.fan2_alarm_start > 5:
                        messages = ["авария", "проверьте крыльчатку", "вероятно заклинивание"]
                        if time.time() - self.fan2_last_switch > 2:
                            self.fan2_alarm_state = (self.fan2_alarm_state + 1) % 3
                            self.fan2_last_switch = time.time()
                        fan2_message = messages[self.fan2_alarm_state]
                        fan2_icon = '<span style="color:#ffaf56; font-size:24pt;">⚠️</span>'
                else:
                    # In grace period, reset alarm state
                    self.fan2_alarm_start = None
                    self.fan2_alarm_state = 0
            else:
                self.fan2_alarm_start = None
                self.fan2_alarm_state = 0
            # Alarm activation
            alarm_active = (fan1_message != "" or fan2_message != "")
            if alarm_active:
                if not self.alarm_triggered:
                    self.show()
                    self.raise_()
                    self.activateWindow()
                    self.alarm_triggered = True
            else:
                self.alarm_triggered = False
            # NEBULA CONTROL: обновление карт вентиляторов
            self.fan1_card.setRpm(_rpm1)
            self.fan1_card.setAlarm(bool(fan1_message), fan1_message)
            self.fan2_card.setRpm(_rpm2)
            self.fan2_card.setAlarm(bool(fan2_message), fan2_message)
            self._web_set_fan("fan1", _rpm1, bool(fan1_message), fan1_message)
            self._web_set_fan("fan2", _rpm2, bool(fan2_message), fan2_message)
        self.update_pump_hours_display()
        # Check for loaded pump hours from ESP
        global global_pump_hours
        if global_pump_hours and not hasattr(self, 'pump_hours_loaded'):
            self.pump_hours_base = {"version": global_pump_hours[0], "total_minutes": struct.unpack('<L', global_pump_hours[1:5])[0], "total_running_ms": struct.unpack('<Q', global_pump_hours[5:13])[0], "sum_percent_ms": struct.unpack('<Q', global_pump_hours[13:21])[0]}
            self.pump_hours_loaded = True

    def load_app_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.autostart = data.get("autostart", False)
                self.minimized = data.get("minimized", False)
                self.keep_led_on_disconnected = data.get("keep_led_on_disconnected", False)
                self.loop_protection_enabled = data.get("loop_protection", False)
                self.purge_on_shutdown_enabled = data.get("purge_on_shutdown", False)
                self.brightness = int(data.get("brightness", 255) or 255)
                self.oled_brightness = int(data.get("oled_brightness", 207) or 207)
                transport_choice = data.get("transport", self.transport)
                if transport_choice not in ("BLE", "USB"):
                    transport_choice = "BLE"
                self.transport = transport_choice
                try:
                    self.transport_combo.blockSignals(True)
                    self.transport_combo.setCurrentText(self.transport)
                except Exception:
                    pass
                finally:
                    try:
                        self.transport_combo.blockSignals(False)
                    except Exception:
                        pass
                # remove legacy test counter if present
                # Load custom_colors
                custom_colors_data = data.get("custom_colors")
                if custom_colors_data is not None:
                    try:
                        self.custom_colors = [QColor(*c) for c in custom_colors_data]
                    except:
                        self.custom_colors = [QColor(0,0,0) for _ in range(20)]
                # Load LED profiles
                self.led_profiles = data.get("led_profiles", {})
                # Apply current profile if exists
                current_profile = self.led_profiles.get("Текущий")
                if current_profile and "colors" in current_profile:
                    colors_data = current_profile["colors"]
                    if colors_data is not None:
                        try:
                            self.custom_colors = [QColor(*c) for c in colors_data]
                        except:
                            self.custom_colors = [QColor(0,0,0) for _ in range(20)]
                    prof_mode = current_profile.get("mode")
                    speed = int(current_profile.get("speed", 0) or 0)
                    # Градиент-анимация (режим редактора "Моно градиентный")
                    if isinstance(prof_mode, str) and prof_mode == "Моно градиентный" and speed > 0 and len(self.custom_colors) >= 2:
                        start_color = self.custom_colors[0]
                        end_color = self.custom_colors[min(len(self.custom_colors)-1, 1)]
                        grad_bytes = bytes([
                            start_color.red(), start_color.green(), start_color.blue(),
                            end_color.red(), end_color.green(), end_color.blue(),
                            speed if 0 < speed < 256 else 5
                        ])
                        self.current_mode = 5
                        self.brightness = int(self.brightness)
                        self.current_custom_colors = grad_bytes
                        self.current_r = self.current_g = self.current_b = 0
                        self.send_led_command(5, int(self.brightness), 0, 0, 0, grad_bytes)
                    elif isinstance(prof_mode, str) and prof_mode == "Моно цвет" and len(self.custom_colors) >= 1:
                        # Моно цвет: отправляем solid (mode=0) по первому цвету палитры
                        c0 = self.custom_colors[0]
                        self.current_mode = 0
                        self.brightness = int(self.brightness)
                        self.current_custom_colors = None
                        self.current_r, self.current_g, self.current_b = c0.red(), c0.green(), c0.blue()
                        self.send_led_command(0, int(self.brightness), self.current_r, self.current_g, self.current_b)
                    else:
                        # Любой другой режим — трактуем как статичную кастом палитру (в т.ч. "Свободное", "Свободное градиентное", "Зависимое градиентное")
                        self.current_mode = 4
                        self.brightness = int(self.brightness)
                        normalized_palette, _ = self._normalize_custom_palette(self.custom_colors)
                        self.current_custom_colors = normalized_palette
                        self.current_r = self.current_g = self.current_b = 0
                        self.send_led_command(4, int(self.brightness), 0, 0, 0, normalized_palette)
                # Флаг загрузки конфигурации для защиты от ранней переотправки
                self.led_config_loaded = True
                # Load delay settings (backwards compatible)
                try:
                    v = data.get("delay_on_seconds", None)
                    self.delay_on_seconds = int(v) if v is not None else getattr(self, 'delay_on_seconds', 0)
                except Exception:
                    self.delay_on_seconds = 0
                try:
                    v = data.get("delay_off_seconds", None)
                    self.delay_off_seconds = int(v) if v is not None else getattr(self, 'delay_off_seconds', 0)
                except Exception:
                    self.delay_off_seconds = 0
                # Display language
                try:
                    self.display_lang = data.get("display_lang", "RU")
                    if self.display_lang not in ("RU", "ENG"):
                        self.display_lang = "RU"
                except Exception:
                    self.display_lang = "RU"
                try:
                    self.app_language = data.get("app_language", "RU")
                    if self.app_language not in ("RU", "ENG"):
                        self.app_language = "RU"
                except Exception:
                    self.app_language = "RU"
                # Theme name (violet / graphite / light)
                try:
                    t = data.get("theme", "violet")
                    if t not in THEMES:
                        t = "violet"
                    self.theme = t
                except Exception:
                    self.theme = "violet"
        except Exception:
            self.brightness = 255
            self.oled_brightness = 207
            self.app_language = "RU"
            self.theme = "violet"

    def save_app_config(self):
        try:
            # Обновляем профиль "Текущий" из текущей палитры, если она задана
            if not hasattr(self, 'led_profiles') or self.led_profiles is None:
                self.led_profiles = {}
            prev_profile = dict(self.led_profiles.get("Текущий", {}) or {})
            palette = getattr(self, 'current_custom_colors', None)
            mode_now = getattr(self, 'current_mode', 0)
            # Если текущий режим градиент-анимация (mode=5) — сохраняем старт/конец как colors[0], colors[-1] + speed
            if mode_now == 5 and isinstance(palette, (bytes, bytearray)) and len(palette) == 7:
                self.led_profiles["Текущий"] = {
                    "mode": "Моно градиентный",
                    "colors": [
                        (palette[0], palette[1], palette[2]),
                        (palette[3], palette[4], palette[5])
                    ],
                    "speed": palette[6],
                }
                if "points" in prev_profile:
                    self.led_profiles["Текущий"]["points"] = prev_profile.get("points")
            elif mode_now == 0:
                self.led_profiles["Текущий"] = {
                    "mode": "Моно цвет",
                    "colors": [(int(self.current_r), int(self.current_g), int(self.current_b))]
                }
                if "points" in prev_profile:
                    self.led_profiles["Текущий"]["points"] = prev_profile.get("points")
                if "speed" in prev_profile:
                    self.led_profiles["Текущий"]["speed"] = prev_profile.get("speed")
            elif mode_now == 4 and isinstance(palette, list):
                try:
                    tuples = [tuple(int(max(0, min(255, v))) for v in rgb[:3]) for rgb in palette]
                    self.led_profiles.setdefault("Текущий", {})
                    self.led_profiles["Текущий"]["mode"] = self.led_profiles["Текущий"].get("mode", "Свободное")
                    self.led_profiles["Текущий"]["colors"] = tuples
                    if "points" in prev_profile:
                        self.led_profiles["Текущий"]["points"] = prev_profile.get("points")
                    if "speed" in prev_profile:
                        self.led_profiles["Текущий"]["speed"] = prev_profile.get("speed")
                except Exception:
                    pass
            elif palette is not None:
                try:
                    if isinstance(palette, (bytes, bytearray)):
                        tuples = [tuple(palette[i:i+3]) for i in range(0, len(palette), 3) if len(palette[i:i+3]) == 3]
                    else:
                        tuples = [tuple(int(v) for v in item[:3]) for item in palette if isinstance(item, (list, tuple))]
                    self.led_profiles.setdefault("Текущий", {})
                    self.led_profiles["Текущий"]["mode"] = self.led_profiles["Текущий"].get("mode", "Свободное")
                    self.led_profiles["Текущий"]["colors"] = tuples
                    if "points" in prev_profile:
                        self.led_profiles["Текущий"]["points"] = prev_profile.get("points")
                    if "speed" in prev_profile:
                        self.led_profiles["Текущий"]["speed"] = prev_profile.get("speed")
                except Exception:
                    pass
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "autostart": self.autostart,
                    "minimized": self.minimized,
                    "keep_led_on_disconnected": self.keep_led_on_disconnected,
                    "loop_protection": self.loop_protection_enabled,
                    "purge_on_shutdown": self.purge_on_shutdown_enabled,
                    "brightness": int(self.brightness),
                    "transport": self.transport,
                    "led_profiles": self.led_profiles,
                    "oled_brightness": int(getattr(self, 'oled_brightness', 207) or 207),
                    "delay_on_seconds": int(self.delay_on_seconds) if hasattr(self, 'delay_on_seconds') else 0,
                    "delay_off_seconds": int(self.delay_off_seconds) if hasattr(self, 'delay_off_seconds') else 0,
                    "app_language": getattr(self, 'app_language', 'RU'),
                    "display_lang": getattr(self, 'display_lang', 'RU'),
                    "theme": getattr(self, 'theme', 'violet')
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения config: {e}")

    def on_transport_mode_changed(self, mode):
        prev = getattr(self, 'transport', None)
        self.transport = mode
        if self._transport_thread:
            old = self._transport_thread
            self._transport_thread = None
            try:
                old.stop()
            except Exception:
                pass
            # КРИТИЧНО: дождаться завершения старого worker-потока ДО потери ссылки.
            # Иначе StatusEmitter (QObject) будет уничтожен в worker-потоке,
            # что вызывает "QObject::killTimer: Timers cannot be stopped from another thread"
            # и в итоге приводит к падению приложения (heap corruption).
            try:
                old.join(timeout=6)
            except Exception:
                pass
            # Принудительно отключаем сигнал старого emitter в главном потоке,
            # чтобы поздние emit'ы не доставлялись после смены транспорта.
            try:
                old.emitter.signal.disconnect()
            except Exception:
                pass
            # Явно удерживаем ссылку до конца метода (GC произойдёт в главном потоке)
            del old
        if mode == "BLE":
            self._transport_thread = BLETempSender(self.get_temps_for_transport, None)
            # Привязываем emitter к главному (UI) потоку — гарантия QueuedConnection
            try:
                app = QApplication.instance()
                if app is not None:
                    self._transport_thread.emitter.moveToThread(app.thread())
            except Exception:
                pass
            self._transport_thread.emitter.signal.connect(
                self.update_link_status, Qt.ConnectionType.QueuedConnection
            )
            self._transport_thread.start()
        elif mode == "USB":
            self._transport_thread = USBTempSender(self.get_temps_for_transport, None)
            try:
                app = QApplication.instance()
                if app is not None:
                    self._transport_thread.emitter.moveToThread(app.thread())
            except Exception:
                pass
            self._transport_thread.emitter.signal.connect(
                self.update_link_status, Qt.ConnectionType.QueuedConnection
            )
            self._transport_thread.start()
        if prev is not None and prev != mode:
            try:
                self.save_app_config()
            except Exception:
                pass

    def show_curve_dialog(self):
        dlg = FanPumpCurveDialog(self)
        dlg.exec()
        try:
            self.fan_points = [p[:] for p in self.presets[dlg.selected_preset]["fan_curve"]]
            self.pump_points = [p[:] for p in self.presets[dlg.selected_preset]["pump_curve"]]
            self.source_mode = dlg.source_mode
            self.hyst_fan = int(getattr(dlg, 'hyst_fan', getattr(self, 'hyst_fan', 5)))
            self.hyst_pump = int(getattr(dlg, 'hyst_pump', getattr(self, 'hyst_pump', 5)))
            self.delay_on_seconds = int(getattr(dlg, 'delay_on_seconds', getattr(self, 'delay_on_seconds', 0)))
            self.delay_off_seconds = int(getattr(dlg, 'delay_off_seconds', getattr(self, 'delay_off_seconds', 0)))
        except (KeyError, AttributeError, TypeError) as e:
            print(f"show_curve_dialog: ошибка при чтении пресета '{getattr(dlg, 'selected_preset', '?')}': {e}")
        self._sync_web_curves()

    def show_settings_dialog(self):
        dialog = SettingsDialog(
            current_transport=self.transport_combo.currentText(),
            autostart=self.autostart,
            minimized=self.minimized,
            pump_hours=True,
            brightness=self.brightness,
            oled_brightness=getattr(self, 'oled_brightness', 207),
            display_lang=getattr(self, 'display_lang', 'RU'),
            theme=getattr(self, 'theme', 'violet'),
            parent=self
        )
        total_min = self.pump_hours_base["total_minutes"] + self.pump_hours_acc_run_ms // 60000
        hours = total_min / 60
        total_ms = self.pump_hours_base["total_running_ms"] + self.pump_hours_acc_run_ms
        avg_pct = 0
        if total_ms > 0:
            avg_pct = (self.pump_hours_base["sum_percent_ms"] + self.pump_hours_acc_sum_pct_ms) / total_ms * 100
        dialog.update_pump_hours_display(hours, avg_pct)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_settings_from_dialog(dialog)

    def _apply_settings_from_dialog(self, dialog: 'SettingsDialog'):
        current_transport_choice = self.transport_combo.currentText()
        new_transport = dialog.get_transport()
        transport_changed = new_transport != current_transport_choice
        self.transport = new_transport
        if transport_changed:
            self.transport_combo.setCurrentText(new_transport)
            self.on_transport_mode_changed(new_transport)
        self.autostart = dialog.get_autostart()
        self.minimized = dialog.get_minimized()
        self.brightness = dialog.brightness
        self.oled_brightness = dialog.oled_brightness
        # keep LED on when disconnected flag
        try:
            self.keep_led_on_disconnected = dialog.get_keep_led()
            self.send_keep_led_flag()
        except Exception:
            pass
        # purge on shutdown flag
        try:
            self.purge_on_shutdown_enabled = dialog.get_purge_on_shutdown()
        except Exception:
            pass
        # loop protection flag
        try:
            self.loop_protection_enabled = dialog.get_loopprot()
            self.send_loopprot_flag()
        except Exception:
            pass
        # Display language
        try:
            new_lang = dialog.get_display_lang()
            if new_lang != getattr(self, 'display_lang', 'RU'):
                self.display_lang = new_lang
                self.send_display_lang()
        except Exception:
            pass
        # Theme change → требует перезапуска для полного применения (часть виджетов имеет inline-стили)
        try:
            new_theme = dialog.get_theme()
            cur_theme = getattr(self, 'theme', 'violet')
            if new_theme != cur_theme:
                self.theme = new_theme
                try:
                    apply_app_theme(QApplication.instance(), new_theme)
                except Exception:
                    pass
                try:
                    self._lifecycle_overlay.setTheme(new_theme)
                except Exception:
                    pass
                self._update_web_fullscreen_theme(new_theme)
                try:
                    QMessageBox.information(
                        self,
                        "Тема оформления",
                        "Тема будет полностью применена после перезапуска приложения."
                    )
                except Exception:
                    pass
        except Exception:
            pass
        self.save_app_config()

    def update_link_status(self, status):
        # Специальные внутрение уведомления от BLE-потока (мгновенные реакции)
        if status.startswith("LOOP:"):
            try:
                code = int(status.split(":", 1)[1])
            except Exception:
                code = -1
            # LOOP:2 — петля разорвана: принудительный стоп + блокировка
            # LOOP:3 — петля замкнулась, ДО разрыва была РАБОТА → авто-старт с отсчётом
            # LOOP:1 — петля замкнулась, ДО разрыва была ПАУЗА → просто разблокировать
            # LOOP:0 — защита отключена
            try:
                if code == 2:
                    # Петля разорвана — принудительный стоп
                    if hasattr(self, 'tri_switch'):
                        if self.tri_switch.state() != 0:
                            self.tri_switch.setState(0, animated=False, external=True)
                        self.system_running = False
                        self.tri_switch.setSoftBlocked(True)
                    # Если шёл отсчёт автозапуска — отменяем
                    if getattr(self, '_autostart_countdown_active', False):
                        self._autostart_timer.stop()
                        self._autostart_countdown_active = False
                        try:
                            self.tri_switch.clearOverlayText()
                        except Exception:
                            pass
                elif code == 3:
                    # Петля восстановлена, ДО разрыва была РАБОТА → авто-старт
                    if hasattr(self, 'tri_switch'):
                        self.tri_switch.setSoftBlocked(False)
                    if not getattr(self, '_autostart_countdown_active', False) and not getattr(self, 'purge_active', False):
                        # Переключаем кнопку в зелёный (РАБОТА) и запускаем отсчёт
                        if hasattr(self, 'tri_switch'):
                            self.tri_switch.setState(1, animated=True, external=True)
                        # system_running пока False — будет True после отсчёта
                        self._start_autostart_countdown(5)
                elif code == 1 or code == 0:
                    # Петля ОК (или защита выкл) — просто снять блокировку
                    if hasattr(self, 'tri_switch'):
                        self.tri_switch.setSoftBlocked(False)
                elif code == 4:
                    # ESP32 завершил auto-rearm — система уже запущена.
                    # Форсируем кнопку в РАБОТА без собственного отсчёта.
                    if getattr(self, '_autostart_countdown_active', False):
                        self._autostart_timer.stop()
                        self._autostart_countdown_active = False
                    if hasattr(self, 'tri_switch'):
                        self.tri_switch.clearOverlayText()
                        self.tri_switch.setSoftBlocked(False)
                        self.tri_switch.setState(1, animated=True, external=True)
                    self.system_running = True
            except Exception:
                pass
            # Перерисуем UI сейчас
            try:
                self.update_ui()
            except Exception:
                pass
            return
        # Обычный текст статуса связи
        parts = status.split(": ", 1)
        if len(parts) == 2:
            transport, rest = parts
            self.link_status = f"Связь: [{transport}] {rest}"
        else:
            self.link_status = f"Связь: {status}"
        self._web_set_info(link=self.link_status)
        # Set connection start time for grace period
        if "Подключено" in status:
            self.connection_start_time = time.time()
            self._prev_loop_status_code = None  # reset on reconnect
            # После переподключения восстанавливаем последний LED-профиль и яркость,
            # только если конфигурация уже загружена (во избежание дефолтного красного)
            try:
                if getattr(self, 'led_config_loaded', False):
                    QTimer.singleShot(200, self.resend_current_led_profile)
                # Переотправить флаг keep_led если включен
                QTimer.singleShot(400, self.send_keep_led_flag)
                # Переотправить флаг защиты гидролинии
                QTimer.singleShot(450, self.send_loopprot_flag)
                # Переотправить яркость OLED
                QTimer.singleShot(500, self.send_oled_brightness)
                # Переотправить язык дисплея
                QTimer.singleShot(550, self.send_display_lang)
                # Запросим текущий статус петли один раз (на случай если notify не пришёл)
                QTimer.singleShot(600, self.request_loop_status_once)
                # Синхронизировать состояние работа/стоп при подключении:
                # ESP32 должна сразу узнать текущее состояние переключателя.
                def _sync_run_state():
                    try:
                        sw = self.tri_switch.state()
                    except Exception:
                        sw = 1 if getattr(self, 'system_running', True) else 0
                    if sw == 1:
                        print("DEBUG: _sync_run_state -> ST (switch=1)")
                        self.send_control('ST')
                    elif sw == 0:
                        print("DEBUG: _sync_run_state -> SP (switch=0)")
                        self.send_control('SP')
                    # sw==2 (продувка) — не отправляем ST/SP
                _sync_run_state()  # немедленно
                QTimer.singleShot(1500, _sync_run_state)  # повтор для надёжности
            except Exception:
                pass


    def _start_autostart_countdown(self, seconds: int = 5):
        try:
            self._autostart_secs = int(max(1, seconds))
        except Exception:
            self._autostart_secs = 5
        self._autostart_countdown_active = True
        try:
            self.tri_switch.setOverlayText(f"работаю через {self._autostart_secs}", marquee=False)
        except Exception:
            pass
        self._autostart_timer.start()

    def _on_autostart_tick(self):
        if not self._autostart_countdown_active:
            self._autostart_timer.stop()
            return
        self._autostart_secs -= 1
        if self._autostart_secs > 0:
            try:
                self.tri_switch.setOverlayText(f"работаю через {self._autostart_secs}", marquee=False)
            except Exception:
                pass
            return
        # Countdown finished
        self._autostart_timer.stop()
        self._autostart_countdown_active = False
        try:
            # Clear overlay and switch to RUN visually
            self.tri_switch.clearOverlayText()
            self.tri_switch.setState(1, animated=True, external=True)
            self.system_running = True  # синхронизируем флаг
        except Exception:
            pass
        # NOTE: НЕ отправляем 'ST' — ESP32 сам выполнит auto-rearm и пришлёт LOOP:4.
        # Отправка 'ST' здесь привела бы к повторному g_start_pending → NVS boost check.
    def resend_current_led_profile(self):
        """Переотправить текущий LED-профиль после подключения BLE/USB.
        Восстанавливает режим, цвета/градиент и яркость на устройстве.
        """
        try:
            if not getattr(self, 'led_config_loaded', False):
                print("DEBUG: Skip resend_current_led_profile (config not loaded yet)")
                return
            cached = getattr(self, '_last_led_payload', None)
            if cached:
                print(f"DEBUG: Resend cached LED payload (len={len(cached)})")
                tx_cmd_queue.put(("led", cached))
                return
            palette = getattr(self, 'current_custom_colors', None)
            print(f"DEBUG: Resend fallback mode={self.current_mode} br={self.brightness}")
            self.send_led_command(self.current_mode, int(self.brightness), self.current_r, self.current_g, self.current_b, palette)
        except Exception as e:
            print(f"LED restore error: {e}")

    def get_temps_for_transport(self):
        """Return (cpu,gpu) strings for transport threads applying on/off delays.

        Behaviour:
        - `delay_on_seconds` requires the curve target to be >0 continuously for that many seconds
          before we consider the component "running" and start forcing the triggering temps.
        - `delay_off_seconds` keeps the component running for that many seconds after target drops to 0.
        - While a component is logically running (or in pending-off), we override outgoing temps
          with the last temperatures that triggered the start for that component, ensuring the
          device remains active.
        """
        raw_cpu, raw_gpu = get_current_temps()
        now = time.time()
        using_hold = False
        if raw_cpu == '--' or raw_gpu == '--':
            try:
                if self._last_valid_temps and (now - self._last_valid_temp_ts) <= float(self._temp_hold_seconds):
                    raw_cpu, raw_gpu = self._last_valid_temps
                    using_hold = True
                else:
                    return raw_cpu, raw_gpu
            except Exception:
                return raw_cpu, raw_gpu
        try:
            if raw_cpu == '--' or raw_gpu == '--':
                return raw_cpu, raw_gpu
            cpu_val = int(round(float(raw_cpu)))
            gpu_val = int(round(float(raw_gpu)))
        except Exception:
            return raw_cpu, raw_gpu
        if not using_hold:
            try:
                self._last_valid_temps = (str(int(cpu_val)), str(int(gpu_val)))
                self._last_valid_temp_ts = now
            except Exception:
                pass

        # Compute temp according to source_mode (mirror logic from update_ui)
        try:
            if self.source_mode == 0:
                temp = float(cpu_val)
            elif self.source_mode == 1:
                temp = float(gpu_val)
            else:
                temp = max(float(cpu_val), float(gpu_val))
        except Exception:
            temp = max(cpu_val, gpu_val)

        # Compute targets
        try:
            target_fan = float(self.interpolate_curve(self.fan_points, temp))
        except Exception:
            target_fan = 0.0
        try:
            target_pump = float(self.interpolate_curve(self.pump_points, temp, is_pump=True))
        except Exception:
            target_pump = 0.0

        cpu_out = cpu_val
        gpu_out = gpu_val

        # Короткий путь: если обе задержки = 0, просто отправляем актуальные температуры
        if (self.delay_on_seconds or 0) <= 0 and (self.delay_off_seconds or 0) <= 0:
            return str(int(round(cpu_out))), str(int(round(gpu_out)))

        with self._temp_hold_lock:
            # FAN logic
            if target_fan > 0.0:
                # saw non-zero target
                if not self._fan_running_state:
                    # start timer if needed
                    if (self.delay_on_seconds or 0) <= 0:
                        # start immediately
                        self._fan_running_state = True
                        self._fan_last_on_temps = (cpu_val, gpu_val)
                        self._fan_on_timer_start = None
                    else:
                        if self._fan_on_timer_start is None:
                            self._fan_on_timer_start = now
                            self._fan_last_on_temps = (cpu_val, gpu_val)
                        elif now - self._fan_on_timer_start >= float(self.delay_on_seconds):
                            self._fan_running_state = True
                            # keep last_on_temps as trigger temps
                            self._fan_on_timer_start = None
                else:
                    # already running — update trigger temps to current values
                    # so we never send stale temperatures from the initial trigger
                    self._fan_last_on_temps = (cpu_val, gpu_val)
                    self._fan_pending_off_until = None
            else:
                # target 0
                # cancel pending on timer
                self._fan_on_timer_start = None
                if self._fan_running_state:
                    if (self.delay_off_seconds or 0) <= 0:
                        self._fan_running_state = False
                        self._fan_last_on_temps = None
                        self._fan_pending_off_until = None
                    else:
                        if self._fan_pending_off_until is None:
                            self._fan_pending_off_until = now + float(self.delay_off_seconds)
                        elif now >= float(self._fan_pending_off_until):
                            self._fan_running_state = False
                            self._fan_last_on_temps = None
                            self._fan_pending_off_until = None

            # PUMP logic (same pattern)
            if target_pump > 0.0:
                if not self._pump_running_state:
                    if (self.delay_on_seconds or 0) <= 0:
                        self._pump_running_state = True
                        self._pump_last_on_temps = (cpu_val, gpu_val)
                        self._pump_on_timer_start = None
                    else:
                        if self._pump_on_timer_start is None:
                            self._pump_on_timer_start = now
                            self._pump_last_on_temps = (cpu_val, gpu_val)
                        elif now - self._pump_on_timer_start >= float(self.delay_on_seconds):
                            self._pump_running_state = True
                            self._pump_on_timer_start = None
                else:
                    # already running — update trigger temps to current values
                    self._pump_last_on_temps = (cpu_val, gpu_val)
                    self._pump_pending_off_until = None
            else:
                self._pump_on_timer_start = None
                if self._pump_running_state:
                    if (self.delay_off_seconds or 0) <= 0:
                        self._pump_running_state = False
                        self._pump_last_on_temps = None
                        self._pump_pending_off_until = None
                    else:
                        if self._pump_pending_off_until is None:
                            self._pump_pending_off_until = now + float(self.delay_off_seconds)
                        elif now >= float(self._pump_pending_off_until):
                            self._pump_running_state = False
                            self._pump_last_on_temps = None
                            self._pump_pending_off_until = None

            # If we're still in the delay-on period (pending start), do not send the triggering temperatures
            pending_on_fan = (not self._fan_running_state) and (self._fan_on_timer_start is not None) and (self.delay_on_seconds and (now - self._fan_on_timer_start < float(self.delay_on_seconds)))
            pending_on_pump = (not self._pump_running_state) and (self._pump_on_timer_start is not None) and (self.delay_on_seconds and (now - self._pump_on_timer_start < float(self.delay_on_seconds)))
            if pending_on_fan or pending_on_pump:
                # compute safe temperature below the earliest curve point to avoid triggering device
                try:
                    tmin = None
                    if self.fan_points and len(self.fan_points) > 0:
                        tmin = float(self.fan_points[0][0])
                    if self.pump_points and len(self.pump_points) > 0:
                        pt = float(self.pump_points[0][0])
                        tmin = pt if tmin is None else min(tmin, pt)
                    if tmin is None:
                        safe_temp = min(cpu_val, gpu_val)
                    else:
                        safe_temp = int(max(-50, int(math.floor(tmin)) - 1))
                except Exception:
                    safe_temp = min(cpu_val, gpu_val)
                cpu_out, gpu_out = int(safe_temp), int(safe_temp)
                return str(int(round(cpu_out))), str(int(round(gpu_out)))

            # Determine overrides: if either component is running or in pending-off, keep its trigger temps
            fan_active = self._fan_running_state or (self._fan_pending_off_until is not None and now < float(self._fan_pending_off_until))
            pump_active = self._pump_running_state or (self._pump_pending_off_until is not None and now < float(self._pump_pending_off_until))
            fan_override = None
            pump_override = None
            if fan_active and self._fan_last_on_temps:
                fan_override = self._fan_last_on_temps
            if pump_active and self._pump_last_on_temps:
                pump_override = self._pump_last_on_temps

            # Combine overrides: choose component-wise max to prefer keeping device running
            if fan_override and pump_override:
                try:
                    c = max(int(fan_override[0]), int(pump_override[0]), int(cpu_val))
                    g = max(int(fan_override[1]), int(pump_override[1]), int(gpu_val))
                    cpu_out, gpu_out = c, g
                except Exception:
                    cpu_out, gpu_out = cpu_val, gpu_val
            elif fan_override:
                try:
                    cpu_out, gpu_out = int(fan_override[0]), int(fan_override[1])
                except Exception:
                    cpu_out, gpu_out = cpu_val, gpu_val
            elif pump_override:
                try:
                    cpu_out, gpu_out = int(pump_override[0]), int(pump_override[1])
                except Exception:
                    cpu_out, gpu_out = cpu_val, gpu_val

        return str(int(round(cpu_out))), str(int(round(gpu_out)))

    def send_pump_hours(self, data: bytes, force: bool = False):
        print(f"DEBUG: send_pump_hours called, data len={len(data)}, force={force}")
        # Pass (payload, force) so transport threads can format correctly (BLE raw blob, USB HRW/HRF)
        tx_cmd_queue.put(("hours_write", (data, force)))

    def sync_pump_hours_to_esp(self, force: bool = False):
        current = self.pump_hours_base.copy()
        current["total_running_ms"] += self.pump_hours_acc_run_ms
        current["sum_percent_ms"] += int(self.pump_hours_acc_sum_pct_ms)
        current["total_minutes"] += self.pump_hours_acc_run_ms // 60000
        payload = struct.pack('<BLQQ', current["version"], current["total_minutes"], current["total_running_ms"], current["sum_percent_ms"])
        self.send_pump_hours(payload, force=force)
        self.pump_hours_last_sync = time.time()
        self.pump_hours_acc_run_ms = 0
        self.pump_hours_acc_sum_pct_ms = 0

    def send_control(self, cmd: str):
        try:
            payload = _build_ctrl_usb(cmd)
        except Exception as e:
            print(f"CTRL build error: {e}")
            return
        tx_cmd_queue.put(("ctrl", payload))

    def _direct_serial_purge(self):
        """Прямая отправка PG минуя tx_cmd_queue — для shutdown/sleep, когда очередь может не обработаться."""
        tt = self._transport_thread
        if tt is None:
            print("PURGE: нет транспорта")
            return
        if isinstance(tt, USBTempSender):
            # USB — прямая запись в serial port
            try:
                ser = tt.ser
                if ser and getattr(ser, 'is_open', False):
                    ser.write(b'PG')
                    ser.flush()
                    print("PURGE: PG отправлен напрямую через USB")
                else:
                    # Fallback через очередь
                    self.send_control('PG')
                    print("PURGE: serial недоступен, PG через очередь")
            except Exception as e:
                print(f"PURGE: USB error: {e}")
                try:
                    self.send_control('PG')
                except Exception:
                    pass
        elif isinstance(tt, BLETempSender):
            # BLE — urgent_purge флаг, BLE поток подхватит немедленно
            tt._purge_done.clear()
            tt.urgent_purge = True
            print("PURGE: urgent_purge flag set, ожидание BLE...")
            # Ждём до 3 сек пока BLE поток отправит PG
            if tt._purge_done.wait(timeout=3.0):
                print("PURGE: PG подтверждён BLE потоком")
            else:
                # Fallback — попытка через очередь
                self.send_control('PG')
                print("PURGE: BLE timeout, PG через очередь")
        else:
            self.send_control('PG')
            print("PURGE: PG через очередь (неизвестный транспорт)")

    def send_keep_led_flag(self):
        """Отправка флага разрешения подсветки без соединения.
        Формат: 'LK' + 1 байт (0 или 1).
        Используем ту же очередь ctrl.
        """
        try:
            val = 1 if getattr(self, 'keep_led_on_disconnected', False) else 0
            payload = b'LK' + bytes([val])
            tx_cmd_queue.put(("ctrl", payload))
            print(f"DEBUG: send_keep_led_flag -> {val}")
        except Exception as e:
            print(f"keep_led_flag error: {e}")

    def send_oled_brightness(self, value: int = None):
        """Send OLED display brightness to ESP32.
        Format: 'OB' + 1 byte (0..255). 0 = display off.
        """
        try:
            val = int(value if value is not None else getattr(self, 'oled_brightness', 207))
            val = max(0, min(255, val))
            payload = b'OB' + bytes([val])
            tx_cmd_queue.put(("ctrl", payload))
            print(f"DEBUG: send_oled_brightness -> {val}")
        except Exception as e:
            print(f"oled_brightness error: {e}")

    def send_display_lang(self):
        """Send display language to ESP32.
        Format: 'DL' + 1 byte (0=RU, 1=EN).
        """
        try:
            lang = getattr(self, 'display_lang', 'RU')
            val = 1 if lang == "ENG" else 0
            payload = b'DL' + bytes([val])
            tx_cmd_queue.put(("ctrl", payload))
            print(f"DEBUG: send_display_lang -> {lang} ({val})")
        except Exception as e:
            print(f"display_lang error: {e}")

    def send_loopprot_flag(self):
        """Отправка флага защиты гидролинии.
        Формат: 'LP' + 1 байт (0 или 1).
        """
        try:
            val = 1 if getattr(self, 'loop_protection_enabled', False) else 0
            payload = b'LP' + bytes([val])
            tx_cmd_queue.put(("ctrl", payload))
            print(f"DEBUG: send_loopprot_flag -> {val}")
            # Не ждём очередного тика: UI обновится сразу по notify, но подстрахуемся —
            # если notify не придёт, дернём разовый запрос
            QTimer.singleShot(300, self.request_loop_status_once)
        except Exception as e:
            print(f"loopprot_flag error: {e}")

    def request_loop_status_once(self):
        """Разовый запрос статуса петли (для BLE): если очередь и поток активны, он выполнит read.
        Для USB пока не реализовано (статус доступен только по BLE).
        """
        try:
            # Используем ту же BLE очередь: специальный псевдокомандный маркер
            tx_cmd_queue.put(("read_loop_status_once", b""))
        except Exception:
            pass

    def on_purge_clicked(self):
        self.purge_active = True
        self.send_control('PG')
        # Fail-safe timer to auto-clear local flag after purge duration (~16s)
        QTimer.singleShot(16000, lambda: setattr(self, 'purge_active', False))
        # Режим "тест" удалён

    def on_start_clicked(self):
        self.send_control('ST')
        self.purge_active = False
        self.system_running = True
        # Режим "тест" удалён

    def on_start_stop_clicked(self):
        # Deprecated after TriStateSwitch introduction (kept for compatibility)
        # Map legacy toggle to switch states
        if getattr(self, 'system_running', True):
            self.tri_switch.setState(0, animated=True)  # пауза/стоп
        else:
            self.tri_switch.setState(1, animated=True)  # работа

    # update_start_button_label removed; TriStateSwitch controls the UI state

    # Режим "тест" и связанные обработчики удалены

    def _on_auto_return_timer(self):
        """Автоматический возврат в 'стоп' по окончании продувки (вне теста).
        Срабатывает только если переключатель всё ещё в положении 'продувка'
        и пользователь не вмешался.
        """
        try:
            if hasattr(self, 'tri_switch') and self.tri_switch.state() == 2:
                # Переведём UI в стоп (внешнее изменение, без повторной отправки в on_switch_state_changed)
                self.tri_switch.setState(0, animated=True, external=True)
                self.system_running = False  # синхронизируем флаг
                # Явно сообщим устройству команду 'SP', чтобы зафиксировать STOP на прошивке
                self.send_control('SP')
        except Exception:
            pass

    def on_switch_state_changed(self, state: int, user: bool):
        """Обработка смены состояния переключателя.
        state: 0=стоп, 1=работа, 2=продувка
        user: True, если изменение инициировано пользователем (drag/snap); False — внешнее.
        """
        # Синхронизируем флаги
        if state == 0:
            self.system_running = False
        elif state == 1:
            self.system_running = True
        elif state == 2:
            self.purge_active = True

        # Планирование/отмена автоперевода в стоп
        try:
            if user:
                if state == 2:
                    # Запланировать возврат, если останемся в продувке до конца
                    self._auto_return_timer.stop()
                    self._auto_return_timer.start(self.PURGE_TOTAL_MS)
                else:
                    # Любое пользовательское действие в 'стоп' или 'работа' — отменяет возврат
                    self._auto_return_timer.stop()
        except Exception:
            pass

        # Если пользователь сменил состояние во время автостарта — отменить countdown
        if user and getattr(self, '_autostart_countdown_active', False):
            self._autostart_timer.stop()
            self._autostart_countdown_active = False
            try:
                self.tri_switch.clearOverlayText()
            except Exception:
                pass

        if not user:
            return

        # Отправка команд при пользовательском действии
        if state == 0:
            self.send_control('SP')
        elif state == 1:
            self.send_control('ST')
            # Дублируем 'ST' через 1.5с для надёжного старта после любых переходов
            try:
                QTimer.singleShot(1500, lambda: self.send_control('ST') if self.system_running else None)
            except Exception:
                pass
        elif state == 2:
            self.send_control('PG')
            # Автовозврат планируется выше через self._auto_return_timer

    def reset_pump_hours(self):
        payload = struct.pack('<BLQQ', 1, 0, 0, 0)
        self.send_pump_hours(payload)
        self.pump_hours_base = {"version": 1, "total_minutes": 0, "total_running_ms": 0, "sum_percent_ms": 0}
        self.pump_hours_acc_run_ms = 0
        self.pump_hours_acc_sum_pct_ms = 0
        global global_pump_hours
        global_pump_hours = None  # Сбросить, чтобы при следующем запуске загрузить новое от ESP
        QMessageBox.information(self, "Сброс", "Счётчик моточасов обнулён")

    def _normalize_custom_palette(self, colors: Any) -> tuple[List[Tuple[int, int, int]], bytes]:
        palette: List[Tuple[int, int, int]] = []
        raw = bytearray()
        if not colors:
            return palette, bytes(raw)
        if isinstance(colors, (bytes, bytearray)):
            data = bytes(colors)
            for i in range(0, len(data), 3):
                chunk = data[i:i+3]
                if len(chunk) != 3:
                    break
                rgb = (int(chunk[0]) & 0xFF, int(chunk[1]) & 0xFF, int(chunk[2]) & 0xFF)
                palette.append(rgb)
                raw.extend(rgb)
            return palette, bytes(raw)
        for item in colors:
            try:
                if isinstance(item, QColor):
                    rgb = (item.red(), item.green(), item.blue())
                elif isinstance(item, (tuple, list)) and len(item) >= 3:
                    rgb = (int(item[0]), int(item[1]), int(item[2]))
                else:
                    continue
                rgb = tuple(max(0, min(255, v)) for v in rgb)
                palette.append(cast(Tuple[int, int, int], rgb))
                raw.extend(rgb)
            except Exception:
                continue
        return palette, bytes(raw)

    def _normalize_gradient_payload(self, custom_colors: Any) -> bytes:
        if isinstance(custom_colors, (bytes, bytearray)):
            data = bytes(custom_colors)
        elif isinstance(custom_colors, (list, tuple)):
            flat = []
            for item in custom_colors:
                try:
                    flat.append(int(item) & 0xFF)
                except Exception:
                    flat.append(0)
            data = bytes(flat)
        else:
            data = b""
        if len(data) < 7:
            data = data + bytes(7 - len(data))
        if len(data) > 7:
            data = data[:7]
        return data

    def send_led_command(self, mode, brightness, r, g, b, custom_colors=None):
        try:
            mode_int = int(mode)
        except Exception:
            mode_int = 0
        try:
            bval = int(brightness) & 0xFF
        except Exception:
            bval = 0
        payload: Optional[bytes] = None
        if mode_int == 4:
            palette, custom_bytes = self._normalize_custom_palette(custom_colors)
            expected = LED_STRIP_LEDS * 3
            if len(custom_bytes) < expected:
                custom_bytes = custom_bytes + bytes(expected - len(custom_bytes))
            elif len(custom_bytes) > expected:
                custom_bytes = custom_bytes[:expected]
            self.current_custom_colors = palette
            self.current_r = self.current_g = self.current_b = 0
            payload = b'LX' + struct.pack('<BBB', 1, mode_int, bval) + custom_bytes
        elif mode_int == 5:
            grad_bytes = self._normalize_gradient_payload(custom_colors)
            self.current_custom_colors = grad_bytes
            self.current_r = self.current_g = self.current_b = 0
            payload = b'LX' + struct.pack('<BBB', 1, mode_int, bval) + grad_bytes
        else:
            try:
                r = int(r) & 0xFF
                g = int(g) & 0xFF
                b = int(b) & 0xFF
            except Exception:
                r = g = b = 0
            self.current_custom_colors = None
            self.current_r, self.current_g, self.current_b = r, g, b
            payload = b'LX' + struct.pack('<BBBBBB', 1, mode_int, bval, r, g, b)
        if not payload:
            return
        self.current_mode = mode_int
        self.brightness = bval
        self._last_led_payload = payload
        try:
            print(f"DEBUG: enqueue LED payload len={len(payload)} hex={payload.hex()}")
        except Exception:
            pass
        self._queue_led_payload(payload)

    def send_led_brightness_only(self, brightness: int):
        """Отправка только яркости (без изменения текущего режима/цветов/массивов).
        Работает одинаково для BLE и USB через общую очередь команд.
        """
        try:
            bval = int(brightness) & 0xFF
        except Exception:
            bval = 0
        self.brightness = bval
        payload = getattr(self, '_last_led_payload', None)
        if payload and len(payload) >= 5:
            buf = bytearray(payload)
            buf[4] = bval  # 'LX'<ver><mode><brightness>
            new_payload = bytes(buf)
            self._last_led_payload = new_payload
            self._queue_led_payload(new_payload)
            return
        # Фолбэк: пересобрать пакет из текущего состояния
        try:
            self.send_led_command(self.current_mode, bval, self.current_r, self.current_g, self.current_b, self.current_custom_colors)
        except Exception:
            pass

    def _queue_led_payload(self, payload: bytes):
        try:
            now = time.monotonic()
        except Exception:
            now = time.time()
        try:
            if self._last_led_sent_payload == payload and (now - self._last_led_sent_ts) < float(self._led_same_suppress_sec):
                return
        except Exception:
            pass
        delta = now - self._last_led_sent_ts
        if delta < float(self._led_min_interval_sec):
            self._led_pending_payload = payload
            if not self._led_debounce_timer.isActive():
                wait_ms = int(max(1, (float(self._led_min_interval_sec) - delta) * 1000.0))
                self._led_debounce_timer.start(wait_ms)
            return
        tx_cmd_queue.put(("led", payload))
        self._last_led_sent_payload = payload
        self._last_led_sent_ts = now

    def _flush_pending_led_payload(self):
        payload = self._led_pending_payload
        if not payload:
            return
        self._led_pending_payload = None
        self._queue_led_payload(payload)

    def update_pump_hours_display(self):
        total_ms = self.pump_hours_base["total_running_ms"] + self.pump_hours_acc_run_ms
        total_min = self.pump_hours_base["total_minutes"] + self.pump_hours_acc_run_ms // 60000
        hours = total_min // 60
        minutes = total_min % 60
        avg_pct = 0
        if total_ms > 0:
            avg_pct = (self.pump_hours_base["sum_percent_ms"] + self.pump_hours_acc_sum_pct_ms) / total_ms * 100
        self.pump_hours_display = f"{hours:05d}.{minutes:02d} {avg_pct:.0f}%"
        self._web_set_pump_hours()
        self.info_label.setText(f'<html><body><p>{self.targets}</p><p>Профиль: {_last_preset_name}</p><p>{self.link_status}</p></body></html>')
        self._web_set_info(targets=self.targets, profile=_last_preset_name, link=self.link_status)

    # ── Лог-окно ──────────────────────────────────────────────────────
    def _open_log_window(self):
        """Открыть/закрыть окно логов."""
        if self._log_window.isVisible():
            self._log_window.hide()
        else:
            # Центрировать рядом с главным окном
            self._log_window.move(
                self.x() + self.width() + 12,
                self.y()
            )
            self._log_window.show()
            self._log_window.raise_()

    def _on_log_new_line(self, _line: str):
        """Обновить счётчик на кнопке при каждом новом лог-сообщении."""
        if not self._log_window.isVisible():
            self._update_log_btn()

    def _update_log_btn(self):
        """Обновить текст ссылки логов с количеством непрочитанных строк."""
        global _log_unread
        try:
            with _log_lock:
                n = _log_unread
            if n > 0:
                label = f"ЛОГИ  {n}" if n <= 999 else "ЛОГИ  999+"
                color = "#f0d060"
            else:
                label = "ЛОГИ"
                color = "rgba(202,195,216,180)"
            self.btn_log.setText(label)
            self.btn_log.setIcon(QIcon(_icon_pixmap("terminal", size=14, color=color)))
            css = (
                "QPushButton {"
                "  text-align: left; padding: 0 12px;"
                "  font-size: 8pt; font-weight: 700; letter-spacing: 2.5px;"
                "  color: __COLOR__;"
                "  background: transparent; border: none;"
                "}"
                "QPushButton:hover { color: #ffffff; }"
            ).replace("__COLOR__", color)
            self.btn_log.setStyleSheet(css)
        except Exception:
            pass
    # ──────────────────────────────────────────────────────────────────

    def _process_events_for(self, duration_sec: float):
        deadline = time.monotonic() + max(0.0, float(duration_sec))
        while time.monotonic() < deadline:
            try:
                QApplication.processEvents()
            except Exception:
                pass
            time.sleep(0.01)

    def _join_thread_with_events(self, thread_obj, timeout_sec: float):
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        while getattr(thread_obj, 'is_alive', lambda: False)() and time.monotonic() < deadline:
            try:
                QApplication.processEvents()
            except Exception:
                pass
            try:
                thread_obj.join(timeout=0.04)
            except Exception:
                break

    def _wait_process_with_events(self, proc, timeout_sec: float):
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        while time.monotonic() < deadline:
            try:
                if proc.poll() is not None:
                    return
            except Exception:
                return
            try:
                QApplication.processEvents()
            except Exception:
                pass
            time.sleep(0.04)

    def _perform_graceful_close(self):
        # При обычном закрытии — STOP; при системном выключении и включённом флаге — ПРОДУВКА
        if getattr(self, '_shutdown_purge_initiated', False) and getattr(self, 'purge_on_shutdown_enabled', False):
            try:
                # Резервная отправка PG напрямую (основная уже была в _sys_evt)
                self._direct_serial_purge()
            except Exception:
                pass
        else:
            # Best-effort graceful stop to avoid any residual PWM pulses on device
            try:
                # Explicitly command STOP twice so ESP32 applies 0% before link teardown
                self.send_control('SP')
                self._process_events_for(0.2)
                self.send_control('SP')
            except Exception:
                pass

        # Force hours sync BEFORE stopping transport so the frame can actually be delivered
        try:
            self.sync_pump_hours_to_esp(force=True)
            self._process_events_for(0.2)
        except Exception:
            pass

        # Останавливаем UI-таймеры в главном потоке ДО завершения worker-потоков,
        # чтобы избежать обращения к Qt-объектам из чужих потоков при teardown.
        for _t_name in ("timer", "pump_hours_timer", "_autostart_timer",
                        "_auto_return_timer", "_led_debounce_timer"):
            try:
                _t = getattr(self, _t_name, None)
                if _t is not None:
                    _t.stop()
            except Exception:
                pass

        if self._transport_thread:
            t = self._transport_thread
            self._transport_thread = None
            try:
                t.stop()
            except Exception:
                pass
            try:
                t.emitter.signal.disconnect()
            except Exception:
                pass
            self._join_thread_with_events(t, 5)
            del t

        # Stop console reporter
        try:
            if hasattr(self, '_console_reporter') and self._console_reporter:
                self._console_reporter.stop()
                self._join_thread_with_events(self._console_reporter, 2)
        except Exception:
            pass

        if hasattr(self, '_lhm_proc') and self._lhm_proc:
            try:
                self._lhm_proc.terminate()
                self._wait_process_with_events(self._lhm_proc, 5)
            except Exception:
                pass
        # Закрываем DLL-режим (если был открыт Computer напрямую)
        _close_lhm_dll()

    def _begin_graceful_close(self):
        if getattr(self, '_closing_in_progress', False):
            return
        self._closing_in_progress = True
        self._show_lifecycle_shutdown()
        def _finish_close():
            try:
                self._perform_graceful_close()
            finally:
                try:
                    self.tray_icon.hide()
                except Exception:
                    pass
                self._allow_close = True
                self.close()
        QTimer.singleShot(260, _finish_close)

    def closeEvent(self, event):
        if getattr(self, '_allow_close', False):
            event.accept()
            return
        event.ignore()
        self._begin_graceful_close()

if __name__ == "__main__":
    # CPU temperature требует прав администратора (LHM kernel driver)
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            params = ' '.join(f'"{a}"' for a in sys.argv)
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            sys.exit(0)
    except Exception:
        pass
    # Оптимизация запуска Qt/WebEngine — до создания QApplication
    try:
        os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    _install_log_capture()
    app = QApplication([])
    app.setWindowIcon(QIcon())
    try:
        apply_app_theme(app)
    except Exception:
        pass
    win = MainWindow()
    win.show()
    app.exec()
