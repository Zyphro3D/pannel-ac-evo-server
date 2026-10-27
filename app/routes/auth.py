import hashlib
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session
from flask_babel import _
from flask_login import login_user, logout_user, login_required, current_user
from app.models import AdminAccount, Driver, DriverStatus
from app.services.netutil import client_ip
from app.services import audit, totp
from app.services.database import db
from app import limiter

auth_bp = Blueprint("auth", __name__)
log = logging.getLogger(__name__)


def _steam_owner_redirect():
    return url_for("public.pilot_dashboard") if current_user.is_pilot else url_for("admin.my_account")

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


def _login(user) -> None:
    """login_user après avoir enregistré le jeton de session : il doit être en base avant que le
    cookie ne le porte (comptes antérieurs au jeton, compte promu pilote → admin)."""
    if not user.session_token:
        user.rotate_session()
    db.session.commit()
    login_user(user)

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
        return redirect(url_for("public.pilot_dashboard") if current_user.is_pilot else url_for("admin.server"))

    if request.method == "POST":
        ip        = client_ip()
        remaining = _bf_check(ip)
        if remaining:
            mins = max(1, remaining // 60)
            flash(_("Trop de tentatives. Réessayez dans %(min)d minute(s).", min=mins), "error")
            return render_template("login.html")

        identifier = request.form.get("username", "").strip()
        password   = request.form.get("password", "")

        account = (AdminAccount.query.filter_by(username=identifier, is_active=True).first()
                   or AdminAccount.query.filter_by(email=identifier.lower(), is_active=True).first())
        if account and account.check_password(password):
            _bf_ok(ip)
            if account.totp_enabled:
                # Deuxième facteur : le mot de passe seul ne suffit plus, on ne connecte pas encore.
                session.clear()
                session["pending_2fa"] = {"uid": account.id, "ts": time.time(), "tries": 0}
                audit.record("login.password_ok_2fa_pending", target=account.username, actor=account.username,
                             role="superadmin" if account.is_superadmin else "admin")
                return redirect(url_for("auth.login_2fa"))
            account.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            _login(account)
            audit.record("login.ok", target=account.username, actor=account.username,
                         role="superadmin" if account.is_superadmin else "admin")
            return redirect(url_for("admin.server"))

        driver = (Driver.query.filter_by(email=identifier.lower()).first()
                  or Driver.query.filter_by(ingame_name=identifier).first())
        if driver and driver.check_password(password):
            if driver.status == DriverStatus.PENDING:
                flash(_("Votre compte est en attente de validation."), "warning")
            elif driver.status == DriverStatus.REJECTED:
                flash(_("Votre compte a été refusé."), "error")
            else:
                _bf_ok(ip)
                _login(driver)
                return redirect(url_for("public.pilot_dashboard"))
            return render_template("login.html")

        _bf_fail(ip)
        # Le champ « identifiant » reçoit parfois un mot de passe tapé par erreur : on ne le journalise que
        # s'il correspond à un compte existant.
        audit.record("login.fail", target=identifier if account or driver else "(compte inconnu)", ok=False,
                     actor=identifier if account or driver else "")
        log.warning("auth: échec connexion pour '%s' depuis %s", identifier, ip)
        flash(_("Identifiants incorrects."), "error")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    audit.record("logout")
    # Nouveau jeton : le cookie courant et toute copie (autre appareil, cookie volé) tombent.
    current_user.rotate_session()
    db.session.commit()
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

        if driver and driver.status == DriverStatus.APPROVED:
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


@auth_bp.route("/pilot/steam/link")
@login_required
@limiter.limit("10 per minute")
def steam_link():
    from app.services.steam_openid import build_auth_url
    # État aléatoire lié à cette session : le retour de Steam n'est accepté que s'il le porte.
    state = secrets.token_urlsafe(24)
    session["steam_link_state"] = state
    realm     = request.url_root
    return_to = url_for("auth.steam_callback", state=state, _external=True)
    return redirect(build_auth_url(return_to, realm))


@auth_bp.route("/pilot/steam/callback")
@login_required
@limiter.limit("10 per minute")
def steam_callback():
    from app.services.steam_openid import verify_callback
    state = session.pop("steam_link_state", None)
    steam_id = None
    if state and secrets.compare_digest(state, request.args.get("state", "")):
        steam_id = verify_callback(request.args, url_for("auth.steam_callback", state=state, _external=True))
    if not steam_id:
        flash(_("Impossible de vérifier votre compte Steam. Réessayez."), "error")
        return redirect(_steam_owner_redirect())

    is_driver_conflict = Driver.query.filter(
        Driver.steam_id == steam_id, Driver.id != (current_user.id if current_user.is_pilot else -1)
    ).first()
    is_admin_conflict = AdminAccount.query.filter(
        AdminAccount.steam_id == steam_id, AdminAccount.id != (current_user.id if current_user.is_admin else -1)
    ).first()
    if is_driver_conflict or is_admin_conflict:
        flash(_("Ce compte Steam est déjà lié à un autre pilote."), "error")
        return redirect(_steam_owner_redirect())

    current_user.steam_id = steam_id
    current_user.steam_id_confirmed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    flash(_("Compte Steam confirmé avec succès."), "success")
    return redirect(_steam_owner_redirect())


@auth_bp.route("/pilot/steam/unlink", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def steam_unlink():
    current_user.steam_id = None
    current_user.steam_id_confirmed_at = None
    db.session.commit()
    flash(_("Compte Steam délié."), "success")
    return redirect(_steam_owner_redirect())


@auth_bp.route("/lang/<lang>")
def set_language(lang):
    from config import Config
    from urllib.parse import urlparse
    if lang in Config.BABEL_SUPPORTED_LOCALES:
        session["lang"] = lang
    referrer = request.referrer
    if referrer and urlparse(referrer).netloc == urlparse(request.url).netloc:
        return redirect(referrer)
    return redirect(url_for("public.index"))


# ── Deuxième facteur (TOTP) ───────────────────────────────────────────────────

_2FA_TTL   = 300        # le mot de passe a été validé il y a moins de 5 minutes
_2FA_TRIES = 5


def _clear_pending():
    session.pop("pending_2fa", None)


@auth_bp.route("/login/2fa", methods=["GET", "POST"])
@limiter.limit("10 per minute; 40 per hour", methods=["POST"])
def login_2fa():
    pend = session.get("pending_2fa")
    account = db.session.get(AdminAccount, pend["uid"]) if pend else None
    if not pend or not account or not account.totp_enabled or time.time() - pend["ts"] > _2FA_TTL:
        _clear_pending()
        flash(_("Session de vérification expirée, reconnectez-vous."), "error")
        return redirect(url_for("auth.login"))

    # Compteur d'essais côté serveur, par compte : celui du cookie (pend["tries"]) se remet à zéro
    # en rejouant un ancien cookie.
    bf_key = f"2fa:{account.id}"
    if request.method == "POST" and _bf_check(bf_key):
        _clear_pending()
        flash(_("Trop d'essais. Réessayez dans quelques minutes."), "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        role = "superadmin" if account.is_superadmin else "admin"
        ok = False
        used_recovery = False
        step = totp.verify(account.totp_secret or "", code, account.totp_last_step or 0)
        if step is not None:
            account.totp_last_step = step
            ok = True
        elif len(code.replace("-", "").replace(" ", "")) >= 8:
            remaining = totp.consume_recovery(account.totp_recovery or "", code,
                                              current_app.config["SECRET_KEY"])
            if remaining is not None:
                account.totp_recovery = remaining
                ok = used_recovery = True
        if ok:
            account.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            _clear_pending()
            _bf_ok(bf_key)
            _login(account)
            audit.record("login.ok", target=account.username, actor=account.username, role=role,
                         detail={"2fa": "recovery" if used_recovery else "totp"})
            if used_recovery:
                left = totp.recovery_left(account.totp_recovery)
                flash(_("Code de secours utilisé : il vous en reste %(n)s.", n=left), "warning")
            return redirect(url_for("admin.server"))
        _bf_fail(bf_key)
        pend["tries"] = pend.get("tries", 0) + 1
        session["pending_2fa"] = pend
        audit.record("login.2fa_fail", target=account.username, ok=False, actor=account.username, role=role)
        if pend["tries"] >= _2FA_TRIES:
            _clear_pending()
            flash(_("Trop d'essais. Reconnectez-vous."), "error")
            return redirect(url_for("auth.login"))
        flash(_("Code incorrect."), "error")
    return render_template("login_2fa.html")
