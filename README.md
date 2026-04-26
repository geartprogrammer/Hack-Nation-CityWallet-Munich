<p align="center">
  <img src="https://img.shields.io/badge/HackNation-2026-black?style=for-the-badge&labelColor=000" />
  <img src="https://img.shields.io/badge/DSV_Gruppe-Challenge_01-C4501C?style=for-the-badge" />
  <img src="https://img.shields.io/badge/815_Cafes-Munich-1A7A3D?style=for-the-badge" />
  <img src="https://img.shields.io/badge/GPT--4o_Vision-Menu_Parsing-111?style=for-the-badge" />
</p>

<br/>

<h1 align="center">
  <img src="https://em-content.zobj.net/source/apple/391/hot-beverage_2615.png" width="36" />
  <br/>
  City Wallet
</h1>

<h3 align="center">Cafes sell their quiet hours. The AI fills their seats.</h3>

<p align="center">
  <a href="https://hacknation-theta.vercel.app/demo.html"><strong>→ Live Demo ←</strong></a>
</p>

<br/>

---

<br/>

## 💡 The Problem

It's 3pm. A cafe has empty tables. A person walks past in the cold. **These two facts never connect.**

Traditional coupons: *"10% off, valid 30 days."* They don't know the weather. They don't know the cafe is empty *right now*. Small merchants can't do algorithmic marketing — they make coffee, not data models.

## ⚡ The Solution

**One button: "Fill my seats."**

```
Merchant taps button
       │
       ▼
AI checks weather ←── Open-Meteo (live)
AI checks demand  ←── Payone transaction density
AI checks who's near ←── GPS
       │
       ▼
AI picks the best menu item
AI sets the optimal discount
AI writes the notification
       │
       ▼
Customer's phone buzzes
       │
       ▼
Tap → see deal → walk in → swipe → cashback ✓
```

The merchant sets **rules** (budget, quiet hours, max discount).
The AI sets **everything else**.

<br/>

## 🎬 See It

<p align="center">
  <a href="https://hacknation-theta.vercel.app/demo.html">
    <img src="https://img.shields.io/badge/Interactive_Demo-Live_on_Vercel-C4501C?style=for-the-badge&logo=vercel&logoColor=white" />
  </a>
</p>

> The demo page shows both apps running live inside phone mockups — merchant on the left, user on the right. The merchant taps "Fill my seats", the AI generates an offer, and it appears on the user's phone. Everything on one page.

<br/>

## 🏪 Merchant Flow

| Step | What happens | Tech |
|:---:|---|---|
| **1** | Photo your menu | GPT-4o Vision reads every item + price |
| **2** | Set limits: €20/day, 2–5pm, max 30% | Stored via API, AI respects bounds |
| **3** | Tap "Fill my seats" | AI picks item, sets discount, sends push |

That's it. One-time setup, then one button forever.

## 📱 User Flow

| Step | What happens |
|:---:|---|
| **1** | Notification arrives: *"☕ Cappuccino €2.62 at Café Riese"* |
| **2** | Tap → price, savings, countdown timer, map directions |
| **3** | Walk in → swipe to confirm → cashback credited |

No app store. No QR codes. No accounts. Just swipe.

<br/>

## 🧮 The Discount Formula

The AI computes every discount dynamically. Nothing is hardcoded.

```python
discount = 12%                    # base
         + 6%  if rain            # Open-Meteo live weather
         + 4%  if temp < 12°C    # cold = need incentive
         + 5%  if tx/hr < 6      # Payone demand proxy
         + 3%  if 2pm–5pm        # dead hours
         = min(total, merchant_max)
```

| Rainy Tuesday 3pm, empty cafe | Sunny Saturday morning, busy |
|:---:|:---:|
| **26% off** | **12% off** |

<br/>

## 🏗 Architecture

