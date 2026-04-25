"""
PROJECT REAL - Munich Markt Server
Zero external dependencies. Python 3 standard library only.

Serves:
  - Real Apple Wallet .pkpass files (application/vnd.apple.pkpass)
  - Google Wallet save links (JWT-encoded)
  - Apple Wallet update callbacks (webServiceURL protocol)
  - Merchant console, live ledger, SSE stream
"""

import http.server
import json
import os
import time
import uuid
import hashlib
import threading
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# Import our pass generators
from apple_pass import generate_pkpass, update_pass_json
from google_pass import generate_save_link
from qr_gen import generate_qr_svg, generate_qr_png

# ── State (in-memory, resets on restart) ──────────────────────────

MERCHANTS = {}     # id -> merchant dict
REDEMPTIONS = []   # list of redemption events
OPTINS = {}        # user_id -> optin dict
SSE_CLIENTS = []   # list of SSE response objects
LOCK = threading.Lock()

# Pass registry: tracks issued passes for Apple Wallet update protocol
PASSES = {}        # serial -> {merchant_id, auth_token, device_tokens: []}
DEVICE_PASSES = {} # device_id -> [serial, ...]  (which passes a device has)

# ── Demo merchants (pre-loaded for in-room testing) ──────────────

def seed_demo_data():
    demos = [
        {
            "id": "cafe-riese",
            "name": "Cafe Riese",
            "area": "Schwabing",
            "lat": 48.1629,
            "lng": 11.5862,
            "quiet_start": "14:00",
            "quiet_end": "16:00",
            "offer_text": "1.50 off any hot drink",
            "offer_value": 1.50,
            "currency": "EUR",
            "status": "live",
            "walk_ins": 0,
            "revenue": 0.0
        },
        {
            "id": "backerei-knaus",
            "name": "Backerei Knaus",
            "area": "Glockenbachviertel",
            "lat": 48.1295,
            "lng": 11.5735,
            "quiet_start": "15:00",
            "quiet_end": "17:00",
            "offer_text": "1.00 off fresh pastry",
            "offer_value": 1.00,
            "currency": "EUR",
            "status": "live",
            "walk_ins": 0,
            "revenue": 0.0
        },
        {
            "id": "brioche-marie",
            "name": "Brioche Marie",
            "area": "Viktualienmarkt",
            "lat": 48.1351,
            "lng": 11.5767,
            "quiet_start": "16:00",
            "quiet_end": "18:00",
            "offer_text": "2.00 off lunch set",
            "offer_value": 2.00,
            "currency": "EUR",
            "status": "live",
            "walk_ins": 0,
            "revenue": 0.0
        }
    ]
    for m in demos:
        MERCHANTS[m["id"]] = m

seed_demo_data()

# ── SSE broadcast ─────────────────────────────────────────────────

def broadcast(event_type, data):
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with LOCK:
        dead = []
        for client in SSE_CLIENTS:
            try:
                client.wfile.write(msg.encode())
                client.wfile.flush()
            except Exception:
                dead.append(client)
        for d in dead:
            SSE_CLIENTS.remove(d)

def get_ledger_snapshot():
    total_walkins = sum(m["walk_ins"] for m in MERCHANTS.values())
    total_revenue = sum(m["revenue"] for m in MERCHANTS.values())
    return {
        "merchants": list(MERCHANTS.values()),
        "total_revenue": round(total_revenue, 2),
        "total_walkins": total_walkins,
        "total_optins": len(OPTINS),
        "redemptions": len(REDEMPTIONS),
        "last_update": time.time()
    }

# ── HTTP Handler ──────────────────────────────────────────────────

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
BASE_URL = os.environ.get("BASE_URL", "http://192.168.101.173:5050")

