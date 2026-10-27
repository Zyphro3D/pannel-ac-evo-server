"""Fichier d'engagés d'un événement : seuls les pilotes encore approuvés y figurent."""
import json
from datetime import datetime, timedelta
from pathlib import Path


def test_rejected_driver_with_confirmed_registration_is_not_whitelisted(admin_client, tmp_path, monkeypatch):
    from app.models import Driver, DriverStatus, Event, EventRegistration, RegStatus
    from app.services import entry_list
    from app.services.database import db

    monkeypatch.setattr(entry_list, "_aceserver_dir", str(tmp_path))
    monkeypatch.setenv("ACE_BOT_STEAM_ID", "")
    with admin_client.app.app_context():
        ev = Event(title="Course test entry list", date=datetime.utcnow() + timedelta(days=1))
        ok = Driver(ingame_name="ElOk", email="elok@example.test", status=DriverStatus.APPROVED, steam_id="76561190000000001")
        ko = Driver(ingame_name="ElKo", email="elko@example.test", status=DriverStatus.REJECTED, steam_id="76561190000000002")
        for d in (ok, ko):
            d.set_password("ElPw-dummy1")
        db.session.add_all([ev, ok, ko])
        db.session.flush()
        db.session.add_all([EventRegistration(event_id=ev.id, driver_id=d.id, status=RegStatus.CONFIRMED) for d in (ok, ko)])
        db.session.commit()
        assert entry_list.generate(ev)

    doc = (Path(tmp_path) / "entry_list.json").read_text(encoding="utf-8")
    assert "76561190000000001" in doc
    assert "76561190000000002" not in doc
