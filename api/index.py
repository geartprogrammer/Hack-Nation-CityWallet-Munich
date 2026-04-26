"""
CITY WALLET — The Quiet Hour Filler (Final)
One button: "Fill my seats." AI does everything else.
"""
from flask import Flask, request, jsonify, Response
import json, time, uuid, random, math, hashlib, hmac, os
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

app = Flask(__name__)

VAPID_PUBLIC = "BD0IpekqsVFbloXMEbiHHiOgF_lKaQYQCp7uv7F1BgQ-ppQUFMdtqhhFuyuq-CoAdbN5PCydaQ-p9Wn0s85IFiE"
VAPID_PRIVATE = "S4CJhFVaTuaErh2yEYKy53QmJNMZARuV0eyxqLFxcvc"
VAPID_EMAIL = "mailto:citywallet@hacknation.dev"
SECRET = "cw-final-2026"
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

CAFES_PATH = Path(__file__).parent / "munich_cafes.json"
RAW_CAFES = json.loads(CAFES_PATH.read_text(encoding="utf-8")) if CAFES_PATH.exists() else []

# ══════════════════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════════════════
MERCHANTS = {}
FILLS = {}          # fill_id -> full fill record
ARRIVALS = []       # {fill_id, user_id/name, ts}
PUSH_SUBS = {}
MOCK_ACTIVITY = []  # Pre-generated mock data showing the system working

def _h(a,b,c,d):
    R=6371000;dl=math.radians(c-a);dn=math.radians(d-b)
    x=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dn/2)**2
    return R*2*math.atan2(math.sqrt(x),math.sqrt(1-x))
def _is_open(hrs):
    if not hrs:return True
    h=datetime.now().hour;da=["Mo","Tu","We","Th","Fr","Sa","Su"][datetime.now().weekday()]
    try:
        for p in hrs.split(";"):
            p=p.strip()
            if "off" in p.lower() and da in p:return False
            if any(d in p for d in [da,"Mo-Su","Mo-Fr" if datetime.now().weekday()<5 else "XX"]):
                for t in p.split(","):
                    if "-" in t and ":" in t:
                        ts2=t.strip()
                        if " " in ts2:ts2=ts2.split(" ")[-1]
                        pts=ts2.split("-")
                        if len(pts)==2:
                            try:
                                if int(pts[0].split(":")[0])<=h<int(pts[1].split(":")[0]):return True
                            except:pass
    except:pass
    return True

def _sim_tx(hour):
    base={8:12,9:12,10:11,11:15,12:16,13:14,14:8,15:5,16:4,17:5,18:8,19:7}.get(hour,3)
    return max(1,base+random.randint(-2,3))

def _pin(p):return hmac.new(SECRET.encode(),p.encode(),hashlib.sha256).hexdigest()[:16]
def _tok(mid):return hmac.new(SECRET.encode(),mid.encode(),hashlib.sha256).hexdigest()[:24]
def _auth():
    t=request.headers.get("Authorization","").replace("Bearer ","")
    for mid,m in MERCHANTS.items():
        if _tok(mid)==t:return mid,m
    return None,None

# ── Generate mock activity on first load ──────────────────────────
def _seed_mock():
    global MOCK_ACTIVITY
    names = ["Mia K.","Jonas W.","Lena B.","Tim R.","Sophie M.","Elias H.","Anna F.","Max P.","Clara S.","Felix D."]
    cafes = ["Café Riese","Bäckerei Knaus","Brioche Marie","Schmalznudel","Nymphenburg Sekt"]
    items = ["Cappuccino","Latte","Croissant","Espresso","Iced Coffee","Bretzel","Hot Chocolate"]
    now = datetime.now()
    for i in range(15):
        mins_ago = random.randint(5, 180)
        t = now - timedelta(minutes=mins_ago)
        MOCK_ACTIVITY.append({
            "user": random.choice(names),
            "cafe": random.choice(cafes),
            "item": random.choice(items),
            "discount": random.randint(15, 35),
            "saved": round(random.uniform(0.8, 2.5), 2),
            "ts": t.strftime("%H:%M"),
            "status": "arrived",
        })
    MOCK_ACTIVITY.sort(key=lambda x: x["ts"], reverse=True)
