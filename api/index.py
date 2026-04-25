"""
CITY WALLET v6 — Production-grade
Merchant auth, per-item tracking, repeatable boost, inter-app sync,
analytics, push routing, offline support.
"""
from flask import Flask, request, jsonify, Response
import json, time, uuid, random, math, os, hashlib, hmac
from datetime import datetime
from io import BytesIO
from pathlib import Path

app = Flask(__name__)

VAPID_PUBLIC = "BD0IpekqsVFbloXMEbiHHiOgF_lKaQYQCp7uv7F1BgQ-ppQUFMdtqhhFuyuq-CoAdbN5PCydaQ-p9Wn0s85IFiE"
VAPID_PRIVATE = "S4CJhFVaTuaErh2yEYKy53QmJNMZARuV0eyxqLFxcvc"
VAPID_EMAIL = "mailto:citywallet@hacknation.dev"
SECRET = "cw-hmac-secret-2026"

CAFES_PATH = Path(__file__).parent / "munich_cafes.json"
RAW_CAFES = json.loads(CAFES_PATH.read_text(encoding="utf-8")) if CAFES_PATH.exists() else []

# ══════════════════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════════════════
MERCHANTS = {}       # merchant_id -> {name, pin_hash, cafe_name, lat, lng, items, ...}
ACTIVE_BOOSTS = {}   # boost_id -> {merchant_id, item, code, discount, ts, redeemed_by: []}
REDEMPTIONS = []     # all redemptions
PUSH_SUBS = {}       # endpoint -> {sub, lat, lng}
CASHBACK = {}        # user_id -> float
BOOST_LOG = []       # {merchant_id, boost_id, sent, ts}
OFFER_LOG = []

def _h(lat1,lng1,lat2,lng2):
    R=6371000;dl=math.radians(lat2-lat1);dn=math.radians(lng2-lng1)
    a=math.sin(dl/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dn/2)**2
    return R*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

def _pin_hash(pin):
    return hmac.new(SECRET.encode(), pin.encode(), hashlib.sha256).hexdigest()[:16]

def _is_open(hrs):
    if not hrs: return True
    h=datetime.now().hour; da=["Mo","Tu","We","Th","Fr","Sa","Su"][datetime.now().weekday()]
    try:
        for p in hrs.split(";"):
            p=p.strip()
            if "off" in p.lower() and da in p: return False
            if any(d in p for d in [da,"Mo-Su","Mo-Fr" if datetime.now().weekday()<5 else "XX"]):
                for t in p.split(","):
                    if "-" in t and ":" in t:
                        ts=t.strip()
                        if " " in ts:ts=ts.split(" ")[-1]
                        pts=ts.split("-")
                        if len(pts)==2:
                            try:
                                if int(pts[0].split(":")[0])<=h<int(pts[1].split(":")[0]):return True
                            except:pass
    except:pass
    return True

def _sim_tx(hour):
    base={8:12,9:12,10:12,11:15,12:15,13:15,14:15,15:5,16:5,17:5,18:8,19:8}.get(hour,3)
    return max(1,base+random.randint(-2,3))

def _gen_copy(w,cafe,disc):
    n=cafe["name"];t=(cafe.get("cuisine")or"coffee").split(";")[0];tp=w.get("temp",15)
    if w.get("is_rainy"):return{"h":f"☔ {n}","s":f"Duck in — {disc}% off","f":"shelter"}
    if w.get("is_cold"):return{"h":f"🔥 {n} · {disc}% off","s":f"{tp}° outside · warm {t} waiting","f":"warmth"}
    if w.get("is_hot"):return{"h":f"🧊 {n}","s":f"{tp}° — cold drinks {disc}% off","f":"refresh"}
    if 11<=datetime.now().hour<=14:return{"h":f"🍽 {n} · {disc}% off","s":f"Lunch deal · {t}","f":"hunger"}
    return{"h":f"✨ {n}","s":f"{disc}% off · just for now","f":"discovery"}


