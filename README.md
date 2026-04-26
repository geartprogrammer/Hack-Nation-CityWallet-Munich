<p align="center">
  <img src="https://img.shields.io/badge/HackNation-2026-black?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Challenge_01-DSV_Gruppe-C4501C?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Status-Live-1A7A3D?style=for-the-badge" />
</p>

<h1 align="center">City Wallet</h1>
<h3 align="center"><em>Cafes sell their quiet hours. The AI fills their seats.</em></h3>

<p align="center">
  <a href="https://hacknation-theta.vercel.app/"><strong>Live Demo</strong></a> ·
  <a href="https://hacknation-theta.vercel.app/src/client/merchant.html"><strong>Merchant App</strong></a> ·
  <a href="#demo-videos"><strong>Demo Videos</strong></a> ·
  <a href="docs/ARCHITECTURE.md"><strong>Architecture</strong></a>
</p>

---

## The Problem

A cafe is empty at 3pm. A person walks past in the cold. These two facts never connect. Traditional coupons are static ("10% off, valid 30 days"). They don't know the weather, the time, or that the cafe has empty seats *right now*.

## The Solution

**One button: "Fill my seats."**

The merchant taps it. The AI handles the rest.

```
Merchant taps "Fill my seats"
         │
         ▼
   ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
   │   Weather    │     │    Payone     │     │   Nearby    │
   │  Open-Meteo  │     │  tx density   │     │   users     │
   │   (live)     │     │  (simulated)  │     │   (GPS)     │
   └──────┬───────┘     └──────┬────────┘     └──────┬──────┘
          └────────────────────┼─────────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │     AI ENGINE       │
                    │                     │
                    │  Picks best item    │
                    │  Sets discount      │
                    │  Writes message     │
                    └──────────┬──────────┘
                               ▼
                    Push notification sent
                               │
                               ▼
                    User taps → countdown starts
                               │
                               ▼
                    Walks in → swipes to verify
                               │
                               ▼
                    Cashback credited ✓
```

## Demo Videos

<a name="demo-videos"></a>

| Demo | Link |
|------|------|
| User flow | [VIDEO_LINK_USER] |
| Merchant flow | [VIDEO_LINK_MERCHANT] |
| Full end-to-end | [VIDEO_LINK_FULL] |

## How It Works

### User (30 seconds)

1. **Install** — add to homescreen. No app store.
2. **Notification arrives** — "☕ Cappuccino €2.62 at Café Riese. 3 min walk."
3. **Tap → see the deal** — price, savings, countdown timer, map.
4. **Walk in → swipe** — cashback credited.

### Merchant (60 seconds)

1. **Register** — name + PIN.
2. **Photo your menu** — GPT-4o Vision reads it. Every item + price extracted.
3. **Set limits** — daily budget, quiet hours, max discount.
4. **Tap "Fill my seats"** — AI picks item, sets discount, sends notification. Done.

## The Discount Formula

```
base = 12%
+ rain      → +6%     (from Open-Meteo)
+ cold      → +4%     (temperature < 12°C)
+ quiet     → +5%     (Payone tx < 6/hr)
+ dead hour → +3%     (2pm–5pm)
─────────────────────
= capped at merchant's max (default 30%)
```

**Rainy Tuesday, 3pm, empty cafe → 26% off.**
**Sunny Saturday morning, busy → 12% off.**

## Three Modules

### 1. Context Sensing

| Signal | Source | Effect |
|--------|--------|--------|
| Weather | Open-Meteo (live) | Cold → hot drinks. Rain → bigger discount. |
| Demand | Payone simulation | Quiet → trigger offers |
| Location | GPS | Only nearby users |
| Time | Clock | Dead hours → more aggressive |

Config-driven. Swap city in [`config/cities.json`](config/cities.json), no code change.

### 2. Generative Offer Engine

Offers don't exist in a database. They're **created** at runtime:
- Item picked from weather × menu
- Discount computed from context signals
- Copy generated ("It's 8°. Warm Cappuccino for €2.62.")
- Menu parsed from photo via GPT-4o Vision

Scoring weights in [`config/scoring.json`](config/scoring.json).

### 3. Seamless Checkout

- Countdown timer (walk time + 2 min buffer)
- Swipe-to-verify at the cafe
- Cashback credited instantly
- No QR scanning needed

## Privacy

- Location stays on device
- No accounts, no emails, no tracking
- Anonymous UUIDs only
- GDPR compliant by architecture

Full details: [`docs/PRIVACY.md`](docs/PRIVACY.md)

## Project Structure

```
city-wallet/
├── api/
│   ├── index.py              # Flask API — all three modules
│   └── munich_cafes.json     # 815 real cafes (OpenStreetMap)
├── src/
│   ├── client/
│   │   ├── app.html          # User PWA
│   │   └── merchant.html     # Merchant PWA
│   ├── worker/
│   │   └── sw.js             # Service worker (push + cache)
│   └── assets/
│       ├── manifest.json     # PWA manifest
│       ├── icon-192.png      # App icon
│       └── icon-512.png      # App icon
├── config/
│   ├── cities.json           # City configuration (Munich, Stuttgart, Berlin)
│   └── scoring.json          # Discount formula + AI weights
├── docs/
│   ├── ARCHITECTURE.md       # System design + data flow
│   └── PRIVACY.md            # GDPR compliance
├── index.html                # Entry point (phone mockup on desktop)
├── vercel.json               # Deployment config
├── requirements.txt          # Python dependencies
└── README.md
```

## Run Locally

```bash
git clone https://github.com/geartprogrammer/HACKNATION.git
cd HACKNATION
pip install -r requirements.txt
export OPENAI_API_KEY=your-key  # optional — for menu photo parsing
cd api && python -c "from index import app; app.run(host='0.0.0.0', port=4000, debug=True)"
```

Open `http://localhost:4000`

## Tech Stack

| | |
|---|---|
| **Frontend** | Vanilla HTML/JS — no framework, <50ms load |
| **Backend** | Python Flask on Vercel serverless |
| **Weather** | Open-Meteo (free, no API key) |
| **Menu parsing** | OpenAI GPT-4o Vision |
| **Notifications** | Web Push API (VAPID) |
| **Data** | 815 Munich cafes from OpenStreetMap |
| **Deploy** | Vercel (auto-deploy from GitHub) |

## Why DSV Gruppe

DSV owns **Payone** (payment processing), **S-Markt & Mehrwert** (merchant portals), and serves **Sparkassen** (savings banks in local communities). They have the merchant relationships and the payment rails. City Wallet is the **AI layer** that turns their quiet-hour data into filled seats. No new infrastructure — just intelligence on top of what exists.

---

<p align="center">
  <strong>HackNation 2026 · Munich · DSV Gruppe Challenge 01</strong><br/>
  <em>Built in 24 hours.</em>
</p>
