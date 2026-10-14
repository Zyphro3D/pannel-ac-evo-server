from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.services.database import db


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Status constants ──────────────────────────────────────────────────────────

class EventStatus:
    DRAFT     = "draft"
    PUBLISHED = "published"
    FINISHED  = "finished"


class DriverStatus:
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RegStatus:
    PENDING   = "pending"
    CONFIRMED = "confirmed"
    REJECTED  = "rejected"


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

    # Champs personnels facultatifs, gérés en self-service via admin.my_account
    email                 = db.Column(db.String(120), nullable=True)
    steam_id              = db.Column(db.String(32),  nullable=True)
    steam_id_confirmed_at = db.Column(db.DateTime,    nullable=True)

    # Authentification à deux facteurs (v2.1.0) — voir services/totp.py
    totp_secret    = db.Column(db.String(64), nullable=True)
    totp_enabled   = db.Column(db.Boolean, default=False, nullable=False, server_default="0")
    totp_recovery  = db.Column(db.Text, nullable=True)        # JSON : hachés des codes de secours restants
    totp_last_step = db.Column(db.Integer, default=0)         # dernier pas accepté (anti-rejeu)

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
    status      = db.Column(db.String(20), default=DriverStatus.PENDING)  # pending/approved/rejected
    created_at  = db.Column(db.DateTime,  default=_utcnow)

    reset_token         = db.Column(db.String(64),  nullable=True)
    reset_token_expires = db.Column(db.DateTime,    nullable=True)

    # Confirmation d'email facultative (togglable via REQUIRE_EMAIL_CONFIRMATION) — voir public.py
    email_confirmed_at          = db.Column(db.DateTime,   nullable=True)
    email_confirm_token         = db.Column(db.String(64), nullable=True)
    email_confirm_token_expires = db.Column(db.DateTime,   nullable=True)

    # Compte Steam vérifié via Steam OpenID (jamais saisi à la main — voir auth.py steam_link/steam_callback)
    steam_id             = db.Column(db.String(32), unique=True, nullable=True)
    steam_id_confirmed_at = db.Column(db.DateTime,  nullable=True)

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
        return self.status == DriverStatus.APPROVED

    @property
    def is_email_confirmed(self) -> bool:
        return self.email_confirmed_at is not None


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
    status          = db.Column(db.String(20),  default=EventStatus.DRAFT) # draft/published/finished
    is_public         = db.Column(db.Boolean,     default=False)   # pas d'inscription requise
    email_sent        = db.Column(db.Boolean,     default=False)   # emails pré-événement envoyés
    discord_notified  = db.Column(db.Boolean,     default=False)   # notif Discord 30min envoyée
    auto_launch       = db.Column(db.Boolean,     default=False)   # lancer le serveur automatiquement
    launched          = db.Column(db.Boolean,     default=False)   # déjà lancé par le scheduler
    server_id         = db.Column(db.Integer,     nullable=True,  default=1)  # serveur cible pour auto-launch
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
        db.Index("ix_event_status_email_sent",       "status", "email_sent"),
        db.Index("ix_event_status_discord_notified",  "status", "discord_notified"),
        db.Index("ix_event_status_date",              "status", "date"),
    )

    @property
    def confirmed_count(self) -> int:
        return sum(1 for r in self.registrations if r.status == RegStatus.CONFIRMED)

    @property
    def pending_count(self) -> int:
        return sum(1 for r in self.registrations if r.status == RegStatus.PENDING)

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
    driver_id    = db.Column(db.Integer, db.ForeignKey("driver.id"), nullable=False, index=True)
    assigned_car = db.Column(db.String(100), default="")  # car.name depuis cars.json
    car_display  = db.Column(db.String(150), default="")  # car.display_name
    status       = db.Column(db.String(20),  default=RegStatus.PENDING)  # pending/confirmed/rejected
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
    run_id       = db.Column(db.String(40),  nullable=True, index=True)  # uuid du démarrage serveur (groupement fiable)
    server_id    = db.Column(db.Integer,     nullable=True, index=True)  # server gérant ce résultat (NULL = rétrocompat)
    raw_json     = db.Column(db.Text, nullable=False)
    raw_json_hash = db.Column(db.String(64), nullable=True, index=True)  # SHA-256[:64] pour dédup rapide


