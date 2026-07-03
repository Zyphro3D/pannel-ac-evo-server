"""
Mise à jour du serveur de jeu via SteamCMD (arrêt container → SteamCMD → redémarrage →
resynchronisation véhicules/circuits). Génère des messages SSE consommés par la route
container_mgmt.container_update().
"""
import json
import os
import subprocess
import tempfile
import time


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
        yield _msg(f"⬇ Lancement de SteamCMD (compte : {steam_user})...")
        # Script temporaire pour éviter que le mot de passe apparaisse dans ps aux
        steam_home = "/tmp/steamcmd_session"
        os.makedirs(steam_home, exist_ok=True)
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False,
            dir=steam_home, prefix="steamcmd_script_"
        ) as tf:
            tf.write("\n".join(script_lines) + "\n")
            script_path = tf.name
        os.chmod(script_path, 0o600)
        cmd = [steamcmd, "+runscript", script_path]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                env={**os.environ, "HOME": steam_home},
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    yield _msg(line)
            proc.wait()
            rc = proc.returncode
            if rc == 0:
                yield _msg("✓ SteamCMD terminé avec succès")
            else:
                yield _msg(f"⚠ SteamCMD code de sortie : {rc}")
        except Exception as e:
            yield _msg(f"✗ Erreur SteamCMD : {e}", error=True)
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

    # 3 — Redémarrage
    yield _msg("🚀 Redémarrage du serveur...")
    try:
        c.start()
    except Exception as e:
        yield _msg(f"✗ Erreur redémarrage : {e}", error=True, done=True)
        return

    # 4 — Attente de la régénération des données (cars.json, events)
    yield _msg("⏳ Synchronisation véhicules et circuits...")
    cars_path = os.path.join(aceserver_dir, "cars.json")
    ev_p_path = os.path.join(aceserver_dir, "events_practice.json")
    ev_r_path = os.path.join(aceserver_dir, "events_race_weekend.json")
    old_cars_mt = os.path.getmtime(cars_path) if os.path.exists(cars_path) else 0
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(3)
        if os.path.exists(cars_path) and os.path.getmtime(cars_path) > old_cars_mt:
            break
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
