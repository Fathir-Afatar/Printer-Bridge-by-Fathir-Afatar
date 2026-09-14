# Standard Application
import os
import requests
import threading
import sys
from datetime import datetime

# Third-party
import usb.core
import usb.util
import usb.backend.libusb1
import tkinter as tk
from tkinter import messagebox
from flask import Flask, request, jsonify # type: ignore
from dotenv import load_dotenv

app = Flask(__name__) # Flask initialization

# load configuration from .env
load_dotenv()
vendor_id_str = os.getenv("PRINTER_VENDOR_ID")
product_id_str = os.getenv("PRINTER_PRODUCT_ID")
vps_url = os.getenv("VPS_URL")

if not vendor_id_str or not product_id_str:
    raise ValueError("PRINTER_VENDOR_ID or PRINTER_PRODUCT_ID not found in .env")

# if there is no prefix '0x', parse as hex; if not, parse as a usual decimal
# setup USB device
vendor_id = int(vendor_id_str, 16) if vendor_id_str.startswith("0x") else int(vendor_id_str)
product_id = int(product_id_str, 16) if product_id_str.startswith("0x") else int(product_id_str)

backend = usb.backend.libusb1.get_backend()
dev = usb.core.find(idVendor=vendor_id, idProduct=product_id, backend=backend)

ep_out = None
if dev:
    dev.set_configuration()
    cfg = dev.get_active_configuration()
    intf = cfg[(0,0)]
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
    )

def escpos_write(data: bytes, chunk_size: int = 64):
    """
    Sends raw ESC/POS commands or text to the thermal printer in small chunks.

    This function chunks the byte data to prevent buffer overflow on the
    printer hardware. It handles common USB timeout errors specifically to
    provide more descriptive error messages.

    Args:
        data (bytes): The raw byte data or ESC/POS commands to be sent.
        chunk_size (int, optional): The size of each data packet chunk.
            Defaults to 64.
    
    Returns:
        None
    
    Raises:
        ValueError: If the printer connection (`ep_out`) is not established.
        usb.core.USBError: If a USB communication error or timeout occurs.
    """
    if not ep_out:
        raise ValueError("The printer is not connected.")

    try:
        # kirim data dalam potongan kecil
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i+chunk_size]
            ep_out.write(chunk)
    except usb.core.USBError as e:
        if "timed out" in str(e).lower():
            raise usb.core.USBError("Printer not responding (USB timeout)")
        else:
            raise
    
LEBAR_BARIS = 42  # lebar baris thermal