_seed_mock()

# ══════════════════════════════════════════════════════════════════
#  WEATHER
# ══════════════════════════════════════════════════════════════════
def _weather(lat, lng):
    try:
        import requests as rq
        r = rq.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
            f"&current=temperature_2m,weather_code,apparent_temperature,precipitation,wind_speed_10m,relative_humidity_2m"
            f"&daily=uv_index_max&timezone=auto&forecast_days=1", timeout=5)
        d = r.json(); c = d.get("current", {}); dy = d.get("daily", {})
        temp = c.get("temperature_2m", 15); code = c.get("weather_code", 0)
        dm = {0:"Clear",1:"Clear",2:"Partly cloudy",3:"Overcast",45:"Foggy",51:"Light drizzle",
              53:"Drizzle",55:"Rain",61:"Light rain",63:"Rain",65:"Heavy rain",80:"Showers",95:"Thunderstorm"}
        return {"temp":temp,"feels":c.get("apparent_temperature",temp),"humidity":c.get("relative_humidity_2m",50),
            "wind":c.get("wind_speed_10m",10),"precip":c.get("precipitation",0),"code":code,
            "desc":dm.get(code,"Cloudy"),"is_cold":temp<12,"is_hot":temp>28,"is_rainy":code>=51,"is_sunny":code<=1,
            "uv":dy.get("uv_index_max",[0])[0] if dy.get("uv_index_max") else 0}
    except:
        return {"temp":14,"feels":12,"desc":"Cloudy","code":3,"is_cold":True,"is_hot":False,"is_rainy":False,"is_sunny":False,"uv":2}

# ══════════════════════════════════════════════════════════════════
#  AI TEXT GENERATION (Groq free tier or smart fallback)
# ══════════════════════════════════════════════════════════════════
def _ai_generate(prompt, fallback=""):
    """Call Groq's Llama API for real AI text. Falls back to smart template if no key."""
    if GROQ_KEY:
        try:
            import requests as rq
            r = rq.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": [
                    {"role": "system", "content": "You write ultra-short, warm, personal push notification text for a local cafe app. Max 15 words. No hashtags. No emojis in the middle of words. Sound like a friend, not a brand."},
                    {"role": "user", "content": prompt}
                ], "max_tokens": 60, "temperature": 0.9}, timeout=8)
            text = r.json()["choices"][0]["message"]["content"].strip().strip('"')
            return text
        except Exception as e:
            pass
    return fallback


