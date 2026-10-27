"""Liaison Steam : le retour n'est accepté que s'il correspond au lien demandé par cette session."""
import io
import urllib.parse

import pytest

from app.services import steam_openid

STEAM = "76561190000000042"


@pytest.fixture
def pilot(admin_client, monkeypatch):
    from app.models import Driver, DriverStatus
    from app.services.database import db
    app = admin_client.app
    with app.app_context():
        d = Driver(ingame_name="SteamPilot", email="steam@example.test", status=DriverStatus.APPROVED)
        d.set_password("SteamPilot-pw1")
        db.session.add(d)
        db.session.commit()
        did = d.id
    # Steam répond « valide » à toute vérification : seul le contrôle du panel est testé (aucun réseau)
    monkeypatch.setattr(steam_openid.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"ns:x\nis_valid:true\n"))
    c = app.test_client()
    c.post("/login", data={"username": "SteamPilot", "password": "SteamPilot-pw1"})
    yield c, did
    with app.app_context():
        db.session.delete(db.session.get(Driver, did))
        db.session.commit()


def _steam_reply(return_to):
    return {"openid.mode": "id_res", "openid.op_endpoint": steam_openid._STEAM_OPENID_URL,
            "openid.claimed_id": f"https://steamcommunity.com/openid/id/{STEAM}",
            "openid.identity": f"https://steamcommunity.com/openid/id/{STEAM}", "openid.return_to": return_to}


def _linked(app, did):
    from app.models import Driver
    from app.services.database import db
    with app.app_context():
        return db.session.get(Driver, did).steam_id


def test_callback_without_this_sessions_state_is_refused(admin_client, pilot):
    c, did = pilot
    c.get("/pilot/steam/link")
    forged = "http://localhost/pilot/steam/callback?state=etat-de-l-attaquant"
    c.get("/pilot/steam/callback?" + urllib.parse.urlencode({"state": "etat-de-l-attaquant", **_steam_reply(forged)}))
    assert _linked(admin_client.app, did) is None


def test_callback_matching_the_link_is_accepted(admin_client, pilot):
    c, did = pilot
    r = c.get("/pilot/steam/link")
    return_to = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["Location"]).query)["openid.return_to"][0]
    state = urllib.parse.parse_qs(urllib.parse.urlparse(return_to).query)["state"][0]
    c.get("/pilot/steam/callback?" + urllib.parse.urlencode({"state": state, **_steam_reply(return_to)}))
    assert _linked(admin_client.app, did) == STEAM
