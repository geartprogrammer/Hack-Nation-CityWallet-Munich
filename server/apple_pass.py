"""
Apple Wallet .pkpass generator

A .pkpass file is a signed ZIP archive containing:
  pass.json       — the pass definition (offers, locations, barcode, style)
  manifest.json   — SHA1 hash of every file in the archive
  signature        — CMS signature of manifest.json (using Apple certs)
  icon.png         — required 29x29 icon
  icon@2x.png     — required 58x58 icon
  logo.png         — optional logo shown on the pass
  strip.png        — optional strip image

Apple Wallet reads the `locations` array in pass.json and triggers
a lock-screen notification when the user enters the geofence (~100m).

REQUIREMENTS:
  1. Apple Developer account ($99/year)
  2. A Pass Type ID registered at developer.apple.com/account
  3. A signing certificate (.pem) for that Pass Type ID
  4. The private key (.pem) for that certificate
  5. The Apple WWDR intermediate certificate (AppleWWDRCAG4.pem)

Place these files in server/certs/:
  - pass_cert.pem     (your pass signing certificate)
  - pass_key.pem      (private key for the certificate)
  - wwdr.pem          (Apple WWDR G4 intermediate cert)

Without these certs, the pass will be generated but won't install on a real iPhone.
For testing, you can inspect the generated .pkpass by renaming it to .zip and extracting.
"""

import json
import hashlib
import zipfile
import uuid
import os
import subprocess
import time
from pathlib import Path
from io import BytesIO

CERTS_DIR = Path(__file__).parent / "certs"
PASSES_DIR = Path(__file__).parent / "passes"
PASSES_DIR.mkdir(exist_ok=True)


def create_pass_json(merchant, offer_code, serial=None, auth_token=None, web_service_url=None):
    """
    Build the pass.json structure for a store card / coupon.

    The `locations` array is the key: Apple Wallet monitors these coordinates
    and surfaces the pass on the lock screen when the user is nearby.
    """
    serial = serial or str(uuid.uuid4())
    auth_token = auth_token or str(uuid.uuid4()).replace("-", "")

    pass_json = {
        # ── Required metadata ─────────────────────────────────────
        "formatVersion": 1,
        "passTypeIdentifier": os.environ.get("PASS_TYPE_ID", "pass.com.munichmarkt.offer"),
        "serialNumber": serial,
        "teamIdentifier": os.environ.get("TEAM_ID", "XXXXXXXXXX"),
        "organizationName": "Munich Markt",
        "description": f"{merchant['name']} - {merchant['offer_text']}",

        # ── Authentication for pass updates ───────────────────────
        # Apple Wallet calls webServiceURL to check for updates.
        # This is how we push new offers to an installed pass.
        "authenticationToken": auth_token,

        # ── Colors and appearance ─────────────────────────────────
        "backgroundColor": "rgb(20, 20, 15)",
        "foregroundColor": "rgb(246, 245, 241)",
        "labelColor": "rgb(166, 162, 153)",

        # ── GEOFENCE LOCATIONS ────────────────────────────────────
        # This is the trigger. Apple Wallet monitors these coordinates.
        # When the user walks within ~100m, the pass appears on the lock screen.
        # You can have up to 10 locations per pass.
        "locations": [
            {
                "latitude": merchant["lat"],
                "longitude": merchant["lng"],
                "relevantText": f"{merchant['offer_text']} at {merchant['name']} - nearby now"
            }
        ],

        # ── Time relevance ────────────────────────────────────────
        # Pass surfaces during these hours (combined with location)
        "relevantDate": _build_relevant_date(merchant),

        # ── Barcode ───────────────────────────────────────────────
        # The merchant scans this to redeem
        "barcode": {
            "format": "PKBarcodeFormatQR",
            "message": offer_code,
            "messageEncoding": "iso-8859-1",
            "altText": offer_code
        },
        # Also include barcodes array for newer iOS
        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": offer_code,
                "messageEncoding": "iso-8859-1",
                "altText": offer_code
            }
        ],

        # ── Pass structure (storeCard type) ───────────────────────
        # storeCard is the right type for loyalty/offer passes.
        # Other options: boardingPass, coupon, eventTicket, generic
        "storeCard": {
            "headerFields": [
                {
                    "key": "offer",
                    "label": "OFFER",
                    "value": f"EUR {merchant['offer_value']:.2f} off"
                }
            ],
            "primaryFields": [
                {
                    "key": "merchant",
                    "label": "MERCHANT",
                    "value": merchant["name"]
                }
            ],
            "secondaryFields": [
                {
                    "key": "area",
                    "label": "AREA",
                    "value": merchant["area"]
                },
                {
                    "key": "valid",
                    "label": "VALID",
                    "value": f"{merchant['quiet_start']} - {merchant['quiet_end']} today"
                }
            ],
            "auxiliaryFields": [
                {
                    "key": "distance",
                    "label": "STATUS",
                    "value": "ACTIVE"
                }
            ],
            "backFields": [
                {
                    "key": "terms",
                    "label": "Terms",
                    "value": "Show this pass to the barista to redeem. One use per customer. Valid during quiet hours only."
                },
                {
                    "key": "about",
                    "label": "About Munich Markt",
                    "value": "Munich Markt connects you with real local offers from cafes and shops during their quiet hours. All matching happens on your device. We never track your location."
                },
                {
                    "key": "merchant_phone",
                    "label": "Contact",
                    "value": merchant.get("phone", "See in-store for details")
                }
            ]
        },

        # ── Sharing ───────────────────────────────────────────────
        "sharingProhibited": False,

        # ── Expiration ────────────────────────────────────────────
        "voided": False
    }

    # Add web service URL if server is configured (enables push updates)
    if web_service_url:
        pass_json["webServiceURL"] = web_service_url

    return pass_json, serial, auth_token


