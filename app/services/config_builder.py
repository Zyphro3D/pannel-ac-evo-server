"""
Build the exact -serverconfig and -seasondefinition args from server_launcher.json.
Structures reverse-engineered by decoding working args from ServerLauncher.exe.
"""
import logging

from app.services.encoder import encode_serverconfig, encode_seasondefinition

log = logging.getLogger(__name__)


def _tod(sess: dict) -> dict:
    return {
        "year": 2024, "month": 8, "day": 15,
        "hour": sess.get("Hour", 16),
        "minute": sess.get("Minute", 0),
        "second": 0,
        "time_multiplier": sess.get("TimeMultiplier", 1),
    }


# Types de session pour lesquels le serveur de jeu attend la configuration complète (practice +
# qualification + warmup + course), comme pour un week-end de course. Vérifié sur banc d'essai
# (serveur 0.9.x) : course instantanée, tour lancé, rallye, A vers B et test drive. Seule la course
# instantanée utilise ces durées/heures ; les quatre autres ont une durée et une heure fixées par le
# jeu (1 h, 1 tour/3 min 15, 10 min, 10 min) qu'aucun réglage ne modifie.
SINGLE_SESSION_MODES = {
    "GameModeType_INSTANT_RACE", "GameModeType_HOTLAP", "GameModeType_RALLY",
    "GameModeType_A_TO_B", "GameModeType_TEST_DRIVE",
}
FULL_CONFIG_TYPES = {"GameModeType_RACE_WEEKEND"} | SINGLE_SESSION_MODES
# Types contenant une session « course » (seule à recevoir tours, arrêt obligatoire et sanctions perso)
RACE_TYPES = {"GameModeType_RACE_WEEKEND", "GameModeType_INSTANT_RACE"}


