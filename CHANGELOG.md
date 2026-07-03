# Changelog

### v1.9.1 — 09/07/2026

**Suppression de la page Administration**

- La page `/administration` est supprimée. Son contenu (config email en lecture seule, test SMTP, test des webhooks Discord, aperçu du design des emails) est déplacé dans Paramètres → Notifications, à côté des réglages correspondants.
- Les routes `/administration/test-email`, `/administration/test-webhook` et `/administration/mail-preview` deviennent `/settings/test-email`, `/settings/test-webhook` et `/settings/mail-preview`.

**Correction**

- Les fichiers `.mo` compilés committés dans git n'étaient plus synchronisés avec leurs `.po` sources depuis plusieurs changements (le conteneur recompile en interne à chaque build Docker, sans jamais remonter le résultat sur le disque hôte). Sans impact sur les déploiements réels (`docker compose up -d --build` recompile toujours les traductions à jour au build), mais corrigé pour la cohérence du dépôt.

### v1.9.0 — 03/07/2026

**Interface modernisée — HTMX + Alpine.js, puis refonte Tailwind CSS**

*Réactivité (HTMX + Alpine.js)*
- Système de toasts unifié : toutes les confirmations d'action apparaissent en haut à droite avec auto-dismiss (4,5 s) et bouton fermer, sans perturber le scroll
- Formulaires Paramètres, boutons de test (email/webhook), publication/refus/suppression d'événements et de pilotes, activation/suppression de serveurs, recherche véhicules : tout soumet désormais en HTMX, sans rechargement de page complet
- Modales (config serveur, comptes administrateurs) : ouverture/fermeture en transitions Alpine.js

