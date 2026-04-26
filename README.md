<p align="center">
  <img src="https://img.shields.io/badge/HackNation-2026-black?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Challenge_01-DSV_Gruppe-C4501C?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Status-Live-1A7A3D?style=for-the-badge" />
</p>

<h1 align="center">City Wallet</h1>
<h3 align="center"><em>Cafes sell their quiet hours. The AI fills their seats.</em></h3>

<p align="center">
  <strong>
    <a href="https://hacknation-theta.vercel.app/">User App</a> ·
    <a href="https://hacknation-theta.vercel.app/merchant.html">Merchant App</a> ·
    <a href="https://hacknation-theta.vercel.app/pitch.html">Pitch Dashboard</a>
  </strong>
</p>

---

## The Problem

A cafe is empty at 3pm. A person is walking past in the cold. These two facts never connect.

Traditional coupons are static ("10% off, valid 30 days"). They don't know the weather, the time, or that the cafe has empty seats *right now*. Small merchants can't compete with the algorithmic precision of Amazon or Uber — they don't have data scientists. They have a coffee machine and empty chairs.

## The Solution

**One button: "Fill my seats."**

The merchant taps it. The AI does everything else:

```
Merchant taps button
       ↓
AI checks weather ← Open-Meteo (real data)
AI checks demand  ← Payone transaction simulation
AI checks who's near ← user GPS
       ↓
AI picks the best menu item (hot drinks when cold, iced when hot)
AI sets the discount (bigger when it's raining + quiet)
AI writes the notification text
       ↓
User gets a push notification
       ↓
User taps → sees the deal → countdown timer starts
       ↓
User walks in → swipes to confirm arrival
       ↓
Cashback credited. Cafe got a customer. Done.
```

## How It Works

### For the user

1. **Install** — add to homescreen from browser. No app store.
2. **Wait** — the app is invisible until the moment matters.
3. **Notification arrives** — "☕ Cappuccino €2.62 at Café Riese. 3 min walk."
4. **Tap → see the deal** — price, savings, countdown timer, map directions.
5. **Walk in → swipe to confirm** — cashback credited.

### For the merchant

1. **Register** — name + PIN. That's the account.
2. **Upload menu** — take a photo of the menu. GPT-4o Vision reads it and extracts every item + price.
3. **Set limits** — daily budget (€20), quiet hours (2-5pm), max discount (30%).
4. **Tap "Fill my seats"** — one button. The AI runs an auction: picks the item, sets the price, writes the message, sends it.
5. **Watch arrivals** — see customers walk in on your dashboard.

## The Three Modules

### 1. Context Sensing

| Signal | Source | How it's used |
|--------|--------|--------------|
| Weather | Open-Meteo (live) | Cold → hot drinks, rain → bigger discount |
| Demand | Payone simulation | Quiet period → trigger offers |
| Location | User GPS | Only nearby users get notified |
| Time | System clock | Afternoon dead hours → more aggressive |
| Events | City calendar | Weekend markets, live music → adjust |

All signals are **configurable** — swap city, change parameters, no code change needed.

### 2. Generative Offer Engine

The AI doesn't retrieve offers from a database. It **creates** them:

- **Item selection** — picks from the merchant's menu based on weather + time
- **Discount calculation** — 12% base + rain (+6%) + cold (+4%) + quiet demand (+5%) + dead hours (+3%) = dynamic price
- **Copy generation** — "It's 8°. Warm Cappuccino for €2.62 at Café Riese. 🔥"
- **Notification delivery** — push via Web Push API (VAPID)

The merchant sets **rules** (budget, max discount, quiet hours). The AI sets **everything else**.

### 3. Seamless Checkout

- User sees the offer → countdown timer starts (walk time + 2 min)
- Walks to the cafe → swipe-to-verify confirms arrival
- Cashback credited to their savings
- Merchant sees the arrival on their dashboard
- No QR scanning needed — just swipe

## The Discount Formula

```
base = 12%
+ rain      → +6%
+ cold      → +4%
+ quiet     → +5%  (Payone tx < 6/hr)
+ dead hour → +3%  (2pm-5pm)
= capped at merchant's max (default 30%)
```

Rainy Tuesday at 3pm with an empty cafe: **26% off**.
Sunny Saturday morning, cafe is busy: **12% off**.

## Privacy (GDPR)

- Location stays on the user's device
- Push subscription is the only thing stored server-side (no name, no email)
- Merchant never sees who the user is
- No tracking, no profiles, no cookies

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | Vanilla HTML/CSS/JS — no framework, instant load |
| Backend | Python/Flask on Vercel serverless |
| Weather | Open-Meteo API (free, no key) |
| Menu parsing | OpenAI GPT-4o Vision |
| Notifications | Web Push API (VAPID) |
| Data | 815 real Munich cafes from OpenStreetMap |
| Hosting | Vercel (auto-deploy from GitHub) |

## Run Locally

```bash
git clone https://github.com/geartprogrammer/HACKNATION.git
cd HACKNATION
pip install flask qrcode[pil] requests pywebpush py-vapid cryptography
export OPENAI_API_KEY=your-key  # optional, for menu photo parsing
cd api && python -c "from index import app; app.run(host='0.0.0.0', port=4000, debug=True)"
```

Open `http://localhost:4000` (user) and `http://localhost:4000/merchant.html` (merchant).

## Why DSV Gruppe

DSV Gruppe owns **Payone** (payments), **S-Markt & Mehrwert** (merchant portals), and serves **Sparkassen** (savings banks embedded in local communities). They already have the merchant relationships and the payment rails. What they don't have is the **AI layer** that turns a quiet cafe into a filled cafe. That's City Wallet.

No new payment infrastructure needed. No new merchant onboarding. Just an AI layer on top of what already exists.

---

<p align="center">
  <strong>HackNation 2026 · Munich · DSV Gruppe Challenge 01</strong><br/>
  <em>Built in 24 hours.</em>
</p>
