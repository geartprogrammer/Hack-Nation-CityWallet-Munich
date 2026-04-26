# Privacy & GDPR Compliance

## What data we collect

| Data | Stored where | Purpose | Retention |
|------|-------------|---------|-----------|
| Push subscription endpoint | Server memory | Send notifications | Session only (lost on restart) |
| Approximate location (lat/lng) | Server memory | Match to nearby cafes | Session only |
| Anonymous user ID | Device localStorage | Track savings | On-device only |
| Menu photos | Not stored | Parsed by OpenAI, discarded | Transient |

## What data we DON'T collect

- No names, emails, or phone numbers
- No browsing history
- No purchase history on our server
- No device fingerprinting
- No cookies
- No third-party tracking

## GDPR Principles

- **Data minimization** — we only process what's needed for the next offer
- **Purpose limitation** — location is used only for proximity matching
- **Storage limitation** — nothing persists beyond the server session
- **Privacy by design** — the architecture makes over-collection impossible
- **No profiling** — each offer is generated fresh, not from a user profile

## Production Enhancements

In a production system with persistent storage:
- Explicit consent flow before any data collection
- Right to erasure (delete all data with one tap)
- Data processing agreements with OpenAI and Open-Meteo
- On-device SLM for preference learning (no cloud needed)
- Anonymized aggregate analytics only for merchants
