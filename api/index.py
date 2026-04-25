"""
CITY WALLET — Generative City-Wallet API (Full Challenge Implementation)
Flask backend for Vercel serverless deployment.

MODULE 1: Context Sensing Layer
  - Real weather from Open-Meteo (temp, UV, AQI, feels-like, sunrise/sunset)
  - Configurable city — swap city via query param, no code change
  - Payone transaction density simulation (varies by hour realistically)
  - Local events from public APIs + simulation
  - Composite context state with trigger scoring

MODULE 2: Generative Offer Engine
  - Dynamic offer generation from context + merchant rules
  - Emotional framing (shelter, warmth, hunger, discovery, refresh)
  - GenUI visual parameters computed at runtime
  - On-device intent signal architecture (privacy-first)
  - Merchant rule interface (max discount, goals, quiet hours, tone)

MODULE 3: Seamless Checkout & Redemption
  - QR code / token generation
  - Simulated checkout with cashback mechanic
  - Accept/decline tracking with rates
  - Merchant dashboard with analytics
"""

from flask import Flask, request, jsonify, Response
import json, time, uuid, hashlib, random, math
from datetime import datetime, timezone
from io import BytesIO

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════════════════

MERCHANTS = {}
REDEMPTIONS = []
OPTINS = {}
GENERATED_OFFERS = []
OFFER_ACTIONS = []  # {offer_id, action: accept|decline|expire, ts}
CASHBACK_LEDGER = []  # {user_id, amount, merchant_id, ts}

# ── Configurable city presets (swap city without code changes) ────
CITY_CONFIGS = {
    "munich": {
        "name": "Munich", "country": "DE", "tz": "Europe/Berlin",
        "center_lat": 48.1351, "center_lng": 11.5820,
        "events_keywords": ["Oktoberfest", "Christkindlmarkt", "FC Bayern", "Viktualienmarkt"],
    },
    "stuttgart": {
        "name": "Stuttgart", "country": "DE", "tz": "Europe/Berlin",
        "center_lat": 48.7758, "center_lng": 9.1829,
        "events_keywords": ["Cannstatter Volksfest", "Stuttgart Wine Village", "VfB Stuttgart"],
    },
    "berlin": {
        "name": "Berlin", "country": "DE", "tz": "Europe/Berlin",
        "center_lat": 52.5200, "center_lng": 13.4050,
        "events_keywords": ["Berlin Festival of Lights", "Berlinale", "Hertha BSC"],
    },
    "hamburg": {
        "name": "Hamburg", "country": "DE", "tz": "Europe/Berlin",
        "center_lat": 53.5511, "center_lng": 9.9937,
        "events_keywords": ["Hafengeburtstag", "Dom Festival", "HSV"],
    },
}

def seed():
    global MERCHANTS
    MERCHANTS = {
        "cafe-riese": {
            "id": "cafe-riese", "name": "Café Riese", "area": "Schwabing",
            "lat": 48.1629, "lng": 11.5862,
            "category": "cafe", "tags": ["coffee", "pastry", "warm drinks"],
            "description": "Cozy corner café with fresh roasts and homemade pastries.",
            "rules": {
                "max_discount_pct": 20, "max_discount_eur": 3.00,
                "quiet_hours": [{"start": "14:00", "end": "16:00"}],
                "goal": "fill_quiet_hours",
                "tone": "warm", "auto_generate": True
            },
            "payone": {"avg_hourly_tx": 12, "peak_hours": [8,9,10,12,13], "base_tx": 3},
            "status": "live", "walk_ins": 0, "revenue": 0.0,
            "stats": {"offers_generated": 0, "offers_accepted": 0, "offers_declined": 0, "cashback_total": 0},
        },
        "backerei-knaus": {
            "id": "backerei-knaus", "name": "Bäckerei Knaus", "area": "Glockenbachviertel",
            "lat": 48.1295, "lng": 11.5735,
            "category": "bakery", "tags": ["pastry", "bread", "fresh"],
            "description": "Traditional German bakery. Fresh bread every morning, pastries all day.",
            "rules": {
                "max_discount_pct": 15, "max_discount_eur": 2.00,
                "quiet_hours": [{"start": "15:00", "end": "17:00"}],
                "goal": "reduce_waste",
                "tone": "friendly", "auto_generate": True
            },
            "payone": {"avg_hourly_tx": 18, "peak_hours": [7,8,9,12,13], "base_tx": 4},
            "status": "live", "walk_ins": 0, "revenue": 0.0,
            "stats": {"offers_generated": 0, "offers_accepted": 0, "offers_declined": 0, "cashback_total": 0},
        },
        "brioche-marie": {
            "id": "brioche-marie", "name": "Brioche Marie", "area": "Viktualienmarkt",
            "lat": 48.1351, "lng": 11.5767,
            "category": "bistro", "tags": ["lunch", "sandwich", "coffee"],
            "description": "French-inspired bistro near the market. Great lunch sets and coffee.",
            "rules": {
                "max_discount_pct": 25, "max_discount_eur": 4.00,
                "quiet_hours": [{"start": "15:00", "end": "17:30"}],
                "goal": "boost_afternoon",
                "tone": "playful", "auto_generate": True
            },
            "payone": {"avg_hourly_tx": 22, "peak_hours": [11,12,13,14,18,19], "base_tx": 5},
            "status": "live", "walk_ins": 0, "revenue": 0.0,
            "stats": {"offers_generated": 0, "offers_accepted": 0, "offers_declined": 0, "cashback_total": 0},
        },
    }
