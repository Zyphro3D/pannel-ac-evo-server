import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_aceserver_dir: str = ""


def init(aceserver_dir: str):
    global _aceserver_dir
    _aceserver_dir = aceserver_dir


def generate(event) -> bool:
    """Écrit le fichier d'engagés d'un événement au format lu par le serveur ACE EVO :
    liste blanche = pilotes confirmés (avec SteamID) + bot du panel, plus les règles d'accès
    (bannis, lest, restricteur). Ancien format (entries/driverName/carModel, celui d'un autre
    jeu) : ignoré par le serveur, d'où cette réécriture. Pour qu'il soit lu, pointer
    SERVER_ENTRY_LIST_PATH vers ce fichier."""
    if not _aceserver_dir:
        log.warning("entry_list: ACESERVER_DIR non configuré")
        return False

    import os
    from app.models import AccessRule, EventRegistration, RegStatus
    from app.services import access_control
    confirmed = EventRegistration.query.filter_by(event_id=event.id, status=RegStatus.CONFIRMED).all()
    steam_ids = [reg.driver.steam_id for reg in confirmed if reg.driver and reg.driver.steam_id]
    bot = os.environ.get("ACE_BOT_STEAM_ID", "").strip()
    out = access_control.build_document(AccessRule.query.all(), steam_ids, True,
                                        always_allow=[bot] if bot else [])
    path = Path(_aceserver_dir) / "entry_list.json"
    try:
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Entry list générée : %d pilote(s) autorisé(s) → %s",
                 len(out.get("steamid_whitelist", [])), path)
        return True
    except Exception:
        log.exception("Erreur génération entry list")
        return False
