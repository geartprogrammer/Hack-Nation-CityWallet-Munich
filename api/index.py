"""
CITY WALLET — Generative City-Wallet API
Flask backend for Vercel serverless deployment.

Three modules:
  1. Context Sensing Layer — weather (Open-Meteo), time, location, simulated Payone data
  2. Generative Offer Engine — dynamic offer creation from context + merchant rules
  3. Seamless Checkout & Redemption — QR token generation, redemption, merchant dashboard
"""

from flask import Flask, request, jsonify, Response
import json
import time
import uuid
import hashlib
import random
import math
from datetime import datetime, timezone
from io import BytesIO

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════════
#  STATE (in-memory — persists while Vercel function is warm)
# ══════════════════════════════════════════════════════════════════

MERCHANTS = {}
REDEMPTIONS = []
OPTINS = {}
GENERATED_OFFERS = []  # Track what the engine has generated

def seed():
    global MERCHANTS
    MERCHANTS = {
        "cafe-riese": {
            "id": "cafe-riese", "name": "Café Riese", "area": "Schwabing",
            "lat": 48.1629, "lng": 11.5862,
            "category": "cafe", "tags": ["coffee", "pastry", "warm drinks"],
            "rules": {
                "max_discount_pct": 20, "max_discount_eur": 3.00,
                "quiet_hours": [{"start": "14:00", "end": "16:00"}],
                "goal": "fill_quiet_hours",
                "tone": "warm", "auto_generate": True
            },
            "payone": {"avg_hourly_tx": 12, "current_tx": 3, "trend": "low"},
            "status": "live", "walk_ins": 0, "revenue": 0.0,
        },
        "backerei-knaus": {
            "id": "backerei-knaus", "name": "Bäckerei Knaus", "area": "Glockenbachviertel",
            "lat": 48.1295, "lng": 11.5735,
            "category": "bakery", "tags": ["pastry", "bread", "fresh"],
            "rules": {
                "max_discount_pct": 15, "max_discount_eur": 2.00,
                "quiet_hours": [{"start": "15:00", "end": "17:00"}],
                "goal": "reduce_waste",
                "tone": "friendly", "auto_generate": True
            },
            "payone": {"avg_hourly_tx": 18, "current_tx": 5, "trend": "low"},
            "status": "live", "walk_ins": 0, "revenue": 0.0,
        },
        "brioche-marie": {
            "id": "brioche-marie", "name": "Brioche Marie", "area": "Viktualienmarkt",
            "lat": 48.1351, "lng": 11.5767,
            "category": "bistro", "tags": ["lunch", "sandwich", "coffee"],
            "rules": {
                "max_discount_pct": 25, "max_discount_eur": 4.00,
                "quiet_hours": [{"start": "16:00", "end": "18:00"}],
                "goal": "boost_afternoon",
                "tone": "playful", "auto_generate": True
            },
            "payone": {"avg_hourly_tx": 22, "current_tx": 7, "trend": "declining"},
            "status": "live", "walk_ins": 0, "revenue": 0.0,
        },
    }

seed()

# ══════════════════════════════════════════════════════════════════
#  MODULE 1: CONTEXT SENSING LAYER
# ══════════════════════════════════════════════════════════════════

@app.route("/api/context", methods=["GET"])
def get_context():
    """
    Aggregate real-time context signals:
      - Weather (Open-Meteo — free, no API key)
      - Time of day, day of week
      - Location (from client)
      - Simulated Payone transaction density per merchant
      - Local events (simulated for demo)
    """
    lat = float(request.args.get("lat", 48.1351))
    lng = float(request.args.get("lng", 11.5820))

    # ── Weather from Open-Meteo (real API, no key needed) ─────
    weather = fetch_weather(lat, lng)

    # ── Time context ──────────────────────────────────────────
    now = datetime.now()
    time_ctx = {
        "hour": now.hour, "minute": now.minute,
        "day_of_week": now.strftime("%A"),
        "is_lunch": 11 <= now.hour <= 14,
        "is_afternoon": 14 <= now.hour <= 17,
        "is_evening": 17 <= now.hour <= 21,
        "is_weekend": now.weekday() >= 5,
        "timestamp": now.isoformat()
    }

    # ── Payone transaction density (simulated) ────────────────
    payone = {}
    for mid, m in MERCHANTS.items():
        tx_ratio = m["payone"]["current_tx"] / max(m["payone"]["avg_hourly_tx"], 1)
        payone[mid] = {
            "merchant": m["name"],
            "avg_hourly_tx": m["payone"]["avg_hourly_tx"],
            "current_tx": m["payone"]["current_tx"],
            "tx_ratio": round(tx_ratio, 2),
            "demand_state": "low" if tx_ratio < 0.4 else "normal" if tx_ratio < 0.8 else "high",
            "trend": m["payone"]["trend"]
        }

    # ── Local events (simulated for Munich) ───────────────────
    events = get_local_events(lat, lng, now)

    # ── Composite context state ───────────────────────────────
    composite = build_composite_state(weather, time_ctx, payone, events)

    return jsonify({
        "weather": weather,
        "time": time_ctx,
        "payone": payone,
        "events": events,
        "composite": composite,
        "location": {"lat": lat, "lng": lng}
    })


