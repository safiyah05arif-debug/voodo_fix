# CIVIX (FixMyCity) 🏙️

An end-to-end, crowdsourced civic issue reporting and tracking platform designed for hackathons. Connects citizens, municipal officers, and field workers in real-time with automated AI classification, spatial deduplication, dynamic priority scoring, and strict SLA management.

---

## 📌 CRITICAL ARCHITECTURAL REQUIREMENTS & NOTES

### 1. 📸 Direct In-Browser Camera & Live Geolocation Capture
> **MANDATORY CITIZEN REPORTING WORKFLOW:**
> - **Direct In-Browser Camera Stream:** When a citizen reports an issue, the web app must directly access the device camera stream (`navigator.mediaDevices.getUserMedia` with `facingMode: "environment"`) rendered inside a live `<video>` viewfinder—**not** just a standard file/gallery picker.
> - **Simultaneous Geolocation Capture:** Geolocation (`navigator.geolocation`) must be active in real-time. When the user taps the **Capture** button, the camera frame snapshot (via `<canvas>`) and the exact GPS coordinates (`[longitude, latitude]`) are captured **simultaneously in a single atomic action**.
> - **Anti-Tampering:** Ensures real-time on-site reporting with authentic coordinates rather than pre-downloaded images from unknown locations.

---

## 🛠️ Tech Stack & Integrations

- **Backend:** Python 3.10+ with Django & Django REST Framework (DRF)
- **Database:** MongoDB Atlas (via MongoEngine & PyMongo ODM) with `2dsphere` spatial indexing
- **Storage:** Supabase Storage (`civix-uploads` bucket) for CDN photo hosting
- **Interactive Maps:** Leaflet.js + OpenStreetMap + `Leaflet.heat` for city heatmaps
- **AI Vision Engine:** OpenAI GPT-4o / Google Gemini Flash for image classification (`{category, issue_type, severity, confidence}`)
- **Accessibility Layer:**
  - Web Speech API: Voice-to-text (STT) and Text-to-speech (TTS) in English & Tamil (`ta-IN`)
  - Bilingual localization toggle (English & Tamil)
  - High-contrast mode toggle (WCAG AAA compliant) & font resizer (A, A+, A++)

---

## 👥 Target User Roles & Portals

### 1. 📱 Citizen Portal (`citizen.html`)
- **Direct Camera & Auto-GPS Reporting:** Real-time viewfinder + instant GPS capture + voice-to-text description (English/Tamil).
- **Spatial Deduplication Prompt:** 50m radius MongoDB `$near` query prompts upvoting an existing ticket instead of creating duplicates.
- **Verification & Reopening:** Nearby citizens verify if a "Resolved" issue is genuinely fixed; triggers auto-reopen if rejected.
- **Gamification Dashboard:** Civic points, levels, and milestone badges (e.g. *First Report*, *Watchdog*, *Community Hero*).

### 2. 🖥️ Municipal Officer Command Center (`officer.html`)
- **Interactive City Heatmap:** Leaflet heatmap colored by priority/severity (🔴 Critical, 🟠 High, 🟡 Medium, 🟢 Low).
- **Master Ticket Queue:** Grouped duplicate tickets, AI classification confidence, dynamic worker assignment dropdowns.
- **SLA Alert Engine:** Real-time countdown timers with pulsing red visual warnings for breached deadlines.

### 3. 👷 Field Worker Mobile App (`worker.html`)
- **Optimized Task List:** Sorted by Dynamic Priority Score + real-time distance from worker's GPS.
- **Proof-of-Work Closing:** Mandatory "After" photo upload + Geo-fencing validation (worker must be within 50m of the issue).

---

## ⚙️ Core Engines & Mathematical Formulas

### 1. Dynamic Priority Score Calculator
$$\text{Priority Score} = (\text{Severity Weight} \times 40) + (\text{Upvotes} \times 20) + (\text{Hours Pending} \times 10) + (\text{Location Risk} \times 30)$$
- **Severity Weights:** Critical = 4, High = 3, Medium = 2, Low = 1
- **Location Risk Factor:** 1.0 to 5.0 (e.g., School zones = 5.0, Highways = 4.0, Residential = 2.0)

### 2. SLA Escalation Engine
- **Critical:** 24 Hours
- **High:** 48 Hours
- **Medium:** 72 Hours
- **Low:** 168 Hours (7 Days)
- Overdue tickets auto-escalate from Field Worker $\rightarrow$ Zone Officer $\rightarrow$ Commissioner.

---

## 🚀 Quickstart & Verification

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials in .env
# (MONGODB_URI, SUPABASE_URL, SUPABASE_SECRET_KEY, etc.)

# Free AI option: create a Gemini API key in Google AI Studio, then set:
# AI_PROVIDER=gemini
# GEMINI_API_KEY=your-key
# GEMINI_MODEL=gemini-2.0-flash
# OpenAI is optional; the app falls back to local heuristics if AI quota is unavailable.

# Offline image detection (after installing the optional packages):
# pip install -r requirements.txt
# Download a YOLO model once, then set YOLO_MODEL_PATH to its local path.
# OFFLINE_VISION=yolo

# 3. Test MongoDB Atlas Connection
python test_connection.py

# 4. Test Supabase Photo Storage
python test_storage.py

# 5. Populate 25 realistic demo issues in Chennai
python seed_data.py
```
