<p align="center">
  <img src="docs/banner.png" alt="AC EVO Server Panel" width="600">
</p>

<h1 align="center">AC EVO Server Panel</h1>

<p align="center">
  Interface web pour gérer un serveur dédié Assetto Corsa EVO.<br>
  Disponible en deux modes : <strong>Windows natif</strong> ou <strong>Docker (Linux)</strong>.
</p>

<p align="center">
  <a href="#-windows">🖥️ Windows</a> •
  <a href="#-docker-linux">🐧 Docker</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#mise-à-jour">Mise à jour</a> •
  <a href="#changelog">Changelog</a> •
  <a href="https://ko-fi.com/zyphro3d">☕ Soutenir</a>
</p>

---

## Choisir votre installation

| | 🖥️ Windows | 🐧 Docker (Linux) |
|---|---|---|
| **OS** | Windows 10/11 ou Windows Server | Debian, Ubuntu, tout Linux avec Docker |
| **Prérequis** | Python 3.11+, Git | Docker + Docker Compose |
| **Serveur ACE** | Installé nativement via Steam/SteamCMD | Téléchargé via SteamCMD, lancé via Wine |
| **Démarrage** | `start.bat` | `docker compose up -d` |

---

## Aperçu

### Dashboard public

Statut du serveur en temps réel, événement en cours et prochains à venir. Accessible sans compte.

<p align="center">
  <img src="docs/screenshot-dashboard.png" alt="Dashboard public" width="700">
</p>

### Gestion du serveur

Démarrage, arrêt, restart depuis le navigateur. Circuit, météo, voitures avec filtres catégorie et plage PI, ballast et restrictor par voiture. Un seul bouton « Sauvegarder tout » en bas de page.

<p align="center">
  <img src="docs/screenshot-server.png" alt="Gestion serveur" width="700">
</p>

### Calendrier des événements

Vue mensuelle avec chips colorés. Clic sur un jour → vue horaire 00h–23h. Clic sur un créneau vide → formulaire de création pré-rempli. Lancement automatique du serveur à l'heure prévue, passage en « terminé » 1h après la fin des sessions.

<p align="center">
  <img src="docs/screenshot-events.png" alt="Calendrier des événements" width="700">
</p>

### Formulaire de création d'événement

Circuit, mode, météo, durées de session, sélection des voitures avec ballast/restrictor, places max, mot de passe optionnel.

<p align="center">
  <img src="docs/screenshot-event-form.png" alt="Formulaire événement" width="700">
</p>

---

## Fonctionnalités

**Serveur** — Modes Practice et Race Weekend (Practice + Qualif + Chauffe + Course). Auto-restart watchdog en cas de crash. Nombre de joueurs en temps réel via l'API HTTP du jeu. Logs serveur consultables depuis l'interface. Notifications Discord (démarrage, arrêt, crash).

**Pilotes** — Inscription publique avec validation. Approbation manuelle par l'admin. Inscriptions aux événements avec confirmation admin. Génération automatique de l'`entry_list.json` depuis les inscrits confirmés. Emails transactionnels (approbation, rejet, rappel avant départ).

**Événements** — Publics ou privés, brouillon/publié/terminé. Lancement auto du serveur à l'heure prévue. Rappels email configurables (X minutes avant le départ). Fin automatique après la dernière session + 1h de grâce.

**Calendrier** — Vue mensuelle avec chips colorés (rouge = privé, bleu = public ; brouillons désaturés, terminés grisés). Clic sur un jour → vue horaire détaillée avec blocs d'événements. Clic sur un créneau vide → formulaire de création pré-rempli à cette heure.

**Interface** — Multilingue (FR / EN / ES / DE / IT). Statut serveur rafraîchi toutes les 5s dans la navbar. Vue calendrier ou liste mémorisée entre les visites. Fuseau horaire configurable (`PANEL_TIMEZONE`) appliqué à la saisie et à l'affichage.

**Sécurité** — CSRF sur tous les formulaires. Rate limiting (login, inscription, reset password). Tokens de réinitialisation stockés en SHA-256. Headers HTTP durcis (CSP, HSTS, X-Frame-Options). Comparaison des identifiants en temps constant (anti timing-attack). Deux niveaux admin : `admin` et `superadmin`.

---

## 🖥️ Windows

### Prérequis

- **Python 3.11+** dans le PATH
- **Git** dans le PATH
- Les fichiers `cars.json`, `events_practice.json` et `events_race_weekend.json` générés par le **ServerLauncher officiel** d'Assetto Corsa EVO

