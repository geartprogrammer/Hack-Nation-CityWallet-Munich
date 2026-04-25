"""
CITY WALLET v5 — Real-world optimized
Real push notifications. Merchant QR scanner. 815 Munich cafes.
"""
from flask import Flask, request, jsonify, Response
import json, time, uuid, random, math, os, hashlib
from datetime import datetime
from io import BytesIO
from pathlib import Path

app = Flask(__name__)

# ── VAPID keys for Web Push ───────────────────────────────────────
VAPID_PUBLIC = "BD0IpekqsVFbloXMEbiHHiOgF_lKaQYQCp7uv7F1BgQ-ppQUFMdtqhhFuyuq-CoAdbN5PCydaQ-p9Wn0s85IFiE"
VAPID_PRIVATE = "S4CJhFVaTuaErh2yEYKy53QmJNMZARuV0eyxqLFxcvc"
VAPID_EMAIL = "mailto:citywallet@hacknation.dev"

# ── Load 815 real Munich cafes ────────────────────────────────────
CAFES_PATH = Path(__file__).parent / "munich_cafes.json"
RAW_CAFES = json.loads(CAFES_PATH.read_text(encoding="utf-8")) if CAFES_PATH.exists() else []

# ── State ─────────────────────────────────────────────────────────
REDEMPTIONS = []
OFFER_LOG = []
CASHBACK = {}
PUSH_SUBS = {}   # endpoint -> {subscription_info, lat, lng, ts}

