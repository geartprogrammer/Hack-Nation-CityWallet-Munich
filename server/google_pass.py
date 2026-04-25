"""
Google Wallet pass generator

Google Wallet passes are created via the Google Wallet API.
The user taps a "Save to Google Wallet" link, which contains a JWT.
The JWT encodes the entire pass object — no file download needed.

The pass appears in Google Wallet with geofence locations.
When the user walks near the location, Android surfaces it.

REQUIREMENTS:
  1. Google Cloud project with "Google Wallet API" enabled
  2. A service account with a JSON key file
  3. An Issuer ID from the Google Pay & Wallet Console
     (https://pay.google.com/business/console)

Place credentials in server/certs/:
  - google_service_account.json

Set environment variables:
  - GOOGLE_ISSUER_ID (your issuer ID from the Wallet console)

Without these, the generator creates the JWT structure but it
won't be accepted by Google. For testing, you can decode the JWT
at jwt.io to inspect the pass object.
"""

import json
import time
import uuid
import os
import base64
import hashlib
import hmac
from pathlib import Path

CERTS_DIR = Path(__file__).parent / "certs"
ISSUER_ID = os.environ.get("GOOGLE_ISSUER_ID", "3388000000000000000")


def _base64url(data):
    """Base64url encode without padding."""
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _load_service_account():
    """Load Google service account credentials."""
    sa_path = CERTS_DIR / "google_service_account.json"
    if not sa_path.exists():
        print(f"[GPASS] Service account not found: {sa_path}")
        print(f"[GPASS] JWT will be generated but unsigned (won't work with Google)")
        return None
    return json.loads(sa_path.read_text())


def _sign_jwt(payload, service_account):
    """
    Sign a JWT using the service account's private key.
    Uses RS256 (RSA + SHA256).

    For proper RSA signing, we shell out to openssl since
    Python stdlib doesn't have RSA signing built in.
    """
    import subprocess
    import tempfile

    header = {"alg": "RS256", "typ": "JWT", "kid": service_account.get("private_key_id", "")}
    segments = _base64url(json.dumps(header)) + "." + _base64url(json.dumps(payload))

    # Write private key to temp file
    key_path = Path(tempfile.mktemp(suffix=".pem"))
    try:
        key_path.write_text(service_account["private_key"])

        # Sign with openssl
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(key_path)],
            input=segments.encode(),
            capture_output=True
        )
        if result.returncode != 0:
            print(f"[GPASS] JWT signing failed: {result.stderr.decode()}")
            return segments + ".UNSIGNED"

        signature = _base64url(result.stdout)
        return segments + "." + signature
    finally:
        key_path.unlink(missing_ok=True)


def _create_unsigned_jwt(payload):
    """Create a JWT without signing (for inspection/testing only)."""
    header = {"alg": "none", "typ": "JWT"}
    return _base64url(json.dumps(header)) + "." + _base64url(json.dumps(payload)) + "."


def create_offer_class(merchant):
    """
    Create a Google Wallet Offer Class.
    This defines the template — all passes of this type share the class.
    You only need to create this once per merchant.
    """
    class_id = f"{ISSUER_ID}.munichmarkt-{merchant['id']}"

    return {
        "id": class_id,
        "issuerName": "Munich Markt",
        "title": f"{merchant['name']} - {merchant['area']}",
        "provider": "Munich Markt",
        "redemptionChannel": "instore",
        "reviewStatus": "UNDER_REVIEW",
        "hexBackgroundColor": "#14140f",
        "heroImage": {
            "sourceUri": {
                "uri": "https://via.placeholder.com/1032x336/14140f/d4a437?text=Munich+Markt"
            }
        },
        # GEOFENCE LOCATIONS
        # Google Wallet monitors these and surfaces the pass when nearby
        "locations": [
            {
                "latitude": merchant["lat"],
                "longitude": merchant["lng"]
            }
        ],
        "titleImage": {
            "sourceUri": {
                "uri": "https://via.placeholder.com/80/b85c2b/ffffff?text=M"
            }
        }
    }


