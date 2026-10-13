"""Noms de voitures : cars.json est la source principale (le paquet kspkg n'est plus lisible)."""
from app.services import kspkg_reader


def _reset():
    kspkg_reader._cars_json = {}
    kspkg_reader._cars_json_loaded_at = 0.0
    kspkg_reader._cars_json_warned = False


def test_nom_et_classe_depuis_cars_json(cars_app, monkeypatch):
    _reset()
    monkeypatch.setattr(kspkg_reader, "_ensure_loaded", lambda: None)  # pas de lecture du paquet
    with cars_app.app_context():
        assert kspkg_reader.get_car_name("preset_m4gt3_mech_1") == "BMW M4 GT3"
        assert kspkg_reader.get_preset_class("preset_m4gt3_mech_1") == "Standard"
        assert kspkg_reader.get_car_name("preset_cup_bop_1") == "Porsche 911 GT3 Cup"
        assert kspkg_reader.get_preset_class("preset_cup_bop_1") == "BOP Carrera Cup"


def test_nom_sans_separateur(cars_app, monkeypatch):
    _reset()
    monkeypatch.setattr(kspkg_reader, "_ensure_loaded", lambda: None)
    with cars_app.app_context():
        assert kspkg_reader.get_car_name("preset_sans_classe") == "Voiture Sans Classe"
        assert kspkg_reader.get_preset_class("preset_sans_classe") == ""


def test_repli_sur_le_slug_si_inconnu(cars_app, monkeypatch):
    _reset()
    monkeypatch.setattr(kspkg_reader, "_ensure_loaded", lambda: None)
    with cars_app.app_context():
        assert kspkg_reader.get_car_name("ks_bmw_m4_gt3") == "Bmw M4 GT3"


def test_hors_contexte_application_ne_plante_pas(monkeypatch):
    """get_car_name peut être appelé depuis un thread sans application Flask."""
    _reset()
    monkeypatch.setattr(kspkg_reader, "_ensure_loaded", lambda: None)
    assert kspkg_reader.get_car_name("ks_porsche_992_gt3_cup") == kspkg_reader.slug_to_name("ks_porsche_992_gt3_cup")
