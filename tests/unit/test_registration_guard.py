"""Serveur réservé aux inscrits : qui passe, qui est prévenu puis expulsé."""
from datetime import datetime, timedelta

from app.services import registration_guard as rg


def _setup(app, *, steam="76561190000000001", public=False, confirmed=True, server_id=2, days=1):
    """Un pilote validé portant ce SteamID, inscrit à un événement publié du serveur. Les données
    des autres tests ne sont pas touchées : on ne retire que celles de ce fichier (préfixe rg-)."""
    import uuid
    from app.models import Driver, Event, EventRegistration, EventStatus, RegStatus, DriverStatus
    from app.services.database import db
    with app.app_context():
        old_ev = [e.id for e in Event.query.filter(Event.title.like("RG %")).all()]
        old_dr = [d.id for d in Driver.query.filter(Driver.email.like("rg-%")).all()]
        EventRegistration.query.filter(EventRegistration.event_id.in_(old_ev) | EventRegistration.driver_id.in_(old_dr)).delete(synchronize_session=False)
        Event.query.filter(Event.id.in_(old_ev)).delete(synchronize_session=False)
        Driver.query.filter(Driver.id.in_(old_dr)).delete(synchronize_session=False)
        Driver.query.filter_by(steam_id=steam).update({"steam_id": None})
        Event.query.filter(Event.server_id == server_id, Event.status == EventStatus.PUBLISHED).update({"status": EventStatus.DRAFT})
        tag = uuid.uuid4().hex[:8]
        d = Driver(email=f"rg-{tag}@test", ingame_name=f"rg-{tag}", status=DriverStatus.APPROVED, steam_id=steam)
        d.set_password("x" * 12)
        ev = Event(title=f"RG {tag}", date=datetime.utcnow() + timedelta(days=days), status=EventStatus.PUBLISHED,
                   server_id=server_id, is_public=public)
        db.session.add_all([d, ev]); db.session.flush()
        db.session.add(EventRegistration(event_id=ev.id, driver_id=d.id,
                                         status=RegStatus.CONFIRMED if confirmed else RegStatus.PENDING))
        db.session.commit()


def test_inscrit_confirme_passe(admin_client):
    app = admin_client.application
    _setup(app)
    with app.app_context():
        assert rg.is_registered("76561190000000001", 2)
        assert not rg.is_registered("76561190000000001", 3)      # inscrit ailleurs
        assert not rg.is_registered("76561199999999999", 2)      # inconnu


def test_inscription_en_attente_ne_suffit_pas(admin_client):
    app = admin_client.application
    _setup(app, confirmed=False)
    with app.app_context():
        assert not rg.is_registered("76561190000000001", 2)


def test_evenement_ancien_ne_compte_plus(admin_client):
    app = admin_client.application
    _setup(app, days=-3)
    with app.app_context():
        assert not rg.is_registered("76561190000000001", 2)


def test_evenement_public_ouvre_a_tous(admin_client):
    app = admin_client.application
    _setup(app, public=True)
    with app.app_context():
        assert rg.is_registered("76561199999999999", 2)


def test_messages_en_anglais_sans_emoji():
    lines = rg.messages("Bob", "https://evo.example", 180)
    assert "Bob" in lines[0] and "https://evo.example" in lines[1] and "3 min" in lines[2]
    assert all(ord(ch) < 128 for line in lines for ch in line)


def test_reglage_par_serveur(admin_client):
    r = admin_client.post("/servers/1/registration", data={"required": "1", "grace_s": "10"})
    assert r.status_code in (200, 302)
    app = admin_client.application
    with app.app_context():
        assert rg.server_settings(1) == (True, 30)               # borné à 30 s minimum
    admin_client.post("/servers/1/registration", data={"grace_s": "120"})
    with app.app_context():
        assert rg.server_settings(1) == (False, 120)
