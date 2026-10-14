"""Contacts en direct, lus dans les logs du serveur de jeu.

Le serveur écrit chaque collision rapportée par un client, mais seulement au niveau de log
« debug » du journal ``gameplay`` (option LIVE_COLLISIONS : le panel lance alors le serveur avec
``-log_debug gameplay``, une douzaine de lignes par session) :

  [gameplay] [debug] Collision between <voiture> and <voiture>, collider Car, damage true
  [gameplay] [debug] Collision between <voiture> and Wall, damage false     (pas de voiture adverse)

Les voitures sont identifiées par un GUID, rattaché à un pilote par la ligne « Car [guid] #N for
driver NOM [steamid] » écrite à son arrivée. Ni la vitesse d'impact ni la position ne sont
journalisées : elles restent disponibles après coup dans le fichier de résultats.
"""
import re

RE_CAR = re.compile(r"\[server\] \[info\] Car \[([0-9a-f]{16})-([0-9a-f]{16})\] #\d+ for driver (.+?) \[\d+\]")
RE_COLLISION = re.compile(
    r"\[gameplay\] \[debug\] Collision between ([0-9a-f-]{36}) and "
    r"(?:([0-9a-f-]{36}), collider (\w+)|(\w+)), damage (true|false)")

_DEDUP_S = 2.0        # chaque voiture impliquée rapporte le même contact
_MAX_EVENTS = 50


def _norm(guid: str) -> str:
    return guid.replace("-", "").lower()


def parse_line(line: str) -> dict | None:
    """{"type": "car", guid, name} ou {"type": "collision", guid, other, collider, damage}."""
    if m := RE_CAR.search(line):
        return {"type": "car", "guid": m.group(1) + m.group(2), "name": m.group(3)}
    if m := RE_COLLISION.search(line):
        return {"type": "collision", "guid": _norm(m.group(1)),
                "other": _norm(m.group(2)) if m.group(2) else None,
                "collider": m.group(3) or m.group(4), "damage": m.group(5) == "true"}
    return None


def new_state() -> dict:
    return {"cars": {}, "events": []}


def apply_event(state: dict, ev: dict, ts: str, epoch: float | None) -> None:
    """Met à jour ``state`` (cars: guid → pilote ; events: contacts, du plus ancien au plus récent)."""
    if ev["type"] == "car":
        state["cars"][ev["guid"]] = ev["name"]
        return
    driver = state["cars"].get(ev["guid"])
    other = state["cars"].get(ev["other"]) if ev["other"] else None
    if driver is None:
        return                      # voiture inconnue (bot, ancien log) : rien à afficher
    key = (frozenset((ev["guid"], ev["other"] or "")), ev["collider"])
    last = state["events"][-1] if state["events"] else None
    for prev in reversed(state["events"][-6:]):
        if prev["_key"] == key and epoch is not None and prev["_epoch"] is not None \
                and abs(epoch - prev["_epoch"]) <= _DEDUP_S:
            prev["damage"] = prev["damage"] or ev["damage"]
            return
    state["events"].append({"ts": ts, "driver": driver, "other": other, "collider": ev["collider"],
                            "damage": ev["damage"], "_key": key, "_epoch": epoch})
    del state["events"][:-_MAX_EVENTS]


def public_events(state: dict, now_utc: float, offset_s: float, limit: int = 15) -> list[dict]:
    """Derniers contacts, du plus récent au plus ancien, avec leur ancienneté en secondes."""
    out = []
    for e in reversed(state["events"][-limit:]):
        age = None if e["_epoch"] is None else max(0, int(now_utc - (e["_epoch"] + offset_s)))
        out.append({"driver": e["driver"], "other": e["other"], "collider": e["collider"],
                    "damage": e["damage"], "age_s": age})
    return out
