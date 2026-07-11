"""Tests pour app/routes/auth.py — login, protection des routes admin.

Attention à l'ordre : le login a une protection anti-bruteforce en mémoire
(5 échecs -> verrouillage 15 min, cf. auth.py::_bf_state) et un rate-limit
Flask-Limiter sur les POST. On garde donc un minimum d'appels et on réinitialise
_bf_state avant chaque test pour rester indépendant de l'ordre d'exécution.
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_bruteforce_state():
    from app.routes.auth import _bf_state
    _bf_state.clear()
    yield
    _bf_state.clear()


def test_login_page_loads_anonymously(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_admin_route_redirects_anonymous_to_login(client):
    resp = client.get("/server", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers["Location"]


def test_login_with_correct_admin_credentials_succeeds(client, app):
    resp = client.post("/login", data={
        "username": app.config["ADMIN_USERNAME"],
        "password": app.config["ADMIN_PASSWORD"],
    }, follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" not in resp.headers["Location"]


def test_login_with_wrong_password_is_rejected(client, app):
    resp = client.post("/login", data={
        "username": app.config["ADMIN_USERNAME"],
        "password": "definitely-not-the-password",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert "Identifiants incorrects" in resp.get_data(as_text=True)


def test_authenticated_admin_can_reach_server_page(client, app):
    client.post("/login", data={
        "username": app.config["ADMIN_USERNAME"],
        "password": app.config["ADMIN_PASSWORD"],
    })
    resp = client.get("/server")
    assert resp.status_code == 200
