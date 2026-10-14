"""Données de test synthétiques partagées (résultat de session à deux pilotes)."""


def _guid(n):
    return {"a": str(n), "b": str(n * 7)}


def _session(collisions=None, penalties=None, race=True):
    """Deux pilotes (A, B), une voiture chacun, deux tours chacun."""
    return {
        "session_type": "Race" if race else "Practice",
        "track_name": "Circuit Test", "track_layout_name": "GP", "server_name": "Test",
        "drivers": [
            {"guid": _guid(1), "nickname": "Alice", "first_name": "A", "last_name": "A", "player_id": "1"},
            {"guid": _guid(2), "nickname": "Bob", "first_name": "B", "last_name": "B", "player_id": "2"},
        ],
        "cars": [
            {"car_id": _guid(11), "model_displayname": "Voiture 1", "race_number": 7},
            {"car_id": _guid(12), "model_displayname": "Voiture 2", "race_number": 9},
        ],
        "car_standings": [{"car_id": _guid(11), "total_km": 5.0}, {"car_id": _guid(12), "total_km": 5.0}],
        "driver_standings": [_guid(1), _guid(2)],
        "time_standings": [180000, 181000],
        "laps": [
            {"driver_key": _guid(1), "car_key": _guid(11), "time": 90000, "split": [30000, 30000, 30000], "flags": 2},
            {"driver_key": _guid(1), "car_key": _guid(11), "time": 90000, "split": [30000, 30000, 30000], "flags": 2},
            {"driver_key": _guid(2), "car_key": _guid(12), "time": 90500, "split": [30000, 30000, 30500], "flags": 2},
            {"driver_key": _guid(2), "car_key": _guid(12), "time": 90500, "split": [30000, 30000, 30500], "flags": 2},
        ],
        "collisions": collisions or [],
        "penalty_collection": penalties if penalties is not None else {},
    }


def _hit(car, ts, collider="Car", impact=12.0, damage=True, x=100.0):
    return {"server_timestamp": ts, "car_id": _guid(car), "collider": collider, "has_damage": damage,
            "relative_impact_kmh": impact, "world_pos": {"x": x, "y": 0.0, "z": 0.0}}
