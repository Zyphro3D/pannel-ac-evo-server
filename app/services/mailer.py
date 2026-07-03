import html as _html
import smtplib
import socket
import threading
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from flask_babel import lazy_gettext as _l

_e = _html.escape  # short alias for escaping user-supplied data in HTML emails

log = logging.getLogger(__name__)

_cfg: dict = {}


def init(config):
    global _cfg
    panel_url = config.get("PANEL_URL", "http://localhost:4300")
    logo_img  = config.get("PANEL_LOGO_IMG", "")
    _cfg = {
        "server":      config.get("MAIL_SERVER",   ""),
        "port":        config.get("MAIL_PORT",     587),
        "use_tls":     config.get("MAIL_USE_TLS",  True),
        "username":    config.get("MAIL_USERNAME", ""),
        "password":    config.get("MAIL_PASSWORD", ""),
        "from":        config.get("MAIL_FROM",     ""),
        "admin":       [a.strip() for a in config.get("MAIL_ADMIN", "").split(",") if a.strip()],
        "panel_url":   panel_url,
        "panel_title": config.get("PANEL_TITLE", "AC EVO Panel"),
        "logo_url":    f"{panel_url}/media/banner/{logo_img}" if logo_img else "",
        "hero_url":    f"{panel_url}/static/mail/hero.png",
        "icon_base":   f"{panel_url}/static/mail/icons",
    }


_ACCENT = "#e03535"
_BG     = "#0d0d10"
_CARD   = "#141417"
_BORDER = "#232326"
_MUTED  = "#8b8b93"
_FONT   = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def _icon_url(name: str) -> str:
    return f"{_cfg['icon_base']}/{name}.png"


def _button(url: str, label: str) -> str:
    return (
        f'<a href="{_e(url)}" '
        f'style="display:inline-block;background:{_ACCENT};color:#ffffff;font-family:{_FONT};'
        f'font-size:15px;font-weight:700;text-decoration:none;padding:14px 34px;border-radius:8px;">'
        f'{_e(label)} &rarr;</a>'
    )


def _features_row(features: list[tuple[str, str, str]]) -> str:
    if not features:
        return ""
    cell_w = 100 // len(features)
    cells = "".join(f"""
        <td width="{cell_w}%" align="center" valign="top" style="padding:10px 12px;">
          <img src="{_e(_icon_url(icon))}" width="34" height="34" alt="" style="display:block;margin:0 auto;">
          <div style="color:#ffffff;font-family:{_FONT};font-size:12.5px;font-weight:700;
                      letter-spacing:.03em;text-transform:uppercase;margin-top:12px;">{_e(title)}</div>
          <div style="color:{_MUTED};font-family:{_FONT};font-size:12px;line-height:1.5;margin-top:5px;">{_e(desc)}</div>
        </td>"""
        for icon, title, desc in features
    )
    return f"""
        <tr>
          <td style="padding:22px 20px;background:{_BG};border-top:1px solid {_BORDER};border-bottom:1px solid {_BORDER};">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>
          </td>
        </tr>"""


