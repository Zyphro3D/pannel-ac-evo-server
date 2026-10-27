"""Mots de passe globaux du serveur de jeu : injectés au lancement (rotation comprise), jamais servis par
l'API de config ni réécrits dans les configs partagées."""
import json


def _write_cfg(name, server):
    from app.services.server_config import _configs_dir, default_config
    cfg = default_config()
    cfg["Server"].update(server)
    (_configs_dir() / name).write_text(json.dumps(cfg), encoding="utf-8")


def test_rotation_launch_gets_global_passwords(admin_client, monkeypatch):
    from app.services.process_manager import _rotation_load_and_build
    from app.services.server_config import _configs_dir
    monkeypatch.setenv("SERVER_ADMIN_PASSWORD", "glob-admin-pw")
    monkeypatch.setenv("SERVER_DRIVER_PASSWORD", "glob-driver-pw")
    _write_cfg("rot_secret_test.json", {"ServerName": "Rot", "AdminPassword": "", "DriverPassword": ""})
    with admin_client.app.app_context():
        cfg_data, *_ = _rotation_load_and_build("rot_secret_test.json", _configs_dir(), 1)
    assert cfg_data["Server"]["AdminPassword"] == "glob-admin-pw"
    assert cfg_data["Server"]["DriverPassword"] == "glob-driver-pw"


def test_config_api_does_not_serve_persisted_global_passwords(admin_client, monkeypatch):
    monkeypatch.setenv("SERVER_ADMIN_PASSWORD", "glob-admin-pw")
    monkeypatch.setenv("SERVER_DRIVER_PASSWORD", "glob-driver-pw")
    _write_cfg("old_persisted.json", {"AdminPassword": "glob-admin-pw", "DriverPassword": "glob-driver-pw"})
    _write_cfg("event_pw.json", {"DriverPassword": "event-only-pw"})

    body = admin_client.get("/api/configs/old_persisted.json").get_data(as_text=True)
    assert "glob-admin-pw" not in body and "glob-driver-pw" not in body
    # un mot de passe propre à un événement reste visible et modifiable
    assert json.loads(admin_client.get("/api/configs/event_pw.json").get_data())["Server"]["DriverPassword"] == "event-only-pw"


def test_default_config_carries_no_global_password(monkeypatch):
    from app.services.server_config import default_config
    monkeypatch.setenv("SERVER_ADMIN_PASSWORD", "glob-admin-pw")
    monkeypatch.setenv("SERVER_DRIVER_PASSWORD", "glob-driver-pw")
    srv = default_config()["Server"]
    assert srv["AdminPassword"] == "" and srv["DriverPassword"] == ""