def _build_relevant_date(merchant):
    """Build ISO 8601 date for today during the merchant's quiet hours."""
    today = time.strftime("%Y-%m-%d")
    return f"{today}T{merchant['quiet_start']}:00+02:00"


def create_icon_png(size=58):
    """
    Generate a minimal valid PNG icon.
    In production, replace with your actual brand icon.
    This creates a simple colored square that satisfies Apple's requirements.
    """
    # Minimal valid PNG: single-color square
    import struct
    import zlib

    width = height = size
    # RGBA: copper color #b85c2b
    r, g, b, a = 184, 92, 43, 255

    raw_data = b""
    for y in range(height):
        raw_data += b"\x00"  # filter byte (none)
        for x in range(width):
            raw_data += bytes([r, g, b, a])

    def make_chunk(chunk_type, data):
        chunk = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + chunk + crc

    png = b"\x89PNG\r\n\x1a\n"
    png += make_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    compressed = zlib.compress(raw_data)
    png += make_chunk(b"IDAT", compressed)
    png += make_chunk(b"IEND", b"")
    return png


def build_manifest(files_dict):
    """
    Build manifest.json: a dict mapping filename -> SHA1 hash.
    Apple Wallet verifies every file against this manifest.
    """
    manifest = {}
    for filename, content in files_dict.items():
        sha1 = hashlib.sha1(content).hexdigest()
        manifest[filename] = sha1
    return json.dumps(manifest).encode()


