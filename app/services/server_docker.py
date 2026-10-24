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
    compose_project = (attrs["Config"].get("Labels") or {}).get("com.docker.compose.project", "")

    return {
        "compose_project":     compose_project,
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
    wine_volume = _wine_volume_name(info["wine_volume_name"], server.id)

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
        # Bibliothèque de mods partagée (même dossier que /aceserver/mods, vu par le
        # panel) posée sur le dossier Wine que ServerLauncher.exe scanne nativement.
        mods_host_path = os.path.join(info["aceserver_host_path"], "mods")
        volumes[mods_host_path] = {
            "bind": "/root/.wine/drive_c/users/root/Saved Games/ACE-Server/mods",
            "mode": "rw",
        }
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
            labels       = _compose_labels(info["compose_project"], server.id),
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


_COMPOSE_OVERRIDE_PATH = "/panel/docker-compose.override.yml"


def _reference_image() -> str:
    """Image réellement utilisée par le container ace-server de référence.

    Ne jamais deviner ce nom via une constante : Docker Compose le construit
    à partir du nom du projet (répertoire de clone par défaut, ex.
    "ev04-aceserver" si le repo vit dans ~/docker/EV04), qui varie d'une
    installation à l'autre. `_ACESERVER_IMAGE` ("pannel-ac-evo-server-aceserver")
    ne correspond que par coïncidence au nom de ce dépôt de dev — pour tout
    autre nom de dossier, `docker compose up` tente alors de PULL une image
    qui n'existe que localement, et échoue (pull access denied)."""
    try:
        return _inspect_reference_container()["image"] or _ACESERVER_IMAGE
    except Exception as e:
        log.warning("_reference_image: inspection du container de référence impossible, "
                    "repli sur %s : %s", _ACESERVER_IMAGE, e)
        return _ACESERVER_IMAGE


def _compose_labels(project: str, server_id: int) -> dict:
    """Étiquettes compose du container d'un serveur additionnel. Sans elles, il héritait de celles de
    l'image construite par compose (service « aceserver ») : compose le prenait pour une 2e copie du
    serveur principal et refusait de créer le service server_N de l'override sous le même nom."""
    if not project:
        return {}
    return {"com.docker.compose.project": project, "com.docker.compose.service": f"server_{server_id}",
            "com.docker.compose.oneoff": "False"}


def _wine_volume_name(reference_volume: str, server_id: int) -> str:
    """Nom réel du volume Wine d'un serveur additionnel : celui du serveur principal suffixé de son id
    (ex. « pannel-ac-evo-server_wine_prefix_2 »), comme à sa création par create_server_container."""
    return f"{reference_volume}_{server_id}" if reference_volume else f"wine_prefix_{server_id}"


def _compose_override_yaml(servers: list, image: str, reference_volume: str = "") -> str:
    lines = ["# Auto-generated by ACE EVO Panel — do not edit manually"]
    if not servers:
        lines += ["services: {}", "volumes: {}"]
        return "\n".join(lines) + "\n"

    lines.append("services:")
    for srv in servers:
        wine_vol = f"wine_prefix_{srv.id}"
        svc      = f"server_{srv.id}"
        lines += [
            f"  {svc}:",
            f"    image: {image}",
            f"    container_name: {srv.container_name}",
            f"    ports:",
            f'      - "{srv.http_port}:8081"',
            f'      - "{srv.tcp_port}:9700/tcp"',
            f'      - "{srv.udp_port}:9700/udp"',
            f"    volumes:",
            f"      - ./aceserver:/aceserver",
            f"      - {wine_vol}:/root/.wine",
            f"      - ./aceserver/mods:/root/.wine/drive_c/users/root/Saved Games/ACE-Server/mods",
            f"    env_file:",
            f"      - .env",
            f"    environment:",
            f'      SERVER_ID: "{srv.id}"',
            f"    security_opt:",
            f"      - seccomp:unconfined",
            f'    restart: "no"',
        ]

    # Le volume existe déjà sous son nom réel (créé avec le container) : sans « name », compose
    # cherchait « wine_prefix_N » et refusait tout le projet (« external volume … not found »)
    lines.append("volumes:")
    for srv in servers:
        lines += [f"  wine_prefix_{srv.id}:", f"    external: true",
                  f"    name: {_wine_volume_name(reference_volume, srv.id)}"]

    return "\n".join(lines) + "\n"


def sync_compose_override():
    """
    Régénère docker-compose.override.yml pour que `docker compose up --build`
    gère aussi les serveurs additionnels (id > 1).
    Appelé au démarrage du panel et après chaque création/suppression de serveur.
    """
    if os.environ.get("DEPLOY_MODE", "native") != "docker_split":
        return

    if not os.path.exists(_COMPOSE_OVERRIDE_PATH):
        log.debug("sync_compose_override: fichier absent, ignoré (%s)", _COMPOSE_OVERRIDE_PATH)
        return

    if os.path.isdir(_COMPOSE_OVERRIDE_PATH):
        log.error(
            "sync_compose_override: %s est un DOSSIER au lieu d'un fichier — "
            "corrigez avec: docker compose down && sudo rm -rf %s && touch %s "
            "&& docker compose up -d --build (voir CHANGELOG v1.9.0)",
            _COMPOSE_OVERRIDE_PATH, _COMPOSE_OVERRIDE_PATH, _COMPOSE_OVERRIDE_PATH,
        )
        return

    try:
        from app.models import Server
        servers = Server.query.filter(Server.id > 1, Server.is_enabled == True).all()  # noqa: E712
    except Exception as e:
        log.warning("sync_compose_override: lecture DB impossible : %s", e)
        return

    reference_volume = ""
    if servers:
        try:
            reference_volume = _inspect_reference_container()["wine_volume_name"] or ""
        except Exception as e:
            log.warning("sync_compose_override: volume Wine de référence illisible : %s", e)

    try:
        with open(_COMPOSE_OVERRIDE_PATH, "w", encoding="utf-8") as f:
            f.write(_compose_override_yaml(servers, _reference_image(), reference_volume))
        log.info("sync_compose_override: %d serveur(s) additionnel(s) synchronisé(s)", len(servers))
    except OSError as e:
        log.error("sync_compose_override: écriture impossible : %s", e)


def container_exists(container_name: str) -> bool:
    try:
        _get_docker_client().containers.get(container_name)
        return True
    except Exception:
        return False


def resolve_new_server(name: str, tcp_port_raw: str, http_port_raw: str) -> dict:
    """Valide les entrées du formulaire de création de serveur et résout un slug/
    container_name uniques. Ne touche pas la DB — retourne les valeurs prêtes à
    utiliser pour construire l'objet Server, ou une erreur structurée.

    Retourne soit {"ok": True, "name", "slug", "tcp_port", "udp_port", "http_port",
    "container_name"}, soit {"ok": False, "error": <code>, "port": int|None}
    avec error dans {"name_required", "invalid_port", "port_conflict", "container_exists"}.
    """
    import re
    from app.models import Server

    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "name_required", "port": None}

    try:
        tcp_port  = int(tcp_port_raw  or 9701)
        http_port = int(http_port_raw or 8082)
    except (ValueError, TypeError):
        return {"ok": False, "error": "invalid_port", "port": None}
    udp_port = tcp_port  # TCP et UDP utilisent toujours le même numéro
    for port in (tcp_port, http_port):
        if not (1024 <= port <= 65535):
            return {"ok": False, "error": "invalid_port", "port": port}

    # Vérifie les conflits de port avec les serveurs existants
    used_ports = {p for s in Server.query.all() for p in (s.tcp_port, s.udp_port, s.http_port)}
    for port in (tcp_port, http_port):
        if port in used_ports:
            return {"ok": False, "error": "port_conflict", "port": port}

    # Slug unique : base + suffixe numérique si collision
    base_slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", name.lower())).strip("-") or "server"
    slug, counter = base_slug, 1
    while Server.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    # container_name : toujours auto-généré depuis le slug, jamais fourni par l'utilisateur
    container_name = f"ace-server-{slug}"
    cnt_base, cnt_i = container_name, 1
    while Server.query.filter_by(container_name=container_name).first():
        container_name = f"{cnt_base}-{cnt_i}"
        cnt_i += 1

    if container_exists(container_name):
        return {"ok": False, "error": "container_exists", "port": None, "container_name": container_name}

    return {
        "ok": True, "name": name, "slug": slug,
        "tcp_port": tcp_port, "udp_port": udp_port, "http_port": http_port,
        "container_name": container_name,
    }
