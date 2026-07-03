"""Utilitaires partagés entre les blueprints (décorateurs d'auth, etc.)."""
from functools import wraps

from flask import redirect, url_for, jsonify, request, render_template, make_response, flash
from flask_login import current_user


# ── Helpers HTMX ─────────────────────────────────────────────────────────────

def is_htmx() -> bool:
    """Retourne True si la requête vient d'HTMX (header HX-Request présent)."""
    return request.headers.get("HX-Request") == "true"


def htmx_toast(type: str, message: str) -> str:
    """Retourne le fragment HTML d'un toast HTMX (cible #toast-zone)."""
    return render_template("_partials/toast.html", type=type, message=message)


def htmx_oob_toast(type: str, message: str) -> str:
    """Retourne un toast OOB (out-of-band) pour HTMX.
    À combiner avec une réponse principale (ex: suppression de ligne).
    Le toast s'injecte dans #toast-zone sans remplacer la cible principale.
    """
    return render_template("_partials/oob_toast.html", type=type, message=message)


def htmx_redirect(url: str):
    """Retourne une réponse HTMX qui déclenche une navigation client vers url."""
    resp = make_response("", 200)
    resp.headers["HX-Redirect"] = url
    return resp


def flash_or_toast(kind: str, message: str, redirect_endpoint: str, **redirect_kwargs):
    """Remplace le pattern répété `if is_htmx(): toast ... else: flash + redirect`.
    En HTMX, retourne un toast fragment. Sinon, flash le message puis redirige
    vers redirect_endpoint (nom de route Flask, via url_for)."""
    if is_htmx():
        return htmx_toast(kind, message)
    flash(message, kind)
    return redirect(url_for(redirect_endpoint, **redirect_kwargs))


def admin_required(f):
    """Redirige vers /login si l'utilisateur n'est pas authentifié ou n'est pas admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required_json(f):
    """Retourne 403 JSON si l'utilisateur n'est pas authentifié ou n'est pas admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        return f(*args, **kwargs)
    return decorated


def superadmin_required(f):
    """Redirige vers /server si l'utilisateur n'est pas superadmin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            return redirect(url_for("admin.server"))
        return f(*args, **kwargs)
    return decorated


def superadmin_required_json(f):
    """Retourne 403 JSON si l'utilisateur n'est pas superadmin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            return jsonify({"ok": False, "error": "forbidden"}), 403
        return f(*args, **kwargs)
    return decorated
