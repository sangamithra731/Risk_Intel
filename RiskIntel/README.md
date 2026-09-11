# RISKintel — AI-Powered Multi-Hazard Intelligence & Disaster Response Platform

> **PROTOTYPE BUILD: SIMULATED / SYNTHETIC DATA ONLY**  
> *This platform uses clearly labeled synthetic/demo data and prototype AI regression models. It does not claim real-time disaster prediction or guaranteed warning accuracy and is not connected to real civil defense sirens.*

---

## 1. Overview & Core Mission

**RISKintel** is an integrated disaster-management command platform engineered for high-altitude multi-hazard monitoring (specifically Glacial Lake Outburst Floods — GLOFs), automated AI risk inference, downstream impact analysis, authority-cleared warning broadcasts, and unified tactical response operations.

### End-to-End Operational Workflow:
```
MONITOR ──► ANALYZE ──► PREDICT ──► WARN ──► COORDINATE ──► RESPOND ──► RECOVER
```
- **MONITOR**: Ingests multi-sensor hydrological telemetry (water levels, glacier stability, ice melt rates, rainfall, seismic tremors, and terrain displacement).
- **ANALYZE & PREDICT**: A scikit-learn Random Forest model calculates a composite GLOF risk score (0–100), severity tier (LOW, MODERATE, HIGH, CRITICAL), and statistical feature attribution.
- **WARN**: Elevated risk triggers automated early-warning recommendations requiring manual Authority review and clearance.
- **COORDINATE & RESPOND**: Cleared alerts activate evacuation plans, deploy NDRF/SDRF rescue teams, log civilian SOS distress beacons, and manage refuge shelters.
- **RECOVER**: Tracks infrastructure lifelines (dams, bridges, roads, power, hospitals) and resource consumption through recovery.

---

## 2. Technology Stack

- **Backend**: Python 3.11+, Flask 3.1, Flask-SQLAlchemy 3.1, Flask-CORS, Werkzeug security, SQLite
- **Machine Learning**: `scikit-learn` (RandomForestRegressor), `numpy`, `pandas`, `joblib`
- **Frontend**: Responsive HTML5, Custom Command Center Dark CSS, Vanilla JavaScript
- **CDNs**: Bootstrap 5.3, Font Awesome 6.5, Leaflet.js 1.9, Chart.js 4.4

---

## 3. Directory Structure

```
RiskIntel/
├── app.py                  # Core Flask server, ORM models, AI engine, and 23-step simulation
├── requirements.txt        # Python dependency manifest
├── .env.example            # Environment variables template
├── README.md               # Documentation and execution guide
├── test_suite.py           # Automated unit and API test suite
├── riskintel.db            # Auto-generated and seeded SQLite database
├── templates/              # High-density Jinja2 command center templates
│   ├── base.html           # Command center frame, header, navigation, and disclaimer
│   ├── login.html          # Authentication terminal with demo-access quick fill
│   ├── dashboard.html      # Command Center (8 live stats, Leaflet map, threat overview)
│   ├── map.html            # GIS Spatial Matrix with multi-hazard layers and inspector
│   ├── lakes.html          # Glacial lakes directory with full CRUD
│   ├── lake_detail.html    # Lake telemetry, risk gauge, and XAI feature importance
│   ├── monitoring.html     # Real-time multi-variable telemetry station
│   ├── risk.html           # Interactive AI risk prediction calculator form
│   ├── explainability.html # Model feature importance (XAI horizontal chart)
│   ├── impact.html         # Downstream population & infrastructure vulnerability
│   ├── alerts.html         # Early warning dispatches & Authority approval workflow
│   ├── incidents.html      # Tactical incident log and response timeline
│   ├── rescue.html         # Rescue team deployments & civilian SOS hub
│   ├── shelters.html       # Designated shelters & live intake saturation
│   ├── evacuation.html     # Downstream evacuation sector planning
│   ├── resources.html      # Emergency relief supplies & shortage warning system
│   ├── analytics.html      # Real-time Chart.js command analytics
│   ├── recovery.html       # Post-disaster recovery & infrastructure status
│   ├── simulation.html     # 23-step Emergency Simulation Center
│   ├── system_health.html  # Subsystem diagnostics & API ping
│   ├── admin.html          # User IAM, status toggles, and role governance
│   ├── audit_logs.html     # Immutable operational audit trail
│   ├── 403.html            # Access restricted template
│   ├── 404.html            # Not found template
│   └── 500.html            # Internal server exception template
└── static/
    ├── css/
    │   └── style.css       # Emergency command center dark navy / slate theme
    └── js/
        └── app.js          # Leaflet map initializers, simulation runner, and toast system
```