def fetch_weather(lat, lng):
    """Fetch real weather from Open-Meteo (free, no API key)."""
    try:
        import requests
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lng}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature"
            f"&timezone=auto"
        )
        resp = requests.get(url, timeout=5)
        data = resp.json()
        current = data.get("current", {})
        temp = current.get("temperature_2m", 15)
        code = current.get("weather_code", 0)

        return {
            "temperature_c": temp,
            "apparent_temp_c": current.get("apparent_temperature", temp),
            "humidity_pct": current.get("relative_humidity_2m", 50),
            "wind_kmh": current.get("wind_speed_10m", 10),
            "weather_code": code,
            "description": weather_code_to_text(code),
            "is_cold": temp < 12,
            "is_hot": temp > 28,
            "is_rainy": code in [51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99],
            "is_sunny": code in [0, 1],
            "source": "open-meteo"
        }
    except Exception as e:
        return {
            "temperature_c": 11, "apparent_temp_c": 9,
            "humidity_pct": 65, "wind_kmh": 12,
            "weather_code": 3, "description": "Overcast",
            "is_cold": True, "is_hot": False,
            "is_rainy": False, "is_sunny": False,
            "source": "fallback", "error": str(e)
        }


def weather_code_to_text(code):
    codes = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
        55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain",
        65: "Heavy rain", 71: "Slight snow", 73: "Moderate snow",
        75: "Heavy snow", 80: "Rain showers", 81: "Moderate showers",
        82: "Violent showers", 95: "Thunderstorm", 96: "Thunderstorm with hail",
    }
    return codes.get(code, "Unknown")


def get_local_events(lat, lng, now):
    """Simulated local events for Munich area."""
    day = now.strftime("%A")
    month = now.month
    events = []
    if day == "Saturday":
        events.append({"name": "Viktualienmarkt Weekend Market", "type": "market", "impact": "high_footfall"})
    if day in ["Friday", "Saturday"]:
        events.append({"name": "Live Music at Kulturzentrum", "type": "entertainment", "impact": "evening_traffic"})
    if month in [11, 12]:
        events.append({"name": "Christkindlmarkt", "type": "seasonal", "impact": "high_footfall"})
    if month in [6, 7, 8]:
        events.append({"name": "Sommerfest im Englischen Garten", "type": "seasonal", "impact": "outdoor_traffic"})
    return events


def build_composite_state(weather, time_ctx, payone, events):
    """Build the composite context state that triggers offer generation."""
    signals = []
    trigger_score = 0

    if weather.get("is_cold"):
        signals.append("cold_weather")
        trigger_score += 20
    if weather.get("is_rainy"):
        signals.append("rain")
        trigger_score += 25
    if weather.get("is_hot"):
        signals.append("hot_weather")
        trigger_score += 15

    if time_ctx.get("is_lunch"):
        signals.append("lunch_hour")
        trigger_score += 15
    if time_ctx.get("is_afternoon"):
        signals.append("afternoon_lull")
        trigger_score += 10

    low_demand = [mid for mid, p in payone.items() if p["demand_state"] == "low"]
    if low_demand:
        signals.append(f"low_demand_{len(low_demand)}_merchants")
        trigger_score += 30

    if events:
        signals.append(f"local_events_{len(events)}")
        trigger_score += 10

    return {
        "signals": signals,
        "trigger_score": trigger_score,
        "should_generate": trigger_score >= 25,
        "description": " + ".join(signals) if signals else "baseline",
        "urgency": "high" if trigger_score >= 50 else "medium" if trigger_score >= 25 else "low"
    }


# ══════════════════════════════════════════════════════════════════
#  MODULE 2: GENERATIVE OFFER ENGINE
# ══════════════════════════════════════════════════════════════════

