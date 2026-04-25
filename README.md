# The Time Market

**Merchants don't set discounts. They sell their quiet hours. The AI buys them.**

> HackNation 2026 · DSV Gruppe Challenge 01 · Generative City-Wallet

---

## What is this?

A cafe is empty at 3pm. A person is walking past in the rain. Traditional marketing can't connect them. The Time Market can.

The merchant sets one thing: **"I'll spend up to €20/day to fill my quiet hours."** That's it. The AI handles everything else — it watches the weather, monitors transaction density (Payone), calculates who nearby is most likely to walk in, computes the optimal discount, generates the offer copy, and pushes it to that one person's phone. Not everyone. Just the one the AI picked.

The user never opens an app. A notification arrives. They tap it. A QR code appears. They walk in, show it. Done.

---

## Architecture

```
MERCHANT                          AI ENGINE                           USER

 Set budget: €20/day         ┌─────────────────────┐
 Set quiet hours: 14-17      │  Context Sensing     │      📱 Phone in pocket
 Add items: Cappuccino €3.50 │  - Weather (real)    │
           │                 │  - Payone tx density  │
           ▼                 │  - 815 Munich cafes   │
 Tap "Run Auction"           │  - Distance/time      │
           │                 └──────────┬────────────┘
           ▼                            │
    ┌──────────────┐                    ▼
    │ Auction API  │──── Score all nearby users ────┐
    │              │     (distance, weather,         │
    │ AI picks ONE │      demand, conversion prob)   │
    │ user. Only   │                                 │
    │ that user    │◄── Winner: score 78, 200m ──────┘
    │ gets it.     │
    └──────┬───────┘
           │
           ▼
    Push notification ──────────────────────────────► 🔔 Lock screen
    "☕ 18% off Cappuccino · 200m away"                    │
                                                           ▼
                                                     Tap → QR code
                                                           │
           ┌───────────────────────────────────────────────┘
           ▼
    Merchant scans QR ── Verified ── Cashback credited ── Dashboard updates
```

---

## Live Demo

| Page | URL | Purpose |
|------|-----|---------|
| **User App** | [/](https://hacknation-theta.vercel.app/) | The customer experience |
| **Merchant App** | [/merchant.html](https://hacknation-theta.vercel.app/merchant.html) | Login, add items, run auctions, scan QR |
| **Pitch Dashboard** | [/pitch.html](https://hacknation-theta.vercel.app/pitch.html) | Projector display with live stats |

---

## How to run locally

```bash
# Clone
git clone https://github.com/geartprogrammer/HACKNATION.git
cd HACKNATION

# Install dependencies
pip install flask qrcode[pil] requests pywebpush py-vapid cryptography

# Start server
cd api && python -c "from index import app; app.run(host='0.0.0.0', port=4000, debug=True)"

# Open in browser
# User:     http://localhost:4000
# Merchant: http://localhost:4000/merchant.html
# Pitch:    http://localhost:4000/pitch.html
```

---

## How to test the full flow

### 1. User App (Phone A)
- Open the app URL
- Allow notifications + location
- You see one offer (or "no offers right now")

### 2. Merchant App (Phone B)
- Open `/merchant.html`
- Register: name + 4-digit PIN
- Go to **Items** tab → add "Cappuccino" at €3.50
- Go to **Auction** tab → select Cappuccino → tap **"Run auction"**
- The AI scores all nearby users, picks the best one, sends a push notification
- You see: "Sent to user 200m away · Score: 78 · Code: TM-A1B2C3D4"

### 3. User receives notification
- Phone A gets a push: "☕ 18% off Cappuccino · 200m away"
- Tap it → app opens → QR code appears (card flips)

### 4. Merchant scans QR
- Go to **Scan** tab → point camera at Phone A's QR
- "✅ Redeemed! Cappuccino · €0.63 cashback"

### 5. Pitch dashboard
- Open `/pitch.html` on a projector
- See the auction + redemption appear in the live feed
- Total cashback counter updates in real time

---

## Challenge requirements fulfilled

### Module 1: Context Sensing Layer
- **Weather**: Real-time from Open-Meteo (temp, rain, UV, humidity, wind)
- **Payone**: Simulated transaction density per merchant, varies by hour
- **Location**: GPS geofencing, distance-gated offers
- **Events**: City calendar (weekend markets, evening events, seasonal)
- **Configurable**: Different cities work via lat/lng, no code change needed

### Module 2: Generative Offer Engine
- **AI Auction**: Scores every nearby user, picks highest conversion probability
- **Dynamic Discount**: Computed from weather + demand + user score + budget
- **Generative Copy**: Headlines, sublines, emotional frames generated from context
- **Merchant Rules**: Budget, quiet hours, max discount — AI handles the rest
- **GDPR**: User location stays on device, only push subscription stored

### Module 3: Seamless Checkout & Redemption
- **QR Code**: Generated per auction, unique code
- **Camera Scanner**: BarcodeDetector API on merchant phone
- **Double-redeem prevention**: Server validates, rejects used codes
- **Cashback**: Credited to user's savings instantly
- **Merchant Dashboard**: Auctions run, redemptions, conversion rate, revenue

### UX Requirements
- **Where?** Push notification on lock screen
- **How?** Emotional-situational ("Rain outside, warm inside. 200m away.")
- **3 seconds?** One card, one headline, one action. Tap to flip to QR.
- **How ends?** Accepted → QR → redeemed. Or just fades. No clutter.

---

## Tech stack

- **Backend**: Python/Flask (Vercel serverless)
- **Frontend**: Vanilla HTML/CSS/JS (no framework, instant load)
- **Push**: Web Push API with VAPID keys
- **QR**: `qrcode` library, BarcodeDetector API for scanning
- **Weather**: Open-Meteo (free, no API key)
- **Data**: 815 real Munich cafes from OpenStreetMap
- **Hosting**: Vercel (auto-deploy from GitHub)

---

## What makes this different

Every other team will build a coupon app with a list of offers. The user browses, picks one, maybe redeems it.

The Time Market inverts this entirely:
1. **The merchant doesn't set a discount.** They set a budget. The AI sets the discount.
2. **The user doesn't browse.** The AI picks them specifically.
3. **The offer doesn't exist in a database.** It's computed in real-time from weather, demand, distance, and conversion probability.
4. **Only one person gets each offer.** It's an auction, not a broadcast.

The result: a merchant taps one button, and the most likely person within 2km gets a notification on their lock screen with a discount the AI calculated is just enough to get them through the door.

---

## Team

Built at HackNation 2026, Munich.
