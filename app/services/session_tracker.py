"""Session en cours (nom, phase, temps restant) déduite des logs du serveur de jeu.

Le serveur de jeu n'envoie son état de session qu'aux clients qui ont une voiture : le bot TCP
du panel n'en reçoit aucun. Ses logs, eux, marquent les moments clés :

  « TimeAttackRemote Practice created » / « InstantRaceRemote Race created »  début d'une session
  « WAIT_LAST_LAP: overtime: …»                                              dernier tour
  « END_SESSION …»                                                           session terminée
  « chaging GameMode » / « Changing GameMode » / « OnExitGamemode » / « Start Server … »
                                                                             fin de la session

Le temps restant est une estimation : début effectif = création + MinWaitingForPlayers de la
config (+ ~1,4 s observés) ; fin = début + Length de la session (0 = pas de limite).
"""
import re
from calendar import timegm
from datetime import datetime

# Horodatage des logs du serveur de jeu : « [2026-10-13 17:20:23.308] » (heure du conteneur)
_TS_FMT = "%Y-%m-%d %H:%M:%S.%f"
_MIN_WAIT_EXTRA_S = 1.4        # écart constaté entre MinWaitingForPlayers et le début réel

RE_CREATED = re.compile(r"^\[[^\]]*\] \[gameplay\] \[info\] (?:TimeAttack|InstantRace)Remote (\w+) created")
RE_LAST_LAP = re.compile(r"^\[[^\]]*\] \[gameplay\] \[info\] WAIT_LAST_LAP")
RE_END = re.compile(r"^\[[^\]]*\] \[gameplay\] \[info\] END_SESSION")
RE_RESET = re.compile(r"^\[[^\]]*\] (?:\[gameplay\] \[info\] (?:chaging|Changing) GameMode|\[server\] \[info\] OnExitGamemode"
                      r"|\[server\] \[info\] Start Server )")

# Nom de session dans le log → clé de la section de la config du panel
_CONFIG_KEYS = {"practice": "PracticeSession", "qualifying": "QualifyingSession",
                "qualify": "QualifyingSession", "warmup": "WarmupSession", "race": "RaceSession"}


def parse_event(line: str, ts: str) -> dict | None:
    """Reconnaît une ligne de log liée aux sessions. ``ts`` = horodatage de la ligne."""
    if m := RE_CREATED.search(line):
        return {"type": "session_created", "ts": ts, "name": m.group(1)}
    if RE_LAST_LAP.search(line):
        return {"type": "session_last_lap", "ts": ts}
    if RE_END.search(line):
        return {"type": "session_end", "ts": ts}
    if RE_RESET.search(line):
        return {"type": "session_reset", "ts": ts}
    return None


def apply_event(session: dict | None, ev: dict) -> dict | None:
    """Fait avancer l'état de session : retourne le nouvel état (None = aucune session)."""
    t = ev["type"]
    if t == "session_created":
        return {"name": ev["name"], "created_ts": ev["ts"], "ended": False, "last_lap": False}
    if session is None:
        return None
    if t == "session_last_lap":
        return {**session, "last_lap": True}
    if t == "session_end":
        return {**session, "ended": True}
    if t == "session_reset":
        return None
    return session


def log_epoch(ts: str) -> float | None:
    """Horodatage du log lu comme s'il était en UTC (le décalage réel est ajouté par l'appelant)."""
    try:
        return timegm(datetime.strptime(ts, _TS_FMT).timetuple()) + int(ts[-3:]) / 1000.0
    except (ValueError, TypeError):
        return None


def describe(session: dict | None, now_utc: float, offset_s: float, sessions_cfg: dict) -> dict | None:
    """Description publique de la session : {name, phase, remaining_ms} ou None.

    phase : waiting (avant le début effectif), running, last_lap, ended.
    remaining_ms : None sans limite de temps, hors phase running, ou si l'horloge est inconnue."""
    if not session:
        return None
    key = _CONFIG_KEYS.get(session["name"].lower())
    cfg = (sessions_cfg or {}).get(key, {}) if key else {}
    out = {"name": session["name"], "phase": "running", "remaining_ms": None}
    if session.get("ended"):
        out["phase"] = "ended"
        return out
    if session.get("last_lap"):
        out["phase"] = "last_lap"
        return out
    created = log_epoch(session["created_ts"])
    if created is None:
        return out
    start = created + offset_s + float(cfg.get("MinWaitingForPlayers") or 0) + _MIN_WAIT_EXTRA_S
    if now_utc < start:
        out["phase"] = "waiting"
        return out
    length_s = float(cfg.get("Length") or 0)
    if length_s > 0:
        out["remaining_ms"] = max(0, int((start + length_s - now_utc) * 1000))
    return out
