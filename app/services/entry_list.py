import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_aceserver_dir: str = ""


def init(aceserver_dir: str):
    global _aceserver_dir
    _aceserver_dir = aceserver_dir


def generate(event) -> bool:
    if not _aceserver_dir:
        log.warning("entry_list: ACESERVER_DIR non configuré")
        return False

    confirmed = event.registrations.filter_by(status="confirmed").all()
    entries = [
        {
            "driverName": reg.driver.ingame_name,
            "carModel":   reg.assigned_car or "",
            "carSkin":    "",
            "spectator":  False,
        }
        for reg in confirmed
    ]

    out = {"entries": entries, "forceEntryList": True}
    path = Path(_aceserver_dir) / "entry_list.json"
    try:
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Entry list générée : %d pilote(s) → %s", len(entries), path)
        return True
    except Exception:
        log.exception("Erreur génération entry list")
        return False
