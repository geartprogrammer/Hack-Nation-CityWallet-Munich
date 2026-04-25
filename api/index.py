"""
THE TIME MARKET — City Wallet v7
Merchants don't set discounts. They sell their quiet hours.
The AI buys them and allocates to the highest-probability user.

Architecture:
  - Merchants upload quiet hours + daily budget
  - AI engine runs a real-time auction per user: who is most likely to walk in?
  - Only ONE user gets each offer slot — the one with highest conversion score
  - Offer is auto-generated: copy, discount, visuals from context
  - Push notification arrives. User taps. QR. Merchant scans. Done.

Modules (per challenge spec):
  1. Context Sensing: weather (Open-Meteo), Payone tx sim, 815 Munich cafes, events
  2. Generative Offer Engine: AI computes discount from budget + context, generates copy
  3. Seamless Checkout: QR redemption, merchant scanner, cashback, live dashboard
"""
from flask import Flask, request, jsonify, Response
import json, time, uuid, random, math, hashlib, hmac
from datetime import datetime
from io import BytesIO
from pathlib import Path

app = Flask(__name__)

VAPID_PUBLIC = "BD0IpekqsVFbloXMEbiHHiOgF_lKaQYQCp7uv7F1BgQ-ppQUFMdtqhhFuyuq-CoAdbN5PCydaQ-p9Wn0s85IFiE"
VAPID_PRIVATE = "S4CJhFVaTuaErh2yEYKy53QmJNMZARuV0eyxqLFxcvc"
VAPID_EMAIL = "mailto:citywallet@hacknation.dev"
SECRET = "tm-secret-2026"

CAFES_PATH = Path(__file__).parent / "munich_cafes.json"
RAW_CAFES = json.loads(CAFES_PATH.read_text(encoding="utf-8")) if CAFES_PATH.exists() else []

# ══════════════════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════════════════
MERCHANTS = {}       # mid -> {name, pin_hash, lat, lng, items, budget, quiet_hours, spent_today}
AUCTIONS = {}        # auction_id -> {merchant, item, budget_used, discount, user_endpoint, code, status}
REDEMPTIONS = []
PUSH_SUBS = {}       # endpoint -> {sub, lat, lng, ts, score_factors}
CASHBACK = {}        # user_id -> float
EVENT_LOG = []       # everything that happens, for the live dashboard

def _h(a,b,c,d):
    R=6371000;dl=math.radians(c-a);dn=math.radians(d-b)
    x=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dn/2)**2
    return R*2*math.atan2(math.sqrt(x),math.sqrt(1-x))

def _pin(p): return hmac.new(SECRET.encode(),p.encode(),hashlib.sha256).hexdigest()[:16]
def _tok(mid): return hmac.new(SECRET.encode(),mid.encode(),hashlib.sha256).hexdigest()[:24]

def _auth():
    t=request.headers.get("Authorization","").replace("Bearer ","")
    for mid,m in MERCHANTS.items():
        if _tok(mid)==t: return mid,m
    return None,None

def _log(typ, data):
    EVENT_LOG.append({"type":typ, "data":data, "ts":datetime.now().isoformat()})
    if len(EVENT_LOG) > 200: EVENT_LOG.pop(0)

def _sim_tx(hour):
    base={8:12,9:12,10:11,11:15,12:16,13:14,14:8,15:5,16:4,17:5,18:8,19:7}.get(hour,3)
    return max(1,base+random.randint(-2,3))

def _is_open(hrs):
    if not hrs: return True
    h=datetime.now().hour;da=["Mo","Tu","We","Th","Fr","Sa","Su"][datetime.now().weekday()]
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

