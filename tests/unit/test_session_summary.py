"""Récapitulatif Discord de fin de session — construction de l'embed (sans réseau)."""
from helpers import _guid, _hit, _session

from app.services import discord_notifier as dn
from app.services.results_parser import parse_result_file


def _penalties():
    return {"session_penalties": [{"car_id": _guid(12), "pending_penalties": [], "cleared_penalties": [
        {"penalty_data": {"type": "PenaltyType_Drive_Through"}, "investigation": "InvestigationType_Speeding",
         "given_lap_count": 1, "given_session_time_ms": "5000"}]}]}


def test_course_podium_incidents_et_sanctions():
    parsed = parse_result_file(_session(collisions=[_hit(11, 1000.0, "Wall", impact=50.0), _hit(12, 4000.0)],
                                        penalties=_penalties()))
    embed = dn.build_session_summary_embed(parsed, "Mon serveur",
                                           penalty_label=lambda r: "Drive-through", investigation_label=lambda r: "Excès de vitesse")
    assert embed["title"].startswith("🏁 Course terminée") and embed["author"]["name"] == "Mon serveur"
    assert "🥇 **Alice**" in embed["description"] and "🥈 **Bob**" in embed["description"]
    names = {f["name"]: f["value"] for f in embed["fields"]}
    assert "Alice" in names["Meilleur tour"] or "Bob" in names["Meilleur tour"]
    assert names["Contacts"].isdigit() and names["Chocs mur/objet"].isdigit()
    assert names["Sanctions (1)"] == "• **Bob** · Drive-through (Excès de vitesse)"


def test_session_sans_incident_ni_sanction_reste_courte():
    data = _session(race=False)
    data["time_standings"] = [90000, 90500]            # hors course : meilleur tour de chaque pilote
    embed = dn.build_session_summary_embed(parse_result_file(data))
    assert "Practice terminée" in embed["title"]
    assert [f["name"] for f in embed["fields"]] == ["Meilleur tour"]


def test_sanctions_regroupees_par_pilote_les_lourdes_d_abord():
    def pens(car, kinds):
        return {"car_id": _guid(car), "pending_penalties": [], "cleared_penalties": [
            {"penalty_data": {"type": k}, "investigation": "InvestigationType_Racecar_Cut",
             "given_lap_count": i, "given_session_time_ms": str(1000 * i)} for i, k in enumerate(kinds, 1)]}
    many = {"session_penalties": [pens(11, ["PenaltyType_Warning"] * 9),
                                  pens(12, ["PenaltyType_Warning", "PenaltyType_Disqualification"])]}
    embed = dn.build_session_summary_embed(parse_result_file(_session(penalties=many)))
    field = next(f for f in embed["fields"] if f["name"].startswith("Sanctions"))
    assert field["name"] == "Sanctions (11)"
    lines = field["value"].split("\n")
    assert lines[0].startswith("• **Bob**") and "PenaltyType_Disqualification (InvestigationType_Racecar_Cut)" in lines[0]   # lourde d'abord
    assert lines[1] == "• **Alice** · 9× PenaltyType_Warning"
    assert len(field["value"]) < 1024                                   # limite Discord d'un champ


def test_session_vide_rien_a_annoncer():
    data = _session(); data["driver_standings"] = []
    assert dn.build_session_summary_embed(parse_result_file(data)) is None
