# PROJECT REAL - Munich Markt
# Setup and Operation Guide (Real Wallet Passes)

This system generates REAL Apple Wallet (.pkpass) and Google Wallet passes
that install in the phone's native wallet and trigger on the lock screen
when the user walks near a cafe. No app. No website to keep open.

---

## WHAT YOU GET

| URL                             | What it does                                             |
|---------------------------------|----------------------------------------------------------|
| `/`                             | Landing page — shows all merchants with wallet buttons   |
| `/pass/cafe-riese`              | Auto-detects iOS/Android, serves the correct pass type   |
| `/pass/apple?merchant=cafe-riese` | Downloads a real .pkpass file (Apple Wallet)            |
| `/pass/google?merchant=cafe-riese`| Redirects to Google Wallet save link                   |
| `/merchant`                     | Merchant console — redeem codes, see stats               |
| `/ledger`                       | Live pitch dashboard — projector display                 |

---

## QUICK START (no certs, inspection mode)

Even without Apple/Google credentials, you can generate and inspect passes.

### Step 1: Start the server

```
cd C:\Users\geart.ferhati\Desktop\HACKNATION
set PORT=4000
python server/index.py
```

### Step 2: Find your IP

```
ipconfig
```
Use the IPv4 address (e.g., 192.168.101.173).

### Step 3: Download a test pass

Open in browser:
```
http://localhost:4000/pass/apple?merchant=cafe-riese
```

This downloads `cafe-riese.pkpass`. Rename it to `.zip` and extract to see:
- `pass.json` — the full pass definition with geofence locations
- `manifest.json` — SHA1 hashes of every file
- `icon.png`, `icon@2x.png` — pass icons
- (No `signature` file yet — needs Apple certs)

### Step 4: Test the live ledger

Open `http://localhost:4000/ledger` on a browser.
Open `http://localhost:4000/merchant` on another tab, select a merchant, tap "Quick Redeem."
Watch the ledger update in real time.

---

## MAKING IT REAL: APPLE WALLET

To install passes on actual iPhones, you need Apple Developer credentials.

### What you need

1. **Apple Developer account** ($99/year) — https://developer.apple.com
2. **Pass Type ID** — register at developer.apple.com/account
3. **Pass signing certificate** — create in the Certificates section
4. **Apple WWDR G4 certificate** — download from Apple

### Step-by-step cert setup

#### A. Create a Pass Type ID

1. Go to https://developer.apple.com/account/resources/identifiers/list/passTypeId
2. Click "+" to register a new Pass Type ID
3. Description: "Munich Markt Offers"
4. Identifier: `pass.com.munichmarkt.offer`
5. Save it

#### B. Create a signing certificate

1. Go to Certificates section
2. Click "+" → select "Pass Type ID Certificate"
3. Select your Pass Type ID from the dropdown
4. Follow the steps to create a CSR (Certificate Signing Request) using Keychain Access on Mac:
   - Open Keychain Access → Certificate Assistant → Request a Certificate from a CA
   - Enter your email, name, select "Saved to disk"
5. Upload the CSR to Apple
6. Download the certificate (.cer file)

#### C. Export as PEM files

On your Mac:
```bash
# Double-click the .cer to import into Keychain Access
# Then export as .p12:
# Keychain Access → My Certificates → right-click the pass cert → Export

# Convert .p12 to PEM:
openssl pkcs12 -in pass_cert.p12 -clcerts -nokeys -out server/certs/pass_cert.pem
openssl pkcs12 -in pass_cert.p12 -nocerts -out server/certs/pass_key.pem
```

#### D. Download the Apple WWDR certificate

```bash
curl -o server/certs/wwdr.pem https://www.apple.com/certificateauthority/AppleWWDRCAG4.cer
openssl x509 -inform DER -in server/certs/wwdr.pem -out server/certs/wwdr.pem
```

#### E. Set environment variables

```bash
set PASS_TYPE_ID=pass.com.munichmarkt.offer
set TEAM_ID=YOUR_TEAM_ID_HERE
set PASS_KEY_PASSWORD=your_key_password
```

#### F. Test on a real iPhone

