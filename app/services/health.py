"""Santé du panel et des serveurs de jeu : ressources, disponibilité, disque, sauvegardes.

Une mesure par minute et par serveur (CPU, mémoire, joueurs, en marche ou non) est gardée 7 jours dans
la table health_sample ; la page « Santé » en tire courbes et indicateurs."""
import logging
import os
import shutil
import threading
import time
from datetime import timedelta
from pathlib import Path

log = logging.getLogger(__name__)

RETAIN_DAYS = 7
SAMPLE_EVERY_S = 60


# ── Mesures ──────────────────────────────────────────────────────────────────

def _docker_resources(server_id: int):
    from app.services.process_manager import _get_docker_client
    from app.services.live_state import container_name
    c = _get_docker_client().containers.get(container_name(server_id))
    if c.status != "running":
        return None
    s = c.stats(stream=False)
    cp, pc = s.get("cpu_stats", {}), s.get("precpu_stats", {})
    d = cp.get("cpu_usage", {}).get("total_usage", 0) - pc.get("cpu_usage", {}).get("total_usage", 0)
    sd = cp.get("system_cpu_usage", 0) - pc.get("system_cpu_usage", 0)
    cpu = (d / sd) * (cp.get("online_cpus") or 1) * 100 if sd > 0 and d >= 0 else 0.0
    mem = s.get("memory_stats", {})
    used = mem.get("usage", 0) - mem.get("stats", {}).get("inactive_file", 0)
    return {"cpu": round(cpu, 1), "mem_mb": round(max(used, 0) / 1048576, 1),
            "restarts": c.attrs.get("RestartCount", 0), "started": c.attrs.get("State", {}).get("StartedAt", "")}


def _native_resources(server_id: int):
    import psutil
    from app.services.process_manager import _proc_matches
    procs = [p for p in psutil.process_iter(["name", "cmdline"]) if _proc_matches(p)]
    if not procs:
        return None
    cpu = sum(p.cpu_percent(interval=None) for p in procs)
    mem = sum(p.memory_info().rss for p in procs) / 1048576
    return {"cpu": round(cpu, 1), "mem_mb": round(mem, 1), "restarts": 0, "started": ""}


def server_resources(server_id: int):
    from app.services.process_manager import _DEPLOY_MODE
    try:
        return _docker_resources(server_id) if _DEPLOY_MODE == "docker_split" else _native_resources(server_id)
    except Exception as e:
        log.debug("health: ressources indisponibles (server=%s) : %s", server_id, e)
        return None


def sample_once() -> int:
    """Enregistre une mesure par serveur activé ; retourne le nombre de mesures."""
    from app.models import HealthSample, Server
    from app.services.database import db
    from app.services.process_manager import get_status
    n = 0
    for srv in Server.query.filter_by(is_enabled=True).all():
        try:
            st = get_status(srv.id)
            res = server_resources(srv.id) if st.get("running") else None
            db.session.add(HealthSample(server_id=srv.id, running=bool(st.get("running")),
                                        players=int(st.get("players") or 0),
                                        cpu=(res or {}).get("cpu", 0.0), mem_mb=(res or {}).get("mem_mb", 0.0)))
            n += 1
        except Exception as e:
            log.debug("health: mesure ignorée (server=%s) : %s", srv.id, e)
    db.session.commit()
    return n


def purge_old() -> int:
    from app.models import HealthSample, _utcnow
    from app.services.database import db
    k = HealthSample.query.filter(HealthSample.ts < _utcnow() - timedelta(days=RETAIN_DAYS)).delete(synchronize_session=False)
    db.session.commit()
    return k


# ── Instantané pour la page ──────────────────────────────────────────────────

def _disk(path) -> dict | None:
    try:
        u = shutil.disk_usage(path)
        return {"path": str(path), "total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1),
                "used_pct": round((u.total - u.free) / u.total * 100, 1)}
    except OSError:
        return None


def _dir_size_mb(path: Path, limit_files: int = 20000) -> float:
    total, n = 0, 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
                n += 1
                if n >= limit_files:
                    break
    except OSError:
        pass
    return round(total / 1048576, 1)


def history(server_id: int, hours: int = 24, buckets: int = 96) -> list[dict]:
    """Courbe des ``hours`` dernières heures, réduite à ``buckets`` points (moyennes)."""
    from app.models import HealthSample, _utcnow
    since = _utcnow() - timedelta(hours=hours)
    rows = (HealthSample.query.filter(HealthSample.server_id == server_id, HealthSample.ts >= since)
            .order_by(HealthSample.ts).all())
    if not rows:
        return []
    span = max(1.0, (_utcnow() - since).total_seconds() / buckets)
    out: dict[int, list] = {}
    for r in rows:
        out.setdefault(int((r.ts - since).total_seconds() // span), []).append(r)
    pts = []
    for b in sorted(out):
        g = out[b]
        pts.append({"t": (since + timedelta(seconds=b * span)).isoformat(timespec="minutes"),
                    "cpu": round(sum(x.cpu for x in g) / len(g), 1), "mem": round(sum(x.mem_mb for x in g) / len(g), 1),
                    "players": max(x.players for x in g), "up": sum(1 for x in g if x.running) / len(g)})
    return pts


def snapshot(app_config) -> dict:
    import psutil
    import app as app_pkg
    from app.models import Server, SessionResult
    from app.services import backup
    from app.services.database import db
    from app.services.process_manager import get_status

    proc = psutil.Process(os.getpid())
    panel = {"mem_mb": round(proc.memory_info().rss / 1048576, 1), "threads": proc.num_threads(),
             "uptime_s": int(time.time() - proc.create_time()), "version": getattr(app_pkg, "_APP_VERSION", "?")}
    servers = []
    for srv in Server.query.filter_by(is_enabled=True).order_by(Server.sort_order, Server.id).all():
        st = get_status(srv.id)
        res = server_resources(srv.id) if st.get("running") else None
        since24 = history(srv.id, 24)
        up_ratio = (sum(p["up"] for p in since24) / len(since24)) if since24 else None
        servers.append({"id": srv.id, "name": srv.name, "running": bool(st.get("running")),
                        "players": st.get("players"), "config": st.get("config"),
                        "uptime_s": int(time.time() - st["started_at"]) if st.get("started_at") else None,
                        "res": res, "availability_24h": None if up_ratio is None else round(up_ratio * 100, 1),
                        "history": since24})
    last = SessionResult.query.order_by(SessionResult.received_at.desc()).first()
    db_file = Path(db.engine.url.database or "")
    return {
        "panel": panel, "servers": servers,
        "disks": [d for d in (_disk(db_file.parent if db_file.parent.exists() else "/"),
                              _disk(app_config.get("ACESERVER_DIR", "/"))) if d],
        "db_mb": round(db_file.stat().st_size / 1048576, 1) if db_file.exists() else None,
        "results_count": SessionResult.query.count(),
        "last_result_at": last.received_at if last else None,
        "last_backup_at": backup.last_backup_time(),
        "backups_mb": round(sum(b["size"] for b in backup.list_backups()) / 1048576, 1),
        "media_mb": _dir_size_mb(Path(app_pkg.__file__).parent.parent / "media"),
    }
