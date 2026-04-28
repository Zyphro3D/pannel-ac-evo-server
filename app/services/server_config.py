import json
import shutil
from pathlib import Path
from flask import current_app, session


# ── Helpers dossier ──────────────────────────────────────────────────────────

def _configs_dir() -> Path:
    return Path(current_app.config["CONFIGS_DIR"])

def _cars_path() -> Path:
    return Path(current_app.config["CARS_JSON_PATH"])

def _events_path(mode: str = "practice") -> Path:
    key = "EVENTS_PRACTICE_JSON_PATH" if mode == "practice" else "EVENTS_RACE_JSON_PATH"
    return Path(current_app.config[key])


# ── Gestion des fichiers de config ───────────────────────────────────────────

def list_configs() -> list[str]:
    """Retourne les noms de tous les fichiers .json dans CONFIGS_DIR."""
    d = _configs_dir()
    return sorted(p.name for p in d.glob("*.json") if p.is_file())


def get_active_config_name() -> str:
    """Config active stockée en session ; fallback sur le premier fichier trouvé."""
    configs = list_configs()
    if not configs:
        return ""
    name = session.get("active_config")
    if name and name in configs:
        return name
    # Premier fichier par défaut
    session["active_config"] = configs[0]
    return configs[0]


def set_active_config(name: str) -> bool:
    configs = list_configs()
    if name not in configs:
        return False
    session["active_config"] = name
    return True


def _active_path() -> Path:
    return _configs_dir() / get_active_config_name()