1. Start the server
2. On the iPhone (same WiFi), open: `http://192.168.x.x:4000/pass/apple?merchant=cafe-riese`
3. The .pkpass downloads
4. iOS prompts "Add to Apple Wallet?"
5. Tap "Add"
6. The pass is now in your wallet with the cafe's GPS coordinates
7. Walk near the coordinates — the pass appears on your lock screen

### What the pass does on the iPhone

- **Geofence trigger**: When you're within ~100m of the cafe's coordinates,
  iOS surfaces the pass on the lock screen with the `relevantText` message
- **Time relevance**: Combined with `relevantDate`, the pass only triggers
  during the merchant's quiet hours
- **Barcode**: The QR code on the pass contains the redemption code
- **Live updates**: If `webServiceURL` is set, iOS periodically checks for
  pass updates (new offer, status change, voided)

---

## MAKING IT REAL: GOOGLE WALLET

### What you need

1. **Google Cloud project** — https://console.cloud.google.com
2. **Google Wallet API enabled** — search "Google Wallet API" in the console
3. **Service account** with a JSON key
4. **Issuer ID** from https://pay.google.com/business/console

### Step-by-step

#### A. Enable the API

1. Go to Google Cloud Console
2. Create a project (or use existing)
3. Search for "Google Wallet API" and enable it

#### B. Create a service account

1. Go to IAM & Admin → Service Accounts
2. Create a service account
3. Grant it the "Wallet Object Creator" role
4. Create a key (JSON format)
5. Save as `server/certs/google_service_account.json`

#### C. Get your Issuer ID

1. Go to https://pay.google.com/business/console
2. Your Issuer ID is in the top left (a long number)

#### D. Set environment variables

```bash
set GOOGLE_ISSUER_ID=3388000000000000000
```

#### E. Test

1. On an Android phone (same WiFi), open:
   `http://192.168.x.x:4000/pass/google?merchant=cafe-riese`
2. It redirects to the Google Wallet save page
3. Tap "Save"
4. The pass is in Google Wallet

### What the pass does on Android

- **Location trigger**: Google Wallet monitors the pass's GPS coordinates
  and shows a notification when the user is nearby
- **Barcode**: QR code for redemption
- **Time window**: The pass shows as active only during valid hours

---

## CERT FILES SUMMARY

Place these in `server/certs/`:

```
server/certs/
  pass_cert.pem              ← Apple pass signing certificate
  pass_key.pem               ← Private key for the certificate
  wwdr.pem                   ← Apple WWDR G4 intermediate cert
  google_service_account.json ← Google Cloud service account key
```

---

## MERCHANT SIDE: WHAT THE CAFE OWNER DOES

### Initial setup (you do this for them)

1. Open `http://YOUR-IP:4000/merchant` on the cafe's phone/tablet
2. Go to the "Setup" tab
3. Enter:
   - Cafe name
   - Area (neighborhood)
   - Quiet hours (start and end time)
   - Offer text and value
4. Tap "Use my current location" (do this while AT the cafe)
5. Tap "Save merchant"

### Daily operation

1. Open the merchant console
2. Select their cafe from the dropdown
3. When a customer shows a pass with a QR code:
   - Type the code → tap "Redeem"
   - OR scan it with any QR scanner app, paste the code
4. The "Stats" tab shows walk-ins and revenue

### What you give the merchant

Print a QR poster that points to:
```
http://YOUR-PUBLIC-URL/pass/{merchant-id}
```

When people scan it, they get the wallet pass for that cafe.

For a public URL, use ngrok:
```
ngrok http 4000
```

---

## IN-ROOM DEMO AND VERIFICATION

### Setup for demo

1. **Computer** — run server, open Live Ledger (`/ledger`) on projector
2. **Phone A** (the "user") — scan QR or open `/pass/cafe-riese`
3. **Phone B** (the "merchant") — open `/merchant`

### Demo flow

1. Open the Live Ledger on the projector — dark dashboard, EUR 0.00
2. On Phone A, open the landing page — tap "Add to Apple Wallet" or "Google Wallet"
3. The pass installs in the native wallet
4. The ledger's opt-in counter increases (SSE update)
5. On Phone B, select the merchant, tap "Quick Redeem"
6. The ledger's revenue counter jumps instantly
7. Repeat — the numbers climb while you talk

