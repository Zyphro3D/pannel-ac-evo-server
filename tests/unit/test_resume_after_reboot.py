from app.services import process_manager as pm

BOOT = 1_800_000_000.0


class _Container:
    def __init__(self, status, finished):
        self.status = status
        self.attrs = {"State": {"FinishedAt": finished}}
        self.started = False

    def reload(self):
        pass

    def start(self):
        self.started = True


def _iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def _setup(monkeypatch, container, state=True):
    monkeypatch.setattr(pm, "_read_state", lambda sid: {"config": "default.json"} if state else {})
    monkeypatch.setattr(pm, "_get_aceserver_container", lambda sid: container)
    monkeypatch.setattr(pm, "_host_boot_time", lambda: BOOT)


def test_serveur_arrete_par_le_redemarrage_de_la_machine_est_relance(monkeypatch):
    c = _Container("exited", _iso(BOOT + 11))      # Docker l'a marqué sorti en redémarrant
    _setup(monkeypatch, c)
    assert pm._resume_after_host_reboot(1) and c.started


def test_plantage_apres_le_demarrage_n_est_pas_relance(monkeypatch):
    c = _Container("exited", _iso(BOOT + 3600))
    _setup(monkeypatch, c)
    assert not pm._resume_after_host_reboot(1) and not c.started


def test_arret_volontaire_n_est_pas_relance(monkeypatch):
    c = _Container("exited", _iso(BOOT + 11))
    _setup(monkeypatch, c, state=False)            # un arrêt volontaire efface le fichier d'état
    assert not pm._resume_after_host_reboot(1) and not c.started


def test_container_jamais_lance_ou_deja_en_marche(monkeypatch):
    c = _Container("created", "0001-01-01T00:00:00Z")
    _setup(monkeypatch, c)
    assert not pm._resume_after_host_reboot(1)
    c = _Container("running", _iso(BOOT + 11))
    _setup(monkeypatch, c)
    assert not pm._resume_after_host_reboot(1) and not c.started


def _launch_file(tmp_path, monkeypatch, url):
    import json
    from app.services.encoder import encode_serverconfig
    monkeypatch.setenv("ACESERVER_DIR", str(tmp_path))
    lcp = pm._launch_config_path(2)
    lcp.write_text(json.dumps({"serverconfig": encode_serverconfig({"server_name": "Trackday", "results_post_url": url}),
                               "seasondefinition": "SD", "extra_args": ["-x"]}))
    return lcp


def _read_launch(lcp):
    import json
    from app.services.encoder import decode_config
    launch = json.loads(lcp.read_text())
    return launch, decode_config(launch["serverconfig"])


def test_reprise_refait_l_url_de_resultats_du_serveur_relance(tmp_path, monkeypatch):
    # Fichier de lancement écrit avant le correctif multi-serveur : le serveur 2 y poste au nom du 1.
    lcp = _launch_file(tmp_path, monkeypatch, "http://panel:4300/api/results/ingest?server_id=1")
    c = _Container("exited", _iso(BOOT + 11))
    _setup(monkeypatch, c)
    assert pm._resume_after_host_reboot(2) and c.started
    launch, cfg = _read_launch(lcp)
    assert "server_id=2" in cfg["results_post_url"] and "server_id=1" not in cfg["results_post_url"]
    assert cfg["server_name"] == "Trackday"                                   # le reste de la config est intact
    assert launch["seasondefinition"] == "SD" and launch["extra_args"] == ["-x"]


def test_reprise_fichier_de_lancement_illisible_le_serveur_repart_quand_meme(tmp_path, monkeypatch):
    monkeypatch.setenv("ACESERVER_DIR", str(tmp_path))
    pm._launch_config_path(2).write_text("pas du json")
    c = _Container("exited", _iso(BOOT + 11))
    _setup(monkeypatch, c)
    assert pm._resume_after_host_reboot(2) and c.started


def test_url_deja_bonne_le_fichier_n_est_pas_reecrit(tmp_path, monkeypatch):
    from app.services.server_config import _results_post_url
    with pm._db_context():                     # même contexte que la reprise : avec ou sans jeton sig
        url = _results_post_url(2)
    lcp = _launch_file(tmp_path, monkeypatch, url)
    avant = lcp.read_text()
    assert not pm._refresh_launch_results_url(2) and lcp.read_text() == avant
