"""Classement ELO des pilotes (à titre informatif, dans l'esprit de Low Fuel Motorsport).

Chaque course (session de type course, au moins deux pilotes humains identifiés par leur SteamID) met à
jour le niveau de chaque participant en le comparant à tous les autres : on gagne des points en battant
mieux classé que soi, on en perd en perdant contre moins bien classé. Calcul rejoué dans l'ordre
chronologique depuis tout l'historique ; rien n'est stocké (résultat mis en cache 60 s).

Règles :
  - niveau de départ 1500 ; ELO classique (échelle 400) ;
  - un pilote qui a parcouru moins de la moitié des tours du leader est « non classé » : il perd contre
    tous les classés, et deux non-classés ne se comparent pas ;
  - petite grille = peu de confiance : variation × 0,5 à 2 pilotes, × 0,75 à 3, × 1 à partir de 4 ;
  - 5 premières courses = provisoire (K plus fort, 48 au lieu de 32) ;
  - une course dont le leader a fait moins de 3 tours est ignorée.

Refus de participation (préparé, désactivé par défaut) : RATING_ENFORCE=true et RATING_MIN_TO_JOIN=N
ajoutent à la liste noire du serveur de jeu les pilotes DÉFINITIFS (au moins RATING_MIN_RACES courses)
dont le niveau est sous N. Les pilotes provisoires ne sont jamais refusés."""
import os
import threading
import time

START = 1500.0
K_NORMAL = 32.0
K_PROVISIONAL = 48.0
PROVISIONAL_RACES = 5
FINISH_RATIO = 0.5
MIN_LEADER_LAPS = 3
SCALE = 400.0
_TTL_S = 60.0

_lock = threading.Lock()
_cache: list | None = None
_cache_at = 0.0


def expected(r_a: float, r_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((r_b - r_a) / SCALE))


def _field_factor(n: int) -> float:
    return min(1.0, 0.25 * n)


def compute(races) -> dict:
    """``races`` : liste chronologique de (identifiant de session, date, résultat décodé).
    Retourne {steamid: statistiques}."""
    players: dict[str, dict] = {}

    def get(pid, nick):
        p = players.get(pid)
        if p is None:
            p = players[pid] = {"player_id": pid, "nickname": nick or pid, "rating": START, "races": 0, "wins": 0,
                                "podiums": 0, "last_delta": 0.0, "peak": START, "history": []}
        if nick:
            p["nickname"] = nick
        return p

    for sid, when, parsed in races:
        if not parsed.get("is_race"):
            continue
        field = []
        for d in parsed.get("standings", []):
            pid = str(d.get("player_id") or "").strip()
            laps = int(d.get("laps_count") or d.get("race_laps_count") or 0)
            if pid and laps > 0:
                field.append((pid, d.get("nickname"), laps, int(d.get("position") or 0)))
        if len(field) < 2:
            continue
        leader_laps = max(f[2] for f in field)
        if leader_laps < MIN_LEADER_LAPS:
            continue
        # positions fiables : on reclasse par position déclarée (ex æquo improbable)
        field.sort(key=lambda f: f[3] or 10_000)
        finished = {f[0]: f[2] >= FINISH_RATIO * leader_laps for f in field}
        order = {f[0]: i for i, f in enumerate(field)}
        before = {pid: get(pid, nick)["rating"] for pid, nick, _l, _p in field}
        factor = _field_factor(len(field))
        deltas = {}
        for pid, nick, _laps, _pos in field:
            diffs = []
            for pid2, _n2, _l2, _p2 in field:
                if pid2 == pid:
                    continue
                f1, f2 = finished[pid], finished[pid2]
                if not f1 and not f2:
                    continue
                if f1 and f2:
                    score = 1.0 if order[pid] < order[pid2] else 0.0
                else:
                    score = 1.0 if f1 else 0.0
                diffs.append(score - expected(before[pid], before[pid2]))
            if diffs:
                p = players[pid]
                k = K_PROVISIONAL if p["races"] < PROVISIONAL_RACES else K_NORMAL
                deltas[pid] = k * factor * sum(diffs) / len(diffs)
        for pid, nick, _laps, _pos in field:
            p = players[pid]
            p["races"] += 1
            d = deltas.get(pid, 0.0)
            p["rating"] += d
            p["last_delta"] = d
            p["peak"] = max(p["peak"], p["rating"])
            pos = order[pid] + 1
            if pos == 1 and finished[pid]:
                p["wins"] += 1
            if pos <= 3 and finished[pid]:
                p["podiums"] += 1
            p["history"].append({"session": sid, "date": when.isoformat(timespec="minutes") if when else "",
                                 "rating": round(p["rating"]), "delta": round(d, 1), "position": pos})
    return players


def rank(players: dict) -> list[dict]:
    out = []
    for p in players.values():
        q = dict(p)
        q["rating"] = round(p["rating"])
        q["last_delta"] = round(p["last_delta"], 1)
        q["peak"] = round(p["peak"])
        q["provisional"] = p["races"] < PROVISIONAL_RACES
        q["history"] = p["history"][-12:]
        out.append(q)
    out.sort(key=lambda p: (p["provisional"], -p["rating"], p["nickname"].lower()))
    return out


def build_rating(load_rows) -> list[dict]:
    """Classement ELO (cache 60 s). ``load_rows`` retourne les SessionResult."""
    global _cache, _cache_at
    with _lock:
        if _cache is not None and time.monotonic() - _cache_at < _TTL_S:
            return _cache
    from app.services.results_parser import get_parsed
    races = []
    for r in load_rows():
        try:
            parsed = get_parsed(r)
        except Exception:
            continue
        if parsed.get("is_race"):
            races.append((r.id, r.received_at, parsed))
    ranking = rank(compute(races))
    with _lock:
        _cache, _cache_at = ranking, time.monotonic()
    return ranking


def invalidate_cache() -> None:
    global _cache, _cache_at
    with _lock:
        _cache, _cache_at = None, 0.0


def for_player(ranking: list[dict], steam_id: str):
    return next((p for p in ranking if p["player_id"] == steam_id), None)


# ── Refus de participation (préparé) ─────────────────────────────────────────

def enforce() -> bool:
    return os.environ.get("RATING_ENFORCE", "false").lower() == "true"


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def min_to_join() -> int:
    return _int_env("RATING_MIN_TO_JOIN", 0)


def min_races() -> int:
    return _int_env("RATING_MIN_RACES", PROVISIONAL_RACES)


def blocked_ids(ranking: list[dict]) -> list[str]:
    """SteamID des pilotes définitifs sous le seuil ; vide si le refus n'est pas activé."""
    if not enforce() or min_to_join() <= 0:
        return []
    need = max(min_races(), PROVISIONAL_RACES)
    return sorted(p["player_id"] for p in ranking if p["races"] >= need and p["rating"] < min_to_join())