def _ai_fill_analysis(merchant, weather, nearby_users, hour):
    """AI analyzes everything and decides: what item, what discount, what message."""
    menu = merchant.get("menu", [])
    if not menu:
        menu = [{"name": "Cappuccino", "price": 3.50}, {"name": "Latte", "price": 4.00},
                {"name": "Croissant", "price": 2.80}]

    temp = weather.get("temp", 15)
    desc = weather.get("desc", "Cloudy")
    is_cold = weather.get("is_cold", False)
    is_rainy = weather.get("is_rainy", False)
    is_hot = weather.get("is_hot", False)

    # AI picks the best item based on weather
    if is_cold or is_rainy:
        # Warm drinks score higher
        scored = [(i, 10 if any(w in i["name"].lower() for w in ["cappuccino","latte","hot","chocolate","tea"]) else 3) for i in menu]
    elif is_hot:
        scored = [(i, 10 if any(w in i["name"].lower() for w in ["iced","cold","juice","smoothie"]) else 3) for i in menu]
    else:
        scored = [(i, random.randint(3, 8)) for i in menu]

    scored.sort(key=lambda x: x[1], reverse=True)
    chosen_item = scored[0][0]

    # AI sets discount based on how desperate the situation is
    base_disc = 15
    if is_rainy: base_disc += 8
    if is_cold: base_disc += 5
    if hour in [14, 15, 16]: base_disc += 5  # dead hours
    if nearby_users < 3: base_disc += 5  # few users = need bigger incentive
    discount = min(base_disc, 40)
    discount_price = round(chosen_item["price"] * (1 - discount/100), 2)
    cashback = round(chosen_item["price"] - discount_price, 2)

    # AI generates the notification text
    prompt = (f"Write a push notification for someone walking near {merchant['name']} cafe. "
              f"Weather: {temp}°C {desc}. Time: {hour}:00. "
              f"The deal: {chosen_item['name']} for €{discount_price} instead of €{chosen_item['price']}. "
              f"Make it feel personal and urgent. Max 12 words.")

    if is_rainy:
        fb = f"Rain outside? {chosen_item['name']} €{discount_price} at {merchant['name']}. Warm and dry inside."
    elif is_cold:
        fb = f"It's {temp}°. Warm {chosen_item['name']} for €{discount_price} at {merchant['name']}. 🔥"
    elif is_hot:
        fb = f"{temp}° today. Cool down with {chosen_item['name']} €{discount_price} at {merchant['name']}."
    else:
        fb = f"{merchant['name']} has {chosen_item['name']} for €{discount_price} right now. Only for you."

    notif_text = _ai_generate(prompt, fb)

    # AI explains its reasoning
    reasoning = (f"Picked {chosen_item['name']} because "
                 f"{'it is cold and rainy — hot drinks convert best' if is_cold and is_rainy else 'it is cold — warm items score higher' if is_cold else 'it is hot — cold items preferred' if is_hot else 'it is the most popular item'}. "
                 f"Set {discount}% off because "
                 f"{'heavy rain + dead hours = maximum incentive needed' if is_rainy and 14<=hour<=16 else 'afternoon quiet period' if 14<=hour<=16 else 'moderate context signals'}. "
                 f"Targeting {nearby_users} users within 500m.")

    return {
        "item": chosen_item,
        "discount_pct": discount,
        "discount_price": discount_price,
        "cashback": cashback,
        "notification_text": notif_text,
        "reasoning": reasoning,
        "weather_factor": desc,
        "temp": temp,
    }


# ══════════════════════════════════════════════════════════════════
#  MERCHANT AUTH
# ══════════════════════════════════════════════════════════════════
@app.route("/api/merchant/register", methods=["POST"])
def reg():
    d = request.get_json(force=True)
    name = d.get("name","").strip(); pin = d.get("pin","").strip()
    if not name or len(pin) < 4: return jsonify({"error":"Name + 4-digit PIN required"}),400
    mid = "m-" + hashlib.md5(name.lower().encode()).hexdigest()[:8]
    lat = float(d.get("lat",48.1351)); lng = float(d.get("lng",11.582))
    MERCHANTS[mid] = {
        "id":mid,"name":name,"pin_hash":_pin(pin),"lat":lat,"lng":lng,
        "menu": d.get("menu", [
            {"name":"Cappuccino","price":3.50},{"name":"Latte Macchiato","price":4.00},
            {"name":"Espresso","price":2.20},{"name":"Hot Chocolate","price":3.80},
            {"name":"Croissant","price":2.80},{"name":"Iced Coffee","price":4.50},
        ]),
        "fills": 0, "total_arrivals": 0, "total_revenue": 0, "total_cashback": 0,
        "created": datetime.now().isoformat(),
    }
    return jsonify({"merchant_id":mid,"token":_tok(mid),"name":name}),201

@app.route("/api/merchant/login", methods=["POST"])
def login():
    d = request.get_json(force=True)
    name = d.get("name","").strip(); pin = d.get("pin","").strip()
    mid = "m-" + hashlib.md5(name.lower().encode()).hexdigest()[:8]
    m = MERCHANTS.get(mid)
    if not m or m["pin_hash"] != _pin(pin): return jsonify({"error":"Wrong name or PIN"}),401
    return jsonify({"merchant_id":mid,"token":_tok(mid),"name":m["name"],"merchant":m})

@app.route("/api/merchant/budget", methods=["POST"])
def set_budget():
    mid,m = _auth()
    if not m: return jsonify({"error":"Unauthorized"}),401
    d = request.get_json(force=True)
    if "budget" in d: m["budget"] = float(d["budget"])
    if "quiet_start" in d: m["quiet_start"] = d["quiet_start"]
    if "quiet_end" in d: m["quiet_end"] = d["quiet_end"]
    if "max_discount" in d: m["max_discount"] = int(d["max_discount"])
    return jsonify({"ok":True,"budget":m.get("budget",20),"quiet_start":m.get("quiet_start","14:00"),
        "quiet_end":m.get("quiet_end","17:00"),"max_discount":m.get("max_discount",30)})

