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

### Pages publiques

**Accueil** — Événements à venir, session en cours avec joueurs connectés et uptime, classement des 4 dernières sessions.

<p align="center">
  <img src="app/static/screenshots/01_accueil.png" alt="Accueil" width="700">
</p>
<p align="center">
  <img src="app/static/screenshots/01b_accueil_bas.png" alt="Accueil — bas de page" width="700">
</p>

**Résultats** — Historique des sessions groupées par run (Race Weekend ou Practice). Badges PRACTICE / QUALIFYING / WARMUP / RACE. Classement avec drapeaux nationaux, meilleurs tours et secteurs color-codés.

<p align="center">
  <img src="app/static/screenshots/02_resultats.png" alt="Résultats" width="700">
</p>

**Classement global** — Leaderboard de la saison par voiture : meilleur tour, nombre de sessions, dernière participation.

<p align="center">
  <img src="app/static/screenshots/03_classement.png" alt="Classement" width="700">
</p>

**Timing en direct** — Classement live mis à jour toutes les 15 secondes : position, pilote, voiture, meilleur tour et écart au leader.

<p align="center">
  <img src="app/static/screenshots/04_timing.png" alt="Timing en direct" width="700">
</p>

**Connexion / Inscription** — Authentification pilote et formulaire d'inscription (validation manuelle par l'admin).

<p align="center">
  <img src="app/static/screenshots/05_login.png" alt="Connexion" width="700">
</p>
<p align="center">
  <img src="app/static/screenshots/06_inscription.png" alt="Inscription" width="700">
</p>

---

### Interface admin

**Dashboard** — Vue synthétique : statut serveur, événement en cours, logs récents.

<p align="center">
  <img src="app/static/screenshots/07_dashboard.png" alt="Dashboard admin" width="700">
</p>

**Serveur — Statut** — Démarrage, arrêt, restart. Statut en temps réel, joueurs connectés, logs en direct.

<p align="center">
  <img src="app/static/screenshots/08_serveur_status.png" alt="Serveur statut" width="700">
</p>

**Serveur — Configuration** — Sélection du circuit, météo, durées de session (Practice / Qualifying / Warmup / Race). Liste des voitures avec filtres par catégorie et plage PI, ballast et restrictor par voiture.

<p align="center">
  <img src="app/static/screenshots/09_serveur_config.png" alt="Serveur config" width="700">
</p>

**Serveur — Rotation** — File d'attente de configs avec glisser-déposer pour réordonner. Option cycle (retour au premier après le dernier). Suivi en temps réel : config active en surbrillance, config suivante.

<p align="center">
  <img src="app/static/screenshots/10_serveur_rotation.png" alt="Rotation de configs" width="700">
</p>

**Serveur — Événements** — Déclenchement des sessions liées aux événements planifiés.

<p align="center">
  <img src="app/static/screenshots/11_serveur_events.png" alt="Serveur événements" width="700">
</p>

**Pilotes** — Liste des pilotes inscrits avec statut (en attente / approuvé / rejeté). Actions d'approbation, rejet, email. Génération de l'`entry_list.json`.

<p align="center">
  <img src="app/static/screenshots/12_pilotes.png" alt="Pilotes" width="700">
</p>

**Événements** — Calendrier mensuel avec chips colorés. Formulaire de création/édition : circuit, mode, météo, voitures, durées. Import depuis un fichier de config existant pour pré-remplir le formulaire.

<p align="center">
  <img src="app/static/screenshots/13_evenements.png" alt="Événements" width="700">
</p>

**Live Admin** — Contrôle de la session en cours : avancer dans la rotation, consulter les logs en temps réel.

<p align="center">
  <img src="app/static/screenshots/14_live_admin.png" alt="Live admin" width="700">
</p>

**Paramètres** — Configuration du panel depuis l'interface : clés API, Discord, email, sécurité. Gestion des comptes admin.

<p align="center">
  <img src="app/static/screenshots/15_parametres.png" alt="Paramètres" width="700">
</p>

---

## Fonctionnalités

**Serveur** — Modes Practice et Race Weekend. Auto-restart watchdog. Joueurs en temps réel. Logs consultables depuis l'interface. Notifications Discord (démarrage, arrêt, crash, roulement).

**Roulement de configs** — File d'attente avec glisser-déposer, option cycle. Déclenchement via webhook de fin de session. Avancement automatique (Practice → suivant ; Race Weekend → après la race). Notifications Discord à chaque changement.

**Timing live** — Classement en temps réel via l'API TCP du serveur. Mis à jour toutes les 15 secondes. Accessible publiquement.

**Leaderboard** — Classement global de la saison par voiture, calculé à partir de tous les résultats importés.

**Résultats** — Import automatique via webhook en fin de session. Classement avec drapeaux nationaux, meilleurs tours, secteurs color-codés (violet = meilleur session, vert = meilleur perso), gap au leader, consistance pilote, détail tour par tour dépliable. Mode Race : temps total, meilleur tour individuel (badge FL), gap en tours, grille de départ.

**Pilotes** — Inscription publique avec validation manuelle. Emails transactionnels (approbation, rejet, rappel). Génération automatique de l'`entry_list.json`.

