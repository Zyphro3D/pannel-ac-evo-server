"""Mods par serveur : un mod n'est posé (et donc exigé des joueurs) que sur les serveurs choisis.

Vécu en production (25/11) : 6 voitures envoyées pour le seul serveur drift ont bloqué l'accès à
tous les serveurs (« Content unavailable or version mismatch »), la bibliothèque étant commune."""
import json
import os
from pathlib import Path

import pytest
from flask import Flask

from app.services import mod_assign, server_docker


@pytest.fixture
def app_ctx(tmp_path):
    app = Flask(__name__)
    app.config["MODS_DIR"] = str(tmp_path / "mods")
    app.config["ACESERVER_DIR"] = str(tmp_path)
    (tmp_path / "mods").mkdir()
    for stem, car in (("drift_v1.4", "preset_drift_mech_1"), ("gt_v2", "preset_gt_mech_1")):
        (tmp_path / "mods" / f"{stem}.kspkg").write_bytes(b"kspkg " + stem.encode())
        (tmp_path / "mods" / f"{stem}.json").write_text(json.dumps({"cars": [{"name": car}]}))
    with app.app_context():
        yield tmp_path


def _files(path: Path) -> set[str]:
    return {p.name for p in path.iterdir()} if path.exists() else set()


def test_mod_sans_affectation_reste_sur_tous_les_serveurs(app_ctx):
    # Installations qui se mettent à jour : rien ne doit disparaître de leurs serveurs.
    assert mod_assign.servers_of("gt_v2.kspkg", [1, 2, 3]) == [1, 2, 3]


def test_mod_affecte_pose_seulement_sur_son_serveur(app_ctx):
    mod_assign.set_servers("drift_v1.4.kspkg", [3])
    mod_assign.set_servers("gt_v2.kspkg", [])
    for sid in (1, 3):
        mod_assign.sync_server_mods(sid, [1, 3])
    assert _files(app_ctx / "mods-server" / "1") == set()
    assert _files(app_ctx / "mods-server" / "3") == {"drift_v1.4.kspkg", "drift_v1.4.json"}
    # Lien physique : pas de copie de plusieurs centaines de Mo par serveur
    assert os.path.samefile(app_ctx / "mods" / "drift_v1.4.kspkg", app_ctx / "mods-server" / "3" / "drift_v1.4.kspkg")


def test_mod_retire_quitte_le_dossier_du_serveur(app_ctx):
    mod_assign.set_servers("drift_v1.4.kspkg", [3])
    mod_assign.sync_server_mods(3, [3])
    mod_assign.set_servers("drift_v1.4.kspkg", [])
    mod_assign.sync_server_mods(3, [3])
    assert "drift_v1.4.kspkg" not in _files(app_ctx / "mods-server" / "3")


def test_serveur_supprime_ignore(app_ctx):
    mod_assign.set_servers("drift_v1.4.kspkg", [3, 9])
    assert mod_assign.servers_of("drift_v1.4.kspkg", [1, 3]) == [3]


def test_voitures_proposees_par_serveur(app_ctx):
    mod_assign.set_servers("drift_v1.4.kspkg", [3])
    mod_assign.set_servers("gt_v2.kspkg", [])
    assert mod_assign.allowed_mod_car_names(3, [1, 3]) == {"preset_drift_mech_1"}
    assert mod_assign.allowed_mod_car_names(1, [1, 3]) == set()


def test_oubli_a_la_suppression(app_ctx):
    mod_assign.set_servers("drift_v1.4.kspkg", [3])
    mod_assign.forget("drift_v1.4.kspkg")
    assert "drift_v1.4.kspkg" not in mod_assign.load_assignments()


def test_fichier_d_affectations_abime_ne_bloque_rien(app_ctx):
    (app_ctx / "mods" / ".servers.json").write_text("{pas du json")
    assert mod_assign.servers_of("gt_v2.kspkg", [1, 2]) == [1, 2]


