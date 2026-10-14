"""Session déduite des logs du serveur de jeu — lignes de log et configuration synthétiques."""
from app.services import session_tracker as st

CFG = {"PracticeSession": {"Length": 1800, "MinWaitingForPlayers": 10},
       "QualifyingSession": {"Length": 600, "MinWaitingForPlayers": 10},
       "RaceSession": {"Length": 0, "MinWaitingForPlayers": 10}}
T0 = "2026-10-13 17:00:00.000"


def _created(name="Practice", ts=T0):
    return st.apply_event(None, st.parse_event(f"[{ts}] [gameplay] [info] TimeAttackRemote {name} created", ts))


def _epoch(ts=T0):
    return st.log_epoch(ts)


def test_reconnait_les_lignes_de_session():
    assert st.parse_event("[x] [gameplay] [info] InstantRaceRemote Race created", "t")["name"] == "Race"
    assert st.parse_event("[x] [gameplay] [info] WAIT_LAST_LAP: overtime: 10000", "t")["type"] == "session_last_lap"
    assert st.parse_event("[x] [gameplay] [info] END_SESSION All cars pitted", "t")["type"] == "session_end"
    for line in ("[x] [gameplay] [info] chaging GameMode", "[x] [gameplay] [info] Changing GameMode. Alive Connections: 2",
                 "[x] [server] [info] OnExitGamemode", "[x] [server] [info] Start Server Mon serveur"):
        assert st.parse_event(line, "t")["type"] == "session_reset", line
    assert st.parse_event("[x] [gameplay] [info] New lap carId 1: 1:30.000", "t") is None


def test_attente_puis_session_en_cours_avec_temps_restant():
    s = _created()
    avant = st.describe(s, _epoch() + 5, 0, CFG)                     # 5 s après la création : attente du départ
    assert avant == {"name": "Practice", "phase": "waiting", "remaining_ms": None}
    en_cours = st.describe(s, _epoch() + 11.4 + 60, 0, CFG)          # 60 s après le départ effectif (10 s + 1,4 s)
    assert en_cours["phase"] == "running" and en_cours["remaining_ms"] == (1800 - 60) * 1000


def test_decalage_horaire_du_conteneur():
    s = _created()
    # logs à l'heure d'été d'Europe (UTC+2) : l'horodatage lu comme UTC est en avance de 2 h
    now_utc = _epoch() - 7200 + 11.4 + 100
    assert st.describe(s, now_utc, -7200, CFG)["remaining_ms"] == (1800 - 100) * 1000


def test_dernier_tour_et_fin():
    s = _created("Qualifying")
    s = st.apply_event(s, st.parse_event("[x] [gameplay] [info] WAIT_LAST_LAP: overtime: 10000", T0))
    assert st.describe(s, _epoch() + 700, 0, CFG) == {"name": "Qualifying", "phase": "last_lap", "remaining_ms": None}
    s = st.apply_event(s, st.parse_event("[x] [gameplay] [info] END_SESSION All cars pitted", T0))
    assert st.describe(s, _epoch() + 800, 0, CFG)["phase"] == "ended"


def test_sans_limite_de_temps_ou_session_inconnue():
    race = _created("Race")
    assert st.describe(race, _epoch() + 500, 0, CFG)["remaining_ms"] is None        # Length 0
    inconnue = _created("HotLap")
    assert st.describe(inconnue, _epoch() + 500, 0, CFG)["remaining_ms"] is None    # pas dans la config


def test_le_temps_restant_ne_devient_pas_negatif():
    s = _created()
    assert st.describe(s, _epoch() + 99999, 0, CFG)["remaining_ms"] == 0


def test_reinitialisation_et_cas_vides():
    s = _created()
    assert st.apply_event(s, st.parse_event("[x] [server] [info] OnExitGamemode", T0)) is None
    assert st.apply_event(None, st.parse_event("[x] [gameplay] [info] WAIT_LAST_LAP", T0)) is None   # sans session
    assert st.describe(None, 0, 0, CFG) is None
    assert st.log_epoch("pas une date") is None
