"""Mods par serveur.

Le jeu charge TOUT ce qu'il trouve dans son dossier Saved Games/ACE-Server/mods et l'exige
ensuite de chaque joueur (« Content unavailable or version mismatch »), même pour une voiture
absente de la liste du serveur. Avec une bibliothèque commune montée dans tous les conteneurs,
un mod envoyé pour un seul serveur bloquait donc l'accès à tous les autres (vécu le 25/11).

La bibliothèque (MODS_DIR) reste l'unique endroit où le panel range les mods. Chaque serveur a
son propre dossier, <ACESERVER_DIR>/mods-server/<id>, rempli de liens physiques vers les mods qui
lui sont affectés ; le conteneur de jeu y fait pointer son dossier de mods (entrypoint).

Affectations : <MODS_DIR>/.servers.json, {"fichier.kspkg": [ids]}. Un mod absent du fichier est
affecté à tous les serveurs : c'était le comportement d'avant, gardé pour les installations qui
se mettent à jour. Un mod envoyé depuis cette version est enregistré sans serveur.
"""
import json
import logging
import os
import shutil
from pathlib import Path

from flask import current_app

log = logging.getLogger(__name__)

_ASSIGN_FILE = ".servers.json"


def _mods_dir() -> Path:
    return Path(current_app.config["MODS_DIR"])


def server_mods_dir(server_id: int) -> Path:
    return Path(current_app.config["ACESERVER_DIR"]) / "mods-server" / str(int(server_id))