def _weather(lat,lng):
    try:
        import requests
        r=requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
            f"&current=temperature_2m,weather_code,apparent_temperature,precipitation,wind_speed_10m,relative_humidity_2m"
            f"&daily=uv_index_max,sunrise,sunset&timezone=auto&forecast_days=1",timeout=5)
        d=r.json();c=d.get("current",{});dy=d.get("daily",{})
        temp=c.get("temperature_2m",15);code=c.get("weather_code",0);feels=c.get("apparent_temperature",temp)
        uv=dy.get("uv_index_max",[0])[0] if dy.get("uv_index_max") else 0
        dm={0:"Clear",1:"Clear",2:"Cloudy",3:"Overcast",45:"Foggy",51:"Drizzle",53:"Drizzle",55:"Rain",61:"Rain",63:"Rain",65:"Heavy rain",80:"Showers",95:"Storm"}
        return{"temp":temp,"feels":feels,"humidity":c.get("relative_humidity_2m",50),"wind":c.get("wind_speed_10m",10),
            "precip":c.get("precipitation",0),"code":code,"desc":dm.get(code,"Cloudy"),
            "is_cold":temp<12,"is_hot":temp>28,"is_rainy":code>=51,"is_sunny":code<=1,
            "uv":uv,"uv_label":"Low" if uv<3 else "Moderate" if uv<6 else "High",
            "sunrise":(dy.get("sunrise",[""])[0]or"").split("T")[-1],
            "sunset":(dy.get("sunset",[""])[0]or"").split("T")[-1]}
    except Exception as e:
        return{"temp":14,"feels":12,"humidity":60,"wind":10,"desc":"Cloudy","code":3,
            "is_cold":True,"is_hot":False,"is_rainy":False,"is_sunny":False,"uv":2,"uv_label":"Low"}

# ══════════════════════════════════════════════════════════════════
#  MODULE 1: CONTEXT SENSING
# ══════════════════════════════════════════════════════════════════

@app.route("/api/context", methods=["GET"])
def context():
    lat=float(request.args.get("lat",48.1351));lng=float(request.args.get("lng",11.582))
    w=_weather(lat,lng);now=datetime.now();hr=now.hour
    # Payone aggregate
    nearby=[c for c in RAW_CAFES if _h(lat,lng,c["lat"],c["lng"])<2000]
    open_now=[c for c in nearby if _is_open(c.get("hours",""))]
    txs=[_sim_tx(hr) for _ in open_now]
    avg_tx=sum(txs)/max(len(txs),1)
    quiet_count=sum(1 for t in txs if t<6)
    events=[]
    day=now.strftime("%A")
    if day=="Saturday":events.append({"name":"Weekend Market","type":"market"})
    if day in["Friday","Saturday"] and hr>=17:events.append({"name":"Live Music Night","type":"entertainment"})
    if now.month in[6,7,8]:events.append({"name":"Summer in Munich","type":"seasonal"})
    signals=[]
    if w["is_cold"]:signals.append("cold")
    if w["is_rainy"]:signals.append("rain")
    if w["is_hot"]:signals.append("hot")
    if 11<=hr<=14:signals.append("lunch")
    elif 14<=hr<=17:signals.append("afternoon")
    if quiet_count>len(open_now)*0.4:signals.append("many_quiet")
    if events:signals.append("events")
    return jsonify({"weather":w,"time":{"hour":hr,"minute":now.minute,"day":day,
        "is_weekend":now.weekday()>=5},"payone":{"nearby_cafes":len(nearby),
        "open_now":len(open_now),"avg_tx":round(avg_tx,1),"quiet_count":quiet_count},
        "events":events,"signals":signals,"location":{"lat":lat,"lng":lng}})

# ══════════════════════════════════════════════════════════════════
#  MODULE 2: THE AUCTION ENGINE
#  Merchant sets budget + quiet hours. AI decides who gets the offer.
# ══════════════════════════════════════════════════════════════════

