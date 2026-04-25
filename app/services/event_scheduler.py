import time
import threading
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _loop(app):
    while True:
        time.sleep(60)
        try:
            with app.app_context():
                from app.models import Event, EventRegistration
                from app.services.database import db
                from app.services import mailer

                now    = datetime.now(timezone.utc).replace(tzinfo=None)

                # ── Rappels email + Discord pré-événement ────────────────────
                for event in Event.query.filter_by(status="published", email_sent=False).all():
                    delta_min = (event.date - now).total_seconds() / 60
                    if delta_min <= event.notify_before:
                        regs = event.registrations.filter_by(status="confirmed", notified=False).all()
                        for reg in regs:
                            mailer.send_event_reminder(reg.driver, event, reg)
                            reg.notified = True
                        event.email_sent = True
                        db.session.commit()
                        log.info("Rappels envoyés pour '%s' (%d pilote(s))", event.title, len(regs))

                    # Discord 30 min avant (indépendant du notify_before email)
                    if 0 < delta_min <= 31 and not event.email_sent:
                        pass  # géré ci-dessous séparément

                # Discord exactly ~30 min avant (fenêtre 60s)
                from app.services import discord_notifier
                for event in Event.query.filter_by(status="published").all():
                    delta_min = (event.date - now).total_seconds() / 60
                    if 29 <= delta_min <= 31:
                        discord_notifier.notify_event_soon(event)
                        log.info("Discord 30min envoyé pour '%s'", event.title)

                # ── Lancement automatique du serveur ──────────────────────────
                for event in (Event.query
                              .filter_by(status="published", auto_launch=True, launched=False)
                              .all()):
                    if event.date > now:
                        continue  # pas encore l'heure
                    _launch_event(app, event, db)

        except Exception:
            log.exception("Erreur event_scheduler")


def _launch_event(app, event, db):
    try:
        from app.services.server_config import build_config_from_event, save_event_config
        from app.services.config_builder import build_launch_args
        from app.services.process_manager import start_server, stop_server, is_running
        from app.services import discord_notifier

        # Arrêter le serveur en cours si besoin
        if is_running():
            log.info("Auto-launch: arrêt du serveur en cours avant lancement de '%s'", event.title)
            stop_server()
            time.sleep(3)

        # Construire et sauvegarder la config
        cfg         = build_config_from_event(event)
        config_name = save_event_config(event, cfg)
        sc_b64, sd_b64 = build_launch_args(cfg)

        result = start_server(sc_b64, sd_b64, config_name, auto_restart=True)
        if result["ok"]:
            event.launched = True
            db.session.commit()
            log.info("Auto-launch: '%s' lancé (PID %s, config %s)",
                     event.title, result.get("pid"), config_name)
            discord_notifier.notify_start(cfg, config_name)
        else:
            log.error("Auto-launch: échec pour '%s' — %s", event.title, result.get("error"))

    except Exception:
        log.exception("Erreur lors du lancement automatique de '%s'", event.title)


def init(app):
    t = threading.Thread(target=_loop, args=(app,), daemon=True)
    t.start()
    log.info("Event scheduler démarré")
