"""Tampon incrémental des logs Docker (live_state) : mêmes lignes qu'une relecture complète."""
import time
from datetime import datetime, timezone

from app.services import live_state


class FakeContainer:
    id = "c1"

    def __init__(self):
        self.lines = []           # (epoch, texte)
        self.calls = []

    def add(self, epoch, text):
        self.lines.append((epoch, text))

    def logs(self, stream=False, since=0, timestamps=False, tail=None):
        self.calls.append(since)
        out = []
        for e, t in self.lines:
            if e >= since:
                ts = datetime.fromtimestamp(e, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z"
                out.append(f"{ts} {t}")
        if tail is not None:
            out = out[-tail:]
        return ("\n".join(out)).encode()


def _setup(monkeypatch, fake):
    live_state._log_buffers.clear()
    monkeypatch.setattr(live_state, "_DEPLOY_MODE", "docker_split")
    import app.services.process_manager as pm

    class Client:
        class containers:
            @staticmethod
            def get(name):
                return fake
    monkeypatch.setattr(pm, "_get_docker_client", lambda: Client)


def test_second_read_only_asks_for_new_lines_and_loses_nothing(monkeypatch):
    now = time.time()
    fake = FakeContainer()
    for i in range(5):
        fake.add(now - 100 + i, f"[ligne {i}]")
    _setup(monkeypatch, fake)
    first = "\n".join(live_state.iter_log_lines(since_hours=1)).splitlines()
    assert first == [f"[ligne {i}]" for i in range(5)]

    fake.add(now - 50, "[nouvelle 1]")
    fake.add(now - 49.5, "[nouvelle 2]")
    second = "\n".join(live_state.iter_log_lines(since_hours=1)).splitlines()
    assert second == first + ["[nouvelle 1]", "[nouvelle 2]"]          # sans doublon
    assert fake.calls[1] > fake.calls[0]                                # lecture incrémentale


def test_lines_leaving_the_window_are_dropped(monkeypatch):
    now = time.time()
    fake = FakeContainer()
    fake.add(now - 7200, "[trop vieille]")
    fake.add(now - 60, "[récente]")
    _setup(monkeypatch, fake)
    out = "\n".join(live_state.iter_log_lines(since_hours=1)).splitlines()
    assert out == ["[récente]"]


def test_saturated_tail_falls_back_to_full_read(monkeypatch):
    now = time.time()
    fake = FakeContainer()
    for i in range(30):
        fake.add(now - 100 + i, f"[ligne {i}]")
    _setup(monkeypatch, fake)
    monkeypatch.setattr(live_state, "_TAIL_FIRST", 10)
    out = "\n".join(live_state.iter_log_lines(since_hours=1)).splitlines()
    assert out == [f"[ligne {i}]" for i in range(30)]      # rien perdu malgré le tail trop court
