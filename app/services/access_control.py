"""Contrôle d'accès au serveur de jeu : liste blanche, liste noire, lest et restricteur par SteamID.

Le serveur de jeu lit un fichier d'engagés (``entry_list_path`` de sa config) de la forme :

    {"version": 1,
     "entrylist": [{"steamid": "7656119…", "ballast": 20, "restrictor": 0.1}],
     "steamid_whitelist": ["7656119…"],
     "steamid_blacklist": ["7656119…"]}

Comportements vérifiés sur un vrai serveur de jeu (banc d'essai, 14/10/2026) :
  - liste blanche : un joueur absent est refusé (« User not allowed ») ; la liste noire l'emporte
    sur la liste blanche ; spectateurs compris ;
  - lest plafonné à 100 kg, restricteur à 0,2 (le serveur ramène au plafond) ;
  - **une liste blanche vide, un fichier absent ou un JSON invalide = aucun filtre** (le serveur
    démarre quand même). D'où le joueur « sentinelle » ci-dessous : sans lui, activer « pilotes
    approuvés seulement » alors qu'aucun pilote n'est approuvé ouvrirait le serveur à tous ;
  - un fichier au format d'un autre jeu (``entries`` / ``driverName``) est ignoré sans erreur.
"""
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

FILE_NAME = "entry_list_access.json"
STEAM_ID_RE = re.compile(r"^7656119\d{10}$")      # SteamID64 d'un compte individuel
MAX_BALLAST = 100
MAX_RESTRICTOR = 0.2
_NOBODY = "0"          # SteamID qui n'existe pas : liste blanche « personne »


def enabled() -> bool:
    return os.environ.get("ACCESS_CONTROL_ENABLED", "false").lower() == "true"


def approved_only() -> bool:
    return os.environ.get("ACCESS_APPROVED_ONLY", "false").lower() == "true"


def valid_steam_id(value: str) -> bool:
    return bool(STEAM_ID_RE.match((value or "").strip()))


def clamp_rule(ballast, restrictor) -> tuple[int, float]:
    """Ramène lest et restricteur dans les bornes du serveur de jeu."""
    try:
        b = max(0, min(MAX_BALLAST, int(ballast)))
    except (TypeError, ValueError):
        b = 0
    try:
        r = max(0.0, min(MAX_RESTRICTOR, round(float(restrictor), 3)))
    except (TypeError, ValueError):
        r = 0.0
    return b, r


def build_document(rules, approved_ids, only_approved: bool, always_allow=()) -> dict:
    """Construit le fichier d'engagés.

    rules        : objets avec steam_id, banned, ballast, restrictor (AccessRule)
    approved_ids : SteamID des pilotes approuvés (comptes du panel)
    only_approved: True = liste blanche = pilotes approuvés + joueurs ayant une règle non bannie
    always_allow : SteamID toujours autorisés (le bot du panel)"""
    banned = sorted({r.steam_id for r in rules if r.banned and valid_steam_id(r.steam_id)})
    entries = []
    for r in sorted(rules, key=lambda x: x.steam_id):
        if r.banned or not valid_steam_id(r.steam_id):
            continue
        ballast, restrictor = clamp_rule(r.ballast, r.restrictor)
        if ballast or restrictor:
            entries.append({"steamid": r.steam_id, "ballast": ballast, "restrictor": restrictor})
    doc: dict = {"version": 1, "entrylist": entries}
    if only_approved:
        allowed = {i for i in approved_ids if valid_steam_id(i)}
        allowed |= {r.steam_id for r in rules if not r.banned and valid_steam_id(r.steam_id)}
        allowed |= {i for i in always_allow if valid_steam_id(i)}
        allowed -= set(banned)       # le serveur donne déjà priorité à la liste noire ; fichier plus net
        doc["steamid_whitelist"] = sorted(allowed) or [_NOBODY]
    if banned:
        doc["steamid_blacklist"] = banned
    return doc


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _aceserver_dir() -> Path | None:
    """Dossier partagé avec le serveur de jeu (vu sous le même chemin par le panel et le jeu)."""
    from flask import current_app, has_app_context
    d = current_app.config.get("ACESERVER_DIR") if has_app_context() else None
    d = d or os.environ.get("ACESERVER_DIR", "")
    return Path(d) if d else None


def current_document() -> dict:
    """Document correspondant à l'état actuel de la base (contexte d'application requis)."""
    from app.models import AccessRule, Driver, DriverStatus
    rules = AccessRule.query.all()
    approved = [d.steam_id for d in Driver.query.filter_by(status=DriverStatus.APPROVED).all() if d.steam_id]
    bot = os.environ.get("ACE_BOT_STEAM_ID", "").strip()
    return build_document(rules, approved, approved_only(), always_allow=[bot] if bot else [])


def prepare_file() -> str | None:
    """Écrit le fichier d'engagés et retourne son chemin (celui que voit le serveur de jeu),
    ou None si l'écriture est impossible. Ne lève jamais : un échec ne doit pas empêcher un
    démarrage de serveur."""
    try:
        from app.services.process_manager import _db_context
        with _db_context():
            base = _aceserver_dir()
            if base is None:
                return None
            doc = current_document()
        path = base / FILE_NAME
        _atomic_write(path, json.dumps(doc, indent=2, ensure_ascii=False))
        log.info("Contrôle d'accès : %s écrit (%d engagé(s), liste blanche=%s, liste noire=%d)",
                 FILE_NAME, len(doc["entrylist"]),
                 len(doc["steamid_whitelist"]) if "steamid_whitelist" in doc else "off",
                 len(doc.get("steamid_blacklist", [])))
        return str(path)
    except Exception as e:
        log.warning("Contrôle d'accès : fichier d'engagés non généré (%s)", e)
        return None