def create_offer_object(merchant, offer_code, serial=None):
    """
    Create a Google Wallet Offer Object.
    This is the individual pass instance — one per user.
    """
    serial = serial or str(uuid.uuid4())
    class_id = f"{ISSUER_ID}.munichmarkt-{merchant['id']}"
    object_id = f"{ISSUER_ID}.{serial}"

    today = time.strftime("%Y-%m-%d")
    valid_end = f"{today}T{merchant['quiet_end']}:00.000Z"

    return {
        "id": object_id,
        "classId": class_id,
        "state": "ACTIVE",
        "heroImage": {
            "sourceUri": {
                "uri": "https://via.placeholder.com/1032x336/14140f/d4a437?text=Munich+Markt"
            }
        },
        # ── The barcode the merchant scans ────────────────────
        "barcode": {
            "type": "QR_CODE",
            "value": offer_code,
            "alternateText": offer_code
        },
        # ── GEOFENCE LOCATIONS ────────────────────────────────
        # These override the class locations if present.
        # Android surfaces the pass on the lock screen when nearby.
        "locations": [
            {
                "latitude": merchant["lat"],
                "longitude": merchant["lng"]
            }
        ],
        # ── Time window ───────────────────────────────────────
        "validTimeInterval": {
            "start": {
                "date": f"{today}T{merchant['quiet_start']}:00.000Z"
            },
            "end": {
                "date": valid_end
            }
        },
        # ── Display fields ────────────────────────────────────
        "textModulesData": [
            {
                "header": "OFFER",
                "body": f"EUR {merchant['offer_value']:.2f} off - {merchant['offer_text']}",
                "id": "offer_detail"
            },
            {
                "header": "MERCHANT",
                "body": f"{merchant['name']} · {merchant['area']}",
                "id": "merchant_info"
            },
            {
                "header": "VALID",
                "body": f"{merchant['quiet_start']} - {merchant['quiet_end']} today",
                "id": "valid_time"
            },
            {
                "header": "HOW TO REDEEM",
                "body": "Show this pass to the barista. They will scan the QR code.",
                "id": "instructions"
            }
        ]
    }


def generate_save_link(merchant, offer_code, serial=None):
    """
    Generate a "Save to Google Wallet" URL.

    The URL contains a JWT that encodes the pass class + object.
    When the user taps it, Google Wallet adds the pass.

    Returns: (url, serial)
    """
    serial = serial or str(uuid.uuid4())

    offer_class = create_offer_class(merchant)
    offer_object = create_offer_object(merchant, offer_code, serial)

    # JWT payload
    now = int(time.time())
    sa = _load_service_account()

    payload = {
        "iss": sa["client_email"] if sa else "test@munichmarkt.iam.gserviceaccount.com",
        "aud": "google",
        "typ": "savetowallet",
        "iat": now,
        "origins": ["*"],
        "payload": {
            "offerClasses": [offer_class],
            "offerObjects": [offer_object]
        }
    }

    # Sign JWT
    if sa:
        jwt_token = _sign_jwt(payload, sa)
    else:
        jwt_token = _create_unsigned_jwt(payload)

    save_url = f"https://pay.google.com/gp/v/save/{jwt_token}"

    print(f"[GPASS] Generated save link for {merchant['name']} (serial: {serial})")
    return save_url, serial


def generate_save_link_simple(merchant, offer_code):
    """
    Generate a simpler JWT-based save link that works even without
    a service account, using the Google Wallet deeplink format.

    This creates a direct link to add a pass. Less control over
    appearance but works for testing.
    """
    serial = str(uuid.uuid4())
    offer_object = create_offer_object(merchant, offer_code, serial)

    # For unsigned testing, encode the object directly
    object_json = json.dumps(offer_object)
    encoded = _base64url(object_json)

    return f"https://pay.google.com/gp/v/save/{encoded}", serial
