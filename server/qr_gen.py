"""
QR Code generator for Munich Markt passes.
Generates real, scannable QR codes as SVG or PNG.
Each QR points to the pass delivery page for a specific merchant.
"""

import qrcode
import qrcode.image.svg
from io import BytesIO


def generate_qr_svg(url):
    """Generate a real, scannable QR code as SVG string."""
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(url, image_factory=factory, box_size=10, border=2)
    buf = BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def generate_qr_png(url):
    """Generate a real, scannable QR code as PNG bytes."""
    img = qrcode.make(url, box_size=10, border=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
