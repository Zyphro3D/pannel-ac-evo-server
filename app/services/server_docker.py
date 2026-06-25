"""
Gestion des containers Docker pour les serveurs ACE EVO additionnels.

Utilise le Docker socket proxy Tecnativa exposé via DOCKER_HOST.
Prérequis dockerproxy : CONTAINERS=1, POST=1 (déjà configuré).
"""
import logging
import os

log = logging.getLogger(__name__)

_ACESERVER_CONTAINER_NAME = os.environ.get("ACESERVER_CONTAINER_NAME", "ace-server")
_ACESERVER_IMAGE          = "pannel-ac-evo-server-aceserver"


def _get_docker_client():
    from app.services.process_manager import _get_docker_client as _pm_docker
    return _pm_docker()


def _inspect_reference_container() -> dict:
    """
    Inspecte le container ace-server de référence pour en extraire :
    - chemin hôte du dossier aceserver (bind mount)
    - nom du volume Wine prefix (pour nommer celui du nouveau serveur)
    - nom du réseau Docker
    - variables d'environnement à propager
    - options de sécurité (seccomp)
    """
    client = _get_docker_client()
    ref    = client.containers.get(_ACESERVER_CONTAINER_NAME)
    attrs  = ref.attrs

    aceserver_host_path = ""
    wine_volume_name    = ""
    for m in attrs.get("Mounts", []):
        if m["Destination"] == "/aceserver" and m["Type"] == "bind":
            aceserver_host_path = m["Source"]
        elif m["Destination"] == "/root/.wine" and m["Type"] == "volume":
            wine_volume_name = m["Name"]

    network_name = next(iter(attrs["NetworkSettings"]["Networks"].keys()), None)
    image        = attrs["Config"]["Image"]

    env_vars: dict[str, str] = {}
    for e in attrs["Config"].get("Env", []):
        k, _, v = e.partition("=")
        env_vars[k] = v

    security_opt = attrs.get("HostConfig", {}).get("SecurityOpt") or []

    return {
        "aceserver_host_path": aceserver_host_path,
        "wine_volume_name":    wine_volume_name,
        "network_name":        network_name,
        "image":               image,
        "env_vars":            env_vars,
        "security_opt":        security_opt,
    }


def create_server_container(server) -> dict:
    """
    Crée un nouveau container Docker pour un serveur ACE EVO additionnel.
    `server` est une instance du modèle `Server`.
    Le container est créé mais PAS démarré (le watchdog s'en charge).
    """
    try:
        info = _inspect_reference_container()
    except Exception as e:
        log.error("create_server_container: impossible d'inspecter le container de référence : %s", e)
        return {"ok": False, "error": f"reference_container_error: {e}"}

    # Volume Wine prefix dédié à ce serveur
    wine_volume = f"{info['wine_volume_name']}_{server.id}" if info["wine_volume_name"] else f"wine_prefix_{server.id}"

    # Env vars : partir de la référence et surcharger SERVER_ID
    env_vars = dict(info["env_vars"])
    env_vars["SERVER_ID"] = str(server.id)

    # Ports : le container écoute toujours sur 8081 (HTTP) et 9700 (TCP/UDP) en interne
    port_bindings = {
        "8081/tcp": server.http_port,
        "9700/tcp": server.tcp_port,
        "9700/udp": server.udp_port,
    }

    volumes = {}
    if info["aceserver_host_path"]:
        volumes[info["aceserver_host_path"]] = {"bind": "/aceserver", "mode": "rw"}
    volumes[wine_volume] = {"bind": "/root/.wine", "mode": "rw"}

    if info["network_name"] == "host":
        return {
            "ok": False,
            "error": (
                "network_mode 'host' is incompatible with multi-server port bindings. "
                "Remove 'network_mode: host' from your docker-compose.yml and recreate "
                "the base container with: docker compose up -d --build"
            ),
        }

    try:
        client    = _get_docker_client()
        container = client.containers.create(
            image        = info["image"] or _ACESERVER_IMAGE,
            name         = server.container_name,
            environment  = env_vars,
            ports        = port_bindings,
            volumes      = volumes,
            security_opt = info["security_opt"] or ["seccomp:unconfined"],
            network      = info["network_name"],
            restart_policy = {"Name": "no"},
            detach       = True,
        )
        log.info("Container '%s' créé (id=%s)", server.container_name, container.short_id)
        return {"ok": True, "container_id": container.short_id}
    except Exception as e:
        log.error("create_server_container: échec création '%s' : %s", server.container_name, e)
        return {"ok": False, "error": str(e)}


def remove_server_container(container_name: str) -> dict:
    """Arrête et supprime un container Docker."""
    try:
        client    = _get_docker_client()
        container = client.containers.get(container_name)
        try:
            container.stop(timeout=10)
        except Exception:
            pass
        container.remove(force=True)
        log.info("Container '%s' supprimé", container_name)
        return {"ok": True}
    except Exception as e:
        log.error("remove_server_container '%s' : %s", container_name, e)
        return {"ok": False, "error": str(e)}


def container_exists(container_name: str) -> bool:
    try:
        _get_docker_client().containers.get(container_name)
        return True
    except Exception:
        return False
