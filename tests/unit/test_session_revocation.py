"""Sessions : jeton dans le cookie (révocation à la déconnexion et au changement de mot de passe, pas
d'héritage par un compte qui reprend un id supprimé) et compteur d'essais 2FA côté serveur."""
import pytest

from app.services import totp


@pytest.fixture
def app(admin_client):
    return admin_client.application


def _add_admin(app, username, password, **kw):
    from app.models import AdminAccount
    from app.services.database import db
    with app.app_context():
        acc = AdminAccount(username=username, role="admin", **kw)
        acc.set_password(password)
        db.session.add(acc)
        db.session.commit()
        return acc.id


def _login(app, username, password):
    c = app.test_client()
    c.post("/login", data={"username": username, "password": password})
    return c


def _is_admin_session(client) -> bool:
    return client.get("/api/config").status_code == 200


def _clone(app, client):
    other = app.test_client()
    other.set_cookie("session", client.get_cookie("session").value)
    return other


def test_deleted_admin_cookie_does_not_open_account_reusing_its_id(app):
    from app.models import AdminAccount
    from app.services.database import db
    aid = _add_admin(app, "sess_old", "SessOld-pw1")
    old = _login(app, "sess_old", "SessOld-pw1")
    assert _is_admin_session(old)
    with app.app_context():
        db.session.delete(db.session.get(AdminAccount, aid))
        db.session.commit()
    _add_admin(app, "sess_new", "SessNew-pw1", id=aid)   # SQLite réutilise l'id libéré
    assert not _is_admin_session(old)


def test_logout_revokes_copies_of_the_cookie(app):
    _add_admin(app, "sess_logout", "SessLogout-pw1")
    c = _login(app, "sess_logout", "SessLogout-pw1")
    copy = _clone(app, c)
    assert _is_admin_session(copy)
    c.get("/logout")
    assert not _is_admin_session(copy)


def test_password_change_revokes_open_sessions(app, admin_client):
    from app.models import AdminAccount
    from app.services.database import db
    aid = _add_admin(app, "sess_pw", "SessPw-pw1")
    c = _login(app, "sess_pw", "SessPw-pw1")
    assert _is_admin_session(c)
    with app.app_context():
        db.session.get(AdminAccount, aid).set_password("SessPw-pw2")
        db.session.commit()
    assert not _is_admin_session(c)


def test_2fa_attempt_counter_survives_cookie_replay(app):
    from app.models import AdminAccount
    from app.services.database import db
    aid = _add_admin(app, "sess_2fa", "Sess2fa-pw1")
    with app.app_context():
        acc = db.session.get(AdminAccount, aid)
        secret = totp.new_secret()
        acc.totp_secret, acc.totp_enabled, acc.totp_last_step = secret, True, 0
        db.session.commit()
    c = app.test_client()
    c.post("/login", data={"username": "sess_2fa", "password": "Sess2fa-pw1"})
    pending = c.get_cookie("session").value
    for _ in range(5):
        c.set_cookie("session", pending)          # rejoue le cookie « 0 essai »
        c.post("/login/2fa", data={"code": "000000"})
    c.set_cookie("session", pending)
    r = c.post("/login/2fa", data={"code": totp.code_at(secret)})
    assert r.headers.get("Location", "").endswith("/login")
    assert not _is_admin_session(c)
