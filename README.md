# AC EVO Server Panel

Interface web pour gérer un serveur dédié **Assetto Corsa EVO** sous Windows, déployable derrière un reverse proxy (Caddy, Nginx…).

## Fonctionnalités

- Démarrer / arrêter / redémarrer le serveur depuis le navigateur
- Modes **Practice** et **Race Weekend** (Practice + Qualification + Chauffe + Course)
- Sélection du circuit, de la météo, de l'adhérence initiale
- Sélection des véhicules avec **filtres par catégorie** (Road/Race/Track, Modern/Vintage, ICE/EV/Hybrid…) et **plage PI** (slider)
- Gestion de plusieurs fichiers de configuration (créer, dupliquer, supprimer)
- **Auto-restart** watchdog : relance automatique en cas de crash serveur
- Affichage du **nombre de joueurs** en temps réel via l'API HTTP du serveur
- **Logs serveur** accessibles depuis l'interface + logs applicatifs rotatifs dans `logs/app.log`
- Notifications **Discord** : démarrage (mode, circuit, voitures, durées), arrêt, crash
- Deux niveaux d'accès : `admin` (accès standard) et `superadmin` (ports réseau visibles et modifiables)
- Interface bilingue **FR / EN**

## Prérequis

- Python **3.11+**
- **Windows** (le serveur ACE EVO est Windows uniquement)
- Fichiers `cars.json`, `events_practice.json` et `events_race_weekend.json` générés par le **ServerLauncher** officiel d'Assetto Corsa EVO

## Installation

```bash
git clone https://github.com/Zyphro3D/pannel-ac-evo-server.git
cd pannel-ac-evo-server

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
# Éditez .env avec vos chemins et mots de passe

python run.py          # démarre sur http://localhost:4300
```

## Configuration `.env`

| Variable | Description | Défaut |
|---|---|---|
| `SECRET_KEY` | Clé secrète Flask — **à changer en production** | — |
| `SUPERADMIN_USERNAME` / `SUPERADMIN_PASSWORD` | Compte superadmin (accès complet) | — |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Compte admin (accès standard) | — |
| `CONFIGS_DIR` | Dossier contenant vos fichiers de configuration `.json` | — |
| `ACESERVER_DIR` | Dossier d'installation du serveur ACE EVO | `C:\aceserver` |
| `ACESERVER_HTTP_PORT` | Port HTTP de l'API du jeu | `8080` |
| `SERVER_SHOW_CONSOLE` | Afficher la fenêtre console du serveur | `false` |
| `DISCORD_WEBHOOK_URL` | URL webhook Discord (laisser vide pour désactiver) | — |
| `SESSION_COOKIE_SECURE` | `true` si HTTPS (Caddy/Nginx), `false` en HTTP local | `true` |

> **`ACESERVER_DIR`** remplace les anciennes variables `ACESERVER_EXE_PATH`, `CARS_JSON_PATH`, etc.
> Les noms de fichiers sont fixes (`AssettoCorsaEVOServer.exe`, `cars.json`, `events_practice.json`, `events_race_weekend.json`) — seul le dossier est configurable.

Générer une `SECRET_KEY` sécurisée :
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Structure du projet

```
app/
  routes/       # Blueprints Flask : auth, admin, api
  services/     # Logique métier : process_manager, config_builder, discord_notifier, server_config
  static/       # CSS + JS
  templates/    # Jinja2 : base.html, dashboard.html, login.html
translations/   # Fichiers i18n FR / EN (.po → compiler avec compile_mo.py)
logs/           # Logs applicatifs rotatifs (ignorés par git)
config.py       # Lecture du .env
run.py          # Point d'entrée Waitress (port 4300, 8 threads)
```

## Notes techniques

- Les arguments `-serverconfig` / `-seasondefinition` sont du JSON compressé zlib encodé en base64 (4 octets longueur + payload zlib).
- En mode Race Weekend, le fichier `content/data/race_weekend.seasondefinition` doit être un JSON UTF-8 valide. Le panel le crée automatiquement si absent ou corrompu (format binaire kspkg).
- Le watchdog tourne en thread daemon : il relance le serveur si le PID disparaît alors que `auto_restart` est actif dans le state file.
- Les notifications Discord utilisent le `User-Agent: DiscordBot` pour contourner le pare-feu Cloudflare.

## Licence

[CC BY-NC 4.0](LICENSE) — usage personnel et communautaire libre, usage commercial interdit.
