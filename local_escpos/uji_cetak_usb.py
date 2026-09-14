import usb.core

"""
Deprecated
This file only for USB test, thermal printing testing.
"""

ESC_INIT = b'\x1B\x40'               # Initialize printer
ESC_CENTER = b'\x1B\x61\x01'         # Align center
ESC_BOLD = b'\x1B\x21\x30'           # Bold + double height/width
ESC_FEED = b'\x0A'                   # Line feed
ESC_CUT = b'\x1D\x56\x42\x00'        # Cut paper

data = ESC_INIT + ESC_CENTER + ESC_BOLD + b'POS Pintar by Fathir\n' + ESC_FEED * 3 + ESC_CUT

dev = usb.core.find(idVendor=0x28e9, idProduct=0x0289)
dev.set_configuration()
endpoint = dev[0][(0,0)][0]
dev.write(endpoint.bEndpointAddress, data)

print("[INFO] Data berhasil dikirim ke printer.")