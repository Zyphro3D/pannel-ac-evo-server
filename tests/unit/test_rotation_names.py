"""Les noms du roulement relus depuis le dossier partagé avec le jeu sont revalidés."""
import json


def test_get_rotation_drops_invalid_names(admin_client):
    from app.services import rotation_manager
    with admin_client.app.app_context():
        p = rotation_manager._rotation_path(1)
        before = p.read_text() if p.exists() else None
        try:
            p.write_text(json.dumps({"enabled": True, "configs": ["ok.json", "<img src=x onerror=alert(1)>.json", "../x.json", 3]}))
            assert rotation_manager.get_rotation(1)["configs"] == ["ok.json"]
        finally:
            p.unlink() if before is None else p.write_text(before)


def test_une_file_de_roulement_par_serveur(tmp_path, monkeypatch):
    """Scénario du 29/10 : le serveur 2 (Trackday, hors de la liste) ne doit pas partir
    sur la file du serveur 1 (GT3)."""
    from app.services import rotation_manager as rm
    monkeypatch.setenv("ACESERVER_DIR", str(tmp_path))
    monkeypatch.setattr("app.services.server_config._valid_config_name", lambda n: n.endswith(".json"))
    rm.save_rotation({"enabled": True, "cycle": True, "configs": ["cota.json", "imola.json"]}, 1)

    assert (tmp_path / ".rotation.json").exists()            # serveur 1 : nom d'origine conservé
    assert rm.get_next_config("imola.json", 1) == "cota.json"
    assert rm.get_rotation(2)["enabled"] is False
    assert rm.get_next_config("trackday.json", 2) is None

    rm.save_rotation({"enabled": True, "cycle": False, "configs": ["nordschleife.json"]}, 2)
    assert (tmp_path / ".rotation_2.json").exists()
    assert rm.get_rotation(1)["configs"] == ["cota.json", "imola.json"]
    rm.delete_rotation(2)
    rm.delete_rotation(1)                                      # sans effet sur le serveur principal
    assert not (tmp_path / ".rotation_2.json").exists() and (tmp_path / ".rotation.json").exists()