# ── LapRecord / LapArchive (historique de tours en direct, indépendant des fins
#    de session — voir CHANGELOG v1.9.4) ──────────────────────────────────────

class LapRecord(db.Model):
    __tablename__ = "lap_record"

    id           = db.Column(db.Integer, primary_key=True)
    server_id    = db.Column(db.Integer, nullable=False, index=True)
    steam_id     = db.Column(db.String(32),  nullable=False, index=True)
    nickname     = db.Column(db.String(100), default="")
    car          = db.Column(db.String(120), default="")   # slug, convention CarMeta.slug
    track_value  = db.Column(db.String(300), default="")   # convention TrackMeta.track_value
    session_type = db.Column(db.String(60),  default="")   # "Practice" / "Race Weekend"
    lap_time_ms  = db.Column(db.Integer, nullable=False)
    sector1_ms   = db.Column(db.Integer, nullable=True)
    sector2_ms   = db.Column(db.Integer, nullable=True)
    sector3_ms   = db.Column(db.Integer, nullable=True)
    recorded_at  = db.Column(db.DateTime, default=_utcnow, index=True)


class LapArchive(db.Model):
    __tablename__ = "lap_archive"

    id           = db.Column(db.Integer, primary_key=True)
    server_id    = db.Column(db.Integer, nullable=False, index=True)
    steam_id     = db.Column(db.String(32),  nullable=False, index=True)
    nickname     = db.Column(db.String(100), default="")
    track_value  = db.Column(db.String(300), default="")
    session_type = db.Column(db.String(60),  default="")
    period       = db.Column(db.String(7),  nullable=False)   # "2026-01"
    laps_json    = db.Column(db.Text, nullable=False)         # [{"t": ms, "car": slug}, ...]
    best_lap_ms  = db.Column(db.Integer, nullable=False)
    avg_lap_ms   = db.Column(db.Integer, nullable=False)
    lap_count    = db.Column(db.Integer, nullable=False)

    __table_args__ = (db.UniqueConstraint(
        "server_id", "steam_id", "track_value", "session_type", "period",
        name="uq_lap_archive_bucket"),)


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

    id               = db.Column(db.Integer, primary_key=True)
    slug             = db.Column(db.String(120), unique=True, nullable=False)  # car["name"] depuis cars.json
    display_name     = db.Column(db.String(150), default="", index=True)
    category         = db.Column(db.String(60),  default="")
    property_2_label = db.Column(db.String(60),  default="")
    property_3_label = db.Column(db.String(60),  default="")
    pi_min           = db.Column(db.Float,       nullable=True)
    pi_max           = db.Column(db.Float,       nullable=True)
    image_path       = db.Column(db.String(255), default="")               # relatif à media/cars/
    is_active        = db.Column(db.Boolean, default=True)
    is_mod           = db.Column(db.Boolean, default=False)  # tags manuels d'un mod (slug = nom de fichier .kspkg)


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
        driver = db.session.get(Driver, int(user_id[2:]))
        return driver if (driver and driver.status == DriverStatus.APPROVED) else None
    # Sessions legacy (avant migration) — tente de retrouver par rôle
    if user_id in ("admin", "superadmin"):
        return AdminAccount.query.filter_by(role=user_id, is_active=True).first()
    return None


