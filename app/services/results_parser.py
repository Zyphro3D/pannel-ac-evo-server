"""
Parse et importe les fichiers de résultats générés par AssettoCorsaEVOServer.

Format découvert le 30/04/2026 — champs clés :
  drivers[]      : guid {a,b} → first_name, last_name, nickname, player_id, nation
  cars[]         : car_id {a,b} → model_displayname, race_number
  laps[]         : driver_key {a,b}, car_key {a,b}, time (ms), split [ms,ms,ms], flags
  time_standings : meilleur temps par pilote (même ordre que driver_standings)
  driver_standings: liste de guids ordonnée par classement
"""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def _ms_to_laptime(ms: int) -> str:
    if not ms:
        return "—"
    minutes, rem = divmod(ms, 60_000)
    seconds, millis = divmod(rem, 1_000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"


def _guid_key(g: dict) -> tuple:
    return (str(g.get("a", "")), str(g.get("b", "")))


def parse_result_file(data: dict) -> dict:
    """Transforme le JSON brut en dict structuré prêt à afficher."""
    driver_map = {_guid_key(d["guid"]): d for d in data.get("drivers", [])}
    car_map    = {_guid_key(c["car_id"]): c for c in data.get("cars", [])}

    # Regrouper les tours par pilote
    from collections import defaultdict
    driver_laps: dict[tuple, list] = defaultdict(list)
    for lap in data.get("laps", []):
        dk = _guid_key(lap["driver_key"])
        driver_laps[dk].append(lap)

    # Classement dans l'ordre du serveur
    standings = []
    for idx, guid_dict in enumerate(data.get("driver_standings", [])):
        dk = _guid_key(guid_dict)
        driver = driver_map.get(dk, {})
        laps   = driver_laps.get(dk, [])

        best_ms = data.get("time_standings", [])[idx] if idx < len(data.get("time_standings", [])) else 0
        if not best_ms and laps:
            best_ms = min(l["time"] for l in laps)

        best_lap_laps = [l for l in laps if l["time"] == best_ms] if best_ms else []
        best_splits = best_lap_laps[0]["split"] if best_lap_laps else []

        # Voiture associée au meilleur tour
        car = {}
        if best_lap_laps:
            car = car_map.get(_guid_key(best_lap_laps[0]["car_key"]), {})

        standings.append({
            "position":     idx + 1,
            "nickname":     driver.get("nickname") or f"{driver.get('first_name','')} {driver.get('last_name','')}".strip(),
            "full_name":    f"{driver.get('first_name','')} {driver.get('last_name','')}".strip(),
            "nation":       driver.get("nation", ""),
            "player_id":    driver.get("player_id", ""),
            "car":          car.get("model_displayname", ""),
            "race_number":  car.get("race_number", 0),
            "laps_count":   len(laps),
            "best_lap_ms":  best_ms,
            "best_lap":     _ms_to_laptime(best_ms),
            "splits":       [_ms_to_laptime(s) for s in best_splits],
            "all_laps":     [
                {
                    "lap":    i + 1,
                    "time":   _ms_to_laptime(l["time"]),
                    "time_ms": l["time"],
                    "splits": [_ms_to_laptime(s) for s in l.get("split", [])],
                    "flags":  l.get("flags", 0),
                }
                for i, l in enumerate(laps)  # ordre chronologique
            ],
        })

    return {
        "track":        data.get("track_name", ""),
        "layout":       data.get("track_layout_name", ""),
        "session_type": data.get("session_type", ""),
        "server_name":  data.get("server_name", ""),
        "is_completed": data.get("is_completed", False),
        "standings":    standings,
    }


def import_result_file(path: Path, source: str = "file") -> bool:
    """Importe un fichier de résultats en base. Retourne True si importé."""
    from app.services.database import db
    from app.models import SessionResult

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as e:
        log.error("Impossible de lire %s : %s", path, e)
        return False

    parsed = parse_result_file(data)

    existing = SessionResult.query.filter_by(
        track=parsed["track"],
        session_type=parsed["session_type"],
        source=source,
        raw_json=raw,
    ).first()
    if existing:
        return False

    result = SessionResult(
        raw_json=raw,
        source=source,
        track=parsed["track"][:200],
        session_type=parsed["session_type"][:60],
    )
    db.session.add(result)
    db.session.commit()
    log.info("Résultats importés depuis %s (track=%s)", path.name, parsed["track"])
    return True


def scan_and_import(aceserver_dir: str):
    """Scanne le dossier aceserver pour des fichiers de résultats non encore importés."""
    base = Path(aceserver_dir)
    imported = 0
    for f in sorted(base.rglob("results_*.json")):
        if import_result_file(f, source="file"):
            imported += 1
    if imported:
        log.info("scan_and_import : %d nouveau(x) fichier(s) importé(s)", imported)
    return imported
