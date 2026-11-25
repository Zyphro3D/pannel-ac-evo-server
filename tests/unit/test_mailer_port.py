"""Vécu en production (25/11) : settings.json garde « 465 » en texte ; « port == 465 » échouait et le
panel parlait SMTP en clair sur le port SSL d'OVH → délai dépassé sur tous les envois."""
from app.services import mailer


def test_port_texte_converti():
    mailer.init({"MAIL_PORT": "465", "MAIL_USE_TLS": "false"})
    assert mailer._cfg["port"] == 465 and mailer._cfg["use_tls"] is False


def test_port_ssl_utilise_smtp_ssl(monkeypatch):
    used = []
    class Fake:
        def __init__(self, host, port, timeout=0): used.append((type(self).__name__, port))
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a): pass
        def sendmail(self, *a): pass
        def starttls(self): used.append("starttls")
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", type("SMTP_SSL", (Fake,), {}))
    monkeypatch.setattr(mailer.smtplib, "SMTP", type("SMTP", (Fake,), {}))
    mailer.init({"MAIL_SERVER": "smtp.example", "MAIL_PORT": "465", "MAIL_USERNAME": "u", "MAIL_FROM": "a@example.org"})
    mailer._smtp_send(mailer._build_msg("b@example.org", "s", "<p>x</p>"), "b@example.org")
    assert used == [("SMTP_SSL", 465)]


def test_port_invalide_repli_587():
    mailer.init({"MAIL_PORT": "abc"})
    assert mailer._cfg["port"] == 587
