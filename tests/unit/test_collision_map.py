"""Carte des accrochages : calage monde → plan, extraction des impacts, routes."""
import json
import math

import pytest

from app.services import collision_map as cm
from app.services import results_parser as rp


def test_calibration_covers_the_track_images_that_have_a_ground_truth():
    cal = cm.calibration()
    assert len(cal) >= 30 and "spa__layout_gp" in cal
    for slug in ("spa__layout_gp", "monza__layout_gp", "suzuka__layout_gp"):
        assert cm.has_map(slug)
    assert not cm.has_map("circuit-inconnu__layout_x") and not cm.has_map(None)


def test_known_spa_points_land_on_the_circuit_outline():
    """Points réels (positions d'accrochages relevés à Spa) : ils doivent tomber près du tracé du plan."""
    import re
    path = cm.svg_path("spa__layout_gp")
    pts = [(float(a), float(b)) for a, b in re.findall(r"(-?\d+\.?\d*),(-?\d+\.?\d*)", path)]
    # points monde du premier tour de contrôle du circuit (x, z), tirés de résultats réels
    world = [(-1207.96, -2094.33), (-1300.0, -2000.0)]
    X, Y = cm.to_map("spa__layout_gp", *world[0])
    assert 0 <= X <= 400 and 0 <= Y <= 400
    dist = min(math.hypot(X - px, Y - py) for px, py in pts)
    assert dist < 6                                   # sur la ligne idéale, donc contre le tracé


def _fake_result(kind="wall"):
    car = {"a": "1", "b": "2"}
    return {"drivers": [{"guid": {"a": "10", "b": "20"}, "nickname": "Alice", "player_id": "76561198000000001"}],
            "cars": [{"car_id": car, "race_number": 7, "model_displayname": "BMW"}],
            "car_standings": [{"car_id": car}], "driver_standings": [{"a": "10", "b": "20"}],
            "collisions": [{"car_id": car, "collider": kind.capitalize(), "has_damage": True, "relative_impact_kmh": 42.5,
                            "server_timestamp": 100.0, "world_pos": {"x": 10.0, "y": 1.0, "z": 20.0},
                            "rel_pos": {"x": -0.5, "y": 0.1, "z": 1.9}}]}


def test_build_incidents_keeps_position_on_track_and_on_car():
    data = _fake_result("wall")
    driver_map = {rp._guid_key(d["guid"]): d for d in data["drivers"]}
    car_map = {rp._guid_key(c["car_id"]): c for c in data["cars"]}
    res = rp.build_incidents(data, driver_map, car_map)
    h = res["hits"][0]
    assert h["kind"] == "wall" and h["kmh"] == 42.5 and h["damage"] is True and h["nickname"] == "Alice"
    assert (h["x"], h["z"]) == (10.0, 20.0) and (h["rx"], h["ry"], h["rz"]) == (-0.5, 0.1, 1.9)


def test_build_groups_by_circuit_and_never_leaks_steam_ids():
    parsed = {"track": "Circuit de Spa Francorchamps", "layout": "GP",
              "hits": [{"nickname": "Alice", "kind": "wall", "kmh": 30.0, "damage": False, "x": -1207.9, "z": -2094.3,
                        "rx": 0.2, "ry": 0.0, "rz": 1.5, "with": []},
                       {"nickname": "Bob", "kind": "car", "kmh": 12.0, "damage": True, "x": -1200.0, "z": -2090.0,
                        "rx": -0.9, "ry": 0.2, "rz": 0.3, "with": ["Alice"]}]}
    out = cm.build([(1, "14/10 · Course", parsed), (2, "x", {"track": "Monza", "layout": "GP", "hits": []})], "spa__layout_gp")
    assert out["drivers"] == ["Alice", "Bob"] and len(out["rows"]) == 2 and len(out["sessions"]) == 1
    assert out["rows"][1][6] == 1 and out["rows"][1][10] == [0]            # type « voiture », avec Alice
    assert "7656119" not in json.dumps(out) and out["path"].startswith("M")
    assert cm.build([(1, "a", parsed)], "spa__layout_gp", only_session=99)["rows"] == []


def test_routes(admin_client, monkeypatch):
    anon = admin_client.application.test_client()
    assert anon.get("/accrochages").status_code == 200                      # page publique, même vide
    assert anon.get("/accrochages/data/circuit-inconnu__layout_x.json").status_code == 404
    r = anon.get("/accrochages/data/spa__layout_gp.json")
    assert r.status_code == 200 and r.json["rows"] == [] and r.json["path"].startswith("M")
