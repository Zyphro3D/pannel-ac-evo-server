"""
Mise à jour du panel depuis le panel (superadmin), sur le modèle de ZCoach et de BeamMP Panel.

Chaque release GitHub publie un manifeste `latest-stable.json` signé Ed25519 (signature faite sur
la machine de publication, jamais en CI). Le panel le vérifie avec la clé publique ci-dessous et
affiche la version disponible. Le bouton « Mettre à jour » ne fait que déposer une DEMANDE dans le
dossier partagé `update/` : le panel n'a aucun droit Docker de plus. L'agent de la machine (service
systemd sous Linux, tâche planifiée sous Windows, posés par install.sh / install.ps1) relance alors
le script d'installation en mode mise à jour : il revérifie signature et empreinte, reconstruit,
redémarre et revient à la version précédente si le panel ne répond plus. Il écrit l'avancement dans
`update/status.json`, que la page lit pendant l'opération.

Module sans dépendance hors bibliothèque standard : `release/verify_release.py` l'importe tel quel
pour que les scripts d'installation vérifient une release avec le code déjà installé.
"""
import base64
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

try:
    from . import ed25519
except ImportError:          # chargé hors du paquet par release/verify_release.py
    import ed25519

APP_ID = "ace-evo-panel"
MANIFEST_URL = "https://github.com/Zyphro3D/pannel-ac-evo-server/releases/latest/download/latest-stable.json"
# Clé publique de publication (la clé privée ne quitte jamais la machine qui signe les releases)
PUBLIC_KEY_B64 = "AKO3VutWivZTAxy1SMRZOHm9qQS1_Ee9vZ-_w2OoKhw"
UPDATE_DIR = Path(os.environ.get("PANEL_UPDATE_DIR", "/panel/update"))

_MAX_MANIFEST = 256 * 1024
_MAX_SIG = 4096
_CHECK_EVERY = 12 * 3600
_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
_PACKAGE_RE = re.compile(r"pannel-ac-evo-docker-v\d+\.\d+\.\d+\.zip")

_cache: dict = {}
_cache_lock = threading.Lock()


def parse_version(v: str) -> tuple:
    if not _VERSION_RE.fullmatch(str(v).strip()):
        raise ValueError(f"version invalide : {v!r}")
    return tuple(int(x) for x in str(v).strip().split("."))


def _b64d(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_manifest(raw: bytes, sig_b64: str, pub_b64: str = PUBLIC_KEY_B64) -> dict:
    """Vérifie la signature Ed25519 puis le contenu du manifeste ; lève ValueError sinon."""
    try:
        signature = _b64d(sig_b64)
    except ValueError:
        raise ValueError("signature illisible")
    if not ed25519.verify(_b64d(pub_b64), raw, signature):
        raise ValueError("signature du manifeste invalide")
    m = json.loads(raw)
    if m.get("app") != APP_ID or m.get("channel") != "stable":
        raise ValueError("manifeste étranger")
    parse_version(m.get("version", ""))
    pkg = m.get("package") or {}
    if (not _PACKAGE_RE.fullmatch(str(pkg.get("name", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(pkg.get("sha256", "")))
            or not isinstance(pkg.get("size"), int) or pkg["size"] <= 0):
        raise ValueError("description du paquet invalide")
    if pkg["name"] != f"pannel-ac-evo-docker-v{m['version']}.zip":
        raise ValueError("le paquet ne correspond pas à la version annoncée")
    return m


def verify_package(manifest: dict, path: Path) -> None:
    """Contrôle taille et SHA-256 de l'archive téléchargée par rapport au manifeste signé."""
    data = Path(path).read_bytes()
    if len(data) != manifest["package"]["size"] or hashlib.sha256(data).hexdigest() != manifest["package"]["sha256"]:
        raise ValueError("empreinte SHA-256 de l'archive incorrecte")


def _fetch(url: str, limit: int) -> bytes:
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("réponse anormalement grosse")
    return data


def check(current: str) -> dict:
    """Interroge la dernière release ; renvoie l'état affiché par la page (jamais d'exception)."""
    result = {"current": current, "latest": None, "available": False, "notes": {}, "error": "",
              "checked": int(time.time())}
    try:
        raw = _fetch(MANIFEST_URL, _MAX_MANIFEST)
        sig = _fetch(MANIFEST_URL + ".sig", _MAX_SIG).decode("ascii")
        m = verify_manifest(raw, sig)
        result.update(latest=m["version"], notes=m.get("notes") or {})
        try:
            result["available"] = parse_version(m["version"]) > parse_version(current)
        except ValueError:            # version locale illisible (copie de développement)
            result["available"] = False
    except Exception as e:
        result["error"] = str(e)[:200]
    with _cache_lock:
        _cache.clear()
        _cache.update(result)
    return result


def cached() -> dict:
    with _cache_lock:
        return dict(_cache)


def check_in_background(current: str) -> None:
    """Contrôle au plus toutes les 12 h, sans faire attendre la page qui l'a déclenché."""
    with _cache_lock:
        if _cache.get("checked", 0) > time.time() - _CHECK_EVERY or _cache.get("_running"):
            return
        _cache["_running"] = True
    threading.Thread(target=check, args=(current,), daemon=True, name="panel-update-check").start()


def agent_installed() -> bool:
    """L'agent de la machine (posé par le script d'installation) signale sa présence ici."""
    return (UPDATE_DIR / "agent.json").is_file()


def request_update(version: str) -> None:
    """Dépose la demande lue par l'agent de la machine (écriture atomique)."""
    parse_version(version)
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = UPDATE_DIR / f".request-{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"version": version, "requested_at": int(time.time())}))
    os.replace(tmp, UPDATE_DIR / "request.json")


def status() -> dict:
    """Avancement écrit par le script d'installation, et demande encore en attente."""
    st: dict = {}
    try:
        st = json.loads((UPDATE_DIR / "status.json").read_text(encoding="utf-8"))
        if not isinstance(st, dict):
            st = {}
    except (OSError, ValueError):
        pass
    st["pending"] = (UPDATE_DIR / "request.json").is_file()
    return st