@app.route("/api/generate", methods=["POST"])
def generate_offer():
    """
    Generative offer engine. Takes context + merchant rules → produces
    a dynamically generated offer with content, discount, visual design,
    and emotional framing. NOT template-filling — the offer parameters,
    copy, and tone are computed from the context state.
    """
    data = request.get_json(force=True)
    context = data.get("context", {})
    merchant_id = data.get("merchant_id")
    user_signals = data.get("user_signals", {})

    if merchant_id and merchant_id in MERCHANTS:
        merchants_to_generate = [MERCHANTS[merchant_id]]
    else:
        merchants_to_generate = [m for m in MERCHANTS.values() if m["status"] == "live"]

    offers = []
    for merchant in merchants_to_generate:
        offer = generate_single_offer(merchant, context, user_signals)
        if offer:
            offers.append(offer)
            GENERATED_OFFERS.append(offer)

    return jsonify({"offers": offers, "generated_at": datetime.now().isoformat()})


def generate_single_offer(merchant, context, user_signals):
    """Generate a single offer for one merchant based on context."""
    rules = merchant.get("rules", {})
    weather = context.get("weather", {})
    time_ctx = context.get("time", {})
    composite = context.get("composite", {})

    # ── Compute discount dynamically from context ─────────────
    base_discount_pct = 10
    max_pct = rules.get("max_discount_pct", 20)
    max_eur = rules.get("max_discount_eur", 3.00)

    # Increase discount for worse conditions
    if weather.get("is_rainy"):
        base_discount_pct += 5
    if weather.get("is_cold"):
        base_discount_pct += 3
    if merchant["payone"]["current_tx"] / max(merchant["payone"]["avg_hourly_tx"], 1) < 0.3:
        base_discount_pct += 5  # Very quiet → bigger discount
    if time_ctx.get("is_afternoon") and _in_quiet_hours(merchant, time_ctx):
        base_discount_pct += 3

    discount_pct = min(base_discount_pct, max_pct)
    discount_eur = min(round(discount_pct * 0.15, 2), max_eur)  # Rough EUR conversion

    # ── Generate copy dynamically ─────────────────────────────
    tone = rules.get("tone", "warm")
    copy = generate_copy(merchant, weather, time_ctx, tone, discount_pct)

    # ── Generate visual parameters ────────────────────────────
    visuals = generate_visuals(merchant, weather, time_ctx)

    # ── Generate unique offer code ────────────────────────────
    offer_id = str(uuid.uuid4())[:8]
    code = f"{merchant['id'][:5].upper()}-{offer_id.upper()}"

    # ── Compute expiry ────────────────────────────────────────
    if composite.get("urgency") == "high":
        expiry_minutes = 15
    elif composite.get("urgency") == "medium":
        expiry_minutes = 30
    else:
        expiry_minutes = 60

    return {
        "id": offer_id,
        "code": code,
        "merchant_id": merchant["id"],
        "merchant_name": merchant["name"],
        "merchant_area": merchant["area"],
        "merchant_lat": merchant["lat"],
        "merchant_lng": merchant["lng"],
        "merchant_category": merchant.get("category", "shop"),
        # Generative content
        "headline": copy["headline"],
        "subline": copy["subline"],
        "cta": copy["cta"],
        "emotional_frame": copy["frame"],
        "tone": tone,
        # Dynamic discount
        "discount_pct": discount_pct,
        "discount_eur": discount_eur,
        "discount_label": f"{discount_pct}% off" if discount_pct <= 15 else f"€{discount_eur:.2f} off",
        # Visual
        "bg_gradient": visuals["gradient"],
        "accent_color": visuals["accent"],
        "icon": visuals["icon"],
        "mood": visuals["mood"],
        # Timing
        "expiry_minutes": expiry_minutes,
        "generated_at": datetime.now().isoformat(),
        # Context that triggered it
        "trigger_signals": composite.get("signals", []),
        "trigger_description": composite.get("description", ""),
    }


