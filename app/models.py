from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.services.database import db


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── AdminAccount (admin/superadmin stockés en DB) ────────────────────────────

class AdminAccount(UserMixin, db.Model):
    __tablename__ = "admin_account"

    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100), default="")
    _pw_hash     = db.Column("password_hash", db.String(256), nullable=False, default="")
    role         = db.Column(db.String(20), default="admin")   # "admin" | "superadmin"
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=_utcnow)
    last_login   = db.Column(db.DateTime, nullable=True)

    def get_id(self) -> str:
        return f"aa_{self.id}"

    def set_password(self, password: str):
        self._pw_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self._pw_hash, password) if self._pw_hash else False

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin"

    @property
    def is_admin(self) -> bool:
        return True

    @property
    def is_pilot(self) -> bool:
        return False

    @property
    def display(self) -> str:
        return self.display_name or self.username


# ── Driver (pilote, stocké en DB) ─────────────────────────────────────────────

class Driver(UserMixin, db.Model):
    __tablename__ = "driver"

    id          = db.Column(db.Integer, primary_key=True)
    ingame_name = db.Column(db.String(50),  unique=True, nullable=False)
    email       = db.Column(db.String(120), unique=True, nullable=False)
    _pw_hash    = db.Column("password_hash", db.String(256), nullable=False)
    status      = db.Column(db.String(20), default="pending")  # pending/approved/rejected
    created_at  = db.Column(db.DateTime,  default=_utcnow)

    reset_token         = db.Column(db.String(64),  nullable=True)
    reset_token_expires = db.Column(db.DateTime,    nullable=True)

    registrations = db.relationship("EventRegistration", back_populates="driver", lazy="select")

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
    is_public         = db.Column(db.Boolean,     default=False)   # pas d'inscription requise
    email_sent        = db.Column(db.Boolean,     default=False)   # emails pré-événement envoyés
    discord_notified  = db.Column(db.Boolean,     default=False)   # notif Discord 30min envoyée
    auto_launch       = db.Column(db.Boolean,     default=False)   # lancer le serveur automatiquement
    launched          = db.Column(db.Boolean,     default=False)   # déjà lancé par le scheduler
    created_at      = db.Column(db.DateTime,    default=_utcnow)
    # Durées de session (minutes)
    practice_minutes   = db.Column(db.Integer, default=60)
    qualifying_minutes = db.Column(db.Integer, default=30)
    warmup_minutes     = db.Column(db.Integer, default=10)
    race_minutes       = db.Column(db.Integer, default=60)
    # Voitures autorisées pour cet événement (JSON list de car.name)
    allowed_cars       = db.Column(db.Text, default="[]")
    # Réglages par voiture : JSON {car_name: {ballast, restrictor}}
    cars_config        = db.Column(db.Text, default="{}")

    registrations = db.relationship("EventRegistration", back_populates="event",
                                    lazy="select", cascade="all, delete-orphan")

    __table_args__ = (
        db.Index("ix_event_status_email_sent",      "status", "email_sent"),
        db.Index("ix_event_status_discord_notified", "status", "discord_notified"),
    )

    @property
    def confirmed_count(self) -> int:
        return sum(1 for r in self.registrations if r.status == "confirmed")

    @property
    def pending_count(self) -> int:
        return sum(1 for r in self.registrations if r.status == "pending")

    @property
    def is_full(self) -> bool:
        return self.confirmed_count >= self.max_drivers

    @property
    def total_minutes(self) -> int:
        if self.mode == "GameModeType_RACE_WEEKEND":
            return ((self.practice_minutes or 0) + (self.qualifying_minutes or 0)
                    + (self.warmup_minutes or 0) + (self.race_minutes or 0))
        return self.practice_minutes or 0

    @property
    def end_date(self):
        from datetime import timedelta
        return self.date + timedelta(minutes=self.total_minutes)

    @property
    def mode_display(self) -> str:
        return {
            "GameModeType_PRACTICE":     "Practice",
            "GameModeType_RACE_WEEKEND": "Race Weekend",
        }.get(self.mode, self.mode)

    @property
    def weather_display(self) -> str:
        return {
            "GameModeSelectionWeatherType_CLEAR":    "Clear",
            "GameModeSelectionWeatherType_OVERCAST": "Overcast",
            "GameModeSelectionWeatherType_RAIN":     "Rain",
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
    created_at   = db.Column(db.DateTime,    default=_utcnow)

    event  = db.relationship("Event",  back_populates="registrations")
    driver = db.relationship("Driver", back_populates="registrations")

    __table_args__ = (db.UniqueConstraint("event_id", "driver_id"),)


# ── SessionResult ─────────────────────────────────────────────────────────────

class SessionResult(db.Model):
    __tablename__ = "session_result"

    id           = db.Column(db.Integer,  primary_key=True)
    received_at  = db.Column(db.DateTime, default=_utcnow, index=True)
    source       = db.Column(db.String(20),  default="webhook")   # "webhook" | "file"
    track        = db.Column(db.String(200), default="")
    session_type = db.Column(db.String(60),  default="")
    config_name  = db.Column(db.String(200), nullable=True)       # config JSON actif au moment de la réception
    run_id       = db.Column(db.String(40),  nullable=True)       # uuid du démarrage serveur (groupement fiable)
    server_id    = db.Column(db.Integer,     nullable=True, index=True)  # server gérant ce résultat (NULL = rétrocompat)
    raw_json     = db.Column(db.Text, nullable=False)


# ── Server (instance ACE EVO gérée par le panel) ─────────────────────────────

class Server(db.Model):
    __tablename__ = "server"

    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(100), nullable=False)
    slug            = db.Column(db.String(40),  unique=True, nullable=False)
    tcp_port        = db.Column(db.Integer, default=9700)
    udp_port        = db.Column(db.Integer, default=9700)
    http_port       = db.Column(db.Integer, default=8081)
    container_name  = db.Column(db.String(80),  unique=True, nullable=False)
    driver_password = db.Column(db.String(255), default="")
    admin_password  = db.Column(db.String(255), default="")
    active_config           = db.Column(db.String(255), default="default.json")
    discord_webhook_main    = db.Column(db.String(255), default="")
    discord_webhook_pilots  = db.Column(db.String(255), default="")
    discord_webhook_race    = db.Column(db.String(255), default="")
    is_enabled      = db.Column(db.Boolean, default=True)
    sort_order      = db.Column(db.Integer, default=0)
    created_at      = db.Column(db.DateTime, default=_utcnow)