def format_nota_thermal(transaksi_id, pembeli, items, total, status="DRAFT", ongkir=0, tanggal=None, pengaturan=None, voucher=0):
    """
    Format a single item line for thermal receipt printing.

    This function truncates product names to 30 characters, align subtotal 
    to the right, and prints quantity with unit price on the next line.

    Args:
        nama (str): Product name
        harga (int): Unit price of the product
        qty (int): Quantity purchased.
        subtotal (int): Subtotal for the item.
        max_width (int, optional): Maximum line widths. Defaults to LEBAR_BARIS.
    
    Returns
        str: Formatted string representatin the item line.
    """
    tanggal_str = (tanggal or datetime.now()).strftime("%d %B %Y")
    lines = []
    header_lines = [line.strip() for line in pengaturan.get("header", "").splitlines() if line.strip()]
    footer_lines = [line.strip() for line in pengaturan.get("footer", "").splitlines() if line.strip()]

    # Header
    lines.append("=" * LEBAR_BARIS)
    for line in header_lines:
        lines.append(line.center(LEBAR_BARIS))
    lines.append("=" * LEBAR_BARIS)

    # Transaction info
    lines.append(f"Transaksi : #{transaksi_id}")
    lines.append(f"Tanggal   : {tanggal_str}")
    lines.append(f"Pembeli   : {pembeli}")
    lines.append("-" * LEBAR_BARIS)
    lines.append(f"{'Produk':<30} {'Subtotal':>12}")
    lines.append("-" * LEBAR_BARIS)

    # Detail Item
    for item in items:
        nama = item.get("nama_produk") or "Produk"
        jumlah = item["jumlah"]
        harga = item["harga_satuan"]
        subtotal = item["subtotal"]

        if "(isi paket)" in nama:
            continue

        if item.get("is_paket"):
            # tampilkan paket utama
            lines.append(f"{nama[:30]:<30} Rp{subtotal:>10,.0f}")
            lines.append(f"{jumlah} x Rp{harga:,.0f}")
            lines.append(" Isi Paket:")
            for isi in item.get("isi_paket", []):
                lines.append(f"   - {isi['nama_produk']} x{isi['jumlah']}")
        else:
            # produk biasa
            lines.append(f"{nama[:30]:<30} Rp{subtotal:>10,.0f}")
            lines.append(f"{jumlah} x Rp{harga:,.0f}")

        if item.get("diskon"):
            lines.append(f"{'Diskon':30} Rp{item['diskon']:>10,.0f}")
        if item.get("catatan"):
            lines.append(f"Catatan: {item['catatan'][:LEBAR_BARIS-9]}")

    # Ringkasan
    subtotal_val = sum(
        item["subtotal"] for item in items
        if "(isi paket)" not in (item.get("nama_produk") or "").lower()
        )

    lines.append("-" * LEBAR_BARIS)
    lines.append(f"{'Subtotal':<24}{f'Rp {subtotal_val:,.0f}':>18}")

    # Kondisi gabungan
    if ongkir and voucher:
        lines.append(f"{'Ongkir':<24}{f'Rp {ongkir:,.0f}':>18}")
        lines.append(f"{'Voucher':<24}{f'-Rp {voucher:,.0f}':>18}")
        grand_total = (subtotal_val + ongkir) - voucher
    elif ongkir:
        lines.append(f"{'Ongkir':<24}{f'Rp {ongkir:,.0f}':>18}")
        grand_total = subtotal_val + ongkir
    elif voucher:
        lines.append(f"{'Voucher':<24}{f'-Rp {voucher:,.0f}':>18}")
        grand_total = subtotal_val - voucher
    else:
        grand_total = subtotal_val

    lines.append(f"{'Total':<24}{f'Rp {grand_total:,.0f}':>18}")
    lines.append("=" * LEBAR_BARIS)

    # Footer
    for line in footer_lines:
        lines.append(line.center(LEBAR_BARIS))
    lines.append("=" * LEBAR_BARIS)

    return "\n".join(lines)

def cetak_nota(transaksi_id=None):
    """
    Fetches transaction data from a VPS API, formats it, and prints the thermal receipt.

    The function falls back to a GUI text entry if no ID is passed, fetches JSON 
    data from a remote API, generates a formatted layout, saves a local text 
    preview, and streams the document line-by-line to the USB thermal printer 
    before executing a paper cut command.

    Args:
        transaksi_id (str, optional): The unique identifier for the transaction. 
            Defaults to None.

    Returns:
        dict: A status dictionary containing `{"status": "ok"}` upon success, 
            or `{"status": "error", "message": "..."}` if an exception occurs.
    """
    try:
        if transaksi_id is None:
            transaksi_id = entry_id.get()

        resp = requests.get(f"{vps_url}/api/nota/{transaksi_id}/", timeout=10)
        nota = resp.json()
        print("URL dipanggil:", f"{vps_url}/api/nota/{transaksi_id}/")
        print("JSON diterima:", nota)

        items = nota['items']
        nota_str = format_nota_thermal(
            transaksi_id=nota['transaksi_id'],
            pembeli=nota['pembeli'],
            items=items,
            total=nota['total'],
            ongkir=nota.get('ongkir', 0),
            tanggal=datetime.strptime(nota['tanggal'], "%d %B %Y %H:%M"),
            pengaturan=nota['pengaturan'],
            voucher=nota.get('voucher', 0)
        )

        # Simpan preview
        with open("nota_preview.txt", "w", encoding="utf-8") as f:
            f.write(nota_str)

        # Kirim nota baris demi baris ke printer
        for line in nota_str.splitlines():
            escpos_write((line + "\n").encode("utf-8"))

        # Cut command
        escpos_write(b"\x1DVA0")

        if transaksi_id == entry_id.get():
            messagebox.showinfo("Success", "The receipt was successfully printed!")

        return {"status": "ok"}
    except Exception as e:
        if transaksi_id == entry_id.get():
            messagebox.showerror("Error", f"Print failed: {e}")
        return {"status": "error", "message": str(e)}

