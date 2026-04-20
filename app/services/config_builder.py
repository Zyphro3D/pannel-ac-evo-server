"""
Build the exact -serverconfig and -seasondefinition args from server_launcher.json.
Structures reverse-engineered by decoding working args from ServerLauncher.exe.
"""
from app.services.encoder import encode_serverconfig, encode_seasondefinition


def _tod(sess: dict) -> dict:
    return {
        "year": 2024, "month": 8, "day": 15,
        "hour": sess.get("Hour", 16),
        "minute": sess.get("Minute", 0),
        "second": 0,
        "time_multiplier": sess.get("TimeMultiplier", 1),
    }


def build_launch_args(config: dict) -> tuple[str, str]:
    server   = config["Server"]
    event    = config["Event"]
    sessions = config["Sessions"]

    # ── serverconfig ────────────────────────────────────────────────────────
    selected_cars = [
        c for c in event.get("Cars", [])
        if c.get("IsSelected") or c.get("is_selected")
    ]

    server_dict = {
        "server_tcp_listener_port": server["TcpPort"],
        "server_udp_listener_port": server["UdpPort"],
        "server_tcp_internal_port": server["TcpPort"],
        "server_udp_internal_port": server["UdpPort"],
        "server_http_port": server.get("HttpPort", 8080),
        "server_name": server["ServerName"],
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
        "entry_list_path": server.get("EntryListPath", ""),
        "results_path": server.get("ResultsPath", ""),
    }

    # ── seasondefinition ─────────────────────────────────────────────────────
    track_value  = event.get("SelectedTrackValue", "")
    parts        = track_value.split("|")
    track        = parts[0] if len(parts) > 0 else ""
    layout       = parts[1] if len(parts) > 1 else ""
    event_name   = parts[2] if len(parts) > 2 else ""
    track_length = parts[3] if len(parts) > 3 else "0"

    game_type = event.get("SelectedSessionTypeValue", "GameModeType_PRACTICE")

    if game_type == "GameModeType_RACE_WEEKEND":
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