seed()

# ══════════════════════════════════════════════════════════════════
#  MODULE 1: CONTEXT SENSING LAYER
#  - Configurable city (query param ?city=munich|stuttgart|berlin)
#  - Real weather, UV, AQI from Open-Meteo
#  - Payone tx density varying by hour
#  - Event detection
# ══════════════════════════════════════════════════════════════════

@app.route("/api/context", methods=["GET"])
def get_context():
    lat = float(request.args.get("lat", 48.1351))
    lng = float(request.args.get("lng", 11.5820))
    city_key = request.args.get("city", "munich")
    city = CITY_CONFIGS.get(city_key, CITY_CONFIGS["munich"])

    weather = fetch_weather(lat, lng)
    now = datetime.now()
    time_ctx = {
        "hour": now.hour, "minute": now.minute,
        "day_of_week": now.strftime("%A"),
        "date": now.strftime("%Y-%m-%d"),
        "is_morning": 6 <= now.hour <= 10,
        "is_lunch": 11 <= now.hour <= 14,
        "is_afternoon": 14 <= now.hour <= 17,
        "is_evening": 17 <= now.hour <= 21,
        "is_night": now.hour >= 21 or now.hour < 6,
        "is_weekend": now.weekday() >= 5,
        "timestamp": now.isoformat()
    }

    # Payone: realistic hourly simulation
    payone = {}
    for mid, m in MERCHANTS.items():
        current_tx = _simulate_payone(m, now.hour, time_ctx["is_weekend"])
        avg = m["payone"]["avg_hourly_tx"]
        ratio = current_tx / max(avg, 1)
        payone[mid] = {
            "merchant": m["name"],
            "avg_hourly_tx": avg,
            "current_tx": current_tx,
            "tx_ratio": round(ratio, 2),
            "demand_state": "very_low" if ratio < 0.25 else "low" if ratio < 0.5 else "normal" if ratio < 0.85 else "busy",
            "trend": "declining" if current_tx < avg * 0.4 else "rising" if current_tx > avg * 0.9 else "stable",
            "quiet_period": ratio < 0.5,
        }

    events = get_local_events(lat, lng, now, city)
    composite = build_composite_state(weather, time_ctx, payone, events)

    return jsonify({
        "city": city["name"],
        "weather": weather,
        "time": time_ctx,
        "payone": payone,
        "events": events,
        "composite": composite,
        "location": {"lat": lat, "lng": lng},
        "config": {"city_key": city_key, "available_cities": list(CITY_CONFIGS.keys())},
    })


def _simulate_payone(merchant, hour, is_weekend):
    """Simulate realistic Payone transaction density that varies by hour."""
    base = merchant["payone"]["base_tx"]
    peak_hours = merchant["payone"]["peak_hours"]
    avg = merchant["payone"]["avg_hourly_tx"]
    if hour in peak_hours:
        tx = avg + random.randint(-2, 4)
    elif abs(hour - min(peak_hours, key=lambda h: abs(h - hour))) <= 1:
        tx = int(avg * 0.7) + random.randint(-1, 2)
    else:
        tx = base + random.randint(0, 3)
    if is_weekend:
        tx = int(tx * 1.2)
    return max(1, tx)


