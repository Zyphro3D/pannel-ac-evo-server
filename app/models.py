from datetime import datetime
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.services.database import db


# ── Admin / Superadmin (in-memory, no DB) ────────────────────────────────────

class AdminUser(UserMixin):
    def __init__(self, role: str = "admin"):
        self.id   = role
        self.role = role

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"

    @property
    def is_admin(self) -> bool:
        return True

    @property
    def is_pilot(self) -> bool:
        return False

    @staticmethod
    def check_credentials(username: str, password: str) -> str | None:
        cfg = current_app.config
        if username == cfg.get("SUPERADMIN_USERNAME") and password == cfg.get("SUPERADMIN_PASSWORD"):
            return "superadmin"
        if username == cfg.get("ADMIN_USERNAME") and password == cfg.get("ADMIN_PASSWORD"):
            return "admin"
        return None


# ── Driver (pilote, stocké en DB) ─────────────────────────────────────────────

class Driver(UserMixin, db.Model):
    __tablename__ = "driver"

    id          = db.Column(db.Integer, primary_key=True)
    ingame_name = db.Column(db.String(50),  unique=True, nullable=False)
    email       = db.Column(db.String(120), unique=True, nullable=False)
    _pw_hash    = db.Column("password_hash", db.String(256), nullable=False)
    status      = db.Column(db.String(20), default="pending")  # pending/approved/rejected
    created_at  = db.Column(db.DateTime,  default=datetime.utcnow)

    reset_token         = db.Column(db.String(64),  nullable=True)
    reset_token_expires = db.Column(db.DateTime,    nullable=True)

    registrations = db.relationship("EventRegistration", back_populates="driver", lazy="dynamic")

    # Flask-Login: prefix "d_" pour distinguer des admins
    def get_id(self) -> str:
        return f"d_{self.id}"

    def set_password(self, password: str):
        self._pw_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self._pw_hash, password)

    @property
    def is_superadmin(self) -> bool:
        return False

    @property
    def is_admin(self) -> bool:
        return False

    @property
    def is_pilot(self) -> bool:
        return True

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"


# ── Event ─────────────────────────────────────────────────────────────────────

class Event(db.Model):
    __tablename__ = "event"

    id              = db.Column(db.Integer, primary_key=True)
    title           = db.Column(db.String(100), nullable=False)
    description     = db.Column(db.Text,        default="")
    date            = db.Column(db.DateTime,    nullable=False)  # UTC
    circuit         = db.Column(db.String(200), default="")      # SelectedTrackValue (pipe-separated)
    circuit_display = db.Column(db.String(200), default="")      # lisible : "Track — Layout"
    mode            = db.Column(db.String(60),  default="GameModeType_PRACTICE")
    weather         = db.Column(db.String(60),  default="GameModeSelectionWeatherType_CLEAR")
    max_drivers     = db.Column(db.Integer,     default=20)
    password        = db.Column(db.String(50),  default="")      # mot de passe course privée
    notify_before   = db.Column(db.Integer,     default=60)      # minutes avant le départ
    status          = db.Column(db.String(20),  default="draft") # draft/published/finished
    email_sent        = db.Column(db.Boolean,     default=False)   # emails pré-événement envoyés
    discord_notified  = db.Column(db.Boolean,     default=False)   # notif Discord 30min envoyée
    auto_launch       = db.Column(db.Boolean,     default=False)   # lancer le serveur automatiquement
    launched          = db.Column(db.Boolean,     default=False)   # déjà lancé par le scheduler
    created_at      = db.Column(db.DateTime,    default=datetime.utcnow)
    # Durées de session (minutes)
    practice_minutes   = db.Column(db.Integer, default=60)
    qualifying_minutes = db.Column(db.Integer, default=30)
    warmup_minutes     = db.Column(db.Integer, default=10)
    race_minutes       = db.Column(db.Integer, default=60)
    # Voitures autorisées pour cet événement (JSON list de car.name)
    allowed_cars       = db.Column(db.Text, default="[]")

    registrations = db.relationship("EventRegistration", back_populates="event",
                                    lazy="dynamic", cascade="all, delete-orphan")

    @property
    def confirmed_count(self) -> int:
        return self.registrations.filter_by(status="confirmed").count()

    @property
    def pending_count(self) -> int:
        return self.registrations.filter_by(status="pending").count()

    @property
    def is_full(self) -> bool:
        return self.confirmed_count >= self.max_drivers

    @property
    def mode_display(self) -> str:
        return {
            "GameModeType_PRACTICE":     "Practice",
            "GameModeType_RACE_WEEKEND": "Race Weekend",
        }.get(self.mode, self.mode)

    @property
    def weather_display(self) -> str:
        return {
            "GameModeSelectionWeatherType_CLEAR":    "Dégagé",
            "GameModeSelectionWeatherType_OVERCAST": "Nuageux",
            "GameModeSelectionWeatherType_RAIN":     "Pluie",
        }.get(self.weather, self.weather)


# ── EventRegistration ─────────────────────────────────────────────────────────

class EventRegistration(db.Model):
    __tablename__ = "event_registration"

    id           = db.Column(db.Integer, primary_key=True)
    event_id     = db.Column(db.Integer, db.ForeignKey("event.id"),  nullable=False)
    driver_id    = db.Column(db.Integer, db.ForeignKey("driver.id"), nullable=False)
    assigned_car = db.Column(db.String(100), default="")  # car.name depuis cars.json
    car_display  = db.Column(db.String(150), default="")  # car.display_name
    status       = db.Column(db.String(20),  default="pending")  # pending/confirmed/rejected
    notified     = db.Column(db.Boolean,     default=False)      # email pré-event envoyé
    created_at   = db.Column(db.DateTime,    default=datetime.utcnow)

    event  = db.relationship("Event",  back_populates="registrations")
    driver = db.relationship("Driver", back_populates="registrations")

    __table_args__ = (db.UniqueConstraint("event_id", "driver_id"),)


# ── Flask-Login user_loader ───────────────────────────────────────────────────

from app import login_manager

@login_manager.user_loader
def load_user(user_id: str):
    if user_id in ("admin", "superadmin"):
        return AdminUser(role=user_id)
    if user_id.startswith("d_"):
        return db.session.get(Driver, int(user_id[2:]))
    return None