class AccessRule(db.Model):
    """Règle d'accès par SteamID : bannissement et/ou handicap (lest, restricteur).

    Lue à chaque démarrage du serveur de jeu pour générer son fichier d'engagés
    (voir services/access_control.py). Indépendante des comptes pilotes : on peut bannir
    ou handicaper un joueur qui n'a jamais créé de compte sur le panel."""
    __tablename__ = "access_rule"

    id         = db.Column(db.Integer, primary_key=True)
    steam_id   = db.Column(db.String(32), unique=True, nullable=False, index=True)
    label      = db.Column(db.String(100), default="")          # pseudo / note de l'admin
    banned     = db.Column(db.Boolean, default=False, nullable=False)
    ballast    = db.Column(db.Integer, default=0, nullable=False)       # kg, 0–100
    restrictor = db.Column(db.Float,   default=0.0, nullable=False)     # 0–0,2
    created_at = db.Column(db.DateTime, default=_utcnow)


# ── Journal d'audit, état du panel, mesures de santé, championnats (v2.1.0) ───

class PanelState(db.Model):
    """Petites valeurs d'état modifiées à l'exécution (ex. date de remise à zéro du fair-play)."""
    __tablename__ = "panel_state"

    key        = db.Column(db.String(80), primary_key=True)
    value      = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)


class AuditLog(db.Model):
    """Qui a fait quoi, quand et depuis où. Jamais de secret dans ``detail``."""
    __tablename__ = "audit_log"

    id         = db.Column(db.Integer, primary_key=True)
    ts         = db.Column(db.DateTime, default=_utcnow, index=True, nullable=False)
    actor      = db.Column(db.String(80), default="", index=True)     # nom d'utilisateur ("" = système / anonyme)
    actor_role = db.Column(db.String(20), default="")
    ip         = db.Column(db.String(64), default="")
    action     = db.Column(db.String(60), default="", index=True)     # ex. "login.ok", "server.start"
    target     = db.Column(db.String(200), default="")                # objet concerné (pilote, config, clé de réglage…)
    detail     = db.Column(db.Text, default="")                       # JSON court
    ok         = db.Column(db.Boolean, default=True, nullable=False)


class HealthSample(db.Model):
    """Mesure périodique des ressources (une par minute, conservée 7 jours)."""
    __tablename__ = "health_sample"

    id        = db.Column(db.Integer, primary_key=True)
    ts        = db.Column(db.DateTime, default=_utcnow, index=True, nullable=False)
    server_id = db.Column(db.Integer, nullable=False, default=1, index=True)
    cpu       = db.Column(db.Float, default=0.0)        # % d'un cœur
    mem_mb    = db.Column(db.Float, default=0.0)
    players   = db.Column(db.Integer, default=0)
    running   = db.Column(db.Boolean, default=False)


class Championship(db.Model):
    __tablename__ = "championship"

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    slug         = db.Column(db.String(60), unique=True, nullable=False)
    description  = db.Column(db.String(500), default="")
    points       = db.Column(db.String(200), default="25,18,15,12,10,8,6,4,2,1")   # points par position
    fastest_lap_bonus = db.Column(db.Integer, default=0)      # points pour le meilleur tour de la manche
    pole_bonus   = db.Column(db.Integer, default=0)           # points pour la première place sur la grille
    drop_worst   = db.Column(db.Integer, default=0)           # nombre de pires manches retirées
    min_rounds_ratio = db.Column(db.Float, default=0.0)       # part des manches exigée pour être classé (0 = aucune)
    is_public    = db.Column(db.Boolean, default=True, nullable=False)
    created_at   = db.Column(db.DateTime, default=_utcnow)
    rounds       = db.relationship("ChampionshipRound", backref="championship", cascade="all, delete-orphan",
                                   order_by="ChampionshipRound.position")


class ChampionshipRound(db.Model):
    """Une manche : une course (SessionResult) comptée dans un championnat."""
    __tablename__ = "championship_round"

    id              = db.Column(db.Integer, primary_key=True)
    championship_id = db.Column(db.Integer, db.ForeignKey("championship.id"), nullable=False, index=True)
    result_id       = db.Column(db.Integer, db.ForeignKey("session_result.id"), nullable=False)
    label           = db.Column(db.String(120), default="")
    position        = db.Column(db.Integer, default=0)
