import hashlib
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_babel import _
from flask_login import login_user, logout_user, login_required, current_user
from app.models import AdminAccount, Driver
from app.services.database import db
from app import limiter

auth_bp = Blueprint("auth", __name__)
log = logging.getLogger(__name__)

# ── Brute-force protection ────────────────────────────────────────────────────
_BF_LOCK      = threading.Lock()
_bf_state: dict[str, dict] = {}   # ip → {count, locked_until}
_BF_MAX       = 5                  # tentatives avant blocage
_BF_WINDOW    = 300                # fenêtre de comptage (5 min)
_BF_LOCKOUT   = 15 * 60           # durée de blocage (15 min)

def _bf_check(ip: str) -> int:
    """Retourne le nombre de secondes restantes de blocage, 0 si libre."""
    with _BF_LOCK:
        e = _bf_state.get(ip)
        if not e:
            return 0
        if e.get("locked_until") and time.time() < e["locked_until"]:
            return int(e["locked_until"] - time.time())
        if time.time() - e.get("first_at", 0) > _BF_WINDOW:
            _bf_state.pop(ip, None)
        return 0

def _bf_fail(ip: str) -> None:
    with _BF_LOCK:
        now = time.time()
        e = _bf_state.get(ip, {"count": 0, "first_at": now})
        if now - e.get("first_at", now) > _BF_WINDOW:
            e = {"count": 0, "first_at": now}
        e["count"] += 1
        if e["count"] >= _BF_MAX:
            e["locked_until"] = now + _BF_LOCKOUT
            log.warning("auth: IP %s bloquée après %d tentatives échouées", ip, e["count"])
        _bf_state[ip] = e

def _bf_ok(ip: str) -> None:
    with _BF_LOCK:
        _bf_state.pop(ip, None)

_PWD_MIN_LEN = 10


def _validate_password(pwd: str) -> list[str]:
    errors = []
    if len(pwd) < _PWD_MIN_LEN:
        errors.append(_("Le mot de passe doit contenir au moins 10 caractères."))
    if not re.search(r"[A-Z]", pwd):
        errors.append(_("Le mot de passe doit contenir au moins une majuscule."))
    if not re.search(r"[a-z]", pwd):
        errors.append(_("Le mot de passe doit contenir au moins une minuscule."))
    if not re.search(r"\d", pwd):
        errors.append(_("Le mot de passe doit contenir au moins un chiffre."))
    if not re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/\\`~]", pwd):
        errors.append(_("Le mot de passe doit contenir au moins un caractère spécial."))
    return errors


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 40 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("public.pilot_dashboard") if current_user.is_pilot else url_for("admin.dashboard"))

    if request.method == "POST":
        ip        = request.remote_addr or "unknown"
        remaining = _bf_check(ip)
        if remaining:
            mins = max(1, remaining // 60)
            flash(_("Trop de tentatives. Réessayez dans %(min)d minute(s).", min=mins), "error")
            return render_template("login.html")

        identifier = request.form.get("username", "").strip()
        password   = request.form.get("password", "")

        account = AdminAccount.query.filter_by(username=identifier, is_active=True).first()
        if account and account.check_password(password):
            _bf_ok(ip)
            account.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.commit()
            login_user(account)
            return redirect(url_for("admin.dashboard"))

        driver = (Driver.query.filter_by(email=identifier.lower()).first()
                  or Driver.query.filter_by(ingame_name=identifier).first())
        if driver and driver.check_password(password):
            if driver.status == "pending":
                flash(_("Votre compte est en attente de validation."), "warning")
            elif driver.status == "rejected":
                flash(_("Votre compte a été refusé."), "error")
            else:
                _bf_ok(ip)
                login_user(driver)
                return redirect(url_for("public.pilot_dashboard"))
            return render_template("login.html")

        _bf_fail(ip)
        log.warning("auth: échec connexion pour '%s' depuis %s", identifier, ip)
        flash(_("Identifiants incorrects."), "error")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.index"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("3 per minute", methods=["POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    if request.method == "POST":
        started = time.monotonic()
        identifier = request.form.get("identifier", "").strip()
        driver = (Driver.query.filter_by(email=identifier.lower()).first()
                  or Driver.query.filter_by(ingame_name=identifier).first())

        # Même message qu'il existe ou non (sécurité anti-énumération)
        flash(_("Un email de réinitialisation a été envoyé si le compte existe."), "success")

        if driver and driver.status == "approved":
            token      = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            driver.reset_token         = token_hash
            driver.reset_token_expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
            db.session.commit()
            from app.services import mailer
            mailer.send_password_reset(driver, token)

        elapsed = time.monotonic() - started
        if elapsed < 0.35:
            time.sleep(0.35 - elapsed)

        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    driver = Driver.query.filter_by(reset_token=token_hash).first()
    if not driver or not driver.reset_token_expires or driver.reset_token_expires < datetime.now(timezone.utc).replace(tzinfo=None):
        flash(_("Ce lien est invalide ou a expiré."), "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        pwd  = request.form.get("password", "")
        conf = request.form.get("confirm", "")
        errors = _validate_password(pwd)
        if pwd != conf:
            errors.append(_("Les mots de passe ne correspondent pas."))

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("reset_password.html", token=token)

        driver.set_password(pwd)
        driver.reset_token         = None
        driver.reset_token_expires = None
        db.session.commit()
        flash(_("Mot de passe mis à jour. Vous pouvez vous connecter."), "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)


@auth_bp.route("/lang/<lang>")
def set_language(lang):
    from config import Config
    if lang in Config.BABEL_SUPPORTED_LOCALES:
        session["lang"] = lang
    return redirect(request.referrer or url_for("public.index"))
