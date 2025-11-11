# Tools: Fan Calibration Helpers

This folder contains small helpers to trigger the firmware's fan RPM auto-calibration without doing it at boot.

- calibrate_fans.py (CLI)
  - USB: `python tools/calibrate_fans.py --usb COM3`
  - BLE: `python tools/calibrate_fans.py --ble`
  - AUTO: `python tools/calibrate_fans.py --auto`
  - Requires `pyserial` for USB and `bleak` for BLE.

- calibrate_gui.py (PySide6 GUI)
  - Simple window for the "Калибровка оборотов" button.
  - Requires `PySide6` and `pyserial` (and `bleak` if using BLE).

- calibrate.ps1 (PowerShell)
  - Quick USB trigger: `pwsh -File tools/calibrate.ps1 -Port COM3`

Firmware expects:
- USB trigger: send two bytes `VC` over UART0 (115200 bps)
- BLE trigger: write any data to characteristic UUID 0xFFE8 of service 0xFFE0 (device name PROEKT1)