def test_plus_de_bibliotheque_commune_montee_dans_les_conteneurs():
    override = server_docker._compose_override_yaml(
        [type("S", (), {"id": 2, "container_name": "c2", "http_port": 8082, "tcp_port": 9701, "udp_port": 9701})()], "img")
    assert "ACE-Server/mods" not in override
    compose = (Path(server_docker.__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ACE-Server/mods" not in compose
    entry = (Path(server_docker.__file__).parents[2] / "entrypoint.aceserver.sh").read_text(encoding="utf-8")
    assert '/aceserver/mods-server/$SERVER_ID' in entry


def test_nom_du_mod_garde_son_point():
    from app.services.mod_scanner import _SAFE_STEM_RE
    assert _SAFE_STEM_RE.sub("_", "hinas_drift_club_ae86_v1.4") == "hinas_drift_club_ae86_v1.4"
    assert _SAFE_STEM_RE.sub("_", "a b/c") == "a_b_c"


def test_page_mods_et_route_d_affectation(admin_client):
    assert admin_client.get("/mods").status_code == 200
    r = admin_client.post("/mods/inconnu.kspkg/servers", data={"servers": ["1"]})
    assert r.status_code == 404


class _Upload:
    def __init__(self, name, data=b"pack"):
        self.filename, self._data = name, data

    def save(self, path):
        Path(path).write_bytes(self._data)


def test_pack_un_seul_par_serveur(app_ctx):
    assert mod_assign.save_pack(3, _Upload("HDC Client 1.4.zip"))["filename"] == "HDC_Client_1.4.zip"
    mod_assign.save_pack(3, _Upload("autre.7z"))
    assert mod_assign.get_pack(3).name == "autre.7z"
    assert [p.name for p in mod_assign.packs_dir(3).iterdir()] == ["autre.7z"]
    assert mod_assign.save_pack(3, _Upload("virus.exe")) == {"ok": False, "error": "bad_extension"}


def test_fichier_public_seulement_si_affecte_au_serveur(app_ctx, monkeypatch):
    monkeypatch.setattr(mod_assign, "enabled_server_ids", lambda: [1, 3])
    mod_assign.set_servers("drift_v1.4.kspkg", [3])
    mod_assign.set_servers("gt_v2.kspkg", [])
    mod_assign.save_pack(3, _Upload("pack.zip"))
    assert mod_assign.public_file(3, "drift_v1.4.kspkg") is not None
    assert mod_assign.public_file(3, "pack.zip") is not None
    assert mod_assign.public_file(1, "drift_v1.4.kspkg") is None      # pas affecté au serveur 1
    assert mod_assign.public_file(1, "pack.zip") is None              # pack du serveur 3
    assert mod_assign.public_file(3, "gt_v2.kspkg") is None
    assert mod_assign.public_file(3, "drift_v1.4.json") is None       # seulement .kspkg et le pack
    assert mod_assign.public_file(3, "../mods/drift_v1.4.kspkg") is None
    assert mod_assign.public_file(3, ".servers.json") is None


def test_liste_publique(app_ctx):
    from types import SimpleNamespace
    mod_assign.set_servers("drift_v1.4.kspkg", [3])
    mod_assign.set_servers("gt_v2.kspkg", [])
    out = mod_assign.public_downloads([SimpleNamespace(id=1), SimpleNamespace(id=3)])
    assert [e["server"].id for e in out] == [3]
    assert [m["filename"] for m in out[0]["mods"]] == ["drift_v1.4.kspkg"]


def test_page_publique_sans_connexion(admin_client):
    anon = admin_client.application.test_client()
    assert anon.get("/downloads").status_code == 200
    assert anon.get("/downloads/1/inconnu.kspkg").status_code == 404
    assert anon.get("/").status_code == 200


def test_pack_accepte_les_gros_fichiers():
    # Vécu en production (25/11) : pack de 223 Mo refusé (413), la route gardait le plafond de 64 Mo.
    from app import _BIG_BODY_ENDPOINTS
    assert _BIG_BODY_ENDPOINTS["admin.mods_pack_upload"] >= 3 * 1024 ** 3