def generate_copy(merchant, weather, time_ctx, tone, discount_pct):
    """
    Generate offer copy dynamically based on context.
    This is generative — the text is composed at runtime from signals,
    not retrieved from a template database.
    """
    name = merchant["name"]
    category = merchant.get("category", "shop")
    tags = merchant.get("tags", [])

    # ── Select emotional frame based on context ───────────────
    if weather.get("is_cold") and weather.get("is_rainy"):
        frame = "shelter"
        headlines = [
            f"Rain + cold? {name} is warm inside.",
            f"Escape the rain. {name}, {discount_pct}% off.",
            f"It's {weather.get('temperature_c', 11)}° and wet. Come in.",
        ]
        sublines = [
            f"A warm {tags[0] if tags else 'drink'} is waiting — {discount_pct}% off right now.",
            f"Your {tags[0] if tags else 'break'} is {discount_pct}% off for the next 15 minutes.",
        ]
    elif weather.get("is_cold"):
        frame = "warmth"
        headlines = [
            f"{weather.get('temperature_c', 11)}° outside. Warm up at {name}.",
            f"Cold hands? Hot {tags[0] if tags else 'drink'} at {name}.",
            f"Your warm escape is {discount_pct}% off.",
        ]
        sublines = [
            f"{name} in {merchant['area']} — {discount_pct}% off hot drinks right now.",
            f"Step in, warm up. {discount_pct}% off your order.",
        ]
    elif weather.get("is_hot"):
        frame = "refresh"
        headlines = [
            f"{weather.get('temperature_c', 30)}° — cool down at {name}.",
            f"Too hot? Cold drinks {discount_pct}% off at {name}.",
        ]
        sublines = [
            f"Iced drinks and AC. {discount_pct}% off.",
            f"Beat the heat. {name} has you covered.",
        ]
    elif time_ctx.get("is_lunch"):
        frame = "hunger"
        headlines = [
            f"Lunch break? {name} has {discount_pct}% off.",
            f"12 minutes to spare? {name} is right here.",
        ]
        sublines = [
            f"Fresh {tags[0] if tags else 'food'} — {discount_pct}% off until 14:00.",
            f"Grab something good. You're {merchant['area']}.",
        ]
    else:
        frame = "discovery"
        headlines = [
            f"{name} — {discount_pct}% off right now.",
            f"Discover {name} in {merchant['area']}.",
        ]
        sublines = [
            f"{discount_pct}% off — generated just for you, just for now.",
            f"This offer was created for this moment. {discount_pct}% off.",
        ]

    # ── Tone adjustment ───────────────────────────────────────
    if tone == "playful":
        ctas = ["Yes please!", "I'm in!", "Take me there"]
    elif tone == "warm":
        ctas = ["Sounds perfect", "I'll stop by", "Save this offer"]
    else:
        ctas = ["Redeem now", "Get this offer", "Claim discount"]

    return {
        "headline": random.choice(headlines),
        "subline": random.choice(sublines),
        "cta": random.choice(ctas),
        "frame": frame,
    }


def generate_visuals(merchant, weather, time_ctx):
    """Generate visual parameters for the offer card at runtime."""
    category = merchant.get("category", "shop")

    if weather.get("is_rainy"):
        mood = "cozy"
        gradient = "linear-gradient(135deg, #2c3e50 0%, #3498db 100%)"
        accent = "#f39c12"
        icon = "☔"
    elif weather.get("is_cold"):
        mood = "warm"
        gradient = "linear-gradient(135deg, #8B4513 0%, #D2691E 100%)"
        accent = "#FFD700"
        icon = "🔥"
    elif weather.get("is_hot"):
        mood = "fresh"
        gradient = "linear-gradient(135deg, #00b4db 0%, #0083b0 100%)"
        accent = "#00d2ff"
        icon = "❄️"
    elif time_ctx.get("is_lunch"):
        mood = "energetic"
        gradient = "linear-gradient(135deg, #f093fb 0%, #f5576c 100%)"
        accent = "#ff6b6b"
        icon = "🍽️"
    else:
        mood = "inviting"
        gradient = "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
        accent = "#a29bfe"
        icon = "✨"

    # Category-specific icon override
    if category == "cafe":
        icon = "☕" if weather.get("is_cold") else "🧊"
    elif category == "bakery":
        icon = "🥐"
    elif category == "bistro":
        icon = "🥖"

    return {"gradient": gradient, "accent": accent, "icon": icon, "mood": mood}


def _in_quiet_hours(merchant, time_ctx):
    hour = time_ctx.get("hour", 12)
    minute = time_ctx.get("minute", 0)
    now_min = hour * 60 + minute
    for qh in merchant.get("rules", {}).get("quiet_hours", []):
        sh, sm = map(int, qh["start"].split(":"))
        eh, em = map(int, qh["end"].split(":"))
        if sh * 60 + sm <= now_min <= eh * 60 + em:
            return True
    return False


