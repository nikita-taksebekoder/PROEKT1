#!/usr/bin/env python3
# Lightweight CLI helper to trigger fan RPM calibration via USB ('VC') or BLE CAL.
# Usage examples:
#   python tools/calibrate_fans.py --usb COM3
#   python tools/calibrate_fans.py --ble
#   python tools/calibrate_fans.py --auto   # try USB first (COM3..COM12), then BLE

import argparse
import sys
import time


def send_usb_vc(port: str, baud: int = 115200, timeout: float = 1.0) -> None:
    try:
        import serial
    except ImportError:
        print("pyserial not installed. Install with: pip install pyserial", file=sys.stderr)
        sys.exit(2)
    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
        # Give a moment for adapter to settle
        time.sleep(0.1)
        ser.write(b"VC")
        ser.flush()
        time.sleep(0.05)
        ser.close()
        print(f"Sent 'VC' over USB to {port}")
    except Exception as e:
        print(f"USB error: {e}", file=sys.stderr)
        sys.exit(1)


BLE_DEV_NAME = "PROEKT1"
BLE_SVC_UUID = 0xFFE0
BLE_CAL_UUID = 0xFFE8


def send_ble_cal() -> None:
    try:
        import asyncio
        from bleak import BleakScanner, BleakClient
    except ImportError:
        print("bleak not installed. Install with: pip install bleak", file=sys.stderr)
        sys.exit(2)

    async def run():
        print("Scanning for BLE device 'PROEKT1'...")
        devices = await BleakScanner.discover(timeout=5.0)
        target = None
        for d in devices:
            if d.name == BLE_DEV_NAME:
                target = d
                break
        if not target:
            print("Device 'PROEKT1' not found. Ensure it is advertising and nearby.", file=sys.stderr)
            sys.exit(3)
        print(f"Connecting to {target.address} ...")
        async with BleakClient(target) as client:
            if not client.is_connected:
                print("BLE connect failed", file=sys.stderr)
                sys.exit(4)
            # Resolve characteristic from 16-bit UUIDs
            cal_uuid = f"0000{BLE_CAL_UUID:04x}-0000-1000-8000-00805f9b34fb"
            print("Writing CAL trigger...")
            await client.write_gatt_char(cal_uuid, b"\x01", response=True)
            print("CAL written successfully")

    import asyncio
    asyncio.run(run())


def try_auto() -> None:
    # Try common COM ports for USB first
    ports = [f"COM{i}" for i in range(3, 21)]
    try:
        import serial
        from serial.tools import list_ports
        pl = [p.device for p in list_ports.comports()]
        if pl:
            ports = pl
    except Exception:
        pass
    for p in ports:
        try:
            send_usb_vc(p)
            return
        except SystemExit:
            # Try next
            continue
        except Exception:
            continue
    # Fallback to BLE
    send_ble_cal()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Trigger fan RPM calibration over USB (VC) or BLE (CAL)")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--usb", help="USB COM port, e.g. COM3")
    g.add_argument("--ble", action="store_true", help="Use BLE (device name PROEKT1)")
    ap.add_argument("--auto", action="store_true", help="Try USB common ports first, then BLE")
    args = ap.parse_args()

    if args.usb:
        send_usb_vc(args.usb)
    elif args.ble:
        send_ble_cal()
    else:
        try_auto()
