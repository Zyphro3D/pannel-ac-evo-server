"""Sauvegarde / restauration du panel : base de données, réglages, configurations serveur, images.

Le zip contient : manifest.json, db/ace_evo.db (copie cohérente via l'API de sauvegarde de SQLite),
settings.json (réglages, dont webhooks et mots de passe : à traiter comme un secret), configs/*.json,
media/** (images). Les mods (plusieurs Go) et les résultats bruts du serveur de jeu ne sont pas inclus.

Restauration : le zip est d'abord validé (noms de fichiers autorisés, tailles, intégrité de la base), une
sauvegarde de sécurité de l'état actuel est faite, puis les fichiers sont remplacés. Un redémarrage du
panel est nécessaire ensuite (la base est rouverte, les caches vidés)."""
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from flask_babel import gettext as _gettext

log = logging.getLogger(__name__)

MAX_ENTRIES      = 5000
MAX_MEMBER_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES  = 1024 * 1024 * 1024
MAX_MEDIA_FILE   = 50 * 1024 * 1024
_MEDIA_EXT       = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico"}
_SAFE_NAME       = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip$")
_CONFIG_NAME     = re.compile(r"^[^\x00-\x1f\\/:*?\"<>|.][^\x00-\x1f\\/:*?\"<>|]{0,100}\.json$")
_MEDIA_PART      = re.compile(r"^[^\x00-\x1f\\/:*?\"<>|.][^\x00-\x1f\\/:*?\"<>|]{0,150}$")   # accents, virgules… autorisés ; ni « .. » ni « / »
_REQUIRED_TABLES = {"admin_account", "session_result", "driver"}


def _(msg: str, **kw) -> str:
    """Traduit si une requête est en cours ; sans contexte (tâche de fond, tests) retombe sur le français."""
    try:
        return _gettext(msg, **kw)
    except RuntimeError:
        return msg % kw if kw else msg


class BackupError(Exception):
    """Erreur affichable telle quelle à l'administrateur."""


# ── Emplacements ─────────────────────────────────────────────────────────────

def _paths() -> dict:
    from flask import current_app
    from app.services.database import db
    import app as app_pkg
    db_file = Path(db.engine.url.database or "")
    return {
        "db": db_file,
        "settings": Path(app_pkg._SETTINGS_PATH),
        "configs": Path(current_app.config["CONFIGS_DIR"]),
        "media": Path(app_pkg.__file__).parent.parent / "media",
        "dir": Path(app_pkg._SETTINGS_PATH).parent / "backups",
    }


