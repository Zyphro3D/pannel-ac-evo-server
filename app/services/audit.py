"""Journal d'audit : qui a fait quoi, quand, depuis quelle adresse.

``record()`` ne lève jamais : une panne du journal ne doit pas empêcher l'action elle-même. Ne jamais y
mettre de secret (mot de passe, jeton, URL de webhook) : on y note la clé d'un réglage, pas sa valeur.
"""
import json
import logging
import os
from datetime import timedelta

log = logging.getLogger(__name__)

_MAX_DETAIL = 1500


def retention_days() -> int:
    try:
        return max(7, int(os.environ.get("AUDIT_RETENTION_DAYS", "365")))
    except ValueError:
        return 365


def record(action: str, target: str = "", detail=None, ok: bool = True, actor: str | None = None,
           role: str | None = None) -> None:
    try:
        from flask import has_request_context
        from flask_login import current_user
        from app.models import AuditLog
        from app.services.database import db
        ip = ""
        if has_request_context():
            from app.services.netutil import client_ip
            ip = client_ip()
            if actor is None and getattr(current_user, "is_authenticated", False):
                actor = getattr(current_user, "username", None) or getattr(current_user, "ingame_name", "") or ""
                role = "superadmin" if getattr(current_user, "is_superadmin", False) else (
                    "admin" if getattr(current_user, "is_admin", False) else "pilot")
        text = ""
        if detail:
            text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str)
        db.session.add(AuditLog(actor=(actor or "")[:80], actor_role=(role or "")[:20], ip=ip[:64],
                                action=action[:60], target=str(target or "")[:200], detail=text[:_MAX_DETAIL],
                                ok=bool(ok)))
        db.session.commit()
    except Exception as e:                       # le journal ne doit jamais casser l'action
        try:
            from app.services.database import db
            db.session.rollback()
        except Exception:
            pass
        log.warning("audit: enregistrement impossible (%s) : %s", action, e)


def purge_old() -> int:
    """Supprime les entrées plus vieilles que la rétention ; retourne le nombre supprimé."""
    from app.models import AuditLog, _utcnow
    from app.services.database import db
    cutoff = _utcnow() - timedelta(days=retention_days())
    n = AuditLog.query.filter(AuditLog.ts < cutoff).delete(synchronize_session=False)
    db.session.commit()
    return n


# Écritures faites par un admin connecté : journalisées automatiquement (nom de la route, cible, NOMS des
# champs envoyés, jamais leurs valeurs). Les routes absentes d'ici ou listées dans _SKIP ont leur propre
# enregistrement (réglages, connexions, commandes en direct) ou n'ont aucun intérêt (accusés de bandeau).
_SKIP = {"api.results_ingest", "api.live_chat", "api.live_admin_cmd", "admin.settings", "live.timing_react",
         "admin.dismiss_env_drift", "admin.dismiss_env_notice", "admin.select_server", "auth.login",
         "tools.audit_csv", "admin.test_webhook", "admin.test_email"}
_WRITE = {"POST", "PUT", "PATCH", "DELETE"}


def install(app) -> None:
    @app.after_request
    def _audit_admin_writes(response):
        try:
            from flask import request
            from flask_login import current_user
            ep = request.endpoint or ""
            if (request.method in _WRITE and ep and ep not in _SKIP
                    and getattr(current_user, "is_authenticated", False)
                    and getattr(current_user, "is_admin", False)):
                target = ", ".join(f"{k}={v}" for k, v in (request.view_args or {}).items())
                fields = sorted(k for k in request.form.keys() if k != "csrf_token")
                record(ep, target=target, detail={"fields": fields} if fields else None,
                       ok=response.status_code < 400)
        except Exception as e:
            log.debug("audit: hook ignoré : %s", e)
        return response