# ══════════════════════════════════════════════════════════════════
#  MERCHANT AUTH
# ══════════════════════════════════════════════════════════════════

@app.route("/api/merchant/register", methods=["POST"])
def merchant_register():
    """Merchant signs up with a name and 4-digit PIN."""
    d = request.get_json(force=True)
    name = d.get("name","").strip()
    pin = d.get("pin","").strip()
    if not name or len(pin) < 4:
        return jsonify({"error": "Name and 4+ digit PIN required"}), 400
    mid = "m-" + hashlib.md5(name.lower().encode()).hexdigest()[:8]
    MERCHANTS[mid] = {
        "id": mid, "name": name, "pin_hash": _pin_hash(pin),
        "lat": float(d.get("lat", 48.1351)), "lng": float(d.get("lng", 11.582)),
        "items": [], "boosts": 0, "redemptions": 0, "revenue": 0,
        "created": datetime.now().isoformat(),
    }
    token = hmac.new(SECRET.encode(), mid.encode(), hashlib.sha256).hexdigest()[:24]
    return jsonify({"merchant_id": mid, "token": token, "name": name}), 201

@app.route("/api/merchant/login", methods=["POST"])
def merchant_login():
    d = request.get_json(force=True)
    name = d.get("name","").strip()
    pin = d.get("pin","").strip()
    mid = "m-" + hashlib.md5(name.lower().encode()).hexdigest()[:8]
    m = MERCHANTS.get(mid)
    if not m or m["pin_hash"] != _pin_hash(pin):
        return jsonify({"error": "Invalid name or PIN"}), 401
    token = hmac.new(SECRET.encode(), mid.encode(), hashlib.sha256).hexdigest()[:24]
    return jsonify({"merchant_id": mid, "token": token, "name": m["name"], "merchant": m})

def _auth_merchant():
    """Extract merchant from Authorization header."""
    auth = request.headers.get("Authorization","").replace("Bearer ","")
    for mid, m in MERCHANTS.items():
        check = hmac.new(SECRET.encode(), mid.encode(), hashlib.sha256).hexdigest()[:24]
        if check == auth: return mid, m
    return None, None


# ══════════════════════════════════════════════════════════════════
#  MERCHANT ITEMS (per-item tracking)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/merchant/items", methods=["GET"])
def list_items():
    mid, m = _auth_merchant()
    if not m: return jsonify({"error":"Unauthorized"}),401
    return jsonify({"items": m.get("items",[])})

@app.route("/api/merchant/items", methods=["POST"])
def add_item():
    """Merchant adds an item (e.g. Cappuccino €3.50)."""
    mid, m = _auth_merchant()
    if not m: return jsonify({"error":"Unauthorized"}),401
    d = request.get_json(force=True)
    item = {
        "id": str(uuid.uuid4())[:8],
        "name": d.get("name","Item"),
        "price": float(d.get("price", 3.50)),
        "category": d.get("category","drink"),
        "created": datetime.now().isoformat(),
    }
    m.setdefault("items",[]).append(item)
    return jsonify(item), 201


