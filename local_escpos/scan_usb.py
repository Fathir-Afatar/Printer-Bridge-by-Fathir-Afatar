import usb.core
import usb.backend.libusb1

backend = usb.backend.libusb1.get_backend()
devices = usb.core.find(find_all=True, backend=backend)

"""
Deprecated
This file only for USB test, scan for printer thermal (ESC/POS).
"""

for dev in devices:
    print(f"[DEBUG] Device: VID={hex(dev.idVendor)}, PID={hex(dev.idProduct)}")

if devices is None:
    print("[ERROR] Tidak ada device USB yang terdeteksi.")