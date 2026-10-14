"""Incidents (collisions) et sanctions extraits d'un fichier de résultats — données synthétiques."""
from app.services.results_parser import parse_result_file


from helpers import _guid, _hit, _session


def _by_name(parsed):
    return {d["nickname"]: d for d in parsed["standings"]}


def test_sans_incident_rien_ne_casse():
    parsed = parse_result_file(_session())
    assert parsed["contacts"] == [] and parsed["big_hits"] == [] and parsed["penalties"] == []
    assert not parsed["has_incidents"] and not parsed["has_penalties"]
    assert _by_name(parsed)["Alice"]["incident_stats"]["total"] == 0


def test_contact_rapporte_par_les_deux_voitures_compte_une_fois():
    hits = [_hit(11, 5000.0, x=100.0), _hit(12, 5050.0, x=101.0), _hit(11, 5200.0, x=100.5)]
    parsed = parse_result_file(_session(collisions=hits))
    assert len(parsed["contacts"]) == 1
    contact = parsed["contacts"][0]
    assert {d["nickname"] for d in contact["drivers"]} == {"Alice", "Bob"}
    assert contact["hits"] == 3
    drivers = _by_name(parsed)
    assert drivers["Alice"]["incident_stats"]["car"] == 1
    assert drivers["Bob"]["incident_stats"]["car"] == 1


def test_deux_contacts_distants_dans_le_temps_restent_separes():
    hits = [_hit(11, 5000.0), _hit(12, 5050.0), _hit(11, 90000.0), _hit(12, 90040.0)]
    parsed = parse_result_file(_session(collisions=hits))
    assert len(parsed["contacts"]) == 2


def test_contact_signale_par_une_seule_voiture():
    parsed = parse_result_file(_session(collisions=[_hit(11, 5000.0)]))
    assert len(parsed["contacts"]) == 1
    assert [d["nickname"] for d in parsed["contacts"][0]["drivers"]] == ["Alice"]


def test_mur_objet_et_gros_chocs():
    hits = [_hit(11, 1000.0, "Wall", impact=80.0), _hit(11, 2000.0, "Wall", impact=5.0, damage=False),
            _hit(12, 3000.0, "Object", impact=40.0)]
    parsed = parse_result_file(_session(collisions=hits))
    alice, bob = _by_name(parsed)["Alice"]["incident_stats"], _by_name(parsed)["Bob"]["incident_stats"]
    assert (alice["wall"], alice["total"], alice["damage"], alice["max_impact_kmh"]) == (2, 2, 1, 80.0)
    assert (bob["object"], bob["total"]) == (1, 1)
    assert [h["impact_kmh"] for h in parsed["big_hits"]] == [80.0, 40.0]     # trié, seuil 30 km/h
    assert alice["per_lap"] == 1.0                                           # 2 incidents / 2 tours


def test_sanctions_en_cours_et_levees():
    pen = {"session_penalties": [{
        "car_id": _guid(12),
        "pending_penalties": [{"penalty_data": {"type": "PenaltyType_Time_Penalty_Seconds", "penalty_time_ms": 5000},
                               "investigation": "InvestigationType_Racecar_Cut", "given_lap_count": 2,
                               "given_session_time_ms": "421000"}],
        "cleared_penalties": [{"penalty_data": {"type": "PenaltyType_Warning"},
                               "investigation": "InvestigationType_Racecar_Cut", "given_lap_count": 1,
                               "given_session_time_ms": "100000", "cleared_session_time_ms": "900000"}],
    }]}
    parsed = parse_result_file(_session(penalties=pen))
    assert parsed["has_penalties"]
    first, second = parsed["penalties"]                      # triées par moment
    assert (first["status"], first["nickname"], first["given_ms"]) == ("cleared", "Bob", 100000)
    assert (second["status"], second["time_ms"], second["lap"]) == ("pending", 5000, 2)
    assert _by_name(parsed)["Bob"]["penalty_count"] == 2
    assert _by_name(parsed)["Alice"]["penalty_count"] == 0


def test_fichier_ancien_sans_les_cles():
    data = _session()
    data.pop("collisions"); data.pop("penalty_collection")
    parsed = parse_result_file(data)
    assert parsed["contacts"] == [] and not parsed["has_penalties"]
    assert parsed["incidents_reported"] is False          # ancienne version du serveur : à ne pas compter « propre »
    assert parse_result_file(_session())["incidents_reported"] is True


def test_donnees_incompletes_ne_plantent_pas():
    data = _session(collisions=[{"collider": "Car"}, {"car_id": _guid(11)}],
                    penalties={"session_penalties": [{"pending_penalties": [{}]}, {"car_id": _guid(11), "cleared_penalties": [{}]}]})
    parsed = parse_result_file(data)
    assert isinstance(parsed["penalties"], list)