def create_config(name: str, copy_from: str | None = None) -> dict:
    """Crée un nouveau fichier de config. Copie copy_from si fourni, sinon template vide."""
    import re
    if not name.endswith(".json"):
        name += ".json"
    # Interdit tout caractère hors alphanum, tiret, underscore, point
    if not re.match(r'^[\w\-. ]+\.json$', name) or '..' in name or '/' in name or '\\' in name:
        return {"ok": False, "error": "invalid_name"}

    dest = _configs_dir() / name
    if dest.exists():
        return {"ok": False, "error": "file_exists"}

    if copy_from:
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

    # Si c'était la config active, basculer sur une autre
    if session.get("active_config") == name:
        remaining = [c for c in configs if c != name]
        session["active_config"] = remaining[0]

    return {"ok": True}


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
        config = load_config()
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
    with open(_active_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def load_config_by_name(name: str) -> dict | None:
    """Charge un fichier de config par son nom de fichier, sans toucher à la session."""
    path = _configs_dir() / name
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
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


def get_running_server_info() -> dict | None:
    """
    Retourne les infos affichables de la session en cours (circuit, mode, météo,
    véhicules sélectionnés, durée de session…) ou None si le serveur est arrêté.
    Fonctionne sans contexte de session utilisateur.
    """
    from app.services.process_manager import _read_state, is_running
    if not is_running():
        return None

    state = _read_state()
    config_name = state.get("config", "")
    if not config_name:
        return None

    cfg = load_config_by_name(config_name)
    if not cfg:
        return None

    ev  = cfg.get("Event", {})
    srv = cfg.get("Server", {})
    ses = cfg.get("Sessions", {})

    # Circuit : "track|layout|event_name|length"
    track_raw = ev.get("SelectedTrackValue", "")
    parts = track_raw.split("|") if track_raw else []
    circuit = f"{parts[0]} — {parts[1]}" if len(parts) >= 2 else "—"
    track_km = f"{float(parts[3]) / 1000:.2f} km" if len(parts) >= 4 else ""

    mode    = _MODE_LABELS.get(ev.get("SelectedSessionTypeValue", ""), ev.get("SelectedSessionTypeValue", "—"))
    weather = _WEATHER_LABELS.get(ev.get("SelectedWeatherTypeValue", ""), "—")

    # Véhicules sélectionnés
    cars = ev.get("Cars", [])
    selected = [c.get("display_name") or c.get("name", "") for c in cars
                if c.get("is_selected") or c.get("IsSelected")]

    # Durée principale (Practice) en secondes → h/min
    def _fmt_dur(seconds: int) -> str:
        if not seconds:
            return "—"
        h, m = divmod(seconds // 60, 60)
        return f"{h}h{m:02d}" if h else f"{m} min"

    practice_dur  = _fmt_dur(ses.get("PracticeSession", {}).get("Length", 0))
    qualifying_dur = _fmt_dur(ses.get("QualifyingSession", {}).get("Length", 0))
    warmup_dur    = _fmt_dur(ses.get("WarmupSession", {}).get("Length", 0))
    race_dur      = _fmt_dur(ses.get("RaceSession", {}).get("Length", 0))

    return {
        "server_name":    srv.get("ServerName", "—"),
        "config_file":    config_name,
        "circuit":        circuit,
        "track_km":       track_km,
        "mode":           mode,
        "weather":        weather,
        "cars":           selected,
        "car_count":      len(selected),
        "max_players":    srv.get("MaxPlayers", "—"),
        "practice_dur":   practice_dur,
        "qualifying_dur": qualifying_dur,
        "warmup_dur":     warmup_dur,
        "race_dur":       race_dur,
        "is_race_weekend": ev.get("SelectedSessionTypeValue") == "GameModeType_RACE_WEEKEND",
    }


def build_config_from_event(event) -> dict:
    """Construit un dict de config complet à partir d'un Event de la DB."""
    import json as _json
    import re

    cfg = _default_config()

    # Server
    cfg["Server"]["ServerName"]     = event.title
    cfg["Server"]["MaxPlayers"]     = event.max_drivers
    cfg["Server"]["DriverPassword"] = event.password or ""

    # Event
    cfg["Event"]["SelectedSessionTypeValue"]    = event.mode
    cfg["Event"]["SelectedWeatherTypeValue"]    = event.weather
    cfg["Event"]["SelectedTrackValue"]          = event.circuit

    # Cars — marquer comme sélectionnées celles dans allowed_cars (ou toutes si liste vide)
    allowed_names = set(_json.loads(event.allowed_cars or "[]"))
    cars_cfg = {}
    try:
        cars_cfg = _json.loads(event.cars_config or "{}")
    except (ValueError, TypeError):
        pass
    car_list = []
    for car in load_cars():
        selected = (not allowed_names) or (car["name"] in allowed_names)
        car_overrides = cars_cfg.get(car["name"], {})
        ballast    = float(car_overrides.get("ballast", 0))
        restrictor = float(car_overrides.get("restrictor", 0))
        car_list.append({
            "is_selected": selected,   "IsSelected": selected,
            "ballast": ballast,        "Ballast": ballast,
            "restrictor": restrictor,  "Restrictor": restrictor,
            "performance_indicator": car["performance_indicator"],
            "PerformanceIndicator":  car["performance_indicator"],
            "property_1": car.get("property_1"), "P1": car.get("property_1"),
            "property_2": car.get("property_2"), "P2": car.get("property_2"),
            "property_3": car.get("property_3"), "P3": car.get("property_3"),
            "name": car["name"], "display_name": car["display_name"],
        })
    cfg["Event"]["Cars"] = car_list

    # Sessions (minutes → secondes)
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
    import re
    slug = re.sub(r"[^\w\-]", "_", event.title)[:40].strip("_")
    name = f"event_{event.id}_{slug}.json"
    path = _configs_dir() / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return name


def save_config(data: dict):
    with open(_active_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


_SUPERADMIN_ONLY_FIELDS = {"TcpPort", "UdpPort", "HttpPort"}


def apply_server_patch(patch: dict, is_superadmin: bool = False) -> dict:
    config = load_config()

    server_fields = {
        "ServerName", "MaxPlayers", "TcpPort", "UdpPort", "HttpPort",
        "IsCycleEnabled", "DriverPassword", "SpectatorPassword",
        "AdminPassword", "EntryListPath", "ResultsPath",
        "EntryListUrl", "ResultsPostUrl", "SelectedServerTypeValue",
    }
    event_fields = {
        "SelectedSessionTypeValue", "SelectedWeatherTypeValue",
        "SelectedWeatherBehaviorValue", "SelectedInitialGripValue",
        "SelectedTrackValue", "ShowOnlySelected",
    }

    for key, value in patch.items():
        if key in server_fields:
            if key in _SUPERADMIN_ONLY_FIELDS and not is_superadmin:
                continue
            config["Server"][key] = value
        elif key in event_fields:
            config["Event"][key] = value
        elif key == "Cars":
            # Reconstruire depuis cars.json pour avoir tous les champs complets
            patch_map = {c["name"]: c for c in value}
            all_cars = load_cars()
            new_cars = []
            for car in all_cars:
                p = patch_map.get(car["name"], {})
                selected = bool(p.get("IsSelected", False))
                ballast = float(p.get("Ballast", 0))
                restrictor = float(p.get("Restrictor", 0))
                new_cars.append({
                    "is_selected": selected,
                    "ballast": ballast,
                    "restrictor": restrictor,
                    "performance_indicator": car["performance_indicator"],
                    "property_1": car["property_1"],
                    "property_2": car["property_2"],
                    "property_3": car["property_3"],
                    "name": car["name"],
                    "display_name": car["display_name"],
                    "IsSelected": selected,
                    "Ballast": ballast,
                    "Restrictor": restrictor,
                    "PerformanceIndicator": car["performance_indicator"],
                    "P1": car["property_1"],
                    "P2": car["property_2"],
                    "P3": car["property_3"],
                })
            config["Event"]["Cars"] = new_cars
        elif key == "Sessions":
            for sess_key, sess_val in value.items():
                if sess_key in config["Sessions"]:
                    config["Sessions"][sess_key].update(sess_val)

    save_config(config)
    return config


# ── Données de référence ─────────────────────────────────────────────────────

def load_cars() -> list:
    with open(_cars_path(), "r", encoding="utf-8") as f:
        return json.load(f).get("cars", [])


def load_events(mode: str = "practice") -> list:
    with open(_events_path(mode), "r", encoding="utf-8") as f:
        return json.load(f).get("events", [])


# ── Template config vide ─────────────────────────────────────────────────────

def _default_config() -> dict:
    return {
        "Server": {
            "SelectedServerTypeValue": "MultiplayerServerListSessionType_RANKED",
            "ServerName": "New Server",
            "MaxPlayers": 8,
            "MaxPlayersLimit": 32,
            "TcpPort": 9700,
            "UdpPort": 9700,
            "HttpPort": 8080,
            "IsCycleEnabled": True,
            "DriverPassword": "",
            "SpectatorPassword": "",
            "AdminPassword": "",
            "EntryListUrl": "",
            "ResultsPostUrl": "",
            "EntryListPath": "",
            "ResultsPath": "",
        },
        "Event": {
            "SelectedSessionTypeValue": "GameModeType_PRACTICE",
            "SelectedWeatherTypeValue": "GameModeSelectionWeatherType_CLEAR",
            "SelectedWeatherBehaviorValue": "GameModeSelectionWeatherBehaviour_STATIC",
            "SelectedInitialGripValue": "InitialGrip_GREEN",
            "SelectedTrackValue": "",
            "Cars": [],
            "ShowOnlySelected": False,
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
