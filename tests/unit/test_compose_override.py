from types import SimpleNamespace

from app.services import server_docker


def _srv(i):
    return SimpleNamespace(id=i, container_name=f"ace-server-{i}", http_port=8080 + i, tcp_port=9698 + i, udp_port=9698 + i)


def test_override_declare_le_vrai_nom_du_volume_wine():
    # Vécu en production (24/10) : le volume s'appelle « pannel-ac-evo-server_wine_prefix_2 » ;
    # déclaré « wine_prefix_2 » sans nom, compose refusait tout le projet (« external volume … not found »).
    text = server_docker._compose_override_yaml([_srv(2), _srv(3)], "img", "pannel-ac-evo-server_wine_prefix")
    volumes = text.split("\nvolumes:\n", 1)[1]
    assert volumes == ("  wine_prefix_2:\n    external: true\n    name: pannel-ac-evo-server_wine_prefix_2\n"
                       "  wine_prefix_3:\n    external: true\n    name: pannel-ac-evo-server_wine_prefix_3\n")
    assert "      - wine_prefix_3:/root/.wine\n" in text


def test_meme_nom_qu_a_la_creation_du_container():
    assert server_docker._wine_volume_name("pannel-ac-evo-server_wine_prefix", 2) == "pannel-ac-evo-server_wine_prefix_2"
    assert server_docker._wine_volume_name("", 2) == "wine_prefix_2"


def test_aucun_serveur_additionnel():
    assert server_docker._compose_override_yaml([], "img").endswith("services: {}\nvolumes: {}\n")
