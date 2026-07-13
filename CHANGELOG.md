# Changelog

### v1.9.4 — 13/07/2026

**Ajout — images véhicules/circuits manquantes (Kyalami, Brands Hatch GP, Audi R8 LMS GT3 Evo II, Datsun 240Z Standard/Tuned, Porsche 935, Porsche 911 GT2 RS Clubsport Evo, KTM X-Bow GT2/GT4, Golf 8 R)**

- Images fournies converties au format et à la convention de nommage attendus (`.webp`, slug exact du circuit/véhicule), circuits redimensionnés à 1920px de large comme les images existantes (les sources faisaient jusqu'à 9 Mo), fichiers originaux supprimés après conversion.
- Bug trouvé au passage : `_sync_track_meta()` ne backfillait jamais l'image d'un circuit **déjà existant** en DB, contrairement à `_sync_car_meta()` qui le fait pour les véhicules — un circuit créé sans image avant l'ajout du fichier correspondant (cas de Kyalami) ne la récupérait donc jamais, même après redémarrage. Corrigé pour que les deux fonctions aient le même comportement.
- Brands Hatch GP avait déjà une image générique (`brands_hatch.webp`, fallback partagé avec Brands Hatch Indy) — mis à jour manuellement vers l'image spécifique désormais disponible (`brands_hatch_gp.webp`), le mécanisme de synchro ne remplaçant jamais une image déjà définie même par une version plus précise.
- Vérifié en conditions réelles (Playwright) : les 8 véhicules et les 2 circuits affichent bien leur nouvelle image sur les pages Véhicules et Classement.
- Bug de doublon trouvé en cours de route : Brands Hatch GP apparaissait deux fois dans le classement. Cause : un fichier de config oublié (`aceserver/configs/server-1/test-config.json`) contenait `"brands_hatch"` (minuscule/underscore) comme valeur de circuit au lieu de `"Brands Hatch"` (casse du catalogue officiel) — `_sync_track_meta()` comparait les circuits par chaîne exacte, donc les deux variantes créaient deux lignes `TrackMeta` distinctes pour le même circuit réel. Corrigé : la déduplication se fait maintenant sur un slug normalisé (insensible à la casse/ponctuation), le nom du catalogue officiel étant toujours préféré. Doublon existant supprimé en base.
- Bug de désalignement trouvé en cours de route (page `/tracks` — signalé par capture d'écran) : la 1re carte de chaque ligne de grille (circuits, véhicules, sessions) était systématiquement plus haute que les suivantes. Cause : une règle CSS générique `.card + .card { margin-top: 16px }`, prévue pour espacer des cartes empilées verticalement, s'appliquait aussi aux cartes utilisées comme éléments de grille (où l'espacement est déjà géré par `gap`) — seule la 1re carte de chaque ligne (sans `.card` précédente dans le DOM) n'avait pas cette marge, la faisant paraître plus grande que ses voisines. Corrigé en neutralisant la marge spécifiquement à l'intérieur d'un conteneur `.grid`.

**Correction — élévation admin du bot ("Aucun mot de passe admin configuré") : bug confirmé, pas une erreur de manipulation**

- Signalé via une issue GitHub : mot de passe admin bien configuré côté serveur, mais le bot refuse de s'élever en admin (config ou page Live) en prétendant qu'aucun mot de passe n'est configuré. Vérifié en conditions réelles — c'est un vrai bug, pas une mauvaise manipulation.
- Cause racine : `_get_active_config_name()` (`ace_tcp_client.py`) était censée lire un marqueur `.active_config` à la racine de `CONFIGS_DIR` pour savoir quelle config est réellement en cours — **ce marqueur n'était écrit nulle part dans tout le code**. La fonction retombait donc systématiquement sur "le premier fichier `.json` par ordre alphabétique" du dossier `CONFIGS_DIR` racine (la bibliothèque de configs disponibles, pas le dossier `server-{id}/` où la config réellement déployée par serveur est écrite), sans lien avec la session réellement lancée ni avec `server_id` — les deux serveurs lisaient toujours le même fichier, ignoré de `server_id`. Si ce fichier "gagnant" par hasard alphabétique n'a pas de mot de passe admin renseigné (ex: un `default.json` générique), l'élévation échoue avec exactement le message remonté dans l'issue, même si la vraie session active en a un.
- Corrigé : la config active est maintenant résolue depuis l'état réel du process manager (`process_manager._read_state(server_id)`, la même source que "quelle config tourne" utilisée ailleurs dans le panel) dans le bon sous-dossier `server-{id}/`. `_get_active_config_name()`/`_read_active_config()` prennent maintenant `server_id` en paramètre.
- Bug multi-serveur associé trouvé et corrigé au passage : la route `/api/live/bot/elevate-admin` (bouton d'élévation de la page Live) n'utilisait aucun `server_id` — elle ciblait donc toujours le serveur 1, quel que soit le serveur réellement sélectionné dans le panel.
- Vérifié en conditions réelles sur les deux serveurs configurés (requêtes HTTP contre le process en cours, avec le vrai bot TCP connecté) : `server_id=1` et `server_id=2` résolvent désormais chacun leur propre config déployée (`server-1/Practice-spa.json` vs `server-2/default.json`), et l'élévation admin aboutit bien pour le serveur réellement sélectionné (log `élévation admin manuelle envoyée (server=1)` / `(server=2)` confirmé pour chacun).

**Correction — les commandes admin (kick, to_pit, skip…) cessaient de fonctionner ~60s après l'élévation**

- Après le fix ci-dessus, toujours signalé par le rapporteur de l'issue : les commandes admin envoyées après élévation manuelle ne fonctionnaient plus. Cause : ACE EVO Server déconnecte le bot toutes les ~60s ("software timeout" — ce bot minimal n'envoie aucun keepalive), et `_connect_loop` ne ré-élève automatiquement en admin à la reconnexion que si `ACE_BOT_IS_ADMIN=true` — une élévation **manuelle** (bouton page Live, avec `ACE_BOT_IS_ADMIN=false`) ne "tenait" donc qu'environ une minute avant de silencieusement redevenir un simple pilote, sans aucune indication dans le panel (le bouton reste affiché comme élevé).
- Corrigé : un flag `manual_admin` mémorise qu'une élévation manuelle a été demandée pour ce serveur ; `_connect_loop` la ré-envoie automatiquement à chaque reconnexion, avec ou sans `ACE_BOT_IS_ADMIN`.
- Vérifié en conditions réelles : élévation manuelle à 02:12:24, reconnexion automatique du bot ~55s plus tard (déconnexion "software timeout"), ré-élévation automatique confirmée dans les logs à 02:13:19 (`élévation admin envoyée (server=1) [ré-élévation manuelle après reconnexion]`) — l'admin reste actif en continu au lieu de retomber après une minute.

**Correction — le bot TCP se déconnectait toutes les ~60 secondes ("software timeout")**

- Cause racine identifiée en instrumentant temporairement la réception réseau : après le handshake initial (`ConnectToServerHandshakeResponse`), ACE EVO Server n'envoie plus rien au bot, et ce client minimal ne renvoie rien non plus tant qu'aucune commande n'est déclenchée — le serveur considère la connexion silencieuse comme morte après ~60s et la coupe (`disconnected due to software timeout`), le bot se reconnectant aussitôt en boucle. C'est ce cycle qui rendait toute élévation admin ou action éphémère (voir les deux corrections ci-dessus).
- Corrigé : en l'absence de tout message serveur pendant 20s, le bot renvoie sa requête de connexion d'origine (`ClientConnectionRequest`, déjà acceptée par le serveur, sans effet de bord visible côté jeu) en guise de heartbeat, avant que le délai de 60s ne soit atteint.
- Vérifié en conditions réelles sur les deux serveurs : connexion stable et sans aucune reconnexion pendant plusieurs minutes consécutives (auparavant coupée toutes les ~60s), statut `connected: true` confirmé via requête HTTP contre le process en cours, aucune régression sur le leaderboard live.

**Nouveau — historique de tours en direct, indépendant de la fin de session**

- Constat : "Derniers résultats" ne se met à jour qu'à la fin d'une session (fichier résultat écrit par ACE EVO Server). En mode Practice continu (`IsCycleEnabled: true`, pas de cycle configuré), le jeu ne termine jamais de session — donc plus aucun résultat n'apparaissait, parfois pendant des semaines, alors que les notifications Discord de meilleur temps continuaient d'arriver (mécanisme totalement séparé, basé sur la surveillance TCP en direct).
- Vérifié en conditions réelles qu'un arrêt manuel du serveur ne résout pas non plus le problème : ACE EVO Server ne répond pas au signal d'arrêt (SIGTERM) envoyé par Docker, qui le tue en SIGKILL après 10s de délai de grâce (`Exited (137)`) sans jamais écrire de résultat.
- Solution : chaque tour roulé est maintenant enregistré en direct via le bot TCP déjà connecté en permanence (même mécanisme que les notifs Discord de meilleur temps), sans attendre la fin d'une session. Nouvelle page **Mes temps** (`/pilot/history`, accessible depuis "Mes inscriptions" pour tout pilote ayant lié son compte Steam) affichant l'historique complet : temps, voiture, circuit, type de roulage.
- Pour rester léger dans la durée : au-delà d'un délai configurable (**Paramètres → Panel → Langue & Fuseau**, `LAP_HISTORY_RETENTION_MONTHS`, défaut 6 mois), l'historique détaillé n'est pas supprimé mais **archivé** — regroupé par mois (pilote/circuit/type de roulage), avec le détail temps + voiture de chaque tour conservé, seul l'horodatage précis étant perdu au profit d'un résumé mensuel compact (meilleur temps, moyenne, nombre de tours).
- Nouvelles tables `lap_record` (détail récent) et `lap_archive` (résumés mensuels compactés), créées automatiquement au démarrage — aucune action requise pour les installations existantes.

**Correction — le toggle "Auto-restart" du widget statut (page Serveur) ne faisait rien**

- `toggleAutoRestart()` (`app.js`) commençait par chercher l'élément `#chk-auto-restart` (la case à cocher de la barre de contrôle) et s'arrêtait immédiatement si absent — hors ce checkbox n'existe pas dans le widget "Auto-restart" du tableau de bord (`#srv-auto-restart-card`), donc le cocher/décocher depuis la page statut n'envoyait jamais la requête à l'API et ne changeait rien en réalité, silencieusement. Le contournement (passer par la configuration) fonctionnait car cette page contient bien `#chk-auto-restart`.
- Corrigé : la fonction gère maintenant les deux emplacements possibles du toggle, sans dépendre de la présence de l'un ou l'autre, et synchronise les deux affichages (case à cocher + libellé) immédiatement après une bascule réussie, sans attendre le prochain rafraîchissement périodique.
- Vérifié en conditions réelles (Playwright, sur le vrai `ace-server`) : avant le fix, aucune requête réseau n'était envoyée en cliquant le toggle du widget statut et l'état revenait à sa valeur d'origine après rechargement de la page ; après le fix, la valeur est bien persistée côté serveur et survit à un rechargement.

**Correction — gap i18n préexistant : plusieurs chaînes `lazy_gettext` jamais traduites**

- La commande d'extraction i18n du projet n'incluait pas le mot-clé `_l` (lazy_gettext), utilisé pour toutes les descriptions de réglages dans `admin.py` construites au chargement du module. Résultat : une partie de ces descriptions (ports serveur, dossiers ACE EVO, labels Actif/Inactif, messages Discord configurables, etc. — 86 chaînes) n'avaient jamais été captées pour traduction et retombaient silencieusement sur le français pour les utilisateurs non-francophones, indépendamment de cette version.
- Corrigé : ré-extraction complète avec le bon mot-clé, traductions ajoutées dans les 5 langues (fr/en/de/es/it). 0 clé vide ou approximative restante dans les 5 catalogues (86 chacun, contre 92 à 97 selon la langue avant correctif).

**Accès admin/superadmin à l'historique de tours + lien navbar**

- `/pilot/history` était réservée aux comptes pilote (`is_pilot`), alors que les comptes admin/superadmin ont eux aussi un `steam_id` lié (même flux Steam OpenID) et peuvent donc avoir des tours enregistrés — ouverte aux deux, avec un lien "Mes temps" ajouté sur `/mon-compte` (équivalent admin de "Mes inscriptions").
- Lien "Mes temps" ajouté dans la barre de navigation (à côté de "Live"), visible pour tout compte connecté ayant un `steam_id` lié, pilote ou admin.

**Refonte — vue "Classement" de la page Résultats : grille par circuit + page détail filtrable**

- L'ancien classement (`/results?v=leaderboard`) affichait une liste accordéon d'une carte par circuit **ayant déjà des résultats** — les circuits jamais roulés n'apparaissaient pas, et il fallait déplier chaque carte pour voir le meilleur temps.
- Remplacé par une grille de cartes photo compactes (une par circuit configuré dans le jeu, **tous circuits confondus** — 37 actuellement), affichant un encadré "TOP 1" avec le meilleur temps directement sur l'image, ou "Aucun résultat" si le circuit n'a jamais été roulé. Circuits avec un temps triés en premier (ordre alphabétique), puis circuits sans résultat (ordre alphabétique) — jamais mélangés par ordre alphabétique pur. Un clic ouvre une page dédiée par circuit (`/results/circuit/<id>`) avec le détail complet et des filtres combinables (catégorie de véhicule, véhicule précis, plage de PI), mis à jour sans rechargement de page (HTMX).
- Rapprochement `TrackMeta ↔ résultats` vérifié fiable par égalité exacte sur `(nom de circuit, layout)` — les deux sources utilisent la même convention de nom verbeuse (confirmé en comparant un fichier résultat réel et la config active).
- Nettoyage : suppression du CSS et du JS d'accordéon devenus inutiles (`.lb-grid`, `.lb-card`, `.lb-detail`, etc. — ~120 lignes mortes), les badges catégorie (Road/Race/Track) réutilisent désormais `.veh-badge-*` (déjà utilisé ailleurs) au lieu de classes `.lb-pi-s/a/b/c/d/x` qui ne correspondaient en réalité à aucune donnée existante (bug d'affichage préexistant, silencieux — le badge PI ne prenait jamais sa couleur).
- Colonnes **Secteur 1 / 2 / 3** ajoutées au tableau de la page détail circuit — la donnée existait déjà dans `results_parser.py` (`best_splits`, calculée pour chaque pilote sur son tour de référence : le meilleur tour en Practice/Qualify, le tour le plus rapide en course) mais n'était jusqu'ici exploitée que sur la page détail d'une session individuelle, pas sur le classement par circuit.
- Corrigé au passage : les filtres (catégorie, véhicule, PI min/max) de la page détail circuit s'étiraient sur toute la largeur au lieu de garder une taille raisonnable — `.form-control` impose `width:100%` en CSS, qui l'emportait sur les classes Tailwind `w-*` à spécificité égale (chargées avant dans la feuille de style). Corrigé en enveloppant chaque champ dans un conteneur de largeur fixe.

**Refonte — onglet "Résultats" de la page Résultats : même style de grille compacte**

- Les cartes de session (dans chaque groupe/événement, structure de regroupement conservée) reprennent le style compact de la nouvelle grille Classement : image de circuit en vignette, encadré "1er · pilote + temps" en overlay, au lieu de l'ancienne carte plus grande avec fond d'image et texte empilé.
- Ordre inchangé (le plus récent en premier — `received_at` décroissant), comme demandé.

**Correction — menu mobile (hamburger) totalement inopérant**

- Le bouton hamburger (`@click="$dispatch('toggle-mobile-nav')"`) n'était rattaché à aucun composant Alpine.js (`x-data`) ancestor — Alpine n'initialise ses directives qu'à l'intérieur d'un arbre `x-data`, donc `@click` n'était jamais lié : clic sans aucun effet, silencieusement, en vue mobile uniquement (le menu desktop ne dépend pas de ce bouton). Corrigé en ajoutant `x-data` directement sur le bouton. Vérifié en conditions réelles (Playwright, viewport 390px) : le menu s'ouvre désormais correctement.
- Liens du menu mobile agrandis (`py-3`/`text-base` au lieu de `py-2`/`text-sm`) pour des cibles tactiles plus confortables. Une refonte plein écran plus ambitieuse a été tentée puis abandonnée : elle causait une page blanche/noire sur téléphone réel (non reproduit en émulation) — reste sur la structure dropdown existante, volontairement inchangée par prudence.

**Correction — gap i18n préexistant : `app/templates/_partials/` jamais scanné par l'extraction**

- Découvert en travaillant sur les traductions ci-dessus : la commande d'extraction pybabel ignore par défaut tout dossier commençant par `_` — **les 8 fichiers de `app/templates/_partials/`** (grille véhicules, listes pilotes en attente/approuvés, lignes serveur/événement, toasts…) n'ont donc jamais été scannés pour traduction, quelle que soit la version. ~23 chaînes concernées, toujours retombées silencieusement sur le français pour les utilisateurs non-francophones.
- Corrigé : ajout du flag `--ignore-dirs='.git'` (qui écrase la valeur par défaut excluant les dossiers `_*`) à la commande d'extraction, traductions ajoutées dans les 5 langues. Commande documentée dans `CLAUDE.md` pour ne pas reproduire l'oubli.

### v1.9.3 — 11/07/2026

> Deux des corrections ci-dessous (rejet du bot, serveur introuvable dans la liste multijoueur) sont directement causées par "la mise à jour du jeu" (build ACE EVO Server 24104623) : bump silencieux de la version de protocole réseau, et validation par Kunos qui filtre les serveurs sur un build trop ancien. Si tu mets à jour ACE EVO Server plus tard et que le bot ou la visibilité multijoueur cassent à nouveau, commence par vérifier ces deux points.

**UI — section "Derniers résultats" de la page d'accueil, clarifiée**

- Le badge "1er/2e/3e/4e" ne représentait pas un classement mais juste le rang de fraîcheur (les 4 dernières sessions affichées, tous types confondus) — visuellement stylé comme un ruban de podium, ça laissait croire à un vrai classement alors que le contenu pouvait venir d'une simple séance de qualification ou d'essais. Remplacé par un badge sémantique qui dit ce qui est réellement affiché : **Vainqueur** (Race), **Pole position** (Qualifying), **Meilleur tour** (Practice/Warmup).
- Ajout du 2e et 3e (nom + écart au 1er, ex. `+0.849` ou `+2 tours` en course) dans un petit encadré à fond flouté sous le nom du vainqueur/pole — mini-podium compact, sans changer le reste de la mise en page (voiture, date, image inchangés).
- 2 nouvelles clés de traduction (Vainqueur, Pole position) dans les 5 langues ; "Meilleur tour" réutilise une clé déjà existante ailleurs dans l'app.

**Correction — le bot admin se faisait rejeter par ACE EVO ("incorrect car or parts")**

- `_get_car_model()` (`ace_tcp_client.py`) choisissait `cars[0]` de la config active — littéralement la première voiture de la liste, sans vérifier si elle était réellement sélectionnée pour la session. Dans l'ordre de la liste de référence (`cars.json`), la première voiture est presque toujours désélectionnée par défaut (ex. `preset_695b_mech_1`, une Abarth 695, alphabétiquement première), donc le bot se connectait quasi systématiquement avec un modèle non autorisé par la session en cours et se faisait rejeter par ACE EVO Server dès la connexion (`Ranked server: incorrect car or parts ..., discarding the connection`) — jamais de chat in-game, jamais de leaderboard temps réel, jamais de notifications de connexion/déconnexion joueur.
- Corrigé : le bot cherche maintenant la première voiture avec `is_selected`/`IsSelected` à `true`, et ne retombe sur `cars[0]` que si aucune voiture n'est sélectionnée (garde-fou, ne devrait jamais arriver en pratique).
- Trouvé en creusant un signalement utilisateur ("serveur introuvable dans la liste multijoueur" — en réalité un problème réseau Docker sans rapport, mais l'investigation a fait remonter ce rejet de connexion bot dans les logs du serveur). Vérifié en conditions réelles : avant le fix, `Ranked server: incorrect car or parts preset_695b_mech_1, discarding the connection` à chaque tentative ; après le fix, le bot choisit `preset_r8gt3_mech_1` (première voiture réellement sélectionnée) et la connexion aboutit (`ace_tcp_client: connecté à ace-server:9700`), plus aucun rejet dans les logs du serveur de jeu.

**Correction — bot rejeté après une mise à jour du serveur de jeu ("ConnectToServerResult_ClientOutdated")**

- Le build ACE EVO Server 24104623 a bumpé la version de protocole interne de 5 à 6. `_build_connection_request()` (`ace_tcp_client.py`) envoyait toujours la version 5, codée en dur — rejeté par le serveur (`Network Version Mismatch. Current: (Server:6, Protocol:8), Requested: (Server:5, Protocol:8)`). Corrigé (`6` au lieu de `5`), avec un commentaire expliquant le contexte pour la prochaine mise à jour qui rebumpera probablement ce numéro. Ce genre de mise à jour côté jeu peut donc casser silencieusement la connexion du bot (chat in-game, leaderboard live, notifications) sans casser le serveur lui-même — à surveiller après chaque mise à jour Steam.

**Investigation — serveur introuvable dans la liste multijoueur du jeu**

Cause réelle trouvée en plusieurs étapes, aucune n'étant un bug du panel proprement dit sauf la dernière :
1. Le build du serveur était en retard (23658359 installé vs 24104623 disponible) — Kunos filtre silencieusement les serveurs sur un build trop ancien de la liste publique, sans jamais renvoyer d'erreur explicite au niveau de l'enregistrement (`MultiplayerServerListRequestRegisterServer` répond `Success: true` même filtré). Résolu par la mise à jour Steam.
2. Après la mise à jour, la synchronisation `CarMeta`/`TrackMeta` (véhicules/circuits) ne se fait qu'au démarrage du panel, jamais automatiquement après une mise à jour Steam — nécessite un redémarrage manuel du panel pour que la nouvelle liste de véhicules/circuits soit prise en compte dans l'UI (97 véhicules et 36 circuits après cette mise à jour, contre 94/35 avant). À automatiser dans une prochaine version (redémarrage auto du panel en fin de mise à jour SteamCMD, ou resynchronisation à chaud sans redémarrage complet).
3. Bug du bot corrigé ci-dessus (version de protocole), trouvé en marge de cette investigation.
4. **Deux serveurs configurés avec le même port HTTP externe (8081)** en base de données — le second serveur ne pouvait jamais démarrer correctement avec une configuration réseau valide tant que le premier occupait ce port. Pas de garde-fou empêchant deux serveurs de partager le même port HTTP à la création — à ajouter dans une prochaine version (même validation que pour les ports TCP/UDP, qui eux sont déjà vérifiés à la création/modification d'un serveur).

### v1.9.2 — 10/07/2026

**Nouveau — support de la nouvelle version du launcher AC EVO Server (véhicules officiels/mods)**

- La nouvelle version du launcher ajoute des véhicules, des circuits, et un tag `is_mod` par véhicule dans `cars.json` (régénéré automatiquement par la mise à jour Steam — aucune action requise). Le panel propage désormais `is_mod`/`IsMod`/`IsModText` dans les configs qu'il écrit (`_car_dict()`), et le schéma de config connaît la nouvelle clé `ShowOnlyOfficial` (`ShowOnlySelected` a son pendant).
- Ajout d'un filtre "Véhicules officiels uniquement" + badge **MOD** sur les deux sélecteurs de véhicules du panel (page Serveur et création/édition d'événement) — le panel a son propre sélecteur, indépendant de celui du launcher.
- Nouveaux véhicules et circuits : rien à faire, ils remontent automatiquement (lecture dynamique de `cars.json`/`events_*.json`). Un nouveau circuit n'aura simplement pas de carte SVG tant que `track_map.py` n'a pas son entrée (nécessite les assets extraits de `content.kspkg`).
- `SelectOnlyOfficialCarsCommand` (présent dans le JSON du launcher) n'est volontairement pas reproduit : c'est un artefact de sérialisation MVVM/WPF du launcher (binding de bouton), sans donnée exploitable côté serveur.

**Nouveau — bandeau "nouvelles variables .env" après une mise à jour**

- Un admin qui se connecte après une mise à jour voit maintenant un bandeau listant les nouvelles variables `.env` introduites depuis sa dernière visite (optionnelles, valeurs par défaut sûres — rien ne casse si elles restent absentes), avec un lien vers Paramètres et un bouton "Compris" qui masque le bandeau définitivement (persisté dans `data/settings.json`, survit aux redémarrages).
- Cette version l'inaugure avec `STEAM_HOME` (voir section DevOps). Pour les prochaines releases : ajouter une entrée dans `NEW_ENV_VARS_BY_VERSION` (`app/routes/admin.py`) à chaque nouvelle clé `.env`, même optionnelle.

**Sécurité**

- `/api/results` et `/api/results/<id>` ne renvoient plus le SteamID64 (`player_id`/`guid`) à un pilote non-admin — n'importe quel compte pilote pouvait auparavant scripter ces routes sur toute la plage d'ID et reconstituer la table SteamID → pseudo de la communauté.
- `deploy_config()` et `save_rotation()` valident maintenant le nom de config (`_valid_config_name()`), comme tous les autres points d'entrée du même genre.
- `server_id` sur `/api/results/ingest` est casté défensivement (un `?server_id=abc` renvoyait un 500 avant la vérification HMAC, renvoie maintenant un 403 propre).

**Multi-serveur**

- `ResultsPostUrl` (générée pour chaque serveur au déploiement de config) porte désormais `?server_id=N` : les résultats du serveur 2+ étaient jusqu'ici attribués au serveur 1 (rotation et historique du mauvais serveur avançaient). Vérifié avec un vrai appel HTTP signé HMAC : `server_id=2` atterrit bien en base avec le bon `server_id`.
- L'auto-launch d'un événement programmé sur un serveur ≠ 1 déploie maintenant la config et annonce le bon port/nom (`deploy_config()` + `tcp_listener`/`udp_listener`/`server_name`), au lieu du port par défaut du serveur 1.
- **Le bouton "Démarrer le roulement" (`/api/rotation/start`) annonçait le port et le nom globaux (`SERVER_TCP_PORT`/`SERVER_NAME`) au lieu de ceux du serveur réellement sélectionné** — signalé par un utilisateur sur GitHub (le nom configuré par-serveur dans Paramètres → Serveur était silencieusement ignoré au démarrage d'un roulement sur un serveur ≠ 1). Le nom par-serveur (`Server.name`, éditable dans Paramètres → Serveur → "Nom du serveur") fonctionnait déjà correctement pour un démarrage normal et pour l'avancement automatique du roulement (webhook) ; seul ce point d'entrée avait été oublié. Même correctif que les deux points ci-dessus : port/nom du `Server` DB passés à `build_launch_args()`. Vérifié par un test qui intercepte les appels (sans toucher aux vrais conteneurs) : le port et le nom du serveur 2 sont bien ceux transmis.
- Un kick/mute/etc. déclenché sur le serveur 2 résout maintenant le nom du pilote sur le bon leaderboard pour l'embed Discord.
- Les webhooks Discord configurés par-serveur (onglet Paramètres → Serveur) sont maintenant pris en compte même depuis les threads du bot TCP (qui n'ont pas de contexte Flask par défaut) — ils retombaient silencieusement sur les webhooks globaux.

**Performance**

- La reconstruction de l'état live (`/timing`) ne rescane plus 24h de logs container à chaque appel : la fenêtre de lecture est bornée au démarrage réel du serveur (sûr par construction — aucun pilote connecté ne peut avoir une ligne de log antérieure au démarrage du container), et le client Docker est réutilisé au lieu d'être recréé à chaque appel.
- Le cache TTL de cet état passe de 10s à 12s pour rester au-dessus du poll client réel (10s) — avant, le cache expirait quasiment à chaque requête.
- Le cache LRU des résultats parsés est aligné sur la taille du plus gros scan existant (2000, au lieu de 200) — au-delà de 200 résultats en base, chaque affichage de `/results` réévinçait et re-parsait en boucle.
- Page d'accueil publique (`/`) : rate limit ajouté (60/min), comme les autres routes publiques.
- Endpoint SSE `/api/live/stream` supprimé : confirmé mort (aucun `EventSource`/extension SSE htmx branchée dessus nulle part dans le projet), il monopolisait un thread Waitress par connexion sans aucun bénéfice actuel.

**Fiabilité**

- Le watchdog (surveillance crash/rotation des serveurs) ne peut plus mourir silencieusement sur une exception imprévue (ex. erreur disque pendant une rotation) — le corps de la boucle est maintenant protégé par un `try/except` qui logue et continue, comme le fait déjà le planificateur d'événements.
- `send_chat()` (bot TCP) ne tient plus le lock partagé pendant l'envoi réseau (`sendall`) — évite un blocage de `is_connected()`/de la reconnexion si le buffer TCP est plein.
- `settings.json` corrompu : `_read_env_file`/`_write_env_file` loguent maintenant un avertissement au lieu d'échouer silencieusement.

**UI / Traductions**

- ~19 clés de traduction manquantes ou vides ajoutées dans les 5 langues (fr/en/de/es/it) : ordinaux (1er/2e/3e/4e), unités de durée (h/j/min), plusieurs libellés de `/timing`, `/results`, `/settings`. Vérifié en navigateur dans les 4 langues non-françaises.
- 11 textes en dur (attributs `aria-label`, `title`, `placeholder`) passés en clés de traduction.
- Les toasts de démarrage/arrêt du cycle de rotation ont leurs propres clés (`cycleStarted`/`cycleStopped`) au lieu de réutiliser celles du serveur (l'utilisateur voyait « Serveur démarré » en lançant un cycle de rotation).
- `car_display_name` échappé avant injection dans le DOM sur `/timing` (principe de précaution — la donnée vient du jeu, pas d'un attaquant HTTP).
- Rebuild Tailwind : les classes `text-inherit`/`underline` (déjà utilisées dans le HTML) manquaient du CSS compilé, qui était simplement périmé.

**Qualité de code**

- Nouvelle suite de tests `tests/unit/` (pytest, `requirements-dev.txt` séparé — non installé dans l'image de production) : parser de résultats, migrations DB, authentification. 18 tests.
- 8 imports morts retirés ; les défauts des messages du bot TCP (dupliqués à 4 endroits) centralisés dans `config.py`.

**DevOps**

- `.env.example` complété : `ACESERVER_HTTP_PORT`, `ACESERVER_TCP_PORT` (déjà lues par `config.py`, non documentées) et `STEAM_HOME` (nouvelle, optionnelle — voir ci-dessous).
- Port HTTP du serveur de jeu dans `docker-compose.yml` : configurable via `ACESERVER_HTTP_PORT` au lieu de codé en dur.
- Montage de la session Steam (`docker-compose.yml`) : nouvelle variable optionnelle `STEAM_HOME`, à définir dans `.env` si le panel est lancé via systemd ou `sudo` sans `-E` (`$HOME` y est vide, ce qui montait un dossier root vide et dégradait silencieusement la mise à jour SteamCMD). Sans action, comportement inchangé (`$HOME` de l'utilisateur courant).
- `CHANGELOG.md` v1.9.1 : ajout d'une ligne « Breaking (URLs) » qui manquait pour le renommage `/administration/*` → `/settings/*`.

**Base de données**

- Nouvel index `ix_event_registration_driver_id` (migration additive, automatique au démarrage — `filter_by(driver_id=...)` était en full-scan sur la page d'accueil, le dashboard pilote, et l'inscription/désinscription aux événements).

Aucune clé `.env` n'est obligatoire pour cette version (toutes ont un défaut sûr). Migration DB automatique au démarrage, comme d'habitude.

### v1.9.1 — 09/07/2026

**Nouveau bouton "Vérifier les mises à jour"**

- Sépare la vérification de version Steam (interroge `app_info_print`, aucun téléchargement, ne touche pas au serveur en cours) de la mise à jour effective. Auparavant, le seul bouton disponible arrêtait le serveur et lançait `app_update` même pour une simple vérification.
- Le résultat de la dernière vérification (build public connu, date) est persisté (`data/steamcmd_last_check.json`, survit aux rebuilds) et affiché sous forme de statut clair : ✓ À jour / ⚠ Mise à jour disponible / Jamais vérifié, avec la vraie date de dernière vérification — auparavant la date affichée provenait du fichier `.acf` local (mis à jour uniquement lors d'une installation effective), donc figée à la dernière install et sans rapport avec une simple vérification.

**Correction — mise à jour SteamCMD pouvait rester bloquée indéfiniment**

- `steamcmd.sh` est un script bash qui re-exec/relance en interne (auto-mise à jour au premier lancement). Le processus tué en cas de blocage (Steam Guard, identifiants refusés, timeout) n'était que le PID direct suivi par `subprocess.Popen` : les processus petits-enfants issus du re-exec restaient orphelins et gardaient le pipe de sortie ouvert, empêchant toute détection de fin de process côté panel. Résultat côté utilisateur : le serveur de jeu restait arrêté et l'appel HTTP finissait en erreur réseau côté navigateur sans jamais recevoir de réponse.
- Le sous-processus est maintenant lancé dans son propre groupe de processus (`start_new_session=True`) et le nettoyage cible tout le groupe (`os.killpg`) plutôt que le seul PID direct.
- `+runscript <fichier>` s'est révélé peu fiable dans cet environnement : l'erreur `Failed to load script file` survenait de façon reproductible dès qu'un login était impliqué, y compris sur un fichier de script valide fraîchement écrit. Remplacé par le mode interactif de SteamCMD (commandes envoyées sur son entrée standard, `steamcmd.sh` lancé sans arguments) — la méthode d'automatisation SteamCMD la plus répandue, validée en test contre le vrai binaire. Bénéfice supplémentaire : les identifiants Steam ne transitent plus par un fichier sur disque ni par les arguments de ligne de commande (visibles via `/proc/<pid>/cmdline`, `ps aux`, etc. sur cette machine partagée).
- Une passe de "préchauffe" (`+quit` en argument direct) absorbe l'auto-mise à jour de SteamCMD avant le vrai script.
- Le flux SSE de vérification transmet maintenant chaque ligne de sortie au navigateur pendant la connexion (auparavant silencieux plusieurs dizaines de secondes, risquant une coupure de connexion par un proxy intermédiaire pour inactivité).
- Extraction du build public corrigée : la réponse `app_info_print` contient plusieurs blocs `"public"` imbriqués (un par dépôt sous `"manifests"`, sans buildid) en plus de celui recherché sous `"branches"`. Le premier reconnu par erreur faisait échouer la détection ("Impossible de déterminer le dernier build"). Le nouveau parseur cible spécifiquement `"branches"."public"."buildid"`.

**Suppression de la page Administration**

- La page `/administration` est supprimée. Son contenu (config email en lecture seule, test SMTP, test des webhooks Discord, aperçu du design des emails) est déplacé dans Paramètres → Notifications, à côté des réglages correspondants.
- Les routes `/administration/test-email`, `/administration/test-webhook` et `/administration/mail-preview` deviennent `/settings/test-email`, `/settings/test-webhook` et `/settings/mail-preview`.
- **Breaking (URLs)** : aucun impact DB ni `.env`, mais tout marque-page ou lien externe pointant vers `/administration/*` casse. Mettre à jour vers `/settings/*`.

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
