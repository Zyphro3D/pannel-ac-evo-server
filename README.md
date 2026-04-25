# AC EVO Server Panel

Interface web pour gérer un serveur dédié **Assetto Corsa EVO** sous Windows, déployable derrière un reverse proxy (Caddy, Nginx…).

## Fonctionnalités

### Gestion du serveur
- Démarrer / arrêter / redémarrer le serveur depuis le navigateur
- Modes **Practice** et **Race Weekend** (Practice + Qualification + Chauffe + Course)
- Sélection du circuit, de la météo, de l'adhérence initiale et des durées par session
- Sélection des véhicules avec **filtres par catégorie** et **plage PI** (slider)
- Gestion de plusieurs fichiers de configuration (créer, dupliquer, supprimer)
- **Auto-restart** watchdog : relance automatique en cas de crash serveur
- Affichage du **nombre de joueurs** en temps réel via l'API HTTP du serveur
- **Logs serveur** accessibles depuis l'interface + logs applicatifs rotatifs dans `logs/app.log`
- Notifications **Discord** : démarrage (mode, circuit, voitures, durées), arrêt, crash

### Gestion des pilotes et événements
- **Inscription des pilotes** : formulaire public avec validation (pseudo in-game, email, mot de passe)
- **Approbation admin** : les pilotes sont `pending` jusqu'à validation manuelle
- **Événements** : création d'épreuves avec circuit, mode, météo, durées, voitures autorisées, places max, mot de passe optionnel
- **Inscriptions** : les pilotes approuvés s'inscrivent aux événements ; les admins confirment/rejettent
- **Entry list automatique** : génération du fichier `entry_list.json` pour le serveur ACE depuis les inscriptions confirmées
- **Rappels email** : envoi automatique X minutes avant le départ (configurable)
- **Emails transactionnels** : confirmation d'inscription, approbation/rejet de compte

### Tableau de bord public
- Statut du serveur en temps réel (circuit, mode, météo, voitures, durées, joueurs)
- Liste des événements à venir avec bouton d'inscription
- Accessible sans connexion

### Sécurité et accès
- Deux niveaux d'accès admin : `admin` (standard) et `superadmin` (ports réseau visibles)
- Comptes pilotes en base de données SQLite avec hash bcrypt
- Headers de sécurité HTTP (X-Frame-Options, CSP, etc.)
- Interface bilingue **FR / EN**

---

## Installation rapide (Windows)

### Prérequis
- **Python 3.11+** installé et dans le PATH
- **Git** installé et dans le PATH
- Fichiers `cars.json`, `events_practice.json` et `events_race_weekend.json` générés par le **ServerLauncher** officiel d'Assetto Corsa EVO

### Étape 1 — Cloner le dépôt

```bat
git clone https://github.com/Zyphro3D/pannel-ac-evo-server.git
cd pannel-ac-evo-server
```

### Étape 2 — Installer

Double-cliquer sur **`install.bat`** ou lancer depuis le terminal :

```bat
install.bat
```

Le script :
1. Vérifie que Python est disponible
2. Crée l'environnement virtuel `.venv`
3. Installe les dépendances (`pip install -r requirements.txt`)
4. Pose quelques questions pour générer le fichier `.env` :
   - Chemin d'installation ACE EVO Server
   - Chemin du dossier de configurations
   - Mots de passe `admin` et `superadmin`
   - URL publique du panel

### Étape 3 — Démarrer

```bat
start.bat
```

Le panel est accessible sur **http://localhost:4300** (ou le port défini dans `.env`).

---

## Mise à jour

```bat
update.bat
```

Le script :
1. Sauvegarde le `.env` local
2. Exécute `git pull`
3. Restaure le `.env` (jamais écrasé)
4. Met à jour les dépendances pip
5. Recompile les traductions
6. Affiche la version avant/après

---

## Configuration `.env`

| Variable | Description | Défaut |
|---|---|---|
| `SECRET_KEY` | Clé secrète Flask — **à changer en production** | — |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Compte admin (accès standard) | `admin` / `admin` |
| `SUPERADMIN_USERNAME` / `SUPERADMIN_PASSWORD` | Compte superadmin (accès complet) | `superadmin` / `superadmin` |
| `ACESERVER_DIR` | Dossier d'installation du serveur ACE EVO | `C:\aceserver` |
| `CONFIGS_DIR` | Dossier contenant vos fichiers de configuration `.json` | — |
| `ACESERVER_HTTP_PORT` | Port HTTP de l'API du jeu | `8080` |
| `SERVER_SHOW_CONSOLE` | Afficher la fenêtre console du serveur | `false` |
| `DATABASE_URL` | URL SQLAlchemy (SQLite par défaut) | `sqlite:///ace_evo.db` |
| `PANEL_URL` | URL publique du panel (pour les liens dans les emails) | `http://localhost:4300` |
| `DISCORD_WEBHOOK_URL` | Webhook Discord principal (démarrage / arrêt / crash serveur) | — |
| `DISCORD_PILOTS_WEBHOOK_URL` | Webhook Discord pilotes (inscriptions, rappels événements) — si vide, utilise le webhook principal | — |
| `SESSION_COOKIE_SECURE` | `true` si HTTPS (reverse proxy), `false` en HTTP local | `true` |
| `MAIL_SERVER` | Serveur SMTP (ex: `smtp.gmail.com`) | — |
| `MAIL_PORT` | Port SMTP | `587` |
| `MAIL_USE_TLS` | Activer STARTTLS | `true` |
| `MAIL_USERNAME` | Identifiant SMTP | — |
| `MAIL_PASSWORD` | Mot de passe SMTP | — |
| `MAIL_FROM` | Adresse expéditeur | — |
| `MAIL_ADMIN` | Adresse(s) admin pour les notifications (plusieurs adresses séparées par des virgules) | — |

> Les emails sont optionnels. Si `MAIL_SERVER` est vide, aucun email n'est envoyé.

Générer une `SECRET_KEY` sécurisée :
```bat
.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"
```

## Soutenir le projet

Si ce projet vous est utile et que vous souhaitez soutenir son développement :

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/zyphro3d)

## Licence

[CC BY-NC 4.0](LICENSE) — usage personnel et communautaire libre, usage commercial interdit.
