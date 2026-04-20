# AC EVO Server Panel

Interface web pour gérer un serveur dédié **Assetto Corsa EVO** (v0.6.0+) sous Windows.

## Fonctionnalités

- Démarrer / arrêter / redémarrer le serveur depuis le navigateur
- Modes **Practice**, **Qualifying**, **Race Weekend** avec toutes les sessions
- Sélection du circuit, des véhicules (avec ballast / restrictor), météo, grip
- Gestion de plusieurs fichiers de configuration (créer, dupliquer, supprimer)
- Deux niveaux d'accès : `superadmin` (ports TCP/UDP visibles) et `admin`
- **Auto-restart** automatique en cas de crash serveur (watchdog)
- Affichage du **nombre de joueurs** en temps réel (API HTTP du serveur)
- **Logs serveur** accessibles depuis l'interface
- Notifications **Discord** : démarrage (mode, circuit, voitures, durées), arrêt, crash
- Interface bilingue FR / EN

## Prérequis

- Python 3.11+
- Windows (le serveur ACE EVO est Windows uniquement)
- `AssettoCorsaEVOServer.exe` installé
- Fichiers `cars.json`, `events_practice.json`, `events_race_weekend.json` générés par le ServerLauncher

## Installation

```bash
git clone https://github.com/<votre-user>/pannel-ac-evo-server.git
cd pannel-ac-evo-server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

```bash
copy .env.example .env
```

Éditez `.env` avec vos chemins et mots de passe.

### Compiler les traductions

```bash
python compile_mo.py
```

### Lancer

```bash
python run.py
```

L'interface est accessible sur `http://localhost:4300` (ou le port configuré dans `run.py`).

## Structure

```
app/
  routes/       # Blueprints Flask (auth, admin, api)
  services/     # Logique métier (process_manager, config_builder, discord_notifier…)
  static/       # CSS + JS
  templates/    # Jinja2 (base.html, dashboard.html, login.html)
translations/   # Fichiers i18n FR / EN (.po / .mo)
config.py       # Configuration Flask (lit .env)
run.py          # Point d'entrée (Waitress WSGI)
```

## Variables d'environnement

Voir `.env.example` pour la liste complète et les commentaires.

| Variable | Description |
|---|---|
| `SECRET_KEY` | Clé secrète Flask (à changer en prod) |
| `SUPERADMIN_PASSWORD` | Mot de passe compte superadmin |
| `ADMIN_PASSWORD` | Mot de passe compte admin |
| `ACESERVER_EXE_PATH` | Chemin vers `AssettoCorsaEVOServer.exe` |
| `CONFIGS_DIR` | Dossier contenant les fichiers `.json` de config |
| `ACESERVER_HTTP_PORT` | Port HTTP de l'API du serveur (défaut : 8080) |
| `SERVER_SHOW_CONSOLE` | Afficher la fenêtre console du serveur (`true`/`false`) |
| `DISCORD_WEBHOOK_URL` | URL webhook Discord (laisser vide pour désactiver) |

## Notes techniques

- Le format `-serverconfig` / `-seasondefinition` est du JSON compressé zlib + encodé base64 (4 octets longueur + payload zlib)
- Pour le mode Race Weekend, le fichier `content/data/race_weekend.seasondefinition` doit être un JSON UTF-8 valide — le panel le crée automatiquement si absent ou binaire (format kspkg)
- Le watchdog tourne en thread daemon et relance le serveur si le PID disparaît alors que `auto_restart` est actif dans le state file
