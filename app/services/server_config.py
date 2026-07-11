import json
import logging
import os
import re
import shutil
from pathlib import Path
from flask import current_app, session

log = logging.getLogger(__name__)


class ConfigJsonError(Exception):
    """Raised when the active config file contains invalid JSON."""
    def __init__(self, filename: str, line: int, col: int, msg: str):
        self.filename = filename
        self.line     = line
        self.col      = col
        super().__init__(f"{filename}: line {line} col {col} — {msg}")


def _configs_base() -> Path:
    """Dossier partagé des configs (source de vérité). Fonctionne avec ou sans app context."""
    try:
        return Path(current_app.config["CONFIGS_DIR"])
    except RuntimeError:
        return Path(os.environ.get("CONFIGS_DIR", "/aceserver/configs"))


# ── Runtime : dossier de configs déployées par serveur ───────────────────────

def _runtime_dir(server_id: int) -> Path:
    """Dossier server-{id}/ contenant les copies déployées pour ce serveur."""
    d = _configs_base() / f"server-{server_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _results_post_url(server_id: int) -> str:
    """URL du webhook d'ingestion de résultats, avec le server_id pour que le
    panel sache quel serveur a envoyé le résultat (cf. api.py:results_ingest)."""
    import os as _os
    port       = _os.environ.get("PANEL_PORT", "4300")
    deploy     = _os.environ.get("DEPLOY_MODE", "native")
    panel_host = "panel" if deploy == "docker_split" else "127.0.0.1"
    return f"http://{panel_host}:{port}/api/results/ingest?server_id={server_id}"


def deploy_config(config_name: str, server_id: int) -> None:
    """Copie config_name depuis la bibliothèque partagée vers server-{id}/,
    en injectant TcpPort/UdpPort/HttpPort/ResultsPostUrl propres à ce serveur."""
    if not _valid_config_name(config_name):
        log.warning("deploy_config: nom de config invalide refusé : %r", config_name)
        return
    base = _configs_base()
    src  = base / config_name
    if not src.exists():
        log.warning("deploy_config: source introuvable : %s", config_name)
        return
    runtime = base / f"server-{server_id}"
    runtime.mkdir(parents=True, exist_ok=True)
    dst  = runtime / config_name
    data = json.loads(src.read_text(encoding="utf-8"))
    data.setdefault("Server", {})["ResultsPostUrl"] = _results_post_url(server_id)
    try:
        from app.models import Server
        from app.services.database import db
        srv = db.session.get(Server, server_id)
        if srv:
            data["Server"].update({
                "TcpPort":  srv.tcp_port,
                "UdpPort":  srv.udp_port,
                "HttpPort": srv.http_port,
            })
    except Exception as e:
        log.warning("deploy_config: DB lookup échouée pour server %d: %s", server_id, e)
    _atomic_write_json(dst, data)
    log.info("deploy_config: %s → server-%d/", config_name, server_id)


def deployed_configs(server_id: int) -> set[str]:
    """Noms des configs déjà déployées pour ce serveur (présentes dans server-{id}/)."""
    d = _configs_base() / f"server-{server_id}"
    if not d.exists():
        return set()
    return {f.name for f in d.glob("*.json") if f.is_file()}


def delete_server_runtime_dir(server_id: int) -> None:
    """Supprime server-{id}/ lors de la suppression d'un serveur."""
    d = _configs_base() / f"server-{server_id}"
    if d.exists():
        shutil.rmtree(str(d))
        log.info("delete_server_runtime_dir: server-%d/ supprimé", server_id)


