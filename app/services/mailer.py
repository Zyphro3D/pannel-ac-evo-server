import html as _html
import smtplib
import socket
import threading
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

_e = _html.escape  # short alias for escaping user-supplied data in HTML emails

log = logging.getLogger(__name__)

_cfg: dict = {}


def init(config):
    global _cfg
    _cfg = {
        "server":    config.get("MAIL_SERVER",   ""),
        "port":      config.get("MAIL_PORT",     587),
        "use_tls":   config.get("MAIL_USE_TLS",  True),
        "username":  config.get("MAIL_USERNAME", ""),
        "password":  config.get("MAIL_PASSWORD", ""),
        "from":      config.get("MAIL_FROM",     ""),
        "admin":     [a.strip() for a in config.get("MAIL_ADMIN", "").split(",") if a.strip()],
        "panel_url": config.get("PANEL_URL",     "http://localhost:4300"),
    }


def _build_msg(to: str, subject: str, html: str, text: str = "") -> MIMEMultipart:
    from_addr = _cfg["from"] or _cfg["username"]
    domain    = from_addr.split("@")[-1] if "@" in from_addr else "localhost"

    msg = MIMEMultipart("alternative")
    msg["Subject"]    = subject
    msg["From"]       = from_addr
    msg["To"]         = to
    msg["Date"]       = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=domain)

    plain = text or _html_to_plain(html)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html,  "html",  "utf-8"))
    return msg


def _html_to_plain(html: str) -> str:
    import re
    txt = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = re.sub(r"&nbsp;", " ", txt)
    txt = re.sub(r"&amp;",  "&", txt)
    txt = re.sub(r"&lt;",   "<", txt)
    txt = re.sub(r"&gt;",   ">", txt)
    return txt.strip()


def _smtp_send(msg: MIMEMultipart, to: str):
    port = _cfg["port"]
    if port == 465:
        with smtplib.SMTP_SSL(_cfg["server"], port, timeout=8) as smtp:
            smtp.login(_cfg["username"], _cfg["password"])
            smtp.sendmail(msg["From"], [to], msg.as_string())
    else:
        with smtplib.SMTP(_cfg["server"], port, timeout=8) as smtp:
            if _cfg.get("use_tls"):
                smtp.starttls()
            smtp.login(_cfg["username"], _cfg["password"])
            smtp.sendmail(msg["From"], [to], msg.as_string())


def _send(to: str, subject: str, html: str):
    if not _cfg.get("server") or not _cfg.get("username"):
        log.debug("Mailer non configuré — email ignoré (%s)", subject)
        return

    def _worker():
        try:
            msg = _build_msg(to, subject, html)
            _smtp_send(msg, to)
            log.info("Email envoyé à %s — %s", to, subject)
        except (smtplib.SMTPException, socket.timeout, OSError):
            log.exception("Erreur envoi email à %s", to)

    threading.Thread(target=_worker, daemon=True).start()


def send_test(to: str) -> dict:
    """Envoi synchrone pour le bouton de test — retourne {"ok": bool, "error": str|None}."""
    if not _cfg.get("server") or not _cfg.get("username"):
        return {"ok": False, "error": "MAIL_SERVER ou MAIL_USERNAME non configuré dans .env"}
    try:
        html = "<p>Email de test envoyé depuis <strong>AC EVO Panel</strong>. La configuration SMTP fonctionne correctement.</p>"
        msg  = _build_msg(to, "[ACE EVO] Email de test", html)
        _smtp_send(msg, to)
        return {"ok": True, "to": to}
    except (smtplib.SMTPException, socket.timeout, OSError) as e:
        return {"ok": False, "error": str(e)}


def send_new_registration(driver):
    admins = _cfg.get("admin", [])
    if not admins:
        return
    url  = f"{_cfg['panel_url']}/drivers"
    date = driver.created_at.strftime("%d/%m/%Y %H:%M")
    html = f"""
<p>Un nouveau pilote s'est inscrit et attend validation&nbsp;:</p>
<ul>
  <li><strong>Nom in-game&nbsp;:</strong> {_e(driver.ingame_name)}</li>
  <li><strong>Email&nbsp;:</strong> {_e(driver.email)}</li>
  <li><strong>Inscrit le&nbsp;:</strong> {date} UTC</li>
</ul>
<p><a href="{_e(url)}">Voir les pilotes en attente</a></p>
"""
    subject = f"[ACE EVO] Nouvelle inscription — {driver.ingame_name}"
    for admin in admins:
        _send(admin, subject, html)


