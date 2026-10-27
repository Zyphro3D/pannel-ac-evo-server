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


def test_serveur_additionnel_etiquete_comme_son_service_compose():
    # Vécu en production (24/10) : sans étiquettes propres, le container héritait de celles de l'image
    # (service « aceserver ») et compose refusait de créer server_2 (« name already in use »).
    assert server_docker._compose_labels("pannel-ac-evo-server", 2) == {
        "com.docker.compose.project": "pannel-ac-evo-server", "com.docker.compose.service": "server_2",
        "com.docker.compose.oneoff": "False"}
    assert server_docker._compose_labels("", 2) == {}


def test_serveurs_de_jeu_sans_le_env_du_panel(monkeypatch):
    from pathlib import Path
    compose = (Path(server_docker.__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    aceserver = compose.split("\n  aceserver:\n", 1)[1].split("\nvolumes:", 1)[0]
    assert "env_file:" not in aceserver
    assert "env_file:" not in server_docker._compose_override_yaml([_srv(2)], "img")

    # création par l'API Docker : rien n'est recopié du container (qui a pu hériter du .env)
    ref = SimpleNamespace(attrs={"Image": "sha256:img", "Mounts": [], "NetworkSettings": {"Networks": {"n": {}}},
                                 "Config": {"Image": "img", "Env": ["SECRET_KEY=fuite", "WINEPREFIX=/root/.wine"]}})
    client = SimpleNamespace(containers=SimpleNamespace(get=lambda name: ref))
    monkeypatch.setattr(server_docker, "_get_docker_client", lambda: client)
    assert server_docker._inspect_reference_container()["env_vars"] == {}
