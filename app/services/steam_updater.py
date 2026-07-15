"""
Mise à jour du serveur de jeu via SteamCMD (arrêt container → SteamCMD → redémarrage →
resynchronisation véhicules/circuits), et vérification de version sans rien installer.
Génère des messages SSE consommés par les routes container_mgmt.container_update() /
container_check_update().
"""
import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

from app.services.process_manager import _atomic_write

_WARMUP_TIMEOUT = 180   # 3 min — le tout premier lancement de SteamCMD se met à jour lui-même
_RUN_TIMEOUT     = 900  # 15 min — généreux pour un téléchargement complet du jeu
_CHECK_TIMEOUT   = 180  # 3 min — une simple requête d'info n'a rien à télécharger

_LAST_CHECK_PATH = Path(__file__).parent.parent.parent / "data" / "steamcmd_last_check.json"


def _steamcmd_env(steam_home: str) -> dict:
    return {**os.environ, "HOME": steam_home}


def load_last_check() -> dict:
    """Retourne `{"latest_build": str, "checked_at": float}` du dernier build public connu
    (via `check_update` ou une mise à jour réussie), ou `{}` si jamais vérifié."""
    if _LAST_CHECK_PATH.exists():
        try:
            return json.loads(_LAST_CHECK_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_last_check(latest_build: str) -> None:
    _LAST_CHECK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(_LAST_CHECK_PATH, json.dumps({"latest_build": latest_build, "checked_at": time.time()}))


def _read_installed_buildid(aceserver_dir: str, appid: str) -> str | None:
    path = os.path.join(aceserver_dir, "steamapps", f"appmanifest_{appid}.acf")
    try:
        with open(path) as f:
            m = re.search(r'"buildid"\s+"(\d+)"', f.read())
            return m.group(1) if m else None
    except Exception:
        return None


def _kill_tree(proc: subprocess.Popen) -> None:
    """Tue le groupe de processus entier, pas seulement `proc` lui-même.

    steamcmd.sh est un script bash qui re-exec/forke (auto-mise à jour, relance
    interne) — proc.kill() ne cible que ce PID précis et laisse les processus
    petits-enfants orphelins tourner, toujours attachés au pipe stdout : la
    lecture bloquante ne reçoit alors jamais l'EOF et reste bloquée indéfiniment
    même après la "mort" du process suivi par Popen. Le process est lancé avec
    start_new_session=True pour permettre de cibler tout le groupe via killpg."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def _spawn(argv: list, steam_home: str, timeout: int, stdin_text: str | None = None):
    """Lance `argv`, génère {"type": "line", "text": ...} pour chaque ligne de sortie puis
    {"type": "result", "rc": int|None, "timed_out": bool, "output": [...]}.

    Si `stdin_text` est fourni, il est écrit sur l'entrée standard du process puis celle-ci
    est fermée (EOF) — permet de piloter le mode interactif de SteamCMD (voir `_run_script`).

    Timeout appliqué via un thread watchdog indépendant : si SteamCMD reste accroché à un
    prompt interactif (identifiants refusés, Steam Guard, etc.), la lecture de son stdout ne
    reçoit plus jamais de nouvelle ligne et bloquerait indéfiniment sans ce filet — c'est
    exactement ce qui a laissé le serveur de jeu arrêté après un échec de mise à jour."""
    os.makedirs(steam_home, exist_ok=True)

    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=_steamcmd_env(steam_home),
        start_new_session=True,
    )
    if stdin_text is not None:
        try:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    timed_out  = threading.Event()
    stop_event = threading.Event()

    def _watchdog():
        if not stop_event.wait(timeout):
            timed_out.set()
            _kill_tree(proc)

    threading.Thread(target=_watchdog, daemon=True).start()

    output = []
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                output.append(line)
                yield {"type": "line", "text": line}
        proc.wait(timeout=15)
    finally:
        stop_event.set()
        # Si on quitte cette fonction pour une autre raison que la fin normale du process
        # (client déconnecté → GeneratorExit levée ici même, exception, etc.), le watchdog
        # peut avoir déjà vu stop_event et renoncé à tuer le process : on s'en assure nous-
        # mêmes, sans quoi SteamCMD continue de tourner indéfiniment côté serveur — c'est
        # exactement ce qui a laissé un process fantôme bloquer le verrou de mise à jour.
        if proc.poll() is None:
            _kill_tree(proc)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

    yield {
        "type": "result",
        "rc": None if timed_out.is_set() else proc.returncode,
        "timed_out": timed_out.is_set(),
        "output": output,
    }


def _run_script(steamcmd: str, steam_home: str, script_lines: list, timeout: int):
    """Comme `_spawn`, mais pilote `script_lines` via le mode interactif de SteamCMD (commandes
    envoyées sur son entrée standard) plutôt que via `+runscript <fichier>`.

    `+runscript` s'est révélé peu fiable dans cet environnement : même après la passe de
    préchauffe (voir `_warmup`), une invocation avec `+runscript` échoue systématiquement avec
    "Failed to load script file" dès qu'un login est impliqué (confirmé en test contre le vrai
    binaire SteamCMD) — reproductible même sur un fichier de script valide fraîchement écrit.
    Le mode interactif (`steamcmd.sh` lancé seul, commandes tapées sur stdin) est la méthode
    d'automatisation SteamCMD la plus répandue et s'est montré fiable en test. Avantage
    supplémentaire : les identifiants ne transitent ni par un fichier sur disque ni par les
    arguments de la ligne de commande (visibles via `/proc/<pid>/cmdline`, `ps aux`, etc.)."""
    yield from _spawn([steamcmd], steam_home, timeout, stdin_text="\n".join(script_lines) + "\n")


def _warmup(steamcmd: str, steam_home: str):
    """Laisse SteamCMD s'auto-mettre à jour et redémarrer en interne AVANT de lui passer un
    vrai script. Au tout premier lancement (ou après une longue inactivité), SteamCMD se met
    à jour puis redémarre tout seul — s'il le fait pendant qu'un `+runscript` est en cours
    (même un script trivial du genre "quit"), il perd la référence au fichier de script et
    plante avec "Failed to load script file" (comportement documenté de Valve, reproduit lors
    des tests : le tout premier `+runscript` déclenche systématiquement ce problème).

    Le contournement consiste à passer `+quit` en argument de ligne de commande plutôt que
    via un fichier de script pour cette toute première invocation : rien à "perdre" lors d'un
    redémarrage interne puisqu'il n'y a pas de fichier externe référencé. Le vrai script (avec
    identifiants) part ensuite toujours "à froid" dans un second `_run_script` séparé.

    Générateur (comme `_spawn`) plutôt qu'appel bloquant silencieux : un premier lancement
    peut télécharger une vraie mise à jour de SteamCMD lui-même et prendre du temps — sans
    sortie envoyée au client pendant ce temps, un proxy intermédiaire (Cloudflare, etc.) peut
    couper la connexion pour inactivité avant même que le vrai script démarre."""
    yield from _spawn([steamcmd, "+quit"], steam_home, timeout=_WARMUP_TIMEOUT)


def _find_block(text: str, key: str) -> str | None:
    """Retourne le contenu du bloc `"key" { ... }` (accolades équilibrées, imbrication
    arbitraire) — ou None si `key` est absent."""
    m = re.search(r'"%s"\s*\{' % re.escape(key), text)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[m.end():i - 1] if depth == 0 else None


def _extract_public_buildid(text: str) -> str | None:
    """Extrait le buildid de la branche 'public' depuis la sortie de app_info_print (format
    proche VDF). La sortie contient aussi un bloc `"public"` par dépôt sous `"manifests"`
    (sans buildid) — on cible spécifiquement `"branches"."public"."buildid"` pour ne pas
    confondre les deux."""
    branches = _find_block(text, "branches")
    if branches is None:
        return None
    public = _find_block(branches, "public")
    if public is None:
        return None
    bid = re.search(r'"buildid"\s+"(\d+)"', public)
    return bid.group(1) if bid else None


def check_update(steamcmd: str, steam_user: str, steam_pass: str, steam_guard: str, appid: str):
    """Interroge Steam pour le dernier build public disponible — aucun téléchargement,
    aucun arrêt du serveur de jeu."""
    def _msg(text, done=False, error=False, **extra):
        payload = {"msg": text, "done": done, "error": error, **extra}
        return f"data: {json.dumps(payload)}\n\n"

    if not os.path.exists(steamcmd):
        yield _msg(f"✗ SteamCMD introuvable : {steamcmd}", error=True, done=True)
        return

    steam_home = "/tmp/steamcmd_session"
    yield _msg("🔄 Vérification de SteamCMD...")
    for event in _warmup(steamcmd, steam_home):
        if event["type"] == "line":
            yield _msg(event["text"])

    yield _msg(f"🔎 Interrogation de Steam (compte : {steam_user})...")
    login_line = f"login {steam_user}"
    if steam_pass:
        login_line += f" {steam_pass}"
    if steam_guard:
        login_line += f" {steam_guard}"
    script_lines = [login_line, "app_info_update 1", f"app_info_print {appid}", "quit"]

    output = []
    try:
        for event in _run_script(steamcmd, steam_home, script_lines, timeout=_CHECK_TIMEOUT):
            if event["type"] == "line":
                output.append(event["text"])
                yield _msg(event["text"])
            elif event["timed_out"]:
                yield _msg("✗ Vérification bloquée (Steam Guard ? identifiants ?), abandon", error=True, done=True)
                return
    except Exception as e:
        yield _msg(f"✗ Erreur : {e}", error=True, done=True)
        return

    buildid = _extract_public_buildid("\n".join(output))
    if buildid:
        _save_last_check(buildid)
        yield _msg(f"✓ Dernier build public Steam : {buildid}", done=True, latest_build=buildid)
    else:
        yield _msg("⚠ Impossible de déterminer le dernier build depuis la réponse Steam", error=True, done=True)


def run_update(steamcmd: str, aceserver_dir: str, steam_user: str, steam_pass: str,
               steam_guard: str, appid: str, container_name: str):
    """Générateur de messages SSE (format `data: {...}\\n\\n`) pour la mise à jour SteamCMD."""
    import docker as _docker

    def _msg(text, done=False, error=False):
        return f"data: {json.dumps({'msg': text, 'done': done, 'error': error})}\n\n"

    # 1 — Arrêt du conteneur
    yield _msg("⏹ Arrêt du serveur de jeu...")
    try:
        client = _docker.from_env()
        c = client.containers.get(container_name)
        c.stop(timeout=20)
        yield _msg("✓ Serveur arrêté")
    except Exception as e:
        yield _msg(f"✗ Impossible d'arrêter le serveur : {e}", error=True, done=True)
        return

    # 2 — SteamCMD
    if not os.path.exists(steamcmd):
        yield _msg(f"✗ SteamCMD introuvable : {steamcmd}", error=True)
    else:
        steam_home = "/tmp/steamcmd_session"
        yield _msg("🔄 Vérification de SteamCMD...")
        for event in _warmup(steamcmd, steam_home):
            if event["type"] == "line":
                yield _msg(event["text"])

        yield _msg(f"⬇ Lancement de SteamCMD (compte : {steam_user})...")
        login_line = f"login {steam_user}"
        if steam_pass:
            login_line += f" {steam_pass}"
        if steam_guard:
            login_line += f" {steam_guard}"
        script_lines = [
            f"force_install_dir {aceserver_dir}",
            login_line,
            f"app_update {appid}",
            "quit",
        ]
        try:
            for event in _run_script(steamcmd, steam_home, script_lines, timeout=_RUN_TIMEOUT):
                if event["type"] == "line":
                    yield _msg(event["text"])
                elif event["timed_out"]:
                    yield _msg("✗ SteamCMD bloqué (Steam Guard ? identifiants ?) — arrêté après 15 min", error=True)
                elif event["rc"] == 0:
                    yield _msg("✓ SteamCMD terminé avec succès")
                    installed = _read_installed_buildid(aceserver_dir, appid)
                    if installed:
                        _save_last_check(installed)
                else:
                    yield _msg(f"⚠ SteamCMD code de sortie : {event['rc']}")
        except Exception as e:
            yield _msg(f"✗ Erreur SteamCMD : {e}", error=True)

    # 3 — Redémarrage (toujours tenté, même si SteamCMD a échoué ou expiré — on ne laisse
    # jamais le serveur de jeu arrêté suite à un problème SteamCMD)
    yield _msg("🚀 Redémarrage du serveur...")
    try:
        c.start()
    except Exception as e:
        yield _msg(f"✗ Erreur redémarrage : {e}", error=True, done=True)
        return

    # 4 — Attente de la régénération des données (cars.json, events). Le serveur de jeu
    # met normalement plusieurs dizaines de secondes à réécrire ces fichiers après un
    # redémarrage — sans message de progression pendant cette attente (jusqu'à 90s), cette
    # étape donne l'impression d'être bloquée alors qu'elle travaille simplement en silence.
    yield _msg("⏳ Synchronisation véhicules et circuits...")
    cars_path = os.path.join(aceserver_dir, "cars.json")
    ev_p_path = os.path.join(aceserver_dir, "events_practice.json")
    ev_r_path = os.path.join(aceserver_dir, "events_race_weekend.json")
    old_cars_mt = os.path.getmtime(cars_path) if os.path.exists(cars_path) else 0
    deadline = time.time() + 90
    started = time.time()
    last_progress = started
    while time.time() < deadline:
        time.sleep(3)
        if os.path.exists(cars_path) and os.path.getmtime(cars_path) > old_cars_mt:
            break
        if time.time() - last_progress >= 15:
            last_progress = time.time()
            yield _msg(f"⏳ Toujours en attente... ({int(time.time() - started)}s écoulées)")
    try:
        with open(cars_path, encoding="utf-8") as f:
            cars_count = len(json.load(f).get("cars", []))
        ev_p_count = 0
        ev_r_count = 0
        if os.path.exists(ev_p_path):
            with open(ev_p_path, encoding="utf-8") as f:
                ev_p_count = len(json.load(f).get("events", []))
        if os.path.exists(ev_r_path):
            with open(ev_r_path, encoding="utf-8") as f:
                ev_r_count = len(json.load(f).get("events", []))
        yield _msg(
            f"✓ Données synchronisées — {cars_count} véhicules, "
            f"{ev_p_count + ev_r_count} circuits",
            done=True,
        )
    except Exception:
        yield _msg("✓ Serveur redémarré", done=True)