class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}")

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # ── APPLE WALLET: Generate and serve .pkpass ──────────

        if path == "/pass/apple":
            merchant_id = params.get("merchant", ["cafe-riese"])[0]
            if merchant_id not in MERCHANTS:
                return self.send_json({"error": "Unknown merchant"}, 404)

            merchant = MERCHANTS[merchant_id]
            offer_code = f"{merchant_id.upper()[:5]}-{uuid.uuid4().hex[:6].upper()}"
            web_service_url = f"{BASE_URL}/api/passes"

            pkpass_bytes, serial, auth_token = generate_pkpass(
                merchant, offer_code, web_service_url=web_service_url
            )

            # Register pass for updates
            PASSES[serial] = {
                "merchant_id": merchant_id,
                "auth_token": auth_token,
                "offer_code": offer_code,
                "created": time.time()
            }

            # Register opt-in
            OPTINS[serial] = {
                "user_id": serial,
                "timestamp": time.time(),
                "ts_human": time.strftime("%H:%M:%S"),
                "type": "apple_wallet"
            }
            broadcast("optin", OPTINS[serial])
            broadcast("snapshot", get_ledger_snapshot())

            # Serve the .pkpass file
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.pkpass")
            self.send_header("Content-Disposition", f'attachment; filename="{merchant_id}.pkpass"')
            self.send_header("Content-Length", len(pkpass_bytes))
            self.end_headers()
            self.wfile.write(pkpass_bytes)
            return

        # ── GOOGLE WALLET: Generate save link ─────────────────

        if path == "/pass/google":
            merchant_id = params.get("merchant", ["cafe-riese"])[0]
            if merchant_id not in MERCHANTS:
                return self.send_json({"error": "Unknown merchant"}, 404)

            merchant = MERCHANTS[merchant_id]
            offer_code = f"{merchant_id.upper()[:5]}-{uuid.uuid4().hex[:6].upper()}"

            save_url, serial = generate_save_link(merchant, offer_code)

            # Register pass
            PASSES[serial] = {
                "merchant_id": merchant_id,
                "offer_code": offer_code,
                "created": time.time()
            }

            # Register opt-in
            OPTINS[serial] = {
                "user_id": serial,
                "timestamp": time.time(),
                "ts_human": time.strftime("%H:%M:%S"),
                "type": "google_wallet"
            }
            broadcast("optin", OPTINS[serial])
            broadcast("snapshot", get_ledger_snapshot())

            # Redirect to Google Wallet
            self.send_response(302)
            self.send_header("Location", save_url)
            self.end_headers()
            return

        # ── PASS DELIVERY: Detect device, serve correct pass ──

        if path.startswith("/pass/") and path != "/pass/apple" and path != "/pass/google":
            merchant_id = path.split("/")[-1]
            if merchant_id not in MERCHANTS:
                merchant_id = "cafe-riese"

            # Serve the landing page (detects device and redirects)
            file_path = PUBLIC_DIR / "pass.html"
            if file_path.is_file():
                body = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
                return

        # ── QR CODE GENERATION ────────────────────────────────

        if path == "/qr/svg":
            merchant_id = params.get("merchant", ["cafe-riese"])[0]
            url = f"{BASE_URL}/pass/{merchant_id}"
            svg = generate_qr_svg(url)
            body = svg.encode() if isinstance(svg, str) else svg
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/qr/png":
            merchant_id = params.get("merchant", ["cafe-riese"])[0]
            url = f"{BASE_URL}/pass/{merchant_id}"
            png = generate_qr_png(url)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", len(png))
            self.end_headers()
            self.wfile.write(png)
            return

        # ── POSTER PAGE (printable QR poster per merchant) ────

        if path.startswith("/poster/"):
            merchant_id = path.split("/")[-1]
            if merchant_id not in MERCHANTS:
                merchant_id = "cafe-riese"
            # Serve the poster template
            file_path = PUBLIC_DIR / "poster.html"
            if file_path.is_file():
                body = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
                return

        # ── POSTERS INDEX (all merchants) ─────────────────────

        if path == "/posters":
            file_path = PUBLIC_DIR / "posters.html"
            if file_path.is_file():
                body = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
                return

        # ── APPLE WALLET UPDATE PROTOCOL ──────────────────────
        # Apple Wallet calls these endpoints to check for updates.
        # See: https://developer.apple.com/documentation/walletpasses

        # GET /api/passes/v1/passes/{passTypeId}/{serial}
        # Apple calls this to get the latest version of a pass
        if path.startswith("/api/passes/v1/passes/"):
            parts = path.split("/")
            if len(parts) >= 7:
                serial = parts[6]
                if serial in PASSES:
                    pass_info = PASSES[serial]
                    merchant = MERCHANTS.get(pass_info["merchant_id"])
                    if merchant:
                        pkpass_bytes, _, _ = generate_pkpass(
                            merchant, pass_info["offer_code"],
                            web_service_url=f"{BASE_URL}/api/passes"
                        )
                        self.send_response(200)
                        self.send_header("Content-Type", "application/vnd.apple.pkpass")
                        self.send_header("Content-Length", len(pkpass_bytes))
                        self.end_headers()
                        self.wfile.write(pkpass_bytes)
                        return
            self.send_response(404)
            self.end_headers()
            return

        # GET /api/passes/v1/devices/{deviceId}/registrations/{passTypeId}
        # Apple calls this to get serials for a device
        if path.startswith("/api/passes/v1/devices/") and "/registrations/" in path:
            parts = path.split("/")
            device_id = parts[5] if len(parts) > 5 else ""
            serials = DEVICE_PASSES.get(device_id, [])
            if serials:
                return self.send_json({
                    "serialNumbers": serials,
                    "lastUpdated": str(int(time.time()))
                })
            self.send_response(204)
            self.end_headers()
            return

        # ── Existing API routes ───────────────────────────────

        if path == "/api/merchants":
            return self.send_json(list(MERCHANTS.values()))

        if path == "/api/ledger":
            return self.send_json(get_ledger_snapshot())

        if path == "/api/catalog":
            catalog = []
            for m in MERCHANTS.values():
                catalog.append({
                    "id": m["id"], "name": m["name"], "area": m["area"],
                    "lat": m["lat"], "lng": m["lng"],
                    "quiet_start": m["quiet_start"], "quiet_end": m["quiet_end"],
                    "offer_text": m["offer_text"], "offer_value": m["offer_value"],
                    "status": m["status"]
                })
            return self.send_json(catalog)

        if path == "/api/optins":
            return self.send_json({"count": len(OPTINS), "optins": list(OPTINS.values())})

        if path == "/api/redemptions":
            return self.send_json(REDEMPTIONS)

        # ── SSE stream ────────────────────────────────────────

        if path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            snapshot = get_ledger_snapshot()
            msg = f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"
            self.wfile.write(msg.encode())
            self.wfile.flush()
            with LOCK:
                SSE_CLIENTS.append(self)
            try:
                while True:
                    time.sleep(1)
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except Exception:
                with LOCK:
                    if self in SSE_CLIENTS:
                        SSE_CLIENTS.remove(self)
            return

        # ── Static files ──────────────────────────────────────

        if path == "/":
            path = "/index.html"
        if path == "/merchant":
            path = "/merchant.html"
        if path == "/ledger":
            path = "/ledger.html"

        file_path = PUBLIC_DIR / path.lstrip("/")
        if file_path.is_file():
            ext = file_path.suffix.lower()
            content_types = {
                ".html": "text/html", ".js": "application/javascript",
                ".css": "text/css", ".json": "application/json",
                ".svg": "image/svg+xml", ".png": "image/png",
                ".ico": "image/x-icon",
                ".webmanifest": "application/manifest+json",
                ".pkpass": "application/vnd.apple.pkpass",
            }
            ctype = content_types.get(ext, "application/octet-stream")
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # ── APPLE WALLET: Device registration ─────────────────
        # POST /api/passes/v1/devices/{deviceId}/registrations/{passTypeId}/{serial}
        # Apple Wallet calls this when a pass is added to a device
        if path.startswith("/api/passes/v1/devices/") and "/registrations/" in path:
            parts = path.split("/")
            if len(parts) >= 8:
                device_id = parts[5]
                serial = parts[7]

                # Verify auth token
                auth_header = self.headers.get("Authorization", "")
                token = auth_header.replace("ApplePass ", "")

                if serial in PASSES:
                    # Register device <-> pass mapping
                    if device_id not in DEVICE_PASSES:
                        DEVICE_PASSES[device_id] = []
                    if serial not in DEVICE_PASSES[device_id]:
                        DEVICE_PASSES[device_id].append(serial)

                    print(f"[APPLE] Device {device_id[:8]}... registered pass {serial[:8]}...")
                    self.send_response(201)
                    self.end_headers()
                    return

            self.send_response(401)
            self.end_headers()
            return

        # ── APPLE WALLET: Log endpoint ────────────────────────
        # POST /api/passes/v1/log
        if path == "/api/passes/v1/log":
            data = self.read_body()
            for msg in data.get("logs", []):
                print(f"[APPLE LOG] {msg}")
            self.send_response(200)
            self.end_headers()
            return

        # ── Merchant registration ─────────────────────────────

        if path == "/api/merchants":
            data = self.read_body()
            mid = data.get("id") or str(uuid.uuid4())[:8]
            merchant = {
                "id": mid,
                "name": data.get("name", "Unknown"),
                "area": data.get("area", "Munich"),
                "lat": float(data.get("lat", 48.1351)),
                "lng": float(data.get("lng", 11.5820)),
                "quiet_start": data.get("quiet_start", "14:00"),
                "quiet_end": data.get("quiet_end", "16:00"),
                "offer_text": data.get("offer_text", "Special offer"),
                "offer_value": float(data.get("offer_value", 1.50)),
                "currency": data.get("currency", "EUR"),
                "status": "live",
                "walk_ins": 0,
                "revenue": 0.0
            }
            MERCHANTS[mid] = merchant
            broadcast("merchant_added", merchant)
            broadcast("snapshot", get_ledger_snapshot())
            return self.send_json(merchant, 201)

        # ── User opt-in ──────────────────────────────────────

        if path == "/api/optin":
            data = self.read_body()
            user_id = data.get("user_id") or str(uuid.uuid4())
            optin = {
                "user_id": user_id,
                "timestamp": time.time(),
                "ts_human": time.strftime("%H:%M:%S")
            }
            OPTINS[user_id] = optin
            broadcast("optin", optin)
            broadcast("snapshot", get_ledger_snapshot())
            return self.send_json({"user_id": user_id, "catalog_url": "/api/catalog"})

        # ── Redemption ────────────────────────────────────────

        if path == "/api/redeem":
            data = self.read_body()
            merchant_id = data.get("merchant_id")
            code = data.get("code", "")

            if merchant_id not in MERCHANTS:
                return self.send_json({"error": "Unknown merchant"}, 404)

            merchant = MERCHANTS[merchant_id]
            redemption = {
                "id": str(uuid.uuid4())[:8],
                "merchant_id": merchant_id,
                "merchant_name": merchant["name"],
                "code": code,
                "value": merchant["offer_value"],
                "timestamp": time.time(),
                "ts_human": time.strftime("%H:%M:%S")
            }
            REDEMPTIONS.append(redemption)
            merchant["walk_ins"] += 1
            merchant["revenue"] += round(merchant["offer_value"] * 3, 2)

            broadcast("redemption", redemption)
            broadcast("snapshot", get_ledger_snapshot())
            return self.send_json(redemption, 201)

        # ── Update merchant ───────────────────────────────────

        if path.startswith("/api/merchants/"):
            mid = path.split("/")[-1]
            if mid not in MERCHANTS:
                return self.send_json({"error": "Not found"}, 404)
            data = self.read_body()
            merchant = MERCHANTS[mid]
            for key in ["name", "area", "quiet_start", "quiet_end", "offer_text", "status"]:
                if key in data:
                    merchant[key] = data[key]
            if "offer_value" in data:
                merchant["offer_value"] = float(data["offer_value"])
            if "lat" in data:
                merchant["lat"] = float(data["lat"])
            if "lng" in data:
                merchant["lng"] = float(data["lng"])
            broadcast("merchant_updated", merchant)
            broadcast("snapshot", get_ledger_snapshot())
            return self.send_json(merchant)

        # ── Reset ─────────────────────────────────────────────

        if path == "/api/reset":
            MERCHANTS.clear()
            REDEMPTIONS.clear()
            OPTINS.clear()
            PASSES.clear()
            DEVICE_PASSES.clear()
            seed_demo_data()
            broadcast("snapshot", get_ledger_snapshot())
            return self.send_json({"status": "reset"})

        self.send_json({"error": "Not found"}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path

        # ── APPLE WALLET: Device unregistration ───────────────
        # DELETE /api/passes/v1/devices/{deviceId}/registrations/{passTypeId}/{serial}
        if path.startswith("/api/passes/v1/devices/") and "/registrations/" in path:
            parts = path.split("/")
            if len(parts) >= 8:
                device_id = parts[5]
                serial = parts[7]
                if device_id in DEVICE_PASSES:
                    DEVICE_PASSES[device_id] = [s for s in DEVICE_PASSES[device_id] if s != serial]
                print(f"[APPLE] Device {device_id[:8]}... unregistered pass {serial[:8]}...")
                self.send_response(200)
                self.end_headers()
                return

        self.send_response(404)
        self.end_headers()


# ── Server startup ────────────────────────────────────────────────

class ThreadedServer(http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        t.daemon = True
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 4000))
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    print(f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║  PROJECT REAL - Munich Markt                              ║
    ║  Server running on http://localhost:{PORT}                  ║
    ║                                                           ║
    ║  Pass endpoints:                                          ║
    ║    Add to Apple Wallet:   /pass/apple?merchant=cafe-riese ║
    ║    Add to Google Wallet:  /pass/google?merchant=cafe-riese║
    ║    Auto-detect device:    /pass/cafe-riese                ║
    ║                                                           ║
    ║  Dashboard:                                               ║
    ║    Merchant console:      /merchant                       ║
    ║    Live ledger:           /ledger                         ║
    ║                                                           ║
    ║  For phones: use http://192.168.x.x:{PORT}                 ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
