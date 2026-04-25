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
| `DISCORD_WEBHOOK_URL` | URL webhook Discord (laisser vide pour désactiver) | — |
| `SESSION_COOKIE_SECURE` | `true` si HTTPS (Caddy/Nginx), `false` en HTTP local | `true` |
| `MAIL_SERVER` | Serveur SMTP (ex: `smtp.gmail.com`) | — |
| `MAIL_PORT` | Port SMTP | `587` |
| `MAIL_USE_TLS` | Activer STARTTLS | `true` |
| `MAIL_USERNAME` | Identifiant SMTP | — |
| `MAIL_PASSWORD` | Mot de passe SMTP | — |
| `MAIL_FROM` | Adresse expéditeur | — |
| `MAIL_ADMIN` | Adresse de l'administrateur (notifications internes) | — |

> Les emails sont optionnels. Si `MAIL_SERVER` est vide, aucun email n'est envoyé.

Générer une `SECRET_KEY` sécurisée :
```bat
.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Structure du projet

```
app/
  routes/
    auth.py           # Connexion unifiée admin + pilote, déconnexion
    admin.py          # Dashboard admin, page contrôle serveur
    api.py            # API JSON : statut serveur, joueurs, logs
    public.py         # Page publique, inscription pilote, espace pilote
    events_admin.py   # CRUD événements, gestion inscriptions
  services/
    process_manager.py   # Lancement / arrêt / watchdog du serveur
    config_builder.py    # Construction des arguments JSON compressés
    server_config.py     # Lecture/écriture des configs JSON
    discord_notifier.py  # Envoi de notifications Discord
    mailer.py            # Envoi d'emails SMTP en thread daemon
    entry_list.py        # Génération du entry_list.json pour ACE
    event_scheduler.py   # Thread de rappels email pré-événement
    database.py          # Instance SQLAlchemy
    encoder.py           # Encodage zlib/base64 des arguments serveur
  static/              # CSS + JS
  templates/
    base.html            # Layout commun, nav, flash messages
    login.html           # Connexion admin et pilote
    register.html        # Inscription pilote
    public.html          # Page publique (statut + événements)
    admin_dashboard.html # Dashboard admin
    server.html          # Contrôle serveur (tabs : config, logs, etc.)
    pilot_dashboard.html # Espace pilote (mes inscriptions)
    events_admin.html    # Liste des événements (admin)
    event_form.html      # Création / édition événement
    event_detail.html    # Détail événement + gestion inscriptions
    drivers.html         # Liste et approbation des pilotes
  models.py            # Modèles SQLAlchemy : Driver, Event, EventRegistration
translations/          # Fichiers i18n FR / EN (.po → compiler avec compile_mo.py)
logs/                  # Logs applicatifs rotatifs (ignorés par git)
config.py              # Lecture du .env
run.py                 # Point d'entrée Waitress (port 4300, 8 threads)
install.bat            # Installation initiale interactive
start.bat              # Démarrage du panel
update.bat             # Mise à jour depuis GitHub
```

---

## Notes techniques

- Les arguments `-serverconfig` / `-seasondefinition` sont du JSON compressé zlib encodé en base64 (4 octets longueur + payload zlib).
- En mode Race Weekend, le fichier `content/data/race_weekend.seasondefinition` est créé automatiquement si absent ou corrompu (format binaire kspkg).
- Le watchdog tourne en thread daemon : il relance le serveur si le PID disparaît alors que `auto_restart` est actif dans le state file.
- Les notifications Discord utilisent le `User-Agent: DiscordBot` pour contourner le pare-feu Cloudflare.
- Les emails sont envoyés dans des threads daemon pour ne pas bloquer les requêtes HTTP.
- Le scheduler de rappels vérifie toutes les 60 secondes les événements dont la date approche.
- La base SQLite est migrée automatiquement au démarrage (colonnes manquantes ajoutées via `ALTER TABLE`).
- Les sessions admin sont en mémoire (pas en DB) ; les sessions pilote utilisent Flask-Login avec prefixe `d_` pour l'ID utilisateur.

## Licence

[CC BY-NC 4.0](LICENSE) — usage personnel et communautaire libre, usage commercial interdit.
