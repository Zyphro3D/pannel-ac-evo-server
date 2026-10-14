"""Options de course (course au tour, arrêt obligatoire, pénalités) — arguments construits pour le serveur."""
import copy

from app.services import config_builder as cb
from app.services.encoder import decode_config
from app.services.server_config import _default_config


def _config(game_type="GameModeType_RACE_WEEKEND", **race):
    cfg = copy.deepcopy(_default_config())
    cfg["Event"]["SelectedSessionTypeValue"] = game_type
    cfg["Sessions"]["RaceSession"]["Length"] = 1800
    cfg["Sessions"]["RaceSession"].update(race)
    return cfg


def _game_config(cfg):
    return decode_config(cb.build_launch_args(cfg)[1])["game_config"]


def test_par_defaut_aucun_champ_supplementaire():
    gc = _game_config(_config())
    assert gc["race_duration"] == 1800 and gc["race_duration_type"] == "GameModeSelectionDuration_TIME"
    for key in ("mandatory_pit_stop", "requires_tyre_change", "requires_refuelling", "pit_window",
                "enable_custom_penalities", "car_cut_tyres_out", "warning_trigger_countdown", "time_penalty_ms"):
        assert key not in gc


def test_ancienne_config_sans_les_nouveaux_champs_reste_identique():
    cfg = _config()
    for k in ("RaceByLaps", "Laps", "MandatoryPitStop", "PitStopTyreChange", "PitStopRefuel", "PitWindow",
              "CustomPenalties", "CarCutTyresOut", "WarningCountdown", "TimePenaltySeconds"):
        cfg["Sessions"]["RaceSession"].pop(k, None)
    assert _game_config(cfg) == _game_config(_config())


def test_course_au_nombre_de_tours():
    gc = _game_config(_config(RaceByLaps=True, Laps=12))
    assert gc["race_duration"] == 12 and gc["race_duration_type"] == "GameModeSelectionDuration_LAPS"
    assert _game_config(_config(RaceByLaps=True, Laps=0))["race_duration_type"] == "GameModeSelectionDuration_TIME"
    assert _game_config(_config(RaceByLaps=False, Laps=12))["race_duration"] == 1800


def test_arret_obligatoire():
    gc = _game_config(_config(MandatoryPitStop=True, PitStopTyreChange=True, PitStopRefuel=False, PitWindow=600))
    assert gc["mandatory_pit_stop"] is True and gc["requires_tyre_change"] is True
    assert gc["requires_refuelling"] is False and gc["pit_window"] == 600
    assert _game_config(_config(MandatoryPitStop=True, PitWindow=5))["pit_window"] == 10          # borne basse
    assert _game_config(_config(MandatoryPitStop=True, PitWindow="n'importe quoi"))["pit_window"] == 600


def test_arret_obligatoire_ignore_en_course_au_tour():
    """Le serveur calcule mal la fenêtre en course au tour (vérifié) : on ne l'envoie pas."""
    gc = _game_config(_config(RaceByLaps=True, Laps=8, MandatoryPitStop=True, PitStopTyreChange=True))
    assert gc["race_duration_type"] == "GameModeSelectionDuration_LAPS"
    assert "mandatory_pit_stop" not in gc and "pit_window" not in gc


def test_penalites_personnalisees_en_weekend_et_en_session_unique():
    expected = {"enable_custom_penalities": True, "car_cut_tyres_out": 2, "warning_trigger_countdown": 5,
                "time_penalty_ms": 10000}
    opts = dict(CustomPenalties=True, CarCutTyresOut=2, WarningCountdown=5, TimePenaltySeconds=10)
    gc = _game_config(_config(**opts))
    assert {k: gc[k] for k in expected} == expected
    gc = _game_config(_config("GameModeType_PRACTICE", **opts))
    assert {k: gc[k] for k in expected} == expected
    assert "practice_duration" in gc


def test_valeurs_hors_bornes_ramenees_aux_bornes():
    gc = _game_config(_config(CustomPenalties=True, CarCutTyresOut=9, WarningCountdown=0, TimePenaltySeconds=9999))
    assert (gc["car_cut_tyres_out"], gc["warning_trigger_countdown"], gc["time_penalty_ms"]) == (4, 1, 120000)