def fetch_weather(lat, lng):
    try:
        import requests
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lng}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,"
            f"apparent_temperature,is_day,cloud_cover,precipitation"
            f"&daily=sunrise,sunset,uv_index_max"
            f"&timezone=auto&forecast_days=1"
        )
        resp = requests.get(url, timeout=5)
        data = resp.json()
        current = data.get("current", {})
        daily = data.get("daily", {})
        temp = current.get("temperature_2m", 15)
        feels = current.get("apparent_temperature", temp)
        code = current.get("weather_code", 0)
        precip = current.get("precipitation", 0)

        aqi_data = {"european_aqi": 15, "aqi_label": "Good"}
        try:
            aqi_resp = requests.get(
                f"https://air-quality-api.open-meteo.com/v1/air-quality"
                f"?latitude={lat}&longitude={lng}&current=european_aqi,pm2_5,pm10",
                timeout=3
            )
            aq = aqi_resp.json().get("current", {})
            val = aq.get("european_aqi", 0)
            aqi_data = {
                "european_aqi": val, "pm2_5": aq.get("pm2_5", 0), "pm10": aq.get("pm10", 0),
                "aqi_label": "Good" if val < 20 else "Fair" if val < 40 else "Moderate" if val < 60 else "Poor",
            }
        except Exception:
            pass

        sunrise = daily.get("sunrise", [""])[0] if daily.get("sunrise") else ""
        sunset = daily.get("sunset", [""])[0] if daily.get("sunset") else ""
        uv_max = daily.get("uv_index_max", [0])[0] if daily.get("uv_index_max") else 0

        return {
            "temperature_c": temp, "apparent_temp_c": feels,
            "humidity_pct": current.get("relative_humidity_2m", 50),
            "wind_kmh": current.get("wind_speed_10m", 10),
            "cloud_cover_pct": current.get("cloud_cover", 50),
            "precipitation_mm": precip,
            "is_day": current.get("is_day", 1) == 1,
            "weather_code": code,
            "description": weather_code_to_text(code),
            "is_cold": temp < 12, "is_hot": temp > 28, "is_mild": 12 <= temp <= 22,
            "is_rainy": code in [51,53,55,61,63,65,71,73,75,80,81,82,95,96,99] or precip > 0,
            "is_sunny": code in [0, 1], "is_cloudy": code in [2, 3],
            "feels_like_label": f"Feels like {feels}°" if abs(feels - temp) > 2 else "",
            "uv_index": uv_max,
            "uv_label": "Low" if uv_max < 3 else "Moderate" if uv_max < 6 else "High" if uv_max < 8 else "Very high",
            "sunrise": sunrise.split("T")[1] if "T" in str(sunrise) else "",
            "sunset": sunset.split("T")[1] if "T" in str(sunset) else "",
            "air_quality": aqi_data,
            "source": "open-meteo",
        }
    except Exception as e:
        return {
            "temperature_c": 11, "apparent_temp_c": 9, "humidity_pct": 65, "wind_kmh": 12,
            "weather_code": 3, "description": "Overcast",
            "is_cold": True, "is_hot": False, "is_mild": False,
            "is_rainy": False, "is_sunny": False, "is_cloudy": True,
            "uv_index": 2, "uv_label": "Low",
            "air_quality": {"european_aqi": 15, "aqi_label": "Good"},
            "source": "fallback", "error": str(e),
        }


def weather_code_to_text(code):
    return {
        0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",
        45:"Foggy",48:"Rime fog",51:"Light drizzle",53:"Drizzle",55:"Dense drizzle",
        61:"Slight rain",63:"Moderate rain",65:"Heavy rain",
        71:"Slight snow",73:"Moderate snow",75:"Heavy snow",
        80:"Rain showers",81:"Moderate showers",82:"Violent showers",
        95:"Thunderstorm",96:"Thunderstorm with hail",
    }.get(code, "Unknown")


