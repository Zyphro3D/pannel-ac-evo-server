import pytest

from app.services import championship as ch


def parsed(*drivers, laps=10):
    """(steamid, nom, tours, tours rapide ms, grille) dans l'ordre d'arrivée."""
    return {"is_race": True, "standings": [
        {"player_id": pid, "nickname": nom, "laps_count": l, "position": i + 1, "fastest_lap_ms": fl,
         "starting_position": g} for i, (pid, nom, l, fl, g) in enumerate(drivers)]}


PTS = [25, 18, 15, 12]


def test_points_follow_human_ranking_and_ai_are_ignored():
    p = {"is_race": True, "standings": [
        {"player_id": "", "nickname": "IA", "laps_count": 10, "position": 1},
        {"player_id": "A", "nickname": "Alice", "laps_count": 10, "position": 2},
        {"player_id": "B", "nickname": "Bob", "laps_count": 10, "position": 3}]}
    sc = ch.round_scores(p, PTS, 0, 0)
    assert sc["A"]["pts"] == 25 and sc["B"]["pts"] == 18 and "" not in sc


def test_dnf_scores_zero_and_does_not_take_a_rank():
    sc = ch.round_scores(parsed(("A", "A", 10, 0, 0), ("B", "B", 3, 0, 0), ("C", "C", 10, 0, 0)), PTS, 0, 0)
    assert sc["B"]["dnf"] and sc["B"]["pts"] == 0 and sc["C"]["pos"] == 2 and sc["C"]["pts"] == 18


def test_bonuses_only_for_classified_drivers():
    sc = ch.round_scores(parsed(("A", "A", 10, 90000, 2), ("B", "B", 10, 88000, 1), ("C", "C", 2, 80000, 3)),
                         PTS, fastest_bonus=1, pole_bonus=2)
    assert sc["B"]["fastest"] and sc["B"]["pts"] == 18 + 1 + 2          # meilleur tour des classés (pas C, non classé)
    assert sc["B"]["pole"] and not sc["C"]["fastest"]


def rounds_of(*races, **kw):
    return [{"label": f"M{i + 1}", "scores": ch.round_scores(r, PTS, kw.get("fl", 0), kw.get("pole", 0))}
            for i, r in enumerate(races)]


def test_totals_drop_worst_and_absence_counts_as_zero():
    r1 = parsed(("A", "A", 10, 0, 0), ("B", "B", 10, 0, 0))
    r2 = parsed(("B", "B", 10, 0, 0), ("A", "A", 10, 0, 0))
    r3 = parsed(("B", "B", 10, 0, 0),)                                      # A absent à la manche 3
    table = ch.standings(rounds_of(r1, r2, r3), drop_worst=1)
    by = {p["player_id"]: p for p in table}
    assert by["B"]["total"] == 18 + 25 + 25 - 18 and by["A"]["total"] == 25 + 18 + 0 - 0   # A retire la manche absente (0)
    assert by["A"]["cells"][2] is None and by["B"]["cells"][0]["dropped"]
    table_nodrop = ch.standings(rounds_of(r1, r2, r3))
    assert {p["player_id"]: p["total"] for p in table_nodrop} == {"A": 43, "B": 68}


def test_tiebreak_by_wins_then_second_places():
    pts = [10, 6, 4, 0]
    r1 = parsed(("A", "Zed", 10, 0, 0), ("B", "Bob", 10, 0, 0), ("C", "Cy", 10, 0, 0), ("D", "Di", 10, 0, 0))
    r2 = parsed(("C", "Cy", 10, 0, 0), ("D", "Di", 10, 0, 0), ("B", "Bob", 10, 0, 0), ("A", "Zed", 10, 0, 0))
    t = ch.standings([{"label": "1", "scores": ch.round_scores(r1, pts, 0, 0)},
                      {"label": "2", "scores": ch.round_scores(r2, pts, 0, 0)}])
    by = {p["player_id"]: p for p in t}
    assert by["A"]["total"] == by["B"]["total"] == 10                       # égalité de points
    order = [p["player_id"] for p in t]
    assert order.index("A") < order.index("B")                              # une victoire l'emporte (pas l'ordre alphabétique)


def test_min_participation_makes_driver_unranked():
    r = [parsed(("A", "A", 10, 0, 0), ("B", "B", 10, 0, 0)) for _ in range(4)]
    r[3] = parsed(("A", "A", 10, 0, 0),)
    t = ch.standings(rounds_of(*r), min_ratio=1.0)
    assert [p["ranked"] for p in sorted(t, key=lambda p: p["player_id"])] == [True, False]
    assert t[-1]["player_id"] == "B"


def test_points_parsing_and_slug():
    assert ch.parse_points("25, 18;15 12") == [25, 18, 15, 12]
    for bad in ("", "a,b", "-1,2", "5000", ",".join(["1"] * 41)):
        with pytest.raises(ValueError):
            ch.parse_points(bad)
    assert ch.slugify("Coupe d'Été 2026 !") == "coupe-d-ete-2026"
    assert ch.slugify("???") == "championnat"