@app.route("/api/merchant/parse-menu", methods=["POST"])
def parse_menu():
    """Upload a menu photo → OpenAI Vision extracts items + prices."""
    mid, m = _auth()
    if not m: return jsonify({"error":"Unauthorized"}),401
    if not OPENAI_KEY: return jsonify({"error":"OpenAI API key not configured"}),500
    d = request.get_json(force=True)
    image_b64 = d.get("image","")
    if not image_b64: return jsonify({"error":"No image provided"}),400
    try:
        import requests as rq
        resp = rq.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization":f"Bearer {OPENAI_KEY}","Content-Type":"application/json"},
            json={
                "model":"gpt-4o",
                "messages":[
                    {"role":"system","content":"You extract menu items from cafe/restaurant menu photos. Return ONLY valid JSON array. Each item: {\"name\":\"Item name\",\"price\":3.50}. Extract every item with a visible price. No markdown, no explanation, just the JSON array."},
                    {"role":"user","content":[
                        {"type":"text","text":"Extract all menu items and prices from this menu photo. Return JSON array only."},
                        {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image_b64}","detail":"high"}}
                    ]}
                ],
                "max_tokens":1000,
                "temperature":0.1
            }, timeout=30)
        result = resp.json()
        text = result["choices"][0]["message"]["content"].strip()
        # Clean up: remove markdown code fences if present
        if text.startswith("```"): text = text.split("\n",1)[1] if "\n" in text else text[3:]
        if text.endswith("```"): text = text[:-3]
        if text.startswith("json"): text = text[4:]
        items = json.loads(text.strip())
        # Validate
        clean = [{"name":str(i.get("name","")),"price":round(float(i.get("price",0)),2)} for i in items if i.get("name") and i.get("price")]
        # Save to merchant
        m["menu"] = clean
        return jsonify({"items":clean,"count":len(clean)})
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/merchant/menu", methods=["POST"])
def update_menu():
    mid,m = _auth()
    if not m: return jsonify({"error":"Unauthorized"}),401
    d = request.get_json(force=True)
    m["menu"] = d.get("menu", m.get("menu",[]))
    return jsonify({"menu": m["menu"]})


# ══════════════════════════════════════════════════════════════════
#  THE ONE BUTTON: "FILL MY SEATS"
# ══════════════════════════════════════════════════════════════════
@app.route("/api/fill", methods=["POST"])
def fill_seats():
    """
    The merchant taps ONE button. The AI:
    1. Checks weather
    2. Counts nearby users
    3. Picks the best item from the menu
    4. Sets the optimal discount
    5. Generates personalized notification text
    6. Sends push to all nearby users
    Returns the full AI analysis.
    """
    mid, m = _auth()
    if not m: return jsonify({"error":"Unauthorized"}),401

    weather = _weather(m["lat"], m["lng"])
    hour = datetime.now().hour

    # Count all subscribers (send to everyone — real-world would filter by distance)
    nearby = []
    for ep, info in PUSH_SUBS.items():
        d = _h(m["lat"],m["lng"],info.get("lat",0),info.get("lng",0)) if info.get("lat") else 999
        nearby.append({"ep":ep,"info":info,"dist":int(d)})

    # AI analysis
    analysis = _ai_fill_analysis(m, weather, len(nearby), hour)

    # Create fill record
    fid = str(uuid.uuid4())[:8]
    code = f"CW-{fid.upper()}"
    fill = {
        "id": fid, "code": code, "merchant_id": mid, "merchant_name": m["name"],
        "merchant_lat": m["lat"], "merchant_lng": m["lng"],
        "item": analysis["item"]["name"], "original_price": analysis["item"]["price"],
        "discount_pct": analysis["discount_pct"], "discount_price": analysis["discount_price"],
        "cashback": analysis["cashback"],
        "notification_text": analysis["notification_text"],
        "reasoning": analysis["reasoning"],
        "weather": weather["desc"], "temp": weather["temp"],
        "nearby_users": len(nearby), "status": "active",
        "arrivals": [], "created": datetime.now().isoformat(),
    }
    FILLS[fid] = fill
    m["fills"] = m.get("fills",0) + 1

    # Push to all nearby users
    sent = 0; failed = 0; dead = []
    title = f"☕ {analysis['item']['name']} €{analysis['discount_price']}"
    body = analysis["notification_text"]
    for n in nearby:
        try:
            from pywebpush import webpush
            payload = json.dumps({"title":title,"body":body,"fillId":fid,"code":code,
                "item":analysis["item"]["name"],"discount_price":analysis["discount_price"],
                "original_price":analysis["item"]["price"],"discount_pct":analysis["discount_pct"],
                "cashback":analysis["cashback"],"merchant_name":m["name"],
                "merchant_lat":m["lat"],"merchant_lng":m["lng"],
                "weather":weather.get("desc",""),"temp":weather.get("temp",0),
                "reasoning":analysis["reasoning"]})
            webpush(n["info"]["sub"], data=payload,
                vapid_private_key=VAPID_PRIVATE, vapid_claims={"sub":VAPID_EMAIL})
            sent += 1
        except Exception as e:
            failed += 1
            if "410" in str(e) or "404" in str(e): dead.append(n["ep"])
    for ep in dead: PUSH_SUBS.pop(ep, None)

    return jsonify({
        "fill": fill, "analysis": analysis,
        "push": {"sent": sent, "failed": failed, "nearby": len(nearby)},
    })