# ── Helpers ───────────────────────────────────────────────────────
def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000  # meters
    dl = math.radians(lat2-lat1); dn = math.radians(lng2-lng1)
    a = math.sin(dl/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dn/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def _is_open_now(hours_str):
    """Best-effort check if a cafe is currently open from OSM opening_hours."""
    if not hours_str: return True  # Unknown = assume open
    now = datetime.now()
    h = now.hour
    day_abbr = ["Mo","Tu","We","Th","Fr","Sa","Su"][now.weekday()]
    # Very simplified parser: look for current day + hour range
    try:
        for part in hours_str.split(";"):
            part = part.strip()
            if "off" in part.lower() and day_abbr in part: return False
            if any(d in part for d in [day_abbr, "Mo-Su", "Mo-Fr" if now.weekday() < 5 else "XX", "PH"]):
                for token in part.split(","):
                    if "-" in token and ":" in token:
                        times = token.strip()
                        if " " in times: times = times.split(" ")[-1]
                        parts = times.split("-")
                        if len(parts) == 2:
                            try:
                                open_h = int(parts[0].split(":")[0])
                                close_h = int(parts[1].split(":")[0])
                                if open_h <= h < close_h: return True
                            except: pass
    except: pass
    return True  # Default: assume open

def _simulate_payone(cafe, hour):
    """Simulate Payone tx density for any cafe based on hour."""
    # Cafes are busier 8-10, 12-14, less busy 14-17
    base = 3
    if hour in [8,9,10]: base = 12
    elif hour in [11,12,13,14]: base = 15
    elif hour in [15,16,17]: base = 5
    elif hour in [18,19]: base = 8
    else: base = 2
    return max(1, base + random.randint(-2, 3))

def _weather_offer_text(weather, cafe, discount):
    """Generate short personalized offer copy from weather + cafe context."""
    temp = weather.get("temperature_c", 15)
    name = cafe["name"]
    tags = (cafe.get("cuisine") or "coffee").split(";")[0]

    if weather.get("is_rainy"):
        texts = [
            {"h": f"☔ {name}", "s": f"Duck in from the rain — {discount}% off", "frame": "shelter"},
            {"h": f"Raining. {name} is dry.", "s": f"Hot {tags} · {discount}% off right now", "frame": "shelter"},
        ]
    elif weather.get("is_cold"):
        texts = [
            {"h": f"🔥 Warm up at {name}", "s": f"{temp}° outside · {discount}% off something hot", "frame": "warmth"},
            {"h": f"{name} · {discount}% off", "s": f"It's {temp}° — you deserve warm {tags}", "frame": "warmth"},
        ]
    elif weather.get("is_hot"):
        texts = [
            {"h": f"🧊 Cool down at {name}", "s": f"{temp}° — iced drinks {discount}% off", "frame": "refresh"},
        ]
    elif 11 <= datetime.now().hour <= 14:
        texts = [
            {"h": f"🍽 {name} · {discount}% off", "s": f"Lunch deal — {tags} right here", "frame": "hunger"},
        ]
    else:
        texts = [
            {"h": f"✨ {name}", "s": f"{discount}% off · just for you, just for now", "frame": "discovery"},
            {"h": f"{name} · {discount}% off", "s": f"Quiet right now — perfect timing", "frame": "quiet"},
        ]
    return random.choice(texts)


# ══════════════════════════════════════════════════════════════════
#  CONTEXT
# ══════════════════════════════════════════════════════════════════

@app.route("/api/context", methods=["GET"])
def get_context():
    lat = float(request.args.get("lat", 48.1351))
    lng = float(request.args.get("lng", 11.5820))

    weather = _fetch_weather(lat, lng)
    now = datetime.now()
    time_ctx = {
        "hour": now.hour, "minute": now.minute,
        "day": now.strftime("%A"), "date": now.strftime("%Y-%m-%d"),
        "is_lunch": 11 <= now.hour <= 14,
        "is_afternoon": 14 <= now.hour <= 17,
        "is_weekend": now.weekday() >= 5,
    }
    return jsonify({"weather": weather, "time": time_ctx, "location": {"lat": lat, "lng": lng}})


def _fetch_weather(lat, lng):
    try:
        import requests
        r = requests.get(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,"
            f"apparent_temperature,precipitation,cloud_cover"
            f"&daily=uv_index_max,sunrise,sunset&timezone=auto&forecast_days=1",
            timeout=5
        )
        d = r.json(); c = d.get("current", {}); dy = d.get("daily", {})
        temp = c.get("temperature_2m", 15); code = c.get("weather_code", 0)
        feels = c.get("apparent_temperature", temp)
        uv = dy.get("uv_index_max", [0])[0] if dy.get("uv_index_max") else 0
        sunrise = (dy.get("sunrise",[""])[0] or "").split("T")[-1]
        sunset = (dy.get("sunset",[""])[0] or "").split("T")[-1]
        desc_map = {0:"Clear",1:"Clear",2:"Cloudy",3:"Overcast",45:"Foggy",51:"Drizzle",61:"Rain",63:"Rain",65:"Heavy rain",80:"Showers",95:"Storm"}
        return {
            "temp": temp, "feels": feels, "humidity": c.get("relative_humidity_2m",50),
            "wind": c.get("wind_speed_10m",10), "precip": c.get("precipitation",0),
            "clouds": c.get("cloud_cover",50), "code": code,
            "desc": desc_map.get(code, "Cloudy"),
            "is_cold": temp < 12, "is_hot": temp > 28, "is_rainy": code >= 51,
            "is_sunny": code <= 1, "uv": uv,
            "uv_label": "Low" if uv<3 else "Moderate" if uv<6 else "High",
            "sunrise": sunrise, "sunset": sunset,
        }
    except Exception as e:
        return {"temp":14,"feels":12,"desc":"Cloudy","is_cold":True,"is_hot":False,"is_rainy":False,
                "is_sunny":False,"uv":2,"uv_label":"Low","error":str(e)}


# ══════════════════════════════════════════════════════════════════
#  NEARBY OFFERS — distance-gated, context-aware
# ══════════════════════════════════════════════════════════════════

@app.route("/api/nearby", methods=["GET"])
def nearby_offers():
    """
    The main endpoint. Returns only cafes within radius, ranked by relevance.
    Each offer is generated dynamically from weather + Payone + distance.
    """
    lat = float(request.args.get("lat", 48.1351))
    lng = float(request.args.get("lng", 11.5820))
    radius = int(request.args.get("radius", 500))  # meters
    limit = int(request.args.get("limit", 15))

    weather = _fetch_weather(lat, lng)
    now = datetime.now()
    hour = now.hour

    results = []
    for cafe in RAW_CAFES:
        dist = _haversine(lat, lng, cafe["lat"], cafe["lng"])
        if dist > radius: continue
        if not _is_open_now(cafe.get("hours", "")): continue

        tx = _simulate_payone(cafe, hour)
        avg_tx = 12
        demand = "quiet" if tx < 5 else "normal" if tx < 10 else "busy"

        # Dynamic discount: quieter + worse weather = bigger discount
        disc = 8
        if weather.get("is_rainy"): disc += 5
        if weather.get("is_cold"): disc += 3
        if demand == "quiet": disc += 5
        if 14 <= hour <= 17: disc += 3
        disc = min(disc, 25)
        cashback = round(disc * 0.14, 2)

        # Relevance score (higher = better match)
        score = 100 - (dist / radius * 40)  # closer = higher
        if demand == "quiet": score += 20
        if weather.get("is_cold") and not cafe.get("outdoor", False): score += 10
        if weather.get("is_rainy"): score += 15
        if cafe.get("wifi"): score += 5

        copy = _weather_offer_text(weather, cafe, disc)
        offer_id = hashlib.md5(f"{cafe['id']}{now.hour}".encode()).hexdigest()[:8]
        code = f"CW-{offer_id.upper()}"

        results.append({
            "id": offer_id, "code": code,
            "name": cafe["name"],
            "lat": cafe["lat"], "lng": cafe["lng"],
            "street": cafe.get("street",""), "housenumber": cafe.get("housenumber",""),
            "distance_m": int(dist), "walk_min": max(1, int(dist / 80)),
            "hours": cafe.get("hours",""),
            "outdoor": cafe.get("outdoor", False),
            "wifi": cafe.get("wifi", False),
            "cuisine": cafe.get("cuisine","coffee"),
            "website": cafe.get("website",""),
            "phone": cafe.get("phone",""),
            # Generated
            "headline": copy["h"], "subline": copy["s"], "frame": copy["frame"],
            "discount_pct": disc, "cashback": cashback,
            "label": f"{disc}% off",
            "demand": demand, "payone_tx": tx,
            "expiry_min": 20 if demand == "quiet" else 35,
            "score": round(score),
            "maps_url": f"https://www.google.com/maps/dir/?api=1&destination={cafe['lat']},{cafe['lng']}&travelmode=walking",
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:limit]

    return jsonify({
        "offers": results,
        "total_nearby": len(results),
        "radius_m": radius,
        "weather": weather,
        "location": {"lat": lat, "lng": lng},
        "generated_at": now.isoformat(),
    })

import hashlib

# ══════════════════════════════════════════════════════════════════
#  REDEEM + CASHBACK
# ══════════════════════════════════════════════════════════════════

@app.route("/api/redeem", methods=["POST"])
def redeem():
    data = request.get_json(force=True)
    code = data.get("code",""); user_id = data.get("user_id","anon")
    name = data.get("merchant_name","Cafe")
    cashback = float(data.get("cashback", 1.50))

    item_price = round(random.uniform(3.5, 8.5), 2)
    final = round(max(item_price - cashback, 0.5), 2)
    r = {
        "id": str(uuid.uuid4())[:8], "code": code, "merchant": name,
        "item_price": item_price, "cashback": cashback, "final": final,
        "ts": datetime.now().strftime("%H:%M · %d %b"), "status": "completed",
    }
    REDEMPTIONS.append(r)
    CASHBACK[user_id] = CASHBACK.get(user_id, 0) + cashback
    return jsonify(r), 201

@app.route("/api/action", methods=["POST"])
def offer_action():
    data = request.get_json(force=True)
    OFFER_LOG.append({**data, "ts": datetime.now().isoformat()})
    return jsonify({"ok": True})

@app.route("/api/savings", methods=["GET"])
def savings():
    uid = request.args.get("user_id","anon")
    user_redemptions = [r for r in REDEMPTIONS if True]  # All for demo
    total_saved = CASHBACK.get(uid, 0)
    return jsonify({
        "total_saved": round(total_saved, 2),
        "redemption_count": len(user_redemptions),
        "history": user_redemptions[-20:],
        "streak_days": min(len(user_redemptions), 7),
    })

@app.route("/api/qr", methods=["GET"])
def gen_qr():
    text = request.args.get("text","")
    if not text: return jsonify({"error":"need text"}), 400
    try:
        import qrcode
        img = qrcode.make(text, box_size=10, border=2)
        buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        return Response(buf.getvalue(), mimetype="image/png")
    except Exception as e:
        return jsonify({"error":str(e)}), 500

# ══════════════════════════════════════════════════════════════════
#  PUSH NOTIFICATIONS (real Web Push via VAPID)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/vapid-public", methods=["GET"])
def vapid_public():
    return jsonify({"publicKey": VAPID_PUBLIC})

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    """Store a push subscription from a user's browser."""
    data = request.get_json(force=True)
    sub = data.get("subscription", {})
    endpoint = sub.get("endpoint", "")
    if not endpoint: return jsonify({"error": "no endpoint"}), 400
    PUSH_SUBS[endpoint] = {
        "sub": sub, "lat": data.get("lat", 0), "lng": data.get("lng", 0),
        "ts": datetime.now().isoformat(),
    }
    return jsonify({"ok": True, "total_subs": len(PUSH_SUBS)})

@app.route("/api/push/send", methods=["POST"])
def push_send():
    """Merchant triggers a push notification to all subscribed users."""
    data = request.get_json(force=True)
    title = data.get("title", "New offer nearby")
    body = data.get("body", "A deal just appeared")
    offer_id = data.get("offer_id", "")
    merchant_lat = float(data.get("lat", 0))
    merchant_lng = float(data.get("lng", 0))
    radius = float(data.get("radius", 2000))

    sent = 0; failed = 0; dead = []
    for endpoint, info in PUSH_SUBS.items():
        # Distance filter: only notify users within radius of merchant
        if merchant_lat and info.get("lat"):
            d = _haversine(merchant_lat, merchant_lng, info["lat"], info["lng"])
            if d > radius: continue
        try:
            from pywebpush import webpush, WebPushException
            payload = json.dumps({"title": title, "body": body, "offerId": offer_id, "url": "/"})
            webpush(info["sub"], data=payload,
                    vapid_private_key=VAPID_PRIVATE, vapid_claims={"sub": VAPID_EMAIL})
            sent += 1
        except Exception as e:
            failed += 1
            if "410" in str(e) or "404" in str(e): dead.append(endpoint)

    for ep in dead: PUSH_SUBS.pop(ep, None)
    return jsonify({"sent": sent, "failed": failed, "total_subs": len(PUSH_SUBS)})

# ══════════════════════════════════════════════════════════════════
#  MERCHANT: Validate QR code
# ══════════════════════════════════════════════════════════════════

@app.route("/api/verify", methods=["POST"])
def verify_code():
    """Merchant scans a customer's QR — validate and redeem it."""
    data = request.get_json(force=True)
    code = data.get("code", "").strip().upper()
    if not code or not code.startswith("CW-"):
        return jsonify({"valid": False, "error": "Invalid code format"}), 400

    # Check if already redeemed
    for r in REDEMPTIONS:
        if r.get("code", "").upper() == code:
            return jsonify({"valid": False, "error": "Already redeemed", "redeemed_at": r.get("ts","")}), 409

    # Find matching cafe by code hash
    offer_hash = code.replace("CW-", "").lower()
    matched_cafe = None
    now = datetime.now()
    for cafe in RAW_CAFES:
        check = hashlib.md5(f"{cafe['id']}{now.hour}".encode()).hexdigest()[:8].upper()
        if check == offer_hash:
            matched_cafe = cafe; break

    if not matched_cafe:
        # Still valid code structure, just accept it
        matched_cafe = {"name": "Unknown Cafe"}

    # Auto-redeem
    cashback = round(random.uniform(1.0, 3.5), 2)
    item_price = round(random.uniform(3.5, 8.5), 2)
    final = round(max(item_price - cashback, 0.5), 2)
    r = {
        "id": str(uuid.uuid4())[:8], "code": code,
        "merchant": matched_cafe.get("name", "Cafe"),
        "item_price": item_price, "cashback": cashback, "final": final,
        "ts": datetime.now().strftime("%H:%M · %d %b"), "status": "completed",
    }
    REDEMPTIONS.append(r)

    return jsonify({"valid": True, "merchant": matched_cafe.get("name",""), "redemption": r})

# ══════════════════════════════════════════════════════════════════
#  MERCHANT DASHBOARD DATA
# ══════════════════════════════════════════════════════════════════

@app.route("/api/merchant/dashboard", methods=["GET"])
def merchant_dashboard():
    total_rev = sum(r.get("final", 0) for r in REDEMPTIONS)
    total_cb = sum(r.get("cashback", 0) for r in REDEMPTIONS)
    return jsonify({
        "total_redemptions": len(REDEMPTIONS),
        "total_revenue": round(total_rev, 2),
        "total_cashback_given": round(total_cb, 2),
        "active_subscribers": len(PUSH_SUBS),
        "recent": REDEMPTIONS[-10:],
    })

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status":"ok","cafes":len(RAW_CAFES),"version":"5.0","push_subs":len(PUSH_SUBS)})

@app.route("/api/ledger", methods=["GET"])
def ledger():
    return jsonify({"total_revenue":sum(r.get("final",0) for r in REDEMPTIONS),
        "total_cashback":sum(r.get("cashback",0) for r in REDEMPTIONS),
        "total_redemptions":len(REDEMPTIONS),"redemptions":REDEMPTIONS[-20:]})

@app.route("/api/optin", methods=["POST"])
def optin():
    return jsonify({"ok":True})

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]="*"
    r.headers["Access-Control-Allow-Methods"]="GET,POST,OPTIONS"
    r.headers["Access-Control-Allow-Headers"]="Content-Type"
    return r

@app.route("/api/<path:p>", methods=["OPTIONS"])
def opts(p): return "",204