def backups_dir() -> Path:
    d = _paths()["dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _panel_version() -> str:
    import app as app_pkg
    return getattr(app_pkg, "_APP_VERSION", "?")


def _vtuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except ValueError:
        return (0, 0, 0)


# ── Création ─────────────────────────────────────────────────────────────────

def create_backup(kind: str = "manuelle", include_secrets: bool = True) -> Path:
    """Crée un zip dans data/backups/ et retourne son chemin. ``kind`` : manuelle | auto | avant-restauration."""
    p = _paths()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = {"manuelle": "", "auto": "-auto", "avant-restauration": "-avant-restauration"}.get(kind, "")
    out = backups_dir() / f"panel-backup-{stamp}{suffix}.zip"
    tmp = tempfile.mkdtemp(prefix="panel-bk-")
    try:
        snap = Path(tmp) / "ace_evo.db"
        src = sqlite3.connect(str(p["db"]))
        try:
            dst = sqlite3.connect(str(snap))
            with dst:
                src.backup(dst)
            dst.close()
        finally:
            src.close()
        manifest = {"format": 1, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "panel_version": _panel_version(), "kind": kind, "includes_settings": bool(include_secrets),
                    "contents": []}
        part = out.with_suffix(".part")
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(snap, "db/ace_evo.db"); manifest["contents"].append("db/ace_evo.db")
            if include_secrets and p["settings"].exists():
                z.write(p["settings"], "settings.json"); manifest["contents"].append("settings.json")
            if p["configs"].is_dir():
                for f in sorted(p["configs"].glob("*.json")):
                    if f.is_file() and _member_ok(f"configs/{f.name}"):
                        z.write(f, f"configs/{f.name}"); manifest["contents"].append(f"configs/{f.name}")
                    elif f.is_file():
                        log.warning("sauvegarde : configuration ignorée (nom non pris en charge) : %s", f.name)
            if p["media"].is_dir():
                for f in sorted(p["media"].rglob("*")):
                    if f.is_file() and f.suffix.lower() in _MEDIA_EXT and f.stat().st_size <= MAX_MEDIA_FILE:
                        arc = "media/" + f.relative_to(p["media"]).as_posix()
                        if not _member_ok(arc):
                            log.warning("sauvegarde : image ignorée (nom non pris en charge) : %s", arc)
                            continue
                        z.write(f, arc); manifest["contents"].append(arc)
            z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        os.replace(part, out)
        os.chmod(out, 0o600)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def list_backups() -> list[dict]:
    out = []
    for f in sorted(backups_dir().glob("*.zip"), reverse=True):
        if not _SAFE_NAME.match(f.name):
            continue
        st = f.stat()
        out.append({"name": f.name, "size": st.st_size,
                    "created": datetime.fromtimestamp(st.st_mtime, timezone.utc).replace(tzinfo=None),
                    "auto": f.name.endswith("-auto.zip"), "pre_restore": f.name.endswith("-avant-restauration.zip")})
    return out


def backup_path(name: str) -> Path:
    if not _SAFE_NAME.match(name or ""):
        raise BackupError(_("Nom de sauvegarde invalide."))
    f = backups_dir() / name
    if not f.is_file():
        raise BackupError(_("Sauvegarde introuvable."))
    return f


def delete_backup(name: str) -> None:
    backup_path(name).unlink()


def prune_auto(keep: int) -> int:
    """Ne garde que les ``keep`` sauvegardes automatiques les plus récentes."""
    autos = [b for b in list_backups() if b["auto"]]
    n = 0
    for b in autos[max(1, keep):]:
        try:
            (backups_dir() / b["name"]).unlink()
            n += 1
        except OSError:
            pass
    return n


def last_backup_time():
    items = list_backups()
    return items[0]["created"] if items else None


# ── Validation ───────────────────────────────────────────────────────────────

def _member_ok(name: str) -> bool:
    if name in ("manifest.json", "db/ace_evo.db", "settings.json"):
        return True
    parts = name.split("/")
    if ".." in parts or name.startswith("/") or "\\" in name or "" in parts[:-1]:
        return False
    if parts[0] == "configs" and len(parts) == 2:
        return bool(_CONFIG_NAME.match(parts[1]))
    if parts[0] == "media" and len(parts) >= 2:
        return all(_MEDIA_PART.match(x) for x in parts[1:]) and Path(parts[-1]).suffix.lower() in _MEDIA_EXT
    return False


def validate(path: Path) -> dict:
    """Vérifie un zip de sauvegarde sans rien extraire dans le panel ; retourne son manifest."""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise BackupError(_("Ce fichier n'est pas une archive zip valide."))
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES:
            raise BackupError(_("Archive trop volumineuse (trop de fichiers)."))
        total = 0
        for i in infos:
            if i.is_dir():
                continue
            if not _member_ok(i.filename):
                raise BackupError(_("Fichier non autorisé dans l'archive : %(f)s", f=i.filename))
            if i.file_size > MAX_MEMBER_BYTES:
                raise BackupError(_("Fichier trop gros dans l'archive : %(f)s", f=i.filename))
            total += i.file_size
        if total > MAX_TOTAL_BYTES:
            raise BackupError(_("Archive trop volumineuse une fois décompressée."))
        names = {i.filename for i in infos}
        if "manifest.json" not in names or "db/ace_evo.db" not in names:
            raise BackupError(_("Archive incomplète : manifest ou base de données absents."))
        try:
            manifest = json.loads(z.read("manifest.json"))
        except ValueError:
            raise BackupError(_("Manifest illisible."))
        if manifest.get("format") != 1:
            raise BackupError(_("Format de sauvegarde inconnu."))
        if _vtuple(str(manifest.get("panel_version", "0"))) > _vtuple(_panel_version()):
            raise BackupError(_("Cette sauvegarde vient d'une version plus récente du panel : mettez le panel à jour d'abord."))
        tmp = tempfile.mkdtemp(prefix="panel-bk-check-")
        try:
            dbf = Path(tmp) / "x.db"
            with z.open("db/ace_evo.db") as src, open(dbf, "wb") as dst:
                shutil.copyfileobj(src, dst)
            con = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)
            try:
                if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError(_("La base de données de la sauvegarde est corrompue."))
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
            if not _REQUIRED_TABLES <= tables:
                raise BackupError(_("La base de données de la sauvegarde ne ressemble pas à celle du panel."))
        except sqlite3.DatabaseError:
            raise BackupError(_("La base de données de la sauvegarde est illisible."))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return manifest


