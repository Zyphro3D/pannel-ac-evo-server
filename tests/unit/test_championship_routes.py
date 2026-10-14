import json

import pytest


@pytest.fixture
def seeded(admin_client):
    """Deux courses synthétiques importées, retourne leurs identifiants."""
    app = admin_client.application
    from app.models import SessionResult, _utcnow
    from app.services.database import db
    import app.services.results_parser as rp

    def fake(n):
        return {"is_race": True, "track": "Monza", "layout": "GP", "session_type": "Race", "standings": [
            {"player_id": "7656119800000000%d" % i, "nickname": nm, "laps_count": 10, "position": i + 1,
             "fastest_lap_ms": 90000 + i, "starting_position": i + 1}
            for i, nm in enumerate(["Alice", "Bob", "Cyril"])]}
    ids = []
    with app.app_context():
        for n in (1, 2):
            r = SessionResult(raw_json=json.dumps({"n": n}), raw_json_hash=f"champ-test-{n}", track="Monza",
                              session_type="Race", received_at=_utcnow())
            db.session.add(r); db.session.commit(); ids.append(r.id)
    orig = rp.get_parsed
    rp.get_parsed = lambda r: fake(r.id) if r.raw_json_hash and r.raw_json_hash.startswith("champ-test") else orig(r)
    yield ids
    rp.get_parsed = orig
    with app.app_context():
        from app.models import Championship, ChampionshipRound
        ChampionshipRound.query.delete(); Championship.query.delete()
        SessionResult.query.filter(SessionResult.raw_json_hash.like("champ-test-%")).delete(synchronize_session=False)
        db.session.commit()


def test_full_championship_lifecycle(admin_client, seeded):
    c = admin_client
    r = c.post("/admin/championships/create", data={"name": "Coupe d'Été", "points": "25,18,15", "pole_bonus": "1",
                                                    "fastest_lap_bonus": "1", "drop_worst": "0", "is_public": "true"})
    assert r.status_code == 302 and "/admin/championships/" in r.headers["Location"]
    cid = int(r.headers["Location"].rsplit("/", 1)[1])
    page = c.get(f"/admin/championships/{cid}").get_data(as_text=True)
    assert f'value="{seeded[0]}"' in page                              # la course est proposée
    for rid in seeded:
        c.post(f"/admin/championships/{cid}/rounds/add", data={"result_id": rid})
    c.post(f"/admin/championships/{cid}/rounds/add", data={"result_id": seeded[0]})   # doublon refusé
    detail = c.get("/championships/coupe-d-ete").get_data(as_text=True)
    assert "Alice" in detail and "Manche 2" in detail and "Manche 3" not in detail
    # Alice : 2 manches × (25 + pole 1 + meilleur tour 1) = 54 ; Bob : 2 × 18 = 36
    assert "<strong>54</strong>" in detail and "<strong>36</strong>" in detail
    assert c.get("/championships").status_code == 200
    csv = c.get("/championships/coupe-d-ete/export.csv").get_data(as_text=True)
    assert "Alice" in csv and "54" in csv
    # inversion des manches puis suppression
    rows = [r for r in c.application.test_client().get("/championships").get_data(as_text=True).split("Coupe")]
    assert c.post(f"/admin/championships/{cid}/delete").status_code == 302
    assert c.get("/championships/coupe-d-ete").status_code == 404


def test_invalid_points_are_refused(admin_client):
    r = admin_client.post("/admin/championships/create", data={"name": "X", "points": "abc"}, follow_redirects=True)
    assert "Barème invalide" in r.get_data(as_text=True)


def test_private_championship_hidden_from_visitors(admin_client, seeded):
    admin_client.post("/admin/championships/create", data={"name": "Secret", "points": "10,5", "is_public": "false"})
    anon = admin_client.application.test_client()
    assert anon.get("/championships/secret").status_code == 404
    assert admin_client.get("/championships/secret").status_code == 200
    assert "Secret" not in anon.get("/championships").get_data(as_text=True)
