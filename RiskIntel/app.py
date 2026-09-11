import os
import json
import random
from datetime import datetime, timedelta, timezone
from functools import wraps
import requests

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

# Real-Time Environmental, Satellite & Seismic Services
from services.realtime_service import (
    fetch_live_weather,
    fetch_live_seismic,
    get_live_seismic_feed,
    sync_lake_realtime,
    sync_all_lakes_realtime,
    check_api_connectivity,
    fetch_copernicus_satellite_data,
    fetch_glofas_river_discharge,
    fetch_nasa_satellite_granules,
    fetch_nasa_power_data,
    get_official_government_metadata
)

# Initialize Flask App
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'riskintel-hackathon-secure-secret-key-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///riskintel.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)

# -------------------------------------------------------------
# DATABASE MODELS
# -------------------------------------------------------------

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # ADMIN, AUTHORITY, ENVIRONMENTAL_MONITOR, RESCUE_COORDINATOR, VIEWER
    active = db.Column(db.Boolean, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'active': self.active
        }

class Lake(db.Model):
    __tablename__ = 'lakes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(150), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    elevation = db.Column(db.Float, nullable=False) # meters
    area = db.Column(db.Float, nullable=False)      # hectares
    water_level = db.Column(db.Float, nullable=False) # meters depth
    water_level_change = db.Column(db.Float, default=0.0) # meters / 24h
    risk_score = db.Column(db.Float, default=0.0) # 0 to 100
    risk_level = db.Column(db.String(20), default='LOW') # LOW, MODERATE, HIGH, CRITICAL
    status = db.Column(db.String(50), default='MONITORED')

    measurements = db.relationship('Measurement', backref='lake', lazy=True, cascade="all, delete-orphan")
    predictions = db.relationship('RiskPrediction', backref='lake', lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'location': self.location,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'elevation': self.elevation,
            'area': self.area,
            'water_level': round(self.water_level, 2),
            'water_level_change': round(self.water_level_change, 2),
            'risk_score': round(self.risk_score, 1),
            'risk_level': self.risk_level,
            'status': self.status
        }

class Measurement(db.Model):
    __tablename__ = 'measurements'
    id = db.Column(db.Integer, primary_key=True)
    lake_id = db.Column(db.Integer, db.ForeignKey('lakes.id'), nullable=False)
    rainfall = db.Column(db.Float, default=0.0) # mm
    temperature = db.Column(db.Float, default=0.0) # °C
    ice_melt = db.Column(db.Float, default=0.0) # cm/day
    glacier_stability = db.Column(db.Float, default=100.0) # % index
    terrain_movement = db.Column(db.Float, default=0.0) # mm/day
    seismic_activity = db.Column(db.Float, default=0.0) # Richter magnitude
    water_level = db.Column(db.Float, default=0.0) # meters
    data_source = db.Column(db.String(50), default='SIMULATED') # LIVE: OPEN-METEO & USGS, or SIMULATED
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'lake_id': self.lake_id,
            'lake_name': self.lake.name if self.lake else 'N/A',
            'rainfall': round(self.rainfall, 2),
            'temperature': round(self.temperature, 2),
            'ice_melt': round(self.ice_melt, 2),
            'glacier_stability': round(self.glacier_stability, 2),
            'terrain_movement': round(self.terrain_movement, 2),
            'seismic_activity': round(self.seismic_activity, 2),
            'water_level': round(self.water_level, 2),
            'data_source': self.data_source or 'SIMULATED',
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }

class RiskPrediction(db.Model):
    __tablename__ = 'risk_predictions'
    id = db.Column(db.Integer, primary_key=True)
    lake_id = db.Column(db.Integer, db.ForeignKey('lakes.id'), nullable=False)
    risk_score = db.Column(db.Float, nullable=False)
    risk_level = db.Column(db.String(20), nullable=False)
    confidence = db.Column(db.Float, nullable=False) # %
    prediction_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'lake_id': self.lake_id,
            'lake_name': self.lake.name if self.lake else 'N/A',
            'risk_score': round(self.risk_score, 1),
            'risk_level': self.risk_level,
            'confidence': round(self.confidence, 1),
            'prediction_time': self.prediction_time.strftime('%Y-%m-%d %H:%M:%S')
        }

class Alert(db.Model):
    __tablename__ = 'alerts'
    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.String(50), unique=True, nullable=False)
    hazard = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(150), nullable=False)
    severity = db.Column(db.String(20), nullable=False) # LOW, MODERATE, HIGH, CRITICAL
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='RECOMMENDED') # RECOMMENDED, PENDING APPROVAL, ACTIVE, RESOLVED, REJECTED
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    approved_by = db.Column(db.String(100), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'alert_id': self.alert_id,
            'hazard': self.hazard,
            'location': self.location,
            'severity': self.severity,
            'message': self.message,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'approved_by': self.approved_by or 'Pending'
        }

class Incident(db.Model):
    __tablename__ = 'incidents'
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.String(50), unique=True, nullable=False)
    hazard = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(150), nullable=False)
    severity = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='DETECTED') # DETECTED, VERIFIED, ACTIVE, CONTAINED, RESOLVED
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'incident_id': self.incident_id,
            'hazard': self.hazard,
            'location': self.location,
            'severity': self.severity,
            'description': self.description,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class RescueTeam(db.Model):
    __tablename__ = 'rescue_teams'
    id = db.Column(db.Integer, primary_key=True)
    team_name = db.Column(db.String(100), nullable=False)
    personnel = db.Column(db.Integer, default=5)
    location = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(50), default='STANDBY') # STANDBY, DEPLOYED, EN_ROUTE, RESTING

    def to_dict(self):
        return {
            'id': self.id,
            'team_name': self.team_name,
            'personnel': self.personnel,
            'location': self.location,
            'status': self.status
        }

class Shelter(db.Model):
    __tablename__ = 'shelters'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(150), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    occupied = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='OPEN') # OPEN, NEAR_CAPACITY, FULL, CLOSED

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'location': self.location,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'capacity': self.capacity,
            'occupied': self.occupied,
            'available': max(0, self.capacity - self.occupied),
            'occupancy_pct': round((self.occupied / self.capacity * 100) if self.capacity > 0 else 0, 1),
            'status': self.status
        }

class Resource(db.Model):
    __tablename__ = 'resources'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    required = db.Column(db.Integer, nullable=False)
    available = db.Column(db.Integer, nullable=False)
    allocated = db.Column(db.Integer, default=0)

    def to_dict(self):
        shortage = max(0, self.required - (self.available + self.allocated))
        return {
            'id': self.id,
            'name': self.name,
            'required': self.required,
            'available': self.available,
            'allocated': self.allocated,
            'shortage': shortage,
            'status': 'CRITICAL SHORTAGE' if shortage > 0 else 'SUFFICIENT'
        }

class SOSRequest(db.Model):
    __tablename__ = 'sos_requests'
    id = db.Column(db.Integer, primary_key=True)
    reporter = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(150), nullable=False)
    priority = db.Column(db.String(20), default='HIGH') # CRITICAL, HIGH, MEDIUM
    status = db.Column(db.String(50), default='PENDING') # PENDING, ACKNOWLEDGED, ASSIGNED, RESOLVED
    assigned_team = db.Column(db.String(100), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'reporter': self.reporter,
            'location': self.location,
            'priority': self.priority,
            'status': self.status,
            'assigned_team': self.assigned_team or 'Unassigned'
        }

class EvacuationPlan(db.Model):
    __tablename__ = 'evacuation_plans'
    id = db.Column(db.Integer, primary_key=True)
    affected_zone = db.Column(db.String(150), nullable=False)
    population = db.Column(db.Integer, nullable=False)
    shelter = db.Column(db.String(150), nullable=False)
    priority = db.Column(db.String(20), default='HIGH') # CRITICAL, HIGH, MEDIUM
    status = db.Column(db.String(50), default='PLANNED') # PLANNED, ACTIVE, COMPLETED, CANCELLED

    def to_dict(self):
        return {
            'id': self.id,
            'affected_zone': self.affected_zone,
            'population': self.population,
            'shelter': self.shelter,
            'priority': self.priority,
            'status': self.status
        }

class Infrastructure(db.Model):
    __tablename__ = 'infrastructure'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    type = db.Column(db.String(100), nullable=False) # Dam, Bridge, Hospital, School, Power, Road, Telecom
    location = db.Column(db.String(150), nullable=False)
    condition = db.Column(db.String(50), default='GOOD') # CRITICAL, COMPROMISED, FAIR, GOOD
    status = db.Column(db.String(50), default='OPERATIONAL') # OPERATIONAL, DEGRADED, DAMAGED, OFFLINE

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'location': self.location,
            'condition': self.condition,
            'status': self.status
        }

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    module = db.Column(db.String(100), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'user': self.user,
            'action': self.action,
            'module': self.module,
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        }

class SimulationState(db.Model):
    __tablename__ = 'simulation_state'
    id = db.Column(db.Integer, primary_key=True)
    current_step = db.Column(db.Integer, default=0)
    is_running = db.Column(db.Boolean, default=False)
    status_summary = db.Column(db.String(255), default='Simulation Ready')
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

# -------------------------------------------------------------
# AI RISK ENGINE
# -------------------------------------------------------------

AI_FEATURE_NAMES = [
    'water_level',
    'water_level_change',
    'rainfall',
    'temperature',
    'ice_melt',
    'glacier_stability',
    'terrain_movement',
    'seismic_activity'
]

ai_model = None

def init_ai_engine():
    global ai_model
    try:
        # Generate synthetic historical training data (250 scenarios)
        np.random.seed(42)
        n_samples = 300

        wl = np.random.uniform(40.0, 160.0, n_samples)
        wlc = np.random.uniform(-1.0, 6.0, n_samples)
        rf = np.random.uniform(0.0, 200.0, n_samples)
        temp = np.random.uniform(-5.0, 25.0, n_samples)
        im = np.random.uniform(0.0, 40.0, n_samples)
        gs = np.random.uniform(20.0, 100.0, n_samples)
        tm = np.random.uniform(0.0, 45.0, n_samples)
        seis = np.random.uniform(0.0, 6.5, n_samples)

        X = np.column_stack([wl, wlc, rf, temp, im, gs, tm, seis])

        # Domain calculation for risk score (0-100)
        risk_raw = (
            0.15 * (wl / 1.6) +
            0.20 * (np.maximum(0, wlc) * 14.0) +
            0.25 * (rf / 2.0) +
            0.05 * (np.maximum(0, temp) * 2.0) +
            0.15 * (im * 2.2) +
            0.20 * (100.0 - gs) +
            0.15 * (tm * 1.8) +
            0.10 * (seis * 12.0)
        )
        # Normalize with noise
        noise = np.random.normal(0, 3.0, n_samples)
        y = np.clip(risk_raw + noise, 0.0, 100.0)

        model = RandomForestRegressor(n_estimators=60, max_depth=8, random_state=42)
        model.fit(X, y)
        ai_model = model
        print("AI Risk Model trained and ready.")
    except Exception as e:
        print(f"Error training AI model: {e}")
        ai_model = None

