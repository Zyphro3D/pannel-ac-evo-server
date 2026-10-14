"""Tâches de fond du panel : mesures de santé, sauvegarde automatique quotidienne, purge des journaux."""
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def _auto_enabled() -> bool:
    return os.environ.get("BACKUP_AUTO", "true").lower() == "true"


def _keep() -> int:
    try:
        return max(1, int(os.environ.get("BACKUP_KEEP", "7")))
    except ValueError:
        return 7


def run_daily_tasks() -> None:
    """Purges et sauvegarde automatique (au plus une par 24 h)."""
    from app.services import audit, backup, health
    try:
        audit.purge_old()
        health.purge_old()
    except Exception as e:
        log.warning("maintenance: purge ignorée : %s", e)
    if _auto_enabled():
        try:
            autos = [b for b in backup.list_backups() if b["auto"]]
            from app.models import _utcnow
            if not autos or (_utcnow() - autos[0]["created"]).total_seconds() > 23 * 3600:
                f = backup.create_backup("auto")
                backup.prune_auto(_keep())
                audit.record("backup.auto", target=f.name, actor="système", role="system")
        except Exception as e:
            log.warning("maintenance: sauvegarde automatique impossible : %s", e)
            audit.record("backup.auto", ok=False, detail=str(e)[:200], actor="système", role="system")


def init(app) -> None:
    global _started
    if os.environ.get("PANEL_DISABLE_MAINTENANCE") == "1" or app.config.get("TESTING"):
        return
    with _lock:
        if _started:
            return
        _started = True

    def loop():
        from app.services import health
        time.sleep(45)                                  # laisse le panel finir de démarrer
        last_daily = 0.0
        while True:
            try:
                with app.app_context():
                    health.sample_once()
                    if time.time() - last_daily > 3600:     # tâches « quotidiennes » vérifiées chaque heure
                        run_daily_tasks()
                        last_daily = time.time()
            except Exception as e:
                log.warning("maintenance: cycle ignoré : %s", e)
            time.sleep(health.SAMPLE_EVERY_S)

    threading.Thread(target=loop, daemon=True, name="panel-maintenance").start()
