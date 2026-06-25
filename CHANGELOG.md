# Changelog

### v1.8.1 — 25/06/2026

**Bot TCP multi-serveur**
- Un bot TCP indépendant est démarré pour chaque serveur activé en base de données (au boot et à la création d'un nouveau serveur)
- En mode `docker_split` : chaque bot se connecte au container ACE EVO par son nom (hostname Docker) sur le port interne 9700 — plus de confusion avec les ports host-mappés
- Nouvelle fonction `start_for_server(srv, cfg)` dans `ace_tcp_client.py` — centralisée, appelée depuis `create_app()` et `server_create()`

**Banque de circuits — catalogue complet**
- `_sync_track_meta()` lit désormais `events_practice.json` + `events_race_weekend.json` (36 circuits au lieu des 3 extraits des configs existantes)
- Fallback sur les configs existantes pour les tracks personnalisés non présents dans les fichiers events

**Timing en direct — tours invalides**
- Pattern de log ACE EVO identifié : `[gameplay] [error] Couldn't create lap from opensplits`
- Regex `_RE_LAP_INVALID` dans `ace_tcp_client.py` : détecte l'invalidation via le `carId`, mappe vers le `steam_id`, pose `lap_invalid = True` dans le leaderboard TCP
- Reset automatique à `False` au passage du secteur 0 (nouveau tour)
- Leaderboard `/api/timing` inclut le champ `lap_invalid` par pilote
- `timing.html` : ligne du pilote en rouge + icône ⚠ à côté du nom si tour invalide

**Page Tracks (ex-Circuits)**
- Renommée "Tracks" dans la navigation, la route (`/admin/tracks`) et le template
- Toggle actif/inactif supprimé (ne servait à rien)
- Suppression réservée à la Phase 5 (gestion mods)

**Page Véhicules**
- Toggle actif/inactif supprimé

**Page Timing publique**
- Fusion avec les fonctionnalités admin : la section TCP (statut bot, chat, commandes) n'est visible que pour les admins connectés
- La route `/live` redirige vers `/timing`
- "Live" supprimé du menu déroulant admin

**Documentation**
- Nouveau README avec section captures d'écran (9 screenshots), section Bot TCP dans la configuration
- CHANGELOG complet

**Corrections**
- Création d'un serveur additionnel : détection précoce du mode réseau `host` avec message d'erreur explicite (incompatible avec les port bindings requis pour le multi-serveur)
- Config JSON corrompue : la page principale ne crash plus en 500 — le panel charge avec les valeurs par défaut et affiche un bandeau indiquant le fichier concerné et la ligne/colonne de l'erreur JSON

---

### v1.8.0 — 22/06/2026

**Multi-serveur — Phase 2 : gestion des serveurs depuis le panel**
- Page *Serveurs* (superadmin) : liste, création et suppression de serveurs ACE EVO supplémentaires
- Création d'un nouveau serveur = nouveau container Docker dédié depuis l'image aceserver existante
- Sélecteur de serveur actif dans la barre de navigation (tous les admins)
- Watchdog indépendant par serveur (container_name + http_host par serveur_id)
- Support `SERVER_ID` dans l'entrypoint aceserver pour les containers additionnels

**Multi-serveur — Phase 3 : adaptation routes**
- Toutes les routes admin/API utilisent `session["current_server_id"]` au lieu d'un serveur fixe
- `server_id` FK ajouté à `SessionResult` (migration automatique, NULL pour les résultats existants)
- Webhook `/api/results/ingest?server_id=N` : identifie le serveur source

**Phase 4 — Banque de données véhicules/circuits**
- Synchronisation automatique `CarMeta` au démarrage depuis `cars.json` (94 véhicules, catégories Road/Race/Track, PI, images auto-détectées)
- Synchronisation automatique `TrackMeta` depuis les configs JSON au démarrage (image auto-matchée)
- Page *Véhicules* (admin) : grille avec image, PI, catégorie, filtres, recherche, toggle actif/inactif, upload image (superadmin)
- Page *Circuits* (admin) : grille avec image, layout, longueur, toggle actif/inactif, upload image
- `./media:/panel/media` dans `docker-compose.yml` — images persistées entre les rebuilds

**Page d'accueil publique — refonte multi-serveur**
- Section 2 : grille de cards serveurs (1/2/3 colonnes selon le nombre de serveurs actifs)
- Section 3 : événements en grille pleine largeur (1/2/3 colonnes selon le nombre d'événements)

**Événements à venir — refonte visuelle (dashboard admin + page publique)**
- Cartes portrait « carte de crédit » (min-height 400px) avec photo circuit en haut, date + heure en overlay
- Disposition adaptive : 1 événement → carte paysage pleine largeur ; 2+ → grille de cartes portrait
- Bandeau « En cours » animé (point ambré pulsant) pour les événements démarrés
- Liens intelligents par rôle : admin → inscriptions, pilote → tableau de bord, visiteur → login
- Données pré-calculées en route (jour/mois localisés via `babel.dates`, heure fuseau `PANEL_TIMEZONE`, durée, taux de remplissage) — zéro logique lourde en Jinja2
- Chargement eager des inscriptions via `selectinload` pour éviter le N+1

**Footer global**
- Footer sur toutes les pages : logo, nom, tagline, version + git hash, liens GitHub (dépôt, wiki, bugs, licence MIT)
- Variable `PANEL_GITHUB_URL` dans `.env.example` et `config.py`
- Git hash calculé au démarrage via `subprocess` (silencieux en cas d'échec)

**Nouvelles pages admin**
- Page *Mods* : gestion des mods (placeholder)
- Pages *Serveurs*, *Véhicules*, *Circuits* : intégrées dans le menu de navigation

⚠️ **Rebuild obligatoire** : `docker compose up -d --build`
L'entrypoint du container aceserver a été modifié — l'ancienne image ne supporte pas les serveurs additionnels.

---

### v1.7.2 — 22/06/2026

**Correction**
- `ValueError` au démarrage du panel si une variable de port (`ACESERVER_TCP_PORT`, `ACESERVER_HTTP_PORT`, `MAIL_PORT`) est définie mais vide dans le `.env`

---

### v1.7.1 — 19/06/2026

**Tableau des véhicules**
- Affichage sous forme de pills cliquables avec filtre par groupe (catégorie)
- Nom de voiture splitté proprement depuis le slug ACE EVO
- Sélection/désélection par pill, ballast/restrictor par voiture

**Configuration des sessions**
- Durée standalone (widget HH:MM:SS autonome, plus de layout 3 colonnes cassé)
- `TimeMultiplier` (multiplicateur de temps in-game) ajouté à chaque session
- `MinWaitingForPlayers` / `MaxWaitingForPlayers` uniquement sur la session Course (Race)
- Fix JS : les valeurs numériques dans les `<select>` étaient converties en string — corrigé
- Fix CSS : fond des `<select>` transparent remplacé par fond solide + chevron SVG

**Événement**
- 5 nouveaux types de météo : Nuages épars, Nuages fragmentés, Bruine, Pluie forte, Humide
- Type de serveur (`SelectedServerTypeValue`) : Classé / Non classé
- Réglages voiture (`SelectedTuningTypeValue`) : Autorisés / Interdits

**Backend**
- `load_config()` fusionne automatiquement avec les valeurs par défaut — migration de schéma transparente, aucune action utilisateur requise
- `load_config_by_name()` applique désormais aussi la fusion avec les valeurs par défaut (alignement avec `load_config()`)
- `tuning_type` correctement mappé dans `config_builder.py`
- Champs globaux (`ServerName`, `MaxPlayers`, ports, mots de passe) gérés uniquement via les Paramètres, non écrasés à chaque sauvegarde config

**Corrections**
- `check_config()` lisait la config fusionnée et ne détectait jamais les clés manquantes — corrigé (lecture du JSON brut)
- Mots de passe serveur (`DriverPassword`, `AdminPassword`) impossibles à effacer via les Paramètres — corrigé
- `superadmin_required` : ajout du guard `is_authenticated` pour éviter une AttributeError sur accès anonyme
- Variables d'environnement globales n'étaient plus sauvegardées dans le JSON de config à chaque édition (évite les valeurs obsolètes après rotation des secrets)

**UI globale**
- Sessions en grille 2×2 (Libre/Qualif | Chauffe/Course)
- 246 déclarations `font-size` sous 1rem passées à 1rem dans `main.css`

**i18n**
- Toutes les nouvelles clés traduites dans les 5 langues (fr, en, de, es, it)

---

### v1.7.0 — 10/06/2026

**Nouvelles pages**
- **Timing en direct** (`/timing`) — classement live via l'API TCP du serveur, mis à jour toutes les 15s, accessible publiquement
- **Classement global** (`/leaderboard`) — meilleur tour par voiture sur l'ensemble des résultats importés
- **Live Admin** — contrôle de la session en cours depuis l'interface admin
- **Paramètres** — toutes les variables `.env` éditables depuis l'interface sans accès SSH ; gestion des comptes admin (création, mot de passe, suppression)

**Interface**
- Refonte complète de l'UI : nouvelle navbar, nouveau thème, mise en page repensée sur toutes les pages
- Page d'accueil : 3 colonnes (événements / session en cours / état serveur), sparkline des joueurs, countdown de session
- Page résultats : tri et recherche, groupement visuel par run

**Qualité du code**
- Décorateur `admin_required` centralisé dans `app/utils.py` (supprimé des 3 blueprints)
- `discord_notifier.safe_notify()` — les notifications Discord loggent l'erreur au lieu de la silencer
- `except Exception: pass` remplacés par des `log.warning(...)` explicites
- Imports inline déplacés en tête de fichier dans tous les blueprints
- `server_config.py` : helpers extraits (`_valid_config_name`, `_car_dict`, `_fmt_dur`), validation des champs numériques (`MaxPlayers`, ports)

**Traductions**
- 13 nouvelles clés ajoutées dans les 5 langues (Live, Port TCP/UDP, Ballast, Restrictor, Timing, Classement en direct…)
- Corrections des correspondances fuzzy incorrectes dans le `.po` français

---

### v1.6.0 — 03/05/2026

**Roulement de configs**
- File d'attente de fichiers de configuration : glisser-déposer pour réordonner, case Cycle (retour au premier après le dernier)
- Bouton **Lancer le cycle** : démarre le serveur sur la première config, enchaîne automatiquement à chaque fin de session
- Suivi en temps réel : pill verte (config active → suivante), bouton **Arrêter le cycle**
- Notifications Discord : **Cycle lancé** et **Changement de config** (précédente → nouvelle, mode, circuit, durées)

**Événements — import depuis une config**
- Menu déroulant pour importer un fichier de config existant dans le formulaire d'événement
- Pré-remplit circuit, mode, météo, durées et véhicules (sélection, ballast, restrictor)

---

### v1.5.0 — 02/05/2026

**Groupement des résultats par run**
- `run_id` unique (uuid4) à chaque démarrage — Practice, Qualifying, Warmup, Race d'un même run liés de façon certaine
- Page résultats : sessions regroupées sous un en-tête coloré avec badges de type

**Interface — icônes CSS pures**
- Tous les emojis interceptés par Twemoji remplacés par des icônes CSS pures
- Médailles podium remplacées par des cercles numérotés CSS (or/argent/bronze)

**Traductions** — 39 clés manquantes ajoutées dans les 5 langues

---

### v1.4.0 — 01/05/2026

**Résultats — import et affichage**
- Import automatique via webhook de fin de session, scan du dossier au démarrage
- 4 dernières sessions sur la page d'accueil publique

**Résultats — mode Race**
- Temps total de course, meilleur tour individuel (badge FL), gap en nombre de tours, grille de départ

**Résultats — enrichissements visuels**
- Drapeaux nationaux via Twemoji, table ISO 3166 (50+ pays)
- Secteurs color-codés, gap au leader, consistance pilote

---

### v1.3.0 — 30/04/2026

**Architecture Docker split**
- `Dockerfile.panel` (Flask, sans Wine) + `Dockerfile.aceserver` (Wine + ACE EVO exe)
- Rebuild du panel en ~30s sans interrompre le serveur de jeu
- Volume partagé `/aceserver` pour les configs et résultats

---

### v1.2.0 — 29/04/2026

- Réception des résultats via webhook (`POST /api/results/ingest`)
- Calendrier des événements mensuel avec timeline horaire
- Ballast et Restrictor par voiture, lancement et fin automatiques

---

### v1.1.0

- CSRF, rate limiting, headers sécurité, tokens SHA-256
- Multilingue FR / EN / ES / DE / IT
- Discord pilotes webhook séparé