# ══════════════════════════════════════════════════════════════════
#  BOOST (repeatable, per-item, tracked)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/merchant/boost", methods=["POST"])
def boost():
    """Merchant boosts an item → push sent to nearby users. Repeatable."""
    mid, m = _auth_merchant()
    if not m: return jsonify({"error":"Unauthorized"}),401
    d = request.get_json(force=True)
    item_id = d.get("item_id")
    discount = int(d.get("discount", 15))
    custom_msg = d.get("message","")

    # Find item
    item = None
    for it in m.get("items",[]):
        if it["id"] == item_id: item = it; break

    item_name = item["name"] if item else d.get("item_name","Special offer")
    item_price = item["price"] if item else float(d.get("price",3.50))
    cashback = round(item_price * discount / 100, 2)

    # Create boost record
    boost_id = str(uuid.uuid4())[:8]
    code = f"CW-{mid[2:6].upper()}{boost_id.upper()}"

    ACTIVE_BOOSTS[boost_id] = {
        "id": boost_id, "code": code,
        "merchant_id": mid, "merchant_name": m["name"],
        "merchant_lat": m["lat"], "merchant_lng": m["lng"],
        "item_name": item_name, "item_price": item_price,
        "discount_pct": discount, "cashback": cashback,
        "message": custom_msg,
        "created": datetime.now().isoformat(),
        "redeemed_by": [],
    }

    # Push to all nearby subscribers
    title = custom_msg or f"☕ {m['name']} · {discount}% off {item_name}"
    body = f"€{cashback:.2f} cashback · Tap to get your code"

    sent = 0; failed = 0; dead = []
    for ep, info in PUSH_SUBS.items():
        if m.get("lat") and info.get("lat"):
            dist = _h(m["lat"], m["lng"], info["lat"], info["lng"])
            if dist > 2000: continue  # 2km radius
        try:
            from pywebpush import webpush
            payload = json.dumps({
                "title": title, "body": body,
                "offerId": boost_id, "boostId": boost_id,
                "code": code, "url": "/"
            })
            webpush(info["sub"], data=payload,
                    vapid_private_key=VAPID_PRIVATE, vapid_claims={"sub": VAPID_EMAIL})
            sent += 1
        except Exception as e:
            failed += 1
            if "410" in str(e) or "404" in str(e): dead.append(ep)
    for ep in dead: PUSH_SUBS.pop(ep, None)

    m["boosts"] = m.get("boosts",0) + 1
    BOOST_LOG.append({"merchant_id":mid,"boost_id":boost_id,"sent":sent,"ts":datetime.now().isoformat()})

    return jsonify({
        "boost_id": boost_id, "code": code,
        "sent": sent, "failed": failed,
        "item": item_name, "discount": discount,
        "total_subs": len(PUSH_SUBS),
    })

@app.route("/api/boost/<boost_id>", methods=["GET"])
def get_boost(boost_id):
    """Get a specific boost (user taps notification → fetches boost details)."""
    b = ACTIVE_BOOSTS.get(boost_id)
    if not b: return jsonify({"error":"Boost not found"}),404
    return jsonify(b)


# ══════════════════════════════════════════════════════════════════
#  VERIFY & REDEEM (merchant scans customer QR)
# ══════════════════════════════════════════════════════════════════

@app.route("/api/verify", methods=["POST"])
def verify_code():
    d = request.get_json(force=True)
    code = d.get("code","").strip().upper()
    user_id = d.get("user_id","anon")

    if not code or not code.startswith("CW-"):
        return jsonify({"valid":False,"error":"Invalid code format"}),400

    # Check double-redeem
    for r in REDEMPTIONS:
        if r.get("code","").upper()==code and r.get("user_id")==user_id:
            return jsonify({"valid":False,"error":"Already redeemed by you","redeemed_at":r.get("ts","")}),409

    # Try to match to a boost
    matched_boost = None
    for bid, b in ACTIVE_BOOSTS.items():
        if b["code"].upper() == code:
            matched_boost = b; break

    if matched_boost:
        name = matched_boost["merchant_name"]
        item = matched_boost["item_name"]
        cashback = matched_boost["cashback"]
        price = matched_boost["item_price"]
        final = round(max(price - cashback, 0.5), 2)
        matched_boost["redeemed_by"].append({"user_id":user_id,"ts":datetime.now().isoformat()})
    else:
        # Generic code — still valid
        name = "Cafe"
        item = "Item"
        cashback = round(random.uniform(1.0, 3.0), 2)
        price = round(random.uniform(3.5, 8.0), 2)
        final = round(max(price - cashback, 0.5), 2)

    r = {
        "id": str(uuid.uuid4())[:8], "code": code, "user_id": user_id,
        "merchant": name, "item": item,
        "item_price": price, "cashback": cashback, "final": final,
        "ts": datetime.now().strftime("%H:%M · %d %b"), "status": "completed",
        "boost_id": matched_boost["id"] if matched_boost else None,
    }
    REDEMPTIONS.append(r)
    CASHBACK[user_id] = CASHBACK.get(user_id, 0) + cashback

    # Update merchant stats
    if matched_boost:
        mid = matched_boost["merchant_id"]
        if mid in MERCHANTS:
            MERCHANTS[mid]["redemptions"] = MERCHANTS[mid].get("redemptions",0) + 1
            MERCHANTS[mid]["revenue"] = MERCHANTS[mid].get("revenue",0) + final

    return jsonify({"valid":True,"merchant":name,"item":item,"redemption":r})


