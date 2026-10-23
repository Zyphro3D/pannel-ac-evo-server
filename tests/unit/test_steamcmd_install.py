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