def _clamp(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def race_rules(race: dict) -> dict:
    """Réglages de course optionnels (tous désactivés par défaut), lus dans RaceSession.

    Chacun a été vérifié sur un vrai serveur de jeu en lisant la session qu'il construit :
      - course au nombre de tours : ``race_duration`` = tours + ``race_duration_type`` LAPS ;
      - arrêt obligatoire : fenêtre de ``pit_window`` secondes centrée au milieu de la course ;
      - pénalités personnalisées : roues dehors pour une coupure, avertissements avant sanction,
        durée de la sanction.
    Retourne les clés à ajouter à ``game_config`` (vide si rien n'est activé)."""
    out: dict = {}
    by_laps = bool(race.get("RaceByLaps")) and _clamp(race.get("Laps"), 0, 999, 0) > 0
    if by_laps:
        out["race_duration"] = _clamp(race.get("Laps"), 1, 999, 1)
        out["race_duration_type"] = "GameModeSelectionDuration_LAPS"
    # Arrêt obligatoire : réservé aux courses au temps. Vérifié : en course au tour le serveur
    # calcule la fenêtre à partir du nombre de tours lu comme des secondes (ex. 8 tours : de
    # −146 s à +154 s), donc une fenêtre fausse dès le départ.
    if race.get("MandatoryPitStop") and not by_laps:
        out["mandatory_pit_stop"] = True
        out["requires_tyre_change"] = bool(race.get("PitStopTyreChange"))
        out["requires_refuelling"] = bool(race.get("PitStopRefuel"))
        out["pit_window"] = _clamp(race.get("PitWindow"), 10, 7200, 600)
    return out


def custom_penalties(race: dict) -> dict:
    """Sanctions personnalisées (options de RaceSession, désactivées par défaut)."""
    if not race.get("CustomPenalties"):
        return {}
    return {
        "enable_custom_penalities": True,   # (sic) orthographe du serveur de jeu
        "car_cut_tyres_out":        _clamp(race.get("CarCutTyresOut"), 1, 4, 3),
        "warning_trigger_countdown": _clamp(race.get("WarningCountdown"), 1, 20, 3),
        "time_penalty_ms":          _clamp(race.get("TimePenaltySeconds"), 1, 120, 5) * 1000,
    }


def build_launch_args(config: dict,
                      tcp_listener: int | None = None,
                      udp_listener: int | None = None,
                      server_name:  str | None = None) -> tuple[str, str]:
    """Build launch args from config.
    tcp_listener / udp_listener override the external port announced to Kunos
    while the internal bind port stays at TcpPort/UdpPort (always 9700 in Docker).
    server_name overrides the in-game server name for multi-server setups.
    """
    server   = config["Server"]
    event    = config["Event"]
    sessions = config["Sessions"]

    # ── serverconfig ────────────────────────────────────────────────────────
    selected_cars = [
        c for c in event.get("Cars", [])
        if c.get("IsSelected") or c.get("is_selected")
    ]

    # Contrôle d'accès (option) : fichier d'engagés généré par le panel, sauf si l'admin a fixé
    # lui-même un chemin (SERVER_ENTRY_LIST_PATH), qui reste prioritaire.
    entry_list_path = server.get("EntryListPath", "")
    try:
        from app.services import access_control
        if access_control.enabled() and not entry_list_path:
            entry_list_path = access_control.prepare_file() or entry_list_path
    except Exception as exc:          # ne jamais empêcher un démarrage de serveur
        log.warning("contrôle d'accès ignoré : %s", exc)

    server_dict = {
        "server_tcp_listener_port": tcp_listener if tcp_listener else server["TcpPort"],
        "server_udp_listener_port": udp_listener if udp_listener else server["UdpPort"],
        "server_tcp_internal_port": server["TcpPort"],
        "server_udp_internal_port": server["UdpPort"],
        "server_http_port": server.get("HttpPort", 8081),
        "server_name": server_name if server_name else server["ServerName"],
        "max_players": server["MaxPlayers"],
        "cycle": server.get("IsCycleEnabled", True),
        "allowed_cars_list_full": [
            {
                "car_name": c["name"],
                "ballast": int(c.get("Ballast", c.get("ballast", 0))),
                "restrictor": float(c.get("Restrictor", c.get("restrictor", 0.0))),
            }
            for c in selected_cars
        ],
        "driver_password": server.get("DriverPassword", ""),
        "spectator_password": server.get("SpectatorPassword", ""),
        "admin_password": server.get("AdminPassword", ""),
        "type": server.get("SelectedServerTypeValue", "MultiplayerServerListSessionType_RANKED"),
        "tuning_type": server.get("SelectedTuningTypeValue", "TuningAllowed"),
        "entry_list_path": entry_list_path,
        "results_path": server.get("ResultsPath", ""),
        "results_post_url": server.get("ResultsPostUrl", ""),
    }

    # ── seasondefinition ─────────────────────────────────────────────────────
    track_value  = event.get("SelectedTrackValue", "")
    parts        = track_value.split("|")
    track        = parts[0] if len(parts) > 0 else ""
    layout       = parts[1] if len(parts) > 1 else ""
    event_name   = parts[2] if len(parts) > 2 else ""
    track_length = parts[3] if len(parts) > 3 else "0"

    game_type = event.get("SelectedSessionTypeValue", "GameModeType_PRACTICE")

    if game_type in FULL_CONFIG_TYPES:
        practice = sessions.get("PracticeSession", {})
        qualify  = sessions.get("QualifyingSession", {})
        warmup   = sessions.get("WarmupSession", {})
        race     = sessions.get("RaceSession", {})
        game_config = {
            "practice_duration":                      practice.get("Length", 300),
            "practice_time_of_day":                   _tod(practice),
            "practice_overtime_waiting_next_session":  practice.get("OvertimeWaitingNextSession", 10),
            "practice_max_wait_to_box":               practice.get("MaxWaitToBox", 10),
            "qualify_duration":                       qualify.get("Length", 300),
            "qualify_time_of_day":                    _tod(qualify),
            "qualify_overtime_waiting_next_session":   qualify.get("OvertimeWaitingNextSession", 10),
            "qualify_max_wait_to_box":                qualify.get("MaxWaitToBox", 10),
            "warmup_duration":                        warmup.get("Length", 300),
            "warmup_time_of_day":                     _tod(warmup),
            "warmup_overtime_waiting_next_session":    warmup.get("OvertimeWaitingNextSession", 10),
            "warmup_max_wait_to_box":                 warmup.get("MaxWaitToBox", 10),
            "race_duration":                          race.get("Length", 300),
            "race_duration_type":                     "GameModeSelectionDuration_TIME",
            "race_time_of_day":                       _tod(race),
            "race_overtime_waiting_next_session":      race.get("OvertimeWaitingNextSession", 10),
            "race_max_wait_to_box":                   race.get("MaxWaitToBox", 10),
            "min_waiting_for_players":                race.get("MinWaitingForPlayers", 10),
            "max_waiting_for_players":                race.get("MaxWaitingForPlayers", 30),
        }
        if game_type in RACE_TYPES:
            # Ces options ne concernent que la session « course » (vérifié : qualification, libre,
            # warmup et les modes à durée fixe gardent les règles d'usine du jeu)
            game_config.update(race_rules(race))
            game_config.update(custom_penalties(race))
    else:
        # Practice ou Qualify : session unique
        _prefix_map = {
            "GameModeType_PRACTICE": ("practice", "PracticeSession"),
            "GameModeType_QUALIFY":  ("qualify",  "QualifyingSession"),
        }
        prefix, sess_key = _prefix_map.get(game_type, ("practice", "PracticeSession"))
        sess = sessions.get(sess_key, {})
        game_config = {
            f"{prefix}_duration":                     sess.get("Length", 300),
            f"{prefix}_time_of_day":                  _tod(sess),
            f"{prefix}_overtime_waiting_next_session": sess.get("OvertimeWaitingNextSession", 10),
            f"{prefix}_max_wait_to_box":              sess.get("MaxWaitToBox", 10),
        }

    season_dict = {
        "game_type":        game_type,
        "event": {
            "track":        track,
            "layout":       layout,
            "event_name":   event_name,
            "track_length": str(track_length),
        },
        "export_json":      False,
        "game_config":      game_config,
        "weather_type":     event.get("SelectedWeatherTypeValue", "GameModeSelectionWeatherType_CLEAR"),
        "weather_behaviour": event.get("SelectedWeatherBehaviorValue", "GameModeSelectionWeatherBehaviour_STATIC"),
        "initial_grip":     event.get("SelectedInitialGripValue", "InitialGrip_GREEN"),
    }

    sc_b64 = encode_serverconfig(server_dict)
    sd_b64 = encode_seasondefinition(season_dict)
    return sc_b64, sd_b64
