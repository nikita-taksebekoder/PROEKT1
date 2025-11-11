import os
import sys
import threading
import time
import queue
import glob
import csv
import struct
import json
import math
import subprocess
import psutil
from typing import Optional, Union, Tuple, Any, cast
import asyncio
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QMessageBox, QDialog, QSpinBox, QSlider, QTableWidget, QTableWidgetItem, QRadioButton, QButtonGroup, QInputDialog, QLineEdit, QCheckBox, QSystemTrayIcon, QMenu, QGroupBox, QColorDialog, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPointF, QRectF
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property, QSize
from PySide6.QtGui import QIcon
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPixmap, QPainterPath, QImage
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPointF, QRectF, QEvent

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
except ImportError:
    pyserial = None  # type: ignore[assignment]
    SERIAL_AVAILABLE = False

# Глобальные переменные
tx_cmd_queue = queue.Queue()
global_pump_hours = None
_rpm_lock = threading.Lock()
_rpm1 = 0
_rpm2 = 0
_water_lock = threading.Lock()
_water_temp = "--"
_water_last_ts = 0.0
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

def _delete_logs_in_dir(dir_path: str) -> int:
    if not os.path.isdir(dir_path): return 0
    patterns = [
        os.path.join(dir_path, LHM_LOG_PREFIX + "*"),
        os.path.join(dir_path, LHM_LOG_PREFIX + "*.csv"),
    ]
    removed = 0; seen = set()
    for pat in patterns:
        for path in glob.glob(pat):
            if not os.path.isfile(path): continue
            if path in seen: continue
            try:
                os.remove(path); removed += 1; seen.add(path)
            except PermissionError: pass
            except Exception: pass
    return removed

def cleanup_old_logs(max_passes=6, sleep_between=0.25):
    for _ in range(max_passes):
        removed = _delete_logs_in_dir(LHM_DIR) + _delete_logs_in_dir(os.getcwd())
        time.sleep(sleep_between)
        if removed == 0: break

PERIODIC_LOG_CLEANUP_INTERVAL_SEC = 3 * 60 * 60
def _periodic_log_cleanup_loop():
    while True:
        try: cleanup_old_logs()
        except Exception: pass
        time.sleep(PERIODIC_LOG_CLEANUP_INTERVAL_SEC)

