"""Embeds Discord du panneau : contenu envoyé, sans réseau (envoi et modification interceptés)."""
from datetime import datetime

import pytest

from app.services import discord_notifier as dn

SID = "76561198000000001"


@pytest.fixture
def sent(monkeypatch):
    """Intercepte les envois : liste de (url, payload). `edits` reçoit les modifications."""
    class _Sent(list):
        edits: list

    out = _Sent()
    monkeypatch.setattr(dn, "_resolve_url", lambda *a, **k: "https://discord.com/api/webhooks/1/x")
    monkeypatch.setattr(dn, "_post_to", lambda url, payload, on_sent=None: out.append((url, payload, on_sent)))
    out.edits = []
    monkeypatch.setattr(dn, "_edit_message", lambda url, mid, payload: out.edits.append((mid, payload)))
    monkeypatch.setattr(dn, "_car_label", lambda raw: {"ks_bmw_m3": "BMW M3 E30 Evo III",
                                                       "ks_supra": "Toyota Supra Mk IV"}.get(raw, raw))
    for key in ("DISCORD_MSG_PLAYER_JOIN", "DISCORD_MSG_BEST_LAP", "PANEL_URL"):
        monkeypatch.delenv(key, raising=False)
    return out


def _embed(sent, i=-1):
    return sent[i][1]["embeds"][0]


def _weekend(track="Monza|GP", q=1200, w=600, r=2400, p=0):
    return {"Event": {"SelectedSessionTypeValue": "GameModeType_RACE_WEEKEND", "SelectedTrackValue": track,
                      "Cars": [{"IsSelected": True, "display_name": "BMW M4 GT3 - Standard"}]},
            "Sessions": {"PracticeSession": {"Length": p}, "QualifyingSession": {"Length": q},
                         "WarmupSession": {"Length": w}, "RaceSession": {"Length": r}}}


def test_serveur_en_entete_et_heure_native(sent):
    dn.notify_start(_weekend(), "gt3-monza.json", server_name="Zyphro GT3")
    e = _embed(sent)
    assert e["author"]["name"] == "Zyphro GT3" and "[" not in e["title"]
    assert e["title"] == "🏁 En ligne · Monza — GP"
    assert e["footer"]["text"] == "EvoPanel · gt3-monza.json"
    datetime.fromisoformat(e["timestamp"])
    assert "Practice" not in e["description"]               # session ignorée : absente
    assert "Qualif   20 min" in e["description"] and e["fields"][0]["value"] == "BMW M4 GT3"


def test_arrivee_une_ligne_lien_steam_et_numero_zero_masque(sent):
    dn.notify_player_join("Canuto_Donosor", "0", "ks_bmw_m3", SID, server_name="Trackday", online=2)
    e = _embed(sent)
    assert "title" not in e
    first, car, online = e["description"].split("\n")
    assert first == f"🟢 **[Canuto\\_Donosor](https://steamcommunity.com/profiles/{SID})** rejoint la piste"
    assert car == "BMW M3 E30 Evo III" and online == "-# 2 pilotes en ligne"


def test_depart_gris_avec_duree(sent):
    dn.notify_player_disconnect("Canuto", SID, 468, online=1)
    e = _embed(sent)
    assert e["color"] == dn._COLOR_GREY
    assert e["description"] == "🔴 **Canuto** quitte la piste après **7 min 48 s**\n-# 1 pilote en ligne"


def test_template_personnalise_toujours_applique(sent, monkeypatch):
    monkeypatch.setenv("DISCORD_MSG_PLAYER_JOIN", "Salut {name} ({num})")
    dn.notify_player_join("Bob", "12", "ks_bmw_m3", SID)
    assert _embed(sent)["description"].startswith("Salut Bob (12)\nBMW M3 E30 Evo III · n°12")


def test_meilleur_tour_rappelle_le_record_absolu(sent):
    dn.notify_best_lap("Pepi to", "08:56.571", "ks_bmw_m3", "Nordschleife", lap_ms=536571,
                       record=(466872, "Pepi to", "ks_supra"))
    e = _embed(sent)
    assert e["title"] == "⏱ Meilleur tour de la session"
    assert e["description"].startswith("# 08:56.571\n")
    assert e["fields"] == [{"name": "Record absolu", "inline": False,
                            "value": "`7:46.872` · Pepi to · Toyota Supra Mk IV"}]


