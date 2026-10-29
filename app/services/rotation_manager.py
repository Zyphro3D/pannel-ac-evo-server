"""
Config Rotation — séquence de fichiers de configuration à enchaîner
automatiquement à chaque arrêt du serveur, ou après un délai d'inactivité
(aucun joueur connecté) si idle_timeout_minutes est configuré.

Une file par serveur : /aceserver/.rotation.json pour le serveur 1 (nom d'origine,
gardé tel quel), /aceserver/.rotation_<id>.json pour les autres — même convention
que .panel_state<_id>.json. Avant, une file unique servait à tous les serveurs : un
serveur hors de la liste repartait sur la première config de la file d'un autre.

Format JSON :
  {
    "enabled": true,
    "cycle":   false,
    "configs": ["practice.json", "race-weekend.json"],
    "idle_timeout_minutes": 0
  }
"""
import json
import os
from pathlib import Path

_DEFAULT_ROTATION = {"enabled": False, "cycle": False, "configs": [], "idle_timeout_minutes": 0}


def _rotation_path(server_id: int) -> Path:
    base = Path(os.environ.get("ACESERVER_DIR", "/aceserver"))
    suffix = "" if int(server_id) == 1 else f"_{int(server_id)}"
    return base / f".rotation{suffix}.json"


def get_rotation(server_id: int) -> dict:
    p = _rotation_path(server_id)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            # Fichier du dossier partagé avec le conteneur du jeu : on revalide les noms à la
            # lecture comme save_rotation le fait à l'écriture.
            from app.services.server_config import _valid_config_name
            data["configs"] = [c for c in data.get("configs", []) if isinstance(c, str) and _valid_config_name(c)]
            return {**_DEFAULT_ROTATION, **data}
        except Exception:
            pass
    return dict(_DEFAULT_ROTATION)


def save_rotation(data: dict, server_id: int):
    from app.services.server_config import _valid_config_name
    configs = [str(c) for c in data.get("configs", [])]
    valid_configs = [c for c in configs if _valid_config_name(c)]
    if len(valid_configs) != len(configs):
        import logging
        logging.getLogger(__name__).warning(
            "save_rotation: nom(s) de config invalide(s) ignoré(s) : %s",
            set(configs) - set(valid_configs),
        )
    try:
        idle_timeout_minutes = max(0, int(data.get("idle_timeout_minutes", 0)))
    except (ValueError, TypeError):
        idle_timeout_minutes = 0
    _rotation_path(server_id).write_text(json.dumps({
        "enabled": bool(data.get("enabled", False)),
        "cycle":   bool(data.get("cycle",   False)),
        "configs": valid_configs,
        "idle_timeout_minutes": idle_timeout_minutes,
    }))


def delete_rotation(server_id: int):
    """Supprime la file d'un serveur supprimé (jamais celle du serveur 1)."""
    if int(server_id) != 1:
        _rotation_path(server_id).unlink(missing_ok=True)


def get_next_config(current_config: str, server_id: int) -> str | None:
    """
    Retourne le nom du prochain fichier de config à démarrer, ou None si le
    roulement est terminé (fin de liste sans cycle, ou feature désactivée).
    """
    rot = get_rotation(server_id)
    if not rot.get("enabled"):
        return None
    configs = rot.get("configs", [])
    if not configs:
        return None
    if current_config not in configs:
        return configs[0]
    idx = configs.index(current_config)
    next_idx = idx + 1
    if next_idx >= len(configs):
        return configs[0] if rot.get("cycle") else None
    return configs[next_idx]