def _layout(*, eyebrow: str, headline1: str, headline2: str, body_html: str,
            features: list[tuple[str, str, str]] | None = None,
            cta_url: str | None = None, cta_label: str | None = None) -> str:
    title = _cfg.get("panel_title", "AC EVO Panel")
    hero  = _cfg.get("hero_url", "")

    cta_block = ""
    if cta_url and cta_label:
        cta_block = f"""
        <tr>
          <td align="center" style="padding:30px 24px;background:{_CARD};">
            {_button(cta_url, cta_label)}
            <div style="margin-top:16px;color:{_MUTED};font-family:{_FONT};font-size:12px;">
              ou copiez ce lien dans votre navigateur&nbsp;:<br>
              <a href="{_e(cta_url)}" style="color:{_ACCENT};word-break:break-all;">{_e(cta_url)}</a>
            </div>
          </td>
        </tr>"""

    return f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:{_CARD};border-radius:16px;overflow:hidden;border:1px solid {_BORDER};">

        <tr>
          <td style="padding:20px 28px;background:{_BG};border-bottom:1px solid {_BORDER};">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
              <td style="color:#ffffff;font-family:{_FONT};font-size:17px;font-weight:800;letter-spacing:.02em;">{_e(title)}</td>
              <td align="right" style="color:{_MUTED};font-family:{_FONT};font-size:12.5px;">{_e(eyebrow)}</td>
            </tr></table>
          </td>
        </tr>

        <tr>
          <td background="{_e(hero)}" bgcolor="{_BG}"
              style="padding:52px 32px;background-image:url('{_e(hero)}');background-size:cover;background-position:center;background-repeat:no-repeat;">
            <!--[if mso]>
            <v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" style="width:600px;">
            <v:fill type="frame" src="{_e(hero)}" color="{_BG}" />
            <v:textbox inset="0,0,0,0">
            <![endif]-->
            <div style="width:38px;height:3px;background:{_ACCENT};margin:0 0 16px;"></div>
            <div style="color:#ffffff;font-family:{_FONT};font-size:24px;font-weight:800;line-height:1.2;text-transform:uppercase;text-shadow:0 1px 6px rgba(0,0,0,.6);">{_e(headline1)}</div>
            <div style="color:{_ACCENT};font-family:{_FONT};font-size:24px;font-weight:800;line-height:1.2;text-transform:uppercase;margin-bottom:16px;text-shadow:0 1px 6px rgba(0,0,0,.6);">{_e(headline2)}</div>
            <div style="color:#f1f1f3;font-family:{_FONT};font-size:14.5px;line-height:1.6;text-shadow:0 1px 4px rgba(0,0,0,.7);max-width:340px;">
              {body_html}
            </div>
            <!--[if mso]>
            </v:textbox>
            </v:rect>
            <![endif]-->
          </td>
        </tr>
{_features_row(features or [])}
{cta_block}

        <tr>
          <td style="padding:18px 28px;background:{_BG};border-top:1px solid {_BORDER};
                     color:{_MUTED};font-family:{_FONT};font-size:11.5px;line-height:1.5;">
            {_e(title)} &mdash; cet email a &eacute;t&eacute; envoy&eacute; automatiquement, merci de ne pas y r&eacute;pondre.
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
"""


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
        with smtplib.SMTP_SSL(_cfg["server"], port, timeout=20) as smtp:
            smtp.login(_cfg["username"], _cfg["password"])
            smtp.sendmail(msg["From"], [to], msg.as_string())
    else:
        with smtplib.SMTP(_cfg["server"], port, timeout=20) as smtp:
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


def _html_test() -> str:
    return _layout(
        eyebrow="Test SMTP",
        headline1="EMAIL DE",
        headline2="TEST",
        body_html="<p style=\"margin:0\">Configuration SMTP fonctionnelle. Cet email a été envoyé depuis le panel.</p>",
    )


def send_test(to: str) -> dict:
    """Envoi synchrone pour le bouton de test — retourne {"ok": bool, "error": str|None}."""
    if not _cfg.get("server") or not _cfg.get("username"):
        return {"ok": False, "error": "MAIL_SERVER ou MAIL_USERNAME non configuré dans .env"}
    try:
        msg = _build_msg(to, "[ACE EVO] Email de test", _html_test())
        _smtp_send(msg, to)
        return {"ok": True, "to": to}
    except (smtplib.SMTPException, socket.timeout, OSError) as e:
        return {"ok": False, "error": str(e)}


def _html_new_registration(driver) -> str:
    url  = f"{_cfg['panel_url']}/drivers"
    date = driver.created_at.strftime("%d/%m/%Y %H:%M")
    body = f"""
<p style="margin:0 0 10px">Un nouveau pilote attend une validation&nbsp;:</p>
<p style="margin:0"><strong>{_e(driver.ingame_name)}</strong><br>
{_e(driver.email)}<br>
{date} UTC</p>
"""
    return _layout(
        eyebrow="Notification admin",
        headline1="NOUVEAU",
        headline2="PILOTE",
        body_html=body,
        features=[("icon-user-plus", "Nouvelle demande", "Compte en attente de validation admin")],
        cta_url=url, cta_label="Voir les pilotes en attente",
    )


def send_new_registration(driver):
    admins = _cfg.get("admin", [])
    if not admins:
        return
    html    = _html_new_registration(driver)
    subject = f"[ACE EVO] Nouvelle inscription — {driver.ingame_name}"
    for admin in admins:
        _send(admin, subject, html)


def _html_registration_received(driver) -> str:
    body = f"""
<p style="margin:0 0 10px">Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p style="margin:0">Votre demande d'inscription a bien été reçue. Un administrateur va examiner votre compte et vous recevrez un email dès qu'il sera validé.</p>
"""
    return _layout(
        eyebrow="Inscription",
        headline1="DEMANDE",
        headline2="REÇUE",
        body_html=body,
        features=[("icon-clock", "En attente", "Validation par un administrateur")],
    )


def send_registration_received(driver):
    _send(driver.email, "[ACE EVO] Demande d'inscription reçue", _html_registration_received(driver))


def _html_registration_approved(driver) -> str:
    url  = f"{_cfg['panel_url']}/login"
    body = f"""
