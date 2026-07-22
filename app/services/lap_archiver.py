"""
Archivage périodique de l'historique des tours (LapRecord → LapArchive).

Au-delà de LAP_HISTORY_RETENTION_MONTHS, les tours détaillés sont regroupés par
(serveur, pilote, circuit, type de roulage, mois) en une ligne compacte plutôt
que supprimés — voir CHANGELOG v1.9.4.
"""
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_LAST_RUN_KEY = "__lap_archive_last_run"


def _get_last_run_date() -> str:
    from app import _SETTINGS_PATH
    if not _SETTINGS_PATH.exists():
        return ""
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return data.get(_LAST_RUN_KEY, "")
    except Exception:
        return ""


def _set_last_run_date(date_str: str) -> None:
    from app import _SETTINGS_PATH
    from app.services.process_manager import _atomic_write
    data = {}
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("_set_last_run_date: settings.json illisible, on repart d'un dict vide : %s", e)
    data[_LAST_RUN_KEY] = date_str
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(_SETTINGS_PATH, json.dumps(data, indent=2, ensure_ascii=False))


def archive_old_laps(app):
    """Regroupe et compacte les LapRecord plus vieux que LAP_HISTORY_RETENTION_MONTHS."""
    from app.models import LapRecord, LapArchive
    from app.services.database import db

    retention_months = int(app.config.get("LAP_HISTORY_RETENTION_MONTHS", "6") or 6)
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention_months * 30)

    old_laps = LapRecord.query.filter(LapRecord.recorded_at < cutoff).all()
    if not old_laps:
        return

    groups = defaultdict(list)
    for lap in old_laps:
        period = lap.recorded_at.strftime("%Y-%m")
        key = (lap.server_id, lap.steam_id, lap.track_value, lap.session_type, period)
        groups[key].append(lap)

    for (server_id, steam_id, track_value, session_type, period), laps in groups.items():
        new_entries = [{"t": l.lap_time_ms, "car": l.car} for l in laps]
        nickname = laps[-1].nickname or laps[0].nickname

        archive = LapArchive.query.filter_by(
            server_id=server_id, steam_id=steam_id, track_value=track_value,
            session_type=session_type, period=period,
        ).first()
        if archive:
            merged = json.loads(archive.laps_json) + new_entries
            archive.laps_json   = json.dumps(merged)
            archive.nickname    = nickname
        else:
            merged = new_entries
            archive = LapArchive(
                server_id=server_id, steam_id=steam_id, nickname=nickname,
                track_value=track_value, session_type=session_type, period=period,
                laps_json=json.dumps(merged), best_lap_ms=0, avg_lap_ms=0, lap_count=0,
            )
            db.session.add(archive)

        merged_times = [e["t"] for e in merged]
        archive.best_lap_ms = min(merged_times)
        archive.avg_lap_ms  = sum(merged_times) // len(merged_times)
        archive.lap_count   = len(merged)

        for lap in laps:
            db.session.delete(lap)

    db.session.commit()
    log.info("lap_archiver: %d tour(s) archivé(s) en %d groupe(s)", len(old_laps), len(groups))


def _loop(app):
    while True:
        for _ in range(72):   # 72 x 5s = 6 min, réveillable rapidement pour un arrêt propre
            time.sleep(5)
        today = datetime.now(timezone.utc).date().isoformat()
        if _get_last_run_date() == today:
            continue
        try:
            with app.app_context():
                archive_old_laps(app)
            _set_last_run_date(today)
        except Exception:
            with app.app_context():
                from app.services.database import db
                db.session.rollback()
            log.exception("Erreur lap_archiver")


def init(app):
    t = threading.Thread(target=_loop, args=(app,), daemon=True)
    t.start()
    log.info("Lap archiver démarré (rétention: %s mois)", app.config.get("LAP_HISTORY_RETENTION_MONTHS", "6"))