def test_meilleur_tour_qui_bat_le_record(sent):
    dn.notify_best_lap("Pepi to", "07:46.872", "ks_supra", lap_ms=466872, record=(518457, "Shini", "ks_bmw_m3"))
    e = _embed(sent)
    assert e["title"] == "🏆 Nouveau record du serveur"
    assert e["fields"][0]["name"] == "Ancien record" and "−51.585 s" in e["fields"][0]["value"]


def test_action_admin_penalite(sent):
    dn.notify_admin_action("add_penalty", "Shini", "12", "dt", "florian")
    assert _embed(sent)["description"] == "🚩 **Drive-Through** pour **#12 Shini**\n-# décidé par florian"


def test_action_admin_sans_cible_ni_accolade_cassee(sent):
    dn.notify_admin_action("ballast", "Shini", "12", "{30}", "florian")
    assert _embed(sent)["description"].startswith("⚖️ **Ballast modifié** pour **#12 Shini** · {30}")
    dn.notify_admin_action("skip", "", "", "", "florian")
    assert _embed(sent)["description"].startswith("⏭️ **Phase suivante**\n")


def test_plantage_passe_au_vert_quand_le_serveur_repart(sent):
    dn._crashes.clear()
    dn.notify_crash("gt3.json", restarting=True, server_id=7, server_name="GT3")
    url, payload, on_sent = sent[-1]
    assert payload["embeds"][0]["color"] == dn._COLOR_RED and on_sent is not None
    on_sent("123456")
    dn.notify_crash_recovered(7, ok=True)
    mid, edit = sent.edits[-1]
    assert mid == "123456" and edit["embeds"][0]["title"] == "✅ Relancé après plantage"
    assert edit["embeds"][0]["color"] == dn._COLOR_GREEN


def test_plantage_relance_avant_reponse_discord(sent):
    dn._crashes.clear()
    dn.notify_crash("gt3.json", restarting=True, server_id=8)
    on_sent = sent[-1][2]
    dn.notify_crash_recovered(8, ok=False)       # Discord n'a pas encore répondu
    assert sent.edits == []
    on_sent("42")
    assert sent.edits[-1][1]["embeds"][0]["title"] == "💥 Plantage, la relance a échoué"


def test_inscription_lien_seulement_si_url_publique(sent, monkeypatch):
    driver = type("D", (), {"ingame_name": "Lou K."})()
    monkeypatch.setenv("PANEL_URL", "http://192.168.1.10:4300")
    dn.notify_new_registration(driver)
    assert "Ouvrir" not in _embed(sent)["description"]
    monkeypatch.setenv("PANEL_URL", "https://evo.exemple.fr/")
    dn.notify_new_registration(driver)
    assert "[Ouvrir la demande](https://evo.exemple.fr/drivers)" in _embed(sent)["description"]


def test_roulement_en_tableau(sent, monkeypatch):
    cfgs = {"a.json": _weekend("Imola|GP"), "b.json": _weekend("Monza|GP")}
    monkeypatch.setattr(dn, "_load_named_config", lambda name: cfgs.get(name))
    dn.notify_rotation_start(["a.json", "b.json"], cycle=True)
    desc = _embed(sent)["description"]
    assert "▶ 1  Imola — GP" in desc and "Q20 W10 R40" in desc
    assert desc.endswith("≈ **2 h 20**")


def test_changement_de_config(sent, monkeypatch):
    cfgs = {"a.json": _weekend("Imola|GP")}
    monkeypatch.setattr(dn, "_load_named_config", lambda name: cfgs.get(name))
    monkeypatch.setattr(dn, "_rotation_step", lambda name, sid: (2, 3))
    dn.notify_rotation_advance("a.json", "b.json", _weekend("Monza|GP"))
    e = _embed(sent)
    assert e["title"] == "⏭️ Place à Monza — GP"
    assert e["description"].split("\n") == ["~~Imola — GP~~ → **Monza — GP** · Race Weekend",
                                           "`Q 20 min` → `W 10 min` → `R 40 min`",
                                           "-# étape 2/3 du roulement · b.json"]


def test_nom_de_voiture_lisible_depuis_cars_json(cars_app):
    with cars_app.app_context():
        assert dn._car_label("preset_m4gt3_mech_1") == "BMW M4 GT3"
        assert dn._car_label("ks_toyota_supra_mkiv") == "Toyota Supra MKIV"     # inconnu : slug mis en forme
