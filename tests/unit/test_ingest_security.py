"""Ingestion des résultats : qui a le droit de poster, avec ou sans reverse proxy."""
import pytest

URL = "/api/results/ingest?server_id=1"


@pytest.fixture
def post(admin_client):
    app = admin_client.application
    from app.services.netutil import ingest_token

    def _post(addr="172.19.0.5", host="panel:4300", headers=None, token=False, trusted=""):
        import os
        os.environ["TRUSTED_PROXIES"] = trusted
        with app.app_context():
            url = URL + (f"&sig={ingest_token(1)}" if token else "")
        h = {"Host": host, **(headers or {})}
        r = app.test_client().post(url, json={}, headers=h, environ_overrides={"REMOTE_ADDR": addr})
        os.environ.pop("TRUSTED_PROXIES", None)
        return r.status_code
    return _post


def test_game_server_on_internal_network_is_accepted(post):
    assert post() == 200                                  # Docker : http://panel:4300
    assert post(addr="127.0.0.1", host="127.0.0.1:4300") == 200   # installation native


def test_public_internet_direct_is_refused(post):
    assert post(addr="93.184.216.34", host="93.184.216.35:4300") == 403


def test_request_through_any_reverse_proxy_is_refused(post):
    # Le proxy arrive d'une IP privée mais transmet le nom de domaine public
    assert post(addr="10.0.0.2", host="evo.example.org") == 403
    # Cloudflare / en-têtes de proxy, même avec un Host interne
    assert post(headers={"CF-Ray": "abc"}) == 403
    assert post(headers={"X-Forwarded-For": "198.51.100.7"}) == 403
    # Proxy déclaré de confiance
    assert post(addr="10.0.0.2", trusted="10.0.0.0/24") == 403


def test_token_works_everywhere(post):
    assert post(addr="93.184.216.34", host="evo.example.org", token=True) == 200


def test_client_ip_uses_cloudflare_header_only_from_trusted_proxy(admin_client, monkeypatch):
    from app.services.netutil import client_ip
    app = admin_client.application
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "10.0.0.2"},
                                  headers={"CF-Connecting-IP": "198.51.100.7"}):
        monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
        assert client_ip() == "10.0.0.2"                # sans proxy déclaré : adresse directe
        monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/24")
        assert client_ip() == "198.51.100.7"
    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "93.184.216.34"},
                                  headers={"CF-Connecting-IP": "1.1.1.1"}):
        assert client_ip() == "93.184.216.34"              # en-tête usurpé par un visiteur direct