@app.route("/api/auction/run", methods=["POST"])
def run_auction():
    """
    The core: merchant triggers an auction for one of their items.
    AI scores all nearby subscribers and picks the best one.
    Only that user gets the offer. Budget is deducted.
    """
    mid,m=_auth()
    if not m: return jsonify({"error":"Unauthorized"}),401
    d=request.get_json(force=True)
    item_name=d.get("item","Special")
    item_price=float(d.get("price",4.00))
    max_discount_pct=int(d.get("max_discount",25))

    budget_daily=float(m.get("budget",20))
    spent=float(m.get("spent_today",0))
    remaining=budget_daily-spent
    if remaining<0.5:
        return jsonify({"error":"Daily budget exhausted","spent":spent,"budget":budget_daily}),400

    w=_weather(m["lat"],m["lng"])
    hr=datetime.now().hour

    # ── Score every subscriber ────────────────────────────────
    candidates=[]
    for ep,info in PUSH_SUBS.items():
        ulat=info.get("lat",0);ulng=info.get("lng",0)
        if not ulat:continue
        dist=_h(m["lat"],m["lng"],ulat,ulng)
        if dist>2000:continue  # 2km max

        # Conversion probability score (0-100)
        score=50
        # Closer = more likely
        if dist<100:score+=25
        elif dist<300:score+=18
        elif dist<500:score+=12
        elif dist<1000:score+=5
        # Weather boost
        if w["is_cold"] or w["is_rainy"]:score+=15  # bad weather = more likely to duck in
        # Time boost
        if 11<=hr<=14:score+=8  # lunch
        elif 14<=hr<=17:score+=12  # afternoon lull = high intent
        # Demand context
        tx=_sim_tx(hr)
        if tx<5:score+=10  # quiet = AI bids more aggressively
        # Randomness (real-world uncertainty)
        score+=random.randint(-5,10)
        score=max(10,min(score,99))

        candidates.append({"endpoint":ep,"info":info,"dist":int(dist),"score":score,"tx":tx})

    if not candidates:
        return jsonify({"error":"No users nearby","subscribers":len(PUSH_SUBS)}),404

    # ── AI picks the winner ───────────────────────────────────
    candidates.sort(key=lambda x:x["score"],reverse=True)
    winner=candidates[0]

    # ── AI computes optimal discount from context ─────────────
    # Higher score = user is very likely → lower discount needed
    # Lower score = needs bigger incentive
    base_disc=8
    if w["is_rainy"]:base_disc+=4
    if w["is_cold"]:base_disc+=3
    if winner["tx"]<5:base_disc+=4  # quiet period
    if winner["score"]<50:base_disc+=5  # harder to convert
    elif winner["score"]>75:base_disc-=3  # easy convert, save budget
    discount=max(5,min(base_disc,max_discount_pct))
    cashback=round(item_price*discount/100,2)

    # Budget check
    if cashback>remaining:
        cashback=round(remaining,2)
        discount=int(cashback/item_price*100)

    # ── Generate offer copy from context ──────────────────────
    copy=_gen_copy(m["name"],item_name,discount,w,winner["dist"])

    # ── Create auction record ─────────────────────────────────
    aid=str(uuid.uuid4())[:8]
    code=f"TM-{aid.upper()}"
    auction={
        "id":aid,"code":code,"status":"sent",
        "merchant_id":mid,"merchant_name":m["name"],"merchant_lat":m["lat"],"merchant_lng":m["lng"],
        "item":item_name,"item_price":item_price,
        "discount_pct":discount,"cashback":cashback,
        "headline":copy["h"],"subline":copy["s"],"frame":copy["f"],"why":copy["w"],
        "winner_dist":winner["dist"],"winner_score":winner["score"],
        "candidates_count":len(candidates),
        "budget_used":cashback,"budget_remaining":round(remaining-cashback,2),
        "weather":w["desc"],"temp":w["temp"],
        "created":datetime.now().isoformat(),
    }
    AUCTIONS[aid]=auction
    m["spent_today"]=spent+cashback

    # ── Push to the winner ────────────────────────────────────
    push_ok=False
    try:
        from pywebpush import webpush
        payload=json.dumps({"title":f"☕ {m['name']} · {discount}% off {item_name}",
            "body":copy["s"],"auctionId":aid,"code":code})
        webpush(winner["info"]["sub"],data=payload,
            vapid_private_key=VAPID_PRIVATE,vapid_claims={"sub":VAPID_EMAIL})
        push_ok=True
    except Exception as e:
        auction["push_error"]=str(e)

    _log("auction",{"id":aid,"merchant":m["name"],"item":item_name,"discount":discount,
        "winner_dist":winner["dist"],"winner_score":winner["score"],"push_ok":push_ok,
        "candidates":len(candidates)})

    return jsonify({**auction,"push_sent":push_ok})


