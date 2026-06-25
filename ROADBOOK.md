# ROADBOOK — Panel ACE EVO Server
> Document de référence exhaustif — architecture actuelle, interactions entre fichiers, décisions prises, roadmap multi-serveur.
> Version : 1.7.1 — Branche active développement : `feat/multi-server`

---

## TABLE DES MATIÈRES

1. [Vue d'ensemble du projet](#1-vue-densemble)
2. [Architecture Docker](#2-architecture-docker)
3. [Stack technique](#3-stack-technique)
4. [Structure des fichiers](#4-structure-des-fichiers)
5. [Base de données — modèles SQLAlchemy](#5-base-de-données)
6. [Démarrage de l'application — `create_app()`](#6-démarrage-de-lapplication)
7. [Services — description et interactions](#7-services)
8. [Routes — blueprints Flask](#8-routes)
9. [Frontend — templates, CSS, JS](#9-frontend)
10. [i18n — internationalisation](#10-i18n)
11. [Sécurité](#11-sécurité)
12. [Variables d'environnement](#12-variables-denvironnement)
13. [Flux de données critiques](#13-flux-de-données-critiques)
14. [État actuel — branche `feat/multi-server`](#14-état-actuel-multi-serveur)
15. [Roadmap multi-serveur — phases détaillées](#15-roadmap-multi-serveur)
16. [Points de vigilance et décisions architecturales](#16-points-de-vigilance)
17. [Procédures opérationnelles](#17-procédures-opérationnelles)

---

## 1. VUE D'ENSEMBLE

**Panel ACE EVO Server** est un panel web Flask open source pour gérer des serveurs de jeu Assetto Corsa EVO.

### Caractéristiques du projet
- Open source GitHub, distribution gratuite communautaire
- 80% du développement pensé pour les autres utilisateurs (clubs, organisateurs de course)
- 2 beta testeurs actifs qui pullent rapidement → chaque push est quasi-immédiatement en production
- **Règle absolue** : réfléchir avant tout push — les migrations DB doivent être rétrocompatibles

### Fonctionnalités actuelles (v1.7.1)
- Démarrage / arrêt / redémarrage du serveur ACE EVO
- Éditeur de configuration JSON (voitures, circuit, météo, sessions)
- Gestion de plusieurs fichiers de configuration + config active
- Roulement automatique de configurations (rotation)
- Résultats de session (webhook + scan fichiers) avec classement enrichi
- Leaderboard public en temps réel (lecture des logs)
- Client TCP ACE EVO (port 9700) : chat in-game + leaderboard live
- Gestion d'événements planifiés avec inscription pilotes
- Notifications Discord (3 webhooks : serveur, pilotes, course)
- Emails SMTP (rappels, confirmations, réinitialisation mot de passe)
- Authentification multi-rôles (superadmin / admin / pilote)
- i18n 5 langues (fr, en, de, es, it)
- Sélecteur de serveur dans la navbar (fondation multi-serveur)
- Page Mods placeholder (fondation future)

---

## 2. ARCHITECTURE DOCKER

```
┌─────────────────────────────────────────────────────────────┐
│  Host Linux                                                   │
│                                                               │
│  ┌──────────────────┐     ┌─────────────────────────────┐   │
│  │   ace-panel      │     │  ace-docker-proxy           │   │
│  │  (Flask + Waitress)    │  (Tecnativa docker-socket-  │   │
│  │  port 4300:4300  │────▶│   proxy)                    │   │
│  │                  │     │  port 2375 (internal)       │   │
│  └────────┬─────────┘     └─────────────┬───────────────┘   │
│           │                             │                     │
│           │ volume partagé              │ proxy Docker API    │
│           │ ./aceserver:/aceserver      │ (CONTAINERS,POST)   │
│           │                             │                     │
│  ┌────────▼─────────────────────────────▼───────────────┐   │
│  │   ace-server                                          │   │
│  │  (Wine + AssettoCorsaEVOServer.exe)                   │   │
│  │  port 8080: API HTTP serveur de jeu                   │   │
│  │  port 9700/tcp: connexions joueurs                    │   │
│  │  port 9700/udp: connexions joueurs                    │   │
│  │  restart: "no" ← géré par le watchdog du panel        │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                               │
│  Volumes persistants:                                         │
│  • panel_data:/panel/data (SQLite DB)                        │
│  • wine_prefix:/root/.wine (prefix Wine)                     │
│  • ./aceserver:/aceserver (configs, résultats, state files)  │
└─────────────────────────────────────────────────────────────┘
```

### Points clés Docker
- `DEPLOY_MODE=docker_split` → mode production (panel contrôle ace-server via Docker API)
- `DEPLOY_MODE=native` → mode Windows legacy (subprocess direct)
- `DEPLOY_MODE=docker` → mode Wine monolithique legacy
- Le dockerproxy Tecnativa isole le socket Docker. Seuls CONTAINERS+POST+START+STOP+RESTARTS sont autorisés
- **CRITIQUE** : le code source est baked dans l'image via `COPY . .`. Après toute modification : `docker compose up -d --build panel`
- Le panel écrit les configs dans `./aceserver/configs/`, le serveur les lit au démarrage
- Le state file (`.panel_state.json`) est dans `/aceserver/` — partagé panel↔serveur

---

## 3. STACK TECHNIQUE

| Composant | Technologie |
|-----------|-------------|
| Backend | Python 3.11, Flask |
| Serveur WSGI | Waitress |
| ORM | SQLAlchemy (SQLite) |
| Auth | Flask-Login |
| i18n | Flask-Babel (5 langues) |
| CSRF | Flask-WTF / CSRFProtect |
| Rate limiting | Flask-Limiter |
| Frontend | Jinja2, CSS vanilla, JS vanilla |
| Docker | docker-compose, Tecnativa proxy |
| Protocole serveur | TCP protobuf custom (port 9700) |
| Notifs | Discord webhooks, SMTP |

---

## 4. STRUCTURE DES FICHIERS

```
/opt/pannel-ac-evo-server/
├── app/
│   ├── __init__.py          # create_app(), seeds, migrations, extensions
│   ├── models.py            # SQLAlchemy ORM (7 modèles)
│   ├── utils.py             # Décorateurs auth (admin_required, superadmin_required)
│   ├── routes/
│   │   ├── admin.py         # Blueprint "admin" — dashboard, serveur, settings, comptes
│   │   ├── api.py           # Blueprint "api" — REST API + webhook ingest
│   │   ├── auth.py          # Blueprint "auth" — login, logout, register
│   │   ├── container_mgmt.py # Blueprint "container_mgmt" — gestion Docker
│   │   ├── events_admin.py  # Blueprint "events_admin" — CRUD événements
│   │   ├── leaderboard.py   # Blueprint "leaderboard" — classements historiques
│   │   ├── live.py          # Blueprint "live" — monitoring temps réel
│   │   └── public.py        # Blueprint "public" — pages publiques
│   ├── services/
│   │   ├── ace_tcp_client.py    # Client TCP ACE EVO (chat + leaderboard)
│   │   ├── config_builder.py    # Construction des args de lancement (base64)
│   │   ├── database.py          # Instance SQLAlchemy (db = SQLAlchemy())
│   │   ├── discord_notifier.py  # Webhooks Discord
│   │   ├── encoder.py           # Encodage config JSON → protobuf
│   │   ├── entry_list.py        # Génération entry_list.ini
│   │   ├── event_scheduler.py   # Scheduler (emails, Discord, auto-launch)
│   │   ├── mailer.py            # SMTP
│   │   ├── process_manager.py   # Lifecycle serveur (start/stop/watchdog)
│   │   ├── results_parser.py    # Parsing JSON résultats ACE EVO
│   │   ├── rotation_manager.py  # Roulement de configs
│   │   └── server_config.py     # Lecture/écriture configs JSON
│   ├── static/
│   │   ├── css/main.css     # CSS vanilla (tout le design)
│   │   └── js/app.js        # JS vanilla (tout l'interactif)
│   └── templates/
│       ├── base.html            # Template de base (navbar, footer, scripts)
│       ├── admin_dashboard.html # Tableau de bord admin
│       ├── administration.html  # Page superadmin (email, webhooks)
│       ├── drivers.html         # Gestion des pilotes
│       ├── event_detail.html    # Détail d'un événement
│       ├── event_form.html      # Formulaire événement
│       ├── events_admin.html    # Liste événements admin
│       ├── leaderboard.html     # Classement historique
│       ├── live.html            # Page live (admin)
│       ├── login.html           # Page login
│       ├── mods.html            # Placeholder mods (bientôt disponible)
│       ├── pilot_dashboard.html # Dashboard pilote
│       ├── public.html          # Page publique
│       ├── result_detail.html   # Détail résultat de session
│       ├── results.html         # Liste des résultats
│       ├── server.html          # Page serveur (status + config)
│       ├── settings.html        # Paramètres (superadmin)
│       └── timing.html          # Classement public temps réel
├── aceserver/               # Monté en volume dans les deux containers
│   ├── configs/             # Fichiers JSON de config (default.json, ...)
│   ├── results/             # Résultats de session (result*.json)
│   ├── .panel_state.json    # State file server #1 (pid, config, auto_restart...)
│   ├── .launch_config.json  # Config de lancement (docker_split mode)
│   └── .rotation.json       # Config roulement
├── media/
│   ├── banner/              # Bannières et logos personnalisés
│   └── circuits/            # Images circuits (.webp)
├── translations/            # i18n Babel
│   ├── fr/LC_MESSAGES/messages.po
│   ├── en/LC_MESSAGES/messages.po
│   ├── de/LC_MESSAGES/messages.po
│   ├── es/LC_MESSAGES/messages.po
│   └── it/LC_MESSAGES/messages.po
├── config.py                # Config Flask (lit les variables d'environnement)
├── run.py                   # Point d'entrée (Waitress)
├── compile_mo.py            # Compilation des .po → .mo
├── docker-compose.yml
├── Dockerfile.panel
├── Dockerfile.aceserver
├── .env                     # Variables d'environnement (NON commité)
├── .env.example             # Template .env (commité)
├── VERSION                  # Version courante (1.7.1)
└── CHANGELOG.md             # Historique des versions
```

---

## 5. BASE DE DONNÉES

### Localisation
- SQLite : `panel_data:/panel/data/ace_evo.db`
- Créée automatiquement au démarrage via `db.create_all()`
- Migrations manuelles via `_migrate_db()` dans `__init__.py` → appelée dans `create_app()`

### Modèles

#### `AdminAccount` — Comptes administrateurs
```python
id, username (unique), display_name, password_hash, 
role ("admin"|"superadmin"), is_active, created_at, last_login

get_id() → "aa_{id}"  # préfixe pour Flask-Login
is_superadmin → role == "superadmin"
is_admin → True (toujours)
is_pilot → False (toujours)
```

#### `Driver` — Pilotes
```python
id, ingame_name (unique), email (unique), password_hash,
status ("pending"|"approved"|"rejected"), created_at,
reset_token, reset_token_expires

get_id() → "d_{id}"  # préfixe pour Flask-Login
is_admin → False
is_pilot → True
is_approved → status == "approved"

→ relationship EventRegistration (lazy="dynamic")
```

#### `Event` — Événements planifiés
```python
id, title, description, date (UTC), circuit (SelectedTrackValue),
circuit_display, mode ("GameModeType_PRACTICE"|"GameModeType_RACE_WEEKEND"),
weather, max_drivers, password, notify_before (minutes),
status ("draft"|"published"|"finished"), is_public,
email_sent, discord_notified, auto_launch, launched,
created_at, practice_minutes, qualifying_minutes, warmup_minutes,
race_minutes, allowed_cars (JSON list), cars_config (JSON dict)

Indexes: (status, email_sent), (status, discord_notified)
→ relationship EventRegistration (cascade delete-orphan)

Properties: confirmed_count, pending_count, is_full,
            total_minutes, end_date, mode_display, weather_display
```

#### `EventRegistration` — Inscriptions événements
```python
id, event_id (FK→event), driver_id (FK→driver),
assigned_car, car_display, status ("pending"|"confirmed"|"rejected"),
notified, created_at

UniqueConstraint(event_id, driver_id)
```

#### `SessionResult` — Résultats de session
```python
id, received_at (index), source ("webhook"|"file"),
track, session_type, config_name (nullable), run_id (nullable),
raw_json (JSON brut ACE EVO complet)
```
> **Note** : `config_name` et `run_id` permettent de grouper les sessions par démarrage serveur.
> **TODO multi-serveur** : ajouter `server_id` FK nullable (rétrocompat).

#### `Server` — Instances serveur ← NOUVEAU (feat/multi-server)
```python
id, name, slug (unique), tcp_port, udp_port, http_port,
container_name (unique), driver_password, admin_password,
active_config, is_enabled, sort_order, created_at
```
> Serveur #1 créé automatiquement au premier boot depuis `.env` via `_seed_servers()`.
> Slug = "server-1", container_name = valeur de `ACESERVER_CONTAINER_NAME`.

#### `CarMeta` — Métadonnées véhicules ← NOUVEAU (feat/multi-server)
```python
id, slug (unique) ← car["name"] depuis cars.json,
display_name, category, pi_min, pi_max,
image_path (relatif à media/cars/), is_active
```

#### `TrackMeta` — Métadonnées circuits ← NOUVEAU (feat/multi-server)
```python
id, track_value (unique) ← "slug|layout|label|length_m",
track_name, layout, length_m,
image_path (relatif à media/circuits/), is_active
```

#### `Mod` — Mods téléchargeables ← NOUVEAU (feat/multi-server)
```python
id, mod_type ("car"|"circuit"), name, version,
source_url, status ("available"|"installed"|"updating"|"error"),
installed_at, created_at
```

### Migrations
Pattern dans `__init__.py` → `_migrate_db(db)` :
```python
# Whitelist sécurisée : seuls les tables/colonnes listées peuvent être modifiées
allowed_tables  = {"event", "driver", "session_result"}
allowed_columns = {"practice_minutes", "qualifying_minutes", ...}
cols_to_add = [("table", "colonne", "TYPE DEFAULT val"), ...]
# → ALTER TABLE IF NOT EXISTS via PRAGMA table_info()
```
**Règle** : toute nouvelle colonne doit être whitelistée dans `allowed_tables`/`allowed_columns`.

### User loader Flask-Login
```python
# models.py — préfixes pour distinguer les deux types d'utilisateurs
"aa_123" → AdminAccount(id=123)
"d_45"   → Driver(id=45)
"admin"  → legacy (sessions antérieures à la migration)
```

---

## 6. DÉMARRAGE DE L'APPLICATION

`create_app()` dans `app/__init__.py` — séquence d'initialisation :

```
1. Flask app + config depuis config.py
2. ProxyFix middleware (X-Forwarded-For)
3. SQLAlchemy init + db.create_all()
4. _migrate_db(db)          ← ALTER TABLE manquants
5. _migrate_indexes(db)     ← Index composites
6. _seed_admin_accounts()   ← Premier démarrage : comptes depuis .env
7. _seed_servers()          ← Premier démarrage : Server #1 depuis .env
8. Flask-Babel, Flask-Login, CSRFProtect, Flask-Limiter
9. Enregistrement blueprints (8 blueprints)
10. Jinja globals (app_version, static_version, panel_title...)
11. Route /media/<path> (serve_media)
12. Filtres Jinja (local_dt, local_dt_short, local_dt_input)
13. Context processors:
    - _inject_globals()   → servers, current_server_id, pending_pilots_count
    - _inject_system_warnings() → system_warnings (docker restart policy)
14. Security headers après chaque requête (CSP, X-Frame-Options...)
15. Vérifications sécurité au démarrage (SECRET_KEY par défaut, etc.)
16. init_watchdog()        ← Démarre le watchdog process_manager
17. Création default.json si CONFIGS_DIR vide
18. scan_and_import()      ← Importe résultats existants hors panel
19. discord_notifier.init()
20. mailer.init()
21. entry_list.init()
22. event_scheduler.init() ← Thread scheduler (toutes les 60s)
23. ace_tcp_client.start() ← Si ACE_BOT_STEAM_ID défini
```

### Context processor `_inject_globals()`
Injecté dans **tous** les templates :
- `pending_pilots_count` : nombre de pilotes en attente (badge navbar)
- `discord_invite` : lien Discord
- `servers` : liste des `Server` is_enabled, ordonnés par sort_order
- `current_server_id` : ID du serveur actif (session Flask, défaut 1)

---

## 7. SERVICES

### 7.1 `process_manager.py` — Lifecycle serveur

**Rôle** : démarrer, arrêter, surveiller le serveur ACE EVO. Watchdog auto-restart.

**État post-refactoring A2** (branche feat/multi-server) :

```python
# Constantes globales (pas d'état par serveur)
_PROCESS_NAME = "AssettoCorsaEVOServer"
_DEPLOY_MODE  = os.environ.get("DEPLOY_MODE", "native")
_DOCKER_CONTAINER_NAME = os.environ.get("ACESERVER_CONTAINER_NAME", "ace-server")
_ACESERVER_HOST = os.environ.get("ACESERVER_HOST", "aceserver")

# État par serveur (keyed by server_id)
_servers: dict = {}         # server_id → dict d'état
_servers_lock = threading.Lock()
```

**`_get_server(server_id)`** — création lazy thread-safe du dict d'état :
```python
{
    "watchdog_thread":     None | Thread,
    "watchdog_stop":       threading.Event(),
    "exe_path":            "",
    "wine_ready":          threading.Event(),
    "player_history":      collections.deque(maxlen=120),
    "player_history_lock": threading.Lock(),
    "system_warnings":     [],
    "last_history_sample": 0.0,
}
```

**Helpers de chemin** (tous avec server_id) :
- `_state_file(server_id)` → suffixe `_2`, `_3`... pour server 2+, rien pour server 1 (rétrocompat)
- `_log_file(server_id)` → idem
- `_launch_config_path(server_id)` → utilisé en mode docker_split

**State file** (`.panel_state.json` ou `/aceserver/.panel_state.json`) :
```json
{
  "pid":           12345,
  "config":        "default.json",
  "sc":            "<base64>",
  "sd":            "<base64>",
  "auto_restart":  false,
  "http_port":     8080,
  "run_id":        "uuid_hex",
  "started_at":    1234567890.0,
  "session_changed_at": null,
  "last_session_type":  null
}
```

**API publique** — toutes avec `server_id: int = 1` (rétrocompatible) :

| Fonction | Rôle |
|----------|------|
| `init_watchdog(exe_path, server_id=1)` | Démarrage au boot de l'app |
| `start_server(sc, sd, config_name, auto_restart, server_id=1)` | Lance le serveur |
| `stop_server(server_id=1)` | Arrête le serveur |
| `get_status(server_id=1)` | Retourne l'état complet |
| `is_running(server_id=1)` | Bool rapide |
| `set_auto_restart(enabled, server_id=1)` | Patch le state file |
| `get_server_logs(lines, server_id=1)` | Dernières N lignes de log |
| `get_player_count(server_id=1)` | Appel HTTP vers l'API du serveur |
| `get_player_history(server_id=1)` | Historique joueurs (deque mémoire) |
| `update_session_state(session_type, server_id=1)` | Mis à jour depuis le webhook |
| `try_rotation_advance(session_type, config_name, server_id=1)` | Rotation après session |
| `get_system_warnings(server_id=1)` | Avertissements config Docker |

**Modes de fonctionnement** :

| Mode | Description | Détection running | Start |
|------|-------------|-------------------|-------|
| `docker_split` | Mode prod | `.launch_config.json` existe + container "running" | `container.start()` / `container.restart()` |
| `docker` | Wine monolithique | psutil scan des cmdlines | subprocess wine |
| `native` | Windows natif | psutil by name | subprocess direct |

**Watchdog** — tourne toutes les 10s :
- Vérifie si le serveur tourne
- Si arrêté + auto_restart → redémarre
- Si arrêté + rotation → passe à la config suivante
- Discord notify sur crash
- Incrémente player_history toutes les 30s

**Rotation** :
- Webhook-driven : `try_rotation_advance()` → thread séparé, sleep 3s → rotate
- Watchdog-driven : détecte container/process mort → rotate

### 7.2 `server_config.py` — Configuration JSON

**Rôle** : lecture, écriture, validation des fichiers JSON de configuration ACE EVO.

**Config active** : stockée en session Flask (`session["active_config"]`).

**Fonctions clés** :

```python
load_config() → dict
# Lit active config + deep_merge(_default_config(), raw)
# TOUJOURS utiliser cette fonction pour obtenir une config complète

load_config_by_name(name) → dict | None
# Idem mais sans toucher à la session

_default_config() → dict
# Template vide avec toutes les clés + valeurs depuis les env vars
# CRITIQUE : c'est cette fonction qui lit SERVER_NAME, SERVER_TCP_PORT, etc.
# Ne PAS appeler trop souvent (lit os.environ à chaque appel)

check_config() → list[str]
# Lit le JSON brut (PAS via load_config) pour détecter les clés manquantes
# IMPORTANT : ne pas passer par load_config ici (sinon jamais de clés manquantes)

repair_config() → dict
# deep_merge(_default_config(), load_config()) → save

apply_server_patch(patch, is_superadmin) → dict
# Patch partiel de la config active (depuis l'API)
# Champs protégés : TcpPort, UdpPort, HttpPort → superadmin seulement
# Champs globaux (_GLOBAL_FIELDS) ignorés (gérés via Settings)

inject_global_server_settings(config) → dict
# Injecte les valeurs .env dans config["Server"]
# Appelé UNIQUEMENT dans _do_start() (api.py), pas au save
# Jamais appelé dans apply_server_patch (sinon bake dans le JSON)

save_config(data)
# Écrit dans la config active

build_config_from_event(event) → dict
# Construit une config depuis un Event DB (pour auto-launch)

save_event_config(event, cfg) → str
# Sauvegarde dans CONFIGS_DIR/event_{id}_{slug}.json
```

**`_deep_merge(base, override)`** :
- Fusionne `override` dans `base` : les clés manquantes dans `override` sont héritées de `base`
- Les listes sont remplacées (pas mergées)
- Utilisé partout pour éviter les `KeyError` sur les nouvelles clés de config

**`_GLOBAL_FIELDS`** : Mapping `.env vars` → champs JSON injectés au lancement :
```python
"SERVER_NAME"            → Server.ServerName
"SERVER_MAX_PLAYERS"     → Server.MaxPlayers
"SERVER_TCP_PORT"        → Server.TcpPort
"SERVER_UDP_PORT"        → Server.UdpPort
"SERVER_DRIVER_PASSWORD" → Server.DriverPassword
"SERVER_ADMIN_PASSWORD"  → Server.AdminPassword
"SERVER_ENTRY_LIST_PATH" → Server.EntryListPath
"SERVER_RESULTS_PATH"    → Server.ResultsPath
```

### 7.3 `ace_tcp_client.py` — Client TCP

**Rôle** : connexion TCP au port 9700 d'ACE EVO pour chat in-game + leaderboard temps réel.

**État** : module-level vars (single server, pas encore refactorisé pour multi-serveur) :
```python
_host, _port, _steam_id, _car_model   # config connexion
_sock, _lock, _connected, _running    # état socket
_leaderboard: dict[str, dict]         # steam_id → {name, num, sector, time_ms}
_lb_lock: threading.Lock()            # protège _leaderboard + tous les dicts ci-dessous
_join_times: dict                     # steam_id → timestamp
_car_id_to_sid: dict                  # car_id → steam_id
_num_to_sid: dict                     # car_num → steam_id
_sid_car_raw: dict                    # steam_id → modèle voiture
_recently_disconnected: dict          # steam_id → {name, car_raw, ts}
_race_state: dict                     # {"server_best_ms": None}
```

**Protocole** : `[uint16_LE: total_len-2][0x02][0x00][uint8: name_len][name][protobuf_payload]`

**Messages supportés** :
- C2S `ClientConnectionRequest` : handshake initial
- C2S `MultiplayerChatMessage` : envoi message chat
- S2C `BroadcastStateMessage` : état courant (PlatformRaceLeaderboard)
- S2C `SplitFromRemoteMessage` : passage de secteur

**Threads lancés** :
- `ace-tcp-client` : `_connect_loop()` — connexion + reconnexion auto toutes les 5s
- `ace-welcome-bot` : `_welcome_loop_docker()` ou `_welcome_loop_native()` — monitoring logs

**Détection changement véhicule** :
Reconnexion dans les 10 minutes + modèle voiture différent → notif Discord "changement de véhicule" au lieu de "connexion".

**`_process_log_line(line, seen)`** :
Parse les logs du serveur pour détecter : connexion, déconnexion, nouveau tour, meilleur tour, reset session.
Les notifs Discord (join/disconnect/best_lap/vehicle_change) sont envoyées depuis ici.

**⚠️ TODO multi-serveur (A3)** : convertir tous les module-level vars en dict `{server_id: ...}`.

### 7.4 `results_parser.py` — Parsing résultats

**Rôle** : transformer le JSON brut ACE EVO en dict structuré pour l'affichage.

**Format ACE EVO** :
- `drivers[]` : guid {a,b} → first_name, last_name, nickname, player_id, nation
- `cars[]` : car_id {a,b} → model_displayname, race_number
- `laps[]` : driver_key, car_key, time (ms), split [ms, ms, ms], flags
- `driver_standings[]` : ordre classement par guid
- `time_standings[]` : meilleur temps par driver (même index que driver_standings)
- `car_standings[]` : total_km, total_fuel_liters, starting_position

**Flags de tour** :
- `flags == 2` : tour propre officiel
- `flags < 64` : avec avertissement (⚠)
- `flags >= 64` : invalide (grisé)
- `flags & 128` : tour de formation

**`parse_result_file(data)`** retourne :
```python
{
    "track", "layout", "session_type", "is_race",
    "server_name", "is_completed", "session_duration_ms",
    "session_best_ms", "session_best_splits_ms",
    "standings": [{
        "position", "nickname", "full_name", "nation", "nation_flag",
        "car", "race_number", "starting_position",
        "best_lap_ms", "best_lap", "best_splits_ms",
        "race_time_ms", "race_time", "race_laps_count",
        "fastest_lap_ms", "gap_ms", "gap", "gap_laps",
        "consistency_ms", "total_km",
        "all_laps": [{lap_num, time, time_ms, splits, flags, is_clean, ...}]
    }]
}
```

**`scan_and_import(aceserver_dir)`** : scanne les `result*.json` et importe ceux pas encore en DB (détection par hash `raw_json`).

### 7.5 `rotation_manager.py` — Roulement de configs

**Rôle** : séquence de fichiers JSON à enchaîner automatiquement.

**State file** : `/aceserver/.rotation.json`
```json
{"enabled": true, "cycle": false, "configs": ["practice.json", "race.json"]}
```

**`get_next_config(current_config)`** :
- Retourne le nom du prochain fichier
- `None` si fin de liste sans cycle
- Retourne `configs[0]` si config courante absente de la liste

### 7.6 `event_scheduler.py` — Scheduler

**Rôle** : thread background, boucle toutes les 60 secondes.

**Actions** :
1. Emails de rappel (N minutes avant l'événement, selon `notify_before`)
2. Discord 30min avant (fenêtre 29-31 min, flag `discord_notified`)
3. Auto-launch serveur quand `auto_launch=True` et `date <= now`
4. Auto-finish événements expirés (date + total_minutes + 1h)

**`_launch_event(app, event, db)`** :
```
build_config_from_event(event)
→ save_event_config(event, cfg)
→ build_launch_args(cfg)          # config_builder
→ start_server(sc, sd, config_name, auto_restart=True)
→ notify Discord
```

### 7.7 `discord_notifier.py` — Notifications Discord

**3 webhooks** :
- `DISCORD_WEBHOOK_URL` : démarrage, arrêt, crash
- `DISCORD_PILOTS_WEBHOOK_URL` : connexions pilotes, inscriptions
- `DISCORD_RACE_WEBHOOK_URL` : meilleur tour, actions admin

**`safe_notify(fn, *args)`** : wrapper thread-safe pour appels depuis threads background.

**`_tmpl(env_key, default, **kwargs)`** : templates configurables via `.env`.

### 7.8 `config_builder.py` — Construction args de lancement

**Rôle** : encode la config JSON en arguments base64 pour l'exécutable.

**`build_launch_args(config)`** → `(sc_b64, sd_b64)` :
- `sc_b64` : serverconfig (Server + Event + Sessions en protobuf/JSON encodé)
- `sd_b64` : seasondefinition (config de saison)

Ces deux strings sont passées à `AssettoCorsaEVOServer.exe -serverconfig <sc_b64> -seasondefinition <sd_b64>`.

### 7.9 `mailer.py` — SMTP

**Initialisation** : `mailer.init(app.config)` lit MAIL_SERVER, MAIL_PORT, etc.

**Fonctions** :
- `send_event_reminder(driver, event, reg)` : email de rappel pilote
- `send_test(to)` : test d'envoi

### 7.10 `entry_list.py` — Liste d'entrée

**Rôle** : génère `entry_list.ini` à partir des inscriptions événement.

**Initialisation** : `entry_list.init(aceserver_dir)` — mémorise le dossier.

---

## 8. ROUTES

### 8.1 Blueprint `auth` — Authentification

| Route | Méthode | Description |
|-------|---------|-------------|
| `/login` | GET/POST | Login (AdminAccount ou Driver) |
| `/logout` | GET | Déconnexion |
| `/register` | GET/POST | Inscription pilote (status=pending) |
| `/forgot-password` | GET/POST | Demande reset |
| `/reset-password/<token>` | GET/POST | Reset mot de passe |

### 8.2 Blueprint `admin` — Administration

| Route | Méthode | Auth | Description |
|-------|---------|------|-------------|
| `/dashboard` | GET | admin | Tableau de bord |
| `/server` | GET | admin | Page serveur (status + config) |
| `/settings` | GET/POST | superadmin | Paramètres .env |
| `/settings/upload-media` | POST | superadmin | Upload bannière |
| `/accounts/create` | POST | superadmin | Créer compte admin |
| `/accounts/<id>/edit` | POST | superadmin | Modifier compte |
| `/accounts/<id>/toggle` | POST | superadmin | Activer/désactiver |
| `/accounts/<id>/delete` | POST | superadmin | Supprimer compte |
| `/server/select/<server_id>` | POST | admin | Changer serveur actif (session) |
| `/mods` | GET | admin | Page mods (placeholder) |
| `/administration` | GET | superadmin | Page administration (email, webhooks) |
| `/administration/test-email` | POST | superadmin | Test email |
| `/administration/test-webhook` | POST | superadmin | Test webhook Discord |

### 8.3 Blueprint `api` — REST API

| Route | Méthode | Auth | Description |
|-------|---------|------|-------------|
| `/api/status` | GET | public* | État serveur (limité si non admin) |
| `/api/server/logs` | GET | admin | Dernières lignes de log |
| `/api/server/start` | POST | admin | Démarrer le serveur |
| `/api/server/stop` | POST | admin | Arrêter |
| `/api/server/restart` | POST | admin | Redémarrer |
| `/api/server/auto-restart` | POST | admin | Activer/désactiver auto-restart |
| `/api/config` | GET | admin | Config active |
| `/api/config` | POST | admin | Patch config active |
| `/api/configs` | GET | admin | Liste configs + active |
| `/api/configs/select` | POST | admin | Changer config active |
| `/api/configs/create` | POST | admin | Créer config |
| `/api/configs/<name>` | GET | admin | Config par nom |
| `/api/configs/delete` | POST | admin | Supprimer config |
| `/api/configs/rename` | POST | admin | Renommer config |
| `/api/config/check` | GET | admin | Valider config |
| `/api/config/repair` | POST | admin | Réparer config |
| `/api/cars` | GET | admin | Liste véhicules |
| `/api/events/<mode>` | GET | admin | Événements (practice/race) |
| `/api/results/ingest` | POST | HMAC | Webhook résultats ACE EVO |
| `/api/results` | GET | login | 50 derniers résultats |
| `/api/results/<id>` | GET | login | Détail résultat |
| `/api/rotation/start` | POST | admin | Démarrer roulement |
| `/api/rotation` | GET/POST | admin | Lire/écrire roulement |
| `/api/live/chat` | POST | admin | Envoyer message chat TCP |
| `/api/live/tcp_status` | GET | admin | État connexion TCP |
| `/api/live/tcp_debug` | GET | admin | Debug TCP |
| `/api/live/admin_cmd` | POST | admin | Commande admin in-game |

**`_do_start()`** — flux de démarrage du serveur :
```
get_status() → si running avec autre config → stop_server()
load_config()
inject_global_server_settings(config)   ← env vars → JSON
config_builder.build_launch_args(config) → (sc_b64, sd_b64)
start_server(sc, sd, config_name, auto_restart)
discord_notifier.notify_start()
```

**`results_ingest`** — webhook ACE EVO :
```
_read_state(1)      ← récupère config_name et run_id même si serveur arrêté
_verify_ingest_signature()   ← HMAC-SHA256
parse_result_file()
→ SessionResult (config_name, run_id)
try_rotation_advance()       ← déclenche rotation si applicable
update_session_state()       ← met à jour last_session_type dans state file
```

### 8.4 Blueprint `live` — Monitoring temps réel

| Route | Méthode | Auth | Description |
|-------|---------|------|-------------|
| `/live` | GET | login | Page live (admin) |
| `/timing` | GET | public | Classement public temps réel |
| `/api/live/state` | GET | login | État courant (leaderboard log) |
| `/api/timing` | GET | public | API timing publique |
| `/api/live/stream` | GET | login | SSE stream de logs |
| `/api/live/bot/elevate-admin` | POST | admin | Envoyer \admin via TCP |

**`_build_state()`** : parse les logs des 24 dernières heures → drivers connectés + leaderboard avec tours/secteurs.

**`_session_timing()`** : durée de session + started_at depuis `_read_state(1)`.

### 8.5 Blueprint `public` — Pages publiques

Pages sans authentification (accès ouvert) :
- `/` : Page d'accueil publique
- `/results` : Historique résultats
- `/leaderboard` : Classement général

### 8.6 Blueprint `events_admin` — Gestion événements

CRUD événements, gestion inscriptions pilotes, export entry_list.

### 8.7 Blueprint `leaderboard` — Classements

Classements historiques par pilote, par circuit.

### 8.8 Blueprint `container_mgmt` — Gestion Docker

Mise à jour du serveur ACE EVO via SteamCMD.

---

## 9. FRONTEND

### 9.1 `base.html` — Template de base

Structure :
```html
<aside class="sidebar">
  logo + nom panel
  nav links (Dashboard, Serveur, Résultats, Live, Events, Pilotes, Mods)
  <div class="server-selector">   ← sélecteur serveur (feat/multi-server)
    - 1 serveur : affichage fixe non cliquable
    - N serveurs : dropdown avec POST /server/select/<id>
  </div>
  dropdown admin (compte, langue, déconnexion)
</aside>

<div class="content">
  flash messages (success/error/warning)
  system_warnings (bannière rouge si config Docker incorrecte)
  {% block content %}
</div>

<script src="/static/js/app.js?v={{ static_version }}">
```

### 9.2 `server.html` — Page serveur

Deux vues (onglets JS) :
- **Status** : état serveur, config active, info session, activité récente, boutons start/stop/restart
- **Config** : éditeur de configuration (voitures, circuit, météo, sessions, roulement)

### 9.3 `app.js` — JavaScript principal

Fonctions clés :

```javascript
// Polling status (toutes les 5s)
updateStatusUI(data)
  → met à jour le point de statut (vert/rouge)
  → synchronise les boutons start/stop/restart
  → synchronise les checkboxes auto-restart (#srv-auto-restart-card, #srv-auto-restart-label)
  → affiche/cache la bannière config-dirty
  → _serverRunning = data.running

serverAction(action)
  → confirm() pour "stop" et "restart"
  → bouton passe en "loading" avec label traduit
  → fetch POST /api/server/<action>
  → restore label depuis b.dataset.origLabel

saveAll()
  → collecte tous les champs du formulaire de config
  → fetch POST /api/config
  → si succès + serveur en cours → affiche bannière config-dirty

// Gestion configs
_rotConfigs: []
updateRotationUI()
addRotConfig()
removeRotConfig()
saveRotation()
```

### 9.4 `main.css` — Feuille de style

Variables CSS principales :
```css
--accent: #e8aa28  /* orange ACE EVO */
--bg: #0d0d0d
--surface: #1a1a1a
--surface2: #252525
--dim: #888
--text: #f0f0f0
```

Classes importantes :
- `.settings-card` / `.settings-card-head` : cartes de configuration
- `.settings-dashboard-grid` : grille responsive
- `.btn`, `.btn-primary`, `.btn-danger` : boutons
- `.form-control` : inputs
- `.status-dot.green` / `.status-dot.red` : indicateur état serveur
- `.server-selector` : sélecteur multi-serveur navbar

---

## 10. i18N

### Configuration
- Framework : Flask-Babel
- 5 langues : `fr`, `en`, `de`, `es`, `it`
- Fichiers : `translations/{lang}/LC_MESSAGES/messages.po`
- Compilés : `messages.mo` (générés par `compile_mo.py`)
- Langue stockée en session : `session["lang"]`
- Fallback : `request.accept_languages`

### Règle absolue
**Tout texte visible par l'utilisateur est une clé de traduction. Sans exception.**

```python
# Dans les routes/templates (contexte requête)
_('texte')
# Dans les modules (lazy, chargé à la requête)
lazy_gettext('texte')  # utilisé dans _ENV_DESCS
```

### Workflow après modification
```bash
# 1. Ajouter la nouvelle clé dans les 5 fichiers .po
# 2. Compiler
docker compose exec panel python compile_mo.py
# 3. Rebuild si les .mo sont dans l'image
docker compose up -d --build panel
```

---

## 11. SÉCURITÉ

### Authentification
- `@login_required` (Flask-Login) : requiert d'être connecté
- `@admin_required` (utils.py) : requiert `current_user.is_admin`
- `@superadmin_required` (utils.py) : requiert `current_user.is_superadmin`
- `@admin_required_json` / `@superadmin_required_json` : versions JSON (retournent 403)
- **Correction critique** : les deux décorateurs `superadmin_required*` vérifient `not current_user.is_authenticated` avant `.is_superadmin` pour éviter AttributeError sur AnonymousUser.

### CSRF
- Flask-WTF `CSRFProtect` active sur tous les blueprints sauf :
  - `live_bp` (SSE stream)
  - `results_ingest` (webhook externe protégé par HMAC)
- Formulaires : `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`
- Fetch JS : header `X-CSRFToken`

### Webhook ingest
- Protégé par HMAC-SHA256 (`RESULTS_INGEST_SECRET`)
- Si secret vide : autorisé seulement depuis réseau privé/loopback
- Headers acceptés : `X-ACE-Signature`, `X-Webhook-Signature`, `X-Hub-Signature-256`

### Security headers (après chaque requête)
```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; ...
HSTS: si SESSION_COOKIE_SECURE=true
```

### Données sensibles
```python
_SENSITIVE = {
    "SECRET_KEY", "MAIL_PASSWORD", "MAIL_USERNAME",
    "DISCORD_WEBHOOK_URL", "DISCORD_PILOTS_WEBHOOK_URL", "DISCORD_RACE_WEBHOOK_URL",
    "DISCORD_MENTION_MAIN", "DISCORD_MENTION_PILOTS", "DISCORD_MENTION_RACE",
    "RESULTS_INGEST_SECRET", "SERVER_DRIVER_PASSWORD", "SERVER_ADMIN_PASSWORD"
}
# → affichées en type="password" dans settings.html
# → jamais loggées
```

### Upload médias
- Extension vérifiée + signature de fichier (magic bytes)
- Nom sanitisé : `re.sub(r"[^a-zA-Z0-9_-]", "_", stem)[:40]` + uuid prefix
- Taille max 5 Mo

---

## 12. VARIABLES D'ENVIRONNEMENT

### Requises au démarrage
```
SECRET_KEY           # Sessions Flask (generate avec secrets.token_hex(32))
ADMIN_PASSWORD       # Mot de passe admin initial
SUPERADMIN_PASSWORD  # Mot de passe superadmin initial
```

### Infrastructure
```
DEPLOY_MODE          # native | docker | docker_split (défaut: native)
PANEL_PORT           # Port panel (défaut: 4300)
PANEL_URL            # URL publique (pour emails)
PANEL_TIMEZONE       # Fuseau horaire (ex: Europe/Paris)
DEFAULT_LOCALE       # Langue par défaut (fr/en/de/es/it)
SESSION_COOKIE_SECURE # true/false (true derrière HTTPS)
```

### Serveur de jeu
```
SERVER_NAME           # Nom dans la liste ACE EVO
SERVER_MAX_PLAYERS    # 1-128
SERVER_TCP_PORT       # Port TCP (défaut: 9700)
SERVER_UDP_PORT       # Port UDP (défaut: 9700)
SERVER_DRIVER_PASSWORD # Mot de passe accès (vide = ouvert)
SERVER_ADMIN_PASSWORD  # Mot de passe admin in-game
ACESERVER_DIR         # Dossier installation ACE EVO (/aceserver)
ACESERVER_CONTAINER_NAME # Nom container ace-server (défaut: ace-server)
ACESERVER_HTTP_PORT   # Port HTTP API serveur (défaut: 8080)
ACESERVER_TCP_HOST    # Hôte TCP (défaut: 127.0.0.1 / aceserver en docker)
ACESERVER_TCP_PORT    # Port TCP bot (défaut: 9700)
CONFIGS_DIR           # Dossier configs JSON
```

### Bot TCP
```
ACE_BOT_STEAM_ID     # Steam ID 64-bit (vide = désactivé)
ACE_BOT_CAR_MODEL    # Modèle voiture bot
ACE_BOT_IS_ADMIN     # true/false
ACE_BOT_MSG_WELCOME  # "{name}"
ACE_BOT_MSG_DISCORD  # "{name}", "{discord_url}"
ACE_BOT_MSG_SITE     # "{name}", "{site_url}"
```

### Discord
```
DISCORD_WEBHOOK_URL        # Serveur (démarrage, arrêt, crash)
DISCORD_PILOTS_WEBHOOK_URL # Pilotes (connexions, inscriptions)
DISCORD_RACE_WEBHOOK_URL   # Course (meilleur tour, actions admin)
DISCORD_INVITE_URL         # Lien affiché sur le panel
DISCORD_MENTION_MAIN/PILOTS/RACE # @here ou <@&role_id>
DISCORD_MSG_*              # Templates messages (optionnel)
RESULTS_INGEST_SECRET      # HMAC webhook
```

### Email
```
MAIL_SERVER, MAIL_PORT, MAIL_USE_TLS, MAIL_USERNAME
MAIL_PASSWORD, MAIL_FROM, MAIL_ADMIN
```

---

## 13. FLUX DE DONNÉES CRITIQUES

### Flux 1 : Démarrage serveur depuis le panel

```
User clique "Démarrer"
→ app.js: fetch POST /api/server/start
→ api.py: server_start() → _do_start()
  → get_status()         # vérifie état actuel
  → load_config()        # lit active_config + deep_merge
  → inject_global_server_settings(config) # env → JSON (Server.ServerName, etc.)
  → config_builder.build_launch_args(config) → (sc_b64, sd_b64)
  → process_manager.start_server(sc_b64, sd_b64, config_name, auto_restart)
    [docker_split]
    → écrit .launch_config.json
    → docker container.start() ou container.restart()
    → _write_state(pid=0, config, sc, sd, auto_restart, http_port, run_id=uuid)
    [native]
    → subprocess.Popen(exe, -serverconfig sc_b64, -seasondefinition sd_b64)
    → _write_state(proc.pid, ...)
  → discord_notifier.notify_start()
→ return {"ok": True, "pid": ..., "run_id": ...}
→ app.js: mise à jour UI immédiate + polling reprend
```

### Flux 2 : Réception résultats de session

```
ACE EVO POST /api/results/ingest (JSON résultats)
→ api.py: results_ingest()
  → _read_state(1)            # run_id + config_name (même si serveur arrêté)
  → _verify_ingest_signature() # HMAC ou réseau privé
  → parse_result_file(data)
  → SessionResult(raw_json, config_name, run_id)
  → db.session.commit()
  → try_rotation_advance(session_type, config_name)
    → rotation_manager.get_next_config()
    → [thread séparé, sleep 3s]
    → _watchdog_rotate_docker() ou _watchdog_rotate_native()
  → update_session_state(session_type) → _write_state() partiel
```

### Flux 3 : Auto-restart / Watchdog

```
[Thread server-watchdog-1, toutes les 10s]
is_running() → False
_read_state() → {auto_restart: true, config: "default.json", sc, sd}
→ si rotation active:
  → get_next_config("default.json") → "race.json"
  → _watchdog_rotate_docker()
    → lire configs/race.json
    → build_launch_args()
    → écrire .launch_config.json
    → container.restart()
    → _write_state(0, "race.json", ...)
    → discord_notifier.notify_rotation_advance()
→ si auto_restart seulement:
  → discord_notifier.notify_crash()
  → container.start() ou _launch(exe, sc, sd)
  → _write_state(pid, ...)
```

### Flux 4 : Sélection serveur multi-serveur

```
User clique sur un serveur dans le dropdown
→ form POST /server/select/<server_id>
→ admin.py: select_server(server_id)
  → db.session.get(Server, server_id)
  → si Server.is_enabled: session["current_server_id"] = server_id
  → redirect(next_url ou referrer ou /dashboard)
→ _inject_globals() lit session["current_server_id"] → injecté dans tous les templates
```

### Flux 5 : Client TCP — détection connexion pilote

```
[Thread ace-welcome-bot, tail des logs]
_welcome_loop_docker() → container.logs(stream=True, follow=True)
→ pour chaque ligne:
  → _process_log_line(line, seen)
    
    Ligne "[gameplay] [info] 76561198... connected on car preset_190_evo_ii, with carId abc-123"
    → _sid_car_raw["76561198..."] = "preset_190_evo_ii"
    → _car_id_to_sid["abc-123"]  = "76561198..."
    → _join_times["76561198..."] = time.time()
    
    Ligne "[server] [info] Car [...] #42 for driver ZyphRo [76561198...]"
    → _num_to_sid["42"] = "76561198..."
    → check _recently_disconnected (changement véhicule ?)
    → Thread: _send_welcome("ZyphRo") [sleep 2s + messages chat]
    → discord_notifier.notify_player_join("ZyphRo", "42", "preset_190_evo_ii", sid)
```

---

## 14. ÉTAT ACTUEL — BRANCHE `feat/multi-server`

### Ce qui est fait ✅

#### A1 — Modèle `Server` + seed
- **Fichier** : `app/models.py` lignes 208-224
- **Fichier** : `app/__init__.py` fonctions `_seed_servers()` + appel dans `create_app()`
- Server #1 créé au premier boot depuis `.env`
- Slug : "server-1", container_name depuis `ACESERVER_CONTAINER_NAME`

#### A2 — `process_manager.py` refactoring complet
- **Fichier** : `app/services/process_manager.py` — 740 lignes
- `_STATE_FILE` → `_state_file(server_id: int) -> Path`
- `_LOG_FILE` → `_log_file(server_id: int) -> Path`
- `_launch_config_path(server_id: int) -> Path`
- Globaux thread → `_servers: dict` + `_get_server(server_id)` lazy thread-safe
- Toutes les fonctions publiques : `server_id: int = 1` (rétrocompatibles)
- Noms threads : `server-watchdog-1`, `wine-prewarm-2`, `rotation-webhook-1`

#### Corrections appelants post-A2
- `app/__init__.py:328` : `_log_file(1)` (au lieu de `_LOG_FILE`)
- `app/routes/live.py:107` : `_log_file(1)`
- `app/routes/live.py:284` : `_read_state(1)`
- `app/services/server_config.py:214` : `_read_state(1)`
- `app/routes/api.py:292` : `_pm_read_state(1)`

#### B1/B2/C1 — Modèles `CarMeta`, `TrackMeta`, `Mod`
- **Fichier** : `app/models.py` lignes 228-268
- Tables créées automatiquement par `db.create_all()`

#### Nav/UI fondation
- Sélecteur serveur dans `base.html` (single: non-cliquable, multi: dropdown POST)
- Route `POST /server/select/<server_id>` dans `admin.py`
- CSS `.server-selector*` dans `main.css`
- `servers` + `current_server_id` injectés dans tous les templates via `_inject_globals()`
- Page Mods placeholder (`mods.html` + route `/mods`)
- "Mods" dans le menu nav

#### Translations
Nouvelles clés ajoutées dans les 5 langues : Mods, Serveur, véhicules/circuits, bientôt disponible, confirmations start/stop/restart.

### Ce qui reste à faire ❌

#### A3 — `ace_tcp_client.py` refactoring pool ✅ DONE
#### Phase 3 — Adaptation des pages existantes ✅ DONE
- `api.py` : `_current_server_id()` helper + toutes routes server/logs/start/stop/restart/auto-restart/rotation_start/results_ingest server-aware
- `admin.py` : `dashboard()`, `server()`, `settings()` utilisent `session.get("current_server_id", 1)`
- `server_config.py` : `get_running_server_info(server_id=1)` propague server_id
- `results_parser.py` : `scan_and_import` + `import_result_file` propagent server_id

#### Phase 3bis — FK `server_id` sur `SessionResult` ✅ DONE
- `app/models.py` : `server_id = db.Column(db.Integer, nullable=True, index=True)`
- `app/__init__.py` : migration `("session_result", "server_id", "INTEGER")` dans `_migrate_db()`
- `api.py/results_ingest` : lit `?server_id=N` (query param ACE EVO) et persiste en DB

#### Phase 2 — Création de serveurs depuis le panel ✅ DONE
- Formulaire (nom, ports, container_name) → INSERT Server
- Docker : création dynamique de containers depuis le panel
- Watchdog multi-serveur opérationnel
- [x] Bot TCP multi-serveur : `start_for_server(srv, cfg)` dans `ace_tcp_client.py`, appelé au boot (tous les serveurs activés) et à la création d'un nouveau serveur. En mode `docker_split` : host = container_name, port = 9700 interne (pas le port host-mappé)

#### Phase 4 — Banque de données véhicules/circuits (indépendant)
- Population `CarMeta` depuis `cars.json` au démarrage (scan + upsert)
- Upload images véhicules (`media/cars/<slug>.jpg`)
- [x] Population `TrackMeta` depuis les fichiers events (`events_practice.json` + `events_race_weekend.json`) — 36 circuits, fallback configs pour tracks custom
- Images circuits : déjà dans `media/circuits/*.webp`
- Refonte page véhicules avec images et filtres

#### Phase 5 — Mods (dépend API Kunos)
- En attente de l'API publique Kunos pour téléchargement de mods
- Page `/mods` complète avec download/install workflow
- Mise à jour table `Mod` avec statuts

---

## 15. ROADMAP MULTI-SERVEUR — PHASES DÉTAILLÉES

### Prérequis à vérifier avant Phase 2 (Docker création)
```bash
# Vérifier ce que le dockerproxy expose :
docker exec ace-docker-proxy env | grep -i container
# Options dockerproxy pour CREATE :
#   CREATE: 1  → nécessaire pour docker create
#   RUN: 1     → nécessaire pour docker run (= create + start)
```

Si le dockerproxy ne supporte pas CREATE, options :
1. Ajouter `CREATE: 1` au dockerproxy (et `RUN: 1` si docker-py l'utilise)
2. Pré-créer les containers dans `docker-compose.yml` et ne gérer que start/stop
3. **Option recommandée** : template `docker-compose.yml` multi-serveur avec containers prédéfinis

### Phase 2 détaillée — Moteur multi-serveur

**Étape 2.1 : Recherche Docker API**
- Tester la création de container via `docker.from_env().containers.create()`
- Vérifier dockerproxy permissions
- Décider entre création dynamique vs statique

**Étape 2.2 : Formulaire création serveur**
```
/admin/servers/create (GET/POST)
→ Champs: name, tcp_port, udp_port, http_port, container_name, driver_password, admin_password
→ Server.create() → INSERT
→ docker.containers.create("ace-server-image", name=container_name, ports={...})
→ redirect /dashboard
```

**Étape 2.3 : init_watchdog multi**
```python
# create_app() devra appeler init_watchdog pour chaque Server.is_enabled
from app.models import Server
for srv in Server.query.filter_by(is_enabled=True).all():
    init_watchdog(exe_path, server_id=srv.id)
```
> **Point de vigilance** : actuellement `init_watchdog` est appelé une fois sans `server_id`. Il faudra refactoriser cet appel.

**Étape 2.4 : `_DOCKER_CONTAINER_NAME` per-server**

Actuellement `_DOCKER_CONTAINER_NAME` est une constante globale lue depuis `.env`.
En multi-serveur, chaque server a son propre `container_name` en DB.

Solution : passer `container_name` en paramètre à `_get_aceserver_container(server_id)` :
```python
def _get_aceserver_container(server_id: int = 1):
    from app.models import Server
    srv = Server.query.get(server_id)
    name = srv.container_name if srv else _DOCKER_CONTAINER_NAME
    return _get_docker_client().containers.get(name)
```
> Nécessite un contexte Flask ! Attention aux appels depuis les threads watchdog sans contexte.
> Solution : stocker `container_name` dans `_get_server(server_id)` dict au moment de `init_watchdog`.

### Phase 3 détaillée — Adaptation routes

**Principe** : `current_server_id = session.get("current_server_id", 1)` lu dans chaque route qui interagit avec un serveur spécifique.

**Routes à adapter dans `api.py`** :
```python
# Avant
result = start_server(sc, sd, config_name)

# Après
server_id = session.get("current_server_id", 1)
result = start_server(sc, sd, config_name, server_id=server_id)
```

**Configs per-server** :
```
# Structure cible
aceserver/
  configs/
    server-1/
      default.json
      race.json
    server-2/
      default.json
```
> `_configs_dir()` dans `server_config.py` devra prendre `server_id` et retourner le bon sous-dossier.
> `get_active_config_name()` lira `Server.active_config` depuis DB plutôt que la session.

**Settings** :
Scinder la page en :
- **Onglet Panel** : clés globales (SECRET_KEY, PANEL_TITLE, email, Discord, etc.)
- **Onglet Serveurs** : par serveur (ports, mots de passe, container) → édite la table `Server`

### Phase 4 détaillée — CarMeta + TrackMeta

**Population CarMeta au démarrage** :
```python
# Dans create_app() après _seed_servers() :
def _sync_car_meta(db):
    """Synchronise CarMeta depuis cars.json."""
    from app.services.server_config import load_cars
    try:
        cars = load_cars()
    except Exception:
        return
    for car in cars:
        slug = car["name"]
        meta = CarMeta.query.filter_by(slug=slug).first()
        if not meta:
            meta = CarMeta(slug=slug, display_name=car.get("display_name",""), ...)
            db.session.add(meta)
    db.session.commit()
```

**Conventions images** :
- `media/cars/<slug>.webp` (ou .jpg)
- Slug = `car["name"]` normalisé (déjà utilisé tel quel dans cars.json)
- Upload via `/settings/upload-car-image` ou drag&drop sur la page véhicules

**Population TrackMeta** :
- [x] Source : `events_practice.json` + `events_race_weekend.json` (catalogue complet), fallback configs pour tracks custom
- Format : `"Brands Hatch|GP|GP Time Attack|3916"` → track_name, layout, length_m

---

## 16. POINTS DE VIGILANCE ET DÉCISIONS ARCHITECTURALES

### 16.1 Thread safety

**`process_manager.py`** :
- `_servers_lock` : protège la création du dict `_servers[server_id]` (lazy init)
- `_servers[server_id]["player_history_lock"]` : protège le deque history
- `_watchdog_stop` : threading.Event, jamais set en pratique (watchdog daemon)

**`ace_tcp_client.py`** :
- `_lock` : protège `_sock`, `_connected` (envoi et lecture état connexion)
- `_lb_lock` : protège TOUS les dicts partagés (_leaderboard, _join_times, etc.)
- **Règle** : acquérir le lock, copier les données, relâcher, traiter hors lock

### 16.2 Contexte Flask dans les threads

Les threads background (watchdog, scheduler, bot TCP) n'ont pas de contexte Flask.
- `server_config.py` utilise `current_app.config` → **ne pas appeler depuis un thread**
- `get_running_server_info()` dans `server_config.py` est OK car appelé depuis les routes
- `process_manager.py` utilise `current_app.config` dans `start_server()` pour le chemin de l'exe → OK car appelé depuis les routes
- Le watchdog, la rotation, `try_rotation_advance()` → n'utilisent pas `current_app`

### 16.3 Config active vs session Flask

`get_active_config_name()` et `set_active_config()` utilisent `session["active_config"]`.
La session Flask n'est disponible que dans le contexte d'une requête.
→ Les threads background lisent `_read_state(server_id)` pour connaître la config en cours.

**En multi-serveur** : la config active sera dans `Server.active_config` (DB) plutôt que la session.

### 16.4 `inject_global_server_settings` — quand l'appeler

Cette fonction injecte les env vars dans la config JSON **au moment du lancement**.
Elle ne doit **jamais** être appelée dans `apply_server_patch` (save config) — sinon les valeurs sont baked dans le JSON et ne reflètent plus les .env.

Appelée **uniquement** dans :
- `_do_start()` dans `api.py` (lancement depuis le panel)
- `rotation_start()` dans `api.py` (démarrage roulement)

### 16.5 `_deep_merge` — comportement

```python
_deep_merge(base, override)
# Clés dans override → override gagne (même valeur None)
# Clés dans base mais pas dans override → base sert de fallback
# Listes → override remplace (pas de merge liste)
```

Utilisé dans :
- `load_config()` : garantit que toutes les clés existent même si config ancienne
- `load_config_by_name()` : idem pour les configs non-actives (watchdog, rotation)
- `repair_config()` : rebuild complet depuis default

### 16.6 `run_id` — groupement des sessions

Chaque démarrage du serveur génère un `run_id = uuid.uuid4().hex`.
Toutes les sessions de ce démarrage partagent le même `run_id` dans `SessionResult`.
Permet de grouper les sessions "Race Weekend" (Practice → Qualifying → Race) ensemble.

### 16.7 Watchdog — démarrage Docker

En mode `docker_split`, le watchdog détecte que le container est arrêté en vérifiant `container.status == "running"`.
**Attention** : si `restart: unless-stopped` est configuré sur ace-server dans docker-compose, Docker peut redémarrer le container indépendamment du panel → double lancement possible.
C'est pourquoi `ace-server` doit avoir `restart: "no"` et pourquoi le panel vérifie la politique au démarrage (`_check_docker_restart_policy()`).

### 16.8 Sélecteur serveur — état session

`session["current_server_id"]` est un int (défaut 1).
Si le serveur correspondant n'existe plus ou est désactivé, `_inject_globals()` rebasule sur `servers[0].id`.
Pas de risque de "serveur orphelin" en session.

### 16.9 `ACESERVER_CONTAINER_NAME` — transition multi-serveur

Actuellement : constante globale lue depuis `.env` → pointe vers "ace-server".
En multi-serveur : chaque `Server` a son propre `container_name` en DB.
La transition sera faite dans A3 quand `_get_aceserver_container()` sera per-server.

### 16.10 Rétrocompatibilité — règle d'or

Les utilisateurs existants ont :
- Une DB SQLite avec les anciens schémas
- Un `.env` avec les clés existantes
- Un volume `./aceserver/` avec des fichiers existants

**Toute migration doit** :
1. Être additive (ALTER TABLE ADD COLUMN avec DEFAULT)
2. Fonctionner avec les données existantes (NULL pour les nouvelles colonnes nullable)
3. Être déclarée dans `_migrate_db()` avec whitelist
4. Bumper la version en MINEUR minimum (si schéma change)

---

## 17. PROCÉDURES OPÉRATIONNELLES

### Déployer une modification

```bash
cd /opt/pannel-ac-evo-server
# Modifier les fichiers
docker compose up -d --build panel
# Vérifier les logs
docker compose logs -f panel
```

### Recompiler les traductions

```bash
docker compose exec panel python compile_mo.py
docker compose restart panel   # ou --build si .mo sont dans l'image
```

### Accéder à la DB SQLite

```bash
docker compose exec panel sqlite3 /panel/data/ace_evo.db
```

### Vérifier le state file

```bash
cat ./aceserver/.panel_state.json
```

### Vérifier les modèles en DB

```bash
docker compose exec panel python -c "
from app import create_app
from app.services.database import db
from app.models import Server, CarMeta, TrackMeta, Mod
app = create_app()
with app.app_context():
    print('Servers:', [(s.id, s.name, s.slug, s.tcp_port, s.container_name) for s in Server.query.all()])
    print('CarMeta count:', CarMeta.query.count())
    print('TrackMeta count:', TrackMeta.query.count())
"
```

### Branching strategy

```
main               ← releases stables (pushées publiquement)
feat/multi-server  ← développement multi-serveur (branche actuelle)
```

Merger dans main seulement quand une feature est complète et testée.

### Versioning semver

| Type de changement | Bump |
|---|---|
| Bug fix, CSS, traductions | PATCH (1.7.1 → 1.7.2) |
| Nouvelle feature rétrocompat, migration DB additive | MINOR (1.7.x → 1.8.0) |
| Breaking change, suppression colonnes | MAJOR (1.x.x → 2.0.0) |

Multi-serveur complet = MINOR minimum (nouvelles tables, nouvelles clés .env).

### Checklist avant push/merge dans main

- [ ] VERSION bumped
- [ ] CHANGELOG.md mis à jour
- [ ] `.env.example` synchronisé si nouvelle clé
- [ ] Migrations DB déclarées dans `_migrate_db()`
- [ ] Toutes les nouvelles strings visibles ont une clé i18n dans les 5 langues
- [ ] `.mo` recompilés
- [ ] Testé visuellement (rebuild + navigateur)
- [ ] Pas de `print()` ou code debug
- [ ] Pas de `_LOG_FILE` ou autres constantes sans `server_id`
- [ ] Thread safety respectée pour les données partagées
- [ ] Rétrocompatibilité DB vérifiée

---

*Document généré le 2026-06-20 — Version codebase 1.7.1 — Branche feat/multi-server*
*Prochaine étape : Phase 2 (création container ace-server-2 depuis le panel) — dockerproxy vérifié OK (POST+CONTAINERS)*

---

## 18. TODO — Points en suspens

### Notifications Discord
- [x] **Numéro de serveur dans le titre** — `[Nom du serveur]` préfixé dans le titre de chaque embed. Helper `_srv(title, server_name)` dans `discord_notifier.py`. Footer simplifié (heure seulement).

### Pages publiques pilote
- [x] **Refaire "Mes inscriptions"** — lien navbar limité aux pilotes uniquement. Page restructurée en 3 sections : événements disponibles / inscriptions à venir / historique (passé). Route `pilot_dashboard()` dans `public.py` sépare `upcoming_regs` et `past_regs`.

### Pages à refaire
- [x] **Refaire la page Résultats** — refonte visuelle et UX complète
- [x] **Refaire la page Classement** — refonte visuelle et UX complète

### Documentation
- [ ] **Screenshots pour le README** — faire des captures d'écran de l'état actuel du panel pour illustrer le README (navbar, page serveur, résultats, classement, live...)

### Page Serveur — onglet Status
- [x] **Performances du container** — métriques CPU %, RAM utilisée/limite via API Docker dans l'onglet Status.

### Page Véhicules & Tracks
- [x] **Renommer "Circuits" en "Tracks"** dans la nav et les titres — route `/admin/tracks`, template `tracks.html`, clé i18n ajoutée (5 langues)
- [x] **Retravailler la page Véhicules et Tracks** :
  - Toggle désactiver supprimé complètement (routes `vehicle_toggle` et `circuit_toggle` supprimées)
  - Suppression non implémentée — viendra avec la gestion des mods (Phase 5)

### Navbar — reorganisation
- [x] **Fusionner Résultats + Classement** — dropdown `.admin-nav-dropdown` avec deux sous-items (Résultats → `/results`, Classement → `/leaderboard`). État actif sur les deux endpoints.
- [x] **Renommer "Timing" en "Live"** — desktop + mobile.
- [ ] **Refaire la page Live** (ex-Timing) en page publique :
  - Temps en direct (leaderboard live)
  - Visualisation du tchat en direct (lecture seule — page publique, pas de saisie)

### Page Live — timing secteurs couleur rouge (tour/secteur invalidé)
- [ ] **Trouver le pattern de log ACE EVO pour tour/secteur invalidé**
  - Quand un tour est invalidé (sortie de piste, collision, track limits...), ACE EVO log une ligne spécifique
  - Pour l'identifier : rouler intentionnellement hors piste puis copier la ligne exacte via `docker compose logs ace-server --tail=50`
  - Une fois le pattern connu, ajouter `_RE_LAP_INVALID` dans `live.py` et colorier les secteurs concernés en rouge dans `timing.html`
  - La donnée de coloration devrait être propagée dans la réponse `/api/timing` (champ `invalid_laps` ou flag par secteur)

### Page Live — mémoire de session (persistance au rafraîchissement)
- [x] **Conserver l'historique entre les chargements de page** ✓
  - `timing.html` : cache localStorage par serveur (`timing_lb_{id}`, `timing_chat_{id}`) — affiché instantanément au chargement, mis à jour à chaque poll
  - `live.html` : `loadChatHistory()` appelée au démarrage, pré-remplit `#live-chat-log` depuis `/api/live/chat-history`
  - Leaderboard et events déjà reconstruits depuis les logs à chaque appel → OK au refresh

### Page Live — modification chat
- [x] que les spectateur public ou même connecter puissent envoyer dans le chat des emo icone prés configuré , ultra securisé ✓
  - Endpoint POST `/api/timing/react` : whitelist stricte `{🏁 👍 ❤️ 🔥 💪 ⚡}`, rate-limit 10/min par IP, CSRF requis
  - `timing.html` : boutons emoji sous le chat, feedback visuel (flash violet + message statut)
  - Message envoyé en jeu : `{emoji} [Spectateur]`