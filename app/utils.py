"""Utilitaires partagés entre les blueprints (décorateurs d'auth, etc.)."""
from functools import wraps

from flask import redirect, url_for, jsonify
from flask_login import current_user


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