def _gen_copy(merchant,item,disc,w,dist):
    temp=w.get("temp",15)
    if w.get("is_rainy"):
        h=f"☔ {merchant} — {disc}% off {item}"
        s=f"Rain outside, warm inside. {dist}m away."
        f="shelter";wh=f"It's raining and {merchant} is quiet — the AI bid {disc}% of their budget for you."
    elif w.get("is_cold"):
        h=f"🔥 {item} at {merchant} — {disc}% off"
        s=f"It's {temp}°. You're {dist}m from warmth."
        f="warmth";wh=f"{merchant} is quiet and it's cold — the AI calculated you're the most likely to walk in."
    elif 11<=datetime.now().hour<=14:
        h=f"🍽 {disc}% off {item} at {merchant}"
        s=f"Lunch deal · {dist}m · generated for you"
        f="hunger";wh=f"Lunchtime + quiet cafe + you're nearby = the AI allocated this slot to you."
    else:
        h=f"✨ {merchant} · {disc}% off {item}"
        s=f"The AI picked you. {dist}m away. Won't last."
        f="discovery";wh=f"Out of {0} people nearby, the AI scored you highest for this offer."
    return{"h":h,"s":s,"f":f,"w":wh}


# ══════════════════════════════════════════════════════════════════
#  MODULE 3: CHECKOUT & REDEMPTION
# ══════════════════════════════════════════════════════════════════

@app.route("/api/verify", methods=["POST"])
def verify():
    d=request.get_json(force=True)
    code=d.get("code","").strip().upper()
    uid=d.get("user_id","anon")
    if not code or not code.startswith("TM-"):
        return jsonify({"valid":False,"error":"Invalid code"}),400
    # Double-redeem check
    for r in REDEMPTIONS:
        if r.get("code","")==code:
            return jsonify({"valid":False,"error":"Already redeemed","at":r.get("ts","")}),409
    # Find auction
    aid=code.replace("TM-","").lower()
    a=AUCTIONS.get(aid)
    if not a:
        return jsonify({"valid":False,"error":"Offer not found or expired"}),404
    # Redeem
    final=round(max(a["item_price"]-a["cashback"],0.5),2)
    r={"id":str(uuid.uuid4())[:8],"code":code,"user_id":uid,
        "merchant":a["merchant_name"],"item":a["item"],"auction_id":aid,
        "item_price":a["item_price"],"cashback":a["cashback"],"final":final,
        "discount_pct":a["discount_pct"],"winner_score":a.get("winner_score",0),
        "ts":datetime.now().strftime("%H:%M · %d %b"),"status":"completed"}
    REDEMPTIONS.append(r)
    CASHBACK[uid]=CASHBACK.get(uid,0)+a["cashback"]
    a["status"]="redeemed"
    # Update merchant
    mid=a.get("merchant_id")
    if mid in MERCHANTS:
        MERCHANTS[mid]["redemptions"]=MERCHANTS[mid].get("redemptions",0)+1
        MERCHANTS[mid]["revenue"]=MERCHANTS[mid].get("revenue",0)+final
    _log("redeem",{"code":code,"merchant":a["merchant_name"],"item":a["item"],
        "cashback":a["cashback"],"final":final})
    return jsonify({"valid":True,"redemption":r,"merchant":a["merchant_name"],"item":a["item"]})

@app.route("/api/auction/<aid>", methods=["GET"])
def get_auction(aid):
    a=AUCTIONS.get(aid)
    if not a:return jsonify({"error":"Not found"}),404
    return jsonify(a)

