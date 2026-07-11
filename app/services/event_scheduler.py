import time
import threading
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


def _loop(app):
    while True:
        for _ in range(12):   # 12 x 5s = 60s, mais réveillable rapidement pour un arrêt propre
            time.sleep(5)
        try:
            with app.app_context():
                from app.models import Event, EventRegistration, EventStatus, RegStatus
                from app.services.database import db
                from app.services import mailer

                now    = datetime.now(timezone.utc).replace(tzinfo=None)
                published = Event.query.filter_by(status=EventStatus.PUBLISHED).all()
                from app.services import discord_notifier

                for event in published:
                    delta_min = (event.date - now).total_seconds() / 60

                    # ── Rappels email pré-événement ───────────────────────────
                    if not event.email_sent and delta_min <= event.notify_before:
                        from sqlalchemy.orm import selectinload as _sl
                        regs = (EventRegistration.query
                                .filter_by(event_id=event.id, status=RegStatus.CONFIRMED, notified=False)
                                .options(_sl(EventRegistration.driver))
                                .all())
                        for reg in regs:
                            mailer.send_event_reminder(reg.driver, event, reg)
                            reg.notified = True
                        event.email_sent = True
                        db.session.commit()
                        log.info("Rappels envoyés pour '%s' (%d pilote(s))", event.title, len(regs))

                    # ── Discord exactly ~30 min avant (fenêtre 60s, une seule fois) ──
                    if not event.discord_notified and 29 <= delta_min <= 31:
                        discord_notifier.safe_notify(discord_notifier.notify_event_soon, event)
                        event.discord_notified = True
                        db.session.commit()
                        log.info("Discord 30min envoyé pour '%s'", event.title)

                    # ── Lancement automatique ─────────────────────────────────
                    if event.auto_launch and not event.launched and event.date <= now:
                        _launch_event(app, event, db)

                    # ── Auto-terminer les événements expirés (1h de grâce) ────
                    event_end = event.date + timedelta(minutes=event.total_minutes + 60)
                    if now >= event_end:
                        event.status = EventStatus.FINISHED
                        db.session.commit()
                        log.info("Auto-terminé: '%s'", event.title)

        except Exception:
            # db.session.rollback() doit s'exécuter dans le même app_context() : une fois le
            # bloc `with` sorti par l'exception, le contexte est déjà dépilé et l'appel plante
            # avec "Working outside of application context".
            with app.app_context():
                db.session.rollback()
            log.exception("Erreur event_scheduler")


def _launch_event(app, event, db):
    try:
        from app.services.server_config import build_config_from_event, save_event_config, deploy_config
        from app.services.config_builder import build_launch_args
        from app.services.process_manager import start_server, stop_server, is_running
        from app.services import discord_notifier
        from app.models import Server

        server_id = int(event.server_id or 1)

        # Arrêter le serveur en cours si besoin
        if is_running(server_id):
            log.info("Auto-launch: arrêt du serveur en cours avant lancement de '%s'", event.title)
            stop_server(server_id)
            time.sleep(3)

        # Ports et nom propres au serveur (multi-serveur), comme _do_start dans api.py
        server = db.session.get(Server, server_id)
        if server is None:
            log.error("Auto-launch: serveur %d introuvable pour '%s'", server_id, event.title)
            return

        # Construire et sauvegarder la config
        cfg         = build_config_from_event(event)
        config_name = save_event_config(event, cfg)

        # Déploie la config dans server-{id}/ avec les bons ports/ResultsPostUrl
        deploy_config(config_name, server_id)

        sc_b64, sd_b64 = build_launch_args(
            cfg, tcp_listener=server.tcp_port, udp_listener=server.udp_port, server_name=server.name)

        result = start_server(sc_b64, sd_b64, config_name, auto_restart=True, server_id=server_id)
        if result["ok"]:
            event.launched = True
            db.session.commit()
            log.info("Auto-launch: '%s' lancé (PID %s, config %s)",
                     event.title, result.get("pid"), config_name)
            discord_notifier.safe_notify(discord_notifier.notify_start, cfg, config_name,
                                         server_id=server_id, server_name=server.name or "")
        else:
            log.error("Auto-launch: échec pour '%s' — %s", event.title, result.get("error"))

    except Exception:
        log.exception("Erreur lors du lancement automatique de '%s'", event.title)


def init(app):
    t = threading.Thread(target=_loop, args=(app,), daemon=True)
    t.start()
    log.info("Event scheduler démarré")
