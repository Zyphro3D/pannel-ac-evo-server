<p align="center">
  <img src="docs/banner.png" alt="AC EVO Server Panel" width="600">
</p>

<h1 align="center">AC EVO Server Panel</h1>

<p align="center">
  Interface web pour gérer un serveur dédié Assetto Corsa EVO.<br>
  <strong>Déploiement Docker (Linux) — panel et serveur dans des containers séparés.</strong>
</p>

<p align="center">
  <a href="#-installation-docker-linux">🐧 Installation</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#mise-à-jour">Mise à jour</a> •
  <a href="#changelog">Changelog</a> •
  <a href="https://ko-fi.com/zyphro3d">☕ Soutenir</a>
</p>

---

## Aperçu

### Dashboard admin

Statut du serveur en temps réel, événement en cours et prochains à venir. Accessible sans compte.

<p align="center">
  <img src="docs/screenshot-dashboard.png" alt="Dashboard" width="700">
</p>

### Gestion du serveur

Démarrage, arrêt, restart depuis le navigateur. Circuit, météo, voitures avec filtres catégorie et plage PI, ballast et restrictor par voiture.

<p align="center">
  <img src="docs/screenshot-server.png" alt="Gestion serveur" width="700">
</p>

### Calendrier des événements

Vue mensuelle avec chips colorés. Clic sur un créneau vide → formulaire pré-rempli. Lancement automatique du serveur à l'heure prévue.

<p align="center">
  <img src="docs/screenshot-events.png" alt="Calendrier" width="700">
</p>

---

## Fonctionnalités

**Serveur** — Modes Practice et Race Weekend. Auto-restart watchdog. Nombre de joueurs en temps réel. Logs consultables depuis l'interface. Notifications Discord (démarrage, arrêt, crash).

**Résultats** — Réception automatique des résultats de fin de session (webhook). Classement avec meilleurs tours, secteurs colorés (meilleur session en violet, meilleur perso en vert), gap au leader. Historique complet avec détail tour par tour.

**Pilotes** — Inscription publique avec validation manuelle. Emails transactionnels (approbation, rejet, rappel). Génération automatique de l'`entry_list.json`.

**Événements** — Publics ou privés, brouillon/publié/terminé. Lancement auto du serveur à l'heure prévue. Fin automatique après la dernière session + 1h de grâce.

**Interface** — Multilingue (FR / EN / ES / DE / IT). Statut serveur rafraîchi toutes les 5s. Fuseau horaire configurable.

**Sécurité** — CSRF, rate limiting, HSTS, CSP, X-Frame-Options. Deux niveaux admin : `admin` et `superadmin`.

---

## 🐧 Installation Docker (Linux)

**Prérequis** : Debian/Ubuntu (ou tout Linux), Docker + Docker Compose, compte Steam.

### 1. Télécharger le serveur ACE EVO via SteamCMD

```bash
# Installation SteamCMD sur Debian 13
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

Variables minimales :

```env
SECRET_KEY=           # python3 -c "import secrets; print(secrets.token_hex(32))"
ADMIN_PASSWORD=
SUPERADMIN_PASSWORD=
PANEL_URL=            # https://votre-domaine.fr ou http://IP:4300
SESSION_COOKIE_SECURE=true   # false si HTTP sans reverse proxy
```

### 4. Lancer

```bash
docker compose up -d
```

Deux containers démarrent :
- **`ace-panel`** — Flask (Python uniquement), port 4300
- **`ace-server`** — Wine + AssettoCorsaEVOServer.exe, ports 9700 + 8080

Premier démarrage : ~5 min (build des images + initialisation Wine).

```bash
docker compose logs -f          # suivre tous les logs
docker compose logs -f panel    # panel uniquement
docker compose logs -f aceserver # serveur de jeu uniquement
```

Le panel est accessible sur `http://IP:4300`.

### Architecture

```
docker compose
├── ace-panel    → Flask uniquement (port 4300) — rebuild rapide sans toucher au jeu
└── ace-server   → Wine + ACE EVO exe (ports 9700, 8080) — cycle de vie géré par le panel
         ↑
    Volume partagé /aceserver (configs, résultats)
    Docker socket (le panel démarre/arrête ace-server)
```

### Variables Docker (référence)

Déjà fixées dans `Dockerfile.panel` — ne pas les ajouter dans `.env` :

| Variable | Valeur |
|---|---|
| `DEPLOY_MODE` | `docker_split` |
| `ACESERVER_DIR` | `/aceserver` |
| `CONFIGS_DIR` | `/aceserver/configs` |
| `DATABASE_URL` | `sqlite:////panel/data/ace_evo.db` |
| `ACESERVER_CONTAINER_NAME` | `ace-server` |

