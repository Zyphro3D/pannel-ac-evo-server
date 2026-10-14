"""Carte des accrochages : positions des impacts sur le plan du circuit et sur la voiture.

Le serveur de jeu enregistre pour chaque impact la position dans le monde (x, z), la position sur la
voiture (repère de la voiture : x droite, y haut, z avant), la vitesse de l'impact, le type (mur, voiture,
objet) et les dégâts. Pour dessiner les impacts sur le plan SVG d'un circuit il faut passer des
coordonnées du jeu à celles du SVG : ``app/calibration/track_calibration.json`` donne, pour chaque circuit, la
transformation (matrice 2×2 + translation, miroir éventuel), calculée une fois en alignant le tracé SVG
sur la ligne idéale du circuit (erreur de forme < 0,15 unité sur 400 pour la plupart des circuits).
Un circuit sans calage (mod, nouveau circuit) n'a simplement pas de carte."""
import json
import re
import threading
import time
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_CAL_PATH = _BASE / "calibration" / "track_calibration.json"
_SVG_DIR = _BASE / "static" / "img" / "tracks"
_KIND = {"wall": 0, "car": 1, "object": 2}
_TTL_S = 60.0

_cal: dict | None = None
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, dict]] = {}


def calibration() -> dict:
    global _cal
    if _cal is None:
        try:
            raw = json.loads(_CAL_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        _cal = {k: v for k, v in raw.items() if isinstance(v, dict) and "m" in v}
    return _cal


def has_map(slug: str | None) -> bool:
    return bool(slug) and slug in calibration() and (_SVG_DIR / f"{slug}.svg").is_file()


def to_map(slug: str, x: float, z: float) -> tuple[float, float]:
    """Coordonnées du jeu (x, z) → coordonnées du plan SVG (viewBox 400×400)."""
    c = calibration()[slug]
    m, t = c["m"], c["t"]
    px = -x if c.get("mirror") else x
    return (m[0] * px + m[1] * z + t[0], m[2] * px + m[3] * z + t[1])


def svg_path(slug: str) -> str:
    """Attribut ``d`` du tracé du circuit."""
    txt = (_SVG_DIR / f"{slug}.svg").read_text(encoding="utf-8")
    m = re.search(r'<path d="([^"]+)"', txt)
    return m.group(1) if m else ""


def slug_for(parsed: dict) -> str | None:
    from app.services.track_map import get_track_svg_name
    return get_track_svg_name(parsed.get("track", ""), parsed.get("layout", ""))


def build(sessions: list[tuple[int, str, dict]], slug: str, only_session: int | None = None) -> dict:
    """Impacts du circuit ``slug``.

    ``sessions`` : liste de (identifiant, libellé, résultat décodé). Retourne
    {path, sessions: [libellés], drivers: [pseudos], rows: [[mx, my, rx, ry, rz, km/h, type, dégâts,
    session, pilote, [pilotes touchés]], …]} avec des indices dans ``sessions`` et ``drivers``."""
    out_sessions, drivers, rows = [], [], []
    drv_idx: dict[str, int] = {}

    def drv(name: str) -> int:
        if name not in drv_idx:
            drv_idx[name] = len(drivers)
            drivers.append(name)
        return drv_idx[name]

    for sid, label, parsed in sessions:
        if only_session is not None and sid != only_session:
            continue
        if slug_for(parsed) != slug or not parsed.get("hits"):
            continue
        si = len(out_sessions)
        out_sessions.append({"id": sid, "label": label})
        for h in parsed["hits"]:
            mx, my = to_map(slug, h["x"], h["z"])
            rows.append([round(mx, 1), round(my, 1), round(h["rx"], 2), round(h["ry"], 2), round(h["rz"], 2),
                         h["kmh"], _KIND.get(h["kind"], 2), 1 if h["damage"] else 0, si, drv(h["nickname"]),
                         [drv(n) for n in h.get("with", [])]])
    return {"path": svg_path(slug), "sessions": out_sessions, "drivers": drivers, "rows": rows}


def circuits_with_hits(load_rows, label_for) -> list[dict]:
    """Circuits ayant des impacts et un calage : [{slug, track, layout, count}], le plus fourni d'abord (cache 60 s)."""
    key = ("circuits",)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _TTL_S:
            return hit[1]["v"]
    from app.services.results_parser import get_parsed
    agg: dict[str, dict] = {}
    for r in load_rows():
        try:
            p = get_parsed(r)
        except Exception:
            continue
        slug = slug_for(p)
        if not has_map(slug) or not p.get("hits"):
            continue
        e = agg.setdefault(slug, {"slug": slug, "track": p.get("track", ""), "layout": p.get("layout", ""), "count": 0})
        e["count"] += len(p["hits"])
    val = sorted(agg.values(), key=lambda e: -e["count"])
    with _lock:
        _cache[key] = (now, {"v": val})
    return val


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()