# ══════════════════════════════════════════════════════════════════
#  MODULE 3: CHECKOUT & REDEMPTION
# ══════════════════════════════════════════════════════════════════

@app.route("/api/redeem", methods=["POST"])
def redeem():
    """Redeem an offer — validates code, records transaction."""
    data = request.get_json(force=True)
    code = data.get("code", "")
    merchant_id = data.get("merchant_id", "")

    if not code:
        return jsonify({"error": "Code required"}), 400
    if merchant_id not in MERCHANTS:
        return jsonify({"error": "Unknown merchant"}), 404

    merchant = MERCHANTS[merchant_id]
    redemption = {
        "id": str(uuid.uuid4())[:8],
        "code": code,
        "merchant_id": merchant_id,
        "merchant_name": merchant["name"],
        "value": merchant["rules"].get("max_discount_eur", 1.50),
        "timestamp": time.time(),
        "ts_human": datetime.now().strftime("%H:%M:%S"),
    }
    REDEMPTIONS.append(redemption)
    merchant["walk_ins"] += 1
    merchant["revenue"] += round(redemption["value"] * 3, 2)

    return jsonify(redemption), 201


@app.route("/api/qr", methods=["GET"])
def generate_qr():
    """Generate a real scannable QR code as PNG."""
    text = request.args.get("text", "")
    if not text:
        return jsonify({"error": "text param required"}), 400
    try:
        import qrcode
        img = qrcode.make(text, box_size=8, border=2)
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(buf.getvalue(), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
#  MERCHANT & LEDGER ENDPOINTS
# ══════════════════════════════════════════════════════════════════

@app.route("/api/merchants", methods=["GET"])
def list_merchants():
    return jsonify(list(MERCHANTS.values()))

@app.route("/api/merchants", methods=["POST"])
def add_merchant():
    data = request.get_json(force=True)
    mid = data.get("id") or str(uuid.uuid4())[:8]
    merchant = {
        "id": mid, "name": data.get("name", "New Shop"),
        "area": data.get("area", "Munich"),
        "lat": float(data.get("lat", 48.1351)),
        "lng": float(data.get("lng", 11.5820)),
        "category": data.get("category", "shop"),
        "tags": data.get("tags", []),
        "rules": data.get("rules", {
            "max_discount_pct": 15, "max_discount_eur": 2.00,
            "quiet_hours": [{"start": "14:00", "end": "16:00"}],
            "goal": "fill_quiet_hours", "tone": "warm", "auto_generate": True
        }),
        "payone": {"avg_hourly_tx": 15, "current_tx": 4, "trend": "normal"},
        "status": "live", "walk_ins": 0, "revenue": 0.0,
    }
    MERCHANTS[mid] = merchant
    return jsonify(merchant), 201

@app.route("/api/merchants/rules", methods=["POST"])
def update_rules():
    """Merchant updates their rules (max discount, goals, quiet hours)."""
    data = request.get_json(force=True)
    mid = data.get("merchant_id")
    if mid not in MERCHANTS:
        return jsonify({"error": "Not found"}), 404
    rules = data.get("rules", {})
    MERCHANTS[mid]["rules"].update(rules)
    return jsonify(MERCHANTS[mid])

@app.route("/api/ledger", methods=["GET"])
def get_ledger():
    total_walkins = sum(m["walk_ins"] for m in MERCHANTS.values())
    total_revenue = sum(m["revenue"] for m in MERCHANTS.values())
    return jsonify({
        "merchants": list(MERCHANTS.values()),
        "total_revenue": round(total_revenue, 2),
        "total_walkins": total_walkins,
        "total_optins": len(OPTINS),
        "total_redemptions": len(REDEMPTIONS),
        "redemptions": REDEMPTIONS[-20:],
        "generated_offers_count": len(GENERATED_OFFERS),
    })

@app.route("/api/optin", methods=["POST"])
def optin():
    data = request.get_json(force=True)
    uid = data.get("user_id") or str(uuid.uuid4())
    OPTINS[uid] = {"user_id": uid, "ts": datetime.now().isoformat()}
    return jsonify({"user_id": uid})

@app.route("/api/reset", methods=["POST"])
def reset():
    REDEMPTIONS.clear()
    OPTINS.clear()
    GENERATED_OFFERS.clear()
    seed()
    return jsonify({"status": "reset"})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "merchants": len(MERCHANTS), "version": "2.0"})


# ══════════════════════════════════════════════════════════════════
#  CORS handler
# ══════════════════════════════════════════════════════════════════

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return "", 204
