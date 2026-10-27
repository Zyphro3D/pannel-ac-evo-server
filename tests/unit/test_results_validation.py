"""Un résultat aux champs mal typés est refusé à l'ingestion : enregistré, il cassait l'accueil et les
pages de résultats à chaque affichage."""
import copy

import pytest

from helpers import _session


@pytest.fixture
def ingest(admin_client):
    app = admin_client.application
    from app.services.netutil import ingest_token

    def _ingest(data):
        with app.app_context():
            url = f"/api/results/ingest?server_id=1&sig={ingest_token(1)}"
        return app.test_client().post(url, json=data, headers={"Host": "panel:4300"},
                                      environ_overrides={"REMOTE_ADDR": "172.19.0.5"})
    return _ingest


@pytest.mark.parametrize("mutate, field", [
    (lambda d: d["cars"][0].update(model_displayname=["x"]), "model_displayname"),
    (lambda d: d.update(track_layout_name={"x": 1}), "track_layout_name"),
    (lambda d: d["cars"][0].update(starting_position="3"), "starting_position"),
    (lambda d: d.update(laps={"pas": "une liste"}), "laps"),
])
def test_malformed_result_is_refused_and_pages_stay_up(admin_client, ingest, mutate, field):
    data = copy.deepcopy(_session())
    data["server_name"] = f"Validation {field}"      # hash distinct à chaque cas
    mutate(data)
    r = ingest(data)
    assert r.status_code == 400 and field in r.get_json()["field"]
    anon = admin_client.application.test_client()
    assert anon.get("/").status_code == 200
    assert anon.get("/results").status_code == 200


def test_well_formed_result_is_still_imported(ingest):
    data = copy.deepcopy(_session())
    data["server_name"] = "Validation OK"
    r = ingest(data)
    assert r.status_code == 200 and r.get_json()["imported"] == 1
