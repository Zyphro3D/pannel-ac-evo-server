from pathlib import Path


def _url(client, endpoint, **kw):
    from flask import url_for
    with client.application.test_request_context():
        return url_for(endpoint, **kw)


def test_installation_neuve_propose_le_telechargement_du_serveur(admin_client):
    exe = Path(admin_client.application.config["ACESERVER_DIR"]) / "AssettoCorsaEVOServer.exe"
    exe.unlink(missing_ok=True)
    with admin_client.session_transaction() as s:
        s.pop("install_prompted", None)
    r = admin_client.get(_url(admin_client, "admin.server"))
    assert r.status_code == 302 and "install=1" in r.headers["Location"]
    # Une seule fois par session : ensuite la page s'affiche, avec le bandeau
    r = admin_client.get(_url(admin_client, "admin.server"))
    assert r.status_code == 200 and b"game-server-missing-banner" in r.data
    page = admin_client.get(_url(admin_client, "admin.settings", tab="server", install=1)).data
    assert b"ctrModalOpen('install')" in page


def test_serveur_installe_ni_redirection_ni_bandeau(admin_client):
    exe = Path(admin_client.application.config["ACESERVER_DIR"]) / "AssettoCorsaEVOServer.exe"
    exe.write_bytes(b"MZ")
    try:
        with admin_client.session_transaction() as s:
            s.pop("install_prompted", None)
        r = admin_client.get(_url(admin_client, "admin.server"))
        assert r.status_code == 200 and b"game-server-missing-banner" not in r.data
        page = admin_client.get(_url(admin_client, "admin.settings", tab="server", install=1)).data
        assert b"ctrModalOpen('install')" not in page
    finally:
        exe.unlink()
