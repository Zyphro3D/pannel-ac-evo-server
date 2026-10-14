import os
from datetime import datetime

from app.services import rating


def race(*drivers, laps=10):
    """drivers : (steamid, nom, tours) dans l'ordre d'arrivée."""
    return {"is_race": True, "standings": [
        {"player_id": pid, "nickname": nom, "laps_count": l, "position": i + 1} for i, (pid, nom, l) in enumerate(drivers)]}


def run(*parsed):
    return rating.compute([(i + 1, datetime(2026, 10, 1 + i), p) for i, p in enumerate(parsed)])


def test_winner_gains_loser_loses_and_total_is_conserved():
    res = run(race(("A", "Alice", 10), ("B", "Bob", 10), ("C", "Carl", 10), ("D", "Dana", 10)))
    assert res["A"]["rating"] > rating.START > res["D"]["rating"]
    assert abs(sum(p["rating"] for p in res.values()) - 4 * rating.START) < 1e-6      # somme nulle
    assert res["A"]["wins"] == 1 and res["B"]["podiums"] == 1 and res["D"]["podiums"] == 0


def test_beating_a_strong_driver_gains_more_than_beating_a_weak_one():
    # B s'est construit un bon niveau ; A le bat ensuite, puis C (faible) bat D (faible)
    warm = [race(("B", "B", 10), ("X", "X", 10), ("Y", "Y", 10), ("Z", "Z", 10)) for _ in range(6)]
    res = run(*warm, race(("A", "A", 10), ("B", "B", 10), ("Y", "Y", 10), ("Z", "Z", 10)))
    gain_vs_strong = res["A"]["last_delta"]
    res2 = run(*warm, race(("Y", "Y", 10), ("A", "A", 10), ("B", "B", 10), ("Z", "Z", 10)))
    assert gain_vs_strong > 0 and res["A"]["rating"] > res2["A"]["rating"]


def test_unclassified_drivers_lose_and_do_not_compare_together():
    res = run(race(("A", "A", 10), ("B", "B", 10), ("C", "C", 2), ("D", "D", 1)))
    assert res["C"]["rating"] < rating.START and res["D"]["rating"] < rating.START
    # C et D ne se sont pas comparés : même perte contre A et B uniquement
    assert abs(res["C"]["last_delta"] - res["D"]["last_delta"]) < 0.5


def test_small_fields_move_less_and_tiny_races_are_ignored():
    duo = run(race(("A", "A", 10), ("B", "B", 10)))
    quad = run(race(("A", "A", 10), ("B", "B", 10), ("C", "C", 10), ("D", "D", 10)))
    assert duo["A"]["last_delta"] < quad["A"]["last_delta"]
    assert run(race(("A", "A", 2), ("B", "B", 2))) == {}                     # leader < 3 tours
    assert run({"is_race": False, "standings": race(("A", "A", 10), ("B", "B", 10))["standings"]}) == {}
    assert run(race(("A", "A", 10), ("", "IA", 10))) == {}                    # un seul humain identifié


def test_provisional_flag_and_ranking_order():
    res = run(*[race(("A", "A", 10), ("B", "B", 10), ("C", "C", 10), ("D", "D", 10)) for _ in range(6)],
              race(("N", "Nouveau", 10), ("D", "D", 10), ("C", "C", 10), ("B", "B", 10)))
    ranking = rating.rank(res)
    names = [p["nickname"] for p in ranking]
    assert names[-1] == "Nouveau" and ranking[-1]["provisional"]              # provisoires en bas de tableau
    assert not ranking[0]["provisional"]


def test_blocking_threshold_is_off_by_default_and_spares_provisional(monkeypatch):
    res = run(*[race(("A", "A", 10), ("B", "B", 10), ("C", "C", 10), ("D", "D", 10)) for _ in range(6)])
    ranking = rating.rank(res)
    monkeypatch.delenv("RATING_ENFORCE", raising=False)
    monkeypatch.setenv("RATING_MIN_TO_JOIN", "1450")
    assert rating.blocked_ids(ranking) == []                                   # pas activé
    monkeypatch.setenv("RATING_ENFORCE", "true")
    blocked = rating.blocked_ids(ranking)
    assert "D" in blocked and "A" not in blocked
    monkeypatch.setenv("RATING_MIN_RACES", "50")                               # trop peu de courses : jamais refusé
    assert rating.blocked_ids(ranking) == []