### Verifying the pass is real

1. Download the .pkpass from `/pass/apple?merchant=cafe-riese`
2. Rename to `.zip`, extract
3. Open `pass.json` — show the `locations` array with real GPS coordinates
4. Show the `barcode` field with the redemption code
5. Show `webServiceURL` — this is how Apple checks for updates
6. On a real iPhone (with certs): show the pass in Apple Wallet
7. Show the lock screen notification when near the coordinates

### Verifying on-device privacy

The pass has GPS coordinates baked INTO the pass file. The phone's OS
handles the geofencing. No server call is made when the user walks near
a cafe. The only outbound call is:
- Apple: periodic check to `webServiceURL` for pass updates (optional)
- The redemption event when the user explicitly shows their code

---

## API REFERENCE

| Method | Endpoint                                 | Purpose                          |
|--------|------------------------------------------|----------------------------------|
| GET    | `/pass/apple?merchant={id}`              | Generate and download .pkpass    |
| GET    | `/pass/google?merchant={id}`             | Redirect to Google Wallet save   |
| GET    | `/pass/{merchant-id}`                    | Auto-detect device, show pass page|
| GET    | `/api/merchants`                         | List all merchants               |
| POST   | `/api/merchants`                         | Add a new merchant               |
| GET    | `/api/catalog`                           | Minimal merchant data            |
| GET    | `/api/ledger`                            | Full ledger snapshot             |
| GET    | `/api/stream`                            | SSE stream for live updates      |
| POST   | `/api/redeem`                            | Redeem an offer                  |
| POST   | `/api/reset`                             | Reset all data to demo defaults  |

### Apple Wallet Update Protocol (automatic)

| Method | Endpoint                                                    | Purpose                |
|--------|-------------------------------------------------------------|------------------------|
| POST   | `/api/passes/v1/devices/{did}/registrations/{type}/{serial}`| Device registers pass  |
| GET    | `/api/passes/v1/devices/{did}/registrations/{type}`         | Get serials for device |
| GET    | `/api/passes/v1/passes/{type}/{serial}`                     | Get latest pass version|
| DELETE | `/api/passes/v1/devices/{did}/registrations/{type}/{serial}`| Device removes pass    |
| POST   | `/api/passes/v1/log`                                        | Apple sends error logs |

---

## FILE STRUCTURE

```
HACKNATION/
  server/
    index.py              ← Main server (API + static files + pass endpoints)
    apple_pass.py         ← Apple Wallet .pkpass generator
    google_pass.py        ← Google Wallet JWT/save link generator
    certs/                ← Your signing certificates go here
    passes/               ← Generated .pkpass files (for inspection)
  public/
    index.html            ← Landing page with wallet buttons per merchant
    pass.html             ← Device-detecting pass install page
    merchant.html         ← Merchant console (redeem, stats, setup)
    ledger.html           ← Live pitch dashboard (projector)
    scoring.js            ← On-device scoring engine (for future PWA layer)
    sw.js                 ← Service worker
    manifest.json         ← PWA manifest
  REVIEW.md               ← This file
```

---

## TROUBLESHOOTING

### "Pass won't install on iPhone"
- You need valid Apple signing certs in `server/certs/`
- The .pkpass MUST be signed with a real Pass Type ID certificate
- Test by renaming .pkpass to .zip — check for `signature` file

### "Google Wallet link doesn't work"
- You need a Google Cloud service account + Issuer ID
- The JWT must be signed with the service account's private key
- Check the browser console for errors

### "Geofence doesn't trigger on lock screen"
- The pass's `locations` array must have valid coordinates
- You must be within ~100m of those coordinates
- On iOS: check Settings → Privacy → Location Services → Wallet is enabled
- It can take a few minutes for the OS to notice you're in the geofence
- Make sure the pass isn't expired (check `relevantDate`)

### "Live ledger doesn't update"
- Refresh the page
- Check the server terminal for errors
- The SSE connection auto-reconnects after 3 seconds
