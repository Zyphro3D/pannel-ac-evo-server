from app.services.server_config import _default_config


def test_circuit_par_defaut_au_format_du_catalogue():
    # Le serveur attend le nom du catalogue (events_*.json : « Brands Hatch ») : avec le slug
    # « brands_hatch », il plantait au tout premier démarrage (« Trying to load a message with an empty path »).
    track, layout, event_name, length = _default_config()["Event"]["SelectedTrackValue"].split("|")
    assert (track, layout, event_name, length) == ("Brands Hatch", "GP", "GP Time Attack", "3916")
