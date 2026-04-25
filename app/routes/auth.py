import re
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_babel import _
from flask_login import login_user, logout_user, login_required, current_user
from app.models import AdminUser, Driver
from app.services.database import db

auth_bp = Blueprint("auth", __name__)

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
def login():
    if current_user.is_authenticated:
        return redirect(url_for("public.pilot_dashboard") if current_user.is_pilot else url_for("admin.dashboard"))

    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password   = request.form.get("password", "")

        role = AdminUser.check_credentials(identifier, password)
        if role:
            login_user(AdminUser(role=role))
            return redirect(url_for("admin.dashboard"))

        driver = (Driver.query.filter_by(email=identifier.lower()).first()
                  or Driver.query.filter_by(ingame_name=identifier).first())
        if driver and driver.check_password(password):
            if driver.status == "pending":
                flash("pending", "error")
            elif driver.status == "rejected":
                flash("rejected", "error")
            else:
                login_user(driver)
                return redirect(url_for("public.pilot_dashboard"))
            return render_template("login.html")

        flash("invalid_credentials", "error")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("public.index"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        driver = (Driver.query.filter_by(email=identifier.lower()).first()
                  or Driver.query.filter_by(ingame_name=identifier).first())

        # Même message qu'il existe ou non (sécurité anti-énumération)
        flash(_("Un email de réinitialisation a été envoyé si le compte existe."), "success")

        if driver and driver.status == "approved":
            token = secrets.token_urlsafe(32)
            driver.reset_token         = token
            driver.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            from app.services import mailer
            mailer.send_password_reset(driver, token)

        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("public.index"))

    driver = Driver.query.filter_by(reset_token=token).first()
    if not driver or not driver.reset_token_expires or driver.reset_token_expires < datetime.utcnow():
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