*Refonte visuelle complète — Tailwind CSS + Flowbite*
- Remplacement progressif de `main.css` par Tailwind CSS v3.4.14 (build Docker multi-stage avec Flowbite v2.3.0 + @tailwindcss/forms), mode hybride le temps de la migration
- Tous les templates migrés : navigation, authentification, dashboard pilote, administration, événements, véhicules, circuits, timing, résultats
- Nettoyage : `main.css` réduit de 24 % (suppression des sélecteurs morts identifiés lors de l'audit)
- **Breaking** : nécessite un rebuild Docker (`docker compose up -d --build panel`) — la compilation CSS est dans le build

**Audit 6 experts (sécurité / backend / qualité / performance / UI) — corrections**

*Sécurité*
- `SESSION_COOKIE_SECURE`/`MAIL_USE_TLS` corrigés en booléens à la lecture des settings — une valeur texte libre pouvait produire un cookie de session malformé et casser le login sur une install HTTP locale
- 64 attributs `onclick=` convertis en `addEventListener` (10 templates) — corrige les boutons cassés par le CSP `script-src-attr`
- Upload bannière/logo réparé, validation stricte de `copy_from` (path traversal) et `steam_pass`/`guard_code` (injection SteamCMD)
- `load_user` revérifie le statut du pilote à chaque requête ; whitelist des champs `Sessions`, correction IDOR sur `reg_assign_car`, anti-énumération des serveurs désactivés

*Backend & performance*
- `server_delete` stoppe le bot TCP et le watchdog du serveur supprimé (fuite de threads corrigée)
- `start_server`/`stop_server` protégés par verrou par-serveur ; écritures d'état rendues atomiques
- `scan_and_import()` ne reparse plus les fichiers déjà importés ; comptage véhicules en une requête `GROUP BY` au lieu de 9 ; cache sur `is_running()`
- Logique métier extraite des routes vers des services dédiés (`live_state.py`, `steam_updater.py`) ; suppression du template mort `live.html`
- Test de fumée Playwright ajouté (`tests/smoke.spec.js`, `npm run test:smoke`)

**Compte Steam vérifié — pilotes et administrateurs**
- Les pilotes peuvent lier leur compte Steam depuis leur tableau de bord via Steam OpenID (gratuit, sans clé API) : redirection vers Steam, authentification, signature revérifiée côté serveur — impossible d'usurper l'identité d'un autre joueur ou de saisir un SteamID à la main
- Nouvelle page « Mon compte » (`/mon-compte`) pour les admins/superadmins : email et liaison Steam facultatifs, indépendants l'un de l'autre
- Unicité du SteamID vérifiée entre tous les types de comptes (un SteamID ne peut être revendiqué qu'une seule fois, pilote ou admin)
- Migrations DB additives : `driver.steam_id`/`steam_id_confirmed_at`, `admin_account.email`/`steam_id`/`steam_id_confirmed_at`
- Correction d'un bug d'affichage Discord : les embeds « Meilleur tour » affichaient parfois `?` à la place du pilote/de la voiture (fonction d'alimentation du leaderboard TCP jamais appelée)

**Confirmation d'email (facultative)**
- Nouveau réglage `REQUIRE_EMAIL_CONFIRMATION` (Paramètres → Panel, désactivé par défaut) : un email de confirmation est envoyé à l'inscription et le pilote doit cliquer le lien avant de pouvoir s'inscrire à un événement
- Le pilote peut toujours se connecter et consulter son dashboard sans confirmer — seule l'inscription à un événement est bloquée
- Rétrocompatible : les pilotes déjà existants sont automatiquement considérés comme confirmés (grandfathering)
- Migration DB additive : `driver.email_confirmed_at`/`email_confirm_token`/`email_confirm_token_expires`

**Refonte des emails du panel**
- Nouveau design pour les 10 emails (inscription, validation, refus, confirmation, reset mot de passe, rappel événement...) : header avec titre du panel, section « hero » avec photo de circuit, icônes contextuelles, bouton d'action, footer — compatible clients mail (CSS inline, layout en table)
- Carte email posée directement sur le fond du client mail (pas de bande sombre pleine largeur autour)
- Photo de fond en pleine largeur avec texte superposé (au lieu d'une colonne latérale) — fallback VML pour Outlook desktop
- Nouveaux assets embarqués dans l'application (`app/static/mail/`) : photo de fond + 9 icônes contextuelles — disponibles directement après `git pull`, aucune configuration requise
- Page Administration → sélecteur « Aperçu du design » : ouvre le rendu réel de n'importe quel type d'email dans un nouvel onglet, sans envoi ni configuration SMTP requise (aperçu et envoi partagent le même code de rendu)

**Corrections diverses**
- `docker-compose.override.yml` : protégé contre la transformation silencieuse en dossier lors d'un `git pull` sur une install où il n'était plus suivi par git (voir procédure de récupération ci-dessous si déjà touché)
- `event_scheduler.py` : le `db.session.rollback()` du bloc except s'exécutait hors du contexte d'application Flask, provoquant un `RuntimeError` qui masquait l'erreur réelle dans les logs
- Page `/administration` (config email/webhooks, test SMTP, aperçu des emails) désormais accessible depuis le menu Admin — elle n'avait aucun lien nulle part auparavant
- `SERVER_NAME` (nom d'affichage du serveur ACE EVO) n'est plus recopié dans la config Flask interne — cette clé y est réservée pour la génération d'URL, la collision cassait silencieusement les liens absolus (callback Steam OpenID notamment) dès qu'un nom de serveur personnalisé était configuré
- Timeout de connexion SMTP remonté de 8 à 20 secondes — la connexion à certains relais (OVH notamment) peut occasionnellement dépasser 8s, provoquant un échec `Connection unexpectedly closed: timed out` sur un envoi pourtant valide
- `/server` : plantait avec une 500 si `cars.json` ou les fichiers `events_*.json` étaient absents (ex: avant toute installation d'ACE EVO via SteamCMD) — `load_cars()`/`load_events()` dégradent maintenant proprement (liste vide + warning), comme le fait déjà `_sync_car_meta()` pour le même cas
- Page d'accueil : l'image de fond du hero était codée en dur (`banner/hero_banner.png`) au lieu d'utiliser le réglage `PANEL_BANNER_IMG` — cassait le chargement (404 → erreur console) sur toute installation sans ce fichier précis présent dans `media/banner/`

*Si vous êtes déjà touché par le bug `docker-compose.override.yml` transformé en dossier* (message `is a directory` au `docker compose up`/`down`) :
```bash
docker compose down
sudo rm -rf docker-compose.override.yml && touch docker-compose.override.yml
docker compose up -d --build
```

**Mise à jour**
```
git pull
docker compose up -d --build panel
# Migrations DB automatiques au démarrage — aucune action requise
# Nouvelles variables .env optionnelles : voir .env.example (REQUIRE_EMAIL_CONFIRMATION, STEAM_USERNAME)
```

---

### v1.8.3 — 28/06/2026

**Badges multi-propriétés sur la page Véhicules**
- Chaque voiture affiche désormais tous ses badges réels : type de route (Road / Race / Track), époque (Modern / Vintage / Young Timer) et motorisation (ICE / EV / Hybrid), en plus du PI
- Nouvelles colonnes `property_2_label` et `property_3_label` ajoutées à `car_meta` en base (migration automatique)
- `_sync_car_meta()` peuple ces colonnes depuis `cars.json` à chaque démarrage
- 9 nouvelles classes CSS de badges colorés (`veh-badge-modern`, `veh-badge-vintage`, `veh-badge-yt`, `veh-badge-ice`, `veh-badge-ev`, `veh-badge-hybrid`)
- Traductions ajoutées dans les 5 langues (fr / en / de / es / it) pour les labels Road, Track, Modern, Vintage, YT, ICE, EV, Hybrid

**Filtre voitures en logique OR dans la configuration serveur**
- La sélection de catégorie dans l'écran de configuration serveur utilise maintenant une logique **OR globale** : une voiture s'affiche dès qu'un de ses badges correspond à la sélection active, indépendamment de ses autres propriétés
- Une voiture Road + Vintage + Hybrid apparaît si l'un de ces trois badges est activé

**Configuration compatible Portainer (settings.json)**
- Les paramètres sauvegardés via l'UI sont désormais stockés dans `data/settings.json` (volume persistant `panel_data`) au lieu du fichier `.env`
- Compatible avec les déploiements Portainer Stack Deploy et tout environnement qui gère ses propres variables d'environnement de démarrage
- Migration automatique au premier démarrage : les variables configurables du `.env` existant sont exportées dans `settings.json` — aucune action requise pour les utilisateurs existants
- `SECRET_KEY` reste exclusivement dans `.env` (jamais dans `settings.json`)
- Les utilisateurs `docker compose` ne voient aucun changement de comportement

**Mise à jour**
```
git pull
docker compose up -d --build panel
# Migration automatique : settings.json créé depuis .env au premier démarrage
# Migration DB : property_2_label et property_3_label ajoutées à car_meta automatiquement
```

---

### v1.8.2 — 26/06/2026

**Noms de voitures depuis le jeu**
- Nouveau service `app/services/kspkg_reader.py` : lit `content.kspkg` (binaire XOR propriétaire Kunos) et extrait les noms d'affichage officiels des 68 voitures et 95 presets mécaniques
- Chargement lazy au premier appel, mise en cache en mémoire, thread-safe
- Fallback automatique `slug_to_name()` pour les voitures ajoutées dans les futures mises à jour du jeu
- `/api/timing` : chaque entrée du leaderboard inclut désormais `car_display_name` (ex : `"BMW M4 GT3 Evo"` au lieu de `"preset_m4gt3_mech_1"`)
- Page timing publique : colonne *Voiture* affiche le nom officiel

**Cartes de circuit haute résolution**
- 16 SVGs régénérés depuis les `splinedata.json` extraits du `content.kspkg` (centerline officielle Kunos, 337 à 14 739 points de donnée)
- Précision 5× supérieure aux versions précédentes issues des `trackcontrolpoints` (ex : Imola 2 KB → 9,5 KB, Nordschleife 11 567 points)
- Circuits mis à jour : Imola, Monza, Mount Panorama, Nürburgring (24h / GP / Nordschleife / Sprint), Oulton Park (Fosters / International), Paul Ricard (4 layouts), Road Atlanta, Sebring, Watkins Glen GP Inner Loop

**Multi-serveur — rebuild complet (`docker compose up --build`)**
- `docker-compose.override.yml` auto-généré par le panel : tous les serveurs additionnels (id > 1) sont inclus dans la gestion Docker Compose
- Synchronisation automatique au démarrage du panel et à chaque création/suppression de serveur
- Les volumes Wine (`wine_prefix_N`) sont déclarés `external: true` — l'installation Wine est préservée lors du rebuild
- À chaque rebuild, les containers additionnels utilisent automatiquement la nouvelle image `aceserver`

**Git — fin des conflits de `git pull`**
- `aceserver/configs/*.json` retirés du tracking git : plus de conflits entre les configs utilisateur et les mises à jour du repo
- Template `aceserver/configs/default.json.example` fourni pour les nouvelles installations
- Le panel crée `default.json` automatiquement au premier démarrage s'il est absent

**Sécurité (audit interne)**
- XSS : fonction `_esc()` appliquée sur tous les champs injectés via `innerHTML` dans `timing.html` et `live.html` (noms de pilotes, messages chat)
- API publique `/api/timing` : filtrage des champs sensibles (`steam_id`, `car_id`, `joined_ts`) avant la réponse JSON
- Rate limiting ajouté sur `/api/timing` (120/min) et `/api/live/chat-history` (60/min)
- Route `/api/container/info` passée de `@login_required` à `@admin_required`
- Webhooks Discord affichés en `type="password"` dans les Paramètres
- `event_scheduler` : notifications Discord via `safe_notify()` — une erreur Discord n'interrompt plus la boucle

**Performance**
- `Event.confirmed_count` / `pending_count` / `is_full` : ne font plus de requête SQL si `registrations` est déjà chargé — les pages liste utilisent `selectinload(Event.registrations)` (2 requêtes au lieu de N+1)
- `/api/timing` et `/api/live/state` : résultat de `_build_state()` mis en cache 10 s — le parsing des logs Docker (24h) n'est plus rejoué à chaque poll client (toutes les 15s)

**Docker / DevOps**
- `.dockerignore` : ajout de `aceserver/` et `media/` — contexte de build réduit de ~580 MB à ~157 KB (build en ~14 s au lieu de plusieurs minutes)
- `requirements.txt` : toutes les dépendances maintenant pinées à une version exacte
- `Dockerfile.panel` : correction d'un `COPY entrypoint.sh` redondant qui générait un fichier en doublon

---

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