**Événements** — Publics ou privés, brouillon/publié/terminé. Lancement auto du serveur à l'heure prévue. Fin automatique après la dernière session + 1h de grâce. Import depuis un fichier de config existant.

**Paramètres** — Toutes les variables `.env` éditables depuis l'interface sans accès SSH. Gestion des comptes admin (création, mot de passe, suppression).

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

mkdir -p /opt/pannel-ac-evo-server/aceserver/configs
cp -r /opt/aceserver/* /opt/pannel-ac-evo-server/aceserver/
```

> Les fichiers résultats générés par le jeu (`result*.json`) tombent dans `aceserver/results/` — ce dossier est ignoré par git.

### 3. Configurer

```bash
cd /opt/pannel-ac-evo-server
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

### 4. Builder et lancer

```bash
docker compose up -d --build
```

Deux containers sont construits puis démarrent :
- **`ace-panel`** — Flask (Python uniquement), port 4300
- **`ace-server`** — Wine + AssettoCorsaEVOServer.exe, ports 9700 + 8080

Premier démarrage : ~5 min (build des images + initialisation Wine).

```bash
docker compose logs -f          # suivre tous les logs
docker compose logs -f panel    # panel uniquement
docker compose logs -f aceserver # serveur de jeu uniquement
```

Le panel est accessible sur `http://IP:4300`.

### 5. Ouvrir les ports (accès depuis internet)

Configurez une redirection de ports sur votre box/routeur vers l'IP locale de votre serveur.

| Port | Protocole | Usage |
|---|---|---|
| `9700` | UDP + TCP | Connexion des joueurs (serveur de jeu ACE EVO) |
| `8081` | TCP | Enregistrement auprès de Kunos (liste publique des serveurs) |
| `4300` | TCP | Interface web du panel — HTTP direct |
| `443` | TCP | Interface web du panel — HTTPS (Let's Encrypt ou reverse proxy) |

> Le port `8080` (API interne ACE EVO) **ne doit pas être exposé** — il est utilisé uniquement en local entre les deux containers.

### 6. Accès HTTPS (optionnel)

**Mode 1 — HTTP direct** (défaut, aucune config supplémentaire)
```
http://IP:4300
```

**Mode 2 — HTTPS intégré via Let's Encrypt**

```bash
sudo apt install certbot
sudo certbot certonly --standalone -d votre-domaine.fr
```

Dans `.env` :
```env
PANEL_PORT=443
SSL_CERTFILE=/etc/letsencrypt/live/votre-domaine.fr/fullchain.pem
SSL_KEYFILE=/etc/letsencrypt/live/votre-domaine.fr/privkey.pem
SESSION_COOKIE_SECURE=true
```

Dans `docker-compose.yml`, décommentez la ligne :
```yaml
- /etc/letsencrypt:/etc/letsencrypt:ro
```

Après chaque renouvellement du certificat :
```bash
docker compose restart panel
```

**Mode 3 — Reverse proxy (Nginx, Caddy…)**

Laissez le panel sur HTTP port 4300 et gérez le SSL côté reverse proxy. Assurez-vous que `SESSION_COOKIE_SECURE=true` est défini dans `.env`.

### Architecture

```
docker compose
├── ace-panel    → Flask uniquement (port 4300) — rebuild rapide sans toucher au jeu
└── ace-server   → Wine + ACE EVO exe (ports 9700, 8080) — cycle de vie géré par le panel
         ↑
    Volume partagé ./aceserver → /aceserver (configs, résultats)
    Docker socket (le panel démarre/arrête ace-server)
```

**Structure du dossier `aceserver/` :**
```
aceserver/
├── AssettoCorsaEVOServer.exe   ← installé via SteamCMD (non versionné)
├── cars.json                   ← liste des voitures disponibles
├── events_practice.json        ← modèles de sessions practice
├── events_race_weekend.json    ← modèles de sessions race weekend
├── configs/                    ← fichiers de config JSON — versionnés
│   └── default.json
└── results/                    ← résultats de session — non versionnés
    └── result*.json
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
| `SESSION_COOKIE_SECURE` | `true` derrière HTTPS, `false` en HTTP direct | `true` |
| `PANEL_PORT` | Port d'écoute du panel | `4300` |
| `ACESERVER_HTTP_PORT` | Port HTTP de l'API du serveur de jeu | `8080` |

### HTTPS / SSL *(optionnel)*

| Variable | Description |
|---|---|
| `SSL_CERTFILE` | Chemin vers le certificat (ex: `/etc/letsencrypt/live/domain/fullchain.pem`) |
| `SSL_KEYFILE` | Chemin vers la clé privée (ex: `/etc/letsencrypt/live/domain/privkey.pem`) |

> Si les deux variables sont renseignées, le panel démarre en HTTPS via gunicorn. Sinon, il utilise waitress en HTTP.

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

Le `.env` et la base de données ne sont jamais modifiés par une mise à jour. Les migrations de schéma s'appliquent automatiquement au démarrage.

---

## Changelog

Voir [CHANGELOG.md](CHANGELOG.md) pour l'historique complet des versions.

---

## Mode alternatif — Windows natif *(legacy, non maintenu)*

> ⚠️ Le support Windows n'est plus activement développé. Il reste fonctionnel mais ne bénéficie pas des nouvelles fonctionnalités. Utilisez Docker si possible.

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
