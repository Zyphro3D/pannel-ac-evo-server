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

RE_CAR = re.compile(r"^\[[^\]]*\] \[server\] \[info\] Car \[([0-9a-f]{16})-([0-9a-f]{16})\] #\d+ for driver (.+?) \[\d+\]")
RE_COLLISION = re.compile(
    r"^\[[^\]]*\] \[gameplay\] \[debug\] Collision between ([0-9a-f-]{36}) and "
    r"(?:([0-9a-f-]{36}), collider (\w+)|(\w+)), damage (true|false)")

_DEDUP_S = 2.0        # chaque voiture impliquée rapporte le même contact
_MAX_EVENTS = 200     # toute une session pour la direction de course
_REPEAT = 3           # contacts à partir desquels un pilote est signalé


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
    return {"cars": {}, "events": [], "laps": {}}


def note_lap(state: dict, car_id: str) -> None:
    """Un tour bouclé par cette voiture : les contacts suivants sont datés du tour d'après."""
    guid = _norm(car_id)
    state.setdefault("laps", {})[guid] = state["laps"].get(guid, 0) + 1


def apply_event(state: dict, ev: dict, ts: str, epoch: float | None) -> dict | None:
    """Met à jour ``state`` (cars: guid → pilote ; events: contacts, du plus ancien au plus récent).
    Retourne le contact s'il est nouveau (pas un doublon rapporté par l'autre voiture)."""
    if ev["type"] == "car":
        state["cars"][ev["guid"]] = ev["name"]
        return None
    driver = state["cars"].get(ev["guid"])
    other = state["cars"].get(ev["other"]) if ev["other"] else None
    if driver is None:
        return None                 # voiture inconnue (bot, ancien log) : rien à afficher
    key = (frozenset((ev["guid"], ev["other"] or "")), ev["collider"])
    for prev in reversed(state["events"][-6:]):
        if prev["_key"] == key and epoch is not None and prev["_epoch"] is not None \
                and abs(epoch - prev["_epoch"]) <= _DEDUP_S:
            prev["damage"] = prev["damage"] or ev["damage"]
            return None
    laps = state.get("laps", {})
    event = {"ts": ts, "driver": driver, "other": other, "collider": ev["collider"],
             "damage": ev["damage"], "lap": laps.get(ev["guid"], 0) + 1, "_key": key, "_epoch": epoch}
    state["events"].append(event)
    del state["events"][:-_MAX_EVENTS]
    return event


def public_events(state: dict, now_utc: float, offset_s: float, limit: int = 15) -> list[dict]:
    """Derniers contacts, du plus récent au plus ancien, avec leur ancienneté en secondes."""
    out = []
    for e in reversed(state["events"][-limit:]):
        age = None if e["_epoch"] is None else max(0, int(now_utc - (e["_epoch"] + offset_s)))
        out.append({"driver": e["driver"], "other": e["other"], "collider": e["collider"],
                    "damage": e["damage"], "age_s": age})
    return out


def race_control(state: dict, limit: int = 100) -> dict:
    """Vue « direction de course » (admins) : tous les contacts de la session, du plus récent au
    plus ancien, avec l'heure du journal et le tour, et le bilan par pilote (les plus impliqués
    d'abord, signalés à partir de _REPEAT contacts)."""
    events = [{"time": (e["ts"] or "")[11:19], "lap": e.get("lap"), "driver": e["driver"],
               "other": e["other"], "collider": e["collider"], "damage": e["damage"]}
              for e in reversed(state["events"][-limit:])]
    tally: dict[str, dict] = {}
    for e in state["events"]:
        for who in filter(None, (e["driver"], e["other"])):
            t = tally.setdefault(who, {"driver": who, "contacts": 0, "cars": 0, "damage": 0})
            t["contacts"] += 1
            t["cars"] += 1 if e["other"] else 0
            t["damage"] += 1 if e["damage"] else 0
    ranked = sorted(tally.values(), key=lambda t: (-t["contacts"], -t["damage"], t["driver"].lower()))
    for t in ranked:
        t["repeat"] = t["contacts"] >= _REPEAT
    return {"events": events, "tally": ranked}