def load_assignments() -> dict[str, list[int]]:
    path = _mods_dir() / _ASSIGN_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("mod_assign: %s illisible (%s), affectations ignorées", path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for name, ids in data.items():
        if isinstance(name, str) and isinstance(ids, list):
            out[name] = sorted({int(i) for i in ids if isinstance(i, int) or str(i).isdigit()})
    return out


def _save_assignments(data: dict[str, list[int]]) -> None:
    path = _mods_dir() / _ASSIGN_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def servers_of(filename: str, all_ids: list[int], assignments: dict | None = None) -> list[int]:
    """Serveurs qui utilisent ce mod ; absent des affectations = tous (compatibilité)."""
    assignments = load_assignments() if assignments is None else assignments
    if filename in assignments:
        return [i for i in assignments[filename] if i in all_ids]
    return list(all_ids)


def set_servers(filename: str, server_ids: list[int]) -> None:
    data = load_assignments()
    data[filename] = sorted({int(i) for i in server_ids})
    _save_assignments(data)


def forget(filename: str) -> None:
    data = load_assignments()
    if data.pop(filename, None) is not None:
        _save_assignments(data)


def mod_files_for_server(server_id: int, all_ids: list[int]) -> set[str]:
    """Fichiers (.kspkg + son .json) à poser dans le dossier du serveur."""
    assignments = load_assignments()
    files = set()
    for kspkg in _mods_dir().glob("*.kspkg"):
        if server_id in servers_of(kspkg.name, all_ids, assignments):
            files.add(kspkg.name)
            if kspkg.with_suffix(".json").exists():
                files.add(kspkg.with_suffix(".json").name)
    return files


def allowed_mod_car_names(server_id: int, all_ids: list[int]) -> set[str]:
    """Identifiants de voitures des mods affectés au serveur (pour filtrer la liste des voitures)."""
    names = set()
    for f in mod_files_for_server(server_id, all_ids):
        if not f.endswith(".json"):
            continue
        try:
            data = json.loads((_mods_dir() / f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        names.update(c.get("name") for c in data.get("cars", []) if c.get("name"))
    return names


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def sync_server_mods(server_id: int, all_ids: list[int]) -> dict:
    """Aligne <ACESERVER_DIR>/mods-server/<id> sur les affectations : lien physique vers la
    bibliothèque (copie si le lien est impossible), suppression de ce qui n'est plus affecté.
    Pris en compte par le jeu au prochain démarrage du serveur."""
    src_dir = _mods_dir()
    dst_dir = server_mods_dir(server_id)
    dst_dir.mkdir(parents=True, exist_ok=True)
    wanted = mod_files_for_server(server_id, all_ids)
    added, removed = [], []
    for name in sorted(wanted):
        src, dst = src_dir / name, dst_dir / name
        if dst.exists() and _same_file(src, dst):
            continue
        tmp = dst_dir / f".{name}.tmp"
        if tmp.exists():
            tmp.unlink()
        try:
            os.link(src, tmp)
        except OSError:
            shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        added.append(name)
    for p in dst_dir.iterdir():
        if p.is_file() and p.name not in wanted:
            p.unlink()
            removed.append(p.name)
    if added or removed:
        log.info("mod_assign: serveur %d, %d mod(s) ajouté(s), %d retiré(s)", server_id, len(added), len(removed))
    return {"added": added, "removed": removed}


def enabled_server_ids() -> list[int]:
    from app.models import Server
    return [s.id for s in Server.query.filter_by(is_enabled=True).order_by(Server.id).all()]


def sync_all() -> None:
    ids = enabled_server_ids()
    for sid in ids:
        try:
            sync_server_mods(sid, ids)
        except OSError as e:
            log.error("mod_assign: synchronisation du serveur %d impossible : %s", sid, e)


# ── Pack client d'un serveur et téléchargements publics ─────────────────────
# Un circuit moddé ne se résume pas à un .kspkg : le joueur passe par l'installeur de son auteur.
# Chaque serveur peut donc proposer un « pack » (archive fournie par l'admin), téléchargeable par
# tous avec ses mods sur la page publique /downloads.

PACK_EXTS = (".zip", ".7z", ".rar")


def packs_dir(server_id: int) -> Path:
    return _mods_dir() / "packs" / str(int(server_id))


def get_pack(server_id: int) -> Path | None:
    d = packs_dir(server_id)
    if not d.is_dir():
        return None
    files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in PACK_EXTS]
    return files[0] if files else None


def save_pack(server_id: int, file_storage) -> dict:
    import re
    name = Path(file_storage.filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in PACK_EXTS:
        return {"ok": False, "error": "bad_extension"}
    stem = re.sub(r"[^a-zA-Z0-9_.-]", "_", Path(name).stem)[:80].strip("_.") or "pack"
    d = packs_dir(server_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".upload{ext}.tmp"
    file_storage.save(str(tmp))
    for old in d.iterdir():          # un seul pack par serveur : le nouveau remplace l'ancien
        if old.is_file() and old != tmp and old.suffix.lower() in PACK_EXTS:
            old.unlink()
    dest = d / f"{stem}{ext}"
    os.replace(tmp, dest)
    return {"ok": True, "filename": dest.name, "sizeBytes": dest.stat().st_size}


def delete_pack(server_id: int) -> bool:
    p = get_pack(server_id)
    if p is None:
        return False
    p.unlink()
    return True


_LINK_FILE = "link.txt"


def get_pack_url(server_id: int) -> str:
    """Lien vers la page de téléchargement de l'auteur, quand sa licence ne permet pas de
    redistribuer son pack : la page publique renvoie alors vers lui au lieu d'héberger ses
    fichiers."""
    try:
        url = (packs_dir(server_id) / _LINK_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return url if valid_url(url) else ""


def valid_url(url: str) -> bool:
    from urllib.parse import urlparse
    u = urlparse(url or "")
    return u.scheme == "https" and bool(u.netloc) and len(url) <= 500 and not any(c in url for c in "\r\n\"'<> ")


def set_pack_url(server_id: int, url: str) -> bool:
    url = (url or "").strip()
    path = packs_dir(server_id) / _LINK_FILE
    if not url:
        path.unlink(missing_ok=True)
        return True
    if not valid_url(url):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(url, encoding="utf-8")
    return True


def public_downloads(servers: list) -> list[dict]:
    """Serveurs actifs qui demandent quelque chose aux joueurs : leur pack et leurs mods."""
    ids = [s.id for s in servers]
    assignments = load_assignments()
    kspkgs = sorted(_mods_dir().glob("*.kspkg"))
    out = []
    for srv in servers:
        mods = []
        for k in kspkgs:
            if srv.id in servers_of(k.name, ids, assignments):
                name = k.stem
                try:
                    cars = json.loads(k.with_suffix(".json").read_text(encoding="utf-8")).get("cars", [])
                    name = ", ".join(c.get("display_name") or c.get("name") for c in cars) or name
                except (OSError, ValueError):
                    pass
                mods.append({"filename": k.name, "label": name, "sizeBytes": k.stat().st_size})
        pack = get_pack(srv.id)
        link = get_pack_url(srv.id)
        if mods or pack or link:
            out.append({"server": srv, "mods": mods, "link": link,
                        "pack": {"filename": pack.name, "sizeBytes": pack.stat().st_size} if pack and not link else None})
    return out


def public_file(server_id: int, filename: str) -> Path | None:
    """Fichier téléchargeable publiquement pour ce serveur (son pack ou un mod qui lui est
    affecté), ou None. Jamais un chemin hors de la bibliothèque."""
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    if get_pack_url(server_id):          # contenu de l'auteur : on renvoie vers lui, rien n'est servi ici
        return None
    pack = get_pack(server_id)
    if pack is not None and pack.name == filename:
        return pack
    if not filename.lower().endswith(".kspkg"):
        return None
    path = _mods_dir() / filename
    if not path.is_file() or path.parent != _mods_dir():
        return None
    if server_id not in servers_of(filename, enabled_server_ids()):
        return None
    return path