---

## 4. Installation & Setup

1. **Clone or navigate to the project directory**:
   ```bash
   cd c:\Users\Yuvasri\Desktop\RiskIntel
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment (optional)**:
   ```bash
   cp .env.example .env
   ```

4. **Launch Application**:
   ```bash
   python app.py
   ```
   *The database `riskintel.db` will be automatically initialized and seeded with realistic demo records upon first launch.*

5. **Access Platform**:
   Open browser at `http://localhost:5000` or `http://127.0.0.1:5000`.

---

## 5. Demo Credentials

All demo accounts share the password: **`riskintel123`** (can be auto-filled by clicking the demo pills on the login screen):

| Role | Email | Permissions & Clearance |
|------|-------|-------------------------|
| **ADMIN** | `admin@riskintel.local` | Full platform access, User IAM, configuration, system deletion |
| **AUTHORITY** | `authority@riskintel.local` | Command Center, Alert approval/rejection, evacuation activation |
| **ENVIRONMENTAL_MONITOR** | `monitor@riskintel.local` | Glacial lakes, Telemetry monitoring, AI risk engine, XAI |
| **RESCUE_COORDINATOR** | `rescue@riskintel.local` | Field alerts, Incidents log, Rescue teams dispatch, SOS handling |
| **VIEWER** | `viewer@riskintel.local` | Read-only situational awareness (mutation operations blocked) |

---

## 6. The 23-Step Emergency Simulation Walkthrough

Navigate to **Emergency Simulation** (`/simulation`):
1. Click **`START SIMULATION`** or use **`Next Step`** to step sequentially.
2. Observe connected database state changes:
   - **Steps 1–6**: South Lhonak lake telemetry deteriorates (water depth surges by +2.8m, rainfall hits 148 mm/24h, moraine displacement surges to 34 mm/day).
   - **Steps 7–9**: Random Forest AI runs; risk score escalates to HIGH (71.4), then CRITICAL (94.2).
   - **Steps 10–12**: Downstream impact calculation flags 14,200 people across Chungthang and Dikchu sectors.
   - **Steps 13–16**: Emergency alert recommended &rarr; queued for Authority review &rarr; approved &rarr; broadcast as ACTIVE.
   - **Steps 17–19**: Evacuation corridor activated; civilian SOS calls logged; rescue teams Alpha-01 & Bravo-02 deployed.
   - **Steps 20–22**: Shelter intake saturates to 88%; potable water shortage flagged; Incident INC-SIM-01 timeline synchronized.
   - **Step 23**: Flood wave crest recedes; containment holds; post-disaster recovery phase initiates.

---

## 7. Verification & Tests

Run the automated test suite verifying route clearance, AI inference, simulation lifecycle, and role guards:
```bash
python test_suite.py
```
*Expected: 8 tests passing with OK status.*

---

## 8. Important Limitations

- **Prototype ML Model**: Uses a synthetic Random Forest model trained on simulated glacio-hydrological scenarios. Does not represent certified geophysical hazard modeling.
- **Synthetic Data**: Lake coordinates, depths, telemetry readings, and incident locations are realistic mock data for hackathon demonstration.
- **No Real Alerts**: Sirens, SMS broadcasts, and public emergency notices are strictly simulated within application memory.
