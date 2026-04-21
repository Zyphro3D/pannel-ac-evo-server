from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required
from app.models import AdminUser

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        role = AdminUser.check_credentials(username, password)
        if role:
            login_user(AdminUser(role=role))
            return redirect(url_for("admin.dashboard"))
        flash("invalid_credentials", "error")
    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/lang/<lang>")
def set_language(lang):
    from config import Config
    if lang in Config.BABEL_SUPPORTED_LOCALES:
        session["lang"] = lang
    return redirect(request.referrer or url_for("admin.dashboard"))
