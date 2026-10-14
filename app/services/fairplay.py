"""Classement fair-play : incidents et sanctions par pilote sur l'historique des résultats.

Source : les incidents/sanctions déjà extraits de chaque fichier de résultats (voir
results_parser.build_incidents). Un pilote est identifié par son SteamID (player_id) ; les
pilotes sans SteamID (IA) sont ignorés. Le classement trie par « incidents par tour » croissant
parmi les pilotes ayant au moins MIN_LAPS tours, pour ne pas récompenser un pilote qui n'a
roulé que deux tours.
"""
import threading
import time

MIN_LAPS = 20          # en dessous : pilote listé mais non classé
_TTL_S = 60.0          # même durée de cache que le classement par circuit


_lock = threading.Lock()
_cache: dict | None = None
_cache_at = 0.0



def aggregate(parsed_sessions) -> list[dict]:
    """Cumule les statistiques par pilote à partir de résultats déjà décodés (dicts de
    parse_result_file). Retourne la liste non triée des pilotes avec leurs totaux."""
    drivers: dict[str, dict] = {}
    for parsed in parsed_sessions:
        if not parsed.get("incidents_reported", True):
            continue        # session d'une version du serveur qui n'enregistrait pas les incidents
        for drv in parsed.get("standings", []):
            pid = str(drv.get("player_id") or "").strip()
            if not pid:
                continue
            st = drv.get("incident_stats") or {}
            laps = int(drv.get("laps_count") or 0)
            d = drivers.setdefault(pid, {
                "player_id": pid, "nickname": drv.get("nickname") or pid, "sessions": 0, "laps": 0,
                "contacts": 0, "walls": 0, "objects": 0, "damage": 0, "max_impact_kmh": 0.0,
                "penalties": 0, "severe_penalties": 0,
            })
            d["nickname"] = drv.get("nickname") or d["nickname"]      # pseudo le plus récent / non vide
            d["sessions"] += 1
            d["laps"] += laps
            d["contacts"] += int(st.get("car", 0))
            d["walls"] += int(st.get("wall", 0))
            d["objects"] += int(st.get("object", 0))
            d["damage"] += int(st.get("damage", 0))
            d["max_impact_kmh"] = max(d["max_impact_kmh"], float(st.get("max_impact_kmh", 0.0)))
            d["penalties"] += int(drv.get("penalty_count", 0))
            d["severe_penalties"] += int(drv.get("severe_penalty_count", 0))
    for d in drivers.values():
        total = d["contacts"] + d["walls"] + d["objects"]
        d["incidents"] = total
        d["per_lap"] = round(total / d["laps"], 3) if d["laps"] else 0.0
        d["ranked"] = d["laps"] >= MIN_LAPS
    return list(drivers.values())


def rank(drivers: list[dict]) -> list[dict]:
    """Classés d'abord (incidents par tour croissants, puis plus de tours), non classés ensuite."""
    return sorted(drivers, key=lambda d: (not d["ranked"], d["per_lap"] if d["ranked"] else 0, -d["laps"],
                                          d["nickname"].lower()))


STATE_KEY = "fairplay_since"


def since():
    """Date de remise à zéro du compteur (None = tout l'historique). Les incidents des sessions
    reçues avant cette date ne comptent plus : le suivi n'était pas encore actif, il serait injuste
    de pénaliser des pilotes pour une période où ils ne pouvaient pas le savoir."""
    from app.services import panel_state
    return panel_state.get_datetime(STATE_KEY)


def reset(when=None) -> str:
    """Remet le compteur à zéro (maintenant par défaut) ; retourne la date ISO enregistrée."""
    from app.models import _utcnow
    from app.services import panel_state
    when = when or _utcnow()
    panel_state.set(STATE_KEY, when.isoformat())
    invalidate_cache()
    return when.isoformat()


def build_fairplay(load_rows) -> list[dict]:
    """Classement fair-play (cache de 60 s). ``load_rows`` : fonction qui retourne les
    enregistrements SessionResult, appelée seulement quand le cache est périmé."""
    global _cache, _cache_at
    with _lock:
        if _cache is not None and time.monotonic() - _cache_at < _TTL_S:
            return _cache
    from app.services.results_parser import get_parsed
    cutoff = since()
    parsed_all = []
    for r in load_rows():
        if cutoff is not None and r.received_at is not None and r.received_at < cutoff:
            continue
        try:
            parsed_all.append(get_parsed(r))
        except Exception:
            continue
    ranking = rank(aggregate(parsed_all))
    with _lock:
        _cache, _cache_at = ranking, time.monotonic()
    return ranking


def invalidate_cache() -> None:
    global _cache, _cache_at
    with _lock:
        _cache, _cache_at = None, 0.0