# Пути
LHM_DIR = os.path.dirname(os.path.dirname(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
LHM_LOG_PREFIX = 'LibreHardwareMonitorLog-'

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
                while not self.stop_flag:
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
                    await asyncio.sleep(1)
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
        self.pending_led: Any = None
        self._requested_hours = False

    def stop(self):
        self.stop_flag = True
        try:
            if self.ser: self.ser.close()
        except Exception: pass

    def open_serial(self):
        if not SERIAL_AVAILABLE:
            self.emitter.signal.emit("USB: библиотека не установлена")
            return False
        port = "COM3"
        if self.ser and getattr(self.ser, "is_open", False) and self.last_port == port:
            return True
        try:
            if self.ser: self.ser.close()
        except Exception: pass
        self.ser = None

        self.emitter.signal.emit(f"USB: Открытие {port}...")
        try:
            # Guard for type checkers
            if not SERIAL_AVAILABLE or pyserial is None:
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
            except Exception: pass
            time.sleep(0.25)
            try:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            except Exception: pass
            self.last_port = port
            self.emitter.signal.emit(f"USB: Подключено ({port})")
            self._requested_hours = False  # will send HRR after connect
            return True
        except Exception as e:
            msg = str(e)
            if "Access is denied" in msg or "PermissionError" in msg:
                self.emitter.signal.emit(f"USB: Порт {port} занят другим приложением.")
            else:
                self.emitter.signal.emit(f"USB: Ошибка порта {port}: {msg}")
            self.ser = None
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

                    # Отправка LED команды
                    if self.pending_led and self.ser and getattr(self.ser, "is_open", False):
                        led_data = self.pending_led
                        if isinstance(led_data, tuple) and len(led_data) == 6:  # custom
                            mode, brightness, r, g, b, custom = led_data
                            data = _build_lx_usb(mode, brightness, r, g, b, custom)
                        elif isinstance(led_data, tuple) and len(led_data) == 5:
                            mode, brightness, r, g, b = led_data
                            data = _build_lx_usb(mode, brightness, r, g, b)
                        else:
                            data = b""
                        try:
                            self.ser.write(data)
                            self.ser.flush()
                            self.pending_led = None
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

            try:
                if self.ser:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None
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

# Функции для LibreHardwareMonitor
def find_latest_log():
    log_files = glob.glob(os.path.join(LHM_DIR, LHM_LOG_PREFIX + '*.csv'))
    if not log_files:
        return None
    latest = max(log_files, key=os.path.getmtime)
    return latest

def read_libre_temps(log_path):
    try:
        with open(log_path, encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
            if len(rows) < 3:
                return '--', '--'
            paths_row = rows[0]
            names_row = rows[1]
            data_row = rows[-1]
            cpu_idx = _pick_cpu_index(paths_row, names_row)
            gpu_idx = _pick_gpu_index(paths_row, names_row)
            def get_temp(idx):
                try:
                    val = data_row[idx]
                    return str(int(float(val)))
                except Exception:
                    return '--'
            cpu = get_temp(cpu_idx) if cpu_idx is not None else '--'
            gpu = get_temp(gpu_idx) if gpu_idx is not None else '--'
            return cpu, gpu
    except Exception:
        return '--', '--'

def _pick_cpu_index(paths_row, names_row):
    for i, (p, n) in enumerate(zip(paths_row, names_row)):
        pl = (p or "").lower()
        nl = (n or "").lower()
        if "/amdcpu/" in pl and "/temperature/" in pl:
            if any(x in nl for x in ["tctl", "tdie", "package", "core"]):
                return i
        if ("/cpu-" in pl or "/cpu/" in pl) and "/temperature/" in pl:
            if any(x in nl for x in ["package", "core", "tctl"]):
                return i
    for i, p in enumerate(paths_row):
        pl = (p or "").lower()
        if "/amdcpu/" in pl and "/temperature/" in pl:
            return i
        if ("/cpu-" in pl or "/cpu/" in pl) and "/temperature/" in pl:
            return i
    return None

def _pick_gpu_index(paths_row, names_row):
    for i, (p, n) in enumerate(zip(paths_row, names_row)):
        pl = (p or "").lower()
        nl = (n or "").lower()
        if ("/gpu-amd/" in pl or "/gpu-nvidia/" in pl) and "/temperature/" in pl:
            if any(x in nl for x in ["hot spot", "hotspot"]):
                return i
        if ("/gpu-" in pl or "/gpu/" in pl) and "/temperature/" in pl:
            if any(x in nl for x in ["hot spot", "hotspot"]):
                return i
    for i, p in enumerate(paths_row):
        pl = (p or "").lower()
        if ("/gpu-amd/" in pl or "/gpu-nvidia/" in pl) and "/temperature/" in pl:
            return i
        if ("/gpu-" in pl or "/gpu/" in pl) and "/temperature/" in pl:
            return i
    return None

def get_current_temps():
    log_path = find_latest_log()
    if log_path:
        return read_libre_temps(log_path)
    return '--', '--'

def start_lhm():
    exe_path = os.path.join(LHM_DIR, 'LibreHardwareMonitor.exe')
    if not os.path.exists(exe_path):
        QMessageBox.warning(None, "Ошибка", f'LibreHardwareMonitor.exe not found at {exe_path}!')
        return None
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            if proc.info['name'] and 'LibreHardwareMonitor' in proc.info['name']:
                return proc
        except Exception:
            pass
    try:
        proc = subprocess.Popen([exe_path], cwd=LHM_DIR)
        return proc
    except Exception as e:
        QMessageBox.warning(None, "Ошибка", f"Ошибка запуска LibreHardwareMonitor: {e}")
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
            painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
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
        except Exception:
            pass
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
        try:
            with open(self.curves_path, "w", encoding="utf-8") as f:
                json.dump({
                    "fan_curve": self.fan_points,
                    "pump_curve": self.pump_points,
                    "source_mode": source_mode,
                    "presets": self.presets,
                    "selected_preset": self.selected_preset,
                    "hyst_fan": int(self.hyst_fan),
                    "hyst_pump": int(self.hyst_pump)
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения: {e}")

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
        self.colors = colors
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
        self.setFixedSize(800, 600)
        self.setMouseTracking(True)
        # Create palette image
        self.palette_image = QImage(800, 600, QImage.Format.Format_RGB32)
        for x in range(800):
            for y in range(600):
                hue = int(360 * x / 800)
                sat = int(255 * (600 - y) / 600)  # saturation from 255 at bottom to 0 at top
                color = QColor.fromHsv(hue, sat, 255)
                self.palette_image.setPixel(x, y, color.rgb())

    def get_color_at_position(self, x, y):
        hue = int(360 * x / self.width()) % 360
        sat = int(255 * (self.height() - y) / self.height())
        return QColor.fromHsv(hue, sat, 255)

    def update_colors(self):
        self.animation_timer.stop()
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
            for i in range(20):
                if len(self.points[i]) == 1:
                    x, y = self.points[i][0]
                    self.points[i].append((x + 40, y + 40))  # add second point
                    self.relative_vectors[i] = (40, 40)
        elif mode == "Моно цвет":
            self.points = [[(self.width() // 2, self.height() // 2)]]  # один круг в центре
        elif mode == "Моно градиентный":
            self.points = [[(self.width() // 4, self.height() // 2)], [(3 * self.width() // 4, self.height() // 2)]]  # два круга
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
            self.points = [[(50 + i * 35, 400)] for i in range(20)]
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
                painter.setFont(QFont("Arial", 10, QFont.Weight.Medium))
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
    def __init__(self, colors, parent=None, points=None, mode="Свободное", profiles=None):
        super().__init__(parent)
        # Secondary window: frameless
        try:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        except Exception:
            pass
        # Transparent background; draw card frame inside
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
        speed_label = QLabel("Скорость перелива (сек):")
        speed_label.setStyleSheet("color: #FFFFFF; font-size: 12pt;")
        top_layout.addWidget(speed_label)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 30)
        self.speed_slider.setValue(5)  # default 5 seconds
        self.speed_slider.setStyleSheet("QSlider::groove:horizontal { background: #555555; height: 4px; } QSlider::handle:horizontal { background: #FFFFFF; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }")
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        top_layout.addWidget(self.speed_slider)
        content_layout.addLayout(top_layout)
        content_layout.addSpacing(20)
        self.color_palette = ColorPalette(self.colors, self.edit_mode_combo)
        self.color_palette.speed = self.speed_slider.value()
        if points:
            self.color_palette.points = points
            self.color_palette.reset_positions()  # apply correct spacing
        else:
            self.color_palette.reset_positions()
        self.color_palette.mode = mode
        self.color_palette.update_mode(mode)
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
        self.color_palette.speed = self.speed_slider.value()
        self.color_palette.update_mode(self.color_palette.mode)
        # Live preview for gradient anim
        self.send_current_led_preview()
        # Persist as current profile
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
            self.speed_slider.setValue(self.color_palette.speed)
            self.color_palette.update_mode(self.color_palette.mode)
            self.edit_mode_combo.setCurrentText(self.color_palette.mode)
            self.color_palette.update()
            # Live preview when profile applied
            self.send_current_led_preview()
            # Also persist as current
            self.save_as_current_profile()

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
                "colors": [c.getRgb() for c in self.color_palette.colors],
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
    def __init__(self, current_transport, autostart, minimized, pump_hours, brightness, parent=None):
        super().__init__(parent)
        # Secondary window: frameless
        try:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        except Exception:
            pass
        # Transparent background; draw card frame inside
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
        # Outer and card
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
        self.keep_led_cb = QCheckBox("Включать подсветку без соединения с ПК")
        try:
            self.keep_led_cb.setChecked(getattr(parent, 'keep_led_on_disconnected', False))
        except Exception:
            self.keep_led_cb.setChecked(False)
        self.keep_led_cb.setStyleSheet("QCheckBox { color: #FFFFFF; font-size: 14pt; } QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #FFFFFF; border-radius: 7px; background-color: #1e1e1e; } QCheckBox::indicator:checked { background-color: #7C4DFF; }")
        content_layout.addWidget(self.keep_led_cb)
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
        self.brightness_slider.setRange(0, 255)
        self.brightness_slider.setValue(self.brightness)
        self.brightness_slider.setStyleSheet("QSlider::groove:horizontal { background: #555555; height: 4px; } QSlider::handle:horizontal { background: #FFFFFF; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }")
        self.brightness_slider.valueChanged.connect(self.update_brightness_value)
        # Вариант А: отправлять только при отпускании ползунка (без промежуточных отправок)
        # Убраны debounce-таймер и отправка по valueChanged; оставляем только sliderReleased.
        # И гарантированная отправка на отпускании ползунка
        self.brightness_slider.sliderReleased.connect(self.on_brightness_changed)
        brightness_layout.addWidget(self.brightness_slider)
        led_layout.addLayout(brightness_layout)
        led_group.setLayout(led_layout)
        content_layout.addWidget(led_group)
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

    # pump hours is always on; no getter needed
    def get_pump_hours(self):
        return True

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
        dialog = LEDCustomDialog(getattr(self.main_window, 'custom_colors', [QColor(0,0,0) for _ in range(20)]), self.main_window, points=profile.get("points"), mode=(mode_val or "Свободное"), profiles=self.led_profiles)
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
            else:
                if self.main_window:
                    self.main_window.send_led_command(4, self.brightness, 0, 0, 0, dialog.colors)
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
        self.brightness = value

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
        self._margin = 4
        self._pill_height = self.height() - 2*self._margin
        self._segment_ratio = 0.60  # width of inner pill vs track
        self._dragging = False
        self._drag_start_x = 0.0
        self._posf = 0.0  # 0.0..1.0, 0=left(Stop), 0.5=mid(Run), 1.0=right(Purge)
        self._state = 0
        self._suppress_emit = False

        # Colors (reference)
        self._track_bg = QColor(240, 243, 247)   # light gray
        self._track_border = QColor(215, 219, 225)
        self._pill_colors = [
            QColor(139, 0, 0),     # пауза (бордовый)
            QColor(0, 138, 0),     # работа (зелёный)
            QColor(0, 61, 138),    # продувка (синий)
        ]
        self._text_color = QColor(255, 255, 255)
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
        return QRectF(self._margin, self._margin, max(200, self.width() - 2*self._margin), self.height() - 2*self._margin)

    def _pill_rect_from_posf(self, tr: QRectF) -> QRectF:
        pill_w = tr.width() * self._segment_ratio
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

        # Background track with border
        p.setPen(QPen(self._track_border, 2))
        p.setBrush(self._track_bg)
        radius = tr.height()/2
        p.drawRoundedRect(tr, radius, radius)

        # Active pill with slight shadow
        pill = self._pill_rect_from_posf(tr)
        shadow = QRectF(pill)
        shadow.translate(0, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(shadow, radius, radius)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._pill_colors[self._state])
        p.drawRoundedRect(pill, radius, radius)

        # Label in the pill
        labels = ["пауза", "работа", "продувка"]
        p.setPen(self._text_color)
        font = QFont()
        # Use explicit point size if provided, else scale from height
        pt = self._text_pt if self._text_pt is not None else int(tr.height() * 0.42)
        font.setPointSize(max(8, pt))
        font.setBold(False)
        p.setFont(font)
        p.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), labels[self._state])

    # Public: match web button metrics
    def setMetrics(self, height_px: int, text_pt: Optional[int] = None):
        try:
            height_px = int(height_px)
        except Exception:
            height_px = 40
        self.setFixedHeight(max(28, height_px))
        self._margin = max(2, int(self.height() * 0.08))
        self._text_pt = int(text_pt) if text_pt is not None else None
        self.update()

    def mousePressEvent(self, e):  # type: ignore[override]
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._anim.stop()
        self._drag_start_x = e.position().x()

    def mouseMoveEvent(self, e):  # type: ignore[override]
        if not self._dragging:
            return
        tr = self._track_rect()
        self.set_posf(self._posf_from_x(tr, e.position().x()))

    def mouseReleaseEvent(self, e):  # type: ignore[override]
        if not self._dragging:
            return
        self._dragging = False
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

    def setState(self, st: int, animated: bool = True, external: bool = False):
        self._suppress_emit = external  # suppress echo back if external
        st = max(0, min(2, int(st)))
        self._state = st
        target = [0.0, 0.5, 1.0][st]
        if animated:
            self._animate_to_posf(target)
        else:
            self.set_posf(target)
        if not self._suppress_emit:
            self.stateChanged.emit(self._state, False)
        self._suppress_emit = False

    def state(self) -> int:
        return self._state


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.purge_active = False
        self.current_mode = 0
        self.current_r = 255
        self.current_g = 0
        self.current_b = 0
        self.current_custom_colors = None
        self.setWindowTitle("PROEKT1 — Мониторинг температур")
        self.setWindowIcon(QIcon())
        self.setMinimumSize(500, 700)
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
        cleanup_old_logs()
        threading.Thread(target=_periodic_log_cleanup_loop, daemon=True).start()
        # Timer to auto-return switch to STOP after manual PURGE (non-test)
        self._auto_return_timer = QTimer(self)
        self._auto_return_timer.setSingleShot(True)
        self._auto_return_timer.timeout.connect(self._on_auto_return_timer)
        central = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(0)
        central.setStyleSheet("background-color: #1e1e1e;")
        header = QLabel("Температуры")
        header.setStyleSheet("font-size: 32pt; color: #FFFFFF;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header)
        # Temps row: CPU | GPU | Вода
        temp_row = QHBoxLayout()
        temp_row.setSpacing(10)
        self.cpu_label = QLabel("CPU: -- °C")
        self.cpu_label.setStyleSheet("font-size: 24pt; color: #FFFFFF; border: 2px solid #555555; border-radius: 8px; padding: 8px;")
        self.cpu_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        temp_row.addWidget(self.cpu_label)
        self.gpu_label = QLabel("GPU: -- °C")
        self.gpu_label.setStyleSheet("font-size: 24pt; color: #FFFFFF; border: 2px solid #555555; border-radius: 8px; padding: 8px;")
        self.gpu_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        temp_row.addWidget(self.gpu_label)
        self.water_label = QLabel("Вода: -- °C")
        self.water_label.setStyleSheet("font-size: 24pt; color: #FFFFFF; border: 2px solid #555555; border-radius: 8px; padding: 8px;")
        self.water_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        temp_row.addWidget(self.water_label)
        main_layout.addLayout(temp_row)
        main_layout.addSpacing(40)
        rpm_row = QHBoxLayout()
        rpm_row.setSpacing(10)
        fan1_box = QVBoxLayout()
        self.fan1_val = QLabel('<html><body style="position:relative;"><p style="position:absolute; top:5px; left:5px; font-size:8pt; color:#FFFFFF;">Вентилятор 1</p><p style="font-size:20pt; color:#FFFFFF;">--</p></body></html>')
        self.fan1_val.setStyleSheet("border: 2px solid #555555; border-radius: 8px; padding: 8px;")
        self.fan1_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fan1_box.addWidget(self.fan1_val)
        rpm_row.addLayout(fan1_box)
        fan2_box = QVBoxLayout()
        self.fan2_val = QLabel('<html><body style="position:relative;"><p style="position:absolute; top:5px; left:5px; font-size:8pt; color:#FFFFFF;">Вентилятор 2</p><p style="font-size:20pt; color:#FFFFFF;">--</p></body></html>')
        self.fan2_val.setStyleSheet("border: 2px solid #555555; border-radius: 8px; padding: 8px;")
        self.fan2_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fan2_box.addWidget(self.fan2_val)
        rpm_row.addLayout(fan2_box)
        main_layout.addLayout(rpm_row)
        main_layout.addSpacing(40)
        self.info_label = QLabel("Цели: --\nПрофиль: --\nСвязь: --")
        self.info_label.setStyleSheet("font-size: 13pt; color: #CCCCCC;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.info_label)
        main_layout.addSpacing(40)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_curve = QPushButton("настроить обороты")
        btn_curve.setStyleSheet("QPushButton { font-size: 14pt; color: #FFFFFF; background-color: #7C4DFF; border-radius: 8px; padding: 0 10px; height: 40px; } QPushButton:hover { background-color: #8C5FFF; }")
        btn_curve.clicked.connect(self.show_curve_dialog)
        btn_row.addWidget(btn_curve)
        btn_settings = QPushButton("настройки")
        btn_settings.setText("⚙")
        btn_settings.setStyleSheet("QPushButton { font-size: 16pt; color: #FFFFFF; background-color: #444444; border-radius: 8px; padding: 0; height: 40px; width: 40px; } QPushButton:hover { background-color: #545454; }")
        btn_settings.setFixedSize(40, 40)
        btn_settings.clicked.connect(self.show_settings_dialog)
        btn_row.addWidget(btn_settings)
        self.transport_combo = QComboBox()
        self.transport_combo.addItems(["BLE", "USB"])
        self.transport_combo.setCurrentText("BLE")
        self.transport_combo.setStyleSheet("QComboBox { font-size: 13pt; color: #FFFFFF; background-color: #111111; border-radius: 6px; padding: 6px 18px; height: 40px; } QComboBox::drop-down { border: none; } QComboBox::down-arrow { border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 3px solid #FFFFFF; margin-right: 6px; } QComboBox:hover { background-color: #323232; } QComboBox::item { color: #FFFFFF; background-color: #171717; } QComboBox::item:selected { background-color: #7C4DFF; color: #FFFFFF; }")
        self.transport_combo.currentTextChanged.connect(self.on_transport_mode_changed)
        # btn_row.addWidget(self.transport_combo)  # Hidden, moved to settings
        # Tri-state switch (стоп | работа | продувка)
        self.tri_switch = TriStateSwitch()
        self.tri_switch.stateChanged.connect(self.on_switch_state_changed)
        # Изначально система в "работе"
        self.tri_switch.setState(1, animated=False, external=True)
        # Привести высоту и кегль к метрикам кнопок сайта (можно скорректировать при необходимости)
        self.tri_switch.setMetrics(height_px=40, text_pt=14)
        btn_row.addWidget(self.tri_switch)
        # Начальное состояние системы
        self.system_running = True  # assume normal operation initially
        main_layout.addLayout(btn_row)
        central.setLayout(main_layout)
        self.setCentralWidget(central)
        # Пути к файлам конфигурации/кривым и начальная загрузка до старта транспорта,
        # чтобы избежать ранней переотправки дефолтного красного профиля
        self.curves_path = os.path.join(os.path.dirname(__file__), "curves.json")
        self.config_path = os.path.join(os.path.dirname(__file__), "config.json")
        self.autostart = False
        self.minimized = False
        self.keep_led_on_disconnected = False
        self.pump_hours = True
        self.led_custom_colors = [QColor(0, 0, 0) for _ in range(20)]
        self.led_config_loaded = False
        self.load_app_config()

        self.transport = "BLE"
        self._transport_thread = None
        self.on_transport_mode_changed("BLE")  # Запуск по умолчанию после загрузки конфигурации

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
        # Connection grace period
        self.connection_start_time = None
        try:
            with open(self.curves_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.fan_points = data.get("fan_curve", self.fan_points)
                self.pump_points = data.get("pump_curve", self.pump_points)
                self.source_mode = data.get("source_mode", self.source_mode)
                self.presets = data.get("presets", self.presets)
                selected_preset = data.get("selected_preset", "Стандарт")
                global _last_preset_name
                _last_preset_name = selected_preset
        except Exception:
            pass
        # Ensure window visible (in case previous geometry was off-screen)
        QTimer.singleShot(200, self.ensure_visible)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger or reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_from_tray()

    def restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.ensure_visible()

    def ensure_visible(self):
        try:
            screen = QApplication.primaryScreen().availableGeometry()
            g = self.geometry()
            if not screen.intersects(g) or g.width() == 0 or g.height() == 0:
                self.resize(900, 700)
                center = screen.center()
                self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
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

    def update_ui(self):
        target_fan = 0.0
        cpu, gpu = get_current_temps()
        self.cpu_label.setText(f"CPU: {cpu} °C")
        self.gpu_label.setText(f"GPU: {gpu} °C")
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
        self.water_label.setText(f"Вода: {water} °C")
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
            target_fan = self.interpolate_curve(self.fan_points, temp)
            target_pump = self.interpolate_curve(self.pump_points, temp, is_pump=True)
            self.targets = f"Цели: 🌀 {int(round(target_fan))}% 💧 {int(round(target_pump))}% (ориентир: {src})"
            # Pump hours accumulation
            if target_pump > 30:
                pct = target_pump / 100
                self.pump_hours_acc_run_ms += 1000
                self.pump_hours_acc_sum_pct_ms += pct * 1000
        else:
            self.targets = "Цели: 🌀 --% 💧 --%"
        self.info_label.setText(f'<html><body><p>{self.targets}</p><p>Профиль: {_last_preset_name}</p><p>{self.link_status}</p></body></html>')
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
            fan1_should_alarm = work_mode and (f1_flag or (target_fan > 0 and self.is_fan_alarm(target_fan, _rpm1)))
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
            fan2_should_alarm = work_mode and (f2_flag or (target_fan > 0 and self.is_fan_alarm(target_fan, _rpm2)))
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
            # Border blinking
            border_color1 = "#ffaf56" if work_mode and fan1_message != "" and (int(time.time()) % 4 < 2) else "#555555"
            border_color2 = "#ffaf56" if work_mode and fan2_message != "" and (int(time.time()) % 4 < 2) else "#555555"
            self.fan1_val.setStyleSheet(f"border: 2px solid {border_color1}; border-radius: 8px; padding: 8px;")
            self.fan2_val.setStyleSheet(f"border: 2px solid {border_color2}; border-radius: 8px; padding: 8px;")
            self.fan1_val.setText('<html><body style="position:relative;"><p style="position:absolute; top:5px; left:5px; font-size:8pt; color:#FFFFFF;">Вент. 1 : ' + fan1_message + '</p><p style="font-size:20pt; color:#FFFFFF;">' + fan1_icon + '</p></body></html>')
            self.fan2_val.setText('<html><body style="position:relative;"><p style="position:absolute; top:5px; left:5px; font-size:8pt; color:#FFFFFF;">Вент. 2 : ' + fan2_message + '</p><p style="font-size:20pt; color:#FFFFFF;">' + fan2_icon + '</p></body></html>')
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
                self.brightness = data.get("brightness", 255)
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
                        self.current_custom_colors = grad_bytes
                        self.current_r = self.current_g = self.current_b = 0
                        self.send_led_command(5, int(self.brightness), 0, 0, 0, grad_bytes)
                    elif isinstance(prof_mode, str) and prof_mode == "Моно цвет" and len(self.custom_colors) >= 1:
                        # Моно цвет: отправляем solid (mode=0) по первому цвету палитры
                        c0 = self.custom_colors[0]
                        self.current_mode = 0
                        self.current_custom_colors = None
                        self.current_r, self.current_g, self.current_b = c0.red(), c0.green(), c0.blue()
                        self.send_led_command(0, int(self.brightness), self.current_r, self.current_g, self.current_b)
                    else:
                        # Любой другой режим — трактуем как статичную кастом палитру (в т.ч. "Свободное", "Свободное градиентное", "Зависимое градиентное")
                        self.current_mode = 4
                        self.current_custom_colors = self.custom_colors
                        self.current_r = self.current_g = self.current_b = 0
                        self.send_led_command(4, int(self.brightness), 0, 0, 0, self.custom_colors)
                # Флаг загрузки конфигурации для защиты от ранней переотправки
                self.led_config_loaded = True
        except Exception:
            self.brightness = 255

    def save_app_config(self):
        try:
            # Обновляем профиль "Текущий" из текущей палитры, если она задана
            if not hasattr(self, 'led_profiles') or self.led_profiles is None:
                self.led_profiles = {}
            palette = getattr(self, 'current_custom_colors', None)
            # Если текущий режим градиент-анимация (mode=5) — сохраняем старт/конец как colors[0], colors[-1] + speed
            if getattr(self, 'current_mode', 0) == 5 and isinstance(palette, (bytes, bytearray)) and len(palette) == 7:
                self.led_profiles["Текущий"] = {
                    "mode": "Моно градиентный",
                    "colors": [
                        (palette[0], palette[1], palette[2]),
                        (palette[3], palette[4], palette[5])
                    ],
                    "speed": palette[6],
                }
            elif getattr(self, 'current_mode', 0) == 0 and isinstance(palette, list) and len(palette) >= 1:
                # Моно цвет: сохраняем только первый цвет
                c0 = palette[0]
                self.led_profiles["Текущий"] = {
                    "mode": "Моно цвет",
                    "colors": [(c0.red(), c0.green(), c0.blue())]
                }
            else:
                if palette is not None:
                    try:
                        # palette здесь список QColor
                        self.led_profiles.setdefault("Текущий", {})
                        self.led_profiles["Текущий"]["mode"] = self.led_profiles["Текущий"].get("mode", "Свободное")
                        self.led_profiles["Текущий"]["colors"] = [(c.red(), c.green(), c.blue()) for c in palette]  # type: ignore
                    except Exception:
                        pass
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "autostart": self.autostart,
                    "minimized": self.minimized,
                    "keep_led_on_disconnected": self.keep_led_on_disconnected,
                    "brightness": self.brightness,
                    "led_profiles": self.led_profiles
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения config: {e}")

    def on_transport_mode_changed(self, mode):
        if self._transport_thread:
            self._transport_thread.stop()
            self._transport_thread = None
        if mode == "BLE":
            self._transport_thread = BLETempSender(get_current_temps, None)
            self._transport_thread.emitter.signal.connect(self.update_link_status)
            self._transport_thread.start()
        elif mode == "USB":
            self._transport_thread = USBTempSender(get_current_temps, None)
            self._transport_thread.emitter.signal.connect(self.update_link_status)
            self._transport_thread.start()

    def show_curve_dialog(self):
        dlg = FanPumpCurveDialog(self)
        dlg.exec()
        self.fan_points = [p[:] for p in self.presets[dlg.selected_preset]["fan_curve"]]
        self.pump_points = [p[:] for p in self.presets[dlg.selected_preset]["pump_curve"]]
        self.source_mode = dlg.source_mode

    def show_settings_dialog(self):
        dialog = SettingsDialog(self.transport_combo.currentText(), self.autostart, self.minimized, True, self.brightness, self)
        total_min = self.pump_hours_base["total_minutes"] + self.pump_hours_acc_run_ms // 60000
        hours = total_min / 60
        total_ms = self.pump_hours_base["total_running_ms"] + self.pump_hours_acc_run_ms
        avg_pct = 0
        if total_ms > 0:
            avg_pct = (self.pump_hours_base["sum_percent_ms"] + self.pump_hours_acc_sum_pct_ms) / total_ms * 100
        dialog.update_pump_hours_display(hours, avg_pct)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_transport = dialog.get_transport()
            self.transport = new_transport
            if new_transport != self.transport_combo.currentText():
                self.transport_combo.setCurrentText(new_transport)
                self.on_transport_mode_changed(new_transport)
            self.autostart = dialog.get_autostart()
            self.minimized = dialog.get_minimized()
            self.brightness = dialog.brightness
            # keep LED on when disconnected flag
            try:
                self.keep_led_on_disconnected = dialog.get_keep_led()
                self.send_keep_led_flag()
            except Exception:
                pass
            self.save_app_config()

    def update_link_status(self, status):
        parts = status.split(": ", 1)
        if len(parts) == 2:
            transport, rest = parts
            self.link_status = f"Связь: [{transport}] {rest}"
        else:
            self.link_status = f"Связь: {status}"
        # Set connection start time for grace period
        if "Подключено" in status:
            self.connection_start_time = time.time()
            # После переподключения восстанавливаем последний LED-профиль и яркость,
            # только если конфигурация уже загружена (во избежание дефолтного красного)
            try:
                if getattr(self, 'led_config_loaded', False):
                    QTimer.singleShot(200, self.resend_current_led_profile)
                # Переотправить флаг keep_led если включен
                QTimer.singleShot(400, self.send_keep_led_flag)
                # Гарантированно запускать систему в режим "работа" на каждом подключении
                # (даже если в прошлой сессии был "стоп"). Дублируем через 1.5с для надёжности.
                QTimer.singleShot(100, lambda: self.send_control('ST'))
                QTimer.singleShot(1600, lambda: self.send_control('ST'))
            except Exception:
                pass

    def resend_current_led_profile(self):
        """Переотправить текущий LED-профиль после подключения BLE/USB.
        Восстанавливает режим, цвета/градиент и яркость на устройстве.
        """
        try:
            if not getattr(self, 'led_config_loaded', False):
                print("DEBUG: Skip resend_current_led_profile (config not loaded yet)")
                return
            # Если есть сохранённая палитра, приоритетно отправим её (custom mode)
            palette = getattr(self, 'current_custom_colors', None)
            if palette is not None:
                try:
                    print("DEBUG: Resend custom palette, len=", len(palette))
                except Exception:
                    pass
                self.send_led_command(4, int(self.brightness), 0, 0, 0, palette)
            else:
                print(f"DEBUG: Resend non-custom mode={self.current_mode} rgb=({self.current_r},{self.current_g},{self.current_b}) br={self.brightness}")
                self.send_led_command(self.current_mode, int(self.brightness), self.current_r, self.current_g, self.current_b, self.current_custom_colors)
        except Exception as e:
            print(f"LED restore error: {e}")

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
        # BLE vs USB
        if self.transport == "BLE":
            tx_cmd_queue.put(("ctrl", payload))
        else:
            tx_cmd_queue.put(("ctrl", payload))

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

    def send_led_command(self, mode, brightness, r, g, b, custom_colors=None):
        # Update current state
        self.current_mode = mode
        self.current_r = r
        self.current_g = g
        self.current_b = b
        self.current_custom_colors = custom_colors
        if mode == 4:  # custom
            if custom_colors is not None:
                # Не масштабируем цвета — яркость передаём отдельно
                custom_bytes = b''.join(struct.pack('BBB', c.red(), c.green(), c.blue()) for c in custom_colors)
                if self.transport == "BLE":
                    payload = b'LX' + struct.pack('<BBB', 1, 4, int(brightness)) + custom_bytes
                    tx_cmd_queue.put(("led", payload))
                elif self.transport == "USB":
                    if hasattr(self, '_transport_thread') and self._transport_thread:
                        thread_any = cast(Any, self._transport_thread)
                        thread_any.pending_led = (4, int(brightness), 0, 0, 0, custom_bytes)
        elif mode == 5:  # gradient anim
            if custom_colors is not None:
                if self.transport == "BLE":
                    payload = b'LX' + struct.pack('<BBB', 1, 5, brightness) + custom_colors
                    tx_cmd_queue.put(("led", payload))
                elif self.transport == "USB":
                    if hasattr(self, '_transport_thread') and self._transport_thread:
                        thread_any = cast(Any, self._transport_thread)
                        thread_any.pending_led = (5, brightness, 0, 0, 0, custom_colors)
        else:
            if self.transport == "BLE":
                payload = b'LX' + struct.pack('<BBBBBB', 1, mode, brightness, r, g, b)
                tx_cmd_queue.put(("led", payload))
            elif self.transport == "USB":
                if hasattr(self, '_transport_thread') and self._transport_thread:
                    thread_any = cast(Any, self._transport_thread)
                    thread_any.pending_led = (mode, brightness, r, g, b)

    def send_led_brightness_only(self, brightness: int):
        """Отправка только яркости (без изменения текущего режима/цветов/массивов).
        Работает одинаково для BLE и USB через общую очередь команд.
        """
        # Для надёжности переотправляем полный пакет текущего режима с новой яркостью,
        # чтобы прошивка гарантированно применила изменение без дополнительных состояний
        try:
            bval = int(brightness)
            mode = int(getattr(self, 'current_mode', 0))
            cur = getattr(self, 'current_custom_colors', None)
            if mode == 5 and isinstance(cur, (bytes, bytearray)) and len(cur) == 7:
                # Градиент-анимация: 'LX'<1><5><b> + 7 байт
                payload = b'LX' + struct.pack('<BBB', 1, 5, bval) + cur
                tx_cmd_queue.put(("led", payload))
                return
            if mode == 4 and isinstance(cur, list) and len(cur) > 0:
                # Кастом: 'LX'<1><4><b> + 20*RGB
                custom_bytes = b''.join(struct.pack('BBB', c.red(), c.green(), c.blue()) for c in cur)
                payload = b'LX' + struct.pack('<BBB', 1, 4, bval) + custom_bytes
                tx_cmd_queue.put(("led", payload))
                return
            if mode == 0:
                # Солид
                r = int(getattr(self, 'current_r', 255))
                g = int(getattr(self, 'current_g', 0))
                b = int(getattr(self, 'current_b', 0))
                payload = b'LX' + struct.pack('<BBBBBB', 1, 0, bval, r, g, b)
                tx_cmd_queue.put(("led", payload))
                return
            # Фолбэк: brightness-only (поддерживается прошивкой)
            payload = b'LX' + struct.pack('<BBB', 1, mode, bval)
            tx_cmd_queue.put(("led", payload))
        except Exception:
            # Последний шанс: brightness-only
            try:
                payload = b'LX' + struct.pack('<BBB', 1, 0, int(brightness))
                tx_cmd_queue.put(("led", payload))
            except Exception:
                pass

    def update_pump_hours_display(self):
        total_ms = self.pump_hours_base["total_running_ms"] + self.pump_hours_acc_run_ms
        total_min = self.pump_hours_base["total_minutes"] + self.pump_hours_acc_run_ms // 60000
        hours = total_min // 60
        minutes = total_min % 60
        avg_pct = 0
        if total_ms > 0:
            avg_pct = (self.pump_hours_base["sum_percent_ms"] + self.pump_hours_acc_sum_pct_ms) / total_ms * 100
        self.pump_hours_display = f"{hours:05d}.{minutes:02d} {avg_pct:.0f}%"
        self.info_label.setText(f'<html><body><p>{self.targets}</p><p>Профиль: {_last_preset_name}</p><p>{self.link_status}</p></body></html>')

    def closeEvent(self, event):
        # Best-effort graceful stop to avoid any residual PWM pulses on device
        try:
            # Explicitly command STOP twice with tiny delay so ESP32 applies 0% before link teardown
            self.send_control('SP')
            QApplication.processEvents()
            time.sleep(0.2)
            self.send_control('SP')
        except Exception:
            pass

        # Force hours sync BEFORE stopping transport so the frame can actually be delivered
        try:
            self.sync_pump_hours_to_esp(force=True)
            # Small grace to allow transport threads to transmit
            time.sleep(0.2)
        except Exception:
            pass

        if self._transport_thread:
            self._transport_thread.stop()
            self._transport_thread.join(timeout=5)

        if hasattr(self, '_lhm_proc') and self._lhm_proc:
            try:
                self._lhm_proc.terminate()
                self._lhm_proc.wait(timeout=5)
            except Exception:
                pass

        event.accept()

if __name__ == "__main__":
    app = QApplication([])
    app.setWindowIcon(QIcon())
    win = MainWindow()
    win.show()
    app.exec()