def _atomic_write_json(path: Path, data: dict):
    """Write JSON atomically (tmp file + os.replace) to avoid partial reads on crash."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _current_server_id() -> int:
    return int(session.get("current_server_id", 1) or 1)


# ── Helpers dossier ──────────────────────────────────────────────────────────

def _configs_dir() -> Path:
    return _configs_base()

def _cars_path() -> Path:
    return Path(current_app.config["CARS_JSON_PATH"])

def _events_path(mode: str = "practice") -> Path:
    key = "EVENTS_PRACTICE_JSON_PATH" if mode == "practice" else "EVENTS_RACE_JSON_PATH"
    return Path(current_app.config[key])


# ── Validation du nom de fichier de config ────────────────────────────────────

_CONFIG_NAME_RE = re.compile(r'^[\w\-. ]+\.json$')

def _valid_config_name(name: str) -> bool:
    """Valide qu'un nom de config est sûr : alphanum/tiret/espace/point, extension .json."""
    return bool(_CONFIG_NAME_RE.match(name)) and ".." not in name and "/" not in name and "\\" not in name


# ── Gestion des fichiers de config ───────────────────────────────────────────

def list_configs() -> list[str]:
    """Retourne les noms de tous les fichiers .json dans CONFIGS_DIR."""
    d = _configs_dir()
    return sorted(p.name for p in d.glob("*.json") if p.is_file())


def get_active_config_name() -> str:
    """Config active stockée en DB par serveur ; fallback sur le premier fichier trouvé."""
    from app.models import Server
    from app.services.database import db
    configs = list_configs()
    if not configs:
        return ""
    sid = _current_server_id()
    srv = db.session.get(Server, sid)
    name = srv.active_config if srv else None
    if name and name in configs:
        return name
    if srv:
        srv.active_config = configs[0]
        db.session.commit()
    return configs[0]


def set_active_config(name: str) -> bool:
    from app.models import Server
    from app.services.database import db
    configs = list_configs()
    if name not in configs:
        return False
    sid = _current_server_id()
    srv = db.session.get(Server, sid)
    if srv:
        srv.active_config = name
        db.session.commit()
    return True


def _active_path() -> Path:
    return _configs_dir() / get_active_config_name()


def create_config(name: str, copy_from: str | None = None) -> dict:
    """Crée un nouveau fichier de config. Copie copy_from si fourni, sinon template vide."""
    if not name.endswith(".json"):
        name += ".json"
    if not _valid_config_name(name):
        return {"ok": False, "error": "invalid_name"}

    dest = _configs_dir() / name
    if dest.exists():
        return {"ok": False, "error": "file_exists"}

    if copy_from:
        if not _valid_config_name(copy_from):
            return {"ok": False, "error": "invalid_source_name"}
        src = _configs_dir() / copy_from
        if not src.exists():
            return {"ok": False, "error": "source_not_found"}
        shutil.copy2(src, dest)
    else:
        dest.write_text(json.dumps(_default_config(), indent=2, ensure_ascii=False), encoding="utf-8")

    return {"ok": True, "name": name}


def delete_config(name: str) -> dict:
    configs = list_configs()
    if name not in configs:
        return {"ok": False, "error": "not_found"}
    if len(configs) == 1:
        return {"ok": False, "error": "cannot_delete_last"}

    (_configs_dir() / name).unlink()

    from app.models import Server
    from app.services.database import db
    remaining = [c for c in configs if c != name]
    for srv in Server.query.filter_by(active_config=name).all():
        srv.active_config = remaining[0]
    db.session.commit()

    return {"ok": True}


def rename_config(old_name: str, new_name: str) -> dict:
    if not new_name.endswith(".json"):
        new_name += ".json"
    if not _valid_config_name(new_name):
        return {"ok": False, "error": "invalid_name"}
    configs = list_configs()
    if old_name not in configs:
        return {"ok": False, "error": "not_found"}
    if new_name in configs:
        return {"ok": False, "error": "file_exists"}
    (_configs_dir() / old_name).rename(_configs_dir() / new_name)

    from app.models import Server
    from app.services.database import db
    for srv in Server.query.filter_by(active_config=old_name).all():
        srv.active_config = new_name
    db.session.commit()

    return {"ok": True, "name": new_name}


