"""
Vérification d'identité Steam via OpenID 2.0 (steamcommunity.com/openid/login).

Gratuit, sans clé API : Steam agit comme fournisseur OpenID. Le flux :
  1. build_auth_url() redirige le pilote vers Steam pour s'y authentifier.
  2. Steam le renvoie vers notre callback avec des paramètres openid.* signés.
  3. verify_callback() renvoie ces mêmes paramètres à Steam (mode check_authentication,
     requête serveur-à-serveur) pour confirmer qu'ils sont authentiques et n'ont pas
     été forgés — c'est cette étape qui rend l'usurpation d'identité impossible.

Le SteamID64 n'est jamais accepté s'il n'a pas transité par ce flux complet.
"""
import logging
import re
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

_STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
_CLAIMED_ID_RE = re.compile(r'^https?://steamcommunity\.com/openid/id/(\d+)$')


def build_auth_url(return_to: str, realm: str) -> str:
    """Retourne l'URL vers laquelle rediriger le pilote pour s'authentifier via Steam."""
    params = {
        "openid.ns":         "http://specs.openid.net/auth/2.0",
        "openid.mode":       "checkid_setup",
        "openid.return_to":  return_to,
        "openid.realm":      realm,
        "openid.identity":   "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return f"{_STEAM_OPENID_URL}?{urllib.parse.urlencode(params)}"


def verify_callback(args) -> str | None:
    """Revérifie auprès de Steam les paramètres openid.* reçus sur le callback.
    Retourne le SteamID64 (str) si la signature est authentique, None sinon.
    `args` est le query string du callback (ex: request.args), doit contenir les
    clés openid.* telles que renvoyées par Steam."""
    if args.get("openid.mode") != "id_res":
        return None

    claimed_id = args.get("openid.claimed_id", "")
    m = _CLAIMED_ID_RE.match(claimed_id)
    if not m:
        return None
    steam_id = m.group(1)

    # Renvoie exactement les mêmes paramètres à Steam, mode check_authentication,
    # pour confirmer que la réponse n'a pas été forgée par le client.
    verify_params = {k: v for k, v in args.items() if k.startswith("openid.")}
    verify_params["openid.mode"] = "check_authentication"

    try:
        data = urllib.parse.urlencode(verify_params).encode()
        req  = urllib.request.Request(_STEAM_OPENID_URL, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("steam_openid: vérification impossible : %s", e)
        return None

    if "is_valid:true" not in body:
        log.warning("steam_openid: signature invalide (réponse Steam: %r)", body[:200])
        return None

    return steam_id