# ══════════════════════════════════════════════════════════════════
#  MERCHANT ANALYTICS
# ══════════════════════════════════════════════════════════════════

@app.route("/api/merchant/dashboard", methods=["GET"])
def merchant_dashboard():
    mid, m = _auth_merchant()
    if not m:
        # Fallback: return global stats
        total_rev = sum(r.get("final",0) for r in REDEMPTIONS)
        total_cb = sum(r.get("cashback",0) for r in REDEMPTIONS)
        return jsonify({"total_redemptions":len(REDEMPTIONS),"total_revenue":round(total_rev,2),
            "total_cashback_given":round(total_cb,2),"active_subscribers":len(PUSH_SUBS),
            "recent":REDEMPTIONS[-10:],"boosts":[],"items":[]})

    my_boosts = [b for b in ACTIVE_BOOSTS.values() if b["merchant_id"]==mid]
    my_reds = [r for r in REDEMPTIONS if r.get("boost_id") in [b["id"] for b in my_boosts]]
    my_boost_log = [bl for bl in BOOST_LOG if bl["merchant_id"]==mid]

    total_sent = sum(bl.get("sent",0) for bl in my_boost_log)
    total_redeemed = len(my_reds)
    conversion = round(total_redeemed/max(total_sent,1)*100)

    return jsonify({
        "merchant_id": mid, "name": m["name"],
        "total_boosts": m.get("boosts",0),
        "total_redemptions": m.get("redemptions",0),
        "total_revenue": round(m.get("revenue",0),2),
        "total_notifications_sent": total_sent,
        "conversion_rate_pct": conversion,
        "active_subscribers": len(PUSH_SUBS),
        "items": m.get("items",[]),
        "recent_boosts": my_boosts[-5:],
        "recent_redemptions": my_reds[-10:],
        "boost_log": my_boost_log[-10:],
    })


# ══════════════════════════════════════════════════════════════════
#  USER ENDPOINTS
# ══════════════════════════════════════════════════════════════════

