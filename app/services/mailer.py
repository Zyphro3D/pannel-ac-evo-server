import html as _html
import os
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


# ── Templates éditables (eyebrow/titre/corps/CTA), stockés en settings ───────
# Même mécanisme que les DISCORD_MSG_* : os.environ.get() à l'appel, jamais
# à l'init, pour refléter les changements settings en direct.

def _tpl_key(type_key: str, field: str) -> str:
    return f"MAIL_TPL_{type_key.upper()}_{field.upper()}"


def _tmpl(key: str, default: str, **kwargs) -> str:
    """Résout un template court (eyebrow/titre/CTA) depuis les settings, avec variables.
    Une valeur vide est traitée comme non définie : restaure le texte par défaut."""
    tpl = os.environ.get(key, "").strip() or default
    try:
        return tpl.format(**kwargs)
    except (KeyError, ValueError):
        return tpl


def _tmpl_body(key: str, default: str, **kwargs) -> str:
    """Résout le corps d'un email : ligne(s) vide(s) = nouveau paragraphe, \\n simple = <br>."""
    text = _tmpl(key, default, **kwargs)
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paras:
        return ""
    parts = []
    for i, p in enumerate(paras):
        margin = "margin:0" if i == len(paras) - 1 else "margin:0 0 10px"
        parts.append(f'<p style="{margin}">{p.replace(chr(10), "<br>")}</p>')
    return "\n".join(parts)


# (type_key, label, variables disponibles dans le corps)
MAIL_TEMPLATE_FIELDS = [
    ("new_registration",             _l("Nouvelle inscription (notif. admin)"), ["name", "email", "date"]),
    ("registration_received",        _l("Inscription reçue"),                   ["name"]),
    ("registration_approved",        _l("Compte validé"),                       ["name"]),
    ("registration_rejected",        _l("Inscription refusée"),                 ["name"]),
    ("event_registration_confirmed", _l("Inscription événement confirmée"),     ["name", "event", "date", "circuit", "mode"]),
    ("event_registration_rejected",  _l("Inscription événement refusée"),       ["name", "event"]),
    ("email_confirmation",           _l("Confirmation d'email"),                ["name"]),
    ("password_reset",               _l("Réinitialisation mot de passe"),       ["name"]),
    ("event_reminder",               _l("Rappel événement"),                    ["name", "event", "date", "circuit", "mode", "weather", "car"]),
]

MAIL_TEMPLATE_DEFAULTS = {
    "new_registration": {
        "eyebrow": "Notification admin", "h1": "NOUVEAU", "h2": "PILOTE",
        "cta": "Voir les pilotes en attente",
        "body": "Un nouveau pilote attend une validation :\n\n{name}\n{email}\n{date} UTC",
    },
    "registration_received": {
        "eyebrow": "Inscription", "h1": "DEMANDE", "h2": "REÇUE",
        "body": "Bonjour {name},\n\nVotre demande d'inscription a bien été reçue. Un administrateur va examiner votre compte et vous recevrez un email dès qu'il sera validé.",
    },
    "registration_approved": {
        "eyebrow": "Bienvenue dans la communauté", "h1": "INSCRIPTION", "h2": "CONFIRMÉE",
        "cta": "Accéder au panel",
        "body": "Bonjour {name},\n\nVotre compte pilote a été validé. Vous pouvez dès maintenant vous connecter et vous inscrire aux événements.",
    },
    "registration_rejected": {
        "eyebrow": "Inscription", "h1": "DEMANDE", "h2": "REFUSÉE",
        "body": "Bonjour {name},\n\nVotre demande d'inscription a été refusée. Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur.",
    },
    "event_registration_confirmed": {
        "eyebrow": "Événement", "h1": "INSCRIPTION", "h2": "CONFIRMÉE",
        "cta": "Accéder au panel",
        "body": "Bonjour {name},\n\nVotre inscription à {event} a été confirmée !\n\n{date}\n{circuit} · {mode}",
    },
    "event_registration_rejected": {
        "eyebrow": "Événement", "h1": "INSCRIPTION", "h2": "REFUSÉE",
        "body": "Bonjour {name},\n\nVotre inscription à {event} a été refusée. Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur.",
    },
    "email_confirmation": {
        "eyebrow": "Sécurité du compte", "h1": "CONFIRMEZ", "h2": "VOTRE EMAIL",
        "cta": "Confirmer mon email",
        "body": "Bonjour {name},\n\nMerci de confirmer votre adresse email pour pouvoir vous inscrire aux événements. Ce lien est valable 48 heures.",
    },
    "password_reset": {
        "eyebrow": "Sécurité du compte", "h1": "RÉINITIALISATION", "h2": "MOT DE PASSE",
        "cta": "Réinitialiser mon mot de passe",
        "body": "Bonjour {name},\n\nUne demande de réinitialisation de mot de passe a été effectuée pour votre compte. Ce lien est valable 1 heure. Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.",
    },
    "event_reminder": {
        "eyebrow": "Rappel événement", "h1": "ÇA COMMENCE", "h2": "BIENTÔT",
        "cta": "Accéder au panel",
        "body": "Bonjour {name},\n\n{event} commence bientôt !\n\n{date}\n{circuit} · {mode} · {weather}\nVoiture assignée : {car}{password_line}",
    },
}