def refresh_printer():
    """Attempts to reconnect and reinitialize the USB thermal printer hardware configuration.

    This function updates the global `dev` and `ep_out` components by searching 
    for the specific vendor and product IDs. It alerts the user via Tkinter popups 
    depending on whether the connection succeeds or fails.

    Returns:
        None
    """
    try:
        global dev, ep_out
        backend = usb.backend.libusb1.get_backend()
        dev = usb.core.find(idVendor=vendor_id, idProduct=product_id, backend=backend)

        if dev is None:
            messagebox.showwarning("Printer", "Printer not found. Turn on the printer and try again.")
            return
        
        dev.set_configuration()
        cfg = dev.get_active_configuration()
        intf = cfg[(0,0)]
        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        print("Endpoint OUT address:", ep_out.bEndpointAddress if ep_out else None)

        messagebox.showinfo("Printer", "The printer successfully reconnected!")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to refresh printer: {e}")

# Flask endpoint
@app.route("/print", methods=["POST"])
def print_receipt():
    """Flask API endpoint to trigger receipt printing from an HTTP POST request.

    Expects a JSON payload containing `transaksi_id`. If the inner printing process 
    fails, it returns an HTTP 500 server error status code.

    Returns:
        tuple: A JSON response object paired with an HTTP status code (200 or 500).
    """
    data = request.json
    transaksi_id = data.get("transaksi_id")
    result = cetak_nota(transaksi_id)
    if result and result.get("status") == "error":
        return jsonify(result), 500
    return jsonify({"status": "ok", "message": "Nota berhasil dicetak"})

def run_flask():
    """Starts the Flask web development server to listen for remote print requests.

    Configured to bind to all available network interfaces (`0.0.0.0`) on port 5000.

    Returns:
        None
    """
    app.run(host="0.0.0.0", port=5000)

def get_license_path(filename="LICENSE"):
    """
    Determines the absolute path to the license file based on execution environment.

    This function checks wheter the script is running as a compiled standalone
    executable (e.g., packaged with PyInstaller) or as a standard Python script.
    It dynamically resolves the directory path accordingly to locate the file.

    Args:
        filename (str, optional): the name of the license file. Default to "LICENSE".
    
    Returns:
        str: The full absolute path to the specified license file. 
    """
    if getattr(sys, "frozen", False):
        # Jika dijalankan sebagai executable (.exe)
        base_path = os.path.dirname(sys.executable)
    else:
    # Jika dijalankan sebagai script .py biasa
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, filename)

def show_license():
    """
    Displays the content of the license file in a GUI info message box.

    This function attemps to find and read the license text file. If successful,
    it opens a Tkinter info popun showing the full license terms. If the file is
    missing, it catches the exception and displays an error messagebox instead.

    Returns:
        None
    """
    license_path = get_license_path("LICENSE")

    try:
        with open(license_path, "r", encoding="utf-8") as file:
            license_text = file.read()
        messagebox.showinfo("MIT License", license_text)
    except FileNotFoundError:
        messagebox.showerror(
        "License Error",
        f"File LICENSE not found:\n{license_path}",
    )
    except Exception as e:
        messagebox.showerror(
            "Error", f"Failed to open license file:\n{str(e)}"
    )

# Simple GUI
root = tk.Tk()
root.title("Printer Bridge by Fathir Afatar")
root.geometry("700x500")

title = tk.Label(root, text="Printer Bridge by Fathir Afatar", font=("Arial", 20, "bold"))
title.pack(pady=20)

tk.Label(root, text="Transaction ID:").pack(pady=5)
entry_id = tk.Entry(root)
entry_id.pack(pady=5)

tk.Button(root, text="Print Receipt", command=cetak_nota).pack(pady=10)
tk.Button(root, text="Refresh Printer", command=refresh_printer).pack(pady=10)

footer_frame = tk.Frame(root)
footer_frame.pack(side="bottom", pady=15)

lbl_copy = tk.Label(
    footer_frame,
    text="© 2025 Fathir Afatar • v2.0 • ",
    font=("Arial", 9),
    fg="#555555",
)
lbl_copy.pack(side="left")

lbl_license = tk.Label(
    footer_frame,
    text="MIT License",
    font=("Arial", 9, "underline"),
    fg="#0066cc",
    cursor="hand2",
)
lbl_license.pack(side="left")
lbl_license.bind("<Button-1>", lambda e: show_license())

# jalankan Flask di thread terpisah
threading.Thread(target=run_flask, daemon=True).start()

root.mainloop()