def get_local_events(lat, lng, now, city):
    """Events from city config + time-based simulation. Configurable per city."""
    events = []
    day = now.strftime("%A")
    month = now.month
    hour = now.hour
    keywords = city.get("events_keywords", [])

    # Time-based events
    if day == "Saturday":
        events.append({"name": f"{city['name']} Weekend Market", "type": "market", "impact": "high_footfall", "source": "city_calendar"})
    if day in ["Friday", "Saturday"] and hour >= 17:
        events.append({"name": "Live Music Evening", "type": "entertainment", "impact": "evening_traffic", "source": "city_calendar"})
    if month in [11, 12] and any("Christkindl" in k or "Weihnacht" in k for k in keywords):
        events.append({"name": "Christkindlmarkt", "type": "seasonal", "impact": "high_footfall", "source": "city_calendar"})
    if month in [6, 7, 8]:
        events.append({"name": f"Summer in {city['name']}", "type": "seasonal", "impact": "outdoor_traffic", "source": "city_calendar"})
    if day == "Tuesday" and 11 <= hour <= 14:
        events.append({"name": "Tuesday Lunch Rush", "type": "routine", "impact": "lunch_demand", "source": "pattern_detection"})

    # City-specific
    if "Oktoberfest" in keywords and month in [9, 10]:
        events.append({"name": "Oktoberfest", "type": "major_event", "impact": "massive_footfall", "source": "city_calendar"})
    if "Cannstatter" in str(keywords) and month in [9, 10]:
        events.append({"name": "Cannstatter Volksfest", "type": "major_event", "impact": "massive_footfall", "source": "city_calendar"})

    return events


def build_composite_state(weather, time_ctx, payone, events):
    signals = []
    trigger_score = 0

    if weather.get("is_cold"):
        signals.append("cold_weather"); trigger_score += 20
    if weather.get("is_rainy"):
        signals.append("rain"); trigger_score += 25
    if weather.get("is_hot"):
        signals.append("hot_weather"); trigger_score += 15
    if weather.get("is_sunny") and weather.get("is_mild"):
        signals.append("pleasant_weather"); trigger_score += 5

    if time_ctx.get("is_lunch"):
        signals.append("lunch_hour"); trigger_score += 15
    elif time_ctx.get("is_afternoon"):
        signals.append("afternoon_lull"); trigger_score += 10
    elif time_ctx.get("is_evening"):
        signals.append("evening"); trigger_score += 8
    elif time_ctx.get("is_morning"):
        signals.append("morning"); trigger_score += 5
    if time_ctx.get("is_weekend"):
        signals.append("weekend"); trigger_score += 5

    very_low = [mid for mid, p in payone.items() if p["demand_state"] == "very_low"]
    low = [mid for mid, p in payone.items() if p["demand_state"] == "low"]
    if very_low:
        signals.append(f"very_low_demand_{len(very_low)}_merchants"); trigger_score += 35
    elif low:
        signals.append(f"low_demand_{len(low)}_merchants"); trigger_score += 25

    if events:
        signals.append(f"events_{len(events)}"); trigger_score += 10

    # Mia scenario detection
    mia_scenario = False
    if weather.get("is_cold") and any(p.get("quiet_period") for p in payone.values()):
        mia_scenario = True
        signals.append("mia_scenario_active")
        trigger_score += 15

    return {
        "signals": signals,
        "trigger_score": trigger_score,
        "should_generate": trigger_score >= 20,
        "description": " + ".join(signals) if signals else "baseline",
        "urgency": "high" if trigger_score >= 50 else "medium" if trigger_score >= 25 else "low",
        "mia_scenario": mia_scenario,
    }


# ══════════════════════════════════════════════════════════════════
#  MODULE 2: GENERATIVE OFFER ENGINE
# ══════════════════════════════════════════════════════════════════

@app.route("/api/generate", methods=["POST"])
def generate_offer():
    data = request.get_json(force=True)
    context = data.get("context", {})
    merchant_id = data.get("merchant_id")
    user_signals = data.get("user_signals", {})
    # On-device intent (privacy: only abstract signal, no raw location data)
    intent = data.get("intent", {})  # e.g. {"browsing": true, "hungry": false}

    if merchant_id and merchant_id in MERCHANTS:
        targets = [MERCHANTS[merchant_id]]
    else:
        targets = [m for m in MERCHANTS.values() if m["status"] == "live"]

    offers = []
    for merchant in targets:
        offer = _generate_single(merchant, context, user_signals, intent)
        if offer:
            offers.append(offer)
            GENERATED_OFFERS.append(offer)
            merchant["stats"]["offers_generated"] += 1

    return jsonify({"offers": offers, "generated_at": datetime.now().isoformat(),
                     "intent_received": bool(intent), "privacy": "on-device intent only"})


