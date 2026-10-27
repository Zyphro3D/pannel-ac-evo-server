"""Les noms du roulement relus depuis le dossier partagé avec le jeu sont revalidés."""
import json


def test_get_rotation_drops_invalid_names(admin_client):
    from app.services import rotation_manager
    with admin_client.app.app_context():
        p = rotation_manager._rotation_path()
        before = p.read_text() if p.exists() else None
        try:
            p.write_text(json.dumps({"enabled": True, "configs": ["ok.json", "<img src=x onerror=alert(1)>.json", "../x.json", 3]}))
            assert rotation_manager.get_rotation()["configs"] == ["ok.json"]
        finally:
            p.unlink() if before is None else p.write_text(before)