@app.route("/api/nearby", methods=["GET"])
def nearby():
    lat=float(request.args.get("lat",48.1351));lng=float(request.args.get("lng",11.582))
    radius=int(request.args.get("radius",500));limit=int(request.args.get("limit",15))
    w=_fetch_weather(lat,lng);now=datetime.now();hr=now.hour
    results=[]
    for c in RAW_CAFES:
        d=_h(lat,lng,c["lat"],c["lng"])
        if d>radius:continue
        if not _is_open(c.get("hours","")):continue
        tx=_sim_tx(hr);demand="quiet" if tx<5 else "normal" if tx<10 else "busy"
        disc=8
        if w.get("is_rainy"):disc+=5
        if w.get("is_cold"):disc+=3
        if demand=="quiet":disc+=5
        if 14<=hr<=17:disc+=3
        disc=min(disc,25);cb=round(disc*0.14,2)
        sc=100-(d/radius*40)
        if demand=="quiet":sc+=20
        if w.get("is_rainy"):sc+=15
        if c.get("wifi"):sc+=5
        cp=_gen_copy(w,c,disc)
        oid=hashlib.md5(f"{c['id']}{hr}".encode()).hexdigest()[:8]
        results.append({"id":oid,"code":f"CW-{oid.upper()}","name":c["name"],"lat":c["lat"],"lng":c["lng"],
            "street":c.get("street",""),"housenumber":c.get("housenumber",""),
            "distance_m":int(d),"walk_min":max(1,int(d/80)),"hours":c.get("hours",""),
            "outdoor":c.get("outdoor",False),"wifi":c.get("wifi",False),
            "cuisine":c.get("cuisine","coffee"),"website":c.get("website",""),"phone":c.get("phone",""),
            "headline":cp["h"],"subline":cp["s"],"frame":cp["f"],
            "discount_pct":disc,"cashback":cb,"label":f"{disc}% off",
            "demand":demand,"payone_tx":tx,"expiry_min":20 if demand=="quiet" else 35,
            "score":round(sc),
            "maps_url":f"https://www.google.com/maps/dir/?api=1&destination={c['lat']},{c['lng']}&travelmode=walking"})
    results.sort(key=lambda x:x["score"],reverse=True)
    return jsonify({"offers":results[:limit],"total_nearby":len(results),"radius_m":radius,
        "weather":w,"location":{"lat":lat,"lng":lng},"generated_at":now.isoformat(),
        "active_boosts":[{"id":b["id"],"code":b["code"],"merchant":b["merchant_name"],
            "item":b["item_name"],"discount":b["discount_pct"],"cashback":b["cashback"],
            "lat":b["merchant_lat"],"lng":b["merchant_lng"]}
            for b in ACTIVE_BOOSTS.values()
            if _h(lat,lng,b["merchant_lat"],b["merchant_lng"])<2000]})

@app.route("/api/savings", methods=["GET"])
def savings():
    uid=request.args.get("user_id","anon")
    mine=[r for r in REDEMPTIONS if r.get("user_id")==uid]
    return jsonify({"total_saved":round(CASHBACK.get(uid,0),2),"redemption_count":len(mine),
        "history":mine[-20:],"streak_days":min(len(mine),7)})

@app.route("/api/redeem", methods=["POST"])
def redeem():
    d=request.get_json(force=True)
    code=d.get("code","");uid=d.get("user_id","anon");name=d.get("merchant_name","Cafe")
    cb=float(d.get("cashback",1.5));ip=round(random.uniform(3.5,8.5),2);fp=round(max(ip-cb,0.5),2)
    r={"id":str(uuid.uuid4())[:8],"code":code,"user_id":uid,"merchant":name,
       "item_price":ip,"cashback":cb,"final":fp,"ts":datetime.now().strftime("%H:%M · %d %b"),"status":"completed"}
    REDEMPTIONS.append(r);CASHBACK[uid]=CASHBACK.get(uid,0)+cb
    return jsonify(r),201

# ══════════════════════════════════════════════════════════════════
#  PUSH + QR + MISC
# ══════════════════════════════════════════════════════════════════

@app.route("/api/vapid-public",methods=["GET"])
def vapid_pub():return jsonify({"publicKey":VAPID_PUBLIC})

@app.route("/api/push/subscribe",methods=["POST"])
def push_sub():
    d=request.get_json(force=True);sub=d.get("subscription",{});ep=sub.get("endpoint","")
    if not ep:return jsonify({"error":"no endpoint"}),400
    PUSH_SUBS[ep]={"sub":sub,"lat":d.get("lat",0),"lng":d.get("lng",0),"ts":datetime.now().isoformat()}
    return jsonify({"ok":True,"total_subs":len(PUSH_SUBS)})