> **Crédits Wine** : approche Docker inspirée de [VandaLpr/acevo-docker-server](https://github.com/VandaLpr/acevo-docker-server).

---

## Configuration

Référence complète des variables `.env` :

### Général

| Variable | Description | Défaut |
|---|---|---|
| `SECRET_KEY` | Clé secrète Flask — **obligatoire en production** | — |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Compte admin | `admin` / `admin` |
| `SUPERADMIN_USERNAME` / `SUPERADMIN_PASSWORD` | Compte superadmin | `superadmin` / `superadmin` |
| `PANEL_URL` | URL publique (utilisée dans les emails) | `http://localhost:4300` |
| `PANEL_TIMEZONE` | Fuseau horaire | `Europe/Paris` |
| `DEFAULT_LOCALE` | Langue par défaut (`fr` / `en` / `es` / `de` / `it`) | `fr` |
| `SESSION_COOKIE_SECURE` | `true` derrière HTTPS, `false` en HTTP | `true` |
| `ACESERVER_HTTP_PORT` | Port HTTP de l'API du serveur de jeu | `8080` |

### Discord

| Variable | Description |
|---|---|
| `DISCORD_WEBHOOK_URL` | Webhook principal (démarrage / arrêt / crash) |
| `DISCORD_PILOTS_WEBHOOK_URL` | Webhook pilotes — fallback sur le principal si vide |
| `DISCORD_INVITE_URL` | Lien d'invitation dans la navbar — vide pour masquer |

### Emails *(optionnel)*

| Variable | Description | Défaut |
|---|---|---|
| `MAIL_SERVER` | Serveur SMTP — vide pour désactiver | — |
| `MAIL_PORT` | Port SMTP | `587` |
| `MAIL_USE_TLS` | STARTTLS | `true` |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | Identifiants SMTP | — |
| `MAIL_FROM` | Adresse expéditeur | — |
| `MAIL_ADMIN` | Adresse(s) admin pour les notifications (virgule) | — |

---

## Mise à jour

```bash
cd /opt/pannel-ac-evo-server
git pull

# Rebuild uniquement le panel (sans toucher au serveur de jeu)
docker compose build panel
docker compose up -d panel

# Ou rebuild complet si le Dockerfile.aceserver a changé
docker compose up -d --build
```

Le `.env` et la base de données ne sont jamais modifiés. Les migrations s'appliquent automatiquement au démarrage.

---

## Changelog

### v1.3.0 — 30/04/2026

**Architecture Docker split (panel ↔ serveur séparés)**
- `Dockerfile.panel` — image Python slim, Flask uniquement, sans Wine
- `Dockerfile.aceserver` — image Wine + ACE EVO exe, sans Flask
- Le panel contrôle `ace-server` via Docker socket (start / stop / logs / watchdog)
- Rebuild du panel en ~30 secondes sans interrompre le serveur de jeu
- Volume partagé `/aceserver` pour les configs et résultats

**Résultats de session — UI complète**
- Gap au leader pour chaque pilote dans le classement
- Color-coding des secteurs : violet = meilleur secteur de la session, vert = meilleur secteur perso
- Interprétation correcte des flags de tour ACE EVO (`flags==2` = tour propre officiel)
- En-tête de session : durée, meilleur tour global, serveur, date
- Détail tour par tour avec icône ♛ (meilleur session) et ★ (meilleur perso)
- Indicateurs de tours notés (⚑) et invalides/out-laps (⚠)
- Consistance pilote (écart-type des tours propres)

**Corrections**
- Bouton "Résultats" dans la navbar : suppression du `div.navbar-center` sans style (boîte blanche flottante)
- `_ensure_race_weekend_file` réintégrée dans process_manager (regression introduite lors du refactoring)
- Lock file Xvfb `/tmp/.X99-lock` nettoyé au démarrage du container aceserver

---

### v1.2.0 — 29/04/2026

**Support Docker (Linux)**
- Image `ich777/winehq-baseimage`, Wine stable, Debian
- Initialisation Wine en arrière-plan, volume prefix persistant
- Config par défaut Brands Hatch GP au premier démarrage

**Nouveautés**
- Réception des résultats de session via webhook (`POST /api/results/ingest`)
- Page résultats publique avec classement, podium, détail tours dépliable
- Widget "Derniers résultats" sur le dashboard admin
- Calendrier des événements mensuel avec timeline horaire
- Ballast et Restrictor par voiture, lancement automatique, fin automatique

---

### v1.1.0

- CSRF, rate limiting, headers sécurité, tokens SHA-256
- Multilingue FR / EN / ES / DE / IT
- Discord pilotes webhook séparé

---

## Mode alternatif — Windows natif *(legacy, non maintenu)*

> ⚠️ Le support Windows n'est plus activement développé. Il reste fonctionnel mais ne bénéficie pas des nouvelles fonctionnalités (architecture split, UI résultats enrichie). Utilisez Docker si possible.

**Prérequis** : Python 3.11+, Git, fichiers `cars.json` / `events_*.json` du ServerLauncher officiel.

```bat
git clone https://github.com/Zyphro3D/pannel-ac-evo-server.git
cd pannel-ac-evo-server
install.bat    :: pose toutes les questions et génère le .env
start.bat      :: démarre le panel
update.bat     :: git pull + pip + traductions
```

Variables spécifiques Windows dans `.env` :

| Variable | Description |
|---|---|
| `ACESERVER_DIR` | Dossier d'installation ACE EVO (ex: `C:\aceserver`) |
| `CONFIGS_DIR` | Dossier des fichiers de config JSON |
| `DEPLOY_MODE` | `native` |

---

## Soutenir le projet

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/zyphro3d)

---

## Licence

[CC BY-NC 4.0](LICENSE) — Usage personnel et communautaire libre, usage commercial interdit.
