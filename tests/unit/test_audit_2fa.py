"""Journal d'audit, connexion avec 2FA, remise à zéro du fair-play."""
import os
import re

import pytest

from app.services import totp


@pytest.fixture
def app(admin_client):
    return admin_client.application


def _login(app, username, password):
    c = app.test_client()
    r = c.post("/login", data={"username": username, "password": password})
    return c, r


def _rows(app, action=None):
    from app.models import AuditLog
    with app.app_context():
        q = AuditLog.query
        if action:
            q = q.filter(AuditLog.action == action)
        return [(r.action, r.actor, r.target, r.ok, r.detail) for r in q.order_by(AuditLog.id).all()]


def test_login_success_and_failure_are_audited(app):
    c, r = _login(app, "superadmin", os.environ["SUPERADMIN_PASSWORD"])
    assert r.status_code == 302
    assert any(x[0] == "login.ok" and x[1] == "superadmin" for x in _rows(app))
    _login(app, "superadmin", "mauvais")
    assert any(x[0] == "login.fail" and not x[3] for x in _rows(app))
    # un mot de passe tapé dans le champ identifiant ne doit pas être journalisé
    _login(app, "MonSuperMotDePasse!", "x")
    assert not any("MonSuperMotDePasse" in (x[2] or "") + (x[1] or "") for x in _rows(app))


def test_admin_write_is_audited_without_values(app, admin_client):
    admin_client.post("/access/rules", data={"steam_id": "76561198000000999", "label": "secret-label", "ballast": "5"})
    rows = [x for x in _rows(app) if x[0] == "events_admin.access_rule_save"]
    assert rows and "steam_id" in rows[-1][4] and "76561198000000999" not in rows[-1][4] and "secret-label" not in rows[-1][4]


def test_2fa_full_flow(app):
    from app.models import AdminAccount
    from app.services.database import db
    c, _ = _login(app, "superadmin", os.environ["SUPERADMIN_PASSWORD"])
    c.application.config["WTF_CSRF_ENABLED"] = False
    assert c.post("/mon-compte/2fa/setup").status_code == 302
    html = c.get("/mon-compte").get_data(as_text=True)
    secret = re.search(r"mono[^>]*>([A-Z2-7]{32})<", html).group(1)
    # mauvais code refusé
    c.post("/mon-compte/2fa/enable", data={"code": "000000"})
    with app.app_context():
        assert not AdminAccount.query.filter_by(username="superadmin").first().totp_enabled
    c.post("/mon-compte/2fa/enable", data={"code": totp.code_at(secret)})
    with app.app_context():
        assert AdminAccount.query.filter_by(username="superadmin").first().totp_enabled
    codes = re.findall(r"<div>([a-z2-9]{4}-[a-z2-9]{4})</div>", c.get("/mon-compte").get_data(as_text=True))
    assert len(codes) == 10

    # nouvelle connexion : le mot de passe seul ne suffit plus
    c2, r = _login(app, "superadmin", os.environ["SUPERADMIN_PASSWORD"])
    assert r.status_code == 302 and "/login/2fa" in r.headers["Location"]
    assert c2.get("/server").status_code in (302, 401)                     # pas connecté
    # mauvais code puis bon code
    assert b"incorrect" in c2.post("/login/2fa", data={"code": "123456"}, follow_redirects=True).data.lower()
    step_code = totp.code_at(secret, at=__import__("time").time() + 30)     # pas suivant (le courant est déjà consommé)
    r = c2.post("/login/2fa", data={"code": step_code})
    assert r.status_code == 302 and "/login" not in r.headers["Location"]
    assert c2.get("/mon-compte").status_code == 200

    # un code de secours fonctionne une fois
    c3, _ = _login(app, "superadmin", os.environ["SUPERADMIN_PASSWORD"])
    assert c3.post("/login/2fa", data={"code": codes[0]}).status_code == 302
    c4, _ = _login(app, "superadmin", os.environ["SUPERADMIN_PASSWORD"])
    r = c4.post("/login/2fa", data={"code": codes[0]}, follow_redirects=True)
    assert b"incorrect" in r.data.lower()

    # désactivation (remet le compte de test dans son état initial pour les autres tests)
    c5, _ = _login(app, "superadmin", os.environ["SUPERADMIN_PASSWORD"])
    c5.post("/login/2fa", data={"code": codes[1]})
    c5.post("/mon-compte/2fa/disable", data={"password": os.environ["SUPERADMIN_PASSWORD"], "code": codes[2]})
    with app.app_context():
        assert not AdminAccount.query.filter_by(username="superadmin").first().totp_enabled
    actions = {x[0] for x in _rows(app)}
    assert {"2fa.enable", "2fa.disable", "login.2fa_fail"} <= actions


def test_fairplay_reset_ignores_older_sessions(app, admin_client):
    from datetime import timedelta
    from app.models import _utcnow
    from app.services import fairplay

    class Row:
        def __init__(self, at):
            self.received_at = at
    old, new = Row(_utcnow() - timedelta(days=5)), Row(_utcnow() + timedelta(minutes=1))
    seen = []
    import app.services.results_parser as rp
    orig = rp.get_parsed
    rp.get_parsed = lambda r: (seen.append(r) or {"standings": [], "incidents_reported": True})
    try:
        with app.app_context():
            fairplay.invalidate_cache()
            fairplay.build_fairplay(lambda: [old, new])
            assert len(seen) == 2                                         # pas de remise à zéro : tout compte
            fairplay.reset()
            seen.clear()
            fairplay.build_fairplay(lambda: [old, new])
            assert seen == [new]                                          # seule la session récente compte
    finally:
        rp.get_parsed = orig
        with app.app_context():
            from app.services import panel_state
            panel_state.set(fairplay.STATE_KEY, "")
            fairplay.invalidate_cache()
