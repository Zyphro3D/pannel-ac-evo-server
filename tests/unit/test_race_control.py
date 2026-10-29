"""Direction de course : tour de chaque contact, bilan par pilote, réservé aux admins, résumé Discord."""
from app.services import collisions as c
from test_collisions import CARS, D1, D2, _feed

HIT = "[2026-10-14 01:00:{s:02d}.000] [gameplay] [debug] Collision between {a} and {b}, damage {d}"
CAR_HIT = "[2026-10-14 01:00:{s:02d}.000] [gameplay] [debug] Collision between {a} and {b}, collider Car, damage {d}"


def test_tour_du_contact_et_bilan_par_pilote():
    st = c.new_state()
    for line, _ in CARS:
        c.apply_event(st, c.parse_line(line), "2026-10-14 01:00:00.000", 0.0)
    c.note_lap(st, D1)                                         # Alice a bouclé un tour
    for i, (line, dmg) in enumerate([(CAR_HIT, "true"), (HIT, "false"), (HIT, "true"), (HIT, "false")]):
        b = D2 if line is CAR_HIT else "Wall"
        ev = c.parse_line(line.format(s=10 + 10 * i, a=D1, b=b, d=dmg))
        assert c.apply_event(st, ev, f"2026-10-14 01:00:{10 + 10 * i:02d}.000", 10.0 + 10 * i) is not None
    rc = c.race_control(st)
    first = rc["events"][-1]
    assert (first["time"], first["lap"], first["driver"], first["other"], first["damage"]) == \
        ("01:00:10", 2, "Alice", "Bob", True)
    alice, bob = rc["tally"]
    assert (alice["driver"], alice["contacts"], alice["cars"], alice["damage"], alice["repeat"]) == \
        ("Alice", 4, 1, 2, True)
    assert (bob["driver"], bob["contacts"], bob["repeat"]) == ("Bob", 1, False)


def test_doublon_de_l_autre_voiture_ne_compte_pas():
    st = _feed(CARS + [(CAR_HIT.format(s=10, a=D1, b=D2, d="false"), 10.0)])
    ev = c.parse_line(CAR_HIT.format(s=10, a=D2, b=D1, d="true"))
    assert c.apply_event(st, ev, "ts", 10.3) is None and st["events"][0]["damage"] is True


def test_reserve_aux_admins_et_jamais_en_cache(admin_client, monkeypatch):
    from app.routes import live
    monkeypatch.setenv("LIVE_COLLISIONS", "true")
    monkeypatch.setattr(live._live_state, "build_state_cached",
                        lambda sid: {"leaderboard": [], "player_count": 0, "collisions_raw": _feed(CARS)})
    resp = admin_client.get("/api/timing")
    assert resp.get_json()["race_control"] == {"events": [], "tally": []}
    assert resp.headers["Cache-Control"] == "private, no-store"
    anon = admin_client.application.test_client().get("/api/timing")
    assert anon.get_json()["race_control"] is None and "no-store" not in anon.headers.get("Cache-Control", "")


def test_resume_discord_par_minute(monkeypatch):
    from app.services import ace_tcp_client as t
    from app.services import discord_notifier as dn
    sent = []
    monkeypatch.setattr(dn, "notify_contacts", lambda contacts, **kw: sent.append(contacts))
    monkeypatch.setenv("LIVE_COLLISIONS", "true")
    monkeypatch.setenv("DISCORD_NOTIFY_CONTACTS", "true")
    cl = t._get_client(97)
    cl.update(contacts=None, contacts_buffer=[], contacts_since=0.0)
    for line, _ in CARS:
        t._on_contact_line(line, cl, 97)
    assert t._on_contact_line(CAR_HIT.format(s=10, a=D1, b=D2, d="true"), cl, 97) is True
    t._on_contact_line(HIT.format(s=20, a=D1, b="Wall", d="false"), cl, 97)    # sans dégâts : ignoré
    t._flush_contacts(cl, 97)
    assert sent == []                                       # moins d'une minute : on attend
    cl["contacts_since"] -= 61
    t._flush_contacts(cl, 97)
    assert sent == [[{"driver": "Alice", "other": "Bob", "collider": "Car", "lap": 1}]]


def test_message_discord(monkeypatch):
    from app.services import discord_notifier as dn
    out = []
    monkeypatch.setattr(dn, "_resolve_url", lambda *a, **k: "https://discord.com/api/webhooks/1/x")
    monkeypatch.setattr(dn, "_post_to", lambda url, payload, on_sent=None: out.append(payload))
    dn.notify_contacts([{"driver": "Alice", "other": "Bob", "collider": "Car", "lap": 3},
                        {"driver": "Bob", "other": None, "collider": "Wall", "lap": 4}], server_name="GT3")
    e = out[-1]["embeds"][0]
    assert e["title"] == "💥 2 contacts avec dégâts"
    assert e["description"] == "**Alice** ↔ **Bob** · tour 3\n**Bob** → mur · tour 4"
