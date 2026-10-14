"""Contrôle d'accès : construction du fichier d'engagés lu par le serveur de jeu (données synthétiques)."""
from types import SimpleNamespace as NS

from app.services import access_control as ac

A, B, C, D = "76561190000000001", "76561190000000002", "76561190000000003", "76561190000000004"
BOT = "76561190000000099"


def rule(steam_id, banned=False, ballast=0, restrictor=0.0):
    return NS(steam_id=steam_id, banned=banned, ballast=ballast, restrictor=restrictor)


def test_steam_id_valide():
    assert ac.valid_steam_id(A) and ac.valid_steam_id(" " + A + " ")
    for bad in ("", "123", "7656119000000000", "76561190000000001x", "abc", None, "86561190000000001"):
        assert not ac.valid_steam_id(bad), bad


def test_bornes_lest_et_restricteur():
    assert ac.clamp_rule(999, 5) == (100, 0.2)
    assert ac.clamp_rule(-5, -1) == (0, 0.0)
    assert ac.clamp_rule("abc", "x") == (0, 0.0)
    assert ac.clamp_rule("20", "0.1") == (20, 0.1)


def test_sans_option_pas_de_liste_blanche():
    doc = ac.build_document([rule(A, ballast=20, restrictor=0.1), rule(B, banned=True)], [C], False)
    assert doc == {"version": 1, "entrylist": [{"steamid": A, "ballast": 20, "restrictor": 0.1}],
                   "steamid_blacklist": [B]}
    assert "steamid_whitelist" not in doc


def test_pilotes_approuves_seulement():
    doc = ac.build_document([rule(D, ballast=10)], [A, B], True, always_allow=[BOT])
    assert doc["steamid_whitelist"] == sorted([A, B, D, BOT])


def test_un_banni_est_exclu_de_la_liste_blanche_et_de_la_liste_des_engages():
    doc = ac.build_document([rule(A, banned=True, ballast=50)], [A, B], True)
    assert A in doc["steamid_blacklist"] and A not in doc["steamid_whitelist"]
    assert doc["entrylist"] == []                         # pas de handicap pour un banni


def test_liste_blanche_jamais_vide_sinon_le_serveur_ouvre_a_tous():
    """Vérifié sur le serveur : une liste blanche vide = aucun filtre. On met un SteamID inexistant."""
    doc = ac.build_document([], [], True)
    assert doc["steamid_whitelist"] == ["0"]


def test_identifiants_invalides_ignores():
    doc = ac.build_document([rule("abc", banned=True), rule("123", ballast=5)], ["xyz", A], True, always_allow=["nope"])
    assert doc["entrylist"] == [] and "steamid_blacklist" not in doc
    assert doc["steamid_whitelist"] == [A]


def test_handicap_nul_n_apparait_pas():
    assert ac.build_document([rule(A)], [], False)["entrylist"] == []


def test_rating_blocked_players_go_to_the_blacklist():
    from types import SimpleNamespace as NS
    from app.services import access_control as ac
    rules = [NS(steam_id="76561198000000001", banned=False, ballast=0, restrictor=0.0)]
    doc = ac.build_document(rules, ["76561198000000001", "76561198000000002"], True,
                            rating_blocked=["76561198000000002", "pas-un-id"])
    assert "76561198000000002" in doc["steamid_blacklist"] and "pas-un-id" not in doc["steamid_blacklist"]
    assert "76561198000000002" not in doc["steamid_whitelist"]          # la liste noire l'emporte, fichier net
    doc2 = ac.build_document(rules, [], False, rating_blocked=["76561198000000003"])
    assert doc2["steamid_blacklist"] == ["76561198000000003"]           # fonctionne sans liste blanche
