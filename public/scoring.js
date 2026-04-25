/**
 * ON-DEVICE SCORING ENGINE
 * Everything runs locally. No data leaves the phone.
 * Downloads merchant catalog once, then goes dark.
 */

const ScoringEngine = {
  catalog: [],
  history: [],       // local accept/decline history
  weather: null,     // cached weather
  initialized: false,

  // ── Initialize: one-time download, then local ────────────────

  async init() {
    // Load catalog from server (one time only)
    try {
      const resp = await fetch('/api/catalog');
      this.catalog = await resp.json();
    } catch (e) {
      // Use cached catalog if offline
      const cached = localStorage.getItem('catalog');
      if (cached) this.catalog = JSON.parse(cached);
    }
    // Cache it locally
    localStorage.setItem('catalog', JSON.stringify(this.catalog));

    // Load local history
    const hist = localStorage.getItem('offer_history');
    if (hist) this.history = JSON.parse(hist);

    // Cache weather once
    this.weather = this.getWeatherEstimate();

    this.initialized = true;
    console.log(`[Scoring] Initialized with ${this.catalog.length} merchants. Going dark.`);
    return this.catalog;
  },

  // ── Read all on-device sensors ───────────────────────────────

  async readSensors() {
    const sensors = {
      location: null,
      motion: null,
      light: null,
      battery: null,
      time: new Date(),
      network: null,
      weather: this.weather
    };

    // GPS
    try {
      const pos = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 8000,
          maximumAge: 5000
        });
      });
      sensors.location = {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy
      };
    } catch (e) {
      console.log('[Scoring] GPS unavailable:', e.message);
    }

    // Battery
    try {
      if (navigator.getBattery) {
        const batt = await navigator.getBattery();
        sensors.battery = {
          level: batt.level,
          charging: batt.charging
        };
      }
    } catch (e) {}

    // Network
    if (navigator.connection) {
      sensors.network = {
        type: navigator.connection.type || 'unknown',
        effectiveType: navigator.connection.effectiveType || 'unknown'
      };
    }

    // Motion (snapshot - we track this continuously elsewhere)
    sensors.motion = this.lastMotionState || 'unknown';

    // Ambient light
    sensors.light = this.lastLightLevel || 'unknown';

    return sensors;
  },

  // ── Distance calculation (Haversine) ─────────────────────────

  distanceKm(lat1, lng1, lat2, lng2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLng = (lng2 - lng1) * Math.PI / 180;
    const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLng/2) * Math.sin(dLng/2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  },

  distanceMeters(lat1, lng1, lat2, lng2) {
    return this.distanceKm(lat1, lng1, lat2, lng2) * 1000;
  },

  // ── Time parsing ─────────────────────────────────────────────

  isInQuietHours(merchant, now) {
    const [startH, startM] = merchant.quiet_start.split(':').map(Number);
    const [endH, endM] = merchant.quiet_end.split(':').map(Number);
    const startMin = startH * 60 + startM;
    const endMin = endH * 60 + endM;
    const nowMin = now.getHours() * 60 + now.getMinutes();
    return nowMin >= startMin && nowMin <= endMin;
  },

  nearQuietHours(merchant, now) {
    const [startH, startM] = merchant.quiet_start.split(':').map(Number);
    const startMin = startH * 60 + startM;
    const nowMin = now.getHours() * 60 + now.getMinutes();
    return Math.abs(nowMin - startMin) <= 30;
  },

  // ── Weather estimate (cached, no server call) ────────────────

  getWeatherEstimate() {
    // In production: fetch once from open API, cache for 3 hours
    // For demo: estimate from time of day and month
    const month = new Date().getMonth();
    const hour = new Date().getHours();
    const isCold = month < 3 || month > 9;
    const isDark = hour < 7 || hour > 19;
    return {
      cold: isCold,
      hot: !isCold && month > 4 && month < 9,
      dark: isDark,
      estimated: true
    };
  },

  // ── Motion tracking (call from devicemotion listener) ────────

  lastMotionState: 'unknown',
  motionSamples: [],

  processMotion(event) {
    if (!event.acceleration) return;
    const mag = Math.sqrt(
      (event.acceleration.x || 0) ** 2 +
      (event.acceleration.y || 0) ** 2 +
      (event.acceleration.z || 0) ** 2
    );
    this.motionSamples.push(mag);
    if (this.motionSamples.length > 20) this.motionSamples.shift();

    const avg = this.motionSamples.reduce((a, b) => a + b, 0) / this.motionSamples.length;
    const variance = this.motionSamples.reduce((a, b) => a + (b - avg) ** 2, 0) / this.motionSamples.length;

    if (avg < 0.5 && variance < 0.3) {
      this.lastMotionState = 'still';
    } else if (avg < 3 && variance > 0.5 && variance < 8) {
      this.lastMotionState = 'walking';
    } else if (avg > 3) {
      this.lastMotionState = 'vehicle';
    } else {
      this.lastMotionState = 'moving';
    }
  },

  // ── Light tracking ──────────────────────────────────────────

  lastLightLevel: 'unknown',

  processLight(lux) {
    if (lux > 1000) this.lastLightLevel = 'outdoor_bright';
    else if (lux > 200) this.lastLightLevel = 'outdoor';
    else if (lux > 50) this.lastLightLevel = 'indoor_bright';
    else this.lastLightLevel = 'indoor_dim';
  },

  // ── Dwell time tracking ────────────────────────────────────

  locationHistory: [],

  trackDwell(lat, lng) {
    const now = Date.now();
    this.locationHistory.push({ lat, lng, time: now });
    // Keep last 5 minutes
    const cutoff = now - 300000;
    this.locationHistory = this.locationHistory.filter(p => p.time > cutoff);
  },

  getDwellNear(merchantLat, merchantLng) {
    const nearby = this.locationHistory.filter(p =>
      this.distanceMeters(p.lat, p.lng, merchantLat, merchantLng) < 150
    );
    if (nearby.length < 2) return 0;
    return (nearby[nearby.length - 1].time - nearby[0].time) / 1000; // seconds
  },

  // ── THE SCORING FUNCTION (runs 100% on-device) ──────────────

  scoreAll(sensors) {
    if (!sensors.location) return [];

    const results = [];
    const now = sensors.time;

    // Track dwell
    this.trackDwell(sensors.location.lat, sensors.location.lng);

    for (const merchant of this.catalog) {
      if (merchant.status !== 'live') continue;

      let score = 0;
      const reasons = [];
      const dist = this.distanceMeters(
        sensors.location.lat, sensors.location.lng,
        merchant.lat, merchant.lng
      );

      // ── Distance scoring ───────────────────────────
      if (dist > 2000) continue; // Skip far merchants entirely
      if (dist < 100)       { score += 40; reasons.push('very close'); }
      else if (dist < 300)  { score += 25; reasons.push('nearby'); }
      else if (dist < 500)  { score += 15; reasons.push('walkable'); }
      else if (dist < 1000) { score += 5;  reasons.push('reachable'); }
      else                  { score += 1; }

      // ── Time match ─────────────────────────────────
      if (this.isInQuietHours(merchant, now)) {
        score += 30;
        reasons.push('quiet hours now');
      } else if (this.nearQuietHours(merchant, now)) {
        score += 15;
        reasons.push('quiet hours soon');
      }

      // ── Movement ───────────────────────────────────
      if (sensors.motion === 'still' && dist < 200) {
        score += 20;
        reasons.push('standing nearby');
      } else if (sensors.motion === 'walking') {
        score += 15;
        reasons.push('walking');
      } else if (sensors.motion === 'vehicle') {
        score += 0; // Can't walk in from a vehicle
      }

      // ── Weather ────────────────────────────────────
      if (sensors.weather) {
        if (sensors.weather.cold && merchant.offer_text.toLowerCase().includes('hot')) {
          score += 15;
          reasons.push('cold day + hot drink');
        }
        if (sensors.weather.hot && merchant.offer_text.toLowerCase().includes('cold')) {
          score += 15;
          reasons.push('hot day + cold drink');
        }
      }

      // ── Ambient light ──────────────────────────────
      if (sensors.light === 'outdoor_bright' || sensors.light === 'outdoor') {
        score += 10;
        reasons.push('outdoors');
      } else if (sensors.light === 'indoor_dim' || sensors.light === 'indoor_bright') {
        score -= 10; // Already indoors
      }

      // ── Dwell time ─────────────────────────────────
      const dwell = this.getDwellNear(merchant.lat, merchant.lng);
      if (dwell > 120) {
        score += 20;
        reasons.push('lingering nearby');
      } else if (dwell > 30) {
        score += 10;
        reasons.push('paused nearby');
      }

      // ── User history (local) ───────────────────────
      const accepted = this.history.filter(h => h.merchant_id === merchant.id && h.action === 'accept');
      const declined = this.history.filter(h => h.merchant_id === merchant.id && h.action === 'decline');
      if (accepted.length > 0) {
        score += 15;
        reasons.push('liked before');
      }
      if (declined.length > 1) {
        score -= 20;
        reasons.push('declined before');
      }

      // ── Battery ────────────────────────────────────
      if (sensors.battery && sensors.battery.level < 0.1 && dist > 200) {
        score -= 30;
        reasons.push('low battery + far');
      }

      results.push({
        merchant,
        score,
        distance: Math.round(dist),
        reasons
      });
    }

    // Sort by score descending
    results.sort((a, b) => b.score - a.score);
    return results;
  },

  // ── Record user action (stored locally) ──────────────────────

  recordAction(merchantId, action) {
    this.history.push({
      merchant_id: merchantId,
      action,
      timestamp: Date.now()
    });
    // Keep last 100 actions
    if (this.history.length > 100) this.history = this.history.slice(-100);
    localStorage.setItem('offer_history', JSON.stringify(this.history));
  },

  // ── Generate offer text (on-device) ──────────────────────────

  generateOffer(scored, sensors) {
    const m = scored.merchant;
    const dist = scored.distance;
    const timeStr = sensors.time.getHours() + ':' + String(sensors.time.getMinutes()).padStart(2, '0');

    let line1 = `${m.offer_text}`;
    let line2 = `${m.name} · ${m.area}`;
    let line3 = `${dist}m away`;

    if (sensors.weather && sensors.weather.cold) {
      line3 += ' · warm inside';
    }
    if (scored.reasons.includes('quiet hours now')) {
      line3 += ' · perfect timing';
    }

    return { line1, line2, line3, value: m.offer_value, merchant: m };
  }
};

// Export for use in main page and service worker
if (typeof module !== 'undefined') module.exports = ScoringEngine;
