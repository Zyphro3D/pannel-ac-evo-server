"""Phase de session et temps restant, lus dans les messages temps réel du serveur de jeu.

Le serveur diffuse (message BroadcastStateMessage, puis dans l'état complet envoyé à la
connexion) une structure SessionPhaseData :
  session_phase_pairs[] : phase, end_timestamp {timestamp: double, ms de temps de mode de jeu},
                          is_set
  current_phase         : phase en cours
  current_gamemode_time : temps de mode de jeu au moment de l'envoi (ms, double)
  start_gamemode_time   : temps de mode de jeu au démarrage de la session

Temps restant = fin de la phase en cours − temps de mode de jeu courant. Le serveur n'envoie
ce message qu'à chaque changement de phase : entre deux messages on avance l'horloge avec
l'heure locale (``time.time()``).

Deux familles de phases (numéros observés dans le serveur de jeu 0.9.x) :
  TimeAttack (practice, qualification, hot lap…) : 0 attente, 10 session, 20 dernier tour,
      21/22 attente IA / stands, 30 terminée, 90 sortie
  InstantRace (course) : 0 attente des joueurs, 1-4 placement / feux, 11-14 départ lancé,
      50 session, 60/70 attente du leader / des autres, 71/72 attente IA / stands,
      80 terminée, 90 sortie
Les phases sont ramenées à six clés stables : waiting, starting, running, last_lap,
finishing, ended — c'est ce qu'affiche l'interface (libellés traduits côté page).
"""
import struct
import time

_TIME_ATTACK = {0: "waiting", 10: "running", 20: "last_lap", 21: "finishing", 22: "finishing",
                30: "ended", 90: "ended"}
_INSTANT_RACE = {0: "waiting", 1: "starting", 2: "starting", 3: "starting", 4: "starting",
                 11: "starting", 12: "starting", 13: "starting", 14: "starting",
                 50: "running", 60: "last_lap", 70: "last_lap", 71: "finishing", 72: "finishing",
                 80: "ended", 90: "ended"}
_MODES = {"time_attack": _TIME_ATTACK, "instant_race": _INSTANT_RACE}

# Message d'état complet envoyé à la connexion : (nom du message, numéro du champ session_data)
STATE_MESSAGES = {"TimeAttack.State.Game": ("time_attack", 1),
                  "InstantRace.State.Game": ("instant_race", 2)}
# Type de l'Any dans un BroadcastStateMessage
BROADCAST_TYPES = {"TimeAttack.SessionPhaseData": "time_attack",
                   "InstantRace.SessionPhaseData": "instant_race"}


def _double(raw) -> float | None:
    if isinstance(raw, (bytes, bytearray)) and len(raw) == 8:
        return struct.unpack("<d", raw)[0]
    return None


def parse_session_data(buf: bytes, mode: str, parse_proto) -> dict | None:
    """Décode un SessionPhaseData. ``parse_proto`` = décodeur protobuf minimal du client TCP
    (injecté pour éviter une dépendance circulaire). Retourne None si le message est vide."""
    if mode not in _MODES or not buf:
        return None
    f = parse_proto(buf)
    current = f.get(2, [0])[0]
    now_ms = _double(f.get(3, [None])[0])
    start_ms = _double(f.get(4, [None])[0])

    end_ms = None
    for pair_bytes in f.get(1, []):
        pf = parse_proto(pair_bytes)
        if pf.get(1, [0])[0] != current:
            continue
        ts = pf.get(2, [None])[0]
        if ts:
            end_ms = _double(parse_proto(ts).get(1, [None])[0])
        break
    # Une fin à 0 ou antérieure au temps courant = phase sans limite de temps (ex. course en tours).
    if end_ms is not None and (end_ms <= 0 or (now_ms is not None and end_ms < now_ms)):
        end_ms = None
    return {"mode": mode, "phase_raw": current, "phase": _MODES[mode].get(current, "running"),
            "end_ms": end_ms, "now_ms": now_ms, "start_ms": start_ms}


def with_remaining(stored: dict | None, received_at: float, now: float | None = None) -> dict | None:
    """Ajoute remaining_ms (None si la phase n'a pas de limite de temps) à une phase mémorisée."""
    if not stored:
        return None
    out = {"mode": stored["mode"], "phase": stored["phase"], "remaining_ms": None}
    if stored.get("end_ms") is not None and stored.get("now_ms") is not None:
        elapsed = ((now if now is not None else time.time()) - received_at) * 1000.0
        out["remaining_ms"] = max(0, int(stored["end_ms"] - stored["now_ms"] - elapsed))
    return out
