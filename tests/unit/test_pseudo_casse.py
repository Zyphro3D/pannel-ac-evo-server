"""Pseudos et identifiants sans tenir compte de la casse : « Zyphro » et « zyphro » sont le même nom
(connexion, mot de passe oublié, inscription, comptes admin). Données préfixées « casse- », retirées à chaque test."""
import uuid

import pytest


@pytest.fixture
def app(admin_client):
    from app.models import AdminAccount, Driver
    from app.services.database import db
    a = admin_client.application
    with a.app_context():
        Driver.query.filter(Driver.email.like("casse-%")).delete(synchronize_session=False)
        AdminAccount.query.filter(AdminAccount.username.like("Casse%")).delete(synchronize_session=False)
        db.session.commit()
    return a


def _pilote(nom, status="approved"):
    from app.models import Driver
    from app.services.database import db
    d = Driver(email=f"casse-{uuid.uuid4().hex[:8]}@test", ingame_name=nom, status=status)
    d.set_password("motdepasse-casse-1")
    db.session.add(d)
    db.session.commit()
    return d


def test_pilote_trouve_quelle_que_soit_la_casse(app):
    from app.models import Driver
    with app.app_context():
        d = _pilote("CasseZyphro")
        assert Driver.par_nom("cassezyphro").id == d.id
        assert Driver.par_nom("CASSEZYPHRO").id == d.id
        assert Driver.nom_pris("casseZYPHRO")
        assert not Driver.nom_pris("casseZYPHRO", sauf_id=d.id)
        assert not Driver.nom_pris("CasseAutre")


def test_doublon_ancien_seul_le_nom_exact_departage(app):
    """Deux comptes d'avant la règle, « CasseDuo » et « casseduo » : le nom exact trouve le bon,
    une troisième écriture ne devine pas entre les deux."""
    from app.models import Driver
    with app.app_context():
        a, b = _pilote("CasseDuo"), _pilote("casseduo")
        assert Driver.par_nom("CasseDuo").id == a.id
        assert Driver.par_nom("casseduo").id == b.id
        assert Driver.par_nom("CASSEDUO") is None


def test_connexion_pilote_en_minuscules(app):
    with app.app_context():
        _pilote("CasseLogin")
    c = app.test_client()
    r = c.post("/login", data={"username": "casselogin", "password": "motdepasse-casse-1"})
    assert r.status_code == 302 and "/login" not in r.headers["Location"]


def test_inscription_refuse_une_variante_de_casse(app):
    from app.models import Driver
    with app.app_context():
        _pilote("CasseInscrit")
    def inscrire(nom, email):
        app.test_client().post("/register", data={"ingame_name": nom, "email": email,
                                                  "password": "Motdepasse-Casse-12", "confirm": "Motdepasse-Casse-12"})
    inscrire("casseinscrit", "casse-refuse@test")
    inscrire("CasseNouveau", "casse-accepte@test")      # témoin : le même formulaire passe avec un autre nom
    with app.app_context():
        assert Driver.query.filter_by(email="casse-refuse@test").first() is None
        assert Driver.query.filter_by(email="casse-accepte@test").first() is not None


def test_compte_admin_variante_de_casse_refusee_mais_renommage_de_soi_permis(app):
    from app.models import AdminAccount
    from app.services.database import db
    with app.app_context():
        acc = AdminAccount(username="CasseAdmin", display_name="x", role="admin")
        acc.set_password("motdepasse-casse-1")
        db.session.add(acc)
        db.session.commit()
        assert AdminAccount.nom_pris("casseadmin")
        assert not AdminAccount.nom_pris("CASSEADMIN", sauf_id=acc.id)
        assert AdminAccount.par_nom("casseadmin", is_active=True).id == acc.id