<p style="margin:0 0 10px">Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p style="margin:0">Votre compte pilote a été validé. Vous pouvez dès maintenant vous connecter et vous inscrire aux événements.</p>
"""
    return _layout(
        eyebrow="Bienvenue dans la communauté",
        headline1="INSCRIPTION",
        headline2="CONFIRMÉE",
        body_html=body,
        features=[
            ("icon-users",  "Compte créé",    "Votre compte est désormais actif et prêt à l'emploi"),
            ("icon-flag",   "Accès complet",  "Vous avez accès à toutes les fonctionnalités du panel"),
            ("icon-trophy", "Prêt à rouler",  "Rejoignez les sessions et affrontez la communauté !"),
        ],
        cta_url=url, cta_label="Accéder au panel",
    )


def send_registration_approved(driver):
    _send(driver.email, "[ACE EVO] Compte validé — Bienvenue !", _html_registration_approved(driver))


def _html_registration_rejected(driver) -> str:
    body = f"""
<p style="margin:0 0 10px">Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p style="margin:0">Votre demande d'inscription a été refusée. Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur.</p>
"""
    return _layout(
        eyebrow="Inscription",
        headline1="DEMANDE",
        headline2="REFUSÉE",
        body_html=body,
        features=[("icon-x-circle", "Non validée", "Contactez l'administrateur pour plus d'informations")],
    )


def send_registration_rejected(driver):
    _send(driver.email, "[ACE EVO] Inscription refusée", _html_registration_rejected(driver))


def _html_event_registration_confirmed(driver, event) -> str:
    date_str = event.date.strftime("%d/%m/%Y à %H:%M") + " UTC"
    url = _cfg["panel_url"]
    body = f"""
<p style="margin:0 0 10px">Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p style="margin:0 0 10px">Votre inscription à <strong>{_e(event.title)}</strong> a été confirmée&nbsp;!</p>
<p style="margin:0">{date_str}<br>{_e(event.circuit_display or event.circuit or "—")} &middot; {_e(event.mode_display)}</p>
"""
    return _layout(
        eyebrow="Événement",
        headline1="INSCRIPTION",
        headline2="CONFIRMÉE",
        body_html=body,
        features=[("icon-flag", "C'est parti", "Votre place est réservée pour cet événement")],
        cta_url=url, cta_label="Accéder au panel",
    )


def send_event_registration_confirmed(driver, event):
    html = _html_event_registration_confirmed(driver, event)
    _send(driver.email, f"[ACE EVO] Inscription confirmée — {event.title}", html)


def _html_event_registration_rejected(driver, event) -> str:
    body = f"""
<p style="margin:0 0 10px">Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p style="margin:0">Votre inscription à <strong>{_e(event.title)}</strong> a été refusée. Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur.</p>
"""
    return _layout(
        eyebrow="Événement",
        headline1="INSCRIPTION",
        headline2="REFUSÉE",
        body_html=body,
        features=[("icon-x-circle", "Non retenue", "Contactez l'administrateur pour plus d'informations")],
    )


def send_event_registration_rejected(driver, event):
    html = _html_event_registration_rejected(driver, event)
    _send(driver.email, f"[ACE EVO] Inscription refusée — {event.title}", html)


def _html_email_confirmation(driver, token: str) -> str:
    url  = f"{_cfg['panel_url']}/confirm-email/{token}"
    body = f"""
<p style="margin:0 0 10px">Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p style="margin:0">Merci de confirmer votre adresse email pour pouvoir vous inscrire aux événements. Ce lien est valable 48 heures.</p>
"""
    return _layout(
        eyebrow="Sécurité du compte",
        headline1="CONFIRMEZ",
        headline2="VOTRE EMAIL",
        body_html=body,
        features=[("icon-mail-check", "Une étape rapide", "Cliquez sur le bouton ci-dessous pour confirmer")],
        cta_url=url, cta_label="Confirmer mon email",
    )


def send_email_confirmation(driver, token: str):
    _send(driver.email, "[ACE EVO] Confirmez votre email", _html_email_confirmation(driver, token))


def _html_password_reset(driver, token: str) -> str:
    url  = f"{_cfg['panel_url']}/reset-password/{token}"
    body = f"""
