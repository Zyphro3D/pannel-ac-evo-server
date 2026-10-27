"""Masquage des SteamID pour les pilotes : il ne doit jamais toucher le cache partagé des résultats."""
import json

from helpers import _session


def test_pilot_view_does_not_strip_shared_parse_cache(admin_client):
    from app.models import Driver, DriverStatus, SessionResult
    from app.services.database import db
    from app.services.results_parser import get_parsed

    app = admin_client.app
    with app.app_context():
        r = SessionResult(track="Circuit Test", session_type="Race", raw_json=json.dumps(_session()))
        d = Driver(ingame_name="PiiPilot", email="pii@example.test", status=DriverStatus.APPROVED)
        d.set_password("PiiPilot-pw1")
        db.session.add_all([r, d])
        db.session.commit()
        rid = r.id
        assert all(row.get("player_id") for row in get_parsed(r)["standings"])

    pilot = app.test_client()
    pilot.post("/login", data={"username": "PiiPilot", "password": "PiiPilot-pw1"})
    for url in ("/api/results", f"/api/results/{rid}"):
        resp = pilot.get(url)
        assert resp.status_code == 200
        assert "player_id" not in resp.get_data(as_text=True)

    with app.app_context():
        standings = get_parsed(db.session.get(SessionResult, rid))["standings"]
        assert [row.get("player_id") for row in standings] == ["1", "2"]
    assert '"player_id"' in admin_client.get(f"/api/results/{rid}").get_data(as_text=True)


def test_pilot_view_replaces_game_guids_with_response_labels(admin_client):
    from app.models import Driver, DriverStatus, SessionResult
    from app.services.database import db

    app = admin_client.app
    with app.app_context():
        r = SessionResult(track="Circuit Test", session_type="Race", raw_json=json.dumps(_session()))
        d = Driver(ingame_name="GuidPilot", email="guid@example.test", status=DriverStatus.APPROVED)
        d.set_password("GuidPilot-pw1")
        db.session.add_all([r, d])
        db.session.commit()
        rid = r.id

    pilot = app.test_client()
    pilot.post("/login", data={"username": "GuidPilot", "password": "GuidPilot-pw1"})
    raw = pilot.get(f"/api/results/{rid}").get_json()["raw"]
    alice = raw["drivers"][0]["guid"]
    assert isinstance(alice, str) and alice.startswith("j")
    assert {lap["driver_key"] for lap in raw["laps"]} == {d["guid"] for d in raw["drivers"]}
    assert '"a"' not in json.dumps(raw)
    # l'admin garde les vrais identifiants
    assert admin_client.get(f"/api/results/{rid}").get_json()["raw"]["drivers"][0]["guid"] == {"a": "1", "b": "7"}
