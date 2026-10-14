"""Lecture / écriture des petites valeurs d'état du panel (table panel_state)."""
from datetime import datetime


def get(key: str, default: str = "") -> str:
    from app.models import PanelState
    from app.services.database import db
    row = db.session.get(PanelState, key)
    return row.value if row and row.value is not None else default


def set(key: str, value: str) -> None:           # noqa: A001 — même nom que dict.update/set, voulu
    from app.models import PanelState
    from app.services.database import db
    row = db.session.get(PanelState, key)
    if row is None:
        db.session.add(PanelState(key=key, value=value))
    else:
        row.value = value
    db.session.commit()


def get_datetime(key: str) -> datetime | None:
    raw = get(key, "")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None