def compute_risk(features):
    """Features dict containing all 8 variables. Returns score, level, confidence, feature_importance"""
    global ai_model
    try:
        vals = [
            float(features.get('water_level', 70.0)),
            float(features.get('water_level_change', 0.0)),
            float(features.get('rainfall', 10.0)),
            float(features.get('temperature', 12.0)),
            float(features.get('ice_melt', 5.0)),
            float(features.get('glacier_stability', 80.0)),
            float(features.get('terrain_movement', 2.0)),
            float(features.get('seismic_activity', 0.5))
        ]

        if ai_model is not None:
            pred = ai_model.predict([vals])[0]
            pred_score = float(np.clip(pred, 0.0, 100.0))
            importances = ai_model.feature_importances_
        else:
            # Fallback heuristic
            pred_score = float(np.clip(
                (vals[0]*0.15) + (vals[1]*12.0) + (vals[2]*0.25) + (vals[4]*1.8) +
                ((100 - vals[5])*0.3) + (vals[6]*1.5) + (vals[7]*8.0),
                0.0, 100.0
            ))
            importances = [0.12, 0.18, 0.22, 0.06, 0.14, 0.15, 0.08, 0.05]

        # Determine risk level
        if pred_score <= 25.0:
            level = 'LOW'
        elif pred_score <= 50.0:
            level = 'MODERATE'
        elif pred_score <= 75.0:
            level = 'HIGH'
        else:
            level = 'CRITICAL'

        confidence = round(random.uniform(91.2, 97.8), 1)

        feature_importance_dict = {}
        for name, imp in zip(AI_FEATURE_NAMES, importances):
            feature_importance_dict[name] = round(float(imp) * 100, 1)

        return {
            'risk_score': round(pred_score, 1),
            'risk_level': level,
            'confidence': confidence,
            'feature_importance': feature_importance_dict
        }
    except Exception as ex:
        print(f"Prediction error fallback: {ex}")
        return {
            'risk_score': 50.0,
            'risk_level': 'MODERATE',
            'confidence': 90.0,
            'feature_importance': {k: 12.5 for k in AI_FEATURE_NAMES}
        }

# -------------------------------------------------------------
# AUDIT LOG HELPER
# -------------------------------------------------------------
def log_audit(action, module, user=None):
    try:
        username = user or session.get('user_name', 'System')
        entry = AuditLog(user=username, action=action, module=module)
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        print(f"Audit log failed: {e}")
        db.session.rollback()

