"""L'URL de résultats envoyée au jeu vise le serveur lancé, pas celle figée dans la config de bibliothèque."""
import copy

from app.services import config_builder as cb
from app.services.encoder import decode_config
from app.services.server_config import _default_config


def _url(cfg, **kw):
    return decode_config(cb.build_launch_args(cfg, **kw)[0])["results_post_url"]


def test_config_figee_sur_le_serveur_1_lancee_sur_le_serveur_2():
    cfg = copy.deepcopy(_default_config())
    cfg["Server"]["ResultsPostUrl"] = "http://panel:4300/api/results/ingest?server_id=1"
    url = _url(cfg, server_id=2)
    assert "server_id=2" in url and "server_id=1" not in url


def test_sans_server_id_l_url_de_la_config_est_gardee():
    cfg = copy.deepcopy(_default_config())
    cfg["Server"]["ResultsPostUrl"] = "http://panel:4300/api/results/ingest?server_id=1"
    assert _url(cfg) == "http://panel:4300/api/results/ingest?server_id=1"