def _generate_single(merchant, context, user_signals, intent):
    rules = merchant.get("rules", {})
    weather = context.get("weather", {})
    time_ctx = context.get("time", {})
    composite = context.get("composite", {})
    payone_data = context.get("payone", {}).get(merchant["id"], {})

    # ── Dynamic discount from context + rules ─────────────────
    base = 8
    max_pct = rules.get("max_discount_pct", 20)
    max_eur = rules.get("max_discount_eur", 3.00)
    if weather.get("is_rainy"): base += 5
    if weather.get("is_cold"): base += 3
    if payone_data.get("demand_state") == "very_low": base += 7
    elif payone_data.get("demand_state") == "low": base += 4
    if _in_quiet_hours(merchant, time_ctx): base += 3
    if intent.get("browsing"): base += 2
    if composite.get("mia_scenario"): base += 3
    discount_pct = min(base, max_pct)
    discount_eur = min(round(discount_pct * 0.15, 2), max_eur)

    # ── Generative copy ───────────────────────────────────────
    tone = rules.get("tone", "warm")
    copy = _gen_copy(merchant, weather, time_ctx, tone, discount_pct, payone_data, intent)

    # ── Generative visuals (GenUI) ────────────────────────────
    visuals = _gen_visuals(merchant, weather, time_ctx, payone_data)

    offer_id = str(uuid.uuid4())[:8]
    code = f"{merchant['id'][:5].upper()}-{offer_id.upper()}"

    # Expiry based on urgency
    urgency = composite.get("urgency", "medium")
    expiry_minutes = {"high": 12, "medium": 25, "low": 45}.get(urgency, 25)

    # Distance
    user_lat = user_signals.get("lat", 48.1351)
    user_lng = user_signals.get("lng", 11.582)
    dist_km = _haversine(user_lat, user_lng, merchant["lat"], merchant["lng"])
    dist_m = int(dist_km * 1000)
    walk_min = max(1, int(dist_m / 80))

    return {
        "id": offer_id, "code": code,
        "merchant_id": merchant["id"], "merchant_name": merchant["name"],
        "merchant_area": merchant["area"], "merchant_description": merchant.get("description", ""),
        "merchant_lat": merchant["lat"], "merchant_lng": merchant["lng"],
        "merchant_category": merchant.get("category", "shop"),
        "merchant_tags": merchant.get("tags", []),
        # Generative content
        "headline": copy["headline"], "subline": copy["subline"],
        "cta": copy["cta"], "emotional_frame": copy["frame"],
        "tone": tone, "why_text": copy["why"],
        # Discount
        "discount_pct": discount_pct, "discount_eur": discount_eur,
        "discount_label": f"{discount_pct}% off" if discount_pct <= 15 else f"€{discount_eur:.2f} off",
        "cashback_amount": discount_eur,
        # Visual (GenUI)
        "bg_gradient": visuals["gradient"], "accent_color": visuals["accent"],
        "icon": visuals["icon"], "mood": visuals["mood"],
        "card_style": visuals["card_style"],
        # Geo
        "distance_m": dist_m, "walk_min": walk_min,
        "distance_label": f"{dist_m}m" if dist_m < 1000 else f"{dist_km:.1f}km",
        "maps_url": f"https://www.google.com/maps/dir/?api=1&destination={merchant['lat']},{merchant['lng']}&travelmode=walking",
        # Timing
        "expiry_minutes": expiry_minutes,
        "generated_at": datetime.now().isoformat(),
        "expires_at": (datetime.now().timestamp() + expiry_minutes * 60),
        # Context
        "trigger_signals": composite.get("signals", []),
        "trigger_description": composite.get("description", ""),
        "payone_state": payone_data.get("demand_state", "unknown"),
        "payone_tx": payone_data.get("current_tx", 0),
        "payone_avg": payone_data.get("avg_hourly_tx", 0),
    }


