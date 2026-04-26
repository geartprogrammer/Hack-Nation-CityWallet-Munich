# Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────┐
│                    CLIENT LAYER                           │
│                                                           │
│  ┌─────────────────┐     ┌─────────────────────┐        │
│  │   User PWA       │     │   Merchant PWA       │        │
│  │   src/client/    │     │   src/client/         │        │
│  │   app.html       │     │   merchant.html       │        │
│  └────────┬─────────┘     └────────┬──────────────┘        │
│           │                        │                       │
│  ┌────────┴────────────────────────┴──────────────┐       │
│  │              Service Worker                     │       │
│  │              src/worker/sw.js                   │       │
│  │              Push notifications + caching       │       │
│  └────────────────────┬───────────────────────────┘       │
└───────────────────────┼───────────────────────────────────┘
                        │ HTTPS
┌───────────────────────┼───────────────────────────────────┐
│                 API LAYER (Vercel Serverless)              │
│                                                           │
│  ┌────────────────────────────────────────────────┐       │
│  │              api/index.py (Flask)               │       │
│  │                                                 │       │
│  │  /api/offer      → Context engine + generation  │       │
│  │  /api/fill       → Merchant auction trigger     │       │
│  │  /api/arrive     → User redemption              │       │
│  │  /api/parse-menu → GPT-4o Vision menu parsing   │       │
│  │  /api/push/*     → Web Push (VAPID)             │       │
│  └────────────┬──────────────┬────────────────────┘       │
│               │              │                            │
│  ┌────────────┴──┐  ┌───────┴──────────┐                 │
│  │ munich_cafes  │  │ Open-Meteo API   │                 │
│  │ .json (815)   │  │ (weather, UV,    │                 │
│  │ OSM data      │  │  air quality)    │                 │
│  └───────────────┘  └──────────────────┘                 │
└───────────────────────────────────────────────────────────┘
```

## Data Flow: "Fill My Seats"

1. Merchant taps "Fill my seats"
2. API checks weather (Open-Meteo), simulates Payone demand
3. AI picks best menu item for current conditions
4. AI computes discount from weather + demand + time
5. AI generates notification copy
6. Push notification sent to nearby users (Web Push / VAPID)
7. User taps notification → redeem screen with countdown
8. User swipes to confirm arrival
9. Cashback credited

## Key Design Decisions

- **No database** — in-memory state for hackathon speed. Production would use Supabase/Postgres.
- **No app store** — PWA installed from browser. Zero friction.
- **No QR scanning** — swipe-to-verify replaces it. Simpler.
- **No user accounts** — anonymous UUID. GDPR-friendly.
- **Menu via camera** — GPT-4o Vision parses photos. No manual data entry.
