"""Rejoindre un championnat : connexion Steam, pseudo + mail, inscription confirmée d'office."""
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def champ(admin_client):
    """Serveur 1 réservé aux inscrits avec une manche publiée demain ; remis en état après."""
    from app.models import Event, EventStatus, Server
    from app.services.database import db
    app = admin_client.application
    with app.app_context():
        srv = db.session.get(Server, 1)
        srv.registration_required = True
        ev = Event(title="JC manche", date=datetime.utcnow() + timedelta(days=1), status=EventStatus.PUBLISHED, server_id=1)
        db.session.add(ev); db.session.commit()
        ev_id = ev.id
    yield ev_id
    with app.app_context():
        from app.models import EventRegistration, Driver
        EventRegistration.query.filter_by(event_id=ev_id).delete()
        Event.query.filter_by(id=ev_id).delete()
        Driver.query.filter(Driver.email.like("jc-%")).delete(synchronize_session=False)
        db.session.get(Server, 1).registration_required = False
        db.session.commit()


def _steam(monkeypatch, steam_id):
    from app.services import steam_openid
    monkeypatch.setattr(steam_openid, "verify_callback", lambda args, ret: steam_id)


def _anon(admin_client):
    return admin_client.application.test_client()


def test_page_reservee_aux_serveurs_championnat(admin_client):
    assert _anon(admin_client).get("/join/1").status_code == 404     # serveur ouvert : pas de page


def test_nouveau_pilote_inscrit_en_une_fois(admin_client, champ, monkeypatch):
    from app.models import Driver, EventRegistration, RegStatus, DriverStatus
    c = _anon(admin_client)
    page = c.get("/join/1").get_data(as_text=True)
    assert "/join/1/steam" in page
    r = c.get("/join/1/steam")
    assert r.status_code == 302 and "steamcommunity.com" in r.headers["Location"]
    with c.session_transaction() as s:
        state = s["join_state"]["state"]
    _steam(monkeypatch, "76561190000004242")
    c.get(f"/join/steam/callback?state={state}")
    assert "join-email" in c.get("/join/1").get_data(as_text=True)          # formulaire pseudo + mail
    r = c.post("/join/1/finish", data={"ingame_name": "JC Pilote", "email": "jc-1@test"})
    assert r.status_code == 302
    with admin_client.application.app_context():
        d = Driver.query.filter_by(steam_id="76561190000004242").first()
        assert d.status == DriverStatus.APPROVED and d.email == "jc-1@test"
        reg = EventRegistration.query.filter_by(event_id=champ, driver_id=d.id).first()
        assert reg.status == RegStatus.CONFIRMED
        from app.services import registration_guard as rg
        assert rg.is_registered("76561190000004242", 1)


def test_mail_obligatoire(admin_client, champ, monkeypatch):
    c = _anon(admin_client)
    c.get("/join/1/steam")
    with c.session_transaction() as s:
        state = s["join_state"]["state"]
    _steam(monkeypatch, "76561190000004243")
    c.get(f"/join/steam/callback?state={state}")
    c.post("/join/1/finish", data={"ingame_name": "JC Sans Mail", "email": ""})
    from app.models import Driver
    with admin_client.application.app_context():
        assert Driver.query.filter_by(steam_id="76561190000004243").first() is None


def test_retour_steam_sans_etat_refuse(admin_client, champ, monkeypatch):
    _steam(monkeypatch, "76561190000004244")
    c = _anon(admin_client)
    c.get("/join/steam/callback?state=forge")
    with c.session_transaction() as s:
        assert "join_pending" not in s


def test_message_du_bot_donne_le_lien():
    from app.services import registration_guard as rg
    lines = rg.messages("Bob", "https://evo.example/", 60, 2)
    assert "https://evo.example/join/2" in lines[1]


def test_voiture_choisie_enregistree(admin_client, champ, monkeypatch):
    import app.routes.public as pub
    from app.models import Driver, EventRegistration
    monkeypatch.setattr(pub, "_join_cars", lambda sid: [{"name": "preset_m4gt3_mech_1", "label": "BMW M4 GT3"}])
    c = _anon(admin_client)
    c.get("/join/1/steam")
    with c.session_transaction() as s:
        state = s["join_state"]["state"]
    _steam(monkeypatch, "76561190000004250")
    c.get(f"/join/steam/callback?state={state}")
    assert "join-car" in c.get("/join/1").get_data(as_text=True)
    c.post("/join/1/finish", data={"ingame_name": "JC Voiture", "email": "jc-car@test", "car": "inconnue"})
    with admin_client.application.app_context():
        assert Driver.query.filter_by(steam_id="76561190000004250").first() is None   # voiture hors liste refusée
    c.post("/join/1/finish", data={"ingame_name": "JC Voiture", "email": "jc-car@test", "car": "preset_m4gt3_mech_1"})
    with admin_client.application.app_context():
        d = Driver.query.filter_by(steam_id="76561190000004250").first()
        reg = EventRegistration.query.filter_by(event_id=champ, driver_id=d.id).first()
        assert (reg.assigned_car, reg.car_display) == ("preset_m4gt3_mech_1", "BMW M4 GT3")


def test_message_selon_la_voiture(monkeypatch):
    from types import SimpleNamespace
    from app.services import registration_guard as rg
    monkeypatch.setattr(rg, "preset_car", lambda p: {"preset_m4gt3_mech_1": "ks_bmw_m4_gt3"}.get(p, ""))
    reg = SimpleNamespace(assigned_car="preset_m4gt3_mech_1", car_display="BMW M4 GT3 Evo - GT3")
    assert "start driving" in rg.car_message("Bob", reg, "ks_bmw_m4_gt3")
    wrong = rg.car_message("Bob", reg, "ks_porsche_992_gt3_r_rennsport")
    assert "wrong car" in wrong and "BMW M4 GT3 Evo - GT3" in wrong
    assert "start driving" in rg.car_message("Bob", SimpleNamespace(assigned_car="", car_display=""), "ks_x")
