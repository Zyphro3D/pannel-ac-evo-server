"""Nom in-game : lettres, chiffres, _ - . et espaces simples ; jamais de retour à la ligne ni de tabulation."""
from app.routes.public import _INGAME_RE


def test_ingame_name_accepts_usual_names():
    for name in ("Lou K.", "JC Pilote", "el_ok-2", "ab"):
        assert _INGAME_RE.match(name), name


def test_ingame_name_refuses_control_characters():
    for name in ("Lou\nK", "Lou\tK", "Lou K\n", "Lou\r\nK", "a", "x" * 31):
        assert not _INGAME_RE.match(name), repr(name)