# ── User gets their best offer (for when they open the app) ──────
@app.route("/api/myoffer", methods=["GET"])
def my_offer():
    """Returns the single best offer for this user right now."""
    lat=float(request.args.get("lat",48.1351));lng=float(request.args.get("lng",11.582))
    # Check active auctions targeted near this user
    best=None;best_dist=99999
    for aid,a in AUCTIONS.items():
        if a["status"]!="sent":continue
        d=_h(lat,lng,a["merchant_lat"],a["merchant_lng"])
        if d<2000 and d<best_dist:
            best=a;best_dist=d
    if best:
        best_copy={**best,"distance_m":int(best_dist),"walk_min":max(1,int(best_dist/80)),
            "maps_url":f"https://www.google.com/maps/dir/?api=1&destination={best['merchant_lat']},{best['merchant_lng']}&travelmode=walking"}
        return jsonify({"has_offer":True,"offer":best_copy})
    # No auction active — generate one from nearby cafes
    w=_weather(lat,lng);hr=datetime.now().hour
    for c in RAW_CAFES:
        d=_h(lat,lng,c["lat"],c["lng"])
        if d>500:continue
        if not _is_open(c.get("hours","")):continue
        tx=_sim_tx(hr)
        if tx>8:continue  # not quiet enough
        disc=random.randint(8,18)
        cb=round(disc*0.14,2)
        cp=_gen_copy(c["name"],(c.get("cuisine")or"coffee").split(";")[0],disc,w,int(d))
        oid=hashlib.md5(f"{c['id']}{hr}".encode()).hexdigest()[:8]
        return jsonify({"has_offer":True,"offer":{
            "id":oid,"code":f"TM-{oid.upper()}","status":"generated",
            "merchant_name":c["name"],"merchant_lat":c["lat"],"merchant_lng":c["lng"],
            "item":(c.get("cuisine")or"coffee").split(";")[0],
            "item_price":round(random.uniform(3,6),2),
            "discount_pct":disc,"cashback":cb,
            "headline":cp["h"],"subline":cp["s"],"frame":cp["f"],"why":cp["w"],
            "distance_m":int(d),"walk_min":max(1,int(d/80)),
            "weather":w["desc"],"temp":w["temp"],
            "maps_url":f"https://www.google.com/maps/dir/?api=1&destination={c['lat']},{c['lng']}&travelmode=walking",
            "created":datetime.now().isoformat()}})
    return jsonify({"has_offer":False,"message":"No offers near you right now. We'll notify you when one appears."})

# ══════════════════════════════════════════════════════════════════
#  MERCHANT AUTH + ITEMS + BUDGET
# ══════════════════════════════════════════════════════════════════

@app.route("/api/merchant/register", methods=["POST"])
def reg():
    d=request.get_json(force=True)
    name=d.get("name","").strip();pin=d.get("pin","").strip()
    if not name or len(pin)<4:return jsonify({"error":"Name + 4-digit PIN required"}),400
    mid="m-"+hashlib.md5(name.lower().encode()).hexdigest()[:8]
    lat=float(d.get("lat",48.1351));lng=float(d.get("lng",11.582))
    MERCHANTS[mid]={"id":mid,"name":name,"pin_hash":_pin(pin),"lat":lat,"lng":lng,
        "items":[],"budget":float(d.get("budget",20)),"spent_today":0,
        "quiet_start":d.get("quiet_start","14:00"),"quiet_end":d.get("quiet_end","17:00"),
        "redemptions":0,"revenue":0,"auctions_run":0,"created":datetime.now().isoformat()}
    _log("merchant_register",{"name":name,"mid":mid})
    return jsonify({"merchant_id":mid,"token":_tok(mid),"name":name}),201

@app.route("/api/merchant/login", methods=["POST"])
def login():
    d=request.get_json(force=True)
    name=d.get("name","").strip();pin=d.get("pin","").strip()
    mid="m-"+hashlib.md5(name.lower().encode()).hexdigest()[:8]
    m=MERCHANTS.get(mid)
    if not m or m["pin_hash"]!=_pin(pin):return jsonify({"error":"Wrong name or PIN"}),401
    return jsonify({"merchant_id":mid,"token":_tok(mid),"name":m["name"],"merchant":m})

@app.route("/api/merchant/items", methods=["GET"])
def items_get():
    mid,m=_auth()
    if not m:return jsonify({"error":"Unauthorized"}),401
    return jsonify({"items":m.get("items",[])})

@app.route("/api/merchant/items", methods=["POST"])
def items_add():
    mid,m=_auth()
    if not m:return jsonify({"error":"Unauthorized"}),401
    d=request.get_json(force=True)
    item={"id":str(uuid.uuid4())[:8],"name":d.get("name","Item"),"price":float(d.get("price",3.5))}
    m.setdefault("items",[]).append(item)
    return jsonify(item),201