# ── Réparation de la config ──────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Fusionne override dans base : les clés manquantes sont ajoutées depuis base."""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def check_config() -> list[str]:
    """Retourne la liste des problèmes détectés dans la config active."""
    issues = []
    try:
        with open(_active_path(), "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        return [f"Fichier illisible : {e}"]

    default = _default_config()
    for section in ("Server", "Event", "Sessions"):
        if section not in config:
            issues.append(f"Section manquante : {section}")
            continue
        for key in default[section]:
            if key not in config[section]:
                issues.append(f"{section}.{key} manquant")

    for sess_key in ("PracticeSession", "QualifyingSession", "WarmupSession", "RaceSession"):
        if "Sessions" in config and sess_key not in config.get("Sessions", {}):
            issues.append(f"Session manquante : {sess_key}")

    return issues


def repair_config() -> dict:
    """Répare la config active en fusionnant avec les valeurs par défaut."""
    try:
        config = load_config()
    except Exception:
        config = {}
    repaired = _deep_merge(_default_config(), config)
    save_config(repaired)
    issues_after = check_config()
    return {"ok": True, "remaining_issues": issues_after}


# ── Lecture / écriture de la config active ───────────────────────────────────

def load_config() -> dict:
    path = _active_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigJsonError(path.name, e.lineno, e.colno, e.msg) from e
    return _deep_merge(_default_config(), raw)


def default_config() -> dict:
    return _default_config()


def load_config_by_name(name: str) -> dict | None:
    """Charge un fichier de config par son nom de fichier, sans toucher à la session."""
    path = _configs_dir() / name
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return _deep_merge(_default_config(), raw)
    except Exception:
        return None


_MODE_LABELS = {
    "GameModeType_PRACTICE":     "Practice",
    "GameModeType_RACE_WEEKEND": "Race Weekend",
}
_WEATHER_LABELS = {
    "GameModeSelectionWeatherType_CLEAR":    "Dégagé",
    "GameModeSelectionWeatherType_OVERCAST": "Nuageux",
    "GameModeSelectionWeatherType_RAIN":     "Pluie",
}


def _fmt_dur(seconds: int) -> str:
    """Formate une durée en secondes en chaîne lisible (ex: '1h30' ou '45 min')."""
    if not seconds:
        return "—"
    h, m = divmod(seconds // 60, 60)
    return f"{h}h{m:02d}" if h else f"{m} min"


def get_running_server_info(server_id: int = 1) -> dict | None:
    """
    Retourne les infos affichables de la session en cours (circuit, mode, météo,
    véhicules sélectionnés, durée de session…) ou None si le serveur est arrêté.
    Fonctionne sans contexte de session utilisateur.
    """
    from app.services.process_manager import _read_state, is_running
    if not is_running(server_id):
        return None

    state = _read_state(server_id)
    config_name = state.get("config", "")
    if not config_name:
        return None

    cfg = load_config_by_name(config_name)
    if not cfg:
        return None

    ev  = cfg.get("Event", {})
    srv = cfg.get("Server", {})
    ses = cfg.get("Sessions", {})

    track_raw = ev.get("SelectedTrackValue", "")
    parts = track_raw.split("|") if track_raw else []
    circuit = f"{parts[0]} — {parts[1]}" if len(parts) >= 2 else "—"
    track_km = f"{float(parts[3]) / 1000:.2f} km" if len(parts) >= 4 else ""
    track_slug = parts[0].lower().replace(" ", "_") if parts else ""

    mode    = _MODE_LABELS.get(ev.get("SelectedSessionTypeValue", ""), ev.get("SelectedSessionTypeValue", "—"))
    weather = _WEATHER_LABELS.get(ev.get("SelectedWeatherTypeValue", ""), "—")

    cars = ev.get("Cars", [])
    selected = [c.get("display_name") or c.get("name", "") for c in cars
                if c.get("is_selected") or c.get("IsSelected")]

    practice_dur   = _fmt_dur(ses.get("PracticeSession",   {}).get("Length", 0))
    qualifying_dur = _fmt_dur(ses.get("QualifyingSession", {}).get("Length", 0))
    warmup_dur     = _fmt_dur(ses.get("WarmupSession",     {}).get("Length", 0))
    race_dur       = _fmt_dur(ses.get("RaceSession",       {}).get("Length", 0))

    is_race_weekend_val = ev.get("SelectedSessionTypeValue") == "GameModeType_RACE_WEEKEND"

    last_type = state.get("last_session_type", "")
    if is_race_weekend_val:
        if last_type == "qualifying":
            cur_sess_key, cur_sess_label = "WarmupSession",     "Warmup"
        elif last_type == "warmup":
            cur_sess_key, cur_sess_label = "RaceSession",       "Race"
        elif last_type == "race":
            cur_sess_key, cur_sess_label = None,                "Terminé"
        else:
            cur_sess_key, cur_sess_label = "QualifyingSession", "Qualifying"
    else:
        cur_sess_key, cur_sess_label = "PracticeSession", "Practice"

    session_dur_secs = ses.get(cur_sess_key, {}).get("Length", 0) if cur_sess_key else 0
    session_changed_at = state.get("session_changed_at") or state.get("started_at")

    return {
        "server_name":            srv.get("ServerName", "—"),
        "config_file":            config_name,
        "circuit":                circuit,
        "track_name":             parts[0] if parts else "—",
        "track_layout":           parts[1] if len(parts) >= 2 else "",
        "track_km":               track_km,
        "mode":                   mode,
        "weather":                weather,
        "cars":                   selected,
        "car_count":              len(selected),
        "max_players":            srv.get("MaxPlayers", "—"),
        "practice_dur":           practice_dur,
        "qualifying_dur":         qualifying_dur,
        "warmup_dur":             warmup_dur,
        "race_dur":               race_dur,
        "is_race_weekend":        is_race_weekend_val,
        "session_dur_secs":       session_dur_secs,
        "session_changed_at":     session_changed_at,
        "current_session_label":  cur_sess_label,
        "track_slug":             track_slug,
    }


def _car_dict(car: dict, selected: bool, ballast: float, restrictor: float) -> dict:
    """Construit le dict complet d'une voiture (clés camelCase + snake_case pour ACE EVO)."""
    is_mod = bool(car.get("is_mod", False))
    return {
        "is_selected": selected,   "IsSelected": selected,
        "ballast": ballast,        "Ballast": ballast,
        "restrictor": restrictor,  "Restrictor": restrictor,
        "performance_indicator": car["performance_indicator"],
        "PerformanceIndicator":  car["performance_indicator"],
        "property_1": car.get("property_1"), "P1": car.get("property_1"),
        "property_2": car.get("property_2"), "P2": car.get("property_2"),
        "property_3": car.get("property_3"), "P3": car.get("property_3"),
        "is_mod": is_mod, "IsMod": is_mod, "IsModText": car.get("is_mod_text", ""),
        "name": car["name"], "display_name": car["display_name"],
    }


def build_config_from_event(event) -> dict:
    """Construit un dict de config complet à partir d'un Event de la DB."""
    cfg = _default_config()

    cfg["Server"]["ServerName"]     = event.title
    cfg["Server"]["MaxPlayers"]     = event.max_drivers
    cfg["Server"]["DriverPassword"] = event.password or ""

    cfg["Event"]["SelectedSessionTypeValue"] = event.mode
    cfg["Event"]["SelectedWeatherTypeValue"] = event.weather
    cfg["Event"]["SelectedTrackValue"]       = event.circuit

    allowed_names = set(json.loads(event.allowed_cars or "[]"))
    try:
        cars_cfg = json.loads(event.cars_config or "{}")
    except (ValueError, TypeError):
        cars_cfg = {}

    car_list = []
    for car in load_cars():
        selected = (not allowed_names) or (car["name"] in allowed_names)
        overrides = cars_cfg.get(car["name"], {})
        try:
            ballast = float(overrides.get("ballast", 0))
        except (ValueError, TypeError):
            ballast = 0.0
        try:
            restrictor = float(overrides.get("restrictor", 0))
        except (ValueError, TypeError):
            restrictor = 0.0
        car_list.append(_car_dict(car, selected, ballast, restrictor))
    cfg["Event"]["Cars"] = car_list

    sess = cfg["Sessions"]
    sess["PracticeSession"]["Length"]   = (event.practice_minutes   or 60) * 60
    sess["QualifyingSession"]["Length"] = (event.qualifying_minutes or 30) * 60
    sess["WarmupSession"]["Length"]     = (event.warmup_minutes     or 10) * 60
    sess["RaceSession"]["Length"]       = (event.race_minutes       or 60) * 60

    if event.mode == "GameModeType_RACE_WEEKEND":
        sess["QualifyingSession"]["IsVisible"] = True
        sess["WarmupSession"]["IsVisible"]     = True
        sess["RaceSession"]["IsVisible"]       = True

    return cfg


def save_event_config(event, cfg: dict) -> str:
    """Sauvegarde la config d'un événement dans CONFIGS_DIR. Retourne le nom du fichier."""
    slug = re.sub(r"[^\w\-]", "_", event.title)[:40].strip("_")
    name = f"event_{event.id}_{slug}.json"
    _atomic_write_json(_configs_dir() / name, cfg)
    return name


def save_config(data: dict):
    _atomic_write_json(_active_path(), data)


# Champs réservés aux superadmins (ports réseau)
_SUPERADMIN_ONLY_FIELDS = {"TcpPort", "UdpPort", "HttpPort"}

# ── Car category constants (shared by admin, events_admin, leaderboard routes) ──
CAR_PROP_MAPS: dict[str, dict[int, str]] = {
    "property_1": {0: "Road", 1: "Race", 2: "Track"},
    "property_2": {0: "Modern", 1: "Vintage", 2: "YT"},
    "property_3": {0: "ICE", 1: "EV", 2: "Hybrid"},
}
CAR_CATEGORY_ORDER: list[str] = [
    "Road", "Race", "Track", "Modern", "Vintage", "YT", "ICE", "EV", "Hybrid"
]

# Champs numériques avec leurs contraintes (min, max)
_INT_FIELDS: dict[str, tuple[int, int]] = {
    "MaxPlayers": (1, 128),
    "TcpPort":    (1, 65535),
    "UdpPort":    (1, 65535),
    "HttpPort":   (1, 65535),
}

# Mapping : variable d'environnement globale → (clé JSON, valeur par défaut)
_GLOBAL_FIELDS: dict[str, tuple[str, object]] = {
    "SERVER_NAME":            ("ServerName",     "ACE EVO Server"),
    "SERVER_MAX_PLAYERS":     ("MaxPlayers",      8),
    "SERVER_TCP_PORT":        ("TcpPort",         9700),
    "SERVER_UDP_PORT":        ("UdpPort",         9700),
    "SERVER_DRIVER_PASSWORD": ("DriverPassword",  ""),
    "SERVER_ADMIN_PASSWORD":  ("AdminPassword",   ""),
    "SERVER_ENTRY_LIST_PATH": ("EntryListPath",   ""),
    "SERVER_RESULTS_PATH":    ("ResultsPath",     ""),
}


def inject_global_server_settings(config: dict) -> dict:
    """Injecte les paramètres globaux (env vars) dans config['Server']."""
    import os as _os
    srv = config.setdefault("Server", {})
    for env_key, (json_key, default) in _GLOBAL_FIELDS.items():
        val = _os.environ.get(env_key, "").strip()
        if not val:
            continue
        if isinstance(default, int):
            try:
                srv[json_key] = int(val)
            except (ValueError, TypeError):
                pass
        else:
            srv[json_key] = val
    return config


def apply_server_patch(patch: dict, is_superadmin: bool = False) -> dict:
    config = load_config()

    # Ces champs sont désormais globaux (gérés via Paramètres → Config serveur)
    _global_json_keys = {v[0] for v in _GLOBAL_FIELDS.values()}

    server_fields = {
        "HttpPort", "SpectatorPassword",
        "EntryListUrl", "ResultsPostUrl", "SelectedServerTypeValue",
        "SelectedTuningTypeValue",
    }
    event_fields = {
        "SelectedSessionTypeValue", "SelectedWeatherTypeValue",
        "SelectedWeatherBehaviorValue", "SelectedInitialGripValue",
        "SelectedTrackValue", "ShowOnlySelected", "ShowOnlyOfficial",
    }

    for key, value in patch.items():
        if key in _global_json_keys:
            continue  # ignoré : géré globalement via les paramètres
        if key in server_fields:
            if key in _SUPERADMIN_ONLY_FIELDS and not is_superadmin:
                continue
            if key in _INT_FIELDS:
                lo, hi = _INT_FIELDS[key]
                try:
                    value = max(lo, min(hi, int(value)))
                except (ValueError, TypeError):
                    continue
            config["Server"][key] = value
        elif key in event_fields:
            config["Event"][key] = value
        elif key == "Cars":
            patch_map = {c["name"]: c for c in value}
            new_cars = []
            for car in load_cars():
                p = patch_map.get(car["name"], {})
                selected = bool(p.get("IsSelected", False))
                try:
                    ballast = float(p.get("Ballast", 0))
                except (ValueError, TypeError):
                    ballast = 0.0
                try:
                    restrictor = float(p.get("Restrictor", 0))
                except (ValueError, TypeError):
                    restrictor = 0.0
                new_cars.append(_car_dict(car, selected, ballast, restrictor))
            config["Event"]["Cars"] = new_cars
        elif key == "Sessions":
            _session_fields = {
                "forceTimeDuration", "TimeMultiplier", "IsVisible", "Name", "Duration",
                "Length", "Hour", "Minute", "MaxWaitToBox", "OvertimeWaitingNextSession",
                "MinWaitingForPlayers", "MaxWaitingForPlayers",
            }
            for sess_key, sess_val in value.items():
                if sess_key in config["Sessions"] and isinstance(sess_val, dict):
                    filtered = {k: v for k, v in sess_val.items() if k in _session_fields}
                    config["Sessions"][sess_key].update(filtered)

    save_config(config)
    return config


# ── Données de référence ─────────────────────────────────────────────────────

def load_cars() -> list:
    try:
        with open(_cars_path(), "r", encoding="utf-8") as f:
            return json.load(f).get("cars", [])
    except FileNotFoundError:
        log.warning("load_cars: %s introuvable (ACE EVO pas encore installé ?)", _cars_path())
        return []


def load_events(mode: str = "practice") -> list:
    path = _events_path(mode)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("events", [])
    except FileNotFoundError:
        log.warning("load_events: %s introuvable (ACE EVO pas encore installé ?)", path)
        return []


# ── Template config vide ─────────────────────────────────────────────────────

def _default_config() -> dict:
    import os as _os

    def _env_int(key, default):
        val = _os.environ.get(key, "").strip()
        try:
            return int(val) if val else default
        except (ValueError, TypeError):
            return default

    return {
        "Server": {
            "SelectedServerTypeValue": "MultiplayerServerListSessionType_RANKED",
            "SelectedTuningTypeValue": "TuningAllowed",
            "ServerName":     _os.environ.get("SERVER_NAME",            "").strip() or "ACE EVO Server",
            "MaxPlayers":     _env_int("SERVER_MAX_PLAYERS", 8),
            "MaxPlayersLimit": 32,
            "TcpPort":        _env_int("SERVER_TCP_PORT",    9700),
            "UdpPort":        _env_int("SERVER_UDP_PORT",    9700),
            "HttpPort": 8081,
            "IsCycleEnabled": True,
            "DriverPassword": _os.environ.get("SERVER_DRIVER_PASSWORD", ""),
            "SpectatorPassword": "",
            "AdminPassword":  _os.environ.get("SERVER_ADMIN_PASSWORD",  ""),
            "EntryListUrl": "",
            "ResultsPostUrl": _results_post_url(1),
            "EntryListPath":  _os.environ.get("SERVER_ENTRY_LIST_PATH", ""),
            "ResultsPath":    _os.environ.get("SERVER_RESULTS_PATH",    ""),
        },
        "Event": {
            "SelectedSessionTypeValue": "GameModeType_PRACTICE",
            "SelectedWeatherTypeValue": "GameModeSelectionWeatherType_CLEAR",
            "SelectedWeatherBehaviorValue": "GameModeSelectionWeatherBehaviour_STATIC",
            "SelectedInitialGripValue": "InitialGrip_GREEN",
            "SelectedTrackValue": "brands_hatch|GP|GP Time Attack|3916",
            "Cars": [],
            "ShowOnlySelected": False,
            "ShowOnlyOfficial": False,
        },
        "Sessions": {
            "PracticeSession": {
                "forceTimeDuration": True, "TimeMultiplier": 1, "IsVisible": True,
                "Name": "Practice", "Duration": 0, "Length": 300,
                "Hour": 16, "Minute": 0, "MaxWaitToBox": 10,
                "OvertimeWaitingNextSession": 10, "MinWaitingForPlayers": 10, "MaxWaitingForPlayers": 30,
            },
            "QualifyingSession": {
                "forceTimeDuration": True, "TimeMultiplier": 1, "IsVisible": False,
                "Name": "Qualify", "Duration": 0, "Length": 300,
                "Hour": 16, "Minute": 0, "MaxWaitToBox": 10,
                "OvertimeWaitingNextSession": 10, "MinWaitingForPlayers": 10, "MaxWaitingForPlayers": 30,
            },
            "WarmupSession": {
                "forceTimeDuration": True, "TimeMultiplier": 1, "IsVisible": False,
                "Name": "Warmup", "Duration": 0, "Length": 300,
                "Hour": 16, "Minute": 0, "MaxWaitToBox": 10,
                "OvertimeWaitingNextSession": 10, "MinWaitingForPlayers": 10, "MaxWaitingForPlayers": 30,
            },
            "RaceSession": {
                "forceTimeDuration": False, "TimeMultiplier": 1, "IsVisible": False,
                "Name": "Race", "Duration": 0, "Length": 300,
                "Hour": 16, "Minute": 0, "MaxWaitToBox": 10,
                "OvertimeWaitingNextSession": 10, "MinWaitingForPlayers": 10, "MaxWaitingForPlayers": 30,
            },
        },
    }


# ── Sauvegarde du formulaire "par-serveur" de /settings ────────────────────────

def save_server_form(current_srv, form) -> list[dict]:
    """Applique au Server les champs du formulaire par-serveur (nom, ports, webhooks Discord)
    et commit en DB. Retourne une liste d'erreurs de port sous forme structurée
    (le libellé traduit est construit par l'appelant, côté route) :
      {"field": "tcp"|"http", "type": "invalid_range"|"conflict", "port": int, "name": str|None}
    """
    from app.services.database import db
    from app.models import Server

    name = form.get("srv_name", "").strip()
    tcp  = form.get("srv_tcp_port", "").strip()
    http = form.get("srv_http_port", "").strip()
    errors: list[dict] = []

    if name:
        current_srv.name = name

    if tcp and tcp.isdigit():
        new_tcp = int(tcp)
        if not (1024 <= new_tcp <= 65535):
            errors.append({"field": "tcp", "type": "invalid_range", "port": new_tcp, "name": None})
        else:
            conflict = Server.query.filter(Server.id != current_srv.id, db.or_(
                Server.tcp_port == new_tcp, Server.udp_port == new_tcp
            )).first()
            if conflict:
                errors.append({"field": "tcp", "type": "conflict", "port": new_tcp, "name": conflict.name})
            else:
                current_srv.tcp_port = new_tcp
                current_srv.udp_port = new_tcp

    if http and http.isdigit():
        new_http = int(http)
        if not (1024 <= new_http <= 65535):
            errors.append({"field": "http", "type": "invalid_range", "port": new_http, "name": None})
        else:
            conflict = Server.query.filter(Server.id != current_srv.id, Server.http_port == new_http).first()
            if conflict:
                errors.append({"field": "http", "type": "conflict", "port": new_http, "name": conflict.name})
            else:
                current_srv.http_port = new_http

    current_srv.discord_webhook_main   = form.get("srv_discord_main",   "").strip()
    current_srv.discord_webhook_pilots = form.get("srv_discord_pilots", "").strip()
    current_srv.discord_webhook_race   = form.get("srv_discord_race",   "").strip()
    db.session.commit()
    return errors
