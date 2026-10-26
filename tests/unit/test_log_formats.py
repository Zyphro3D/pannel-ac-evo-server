"""Formats des lignes de log du serveur de jeu lues par le panel.

Les regex existent en deux exemplaires (live_state.py pour l'état en direct, ace_tcp_client.py pour le
bot) : ce test vérifie que les deux reconnaissent les mêmes lignes et capturent la même chose.
Lignes = format du serveur 0.9.x (identifiants fictifs). À une mise à jour du jeu, ajouter les lignes
réelles de la nouvelle version (anonymisées) dans LINES : un test rouge = regex à corriger aux deux endroits.
"""
import pytest

from app.services import ace_tcp_client as tcp
from app.services import collisions, live_state, session_tracker

CAR = "4c1384235455c0d1-684cface53e6b58d"
CAR2 = "45a71af3e37f1857-ea48a6135e19399a"
STEAM = "76561190000000001"
TS = "[2026-10-24 18:30:00.555] "

LINES = {
    "connect": TS + f"[gameplay] [info] {STEAM} connected (true) on car ks_bmw_m4_gt3, with new carId {CAR}",
    "driver": TS + f"[server] [info] Car [{CAR}] #1 for driver Jean Testeur [{STEAM}]",
    "players": TS + "[server] [info] Server updated: 2 players",
    "disconn_car": TS + f"[gameplay] [info] Disconnected carId {CAR}",
    "newlap": TS + f"[gameplay] [info] New lap carId {CAR}: 02:08.232",
    "sector": TS + f"[gameplay] [info] [TimelineMessage] Split completed for car {CAR}: (41234 ms, splitindex 1) lap:3",
    "invalid": TS + f"[gameplay] [error] Couldn't create lap from opensplits (carId {CAR}): Splitcollection 1/3, split times: 2, ",
    "created": TS + "[gameplay] [info] TimeAttackRemote Qualifying created",
    "created_race": TS + "[gameplay] [info] InstantRaceRemote Race created",
    "last_lap": TS + "[gameplay] [info] WAIT_LAST_LAP: overtime: 10000",
    "end": TS + "[gameplay] [info] END_SESSION All cars ended",
    "reset_mode": TS + "[gameplay] [info] Changing GameMode. Alive Connections: 2",
    "reset_exit": TS + "[server] [info] OnExitGamemode",
    "reset_start": TS + "[server] [info] Start Server Zyphro GT3 Race",
    # format exe : « Collision between {} and {}, collider {}, damage {} » (GUID 8-4-4-4-12 ; ligne écrite avec -log_debug gameplay)
    "collision_car": TS + "[gameplay] [debug] Collision between 770fcbb6-371c-4541-8ed3-f538a0eb5af2 and "
                          "ff0399bc-a961-dbbc-63f8-b51418672f76, collider Car, damage true",
    "collision_wall": TS + "[gameplay] [debug] Collision between 770fcbb6-371c-4541-8ed3-f538a0eb5af2 and Wall, damage false",
}

# (regex de live_state, regex de ace_tcp_client, ligne)
PAIRS = [
    (live_state._RE_CONNECT, tcp._RE_CONNECT_LOG, "connect"),
    (live_state._RE_PLAYERS, tcp._RE_PLAYERS_LOG, "players"),
    (live_state._RE_DISCONN_CAR, tcp._RE_DISCONN_CAR_LOG, "disconn_car"),
    (live_state._RE_NEWLAP, tcp._RE_NEWLAP_LOG, "newlap"),
    (live_state._RE_SECTORC, tcp._RE_SECTOR_LOG, "sector"),
]


@pytest.mark.parametrize("rl, rt, key", PAIRS, ids=[p[2] for p in PAIRS])
def test_both_copies_agree(rl, rt, key):
    ml, mt = rl.search(LINES[key]), rt.search(LINES[key])
    assert ml and mt, f"{key} : ligne non reconnue ({'live_state' if not ml else 'ace_tcp_client'})"
    assert ml.groups() == mt.groups()


def test_connect_groups():
    m = live_state._RE_CONNECT.search(LINES["connect"])
    assert m.groups() == (STEAM, "ks_bmw_m4_gt3", CAR)


def test_driver_line():
    m = live_state._RE_DRIVER.search(LINES["driver"])
    assert m.groups() == (CAR, "1", "Jean Testeur", STEAM)
    mt = tcp._RE_DRIVER_LOG.search(LINES["driver"])
    assert mt.groups() == ("1", "Jean Testeur", STEAM)
    assert collisions.RE_CAR.search(LINES["driver"])


def test_lap_and_sector_values():
    assert live_state._RE_NEWLAP.search(LINES["newlap"]).group(2) == "02:08.232"
    assert live_state._RE_SECTORC.search(LINES["sector"]).groups() == (CAR, "41234", "1")
    assert tcp._RE_LAP_INVALID.search(LINES["invalid"]).group(1) == CAR


@pytest.mark.parametrize("key, rx", [
    ("created", session_tracker.RE_CREATED), ("created_race", session_tracker.RE_CREATED),
    ("last_lap", session_tracker.RE_LAST_LAP), ("end", session_tracker.RE_END),
    ("reset_mode", session_tracker.RE_RESET), ("reset_exit", session_tracker.RE_RESET),
    ("reset_start", session_tracker.RE_RESET),
])
def test_session_lines(key, rx):
    assert rx.search(LINES[key]), key


def test_version_mismatch_adapts_bot():
    line = TS + "[server] [error] Network Version Mismatch. Current: (Server:7, Protocol:9), Requested: (Server:6, Protocol:8)"
    c = {}
    tcp._on_version_mismatch(tcp._RE_VERSION_MISMATCH.search(line), c)
    assert (c["server_version"], c["protocol_version"]) == (7, 9)
    payload = tcp._build_connection_request({**c, "steam_id": STEAM, "car_model": "preset_x"}, {})
    assert bytes([0x28, 9, 0x30, 7]) in payload   # champ 5 = 9, champ 6 = 7
    default = tcp._build_connection_request({"steam_id": STEAM, "car_model": "preset_x"}, {})
    assert bytes([0x28, 8, 0x30, 6]) in default


def test_collision_lines():
    m = collisions.RE_COLLISION.search(LINES["collision_car"])
    assert m and m.group(3) == "Car" and m.group(5) == "true"
    m = collisions.RE_COLLISION.search(LINES["collision_wall"])
    assert m and m.group(4) == "Wall" and m.group(5) == "false"
