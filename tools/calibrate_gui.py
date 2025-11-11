#!/usr/bin/env python3
# Minimal PySide6 GUI with a button "Калибровка оборотов".
# It can send USB 'VC' to a selected COM port or do BLE CAL to device "PROEKT1".

import sys
import time
from typing import List

from PySide6 import QtWidgets, QtCore


def list_serial_ports() -> List[str]:
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return [f"COM{i}" for i in range(3, 21)]


def send_usb_vc(port: str):
    from serial import Serial
    s = Serial(port=port, baudrate=115200, timeout=1.0)
    time.sleep(0.1)
    s.write(b"VC")
    s.flush()
    time.sleep(0.05)
    s.close()


async def send_ble_cal_async():
    from bleak import BleakScanner, BleakClient
    devname = "PROEKT1"
    cal_uuid = "0000ffe8-0000-1000-8000-00805f9b34fb"
    devices = await BleakScanner.discover(timeout=5.0)
    target = next((d for d in devices if d.name == devname), None)
    if not target:
        raise RuntimeError("BLE device PROEKT1 not found")
    async with BleakClient(target) as client:
        if not client.is_connected:
            raise RuntimeError("BLE connect failed")
        await client.write_gatt_char(cal_uuid, b"\x01", response=True)


class CalibWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Настройка кривых — калибровка оборотов")
        self.resize(420, 160)

        self.combo = QtWidgets.QComboBox()
        self.combo.addItems(list_serial_ports())
        self.refresh_btn = QtWidgets.QPushButton("Обновить COM-порты")
        self.usb_btn = QtWidgets.QPushButton("Калибровка оборотов (USB)")
        self.ble_btn = QtWidgets.QPushButton("Калибровка оборотов (BLE)")

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)

        grid = QtWidgets.QGridLayout(self)
        grid.addWidget(QtWidgets.QLabel("USB COM:"), 0, 0)
        grid.addWidget(self.combo, 0, 1)
        grid.addWidget(self.refresh_btn, 0, 2)
        grid.addWidget(self.usb_btn, 1, 0, 1, 3)
        grid.addWidget(self.ble_btn, 2, 0, 1, 3)
        grid.addWidget(self.log, 3, 0, 1, 3)

        self.refresh_btn.clicked.connect(self.on_refresh)
        self.usb_btn.clicked.connect(self.on_usb)
        self.ble_btn.clicked.connect(self.on_ble)

    def on_refresh(self):
        self.combo.clear()
        self.combo.addItems(list_serial_ports())

    def logln(self, msg: str):
        self.log.append(msg)

    def on_usb(self):
        port = self.combo.currentText()
        try:
            self.logln(f"Отправляю 'VC' в {port} ...")
            send_usb_vc(port)
            self.logln("Готово. Смотрите монитор: калибровка 15с и сохранение.")
        except Exception as e:
            self.logln(f"USB ошибка: {e}")

    def on_ble(self):
        self.logln("Поиск BLE 'PROEKT1' ...")
        async def runner():
            try:
                await send_ble_cal_async()
                self.logln("CAL записан (BLE)")
            except Exception as e:
                self.logln(f"BLE ошибка: {e}")
        QtCore.QTimer.singleShot(0, lambda: QtCore.QThreadPool.globalInstance().start(_AsyncTask(runner())))


class _AsyncTask(QtCore.QRunnable):
    def __init__(self, coro):
        super().__init__()
        self.coro = coro

    @QtCore.Slot()
    def run(self):
        import asyncio
        asyncio.run(self.coro)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = CalibWindow()
    w.show()
    sys.exit(app.exec())