@app.route("/api/fill/<fid>", methods=["GET"])
def get_fill(fid):
    f = FILLS.get(fid)
    if not f: return jsonify({"error":"Not found"}),404
    return jsonify(f)


# ══════════════════════════════════════════════════════════════════
#  USER: "I'M HERE" (no QR scan needed)
# ══════════════════════════════════════════════════════════════════
@app.route("/api/arrive", methods=["POST"])
def arrive():
    """User shows they arrived at the cafe. No scanning needed."""
    d = request.get_json(force=True)
    fill_id = d.get("fill_id","")
    user_id = d.get("user_id","anon")
    user_name = d.get("user_name","A customer")

    f = FILLS.get(fill_id)
    if not f: return jsonify({"error":"Offer not found"}),404

    arrival = {
        "user_id": user_id, "user_name": user_name,
        "ts": datetime.now().strftime("%H:%M"), "item": f["item"],
        "saved": f["cashback"],
    }
    f["arrivals"].append(arrival)
    ARRIVALS.append({**arrival, "fill_id": fill_id, "merchant": f["merchant_name"]})

    # Update merchant stats
    mid = f.get("merchant_id")
    if mid in MERCHANTS:
        MERCHANTS[mid]["total_arrivals"] = MERCHANTS[mid].get("total_arrivals",0) + 1
        MERCHANTS[mid]["total_revenue"] = MERCHANTS[mid].get("total_revenue",0) + f["discount_price"]
        MERCHANTS[mid]["total_cashback"] = MERCHANTS[mid].get("total_cashback",0) + f["cashback"]

    return jsonify({"ok": True, "arrival": arrival, "merchant": f["merchant_name"],
        "item": f["item"], "saved": f["cashback"], "price_paid": f["discount_price"]})


