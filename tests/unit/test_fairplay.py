"""Classement fair-play — résultats déjà décodés, fabriqués à la main (données synthétiques)."""
from app.services import fairplay


def _drv(pid, nick, laps, car=0, wall=0, obj=0, damage=0, impact=0.0, pens=0, severe=0):
    return {"player_id": pid, "nickname": nick, "laps_count": laps,
            "incident_stats": {"car": car, "wall": wall, "object": obj, "damage": damage, "max_impact_kmh": impact},
            "penalty_count": pens, "severe_penalty_count": severe}


def _sessions():
    return [
        {"standings": [_drv("1", "Alice", 30, car=3, wall=3), _drv("2", "Bob", 25, car=1),
                       _drv("", "BOT", 40, car=9)]},
        {"standings": [_drv("1", "Alice", 20, wall=2, impact=77.0, pens=2, severe=1),
                       _drv("3", "Chloé", 5, car=5)]},
    ]


def test_cumul_par_pilote_et_ignore_les_ia():
    by_id = {d["player_id"]: d for d in fairplay.aggregate(_sessions())}
    assert set(by_id) == {"1", "2", "3"}                       # le pilote sans SteamID est ignoré
    a = by_id["1"]
    assert (a["sessions"], a["laps"], a["contacts"], a["walls"], a["incidents"]) == (2, 50, 3, 5, 8)
    assert a["per_lap"] == round(8 / 50, 3) and a["max_impact_kmh"] == 77.0
    assert (a["penalties"], a["severe_penalties"]) == (2, 1)


def test_classement_minimum_de_tours_et_ordre():
    ranking = fairplay.rank(fairplay.aggregate(_sessions()))
    assert [d["nickname"] for d in ranking] == ["Bob", "Alice", "Chloé"]    # Bob 0,04/tour < Alice 0,16 ; Chloé non classée
    assert [d["ranked"] for d in ranking] == [True, True, False]


def test_sessions_sans_enregistrement_d_incidents_ne_comptent_pas():
    old = {"incidents_reported": False, "standings": [_drv("1", "Alice", 500)]}
    by_id = {d["player_id"]: d for d in fairplay.aggregate(_sessions() + [old])}
    assert by_id["1"]["laps"] == 50 and by_id["1"]["sessions"] == 2


def test_aucune_donnee():
    assert fairplay.rank(fairplay.aggregate([])) == []
    assert fairplay.rank(fairplay.aggregate([{"standings": []}, {}])) == []
