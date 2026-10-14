from app.services import collisions as c

G1 = "770fcbb6371c4541" + "8ed3f538a0eb5af2"
G2 = "ff0399bca961dbbc" + "63f8b51418672f76"
D1 = "770fcbb6-371c-4541-8ed3-f538a0eb5af2"
D2 = "ff0399bc-a961-dbbc-63f8-b51418672f76"


def _feed(lines):
    st = c.new_state()
    for i, (line, t) in enumerate(lines):
        ev = c.parse_line(line)
        if ev:
            c.apply_event(st, ev, "ts", t)
    return st


CARS = [(f"[2026-10-14 01:00:00.000] [server] [info] Car [{G1[:16]}-{G1[16:]}] #84 for driver Alice [7656119800000001]", 0.0),
        (f"[2026-10-14 01:00:00.000] [server] [info] Car [{G2[:16]}-{G2[16:]}] #85 for driver Bob [7656119800000002]", 0.0)]


def test_contact_between_cars_is_deduplicated():
    st = _feed(CARS + [
        (f"[x] [gameplay] [debug] Collision between {D1} and {D2}, collider Car, damage false", 10.0),
        (f"[x] [gameplay] [debug] Collision between {D2} and {D1}, collider Car, damage true", 10.4)])
    assert len(st["events"]) == 1
    e = c.public_events(st, 20.0, 0.0)[0]
    assert (e["driver"], e["other"], e["collider"], e["damage"], e["age_s"]) == ("Alice", "Bob", "Car", True, 10)


def test_wall_without_other_car_and_separate_events():
    st = _feed(CARS + [
        (f"[x] [gameplay] [debug] Collision between {D1} and Wall, damage true", 10.0),
        (f"[x] [gameplay] [debug] Collision between {D1} and Wall, damage true", 30.0)])
    ev = c.public_events(st, 31.0, 0.0)
    assert len(ev) == 2 and ev[0]["age_s"] == 1 and ev[0]["other"] is None and ev[0]["collider"] == "Wall"


def test_unknown_car_ignored_and_other_lines_skipped():
    st = _feed([(f"[x] [gameplay] [debug] Collision between {D1} and Wall, damage true", 1.0),
                ("[x] [server] [info] Listening to TCP 9700", 2.0)])
    assert st["events"] == []


def test_launch_flags_follow_option(monkeypatch):
    from app.services import process_manager as pm
    monkeypatch.delenv("LIVE_COLLISIONS", raising=False)
    assert pm._extra_server_flags() == []
    monkeypatch.setenv("LIVE_COLLISIONS", "true")
    assert pm._extra_server_flags() == ["-log_debug", "gameplay"]


def test_build_state_exposes_contacts(monkeypatch):
    from app.services import live_state
    lines = [l for l, _ in CARS] + [
        f"[2026-10-14 01:00:10.000] [gameplay] [debug] Collision between {D1} and {D2}, collider Car, damage true"]
    monkeypatch.setattr(live_state, "iter_log_lines", lambda **kw: iter(lines))
    monkeypatch.setattr(live_state, "log_clock_offset", lambda sid=1: 0.0)
    st = live_state.build_state(1)
    evs = st["collisions_raw"]["events"]
    assert len(evs) == 1 and evs[0]["driver"] == "Alice" and evs[0]["other"] == "Bob"
