import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import panel_update

ROOT = Path(__file__).resolve().parents[2]
# Manifestes signés avec une clé de test jetable (pas de bibliothèque de signature nécessaire aux tests)
FX = json.loads((Path(__file__).parent / "fixtures" / "update_manifests.json").read_text())
PUB = FX["public_key"]


def test_manifeste_signe_accepte():
    m = panel_update.verify_manifest(FX["valid"]["body"].encode(), FX["valid"]["sig"], PUB)
    assert m["version"] == "9.9.9"


@pytest.mark.parametrize("case", ["tampered", "foreign_key"])
def test_contenu_falsifie_ou_autre_cle_refuses(case):
    with pytest.raises(ValueError, match="signature"):
        panel_update.verify_manifest(FX[case]["body"].encode(), FX[case]["sig"], PUB)


def test_la_cle_de_production_refuse_un_manifeste_de_test():
    with pytest.raises(ValueError, match="signature"):
        panel_update.verify_manifest(FX["valid"]["body"].encode(), FX["valid"]["sig"])


@pytest.mark.parametrize("i", range(len(FX["incoherent"])))
def test_manifeste_signe_mais_incoherent_refuse(i):
    case = FX["incoherent"][i]
    with pytest.raises(ValueError):
        panel_update.verify_manifest(case["body"].encode(), case["sig"], PUB)


def test_empreinte_de_l_archive(tmp_path):
    m = json.loads(FX["valid"]["body"])
    good, bad = tmp_path / "ok.zip", tmp_path / "ko.zip"
    good.write_text(FX["archive"])
    bad.write_text(FX["archive"] + "x")
    panel_update.verify_package(m, good)
    with pytest.raises(ValueError):
        panel_update.verify_package(m, bad)


def test_demande_et_etat(tmp_path, monkeypatch):
    monkeypatch.setattr(panel_update, "UPDATE_DIR", tmp_path)
    assert not panel_update.agent_installed() and panel_update.status() == {"pending": False}
    with pytest.raises(ValueError):
        panel_update.request_update("2.3.0; rm -rf /")
    panel_update.request_update("2.3.0")
    assert json.loads((tmp_path / "request.json").read_text())["version"] == "2.3.0"
    (tmp_path / "status.json").write_text('{"phase": "build", "version": "2.3.0"}')
    assert panel_update.status() == {"phase": "build", "version": "2.3.0", "pending": True}


def _run_verifier(tmp_path, archive: str, expected="v9.9.9"):
    (tmp_path / "m.json").write_text(FX["valid"]["body"])
    (tmp_path / "m.sig").write_text(FX["valid"]["sig"])
    (tmp_path / "a.zip").write_text(archive)
    # Hors de Flask, comme dans les scripts d'installation ; seule la clé est remplacée par celle de test
    code = (f"import sys; sys.path.insert(0, {str(ROOT / 'release')!r}); import verify_release as v; "
            f"v.panel_update.verify_manifest.__defaults__ = ({PUB!r},); "
            f"sys.exit(v.main([{str(tmp_path / 'm.json')!r}, {str(tmp_path / 'm.sig')!r}, "
            f"{str(tmp_path / 'a.zip')!r}, {expected!r}]))")
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def test_outil_de_verification_des_scripts(tmp_path):
    r = _run_verifier(tmp_path, FX["archive"])
    assert r.returncode == 0 and r.stdout.strip() == "9.9.9", r.stderr
    r = _run_verifier(tmp_path, FX["archive"] + "x")
    assert r.returncode == 1 and "refusé" in r.stderr
    r = _run_verifier(tmp_path, FX["archive"], expected="v9.9.8")
    assert r.returncode == 1


def test_routes_demande_seulement_une_version_verifiee_avec_agent(admin_client, tmp_path, monkeypatch):
    monkeypatch.setattr(panel_update, "UPDATE_DIR", tmp_path)
    panel_update._cache.clear()
    r = admin_client.post("/api/panel-update/start", json={"version": "9.9.9"})
    assert r.status_code == 409                                    # rien de vérifié
    panel_update._cache.update(available=True, latest="9.9.9")
    r = admin_client.post("/api/panel-update/start", json={"version": "9.9.9"})
    assert r.status_code == 409 and "Agent" in r.get_json()["error"]   # pas d'agent sur la machine
    (tmp_path / "agent.json").write_text("{}")
    assert admin_client.post("/api/panel-update/start", json={"version": "9.9.8"}).status_code == 409
    r = admin_client.post("/api/panel-update/start", json={"version": "9.9.9"})
    assert r.status_code == 200 and json.loads((tmp_path / "request.json").read_text())["version"] == "9.9.9"
    assert admin_client.post("/api/panel-update/start", json={"version": "9.9.9"}).status_code == 409   # déjà demandée
    st = admin_client.get("/api/panel-update/status").get_json()
    assert st["pending"] is True and st["current"]
    panel_update._cache.clear()


def test_page_parametres_affiche_la_section(admin_client, monkeypatch):
    monkeypatch.setattr(panel_update, "check_in_background", lambda current: None)
    page = admin_client.get("/settings?tab=panel")
    assert page.status_code == 200 and b'id="panel-update"' in page.data
