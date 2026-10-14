"""Phase de session et temps restant — messages protobuf fabriqués à la main (données synthétiques)."""
import struct

from app.services import session_phase
from app.services.ace_tcp_client import _field_bytes, _field_varint, _parse_proto


def _f64(num: int, value: float) -> bytes:
    return bytes([(num << 3) | 1]) + struct.pack("<d", value)


def _pair(phase: int | None, end: float | None, is_set_field: int = 3) -> bytes:
    out = b""
    if phase:                      # proto2 : une valeur 0 n'est pas obligatoirement écrite
        out += _field_varint(1, phase)
    if end is not None:
        out += _field_bytes(2, _f64(1, end))
    return out + _field_varint(is_set_field, 1)


def _session_data(pairs: list[bytes], current: int, now_ms: float, start_ms: float = 100.0) -> bytes:
    out = b"".join(_field_bytes(1, p) for p in pairs)
    return out + _field_varint(2, current) + _f64(3, now_ms) + _f64(4, start_ms)


def test_practice_trente_minutes_reste_exact():
    data = _session_data([_pair(None, 11478.8), _pair(10, 1811481.9), _pair(20, None)], current=10, now_ms=11481.9)
    r = session_phase.parse_session_data(data, "time_attack", _parse_proto)
    assert r["phase"] == "running" and r["phase_raw"] == 10
    assert round(r["end_ms"] - r["now_ms"]) == 1_800_000
    out = session_phase.with_remaining(r, received_at=1000.0, now=1000.0)
    assert out["remaining_ms"] == 1_800_000


def test_l_horloge_avance_avec_l_heure_locale():
    data = _session_data([_pair(10, 61000.0)], current=10, now_ms=1000.0)
    r = session_phase.parse_session_data(data, "time_attack", _parse_proto)
    out = session_phase.with_remaining(r, received_at=500.0, now=530.0)     # 30 s plus tard
    assert out["remaining_ms"] == 60_000 - 30_000


def test_le_temps_restant_ne_devient_jamais_negatif():
    data = _session_data([_pair(10, 5000.0)], current=10, now_ms=1000.0)
    r = session_phase.parse_session_data(data, "time_attack", _parse_proto)
    assert session_phase.with_remaining(r, received_at=0.0, now=100.0)["remaining_ms"] == 0


def test_course_phases_et_fin_sans_limite():
    # InstantRace : is_set est le champ 4 ; phase 50 = session ; 3 = feux
    data = _session_data([_pair(3, 2000.0, 4), _pair(50, None, 4)], current=50, now_ms=3000.0)
    r = session_phase.parse_session_data(data, "instant_race", _parse_proto)
    assert r["phase"] == "running" and r["end_ms"] is None
    assert session_phase.with_remaining(r, 0.0, 1.0)["remaining_ms"] is None
    start = _session_data([_pair(3, 5000.0, 4)], current=3, now_ms=2000.0)
    assert session_phase.parse_session_data(start, "instant_race", _parse_proto)["phase"] == "starting"


def test_phases_connues_et_inconnues():
    for raw, key in ((0, "waiting"), (20, "last_lap"), (22, "finishing"), (30, "ended")):
        d = _session_data([_pair(raw or None, None)], current=raw, now_ms=1.0)
        assert session_phase.parse_session_data(d, "time_attack", _parse_proto)["phase"] == key
    d = _session_data([], current=77, now_ms=1.0)
    assert session_phase.parse_session_data(d, "time_attack", _parse_proto)["phase"] == "running"   # inconnue : prudente


def test_messages_vides_ou_mode_inconnu():
    assert session_phase.parse_session_data(b"", "time_attack", _parse_proto) is None
    assert session_phase.parse_session_data(b"\x10\x0a", "hot_stint", _parse_proto) is None
    assert session_phase.with_remaining(None, 0.0) is None