<p style="margin:0 0 10px">Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p style="margin:0">Une demande de réinitialisation de mot de passe a été effectuée pour votre compte. Ce lien est valable 1 heure. Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.</p>
"""
    return _layout(
        eyebrow="Sécurité du compte",
        headline1="RÉINITIALISATION",
        headline2="MOT DE PASSE",
        body_html=body,
        features=[("icon-key", "Lien à usage unique", "Valable 1 heure, ignorez si non demandé")],
        cta_url=url, cta_label="Réinitialiser mon mot de passe",
    )


def send_password_reset(driver, token: str):
    _send(driver.email, "[ACE EVO] Réinitialisation de mot de passe", _html_password_reset(driver, token))


def _html_event_reminder(driver, event, registration) -> str:
    date_str = event.date.strftime("%d/%m/%Y à %H:%M") + " UTC"
    car_info = registration.car_display or registration.assigned_car or "Non assignée"
    pwd_line = f"<br>Mot de passe serveur&nbsp;: <strong>{_e(event.password)}</strong>" if event.password else ""
    url  = _cfg["panel_url"]
    body = f"""
<p style="margin:0 0 10px">Bonjour <strong>{_e(driver.ingame_name)}</strong>,</p>
<p style="margin:0 0 10px"><strong>{_e(event.title)}</strong> commence bientôt&nbsp;!</p>
<p style="margin:0">{date_str}<br>{_e(event.circuit_display or event.circuit)} &middot; {_e(event.mode_display)} &middot; {_e(event.weather_display)}<br>
Voiture assignée&nbsp;: <strong>{_e(car_info)}</strong>{pwd_line}</p>
"""
    return _layout(
        eyebrow="Rappel événement",
        headline1="ÇA COMMENCE",
        headline2="BIENTÔT",
        body_html=body,
        features=[("icon-bell", "Ne manquez pas le départ", "Retrouvez tous les détails sur le panel")],
        cta_url=url, cta_label="Accéder au panel",
    )


def send_event_reminder(driver, event, registration):
    html = _html_event_reminder(driver, event, registration)
    _send(driver.email, f"[ACE EVO] Rappel — {event.title} commence bientôt", html)


# ── Prévisualisation admin (aucun envoi réel, données factices) ──────────────

def _preview_dummies():
    from types import SimpleNamespace
    from datetime import timedelta
    driver = SimpleNamespace(
        ingame_name="Zyphro",
        email="zyphro@exemple.fr",
        created_at=datetime.utcnow(),
    )
    event = SimpleNamespace(
        title="Course du vendredi soir",
        date=datetime.utcnow() + timedelta(days=3),
        circuit_display="Spa-Francorchamps",
        circuit="circuit_de_spa_francorchamps",
        mode_display="Course",
        weather_display="Ensoleillé",
        password="",
    )
    registration = SimpleNamespace(car_display="Ferrari 296 GT3", assigned_car=None)
    return driver, event, registration


PREVIEW_TYPES = [
    ("test",                          _l("Email de test")),
    ("new_registration",              _l("Nouvelle inscription (notif. admin)")),
    ("registration_received",         _l("Inscription reçue")),
    ("registration_approved",         _l("Compte validé")),
    ("registration_rejected",         _l("Inscription refusée")),
    ("event_registration_confirmed",  _l("Inscription événement confirmée")),
    ("event_registration_rejected",   _l("Inscription événement refusée")),
    ("email_confirmation",            _l("Confirmation d'email")),
    ("password_reset",                _l("Réinitialisation mot de passe")),
    ("event_reminder",                _l("Rappel événement")),
]


def render_preview(key: str) -> str | None:
    """Rend le HTML d'un type d'email avec des données factices, pour prévisualisation admin."""
    driver, event, registration = _preview_dummies()
    builders = {
        "test":                         lambda: _html_test(),
        "new_registration":             lambda: _html_new_registration(driver),
        "registration_received":        lambda: _html_registration_received(driver),
        "registration_approved":        lambda: _html_registration_approved(driver),
        "registration_rejected":        lambda: _html_registration_rejected(driver),
        "event_registration_confirmed": lambda: _html_event_registration_confirmed(driver, event),
        "event_registration_rejected":  lambda: _html_event_registration_rejected(driver, event),
        "email_confirmation":           lambda: _html_email_confirmation(driver, "apercu-token"),
        "password_reset":               lambda: _html_password_reset(driver, "apercu-token"),
        "event_reminder":               lambda: _html_event_reminder(driver, event, registration),
    }
    builder = builders.get(key)
    return builder() if builder else None