### Étapes

```bat
git clone https://github.com/Zyphro3D/pannel-ac-evo-server.git
cd pannel-ac-evo-server
```

Lancer **`install.bat`** (double-clic ou terminal) — il pose toutes les questions et génère le `.env` automatiquement :

- Chemin d'installation du serveur ACE EVO
- Chemin du dossier de configurations
- Mots de passe admin et superadmin
- URL publique du panel

Ou copier manuellement le fichier d'exemple :

```bat
copy .env.example .env
```

Puis démarrer :

```bat
start.bat
```

Le panel est accessible sur `http://localhost:4300`.

---

## 🐧 Docker (Linux)

Le panel et le serveur ACE EVO tournent dans un seul conteneur (Python 3 + Wine).  
Testé sur **Debian 13**. Docker et Docker Compose requis.

### 1. Télécharger le serveur ACE EVO via SteamCMD

Le paquet `steamcmd` n'existe pas sous Debian 13 — installation manuelle :

```bash
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install -y lib32gcc-s1

mkdir -p /opt/steamcmd && cd /opt/steamcmd
curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz | tar xz

/opt/steamcmd/steamcmd.sh \
  +@sSteamCmdForcePlatformType windows \
  +login TON_COMPTE_STEAM \
  +force_install_dir /opt/aceserver \
  +app_update 4564210 validate \
  +quit
```

> SteamCMD télécharge la version **Windows** du serveur (`.exe`), exécutée via Wine dans le conteneur.

### 2. Cloner le panel et copier les fichiers serveur

```bash
git clone https://github.com/Zyphro3D/pannel-ac-evo-server.git /opt/pannel-ac-evo-server

mkdir -p /opt/pannel-ac-evo-server/docker/aceserver/configs
cp -r /opt/aceserver/* /opt/pannel-ac-evo-server/docker/aceserver/
```

### 3. Configurer

```bash
cd /opt/pannel-ac-evo-server/docker
cp .env.example .env
nano .env
```

Variables minimales à renseigner :

```env
SECRET_KEY=           # générer : python3 -c "import secrets; print(secrets.token_hex(32))"
ADMIN_PASSWORD=       # mot de passe admin
SUPERADMIN_PASSWORD=  # mot de passe superadmin
PANEL_URL=            # ex : https://votre-domaine.fr ou http://IP_VM:4300
SESSION_COOKIE_SECURE=true   # false si HTTP direct (sans reverse proxy)
```

### 4. Lancer

```bash
docker compose up -d
```

