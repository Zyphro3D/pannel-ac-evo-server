"""Tests pour app/services/results_parser.py::parse_result_file.

parse_result_file() est une fonction pure (dict -> dict), testée sans app Flask.
Fixture synthétique dans fixtures/qualify_sample.json — 2 pilotes, 3 tours,
flags=2 (tour propre) pour tous les tours de la fixture.
"""
import json
from pathlib import Path

import pytest

from app.services.results_parser import parse_result_file

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def qualify_data():
    return json.loads((FIXTURES / "qualify_sample.json").read_text())


def test_parse_result_file_does_not_raise(qualify_data):
    parse_result_file(qualify_data)


def test_session_metadata(qualify_data):
    result = parse_result_file(qualify_data)
    assert result["track"] == "Brands Hatch"
    assert result["layout"] == "GP"
    assert result["session_type"] == "Qualify"
    assert result["is_race"] is False


def test_standings_order_and_positions(qualify_data):
    result = parse_result_file(qualify_data)
    standings = result["standings"]
    assert len(standings) == 2
    assert standings[0]["position"] == 1
    assert standings[0]["nickname"] == "AliceT"
    assert standings[1]["position"] == 2
    assert standings[1]["nickname"] == "BobT"


def test_best_lap_picks_the_clean_lap_matching_time_standings(qualify_data):
    result = parse_result_file(qualify_data)
    alice = result["standings"][0]
    # Alice a 2 tours (96500 et 95123) ; time_standings donne 95123 comme référence.
    assert alice["best_lap_ms"] == 95123
    assert alice["best_splits_ms"] == [31000, 32000, 32123]
    assert alice["laps_count"] == 2


def test_session_best_is_the_fastest_clean_lap_across_all_drivers(qualify_data):
    result = parse_result_file(qualify_data)
    assert result["session_best_ms"] == 95123


def test_gap_to_leader_is_computed_for_non_race_sessions(qualify_data):
    result = parse_result_file(qualify_data)
    bob = result["standings"][1]
    assert bob["gap_ms"] == 95890 - 95123


def test_parser_does_not_strip_pii_itself(qualify_data):
    """player_id est retiré au niveau de la route API pour les non-admins
    (app/routes/api.py::_strip_pii_for_pilot), pas dans le parser lui-même."""
    result = parse_result_file(qualify_data)
    assert result["standings"][0]["player_id"] == "76561190000000001"


def test_unknown_session_type_defaults_to_non_race():
    data = {"session_type": "", "drivers": [], "cars": [], "driver_standings": [],
            "time_standings": [], "car_standings": [], "laps": []}
    result = parse_result_file(data)
    assert result["is_race"] is False
    assert result["standings"] == []