# ── Restauration ─────────────────────────────────────────────────────────────

# Réglages écrits par les pages Sauvegarde et Accès (hors _ENV_SECTIONS de la page Paramètres).
_EXTRA_SETTINGS_KEYS = {"BACKUP_AUTO", "BACKUP_KEEP", "ACCESS_CONTROL_ENABLED", "ACCESS_APPROVED_ONLY",
                        "RATING_ENFORCE", "RATING_MIN_TO_JOIN", "RATING_MIN_RACES"}
_INTERNAL_SETTINGS_KEY = re.compile(r"^__[a-z_]{1,60}$")   # marqueurs du panel (__last_seen_version…)


def _filtered_settings(raw: bytes) -> bytes:
    """Ne garde du settings.json d'une archive que les clés que le panel sait écrire lui-même.
    _load_settings recopie chaque clé dans os.environ au démarrage : une archive modifiée pouvait
    sinon poser n'importe quelle variable (DATABASE_URL, PYTHONPATH…) pour le panel et ses
    sous-processus."""
    from app import _SETTINGS_SKIP_KEYS
    from app.routes.admin import _ENV_SECTIONS
    allowed = ({k for _s, _l, keys in _ENV_SECTIONS for k in keys} | _EXTRA_SETTINGS_KEYS) - _SETTINGS_SKIP_KEYS
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BackupError(_("Les réglages (settings.json) de la sauvegarde sont illisibles."))
    if not isinstance(data, dict):
        raise BackupError(_("Les réglages (settings.json) de la sauvegarde sont illisibles."))
    kept, dropped = {}, []
    for k, v in data.items():
        if k in allowed and isinstance(v, (str, int, float, bool)):
            kept[k] = v
        elif isinstance(k, str) and _INTERNAL_SETTINGS_KEY.match(k):
            kept[k] = v
        else:
            dropped.append(str(k)[:60])
    if dropped:
        log.warning("Restauration : %d réglage(s) inconnu(s) ignoré(s) : %s", len(dropped), ", ".join(dropped[:20]))
    return json.dumps(kept, indent=2, ensure_ascii=False).encode("utf-8")


def restore(path: Path) -> dict:
    """Valide puis applique une sauvegarde. Retourne {manifest, safety_backup}. Redémarrage du panel requis."""
    manifest = validate(path)
    safety = create_backup("avant-restauration")
    p = _paths()
    from app.services.database import db
    with zipfile.ZipFile(path) as z:
        # Écrit tout dans des fichiers temporaires voisins d'abord : si un échec survient, rien n'est à moitié remplacé.
        staged: list[tuple[Path, Path]] = []
        try:
            def stage(member: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".restore-tmp")
                with z.open(member) as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                staged.append((tmp, target))
            stage("db/ace_evo.db", p["db"])
            names = {i.filename for i in z.infolist()}
            if "settings.json" in names:
                target = p["settings"]
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".restore-tmp")
                tmp.write_bytes(_filtered_settings(z.read("settings.json")))
                staged.append((tmp, target))
            for n in sorted(names):
                if n.startswith("configs/") and not n.endswith("/"):
                    stage(n, p["configs"] / n.split("/", 1)[1])
                elif n.startswith("media/") and not n.endswith("/"):
                    stage(n, p["media"] / n.split("/", 1)[1])
        except Exception:
            for tmp, _t in staged:
                tmp.unlink(missing_ok=True)
            raise
    db.session.remove()
    db.engine.dispose()
    for suffix in ("-wal", "-shm"):
        Path(str(p["db"]) + suffix).unlink(missing_ok=True)
    for tmp, target in staged:
        os.replace(tmp, target)
    return {"manifest": manifest, "safety_backup": safety.name}