Premier démarrage : ~5 min (build de l'image + initialisation Wine au premier lancement du serveur).

```bash
docker compose logs -f   # suivre les logs
```

Le panel est accessible sur `http://IP_VM:4300`.

### Variables Docker (référence)

Les variables de chemins et de mode sont déjà fixées dans le Dockerfile. Ne les ajoutez pas dans votre `.env`.

| Variable | Valeur dans le conteneur |
|---|---|
| `DEPLOY_MODE` | `docker` (automatique) |
| `ACESERVER_DIR` | `/aceserver` |
| `CONFIGS_DIR` | `/aceserver/configs` |
| `DATABASE_URL` | `sqlite:////panel/data/ace_evo.db` |

> **Crédits Wine** : approche Docker inspirée de [VandaLpr/acevo-docker-server](https://github.com/VandaLpr/acevo-docker-server).

---

## Configuration

Le fichier `.env` contient toute la configuration. Référence complète des variables :

### Général

| Variable | Description | Défaut |
|---|---|---|
| `SECRET_KEY` | Clé secrète Flask — **à changer en production** | — |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Compte admin standard | `admin` / `admin` |
| `SUPERADMIN_USERNAME` / `SUPERADMIN_PASSWORD` | Compte superadmin (ports réseau visibles) | `superadmin` / `superadmin` |
| `PANEL_URL` | URL publique du panel (utilisée dans les emails) | `http://localhost:4300` |
| `PANEL_TIMEZONE` | Fuseau horaire pour la saisie et l'affichage des dates | `Europe/Paris` |
| `DEFAULT_LOCALE` | Langue par défaut (`fr` / `en` / `es` / `de` / `it`) | `fr` |
| `SESSION_COOKIE_SECURE` | `true` derrière HTTPS, `false` en HTTP local | `true` |

### Serveur ACE *(Windows uniquement)*

| Variable | Description | Défaut |
|---|---|---|
| `ACESERVER_DIR` | Dossier d'installation du serveur ACE EVO | `C:\aceserver` |
| `CONFIGS_DIR` | Dossier contenant vos `.json` de configuration | — |
| `ACESERVER_HTTP_PORT` | Port HTTP de l'API du jeu | `8080` |
| `SERVER_SHOW_CONSOLE` | Afficher la fenêtre console du serveur | `false` |
| `DATABASE_URL` | URL SQLAlchemy | `sqlite:///ace_evo.db` |

### Discord

| Variable | Description |
|---|---|
| `DISCORD_WEBHOOK_URL` | Webhook principal (démarrage / arrêt / crash) |
| `DISCORD_PILOTS_WEBHOOK_URL` | Webhook pilotes (inscriptions, rappels) — fallback sur le principal si vide |
| `DISCORD_INVITE_URL` | Lien d'invitation affiché dans la navbar — laisser vide pour masquer |

### Emails *(optionnel)*

| Variable | Description | Défaut |
|---|---|---|
| `MAIL_SERVER` | Serveur SMTP (ex : `smtp.gmail.com`) — laisser vide pour désactiver | — |
| `MAIL_PORT` | Port SMTP | `587` |
| `MAIL_USE_TLS` | STARTTLS | `true` |
| `MAIL_USERNAME` | Identifiant SMTP | — |
| `MAIL_PASSWORD` | Mot de passe SMTP | — |
| `MAIL_FROM` | Adresse expéditeur | — |
| `MAIL_ADMIN` | Adresse(s) admin pour les notifications (virgule pour séparer) | — |

Générer une `SECRET_KEY` sécurisée :

```bash
# Windows
.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"

# Linux / Docker
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Mise à jour

**Windows :**

```bat
update.bat
```

Fait un `git pull`, met à jour les dépendances pip et recompile les traductions. Le `.env` et la base de données ne sont jamais modifiés. Les migrations de base s'appliquent automatiquement au démarrage.

**Docker :**

```bash
cd /opt/pannel-ac-evo-server
git pull
docker compose up -d --build
```

---

## Changelog

### v1.2.0 — 29/04/2026

**Support Docker (Linux)**
- Déploiement via Docker avec Wine pour exécuter le serveur Windows sur Linux
- Image basée sur `ich777/winehq-baseimage` (Wine stable, Debian)
- Initialisation Wine en arrière-plan au démarrage du panel
- Configuration automatique (`WINEDLLOVERRIDES`) pour éviter les blocages Wine en mode headless
- Volume persistant pour le prefix Wine (pas de réinitialisation au restart)
- Configuration par défaut avec Brands Hatch GP pré-remplie (évite le crash "gamemode not found" au premier lancement)
- Création automatique de `default.json` au premier démarrage si aucune config n'existe

**Nouveautés**
- Calendrier des événements : vue mensuelle avec chips colorés (privé/public/statut)
- Vue journée avec timeline horaire (00h–23h), clic sur un créneau → création pré-remplie
- Ballast et Restrictor par voiture dans les événements et le serveur
- Lancement automatique = publication automatique de l'événement
- Fin automatique des événements 1h après la durée prévue
- Fuseau horaire appliqué à la saisie des dates
- Bouton Discord intégré dans la navbar
- Page serveur en défilement unique avec un seul bouton « Sauvegarder tout »
- `update.bat` pour la mise à jour sans toucher au `.env` ni à la base

**Corrections**
- Checkboxes « Événement public » et « Lancement automatique » ignorées à l'édition
- Slider PI dans le formulaire d'événement non visible et sans auto-sélection
- Statut serveur affichait le nom du fichier de config au lieu de « En ligne / Hors ligne »
- Badges de statut en anglais dans les listes d'événements

---

### v1.1.0

**Nouveautés**
- Protection CSRF sur tous les formulaires HTML (Flask-WTF)
- Rate limiting sur le login, l'inscription et le reset password (Flask-Limiter)
- Tokens de réinitialisation de mot de passe stockés en SHA-256
- Headers de sécurité HTTP durcis (CSP, HSTS, X-Frame-Options…)
- Support multilingue FR / EN / ES / DE / IT
- Notifications Discord pilotes sur webhook séparé
- Bannière Discord configurable (`DISCORD_INVITE_URL`)

---

## Soutenir le projet

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/zyphro3d)

---

## Licence

[CC BY-NC 4.0](LICENSE) — Usage personnel et communautaire libre, usage commercial interdit.