# ══════════════════════════════════════════════════════════════════
#  USER: get active offer near me
# ══════════════════════════════════════════════════════════════════
@app.route("/api/offer", methods=["GET"])
def get_offer():
    lat=float(request.args.get("lat",48.1351));lng=float(request.args.get("lng",11.582))
    fill_id=request.args.get("fill","")  # Direct fill link from merchant

    # Direct fill link — always works
    if fill_id and fill_id in FILLS:
        f=FILLS[fill_id]
        d=_h(lat,lng,f["merchant_lat"],f["merchant_lng"])
        return jsonify({"has_offer":True,"source":"merchant_fill","offer":{**f,
            "distance_m":int(d),"walk_min":max(1,int(d/80)),
            "maps_url":f"https://www.google.com/maps/dir/?api=1&destination={f['merchant_lat']},{f['merchant_lng']}&travelmode=walking"}})

    # Check active fills (works when same Vercel instance)
    for fid, f in FILLS.items():
        if f["status"] != "active": continue
        d = _h(lat,lng,f["merchant_lat"],f["merchant_lng"])
        return jsonify({"has_offer":True,"source":"active_fill","offer":{**f,
            "distance_m":int(d),"walk_min":max(1,int(d/80)),
            "maps_url":f"https://www.google.com/maps/dir/?api=1&destination={f['merchant_lat']},{f['merchant_lng']}&travelmode=walking"}})
    # No active fill — find the closest open cafe and generate an offer
    w = _weather(lat, lng); hr = datetime.now().hour
    # Sort ALL cafes by distance, pick the closest open one
    scored = []
    for c in RAW_CAFES:
        d = _h(lat, lng, c["lat"], c["lng"])
        if _is_open(c.get("hours","")): scored.append((c, d))
    scored.sort(key=lambda x: x[1])
    if scored:
        c, d = scored[0]
        tx = _sim_tx(hr)
        disc = 12
        if w.get("is_rainy"): disc += 6
        if w.get("is_cold"): disc += 4
        if tx < 6: disc += 5
        if 14 <= hr <= 17: disc += 3
        disc = min(disc, 30)
        items_weather = (["Cappuccino","Hot Chocolate","Latte"] if w.get("is_cold") or w.get("is_rainy")
            else ["Iced Coffee","Iced Latte","Cold Brew"] if w.get("is_hot")
            else ["Cappuccino","Latte","Espresso","Croissant"])
        item = random.choice(items_weather)
        price = {"Cappuccino":3.50,"Latte":4.00,"Espresso":2.20,"Croissant":2.80,
                 "Hot Chocolate":3.80,"Iced Coffee":4.50,"Iced Latte":4.80,"Cold Brew":4.20}.get(item, 3.50)
        dp = round(price*(1-disc/100), 2)
        cb = round(price - dp, 2)
        fid = hashlib.md5(f"{c['id']}{hr}".encode()).hexdigest()[:8]
        # Generate copy from weather
        if w.get("is_rainy"):
            notif = f"Rain outside? {c['name']} is warm and dry. {item} for €{dp}."
            reason = f"It's raining and {c['name']} is quiet ({tx} tx/hr). AI picked {item} (hot drink for cold rain) and set {disc}% off to get you inside."
        elif w.get("is_cold"):
            notif = f"It's {w['temp']}°. Warm {item} for €{dp} at {c['name']}."
            reason = f"Cold weather ({w['temp']}°) + quiet period ({tx} tx/hr). AI picked {item} and set {disc}% off."
        elif w.get("is_hot"):
            notif = f"{w['temp']}° today. {item} for €{dp} at {c['name']}. Cool down."
            reason = f"Hot weather ({w['temp']}°). AI picked {item} (cold drink) and set {disc}% off."
        else:
            notif = f"{c['name']} — {item} for €{dp}. Just for you, just for now."
            reason = f"AI picked {item} based on time ({hr}:00) and demand ({tx} tx/hr). {disc}% off."
        return jsonify({"has_offer":True,"offer":{
            "id":fid,"code":f"CW-{fid.upper()}","merchant_name":c["name"],
            "merchant_lat":c["lat"],"merchant_lng":c["lng"],
            "item":item,"original_price":price,"discount_pct":disc,
            "discount_price":dp,"cashback":cb,
            "notification_text":notif,
            "weather":w.get("desc",""),"temp":w.get("temp",15),"status":"generated",
            "distance_m":int(d),"walk_min":max(1,int(d/80)),
            "arrivals":[],"reasoning":reason,
            "maps_url":f"https://www.google.com/maps/dir/?api=1&destination={c['lat']},{c['lng']}&travelmode=walking"}})
    return jsonify({"has_offer":False})


