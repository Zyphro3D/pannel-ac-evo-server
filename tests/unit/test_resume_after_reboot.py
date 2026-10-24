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
