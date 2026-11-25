"""Places : propres à chaque configuration (SERVER_MAX_PLAYERS n'est plus qu'une valeur par défaut)."""
from unittest.mock import patch


def test_global_max_players_no_longer_overrides_config(monkeypatch):
    from app.services.server_config import inject_global_server_settings
    monkeypatch.setenv("SERVER_MAX_PLAYERS", "20")
    cfg = inject_global_server_settings({"Server": {"MaxPlayers": 12}})
    assert cfg["Server"]["MaxPlayers"] == 12


def test_default_config_takes_global_max_players(monkeypatch):
    from app.services.server_config import default_config
    monkeypatch.setenv("SERVER_MAX_PLAYERS", "14")
    assert default_config()["Server"]["MaxPlayers"] == 14


def test_config_patch_saves_max_players(admin_client):
    r = admin_client.post("/api/config", json={"MaxPlayers": 12})
    assert r.get_json()["config"]["Server"]["MaxPlayers"] == 12
    r = admin_client.post("/api/config", json={"MaxPlayers": 999})
    assert r.get_json()["config"]["Server"]["MaxPlayers"] == 128


def test_start_keeps_or_enables_auto_restart():
    from app.routes import api
    with patch.object(api, "get_server_raw_state", return_value={}):
        assert api._default_auto_restart(1) is True
    with patch.object(api, "get_server_raw_state", return_value={"auto_restart": False}):
        assert api._default_auto_restart(1) is False