# ══════════════════════════════════════════════════════════════════
#  DASHBOARD + PUSH + MISC
# ══════════════════════════════════════════════════════════════════
@app.route("/api/merchant/dashboard", methods=["GET"])
def dashboard():
    mid,m = _auth()
    if not m:
        return jsonify({"fills":len(FILLS),"arrivals":len(ARRIVALS),"subscribers":len(PUSH_SUBS),
            "merchants":len(MERCHANTS),"mock_activity":MOCK_ACTIVITY[:10]})
    my_fills = [f for f in FILLS.values() if f.get("merchant_id")==mid]
    total_arr = sum(len(f.get("arrivals",[])) for f in my_fills)
    return jsonify({"name":m["name"],"fills":len(my_fills),"total_arrivals":m.get("total_arrivals",0),
        "total_revenue":round(m.get("total_revenue",0),2),"total_cashback":round(m.get("total_cashback",0),2),
        "subscribers":len(PUSH_SUBS),"menu":m.get("menu",[]),
        "budget":m.get("budget",20),"spent_today":m.get("spent_today",0),
        "quiet_start":m.get("quiet_start","14:00"),"quiet_end":m.get("quiet_end","17:00"),
        "max_discount":m.get("max_discount",30),
        "recent_fills":my_fills[-5:],"recent_arrivals":ARRIVALS[-10:]})

@app.route("/api/activity", methods=["GET"])
def activity():
    """Returns mock + real activity for the user app."""
    real = [{"user":a.get("user_name","Someone"),"cafe":a.get("merchant","Cafe"),
        "item":a.get("item",""),"saved":a.get("saved",0),"ts":a.get("ts",""),
        "status":"arrived"} for a in ARRIVALS[-10:]]
    combined = real + MOCK_ACTIVITY
    combined.sort(key=lambda x: x.get("ts",""), reverse=True)
    return jsonify({"activity": combined[:15]})

@app.route("/api/savings", methods=["GET"])
def savings():
    uid = request.args.get("user_id","anon")
    mine = [a for a in ARRIVALS if a.get("user_id")==uid]
    total = sum(a.get("saved",0) for a in mine)
    return jsonify({"total":round(total,2),"count":len(mine),"history":mine[-15:]})

@app.route("/api/live", methods=["GET"])
def live():
    return jsonify({"fills":len(FILLS),"arrivals":len(ARRIVALS),"subscribers":len(PUSH_SUBS),
        "merchants":len(MERCHANTS),"total_cashback":round(sum(a.get("saved",0) for a in ARRIVALS),2),
        "recent_arrivals":ARRIVALS[-15:],"mock_activity":MOCK_ACTIVITY[:10],
        "recent_fills":[{"merchant":f["merchant_name"],"item":f["item"],"discount":f["discount_pct"],
            "arrivals":len(f.get("arrivals",[])),"ts":f.get("created","").split("T")[-1][:5]}
            for f in list(FILLS.values())[-10:]]})

@app.route("/api/vapid-public",methods=["GET"])
def vpub():return jsonify({"publicKey":VAPID_PUBLIC})

@app.route("/api/push/subscribe",methods=["POST"])
def psub():
    d=request.get_json(force=True);sub=d.get("subscription",{});ep=sub.get("endpoint","")
    if not ep:return jsonify({"error":"no endpoint"}),400
    PUSH_SUBS[ep]={"sub":sub,"lat":d.get("lat",0),"lng":d.get("lng",0),"ts":datetime.now().isoformat()}
    return jsonify({"ok":True,"total":len(PUSH_SUBS)})

@app.route("/api/qr",methods=["GET"])
def qr():
    text=request.args.get("text","")
    if not text:return jsonify({"error":"need text"}),400
    try:
        import qrcode;img=qrcode.make(text,box_size=10,border=2)
        buf=BytesIO();img.save(buf,format="PNG");buf.seek(0)
        return Response(buf.getvalue(),mimetype="image/png")
    except Exception as e:return jsonify({"error":str(e)}),500

@app.route("/api/health",methods=["GET"])
def health():
    return jsonify({"status":"ok","version":"8.0-quiet-hour-filler","cafes":len(RAW_CAFES),
        "subs":len(PUSH_SUBS),"merchants":len(MERCHANTS),"fills":len(FILLS),
        "groq": "connected" if GROQ_KEY else "fallback"})

@app.route("/api/optin",methods=["POST"])
def optin():return jsonify({"ok":True})

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]="*"
    r.headers["Access-Control-Allow-Methods"]="GET,POST,OPTIONS"
    r.headers["Access-Control-Allow-Headers"]="Content-Type,Authorization"
    return r
@app.route("/api/<path:p>",methods=["OPTIONS"])
def opts(p):return"",204
