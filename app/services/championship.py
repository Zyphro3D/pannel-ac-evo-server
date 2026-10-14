"""Classement de championnat : points par manche, bonus, pires manches retirées, départage.

Une manche = une course déjà importée (SessionResult). Seuls les pilotes humains identifiés par leur SteamID
comptent ; les IA sont ignorées et les places sont recalculées parmi les humains. Un pilote qui a parcouru
moins de la moitié des tours du leader est non classé dans la manche (0 point, la participation compte).

Barème par défaut : 25-18-15-12-10-8-6-4-2-1. Départage : plus de victoires, puis plus de 2es places, etc."""
import re
import unicodedata

FINISH_RATIO = 0.5
MAX_POINTS_ENTRIES = 40
MAX_POINT_VALUE = 1000


def parse_points(text: str) -> list[int]:
    """« 25,18,15 » → [25, 18, 15] ; ValueError si invalide."""
    parts = [p.strip() for p in re.split(r"[,\s;]+", text or "") if p.strip()]
    if not parts or len(parts) > MAX_POINTS_ENTRIES:
        raise ValueError("barème vide ou trop long")
    vals = [int(p) for p in parts]
    if any(v < 0 or v > MAX_POINT_VALUE for v in vals):
        raise ValueError("points hors limites")
    return vals


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:50] or "championnat"


def round_scores(parsed: dict, points: list[int], fastest_bonus: int, pole_bonus: int) -> dict:
    """Points de chaque pilote humain pour une manche : {steamid: {pos, pts, dnf, nickname, fastest, pole}}."""
    humans = []
    for d in parsed.get("standings", []):
        pid = str(d.get("player_id") or "").strip()
        laps = int(d.get("laps_count") or d.get("race_laps_count") or 0)
        if pid and laps > 0:
            humans.append((pid, d, laps))
    if not humans:
        return {}
    humans.sort(key=lambda h: int(h[1].get("position") or 10_000))
    leader = max(h[2] for h in humans)
    out: dict[str, dict] = {}
    rank = 0
    for pid, d, laps in humans:
        dnf = laps < FINISH_RATIO * leader
        if not dnf:
            rank += 1
        pts = 0 if dnf else (points[rank - 1] if rank - 1 < len(points) else 0)
        out[pid] = {"pos": None if dnf else rank, "pts": pts, "dnf": dnf, "nickname": d.get("nickname") or pid,
                    "fastest": False, "pole": False}
    if fastest_bonus:
        cands = [(int(d.get("fastest_lap_ms") or d.get("best_lap_ms") or 0), pid) for pid, d, _l in humans
                 if not out[pid]["dnf"]]
        cands = [c for c in cands if c[0] > 0]
        if cands:
            pid = min(cands)[1]
            out[pid]["pts"] += fastest_bonus
            out[pid]["fastest"] = True
    if pole_bonus:
        grid = [(int(d.get("starting_position") or 0), pid) for pid, d, _l in humans]
        grid = [g for g in grid if g[0] > 0]
        if grid:
            pid = min(grid)[1]
            out[pid]["pts"] += pole_bonus
            out[pid]["pole"] = True
    return out


def standings(rounds: list[dict], drop_worst: int = 0, min_ratio: float = 0.0) -> list[dict]:
    """``rounds`` : liste (dans l'ordre) de {label, scores: round_scores(...)}. Retourne le classement."""
    n_rounds = len(rounds)
    players: dict[str, dict] = {}
    for idx, r in enumerate(rounds):
        for pid, sc in r["scores"].items():
            p = players.setdefault(pid, {"player_id": pid, "nickname": sc["nickname"], "cells": [None] * n_rounds})
            p["nickname"] = sc["nickname"]
            p["cells"][idx] = {"pts": sc["pts"], "pos": sc["pos"], "dnf": sc["dnf"], "fastest": sc["fastest"],
                               "pole": sc["pole"], "dropped": False}
    drop = max(0, min(int(drop_worst or 0), n_rounds - 1)) if n_rounds else 0
    out = []
    for p in players.values():
        scores = [(c["pts"] if c else 0, i) for i, c in enumerate(p["cells"])]
        if drop:
            for _pts, i in sorted(scores)[:drop]:
                if p["cells"][i]:
                    p["cells"][i]["dropped"] = True
        total = sum(c["pts"] for c in p["cells"] if c and not c["dropped"])
        played = sum(1 for c in p["cells"] if c)
        positions = [c["pos"] for c in p["cells"] if c and c["pos"]]
        top = max(positions, default=0)
        countback = [sum(1 for x in positions if x == k) for k in range(1, max(top, 3) + 1)]
        out.append({**p, "total": total, "played": played, "wins": countback[0] if countback else 0,
                    "podiums": sum(countback[:3]), "countback": countback,
                    "ranked": (played >= min_ratio * n_rounds) if n_rounds else False})
    out.sort(key=lambda p: (not p["ranked"], -p["total"], [-c for c in p["countback"]], p["nickname"].lower()))
    return out
