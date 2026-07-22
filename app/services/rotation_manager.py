"""
Config Rotation — séquence de fichiers de configuration à enchaîner
automatiquement à chaque arrêt du serveur, ou après un délai d'inactivité
(aucun joueur connecté) si idle_timeout_minutes est configuré.

Format JSON (/aceserver/.rotation.json) :
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


def _rotation_path() -> Path:
    base = Path(os.environ.get("ACESERVER_DIR", "/aceserver"))
    return base / ".rotation.json"


def get_rotation() -> dict:
    p = _rotation_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return {**_DEFAULT_ROTATION, **data}
        except Exception:
            pass
    return dict(_DEFAULT_ROTATION)


def save_rotation(data: dict):
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
    _rotation_path().write_text(json.dumps({
        "enabled": bool(data.get("enabled", False)),
        "cycle":   bool(data.get("cycle",   False)),
        "configs": valid_configs,
        "idle_timeout_minutes": idle_timeout_minutes,
    }))


def get_next_config(current_config: str) -> str | None:
    """
    Retourne le nom du prochain fichier de config à démarrer, ou None si le
    roulement est terminé (fin de liste sans cycle, ou feature désactivée).
    """
    rot = get_rotation()
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