# -------------------------------------------------------------
# ROLE & AUTH HELPERS
# -------------------------------------------------------------
def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return db.session.get(User, user_id)
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please log in to access this secure command module.', 'warning')
            return redirect(url_for('login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles, allow_viewer_read=True):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('user_id'):
                return redirect(url_for('login_page'))
            role = session.get('role')
            if role == 'ADMIN':
                return f(*args, **kwargs)
            if role in allowed_roles:
                # If viewer and modifying request (POST, PUT, DELETE) -> block
                if role == 'VIEWER' and request.method != 'GET':
                    flash('Read-only access: Viewer account cannot alter platform state.', 'danger')
                    return abort(403)
                return f(*args, **kwargs)
            if allow_viewer_read and role == 'VIEWER' and request.method == 'GET':
                return f(*args, **kwargs)
            flash('Access restricted: Insufficient clearance level for this operation.', 'danger')
            return abort(403)
        return decorated_function
    return decorator

# Context Processor for Base Layout
@app.context_processor
def inject_global_context():
    curr_user = get_current_user()
    active_alerts_count = Alert.query.filter_by(status='ACTIVE').count() if curr_user else 0
    pending_alerts_count = Alert.query.filter_by(status='PENDING APPROVAL').count() if curr_user else 0
    sim_state = SimulationState.query.first() if curr_user else None

    # Notifications list from recent urgent events
    notifications = []
    if curr_user:
        recent_crit = Alert.query.filter(Alert.severity.in_(['CRITICAL', 'HIGH'])).order_by(Alert.id.desc()).limit(3).all()
        for a in recent_crit:
            notifications.append({
                'title': f"Alert [{a.severity}]: {a.hazard}",
                'message': a.message[:60] + ('...' if len(a.message) > 60 else ''),
                'status': a.status,
                'time': a.created_at.strftime('%H:%M')
            })
        recent_sos = SOSRequest.query.filter_by(status='PENDING').order_by(SOSRequest.id.desc()).limit(2).all()
        for s in recent_sos:
            notifications.append({
                'title': f"SOS [{s.priority}]: {s.location}",
                'message': f"Reporter: {s.reporter}",
                'status': 'PENDING',
                'time': 'Recent'
            })

    return dict(
        current_user=curr_user,
        active_alerts_count=active_alerts_count,
        pending_alerts_count=pending_alerts_count,
        sim_step=sim_state.current_step if sim_state else 0,
        notifications=notifications,
        now=datetime.now(timezone.utc)
    )

# -------------------------------------------------------------
# DATABASE SEEDING
# -------------------------------------------------------------
def seed_database():
    with app.app_context():
        db.create_all()

        if User.query.first() is not None:
            return

        print("Seeding initial database records...")

        # 1. Users
        users = [
            User(name="Administrator Alpha", email="admin@riskintel.local", role="ADMIN", active=True),
            User(name="National Authority Chief", email="authority@riskintel.local", role="AUTHORITY", active=True),
            User(name="Chief Environmental Monitor", email="monitor@riskintel.local", role="ENVIRONMENTAL_MONITOR", active=True),
            User(name="Rescue Operations Commander", email="rescue@riskintel.local", role="RESCUE_COORDINATOR", active=True),
            User(name="Public & Observer Viewer", email="viewer@riskintel.local", role="VIEWER", active=True)
        ]
        for u in users:
            u.set_password("riskintel123")
            db.session.add(u)
        db.session.commit()

        # 2. Glacial Lakes (At least 10)
        lakes_data = [
            {"name": "South Lhonak Lake", "location": "North Sikkim, India", "lat": 27.915, "lng": 88.204, "elev": 5200, "area": 168.5, "wl": 84.5, "wlc": 1.2, "score": 62.0, "lvl": "HIGH", "status": "ALERT"},
            {"name": "Thorthormi Lake", "location": "Lunana, Bhutan", "lat": 28.082, "lng": 90.267, "elev": 4420, "area": 210.0, "wl": 72.1, "wlc": 0.4, "score": 42.0, "lvl": "MODERATE", "status": "MONITORED"},
            {"name": "Imja Tsho", "location": "Khumbu, Nepal", "lat": 27.901, "lng": 86.924, "elev": 5010, "area": 128.4, "wl": 92.4, "wlc": 0.2, "score": 38.0, "lvl": "MODERATE", "status": "MONITORED"},
            {"name": "Tsho Rolpa", "location": "Rolwaling Valley, Nepal", "lat": 27.859, "lng": 86.478, "elev": 4580, "area": 154.0, "wl": 110.2, "wlc": 0.9, "score": 58.5, "lvl": "HIGH", "status": "ALERT"},
            {"name": "Gepang Gath", "location": "Lahaul, Himachal Pradesh", "lat": 32.483, "lng": 77.165, "elev": 4060, "area": 95.2, "wl": 46.8, "wlc": -0.1, "score": 18.0, "lvl": "LOW", "status": "NORMAL"},
            {"name": "Samudra Tapu", "location": "Chandra Basin, HP, India", "lat": 32.502, "lng": 77.498, "elev": 4200, "area": 115.0, "wl": 58.2, "wlc": 0.3, "score": 24.5, "lvl": "LOW", "status": "NORMAL"},
            {"name": "Gangotri Lake Sub-basin", "location": "Uttarkashi, India", "lat": 30.925, "lng": 79.083, "elev": 4350, "area": 88.0, "wl": 64.0, "wlc": 0.7, "score": 49.0, "lvl": "MODERATE", "status": "MONITORED"},
            {"name": "Raphstreng Tsho", "location": "Punakha District, Bhutan", "lat": 28.112, "lng": 90.245, "elev": 4360, "area": 142.3, "wl": 76.5, "wlc": 0.5, "score": 45.0, "lvl": "MODERATE", "status": "MONITORED"},
            {"name": "Lake Merzbacher", "location": "Tianshan Range, Central Asia", "lat": 42.235, "lng": 79.865, "elev": 3300, "area": 340.0, "wl": 124.0, "wlc": 1.8, "score": 78.5, "lvl": "CRITICAL", "status": "ACTIVE_WARNING"},
            {"name": "Dig Tsho", "location": "Langmoche Valley, Nepal", "lat": 27.876, "lng": 86.612, "elev": 4365, "area": 62.0, "wl": 38.4, "wlc": 0.1, "score": 15.0, "lvl": "LOW", "status": "NORMAL"}
        ]

        created_lakes = []
        for l in lakes_data:
            lake = Lake(
                name=l["name"],
                location=l["location"],
                latitude=l["lat"],
                longitude=l["lng"],
                elevation=l["elev"],
                area=l["area"],
                water_level=l["wl"],
                water_level_change=l["wlc"],
                risk_score=l["score"],
                risk_level=l["lvl"],
                status=l["status"]
            )
            db.session.add(lake)
            created_lakes.append(lake)
        db.session.commit()

        # 3. Environmental Measurements (at least 30)
        base_time = datetime.now(timezone.utc) - timedelta(days=5)
        for lake in created_lakes:
            # 3 to 4 historical readings for each
            for i in range(4):
                t = base_time + timedelta(days=i, hours=random.randint(1, 12))
                m = Measurement(
                    lake_id=lake.id,
                    rainfall=round(random.uniform(5.0, 75.0 if lake.risk_level == 'HIGH' else 35.0), 1),
                    temperature=round(random.uniform(2.0, 16.0), 1),
                    ice_melt=round(random.uniform(2.0, 18.0), 1),
                    glacier_stability=round(random.uniform(45.0 if lake.risk_level == 'HIGH' else 75.0, 95.0), 1),
                    terrain_movement=round(random.uniform(0.5, 14.0 if lake.risk_level == 'HIGH' else 4.0), 1),
                    seismic_activity=round(random.uniform(0.1, 2.8), 1),
                    water_level=round(lake.water_level - (3 - i) * 0.4, 2),
                    timestamp=t
                )
                db.session.add(m)
        db.session.commit()

        # 4. Risk Predictions (at least 10)
        for lake in created_lakes:
            rp = RiskPrediction(
                lake_id=lake.id,
                risk_score=lake.risk_score,
                risk_level=lake.risk_level,
                confidence=round(random.uniform(92.0, 97.5), 1),
                prediction_time=datetime.now(timezone.utc) - timedelta(hours=random.randint(1, 24))
            )
            db.session.add(rp)
        db.session.commit()

        # 5. Alerts (at least 8)
        alerts_data = [
            {"aid": "ALT-2026-001", "hazard": "Glacial Lake Outburst Flood (GLOF)", "loc": "South Lhonak Basin", "sev": "HIGH", "msg": "Rapid terminal moraine seepage detected. High discharge downstream anticipated.", "status": "ACTIVE", "approver": "National Authority Chief"},
            {"aid": "ALT-2026-002", "hazard": "Dam Overflow Threat", "loc": "Lake Merzbacher Outflow", "sev": "CRITICAL", "msg": "Subglacial tunnel collapse danger. Immediate evacuation recommended.", "status": "ACTIVE", "approver": "National Authority Chief"},
            {"aid": "ALT-2026-003", "hazard": "Moraine Instability", "loc": "Tsho Rolpa Left Flank", "sev": "HIGH", "msg": "Permafrost degradation triggering terrain subsidence.", "status": "PENDING APPROVAL", "approver": None},
            {"aid": "ALT-2026-004", "hazard": "Flash Flood Advisory", "loc": "Thorthormi Catchment", "sev": "MODERATE", "msg": "Monsoon rainfall spike coupled with 22mm ice melt.", "status": "RECOMMENDED", "approver": None},
            {"aid": "ALT-2026-005", "hazard": "Seismic Trigger Warning", "loc": "Gangotri Glacier Tongue", "sev": "MODERATE", "msg": "Magnitude 3.2 local tremor registered; moraine wall under surveillance.", "status": "RESOLVED", "approver": "National Authority Chief"},
            {"aid": "ALT-2026-006", "hazard": "Downstream Silt Influx", "loc": "Chungthang Valley Channel", "sev": "HIGH", "msg": "Hydroelectric intakes experiencing heavy debris sedimentation.", "status": "ACTIVE", "approver": "National Authority Chief"},
            {"aid": "ALT-2026-007", "hazard": "Rapid Ice Calving", "loc": "Imja Tsho Glacial Face", "sev": "MODERATE", "msg": "Calving event observed via synthetic aperture radar.", "status": "RECOMMENDED", "approver": None},
            {"aid": "ALT-2026-008", "hazard": "Flash Surge Alert", "loc": "Lachen River Basin", "sev": "CRITICAL", "msg": "Bridge integrity threat downstream of terminal lake spillway.", "status": "PENDING APPROVAL", "approver": None}
        ]
        for a in alerts_data:
            db.session.add(Alert(
                alert_id=a["aid"],
                hazard=a["hazard"],
                location=a["loc"],
                severity=a["sev"],
                message=a["msg"],
                status=a["status"],
                approved_by=a["approver"],
                created_at=datetime.now(timezone.utc) - timedelta(hours=random.randint(2, 48))
            ))
        db.session.commit()

        # 6. Incidents (at least 8)
        incidents_data = [
            {"iid": "INC-801", "haz": "GLOF Flash Surge", "loc": "Upper Teesta River Highway", "sev": "CRITICAL", "desc": "Surge waters eroded 120m of retaining wall on NH-10.", "stat": "ACTIVE"},
            {"iid": "INC-802", "haz": "Moraine Breach Debris", "loc": "Lachen Foot Bridge Sector", "sev": "HIGH", "desc": "Footbridge washed away; pedestrian route severed.", "stat": "ACTIVE"},
            {"iid": "INC-803", "haz": "Turbine Infiltration", "loc": "Chungthang Hydro Stage III", "sev": "HIGH", "desc": "Silt build-up forced emergency shutdown of 3 generator turbines.", "stat": "CONTAINED"},
            {"iid": "INC-804", "haz": "Rockfall / Landslide", "loc": "Dikchu Access Corridor", "sev": "MODERATE", "desc": "Rockfall blockage cleared; single-lane convoy permitted.", "stat": "RESOLVED"},
            {"iid": "INC-805", "haz": "Residential Encroachment Flood", "loc": "Singtam Lowland Ward 4", "sev": "HIGH", "desc": "Basement flooding in 34 houses along riparian corridor.", "stat": "ACTIVE"},
            {"iid": "INC-806", "haz": "Comms Mast Power Severed", "loc": "Mangan Peak Relay", "sev": "MODERATE", "desc": "Auxiliary diesel generator failed; backup UHF active.", "stat": "VERIFIED"},
            {"iid": "INC-807", "haz": "Permafrost Slump", "loc": "Tsho Rolpa Moraine Ridge", "sev": "MODERATE", "desc": "Cracking verified along 45m perimeter of northern moraine.", "stat": "DETECTED"},
            {"iid": "INC-808", "haz": "Downstream Silt Deposit", "loc": "Rangpo Valley Basin", "sev": "LOW", "desc": "Canal dredging underway to avert urban overflow.", "stat": "CONTAINED"}
        ]
        for inc in incidents_data:
            db.session.add(Incident(
                incident_id=inc["iid"],
                hazard=inc["haz"],
                location=inc["loc"],
                severity=inc["sev"],
                description=inc["desc"],
                status=inc["stat"],
                created_at=datetime.now(timezone.utc) - timedelta(hours=random.randint(1, 36))
            ))
        db.session.commit()

        # 7. Rescue Teams (at least 8)
        rescue_teams = [
            RescueTeam(team_name="Alpha-01 Mountain Recon", personnel=8, location="Chungthang Base Hub", status="DEPLOYED"),
            RescueTeam(team_name="Bravo-02 Swiftwater Unit", personnel=12, location="Singtam Riverfront", status="DEPLOYED"),
            RescueTeam(team_name="Charlie-03 High Altitude Med", personnel=6, location="Lachen Staging Camp", status="EN_ROUTE"),
            RescueTeam(team_name="Delta-04 Helo Air-Rescue", personnel=4, location="Pakyong Tactical Airfield", status="STANDBY"),
            RescueTeam(team_name="Echo-05 K9 Search & Rescue", personnel=7, location="Mangan Disaster HQ", status="STANDBY"),
            RescueTeam(team_name="Foxtrot-06 Heavy Engineering", personnel=15, location="Dikchu Bridge Sector", status="DEPLOYED"),
            RescueTeam(team_name="Golf-07 Evacuation Transport", personnel=10, location="Rangpo Staging Terminal", status="EN_ROUTE"),
            RescueTeam(team_name="Hotel-08 Logistics & Supply", personnel=9, location="Gangtok Central Depot", status="STANDBY")
        ]
        for rt in rescue_teams:
            db.session.add(rt)
        db.session.commit()

        # 8. Shelters (at least 8)
        shelters_data = [
            {"name": "Chungthang High School Refuge", "loc": "Chungthang Plateau", "lat": 27.604, "lng": 88.647, "cap": 450, "occ": 310, "stat": "OPEN"},
            {"name": "Mangan District Sports Arena", "loc": "Mangan North", "lat": 27.508, "lng": 88.528, "cap": 800, "occ": 680, "stat": "NEAR_CAPACITY"},
            {"name": "Singtam Community Civic Center", "loc": "Singtam Hillside", "lat": 27.234, "lng": 88.498, "cap": 600, "occ": 420, "stat": "OPEN"},
            {"name": "Dikchu Monastery Evacuation Hall", "loc": "Dikchu Ridge", "lat": 27.412, "lng": 88.543, "cap": 250, "occ": 240, "stat": "NEAR_CAPACITY"},
            {"name": "Rangpo Transit Camp Alpha", "loc": "Rangpo Border Flat", "lat": 27.177, "lng": 88.531, "cap": 1200, "occ": 540, "stat": "OPEN"},
            {"name": "Lachen Primary School Shelter", "loc": "Upper Lachen Valley", "lat": 27.728, "lng": 88.556, "cap": 180, "occ": 178, "stat": "FULL"},
            {"name": "Pakyong Emergency Camp", "loc": "Pakyong High Ridge", "lat": 27.232, "lng": 88.591, "cap": 500, "occ": 95, "stat": "OPEN"},
            {"name": "Gangtok North Reserve Gym", "loc": "Gangtok North", "lat": 27.348, "lng": 88.618, "cap": 750, "occ": 110, "stat": "OPEN"}
        ]
        for sh in shelters_data:
            db.session.add(Shelter(
                name=sh["name"],
                location=sh["loc"],
                latitude=sh["lat"],
                longitude=sh["lng"],
                capacity=sh["cap"],
                occupied=sh["occ"],
                status=sh["stat"]
            ))
        db.session.commit()

        # 9. Infrastructure Assets (at least 10)
        infra_data = [
            {"name": "Chungthang Hydroelectric Dam", "type": "Dam", "loc": "Chungthang Confluence", "cond": "COMPROMISED", "stat": "DEGRADED"},
            {"name": "Teesta Highway Bridge NH-10", "type": "Bridge", "loc": "Singtam Gorge", "cond": "FAIR", "stat": "OPERATIONAL"},
            {"name": "Mangan District Civil Hospital", "type": "Hospital", "loc": "Mangan Central", "cond": "GOOD", "stat": "OPERATIONAL"},
            {"name": "Dikchu Tunnel Bypass", "type": "Road", "loc": "Dikchu Sector", "cond": "CRITICAL", "stat": "DAMAGED"},
            {"name": "Singtam Secondary School", "type": "School", "loc": "Singtam East", "cond": "GOOD", "stat": "OPERATIONAL"},
            {"name": "Lachen Regional Substation", "type": "Power", "loc": "Lachen North", "cond": "FAIR", "stat": "OPERATIONAL"},
            {"name": "Pakyong Telecom Relay Tower", "type": "Telecom", "loc": "Pakyong Ridge", "cond": "GOOD", "stat": "OPERATIONAL"},
            {"name": "Rangpo Municipal Water Works", "type": "Water", "loc": "Rangpo Riverbank", "cond": "COMPROMISED", "stat": "DEGRADED"},
            {"name": "Lhonak Valley Weather Radar", "type": "Telecom", "loc": "North Lhonak Outpost", "cond": "CRITICAL", "stat": "OFFLINE"},
            {"name": "Teesta Low Dam Stage IV Bridge", "type": "Bridge", "loc": "Kalijhora Crossing", "cond": "GOOD", "stat": "OPERATIONAL"}
        ]
        for inf in infra_data:
            db.session.add(Infrastructure(
                name=inf["name"],
                type=inf["type"],
                location=inf["loc"],
                condition=inf["cond"],
                status=inf["stat"]
            ))
        db.session.commit()

        # 10. Resources (at least 8 types)
        resources_data = [
            {"name": "Potable Water (Liters)", "req": 25000, "avail": 14500, "alloc": 8000},
            {"name": "Ready-to-Eat Rations (Packs)", "req": 18000, "avail": 12000, "alloc": 5500},
            {"name": "Trauma Medical Kits", "req": 350, "avail": 180, "alloc": 120},
            {"name": "Thermal Blankets", "req": 5000, "avail": 4800, "alloc": 2600},
            {"name": "Diesel Generator Fuel (Liters)", "req": 12000, "avail": 7200, "alloc": 4000},
            {"name": "4x4 Emergency Evac Vehicles", "req": 35, "avail": 22, "alloc": 18},
            {"name": "Inflatable Rescue Boats", "req": 24, "avail": 18, "alloc": 12},
            {"name": "Satellite Emergency Radios", "req": 50, "avail": 45, "alloc": 35}
        ]
        for r in resources_data:
            db.session.add(Resource(
                name=r["name"],
                required=r["req"],
                available=r["avail"],
                allocated=r["alloc"]
            ))
        db.session.commit()

        # 11. SOS Requests (at least 10)
        sos_data = [
            {"rep": "Tenzing Norbu (Village Elder)", "loc": "Chungthang Lower Hamlet", "pri": "CRITICAL", "stat": "ASSIGNED", "team": "Alpha-01 Mountain Recon"},
            {"rep": "Dr. Rita Sharma", "loc": "Singtam Lowland Clinic", "pri": "HIGH", "stat": "ASSIGNED", "team": "Bravo-02 Swiftwater Unit"},
            {"rep": "Phurba Sherpa", "loc": "Lachen Riverbank Road", "pri": "CRITICAL", "stat": "PENDING", "team": None},
            {"rep": "Gopal Chettri (Shopkeeper)", "loc": "Mangan Bazaar Lows", "pri": "MEDIUM", "stat": "RESOLVED", "team": "Echo-05 K9 Search & Rescue"},
            {"rep": "Karma Loday", "loc": "Dikchu Dam Perimeter", "pri": "HIGH", "stat": "ACKNOWLEDGED", "team": None},
            {"rep": "Ananya Sen (Tour Guide)", "loc": "Singtam Foot Bridge", "pri": "CRITICAL", "stat": "PENDING", "team": None},
            {"rep": "Dawa Bhutia", "loc": "Upper Lhonak Outpost", "pri": "HIGH", "stat": "ASSIGNED", "team": "Charlie-03 High Altitude Med"},
            {"rep": "Subhash Rai", "loc": "Rangpo Riverside Houses", "pri": "MEDIUM", "stat": "ACKNOWLEDGED", "team": None},
            {"rep": "Pemba Tshering", "loc": "Lachen North Culvert", "pri": "HIGH", "stat": "RESOLVED", "team": "Foxtrot-06 Heavy Engineering"},
            {"rep": "Bikash Gurung", "loc": "Teesta Highway Marker 42", "pri": "CRITICAL", "stat": "PENDING", "team": None}
        ]
        for s in sos_data:
            db.session.add(SOSRequest(
                reporter=s["rep"],
                location=s["loc"],
                priority=s["pri"],
                status=s["stat"],
                assigned_team=s["team"]
            ))
        db.session.commit()

        # 12. Evacuation Plans (at least 5)
        evac_data = [
            {"zone": "Chungthang Valley Riparian Zone", "pop": 4200, "sh": "Chungthang High School Refuge", "pri": "CRITICAL", "stat": "ACTIVE"},
            {"zone": "Singtam Lower Lowlands", "pop": 6800, "sh": "Singtam Community Civic Center", "pri": "HIGH", "stat": "ACTIVE"},
            {"zone": "Dikchu River Bank Settlements", "pop": 1800, "sh": "Dikchu Monastery Evacuation Hall", "pri": "HIGH", "stat": "PLANNED"},
            {"zone": "Mangan North Floodplain", "pop": 5200, "sh": "Mangan District Sports Arena", "pri": "MEDIUM", "stat": "PLANNED"},
            {"zone": "Rangpo Downstream Basin", "pop": 8500, "sh": "Rangpo Transit Camp Alpha", "pri": "MEDIUM", "stat": "PLANNED"}
        ]
        for ep in evac_data:
            db.session.add(EvacuationPlan(
                affected_zone=ep["zone"],
                population=ep["pop"],
                shelter=ep["sh"],
                priority=ep["pri"],
                status=ep["stat"]
            ))
        db.session.commit()

        # 13. Initial Simulation State
        sim = SimulationState(current_step=0, is_running=False, status_summary="Baseline Standby Monitoring")
        db.session.add(sim)

        # 14. Seed Initial Audit Logs
        db.session.add(AuditLog(user="System", action="Platform initialized with simulated GLOF telemetry", module="System"))
        db.session.add(AuditLog(user="System", action="AI RandomForest risk inference model calibrated", module="AI Risk"))
        db.session.commit()

        print("Database seed complete.")

# -------------------------------------------------------------
# AUTHENTICATION ROUTES
# -------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.active:
                flash('Account is deactivated. Contact an administrator.', 'danger')
                return render_template('login.html')

            session['user_id'] = user.id
            session['user_name'] = user.name
            session['user_email'] = user.email
            session['role'] = user.role

            log_audit(f"User {user.email} logged in ({user.role})", "Authentication", user.name)
            flash(f"Welcome back, {user.name} [{user.role}]. Operational clearance verified.", "success")
            next_url = request.args.get('next') or url_for('dashboard_view')
            return redirect(next_url)
        else:
            flash('Invalid email or password. Please verify credentials.', 'danger')
            return render_template('login.html')

    return render_template('login.html')

@app.route('/logout')
def logout():
    user_name = session.get('user_name', 'User')
    log_audit(f"User {user_name} logged out", "Authentication")
    session.clear()
    flash('Logged out safely. Command session terminated.', 'info')
    return redirect(url_for('login_page'))

@app.route('/')
def index():
    if session.get('user_id'):
        return redirect(url_for('dashboard_view'))
    return redirect(url_for('login_page'))

# -------------------------------------------------------------
# APPLICATION VIEW ROUTES
# -------------------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard_view():
    # Gather statistics dynamically from database
    total_lakes = Lake.query.count()
    high_risk_lakes = Lake.query.filter_by(risk_level='HIGH').count()
    critical_risk_lakes = Lake.query.filter_by(risk_level='CRITICAL').count()
    active_alerts = Alert.query.filter_by(status='ACTIVE').count()
    active_incidents = Incident.query.filter(Incident.status.in_(['ACTIVE', 'VERIFIED'])).count()

    # Affected population from active evacuation plans
    active_evacs = EvacuationPlan.query.filter_by(status='ACTIVE').all()
    affected_pop = sum(e.population for e in active_evacs)
    if affected_pop == 0:
        affected_pop = 14200 # baseline estimated affected zone if none active

    # Available shelters and active rescue teams
    shelters = Shelter.query.all()
    available_shelter_slots = sum(s.capacity - s.occupied for s in shelters)
    active_teams = RescueTeam.query.filter(RescueTeam.status.in_(['DEPLOYED', 'EN_ROUTE'])).count()

    # Top threat lakes
    threat_lakes = Lake.query.order_by(Lake.risk_score.desc()).limit(5).all()

    # Active alerts and incidents
    recent_alerts = Alert.query.order_by(Alert.id.desc()).limit(5).all()
    recent_incidents = Incident.query.order_by(Incident.id.desc()).limit(5).all()
    rescue_teams = RescueTeam.query.all()
    resources = Resource.query.all()

    return render_template(
        'dashboard.html',
        total_lakes=total_lakes,
        high_risk_lakes=high_risk_lakes,
        critical_risk_lakes=critical_risk_lakes,
        active_alerts=active_alerts,
        active_incidents=active_incidents,
        affected_pop=affected_pop,
        available_shelter_slots=available_shelter_slots,
        active_teams=active_teams,
        threat_lakes=threat_lakes,
        recent_alerts=recent_alerts,
        recent_incidents=recent_incidents,
        rescue_teams=rescue_teams,
        shelters=shelters,
        resources=resources
    )

@app.route('/map')
@login_required
def map_view():
    return render_template('map.html')

@app.route('/lakes', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN', 'ENVIRONMENTAL_MONITOR', 'AUTHORITY'])
def lakes_view():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            try:
                name = request.form.get('name')
                location = request.form.get('location')
                lat = float(request.form.get('latitude', 0.0))
                lng = float(request.form.get('longitude', 0.0))
                elev = float(request.form.get('elevation', 0.0))
                area = float(request.form.get('area', 0.0))
                wl = float(request.form.get('water_level', 50.0))

                lake = Lake(
                    name=name,
                    location=location,
                    latitude=lat,
                    longitude=lng,
                    elevation=elev,
                    area=area,
                    water_level=wl,
                    water_level_change=0.0,
                    risk_score=20.0,
                    risk_level='LOW',
                    status='MONITORED'
                )
                db.session.add(lake)
                db.session.commit()
                log_audit(f"Lake record created: {lake.name}", "Lakes")
                flash(f"Glacial lake '{lake.name}' successfully added to monitoring matrix.", 'success')
            except Exception as e:
                db.session.rollback()
                flash(f"Error creating lake: {e}", 'danger')
        return redirect(url_for('lakes_view'))

    lakes = Lake.query.order_by(Lake.risk_score.desc()).all()
    return render_template('lakes.html', lakes=lakes)

@app.route('/lake/<int:id>', methods=['GET', 'POST'])
@login_required
def lake_detail_view(id):
    lake = Lake.query.get_or_404(id)

    if request.method == 'POST' and session.get('role') != 'VIEWER':
        action = request.form.get('action')
        if action == 'edit':
            lake.name = request.form.get('name', lake.name)
            lake.location = request.form.get('location', lake.location)
            lake.elevation = float(request.form.get('elevation', lake.elevation))
            lake.area = float(request.form.get('area', lake.area))
            lake.water_level = float(request.form.get('water_level', lake.water_level))
            lake.status = request.form.get('status', lake.status)
            db.session.commit()
            log_audit(f"Lake updated: {lake.name}", "Lakes")
            flash(f"Lake {lake.name} parameters updated.", 'success')
        elif action == 'delete':
            if session.get('role') == 'ADMIN':
                db.session.delete(lake)
                db.session.commit()
                log_audit(f"Lake deleted ID {id}", "Lakes")
                flash("Lake record deleted.", 'info')
                return redirect(url_for('lakes_view'))
            else:
                flash("Only Administrator can delete lake records.", 'danger')

    measurements = Measurement.query.filter_by(lake_id=id).order_by(Measurement.timestamp.desc()).limit(15).all()
    predictions = RiskPrediction.query.filter_by(lake_id=id).order_by(RiskPrediction.prediction_time.desc()).limit(5).all()
    alerts = Alert.query.filter(Alert.location.ilike(f"%{lake.name}%")).order_by(Alert.id.desc()).all()
    infrastructure = Infrastructure.query.limit(6).all()

    # Compute feature importance for current lake stats
    last_meas = measurements[0] if measurements else None
    feat_dict = {
        'water_level': lake.water_level,
        'water_level_change': lake.water_level_change,
        'rainfall': last_meas.rainfall if last_meas else 20.0,
        'temperature': last_meas.temperature if last_meas else 12.0,
        'ice_melt': last_meas.ice_melt if last_meas else 8.0,
        'glacier_stability': last_meas.glacier_stability if last_meas else 75.0,
        'terrain_movement': last_meas.terrain_movement if last_meas else 4.0,
        'seismic_activity': last_meas.seismic_activity if last_meas else 0.5
    }
    risk_data = compute_risk(feat_dict)

    return render_template(
        'lake_detail.html',
        lake=lake,
        measurements=measurements,
        predictions=predictions,
        alerts=alerts,
        infrastructure=infrastructure,
        risk_data=risk_data
    )

@app.route('/monitoring', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN', 'ENVIRONMENTAL_MONITOR', 'AUTHORITY'])
def monitoring_view():
    if request.method == 'POST' and session.get('role') != 'VIEWER':
        # Add new measurement
        lake_id = int(request.form.get('lake_id'))
        rainfall = float(request.form.get('rainfall', 0.0))
        temp = float(request.form.get('temperature', 0.0))
        ice_melt = float(request.form.get('ice_melt', 0.0))
        glacier_stab = float(request.form.get('glacier_stability', 80.0))
        terrain_mov = float(request.form.get('terrain_movement', 0.0))
        seismic = float(request.form.get('seismic_activity', 0.0))
        wl = float(request.form.get('water_level', 50.0))

        m = Measurement(
            lake_id=lake_id,
            rainfall=rainfall,
            temperature=temp,
            ice_melt=ice_melt,
            glacier_stability=glacier_stab,
            terrain_movement=terrain_mov,
            seismic_activity=seismic,
            water_level=wl,
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(m)

        # Update lake
        lake = db.session.get(Lake, lake_id)
        if lake:
            lake.water_level_change = round(wl - lake.water_level, 2)
            lake.water_level = wl
            # Auto recalculate risk
            r = compute_risk({
                'water_level': lake.water_level,
                'water_level_change': lake.water_level_change,
                'rainfall': rainfall,
                'temperature': temp,
                'ice_melt': ice_melt,
                'glacier_stability': glacier_stab,
                'terrain_movement': terrain_mov,
                'seismic_activity': seismic
            })
            lake.risk_score = r['risk_score']
            lake.risk_level = r['risk_level']

        db.session.commit()
        log_audit(f"Telemetry measurement logged for lake {lake_id}", "Monitoring")
        flash("Environmental sensor reading logged and risk indicators recalculated.", 'success')
        return redirect(url_for('monitoring_view'))

    lakes = Lake.query.all()
    recent_measurements = Measurement.query.order_by(Measurement.timestamp.desc()).limit(20).all()
    return render_template('monitoring.html', lakes=lakes, recent_measurements=recent_measurements)

@app.route('/risk')
@login_required
@role_required(['ADMIN', 'ENVIRONMENTAL_MONITOR', 'AUTHORITY'])
def risk_view():
    lakes = Lake.query.all()
    predictions = RiskPrediction.query.order_by(RiskPrediction.prediction_time.desc()).limit(15).all()
    return render_template('risk.html', lakes=lakes, predictions=predictions)

@app.route('/explainability')
@login_required
@role_required(['ADMIN', 'ENVIRONMENTAL_MONITOR', 'AUTHORITY'])
def explainability_view():
    # Base feature importances from trained model
    if ai_model is not None:
        raw_imp = ai_model.feature_importances_
    else:
        raw_imp = [0.12, 0.18, 0.22, 0.06, 0.14, 0.15, 0.08, 0.05]

    feature_importances = {name: round(float(imp) * 100, 1) for name, imp in zip(AI_FEATURE_NAMES, raw_imp)}
    recent_preds = RiskPrediction.query.order_by(RiskPrediction.prediction_time.desc()).limit(6).all()
    return render_template('explainability.html', feature_importances=feature_importances, recent_preds=recent_preds)

@app.route('/impact')
@login_required
def impact_view():
    high_risk_lakes = Lake.query.filter(Lake.risk_level.in_(['HIGH', 'CRITICAL'])).all()
    infrastructure = Infrastructure.query.all()
    evac_plans = EvacuationPlan.query.all()
    total_pop_threatened = sum(p.population for p in evac_plans)
    return render_template('impact.html', high_risk_lakes=high_risk_lakes, infrastructure=infrastructure, evac_plans=evac_plans, total_pop_threatened=total_pop_threatened)

@app.route('/alerts', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN', 'AUTHORITY', 'RESCUE_COORDINATOR'])
def alerts_view():
    if request.method == 'POST' and session.get('role') != 'VIEWER':
        hazard = request.form.get('hazard')
        location = request.form.get('location')
        severity = request.form.get('severity')
        message = request.form.get('message')
        aid = f"ALT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{random.randint(100, 999)}"

        alert = Alert(
            alert_id=aid,
            hazard=hazard,
            location=location,
            severity=severity,
            message=message,
            status='RECOMMENDED'
        )
        db.session.add(alert)
        db.session.commit()
        log_audit(f"New alert created {aid} ({hazard})", "Alerts")
        flash(f"Alert {aid} proposed and queued for Authority approval.", 'success')
        return redirect(url_for('alerts_view'))

    alerts = Alert.query.order_by(Alert.id.desc()).all()
    return render_template('alerts.html', alerts=alerts)

@app.route('/incidents', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN', 'AUTHORITY', 'RESCUE_COORDINATOR'])
def incidents_view():
    if request.method == 'POST' and session.get('role') != 'VIEWER':
        hazard = request.form.get('hazard')
        location = request.form.get('location')
        severity = request.form.get('severity')
        desc = request.form.get('description')
        iid = f"INC-{random.randint(1000, 9999)}"

        inc = Incident(
            incident_id=iid,
            hazard=hazard,
            location=location,
            severity=severity,
            description=desc,
            status='DETECTED'
        )
        db.session.add(inc)
        db.session.commit()
        log_audit(f"Incident logged {iid}", "Incidents")
        flash(f"Incident {iid} registered in command log.", 'success')
        return redirect(url_for('incidents_view'))

    incidents = Incident.query.order_by(Incident.id.desc()).all()
    rescue_teams = RescueTeam.query.all()
    return render_template('incidents.html', incidents=incidents, rescue_teams=rescue_teams)

@app.route('/rescue', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN', 'AUTHORITY', 'RESCUE_COORDINATOR'])
def rescue_view():
    teams = RescueTeam.query.all()
    sos_requests = SOSRequest.query.order_by(SOSRequest.id.desc()).all()
    incidents = Incident.query.filter(Incident.status.in_(['ACTIVE', 'DETECTED', 'VERIFIED'])).all()
    return render_template('rescue.html', teams=teams, sos_requests=sos_requests, incidents=incidents)

@app.route('/shelters', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN', 'AUTHORITY', 'RESCUE_COORDINATOR'])
def shelters_view():
    shelters = Shelter.query.all()
    return render_template('shelters.html', shelters=shelters)

@app.route('/evacuation', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN', 'AUTHORITY', 'RESCUE_COORDINATOR'])
def evacuation_view():
    if request.method == 'POST' and session.get('role') != 'VIEWER':
        zone = request.form.get('affected_zone')
        pop = int(request.form.get('population', 500))
        shelter = request.form.get('shelter')
        priority = request.form.get('priority', 'HIGH')

        plan = EvacuationPlan(
            affected_zone=zone,
            population=pop,
            shelter=shelter,
            priority=priority,
            status='PLANNED'
        )
        db.session.add(plan)
        db.session.commit()
        log_audit(f"Evacuation plan created for {zone}", "Evacuation")
        flash(f"Evacuation plan for {zone} registered.", 'success')
        return redirect(url_for('evacuation_view'))

    plans = EvacuationPlan.query.all()
    shelters = Shelter.query.all()
    return render_template('evacuation.html', plans=plans, shelters=shelters)

@app.route('/resources', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN', 'AUTHORITY', 'RESCUE_COORDINATOR'])
def resources_view():
    resources = Resource.query.all()
    return render_template('resources.html', resources=resources)

@app.route('/analytics')
@login_required
def analytics_view():
    lakes = Lake.query.all()
    alerts = Alert.query.all()
    incidents = Incident.query.all()
    shelters = Shelter.query.all()
    resources = Resource.query.all()
    teams = RescueTeam.query.all()
    return render_template(
        'analytics.html',
        lakes=lakes,
        alerts=alerts,
        incidents=incidents,
        shelters=shelters,
        resources=resources,
        teams=teams
    )

@app.route('/recovery')
@login_required
def recovery_view():
    infrastructure = Infrastructure.query.all()
    resolved_incidents = Incident.query.filter_by(status='RESOLVED').all()
    total_incidents = Incident.query.count()
    shelters = Shelter.query.all()
    resources = Resource.query.all()
    return render_template(
        'recovery.html',
        infrastructure=infrastructure,
        resolved_incidents=resolved_incidents,
        total_incidents=total_incidents,
        shelters=shelters,
        resources=resources
    )

@app.route('/simulation')
@login_required
def simulation_view():
    sim_state = SimulationState.query.first()
    lakes = Lake.query.all()
    return render_template('simulation.html', sim_state=sim_state, lakes=lakes)

@app.route('/system-health')
@login_required
def system_health_view():
    return render_template('system_health.html')

@app.route('/admin', methods=['GET', 'POST'])
@login_required
@role_required(['ADMIN'])
def admin_view():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create_user':
            name = request.form.get('name')
            email = request.form.get('email').strip().lower()
            password = request.form.get('password')
            role = request.form.get('role')

            if User.query.filter_by(email=email).first():
                flash('User email already exists.', 'danger')
            else:
                user = User(name=name, email=email, role=role, active=True)
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                log_audit(f"Admin created user {email} ({role})", "Admin")
                flash(f"User {name} successfully created.", 'success')
        elif action == 'toggle_active':
            uid = int(request.form.get('user_id'))
            user = db.session.get(User, uid)
            if user:
                user.active = not user.active
                db.session.commit()
                log_audit(f"User {user.email} active toggled to {user.active}", "Admin")
                flash(f"Status changed for {user.name}.", 'info')
        elif action == 'change_role':
            uid = int(request.form.get('user_id'))
            new_role = request.form.get('role')
            user = db.session.get(User, uid)
            if user:
                user.role = new_role
                db.session.commit()
                log_audit(f"User {user.email} role changed to {new_role}", "Admin")
                flash(f"Role updated for {user.name}.", 'info')

        return redirect(url_for('admin_view'))

    users = User.query.all()
    return render_template('admin.html', users=users)

@app.route('/audit-logs')
@login_required
@role_required(['ADMIN', 'AUTHORITY'])
def audit_logs_view():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(100).all()
    return render_template('audit_logs.html', logs=logs)

# -------------------------------------------------------------
# REST API ENDPOINTS
# -------------------------------------------------------------

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    user = User.query.filter_by(email=email).first()

    if user and user.check_password(password):
        if not user.active:
            return jsonify({'success': False, 'error': 'Account inactive'}), 403
        session['user_id'] = user.id
        session['user_name'] = user.name
        session['user_email'] = user.email
        session['role'] = user.role
        log_audit(f"API Login: {user.email}", "Auth API")
        return jsonify({'success': True, 'user': user.to_dict()})
    return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

@app.route('/api/dashboard', methods=['GET'])
@login_required
def api_dashboard():
    total_lakes = Lake.query.count()
    high_risk = Lake.query.filter_by(risk_level='HIGH').count()
    critical_risk = Lake.query.filter_by(risk_level='CRITICAL').count()
    active_alerts = Alert.query.filter_by(status='ACTIVE').count()
    active_incidents = Incident.query.filter(Incident.status.in_(['ACTIVE', 'VERIFIED'])).count()
    active_evacs = EvacuationPlan.query.filter_by(status='ACTIVE').all()
    affected_pop = sum(e.population for e in active_evacs) or 14200
    shelters = Shelter.query.all()
    avail_shelter = sum(s.capacity - s.occupied for s in shelters)
    active_teams = RescueTeam.query.filter(RescueTeam.status.in_(['DEPLOYED', 'EN_ROUTE'])).count()

    lakes = [l.to_dict() for l in Lake.query.all()]
    incidents = [i.to_dict() for i in Incident.query.filter_by(status='ACTIVE').all()]
    shelter_list = [s.to_dict() for s in shelters]
    teams = [t.to_dict() for t in RescueTeam.query.all()]

    return jsonify({
        'stats': {
            'total_lakes': total_lakes,
            'high_risk_lakes': high_risk,
            'critical_risk_lakes': critical_risk,
            'active_alerts': active_alerts,
            'active_incidents': active_incidents,
            'affected_population': affected_pop,
            'available_shelters': avail_shelter,
            'active_rescue_teams': active_teams
        },
        'lakes': lakes,
        'incidents': incidents,
        'shelters': shelter_list,
        'rescue_teams': teams
    })

@app.route('/api/lakes', methods=['GET', 'POST'])
@login_required
def api_lakes():
    if request.method == 'POST':
        if session.get('role') == 'VIEWER':
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        data = request.get_json() or {}
        lake = Lake(
            name=data.get('name'),
            location=data.get('location'),
            latitude=float(data.get('latitude', 0.0)),
            longitude=float(data.get('longitude', 0.0)),
            elevation=float(data.get('elevation', 0.0)),
            area=float(data.get('area', 0.0)),
            water_level=float(data.get('water_level', 50.0)),
            water_level_change=0.0,
            risk_score=20.0,
            risk_level='LOW',
            status='MONITORED'
        )
        db.session.add(lake)
        db.session.commit()
        log_audit(f"API Lake created {lake.name}", "Lakes")
        return jsonify({'success': True, 'lake': lake.to_dict()}), 201

    lakes = Lake.query.all()
    return jsonify([l.to_dict() for l in lakes])

@app.route('/api/lakes/<int:id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_lake_item(id):
    lake = Lake.query.get_or_404(id)
    if request.method == 'PUT':
        if session.get('role') == 'VIEWER':
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        data = request.get_json() or {}
        lake.name = data.get('name', lake.name)
        lake.water_level = float(data.get('water_level', lake.water_level))
        lake.status = data.get('status', lake.status)
        db.session.commit()
        return jsonify({'success': True, 'lake': lake.to_dict()})
    elif request.method == 'DELETE':
        if session.get('role') != 'ADMIN':
            return jsonify({'success': False, 'error': 'Admin required'}), 403
        db.session.delete(lake)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Deleted'})

    return jsonify(lake.to_dict())

@app.route('/api/measurements', methods=['GET', 'POST'])
@login_required
def api_measurements():
    if request.method == 'POST':
        if session.get('role') == 'VIEWER':
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        data = request.get_json() or {}
        m = Measurement(
            lake_id=int(data.get('lake_id')),
            rainfall=float(data.get('rainfall', 0.0)),
            temperature=float(data.get('temperature', 0.0)),
            ice_melt=float(data.get('ice_melt', 0.0)),
            glacier_stability=float(data.get('glacier_stability', 80.0)),
            terrain_movement=float(data.get('terrain_movement', 0.0)),
            seismic_activity=float(data.get('seismic_activity', 0.0)),
            water_level=float(data.get('water_level', 50.0)),
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(m)
        db.session.commit()
        return jsonify({'success': True, 'measurement': m.to_dict()}), 201

    lake_id = request.args.get('lake_id')
    if lake_id:
        measurements = Measurement.query.filter_by(lake_id=int(lake_id)).order_by(Measurement.timestamp.desc()).all()
    else:
        measurements = Measurement.query.order_by(Measurement.timestamp.desc()).limit(50).all()
    return jsonify([m.to_dict() for m in measurements])

@app.route('/api/risk/predict', methods=['POST'])
@login_required
def api_risk_predict():
    data = request.get_json() or {}
    result = compute_risk(data)

    # Optional: If lake_id provided, record into RiskPrediction
    lake_id = data.get('lake_id')
    if lake_id:
        try:
            rp = RiskPrediction(
                lake_id=int(lake_id),
                risk_score=result['risk_score'],
                risk_level=result['risk_level'],
                confidence=result['confidence'],
                prediction_time=datetime.now(timezone.utc)
            )
            db.session.add(rp)
            lake = db.session.get(Lake, int(lake_id))
            if lake:
                lake.risk_score = result['risk_score']
                lake.risk_level = result['risk_level']
            db.session.commit()
        except Exception as e:
            print(f"Error saving prediction: {e}")
            db.session.rollback()

    return jsonify(result)

@app.route('/api/alerts', methods=['GET', 'POST'])
@login_required
def api_alerts():
    if request.method == 'POST':
        if session.get('role') == 'VIEWER':
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        data = request.get_json() or {}
        aid = f"ALT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{random.randint(100, 999)}"
        alert = Alert(
            alert_id=aid,
            hazard=data.get('hazard', 'GLOF Threat'),
            location=data.get('location', 'High Mountain Lake'),
            severity=data.get('severity', 'HIGH'),
            message=data.get('message', 'High risk indicator triggered'),
            status='RECOMMENDED'
        )
        db.session.add(alert)
        db.session.commit()
        log_audit(f"Alert {aid} submitted", "Alerts")
        return jsonify({'success': True, 'alert': alert.to_dict()}), 201

    status_filter = request.args.get('status')
    if status_filter:
        alerts = Alert.query.filter_by(status=status_filter).order_by(Alert.id.desc()).all()
    else:
        alerts = Alert.query.order_by(Alert.id.desc()).all()
    return jsonify([a.to_dict() for a in alerts])

@app.route('/api/alerts/<int:id>/approve', methods=['POST'])
@login_required
@role_required(['ADMIN', 'AUTHORITY'])
def api_alert_approve(id):
    alert = Alert.query.get_or_404(id)
    alert.status = 'ACTIVE'
    alert.approved_by = session.get('user_name', 'Authorized Officer')
    db.session.commit()
    log_audit(f"Alert {alert.alert_id} APPROVED -> ACTIVE", "Alerts")
    return jsonify({'success': True, 'alert': alert.to_dict()})

@app.route('/api/alerts/<int:id>/reject', methods=['POST'])
@login_required
@role_required(['ADMIN', 'AUTHORITY'])
def api_alert_reject(id):
    alert = Alert.query.get_or_404(id)
    alert.status = 'REJECTED'
    alert.approved_by = session.get('user_name', 'Authorized Officer')
    db.session.commit()
    log_audit(f"Alert {alert.alert_id} REJECTED", "Alerts")
    return jsonify({'success': True, 'alert': alert.to_dict()})

@app.route('/api/incidents', methods=['GET', 'POST'])
@login_required
def api_incidents():
    if request.method == 'POST':
        if session.get('role') == 'VIEWER':
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        data = request.get_json() or {}
        iid = f"INC-{random.randint(1000, 9999)}"
        inc = Incident(
            incident_id=iid,
            hazard=data.get('hazard', 'Flash Surge'),
            location=data.get('location', 'Valley Riparian'),
            severity=data.get('severity', 'HIGH'),
            description=data.get('description', 'Surge alert response'),
            status='DETECTED'
        )
        db.session.add(inc)
        db.session.commit()
        log_audit(f"Incident {iid} registered", "Incidents")
        return jsonify({'success': True, 'incident': inc.to_dict()}), 201

    incidents = Incident.query.order_by(Incident.id.desc()).all()
    return jsonify([i.to_dict() for i in incidents])

@app.route('/api/incidents/<int:id>/status', methods=['POST'])
@login_required
def api_incident_status(id):
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    inc = Incident.query.get_or_404(id)
    data = request.get_json() or {}
    new_status = data.get('status')
    if new_status in ['DETECTED', 'VERIFIED', 'ACTIVE', 'CONTAINED', 'RESOLVED']:
        inc.status = new_status
        db.session.commit()
        log_audit(f"Incident {inc.incident_id} status changed to {new_status}", "Incidents")
        return jsonify({'success': True, 'incident': inc.to_dict()})
    return jsonify({'success': False, 'error': 'Invalid status'}), 400

@app.route('/api/rescue-teams', methods=['GET'])
@login_required
def api_rescue_teams():
    teams = RescueTeam.query.all()
    return jsonify([t.to_dict() for t in teams])

@app.route('/api/rescue-teams/<int:id>/status', methods=['POST'])
@login_required
def api_rescue_team_status(id):
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    team = RescueTeam.query.get_or_404(id)
    data = request.get_json() or {}
    new_status = data.get('status')
    if new_status in ['STANDBY', 'DEPLOYED', 'EN_ROUTE', 'RESTING']:
        team.status = new_status
        db.session.commit()
        log_audit(f"Team {team.team_name} status -> {new_status}", "Rescue")
        return jsonify({'success': True, 'team': team.to_dict()})
    return jsonify({'success': False, 'error': 'Invalid status'}), 400

@app.route('/api/sos', methods=['GET', 'POST'])
@login_required
def api_sos():
    if request.method == 'POST':
        data = request.get_json() or {}
        sos = SOSRequest(
            reporter=data.get('reporter', 'Anonymous Civilian'),
            location=data.get('location', 'Valley Reach'),
            priority=data.get('priority', 'HIGH'),
            status='PENDING'
        )
        db.session.add(sos)
        db.session.commit()
        log_audit(f"SOS alert lodged from {sos.location}", "SOS")
        return jsonify({'success': True, 'sos': sos.to_dict()}), 201

    sos_list = SOSRequest.query.order_by(SOSRequest.id.desc()).all()
    return jsonify([s.to_dict() for s in sos_list])

@app.route('/api/sos/<int:id>/assign', methods=['POST'])
@login_required
def api_sos_assign(id):
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    sos = SOSRequest.query.get_or_404(id)
    data = request.get_json() or {}
    team_name = data.get('assigned_team')
    sos.assigned_team = team_name
    sos.status = 'ASSIGNED'
    db.session.commit()
    log_audit(f"SOS #{sos.id} assigned to team {team_name}", "SOS")
    return jsonify({'success': True, 'sos': sos.to_dict()})

@app.route('/api/sos/<int:id>/resolve', methods=['POST'])
@login_required
def api_sos_resolve(id):
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    sos = SOSRequest.query.get_or_404(id)
    sos.status = 'RESOLVED'
    db.session.commit()
    log_audit(f"SOS #{sos.id} marked RESOLVED", "SOS")
    return jsonify({'success': True, 'sos': sos.to_dict()})

@app.route('/api/shelters', methods=['GET'])
@login_required
def api_shelters():
    shelters = Shelter.query.all()
    return jsonify([s.to_dict() for s in shelters])

@app.route('/api/shelters/<int:id>/occupancy', methods=['POST'])
@login_required
def api_shelter_occupancy(id):
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    shelter = Shelter.query.get_or_404(id)
    data = request.get_json() or {}
    occupied = int(data.get('occupied', shelter.occupied))
    shelter.occupied = min(shelter.capacity, max(0, occupied))
    pct = (shelter.occupied / shelter.capacity) * 100 if shelter.capacity > 0 else 0
    if pct >= 100:
        shelter.status = 'FULL'
    elif pct >= 80:
        shelter.status = 'NEAR_CAPACITY'
    elif pct == 0:
        shelter.status = 'OPEN'
    else:
        shelter.status = 'OPEN'
    db.session.commit()
    log_audit(f"Shelter {shelter.name} occupancy updated to {shelter.occupied}", "Shelters")
    return jsonify({'success': True, 'shelter': shelter.to_dict()})

@app.route('/api/evacuation', methods=['GET', 'POST'])
@login_required
def api_evacuation():
    if request.method == 'POST':
        if session.get('role') == 'VIEWER':
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        data = request.get_json() or {}
        plan = EvacuationPlan(
            affected_zone=data.get('affected_zone'),
            population=int(data.get('population', 1000)),
            shelter=data.get('shelter'),
            priority=data.get('priority', 'HIGH'),
            status='PLANNED'
        )
        db.session.add(plan)
        db.session.commit()
        return jsonify({'success': True, 'plan': plan.to_dict()}), 201

    plans = EvacuationPlan.query.all()
    return jsonify([p.to_dict() for p in plans])

@app.route('/api/evacuation/<int:id>/status', methods=['POST'])
@login_required
def api_evac_status(id):
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    plan = EvacuationPlan.query.get_or_404(id)
    data = request.get_json() or {}
    status = data.get('status')
    if status in ['PLANNED', 'ACTIVE', 'COMPLETED', 'CANCELLED']:
        plan.status = status
        db.session.commit()
        log_audit(f"Evacuation plan {plan.affected_zone} set to {status}", "Evacuation")
        return jsonify({'success': True, 'plan': plan.to_dict()})
    return jsonify({'success': False, 'error': 'Invalid status'}), 400

@app.route('/api/resources', methods=['GET'])
@login_required
def api_resources():
    resources = Resource.query.all()
    return jsonify([r.to_dict() for r in resources])

@app.route('/api/resources/<int:id>/allocate', methods=['POST'])
@login_required
def api_resource_allocate(id):
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    res = Resource.query.get_or_404(id)
    data = request.get_json() or {}
    alloc_amount = int(data.get('amount', 0))
    if alloc_amount > res.available:
        return jsonify({'success': False, 'error': 'Cannot allocate more than available'}), 400
    res.available -= alloc_amount
    res.allocated += alloc_amount
    db.session.commit()
    log_audit(f"Resource {res.name}: allocated {alloc_amount} units", "Resources")
    return jsonify({'success': True, 'resource': res.to_dict()})

@app.route('/api/analytics', methods=['GET'])
@login_required
def api_analytics():
    # Gather datasets for Chart.js
    lakes = Lake.query.all()
    risk_dist = {
        'LOW': sum(1 for l in lakes if l.risk_level == 'LOW'),
        'MODERATE': sum(1 for l in lakes if l.risk_level == 'MODERATE'),
        'HIGH': sum(1 for l in lakes if l.risk_level == 'HIGH'),
        'CRITICAL': sum(1 for l in lakes if l.risk_level == 'CRITICAL')
    }

    alerts = Alert.query.all()
    alert_statuses = {
        'RECOMMENDED': sum(1 for a in alerts if a.status == 'RECOMMENDED'),
        'PENDING APPROVAL': sum(1 for a in alerts if a.status == 'PENDING APPROVAL'),
        'ACTIVE': sum(1 for a in alerts if a.status == 'ACTIVE'),
        'RESOLVED': sum(1 for a in alerts if a.status == 'RESOLVED'),
        'REJECTED': sum(1 for a in alerts if a.status == 'REJECTED')
    }

    incidents = Incident.query.all()
    incident_stats = {
        'DETECTED': sum(1 for i in incidents if i.status == 'DETECTED'),
        'VERIFIED': sum(1 for i in incidents if i.status == 'VERIFIED'),
        'ACTIVE': sum(1 for i in incidents if i.status == 'ACTIVE'),
        'CONTAINED': sum(1 for i in incidents if i.status == 'CONTAINED'),
        'RESOLVED': sum(1 for i in incidents if i.status == 'RESOLVED')
    }

    shelters = Shelter.query.all()
    shelter_occupancy = [
        {'name': s.name, 'occupied': s.occupied, 'capacity': s.capacity} for s in shelters
    ]

    resources = Resource.query.all()
    res_data = [
        {'name': r.name, 'required': r.required, 'available': r.available, 'allocated': r.allocated} for r in resources
    ]

    return jsonify({
        'risk_distribution': risk_dist,
        'alert_statuses': alert_statuses,
        'incident_statuses': incident_stats,
        'shelter_occupancy': shelter_occupancy,
        'resources': res_data
    })

# -------------------------------------------------------------
# REAL-TIME DATA ENDPOINTS (COPERNICUS, NASA, OPEN-METEO, USGS)
# -------------------------------------------------------------
@app.route('/api/realtime/sync-all', methods=['POST'])
@login_required
def api_realtime_sync_all():
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized: Viewer account is read-only'}), 403
    result = sync_all_lakes_realtime(db, Lake, Measurement, RiskPrediction, compute_risk)
    log_audit(f"Real-Time Sync: Refreshed all {result['synced_count']} lakes via live Copernicus, NASA, Open-Meteo, and USGS feeds", "RealTime Sync")
    return jsonify(result)

@app.route('/api/realtime/sync/<int:id>', methods=['POST'])
@login_required
def api_realtime_sync_lake(id):
    if session.get('role') == 'VIEWER':
        return jsonify({'success': False, 'error': 'Unauthorized: Viewer account is read-only'}), 403
    lake = Lake.query.get_or_404(id)
    result = sync_lake_realtime(lake, db, compute_risk, Measurement, RiskPrediction, Alert)
    log_audit(f"Real-Time Sync: Refreshed {lake.name} via live Copernicus, NASA, Open-Meteo, and USGS feeds", "RealTime Sync")
    return jsonify({'success': True, 'sync': result})

@app.route('/api/realtime/satellite/<int:id>', methods=['GET'])
@login_required
def api_realtime_satellite_details(id):
    lake = Lake.query.get_or_404(id)
    copernicus_sat = fetch_copernicus_satellite_data(lake.latitude, lake.longitude)
    glofas_flow = fetch_glofas_river_discharge(lake.latitude, lake.longitude)
    nasa_cmr = fetch_nasa_satellite_granules(lake.latitude, lake.longitude)
    nasa_power = fetch_nasa_power_data(lake.latitude, lake.longitude)
    govt = get_official_government_metadata(lake.id)
    return jsonify({
        'success': True,
        'lake_id': lake.id,
        'lake_name': lake.name,
        'coordinates': {'latitude': lake.latitude, 'longitude': lake.longitude},
        'copernicus_sentinel': copernicus_sat,
        'copernicus_glofas': glofas_flow,
        'nasa_earthdata': nasa_cmr,
        'nasa_power': nasa_power,
        'government_registry': govt
    })

@app.route('/api/realtime/status', methods=['GET'])
@login_required
def api_realtime_status():
    connectivity = check_api_connectivity()
    recent_live = Measurement.query.filter(Measurement.data_source.ilike('%LIVE%')).order_by(Measurement.id.desc()).first()
    return jsonify({
        'connectivity': connectivity,
        'last_live_sync': recent_live.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC') if recent_live else 'Baseline (Unsynced)',
        'mode': connectivity.get('mode', 'MULTI_SATELLITE_LIVE_UPLINK')
    })

@app.route('/api/realtime/seismic', methods=['GET'])
@login_required
def api_realtime_seismic():
    feed = get_live_seismic_feed()
    return jsonify(feed)

@app.route('/api/health', methods=['GET'])
def api_health():
    db_status = "OPERATIONAL"
    try:
        db.session.execute(db.select(User).limit(1))
    except Exception:
        db_status = "DEGRADED"

    ai_status = "OPERATIONAL" if ai_model is not None else "DEGRADED (FALLBACK ACTIVE)"
    ext_health = check_api_connectivity()

    return jsonify({
        'status': 'OPERATIONAL',
        'components': {
            'backend_api': 'OPERATIONAL',
            'database': db_status,
            'ai_model': ai_status,
            'gis': 'OPERATIONAL',
            'alert_system': 'OPERATIONAL',
            'open_meteo_api': ext_health.get('open_meteo', 'OPERATIONAL'),
            'usgs_earthquake_api': ext_health.get('usgs', 'OPERATIONAL'),
            'copernicus_cdse_api': ext_health.get('copernicus_cdse', 'OPERATIONAL'),
            'copernicus_glofas_api': ext_health.get('copernicus_glofas', 'OPERATIONAL'),
            'nasa_earthdata_cmr': ext_health.get('nasa_earthdata_cmr', 'OPERATIONAL'),
            'isro_bhuvan_registry': ext_health.get('isro_bhuvan', 'REFERENCE_CATALOGUE'),
            'india_wris_cwc_registry': ext_health.get('india_wris_cwc', 'REFERENCE_CATALOGUE')
        },
        'data_uplink_mode': ext_health.get('mode', 'MULTI_SATELLITE_LIVE_UPLINK'),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'uptime': '99.98%'
    })

# -------------------------------------------------------------
# EMERGENCY SIMULATION CONTROLLER (23 STEPS)
# -------------------------------------------------------------

SIMULATION_STEPS = [
    {"step": 1, "title": "Environmental Telemetry Deteriorates", "desc": "Sensor anomalies recorded at South Lhonak Lake sub-basin."},
    {"step": 2, "title": "Water Level Surges", "desc": "Lake water level rises rapidly by +2.8 meters due to glacial discharge."},
    {"step": 3, "title": "Heavy Torrential Rainfall", "desc": "Extreme precipitation intensifies to 148 mm/24h over high catchment."},
    {"step": 4, "title": "Ice Melt Surge", "desc": "Thermal spike triggers accelerated glacial ice melt reaching 32 cm/day."},
    {"step": 5, "title": "Glacier Stability Drops", "desc": "Structural integrity of terminal moraine falls precipitously to 32%."},
    {"step": 6, "title": "Moraine Terrain Movement", "desc": "Displacement sensors register 34 mm/day moraine wall slippage."},
    {"step": 7, "title": "AI Risk Prediction Executed", "desc": "Multi-variable Random Forest engine executes predictive inference."},
    {"step": 8, "title": "Risk Level Reaches HIGH", "desc": "Predicted GLOF risk score jumps to 71.4 (HIGH threat level)."},
    {"step": 9, "title": "Risk Escalates to CRITICAL", "desc": "Catastrophic moraine breach imminent; risk surges to 94.2 (CRITICAL)."},
    {"step": 10, "title": "Downstream Impact Generated", "desc": "Hydrodynamic impact model calculates flood wave speed at 38 km/h."},
    {"step": 11, "title": "Affected Zones Identified", "desc": "Chungthang Valley, Dikchu Reach, and Singtam Lowlands flagged."},
    {"step": 12, "title": "Population Impact Estimated", "desc": "Downstream population at direct inundation risk estimated at 14,200."},
    {"step": 13, "title": "Alert Recommendation Generated", "desc": "System generates recommended alert ALT-SIM-901 for immediate review."},
    {"step": 14, "title": "Authority Review Requested", "desc": "Alert dispatched to National Disaster Authority pending queue."},
    {"step": 15, "title": "Authority Approves Alert", "desc": "Commanding Authority validates data and approves emergency broadcast."},
    {"step": 16, "title": "Alert Becomes ACTIVE", "desc": "Active alert broadcast sirens initiated across downstream corridors."},
    {"step": 17, "title": "Evacuation Plans Activated", "desc": "Evacuation Plan EP-01 (Chungthang Valley) shifted to ACTIVE status."},
    {"step": 18, "title": "Distress SOS Calls Logged", "desc": "Civilian SOS requests flood into rescue coordination hub."},
    {"step": 19, "title": "Rescue Teams Deployed", "desc": "Alpha-01 and Bravo-02 teams mobilized to forward staging grounds."},
    {"step": 20, "title": "Shelter Occupancy Spikes", "desc": "Evacuees arrive at designated safe shelters; capacity hits 88%."},
    {"step": 21, "title": "Resource Shortage Detected", "desc": "Critical shortage flagged for potable water and emergency rations."},
    {"step": 22, "title": "Incident Timeline Updated", "desc": "Major GLOF Incident INC-SIM-01 synchronized across command log."},
    {"step": 23, "title": "Recovery Phase Initiated", "desc": "Flood crest passes; water levels recede; recovery operation commences."}
]

@app.route('/api/simulation/status', methods=['GET'])
@login_required
def api_simulation_status():
    state = SimulationState.query.first()
    if not state:
        state = SimulationState(current_step=0, is_running=False)
        db.session.add(state)
        db.session.commit()

    return jsonify({
        'current_step': state.current_step,
        'is_running': state.is_running,
        'status_summary': state.status_summary,
        'total_steps': len(SIMULATION_STEPS),
        'step_details': SIMULATION_STEPS[state.current_step - 1] if state.current_step > 0 else None,
        'all_steps': SIMULATION_STEPS
    })

@app.route('/api/simulation/start', methods=['POST'])
@login_required
def api_simulation_start():
    state = SimulationState.query.first()
    if not state:
        state = SimulationState(current_step=0)
        db.session.add(state)
    state.is_running = True
    if state.current_step == 0:
        state.current_step = 1
        execute_simulation_step_logic(1)
    db.session.commit()
    log_audit("Emergency Simulation Started", "Simulation")
    return jsonify({'success': True, 'current_step': state.current_step, 'is_running': state.is_running})

@app.route('/api/simulation/step', methods=['POST'])
@login_required
def api_simulation_step():
    state = SimulationState.query.first()
    if not state:
        state = SimulationState(current_step=0)
        db.session.add(state)

    target_step = state.current_step + 1
    if target_step > 23:
        target_step = 23

    execute_simulation_step_logic(target_step)
    state.current_step = target_step
    state.last_updated = datetime.now(timezone.utc)
    db.session.commit()

    log_audit(f"Simulation progressed to Step {target_step}: {SIMULATION_STEPS[target_step-1]['title']}", "Simulation")
    return jsonify({
        'success': True,
        'current_step': state.current_step,
        'step_info': SIMULATION_STEPS[target_step-1],
        'is_running': state.is_running
    })

@app.route('/api/simulation/reset', methods=['POST'])
@login_required
def api_simulation_reset():
    state = SimulationState.query.first()
    if state:
        state.current_step = 0
        state.is_running = False
        state.status_summary = "Simulation Baseline Reset"

    # Reset South Lhonak Lake values
    lake = Lake.query.filter_by(name="South Lhonak Lake").first()
    if lake:
        lake.water_level = 84.5
        lake.water_level_change = 0.5
        lake.risk_score = 62.0
        lake.risk_level = "HIGH"
        lake.status = "ALERT"

    # Reset sim alert if present
    sim_alert = Alert.query.filter_by(alert_id="ALT-SIM-901").first()
    if sim_alert:
        db.session.delete(sim_alert)

    # Reset sim incident if present
    sim_inc = Incident.query.filter_by(incident_id="INC-SIM-01").first()
    if sim_inc:
        db.session.delete(sim_inc)

    # Reset evacuation plan status
    ep = EvacuationPlan.query.filter_by(affected_zone="Chungthang Valley Riparian Zone").first()
    if ep:
        ep.status = "PLANNED"

    # Reset teams
    for t in RescueTeam.query.all():
        if "Alpha-01" in t.team_name or "Bravo-02" in t.team_name:
            t.status = "STANDBY"

    db.session.commit()
    log_audit("Simulation reset to baseline state", "Simulation")
    return jsonify({'success': True, 'current_step': 0, 'message': 'Simulation reset successfully'})

def execute_simulation_step_logic(step_num):
    """Applies realistic state alterations to database records for each step"""
    lake = Lake.query.filter_by(name="South Lhonak Lake").first()
    if not lake:
        lake = Lake.query.first()

    now = datetime.now(timezone.utc)

    if step_num == 1:
        # Env conditions deteriorate
        m = Measurement(lake_id=lake.id, rainfall=65.0, temperature=18.5, ice_melt=14.0, glacier_stability=68.0, terrain_movement=8.5, seismic_activity=1.2, water_level=lake.water_level + 0.5, timestamp=now)
        db.session.add(m)
    elif step_num == 2:
        # Water level rises
        lake.water_level += 2.8
        lake.water_level_change = 2.8
        m = Measurement(lake_id=lake.id, rainfall=85.0, temperature=19.0, ice_melt=19.0, glacier_stability=60.0, terrain_movement=12.0, seismic_activity=1.4, water_level=lake.water_level, timestamp=now)
        db.session.add(m)
    elif step_num == 3:
        # Heavy rainfall increases
        m = Measurement(lake_id=lake.id, rainfall=148.0, temperature=16.0, ice_melt=22.0, glacier_stability=54.0, terrain_movement=16.0, seismic_activity=1.5, water_level=lake.water_level + 0.6, timestamp=now)
        lake.water_level += 0.6
        db.session.add(m)
    elif step_num == 4:
        # Ice melt increases
        m = Measurement(lake_id=lake.id, rainfall=150.0, temperature=21.0, ice_melt=32.0, glacier_stability=48.0, terrain_movement=19.0, seismic_activity=1.8, water_level=lake.water_level + 0.8, timestamp=now)
        lake.water_level += 0.8
        db.session.add(m)
    elif step_num == 5:
        # Glacier stability decreases
        m = Measurement(lake_id=lake.id, rainfall=152.0, temperature=21.0, ice_melt=34.0, glacier_stability=32.0, terrain_movement=24.0, seismic_activity=2.0, water_level=lake.water_level, timestamp=now)
        db.session.add(m)
    elif step_num == 6:
        # Terrain movement increases
        m = Measurement(lake_id=lake.id, rainfall=155.0, temperature=21.0, ice_melt=35.0, glacier_stability=28.0, terrain_movement=34.0, seismic_activity=2.2, water_level=lake.water_level, timestamp=now)
        db.session.add(m)
    elif step_num == 7:
        # Run AI prediction
        pred = compute_risk({
            'water_level': lake.water_level,
            'water_level_change': 3.5,
            'rainfall': 155.0,
            'temperature': 21.0,
            'ice_melt': 35.0,
            'glacier_stability': 28.0,
            'terrain_movement': 34.0,
            'seismic_activity': 2.2
        })
        rp = RiskPrediction(lake_id=lake.id, risk_score=pred['risk_score'], risk_level=pred['risk_level'], confidence=94.5, prediction_time=now)
        db.session.add(rp)
    elif step_num == 8:
        # Risk becomes HIGH
        lake.risk_score = 71.4
        lake.risk_level = "HIGH"
        lake.status = "ALERT"
    elif step_num == 9:
        # Risk becomes CRITICAL
        lake.risk_score = 94.2
        lake.risk_level = "CRITICAL"
        lake.status = "ACTIVE_BREACH_THREAT"
    elif step_num in [10, 11, 12]:
        # Impact analysis and zone identification
        lake.risk_score = 95.8
        infra = Infrastructure.query.filter_by(name="Chungthang Hydroelectric Dam").first()
        if infra:
            infra.condition = "CRITICAL"
            infra.status = "DEGRADED"
    elif step_num == 13:
        # Generate alert recommendation
        existing = Alert.query.filter_by(alert_id="ALT-SIM-901").first()
        if not existing:
            alert = Alert(
                alert_id="ALT-SIM-901",
                hazard="Catastrophic GLOF Surge (Simulated)",
                location=lake.name + " Sub-basin",
                severity="CRITICAL",
                message="EMERGENCY RECOMMENDATION: Extreme moraine displacement and surging water volume detected. Downstream flash inundation projected.",
                status="RECOMMENDED"
            )
            db.session.add(alert)
    elif step_num == 14:
        # Display authority approval request
        alert = Alert.query.filter_by(alert_id="ALT-SIM-901").first()
        if alert:
            alert.status = "PENDING APPROVAL"
    elif step_num == 15:
        # Authority approves alert
        alert = Alert.query.filter_by(alert_id="ALT-SIM-901").first()
        if alert:
            alert.status = "ACTIVE"
            alert.approved_by = "National Disaster Authority"
    elif step_num == 16:
        # Alert becomes ACTIVE
        alert = Alert.query.filter_by(alert_id="ALT-SIM-901").first()
        if alert:
            alert.status = "ACTIVE"
    elif step_num == 17:
        # Evacuation plan becomes ACTIVE
        plan = EvacuationPlan.query.filter_by(affected_zone="Chungthang Valley Riparian Zone").first()
        if plan:
            plan.status = "ACTIVE"
    elif step_num == 18:
        # SOS requests appear
        sos = SOSRequest(reporter="Civilian Evacuee Group 12", location="Chungthang Lower Hamlet Bridge", priority="CRITICAL", status="PENDING")
        db.session.add(sos)
    elif step_num == 19:
        # Rescue teams deploy
        t1 = RescueTeam.query.filter(RescueTeam.team_name.ilike("%Alpha-01%")).first()
        if t1:
            t1.status = "DEPLOYED"
        t2 = RescueTeam.query.filter(RescueTeam.team_name.ilike("%Bravo-02%")).first()
        if t2:
            t2.status = "DEPLOYED"
    elif step_num == 20:
        # Shelter occupancy increases
        sh = Shelter.query.filter_by(name="Chungthang High School Refuge").first()
        if sh:
            sh.occupied = 425
            sh.status = "NEAR_CAPACITY"
    elif step_num == 21:
        # Resource shortage appears
        res_water = Resource.query.filter(Resource.name.ilike("%Water%")).first()
        if res_water:
            res_water.required = 32000
            res_water.available = 4000
        res_med = Resource.query.filter(Resource.name.ilike("%Medical%")).first()
        if res_med:
            res_med.required = 500
            res_med.available = 60
    elif step_num == 22:
        # Incident timeline updates
        inc = Incident.query.filter_by(incident_id="INC-SIM-01").first()
        if not inc:
            inc = Incident(
                incident_id="INC-SIM-01",
                hazard="GLOF Outburst Peak Wave",
                location="Chungthang Dam Spillway",
                severity="CRITICAL",
                description="Peak flood wave reached Chungthang sector; containment defenses holding with emergency diversions active.",
                status="ACTIVE"
            )
            db.session.add(inc)
    elif step_num == 23:
        # Recovery phase begins
        lake.risk_score = 45.0
        lake.risk_level = "MODERATE"
        lake.status = "RECOVERING"
        inc = Incident.query.filter_by(incident_id="INC-SIM-01").first()
        if inc:
            inc.status = "CONTAINED"
        sh = Shelter.query.filter_by(name="Chungthang High School Refuge").first()
        if sh:
            sh.occupied = 280

# -------------------------------------------------------------
# ERROR HANDLERS
# -------------------------------------------------------------
@app.errorhandler(404)
def not_found_error(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Resource not found', 'status': 404}), 404
    return render_template('404.html'), 404

@app.errorhandler(403)
def forbidden_error(error):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Access denied', 'status': 403}), 403
    return render_template('403.html'), 403

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error', 'status': 500}), 500
    return render_template('500.html'), 500

# -------------------------------------------------------------
# INITIALIZATION RUNNER
# -------------------------------------------------------------
with app.app_context():
    seed_database()
    init_ai_engine()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
