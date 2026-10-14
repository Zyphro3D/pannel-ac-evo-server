"""Adresse réelle du visiteur derrière un reverse proxy.

Waitress ignore (et supprime) X-Forwarded-For tant qu'aucun proxy n'est déclaré de confiance :
derrière Caddy / Cloudflare, ``request.remote_addr`` est donc l'adresse du proxy, la même pour tout
le monde. Conséquences : limite de débit et anti-brute-force du login partagés par tous les
visiteurs, et confiance « IP privée » de l'ingestion des résultats ouverte à tout Internet.

TRUSTED_PROXIES (adresses ou réseaux CIDR, séparés par des virgules) liste les proxys qui ont le droit
de dire qui est le visiteur : pour eux seulement, l'en-tête CF-Connecting-IP est lu. Vide (défaut) =
comportement historique.
"""
import hashlib
import hmac
import ipaddress
import os

from flask import current_app, request

# En-têtes ajoutés par un proxy : leur présence prouve que la requête n'est pas directe.
_PROXY_HEADERS = ("CF-Connecting-IP", "CF-Ray", "X-Forwarded-For", "X-Real-IP", "Forwarded")


def _networks() -> list:
    nets = []
    for raw in os.environ.get("TRUSTED_PROXIES", "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue
    return nets


def _parse(addr: str):
    try:
        return ipaddress.ip_address((addr or "").strip())
    except ValueError:
        return None


def is_trusted_proxy(addr: str) -> bool:
    ip = _parse(addr)
    return bool(ip) and any(ip in net for net in _networks())


def client_ip() -> str:
    """Adresse du visiteur : celle du proxy de confiance (CF-Connecting-IP) ou l'adresse directe."""
    peer = request.remote_addr or ""
    if is_trusted_proxy(peer):
        fwd = _parse(request.headers.get("CF-Connecting-IP", ""))
        if fwd:
            return str(fwd)
    return peer or "unknown"


def came_through_proxy() -> bool:
    """True si la requête porte la trace d'un proxy, ou vient d'un proxy déclaré de confiance."""
    return is_trusted_proxy(request.remote_addr or "") or any(h in request.headers for h in _PROXY_HEADERS)


def host_is_internal() -> bool:
    """Le serveur de jeu poste toujours vers une adresse interne (``panel``, ``127.0.0.1``…), jamais
    vers un nom de domaine public : un Host avec un point et qui n'est pas une IP vient d'un visiteur
    passé par un nom public, donc d'un proxy ou d'un accès direct par domaine."""
    host = (request.host or "").rsplit(":", 1)[0] if not request.host.startswith("[") else request.host
    host = host.strip("[]")
    if not host:
        return False
    if _parse(host) is not None:
        return True
    return "." not in host


def ingest_token(server_id: int) -> str:
    """Jeton ajouté à l'URL de retour des résultats : seule la config construite par le panel le porte,
    ce qui authentifie le serveur de jeu (qui ne sait pas signer ses requêtes), avec ou sans proxy."""
    key = (current_app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY") or "").encode()
    return hmac.new(key, f"results-ingest:{int(server_id)}".encode(), hashlib.sha256).hexdigest()[:32]