def _gen_copy(merchant, weather, time_ctx, tone, discount_pct, payone, intent):
    name = merchant["name"]
    tags = merchant.get("tags", [])
    tag0 = tags[0] if tags else "treat"
    demand = payone.get("demand_state", "normal")
    temp = weather.get("temperature_c", 15)

    # Frame selection based on full context
    if weather.get("is_cold") and weather.get("is_rainy"):
        frame = "shelter"
        heads = [f"Rain + {temp}°. {name} is warm.", f"Escape the rain — {discount_pct}% off at {name}.",
                 f"Wet and cold? Hot {tag0} waiting inside."]
        subs = [f"Your warm {tag0} is {discount_pct}% off for the next 15 minutes.",
                f"Ducking in isn't giving up — it's smart. {discount_pct}% off."]
        why = f"It's raining and {temp}° — {name} has low traffic and a warm seat."
    elif weather.get("is_cold"):
        frame = "warmth"
        heads = [f"{temp}° outside. Warm up at {name}.", f"Cold hands? Hot {tag0} at {name}.",
                 f"Your warm escape is {discount_pct}% off."]
        subs = [f"{name} in {merchant['area']} — {discount_pct}% off right now.",
                f"Step in, warm up. {discount_pct}% off your order."]
        why = f"It's cold ({temp}°) and {name} is quiet — perfect time for a warm {tag0}."
    elif weather.get("is_hot"):
        frame = "refresh"
        heads = [f"{temp}° — cool down at {name}.", f"Too hot? Cold drinks {discount_pct}% off."]
        subs = [f"Iced drinks and shade. {discount_pct}% off.", f"Beat the heat at {name}."]
        why = f"It's {temp}° — {name} has AC and cold drinks."
    elif time_ctx.get("is_lunch"):
        frame = "hunger"
        heads = [f"Lunch break? {name} — {discount_pct}% off.", f"12 minutes? {name} is right here."]
        subs = [f"Fresh {tag0} — {discount_pct}% off until 14:00.", f"Quick lunch, great price."]
        why = f"It's lunchtime and {name} wants to fill seats — {discount_pct}% off."
    elif demand in ["very_low", "low"]:
        frame = "quiet_deal"
        heads = [f"{name} is quiet right now — {discount_pct}% off.", f"Best seat in the house? Now. {discount_pct}% off."]
        subs = [f"Low crowd, big discount. {name} wants you in.", f"Quiet hour deal — won't last."]
        why = f"Payone data shows {name} has very low traffic now — they're boosting offers."
    else:
        frame = "discovery"
        heads = [f"{name} — {discount_pct}% off right now.", f"Discover {name} in {merchant['area']}."]
        subs = [f"{discount_pct}% off — created just for this moment.", f"AI-generated deal, just for you."]
        why = f"Context signals matched — {name} has an active offer for you."

    if tone == "playful":
        ctas = ["Yes please!", "I'm in!", "Take me there", "Let's go!"]
    elif tone == "warm":
        ctas = ["Sounds perfect", "I'll stop by", "Save this offer", "Reserve my deal"]
    else:
        ctas = ["Redeem now", "Get this offer", "Claim discount", "Grab deal"]

    return {"headline": random.choice(heads), "subline": random.choice(subs),
            "cta": random.choice(ctas), "frame": frame, "why": why}


