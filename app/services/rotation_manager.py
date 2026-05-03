"""
Config Rotation — séquence de fichiers de configuration à enchaîner
automatiquement à chaque arrêt du serveur.

Format JSON (/aceserver/.rotation.json) :
  {
    "enabled": true,
    "cycle":   false,
    "configs": ["practice.json", "race-weekend.json"]
  }
"""
import json
import os
from pathlib import Path


def _rotation_path() -> Path:
    base = Path(os.environ.get("ACESERVER_DIR", "/aceserver"))
    return base / ".rotation.json"


def get_rotation() -> dict:
    p = _rotation_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"enabled": False, "cycle": False, "configs": []}


def save_rotation(data: dict):
    _rotation_path().write_text(json.dumps({
        "enabled": bool(data.get("enabled", False)),
        "cycle":   bool(data.get("cycle",   False)),
        "configs": [str(c) for c in data.get("configs", [])],
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
