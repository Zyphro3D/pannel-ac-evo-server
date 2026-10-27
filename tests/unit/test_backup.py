import io
import json
import zipfile

import pytest

from app.services import backup


@pytest.fixture
def app(admin_client):
    return admin_client.application


def test_create_validate_restore_roundtrip(app):
    from app.models import PanelState
    from app.services import panel_state
    from app.services.database import db
    with app.app_context():
        panel_state.set("test_backup_marker", "avant")
        path = backup.create_backup("manuelle")
        manifest = backup.validate(path)
        assert manifest["format"] == 1 and "db/ace_evo.db" in manifest["contents"]
        panel_state.set("test_backup_marker", "apres")
        res = backup.restore(path)
        assert res["safety_backup"].endswith("-avant-restauration.zip")
        assert backup.backup_path(res["safety_backup"]).exists()
        db.session.remove()
        assert panel_state.get("test_backup_marker") == "avant"     # l'état d'avant la sauvegarde est revenu
        panel_state.set("test_backup_marker", "")


def _zip_with(tmp_path, members: dict) -> "Path":
    f = tmp_path / "x.zip"
    with zipfile.ZipFile(f, "w") as z:
        for n, data in members.items():
            z.writestr(n, data)
    return f


def test_malicious_archives_are_refused(app, tmp_path):
    with app.app_context():
        good_manifest = json.dumps({"format": 1, "panel_version": "1.0.0"})
        for evil in ("../../etc/passwd", "/etc/passwd", "configs/../../x.json", "app/__init__.py", "media/x.php",
                     "configs\\evil.json", "settings.json/../x"):
            f = _zip_with(tmp_path, {"manifest.json": good_manifest, "db/ace_evo.db": b"x", evil: b"boom"})
            with pytest.raises(backup.BackupError):
                backup.validate(f)
        with pytest.raises(backup.BackupError):                      # pas un zip
            p = tmp_path / "n.zip"; p.write_bytes(b"pas un zip"); backup.validate(p)
        with pytest.raises(backup.BackupError):                      # base absente
            backup.validate(_zip_with(tmp_path, {"manifest.json": good_manifest}))
        with pytest.raises(backup.BackupError):                      # base qui n'est pas SQLite
            backup.validate(_zip_with(tmp_path, {"manifest.json": good_manifest, "db/ace_evo.db": b"garbage" * 100}))
        with pytest.raises(backup.BackupError):                      # version trop récente
            backup.validate(_zip_with(tmp_path, {"manifest.json": json.dumps({"format": 1, "panel_version": "99.0.0"}),
                                                 "db/ace_evo.db": b"x"}))


def test_backup_name_must_be_safe(app):
    with app.app_context():
        for bad in ("../../etc/passwd", "a/b.zip", "x.txt", "", "..zip"):
            with pytest.raises(backup.BackupError):
                backup.backup_path(bad)


def test_prune_keeps_only_recent_auto(app):
    with app.app_context():
        d = backup.backups_dir()
        for i in range(5):
            f = d / f"panel-backup-20260101-00000{i}-auto.zip"
            f.write_bytes(b"x")
            import os; os.utime(f, (1_700_000_000 + i, 1_700_000_000 + i))
        manual = d / "panel-backup-20260101-000009.zip"; manual.write_bytes(b"x")
        backup.prune_auto(2)
        left = [b["name"] for b in backup.list_backups()]
        assert sum(n.endswith("-auto.zip") for n in left) == 2 and manual.name in left
        for n in left:
            (d / n).unlink()


def test_realistic_file_names_survive_roundtrip(app, tmp_path):
    """Régression : une image « ChatGPT Image 3 juil. 2026, 07_12_03.png » (accents, virgule, points)
    était incluse à la création mais refusée à la validation, rendant la sauvegarde inutilisable."""
    from pathlib import Path
    import app as app_pkg
    media = Path(app_pkg.__file__).parent.parent / "media" / "mail"
    media.mkdir(parents=True, exist_ok=True)
    names = ["ChatGPT Image 3 juil. 2026, 07_12_03.png", "été (1).webp", "x-y_z.jpg"]
    for n in names:
        (media / n).write_bytes(b"\x89PNG fake")
    try:
        with app.app_context():
            f = backup.create_backup("manuelle")
            manifest = backup.validate(f)
            for n in names:
                assert f"media/mail/{n}" in manifest["contents"]
            f.unlink()
    finally:
        for n in names:
            (media / n).unlink(missing_ok=True)
        try:
            media.rmdir()
        except OSError:
            pass


def test_restore_keeps_only_known_settings(app):
    raw = json.dumps({"PANEL_TITLE": "Mon panel", "BACKUP_KEEP": "5", "__last_seen_version": "2.4.0",
                      "SECRET_KEY": "volee", "PYTHONPATH": "/tmp/x", "DATABASE_URL": "sqlite:////tmp/x.db",
                      "MAIL_SERVER": {"pas": "une chaîne"}}).encode()
    with app.app_context():
        kept = json.loads(backup._filtered_settings(raw))
    assert kept == {"PANEL_TITLE": "Mon panel", "BACKUP_KEEP": "5", "__last_seen_version": "2.4.0"}
    with pytest.raises(backup.BackupError):
        backup._filtered_settings(b"[1, 2]")