def _render_type(type_key: str, *, features=None, cta_url=None, **variables) -> str:
    """Construit le HTML d'un email éditable à partir de MAIL_TEMPLATE_DEFAULTS + settings."""
    d = MAIL_TEMPLATE_DEFAULTS[type_key]
    eyebrow = _tmpl(_tpl_key(type_key, "eyebrow"), d["eyebrow"])
    h1      = _tmpl(_tpl_key(type_key, "h1"), d["h1"])
    h2      = _tmpl(_tpl_key(type_key, "h2"), d["h2"])
    body    = _tmpl_body(_tpl_key(type_key, "body"), d["body"], **variables)
    cta_label = _tmpl(_tpl_key(type_key, "cta"), d["cta"]) if "cta" in d else None
    return _layout(eyebrow=eyebrow, headline1=h1, headline2=h2, body_html=body,
                   features=features, cta_url=cta_url if cta_label else None, cta_label=cta_label)


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
    return _render_type(
        "new_registration",
        features=[("icon-user-plus", "Nouvelle demande", "Compte en attente de validation admin")],
        cta_url=f"{_cfg['panel_url']}/drivers",
        name=_e(driver.ingame_name), email=_e(driver.email),
        date=driver.created_at.strftime("%d/%m/%Y %H:%M"),
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
    return _render_type(
        "registration_received",
        features=[("icon-clock", "En attente", "Validation par un administrateur")],
        name=_e(driver.ingame_name),
    )


def send_registration_received(driver):
    _send(driver.email, "[ACE EVO] Demande d'inscription reçue", _html_registration_received(driver))


def _html_registration_approved(driver) -> str:
    return _render_type(
        "registration_approved",
        features=[
            ("icon-users",  "Compte créé",    "Votre compte est désormais actif et prêt à l'emploi"),
            ("icon-flag",   "Accès complet",  "Vous avez accès à toutes les fonctionnalités du panel"),
            ("icon-trophy", "Prêt à rouler",  "Rejoignez les sessions et affrontez la communauté !"),
        ],
        cta_url=f"{_cfg['panel_url']}/login",
        name=_e(driver.ingame_name),
    )


def send_registration_approved(driver):
    _send(driver.email, "[ACE EVO] Compte validé — Bienvenue !", _html_registration_approved(driver))


def _html_registration_rejected(driver) -> str:
    return _render_type(
        "registration_rejected",
        features=[("icon-x-circle", "Non validée", "Contactez l'administrateur pour plus d'informations")],
        name=_e(driver.ingame_name),
    )


def send_registration_rejected(driver):
    _send(driver.email, "[ACE EVO] Inscription refusée", _html_registration_rejected(driver))


def _html_event_registration_confirmed(driver, event) -> str:
    date_str = event.date.strftime("%d/%m/%Y à %H:%M") + " UTC"
    return _render_type(
        "event_registration_confirmed",
        features=[("icon-flag", "C'est parti", "Votre place est réservée pour cet événement")],
        cta_url=_cfg["panel_url"],
        name=_e(driver.ingame_name), event=_e(event.title), date=date_str,
        circuit=_e(event.circuit_display or event.circuit or "—"), mode=_e(event.mode_display),
    )


def send_event_registration_confirmed(driver, event):
    html = _html_event_registration_confirmed(driver, event)
    _send(driver.email, f"[ACE EVO] Inscription confirmée — {event.title}", html)


def _html_event_registration_rejected(driver, event) -> str:
    return _render_type(
        "event_registration_rejected",
        features=[("icon-x-circle", "Non retenue", "Contactez l'administrateur pour plus d'informations")],
        name=_e(driver.ingame_name), event=_e(event.title),
    )


def send_event_registration_rejected(driver, event):
    html = _html_event_registration_rejected(driver, event)
    _send(driver.email, f"[ACE EVO] Inscription refusée — {event.title}", html)


def _html_email_confirmation(driver, token: str) -> str:
    return _render_type(
        "email_confirmation",
        features=[("icon-mail-check", "Une étape rapide", "Cliquez sur le bouton ci-dessous pour confirmer")],
        cta_url=f"{_cfg['panel_url']}/confirm-email/{token}",
        name=_e(driver.ingame_name),
    )


def send_email_confirmation(driver, token: str):
    _send(driver.email, "[ACE EVO] Confirmez votre email", _html_email_confirmation(driver, token))


def _html_password_reset(driver, token: str) -> str:
    return _render_type(
        "password_reset",
        features=[("icon-key", "Lien à usage unique", "Valable 1 heure, ignorez si non demandé")],
        cta_url=f"{_cfg['panel_url']}/reset-password/{token}",
        name=_e(driver.ingame_name),
    )


def send_password_reset(driver, token: str):
    _send(driver.email, "[ACE EVO] Réinitialisation de mot de passe", _html_password_reset(driver, token))


def _html_event_reminder(driver, event, registration) -> str:
    date_str = event.date.strftime("%d/%m/%Y à %H:%M") + " UTC"
    car_info = registration.car_display or registration.assigned_car or "Non assignée"
    password_line = f"\nMot de passe serveur : {_e(event.password)}" if event.password else ""
    return _render_type(
        "event_reminder",
        features=[("icon-bell", "Ne manquez pas le départ", "Retrouvez tous les détails sur le panel")],
        cta_url=_cfg["panel_url"],
        name=_e(driver.ingame_name), event=_e(event.title), date=date_str,
        circuit=_e(event.circuit_display or event.circuit), mode=_e(event.mode_display),
        weather=_e(event.weather_display), car=_e(car_info), password_line=password_line,
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