@app.route("/api/merchant/budget", methods=["POST"])
def set_budget():
    mid,m=_auth()
    if not m:return jsonify({"error":"Unauthorized"}),401
    d=request.get_json(force=True)
    m["budget"]=float(d.get("budget",m.get("budget",20)))
    m["quiet_start"]=d.get("quiet_start",m.get("quiet_start","14:00"))
    m["quiet_end"]=d.get("quiet_end",m.get("quiet_end","17:00"))
    return jsonify({"budget":m["budget"],"quiet_start":m["quiet_start"],"quiet_end":m["quiet_end"],
        "spent_today":m.get("spent_today",0)})

@app.route("/api/merchant/dashboard", methods=["GET"])
def dashboard():
    mid,m=_auth()
    if not m:
        # Unauthenticated: return global stats
        return jsonify({"total_redemptions":len(REDEMPTIONS),"total_auctions":len(AUCTIONS),
            "subscribers":len(PUSH_SUBS),"events":EVENT_LOG[-20:]})
    my_auctions=[a for a in AUCTIONS.values() if a.get("merchant_id")==mid]
    my_reds=[r for r in REDEMPTIONS if any(a["id"]==r.get("auction_id") for a in my_auctions)]
    return jsonify({"name":m["name"],"budget":m.get("budget",20),"spent_today":m.get("spent_today",0),
        "redemptions":m.get("redemptions",0),"revenue":round(m.get("revenue",0),2),
        "auctions_run":len(my_auctions),"auctions_redeemed":len(my_reds),
        "conversion_pct":round(len(my_reds)/max(len(my_auctions),1)*100),
        "subscribers_nearby":len(PUSH_SUBS),"items":m.get("items",[]),
        "recent_auctions":my_auctions[-8:],"recent_redemptions":my_reds[-8:]})

# ══════════════════════════════════════════════════════════════════
#  PUSH + QR + SAVINGS + LIVE FEED
# ══════════════════════════════════════════════════════════════════

@app.route("/api/vapid-public",methods=["GET"])
def vpub():return jsonify({"publicKey":VAPID_PUBLIC})

@app.route("/api/push/subscribe",methods=["POST"])
def psub():
    d=request.get_json(force=True);sub=d.get("subscription",{});ep=sub.get("endpoint","")
    if not ep:return jsonify({"error":"no endpoint"}),400
    PUSH_SUBS[ep]={"sub":sub,"lat":d.get("lat",0),"lng":d.get("lng",0),"ts":datetime.now().isoformat()}
    _log("subscribe",{"lat":d.get("lat"),"total":len(PUSH_SUBS)})
    return jsonify({"ok":True,"total_subs":len(PUSH_SUBS)})

@app.route("/api/savings",methods=["GET"])
def savings():
    uid=request.args.get("user_id","anon")
    mine=[r for r in REDEMPTIONS if r.get("user_id")==uid]
    return jsonify({"total_saved":round(CASHBACK.get(uid,0),2),"count":len(mine),"history":mine[-15:]})

@app.route("/api/qr",methods=["GET"])
def qr():
    text=request.args.get("text","")
    if not text:return jsonify({"error":"need text"}),400
    try:
        import qrcode;img=qrcode.make(text,box_size=10,border=2)
        buf=BytesIO();img.save(buf,format="PNG");buf.seek(0)
        return Response(buf.getvalue(),mimetype="image/png")
    except Exception as e:return jsonify({"error":str(e)}),500

@app.route("/api/live",methods=["GET"])
def live_feed():
    """Live data for the pitch dashboard."""
    total_cb=sum(r.get("cashback",0) for r in REDEMPTIONS)
    total_rev=sum(r.get("final",0) for r in REDEMPTIONS)
    return jsonify({"redemptions":len(REDEMPTIONS),"auctions":len(AUCTIONS),
        "subscribers":len(PUSH_SUBS),"merchants":len(MERCHANTS),
        "total_cashback":round(total_cb,2),"total_revenue":round(total_rev,2),
        "events":EVENT_LOG[-30:],"recent_redemptions":REDEMPTIONS[-10:]})

@app.route("/api/health",methods=["GET"])
def health():
    return jsonify({"status":"ok","version":"7.0-time-market","cafes":len(RAW_CAFES),
        "push_subs":len(PUSH_SUBS),"merchants":len(MERCHANTS),"active_auctions":sum(1 for a in AUCTIONS.values() if a["status"]=="sent")})

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