# ── CarMeta (métadonnées enrichies des véhicules) ─────────────────────────────

class CarMeta(db.Model):
    __tablename__ = "car_meta"

    id           = db.Column(db.Integer, primary_key=True)
    slug         = db.Column(db.String(120), unique=True, nullable=False)  # car["name"] depuis cars.json
    display_name = db.Column(db.String(150), default="")
    category     = db.Column(db.String(60),  default="")
    pi_min       = db.Column(db.Float,       nullable=True)
    pi_max       = db.Column(db.Float,       nullable=True)
    image_path   = db.Column(db.String(255), default="")                   # relatif à media/cars/
    is_active    = db.Column(db.Boolean, default=True)


# ── TrackMeta (métadonnées enrichies des circuits) ────────────────────────────

class TrackMeta(db.Model):
    __tablename__ = "track_meta"

    id           = db.Column(db.Integer, primary_key=True)
    track_value  = db.Column(db.String(300), unique=True, nullable=False)  # "slug|layout|label|length_m"
    track_name   = db.Column(db.String(150), default="")
    layout       = db.Column(db.String(100), default="")
    length_m     = db.Column(db.Integer,     nullable=True)
    image_path   = db.Column(db.String(255), default="")                   # relatif à media/circuits/
    is_active    = db.Column(db.Boolean, default=True)


# ── Mod (mods véhicules/circuits téléchargeables) ─────────────────────────────

class Mod(db.Model):
    __tablename__ = "mod"

    id           = db.Column(db.Integer, primary_key=True)
    mod_type     = db.Column(db.String(20),  nullable=False)               # "car" | "circuit"
    name         = db.Column(db.String(150), nullable=False)
    version      = db.Column(db.String(40),  default="")
    source_url   = db.Column(db.String(500), default="")
    status       = db.Column(db.String(20),  default="available")          # available|installed|updating|error
    installed_at = db.Column(db.DateTime,    nullable=True)
    created_at   = db.Column(db.DateTime,    default=_utcnow)


# ── Flask-Login user_loader ───────────────────────────────────────────────────

from app import login_manager

@login_manager.user_loader
def load_user(user_id: str):
    if user_id.startswith("aa_"):
        acc = db.session.get(AdminAccount, int(user_id[3:]))
        return acc if (acc and acc.is_active) else None
    if user_id.startswith("d_"):
        return db.session.get(Driver, int(user_id[2:]))
    # Sessions legacy (avant migration) — tente de retrouver par rôle
    if user_id in ("admin", "superadmin"):
        return AdminAccount.query.filter_by(role=user_id, is_active=True).first()
    return None
