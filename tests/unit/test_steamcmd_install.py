import io
import tarfile

import pytest

from app.services import steam_updater


def _tar(members: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, payload: bytes):
    monkeypatch.setattr(steam_updater.urllib.request, "urlopen", lambda url, timeout: _Resp(payload))


def test_install_steamcmd_extrait_l_archive(tmp_path, monkeypatch):
    _serve(monkeypatch, _tar({"steamcmd.sh": b"#!/bin/sh\n", "linux32/steamcmd": b"bin"}))
    target = tmp_path / "steamcmd" / "steamcmd.sh"
    steam_updater.install_steamcmd(str(target))
    assert target.exists() and (tmp_path / "steamcmd" / "linux32" / "steamcmd").exists()


def test_install_steamcmd_refuse_un_chemin_hors_du_dossier(tmp_path, monkeypatch):
    _serve(monkeypatch, _tar({"../evil.sh": b"x", "steamcmd.sh": b"#!/bin/sh\n"}))
    with pytest.raises(tarfile.TarError):
        steam_updater.install_steamcmd(str(tmp_path / "steamcmd" / "steamcmd.sh"))
    assert not (tmp_path / "evil.sh").exists()


def test_install_steamcmd_refuse_une_archive_sans_steamcmd(tmp_path, monkeypatch):
    _serve(monkeypatch, _tar({"autre.txt": b"x"}))
    with pytest.raises(FileNotFoundError):
        steam_updater.install_steamcmd(str(tmp_path / "steamcmd" / "steamcmd.sh"))


def test_install_steamcmd_refuse_une_reponse_trop_grosse(tmp_path, monkeypatch):
    monkeypatch.setattr(steam_updater, "_STEAMCMD_MAX_BYTES", 10)
    _serve(monkeypatch, b"x" * 50)
    with pytest.raises(ValueError):
        steam_updater.install_steamcmd(str(tmp_path / "steamcmd" / "steamcmd.sh"))


def test_check_update_installe_steamcmd_s_il_manque(tmp_path, monkeypatch):
    target = tmp_path / "steamcmd" / "steamcmd.sh"
    calls = []
    monkeypatch.setattr(steam_updater, "install_steamcmd", lambda p: calls.append(p))
    msgs = list(steam_updater.check_update(str(target), "user", "", "", "4564210"))
    assert calls == [str(target)]
    assert any("installation automatique" in m for m in msgs)
    assert "introuvable" in msgs[-1]      # le faux installateur n'a rien posé : erreur propre, pas de plantage


def test_echec_app_update_detecte_malgre_le_code_0():
    out = "Connecting anonymously to Steam Public...OK\nERROR! Failed to install app '4564210' (No subscription)\n"
    assert "compte anonyme" in steam_updater._install_failure(out, "anonymous")
    assert "« florian »" in steam_updater._install_failure(out, "florian")
    assert steam_updater._install_failure("Success! App '4564210' fully installed.", "florian") is None


def _fake_run(monkeypatch, tmp_path, lines, rc=0):
    exe = tmp_path / "steamcmd" / "steamcmd.sh"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    monkeypatch.setattr(steam_updater, "_warmup", lambda *a, **k: iter(()))

    def run(*a, **k):
        for text in lines:
            yield {"type": "line", "text": text}
        yield {"type": "exit", "timed_out": False, "rc": rc}
    monkeypatch.setattr(steam_updater, "_run_script", run)
    return str(exe)


def _events(gen):
    import json as _json
    return [_json.loads(m[len("data: "):]) for m in gen]


def test_premiere_installation_se_termine_sans_attente_ni_faux_redemarrage(tmp_path, monkeypatch):
    exe = _fake_run(monkeypatch, tmp_path, ["Success! App '4564210' fully installed."])
    evs = _events(steam_updater.run_update(exe, str(tmp_path), "florian", "pw", "", "4564210", []))
    assert evs[-1]["done"] and not evs[-1]["error"] and "installé" in evs[-1]["msg"]
    assert not any("Synchronisation" in e["msg"] for e in evs)


def test_echec_steamcmd_termine_en_erreur(tmp_path, monkeypatch):
    exe = _fake_run(monkeypatch, tmp_path, ["ERROR! Failed to install app '4564210' (No subscription)"])
    evs = _events(steam_updater.run_update(exe, str(tmp_path), "anonymous", "", "", "4564210", []))
    assert evs[-1]["done"] and evs[-1]["error"]
    assert any("compte anonyme" in e["msg"] for e in evs)