def _gen_visuals(merchant, weather, time_ctx, payone):
    """GenUI: compute visual parameters at runtime from context."""
    cat = merchant.get("category", "shop")
    demand = payone.get("demand_state", "normal")

    # Base mood from weather
    if weather.get("is_rainy"):
        mood, gradient, accent = "cozy", "linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%)", "#e94560"
    elif weather.get("is_cold"):
        mood, gradient, accent = "warm", "linear-gradient(135deg,#2d1810 0%,#5c3317 50%,#8b4513 100%)", "#ffd700"
    elif weather.get("is_hot"):
        mood, gradient, accent = "fresh", "linear-gradient(135deg,#0c2340 0%,#005c97 50%,#00b4db 100%)", "#00e5ff"
    elif time_ctx.get("is_evening"):
        mood, gradient, accent = "evening", "linear-gradient(135deg,#1a0033 0%,#330066 50%,#6600cc 100%)", "#ff9f43"
    elif time_ctx.get("is_morning"):
        mood, gradient, accent = "morning", "linear-gradient(135deg,#0d1117 0%,#1a3a1a 50%,#2d5a2d 100%)", "#a8e063"
    elif demand in ["very_low", "low"]:
        mood, gradient, accent = "deal", "linear-gradient(135deg,#1a0000 0%,#4a0000 50%,#8b0000 100%)", "#ff6b6b"
    else:
        mood, gradient, accent = "inviting", "linear-gradient(135deg,#1a1a2e 0%,#2d2d44 50%,#3d3d5c 100%)", "#a29bfe"

    icons = {"cafe": "☕" if weather.get("is_cold") else "🧊", "bakery": "🥐", "bistro": "🍽️"}.get(cat, "✨")

    # Card style varies by context
    if demand == "very_low":
        card_style = "urgent"
    elif weather.get("is_rainy"):
        card_style = "shelter"
    elif time_ctx.get("is_lunch"):
        card_style = "quick"
    else:
        card_style = "standard"

    return {"gradient": gradient, "accent": accent, "icon": icons, "mood": mood, "card_style": card_style}


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371; dlat = math.radians(lat2-lat1); dlng = math.radians(lng2-lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def _in_quiet_hours(merchant, time_ctx):
    h, m = time_ctx.get("hour", 12), time_ctx.get("minute", 0)
    now_min = h * 60 + m
    for qh in merchant.get("rules", {}).get("quiet_hours", []):
        sh, sm = map(int, qh["start"].split(":")); eh, em = map(int, qh["end"].split(":"))
        if sh*60+sm <= now_min <= eh*60+em: return True
    return False


# ══════════════════════════════════════════════════════════════════
#  MODULE 3: CHECKOUT & REDEMPTION
# ══════════════════════════════════════════════════════════════════

@app.route("/api/offer/action", methods=["POST"])
def offer_action():
    """Track accept/decline/expire for merchant analytics."""
    data = request.get_json(force=True)
    action = data.get("action")  # accept, decline, expire
    offer_id = data.get("offer_id", "")
    merchant_id = data.get("merchant_id", "")

    OFFER_ACTIONS.append({"offer_id": offer_id, "merchant_id": merchant_id,
                          "action": action, "ts": datetime.now().isoformat()})

    if merchant_id in MERCHANTS:
        if action == "accept": MERCHANTS[merchant_id]["stats"]["offers_accepted"] += 1
        elif action == "decline": MERCHANTS[merchant_id]["stats"]["offers_declined"] += 1

    return jsonify({"ok": True})


@app.route("/api/redeem", methods=["POST"])
def redeem():
    """Redeem an offer — simulated checkout with cashback."""
    data = request.get_json(force=True)
    code = data.get("code", "")
    merchant_id = data.get("merchant_id", "")
    user_id = data.get("user_id", "anonymous")

    if not code: return jsonify({"error": "Code required"}), 400
    if merchant_id not in MERCHANTS: return jsonify({"error": "Unknown merchant"}), 404

    merchant = MERCHANTS[merchant_id]
    cashback = merchant["rules"].get("max_discount_eur", 1.50)

    # Simulated checkout
    item_price = round(random.uniform(3.5, 8.5), 2)
    final_price = round(max(item_price - cashback, 0.5), 2)

    redemption = {
        "id": str(uuid.uuid4())[:8], "code": code,
        "merchant_id": merchant_id, "merchant_name": merchant["name"],
        "item_price": item_price, "discount": cashback,
        "final_price": final_price, "cashback_credited": cashback,
        "timestamp": time.time(), "ts_human": datetime.now().strftime("%H:%M:%S"),
        "checkout_status": "completed",
    }
    REDEMPTIONS.append(redemption)
    merchant["walk_ins"] += 1
    merchant["revenue"] += final_price
    merchant["stats"]["cashback_total"] += cashback

    # Cashback ledger
    CASHBACK_LEDGER.append({"user_id": user_id, "amount": cashback,
                            "merchant_id": merchant_id, "ts": datetime.now().isoformat()})

    return jsonify(redemption), 201


@app.route("/api/qr", methods=["GET"])
def generate_qr():
    text = request.args.get("text", "")
    if not text: return jsonify({"error": "text param required"}), 400
    try:
        import qrcode
        img = qrcode.make(text, box_size=8, border=2)
        buf = BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        return Response(buf.getvalue(), mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cashback", methods=["GET"])
def get_cashback():
    """Get cashback balance for a user."""
    user_id = request.args.get("user_id", "anonymous")
    entries = [e for e in CASHBACK_LEDGER if e["user_id"] == user_id]
    total = sum(e["amount"] for e in entries)
    return jsonify({"user_id": user_id, "balance": round(total, 2), "transactions": entries})


# ══════════════════════════════════════════════════════════════════
#  MERCHANT & LEDGER
# ══════════════════════════════════════════════════════════════════

@app.route("/api/merchants", methods=["GET"])
def list_merchants():
    return jsonify(list(MERCHANTS.values()))

@app.route("/api/merchants", methods=["POST"])
def add_merchant():
    data = request.get_json(force=True)
    mid = data.get("id") or str(uuid.uuid4())[:8]
    merchant = {
        "id": mid, "name": data.get("name", "New Shop"), "area": data.get("area", "Munich"),
        "lat": float(data.get("lat", 48.1351)), "lng": float(data.get("lng", 11.582)),
        "category": data.get("category", "shop"), "tags": data.get("tags", []),
        "description": data.get("description", ""),
        "rules": data.get("rules", {"max_discount_pct":15,"max_discount_eur":2,"quiet_hours":[{"start":"14:00","end":"16:00"}],"goal":"fill_quiet_hours","tone":"warm","auto_generate":True}),
        "payone": {"avg_hourly_tx": 15, "peak_hours": [8,9,12,13], "base_tx": 4},
        "status": "live", "walk_ins": 0, "revenue": 0.0,
        "stats": {"offers_generated":0,"offers_accepted":0,"offers_declined":0,"cashback_total":0},
    }
    MERCHANTS[mid] = merchant
    return jsonify(merchant), 201

@app.route("/api/merchants/rules", methods=["POST"])
def update_rules():
    data = request.get_json(force=True)
    mid = data.get("merchant_id")
    if mid not in MERCHANTS: return jsonify({"error": "Not found"}), 404
    MERCHANTS[mid]["rules"].update(data.get("rules", {}))
    return jsonify(MERCHANTS[mid])

@app.route("/api/ledger", methods=["GET"])
def get_ledger():
    total_walkins = sum(m["walk_ins"] for m in MERCHANTS.values())
    total_revenue = sum(m["revenue"] for m in MERCHANTS.values())
    total_cashback = sum(m["stats"]["cashback_total"] for m in MERCHANTS.values())
    total_accepted = sum(m["stats"]["offers_accepted"] for m in MERCHANTS.values())
    total_declined = sum(m["stats"]["offers_declined"] for m in MERCHANTS.values())
    total_gen = sum(m["stats"]["offers_generated"] for m in MERCHANTS.values())
    accept_rate = round(total_accepted / max(total_accepted + total_declined, 1) * 100)

    return jsonify({
        "merchants": list(MERCHANTS.values()),
        "total_revenue": round(total_revenue, 2),
        "total_walkins": total_walkins,
        "total_optins": len(OPTINS),
        "total_redemptions": len(REDEMPTIONS),
        "total_cashback": round(total_cashback, 2),
        "total_offers_generated": total_gen,
        "accept_rate_pct": accept_rate,
        "redemptions": REDEMPTIONS[-20:],
        "generated_offers_count": len(GENERATED_OFFERS),
    })

@app.route("/api/merchant/stats", methods=["GET"])
def merchant_stats():
    """Merchant analytics: accept/decline rates, revenue, cashback."""
    mid = request.args.get("merchant_id", "")
    if mid not in MERCHANTS: return jsonify({"error": "Not found"}), 404
    m = MERCHANTS[mid]
    gen = m["stats"]["offers_generated"]
    acc = m["stats"]["offers_accepted"]
    dec = m["stats"]["offers_declined"]
    return jsonify({
        "merchant_id": mid, "name": m["name"],
        "offers_generated": gen, "offers_accepted": acc, "offers_declined": dec,
        "accept_rate_pct": round(acc / max(acc + dec, 1) * 100),
        "walk_ins": m["walk_ins"], "revenue": m["revenue"],
        "cashback_total": m["stats"]["cashback_total"],
    })

@app.route("/api/optin", methods=["POST"])
def optin():
    data = request.get_json(force=True)
    uid = data.get("user_id") or str(uuid.uuid4())
    OPTINS[uid] = {"user_id": uid, "ts": datetime.now().isoformat()}
    return jsonify({"user_id": uid})

@app.route("/api/reset", methods=["POST"])
def reset():
    REDEMPTIONS.clear(); OPTINS.clear(); GENERATED_OFFERS.clear()
    OFFER_ACTIONS.clear(); CASHBACK_LEDGER.clear(); seed()
    return jsonify({"status": "reset"})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "merchants": len(MERCHANTS), "version": "3.0",
                     "cities": list(CITY_CONFIGS.keys())})

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return "", 204