def send_registration_received(driver):
    html = f"""
<p>Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p>Votre demande d'inscription a bien été reçue. Un administrateur va examiner votre compte et vous recevrez un email de confirmation dès qu'il sera validé.</p>
<p style="color:#888;font-size:12px">Si vous n'êtes pas à l'origine de cette inscription, ignorez cet email.</p>
"""
    _send(driver.email, "[ACE EVO] Demande d'inscription reçue", html)


def send_registration_approved(driver):
    url  = f"{_cfg['panel_url']}/login"
    html = f"""
<p>Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p>Votre compte pilote a été <strong>validé</strong>. Vous pouvez maintenant vous connecter et vous inscrire aux événements.</p>
<p><a href="{_e(url)}">Se connecter</a></p>
"""
    _send(driver.email, "[ACE EVO] Compte validé — Bienvenue !", html)


def send_registration_rejected(driver):
    html = f"""
<p>Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p>Votre demande d'inscription a été <strong>refusée</strong>.</p>
<p>Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur.</p>
"""
    _send(driver.email, "[ACE EVO] Inscription refusée", html)


def send_event_registration_confirmed(driver, event):
    date_str = event.date.strftime("%d/%m/%Y à %H:%M") + " UTC"
    url = _cfg["panel_url"]
    html = f"""
<p>Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p>Votre inscription à l'événement <strong>{_e(event.title)}</strong> a été <strong>confirmée</strong>&nbsp;!</p>
<ul>
  <li><strong>Date&nbsp;:</strong> {date_str}</li>
  <li><strong>Circuit&nbsp;:</strong> {_e(event.circuit_display or event.circuit or "—")}</li>
  <li><strong>Mode&nbsp;:</strong> {_e(event.mode_display)}</li>
</ul>
<p><a href="{_e(url)}">Accéder au panel</a></p>
"""
    _send(driver.email, f"[ACE EVO] Inscription confirmée — {event.title}", html)


def send_event_registration_rejected(driver, event):
    html = f"""
<p>Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p>Votre inscription à l'événement <strong>{_e(event.title)}</strong> a été <strong>refusée</strong>.</p>
<p>Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur.</p>
"""
    _send(driver.email, f"[ACE EVO] Inscription refusée — {event.title}", html)


def send_password_reset(driver, token: str):
    url  = f"{_cfg['panel_url']}/reset-password/{token}"
    html = f"""
<p>Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p>Une demande de réinitialisation de mot de passe a été effectuée pour votre compte.</p>
<p><a href="{_e(url)}" style="background:#c0392b;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">Réinitialiser mon mot de passe</a></p>
<p style="color:#888;font-size:12px">Ce lien est valable <strong>1 heure</strong>. Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.</p>
<p style="color:#888;font-size:12px">Lien : {_e(url)}</p>
"""
    _send(driver.email, "[ACE EVO] Réinitialisation de mot de passe", html)


def send_event_reminder(driver, event, registration):
    date_str = event.date.strftime("%d/%m/%Y à %H:%M") + " UTC"
    car_info = registration.car_display or registration.assigned_car or "Non assignée"
    pwd_line = (
        f"<li><strong>Mot de passe serveur&nbsp;:</strong> <code>{_e(event.password)}</code></li>"
        if event.password else ""
    )
    url  = _cfg["panel_url"]
    html = f"""
<p>Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p>L'événement <strong>{_e(event.title)}</strong> commence bientôt&nbsp;!</p>
<ul>
  <li><strong>Date&nbsp;:</strong> {date_str}</li>
  <li><strong>Circuit&nbsp;:</strong> {_e(event.circuit_display or event.circuit)}</li>
  <li><strong>Mode&nbsp;:</strong> {_e(event.mode_display)}</li>
  <li><strong>Météo&nbsp;:</strong> {_e(event.weather_display)}</li>
  <li><strong>Voiture assignée&nbsp;:</strong> {_e(car_info)}</li>
  {pwd_line}
</ul>
<p><a href="{_e(url)}">Accéder au panel</a></p>
"""
    _send(driver.email, f"[ACE EVO] Rappel — {event.title} commence bientôt", html)