@app.route("/api/push/send",methods=["POST"])
def push_send():
    d=request.get_json(force=True)
    title=d.get("title","New offer");body=d.get("body","Tap to see")
    oid=d.get("offer_id","");mlat=float(d.get("lat",0));mlng=float(d.get("lng",0));rad=float(d.get("radius",2000))
    sent=0;failed=0;dead=[]
    for ep,info in PUSH_SUBS.items():
        if mlat and info.get("lat"):
            if _h(mlat,mlng,info["lat"],info["lng"])>rad:continue
        try:
            from pywebpush import webpush
            webpush(info["sub"],data=json.dumps({"title":title,"body":body,"offerId":oid}),
                vapid_private_key=VAPID_PRIVATE,vapid_claims={"sub":VAPID_EMAIL});sent+=1
        except Exception as e:
            failed+=1
            if "410" in str(e) or "404" in str(e):dead.append(ep)
    for ep in dead:PUSH_SUBS.pop(ep,None)
    return jsonify({"sent":sent,"failed":failed,"total_subs":len(PUSH_SUBS)})

@app.route("/api/qr",methods=["GET"])
def gen_qr():
    text=request.args.get("text","")
    if not text:return jsonify({"error":"need text"}),400
    try:
        import qrcode;img=qrcode.make(text,box_size=10,border=2)
        buf=BytesIO();img.save(buf,format="PNG");buf.seek(0)
        return Response(buf.getvalue(),mimetype="image/png")
    except Exception as e:return jsonify({"error":str(e)}),500

@app.route("/api/health",methods=["GET"])
def health():
    return jsonify({"status":"ok","version":"6.0","cafes":len(RAW_CAFES),
        "push_subs":len(PUSH_SUBS),"merchants":len(MERCHANTS),"active_boosts":len(ACTIVE_BOOSTS)})

@app.route("/api/action",methods=["POST"])
def action():OFFER_LOG.append({**request.get_json(force=True),"ts":datetime.now().isoformat()});return jsonify({"ok":True})
@app.route("/api/optin",methods=["POST"])
def optin():return jsonify({"ok":True})
@app.route("/api/ledger",methods=["GET"])
def ledger():return jsonify({"total_revenue":sum(r.get("final",0) for r in REDEMPTIONS),"total_cashback":sum(r.get("cashback",0) for r in REDEMPTIONS),"total_redemptions":len(REDEMPTIONS),"redemptions":REDEMPTIONS[-20:]})

def _fetch_weather(lat,lng):
    try:
        import requests
        r=requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,weather_code,apparent_temperature,precipitation&daily=uv_index_max,sunrise,sunset&timezone=auto&forecast_days=1",timeout=5)
        d=r.json();c=d.get("current",{});dy=d.get("daily",{});temp=c.get("temperature_2m",15);code=c.get("weather_code",0)
        dm={0:"Clear",1:"Clear",2:"Cloudy",3:"Overcast",45:"Foggy",51:"Drizzle",61:"Rain",63:"Rain",65:"Heavy rain",80:"Showers",95:"Storm"}
        uv=dy.get("uv_index_max",[0])[0] if dy.get("uv_index_max") else 0
        return{"temp":temp,"feels":c.get("apparent_temperature",temp),"desc":dm.get(code,"Cloudy"),"code":code,
            "is_cold":temp<12,"is_hot":temp>28,"is_rainy":code>=51,"is_sunny":code<=1,
            "uv":uv,"uv_label":"Low" if uv<3 else "Moderate" if uv<6 else "High",
            "sunrise":(dy.get("sunrise",[""])[0]or"").split("T")[-1],"sunset":(dy.get("sunset",[""])[0]or"").split("T")[-1]}
    except Exception as e:
        return{"temp":14,"feels":12,"desc":"Cloudy","is_cold":True,"is_hot":False,"is_rainy":False,"is_sunny":False,"uv":2,"uv_label":"Low","error":str(e)}

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]="*"
    r.headers["Access-Control-Allow-Methods"]="GET,POST,OPTIONS"
    r.headers["Access-Control-Allow-Headers"]="Content-Type,Authorization"
    return r
@app.route("/api/<path:p>",methods=["OPTIONS"])
def opts(p):return"",204