def sign_manifest(manifest_data):
    """
    Sign the manifest using OpenSSL (CMS detached signature).

    This requires:
      - server/certs/pass_cert.pem  (your Pass Type ID certificate)
      - server/certs/pass_key.pem   (private key)
      - server/certs/wwdr.pem       (Apple WWDR intermediate cert)

    Returns the DER-encoded signature bytes, or None if signing fails.
    """
    cert_file = CERTS_DIR / "pass_cert.pem"
    key_file = CERTS_DIR / "pass_key.pem"
    wwdr_file = CERTS_DIR / "wwdr.pem"

    if not cert_file.exists() or not key_file.exists() or not wwdr_file.exists():
        print(f"[PASS] Signing certs not found in {CERTS_DIR}/")
        print(f"[PASS]   Need: pass_cert.pem, pass_key.pem, wwdr.pem")
        print(f"[PASS]   Pass will be generated UNSIGNED (won't install on real device)")
        return None

    # Write manifest to temp file
    manifest_path = PASSES_DIR / "_tmp_manifest.json"
    signature_path = PASSES_DIR / "_tmp_signature"

    try:
        manifest_path.write_bytes(manifest_data)

        # OpenSSL CMS sign command
        cmd = [
            "openssl", "smime", "-sign", "-binary",
            "-in", str(manifest_path),
            "-out", str(signature_path),
            "-outform", "DER",
            "-signer", str(cert_file),
            "-inkey", str(key_file),
            "-certfile", str(wwdr_file),
            "-passin", f"pass:{os.environ.get('PASS_KEY_PASSWORD', '')}"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[PASS] OpenSSL signing failed: {result.stderr}")
            return None

        return signature_path.read_bytes()

    finally:
        manifest_path.unlink(missing_ok=True)
        if signature_path.exists() and signature_path.stat().st_size == 0:
            signature_path.unlink(missing_ok=True)


def generate_pkpass(merchant, offer_code, web_service_url=None):
    """
    Generate a complete .pkpass file (ZIP archive).

    Returns: (bytes, serial, auth_token)
      - bytes: the .pkpass file content, ready to send as application/vnd.apple.pkpass
      - serial: the unique serial number for this pass
      - auth_token: the auth token for pass update callbacks
    """

    # 1. Build pass.json
    pass_data, serial, auth_token = create_pass_json(
        merchant, offer_code, web_service_url=web_service_url
    )

    # 2. Create icon PNGs
    icon_1x = create_icon_png(29)
    icon_2x = create_icon_png(58)
    icon_3x = create_icon_png(87)
    logo_1x = create_icon_png(50)
    logo_2x = create_icon_png(100)

    # 3. Collect all files
    files = {
        "pass.json": json.dumps(pass_data, indent=2).encode(),
        "icon.png": icon_1x,
        "icon@2x.png": icon_2x,
        "icon@3x.png": icon_3x,
        "logo.png": logo_1x,
        "logo@2x.png": logo_2x,
    }

    # 4. Build manifest
    manifest_data = build_manifest(files)
    files["manifest.json"] = manifest_data

    # 5. Sign manifest (requires certs)
    signature = sign_manifest(manifest_data)
    if signature:
        files["signature"] = signature

    # 6. Create ZIP
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)

    pkpass_bytes = buffer.getvalue()

    # 7. Save a copy for inspection
    output_path = PASSES_DIR / f"{serial}.pkpass"
    output_path.write_bytes(pkpass_bytes)
    print(f"[PASS] Generated: {output_path} ({len(pkpass_bytes)} bytes)")

    return pkpass_bytes, serial, auth_token


def update_pass_json(serial, updates):
    """
    Update a pass's data (for push updates).
    After calling this, trigger an APNs push to the device.

    `updates` can include:
      - New offer text/value
      - New locations (re-target to a different merchant)
      - Status change (redeemed, expired)
    """
    pass_path = PASSES_DIR / f"{serial}.pkpass"
    if not pass_path.exists():
        return None

    # Extract, modify, re-sign, re-zip
    buffer = BytesIO(pass_path.read_bytes())
    with zipfile.ZipFile(buffer, "r") as zf:
        pass_data = json.loads(zf.read("pass.json"))

    # Apply updates
    if "locations" in updates:
        pass_data["locations"] = updates["locations"]
    if "offer_text" in updates:
        pass_data["storeCard"]["headerFields"][0]["value"] = updates["offer_text"]
    if "status" in updates:
        pass_data["storeCard"]["auxiliaryFields"][0]["value"] = updates["status"]
    if "voided" in updates:
        pass_data["voided"] = updates["voided"]
    if "relevantDate" in updates:
        pass_data["relevantDate"] = updates["relevantDate"]

    return pass_data