```
src/
├── client/
│   ├── app.html            ← User PWA (offer + swipe-to-verify)
│   └── merchant.html       ← Merchant PWA (fill + stats + settings)
├── worker/
│   └── sw.js               ← Service Worker (push + offline cache)
└── assets/                 ← Icons, manifest

api/
├── index.py                ← Flask serverless (Vercel)
│   ├── /api/fill           ← "Fill my seats" — the core auction
│   ├── /api/offer          ← Best offer for user's location
│   ├── /api/arrive         ← Swipe-to-verify redemption
│   ├── /api/parse-menu     ← GPT-4o Vision menu extraction
│   └── /api/push/*         ← Web Push (VAPID)
└── munich_cafes.json       ← 815 real cafes (OpenStreetMap)

config/
├── cities.json             ← Munich / Stuttgart / Berlin (swap without code change)
└── scoring.json            ← Discount formula weights

docs/
├── ARCHITECTURE.md         ← System design + data flow
└── PRIVACY.md              ← GDPR compliance
```

## 📡 Three Modules (Challenge Spec)

### Module 1: Context Sensing

| Signal | Source | Real data? |
|---|---|:---:|
| Weather (temp, rain, UV) | Open-Meteo API | ✅ Live |
| Transaction density | Payone simulation | Simulated |
| User location | Browser Geolocation | ✅ Live |
| Time / day patterns | System clock | ✅ Live |
| Local events | City config | Configurable |

**Configurable**: swap city in `config/cities.json`. No code change needed.

### Module 2: Generative Offer Engine

- **Item selection** → weather × menu (hot drinks when cold, iced when hot)
- **Discount** → computed from 4 context signals, not a fixed number
- **Copy** → AI-written notification text (Groq Llama when available, smart fallback)
- **Menu parsing** → GPT-4o Vision reads photos of menu boards
- **Merchant rules** → budget, quiet hours, max discount. AI operates within bounds.

### Module 3: Seamless Checkout

- Countdown timer = walk time + 2 min
- Swipe-to-verify at the cafe (no QR scanning)
- Cashback credited instantly
- Merchant dashboard: arrivals, revenue, conversion rate

<br/>

## 🔒 Privacy

| | |
|---|---|
| Location | Stays on device. Only used for proximity matching. |
| Accounts | None. Anonymous UUID in localStorage. |
| Tracking | None. No cookies, no analytics, no fingerprinting. |
| Menu photos | Processed by OpenAI, not stored. |
| GDPR | Compliant by architecture, not just policy. |

Full details → [`docs/PRIVACY.md`](docs/PRIVACY.md)

<br/>

## 🛠 Run Locally

```bash
git clone https://github.com/geartprogrammer/HACKNATION.git
cd HACKNATION && pip install -r requirements.txt

# Optional: enable menu photo parsing
export OPENAI_API_KEY=your-key

# Start
cd api && python -c "from index import app; app.run(host='0.0.0.0', port=4000, debug=True)"
```

Open `http://localhost:4000`

## 🧱 Tech Stack

| | |
|---|---|
| Frontend | Vanilla HTML/JS — no framework, <50ms load |
| Backend | Python Flask on Vercel serverless |
| Weather | Open-Meteo (free, no API key) |
| Menu AI | OpenAI GPT-4o Vision |
| Push | Web Push API (VAPID keys) |
| Data | 815 Munich cafes from OpenStreetMap |
| Fonts | Inter + Fraunces |
| Deploy | Vercel (auto-deploy from GitHub) |

<br/>

## 🏦 Why DSV Gruppe

DSV owns **Payone** (payments), **S-Markt & Mehrwert** (merchant portals), and serves **Sparkassen** (savings banks embedded in German communities).

They already have:
- ✅ The merchant relationships
- ✅ The payment infrastructure
- ✅ The local banking trust

They don't have:
- ❌ The AI layer that turns quiet-hour data into filled seats

**City Wallet is that layer.** No new payment infrastructure. No new merchant onboarding. Just intelligence on top of what already exists.

<br/>

---

<p align="center">
  <strong>HackNation 2026 · Munich · Built in 24 hours</strong>
  <br/><br/>
  <a href="https://hacknation-theta.vercel.app/demo.html">
    <img src="https://img.shields.io/badge/Try_the_demo-→-C4501C?style=for-the-badge" />
  </a>
</p>
